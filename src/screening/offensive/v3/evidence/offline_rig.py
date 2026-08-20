"""Offline ephemeral evidence rig — shared by tests and offline seeders (2026-08-20).

Builds a self-contained trust chain (root anchor → signed trust bundle →
capability verifier) plus an ``EvidenceRepository`` and publishers over one
writable namespace. The signer is an **ephemeral in-process key**: acceptable
only for offline primitives and tests (same owner-approved shadow-ephemeral
deviation as the Plan 05 CLI). It is NOT a production identity and confers no
authority.

Never import this from kernel/gateway/execution paths; evidence-layer tooling
only.
"""

from __future__ import annotations

import hashlib
from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.screening.offensive.v3 import trust as v3trust
from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.contracts.evidence import SUPPORTED_SCHEMA_MAJOR
from src.screening.offensive.v3.contracts.governance import TrustBundle
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.market_bars import MarketBarSetPublisher
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.evidence.trading_schedule import TradingSchedulePublisher
from src.screening.offensive.v3.trust import SignedEnvelope, canonical_json_bytes

_VALID_FROM_HOURS = 24.0
_VALID_UNTIL_DAYS = 120


class _Signer:
    def __init__(self, key: Ed25519PrivateKey, issuer: object, capability: object) -> None:
        self._key, self._issuer, self._capability = key, issuer, capability

    def __call__(self, payload: bytes) -> SignedEnvelope:
        payload_hash = hashlib.sha256(payload).hexdigest()
        protected = canonical_json_bytes(
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
    def __init__(self, head: object) -> None:
        self._head = head

    def current_trust_head(self, trusted_at: datetime) -> object:
        return self._head


@dataclass(frozen=True)
class OfflineEvidenceRig:
    """One writable namespace + publishers over an ephemeral trust chain."""

    repository: EvidenceRepository
    signer: Callable[[bytes], SignedEnvelope]
    clock: Callable[[], datetime]

    @property
    def schedule_publisher(self) -> TradingSchedulePublisher:
        return TradingSchedulePublisher(
            repository=self.repository, clock=self.clock, signer=self.signer
        )

    @property
    def bar_publisher(self) -> MarketBarSetPublisher:
        return MarketBarSetPublisher(
            repository=self.repository, clock=self.clock, signer=self.signer
        )


def build_offline_evidence_rig(
    *,
    database_path: Path,
    blobs_dir: Path,
    namespace: str,
    clock: Callable[[], datetime] | None = None,
    trust_now: datetime | None = None,
) -> OfflineEvidenceRig:
    """Build one rig; ``trust_now`` anchors the ephemeral trust windows.

    信任窗 (anchor/issuer/bundle) 默认锚在真实墙钟; 需要冻结仓库时钟的
    测试 (跨命名空间与其他固定窗口信任链共库, 如 session_batch) 传
    ``trust_now`` 把窗口锚到同一时基 — 否则冻结钟早于真实锚点会被
    "root key is not yet valid" 拒绝。默认行为不变。
    """
    now = trust_now if trust_now is not None else datetime.now(timezone.utc)
    valid_from = now - timedelta(hours=_VALID_FROM_HOURS)
    valid_until = now + timedelta(days=_VALID_UNTIL_DAYS)

    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    capability = v3trust.Capability(
        artifact=v3trust.ArtifactKind.SNAPSHOT,
        namespace=namespace,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        capability_version="offline.snapshot.v1",
        scope=f"global:{namespace}",
        valid_from=valid_from,
        valid_until=valid_until,
        revoked_at=None,
    )
    issuer = v3trust.TrustedIssuer(
        issuer_id="offline-ephemeral.service",
        key_id=f"{namespace}-key-1",
        issuer_kind=v3trust.IssuerKind.MARKET_PUBLISHER,
        public_key=b64encode(public).decode("ascii"),
        valid_from=valid_from,
        valid_until=valid_until,
        revoked_at=None,
        capabilities=(capability,),
    )
    registry = v3trust.TrustedRegistry(issuers=(issuer,))
    root_key = Ed25519PrivateKey.generate()
    root_public = root_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    anchor = v3trust.RootTrustAnchor(
        root_hash=hashlib.sha256(root_public).hexdigest(),
        root_key_id="offline-root-1",
        public_key=b64encode(root_public).decode("ascii"),
        valid_from=valid_from,
        valid_until=valid_until,
        revoked_at=None,
    )
    bundle = TrustBundle(
        registry_epoch=1,
        predecessor_bundle_hash="0" * 64,
        root_hash=anchor.root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=valid_from,
        expires_at=valid_until,
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=SUPPORTED_SCHEMA_MAJOR,
    )
    signed_bundle = v3trust.SignedTrustBundle(
        bundle=bundle,
        registry=registry,
        signature=b64encode(
            root_key.sign(v3trust.trust_bundle_signature_preimage(bundle, registry))
        ).decode("ascii"),
    )
    head = v3trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=1,
        head_version=1,
        store_version=1,
        observed_at=now,
    )
    if clock is None:
        clock = lambda: now  # noqa: E731 - frozen offline rig clock
    repository = EvidenceRepository(
        database_path=str(database_path),
        blob_store=BlobStore(blobs_dir),
        verifier=v3trust.CapabilityVerifier(v3trust.TrustBundleVerifier((anchor,)), (signed_bundle,)),
        trust_head_provider=_TrustHeadProvider(head),
        issuer_namespace=namespace,
        clock=clock,
    )
    return OfflineEvidenceRig(repository=repository, signer=_Signer(key, issuer, capability), clock=clock)


__all__ = ["OfflineEvidenceRig", "build_offline_evidence_rig"]
