"""Public immutable execution lifecycle and broker-revision contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from .base import (
    CanonicalModel,
    ExactInteger,
    ExecutionMode,
    MoneyCents,
    QuantityUnits,
    SchemaVersion,
    Sha256,
    UtcInstant,
    domain_hash,
)
from .decision import (
    ClockHealth,
    DecisionLogicalKey,
    GatewayIssuerBinding,
    PortfolioDecisionSeal,
    StageAdmissionBinding,
    TrustedExecutionWindow,
    _validate_issuer_binding,
)
from .evidence import NonEmptyStr
from .risk import (
    ReconciliationLatchState,
    RiskLatchState,
    RiskSnapshotCompleteness,
    RiskSnapshotFreshness,
)
from .trust import ArtifactKind


PositiveInt = Annotated[ExactInteger, Field(ge=1)]
NonNegativeQuantity = Annotated[QuantityUnits, Field(ge=0)]
PositiveQuantity = Annotated[QuantityUnits, Field(gt=0)]
SignedQuantity = QuantityUnits
NonNegativeCents = Annotated[MoneyCents, Field(ge=0)]
PositiveCents = Annotated[MoneyCents, Field(gt=0)]


class PermitDisposition(StrEnum):
    ALLOW = "ALLOW"
    CANCEL = "CANCEL"


class PermitReasonCode(StrEnum):
    UNCHANGED = "UNCHANGED"
    AVAILABILITY_REDUCTION = "AVAILABILITY_REDUCTION"
    PRICE_REDUCTION = "PRICE_REDUCTION"
    CAPACITY_REDUCTION = "CAPACITY_REDUCTION"
    CASH_REDUCTION = "CASH_REDUCTION"
    CAPITAL_RISK_REDUCTION = "CAPITAL_RISK_REDUCTION"
    STAGE_HALT_CANCEL = "STAGE_HALT_CANCEL"
    RECONCILIATION_CANCEL = "RECONCILIATION_CANCEL"
    FACT_INTEGRITY_CANCEL = "FACT_INTEGRITY_CANCEL"
    AUTHORIZATION_CANCEL = "AUTHORIZATION_CANCEL"
    FENCE_CANCEL = "FENCE_CANCEL"
    DEADLINE_CANCEL = "DEADLINE_CANCEL"


_SHRINK_REASONS = frozenset(
    {
        PermitReasonCode.AVAILABILITY_REDUCTION,
        PermitReasonCode.PRICE_REDUCTION,
        PermitReasonCode.CAPACITY_REDUCTION,
        PermitReasonCode.CASH_REDUCTION,
        PermitReasonCode.CAPITAL_RISK_REDUCTION,
    }
)
_CANCEL_REASONS = frozenset(
    {
        PermitReasonCode.STAGE_HALT_CANCEL,
        PermitReasonCode.RECONCILIATION_CANCEL,
        PermitReasonCode.FACT_INTEGRITY_CANCEL,
        PermitReasonCode.AUTHORIZATION_CANCEL,
        PermitReasonCode.FENCE_CANCEL,
        PermitReasonCode.DEADLINE_CANCEL,
    }
)


class ExecutionPermitLine(CanonicalModel):
    """One seal line mechanically left unchanged, shrunk, or cancelled."""

    order_line_id: NonEmptyStr
    security_id: NonEmptyStr
    sealed_quantity_units: PositiveQuantity
    permitted_quantity_units: NonNegativeQuantity
    reason_code: PermitReasonCode
    predicate_policy_version: NonEmptyStr
    preopen_fact_snapshot_id: NonEmptyStr
    preopen_fact_snapshot_hash: Sha256
    preopen_fact_as_of: UtcInstant
    client_order_id: NonEmptyStr | None
    order_type: NonEmptyStr
    limit_price_cents: PositiveCents
    worst_case_price_cents: PositiveCents
    price_boundary_version: NonEmptyStr
    time_in_force: NonEmptyStr
    exit_session_ordinal: Literal[10]
    sealed_reserve_cents: PositiveCents
    remaining_reserve_cents: NonNegativeCents
    released_reserve_cents: NonNegativeCents

    @field_validator("exit_session_ordinal", mode="before")
    @classmethod
    def validate_native_t_plus_ten(cls, value: object) -> object:
        if type(value) is not int or value != 10:
            raise ValueError("T+10 session ordinal must be the native integer 10")
        return value

    @model_validator(mode="after")
    def validate_line(self) -> Self:
        if self.permitted_quantity_units > self.sealed_quantity_units:
            raise ValueError(
                "permitted line quantity cannot grow beyond sealed quantity"
            )
        fee_reserve = self.sealed_reserve_cents - (
            self.worst_case_price_cents * self.sealed_quantity_units
        )
        if fee_reserve < 0:
            raise ValueError("sealed reserve cannot be below sealed line notional")
        expected_remaining = (
            self.worst_case_price_cents * self.permitted_quantity_units
            + (fee_reserve if self.permitted_quantity_units > 0 else 0)
        )
        if self.remaining_reserve_cents != expected_remaining:
            raise ValueError("remaining reserve must exactly match permitted line")
        if (
            self.released_reserve_cents
            != self.sealed_reserve_cents - self.remaining_reserve_cents
        ):
            raise ValueError(
                "released reserve must exactly complement remaining reserve"
            )

        if self.permitted_quantity_units == self.sealed_quantity_units:
            if self.reason_code is not PermitReasonCode.UNCHANGED:
                raise ValueError("unchanged quantity requires UNCHANGED reason")
        elif self.permitted_quantity_units > 0:
            if self.reason_code not in _SHRINK_REASONS:
                raise ValueError(
                    "positive shrink requires a mechanical reduction reason"
                )
        elif self.reason_code not in _CANCEL_REASONS:
            raise ValueError("zero quantity requires a mechanical cancel reason")

        return self


class SendClaimExpectedVersions(CanonicalModel):
    """Complete frozen bundle that a future SEND_CLAIMED CAS must re-read."""

    active_seal_id: NonEmptyStr
    active_seal_revision: PositiveInt
    active_seal_artifact_hash: Sha256
    active_permit_id: NonEmptyStr
    active_permit_nonce: NonEmptyStr
    permit_nonce_sequence: PositiveInt
    permit_nonce_state: Literal["ACTIVE"]
    policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveInt
    policy_epoch: PositiveInt
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    authorization_id: NonEmptyStr
    authorization_version: PositiveInt
    authorization_envelope_hash: Sha256
    authorization_status: Literal["ACTIVE"]
    authorization_status_version: PositiveInt
    authorization_status_hash: Sha256
    authorization_revalidation_required: bool
    evidence_set_merkle_root: Sha256
    entry_fence_id: NonEmptyStr
    entry_fence_hash: Sha256
    entry_fence_version: Annotated[ExactInteger, Field(ge=0)]
    capital_version: PositiveInt
    capital_stream_version: PositiveInt
    risk_snapshot_id: NonEmptyStr
    risk_snapshot_artifact_hash: Sha256
    risk_snapshot_version: PositiveInt
    risk_snapshot_freshness: RiskSnapshotFreshness
    risk_snapshot_completeness: RiskSnapshotCompleteness
    risk_latch: RiskLatchState
    reconciliation_latch: ReconciliationLatchState
    stage_loss_bindings: Annotated[
        tuple[StageAdmissionBinding, ...], Field(min_length=1)
    ]
    reservation_id: NonEmptyStr
    reservation_version: PositiveInt
    reservation_state: Literal["ACTIVE"]
    remaining_reserved_cash_cents: NonNegativeCents
    outbox_batch_id: NonEmptyStr | None
    outbox_payload_hash: Sha256 | None
    outbox_state: Literal["DURABLE", "TOMBSTONED"]
    outbox_permit_nonce: NonEmptyStr | None
    writer_fencing_epoch: PositiveInt
    effective_send_deadline: UtcInstant

    @model_validator(mode="after")
    def validate_stage_order(self) -> Self:
        identities = [item.identity() for item in self.stage_loss_bindings]
        if len(identities) != len(set(identities)):
            raise ValueError("send-claim stage identities must be unique")
        if identities != sorted(identities):
            raise ValueError("send-claim stage identities must use canonical order")
        return self


class ExecutionPermit(CanonicalModel):
    """Gateway permit that can only preserve, shrink, or cancel a sealed plan."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.decision.execution-permit.v1"

    artifact_kind: Literal[ArtifactKind.EXECUTION_PERMIT]
    artifact_namespace: Literal["capital-gateway.entry-permit.v1"]
    schema_major: SchemaVersion
    permit_id: NonEmptyStr
    permit_nonce: NonEmptyStr
    permit_nonce_sequence: PositiveInt
    permit_nonce_state: Literal["ACTIVE"]
    disposition: PermitDisposition
    seal: PortfolioDecisionSeal
    seal_id: NonEmptyStr
    seal_revision: PositiveInt
    seal_artifact_hash: Sha256
    logical_key: DecisionLogicalKey
    proposal_artifact_hash: Sha256
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None
    broker_account_fingerprint: Sha256 | None
    base_currency: NonEmptyStr
    mode: ExecutionMode
    target_entry_session: date
    permit_lines: Annotated[tuple[ExecutionPermitLine, ...], Field(min_length=1)]
    total_remaining_reserve_cents: NonNegativeCents
    total_released_reserve_cents: NonNegativeCents
    send_claim_expected_versions: SendClaimExpectedVersions
    execution_window: TrustedExecutionWindow
    issued_at: UtcInstant
    permit_expires_at: UtcInstant
    issuer_binding: GatewayIssuerBinding

    @model_validator(mode="after")
    def validate_permit(self) -> Self:
        _validate_permit_seal_identity(self)
        _validate_permit_lines(self)
        _validate_permit_send_claim_bundle(self)
        _validate_permit_time_and_issuer(self)
        return self

    def artifact_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, self.schema_major, self)


