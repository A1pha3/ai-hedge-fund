"""Market data loading logic extracted from BacktestEngine.

This module encapsulates all market data operations: prefetching ticker data,
iterating backtest date ranges, normalizing tickers, shifting business days,
managing exit reentry cooldowns, and loading price / turnover / limit state.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Sequence

import pandas as pd
from dateutil.relativedelta import relativedelta

from src.tools.akshare_api import is_ashare
from src.tools.api import (
    get_company_news,
    get_financial_metrics,
    get_insider_trades,
    get_price_data,
    get_prices,
)
from src.tools.tushare_api import get_limit_list

from .portfolio import Portfolio

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants (moved from engine.py)
# ---------------------------------------------------------------------------

DEFENSIVE_EXIT_REASONS = {"hard_stop_loss", "atr_stop_loss"}
EXIT_REENTRY_COOLDOWN_TRADING_DAYS = max(0, int(os.getenv("PIPELINE_EXIT_REENTRY_COOLDOWN_TRADING_DAYS", "5")))
EXIT_REENTRY_REVIEW_TRADING_DAYS = max(0, int(os.getenv("PIPELINE_EXIT_REENTRY_REVIEW_TRADING_DAYS", "5")))
DEFAULT_US_BENCHMARK_TICKER = "SPY"
DEFAULT_ASHARE_BENCHMARK_TICKER = "000300.SH"


# ---------------------------------------------------------------------------
# Standalone utilities (formerly static methods on BacktestEngine)
# ---------------------------------------------------------------------------

def normalize_ticker(ticker: str) -> str:
    return str(ticker).split(".")[0].upper()


def shift_business_days(trade_date_compact: str, business_days: int) -> str:
    shifted = pd.Timestamp(datetime.strptime(trade_date_compact, "%Y%m%d")) + pd.offsets.BDay(max(0, business_days))
    return shifted.strftime("%Y%m%d")


def resolve_benchmark_ticker(tickers: Sequence[str]) -> str:
    normalized_tickers = [str(ticker).strip() for ticker in tickers if str(ticker).strip()]
    if normalized_tickers and all(is_ashare(ticker) for ticker in normalized_tickers):
        return DEFAULT_ASHARE_BENCHMARK_TICKER
    return DEFAULT_US_BENCHMARK_TICKER


def _is_suspended_row(row) -> bool:
    """BETA-007 shared suspension guard.

    Returns True when *row* (a price-frame row) represents a suspended /
    zero-volume trading day (``volume`` column present and ``<= 0``). Used by
    both ``load_current_prices`` and ``hydrate_position_prices`` so the two
    price-loading paths apply an identical "do not trade / mark at the phantom
    carry-forward close" rule. A missing ``volume`` column is treated as
    tradable (data-source compatibility).
    """
    volume = row.get("volume")
    return volume is not None and float(volume) <= 0


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
        data_through: str | None = None,
    ) -> None:
        self._tickers = tickers
        self._start_date = start_date
        self._end_date = end_date
        self._portfolio = portfolio
        self._exit_reentry_cooldowns = exit_reentry_cooldowns
        # GAMMA-007: embargo bound. When set, prefetch clamps the feature-warmup
        # window to ``min(end_date, data_through)`` so the loader never reads
        # data published after the simulated trade horizon. Walk-forward callers
        # pass ``data_through=test_end`` (or the last trading day of the window)
        # to make the no-look-ahead contract self-enforcing instead of trusting
        # each caller to pass a correctly-truncated ``end_date``. None keeps the
        # original "fetch through end_date" behavior (single-window backtests).
        self._data_through = data_through

    # ------------------------------------------------------------------
    # Data prefetch
    # ------------------------------------------------------------------

    def prefetch_data(self) -> None:
        # GAMMA-007: the feature-warmup fetch horizon. Clamp to data_through so a
        # window whose end_date overshoots its last legitimate trading day never
        # loads post-window prices into the feature cache.
        fetch_end = self._end_date
        if self._data_through is not None and self._data_through < self._end_date:
            fetch_end = self._data_through

        end_date_dt = datetime.strptime(fetch_end, "%Y-%m-%d")
        start_date_dt = end_date_dt - relativedelta(years=1)
        start_date_str = start_date_dt.strftime("%Y-%m-%d")

        for ticker in self._tickers:
            get_prices(ticker, start_date_str, fetch_end)
            get_financial_metrics(ticker, fetch_end, limit=10)
            get_insider_trades(ticker, fetch_end, start_date=self._start_date, limit=1000)
            get_company_news(ticker, fetch_end, start_date=self._start_date, limit=1000)

        benchmark_ticker = resolve_benchmark_ticker(self._tickers)
        get_prices(benchmark_ticker, self._start_date, fetch_end)

    # ------------------------------------------------------------------
    # Date iteration
    # ------------------------------------------------------------------

    def iter_backtest_dates(self) -> pd.DatetimeIndex:
        """A-share trading days over the backtest window.

        R38: previously used ``pd.date_range(freq="B")`` — the generic Mon–Fri
        business calendar, which includes Chinese public holidays (Spring
        Festival, National Day, etc.). On a holiday ``load_current_prices``
        falls back to the prior session's close, producing phantom zero-return
        bars that dilute Sharpe/annualization (extra zero-return days). Now
        prefer the real A-share trading calendar via ``get_open_trade_dates``
        (trade_cal); on any failure (no token, network, empty) fall back to
        ``freq="B"`` so the backtest still runs.
        """
        try:
            from src.tools.tushare_api import get_open_trade_dates

            start_compact = self._start_date.replace("-", "")
            end_compact = self._end_date.replace("-", "")
            open_dates = get_open_trade_dates(start_compact, end_compact)
            if open_dates:
                return pd.DatetimeIndex([pd.Timestamp(d) for d in open_dates])
            # Empty result (no token / API failure) → fall back to business-day cal.
        except Exception as e:  # noqa: BLE001 — never block the backtest on calendar fetch
            print(f"[Backtest] trade_cal 获取失败，回退到 freq=B 工作日历: {e}")
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
                    logger.warning("load_current_prices: no price data for ticker=%s (%s ~ %s)", ticker, previous_date_str, current_date_str)
                    continue
                row = price_data.iloc[-1]
                # BETA-007: 停牌检测 — volume=0 表示当日未成交 (停牌), 不可交易。
                # 若包含则回测会在停牌日按 carry-forward 价格"虚拟成交"导致结果失真。
                if _is_suspended_row(row):
                    logger.debug(
                        "load_current_prices: ticker=%s 停牌或零成交 (%s), 跳过",
                        ticker, current_date_str,
                    )
                    continue
                current_prices[ticker] = float(row["close"])
            except Exception:
                logger.warning("load_current_prices: exception loading price for ticker=%s (%s ~ %s)", ticker, previous_date_str, current_date_str, exc_info=True)
                continue
        if not current_prices:
            logger.warning("load_current_prices: all %d tickers failed (%s ~ %s)", len(tickers), previous_date_str, current_date_str)
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
                    row = price_data.iloc[-1]
                    # BETA-007-drain: apply the SAME suspension guard as
                    # load_current_prices. A held position that suspends
                    # (volume=0) must NOT be marked-to-market at the phantom
                    # carry-forward close — that silently inflates NAV/drawdown
                    # and defeats the BETA-007 protection. Fall back to cost
                    # basis (long) / cost basis (short) instead, matching the
                    # pre-existing fallback below.
                    if _is_suspended_row(row):
                        logger.debug(
                            "hydrate_position_prices: ticker=%s 停牌或零成交 (%s), 回退 cost_basis",
                            ticker, current_date_str,
                        )
                    else:
                        hydrated_prices[ticker] = float(row["close"])
                        continue
            except Exception:
                pass
            if fallback_price > 0:
                hydrated_prices[ticker] = fallback_price
        return hydrated_prices
