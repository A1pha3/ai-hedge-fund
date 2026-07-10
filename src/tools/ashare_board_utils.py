from __future__ import annotations

from typing import Any

import pandas as pd

SHANGHAI_EXCHANGE_SYMBOL_PREFIXES: tuple[str, ...] = ("6", "68", "51", "56", "58", "60")
SHENZHEN_EXCHANGE_SYMBOL_PREFIXES: tuple[str, ...] = ("0", "3", "15", "16", "18", "20")
BEIJING_EXCHANGE_SYMBOL_PREFIXES: tuple[str, ...] = ("4", "8", "92")
ASHARE_EXCHANGE_SUFFIXES: dict[str, str] = {"sh": "SH", "sz": "SZ", "bj": "BJ"}


def _normalize_ticker_text(ticker: Any) -> str:
    return str(ticker or "").strip()


def split_ashare_exchange_prefix(ticker: Any) -> tuple[str | None, str]:
    normalized = _normalize_ticker_text(ticker).lower()
    # R163: .SH/.SZ/.BJ SUFFIX format (tushare ts_code standard, e.g. "600000.SH")
    # must be split — before fix the suffix stayed attached to the symbol and
    # to_tushare_code re-appended it → "600000.sh.SH" (double-suffix → empty fetch).
    if "." in normalized:
        base, _, suffix = normalized.rpartition(".")
        if suffix in ("sh", "sz", "bj") and base:
            return suffix, base
    # sh/sz/bj PREFIX format (e.g. "sh600000")
    if normalized.startswith(("sh", "sz", "bj")):
        return normalized[:2], normalized[2:]
    return None, normalized


def get_ashare_symbol(ticker: Any) -> str:
    _, symbol = split_ashare_exchange_prefix(ticker)
    return symbol


def detect_ashare_exchange(ticker: Any) -> str:
    exchange, symbol = split_ashare_exchange_prefix(ticker)
    if exchange is not None:
        return exchange
    if symbol.startswith(SHANGHAI_EXCHANGE_SYMBOL_PREFIXES):
        return "sh"
    if symbol.startswith(SHENZHEN_EXCHANGE_SYMBOL_PREFIXES):
        return "sz"
    if symbol.startswith(BEIJING_EXCHANGE_SYMBOL_PREFIXES):
        return "bj"
    return "sz"


def to_tushare_code(ticker: Any) -> str:
    symbol = get_ashare_symbol(ticker)
    exchange = detect_ashare_exchange(ticker)
    return f"{symbol}.{ASHARE_EXCHANGE_SUFFIXES[exchange]}"


def to_baostock_code(ticker: Any) -> str:
    symbol = get_ashare_symbol(ticker)
    exchange = detect_ashare_exchange(ticker)
    return f"{exchange}.{symbol}"


def to_prefixed_ashare_code(ticker: Any) -> str:
    symbol = get_ashare_symbol(ticker)
    exchange = detect_ashare_exchange(ticker)
    return f"{exchange}{symbol}"


def is_beijing_exchange_ts_code(ts_code: Any) -> bool:
    normalized = _normalize_ticker_text(ts_code).upper()
    if not normalized:
        return False
    if normalized.endswith(".BJ"):
        return True
    return normalized.split(".", 1)[0].startswith(BEIJING_EXCHANGE_SYMBOL_PREFIXES)


def is_beijing_exchange_stock(*, ts_code: str | None = None, symbol: str | None = None, market: str | None = None) -> bool:
    market_text = _normalize_ticker_text(market)
    if market_text.upper() == "BJ" or market_text == "北交所":
        return True
    if is_beijing_exchange_ts_code(ts_code):
        return True
    return get_ashare_symbol(symbol).startswith(BEIJING_EXCHANGE_SYMBOL_PREFIXES)


def build_beijing_exchange_mask_from_series(series: pd.Series) -> pd.Series:
    normalized = series.fillna("").astype(str).str.strip().str.upper()
    symbol = normalized.str.split(".").str[0]
    return normalized.str.endswith(".BJ") | symbol.str.startswith(BEIJING_EXCHANGE_SYMBOL_PREFIXES)


def build_beijing_exchange_mask(stock_df: pd.DataFrame) -> pd.Series:
    if stock_df.empty:
        return pd.Series(dtype=bool)

    market_series = stock_df["market"] if "market" in stock_df else pd.Series("", index=stock_df.index, dtype="object")
    ts_code_series = stock_df["ts_code"] if "ts_code" in stock_df else pd.Series("", index=stock_df.index, dtype="object")
    symbol_series = stock_df["symbol"] if "symbol" in stock_df else pd.Series("", index=stock_df.index, dtype="object")

    normalized_market = market_series.fillna("").astype(str).str.strip()
    return normalized_market.str.upper().eq("BJ") | normalized_market.eq("北交所") | build_beijing_exchange_mask_from_series(ts_code_series) | symbol_series.fillna("").astype(str).str.strip().str.startswith(BEIJING_EXCHANGE_SYMBOL_PREFIXES)


# A 股涨跌停幅度 (按板块). 用于判断「涨停」的 pct_change 阈值.
# 主板 (沪 60/深 00) ±10%, 科创板 (688) / 创业板 (300/301) ±20%, 北交所 ±30%.
# 返回的是「接近涨停」的保守下限 (真实涨停的 95%), 容忍浮点/四舍五入:
#   主板 10% × 0.95 = 9.5%; 科创/创业 20% × 0.95 = 19.0% (取 19.5 容 19.0-19.4 的边界).
_LIMIT_UP_PCT_MAIN = 9.5       # 主板 (60/00): 涨停 ≈ +10%, 下限 9.5%
_LIMIT_UP_PCT_STAR = 19.5      # 科创板 (688) / 创业板 (300/301): 涨停 ≈ +20%, 下限 19.5%
_LIMIT_UP_PCT_BJ = 29.0        # 北交所 (4/8/92/83): 涨停 ±30%, 下限 29.0%


def _is_star_or_chinext_symbol(symbol: str) -> bool:
    """688 (科创板) / 300 / 301 (创业板) → ±20% 涨跌停板."""
    return symbol.startswith(("688", "300", "301"))


def limit_up_pct_for_ticker(ticker: Any) -> float:
    """返回该 ticker 的涨停 pct_change 判定下限 (保守, 真实涨停的 ~95%).

    板块规则 (2026):
        - 主板 (沪 60 / 深 00): ±10% → 9.5%
        - 科创板 (688) / 创业板 (300/301): ±20% → 19.5%
        - 北交所 (43/83/87/92 / 8/4 开头): ±30% → 29.0%
        - 其它/未知: 保守用主板口径 9.5% (不误判非主板为涨停)

    Args:
        ticker: 6 位代码或带后缀 (如 "688037", "300903.SZ")

    Returns:
        涨停判定下限 pct (如 9.5 / 19.5 / 29.0). BTST setup 用 ``pct_change >=
        limit_up_pct_for_ticker(ticker)`` 判涨停, 替代旧的固定 9.5 常量.
    """
    symbol = get_ashare_symbol(ticker)
    if _is_star_or_chinext_symbol(symbol):
        return _LIMIT_UP_PCT_STAR
    if symbol.startswith(("43", "83", "87")) or is_beijing_exchange_stock(symbol=symbol):
        return _LIMIT_UP_PCT_BJ
    return _LIMIT_UP_PCT_MAIN
