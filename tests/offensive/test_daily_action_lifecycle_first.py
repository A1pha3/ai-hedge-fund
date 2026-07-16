from __future__ import annotations

from datetime import date, timedelta

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action_service import DailyActionService, MarketBar
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository


def test_due_exit_runs_when_manifest_is_invalid(tmp_path):
    signal_date = date(2026, 7, 13)
    sessions = tuple(signal_date - timedelta(days=9 - offset) for offset in range(12))
    costs = ExecutionCosts(version="test")
    repository = LedgerRepository(tmp_path / "ledger.sqlite3", "daily-action-v2", 100_000, execution_costs=costs)
    repository.initialize()
    plan = repository.create_plan("000001", "btst_breakout", "v2", sessions[0] - timedelta(days=1), sessions[0], 0.10, 1)
    trade = repository.settle_plan_at_open(plan.trade_id, sessions[0], 10.0, 9.0, 11.0, False, 10.5, 9.5)[0]
    repository.mark_exit_pending(trade.trade_id, sessions[8], forced_exit_target_date=signal_date)
    service = DailyActionService(
        repository,
        TradingSessionCalendar(sessions),
        lambda _ticker, _trade_date: MarketBar(10.0, 10.0, 9.0, 11.0, False, 10.5, 9.5),
        costs,
        enforce_manifest_gate=False,
    )

    context = service.advance_lifecycle(signal_date)
    run = service.complete_run(context, snapshot=None, candidates=(), new_entry_block="readiness_manifest_invalid")

    assert run.completed_exits[0].reason == "exit_filled"
    assert run.block_reasons == ("readiness_manifest_invalid",)
