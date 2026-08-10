"""Tests for canonical regime observation publication and PIT reads."""

from __future__ import annotations

import hashlib
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.screening.offensive.v3 import trust as v3trust
from src.screening.offensive.v3.contracts.base import EvidenceScope, ExecutionMode
from src.screening.offensive.v3.contracts.evidence import SnapshotEvidence
from src.screening.offensive.v3.contracts.regime import (
    RegimeObservation,
    RegimeObservationReason,
    RegimeSourceRevision,
    RegimeState,
)
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.regime import (
    ActiveRegimeObservation,
    RegimeEvidenceError,
    RegimeObservationPublisher,
    RegimeObservationReader,
)
from src.screening.offensive.v3.evidence.repository import EvidenceRepository

UTC = timezone.utc
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=UTC)
SESSION_DAY = datetime(2026, 8, 11, tzinfo=UTC).date()
ISSUER_NAMESPACE = "regime.classifier"
HASH_A = "a" * 64
HASH_B = "b" * 64


def _observation(
    *,
    state: RegimeState = RegimeState.NORMAL,
    reason: RegimeObservationReason = RegimeObservationReason.CLASSIFIED,
    raw_state: str | None = "NORMAL",
    observed_at: datetime = NOW,
) -> RegimeObservation:
    return RegimeObservation(
        signal_session=SESSION_DAY,
        state=state,
        reason=reason,
        raw_state=raw_state,
        source_revisions=(
            RegimeSourceRevision(evidence_id="regime-input-1", revision=1, artifact_hash=HASH_A),
            RegimeSourceRevision(evidence_id="regime-input-2", revision=2, artifact_hash=HASH_B),
        ),
        effective_at=observed_at - timedelta(minutes=30),
        provider_published_at=observed_at - timedelta(minutes=10),
        observed_at=observed_at,
        classifier_semver="1.0.0",
        behavior_fingerprint=HASH_A,
        input_schema_hash=HASH_B,
    )


def _snapshot(observation: RegimeObservation, evidence_id: str) -> SnapshotEvidence:
    return SnapshotEvidence(
        evidence_id=evidence_id,
        subject_scope=EvidenceScope.GLOBAL,
        subject_producer="regime.classifier",
        family_id=None,
        strategy_semver="1.0.0",
        behavior_fingerprint=observation.behavior_fingerprint,
        policy_epoch=1,
        execution_version="t0-close-t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=observation.effective_at,
        provider_published_at=observation.provider_published_at,  # type: ignore[arg-type]
        observed_at=observation.observed_at,
        available_at=observation.observed_at + timedelta(hours=1),
        mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority="governance.service",
        payload_content_hash=observation.content_hash(),
        schema_major=2,
        evidence_kind="snapshot",
    )


class _SnapshotSigner:
    """Signs SnapshotEvidence envelopes with a real governance trust chain."""

    def __init__(self, issuer_key, issuer, capability):
        self._key = issuer_key
        self._issuer = issuer
        self._capability = capability

    def sign_snapshot(self, snapshot: SnapshotEvidence, payload: bytes):
        payload_hash = hashlib.sha256(payload).hexdigest()
        protected = v3trust.canonical_json_bytes(
            {
                "artifact": self._capability.artifact,
                "capability_scope": self._capability.scope,
                "capability_version": self._capability.capability_version,
                "issuer_id": self._issuer.issuer_id,
                "key_id": self._issuer.key_id,
                "mode": self._capability.mode,
                "namespace": self._capability.namespace,
                "payload": b64encode(payload).decode("ascii"),
                "payload_hash": payload_hash,
                "schema_major": self._capability.schema_major,
            }
        )
        return v3trust.SignedEnvelope(
            issuer_id=self._issuer.issuer_id,
            key_id=self._issuer.key_id,
            schema_major=self._capability.schema_major,
            artifact=self._capability.artifact,
            namespace=self._capability.namespace,
            mode=self._capability.mode,
            capability_version=self._capability.capability_version,
            capability_scope=self._capability.scope,
            payload_hash=payload_hash,
            payload=payload,
            signature=b64encode(self._key.sign(protected)).decode("ascii"),
        )


class _TrustHeadProvider:
    def __init__(self, head: Any) -> None:
        self._head = head

    def current_trust_head(self, trusted_at: datetime) -> Any:
        return self._head


