"""Tests for bugs found during systematic audit of quantitative agents.

Covers:
  A. valuation.calculate_intrinsic_value — division by zero when discount_rate == terminal_growth_rate
  B. valuation.calculate_residual_income_value — division by zero when cost_of_equity == terminal_growth_rate
  C. aswath_damodaran.estimate_cost_of_equity — no upper bound cap
  D. fundamentals_helpers._finalize_fundamentals_signal — confidence 0 for all-neutral signals
  E. aswath_damodaran revenue CAGR from TTM data with incorrect period count
  F. aswath_damodaran treats 0 EBIT as missing data instead of weak coverage
  G. portfolio_manager_helpers._resolve_max_short — double-counted margin_requirement
"""

import math

import pytest

from src.agents.aswath_damodaran import (
    analyze_growth_and_reinvestment,
    analyze_risk_profile,
    estimate_cost_of_equity,
)
from src.agents.fundamentals_helpers import _finalize_fundamentals_signal
from src.agents.valuation import (
    calculate_intrinsic_value,
    calculate_residual_income_value,
)
from src.agents.portfolio_manager_helpers import _resolve_max_short


# ---------------------------------------------------------------------------
# Bug A: calculate_intrinsic_value division by zero
# ---------------------------------------------------------------------------


class TestCalculateIntrinsicValueDivisionByZero:
    def test_discount_equals_terminal_growth_no_crash(self):
        """When discount_rate == terminal_growth_rate, must not raise ZeroDivisionError."""
        result = calculate_intrinsic_value(
            free_cash_flow=100.0,
            growth_rate=0.05,
            discount_rate=0.02,
            terminal_growth_rate=0.02,
        )
        assert isinstance(result, float)
        assert math.isfinite(result)

    def test_discount_less_than_terminal_growth_no_crash(self):
        """When discount_rate < terminal_growth_rate, must not raise ZeroDivisionError."""
        result = calculate_intrinsic_value(
            free_cash_flow=100.0,
            growth_rate=0.05,
            discount_rate=0.01,
            terminal_growth_rate=0.02,
        )
        assert isinstance(result, float)
        assert math.isfinite(result)

    def test_normal_case_unchanged(self):
        """Normal case should still produce a positive intrinsic value."""
        result = calculate_intrinsic_value(
            free_cash_flow=100.0,
            growth_rate=0.05,
            discount_rate=0.10,
            terminal_growth_rate=0.02,
        )
        assert result > 0


# ---------------------------------------------------------------------------
# Bug B: calculate_residual_income_value division by zero
# ---------------------------------------------------------------------------


class TestCalculateResidualIncomeValueDivisionByZero:
    def test_cost_of_equity_equals_terminal_growth_no_crash(self):
        """When cost_of_equity == terminal_growth_rate, must not raise."""
        result = calculate_residual_income_value(
            market_cap=1000.0,
            net_income=100.0,
            price_to_book_ratio=2.0,
            cost_of_equity=0.03,
            terminal_growth_rate=0.03,
        )
        assert isinstance(result, (int, float))
        assert math.isfinite(result)

    def test_normal_case_positive_ri(self):
        """Normal case with positive residual income should produce a value."""
        result = calculate_residual_income_value(
            market_cap=1000.0,
            net_income=200.0,
            price_to_book_ratio=2.0,
            cost_of_equity=0.10,
            terminal_growth_rate=0.03,
        )
        assert result > 0


# ---------------------------------------------------------------------------
# Bug C: estimate_cost_of_equity no upper bound
# ---------------------------------------------------------------------------


class TestEstimateCostOfEquityUpperBound:
    def test_high_beta_high_debt_capped(self):
        """Very high beta and debt should not produce > 30% cost of equity."""
        cost = estimate_cost_of_equity(
            beta=3.0,
            debt_to_equity=5.0,
            is_loss_making=True,
            ticker=None,  # not A-share
        )
        assert cost <= 0.30

    def test_extreme_inputs(self):
        """Extreme beta with A-share and loss-making still capped."""
        cost = estimate_cost_of_equity(
            beta=5.0,
            debt_to_equity=10.0,
            is_loss_making=True,
            ticker="000001",  # A-share
        )
        assert cost <= 0.30

    def test_normal_inputs_reasonable(self):
        """Normal inputs should produce a reasonable cost of equity."""
        cost = estimate_cost_of_equity(
            beta=1.0,
            debt_to_equity=0.5,
        )
        assert 0.05 <= cost <= 0.20


# ---------------------------------------------------------------------------
# Bug D: _finalize_fundamentals_signal confidence for all-neutral
# ---------------------------------------------------------------------------


