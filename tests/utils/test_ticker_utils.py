"""Characterization tests for src/utils/ticker_utils.py.

get_currency_context (25 call sites) and get_currency_symbol had zero direct
test coverage. Tests lock down the A-share (CNY/¥) vs US (USD/$) contract.
"""

from __future__ import annotations

import pytest

from src.utils.ticker_utils import get_currency_context, get_currency_symbol


class TestGetCurrencySymbol:
    @pytest.mark.parametrize("ticker", ["000001", "300118", "600519", "000880"])
    def test_ashare_returns_cny(self, ticker: str) -> None:
        assert get_currency_symbol(ticker) == "¥"

    @pytest.mark.parametrize("ticker", ["AAPL", "GOOGL", "MSFT", "NVDA", "TSLA"])
    def test_us_returns_usd(self, ticker: str) -> None:
        assert get_currency_symbol(ticker) == "$"

    def test_non_six_digit_is_usd(self) -> None:
        """3-digit '123' is not an A-share ticker → $."""
        assert get_currency_symbol("123") == "$"

    def test_suffixed_ticker_is_usd(self) -> None:
        """'000001.SH' has a suffix → treated as non-ashare → $."""
        assert get_currency_symbol("000001.SH") == "$"


class TestGetCurrencyContext:
    @pytest.mark.parametrize("ticker", ["000001", "300118", "600519"])
    def test_ashare_context_mentions_cny(self, ticker: str) -> None:
        ctx = get_currency_context(ticker)
        assert "CNY" in ctx
        assert "¥" in ctx
        assert ticker in ctx

    def test_ashare_context_does_not_say_usd(self) -> None:
        ctx = get_currency_context("000001")
        assert "USD" not in ctx

    @pytest.mark.parametrize("ticker", ["AAPL", "GOOGL", "MSFT"])
    def test_us_context_mentions_usd(self, ticker: str) -> None:
        ctx = get_currency_context(ticker)
        assert "USD" in ctx
        assert "$" in ctx

    def test_us_context_is_concise(self) -> None:
        """US context is a short fixed string without ticker-specific text."""
        ctx = get_currency_context("AAPL")
        assert ctx == "All monetary values are in USD ($)."

    def test_ashare_context_instructs_not_to_use_dollar(self) -> None:
        """The A-share context explicitly tells the LLM NOT to use $."""
        ctx = get_currency_context("000001")
        assert "NOT $" in ctx
