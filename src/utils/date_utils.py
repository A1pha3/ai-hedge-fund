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
