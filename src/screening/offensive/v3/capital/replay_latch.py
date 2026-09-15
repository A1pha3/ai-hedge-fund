"""Divergent replay latch across takeover for a fenced shadow-trial namespace.

Re-enable gate item 4 of the shadow-capital mutation withdrawal
(``docs/superpowers/migrations/2026-08-13-shadow-capital-mutation-withdrawal.md``):
"stable operation ids and divergent replay latching across takeover".  The
trial design spec pins the identities this module exists for: every economic
side effect belongs to a stable operation id derived from
``trial_id + arm + decision_cycle_id + shadow_line_id + event_kind``, and a
writer that resumes a window after another writer's takeover must re-drive the
*same* ids — changing ids, deleting the successful arm, or recomputing a more
favorable proposal is forbidden.  When a replayed computation disagrees with
the already-committed payload for a stable operation id, the only honest exit
is a durable, typed latch — never a silent overwrite and never a silent pass.

Scope discipline (this primitive only):

- ``attach`` composes with the fencing epoch primitive (``capital_fence.py``):
  it adopts a **fresh, already-fenced namespace only** — an initialized ledger
  carrying zero ``economic_events`` whose ``capital_fence_epochs`` table is
  present.  Unfenced or history-carrying ledgers are rejected before a single
  byte is written; a drifted latch schema is rejected, never self-healed.
- ``record`` is the per-operation consumption point.  It takes the caller's
  connection, enforces ``CapitalFence.assert_current`` *first* (a writer that
  lost the fence can record nothing), then either inserts the operation's
  first record, converges idempotently on a byte-identical replay (matching
  by payload digest — across takeover the committing epoch stays the original
  writer's), or fails closed with ``replay_divergence`` when the replayed
  digest differs.  This method never opens, commits, or rolls back a
  transaction: the latch row and the economic write it guards live and die
  inside one ``BEGIN IMMEDIATE``.
- ``latch_divergence`` durably marks a divergence the caller detected
  (``COMMITTED -> DIVERGED``, one way).  A latched operation refuses every
  later ``record`` regardless of digest, so a latched disagreement can never
  be papered over by another writer.  Equality is refused — latching is for
  disagreement, not for noise.
- Payload identity is the caller-computed sha256 of the canonical payload
  bytes (64 lowercase hex), matching the capital namespace's content-hash
  discipline; anything else is rejected before the fence is consulted.
- Nothing here touches the withdrawn mutation facades or any live production
  path.  This module is unreachable from production code until the re-enable
  operation wires it in; possessing a fence ticket confers no authority
  beyond the right to be the current writer of one database.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

import sqlalchemy as sa

from src.screening.offensive.v3.contracts import CanonicalModel
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr
from src.screening.offensive.v3.capital.fence import CapitalFence, FenceTicket

if TYPE_CHECKING:
    from src.screening.offensive.v3.capital.repository import CapitalRepository

_LATCH_TABLE = "capital_replay_latches"

_DIGEST_RE = re.compile(r"[0-9a-f]{64}")

_LATCH_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS capital_replay_latches (
    operation_id TEXT PRIMARY KEY,
    epoch INTEGER NOT NULL,
    payload_content_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('COMMITTED', 'DIVERGED')),
    recorded_wall_ms INTEGER NOT NULL,
    diverged_epoch INTEGER,
    diverged_payload_content_hash TEXT,
    diverged_wall_ms INTEGER,
    CHECK (epoch >= 1),
    CHECK (
        state <> 'DIVERGED'
        OR (
            diverged_epoch IS NOT NULL
            AND diverged_payload_content_hash IS NOT NULL
            AND diverged_wall_ms IS NOT NULL
        )
    ),
    CHECK (diverged_epoch IS NULL OR state = 'DIVERGED'),
    CHECK (
        diverged_payload_content_hash IS NULL
        OR diverged_payload_content_hash <> payload_content_hash
    ),
    FOREIGN KEY (epoch) REFERENCES capital_fence_epochs (epoch)
)
"""

