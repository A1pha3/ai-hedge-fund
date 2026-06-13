"""Tests for src/screening/strategy_scorer_utils.py — shared scoring utilities."""

from __future__ import annotations

import pytest

from src.screening.models import SubFactor
from src.screening.strategy_scorer_utils import (
    aggregate_sub_factors,
    derive_completeness,
    _make_sub_factor,
    _signal_to_direction,
)


# ---------------------------------------------------------------------------
# _signal_to_direction
# ---------------------------------------------------------------------------


class TestSignalToDirection:
    def test_bullish(self) -> None:
        assert _signal_to_direction("bullish") == 1

    def test_bearish(self) -> None:
        assert _signal_to_direction("bearish") == -1

    def test_neutral(self) -> None:
        assert _signal_to_direction("neutral") == 0

    def test_unknown(self) -> None:
        assert _signal_to_direction("unknown") == 0

    def test_case_insensitive(self) -> None:
        assert _signal_to_direction("Bullish") == 1
        assert _signal_to_direction("BEARISH") == -1


# ---------------------------------------------------------------------------
# _make_sub_factor
# ---------------------------------------------------------------------------


class TestMakeSubFactor:
    def test_basic(self) -> None:
        sf = _make_sub_factor("test", 1, 80.0, 0.5)
        assert sf.name == "test"
        assert sf.direction == 1
        assert sf.confidence == 80.0
        assert sf.weight == 0.5

    def test_confidence_clipped(self) -> None:
        sf = _make_sub_factor("test", 1, 150.0, 0.5)
        assert sf.confidence == 100.0

    def test_confidence_negative_clipped(self) -> None:
        sf = _make_sub_factor("test", 1, -10.0, 0.5)
        assert sf.confidence == 0.0

    def test_completeness_clipped(self) -> None:
        sf = _make_sub_factor("test", 1, 50.0, 0.5, completeness=2.0)
        assert sf.completeness == 1.0

    def test_default_completeness(self) -> None:
        sf = _make_sub_factor("test", 1, 50.0, 0.5)
        assert sf.completeness == 1.0


# ---------------------------------------------------------------------------
# derive_completeness
# ---------------------------------------------------------------------------


class TestDeriveCompleteness:
    def test_empty(self) -> None:
        assert derive_completeness([]) == 0.0

    def test_all_complete(self) -> None:
        factors = [
            _make_sub_factor("a", 1, 50.0, 0.5, completeness=1.0),
            _make_sub_factor("b", 1, 50.0, 0.5, completeness=1.0),
        ]
        assert derive_completeness(factors) == pytest.approx(1.0)

    def test_all_incomplete(self) -> None:
        factors = [
            _make_sub_factor("a", 1, 50.0, 0.5, completeness=0.0),
            _make_sub_factor("b", 1, 50.0, 0.5, completeness=0.0),
        ]
        assert derive_completeness(factors) == 0.0

    def test_mixed(self) -> None:
        factors = [
            _make_sub_factor("a", 1, 50.0, 0.5, completeness=1.0),
            _make_sub_factor("b", 1, 50.0, 0.5, completeness=0.5),
        ]
        result = derive_completeness(factors)
        # weighted: 0.5/1.0 * 1.0 + 0.5/1.0 * 0.5 = 0.75
        assert result == pytest.approx(0.75)

    def test_zero_weights(self) -> None:
        factors = [
            _make_sub_factor("a", 1, 50.0, 0.0, completeness=1.0),
        ]
        assert derive_completeness(factors) == 0.0


# ---------------------------------------------------------------------------
# aggregate_sub_factors
# ---------------------------------------------------------------------------


class TestAggregateSubFactors:
    def test_all_bullish(self) -> None:
        factors = [
            _make_sub_factor("a", 1, 80.0, 0.5),
            _make_sub_factor("b", 1, 70.0, 0.5),
        ]
        signal = aggregate_sub_factors(factors)
        assert signal.direction == 1
        assert signal.confidence > 0
        assert signal.completeness > 0

    def test_all_bearish(self) -> None:
        factors = [
            _make_sub_factor("a", -1, 80.0, 0.5),
            _make_sub_factor("b", -1, 70.0, 0.5),
        ]
        signal = aggregate_sub_factors(factors)
        assert signal.direction == -1
        assert signal.confidence > 0

    def test_mixed_direction(self) -> None:
        factors = [
            _make_sub_factor("a", 1, 80.0, 0.5),
            _make_sub_factor("b", -1, 70.0, 0.5),
        ]
        signal = aggregate_sub_factors(factors)
        # score = 0.5*1*0.8 + 0.5*(-1)*0.7 = 0.05 > 0 → bullish
        assert signal.direction == 1

    def test_empty(self) -> None:
        signal = aggregate_sub_factors([])
        assert signal.direction == 0
        assert signal.confidence == 0.0
        assert signal.completeness == 0.0

    def test_all_incomplete(self) -> None:
        factors = [
            _make_sub_factor("a", 1, 80.0, 0.5, completeness=0.0),
        ]
        signal = aggregate_sub_factors(factors)
        assert signal.direction == 0
        assert signal.confidence == 0.0
        assert signal.completeness == 0.0

    def test_sub_factors_populated(self) -> None:
        factors = [
            _make_sub_factor("a", 1, 80.0, 0.5),
        ]
        signal = aggregate_sub_factors(factors)
        assert "a" in signal.sub_factors
