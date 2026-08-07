"""Capital Gateway entry admission and send-right linearization (Plan 04).

One immediate transaction owns the whole entry lifecycle. Tasks 5 admits
the decision, reserves exact worst-case cash, and publishes the active
PortfolioDecisionSeal; Task 6 extends the same seal store with the permit
state machine: SEALED -> PERMITTED -> OUTBOX_DURABLE -> SEND_CLAIMED, then
SUBMISSION_AMBIGUOUS | BROKER_ACK delivery outcomes, with TOMBSTONED as the
only pre-claim exit. Economic idempotency keys on
``(portfolio_id, signal_session, decision_cycle_id)`` and can never be
escaped by changing epochs or retry ids. Before a permit, an explicit
legal shrink/cancel may supersede the active seal under the same economic
key and revision chain; after a permit (or outbox state) no quantity
increase or key escape is possible.

``claim_send`` is the final linearization point for the right to send: one
transaction revalidates the active seal, permit nonce, durable outbox,
reserve allocations, deadlines, and the complete authority/capital/risk/
stage/fence truth, then consumes the permit nonce. No network call ever
occurs inside the database transaction; after commit the owner either
sends the exact immutable payload under the same client order ids or
records an ambiguous/receipt state. Retries may only reuse the claimed
client ids, never guess new ones.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Callable, Final

import sqlalchemy as sa

from src.screening.offensive.v3.contracts import SignedEnvelope  # noqa: F401
from src.screening.offensive.v3.contracts import (
    AuthorizationLifecycle,
    OutboxState,
    PermitDisposition,
    PermitNonceState,
    ReconciliationLatchState,
    RiskLatchState,
    StageLossLatchState,
)
from src.screening.offensive.v3.contracts.decision import (  # noqa: F401
    DecisionLogicalKey,
    GatewayExpectedVersions,
    PortfolioDecision,
    PortfolioDecisionSeal,
)
from src.screening.offensive.v3.contracts.execution import (
    EntryCancellationReceipt,
    ExecutionPermit,
    SendClaimExpectedVersions,
)

_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS decision_seals (
        seal_id TEXT PRIMARY KEY,
        portfolio_id TEXT NOT NULL,
        signal_session TEXT NOT NULL,
        decision_cycle_id TEXT NOT NULL,
        seal_revision INTEGER NOT NULL,
        seal_artifact_hash TEXT NOT NULL,
        proposal_artifact_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        total_reserved_cash_cents INTEGER NOT NULL,
        supersedes_seal_id TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_active_seal_per_key
    ON decision_seals (portfolio_id, signal_session, decision_cycle_id)
    WHERE status = 'SEALED'
    """,
    """
    CREATE TABLE IF NOT EXISTS entry_reserves (
        reservation_id TEXT PRIMARY KEY,
        seal_id TEXT NOT NULL,
        order_line_id TEXT NOT NULL,
        reservation_allocation_id TEXT NOT NULL DEFAULT '',
        reserved_cash_cents INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entry_permits (
        permit_id TEXT PRIMARY KEY,
        seal_id TEXT NOT NULL,
        permit_nonce TEXT NOT NULL,
        permit_nonce_sequence INTEGER NOT NULL,
        permit_nonce_state TEXT NOT NULL,
        disposition TEXT NOT NULL,
        permit_artifact_hash TEXT NOT NULL,
        total_remaining_reserve_cents INTEGER NOT NULL,
        total_released_reserve_cents INTEGER NOT NULL,
        permit_expires_at TEXT NOT NULL,
        issued_at TEXT NOT NULL,
        cancel_receipt_id TEXT,
        cancel_receipt_artifact_hash TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entry_permit_lines (
        permit_id TEXT NOT NULL,
        order_line_id TEXT NOT NULL,
        permitted_quantity_units INTEGER NOT NULL,
        client_order_id TEXT,
        remaining_reserve_cents INTEGER NOT NULL,
        PRIMARY KEY (permit_id, order_line_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entry_outbox (
        outbox_batch_id TEXT PRIMARY KEY,
        seal_id TEXT NOT NULL,
        permit_id TEXT NOT NULL,
        permit_nonce TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        state TEXT NOT NULL,
        created_at TEXT NOT NULL,
        tombstoned_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS send_claims (
        seal_id TEXT PRIMARY KEY,
        permit_id TEXT NOT NULL,
        permit_nonce TEXT NOT NULL,
        outbox_batch_id TEXT NOT NULL,
        send_claim_sequence INTEGER NOT NULL,
        claimed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS send_claim_lines (
        seal_id TEXT NOT NULL,
        order_line_id TEXT NOT NULL,
        client_order_id TEXT NOT NULL,
        PRIMARY KEY (seal_id, order_line_id)
    )
    """,
)

_CLAIMABLE_SEAL_STATUSES: Final[frozenset[str]] = frozenset(
    {"SEND_CLAIMED", "SUBMISSION_AMBIGUOUS", "BROKER_ACK"}
)


class CapitalGatewayError(RuntimeError):
    """Fail-closed rejection of an entry admission."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class DeliveryOutcome(StrEnum):
    """Post-claim delivery truth recorded without any network access."""

    SUBMISSION_AMBIGUOUS = "SUBMISSION_AMBIGUOUS"
    BROKER_ACK = "BROKER_ACK"


@dataclass(frozen=True)
class AdmissionContext:
    """Injected CAS/state context for one admission."""

    available_cash_cents: int
    active_authorization_id: str
    active_authorization_version: int
    active_envelope_hash: str
    policy_activation_hash: str
    authorization_status_version: int
    authorization_status_hash: str
    writer_fencing_epoch: int


@dataclass(frozen=True)
class StageLossTruth:
    """One stage-loss budget's current version and latch."""

    research_program_id: str
    economic_lineage_id: str
    stage_id: str
    stage_loss_budget_id: str
    stage_loss_version: int
    stage_loss_latch: StageLossLatchState


@dataclass(frozen=True)
class GatewayTruthContext:
    """Injected current authority/capital/risk/stage/fence truth.

    The gateway revalidates every permit and send claim against this
    bundle inside the linearizing transaction; any drift or halt fails
    closed.
    """

    policy_activation_hash: str
    trust_bundle_hash: str
    registry_epoch: int
    policy_epoch: int
    authority_epoch: int
    risk_epoch: int
    active_authorization_id: str
    active_authorization_version: int
    active_envelope_hash: str
    authorization_lifecycle: AuthorizationLifecycle
    authorization_status_version: int
    authorization_status_hash: str
    entry_fence_id: str
    entry_fence_hash: str
    entry_fence_version: int
    capital_version: int
    capital_stream_version: int
    risk_snapshot_artifact_hash: str
    risk_latch: RiskLatchState
    reconciliation_latch: ReconciliationLatchState
    stage_loss_states: tuple[StageLossTruth, ...]
    writer_fencing_epoch: int


