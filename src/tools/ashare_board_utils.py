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
    return (
        normalized_market.str.upper().eq("BJ")
        | normalized_market.eq("北交所")
        | build_beijing_exchange_mask_from_series(ts_code_series)
        | symbol_series.fillna("").astype(str).str.strip().str.startswith(BEIJING_EXCHANGE_SYMBOL_PREFIXES)
    )