_LATCH_TRIGGERS: tuple[tuple[str, str], ...] = (
    (
        "replay_latch_no_delete",
        """
CREATE TRIGGER IF NOT EXISTS replay_latch_no_delete
BEFORE DELETE ON capital_replay_latches
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'capital_replay_latches: append-only');
END
""",
    ),
    (
        "replay_latch_identity_immutable",
        """
CREATE TRIGGER IF NOT EXISTS replay_latch_identity_immutable
BEFORE UPDATE ON capital_replay_latches
FOR EACH ROW
WHEN NEW.operation_id <> OLD.operation_id
    OR NEW.epoch <> OLD.epoch
    OR NEW.payload_content_hash <> OLD.payload_content_hash
    OR NEW.recorded_wall_ms <> OLD.recorded_wall_ms
BEGIN
    SELECT RAISE(ABORT, 'capital_replay_latches: identity immutable');
END
""",
    ),
    (
        "replay_latch_divergence_irreversible",
        """
CREATE TRIGGER IF NOT EXISTS replay_latch_divergence_irreversible
BEFORE UPDATE ON capital_replay_latches
FOR EACH ROW
WHEN OLD.state = 'DIVERGED'
BEGIN
    SELECT RAISE(ABORT, 'capital_replay_latches: divergence irreversible');
END
""",
    ),
)

_EXPECTED_COLUMNS: frozenset[str] = frozenset(
    {
        "operation_id",
        "epoch",
        "payload_content_hash",
        "state",
        "recorded_wall_ms",
        "diverged_epoch",
        "diverged_payload_content_hash",
        "diverged_wall_ms",
    }
)
_EXPECTED_TRIGGER_NAMES: frozenset[str] = frozenset(
    name for name, _ in _LATCH_TRIGGERS
)


class ReplayLatchError(RuntimeError):
    """Fail-closed rejection of a latch lifecycle or consumption step."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details: Mapping[str, Any] = {
            key: value for key, value in details.items()
        }


class ReplayLatchEntry(CanonicalModel):
    """One stable operation id's durable replay state."""

    operation_id: NonEmptyStr
    epoch: int
    payload_content_hash: NonEmptyStr
    state: NonEmptyStr
    diverged_epoch: int | None = None
    diverged_payload_content_hash: str | None = None


def _wall_ms(now: datetime) -> int:
    if not isinstance(now, datetime):
        raise ReplayLatchError(
            "replay_latch_now_invalid", "the injected now must be a datetime"
        )
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ReplayLatchError(
            "replay_latch_now_naive",
            "the injected now must be timezone-aware; naive time is not a "
            "trustworthy fencing clock",
        )
    return int(now.timestamp() * 1000)


def _require_operation_id(operation_id: str) -> None:
    if not isinstance(operation_id, str) or not operation_id.strip():
        raise ReplayLatchError(
            "replay_latch_invalid_operation",
            "operation_id must be a non-empty string",
        )


def _require_digest(payload_content_hash: str) -> None:
    if not isinstance(payload_content_hash, str) or not _DIGEST_RE.fullmatch(
        payload_content_hash
    ):
        raise ReplayLatchError(
            "replay_latch_invalid_digest",
            "payload_content_hash must be lowercase sha256 hex (64 chars)",
        )


def _require_ticket(ticket: FenceTicket) -> None:
    if not isinstance(ticket, FenceTicket):
        raise ReplayLatchError(
            "replay_latch_invalid_ticket",
            "ticket must be a FenceTicket minted by CapitalFence.claim",
        )


