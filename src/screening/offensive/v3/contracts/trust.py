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
    PORTFOLIO_DECISION_SEAL = "portfolio_decision_seal"
    DECISION_SEAL = "decision_seal"
    SHADOW_DECISION = "shadow_decision"
    EXECUTION_PERMIT = "execution_permit"
    ENTRY_CANCELLATION_RECEIPT = "entry_cancellation_receipt"


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
    """Minimal authority result safe for downstream trust decisions."""

    issuer_id: NonEmptyStr
    capability: Capability


__all__ = [
    "ArtifactKind",
    "Capability",
    "SignedEnvelope",
    "VerifiedIssuer",
]
