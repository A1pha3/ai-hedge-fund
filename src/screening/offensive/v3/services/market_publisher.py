"""Plan 05 Task 2: MarketPublisherService — thin snapshot-publishing adapter.

Wraps the Plan 03 ``EvidenceRepository`` and only ever publishes/queries
**snapshot** evidence under this service's own issuer namespace. The store
still owns ``ingested_at``, commit sequence, the revision/supersedes chain
and the PIT active projection; this adapter only shapes the payload, signs
it with the injected signer (declaring ``ArtifactKind.SNAPSHOT`` and this
service's issuer namespace), and delegates.

Import boundary: this module must NOT import ``capital``, ``gateway`` or
``execution`` modules (a capability-matrix test scans the source).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Final

from src.screening.offensive.v3.contracts import ArtifactKind, SignedEnvelope
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SnapshotEvidence,
)
from src.screening.offensive.v3.contracts.ports import ActiveEvidenceRecord
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.repository import (
    EvidenceRepository,
    EvidenceStoreError,
    TrustHeadProvider,
    VerifierProtocol,
)

NOT_A_SNAPSHOT_ERROR_CODE: Final[str] = "not_a_snapshot"
"""Stable error code for a non-snapshot envelope passed to publish_snapshot."""


class MarketPublisherService:
    """Owns one snapshot evidence namespace; publishes and queries snapshots only."""

    def __init__(
        self,
        *,
        database_path: str,
        blob_store: BlobStore,
        verifier: VerifierProtocol,
        trust_head_provider: TrustHeadProvider,
        issuer_namespace: str,
        clock: Callable[[], datetime],
        signer: Callable[[bytes], SignedEnvelope],
    ) -> None:
        """Construct the service over one writable evidence namespace.

        The service builds its own ``EvidenceRepository`` over
        ``database_path`` / ``blob_store`` with the given verifier and
        trust-head provider; ``signer`` signs every published payload
        declaring ``ArtifactKind.SNAPSHOT`` and ``issuer_namespace``.
        """
        self._signer = signer
        self._issuer_namespace = issuer_namespace
        self._repository = EvidenceRepository(
            database_path=database_path,
            blob_store=blob_store,
            verifier=verifier,
            trust_head_provider=trust_head_provider,
            issuer_namespace=issuer_namespace,
            clock=clock,
        )

    def publish_snapshot(
        self, snapshot: SnapshotEvidence
    ) -> EvidenceRecord[SnapshotEvidence]:
        """Publish one snapshot envelope under this service's namespace.

        Fail-closed guards:
        - an envelope whose ``evidence_kind != "snapshot"`` is rejected with
          an ``EvidenceStoreError`` (code ``NOT_A_SNAPSHOT_ERROR_CODE``);
        - the payload is ``snapshot.model_dump_json().encode()``, signed with
          the injected signer (artifact ``ArtifactKind.SNAPSHOT``, namespace
          = this service's issuer namespace), then published through the
          underlying ``EvidenceRepository.publish``.
        """
        if snapshot.evidence_kind != "snapshot":
            raise EvidenceStoreError(
                NOT_A_SNAPSHOT_ERROR_CODE,
                "market publisher accepts snapshot evidence only",
                evidence_kind=snapshot.evidence_kind,
            )
        payload = snapshot.model_dump_json().encode("utf-8")
        signed = self._signer(payload)
        return self._repository.publish(signed, payload)

    def active_snapshot(
        self, evidence_id: str, cutoff: datetime
    ) -> ActiveEvidenceRecord:
        """The snapshot active at the cutoff instant (PIT projection).

        Delegates to ``EvidenceRepository.active_revision``; later
        ingestions or activations are invisible at earlier cutoffs.
        """
        return self._repository.active_revision(evidence_id, cutoff)

    def raw_payload(self, content_hash: str) -> bytes:
        """Raw producer payload bytes by content hash (blob store read)."""
        return self._repository.raw_payload(content_hash)


__all__ = ["MarketPublisherService", "NOT_A_SNAPSHOT_ERROR_CODE"]
