"""Adversarial review-fix tests for Task 4 trust, policy, and PIT boundaries."""

from __future__ import annotations

from base64 import b64encode
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from pydantic import ValidationError


UTC = timezone.utc
NOW = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)
ZERO_HASH = "0" * 64


def _public_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _signed_bundle(
    api: Any,
    *,
    root_key: Ed25519PrivateKey,
    anchor: Any,
    registry: Any,
    epoch: int,
    predecessor_hash: str,
    issued_at: datetime,
    expires_at: datetime,
) -> Any:
    from src.screening.offensive.v3.contracts.governance import TrustBundle

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


def _trust_context(
    *,
    artifact_name: str = "EDGE_AUTHORIZATION",
    issuer_kind_name: str = "AUTHORIZER",
    schema_major: int = 2,
    mode_name: str = "DAILY_BAR_PROXY",
    root_valid_from: datetime = NOW - timedelta(days=1),
    root_valid_until: datetime = NOW + timedelta(hours=4),
    root_revoked_at: datetime | None = None,
    bundle_issued_at: datetime = NOW - timedelta(minutes=10),
    bundle_expires_at: datetime = NOW + timedelta(hours=3),
    issuer_valid_until: datetime = NOW + timedelta(hours=2),
    capability_valid_until: datetime = NOW + timedelta(hours=1),
    capability_revoked_at: datetime | None = None,
) -> SimpleNamespace:
    from src.screening.offensive.v3 import trust as api

    artifact = getattr(api.ArtifactKind, artifact_name)
    issuer_kind = getattr(api.IssuerKind, issuer_kind_name)
    mode = getattr(api.ExecutionMode, mode_name)
    issuer_key = Ed25519PrivateKey.generate()
    issuer_public = _public_bytes(issuer_key)
    capability = api.Capability(
        artifact=artifact,
        namespace=f"test.{artifact.value}",
        mode=mode,
        schema_major=schema_major,
        capability_version=f"test.{artifact.value}.v1",
        scope="portfolio:paper-v3",
        valid_from=NOW - timedelta(days=1),
        valid_until=capability_valid_until,
        revoked_at=capability_revoked_at,
    )
    issuer = api.TrustedIssuer(
        issuer_id=f"{issuer_kind.value}.service",
        key_id=f"{issuer_kind.value}-key-1",
        issuer_kind=issuer_kind,
        public_key=b64encode(issuer_public).decode("ascii"),
        valid_from=NOW - timedelta(days=1),
        valid_until=issuer_valid_until,
        revoked_at=None,
        capabilities=(capability,),
    )
    registry = api.TrustedRegistry(issuers=(issuer,))
    root_key = Ed25519PrivateKey.generate()
    root_public = _public_bytes(root_key)
    anchor = api.RootTrustAnchor(
        root_hash=hashlib.sha256(root_public).hexdigest(),
        root_key_id="offline-root-1",
        public_key=b64encode(root_public).decode("ascii"),
        valid_from=root_valid_from,
        valid_until=root_valid_until,
        revoked_at=root_revoked_at,
    )
    genesis = _signed_bundle(
        api,
        root_key=root_key,
        anchor=anchor,
        registry=registry,
        epoch=1,
        predecessor_hash=ZERO_HASH,
        issued_at=bundle_issued_at,
        expires_at=bundle_expires_at,
    )
    payload = b'{"candidate":"task4-review"}'
    payload_hash = hashlib.sha256(payload).hexdigest()
    protected = api.canonical_json_bytes(
        {
            "artifact": capability.artifact,
            "capability_scope": capability.scope,
            "capability_version": capability.capability_version,
            "issuer_id": issuer.issuer_id,
            "key_id": issuer.key_id,
            "mode": capability.mode,
            "namespace": capability.namespace,
            "payload": b64encode(payload).decode("ascii"),
            "payload_hash": payload_hash,
            "schema_major": capability.schema_major,
        }
    )
    envelope = api.SignedEnvelope(
        issuer_id=issuer.issuer_id,
        key_id=issuer.key_id,
        schema_major=capability.schema_major,
        artifact=capability.artifact,
        namespace=capability.namespace,
        mode=capability.mode,
        capability_version=capability.capability_version,
        capability_scope=capability.scope,
        payload_hash=payload_hash,
        payload=payload,
        signature=b64encode(issuer_key.sign(protected)).decode("ascii"),
    )
    trust_verifier = api.TrustBundleVerifier((anchor,))
    capability_verifier = api.CapabilityVerifier(trust_verifier, (genesis,))
    head = api.CurrentTrustHeadWitness(
        active_trust_bundle_hash=genesis.bundle.artifact_hash(),
        registry_epoch=1,
        head_version=1,
        store_version=1,
        observed_at=NOW,
    )
    return SimpleNamespace(
        api=api,
        root_key=root_key,
        anchor=anchor,
        registry=registry,
        issuer=issuer,
        issuer_key=issuer_key,
        capability=capability,
        genesis=genesis,
        envelope=envelope,
        trust_verifier=trust_verifier,
        verifier=capability_verifier,
        head=head,
    )


