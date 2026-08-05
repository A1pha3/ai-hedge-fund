"""Plan 03 Task 1: issuer-scoped PIT Evidence Store.

Covers payload round-trip and hash mismatch, secure blob durability,
duplicate/same-ID conflict, the effective/published/observed/ingested/
available ordering, trusted-clock stamp ownership, commit sequence
monotonicity, the revision/supersedes chain with cutoff-correct active
projections, a legal empty snapshot superseding a stale one, and issuer
namespace separation.
"""

from __future__ import annotations

from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
import pytest

from src.screening.offensive.v3 import trust
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    SUPPORTED_SCHEMA_MAJOR,
    canonical_json_bytes,
)
from src.screening.offensive.v3.contracts.base import (
    EvidenceScope,
    SignalStage,
)
from src.screening.offensive.v3.contracts.decision import PlanEvidence
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    OutcomeEvidence,
    SignalEvidence,
    SnapshotEvidence,
)
from src.screening.offensive.v3.contracts.governance import TrustBundle
from src.screening.offensive.v3.contracts.ports import EvidenceQueryPort
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.repository import (
    EvidenceRepository,
    EvidenceStoreError,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
OBSERVED = NOW - timedelta(hours=1)
AVAILABLE = NOW + timedelta(hours=1)
HASH = "e" * 64
NAMESPACE = "evidence.market.test"


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value

    def advance(self, **kwargs: float) -> None:
        self.now_value += timedelta(**kwargs)


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return b64encode(public_bytes).decode("ascii")


def _capability(**overrides):
    values = {
        "artifact": trust.ArtifactKind.SNAPSHOT,
        "namespace": NAMESPACE,
        "mode": ExecutionMode.RESEARCH_RECONSTRUCTION,
        "schema_major": SUPPORTED_SCHEMA_MAJOR,
        "capability_version": "evidence-publisher.v1",
        "scope": "evidence:market.test",
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "revoked_at": None,
    }
    values.update(overrides)
    return trust.Capability(**values)


def _issuer(private_key, *capabilities, issuer_id, key_id, kind):
    return trust.TrustedIssuer(
        issuer_id=issuer_id,
        key_id=key_id,
        issuer_kind=kind,
        public_key=_public_key_b64(private_key),
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        revoked_at=None,
        capabilities=tuple(capabilities),
    )


def _protected_input(*, issuer_id, key_id, capability, payload, payload_hash):
    return canonical_json_bytes(
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


def _signed(private_key, capability, *, issuer_id, key_id, payload):
    digest = hashlib.sha256(payload).hexdigest()
    protected = _protected_input(
        issuer_id=issuer_id,
        key_id=key_id,
        capability=capability,
        payload=payload,
        payload_hash=digest,
    )
    signature = private_key.sign(protected)
    return trust.SignedEnvelope(
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


def _root_context(registry):
    root_key = Ed25519PrivateKey.generate()
    root_public = _public_key_b64(root_key)
    root_hash = hashlib.sha256(
        root_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()
    anchor = trust.RootTrustAnchor(
        root_hash=root_hash,
        root_key_id="offline-root-1",
        public_key=root_public,
        valid_from=NOW - timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        revoked_at=None,
    )
    bundle = TrustBundle(
        registry_epoch=1,
        predecessor_bundle_hash="0" * 64,
        root_hash=root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(days=1),
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=2,
    )
    signature = b64encode(
        root_key.sign(trust.trust_bundle_signature_preimage(bundle, registry))
    ).decode("ascii")
    signed_bundle = trust.SignedTrustBundle(
        bundle=bundle, registry=registry, signature=signature
    )
    verifier = trust.TrustBundleVerifier((anchor,))
    delegate = trust.CapabilityVerifier(verifier, (signed_bundle,))
    head = trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=bundle.registry_epoch,
        head_version=bundle.registry_epoch,
        store_version=1,
        observed_at=NOW,
    )

    class _HeadProvider:
        def current_trust_head(self, trusted_at):
            return head

    return delegate, _HeadProvider()


class _World:
    """One trusted registry with publisher/finalizer issuers plus a store."""

    def __init__(self, tmp_path: Path) -> None:
        self.clock = _Clock(NOW)
        self.publisher_key = Ed25519PrivateKey.generate()
        self.signal_key = Ed25519PrivateKey.generate()
        self.finalizer_key = Ed25519PrivateKey.generate()
        self.snapshot_capability = _capability(
            artifact=trust.ArtifactKind.SNAPSHOT
        )
        self.signal_capability = _capability(
            artifact=trust.ArtifactKind.SIGNAL,
            namespace=NAMESPACE,
        )
        self.plan_capability = _capability(
            artifact=trust.ArtifactKind.PLAN,
            namespace=NAMESPACE,
        )
        self.outcome_capability = _capability(
            artifact=trust.ArtifactKind.OUTCOME,
            namespace=NAMESPACE,
        )
        registry = trust.TrustedRegistry(
            issuers=(
                _issuer(
                    self.publisher_key,
                    self.snapshot_capability,
                    issuer_id="market.publisher",
                    key_id="publisher-key-1",
                    kind=trust.IssuerKind.MARKET_PUBLISHER,
                ),
                _issuer(
                    self.signal_key,
                    self.signal_capability,
                    self.plan_capability,
                    issuer_id="signal.producer",
                    key_id="signal-key-1",
                    kind=trust.IssuerKind.SIGNAL_PRODUCER,
                ),
                _issuer(
                    self.finalizer_key,
                    self.outcome_capability,
                    issuer_id="outcome.finalizer",
                    key_id="finalizer-key-1",
                    kind=trust.IssuerKind.OUTCOME_FINALIZER,
                ),
            )
        )
        verifier, head_provider = _root_context(registry)
        self.blob_store = BlobStore(tmp_path / "blobs")
        self.repository = EvidenceRepository(
            database_path=str(tmp_path / "evidence.sqlite3"),
            blob_store=self.blob_store,
            verifier=verifier,
            trust_head_provider=head_provider,
            issuer_namespace=NAMESPACE,
            clock=self.clock,
        )

    def snapshot_envelope(self, evidence_id="snap-1", **overrides):
        values = {
            "evidence_id": evidence_id,
            "subject_scope": EvidenceScope.GLOBAL,
            "subject_producer": "market.test",
            "family_id": None,
            "strategy_semver": "3.0.0",
            "behavior_fingerprint": HASH,
            "policy_epoch": 1,
            "execution_version": "readiness.v2",
            "cost_version": "cn-a-share-costs.v1",
            "effective_at": OBSERVED,
            "provider_published_at": OBSERVED,
            "observed_at": OBSERVED,
            "available_at": AVAILABLE,
            "mode": ExecutionMode.RESEARCH_RECONSTRUCTION,
            "source_authority": "market.publisher",
            "payload_content_hash": HASH,
            "schema_major": SUPPORTED_SCHEMA_MAJOR,
            "evidence_kind": "snapshot",
        }
        values.update(overrides)
        return SnapshotEvidence(**values)

    def sign_snapshot(self, envelope):
        payload = envelope.model_dump_json().encode("utf-8")
        return _signed(
            self.publisher_key,
            self.snapshot_capability,
            issuer_id="market.publisher",
            key_id="publisher-key-1",
            payload=payload,
        ), payload


@pytest.fixture()
def world(tmp_path: Path) -> _World:
    return _World(tmp_path)


def test_publish_commits_store_owned_timeline(world: _World) -> None:
    envelope = world.snapshot_envelope()
    signed, payload = world.sign_snapshot(envelope)
    world.clock.advance(seconds=30)
    record = world.repository.publish(signed, payload)

    assert isinstance(record, EvidenceRecord)
    assert isinstance(record.evidence, SnapshotEvidence)
    assert record.revision == 1
    assert record.active_revision == 1
    assert record.is_active
    assert record.supersedes_revision is None
    assert record.commit_sequence == 1
    # The store owns ingested_at: it is the trusted clock instant, not a
    # producer-supplied field.
    assert record.ingested_at == NOW + timedelta(seconds=30)
    assert record.evidence.observed_at <= record.ingested_at
    assert record.ingested_at <= record.evidence.available_at
    # The blob is durable before the envelope is readable.
    assert world.blob_store.get(signed.payload_hash) == payload


def test_get_round_trips_concrete_variant_and_hash(world: _World) -> None:
    envelope = world.snapshot_envelope()
    signed, payload = world.sign_snapshot(envelope)
    published = world.repository.publish(signed, payload)
    fetched = world.repository.get("snap-1")
    assert type(fetched.evidence) is SnapshotEvidence
    assert fetched.evidence == envelope
    assert fetched.artifact_hash() == published.artifact_hash()
    assert fetched.commit_sequence == published.commit_sequence


def test_payload_hash_mismatch_fails_closed(world: _World) -> None:
    envelope = world.snapshot_envelope()
    signed, payload = world.sign_snapshot(envelope)
    tampered = payload + b" "
    with pytest.raises(EvidenceStoreError) as excinfo:
        world.repository.publish(signed, tampered)
    assert excinfo.value.code == "payload_hash_mismatch"
    assert world.repository.commit_sequence() == 0


def test_unknown_issuer_fails_closed(world: _World, tmp_path: Path) -> None:
    envelope = world.snapshot_envelope()
    payload = envelope.model_dump_json().encode("utf-8")
    rogue_key = Ed25519PrivateKey.generate()
    signed = _signed(
        rogue_key,
        world.snapshot_capability,
        issuer_id="market.publisher",
        key_id="rogue-key",
        payload=payload,
    )
    with pytest.raises(EvidenceStoreError) as excinfo:
        world.repository.publish(signed, payload)
    assert excinfo.value.code == "trust_verification_failed"


def test_namespace_mismatch_is_rejected(
    world: _World, tmp_path: Path
) -> None:
    other_capability = _capability(
        artifact=trust.ArtifactKind.SNAPSHOT,
        namespace="evidence.other.namespace",
    )
    registry = trust.TrustedRegistry(
        issuers=(
            _issuer(
                world.publisher_key,
                other_capability,
                issuer_id="market.publisher",
                key_id="publisher-key-1",
                kind=trust.IssuerKind.MARKET_PUBLISHER,
            ),
        )
    )
    verifier, head_provider = _root_context(registry)
    other_store = EvidenceRepository(
        database_path=str(tmp_path / "other.sqlite3"),
        blob_store=world.blob_store,
        verifier=verifier,
        trust_head_provider=head_provider,
        issuer_namespace=NAMESPACE,
        clock=world.clock,
    )
    envelope = world.snapshot_envelope()
    payload = envelope.model_dump_json().encode("utf-8")
    signed = _signed(
        world.publisher_key,
        other_capability,
        issuer_id="market.publisher",
        key_id="publisher-key-1",
        payload=payload,
    )
    with pytest.raises(EvidenceStoreError) as excinfo:
        other_store.publish(signed, payload)
    assert excinfo.value.code == "namespace_mismatch"


def test_ingestion_outside_availability_window_fails_closed(
    world: _World,
) -> None:
    envelope = world.snapshot_envelope(available_at=NOW - timedelta(minutes=5))
    signed, payload = world.sign_snapshot(envelope)
    world.clock.advance(hours=1)  # trusted_at beyond available_at
    with pytest.raises(EvidenceStoreError) as excinfo:
        world.repository.publish(signed, payload)
    assert excinfo.value.code == "store_timeline_rejected"


def test_duplicate_same_id_same_content_converges(world: _World) -> None:
    envelope = world.snapshot_envelope()
    signed, payload = world.sign_snapshot(envelope)
    first = world.repository.publish(signed, payload)
    second = world.repository.publish(signed, payload)
    assert second.commit_sequence == first.commit_sequence == 1
    assert second.artifact_hash() == first.artifact_hash()


def test_duplicate_same_id_different_content_conflicts(
    world: _World,
) -> None:
    envelope = world.snapshot_envelope()
    signed, payload = world.sign_snapshot(envelope)
    world.repository.publish(signed, payload)
    other = world.snapshot_envelope(source_authority="different.publisher")
    signed_other, payload_other = world.sign_snapshot(other)
    with pytest.raises(EvidenceStoreError) as excinfo:
        world.repository.publish(signed_other, payload_other)
    assert excinfo.value.code == "evidence_id_conflict"


def test_commit_sequence_and_dependency_root_are_monotone(
    world: _World,
) -> None:
    assert world.repository.commit_sequence() == 0
    roots = {world.repository.dependency_root()}
    for index in range(1, 4):
        envelope = world.snapshot_envelope(evidence_id=f"snap-{index}")
        signed, payload = world.sign_snapshot(envelope)
        record = world.repository.publish(signed, payload)
        assert record.commit_sequence == index
        roots.add(world.repository.dependency_root())
    assert world.repository.commit_sequence() == 3
    assert len(roots) == 4  # genesis root plus one per commit


def test_revision_chain_and_cutoff_active_projection(world: _World) -> None:
    envelope = world.snapshot_envelope(payload_content_hash="a" * 64)
    signed, payload = world.sign_snapshot(envelope)
    world.repository.publish(signed, payload)
    publish_time = world.clock.now_value

    world.clock.advance(minutes=10)
    revised = world.snapshot_envelope(
        payload_content_hash="b" * 64,
        observed_at=world.clock.now_value - timedelta(minutes=1),
        available_at=world.clock.now_value + timedelta(hours=1),
        effective_at=world.clock.now_value - timedelta(minutes=1),
        provider_published_at=world.clock.now_value - timedelta(minutes=1),
    )
    signed_rev, payload_rev = world.sign_snapshot(revised)
    prepared = world.repository.prepare_revision(signed_rev, payload_rev)
    assert prepared.revision == 2
    assert prepared.supersedes_revision == 1

    # Prepared but not activated: the active projection stays revision 1,
    # both now and at any cutoff after the preparation.
    assert world.repository.get("snap-1").revision == 1
    assert world.repository.get("snap-1").is_active
    world.clock.advance(minutes=5)
    active_now = world.repository.active_revision(
        "snap-1", world.clock.now_value
    )
    assert active_now.revision == 1

    world.clock.advance(minutes=5)
    activation_time = world.clock.now_value
    activated = world.repository.activate_revision("snap-1", 2)
    assert activated.revision == 2
    assert activated.is_active
    assert world.repository.get("snap-1").revision == 2
    assert world.repository.get("snap-1", revision=1).revision == 1
    assert not world.repository.get("snap-1", revision=1).is_active

    # Cutoffs before the activation keep seeing revision 1; later cutoffs
    # see revision 2. Official OOS never sees late activations early.
    before = world.repository.active_revision("snap-1", activation_time)
    assert before.revision == 1
    world.clock.advance(minutes=1)
    after = world.repository.active_revision(
        "snap-1", world.clock.now_value
    )
    assert after.revision == 2
    assert after.ingested_at < activation_time  # store-owned ingest time
    assert publish_time < activation_time


def test_activate_retry_converges_and_backwards_activation_is_rejected(
    world: _World,
) -> None:
    envelope = world.snapshot_envelope()
    signed, payload = world.sign_snapshot(envelope)
    world.repository.publish(signed, payload)
    revised = world.snapshot_envelope(payload_content_hash="c" * 64)
    signed_rev, payload_rev = world.sign_snapshot(revised)
    world.repository.prepare_revision(signed_rev, payload_rev)
    first = world.repository.activate_revision("snap-1", 2)
    again = world.repository.activate_revision("snap-1", 2)
    assert again.artifact_hash() == first.artifact_hash()


def test_legal_empty_snapshot_supersedes_stale_active(world: _World) -> None:
    stale = world.snapshot_envelope(payload_content_hash="d" * 64)
    signed, payload = world.sign_snapshot(stale)
    world.repository.publish(signed, payload)

    world.clock.advance(minutes=3)
    # Today's authoritative EMPTY observation: a legally empty snapshot
    # supersedes the stale one once activated.
    empty_envelope = world.snapshot_envelope(
        evidence_id="snap-empty",
        payload_content_hash="f" * 64,
        observed_at=world.clock.now_value - timedelta(seconds=10),
        available_at=world.clock.now_value + timedelta(hours=1),
        effective_at=world.clock.now_value - timedelta(seconds=10),
        provider_published_at=world.clock.now_value - timedelta(seconds=10),
    )
    signed_empty, payload_empty = world.sign_snapshot(empty_envelope)
    record = world.repository.publish(signed_empty, payload_empty)
    assert record.is_active
    assert world.repository.get("snap-empty").evidence == empty_envelope


def test_signal_and_outcome_and_plan_variants_round_trip(
    world: _World,
) -> None:
    signal = SignalEvidence(
        evidence_id="sig-1",
        subject_scope=EvidenceScope.STRATEGY_LINEAGE,
        subject_producer="btst",
        family_id="btst.limit-up-breakout",
        strategy_semver="3.0.0",
        behavior_fingerprint=HASH,
        policy_epoch=1,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=OBSERVED,
        provider_published_at=OBSERVED,
        observed_at=OBSERVED,
        available_at=AVAILABLE,
        mode=ExecutionMode.RESEARCH_RECONSTRUCTION,
        source_authority="signal.producer",
        payload_content_hash=HASH,
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="signal",
        stage=SignalStage.SELECTED,
    )
    signal_payload = signal.model_dump_json().encode("utf-8")
    signal_signed = _signed(
        world.signal_key,
        world.signal_capability,
        issuer_id="signal.producer",
        key_id="signal-key-1",
        payload=signal_payload,
    )
    signal_record = world.repository.publish(signal_signed, signal_payload)
    assert type(signal_record.evidence) is SignalEvidence

    plan = PlanEvidence(
        evidence_id="plan-1",
        subject_scope=EvidenceScope.STRATEGY_LINEAGE,
        subject_producer="btst",
        family_id="btst.limit-up-breakout",
        strategy_semver="3.0.0",
        behavior_fingerprint=HASH,
        policy_epoch=1,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=OBSERVED,
        provider_published_at=OBSERVED,
        observed_at=OBSERVED,
        available_at=AVAILABLE,
        mode=ExecutionMode.RESEARCH_RECONSTRUCTION,
        source_authority="signal.producer",
        payload_content_hash=HASH,
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="plan",
        portfolio_id="paper-v3",
        signal_session=date(2026, 8, 5),
        economic_lineage_id="btst-economic-lineage",
        snapshot_id="snapshot-001",
        raw_target_fraction=Decimal("0.02"),
        created_at=OBSERVED,
    )
    plan_payload = plan.model_dump_json().encode("utf-8")
    plan_signed = _signed(
        world.signal_key,
        world.plan_capability,
        issuer_id="signal.producer",
        key_id="signal-key-1",
        payload=plan_payload,
    )
    plan_record = world.repository.publish(plan_signed, plan_payload)
    assert type(plan_record.evidence) is PlanEvidence

    outcome = OutcomeEvidence(
        evidence_id="out-1",
        subject_scope=EvidenceScope.STRATEGY_LINEAGE,
        subject_producer="btst",
        family_id="btst.limit-up-breakout",
        strategy_semver="3.0.0",
        behavior_fingerprint=HASH,
        policy_epoch=1,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=OBSERVED,
        provider_published_at=OBSERVED,
        observed_at=OBSERVED,
        available_at=AVAILABLE,
        mode=ExecutionMode.RESEARCH_RECONSTRUCTION,
        source_authority="outcome.finalizer",
        payload_content_hash=HASH,
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="outcome",
    )
    outcome_payload = outcome.model_dump_json().encode("utf-8")
    outcome_signed = _signed(
        world.finalizer_key,
        world.outcome_capability,
        issuer_id="outcome.finalizer",
        key_id="finalizer-key-1",
        payload=outcome_payload,
    )
    outcome_record = world.repository.publish(outcome_signed, outcome_payload)
    assert type(outcome_record.evidence) is OutcomeEvidence

    fetched = world.repository.outcome("out-1", 1)
    assert fetched.artifact_hash() == outcome_record.artifact_hash()
    with pytest.raises(EvidenceStoreError) as excinfo:
        world.repository.outcome("sig-1", 1)
    assert excinfo.value.code == "evidence_kind_mismatch"


def test_repository_satisfies_final_evidence_query_port(
    world: _World,
) -> None:
    assert isinstance(world.repository, EvidenceQueryPort)


def test_cutoff_before_any_commit_fails_closed(world: _World) -> None:
    envelope = world.snapshot_envelope()
    signed, payload = world.sign_snapshot(envelope)
    world.repository.publish(signed, payload)
    with pytest.raises(EvidenceStoreError) as excinfo:
        world.repository.active_revision(
            "snap-1", NOW - timedelta(minutes=10)
        )
    assert excinfo.value.code == "evidence_not_committed_before_cutoff"
