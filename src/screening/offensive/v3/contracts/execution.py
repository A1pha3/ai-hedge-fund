"""Public immutable execution lifecycle and broker-revision contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from ._execution_relations import (
    ensure_equal_bindings,
    ensure_not_regressed,
    ensure_same_identity_sequence,
    ensure_strict_advance,
    ensure_unique_canonical_stages,
    stage_identity,
    witnessed_cancel_reasons,
)
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
    StageLossExpectedVersion,
    TrustedClockObservation,
    TrustedExecutionWindow,
    _validate_issuer_binding,
)
from .evidence import NonEmptyStr
from .governance import AuthorizationLifecycle
from .risk import (
    ReconciliationLatchState,
    RiskLatchState,
    RiskSnapshotCompleteness,
    RiskSnapshotFreshness,
    StageLossLatchState,
)
from .trust import ArtifactKind

if TYPE_CHECKING:
    from .capital import CapitalRiskSnapshot


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
    RISK_HALT_CANCEL = "RISK_HALT_CANCEL"
    STAGE_HALT_CANCEL = "STAGE_HALT_CANCEL"
    RECONCILIATION_CANCEL = "RECONCILIATION_CANCEL"
    FACT_INTEGRITY_CANCEL = "FACT_INTEGRITY_CANCEL"
    AUTHORIZATION_CANCEL = "AUTHORIZATION_CANCEL"
    FENCE_CANCEL = "FENCE_CANCEL"
    DEADLINE_CANCEL = "DEADLINE_CANCEL"


class PermitNonceState(StrEnum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    INVALIDATED = "INVALIDATED"


class ReservationState(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class OutboxState(StrEnum):
    DURABLE = "DURABLE"
    TOMBSTONED = "TOMBSTONED"


class ActiveEntryClaimState(StrEnum):
    UNCLAIMED = "UNCLAIMED"
    SEND_CLAIMED = "SEND_CLAIMED"


class AuthorizationIssuerVerificationResult(StrEnum):
    """Current verifier result for the seal's frozen issuer claims."""

    VALID = "VALID"
    INVALID = "INVALID"


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
        PermitReasonCode.RISK_HALT_CANCEL,
        PermitReasonCode.STAGE_HALT_CANCEL,
        PermitReasonCode.RECONCILIATION_CANCEL,
        PermitReasonCode.FACT_INTEGRITY_CANCEL,
        PermitReasonCode.AUTHORIZATION_CANCEL,
        PermitReasonCode.FENCE_CANCEL,
        PermitReasonCode.DEADLINE_CANCEL,
    }
)

_LOCAL_CAP_PRIORITY = (
    (PermitReasonCode.AVAILABILITY_REDUCTION, "availability_cap_units"),
    (PermitReasonCode.PRICE_REDUCTION, "price_cap_units"),
    (PermitReasonCode.CAPACITY_REDUCTION, "capacity_cap_units"),
    (PermitReasonCode.CASH_REDUCTION, "cash_cap_units"),
    (PermitReasonCode.CAPITAL_RISK_REDUCTION, "capital_risk_cap_units"),
)


class ReservationLineAllocation(CanonicalModel):
    """Stable reservation ownership for one sealed order line."""

    order_line_id: NonEmptyStr
    reservation_allocation_id: NonEmptyStr
    reserved_cash_cents: NonNegativeCents


class PermitLineMechanicalBinding(CanonicalModel):
    """Frozen, non-alpha T+1 caps used to shrink one line."""

    order_line_id: NonEmptyStr
    predicate_policy_version: NonEmptyStr
    preopen_fact_snapshot_id: NonEmptyStr
    preopen_fact_snapshot_hash: Sha256
    preopen_fact_as_of: UtcInstant
    availability_cap_units: NonNegativeQuantity
    price_cap_units: NonNegativeQuantity
    capacity_cap_units: NonNegativeQuantity
    cash_cap_units: NonNegativeQuantity
    capital_risk_cap_units: NonNegativeQuantity

    def limiting_cap(self, sealed_quantity_units: int) -> int:
        return min(
            sealed_quantity_units,
            *(getattr(self, field) for _, field in _LOCAL_CAP_PRIORITY),
        )

    def limiting_reason(self, sealed_quantity_units: int) -> PermitReasonCode:
        minimum = self.limiting_cap(sealed_quantity_units)
        if minimum == sealed_quantity_units:
            return PermitReasonCode.UNCHANGED
        return next(
            reason
            for reason, field in _LOCAL_CAP_PRIORITY
            if getattr(self, field) == minimum
        )


class AuthorizationIssuerRevalidation(CanonicalModel):
    """Gateway proof that the authorization issuer remains trusted now."""

    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.execution.authorization-issuer-revalidation.v1"
    )

    revalidation_id: NonEmptyStr
    authorization_envelope_hash: Sha256
    authorization_issuance_binding_artifact_hash: Sha256
    authorization_issuer_id: NonEmptyStr
    authorization_issuer_key_id: NonEmptyStr
    authorization_issuer_capability: NonEmptyStr
    authorization_issuer_capability_version: NonEmptyStr
    authorization_issuer_identity_fingerprint: Sha256
    issuance_registry_epoch: PositiveInt
    issuance_trust_bundle_hash: Sha256
    current_registry_epoch: PositiveInt
    current_trust_bundle_hash: Sha256
    verification_result: AuthorizationIssuerVerificationResult
    verified_at: UtcInstant
    valid_until: UtcInstant

    @model_validator(mode="after")
    def validate_trust_progression(self) -> Self:
        if self.valid_until <= self.verified_at:
            raise ValueError(
                "authorization revalidation validity must extend beyond verification"
            )
        if self.current_registry_epoch < self.issuance_registry_epoch:
            raise ValueError(
                "authorization revalidation registry epoch cannot rollback"
            )
        if (
            self.current_registry_epoch == self.issuance_registry_epoch
            and self.current_trust_bundle_hash != self.issuance_trust_bundle_hash
        ):
            raise ValueError(
                "same registry epoch requires the exact issuance trust bundle hash"
            )
        return self

    def artifact_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, 2, self)


class ExecutionPermitLine(CanonicalModel):
    """One seal line mechanically left unchanged, shrunk, or cancelled."""

    order_line_id: NonEmptyStr
    security_id: NonEmptyStr
    sealed_quantity_units: PositiveQuantity
    permitted_quantity_units: NonNegativeQuantity
    reason_code: PermitReasonCode
    mechanical_binding: PermitLineMechanicalBinding | None
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
        if self.remaining_reserve_cents > self.sealed_reserve_cents:
            raise ValueError("remaining reserve cannot exceed sealed reserve")

        if self.permitted_quantity_units == self.sealed_quantity_units:
            if self.reason_code is not PermitReasonCode.UNCHANGED:
                raise ValueError("unchanged quantity requires UNCHANGED reason")
        elif self.permitted_quantity_units > 0:
            if self.reason_code not in _SHRINK_REASONS:
                raise ValueError(
                    "positive shrink requires a mechanical reduction reason"
                )
        elif self.reason_code not in _CANCEL_REASONS | _SHRINK_REASONS:
            raise ValueError(
                "zero quantity requires a mechanical reduction or cancel reason"
            )

        return self


