"""Plan 06 Task 2: legacy v2 写收敛 — CompatibilityWriter.

所有 v2 资本写都必须经此 seam: acquire lease -> 投影恰好一个 inbox revision ->
commit v2 -> ACK source token -> release lease. 安全性质:

- 单写者: 任何时刻只有一个未释放 lease; 竞争写者收到 LEASE_HELD.
- 幂等重放: v2 commit 成功但 ACK 丢失时, 重放同一 revision 由
  LedgerRepository 的幂等键吸收, 不产生第二笔现金/事件.
- fence 一次性: flip 后 writer (含已持有 lease 句柄) 永久失去写能力.
- 返回 SourceToken: 每次成功投影绑定盘点 source root, 供 CAS preimage 校验.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
from typing import Any, Callable

from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.v3.contracts import CanonicalModel

from src.screening.offensive.v3.migration.inbox import (
    DurableCapitalInbox,
    ExternalEventKind,
    InboxRevision,
)
from src.screening.offensive.v3.migration.inventory import capture_v2_inventory
from src.screening.offensive.v3.migration.models import SourceToken

LEASE_HELD = "LEASE_HELD"
UNRESOLVED_LEASE = "UNRESOLVED_LEASE"
COMPAT_WRITER_FENCED = "COMPAT_WRITER_FENCED"
ACK_PENDING = "ACK_PENDING"
UNSUPPORTED_REVISION = "UNSUPPORTED_REVISION"


class CompatWriterError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class ApplyResult(CanonicalModel):
    applied: bool
    revision: int | None
    source_token: SourceToken | None


class _Lease:
    """兼容 writer 持有的写租约句柄; fence 后任何经此句柄的操作失败."""

    def __init__(self, writer: CompatibilityWriter, holder: str) -> None:
        self._writer = writer
        self._holder = holder
        self._active = False

    def __enter__(self) -> _Lease:
        self._writer._assert_writable()
        self._writer._inbox.acquire_lease(self._holder)
        self._active = True
        return self

    def __exit__(self, *_exc: object) -> None:
        self._writer._assert_writable()
        self._writer._inbox.release_lease(self._holder)
        self._active = False

    @property
    def active(self) -> bool:
        return self._active


class CompatibilityWriter:
    """v2 资本写的唯一收敛入口 (迁移期)."""

    def __init__(
        self,
        *,
        ledger_path: Path | str,
        inbox: DurableCapitalInbox,
        ledger_id: str,
        initial_cash: float,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._ledger_path = Path(ledger_path)
        self._inbox = inbox
        self._ledger_id = ledger_id
        self._initial_cash = initial_cash
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._holder = f"compat-writer:{ledger_id}"

    # ------------------------------------------------------------------
    # 租约与 fence
    # ------------------------------------------------------------------

    def lease(self) -> _Lease:
        return _Lease(self, self._holder)

    def _assert_writable(self) -> None:
        if self._is_fenced():
            raise CompatWriterError(
                COMPAT_WRITER_FENCED,
                f"writer {self._holder} fenced; v2 is read-only for this writer",
            )

    def _is_fenced(self) -> bool:
        with self._inbox._connect() as conn:
            row = conn.execute(
                "SELECT value FROM inbox_meta WHERE key='writer_fence'"
            ).fetchone()
        return row is not None and row["value"] == self._holder

    def fence(self) -> None:
        with self._inbox._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO inbox_meta (key, value) VALUES ('writer_fence', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (self._holder,),
            )

    # ------------------------------------------------------------------
    # 投影
    # ------------------------------------------------------------------

    def apply_next(self, *, lease: _Lease | None = None) -> ApplyResult:
        """投影恰好一个 pending revision; 空 inbox 返回 applied=False."""

        self._assert_writable()
        if lease is not None:
            if not lease.active:
                raise CompatWriterError(
                    LEASE_HELD, "supplied lease is not active"
                )
        else:
            self._inbox.acquire_lease(self._holder)
        try:
            pending = self._inbox.pending()
            if not pending:
                return ApplyResult(
                    applied=False, revision=None, source_token=None
                )
            revision = pending[0]
            self._project(revision)
            self._inbox.mark_projected(revision.revision)
            token = self._capture_token()
            self._inbox.acknowledge(revision.revision, source_root=token.root)
            return ApplyResult(
                applied=True, revision=revision.revision, source_token=token
            )
        finally:
            if lease is None:
                self._inbox.release_lease(self._holder)

    def _capture_token(self) -> SourceToken:
        # 投影刚由 LedgerRepository 的短事务连接写入; 须先释放写锁并把 WAL
        # 落盘, 只读盘点才能看到最新提交.
        import contextlib
        import sqlite3
        import time

        for attempt in range(50):
            try:
                with sqlite3.connect(self._ledger_path, timeout=5.0) as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                break
            except sqlite3.OperationalError:
                if attempt == 49:
                    raise
                time.sleep(0.05)
        for suffix in ("-wal", "-shm"):
            with contextlib.suppress(FileNotFoundError):
                (
                    self._ledger_path.parent / f"{self._ledger_path.name}{suffix}"
                ).unlink()
        inventory = capture_v2_inventory(
            self._ledger_path, ledger_id=self._ledger_id
        )
        return inventory.source_token

    def _project(self, revision: InboxRevision) -> None:
        kind = revision.kind
        payload = dict(revision.payload)
        if kind == ExternalEventKind.BROKER_FILL:
            self._project_broker_fill(payload)
        else:
            raise CompatWriterError(
                UNSUPPORTED_REVISION,
                f"no projector for kind {kind!r} (revision {revision.revision})",
            )

    def _project_broker_fill(self, payload: dict[str, Any]) -> None:
        trade_id = str(payload["trade_id"])
        repo = LedgerRepository(
            self._ledger_path,
            self._ledger_id,
            self._initial_cash,
        )
        exit_date = date.fromisoformat(str(payload["exit_date"]))
        trade = repo.get_trade(trade_id)
        if trade.state == "closed":
            return  # 重放: v2 已吸收该事实
        repo.close_trade(
            trade_id,
            exit_date,
            float(Decimal(str(payload["raw_fill_price"]))),
            float(Decimal(str(payload["commission"]))),
            float(Decimal(str(payload["tax"]))),
            float(Decimal(str(payload["slippage_cost"]))),
        )

    # ------------------------------------------------------------------
    # flip 门禁
    # ------------------------------------------------------------------

    def assert_flip_ready(self) -> None:
        """flip 前置条件: 无未投影 revision、无未 ACK 投影、无 unresolved lease."""

        self._assert_writable()
        if self._inbox.unprojected():
            raise CompatWriterError(
                ACK_PENDING, "inbox still has unprojected revisions"
            )
        if self._inbox.has_unacked_history():
            raise CompatWriterError(
                UNRESOLVED_LEASE,
                "projected-but-unacked revision blocks authority flip",
            )
        if self._inbox.has_unresolved_lease():
            raise CompatWriterError(
                UNRESOLVED_LEASE,
                "unresolved writer lease blocks authority flip",
            )
