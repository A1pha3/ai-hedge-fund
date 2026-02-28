"""Ticker utility functions for currency and market detection."""

from src.tools.akshare_api import is_ashare


def get_currency_context(ticker: str) -> str:
    """Return currency context string for LLM prompts."""
    if is_ashare(ticker):
        return "IMPORTANT: This is a Chinese A-share stock (ticker: {ticker}). All monetary values in the data are in CNY (Chinese Yuan, ¥). Use ¥ symbol when referencing monetary amounts, NOT $. For example: ¥100M, ¥3.7B, ¥11.75/share.".format(ticker=ticker)
    return "All monetary values are in USD ($)."


def get_currency_symbol(ticker: str) -> str:
    """Return appropriate currency symbol for the ticker."""
    return "¥" if is_ashare(ticker) else "$"