class PermitEvaluationState(CanonicalModel):
    """Current authority, risk, capital, and reservation truth at permit issue."""

    policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveInt
    policy_epoch: PositiveInt
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    authorization_id: NonEmptyStr
    authorization_version: PositiveInt
    authorization_envelope_hash: Sha256
    authorization_lifecycle: AuthorizationLifecycle
    authorization_status_version: PositiveInt
    authorization_status_hash: Sha256
    authorization_revalidation: AuthorizationIssuerRevalidation
    evidence_set_merkle_root: Sha256
    entry_fence_id: NonEmptyStr
    entry_fence_hash: Sha256
    entry_fence_version: Annotated[ExactInteger, Field(ge=0)]
    capital_version: PositiveInt
    capital_stream_version: PositiveInt
    risk_snapshot: "CapitalRiskSnapshot"
    risk_snapshot_artifact_hash: Sha256
    stage_loss_bindings: Annotated[
        tuple[StageLossExpectedVersion, ...], Field(min_length=1)
    ]
    reservation_id: NonEmptyStr
    reservation_version: PositiveInt
    reservation_state: ReservationState
    reservation_allocations: Annotated[
        tuple[ReservationLineAllocation, ...], Field(min_length=1)
    ]
    remaining_reserved_cash_cents: NonNegativeCents
    prior_permit_nonce_sequence: Annotated[ExactInteger, Field(ge=0)]
    active_permit_id: NonEmptyStr | None
    active_permit_artifact_hash: Sha256 | None
    active_permit_nonce: NonEmptyStr | None
    active_permit_nonce_sequence: PositiveInt | None
    active_permit_nonce_state: PermitNonceState | None
    active_outbox_batch_id: NonEmptyStr | None
    active_outbox_payload_hash: Sha256 | None
    active_outbox_state: OutboxState | None
    active_send_claim_state: ActiveEntryClaimState
    send_claim_sequence: Annotated[ExactInteger, Field(ge=0)]
    writer_fencing_epoch: PositiveInt

    @model_validator(mode="after")
    def validate_current_truth(self) -> Self:
        ensure_unique_canonical_stages(
            self.stage_loss_bindings, label="permit evaluation"
        )
        allocation_ids = tuple(
            (item.order_line_id, item.reservation_allocation_id)
            for item in self.reservation_allocations
        )
        if len(allocation_ids) != len(set(allocation_ids)):
            raise ValueError("permit evaluation reservation allocations must be unique")
        if allocation_ids != tuple(sorted(allocation_ids)):
            raise ValueError("permit evaluation allocations must use canonical order")
        if self.remaining_reserved_cash_cents != sum(
            item.reserved_cash_cents for item in self.reservation_allocations
        ):
            raise ValueError("remaining reserve must equal line allocation sum")
        if self.reservation_state is ReservationState.RELEASED and (
            self.remaining_reserved_cash_cents != 0
            or any(
                item.reserved_cash_cents != 0 for item in self.reservation_allocations
            )
        ):
            raise ValueError(
                "released reservation requires zero allocations and remaining reserve"
            )
        if self.risk_snapshot.artifact_hash() != self.risk_snapshot_artifact_hash:
            raise ValueError("current risk snapshot artifact hash mismatch")
        if self.risk_snapshot.capital_version != self.capital_version:
            raise ValueError("current risk snapshot capital version mismatch")
        active_permit_fields = (
            self.active_permit_id,
            self.active_permit_artifact_hash,
            self.active_permit_nonce,
            self.active_permit_nonce_sequence,
            self.active_permit_nonce_state,
        )
        if any(item is None for item in active_permit_fields) and any(
            item is not None for item in active_permit_fields
        ):
            raise ValueError(
                "active permit identity, artifact, nonce, and sequence pair"
            )
        active_outbox_fields = (
            self.active_outbox_batch_id,
            self.active_outbox_payload_hash,
            self.active_outbox_state,
        )
        if any(item is None for item in active_outbox_fields) and any(
            item is not None for item in active_outbox_fields
        ):
            raise ValueError("active outbox ID, payload hash, and state must be paired")
        if self.active_permit_nonce is None:
            if self.active_outbox_batch_id is not None:
                raise ValueError("active outbox requires an active permit")
            if self.active_send_claim_state is not ActiveEntryClaimState.UNCLAIMED:
                raise ValueError("SEND_CLAIMED requires an active permit")
            if self.send_claim_sequence != 0:
                raise ValueError("unclaimed state requires zero send-claim sequence")
        else:
            if self.active_permit_nonce_sequence != self.prior_permit_nonce_sequence:
                raise ValueError(
                    "active permit nonce sequence must equal current sequence"
                )
            if self.active_outbox_state is not OutboxState.DURABLE:
                raise ValueError("active permit requires its exact durable outbox")
            if self.active_send_claim_state is ActiveEntryClaimState.UNCLAIMED:
                if self.send_claim_sequence != 0:
                    raise ValueError(
                        "UNCLAIMED state requires zero send-claim sequence"
                    )
                if self.active_permit_nonce_state is not PermitNonceState.ACTIVE:
                    raise ValueError("unclaimed permit nonce state must remain ACTIVE")
            else:
                if self.send_claim_sequence <= 0:
                    raise ValueError(
                        "SEND_CLAIMED state requires positive send-claim sequence"
                    )
                if self.active_permit_nonce_state is not PermitNonceState.CONSUMED:
                    raise ValueError("claimed permit nonce state must be CONSUMED")
        return self


class PermitCancellationBinding(CanonicalModel):
    """Atomic reserve release, nonce invalidation, and optional outbox tombstone."""

    permit_nonce: NonEmptyStr
    post_permit_nonce_sequence: PositiveInt
    post_permit_nonce_state: PermitNonceState
    reservation_id: NonEmptyStr
    pre_reservation_version: PositiveInt
    post_reservation_version: PositiveInt
    post_reservation_state: ReservationState
    released_cash_cents: NonNegativeCents
    remaining_reserved_cash_cents: NonNegativeCents
    outbox_batch_id: NonEmptyStr | None
    outbox_payload_hash: Sha256 | None
    post_outbox_state: OutboxState | None
    post_capital_version: PositiveInt
    post_capital_stream_version: PositiveInt
    post_risk_snapshot: "CapitalRiskSnapshot"
    post_risk_snapshot_artifact_hash: Sha256
    writer_fencing_epoch: PositiveInt

    @model_validator(mode="after")
    def validate_post_snapshot_hash(self) -> Self:
        if self.post_risk_snapshot.artifact_hash() != (
            self.post_risk_snapshot_artifact_hash
        ):
            raise ValueError("cancel post risk snapshot artifact hash mismatch")
        return self


class SendClaimExpectedVersions(CanonicalModel):
    """Post-permit, pre-SEND_CLAIMED CAS truth expected by the send transition."""

    active_seal_id: NonEmptyStr
    active_seal_revision: PositiveInt
    active_seal_artifact_hash: Sha256
    active_permit_id: NonEmptyStr
    active_permit_nonce: NonEmptyStr
    permit_nonce_sequence: PositiveInt
    permit_nonce_state: PermitNonceState
    policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveInt
    policy_epoch: PositiveInt
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    authorization_id: NonEmptyStr
    authorization_version: PositiveInt
    authorization_envelope_hash: Sha256
    authorization_lifecycle: AuthorizationLifecycle
    authorization_status_version: PositiveInt
    authorization_status_hash: Sha256
    authorization_revalidation: AuthorizationIssuerRevalidation
    evidence_set_merkle_root: Sha256
    entry_fence_id: NonEmptyStr
    entry_fence_hash: Sha256
    entry_fence_version: Annotated[ExactInteger, Field(ge=0)]
    capital_version: PositiveInt
    capital_stream_version: PositiveInt
    post_risk_snapshot: "CapitalRiskSnapshot"
    post_risk_snapshot_artifact_hash: Sha256
    stage_loss_bindings: Annotated[
        tuple[StageLossExpectedVersion, ...], Field(min_length=1)
    ]
    reservation_id: NonEmptyStr
    reservation_version: PositiveInt
    reservation_state: ReservationState
    post_reservation_allocations: Annotated[
        tuple[ReservationLineAllocation, ...], Field(min_length=1)
    ]
    remaining_reserved_cash_cents: NonNegativeCents
    outbox_batch_id: NonEmptyStr | None
    outbox_payload_hash: Sha256 | None
    outbox_state: OutboxState
    outbox_permit_nonce: NonEmptyStr | None
    writer_fencing_epoch: PositiveInt
    effective_send_deadline: UtcInstant

    @model_validator(mode="after")
    def validate_post_truth(self) -> Self:
        ensure_unique_canonical_stages(self.stage_loss_bindings, label="send-claim")
        allocation_ids = tuple(
            (item.order_line_id, item.reservation_allocation_id)
            for item in self.post_reservation_allocations
        )
        if len(allocation_ids) != len(set(allocation_ids)):
            raise ValueError("send-claim reservation allocations must be unique")
        if allocation_ids != tuple(sorted(allocation_ids)):
            raise ValueError("send-claim allocations must use canonical order")
        if self.remaining_reserved_cash_cents != sum(
            item.reserved_cash_cents for item in self.post_reservation_allocations
        ):
            raise ValueError("send-claim reserve must equal post allocation sum")
        if self.post_risk_snapshot.artifact_hash() != (
            self.post_risk_snapshot_artifact_hash
        ):
            raise ValueError("send-claim post risk snapshot artifact hash mismatch")
        if self.post_risk_snapshot.capital_version != self.capital_version:
            raise ValueError("send-claim post risk snapshot capital version mismatch")
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
    permit_nonce_state: PermitNonceState
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
    permit_clock_observation: TrustedClockObservation
    evaluation_state: PermitEvaluationState
    send_claim_expected_versions: SendClaimExpectedVersions | None
    cancellation_binding: PermitCancellationBinding | None
    execution_window: TrustedExecutionWindow
    issued_at: UtcInstant
    permit_expires_at: UtcInstant
    issuer_binding: GatewayIssuerBinding

    @model_validator(mode="after")
    def validate_permit(self) -> Self:
        _validate_permit_seal_identity(self)
        _validate_permit_lines(self)
        _validate_permit_time_and_issuer(self)
        _validate_permit_evaluation(self)
        _validate_permit_transition(self)
        return self

    def artifact_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, self.schema_major, self)


