"""Plan 06 Task 3 (RED): 迁移状态机与逐项守恒.

锁定约束:
1. 合法转换链 DISCOVERED→...→V2_READ_ONLY 逐步可达; 跳步/回退/终态后动作拒绝.
2. 崩溃恢复: 每个 commit 点之后重启, 状态可继续; 同一 migration id 不同
   source root 即冲突拒绝.
3. 每步幂等: 重复执行同一步返回既有记录, 不产生第二份.
4. conservation 逐项: 只比总 NAV 不够 — 任一字段 (cash/position/fee/plan/...)
   漂移即失败并点名 section.
5. adoption: v2 无 live order 时为空证明; 发现不可归因 order 即阻断;
   adoption 永不重提交订单.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.v3.migration.conservation import (
    CONSERVATION_MISMATCH,
    ConservationError,
    verify_conservation,
)
from src.screening.offensive.v3.migration.coordinator import (
    ILLEGAL_TRANSITION,
    MigrationCoordinator,
    MigrationError,
    MigrationState,
    ROOT_CONFLICT,
)
from src.screening.offensive.v3.migration.inventory import capture_v2_inventory

from tests.offensive.v3.migration.helpers import build_populated_ledger

UTC = timezone.utc
NOW = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


def _stack(tmp_path: Path):  # type: ignore[no-untyped-def]
    ledger_path, _ = build_populated_ledger(tmp_path / "v2")
    coordinator = MigrationCoordinator(
        state_path=tmp_path / "migration.sqlite3",
        migration_id="mig-1",
        source_path=ledger_path,
        ledger_id="test",
    )
    return ledger_path, coordinator


def _drive_to(coordinator: MigrationCoordinator, target: MigrationState):
    order = [
        MigrationState.DISCOVERED,
        MigrationState.V2_NEW_RISK_FROZEN,
        MigrationState.ORDERS_DRAINED_OR_ADOPTED,
        MigrationState.CAPITAL_RECONCILED,
        MigrationState.V3_IMPORT_PREPARED,
        MigrationState.CONSERVATION_VERIFIED,
    ]
    for state in order:
        coordinator.advance(state)
        if state is target:
            return


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------


def test_legal_chain_walks_through_all_states(tmp_path: Path) -> None:
    _ledger_path, coordinator = _stack(tmp_path)
    assert coordinator.current_state() is MigrationState.DISCOVERED
    _drive_to(coordinator, MigrationState.CONSERVATION_VERIFIED)
    assert coordinator.current_state() is MigrationState.CONSERVATION_VERIFIED


def test_skipping_a_state_is_rejected(tmp_path: Path) -> None:
    _ledger_path, coordinator = _stack(tmp_path)
    with pytest.raises(MigrationError) as excinfo:
        coordinator.advance(MigrationState.CAPITAL_RECONCILED)
    assert excinfo.value.code == ILLEGAL_TRANSITION


def test_backtracking_is_rejected(tmp_path: Path) -> None:
    _ledger_path, coordinator = _stack(tmp_path)
    _drive_to(coordinator, MigrationState.ORDERS_DRAINED_OR_ADOPTED)
    with pytest.raises(MigrationError) as excinfo:
        coordinator.advance(MigrationState.V2_NEW_RISK_FROZEN)
    assert excinfo.value.code == ILLEGAL_TRANSITION


def test_each_advance_is_idempotent(tmp_path: Path) -> None:
    _ledger_path, coordinator = _stack(tmp_path)
    first = coordinator.advance(MigrationState.V2_NEW_RISK_FROZEN)
    again = coordinator.advance(MigrationState.V2_NEW_RISK_FROZEN)
    assert first.entered_at == again.entered_at
    assert coordinator.current_state() is MigrationState.V2_NEW_RISK_FROZEN


def test_state_survives_restart(tmp_path: Path) -> None:
    ledger_path, coordinator = _stack(tmp_path)
    _drive_to(coordinator, MigrationState.ORDERS_DRAINED_OR_ADOPTED)
    restarted = MigrationCoordinator(
        state_path=tmp_path / "migration.sqlite3",
        migration_id="mig-1",
        source_path=ledger_path,
        ledger_id="test",
    )
    assert restarted.current_state() is MigrationState.ORDERS_DRAINED_OR_ADOPTED
    restarted.advance(MigrationState.CAPITAL_RECONCILED)
    assert restarted.current_state() is MigrationState.CAPITAL_RECONCILED


def test_same_migration_id_with_different_root_conflicts(tmp_path: Path) -> None:
    ledger_path, coordinator = _stack(tmp_path)
    coordinator.advance(MigrationState.V2_NEW_RISK_FROZEN)
    other_dir = tmp_path / "other"
    other_path, _ = build_populated_ledger(other_dir)
    from src.screening.offensive.ledger_repository import LedgerRepository

    repo = LedgerRepository(other_path, ledger_id="test", initial_cash=100_000, execution_costs=ExecutionCosts(version="test"))
    repo.record_position_mark("trade-open", __import__("datetime").date(2026, 7, 18), 10.9)
    del repo
    from tests.offensive.v3.migration.helpers import _checkpoint, _delete_wal_sidecars

    _checkpoint(other_path)
    _delete_wal_sidecars(other_path)
    rival = MigrationCoordinator(
        state_path=tmp_path / "migration.sqlite3",
        migration_id="mig-1",
        source_path=other_path,
        ledger_id="test",
    )
    with pytest.raises(MigrationError) as excinfo:
        rival.advance(MigrationState.ORDERS_DRAINED_OR_ADOPTED)
    assert excinfo.value.code == ROOT_CONFLICT


# ---------------------------------------------------------------------------
# conservation
# ---------------------------------------------------------------------------


def test_conservation_passes_on_identical_projection(tmp_path: Path) -> None:
    ledger_path, coordinator = _stack(tmp_path)
    _drive_to(coordinator, MigrationState.V3_IMPORT_PREPARED)
    prepared = coordinator.prepared_import()
    source = capture_v2_inventory(ledger_path, ledger_id="test")
    proof = verify_conservation(source, prepared.target_projection)
    assert proof.verified_sections
    coordinator.advance(MigrationState.CONSERVATION_VERIFIED)


def test_conservation_names_drifting_section(tmp_path: Path) -> None:
    ledger_path, coordinator = _stack(tmp_path)
    _drive_to(coordinator, MigrationState.V3_IMPORT_PREPARED)
    prepared = coordinator.prepared_import()
    tampered = dict(prepared.target_projection)
    cash = dict(tampered["cash"])
    cash["cash_balance"] = "1"  # 漂移
    tampered["cash"] = cash
    source = capture_v2_inventory(ledger_path, ledger_id="test")
    with pytest.raises(ConservationError) as excinfo:
        verify_conservation(source, tampered)
    assert excinfo.value.code == CONSERVATION_MISMATCH
    assert "cash" in str(excinfo.value)


def test_conservation_requires_itemized_sections(tmp_path: Path) -> None:
    ledger_path, coordinator = _stack(tmp_path)
    _drive_to(coordinator, MigrationState.V3_IMPORT_PREPARED)
    source = capture_v2_inventory(ledger_path, ledger_id="test")
    with pytest.raises(ConservationError):
        verify_conservation(source, {"nav_only": "107675"})


def test_prepared_import_is_non_executable_and_bound(tmp_path: Path) -> None:
    ledger_path, coordinator = _stack(tmp_path)
    _drive_to(coordinator, MigrationState.V3_IMPORT_PREPARED)
    prepared = coordinator.prepared_import()
    assert prepared.executable is False
    assert prepared.source_root == capture_v2_inventory(
        ledger_path, ledger_id="test"
    ).source_root
