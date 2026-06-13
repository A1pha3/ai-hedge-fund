"""Tests for src/screening/industry_rotation.py — P1-2 行业轮动信号."""

from __future__ import annotations

import pytest

from src.screening.industry_rotation import (
    IndustrySignal,
    _aggregate_momentum,
    _extract_momentum_from_signal,
    _resolve_industry_name,
    bottom_weak_industries,
    calculate_industry_rotation,
    format_rotation_block,
    top_strong_industries,
)


# ---------------------------------------------------------------------------
# _extract_momentum_from_signal
# ---------------------------------------------------------------------------


class TestExtractMomentumFromSignal:
    def test_none_returns_zero(self) -> None:
        assert _extract_momentum_from_signal(None) == 0.0

    def test_dict_bullish(self) -> None:
        sig = {"direction": 1, "confidence": 80.0}
        assert _extract_momentum_from_signal(sig) == pytest.approx(80.0)

    def test_dict_bearish(self) -> None:
        sig = {"direction": -1, "confidence": 60.0}
        assert _extract_momentum_from_signal(sig) == pytest.approx(-60.0)

    def test_dict_zero_direction(self) -> None:
        sig = {"direction": 0, "confidence": 80.0}
        assert _extract_momentum_from_signal(sig) == 0.0

    def test_dict_missing_direction(self) -> None:
        sig = {"confidence": 80.0}
        assert _extract_momentum_from_signal(sig) == 0.0

    def test_dict_missing_confidence(self) -> None:
        sig = {"direction": 1}
        assert _extract_momentum_from_signal(sig) == 0.0

    def test_dict_non_numeric_direction(self) -> None:
        sig = {"direction": "up", "confidence": 80.0}
        assert _extract_momentum_from_signal(sig) == 0.0

    def test_dict_nan_confidence(self) -> None:
        sig = {"direction": 1, "confidence": float("nan")}
        assert _extract_momentum_from_signal(sig) == 0.0

    def test_dict_inf_confidence(self) -> None:
        sig = {"direction": 1, "confidence": float("inf")}
        assert _extract_momentum_from_signal(sig) == 0.0

    def test_dict_negative_confidence_clamped(self) -> None:
        sig = {"direction": 1, "confidence": -50.0}
        assert _extract_momentum_from_signal(sig) == 0.0  # clamped to 0

    def test_dict_over_100_confidence_clamped(self) -> None:
        sig = {"direction": 1, "confidence": 200.0}
        assert _extract_momentum_from_signal(sig) == pytest.approx(100.0)

    def test_object_with_attributes(self) -> None:
        class Sig:
            direction = 1
            confidence = 75.0
        assert _extract_momentum_from_signal(Sig()) == pytest.approx(75.0)

    def test_direction_truncated_to_range(self) -> None:
        """direction > 1 is truncated to 1."""
        sig = {"direction": 5, "confidence": 50.0}
        assert _extract_momentum_from_signal(sig) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# _aggregate_momentum
# ---------------------------------------------------------------------------


class TestAggregateMomentum:
    def test_no_strategy_signals(self) -> None:
        assert _aggregate_momentum({"ticker": "A"}) == 0.0

    def test_single_bullish(self) -> None:
        rec = {"strategy_signals": {"trend": {"direction": 1, "confidence": 80.0}}}
        result = _aggregate_momentum(rec)
        assert result == pytest.approx(80.0)

    def test_mixed_signals(self) -> None:
        rec = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 100.0},
                "fundamental": {"direction": -1, "confidence": 50.0},
            },
        }
        result = _aggregate_momentum(rec)
        # (100 + (-50)) / 2 = 25.0
        assert result == pytest.approx(25.0)

    def test_empty_signals(self) -> None:
        rec = {"strategy_signals": {}}
        assert _aggregate_momentum(rec) == 0.0


# ---------------------------------------------------------------------------
# _resolve_industry_name
# ---------------------------------------------------------------------------


class TestResolveIndustryName:
    def test_normal_name(self) -> None:
        assert _resolve_industry_name({"industry_sw": "电子"}) == "电子"

    def test_none_returns_empty(self) -> None:
        assert _resolve_industry_name({}) == ""

    def test_whitespace_stripped(self) -> None:
        assert _resolve_industry_name({"industry_sw": "  电子  "}) == "电子"


# ---------------------------------------------------------------------------
# calculate_industry_rotation
# ---------------------------------------------------------------------------


