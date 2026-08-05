"""Governance authority store primitives (Plan 03 Task 2).

Scope: attempt reservation sealed atomically with the Trial/SAP manifests
and the target ``PolicySnapshot`` registration. Everything here is
governance truth, never execution authority: the registered target policy
is explicitly non-executable until a Plan 06 authorization envelope says
so, and the sealed trial is immutable once committed.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Callable, Final

import sqlalchemy as sa
from pydantic import ValidationError

from src.screening.offensive.v3.contracts.governance import (
    StatisticalAnalysisPlan,
    TrialManifest,
)

_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS trial_attempts (
        attempt_budget_reservation_id TEXT PRIMARY KEY,
        research_program_id TEXT NOT NULL,
        economic_lineage_id TEXT NOT NULL,
        stage_id TEXT NOT NULL,
        trial_id TEXT NOT NULL,
        sealed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sealed_trials (
        trial_id TEXT PRIMARY KEY,
        research_program_id TEXT NOT NULL,
        economic_lineage_id TEXT NOT NULL,
        role TEXT NOT NULL,
        trial_manifest_hash TEXT NOT NULL,
        trial_manifest_json TEXT NOT NULL,
        sap_manifest_hash TEXT NOT NULL,
        sap_manifest_json TEXT NOT NULL,
        attempt_budget_reservation_id TEXT NOT NULL,
        sealed_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_sealed_trial_lineage_role
    ON sealed_trials (research_program_id, economic_lineage_id, role)
    """,
    """
    CREATE TABLE IF NOT EXISTS target_policy_registrations (
        target_policy_snapshot_registration_hash TEXT PRIMARY KEY,
        policy_snapshot_json TEXT NOT NULL,
        policy_fingerprint TEXT NOT NULL,
        executable INTEGER NOT NULL DEFAULT 0,
        registered_at TEXT NOT NULL
    )
    """,
    "CREATE TRIGGER IF NOT EXISTS no_update_sealed_trials "
    "BEFORE UPDATE ON sealed_trials "
    "BEGIN SELECT RAISE(ABORT, 'immutable table: sealed_trials rejects "
    "UPDATE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_delete_sealed_trials "
    "BEFORE DELETE ON sealed_trials "
    "BEGIN SELECT RAISE(ABORT, 'immutable table: sealed_trials rejects "
    "DELETE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_update_trial_attempts "
    "BEFORE UPDATE ON trial_attempts "
    "BEGIN SELECT RAISE(ABORT, 'immutable table: trial_attempts rejects "
    "UPDATE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_delete_trial_attempts "
    "BEFORE DELETE ON trial_attempts "
    "BEGIN SELECT RAISE(ABORT, 'immutable table: trial_attempts rejects "
    "DELETE'); END;",
)


