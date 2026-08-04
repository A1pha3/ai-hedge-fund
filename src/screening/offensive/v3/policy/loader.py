"""Secure, environment-independent loading for one v3 policy JSON file."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager, ExitStack
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterator

from pydantic import ValidationError

from ..contracts.base import ExecutionMode
from ..contracts.governance import PolicyActivation
from ..contracts.trust import (
    ArtifactKind,
    Capability,
    CurrentTrustHeadWitness,
    SignedEnvelope,
)
from ..trust.registry import (
    CapabilityVerifier,
    TrustVerificationError,
)
from .models import (
    ActivePolicyActivationWitness,
    PolicySnapshot,
    VerifiedPolicyActivation,
)

MAX_POLICY_FILE_BYTES = 1024 * 1024


class PolicyLoadError(ValueError):
    """The supplied policy file is not a secure, supported policy snapshot."""


class PolicyActivationVerificationError(ValueError):
    """A signed policy activation candidate failed closed."""


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyLoadError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _required_descriptor_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or value == 0:
        raise PolicyLoadError(f"required descriptor safety flag is unavailable: {name}")
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
                f"also failed to close policy descriptor: {close_error}"
            )
        raise
    else:
        try:
            os.close(descriptor)
        except OSError as exc:
            raise PolicyLoadError("unable to close policy descriptor") from exc


def _read_regular_file(path: str | os.PathLike[str]) -> bytes:
    try:
        parsed_path = Path(os.fspath(path))
    except (OSError, TypeError, ValueError) as exc:
        raise PolicyLoadError(
            "policy path must name one non-symlink regular file"
        ) from exc

    path_parts = parsed_path.parts
    if parsed_path.is_absolute():
        directory_path = path_parts[0]
        components = path_parts[1:]
    else:
        directory_path = "."
        components = path_parts
    if not components:
        raise PolicyLoadError("policy path must name one non-symlink regular file")

    nofollow = _required_descriptor_flag("O_NOFOLLOW")
    directory = _required_descriptor_flag("O_DIRECTORY")
    cloexec = _required_descriptor_flag("O_CLOEXEC")
    nonblock = _required_descriptor_flag("O_NONBLOCK")
    directory_flags = os.O_RDONLY | cloexec | directory | nofollow
    file_flags = os.O_RDONLY | cloexec | nofollow | nonblock
    try:
        directory_descriptor = os.open(directory_path, directory_flags)
    except (OSError, TypeError, ValueError) as exc:
        raise PolicyLoadError(
            "policy path must name one non-symlink regular file"
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
                    raise PolicyLoadError(
                        "policy parent must be a non-symlink directory"
                    )
                directory_descriptor = next_descriptor
            descriptor = os.open(
                components[-1],
                file_flags,
                dir_fd=directory_descriptor,
            )
            descriptor = descriptors.enter_context(_owned_descriptor(descriptor))
        except PolicyLoadError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise PolicyLoadError("policy path must contain no symlinks") from exc

        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise PolicyLoadError("policy path must name one regular file")
            if before.st_size > MAX_POLICY_FILE_BYTES:
                raise PolicyLoadError("policy file is too large")
            chunks: list[bytes] = []
            bytes_read = 0
            while chunk := os.read(descriptor, 64 * 1024):
                chunks.append(chunk)
                bytes_read += len(chunk)
                if bytes_read > MAX_POLICY_FILE_BYTES:
                    raise PolicyLoadError("policy file is too large")
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
                raise PolicyLoadError("policy file changed while it was being read")
            return payload
        except OSError as exc:
            raise PolicyLoadError("unable to read policy regular file") from exc


def load_policy_snapshot(path: str | os.PathLike[str] | Path) -> PolicySnapshot:
    """Load one regular-file candidate; loading never activates policy authority."""

    payload = _read_regular_file(path)
    try:
        json.loads(
            payload,
            parse_float=Decimal,
            parse_int=int,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except PolicyLoadError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PolicyLoadError("policy file must contain one valid JSON value") from exc

    try:
        return PolicySnapshot.model_validate_json(payload, strict=True)
    except ValidationError as exc:
        raise PolicyLoadError(f"invalid policy snapshot: {exc}") from exc


def verify_policy_activation(
    signed: SignedEnvelope,
    policy_snapshot: PolicySnapshot,
    verifier: CapabilityVerifier,
    required: Capability,
    *,
    current_trust_head: CurrentTrustHeadWitness,
    trusted_at: datetime,
    predecessor: ActivePolicyActivationWitness | None,
    expected_portfolio_id: str,
    expected_broker_account_id: str | None,
    expected_broker_account_fingerprint: str | None,
    expected_mode: ExecutionMode,
) -> VerifiedPolicyActivation:
    """Verify one signed candidate without mutating any active policy state."""

    if type(verifier) is not CapabilityVerifier:
        raise TypeError("verifier must be a TrustBundle-bound CapabilityVerifier")
    try:
        checked_policy = PolicySnapshot.model_validate(
            policy_snapshot.model_dump(mode="python", round_trip=True),
            strict=True,
        )
        if predecessor is not None:
            if not isinstance(predecessor, ActivePolicyActivationWitness):
                raise PolicyActivationVerificationError(
                    "predecessor must be an active Authority Store witness"
                )
            predecessor = ActivePolicyActivationWitness.model_validate(
                predecessor.model_dump(mode="python", round_trip=True),
                strict=True,
            )
            if predecessor.effective_from > predecessor.observed_at:
                raise PolicyActivationVerificationError(
                    "predecessor effective_from must be at or before observed_at"
                )
        if required.artifact is not ArtifactKind.POLICY_ACTIVATION:
            raise PolicyActivationVerificationError(
                "required capability must be POLICY_ACTIVATION"
            )
        verified_issuer = CapabilityVerifier.verify(
            verifier,
            signed,
            required,
            current_head=current_trust_head,
            trusted_at=trusted_at,
        )
        expected_capability_context = (
            ArtifactKind.POLICY_ACTIVATION,
            "governance.policy.activation",
            expected_mode,
            2,
            "governance.policy.activation.v1",
            f"portfolio:{expected_portfolio_id}",
        )
        if verified_issuer.capability.context() != expected_capability_context:
            raise PolicyActivationVerificationError(
                "policy activation capability scope or context mismatch"
            )
        try:
            json.loads(
                signed.payload,
                object_pairs_hook=_reject_duplicate_keys,
            )
        except PolicyLoadError as exc:
            raise PolicyActivationVerificationError(str(exc)) from exc
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise PolicyActivationVerificationError(
                "policy activation payload must be valid JSON"
            ) from exc
        try:
            activation = PolicyActivation.model_validate_json(
                signed.payload,
                strict=True,
            )
        except ValidationError as exc:
            raise PolicyActivationVerificationError(
                f"invalid policy activation payload: {exc}"
            ) from exc
        if activation.canonical_bytes() != signed.payload:
            raise PolicyActivationVerificationError(
                "policy activation payload must use canonical JSON"
            )
        mismatches = {
            "portfolio": activation.portfolio_id != expected_portfolio_id,
            "account": (
                activation.broker_account_id != expected_broker_account_id
                or activation.broker_account_fingerprint
                != expected_broker_account_fingerprint
            ),
            "mode": activation.mode is not expected_mode,
            "policy_snapshot_hash": (
                activation.policy_snapshot_hash != checked_policy.policy_fingerprint
            ),
            "policy_epoch": activation.policy_epoch != checked_policy.policy_epoch,
            "authority_epoch": (
                activation.authority_epoch != checked_policy.authority_epoch
            ),
            "risk_epoch": activation.risk_epoch != checked_policy.risk_epoch,
            "trust_bundle_hash": (
                activation.trust_bundle_hash != verified_issuer.trust_bundle_hash
            ),
            "registry_epoch": (
                activation.registry_epoch != verified_issuer.registry_epoch
            ),
            "issuer": activation.issuer_id != verified_issuer.issuer_id,
            "issuer_capability": (
                activation.issuer_capability != required.capability_version
            ),
        }
        for label, mismatch in mismatches.items():
            if mismatch:
                raise PolicyActivationVerificationError(f"{label} mismatch")
        if activation.effective_from < verified_issuer.valid_from:
            raise PolicyActivationVerificationError(
                "policy effective_from cannot predate issuer authority valid_from"
            )
        if activation.expires_at <= verified_issuer.trusted_at:
            raise PolicyActivationVerificationError(
                "policy activation candidate is already expired at trusted_at"
            )
        if predecessor is None:
            if activation.predecessor_policy_activation_hash != "0" * 64:
                raise PolicyActivationVerificationError(
                    "genesis policy predecessor mismatch"
                )
            if (
                activation.policy_epoch != 1
                or activation.authority_epoch != 1
                or activation.risk_epoch != 1
            ):
                raise PolicyActivationVerificationError(
                    "genesis policy, authority, and risk epochs must all start at one"
                )
        else:
            if predecessor.observed_at > verified_issuer.trusted_at:
                raise PolicyActivationVerificationError(
                    "policy predecessor observed_at cannot follow trusted_at"
                )
            if (
                activation.predecessor_policy_activation_hash
                != predecessor.active_policy_activation_hash
            ):
                raise PolicyActivationVerificationError("policy predecessor mismatch")
            if activation.policy_epoch != predecessor.policy_epoch + 1:
                raise PolicyActivationVerificationError(
                    "policy_epoch must advance by exactly one"
                )
            if (
                activation.authority_epoch < predecessor.authority_epoch
                or activation.risk_epoch < predecessor.risk_epoch
            ):
                raise PolicyActivationVerificationError(
                    "authority/risk epoch rollback is forbidden"
                )
            if activation.registry_epoch < predecessor.registry_epoch:
                raise PolicyActivationVerificationError(
                    "registry epoch rollback is forbidden"
                )
            if (
                activation.registry_epoch == predecessor.registry_epoch
                and activation.trust_bundle_hash != predecessor.trust_bundle_hash
            ):
                raise PolicyActivationVerificationError(
                    "same-epoch trust bundle fork is forbidden"
                )
            if activation.effective_from < predecessor.effective_from:
                raise PolicyActivationVerificationError(
                    "policy effective_from time rollback is forbidden"
                )
            if (
                activation.portfolio_id != predecessor.portfolio_id
                or activation.broker_account_id != predecessor.broker_account_id
                or activation.broker_account_fingerprint
                != predecessor.broker_account_fingerprint
                or activation.mode is not predecessor.mode
            ):
                raise PolicyActivationVerificationError(
                    "policy predecessor account or mode mismatch"
                )
        return VerifiedPolicyActivation(
            activation=activation,
            policy_snapshot=checked_policy,
            verified_issuer=verified_issuer,
            trust_bundle_hash=verified_issuer.trust_bundle_hash,
            registry_epoch=verified_issuer.registry_epoch,
            trusted_at=verified_issuer.trusted_at,
        )
    except PolicyActivationVerificationError:
        raise
    except (AttributeError, TypeError, ValueError, TrustVerificationError) as exc:
        raise PolicyActivationVerificationError(
            f"policy activation verification failed: {exc}"
        ) from exc


__all__ = [
    "MAX_POLICY_FILE_BYTES",
    "PolicyActivationVerificationError",
    "PolicyLoadError",
    "load_policy_snapshot",
    "verify_policy_activation",
]
