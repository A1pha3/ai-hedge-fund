"""Market data loading logic extracted from BacktestEngine.

This module encapsulates all market data operations: prefetching ticker data,
iterating backtest date ranges, normalizing tickers, shifting business days,
managing exit reentry cooldowns, and loading price / turnover / limit state.
"""

from __future__ import annotations

from datetime import datetime
import os
from typing import Sequence

import pandas as pd
from dateutil.relativedelta import relativedelta

from src.tools.tushare_api import get_limit_list
from src.tools.api import (
    get_company_news,
    get_financial_metrics,
    get_insider_trades,
    get_price_data,
    get_prices,
)

from .portfolio import Portfolio


# ---------------------------------------------------------------------------
# Constants (moved from engine.py)
# ---------------------------------------------------------------------------

DEFENSIVE_EXIT_REASONS = {"hard_stop_loss", "atr_stop_loss"}
EXIT_REENTRY_COOLDOWN_TRADING_DAYS = max(0, int(os.getenv("PIPELINE_EXIT_REENTRY_COOLDOWN_TRADING_DAYS", "5")))
EXIT_REENTRY_REVIEW_TRADING_DAYS = max(0, int(os.getenv("PIPELINE_EXIT_REENTRY_REVIEW_TRADING_DAYS", "5")))


# ---------------------------------------------------------------------------
# Standalone utilities (formerly static methods on BacktestEngine)
# ---------------------------------------------------------------------------

def normalize_ticker(ticker: str) -> str:
    return str(ticker).split(".")[0].upper()


def shift_business_days(trade_date_compact: str, business_days: int) -> str:
    shifted = pd.Timestamp(datetime.strptime(trade_date_compact, "%Y%m%d")) + pd.offsets.BDay(max(0, business_days))
    return shifted.strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# MarketDataLoader
# ---------------------------------------------------------------------------

