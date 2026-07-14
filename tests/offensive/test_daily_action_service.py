from datetime import date, timedelta
import json
import sqlite3

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action_service import (
    DailyActionService,
    MarketBar,
    PlanCandidate,
    RegimeAuthorization,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.trade_lifecycle import (
    ExecutionMode,
    FillSource,
    TradeState,
)


class FixedPrices:
    def __init__(self, default: MarketBar) -> None:
        self.default = default
        self.values: dict[tuple[str, date], MarketBar | None] = {}

    def __call__(self, ticker: str, trade_date: date) -> MarketBar | None:
        return self.values.get((ticker, trade_date), self.default)


@pytest.fixture
def sessions() -> tuple[date, ...]:
    start = date(2026, 7, 13)
    return tuple(start + timedelta(days=i) for i in range(12))


@pytest.fixture
def service(tmp_path, sessions) -> DailyActionService:
    costs = ExecutionCosts(
        version="test", commission=5.0, tax_rate=0.001, slippage_bps=10.0
    )
    repo = LedgerRepository(
        tmp_path / "ledger.sqlite3", "service", 100_000, execution_costs=costs
    )
    repo.initialize()
    prices = FixedPrices(
        MarketBar(
            open=10.0,
            close=10.0,
            limit_down=9.0,
            limit_up=11.0,
            suspended=False,
            high=10.5,
            low=9.5,
        )
    )
    return DailyActionService(
        repo,
        TradingSessionCalendar(sessions),
        prices,
        costs,
        enforce_manifest_gate=False,
    )


def candidate(ticker: str, priority: int = 1, weight: float = 0.10) -> PlanCandidate:
    return PlanCandidate(ticker, "btst_breakout", "v2", weight, priority)


def open_trade(service, ticker: str, entry_date: date, weight: float = 0.1):
    plan = service.repository.create_plan(
        ticker,
        "btst_breakout",
        "v2",
        entry_date - timedelta(days=1),
        entry_date,
        weight,
        1,
    )
    return service.repository.settle_plan_at_open(
        plan.trade_id, entry_date, 10.0, 9.0, 11.0, False, 10.5, 9.5,
    )[0]


def test_pending_plans_reserve_exposure_and_never_exceed_sixty_percent(
    service, sessions
):
    run = service.run(
        sessions[0], tuple(candidate(f"00000{i}", i) for i in range(1, 7))
    )
    assert run.open_exposure == 0.0
    assert run.reserved_exposure == pytest.approx(0.60)
    assert len(run.new_plans) == 6
    assert all(plan.execution_label == "pending" for plan in run.new_plans)
    assert all(plan.source_label == "pending" for plan in run.new_plans)


def test_fill_rechecks_capacity_and_skips_lower_priority_plan(service, sessions):
    for i in range(7):
        service.repository.create_plan(
            f"00001{i}", "btst_breakout", "v2", sessions[0], sessions[1], 0.10, i
        )
    run = service.run(sessions[1], ())
    assert run.open_exposure <= 0.60
    assert run.skipped_plans[-1].reason == "portfolio_capacity"
    assert len(service.repository.open_trades()) == 6
    assert all(trade.quantity % 100 == 0 for trade in service.repository.open_trades())
    assert service.repository.cash_balance() >= 0


def test_unknown_higher_priority_entry_expires_and_releases_capacity(service, sessions):
    unknown = [
        service.repository.create_plan(
            f"00002{i}", "btst_breakout", "v2", sessions[0], sessions[1], 0.10, i
        )
        for i in range(5)
    ]
    filled = service.repository.create_plan(
        "000025", "btst_breakout", "v2", sessions[0], sessions[1], 0.10, 5
    )
    skipped = service.repository.create_plan(
        "000026", "btst_breakout", "v2", sessions[0], sessions[1], 0.10, 6
    )
    for plan in unknown:
        service.prices.values[(plan.ticker, sessions[1])] = None

    run = service.run(sessions[1], ())

    assert all(service.repository.get_trade(plan.trade_id).state is TradeState.SKIPPED for plan in unknown)
    assert service.repository.get_trade(filled.trade_id).state is TradeState.OPEN
    assert service.repository.get_trade(skipped.trade_id).state is TradeState.OPEN
    assert run.open_exposure + run.reserved_exposure <= 0.60


def test_entry_plan_run_after_exact_date_is_atomically_expired(service, sessions):
    plan = service.repository.create_plan(
        "000027", "btst_breakout", "v2", sessions[0], sessions[1], 0.10, 1
    )
    service.run(sessions[2], ())
    assert service.repository.get_trade(plan.trade_id).state is TradeState.SKIPPED
    with sqlite3.connect(service.repository.path) as conn:
        payload = json.loads(conn.execute(
            "SELECT payload_json FROM trade_events WHERE trade_id=? AND event_type='PLAN_SKIPPED'",
            (plan.trade_id,),
        ).fetchone()[0])
    assert payload["reason"] == "entry_expired"


@pytest.mark.parametrize(
    ("bar", "reason"),
    [
        (None, "entry_queue_unknown"),
        (MarketBar(9, 9, 9, 11, False, 9, 9), "entry_unexecutable"),
    ],
)
def test_single_observed_open_failure_expires_without_next_day_fill(service, sessions, bar, reason):
    plan = service.repository.create_plan(
        "000028", "btst_breakout", "v2", sessions[0], sessions[1], 0.10, 1
    )
    service.prices.values[(plan.ticker, sessions[1])] = bar
    service.run(sessions[1], ())
    service.run(sessions[2], ())
    assert service.repository.get_trade(plan.trade_id).state is TradeState.SKIPPED
    with sqlite3.connect(service.repository.path) as conn:
        payload = json.loads(conn.execute(
            "SELECT payload_json FROM trade_events WHERE trade_id=? AND event_type='PLAN_SKIPPED'",
            (plan.trade_id,),
        ).fetchone()[0])
    assert payload["reason"] == reason
    assert service.repository.count_events(plan.trade_id, "ENTRY_FILLED") == 0


def test_mark_to_market_updates_nav_and_drawdown_before_new_plans(service, sessions):
    trade = open_trade(service, "000101", sessions[1])
    service.prices.values[(trade.ticker, sessions[2])] = MarketBar(
        10, 8, 7, 11, False, 10, 8
    )
    run = service.run(sessions[2], ())
    assert run.valuation.nav < service.repository.initial_cash
    assert run.valuation.drawdown < 0
    assert run.valuation.trade_date == sessions[2]


def test_session_nine_close_creates_exit_pending_for_session_ten_open(
    service, sessions
):
    trade = open_trade(service, "000102", sessions[1])
    session_nine = service.calendar.nth_holding_session(trade.entry_date, 9)
    run = service.run(session_nine, ())
    stored = service.repository.get_trade(trade.trade_id)
    assert stored.state is TradeState.EXIT_PENDING
    assert stored.forced_exit_target_date == service.calendar.nth_holding_session(
        trade.entry_date, 10
    )
    assert run.exit_plans[0].reason == "maximum_holding_session"


def test_limit_down_unknown_queue_records_exit_deferred(service, sessions):
    trade = open_trade(service, "000103", sessions[1])
    target = service.calendar.nth_holding_session(trade.entry_date, 10)
    service.repository.mark_exit_pending(
        trade.trade_id, sessions[9], forced_exit_target_date=target
    )
    service.prices.values[(trade.ticker, target)] = MarketBar(
        9, 9, 9, 11, False, 9.5, 9
    )
    run = service.run(target, ())
    assert service.repository.get_trade(trade.trade_id).state is TradeState.EXIT_PENDING
    assert run.deferred_exits[0].reason == "unknown_queue"
    assert service.repository.count_events(trade.trade_id, "EXIT_DEFERRED") == 1


def test_missing_calendar_blocks_new_plan_but_still_lists_open_trade(
    service, sessions, monkeypatch
):
    trade = open_trade(service, "000104", sessions[1])
    monkeypatch.setattr(
        type(service.calendar),
        "next_session",
        lambda self, value: (_ for _ in ()).throw(
            ValueError("open-session data unavailable")
        ),
    )
    run = service.run(sessions[2], (candidate("000105"),))
    assert run.new_plans == ()
    assert run.open_positions[0].trade_id == trade.trade_id
    assert run.block_reason == "calendar_unavailable"


def test_drawdown_fill_capacity_uses_current_nav_denominator(service, sessions):
    trades = [open_trade(service, f"00011{i}", sessions[1]) for i in range(5)]
    for trade in trades:
        service.prices.values[(trade.ticker, sessions[2])] = MarketBar(
            5, 5, 4, 6, False, 5.5, 4.5
        )
    for i in range(4):
        service.repository.create_plan(
            f"00012{i}", "btst_breakout", "v2", sessions[1], sessions[2], 0.1, i
        )

    run = service.run(sessions[2], ())

    assert run.open_exposure + run.reserved_exposure <= 0.60
    assert run.skipped_plans[-1].reason == "portfolio_capacity"


def test_missing_close_retains_profitable_marks_and_does_not_invent_capacity(
    service, sessions
):
    trades = [open_trade(service, f"00013{i}", sessions[1]) for i in range(5)]
    for trade in trades:
        service.prices.values[(trade.ticker, sessions[2])] = MarketBar(
            12, 12, 10, 13, False, 12.5, 11.5
        )
    service.run(sessions[2], ())
    for trade in trades:
        service.prices.values[(trade.ticker, sessions[3])] = None

    run = service.run(sessions[3], (candidate("000139"),))

    assert run.new_plans == ()
    assert set(run.valuation.stale_tickers) == {trade.ticker for trade in trades}
    assert run.valuation.market_value == pytest.approx(54_000)


def test_duplicate_ticker_candidates_are_deduplicated_and_capped(service, sessions):
    run = service.run(sessions[0], (candidate("000140", 2), candidate("000140", 1)))
    assert len(run.new_plans) == 1
    assert service.repository.planned_trades()[0].planned_weight == pytest.approx(0.10)


def test_held_ticker_cannot_receive_another_plan(service, sessions):
    open_trade(service, "000141", sessions[1])
    run = service.run(sessions[2], (candidate("000141"),))
    assert run.new_plans == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_weight": float("nan")},
        {"target_weight": 0},
        {"priority": 0},
        {"setup": "oversold_bounce"},
        {"setup": "unknown"},
        {"authorization": "crisis"},
    ],
)
def test_invalid_or_disabled_candidate_is_rejected(kwargs):
    values = dict(
        ticker="000142",
        setup="btst_breakout",
        setup_version="v2",
        target_weight=0.1,
        priority=1,
    )
    values.update(kwargs)
    with pytest.raises(ValueError):
        PlanCandidate(**values)