def _validate_permit_seal_identity(permit: ExecutionPermit) -> None:
    seal = permit.seal
    if seal.artifact_hash() != permit.seal_artifact_hash:
        raise ValueError("permit seal artifact hash mismatch")
    bindings = {
        "seal ID": (permit.seal_id, seal.seal_id),
        "seal revision": (permit.seal_revision, seal.seal_revision),
        "logical key": (permit.logical_key, seal.logical_key),
        "proposal hash": (
            permit.proposal_artifact_hash,
            seal.proposal_artifact_hash,
        ),
        "portfolio": (permit.portfolio_id, seal.portfolio_id),
        "broker account": (permit.broker_account_id, seal.broker_account_id),
        "broker account fingerprint": (
            permit.broker_account_fingerprint,
            seal.broker_account_fingerprint,
        ),
        "base currency": (permit.base_currency, seal.base_currency),
        "mode": (permit.mode, seal.mode),
        "target entry session": (
            permit.target_entry_session,
            seal.target_entry_session,
        ),
    }
    for label, (actual, expected) in bindings.items():
        if actual != expected:
            raise ValueError(f"permit {label} must exactly match seal")


def _validate_permit_lines(permit: ExecutionPermit) -> None:
    seal_lines = {line.order_line_id: line for line in permit.seal.proposal.order_lines}
    line_ids = [line.order_line_id for line in permit.permit_lines]
    if len(line_ids) != len(set(line_ids)):
        raise ValueError("permit line IDs must be unique")
    if line_ids != sorted(line_ids):
        raise ValueError("permit lines must use canonical order")
    if set(line_ids) != set(seal_lines):
        raise ValueError("permit line set must exactly match seal line set")

    client_order_ids: list[str] = []
    for line in permit.permit_lines:
        sealed = seal_lines[line.order_line_id]
        bindings = {
            "security": (line.security_id, sealed.security_id),
            "sealed quantity": (
                line.sealed_quantity_units,
                sealed.sealed_quantity_units,
            ),
            "order type": (line.order_type, sealed.order_type),
            "limit price": (line.limit_price_cents, sealed.limit_price_cents),
            "worst-case price": (
                line.worst_case_price_cents,
                sealed.worst_case_price_cents,
            ),
            "price boundary": (
                line.price_boundary_version,
                sealed.price_boundary_version,
            ),
            "time in force": (line.time_in_force, sealed.time_in_force),
            "exit policy": (
                line.exit_session_ordinal,
                sealed.exit_session_ordinal,
            ),
            "sealed reserve": (
                line.sealed_reserve_cents,
                sealed.worst_case_cash_reserve_cents,
            ),
        }
        for label, (actual, expected) in bindings.items():
            if actual != expected:
                raise ValueError(f"permit line {label} must exactly match seal line")
        if line.permitted_quantity_units % sealed.lot_size_units != 0:
            raise ValueError("permit line quantity must remain an exact whole lot")
        if (
            permit.disposition is PermitDisposition.ALLOW
            and line.permitted_quantity_units > 0
            and line.client_order_id is None
        ):
            raise ValueError("positive sendable permit line requires client order ID")
        if line.permitted_quantity_units == 0 and line.client_order_id is not None:
            raise ValueError("zero permit line cannot carry a client order ID")
        if line.client_order_id is not None:
            client_order_ids.append(line.client_order_id)
    if len(client_order_ids) != len(set(client_order_ids)):
        raise ValueError("sendable client order IDs must be unique")

    remaining = sum(line.remaining_reserve_cents for line in permit.permit_lines)
    released = sum(line.released_reserve_cents for line in permit.permit_lines)
    if remaining != permit.total_remaining_reserve_cents:
        raise ValueError("permit total remaining reserve must equal line reserves")
    if released != permit.total_released_reserve_cents:
        raise ValueError("permit total released reserve must equal line releases")
    if remaining + released != permit.seal.total_reserved_cash_cents:
        raise ValueError("permit reserve cannot be reallocated beyond sealed cash")


