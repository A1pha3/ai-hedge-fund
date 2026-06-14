"""Tests for src/screening/compare_tool.py — ticker comparison helpers."""

from __future__ import annotations

import math

import pytest

from src.screening.compare_tool import _extract_raw_metric, _normalize_minmax

# ---------------------------------------------------------------------------
# _extract_raw_metric
# ---------------------------------------------------------------------------


class TestExtractRawMetric:
    def test_score_b(self) -> None:
        rec = {"score_b": 0.5}
        assert _extract_raw_metric(rec, "score_b") == pytest.approx(0.5)

    def test_score_b_missing(self) -> None:
        rec = {}
        assert _extract_raw_metric(rec, "score_b") == 0.0

    def test_score_b_none(self) -> None:
        rec = {"score_b": None}
        assert _extract_raw_metric(rec, "score_b") == 0.0

    def test_strategy_bullish(self) -> None:
        rec = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 80.0},
            },
        }
        result = _extract_raw_metric(rec, "trend_score")
        assert result == pytest.approx(80.0)

    def test_strategy_bearish(self) -> None:
        rec = {
            "strategy_signals": {
                "trend": {"direction": -1, "confidence": 60.0},
            },
        }
        result = _extract_raw_metric(rec, "trend_score")
        assert result == pytest.approx(-60.0)

    def test_strategy_neutral_direction(self) -> None:
        rec = {
            "strategy_signals": {
                "trend": {"direction": 0, "confidence": 50.0},
            },
        }
        result = _extract_raw_metric(rec, "trend")
        assert result == 0.0

    def test_missing_strategy(self) -> None:
        rec = {"strategy_signals": {"trend": {"direction": 1, "confidence": 80.0}}}
        assert _extract_raw_metric(rec, "fundamental_score") == 0.0

    def test_no_strategy_signals(self) -> None:
        rec = {}
        assert _extract_raw_metric(rec, "trend_score") == 0.0

    def test_non_dict_recommendation(self) -> None:
        assert _extract_raw_metric("bad", "score_b") == 0.0

    def test_unknown_metric(self) -> None:
        rec = {"score_b": 0.5}
        assert _extract_raw_metric(rec, "unknown_metric") == 0.0

    def test_non_dict_signal(self) -> None:
        rec = {"strategy_signals": {"trend": "bad"}}
        assert _extract_raw_metric(rec, "trend_score") == 0.0


# ---------------------------------------------------------------------------
# _normalize_minmax
# ---------------------------------------------------------------------------


class TestNormalizeMinmax:
    def test_empty(self) -> None:
        assert _normalize_minmax([]) == []

    def test_single_value(self) -> None:
        assert _normalize_minmax([5.0]) == [50.0]

    def test_all_equal(self) -> None:
        assert _normalize_minmax([3.0, 3.0, 3.0]) == [50.0, 50.0, 50.0]

    def test_two_values(self) -> None:
        result = _normalize_minmax([0.0, 100.0])
        assert result == [0.0, 100.0]

    def test_three_values(self) -> None:
        result = _normalize_minmax([0.0, 50.0, 100.0])
        assert result == [0.0, 50.0, 100.0]

    def test_negative_values(self) -> None:
        result = _normalize_minmax([-1.0, 0.0, 1.0])
        assert result == [0.0, 50.0, 100.0]

    def test_near_equal_treated_as_equal(self) -> None:
        """Values within abs_tol=1e-9 → treated as equal → all 50.0."""
        result = _normalize_minmax([1.0, 1.0 + 1e-10])
        assert result == [50.0, 50.0]

    def test_preserves_order(self) -> None:
        result = _normalize_minmax([10.0, 30.0, 20.0])
        assert result[0] < result[2] < result[1]
