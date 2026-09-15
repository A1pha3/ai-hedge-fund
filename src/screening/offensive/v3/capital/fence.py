"""Capital-local writer fencing epoch for a fresh shadow-trial namespace.

Re-enable gate items 1-3 of the shadow-capital mutation withdrawal
(``docs/superpowers/migrations/2026-08-13-shadow-capital-mutation-withdrawal.md``):
a monotone fencing epoch in each arm capital database, atomic
claim/renew/expiry/takeover bound to a writer identity, and a same-transaction
consumption point for economic writes. The trial design spec pins the
discipline this module exists for: every capital mutation must validate and
consume the current fence inside the same local transaction as its economic
event; a decision-store lease check followed by a capital write is not a
substitute, and the two arm databases never pretend to form one transaction.

Scope discipline (this primitive only):

- ``attach`` accepts a **fresh namespace only** — a ledger with zero
  ``economic_events``. Legacy or live ledgers are rejected
  (``fence_namespace_not_fresh``), implementing re-enable gate item 7: no
  unfenced rows are promoted or silently adopted. The freshness and
  schema-presence checks run before any DDL, so every rejection path leaves
  the ledger byte-identical.
- The ``capital_fence_epochs`` table is module-owned here and *not* part of
  the versioned ledger schema yet: folding it into the Alembic chain belongs
  to the re-enable operation that first wires fenced writers, so this
  primitive never forces a schema migration of the live production arms.
  Epoch monotonicity, identity immutability, terminal-state irreversibility,
  and append-only semantics are enforced by database triggers, not caller
  cooperation.
- Expiry is a derived predicate over the injected clock, never a background
  mutation: an expired lease stays ``ACTIVE`` in the table until ``takeover``
  supersedes it. ``claim`` refuses only an *unexpired* active lease; a new
  writer takes over a live writer through ``takeover``, never through
  ``claim``.
- ``assert_current`` is the per-economic-write consumption point. It takes
  the caller's connection and never opens a transaction of its own, so the
  check and the economic write live and die inside one ``BEGIN IMMEDIATE``;
  a writer superseded before its transaction even starts cannot pass.
- Nothing here touches the withdrawn mutation facades
  (``execution.shadow_proxy``), the gateway's ``gateway_meta.writer_fencing_epoch``
  sentinel (a Governance Control Plane surface, not a namespace-local lease),
  or any live production path. This module is unreachable from production
  code until the re-enable operation wires it in; possessing a ticket confers
  no authority beyond the right to be the current writer of one database.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from src.screening.offensive.v3.contracts import CanonicalModel
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr

if TYPE_CHECKING:
    from src.screening.offensive.v3.capital.repository import CapitalRepository

_FENCE_TABLE = "capital_fence_epochs"

_FENCE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS capital_fence_epochs (
    epoch INTEGER PRIMARY KEY,
    writer_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'SUPERSEDED', 'RELEASED')),
    claimed_wall_ms INTEGER NOT NULL,
    expires_wall_ms INTEGER NOT NULL,
    superseded_by_epoch INTEGER,
    CHECK (epoch >= 1),
    CHECK (superseded_by_epoch IS NULL OR superseded_by_epoch > epoch),
    CHECK (expires_wall_ms >= claimed_wall_ms)
)
"""

_FENCE_TRIGGERS: tuple[tuple[str, str], ...] = (
    (
        "fence_epoch_monotone",
        """
CREATE TRIGGER IF NOT EXISTS fence_epoch_monotone
BEFORE INSERT ON capital_fence_epochs
FOR EACH ROW
WHEN NEW.epoch <= (SELECT COALESCE(MAX(epoch), 0) FROM capital_fence_epochs)
BEGIN
    SELECT RAISE(ABORT, 'capital_fence_epochs: epoch not monotone');
END
""",
    ),
    (
        "fence_identity_immutable",
        """
CREATE TRIGGER IF NOT EXISTS fence_identity_immutable
BEFORE UPDATE ON capital_fence_epochs
FOR EACH ROW
WHEN NEW.epoch <> OLD.epoch
    OR NEW.writer_id <> OLD.writer_id
    OR NEW.claimed_wall_ms <> OLD.claimed_wall_ms
BEGIN
    SELECT RAISE(ABORT, 'capital_fence_epochs: identity immutable');
END
""",
    ),
    (
        "fence_terminal_irreversible",
        """
CREATE TRIGGER IF NOT EXISTS fence_terminal_irreversible
BEFORE UPDATE ON capital_fence_epochs
FOR EACH ROW
WHEN OLD.state <> 'ACTIVE'
BEGIN
    SELECT RAISE(ABORT, 'capital_fence_epochs: terminal state immutable');
END
""",
    ),
    (
        "fence_no_delete",
        """
CREATE TRIGGER IF NOT EXISTS fence_no_delete
BEFORE DELETE ON capital_fence_epochs
BEGIN
    SELECT RAISE(ABORT, 'capital_fence_epochs: append-only');
END
""",
    ),
)