def _validate_permit_send_claim_bundle(permit: ExecutionPermit) -> None:
    seal = permit.seal
    expected = permit.send_claim_expected_versions
    bindings = {
        "active seal ID": (expected.active_seal_id, seal.seal_id),
        "active seal revision": (expected.active_seal_revision, seal.seal_revision),
        "active seal artifact": (
            expected.active_seal_artifact_hash,
            permit.seal_artifact_hash,
        ),
        "active permit ID": (expected.active_permit_id, permit.permit_id),
        "active permit nonce": (
            expected.active_permit_nonce,
            permit.permit_nonce,
        ),
        "permit nonce sequence": (
            expected.permit_nonce_sequence,
            permit.permit_nonce_sequence,
        ),
        "permit nonce state": (
            expected.permit_nonce_state,
            permit.permit_nonce_state,
        ),
        "policy activation": (
            expected.policy_activation_hash,
            seal.policy_activation_hash,
        ),
        "trust bundle": (expected.trust_bundle_hash, seal.trust_bundle_hash),
        "registry epoch": (expected.registry_epoch, seal.registry_epoch),
        "policy epoch": (expected.policy_epoch, seal.policy_epoch),
        "authority epoch": (expected.authority_epoch, seal.authority_epoch),
        "risk epoch": (expected.risk_epoch, seal.risk_epoch),
        "authorization ID": (expected.authorization_id, seal.authorization_id),
        "authorization version": (
            expected.authorization_version,
            seal.authorization_version,
        ),
        "authorization envelope": (
            expected.authorization_envelope_hash,
            seal.authorization_envelope_hash,
        ),
        "authorization status version": (
            expected.authorization_status_version,
            seal.authorization_status_version,
        ),
        "authorization status hash": (
            expected.authorization_status_hash,
            seal.authorization_status_hash,
        ),
        "evidence root": (
            expected.evidence_set_merkle_root,
            seal.evidence_set_merkle_root,
        ),
        "entry fence ID": (expected.entry_fence_id, seal.entry_fence_id),
        "entry fence hash": (expected.entry_fence_hash, seal.entry_fence_hash),
        "entry fence version": (
            expected.entry_fence_version,
            seal.entry_fence_version,
        ),
        "capital version": (
            expected.capital_version,
            seal.post_admission_capital_version,
        ),
        "capital stream version": (
            expected.capital_stream_version,
            seal.capital_stream_version,
        ),
        "risk snapshot ID": (expected.risk_snapshot_id, seal.risk_snapshot_id),
        "risk snapshot artifact": (
            expected.risk_snapshot_artifact_hash,
            seal.risk_snapshot_artifact_hash,
        ),
        "stage loss": (expected.stage_loss_bindings, seal.stage_admission_bindings),
        "reservation ID": (expected.reservation_id, seal.reservation_id),
        "reservation version": (
            expected.reservation_version,
            seal.post_admission_reservation_version,
        ),
        "remaining reserve": (
            expected.remaining_reserved_cash_cents,
            permit.total_remaining_reserve_cents,
        ),
        "writer fencing": (
            expected.writer_fencing_epoch,
            seal.writer_fencing_epoch,
        ),
        "effective send deadline": (
            expected.effective_send_deadline,
            min(
                permit.permit_expires_at,
                permit.execution_window.gateway_send_deadline,
            ),
        ),
    }
    for label, (actual, required) in bindings.items():
        if actual != required:
            raise ValueError(f"permit send-claim {label} binding mismatch")

    if expected.authorization_revalidation_required:
        raise ValueError("authorization revalidation blocks permit send claim")
    if expected.risk_snapshot_freshness is not RiskSnapshotFreshness.FRESH:
        raise ValueError("stale risk snapshot blocks permit send claim")
    if expected.risk_snapshot_completeness is not RiskSnapshotCompleteness.COMPLETE:
        raise ValueError("incomplete risk snapshot blocks permit send claim")
    if expected.risk_latch is not RiskLatchState.CLEAR:
        raise ValueError("risk latch blocks permit send claim")
    if expected.reconciliation_latch is not ReconciliationLatchState.CLEAR:
        raise ValueError("reconciliation latch blocks permit send claim")

    if permit.disposition is PermitDisposition.ALLOW:
        if not any(line.permitted_quantity_units > 0 for line in permit.permit_lines):
            raise ValueError("ALLOW permit requires a positive sendable line")
        if (
            expected.outbox_batch_id is None
            or expected.outbox_payload_hash is None
            or expected.outbox_state != "DURABLE"
            or expected.outbox_permit_nonce != permit.permit_nonce
        ):
            raise ValueError(
                "ALLOW positive lines require exact durable outbox nonce binding"
            )
    else:
        if any(line.permitted_quantity_units > 0 for line in permit.permit_lines):
            raise ValueError("CANCEL permit requires every line quantity to be zero")
        if (
            expected.outbox_batch_id is not None
            or expected.outbox_payload_hash is not None
            or expected.outbox_state != "TOMBSTONED"
            or expected.outbox_permit_nonce is not None
        ):
            raise ValueError("CANCEL permit requires a non-sendable tombstoned outbox")


