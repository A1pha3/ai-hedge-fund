"""Shared date formatting utilities."""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta


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


def latest_open_trade_date_on_or_before(date_str: str, *, lookback_days: int = 14) -> str:
    """Return the latest open A-share trading day on or before ``date_str``.

    Prefer ``trade_cal`` when available; when it is unavailable or returns no
    data, fall back to a weekday-only rollback so weekend invocations still map
    to Friday. This fallback cannot detect exchange holidays, but it avoids the
    most harmful false positives in non-trading-time automation.
    """

    compact = str(date_str or "").strip().replace("-", "")
    if len(compact) != 8 or not compact.isdigit():
        return compact

    try:
        requested = datetime.strptime(compact, "%Y%m%d")
    except ValueError:
        return compact

    try:
        from src.tools.tushare_api import get_open_trade_dates

        start_date = (requested - timedelta(days=max(lookback_days - 1, 0))).strftime("%Y%m%d")
        open_dates = get_open_trade_dates(start_date, compact)
        if open_dates:
            return open_dates[-1]
    except Exception:
        pass

    while requested.weekday() >= 5:
        requested -= timedelta(days=1)
    return requested.strftime("%Y%m%d")


def resolve_market_ready_date(*, now: datetime | None = None, ready_hour: int | None = None) -> str:
    """Return the effective trading date under the data-ready cutoff rule.

    Before the cutoff, step back one calendar day first, then normalize to the
    latest open trading day on or before that date. At/after the cutoff, use the
    current day and normalize the same way.
    """

    now = now if now is not None else datetime.now()
    cutoff = _resolve_ready_hour(ready_hour)
    base = now - timedelta(days=1) if now.hour < cutoff else now
    return latest_open_trade_date_on_or_before(base.strftime("%Y%m%d"))


def resolve_market_ready_date_iso(*, now: datetime | None = None, ready_hour: int | None = None) -> str:
    """Same rule as :func:`resolve_market_ready_date` but returns ``YYYY-MM-DD``."""

    compact = resolve_market_ready_date(now=now, ready_hour=ready_hour)
    return format_date(compact)


def resolve_signal_date(*, now: datetime | None = None, ready_hour: int | None = None) -> str:
    """Return the default signal date under the data-ready time-of-day rule.

    A-share fund-flow data (tushare moneyflow / akshare push2his) typically
    finishes ingestion ~2 hours after close (~17:00). Querying same-day data
    before the cutoff returns empty rows, which used to silently break
    screening (cache_refresh "双源均失败", stale-signal guards). When no
    explicit date is provided, before ``ready_hour`` rolls back one calendar
    day so callers never operate on incomplete data; at/after the cutoff the
    current day is used.

    Non-trading days are normalized to the latest open A-share trading day on
    or before the cutoff-adjusted wall-clock date, so Sunday / Monday-morning
    automation resolves to Friday rather than emitting weekend pseudo-dates.

    The cutoff is overridable via the ``DATA_READY_HOUR`` env var (default 17);
    an explicit ``ready_hour`` argument takes precedence over the env var.

    Args:
        now: Reference wall-clock (defaults to ``datetime.now()``; injectable
            for tests so callers avoid patching the ``datetime`` module).
        ready_hour: Explicit cutoff hour (0-23). ``None`` → read env var.

    Returns:
        Signal date in compact ``YYYYMMDD`` form.
    """
    return resolve_market_ready_date(now=now, ready_hour=ready_hour)


def resolve_signal_date_iso(*, now: datetime | None = None, ready_hour: int | None = None) -> str:
    """Same rule as :func:`resolve_signal_date` but returns ``YYYY-MM-DD``.

    Convenience for callers (e.g. ``--end-date`` CLI values) that use the
    dashed ISO form, avoiding a redundant ``format_date`` round-trip.
    """
    return resolve_market_ready_date_iso(now=now, ready_hour=ready_hour)


# ---------------------------------------------------------------------------
# Unified 17:00 signal-session policy (ashare-cn-1700-v1)
# ---------------------------------------------------------------------------
#
# Three call sites (``_resolve_default_end_date`` in ``src/cli/input.py``,
# the ``--auto`` factor-scoring path, and ``daily_action``'s signal
# resolution) each re-implemented the 17:00 cutoff independently. The
# constants + function below are the single source of truth for that rule.
# A caller passes in the authoritative set of open A-share sessions and an
# optional override; the function returns the canonical signal date.
# Production Auto and Daily Action call sites both route through this resolver.

SIGNAL_SESSION_POLICY_VERSION = "ashare-cn-1700-v1"
_SIGNAL_READY_CUTOFF = time(17, 0)


class SignalSessionUnavailable(ValueError):
    """Raised when no authoritative signal session can be resolved."""


def resolve_signal_session(
    *,
    now_cn: datetime,
    open_sessions: Sequence[date],
    override: str | date | None = None,
    ready_cutoff: time = _SIGNAL_READY_CUTOFF,
) -> date:
    """Return the canonical signal date under the data-ready session policy.

    The rule is the single source of truth for the data-ready cutoff: at or
    after ``ready_cutoff`` (default 17:00 Asia/Shanghai), same-day data is
    treated as ready; before the cutoff the previous day is used. Weekday vs.
    weekend is handled by the same rule because callers must pass an
    authoritative open-session calendar, which is the only thing that can
    correctly skip exchange holidays.

    Args:
        now_cn: Reference wall-clock in Asia/Shanghai.
        open_sessions: Authoritative set of open A-share trading sessions.
            Duplicates and ordering are tolerated (the function sorts and
            dedupes). An empty sequence is a hard error — without an
            explicit calendar, a silent fallback would mask data issues.
        override: Optional explicit session. May be a :class:`date` or a
            ``YYYYMMDD``/``YYYY-MM-DD`` string. Must be a member of
            ``open_sessions``; otherwise a :class:`SignalSessionUnavailable`
            is raised.
        ready_cutoff: Injectable policy seam for direct resolver tests. Both
            production command paths omit it and therefore use the fixed,
            versioned 17:00 cutoff.

    Returns:
        The resolved signal date (a :class:`date`).

    Raises:
        SignalSessionUnavailable: ``open_sessions`` is empty, ``override``
            is not a member of ``open_sessions``, or no session exists at or
            before the cutoff-adjusted date.
    """
    sessions = tuple(sorted(set(open_sessions)))
    if not sessions:
        raise SignalSessionUnavailable("authoritative open sessions unavailable")
    cutoff_date = (
        now_cn.date() if now_cn.time() >= ready_cutoff else now_cn.date() - timedelta(days=1)
    )
    if override is not None:
        selected = (
            override
            if isinstance(override, date) and not isinstance(override, datetime)
            else datetime.strptime(str(override).replace("-", ""), "%Y%m%d").date()
        )
        if selected not in sessions:
            raise SignalSessionUnavailable("override is not an authoritative open session")
        # 未来日护栏 (2026-07-18): override 不得晚于 17:00 规则解析出的自然信号日.
        # 未来日的 lifecycle 会把排队计划按"窗口已过"永久 skip 并写入未来日期估值,
        # 一次手滑即可损毁台账状态.
        eligible = tuple(session for session in sessions if session <= cutoff_date)
        if eligible and selected > eligible[-1]:
            raise SignalSessionUnavailable(
                f"override {selected.isoformat()} is after the natural signal session "
                f"{eligible[-1].isoformat()}"
            )
        return selected
    eligible = tuple(session for session in sessions if session <= cutoff_date)
    if not eligible:
        raise SignalSessionUnavailable("calendar has no session at or before cutoff")
    return eligible[-1]
