"""TDD red test: CAPM cost-of-equity / WACC public functions must not return NaN
on NaN beta input (R154 same-class drain — public functions where a documented
rate cap is silently violated because Python ``min(NaN, x)`` / ``max(NaN, x)``
return NaN, not the cap).

R154 hardened ``risk_manager.calculate_volatility_adjusted_limit`` /
``calculate_correlation_multiplier`` against NaN inputs. The same vulnerability
class exists in the CAPM valuation path:

1. ``estimate_cost_of_equity(NaN beta)``: ``beta_u = NaN`` → ``cost = risk_free
   + NaN * erp = NaN`` → ``min(cost, 0.30)`` returns NaN (Python ``min`` does
   NOT clamp NaN). The documented "cap cost of equity at 30%" guarantee
   (aswath_damodaran.py:458) is silently violated.

2. ``calculate_wacc(NaN beta_proxy)``: ``cost_of_equity = risk_free + NaN * erp
   = NaN`` → ``wacc = NaN`` → ``min(max(NaN, 0.06), 0.20)`` returns NaN. The
   documented "Floor 6%, cap 20%" guarantee (valuation.py:384) is silently
   violated.

NaN beta is latent-reachable (regression-based beta computation can produce NaN
on insufficient data / zero variance; data-provider NaN propagation). These are
PUBLIC functions on the valuation path feeding DCF intrinsic value → agent
signals. Fix: guard beta with ``is_finite_number`` → default 1.0 (same as
None/missing), so the rate caps work correctly. Behavior-preserving for valid
inputs.
"""

from __future__ import annotations

import math

import pytest

from src.agents.aswath_damodaran import estimate_cost_of_equity
from src.agents.valuation import calculate_wacc


class TestEstimateCostOfEquityNaNHardening:
    def test_nan_beta_returns_finite_not_nan(self) -> None:
        """NaN beta must not produce NaN cost_of_equity — the 30% cap is
        documented but ``min(NaN, 0.30)`` returns NaN, silently violating it.
        Guard beta → default 1.0 (same as None)."""
        result = estimate_cost_of_equity(float("nan"), ticker="000001")
        assert isinstance(result, float)
        assert math.isfinite(result), "NaN beta must not propagate to NaN cost_of_equity; the 30% cap " "is silently violated because min(NaN, 0.30) returns NaN"
        # Should match the None-beta path (default beta 1.0)
        expected = estimate_cost_of_equity(None, ticker="000001")
        assert result == pytest.approx(expected)

    def test_normal_beta_unchanged(self) -> None:
        """Normal beta inputs must produce the same result (behavior-preserving)."""
        assert estimate_cost_of_equity(1.2, ticker="000001") == pytest.approx(0.125)
        assert estimate_cost_of_equity(0.5) < estimate_cost_of_equity(2.0)  # higher beta → higher cost


class TestCalculateWaccNaNHardening:
    def test_nan_beta_proxy_returns_finite_not_nan(self) -> None:
        """NaN beta_proxy must not produce NaN WACC — the [6%, 20%] floor/cap
        is documented but ``min(max(NaN, 0.06), 0.20)`` returns NaN, silently
        violating it. Guard beta_proxy → default 1.0."""
        result = calculate_wacc(
            market_cap=1000,
            total_debt=100,
            cash=50,
            interest_coverage=5,
            debt_to_equity=0.5,
            beta_proxy=float("nan"),
        )
        assert isinstance(result, float)
        assert math.isfinite(result), "NaN beta_proxy must not propagate to NaN WACC; the [6%, 20%] " "floor/cap is silently violated because min/max do not clamp NaN"
        # Should be within documented [0.06, 0.20] range
        assert 0.06 <= result <= 0.20

    def test_normal_wacc_unchanged(self) -> None:
        """Normal inputs must produce the same result (behavior-preserving)."""
        result = calculate_wacc(
            market_cap=1000,
            total_debt=100,
            cash=50,
            interest_coverage=5,
            debt_to_equity=0.5,
            beta_proxy=1.2,
        )
        assert result == pytest.approx(0.11375, abs=1e-4)
        assert 0.06 <= result <= 0.20