def test_capability_requires_current_head_and_rejects_superseded_chain() -> None:
    context = _trust_context()
    verified = context.verifier.verify(
        context.envelope,
        context.capability,
        current_head=context.head,
        trusted_at=NOW,
    )
    assert verified.trust_bundle_hash == context.head.active_trust_bundle_hash

    with pytest.raises(TypeError, match="current.*head|witness"):
        context.verifier.verify(
            context.envelope,
            context.capability,
            trusted_at=NOW,
        )

    successor = _signed_bundle(
        context.api,
        root_key=context.root_key,
        anchor=context.anchor,
        registry=context.registry,
        epoch=2,
        predecessor_hash=context.genesis.bundle.artifact_hash(),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=2),
    )
    active_successor = context.api.CurrentTrustHeadWitness(
        active_trust_bundle_hash=successor.bundle.artifact_hash(),
        registry_epoch=2,
        head_version=2,
        store_version=2,
        observed_at=NOW,
    )
    with pytest.raises(context.api.TrustVerificationError, match="current.*head"):
        context.verifier.verify(
            context.envelope,
            context.capability,
            current_head=active_successor,
            trusted_at=NOW,
        )


def test_current_head_rejects_same_epoch_fork_future_time_and_nonpositive_versions() -> (
    None
):
    context = _trust_context()
    fork = _signed_bundle(
        context.api,
        root_key=context.root_key,
        anchor=context.anchor,
        registry=context.registry,
        epoch=1,
        predecessor_hash=ZERO_HASH,
        issued_at=NOW - timedelta(minutes=9),
        expires_at=NOW + timedelta(hours=3),
    )
    fork_verifier = context.api.CapabilityVerifier(
        context.trust_verifier,
        (fork,),
    )
    with pytest.raises(context.api.TrustVerificationError, match="current.*head"):
        fork_verifier.verify(
            context.envelope,
            context.capability,
            current_head=context.head,
            trusted_at=NOW,
        )

    future = context.head.model_copy(update={"observed_at": NOW + timedelta(seconds=1)})
    with pytest.raises(context.api.TrustVerificationError, match="observed_at"):
        context.verifier.verify(
            context.envelope,
            context.capability,
            current_head=future,
            trusted_at=NOW,
        )

    for field in ("head_version", "store_version"):
        with pytest.raises(ValidationError):
            context.api.CurrentTrustHeadWitness.model_validate(
                context.head.model_dump(mode="python") | {field: 0},
                strict=True,
            )


def test_trust_verifier_exposes_only_complete_signed_chain_api() -> None:
    context = _trust_context()
    assert not hasattr(context.trust_verifier, "verify")
    assert (
        context.trust_verifier.verify_chain((context.genesis,), trusted_at=NOW).bundle
        == context.genesis.bundle
    )

    orphan = _signed_bundle(
        context.api,
        root_key=context.root_key,
        anchor=context.anchor,
        registry=context.registry,
        epoch=2,
        predecessor_hash="f" * 64,
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=2),
    )
    with pytest.raises(context.api.TrustVerificationError, match="genesis|predecessor"):
        context.trust_verifier.verify_chain((orphan,), trusted_at=NOW)


