"""资金流数据多源 dispatcher — tushare → akshare → ftshare。

三源:
- tushare moneyflow: 主源 (token 全通, 数据丰富)
- akshare stock_individual_fund_flow: 第 2 源 (东财 push2his 域偶发不稳)
- ftshare stock_capital_flows: 第 3 源 (东财源, 提供 main_net_pct 占比, tushare 缺)

N 源 fallback 循环、去重日志、空返回由 _multi_source.try_sources 统一处理。

列级补全 (enrich): tushare moneyflow 不含 close / main_net_pct, 旧实现只做整源替换,
tushare 一旦非空就立即返回, 永远不会调到 akshare/ftshare — 结果这两列恒为 NaN, 被
pit_evidence.validate_flow_artifact fail-closed 拒掉整票缓存刷新 (2026-07-17
出现 63 只票被拒的系统性故障)。fix: tushare 获胜后, 若 close/main_net_pct 存在
NaN, 依次尝试 ftshare → akshare, 按日期匹配只补这两列, 保留 tushare 的金额字段不动。
ftshare 是可选 SDK (不在 PyPI), 生产环境常未安装; akshare 是已安装依赖, 作为
enrich 的可靠兜底。
"""

from __future__ import annotations

import logging

import pandas as pd

from src.tools._multi_source import EMPTY_FUND_FLOW_DF, reorder_sources, try_sources

logger = logging.getLogger(__name__)

# tushare moneyflow schema 里缺失、但 akshare/ftshare 能补上的列。
_ENRICHABLE_FIELDS = ("close", "main_net_pct")


def _fetch_enrich_supplement(
    ticker: str,
    start_date: str,
    end_date: str | None,
) -> pd.DataFrame:
    """合并 ftshare + akshare 两源, 返回 close/main_net_pct 的补全数据。

    两源覆盖区间可能不同 (实测 ftshare 偶尔缺某天, akshare 间歇 ProxyError),
    所以合并而非二选一: ftshare 优先, ftshare 缺的日期用 akshare 补。
    只取 _ENRICHABLE_FIELDS 列返回 (金额列由 base 主源负责, 不从这里取)。

    ftshare: 已安装时稳定 (market.ft.tech 网关), 提供 eastmoney_stock_flow。
    akshare: 东财 push2his 域间歇性 ProxyError (实测 ~60%), 重试一次 (→ ~84%);
    2026-07-17 起东财 WAF 封禁期恶化到 ~100%, 由 akshare_fund_flow 熔断器整批跳过
    (此处同步检查, 省每票 2 次注定失败的调用 + 0.5s 退避)。
    两源都失败时返回空 DataFrame, 调用方按原样保留 base。
    """
    import pandas as pd  # local import, 模块顶部已 import 但显式声明

    supplements: list[pd.DataFrame] = []

    # 1) ftshare (优先)
    try:
        from src.tools.ftshare_api import fetch_individual_fund_flow_ftshare

        supp = fetch_individual_fund_flow_ftshare(ticker, start_date, end_date)
        if supp is not None and len(supp) > 0:
            supplements.append(supp)
    except Exception as exc:  # noqa: BLE001 - ftshare 故障不阻塞, 试 akshare
        logger.debug("[资金流] %s ftshare 补全失败, 试 akshare: %s", ticker, exc)

    # 2) akshare (补 ftshare 缺口; 间歇性 ProxyError, 重试一次; 熔断期整段跳过)
    from src.tools.akshare_fund_flow import circuit_breaker_open

    if circuit_breaker_open():
        logger.debug("[资金流] %s akshare 熔断中, 跳过补全", ticker)
    else:
        for attempt in (1, 2):
            try:
                supp = _try_akshare(ticker, start_date=start_date, end_date=end_date)
                if supp is not None and len(supp) > 0:
                    supplements.append(supp)
                    break
            except Exception as exc:  # noqa: BLE001 - akshare 间歇性故障, 再试一次
                logger.debug("[资金流] %s akshare 补全尝试 %d 失败: %s", ticker, attempt, exc)
            if attempt == 1:
                import time
                time.sleep(0.5)  # 短退避, 缓解 push2his 域瞬时拥塞

    if not supplements:
        return pd.DataFrame()

    # 合并: ftshare 优先 (supplements[0]), akshare 补缺口 (supplements[1])。
    # 只保留 _ENRICHABLE_FIELDS 列 (close/main_net_pct); 金额列由 base 主源负责。
    keep_cols = [f for f in _ENRICHABLE_FIELDS if any(f in s.columns for s in supplements)]
    if not keep_cols:
        return pd.DataFrame()

    # 按 YYYYMMDD 字符串建 key, combine_first: supplements[0] 的 NaN 用 supplements[1] 填。
    normalized = []
    for supp in supplements:
        s = supp.copy()
        s["_date_key"] = _normalize_date_key(s["date"])
        cols = ["_date_key"] + [c for c in keep_cols if c in s.columns]
        normalized.append(s[cols].set_index("_date_key"))
    merged = normalized[0]
    for extra in normalized[1:]:
        merged = merged.combine_first(extra)
    # 返回带 date 列的结构 (下游 _enrich_close_and_main_net_pct 期望 supplement 有 date 列)。
    # _date_key 是 YYYYMMDD 字符串, 转成 pandas datetime 作为 date 列。
    result = merged.reset_index().rename(columns={"_date_key": "date"})
    result["date"] = pd.to_datetime(result["date"], format="%Y%m%d", errors="coerce")
    return result