class TestCalculateIndustryRotation:
    def test_empty_recommendations(self) -> None:
        assert calculate_industry_rotation([], "20260101") == []

    def test_single_industry_filtered_by_min_candidates(self) -> None:
        """Single rec in an industry → candidate_count=1 < min_candidates=2 → filtered out."""
        recs = [{"industry_sw": "电子", "score_b": 0.5, "strategy_signals": {"trend": {"direction": 1, "confidence": 80}}}]
        result = calculate_industry_rotation(recs, "20260101", min_candidates=2)
        assert result == []

    def test_two_candidates_same_industry(self) -> None:
        recs = [
            {"ticker": "A", "industry_sw": "电子", "score_b": 0.5, "strategy_signals": {"trend": {"direction": 1, "confidence": 80}}},
            {"ticker": "B", "industry_sw": "电子", "score_b": 0.3, "strategy_signals": {"trend": {"direction": 1, "confidence": 60}}},
        ]
        result = calculate_industry_rotation(recs, "20260101", min_candidates=2)
        assert len(result) == 1
        assert result[0].industry_name == "电子"
        assert result[0].candidate_count == 2
        assert result[0].rank == 1

    def test_unknown_industry_excluded(self) -> None:
        recs = [
            {"industry_sw": "", "score_b": 0.5, "strategy_signals": {"trend": {"direction": 1, "confidence": 80}}},
            {"industry_sw": "", "score_b": 0.3, "strategy_signals": {"trend": {"direction": 1, "confidence": 60}}},
        ]
        result = calculate_industry_rotation(recs, "20260101", min_candidates=2)
        assert result == []

    def test_multiple_industries_ranked(self) -> None:
        recs = [
            {"ticker": "A", "industry_sw": "电子", "score_b": 0.8, "strategy_signals": {"trend": {"direction": 1, "confidence": 100}}},
            {"ticker": "B", "industry_sw": "电子", "score_b": 0.7, "strategy_signals": {"trend": {"direction": 1, "confidence": 90}}},
            {"ticker": "C", "industry_sw": "银行", "score_b": 0.2, "strategy_signals": {"trend": {"direction": -1, "confidence": 80}}},
            {"ticker": "D", "industry_sw": "银行", "score_b": 0.1, "strategy_signals": {"trend": {"direction": -1, "confidence": 70}}},
        ]
        result = calculate_industry_rotation(recs, "20260101", min_candidates=2)
        assert len(result) == 2
        assert result[0].industry_name == "电子"  # higher momentum
        assert result[1].industry_name == "银行"

    def test_non_dict_rec_skipped(self) -> None:
        recs = ["not a dict", {"ticker": "A", "industry_sw": "电子", "score_b": 0.5, "strategy_signals": {"trend": {"direction": 1, "confidence": 80}}}]
        result = calculate_industry_rotation(recs, "20260101", min_candidates=1)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# top_strong_industries / bottom_weak_industries
# ---------------------------------------------------------------------------


class TestTopBottomIndustries:
    def _make_signals(self, n: int = 5) -> list[IndustrySignal]:
        return [
            IndustrySignal(industry_name=f"行业{i}", momentum_score=float(n - i), rank=i)
            for i in range(1, n + 1)
        ]

    def test_top_strong(self) -> None:
        signals = self._make_signals(5)
        top = top_strong_industries(signals, 3)
        assert len(top) == 3
        assert top[0].rank == 1

    def test_top_strong_fewer_than_n(self) -> None:
        signals = self._make_signals(2)
        top = top_strong_industries(signals, 5)
        assert len(top) == 2

    def test_bottom_weak(self) -> None:
        signals = self._make_signals(5)
        bottom = bottom_weak_industries(signals, 2)
        assert len(bottom) == 2
        # Reversed, so weakest first
        assert bottom[0].rank == 5
        assert bottom[1].rank == 4

    def test_bottom_weak_empty(self) -> None:
        assert bottom_weak_industries([], 3) == []


# ---------------------------------------------------------------------------
# format_rotation_block
# ---------------------------------------------------------------------------


class TestFormatRotationBlock:
    def test_empty_signals(self) -> None:
        result = format_rotation_block([])
        assert "无行业轮动信号" in result

    def test_with_signals(self) -> None:
        signals = [
            IndustrySignal(industry_name="电子", momentum_score=50.0, avg_score_b=0.6, candidate_count=3, rank=1),
            IndustrySignal(industry_name="银行", momentum_score=-20.0, avg_score_b=-0.1, candidate_count=2, rank=2),
        ]
        result = format_rotation_block(signals)
        assert "强势行业" in result
        assert "电子" in result
        assert "弱势行业" in result


# ---------------------------------------------------------------------------
# IndustrySignal.to_dict
# ---------------------------------------------------------------------------


class TestIndustrySignalToDict:
    def test_to_dict(self) -> None:
        sig = IndustrySignal(
            industry_name="电子",
            momentum_score=45.6,
            avg_score_b=0.65,
            candidate_count=5,
            rank=1,
        )
        d = sig.to_dict()
        assert d["industry_name"] == "电子"
        assert d["momentum_score"] == pytest.approx(45.6)
        assert d["rank"] == 1
        assert d["candidate_count"] == 5
