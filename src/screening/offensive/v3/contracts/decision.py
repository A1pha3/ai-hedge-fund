"""Storage-free Revision 2 portfolio proposal contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
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
from .capital import StageLossLatchState
from .evidence import EvidenceEnvelope, NonEmptyStr


PositiveExactInt = Annotated[ExactInteger, Field(ge=1)]
NonNegativeExactInt = Annotated[ExactInteger, Field(ge=0)]
PositiveQuantity = Annotated[QuantityUnits, Field(gt=0)]
PositiveCents = Annotated[MoneyCents, Field(gt=0)]
NonNegativeCents = Annotated[MoneyCents, Field(ge=0)]


class DecisionLogicalKey(CanonicalModel):
    """Economic idempotency key shared by every authority/policy epoch."""

    portfolio_id: NonEmptyStr
    signal_session: date
    decision_cycle_id: NonEmptyStr


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
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_cas_bundle(self) -> Self:
        seal_pair = (
            self.expected_active_seal_id,
            self.expected_active_seal_revision,
        )
        if (seal_pair[0] is None) != (seal_pair[1] is None):
            raise ValueError(
                "expected active seal ID/revision must be an all-or-none pair"
            )

        identities = [
            (
                item.research_program_id,
                item.economic_lineage_id,
                item.stage_id,
                item.stage_loss_budget_id,
            )
            for item in self.stage_loss_expected_versions
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("stage loss expected versions must be unique")
        if identities != sorted(identities):
            raise ValueError("stage loss expected versions must use canonical order")
        return self


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


__all__ = [
    "DecisionLogicalKey",
    "GatewayExpectedVersions",
    "PlanEvidence",
    "PortfolioDecision",
    "PortfolioOrderLine",
    "StageLossExpectedVersion",
]
