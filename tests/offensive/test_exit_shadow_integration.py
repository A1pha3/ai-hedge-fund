from __future__ import annotations

import json
import sqlite3
from dataclasses import fields
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
from src.screening.offensive.atr_utils import compute_atr
from src.screening.offensive.exit_policy import (
    ExitObservation,
    ExitPolicyState,
    evaluate_shadow_exit,
)
from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.daily_action_service import PlanCandidate
from src.research.exit_shadow_research import _normalize_prices
from src.screening.offensive.trade_lifecycle import (
    ExecutionMode,
    FillSource,
    TradeState,
)


def _sessions() -> tuple[date, ...]:
    start = date(2026, 6, 22)
    return tuple(start + timedelta(days=offset) for offset in range(40))


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


def _all_table_bytes(path) -> dict[str, bytes]:
    with sqlite3.connect(path) as connection:
        tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        )
    return {table: _table_bytes(path, table) for table in tables}


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


def test_shadow_provider_exception_is_visible_after_normal_work(shadow_case):
    service, open_trade, _prices, as_of = shadow_case

    def broken_provider(_ticker, _session):
        raise RuntimeError("malformed local price provider")

    run = service.run(
        as_of,
        candidates=(PlanCandidate("000999", "btst_breakout", "v2", 0.10, 2),),
        shadow_prices=broken_provider,
    )

    assert run.open_positions[0].shadow_reason == "insufficient_data"
    assert len(run.new_plans) == 1
    assert run.valuation.trade_date == as_of
    assert service.repository.latest_valuation() == run.valuation
    assert service.repository.get_trade(open_trade.trade_id).state is TradeState.OPEN


def test_shadow_date_parser_exception_is_visible(shadow_case, monkeypatch):
    service, _open_trade, prices, as_of = shadow_case
    frame = pd.DataFrame(
        {"date": session, "high": bar.high, "low": bar.low, "close": bar.close}
        for (_ticker, session), bar in prices.items()
    )
    monkeypatch.setattr(
        "src.screening.offensive.daily_action_service.pd.to_datetime",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("parser failed")),
    )

    run = service.run(as_of, candidates=(), shadow_prices=frame)

    assert run.open_positions[0].shadow_reason == "insufficient_data"
    assert service.repository.latest_valuation() == run.valuation


def test_shadow_policy_exception_is_visible(shadow_case, monkeypatch):
    service, _open_trade, prices, as_of = shadow_case
    monkeypatch.setattr(
        "src.screening.offensive.daily_action_service.evaluate_shadow_exit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("policy failed")),
    )

    run = service.run(as_of, candidates=(), shadow_prices=prices)

    assert run.open_positions[0].shadow_reason == "insufficient_data"
    assert service.repository.latest_valuation() == run.valuation


def test_shadow_atr_exception_is_visible(shadow_case, monkeypatch):
    service, _open_trade, prices, as_of = shadow_case
    monkeypatch.setattr(
        "src.screening.offensive.daily_action_service.compute_atr",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ATR failed")),
    )

    run = service.run(as_of, candidates=(), shadow_prices=prices)

    assert run.open_positions[0].shadow_reason == "insufficient_data"
    assert service.repository.latest_valuation() == run.valuation


def test_shadow_does_not_swallow_base_exceptions(shadow_case):
    service, _open_trade, _prices, as_of = shadow_case

    def interrupted(_ticker, _session):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        service.run(as_of, candidates=(), shadow_prices=interrupted)