class EntryCancellationReceipt(CanonicalModel):
    """Gateway receipt cancelling one unclaimed prior ALLOW permit/outbox."""

    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.decision.entry-cancellation-receipt.v1"
    )

    artifact_kind: Literal[ArtifactKind.ENTRY_CANCELLATION_RECEIPT]
    artifact_namespace: Literal["capital-gateway.entry-cancellation.v1"]
    schema_major: SchemaVersion
    cancellation_receipt_id: NonEmptyStr
    reason_code: PermitReasonCode
    prior_permit: ExecutionPermit
    prior_permit_artifact_hash: Sha256
    permit_id: NonEmptyStr
    permit_nonce: NonEmptyStr
    permit_nonce_sequence: PositiveInt
    logical_key: DecisionLogicalKey
    evaluation_state: PermitEvaluationState
    cancellation_binding: PermitCancellationBinding
    cancellation_clock_observation: TrustedClockObservation
    cancelled_at: UtcInstant
    issuer_binding: GatewayIssuerBinding

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        _validate_entry_cancellation_receipt(self)
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
    current_allocations = {
        item.order_line_id: item.reserved_cash_cents
        for item in permit.evaluation_state.reservation_allocations
    }
    line_ids = [line.order_line_id for line in permit.permit_lines]
    if len(line_ids) != len(set(line_ids)):
        raise ValueError("permit line IDs must be unique")
    if line_ids != sorted(line_ids):
        raise ValueError("permit lines must use canonical order")
    if set(line_ids) != set(seal_lines):
        raise ValueError("permit line set must exactly match seal line set")

    mechanical_presence = tuple(
        line.mechanical_binding is not None for line in permit.permit_lines
    )
    mechanical_cancel = permit.disposition is PermitDisposition.CANCEL and all(
        mechanical_presence
    )
    if (
        permit.disposition is PermitDisposition.CANCEL
        and any(mechanical_presence)
        and not all(mechanical_presence)
    ):
        raise ValueError(
            "CANCEL cannot mix mechanical and portfolio-wide cancel reasons"
        )

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
        if (
            permit.disposition is PermitDisposition.ALLOW
            and line.permitted_quantity_units > 0
            and line.client_order_id is None
        ):
            raise ValueError("positive sendable permit line requires client order ID")
        if line.permitted_quantity_units == 0 and line.client_order_id is not None:
            raise ValueError("zero permit line cannot carry a client order ID")
        mechanical = line.mechanical_binding
        if permit.disposition is PermitDisposition.CANCEL:
            if mechanical_cancel:
                if mechanical is None or line.reason_code not in _SHRINK_REASONS:
                    raise ValueError(
                        "mechanical CANCEL requires a consumed binding and shrink reason"
                    )
            elif mechanical is not None or line.reason_code not in _CANCEL_REASONS:
                raise ValueError(
                    "portfolio-wide CANCEL requires no mechanical binding and a cancel reason"
                )
        elif mechanical is None:
            raise ValueError("ALLOW requires a mechanical fact binding on every line")
        if mechanical is not None and mechanical.order_line_id != line.order_line_id:
            raise ValueError("permit mechanical binding line identity mismatch")
        if mechanical is not None and (
            mechanical.predicate_policy_version
            != permit.execution_window.execution_policy_version
        ):
            raise ValueError(
                "permit predicate policy must match sealed execution policy"
            )
        if line.permitted_quantity_units % sealed.lot_size_units != 0:
            raise ValueError("permit line quantity must remain an exact whole lot")
        if permit.disposition is PermitDisposition.ALLOW or mechanical_cancel:
            assert mechanical is not None
            raw_cap = mechanical.limiting_cap(sealed.sealed_quantity_units)
            lot_floored_cap = (raw_cap // sealed.lot_size_units) * sealed.lot_size_units
            if line.permitted_quantity_units != lot_floored_cap:
                raise ValueError(
                    "ALLOW quantity must equal the lot-floor of its limiting cap"
                )
            required_reason = mechanical.limiting_reason(sealed.sealed_quantity_units)
            if line.reason_code is not required_reason:
                raise ValueError(
                    "mechanical permit reason must follow frozen cap priority"
                )
            if (
                permit.disposition is PermitDisposition.ALLOW
                and line.reason_code in _CANCEL_REASONS
            ):
                raise ValueError(
                    "ALLOW cannot hide a portfolio-wide cancel reason on one line"
                )
        if line.client_order_id is not None:
            client_order_ids.append(line.client_order_id)
        current_reserved = current_allocations.get(line.order_line_id)
        if current_reserved is None:
            raise ValueError("permit line has no current reservation allocation")
        if line.remaining_reserve_cents > current_reserved:
            raise ValueError("permit line cannot exceed its current allocation")
        if line.released_reserve_cents != (
            current_reserved - line.remaining_reserve_cents
        ):
            raise ValueError(
                "permit line release must complement its own current allocation"
            )
    if len(client_order_ids) != len(set(client_order_ids)):
        raise ValueError("sendable client order IDs must be unique")

    remaining = sum(line.remaining_reserve_cents for line in permit.permit_lines)
    released = sum(line.released_reserve_cents for line in permit.permit_lines)
    if remaining != permit.total_remaining_reserve_cents:
        raise ValueError("permit total remaining reserve must equal line reserves")
    if released != permit.total_released_reserve_cents:
        raise ValueError("permit total released reserve must equal line releases")
    if remaining + released != permit.evaluation_state.remaining_reserved_cash_cents:
        raise ValueError("permit reserve must reconcile to current line allocations")


def _validate_permit_evaluation(permit: ExecutionPermit) -> None:
    seal = permit.seal
    current = permit.evaluation_state
    _validate_current_authority_against_seal(seal, current)
    _validate_authorization_revalidation_binding(seal, current)
    ensure_not_regressed(
        seal.post_admission_capital_version,
        current.capital_version,
        label="current capital",
    )
    ensure_not_regressed(
        seal.post_admission_capital_stream_version,
        current.capital_stream_version,
        label="current capital stream",
    )
    ensure_not_regressed(
        seal.post_admission_reservation_version,
        current.reservation_version,
        label="current reservation",
    )
    ensure_not_regressed(
        seal.authorization_status_version,
        current.authorization_status_version,
        label="current authorization status",
    )
    if current.authorization_status_version == seal.authorization_status_version:
        if (
            current.authorization_status_hash != seal.authorization_status_hash
            or current.authorization_lifecycle is not AuthorizationLifecycle.ACTIVE
        ):
            raise ValueError(
                "authorization status content cannot drift at the same version"
            )
    if current.capital_version == seal.post_admission_capital_version and (
        current.risk_snapshot.risk_snapshot_id != seal.post_admission_risk_snapshot_id
        or current.risk_snapshot_artifact_hash
        != seal.post_admission_risk_snapshot_artifact_hash
    ):
        raise ValueError(
            "equal post-admission capital version requires exact sealed snapshot anchor"
        )
    if (
        current.capital_version > seal.post_admission_capital_version
        and current.risk_snapshot.risk_snapshot_id
        == seal.post_admission_risk_snapshot_id
    ):
        raise ValueError("advanced capital version requires a new risk snapshot ID")
    ensure_same_identity_sequence(
        seal.stage_admission_bindings,
        current.stage_loss_bindings,
        label="current",
    )
    for admission, stage in zip(
        seal.stage_admission_bindings,
        current.stage_loss_bindings,
        strict=True,
    ):
        ensure_not_regressed(
            admission.post_stage_loss_version,
            stage.stage_loss_version,
            label="current stage loss",
        )
        if (
            stage.stage_loss_version == admission.post_stage_loss_version
            and stage.stage_loss_latch is not admission.stage_loss_latch
        ):
            raise ValueError("stage latch cannot drift at the same version")
    if current.reservation_state is not ReservationState.ACTIVE:
        raise ValueError("current reservation must remain ACTIVE for permit transition")
    sealed_allocations = {
        item.order_line_id: item for item in seal.line_reserve_bindings
    }
    current_allocations = {
        item.order_line_id: item for item in current.reservation_allocations
    }
    if set(current_allocations) != set(sealed_allocations):
        raise ValueError("current reservation allocation line coverage mismatch")
    for line_id, allocation in current_allocations.items():
        sealed_allocation = sealed_allocations[line_id]
        if allocation.reservation_allocation_id != (
            sealed_allocation.reservation_allocation_id
        ):
            raise ValueError("reservation allocation identity must remain stable")
        if allocation.reserved_cash_cents > sealed_allocation.reserved_cash_cents:
            raise ValueError("reservation allocation cannot grow or move across lines")
    sealed_allocation_sequence = tuple(
        ReservationLineAllocation(
            order_line_id=item.order_line_id,
            reservation_allocation_id=item.reservation_allocation_id,
            reserved_cash_cents=item.reserved_cash_cents,
        )
        for item in seal.line_reserve_bindings
    )
    allocations_changed_since_seal = (
        tuple(current.reservation_allocations) != sealed_allocation_sequence
    )
    if (
        current.reservation_version == seal.post_admission_reservation_version
        and allocations_changed_since_seal
    ):
        raise ValueError(
            "reservation allocation content changed without version advance"
        )
    if allocations_changed_since_seal:
        ensure_strict_advance(
            seal.post_admission_capital_version,
            current.capital_version,
            label="allocation-change capital",
        )
        ensure_strict_advance(
            seal.post_admission_capital_stream_version,
            current.capital_stream_version,
            label="allocation-change capital stream",
        )
    if current.remaining_reserved_cash_cents < permit.total_remaining_reserve_cents:
        raise ValueError("current reservation cannot fund permitted line reserves")
    if any(
        item is not None
        for item in (
            current.active_permit_id,
            current.active_permit_artifact_hash,
            current.active_permit_nonce,
            current.active_permit_nonce_sequence,
            current.active_outbox_batch_id,
            current.active_outbox_payload_hash,
            current.active_outbox_state,
        )
    ):
        raise ValueError("permit issuance requires no existing active nonce or outbox")
    if current.active_send_claim_state is not ActiveEntryClaimState.UNCLAIMED:
        raise ValueError("permit issuance cannot follow SEND_CLAIMED state")
    if permit.permit_nonce_sequence <= current.prior_permit_nonce_sequence:
        raise ValueError("permit nonce sequence must advance prior issuance")
    _validate_current_risk_snapshot(
        seal,
        current,
        current.risk_snapshot,
        event_at=permit.issued_at,
        require_current=permit.disposition is PermitDisposition.ALLOW,
        clock_health=permit.permit_clock_observation.clock_health,
    )


def _validate_current_authority_against_seal(
    seal: PortfolioDecisionSeal,
    current: PermitEvaluationState,
) -> None:
    for label, before, now in (
        ("registry", seal.registry_epoch, current.registry_epoch),
        ("policy", seal.policy_epoch, current.policy_epoch),
        ("authority", seal.authority_epoch, current.authority_epoch),
        ("risk", seal.risk_epoch, current.risk_epoch),
        ("entry fence", seal.entry_fence_version, current.entry_fence_version),
        ("writer fencing", seal.writer_fencing_epoch, current.writer_fencing_epoch),
    ):
        ensure_not_regressed(before, now, label=f"current {label}")
    if (
        current.registry_epoch == seal.registry_epoch
        and current.trust_bundle_hash != seal.trust_bundle_hash
    ):
        raise ValueError("same registry epoch requires exact seal trust bundle hash")
    if (
        current.policy_epoch == seal.policy_epoch
        and current.policy_activation_hash != seal.policy_activation_hash
    ):
        raise ValueError("same policy epoch requires exact activation hash")
    if current.entry_fence_version == seal.entry_fence_version and (
        current.entry_fence_id != seal.entry_fence_id
        or current.entry_fence_hash != seal.entry_fence_hash
    ):
        raise ValueError("same entry fence version requires exact ID and hash")
    if current.authorization_id == seal.authorization_id:
        ensure_not_regressed(
            seal.authorization_version,
            current.authorization_version,
            label="current authorization",
        )
        if (
            current.authorization_version == seal.authorization_version
            and current.authorization_envelope_hash != seal.authorization_envelope_hash
        ):
            raise ValueError("same authorization version requires exact envelope hash")
    elif current.authorization_version <= seal.authorization_version:
        raise ValueError(
            "replacement authorization version must advance the sealed version"
        )


def _validate_authorization_revalidation_binding(
    seal: PortfolioDecisionSeal,
    current: PermitEvaluationState,
) -> None:
    revalidation = current.authorization_revalidation
    issuance = seal.authorization_issuance_binding
    ensure_equal_bindings(
        {
            "authorization envelope": (
                revalidation.authorization_envelope_hash,
                seal.authorization_envelope_hash,
            ),
            "authorization issuance binding": (
                revalidation.authorization_issuance_binding_artifact_hash,
                seal.authorization_issuance_binding_artifact_hash,
            ),
            "authorization issuer ID": (
                revalidation.authorization_issuer_id,
                issuance.authorization_issuer_id,
            ),
            "authorization issuer key": (
                revalidation.authorization_issuer_key_id,
                issuance.authorization_issuer_key_id,
            ),
            "authorization issuer capability": (
                revalidation.authorization_issuer_capability,
                issuance.authorization_issuer_capability,
            ),
            "authorization issuer capability version": (
                revalidation.authorization_issuer_capability_version,
                issuance.authorization_issuer_capability_version,
            ),
            "authorization issuer identity": (
                revalidation.authorization_issuer_identity_fingerprint,
                issuance.authorization_issuer_identity_fingerprint,
            ),
            "issuance registry epoch": (
                revalidation.issuance_registry_epoch,
                issuance.registry_epoch,
            ),
            "issuance trust bundle": (
                revalidation.issuance_trust_bundle_hash,
                issuance.trust_bundle_hash,
            ),
            "current registry epoch": (
                revalidation.current_registry_epoch,
                current.registry_epoch,
            ),
            "current trust bundle": (
                revalidation.current_trust_bundle_hash,
                current.trust_bundle_hash,
            ),
        },
        prefix="authorization issuer revalidation",
    )


def _validate_current_risk_snapshot(
    seal: PortfolioDecisionSeal,
    current: PermitEvaluationState,
    snapshot: "CapitalRiskSnapshot",
    *,
    event_at: UtcInstant,
    require_current: bool,
    clock_health: ClockHealth,
) -> None:
    ensure_equal_bindings(
        {
            "portfolio": (snapshot.portfolio_id, seal.portfolio_id),
            "broker account": (snapshot.broker_account_id, seal.broker_account_id),
            "base currency": (snapshot.base_currency, seal.base_currency),
            "mode": (snapshot.mode, seal.mode),
            "policy activation": (
                snapshot.policy_activation_hash,
                current.policy_activation_hash,
            ),
            "policy epoch": (snapshot.policy_epoch, current.policy_epoch),
            "authority epoch": (snapshot.authority_epoch, current.authority_epoch),
            "risk epoch": (snapshot.risk_epoch, current.risk_epoch),
            "registry epoch": (snapshot.registry_epoch, current.registry_epoch),
            "authorization ID": (
                snapshot.authorization_id,
                current.authorization_id,
            ),
            "authorization version": (
                snapshot.authorization_version,
                current.authorization_version,
            ),
            "writer fencing": (
                snapshot.writer_fencing_epoch,
                current.writer_fencing_epoch,
            ),
            "capital version": (snapshot.capital_version, current.capital_version),
        },
        prefix="current risk snapshot",
    )
    if clock_health is ClockHealth.HEALTHY and snapshot.as_of > event_at:
        raise ValueError("current risk snapshot as_of cannot be future to event")
    if require_current and not snapshot.as_of <= event_at < snapshot.valid_until:
        raise ValueError("current risk snapshot must be valid at permit issuance")
    snapshot_reserves = {item.identity(): item for item in snapshot.entry_reserves}
    expected_reserves = _owned_reserve_truth(seal, current.reservation_allocations)
    for identity, amount in expected_reserves.items():
        component = snapshot_reserves.get(identity)
        if component is None or component.covered_live_order_id is not None:
            raise ValueError(
                "risk snapshot owned reserve attribution is missing or covered"
            )
        if component.reserved_entry_gross_cents != amount:
            raise ValueError("risk snapshot owned reserve amount mismatch")
    owned_sources = {
        item.reservation_allocation_id for item in current.reservation_allocations
    }
    for item in snapshot.entry_reserves:
        if item.source_id in owned_sources and item.identity() not in expected_reserves:
            raise ValueError("risk snapshot reserve source has ambiguous attribution")
    latch_by_identity = {
        (
            item.research_program_id,
            item.economic_lineage_id,
            item.stage_id,
            item.stage_loss_budget_id,
        ): (item.stage_loss_version, item.state)
        for item in snapshot.stage_loss_latches
    }
    expected_latches = {
        stage_identity(item): (item.stage_loss_version, item.stage_loss_latch)
        for item in current.stage_loss_bindings
    }
    for identity, expected in expected_latches.items():
        if latch_by_identity.get(identity) != expected:
            raise ValueError("risk snapshot stage loss binding subset mismatch")


def _owned_reserve_truth(
    seal: PortfolioDecisionSeal,
    allocations: tuple[ReservationLineAllocation, ...],
) -> dict[tuple[str, str, str, str], int]:
    line_by_id = {line.order_line_id: line for line in seal.proposal.order_lines}
    result: dict[tuple[str, str, str, str], int] = {}
    for allocation in allocations:
        if allocation.reserved_cash_cents == 0:
            continue
        line = line_by_id[allocation.order_line_id]
        identity = (
            line.research_program_id,
            line.economic_lineage_id,
            line.stage_id,
            allocation.reservation_allocation_id,
        )
        result[identity] = allocation.reserved_cash_cents
    return result


def _validate_permit_transition(permit: ExecutionPermit) -> None:
    if permit.permit_nonce_state is not PermitNonceState.ACTIVE:
        raise ValueError("permit nonce must be ACTIVE at permit issuance")
    if permit.disposition is PermitDisposition.ALLOW:
        _validate_allow_transition(permit)
    else:
        _validate_cancel_transition(permit)


def _validate_allow_transition(permit: ExecutionPermit) -> None:
    seal = permit.seal
    current = permit.evaluation_state
    expected = permit.send_claim_expected_versions
    if expected is None or permit.cancellation_binding is not None:
        raise ValueError("ALLOW requires send-claim state and no cancellation binding")
    if not any(line.permitted_quantity_units > 0 for line in permit.permit_lines):
        raise ValueError("ALLOW permit requires a positive sendable line")
    ensure_equal_bindings(
        {
            "policy activation": (
                current.policy_activation_hash,
                seal.policy_activation_hash,
            ),
            "policy epoch": (current.policy_epoch, seal.policy_epoch),
            "authority epoch": (current.authority_epoch, seal.authority_epoch),
            "risk epoch": (current.risk_epoch, seal.risk_epoch),
            "authorization ID": (
                current.authorization_id,
                seal.authorization_id,
            ),
            "authorization version": (
                current.authorization_version,
                seal.authorization_version,
            ),
            "authorization envelope": (
                current.authorization_envelope_hash,
                seal.authorization_envelope_hash,
            ),
            "evidence root": (
                current.evidence_set_merkle_root,
                seal.evidence_set_merkle_root,
            ),
            "writer fencing epoch": (
                current.writer_fencing_epoch,
                seal.writer_fencing_epoch,
            ),
            "reservation ID": (current.reservation_id, seal.reservation_id),
            "current entry fence ID": (current.entry_fence_id, seal.entry_fence_id),
            "current entry fence hash": (
                current.entry_fence_hash,
                seal.entry_fence_hash,
            ),
            "current entry fence version": (
                current.entry_fence_version,
                seal.entry_fence_version,
            ),
        },
        prefix="ALLOW seal",
    )
    if current.authorization_lifecycle is not AuthorizationLifecycle.ACTIVE:
        raise ValueError("ALLOW requires an ACTIVE authorization")
    revalidation = current.authorization_revalidation
    if (
        revalidation.verification_result
        is not AuthorizationIssuerVerificationResult.VALID
    ):
        raise ValueError("ALLOW requires a VALID authorization issuer result")
    if revalidation.verified_at != permit.issued_at:
        raise ValueError(
            "ALLOW authorization issuer revalidation must be current at issued event"
        )
    if permit.issued_at >= revalidation.valid_until:
        raise ValueError("ALLOW authorization issuer revalidation is expired")
    risk_snapshot = current.risk_snapshot
    if risk_snapshot.freshness is not RiskSnapshotFreshness.FRESH:
        raise ValueError("fresh current risk snapshot is required for ALLOW")
    if risk_snapshot.completeness is not RiskSnapshotCompleteness.COMPLETE:
        raise ValueError("complete current risk snapshot is required for ALLOW")
    if risk_snapshot.risk_latch is not RiskLatchState.CLEAR:
        raise ValueError("risk halt blocks ALLOW")
    if risk_snapshot.reconciliation_latch is not ReconciliationLatchState.CLEAR:
        raise ValueError("reconciliation halt blocks ALLOW")
    if any(
        stage.stage_loss_latch is not StageLossLatchState.CLEAR
        for stage in current.stage_loss_bindings
    ):
        raise ValueError("stage loss halt blocks ALLOW")
    _validate_send_claim_post_state(permit, expected)


def _validate_send_claim_post_state(
    permit: ExecutionPermit, expected: SendClaimExpectedVersions
) -> None:
    seal = permit.seal
    current = permit.evaluation_state
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
            current.policy_activation_hash,
        ),
        "trust bundle": (expected.trust_bundle_hash, current.trust_bundle_hash),
        "registry epoch": (expected.registry_epoch, current.registry_epoch),
        "policy epoch": (expected.policy_epoch, current.policy_epoch),
        "authority epoch": (expected.authority_epoch, current.authority_epoch),
        "risk epoch": (expected.risk_epoch, current.risk_epoch),
        "authorization ID": (expected.authorization_id, current.authorization_id),
        "authorization version": (
            expected.authorization_version,
            current.authorization_version,
        ),
        "authorization envelope": (
            expected.authorization_envelope_hash,
            current.authorization_envelope_hash,
        ),
        "authorization lifecycle": (
            expected.authorization_lifecycle,
            current.authorization_lifecycle,
        ),
        "authorization status version": (
            expected.authorization_status_version,
            current.authorization_status_version,
        ),
        "authorization status hash": (
            expected.authorization_status_hash,
            current.authorization_status_hash,
        ),
        "authorization revalidation": (
            expected.authorization_revalidation,
            current.authorization_revalidation,
        ),
        "evidence root": (
            expected.evidence_set_merkle_root,
            current.evidence_set_merkle_root,
        ),
        "entry fence ID": (expected.entry_fence_id, current.entry_fence_id),
        "entry fence hash": (expected.entry_fence_hash, current.entry_fence_hash),
        "entry fence version": (
            expected.entry_fence_version,
            current.entry_fence_version,
        ),
        "reservation ID": (expected.reservation_id, current.reservation_id),
        "reservation state": (
            expected.reservation_state,
            ReservationState.ACTIVE,
        ),
        "remaining reserve": (
            expected.remaining_reserved_cash_cents,
            permit.total_remaining_reserve_cents,
        ),
        "writer fencing": (
            expected.writer_fencing_epoch,
            current.writer_fencing_epoch,
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
    current_allocations = tuple(current.reservation_allocations)
    post_allocations = tuple(expected.post_reservation_allocations)
    expected_allocation_ids = tuple(
        (item.order_line_id, item.reservation_allocation_id)
        for item in current_allocations
    )
    post_allocation_ids = tuple(
        (item.order_line_id, item.reservation_allocation_id)
        for item in post_allocations
    )
    if post_allocation_ids != expected_allocation_ids:
        raise ValueError("send-claim allocation identities must remain stable per line")
    remaining_by_line = {
        item.order_line_id: item.remaining_reserve_cents for item in permit.permit_lines
    }
    if any(
        item.reserved_cash_cents != remaining_by_line[item.order_line_id]
        for item in post_allocations
    ):
        raise ValueError(
            "post allocation must equal each permit line remaining reserve"
        )
    allocations_changed = post_allocations != current_allocations
    for label, current_version, post_version in (
        ("capital", current.capital_version, expected.capital_version),
        (
            "capital stream",
            current.capital_stream_version,
            expected.capital_stream_version,
        ),
        ("reservation", current.reservation_version, expected.reservation_version),
    ):
        if allocations_changed:
            ensure_strict_advance(current_version, post_version, label=label)
        elif post_version != current_version:
            raise ValueError(f"quiet {label} version must remain unchanged")
    ensure_same_identity_sequence(
        current.stage_loss_bindings,
        expected.stage_loss_bindings,
        label="send-claim",
    )
    for before, after in zip(
        current.stage_loss_bindings,
        expected.stage_loss_bindings,
        strict=True,
    ):
        if before != after:
            raise ValueError("send-claim stage loss truth must remain unchanged")
    if allocations_changed:
        if expected.post_risk_snapshot == current.risk_snapshot:
            raise ValueError("changed reserve requires a new post risk snapshot")
    elif (
        expected.post_risk_snapshot != current.risk_snapshot
        or expected.post_risk_snapshot_artifact_hash
        != current.risk_snapshot_artifact_hash
    ):
        raise ValueError("unchanged capital risk requires the exact current snapshot")
    _validate_post_risk_snapshot(
        permit.seal,
        current,
        expected.post_risk_snapshot,
        expected.post_reservation_allocations,
        expected.capital_version,
        expected.stage_loss_bindings,
        event_at=permit.issued_at,
    )
    if (
        expected.outbox_batch_id is None
        or expected.outbox_payload_hash is None
        or expected.outbox_state is not OutboxState.DURABLE
        or expected.outbox_permit_nonce != permit.permit_nonce
    ):
        raise ValueError("ALLOW requires exact durable outbox nonce binding")


def _validate_post_risk_snapshot(
    seal: PortfolioDecisionSeal,
    current: PermitEvaluationState,
    snapshot: "CapitalRiskSnapshot",
    allocations: tuple[ReservationLineAllocation, ...],
    capital_version: int,
    stages: tuple[StageLossExpectedVersion, ...],
    *,
    event_at: UtcInstant,
) -> None:
    ensure_equal_bindings(
        {
            "portfolio": (snapshot.portfolio_id, seal.portfolio_id),
            "broker account": (
                snapshot.broker_account_id,
                seal.broker_account_id,
            ),
            "currency": (snapshot.base_currency, seal.base_currency),
            "mode": (snapshot.mode, seal.mode),
            "policy activation": (
                snapshot.policy_activation_hash,
                current.policy_activation_hash,
            ),
            "policy epoch": (snapshot.policy_epoch, current.policy_epoch),
            "authority epoch": (snapshot.authority_epoch, current.authority_epoch),
            "risk epoch": (snapshot.risk_epoch, current.risk_epoch),
            "registry epoch": (snapshot.registry_epoch, current.registry_epoch),
            "authorization ID": (
                snapshot.authorization_id,
                current.authorization_id,
            ),
            "authorization version": (
                snapshot.authorization_version,
                current.authorization_version,
            ),
            "writer fencing": (
                snapshot.writer_fencing_epoch,
                current.writer_fencing_epoch,
            ),
            "capital version": (snapshot.capital_version, capital_version),
        },
        prefix="post risk snapshot",
    )
    capital_changed = capital_version != current.capital_version
    if capital_changed:
        if snapshot.risk_snapshot_id == current.risk_snapshot.risk_snapshot_id:
            raise ValueError("changed capital requires a new post risk snapshot ID")
        if not snapshot.as_of == event_at < snapshot.valid_until:
            raise ValueError(
                "changed post risk snapshot must be created and valid at event"
            )
        mutable_reserve_projection_fields = {
            "risk_snapshot_id",
            "as_of",
            "valid_until",
            "capital_version",
            "entry_reserves",
            "reserved_cash_cents",
            "exposures",
            "total_gross_exposure_cents",
        }
        current_unchanged = current.risk_snapshot.model_dump(
            mode="python", round_trip=True
        )
        post_unchanged = snapshot.model_dump(mode="python", round_trip=True)
        for field_name in mutable_reserve_projection_fields:
            current_unchanged.pop(field_name)
            post_unchanged.pop(field_name)
        if post_unchanged != current_unchanged:
            raise ValueError(
                "reserve delta cannot alter unrelated capital snapshot truth"
            )
    elif snapshot != current.risk_snapshot:
        raise ValueError("quiet capital requires the exact current risk snapshot")

    current_reserves = {
        item.identity(): item for item in current.risk_snapshot.entry_reserves
    }
    post_reserves = {item.identity(): item for item in snapshot.entry_reserves}
    current_owned = _owned_reserve_truth(seal, current.reservation_allocations)
    post_owned = _owned_reserve_truth(seal, allocations)
    expected_post = {
        identity: item
        for identity, item in current_reserves.items()
        if identity not in current_owned
    }
    current_components = current_reserves
    for identity, amount in post_owned.items():
        template = current_components.get(identity)
        if template is None:
            raise ValueError("post risk snapshot cannot invent an owned reserve source")
        expected_post[identity] = template.model_copy(
            update={"reserved_entry_gross_cents": amount}
        )
    if post_reserves != expected_post:
        raise ValueError(
            "post risk snapshot must apply owned reserve delta and preserve unrelated truth"
        )
    expected_reserved_cash = (
        current.risk_snapshot.reserved_cash_cents
        - sum(current_owned.values())
        + sum(post_owned.values())
    )
    if snapshot.reserved_cash_cents != expected_reserved_cash:
        raise ValueError("post risk snapshot full reserved cash delta mismatch")
    snapshot_latches = {
        (
            item.research_program_id,
            item.economic_lineage_id,
            item.stage_id,
            item.stage_loss_budget_id,
        ): (item.stage_loss_version, item.state)
        for item in snapshot.stage_loss_latches
    }
    expected_latches = {
        stage_identity(item): (item.stage_loss_version, item.stage_loss_latch)
        for item in stages
    }
    for identity, expected in expected_latches.items():
        if snapshot_latches.get(identity) != expected:
            raise ValueError("post risk snapshot required stage truth mismatch")
    if tuple(snapshot.stage_loss_latches) != tuple(
        current.risk_snapshot.stage_loss_latches
    ):
        raise ValueError("post risk snapshot must preserve unrelated stage latches")


def _validate_cancel_transition(permit: ExecutionPermit) -> None:
    current = permit.evaluation_state
    binding = permit.cancellation_binding
    if permit.send_claim_expected_versions is not None:
        raise ValueError("CANCEL cannot carry durable send-claim state")
    if binding is None:
        raise ValueError("CANCEL requires an atomic cancellation binding")
    if any(line.permitted_quantity_units > 0 for line in permit.permit_lines):
        raise ValueError("CANCEL permit requires every line quantity to be zero")
    witnessed = witnessed_cancel_reasons(
        authorization_failed=(
            current.authorization_lifecycle is not AuthorizationLifecycle.ACTIVE
            or current.policy_activation_hash != permit.seal.policy_activation_hash
            or current.policy_epoch != permit.seal.policy_epoch
            or current.authority_epoch != permit.seal.authority_epoch
            or current.risk_epoch != permit.seal.risk_epoch
            or current.authorization_id != permit.seal.authorization_id
            or current.authorization_version != permit.seal.authorization_version
            or current.authorization_envelope_hash
            != permit.seal.authorization_envelope_hash
            or current.evidence_set_merkle_root != permit.seal.evidence_set_merkle_root
            or current.authorization_revalidation.verification_result
            is AuthorizationIssuerVerificationResult.INVALID
        ),
        stage_halted=any(
            stage.stage_loss_latch is not StageLossLatchState.CLEAR
            for stage in current.stage_loss_bindings
        ),
        reconciliation_halted=(
            current.risk_snapshot.reconciliation_latch
            is not ReconciliationLatchState.CLEAR
        ),
        fact_integrity_failed=(
            current.risk_snapshot.freshness is not RiskSnapshotFreshness.FRESH
            or current.risk_snapshot.completeness
            is not RiskSnapshotCompleteness.COMPLETE
            or permit.permit_clock_observation.clock_health is not ClockHealth.HEALTHY
        ),
        fence_changed=(
            (
                current.entry_fence_id,
                current.entry_fence_hash,
                current.entry_fence_version,
                current.writer_fencing_epoch,
            )
            != (
                permit.seal.entry_fence_id,
                permit.seal.entry_fence_hash,
                permit.seal.entry_fence_version,
                permit.seal.writer_fencing_epoch,
            )
        ),
        deadline_reached=(
            permit.permit_clock_observation.clock_health is ClockHealth.HEALTHY
            and permit.issued_at > permit.execution_window.permit_issue_deadline
        ),
        authorization_reason=PermitReasonCode.AUTHORIZATION_CANCEL,
        stage_reason=PermitReasonCode.STAGE_HALT_CANCEL,
        reconciliation_reason=PermitReasonCode.RECONCILIATION_CANCEL,
        fact_reason=PermitReasonCode.FACT_INTEGRITY_CANCEL,
        fence_reason=PermitReasonCode.FENCE_CANCEL,
        deadline_reason=PermitReasonCode.DEADLINE_CANCEL,
    )
    if current.risk_snapshot.risk_latch is not RiskLatchState.CLEAR:
        witnessed = witnessed | {PermitReasonCode.RISK_HALT_CANCEL}
    mechanical_cancel = all(
        line.mechanical_binding is not None for line in permit.permit_lines
    )
    if mechanical_cancel:
        if witnessed:
            raise ValueError(
                "mechanical CANCEL cannot mix a portfolio-wide cancel witness"
            )
    else:
        for line in permit.permit_lines:
            if line.reason_code not in witnessed:
                raise ValueError(
                    "CANCEL reason must be witnessed by current authorization, stage, "
                    "reconciliation, fact, fence, or deadline truth"
                )
    ensure_equal_bindings(
        {
            "permit nonce": (binding.permit_nonce, permit.permit_nonce),
            "post permit nonce state": (
                binding.post_permit_nonce_state,
                PermitNonceState.INVALIDATED,
            ),
            "reservation ID": (binding.reservation_id, current.reservation_id),
            "pre-reservation version": (
                binding.pre_reservation_version,
                current.reservation_version,
            ),
            "post-reservation state": (
                binding.post_reservation_state,
                ReservationState.RELEASED,
            ),
            "released cash": (
                binding.released_cash_cents,
                current.remaining_reserved_cash_cents,
            ),
            "remaining reserved cash": (
                binding.remaining_reserved_cash_cents,
                0,
            ),
            "writer fencing": (
                binding.writer_fencing_epoch,
                current.writer_fencing_epoch,
            ),
        },
        prefix="permit cancel",
    )
    if current.active_outbox_batch_id is None:
        if any(
            item is not None
            for item in (
                binding.outbox_batch_id,
                binding.outbox_payload_hash,
                binding.post_outbox_state,
            )
        ):
            raise ValueError("cancel cannot invent an outbox tombstone")
    elif (
        binding.outbox_batch_id != current.active_outbox_batch_id
        or binding.outbox_payload_hash != current.active_outbox_payload_hash
        or binding.post_outbox_state is not OutboxState.TOMBSTONED
    ):
        raise ValueError("cancel must tombstone the exact current outbox")
    ensure_strict_advance(
        permit.permit_nonce_sequence,
        binding.post_permit_nonce_sequence,
        label="cancel permit nonce",
    )
    ensure_strict_advance(
        current.reservation_version,
        binding.post_reservation_version,
        label="cancel reservation",
    )
    if binding.released_cash_cents > 0:
        ensure_strict_advance(
            current.capital_version,
            binding.post_capital_version,
            label="cancel capital",
        )
        ensure_strict_advance(
            current.capital_stream_version,
            binding.post_capital_stream_version,
            label="cancel capital stream",
        )
    elif (
        binding.post_capital_version != current.capital_version
        or binding.post_capital_stream_version != current.capital_stream_version
        or binding.post_risk_snapshot != current.risk_snapshot
        or binding.post_risk_snapshot_artifact_hash
        != current.risk_snapshot_artifact_hash
    ):
        raise ValueError(
            "zero-release cancel capital and risk snapshot must remain quiet"
        )
    if binding.released_cash_cents != sum(
        item.reserved_cash_cents for item in current.reservation_allocations
    ):
        raise ValueError("cancel release must equal current line allocation sum")
    _validate_post_risk_snapshot(
        permit.seal,
        current,
        binding.post_risk_snapshot,
        tuple(
            item.model_copy(update={"reserved_cash_cents": 0})
            for item in current.reservation_allocations
        ),
        binding.post_capital_version,
        current.stage_loss_bindings,
        event_at=permit.issued_at,
    )


def _validate_permit_time_and_issuer(permit: ExecutionPermit) -> None:
    window = permit.execution_window
    if window != permit.seal.execution_window:
        raise ValueError("permit execution window must exactly match seal window")
    observation = permit.permit_clock_observation
    seal_observation = window.seal_clock_observation
    if not (
        observation.monotonic_observation_ns > seal_observation.monotonic_observation_ns
        and observation.monotonic_sequence > seal_observation.monotonic_sequence
    ):
        raise ValueError("permit clock monotonic observation must be later than seal")
    if permit.issued_at != observation.wall_clock_utc:
        raise ValueError("permit issued_at must equal its clock wall observation")
    if observation.clock_health is ClockHealth.HEALTHY:
        if observation.wall_clock_utc <= seal_observation.wall_clock_utc:
            raise ValueError("healthy permit wall clock must be later than seal")
    if permit.disposition is PermitDisposition.ALLOW:
        if observation.clock_health is not ClockHealth.HEALTHY:
            raise ValueError("healthy trusted clock observation is required for ALLOW")
        if not (
            permit.seal.created_at < permit.issued_at <= window.permit_issue_deadline
        ):
            raise ValueError(
                "ALLOW issued_at must follow seal and not exceed permit issue deadline"
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
        if line.mechanical_binding is None:
            continue
        if not (
            permit.seal.created_at
            <= line.mechanical_binding.preopen_fact_as_of
            <= permit.issued_at
        ):
            raise ValueError(
                "preopen fact as_of must be after seal and not future to permit issuance"
            )
    revalidation = permit.evaluation_state.authorization_revalidation
    if not (revalidation.verified_at == permit.issued_at < revalidation.valid_until):
        raise ValueError(
            "authorization issuer revalidation must be current at permit transaction"
        )
    _validate_issuer_binding(
        permit.issuer_binding,
        artifact_kind=permit.artifact_kind,
        artifact_namespace=permit.artifact_namespace,
        mode=permit.mode,
        schema_major=permit.schema_major,
        portfolio_id=permit.portfolio_id,
        issued_at=permit.issued_at,
        trust_bundle_hash=permit.evaluation_state.trust_bundle_hash,
        registry_epoch=permit.evaluation_state.registry_epoch,
    )


def _validate_entry_cancellation_receipt(
    receipt: EntryCancellationReceipt,
) -> None:
    prior = receipt.prior_permit
    current = receipt.evaluation_state
    expected = prior.send_claim_expected_versions

    if prior.disposition is not PermitDisposition.ALLOW or expected is None:
        raise ValueError("cancellation receipt requires a prior ALLOW permit")
    if prior.artifact_hash() != receipt.prior_permit_artifact_hash:
        raise ValueError("cancellation receipt prior permit artifact hash mismatch")
    ensure_equal_bindings(
        {
            "permit ID": (receipt.permit_id, prior.permit_id),
            "permit nonce": (receipt.permit_nonce, prior.permit_nonce),
            "permit nonce sequence": (
                receipt.permit_nonce_sequence,
                prior.permit_nonce_sequence,
            ),
            "logical key": (receipt.logical_key, prior.logical_key),
            "active permit ID": (current.active_permit_id, prior.permit_id),
            "active permit artifact": (
                current.active_permit_artifact_hash,
                receipt.prior_permit_artifact_hash,
            ),
            "active permit nonce": (
                current.active_permit_nonce,
                prior.permit_nonce,
            ),
            "active permit nonce sequence": (
                current.active_permit_nonce_sequence,
                prior.permit_nonce_sequence,
            ),
            "active outbox state": (
                current.active_outbox_state,
                OutboxState.DURABLE,
            ),
            "active send-claim state": (
                current.active_send_claim_state,
                ActiveEntryClaimState.UNCLAIMED,
            ),
            "send-claim sequence": (current.send_claim_sequence, 0),
        },
        prefix="entry cancellation receipt",
    )
    _validate_receipt_current_state(
        prior,
        current,
        expected,
        event_at=receipt.cancelled_at,
        clock_health=receipt.cancellation_clock_observation.clock_health,
    )
    _validate_receipt_reason_and_time(receipt, expected)
    _validate_receipt_cancellation_binding(receipt)
    revalidation = current.authorization_revalidation
    if not (
        revalidation.verified_at == receipt.cancelled_at < revalidation.valid_until
    ):
        raise ValueError(
            "authorization issuer revalidation must be current at cancellation"
        )
    _validate_issuer_binding(
        receipt.issuer_binding,
        artifact_kind=receipt.artifact_kind,
        artifact_namespace=receipt.artifact_namespace,
        mode=prior.mode,
        schema_major=receipt.schema_major,
        portfolio_id=prior.portfolio_id,
        issued_at=receipt.cancelled_at,
        trust_bundle_hash=current.trust_bundle_hash,
        registry_epoch=current.registry_epoch,
    )


def _validate_receipt_current_state(
    prior: ExecutionPermit,
    current: PermitEvaluationState,
    expected: SendClaimExpectedVersions,
    *,
    event_at: UtcInstant,
    clock_health: ClockHealth,
) -> None:
    for label, before, now in (
        ("registry", expected.registry_epoch, current.registry_epoch),
        ("policy", expected.policy_epoch, current.policy_epoch),
        ("authority", expected.authority_epoch, current.authority_epoch),
        ("risk", expected.risk_epoch, current.risk_epoch),
        ("entry fence", expected.entry_fence_version, current.entry_fence_version),
        (
            "writer fencing",
            expected.writer_fencing_epoch,
            current.writer_fencing_epoch,
        ),
    ):
        ensure_not_regressed(before, now, label=f"cancellation current {label}")
    if current.registry_epoch < expected.registry_epoch:
        raise ValueError("cancellation current registry epoch cannot rollback")
    if (
        current.registry_epoch == expected.registry_epoch
        and current.trust_bundle_hash != expected.trust_bundle_hash
    ):
        raise ValueError(
            "same cancellation registry epoch requires exact trust bundle hash"
        )
    if (
        current.policy_epoch == expected.policy_epoch
        and current.policy_activation_hash != expected.policy_activation_hash
    ):
        raise ValueError(
            "same cancellation policy epoch requires exact activation hash"
        )
    if current.entry_fence_version == expected.entry_fence_version and (
        current.entry_fence_id != expected.entry_fence_id
        or current.entry_fence_hash != expected.entry_fence_hash
    ):
        raise ValueError(
            "same cancellation entry fence version requires exact ID and hash"
        )
    if current.authorization_id == expected.authorization_id:
        ensure_not_regressed(
            expected.authorization_version,
            current.authorization_version,
            label="cancellation current authorization",
        )
        if (
            current.authorization_version == expected.authorization_version
            and current.authorization_envelope_hash
            != expected.authorization_envelope_hash
        ):
            raise ValueError(
                "same cancellation authorization version requires exact envelope"
            )
    elif current.authorization_version <= expected.authorization_version:
        raise ValueError("replacement cancellation authorization version must advance")
    _validate_authorization_revalidation_binding(prior.seal, current)
    for label, before, now in (
        ("capital", expected.capital_version, current.capital_version),
        (
            "capital stream",
            expected.capital_stream_version,
            current.capital_stream_version,
        ),
        (
            "authorization status",
            expected.authorization_status_version,
            current.authorization_status_version,
        ),
    ):
        ensure_not_regressed(before, now, label=f"cancellation current {label}")
    if current.authorization_status_version == expected.authorization_status_version:
        if (
            current.authorization_status_hash != expected.authorization_status_hash
            or current.authorization_lifecycle is not expected.authorization_lifecycle
        ):
            raise ValueError(
                "cancellation authorization status cannot drift at the same version"
            )
    if current.reservation_id != expected.reservation_id:
        raise ValueError("active permit requires its exact reservation ID")
    if current.reservation_state is not ReservationState.ACTIVE:
        raise ValueError("active permit reservation must remain ACTIVE")
    ensure_not_regressed(
        expected.reservation_version,
        current.reservation_version,
        label="cancellation current reservation",
    )
    expected_allocations = tuple(expected.post_reservation_allocations)
    current_allocations = tuple(current.reservation_allocations)
    expected_allocation_ids = tuple(
        (item.order_line_id, item.reservation_allocation_id)
        for item in expected_allocations
    )
    current_allocation_ids = tuple(
        (item.order_line_id, item.reservation_allocation_id)
        for item in current_allocations
    )
    if current_allocation_ids != expected_allocation_ids:
        raise ValueError(
            "active permit reservation ownership and source IDs must remain exact"
        )
    if any(
        now.reserved_cash_cents > before.reserved_cash_cents
        for before, now in zip(
            expected_allocations,
            current_allocations,
            strict=True,
        )
    ):
        raise ValueError("active permit reservation allocation cannot grow")
    allocations_changed = current_allocations != expected_allocations
    if allocations_changed:
        ensure_strict_advance(
            expected.reservation_version,
            current.reservation_version,
            label="reduced active reservation",
        )
        ensure_strict_advance(
            expected.capital_version,
            current.capital_version,
            label="reduced reservation capital",
        )
        ensure_strict_advance(
            expected.capital_stream_version,
            current.capital_stream_version,
            label="reduced reservation capital stream",
        )
    elif current.reservation_version != expected.reservation_version:
        raise ValueError("unchanged active reservation version must remain exact")
    if current.capital_version == expected.capital_version and (
        current.risk_snapshot != expected.post_risk_snapshot
        or current.risk_snapshot_artifact_hash
        != expected.post_risk_snapshot_artifact_hash
    ):
        raise ValueError("same capital version requires exact prior post risk snapshot")
    if (
        current.capital_version > expected.capital_version
        and current.risk_snapshot.risk_snapshot_id
        == expected.post_risk_snapshot.risk_snapshot_id
    ):
        raise ValueError("advanced capital version requires a new risk snapshot ID")
    ensure_same_identity_sequence(
        expected.stage_loss_bindings,
        current.stage_loss_bindings,
        label="cancellation current",
    )
    for before, now in zip(
        expected.stage_loss_bindings,
        current.stage_loss_bindings,
        strict=True,
    ):
        ensure_not_regressed(
            before.stage_loss_version,
            now.stage_loss_version,
            label="cancellation current stage loss",
        )
        if (
            now.stage_loss_version == before.stage_loss_version
            and now.stage_loss_latch is not before.stage_loss_latch
        ):
            raise ValueError(
                "cancellation stage latch cannot drift at the same version"
            )
    _validate_current_risk_snapshot(
        prior.seal,
        current,
        current.risk_snapshot,
        event_at=event_at,
        require_current=False,
        clock_health=clock_health,
    )


def _validate_receipt_reason_and_time(
    receipt: EntryCancellationReceipt,
    expected: SendClaimExpectedVersions,
) -> None:
    observation = receipt.cancellation_clock_observation
    prior_observation = receipt.prior_permit.permit_clock_observation
    if not (
        observation.monotonic_observation_ns
        > prior_observation.monotonic_observation_ns
        and observation.monotonic_sequence > prior_observation.monotonic_sequence
    ):
        raise ValueError(
            "cancellation clock monotonic observation must be later than prior permit"
        )
    if receipt.cancelled_at != observation.wall_clock_utc:
        raise ValueError("cancellation time must equal its clock wall observation")
    if (
        observation.clock_health is ClockHealth.HEALTHY
        and receipt.cancelled_at <= receipt.prior_permit.issued_at
    ):
        raise ValueError(
            "healthy cancellation wall clock must be later than prior permit"
        )

    current = receipt.evaluation_state
    authority_changed = (
        current.authorization_lifecycle is not AuthorizationLifecycle.ACTIVE
        or current.registry_epoch != expected.registry_epoch
        or current.trust_bundle_hash != expected.trust_bundle_hash
        or current.policy_activation_hash != expected.policy_activation_hash
        or current.policy_epoch != expected.policy_epoch
        or current.authority_epoch != expected.authority_epoch
        or current.risk_epoch != expected.risk_epoch
        or current.authorization_id != expected.authorization_id
        or current.authorization_version != expected.authorization_version
        or current.authorization_envelope_hash != expected.authorization_envelope_hash
        or current.authorization_status_version != expected.authorization_status_version
        or current.authorization_status_hash != expected.authorization_status_hash
        or current.evidence_set_merkle_root != expected.evidence_set_merkle_root
        or current.authorization_revalidation.verification_result
        is AuthorizationIssuerVerificationResult.INVALID
    )
    fence_changed = (
        current.entry_fence_id,
        current.entry_fence_hash,
        current.entry_fence_version,
        current.writer_fencing_epoch,
    ) != (
        expected.entry_fence_id,
        expected.entry_fence_hash,
        expected.entry_fence_version,
        expected.writer_fencing_epoch,
    )
    current_stage_truth = tuple(
        (
            stage_identity(item),
            item.stage_loss_version,
            item.stage_loss_latch,
        )
        for item in current.stage_loss_bindings
    )
    expected_stage_truth = tuple(
        (
            stage_identity(item),
            item.stage_loss_version,
            item.stage_loss_latch,
        )
        for item in expected.stage_loss_bindings
    )
    post_permit_fact_changed = (
        current.capital_version != expected.capital_version
        or current.capital_stream_version != expected.capital_stream_version
        or current.risk_snapshot_artifact_hash
        != expected.post_risk_snapshot_artifact_hash
        or current_stage_truth != expected_stage_truth
        or current.reservation_version != expected.reservation_version
        or tuple(current.reservation_allocations)
        != tuple(expected.post_reservation_allocations)
        or current.remaining_reserved_cash_cents
        != expected.remaining_reserved_cash_cents
        or current.active_outbox_batch_id != expected.outbox_batch_id
        or current.active_outbox_payload_hash != expected.outbox_payload_hash
    )
    witnesses = witnessed_cancel_reasons(
        authorization_failed=authority_changed,
        stage_halted=any(
            item.stage_loss_latch is not StageLossLatchState.CLEAR
            for item in current.stage_loss_bindings
        ),
        reconciliation_halted=(
            current.risk_snapshot.reconciliation_latch
            is not ReconciliationLatchState.CLEAR
        ),
        fact_integrity_failed=(
            observation.clock_health is not ClockHealth.HEALTHY
            or post_permit_fact_changed
            or current.risk_snapshot.freshness is not RiskSnapshotFreshness.FRESH
            or current.risk_snapshot.completeness
            is not RiskSnapshotCompleteness.COMPLETE
        ),
        fence_changed=fence_changed,
        deadline_reached=(
            observation.clock_health is ClockHealth.HEALTHY
            and receipt.cancelled_at > expected.effective_send_deadline
        ),
        authorization_reason=PermitReasonCode.AUTHORIZATION_CANCEL,
        stage_reason=PermitReasonCode.STAGE_HALT_CANCEL,
        reconciliation_reason=PermitReasonCode.RECONCILIATION_CANCEL,
        fact_reason=PermitReasonCode.FACT_INTEGRITY_CANCEL,
        fence_reason=PermitReasonCode.FENCE_CANCEL,
        deadline_reason=PermitReasonCode.DEADLINE_CANCEL,
    )
    if current.risk_snapshot.risk_latch is not RiskLatchState.CLEAR:
        witnesses = witnesses | {PermitReasonCode.RISK_HALT_CANCEL}
    if receipt.reason_code not in witnesses:
        raise ValueError(
            "entry cancellation reason must be witnessed by current authority, "
            "risk, stage, reconciliation, fact, fence, or deadline truth"
        )


def _validate_receipt_cancellation_binding(
    receipt: EntryCancellationReceipt,
) -> None:
    prior = receipt.prior_permit
    current = receipt.evaluation_state
    binding = receipt.cancellation_binding
    ensure_equal_bindings(
        {
            "permit nonce": (binding.permit_nonce, prior.permit_nonce),
            "post permit nonce state": (
                binding.post_permit_nonce_state,
                PermitNonceState.INVALIDATED,
            ),
            "reservation ID": (binding.reservation_id, current.reservation_id),
            "pre-reservation version": (
                binding.pre_reservation_version,
                current.reservation_version,
            ),
            "post-reservation state": (
                binding.post_reservation_state,
                ReservationState.RELEASED,
            ),
            "released cash": (
                binding.released_cash_cents,
                current.remaining_reserved_cash_cents,
            ),
            "remaining reserved cash": (
                binding.remaining_reserved_cash_cents,
                0,
            ),
            "outbox batch": (
                binding.outbox_batch_id,
                current.active_outbox_batch_id,
            ),
            "outbox payload": (
                binding.outbox_payload_hash,
                current.active_outbox_payload_hash,
            ),
            "post outbox state": (
                binding.post_outbox_state,
                OutboxState.TOMBSTONED,
            ),
            "writer fencing": (
                binding.writer_fencing_epoch,
                current.writer_fencing_epoch,
            ),
        },
        prefix="entry cancellation binding",
    )
    ensure_strict_advance(
        prior.permit_nonce_sequence,
        binding.post_permit_nonce_sequence,
        label="entry cancellation permit nonce",
    )
    ensure_strict_advance(
        current.reservation_version,
        binding.post_reservation_version,
        label="entry cancellation reservation",
    )
    if binding.released_cash_cents > 0:
        ensure_strict_advance(
            current.capital_version,
            binding.post_capital_version,
            label="entry cancellation capital",
        )
        ensure_strict_advance(
            current.capital_stream_version,
            binding.post_capital_stream_version,
            label="entry cancellation capital stream",
        )
    elif (
        binding.post_capital_version != current.capital_version
        or binding.post_capital_stream_version != current.capital_stream_version
        or binding.post_risk_snapshot != current.risk_snapshot
        or binding.post_risk_snapshot_artifact_hash
        != current.risk_snapshot_artifact_hash
    ):
        raise ValueError(
            "zero-release entry cancellation capital and risk snapshot must remain quiet"
        )
    zero_allocations = tuple(
        item.model_copy(update={"reserved_cash_cents": 0})
        for item in current.reservation_allocations
    )
    _validate_post_risk_snapshot(
        prior.seal,
        current,
        binding.post_risk_snapshot,
        zero_allocations,
        binding.post_capital_version,
        current.stage_loss_bindings,
        event_at=receipt.cancelled_at,
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
            or self.effective_gross_cash_cents != 0
            or (
                self.side is ExecutionSide.ENTRY
                and self.effective_position_quantity != 0
            )
        ):
            raise ValueError(
                "BUSTED revision must remove its fill and cash; ENTRY bust must be flat"
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
            and not (
                self.revision_kind is ExecutionRevisionKind.CORRECTED
                or (
                    self.revision_kind is ExecutionRevisionKind.BUSTED
                    and self.side is ExecutionSide.EXIT
                    and self.effective_position_quantity > 0
                )
            )
        ):
            raise ValueError(
                "only a correction or busted EXIT can reopen an economic projection"
            )
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
        previous_revision: ExecutionRevision | None = None
        stable_exit_mandate_id: str | None = None
        maximum_seen_mandate_revision = 0
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
                assert previous_revision is not None
                reopened_transition = (
                    previous_revision.effective_position_quantity <= 0
                    and revision.effective_position_quantity > 0
                )
                is_reopened_projection = (
                    revision.economic_projection_state
                    is EconomicProjectionState.REOPENED_BY_CORRECTION
                )
                if reopened_transition:
                    if (
                        revision.effective_position_state
                        is not EffectivePositionState.EXIT_PENDING
                        or not is_reopened_projection
                    ):
                        raise ValueError(
                            "flat or nonpositive position reopen requires EXIT_PENDING "
                            "and REOPENED_BY_CORRECTION projection"
                        )
                    assert revision.exit_mandate_revision is not None
                    if revision.exit_mandate_revision <= max(
                        1, maximum_seen_mandate_revision
                    ):
                        raise ValueError(
                            "reopened exit mandate revision must advance every prior "
                            "seen mandate revision and the initial revision"
                        )
                elif is_reopened_projection:
                    raise ValueError(
                        "REOPENED_BY_CORRECTION requires a nonpositive-to-positive "
                        "position projection"
                    )
            if revision.exit_mandate_id is not None:
                if stable_exit_mandate_id is None:
                    stable_exit_mandate_id = revision.exit_mandate_id
                elif revision.exit_mandate_id != stable_exit_mandate_id:
                    raise ValueError(
                        "exit mandate ID must remain stable across execution revisions"
                    )
                assert revision.exit_mandate_revision is not None
                maximum_seen_mandate_revision = max(
                    maximum_seen_mandate_revision,
                    revision.exit_mandate_revision,
                )
            previous_observed_at = revision.observed_at
            previous_revision = revision

        if self.active_revision != self.revisions[-1].revision:
            raise ValueError("active revision must be the highest appended revision")
        return self


__all__ = [
    "ActiveEntryClaimState",
    "AuthorizationIssuerRevalidation",
    "AuthorizationIssuerVerificationResult",
    "EconomicProjectionState",
    "EffectivePositionState",
    "EntryCancellationReceipt",
    "ExecutionMode",
    "ExecutionPermit",
    "ExecutionPermitLine",
    "ExecutionRevision",
    "ExecutionRevisionHistory",
    "ExecutionRevisionKind",
    "ExecutionSide",
    "ORDER_STATE_TRANSITIONS",
    "OutboxState",
    "OrderState",
    "PLAN_STATE_TRANSITIONS",
    "PlanState",
    "PermitDisposition",
    "PermitCancellationBinding",
    "PermitEvaluationState",
    "PermitLineMechanicalBinding",
    "PermitNonceState",
    "PermitReasonCode",
    "ReservationLineAllocation",
    "ReservationState",
    "SendClaimExpectedVersions",
    "validate_order_transition",
    "validate_plan_transition",
]
