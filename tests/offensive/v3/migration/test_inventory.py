"""Plan 06 Task 1 (RED): V2 资本状态只读盘点 — 捕获测试.

锁定约束:
1. capture_v2_inventory() 只读: 捕获前后源文件 byte-identical, 且不以可写方式
   打开源数据库 (immutable=1 URI).
2. 逐项捕获守恒字段: cash(导出值+独立重算一致), positions(每 trade/ticker),
   plans(含 provenance/weight/priority), marks, valuations(NAV/peak/drawdown),
   费用合计, pending exits (state/exit_trigger/defer 计数), 事件数.
3. 逐项 content root: 每节独立哈希, 任一字段变化只翻转对应节根;
   source_root 由节根规范化合成.
4. ledger_id 绑定: 实际与期望不符即拒绝 (InventoryError/LEDGER_MISMATCH).
5. 禁止默认/取整: 未知 price 字段不得被静默视为 0.0 (unrepresentable).
6. v2 不存在可表示的 live/ambiguous/cancel-pending order, 但不可归因的
   order row (引用不存在的 trade) 必须成为 blocker, 不得丢弃.
7. 非空 ledger (plan+fill+valuation+mark) 必须全部出现在盘点中.
8. 符号链接/非普通文件路径拒绝 (InventoryError/SYMLINK).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
import os
from pathlib import Path
import sqlite3

import pytest

from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.trade_lifecycle import ExecutionMode, FillSource
from src.screening.offensive.v3.migration.inventory import (
    InventoryError,
    LEDGER_MISMATCH,
    NON_REGULAR_SOURCE,
    SYMLINK_SOURCE,
    UNREPRESENTABLE_FACT,
    V2Inventory,
    capture_v2_inventory,
)
from src.screening.offensive.v3.migration.models import SourceToken

from tests.offensive.v3.migration.helpers import (
    _checkpoint,
    _delete_wal_sidecars,
    build_populated_ledger,
)


def _rewrite_source(path: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    """在 fixture 已固化的 ledger 上注入破坏, 再重新固化 (测试专用)."""

    with sqlite3.connect(path) as conn:
        mutate(conn)
    _checkpoint(path)
    _delete_wal_sidecars(path)


def _file_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _capture(path: Path, **kwargs) -> V2Inventory:
    return capture_v2_inventory(path, ledger_id="test", **kwargs)


# ---------------------------------------------------------------------------
# 只读性: 捕获不得改变源文件, 且不得持有可写句柄
# ---------------------------------------------------------------------------


def test_capture_leaves_source_byte_identical(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)
    before = _file_bytes(path)
    inventory = _capture(path)
    assert _file_bytes(path) == before
    assert inventory.source_token.root == inventory.source_root


def test_capture_opens_source_database_read_only(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)
    observed: list[str] = []
    real_connect = sqlite3.connect

    def spy(target, *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(target, str) and target.startswith("file:"):
            observed.append(target)
        return real_connect(target, *args, **kwargs)

    original = sqlite3.connect
    sqlite3.connect = spy  # type: ignore[assignment]
    try:
        _capture(path)
    finally:
        sqlite3.connect = original  # type: ignore[assignment]
    assert observed, "capture must open the ledger via an explicit URI"
    assert all("mode=ro" in uri for uri in observed)
    assert all("immutable=1" in uri for uri in observed)


def test_capture_rejects_symlink_path(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)
    link = tmp_path / "linked.sqlite3"
    os.symlink(path, link)
    with pytest.raises(InventoryError) as excinfo:
        _capture(link)
    assert excinfo.value.code == SYMLINK_SOURCE


def test_capture_rejects_non_regular_file(tmp_path: Path) -> None:
    with pytest.raises(InventoryError) as excinfo:
        _capture(tmp_path / "missing.sqlite3")
    assert excinfo.value.code == NON_REGULAR_SOURCE


def test_capture_rejects_ledger_id_mismatch(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)
    with pytest.raises(InventoryError) as excinfo:
        capture_v2_inventory(path, ledger_id="someone-else")
    assert excinfo.value.code == LEDGER_MISMATCH


# ---------------------------------------------------------------------------
# 逐项守恒字段
# ---------------------------------------------------------------------------


def test_cash_projection_matches_independent_recompute(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)
    inventory = _capture(path)
    cash = inventory.cash
    assert cash.initial_cash == Decimal("100000")
    assert cash.event_cash_delta_sum == cash.cash_balance - cash.initial_cash
    assert cash.derivation == "initial_cash+sum(trade_events.cash_delta)"


def test_positions_itemize_open_and_exit_pending_lots(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)
    inventory = _capture(path)
    positions = {p.trade_id: p for p in inventory.positions}
    open_row = positions["trade-open"]
    assert open_row.state == "open"
    assert open_row.quantity == 900
    assert open_row.ticker == "000001"
    pending_row = positions["trade-pending"]
    assert pending_row.state == "exit_pending"
    assert pending_row.quantity == 900


def test_pending_exits_carry_trigger_and_defer_count(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)
    inventory = _capture(path)
    assert len(inventory.pending_exits) == 1
    pending = inventory.pending_exits[0]
    assert pending.trade_id == "trade-pending"
    assert pending.exit_trigger_date == date(2026, 7, 20)
    assert pending.defer_count == 1
    assert pending.state == "exit_pending"


def test_plans_preserve_weight_priority_and_provenance(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)
    inventory = _capture(path)
    assert len(inventory.plans) == 1
    plan = inventory.plans[0]
    assert plan.trade_id == "trade-planned"
    assert plan.planned_weight == Decimal("0.1")
    assert plan.priority == 3
    assert plan.signal_date == date(2026, 7, 18)
    assert plan.planned_entry_date == date(2026, 7, 21)
    assert plan.provenance_json  # provenance payload round-trips
    import json as _json

    provenance = _json.loads(plan.provenance_json)
    assert provenance["verification_status"] == "legacy_unverified"


def test_valuations_marks_and_fees_captured(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)
    inventory = _capture(path)
    valuations = {v.trade_date: v for v in inventory.valuations}
    assert valuations[date(2026, 7, 17)].nav == Decimal("107675")
    assert valuations[date(2026, 7, 17)].peak == Decimal("107675")
    assert valuations[date(2026, 7, 17)].drawdown == Decimal("0")
    marks = {(m.trade_id, m.trade_date): m for m in inventory.marks}
    assert marks[("trade-open", date(2026, 7, 17))].close_price == Decimal("10.5")
    fees = inventory.fees
    assert fees.entry_commission == Decimal("10")  # 5 + 5 across two fills
    assert fees.entry_tax == Decimal("0")
    assert fees.entry_slippage == Decimal("60")  # 30 + 30
    assert fees.exit_commission == Decimal("0")
    assert fees.exit_tax == Decimal("0")
    assert fees.exit_slippage == Decimal("0")


def test_event_and_trade_counts_are_exact(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)
    inventory = _capture(path)
    # build_populated_ledger emits: 4 PLAN_CREATED + 2 ENTRY_FILLED
    #   + 1 EXIT_PENDING + 1 EXIT_DEFERRED + 1 PLAN_SKIPPED = 9 events
    assert inventory.event_count == 9
    assert inventory.trade_count == 4
    assert inventory.meta.schema_version == 2
    assert inventory.meta.ledger_id == "test"


# ---------------------------------------------------------------------------
# 逐项 content root
# ---------------------------------------------------------------------------


def test_section_roots_change_independently(tmp_path: Path) -> None:
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first, _ = build_populated_ledger(first_dir)
    second, _ = build_populated_ledger(second_dir)
    base = _capture(first)
    variant = _capture(second)
    assert base.source_root == variant.source_root

    from src.screening.offensive.ledger_repository import LedgerRepository

    second_repo = LedgerRepository(second, ledger_id="test", initial_cash=100_000, execution_costs=ExecutionCosts(version="test"))
    second_repo.record_position_mark(
        "trade-open", date(2026, 7, 18), 10.6
    )
    del second_repo
    _checkpoint(second)
    _delete_wal_sidecars(second)
    changed = _capture(second)
    assert changed.section_roots["marks"] != base.section_roots["marks"]
    assert changed.section_roots["cash"] == base.section_roots["cash"]
    assert changed.section_roots["plans"] == base.section_roots["plans"]
    assert changed.source_root != base.source_root


def test_source_token_binds_root_and_capture_identity(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)
    inventory = _capture(path)
    token = inventory.source_token
    assert isinstance(token, SourceToken)
    assert token.root == inventory.source_root
    assert token.ledger_id == "test"
    assert token.schema_version == 2
    assert token.captured_at.tzinfo is not None
    # token hash is a pure function of its payload
    assert token.token_hash == hashlib.sha256(token.canonical_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 未知/不可表示状态 — 不得默认、不得取整
# ---------------------------------------------------------------------------


def test_unknown_cost_field_blocks_capture(tmp_path: Path) -> None:
    """真实 schema 对费用列有 NOT NULL; 用无约束同构表模拟上游损坏."""

    path, _repo = build_populated_ledger(tmp_path)

    def _mutate(conn) -> None:  # type: ignore[no-untyped-def]
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("CREATE TABLE trades_new AS SELECT * FROM trades")
        conn.execute("DROP TABLE trades")
        conn.execute("ALTER TABLE trades_new RENAME TO trades")
        conn.execute(
            "UPDATE trades SET entry_slippage = NULL WHERE trade_id = ?",
            ("trade-open",),
        )

    _rewrite_source(path, _mutate)
    with pytest.raises(InventoryError) as excinfo:
        _capture(path)
    assert excinfo.value.code == UNREPRESENTABLE_FACT
    assert "entry_slippage" in str(excinfo.value)


def test_unknown_state_string_blocks_capture(tmp_path: Path) -> None:
    """绕过 CHECK 约束: 重建同构无约束表并注入未知 state."""

    path, _repo = build_populated_ledger(tmp_path)

    def _mutate(conn) -> None:  # type: ignore[no-untyped-def]
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("CREATE TABLE trades_new AS SELECT * FROM trades")
        conn.execute("DROP TABLE trades")
        conn.execute("ALTER TABLE trades_new RENAME TO trades")
        conn.execute(
            "UPDATE trades SET state = 'mystery' WHERE trade_id = ?",
            ("trade-open",),
        )

    _rewrite_source(path, _mutate)
    with pytest.raises(InventoryError) as excinfo:
        _capture(path)
    assert excinfo.value.code == UNREPRESENTABLE_FACT


def test_orphan_order_row_becomes_unattributed_risk(tmp_path: Path) -> None:
    path, _repo = build_populated_ledger(tmp_path)

    def _mutate(conn) -> None:  # type: ignore[no-untyped-def]
        conn.execute(
            """
            CREATE TABLE live_orders (
                order_id TEXT PRIMARY KEY,
                trade_id TEXT,
                quantity INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO live_orders VALUES ('ord-1', 'no-such-trade', 100)"
        )

    _rewrite_source(path, _mutate)
    with pytest.raises(InventoryError) as excinfo:
        _capture(path)
    assert excinfo.value.code == UNREPRESENTABLE_FACT
    assert "live_orders" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 空 ledger 合法性
# ---------------------------------------------------------------------------


def test_empty_initialized_ledger_captures_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    repo = LedgerRepository(path, ledger_id="test", initial_cash=100_000, execution_costs=ExecutionCosts(version="test"))
    repo.initialize()
    del repo  # 释放写连接, 使 checkpoint 可以拿到写锁
    import contextlib
    import sqlite3 as _sqlite3

    with _sqlite3.connect(path, timeout=5.0) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    for suffix in ("-wal", "-shm"):
        with contextlib.suppress(FileNotFoundError):
            (tmp_path / f"ledger.sqlite3{suffix}").unlink()
    inventory = _capture(path)
    assert inventory.cash.cash_balance == Decimal("100000")
    assert inventory.positions == ()
    assert inventory.plans == ()
    assert inventory.pending_exits == ()
    assert inventory.event_count == 0
    assert inventory.orders == ()
