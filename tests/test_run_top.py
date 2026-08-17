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
        "recommendations": recs
        or [
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
        # v3 (2026-08-16): 桶分组纪律 — 4 位小数信号分已删, 档头带区间+名次
        assert "信号分档" in output
        assert "本表第 1 名" in output
        assert "最近推荐" in output

    def test_top_n_limits_output(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """--top 1 只显示 1 条推荐。"""
        recs = [{"ticker": f"00000{i}", "name": f"Stock{i}", "industry_sw": "行业", "score_b": 0.5 - i * 0.1, "decision": "watch", "consecutive_days": 0, "decay": {"level": "none"}} for i in range(5)]
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
        assert "3天" in output  # v3: 连续天数中文 (旧 "3d" 已废)
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
        assert "缓存命中:" in output

    def test_top_table_is_chinese_and_bucket_grouped(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """G3 (v3 2026-08-16): --top 与 --auto 同一展示契约 — 中文表头 + 桶分组
        档头; 旧「池胜率」逐行列已删 (桶级钱数上档头一次)。本 fixture 的
        report_dir 无 tracking_history → 档头走确定性空态, 不编造数字。"""
        recs = [{
            "ticker": "300750", "name": "宁德时代", "industry_sw": "电力设备",
            "score_b": 0.55, "decision": "watch", "consecutive_days": 1,
            "decay": {"level": "none"},
            "win_rates": {"t5": 0.4825, "t10": 0.4701}, "bucket_sample_count": 428,
        }]
        report_dir = tmp_path / "reports"
        report_dir.mkdir(parents=True)
        report_path = report_dir / "auto_screening_20260608.json"
        payload = {
            "date": "20260608",
            "market_state": {"state_type": "mixed"},
            "layer_a_count": 50,
            "recommendations": recs,
        }
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=report_dir):
            with patch("src.reporting.pdf_exporter.find_latest_report", return_value=report_path):
                rc = run_top()
        assert rc == 0
        output = capsys.readouterr().out
        assert "信号分档 0.5-0.6" in output  # score_b=0.55 → 档 0.5-0.6, 中文区间
        assert "前门" in output  # --top 独有判决列保留
        assert "不提供估计" in output  # 无 tracking → 档头空态, 不显示编造胜率
        assert "Front Door" not in output
        assert "watch" not in output

    def test_malformed_score_b_does_not_crash(self, capsys: pytest.CaptureFixture[str], tmp_path: Path, caplog) -> None:
        """score_b 越界时不崩溃 — v3 契约: 坏行**跳过 + 警告**, 不再渲染补零行。

        旧契约 (渲染 0.0) 已废: 桶分组依赖 score_b, 报告 JSON 来自自身 dump,
        坏行应响亮暴露而不是被 "+0.0000" 静默淹没。"""
        recs = [
            {"ticker": "300750", "name": "宁德时代", "industry_sw": "电气设备", "score_b": 5.0, "decision": "watch", "consecutive_days": 1, "decay": {"level": "none"}},
            {"ticker": "000001", "name": "平安银行", "industry_sw": "银行", "score_b": 0.35, "decision": "watch", "consecutive_days": 1, "decay": {"level": "none"}},
        ]
        report_path = _write_report(tmp_path, recs=recs)
        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=report_path.parent):
            with patch("src.reporting.pdf_exporter.find_latest_report", return_value=report_path):
                rc = run_top()
        assert rc == 0
        output = capsys.readouterr().out
        assert "000001" in output  # 合法行照常渲染
        assert "300750" not in output  # 坏行被跳过 (不再以 +0.0000 补零渲染)
        assert any("300750" in r.message for r in caplog.records)  # 且有跳行警告


# ── autodev-29 loop 146: report staleness disclosure ──


class TestRunTopStaleness:
    """报告时效性披露 — 过时报 (≥2天) 显示 ⚠ 警告."""

    def test_staleness_warning_shown_for_old_report(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """报告超过 2 天 → 必须显示时效性警告."""
        from datetime import datetime

        report_date = "20260704"  # 3 days before 20260707
        report_path = _write_report(tmp_path, date=report_date)

        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=report_path.parent):
            with patch("src.reporting.pdf_exporter.find_latest_report", return_value=report_path):
                # Mock datetime.now to 20260707 (3 days after report)
                with patch("src.main.datetime") as mock_dt:
                    mock_dt.now.return_value = datetime(2026, 7, 7)
                    mock_dt.strptime = datetime.strptime
                    rc = run_top()
        assert rc == 0
        output = capsys.readouterr().out
        assert "报告已过 3 天" in output
        assert "⚠" in output

    def test_staleness_warning_hidden_for_fresh_report(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """报告 1 天内 → 不显示时效性警告."""
        from datetime import datetime

        report_date = "20260706"  # yesterday
        report_path = _write_report(tmp_path, date=report_date)

        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=report_path.parent):
            with patch("src.reporting.pdf_exporter.find_latest_report", return_value=report_path):
                with patch("src.main.datetime") as mock_dt:
                    mock_dt.now.return_value = datetime(2026, 7, 7)
                    mock_dt.strptime = datetime.strptime
                    rc = run_top()
        assert rc == 0
        output = capsys.readouterr().out
        assert "⚠ 报告已过" not in output  # 1-day-old report, no warming
