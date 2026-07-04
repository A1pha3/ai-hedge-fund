import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any

import pandas as pd

from src.data.enhanced_cache import get_enhanced_cache
from src.data.models import FinancialMetrics, InsiderTrade, LineItem, Price
from src.tools.ashare_board_utils import to_tushare_code
from src.tools.tushare_batch_fetch_helpers import fetch_batch_cached_frame
from src.tools.tushare_daily_basic_helpers import (
    load_daily_basic_batch,
    select_latest_daily_basic_row,
)
from src.tools.tushare_daily_gainers_helpers import (
    build_daily_gainer_item,
    build_daily_gainers_with_tushare_data,
    build_stock_basic_maps,
    fallback_trade_date_dataframe,
    fill_missing_pct_change,
)
from src.tools.tushare_financial_metrics_helpers import (
    build_financial_metric_support_maps,
    build_financial_metrics_from_frames,
    fetch_financial_metric_frames,
    resolve_financial_metrics_fetch_limit,
)
from src.tools.tushare_insider_trade_helpers import (
    build_holdertrade_query_kwargs,
    build_insider_trade_from_row,
)
from src.tools.tushare_line_items_helpers import (
    build_line_items_from_frames,
    fetch_line_item_statement_frames,
)
from src.tools.tushare_market_data_helpers import (
    build_index_daily_query_kwargs,
    build_northbound_flow_query_kwargs,
    fetch_sorted_cached_market_frame,
)
from src.tools.tushare_stock_details_helpers import (
    build_default_stock_details,
    build_prices_from_tushare_daily_df,
    build_stock_basic_details,
    build_stock_price_details,
)
from src.tools.tushare_sw_industry_helpers import (
    build_sw_industry_mapping,
    extract_open_trade_dates,
    load_sw_index_classification,
    resolve_cached_sw_industry_mapping,
)

# NS-17 / BH-017 family sibling drain: 本模块是 A 股核心生产数据层
# (价格/财报/daily_basic/涨幅榜/行业/北向资金), 被 main.py / screening / data /
# paper_trading / execution 几乎所有 must-win workflow 调用。此前无 logger,
# 27 处 print() + 3 处 traceback.print_exc() 在 cron/launchd 上下文里不入结构化
# 日志: 限速/重试耗尽静默返回 None → 下游在空数据上打分, TUSHARE_TOKEN 缺失静默
# 返回 [], 运维无法定位"为何这批票数据为空"。
logger = logging.getLogger(__name__)

_pro = None
_pro_lock = threading.Lock()
_stock_name_cache: dict[str, str] = {}
_persistent_cache = get_enhanced_cache()

# Tushare 原始 DataFrame 内存缓存 — 同一次运行内复用，避免多 Agent 并行重复请求
_tushare_df_cache: dict[str, pd.DataFrame] = {}
_tushare_df_cache_lock = threading.Lock()


def _resolve_tushare_df_cache_max_entries() -> int:
    raw_value = os.getenv("TUSHARE_DF_CACHE_MAX_ENTRIES", "256")
    try:
        return max(64, int(raw_value))
    except ValueError:
        return 256


_TUSHARE_DF_CACHE_MAX_ENTRIES = _resolve_tushare_df_cache_max_entries()


def _get_tushare_cached_df(cache_key: str) -> pd.DataFrame | None:
    with _tushare_df_cache_lock:
        cached_df = _tushare_df_cache.pop(cache_key, None)
        if cached_df is None:
            return None
        _tushare_df_cache[cache_key] = cached_df
        return cached_df.copy()


def _store_tushare_cached_df(cache_key: str, df: pd.DataFrame) -> None:
    with _tushare_df_cache_lock:
        if cache_key in _tushare_df_cache:
            _tushare_df_cache.pop(cache_key)
        _tushare_df_cache[cache_key] = df
        while len(_tushare_df_cache) > _TUSHARE_DF_CACHE_MAX_ENTRIES:
            oldest_key = next(iter(_tushare_df_cache))
            _tushare_df_cache.pop(oldest_key)


def _normalize_tushare_cache_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_tushare_cache_value(inner_value) for key, inner_value in sorted(value.items()) if inner_value is not None}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_tushare_cache_value(item) for item in value]
    return value


def _make_tushare_query_cache_key(api_name: str, **kwargs) -> str:
    normalized_payload = {
        "api_name": api_name,
        "params": _normalize_tushare_cache_value(kwargs),
    }
    payload = json.dumps(normalized_payload, sort_keys=True, ensure_ascii=True, default=str)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"tushare_df:{api_name}:{digest}"


def _resolve_tushare_cache_ttl(api_name: str, **kwargs) -> int:
    reference_date = str(kwargs.get("trade_date") or kwargs.get("end_date") or kwargs.get("ann_date") or "")
    today = datetime.now().strftime("%Y%m%d")
    is_historical = bool(reference_date) and reference_date < today

    if api_name in {"daily", "daily_basic", "limit_list_d", "suspend_d", "trade_cal"}:
        return 30 * 86400 if is_historical else 6 * 3600
    if api_name in {"stock_basic", "index_classify", "index_member"}:
        return 7 * 86400
    if api_name in {"fina_indicator", "cashflow", "balancesheet", "income"}:
        return 14 * 86400
    if api_name == "stk_holdertrade":
        return 24 * 3600
    return 24 * 3600


def _get_persisted_tushare_cached_df(cache_key: str) -> pd.DataFrame | None:
    persisted_df = _persistent_cache.get(cache_key)
    if not isinstance(persisted_df, pd.DataFrame):
        return None
    _store_tushare_cached_df(cache_key, persisted_df)
    return persisted_df.copy()


def _is_tushare_rate_limit_error(exc: BaseException) -> bool:
    """检测是否为 Tushare 限速错误 (HTTP 429 / 显式 msg 含 rate limit)。

    Tushare 官方文档：免费用户 ~200 req/min，付费用户 ~10000 req/min。
    限速时服务端通常返回：
      - HTTP 429 Too Many Requests
      - JSON ``code != 0`` 配合 msg 含 "rate" / "limit" / "频率" / "限速" / "too many"
    """
    exc_name = type(exc).__name__
    if exc_name in {"HTTPError", "TooManyRequests", "RequestException"}:
        return True
    msg = str(exc).lower()
    return any(needle in msg for needle in ("rate limit", "too many", "限速", "频率", "rate-limit", "429"))


