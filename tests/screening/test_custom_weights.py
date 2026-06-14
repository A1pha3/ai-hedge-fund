"""Tests for src/screening/custom_weights.py — P2-5 自定义策略权重."""

from __future__ import annotations

import math

import pytest

from src.screening.custom_weights import (
    _compute_weighted_score_b,
    _extract_strategy_score,
    DEFAULT_WEIGHTS,
    MAX_STRATEGY_SCORE,
    reweight_recommendations,
    STRATEGY_KEYS,
    StrategyWeights,
    WEIGHT_SUM_TOLERANCE,
)

# ---------------------------------------------------------------------------
# StrategyWeights
# ---------------------------------------------------------------------------


class TestStrategyWeights:
    def test_default_weights_sum_to_one(self) -> None:
        w = StrategyWeights()
        assert abs(w.trend + w.mean_reversion + w.fundamental + w.event_sentiment - 1.0) < 1e-9

    def test_default_all_0_25(self) -> None:
        w = StrategyWeights()
        for key in STRATEGY_KEYS:
            assert getattr(w, key) == 0.25

    def test_custom_valid_weights(self) -> None:
        w = StrategyWeights(trend=0.5, mean_reversion=0.3, fundamental=0.1, event_sentiment=0.1)
        assert w.trend == 0.5
        assert w.mean_reversion == 0.3

    def test_reject_negative_weight(self) -> None:
        with pytest.raises(ValueError, match="不能为负数"):
            StrategyWeights(trend=-0.1, mean_reversion=0.4, fundamental=0.35, event_sentiment=0.35)

    def test_reject_weight_over_one(self) -> None:
        with pytest.raises(ValueError, match="不能超过 1.0"):
            StrategyWeights(trend=1.5, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)

    def test_reject_sum_not_one(self) -> None:
        with pytest.raises(ValueError, match="权重之和必须为 1.0"):
            StrategyWeights(trend=0.5, mean_reversion=0.3, fundamental=0.1, event_sentiment=0.0)

    def test_reject_nan(self) -> None:
        with pytest.raises(ValueError, match="必须为有限数"):
            StrategyWeights(trend=float("nan"), mean_reversion=0.25, fundamental=0.25, event_sentiment=0.25)

    def test_reject_inf(self) -> None:
        with pytest.raises(ValueError, match="必须为有限数"):
            StrategyWeights(trend=float("inf"), mean_reversion=0.25, fundamental=0.25, event_sentiment=0.25)

    def test_to_dict(self) -> None:
        w = StrategyWeights(trend=0.4, mean_reversion=0.3, fundamental=0.2, event_sentiment=0.1)
        d = w.to_dict()
        assert d == {"trend": 0.4, "mean_reversion": 0.3, "fundamental": 0.2, "event_sentiment": 0.1}

    def test_from_dict_full(self) -> None:
        d = {"trend": 0.6, "mean_reversion": 0.2, "fundamental": 0.1, "event_sentiment": 0.1}
        w = StrategyWeights.from_dict(d)
        assert w.trend == 0.6

    def test_from_dict_partial_uses_defaults(self) -> None:
        d = {"trend": 1.0, "mean_reversion": 0.0, "fundamental": 0.0, "event_sentiment": 0.0}
        w = StrategyWeights.from_dict(d)
        assert w.trend == 1.0

    def test_normalize(self) -> None:
        # StrategyWeights.__post_init__ enforces sum=1, so this is a round-trip
        w = StrategyWeights(trend=0.4, mean_reversion=0.3, fundamental=0.2, event_sentiment=0.1)
        n = w.normalize()
        assert abs(n.trend + n.mean_reversion + n.fundamental + n.event_sentiment - 1.0) < 1e-9

    def test_zero_trend_weight(self) -> None:
        """trend=0 is valid (non-negative, sum still 1)."""
        w = StrategyWeights(trend=0.0, mean_reversion=0.5, fundamental=0.25, event_sentiment=0.25)
        assert w.trend == 0.0

    def test_all_weight_on_one_strategy(self) -> None:
        w = StrategyWeights(trend=1.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)
        assert w.trend == 1.0


