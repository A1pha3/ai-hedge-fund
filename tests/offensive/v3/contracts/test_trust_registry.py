"""Adversarial tests for the read-only v3 issuer trust boundary."""

from __future__ import annotations

from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from pydantic import ValidationError


UTC = timezone.utc
NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
PAYLOAD = b'{"authorization_kind":"edge","authorization_id":"auth-1"}'


def _api() -> Any:
    try:
        from src.screening.offensive.v3 import trust
    except ImportError as exc:
        pytest.fail(f"v3 trust registry is not implemented: {exc}", pytrace=False)
    return trust


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return b64encode(public_bytes).decode("ascii")


def _capability(api: Any, **overrides: Any) -> Any:
    values = {
        "artifact": api.ArtifactKind.EDGE_AUTHORIZATION,
        "namespace": "capital.edge.btst",
        "mode": api.ExecutionMode.DAILY_BAR_PROXY,
        "schema_major": api.SUPPORTED_SCHEMA_MAJOR,
        "capability_version": "edge-authorizer.v1",
        "scope": "portfolio:paper-v3/lineage:btst",
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "revoked_at": None,
    }
    values.update(overrides)
    return api.Capability(**values)


def _issuer(
    api: Any,
    private_key: Ed25519PrivateKey,
    capability: Any,
    **overrides: Any,
) -> Any:
    values = {
        "issuer_id": "authorizer.service",
        "key_id": "authorizer-key-2026-07",
        "issuer_kind": api.IssuerKind.AUTHORIZER,
        "public_key": _public_key_b64(private_key),
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "revoked_at": None,
        "capabilities": (capability,),
    }
    values.update(overrides)
    return api.TrustedIssuer(**values)


def _protected_input(
    api: Any,
    *,
    issuer_id: str,
    key_id: str,
    capability: Any,
    payload: bytes,
    payload_hash: str,
) -> bytes:
    return api.canonical_json_bytes(
        {
            "artifact": capability.artifact,
            "capability_scope": capability.scope,
            "capability_version": capability.capability_version,
            "issuer_id": issuer_id,
            "key_id": key_id,
            "mode": capability.mode,
            "namespace": capability.namespace,
            "payload": b64encode(payload).decode("ascii"),
            "payload_hash": payload_hash,
            "schema_major": capability.schema_major,
        }
    )


def _signed(
    api: Any,
    private_key: Ed25519PrivateKey,
    capability: Any,
    *,
    issuer_id: str = "authorizer.service",
    key_id: str = "authorizer-key-2026-07",
    payload: bytes = PAYLOAD,
    payload_hash: str | None = None,
) -> Any:
    digest = payload_hash or hashlib.sha256(payload).hexdigest()
    protected = _protected_input(
        api,
        issuer_id=issuer_id,
        key_id=key_id,
        capability=capability,
        payload=payload,
        payload_hash=digest,
    )
    signature = private_key.sign(protected)
    return api.SignedEnvelope(
        issuer_id=issuer_id,
        key_id=key_id,
        schema_major=capability.schema_major,
        artifact=capability.artifact,
        namespace=capability.namespace,
        mode=capability.mode,
        capability_version=capability.capability_version,
        capability_scope=capability.scope,
        payload_hash=digest,
        payload=payload,
        signature=b64encode(signature).decode("ascii"),
    )


def _verifier(api: Any, issuer: Any) -> Any:
    return api.CapabilityVerifier(api.TrustedRegistry(issuers=(issuer,)))


def _registry_json(issuer: Any) -> str:
    return json.dumps(
        {"issuers": [issuer.model_dump(mode="json")]},
        separators=(",", ":"),
    )


def _unchecked_mutation(model: Any, method: str, **updates: Any) -> Any:
    if method == "model_copy":
        return model.model_copy(update=updates)
    values = {name: getattr(model, name) for name in type(model).model_fields}
    values.update(updates)
    return type(model).model_construct(**values)


def test_valid_signature_returns_only_verified_issuer_and_required_capability() -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(api)
    signed = _signed(api, private_key, required)

    verified = _verifier(api, _issuer(api, private_key, required)).verify(
        signed,
        required,
        verification_time=NOW,
    )

    assert verified == api.VerifiedIssuer(
        issuer_id="authorizer.service",
        capability=required,
    )
    assert set(api.VerifiedIssuer.model_fields) == {"issuer_id", "capability"}


