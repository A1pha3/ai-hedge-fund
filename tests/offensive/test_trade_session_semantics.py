from datetime import date

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
    start, end = (missing, tuesday) if missing_endpoint == "start" else (monday, missing)

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
