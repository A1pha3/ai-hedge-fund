"""Plan 03 Task 7: dependency-fix protocol and research-only importer."""

from __future__ import annotations

import hashlib
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3 import trust
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    SUPPORTED_SCHEMA_MAJOR,
    canonical_json_bytes,
)
from src.screening.offensive.v3.contracts.base import EvidenceScope
from src.screening.offensive.v3.contracts.evidence import (
    ProviderPublicationState,
    SnapshotEvidence,
)
from src.screening.offensive.v3.contracts.governance import TrustBundle
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.dependency_fix import (
    DependencyFixError,
    DependencyFixLedger,
    DependencyFixManifest,
    ResearchImporter,
    ResearchImporterError,
)
from src.screening.offensive.v3.evidence.repository import (
    EvidenceRepository,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
OBSERVED = NOW - timedelta(days=30)
AVAILABLE = NOW + timedelta(days=1)
HASH = "e" * 64
NAMESPACE = "prior.research.importer"


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


def _public_key_b64(private_key) -> str:
    from cryptography.hazmat.primitives import serialization

    return b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")


def _root_context(registry):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    root_key = Ed25519PrivateKey.generate()
    root_public = _public_key_b64(root_key)
    from cryptography.hazmat.primitives import serialization

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
    def __init__(self, tmp_path: Path) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        self.clock = _Clock(NOW)
        self.snapshot_key = Ed25519PrivateKey.generate()
        capability = trust.Capability(
            artifact=trust.ArtifactKind.SNAPSHOT,
            namespace=NAMESPACE,
            mode=ExecutionMode.RESEARCH_RECONSTRUCTION,
            schema_major=SUPPORTED_SCHEMA_MAJOR,
            capability_version="prior-research-publisher.v1",
            scope="prior.research:importer",
            valid_from=NOW - timedelta(days=1),
            valid_until=NOW + timedelta(days=1),
            revoked_at=None,
        )
        issuer = trust.TrustedIssuer(
            issuer_id="prior.research.importer",
            key_id="importer-key-1",
            issuer_kind=trust.IssuerKind.MARKET_PUBLISHER,
            public_key=_public_key_b64(self.snapshot_key),
            valid_from=NOW - timedelta(days=1),
            valid_until=NOW + timedelta(days=1),
            revoked_at=None,
            capabilities=(capability,),
        )
        verifier, head_provider = _root_context(
            trust.TrustedRegistry(issuers=(issuer,))
        )
        self.evidence = EvidenceRepository(
            database_path=str(tmp_path / "evidence.sqlite3"),
            blob_store=BlobStore(tmp_path / "blobs"),
            verifier=verifier,
            trust_head_provider=head_provider,
            issuer_namespace=NAMESPACE,
            clock=self.clock,
        )
        self._capability = capability
        self.importer = ResearchImporter(
            self.evidence,
            signer=self._sign,
            clock=self.clock,
        )
        self.ledger = DependencyFixLedger(
            str(tmp_path / "dependency.sqlite3"),
            clock=self.clock,
        )

    def _sign(self, payload: bytes):
        digest = hashlib.sha256(payload).hexdigest()
        protected = canonical_json_bytes(
            {
                "artifact": self._capability.artifact,
                "capability_scope": self._capability.scope,
                "capability_version": self._capability.capability_version,
                "issuer_id": "prior.research.importer",
                "key_id": "importer-key-1",
                "mode": self._capability.mode,
                "namespace": self._capability.namespace,
                "payload": b64encode(payload).decode("ascii"),
                "payload_hash": digest,
                "schema_major": self._capability.schema_major,
            }
        )
        signature = self.snapshot_key.sign(protected)
        return trust.SignedEnvelope(
            issuer_id="prior.research.importer",
            key_id="importer-key-1",
            schema_major=self._capability.schema_major,
            artifact=self._capability.artifact,
            namespace=self._capability.namespace,
            mode=self._capability.mode,
            capability_version=self._capability.capability_version,
            capability_scope=self._capability.scope,
            payload_hash=digest,
            payload=payload,
            signature=b64encode(signature).decode("ascii"),
        )

    def legacy_snapshot(self, evidence_id="legacy-1", mode=None):
        return SnapshotEvidence(
            evidence_id=evidence_id,
            subject_scope=EvidenceScope.GLOBAL,
            subject_producer="legacy.paper-trading",
            family_id=None,
            strategy_semver="2.9.0",
            behavior_fingerprint=HASH,
            policy_epoch=1,
            execution_version="legacy-close-to-close.v0",
            cost_version="zero-cost.v0",
            effective_at=OBSERVED,
            provider_published_at=OBSERVED,
            observed_at=OBSERVED,
            available_at=AVAILABLE,
            mode=(
                mode
                if mode is not None
                else ExecutionMode.RESEARCH_RECONSTRUCTION
            ),
            source_authority="legacy.journal",
            payload_content_hash=HASH,
            schema_major=SUPPORTED_SCHEMA_MAJOR,
            evidence_kind="snapshot",
        )


@pytest.fixture()
def world(tmp_path: Path) -> _World:
    return _World(tmp_path)


def _manifest(
    dependency_fix_id="fix-1",
    *,
    depends_on=(),
    plan_fence="a" * 64,
    trial_fence="b" * 64,
    target_fence="c" * 64,
) -> DependencyFixManifest:
    return DependencyFixManifest(
        dependency_fix_id=dependency_fix_id,
        revision_ordinal=1,
        plan_evidence_fence=plan_fence,
        trial_manifest_fence=trial_fence,
        target_policy_fence=target_fence,
        depends_on=tuple(depends_on),
    )


def _signed_manifest(world, manifest):
    payload = manifest.model_dump_json().encode("utf-8")
    return world._sign(payload)


def test_activation_requires_all_fence_acks(world: _World) -> None:
    manifest = _manifest()
    world.ledger.submit(manifest, _signed_manifest(world, manifest))
    world.ledger.acknowledge_fence("fix-1", manifest.plan_evidence_fence)
    world.ledger.acknowledge_fence("fix-1", manifest.trial_manifest_fence)
    # Target policy fence still unacknowledged: activation is rejected.
    with pytest.raises(DependencyFixError) as excinfo:
        world.ledger.activate("fix-1")
    assert excinfo.value.code == "fence_ack_missing"
    world.ledger.acknowledge_fence("fix-1", manifest.target_policy_fence)
    world.ledger.activate("fix-1")
    assert world.ledger.status("fix-1") == "ACTIVE"


def test_unknown_fence_ack_is_rejected(world: _World) -> None:
    manifest = _manifest()
    world.ledger.submit(manifest, _signed_manifest(world, manifest))
    with pytest.raises(DependencyFixError) as excinfo:
        world.ledger.acknowledge_fence("fix-1", "f" * 64)
    assert excinfo.value.code == "fence_unknown"


def test_activation_follows_dependency_order(world: _World) -> None:
    parent = _manifest("fix-parent")
    child = _manifest("fix-child", depends_on=("fix-parent",))
    world.ledger.submit(parent, _signed_manifest(world, parent))
    world.ledger.submit(child, _signed_manifest(world, child))
    for fence in child.fences():
        world.ledger.acknowledge_fence("fix-child", fence)
    # The dependency is not ACTIVE yet: the child cannot activate.
    with pytest.raises(DependencyFixError) as excinfo:
        world.ledger.activate("fix-child")
    assert excinfo.value.code == "dependency_not_active"
    for fence in parent.fences():
        world.ledger.acknowledge_fence("fix-parent", fence)
    world.ledger.activate("fix-parent")
    world.ledger.activate("fix-child")
    assert world.ledger.status("fix-child") == "ACTIVE"


def test_ack_after_activation_writes_nothing(world: _World) -> None:
    manifest = _manifest()
    world.ledger.submit(manifest, _signed_manifest(world, manifest))
    for fence in manifest.fences():
        world.ledger.acknowledge_fence("fix-1", fence)
    world.ledger.activate("fix-1")
    # An ACK after activation is idempotent: nothing is written.
    assert world.ledger.acknowledge_fence(
        "fix-1", manifest.plan_evidence_fence
    ) is False


def test_legacy_import_is_prior_research_reconstruction_only(
    world: _World,
) -> None:
    envelope = world.legacy_snapshot()
    payload = envelope.model_dump_json().encode("utf-8")
    fingerprint = hashlib.sha256(payload).hexdigest()
    evidence_id = world.importer.import_prior_research(
        legacy_payload=payload,
        anchor_fingerprint=fingerprint,
        expected_anchor_fingerprint=fingerprint,
    )
    record = world.evidence.get(evidence_id)
    assert record.evidence.mode is ExecutionMode.RESEARCH_RECONSTRUCTION
    assert record.revision == 1


def test_legacy_broker_claim_is_rejected(world: _World) -> None:
    envelope = world.legacy_snapshot(
        evidence_id="legacy-broker",
        mode=ExecutionMode.BROKER_CONFIRMED,
    )
    payload = envelope.model_dump_json().encode("utf-8")
    fingerprint = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ResearchImporterError) as excinfo:
        world.importer.import_prior_research(
            legacy_payload=payload,
            anchor_fingerprint=fingerprint,
            expected_anchor_fingerprint=fingerprint,
        )
    assert excinfo.value.code == "legacy_broker_claim_rejected"