def _call_tushare_dataframe_api(pro, api_name: str, **kwargs) -> pd.DataFrame | None:
    """调用 Tushare Pro API，带 exponential backoff 重试。

    瞬时错误（网络超时 / 服务端 5xx）通过最多 ``TUSHARE_MAX_RETRIES`` 次
    重试恢复，重试间隔按 base_delay * 2^attempt 秒递增（默认 1s → 2s → 4s）。
    限速错误（HTTP 429 / msg 含 rate limit / 限速）走独立的限速重试通道：
    最多 ``TUSHARE_RATE_LIMIT_MAX_RETRIES`` 次，默认退避 ``TUSHARE_RATE_LIMIT_DELAY``
    秒（默认 30s），加 ±30% jitter 防止并发雪崩。
    非瞬时错误（参数错误 / 数据不存在）不重试，直接返回 None。

    Tushare 限速配额（参考 tushare.pro 文档）：
      - 免费用户：~200 req/min
      - 付费用户：~10000 req/min
    """
    import random

    max_retries = int(os.environ.get("TUSHARE_MAX_RETRIES", "2"))
    base_delay = float(os.environ.get("TUSHARE_RETRY_BASE_DELAY", "1.0"))
    rate_limit_delay = float(os.environ.get("TUSHARE_RATE_LIMIT_DELAY", "30.0"))
    rate_limit_max_retries = int(os.environ.get("TUSHARE_RATE_LIMIT_MAX_RETRIES", "2"))

    api_func = getattr(pro, api_name, None)
    if api_func is None:
        return None

    transient_attempts = 0
    rate_limit_attempts = 0
    # 上限：transient + rate_limit 各自耗尽后退出，避免无限循环
    max_total = max_retries + rate_limit_max_retries + 1
    for _ in range(max_total):
        try:
            return api_func(**kwargs)
        except Exception as e:
            exc_name = type(e).__name__
            # 非瞬时错误不重试（参数错误、数据不存在等）
            non_retryable = ("TypeError", "ValueError", "AttributeError", "KeyError")
            if exc_name in non_retryable:
                logger.warning("[Tushare] API %s 调用失败 (不可重试): %s", api_name, e)
                return None

            is_rate_limit = _is_tushare_rate_limit_error(e)

            if is_rate_limit:
                rate_limit_attempts += 1
                if rate_limit_attempts > rate_limit_max_retries:
                    logger.warning(
                        "[Tushare] API %s 限速重试已用尽 (%d 次): %s",
                        api_name,
                        rate_limit_max_retries,
                        e,
                    )
                    return None
                # 限速退避：默认 30s + ±30% jitter
                delay = rate_limit_delay * (1 + random.random() * 0.3)
                logger.info(
                    "[Tushare] API %s 触发限速 (尝试 %d/%d): %s，%.1fs 后重试...",
                    api_name,
                    rate_limit_attempts,
                    rate_limit_max_retries,
                    e,
                    delay,
                )
                time.sleep(delay)
                continue

            transient_attempts += 1
            if transient_attempts > max_retries:
                logger.warning(
                    "[Tushare] API %s(%s) 调用失败 (已重试 %d 次): %s",
                    api_name,
                    kwargs,
                    max_retries,
                    e,
                )
                return None
            # 常规指数退避 (base_delay * 2^(attempt-1)) + ±30% jitter
            delay = base_delay * (2 ** (transient_attempts - 1)) * (1 + random.random() * 0.3)
            logger.info(
                "[Tushare] API %s 调用失败 (尝试 %d/%d): %s，%.1fs 后重试...",
                api_name,
                transient_attempts,
                max_retries + 1,
                e,
                delay,
            )
            time.sleep(delay)

    return None


def _persist_tushare_dataframe_result(cache_key: str, df: pd.DataFrame, *, api_name: str, ttl: int | None, **kwargs) -> pd.DataFrame:
    _store_tushare_cached_df(cache_key, df)
    _persistent_cache.set(
        cache_key,
        df,
        ttl=ttl if ttl is not None else _resolve_tushare_cache_ttl(api_name, **kwargs),
    )
    return df.copy()


def _cached_tushare_dataframe_call(pro, api_name: str, dedupe: bool = False, ttl: int | None = None, **kwargs) -> pd.DataFrame | None:
    """带进程内 + 持久化缓存的通用 Tushare DataFrame 调用。"""
    cache_key = _make_tushare_query_cache_key(api_name, **kwargs)

    cached_df = _get_tushare_cached_df(cache_key)
    if cached_df is not None:
        return cached_df

    persisted_df = _get_persisted_tushare_cached_df(cache_key)
    if persisted_df is not None:
        return persisted_df

    df = _call_tushare_dataframe_api(pro, api_name, **kwargs)

    if dedupe and df is not None and not df.empty:
        df = _dedupe_tushare_df(df)

    if df is not None:
        return _persist_tushare_dataframe_result(
            cache_key,
            df,
            api_name=api_name,
            ttl=ttl,
            **kwargs,
        )

    return None


def _cached_tushare_call(pro, api_name: str, ts_code: str, limit: int, dedupe: bool = False) -> pd.DataFrame | None:
    """
    带内存缓存的 Tushare API 调用。

    同一 ts_code + api_name 的首次调用会实际请求 Tushare，后续直接从内存返回。
    limit 取已缓存和请求中的较大值，确保不会因 limit 不同而丢失数据。
    重新获取失败时，保留已有的有效缓存（防止空数据覆盖有效数据）。
    """
    return _cached_tushare_dataframe_call(pro, api_name, ts_code=ts_code, limit=limit, dedupe=dedupe)


