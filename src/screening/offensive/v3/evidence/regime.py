"""Publish and read canonical regime observations through SnapshotEvidence.

A ``RegimeObservation`` is committed as the payload of an existing
``SnapshotEvidence`` envelope — no fifth evidence kind is added. The publisher
makes the observation bytes durable first, requires the snapshot's
``payload_content_hash`` to bind exactly those bytes, then signs and publishes
the snapshot envelope through the Evidence Store. The reader resolves the active
revision strictly before cutoff, fetches the observation blob by its bound hash,
strict-decodes it, and verifies the observation matches the envelope's PIT
timestamps. It never reads ``regime_history.json``, current caches, or calls the
classifier during historical assessment.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SnapshotEvidence,
)
from src.screening.offensive.v3.contracts.regime import RegimeObservation
from src.screening.offensive.v3.contracts.trust import SignedEnvelope


class RegimeEvidenceError(RuntimeError):
    """Fail-closed rejection of a regime observation store operation."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@runtime_checkable
class RegimeSnapshotSignerPort(Protocol):
    """Signs one SnapshotEvidence envelope over its canonical bytes."""

    def sign_snapshot(self, snapshot: SnapshotEvidence, payload: bytes) -> SignedEnvelope: ...


class RegimeObservationPublisher:
    """Commits one canonical regime observation as a SnapshotEvidence payload."""

    def __init__(self, repository: object) -> None:
        self._repository = repository

    def publish(
        self,
        observation: RegimeObservation,
        snapshot: SnapshotEvidence,
        signer: RegimeSnapshotSignerPort,
    ) -> EvidenceRecord[SnapshotEvidence]:
        """Persist the observation blob, bind it, sign, and publish the snapshot.

        A fault after the observation blob is durably written may leave an orphan
        blob; it may not leave a snapshot envelope pointing at missing bytes,
        because the snapshot is signed and committed only after the blob exists
        and its hash matches ``snapshot.payload_content_hash``.
        """

        if snapshot.evidence_kind != "snapshot":
            raise RegimeEvidenceError(
                "snapshot_kind_mismatch",
                "regime observation must be carried by a SnapshotEvidence envelope",
            )
        observation_bytes = observation.canonical_bytes()
        observation_hash = self._repository.persist_payload(observation_bytes)
        if snapshot.payload_content_hash != observation_hash:
            raise RegimeEvidenceError(
                "observation_hash_mismatch",
                "snapshot payload_content_hash does not bind the observation bytes",
            )
        snapshot_bytes = snapshot.model_dump_json().encode("utf-8")
        signed = signer.sign_snapshot(snapshot, snapshot_bytes)
        return self._repository.publish(signed, snapshot_bytes)


class ActiveRegimeObservation:
    """The PIT-active regime observation bound to its evidence record."""

    def __init__(
        self,
        *,
        record: EvidenceRecord[SnapshotEvidence],
        observation: RegimeObservation,
        observation_hash: str,
    ) -> None:
        self.record = record
        self.observation = observation
        self.observation_hash = observation_hash


class RegimeObservationReader:
    """Reads the PIT-active regime observation for one evidence id."""

    def __init__(self, repository: object) -> None:
        self._repository = repository

    def active(self, evidence_id: str, cutoff: datetime) -> ActiveRegimeObservation:
        """Resolve the active snapshot before cutoff and decode its observation.

        The Evidence Store's active revision (committed strictly before cutoff)
        is the only authority; the observation blob is fetched by the snapshot's
        bound hash, strict-decoded, and cross-checked against the envelope's PIT
        timestamps. A missing, late, or revised-after-cutoff observation yields
        no active record rather than a back-filled ``NORMAL``.
        """

        record = self._repository.active_revision(evidence_id, cutoff)
        snapshot = record.evidence
        if not isinstance(snapshot, SnapshotEvidence):
            raise RegimeEvidenceError(
                "evidence_kind_mismatch",
                "active regime evidence is not a SnapshotEvidence envelope",
                evidence_id=evidence_id,
            )
        observation_bytes = self._repository.raw_payload(snapshot.payload_content_hash)
        try:
            observation = RegimeObservation.model_validate_json(observation_bytes, strict=True)
        except ValidationError as exc:
            raise RegimeEvidenceError(
                "observation_decode_failed",
                "bound observation blob is not a strict RegimeObservation",
                evidence_id=evidence_id,
                reason=str(exc),
            ) from exc
        if observation.effective_at != snapshot.effective_at:
            raise RegimeEvidenceError(
                "observation_effective_at_mismatch",
                "observation effective_at does not match the snapshot envelope",
                evidence_id=evidence_id,
            )
        if observation.observed_at != snapshot.observed_at:
            raise RegimeEvidenceError(
                "observation_observed_at_mismatch",
                "observation observed_at does not match the snapshot envelope",
                evidence_id=evidence_id,
            )
        return ActiveRegimeObservation(
            record=record,
            observation=observation,
            observation_hash=snapshot.payload_content_hash,
        )


__all__ = [
    "ActiveRegimeObservation",
    "RegimeEvidenceError",
    "RegimeObservationPublisher",
    "RegimeObservationReader",
    "RegimeSnapshotSignerPort",
]
