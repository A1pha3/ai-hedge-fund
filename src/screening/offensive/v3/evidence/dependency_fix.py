"""Dependency-fix protocol and research-only importer (Plan 03 Task 7).

Signed dependency-fix manifests declare their fences (plan evidence, trial
manifest, target policy) and their manifest dependencies. All fences must
be acknowledged BEFORE the revision activates, and activation order
follows the dependency graph; an ACK arriving after activation writes
nothing. The research importer converts legacy materials only as
``PRIOR | RESEARCH_RECONSTRUCTION``: broker-mode claims on legacy data are
rejected, and materials must be re-anchored (anchor fingerprint verified)
before ingestion.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from typing import Callable, Final

import sqlalchemy as sa
from pydantic import ValidationError

from src.screening.offensive.v3.contracts import SignedEnvelope
from src.screening.offensive.v3.contracts.base import (
    CanonicalModel,
    ExecutionMode,
)
from src.screening.offensive.v3.contracts.decision import PlanEvidence
from src.screening.offensive.v3.contracts.evidence import (
    OutcomeEvidence,
    SignalEvidence,
    SnapshotEvidence,
)
from src.screening.offensive.v3.evidence.repository import (
    EvidenceRepository,
)

_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS dependency_fix_manifests (
        dependency_fix_id TEXT PRIMARY KEY,
        revision_ordinal INTEGER NOT NULL,
        manifest_json TEXT NOT NULL,
        status TEXT NOT NULL,
        submitted_at TEXT NOT NULL,
        activated_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fence_acks (
        dependency_fix_id TEXT NOT NULL,
        fence_hash TEXT NOT NULL,
        acked_at TEXT NOT NULL,
        PRIMARY KEY (dependency_fix_id, fence_hash)
    )
    """,
)