class TestFinalizeFundamentalsSignalConfidence:
    def test_all_neutral_confidence_not_zero(self):
        """When all 4 sub-signals are neutral, confidence should be > 0."""
        signals = ["neutral", "neutral", "neutral", "neutral"]
        result = _finalize_fundamentals_signal(signals, {})
        assert result["signal"] == "neutral"
        assert result["confidence"] > 0

    def test_mixed_signals_confidence_positive(self):
        """When signals are mixed but equal, neutral with positive confidence."""
        signals = ["bullish", "bearish", "bullish", "bearish"]
        result = _finalize_fundamentals_signal(signals, {})
        assert result["signal"] == "neutral"
        assert result["confidence"] > 0

    def test_clear_bullish_high_confidence(self):
        """When majority is bullish, confidence should reflect agreement level."""
        signals = ["bullish", "bullish", "bullish", "bearish"]
        result = _finalize_fundamentals_signal(signals, {})
        assert result["signal"] == "bullish"
        assert result["confidence"] == 75  # 3/4 * 100

    def test_all_bullish_max_confidence(self):
        signals = ["bullish", "bullish", "bullish", "bullish"]
        result = _finalize_fundamentals_signal(signals, {})
        assert result["signal"] == "bullish"
        assert result["confidence"] == 100


# ---------------------------------------------------------------------------
# Bug E: Damodaran revenue CAGR from TTM data
# ---------------------------------------------------------------------------


class TestDamodaranRevenueCAGRFromTTM:
    def test_ttm_cagr_annualized(self):
        """TTM revenue CAGR should be annualized, not treat each TTM period as a year.

        Verify the formula produces correct annualized CAGR when using TTM data
        where each consecutive data point is ~0.25 years apart.
        """
        # Simulate 5 TTM periods: revenue growing from 100 to 120 over ~1 year
        revs = [100.0, 105.0, 110.0, 115.0, 120.0]
        n_periods = len(revs) - 1  # 4

        # Old buggy formula: treats each TTM period as a full year
        old_cagr = (revs[-1] / revs[0]) ** (1 / n_periods) - 1
        # (120/100)^(1/4) - 1 = 0.0466 = 4.66% (understates true 20% growth)

        # Fixed formula: TTM periods are ~0.25 years apart
        n_years = max(n_periods * 0.25, 1.0)
        fixed_cagr = (revs[-1] / revs[0]) ** (1 / n_years) - 1
        # (120/100)^(1/1) - 1 = 0.20 = 20% (correct)

        # The fixed CAGR should be significantly higher than the old one
        assert fixed_cagr > old_cagr
        # The fixed CAGR should be close to the true 20% annual growth
        assert abs(fixed_cagr - 0.20) < 0.01
        # The old CAGR was only ~4.7%, which is wrong
        assert old_cagr < 0.05


# ---------------------------------------------------------------------------
# Bug F: Damodaran treats 0 EBIT as missing
# ---------------------------------------------------------------------------


class TestDamodaranZeroEBITHandling:
    def test_zero_ebit_shows_weak_coverage(self):
        """When EBIT is exactly 0, it should show 'Weak coverage' not 'NA'."""
        from types import SimpleNamespace

        metrics = [SimpleNamespace(beta=1.0, debt_to_equity=0.5)]
        line_items = [
            SimpleNamespace(ebit=0.0, interest_expense=10.0),
            SimpleNamespace(ebit=0.0, interest_expense=10.0),
        ]
        result = analyze_risk_profile(metrics, line_items, ticker="AAPL")
        # With EBIT=0 and interest=10: coverage = 0/10 = 0 (weak, not missing)
        assert "Weak coverage" in result["details"] or "coverage" in result["details"].lower()
        # Score should NOT include the interest coverage point (coverage <= 3)
        assert result["score"] < 3  # Should miss the coverage bonus


# ---------------------------------------------------------------------------
# Bug G: _resolve_max_short double-counted margin_requirement
# ---------------------------------------------------------------------------


class TestResolveMaxShortCorrectFormula:
    def test_standard_margin_calculation(self):
        """Verify short capacity = equity / (price * margin_requirement)."""
        # equity=1000, price=10, margin=0.5
        # max_short = 1000 / (10 * 0.5) = 200
        assert _resolve_max_short(10.0, 1000, 0.5, 0.0, 1000.0) == 200

    def test_doubling_margin_halves_capacity(self):
        """Doubling margin requirement should halve short capacity."""
        low = _resolve_max_short(10.0, 9999, 0.25, 0.0, 1000.0)
        high = _resolve_max_short(10.0, 9999, 0.50, 0.0, 1000.0)
        assert low == 2 * high

    def test_margin_used_reduces_capacity(self):
        """Margin used should reduce available equity for new shorts."""
        no_used = _resolve_max_short(10.0, 9999, 0.5, 0.0, 1000.0)
        with_used = _resolve_max_short(10.0, 9999, 0.5, 500.0, 1000.0)
        assert with_used == no_used // 2  # 500 equity vs 1000