def _enrich_close_and_main_net_pct(
    base: pd.DataFrame,
    ticker: str,
    start_date: str,
    end_date: str | None,
) -> pd.DataFrame:
    """主源获胜后, 用 ftshare→akshare 补 base 里 close/main_net_pct 的 NaN 格。

    只补 NaN, 不覆盖 base 已有的非 NaN 值; 金额字段 (main_net_inflow 等) 完全不动。
    补全源异常/空/无重叠日期 → 原样返回 base, 永不抛出 (best-effort)。

    Args:
        base: tushare (或其他主源) 返回的非空 DataFrame, 含 date 列。
        ticker: 6 位代码。
        start_date / end_date: 透传给补全源, 保证日期范围一致。

    Returns:
        补全后的 DataFrame (列/schema 与 base 一致); base 本身会被复制, 不被原地修改。
    """
    if base is None or len(base) == 0:
        return base

    enrichable = [f for f in _ENRICHABLE_FIELDS if f in base.columns]
    if not enrichable:
        return base

    # 快路径: 这两列都无 NaN → 不调补全源, 零开销。
    needs_enrich = any(base[f].isna().any() for f in enrichable)
    if not needs_enrich:
        return base

    supplement = _fetch_enrich_supplement(ticker, start_date, end_date)

    if supplement is None or len(supplement) == 0:
        return base

    # 用 YYYYMMDD 字符串作为对齐 key, 把两源按日期合并。
    # combine_first 的语义: base 的 NaN 用 supplement 对应位置填上, 非 NaN 不动;
    # 但也会把 supplement 独有的行 (base 没有的日期) 追加进来 — 这会污染 base 的行集,
    # 所以先 reindex supplement 到 base 的 date_key, 丢弃 base 没有的日期。
    base_norm = base.copy(deep=True).reset_index(drop=True)
    base_norm["_date_key"] = _normalize_date_key(base_norm["date"])
    supp_norm = supplement.copy(deep=True).reset_index(drop=True)
    supp_norm["_date_key"] = _normalize_date_key(supp_norm["date"])

    base_idx = base_norm.set_index("_date_key")
    supp_idx = supp_norm.set_index("_date_key")
    # 关键: 只补 enrichable 列; 金额列完全保留 base 原值; 只用 base 已有的行。
    supp_aligned = supp_idx.reindex(base_idx.index)
    supp_for_combine = supp_aligned[[f for f in enrichable if f in supp_aligned.columns]]
    enriched_cols = base_idx[[f for f in enrichable if f in base_idx.columns]].combine_first(supp_for_combine)
    base_idx[enriched_cols.columns] = enriched_cols
    # reset_index(drop=True) 丢弃临时的 _date_key index, 不把它带回列。
    base_norm = base_idx.reset_index(drop=True)

    filled = sum(
        1
        for f in enrichable
        if base[f].isna().any() and not base_norm[f].isna().any()
    )
    if filled:
        logger.debug(
            "[资金流] %s 补全了 %d/%d 个 NaN 列 (close/main_net_pct, 源: ftshare→akshare)",
            ticker, filled, len(enrichable),
        )
    return base_norm


