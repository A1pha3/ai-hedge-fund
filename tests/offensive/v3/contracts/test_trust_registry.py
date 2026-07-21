"""Adversarial tests for the read-only v3 issuer trust boundary."""

from __future__ import annotations

from base64 import b64encode
from datetime import datetime, timedelta, timezone
import hashlib
import json
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
    path.write_text(
        json.dumps(
            {"issuers": [issuer.model_dump(mode="json")]},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

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