def test_full_history_wilder_atr_matches_hand_and_research_prefix(shadow_case):
    service, _open_trade, prices, _as_of = shadow_case
    sessions = service.calendar.open_sessions
    entry_date = sessions[15]
    observation_date = sessions[16]
    for index, session in enumerate(sessions):
        close = 10.0
        high, low = (15.0, 5.0) if index < 4 else (10.2, 9.8)
        prices[("000777", session)] = MarketBar(
            close, close, close * 0.9, close * 1.1, False, high, low
        )
    prices[("000777", entry_date)] = MarketBar(20, 20, 18, 22, False, 20.2, 19.8)
    prices[("000777", observation_date)] = MarketBar(21, 21, 19, 23, False, 21.2, 20.8)
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
    prefix = frame.loc[frame["date"] <= observation_date].reset_index(drop=True)
    true_ranges: list[float] = []
    for index, row in prefix.iterrows():
        previous = float(prefix.iloc[index - 1]["close"]) if index else None
        true_ranges.append(
            max(
                float(row["high"] - row["low"]),
                abs(float(row["high"]) - previous) if previous is not None else 0.0,
                abs(float(row["low"]) - previous) if previous is not None else 0.0,
            )
        )
    hand_atr = sum(true_ranges[:14]) / 14
    for true_range in true_ranges[14:]:
        hand_atr = (hand_atr * 13 + true_range) / 14
    normalized, reason = _normalize_prices(frame)
    assert reason is None and normalized is not None
    shared_atr = compute_atr(normalized, period=14, at_idx=len(prefix))
    assert shared_atr == pytest.approx(hand_atr)

    entry_decision = evaluate_shadow_exit(
        ExitPolicyState.unarmed(entry_price=10.0),
        ExitObservation(
            entry_date, 1, 20.0, compute_atr(normalized, period=14, at_idx=16)
        ),
    )
    expected = evaluate_shadow_exit(
        entry_decision.state,
        ExitObservation(observation_date, 2, 21.0, shared_atr),
    )
    position = service.run(
        observation_date, candidates=(), shadow_prices=frame
    ).open_positions[0]
    assert position.shadow_exit_line == pytest.approx(expected.state.exit_line)

    extended = pd.concat(
        [
            frame,
            pd.DataFrame(
                [
                    {
                        "date": sessions[30],
                        "open": 100,
                        "high": 120,
                        "low": 80,
                        "close": 100,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    repeated = service.run(
        observation_date, candidates=(), shadow_prices=extended
    ).open_positions[0]
    assert repeated.shadow_exit_line == pytest.approx(position.shadow_exit_line)


def test_session_nine_exit_pending_is_omitted_from_shadow_rows(shadow_case):
    service, open_trade, prices, _as_of = shadow_case
    session_nine = service.calendar.nth_holding_session(open_trade.entry_date, 9)

    run = service.run(session_nine, candidates=(), shadow_prices=prices)
    text = render_daily_action_v2(DailyActionV2Run(run, (), run.open_positions, (), ()))

    assert (
        service.repository.get_trade(open_trade.trade_id).state
        is TradeState.EXIT_PENDING
    )
    assert run.open_positions == ()
    assert len(run.exit_plans) == 1
    assert "000777 shadow_exit_line" not in text


@pytest.mark.parametrize("mode", ["duplicate", "normalized_duplicate", "out_of_order"])
def test_duplicate_or_out_of_order_shadow_history_fails_closed(shadow_case, mode):
    service, _open_trade, prices, as_of = shadow_case
    frame = pd.DataFrame(
        {"date": session, "high": bar.high, "low": bar.low, "close": bar.close}
        for (_ticker, session), bar in prices.items()
    )
    first, second = frame.loc[0, "date"], frame.loc[1, "date"]
    if mode == "duplicate":
        frame.loc[1, "date"] = first
    elif mode == "normalized_duplicate":
        frame.loc[0, "date"] = f"{first.isoformat()} 00:00:00"
        frame.loc[1, "date"] = first.isoformat()
    else:
        frame.loc[0, "date"], frame.loc[1, "date"] = second, first

    position = service.run(as_of, candidates=(), shadow_prices=frame).open_positions[0]

    assert position.shadow_reason == "insufficient_data"


def test_fourteen_rows_without_prior_close_context_is_insufficient(shadow_case):
    service, _open_trade, prices, as_of = shadow_case
    frame = pd.DataFrame(
        {"date": session, "high": bar.high, "low": bar.low, "close": bar.close}
        for (_ticker, session), bar in prices.items()
        if service.calendar.open_sessions[2] <= session <= as_of
    )

    position = service.run(as_of, candidates=(), shadow_prices=frame).open_positions[0]

    assert position.shadow_reason == "insufficient_data"


def test_default_shadow_uses_complete_read_only_history_loader(shadow_case):
    service, _open_trade, prices, as_of = shadow_case
    frame = pd.DataFrame(
        {"date": session, "high": bar.high, "low": bar.low, "close": bar.close}
        for (_ticker, session), bar in prices.items()
    )
    frame.loc[1, "date"] = frame.loc[0, "date"]
    local = DailyActionService(
        service.repository,
        service.calendar,
        service.prices,
        service.costs,
        enforce_manifest_gate=False,
        shadow_history=lambda _ticker: frame,
    )

    position = local.run(as_of, candidates=()).open_positions[0]

    assert position.shadow_reason == "insufficient_data"


def _production_view(run):
    result = {
        field.name: getattr(run, field.name)
        for field in fields(run)
        if field.name != "open_positions"
    }
    result["open_positions"] = tuple(
        {
            key: value
            for key, value in vars(position).items()
            if not key.startswith("shadow_")
        }
        for position in run.open_positions
    )
    return result


def test_triggering_shadow_is_differentially_zero_effect_and_idempotent(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        LedgerRepository,
        "_now",
        staticmethod(lambda: "2026-07-13T00:00:00+00:00"),
    )
    sessions = _sessions()
    entry_date, as_of = sessions[15], sessions[18]
    prices = {("000777", session): _bar(10.0) for session in sessions}
    prices[("000777", sessions[16])] = _bar(11.0)
    prices[("000777", sessions[17])] = _bar(12.0)
    prices[("000777", as_of)] = _bar(10.5)

    def build(path):
        repository = LedgerRepository(path, "differential", 100_000)
        repository.initialize()
        plan = repository.create_plan(
            "000777", "btst_breakout", "v2", sessions[14], entry_date, 0.10, 1
        )
        repository.fill_plan(
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
        return DailyActionService(
            repository,
            TradingSessionCalendar(sessions),
            lambda ticker, session: prices.get((ticker, session), _bar(10.0)),
            ExecutionCosts(version="test"),
            enforce_manifest_gate=False,
        )

    trigger_service = build(tmp_path / "trigger.sqlite3")
    control_service = build(tmp_path / "control.sqlite3")
    candidates = (PlanCandidate("000888", "btst_breakout", "v2", 0.10, 2),)

    trigger_run = trigger_service.run(as_of, candidates, shadow_prices=prices)
    control_run = control_service.run(as_of, candidates, shadow_prices={})

    assert trigger_run.open_positions[0].shadow_would_exit_next_open is True
    assert control_run.open_positions[0].shadow_reason == "insufficient_data"
    assert _production_view(trigger_run) == _production_view(control_run)
    assert _all_table_bytes(trigger_service.repository.path) == _all_table_bytes(
        control_service.repository.path
    )
    assert (
        trigger_service.repository.cash_balance()
        == control_service.repository.cash_balance()
    )
    trigger_tables_after_first = _all_table_bytes(trigger_service.repository.path)
    control_tables_after_first = _all_table_bytes(control_service.repository.path)

    trigger_second = trigger_service.run(as_of, candidates, shadow_prices=prices)
    control_second = control_service.run(as_of, candidates, shadow_prices={})
    assert _production_view(trigger_second) == _production_view(control_second)
    assert _all_table_bytes(trigger_service.repository.path) == _all_table_bytes(
        control_service.repository.path
    )
    assert (
        _all_table_bytes(trigger_service.repository.path) == trigger_tables_after_first
    )
    assert (
        _all_table_bytes(control_service.repository.path) == control_tables_after_first
    )
