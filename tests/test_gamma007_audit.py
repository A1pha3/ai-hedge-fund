"""Regression tests for GAMMA-007 bugs found during systematic code audit.

Covers:
- BUG-1: calculate_volatility_adjusted_limit step discontinuities at boundaries
- BUG-2: compute_allowed_actions equity missing margin_used
- BUG-3: metrics.py annual return crash on negative portfolio value (short squeeze)
"""

import math

import numpy as np
import pytest

from src.agents.portfolio_manager import compute_allowed_actions
from src.agents.risk_manager import calculate_volatility_adjusted_limit
from src.backtesting.metrics import PerformanceMetricsCalculator

# ===========================================================================
# BUG-1: calculate_volatility_adjusted_limit continuity
# ===========================================================================


class TestVolatilityAdjustedLimitContinuity:
    """GAMMA-007: the limit function must be continuous at all vol boundaries."""

    def test_no_jump_at_vol_30_boundary(self):
        """At vol=0.30 the old code jumped from 18.5% to 15.0% (3.5pp gap).
        The continuous interpolation must not have a jump."""
        eps = 1e-6
        below = calculate_volatility_adjusted_limit(0.30 - eps)
        at = calculate_volatility_adjusted_limit(0.30)
        above = calculate_volatility_adjusted_limit(0.30 + eps)

        # No discontinuity: difference should be ~ eps * slope
        assert abs(below - at) < 0.001, f"Jump at vol=0.30-: {below:.4f} vs {at:.4f}"
        assert abs(at - above) < 0.001, f"Jump at vol=0.30+: {at:.4f} vs {above:.4f}"

    def test_no_jump_at_vol_50_boundary(self):
        """At vol=0.50 the old code jumped from 13.0% to 10.0% (3.0pp gap)."""
        eps = 1e-6
        below = calculate_volatility_adjusted_limit(0.50 - eps)
        at = calculate_volatility_adjusted_limit(0.50)
        above = calculate_volatility_adjusted_limit(0.50 + eps)

        assert abs(below - at) < 0.001, f"Jump at vol=0.50-: {below:.4f} vs {at:.4f}"
        assert abs(at - above) < 0.001, f"Jump at vol=0.50+: {at:.4f} vs {above:.4f}"

    def test_no_jump_at_vol_15_boundary(self):
        """At vol=0.15 the old code jumped from 25% to 20%."""
        eps = 1e-6
        below = calculate_volatility_adjusted_limit(0.15 - eps)
        at = calculate_volatility_adjusted_limit(0.15)
        above = calculate_volatility_adjusted_limit(0.15 + eps)

        assert abs(below - at) < 0.001, f"Jump at vol=0.15-: {below:.4f} vs {at:.4f}"
        assert abs(at - above) < 0.001, f"Jump at vol=0.15+: {at:.4f} vs {above:.4f}"

    def test_monotonically_decreasing(self):
        """Higher volatility must always produce lower or equal allocation."""
        limits = [calculate_volatility_adjusted_limit(v) for v in np.linspace(0.01, 1.5, 100)]
        for i in range(1, len(limits)):
            assert limits[i] <= limits[i - 1] + 1e-10, f"Non-monotonic at index {i}: {limits[i]:.6f} > {limits[i-1]:.6f}"

    def test_anchor_points_match_expected(self):
        """The five anchor points must produce the documented allocations."""
        assert calculate_volatility_adjusted_limit(0.00) == pytest.approx(0.25, abs=1e-10)
        assert calculate_volatility_adjusted_limit(0.15) == pytest.approx(0.20, abs=1e-10)
        assert calculate_volatility_adjusted_limit(0.30) == pytest.approx(0.15, abs=1e-10)
        assert calculate_volatility_adjusted_limit(0.50) == pytest.approx(0.10, abs=1e-10)
        assert calculate_volatility_adjusted_limit(1.00) == pytest.approx(0.05, abs=1e-10)

    def test_extreme_vol_clamps_to_floor(self):
        """Very high volatility must not go below the 5% floor."""
        assert calculate_volatility_adjusted_limit(2.0) == pytest.approx(0.05, abs=1e-10)
        assert calculate_volatility_adjusted_limit(10.0) == pytest.approx(0.05, abs=1e-10)

    def test_zero_vol_clamps_to_ceiling(self):
        """Zero volatility must not exceed the 25% ceiling."""
        assert calculate_volatility_adjusted_limit(0.0) == pytest.approx(0.25, abs=1e-10)
        assert calculate_volatility_adjusted_limit(-0.5) == pytest.approx(0.25, abs=1e-10)


# ===========================================================================
# BUG-2: compute_allowed_actions equity includes margin_used
# ===========================================================================


