"""Plan 06 Task 3: 迁移协调器状态机.

DISCOVERED → V2_NEW_RISK_FROZEN → ORDERS_DRAINED_OR_ADOPTED →
CAPITAL_RECONCILED → V3_IMPORT_PREPARED → CONSERVATION_VERIFIED →
V2_CAPITAL_WRITE_FENCED_AND_AUTHORITY_FLIPPED → V3_INBOX_REPLAYED → V2_READ_ONLY

安全性质:
- 合法转换严格线性; 跳步/回退/终态后动作均 ILLEGAL_TRANSITION.
- 每个 advance 幂等: 重复进入同一状态返回首次记录, 不产生第二份.
- 状态持久化于独立 state 库; 崩溃后重启可继续.
- 同一 migration id 绑定首次观察到的 source root; 不同 root 即 ROOT_CONFLICT.
- prepared import 非可执行: 仅携带 target projection + 绑定哈希, 无写能力.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
import sqlite3
import stat
from typing import Any, Callable, Mapping

from src.screening.offensive.v3.contracts import CanonicalModel
from src.screening.offensive.v3.orchestration.path_guards import (
    ensure_directory_components,
)

from src.screening.offensive.v3.migration.inventory import capture_v2_inventory

ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
ROOT_CONFLICT = "ROOT_CONFLICT"
NOT_PREPARED = "NOT_PREPARED"


class MigrationError(ValueError):
    def __init__(self, code: str, message: str, **_details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class MigrationState(StrEnum):
    DISCOVERED = "DISCOVERED"
    V2_NEW_RISK_FROZEN = "V2_NEW_RISK_FROZEN"
    ORDERS_DRAINED_OR_ADOPTED = "ORDERS_DRAINED_OR_ADOPTED"
    CAPITAL_RECONCILED = "CAPITAL_RECONCILED"
    V3_IMPORT_PREPARED = "V3_IMPORT_PREPARED"
    CONSERVATION_VERIFIED = "CONSERVATION_VERIFIED"
    V2_CAPITAL_WRITE_FENCED_AND_AUTHORITY_FLIPPED = (
        "V2_CAPITAL_WRITE_FENCED_AND_AUTHORITY_FLIPPED"
    )
    V3_INBOX_REPLAYED = "V3_INBOX_REPLAYED"
    V2_READ_ONLY = "V2_READ_ONLY"


_CHAIN: tuple[MigrationState, ...] = (
    MigrationState.DISCOVERED,
    MigrationState.V2_NEW_RISK_FROZEN,
    MigrationState.ORDERS_DRAINED_OR_ADOPTED,
    MigrationState.CAPITAL_RECONCILED,
    MigrationState.V3_IMPORT_PREPARED,
    MigrationState.CONSERVATION_VERIFIED,
    MigrationState.V2_CAPITAL_WRITE_FENCED_AND_AUTHORITY_FLIPPED,
    MigrationState.V3_INBOX_REPLAYED,
    MigrationState.V2_READ_ONLY,
)
_INDEX = {state: position for position, state in enumerate(_CHAIN)}


class StateRecord(CanonicalModel):
    state: str
    entered_at: datetime
    source_root: str


class PreparedImport(CanonicalModel):
    """V3_IMPORT_PREPARED 的产物: 绑定 source root 的非可执行目标投影."""

    source_root: str
    target_projection: Mapping[str, Any]
    prepared_at: datetime
    executable: bool = False


_SCHEMA = """
CREATE TABLE IF NOT EXISTS migration_states (
  migration_id TEXT NOT NULL,
  state TEXT NOT NULL,
  entered_at TEXT NOT NULL,
  source_root TEXT NOT NULL,
  PRIMARY KEY (migration_id, state)
);
CREATE TABLE IF NOT EXISTS migration_meta (
  migration_id TEXT PRIMARY KEY,
  ledger_id TEXT NOT NULL,
  source_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS migration_prepared (
  migration_id TEXT PRIMARY KEY,
  source_root TEXT NOT NULL,
  projection_json TEXT NOT NULL,
  prepared_at TEXT NOT NULL
);
"""


class MigrationCoordinator:
    """线性迁移状态机; 每个迁移 id 一条链."""

    def __init__(
        self,
        *,
        state_path: Path | str,
        migration_id: str,
        source_path: Path | str,
        ledger_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._state_path = Path(state_path)
        self._migration_id = migration_id
        self._source_path = Path(source_path)
        self._ledger_id = ledger_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # 逐段创建 + 逐段验证 (第五轮): 线性迁移状态机库不得经预置
        # symlink 在 root 外创建/读写; db 最终组件 symlink 同拒。
        ensure_directory_components(
            self._state_path.parent,
            fail=MigrationError,
            missing_code="state_component_missing",
            rejected_code="state_component_rejected",
        )
        try:
            db_mode = self._state_path.lstat().st_mode
        except FileNotFoundError:
            db_mode = None
        if db_mode is not None and not stat.S_ISREG(db_mode):
            raise MigrationError(
                "state_path_rejected",
                "the migration state database must be a regular file or absent",
            )
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO migration_meta "
                "(migration_id, ledger_id, source_path, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    migration_id,
                    ledger_id,
                    str(self._source_path),
                    self._clock().isoformat(),
                ),
            )
            seeded = conn.execute(
                "SELECT 1 FROM migration_states WHERE migration_id=? LIMIT 1",
                (migration_id,),
            ).fetchone()
        if seeded is None:
            self.advance(MigrationState.DISCOVERED)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._state_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def current_state(self) -> MigrationState:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state FROM migration_states WHERE migration_id=? "
                "ORDER BY rowid DESC LIMIT 1",
                (self._migration_id,),
            ).fetchone()
        if row is None:
            return MigrationState.DISCOVERED
        return MigrationState(row["state"])

    def _source_root_or_pending(self) -> str:
        """源尚不存在 (迁移前) 时返回全零根, 不做 InventoryError 硬失败."""

        if not self._source_path.exists():
            return "0" * 64
        return capture_v2_inventory(
            self._source_path, ledger_id=self._ledger_id
        ).source_root

    def advance(self, target: MigrationState) -> StateRecord:
        current = self.current_state()
        if _INDEX[target] < _INDEX[current]:
            raise MigrationError(
                ILLEGAL_TRANSITION,
                f"cannot backtrack {current} -> {target}",
            )
        if _INDEX[target] > _INDEX[current] + 1:
            raise MigrationError(
                ILLEGAL_TRANSITION,
                f"cannot skip {current} -> {target}",
            )
        root = self._source_root_or_pending()
        entered = self._clock()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            bound = conn.execute(
                "SELECT source_root FROM migration_states WHERE migration_id=? "
                "ORDER BY rowid LIMIT 1",
                (self._migration_id,),
            ).fetchone()
            if bound is not None and bound["source_root"] != root:
                raise MigrationError(
                    ROOT_CONFLICT,
                    f"migration {self._migration_id} bound to root "
                    f"{bound['source_root']}, observed {root}",
                )
            existing = conn.execute(
                "SELECT state, entered_at, source_root FROM migration_states "
                "WHERE migration_id=? AND state=?",
                (self._migration_id, target.value),
            ).fetchone()
            if existing is not None:
                if existing["source_root"] != root and _INDEX[target] == _INDEX[current]:
                    # 同状态重复进入但 root 已变 — 幂等只接受同一 root
                    raise MigrationError(
                        ROOT_CONFLICT,
                        f"state {target} already entered under root "
                        f"{existing['source_root']}",
                    )
                return StateRecord(
                    state=existing["state"],
                    entered_at=datetime.fromisoformat(existing["entered_at"]),
                    source_root=existing["source_root"],
                )
            conn.execute(
                "INSERT INTO migration_states "
                "(migration_id, state, entered_at, source_root) VALUES (?, ?, ?, ?)",
                (self._migration_id, target.value, entered.isoformat(), root),
            )
        if target is MigrationState.V3_IMPORT_PREPARED:
            self._prepare_import(root, entered)
        return StateRecord(state=target.value, entered_at=entered, source_root=root)

    # ------------------------------------------------------------------
    # prepared import
    # ------------------------------------------------------------------

    def _prepare_import(self, source_root: str, prepared_at: datetime) -> None:
        import json

        inventory = capture_v2_inventory(
            self._source_path, ledger_id=self._ledger_id
        )
        projection = _target_projection(inventory)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO migration_prepared "
                "(migration_id, source_root, projection_json, prepared_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    self._migration_id,
                    source_root,
                    json.dumps(projection, sort_keys=True),
                    prepared_at.isoformat(),
                ),
            )

    def prepared_import(self) -> PreparedImport:
        import json

        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_root, projection_json, prepared_at "
                "FROM migration_prepared WHERE migration_id=?",
                (self._migration_id,),
            ).fetchone()
        if row is None:
            raise MigrationError(
                NOT_PREPARED,
                f"migration {self._migration_id} has no prepared import",
            )
        return PreparedImport(
            source_root=row["source_root"],
            target_projection=json.loads(row["projection_json"]),
            prepared_at=datetime.fromisoformat(row["prepared_at"]),
            executable=False,
        )


def _target_projection(inventory: Any) -> dict[str, Any]:
    """v3 目标投影: 逐项守恒所需的全部字段 (Decimal → 字符串以便 JSON)."""

    return {
        "cash": {
            "initial_cash": str(inventory.cash.initial_cash),
            "event_cash_delta_sum": str(inventory.cash.event_cash_delta_sum),
            "cash_balance": str(inventory.cash.cash_balance),
        },
        "positions": [
            {
                "trade_id": p.trade_id,
                "ticker": p.ticker,
                "state": p.state,
                "quantity": p.quantity,
                "raw_entry_price": (
                    str(p.raw_entry_price) if p.raw_entry_price is not None else None
                ),
            }
            for p in inventory.positions
        ],
        "plans": [
            {
                "trade_id": p.trade_id,
                "ticker": p.ticker,
                "planned_weight": str(p.planned_weight),
                "priority": p.priority,
            }
            for p in inventory.plans
        ],
        "pending_exits": [
            {
                "trade_id": p.trade_id,
                "exit_trigger_date": (
                    p.exit_trigger_date.isoformat()
                    if p.exit_trigger_date
                    else None
                ),
                "defer_count": p.defer_count,
            }
            for p in inventory.pending_exits
        ],
        "fees": {
            "entry_commission": str(inventory.fees.entry_commission),
            "entry_tax": str(inventory.fees.entry_tax),
            "entry_slippage": str(inventory.fees.entry_slippage),
            "exit_commission": str(inventory.fees.exit_commission),
            "exit_tax": str(inventory.fees.exit_tax),
            "exit_slippage": str(inventory.fees.exit_slippage),
        },
        "counts": {
            "event_count": inventory.event_count,
            "trade_count": inventory.trade_count,
        },
    }
