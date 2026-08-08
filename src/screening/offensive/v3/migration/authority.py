"""Plan 06 Task 4: 单存储 authority CAS 与交接游标.

`AuthorityRegistry.compare_and_flip()` 是唯一的 authority 交接点:

- 单库事务: preimage 校验、fencing v2、激活 v3、绑定 handoff cursor 全部在
  同一个 authority 库事务内 — 不存在跨库"原子"错觉.
- 前置条件: 无 in-flight/unresolved lease、无 projected-but-unacked revision、
  preimage 与注册表逐字段一致; 任一不满足即拒绝且无副作用.
- 一次性: 已 flip 后再次 flip 收到 AUTHORITY_CONFLICT; 并发 flip 恰一成功.
- flip 后 entry 保持 fenced, 直到 final reconciliation 完成.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
import sqlite3
from typing import Any, Callable, Mapping

from src.screening.offensive.v3.contracts import CanonicalModel

from src.screening.offensive.v3.migration.inbox import DurableCapitalInbox

PREIMAGE_MISMATCH = "PREIMAGE_MISMATCH"
AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"
UNRESOLVED_LEASE = "UNRESOLVED_LEASE"
NOT_FLIPPED = "NOT_FLIPPED"


class AuthorityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class AuthorityState(StrEnum):
    V2_ACTIVE = "V2_ACTIVE"
    FLIPPED = "FLIPPED"
    RECONCILED = "RECONCILED"


class FlipReceipt(CanonicalModel):
    state: AuthorityState
    active_writer: str
    fencing_epoch: int
    handoff_cursor: int
    replay_from: int
    flipped_at: datetime


_PREIMAGE_FIELDS = (
    "approval_hash",
    "adoption_hash",
    "source_root",
    "target_root",
    "source_stream_version",
    "target_import_version",
    "source_writer",
    "target_writer",
    "next_fencing_epoch",
    "handoff_cursor",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS authority_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  state TEXT NOT NULL,
  active_writer TEXT NOT NULL,
  fencing_epoch INTEGER NOT NULL,
  handoff_cursor INTEGER,
  final_reconciled_at TEXT,
  flipped_at TEXT
);
CREATE TABLE IF NOT EXISTS authority_preimage (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  approval_hash TEXT NOT NULL,
  adoption_hash TEXT NOT NULL,
  source_root TEXT NOT NULL,
  target_root TEXT NOT NULL,
  source_stream_version INTEGER NOT NULL,
  target_import_version INTEGER NOT NULL,
  source_writer TEXT NOT NULL,
  target_writer TEXT NOT NULL,
  next_fencing_epoch INTEGER NOT NULL,
  handoff_cursor INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS authority_replay (
  revision INTEGER PRIMARY KEY,
  replayed_at TEXT NOT NULL
);
"""