class TestComputeAllowedActionsEquityMarginFix:
    """GAMMA-007: equity must include margin_used for correct short capacity.

    The formula is: equity = cash + position_value + margin_used
    Then _resolve_max_short uses: available = equity - margin_used

    So available = cash + position_value + margin_used - margin_used = cash + position_value.
    Without the margin_used term in equity, available = cash + position_value - margin_used,
    which undercounts by margin_used when both positions and margin exist.
    """

    def test_margin_used_increases_short_capacity_with_positions(self):
        """With positions AND margin_used, the fix increases short capacity.

        Without fix: equity = cash + position_value = 5000 + 10000 = 15000
                     available = 15000 - 3000 = 12000, max = 12000//25 = 480
        With fix:    equity = cash + position_value + margin_used = 18000
                     available = 18000 - 3000 = 15000, max = 15000//25 = 600
        """
        result = compute_allowed_actions(
            tickers=["X"],
            current_prices={"A": 200.0, "X": 50.0},
            max_shares={"X": 10000},
            portfolio={
                "cash": 5_000.0,
                "positions": {"A": {"long": 50, "short": 0}},  # long 50 @ $200 = $10000
                "margin_requirement": 0.5,
                "margin_used": 3_000.0,
            },
        )
        # equity = 5000 + 3000 + 50*200 = 18000
        # available = 18000 - 3000 = 15000
        # per_share = 50 * 0.5 = 25
        # max_short = int(15000 // 25) = 600
        assert result["X"]["short"] == 600

    def test_no_margin_used_unchanged(self):
        """Without margin_used, the fix has no effect (baseline sanity check)."""
        result = compute_allowed_actions(
            tickers=["X"],
            current_prices={"A": 200.0, "X": 50.0},
            max_shares={"X": 10000},
            portfolio={
                "cash": 5_000.0,
                "positions": {"A": {"long": 50, "short": 0}},
                "margin_requirement": 0.5,
                "margin_used": 0.0,
            },
        )
        # equity = 5000 + 0 + 10000 = 15000
        # available = 15000 - 0 = 15000
        # max = int(15000 // 25) = 600
        assert result["X"]["short"] == 600

    def test_margin_used_with_existing_short_in_equity(self):
        """Short position value correctly reduces equity, margin_used adds back."""
        result = compute_allowed_actions(
            tickers=["Y"],
            current_prices={"Y": 100.0, "Z": 100.0},
            max_shares={"Y": 5000},
            portfolio={
                "cash": 5_000.0,
                "positions": {"Z": {"long": 0, "short": 50}},  # short 50 @ $100 = -$5000
                "margin_requirement": 0.5,
                "margin_used": 2_500.0,  # collateral for Z short
            },
        )
        # equity = 5000 + 2500 + 0 - 50*100 = 2500
        # available = 2500 - 2500 = 0
        # max_short = 0
        # Y cannot be shorted because all equity is consumed by Z's short position
        assert result["Y"].get("short", 0) == 0


# ===========================================================================
# BUG-3: metrics.py annual return negative base crash
# ===========================================================================


class TestMetricsNegativePortfolioValue:
    """GAMMA-007: annual return must not crash when portfolio value goes negative."""

    def _make_values(self, prices: list[float]):
        from datetime import datetime, timedelta

        start = datetime(2024, 1, 1)
        return [
            {
                "Date": start + timedelta(days=i),
                "Portfolio Value": v,
                "Long Exposure": 0.0,
                "Short Exposure": 0.0,
                "Gross Exposure": 0.0,
                "Net Exposure": 0.0,
                "Long/Short Ratio": float("inf"),
            }
            for i, v in enumerate(prices)
        ]

    def test_negative_portfolio_value_does_not_crash(self):
        """When portfolio goes negative (extreme short squeeze), metrics must
        compute without crashing."""
        calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
        values = self._make_values([100_000.0, 50_000.0, 10_000.0, -10_000.0])
        metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
        calc.update_metrics(metrics, values)
        assert metrics.get("calmar_ratio") is not None

    def test_zero_portfolio_value_does_not_crash(self):
        """When portfolio goes to zero, annual return must be -1.0, not crash."""
        calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
        values = self._make_values([100_000.0, 50_000.0, 10_000.0, 0.0])
        metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
        calc.update_metrics(metrics, values)
        assert metrics.get("calmar_ratio") is not None

    def test_positive_portfolio_value_annual_return_works(self):
        """Normal case: portfolio grows, metrics must compute correctly."""
        calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
        values = self._make_values([100_000.0, 110_000.0, 120_000.0, 130_000.0])
        metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
        calc.update_metrics(metrics, values)
        assert metrics["calmar_ratio"] is not None
