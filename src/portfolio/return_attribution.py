"""Simplified Brinson return attribution model.

Decomposes portfolio returns into allocation (配置) and selection (选择) contributions
per ticker, using a benchmark as reference. When no external benchmark is provided,
an equal-weight portfolio is used as the benchmark.

Brinson decomposition (simplified, no interaction term):
    Allocation contribution (配置贡献) = sum_ticker (w_p - w_b) * r_b
    Selection contribution (选择贡献) = sum_ticker w_p * (r_p - r_b)
    Residual (残差) = total_return - allocation - selection

Where:
    w_p = portfolio weight of ticker
    w_b = benchmark weight of ticker
    r_p = portfolio return of ticker
    r_b = benchmark return of ticker
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence


def _is_finite(value: Any) -> bool:
    """Return True iff value is a real number (int/float) and not NaN/Inf."""
    if isinstance(value, bool):
        return True
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _assert_finite_mapping(name: str, mapping: Mapping[str, Any]) -> None:
    """Raise ValueError when any value in *mapping* is non-finite (NaN/Inf)."""
    bad = [k for k, v in mapping.items() if not _is_finite(v)]
    if bad:
        raise ValueError(
            f"{name} contains non-finite values (NaN/Inf) for: {bad[:5]}"
            f"{' ...' if len(bad) > 5 else ''}"
        )


@dataclass(frozen=True)
class TickerAttribution:
    """Per-ticker attribution result."""

    ticker: str
    portfolio_weight: float
    benchmark_weight: float
    portfolio_return: float
    benchmark_return: float
    allocation_contribution: float
    selection_contribution: float
    total_contribution: float


@dataclass(frozen=True)
class AttributionResult:
    """Aggregated attribution result for a time period."""

    start_date: str
    end_date: str
    tickers: list[TickerAttribution] = field(default_factory=list)
    total_allocation_contribution: float = 0.0
    total_selection_contribution: float = 0.0
    total_residual: float = 0.0
    total_portfolio_return: float = 0.0
    total_benchmark_return: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_portfolio_return": self.total_portfolio_return,
            "total_benchmark_return": self.total_benchmark_return,
            "total_allocation_contribution": self.total_allocation_contribution,
            "total_selection_contribution": self.total_selection_contribution,
            "total_residual": self.total_residual,
            "tickers": [
                {
                    "ticker": t.ticker,
                    "portfolio_weight": t.portfolio_weight,
                    "benchmark_weight": t.benchmark_weight,
                    "portfolio_return": t.portfolio_return,
                    "benchmark_return": t.benchmark_return,
                    "allocation_contribution": t.allocation_contribution,
                    "selection_contribution": t.selection_contribution,
                    "total_contribution": t.total_contribution,
                }
                for t in sorted(self.tickers, key=lambda x: x.total_contribution, reverse=True)
            ],
        }


def compute_equal_weight_benchmark(
    tickers: Sequence[str],
    ticker_returns: Mapping[str, float],
) -> dict[str, float]:
    """Compute equal-weight benchmark weights and returns.

    Returns a dict mapping ticker -> benchmark weight (1/N for each ticker
    that has a return, 0 for tickers with no return).
    """
    active_tickers = [t for t in tickers if t in ticker_returns]
    n = len(active_tickers)
    if n == 0:
        return {t: 0.0 for t in tickers}
    return {t: (1.0 / n if t in ticker_returns else 0.0) for t in tickers}


def compute_benchmark_returns_from_equal_weight(
    ticker_returns: Mapping[str, float],
    benchmark_weights: Mapping[str, float],
) -> float:
    """Compute the total benchmark return from weights and individual returns."""
    return sum(benchmark_weights.get(t, 0.0) * ticker_returns.get(t, 0.0) for t in ticker_returns)


def compute_portfolio_weights(
    ticker_market_values: Mapping[str, float],
    total_portfolio_value: float,
) -> dict[str, float]:
    """Compute portfolio weights from market values.

    Handles shorts by treating their market value as negative contribution.
    """
    if total_portfolio_value == 0.0:
        return {t: 0.0 for t in ticker_market_values}
    return {t: mv / total_portfolio_value for t, mv in ticker_market_values.items()}


def brinson_attribution(
    *,
    start_date: str,
    end_date: str,
    ticker_returns: Mapping[str, float],
    ticker_market_values: Mapping[str, float],
    total_portfolio_value: float,
    benchmark_weights: Mapping[str, float] | None = None,
    benchmark_returns: Mapping[str, float] | None = None,
) -> AttributionResult:
    """Run simplified Brinson attribution analysis.

    Args:
        start_date: Period start date (ISO format string).
        end_date: Period end date (ISO format string).
        ticker_returns: Per-ticker total return over the period (e.g. 0.05 for +5%).
        ticker_market_values: Per-ticker market value at period start (long positive,
            short negative).
        total_portfolio_value: Total portfolio value at period start.
        benchmark_weights: Optional per-ticker benchmark weights. If None, equal-weight
            benchmark is used for tickers with returns.
        benchmark_returns: Optional per-ticker benchmark returns. If None, uses
            ticker_returns as benchmark returns (i.e., the benchmark holds the same
            stocks, so selection contribution measures weight differences only).

    Returns:
        AttributionResult with per-ticker and aggregate attribution.
    """
    if not ticker_returns or total_portfolio_value == 0.0:
        return AttributionResult(start_date=start_date, end_date=end_date)

    # Guard against NaN/Inf silently propagating through the decomposition
    # (which would leave every downstream metric — total return, residual,
    # allocation/selection — as NaN/Inf and crash most JSON consumers).
    _assert_finite_mapping("ticker_returns", ticker_returns)
    _assert_finite_mapping("ticker_market_values", ticker_market_values)
    if not _is_finite(total_portfolio_value):
        raise ValueError(
            f"total_portfolio_value must be a finite number, got {total_portfolio_value!r}"
        )
    if benchmark_weights is not None:
        _assert_finite_mapping("benchmark_weights", benchmark_weights)
    if benchmark_returns is not None:
        _assert_finite_mapping("benchmark_returns", benchmark_returns)

    tickers = list(ticker_returns.keys())

    # Portfolio weights from market values
    portfolio_weights = compute_portfolio_weights(ticker_market_values, total_portfolio_value)

    # Benchmark weights: use provided or default to equal-weight
    if benchmark_weights is not None:
        b_weights: dict[str, float] = {t: benchmark_weights.get(t, 0.0) for t in tickers}
    else:
        b_weights = compute_equal_weight_benchmark(tickers, ticker_returns)

    # Benchmark returns: use provided or default to same as portfolio returns
    if benchmark_returns is not None:
        b_returns: dict[str, float] = {t: benchmark_returns.get(t, 0.0) for t in tickers}
    else:
        b_returns = dict(ticker_returns)

    # Compute per-ticker attribution
    ticker_attributions: list[TickerAttribution] = []
    total_alloc = 0.0
    total_select = 0.0

    for ticker in tickers:
        w_p = portfolio_weights.get(ticker, 0.0)
        w_b = b_weights.get(ticker, 0.0)
        r_p = ticker_returns[ticker]
        r_b = b_returns.get(ticker, 0.0)

        alloc = (w_p - w_b) * r_b
        select = w_p * (r_p - r_b)
        total = alloc + select

        total_alloc += alloc
        total_select += select

        ticker_attributions.append(
            TickerAttribution(
                ticker=ticker,
                portfolio_weight=w_p,
                benchmark_weight=w_b,
                portfolio_return=r_p,
                benchmark_return=r_b,
                allocation_contribution=alloc,
                selection_contribution=select,
                total_contribution=total,
            )
        )

    # Total portfolio return = sum of (weight * return) for each ticker
    total_portfolio_return = sum(
        portfolio_weights.get(t, 0.0) * ticker_returns.get(t, 0.0) for t in tickers
    )

    # Total benchmark return = sum of (benchmark_weight * benchmark_return)
    total_benchmark_return = sum(b_weights.get(t, 0.0) * b_returns.get(t, 0.0) for t in tickers)

    # Residual = what the Brinson decomposition cannot explain
    residual = total_portfolio_return - total_alloc - total_select

    return AttributionResult(
        start_date=start_date,
        end_date=end_date,
        tickers=ticker_attributions,
        total_allocation_contribution=total_alloc,
        total_selection_contribution=total_select,
        total_residual=residual,
        total_portfolio_return=total_portfolio_return,
        total_benchmark_return=total_benchmark_return,
    )


def brinson_attribution_from_snapshots(
    *,
    start_date: str,
    end_date: str,
    portfolio_snapshots: Sequence[Mapping[str, Any]],
    price_snapshots: Sequence[Mapping[str, Any]],
    benchmark_weights: Mapping[str, float] | None = None,
    benchmark_returns: Mapping[str, float] | None = None,
) -> AttributionResult:
    """Run Brinson attribution from raw portfolio and price snapshots.

    This is a convenience wrapper that extracts per-ticker returns and market values
    from snapshot data.

    Args:
        start_date: Period start date (ISO format).
        end_date: Period end date (ISO format).
        portfolio_snapshots: Sequence of portfolio snapshot dicts, each containing
            at least a "positions" key with per-ticker position data. Must have
            at least 2 snapshots (start and end).
        price_snapshots: Sequence of price dicts, each mapping ticker -> price.
            Must be aligned with portfolio_snapshots by index.
        benchmark_weights: Optional benchmark weights.
        benchmark_returns: Optional benchmark returns.

    Returns:
        AttributionResult for the period.
    """
    if len(portfolio_snapshots) < 2 or len(price_snapshots) < 2:
        return AttributionResult(start_date=start_date, end_date=end_date)

    start_positions = portfolio_snapshots[0].get("positions", {})
    end_positions = portfolio_snapshots[-1].get("positions", {})
    start_prices = price_snapshots[0]
    end_prices = price_snapshots[-1]

    # Collect all tickers across start and end
    all_tickers = set(start_positions.keys()) | set(end_positions.keys())

    ticker_returns: dict[str, float] = {}
    ticker_market_values: dict[str, float] = {}

    for ticker in all_tickers:
        start_pos = start_positions.get(ticker, {})
        end_pos = end_positions.get(ticker, {})

        start_long = int(start_pos.get("long", 0))
        start_short = int(start_pos.get("short", 0))
        end_long = int(end_pos.get("long", 0))
        end_short = int(end_pos.get("short", 0))

        p_start = float(start_prices.get(ticker, 0.0))
        p_end = float(end_prices.get(ticker, 0.0))

        # Skip tickers with no price data
        if p_start <= 0.0:
            continue

        # Net market value at start (long positive, short negative)
        start_mv = (start_long - start_short) * p_start
        ticker_market_values[ticker] = start_mv

        # Compute return: if we had a position at start, use price change
        # For simplicity, if no position at start but position at end, skip return
        net_start = start_long - start_short
        if net_start != 0:
            if p_start > 0:
                ticker_returns[ticker] = (p_end / p_start) - 1.0
            else:
                ticker_returns[ticker] = 0.0
        elif end_long > 0 or end_short > 0:
            # New position entered during period — no meaningful return from start
            ticker_returns[ticker] = 0.0

    # Total portfolio value at start
    total_value_start = sum(ticker_market_values.values())
    # Add cash if available in the snapshot
    cash = float(portfolio_snapshots[0].get("cash", 0.0))
    margin_used = float(portfolio_snapshots[0].get("margin_used", 0.0))
    total_value_start += cash + margin_used

    if total_value_start == 0.0:
        return AttributionResult(start_date=start_date, end_date=end_date)

    return brinson_attribution(
        start_date=start_date,
        end_date=end_date,
        ticker_returns=ticker_returns,
        ticker_market_values=ticker_market_values,
        total_portfolio_value=total_value_start,
        benchmark_weights=benchmark_weights,
        benchmark_returns=benchmark_returns,
    )
