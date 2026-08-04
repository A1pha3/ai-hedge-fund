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
    root_verifier, signed_chain = _root_verified_bundle(
        api,
        api.TrustedRegistry(issuers=(issuer,)),
        return_context=True,
    )
    delegate = api.CapabilityVerifier(root_verifier, signed_chain)

    class BoundCurrentHeadVerifier:
        _signed_chain = delegate._signed_chain

        def verify(self, signed: Any, required: Any, **kwargs: Any) -> Any:
            return delegate.verify(
                signed,
                required,
                current_head=_current_head(api, delegate),
                **kwargs,
            )

    return BoundCurrentHeadVerifier()


def _current_head(api: Any, verifier: Any) -> Any:
    bundle = verifier._signed_chain[-1].bundle
    return api.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=bundle.registry_epoch,
        head_version=bundle.registry_epoch,
        store_version=1,
        observed_at=NOW,
    )


def _registry_json(issuer: Any) -> str:
    return json.dumps(
        {"issuers": [issuer.model_dump(mode="json")]},
        separators=(",", ":"),
    )


def _root_verified_bundle(
    api: Any,
    registry: Any,
    *,
    epoch: int = 1,
    trusted_at: datetime = NOW,
    root_valid_until: datetime | None = None,
    bundle_expires_at: datetime | None = None,
    root_revoked_at: datetime | None = None,
    registry_hash_override: str | None = None,
    tamper_signature: bool = False,
    return_context: bool = False,
) -> Any:
    from src.screening.offensive.v3.contracts.governance import TrustBundle

    root_key = Ed25519PrivateKey.generate()
    root_public = _public_key_b64(root_key)
    root_hash = hashlib.sha256(
        root_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()
    anchor = api.RootTrustAnchor(
        root_hash=root_hash,
        root_key_id="offline-root-1",
        public_key=root_public,
        valid_from=NOW - timedelta(days=30),
        valid_until=root_valid_until or NOW + timedelta(days=30),
        revoked_at=root_revoked_at,
    )
    bundle = TrustBundle(
        registry_epoch=epoch,
        predecessor_bundle_hash="0" * 64,
        root_hash=root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=(
            registry_hash_override or registry.content_hash()
        ),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=bundle_expires_at or NOW + timedelta(days=1),
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=2,
    )
    signature = b64encode(
        root_key.sign(api.trust_bundle_signature_preimage(bundle, registry))
    ).decode("ascii")
    candidate = api.SignedTrustBundle(
        bundle=bundle,
        registry=registry,
        signature=(
            b64encode(b"\0" * 64).decode("ascii") if tamper_signature else signature
        ),
    )
    verifier = api.TrustBundleVerifier((anchor,))
    if return_context:
        return verifier, (candidate,)
    return verifier.verify_chain((candidate,), trusted_at=trusted_at)


def test_root_signature_and_exact_trusted_at_are_required_for_bundle() -> None:
    api = _api()
    issuer_key = Ed25519PrivateKey.generate()
    capability = _capability(api)
    registry = api.TrustedRegistry(issuers=(_issuer(api, issuer_key, capability),))

    verified = _root_verified_bundle(api, registry)

    assert verified.registry == registry
    assert verified.trusted_at == NOW
    with pytest.raises(api.TrustVerificationError, match="trusted_at|UTC"):
        _root_verified_bundle(api, registry, trusted_at=NOW.replace(tzinfo=None))


def test_bundle_chain_rejects_rollback_and_wrong_predecessor() -> None:
    api = _api()
    issuer_key = Ed25519PrivateKey.generate()
    capability = _capability(api)
    registry = api.TrustedRegistry(issuers=(_issuer(api, issuer_key, capability),))
    from src.screening.offensive.v3.contracts.governance import TrustBundle

    root_key = Ed25519PrivateKey.generate()
    root_bytes = root_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    anchor = api.RootTrustAnchor(
        root_hash=hashlib.sha256(root_bytes).hexdigest(),
        root_key_id="offline-root-2",
        public_key=b64encode(root_bytes).decode("ascii"),
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        revoked_at=None,
    )
    bad = TrustBundle(
        registry_epoch=2,
        predecessor_bundle_hash="f" * 64,
        root_hash=anchor.root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(days=1),
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=2,
    )
    signed = api.SignedTrustBundle(
        bundle=bad,
        registry=registry,
        signature=b64encode(
            root_key.sign(api.trust_bundle_signature_preimage(bad, registry))
        ).decode("ascii"),
    )
    with pytest.raises(api.TrustVerificationError, match="genesis|predecessor"):
        api.TrustBundleVerifier((anchor,)).verify_chain(
            (signed,),
            trusted_at=NOW,
        )


def test_bundle_verification_rejects_expired_root_and_bundle() -> None:
    api = _api()
    issuer_key = Ed25519PrivateKey.generate()
    capability = _capability(api)
    registry = api.TrustedRegistry(issuers=(_issuer(api, issuer_key, capability),))

    with pytest.raises(api.TrustVerificationError, match="root.*expired"):
        _root_verified_bundle(
            api,
            registry,
            root_valid_until=NOW,
        )
    with pytest.raises(api.TrustVerificationError, match="bundle.*expired"):
        _root_verified_bundle(
            api,
            registry,
            bundle_expires_at=NOW,
        )
    with pytest.raises(api.TrustVerificationError, match="root.*revoked"):
        _root_verified_bundle(api, registry, root_revoked_at=NOW)


def test_bundle_verification_rejects_registry_hash_drift_and_signature_tamper() -> None:
    api = _api()
    issuer_key = Ed25519PrivateKey.generate()
    capability = _capability(api)
    registry = api.TrustedRegistry(issuers=(_issuer(api, issuer_key, capability),))

    with pytest.raises(api.TrustVerificationError, match="registry hash"):
        _root_verified_bundle(
            api,
            registry,
            registry_hash_override="f" * 64,
        )
    with pytest.raises(api.TrustVerificationError, match="root signature"):
        _root_verified_bundle(api, registry, tamper_signature=True)


def test_chain_allows_expired_historical_bundle_but_requires_live_head() -> None:
    from src.screening.offensive.v3.contracts.governance import TrustBundle

    api = _api()
    issuer_key = Ed25519PrivateKey.generate()
    capability = _capability(api)
    registry = api.TrustedRegistry(issuers=(_issuer(api, issuer_key, capability),))
    root_key = Ed25519PrivateKey.generate()
    root_bytes = root_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    anchor = api.RootTrustAnchor(
        root_hash=hashlib.sha256(root_bytes).hexdigest(),
        root_key_id="offline-root-rotation",
        public_key=b64encode(root_bytes).decode("ascii"),
        valid_from=NOW - timedelta(days=10),
        valid_until=NOW + timedelta(days=10),
        revoked_at=None,
    )

    def signed_bundle(
        epoch: int,
        predecessor_hash: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> Any:
        bundle = TrustBundle(
            registry_epoch=epoch,
            predecessor_bundle_hash=predecessor_hash,
            root_hash=anchor.root_hash,
            root_key_id=anchor.root_key_id,
            trusted_issuer_registry_hash=registry.content_hash(),
            issued_at=issued_at,
            expires_at=expires_at,
            revoked_at=None,
            issuer_id="offline-governance-root",
            issuer_capability="root.trust.bundle.v1",
            schema_major=2,
        )
        return api.SignedTrustBundle(
            bundle=bundle,
            registry=registry,
            signature=b64encode(
                root_key.sign(api.trust_bundle_signature_preimage(bundle, registry))
            ).decode("ascii"),
        )

    historical = signed_bundle(
        1,
        "0" * 64,
        NOW - timedelta(days=3),
        NOW - timedelta(days=1),
    )
    head = signed_bundle(
        2,
        historical.bundle.artifact_hash(),
        NOW - timedelta(days=2),
        NOW + timedelta(days=1),
    )

    verified = api.TrustBundleVerifier((anchor,)).verify_chain(
        (historical, head),
        trusted_at=NOW,
    )
    assert verified.bundle == head.bundle


def test_raw_registry_is_only_a_parser_and_cannot_verify_capabilities() -> None:
    api = _api()
    issuer_key = Ed25519PrivateKey.generate()
    capability = _capability(api)
    registry = api.TrustedRegistry(issuers=(_issuer(api, issuer_key, capability),))

    with pytest.raises(TypeError, match="TrustBundleVerifier|signed_chain"):
        api.CapabilityVerifier(registry)
    forged = api.VerifiedTrustBundle(
        bundle=_root_verified_bundle(api, registry).bundle,
        registry=registry,
        trusted_at=NOW,
    )
    with pytest.raises(TypeError, match="signed.*chain|TrustBundleVerifier"):
        api.CapabilityVerifier(forged)


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

    assert verified.issuer_id == "authorizer.service"
    assert verified.key_id == "authorizer-key-2026-07"
    assert verified.issuer_kind is api.IssuerKind.AUTHORIZER
    assert verified.capability == required
    assert verified.registry_epoch == 1
    assert verified.trusted_at == NOW
    assert verified.valid_from == NOW - timedelta(minutes=5)
    assert verified.valid_until == NOW + timedelta(days=1)
    assert set(api.VerifiedIssuer.model_fields) == {
        "issuer_id",
        "key_id",
        "issuer_kind",
        "public_key_fingerprint",
        "identity_fingerprint",
        "capability",
        "trust_bundle_hash",
        "registry_epoch",
        "trusted_at",
        "valid_from",
        "valid_until",
    }


def test_final_trust_verifier_does_not_accept_revision1_decision_seals() -> None:
    from src.screening.offensive.v3.contracts.revision1 import DecisionSeal

    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(
        api,
        artifact=api.ArtifactKind.DECISION_SEAL,
        namespace="decision.live",
        capability_version="growth-kernel.v1",
        scope="portfolio:paper-v3",
    )
    issuer = _issuer(
        api,
        private_key,
        required,
        issuer_id="growth-kernel.service",
        key_id="growth-kernel-key-2026-07",
        issuer_kind=api.IssuerKind.GROWTH_KERNEL,
    )
    opaque_payload = b'{"decision_kind":"decision_seal"}'
    signed = _signed(
        api,
        private_key,
        required,
        issuer_id=issuer.issuer_id,
        key_id=issuer.key_id,
        payload=opaque_payload,
    )

    with pytest.raises(api.TrustVerificationError, match="legacy|unsupported"):
        _verifier(api, issuer).verify(
            signed,
            required,
            verification_time=NOW,
        )
    with pytest.raises(ValidationError):
        DecisionSeal.model_validate_json(signed.payload, strict=True)


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
        ("shadow", {"artifact": "decision_seal"}, "legacy|unsupported"),
        ("authorizer", {"artifact": "decision_seal"}, "legacy|unsupported"),
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


def test_growth_kernel_cannot_sign_shadow_decisions() -> None:
    api = _api()
    private_key = Ed25519PrivateKey.generate()
    required = _capability(
        api,
        artifact=api.ArtifactKind.SHADOW_DECISION,
        namespace="decision.shadow",
        capability_version="shadow-decision.v1",
        scope="portfolio:shadow-v3",
    )
    issuer = _issuer(
        api,
        private_key,
        required,
        issuer_id="growth-kernel.service",
        key_id="growth-kernel-key-2026-07",
        issuer_kind=api.IssuerKind.GROWTH_KERNEL,
    )
    signed = _signed(
        api,
        private_key,
        required,
        issuer_id=issuer.issuer_id,
        key_id=issuer.key_id,
    )

    with pytest.raises(api.TrustVerificationError, match="growth_kernel"):
        _verifier(api, issuer).verify(
            signed,
            required,
            verification_time=NOW,
        )


@pytest.mark.parametrize(
    "artifact",
    [
        "PORTFOLIO_DECISION_SEAL",
        "EXECUTION_PERMIT",
        "ENTRY_CANCELLATION_RECEIPT",
    ],
)
def test_only_capital_gateway_can_issue_entry_authority_artifacts(
    artifact: str,
) -> None:
    api = _api()
    gateway_key = Ed25519PrivateKey.generate()
    artifact_kind = getattr(api.ArtifactKind, artifact)
    required = _capability(
        api,
        artifact=artifact_kind,
        namespace=f"capital-gateway.{artifact.lower()}",
        schema_major=2,
        capability_version="capital-gateway.authority.v1",
        scope="portfolio:paper-v3",
    )
    signed = _signed(
        api,
        gateway_key,
        required,
        issuer_id="capital-gateway.service",
        key_id="capital-gateway-key-1",
    )
    gateway = _issuer(
        api,
        gateway_key,
        required,
        issuer_id="capital-gateway.service",
        key_id="capital-gateway-key-1",
        issuer_kind=api.IssuerKind.CAPITAL_GATEWAY,
    )

    assert (
        _verifier(api, gateway)
        .verify(
            signed,
            required,
            trusted_at=NOW,
        )
        .issuer_id
        == gateway.issuer_id
    )

    for forbidden_role in (
        api.IssuerKind.GROWTH_KERNEL,
        api.IssuerKind.BROKER_GATEWAY,
        api.IssuerKind.SHADOW,
    ):
        forbidden = gateway.model_copy(update={"issuer_kind": forbidden_role})
        with pytest.raises(api.TrustVerificationError, match="cannot sign"):
            _verifier(api, forbidden).verify(
                signed,
                required,
                trusted_at=NOW,
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


def test_registry_rejects_key_rotation_that_changes_issuer_kind() -> None:
    api = _api()
    authorizer_key = Ed25519PrivateKey.generate()
    shadow_key = Ed25519PrivateKey.generate()
    authorizer = _issuer(api, authorizer_key, _capability(api))
    shadow_capability = _capability(
        api,
        artifact=api.ArtifactKind.SIGNAL,
        namespace="signal.shadow",
        capability_version="shadow-signal.v1",
        scope="portfolio:shadow-v3",
    )
    shadow = _issuer(
        api,
        shadow_key,
        shadow_capability,
        key_id="shadow-key-2026-07",
        issuer_kind=api.IssuerKind.SHADOW,
    )

    with pytest.raises(ValidationError, match="issuer.kind|issuer_kind"):
        api.TrustedRegistry(issuers=(authorizer, shadow))


def test_registry_loader_rejects_key_rotation_that_changes_issuer_kind(
    tmp_path: Path,
) -> None:
    api = _api()
    authorizer_key = Ed25519PrivateKey.generate()
    shadow_key = Ed25519PrivateKey.generate()
    authorizer = _issuer(api, authorizer_key, _capability(api))
    shadow = _issuer(
        api,
        shadow_key,
        _capability(
            api,
            artifact=api.ArtifactKind.SIGNAL,
            namespace="signal.shadow",
            capability_version="shadow-signal.v1",
            scope="portfolio:shadow-v3",
        ),
        key_id="shadow-key-2026-07",
        issuer_kind=api.IssuerKind.SHADOW,
    )
    path = tmp_path / "trusted-issuers.json"
    path.write_text(
        json.dumps(
            {
                "issuers": [
                    authorizer.model_dump(mode="json"),
                    shadow.model_dump(mode="json"),
                ]
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    with pytest.raises(api.TrustedRegistryLoadError, match="issuer.kind|issuer_kind"):
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


def test_registry_loader_closes_leaf_if_parent_descriptor_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening.offensive.v3.trust import registry as registry_module

    api = _api()
    private_key = Ed25519PrivateKey.generate()
    issuer = _issuer(api, private_key, _capability(api))
    path = tmp_path / "trusted-issuers.json"
    path.write_text(_registry_json(issuer), encoding="utf-8")
    real_open = registry_module.os.open
    real_close = registry_module.os.close
    leaf_descriptor: int | None = None
    parent_descriptor: int | None = None
    leaf_close_attempted = False
    parent_close_failed = False
    closed_descriptors: set[int] = set()

    def track_open(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal leaf_descriptor, parent_descriptor
        descriptor = real_open(file, flags, mode, dir_fd=dir_fd)
        if os.fspath(file) == path.name and not flags & os.O_DIRECTORY:
            leaf_descriptor = descriptor
            parent_descriptor = dir_fd
        return descriptor

    def fail_parent_close_once(descriptor: int) -> None:
        nonlocal leaf_close_attempted, parent_close_failed
        if descriptor == leaf_descriptor:
            leaf_close_attempted = True
        if descriptor == parent_descriptor and not parent_close_failed:
            parent_close_failed = True
            raise OSError("simulated parent close failure")
        real_close(descriptor)
        closed_descriptors.add(descriptor)

    monkeypatch.setattr(registry_module.os, "open", track_open)
    monkeypatch.setattr(registry_module.os, "close", fail_parent_close_once)
    caught: Exception | None = None
    try:
        api.TrustedRegistry.load(path)
    except Exception as exc:  # noqa: BLE001 - public-boundary assertion
        caught = exc
    finally:
        for descriptor in (leaf_descriptor, parent_descriptor):
            if descriptor is not None and descriptor not in closed_descriptors:
                try:
                    real_close(descriptor)
                except OSError:
                    pass

    assert (
        isinstance(caught, api.TrustedRegistryLoadError),
        leaf_close_attempted,
    ) == (True, True)


def test_registry_loader_preserves_read_error_and_continues_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening.offensive.v3.trust import registry as registry_module

    api = _api()
    path = tmp_path / "trusted-issuers.json"
    path.write_bytes(b'{"issuers":[]}')
    real_open = registry_module.os.open
    real_close = registry_module.os.close
    real_read = registry_module.os.read
    leaf_descriptor: int | None = None
    parent_descriptor: int | None = None
    leaf_close_failed = False
    parent_close_after_leaf_failure = False
    closed_descriptors: set[int] = set()

    def track_open(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal leaf_descriptor, parent_descriptor
        descriptor = real_open(file, flags, mode, dir_fd=dir_fd)
        if os.fspath(file) == path.name and not flags & os.O_DIRECTORY:
            leaf_descriptor = descriptor
            parent_descriptor = dir_fd
        return descriptor

    def fail_leaf_read(descriptor: int, size: int) -> bytes:
        if descriptor == leaf_descriptor:
            raise OSError("simulated registry read failure")
        return real_read(descriptor, size)

    def fail_leaf_close_once(descriptor: int) -> None:
        nonlocal leaf_close_failed, parent_close_after_leaf_failure
        if descriptor == leaf_descriptor and not leaf_close_failed:
            leaf_close_failed = True
            raise OSError("simulated leaf close failure")
        if descriptor == parent_descriptor and leaf_close_failed:
            parent_close_after_leaf_failure = True
        real_close(descriptor)
        closed_descriptors.add(descriptor)

    monkeypatch.setattr(registry_module.os, "open", track_open)
    monkeypatch.setattr(registry_module.os, "read", fail_leaf_read)
    monkeypatch.setattr(registry_module.os, "close", fail_leaf_close_once)
    caught: Exception | None = None
    try:
        api.TrustedRegistry.load(path)
    except Exception as exc:  # noqa: BLE001 - public-boundary assertion
        caught = exc
    finally:
        if leaf_descriptor is not None and leaf_descriptor not in closed_descriptors:
            try:
                real_close(leaf_descriptor)
            except OSError:
                pass

    assert isinstance(caught, api.TrustedRegistryLoadError)
    assert "unable to read" in str(caught)
    assert (leaf_close_failed, parent_close_after_leaf_failure) == (True, True)


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
        assert (
            _verifier(api, issuer)
            .verify(
                signed,
                required,
                verification_time=NOW,
            )
            .issuer_id
            == issuer.issuer_id
        )
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
    with pytest.raises(TypeError, match="TrustBundleVerifier|signed_chain"):
        api.CapabilityVerifier(poisoned_registry)


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
