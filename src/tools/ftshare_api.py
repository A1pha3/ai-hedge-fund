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
    """ftshare eastmoney_stock_flow (东财个股资金流) → fund_flow_cache schema。

    核心优势: 东财源提供 main_net_pct (主力净流入占比) 和 close, 填补 tushare moneyflow
    这两列恒为 NaN 的缺口。tushare 主源获胜后, fund_flow._enrich_close_and_main_net_pct
    会调本函数按日期补全这两列。

    Note: 早期版本误用 market.stock_capital_flows — 那是全市场单日快照, 没有 symbol
    参数, 调用一直空返回。正确接口是 eastmoney_stock_flow (单票区间, 含 close/占比)。
    另: eastmoney_stock_flow 的日期参数必须带横线 (YYYY-MM-DD), 不带横线返回空。
    """
    market = _get_market()
    if market is None:
        return EMPTY_FUND_FLOW_DF.copy()

    if end_date is None:
        end_date = pd.Timestamp.now().strftime("%Y%m%d")

    # eastmoney_stock_flow 要求 YYYY-MM-DD 带横线 (实测不带横线返回空)。
    sd = _ensure_dashed(start_date)
    ed = _ensure_dashed(end_date)

    try:
        df = market.eastmoney_stock_flow(
            symbol=ticker,
            start_date=sd,
            end_date=ed,
        )
    except Exception as exc:
        logger.debug("[ftshare] eastmoney_stock_flow %s 调用失败: %s", ticker, exc)
        return EMPTY_FUND_FLOW_DF.copy()

    if df is None or len(df) == 0:
        return EMPTY_FUND_FLOW_DF.copy()
    return _normalise_fund_flow(df, ticker)


def _ensure_dashed(date_str: str) -> str:
    """YYYYMMDD → YYYY-MM-DD; 已带横线的原样返回。"""
    s = str(date_str).strip()
    if "-" in s:
        return s
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s


# 金额字段列名映射 (东财个股资金流真实列名 → 归一化名)
# 实测 eastmoney_stock_flow 返回 16 列: code/name/market/trade_date/close_price/
# change_pct/main_net/main_pct/super_large_net/super_large_pct/large_net/large_pct/
# medium_net/medium_pct/small_net/small_pct
_FLOW_AMOUNT_FIELDS = [
    ("main_net_inflow",     ["main_net", "main_net_inflow", "主力净流入-净额", "主力净流入净额", "net_mf_amount"]),
    ("main_net_pct",        ["main_pct", "main_net_pct", "主力净流入-净占比", "主力净流入净占比"]),
    ("big_net_inflow",      ["large_net", "big_net_inflow", "大单净流入-净额", "大单净流入净额"]),
    ("super_big_net_inflow",["super_large_net", "super_big_net_inflow", "超大单净流入-净额", "超大单净流入净额"]),
    ("medium_net_inflow",   ["medium_net", "中单净流入-净额", "中单净流入净额"]),
    ("small_net_inflow",    ["small_net", "小单净流入-净额", "小单净流入净额"]),
]


def _normalise_fund_flow(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """归一化为 fund_flow_cache schema。东财资金流金额单位: 元 (非万元, 不做启发式)。"""
    df = df.copy()

    date_col = find_col(df, ["trade_date", "date", "日期", "交易日"])
    if date_col is None:
        logger.warning("[ftshare] %s eastmoney_stock_flow 无日期列: %s", ticker, list(df.columns))
        return EMPTY_FUND_FLOW_DF.copy()
    df["date"] = pd.to_datetime(df[date_col].astype(str).str.replace("-", ""), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])

    # 金额字段: ftshare 东财源返回元 (非万元), 不需要 wan_to_yuan 启发式.
    # Bug fix (C2): 旧启发式 median<1e4 误判小额资金流为万元 → 10000x 膨胀.
    for target, candidates in _FLOW_AMOUNT_FIELDS:
        col = find_col(df, candidates)
        if col:
            df[target] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        elif target == "main_net_pct":
            # Bug fix (M4): ftshare 不提供占比时用 NaN 而非 0.0, 避免伪造数据
            df[target] = float("nan")
        else:
            df[target] = 0.0

    # close / pct_change (东财个股资金流接口含 close_price / change_pct)
    close_col = find_col(df, ["close_price", "close", "收盘价", "收盘"])
    df["close"] = pd.to_numeric(df[close_col], errors="coerce") if close_col else float("nan")
    pct_col = find_col(df, ["change_pct", "pct_change", "涨跌幅"])
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
