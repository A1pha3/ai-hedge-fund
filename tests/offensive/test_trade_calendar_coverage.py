"""Forward trading-calendar coverage for --daily-action.

``regime_history.json`` is a historical regime record: it can never contain
future open sessions, so the daily-action service could not compute the next-day
entry or the T+10 BTST horizon (``calendar_unavailable``) and never produced a
plan. These tests pin the forward-inclusive ``trade_calendar.json`` contract.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import src.screening.offensive.daily_action as da


def test_authoritative_sessions_prefer_forward_trade_calendar(tmp_path, monkeypatch):
    """When present, the forward trade calendar (incl. future sessions) wins."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAILY_ACTION_CALENDAR_PATH", raising=False)
    reports = tmp_path / "data" / "reports"
    reports.mkdir(parents=True)
    # Historical regime record ends before today; cannot cover forward sessions.
    (reports / "regime_history.json").write_text(
        json.dumps({"20260706": "normal", "20260707": "normal"}), encoding="utf-8"
    )
    # Forward calendar includes today's signal date AND future open sessions.
    (reports / "trade_calendar.json").write_text(
        json.dumps(["20260707", "20260714", "20260715", "20260716"]),
        encoding="utf-8",
    )

    sessions = da._load_authoritative_session_dates()

    assert date(2026, 7, 15) in sessions
    assert date(2026, 7, 16) in sessions


def test_authoritative_sessions_fall_back_to_regime_history(tmp_path, monkeypatch):
    """Without a forward calendar, fall back to regime_history (unchanged)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAILY_ACTION_CALENDAR_PATH", raising=False)
    reports = tmp_path / "data" / "reports"
    reports.mkdir(parents=True)
    (reports / "regime_history.json").write_text(
        json.dumps({"20260706": "normal", "20260707": "normal"}), encoding="utf-8"
    )

    sessions = da._load_authoritative_session_dates()

    assert date(2026, 7, 7) in sessions
    assert date(2026, 7, 15) not in sessions


def test_refresh_writes_forward_inclusive_calendar(tmp_path):
    """The refresh persists real open sessions incl. future dates."""
    reports = tmp_path / "reports"

    target = da.refresh_authoritative_trade_calendar(
        reports_dir=reports,
        fetch=lambda _start, _end: ["20260707", "20260714", "20260715", "20260716"],
    )

    assert target is not None
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert "20260715" in stored
    assert "20260716" in stored
    # Sorted, deduplicated, compact YYYYMMDD.
    assert stored == sorted(set(stored))


def test_refresh_never_overwrites_existing_with_empty(tmp_path):
    """An authoritative-source failure (empty) must not clobber a good calendar."""
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    good = reports / "trade_calendar.json"
    good.write_text(json.dumps(["20260714", "20260715"]), encoding="utf-8")

    result = da.refresh_authoritative_trade_calendar(
        reports_dir=reports, fetch=lambda _start, _end: []
    )

    assert result is None
    # Existing good calendar is preserved.
    assert json.loads(good.read_text(encoding="utf-8")) == ["20260714", "20260715"]
