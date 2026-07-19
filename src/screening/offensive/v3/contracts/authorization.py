"""Immutable capital authorization contracts; no issuer or trust behavior."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, RootModel, model_validator

from .base import EvidenceScope, ExecutionMode, Sha256, UtcInstant
from .evidence import EvidenceEnvelope, NonEmptyStr


AllowedCapitalTier = Literal[2, 5, 10]


class EdgeAuthorization(EvidenceEnvelope):
    """Independent authorization of a complete baseline-to-target policy change."""

    authorization_kind: Literal["edge"]
    authorization_version: Annotated[int, Field(ge=1)]
    economic_lineage_id: NonEmptyStr
    research_program_id: NonEmptyStr
    baseline_portfolio_policy_fingerprint: Sha256
    target_portfolio_policy_fingerprint: Sha256
    evidence_as_of: UtcInstant
    evidence_set_merkle_root: Sha256
    issued_at: UtcInstant
    expires_at: UtcInstant
    max_capital_tier: AllowedCapitalTier
    issuer_id: NonEmptyStr
    issuer_capability: NonEmptyStr
    trial_id: NonEmptyStr
    trial_manifest_hash: Sha256
    statistical_analysis_plan_hash: Sha256
    assessment_result_hash: Sha256
    attempt_ledger_checkpoint_hash: Sha256
    alpha_sample_consumption_id: NonEmptyStr
    authorization_payload_hash: Sha256

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError("research reconstruction cannot receive capital authorization")
        if self.evidence_as_of > self.issued_at:
            raise ValueError("evidence_as_of must be at or before issued_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if self.subject_scope is not EvidenceScope.STRATEGY_LINEAGE:
            raise ValueError("edge authorization requires strategy-lineage scope")
        return self


class ExplorationAuthorization(EvidenceEnvelope):
    """One-shot broker-confirmed 2% evidence-collection authorization."""

    authorization_kind: Literal["exploration"]
    authorization_version: Annotated[int, Field(ge=1)]
    economic_lineage_id: NonEmptyStr
    research_program_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    evidence_set_merkle_root: Sha256
    issued_at: UtcInstant
    expires_at: UtcInstant
    max_capital_tier: Literal[2]
    portfolio_gross_risk_cap: Annotated[Decimal, Field(gt=0, le=Decimal("0.02"))]
    stress_loss_budget: Annotated[Decimal, Field(gt=0)]
    issuer_id: NonEmptyStr
    issuer_capability: NonEmptyStr
    trial_id: NonEmptyStr
    trial_manifest_hash: Sha256
    one_shot: Literal[True]

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        if self.mode is not ExecutionMode.BROKER_CONFIRMED:
            raise ValueError("exploration authorization requires broker-confirmed mode")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if self.subject_scope is not EvidenceScope.STRATEGY_LINEAGE:
            raise ValueError("exploration authorization requires strategy-lineage scope")
        return self


AuthorizationUnion = Annotated[
    EdgeAuthorization | ExplorationAuthorization,
    Field(discriminator="authorization_kind"),
]


class CapitalAuthorization(RootModel[AuthorizationUnion]):
    """Discriminated union accepted by the decision/gateway boundary."""

    model_config = ConfigDict(strict=True, frozen=True)


__all__ = [
    "AllowedCapitalTier",
    "AuthorizationUnion",
    "CapitalAuthorization",
    "EdgeAuthorization",
    "ExplorationAuthorization",
]
