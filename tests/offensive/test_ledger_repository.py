from concurrent.futures import ThreadPoolExecutor
import dataclasses
from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from src.screening.offensive.ledger_repository import LedgerRepository, PlanProvenance
from src.screening.offensive.trade_lifecycle import (
    ExecutionMode,
    FillSource,
    TradeState,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts


def test_repository_context_manager_initializes_and_returns_repository(tmp_path):
    path = tmp_path / "context.sqlite3"
    with LedgerRepository(path, "context", 100_000) as repository:
        assert repository.path == path
        assert path.exists()


def _repo(tmp_path: Path) -> LedgerRepository:
    repo = LedgerRepository(
        tmp_path / "ledger.sqlite3", ledger_id="test", initial_cash=100_000,
        execution_costs=ExecutionCosts(version="test", commission=5.0, other_fee=30.0),
    )
    repo.initialize()
    return repo


def _plan(repo: LedgerRepository):
    return repo.create_plan(
        "000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.10, 1
    )


def _provenance(ticker: str = "000001") -> PlanProvenance:
    return PlanProvenance(
        verification_status="verified",
        source_run_id="run-20260710",
        manifest_fingerprint="manifest-fp",
        input_fingerprint="input-fp",
        ticker_cache_fingerprint=f"cache-{ticker}",
        snapshot_id="sha256:" + "7" * 64,
        setup_consumed_fingerprint=f"cache-{ticker}",
        reference_price=10.0,
        order_type="next_session_open_proxy",
        board_rule_version="ashare-board-v1",
        valid_on=date(2026, 7, 13),
        execution_cost_version="test",
        authorization="normal",
    )


def _opened(repo: LedgerRepository):
    trade = _plan(repo)
    return repo.settle_plan_at_open(
        trade.trade_id, date(2026, 7, 13), 10.0, 9.0, 11.0, False, 10.5, 9.5,
    )[0]


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
        execution_mode=ExecutionMode.BROKER_CONFIRMED,
        fill_source=FillSource.BROKER_IMPORT,
        entry_date=date(2026, 7, 13),
        raw_fill_price=10.0,
        quantity=900,
        commission=5.0,
        tax=0.0,
        slippage_cost=30.0,
    )
    assert opened.state is TradeState.OPEN
    assert repo.cash_balance() == pytest.approx(90_965.0)
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
            ExecutionMode.BROKER_CONFIRMED,
            FillSource.BROKER_IMPORT,
            date(2026, 7, 13),
            10.0,
            900,
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
            ExecutionMode.BROKER_CONFIRMED,
            FillSource.BROKER_IMPORT,
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
    with pytest.raises(ValueError, match="broker-confirmed"):
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
    assert repo.cash_balance() == pytest.approx(100_829.0)
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


