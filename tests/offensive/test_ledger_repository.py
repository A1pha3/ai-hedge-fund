from concurrent.futures import ThreadPoolExecutor
from datetime import date
import hashlib
from pathlib import Path
import sqlite3

import pytest

from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.trade_lifecycle import (
    ExecutionMode,
    FillSource,
    TradeState,
)


def _repo(tmp_path: Path) -> LedgerRepository:
    repo = LedgerRepository(
        tmp_path / "ledger.sqlite3", ledger_id="test", initial_cash=100_000
    )
    repo.initialize()
    return repo


def _plan(repo: LedgerRepository):
    return repo.create_plan(
        "000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.10, 1
    )


def _opened(repo: LedgerRepository):
    trade = _plan(repo)
    return repo.fill_plan(
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


def _tree_snapshot(path: Path) -> list[tuple[str, int, int, str]]:
    return [
        (
            str(item.relative_to(path)),
            item.stat().st_size,
            item.stat().st_mtime_ns,
            hashlib.sha256(item.read_bytes()).hexdigest(),
        )
        for item in sorted(path.rglob("*"))
        if item.is_file()
    ]


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


def test_conflicting_duplicate_defer_rolls_back_field_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    opened = _opened(repo)
    repo.mark_exit_pending(opened.trade_id, date(2026, 7, 20))
    first = repo.defer_exit(
        opened.trade_id, date(2026, 7, 21), highest_close=12.0, exit_line=11.0
    )

    with pytest.raises(ValueError, match="conflicting idempotent event"):
        repo.defer_exit(
            opened.trade_id, date(2026, 7, 21), highest_close=13.0, exit_line=12.0
        )

    unchanged = repo.get_trade(opened.trade_id)
    assert unchanged.highest_close == first.highest_close == 12.0
    assert unchanged.exit_line == first.exit_line == 11.0
    assert repo.count_events(opened.trade_id, "EXIT_DEFERRED") == 1


def test_concurrent_exit_pending_is_one_transition(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    opened = _opened(repo)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: repo.mark_exit_pending(
                    opened.trade_id,
                    date(2026, 7, 20),
                    highest_close=12.0,
                    exit_line=11.0,
                ),
                range(8),
            )
        )

    assert {result.state for result in results} == {TradeState.EXIT_PENDING}
    assert repo.count_events(opened.trade_id, "EXIT_PENDING") == 1


@pytest.mark.parametrize(
    ("schema_version", "initial_cash", "message"),
    [
        (99, 100_000, "unsupported schema version"),
        (1, 200_000, "initial_cash mismatch"),
    ],
)
def test_initialize_rejects_incompatible_existing_metadata(
    tmp_path: Path, schema_version: int, initial_cash: float, message: str
) -> None:
    path = tmp_path / "ledger.sqlite3"
    repo = LedgerRepository(path, ledger_id="test", initial_cash=100_000)
    repo.initialize()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE ledger_meta SET schema_version=?, initial_cash=? WHERE ledger_id='test'",
            (schema_version, initial_cash),
        )

    with pytest.raises(ValueError, match=message):
        repo.initialize()


@pytest.mark.parametrize(
    ("price", "quantity", "commission", "tax", "slippage"),
    [
        (0.0, 1, 0.0, 0.0, 0.0),
        (float("inf"), 1, 0.0, 0.0, 0.0),
        (10.0, 0, 0.0, 0.0, 0.0),
        (10.0, 1, -1.0, 0.0, 0.0),
        (10.0, 1, 0.0, float("nan"), 0.0),
        (10.0, 1, 0.0, 0.0, float("inf")),
    ],
)
def test_fill_rejects_invalid_money_or_quantity(
    tmp_path: Path,
    price: float,
    quantity: int,
    commission: float,
    tax: float,
    slippage: float,
) -> None:
    repo = _repo(tmp_path)
    trade = _plan(repo)
    with pytest.raises(ValueError):
        repo.fill_plan(
            trade.trade_id,
            ExecutionMode.PAPER,
            FillSource.SYNTHETIC_OPEN,
            date(2026, 7, 13),
            price,
            quantity,
            commission,
            tax,
            slippage,
        )
    assert repo.get_trade(trade.trade_id).state is TradeState.PLANNED


@pytest.mark.parametrize("price", [0.0, float("nan"), float("inf")])
def test_close_rejects_invalid_price(tmp_path: Path, price: float) -> None:
    repo = _repo(tmp_path)
    opened = _opened(repo)
    repo.mark_exit_pending(opened.trade_id, date(2026, 7, 20))
    with pytest.raises(ValueError):
        repo.close_trade(opened.trade_id, date(2026, 7, 21), price, 0.0, 0.0, 0.0)
    assert repo.get_trade(opened.trade_id).state is TradeState.EXIT_PENDING