def test_root_anchor_must_be_active_at_bundle_issue_and_head_trusted_time() -> None:
    issued_before_root = _trust_context(
        root_valid_from=NOW - timedelta(minutes=5),
        bundle_issued_at=NOW - timedelta(minutes=10),
    )
    with pytest.raises(
        issued_before_root.api.TrustVerificationError,
        match="root.*not yet valid|issue",
    ):
        issued_before_root.trust_verifier.verify_chain(
            (issued_before_root.genesis,), trusted_at=NOW
        )

    revoked_head = _trust_context(root_revoked_at=NOW - timedelta(minutes=1))
    with pytest.raises(revoked_head.api.TrustVerificationError, match="root.*revoked"):
        revoked_head.trust_verifier.verify_chain(
            (revoked_head.genesis,), trusted_at=NOW
        )


@pytest.mark.parametrize(
    ("artifact_name", "issuer_kind_name"),
    [
        ("SNAPSHOT", "MARKET_PUBLISHER"),
        ("SIGNAL", "SIGNAL_PRODUCER"),
        ("PLAN", "SIGNAL_PRODUCER"),
        ("OUTCOME", "OUTCOME_FINALIZER"),
        ("EDGE_AUTHORIZATION", "AUTHORIZER"),
        ("EXPLORATION_AUTHORIZATION", "GOVERNANCE"),
        ("RECOVERY_AUTHORIZATION", "GOVERNANCE"),
        ("SHADOW_DECISION", "SHADOW"),
        ("PORTFOLIO_DECISION_SEAL", "CAPITAL_GATEWAY"),
        ("EXECUTION_PERMIT", "CAPITAL_GATEWAY"),
        ("ENTRY_CANCELLATION_RECEIPT", "CAPITAL_GATEWAY"),
        ("POLICY_ACTIVATION", "GOVERNANCE"),
    ],
)
def test_revision2_artifact_role_and_schema_routes_are_complete(
    artifact_name: str,
    issuer_kind_name: str,
) -> None:
    context = _trust_context(
        artifact_name=artifact_name,
        issuer_kind_name=issuer_kind_name,
        schema_major=2,
    )
    verified = context.verifier.verify(
        context.envelope,
        context.capability,
        current_head=context.head,
        trusted_at=NOW,
    )
    assert verified.capability.schema_major == 2


def test_final_verifier_rejects_legacy_decision_seal_and_wrong_recovery_role() -> None:
    legacy = _trust_context(
        artifact_name="DECISION_SEAL",
        issuer_kind_name="GROWTH_KERNEL",
        schema_major=1,
    )
    with pytest.raises(
        legacy.api.TrustVerificationError, match="cannot sign|unsupported"
    ):
        legacy.verifier.verify(
            legacy.envelope,
            legacy.capability,
            current_head=legacy.head,
            trusted_at=NOW,
        )

    recovery = _trust_context(
        artifact_name="RECOVERY_AUTHORIZATION",
        issuer_kind_name="AUTHORIZER",
    )
    with pytest.raises(recovery.api.TrustVerificationError, match="cannot sign"):
        recovery.verifier.verify(
            recovery.envelope,
            recovery.capability,
            current_head=recovery.head,
            trusted_at=NOW,
        )


