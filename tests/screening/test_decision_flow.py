"""Tests for decision_flow.py -- P8-1."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.screening.decision_flow import run_decision_flow, render_decision_flow_summary


def _make_report(date_str: str, recs: list[dict]) -> dict:
    return {"trade_date": date_str, "recommendations": recs}


def _make_rec(ticker: str, name: str, score_b: float, signals: dict | None = None) -> dict:
    return {"ticker": ticker, "name": name, "score_b": score_b, "strategy_signals": signals or {}}


class TestDecisionFlow:
    def test_no_report_returns_error(self, tmp_path: Path) -> None:
        result = run_decision_flow(reports_dir=tmp_path)
        assert result.get("error") == "no_report"

    def test_full_flow_runs(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [_make_rec("000001", "A", 0.7)])
        today = _make_report("20260611", [
            _make_rec("000001", "A", 0.8, {
                "trend": {"signal": "bullish", "confidence": 80},
                "mean_reversion": {"signal": "bullish", "confidence": 70},
            }),
        ])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = run_decision_flow(top_n=10, reports_dir=reports_dir)
        assert "error" not in result
        assert result["recommendation_count"] == 1
        assert "freshness" in result
        assert "consistency" in result
        assert "dynamic_threshold" in result
        assert "daily_delta" in result

    def test_render_summary(self) -> None:
        flow = {
            "trade_date": "20260611",
            "recommendation_count": 5,
            "freshness": {"fresh": True},
            "high_consistency_count": 4,
        }
        output = render_decision_flow_summary(flow)
        assert "20260611" in output
        assert "5" in output
        assert "PASS" in output