class DependencyFixError(RuntimeError):
    """Fail-closed rejection of a dependency-fix operation."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class DependencyFixManifest(CanonicalModel):
    """One signed dependency-fix revision declaration."""

    HASH_DOMAIN: str = "ai-hedge-fund.v3.governance.dependency-fix.v1"

    dependency_fix_id: str
    revision_ordinal: int
    plan_evidence_fence: str
    trial_manifest_fence: str
    target_policy_fence: str
    depends_on: tuple[str, ...] = ()

    def fences(self) -> tuple[str, ...]:
        return (
            self.plan_evidence_fence,
            self.trial_manifest_fence,
            self.target_policy_fence,
        )


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


class DependencyFixLedger:
    """Fence ACKs and dependency-ordered activation of revisions."""

    def __init__(
        self,
        database_path: str,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._clock = clock
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        sa.event.listen(self._engine, "connect", _configure_connection)
        with self._engine.begin() as conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(sa.text(ddl))

    def submit(
        self, manifest: DependencyFixManifest, signed: SignedEnvelope
    ) -> None:
        """Register one signed dependency-fix manifest (PENDING)."""

        if hashlib.sha256(
            manifest.model_dump_json().encode("utf-8")
        ).hexdigest() != signed.payload_hash:
            raise DependencyFixError(
                "manifest_signature_mismatch",
                "signed payload hash does not bind this manifest",
            )
        with self._engine.begin() as conn:
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO dependency_fix_manifests ("
                        " dependency_fix_id, revision_ordinal,"
                        " manifest_json, status, submitted_at)"
                        " VALUES (:id, :ordinal, :json, 'PENDING',"
                        " :submitted_at)"
                    ),
                    {
                        "id": manifest.dependency_fix_id,
                        "ordinal": manifest.revision_ordinal,
                        "json": manifest.model_dump_json(),
                        "submitted_at": self._clock().isoformat(),
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise DependencyFixError(
                    "manifest_already_submitted",
                    "dependency fix id already submitted",
                ) from exc

    def _manifest_row(self, conn, dependency_fix_id: str):
        row = conn.execute(
            sa.text(
                "SELECT * FROM dependency_fix_manifests"
                " WHERE dependency_fix_id = :id"
            ),
            {"id": dependency_fix_id},
        ).first()
        if row is None:
            raise DependencyFixError(
                "manifest_unknown", "unknown dependency fix id"
            )
        return row

    def acknowledge_fence(
        self, dependency_fix_id: str, fence_hash: str
    ) -> bool:
        """ACK one fence before activation.

        An ACK after the revision already activated writes nothing
        (returns False); an ACK for an unknown fence is rejected.
        """

        with self._engine.begin() as conn:
            row = self._manifest_row(conn, dependency_fix_id)
            if str(row.status) == "ACTIVE":
                return False
            manifest = DependencyFixManifest.model_validate_json(
                str(row.manifest_json)
            )
            if fence_hash not in manifest.fences():
                raise DependencyFixError(
                    "fence_unknown",
                    "fence is not declared by this manifest",
                )
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO fence_acks (dependency_fix_id,"
                        " fence_hash, acked_at) VALUES (:id, :fence,"
                        " :acked_at)"
                    ),
                    {
                        "id": dependency_fix_id,
                        "fence": fence_hash,
                        "acked_at": self._clock().isoformat(),
                    },
                )
            except sa.exc.IntegrityError:
                return True  # already acknowledged
        return True

    def activate(self, dependency_fix_id: str) -> None:
        """Activate one revision: every fence ACKed, every dependency
        already ACTIVE. Activation order follows the dependency graph."""

        activated_at = self._clock()
        with self._engine.begin() as conn:
            row = self._manifest_row(conn, dependency_fix_id)
            if str(row.status) == "ACTIVE":
                return  # idempotent
            manifest = DependencyFixManifest.model_validate_json(
                str(row.manifest_json)
            )
            acked = {
                ack_row.fence_hash
                for ack_row in conn.execute(
                    sa.text(
                        "SELECT fence_hash FROM fence_acks"
                        " WHERE dependency_fix_id = :id"
                    ),
                    {"id": dependency_fix_id},
                )
            }
            missing = [
                fence
                for fence in manifest.fences()
                if fence not in acked
            ]
            if missing:
                raise DependencyFixError(
                    "fence_ack_missing",
                    "all fences must be acknowledged before activation",
                    missing_fences=missing,
                )
            for dependency_id in manifest.depends_on:
                dependency_row = self._manifest_row(conn, dependency_id)
                if str(dependency_row.status) != "ACTIVE":
                    raise DependencyFixError(
                        "dependency_not_active",
                        "activation order must follow the dependency"
                        " graph",
                        dependency_id=dependency_id,
                    )
            conn.execute(
                sa.text(
                    "UPDATE dependency_fix_manifests SET status = 'ACTIVE',"
                    " activated_at = :activated_at"
                    " WHERE dependency_fix_id = :id"
                ),
                {
                    "activated_at": activated_at.isoformat(),
                    "id": dependency_fix_id,
                },
            )

    def status(self, dependency_fix_id: str) -> str:
        with self._engine.connect() as conn:
            row = self._manifest_row(conn, dependency_fix_id)
        return str(row.status)


class ActivationGate:
    """Port the Plan 04 Gateway replaces.

    Evidence revisions may activate only while their bound dependency-fix
    manifest is ACTIVE (all fences ACKed, dependencies active). A
    fence-without-activation may overblock but never underblock.
    """

    def require_activation_allowed(self, fence_manifest_id: str) -> None:
        raise NotImplementedError


class FenceActivationGate(ActivationGate):
    """Fence ACK gate over the DependencyFixLedger."""

    def __init__(self, ledger: DependencyFixLedger) -> None:
        self._ledger = ledger

    def require_activation_allowed(self, fence_manifest_id: str) -> None:
        if self._ledger.status(fence_manifest_id) != "ACTIVE":
            raise DependencyFixError(
                "fence_not_active",
                "revision activation requires an ACTIVE dependency-fix"
                " manifest (all fence ACKs, dependencies active)",
                fence_manifest_id=fence_manifest_id,
            )


class ResearchImporterError(RuntimeError):
    """Fail-closed rejection of a legacy research import."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class ResearchImporter:
    """Imports legacy materials as PRIOR | RESEARCH_RECONSTRUCTION only.

    Legacy data carries no broker authority: ``BROKER_CONFIRMED`` claims
    are rejected, and every material must be re-anchored (the caller's
    anchor fingerprint must match the imported payload) and re-verified
    before ingestion.
    """

    def __init__(
        self,
        evidence_repository: EvidenceRepository,
        *,
        signer: Callable[[bytes], SignedEnvelope],
        clock: Callable[[], datetime],
    ) -> None:
        self._evidence = evidence_repository
        self._signer = signer
        self._clock = clock

    def import_prior_research(
        self,
        *,
        legacy_payload: bytes,
        anchor_fingerprint: str,
        expected_anchor_fingerprint: str,
    ) -> str:
        """Convert one legacy material into store truth.

        The legacy payload must decode as a strict evidence envelope whose
        mode is RESEARCH_RECONSTRUCTION; the re-anchoring fingerprint must
        match before ingestion.
        """

        from pydantic import TypeAdapter

        if anchor_fingerprint != expected_anchor_fingerprint:
            raise ResearchImporterError(
                "anchor_mismatch",
                "legacy material must be re-anchored and re-verified"
                " before ingestion",
            )
        adapter = TypeAdapter(
            SnapshotEvidence
            | SignalEvidence
            | OutcomeEvidence
            | PlanEvidence
        )
        try:
            envelope = adapter.validate_json(legacy_payload, strict=True)
        except ValidationError as exc:
            raise ResearchImporterError(
                "legacy_payload_invalid",
                "legacy payload is not a strict evidence envelope",
            ) from exc
        if envelope.mode is not ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ResearchImporterError(
                "legacy_broker_claim_rejected",
                "legacy materials are PRIOR | RESEARCH_RECONSTRUCTION"
                " only; broker-mode claims are forbidden",
            )
        signed = self._signer(legacy_payload)
        record = self._evidence.publish(signed, legacy_payload)
        return record.evidence.evidence_id


__all__ = [
    "ActivationGate",
    "DependencyFixError",
    "DependencyFixLedger",
    "DependencyFixManifest",
    "FenceActivationGate",
    "ResearchImporter",
    "ResearchImporterError",
]
