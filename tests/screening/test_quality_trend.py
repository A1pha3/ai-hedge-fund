"""Tests for src/screening/quality_trend.py — Q-3 推荐质量趋势."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.quality_trend import (
    QualityTrendReport,
    QualityWindow,
    compute_quality_trend,
    render_quality_trend_line,
)


def _seed_tracking(dir_path: Path, records: list[dict]) -> None:
    (dir_path / "tracking_history.json").write_text(json.dumps(records), encoding="utf-8")


def _rec(ticker: str, date: str, t30: float | None) -> dict:
    return {"ticker": ticker, "recommended_date": date, "recommendation_score": 0.7, "next_30day_return": t30}


# ---------------------------------------------------------------------------
# compute_quality_trend
# ---------------------------------------------------------------------------


class TestComputeQualityTrend:
    def test_improving_trend(self, tmp_path: Path) -> None:
        """4 weekly windows; win-rate rises 40%→60%→80%→100% → ↑改善."""
        # oldest window (W-3): 2 wins / 5
        recs = [_rec(f"00000{i}", "20260101", 5.0) for i in range(2)]
        recs += [_rec(f"00000{i}", "20260101", -3.0) for i in range(2, 5)]
        # W-2: 3/5
        recs += [_rec(f"10000{i}", "20260108", 5.0) for i in range(3)]
        recs += [_rec(f"10000{i}", "20260108", -3.0) for i in range(3, 5)]
        # W-1: 4/5
        recs += [_rec(f"20000{i}", "20260115", 5.0) for i in range(4)]
        recs += [_rec(f"20000{i}", "20260115", -3.0) for i in range(4, 5)]
        # current: 5/5
        recs += [_rec(f"30000{i}", "20260122", 5.0) for i in range(5)]
        _seed_tracking(tmp_path, recs)
        report = compute_quality_trend(reports_dir=tmp_path, n_windows=4, window_days=7)
        assert len(report.windows) == 4
        rates = [w.t30_win_rate for w in report.windows if w.t30_win_rate is not None]
        assert rates == sorted(rates)  # monotonically rising
        assert "改善" in report.trend_direction or "↑" in report.trend_direction

    def test_degrading_trend(self, tmp_path: Path) -> None:
        """Win-rate falls → ↓恶化."""
        recs = [_rec(f"00000{i}", "20260101", 5.0) for i in range(5)]  # 5/5 oldest
        recs += [_rec(f"10000{i}", "20260108", 5.0) for i in range(4)]
        recs += [_rec(f"10000{i}", "20260108", -3.0) for i in range(4, 5)]  # 4/5
        recs += [_rec(f"20000{i}", "20260115", 5.0) for i in range(3)]
        recs += [_rec(f"20000{i}", "20260115", -3.0) for i in range(3, 5)]  # 3/5
        recs += [_rec(f"30000{i}", "20260122", -3.0) for i in range(5)]  # 0/5 current
        _seed_tracking(tmp_path, recs)
        report = compute_quality_trend(reports_dir=tmp_path, n_windows=4, window_days=7)
        assert "恶化" in report.trend_direction or "↓" in report.trend_direction

    def test_stable_trend(self, tmp_path: Path) -> None:
        """Win-rate flat → →平稳."""
        # all windows 2/4 = 0.5
        for win_start in ["20260101", "20260108", "20260115", "20260122"]:
            pass
        recs = []
        for d in ["20260101", "20260108", "20260115", "20260122"]:
            recs += [_rec(f"{d}{i}", d, 5.0) for i in range(2)]
            recs += [_rec(f"{d}{i}", d, -3.0) for i in range(2, 4)]
        _seed_tracking(tmp_path, recs)
        report = compute_quality_trend(reports_dir=tmp_path, n_windows=4, window_days=7)
        assert "平稳" in report.trend_direction or "→" in report.trend_direction

    def test_no_data(self, tmp_path: Path) -> None:
        """Empty tracking → 4 windows all None, trend 数据不足."""
        _seed_tracking(tmp_path, [])
        report = compute_quality_trend(reports_dir=tmp_path, n_windows=4, window_days=7)
        assert all(w.t30_win_rate is None for w in report.windows)
        assert "不足" in report.trend_direction or "—" in report.trend_direction

    def test_some_windows_immature(self, tmp_path: Path) -> None:
        """Windows with no matured T+30 → None; trend uses available windows only."""
        recs = [_rec("000001", "20260101", 5.0), _rec("000002", "20260101", -3.0)]
        _seed_tracking(tmp_path, recs)
        report = compute_quality_trend(reports_dir=tmp_path, n_windows=4, window_days=7)
        # only the oldest window has data; others None
        assert any(w.t30_win_rate is not None for w in report.windows)
        assert any(w.t30_win_rate is None for w in report.windows)

    def test_window_sample_counts(self, tmp_path: Path) -> None:
        recs = [_rec(f"00000{i}", "20260101", 5.0) for i in range(3)]
        _seed_tracking(tmp_path, recs)
        report = compute_quality_trend(reports_dir=tmp_path, n_windows=4, window_days=7)
        # records on the latest date → land in the newest window (当前)
        newest = report.windows[-1]
        assert newest.sample_count >= 3
        assert newest.mature_count == 3


# ---------------------------------------------------------------------------
# render_quality_trend_line
# ---------------------------------------------------------------------------


class TestRenderQualityTrendLine:
    def test_renders_windows_and_trend(self) -> None:
        report = QualityTrendReport(
            windows=[
                QualityWindow(label="W-3", t30_win_rate=0.52, sample_count=8, mature_count=8),
                QualityWindow(label="W-2", t30_win_rate=0.58, sample_count=10, mature_count=10),
                QualityWindow(label="W-1", t30_win_rate=0.61, sample_count=7, mature_count=7),
                QualityWindow(label="当前", t30_win_rate=None, sample_count=0, mature_count=0),
            ],
            trend_direction="↑改善",
        )
        out = render_quality_trend_line(report)
        assert "52%" in out
        assert "58%" in out
        assert "改善" in out or "↑" in out

    def test_insufficient_empty(self) -> None:
        report = QualityTrendReport(
            windows=[QualityWindow(label=f"W-{i}", t30_win_rate=None, sample_count=0, mature_count=0) for i in range(4)],
            trend_direction="—数据不足",
        )
        out = render_quality_trend_line(report)
        assert "不足" in out or "—" in out