def _validate_permit_time_and_issuer(permit: ExecutionPermit) -> None:
    window = permit.execution_window
    if window.clock_health is not ClockHealth.HEALTHY:
        raise ValueError("healthy trusted clock is required for a permit")
    if window != permit.seal.execution_window:
        raise ValueError("permit execution window must exactly match seal window")
    if not (permit.seal.created_at < permit.issued_at <= window.permit_issue_deadline):
        raise ValueError(
            "permit issued_at must follow seal and not exceed permit issue deadline"
        )
    if not (
        window.permit_issue_deadline
        < permit.permit_expires_at
        <= window.gateway_send_deadline
    ):
        raise ValueError(
            "permit expires_at must follow issue deadline and not exceed send deadline"
        )
    for line in permit.permit_lines:
        if not (permit.seal.created_at <= line.preopen_fact_as_of <= permit.issued_at):
            raise ValueError(
                "preopen fact as_of must be after seal and not future to permit issuance"
            )
    _validate_issuer_binding(
        permit.issuer_binding,
        artifact_kind=permit.artifact_kind,
        artifact_namespace=permit.artifact_namespace,
        mode=permit.mode,
        schema_major=permit.schema_major,
        portfolio_id=permit.portfolio_id,
        issued_at=permit.issued_at,
        trust_bundle_hash=permit.seal.trust_bundle_hash,
        registry_epoch=permit.seal.registry_epoch,
    )


