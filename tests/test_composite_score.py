"""Tests for composite_score.py — P11-1."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.screening.composite_score import (
    CompositeEntry,
    CompositeReport,
    compute_composite_scores,
    render_composite_scores,
    render_composite_compact,
)


def _write_reports(tmp_dir: Path, reports: dict[str, list[dict]]) -> None:
    for date_str, recs in reports.items():
        path = tmp_dir / f"auto_screening_{date_str}.json"
        path.write_text(
            json.dumps({"trade_date": date_str, "recommendations": recs}),
            encoding="utf-8",
        )


def _make_rec(
    ticker: str,
    name: str,
    score_b: float,
    industry: str = "电子",
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "name": name,
        "score_b": score_b,
        "industry_sw": industry,
        "strategy_signals": {
            "trend": {"signal": "bullish", "confidence": 70, "direction": 1},
            "fundamental": {"signal": "bullish", "confidence": 60, "direction": 1},
            "mean_reversion": {"signal": "neutral", "confidence": 40, "direction": 0},
            "event_sentiment": {"signal": "bullish", "confidence": 55, "direction": 1},
        },
    }


class TestComputeCompositeScores:
    def test_no_reports(self, tmp_path: Path) -> None:
        report = compute_composite_scores(reports_dir=tmp_path)
        assert report.items == []

    def test_single_report_basic(self, tmp_path: Path) -> None:
        recs = [
            _make_rec("000001", "平安银行", 0.5, "银行"),
            _make_rec("300750", "宁德时代", 0.6, "电气设备"),
        ]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_composite_scores(reports_dir=tmp_path)
        assert len(report.items) == 2
        # Items sorted by composite_score descending
        assert report.items[0].base_score >= report.items[1].base_score

    def test_composite_includes_base_score(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", "Test", 0.5)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_composite_scores(reports_dir=tmp_path)
        item = report.items[0]
        assert item.base_score == 0.5
        # composite_score should be base_score + adjustments
        assert item.composite_score != 0.0 or item.base_score == 0.0

    def test_composite_clamped(self, tmp_path: Path) -> None:
        """Composite score should be clamped to [-1.0, +1.0]."""
        recs = [_make_rec("000001", "Test", 0.99)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_composite_scores(reports_dir=tmp_path)
        assert -1.0 <= report.items[0].composite_score <= 1.0

    def test_top_n_limits(self, tmp_path: Path) -> None:
        recs = [_make_rec(f"{i:06d}", f"S{i}", 0.5, "电子") for i in range(10)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_composite_scores(reports_dir=tmp_path, top_n=3)
        assert len(report.items) == 3

    def test_trade_date_extracted(self, tmp_path: Path) -> None:
        _write_reports(tmp_path, {"20260610": [_make_rec("000001", "T", 0.5)]})
        report = compute_composite_scores(reports_dir=tmp_path)
        assert report.trade_date == "20260610"

    def test_to_dict(self, tmp_path: Path) -> None:
        _write_reports(tmp_path, {"20260610": [_make_rec("000001", "T", 0.5)]})
        report = compute_composite_scores(reports_dir=tmp_path)
        d = report.to_dict()
        assert "items" in d
        assert "volume_factor" in d["items"][0]

    def test_score_b_none_safe(self, tmp_path: Path) -> None:
        rec = {"ticker": "000001", "name": "T", "score_b": None, "strategy_signals": {}}
        _write_reports(tmp_path, {"20260610": [rec]})
        report = compute_composite_scores(reports_dir=tmp_path)
        assert len(report.items) == 1
        assert report.items[0].base_score == 0.0


class TestRenderCompositeScores:
    def test_empty(self) -> None:
        text = render_composite_scores(CompositeReport())
        assert "无推荐数据" in text

    def test_basic(self) -> None:
        report = CompositeReport(
            trade_date="20260610",
            items=[
                CompositeEntry(
                    ticker="000001",
                    name="Test",
                    base_score=0.5,
                    momentum_bonus=0.05,
                    sector_bonus=0.0,
                    consistency_adj=0.0,
                    volume_factor=0.0,
                    composite_score=0.55,
                ),
            ],
        )
        text = render_composite_scores(report)
        assert "000001" in text
        assert "Composite Confidence" in text

    def test_compact(self) -> None:
        report = CompositeReport(
            items=[
                CompositeEntry(ticker="000001", composite_score=0.55),
            ],
        )
        text = render_composite_compact(report)
        assert "000001" in text

    def test_compact_empty(self) -> None:
        text = render_composite_compact(CompositeReport())
        assert "无" in text

    def test_grade_distribution(self) -> None:
        report = CompositeReport(
            trade_date="20260610",
            items=[
                CompositeEntry(ticker="A", composite_score=0.8),
                CompositeEntry(ticker="B", composite_score=0.4),
            ],
        )
        text = render_composite_scores(report)
        assert "A级" in text
