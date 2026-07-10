"""资金流数据多源 dispatcher — tushare → akshare → ftshare。

三源:
- tushare moneyflow: 主源 (token 全通, 数据丰富)
- akshare stock_individual_fund_flow: 第 2 源 (东财 push2his 域偶发不稳)
- ftshare stock_capital_flows: 第 3 源 (东财源, 提供 main_net_pct 占比, tushare 缺)

N 源 fallback 循环、去重日志、空返回由 _multi_source.try_sources 统一处理。
"""

from __future__ import annotations

import pandas as pd

from src.tools._multi_source import EMPTY_FUND_FLOW_DF, reorder_sources, try_sources


def fetch_individual_fund_flow(
    ticker: str,
    start_date: str = "20200101",
    end_date: str | None = None,
    primary: str = "tushare",
) -> pd.DataFrame:
    """多源拉取个股资金流, tushare 主源 → akshare → ftshare。

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
    return try_sources(
        sources,
        log_tag="[资金流]",
        label=ticker,
        fetch_args=(ticker, start_date, end_date),
        empty_df=EMPTY_FUND_FLOW_DF,
    )


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
