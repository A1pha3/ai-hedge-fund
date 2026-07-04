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
        (tmp_path / "auto_screening_20260102.json").write_text(json.dumps({"recommendations": []}), encoding="utf-8")
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
        (tmp_path / "tracking_history.json").write_text(json.dumps({"records": [{"ticker": "000001", "return_pct": 5.0}]}), encoding="utf-8")
        result = load_tracking_history(tmp_path)
        assert len(result) == 1
        assert result[0]["ticker"] == "000001"

    def test_loads_list(self, tmp_path) -> None:
        (tmp_path / "tracking_history.json").write_text(json.dumps([{"ticker": "000001"}]), encoding="utf-8")
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

    def test_streak_survives_weekend_gap(self, tmp_path) -> None:
        """BH-005: a Fri→Mon consecutive recommendation must count as a streak.

        Previously streak continuity stepped back one *calendar* day, so the
        cursor landed on Saturday/Sunday and broke on every post-weekend
        report — silently zeroing the R4 consecutive-recommendation bonus on
        the most common (Mon/Tue) case. With trading-day stepping, Fri+Mon is
        a 2-day streak.
        """
        # 20260102 = Friday, 20260105 = Monday (weekend in between).
        for date_str in ["20260102", "20260105"]:
            report = {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=7,
            report_dir=tmp_path,
            end_date="20260105",
        )
        assert result["000001"].consecutive_days == 2
        assert result["000001"].status == RecommendationStatus.CONSECUTIVE_2DAYS

    def test_long_holiday_does_not_create_phantom_streak(self, tmp_path, monkeypatch) -> None:
        """R45: Spring Festival gap must NOT inflate streak via weekday approximation.

        2024-02-08 (Thu) was the last trading day before Spring Festival;
        2024-02-19 (Mon) was the first trading day after the holiday — 7
        trading days apart on the real calendar. The previous weekday
        approximation walked back just one weekday from 2024-02-19 (→ Fri
        2024-02-16, a holiday closure day), wrongly treating Thu+Mon as a
        2-day consecutive streak and adding R4 stability bonus on every
        post-CNY first-trading-day report. With trade_cal stepping the prior
        trading day before 2024-02-19 is 2024-02-08, but the recommendation
        on Mon and Thu are NOT adjacent (Thu→Mon is one trading-day step
        across the holiday), so streak must equal 2 ONLY when consecutive
        trading days are truly recommended. Here the test models an actual
        holiday gap with no intervening trading days — streak = 2 is correct
        (Thu+Mon are adjacent trading days on the real A-share calendar).
        The phantom-streak failure mode is a different scenario (recommended
        on Mon and prior Wed but NOT Thu): weekday approx counts Mon→Tue→Wed
        backwards across only 2 weekdays, so it would step Mon→Fri→Thu and
        find Wed three weekdays back as consecutive when in fact 1
        intervening trading day (Thu) without recommendation breaks the
        streak. Models that scenario:
        Wed 2024-02-07 + Thu 2024-02-08 + skip CNY + Mon 2024-02-19 — Mon's
        only consecutive predecessor is 2024-02-08 (Thu, real prev trading
        day on A-share calendar). With weekday approx the cursor lands on
        Fri 2024-02-16 (a holiday closure day), and since neither Wed nor
        Thu reports match Fri, the bug actually breaks streak too early
        without trade_cal — but Thu's report DOES match the real prev
        trading day before Mon. So this test validates that the real
        calendar correctly continues Thu→Mon=2 and Wed→Thu→Mon=3.
        """
        # Inject a mock trade_cal that returns the real A-share open dates
        # spanning Spring Festival 2024 (Feb 8 Thu, Feb 19 Mon, Feb 20 Tue).
        cny_open_dates = [
            "20240207",  # Wed
            "20240208",  # Thu (last day before CNY)
            # 20240209-20240218 — Spring Festival closure
            "20240219",  # Mon (first day after CNY)
            "20240220",  # Tue
            "20240221",  # Wed
        ]

        def mock_get_open(start: str, end: str) -> list[str]:
            return [d for d in cny_open_dates if start <= d <= end]

        monkeypatch.setattr(
            "src.tools.tushare_api.get_open_trade_dates",
            mock_get_open,
        )
        for date_str in ["20240207", "20240208", "20240219", "20240220"]:
            report = {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report), encoding="utf-8")

        result = compute_consecutive_recommendations(
            lookback_days=15,
            report_dir=tmp_path,
            end_date="20240220",
        )
        # Tue 20240220 + Mon 20240219 + Thu 20240208 + Wed 20240207
        # = 4 consecutive trading-day reports across the CNY gap.
        # With weekday-only approx: from 20240220 step back lands on
        # Fri 20240216 (holiday closure, no report) → streak breaks at 2.
        # With real trade_cal step: 20240220→20240219→20240208→20240207
        # → all reports present → streak = 4.
        assert result["000001"].consecutive_days == 4

    def test_streak_falls_back_to_weekday_when_trade_cal_unavailable(self, tmp_path, monkeypatch) -> None:
        """R45 fallback: if get_open_trade_dates fails/empty, retain weekday approx.

        Backward-compatible fallback: pre-R45 behavior must remain when no
        token / network failure. Fri→Mon must still count as 2-day streak.
        """

        def mock_empty(start: str, end: str) -> list[str]:
            return []  # simulates no token / API failure

        monkeypatch.setattr(
            "src.tools.tushare_api.get_open_trade_dates",
            mock_empty,
        )
        # 20260102 = Friday, 20260105 = Monday (weekend in between).
        for date_str in ["20260102", "20260105"]:
            report = {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=7,
            report_dir=tmp_path,
            end_date="20260105",
        )
        # Fallback to weekday: Fri+Mon = 2-day streak (R36 behavior preserved).
        assert result["000001"].consecutive_days == 2

    def test_streak_survives_holiday_adjacent_weekend(self, tmp_path) -> None:
        """BH-005 drain: Fri→(weekend)→Mon→Tue 3-day trading streak stays 3."""
        # 20260102 Fri, 20260105 Mon, 20260106 Tue.
        for date_str in ["20260102", "20260105", "20260106"]:
            report = {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=10,
            report_dir=tmp_path,
            end_date="20260106",
        )
        assert result["000001"].consecutive_days == 3
        assert result["000001"].status == RecommendationStatus.CONSECUTIVE_3PLUS

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

    def test_broken_streak_low_historical_score_not_reentry(self, tmp_path) -> None:
        """BH-016 ported: score_b<0.3 throughout → BROKEN_STREAK, not REENTRY.

        20260101 (Thu) score=0.2, 20260102 (Fri) absent, 20260105 (Mon)
        score=0.2 — too low to qualify for re-entry signal threshold.
        """
        (tmp_path / "auto_screening_20260101.json").write_text(json.dumps({"recommendations": [{"ticker": "000001", "score_b": 0.2}]}), encoding="utf-8")
        (tmp_path / "auto_screening_20260102.json").write_text(json.dumps({"recommendations": [{"ticker": "000002", "score_b": 0.3}]}), encoding="utf-8")
        (tmp_path / "auto_screening_20260105.json").write_text(json.dumps({"recommendations": [{"ticker": "000001", "score_b": 0.2}]}), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=5,
            report_dir=tmp_path,
            end_date="20260105",
        )
        assert result["000001"].status == RecommendationStatus.BROKEN_STREAK
        assert result["000001"].stability_bonus == 0.0

    def test_consecutive_not_misclassified_as_reentry(self, tmp_path) -> None:
        """BH-016 ported: continuous Thu-Fri-Mon stays CONSECUTIVE_3PLUS, not REENTRY."""
        for date_str in ["20260101", "20260102", "20260105"]:
            (tmp_path / f"auto_screening_{date_str}.json").write_text(json.dumps({"recommendations": [{"ticker": "000001", "score_b": 0.5}]}), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=5,
            report_dir=tmp_path,
            end_date="20260105",
        )
        assert result["000001"].status == RecommendationStatus.CONSECUTIVE_3PLUS
        assert result["000001"].stability_bonus == 10.0

    def test_first_appearance_does_not_trigger_reentry(self, tmp_path) -> None:
        """BH-016 ported: only 1 appearance in window → FIRST_APPEARANCE."""
        (tmp_path / "auto_screening_20260105.json").write_text(json.dumps({"recommendations": [{"ticker": "000001", "score_b": 0.5}]}), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260105",
        )
        assert result["000001"].status == RecommendationStatus.FIRST_APPEARANCE

    def test_reentry_bonus_strictly_between_first_and_consecutive(self, tmp_path) -> None:
        """BH-016 ported: REENTRY bonus must be 0 < bonus < 10 (between
        FIRST_APPEARANCE and CONSECUTIVE_3PLUS)."""
        (tmp_path / "auto_screening_20260101.json").write_text(json.dumps({"recommendations": [{"ticker": "000001", "score_b": 0.5}]}), encoding="utf-8")
        (tmp_path / "auto_screening_20260102.json").write_text(json.dumps({"recommendations": [{"ticker": "000002", "score_b": 0.3}]}), encoding="utf-8")
        (tmp_path / "auto_screening_20260105.json").write_text(json.dumps({"recommendations": [{"ticker": "000001", "score_b": 0.4}]}), encoding="utf-8")
        result = compute_consecutive_recommendations(
            lookback_days=5,
            report_dir=tmp_path,
            end_date="20260105",
        )
        bonus = result["000001"].stability_bonus
        assert 0.0 < bonus < 10.0

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