class GovernanceStoreError(RuntimeError):
    """Fail-closed rejection of a governance store operation."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class TrialSealRequest:
    """One atomic attempt-reservation + trial/SAP seal + policy registration.

    Plain dataclass-style container: the manifests are strict Plan 01
    governance artifacts; the store revalidates them on seal.
    """

    def __init__(
        self,
        *,
        attempt_budget_reservation_id: str,
        stage_id: str,
        role: str,
        trial_manifest: TrialManifest,
        sap_manifest: StatisticalAnalysisPlan,
        policy_snapshot_json: str,
        policy_fingerprint: str,
        target_policy_snapshot_registration_hash: str,
        expected_signal_cutoff: datetime,
    ) -> None:
        self.attempt_budget_reservation_id = attempt_budget_reservation_id
        self.stage_id = stage_id
        self.role = role
        self.trial_manifest = trial_manifest
        self.sap_manifest = sap_manifest
        self.policy_snapshot_json = policy_snapshot_json
        self.policy_fingerprint = policy_fingerprint
        self.target_policy_snapshot_registration_hash = (
            target_policy_snapshot_registration_hash
        )
        self.expected_signal_cutoff = expected_signal_cutoff


class TrialSealReceipt:
    """The committed seal identity."""

    def __init__(
        self,
        *,
        trial_id: str,
        attempt_budget_reservation_id: str,
        trial_manifest_hash: str,
        sap_manifest_hash: str,
        target_policy_snapshot_registration_hash: str,
        sealed_at: datetime,
    ) -> None:
        self.trial_id = trial_id
        self.attempt_budget_reservation_id = attempt_budget_reservation_id
        self.trial_manifest_hash = trial_manifest_hash
        self.sap_manifest_hash = sap_manifest_hash
        self.target_policy_snapshot_registration_hash = (
            target_policy_snapshot_registration_hash
        )
        self.sealed_at = sealed_at


class GovernanceRepository:
    """One governance namespace's trial/target store."""

    def __init__(
        self,
        *,
        database_path: str,
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

    def reserve_attempt_and_seal_trial(
        self, request: TrialSealRequest
    ) -> TrialSealReceipt:
        """Atomically reserve the attempt and seal the trial/SAP/target.

        Either every row commits or none does: a conflict anywhere rolls
        the whole governance transaction back. The sealed manifests must
        be frozen before the trial's first signal cutoff.
        """

        trial = request.trial_manifest
        sap = request.sap_manifest
        sealed_at = self._clock()
        if trial.trial_manifest_sealed_at > request.expected_signal_cutoff:
            raise GovernanceStoreError(
                "seal_after_signal_cutoff",
                "trial manifest must be sealed before the signal cutoff",
            )
        if sap.trial_manifest_hash != trial.artifact_hash():
            raise GovernanceStoreError(
                "sap_trial_mismatch",
                "SAP does not bind the trial manifest being sealed",
            )
        if trial.trial_id != sap.sap_id and (
            trial.research_program_id != sap.research_program_id
            or trial.economic_lineage_id != sap.economic_lineage_id
        ):
            raise GovernanceStoreError(
                "sap_lineage_mismatch",
                "SAP program/lineage differs from the trial manifest",
            )
        if trial.target_portfolio_policy_fingerprint != (
            request.policy_fingerprint
        ):
            raise GovernanceStoreError(
                "target_policy_fingerprint_mismatch",
                "registered target policy differs from the trial target",
            )
        with self._engine.begin() as conn:
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO trial_attempts ("
                        " attempt_budget_reservation_id,"
                        " research_program_id, economic_lineage_id,"
                        " stage_id, trial_id, sealed_at)"
                        " VALUES (:attempt, :program, :lineage, :stage,"
                        " :trial, :sealed_at)"
                    ),
                    {
                        "attempt": request.attempt_budget_reservation_id,
                        "program": trial.research_program_id,
                        "lineage": trial.economic_lineage_id,
                        "stage": request.stage_id,
                        "trial": trial.trial_id,
                        "sealed_at": sealed_at.isoformat(),
                    },
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO sealed_trials (trial_id,"
                        " research_program_id, economic_lineage_id, role,"
                        " trial_manifest_hash, trial_manifest_json,"
                        " sap_manifest_hash, sap_manifest_json,"
                        " attempt_budget_reservation_id, sealed_at)"
                        " VALUES (:trial, :program, :lineage, :role,"
                        " :trial_hash, :trial_json, :sap_hash, :sap_json,"
                        " :attempt, :sealed_at)"
                    ),
                    {
                        "trial": trial.trial_id,
                        "program": trial.research_program_id,
                        "lineage": trial.economic_lineage_id,
                        "role": request.role,
                        "trial_hash": trial.artifact_hash(),
                        "trial_json": trial.model_dump_json(),
                        "sap_hash": sap.artifact_hash(),
                        "sap_json": sap.model_dump_json(),
                        "attempt": request.attempt_budget_reservation_id,
                        "sealed_at": sealed_at.isoformat(),
                    },
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO target_policy_registrations ("
                        " target_policy_snapshot_registration_hash,"
                        " policy_snapshot_json, policy_fingerprint,"
                        " executable, registered_at)"
                        " VALUES (:hash, :json, :fingerprint, 0, :at)"
                    ),
                    {
                        "hash": (
                            request
                            .target_policy_snapshot_registration_hash
                        ),
                        "json": request.policy_snapshot_json,
                        "fingerprint": request.policy_fingerprint,
                        "at": sealed_at.isoformat(),
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise GovernanceStoreError(
                    "trial_seal_conflict",
                    "attempt, trial role or target registration already"
                    " committed; the whole seal rolled back",
                    reason=str(exc),
                ) from exc
            except ValidationError as exc:
                raise GovernanceStoreError(
                    "manifest_rejected",
                    "governance manifest failed strict revalidation",
                    reason=str(exc),
                ) from exc
        return TrialSealReceipt(
            trial_id=trial.trial_id,
            attempt_budget_reservation_id=(
                request.attempt_budget_reservation_id
            ),
            trial_manifest_hash=trial.artifact_hash(),
            sap_manifest_hash=sap.artifact_hash(),
            target_policy_snapshot_registration_hash=(
                request.target_policy_snapshot_registration_hash
            ),
            sealed_at=sealed_at,
        )

    def sealed_trial(self, trial_id: str) -> dict[str, object]:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT * FROM sealed_trials WHERE trial_id = :trial"
                ),
                {"trial": trial_id},
            ).first()
        if row is None:
            raise GovernanceStoreError(
                "trial_unknown", "no sealed trial for id", trial_id=trial_id
            )
        return dict(row._mapping)

    def target_policy(self, registration_hash: str) -> dict[str, object]:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT * FROM target_policy_registrations"
                    " WHERE target_policy_snapshot_registration_hash ="
                    " :hash"
                ),
                {"hash": registration_hash},
            ).first()
        if row is None:
            raise GovernanceStoreError(
                "target_policy_unknown",
                "no registered target policy for hash",
            )
        return dict(row._mapping)

    def attempt_reserved(self, attempt_id: str) -> bool:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT 1 FROM trial_attempts"
                    " WHERE attempt_budget_reservation_id = :attempt"
                ),
                {"attempt": attempt_id},
            ).first()
        return row is not None


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


__all__ = [
    "GovernanceRepository",
    "GovernanceStoreError",
    "TrialSealReceipt",
    "TrialSealRequest",
]
