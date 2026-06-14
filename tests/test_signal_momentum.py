"""Tests for signal_momentum.py — P10-1."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.screening.signal_momentum import (
    _classify_momentum,
    _simple_slope,
    compute_signal_momentum,
    MomentumInfo,
    MomentumReport,
    render_signal_momentum,
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

    def test_noisy_but_trending_up(self) -> None:
        values = [0.2, 0.35, 0.3, 0.45, 0.5]
        slope = _simple_slope(values)
        assert slope > 0


# ---------------------------------------------------------------------------
# Unit: _classify_momentum
# ---------------------------------------------------------------------------


class TestClassifyMomentum:
    def test_strong_improving(self) -> None:
        label, bonus = _classify_momentum(0.03)
        assert label == "strong_improving"
        assert bonus == 0.10

    def test_improving(self) -> None:
        label, bonus = _classify_momentum(0.01)
        assert label == "improving"
        assert bonus == 0.05

    def test_stable_zero(self) -> None:
        label, bonus = _classify_momentum(0.0)
        assert label == "stable"
        assert bonus == 0.0

    def test_stable_near_zero(self) -> None:
        label, bonus = _classify_momentum(0.003)
        assert label == "stable"
        assert bonus == 0.0

    def test_declining(self) -> None:
        label, bonus = _classify_momentum(-0.01)
        assert label == "declining"
        assert bonus == -0.05

    def test_strong_declining(self) -> None:
        label, bonus = _classify_momentum(-0.03)
        assert label == "strong_declining"
        assert bonus == -0.10

    def test_boundary_strong(self) -> None:
        label, bonus = _classify_momentum(0.02)
        assert label == "strong_improving"

    def test_boundary_weak(self) -> None:
        label, bonus = _classify_momentum(0.005)
        assert label == "improving"


# ---------------------------------------------------------------------------
# Integration: compute_signal_momentum with mock data
# ---------------------------------------------------------------------------


def _make_report(date: str, recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Helper: build an auto_screening report dict."""
    return {"trade_date": date, "recommendations": recs}


def _write_reports(tmp_dir: Path, reports: dict[str, list[dict]]) -> None:
    """Write auto_screening_*.json files to tmp_dir."""
    for date_str, recs in reports.items():
        path = tmp_dir / f"auto_screening_{date_str}.json"
        path.write_text(
            json.dumps({"trade_date": date_str, "recommendations": recs}),
            encoding="utf-8",
        )


