"""Read-only public issuer registry and Ed25519 capability verification."""

from __future__ import annotations

from base64 import b64decode, b64encode
import binascii
from datetime import datetime
from enum import StrEnum
import hashlib
from pathlib import Path
from typing import Annotated, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from ..contracts.base import (
    CanonicalModel,
    ExecutionMode,
    Sha256,
    UtcInstant,
    UtcInstantAdapter,
    canonical_json_bytes,
)
from ..contracts.evidence import NonEmptyStr, SUPPORTED_SCHEMA_MAJOR


class TrustVerificationError(ValueError):
    """A signed envelope did not satisfy the complete trust boundary."""


class TrustedRegistryLoadError(ValueError):
    """A public trusted-issuer registry could not be loaded strictly."""


class ArtifactKind(StrEnum):
    """Existing v3 evidence, authorization, and decision discriminators."""

    SNAPSHOT = "snapshot"
    SIGNAL = "signal"
    OUTCOME = "outcome"
    PLAN = "plan"
    EDGE_AUTHORIZATION = "edge"
    EXPLORATION_AUTHORIZATION = "exploration"
    DECISION_SEAL = "decision_seal"
    SHADOW_DECISION = "shadow_decision"
    EXECUTION_PERMIT = "execution_permit"


class IssuerKind(StrEnum):
    """Service-principal role used to enforce non-overridable separation."""

    MARKET_PUBLISHER = "market_publisher"
    SIGNAL_PRODUCER = "signal_producer"
    OUTCOME_FINALIZER = "outcome_finalizer"
    AUTHORIZER = "authorizer"
    GOVERNANCE = "governance"
    GROWTH_KERNEL = "growth_kernel"
    BROKER_GATEWAY = "broker_gateway"
    SHADOW = "shadow"
    MANUAL = "manual"


def _decode_canonical_base64(value: str, *, expected_length: int, label: str) -> bytes:
    try:
        decoded = b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{label} must be canonical base64") from exc
    if len(decoded) != expected_length:
        raise ValueError(f"{label} must decode to {expected_length} bytes")
    if b64encode(decoded).decode("ascii") != value:
        raise ValueError(f"{label} must be canonical base64")
    return decoded


def _validate_public_key(value: str) -> str:
    _decode_canonical_base64(value, expected_length=32, label="public key")
    return value


def _validate_signature(value: str) -> str:
    _decode_canonical_base64(value, expected_length=64, label="signature")
    return value


PublicKey = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_validate_public_key),
]
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


class TrustedIssuer(CanonicalModel):
    """One immutable public key, its lifecycle, and explicit grants."""

    issuer_id: NonEmptyStr
    key_id: NonEmptyStr
    issuer_kind: IssuerKind
    public_key: PublicKey
    valid_from: UtcInstant
    valid_until: UtcInstant
    revoked_at: UtcInstant | None
    capabilities: tuple[Capability, ...]

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("key valid_until must be after valid_from")
        contexts = [capability.context() for capability in self.capabilities]
        if len(contexts) != len(set(contexts)):
            raise ValueError("duplicate capability grant")
        return self

    def require_capability(
        self,
        required: Capability,
        verification_time: datetime,
    ) -> Capability:
        """Resolve registry authority for caller-required context."""

        for capability in self.capabilities:
            if capability.context() == required.context():
                _require_active(
                    valid_from=capability.valid_from,
                    valid_until=capability.valid_until,
                    revoked_at=capability.revoked_at,
                    verification_time=verification_time,
                    label="capability",
                )
                return capability
        raise TrustVerificationError("capability is not granted by trusted registry")


class TrustedRegistry(CanonicalModel):
    """Frozen, read-only public issuer/key/capability truth."""

    issuers: tuple[TrustedIssuer, ...]

    @model_validator(mode="after")
    def unique_identities(self) -> Self:
        identities = [(issuer.issuer_id, issuer.key_id) for issuer in self.issuers]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate issuer/key identity")
        return self

    @classmethod
    def load(cls, path: str | Path) -> TrustedRegistry:
        """Load one strict local public registry file without network access."""

        try:
            return cls.model_validate_json(Path(path).read_bytes())
        except (OSError, ValidationError, ValueError) as exc:
            raise TrustedRegistryLoadError("invalid trusted issuer registry") from exc

    def require(self, issuer_id: str, key_id: str) -> TrustedIssuer:
        """Resolve one exact issuer/key pair without fallback or aliasing."""

        for issuer in self.issuers:
            if issuer.issuer_id == issuer_id and issuer.key_id == key_id:
                return issuer
        raise TrustVerificationError("unknown issuer or key")


