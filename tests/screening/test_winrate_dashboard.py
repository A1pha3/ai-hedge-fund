"""Tests for src/screening/winrate_dashboard.py — P2-4 历史推荐胜率看板."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.screening.winrate_dashboard import (
    DailyWinRate,
    WinRateSummary,
    _compute_horizon_stats,
    _determine_trend,
    _format_date_short,
    _parse_date,
    compute_winrate_dashboard,
    render_winrate_dashboard,
)


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_yyyymmdd(self) -> None:
        assert _parse_date("20260101") == datetime(2026, 1, 1)

    def test_yyyy_mm_dd(self) -> None:
        assert _parse_date("2026-01-01") == datetime(2026, 1, 1)

    def test_empty_returns_none(self) -> None:
        assert _parse_date("") is None

    def test_invalid_returns_none(self) -> None:
        assert _parse_date("not a date") is None

    def test_too_short_returns_none(self) -> None:
        assert _parse_date("2026") is None

    def test_non_digit_returns_none(self) -> None:
        assert _parse_date("20260101X") is None


# ---------------------------------------------------------------------------
# _format_date_short
# ---------------------------------------------------------------------------


class TestFormatDateShort:
    def test_yyyymmdd(self) -> None:
        assert _format_date_short("20260101") == "01-01"

    def test_yyyy_mm_dd(self) -> None:
        # The function only strips hyphens but checks length
        assert _format_date_short("2026-12-25") == "12-25"

    def test_unparseable_returns_as_is(self) -> None:
        assert _format_date_short("bad") == "bad"


# ---------------------------------------------------------------------------
# _compute_horizon_stats
# ---------------------------------------------------------------------------


class TestComputeHorizonStats:
    def test_empty(self) -> None:
        wr, avg, count = _compute_horizon_stats([], "next_day_return")
        assert wr is None
        assert avg is None
        assert count == 0

    def test_all_winners(self) -> None:
        records = [{"next_day_return": 1.0}, {"next_day_return": 2.0}, {"next_day_return": 0.5}]
        wr, avg, count = _compute_horizon_stats(records, "next_day_return")
        assert wr == 1.0
        assert avg == pytest.approx(1.166, abs=1e-2)
        assert count == 3

    def test_all_losers(self) -> None:
        records = [{"next_day_return": -1.0}, {"next_day_return": -2.0}]
        wr, avg, count = _compute_horizon_stats(records, "next_day_return")
        assert wr == 0.0
        assert avg == pytest.approx(-1.5)
        assert count == 2

    def test_mixed(self) -> None:
        records = [{"next_day_return": 1.0}, {"next_day_return": -1.0}]
        wr, avg, count = _compute_horizon_stats(records, "next_day_return")
        assert wr == 0.5
        assert avg == 0.0
        assert count == 2

    def test_zero_return_is_not_winner(self) -> None:
        """Zero return is NOT a winner (only > 0)."""
        records = [{"next_day_return": 0.0}]
        wr, _, _ = _compute_horizon_stats(records, "next_day_return")
        assert wr == 0.0

    def test_missing_field_skipped(self) -> None:
        records = [{"next_day_return": 1.0}, {"other": 2.0}]
        wr, avg, count = _compute_horizon_stats(records, "next_day_return")
        assert count == 1
        assert wr == 1.0

    def test_none_value_skipped(self) -> None:
        records = [{"next_day_return": None}]
        wr, _, count = _compute_horizon_stats(records, "next_day_return")
        assert count == 0
        assert wr is None


# ---------------------------------------------------------------------------
# _determine_trend
# ---------------------------------------------------------------------------


class TestDetermineTrend:
    def test_no_data(self) -> None:
        assert _determine_trend([]) == "stable"

    def test_single_day(self) -> None:
        day = DailyWinRate(date="20260101", t1_win_rate=0.5)
        assert _determine_trend([day]) == "stable"

    def test_improving(self) -> None:
        # 14 days, recent 7 = 0.7, earlier 7 = 0.3 → diff=0.4 > 0.05 → improving
        days = [
            DailyWinRate(date=f"202601{i:02d}", t1_win_rate=0.3)
            for i in range(1, 8)
        ] + [
            DailyWinRate(date=f"202602{i:02d}", t1_win_rate=0.7)
            for i in range(1, 8)
        ]
        assert _determine_trend(days) == "improving"

    def test_declining(self) -> None:
        days = [
            DailyWinRate(date=f"202601{i:02d}", t1_win_rate=0.7)
            for i in range(1, 8)
        ] + [
            DailyWinRate(date=f"202602{i:02d}", t1_win_rate=0.3)
            for i in range(1, 8)
        ]
        assert _determine_trend(days) == "declining"

    def test_stable_small_diff(self) -> None:
        """14 days, recent=0.50, earlier=0.48 → diff=0.02 ≤ 0.05 → stable."""
        days = [
            DailyWinRate(date=f"202601{i:02d}", t1_win_rate=0.48)
            for i in range(1, 8)
        ] + [
            DailyWinRate(date=f"202602{i:02d}", t1_win_rate=0.50)
            for i in range(1, 8)
        ]
        assert _determine_trend(days) == "stable"

    def test_boundary_improving(self) -> None:
        """14 days, recent=0.6, earlier=0.5 → diff=0.1 > 0.05 → improving."""
        days = [
            DailyWinRate(date=f"202601{i:02d}", t1_win_rate=0.50)
            for i in range(1, 8)
        ] + [
            DailyWinRate(date=f"202602{i:02d}", t1_win_rate=0.60)
            for i in range(1, 8)
        ]
        assert _determine_trend(days) == "improving"

    def test_few_days_uses_midpoint(self) -> None:
        """4 days: midpoint split into 2 each."""
        days = [
            DailyWinRate(date="20260101", t1_win_rate=0.3),
            DailyWinRate(date="20260102", t1_win_rate=0.3),
            DailyWinRate(date="20260103", t1_win_rate=0.7),
            DailyWinRate(date="20260104", t1_win_rate=0.7),
        ]
        assert _determine_trend(days) == "improving"


# ---------------------------------------------------------------------------
# DailyWinRate / WinRateSummary
# ---------------------------------------------------------------------------


class TestDailyWinRate:
    def test_to_dict(self) -> None:
        d = DailyWinRate(date="20260101", total_recommendations=5, t1_win_rate=0.6)
        result = d.to_dict()
        assert result["date"] == "20260101"
        assert result["t1_win_rate"] == 0.6


class TestWinRateSummary:
    def test_to_dict(self) -> None:
        s = WinRateSummary(period_days=30, total_days=5, trend="improving")
        result = s.to_dict()
        assert result["period_days"] == 30
        assert result["trend"] == "improving"


# ---------------------------------------------------------------------------
# compute_winrate_dashboard
# ---------------------------------------------------------------------------


class TestComputeWinrateDashboard:
    def test_no_file(self, tmp_path) -> None:
        result = compute_winrate_dashboard(tmp_path / "missing.json", lookback_days=30)
        assert result.total_days == 0
        assert result.daily == []

    def test_corrupt_file(self, tmp_path) -> None:
        path = tmp_path / "tracking_history.json"
        path.write_text("NOT JSON", encoding="utf-8")
        result = compute_winrate_dashboard(path, lookback_days=30)
        assert result.total_days == 0

    def test_empty_history(self, tmp_path) -> None:
        path = tmp_path / "tracking_history.json"
        path.write_text(json.dumps({"records": []}), encoding="utf-8")
        result = compute_winrate_dashboard(path, lookback_days=30)
        assert result.total_days == 0

    def test_with_recent_data(self, tmp_path) -> None:
        path = tmp_path / "tracking_history.json"
        today = datetime.now()
        rec_date = today.strftime("%Y%m%d")
        records = {
            "records": [
                {"recommended_date": rec_date, "next_day_return": 1.5},
                {"recommended_date": rec_date, "next_day_return": -0.5},
            ],
        }
        path.write_text(json.dumps(records), encoding="utf-8")
        result = compute_winrate_dashboard(path, lookback_days=30)
        assert result.total_days >= 1
        assert result.total_recommendations == 2

    def test_old_data_excluded(self, tmp_path) -> None:
        path = tmp_path / "tracking_history.json"
        old_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
        records = {"records": [{"recommended_date": old_date, "next_day_return": 1.0}]}
        path.write_text(json.dumps(records), encoding="utf-8")
        result = compute_winrate_dashboard(path, lookback_days=30)
        assert result.total_days == 0

    def test_invalid_date_excluded(self, tmp_path) -> None:
        path = tmp_path / "tracking_history.json"
        records = {
            "records": [
                {"recommended_date": "invalid", "next_day_return": 1.0},
                {"recommended_date": datetime.now().strftime("%Y%m%d"), "next_day_return": 1.0},
            ],
        }
        path.write_text(json.dumps(records), encoding="utf-8")
        result = compute_winrate_dashboard(path, lookback_days=30)
        assert result.total_recommendations == 1


# ---------------------------------------------------------------------------
# render_winrate_dashboard
# ---------------------------------------------------------------------------


class TestRenderWinrateDashboard:
    def test_empty(self) -> None:
        result = render_winrate_dashboard(WinRateSummary(period_days=30))
        assert "暂无推荐历史数据" in result

    def test_with_data(self) -> None:
        s = WinRateSummary(
            period_days=30,
            total_days=2,
            total_recommendations=5,
            avg_t1_win_rate=0.6,
            avg_t1_return=1.5,
            trend="improving",
            daily=[
                DailyWinRate(date="20260101", t1_win_rate=0.6),
                DailyWinRate(date="20260102", t1_win_rate=0.7),
            ],
        )
        result = render_winrate_dashboard(s)
        assert "improving" in result or "📈" in result
        assert "胜率看板" in result
        assert "20260101" not in result  # formatted as MM-DD
        assert "01-01" in result
