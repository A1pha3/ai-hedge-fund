"""Shared date formatting utilities."""

from __future__ import annotations

import os
from datetime import datetime, timedelta


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
    if len(ann_compact) == 8 and len(as_of_compact) == 8 and ann_compact[:8].isdigit() and as_of_compact[:8].isdigit():
        return ann_compact > as_of_compact
    return False


_DEFAULT_READY_HOUR = 17


def _resolve_ready_hour(ready_hour: int | None) -> int:
    """Resolve the data-ready cutoff hour.

    A non-None ``ready_hour`` wins (explicit caller override). Otherwise fall
    back to the ``DATA_READY_HOUR`` env var; an unparseable value reverts to
    the default (17) so a misconfigured env never breaks date resolution.
    """
    if ready_hour is not None:
        return ready_hour
    try:
        return int(os.environ.get("DATA_READY_HOUR", str(_DEFAULT_READY_HOUR)))
    except ValueError:
        return _DEFAULT_READY_HOUR


def resolve_signal_date(*, now: datetime | None = None, ready_hour: int | None = None) -> str:
    """Return the default signal date under the data-ready time-of-day rule.

    A-share fund-flow data (tushare moneyflow / akshare push2his) typically
    finishes ingestion ~2 hours after close (~17:00). Querying same-day data
    before the cutoff returns empty rows, which used to silently break
    screening (cache_refresh "双源均失败", stale-signal guards). When no
    explicit date is provided, before ``ready_hour`` rolls back one calendar
    day so callers never operate on incomplete data; at/after the cutoff the
    current day is used.

    Non-trading days (weekends/holidays) are NOT skipped here — downstream
    ``build_candidate_pool`` / data queries naturally land on the nearest
    trading day, so a one-day natural rollback is harmless.

    The cutoff is overridable via the ``DATA_READY_HOUR`` env var (default 17);
    an explicit ``ready_hour`` argument takes precedence over the env var.

    Args:
        now: Reference wall-clock (defaults to ``datetime.now()``; injectable
            for tests so callers avoid patching the ``datetime`` module).
        ready_hour: Explicit cutoff hour (0-23). ``None`` → read env var.

    Returns:
        Signal date in compact ``YYYYMMDD`` form.
    """
    now = now if now is not None else datetime.now()
    cutoff = _resolve_ready_hour(ready_hour)
    base = now - timedelta(days=1) if now.hour < cutoff else now
    return base.strftime("%Y%m%d")


def resolve_signal_date_iso(*, now: datetime | None = None, ready_hour: int | None = None) -> str:
    """Same rule as :func:`resolve_signal_date` but returns ``YYYY-MM-DD``.

    Convenience for callers (e.g. ``--end-date`` CLI values) that use the
    dashed ISO form, avoiding a redundant ``format_date`` round-trip.
    """
    now = now if now is not None else datetime.now()
    cutoff = _resolve_ready_hour(ready_hour)
    base = now - timedelta(days=1) if now.hour < cutoff else now
    return base.strftime("%Y-%m-%d")
