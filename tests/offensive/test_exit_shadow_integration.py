from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pandas as pd
import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action import (
    DailyActionV2Run,
    render_daily_action_v2,
)
from src.screening.offensive.daily_action_service import (
    DailyActionService,
    MarketBar,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.trade_lifecycle import (
    ExecutionMode,
    FillSource,
    TradeState,
)


def _sessions() -> tuple[date, ...]:
    start = date(2026, 6, 22)
    return tuple(start + timedelta(days=offset) for offset in range(28))


def _bar(close: float) -> MarketBar:
    return MarketBar(
        open=close,
        close=close,
        limit_down=close * 0.9,
        limit_up=close * 1.1,
        suspended=False,
        high=close + 0.2,
        low=close - 0.2,
    )


@pytest.fixture
def shadow_case(tmp_path):
    sessions = _sessions()
    entry_date = sessions[15]
    as_of = sessions[18]
    ticker = "000777"
    prices = {(ticker, session): _bar(10.0) for session in sessions}
    prices[(ticker, entry_date)] = _bar(10.0)
    prices[(ticker, sessions[16])] = _bar(11.0)
    prices[(ticker, sessions[17])] = _bar(12.0)
    prices[(ticker, as_of)] = _bar(10.5)

    repository = LedgerRepository(tmp_path / "ledger.sqlite3", "shadow", 100_000)
    repository.initialize()
    plan = repository.create_plan(
        ticker,
        "btst_breakout",
        "v2",
        sessions[14],
        entry_date,
        0.10,
        1,
    )
    trade = repository.fill_plan(
        plan.trade_id,
        ExecutionMode.PAPER,
        FillSource.SYNTHETIC_OPEN,
        entry_date,
        10.0,
        1_000,
        5.0,
        0.0,
        10.0,
    )
    service = DailyActionService(
        repository,
        TradingSessionCalendar(sessions),
        lambda symbol, session: prices.get((symbol, session)),
        ExecutionCosts(version="test"),
        enforce_manifest_gate=False,
    )
    return service, trade, prices, as_of


def _table_bytes(path, table: str) -> bytes:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = [
            dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")
        ]
    return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()


def test_shadow_exit_never_changes_trade_state_or_execution_ledger(shadow_case):
    service, open_trade, prices, as_of = shadow_case
    before_trade = _table_bytes(service.repository.path, "trades")
    before_events = _table_bytes(service.repository.path, "trade_events")
    before_cash = service.repository.cash_balance()

    run = service.run(as_of, candidates=(), shadow_prices=prices)

    after = service.repository.get_trade(open_trade.trade_id)
    assert after.state is TradeState.OPEN
    assert run.open_positions[0].shadow_would_exit_next_open is True
    assert run.open_positions[0].shadow_reason == "close_below_trailing_line"
    assert run.open_positions[0].shadow_exit_line > 10.5
    assert _table_bytes(service.repository.path, "trades") == before_trade
    assert _table_bytes(service.repository.path, "trade_events") == before_events
    assert service.repository.cash_balance() == before_cash
    assert service.repository.count_events(open_trade.trade_id, "EXIT_REQUESTED") == 0
    assert service.repository.count_events(open_trade.trade_id, "EXIT_PENDING") == 0
    assert run.exit_plans == ()


def test_render_labels_shadow_as_non_executable_advice(shadow_case):
    service, _open_trade, prices, as_of = shadow_case
    run = service.run(as_of, candidates=(), shadow_prices=prices)

    text = render_daily_action_v2(DailyActionV2Run(run, (), run.open_positions, (), ()))

    assert "shadow only" in text.lower()
    assert "不改变默认退出" in text
    assert "close_below_trailing_line" in text
    assert "shadow_exit_line=" in text
    assert text == service.render(run)


def test_missing_shadow_path_is_visible_and_never_treated_as_exit(shadow_case):
    service, _open_trade, prices, as_of = shadow_case
    incomplete = dict(prices)
    incomplete.pop(("000777", as_of))

    position = service.run(
        as_of, candidates=(), shadow_prices=incomplete
    ).open_positions[0]

    assert position.shadow_exit_line is None
    assert position.shadow_would_exit_next_open is False
    assert position.shadow_reason == "insufficient_data"


def test_shadow_ignores_observations_after_as_of(shadow_case):
    service, _open_trade, prices, _as_of = shadow_case
    before_reversal = service.calendar.open_sessions[17]

    position = service.run(
        before_reversal,
        candidates=(),
        shadow_prices=prices,
    ).open_positions[0]

    assert position.shadow_would_exit_next_open is False
    assert position.shadow_reason == "hold"


def test_repeated_shadow_runs_are_idempotent(shadow_case):
    service, open_trade, prices, as_of = shadow_case
    first = service.run(as_of, candidates=(), shadow_prices=prices).open_positions[0]
    trade_after_first = _table_bytes(service.repository.path, "trades")
    events_after_first = _table_bytes(service.repository.path, "trade_events")

    second = service.run(as_of, candidates=(), shadow_prices=prices).open_positions[0]

    assert (
        first.shadow_exit_line,
        first.shadow_would_exit_next_open,
        first.shadow_reason,
    ) == (
        second.shadow_exit_line,
        second.shadow_would_exit_next_open,
        second.shadow_reason,
    )
    assert _table_bytes(service.repository.path, "trades") == trade_after_first
    assert _table_bytes(service.repository.path, "trade_events") == events_after_first
    assert service.repository.count_events(open_trade.trade_id, "EXIT_REQUESTED") == 0


def test_shadow_accepts_the_price_history_dataframe_used_by_daily_action(shadow_case):
    service, _open_trade, prices, as_of = shadow_case
    frame = pd.DataFrame(
        {
            "date": session,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
        }
        for (ticker, session), bar in prices.items()
        if ticker == "000777"
    )

    position = service.run(as_of, candidates=(), shadow_prices=frame).open_positions[0]

    assert position.shadow_would_exit_next_open is True
    assert position.shadow_reason == "close_below_trailing_line"