def _get_pro():
    """初始化并返回 Tushare Pro 实例（线程安全）。"""
    global _pro
    if _pro is not None:
        return _pro

    with _pro_lock:
        # Double-check after acquiring lock
        if _pro is not None:
            return _pro

        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            return None

        raw_timeout = os.getenv("TUSHARE_TIMEOUT", "120")
        try:
            timeout = int(raw_timeout)
        except ValueError:
            timeout = 120

        try:
            import tushare as ts

            # 直接使用 token 创建 pro_api，避免写入文件
            try:
                _pro = ts.pro_api(token=token, timeout=timeout)
            except TypeError:
                # 旧版 tushare 不支持 timeout 参数
                _pro = ts.pro_api(token=token)
            return _pro
        except ImportError:
            # tushare 未安装是 dev box 的预期状态, 静默
            return None
        except Exception as e:
            # NS-17 / BH-017 family sibling: 此处是 backfill/daily_pipeline 用的
            # tushare pro_api 单例初始化路径 (非 provider 路径), 与
            # src/data/providers/tushare_provider.py:_init_tushare 同族。token
            # revoked / runtime schema change / 网络错误等非 ImportError 失败
            # 之前被静默吞成 return None — 调用方看到 `if not pro: return None`
            # 时无法区分 "未配置 TUSHARE_TOKEN" 与 "已配置但失效"。surface 到
            # logger.warning 让 operators 能从结构化日志定位单例 init 失败原因。
            logger.warning(
                "Tushare _get_pro 单例初始化失败 (非 ImportError): %s",
                e,
                exc_info=True,
            )
            return None


def _to_ts_code(ticker: str) -> str:
    """
    转换为 Tushare 代码格式
    """
    return to_tushare_code(ticker)


def get_stock_name(ticker: str) -> str:
    """
    获取 A 股股票名称

    Args:
        ticker: 股票代码

    Returns:
        str: 股票名称，如果获取失败则返回股票代码
    """
    if ticker in _stock_name_cache:
        return _stock_name_cache[ticker]

    pro = _get_pro()
    if not pro:
        return ticker

    try:
        ts_code = _to_ts_code(ticker)
        df = _cached_tushare_dataframe_call(pro, "stock_basic", ts_code=ts_code, fields="ts_code,name")
        if df is not None and not df.empty:
            name = str(df.iloc[0]["name"])
            _stock_name_cache[ticker] = name
            return name
    except Exception as exc:
        # NS-17/BH-017 同族 (c274): c306 drain 漏网 — stock_basic 查询失败静默
        # pass 会让运维无法区分 "ticker 无对应 stock_basic 记录" (合法) 与
        # "tushare API 抖动 / token 失效" (需运维介入)。debug 级别 (展示用途,
        # 非决策链, 有 _stock_name_cache 减少 hot path 噪声)。
        logger.debug(
            "get_stock_name stock_basic query failed (ticker=%s, fallback to ticker): %s",
            ticker,
            exc,
        )

    return ticker


def get_ashare_prices_with_tushare(ticker: str, start_date: str, end_date: str) -> list[Price]:
    """
    使用 Tushare 获取 A 股价格数据
    """
    pro = _get_pro()
    if not pro:
        logger.warning("[Tushare] 未初始化，检查 TUSHARE_TOKEN")
        return []
    try:
        ts_code = _to_ts_code(ticker)
        start_fmt = start_date.replace("-", "")
        end_fmt = end_date.replace("-", "")
        logger.debug(
            "[Tushare] 调用 daily API: ts_code=%s, start_date=%s, end_date=%s",
            ts_code,
            start_fmt,
            end_fmt,
        )
        df = _fetch_tushare_ashare_prices_df(pro, ts_code, start_fmt, end_fmt)
        logger.debug("[Tushare] 返回数据: %s", df.shape if df is not None else "None")
        prices = build_prices_from_tushare_daily_df(df)
        logger.debug("[Tushare] 成功获取 %d 条数据", len(prices))
        return prices
    except Exception as e:
        logger.error("[Tushare] 获取价格数据失败: %s", e, exc_info=True)
        return []


def _fetch_tushare_ashare_prices_df(pro, ts_code: str, start_fmt: str, end_fmt: str) -> pd.DataFrame | None:
    """Fetch A-share daily OHLCV with forward-adjustment (前复权 qfq).

    R37: previously used ``pro.daily`` which returns **unadjusted** (不复权)
    prices. Across any ex-dividend day (送股/分红/配股) the raw close gaps down,
    fabricating a phantom loss that corrupts return/ATR/stop-loss/drawdown
    computations — the dominant backtest-validity bug for A-shares. qfq
    (前复权) eliminates the dividend gap so realized returns are clean; the
    adjustment is on price levels only and does not change return *structure*
    (stop-loss/ATR logic is unaffected).

    Implementation: ``ts.pro_bar(adj=...)`` is Tushare's adjustment helper but
    it internally calls ``DataFrame.fillna(method=...)`` which is removed in
    pandas 2.x/3.x (raises ``TypeError`` → ``OSError``), making it unusable in
    this environment. Instead we fetch ``pro.daily`` + ``pro.adj_factor`` (both
    standard ``pro`` methods, cached/retried via ``_cached_tushare_dataframe_call``)
    and apply forward-adjustment manually:
        price_qfq = price_raw * adj_factor / adj_factor_latest
    This is exactly the qfq definition (anchor the latest price, scale history).
    If ``adj_factor`` fetch fails, fall back to raw ``daily`` (degrade gracefully
    rather than return no data — a backtest with unadjusted prices is still
    runnable, just less accurate on ex-dividend days).
    """
    raw_df = _cached_tushare_dataframe_call(
        pro,
        "daily",
        ts_code=ts_code,
        start_date=start_fmt,
        end_date=end_fmt,
    )
    if raw_df is None or raw_df.empty:
        return raw_df

    adj_df = _cached_tushare_dataframe_call(
        pro,
        "adj_factor",
        ts_code=ts_code,
        start_date=start_fmt,
        end_date=end_fmt,
    )
    if adj_df is None or adj_df.empty:
        # adj_factor unavailable → return raw (degrade, don't block the backtest).
        return raw_df

    return _apply_qfq_adjustment(raw_df, adj_df)


