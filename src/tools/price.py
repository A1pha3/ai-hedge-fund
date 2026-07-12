"""日线行情多源 dispatcher — tushare → akshare → ftshare。

返回 price_cache schema: date[YYYY-MM-DD] / close / open / high / low / pct_change[百分] / volume。
N 源 fallback 循环、去重日志、空返回由 _multi_source.try_sources 统一处理。
"""

from __future__ import annotations

import pandas as pd

from src.tools._multi_source import EMPTY_PRICE_DF, reorder_sources, try_sources


def fetch_daily_ohlcv(
    ticker: str,
    start_date: str,
    end_date: str,
    primary: str = "tushare",
) -> pd.DataFrame:
    """日线行情 N 源 fallback: tushare → akshare → ftshare。"""
    sources = [
        ("tushare", _try_tushare),
        ("akshare", _try_akshare),
        ("ftshare", _try_ftshare),
    ]
    if primary != "tushare":
        sources = reorder_sources(sources, primary)
    return try_sources(
        sources,
        log_tag="[日线]",
        label=ticker,
        fetch_args=(ticker, start_date, end_date),
        empty_df=EMPTY_PRICE_DF,
    )


def _try_tushare(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """tushare: pro.daily + adj_factor (前复权 qfq)。复用 cache_refresh 已有逻辑。"""
    from src.screening.offensive.cache_refresh import _fetch_price_history_with_tushare

    return _fetch_price_history_with_tushare(ticker, start_date, end_date)


def _try_akshare(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """akshare: stock_zh_a_hist (前复权), 中文列名归一化.

    M1 fix: 复用 akshare_runtime_helpers 的共享线程池加超时, 防止单次 akshare 调用挂起整个 --auto 运行.
    """
    try:
        import akshare as ak
    except ImportError:
        return pd.DataFrame()

    from src.tools.akshare_runtime_helpers import _call_with_timeout

    try:
        df = _call_with_timeout(
            ak.stock_zh_a_hist,
            symbol=ticker, period="daily",
            start_date=start_date.replace("-", ""), end_date=end_date.replace("-", ""),
            adjust="qfq",
        )
    except TimeoutError:
        logger.debug("[price] akshare stock_zh_a_hist %s 超时", ticker)
        return pd.DataFrame()
    if df is None or len(df) == 0:
        return pd.DataFrame()
    return _normalise_akshare(df)


def _try_ftshare(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """ftshare: stock_ohlcs (前复权), 独立于东财/tushare 的网络出口。"""
    from src.tools.ftshare_api import fetch_daily_ohlcv_ftshare

    return fetch_daily_ohlcv_ftshare(ticker, start_date, end_date)


# ── akshare 中文列名 → price_cache schema ─────────────────────────────────

_AKSHARE_COL_MAP = {
    "日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
    "最低": "low", "成交量": "volume", "涨跌幅": "pct_change",
}


def _normalise_akshare(df: pd.DataFrame) -> pd.DataFrame:
    from src.tools._multi_source import select_and_sort

    df = df.rename(columns=_AKSHARE_COL_MAP).copy()
    if "date" in df.columns:
        parsed = pd.to_datetime(df["date"].astype(str).str.replace("-", ""), format="%Y%m%d", errors="coerce")
        df["date"] = parsed.dt.strftime("%Y-%m-%d")
        df = df.dropna(subset=["date"])
    if "pct_change" not in df.columns:
        df["pct_change"] = df["close"].pct_change().fillna(0.0) * 100.0
    else:
        df["pct_change"] = pd.to_numeric(df["pct_change"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["close"])
    return select_and_sort(df, ["date", "close", "open", "high", "low", "pct_change", "volume"])