class PlanState(StrEnum):
    SEALED = "SEALED"
    PERMITTED = "PERMITTED"
    OUTBOX_DURABLE = "OUTBOX_DURABLE"
    SEND_CLAIMED = "SEND_CLAIMED"
    SUBMISSION_AMBIGUOUS = "SUBMISSION_AMBIGUOUS"
    BROKER_ACK = "BROKER_ACK"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    CANCEL_PENDING = "CANCEL_PENDING"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    RECONCILED_NOT_ACCEPTED = "RECONCILED_NOT_ACCEPTED"
    EXECUTED = "EXECUTED"


class OrderState(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


PLAN_STATE_TRANSITIONS = MappingProxyType(
    {
        PlanState.SEALED: frozenset(
            {
                PlanState.PERMITTED,
                PlanState.SUPERSEDED,
                PlanState.CANCELLED,
                PlanState.EXPIRED,
            }
        ),
        PlanState.PERMITTED: frozenset(
            {PlanState.OUTBOX_DURABLE, PlanState.CANCELLED, PlanState.EXPIRED}
        ),
        PlanState.OUTBOX_DURABLE: frozenset(
            {PlanState.SEND_CLAIMED, PlanState.CANCELLED, PlanState.EXPIRED}
        ),
        PlanState.SEND_CLAIMED: frozenset(
            {
                PlanState.SUBMISSION_AMBIGUOUS,
                PlanState.BROKER_ACK,
                PlanState.RECONCILED_NOT_ACCEPTED,
            }
        ),
        PlanState.SUBMISSION_AMBIGUOUS: frozenset(
            {PlanState.BROKER_ACK, PlanState.RECONCILED_NOT_ACCEPTED}
        ),
        PlanState.BROKER_ACK: frozenset(
            {
                PlanState.PARTIALLY_EXECUTED,
                PlanState.EXECUTED,
                PlanState.CANCEL_PENDING,
                PlanState.REJECTED,
                PlanState.EXPIRED,
            }
        ),
        PlanState.PARTIALLY_EXECUTED: frozenset(
            {
                PlanState.PARTIALLY_EXECUTED,
                PlanState.EXECUTED,
                PlanState.CANCEL_PENDING,
                PlanState.EXPIRED,
            }
        ),
        PlanState.CANCEL_PENDING: frozenset(
            {
                PlanState.CANCEL_PENDING,
                PlanState.EXECUTED,
                PlanState.CANCELLED,
                PlanState.EXPIRED,
            }
        ),
        PlanState.SUPERSEDED: frozenset(),
        PlanState.CANCELLED: frozenset(),
        PlanState.EXPIRED: frozenset(),
        PlanState.REJECTED: frozenset(),
        PlanState.RECONCILED_NOT_ACCEPTED: frozenset(),
        PlanState.EXECUTED: frozenset(),
    }
)


ORDER_STATE_TRANSITIONS = MappingProxyType(
    {
        OrderState.CREATED: frozenset({OrderState.SUBMITTED, OrderState.REJECTED}),
        OrderState.SUBMITTED: frozenset(
            {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.REJECTED,
                OrderState.CANCEL_REQUESTED,
                OrderState.EXPIRED,
            }
        ),
        OrderState.PARTIALLY_FILLED: frozenset(
            {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.CANCEL_REQUESTED,
                OrderState.EXPIRED,
            }
        ),
        OrderState.CANCEL_REQUESTED: frozenset(
            {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.CANCELLED,
                OrderState.EXPIRED,
            }
        ),
        OrderState.FILLED: frozenset(),
        OrderState.REJECTED: frozenset(),
        OrderState.CANCELLED: frozenset(),
        OrderState.EXPIRED: frozenset(),
    }
)


def validate_plan_transition(current: PlanState, target: PlanState) -> None:
    if target not in PLAN_STATE_TRANSITIONS[current]:
        raise ValueError(f"invalid plan transition: {current.value} -> {target.value}")


def validate_order_transition(current: OrderState, target: OrderState) -> None:
    if target not in ORDER_STATE_TRANSITIONS[current]:
        raise ValueError(f"invalid order transition: {current.value} -> {target.value}")


class ExecutionRevisionKind(StrEnum):
    RECORDED = "RECORDED"
    BUSTED = "BUSTED"
    CORRECTED = "CORRECTED"


class EconomicProjectionState(StrEnum):
    RECONCILED = "RECONCILED"
    REOPENED_BY_CORRECTION = "REOPENED_BY_CORRECTION"
    RECONCILIATION_PENDING = "RECONCILIATION_PENDING"


class ExecutionSide(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class EffectivePositionState(StrEnum):
    OPEN = "OPEN"
    EXIT_PENDING = "EXIT_PENDING"
    FLAT = "FLAT"
    RECONCILIATION_HALT = "RECONCILIATION_HALT"


_TERMINAL_ORDER_STATES = frozenset(
    {
        OrderState.FILLED,
        OrderState.REJECTED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
    }
)


def _validate_execution_account_mode(
    mode: ExecutionMode,
    broker_account_id: str | None,
) -> None:
    if mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
        raise ValueError("research mode cannot represent an execution fact")
    if mode is ExecutionMode.DAILY_BAR_PROXY:
        if broker_account_id is not None:
            raise ValueError("proxy execution cannot bind a broker account")
    elif broker_account_id is None:
        raise ValueError("manual and broker execution require an account")


class ExecutionRevision(CanonicalModel):
    """One append-only revision of a broker execution's economic effect."""

    execution_id: NonEmptyStr
    revision: PositiveInt
    revision_kind: ExecutionRevisionKind
    supersedes_revision: PositiveInt | None
    order_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None
    mode: ExecutionMode
    security_id: NonEmptyStr
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    side: ExecutionSide
    broker_order_id: NonEmptyStr
    broker_execution_id: NonEmptyStr
    historical_terminal_order_state: OrderState
    effective_filled_quantity: NonNegativeQuantity
    effective_position_quantity: SignedQuantity
    effective_gross_cash_cents: NonNegativeCents
    effective_position_state: EffectivePositionState
    exit_mandate_id: NonEmptyStr | None
    exit_mandate_revision: PositiveInt | None
    economic_projection_state: EconomicProjectionState
    effective_at: UtcInstant
    observed_at: UtcInstant
    source_envelope_hash: Sha256
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        _validate_execution_account_mode(self.mode, self.broker_account_id)
        if self.historical_terminal_order_state not in _TERMINAL_ORDER_STATES:
            raise ValueError("historical terminal order state must remain terminal")
        if self.observed_at < self.effective_at:
            raise ValueError("observed_at cannot precede effective_at")
        if self.revision_kind is ExecutionRevisionKind.RECORDED:
            if self.revision != 1 or self.supersedes_revision is not None:
                raise ValueError("RECORDED must be revision 1 without a predecessor")
        elif self.revision <= 1 or self.supersedes_revision != self.revision - 1:
            raise ValueError(
                "BUSTED/CORRECTED must supersede the immediately prior revision"
            )
        if self.revision_kind is ExecutionRevisionKind.BUSTED and (
            self.effective_filled_quantity != 0
            or self.effective_position_quantity != 0
            or self.effective_gross_cash_cents != 0
        ):
            raise ValueError(
                "BUSTED revision must have zero effective quantity and cash"
            )

        mandate_pair = (self.exit_mandate_id, self.exit_mandate_revision)
        if (mandate_pair[0] is None) != (mandate_pair[1] is None):
            raise ValueError("exit mandate ID and revision must be an all-or-none pair")
        if self.effective_position_quantity > 0:
            if self.effective_position_state not in {
                EffectivePositionState.OPEN,
                EffectivePositionState.EXIT_PENDING,
            }:
                raise ValueError(
                    "positive position requires OPEN or EXIT_PENDING state"
                )
            if mandate_pair[0] is None:
                raise ValueError("positive position requires an exit mandate revision")
        elif self.effective_position_quantity == 0:
            if self.effective_position_state is not EffectivePositionState.FLAT:
                raise ValueError("zero position requires FLAT state")
            if mandate_pair[0] is not None:
                raise ValueError("flat position cannot retain an exit mandate")
        else:
            if (
                self.effective_position_state
                is not EffectivePositionState.RECONCILIATION_HALT
                or self.economic_projection_state
                is not EconomicProjectionState.RECONCILIATION_PENDING
            ):
                raise ValueError(
                    "negative long-only position requires reconciliation halt"
                )
            if mandate_pair[0] is not None:
                raise ValueError(
                    "negative position cannot expose orderable exit quantity"
                )

        if (
            self.economic_projection_state
            is EconomicProjectionState.REOPENED_BY_CORRECTION
            and self.revision_kind is not ExecutionRevisionKind.CORRECTED
        ):
            raise ValueError("only a correction can reopen an economic projection")
        return self


class ExecutionRevisionHistory(CanonicalModel):
    """A complete, contiguous append-only execution revision chain."""

    execution_id: NonEmptyStr
    order_id: NonEmptyStr
    revisions: Annotated[tuple[ExecutionRevision, ...], Field(min_length=1)]
    active_revision: PositiveInt
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_history(self) -> Self:
        first = self.revisions[0]
        if (
            first.revision != 1
            or first.revision_kind is not ExecutionRevisionKind.RECORDED
        ):
            raise ValueError("revision history must begin with RECORDED revision 1")

        stable_identity = (
            first.portfolio_id,
            first.broker_account_id,
            first.mode,
            first.security_id,
            first.position_lineage_id,
            first.economic_lot_id,
            first.side,
            first.broker_order_id,
            first.broker_execution_id,
            first.historical_terminal_order_state,
        )
        previous_observed_at = first.observed_at
        for expected_revision, revision in enumerate(self.revisions, start=1):
            if revision.revision != expected_revision:
                raise ValueError("revision history must be contiguous and canonical")
            if (
                revision.execution_id != self.execution_id
                or revision.order_id != self.order_id
            ):
                raise ValueError("revision identity must match history identity")
            current_identity = (
                revision.portfolio_id,
                revision.broker_account_id,
                revision.mode,
                revision.security_id,
                revision.position_lineage_id,
                revision.economic_lot_id,
                revision.side,
                revision.broker_order_id,
                revision.broker_execution_id,
                revision.historical_terminal_order_state,
            )
            if current_identity != stable_identity:
                raise ValueError(
                    "execution, account, position, broker, and terminal identity "
                    "cannot change across revisions"
                )
            if expected_revision > 1:
                if revision.supersedes_revision != expected_revision - 1:
                    raise ValueError("revision predecessor must be contiguous")
                if revision.observed_at < previous_observed_at:
                    raise ValueError("revision observations must be monotonic")
            previous_observed_at = revision.observed_at

        if self.active_revision != self.revisions[-1].revision:
            raise ValueError("active revision must be the highest appended revision")
        return self


__all__ = [
    "EconomicProjectionState",
    "EffectivePositionState",
    "ExecutionMode",
    "ExecutionPermit",
    "ExecutionPermitLine",
    "ExecutionRevision",
    "ExecutionRevisionHistory",
    "ExecutionRevisionKind",
    "ExecutionSide",
    "ORDER_STATE_TRANSITIONS",
    "OrderState",
    "PLAN_STATE_TRANSITIONS",
    "PlanState",
    "PermitDisposition",
    "PermitReasonCode",
    "SendClaimExpectedVersions",
    "validate_order_transition",
    "validate_plan_transition",
]
