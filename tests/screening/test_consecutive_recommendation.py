"""Tests for src/screening/consecutive_recommendation.py — P0-6 连续推荐."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.screening.consecutive_recommendation import (
    _classify_status,
    _format_date,
    _parse_date,
    compute_consecutive_recommendations,
    ConsecutiveStats,
    DEFAULT_LOOKBACK_DAYS,
    load_auto_screening_history,
    load_tracking_history,
    RecommendationStatus,
    resolve_report_dir,
)

# ---------------------------------------------------------------------------
# _parse_date / _format_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_yyyymmdd(self) -> None:
        assert _parse_date("20260101") == datetime(2026, 1, 1)

    def test_yyyy_mm_dd(self) -> None:
        assert _parse_date("2026-01-01") == datetime(2026, 1, 1)

    def test_invalid(self) -> None:
        with pytest.raises(ValueError):
            _parse_date("bad")

    def test_too_short(self) -> None:
        with pytest.raises(ValueError):
            _parse_date("2026")


class TestFormatDate:
    def test_roundtrip(self) -> None:
        assert _format_date(datetime(2026, 1, 1)) == "20260101"


# ---------------------------------------------------------------------------
# _classify_status
# ---------------------------------------------------------------------------


class TestClassifyStatus:
    def test_first_appearance_0(self) -> None:
        assert _classify_status(0) == RecommendationStatus.FIRST_APPEARANCE

    def test_first_appearance_1(self) -> None:
        assert _classify_status(1) == RecommendationStatus.FIRST_APPEARANCE

    def test_consecutive_2(self) -> None:
        assert _classify_status(2) == RecommendationStatus.CONSECUTIVE_2DAYS

    def test_consecutive_3plus(self) -> None:
        assert _classify_status(3) == RecommendationStatus.CONSECUTIVE_3PLUS
        assert _classify_status(10) == RecommendationStatus.CONSECUTIVE_3PLUS


# ---------------------------------------------------------------------------
# RecommendationStatus
# ---------------------------------------------------------------------------


class TestRecommendationStatus:
    def test_values(self) -> None:
        assert RecommendationStatus.FIRST_APPEARANCE.value == "first_appearance"
        assert RecommendationStatus.CONSECUTIVE_2DAYS.value == "consecutive_2days"
        assert RecommendationStatus.CONSECUTIVE_3PLUS.value == "consecutive_3plus"
        assert RecommendationStatus.BROKEN_STREAK.value == "broken_streak"
        assert RecommendationStatus.REENTRY_SIGNAL.value == "reentry_signal"


# ---------------------------------------------------------------------------
# load_auto_screening_history
# ---------------------------------------------------------------------------


class TestLoadAutoScreeningHistory:
    def test_empty_dir(self, tmp_path) -> None:
        result = load_auto_screening_history(lookback_days=3, report_dir=tmp_path)
        assert result == []

    def test_loads_reports(self, tmp_path) -> None:
        report = {"date": "20260101", "recommendations": [{"ticker": "000001", "score_b": 0.5}]}
        (tmp_path / "auto_screening_20260101.json").write_text(json.dumps(report), encoding="utf-8")
        result = load_auto_screening_history(lookback_days=3, report_dir=tmp_path, end_date="20260101")
        assert len(result) == 1
        assert result[0]["date"] == "20260101"

    def test_sorted_descending(self, tmp_path) -> None:
        for date_str in ["20260101", "20260102", "20260103"]:
            report = {"recommendations": []}
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report), encoding="utf-8")
        result = load_auto_screening_history(lookback_days=5, report_dir=tmp_path, end_date="20260103")
        assert [r["date"] for r in result] == ["20260103", "20260102", "20260101"]

    def test_filters_outside_window(self, tmp_path) -> None:
        for date_str in ["20260101", "20260110"]:
            report = {"recommendations": []}
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report), encoding="utf-8")
        # lookback=3 with end_date=20260103 → window is 20260101-20260103
        result = load_auto_screening_history(lookback_days=3, report_dir=tmp_path, end_date="20260103")
        assert len(result) == 1
        assert result[0]["date"] == "20260101"

    def test_skips_corrupt_files(self, tmp_path) -> None:
        (tmp_path / "auto_screening_20260101.json").write_text("NOT JSON", encoding="utf-8")
        (tmp_path / "auto_screening_20260102.json").write_text(
            json.dumps({"recommendations": []}), encoding="utf-8"
        )
        result = load_auto_screening_history(lookback_days=5, report_dir=tmp_path, end_date="20260102")
        assert len(result) == 1

    def test_invalid_end_date(self, tmp_path) -> None:
        result = load_auto_screening_history(lookback_days=3, report_dir=tmp_path, end_date="bad")
        assert result == []


# ---------------------------------------------------------------------------
# load_tracking_history
# ---------------------------------------------------------------------------


class TestLoadTrackingHistory:
    def test_no_file(self, tmp_path) -> None:
        result = load_tracking_history(tmp_path)
        assert result == []

    def test_corrupt_file(self, tmp_path) -> None:
        (tmp_path / "tracking_history.json").write_text("NOT JSON", encoding="utf-8")
        assert load_tracking_history(tmp_path) == []

    def test_loads_records(self, tmp_path) -> None:
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": [{"ticker": "000001", "return_pct": 5.0}]}), encoding="utf-8"
        )
        result = load_tracking_history(tmp_path)
        assert len(result) == 1
        assert result[0]["ticker"] == "000001"

    def test_loads_list(self, tmp_path) -> None:
        (tmp_path / "tracking_history.json").write_text(
            json.dumps([{"ticker": "000001"}]), encoding="utf-8"
        )
        result = load_tracking_history(tmp_path)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# compute_consecutive_recommendations
# ---------------------------------------------------------------------------


class TestComputeConsecutiveRecommendations:
    def test_no_reports(self, tmp_path) -> None:
        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
        )
        assert result == {}

    def test_first_appearance(self, tmp_path) -> None:
        report = {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}
        (tmp_path / "auto_screening_20260101.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260101",
        )
        assert "000001" in result
        assert result["000001"].consecutive_days == 1
        assert result["000001"].status == RecommendationStatus.FIRST_APPEARANCE

    def test_consecutive_3plus(self, tmp_path) -> None:
        for date_str in ["20260101", "20260102", "20260103"]:
            report = {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260103",
        )
        assert result["000001"].consecutive_days == 3
        assert result["000001"].status == RecommendationStatus.CONSECUTIVE_3PLUS

    def test_consecutive_2days(self, tmp_path) -> None:
        for date_str in ["20260102", "20260103"]:
            report = {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260103",
        )
        assert result["000001"].consecutive_days == 2
        assert result["000001"].status == RecommendationStatus.CONSECUTIVE_2DAYS

    def test_broken_streak(self, tmp_path) -> None:
        """Day1: present (low score), Day2: missing, Day3: present → broken streak (no reentry)."""
        for date_str, score in [("20260101", 0.1), ("20260102", None), ("20260103", 0.1)]:
            recs = [{"ticker": "000001", "score_b": score}] if score is not None else []
            report = {"recommendations": recs}
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260103",
        )
        assert result["000001"].consecutive_days == 1
        assert result["000001"].status == RecommendationStatus.BROKEN_STREAK

    def test_reentry_signal(self, tmp_path) -> None:
        """Broken streak + previous high score → reentry signal."""
        for date_str, score in [("20260101", 0.4), ("20260102", None), ("20260103", 0.3)]:
            recs = [{"ticker": "000001", "score_b": score}] if score is not None else []
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps({"recommendations": recs}), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260103",
        )
        assert result["000001"].status == RecommendationStatus.REENTRY_SIGNAL

    def test_stability_bonus_increases_with_streak(self, tmp_path) -> None:
        # 3 days
        for date_str in ["20260101", "20260102", "20260103"]:
            report = {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260103",
        )
        assert result["000001"].stability_bonus == 10.0

    def test_non_dict_recommendation_skipped(self, tmp_path) -> None:
        report = {"recommendations": ["bad", {"ticker": "000001", "score_b": 0.5}]}
        (tmp_path / "auto_screening_20260101.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260101",
        )
        assert "000001" in result

    def test_none_score_b_handled(self, tmp_path) -> None:
        report = {"recommendations": [{"ticker": "000001", "score_b": None}]}
        (tmp_path / "auto_screening_20260101.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260101",
        )
        # score_b=None gets coerced to 0.0 in recommendation_history
        assert len(result["000001"].recommendation_history) == 1
        assert result["000001"].recommendation_history[0]["score_b"] == 0.0


# ---------------------------------------------------------------------------
# ConsecutiveStats
# ---------------------------------------------------------------------------


class TestConsecutiveStats:
    def test_required_fields(self) -> None:
        stats = ConsecutiveStats(
            ticker="000001",
            consecutive_days=1,
            status=RecommendationStatus.FIRST_APPEARANCE,
        )
        assert stats.consecutive_days == 1
        assert stats.status == RecommendationStatus.FIRST_APPEARANCE
        assert stats.stability_bonus == 0.0
        assert stats.recommendation_history == []


# ---------------------------------------------------------------------------
# resolve_report_dir
# ---------------------------------------------------------------------------


class TestResolveReportDir:
    def test_returns_path(self) -> None:
        result = resolve_report_dir()
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# _latest_report_date
# ---------------------------------------------------------------------------


class TestLatestReportDate:
    """Return the latest auto_screening_*.json report date as datetime."""

    def test_empty_dir_returns_none(self, tmp_path):
        from src.screening.consecutive_recommendation import _latest_report_date

        assert _latest_report_date(tmp_path) is None

    def test_single_file(self, tmp_path):
        from src.screening.consecutive_recommendation import _latest_report_date

        (tmp_path / "auto_screening_20260610.json").write_text("{}")
        result = _latest_report_date(tmp_path)
        assert result == datetime(2026, 6, 10)

    def test_multiple_files_returns_latest(self, tmp_path):
        from src.screening.consecutive_recommendation import _latest_report_date

        (tmp_path / "auto_screening_20260601.json").write_text("{}")
        (tmp_path / "auto_screening_20260620.json").write_text("{}")
        (tmp_path / "auto_screening_20260615.json").write_text("{}")
        assert _latest_report_date(tmp_path) == datetime(2026, 6, 20)

    def test_non_matching_files_ignored(self, tmp_path):
        from src.screening.consecutive_recommendation import _latest_report_date

        (tmp_path / "report_20260610.json").write_text("{}")
        (tmp_path / "auto_screening_20260610.json").write_text("{}")
        assert _latest_report_date(tmp_path) == datetime(2026, 6, 10)

    def test_returns_datetime_type(self, tmp_path):
        from src.screening.consecutive_recommendation import _latest_report_date

        (tmp_path / "auto_screening_20260101.json").write_text("{}")
        result = _latest_report_date(tmp_path)
        assert isinstance(result, datetime)
