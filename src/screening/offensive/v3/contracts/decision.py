"""Storage-free Revision 2 portfolio proposal contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from .base import (
    CanonicalModel,
    EvidenceScope,
    ExactInteger,
    ExecutionMode,
    MoneyCents,
    QuantityUnits,
    SchemaVersion,
    Sha256,
    UtcInstant,
    domain_hash,
)
from ._decision_relations import (
    ensure_equal_bindings,
    ensure_seal_time_chain,
    ensure_unique_stage_budget_mapping,
)
from .evidence import EvidenceEnvelope, NonEmptyStr
from .risk import StageLossLatchState
from .trust import ArtifactKind


PositiveExactInt = Annotated[ExactInteger, Field(ge=1)]
NonNegativeExactInt = Annotated[ExactInteger, Field(ge=0)]
PositiveQuantity = Annotated[QuantityUnits, Field(gt=0)]
PositiveCents = Annotated[MoneyCents, Field(gt=0)]
NonNegativeCents = Annotated[MoneyCents, Field(ge=0)]
NonNegativeQuantity = Annotated[QuantityUnits, Field(ge=0)]


class ClockHealth(StrEnum):
    """Gateway-owned trusted-clock health at the frozen observation."""

    HEALTHY = "HEALTHY"
    UNKNOWN = "UNKNOWN"
    EXCESSIVE_SKEW = "EXCESSIVE_SKEW"
    ROLLBACK_DETECTED = "ROLLBACK_DETECTED"


class TrustedClockObservation(CanonicalModel):
    """One immutable trusted-clock reading with monotonic provenance."""

    observation_id: NonEmptyStr
    raw_payload_hash: Sha256
    wall_clock_utc: UtcInstant
    monotonic_observation_ns: NonNegativeExactInt
    monotonic_sequence: PositiveExactInt
    clock_health: ClockHealth


class TrustedExecutionWindow(CanonicalModel):
    """Exact exchange calendar, cutoff, and trusted-clock deadline binding."""

    signal_session: date
    target_entry_session: date
    exchange_id: NonEmptyStr
    calendar_snapshot_id: NonEmptyStr
    calendar_snapshot_hash: Sha256
    calendar_snapshot_version: PositiveExactInt
    cutoff_snapshot_id: NonEmptyStr
    cutoff_snapshot_hash: Sha256
    cutoff_snapshot_version: PositiveExactInt
    cutoff_snapshot_session: date
    cutoff_snapshot_exchange_id: NonEmptyStr
    execution_policy_version: NonEmptyStr
    cutoff_policy_version: NonEmptyStr
    seal_clock_observation: TrustedClockObservation
    t0_close_finalized_at: UtcInstant
    seal_creation_deadline: UtcInstant
    permit_issue_deadline: UtcInstant
    gateway_send_deadline: UtcInstant
    broker_auction_submission_cutoff: UtcInstant

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.target_entry_session <= self.signal_session:
            raise ValueError("target entry session must follow signal session")
        if self.cutoff_snapshot_session != self.target_entry_session:
            raise ValueError("cutoff snapshot session must match target entry session")
        if self.cutoff_snapshot_exchange_id != self.exchange_id:
            raise ValueError("cutoff snapshot exchange must match execution exchange")
        if not (
            self.t0_close_finalized_at
            < self.seal_creation_deadline
            < self.permit_issue_deadline
            < self.gateway_send_deadline
            < self.broker_auction_submission_cutoff
        ):
            raise ValueError(
                "trusted deadlines require close < seal < permit < send < broker cutoff"
            )
        if not (
            self.t0_close_finalized_at
            <= self.seal_clock_observation.wall_clock_utc
            <= self.seal_creation_deadline
        ):
            raise ValueError(
                "trusted clock observation must be between close finality and seal deadline"
            )
        return self


class AuthorizationIssuanceBinding(CanonicalModel):
    """Immutable authorization-envelope issuer claims consumed by a seal."""

    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.decision.authorization-issuance-binding.v1"
    )

    authorization_envelope_hash: Sha256
    authorization_issuer_id: NonEmptyStr
    authorization_issuer_key_id: NonEmptyStr
    authorization_issuer_capability: NonEmptyStr
    authorization_issuer_capability_version: NonEmptyStr
    authorization_issuer_identity_fingerprint: Sha256
    registry_epoch: PositiveExactInt
    trust_bundle_hash: Sha256

    def artifact_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, 2, self)


class GatewayIssuerBinding(CanonicalModel):
    """Verified current Capital Gateway issuer capability provenance."""

    issuer_id: NonEmptyStr
    key_id: NonEmptyStr
    capability_artifact_kind: ArtifactKind
    capability_namespace: NonEmptyStr
    capability_mode: ExecutionMode
    capability_schema_major: SchemaVersion
    capability_version: NonEmptyStr
    capability_scope: NonEmptyStr
    verification_result: Literal["VALID"]
    verified_at: UtcInstant
    valid_until: UtcInstant
    trust_bundle_hash: Sha256
    registry_epoch: PositiveExactInt

    @model_validator(mode="after")
    def validate_validity_window(self) -> Self:
        if self.valid_until <= self.verified_at:
            raise ValueError("Gateway issuer validity must extend beyond verification")
        return self


class ShadowIssuerBinding(CanonicalModel):
    """Verified current Growth Kernel shadow issuer capability provenance."""

    issuer_id: NonEmptyStr
    key_id: NonEmptyStr
    capability_artifact_kind: ArtifactKind
    capability_namespace: NonEmptyStr
    capability_mode: ExecutionMode
    capability_schema_major: SchemaVersion
    capability_version: NonEmptyStr
    capability_scope: NonEmptyStr
    verification_result: Literal["VALID"]
    verified_at: UtcInstant
    valid_until: UtcInstant
    trust_bundle_hash: Sha256
    registry_epoch: PositiveExactInt

    @model_validator(mode="after")
    def validate_validity_window(self) -> Self:
        if self.valid_until <= self.verified_at:
            raise ValueError("shadow issuer validity must extend beyond verification")
        return self


class StageAdmissionBinding(CanonicalModel):
    """One composite stage-loss version transition consumed by admission."""

    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    stage_loss_budget_id: NonEmptyStr
    expected_stage_loss_version: PositiveExactInt
    post_stage_loss_version: PositiveExactInt
    stage_loss_latch: StageLossLatchState

    @model_validator(mode="after")
    def validate_version_advance(self) -> Self:
        if self.post_stage_loss_version <= self.expected_stage_loss_version:
            raise ValueError("post stage-loss version must monotonically advance")
        if self.stage_loss_latch is not StageLossLatchState.CLEAR:
            raise ValueError("stage admission cannot seal a halted stage")
        return self

    def identity(self) -> tuple[str, str, str, str]:
        return (
            self.research_program_id,
            self.economic_lineage_id,
            self.stage_id,
            self.stage_loss_budget_id,
        )


class SealReserveLineBinding(CanonicalModel):
    """Exact per-line cash allocation created with a seal."""

    order_line_id: NonEmptyStr
    reservation_allocation_id: NonEmptyStr
    reserved_cash_cents: PositiveCents


class DecisionLogicalKey(CanonicalModel):
    """Economic idempotency key shared by every authority/policy epoch."""

    portfolio_id: NonEmptyStr
    signal_session: date
    decision_cycle_id: NonEmptyStr


class PriorSealEligibilityBinding(CanonicalModel):
    """Immutable facts proving whether a prior seal can be superseded."""

    prior_seal_id: NonEmptyStr
    prior_seal_revision: PositiveExactInt
    prior_seal_artifact_hash: Sha256
    logical_key: DecisionLogicalKey
    permit_issuance_sequence: NonNegativeExactInt
    fencing_token_issuance_sequence: NonNegativeExactInt
    live_order_count: NonNegativeExactInt


class PlanEvidence(EvidenceEnvelope):
    """Producer raw-target evidence; it carries no execution authority."""

    evidence_kind: Literal["plan"]
    portfolio_id: NonEmptyStr
    signal_session: date
    economic_lineage_id: NonEmptyStr
    snapshot_id: NonEmptyStr
    raw_target_fraction: Annotated[Decimal, Field(gt=0, le=1)]
    created_at: UtcInstant

    @model_validator(mode="after")
    def validate_plan_scope(self) -> Self:
        if self.subject_scope is not EvidenceScope.STRATEGY_LINEAGE:
            raise ValueError("plan evidence requires strategy-lineage scope")
        if self.family_id == self.economic_lineage_id:
            raise ValueError("family_id must remain distinct from economic_lineage_id")
        return self


class StageLossExpectedVersion(CanonicalModel):
    """One stage-loss CAS component used by the Capital Gateway."""

    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    stage_loss_budget_id: NonEmptyStr
    stage_loss_version: PositiveExactInt
    stage_loss_latch: StageLossLatchState


class PortfolioOrderLine(CanonicalModel):
    """One fixed, entry-only order line in a complete portfolio proposal."""

    order_line_id: NonEmptyStr
    security_id: NonEmptyStr
    order_action: Literal["ENTRY"]
    producer_namespace: NonEmptyStr
    family_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    research_program_id: NonEmptyStr
    stage_id: NonEmptyStr
    stage_manifest_hash: Sha256
    grant_id: NonEmptyStr
    grant_certificate_hash: Sha256
    authorization_id: NonEmptyStr
    authorization_version: PositiveExactInt
    plan_evidence: PlanEvidence
    plan_evidence_artifact_hash: Sha256
    plan_payload_content_hash: Sha256
    mode: ExecutionMode
    target_entry_session: date
    exit_session_ordinal: Literal[10]
    sealed_quantity_units: PositiveQuantity
    lot_size_units: PositiveQuantity
    lot_rule_version: NonEmptyStr
    order_type: NonEmptyStr
    limit_price_cents: PositiveCents
    worst_case_price_cents: PositiveCents
    price_boundary_version: NonEmptyStr
    time_in_force: NonEmptyStr
    worst_case_fee_reserve_cents: NonNegativeCents
    worst_case_cash_reserve_cents: PositiveCents

    @field_validator("exit_session_ordinal", mode="before")
    @classmethod
    def validate_native_t_plus_ten(cls, value: object) -> object:
        if type(value) is not int or value != 10:
            raise ValueError("T+10 session ordinal must be the native integer 10")
        return value

    @model_validator(mode="after")
    def validate_entry_economics_and_provenance(self) -> Self:
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError("research execution cannot create a portfolio order line")
        if self.family_id == self.economic_lineage_id:
            raise ValueError("family_id must remain distinct from economic_lineage_id")
        if self.sealed_quantity_units % self.lot_size_units != 0:
            raise ValueError("sealed quantity must be an exact whole lot")
        if self.limit_price_cents > self.worst_case_price_cents:
            raise ValueError("limit price cannot exceed worst-case price")
        required_reserve = (
            self.worst_case_price_cents * self.sealed_quantity_units
            + self.worst_case_fee_reserve_cents
        )
        if self.worst_case_cash_reserve_cents != required_reserve:
            raise ValueError(
                "cash reserve must exactly equal worst-case price times quantity "
                "plus fee reserve"
            )

        plan = self.plan_evidence
        if plan.subject_producer != self.producer_namespace:
            raise ValueError("plan evidence producer must match order producer")
        if plan.family_id != self.family_id:
            raise ValueError("plan evidence family must match order family")
        if plan.economic_lineage_id != self.economic_lineage_id:
            raise ValueError("plan evidence lineage must match order lineage")
        if plan.mode is not self.mode:
            raise ValueError("plan evidence mode must match order mode")
        if plan.content_hash() != self.plan_evidence_artifact_hash:
            raise ValueError("plan evidence artifact hash does not match evidence")
        if plan.payload_content_hash != self.plan_payload_content_hash:
            raise ValueError("plan payload content hash does not match evidence")
        if self.target_entry_session <= plan.signal_session:
            raise ValueError("target entry session must follow the signal session")
        return self


class GatewayExpectedVersions(CanonicalModel):
    """Complete CAS precondition bundle for first publication or supersede."""

    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.decision.gateway-expected-versions.v1"
    )

    policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveExactInt
    policy_epoch: PositiveExactInt
    authority_epoch: PositiveExactInt
    risk_epoch: PositiveExactInt
    authorization_id: NonEmptyStr
    authorization_version: PositiveExactInt
    authorization_envelope_hash: Sha256
    authorization_status_version: PositiveExactInt
    authorization_status_hash: Sha256
    evidence_set_merkle_root: Sha256
    entry_fence_id: NonEmptyStr
    entry_fence_hash: Sha256
    entry_fence_version: NonNegativeExactInt
    risk_snapshot_id: NonEmptyStr
    risk_snapshot_artifact_hash: Sha256
    capital_version: PositiveExactInt
    capital_stream_version: PositiveExactInt
    writer_fencing_epoch: PositiveExactInt
    stage_loss_expected_versions: Annotated[
        tuple[StageLossExpectedVersion, ...], Field(min_length=1)
    ]
    expected_active_seal_id: NonEmptyStr | None
    expected_active_seal_revision: PositiveExactInt | None
    expected_active_seal_logical_key: DecisionLogicalKey | None
    expected_active_seal_artifact_hash: Sha256 | None
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_cas_bundle(self) -> Self:
        active_binding = (
            self.expected_active_seal_id,
            self.expected_active_seal_revision,
            self.expected_active_seal_logical_key,
            self.expected_active_seal_artifact_hash,
        )
        populated = tuple(item is not None for item in active_binding)
        if any(populated) and not all(populated):
            raise ValueError(
                "expected active seal binding must be an all-or-none tuple"
            )

        ensure_unique_stage_budget_mapping(
            self.stage_loss_expected_versions,
            label="stage loss expected versions",
        )
        return self

    def artifact_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, self.schema_major, self)


class PortfolioDecision(CanonicalModel):
    """Complete pure Growth Kernel proposal; it grants no send authority."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.decision.portfolio-proposal.v1"

    logical_key: DecisionLogicalKey
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None
    broker_account_fingerprint: Sha256 | None
    base_currency: NonEmptyStr
    mode: ExecutionMode
    target_entry_session: date
    target_portfolio_policy_fingerprint: Sha256
    policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveExactInt
    policy_epoch: PositiveExactInt
    authority_epoch: PositiveExactInt
    risk_epoch: PositiveExactInt
    authorization_id: NonEmptyStr
    authorization_version: PositiveExactInt
    authorization_artifact_hash: Sha256
    evidence_set_merkle_root: Sha256
    risk_snapshot_id: NonEmptyStr
    risk_snapshot_artifact_hash: Sha256
    risk_snapshot_as_of: UtcInstant
    capital_version: PositiveExactInt
    capital_stream_version: PositiveExactInt
    writer_fencing_epoch: PositiveExactInt
    order_lines: Annotated[tuple[PortfolioOrderLine, ...], Field(min_length=1)]
    total_worst_case_cash_reserve_cents: PositiveCents
    decision_cutoff: UtcInstant
    proposal_created_at: UtcInstant
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_portfolio_proposal(self) -> Self:
        self._validate_context_and_time()
        self._validate_lines_and_reserve()
        return self

    def _validate_context_and_time(self) -> None:
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError("research execution cannot create PortfolioDecision")
        if self.decision_cutoff >= self.proposal_created_at:
            raise ValueError("decision cutoff must precede proposal creation")
        if self.logical_key.portfolio_id != self.portfolio_id:
            raise ValueError("logical key portfolio must match decision portfolio")
        if self.target_entry_session <= self.logical_key.signal_session:
            raise ValueError("target entry session must follow signal session")
        if self.risk_snapshot_as_of > self.proposal_created_at:
            raise ValueError("risk snapshot as_of cannot follow proposal creation")

        if self.mode is ExecutionMode.BROKER_CONFIRMED:
            if (
                self.broker_account_id is None
                or self.broker_account_fingerprint is None
            ):
                raise ValueError("broker mode requires account ID and fingerprint")
        elif self.mode is ExecutionMode.MANUAL_CONFIRMED:
            if (
                self.broker_account_id is None
                or self.broker_account_fingerprint is not None
            ):
                raise ValueError("manual mode requires account ID without fingerprint")
        elif (
            self.broker_account_id is not None
            or self.broker_account_fingerprint is not None
        ):
            raise ValueError("proxy mode cannot bind a broker account")

    def _validate_lines_and_reserve(self) -> None:
        line_ids = [line.order_line_id for line in self.order_lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("portfolio order line IDs must be unique")
        canonical = sorted(self.order_lines, key=lambda line: line.order_line_id)
        if list(self.order_lines) != canonical:
            raise ValueError("portfolio order lines must use canonical order")
        reserve = sum(line.worst_case_cash_reserve_cents for line in self.order_lines)
        if reserve != self.total_worst_case_cash_reserve_cents:
            raise ValueError("portfolio total reserve must exactly equal line reserves")

        lineage_provenance: dict[tuple[str, str], tuple[str, str, str, str]] = {}
        for line in self.order_lines:
            if line.authorization_id != self.authorization_id:
                raise ValueError("order authorization ID does not match proposal")
            if line.authorization_version != self.authorization_version:
                raise ValueError("order authorization version does not match proposal")
            if line.mode is not self.mode:
                raise ValueError("order mode does not match decision mode")
            if line.target_entry_session != self.target_entry_session:
                raise ValueError("order target entry session does not match decision")
            plan = line.plan_evidence
            if plan.portfolio_id != self.portfolio_id:
                raise ValueError("plan portfolio does not match decision portfolio")
            if plan.signal_session != self.logical_key.signal_session:
                raise ValueError("plan signal session does not match logical key")
            if plan.policy_epoch != self.policy_epoch:
                raise ValueError("plan policy epoch does not match decision policy")
            if (
                plan.available_at > self.decision_cutoff
                or plan.created_at > self.decision_cutoff
            ):
                raise ValueError(
                    "plan evidence must be available by decision cutoff for PIT use"
                )
            lineage_key = (line.research_program_id, line.economic_lineage_id)
            provenance = (
                line.stage_id,
                line.stage_manifest_hash,
                line.grant_id,
                line.grant_certificate_hash,
            )
            prior = lineage_provenance.setdefault(lineage_key, provenance)
            if prior != provenance:
                raise ValueError(
                    "stage and grant provenance must be stable within a lineage"
                )

    def artifact_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, self.schema_major, self)


