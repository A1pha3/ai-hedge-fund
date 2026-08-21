"""Plan 06 Task 2: durable 资本外部收件箱.

所有外部事实 (broker fill/fee、公司行动、exit、correction、manual) 先持久化
到这里, 再被当前 writer 投影进 v2/v3. 安全性质:

- append-only: 每个接受的事实获得单调 ``revision``; 崩溃不丢已接受事实.
- 幂等去重: 同 ``(source, external_id)`` 重放返回原 revision, 不产生第二行.
- out-of-order: 按接受序持久化, 不按发生时间重排, 不丢弃迟到事实.
- ACK 与 lease 状态同库存储: ``has_unresolved_lease()`` 是 flip 阻断信号.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import stat
from typing import Any, Callable, Mapping

from src.screening.offensive.v3.contracts import CanonicalModel
from src.screening.offensive.v3.orchestration.path_guards import (
    ensure_directory_components,
)

from src.screening.offensive.v3.migration.models import SourceToken


class ExternalEventKind:
    """外部事实类别 (字符串常量, 避免枚举序列化漂移)."""

    BROKER_FILL = "broker_fill"
    BROKER_FEE = "broker_fee"
    CORPORATE_ACTION = "corporate_action"
    EXIT = "exit"
    CORRECTION = "correction"
    MANUAL = "manual"

    ALL = frozenset(
        {
            BROKER_FILL,
            BROKER_FEE,
            CORPORATE_ACTION,
            EXIT,
            CORRECTION,
            MANUAL,
        }
    )


class InboxRevision(CanonicalModel):
    """一条已持久化的外部事实."""

    revision: int
    kind: str
    source: str
    external_id: str
    occurred_at: datetime
    payload: Mapping[str, Any]
    accepted_at: datetime
    acked_at: datetime | None
    ack_source_root: str | None


class AppendReceipt(CanonicalModel):
    revision: int
    deduplicated: bool


_SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox_revisions (
  revision INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  accepted_at TEXT NOT NULL,
  projected_at TEXT,
  acked_at TEXT,
  ack_source_root TEXT,
  UNIQUE(source, external_id)
);
CREATE TABLE IF NOT EXISTS inbox_lease (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  holder TEXT,
  acquired_at TEXT,
  resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS inbox_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class InboxError(ValueError):
    """Fail-closed inbox state-path rejection (code + message)."""

    def __init__(self, code: str, message: str, **_details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class DurableCapitalInbox:
    """共享 durable inbox: 单一 SQLite 存储, 与 v2/v3 库物理分离."""

    def __init__(
        self,
        path: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # 逐段创建 + 逐段验证 (第五轮): mkdir(parents=True) 穿透语义根除;
        # db 最终组件预置 symlink 时 sqlite connect 跟随读写穿 — lstat 拒。
        ensure_directory_components(
            self.path.parent,
            fail=InboxError,
            missing_code="inbox_component_missing",
            rejected_code="inbox_component_rejected",
        )
        try:
            db_mode = self.path.lstat().st_mode
        except FileNotFoundError:
            db_mode = None
        if db_mode is not None and not stat.S_ISREG(db_mode):
            raise InboxError(
                "inbox_path_rejected",
                "the inbox database must be a regular file or absent",
            )
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is not timezone.utc:
            raise ValueError("inbox clock must produce UTC instants")
        return value

    # ------------------------------------------------------------------
    # 追加与读取
    # ------------------------------------------------------------------

    def append(
        self,
        *,
        kind: str,
        source: str,
        external_id: str,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> AppendReceipt:
        if kind not in ExternalEventKind.ALL:
            raise ValueError(f"unknown external event kind: {kind!r}")
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        accepted = self._now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT revision FROM inbox_revisions WHERE source=? AND external_id=?",
                (source, external_id),
            ).fetchone()
            if existing is not None:
                return AppendReceipt(
                    revision=int(existing["revision"]), deduplicated=True
                )
            cursor = conn.execute(
                "INSERT INTO inbox_revisions "
                "(kind, source, external_id, occurred_at, payload_json, accepted_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    kind,
                    source,
                    external_id,
                    occurred_at.isoformat(),
                    body,
                    accepted.isoformat(),
                ),
            )
            return AppendReceipt(revision=int(cursor.lastrowid), deduplicated=False)

    def pending(self) -> tuple[InboxRevision, ...]:
        """未 ACK 的 revision, 按接受序 (projection 的工作队列)."""

        return self._rows("acked_at IS NULL")

    def unprojected(self) -> tuple[InboxRevision, ...]:
        """从未投影成功的 revision (flip 要求该集合为空)."""

        return self._rows("projected_at IS NULL")

    def history(self) -> tuple[InboxRevision, ...]:
        return self._rows("1=1")

    def _rows(self, where: str) -> tuple[InboxRevision, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM inbox_revisions WHERE {where} ORDER BY revision"
            ).fetchall()
        return tuple(self._to_model(row) for row in rows)

    @staticmethod
    def _to_model(row: sqlite3.Row) -> InboxRevision:
        return InboxRevision(
            revision=int(row["revision"]),
            kind=row["kind"],
            source=row["source"],
            external_id=row["external_id"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            payload=json.loads(row["payload_json"]),
            accepted_at=datetime.fromisoformat(row["accepted_at"]),
            acked_at=(
                datetime.fromisoformat(row["acked_at"]) if row["acked_at"] else None
            ),
            ack_source_root=row["ack_source_root"],
        )

    # ------------------------------------------------------------------
    # ACK
    # ------------------------------------------------------------------

    def acknowledge(self, revision: int, *, source_root: str) -> None:
        """writer 投影完成后的 ACK; 重复 ACK 必须携带同一 root."""

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT acked_at, ack_source_root FROM inbox_revisions WHERE revision=?",
                (revision,),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown inbox revision {revision}")
            if row["acked_at"] is not None:
                if row["ack_source_root"] != source_root:
                    raise ValueError(
                        f"conflicting ACK for revision {revision}: "
                        f"{row['ack_source_root']} != {source_root}"
                    )
                return
            conn.execute(
                "UPDATE inbox_revisions SET acked_at=?, ack_source_root=? "
                "WHERE revision=?",
                (self._now().isoformat(), source_root, revision),
            )

    def mark_projected(self, revision: int) -> None:
        """v2 commit 完成后、ACK 前的中间态: projected=1, acked 仍 NULL."""

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE inbox_revisions SET projected_at=? WHERE revision=? "
                "AND projected_at IS NULL",
                (self._now().isoformat(), revision),
            )

    def _force_unack_for_test(self, revision: int) -> None:
        """测试专用: 模拟 ACK 前崩溃 (v2 已 commit, ACK 未持久化)."""

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE inbox_revisions SET acked_at=NULL, ack_source_root=NULL "
                "WHERE revision=?",
                (revision,),
            )

    def force_unresolved_lease_for_test(self, holder: str = "crashed-writer") -> None:
        """测试专用: 模拟 lease 释放前崩溃."""

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO inbox_lease (id, holder, acquired_at, resolved_at) "
                "VALUES (1, ?, ?, NULL) "
                "ON CONFLICT(id) DO UPDATE SET holder=excluded.holder, "
                "acquired_at=excluded.acquired_at, resolved_at=NULL",
                (holder, self._now().isoformat()),
            )

    # ------------------------------------------------------------------
    # lease 状态 (flip 阻断信号)
    # ------------------------------------------------------------------

    def acquire_lease(self, holder: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT holder, resolved_at FROM inbox_lease WHERE id=1"
            ).fetchone()
            if row is not None and row["resolved_at"] is None:
                if row["holder"] == holder:
                    return  # 同一持有者可重入 (崩溃恢复/重试)
                from src.screening.offensive.v3.migration.compat_writer import (
                    CompatWriterError,
                    LEASE_HELD,
                )

                raise CompatWriterError(
                    LEASE_HELD, f"lease already held by {row['holder']}"
                )
            conn.execute(
                "INSERT INTO inbox_lease (id, holder, acquired_at, resolved_at) "
                "VALUES (1, ?, ?, NULL) "
                "ON CONFLICT(id) DO UPDATE SET holder=excluded.holder, "
                "acquired_at=excluded.acquired_at, resolved_at=NULL",
                (holder, self._now().isoformat()),
            )

    def release_lease(self, holder: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT holder, resolved_at FROM inbox_lease WHERE id=1"
            ).fetchone()
            if row is None or row["resolved_at"] is not None:
                return
            if row["holder"] != holder:
                raise ValueError(f"lease held by {row['holder']}, not {holder}")
            conn.execute(
                "UPDATE inbox_lease SET resolved_at=? WHERE id=1",
                (self._now().isoformat(),),
            )

    def has_unresolved_lease(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT resolved_at FROM inbox_lease WHERE id=1"
            ).fetchone()
        return row is not None and row["resolved_at"] is None

    def has_unacked_history(self) -> bool:
        """已投影但 ACK 未持久化的 revision (崩溃恢复/flip 阻断信号)."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM inbox_revisions "
                "WHERE projected_at IS NOT NULL AND acked_at IS NULL"
            ).fetchone()
        return int(row["n"]) > 0