def _apply_qfq_adjustment(raw_df: pd.DataFrame, adj_df: pd.DataFrame) -> pd.DataFrame:
    """Apply forward-adjustment (前复权) to a raw daily frame using adj_factor.

    qfq anchors the LATEST price and scales history: price_qfq = price_raw *
    adj_factor / adj_factor_latest. Only OHLC columns are scaled; volume is
    left as-is (volume adjustment is a separate concern and the backtest does
    not compute returns from volume). Rows are matched on trade_date.

    Preserves the input ``raw_df`` row order (Tushare ``daily`` returns latest-
    first; callers like ``get_ashare_prices_with_tushare`` reverse it). See R37.
    """
    adj = adj_df.sort_values("trade_date").reset_index(drop=True)
    # adj_factor_latest = the factor on the chronologically latest trade date.
    latest_adj = adj["adj_factor"].iloc[-1] if not adj.empty else None
    if latest_adj is None or pd.isna(latest_adj) or float(latest_adj) == 0:
        return raw_df
    adj_map = dict(zip(adj["trade_date"].astype(str), adj["adj_factor"].astype(float)))
    result = raw_df.copy()
    ratios = []
    for td in result["trade_date"].astype(str):
        af = adj_map.get(td)
        ratios.append((af / float(latest_adj)) if af is not None and af != 0 else 1.0)
    ratio = pd.Series(ratios, index=result.index)
    for col in ("open", "high", "low", "close"):
        if col in result.columns:
            result[col] = (result[col].astype(float) * ratio).round(2)
    return result


def get_ashare_daily_gainers_with_tushare(trade_date: str, pct_threshold: float = 3.0, include_name: bool = True) -> list[dict]:
    """
    使用 Tushare 获取指定交易日涨幅超过阈值的 A 股列表
    """
    pro = _get_pro()
    if not pro:
        logger.warning("[Tushare] 未初始化，检查 TUSHARE_TOKEN")
        return []
    try:
        trade_fmt = _normalize_tushare_trade_date(trade_date)
        return build_daily_gainers_with_tushare_data(
            pro=pro,
            trade_fmt=trade_fmt,
            pct_threshold=pct_threshold,
            include_name=include_name,
            fetch_dataframe=_cached_tushare_dataframe_call,
            fallback_trade_date_dataframe_fn=fallback_trade_date_dataframe,
            fill_missing_pct_change_fn=fill_missing_pct_change,
            build_stock_basic_maps_fn=build_stock_basic_maps,
            build_daily_gainer_item_fn=build_daily_gainer_item,
        )
    except Exception as e:
        logger.error("[Tushare] 获取涨幅榜失败: %s", e, exc_info=True)
        return []


def _normalize_tushare_trade_date(trade_date: str) -> str:
    return trade_date.replace("-", "")


def _validate_margin(value: float | None) -> float | None:
    """验证利润率数据，过滤异常值（利润率应在 -100% 到 100% 之间）"""
    if value is None:
        return None
    if value < -1.0 or value > 1.0:
        return None
    return value


def _validate_roe(value: float | None) -> float | None:
    """验证 ROE 数据，过滤异常值（ROE 应在 -200% 到 200% 之间）"""
    if value is None:
        return None
    if value < -2.0 or value > 2.0:
        return None
    return value


def _dedupe_tushare_df(df: pd.DataFrame, date_col: str = "end_date") -> pd.DataFrame:
    """去重 Tushare 返回的 DataFrame：同一 end_date 可能有多行（如数据修正）。

    策略：对每个 end_date 保留非 NaN 字段最多的那一行。
    这样可避免 iloc[0] 取到字段缺失较多的行。
    """
    if df is None or df.empty or date_col not in df.columns:
        return df
    # 计算每行的非NaN字段数
    df = df.copy()
    df["_non_null_cnt"] = df.drop(columns=[date_col], errors="ignore").notna().sum(axis=1)
    # 按 end_date 分组，保留非NaN最多的行
    df = df.sort_values([date_col, "_non_null_cnt"], ascending=[True, False])
    df = df.drop_duplicates(subset=[date_col], keep="first")
    df = df.drop(columns=["_non_null_cnt"])
    # 恢复原始排序（按 end_date 降序）
    return df.sort_values(date_col, ascending=False).reset_index(drop=True)


def _get_latest_daily_basic(pro, ts_code: str, anchor_date: str, lookback_days: int = 30) -> dict | None:
    """获取指定日期（含）之前最近一个交易日的 daily_basic 数据行。

    返回包含 total_mv, pe, pe_ttm, pb, ps, ps_ttm 等字段的 dict，
    如果找不到数据则返回 None。
    内置内存缓存：同一 ts_code 批量获取一次 daily_basic，后续按日期过滤。
    """
    batch_cache_key = f"{ts_code}_daily_basic_batch"
    df_batch = load_daily_basic_batch(
        pro=pro,
        ts_code=ts_code,
        anchor_date=anchor_date,
        cache_key=batch_cache_key,
        get_cached_df=_get_tushare_cached_df,
        store_cached_df=_store_tushare_cached_df,
    )
    return select_latest_daily_basic_row(df_batch, anchor_date)