def test_candidate_cannot_forge_rendered_execution_label():
    with pytest.raises(TypeError):
        PlanCandidate("000142", "btst_breakout", "v2", 0.1, 1, simulation_label="实盘")


def test_legacy_unverified_cannot_claim_regime_twelve_percent(
    service, sessions
):
    normal = PlanCandidate("000143", "btst_breakout", "v2", 0.12, 1)
    crisis = PlanCandidate(
        "000144", "btst_breakout", "v2", 0.12, 2, RegimeAuthorization.BTST_CRISIS
    )
    service.run(sessions[0], (normal, crisis))
    weights = {
        plan.ticker: plan.planned_weight for plan in service.repository.planned_trades()
    }
    assert weights == {"000143": pytest.approx(0.10), "000144": pytest.approx(0.10)}


def test_same_day_rerun_does_not_render_or_record_duplicate_plan(service, sessions):
    first = service.run(sessions[0], (candidate("000145"),))
    second = service.run(sessions[0], (candidate("000145"),))
    assert len(first.new_plans) == 1
    assert second.new_plans == ()
    assert (
        service.repository.count_events(first.new_plans[0].trade_id, "PLAN_CREATED")
        == 1
    )


@pytest.mark.parametrize("calendar_dates", [(), (date(2026, 7, 13),)])
def test_due_entry_fails_closed_when_as_of_is_not_exact_calendar_session(
    tmp_path, sessions, calendar_dates
):
    repo = LedgerRepository(
        tmp_path / "closed-calendar.sqlite3", "closed", 100_000,
        execution_costs=ExecutionCosts(version="test"),
    )
    repo.initialize()
    plan = repo.create_plan(
        "000150", "btst_breakout", "v2", sessions[0], sessions[1], 0.1, 1
    )
    prices = FixedPrices(MarketBar(10, 10, 9, 11, False, 10.5, 9.5))
    local = DailyActionService(
        repo,
        TradingSessionCalendar(calendar_dates),
        prices,
        ExecutionCosts(version="test"),
        enforce_manifest_gate=False,
    )
    run = local.run(sessions[1], ())
    assert repo.get_trade(plan.trade_id).state is TradeState.SKIPPED
    assert run.skipped_plans[-1].reason == "entry_calendar_unavailable"
    assert repo.count_events(plan.trade_id, "ENTRY_FILLED") == 0