# ---------------------------------------------------------------------------
# _extract_strategy_score
# ---------------------------------------------------------------------------


class TestExtractStrategyScore:
    def test_bullish_signal(self) -> None:
        rec = {"strategy_signals": {"trend": {"direction": 1, "confidence": 80.0, "completeness": 1.0}}}
        assert _extract_strategy_score(rec, "trend") == 80.0

    def test_bearish_signal(self) -> None:
        rec = {"strategy_signals": {"trend": {"direction": -1, "confidence": 60.0, "completeness": 1.0}}}
        assert _extract_strategy_score(rec, "trend") == -60.0

    def test_zero_direction(self) -> None:
        rec = {"strategy_signals": {"trend": {"direction": 0, "confidence": 80.0, "completeness": 1.0}}}
        assert _extract_strategy_score(rec, "trend") == 0.0

    def test_completeness_zero_returns_zero(self) -> None:
        rec = {"strategy_signals": {"trend": {"direction": 1, "confidence": 80.0, "completeness": 0.0}}}
        assert _extract_strategy_score(rec, "trend") == 0.0

    def test_missing_strategy_returns_zero(self) -> None:
        rec = {"strategy_signals": {"trend": {"direction": 1, "confidence": 80.0, "completeness": 1.0}}}
        assert _extract_strategy_score(rec, "fundamental") == 0.0

    def test_missing_strategy_signals_returns_zero(self) -> None:
        assert _extract_strategy_score({"ticker": "000001"}, "trend") == 0.0

    def test_non_mapping_rec_returns_zero(self) -> None:
        assert _extract_strategy_score("not a dict", "trend") == 0.0

    def test_non_mapping_signals_returns_zero(self) -> None:
        rec = {"strategy_signals": "bad"}
        assert _extract_strategy_score(rec, "trend") == 0.0

    def test_non_mapping_strategy_returns_zero(self) -> None:
        rec = {"strategy_signals": {"trend": "bad"}}
        assert _extract_strategy_score(rec, "trend") == 0.0

    def test_non_numeric_direction_returns_zero(self) -> None:
        rec = {"strategy_signals": {"trend": {"direction": "up", "confidence": 80.0, "completeness": 1.0}}}
        assert _extract_strategy_score(rec, "trend") == 0.0


# ---------------------------------------------------------------------------
# _compute_weighted_score_b
# ---------------------------------------------------------------------------


class TestComputeWeightedScoreB:
    def test_all_bullish_equal_weights(self) -> None:
        rec = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                "mean_reversion": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                "fundamental": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                "event_sentiment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
            },
        }
        w = StrategyWeights()
        score = _compute_weighted_score_b(rec, w)
        assert score == pytest.approx(1.0)

    def test_all_bearish_equal_weights(self) -> None:
        rec = {
            "strategy_signals": {
                "trend": {"direction": -1, "confidence": 100.0, "completeness": 1.0},
                "mean_reversion": {"direction": -1, "confidence": 100.0, "completeness": 1.0},
                "fundamental": {"direction": -1, "confidence": 100.0, "completeness": 1.0},
                "event_sentiment": {"direction": -1, "confidence": 100.0, "completeness": 1.0},
            },
        }
        w = StrategyWeights()
        score = _compute_weighted_score_b(rec, w)
        assert score == pytest.approx(-1.0)

    def test_single_strategy_dominant(self) -> None:
        """Only trend with weight=1.0 → score = direction*confidence/100."""
        rec = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
            },
        }
        w = StrategyWeights(trend=1.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)
        score = _compute_weighted_score_b(rec, w)
        assert score == pytest.approx(0.5)

    def test_no_signals_falls_back_to_score_b(self) -> None:
        rec = {"ticker": "000001", "score_b": 0.6}
        w = StrategyWeights()
        score = _compute_weighted_score_b(rec, w)
        assert score == pytest.approx(0.6)

    def test_mixed_signals(self) -> None:
        """Trend bullish 80, fundamental bearish 60 → net depends on weights."""
        rec = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                "fundamental": {"direction": -1, "confidence": 60.0, "completeness": 1.0},
            },
        }
        w = StrategyWeights(trend=0.5, mean_reversion=0.0, fundamental=0.5, event_sentiment=0.0)
        score = _compute_weighted_score_b(rec, w)
        # 0.5*80 + 0.5*(-60) = 10, /100 = 0.1
        assert score == pytest.approx(0.1)

    def test_non_mapping_rec_returns_zero(self) -> None:
        w = StrategyWeights()
        assert _compute_weighted_score_b("bad", w) == 0.0

    def test_score_clamped_at_upper(self) -> None:
        rec = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 200.0, "completeness": 1.0},
                "mean_reversion": {"direction": 1, "confidence": 200.0, "completeness": 1.0},
                "fundamental": {"direction": 1, "confidence": 200.0, "completeness": 1.0},
                "event_sentiment": {"direction": 1, "confidence": 200.0, "completeness": 1.0},
            },
        }
        w = StrategyWeights()
        score = _compute_weighted_score_b(rec, w)
        assert score == 1.0


