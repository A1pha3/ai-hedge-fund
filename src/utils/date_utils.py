"""Shared date formatting utilities."""

from __future__ import annotations

from datetime import datetime


def format_date(date_str: str) -> str:
    """Normalize date to YYYY-MM-DD. Accepts YYYYMMDD or YYYY-MM-DD."""
    date_str = str(date_str).strip()
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


def parse_date(date_str: str) -> datetime:
    """Parse a date string (YYYYMMDD or YYYY-MM-DD) into a datetime object."""
    return datetime.strptime(format_date(date_str), "%Y-%m-%d")


def is_announced_after_as_of(ann_date_str: str | None, as_of_date: str | None) -> bool:
    """Return ``True`` iff an ``ann_date`` was announced strictly after ``as_of``.

    Shared point-in-time (PIT) gate used by both the ``fina_indicator`` metrics
    path (R41) and the balancesheet/cashflow/income ``line_items`` path (R74).
    A ``True`` result means the report is look-ahead for a backtest anchored at
    ``as_of`` and must be excluded.

    Robustness contract (mirrors the C2-BH2 contract of both call sites):
    missing / malformed ``ann_date`` or ``as_of`` returns ``False`` (cannot
    prove look-ahead → live fallback). This avoids over-filtering legitimate
    data on bad rows. Dates may be compact (``YYYYMMDD``) or dashed
    (``YYYY-MM-DD``); both are normalized to compact before the 8-digit
    numeric comparison.
    """
    if not ann_date_str or not as_of_date:
        return False
    ann_compact = str(ann_date_str).replace("-", "")
    as_of_compact = str(as_of_date).replace("-", "")
    if (
        len(ann_compact) == 8
        and len(as_of_compact) == 8
        and ann_compact[:8].isdigit()
        and as_of_compact[:8].isdigit()
    ):
        return ann_compact > as_of_compact
    return False