def _validate_issuer_binding(
    binding: GatewayIssuerBinding | ShadowIssuerBinding,
    *,
    artifact_kind: ArtifactKind,
    artifact_namespace: str,
    mode: ExecutionMode,
    schema_major: int,
    portfolio_id: str,
    issued_at: UtcInstant,
    trust_bundle_hash: str | None = None,
    registry_epoch: int | None = None,
) -> None:
    expected = (
        artifact_kind,
        artifact_namespace,
        mode,
        schema_major,
        f"portfolio:{portfolio_id}",
    )
    actual = (
        binding.capability_artifact_kind,
        binding.capability_namespace,
        binding.capability_mode,
        binding.capability_schema_major,
        binding.capability_scope,
    )
    if actual != expected:
        raise ValueError(
            "issuer capability artifact, namespace, mode, schema, or scope mismatch"
        )
    if not binding.verified_at <= issued_at < binding.valid_until:
        raise ValueError(
            "issuer capability must be verified and valid at artifact issuance"
        )
    if trust_bundle_hash is not None and binding.trust_bundle_hash != trust_bundle_hash:
        raise ValueError("issuer current trust bundle hash mismatch")
    if registry_epoch is not None and binding.registry_epoch != registry_epoch:
        raise ValueError("issuer current registry epoch mismatch")