def test_invalid_entry_calendar_does_not_block_due_exit_retry(service, sessions):
    trade = open_trade(service, "000152", sessions[1])
    service.repository.mark_exit_pending(
        trade.trade_id, sessions[1], forced_exit_target_date=sessions[2]
    )
    service.calendar = TradingSessionCalendar.from_dates([])
    service.prices.values[(trade.ticker, sessions[2])] = None
    run = service.run(sessions[2], ())
    assert run.deferred_exits[0].trade_id == trade.trade_id
    assert service.repository.count_events(trade.trade_id, "EXIT_DEFERRED") == 1


def test_btst_plan_requires_full_entry_through_holding_session_ten(tmp_path):
    signal = date(2026, 7, 10)
    monday = date(2026, 7, 13)
    repo = LedgerRepository(
        tmp_path / "short-calendar.sqlite3", "short", 100_000,
        execution_costs=ExecutionCosts(version="test"),
    )
    repo.initialize()
    local = DailyActionService(
        repo,
        TradingSessionCalendar((signal, monday)),
        FixedPrices(MarketBar(10, 10, 9, 11, False, 10.5, 9.5)),
        ExecutionCosts(version="test"),
        enforce_manifest_gate=False,
    )
    run = local.run(signal, (candidate("000160"),))
    assert run.new_plans == ()
    assert run.block_reason == "calendar_unavailable"
    assert repo.planned_trades() == []


