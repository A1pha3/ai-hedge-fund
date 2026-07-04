"""TDD red test: calculate_portfolio_value / compute_exposures must not
propagate NaN price into the NAV (R154 family defense-in-depth on the
money-path NAV core — R78 precedent: latent finite-guards on the critical
path even when current callers are guarded upstream).

R156 drained the upstream price-dict construction (load_current_prices /
hydrate_position_prices) so NaN close never reaches ``current_prices`` in the
normal flow. But ``calculate_portfolio_value`` / ``compute_exposures`` are the
PUBLIC NAV-core functions — the last line of defense. A single NaN price in
the dict (from a future caller, a replay/snapshot, or an upstream regression)
makes ``pos["long"] * NaN = NaN`` → ``total_value += NaN`` → the ENTIRE NAV
becomes NaN, silently poisoning sharpe/sortino/max_drawdown/drawdown_date.

R78 precedent: composite_score dimension bonuses got finite-guards even though
the 5 calculators never produced NaN (latent defense-in-depth on the critical
scoring path). Same principle here for the NAV core. Fix: treat NaN price as
0.0 (position unvalued — conservative, the position cannot be marked).
"""

from __future__ import annotations

import math

import pytest

from src.backtesting.valuation import calculate_portfolio_value, compute_exposures


def test_calculate_portfolio_value_nan_price_does_not_corrupt_nav(portfolio) -> None:
    """A NaN price for one position must not make the entire NAV NaN — the
    NaN-price position should contribute 0 (unvalued), not poison the total."""
    portfolio.apply_long_buy("AAPL", 10, 100.0)
    portfolio.apply_long_buy("MSFT", 5, 200.0)

    # Normal NAV (control): 10*100 + 5*200 = 2000 long + cash
    normal_prices = {"AAPL": 100.0, "MSFT": 200.0}
    normal_nav = calculate_portfolio_value(portfolio, normal_prices)
    assert math.isfinite(normal_nav)

    # NaN price for MSFT — must NOT corrupt the entire NAV
    nan_prices = {"AAPL": 100.0, "MSFT": float("nan")}
    nan_nav = calculate_portfolio_value(portfolio, nan_prices)
    assert isinstance(nan_nav, float)
    assert math.isfinite(nan_nav), "NaN price for one position must not make the entire NAV NaN; " "a single NaN poisons sharpe/sortino/drawdown silently. Treat NaN " "price as 0.0 (position unvalued), not as NaN propagation"
    # MSFT (NaN price) contributes 0; AAPL contributes 10*100=1000
    # nan_nav should equal cash + margin_used + 1000 (AAPL only)
    snap = portfolio.get_snapshot()
    expected = snap["cash"] + snap["margin_used"] + 10 * 100.0
    assert nan_nav == pytest.approx(expected)


def test_compute_exposures_nan_price_does_not_corrupt(portfolio) -> None:
    """A NaN price must not make Long/Short/Gross/Net exposure NaN."""
    portfolio.apply_long_buy("AAPL", 10, 100.0)
    portfolio.apply_long_buy("MSFT", 5, 200.0)

    nan_prices = {"AAPL": 100.0, "MSFT": float("nan")}
    exp = compute_exposures(portfolio, nan_prices)
    # All exposure values must be finite
    for key in ("Long Exposure", "Short Exposure", "Gross Exposure", "Net Exposure"):
        assert math.isfinite(float(exp[key])), f"{key} must be finite — NaN price must not propagate to exposures"
    # AAPL contributes 1000 long; MSFT (NaN) contributes 0
    assert exp["Long Exposure"] == pytest.approx(1000.0)


def test_normal_prices_unchanged(portfolio) -> None:
    """Normal prices must produce the same result (behavior-preserving)."""
    portfolio.apply_long_buy("AAPL", 10, 100.0)
    portfolio.apply_short_open("MSFT", 5, 200.0)
    prices = {"AAPL": 100.0, "MSFT": 200.0}

    value = calculate_portfolio_value(portfolio, prices)
    snap = portfolio.get_snapshot()
    expected = snap["cash"] + snap["margin_used"] + 10 * 100.0 - 5 * 200.0
    assert value == pytest.approx(expected)

    exp = compute_exposures(portfolio, prices)
    assert exp["Long Exposure"] == pytest.approx(1000.0)
    assert exp["Short Exposure"] == pytest.approx(1000.0)