def test_verified_issuer_binds_exact_identity_and_effective_expiry() -> None:
    context = _trust_context(capability_revoked_at=NOW + timedelta(minutes=30))
    verified = context.verifier.verify(
        context.envelope,
        context.capability,
        current_head=context.head,
        trusted_at=NOW,
    )
    public_key_fingerprint = hashlib.sha256(
        _public_bytes(context.issuer_key)
    ).hexdigest()
    identity_payload = {
        "issuer_id": context.issuer.issuer_id,
        "issuer_kind": context.issuer.issuer_kind.value,
        "key_id": context.issuer.key_id,
        "public_key_fingerprint": public_key_fingerprint,
    }
    identity_preimage = json.dumps(
        {
            "domain": "ai-hedge-fund.v3.trust.issuer-identity.v1",
            "payload": identity_payload,
            "schema_major": 2,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    identity_fingerprint = hashlib.sha256(identity_preimage).hexdigest()

    assert verified.key_id == context.issuer.key_id
    assert verified.issuer_kind is context.issuer.issuer_kind
    assert verified.public_key_fingerprint == public_key_fingerprint
    assert verified.identity_fingerprint == identity_fingerprint
    assert verified.valid_until == NOW + timedelta(minutes=30)

    poisoned_registry = context.registry.model_copy(
        update={
            "issuers": (context.issuer.model_copy(update={"key_id": "forged-key"}),)
        }
    )
    poisoned_bundle = context.genesis.model_copy(update={"registry": poisoned_registry})
    verifier = context.api.CapabilityVerifier(
        context.trust_verifier,
        (poisoned_bundle,),
    )
    with pytest.raises(context.api.TrustVerificationError):
        verifier.verify(
            context.envelope,
            context.capability,
            current_head=context.head,
            trusted_at=NOW,
        )


def _independent_domain_hash(domain: str, schema_major: int, payload: Any) -> str:
    canonical_payload = payload.model_dump(mode="json", round_trip=True)
    encoded = json.dumps(
        {
            "domain": domain,
            "payload": canonical_payload,
            "schema_major": schema_major,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_executable_plan_requires_active_store_record_and_known_provider_time() -> None:
    from src.screening.offensive.v3 import contracts as api
    from tests.offensive.v3.contracts.checkpoint2_helpers import (
        _plan,
        _proposal,
    )

    proposal = _proposal(api)
    line = proposal.order_lines[0]
    assert isinstance(line.plan_evidence, api.EvidenceRecord)
    assert line.plan_evidence.is_active is True
    assert line.plan_evidence_artifact_hash == line.plan_evidence.artifact_hash()

    raw = line.model_dump(mode="python", round_trip=True)
    raw["plan_evidence"] = line.plan_evidence.evidence
    raw["plan_evidence_artifact_hash"] = line.plan_evidence.evidence.content_hash()
    with pytest.raises(ValidationError, match="EvidenceRecord|plan_evidence"):
        api.PortfolioOrderLine.model_validate(raw, strict=True)

    for state in (
        api.ProviderPublicationState.UNKNOWN,
        api.ProviderPublicationState.NOT_APPLICABLE,
    ):
        plan = api.PlanEvidence.model_validate(
            _plan(api).model_dump(mode="python") | {"provider_published_at": state},
            strict=True,
        )
        record = api.EvidenceRecord[api.PlanEvidence](
            evidence=plan,
            ingested_at=plan.available_at,
            commit_sequence=2,
            revision=1,
            supersedes_revision=None,
            active_revision=1,
        )
        poisoned = line.model_dump(mode="python", round_trip=True) | {
            "plan_evidence": record,
            "plan_evidence_artifact_hash": record.artifact_hash(),
        }
        with pytest.raises(ValidationError, match="provider|publication|PIT"):
            api.PortfolioOrderLine.model_validate(poisoned, strict=True)

    historical = line.plan_evidence.model_copy(update={"active_revision": 2})
    poisoned = line.model_dump(mode="python", round_trip=True) | {
        "plan_evidence": historical,
        "plan_evidence_artifact_hash": historical.artifact_hash(),
    }
    with pytest.raises(ValidationError, match="active.*revision|historical"):
        api.PortfolioOrderLine.model_validate(poisoned, strict=True)


def test_store_timeline_is_in_plan_and_portfolio_hash_preimage() -> None:
    from src.screening.offensive.v3 import contracts as api
    from tests.offensive.v3.contracts.checkpoint2_helpers import _proposal

    first = _proposal(api)
    first_line = first.order_lines[0]
    revised_record = api.EvidenceRecord[api.PlanEvidence](
        evidence=first_line.plan_evidence.evidence,
        ingested_at=first_line.plan_evidence.ingested_at,
        commit_sequence=first_line.plan_evidence.commit_sequence + 1,
        revision=2,
        supersedes_revision=1,
        active_revision=2,
    )
    revised_line = first_line.model_copy(
        update={
            "plan_evidence": revised_record,
            "plan_evidence_artifact_hash": revised_record.artifact_hash(),
        }
    )
    lines = (revised_line, *first.order_lines[1:])
    revised = api.PortfolioDecision.model_validate(
        first.model_dump(mode="python", round_trip=True) | {"order_lines": lines},
        strict=True,
    )

    assert revised.artifact_hash() != first.artifact_hash()
    assert first.artifact_hash() == _independent_domain_hash(
        first.HASH_DOMAIN,
        first.schema_major,
        first,
    )


def test_current_evidence_wire_is_schema_two_while_revision_one_stays_frozen() -> None:
    from src.screening.offensive.v3.contracts import evidence as current
    from src.screening.offensive.v3.contracts import revision1

    assert current.SUPPORTED_SCHEMA_MAJOR == 2
    assert "provider_published_at" not in revision1.EvidenceEnvelope.model_fields
    legacy = revision1.SnapshotEvidence.model_validate(
        {
            "evidence_id": "legacy-1",
            "subject_scope": revision1.EvidenceScope.GLOBAL,
            "subject_producer": "legacy",
            "family_id": None,
            "strategy_semver": "1.0.0",
            "behavior_fingerprint": "a" * 64,
            "policy_epoch": 1,
            "execution_version": "legacy.v1",
            "cost_version": "legacy.v1",
            "effective_at": NOW,
            "observed_at": NOW,
            "available_at": NOW,
            "mode": revision1.ExecutionMode.DAILY_BAR_PROXY,
            "source_authority": "legacy",
            "payload_content_hash": "b" * 64,
            "schema_major": 1,
            "evidence_kind": "snapshot",
        },
        strict=True,
    )
    assert legacy.schema_major == 1


def _policy_head_witness(verifier: Any) -> Any:
    from src.screening.offensive.v3 import trust

    bundle = verifier._signed_chain[-1].bundle
    return trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=bundle.registry_epoch,
        head_version=bundle.registry_epoch,
        store_version=1,
        observed_at=NOW,
    )


def _active_policy_witness(
    policy_api: Any,
    activation: Any,
    **overrides: Any,
) -> Any:
    values = {
        "active_policy_activation_hash": "f" * 64,
        "portfolio_id": activation.portfolio_id,
        "broker_account_id": activation.broker_account_id,
        "broker_account_fingerprint": activation.broker_account_fingerprint,
        "mode": activation.mode,
        "trust_bundle_hash": activation.trust_bundle_hash,
        "registry_epoch": activation.registry_epoch,
        "policy_epoch": activation.policy_epoch - 1,
        "authority_epoch": activation.authority_epoch,
        "risk_epoch": activation.risk_epoch,
        "effective_from": activation.effective_from - timedelta(minutes=1),
        "store_version": 1,
        "observed_at": NOW,
    }
    values.update(overrides)
    return policy_api.ActivePolicyActivationWitness(**values)


def _verify_policy_candidate(
    policy_api: Any,
    trust: Any,
    policy: Any,
    signed: Any,
    required: Any,
    verifier: Any,
    *,
    predecessor: Any | None,
) -> Any:
    return policy_api.verify_policy_activation(
        signed,
        policy,
        verifier,
        required,
        current_trust_head=_policy_head_witness(verifier),
        trusted_at=NOW,
        predecessor=predecessor,
        expected_portfolio_id="paper-v3",
        expected_broker_account_id="manual-account-1",
        expected_broker_account_fingerprint=None,
        expected_mode=trust.ExecutionMode.MANUAL_CONFIRMED,
    )


def test_policy_genesis_requires_current_trust_head_and_all_epochs_one() -> None:
    from src.screening.offensive.v3 import trust
    from tests.offensive.v3.contracts.test_policy import _signed_policy_activation

    policy_api = __import__(
        "src.screening.offensive.v3.policy",
        fromlist=["policy"],
    )
    policy, activation, signed, required, verifier = _signed_policy_activation()
    verified = _verify_policy_candidate(
        policy_api,
        trust,
        policy,
        signed,
        required,
        verifier,
        predecessor=None,
    )
    assert verified.activation == activation
    assert not hasattr(verified, "activate")

    for epoch_field in ("policy_epoch", "authority_epoch", "risk_epoch"):
        changed_policy = {epoch_field: 2}
        policy, _, signed, required, verifier = _signed_policy_activation(
            policy_updates=changed_policy,
        )
        with pytest.raises(
            policy_api.PolicyActivationVerificationError,
            match="genesis|epoch.*one",
        ):
            _verify_policy_candidate(
                policy_api,
                trust,
                policy,
                signed,
                required,
                verifier,
                predecessor=None,
            )


def test_policy_predecessor_must_be_typed_active_store_witness() -> None:
    from src.screening.offensive.v3 import policy as policy_api
    from src.screening.offensive.v3 import trust
    from tests.offensive.v3.contracts.test_policy import _signed_policy_activation

    policy, activation, signed, required, verifier = _signed_policy_activation()
    with pytest.raises(
        policy_api.PolicyActivationVerificationError,
        match="predecessor|witness",
    ):
        _verify_policy_candidate(
            policy_api,
            trust,
            policy,
            signed,
            required,
            verifier,
            predecessor=activation,
        )


@pytest.mark.parametrize(
    ("policy_updates", "witness_updates", "match"),
    [
        ({"policy_epoch": 3}, {"policy_epoch": 1}, "exactly one"),
        (
            {"policy_epoch": 2},
            {"registry_epoch": 2, "trust_bundle_hash": "e" * 64},
            "registry.*rollback",
        ),
        (
            {"policy_epoch": 2},
            {"trust_bundle_hash": "e" * 64},
            "trust.*fork|trust.*mismatch",
        ),
        (
            {"policy_epoch": 2},
            {"effective_from": NOW},
            "effective_from|time.*rollback",
        ),
    ],
)
def test_policy_successor_rejects_epoch_trust_and_time_rollback(
    policy_updates: dict[str, int],
    witness_updates: dict[str, Any],
    match: str,
) -> None:
    from src.screening.offensive.v3 import policy as policy_api
    from src.screening.offensive.v3 import trust
    from tests.offensive.v3.contracts.test_policy import _signed_policy_activation

    policy, activation, signed, required, verifier = _signed_policy_activation(
        policy_updates=policy_updates,
        activation_updates={
            "predecessor_policy_activation_hash": "f" * 64,
            "effective_from": NOW - timedelta(minutes=1),
        },
    )
    predecessor = _active_policy_witness(
        policy_api,
        activation,
        **witness_updates,
    )
    with pytest.raises(policy_api.PolicyActivationVerificationError, match=match):
        _verify_policy_candidate(
            policy_api,
            trust,
            policy,
            signed,
            required,
            verifier,
            predecessor=predecessor,
        )


def test_policy_successor_accepts_exact_active_predecessor_without_activating() -> None:
    from src.screening.offensive.v3 import policy as policy_api
    from src.screening.offensive.v3 import trust
    from tests.offensive.v3.contracts.test_policy import _signed_policy_activation

    policy, activation, signed, required, verifier = _signed_policy_activation(
        policy_updates={"policy_epoch": 2},
        activation_updates={
            "predecessor_policy_activation_hash": "f" * 64,
            "effective_from": NOW - timedelta(minutes=1),
        },
    )
    predecessor = _active_policy_witness(policy_api, activation)
    verified = _verify_policy_candidate(
        policy_api,
        trust,
        policy,
        signed,
        required,
        verifier,
        predecessor=predecessor,
    )

    assert verified.activation == activation
    assert not hasattr(predecessor, "authorize")
    assert not hasattr(verified, "activate")