def test_same_natural_key_with_different_plan_contract_is_conflict(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    args = ("000001", "btst", "v1", date(2026, 7, 10), date(2026, 7, 13))
    repo.create_plan_if_absent(*args, 0.1, 1, provenance=_provenance())
    with pytest.raises(ValueError, match="conflicting idempotent plan"):
        repo.create_plan_if_absent(*args, 0.09, 2, provenance=_provenance())


def test_verified_plan_provenance_round_trips_and_is_in_plan_event(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    provenance = _provenance()
    trade = repo.create_plan(
        "000001", "btst", "v1", date(2026, 7, 10), date(2026, 7, 13),
        0.1, 1, provenance=provenance,
    )
    assert trade.provenance == provenance
    with sqlite3.connect(repo.path) as conn:
        payload = json.loads(conn.execute(
            "SELECT payload_json FROM trade_events WHERE trade_id=? AND event_type='PLAN_CREATED'",
            (trade.trade_id,),
        ).fetchone()[0])
    assert payload["provenance"]["source_run_id"] == "run-20260710"
    assert payload["provenance"]["order_type"] == "next_session_open_proxy"


def test_verified_plan_provenance_round_trips_snapshot_identity(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    provenance = PlanProvenance(
        verification_status="verified",
        source_run_id="run-20260710",
        manifest_fingerprint="manifest-fp",
        input_fingerprint="input-fp",
        ticker_cache_fingerprint="sha256:" + "8" * 64,
        snapshot_id="sha256:" + "7" * 64,
        setup_consumed_fingerprint="sha256:" + "8" * 64,
        reference_price=10.0,
        order_type="next_session_open_proxy",
        board_rule_version="ashare-board-v1",
        valid_on=date(2026, 7, 13),
        execution_cost_version="test",
        authorization="normal",
    )
    trade = repo.create_plan(
        "000001", "btst", "v1", date(2026, 7, 10), date(2026, 7, 13),
        0.1, 1, provenance=provenance,
    )

    stored = repo.get_trade(trade.trade_id).provenance

    assert stored.snapshot_id == provenance.snapshot_id
    assert stored.setup_consumed_fingerprint == provenance.setup_consumed_fingerprint
    with sqlite3.connect(repo.path) as conn:
        payload = json.loads(conn.execute(
            "SELECT payload_json FROM trade_events WHERE trade_id=? AND event_type='PLAN_CREATED'",
            (trade.trade_id,),
        ).fetchone()[0])
    assert payload["provenance"]["snapshot_id"] == provenance.snapshot_id
    assert payload["provenance"]["setup_consumed_fingerprint"] == provenance.setup_consumed_fingerprint


def test_verified_plan_rejects_incomplete_or_mismatched_provenance(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    bad = dataclasses.replace(_provenance(), valid_on=date(2026, 7, 14))
    with pytest.raises(ValueError, match="provenance"):
        repo.create_plan(
            "000001", "btst", "v1", date(2026, 7, 10), date(2026, 7, 13),
            0.1, 1, provenance=bad,
        )


@pytest.mark.parametrize(
    ("provenance", "weight", "allowed"),
    [
        (PlanProvenance.legacy_unverified(), 0.12, False),
        (_provenance(), 0.12, False),
        (dataclasses.replace(_provenance(), authorization="btst_crisis"), 0.12, False),
        (dataclasses.replace(_provenance(), authorization="btst_risk_off"), 0.12, False),
    ],
)
def test_twelve_percent_plan_requires_verified_btst_risk_authorization(
    tmp_path: Path, provenance: PlanProvenance, weight: float, allowed: bool
) -> None:
    repo = _repo(tmp_path)
    create = lambda: repo.create_plan(
        "000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13),
        weight, 1, provenance=provenance,
    )
    if allowed:
        assert create().planned_weight == pytest.approx(0.12)
    else:
        with pytest.raises(ValueError, match="authorization evidence"):
            create()


@pytest.mark.parametrize("quantity", [1_000, 10_000])
def test_public_fill_plan_cannot_bypass_cash_and_target_weight_caps(
    tmp_path: Path, quantity: int
) -> None:
    repo = _repo(tmp_path)
    trade = _plan(repo)

    result = repo.fill_plan(
        trade.trade_id,
        ExecutionMode.BROKER_CONFIRMED,
        FillSource.BROKER_IMPORT,
        date(2026, 7, 13),
        10.0,
        quantity,
        5.0,
        0.0,
        30.0,
    )

    assert result.state is TradeState.SKIPPED
    assert repo.cash_balance() == pytest.approx(100_000)
    assert repo.count_events(trade.trade_id, "ENTRY_FILLED") == 0


def test_v1_ticker_mark_migration_preserves_unique_active_owner(tmp_path: Path) -> None:
    path = tmp_path / "v1.sqlite3"
    repo = LedgerRepository(path, "test", 100_000)
    repo.initialize()
    trade = _plan(repo)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE ledger_meta SET schema_version=1")
        conn.execute("ALTER TABLE position_marks RENAME TO position_marks_v2")
        conn.execute("CREATE TABLE position_marks (ledger_id TEXT, ticker TEXT, trade_date TEXT, close_price REAL)")
        conn.execute("INSERT INTO position_marks VALUES ('test','000001','2026-07-13',12.5)")
        conn.execute("DROP TABLE position_marks_v2")
    repo.initialize()
    assert repo.latest_position_mark(trade.trade_id, date(2026, 7, 14)) == pytest.approx(12.5)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT schema_version FROM ledger_meta").fetchone()[0] == 2


def test_v1_migration_backfills_and_enforces_nonnull_provenance(tmp_path: Path) -> None:
    path = tmp_path / "v1-provenance.sqlite3"
    repo = LedgerRepository(path, "test", 100_000)
    repo.initialize()
    trade = _plan(repo)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE ledger_meta SET schema_version=1")
        conn.execute("ALTER TABLE trades DROP COLUMN provenance_json")

    repo.initialize()

    assert repo.get_trade(trade.trade_id).provenance == PlanProvenance.legacy_unverified()
    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE trades SET provenance_json=NULL WHERE trade_id=?", (trade.trade_id,))


def test_ambiguous_v1_ticker_mark_migration_rolls_back_intact(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.sqlite3"
    repo = LedgerRepository(path, "test", 100_000)
    repo.initialize()
    _plan(repo)
    repo.create_plan("000001", "btst", "v1", date(2026, 7, 11), date(2026, 7, 13), 0.1, 2)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE ledger_meta SET schema_version=1")
        conn.execute("ALTER TABLE position_marks RENAME TO position_marks_v2")
        conn.execute("CREATE TABLE position_marks (ledger_id TEXT, ticker TEXT, trade_date TEXT, close_price REAL)")
        conn.execute("INSERT INTO position_marks VALUES ('test','000001','2026-07-13',12.5)")
        conn.execute("DROP TABLE position_marks_v2")
    with pytest.raises(ValueError, match="ambiguous legacy position mark"):
        repo.initialize()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT schema_version FROM ledger_meta").fetchone()[0] == 1
        assert {row[1] for row in conn.execute("PRAGMA table_info(position_marks)")} == {"ledger_id", "ticker", "trade_date", "close_price"}
        assert conn.execute("SELECT COUNT(*) FROM position_marks").fetchone()[0] == 1


def test_concurrent_transactional_settlement_serializes_priority_and_caps(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    plans = [repo.create_plan(
        f"0001{i:02d}", "btst", "v1", date(2026, 7, 10), date(2026, 7, 13), 0.1, i + 1
    ) for i in range(7)]
    def settle(plan):
        result = None
        for _ in range(8):
            result = repo.settle_plan_at_open(
                plan.trade_id, date(2026, 7, 13), 10.0, 9.0, 11.0, False,
                10.5, 9.5,
            )
            if result[1] != "higher_priority_pending":
                break
        return result

    with ThreadPoolExecutor(max_workers=7) as pool:
        list(pool.map(settle, reversed(plans)))
    # A deterministic ordered retry settles any thread that observed a pending predecessor.
    for plan in plans:
        settle(plan)
    opened = repo.open_trades()
    assert len(opened) == 6
    assert [trade.priority for trade in opened] == [1, 2, 3, 4, 5, 6]
    assert repo.get_trade(plans[-1].trade_id).state is TradeState.SKIPPED
    assert repo.cash_balance() >= 0
    assert sum(trade.raw_entry_price * trade.quantity for trade in opened) <= 60_000


def test_public_synthetic_fill_and_policy_overrides_are_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    plan = _plan(repo)
    with pytest.raises(ValueError, match="broker-confirmed"):
        repo.fill_plan(
            plan.trade_id, ExecutionMode.PAPER, FillSource.SYNTHETIC_OPEN,
            date(2026, 7, 13), 10.0, 900, 0.0, 0.0, 0.0,
        )
    with pytest.raises(TypeError):
        repo.settle_plan_at_open(
            plan.trade_id, date(2026, 7, 13), 10.0, 9.0, 11.0, False,
            10.5, 9.5, ExecutionCosts(version="test"),
            lot_size=1, portfolio_cap=1.0,
        )


def test_verified_synthetic_fill_with_cost_version_mismatch_is_skipped(tmp_path: Path) -> None:
    """成本口径演进后旧 provenance 的计划按 skip 处理 (cost_version_mismatch),
    绝不能 raise — raise 会在 advance_lifecycle 第一步炸掉整个命令 (崩溃死锁)."""
    repo = LedgerRepository(
        tmp_path / "mismatch.sqlite3", "test", 100_000,
        execution_costs=ExecutionCosts(version="forged-zero-cost"),
    )
    repo.initialize()
    plan = repo.create_plan(
        "000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13),
        0.10, 1, provenance=_provenance(),
    )
    _trade, outcome = repo.settle_plan_at_open(
        plan.trade_id, date(2026, 7, 13), 10.0, 9.0, 11.0, False,
        10.5, 9.5,
    )
    assert outcome == "cost_version_mismatch"
    refreshed = repo.get_trade(plan.trade_id)
    assert refreshed.state.value == "skipped"


def test_forged_crisis_provenance_cannot_authorize_twelve_percent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    forged = dataclasses.replace(_provenance(), authorization="btst_crisis")
    with pytest.raises(ValueError, match="authorization evidence"):
        repo.create_plan(
            "000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13),
            0.12, 1, provenance=forged,
        )


@pytest.mark.parametrize("authorization", ["btst_crisis", "btst_risk_off", "normal"])
def test_legacy_provenance_rejects_every_noncanonical_authorization(
    tmp_path: Path, authorization: str
) -> None:
    repo = _repo(tmp_path)
    forged = PlanProvenance("legacy_unverified", authorization=authorization)

    with pytest.raises(ValueError, match="canonical legacy provenance"):
        repo.create_plan(
            "000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13),
            0.10, 1, provenance=forged,
        )


def test_future_priority_and_reservations_do_not_block_due_session(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.create_plan(
        "000002", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 14),
        0.10, 1,
    )
    due = repo.create_plan(
        "000001", "btst_breakout", "v1", date(2026, 7, 10), date(2026, 7, 13),
        0.10, 2,
    )

    opened, reason = repo.settle_plan_at_open(
        due.trade_id, date(2026, 7, 13), 10.0, 9.0, 11.0, False,
        10.5, 9.5,
    )

    assert reason == "entry_filled"
    assert opened.state is TradeState.OPEN
