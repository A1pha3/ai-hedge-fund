"""ftshare 源数据 fetcher — 日线行情 / 个股资金流 / 宏观指标。

每个函数返回与 tushare/akshare 同族 fetcher 完全相同 schema 的 DataFrame,
使 dispatcher (price.py / fund_flow.py / macro_multi.py) 可以无缝混用多源数据。

Schema:
- 日线: date[YYYY-MM-DD] / close / open / high / low / pct_change[百分] / volume
- 资金流: date / close / pct_change / main_net_inflow[元] / main_net_pct / ...
- 宏观: dict[str, dict] (与 macro_data.fetch_macro_snapshot 兼容)

工具函数 (find_col / safe_float_col / safe_scalar / 常量) 统一从 _multi_source 导入。
"""

from __future__ import annotations

import logging

import pandas as pd

from src.tools._multi_source import (
    EMPTY_FUND_FLOW_DF,
    EMPTY_PRICE_DF,
    WAN_TO_YUAN,
    find_col,
    safe_float_col,
    safe_scalar,
    select_and_sort,
    wan_to_yuan_if_needed,
)
from src.tools.ftshare_client import _get_market

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 日线行情
# ═══════════════════════════════════════════════════════════════════════════

def fetch_daily_ohlcv_ftshare(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """ftshare stock_ohlcs (前复权 qfq) → price_cache schema。"""
    market = _get_market()
    if market is None:
        return EMPTY_PRICE_DF.copy()

    try:
        df = market.stock_ohlcs(
            symbol=ticker,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="qfq",
        )
    except Exception as exc:
        logger.debug("[ftshare] stock_ohlcs %s 调用失败: %s", ticker, exc)
        return EMPTY_PRICE_DF.copy()

    if df is None or len(df) == 0:
        return EMPTY_PRICE_DF.copy()
    return _normalise_ohlcv(df, ticker)


def _normalise_ohlcv(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """归一化为 price_cache schema。列名大小写不敏感查找。"""
    df = df.copy()

    date_col = find_col(df, ["date", "trade_date", "trade_time", "day"])
    if date_col is None:
        logger.warning("[ftshare] %s stock_ohlcs 无日期列, 列名: %s", ticker, list(df.columns))
        return EMPTY_PRICE_DF.copy()

    dates = pd.to_datetime(df[date_col].astype(str).str.replace("-", ""), format="%Y%m%d", errors="coerce")
    df["date"] = dates.dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["date"])

    # find_col 已大小写不敏感, 每个字段只列语义不同的候选
    df["open"] = safe_float_col(df, ["open"])
    df["high"] = safe_float_col(df, ["high"])
    df["low"] = safe_float_col(df, ["low"])
    df["close"] = safe_float_col(df, ["close", "last"])
    df["volume"] = safe_float_col(df, ["volume", "vol", "成交量"])

    pct_col = find_col(df, ["pct_chg", "pct_change", "change_pct", "涨跌幅"])
    if pct_col:
        df["pct_change"] = pd.to_numeric(df[pct_col], errors="coerce").fillna(0.0)
    else:
        df["pct_change"] = df["close"].pct_change().fillna(0.0) * 100.0

    df = df.dropna(subset=["close"])
    return select_and_sort(df, ["date", "close", "open", "high", "low", "pct_change", "volume"])


# ═══════════════════════════════════════════════════════════════════════════
# 个股资金流
# ═══════════════════════════════════════════════════════════════════════════

def fetch_individual_fund_flow_ftshare(
    ticker: str, start_date: str, end_date: str | None = None,
) -> pd.DataFrame:
    """ftshare stock_capital_flows (东财源) → fund_flow_cache schema。

    核心优势: 东财源提供 main_net_pct (主力净流入占比), 填补 tushare 该字段恒为 0.0。
    """
    market = _get_market()
    if market is None:
        return EMPTY_FUND_FLOW_DF.copy()

    if end_date is None:
        end_date = pd.Timestamp.now().strftime("%Y%m%d")

    try:
        df = market.stock_capital_flows(
            symbol=ticker,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )
    except Exception as exc:
        logger.debug("[ftshare] stock_capital_flows %s 调用失败: %s", ticker, exc)
        return EMPTY_FUND_FLOW_DF.copy()

    if df is None or len(df) == 0:
        return EMPTY_FUND_FLOW_DF.copy()
    return _normalise_fund_flow(df, ticker)


# 金额字段列名映射 (中文 → 归一化名)
_FLOW_AMOUNT_FIELDS = [
    ("main_net_inflow",     ["main_net_inflow", "主力净流入-净额", "主力净流入净额", "net_mf_amount"]),
    ("main_net_pct",        ["main_net_pct", "主力净流入-净占比", "主力净流入净占比"]),
    ("big_net_inflow",      ["big_net_inflow", "大单净流入-净额", "大单净流入净额"]),
    ("super_big_net_inflow",["super_big_net_inflow", "超大单净流入-净额", "超大单净流入净额"]),
    ("medium_net_inflow",   ["medium_net_inflow", "中单净流入-净额", "中单净流入净额"]),
    ("small_net_inflow",    ["small_net_inflow", "小单净流入-净额", "小单净流入净额"]),
]


def _normalise_fund_flow(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """归一化为 fund_flow_cache schema。东财资金流金额单位: 元 (启发式万元检测)。"""
    df = df.copy()

    date_col = find_col(df, ["date", "trade_date", "日期", "交易日"])
    if date_col is None:
        logger.warning("[ftshare] %s stock_capital_flows 无日期列: %s", ticker, list(df.columns))
        return EMPTY_FUND_FLOW_DF.copy()
    df["date"] = pd.to_datetime(df[date_col].astype(str).str.replace("-", ""), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])

    # 金额字段: 查找 + 万元→元启发式
    amount_fields = ["main_net_inflow", "big_net_inflow", "super_big_net_inflow",
                     "medium_net_inflow", "small_net_inflow"]
    for target, candidates in _FLOW_AMOUNT_FIELDS:
        col = find_col(df, candidates)
        if col:
            series = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            if target in amount_fields:
                series = wan_to_yuan_if_needed(series)
            df[target] = series
        elif target == "main_net_pct":
            df[target] = 0.0
        else:
            df[target] = 0.0

    # close / pct_change (东财资金流接口通常含收盘价)
    close_col = find_col(df, ["close", "收盘价", "收盘"])
    df["close"] = pd.to_numeric(df[close_col], errors="coerce") if close_col else float("nan")
    pct_col = find_col(df, ["pct_change", "涨跌幅"])
    df["pct_change"] = pd.to_numeric(df[pct_col], errors="coerce").fillna(0.0) if pct_col else 0.0

    keep = ["date", "close", "pct_change", "main_net_inflow", "main_net_pct",
            "big_net_inflow", "super_big_net_inflow", "medium_net_inflow", "small_net_inflow"]
    return select_and_sort(df, keep)


# ═══════════════════════════════════════════════════════════════════════════
# 宏观指标
# ═══════════════════════════════════════════════════════════════════════════

# (结果 key, market 方法名)
_MACRO_ENDPOINTS = [
    ("cpi", "consumer_price_index_monthly"),
    ("ppi", "consumer_ppi_monthly"),
    ("pmi", "consumer_pmi_monthly"),
    ("m2", "consumer_money_supply_monthly"),
    ("sf", "consumer_credit_monthly"),
    ("lpr", "lpr_monthly"),
]


def fetch_macro_snapshot_ftshare() -> dict:
    """批量调用 6 个宏观接口 (CPI/PPI/PMI/M2/社融/LPR), 返回最新一期 dict。

    tushare 宏观接口多无权限 → ftshare 作为唯一可靠宏观源。
    """
    market = _get_market()
    if market is None:
        return {}

    result: dict[str, dict] = {}
    for key, method_name in _MACRO_ENDPOINTS:
        df = _safe_call(market, method_name)
        if df is not None and len(df) > 0:
            row = df.iloc[-1]
            result[key] = {k: safe_scalar(v) for k, v in row.items()}

    if not result:
        logger.warning("[ftshare] 宏观快照全部接口返回空")
    else:
        logger.debug("[ftshare] 宏观快照获取成功: %s", list(result.keys()))
    return result


def _safe_call(market: object, method_name: str) -> pd.DataFrame | None:
    """安全调用 market 的指定方法, 异常时返回 None。"""
    try:
        return getattr(market, method_name)()
    except Exception as exc:
        logger.debug("[ftshare] 宏观接口 %s 调用失败: %s", method_name, exc)
        return None
