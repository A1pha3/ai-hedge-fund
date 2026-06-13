"""Tests for src/screening/trend_resonance.py — P14-1 Multi-Timeframe Trend Resonance."""

from __future__ import annotations

import pytest

from src.screening.trend_resonance import (
    TrendResonanceEntry,
    TrendResonanceReport,
    _classify_direction,
    _classify_resonance,
    _extract_score_history,
    _simple_slope,
    render_trend_resonance,
)


# ---------------------------------------------------------------------------
# _simple_slope
# ---------------------------------------------------------------------------


class TestSimpleSlope:
    def test_empty(self) -> None:
        assert _simple_slope([]) == 0.0

    def test_single(self) -> None:
        assert _simple_slope([1.0]) == 0.0

    def test_ascending(self) -> None:
        assert _simple_slope([0.0, 0.1, 0.2, 0.3]) == pytest.approx(0.1)

    def test_descending(self) -> None:
        assert _simple_slope([0.3, 0.2, 0.1, 0.0]) == pytest.approx(-0.1)

    def test_flat(self) -> None:
        assert _simple_slope([0.5, 0.5, 0.5]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _classify_direction
# ---------------------------------------------------------------------------


class TestClassifyDirection:
    def test_up(self) -> None:
        assert _classify_direction(0.01) == "up"

    def test_down(self) -> None:
        assert _classify_direction(-0.01) == "down"

    def test_flat_zero(self) -> None:
        assert _classify_direction(0.0) == "flat"

    def test_flat_near_zero(self) -> None:
        assert _classify_direction(0.002) == "flat"

    def test_flat_negative_near_zero(self) -> None:
        assert _classify_direction(-0.002) == "flat"

    def test_exactly_threshold_up(self) -> None:
        """Exactly 0.003 is NOT up (must be > threshold)."""
        assert _classify_direction(0.003) == "flat"

    def test_above_threshold(self) -> None:
        assert _classify_direction(0.004) == "up"


# ---------------------------------------------------------------------------
# _classify_resonance
# ---------------------------------------------------------------------------


class TestClassifyResonance:
    def test_all_up(self) -> None:
        label, factor = _classify_resonance(("up", "up", "up"))
        assert label == "resonance_up"
        assert factor == 0.05

    def test_all_down(self) -> None:
        label, factor = _classify_resonance(("down", "down", "down"))
        assert label == "resonance_down"
        assert factor == -0.05

    def test_two_up_one_flat(self) -> None:
        label, factor = _classify_resonance(("up", "up", "flat"))
        assert label == "partial_up"
        assert factor == 0.02

    def test_two_down_one_flat(self) -> None:
        label, factor = _classify_resonance(("down", "down", "flat"))
        assert label == "partial_down"
        assert factor == -0.02

    def test_mixed_up_and_down(self) -> None:
        label, factor = _classify_resonance(("up", "down", "flat"))
        assert label == "mixed"
        assert factor == -0.05

    def test_all_flat(self) -> None:
        label, factor = _classify_resonance(("flat", "flat", "flat"))
        assert label == "neutral"
        assert factor == 0.0

    def test_one_up_two_flat(self) -> None:
        """Only 1 up and 0 downs → ups >= 2 is False, so neutral."""
        label, factor = _classify_resonance(("up", "flat", "flat"))
        assert label == "neutral"
        assert factor == 0.0

    def test_up_up_down_conflict(self) -> None:
        label, factor = _classify_resonance(("up", "up", "down"))
        assert label == "mixed"
        assert factor == -0.05


# ---------------------------------------------------------------------------
# _extract_score_history
# ---------------------------------------------------------------------------


class TestExtractScoreHistory:
    def test_empty_history(self) -> None:
        assert _extract_score_history("000001", []) == []

    def test_single_report_with_ticker(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}},
        ]
        scores = _extract_score_history("000001", history)
        assert scores == [0.5]

    def test_multiple_reports_chronological(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.7}]}},
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}},
        ]
        scores = _extract_score_history("000001", history)
        # reversed: oldest first → [0.5, 0.7]
        assert scores == [0.5, 0.7]

    def test_ticker_not_found(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "000002", "score_b": 0.5}]}},
        ]
        assert _extract_score_history("000001", history) == []

    def test_max_days_truncation(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "A", "score_b": float(i)}]}}
            for i in range(10)
        ]
        scores = _extract_score_history("A", history, max_days=5)
        assert len(scores) == 5
        # reversed: oldest first → scores are [9,8,7,...,0] reversed = [0,1,2,...,9]
        # then truncated to last 5 → [5,6,7,8,9]
        # Actually: reversed(history) iterates oldest first. history[0]=score_0 (newest)
        # reversed → score_9, score_8, ..., score_0 → [9,8,7,6,5,4,3,2,1,0]
        # then [-5:] → [4,3,2,1,0]
        assert scores == [4.0, 3.0, 2.0, 1.0, 0.0]

    def test_none_score_b_treated_as_zero(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "A", "score_b": None}]}},
        ]
        scores = _extract_score_history("A", history)
        assert scores == [0.0]


# ---------------------------------------------------------------------------
# TrendResonanceEntry / TrendResonanceReport
# ---------------------------------------------------------------------------


class TestTrendResonanceEntry:
    def test_defaults(self) -> None:
        entry = TrendResonanceEntry(ticker="000001")
        assert entry.direction_5d == "flat"
        assert entry.resonance_label == "neutral"
        assert entry.resonance_factor == 0.0


class TestTrendResonanceReport:
    def test_empty(self) -> None:
        report = TrendResonanceReport()
        assert report.items == []

    def test_to_dict(self) -> None:
        report = TrendResonanceReport(
            trade_date="2026-01-01",
            items=[
                TrendResonanceEntry(
                    ticker="000001",
                    name="平安",
                    slope_5d=0.01,
                    direction_5d="up",
                    resonance_label="resonance_up",
                    resonance_factor=0.05,
                ),
            ],
        )
        d = report.to_dict()
        assert d["trade_date"] == "2026-01-01"
        assert d["items"][0]["resonance_label"] == "resonance_up"


# ---------------------------------------------------------------------------
# render_trend_resonance
# ---------------------------------------------------------------------------


class TestRenderTrendResonance:
    def test_empty(self) -> None:
        result = render_trend_resonance(TrendResonanceReport())
        assert "无推荐数据" in result

    def test_with_items(self) -> None:
        report = TrendResonanceReport(
            trade_date="2026-01-01",
            items=[
                TrendResonanceEntry(
                    ticker="000001",
                    name="平安",
                    direction_5d="up",
                    direction_20d="up",
                    direction_60d="up",
                    resonance_label="resonance_up",
                    resonance_factor=0.05,
                ),
            ],
        )
        result = render_trend_resonance(report)
        assert "000001" in result
        assert "趋势共振" in result


# ---------------------------------------------------------------------------
# compute_trend_resonance (end-to-end, no report files → empty)
# ---------------------------------------------------------------------------


class TestComputeTrendResonance:
    def test_no_reports_returns_empty(self, tmp_path) -> None:
        from src.screening.trend_resonance import compute_trend_resonance

        report = compute_trend_resonance(reports_dir=tmp_path)
        assert report.items == []