def _load_tushare_financial_metric_frames(pro, ts_code: str, *, limit: int, period: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    fetch_limit = resolve_financial_metrics_fetch_limit(limit, period)
    financial_fetch_limit = limit * 4
    return fetch_financial_metric_frames(
        _cached_tushare_call,
        _cached_tushare_dataframe_call,
        pro,
        ts_code,
        fetch_limit,
        financial_fetch_limit,
    )


def _build_tushare_financial_metrics(
    *,
    ticker: str,
    end_date: str,
    limit: int,
    period: str,
    pro,
    ts_code: str,
    df_fin: pd.DataFrame,
    df_cash: pd.DataFrame | None,
    df_bal: pd.DataFrame | None,
    df_income: pd.DataFrame | None,
) -> list[FinancialMetrics]:
    fcf_values, raw_income_map, ttm_income_map = build_financial_metric_support_maps(df_fin, df_cash, df_income)
    return build_financial_metrics_from_frames(
        ticker=ticker,
        end_date=end_date,
        limit=limit,
        period=period,
        pro=pro,
        ts_code=ts_code,
        df_fin=df_fin,
        df_cash=df_cash,
        df_bal=df_bal,
        df_income=df_income,
        fcf_values=fcf_values,
        raw_income_map=raw_income_map,
        ttm_income_map=ttm_income_map,
        get_latest_daily_basic=_get_latest_daily_basic,
        validate_margin=_validate_margin,
        validate_roe=_validate_roe,
    )


def get_ashare_financial_metrics_with_tushare(ticker: str, end_date: str, limit: int = 10, period: str = "ttm") -> list[FinancialMetrics]:
    """
    使用 Tushare 获取 A 股财务指标

    Args:
        period: "ttm" (默认, 返回所有季度含TTM合成) | "annual" (仅返回年报 1231) | "quarterly" (仅返回季报)
    """
    pro = _get_pro()
    if not pro:
        return []
    try:
        ts_code = _to_ts_code(ticker)
        df_fin, df_cash, df_bal, df_income = _load_tushare_financial_metric_frames(
            pro,
            ts_code,
            limit=limit,
            period=period,
        )
        if df_fin is None or df_fin.empty:
            return []
        return _build_tushare_financial_metrics(
            ticker=ticker,
            end_date=end_date,
            limit=limit,
            period=period,
            pro=pro,
            ts_code=ts_code,
            df_fin=df_fin,
            df_cash=df_cash,
            df_bal=df_bal,
            df_income=df_income,
        )
    except Exception as e:
        logger.error("[Tushare] 获取财务指标失败: %s", e, exc_info=True)
        return []


def get_ashare_market_cap_with_tushare(ticker: str, end_date: str) -> float | None:
    """
    使用 Tushare 获取 A 股市值。
    优先使用 _get_latest_daily_basic 缓存（与 get_financial_metrics 共享）。
    """
    pro = _get_pro()
    if not pro:
        return None
    try:
        ts_code = _to_ts_code(ticker)
        # 优先从 daily_basic 缓存获取市值
        daily_data = _get_latest_daily_basic(pro, ts_code, end_date)
        if daily_data:
            mv = daily_data.get("total_mv")
            if mv is not None and not pd.isna(mv):
                return float(mv) * 10000
        return None
    except Exception as e:
        logger.error("[Tushare] 获取市值失败(%s): %s", ticker, e, exc_info=True)
        return None


def _load_tushare_line_item_frames(pro, ts_code: str, *, limit: int) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    return fetch_line_item_statement_frames(
        _cached_tushare_call,
        pro,
        ts_code,
        limit * 4,
    )


def _build_tushare_line_items(
    *,
    ticker: str,
    line_items: list[str],
    period: str,
    limit: int,
    df_fin: pd.DataFrame,
    df_bal: pd.DataFrame | None,
    df_cash: pd.DataFrame | None,
    df_income: pd.DataFrame | None,
    as_of_date: str | None = None,
) -> list[LineItem]:
    return build_line_items_from_frames(
        ticker=ticker,
        line_items=line_items,
        period=period,
        limit=limit,
        df_fin=df_fin,
        df_bal=df_bal,
        df_cash=df_cash,
        df_income=df_income,
        as_of_date=as_of_date,
    )


def _resolve_tushare_line_items(
    *,
    pro,
    ticker: str,
    line_items: list[str],
    period: str,
    limit: int,
    as_of_date: str | None = None,
) -> list[LineItem]:
    ts_code = _to_ts_code(ticker)
    df_fin, df_bal, df_cash, df_income = _load_tushare_line_item_frames(
        pro,
        ts_code,
        limit=limit,
    )
    if df_fin is None or df_fin.empty:
        return []
    return _build_tushare_line_items(
        ticker=ticker,
        line_items=line_items,
        period=period,
        limit=limit,
        df_fin=df_fin,
        df_bal=df_bal,
        df_cash=df_cash,
        df_income=df_income,
        as_of_date=as_of_date,
    )


def get_ashare_line_items_with_tushare(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[LineItem]:
    """
    使用 Tushare 获取 A 股财务项目数据

    将 Tushare 的财务指标数据映射为 LineItem 格式。

    ``end_date`` 作为 point-in-time ``as_of`` 锚点传到
    ``build_line_items_from_frames``（R74）：一个 ann_date 严格晚于 ``end_date``
    的报告被视为 look-ahead 并剔除（仅在 balancesheet/cashflow/income/
    fina_indicator frames 含 ann_date 列时生效；缺失 ann_date 时保持 live 行为）。
    """
    pro = _get_pro()
    if not pro:
        return []

    try:
        return _resolve_tushare_line_items(
            pro=pro,
            ticker=ticker,
            line_items=line_items,
            period=period,
            limit=limit,
            as_of_date=end_date,
        )
    except Exception as e:
        logger.error("[Tushare] 获取财务项目失败: %s", e, exc_info=True)
        return []


def _load_tushare_insider_trade_frame(pro, ts_code: str, end_date: str, start_date: str | None) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "stk_holdertrade",
        **build_holdertrade_query_kwargs(ts_code, end_date, start_date),
    )


def _build_tushare_insider_trades(ticker: str, df: pd.DataFrame, *, limit: int) -> list[InsiderTrade]:
    if "ann_date" in df.columns:
        df = df.sort_values("ann_date", ascending=False)
    return [build_insider_trade_from_row(ticker, row) for _, row in df.head(limit).iterrows()]


def get_ashare_insider_trades_with_tushare(ticker: str, end_date: str, start_date: str | None = None, limit: int = 100) -> list[InsiderTrade]:
    """
    使用 Tushare stk_holdertrade 获取 A 股股东增减持数据

    Args:
        ticker: 股票代码 (如 600567)
        end_date: 结束日期 (YYYY-MM-DD)
        start_date: 开始日期 (YYYY-MM-DD), 可选
        limit: 最大记录数

    Returns:
        List[InsiderTrade]
    """
    pro = _get_pro()
    if not pro:
        return []
    try:
        ts_code = _to_ts_code(ticker)
        df = _load_tushare_insider_trade_frame(pro, ts_code, end_date, start_date)
        if df is None or df.empty:
            return []
        return _build_tushare_insider_trades(ticker, df, limit=limit)
    except Exception as e:
        logger.error("[Tushare] 获取股东增减持数据失败: %s", e, exc_info=True)
        return []


def _load_tushare_stock_basic_details(pro, ts_code: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "stock_basic",
        ts_code=ts_code,
        fields="ts_code,name,area,industry,market,list_date",
    )


def _load_tushare_stock_price_details(pro, ts_code: str, trade_date: str | None) -> pd.DataFrame | None:
    daily_kwargs: dict[str, Any] = {
        "ts_code": ts_code,
        "fields": "trade_date,close,pre_close,pct_chg",
    }
    if trade_date is None:
        daily_kwargs["limit"] = 1
    else:
        daily_kwargs["trade_date"] = trade_date
    return _cached_tushare_dataframe_call(pro, "daily", **daily_kwargs)


def get_stock_details(ticker: str, trade_date: str | None = None) -> dict:
    """
    获取股票详细信息，包括基本信息和最新价格数据

    Args:
        ticker: 股票代码（如 000807）
        trade_date: 交易日期（如 20260302），默认为最新日期

    Returns:
        dict: 股票详细信息，包含以下字段：
              - name: 股票名称
              - area: 地域
              - industry: 所属行业
              - market: 市场类型
              - list_date: 上市日期
              - pct_chg: 涨幅（%）
              - pre_close: 昨日收盘价
              - close: 今日收盘价
              字段不存在则为 N/A
    """
    pro = _get_pro()
    if not pro:
        return build_default_stock_details(ticker)

    try:
        ts_code = _to_ts_code(ticker)
        df_basic = _load_tushare_stock_basic_details(pro, ts_code)
        df_daily = _load_tushare_stock_price_details(pro, ts_code, trade_date)

        return {
            **build_stock_basic_details(ticker, df_basic),
            **build_stock_price_details(df_daily),
        }
    except Exception as e:
        logger.error("[Tushare] 获取股票详细信息失败 (%s): %s", ticker, e, exc_info=True)
        return build_default_stock_details(ticker)


# ============================================================================
# 以下为机构级多策略框架（Phase 0.2）新增接口
# ============================================================================

# 全量 stock_basic 缓存
_stock_basic_cache: pd.DataFrame | None = None
_stock_basic_cache_lock = threading.Lock()

# 申万行业分类缓存
_sw_industry_cache: dict[str, str] | None = None
_sw_industry_cache_lock = threading.Lock()


def _fetch_tushare_all_stock_basic(pro) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "stock_basic",
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,area,industry,market,list_date,list_status,is_hs",
        ttl=7 * 86400,
    )


