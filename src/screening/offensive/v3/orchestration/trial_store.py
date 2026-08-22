"""Plan Task 6: atomic arm decision store + fenced single writer.

``TrialArmDecisionStore`` persists the exact pair of arm decisions
(``ShadowDecision | NoTradeDecision``) for one trial/session/cycle under the
unique key ``(trial_id, signal_session, decision_cycle_id, arm)``. Rows are
immutable (UPDATE/DELETE triggers), replay is exact-idempotent, a
same-key/different-content replay is a typed conflict, and pair commits are
two-row atomic via ``BEGIN IMMEDIATE``. A monotone fencing epoch guards
pair/capital lifecycle mutation: every new owner bumps the epoch, stale
tokens fail before any mutation.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, timezone
from typing import TypeAlias

from pydantic import ConfigDict

from src.screening.offensive.v3.contracts.base import CanonicalModel
from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.governance.regime_trial import (
    RegimeTrialBundle,
)
from src.screening.offensive.v3.kernel.models import NoTradeDecision
from src.screening.offensive.v3.orchestration.genesis import (
    TrialGenesisManifest,
)

SCHEMA_MAJOR = 2


class TrialStoreError(RuntimeError):
    """A durable arm-decision store operation failed a frozen invariant."""

    def __init__(self, code: str, detail: str, **details: object) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.details = details


#: One arm decision payload: a full ShadowDecision or a typed NoTradeDecision.
ArmDecision: TypeAlias = ShadowDecision | NoTradeDecision


class TrialArmDecisionRecord(CanonicalModel):
    """One durable arm decision under the exact session/cycle key.

    ``decision`` carries the complete canonical artifact (``ShadowDecision``
    or ``NoTradeDecision``); ``artifact_hash`` is its content hash, so a
    partial-row tamper of the payload breaks the binding. The remaining
    columns freeze the shared input identity and the arm-specific policy/
    capital/regime bindings at decision time.
    """

    trial_id: str
    signal_session: date
    decision_cycle_id: str
    arm: TrialArm
    shared_input_hash: str
    arm_policy_fingerprint: str | None
    arm_capital_checkpoint_hash: str
    regime_observation_hash: str
    decision: ArmDecision
    created_at: datetime
    artifact_hash: str


class PairCommitReceipt(CanonicalModel):
    """One committed pair of arm decisions, keyed by session/cycle."""

    trial_id: str
    signal_session: date
    decision_cycle_id: str
    champion_artifact_hash: str
    challenger_artifact_hash: str
    committed_at: datetime
    schema_major: int = SCHEMA_MAJOR

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.trial_id, self.signal_session.isoformat(), self.decision_cycle_id)


class WriterLeaseToken(CanonicalModel):
    """One fenced single-writer lease token for the trial lifecycle."""

    writer_id: str
    epoch: int
    expires_at: datetime


class TrialArmDecisionStore:
    """Durable, immutable arm-decision store with a fenced single writer.

    Tables:
      ``trial_registrations``   — one row per sealed trial (bundle + genesis)
      ``trial_arm_decisions``   — FK to registration; exact unique key
                                  (trial_id, signal_session, decision_cycle_id,
                                  arm); UPDATE/DELETE triggers make rows
                                  immutable; ``decision_json`` is the full
                                  canonical payload
      ``trial_writer_state``    — one row: the current epoch and owner
      ``trial_writer_leases``   — one row per live lease token
    """

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        self._connect()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._database_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trial_registrations (
                    trial_id TEXT PRIMARY KEY,
                    bundle_json TEXT NOT NULL,
                    genesis_manifest_json TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trial_arm_decisions (
                    trial_id TEXT NOT NULL,
                    signal_session TEXT NOT NULL,
                    decision_cycle_id TEXT NOT NULL,
                    arm TEXT NOT NULL,
                    shared_input_hash TEXT NOT NULL,
                    arm_policy_fingerprint TEXT,
                    arm_capital_checkpoint_hash TEXT NOT NULL,
                    regime_observation_hash TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    PRIMARY KEY (trial_id, signal_session, decision_cycle_id, arm),
                    FOREIGN KEY (trial_id)
                        REFERENCES trial_registrations (trial_id)
                );
                CREATE TRIGGER IF NOT EXISTS trial_arm_decisions_no_update
                BEFORE UPDATE ON trial_arm_decisions
                BEGIN
                    SELECT RAISE(ABORT,
                        'immutable table: trial_arm_decisions rejects UPDATE');
                END;
                CREATE TRIGGER IF NOT EXISTS trial_arm_decisions_no_delete
                BEFORE DELETE ON trial_arm_decisions
                BEGIN
                    SELECT RAISE(ABORT,
                        'immutable table: trial_arm_decisions rejects DELETE');
                END;
                CREATE TABLE IF NOT EXISTS trial_writer_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    epoch INTEGER NOT NULL,
                    owner_id TEXT
                );
                CREATE TABLE IF NOT EXISTS trial_writer_leases (
                    writer_id TEXT PRIMARY KEY,
                    epoch INTEGER NOT NULL,
                    expires_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO trial_writer_state (id, epoch, owner_id)
                    VALUES (1, 0, NULL);
                """
            )
            conn.commit()
        finally:
            conn.close()

    # -- registration --------------------------------------------------------

    def register_trial(
        self, bundle: RegimeTrialBundle, genesis_manifest: TrialGenesisManifest
    ) -> None:
        """Register one sealed trial before any arm decision may commit.

        The bundle and genesis manifest are stored whole; the registration
        row is the FK parent for every arm decision of this trial. The
        genesis manifest must name the same trial as the bundle — a
        cross-trial binding is rejected before any row is written.
        """

        if genesis_manifest.trial_id != bundle.trial_manifest.trial_id:
            raise TrialStoreError(
                "genesis_trial_mismatch",
                "genesis manifest names a different trial than the bundle",
                genesis_trial_id=genesis_manifest.trial_id,
                bundle_trial_id=bundle.trial_manifest.trial_id,
            )
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT bundle_json, genesis_manifest_json"
                " FROM trial_registrations WHERE trial_id = :trial_id",
                {"trial_id": bundle.trial_manifest.trial_id},
            ).fetchone()
            if existing is not None:
                if (
                    existing[0] != bundle.model_dump_json()
                    or existing[1] != genesis_manifest.model_dump_json()
                ):
                    raise TrialStoreError(
                        "registration_conflict",
                        "this trial is already registered with a different"
                        " bundle or genesis manifest",
                        trial_id=bundle.trial_manifest.trial_id,
                    )
                return
            conn.execute(
                "INSERT INTO trial_registrations"
                " (trial_id, bundle_json, genesis_manifest_json, registered_at)"
                " VALUES (:trial_id, :bundle, :genesis, :at)",
                {
                    "trial_id": bundle.trial_manifest.trial_id,
                    "bundle": bundle.model_dump_json(),
                    "genesis": genesis_manifest.model_dump_json(),
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            )
            conn.commit()
        finally:
            conn.close()

    # -- pair commit ---------------------------------------------------------

    def commit_pair(
        self, champion: TrialArmDecisionRecord, challenger: TrialArmDecisionRecord
    ) -> PairCommitReceipt:
        """Atomically insert (or exactly verify) both arm decisions.

        ``BEGIN IMMEDIATE`` guarantees either both rows land or neither does;
        a replay of the exact same pair returns the same receipt, while a
        same-key/different-content replay raises ``arm_decision_conflict``.
        """

        if champion.arm is not TrialArm.CHAMPION or challenger.arm is not TrialArm.CHALLENGER:
            raise TrialStoreError(
                "arm_mismatch",
                "commit_pair requires exactly one CHAMPION and one CHALLENGER"
                " record",
            )
        if champion.trial_id != challenger.trial_id:
            raise TrialStoreError(
                "trial_mismatch",
                "the two arm decisions must belong to the same trial",
            )
        if (
            champion.signal_session != challenger.signal_session
            or champion.decision_cycle_id != challenger.decision_cycle_id
        ):
            raise TrialStoreError(
                "session_mismatch",
                "the two arm decisions must share one signal session and"
                " decision cycle",
            )
        if (
            champion.shared_input_hash != challenger.shared_input_hash
            or champion.regime_observation_hash != challenger.regime_observation_hash
        ):
            raise TrialStoreError(
                "shared_input_mismatch",
                "the two arm decisions must bind the same shared input and"
                " regime observation",
            )
        if (
            champion.arm_policy_fingerprint is not None
            and challenger.arm_policy_fingerprint is not None
            and champion.arm_policy_fingerprint == challenger.arm_policy_fingerprint
        ):
            raise TrialStoreError(
                "policy_binding_duplicate",
                "the two arms must bind distinct policy fingerprints",
            )
        _validate_record_decision_consistency(champion)
        _validate_record_decision_consistency(challenger)

        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            self._validate_registered(conn, champion.trial_id)
            self._insert_or_verify_exact(conn, champion)
            self._insert_or_verify_exact(conn, challenger)
            receipt = PairCommitReceipt(
                trial_id=champion.trial_id,
                signal_session=champion.signal_session,
                decision_cycle_id=champion.decision_cycle_id,
                champion_artifact_hash=champion.artifact_hash,
                challenger_artifact_hash=challenger.artifact_hash,
                committed_at=champion.created_at,
            )
            conn.commit()
            return receipt
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _validate_registered(self, conn: sqlite3.Connection, trial_id: str) -> None:
        row = conn.execute(
            "SELECT 1 FROM trial_registrations WHERE trial_id = :trial_id",
            {"trial_id": trial_id},
        ).fetchone()
        if row is None:
            raise TrialStoreError(
                "not_registered",
                f"trial {trial_id} has no registration; register before commit",
            )

    def _insert_or_verify_exact(
        self, conn: sqlite3.Connection, record: TrialArmDecisionRecord
    ) -> None:
        key = (
            record.trial_id,
            record.signal_session.isoformat(),
            record.decision_cycle_id,
            record.arm.value,
        )
        existing = conn.execute(
            "SELECT shared_input_hash, arm_policy_fingerprint,"
            " arm_capital_checkpoint_hash, regime_observation_hash,"
            " decision_json, artifact_hash FROM trial_arm_decisions"
            " WHERE trial_id = ? AND signal_session = ? AND decision_cycle_id = ?"
            " AND arm = ?",
            key,
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO trial_arm_decisions (trial_id, signal_session,"
                " decision_cycle_id, arm, shared_input_hash,"
                " arm_policy_fingerprint, arm_capital_checkpoint_hash,"
                " regime_observation_hash, decision_json, created_at,"
                " artifact_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.trial_id,
                    record.signal_session.isoformat(),
                    record.decision_cycle_id,
                    record.arm.value,
                    record.shared_input_hash,
                    record.arm_policy_fingerprint,
                    record.arm_capital_checkpoint_hash,
                    record.regime_observation_hash,
                    record.decision.model_dump_json(),
                    record.created_at.isoformat(),
                    record.artifact_hash,
                ),
            )
            return
        stored = (
            existing[0],
            existing[1],
            existing[2],
            existing[3],
            existing[4],
            existing[5],
        )
        candidate = (
            record.shared_input_hash,
            record.arm_policy_fingerprint,
            record.arm_capital_checkpoint_hash,
            record.regime_observation_hash,
            record.decision.model_dump_json(),
            record.artifact_hash,
        )
        if stored != candidate:
            raise TrialStoreError(
                "arm_decision_conflict",
                "same decision key already committed with different content",
                key=key,
            )

    # -- read ----------------------------------------------------------------

    def pair_keys(self, trial_id: str) -> tuple[tuple[str, str, str], ...]:
        """All committed pair keys of one trial, ordered (advance/lifecycle face)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT signal_session, decision_cycle_id, COUNT(*) AS n"
                " FROM trial_arm_decisions"
                " WHERE trial_id = ?"
                " GROUP BY signal_session, decision_cycle_id"
                " HAVING n = 2"
                " ORDER BY signal_session, decision_cycle_id",
                (trial_id,),
            ).fetchall()
        finally:
            conn.close()
        return tuple(
            (trial_id, str(row[0]), str(row[1])) for row in rows
        )

    def pair(
        self, key: tuple[str, str, str]
    ) -> tuple[TrialArmDecisionRecord, TrialArmDecisionRecord]:
        """Read both arm decisions for one key, verifying payload integrity.

        The stored artifact hash must match the stored payload's content
        hash; a partial-row tamper raises ``tamper``.
        """

        trial_id, signal_session, decision_cycle_id = key
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT arm, shared_input_hash, arm_policy_fingerprint,"
                " arm_capital_checkpoint_hash, regime_observation_hash,"
                " decision_json, created_at, artifact_hash"
                " FROM trial_arm_decisions"
                " WHERE trial_id = ? AND signal_session = ? AND decision_cycle_id = ?"
                " ORDER BY arm",
                (trial_id, signal_session, decision_cycle_id),
            ).fetchall()
        finally:
            conn.close()
        if len(rows) != 2:
            raise TrialStoreError(
                "pair_incomplete",
                "expected exactly two arm decision rows for the key",
                key=key,
            )
        records: list[TrialArmDecisionRecord] = []
        for row in rows:
            decision = _parse_decision(row[5])
            artifact_hash = row[7]
            if artifact_hash != decision.content_hash():
                raise TrialStoreError(
                    "tamper",
                    "stored artifact hash does not match the payload content",
                )
            records.append(
                TrialArmDecisionRecord(
                    trial_id=trial_id,
                    signal_session=date.fromisoformat(signal_session),
                    decision_cycle_id=decision_cycle_id,
                    arm=TrialArm(row[0]),
                    shared_input_hash=row[1],
                    arm_policy_fingerprint=row[2],
                    arm_capital_checkpoint_hash=row[3],
                    regime_observation_hash=row[4],
                    decision=decision,
                    created_at=datetime.fromisoformat(row[6]),
                    artifact_hash=artifact_hash,
                )
            )
        return records[0], records[1]

    # -- writer fencing ------------------------------------------------------

    def claim_writer(self) -> WriterLeaseToken:
        """Take over the single writer lease, bumping the fencing epoch.

        Every new owner increments the trial fencing epoch; a stale token
        from a previous owner fails before any pair/capital lifecycle
        mutation.
        """

        writer_id = uuid.uuid4().hex
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                state = conn.execute(
                    "SELECT epoch FROM trial_writer_state WHERE id = 1"
                ).fetchone()
                epoch = int(state[0]) + 1
                expires_at = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE trial_writer_state SET epoch = :epoch,"
                    " owner_id = :owner WHERE id = 1",
                    {"epoch": epoch, "owner": writer_id},
                )
                conn.execute(
                    "INSERT OR REPLACE INTO trial_writer_leases"
                    " (writer_id, epoch, expires_at) VALUES (:writer, :epoch, :expires)",
                    {"writer": writer_id, "epoch": epoch, "expires": expires_at},
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()
        return WriterLeaseToken(
            writer_id=writer_id, epoch=epoch, expires_at=datetime.fromisoformat(expires_at)
        )

    def renew_writer(self, token: WriterLeaseToken) -> WriterLeaseToken:
        """Extend a live lease; the same live owner retains its epoch."""

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT epoch FROM trial_writer_leases"
                    " WHERE writer_id = :writer",
                    {"writer": token.writer_id},
                ).fetchone()
                if row is None or int(row[0]) != token.epoch:
                    raise TrialStoreError(
                        "fencing",
                        "writer lease is stale or unknown; renew failed",
                        writer_id=token.writer_id,
                    )
                expires_at = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE trial_writer_leases SET expires_at = :expires"
                    " WHERE writer_id = :writer",
                    {"writer": token.writer_id, "expires": expires_at},
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()
        return WriterLeaseToken(
            writer_id=token.writer_id,
            epoch=token.epoch,
            expires_at=datetime.fromisoformat(expires_at),
        )

    def require_writer(self, token: WriterLeaseToken) -> None:
        """Verify the token is the live owner at the current epoch.

        Fails before any pair/capital lifecycle mutation when the epoch has
        moved on (a stale token from a previous owner).
        """

        conn = self._connect()
        try:
            state = conn.execute(
                "SELECT epoch, owner_id FROM trial_writer_state WHERE id = 1"
            ).fetchone()
            lease = conn.execute(
                "SELECT epoch FROM trial_writer_leases"
                " WHERE writer_id = :writer",
                {"writer": token.writer_id},
            ).fetchone()
        finally:
            conn.close()
        if state is None or int(state[0]) != token.epoch or state[1] != token.writer_id:
            raise TrialStoreError(
                "fencing",
                "writer token is stale; the epoch moved on",
                writer_id=token.writer_id,
            )
        if lease is None or int(lease[0]) != token.epoch:
            raise TrialStoreError(
                "fencing",
                "writer lease no longer matches the token",
                writer_id=token.writer_id,
            )

    def release_writer(self, token: WriterLeaseToken) -> None:
        """Release the lease; the epoch stays where it is (no takeover bump)."""

        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM trial_writer_leases WHERE writer_id = :writer"
                " AND epoch = :epoch",
                {"writer": token.writer_id, "epoch": token.epoch},
            )
            conn.commit()
        finally:
            conn.close()

    def force_expire_writer(self, token: WriterLeaseToken) -> None:
        """Test-only expiry hook: drop the lease row without bumping the epoch."""

        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM trial_writer_leases WHERE writer_id = :writer",
                {"writer": token.writer_id},
            )
            conn.commit()
        finally:
            conn.close()


def _validate_record_decision_consistency(record: TrialArmDecisionRecord) -> None:
    """The record's key bindings must match the wrapped decision payload.

    A ShadowDecision binds its own arm/session/cycle/hash; a NoTradeDecision
    has no policy binding, so its fingerprint column is null. Fabricating a
    record that names a different arm than its payload is a tamper.
    """

    if isinstance(record.decision, ShadowDecision):
        if (
            record.decision.counterfactual_key.signal_session
            != record.signal_session
            or record.decision.counterfactual_key.counterfactual_cycle_id
            != record.decision_cycle_id
        ):
            raise TrialStoreError(
                "record_decision_mismatch",
                "record session/cycle key disagrees with the decision payload",
            )
        if record.arm_policy_fingerprint is None:
            raise TrialStoreError(
                "record_decision_mismatch",
                "a ShadowDecision record must carry its policy fingerprint",
            )
    elif record.arm_policy_fingerprint is not None:
        raise TrialStoreError(
            "record_decision_mismatch",
            "a NoTradeDecision record cannot carry a policy fingerprint",
        )


def _parse_decision(payload: str) -> ArmDecision:
    """Parse a stored decision payload, dispatching on the artifact kind."""

    import json

    data = json.loads(payload)
    if data.get("artifact_kind") == "shadow_decision":
        return ShadowDecision.model_validate_json(payload, strict=True)
    return NoTradeDecision.model_validate_json(payload, strict=True)


__all__ = [
    "ArmDecision",
    "PairCommitReceipt",
    "TrialArmDecisionRecord",
    "TrialArmDecisionStore",
    "TrialStoreError",
    "WriterLeaseToken",
]
