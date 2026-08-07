"""Capital Gateway exit mandate lane (Plan 04 Task 7).

Independent exit obligations derived only from injected capital truth.
The lane never consumes entry authorization, policy envelopes, or the
permit/outbox machinery: risk and stage halts do not block exits, and
entry-side dependency outages cannot stop them. Mandate quantity is the
verified tradable quantity minus proven live exit leaves; an unknown
quantity schedules reconciliation and exposes zero orderable quantity -
the lane never guesses and never oversells. Mandates and leases are
durable across crashes and restarts.
"""

from __future__ import annotations

import json
import sqlite3
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Callable, Final

import sqlalchemy as sa

from src.screening.offensive.v3.capital.execution_revisions import (
    MANDATE_REVISION_FLOOR,
    ReopenedEconomicLot,
)
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    ExitMandate,
    ExitMandateRevisionKind,
    ExitQuantityKnowledge,
    PositionState,
    RiskLatchState,
    StageLossLatchState,
)

_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS exit_mandates (
        mandate_hash TEXT PRIMARY KEY,
        exit_mandate_id TEXT NOT NULL UNIQUE,
        position_lineage_id TEXT NOT NULL,
        economic_lot_id TEXT NOT NULL,
        security_id TEXT NOT NULL,
        portfolio_id TEXT NOT NULL,
        due_session TEXT NOT NULL,
        mandate_revision INTEGER NOT NULL,
        revision_kind TEXT NOT NULL,
        status TEXT NOT NULL,
        quantity_knowledge TEXT NOT NULL,
        reconciliation_pending INTEGER NOT NULL,
        tradable_quantity INTEGER NOT NULL,
        live_exit_leaves INTEGER NOT NULL,
        executable_quantity INTEGER NOT NULL,
        capital_version INTEGER NOT NULL,
        stable_client_order_id TEXT NOT NULL,
        supersedes_mandate_hash TEXT,
        reopened_by_execution_revision_id TEXT,
        mandate_artifact TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_active_exit_mandate_per_lot
    ON exit_mandates (position_lineage_id, economic_lot_id)
    WHERE status != 'SUPERSEDED'
    """,
    """
    CREATE TABLE IF NOT EXISTS exit_leases (
        lease_id TEXT PRIMARY KEY,
        mandate_hash TEXT NOT NULL,
        worker_id TEXT NOT NULL,
        leased_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        released_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exit_attempts (
        attempt_id TEXT PRIMARY KEY,
        mandate_hash TEXT NOT NULL,
        client_order_id TEXT NOT NULL,
        submitted_leaves INTEGER NOT NULL,
        filled_quantity INTEGER NOT NULL,
        late_filled_quantity INTEGER NOT NULL,
        cancelled_quantity INTEGER NOT NULL,
        recorded_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exit_reconciliations (
        reconciliation_id TEXT PRIMARY KEY,
        position_lineage_id TEXT NOT NULL,
        economic_lot_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        scheduled_at TEXT NOT NULL,
        resolved_at TEXT,
        resolved_tradable_quantity INTEGER
    )
    """,
)

_ACTIVE_MANDATE_STATUSES: Final[frozenset[str]] = frozenset(
    {"PENDING", "TERMINAL_LEGAL", "CLOSED"}
)

# Fixed T+10 exit policy ordinal (contracts require the native int 10).
_EXIT_SESSION_ORDINAL: Final[int] = 10


class ExitLaneError(RuntimeError):
    """Fail-closed rejection of one exit-lane operation."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class ExitAttemptOutcome(StrEnum):
    """One durable exit dispatch fact recorded against a mandate."""

    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    LATE_FILL = "LATE_FILL"


@dataclass(frozen=True)
class ExitLotTruth:
    """Injected capital truth for one economic lot."""

    position_lineage_id: str
    economic_lot_id: str
    security_id: str
    producer_namespace: str
    research_program_id: str
    economic_lineage_id: str
    stage_id: str
    position_state: PositionState
    signal_session: date
    entry_session_ordinal: int
    entry_plan_evidence_artifact_hash: str
    settled_quantity: int
    tradable_quantity: int | None
    live_exit_leaves: int
    successor_security_id: str | None
    reopen: ReopenedEconomicLot | None


@dataclass(frozen=True)
class ExitDerivationContext:
    """Injected portfolio truth and calendar for one derivation pass.

    Halt states are carried only to prove the lane ignores them: exits
    continue while risk or stage halts are active.
    """

    portfolio_id: str
    broker_account_id: str | None
    base_currency: str
    mode: ExecutionMode
    capital_version: int
    writer_fencing_epoch: int
    fixed_exit_policy_fingerprint: str
    source_risk_snapshot_id: str
    source_risk_snapshot_hash: str
    trading_sessions: tuple[date, ...]
    risk_latch: RiskLatchState = RiskLatchState.CLEAR
    stage_loss_latches: tuple[StageLossLatchState, ...] = ()


@dataclass(frozen=True)
class ExitDependencies:
    """Entry-side probes a Plan 05 scheduler may wire in.

    The exit path must never invoke any probe: outage tests install
    raising probes and require the full exit lifecycle to proceed.
    """

    policy_probe: Callable[[], object] | None = None
    envelope_probe: Callable[[], object] | None = None
    authorizer_probe: Callable[[], object] | None = None
    publisher_probe: Callable[[], object] | None = None
    entry_probe: Callable[[], object] | None = None


@dataclass(frozen=True)
class ClaimedExitWork:
    """One leased exit obligation released to a worker."""

    exit_mandate_id: str
    lease_id: str
    position_lineage_id: str
    economic_lot_id: str
    security_id: str
    due_session: date
    executable_quantity: int
    stable_client_order_id: str
    worker_id: str


@dataclass(frozen=True)
class ExitLaneProjection:
    """Read-only projection of one lot's exit obligation."""

    exit_mandate_id: str
    status: str
    mandate_revision: int
    security_id: str
    due_session: date
    quantity_knowledge: str
    reconciliation_pending: bool
    tradable_quantity: int
    live_exit_leaves: int
    executable_quantity: int
    outstanding_attempt_leaves: int
    claimable_quantity: int
    leased: bool
    outstanding_query_count: int
    stable_client_order_id: str


class ExitLane:
    """Durable scheduler for independent exit obligations."""

    def __init__(
        self,
        *,
        database_path: str,
        clock: Callable[[], datetime],
        lease_ttl: timedelta = timedelta(minutes=30),
        dependencies: ExitDependencies | None = None,
        _fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self._clock = clock
        self._lease_ttl = lease_ttl
        self._dependencies = dependencies
        self._fault_hook = _fault_hook
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        sa.event.listen(self._engine, "connect", _configure_connection)
        with self._engine.begin() as conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(sa.text(ddl))

    def _fault(self, phase: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(phase)

    # -- derivation -----------------------------------------------------------

    def derive_exit_mandates(
        self,
        lots: tuple[ExitLotTruth, ...],
        *,
        context: ExitDerivationContext,
    ) -> tuple[ExitMandate, ...]:
        """Derive or refresh one mandate per lot from capital truth.

        Halt states in the context are deliberately not consulted: exit
        obligations survive risk and stage halts unchanged.
        """

        mandates: list[ExitMandate] = []
        for lot in lots:
            mandates.append(self._derive_one_lot(lot, context))
        return tuple(mandates)

    def _derive_one_lot(
        self, lot: ExitLotTruth, context: ExitDerivationContext
    ) -> ExitMandate:
        if lot.position_state not in {
            PositionState.OPEN,
            PositionState.EXIT_PENDING,
            PositionState.LEGAL_TERMINAL,
        }:
            raise ExitLaneError(
                "exit_lot_state_conflict",
                "lot position state cannot carry an exit obligation",
            )
        tradable = lot.tradable_quantity
        leaves = lot.live_exit_leaves
        if tradable is None and leaves != 0:
            raise ExitLaneError(
                "exit_leaves_exceed_tradable",
                "unknown quantity cannot carry proven exit leaves",
            )
        if tradable is not None and leaves > tradable:
            raise ExitLaneError(
                "exit_leaves_exceed_tradable",
                "live exit leaves exceed the verified tradable quantity",
            )
        due_session = self._due_session(lot, context)
        security_id = lot.successor_security_id or lot.security_id
        knowledge = (
            ExitQuantityKnowledge.KNOWN
            if tradable is not None
            else ExitQuantityKnowledge.UNKNOWN
        )
        if lot.position_state is PositionState.LEGAL_TERMINAL:
            target_status = "TERMINAL_LEGAL"
        elif tradable == 0:
            target_status = "CLOSED"
        else:
            target_status = "PENDING"
        executable = 0 if tradable is None else tradable - leaves
        with self._engine.begin() as conn:
            active = self._active_mandate_row(
                conn, lot.position_lineage_id, lot.economic_lot_id
            )
            if active is not None and self._essentials_unchanged(
                active,
                knowledge=knowledge,
                tradable=tradable or 0,
                leaves=leaves if tradable is not None else 0,
                executable=executable,
                security_id=security_id,
                due_session=due_session,
                status=target_status,
            ):
                return self._mandate_from_row(active)
            if active is None and lot.reopen is not None:
                mandate = self._reopen_chain_for_never_mandated_lot(
                    conn,
                    lot,
                    context,
                    knowledge=knowledge,
                    tradable=tradable or 0,
                    leaves=leaves if tradable is not None else 0,
                    executable=executable,
                    security_id=security_id,
                    due_session=due_session,
                    status=target_status,
                )
            else:
                revision, kind, supersedes_hash, reopened_by = (
                    self._next_revision_binding(active, lot)
                )
                mandate = self._build_mandate(
                    lot,
                    context,
                    knowledge=knowledge,
                    tradable=tradable or 0,
                    leaves=leaves if tradable is not None else 0,
                    executable=executable,
                    security_id=security_id,
                    due_session=due_session,
                    revision=revision,
                    kind=kind,
                    supersedes_hash=supersedes_hash,
                    reopened_by=reopened_by,
                )
                if active is not None:
                    conn.execute(
                        sa.text(
                            "UPDATE exit_mandates SET status = 'SUPERSEDED'"
                            " WHERE mandate_hash = :hash"
                        ),
                        {"hash": str(active.mandate_hash)},
                    )
                self._fault("derive.after_supersede")
                self._insert_mandate_row(conn, mandate, target_status)
            self._fault("derive.after_insert")
            if knowledge is ExitQuantityKnowledge.UNKNOWN:
                self._schedule_reconciliation(
                    conn,
                    lot,
                    reason="unknown_tradable_quantity",
                )
        return mandate

    def _reopen_chain_for_never_mandated_lot(
        self,
        conn: sa.engine.Connection,
        lot: ExitLotTruth,
        context: ExitDerivationContext,
        *,
        knowledge: ExitQuantityKnowledge,
        tradable: int,
        leaves: int,
        executable: int,
        security_id: str,
        due_session: date,
        status: str,
    ) -> ExitMandate:
        """Atomic INITIAL + REOPENED chain when a reopen fact arrives for a
        lot the lane never mandated. Revision 1 belongs to INITIAL
        mandates only, so the reopen provenance lands on revision 2 with
        a real predecessor hash to bind."""

        assert lot.reopen is not None
        initial = self._build_mandate(
            lot,
            context,
            knowledge=knowledge,
            tradable=tradable,
            leaves=leaves,
            executable=executable,
            security_id=security_id,
            due_session=due_session,
            revision=1,
            kind=ExitMandateRevisionKind.INITIAL,
            supersedes_hash=None,
            reopened_by=None,
        )
        self._insert_mandate_row(conn, initial, status)
        conn.execute(
            sa.text(
                "UPDATE exit_mandates SET status = 'SUPERSEDED'"
                " WHERE mandate_hash = :hash"
            ),
            {"hash": initial.artifact_hash()},
        )
        return self._insert_reopened_revision(
            conn,
            lot,
            context,
            initial_hash=initial.artifact_hash(),
            knowledge=knowledge,
            tradable=tradable,
            leaves=leaves,
            executable=executable,
            security_id=security_id,
            due_session=due_session,
            status=status,
        )

    def _insert_reopened_revision(
        self,
        conn: sa.engine.Connection,
        lot: ExitLotTruth,
        context: ExitDerivationContext,
        *,
        initial_hash: str,
        knowledge: ExitQuantityKnowledge,
        tradable: int,
        leaves: int,
        executable: int,
        security_id: str,
        due_session: date,
        status: str,
    ) -> ExitMandate:
        assert lot.reopen is not None
        reopened = self._build_mandate(
            lot,
            context,
            knowledge=knowledge,
            tradable=tradable,
            leaves=leaves,
            executable=executable,
            security_id=security_id,
            due_session=due_session,
            revision=MANDATE_REVISION_FLOOR,
            kind=ExitMandateRevisionKind.REOPENED_BY_CORRECTION,
            supersedes_hash=initial_hash,
            reopened_by=lot.reopen.reopened_by_execution_revision_id,
        )
        self._insert_mandate_row(conn, reopened, status)
        return reopened

    def _due_session(
        self, lot: ExitLotTruth, context: ExitDerivationContext
    ) -> date:
        sessions = context.trading_sessions
        first_after = bisect_right(sessions, lot.signal_session)
        index = first_after + lot.entry_session_ordinal + (
            _EXIT_SESSION_ORDINAL - 2
        )
        if index >= len(sessions):
            raise ExitLaneError(
                "exit_calendar_insufficient",
                "trading calendar cannot resolve the T+10 due session",
            )
        return sessions[index]

    def _essentials_unchanged(
        self,
        row,
        *,
        knowledge: ExitQuantityKnowledge,
        tradable: int,
        leaves: int,
        executable: int,
        security_id: str,
        due_session: date,
        status: str,
    ) -> bool:
        return (
            str(row.quantity_knowledge) == knowledge.value
            and int(row.tradable_quantity) == tradable
            and int(row.live_exit_leaves) == leaves
            and int(row.executable_quantity) == executable
            and str(row.security_id) == security_id
            and str(row.due_session) == due_session.isoformat()
            and str(row.status) == status
        )

    def _next_revision_binding(
        self, active, lot: ExitLotTruth
    ) -> tuple[int, ExitMandateRevisionKind, str | None, str | None]:
        # The active-None reopen case is owned by the two-step chain
        # path; here an absent predecessor can only mean INITIAL.
        if active is None:
            return (1, ExitMandateRevisionKind.INITIAL, None, None)
        reopen = lot.reopen
        prior_reopen = str(active.reopened_by_execution_revision_id or "")
        if (
            reopen is not None
            and reopen.reopened_by_execution_revision_id != prior_reopen
        ):
            return (
                int(active.mandate_revision) + 1,
                ExitMandateRevisionKind.REOPENED_BY_CORRECTION,
                str(active.mandate_hash),
                reopen.reopened_by_execution_revision_id,
            )
        return (
            int(active.mandate_revision) + 1,
            ExitMandateRevisionKind.QUANTITY_REFRESH,
            str(active.mandate_hash),
            None,
        )

    def _build_mandate(
        self,
        lot: ExitLotTruth,
        context: ExitDerivationContext,
        *,
        knowledge: ExitQuantityKnowledge,
        tradable: int,
        leaves: int,
        executable: int,
        security_id: str,
        due_session: date,
        revision: int,
        kind: ExitMandateRevisionKind,
        supersedes_hash: str | None,
        reopened_by: str | None,
    ) -> ExitMandate:
        lot_slug = f"{lot.position_lineage_id}:{lot.economic_lot_id}"
        reconciliation_pending = knowledge is ExitQuantityKnowledge.UNKNOWN
        return ExitMandate(
            exit_mandate_id=f"exit-mandate-{lot_slug}:r{revision}",
            portfolio_id=context.portfolio_id,
            broker_account_id=context.broker_account_id,
            base_currency=context.base_currency,
            mode=context.mode,
            position_lineage_id=lot.position_lineage_id,
            economic_lot_id=lot.economic_lot_id,
            security_id=security_id,
            producer_namespace=lot.producer_namespace,
            research_program_id=lot.research_program_id,
            economic_lineage_id=lot.economic_lineage_id,
            stage_id=lot.stage_id,
            entry_plan_evidence_artifact_hash=(
                lot.entry_plan_evidence_artifact_hash
            ),
            fixed_exit_policy_fingerprint=(
                context.fixed_exit_policy_fingerprint
            ),
            exit_session_ordinal=_EXIT_SESSION_ORDINAL,
            due_session=due_session,
            quantity_knowledge=knowledge,
            reconciliation_pending=reconciliation_pending,
            tradable_quantity=tradable,
            live_exit_leaves_quantity=leaves,
            executable_quantity=executable,
            mandate_revision=revision,
            revision_kind=kind,
            supersedes_mandate_hash=supersedes_hash,
            reopened_by_execution_revision_id=reopened_by,
            capital_version=context.capital_version,
            writer_fencing_epoch=context.writer_fencing_epoch,
            stable_client_order_id=f"exit-client-{lot_slug}",
            issued_at=self._clock(),
            source_risk_snapshot_id=context.source_risk_snapshot_id,
            source_risk_snapshot_hash=context.source_risk_snapshot_hash,
            schema_major=2,
        )

    def _insert_mandate_row(
        self, conn: sa.engine.Connection, mandate: ExitMandate, status: str
    ) -> None:
        conn.execute(
            sa.text(
                "INSERT INTO exit_mandates (mandate_hash,"
                " exit_mandate_id, position_lineage_id, economic_lot_id,"
                " security_id, portfolio_id, due_session,"
                " mandate_revision, revision_kind, status,"
                " quantity_knowledge, reconciliation_pending,"
                " tradable_quantity, live_exit_leaves,"
                " executable_quantity, capital_version,"
                " stable_client_order_id, supersedes_mandate_hash,"
                " reopened_by_execution_revision_id, mandate_artifact,"
                " created_at)"
                " VALUES (:hash, :mandate_id, :lineage, :lot, :security,"
                " :portfolio, :due, :revision, :kind, :status,"
                " :knowledge, :pending, :tradable, :leaves,"
                " :executable, :capital_version, :client,"
                " :supersedes, :reopened_by, :artifact, :created_at)"
            ),
            {
                "hash": mandate.artifact_hash(),
                "mandate_id": mandate.exit_mandate_id,
                "lineage": mandate.position_lineage_id,
                "lot": mandate.economic_lot_id,
                "security": mandate.security_id,
                "portfolio": mandate.portfolio_id,
                "due": mandate.due_session.isoformat(),
                "revision": mandate.mandate_revision,
                "kind": mandate.revision_kind.value,
                "status": status,
                "knowledge": mandate.quantity_knowledge.value,
                "pending": int(mandate.reconciliation_pending),
                "tradable": mandate.tradable_quantity,
                "leaves": mandate.live_exit_leaves_quantity,
                "executable": mandate.executable_quantity,
                "capital_version": mandate.capital_version,
                "client": mandate.stable_client_order_id,
                "supersedes": mandate.supersedes_mandate_hash,
                "reopened_by": (
                    mandate.reopened_by_execution_revision_id
                ),
                "artifact": mandate.model_dump_json(),
                "created_at": self._clock().isoformat(),
            },
        )

    def _mandate_from_row(self, row) -> ExitMandate:
        return ExitMandate.model_validate_json(str(row.mandate_artifact))

    def _schedule_reconciliation(
        self, conn: sa.engine.Connection, lot: ExitLotTruth, *, reason: str
    ) -> None:
        self._schedule_reconciliation_by_slug(
            conn,
            lot.position_lineage_id,
            lot.economic_lot_id,
            reason=reason,
        )

    # -- leasing due work -------------------------------------------------------

    def claim_due_exit_work(
        self,
        *,
        as_of_session: date,
        worker_id: str,
        blocked_securities: frozenset[str] = frozenset(),
        max_claims: int | None = None,
    ) -> tuple[ClaimedExitWork, ...]:
        """Lease due, known, executable mandates to one worker.

        Suspended or limit-blocked securities are skipped for the day;
        the underlying obligation is never cancelled by a market state.
        Expired leases from crashed workers return to the pool first.
        """

        now = self._clock()
        now_iso = now.isoformat()
        with self._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE exit_leases SET released_at = :now"
                    " WHERE released_at IS NULL AND expires_at < :now"
                ),
                {"now": now_iso},
            )
            candidates = conn.execute(
                sa.text(
                    "SELECT * FROM exit_mandates WHERE status = 'PENDING'"
                    " AND quantity_knowledge = 'KNOWN'"
                    " AND executable_quantity > 0"
                    " AND due_session <= :as_of"
                    " ORDER BY due_session, exit_mandate_id"
                ),
                {"as_of": as_of_session.isoformat()},
            ).all()
            claimed: list[ClaimedExitWork] = []
            for row in candidates:
                if max_claims is not None and len(claimed) >= max_claims:
                    break
                if str(row.security_id) in blocked_securities:
                    continue
                active_lease = conn.execute(
                    sa.text(
                        "SELECT COUNT(*) AS n FROM exit_leases"
                        " WHERE mandate_hash = :hash AND released_at IS"
                        " NULL AND expires_at >= :now"
                    ),
                    {"hash": str(row.mandate_hash), "now": now_iso},
                ).one()
                if int(active_lease.n) > 0:
                    continue
                claimable = self._claimable_quantity(conn, row)
                if claimable <= 0:
                    continue
                lease_sequence = conn.execute(
                    sa.text(
                        "SELECT COUNT(*) AS n FROM exit_leases"
                        " WHERE mandate_hash = :hash"
                    ),
                    {"hash": str(row.mandate_hash)},
                ).one()
                lease_id = (
                    f"lease:{row.mandate_hash}:{int(lease_sequence.n) + 1}"
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO exit_leases (lease_id, mandate_hash,"
                        " worker_id, leased_at, expires_at)"
                        " VALUES (:lease, :hash, :worker, :leased_at,"
                        " :expires_at)"
                    ),
                    {
                        "lease": lease_id,
                        "hash": str(row.mandate_hash),
                        "worker": worker_id,
                        "leased_at": now_iso,
                        "expires_at": (now + self._lease_ttl).isoformat(),
                    },
                )
                self._fault("claim.after_lease")
                claimed.append(
                    ClaimedExitWork(
                        exit_mandate_id=str(row.exit_mandate_id),
                        lease_id=lease_id,
                        position_lineage_id=str(row.position_lineage_id),
                        economic_lot_id=str(row.economic_lot_id),
                        security_id=str(row.security_id),
                        due_session=date.fromisoformat(str(row.due_session)),
                        executable_quantity=claimable,
                        stable_client_order_id=str(
                            row.stable_client_order_id
                        ),
                        worker_id=worker_id,
                    )
                )
        return tuple(claimed)

    def _attempt_ledger(self, conn: sa.engine.Connection, mandate_hash: str):
        rows = conn.execute(
            sa.text(
                "SELECT submitted_leaves, filled_quantity,"
                " late_filled_quantity, cancelled_quantity"
                " FROM exit_attempts WHERE mandate_hash = :hash"
            ),
            {"hash": mandate_hash},
        ).all()
        outstanding = 0
        filled = 0
        for row in rows:
            submitted = int(row.submitted_leaves)
            fill_total = int(row.filled_quantity) + int(
                row.late_filled_quantity
            )
            outstanding += max(
                0, submitted - fill_total - int(row.cancelled_quantity)
            )
            filled += fill_total
        return outstanding, filled

    def _claimable_quantity(self, conn: sa.engine.Connection, row) -> int:
        outstanding, filled = self._attempt_ledger(
            conn, str(row.mandate_hash)
        )
        return int(row.executable_quantity) - outstanding - filled

    # -- exit attempts -----------------------------------------------------------

    def record_exit_attempt(
        self,
        *,
        exit_mandate_id: str,
        attempt_id: str,
        client_order_id: str,
        outcome: ExitAttemptOutcome,
        submitted_leaves: int = 0,
        filled_quantity: int = 0,
    ) -> None:
        """Record one durable dispatch fact against a mandate.

        Submissions may never exceed the claimable quantity (the lane
        never oversells); cancellations free the book; late fills after a
        cancel count as sold shares but can never exceed what was ever on
        the book. Retries must reuse the stable client order id.
        """

        with self._engine.begin() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT * FROM exit_mandates"
                    " WHERE exit_mandate_id = :mandate_id"
                ),
                {"mandate_id": exit_mandate_id},
            ).first()
            if row is None:
                raise ExitLaneError(
                    "exit_mandate_unknown", "no exit mandate for id"
                )
            if str(row.status) != "PENDING":
                raise ExitLaneError(
                    "exit_attempt_state_conflict",
                    "attempts require a PENDING exit mandate",
                )
            if client_order_id != str(row.stable_client_order_id):
                raise ExitLaneError(
                    "client_order_id_mismatch",
                    "exit attempts must reuse the stable client order id",
                )
            attempt = conn.execute(
                sa.text(
                    "SELECT * FROM exit_attempts"
                    " WHERE attempt_id = :attempt"
                ),
                {"attempt": attempt_id},
            ).first()
            if attempt is None:
                if outcome is not ExitAttemptOutcome.SUBMITTED:
                    raise ExitLaneError(
                        "exit_attempt_state_conflict",
                        "only a submission may open a new attempt",
                    )
                if submitted_leaves <= 0:
                    raise ExitLaneError(
                        "exit_attempt_state_conflict",
                        "submission requires positive leaves",
                    )
                if submitted_leaves > self._claimable_quantity(conn, row):
                    raise ExitLaneError(
                        "exit_oversell_blocked",
                        "submission exceeds the claimable exit quantity",
                    )
                conn.execute(
                    sa.text(
                        "INSERT INTO exit_attempts (attempt_id,"
                        " mandate_hash, client_order_id,"
                        " submitted_leaves, filled_quantity,"
                        " late_filled_quantity, cancelled_quantity,"
                        " recorded_at) VALUES (:attempt, :hash, :client,"
                        " :leaves, 0, 0, 0, :recorded_at)"
                    ),
                    {
                        "attempt": attempt_id,
                        "hash": str(row.mandate_hash),
                        "client": client_order_id,
                        "leaves": submitted_leaves,
                        "recorded_at": self._clock().isoformat(),
                    },
                )
                self._fault("attempt.after_insert")
                return
            self._update_attempt(
                conn, attempt, outcome, submitted_leaves, filled_quantity
            )

    def _update_attempt(
        self,
        conn: sa.engine.Connection,
        attempt,
        outcome: ExitAttemptOutcome,
        submitted_leaves: int,
        filled_quantity: int,
    ) -> None:
        submitted = int(attempt.submitted_leaves)
        filled = int(attempt.filled_quantity)
        late = int(attempt.late_filled_quantity)
        cancelled = int(attempt.cancelled_quantity)
        if outcome is ExitAttemptOutcome.SUBMITTED:
            if submitted_leaves == submitted:
                return  # idempotent replay
            raise ExitLaneError(
                "exit_attempt_conflict",
                "attempt identity already opened a different submission",
            )
        if outcome is ExitAttemptOutcome.FILLED:
            if cancelled != 0:
                raise ExitLaneError(
                    "exit_attempt_state_conflict",
                    "post-cancel fills must be recorded as late fills",
                )
            if filled_quantity < filled:
                raise ExitLaneError(
                    "exit_attempt_conflict",
                    "cumulative fills cannot move backwards",
                )
            if filled_quantity == filled:
                return  # idempotent replay
            if filled_quantity > submitted - late:
                raise ExitLaneError(
                    "exit_fill_exceeds_submission",
                    "fills cannot exceed the submitted leaves",
                )
            conn.execute(
                sa.text(
                    "UPDATE exit_attempts SET filled_quantity = :filled"
                    " WHERE attempt_id = :attempt"
                ),
                {"filled": filled_quantity, "attempt": attempt.attempt_id},
            )
            self._fault("attempt.after_update")
            return
        if outcome is ExitAttemptOutcome.CANCELLED:
            if cancelled != 0:
                return  # idempotent replay
            conn.execute(
                sa.text(
                    "UPDATE exit_attempts SET cancelled_quantity ="
                    " :cancelled WHERE attempt_id = :attempt"
                ),
                {
                    "cancelled": submitted - filled - late,
                    "attempt": attempt.attempt_id,
                },
            )
            self._fault("attempt.after_update")
            return
        # LATE_FILL
        if cancelled == 0:
            raise ExitLaneError(
                "exit_attempt_state_conflict",
                "late fills require a cancelled attempt",
            )
        if filled_quantity < late:
            raise ExitLaneError(
                "exit_attempt_conflict",
                "cumulative late fills cannot move backwards",
            )
        if filled_quantity == late:
            return  # idempotent replay
        if filled + filled_quantity > submitted:
            raise ExitLaneError(
                "exit_late_fill_exceeds_book",
                "late fills cannot exceed what was ever on the book",
            )
        conn.execute(
            sa.text(
                "UPDATE exit_attempts SET late_filled_quantity = :late"
                " WHERE attempt_id = :attempt"
            ),
            {"late": filled_quantity, "attempt": attempt.attempt_id},
        )
        self._fault("attempt.after_update")

    # -- reconciliation -----------------------------------------------------------

    def reconcile_exit(
        self,
        *,
        position_lineage_id: str,
        economic_lot_id: str,
        reason: str,
        verified_tradable_quantity: int | None = None,
        live_exit_leaves: int = 0,
    ) -> ExitMandate | None:
        """Resolve or schedule one lot's quantity reconciliation.

        Without a verified quantity the lane schedules a query and keeps
        the mandate unorderable; with one it publishes a KNOWN refresh
        revision and resolves the open queries. Identical verified
        replays are idempotent and never bump the revision. Closed lots
        reopen only through correction facts, never through reconcile.
        """

        lot_slug = f"{position_lineage_id}:{economic_lot_id}"
        with self._engine.begin() as conn:
            active = self._active_mandate_row(
                conn, position_lineage_id, economic_lot_id
            )
            if active is None:
                raise ExitLaneError(
                    "exit_mandate_unknown",
                    "no exit mandate for lot",
                )
            if str(active.status) == "TERMINAL_LEGAL":
                raise ExitLaneError(
                    "exit_mandate_state_conflict",
                    "terminal legal mandates cannot be reconciled",
                )
            if verified_tradable_quantity is None:
                self._schedule_reconciliation_by_slug(
                    conn,
                    position_lineage_id,
                    economic_lot_id,
                    reason=reason,
                )
                return None
            if live_exit_leaves > verified_tradable_quantity:
                raise ExitLaneError(
                    "exit_leaves_exceed_tradable",
                    "verified leaves exceed the verified tradable"
                    " quantity",
                )
            target_status = (
                "PENDING" if verified_tradable_quantity > 0 else "CLOSED"
            )
            if (
                str(active.quantity_knowledge)
                == ExitQuantityKnowledge.KNOWN.value
                and int(active.tradable_quantity)
                == verified_tradable_quantity
                and int(active.live_exit_leaves) == live_exit_leaves
                and int(active.executable_quantity)
                == verified_tradable_quantity - live_exit_leaves
                and str(active.status) == target_status
            ):
                return self._mandate_from_row(active)  # idempotent replay
            if str(active.status) == "CLOSED":
                raise ExitLaneError(
                    "exit_mandate_state_conflict",
                    "closed lots reopen only through correction facts",
                )
            artifact = self._mandate_artifact(active)
            mandate = ExitMandate(
                exit_mandate_id=(
                    f"exit-mandate-{lot_slug}:"
                    f"r{int(active.mandate_revision) + 1}"
                ),
                portfolio_id=str(active.portfolio_id),
                broker_account_id=artifact["broker_account_id"],
                base_currency=artifact["base_currency"],
                mode=ExecutionMode(artifact["mode"]),
                position_lineage_id=position_lineage_id,
                economic_lot_id=economic_lot_id,
                security_id=str(active.security_id),
                producer_namespace=artifact["producer_namespace"],
                research_program_id=artifact["research_program_id"],
                economic_lineage_id=artifact["economic_lineage_id"],
                stage_id=artifact["stage_id"],
                entry_plan_evidence_artifact_hash=(
                    artifact["entry_plan_evidence_artifact_hash"]
                ),
                fixed_exit_policy_fingerprint=(
                    artifact["fixed_exit_policy_fingerprint"]
                ),
                exit_session_ordinal=_EXIT_SESSION_ORDINAL,
                due_session=date.fromisoformat(str(active.due_session)),
                quantity_knowledge=ExitQuantityKnowledge.KNOWN,
                reconciliation_pending=False,
                tradable_quantity=verified_tradable_quantity,
                live_exit_leaves_quantity=live_exit_leaves,
                executable_quantity=(
                    verified_tradable_quantity - live_exit_leaves
                ),
                mandate_revision=int(active.mandate_revision) + 1,
                revision_kind=ExitMandateRevisionKind.QUANTITY_REFRESH,
                supersedes_mandate_hash=str(active.mandate_hash),
                reopened_by_execution_revision_id=None,
                capital_version=int(active.capital_version),
                writer_fencing_epoch=artifact["writer_fencing_epoch"],
                stable_client_order_id=str(active.stable_client_order_id),
                issued_at=self._clock(),
                source_risk_snapshot_id=artifact["source_risk_snapshot_id"],
                source_risk_snapshot_hash=(
                    artifact["source_risk_snapshot_hash"]
                ),
                schema_major=2,
            )
            conn.execute(
                sa.text(
                    "UPDATE exit_mandates SET status = 'SUPERSEDED'"
                    " WHERE mandate_hash = :hash"
                ),
                {"hash": str(active.mandate_hash)},
            )
            self._fault("reconcile.after_supersede")
            self._insert_mandate_row(conn, mandate, target_status)
            self._fault("reconcile.after_insert")
            conn.execute(
                sa.text(
                    "UPDATE exit_reconciliations SET resolved_at = :now,"
                    " resolved_tradable_quantity = :quantity"
                    " WHERE position_lineage_id = :lineage AND"
                    " economic_lot_id = :lot AND resolved_at IS NULL"
                ),
                {
                    "now": self._clock().isoformat(),
                    "quantity": verified_tradable_quantity,
                    "lineage": position_lineage_id,
                    "lot": economic_lot_id,
                },
            )
        return mandate

    def _mandate_artifact(self, row) -> dict:
        return json.loads(str(row.mandate_artifact))

    def _schedule_reconciliation_by_slug(
        self,
        conn: sa.engine.Connection,
        position_lineage_id: str,
        economic_lot_id: str,
        *,
        reason: str,
    ) -> None:
        open_query = conn.execute(
            sa.text(
                "SELECT COUNT(*) AS n FROM exit_reconciliations"
                " WHERE position_lineage_id = :lineage AND"
                " economic_lot_id = :lot AND resolved_at IS NULL"
            ),
            {"lineage": position_lineage_id, "lot": economic_lot_id},
        ).one()
        if int(open_query.n) > 0:
            return  # one open query per lot is enough
        scheduled = conn.execute(
            sa.text(
                "SELECT COUNT(*) AS n FROM exit_reconciliations"
                " WHERE position_lineage_id = :lineage AND"
                " economic_lot_id = :lot"
            ),
            {"lineage": position_lineage_id, "lot": economic_lot_id},
        ).one()
        conn.execute(
            sa.text(
                "INSERT INTO exit_reconciliations (reconciliation_id,"
                " position_lineage_id, economic_lot_id, reason,"
                " scheduled_at) VALUES (:recon_id, :lineage, :lot,"
                " :reason, :scheduled_at)"
            ),
            {
                "recon_id": (
                    f"recon:{position_lineage_id}:{economic_lot_id}:"
                    f"{int(scheduled.n) + 1}"
                ),
                "lineage": position_lineage_id,
                "lot": economic_lot_id,
                "reason": reason,
                "scheduled_at": self._clock().isoformat(),
            },
        )

    # -- read-only projection ------------------------------------------------------

    def exit_state(
        self, position_lineage_id: str, economic_lot_id: str
    ) -> ExitLaneProjection | None:
        with self._engine.connect() as conn:
            active = self._active_mandate_row(
                conn, position_lineage_id, economic_lot_id
            )
            if active is None:
                return None
            now_iso = self._clock().isoformat()
            lease_row = conn.execute(
                sa.text(
                    "SELECT COUNT(*) AS n FROM exit_leases"
                    " WHERE mandate_hash = :hash AND released_at IS NULL"
                    " AND expires_at >= :now"
                ),
                {"hash": str(active.mandate_hash), "now": now_iso},
            ).one()
            queries = conn.execute(
                sa.text(
                    "SELECT COUNT(*) AS n FROM exit_reconciliations"
                    " WHERE position_lineage_id = :lineage AND"
                    " economic_lot_id = :lot AND resolved_at IS NULL"
                ),
                {
                    "lineage": position_lineage_id,
                    "lot": economic_lot_id,
                },
            ).one()
            outstanding, filled = self._attempt_ledger(
                conn, str(active.mandate_hash)
            )
        executable = int(active.executable_quantity)
        return ExitLaneProjection(
            exit_mandate_id=str(active.exit_mandate_id),
            status=str(active.status),
            mandate_revision=int(active.mandate_revision),
            security_id=str(active.security_id),
            due_session=date.fromisoformat(str(active.due_session)),
            quantity_knowledge=str(active.quantity_knowledge),
            reconciliation_pending=bool(active.reconciliation_pending),
            tradable_quantity=int(active.tradable_quantity),
            live_exit_leaves=int(active.live_exit_leaves),
            executable_quantity=executable,
            outstanding_attempt_leaves=outstanding,
            claimable_quantity=executable - outstanding - filled,
            leased=int(lease_row.n) > 0,
            outstanding_query_count=int(queries.n),
            stable_client_order_id=str(active.stable_client_order_id),
        )

    def _active_mandate_row(
        self,
        conn: sa.engine.Connection,
        position_lineage_id: str,
        economic_lot_id: str,
    ):
        return conn.execute(
            sa.text(
                "SELECT * FROM exit_mandates"
                " WHERE position_lineage_id = :lineage AND"
                " economic_lot_id = :lot AND status != 'SUPERSEDED'"
            ),
            {"lineage": position_lineage_id, "lot": economic_lot_id},
        ).first()


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


__all__ = [
    "ClaimedExitWork",
    "ExitAttemptOutcome",
    "ExitDerivationContext",
    "ExitDependencies",
    "ExitLane",
    "ExitLaneError",
    "ExitLaneProjection",
    "ExitLotTruth",
]
