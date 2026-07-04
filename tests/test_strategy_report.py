"""Tests for strategy_report.py — P15-2 strategy performance report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.screening.strategy_report import (
    compute_strategy_report,
    render_strategy_report,
    StrategyReport,
    StrategyStats,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_reports(tmp_dir: Path, reports: dict[str, list[dict]]) -> None:
    for date_str, recs in reports.items():
        path = tmp_dir / f"auto_screening_{date_str}.json"
        path.write_text(
            json.dumps({"trade_date": date_str, "recommendations": recs}),
            encoding="utf-8",
        )


def _make_rec(ticker: str, score_b: float, trend_conf: float = 70.0) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "name": f"Stock_{ticker}",
        "score_b": score_b,
        "strategy_signals": {
            "trend": {"signal": "bullish", "confidence": trend_conf, "direction": 1},
            "fundamental": {"signal": "bullish", "confidence": 60.0, "direction": 1},
            "mean_reversion": {"signal": "neutral", "confidence": 40.0, "direction": 0},
            "event_sentiment": {"signal": "bearish", "confidence": 55.0, "direction": -1},
        },
    }


# ---------------------------------------------------------------------------
# Integration: compute_strategy_report
# ---------------------------------------------------------------------------


class TestComputeStrategyReport:
    def test_empty_dir(self, tmp_path: Path) -> None:
        report = compute_strategy_report(reports_dir=tmp_path)
        assert report.strategies == []

    def test_single_report(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", 0.5)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_strategy_report(reports_dir=tmp_path)
        assert len(report.strategies) == 4
        # Trend should have signals
        trend = next(s for s in report.strategies if s.strategy == "trend")
        assert trend.signal_count >= 1
        assert trend.avg_confidence > 0

    def test_multiple_reports(self, tmp_path: Path) -> None:
        for i in range(5):
            recs = [_make_rec("000001", 0.5, trend_conf=50.0 + i * 10)]
            _write_reports(tmp_path, {f"202606{10 + i:02d}": recs})
        report = compute_strategy_report(lookback_days=5, reports_dir=tmp_path)
        trend = next(s for s in report.strategies if s.strategy == "trend")
        assert trend.signal_count == 5

    def test_strong_signal_count(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", 0.5, trend_conf=80.0)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_strategy_report(reports_dir=tmp_path)
        trend = next(s for s in report.strategies if s.strategy == "trend")
        assert trend.strong_signal_count >= 1  # confidence=80 >= 60

    def test_bullish_bearish_counts(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", 0.5)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_strategy_report(reports_dir=tmp_path)
        event = next(s for s in report.strategies if s.strategy == "event_sentiment")
        assert event.bearish_count >= 1  # direction=-1 in test data

    def test_sorted_by_strong_signals(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", 0.5, trend_conf=90.0)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_strategy_report(reports_dir=tmp_path)
        # Should be sorted by strong_signal_count descending
        for i in range(1, len(report.strategies)):
            assert report.strategies[i - 1].strong_signal_count >= report.strategies[i].strong_signal_count

    def test_recommendation_generated(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", 0.5, trend_conf=80.0)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_strategy_report(reports_dir=tmp_path)
        assert report.recommendation != ""

    def test_to_dict(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", 0.5)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_strategy_report(reports_dir=tmp_path)
        d = report.to_dict()
        assert "strategies" in d
        assert len(d["strategies"]) == 4
        assert "recommendation" in d


# ---------------------------------------------------------------------------
# Unit: render_strategy_report
# ---------------------------------------------------------------------------


class TestRenderStrategyReport:
    def test_empty(self) -> None:
        output = render_strategy_report(StrategyReport())
        assert "无数据" in output

    def test_with_strategies(self) -> None:
        report = StrategyReport(
            trade_date="20260610",
            lookback_days=7,
            strategies=[
                StrategyStats(
                    strategy="trend",
                    name="趋势",
                    signal_count=10,
                    bullish_count=8,
                    bearish_count=2,
                    strong_signal_count=6,
                    avg_confidence=72.5,
                ),
            ],
            recommendation="趋势信号最强",
        )
        output = render_strategy_report(report)
        assert "趋势" in output
        assert "10" in output
        assert "策略表现周报" in output

    def test_no_strategies(self) -> None:
        report = StrategyReport(trade_date="20260610", strategies=[])
        output = render_strategy_report(report)
        # With empty strategies list, should still render
        assert "Strategy Performance" in output