def test_anchor_mismatch_is_rejected(world: _World) -> None:
    envelope = world.legacy_snapshot(evidence_id="legacy-anchor")
    payload = envelope.model_dump_json().encode("utf-8")
    fingerprint = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ResearchImporterError) as excinfo:
        world.importer.import_prior_research(
            legacy_payload=payload,
            anchor_fingerprint=fingerprint,
            expected_anchor_fingerprint="0" * 64,
        )
    assert excinfo.value.code == "anchor_mismatch"


def test_manifest_signature_mismatch_is_rejected(world: _World) -> None:
    manifest = _manifest("fix-bad-sig")
    other = _signed_manifest(world, _manifest("fix-other"))
    with pytest.raises(DependencyFixError) as excinfo:
        world.ledger.submit(manifest, other)
    assert excinfo.value.code == "manifest_signature_mismatch"


def test_crash_before_activation_keeps_revision_pending(
    world: _World, tmp_path: Path
) -> None:
    """A crash between submit/ack and activation never leaves the
    revision active: reopening the store shows the durable state."""

    manifest = _manifest("fix-crash")
    world.ledger.submit(manifest, _signed_manifest(world, manifest))
    for fence in manifest.fences():
        world.ledger.acknowledge_fence("fix-crash", fence)
    # Simulate a crash before activation: drop the handle, reopen.
    reopened = DependencyFixLedger(
        str(tmp_path / "dependency.sqlite3"), clock=world.clock
    )
    assert reopened.status("fix-crash") == "PENDING"
    # Fence ACKs survived the crash and activation still works.
    reopened.activate("fix-crash")
    assert reopened.status("fix-crash") == "ACTIVE"


def test_duplicate_fence_ack_is_idempotent(world: _World) -> None:
    manifest = _manifest("fix-dup")
    world.ledger.submit(manifest, _signed_manifest(world, manifest))
    assert world.ledger.acknowledge_fence(
        "fix-dup", manifest.plan_evidence_fence
    ) is True
    assert world.ledger.acknowledge_fence(
        "fix-dup", manifest.plan_evidence_fence
    ) is True  # nothing written the second time


def test_repeat_activation_is_idempotent(world: _World) -> None:
    manifest = _manifest("fix-repeat")
    world.ledger.submit(manifest, _signed_manifest(world, manifest))
    for fence in manifest.fences():
        world.ledger.acknowledge_fence("fix-repeat", fence)
    world.ledger.activate("fix-repeat")
    world.ledger.activate("fix-repeat")  # old status: no-op
    assert world.ledger.status("fix-repeat") == "ACTIVE"
