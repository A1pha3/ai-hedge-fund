"""Neutral immutable DTOs shared by trust verifiers and their callers."""

from __future__ import annotations

from base64 import b64decode, b64encode
import binascii
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from .base import (
    CanonicalModel,
    ExecutionMode,
    Sha256,
    UtcInstant,
    canonical_json_bytes,
)
from .evidence import NonEmptyStr


class ArtifactKind(StrEnum):
    """Existing v3 evidence, authorization, and decision discriminators."""

    SNAPSHOT = "snapshot"
    SIGNAL = "signal"
    OUTCOME = "outcome"
    PLAN = "plan"
    EDGE_AUTHORIZATION = "edge"
    EXPLORATION_AUTHORIZATION = "exploration"
    RECOVERY_AUTHORIZATION = "recovery"
    PORTFOLIO_DECISION_SEAL = "portfolio_decision_seal"
    DECISION_SEAL = "decision_seal"
    SHADOW_DECISION = "shadow_decision"
    EXECUTION_PERMIT = "execution_permit"
    ENTRY_CANCELLATION_RECEIPT = "entry_cancellation_receipt"
    POLICY_ACTIVATION = "policy_activation"
    RISK_EPOCH_STARTED = "risk_epoch_started"
    TRIAL_MANIFEST = "trial_manifest"
    STATISTICAL_ANALYSIS_PLAN = "statistical_analysis_plan"
    STAGE_MANIFEST = "stage_manifest"
    AUTHORIZATION_STATUS = "authorization_status"
    ENTRY_FENCE_RAISED = "entry_fence_raised"
    ENTRY_FENCE_ACKNOWLEDGEMENT = "entry_fence_acknowledgement"
    MIGRATION_APPROVAL_MANIFEST = "migration_approval_manifest"
    BROKER_ENABLEMENT_MANIFEST = "broker_enablement_manifest"
    DISASTER_RECOVERY_MANIFEST = "disaster_recovery_manifest"


class IssuerKind(StrEnum):
    """Service-principal role used for non-overridable separation."""

    MARKET_PUBLISHER = "market_publisher"
    SIGNAL_PRODUCER = "signal_producer"
    OUTCOME_FINALIZER = "outcome_finalizer"
    AUTHORIZER = "authorizer"
    GOVERNANCE = "governance"
    GROWTH_KERNEL = "growth_kernel"
    CAPITAL_GATEWAY = "capital_gateway"
    DEPENDENCY_TRACKER = "dependency_tracker"
    BROKER_GATEWAY = "broker_gateway"
    SHADOW = "shadow"
    MANUAL = "manual"


def _decode_canonical_base64(
    value: str,
    *,
    expected_length: int,
    label: str,
) -> bytes:
    try:
        decoded = b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{label} must be canonical base64") from exc
    if len(decoded) != expected_length:
        raise ValueError(f"{label} must decode to {expected_length} bytes")
    if b64encode(decoded).decode("ascii") != value:
        raise ValueError(f"{label} must be canonical base64")
    return decoded


def _validate_signature(value: str) -> str:
    _decode_canonical_base64(value, expected_length=64, label="signature")
    return value


Signature = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_validate_signature),
]


class Capability(CanonicalModel):
    """One time-bounded registry grant and caller-required trust context."""

    artifact: ArtifactKind
    namespace: NonEmptyStr
    mode: ExecutionMode
    schema_major: Annotated[int, Field(ge=1)]
    capability_version: NonEmptyStr
    scope: NonEmptyStr
    valid_from: UtcInstant
    valid_until: UtcInstant
    revoked_at: UtcInstant | None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("capability valid_until must be after valid_from")
        return self

    def context(self) -> tuple[ArtifactKind, str, ExecutionMode, int, str, str]:
        """Return fields that an endpoint, rather than an envelope, requires."""

        return (
            self.artifact,
            self.namespace,
            self.mode,
            self.schema_major,
            self.capability_version,
            self.scope,
        )


class SignedEnvelope(BaseModel):
    """Payload plus protected authority and capability audit claims."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )

    issuer_id: NonEmptyStr
    key_id: NonEmptyStr
    schema_major: Annotated[int, Field(ge=1)]
    artifact: ArtifactKind
    namespace: NonEmptyStr
    mode: ExecutionMode
    capability_version: NonEmptyStr
    capability_scope: NonEmptyStr
    payload_hash: Sha256
    payload: bytes
    signature: Signature

    def _protected_signing_input(self) -> bytes:
        return canonical_json_bytes(
            {
                "artifact": self.artifact,
                "capability_scope": self.capability_scope,
                "capability_version": self.capability_version,
                "issuer_id": self.issuer_id,
                "key_id": self.key_id,
                "mode": self.mode,
                "namespace": self.namespace,
                "payload": b64encode(self.payload).decode("ascii"),
                "payload_hash": self.payload_hash,
                "schema_major": self.schema_major,
            }
        )


class VerifiedIssuer(CanonicalModel):
    """Reverified issuer truth; this inspection result grants no authority alone."""

    issuer_id: NonEmptyStr
    key_id: NonEmptyStr
    issuer_kind: IssuerKind
    public_key_fingerprint: Sha256
    identity_fingerprint: Sha256
    capability: Capability
    trust_bundle_hash: Sha256
    registry_epoch: Annotated[int, Field(ge=1)]
    trusted_at: UtcInstant
    valid_from: UtcInstant
    valid_until: UtcInstant


class CurrentTrustHeadWitness(CanonicalModel):
    """Authority-Store observation of the exact active trust head.

    The witness is a typed input boundary, not a signature or standalone authority.
    Callers must obtain it from the future authoritative store for each verification.
    """

    active_trust_bundle_hash: Sha256
    registry_epoch: Annotated[int, Field(ge=1)]
    head_version: Annotated[int, Field(ge=1)]
    store_version: Annotated[int, Field(ge=1)]
    observed_at: UtcInstant


__all__ = [
    "ArtifactKind",
    "Capability",
    "CurrentTrustHeadWitness",
    "IssuerKind",
    "SignedEnvelope",
    "VerifiedIssuer",
]