def get_all_stock_basic() -> pd.DataFrame | None:
    """
    获取全 A 股基本信息（代码/名称/上市日期/行业/市场/状态）。

    返回 DataFrame 列: ts_code, symbol, name, area, industry, market,
                       list_date, list_status, is_hs
    结果全局缓存，同一进程内仅调用一次。
    """
    global _stock_basic_cache

    pro = _get_pro()
    if pro is None:
        return None

    # Double-checked locking: fast path (read lock) + slow path (write lock)
    with _stock_basic_cache_lock:
        if _stock_basic_cache is not None:
            return _stock_basic_cache.copy()

        try:
            df = _fetch_tushare_all_stock_basic(pro)
            if df is None or df.empty:
                return None
            _stock_basic_cache = df
            return df.copy()
        except Exception as e:
            logger.error("[Tushare] get_all_stock_basic 失败: %s", e, exc_info=True)
            return None


def _normalize_compact_date(raw: object) -> str | None:
    """Normalize a date-like cell to compact ``YYYYMMDD`` for integer comparison.

    Accepts ``YYYY-MM-DD`` / ``YYYY/MM/DD`` / ``YYYYMMDD`` / ``datetime`` /
    ``NaT``. Returns ``None`` when the value is empty, NaN, or unparseable —
    callers treat ``None`` as "unknown" and decide conservatively per field
    (list_date unknown → exclude; delist_date unknown → treat as not-yet-delisted).
    Parity with R41 ``_normalize_compact_date`` in tushare_financial_metrics_helpers."""
    if raw is None:
        return None
    if isinstance(raw, float) and pd.isna(raw):
        return None
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return None
    # Accept YYYY-MM-DD / YYYY/MM-DD etc. — strip non-digits.
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) != 8:
        return None
    return digits