class MarketDataLoader:
    """Handles all market data loading, price hydration, limit state, and
    exit reentry cooldown management for the backtest engine."""

    def __init__(
        self,
        *,
        tickers: list[str],
        start_date: str,
        end_date: str,
        portfolio: Portfolio,
        exit_reentry_cooldowns: dict[str, dict],
    ) -> None:
        self._tickers = tickers
        self._start_date = start_date
        self._end_date = end_date
        self._portfolio = portfolio
        self._exit_reentry_cooldowns = exit_reentry_cooldowns

    # ------------------------------------------------------------------
    # Data prefetch
    # ------------------------------------------------------------------

    def prefetch_data(self) -> None:
        end_date_dt = datetime.strptime(self._end_date, "%Y-%m-%d")
        start_date_dt = end_date_dt - relativedelta(years=1)
        start_date_str = start_date_dt.strftime("%Y-%m-%d")

        for ticker in self._tickers:
            get_prices(ticker, start_date_str, self._end_date)
            get_financial_metrics(ticker, self._end_date, limit=10)
            get_insider_trades(ticker, self._end_date, start_date=self._start_date, limit=1000)
            get_company_news(ticker, self._end_date, start_date=self._start_date, limit=1000)

        # Preload data for SPY for benchmark comparison
        get_prices("SPY", self._start_date, self._end_date)

    # ------------------------------------------------------------------
    # Date iteration
    # ------------------------------------------------------------------

    def iter_backtest_dates(self) -> pd.DatetimeIndex:
        return pd.date_range(self._start_date, self._end_date, freq="B")

    # ------------------------------------------------------------------
    # Exit reentry cooldown management
    # ------------------------------------------------------------------

    def register_exit_reentry_cooldown(self, ticker: str, trade_date_compact: str, trigger_reason: str) -> None:
        if EXIT_REENTRY_COOLDOWN_TRADING_DAYS <= 0 or trigger_reason not in DEFENSIVE_EXIT_REASONS:
            return
        blocked_until = shift_business_days(trade_date_compact, EXIT_REENTRY_COOLDOWN_TRADING_DAYS)
        self._exit_reentry_cooldowns[ticker] = {
            "trigger_reason": trigger_reason,
            "exit_trade_date": trade_date_compact,
            "blocked_until": blocked_until,
            "reentry_review_until": shift_business_days(blocked_until, EXIT_REENTRY_REVIEW_TRADING_DAYS),
        }

    def get_active_exit_reentry_cooldowns(self, trade_date_compact: str) -> dict[str, dict]:
        active: dict[str, dict] = {}
        expired_tickers: list[str] = []
        for ticker, payload in self._exit_reentry_cooldowns.items():
            blocked_until = str(payload.get("blocked_until") or "")
            reentry_review_until = str(payload.get("reentry_review_until") or blocked_until)
            if (blocked_until and trade_date_compact < blocked_until) or (reentry_review_until and trade_date_compact <= reentry_review_until):
                active[ticker] = dict(payload)
                continue
            expired_tickers.append(ticker)
        for ticker in expired_tickers:
            self._exit_reentry_cooldowns.pop(ticker, None)
        return active

    # ------------------------------------------------------------------
    # Limit state
    # ------------------------------------------------------------------

    def get_limit_state(self, trade_date_compact: str) -> tuple[set[str], set[str]]:
        limit_df = get_limit_list(trade_date_compact)
        if limit_df is None or limit_df.empty:
            return set(), set()
        limit_up = {
            normalize_ticker(ts_code)
            for ts_code in limit_df.loc[limit_df["limit"] == "U", "ts_code"].tolist()
        }
        limit_down = {
            normalize_ticker(ts_code)
            for ts_code in limit_df.loc[limit_df["limit"] == "D", "ts_code"].tolist()
        }
        return limit_up, limit_down

    # ------------------------------------------------------------------
    # Turnover data
    # ------------------------------------------------------------------

    def get_daily_turnovers(self, active_tickers: Sequence[str], previous_date_str: str, current_date_str: str) -> dict[str, float]:
        turnovers: dict[str, float] = {}
        for ticker in active_tickers:
            try:
                price_data = get_price_data(ticker, previous_date_str, current_date_str)
                if price_data.empty:
                    continue
                row = price_data.iloc[-1]
                turnovers[ticker] = float(row.get("close", 0.0)) * float(row.get("volume", 0.0))
            except Exception:
                continue
        return turnovers

    # ------------------------------------------------------------------
    # Price loading
    # ------------------------------------------------------------------

    def load_current_prices(self, tickers: Sequence[str], previous_date_str: str, current_date_str: str) -> dict[str, float] | None:
        current_prices: dict[str, float] = {}
        for ticker in tickers:
            try:
                price_data = get_price_data(ticker, previous_date_str, current_date_str)
                if price_data.empty:
                    return None
                current_prices[ticker] = float(price_data.iloc[-1]["close"])
            except Exception:
                return None
        return current_prices

    def hydrate_position_prices(self, current_prices: dict[str, float], previous_date_str: str, current_date_str: str) -> dict[str, float]:
        hydrated_prices = dict(current_prices)
        for ticker, position in self._portfolio.get_positions().items():
            if ticker in hydrated_prices:
                continue
            fallback_price = 0.0
            if int(position.get("long", 0)) > 0:
                fallback_price = float(position.get("long_cost_basis", 0.0) or 0.0)
            elif int(position.get("short", 0)) > 0:
                fallback_price = float(position.get("short_cost_basis", 0.0) or 0.0)
            try:
                price_data = get_price_data(ticker, previous_date_str, current_date_str)
                if price_data is not None and not price_data.empty:
                    hydrated_prices[ticker] = float(price_data.iloc[-1]["close"])
                    continue
            except Exception:
                pass
            if fallback_price > 0:
                hydrated_prices[ticker] = fallback_price
        return hydrated_prices
