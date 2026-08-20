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
    PolicyActivation,
    StageManifest,
    StatisticalAnalysisPlan,
    TrialManifest,
)
from src.screening.offensive.v3.contracts.trust import (
    Capability,
    CurrentTrustHeadWitness,
    SignedEnvelope,
)
from src.screening.offensive.v3.governance.regime_trial import (
    GovernanceArtifactVerifierPort,
    RegimeTrialBundle,
    RegimeTrialGovernanceError,
    target_policy_registration_hash,
    validate_regime_trial_bundle,
)
from src.screening.offensive.v3.policy.models import PolicySnapshot

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
    "CREATE TRIGGER IF NOT EXISTS no_update_sealed_trials " "BEFORE UPDATE ON sealed_trials " "BEGIN SELECT RAISE(ABORT, 'immutable table: sealed_trials rejects " "UPDATE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_delete_sealed_trials " "BEFORE DELETE ON sealed_trials " "BEGIN SELECT RAISE(ABORT, 'immutable table: sealed_trials rejects " "DELETE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_update_trial_attempts " "BEFORE UPDATE ON trial_attempts " "BEGIN SELECT RAISE(ABORT, 'immutable table: trial_attempts rejects " "UPDATE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_delete_trial_attempts " "BEFORE DELETE ON trial_attempts " "BEGIN SELECT RAISE(ABORT, 'immutable table: trial_attempts rejects " "DELETE'); END;",
    """
    CREATE TABLE IF NOT EXISTS regime_trial_bindings (
        trial_id TEXT PRIMARY KEY,
        baseline_policy_json TEXT NOT NULL,
        baseline_policy_activation_json TEXT NOT NULL,
        signed_trial_envelope_json TEXT NOT NULL,
        signed_sap_envelope_json TEXT NOT NULL,
        signed_baseline_activation_envelope_json TEXT NOT NULL,
        sealed_at TEXT NOT NULL,
        FOREIGN KEY (trial_id) REFERENCES sealed_trials (trial_id)
    )
    """,
    "CREATE TRIGGER IF NOT EXISTS no_update_regime_trial_bindings " "BEFORE UPDATE ON regime_trial_bindings " "BEGIN SELECT RAISE(ABORT, 'immutable table: regime_trial_bindings rejects " "UPDATE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_delete_regime_trial_bindings " "BEFORE DELETE ON regime_trial_bindings " "BEGIN SELECT RAISE(ABORT, 'immutable table: regime_trial_bindings rejects " "DELETE'); END;",
    """
    CREATE TABLE IF NOT EXISTS sealed_stages (
        stage_id TEXT PRIMARY KEY,
        trial_id TEXT NOT NULL,
        stage_manifest_hash TEXT NOT NULL UNIQUE,
        stage_manifest_json TEXT NOT NULL,
        signed_stage_envelope_json TEXT NOT NULL,
        sealed_at TEXT NOT NULL,
        FOREIGN KEY (trial_id) REFERENCES sealed_trials (trial_id)
    )
    """,
    "CREATE TRIGGER IF NOT EXISTS no_update_sealed_stages " "BEFORE UPDATE ON sealed_stages " "BEGIN SELECT RAISE(ABORT, 'immutable table: sealed_stages rejects " "UPDATE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_delete_sealed_stages " "BEFORE DELETE ON sealed_stages " "BEGIN SELECT RAISE(ABORT, 'immutable table: sealed_stages rejects " "DELETE'); END;",
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
        self.target_policy_snapshot_registration_hash = target_policy_snapshot_registration_hash
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
        self.target_policy_snapshot_registration_hash = target_policy_snapshot_registration_hash
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

    def reserve_attempt_and_seal_trial(self, request: TrialSealRequest) -> TrialSealReceipt:
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
        if trial.trial_id != sap.sap_id and (trial.research_program_id != sap.research_program_id or trial.economic_lineage_id != sap.economic_lineage_id):
            raise GovernanceStoreError(
                "sap_lineage_mismatch",
                "SAP program/lineage differs from the trial manifest",
            )
        if trial.target_portfolio_policy_fingerprint != (request.policy_fingerprint):
            raise GovernanceStoreError(
                "target_policy_fingerprint_mismatch",
                "registered target policy differs from the trial target",
            )
        with self._engine.begin() as conn:
            try:
                conn.execute(
                    sa.text("INSERT INTO trial_attempts (" " attempt_budget_reservation_id," " research_program_id, economic_lineage_id," " stage_id, trial_id, sealed_at)" " VALUES (:attempt, :program, :lineage, :stage," " :trial, :sealed_at)"),
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
                    sa.text("INSERT INTO sealed_trials (trial_id," " research_program_id, economic_lineage_id, role," " trial_manifest_hash, trial_manifest_json," " sap_manifest_hash, sap_manifest_json," " attempt_budget_reservation_id, sealed_at)" " VALUES (:trial, :program, :lineage, :role," " :trial_hash, :trial_json, :sap_hash, :sap_json," " :attempt, :sealed_at)"),
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
                    sa.text("INSERT INTO target_policy_registrations (" " target_policy_snapshot_registration_hash," " policy_snapshot_json, policy_fingerprint," " executable, registered_at)" " VALUES (:hash, :json, :fingerprint, 0, :at)"),
                    {
                        "hash": (request.target_policy_snapshot_registration_hash),
                        "json": request.policy_snapshot_json,
                        "fingerprint": request.policy_fingerprint,
                        "at": sealed_at.isoformat(),
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise GovernanceStoreError(
                    "trial_seal_conflict",
                    "attempt, trial role or target registration already" " committed; the whole seal rolled back",
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
            attempt_budget_reservation_id=(request.attempt_budget_reservation_id),
            trial_manifest_hash=trial.artifact_hash(),
            sap_manifest_hash=sap.artifact_hash(),
            target_policy_snapshot_registration_hash=(request.target_policy_snapshot_registration_hash),
            sealed_at=sealed_at,
        )

    def sealed_trial(self, trial_id: str) -> dict[str, object]:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT * FROM sealed_trials WHERE trial_id = :trial"),
                {"trial": trial_id},
            ).first()
        if row is None:
            raise GovernanceStoreError("trial_unknown", "no sealed trial for id", trial_id=trial_id)
        return dict(row._mapping)

    def target_policy(self, registration_hash: str) -> dict[str, object]:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT * FROM target_policy_registrations" " WHERE target_policy_snapshot_registration_hash =" " :hash"),
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
                sa.text("SELECT 1 FROM trial_attempts" " WHERE attempt_budget_reservation_id = :attempt"),
                {"attempt": attempt_id},
            ).first()
        return row is not None

    def seal_regime_trial(
        self,
        request: RegimeTrialSealRequest,
        *,
        verifier: GovernanceArtifactVerifierPort,
        current_head: CurrentTrustHeadWitness,
        trusted_at: datetime,
    ) -> TrialSealReceipt:
        """Verify signed envelopes, validate the bundle, then seal atomically.

        Signatures and capability/trust are verified through ``verifier`` before
        the transaction opens; payload binding (envelope bytes equal the typed
        manifest canonical bytes) is checked here. The semantic one-delta
        contract is enforced by ``validate_regime_trial_bundle``. Either every
        row commits or none does.
        """

        trial = request.trial_manifest
        sap = request.sap_manifest
        activation = request.baseline_policy_activation
        self._verify_signed_artifact(
            request.signed_trial_envelope,
            trial,
            request.trial_capability,
            verifier,
            current_head=current_head,
            trusted_at=trusted_at,
        )
        self._verify_signed_artifact(
            request.signed_sap_envelope,
            sap,
            request.sap_capability,
            verifier,
            current_head=current_head,
            trusted_at=trusted_at,
        )
        self._verify_signed_artifact(
            request.signed_baseline_activation_envelope,
            activation,
            request.baseline_activation_capability,
            verifier,
            current_head=current_head,
            trusted_at=trusted_at,
        )
        bundle = RegimeTrialBundle(
            baseline_policy=request.baseline_policy,
            target_policy=request.target_policy,
            trial_manifest=trial,
            sap_manifest=sap,
            baseline_policy_activation=activation,
        )
        validate_regime_trial_bundle(bundle, trusted_at=trusted_at)
        if trial.trial_manifest_sealed_at > request.expected_signal_cutoff:
            raise GovernanceStoreError(
                "seal_after_signal_cutoff",
                "trial manifest must be sealed before the signal cutoff",
            )

        sealed_at = self._clock()
        registration_hash = target_policy_registration_hash(request.target_policy)
        with self._engine.begin() as conn:
            try:
                conn.execute(
                    sa.text("INSERT INTO trial_attempts (" " attempt_budget_reservation_id," " research_program_id, economic_lineage_id," " stage_id, trial_id, sealed_at)" " VALUES (:attempt, :program, :lineage, :stage," " :trial, :sealed_at)"),
                    {
                        "attempt": trial.attempt_budget_reservation_id,
                        "program": trial.research_program_id,
                        "lineage": trial.economic_lineage_id,
                        "stage": request.stage_id,
                        "trial": trial.trial_id,
                        "sealed_at": sealed_at.isoformat(),
                    },
                )
                conn.execute(
                    sa.text("INSERT INTO sealed_trials (trial_id," " research_program_id, economic_lineage_id, role," " trial_manifest_hash, trial_manifest_json," " sap_manifest_hash, sap_manifest_json," " attempt_budget_reservation_id, sealed_at)" " VALUES (:trial, :program, :lineage, 'paired'," " :trial_hash, :trial_json, :sap_hash, :sap_json," " :attempt, :sealed_at)"),
                    {
                        "trial": trial.trial_id,
                        "program": trial.research_program_id,
                        "lineage": trial.economic_lineage_id,
                        "trial_hash": trial.artifact_hash(),
                        "trial_json": trial.model_dump_json(),
                        "sap_hash": sap.artifact_hash(),
                        "sap_json": sap.model_dump_json(),
                        "attempt": trial.attempt_budget_reservation_id,
                        "sealed_at": sealed_at.isoformat(),
                    },
                )
                conn.execute(
                    sa.text("INSERT INTO target_policy_registrations (" " target_policy_snapshot_registration_hash," " policy_snapshot_json, policy_fingerprint," " executable, registered_at)" " VALUES (:hash, :json, :fingerprint, 0, :at)"),
                    {
                        "hash": registration_hash,
                        "json": request.target_policy.model_dump_json(),
                        "fingerprint": request.target_policy.policy_fingerprint,
                        "at": sealed_at.isoformat(),
                    },
                )
                conn.execute(
                    sa.text("INSERT INTO regime_trial_bindings (trial_id," " baseline_policy_json," " baseline_policy_activation_json," " signed_trial_envelope_json," " signed_sap_envelope_json," " signed_baseline_activation_envelope_json," " sealed_at)" " VALUES (:trial, :baseline_policy," " :baseline_activation, :signed_trial," " :signed_sap, :signed_activation, :sealed_at)"),
                    {
                        "trial": trial.trial_id,
                        "baseline_policy": request.baseline_policy.model_dump_json(),
                        "baseline_activation": activation.model_dump_json(),
                        "signed_trial": request.signed_trial_envelope.model_dump_json(),
                        "signed_sap": request.signed_sap_envelope.model_dump_json(),
                        "signed_activation": (request.signed_baseline_activation_envelope.model_dump_json()),
                        "sealed_at": sealed_at.isoformat(),
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise GovernanceStoreError(
                    "regime_trial_seal_conflict",
                    "attempt, paired trial role, target registration or binding" " already committed; the whole seal rolled back",
                    reason=str(exc),
                ) from exc
        return TrialSealReceipt(
            trial_id=trial.trial_id,
            attempt_budget_reservation_id=trial.attempt_budget_reservation_id,
            trial_manifest_hash=trial.artifact_hash(),
            sap_manifest_hash=sap.artifact_hash(),
            target_policy_snapshot_registration_hash=registration_hash,
            sealed_at=sealed_at,
        )

    def seal_stage(
        self,
        signed_stage: SignedEnvelope,
        stage_manifest: StageManifest,
        required: Capability,
        *,
        verifier: GovernanceArtifactVerifierPort,
        current_head: CurrentTrustHeadWitness,
        trusted_at: datetime,
    ) -> str:
        """Verify and persist one immutable StageManifest bound to its trial.

        恰等重放幂等 (镜像 trial store 的 insert-or-verify-exact 纪律):
        签发方 crash 后重试同一已封存 stage (同 manifest 字节 + 同签名信封)
        收敛为幂等返回; 同 ``stage_id`` 不同内容是类型化冲突, 整个事务回滚。
        """

        self._verify_signed_artifact(
            signed_stage,
            stage_manifest,
            required,
            verifier,
            current_head=current_head,
            trusted_at=trusted_at,
        )
        sealed_at = self._clock()
        with self._engine.begin() as conn:
            existing = conn.execute(
                sa.text(
                    "SELECT stage_manifest_hash, stage_manifest_json,"
                    " signed_stage_envelope_json FROM sealed_stages"
                    " WHERE stage_id = :stage"
                ),
                {"stage": stage_manifest.stage_id},
            ).first()
            if existing is not None:
                candidate = (
                    stage_manifest.artifact_hash(),
                    stage_manifest.model_dump_json(),
                    signed_stage.model_dump_json(),
                )
                if tuple(existing) != candidate:
                    raise GovernanceStoreError(
                        "stage_seal_conflict",
                        "stage already sealed with different content;"
                        " the replay rolled back",
                        stage_id=stage_manifest.stage_id,
                    )
                return stage_manifest.stage_id
            try:
                conn.execute(
                    sa.text("INSERT INTO sealed_stages (stage_id, trial_id," " stage_manifest_hash, stage_manifest_json," " signed_stage_envelope_json, sealed_at)" " VALUES (:stage, :trial, :hash, :json, :signed, :at)"),
                    {
                        "stage": stage_manifest.stage_id,
                        "trial": self._require_trial_for_stage(conn, stage_manifest.trial_manifest_hash),
                        "hash": stage_manifest.artifact_hash(),
                        "json": stage_manifest.model_dump_json(),
                        "signed": signed_stage.model_dump_json(),
                        "at": sealed_at.isoformat(),
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise GovernanceStoreError(
                    "stage_seal_conflict",
                    "stage already sealed or trial lineage absent;" " the insert rolled back",
                    reason=str(exc),
                ) from exc
        return stage_manifest.stage_id

    def regime_trial_bundle(self, trial_id: str) -> RegimeTrialBundle:
        """Reconstruct the typed paired regime trial bundle from sealed truth."""

        with self._engine.connect() as conn:
            trial_row = conn.execute(
                sa.text("SELECT * FROM sealed_trials WHERE trial_id = :trial"),
                {"trial": trial_id},
            ).first()
            binding_row = conn.execute(
                sa.text("SELECT * FROM regime_trial_bindings WHERE trial_id = :trial"),
                {"trial": trial_id},
            ).first()
        if trial_row is None or binding_row is None:
            raise GovernanceStoreError(
                "regime_trial_unknown",
                "no sealed paired regime trial bundle for id",
                trial_id=trial_id,
            )
        trial_mapping = dict(trial_row._mapping)
        binding_mapping = dict(binding_row._mapping)
        try:
            trial_manifest = TrialManifest.model_validate_json(trial_mapping["trial_manifest_json"], strict=True)
            target_row = self.target_policy(trial_manifest.target_policy_snapshot_registration_hash)
            return RegimeTrialBundle(
                baseline_policy=PolicySnapshot.model_validate_json(binding_mapping["baseline_policy_json"], strict=True),
                target_policy=PolicySnapshot.model_validate_json(target_row["policy_snapshot_json"], strict=True),
                trial_manifest=trial_manifest,
                sap_manifest=StatisticalAnalysisPlan.model_validate_json(trial_mapping["sap_manifest_json"], strict=True),
                baseline_policy_activation=PolicyActivation.model_validate_json(
                    binding_mapping["baseline_policy_activation_json"],
                    strict=True,
                ),
            )
        except ValidationError as exc:
            raise GovernanceStoreError(
                "regime_trial_bundle_corrupt",
                "sealed regime trial bundle failed strict revalidation",
                reason=str(exc),
            ) from exc

    @staticmethod
    def _require_trial_for_stage(conn: sa.Connection, trial_manifest_hash: str) -> str:
        row = conn.execute(
            sa.text("SELECT trial_id FROM sealed_trials" " WHERE trial_manifest_hash = :hash"),
            {"hash": trial_manifest_hash},
        ).first()
        if row is None:
            raise GovernanceStoreError(
                "stage_trial_unknown",
                "StageManifest references an unsealed trial manifest",
            )
        return str(row._mapping["trial_id"])

    @staticmethod
    def _verify_signed_artifact(
        signed: SignedEnvelope,
        payload_model: object,
        required: Capability,
        verifier: GovernanceArtifactVerifierPort,
        *,
        current_head: CurrentTrustHeadWitness,
        trusted_at: datetime,
    ) -> None:
        if signed.payload != payload_model.canonical_bytes():  # type: ignore[attr-defined]
            raise GovernanceStoreError(
                "signed_payload_binding_mismatch",
                "signed envelope payload must equal the typed manifest bytes",
            )
        try:
            verifier.verify(
                signed,
                required,
                current_head=current_head,
                trusted_at=trusted_at,
            )
        except RegimeTrialGovernanceError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any verifier failure closed
            raise GovernanceStoreError(
                "artifact_verification_failed",
                "signed governance artifact failed capability/trust verification",
                reason=str(exc),
            ) from exc


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


class RegimeTrialSealRequest:
    """Typed, signed payload bundle for sealing one paired regime trial.

    Unlike the audit-only :class:`TrialSealRequest`, this carries the signed
    Trial/SAP/baseline-activation envelopes, their exact typed payloads, the
    matching baseline and target ``PolicySnapshot`` objects, and the
    capabilities required to verify each envelope. The store verifies every
    signature and payload binding before opening its transaction.
    """

    def __init__(
        self,
        *,
        stage_id: str,
        signed_trial_envelope: SignedEnvelope,
        trial_manifest: TrialManifest,
        trial_capability: Capability,
        signed_sap_envelope: SignedEnvelope,
        sap_manifest: StatisticalAnalysisPlan,
        sap_capability: Capability,
        signed_baseline_activation_envelope: SignedEnvelope,
        baseline_policy_activation: PolicyActivation,
        baseline_activation_capability: Capability,
        baseline_policy: PolicySnapshot,
        target_policy: PolicySnapshot,
        expected_signal_cutoff: datetime,
    ) -> None:
        self.stage_id = stage_id
        self.signed_trial_envelope = signed_trial_envelope
        self.trial_manifest = trial_manifest
        self.trial_capability = trial_capability
        self.signed_sap_envelope = signed_sap_envelope
        self.sap_manifest = sap_manifest
        self.sap_capability = sap_capability
        self.signed_baseline_activation_envelope = signed_baseline_activation_envelope
        self.baseline_policy_activation = baseline_policy_activation
        self.baseline_activation_capability = baseline_activation_capability
        self.baseline_policy = baseline_policy
        self.target_policy = target_policy
        self.expected_signal_cutoff = expected_signal_cutoff


__all__ = [
    "GovernanceRepository",
    "GovernanceStoreError",
    "RegimeTrialSealRequest",
    "TrialSealReceipt",
    "TrialSealRequest",
]
