"""Read-only compatibility contracts for historical shadow decisions.

The current ``ShadowDecision`` is schema major 3 with a discriminated
``ShadowPolicyBinding``. Historical schema-major-2 artifacts (namespace
``growth-kernel.shadow.v1``, field ``policy_activation_hash``) remain
audit-readable through these frozen legacy shapes. There is deliberately no
upgrader: nothing rewrites old bytes into the new schema, and the official
paired-trial runner rejects legacy shadow artifacts.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from src.screening.offensive.v3.contracts.base import (
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
from src.screening.offensive.v3.contracts.decision import (
    CounterfactualDecisionKey,
    ShadowIssuerBinding,
    ShadowStageBinding,
    _validate_issuer_binding,
)
from src.screening.offensive.v3.contracts.trust import ArtifactKind

PositiveQuantity = Annotated[QuantityUnits, Field(gt=0)]
PositiveCents = Annotated[MoneyCents, Field(gt=0)]
NonNegativeCents = Annotated[MoneyCents, Field(ge=0)]


class ShadowCompatibilityError(ValueError):
    """A historical shadow artifact cannot be used officially."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


class LegacyShadowOrderLine(CanonicalModel):
    """The schema-major-2 shadow line shape, frozen verbatim for audit."""

    shadow_line_id: str
    security_id: str
    producer_namespace: str
    family_id: str
    economic_lineage_id: str
    research_program_id: str
    stage_id: str
    trial_id: str
    stage_manifest_hash: Sha256
    evidence_id: str
    evidence_artifact_hash: Sha256
    evidence_payload_hash: Sha256
    target_quantity_units: PositiveQuantity
    lot_size_units: PositiveQuantity
    lot_rule_version: str
    order_type: str
    limit_price_cents: PositiveCents
    worst_case_price_cents: PositiveCents
    price_boundary_version: str
    time_in_force: str
    exit_session_ordinal: Literal[10]
    estimated_fee_cents: NonNegativeCents
    estimated_cash_reserve_cents: PositiveCents
    cost_assumption_version: str
    execution_assumption_version: str

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
        required = self.worst_case_price_cents * self.target_quantity_units + self.estimated_fee_cents
        if self.estimated_cash_reserve_cents != required:
            raise ValueError("shadow estimated reserve must equal line economics")
        return self


class LegacyShadowDecisionV2(CanonicalModel):
    """The schema-major-2 shadow decision shape, frozen verbatim for audit."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.decision.shadow-decision.v1"

    artifact_kind: Literal[ArtifactKind.SHADOW_DECISION]
    artifact_namespace: Literal["growth-kernel.shadow.v1"]
    schema_major: SchemaVersion
    shadow_decision_id: str
    counterfactual_key: CounterfactualDecisionKey
    portfolio_id: str
    mode: ExecutionMode
    target_entry_session: date
    producer_namespace: str
    family_id: str
    research_program_id: str
    economic_lineage_id: str
    stage_id: str
    trial_id: str
    policy_activation_hash: Sha256
    policy_epoch: int
    evidence_set_merkle_root: Sha256
    shadow_stage_binding: ShadowStageBinding
    counterfactual_lines: Annotated[tuple[LegacyShadowOrderLine, ...], Field(min_length=1)]
    cost_assumption_version: str
    execution_assumption_version: str
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


def read_shadow_decision_json(payload: bytes, *, official_trial: bool) -> LegacyShadowDecisionV2:
    """Decode one historical schema-major-2 shadow decision, read-only.

    The official paired trial never accepts legacy shadow artifacts; when
    ``official_trial`` is true the read fails closed even though the bytes are
    valid history. There is no upgrader and no implicit default upgrade.
    """

    if official_trial:
        raise ShadowCompatibilityError(
            "legacy_shadow_not_official",
            "schema-major-2 shadow decisions are audit history, never official" " trial inputs",
        )
    return LegacyShadowDecisionV2.model_validate_json(payload, strict=True)


__all__ = [
    "LegacyShadowDecisionV2",
    "LegacyShadowOrderLine",
    "ShadowCompatibilityError",
    "read_shadow_decision_json",
]