_EXPECTED_COLUMNS: frozenset[str] = frozenset(
    {
        "epoch",
        "writer_id",
        "state",
        "claimed_wall_ms",
        "expires_wall_ms",
        "superseded_by_epoch",
    }
)
_EXPECTED_TRIGGER_NAMES: frozenset[str] = frozenset(
    name for name, _ in _FENCE_TRIGGERS
)


class CapitalFenceError(RuntimeError):
    """Fail-closed rejection of a fencing lifecycle or consumption step."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details: Mapping[str, Any] = {
            key: value for key, value in details.items()
        }


class FenceTicket(CanonicalModel):
    """One writer's proof of fence ownership at one epoch."""

    epoch: int
    writer_id: NonEmptyStr
    expires_wall_ms: int


def _wall_ms(now: datetime) -> int:
    if not isinstance(now, datetime):
        raise CapitalFenceError(
            "fence_now_invalid", "the injected now must be a datetime"
        )
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise CapitalFenceError(
            "fence_now_naive",
            "the injected now must be timezone-aware; naive time is not a "
            "trustworthy fencing clock",
        )
    return int(now.timestamp() * 1000)


def _require_writer(writer_id: str) -> None:
    if not isinstance(writer_id, str) or not writer_id.strip():
        raise CapitalFenceError(
            "fence_invalid_writer", "writer_id must be a non-empty string"
        )


def _require_lease(lease_seconds: int) -> int:
    if (
        type(lease_seconds) is not int
        or isinstance(lease_seconds, bool)
        or lease_seconds <= 0
    ):
        raise CapitalFenceError(
            "fence_invalid_lease",
            "lease_seconds must be a positive integer",
        )
    return lease_seconds * 1000


