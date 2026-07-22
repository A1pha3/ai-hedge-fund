"""Read-only public issuer registry and Ed25519 capability verification."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager, ExitStack
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Annotated, Any, Self, TypeVar

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import (
    AfterValidator,
    BaseModel,
    StringConstraints,
    ValidationError,
    model_validator,
)

from ..contracts.base import (
    CanonicalModel,
    ExecutionMode,
    UtcInstant,
    UtcInstantAdapter,
)
from ..contracts.evidence import NonEmptyStr, SUPPORTED_SCHEMA_MAJOR
from ..contracts.trust import (
    ArtifactKind,
    Capability,
    SignedEnvelope,
    VerifiedIssuer,
    _decode_canonical_base64,
)


class TrustVerificationError(ValueError):
    """A signed envelope did not satisfy the complete trust boundary."""


class TrustedRegistryLoadError(ValueError):
    """A public trusted-issuer registry could not be loaded strictly."""


MAX_TRUSTED_REGISTRY_FILE_BYTES = 1024 * 1024


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrustedRegistryLoadError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _required_descriptor_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or value == 0:
        raise TrustedRegistryLoadError(
            f"required descriptor safety flag is unavailable: {name}"
        )
    return value


@contextmanager
def _owned_descriptor(descriptor: int) -> Iterator[int]:
    """Close one descriptor without replacing an error already in flight."""

    try:
        yield descriptor
    except BaseException as primary_error:
        try:
            os.close(descriptor)
        except OSError as close_error:
            primary_error.add_note(
                f"also failed to close trusted registry descriptor: {close_error}"
            )
        raise
    else:
        try:
            os.close(descriptor)
        except OSError as exc:
            raise TrustedRegistryLoadError(
                "unable to close trusted registry descriptor"
            ) from exc


def _read_regular_registry_file(path: str | os.PathLike[str]) -> bytes:
    try:
        parsed_path = Path(os.fspath(path))
    except (OSError, TypeError, ValueError) as exc:
        raise TrustedRegistryLoadError(
            "trusted registry path must name one non-symlink regular file"
        ) from exc

    path_parts = parsed_path.parts
    if parsed_path.is_absolute():
        directory_path = path_parts[0]
        components = path_parts[1:]
    else:
        directory_path = "."
        components = path_parts
    if not components:
        raise TrustedRegistryLoadError(
            "trusted registry path must name one non-symlink regular file"
        )

    nofollow = _required_descriptor_flag("O_NOFOLLOW")
    directory = _required_descriptor_flag("O_DIRECTORY")
    cloexec = _required_descriptor_flag("O_CLOEXEC")
    nonblock = _required_descriptor_flag("O_NONBLOCK")
    directory_flags = os.O_RDONLY | cloexec | directory | nofollow
    file_flags = os.O_RDONLY | cloexec | nofollow | nonblock
    try:
        directory_descriptor = os.open(directory_path, directory_flags)
    except (OSError, TypeError, ValueError) as exc:
        raise TrustedRegistryLoadError(
            "trusted registry path must name one non-symlink regular file"
        ) from exc

    with ExitStack() as descriptors:
        directory_descriptor = descriptors.enter_context(
            _owned_descriptor(directory_descriptor)
        )
        try:
            for component in components[:-1]:
                next_descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=directory_descriptor,
                )
                next_descriptor = descriptors.enter_context(
                    _owned_descriptor(next_descriptor)
                )
                if not stat.S_ISDIR(os.fstat(next_descriptor).st_mode):
                    raise TrustedRegistryLoadError(
                        "trusted registry parent must be a non-symlink directory"
                    )
                directory_descriptor = next_descriptor
            descriptor = os.open(
                components[-1],
                file_flags,
                dir_fd=directory_descriptor,
            )
            descriptor = descriptors.enter_context(_owned_descriptor(descriptor))
        except TrustedRegistryLoadError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise TrustedRegistryLoadError(
                "trusted registry path must contain no symlinks"
            ) from exc

        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise TrustedRegistryLoadError(
                    "trusted registry path must name one regular file"
                )
            if before.st_size > MAX_TRUSTED_REGISTRY_FILE_BYTES:
                raise TrustedRegistryLoadError("trusted registry file is too large")

            chunks: list[bytes] = []
            bytes_read = 0
            while chunk := os.read(descriptor, 64 * 1024):
                chunks.append(chunk)
                bytes_read += len(chunk)
                if bytes_read > MAX_TRUSTED_REGISTRY_FILE_BYTES:
                    raise TrustedRegistryLoadError(
                        "trusted registry file is too large"
                    )
            payload = b"".join(chunks)
            after = os.fstat(descriptor)
            unchanged_fields = (
                "st_dev",
                "st_ino",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
            if (
                any(
                    getattr(before, field) != getattr(after, field)
                    for field in unchanged_fields
                )
                or len(payload) != before.st_size
            ):
                raise TrustedRegistryLoadError(
                    "trusted registry file changed while it was being read"
                )
            return payload
        except OSError as exc:
            raise TrustedRegistryLoadError(
                "unable to read trusted registry regular file"
            ) from exc


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


def _validate_public_key(value: str) -> str:
    _decode_canonical_base64(value, expected_length=32, label="public key")
    return value


PublicKey = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_validate_public_key),
]
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
        issuer_kinds: dict[str, IssuerKind] = {}
        for issuer in self.issuers:
            existing_kind = issuer_kinds.setdefault(
                issuer.issuer_id,
                issuer.issuer_kind,
            )
            if existing_kind is not issuer.issuer_kind:
                raise ValueError("issuer_id cannot change issuer_kind across keys")
        return self

    @classmethod
    def load(cls, path: str | Path) -> TrustedRegistry:
        """Load one strict local public registry file without network access."""

        payload = _read_regular_registry_file(path)
        try:
            json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
        except TrustedRegistryLoadError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise TrustedRegistryLoadError(
                "trusted registry file must contain one valid JSON value"
            ) from exc

        try:
            return cls.model_validate_json(payload)
        except (ValidationError, ValueError) as exc:
            raise TrustedRegistryLoadError(
                f"invalid trusted issuer registry: {exc}"
            ) from exc

    def require(self, issuer_id: str, key_id: str) -> TrustedIssuer:
        """Resolve one exact issuer/key pair without fallback or aliasing."""

        for issuer in self.issuers:
            if issuer.issuer_id == issuer_id and issuer.key_id == key_id:
                return issuer
        raise TrustVerificationError("unknown issuer or key")


StrictModel = TypeVar("StrictModel", bound=BaseModel)


def _strict_revalidate_model(
    value: StrictModel,
    model_type: type[StrictModel],
    *,
    label: str,
) -> StrictModel:
    """Rebuild an instance so unchecked Pydantic construction cannot cross trust."""

    try:
        raw = value.model_dump(
            mode="python",
            round_trip=True,
            warnings="none",
        )
        return model_type.model_validate(raw, strict=True)
    except (AttributeError, TypeError, ValueError) as exc:
        raise TrustVerificationError(f"invalid {label}") from exc


_ROLE_ARTIFACTS: dict[IssuerKind, frozenset[ArtifactKind]] = {
    IssuerKind.MARKET_PUBLISHER: frozenset({ArtifactKind.SNAPSHOT}),
    IssuerKind.SIGNAL_PRODUCER: frozenset({ArtifactKind.SIGNAL, ArtifactKind.PLAN}),
    IssuerKind.OUTCOME_FINALIZER: frozenset({ArtifactKind.OUTCOME}),
    IssuerKind.AUTHORIZER: frozenset({ArtifactKind.EDGE_AUTHORIZATION}),
    IssuerKind.GOVERNANCE: frozenset({ArtifactKind.EXPLORATION_AUTHORIZATION}),
    IssuerKind.GROWTH_KERNEL: frozenset({ArtifactKind.DECISION_SEAL}),
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
        and required.mode is not ExecutionMode.MANUAL_CONFIRMED
    ):
        raise TrustVerificationError(
            "manual issuer can only assert manual-confirmed outcomes"
        )
    if required.artifact not in _ROLE_ARTIFACTS[issuer.issuer_kind]:
        raise TrustVerificationError(
            f"{issuer.issuer_kind.value} issuer cannot sign {required.artifact.value}"
        )


class CapabilityVerifier:
    """Pure verifier over injected registry truth and verification time."""

    def __init__(self, registry: TrustedRegistry) -> None:
        if not isinstance(registry, TrustedRegistry):
            raise TypeError("registry must be a TrustedRegistry")
        self._registry = _strict_revalidate_model(
            registry,
            TrustedRegistry,
            label="trusted registry",
        )

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
        signed = _strict_revalidate_model(
            signed,
            SignedEnvelope,
            label="signed envelope",
        )
        required = _strict_revalidate_model(
            required,
            Capability,
            label="required capability",
        )
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
