from datetime import date, datetime

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar


def test_friday_entry_plan_resolves_to_monday() -> None:
    cal = TradingSessionCalendar.from_dates([date(2026, 7, 10), date(2026, 7, 13)])
    assert cal.next_session(date(2026, 7, 10)) == date(2026, 7, 13)


def test_tenth_holding_session_counts_entry_as_one() -> None:
    sessions = [date(2026, 9, d) for d in (21, 22, 23, 24, 25, 28, 29, 30)] + [
        date(2026, 10, d) for d in (9, 12)
    ]
    cal = TradingSessionCalendar.from_dates(sessions)
    assert cal.nth_holding_session(date(2026, 9, 21), 10) == date(2026, 10, 12)


def test_calendar_failure_does_not_fall_back_to_weekdays() -> None:
    cal = TradingSessionCalendar.from_dates([])
    with pytest.raises(ValueError, match="open-session data unavailable"):
        cal.next_session(date(2026, 10, 1))


def test_direct_construction_normalizes_unordered_duplicate_sessions() -> None:
    monday = date(2026, 7, 13)
    friday = date(2026, 7, 10)
    cal = TradingSessionCalendar((monday, friday, monday))

    assert cal.open_sessions == (friday, monday)
    assert cal.next_session(friday) == monday


def test_first_holding_session_is_entry_date() -> None:
    entry = date(2026, 7, 13)
    cal = TradingSessionCalendar.from_dates([entry])
    assert cal.nth_holding_session(entry, 1) == entry


def test_holding_session_number_must_be_positive() -> None:
    entry = date(2026, 7, 13)
    cal = TradingSessionCalendar.from_dates([entry])
    with pytest.raises(ValueError, match="at least 1"):
        cal.nth_holding_session(entry, 0)


def test_holding_entry_must_be_an_open_session() -> None:
    cal = TradingSessionCalendar.from_dates([date(2026, 7, 13)])
    with pytest.raises(ValueError, match="absent from open-session data"):
        cal.nth_holding_session(date(2026, 7, 10), 1)


def test_holding_horizon_requires_calendar_coverage() -> None:
    entry = date(2026, 7, 13)
    cal = TradingSessionCalendar.from_dates([entry])
    with pytest.raises(ValueError, match="open-session data unavailable"):
        cal.nth_holding_session(entry, 2)


@pytest.mark.parametrize("missing_endpoint", ["start", "end"])
def test_session_distance_requires_both_endpoints(missing_endpoint: str) -> None:
    monday = date(2026, 7, 13)
    tuesday = date(2026, 7, 14)
    missing = date(2026, 7, 15)
    cal = TradingSessionCalendar.from_dates([monday, tuesday])
    start, end = (
        (missing, tuesday) if missing_endpoint == "start" else (monday, missing)
    )

    with pytest.raises(ValueError, match="absent from open-session data"):
        cal.session_distance(start, end)


@pytest.mark.parametrize(
    ("start_index", "end_index", "expected"),
    [(0, 2, 2), (1, 1, 0), (2, 0, -2)],
)
def test_session_distance_is_signed_index_difference(
    start_index: int, end_index: int, expected: int
) -> None:
    sessions = [date(2026, 7, day) for day in (13, 14, 15)]
    cal = TradingSessionCalendar.from_dates(sessions)
    assert cal.session_distance(sessions[start_index], sessions[end_index]) == expected


def test_next_session_requires_future_calendar_coverage() -> None:
    final_session = date(2026, 7, 13)
    cal = TradingSessionCalendar.from_dates([final_session])
    with pytest.raises(ValueError, match="open-session data unavailable"):
        cal.next_session(final_session)


def test_contains_session_is_exact_and_empty_calendar_is_false() -> None:
    monday = date(2026, 7, 13)
    calendar = TradingSessionCalendar.from_dates([monday])
    assert calendar.contains_session(monday) is True
    assert calendar.contains_session(date(2026, 7, 14)) is False
    assert TradingSessionCalendar.from_dates([]).contains_session(monday) is False


def test_daily_action_signal_resolution_delegates_to_shared_resolver(
    tmp_path, monkeypatch
) -> None:
    """Task 1 (spec 8.1): --daily-action resolves its signal session through the
    single shared ``resolve_signal_session`` rather than a duplicated inline
    17:00 rule, so both commands share one authoritative cutoff policy."""
    import src.screening.offensive.daily_action as da

    monkeypatch.chdir(tmp_path)
    cache = tmp_path / "data" / "price_cache"
    cache.mkdir(parents=True)
    # price_cache already contains the not-yet-ready session (pre-17:00 injection).
    (cache / "000001.csv").write_text("date,close\n20260714,10.0\n")

    monkeypatch.setattr(
        da,
        "_current_cn_datetime",
        lambda: datetime(2026, 7, 13, 16, 0, tzinfo=da._CN_TZ),
    )
    monkeypatch.setattr(
        da,
        "_load_authoritative_session_dates",
        lambda: (date(2026, 7, 10), date(2026, 7, 13), date(2026, 7, 14)),
    )

    calls: dict[str, object] = {}
    real = da.resolve_signal_session

    def spy(**kwargs):
        calls["kwargs"] = kwargs
        return real(**kwargs)

    monkeypatch.setattr(da, "resolve_signal_session", spy)

    signal_date, _regime = da._resolve_trade_date_and_regime()

    assert "kwargs" in calls, "daily action did not delegate to resolve_signal_session"
    # Monday 16:00 (before 17:00) → cutoff Sunday → latest session <= Sunday = Friday.
    assert signal_date == "20260710"
