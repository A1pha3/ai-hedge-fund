"""Characterization tests for src/utils/date_utils.py.

format_date and parse_date had zero direct test coverage despite being used
across date-handling paths. Tests lock down the YYYYMMDD ↔ YYYY-MM-DD contract.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.utils.date_utils import format_date, parse_date, resolve_signal_date, resolve_signal_date_iso


class TestFormatDate:
    def test_yyyymmdd_normalized(self) -> None:
        assert format_date("20260615") == "2026-06-15"

    def test_yyyy_mm_dd_passthrough(self) -> None:
        assert format_date("2026-06-15") == "2026-06-15"

    def test_whitespace_stripped(self) -> None:
        assert format_date("  20260615  ") == "2026-06-15"

    def test_non_eight_digit_passthrough(self) -> None:
        """7-digit string is not YYYYMMDD → returned unchanged."""
        assert format_date("2026615") == "2026615"

    def test_non_digit_eight_char_passthrough(self) -> None:
        """8 chars but not all digits → returned unchanged."""
        assert format_date("2026-615") == "2026-615"

    def test_slash_format_passthrough(self) -> None:
        """Non-standard format is returned as-is (not converted)."""
        assert format_date("2026/06/15") == "2026/06/15"

    def test_non_string_input_coerced(self) -> None:
        """Non-string input is coerced via str()."""
        assert format_date(20260615) == "2026-06-15"

    def test_invalid_month_preserves_format(self) -> None:
        """format_date does not validate the date — '20261301' still formats."""
        assert format_date("20261301") == "2026-13-01"


class TestParseDate:
    def test_parse_yyyymmdd(self) -> None:
        assert parse_date("20260615") == datetime(2026, 6, 15)

    def test_parse_yyyy_mm_dd(self) -> None:
        assert parse_date("2026-06-15") == datetime(2026, 6, 15)

    def test_parse_strips_whitespace(self) -> None:
        assert parse_date("  20260615  ") == datetime(2026, 6, 15)

    def test_parse_invalid_date_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_date("20261301")

    def test_parse_non_date_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_date("not-a-date")


class TestResolveSignalDate:
    """17:00 data-ready rule: before cutoff → previous day, at/after → today.

    A-share fund-flow ingestion finishes ~17:00; before that same-day data is
    empty, so the default signal date rolls back one calendar day.
    """

    def test_before_cutoff_returns_previous_day(self) -> None:
        assert resolve_signal_date(now=datetime(2026, 7, 9, 10, 30)) == "20260708"

    def test_midnight_returns_previous_day(self) -> None:
        assert resolve_signal_date(now=datetime(2026, 7, 9, 0, 1)) == "20260708"

    def test_exactly_cutoff_returns_today(self) -> None:
        """At the cutoff hour (>=), same-day data is considered ready."""
        assert resolve_signal_date(now=datetime(2026, 7, 9, 17, 0)) == "20260709"

    def test_after_cutoff_returns_today(self) -> None:
        assert resolve_signal_date(now=datetime(2026, 7, 9, 23, 59)) == "20260709"

    def test_monday_morning_returns_sunday(self) -> None:
        """Monday before cutoff → Sunday (natural-day rollback; no weekend skip)."""
        # 2026-07-13 is a Monday
        assert resolve_signal_date(now=datetime(2026, 7, 13, 8, 0)) == "20260712"

    def test_explicit_ready_hour_overrides_default(self) -> None:
        """ready_hour arg takes precedence over the default 17."""
        # 18:00 is after default 17 but before explicit 20 → previous day
        assert resolve_signal_date(now=datetime(2026, 7, 9, 18, 0), ready_hour=20) == "20260708"

    def test_env_override_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATA_READY_HOUR", "20")
        assert resolve_signal_date(now=datetime(2026, 7, 9, 18, 0)) == "20260708"

    def test_invalid_env_falls_back_to_17(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATA_READY_HOUR", "not_a_number")
        assert resolve_signal_date(now=datetime(2026, 7, 9, 16, 0)) == "20260708"

    def test_explicit_ready_hour_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit arg wins over env var."""
        monkeypatch.setenv("DATA_READY_HOUR", "20")
        assert resolve_signal_date(now=datetime(2026, 7, 9, 18, 0), ready_hour=17) == "20260709"


class TestResolveSignalDateIso:
    """Same rule, dashed YYYY-MM-DD output."""

    def test_before_cutoff_returns_previous_day(self) -> None:
        assert resolve_signal_date_iso(now=datetime(2026, 7, 9, 10, 30)) == "2026-07-08"

    def test_after_cutoff_returns_today(self) -> None:
        assert resolve_signal_date_iso(now=datetime(2026, 7, 9, 17, 0)) == "2026-07-09"