def test_verified_capability_lifecycle_always_comes_from_registry_truth() -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    granted = _capability(
        api,
        valid_from=NOW - timedelta(hours=2),
        valid_until=NOW + timedelta(hours=2),
    )
    required = granted.model_copy(
        update={
            "valid_from": NOW - timedelta(days=30),
            "valid_until": NOW + timedelta(days=30),
        }
    )
    signed = _signed(api, private_key, required)

    verified = _verifier(api, _issuer(api, private_key, granted)).verify(
        signed,
        required,
        verification_time=NOW,
    )

    assert verified.capability == granted


@pytest.mark.parametrize(
    ("identity_override", "match"),
    [
        ({"issuer_id": "unknown.service"}, "unknown issuer or key"),
        ({"key_id": "unknown-key"}, "unknown issuer or key"),
    ],
)
def test_unknown_issuer_or_key_fails_closed(
    identity_override: dict[str, str], match: str
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(api)
    signed = _signed(api, private_key, required, **identity_override)

    with pytest.raises(api.TrustVerificationError, match=match):
        _verifier(api, _issuer(api, private_key, required)).verify(
            signed,
            required,
            verification_time=NOW,
        )


@pytest.mark.parametrize(
    "changed",
    [
        {"artifact": "outcome"},
        {"namespace": "capital.edge.other"},
        {"mode": "broker_confirmed"},
        {"capability_version": "edge-authorizer.v2"},
        {"scope": "portfolio:other/lineage:btst"},
    ],
)
def test_caller_required_context_cannot_be_replaced_by_envelope_claims(
    changed: dict[str, str],
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(api)
    claimed_values = required.model_dump(mode="python")
    field, value = next(iter(changed.items()))
    if field == "mode":
        value = api.ExecutionMode(value)
    elif field == "artifact":
        value = api.ArtifactKind(value)
    claimed_values[field] = value
    claimed = api.Capability(**claimed_values)
    signed = _signed(api, private_key, claimed)

    with pytest.raises(api.TrustVerificationError, match="required capability context"):
        _verifier(api, _issuer(api, private_key, required)).verify(
            signed,
            required,
            verification_time=NOW,
        )


def test_self_declared_capability_never_grants_authority() -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    granted = _capability(api, scope="portfolio:paper-v3/lineage:other")
    self_claimed = _capability(api)
    signed = _signed(api, private_key, self_claimed)

    with pytest.raises(api.TrustVerificationError, match="capability is not granted"):
        _verifier(api, _issuer(api, private_key, granted)).verify(
            signed,
            self_claimed,
            verification_time=NOW,
        )


@pytest.mark.parametrize(
    ("issuer_changes", "verification_time", "match"),
    [
        ({"valid_from": NOW + timedelta(seconds=1)}, NOW, "not yet valid"),
        ({"valid_until": NOW}, NOW, "expired"),
        ({"revoked_at": NOW}, NOW, "revoked"),
    ],
)
def test_key_lifecycle_is_evaluated_at_explicit_utc_time(
    issuer_changes: dict[str, datetime],
    verification_time: datetime,
    match: str,
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(api)
    issuer = _issuer(api, private_key, required, **issuer_changes)
    signed = _signed(api, private_key, required)

    with pytest.raises(api.TrustVerificationError, match=match):
        _verifier(api, issuer).verify(
            signed,
            required,
            verification_time=verification_time,
        )


@pytest.mark.parametrize(
    ("capability_changes", "match"),
    [
        ({"valid_from": NOW + timedelta(seconds=1)}, "not yet valid"),
        ({"valid_until": NOW}, "expired"),
        ({"revoked_at": NOW}, "revoked"),
    ],
)
def test_capability_lifecycle_is_evaluated_at_explicit_utc_time(
    capability_changes: dict[str, datetime], match: str
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(api, **capability_changes)
    signed = _signed(api, private_key, required)

    with pytest.raises(api.TrustVerificationError, match=match):
        _verifier(api, _issuer(api, private_key, required)).verify(
            signed,
            required,
            verification_time=NOW,
        )


def test_verification_time_must_be_explicit_strict_utc() -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(api)
    verifier = _verifier(api, _issuer(api, private_key, required))
    signed = _signed(api, private_key, required)

    with pytest.raises(TypeError):
        verifier.verify(signed, required)  # type: ignore[call-arg]
    with pytest.raises(api.TrustVerificationError, match="UTC"):
        verifier.verify(
            signed,
            required,
            verification_time=NOW.replace(tzinfo=None),
        )


def test_payload_hash_mismatch_and_payload_mutation_fail_closed() -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(api)
    issuer = _issuer(api, private_key, required)
    signed = _signed(api, private_key, required)

    bad_hash = signed.model_copy(update={"payload_hash": "0" * 64})
    with pytest.raises(api.TrustVerificationError, match="payload hash"):
        _verifier(api, issuer).verify(
            bad_hash,
            required,
            verification_time=NOW,
        )

    mutated = signed.model_copy(update={"payload": PAYLOAD + b" "})
    with pytest.raises(api.TrustVerificationError, match="payload hash"):
        _verifier(api, issuer).verify(
            mutated,
            required,
            verification_time=NOW,
        )


@pytest.mark.parametrize(
    "header_change",
    [
        {"issuer_id": "other.service"},
        {"key_id": "other-key"},
        {"namespace": "capital.edge.other"},
    ],
)
def test_protected_headers_cannot_be_substituted_after_signing(
    header_change: dict[str, str],
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(api)
    issuer = _issuer(api, private_key, required)
    signed = _signed(api, private_key, required)
    substituted = signed.model_copy(update=header_change)

    with pytest.raises(api.TrustVerificationError):
        _verifier(api, issuer).verify(
            substituted,
            required,
            verification_time=NOW,
        )


def test_bad_signature_fails_closed() -> None:
    api = _api()
    trusted_key = Ed25519PrivateKey.generate()
    attacker_key = Ed25519PrivateKey.generate()
    required = _capability(api)
    signed = _signed(api, attacker_key, required)

    with pytest.raises(api.TrustVerificationError, match="signature"):
        _verifier(api, _issuer(api, trusted_key, required)).verify(
            signed,
            required,
            verification_time=NOW,
        )


def test_unknown_schema_major_fails_even_if_registry_claims_to_grant_it() -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    unknown = _capability(api, schema_major=api.SUPPORTED_SCHEMA_MAJOR + 1)
    signed = _signed(api, private_key, unknown)

    with pytest.raises(api.TrustVerificationError, match="schema major"):
        _verifier(api, _issuer(api, private_key, unknown)).verify(
            signed,
            unknown,
            verification_time=NOW,
        )


@pytest.mark.parametrize(
    ("issuer_kind", "capability_changes", "match"),
    [
        ("shadow", {"artifact": "decision_seal"}, "shadow"),
        ("authorizer", {"artifact": "decision_seal"}, "authorizer"),
        ("manual", {"mode": "broker_confirmed"}, "manual"),
    ],
)
def test_issuer_role_separation_cannot_be_overridden_by_a_registry_grant(
    issuer_kind: str,
    capability_changes: dict[str, str],
    match: str,
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    values = _capability(api).model_dump(mode="python")
    for field, value in capability_changes.items():
        if field == "artifact":
            value = api.ArtifactKind(value)
        elif field == "mode":
            value = api.ExecutionMode(value)
        values[field] = value
    required = api.Capability(**values)
    issuer = _issuer(
        api,
        private_key,
        required,
        issuer_kind=api.IssuerKind(issuer_kind),
    )
    signed = _signed(api, private_key, required)

    with pytest.raises(api.TrustVerificationError, match=match):
        _verifier(api, issuer).verify(
            signed,
            required,
            verification_time=NOW,
        )


def test_registry_loads_only_strict_public_key_truth(tmp_path: Path) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    capability = _capability(api)
    issuer = _issuer(api, private_key, capability)
    path = tmp_path / "trusted-issuers.json"
    path.write_text(_registry_json(issuer), encoding="utf-8")

    loaded = api.TrustedRegistry.load(path)

    assert loaded == api.TrustedRegistry(issuers=(issuer,))
    assert loaded.model_config["frozen"] is True
    assert not hasattr(api, "sign")
    assert all("private" not in field for field in api.TrustedIssuer.model_fields)

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["unexpected"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(api.TrustedRegistryLoadError):
        api.TrustedRegistry.load(path)


def test_registry_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    issuer = _issuer(api, private_key, _capability(api))
    path = tmp_path / "trusted-issuers.json"
    path.write_text(
        '{"issuers":[],"issuers":' + _registry_json(issuer)[11:],
        encoding="utf-8",
    )

    with pytest.raises(api.TrustedRegistryLoadError, match="duplicate"):
        api.TrustedRegistry.load(path)


def test_registry_loader_rejects_leaf_and_parent_symlinks(tmp_path: Path) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    issuer = _issuer(api, private_key, _capability(api))
    real_directory = tmp_path / "real-directory"
    real_directory.mkdir()
    real_path = real_directory / "trusted-issuers.json"
    real_path.write_text(_registry_json(issuer), encoding="utf-8")

    leaf_link = tmp_path / "leaf-link.json"
    leaf_link.symlink_to(real_path)
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(api.TrustedRegistryLoadError, match="regular|symlink"):
        api.TrustedRegistry.load(leaf_link)
    with pytest.raises(api.TrustedRegistryLoadError, match="regular|symlink"):
        api.TrustedRegistry.load(parent_link / real_path.name)


def test_registry_loader_rejects_non_regular_files_without_blocking(
    tmp_path: Path,
) -> None:
    api = _api()
    fifo_path = tmp_path / "registry.fifo"
    os.mkfifo(fifo_path)
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(api.TrustedRegistry.load, fifo_path)
    blocked = False
    try:
        with pytest.raises(api.TrustedRegistryLoadError, match="regular"):
            future.result(timeout=0.5)
    except FutureTimeoutError:
        blocked = True
    finally:
        if not future.done():
            writer = os.open(fifo_path, os.O_WRONLY | os.O_NONBLOCK)
            try:
                os.write(writer, b"{}")
            finally:
                os.close(writer)
        executor.shutdown(wait=True)

    assert blocked is False, "registry loader blocked while opening a FIFO"
    with pytest.raises(api.TrustedRegistryLoadError, match="regular"):
        api.TrustedRegistry.load(tmp_path)


def test_registry_loader_rejects_oversized_file_before_parsing(tmp_path: Path) -> None:
    api = _api()
    path = tmp_path / "oversized-registry.json"
    path.write_bytes(b" " * (1024 * 1024 + 1) + b'{"issuers":[]}')

    with pytest.raises(api.TrustedRegistryLoadError, match="too large"):
        api.TrustedRegistry.load(path)


def test_registry_loader_rejects_file_mutation_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    issuer = _issuer(api, private_key, _capability(api))
    path = tmp_path / "trusted-issuers.json"
    original = _registry_json(issuer).encode("utf-8")
    path.write_bytes(original)
    real_read = os.read
    mutated = False

    def mutate_after_first_read(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = real_read(descriptor, size)
        if chunk and not mutated:
            mutated = True
            path.write_bytes(original)
        return chunk

    monkeypatch.setattr(os, "read", mutate_after_first_read)

    with pytest.raises(api.TrustedRegistryLoadError, match="changed"):
        api.TrustedRegistry.load(path)


def test_registry_loader_rejects_descriptor_length_inconsistency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    path = tmp_path / "trusted-issuers.json"
    path.write_bytes(b'{"issuers":[]}')
    real_read = os.read
    first_read = True

    def truncate_observed_bytes(descriptor: int, size: int) -> bytes:
        nonlocal first_read
        chunk = real_read(descriptor, size)
        if first_read:
            first_read = False
            return chunk[:-1]
        return chunk

    monkeypatch.setattr(os, "read", truncate_observed_bytes)

    with pytest.raises(api.TrustedRegistryLoadError, match="changed"):
        api.TrustedRegistry.load(path)


@pytest.mark.parametrize(
    "missing_flag",
    ["O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK"],
)
def test_registry_loader_fails_closed_without_descriptor_safety_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_flag: str,
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    issuer = _issuer(api, private_key, _capability(api))
    path = tmp_path / "trusted-issuers.json"
    path.write_text(_registry_json(issuer), encoding="utf-8")
    monkeypatch.delattr(os, missing_flag)

    with pytest.raises(api.TrustedRegistryLoadError, match=missing_flag):
        api.TrustedRegistry.load(path)


@pytest.mark.parametrize(
    ("mode", "accepted"),
    [
        ("research_reconstruction", False),
        ("daily_bar_proxy", False),
        ("manual_confirmed", True),
        ("broker_confirmed", False),
    ],
)
def test_manual_outcome_issuer_is_isolated_to_manual_confirmed_mode(
    mode: str,
    accepted: bool,
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(
        api,
        artifact=api.ArtifactKind.OUTCOME,
        namespace="outcome.manual",
        mode=api.ExecutionMode(mode),
        capability_version="manual-outcome.v1",
        scope="portfolio:manual-v3",
    )
    issuer = _issuer(
        api,
        private_key,
        required,
        issuer_id="manual.operator",
        key_id="manual-key-2026-07",
        issuer_kind=api.IssuerKind.MANUAL,
    )
    signed = _signed(
        api,
        private_key,
        required,
        issuer_id=issuer.issuer_id,
        key_id=issuer.key_id,
    )

    if accepted:
        assert _verifier(api, issuer).verify(
            signed,
            required,
            verification_time=NOW,
        ).issuer_id == issuer.issuer_id
    else:
        with pytest.raises(api.TrustVerificationError, match="manual"):
            _verifier(api, issuer).verify(
                signed,
                required,
                verification_time=NOW,
            )


@pytest.mark.parametrize("mutation_method", ["model_copy", "model_construct"])
def test_verifier_revalidates_registry_instances_at_the_public_boundary(
    mutation_method: str,
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(
        api,
        artifact=api.ArtifactKind.OUTCOME,
        namespace="outcome.manual",
        mode=api.ExecutionMode.DAILY_BAR_PROXY,
        capability_version="manual-outcome.v1",
        scope="portfolio:manual-v3",
    )
    manual_issuer = _issuer(
        api,
        private_key,
        required,
        issuer_id="manual.operator",
        key_id="manual-key-2026-07",
        issuer_kind=api.IssuerKind.MANUAL,
    )
    poisoned_issuer = _unchecked_mutation(
        manual_issuer,
        mutation_method,
        issuer_kind=api.IssuerKind.MANUAL.value,
    )
    valid_registry = api.TrustedRegistry(issuers=(manual_issuer,))
    poisoned_registry = _unchecked_mutation(
        valid_registry,
        mutation_method,
        issuers=(poisoned_issuer,),
    )
    signed = _signed(
        api,
        private_key,
        required,
        issuer_id=manual_issuer.issuer_id,
        key_id=manual_issuer.key_id,
    )

    with pytest.raises(api.TrustVerificationError, match="registry"):
        verifier = api.CapabilityVerifier(poisoned_registry)
        verifier.verify(signed, required, verification_time=NOW)


@pytest.mark.parametrize("mutation_method", ["model_copy", "model_construct"])
def test_verifier_revalidates_signed_envelope_instances_at_the_public_boundary(
    mutation_method: str,
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(api)
    signed = _signed(api, private_key, required)
    poisoned_signed = _unchecked_mutation(
        signed,
        mutation_method,
        mode=required.mode.value,
    )
    verifier = _verifier(api, _issuer(api, private_key, required))

    with pytest.raises(api.TrustVerificationError, match="signed envelope"):
        verifier.verify(poisoned_signed, required, verification_time=NOW)


@pytest.mark.parametrize("mutation_method", ["model_copy", "model_construct"])
def test_verifier_revalidates_required_capability_at_the_public_boundary(
    mutation_method: str,
) -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(api)
    poisoned_required = _unchecked_mutation(
        required,
        mutation_method,
        mode=required.mode.value,
    )
    signed = _signed(api, private_key, required)
    verifier = _verifier(api, _issuer(api, private_key, required))

    with pytest.raises(api.TrustVerificationError, match="required capability"):
        verifier.verify(signed, poisoned_required, verification_time=NOW)


def test_registry_rejects_duplicate_identity_and_malformed_public_key() -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    capability = _capability(api)
    issuer = _issuer(api, private_key, capability)

    with pytest.raises(ValidationError, match="duplicate issuer/key"):
        api.TrustedRegistry(issuers=(issuer, issuer))
    with pytest.raises(ValidationError, match="public key"):
        api.TrustedIssuer(
            **(
                issuer.model_dump(mode="python")
                | {"public_key": b64encode(b"short").decode("ascii")}
            )
        )