class SignedEnvelope(BaseModel):
    """Payload plus protected authority and capability audit claims."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

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


_ROLE_ARTIFACTS: dict[IssuerKind, frozenset[ArtifactKind]] = {
    IssuerKind.MARKET_PUBLISHER: frozenset({ArtifactKind.SNAPSHOT}),
    IssuerKind.SIGNAL_PRODUCER: frozenset({ArtifactKind.SIGNAL, ArtifactKind.PLAN}),
    IssuerKind.OUTCOME_FINALIZER: frozenset({ArtifactKind.OUTCOME}),
    IssuerKind.AUTHORIZER: frozenset({ArtifactKind.EDGE_AUTHORIZATION}),
    IssuerKind.GOVERNANCE: frozenset({ArtifactKind.EXPLORATION_AUTHORIZATION}),
    IssuerKind.GROWTH_KERNEL: frozenset(
        {ArtifactKind.DECISION_SEAL, ArtifactKind.SHADOW_DECISION}
    ),
    IssuerKind.BROKER_GATEWAY: frozenset({ArtifactKind.EXECUTION_PERMIT}),
    IssuerKind.SHADOW: frozenset(
        {ArtifactKind.SIGNAL, ArtifactKind.PLAN, ArtifactKind.SHADOW_DECISION}
    ),
    IssuerKind.MANUAL: frozenset({ArtifactKind.OUTCOME}),
}


def _require_active(
    *,
    valid_from: datetime,
    valid_until: datetime,
    revoked_at: datetime | None,
    verification_time: datetime,
    label: str,
) -> None:
    if verification_time < valid_from:
        raise TrustVerificationError(f"{label} is not yet valid")
    if verification_time >= valid_until:
        raise TrustVerificationError(f"{label} is expired")
    if revoked_at is not None and verification_time >= revoked_at:
        raise TrustVerificationError(f"{label} is revoked")


def _require_role_boundary(issuer: TrustedIssuer, required: Capability) -> None:
    if (
        issuer.issuer_kind is IssuerKind.MANUAL
        and required.mode is ExecutionMode.BROKER_CONFIRMED
    ):
        raise TrustVerificationError("manual issuer cannot assert broker mode")
    if required.artifact not in _ROLE_ARTIFACTS[issuer.issuer_kind]:
        raise TrustVerificationError(
            f"{issuer.issuer_kind.value} issuer cannot sign {required.artifact.value}"
        )


class CapabilityVerifier:
    """Pure verifier over injected registry truth and verification time."""

    def __init__(self, registry: TrustedRegistry) -> None:
        if not isinstance(registry, TrustedRegistry):
            raise TypeError("registry must be a TrustedRegistry")
        self._registry = registry

    @property
    def registry(self) -> TrustedRegistry:
        return self._registry

    def verify(
        self,
        signed: SignedEnvelope,
        required: Capability,
        *,
        verification_time: datetime,
    ) -> VerifiedIssuer:
        """Fail closed unless identity, grant, context, hash, and signature agree."""

        if not isinstance(signed, SignedEnvelope):
            raise TypeError("signed must be a SignedEnvelope")
        if not isinstance(required, Capability):
            raise TypeError("required must be a Capability")
        try:
            checked_time = UtcInstantAdapter.validate_python(
                verification_time,
                strict=True,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise TrustVerificationError(
                "verification time must be strict UTC"
            ) from exc

        if (
            signed.schema_major != SUPPORTED_SCHEMA_MAJOR
            or required.schema_major != SUPPORTED_SCHEMA_MAJOR
        ):
            raise TrustVerificationError("unsupported schema major")

        claimed_context = (
            signed.artifact,
            signed.namespace,
            signed.mode,
            signed.schema_major,
            signed.capability_version,
            signed.capability_scope,
        )
        if claimed_context != required.context():
            raise TrustVerificationError(
                "envelope does not match caller-required capability context"
            )

        issuer = self.registry.require(signed.issuer_id, signed.key_id)
        _require_active(
            valid_from=issuer.valid_from,
            valid_until=issuer.valid_until,
            revoked_at=issuer.revoked_at,
            verification_time=checked_time,
            label="key",
        )
        _require_role_boundary(issuer, required)
        granted = issuer.require_capability(required, checked_time)

        actual_hash = hashlib.sha256(signed.payload).hexdigest()
        if actual_hash != signed.payload_hash:
            raise TrustVerificationError("payload hash mismatch")

        public_bytes = _decode_canonical_base64(
            issuer.public_key,
            expected_length=32,
            label="public key",
        )
        signature_bytes = _decode_canonical_base64(
            signed.signature,
            expected_length=64,
            label="signature",
        )
        try:
            Ed25519PublicKey.from_public_bytes(public_bytes).verify(
                signature_bytes,
                signed._protected_signing_input(),
            )
        except (InvalidSignature, ValueError) as exc:
            raise TrustVerificationError("invalid Ed25519 signature") from exc

        return VerifiedIssuer(issuer_id=issuer.issuer_id, capability=granted)


__all__ = [
    "ArtifactKind",
    "Capability",
    "CapabilityVerifier",
    "IssuerKind",
    "SignedEnvelope",
    "TrustedIssuer",
    "TrustedRegistry",
    "TrustedRegistryLoadError",
    "TrustVerificationError",
    "VerifiedIssuer",
]
