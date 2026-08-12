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
from src.screening.models import StrategySignal

# ---------------------------------------------------------------------------
# StrategyWeights
# ---------------------------------------------------------------------------


class TestStrategyWeights:
    def test_default_weights_from_authority(self) -> None:
        """默认权重从 DEFAULT_STRATEGY_WEIGHTS 派生 (2026-08-12 重构后不再 0.25 等分).

        旧测试断言 0.25 等分 + sum=1，但这会让 --auto 与重算路径拥有两套默认值。
        当前默认值直接从权威源派生，权威源变化时两条路径同步。
        """
        from src.screening.models import DEFAULT_STRATEGY_WEIGHTS

        w = StrategyWeights()
        for key in STRATEGY_KEYS:
            assert getattr(w, key) == DEFAULT_STRATEGY_WEIGHTS[key]
        total = w.trend + w.mean_reversion + w.fundamental + w.event_sentiment
        assert total > 0.0, "默认权重之和必须 > 0 (全 0 无法归一化)"
        # 不再断言 sum==1 — 权威源在策略降权时 sum 可以 < 1, 归一化在消费时进行

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

    def test_reject_all_zero(self) -> None:
        """全 0 权重被拒 (无法归一化, 会污染排序).

        校验允许任意正的相对权重和，但全 0 仍然非法。
        """
        with pytest.raises(ValueError, match="权重之和必须 > 0"):
            StrategyWeights(trend=0.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)

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
        """四策略全 bullish + 等权 → 满分 1.0 (权重归一化后)."""
        rec = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                "mean_reversion": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                "fundamental": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                "event_sentiment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
            },
        }
        # 显式等权 (不再依赖默认值, 默认值从权威源派生可能不等权)
        w = StrategyWeights(trend=0.25, mean_reversion=0.25, fundamental=0.25, event_sentiment=0.25)
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
        w = StrategyWeights(trend=0.25, mean_reversion=0.25, fundamental=0.25, event_sentiment=0.25)
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

    def test_no_signals_matches_production_zero_score(self) -> None:
        rec = {"ticker": "000001", "score_b": 0.6}
        w = StrategyWeights()
        score = _compute_weighted_score_b(rec, w)
        assert score == 0.0

    @pytest.mark.parametrize(
        ("raw_signals", "production_signals", "expected"),
        [
            (
                {
                    "trend": {
                        "direction": 1,
                        "confidence": 70.0,
                        "completeness": 1.0,
                    }
                },
                {
                    "trend": StrategySignal(
                        direction=1,
                        confidence=70.0,
                        completeness=1.0,
                    )
                },
                0.70,
            ),
            (
                {
                    "fundamental": {
                        "direction": 1,
                        "confidence": 80.0,
                        "completeness": 0.5,
                    },
                    "event_sentiment": {
                        "direction": -1,
                        "confidence": 100.0,
                        "completeness": 0.0,
                    },
                },
                {
                    "fundamental": StrategySignal(
                        direction=1,
                        confidence=80.0,
                        completeness=0.5,
                    ),
                    "event_sentiment": StrategySignal(
                        direction=-1,
                        confidence=100.0,
                        completeness=0.0,
                    ),
                },
                0.40,
            ),
            (
                {
                    "trend": {
                        "direction": 1,
                        "confidence": 70.0,
                        "completeness": 0.0,
                    }
                },
                {
                    "trend": StrategySignal(
                        direction=1,
                        confidence=70.0,
                        completeness=0.0,
                    )
                },
                0.0,
            ),
        ],
    )
    def test_default_reweight_math_matches_production_fusion(
        self,
        raw_signals: dict,
        production_signals: dict,
        expected: float,
    ) -> None:
        """Default web reweighting must reproduce production's active-signal math."""
        from src.screening.models import DEFAULT_STRATEGY_WEIGHTS
        from src.screening.signal_fusion import compute_score_b

        custom_score = _compute_weighted_score_b(
            {"strategy_signals": raw_signals},
            StrategyWeights(),
        )
        production_score = compute_score_b(
            production_signals,
            DEFAULT_STRATEGY_WEIGHTS,
            [],
        )

        assert custom_score == pytest.approx(expected)
        assert production_score == pytest.approx(expected)

    def test_raw_reweight_fields_are_bounded_by_production_model_ranges(self) -> None:
        """Malformed report fields must not outweigh a valid opposing signal."""
        rec = {
            "strategy_signals": {
                "trend": {
                    "direction": 1,
                    "confidence": 200.0,
                    "completeness": 2.0,
                },
                "fundamental": {
                    "direction": -1,
                    "confidence": 100.0,
                    "completeness": 1.0,
                },
            }
        }
        weights = StrategyWeights(
            trend=0.5,
            mean_reversion=0.0,
            fundamental=0.5,
            event_sentiment=0.0,
        )

        assert _compute_weighted_score_b(rec, weights) == 0.0

    def test_selected_unavailable_strategy_does_not_fallback_to_unselected_signal(self) -> None:
        """A valid user subset remains authoritative when its evidence is unavailable."""
        rec = {
            "strategy_signals": {
                "trend": {
                    "direction": 1,
                    "confidence": 100.0,
                    "completeness": 1.0,
                },
                "event_sentiment": {
                    "direction": 1,
                    "confidence": 100.0,
                    "completeness": 0.0,
                },
            }
        }
        event_only = StrategyWeights(
            trend=0.0,
            mean_reversion=0.0,
            fundamental=0.0,
            event_sentiment=1.0,
        )

        assert _compute_weighted_score_b(rec, event_only) == 0.0

    @pytest.mark.parametrize("raw_direction", [float("inf"), 2, 1.9, True])
    def test_malformed_raw_direction_fails_closed(
        self,
        raw_direction: object,
    ) -> None:
        """Only exact non-boolean {-1, 0, 1} direction values are admissible."""
        rec = {
            "strategy_signals": {
                "trend": {
                    "direction": raw_direction,
                    "confidence": 100.0,
                    "completeness": 1.0,
                }
            }
        }

        assert _compute_weighted_score_b(rec, StrategyWeights()) == 0.0

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
        """confidence 超过 100 时 clamp 到 1.0 (无论权重 sum)."""
        rec = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 200.0, "completeness": 1.0},
                "mean_reversion": {"direction": 1, "confidence": 200.0, "completeness": 1.0},
                "fundamental": {"direction": 1, "confidence": 200.0, "completeness": 1.0},
                "event_sentiment": {"direction": 1, "confidence": 200.0, "completeness": 1.0},
            },
        }
        # 显式等权 — 测试 clamp 行为, 不依赖默认权重
        w = StrategyWeights(trend=0.25, mean_reversion=0.25, fundamental=0.25, event_sentiment=0.25)
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