class ReplayLatch:
    """The divergent-replay protocol over one fenced arm capital database."""

    def __init__(self, fence: CapitalFence) -> None:
        self._fence = fence

    @property
    def fence(self) -> CapitalFence:
        return self._fence

    @property
    def repository(self) -> "CapitalRepository":
        return self._fence.repository

    # -- attach ---------------------------------------------------------------

    @classmethod
    def attach(cls, fence: CapitalFence) -> "ReplayLatch":
        """Adopt a fenced namespace for replay latching, fresh namespaces only.

        Idempotent: attaching an already-attached ledger converges on the
        same schema.  Requires the fencing epoch schema to be present (attach
        the fence first) and the ledger to still carry zero economic events.
        """

        repository = fence.repository
        with repository.engine.connect() as conn:
            try:
                meta_present = _table_exists(conn, "gateway_meta")
            except sa.exc.DatabaseError:
                raise ReplayLatchError(
                    "replay_latch_requires_initialized_ledger",
                    "attach requires an initialized capital ledger; this "
                    "file is not a readable SQLite capital store",
                )
            if not meta_present:
                raise ReplayLatchError(
                    "replay_latch_requires_initialized_ledger",
                    "attach requires an initialized capital ledger "
                    "(gateway_meta missing); never create the latch schema "
                    "on a foreign or uninitialized file",
                )
            if not _table_exists(conn, "economic_events"):
                raise ReplayLatchError(
                    "replay_latch_requires_initialized_ledger",
                    "attach requires an initialized capital ledger "
                    "(economic_events missing)",
                )
            event_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM economic_events")
            ).scalar_one()
            if int(event_count) != 0:
                raise ReplayLatchError(
                    "replay_latch_requires_fresh_namespace",
                    "the replay latch protocol adopts fresh namespaces "
                    "only; this ledger already carries economic events and "
                    "no unfenced history may gain a latch",
                    economic_events=int(event_count),
                )
            if not _table_exists(conn, "capital_fence_epochs"):
                raise ReplayLatchError(
                    "replay_latch_requires_fenced_ledger",
                    "attach the fencing epoch first; the replay latch is "
                    "defined over fenced namespaces and refuses to create "
                    "its schema on an unfenced ledger",
                )
            if _table_exists(conn, _LATCH_TABLE):
                # Validate an existing latch schema before writing anything,
                # so a drifted shape is rejected with zero side effects.
                _validate_shape(conn)
        engine = repository.engine
        with engine.begin() as conn:
            if not _table_exists(conn, _LATCH_TABLE):
                conn.execute(sa.text(_LATCH_TABLE_DDL))
                for _, ddl in _LATCH_TRIGGERS:
                    conn.execute(sa.text(ddl))
        with engine.connect() as conn:
            _validate_shape(conn)
        return cls(fence)

    # -- same-transaction consumption -----------------------------------------

    def record(
        self,
        conn: sa.Connection,
        ticket: FenceTicket,
        operation_id: str,
        payload_content_hash: str,
        *,
        now: datetime,
    ) -> ReplayLatchEntry:
        """Consume the fence and record/converge one stable operation id.

        Runs on the caller's connection inside the economic write's own
        ``BEGIN IMMEDIATE``.  Fail-closed outcomes leave the latch table
        untouched: ``replay_divergence`` for a byte-different replay of a
        committed operation, ``replay_latch_latched`` once a divergence has
        been durably latched.
        """

        self._require_conn(conn)
        _require_ticket(ticket)
        _require_operation_id(operation_id)
        _require_digest(payload_content_hash)
        now_ms = _wall_ms(now)
        self._fence.assert_current(conn, ticket, now=now)
        row = conn.execute(
            sa.text(
                "SELECT epoch, payload_content_hash, state, diverged_epoch,"
                " diverged_payload_content_hash FROM capital_replay_latches"
                " WHERE operation_id = :operation_id"
            ),
            {"operation_id": operation_id},
        ).first()
        if row is None:
            conn.execute(
                sa.text(
                    "INSERT INTO capital_replay_latches (operation_id, epoch,"
                    " payload_content_hash, state, recorded_wall_ms,"
                    " diverged_epoch, diverged_payload_content_hash,"
                    " diverged_wall_ms)"
                    " VALUES (:operation_id, :epoch, :digest, 'COMMITTED',"
                    " :recorded, NULL, NULL, NULL)"
                ),
                {
                    "operation_id": operation_id,
                    "epoch": ticket.epoch,
                    "digest": payload_content_hash,
                    "recorded": now_ms,
                },
            )
            return ReplayLatchEntry(
                operation_id=operation_id,
                epoch=ticket.epoch,
                payload_content_hash=payload_content_hash,
                state="COMMITTED",
            )
        entry = _entry_from_row(operation_id, row)
        if str(entry.state) == "DIVERGED":
            raise ReplayLatchError(
                "replay_latch_latched",
                "this operation id carries a durably latched divergence;"
                " no further replay may commit over it",
                operation_id=operation_id,
                committed_epoch=int(entry.epoch),
                committed_payload_content_hash=str(entry.payload_content_hash),
                diverged_epoch=(
                    int(entry.diverged_epoch)
                    if entry.diverged_epoch is not None
                    else None
                ),
                diverged_payload_content_hash=entry.diverged_payload_content_hash,
            )
        if str(entry.payload_content_hash) != payload_content_hash:
            raise ReplayLatchError(
                "replay_divergence",
                "the replayed payload digest differs from the committed one;"
                " record the divergence explicitly instead of overwriting",
                operation_id=operation_id,
                committed_epoch=int(entry.epoch),
                committed_payload_content_hash=str(entry.payload_content_hash),
                observed_payload_content_hash=payload_content_hash,
            )
        return entry

    def latch_divergence(
        self,
        conn: sa.Connection,
        ticket: FenceTicket,
        operation_id: str,
        observed_payload_content_hash: str,
        *,
        now: datetime,
    ) -> ReplayLatchEntry:
        """Durably latch a detected divergence for one stable operation id.

        The latch is one-way: every later ``record`` on this operation id is
        refused, and no trigger or API can revive a ``DIVERGED`` row.
        """

        self._require_conn(conn)
        _require_ticket(ticket)
        _require_operation_id(operation_id)
        _require_digest(observed_payload_content_hash)
        now_ms = _wall_ms(now)
        self._fence.assert_current(conn, ticket, now=now)
        row = conn.execute(
            sa.text(
                "SELECT epoch, payload_content_hash, state, diverged_epoch,"
                " diverged_payload_content_hash FROM capital_replay_latches"
                " WHERE operation_id = :operation_id"
            ),
            {"operation_id": operation_id},
        ).first()
        if row is None:
            raise ReplayLatchError(
                "replay_latch_unknown_operation",
                "divergence can only be latched for a committed operation",
                operation_id=operation_id,
            )
        entry = _entry_from_row(operation_id, row)
        if str(entry.state) == "DIVERGED":
            raise ReplayLatchError(
                "replay_latch_already_latched",
                "the divergence for this operation id is already latched",
                operation_id=operation_id,
                committed_payload_content_hash=str(entry.payload_content_hash),
                diverged_payload_content_hash=(
                    entry.diverged_payload_content_hash
                ),
            )
        if str(entry.payload_content_hash) == observed_payload_content_hash:
            raise ReplayLatchError(
                "replay_latch_not_divergent",
                "the observed digest equals the committed digest; there is"
                " no divergence to latch",
                operation_id=operation_id,
                committed_payload_content_hash=str(entry.payload_content_hash),
            )
        conn.execute(
            sa.text(
                "UPDATE capital_replay_latches SET state = 'DIVERGED',"
                " diverged_epoch = :diverged_epoch,"
                " diverged_payload_content_hash = :diverged_digest,"
                " diverged_wall_ms = :diverged_at"
                " WHERE operation_id = :operation_id"
            ),
            {
                "diverged_epoch": ticket.epoch,
                "diverged_digest": observed_payload_content_hash,
                "diverged_at": now_ms,
                "operation_id": operation_id,
            },
        )
        return ReplayLatchEntry(
            operation_id=operation_id,
            epoch=int(entry.epoch),
            payload_content_hash=str(entry.payload_content_hash),
            state="DIVERGED",
            diverged_epoch=ticket.epoch,
            diverged_payload_content_hash=observed_payload_content_hash,
        )

    # -- plumbing ---------------------------------------------------------------

    def _require_conn(self, conn: sa.Connection) -> None:
        if not isinstance(conn, sa.Connection):
            raise TypeError(
                "latch operations require the caller's sqlalchemy"
                " Connection; they must run inside the economic write's own"
                " transaction"
            )


