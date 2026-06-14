"""Characterization tests for src/utils/date_utils.py.

format_date and parse_date had zero direct test coverage despite being used
across date-handling paths. Tests lock down the YYYYMMDD ↔ YYYY-MM-DD contract.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.utils.date_utils import format_date, parse_date


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