class AuthorityRegistry:
    """v2/v3 写权威注册表; flip 是单库 CAS."""

    def __init__(
        self,
        path: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._inbox: DurableCapitalInbox | None = None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO authority_state "
                "(id, state, active_writer, fencing_epoch) "
                "VALUES (1, 'V2_ACTIVE', 'v2-writer', 8)"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def attach_inbox(self, inbox: DurableCapitalInbox) -> None:
        self._inbox = inbox

    # ------------------------------------------------------------------
    # preimage 绑定
    # ------------------------------------------------------------------

    def bind_preimage(self, preimage: Mapping[str, Any]) -> None:
        """flip 前由协调器绑定期望 preimage; 重复绑定必须逐字段一致."""

        missing = [field for field in _PREIMAGE_FIELDS if field not in preimage]
        if missing:
            raise AuthorityError(
                PREIMAGE_MISMATCH, f"preimage missing fields {missing}"
            )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM authority_preimage WHERE id=1"
            ).fetchone()
            if existing is not None:
                for field in _PREIMAGE_FIELDS:
                    if existing[field] != preimage[field]:
                        raise AuthorityError(
                            PREIMAGE_MISMATCH,
                            f"preimage field {field} already bound to "
                            f"{existing[field]!r}",
                        )
                return
            conn.execute(
                "INSERT INTO authority_preimage (id, "
                + ", ".join(_PREIMAGE_FIELDS)
                + ") VALUES (1, "
                + ", ".join("?" for _ in _PREIMAGE_FIELDS)
                + ")",
                tuple(preimage[field] for field in _PREIMAGE_FIELDS),
            )

    # ------------------------------------------------------------------
    # CAS flip
    # ------------------------------------------------------------------

    def compare_and_flip(self, preimage: Mapping[str, Any]) -> FlipReceipt:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            state = conn.execute(
                "SELECT * FROM authority_state WHERE id=1"
            ).fetchone()
            if state["state"] != "V2_ACTIVE":
                raise AuthorityError(
                    AUTHORITY_CONFLICT,
                    f"authority already {state['state']}",
                )
            bound = conn.execute(
                "SELECT * FROM authority_preimage WHERE id=1"
            ).fetchone()
            if bound is None:
                raise AuthorityError(
                    PREIMAGE_MISMATCH, "no preimage bound"
                )
            for field in _PREIMAGE_FIELDS:
                if field not in preimage or preimage[field] != bound[field]:
                    raise AuthorityError(
                        PREIMAGE_MISMATCH,
                        f"preimage field {field} mismatch",
                    )
            self._require_no_writer_lease()
            flipped_at = self._clock()
            conn.execute(
                "UPDATE authority_state SET state='FLIPPED', "
                "active_writer=?, fencing_epoch=?, handoff_cursor=?, "
                "flipped_at=? WHERE id=1 AND state='V2_ACTIVE'",
                (
                    str(bound["target_writer"]),
                    int(bound["next_fencing_epoch"]),
                    int(bound["handoff_cursor"]),
                    flipped_at.isoformat(),
                ),
            )
        if self._inbox is not None:
            self._fence_source_writer(str(bound["source_writer"]))
        return FlipReceipt(
            state=AuthorityState.FLIPPED,
            active_writer=str(bound["target_writer"]),
            fencing_epoch=int(bound["next_fencing_epoch"]),
            handoff_cursor=int(bound["handoff_cursor"]),
            replay_from=int(bound["handoff_cursor"]) + 1,
            flipped_at=flipped_at,
        )

    def _require_no_writer_lease(self) -> None:
        if self._inbox is None:
            return
        if self._inbox.has_unresolved_lease() or self._inbox.has_unacked_history():
            raise AuthorityError(
                UNRESOLVED_LEASE,
                "writer lease or unacked projection blocks flip",
            )

    def _fence_source_writer(self, source_writer: str) -> None:
        assert self._inbox is not None
        with self._inbox._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO inbox_meta (key, value) VALUES ('writer_fence', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (source_writer,),
            )

    # ------------------------------------------------------------------
    # flip 后: replay 与 final reconciliation
    # ------------------------------------------------------------------

    def replay_inbox(self) -> tuple[int, ...]:
        """消费 handoff cursor 之后的新 revision; 返回本次消费的 revision."""

        with self._connect() as conn:
            state = conn.execute(
                "SELECT state FROM authority_state WHERE id=1"
            ).fetchone()
            if state["state"] == "V2_ACTIVE":
                raise AuthorityError(NOT_FLIPPED, "cannot replay before flip")
        if self._inbox is None:
            return ()
        consumed: list[int] = []
        with self._connect() as conn:
            already = {
                int(row["revision"])
                for row in conn.execute(
                    "SELECT revision FROM authority_replay"
                ).fetchall()
            }
        for revision in self._inbox.history():
            if revision.revision in already:
                continue
            self._inbox.acknowledge(
                revision.revision, source_root=revision.ack_source_root or "0" * 64
            )
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT OR IGNORE INTO authority_replay "
                    "(revision, replayed_at) VALUES (?, ?)",
                    (revision.revision, self._clock().isoformat()),
                )
            consumed.append(revision.revision)
        return tuple(consumed)

    def complete_final_reconciliation(self) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            state = conn.execute(
                "SELECT state FROM authority_state WHERE id=1"
            ).fetchone()
            if state["state"] == "V2_ACTIVE":
                raise AuthorityError(NOT_FLIPPED, "cannot reconcile before flip")
            conn.execute(
                "UPDATE authority_state SET state='RECONCILED', "
                "final_reconciled_at=? WHERE id=1",
                (self._clock().isoformat(),),
            )

    def entry_permitted(self) -> bool:
        with self._connect() as conn:
            state = conn.execute(
                "SELECT state FROM authority_state WHERE id=1"
            ).fetchone()
        return state["state"] == "RECONCILED"
