"""Immutable evidence envelopes for the v3 growth kernel."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from .base import (
    CanonicalModel,
    EvidenceScope,
    ExecutionMode,
    Sha256,
    SignalStage,
    UtcInstant,
)


SUPPORTED_SCHEMA_MAJOR = 1
"""The only evidence schema major accepted by this implementation."""

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]


class EvidenceEnvelope(CanonicalModel):
    """Common bitemporal and provenance binding for all evidence contracts."""

    evidence_id: NonEmptyStr
    subject_scope: EvidenceScope
    subject_producer: NonEmptyStr
    family_id: NonEmptyStr | None
    strategy_semver: NonEmptyStr
    behavior_fingerprint: Sha256
    policy_epoch: Annotated[int, Field(ge=1)]
    execution_version: NonEmptyStr
    cost_version: NonEmptyStr
    effective_at: UtcInstant
    observed_at: UtcInstant
    available_at: UtcInstant
    mode: ExecutionMode
    source_authority: NonEmptyStr
    payload_content_hash: Sha256
    schema_major: int

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.schema_major != SUPPORTED_SCHEMA_MAJOR:
            raise ValueError(
                f"unsupported schema major: {self.schema_major}; "
                f"expected {SUPPORTED_SCHEMA_MAJOR}"
            )
        if self.observed_at > self.available_at:
            raise ValueError("observed_at must be at or before available_at")
        if self.subject_scope is EvidenceScope.GLOBAL and self.family_id is not None:
            raise ValueError("GLOBAL evidence requires family_id=None")
        if (
            self.subject_scope is EvidenceScope.STRATEGY_LINEAGE
            and self.family_id is None
        ):
            raise ValueError("STRATEGY_LINEAGE evidence requires a nonempty family_id")
        return self


class SnapshotEvidence(EvidenceEnvelope):
    """PIT market/data-health evidence; never an execution authorization."""

    evidence_kind: Literal["snapshot"]


class SignalEvidence(EvidenceEnvelope):
    """One immutable observation of a producer candidate-funnel stage."""

    evidence_kind: Literal["signal"]
    stage: SignalStage


class OutcomeEvidence(EvidenceEnvelope):
    """A matured outcome under one fixed execution mode and behavior version."""

    evidence_kind: Literal["outcome"]


__all__ = [
    "SUPPORTED_SCHEMA_MAJOR",
    "EvidenceEnvelope",
    "OutcomeEvidence",
    "SignalEvidence",
    "SnapshotEvidence",
]