class CapitalFence:
    """The fencing epoch protocol for one fresh arm capital database."""

    def __init__(self, repository: "CapitalRepository") -> None:
        self._repository = repository

    @property
    def repository(self) -> "CapitalRepository":
        return self._repository

    # -- attach ---------------------------------------------------------------

    @classmethod
    def attach(cls, repository: "CapitalRepository") -> "CapitalFence":
        """Adopt this ledger as a fenced namespace, fresh namespaces only.

        Idempotent: attaching an already-attached fresh ledger converges on
        the same schema. A ledger carrying any economic event is rejected
        before a single byte is written to it.
        """

        with repository.engine.connect() as conn:
            try:
                meta_present = _table_exists(conn, "gateway_meta")
            except sa.exc.DatabaseError:
                # A foreign or corrupted file is not a fence namespace; the
                # probe is read-only, so rejection leaves it byte-identical.
                raise CapitalFenceError(
                    "fence_requires_initialized_ledger",
                    "attach requires an initialized capital ledger; this "
                    "file is not a readable SQLite capital store",
                )
            if not meta_present:
                raise CapitalFenceError(
                    "fence_requires_initialized_ledger",
                    "attach requires an initialized capital ledger "
                    "(gateway_meta missing); never create the fence schema "
                    "on a foreign or uninitialized file",
                )
            if not _table_exists(conn, "economic_events"):
                raise CapitalFenceError(
                    "fence_requires_initialized_ledger",
                    "attach requires an initialized capital ledger "
                    "(economic_events missing)",
                )
            event_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM economic_events")
            ).scalar_one()
            if int(event_count) != 0:
                raise CapitalFenceError(
                    "fence_namespace_not_fresh",
                    "the fencing epoch protocol adopts fresh namespaces "
                    "only; this ledger already carries economic events and "
                    "no unfenced history may be promoted under a fence",
                    economic_events=int(event_count),
                )
            table_present = _table_exists(conn, _FENCE_TABLE)
            if table_present:
                # Validate an existing fence schema before writing anything,
                # so a drifted shape is rejected with zero side effects.
                _validate_shape(conn)
        engine = repository.engine
        with engine.begin() as conn:
            if not _table_exists(conn, _FENCE_TABLE):
                conn.execute(sa.text(_FENCE_TABLE_DDL))
                for _, ddl in _FENCE_TRIGGERS:
                    conn.execute(sa.text(ddl))
        with engine.connect() as conn:
            _validate_shape(conn)
        return cls(repository)

    # -- lifecycle ------------------------------------------------------------

    def claim(
        self, writer_id: str, *, now: datetime, lease_seconds: int
    ) -> FenceTicket:
        """Mint the next epoch for ``writer_id`` when the fence is quiet.

        Fails closed while any *unexpired* lease is ACTIVE — including the
        caller's own; a crashed writer resumes through ``renew`` and a live
        writer is displaced only through ``takeover``. Expired ACTIVE rows
        stay in the table until a takeover supersedes them.
        """

        _require_writer(writer_id)
        lease_ms = _require_lease(lease_seconds)
        now_ms = _wall_ms(now)

        def operation(conn: sa.Connection) -> FenceTicket:
            for row in conn.execute(
                sa.text(
                    "SELECT epoch, writer_id, expires_wall_ms FROM"
                    " capital_fence_epochs WHERE state = 'ACTIVE'"
                )
            ).all():
                if now_ms < int(row.expires_wall_ms):
                    raise CapitalFenceError(
                        "fence_already_active",
                        "an unexpired lease holds the fence; resume through"
                        " renew or displace through takeover",
                        active_epoch=int(row.epoch),
                        active_writer_id=str(row.writer_id),
                        active_expires_wall_ms=int(row.expires_wall_ms),
                    )
            return _insert_active(conn, writer_id, now_ms, lease_ms)

        return self._write(operation)

    def renew(
        self, ticket: FenceTicket, *, now: datetime, lease_seconds: int
    ) -> FenceTicket:
        """Extend the caller's lease, failing closed once the fence is lost."""

        lease_ms = _require_lease(lease_seconds)
        now_ms = _wall_ms(now)

        def operation(conn: sa.Connection) -> FenceTicket:
            _assert_row(conn, ticket, now_ms)
            expires = now_ms + lease_ms
            conn.execute(
                sa.text(
                    "UPDATE capital_fence_epochs SET expires_wall_ms ="
                    " :expires WHERE epoch = :epoch"
                ),
                {"expires": expires, "epoch": ticket.epoch},
            )
            return FenceTicket(
                epoch=ticket.epoch,
                writer_id=ticket.writer_id,
                expires_wall_ms=expires,
            )

        return self._write(operation)

    def takeover(
        self, writer_id: str, *, now: datetime, lease_seconds: int
    ) -> FenceTicket:
        """Displace every ACTIVE lease with a new epoch for ``writer_id``.

        All superseded rows record ``superseded_by_epoch`` in the same
        transaction that mints the new epoch, so a displaced writer's next
        ``renew``/``assert_current`` fails closed with the supersession
        visible in the error details.
        """

        _require_writer(writer_id)
        lease_ms = _require_lease(lease_seconds)
        now_ms = _wall_ms(now)

        def operation(conn: sa.Connection) -> FenceTicket:
            new_epoch = _next_epoch(conn)
            conn.execute(
                sa.text(
                    "UPDATE capital_fence_epochs SET state = 'SUPERSEDED',"
                    " superseded_by_epoch = :successor"
                    " WHERE state = 'ACTIVE'"
                ),
                {"successor": new_epoch},
            )
            return _insert_active(conn, writer_id, now_ms, lease_ms, epoch=new_epoch)

        return self._write(operation)

    def release(self, ticket: FenceTicket, *, now: datetime) -> None:
        """Retire the caller's lease; the row becomes immutable history."""

        now_ms = _wall_ms(now)

        def operation(conn: sa.Connection) -> None:
            _assert_row(conn, ticket, now_ms)
            conn.execute(
                sa.text(
                    "UPDATE capital_fence_epochs SET state = 'RELEASED'"
                    " WHERE epoch = :epoch"
                ),
                {"epoch": ticket.epoch},
            )

        self._write(operation)

    # -- same-transaction consumption -----------------------------------------

    def assert_current(
        self, conn: sa.Connection, ticket: FenceTicket, *, now: datetime
    ) -> None:
        """Consume the fence inside the caller's transaction.

        This is the per-economic-write gate required by the re-enable gate:
        callers must run it on the *same* connection (and therefore inside
        the same ``BEGIN IMMEDIATE`` transaction) as the economic writes it
        guards, so a writer that lost the fence can neither commit an
        economic event nor observe an uncommitted successor. This method
        never opens, commits, or rolls back a transaction.
        """

        if not isinstance(conn, sa.Connection):
            raise TypeError(
                "assert_current requires the caller's sqlalchemy Connection;"
                " it must run inside the economic write's own transaction"
            )
        _assert_row(conn, ticket, _wall_ms(now))

    # -- transaction plumbing ---------------------------------------------------

    def _write(self, operation):
        conn = self._repository.engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        )
        try:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                result = operation(conn)
            except BaseException:
                with contextlib.suppress(DBAPIError):
                    conn.exec_driver_sql("ROLLBACK")
                raise
            conn.exec_driver_sql("COMMIT")
            return result
        finally:
            conn.close()