@dataclass(frozen=True)
class SealedEntry:
    """The admitted seal with its reservation totals."""

    seal: PortfolioDecisionSeal
    total_reserved_cash_cents: int


@dataclass(frozen=True)
class PermittedEntry:
    """The permitted seal state after one permit transaction."""

    seal_id: str
    permit_id: str
    permit_nonce: str
    permit_nonce_state: str
    seal_status: str
    total_remaining_reserve_cents: int
    total_released_reserve_cents: int


@dataclass(frozen=True)
class DurableOutbox:
    """One durable outbox batch bound to its permit nonce."""

    outbox_batch_id: str
    seal_id: str
    permit_nonce: str
    payload_hash: str
    state: str


@dataclass(frozen=True)
class ClaimedSend:
    """The immutable payload binding released by one send claim."""

    seal_id: str
    permit_id: str
    permit_nonce: str
    outbox_batch_id: str
    outbox_payload_hash: str
    client_order_ids: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class EntryStateProjection:
    """Read-only projection of one entry's send-right state machine."""

    seal_id: str
    status: str
    permit_nonce_state: str | None
    outbox_state: str | None
    send_claim_sequence: int
    remaining_reserved_cash_cents: int


class CapitalGateway:
    """Entry admission and send-right linearization point."""

    def __init__(
        self,
        *,
        database_path: str,
        clock: Callable[[], datetime],
        _fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self._clock = clock
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

    # -- Task 5: atomic admission -------------------------------------------

    def publish_entry(
        self,
        seal: PortfolioDecisionSeal,
        *,
        expected_versions: GatewayExpectedVersions,
        context: AdmissionContext,
    ) -> SealedEntry:
        """Atomically admit one proposal: CAS, reserve, seal.

        Any failure rolls back all three; nothing partial persists.
        """

        self._validate_cas_bundle(seal, expected_versions, context)
        # Snapshot at admission time. The live worst-case reserve truth
        # is always SUM(entry_reserves.reserved_cash_cents); permits,
        # cancellations, and claims mutate only the line allocations.
        total_reserved = int(seal.total_reserved_cash_cents)
        if total_reserved > context.available_cash_cents:
            raise CapitalGatewayError(
                "reserve_insufficient",
                "worst-case reserve exceeds available capital",
                required_cents=total_reserved,
                available_cents=context.available_cash_cents,
            )
        logical_key = seal.logical_key
        with self._engine.begin() as conn:
            existing = self._latest_seal_row(conn, logical_key)
            if existing is not None:
                if str(existing.proposal_artifact_hash) == (
                    seal.proposal_artifact_hash
                ):
                    # Idempotent identical rerun: return the committed seal.
                    if str(existing.seal_id) != seal.seal_id:
                        raise CapitalGatewayError(
                            "seal_identity_conflict",
                            "same proposal already sealed under a different"
                            " seal identity",
                        )
                    if int(existing.seal_revision) != seal.seal_revision:
                        raise CapitalGatewayError(
                            "seal_revision_conflict",
                            "identical proposal already sealed at another"
                            " revision",
                        )
                    return SealedEntry(
                        seal=seal,
                        total_reserved_cash_cents=int(
                            existing.total_reserved_cash_cents
                        ),
                    )
                self._require_supersede_allowed(
                    conn, seal, existing, expected_versions
                )
            elif (
                expected_versions.expected_active_seal_id is not None
            ):
                raise CapitalGatewayError(
                    "seal_cas_conflict",
                    "expected an active seal but none exists",
                )
            if existing is not None:
                conn.execute(
                    sa.text(
                        "UPDATE decision_seals SET status = 'SUPERSEDED'"
                        " WHERE seal_id = :seal_id"
                    ),
                    {"seal_id": str(existing.seal_id)},
                )
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO decision_seals (seal_id, portfolio_id,"
                        " signal_session, decision_cycle_id, seal_revision,"
                        " seal_artifact_hash, proposal_artifact_hash,"
                        " status, total_reserved_cash_cents,"
                        " supersedes_seal_id, created_at)"
                        " VALUES (:seal_id, :portfolio, :session, :cycle,"
                        " :revision, :seal_hash, :proposal_hash, 'SEALED',"
                        " :reserved, :supersedes, :created_at)"
                    ),
                    {
                        "seal_id": seal.seal_id,
                        "portfolio": logical_key.portfolio_id,
                        "session": logical_key.signal_session.isoformat(),
                        "cycle": logical_key.decision_cycle_id,
                        "revision": seal.seal_revision,
                        "seal_hash": seal.artifact_hash(),
                        "proposal_hash": seal.proposal_artifact_hash,
                        "reserved": total_reserved,
                        "supersedes": seal.supersedes_seal_id,
                        "created_at": self._clock().isoformat(),
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise CapitalGatewayError(
                    "seal_race_conflict",
                    "another seal landed on the same economic key first",
                ) from exc
            reservation_id = seal.reservation_id
            for line in seal.line_reserve_bindings:
                conn.execute(
                    sa.text(
                        "INSERT INTO entry_reserves (reservation_id,"
                        " seal_id, order_line_id,"
                        " reservation_allocation_id, reserved_cash_cents,"
                        " created_at)"
                        " VALUES (:reservation, :seal, :line, :allocation,"
                        " :reserved, :created_at)"
                    ),
                    {
                        "reservation": (
                            f"{reservation_id}:{line.order_line_id}"
                        ),
                        "seal": seal.seal_id,
                        "line": line.order_line_id,
                        "allocation": line.reservation_allocation_id,
                        "reserved": int(line.reserved_cash_cents),
                        "created_at": self._clock().isoformat(),
                    },
                )
        return SealedEntry(
            seal=seal, total_reserved_cash_cents=total_reserved
        )

    def _validate_cas_bundle(
        self,
        seal: PortfolioDecisionSeal,
        expected: GatewayExpectedVersions,
        context: AdmissionContext,
    ) -> None:
        if seal.consumed_gateway_expected_versions.artifact_hash() != (
            expected.artifact_hash()
        ):
            raise CapitalGatewayError(
                "expected_versions_mismatch",
                "seal does not consume the presented CAS bundle",
            )
        if seal.policy_activation_hash != context.policy_activation_hash:
            raise CapitalGatewayError(
                "policy_activation_mismatch",
                "seal policy activation differs from the active policy",
            )
        if seal.authorization_id != context.active_authorization_id or (
            seal.authorization_version
            != context.active_authorization_version
        ):
            raise CapitalGatewayError(
                "authorization_mismatch",
                "seal authorization differs from the active envelope",
            )
        if seal.authorization_envelope_hash != (
            context.active_envelope_hash
        ):
            raise CapitalGatewayError(
                "envelope_mismatch",
                "seal envelope hash differs from the active envelope",
            )
        if seal.authorization_status_version != (
            context.authorization_status_version
        ) or seal.authorization_status_hash != (
            context.authorization_status_hash
        ):
            raise CapitalGatewayError(
                "authorization_status_stale",
                "seal consumed a stale authorization status",
            )
        if seal.writer_fencing_epoch != context.writer_fencing_epoch:
            raise CapitalGatewayError(
                "writer_fencing_epoch_mismatch",
                "seal writer fencing epoch differs from the gateway",
            )
        if expected.policy_epoch != seal.policy_epoch or (
            expected.authority_epoch != seal.authority_epoch
        ) or expected.risk_epoch != seal.risk_epoch:
            raise CapitalGatewayError(
                "epoch_mismatch",
                "CAS bundle epochs differ from the seal",
            )

    def _require_supersede_allowed(
        self,
        conn: sa.engine.Connection,
        seal: PortfolioDecisionSeal,
        existing,
        expected: GatewayExpectedVersions,
    ) -> None:
        if str(existing.status) != "SEALED":
            raise CapitalGatewayError(
                "supersede_forbidden_after_permit",
                "seals beyond SEALED state cannot be superseded",
            )
        if (
            expected.expected_active_seal_id is None
            or expected.expected_active_seal_revision is None
            or expected.expected_active_seal_artifact_hash is None
        ):
            raise CapitalGatewayError(
                "supersede_requires_expected_binding",
                "supersede must declare the expected active seal",
            )
        if expected.expected_active_seal_id != str(existing.seal_id) or (
            expected.expected_active_seal_revision
            != int(existing.seal_revision)
        ) or expected.expected_active_seal_artifact_hash != str(
            existing.seal_artifact_hash
        ):
            raise CapitalGatewayError(
                "seal_cas_conflict",
                "expected active seal does not match the registry;"
                " another supersede landed first",
            )
        if seal.seal_revision != int(existing.seal_revision) + 1:
            raise CapitalGatewayError(
                "seal_revision_not_successor",
                "superseding seal revision must be the exact successor",
            )
        if seal.supersedes_seal_id != str(existing.seal_id):
            raise CapitalGatewayError(
                "supersede_binding_mismatch",
                "seal supersedes binding must name the active seal",
            )
        # Mechanical shrink check: a supersede may never increase total
        # sealed quantity or reserved cash.
        if int(seal.total_reserved_cash_cents) > int(
            existing.total_reserved_cash_cents
        ):
            raise CapitalGatewayError(
                "supersede_increases_reserve",
                "supersede cannot increase the worst-case reserve",
            )

    # -- Task 6: permit issuance ---------------------------------------------

    def issue_permit(
        self, permit: ExecutionPermit, *, context: GatewayTruthContext
    ) -> PermittedEntry:
        """Permit one sealed plan: preserve, shrink, or cancel it.

        ALLOW moves the seal SEALED -> PERMITTED and releases any shrunk
        reserve; CANCEL tombstones the seal and releases the entire
        reserve. The permit nonce starts ACTIVE (ALLOW) or lands directly
        INVALIDATED (CANCEL). Any failure rolls back everything.

        Identical replays of an already-committed permit are idempotent
        as long as the presented gateway truth still matches the permit
        evaluation; once truth has drifted the replay fails closed.
        """

        self._require_issue_truth(permit, context)
        evaluation = permit.evaluation_state
        allow = permit.disposition is PermitDisposition.ALLOW
        post_nonce_state = (
            PermitNonceState.ACTIVE
            if allow
            else PermitNonceState.INVALIDATED
        )
        target_status = "PERMITTED" if allow else "TOMBSTONED"
        with self._engine.begin() as conn:
            seal_row = self._seal_row(conn, permit.seal_id)
            if seal_row is None:
                raise CapitalGatewayError(
                    "seal_unknown", "no seal for id"
                )
            existing_permit = self._permit_row(conn, permit.permit_id)
            if existing_permit is not None:
                if str(existing_permit.permit_artifact_hash) == (
                    permit.artifact_hash()
                ):
                    # Idempotent identical replay: return the committed
                    # permit regardless of lifecycle progress.
                    return PermittedEntry(
                        seal_id=permit.seal_id,
                        permit_id=permit.permit_id,
                        permit_nonce=str(existing_permit.permit_nonce),
                        permit_nonce_state=str(
                            existing_permit.permit_nonce_state
                        ),
                        seal_status=str(seal_row.status),
                        total_remaining_reserve_cents=int(
                            existing_permit.total_remaining_reserve_cents
                        ),
                        total_released_reserve_cents=int(
                            existing_permit.total_released_reserve_cents
                        ),
                    )
                raise CapitalGatewayError(
                    "permit_identity_conflict",
                    "permit id already issued with different content",
                )
            if (
                str(seal_row.status) != "SEALED"
                or int(seal_row.seal_revision) != permit.seal_revision
                or str(seal_row.seal_artifact_hash)
                != permit.seal_artifact_hash
            ):
                raise CapitalGatewayError(
                    "permit_stale_seal",
                    "permit must bind the exact active sealed revision",
                )
            stored_allocations = self._stored_allocations(
                conn, permit.seal_id
            )
            evaluation_allocations = tuple(
                (
                    item.order_line_id,
                    item.reservation_allocation_id,
                    int(item.reserved_cash_cents),
                )
                for item in evaluation.reservation_allocations
            )
            if stored_allocations != evaluation_allocations:
                raise CapitalGatewayError(
                    "permit_allocation_conflict",
                    "permit evaluation consumed stale reserve allocations;"
                    " the store truth differs",
                )
            if self._stored_reservation_id(conn, permit.seal_id) != (
                evaluation.reservation_id
            ):
                raise CapitalGatewayError(
                    "permit_allocation_conflict",
                    "permit evaluation consumed a stale reservation id",
                )
            conn.execute(
                sa.text(
                    "INSERT INTO entry_permits (permit_id, seal_id,"
                    " permit_nonce, permit_nonce_sequence,"
                    " permit_nonce_state, disposition,"
                    " permit_artifact_hash, total_remaining_reserve_cents,"
                    " total_released_reserve_cents, permit_expires_at,"
                    " issued_at, created_at)"
                    " VALUES (:permit_id, :seal_id, :nonce, :sequence,"
                    " :nonce_state, :disposition, :artifact,"
                    " :remaining, :released, :expires, :issued,"
                    " :created_at)"
                ),
                {
                    "permit_id": permit.permit_id,
                    "seal_id": permit.seal_id,
                    "nonce": permit.permit_nonce,
                    "sequence": permit.permit_nonce_sequence,
                    "nonce_state": post_nonce_state.value,
                    "disposition": permit.disposition.value,
                    "artifact": permit.artifact_hash(),
                    "remaining": int(permit.total_remaining_reserve_cents),
                    "released": int(permit.total_released_reserve_cents),
                    "expires": permit.permit_expires_at.isoformat(),
                    "issued": permit.issued_at.isoformat(),
                    "created_at": self._clock().isoformat(),
                },
            )
            self._fault("issue.after_permit_row")
            for line in permit.permit_lines:
                conn.execute(
                    sa.text(
                        "INSERT INTO entry_permit_lines (permit_id,"
                        " order_line_id, permitted_quantity_units,"
                        " client_order_id, remaining_reserve_cents)"
                        " VALUES (:permit_id, :line, :quantity, :client,"
                        " :remaining)"
                    ),
                    {
                        "permit_id": permit.permit_id,
                        "line": line.order_line_id,
                        "quantity": int(line.permitted_quantity_units),
                        "client": line.client_order_id,
                        "remaining": int(line.remaining_reserve_cents),
                    },
                )
            self._fault("issue.after_line_rows")
            remaining_by_line = {
                line.order_line_id: int(line.remaining_reserve_cents)
                for line in permit.permit_lines
            }
            for order_line_id, remaining in remaining_by_line.items():
                conn.execute(
                    sa.text(
                        "UPDATE entry_reserves SET reserved_cash_cents ="
                        " :remaining WHERE seal_id = :seal AND"
                        " order_line_id = :line"
                    ),
                    {
                        "remaining": remaining,
                        "seal": permit.seal_id,
                        "line": order_line_id,
                    },
                )
            self._fault("issue.after_reserve_update")
            updated = conn.execute(
                sa.text(
                    "UPDATE decision_seals SET status = :status"
                    " WHERE seal_id = :seal AND status = 'SEALED'"
                ),
                {"status": target_status, "seal": permit.seal_id},
            )
            if updated.rowcount != 1:
                raise CapitalGatewayError(
                    "permit_stale_seal",
                    "seal left SEALED before permit commit; another"
                    " permit landed first",
                )
            self._fault("issue.after_seal_status")
        return PermittedEntry(
            seal_id=permit.seal_id,
            permit_id=permit.permit_id,
            permit_nonce=permit.permit_nonce,
            permit_nonce_state=post_nonce_state.value,
            seal_status=target_status,
            total_remaining_reserve_cents=int(
                permit.total_remaining_reserve_cents
            ),
            total_released_reserve_cents=int(
                permit.total_released_reserve_cents
            ),
        )

    def _require_issue_truth(
        self, permit: ExecutionPermit, context: GatewayTruthContext
    ) -> None:
        """Fail-closed revalidation of deadlines, halts, and CAS truth."""

        now = self._clock()
        window = permit.execution_window
        if now > window.permit_issue_deadline:
            raise CapitalGatewayError(
                "permit_issue_deadline_missed",
                "permit issuance landed after the trusted issue deadline",
            )
        if now >= permit.permit_expires_at:
            raise CapitalGatewayError(
                "permit_expired",
                "permit expiry passed before issuance landed",
            )
        evaluation = permit.evaluation_state
        allow = permit.disposition is PermitDisposition.ALLOW
        if allow:
            self._require_no_halts(context)
            if context.authorization_lifecycle is not (
                AuthorizationLifecycle.ACTIVE
            ):
                raise CapitalGatewayError(
                    "authorization_not_active",
                    "ALLOW requires an active authorization lifecycle",
                )
        self._require_equal_truth(
            evaluation,
            context,
            risk_hash=evaluation.risk_snapshot_artifact_hash,
        )

    def _require_no_halts(self, context: GatewayTruthContext) -> None:
        if context.risk_latch is not RiskLatchState.CLEAR:
            raise CapitalGatewayError(
                "risk_halt_blocks_send",
                "risk halt blocks the send-right transition",
            )
        if context.reconciliation_latch is not (
            ReconciliationLatchState.CLEAR
        ):
            raise CapitalGatewayError(
                "reconciliation_halt_blocks_send",
                "reconciliation halt blocks the send-right transition",
            )
        if any(
            stage.stage_loss_latch is not StageLossLatchState.CLEAR
            for stage in context.stage_loss_states
        ):
            raise CapitalGatewayError(
                "stage_halt_blocks_send",
                "stage loss halt blocks the send-right transition",
            )

    def _require_equal_truth(
        self,
        claimed,
        context: GatewayTruthContext,
        *,
        risk_hash: str,
    ) -> None:
        """Compare one claimed truth bundle against the gateway truth.

        Frozen permit artifacts (authorization revalidation, evidence
        merkle root, outbox bindings) are not live gateway truth; they
        are bound through the permit artifact hash itself and are not
        re-compared here.
        """

        bindings = (
            (
                "policy_activation_stale",
                claimed.policy_activation_hash,
                context.policy_activation_hash,
            ),
            (
                "trust_bundle_stale",
                claimed.trust_bundle_hash,
                context.trust_bundle_hash,
            ),
            (
                "trust_bundle_stale",
                claimed.registry_epoch,
                context.registry_epoch,
            ),
            ("epoch_stale", claimed.policy_epoch, context.policy_epoch),
            (
                "epoch_stale",
                claimed.authority_epoch,
                context.authority_epoch,
            ),
            ("epoch_stale", claimed.risk_epoch, context.risk_epoch),
            (
                "authorization_stale",
                claimed.authorization_id,
                context.active_authorization_id,
            ),
            (
                "authorization_stale",
                claimed.authorization_version,
                context.active_authorization_version,
            ),
            (
                "authorization_stale",
                claimed.authorization_lifecycle,
                context.authorization_lifecycle,
            ),
            (
                "envelope_stale",
                claimed.authorization_envelope_hash,
                context.active_envelope_hash,
            ),
            (
                "authorization_status_stale",
                claimed.authorization_status_version,
                context.authorization_status_version,
            ),
            (
                "authorization_status_stale",
                claimed.authorization_status_hash,
                context.authorization_status_hash,
            ),
            (
                "entry_fence_stale",
                claimed.entry_fence_id,
                context.entry_fence_id,
            ),
            (
                "entry_fence_stale",
                claimed.entry_fence_hash,
                context.entry_fence_hash,
            ),
            (
                "entry_fence_stale",
                claimed.entry_fence_version,
                context.entry_fence_version,
            ),
            (
                "writer_fencing_epoch_mismatch",
                claimed.writer_fencing_epoch,
                context.writer_fencing_epoch,
            ),
            (
                "capital_version_stale",
                claimed.capital_version,
                context.capital_version,
            ),
            (
                "capital_stream_stale",
                claimed.capital_stream_version,
                context.capital_stream_version,
            ),
        )
        for code, claimed_value, current in bindings:
            if claimed_value != current:
                raise CapitalGatewayError(
                    code,
                    "gateway truth drifted from the permit evaluation",
                    claimed=claimed_value,
                    current=current,
                )
        claimed_stages = {
            (
                item.research_program_id,
                item.economic_lineage_id,
                item.stage_id,
                item.stage_loss_budget_id,
            ): (item.stage_loss_version, item.stage_loss_latch)
            for item in claimed.stage_loss_bindings
        }
        current_stages = {
            (
                item.research_program_id,
                item.economic_lineage_id,
                item.stage_id,
                item.stage_loss_budget_id,
            ): (item.stage_loss_version, item.stage_loss_latch)
            for item in context.stage_loss_states
        }
        if claimed_stages != current_stages:
            raise CapitalGatewayError(
                "stage_loss_stale",
                "stage loss versions or latches drifted from the permit",
            )
        if risk_hash != context.risk_snapshot_artifact_hash:
            raise CapitalGatewayError(
                "risk_snapshot_stale",
                "current risk snapshot drifted from the permit evaluation",
            )

    # -- Task 6: durable outbox ----------------------------------------------

    def make_outbox_durable(self, permit: ExecutionPermit) -> DurableOutbox:
        """Persist the permit's frozen outbox batch (PERMITTED -> OUTBOX_DURABLE).

        The batch id, payload hash, and nonce binding come from the
        immutable permit; replays with identical bindings are idempotent.
        """

        now = self._clock()
        if now >= permit.permit_expires_at:
            raise CapitalGatewayError(
                "permit_expired",
                "permit expiry passed before outbox durability",
            )
        expected = permit.send_claim_expected_versions
        if (
            permit.disposition is not PermitDisposition.ALLOW
            or expected is None
            or expected.outbox_batch_id is None
            or expected.outbox_payload_hash is None
        ):
            raise CapitalGatewayError(
                "outbox_requires_sendable",
                "only ALLOW permits with sendable lines carry an outbox",
            )
        batch_id = expected.outbox_batch_id
        payload_hash = expected.outbox_payload_hash
        with self._engine.begin() as conn:
            seal_row = self._seal_row(conn, permit.seal_id)
            if seal_row is None:
                raise CapitalGatewayError(
                    "seal_unknown", "no seal for id"
                )
            existing = conn.execute(
                sa.text(
                    "SELECT * FROM entry_outbox"
                    " WHERE outbox_batch_id = :batch"
                ),
                {"batch": batch_id},
            ).first()
            if existing is not None:
                if (
                    str(existing.seal_id) == permit.seal_id
                    and str(existing.permit_id) == permit.permit_id
                    and str(existing.permit_nonce) == permit.permit_nonce
                    and str(existing.payload_hash) == payload_hash
                ):
                    return DurableOutbox(
                        outbox_batch_id=batch_id,
                        seal_id=permit.seal_id,
                        permit_nonce=permit.permit_nonce,
                        payload_hash=payload_hash,
                        state=str(existing.state),
                    )
                raise CapitalGatewayError(
                    "outbox_identity_conflict",
                    "outbox batch id already bound to different content",
                )
            if str(seal_row.status) != "PERMITTED":
                raise CapitalGatewayError(
                    "outbox_requires_permitted",
                    "outbox durability requires a PERMITTED seal",
                )
            permit_row = self._permit_row(conn, permit.permit_id)
            if (
                permit_row is None
                or str(permit_row.seal_id) != permit.seal_id
                or str(permit_row.permit_artifact_hash)
                != permit.artifact_hash()
                or str(permit_row.permit_nonce) != permit.permit_nonce
                or str(permit_row.permit_nonce_state)
                != PermitNonceState.ACTIVE.value
            ):
                raise CapitalGatewayError(
                    "permit_cas_conflict",
                    "outbox must bind the exact active permit",
                )
            conn.execute(
                sa.text(
                    "INSERT INTO entry_outbox (outbox_batch_id, seal_id,"
                    " permit_id, permit_nonce, payload_hash, state,"
                    " created_at) VALUES (:batch, :seal, :permit, :nonce,"
                    " :payload, 'DURABLE', :created_at)"
                ),
                {
                    "batch": batch_id,
                    "seal": permit.seal_id,
                    "permit": permit.permit_id,
                    "nonce": permit.permit_nonce,
                    "payload": payload_hash,
                    "created_at": self._clock().isoformat(),
                },
            )
            self._fault("outbox.after_row")
            updated = conn.execute(
                sa.text(
                    "UPDATE decision_seals SET status = 'OUTBOX_DURABLE'"
                    " WHERE seal_id = :seal AND status = 'PERMITTED'"
                ),
                {"seal": permit.seal_id},
            )
            if updated.rowcount != 1:
                raise CapitalGatewayError(
                    "outbox_requires_permitted",
                    "seal left PERMITTED before outbox commit",
                )
            self._fault("outbox.after_seal_status")
        return DurableOutbox(
            outbox_batch_id=batch_id,
            seal_id=permit.seal_id,
            permit_nonce=permit.permit_nonce,
            payload_hash=payload_hash,
            state=OutboxState.DURABLE.value,
        )

    # -- Task 6: final send-right linearization -------------------------------

    def claim_send(
        self,
        permit: ExecutionPermit,
        expected_versions: SendClaimExpectedVersions,
        *,
        context: GatewayTruthContext,
    ) -> ClaimedSend:
        """Consume the permit nonce and linearize the final send right.

        One transaction revalidates the active seal, permit, durable
        outbox, reserve allocations, deadlines, and the complete
        authority/capital/risk/stage/fence truth. No network call occurs
        here; the returned binding is the exact immutable payload the
        owner may send after commit, always under the claimed client ids.
        """

        now = self._clock()
        with self._engine.begin() as conn:
            seal_row = self._seal_row(
                conn, expected_versions.active_seal_id
            )
            if seal_row is None:
                raise CapitalGatewayError(
                    "seal_unknown", "no seal for id"
                )
            if (
                int(seal_row.seal_revision)
                != expected_versions.active_seal_revision
                or str(seal_row.seal_artifact_hash)
                != expected_versions.active_seal_artifact_hash
            ):
                raise CapitalGatewayError(
                    "seal_cas_conflict",
                    "expected active seal does not match the registry",
                )
            permit_row = self._permit_row(
                conn, expected_versions.active_permit_id
            )
            if (
                permit_row is None
                or str(permit_row.seal_id) != seal_row.seal_id
                or str(permit_row.permit_artifact_hash)
                != permit.artifact_hash()
            ):
                raise CapitalGatewayError(
                    "permit_cas_conflict",
                    "send claim must present the exact active permit",
                )
            if str(permit_row.permit_nonce) != (
                expected_versions.active_permit_nonce
            ):
                raise CapitalGatewayError(
                    "permit_nonce_mismatch",
                    "send claim consumed the wrong permit nonce",
                )
            if str(permit_row.permit_nonce_state) != (
                PermitNonceState.ACTIVE.value
            ):
                raise CapitalGatewayError(
                    "send_claim_conflict",
                    "permit nonce is no longer ACTIVE",
                )
            if (
                int(permit_row.permit_nonce_sequence)
                != expected_versions.permit_nonce_sequence
                or str(permit_row.permit_nonce_state)
                != getattr(
                    expected_versions.permit_nonce_state,
                    "value",
                    expected_versions.permit_nonce_state,
                )
            ):
                raise CapitalGatewayError(
                    "permit_cas_conflict",
                    "permit nonce sequence or state drifted",
                )
            if str(seal_row.status) != "OUTBOX_DURABLE":
                raise CapitalGatewayError(
                    "outbox_not_durable",
                    "send claim requires an OUTBOX_DURABLE seal",
                )
            outbox_row = conn.execute(
                sa.text(
                    "SELECT * FROM entry_outbox"
                    " WHERE outbox_batch_id = :batch"
                ),
                {"batch": expected_versions.outbox_batch_id},
            ).first()
            if (
                outbox_row is None
                or str(outbox_row.seal_id) != seal_row.seal_id
                or str(outbox_row.state) != OutboxState.DURABLE.value
            ):
                raise CapitalGatewayError(
                    "outbox_not_durable",
                    "send claim requires the exact durable outbox",
                )
            if (
                str(outbox_row.payload_hash)
                != expected_versions.outbox_payload_hash
                or str(outbox_row.permit_nonce)
                != expected_versions.outbox_permit_nonce
                or str(outbox_row.state)
                != getattr(
                    expected_versions.outbox_state,
                    "value",
                    expected_versions.outbox_state,
                )
            ):
                raise CapitalGatewayError(
                    "outbox_cas_conflict",
                    "outbox payload, nonce, or state binding drifted",
                )
            stored_allocations = self._stored_allocations(
                conn, str(seal_row.seal_id)
            )
            expected_allocations = tuple(
                (
                    item.order_line_id,
                    item.reservation_allocation_id,
                    int(item.reserved_cash_cents),
                )
                for item in (
                    expected_versions.post_reservation_allocations
                )
            )
            if stored_allocations != expected_allocations:
                raise CapitalGatewayError(
                    "permit_allocation_conflict",
                    "send claim consumed stale reserve allocations;"
                    " the store truth differs",
                )
            if self._stored_reservation_id(conn, str(seal_row.seal_id)) != (
                expected_versions.reservation_id
            ):
                raise CapitalGatewayError(
                    "permit_allocation_conflict",
                    "send claim consumed a stale reservation id",
                )
            if now >= expected_versions.effective_send_deadline:
                raise CapitalGatewayError(
                    "send_deadline_missed",
                    "send claim landed after the effective send deadline",
                )
            self._require_no_halts(context)
            self._require_equal_truth(
                expected_versions,
                context,
                risk_hash=(
                    expected_versions.post_risk_snapshot_artifact_hash
                ),
            )
            updated = conn.execute(
                sa.text(
                    "UPDATE decision_seals SET status = 'SEND_CLAIMED'"
                    " WHERE seal_id = :seal AND status = 'OUTBOX_DURABLE'"
                ),
                {"seal": str(seal_row.seal_id)},
            )
            if updated.rowcount != 1:
                raise CapitalGatewayError(
                    "send_claim_conflict",
                    "another dispatcher claimed the send right first",
                )
            self._fault("claim.after_seal_status")
            consumed = conn.execute(
                sa.text(
                    "UPDATE entry_permits SET permit_nonce_state ="
                    " 'CONSUMED' WHERE permit_id = :permit AND"
                    " permit_nonce_state = 'ACTIVE'"
                ),
                {"permit": str(permit_row.permit_id)},
            )
            if consumed.rowcount != 1:
                raise CapitalGatewayError(
                    "send_claim_conflict",
                    "permit nonce was consumed by another claim",
                )
            self._fault("claim.after_nonce_consumed")
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO send_claims (seal_id, permit_id,"
                        " permit_nonce, outbox_batch_id,"
                        " send_claim_sequence, claimed_at)"
                        " VALUES (:seal, :permit, :nonce, :batch,"
                        " :sequence, :claimed_at)"
                    ),
                    {
                        "seal": str(seal_row.seal_id),
                        "permit": str(permit_row.permit_id),
                        "nonce": str(permit_row.permit_nonce),
                        "batch": expected_versions.outbox_batch_id,
                        "sequence": 1,
                        "claimed_at": self._clock().isoformat(),
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise CapitalGatewayError(
                    "send_claim_conflict",
                    "send right already claimed for this entry",
                ) from exc
            client_order_ids: list[tuple[str, str]] = []
            for line in permit.permit_lines:
                if (
                    line.permitted_quantity_units > 0
                    and line.client_order_id is not None
                ):
                    conn.execute(
                        sa.text(
                            "INSERT INTO send_claim_lines (seal_id,"
                            " order_line_id, client_order_id)"
                            " VALUES (:seal, :line, :client)"
                        ),
                        {
                            "seal": str(seal_row.seal_id),
                            "line": line.order_line_id,
                            "client": line.client_order_id,
                        },
                    )
                    client_order_ids.append(
                        (line.order_line_id, line.client_order_id)
                    )
            self._fault("claim.after_claim_rows")
        return ClaimedSend(
            seal_id=str(seal_row.seal_id),
            permit_id=permit.permit_id,
            permit_nonce=permit.permit_nonce,
            outbox_batch_id=expected_versions.outbox_batch_id,
            outbox_payload_hash=expected_versions.outbox_payload_hash,
            client_order_ids=tuple(client_order_ids),
        )

    # -- Task 6: cancellation before claim ------------------------------------

    def cancel_unclaimed_entry(
        self, receipt: EntryCancellationReceipt
    ) -> None:
        """Tombstone one unclaimed ALLOW permit/outbox atomically.

        Legal while the seal is PERMITTED or OUTBOX_DURABLE; after
        SEND_CLAIMED the entry is already in-flight risk and can never be
        cancelled. Identical receipt replays are idempotent.
        """

        seal_id = receipt.prior_permit.seal_id
        binding = receipt.cancellation_binding
        evaluation = receipt.evaluation_state
        with self._engine.begin() as conn:
            seal_row = self._seal_row(conn, seal_id)
            if seal_row is None:
                raise CapitalGatewayError(
                    "seal_unknown", "no seal for id"
                )
            permit_row = self._permit_row(conn, receipt.permit_id)
            status = str(seal_row.status)
            if status == "TOMBSTONED":
                if (
                    permit_row is not None
                    and str(permit_row.cancel_receipt_id or "")
                    == receipt.cancellation_receipt_id
                    and str(permit_row.cancel_receipt_artifact_hash or "")
                    == receipt.artifact_hash()
                ):
                    return  # idempotent identical replay
                raise CapitalGatewayError(
                    "cancel_state_conflict",
                    "entry already tombstoned by another cancellation",
                )
            if status not in {"PERMITTED", "OUTBOX_DURABLE"}:
                if status in _CLAIMABLE_SEAL_STATUSES:
                    raise CapitalGatewayError(
                        "cancel_forbidden_after_claim",
                        "claimed entries are in-flight risk and cannot be"
                        " cancelled",
                    )
                raise CapitalGatewayError(
                    "cancel_state_conflict",
                    "cancellation requires a PERMITTED or OUTBOX_DURABLE"
                    " entry",
                )
            if (
                permit_row is None
                or str(permit_row.seal_id) != seal_id
                or str(permit_row.disposition)
                != PermitDisposition.ALLOW.value
                or str(permit_row.permit_nonce) != receipt.permit_nonce
                or int(permit_row.permit_nonce_sequence)
                != receipt.permit_nonce_sequence
                or str(permit_row.permit_nonce_state)
                != PermitNonceState.ACTIVE.value
                or str(permit_row.permit_artifact_hash)
                != receipt.prior_permit_artifact_hash
            ):
                raise CapitalGatewayError(
                    "receipt_store_mismatch",
                    "receipt does not bind the exact active permit",
                )
            outbox_row = conn.execute(
                sa.text(
                    "SELECT * FROM entry_outbox WHERE seal_id = :seal"
                    " ORDER BY created_at DESC LIMIT 1"
                ),
                {"seal": seal_id},
            ).first()
            if outbox_row is None:
                if binding.outbox_batch_id is not None:
                    raise CapitalGatewayError(
                        "receipt_store_mismatch",
                        "receipt invented an outbox the store never held",
                    )
                if evaluation.active_outbox_batch_id is not None:
                    raise CapitalGatewayError(
                        "receipt_store_mismatch",
                        "receipt evaluation claims an outbox the store"
                        " never held",
                    )
            else:
                if (
                    binding.outbox_batch_id != str(outbox_row.outbox_batch_id)
                    or binding.outbox_payload_hash
                    != str(outbox_row.payload_hash)
                    or binding.post_outbox_state is not OutboxState.TOMBSTONED
                ):
                    raise CapitalGatewayError(
                        "receipt_store_mismatch",
                        "receipt must tombstone the exact current outbox",
                    )
            stored_allocations = self._stored_allocations(conn, seal_id)
            evaluation_allocations = tuple(
                (
                    item.order_line_id,
                    item.reservation_allocation_id,
                    int(item.reserved_cash_cents),
                )
                for item in evaluation.reservation_allocations
            )
            if stored_allocations != evaluation_allocations:
                raise CapitalGatewayError(
                    "receipt_store_mismatch",
                    "receipt evaluation consumed stale reserve allocations",
                )
            if self._stored_reservation_id(conn, seal_id) != (
                evaluation.reservation_id
            ):
                raise CapitalGatewayError(
                    "receipt_store_mismatch",
                    "receipt evaluation consumed a stale reservation id",
                )
            # First write owns the transition: the conditional UPDATE
            # revalidates the state under the write lock, so a concurrent
            # claim or cancellation that landed after the reads above is
            # caught here, before any reserve is released.
            tombstoned = conn.execute(
                sa.text(
                    "UPDATE decision_seals SET status = 'TOMBSTONED'"
                    " WHERE seal_id = :seal AND status IN"
                    " ('PERMITTED', 'OUTBOX_DURABLE')"
                ),
                {"seal": seal_id},
            )
            if tombstoned.rowcount != 1:
                current = self._seal_row(conn, seal_id)
                current_status = (
                    str(current.status) if current is not None else ""
                )
                if current_status == "TOMBSTONED":
                    fresh_permit = self._permit_row(
                        conn, receipt.permit_id
                    )
                    if (
                        fresh_permit is not None
                        and str(fresh_permit.cancel_receipt_id or "")
                        == receipt.cancellation_receipt_id
                        and str(
                            fresh_permit.cancel_receipt_artifact_hash or ""
                        )
                        == receipt.artifact_hash()
                    ):
                        return  # identical replay won the race
                if current_status in _CLAIMABLE_SEAL_STATUSES:
                    raise CapitalGatewayError(
                        "cancel_forbidden_after_claim",
                        "entry was claimed before the cancellation"
                        " landed",
                    )
                raise CapitalGatewayError(
                    "cancel_state_conflict",
                    "entry left the cancellable states before the"
                    " cancellation landed",
                )
            self._fault("cancel.after_seal_status")
            if outbox_row is not None:
                outbox_update = conn.execute(
                    sa.text(
                        "UPDATE entry_outbox SET state = 'TOMBSTONED',"
                        " tombstoned_at = :now"
                        " WHERE outbox_batch_id = :batch AND state ="
                        " 'DURABLE'"
                    ),
                    {
                        "now": self._clock().isoformat(),
                        "batch": str(outbox_row.outbox_batch_id),
                    },
                )
                if outbox_update.rowcount != 1:
                    raise CapitalGatewayError(
                        "cancel_race_conflict",
                        "outbox left DURABLE during cancellation",
                    )
                self._fault("cancel.after_outbox")
            permit_update = conn.execute(
                sa.text(
                    "UPDATE entry_permits SET permit_nonce_state ="
                    " 'INVALIDATED', cancel_receipt_id = :receipt_id,"
                    " cancel_receipt_artifact_hash = :receipt_hash"
                    " WHERE permit_id = :permit AND permit_nonce_state ="
                    " 'ACTIVE'"
                ),
                {
                    "receipt_id": receipt.cancellation_receipt_id,
                    "receipt_hash": receipt.artifact_hash(),
                    "permit": receipt.permit_id,
                },
            )
            if permit_update.rowcount != 1:
                raise CapitalGatewayError(
                    "cancel_race_conflict",
                    "permit nonce left ACTIVE during cancellation",
                )
            self._fault("cancel.after_permit_nonce")
            reserve_update = conn.execute(
                sa.text(
                    "UPDATE entry_reserves SET reserved_cash_cents = 0"
                    " WHERE seal_id = :seal"
                ),
                {"seal": seal_id},
            )
            if reserve_update.rowcount != len(evaluation_allocations):
                raise CapitalGatewayError(
                    "cancel_race_conflict",
                    "reserve allocations changed during cancellation",
                )
            self._fault("cancel.after_reserves")

    # -- Task 6: post-claim delivery truth ------------------------------------

    def record_delivery_outcome(
        self,
        seal_id: str,
        outcome: DeliveryOutcome,
        *,
        submission_client_order_ids: tuple[str, ...] | None = None,
    ) -> None:
        """Record SUBMISSION_AMBIGUOUS | BROKER_ACK without any network.

        The claimed client order ids are immutable: any recorded outcome
        that presents client ids must match the claimed set exactly.
        Retries never guess new ids.
        """

        with self._engine.begin() as conn:
            seal_row = self._seal_row(conn, seal_id)
            if seal_row is None:
                raise CapitalGatewayError(
                    "seal_unknown", "no seal for id"
                )
            status = str(seal_row.status)
            if status == "BROKER_ACK":
                raise CapitalGatewayError(
                    "delivery_state_conflict",
                    "broker acknowledgement is terminal",
                )
            if (
                status == "SUBMISSION_AMBIGUOUS"
                and outcome is DeliveryOutcome.SUBMISSION_AMBIGUOUS
            ):
                return  # idempotent ambiguous rerecord
            if status not in {"SEND_CLAIMED", "SUBMISSION_AMBIGUOUS"}:
                raise CapitalGatewayError(
                    "delivery_state_conflict",
                    "delivery outcomes only follow a claimed send",
                )
            if submission_client_order_ids is not None:
                claimed_rows = conn.execute(
                    sa.text(
                        "SELECT client_order_id FROM send_claim_lines"
                        " WHERE seal_id = :seal ORDER BY client_order_id"
                    ),
                    {"seal": seal_id},
                ).all()
                claimed = tuple(
                    str(row.client_order_id) for row in claimed_rows
                )
                if tuple(sorted(submission_client_order_ids)) != claimed:
                    raise CapitalGatewayError(
                        "client_order_id_mismatch",
                        "delivery retry must reuse the exact claimed"
                        " client order ids",
                    )
            updated = conn.execute(
                sa.text(
                    "UPDATE decision_seals SET status = :status"
                    " WHERE seal_id = :seal AND status = :precondition"
                ),
                {
                    "status": outcome.value,
                    "seal": seal_id,
                    "precondition": status,
                },
            )
            if updated.rowcount != 1:
                raise CapitalGatewayError(
                    "delivery_state_conflict",
                    "delivery state moved before the outcome landed",
                )

    # -- read-only projections -------------------------------------------------

    def entry_state(self, seal_id: str) -> EntryStateProjection | None:
        """Read-only projection of one entry's send-right state."""

        with self._engine.connect() as conn:
            seal_row = self._seal_row(conn, seal_id)
            if seal_row is None:
                return None
            permit_row = conn.execute(
                sa.text(
                    "SELECT permit_nonce_state FROM entry_permits"
                    " WHERE seal_id = :seal"
                    " ORDER BY permit_nonce_sequence DESC LIMIT 1"
                ),
                {"seal": seal_id},
            ).first()
            outbox_row = conn.execute(
                sa.text(
                    "SELECT state FROM entry_outbox WHERE seal_id = :seal"
                    " ORDER BY created_at DESC LIMIT 1"
                ),
                {"seal": seal_id},
            ).first()
            claim_row = conn.execute(
                sa.text(
                    "SELECT send_claim_sequence FROM send_claims"
                    " WHERE seal_id = :seal"
                ),
                {"seal": seal_id},
            ).first()
            reserve_row = conn.execute(
                sa.text(
                    "SELECT COALESCE(SUM(reserved_cash_cents), 0) AS total"
                    " FROM entry_reserves WHERE seal_id = :seal"
                ),
                {"seal": seal_id},
            ).one()
        return EntryStateProjection(
            seal_id=seal_id,
            status=str(seal_row.status),
            permit_nonce_state=(
                str(permit_row.permit_nonce_state)
                if permit_row is not None
                else None
            ),
            outbox_state=(
                str(outbox_row.state) if outbox_row is not None else None
            ),
            send_claim_sequence=(
                int(claim_row.send_claim_sequence)
                if claim_row is not None
                else 0
            ),
            remaining_reserved_cash_cents=int(reserve_row.total),
        )

    def active_seal(
        self, logical_key: DecisionLogicalKey
    ) -> tuple[str, int] | None:
        """Read-only projection: the active seal id/revision for one key."""

        with self._engine.connect() as conn:
            row = self._active_seal_row(conn, logical_key)
        if row is None:
            return None
        return str(row.seal_id), int(row.seal_revision)

    # -- shared helpers ---------------------------------------------------------

    def _seal_row(self, conn: sa.engine.Connection, seal_id: str):
        return conn.execute(
            sa.text(
                "SELECT * FROM decision_seals WHERE seal_id = :seal_id"
            ),
            {"seal_id": seal_id},
        ).first()

    def _permit_row(self, conn: sa.engine.Connection, permit_id: str):
        return conn.execute(
            sa.text(
                "SELECT * FROM entry_permits WHERE permit_id = :permit_id"
            ),
            {"permit_id": permit_id},
        ).first()

    def _stored_allocations(
        self, conn: sa.engine.Connection, seal_id: str
    ) -> tuple[tuple[str, str, int], ...]:
        rows = conn.execute(
            sa.text(
                "SELECT order_line_id, reservation_allocation_id,"
                " reserved_cash_cents FROM entry_reserves"
                " WHERE seal_id = :seal"
                " ORDER BY order_line_id, reservation_allocation_id"
            ),
            {"seal": seal_id},
        ).all()
        return tuple(
            (
                str(row.order_line_id),
                str(row.reservation_allocation_id),
                int(row.reserved_cash_cents),
            )
            for row in rows
        )

    def _stored_reservation_id(
        self, conn: sa.engine.Connection, seal_id: str
    ) -> str | None:
        row = conn.execute(
            sa.text(
                "SELECT reservation_id FROM entry_reserves"
                " WHERE seal_id = :seal LIMIT 1"
            ),
            {"seal": seal_id},
        ).first()
        if row is None:
            return None
        return str(row.reservation_id).split(":", 1)[0]

    def _active_seal_row(
        self, conn: sa.engine.Connection, logical_key: DecisionLogicalKey
    ):
        return conn.execute(
            sa.text(
                "SELECT * FROM decision_seals"
                " WHERE portfolio_id = :portfolio"
                " AND signal_session = :session"
                " AND decision_cycle_id = :cycle AND status = 'SEALED'"
            ),
            {
                "portfolio": logical_key.portfolio_id,
                "session": logical_key.signal_session.isoformat(),
                "cycle": logical_key.decision_cycle_id,
            },
        ).first()

    def _latest_seal_row(
        self, conn: sa.engine.Connection, logical_key: DecisionLogicalKey
    ):
        return conn.execute(
            sa.text(
                "SELECT * FROM decision_seals"
                " WHERE portfolio_id = :portfolio"
                " AND signal_session = :session"
                " AND decision_cycle_id = :cycle"
                " ORDER BY seal_revision DESC LIMIT 1"
            ),
            {
                "portfolio": logical_key.portfolio_id,
                "session": logical_key.signal_session.isoformat(),
                "cycle": logical_key.decision_cycle_id,
            },
        ).first()


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


__all__ = [
    "AdmissionContext",
    "CapitalGateway",
    "CapitalGatewayError",
    "ClaimedSend",
    "DeliveryOutcome",
    "DurableOutbox",
    "EntryStateProjection",
    "GatewayTruthContext",
    "PermittedEntry",
    "SealedEntry",
    "StageLossTruth",
]
