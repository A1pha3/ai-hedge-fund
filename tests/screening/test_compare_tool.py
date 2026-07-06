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


# ---------------------------------------------------------------------------
# autodev-13 / loop 106: --compare cross-surface verdict consistency
# (C-CONDITIONAL-ORDER-VERDICT-GATE disease class sweep — the pairwise "推荐首选"
# by raw factor 胜场 can be an AVOID-rated pick, contradicting --top-picks).
# ---------------------------------------------------------------------------


class TestCompareVerdictDisclosure:
    """--compare's "推荐首选" picks the ticker with the most raw-factor wins,
    which can be an AVOID-rated pick (e.g. 688019 on report 20260703 wins 3/5
    factors but is AVOID — 成熟样本不足 20). The disclosure surfaces each
    compared ticker's front-door verdict and warns when the winner is not BUY."""

    def test_warns_when_winner_is_avoid(self) -> None:
        """When the pairwise winner is AVOID-rated, the disclosure must ⚠ the
        operator that the '推荐首选' is NOT a BUY (买入决策以 --top-picks 前门为准)."""
        from src.screening.compare_tool import _format_compare_verdict_disclosure

        # 300054 passes BUY gate; 688019 fails (no calibration → AVOID).
        # Winner = 688019 (AVOID) — the dangerous case.
        recs = [
            {
                "ticker": "300054",
                "composite_score": 0.70,
                "win_rates": {"t5": 0.62, "t10": 0.62},
                "expected_returns": {"t5": 3.0, "t10": 4.0},
                "bucket_sample_count": 100,
                "bucket_t30_mature_count": 90,
            },
            {"ticker": "688019", "composite_score": 0.61},  # AVOID
        ]
        out = _format_compare_verdict_disclosure(recs, winner="688019", market_regime="normal")
        assert "AVOID" in out
        assert "688019" in out
        assert "⚠" in out, (
            "When --compare's 推荐首选 (winner) is AVOID-rated, the disclosure "
            "must warn the operator that the pairwise winner is not a BUY pick."
        )

    def test_no_alarm_when_winner_is_buy(self) -> None:
        """Negative guard: when the winner clears the BUY gate, no ⚠ alarm
        (verdicts still shown for context)."""
        from src.screening.compare_tool import _format_compare_verdict_disclosure

        recs = [
            {
                "ticker": "300054",
                "composite_score": 0.70,
                "win_rates": {"t5": 0.62, "t10": 0.62},
                "expected_returns": {"t5": 3.0, "t10": 4.0},
                "bucket_sample_count": 100,
                "bucket_t30_mature_count": 90,
            },
            {"ticker": "688019", "composite_score": 0.61},  # AVOID
        ]
        out = _format_compare_verdict_disclosure(recs, winner="300054", market_regime="normal")
        assert "BUY" in out
        assert "⚠" not in out

    def test_empty_recs_returns_empty(self) -> None:
        from src.screening.compare_tool import _format_compare_verdict_disclosure

        assert _format_compare_verdict_disclosure([], winner=None, market_regime="normal") == ""