class TestComputeSignalMomentum:
    def test_no_reports(self, tmp_path: Path) -> None:
        report = compute_signal_momentum(reports_dir=tmp_path)
        assert report.items == []

    def test_single_report(self, tmp_path: Path) -> None:
        _write_reports(
            tmp_path,
            {
                "20260610": [
                    {"ticker": "000001", "name": "平安银行", "score_b": 0.5},
                    {"ticker": "000880", "name": "潍柴重机", "score_b": 0.4},
                ]
            },
        )
        report = compute_signal_momentum(reports_dir=tmp_path, top_n=10)
        # Single day → slope = 0.0 → stable
        assert len(report.items) == 2
        assert report.items[0].momentum_label == "stable"
        assert report.items[0].days_observed == 1

    def test_improving_trajectory(self, tmp_path: Path) -> None:
        _write_reports(
            tmp_path,
            {
                "20260608": [
                    {"ticker": "000001", "name": "平安银行", "score_b": 0.2},
                ],
                "20260609": [
                    {"ticker": "000001", "name": "平安银行", "score_b": 0.4},
                ],
                "20260610": [
                    {"ticker": "000001", "name": "平安银行", "score_b": 0.6},
                ],
            },
        )
        report = compute_signal_momentum(reports_dir=tmp_path, lookback_days=5)
        assert len(report.items) == 1
        item = report.items[0]
        assert item.slope > 0
        assert item.momentum_bonus > 0
        assert item.momentum_label in ("improving", "strong_improving")
        assert item.days_observed == 3

    def test_declining_trajectory(self, tmp_path: Path) -> None:
        _write_reports(
            tmp_path,
            {
                "20260608": [
                    {"ticker": "000001", "name": "平安银行", "score_b": 0.6},
                ],
                "20260609": [
                    {"ticker": "000001", "name": "平安银行", "score_b": 0.4},
                ],
                "20260610": [
                    {"ticker": "000001", "name": "平安银行", "score_b": 0.2},
                ],
            },
        )
        report = compute_signal_momentum(reports_dir=tmp_path, lookback_days=5)
        item = report.items[0]
        assert item.slope < 0
        assert item.momentum_bonus < 0
        assert item.momentum_label in ("declining", "strong_declining")

    def test_flat_trajectory(self, tmp_path: Path) -> None:
        _write_reports(
            tmp_path,
            {
                "20260608": [
                    {"ticker": "000001", "name": "平安银行", "score_b": 0.5},
                ],
                "20260609": [
                    {"ticker": "000001", "name": "平安银行", "score_b": 0.5},
                ],
                "20260610": [
                    {"ticker": "000001", "name": "平安银行", "score_b": 0.5},
                ],
            },
        )
        report = compute_signal_momentum(reports_dir=tmp_path, lookback_days=5)
        item = report.items[0]
        assert item.slope == pytest.approx(0.0)
        assert item.momentum_bonus == 0.0
        assert item.momentum_label == "stable"

    def test_top_n_limits_output(self, tmp_path: Path) -> None:
        recs = [{"ticker": f"{i:06d}", "name": f"Stock{i}", "score_b": 0.5} for i in range(10)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_signal_momentum(reports_dir=tmp_path, top_n=3)
        assert len(report.items) == 3

    def test_score_b_none_treated_as_zero(self, tmp_path: Path) -> None:
        _write_reports(
            tmp_path,
            {
                "20260610": [
                    {"ticker": "000001", "name": "Test", "score_b": None},
                ],
            },
        )
        report = compute_signal_momentum(reports_dir=tmp_path)
        assert len(report.items) == 1
        assert report.items[0].score_current == 0.0

    def test_trade_date_extracted(self, tmp_path: Path) -> None:
        _write_reports(
            tmp_path,
            {
                "20260610": [
                    {"ticker": "000001", "name": "Test", "score_b": 0.5},
                ],
            },
        )
        report = compute_signal_momentum(reports_dir=tmp_path)
        assert report.trade_date == "20260610"

    def test_mixed_tickers(self, tmp_path: Path) -> None:
        _write_reports(
            tmp_path,
            {
                "20260609": [
                    {"ticker": "000001", "name": "A", "score_b": 0.3},
                    {"ticker": "000002", "name": "B", "score_b": 0.6},
                ],
                "20260610": [
                    {"ticker": "000001", "name": "A", "score_b": 0.5},
                    {"ticker": "000002", "name": "B", "score_b": 0.4},
                ],
            },
        )
        report = compute_signal_momentum(reports_dir=tmp_path)
        items_by_ticker = {i.ticker: i for i in report.items}
        assert items_by_ticker["000001"].slope > 0  # improving
        assert items_by_ticker["000002"].slope < 0  # declining


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRenderSignalMomentum:
    def test_empty_report(self) -> None:
        text = render_signal_momentum(MomentumReport())
        assert "无推荐数据" in text

    def test_basic_report(self) -> None:
        report = MomentumReport(
            trade_date="20260610",
            lookback_days=5,
            items=[
                MomentumInfo(
                    ticker="000001",
                    name="平安银行",
                    score_current=0.5,
                    slope=0.03,
                    momentum_label="strong_improving",
                    momentum_bonus=0.10,
                    days_observed=3,
                ),
            ],
        )
        text = render_signal_momentum(report)
        assert "000001" in text
        assert "Signal Momentum" in text

    def test_to_dict(self) -> None:
        report = MomentumReport(
            trade_date="20260610",
            lookback_days=5,
            items=[
                MomentumInfo(
                    ticker="000001",
                    name="Test",
                    score_current=0.5,
                    slope=0.01,
                    momentum_label="improving",
                    momentum_bonus=0.05,
                    days_observed=3,
                ),
            ],
        )
        d = report.to_dict()
        assert d["trade_date"] == "20260610"
        assert len(d["items"]) == 1
        assert d["items"][0]["ticker"] == "000001"
        assert d["items"][0]["momentum_bonus"] == 0.05
