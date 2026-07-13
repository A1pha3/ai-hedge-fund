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
