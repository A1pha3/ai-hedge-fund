"""Tests for daily_delta.py — P6-2 推荐日间变动摘要."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.daily_delta import (
    _empty_delta,
    _extract_top_n,
    _find_adjacent_reports,
    _format_delta_entry,
    _load_sorted_reports,
    compute_daily_delta,
    render_daily_delta,
)
from src.utils.date_utils import format_date


def _make_report(date_str: str, recs: list[dict]) -> dict:
    """Helper: build a report dict with recommendations."""
    return {
        "trade_date": date_str,
        "recommendations": recs,
    }


def _make_rec(ticker: str, name: str, score_b: float) -> dict:
    return {"ticker": ticker, "name": name, "score_b": score_b}


class TestComputeDailyDelta:
    def test_empty_dir_returns_error(self, tmp_path: Path) -> None:
        result = compute_daily_delta(reports_dir=tmp_path / "nonexistent")
        assert result.get("error") is not None

    def test_single_report_returns_error(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        report = _make_report("20260610", [_make_rec("000001", "Test", 0.6)])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_daily_delta(reports_dir=reports_dir)
        assert result.get("error") is not None

    def test_two_reports_shows_added_and_removed(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [
            _make_rec("000001", "StockA", 0.7),
            _make_rec("000002", "StockB", 0.5),
        ])
        today = _make_report("20260611", [
            _make_rec("000001", "StockA", 0.75),
            _make_rec("000003", "StockC", 0.8),
        ])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir, top_n=20)
        assert result["today_date"] == "2026-06-11"
        assert result["yesterday_date"] == "2026-06-10"
        assert result["added_count"] == 1
        assert result["removed_count"] == 1
        assert result["added"][0]["ticker"] == "000003"
        assert result["removed"][0]["ticker"] == "000002"

    def test_score_change_detected(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [_make_rec("000001", "StockA", 0.5)])
        today = _make_report("20260611", [_make_rec("000001", "StockA", 0.8)])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir)
        assert result["changed_count"] == 1
        assert result["changed"][0]["score_b_delta"] == pytest.approx(0.3, abs=0.001)
        assert result["changed"][0]["rank_change"] == 0  # same rank in both

    def test_unchanged_when_scores_match(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        rec = _make_rec("000001", "StockA", 0.6)
        yesterday = _make_report("20260610", [rec])
        today = _make_report("20260611", [_make_rec("000001", "StockA", 0.6)])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir)
        assert result["changed_count"] == 0
        assert result["unchanged_count"] == 1
        assert result["added_count"] == 0
        assert result["removed_count"] == 0

    def test_top_n_limits_comparison(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday_recs = [_make_rec(f"00{i:04d}", f"S{i}", 0.9 - i * 0.05) for i in range(20)]
        today_recs = [_make_rec(f"00{i:04d}", f"S{i}", 0.9 - i * 0.05 + 0.01) for i in range(20)]
        yesterday = _make_report("20260610", yesterday_recs)
        today = _make_report("20260611", today_recs)
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir, top_n=5)
        assert result["today_total"] == 5
        assert result["yesterday_total"] == 5

    def test_rank_change_tracked(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [
            _make_rec("000001", "A", 0.9),
            _make_rec("000002", "B", 0.8),
            _make_rec("000003", "C", 0.7),
        ])
        today = _make_report("20260611", [
            _make_rec("000003", "C", 0.95),
            _make_rec("000001", "A", 0.85),
            _make_rec("000002", "B", 0.75),
        ])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir)
        changed_map = {c["ticker"]: c for c in result["changed"]}
        # C moved from rank 3 to rank 1 → rank_change = +2
        assert changed_map["000003"]["rank_change"] == 2
        # A moved from rank 1 to rank 2 → rank_change = -1
        assert changed_map["000001"]["rank_change"] == -1

    def test_invalid_json_skipped(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "auto_screening_20260609.json").write_text("not json", encoding="utf-8")
        yesterday = _make_report("20260610", [_make_rec("000001", "A", 0.5)])
        today = _make_report("20260611", [_make_rec("000001", "A", 0.6)])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir)
        assert result["today_date"] == "2026-06-11"
        assert result["changed_count"] == 1


class TestRenderDailyDelta:
    def test_error_renders_as_warning(self) -> None:
        delta = {"error": "No reports found", "today_date": "", "yesterday_date": ""}
        output = render_daily_delta(delta)
        assert "⚠" in output
        assert "No reports found" in output

    def test_added_renders(self) -> None:
        delta = {
            "today_date": "2026-06-11",
            "yesterday_date": "2026-06-10",
            "added_count": 1,
            "removed_count": 0,
            "changed_count": 0,
            "unchanged_count": 0,
            "added": [{"ticker": "000001", "name": "TestStock", "score_b": 0.8, "rank": 1}],
            "removed": [],
            "changed": [],
        }
        output = render_daily_delta(delta)
        assert "新增" in output
        assert "TestStock" in output

    def test_removed_renders(self) -> None:
        delta = {
            "today_date": "2026-06-11",
            "yesterday_date": "2026-06-10",
            "added_count": 0,
            "removed_count": 1,
            "changed_count": 0,
            "unchanged_count": 0,
            "added": [],
            "removed": [{"ticker": "000002", "name": "OldStock", "score_b": 0.3, "rank": 5}],
            "changed": [],
        }
        output = render_daily_delta(delta)
        assert "移除" in output
        assert "OldStock" in output

    def test_changed_renders_with_arrows(self) -> None:
        delta = {
            "today_date": "2026-06-11",
            "yesterday_date": "2026-06-10",
            "added_count": 0,
            "removed_count": 0,
            "changed_count": 1,
            "unchanged_count": 0,
            "added": [],
            "removed": [],
            "changed": [{"ticker": "000001", "name": "StockA", "score_b_delta": 0.15, "rank_change": 2}],
        }
        output = render_daily_delta(delta)
        assert "StockA" in output
        assert "↑" in output


class TestEdgeCases:
    def test_none_score_b_no_delta(self) -> None:
        """When yesterday's score_b is None, no delta should be computed."""
        from src.screening.daily_delta import _compute_field_deltas
        result = _compute_field_deltas(
            {"ticker": "000001", "name": "A", "score_b": 0.5},
            {"ticker": "000001", "name": "A", "score_b": None},
        )
        assert result == {}

    def test_both_none_score_b_no_delta(self) -> None:
        """When both score_b are None, no delta should be computed."""
        from src.screening.daily_delta import _compute_field_deltas
        result = _compute_field_deltas(
            {"ticker": "000001", "name": "A", "score_b": None},
            {"ticker": "000001", "name": "A", "score_b": None},
        )
        assert result == {}


