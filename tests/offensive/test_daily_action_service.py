from datetime import date, timedelta

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action_service import (
    DailyActionService,
    MarketBar,
    PlanCandidate,
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
    repo = LedgerRepository(tmp_path / "ledger.sqlite3", "service", 100_000)
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
        ExecutionCosts(
            version="test", commission=5.0, tax_rate=0.001, slippage_bps=10.0
        ),
    )


def candidate(ticker: str, priority: int = 1, weight: float = 0.10) -> PlanCandidate:
    return PlanCandidate(ticker, "btst_breakout", "v2", weight, priority, "模拟盘")


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
    return service.repository.fill_plan(
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


def test_pending_plans_reserve_exposure_and_never_exceed_sixty_percent(
    service, sessions
):
    run = service.run(
        sessions[0], tuple(candidate(f"00000{i}", i) for i in range(1, 7))
    )
    assert run.open_exposure == 0.0
    assert run.reserved_exposure == pytest.approx(0.60)
    assert len(run.new_plans) == 6
    assert all(plan.simulation_label == "模拟盘" for plan in run.new_plans)


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


def test_unknown_higher_priority_entry_keeps_its_capacity_reserved(service, sessions):
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

    assert all(
        service.repository.get_trade(plan.trade_id).state is TradeState.PLANNED
        for plan in unknown
    )
    assert service.repository.get_trade(filled.trade_id).state is TradeState.OPEN
    assert service.repository.get_trade(skipped.trade_id).state is TradeState.SKIPPED
    assert run.open_exposure + run.reserved_exposure <= 0.60


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
