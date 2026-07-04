"""Tests for trend_resonance.py — P14-1 multi-timeframe trend resonance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.screening.trend_resonance import (
    _classify_direction,
    _classify_resonance,
    _extract_score_history,
    _simple_slope,
    compute_trend_resonance,
    render_trend_resonance,
    TrendResonanceEntry,
    TrendResonanceReport,
)

# ---------------------------------------------------------------------------
# Unit: _simple_slope
# ---------------------------------------------------------------------------


class TestSimpleSlope:
    def test_empty(self) -> None:
        assert _simple_slope([]) == 0.0

    def test_single_value(self) -> None:
        assert _simple_slope([0.5]) == 0.0

    def test_two_values_ascending(self) -> None:
        slope = _simple_slope([0.3, 0.5])
        assert slope > 0

    def test_two_values_descending(self) -> None:
        slope = _simple_slope([0.5, 0.3])
        assert slope < 0

    def test_flat_values(self) -> None:
        assert _simple_slope([0.5, 0.5, 0.5]) == 0.0

    def test_perfect_ascending(self) -> None:
        values = [0.1, 0.2, 0.3, 0.4, 0.5]
        slope = _simple_slope(values)
        assert slope == pytest.approx(0.1, abs=1e-6)

    def test_perfect_descending(self) -> None:
        values = [0.5, 0.4, 0.3, 0.2, 0.1]
        slope = _simple_slope(values)
        assert slope == pytest.approx(-0.1, abs=1e-6)


# ---------------------------------------------------------------------------
# Unit: _classify_direction
# ---------------------------------------------------------------------------


class TestClassifyDirection:
    def test_up(self) -> None:
        assert _classify_direction(0.01) == "up"

    def test_down(self) -> None:
        assert _classify_direction(-0.01) == "down"

    def test_flat_zero(self) -> None:
        assert _classify_direction(0.0) == "flat"

    def test_flat_small_positive(self) -> None:
        assert _classify_direction(0.001) == "flat"

    def test_flat_small_negative(self) -> None:
        assert _classify_direction(-0.001) == "flat"

    def test_threshold_boundary(self) -> None:
        # _TREND_THRESHOLD = 0.003, strict > comparison
        assert _classify_direction(0.0031) == "up"
        assert _classify_direction(-0.0031) == "down"
        assert _classify_direction(0.003) == "flat"
        assert _classify_direction(-0.003) == "flat"


# ---------------------------------------------------------------------------
# Unit: _classify_resonance
# ---------------------------------------------------------------------------


class TestClassifyResonance:
    def test_all_up_resonance(self) -> None:
        label, factor = _classify_resonance(("up", "up", "up"))
        assert label == "resonance_up"
        assert factor == 0.05

    def test_all_down_resonance(self) -> None:
        label, factor = _classify_resonance(("down", "down", "down"))
        assert label == "resonance_down"
        assert factor == -0.05

    def test_two_up_one_flat_partial(self) -> None:
        label, factor = _classify_resonance(("up", "up", "flat"))
        assert label == "partial_up"
        assert factor == 0.02

    def test_two_down_one_flat_partial(self) -> None:
        label, factor = _classify_resonance(("down", "down", "flat"))
        assert label == "partial_down"
        assert factor == -0.02

    def test_mixed_conflict(self) -> None:
        label, factor = _classify_resonance(("up", "down", "flat"))
        assert label == "mixed"
        assert factor == -0.05

    def test_all_flat_neutral(self) -> None:
        label, factor = _classify_resonance(("flat", "flat", "flat"))
        assert label == "neutral"
        assert factor == 0.0

    def test_up_down_up_mixed(self) -> None:
        label, factor = _classify_resonance(("up", "down", "up"))
        assert label == "mixed"
        assert factor == -0.05

    def test_two_up_one_down_mixed(self) -> None:
        label, factor = _classify_resonance(("up", "up", "down"))
        assert label == "mixed"
        assert factor == -0.05


# ---------------------------------------------------------------------------
# Unit: _extract_score_history
# ---------------------------------------------------------------------------


class TestExtractScoreHistory:
    def test_empty_history(self) -> None:
        result = _extract_score_history("000001", [])
        assert result == []

    def test_single_report(self) -> None:
        history = [{"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}}]
        result = _extract_score_history("000001", history)
        assert result == [0.5]

    def test_multiple_reports_ordered(self) -> None:
        # history is newest-first; after reversed() it becomes oldest-first
        history = [
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.7}]}},
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}},
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.3}]}},
        ]
        result = _extract_score_history("000001", history)
        assert result == [0.3, 0.5, 0.7]

    def test_ticker_not_found(self) -> None:
        history = [{"payload": {"recommendations": [{"ticker": "000002", "score_b": 0.5}]}}]
        result = _extract_score_history("000001", history)
        assert result == []

    def test_max_days_limit(self) -> None:
        history = [{"payload": {"recommendations": [{"ticker": "000001", "score_b": float(i / 100)}]}} for i in range(100)]
        result = _extract_score_history("000001", history, max_days=30)
        assert len(result) == 30

    def test_none_score_b_handled(self) -> None:
        history = [{"payload": {"recommendations": [{"ticker": "000001", "score_b": None}]}}]
        result = _extract_score_history("000001", history)
        assert result == [0.0]


# ---------------------------------------------------------------------------
# Integration: compute_trend_resonance with mock data
# ---------------------------------------------------------------------------


class TestComputeTrendResonance:
    def test_empty_dir(self, tmp_path: Path) -> None:
        report = compute_trend_resonance(top_n=10, reports_dir=tmp_path)
        assert report.items == []
        assert report.trade_date == ""

    def test_single_report_insufficient_data(self, tmp_path: Path) -> None:
        """With only 1 report, we can't compute 5d slope (need >=5 data points)."""
        report_data = {"recommendations": [{"ticker": "000001", "name": "Test", "score_b": 0.5}]}
        (tmp_path / "auto_screening_20260601.json").write_text(json.dumps(report_data), encoding="utf-8")
        report = compute_trend_resonance(top_n=10, reports_dir=tmp_path)
        assert len(report.items) == 1
        assert report.items[0].ticker == "000001"
        assert report.items[0].resonance_label == "neutral"
        assert report.items[0].resonance_factor == 0.0

    def test_five_days_trending_up(self, tmp_path: Path) -> None:
        """5 days of rising scores should detect uptrend."""
        for i in range(5):
            report_data = {"recommendations": [{"ticker": "000001", "name": "Test", "score_b": 0.1 + i * 0.1}]}
            date_str = f"2026060{i + 1}"
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report_data), encoding="utf-8")

        report = compute_trend_resonance(top_n=10, reports_dir=tmp_path)
        assert len(report.items) == 1
        entry = report.items[0]
        assert entry.ticker == "000001"
        assert entry.direction_5d == "up"
        assert entry.resonance_factor > 0

    def test_five_days_trending_down(self, tmp_path: Path) -> None:
        """5 days of falling scores should detect downtrend."""
        for i in range(5):
            report_data = {"recommendations": [{"ticker": "000001", "name": "Test", "score_b": 0.5 - i * 0.1}]}
            date_str = f"2026060{i + 1}"
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report_data), encoding="utf-8")

        report = compute_trend_resonance(top_n=10, reports_dir=tmp_path)
        entry = report.items[0]
        assert entry.direction_5d == "down"
        assert entry.resonance_factor < 0

    def test_top_n_limits_results(self, tmp_path: Path) -> None:
        """Only top_n recommendations are analyzed."""
        for i in range(5):
            report_data = {"recommendations": [{"ticker": f"00000{j}", "name": f"Stock{j}", "score_b": 0.5} for j in range(1, 11)]}
            date_str = f"2026060{i + 1}"
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report_data), encoding="utf-8")

        report = compute_trend_resonance(top_n=3, reports_dir=tmp_path)
        assert len(report.items) <= 3


