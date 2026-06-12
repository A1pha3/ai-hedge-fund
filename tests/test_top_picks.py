"""Tests for top_picks.py — P12-2."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.screening.expected_return import ExpectedReturn, ExpectedReturnReport
from src.screening.top_picks import run_top_picks


def _make_rec(ticker: str, name: str, score_b: float, industry: str = "电子") -> dict[str, Any]:
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


def _write_report(tmp_dir: Path, recs: list[dict], date: str = "20260610") -> None:
    path = tmp_dir / f"auto_screening_{date}.json"
    path.write_text(
        json.dumps({"trade_date": date, "recommendations": recs}),
        encoding="utf-8",
    )


class TestTopPicks:
    def test_no_report(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 1
        assert "No auto_screening report found" in capsys.readouterr().out

    def test_empty_recommendations(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_report(tmp_path, [])
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0

    def test_basic_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [
            _make_rec("300750", "宁德时代", 0.6, "电气设备"),
            _make_rec("000001", "平安银行", 0.3, "银行"),
            _make_rec("600519", "贵州茅台", 0.5, "食品饮料"),
        ]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "Top Picks" in output
        assert "300750" in output

    def test_count_limits_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec(f"{i:06d}", f"Stock{i}", 0.5) for i in range(10)]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=3, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        # Should show at most 3 numbered picks
        assert "1." in output
        assert "3." in output

    def test_high_confidence_message(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec("300750", "宁德时代", 0.8)]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "High confidence" in output

    def test_no_confidence_message(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec("000001", "平安银行", 0.05)]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "No high-confidence" in output or "waiting" in output

    def test_signal_breakdown(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec("300750", "宁德时代", 0.6)]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        # Should show signal breakdown (动量/行业/一致/量价)
        assert "base=" in output

    @patch(
        "src.screening.expected_return.compute_expected_returns",
        return_value=ExpectedReturnReport(
            trade_date="20260610",
            lookback_days=60,
            total_samples=120,
            items=[
                ExpectedReturn(
                    ticker="300750",
                    score_b=0.8,
                    bucket_label="高 (>0.8)",
                    bucket_sample_count=40,
                    expected_returns={"t1": 1.0, "t5": 3.5, "t10": 5.2, "t20": 8.1, "t30": 11.4},
                    win_rates={"t1": 0.55, "t5": 0.60, "t10": 0.61, "t20": 0.63, "t30": 0.66},
                ),
            ],
        ),
    )
    def test_output_includes_t30_investability_evidence(self, _mock_expected: object, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec("300750", "宁德时代", 0.8)]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "T+30" in output
        assert "样本" in output