class PortfolioDecisionSeal(CanonicalModel):
    """Gateway-owned immutable receipt for one atomically admitted proposal."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.decision.portfolio-seal.v1"

    artifact_kind: Literal[ArtifactKind.PORTFOLIO_DECISION_SEAL]
    artifact_namespace: Literal["capital-gateway.entry-seal.v1"]
    schema_major: SchemaVersion
    seal_id: NonEmptyStr
    seal_revision: PositiveExactInt
    logical_key: DecisionLogicalKey
    supersedes_seal_id: NonEmptyStr | None
    supersedes_seal_revision: PositiveExactInt | None
    prior_seal_eligibility: PriorSealEligibilityBinding | None
    proposal: PortfolioDecision
    proposal_artifact_hash: Sha256
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None
    broker_account_fingerprint: Sha256 | None
    base_currency: NonEmptyStr
    mode: ExecutionMode
    target_entry_session: date
    target_portfolio_policy_fingerprint: Sha256
    policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveExactInt
    policy_epoch: PositiveExactInt
    authority_epoch: PositiveExactInt
    risk_epoch: PositiveExactInt
    authorization_id: NonEmptyStr
    authorization_version: PositiveExactInt
    authorization_envelope_hash: Sha256
    authorization_issuance_binding: AuthorizationIssuanceBinding
    authorization_issuance_binding_artifact_hash: Sha256
    authorization_status_version: PositiveExactInt
    authorization_status_hash: Sha256
    evidence_set_merkle_root: Sha256
    entry_fence_id: NonEmptyStr
    entry_fence_hash: Sha256
    entry_fence_version: NonNegativeExactInt
    risk_snapshot_id: NonEmptyStr
    risk_snapshot_artifact_hash: Sha256
    capital_version: PositiveExactInt
    capital_stream_version: PositiveExactInt
    stage_admission_bindings: Annotated[
        tuple[StageAdmissionBinding, ...], Field(min_length=1)
    ]
    writer_fencing_epoch: PositiveExactInt
    consumed_gateway_expected_versions: GatewayExpectedVersions
    consumed_gateway_expected_versions_artifact_hash: Sha256
    reservation_id: NonEmptyStr
    reservation_version: PositiveExactInt
    line_reserve_bindings: Annotated[
        tuple[SealReserveLineBinding, ...], Field(min_length=1)
    ]
    total_reserved_cash_cents: PositiveCents
    post_admission_capital_version: PositiveExactInt
    post_admission_capital_stream_version: PositiveExactInt
    post_admission_reservation_version: PositiveExactInt
    post_admission_risk_snapshot_id: NonEmptyStr
    post_admission_risk_snapshot_artifact_hash: Sha256
    execution_window: TrustedExecutionWindow
    created_at: UtcInstant
    issuer_binding: GatewayIssuerBinding

    @model_validator(mode="after")
    def validate_seal(self) -> Self:
        self._validate_proposal_binding()
        self._validate_consumed_expected_versions()
        self._validate_stage_and_reserve_bindings()
        self._validate_supersede_binding()
        self._validate_time_and_issuer()
        return self

    def _validate_proposal_binding(self) -> None:
        proposal = self.proposal
        if proposal.artifact_hash() != self.proposal_artifact_hash:
            raise ValueError("proposal artifact hash does not match embedded proposal")
        bindings = {
            "logical key": (self.logical_key, proposal.logical_key),
            "portfolio": (self.portfolio_id, proposal.portfolio_id),
            "broker account": (self.broker_account_id, proposal.broker_account_id),
            "broker account fingerprint": (
                self.broker_account_fingerprint,
                proposal.broker_account_fingerprint,
            ),
            "base currency": (self.base_currency, proposal.base_currency),
            "mode": (self.mode, proposal.mode),
            "target entry session": (
                self.target_entry_session,
                proposal.target_entry_session,
            ),
            "target portfolio policy": (
                self.target_portfolio_policy_fingerprint,
                proposal.target_portfolio_policy_fingerprint,
            ),
            "policy activation": (
                self.policy_activation_hash,
                proposal.policy_activation_hash,
            ),
            "trust bundle": (self.trust_bundle_hash, proposal.trust_bundle_hash),
            "registry epoch": (self.registry_epoch, proposal.registry_epoch),
            "policy epoch": (self.policy_epoch, proposal.policy_epoch),
            "authority epoch": (self.authority_epoch, proposal.authority_epoch),
            "risk epoch": (self.risk_epoch, proposal.risk_epoch),
            "authorization ID": (
                self.authorization_id,
                proposal.authorization_id,
            ),
            "authorization version": (
                self.authorization_version,
                proposal.authorization_version,
            ),
            "authorization envelope": (
                self.authorization_envelope_hash,
                proposal.authorization_artifact_hash,
            ),
            "evidence root": (
                self.evidence_set_merkle_root,
                proposal.evidence_set_merkle_root,
            ),
            "risk snapshot ID": (
                self.risk_snapshot_id,
                proposal.risk_snapshot_id,
            ),
            "risk snapshot artifact": (
                self.risk_snapshot_artifact_hash,
                proposal.risk_snapshot_artifact_hash,
            ),
            "capital version": (self.capital_version, proposal.capital_version),
            "capital stream version": (
                self.capital_stream_version,
                proposal.capital_stream_version,
            ),
            "writer fencing epoch": (
                self.writer_fencing_epoch,
                proposal.writer_fencing_epoch,
            ),
        }
        ensure_equal_bindings(bindings, prefix="seal proposal")
        issuance = self.authorization_issuance_binding
        if issuance.artifact_hash() != (
            self.authorization_issuance_binding_artifact_hash
        ):
            raise ValueError("authorization issuance binding artifact hash mismatch")
        ensure_equal_bindings(
            {
                "authorization envelope": (
                    issuance.authorization_envelope_hash,
                    self.authorization_envelope_hash,
                ),
            },
            prefix="authorization issuance binding",
        )
        if issuance.registry_epoch > self.registry_epoch:
            raise ValueError(
                "authorization issuance registry epoch cannot exceed current epoch"
            )
        if (
            issuance.registry_epoch == self.registry_epoch
            and issuance.trust_bundle_hash != self.trust_bundle_hash
        ):
            raise ValueError(
                "same authorization issuance registry epoch requires exact trust bundle"
            )

    def _validate_consumed_expected_versions(self) -> None:
        expected = self.consumed_gateway_expected_versions
        if (
            expected.artifact_hash()
            != self.consumed_gateway_expected_versions_artifact_hash
        ):
            raise ValueError("consumed Gateway expected artifact hash mismatch")
        bindings = {
            "policy": (expected.policy_activation_hash, self.policy_activation_hash),
            "trust": (expected.trust_bundle_hash, self.trust_bundle_hash),
            "registry": (expected.registry_epoch, self.registry_epoch),
            "policy epoch": (expected.policy_epoch, self.policy_epoch),
            "authority": (expected.authority_epoch, self.authority_epoch),
            "risk epoch": (expected.risk_epoch, self.risk_epoch),
            "authorization ID": (expected.authorization_id, self.authorization_id),
            "authorization version": (
                expected.authorization_version,
                self.authorization_version,
            ),
            "authorization envelope": (
                expected.authorization_envelope_hash,
                self.authorization_envelope_hash,
            ),
            "authorization status version": (
                expected.authorization_status_version,
                self.authorization_status_version,
            ),
            "authorization status": (
                expected.authorization_status_hash,
                self.authorization_status_hash,
            ),
            "evidence": (
                expected.evidence_set_merkle_root,
                self.evidence_set_merkle_root,
            ),
            "entry fence ID": (expected.entry_fence_id, self.entry_fence_id),
            "entry fence": (expected.entry_fence_hash, self.entry_fence_hash),
            "entry fence version": (
                expected.entry_fence_version,
                self.entry_fence_version,
            ),
            "risk snapshot ID": (
                expected.risk_snapshot_id,
                self.risk_snapshot_id,
            ),
            "risk snapshot": (
                expected.risk_snapshot_artifact_hash,
                self.risk_snapshot_artifact_hash,
            ),
            "capital": (expected.capital_version, self.capital_version),
            "capital stream": (
                expected.capital_stream_version,
                self.capital_stream_version,
            ),
            "writer fencing": (
                expected.writer_fencing_epoch,
                self.writer_fencing_epoch,
            ),
        }
        ensure_equal_bindings(bindings, prefix="consumed expected seal")

    def _validate_stage_and_reserve_bindings(self) -> None:
        proposal_identities = {
            (line.research_program_id, line.economic_lineage_id, line.stage_id)
            for line in self.proposal.order_lines
        }
        stage_identities = [item.identity() for item in self.stage_admission_bindings]
        ensure_unique_stage_budget_mapping(
            self.stage_admission_bindings,
            label="stage admission",
        )
        if {identity[:3] for identity in stage_identities} != proposal_identities:
            raise ValueError("stage admission coverage must exactly match proposal")

        expected_items = (
            self.consumed_gateway_expected_versions.stage_loss_expected_versions
        )
        expected_by_identity = {
            (
                item.research_program_id,
                item.economic_lineage_id,
                item.stage_id,
                item.stage_loss_budget_id,
            ): item
            for item in expected_items
        }
        if set(expected_by_identity) != set(stage_identities):
            raise ValueError("stage expected coverage must exactly match proposal")
        for admission in self.stage_admission_bindings:
            expected = expected_by_identity[admission.identity()]
            if (
                admission.expected_stage_loss_version != expected.stage_loss_version
                or admission.stage_loss_latch is not expected.stage_loss_latch
            ):
                raise ValueError("stage admission must match consumed expected version")

        proposal_by_line = {
            line.order_line_id: line for line in self.proposal.order_lines
        }
        reserve_ids = [item.order_line_id for item in self.line_reserve_bindings]
        allocation_ids = [
            item.reservation_allocation_id for item in self.line_reserve_bindings
        ]
        if len(reserve_ids) != len(set(reserve_ids)):
            raise ValueError("reserve order-line bindings must be unique")
        if len(allocation_ids) != len(set(allocation_ids)):
            raise ValueError("reservation allocation IDs must be unique")
        if reserve_ids != sorted(reserve_ids):
            raise ValueError("reserve line bindings must use canonical order")
        if set(reserve_ids) != set(proposal_by_line):
            raise ValueError("reserve line coverage must exactly match proposal")
        for reserve in self.line_reserve_bindings:
            if (
                reserve.reserved_cash_cents
                != proposal_by_line[reserve.order_line_id].worst_case_cash_reserve_cents
            ):
                raise ValueError("reserve allocation must equal proposal line reserve")
        reserve_total = sum(
            item.reserved_cash_cents for item in self.line_reserve_bindings
        )
        if (
            self.total_reserved_cash_cents != reserve_total
            or reserve_total != self.proposal.total_worst_case_cash_reserve_cents
        ):
            raise ValueError("aggregate reserve must exactly equal proposal reserves")
        if self.post_admission_capital_version <= self.capital_version:
            raise ValueError("post-admission capital version must strictly advance")
        if self.post_admission_capital_stream_version <= self.capital_stream_version:
            raise ValueError(
                "post-admission capital stream version must strictly advance"
            )
        if self.post_admission_reservation_version <= self.reservation_version:
            raise ValueError("post-admission reservation version must strictly advance")
        if (
            self.post_admission_risk_snapshot_id == self.risk_snapshot_id
            or self.post_admission_risk_snapshot_artifact_hash
            == self.risk_snapshot_artifact_hash
        ):
            raise ValueError(
                "post-admission risk snapshot identity and hash must both be new"
            )

    def _validate_supersede_binding(self) -> None:
        expected = self.consumed_gateway_expected_versions
        representations = (
            self.supersedes_seal_id,
            self.supersedes_seal_revision,
            self.prior_seal_eligibility,
            expected.expected_active_seal_id,
            expected.expected_active_seal_revision,
            expected.expected_active_seal_logical_key,
            expected.expected_active_seal_artifact_hash,
        )
        populated = tuple(item is not None for item in representations)
        if not any(populated):
            if self.seal_revision != 1:
                raise ValueError("first seal publication must use revision 1")
            return
        if not all(populated):
            raise ValueError(
                "supersede requires every prior and expected active representation"
            )
        prior = self.prior_seal_eligibility
        assert prior is not None
        if not (
            self.supersedes_seal_id
            == prior.prior_seal_id
            == expected.expected_active_seal_id
        ):
            raise ValueError("supersede prior seal ID representations mismatch")
        if not (
            self.supersedes_seal_revision
            == prior.prior_seal_revision
            == expected.expected_active_seal_revision
        ):
            raise ValueError("supersede prior seal revision representations mismatch")
        if not (
            self.logical_key
            == prior.logical_key
            == expected.expected_active_seal_logical_key
        ):
            raise ValueError("supersede logical key must match prior active seal")
        if (
            prior.prior_seal_artifact_hash
            != expected.expected_active_seal_artifact_hash
        ):
            raise ValueError("supersede prior artifact hash representations mismatch")
        if self.seal_revision <= prior.prior_seal_revision:
            raise ValueError("supersede seal revision must be strictly higher")
        if prior.permit_issuance_sequence != 0:
            raise ValueError("seal with prior permit issuance cannot supersede")
        if prior.fencing_token_issuance_sequence != 0:
            raise ValueError("seal with prior fencing token cannot supersede")
        if prior.live_order_count != 0:
            raise ValueError("seal with live order cannot supersede")

    def _validate_time_and_issuer(self) -> None:
        window = self.execution_window
        observation = window.seal_clock_observation
        if observation.clock_health is not ClockHealth.HEALTHY:
            raise ValueError("healthy trusted clock is required for a seal")
        if window.signal_session != self.logical_key.signal_session:
            raise ValueError("execution window signal session mismatches logical key")
        if window.target_entry_session != self.target_entry_session:
            raise ValueError("execution window target session mismatches seal")
        if self.created_at != observation.wall_clock_utc:
            raise ValueError("seal created_at must equal its trusted clock observation")
        ensure_seal_time_chain(
            close_finalized_at=window.t0_close_finalized_at,
            decision_cutoff=self.proposal.decision_cutoff,
            proposal_created_at=self.proposal.proposal_created_at,
            seal_created_at=self.created_at,
            seal_creation_deadline=window.seal_creation_deadline,
        )
        _validate_issuer_binding(
            self.issuer_binding,
            artifact_kind=self.artifact_kind,
            artifact_namespace=self.artifact_namespace,
            mode=self.mode,
            schema_major=self.schema_major,
            portfolio_id=self.portfolio_id,
            issued_at=self.created_at,
            trust_bundle_hash=self.trust_bundle_hash,
            registry_epoch=self.registry_epoch,
        )

    def artifact_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, self.schema_major, self)


class CounterfactualDecisionKey(CanonicalModel):
    """Non-authoritative identity kept distinct from an executable logical key."""

    portfolio_id: NonEmptyStr
    signal_session: date
    counterfactual_cycle_id: NonEmptyStr


class ShadowStageBinding(CanonicalModel):
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    trial_id: NonEmptyStr
    stage_manifest_hash: Sha256


class ShadowOrderLine(CanonicalModel):
    """One complete but non-authoritative counterfactual entry line."""

    shadow_line_id: NonEmptyStr
    security_id: NonEmptyStr
    producer_namespace: NonEmptyStr
    family_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    research_program_id: NonEmptyStr
    stage_id: NonEmptyStr
    trial_id: NonEmptyStr
    stage_manifest_hash: Sha256
    evidence_id: NonEmptyStr
    evidence_artifact_hash: Sha256
    evidence_payload_hash: Sha256
    target_quantity_units: PositiveQuantity
    lot_size_units: PositiveQuantity
    lot_rule_version: NonEmptyStr
    order_type: NonEmptyStr
    limit_price_cents: PositiveCents
    worst_case_price_cents: PositiveCents
    price_boundary_version: NonEmptyStr
    time_in_force: NonEmptyStr
    exit_session_ordinal: Literal[10]
    estimated_fee_cents: NonNegativeCents
    estimated_cash_reserve_cents: PositiveCents
    cost_assumption_version: NonEmptyStr
    execution_assumption_version: NonEmptyStr

    @field_validator("exit_session_ordinal", mode="before")
    @classmethod
    def validate_native_t_plus_ten(cls, value: object) -> object:
        if type(value) is not int or value != 10:
            raise ValueError("T+10 session ordinal must be the native integer 10")
        return value

    @model_validator(mode="after")
    def validate_line(self) -> Self:
        if self.target_quantity_units % self.lot_size_units != 0:
            raise ValueError("shadow quantity must be an exact whole lot")
        if self.limit_price_cents > self.worst_case_price_cents:
            raise ValueError("shadow limit price cannot exceed worst-case price")
        required = (
            self.worst_case_price_cents * self.target_quantity_units
            + self.estimated_fee_cents
        )
        if self.estimated_cash_reserve_cents != required:
            raise ValueError("shadow estimated reserve must equal line economics")
        return self


class ShadowDecision(CanonicalModel):
    """Complete counterfactual output with literal absence of execution authority."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.decision.shadow-decision.v1"

    artifact_kind: Literal[ArtifactKind.SHADOW_DECISION]
    artifact_namespace: Literal["growth-kernel.shadow.v1"]
    schema_major: SchemaVersion
    shadow_decision_id: NonEmptyStr
    counterfactual_key: CounterfactualDecisionKey
    portfolio_id: NonEmptyStr
    mode: ExecutionMode
    target_entry_session: date
    producer_namespace: NonEmptyStr
    family_id: NonEmptyStr
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    trial_id: NonEmptyStr
    policy_activation_hash: Sha256
    policy_epoch: PositiveExactInt
    evidence_set_merkle_root: Sha256
    shadow_stage_binding: ShadowStageBinding
    counterfactual_lines: Annotated[tuple[ShadowOrderLine, ...], Field(min_length=1)]
    cost_assumption_version: NonEmptyStr
    execution_assumption_version: NonEmptyStr
    created_at: UtcInstant
    available_at: UtcInstant
    execution_authority: Literal["NONE"]
    issuer_binding: ShadowIssuerBinding

    @model_validator(mode="after")
    def validate_shadow(self) -> Self:
        if self.counterfactual_key.portfolio_id != self.portfolio_id:
            raise ValueError("shadow counterfactual key portfolio mismatches header")
        if self.target_entry_session <= self.counterfactual_key.signal_session:
            raise ValueError("shadow target session must follow signal session")
        if self.available_at < self.created_at:
            raise ValueError("shadow available_at cannot precede created_at")
        line_ids = [line.shadow_line_id for line in self.counterfactual_lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("shadow line IDs must be unique")
        if line_ids != sorted(line_ids):
            raise ValueError("shadow lines must use canonical order")
        stage = self.shadow_stage_binding
        header = (
            self.producer_namespace,
            self.family_id,
            self.research_program_id,
            self.economic_lineage_id,
            self.stage_id,
            self.trial_id,
            self.cost_assumption_version,
            self.execution_assumption_version,
        )
        stage_identity = (
            stage.research_program_id,
            stage.economic_lineage_id,
            stage.stage_id,
            stage.trial_id,
            stage.stage_manifest_hash,
        )
        for line in self.counterfactual_lines:
            line_header = (
                line.producer_namespace,
                line.family_id,
                line.research_program_id,
                line.economic_lineage_id,
                line.stage_id,
                line.trial_id,
                line.cost_assumption_version,
                line.execution_assumption_version,
            )
            if line_header != header:
                raise ValueError("shadow line provenance must match shadow header")
            line_stage = (
                line.research_program_id,
                line.economic_lineage_id,
                line.stage_id,
                line.trial_id,
                line.stage_manifest_hash,
            )
            if line_stage != stage_identity:
                raise ValueError("shadow line stage manifest must match stage binding")
        _validate_issuer_binding(
            self.issuer_binding,
            artifact_kind=self.artifact_kind,
            artifact_namespace=self.artifact_namespace,
            mode=self.mode,
            schema_major=self.schema_major,
            portfolio_id=self.portfolio_id,
            issued_at=self.created_at,
        )
        return self

    def artifact_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, self.schema_major, self)


__all__ = [
    "AuthorizationIssuanceBinding",
    "ClockHealth",
    "CounterfactualDecisionKey",
    "DecisionLogicalKey",
    "GatewayIssuerBinding",
    "GatewayExpectedVersions",
    "PlanEvidence",
    "PortfolioDecisionSeal",
    "PortfolioDecision",
    "PortfolioOrderLine",
    "PriorSealEligibilityBinding",
    "SealReserveLineBinding",
    "ShadowDecision",
    "ShadowIssuerBinding",
    "ShadowOrderLine",
    "ShadowStageBinding",
    "StageAdmissionBinding",
    "StageLossExpectedVersion",
    "TrustedClockObservation",
    "TrustedExecutionWindow",
]
