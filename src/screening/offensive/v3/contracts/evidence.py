"""Immutable evidence envelopes for the v3 growth kernel."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, ClassVar, Generic, Literal, Self, TypeVar

from pydantic import Field, StringConstraints, model_validator

from .base import (
    CanonicalModel,
    EvidenceScope,
    ExactInteger,
    ExecutionMode,
    Sha256,
    SignalStage,
    UtcInstant,
    domain_hash,
)


SUPPORTED_SCHEMA_MAJOR = 2
"""The only evidence schema major accepted by this implementation."""

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]
PositiveInt = Annotated[ExactInteger, Field(ge=1)]


class ProviderPublicationState(StrEnum):
    """Typed source states; neither state grants production PIT eligibility."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


ProviderPublishedAt = UtcInstant | ProviderPublicationState


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
    provider_published_at: ProviderPublishedAt
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
        if (
            isinstance(self.provider_published_at, datetime)
            and self.provider_published_at > self.available_at
        ):
            raise ValueError("provider_published_at must be at or before available_at")
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


EvidencePayload = SnapshotEvidence | SignalEvidence | OutcomeEvidence
EvidenceT = TypeVar("EvidenceT", bound=EvidenceEnvelope)


class EvidenceRecord(CanonicalModel, Generic[EvidenceT]):
    """Store-owned timeline projection; construction grants no edge/entry authority."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.evidence.store-record.v1"

    evidence: EvidenceT
    ingested_at: UtcInstant
    commit_sequence: PositiveInt
    revision: PositiveInt
    supersedes_revision: PositiveInt | None
    active_revision: PositiveInt

    @property
    def is_active(self) -> bool:
        """Whether this immutable historical record is the active projection."""

        return self.revision == self.active_revision

    def artifact_hash(self) -> str:
        """Hash the complete store record in its evidence-schema identity domain."""

        return domain_hash(self.HASH_DOMAIN, self.evidence.schema_major, self)

    def content_hash(self) -> str:
        """Prevent generic callers from dropping the store-record hash domain."""

        return self.artifact_hash()

    @model_validator(mode="after")
    def validate_store_timeline(self) -> Self:
        if (
            not self.evidence.observed_at
            <= self.ingested_at
            <= self.evidence.available_at
        ):
            raise ValueError("ingested_at must be between observed_at and available_at")
        if self.revision == 1:
            if self.supersedes_revision is not None:
                raise ValueError("first revision cannot supersede another revision")
        elif self.supersedes_revision != self.revision - 1:
            raise ValueError("supersedes_revision must identify the prior revision")
        if self.active_revision < self.revision:
            raise ValueError("active_revision cannot precede the stored revision")
        return self


__all__ = [
    "SUPPORTED_SCHEMA_MAJOR",
    "EvidenceEnvelope",
    "EvidenceRecord",
    "OutcomeEvidence",
    "ProviderPublicationState",
    "SignalEvidence",
    "SnapshotEvidence",
]