def test_open_trade_with_incomplete_horizon_surfaces_calendar_warning(tmp_path):
    entry = date(2026, 7, 13)
    repo = LedgerRepository(
        tmp_path / "open-short.sqlite3", "open-short", 100_000,
        execution_costs=ExecutionCosts(version="test"),
    )
    repo.initialize()
    third = entry + timedelta(days=2)
    local = DailyActionService(
        repo,
        TradingSessionCalendar((entry, entry + timedelta(days=1), third)),
        FixedPrices(MarketBar(10, 10, 9, 11, False, 10.5, 9.5)),
        ExecutionCosts(version="test"),
        enforce_manifest_gate=False,
    )
    trade = open_trade(local, "000161", entry)
    run = local.run(entry + timedelta(days=1), ())
    assert repo.get_trade(trade.trade_id).state is TradeState.OPEN
    assert run.block_reason == "calendar_unavailable"


def test_reentry_missing_close_does_not_inherit_closed_trade_mark(service, sessions):
    old = open_trade(service, "000151", sessions[1])
    service.prices.values[(old.ticker, sessions[2])] = MarketBar(
        20, 20, 18, 22, False, 21, 19
    )
    service.run(sessions[2], ())
    service.repository.mark_exit_pending(
        old.trade_id, sessions[2], forced_exit_target_date=sessions[3]
    )
    service.prices.values[(old.ticker, sessions[3])] = MarketBar(
        10, 10, 9, 11, False, 10.5, 9.5
    )
    service.run(sessions[3], ())
    new = open_trade(service, old.ticker, sessions[4])
    service.prices.values[(new.ticker, sessions[5])] = None
    run = service.run(sessions[5], ())
    assert run.valuation.market_value == pytest.approx(
        new.raw_entry_price * new.quantity
    )
    assert new.ticker in run.valuation.stale_tickers