# -- module-level helpers -----------------------------------------------------


def _table_exists(conn: sa.Connection, name: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"
        ),
        {"name": name},
    ).first()
    return row is not None


def _validate_shape(conn: sa.Connection) -> None:
    columns = {
        str(row.name)
        for row in conn.execute(sa.text(f"PRAGMA table_info({_FENCE_TABLE})")).all()
    }
    if columns != _EXPECTED_COLUMNS:
        raise CapitalFenceError(
            "fence_schema_drift",
            "the capital_fence_epochs table does not match the fence "
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
        raise CapitalFenceError(
            "fence_schema_drift",
            "fence enforcement triggers are missing or renamed; the epoch "
            "monotonicity contract is not enforced on this ledger",
            observed_triggers=sorted(triggers),
        )


def _next_epoch(conn: sa.Connection) -> int:
    current = conn.execute(
        sa.text("SELECT COALESCE(MAX(epoch), 0) FROM capital_fence_epochs")
    ).scalar_one()
    return int(current) + 1


def _insert_active(
    conn: sa.Connection,
    writer_id: str,
    now_ms: int,
    lease_ms: int,
    *,
    epoch: int | None = None,
) -> FenceTicket:
    if epoch is None:
        epoch = _next_epoch(conn)
    expires = now_ms + lease_ms
    conn.execute(
        sa.text(
            "INSERT INTO capital_fence_epochs (epoch, writer_id, state,"
            " claimed_wall_ms, expires_wall_ms, superseded_by_epoch)"
            " VALUES (:epoch, :writer_id, 'ACTIVE', :claimed, :expires, NULL)"
        ),
        {
            "epoch": epoch,
            "writer_id": writer_id,
            "claimed": now_ms,
            "expires": expires,
        },
    )
    return FenceTicket(
        epoch=epoch, writer_id=writer_id, expires_wall_ms=expires
    )


def _assert_row(
    conn: sa.Connection, ticket: FenceTicket, now_ms: int
) -> None:
    row = conn.execute(
        sa.text(
            "SELECT writer_id, state, expires_wall_ms, superseded_by_epoch"
            " FROM capital_fence_epochs WHERE epoch = :epoch"
        ),
        {"epoch": ticket.epoch},
    ).first()
    if row is None:
        raise CapitalFenceError(
            "fence_lost",
            "the fenced epoch no longer exists",
            epoch=ticket.epoch,
            reason="missing",
        )
    if str(row.writer_id) != ticket.writer_id:
        raise CapitalFenceError(
            "fence_lost",
            "the ticket's writer identity does not match the epoch's owner",
            epoch=ticket.epoch,
            reason="writer_mismatch",
            ticket_writer_id=ticket.writer_id,
            epoch_writer_id=str(row.writer_id),
        )
    if str(row.state) != "ACTIVE":
        raise CapitalFenceError(
            "fence_lost",
            "the fenced epoch is no longer active",
            epoch=ticket.epoch,
            reason=str(row.state).lower(),
            superseded_by_epoch=(
                int(row.superseded_by_epoch)
                if row.superseded_by_epoch is not None
                else None
            ),
        )
    if now_ms >= int(row.expires_wall_ms):
        raise CapitalFenceError(
            "fence_lost",
            "the fenced epoch expired before this consumption attempt",
            epoch=ticket.epoch,
            reason="expired",
            expired_wall_ms=int(row.expires_wall_ms),
            now_wall_ms=now_ms,
        )


__all__ = [
    "CapitalFence",
    "CapitalFenceError",
    "FenceTicket",
]
