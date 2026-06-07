"""Tests for run_top — 快速查看最近推荐 (无需重跑 --auto)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.main import run_top


def _write_report(tmp_path: Path, date: str = "20260608", recs: list[dict] | None = None) -> Path:
    """Helper: write a minimal auto_screening report to disk."""
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"auto_screening_{date}.json"
    payload = {
        "date": date,
        "market_state": {"state_type": "mixed"},
        "layer_a_count": 100,
        "recommendations": recs or [
            {"ticker": "300750", "name": "宁德时代", "industry_sw": "电气设备", "score_b": 0.55, "decision": "watch", "consecutive_days": 3, "decay": {"level": "none"}},
            {"ticker": "000001", "name": "平安银行", "industry_sw": "银行", "score_b": 0.35, "decision": "watch", "consecutive_days": 1, "decay": {"level": "mild", "change_pct": -5}},
        ],
    }
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    return report_path


def _write_empty_report(tmp_path: Path, date: str = "20260608") -> Path:
    """Helper: write a report with empty recommendations list."""
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"auto_screening_{date}.json"
    payload = {
        "date": date,
        "market_state": {"state_type": "mixed"},
        "layer_a_count": 0,
        "recommendations": [],
    }
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    return report_path


class TestRunTop:
    """--top CLI 命令测试。"""

    def test_no_report_returns_1(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """无报告时返回 1 并提示用户先跑 --auto。"""
        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=tmp_path / "nonexist"):
            with patch("src.reporting.pdf_exporter.find_latest_report", return_value=None):
                rc = run_top()
        assert rc == 1
        output = capsys.readouterr().out
        assert "未找到" in output

    def test_displays_top_results(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """正常显示 Top N 推荐。"""
        report_path = _write_report(tmp_path)
        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=report_path.parent):
            with patch("src.reporting.pdf_exporter.find_latest_report", return_value=report_path):
                rc = run_top(top_n=10)
        assert rc == 0
        output = capsys.readouterr().out
        assert "300750" in output
        assert "宁德时代" in output
        assert "+0.5500" in output
        assert "最近推荐" in output

    def test_top_n_limits_output(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """--top 1 只显示 1 条推荐。"""
        recs = [
            {"ticker": f"00000{i}", "name": f"Stock{i}", "industry_sw": "行业", "score_b": 0.5 - i * 0.1, "decision": "watch", "consecutive_days": 0, "decay": {"level": "none"}}
            for i in range(5)
        ]
        report_path = _write_report(tmp_path, recs=recs)
        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=report_path.parent):
            with patch("src.reporting.pdf_exporter.find_latest_report", return_value=report_path):
                rc = run_top(top_n=1)
        assert rc == 0
        output = capsys.readouterr().out
        assert "000000" in output
        assert "000001" not in output

    def test_empty_recommendations(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """报告存在但推荐为空时返回 0。"""
        report_path = _write_empty_report(tmp_path)
        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=report_path.parent):
            with patch("src.reporting.pdf_exporter.find_latest_report", return_value=report_path):
                rc = run_top()
        assert rc == 0
        output = capsys.readouterr().out
        assert "无推荐" in output

    def test_shows_consecutive_and_decay(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """显示连续推荐天数和衰减标记。"""
        recs = [
            {"ticker": "300750", "name": "宁德时代", "industry_sw": "电气设备", "score_b": 0.55, "decision": "watch", "consecutive_days": 3, "decay": {"level": "mild", "change_pct": -8}},
        ]
        report_path = _write_report(tmp_path, recs=recs)
        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=report_path.parent):
            with patch("src.reporting.pdf_exporter.find_latest_report", return_value=report_path):
                rc = run_top()
        assert rc == 0
        output = capsys.readouterr().out
        assert "3d" in output
        assert "↓8%" in output

    def test_invalid_report_returns_1(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """报告 JSON 损坏时返回 1。"""
        report_dir = tmp_path / "reports"
        report_dir.mkdir(parents=True)
        bad_path = report_dir / "auto_screening_20260608.json"
        bad_path.write_text("NOT JSON", encoding="utf-8")
        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=report_dir):
            with patch("src.reporting.pdf_exporter.find_latest_report", return_value=bad_path):
                rc = run_top()
        assert rc == 1
        output = capsys.readouterr().out
        assert "无法加载" in output

    def test_cache_stats_shown(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """batch_data_fetcher 统计信息被显示。"""
        recs = [{"ticker": "300750", "name": "宁德时代", "industry_sw": "电气设备", "score_b": 0.55, "decision": "watch", "consecutive_days": 1, "decay": {"level": "none"}}]
        report_dir = tmp_path / "reports"
        report_dir.mkdir(parents=True)
        report_path = report_dir / "auto_screening_20260608.json"
        payload = {
            "date": "20260608",
            "market_state": {"state_type": "mixed"},
            "layer_a_count": 50,
            "recommendations": recs,
            "batch_data_fetcher": {"batch_calls": 2, "batch_failures": 0, "single_ticker_calls": 50, "single_ticker_cache_hits": 30, "cache_hits": 5},
        }
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=report_dir):
            with patch("src.reporting.pdf_exporter.find_latest_report", return_value=report_path):
                rc = run_top()
        assert rc == 0
        output = capsys.readouterr().out
        assert "Cache:" in output