def filter_stock_basic_as_of(
    stock_basic: pd.DataFrame,
    *,
    as_of: str | None,
    return_audit: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, int]]:
    """R42 survivorship-bias fix: filter a stock_basic universe to the subset
    that was actually listed and not-yet-delisted on ``as_of``.

    The current ``_fetch_tushare_all_stock_basic`` requests ``list_status="L"``
    (currently listed), which silently drops every stock that delisted before
    *today*. A historical backtest for trade date T therefore cannot pick a
    name that delisted after T but before today — even though that name was
    alive and tradeable on T. That is survivorship bias: it beautifies backtest
    returns because the eventual losers can never be selected.

    This pure filter takes a stock_basic-shaped DataFrame (with ``list_date``
    and, when available, ``delist_date``) plus an ``as_of`` trade date, and
    returns the PIT-legitimate subset: listed on or before ``as_of`` AND (no
    delist_date OR delist_date strictly after ``as_of``).

    Args:
        stock_basic: DataFrame with at least ``ts_code`` and ``list_date``;
            ``delist_date`` is optional (current list_status="L" shape omits it).
        as_of: compact or dashed trade date (YYYYMMDD / YYYY-MM-DD). When
            ``None`` (live mode), returns the input unchanged — PIT filtering
            is a backtest-only concern (parity with R40/R41 as_of=None).
        return_audit: when True, also return a compact survivorship-bias audit
            summary dict so a campaign can quantify the bias magnitude.

    Returns:
        Filtered DataFrame, or ``(filtered, audit_summary)`` when
        ``return_audit=True``. The audit summary distinguishes
        ``dropped_already_delisted`` (the survivorship-bias signal) from
        ``dropped_not_yet_listed`` and ``dropped_unparseable``.
    """
    if as_of is None:
        # Live mode: no PIT filtering. Return input unchanged.
        if return_audit:
            summary = {
                "input_count": len(stock_basic),
                "kept_count": len(stock_basic),
                "dropped_already_delisted": 0,
                "dropped_not_yet_listed": 0,
                "dropped_unparseable": 0,
            }
            return stock_basic, summary
        return stock_basic

    as_of_compact = _normalize_compact_date(as_of)
    # If as_of itself is unparseable, fail safe: do not filter (return input).
    # This mirrors the R41 malformed-as_of fallback — never let a bad as_of
    # silently over-filter the universe.
    if as_of_compact is None:
        if return_audit:
            summary = {
                "input_count": len(stock_basic),
                "kept_count": len(stock_basic),
                "dropped_already_delisted": 0,
                "dropped_not_yet_listed": 0,
                "dropped_unparseable": 0,
            }
            return stock_basic, summary
        return stock_basic

    input_count = len(stock_basic)
    if input_count == 0:
        if return_audit:
            summary = {
                "input_count": 0,
                "kept_count": 0,
                "dropped_already_delisted": 0,
                "dropped_not_yet_listed": 0,
                "dropped_unparseable": 0,
            }
            return stock_basic, summary

    has_delist_col = "delist_date" in stock_basic.columns

    kept_mask: list[bool] = []
    dropped_already_delisted = 0
    dropped_not_yet_listed = 0
    dropped_unparseable = 0

    for _, row in stock_basic.iterrows():
        list_compact = _normalize_compact_date(row.get("list_date"))
        if list_compact is None:
            # Cannot establish PIT legality — conservative exclusion.
            kept_mask.append(False)
            dropped_unparseable += 1
            continue
        if list_compact > as_of_compact:
            # IPO after as_of — did not exist yet.
            kept_mask.append(False)
            dropped_not_yet_listed += 1
            continue
        # list_date <= as_of: listed on or before as_of. Now check delist.
        if has_delist_col:
            delist_compact = _normalize_compact_date(row.get("delist_date"))
            if delist_compact is not None and delist_compact <= as_of_compact:
                # Delisted on or before as_of — no longer tradeable.
                kept_mask.append(False)
                dropped_already_delisted += 1
                continue
        kept_mask.append(True)

    kept = stock_basic[pd.Series(kept_mask, index=stock_basic.index)].reset_index(drop=True)
    if return_audit:
        summary = {
            "input_count": input_count,
            "kept_count": len(kept),
            "dropped_already_delisted": dropped_already_delisted,
            "dropped_not_yet_listed": dropped_not_yet_listed,
            "dropped_unparseable": dropped_unparseable,
        }
        return kept, summary
    return kept


def _fetch_tushare_daily_basic_batch(pro, trade_date: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "daily_basic",
        trade_date=trade_date,
        fields="ts_code,trade_date,close,turnover_rate,pe,pe_ttm,pb,ps,ps_ttm," "dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv",
    )


def get_daily_basic_batch(trade_date: str) -> pd.DataFrame | None:
    """
    获取全市场当日基础面指标（PE/PB/换手率/成交额/总市值/流通市值）。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD

    返回 DataFrame 列: ts_code, trade_date, close, turnover_rate, pe, pe_ttm,
                       pb, ps, ps_ttm, dv_ratio, dv_ttm, total_share, float_share,
                       free_share, total_mv, circ_mv, volume, amount
    """
    # Cache key uses ":" separator to match BatchDataFetcher key format and
    # share the same cache entry — see GAMMA-018 / R20.4 fix.
    cache_key = f"daily_basic_batch:{trade_date}"

    pro = _get_pro()
    if pro is None:
        return None

    try:
        return fetch_batch_cached_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_daily_basic_batch(pro, trade_date),
        )
    except Exception as e:
        logger.error("[Tushare] get_daily_basic_batch(%s) 失败: %s", trade_date, e, exc_info=True)
        return None


def _fetch_tushare_daily_price_batch(pro, trade_date: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "daily",
        trade_date=trade_date,
        fields="ts_code,trade_date,open,high,low,close,pre_close,vol,amount,pct_chg",
    )


def get_daily_price_batch(trade_date: str) -> pd.DataFrame | None:
    """
    获取全市场当日日线行情。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD

    返回 DataFrame 列: ts_code, trade_date, open, high, low, close,
                       pre_close, vol, amount, pct_chg
    """
    # Cache key uses ":" separator to match BatchDataFetcher key format and
    # share the same cache entry — see GAMMA-018 / R20.4 fix.
    cache_key = f"daily_price_batch:{trade_date}"

    pro = _get_pro()
    if pro is None:
        return None

    try:
        return fetch_batch_cached_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_daily_price_batch(pro, trade_date),
        )
    except Exception as e:
        logger.error("[Tushare] get_daily_price_batch(%s) 失败: %s", trade_date, e, exc_info=True)
        return None


def get_open_trade_dates(start_date: str, end_date: str) -> list[str]:
    """
    获取区间内开市交易日列表。

    参数:
        start_date: 开始日期，格式 YYYYMMDD
        end_date: 结束日期，格式 YYYYMMDD
    """
    pro = _get_pro()
    if pro is None:
        return []

    try:
        df = _fetch_tushare_open_trade_dates(pro, start_date, end_date)
        return extract_open_trade_dates(df)
    except Exception as e:
        logger.error(
            "[Tushare] get_open_trade_dates(%s, %s) 失败: %s",
            start_date,
            end_date,
            e,
            exc_info=True,
        )
        return []