# -- module-level helpers -----------------------------------------------------


def _table_exists(conn: sa.Connection, name: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"
        ),
        {"name": name},
    ).first()
    return row is not None


def _entry_from_row(operation_id: str, row: Any) -> ReplayLatchEntry:
    return ReplayLatchEntry(
        operation_id=operation_id,
        epoch=int(row.epoch),
        payload_content_hash=str(row.payload_content_hash),
        state=str(row.state),
        diverged_epoch=(
            int(row.diverged_epoch) if row.diverged_epoch is not None else None
        ),
        diverged_payload_content_hash=(
            str(row.diverged_payload_content_hash)
            if row.diverged_payload_content_hash is not None
            else None
        ),
    )


def _validate_shape(conn: sa.Connection) -> None:
    columns = {
        str(row.name)
        for row in conn.execute(
            sa.text(f"PRAGMA table_info({_LATCH_TABLE})")
        ).all()
    }
    if columns != _EXPECTED_COLUMNS:
        raise ReplayLatchError(
            "replay_latch_schema_drift",
            "the capital_replay_latches table does not match the latch "
            "contract; refusing to operate on a drifted shape",
            observed_columns=sorted(columns),
        )
    triggers = {
        str(row.name)
        for row in conn.execute(
            sa.text(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                " AND name IN ("
                + ", ".join(f"'{name}'" for name in sorted(_EXPECTED_TRIGGER_NAMES))
                + ")"
            )
        ).all()
    }
    if triggers != _EXPECTED_TRIGGER_NAMES:
        raise ReplayLatchError(
            "replay_latch_schema_drift",
            "latch enforcement triggers are missing or renamed; the "
            "append-only and divergence-irreversibility contract is not "
            "enforced on this ledger",
            observed_triggers=sorted(triggers),
        )


__all__ = [
    "ReplayLatch",
    "ReplayLatchEntry",
    "ReplayLatchError",
]