# ---------------------------------------------------------------------------
# Unit: render_trend_resonance
# ---------------------------------------------------------------------------


class TestRenderTrendResonance:
    def test_empty_report(self) -> None:
        output = render_trend_resonance(TrendResonanceReport())
        assert "无推荐数据" in output

    def test_with_items(self) -> None:
        report = TrendResonanceReport(
            trade_date="20260601",
            items=[
                TrendResonanceEntry(
                    ticker="000001",
                    name="Test",
                    direction_5d="up",
                    direction_20d="up",
                    direction_60d="up",
                    resonance_label="resonance_up",
                    resonance_factor=0.05,
                )
            ],
        )
        output = render_trend_resonance(report)
        assert "000001" in output
        assert "共振" in output

    def test_to_dict(self) -> None:
        report = TrendResonanceReport(
            trade_date="20260601",
            items=[
                TrendResonanceEntry(
                    ticker="000001",
                    name="Test",
                    slope_5d=0.01,
                    resonance_label="resonance_up",
                    resonance_factor=0.05,
                )
            ],
        )
        d = report.to_dict()
        assert d["trade_date"] == "20260601"
        assert len(d["items"]) == 1
        assert d["items"][0]["ticker"] == "000001"
        assert d["items"][0]["resonance_factor"] == 0.05
