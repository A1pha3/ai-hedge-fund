"""Plan 06 Task 3 (RED): live-order adoption 证明.

v2 没有可表示的 live/ambiguous/cancel-pending order; adoption 的职责是
*证明* 这一点 (空证明), 或在发现不可归因订单时阻断 — 永不重提交.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from src.screening.offensive.v3.migration.adoption import (
    ADOPTION_BLOCKED,
    AdoptionError,
    OrderAdoptionManifest,
    adopt_live_orders,
)
from src.screening.offensive.v3.migration.inventory import capture_v2_inventory

from tests.offensive.v3.migration.helpers import (
    _checkpoint,
    _delete_wal_sidecars,
    build_populated_ledger,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


def test_empty_adoption_proof_when_v2_has_no_orders(tmp_path: Path) -> None:
    ledger_path, _ = build_populated_ledger(tmp_path / "v2")
    inventory = capture_v2_inventory(ledger_path, ledger_id="test")
    manifest = adopt_live_orders(inventory, adopted_at=NOW)
    assert isinstance(manifest, OrderAdoptionManifest)
    assert manifest.adoptions == ()
    assert manifest.source_root == inventory.source_root
    assert manifest.never_resubmits is True


def test_adoption_proof_hash_binds_source_root(tmp_path: Path) -> None:
    first, _ = build_populated_ledger(tmp_path / "a")
    second, _ = build_populated_ledger(tmp_path / "b")
    inv_a = capture_v2_inventory(first, ledger_id="test")
    inv_b = capture_v2_inventory(second, ledger_id="test")
    proof_a = adopt_live_orders(inv_a, adopted_at=NOW)
    proof_b = adopt_live_orders(inv_b, adopted_at=NOW)
    assert proof_a.manifest_hash == proof_b.manifest_hash

    from src.screening.offensive.ledger_repository import LedgerRepository

    repo = LedgerRepository(second, ledger_id="test", initial_cash=100_000)
    repo.record_position_mark("trade-open", __import__("datetime").date(2026, 7, 18), 10.7)
    del repo
    _checkpoint(second)
    _delete_wal_sidecars(second)
    inv_b2 = capture_v2_inventory(second, ledger_id="test")
    proof_b2 = adopt_live_orders(inv_b2, adopted_at=NOW)
    assert proof_b2.manifest_hash != proof_b.manifest_hash


def test_unattributed_order_rows_block_adoption(tmp_path: Path) -> None:
    ledger_path, _ = build_populated_ledger(tmp_path / "v2")
    with sqlite3.connect(ledger_path) as conn:
        conn.execute(
            "CREATE TABLE broker_live_orders (order_id TEXT PRIMARY KEY, "
            "trade_id TEXT, remaining INTEGER)"
        )
        conn.execute(
            "INSERT INTO broker_live_orders VALUES ('ord-9', NULL, 100)"
        )
    _checkpoint(ledger_path)
    _delete_wal_sidecars(ledger_path)
    # 盘点本身就拒绝不可归因风险
    from src.screening.offensive.v3.migration.inventory import (
        InventoryError,
        UNREPRESENTABLE_FACT,
    )

    with pytest.raises(InventoryError) as excinfo:
        capture_v2_inventory(ledger_path, ledger_id="test")
    assert excinfo.value.code == UNREPRESENTABLE_FACT


def test_adoption_never_resubmits_orders(tmp_path: Path) -> None:
    """adoption manifest 不含任何可提交字段 (无 broker 目标/无新指令)."""

    ledger_path, _ = build_populated_ledger(tmp_path / "v2")
    inventory = capture_v2_inventory(ledger_path, ledger_id="test")
    manifest = adopt_live_orders(inventory, adopted_at=NOW)
    payload = manifest.model_dump()
    forbidden = {"submit", "broker_order_request", "resubmit", "new_order"}
    assert forbidden.isdisjoint({key for key in payload})
    assert manifest.never_resubmits is True