def _fetch_tushare_open_trade_dates(pro, start_date: str, end_date: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(
        pro,
        "trade_cal",
        exchange="",
        start_date=start_date,
        end_date=end_date,
        is_open=1,
        fields="cal_date,is_open",
    )


def _resolve_tushare_sw_industry_mapping(pro, cached_mapping: dict[str, str] | None) -> dict[str, str] | None:
    return resolve_cached_sw_industry_mapping(
        cached_mapping=cached_mapping,
        load_index_df=lambda: load_sw_index_classification(_cached_tushare_dataframe_call, pro),
        build_mapping=lambda index_df: build_sw_industry_mapping(_cached_tushare_dataframe_call, pro, index_df),
        cache_mapping=_cache_sw_industry_mapping,
    )


def get_sw_industry_classification() -> dict[str, str] | None:
    """
    获取申万一级行业分类映射：{ts_code -> 行业名称}。

    使用 tushare index_classify（L1 申万一级）获取行业列表，
    再用 index_member 获取每个行业的成分股。
    结果全局缓存。
    """
    pro = _get_pro()
    if pro is None:
        return None

    # Fast path: return cached copy under the lock.
    with _sw_industry_cache_lock:
        if _sw_industry_cache is not None:
            return dict(_sw_industry_cache)

    # Slow path: build WITHOUT holding _sw_industry_cache_lock.
    # _resolve_tushare_sw_industry_mapping → resolve_cached_sw_industry_mapping
    # invokes the cache_mapping callback (_cache_sw_industry_mapping), which
    # re-acquires _sw_industry_cache_lock — holding it here would self-deadlock
    # (the lock is a non-reentrant threading.Lock). R20.25.
    # Building is idempotent; a concurrent builder at worst sets the cache twice.
    try:
        result = _resolve_tushare_sw_industry_mapping(pro, None)
        if result is None:
            logger.warning("[Tushare] 无法获取申万行业分类")
        return result
    except Exception as e:
        logger.error("[Tushare] get_sw_industry_classification 失败: %s", e, exc_info=True)
        return None


def _cache_sw_industry_mapping(mapping: dict[str, str]) -> None:
    global _sw_industry_cache
    with _sw_industry_cache_lock:
        _sw_industry_cache = mapping


def _fetch_tushare_limit_list(pro, trade_date: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(pro, "limit_list_d", trade_date=trade_date)


def get_limit_list(trade_date: str) -> pd.DataFrame | None:
    """
    获取当日涨跌停列表。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD

    返回 DataFrame 列: trade_date, ts_code, name, close, pct_chg,
                       amp, fc_ratio, fl_ratio, fd_amount, first_time, last_time,
                       open_times, up_stat, limit_times, limit
    其中 limit 字段: U=涨停, D=跌停, Z=炸板
    """
    cache_key = f"limit_list_{trade_date}"

    pro = _get_pro()
    if pro is None:
        return None

    try:
        return fetch_batch_cached_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_limit_list(pro, trade_date),
        )
    except Exception as e:
        logger.error("[Tushare] get_limit_list(%s) 失败: %s", trade_date, e, exc_info=True)
        return None


def get_suspend_list(trade_date: str) -> pd.DataFrame | None:
    """
    获取当日停牌列表。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD

    返回 DataFrame 列: ts_code, trade_date, suspend_timing, suspend_type
    """
    cache_key = f"suspend_list_{trade_date}"

    pro = _get_pro()
    if pro is None:
        return None

    try:
        return fetch_batch_cached_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_suspend_list(pro, trade_date),
        )
    except Exception as e:
        logger.error("[Tushare] get_suspend_list(%s) 失败: %s", trade_date, e, exc_info=True)
        return None


def _fetch_tushare_suspend_list(pro, trade_date: str) -> pd.DataFrame | None:
    return _cached_tushare_dataframe_call(pro, "suspend_d", trade_date=trade_date)


def _fetch_tushare_index_daily(pro, kwargs: dict[str, Any]) -> pd.DataFrame | None:
    return pro.index_daily(**kwargs)


def get_index_daily(index_code: str, start_date: str = "", end_date: str = "", limit: int = 120) -> pd.DataFrame | None:
    """
    获取指数日线行情（沪深300/上证50/中证500等）。

    参数:
        index_code: 指数代码（如 '000300.SH' 沪深300, '000016.SH' 上证50, '000905.SH' 中证500）
        start_date: 开始日期 YYYYMMDD（可选）
        end_date: 结束日期 YYYYMMDD（可选）
        limit: 返回行数

    返回 DataFrame 列: ts_code, trade_date, close, open, high, low, pre_close,
                       change, pct_chg, vol, amount
    """
    cache_key = f"index_daily_{index_code}_{start_date}_{end_date}_{limit}"
    pro = _get_pro()
    if pro is None:
        return None

    try:
        kwargs = build_index_daily_query_kwargs(index_code, start_date, end_date, limit)
        return fetch_sorted_cached_market_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_index_daily(pro, kwargs),
        )
    except Exception as e:
        logger.error("[Tushare] get_index_daily(%s) 失败: %s", index_code, e, exc_info=True)
        return None


def _fetch_tushare_northbound_flow(pro, kwargs: dict[str, Any]) -> pd.DataFrame | None:
    return pro.moneyflow_hsgt(**kwargs)


def get_northbound_flow(trade_date: str = "", start_date: str = "", end_date: str = "", limit: int = 30) -> pd.DataFrame | None:
    """
    获取北向资金（沪股通+深股通）每日流向。

    参数:
        trade_date: 单日查询 YYYYMMDD（可选）
        start_date/end_date: 区间查询（可选）
        limit: 默认 30 日

    返回 DataFrame 列: trade_date, ggt_ss（港股通上海）, ggt_sz（港股通深圳）,
                       hgt（沪股通）, sgt（深股通）, north_money（北向合计）, south_money（南向合计）
    """
    cache_key = f"northbound_{trade_date}_{start_date}_{end_date}_{limit}"
    pro = _get_pro()
    if pro is None:
        return None

    try:
        kwargs = build_northbound_flow_query_kwargs(trade_date, start_date, end_date, limit)
        return fetch_sorted_cached_market_frame(
            cache_key=cache_key,
            get_cached_df=_get_tushare_cached_df,
            store_cached_df=_store_tushare_cached_df,
            fetch_frame=lambda: _fetch_tushare_northbound_flow(pro, kwargs),
        )
    except Exception as e:
        logger.error("[Tushare] get_northbound_flow 失败: %s", e, exc_info=True)
        return None