def _normalize_date_key(series: pd.Series) -> list[str]:
    """把 date Series 归一为 YYYYMMDD 字符串列表, 用于跨源按日期对齐。"""
    as_str = series.astype(str).str.replace("-", "", regex=False).str.strip()
    return [s.split(" ")[0] for s in as_str]


def fetch_individual_fund_flow(
    ticker: str,
    start_date: str = "20200101",
    end_date: str | None = None,
    primary: str = "tushare",
) -> pd.DataFrame:
    """多源拉取个股资金流, tushare 主源 → akshare → ftshare。

    主源获胜后, 若 close/main_net_pct 存在 NaN (tushare moneyflow 的固有限制),
    自动用 ftshare→akshare 按日期补全这两列, 避免被 PIT 校验 fail-closed 拒掉整票。

    Args:
        ticker: 6 位代码
        start_date: YYYYMMDD (tushare 用; akshare 忽略, 返回近期)
        end_date: YYYYMMDD (None = 今天)
        primary: "tushare" (默认) 或 "akshare" — 主源选择

    Returns:
        标准化 DataFrame (date/close/pct_change/main_net_inflow[元]/...);
        所有源均失败时返回空 DataFrame。
    """
    sources = [
        ("tushare", _try_tushare),
        ("akshare", _try_akshare),
        ("ftshare", _try_ftshare),
    ]
    if primary != "tushare":
        sources = reorder_sources(sources, primary)
    df = try_sources(
        sources,
        log_tag="[资金流]",
        label=ticker,
        fetch_args=(ticker, start_date, end_date),
        empty_df=EMPTY_FUND_FLOW_DF,
    )
    if df is None or len(df) == 0:
        return df
    return _enrich_close_and_main_net_pct(df, ticker, start_date, end_date)


def _try_tushare(ticker: str, start_date: str, end_date: str | None) -> pd.DataFrame:
    from src.tools.tushare_fund_flow import fetch_individual_fund_flow_tushare

    return fetch_individual_fund_flow_tushare(ticker, start_date=start_date, end_date=end_date)


def _try_akshare(ticker: str, start_date: str, end_date: str | None) -> pd.DataFrame:
    """akshare fallback. akshare 不支持 start/end date 参数 (只返回近期), 忽略。"""
    from src.tools.akshare_fund_flow import fetch_individual_fund_flow as _ak_fetch

    df = _ak_fetch(ticker)
    if df is not None and len(df) > 0:
        df = df.copy()
        df["date_str"] = df["date"].dt.strftime("%Y%m%d")
        if start_date:
            df = df[df["date_str"] >= start_date]
        if end_date:
            df = df[df["date_str"] <= end_date]
        df = df.drop(columns=["date_str"]).reset_index(drop=True)
    return df


def _try_ftshare(ticker: str, start_date: str, end_date: str | None) -> pd.DataFrame:
    """ftshare 第 3 源: 东财资金流, 提供 main_net_pct 占比 (tushare 缺失)。"""
    from src.tools.ftshare_api import fetch_individual_fund_flow_ftshare

    return fetch_individual_fund_flow_ftshare(ticker, start_date, end_date)
