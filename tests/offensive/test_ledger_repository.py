from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest

from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.trade_lifecycle import ExecutionMode, FillSource, TradeState


def _repo(tmp_path: Path) -> LedgerRepository:
    repo = LedgerRepository(tmp_path / "ledger.sqlite3", ledger_id="test", initial_cash=100_000)
    repo.initialize()
    return repo


def _plan(repo: LedgerRepository):
    return repo.create_plan(
        "000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.10, 1
    )


def test_duplicate_plan_is_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    first = _plan(repo)
    second = _plan(repo)
    assert first.trade_id == second.trade_id
    assert repo.count_events(first.trade_id, "PLAN_CREATED") == 1


def test_fill_and_event_commit_together(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    trade = _plan(repo)
    opened = repo.fill_plan(
        trade.trade_id,
        execution_mode=ExecutionMode.PAPER,
        fill_source=FillSource.SYNTHETIC_OPEN,
        entry_date=date(2026, 7, 13),
        raw_fill_price=10.0,
        quantity=1_000,
        commission=5.0,
        tax=0.0,
        slippage_cost=30.0,
    )
    assert opened.state is TradeState.OPEN
    assert repo.cash_balance() == pytest.approx(89_965.0)
    assert repo.count_events(trade.trade_id, "ENTRY_FILLED") == 1


def test_failed_transition_rolls_back_trade_and_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    trade = _plan(repo)
    monkeypatch.setattr(
        repo,
        "_insert_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError, match="boom"):
        repo.fill_plan(
            trade.trade_id,
            ExecutionMode.PAPER,
            FillSource.SYNTHETIC_OPEN,
            date(2026, 7, 13),
            10.0,
            1_000,
            5.0,
            0.0,
            30.0,
        )
    assert repo.get_trade(trade.trade_id).state is TradeState.PLANNED


def test_concurrent_duplicate_plan_creates_one_trade_and_event(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        trades = list(pool.map(lambda _: _plan(repo), range(8)))

    assert len({trade.trade_id for trade in trades}) == 1
    assert repo.count_trades() == 1
    assert repo.count_events(trades[0].trade_id, "PLAN_CREATED") == 1
