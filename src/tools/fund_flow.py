"""资金流数据双源 dispatcher — tushare 主源 + akshare fallback。

本项目架构约定 (记忆 autodev-session-20260623-r162-r163-r164): 单源不可用时
fallback 到另一源, 避免单点故障。资金流同理:
- tushare moneyflow: 主源 (本项目 token 全通, 数据更丰富)
- akshare stock_individual_fund_flow: fallback (eastmoney push2his 域偶发不稳)

两源在 fetch 层归一化为相同 schema + 相同单位 (元), 保证 store 数据可混用。

CLI/脚本统一调 fetch_individual_fund_flow (本模块), 不直接调单源。
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# 双源均空去重: 批量拉取时北交所/新股会大量触发, 首次打 WARNING, 后续静默计数。
_empty_source_counts: dict[str, int] = {}


def fetch_individual_fund_flow(
    ticker: str,
    start_date: str = "20200101",
    end_date: str | None = None,
    primary: str = "tushare",
) -> pd.DataFrame:
    """双源拉取个股资金流, tushare 主源, akshare fallback。

    Args:
        ticker: 6 位代码
        start_date: YYYYMMDD (tushare 用; akshare 忽略, 返回近期)
        end_date: YYYYMMDD (None = 今天)
        primary: "tushare" (默认) 或 "akshare" — 主源选择

    Returns:
        标准化 DataFrame (date/close/pct_change/main_net_inflow[元]/...);
        两源都失败时返回空 DataFrame。
    """
    sources = []
    if primary == "tushare":
        sources = [("tushare", _try_tushare), ("akshare", _try_akshare)]
    else:
        sources = [("akshare", _try_akshare), ("tushare", _try_tushare)]

    # Track each source's real outcome so the final message distinguishes "empty
    # data" from "fetch exception" — these have different root causes (data not
    # covered/ready vs. network/SSL failure) and must not be conflated.
    outcomes: dict[str, str] = {}
    for name, fetcher in sources:
        try:
            df = fetcher(ticker, start_date, end_date)
        except Exception as exc:
            outcomes[name] = f"异常 ({type(exc).__name__}: {exc})"
            df = pd.DataFrame()
        if df is not None and len(df) > 0:
            logger.debug("[%s] %s 命中 %d 行", ticker, name, len(df))
            return df
        if name not in outcomes:
            outcomes[name] = "返回空数据"
        logger.debug("[%s] %s 返回空, 尝试下一源", ticker, name)

    # 双源均失败去重: 批量拉取时北交所/新股/网络抖动会大量触发, 首次 WARNING
    # (含每源真实失败原因), 后续静默计数。
    _empty_source_counts["dual_empty"] = _empty_source_counts.get("dual_empty", 0) + 1
    count = _empty_source_counts["dual_empty"]
    detail = "; ".join(f"{src}: {reason}" for src, reason in outcomes.items())
    if count == 1:
        logger.warning("[资金流] %s 双源均失败 — %s (后续同类将静默)", ticker, detail)
    elif count % 50 == 0:
        logger.info("资金流双源均失败已累计 %d 次 (静默中)", count)
    return pd.DataFrame(columns=["date", "main_net_inflow"])


def _try_tushare(ticker: str, start_date: str, end_date: str | None) -> pd.DataFrame:
    from src.tools.tushare_fund_flow import fetch_individual_fund_flow_tushare

    return fetch_individual_fund_flow_tushare(ticker, start_date=start_date, end_date=end_date)


def _try_akshare(ticker: str, start_date: str, end_date: str | None) -> pd.DataFrame:
    """akshare fallback. akshare 不支持 start/end_date 参数 (只返回近期), 忽略。"""
    from src.tools.akshare_fund_flow import fetch_individual_fund_flow as _ak_fetch

    df = _ak_fetch(ticker)
    # 如果指定了 end_date, 按日期过滤 (akshare 返回全部近期)
    if df is not None and len(df) > 0 and end_date:
        df = df.copy()
        df["date_str"] = df["date"].dt.strftime("%Y%m%d")
        df = df[df["date_str"] <= end_date].drop(columns=["date_str"]).reset_index(drop=True)
    if df is not None and len(df) > 0 and start_date:
        df = df.copy()
        df["date_str"] = df["date"].dt.strftime("%Y%m%d")
        df = df[df["date_str"] >= start_date].drop(columns=["date_str"]).reset_index(drop=True)
    return df