def test_fill_source_must_match_execution_mode(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    trade = _plan(repo)
    with pytest.raises(ValueError, match="not allowed"):
        repo.fill_plan(
            trade.trade_id,
            ExecutionMode.BROKER_CONFIRMED,
            FillSource.SYNTHETIC_OPEN,
            date(2026, 7, 13),
            10.0,
            1,
            0.0,
            0.0,
            0.0,
        )


def test_exit_defer_close_updates_state_events_and_cash(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    opened = _opened(repo)
    pending = repo.mark_exit_pending(opened.trade_id, date(2026, 7, 20))
    deferred = repo.defer_exit(pending.trade_id, date(2026, 7, 21), exit_line=9.5)
    closed = repo.close_trade(
        deferred.trade_id, date(2026, 7, 22), 11.0, 5.0, 11.0, 20.0
    )

    assert closed.state is TradeState.CLOSED
    assert repo.open_trades() == []
    assert repo.cash_balance() == pytest.approx(100_929.0)
    assert repo.count_events(closed.trade_id, "EXIT_PENDING") == 1
    assert repo.count_events(closed.trade_id, "EXIT_DEFERRED") == 1
    assert repo.count_events(closed.trade_id, "EXIT_FILLED") == 1


def test_valuation_upsert_is_ledger_isolated(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    first = LedgerRepository(path, ledger_id="first", initial_cash=100_000)
    second = LedgerRepository(path, ledger_id="second", initial_cash=200_000)
    first.initialize()
    second.initialize()
    first.record_valuation(
        date(2026, 7, 13), 90_000, 11_000, 1.01, 1.02, -0.01, ["000001"]
    )
    first.record_valuation(date(2026, 7, 13), 91_000, 10_000, 1.01, 1.02, -0.01, [])
    second.record_valuation(date(2026, 7, 13), 200_000, 0, 1.0, 1.0, 0.0, [])

    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT ledger_id, cash, stale_tickers_json FROM daily_valuations ORDER BY ledger_id"
        ).fetchall()
    assert rows == [("first", 91_000.0, "[]"), ("second", 200_000.0, "[]")]


def test_repository_does_not_touch_legacy_paper_directories(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    protected = [root / "data/paper_trading", root / "data/paper_trading_backtest"]
    before = {path: _tree_snapshot(path) for path in protected}

    repo = _repo(tmp_path)
    _opened(repo)
    repo.record_valuation(date(2026, 7, 13), 90_000, 10_000, 1.0, 1.0, 0.0, [])

    assert {path: _tree_snapshot(path) for path in protected} == before


def test_planned_trades_filters_due_date_and_orders_by_priority(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    later = repo.create_plan(
        "000003", "btst", "v1", date(2026, 7, 10), date(2026, 7, 14), 0.1, 1
    )
    low = repo.create_plan(
        "000002", "btst", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.1, 2
    )
    high = repo.create_plan(
        "000001", "btst", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.1, 1
    )

    assert [trade.trade_id for trade in repo.planned_trades(date(2026, 7, 13))] == [
        high.trade_id,
        low.trade_id,
    ]
    assert later.trade_id not in {
        trade.trade_id for trade in repo.planned_trades(date(2026, 7, 13))
    }


def test_skip_plan_is_idempotent_and_conflicting_reason_rolls_back(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    plan = _plan(repo)
    skipped = repo.skip_plan(plan.trade_id, date(2026, 7, 13), "portfolio_capacity")
    repeated = repo.skip_plan(plan.trade_id, date(2026, 7, 13), "portfolio_capacity")

    assert skipped.state is repeated.state is TradeState.SKIPPED
    assert repo.count_events(plan.trade_id, "PLAN_SKIPPED") == 1
    with pytest.raises(ValueError, match="conflicting idempotent event"):
        repo.skip_plan(plan.trade_id, date(2026, 7, 13), "cash_capacity")
    assert repo.count_events(plan.trade_id, "PLAN_SKIPPED") == 1


def test_latest_valuation_is_ledger_scoped_and_peak_is_monotonic_input(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    first = LedgerRepository(path, "first", 100_000)
    second = LedgerRepository(path, "second", 200_000)
    first.initialize()
    second.initialize()
    first.record_valuation(date(2026, 7, 13), 90_000, 10_000, 1.0, 1.0, 0.0, [])
    first.record_valuation(
        date(2026, 7, 14), 89_000, 10_000, 0.99, 1.0, -0.01, ["000001"]
    )
    second.record_valuation(date(2026, 7, 14), 200_000, 0, 1.0, 1.2, 0.0, [])

    valuation = first.latest_valuation()
    assert valuation is not None
    assert valuation.trade_date == date(2026, 7, 14)
    assert valuation.peak == 1.0
    assert valuation.stale_tickers == ("000001",)


def test_create_plan_if_absent_reports_creation_without_duplicate_event(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    args = ("000001", "btst", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.1, 1)
    first, first_created = repo.create_plan_if_absent(*args)
    second, second_created = repo.create_plan_if_absent(*args)
    assert first.trade_id == second.trade_id
    assert first_created is True
    assert second_created is False
    assert repo.count_events(first.trade_id, "PLAN_CREATED") == 1


def test_position_mark_round_trip_is_latest_and_ledger_scoped(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    first = LedgerRepository(path, "first", 100_000)
    second = LedgerRepository(path, "second", 100_000)
    first.initialize()
    second.initialize()
    first_trade = _plan(first)
    second_trade = _plan(second)
    first.record_position_mark(first_trade.trade_id, date(2026, 7, 13), 10.0)
    first.record_position_mark(first_trade.trade_id, date(2026, 7, 14), 12.0)
    second.record_position_mark(second_trade.trade_id, date(2026, 7, 14), 99.0)
    assert first.latest_position_mark(
        first_trade.trade_id, date(2026, 7, 15)
    ) == pytest.approx(12.0)


def test_position_marks_do_not_leak_between_trade_epochs_for_same_ticker(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    old = repo.create_plan(
        "000001", "btst", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.1, 1
    )
    new = repo.create_plan(
        "000001", "btst", "v1", date(2026, 7, 14), date(2026, 7, 15), 0.1, 1
    )
    repo.record_position_mark(old.trade_id, date(2026, 7, 14), 20.0)
    assert repo.latest_position_mark(new.trade_id, date(2026, 7, 16)) is None