# ---------------------------------------------------------------------------
# reweight_recommendations
# ---------------------------------------------------------------------------


class TestReweightRecommendations:
    def test_empty_list(self) -> None:
        result = reweight_recommendations([], StrategyWeights())
        assert result == []

    def test_non_sequence_returns_empty(self) -> None:
        result = reweight_recommendations("bad", StrategyWeights())  # type: ignore[arg-type]
        assert result == []

    def test_single_rec(self) -> None:
        recs = [
            {
                "ticker": "000001",
                "score_b": 0.3,
                "strategy_signals": {
                    "trend": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                },
            },
        ]
        w = StrategyWeights(trend=1.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)
        result = reweight_recommendations(recs, w)
        assert len(result) == 1
        assert result[0]["original_score_b"] == 0.3
        assert result[0]["score_b"] == pytest.approx(0.8)
        assert result[0]["custom_weights"]["trend"] == 1.0

    def test_sorted_descending(self) -> None:
        recs = [
            {"ticker": "A", "score_b": 0.5, "strategy_signals": {"trend": {"direction": 1, "confidence": 30.0, "completeness": 1.0}}},
            {"ticker": "B", "score_b": 0.2, "strategy_signals": {"trend": {"direction": 1, "confidence": 90.0, "completeness": 1.0}}},
        ]
        w = StrategyWeights(trend=1.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)
        result = reweight_recommendations(recs, w)
        assert result[0]["ticker"] == "B"  # higher confidence
        assert result[1]["ticker"] == "A"

    def test_no_sort(self) -> None:
        recs = [
            {"ticker": "A", "score_b": 0.5, "strategy_signals": {"trend": {"direction": 1, "confidence": 30.0, "completeness": 1.0}}},
            {"ticker": "B", "score_b": 0.2, "strategy_signals": {"trend": {"direction": 1, "confidence": 90.0, "completeness": 1.0}}},
        ]
        w = StrategyWeights(trend=1.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)
        result = reweight_recommendations(recs, w, sort=False)
        # Original order preserved
        assert result[0]["ticker"] == "A"
        assert result[1]["ticker"] == "B"

    def test_does_not_mutate_input(self) -> None:
        rec = {"ticker": "A", "score_b": 0.5, "strategy_signals": {"trend": {"direction": 1, "confidence": 80.0, "completeness": 1.0}}}
        recs = [rec]
        w = StrategyWeights()
        result = reweight_recommendations(recs, w)
        # Original should be untouched
        assert "original_score_b" not in rec
        assert rec["score_b"] == 0.5
        assert result[0]["original_score_b"] == 0.5

    def test_same_score_sorts_by_ticker(self) -> None:
        recs = [
            {"ticker": "B", "score_b": 0.0, "strategy_signals": {}},
            {"ticker": "A", "score_b": 0.0, "strategy_signals": {}},
        ]
        w = StrategyWeights()
        result = reweight_recommendations(recs, w)
        assert result[0]["ticker"] == "A"
        assert result[1]["ticker"] == "B"