class TestFormatDate:
    """Regression guard for date formatting (now delegated to date_utils.format_date).

    Kept here because daily_delta consumes this contract; the assertions lock
    the YYYYMMDD -> YYYY-MM-DD behavior that callers depend on.
    """

    def test_compact_8_digits_to_iso(self) -> None:
        assert format_date("20260610") == "2026-06-10"

    def test_leading_zeros_preserved(self) -> None:
        assert format_date("20260105") == "2026-01-05"

    def test_non_digit_8_chars_returned_unchanged(self) -> None:
        assert format_date("abcdefgh") == "abcdefgh"

    def test_short_string_returned_unchanged(self) -> None:
        assert format_date("2026061") == "2026061"

    def test_long_string_returned_unchanged(self) -> None:
        assert format_date("202606100") == "202606100"

    def test_empty_string_returned_unchanged(self) -> None:
        assert format_date("") == ""


class TestFormatDeltaEntry:
    """Direct unit tests for _format_delta_entry (was 0 direct coverage)."""

    def test_normal_record(self) -> None:
        rec = {"ticker": "000001", "name": "StockA", "score_b": 0.7}
        result = _format_delta_entry(rec, rank=3)
        assert result == {"ticker": "000001", "name": "StockA", "score_b": 0.7, "rank": 3}

    def test_rank_defaults_to_zero(self) -> None:
        result = _format_delta_entry({"ticker": "T", "name": "N", "score_b": 0.5})
        assert result["rank"] == 0

    def test_missing_ticker_defaults_to_empty(self) -> None:
        result = _format_delta_entry({"name": "N", "score_b": 0.5}, rank=1)
        assert result["ticker"] == ""

    def test_missing_name_defaults_to_empty(self) -> None:
        result = _format_delta_entry({"ticker": "T", "score_b": 0.5}, rank=1)
        assert result["name"] == ""

    def test_missing_score_b_defaults_to_zero(self) -> None:
        result = _format_delta_entry({"ticker": "T", "name": "N"}, rank=1)
        assert result["score_b"] == 0.0

    def test_none_score_b_defaults_to_zero(self) -> None:
        result = _format_delta_entry({"ticker": "T", "name": "N", "score_b": None}, rank=1)
        assert result["score_b"] == 0.0

    def test_score_b_rounded_to_4_decimals(self) -> None:
        result = _format_delta_entry({"ticker": "T", "name": "N", "score_b": 0.123456}, rank=1)
        assert result["score_b"] == 0.1235

    def test_ticker_coerced_to_str(self) -> None:
        result = _format_delta_entry({"ticker": 12345, "name": "N", "score_b": 0.5}, rank=1)
        assert result["ticker"] == "12345"