@pytest.fixture()
def rig(tmp_path: Path):
    issuer_key = Ed25519PrivateKey.generate()
    issuer_public = issuer_key.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    capability = v3trust.Capability(
        artifact=v3trust.ArtifactKind.SNAPSHOT,
        namespace=ISSUER_NAMESPACE,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        schema_major=2,
        capability_version="regime.snapshot.v1",
        scope="global:regime",
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=120),
        revoked_at=None,
    )
    issuer = v3trust.TrustedIssuer(
        issuer_id="governance.service",
        key_id="regime-key-1",
        issuer_kind=v3trust.IssuerKind.MARKET_PUBLISHER,
        public_key=b64encode(issuer_public).decode("ascii"),
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=120),
        revoked_at=None,
        capabilities=(capability,),
    )
    registry = v3trust.TrustedRegistry(issuers=(issuer,))
    root_key = Ed25519PrivateKey.generate()
    root_public = root_key.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    anchor = v3trust.RootTrustAnchor(
        root_hash=hashlib.sha256(root_public).hexdigest(),
        root_key_id="root-1",
        public_key=b64encode(root_public).decode("ascii"),
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=120),
        revoked_at=None,
    )
    from src.screening.offensive.v3.contracts.governance import TrustBundle

    bundle = TrustBundle(
        registry_epoch=1,
        predecessor_bundle_hash="0" * 64,
        root_hash=anchor.root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(days=120),
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=2,
    )
    signed_bundle = v3trust.SignedTrustBundle(
        bundle=bundle,
        registry=registry,
        signature=b64encode(root_key.sign(v3trust.trust_bundle_signature_preimage(bundle, registry))).decode("ascii"),
    )
    trust_verifier = v3trust.TrustBundleVerifier((anchor,))
    verifier = v3trust.CapabilityVerifier(trust_verifier, (signed_bundle,))
    current_head = v3trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=1,
        head_version=1,
        store_version=1,
        observed_at=NOW,
    )
    repository = EvidenceRepository(
        database_path=str(tmp_path / "regime-evidence.sqlite3"),
        blob_store=BlobStore(tmp_path / "blobs"),
        verifier=verifier,
        trust_head_provider=_TrustHeadProvider(current_head),
        issuer_namespace=ISSUER_NAMESPACE,
        clock=lambda: NOW,
    )
    signer = _SnapshotSigner(issuer_key, issuer, capability)
    return SimpleNamespace(
        repository=repository,
        signer=signer,
        publisher=RegimeObservationPublisher(repository),
        reader=RegimeObservationReader(repository),
    )


def test_publishes_and_reads_a_normal_observation(rig) -> None:
    observation = _observation()
    snapshot = _snapshot(observation, evidence_id="regime-2026-08-11")
    record = rig.publisher.publish(observation, snapshot, rig.signer)
    assert record.evidence.payload_content_hash == observation.content_hash()

    active = rig.reader.active("regime-2026-08-11", cutoff=NOW + timedelta(hours=2))
    assert isinstance(active, ActiveRegimeObservation)
    assert active.observation.state is RegimeState.NORMAL
    assert active.observation_hash == observation.content_hash()
    assert active.record.commit_sequence == record.commit_sequence


def test_unknown_is_a_committed_policy_fact_not_a_no_run(rig) -> None:
    observation = _observation(
        state=RegimeState.UNKNOWN,
        reason=RegimeObservationReason.MISSING_REQUIRED_INPUT,
        raw_state=None,
    )
    snapshot = _snapshot(observation, evidence_id="regime-unknown-1")
    record = rig.publisher.publish(observation, snapshot, rig.signer)

    active = rig.reader.active("regime-unknown-1", cutoff=NOW + timedelta(hours=2))
    assert active.observation.state is RegimeState.UNKNOWN
    assert active.record.commit_sequence == record.commit_sequence


def test_hash_mismatch_rejects_publication(rig) -> None:
    observation = _observation()
    snapshot = _snapshot(observation, evidence_id="regime-mismatch")
    snapshot = snapshot.model_copy(update={"payload_content_hash": "e" * 64})
    with pytest.raises(RegimeEvidenceError, match="observation_hash_mismatch"):
        rig.publisher.publish(observation, snapshot, rig.signer)


def test_late_or_absent_observation_is_no_run_not_normal(rig) -> None:
    observation = _observation()
    snapshot = _snapshot(observation, evidence_id="regime-late-1")
    rig.publisher.publish(observation, snapshot, rig.signer)
    with pytest.raises(Exception, match="before_cutoff|not_committed"):
        rig.reader.active("regime-late-1", cutoff=NOW - timedelta(hours=1))


def test_reader_rejects_observation_decoding_from_unbound_bytes(rig) -> None:
    observation = _observation()
    snapshot = _snapshot(observation, evidence_id="regime-corrupt-1")
    rig.publisher.publish(observation, snapshot, rig.signer)
    # Corrupt the bound observation blob to non-RegimeObservation bytes.
    blob_path = rig.repository._blobs.blob_path(observation.content_hash())  # noqa: SLF001
    blob_path.write_bytes(b"not a regime observation")
    with pytest.raises(RegimeEvidenceError, match="observation_decode_failed"):
        rig.reader.active("regime-corrupt-1", cutoff=NOW + timedelta(hours=2))
