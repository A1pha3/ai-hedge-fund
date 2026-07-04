"""TDD red test: risk_manager public limit/multiplier functions must not crash
or return risk-unsafe values on NaN/None inputs (latent hardening, R78/R85/R117
precedent — public functions on the position-sizing decision path).

``calculate_volatility_adjusted_limit`` and ``calculate_correlation_multiplier``
are PUBLIC functions (no underscore) passed as injected callables into the risk
management pipeline. Current callers (``_build_correlation_metrics`` /
``_build_risk_analysis_entry``) guard None/NaN before calling them, but the
functions themselves are unguarded:

1. ``calculate_volatility_adjusted_limit(NaN)`` → ``UnboundLocalError``: NaN
   is neither ``<= anchors[0][0]`` nor ``>= anchors[-1][0]`` (both False), and
   ``vol_low <= NaN < vol_high`` is False for every anchor pair, so the loop
   exits without assigning ``vol_multiplier`` → line 172 ``max(0.25, min(1.25,
   vol_multiplier))`` raises. A future caller (new agent / replay / web) that
   passes a NaN annualized_volatility crashes the whole risk pipeline.

2. ``calculate_correlation_multiplier(NaN)`` → returns ``1.10`` (the MOST
   PERMISSIVE multiplier — INCREASES the position limit). Unknown correlation
   should be RISK-CONSERVATIVE (neutral 1.0, not permissive 1.10): if you
   cannot measure how correlated your positions are, increasing exposure is
   the wrong direction.

3. ``calculate_correlation_multiplier(None)`` → ``TypeError`` (``None >= 0.80``).

Fix: guard NaN/None at the top of each function. NaN/None volatility → neutral
baseline (0.20); NaN/None correlation → conservative neutral (1.0). Behavior-
preserving for current callers (they never pass NaN/None).
"""

from __future__ import annotations

import math

import pytest

from src.agents.risk_manager import (
    calculate_correlation_multiplier,
    calculate_volatility_adjusted_limit,
)


class TestVolatilityAdjustedLimitNaNRobustness:
    def test_nan_volatility_does_not_crash(self) -> None:
        """NaN annualized_volatility must not raise UnboundLocalError — return
        the neutral baseline (0.20) so a malformed input degrades gracefully
        instead of crashing the risk pipeline."""
        result = calculate_volatility_adjusted_limit(float("nan"))
        assert isinstance(result, float)
        assert math.isfinite(result)
        # Neutral baseline = base_limit (0.20): neither max nor min allocation
        assert result == pytest.approx(0.20)

    def test_normal_volatility_unchanged(self) -> None:
        """Normal inputs must produce the same result as before the guard
        (behavior-preserving for current callers)."""
        low_vol = calculate_volatility_adjusted_limit(0.10)
        high_vol = calculate_volatility_adjusted_limit(0.60)
        # Low vol → higher allocation, high vol → lower allocation
        assert low_vol > high_vol
        # Both within documented [0.05, 0.25] range
        assert 0.05 <= low_vol <= 0.25
        assert 0.05 <= high_vol <= 0.25


class TestCorrelationMultiplierNaNNoneRobustness:
    def test_nan_correlation_returns_conservative_neutral(self) -> None:
        """NaN correlation must return 1.0 (neutral), NOT 1.10 (permissive).
        Unknown correlation is a risk signal — the safe default is to neither
        increase nor decrease the limit, not to increase it."""
        result = calculate_correlation_multiplier(float("nan"))
        assert result == pytest.approx(1.0)

    def test_none_correlation_does_not_crash(self) -> None:
        """None correlation must not raise TypeError — return conservative
        neutral (1.0)."""
        result = calculate_correlation_multiplier(None)  # type: ignore[arg-type]
        assert isinstance(result, float)
        assert result == pytest.approx(1.0)

    def test_normal_correlation_unchanged(self) -> None:
        """Normal inputs must produce the same result as before (behavior-
        preserving)."""
        assert calculate_correlation_multiplier(0.90) == pytest.approx(0.70)  # very high → reduce
        assert calculate_correlation_multiplier(0.50) == pytest.approx(1.00)  # moderate → neutral
        assert calculate_correlation_multiplier(0.10) == pytest.approx(1.10)  # very low → increase