class TestEmptyDelta:
    """Direct unit tests for _empty_delta (was 0 direct coverage)."""

    def test_error_message_propagated(self) -> None:
        result = _empty_delta("something went wrong")
        assert result["error"] == "something went wrong"

    def test_all_counts_zero(self) -> None:
        result = _empty_delta("err")
        assert result["added_count"] == 0
        assert result["removed_count"] == 0
        assert result["changed_count"] == 0
        assert result["unchanged_count"] == 0

    def test_lists_empty_and_dates_blank(self) -> None:
        result = _empty_delta("err")
        assert result["added"] == []
        assert result["removed"] == []
        assert result["changed"] == []
        assert result["today_date"] == ""
        assert result["yesterday_date"] == ""
        assert result["today_total"] == 0
        assert result["yesterday_total"] == 0


class TestExtractTopN:
    """Direct unit tests for _extract_top_n (was 0 direct coverage)."""

    def test_returns_first_n(self) -> None:
        recs = [{"ticker": str(i)} for i in range(10)]
        result = _extract_top_n({"recommendations": recs}, 3)
        assert len(result) == 3
        assert result[0]["ticker"] == "0"

    def test_top_n_larger_than_list_returns_all(self) -> None:
        recs = [{"ticker": "a"}, {"ticker": "b"}]
        result = _extract_top_n({"recommendations": recs}, 100)
        assert len(result) == 2

    def test_missing_recommendations_key_returns_empty(self) -> None:
        result = _extract_top_n({}, 5)
        assert result == []

    def test_none_recommendations_returns_empty(self) -> None:
        result = _extract_top_n({"recommendations": None}, 5)
        assert result == []

    def test_top_n_zero_returns_empty(self) -> None:
        recs = [{"ticker": "a"}, {"ticker": "b"}]
        result = _extract_top_n({"recommendations": recs}, 0)
        assert result == []


class TestLoadSortedReports:
    """Direct unit tests for _load_sorted_reports (was 0 direct coverage)."""

    def test_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        result = _load_sorted_reports(tmp_path / "missing")
        assert result == []

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        assert _load_sorted_reports(reports_dir) == []

    def test_loads_and_sorts_newest_first(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        older = _make_report("20260609", [_make_rec("000001", "A", 0.5)])
        newer = _make_report("20260611", [_make_rec("000002", "B", 0.6)])
        (reports_dir / "auto_screening_20260609.json").write_text(json.dumps(older), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(newer), encoding="utf-8")

        result = _load_sorted_reports(reports_dir)
        assert len(result) == 2
        assert result[0]["date"] == "2026-06-11"
        assert result[1]["date"] == "2026-06-09"

    def test_date_formatted_to_iso(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        report = _make_report("20260610", [_make_rec("000001", "A", 0.5)])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(report), encoding="utf-8")

        result = _load_sorted_reports(reports_dir)
        assert result[0]["date"] == "2026-06-10"

    def test_invalid_json_skipped(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "auto_screening_20260610.json").write_text("not json", encoding="utf-8")
        valid = _make_report("20260611", [_make_rec("000001", "A", 0.5)])
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(valid), encoding="utf-8")

        result = _load_sorted_reports(reports_dir)
        assert len(result) == 1
        assert result[0]["date"] == "2026-06-11"

    def test_non_matching_glob_ignored(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        other = _make_report("20260610", [_make_rec("000001", "A", 0.5)])
        (reports_dir / "other_file.json").write_text(json.dumps(other), encoding="utf-8")

        result = _load_sorted_reports(reports_dir)
        assert result == []


class TestFindAdjacentReports:
    """Direct unit tests for _find_adjacent_reports (was 0 direct coverage)."""

    def test_fewer_than_two_returns_none_pair(self) -> None:
        assert _find_adjacent_reports([], 5) == (None, None)
        single = [{"date": "2026-06-10", "data": {}}]
        assert _find_adjacent_reports(single, 5) == (None, None)

    def test_returns_today_and_first_different(self) -> None:
        reports = [
            {"date": "2026-06-11", "data": {}},
            {"date": "2026-06-10", "data": {}},
            {"date": "2026-06-09", "data": {}},
        ]
        today, yesterday = _find_adjacent_reports(reports, 5)
        assert today["date"] == "2026-06-11"
        assert yesterday["date"] == "2026-06-10"

    def test_all_same_date_returns_today_and_none(self) -> None:
        reports = [
            {"date": "2026-06-11", "data": {}},
            {"date": "2026-06-11", "data": {}},
        ]
        today, yesterday = _find_adjacent_reports(reports, 5)
        assert today["date"] == "2026-06-11"
        assert yesterday is None

    def test_skips_duplicate_dates_to_find_adjacent(self) -> None:
        reports = [
            {"date": "2026-06-11", "data": {}},
            {"date": "2026-06-11", "data": {}},
            {"date": "2026-06-10", "data": {}},
        ]
        today, yesterday = _find_adjacent_reports(reports, 5)
        assert today["date"] == "2026-06-11"
        assert yesterday["date"] == "2026-06-10"
