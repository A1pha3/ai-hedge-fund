"""Plan 07 Task 8: disaster recovery restore and old-writer fencing.

Disaster recovery is the only path that re-establishes broker write
authority after a lost or corrupted process, durable store, or credential.
It is driven by a signed two-person one-shot ``DisasterRecoveryManifest``
and a strict state machine:

    PRE_RESTORE -> BACKUP_VERIFIED -> STORES_RESTORED -> RECONCILED
        -> RECOVERY_COMPLETE

Before ``RECOVERY_COMPLETE`` entry is fenced; only exit/tightening (and
query/reconcile) may proceed. The restore:

1. verifies the signed manifest through the full ``CapabilityVerifier`` chain
   (registry, role boundary, lifecycle, Ed25519 signature, payload hash);
2. proves the recovered backup root hash equals the manifest binding
   (stale/tampered backup => ``BACKUP_ROOT_MISMATCH``);
3. raises the recovery and fencing epochs past the live ones — a stale or
   replayed manifest whose epoch does not advance is rejected
   (``RECOVERY_EPOCH_NOT_ADVANCED`` / ``FENCING_EPOCH_NOT_ADVANCED``);
4. restores and verifies the durable inbox/outbox/broker cursors against the
   manifest cursor proof (missing/contradicted cursor rejected);
5. reconciles complete broker state and re-proves capital conservation
   before entry (``reconcile_before_entry``); live/ambiguous orders and an
   unproven conservation block completion;
6. re-binds a fresh broker credential/session/network fence — a lost
   credential cannot be reused; and
7. activates a new writer under the raised fencing epoch. The old writer's
   epoch is permanently invalid: any send under it is fenced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from src.screening.offensive.v3.contracts import (
    Capability,
    DisasterRecoveryManifest,
    SignedEnvelope,
)
from src.screening.offensive.v3.trust import (
    CapabilityVerifier,
    CurrentTrustHeadWitness,
)


class DisasterRecoveryError(RuntimeError):
    """Recovery/fencing failure with a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class RecoveryState(StrEnum):
    PRE_RESTORE = "pre_restore"
    BACKUP_VERIFIED = "backup_verified"
    STORES_RESTORED = "stores_restored"
    RECONCILED = "reconciled"
    RECOVERY_COMPLETE = "recovery_complete"


@dataclass(frozen=True)
class RecoveredStores:
    """The durable stores/cursors restored from the verified backup."""

    backup_root_hash: str
    inbox_cursor: str
    outbox_cursor: str
    broker_cursor: str


@dataclass(frozen=True)
class RecoveryFenceProof:
    """Re-establishes broker reach after restore.

    A lost credential cannot be reused: restore must bind a fresh credential,
    sever the old session, and re-fence the old network egress. When the
    broker cannot revoke the old session, a process/host termination proof
    plus a network-policy proof substitutes for session severance.
    """

    credential_re_bound: bool
    session_re_severed: bool
    network_egress_re_fenced: bool
    proven_at: datetime
    termination_proof: bool = False
    network_policy_proof: bool = False


@dataclass
class DisasterRecoveryCoordinator:
    """Orchestrates disaster-recovery restore under a signed manifest.

    Only one valid recovery epoch can send after completion; the old writer
    and the old fencing epoch are permanently invalid.
    """

    _state: RecoveryState = RecoveryState.PRE_RESTORE
    _recovery_epoch: int = 0
    _fencing_epoch: int = 0
    _manifest: DisasterRecoveryManifest | None = None
    _stores: RecoveredStores | None = None
    _active_writer_id: str = "writer-1"
    _fence_proof: RecoveryFenceProof | None = None

    @property
    def state(self) -> RecoveryState:
        return self._state

    @property
    def recovery_epoch(self) -> int:
        return self._recovery_epoch

    @property
    def fencing_epoch(self) -> int:
        return self._fencing_epoch

    @property
    def entry_permitted(self) -> bool:
        """Entry is only permitted once recovery is fully complete."""

        return self._state is RecoveryState.RECOVERY_COMPLETE

    # -- PRE_RESTORE -> BACKUP_VERIFIED -----------------------------------

    def verify_backup(
        self,
        envelope: SignedEnvelope,
        *,
        verifier: CapabilityVerifier,
        current_head: CurrentTrustHeadWitness,
        required_capability: Capability,
        trusted_at: datetime,
        recovered_backup_root_hash: str,
        current_recovery_epoch: int,
        current_fencing_epoch: int,
        expected_account_fingerprint: str,
    ) -> DisasterRecoveryManifest:
        """Verify the signed manifest, backup root, account and epoch advance."""

        self._require(RecoveryState.PRE_RESTORE, "verify_backup")
        verifier.verify(
            envelope,
            required_capability,
            current_head=current_head,
            trusted_at=trusted_at,
        )
        try:
            manifest = DisasterRecoveryManifest.model_validate_json(
                envelope.payload
            )
        except ValueError as exc:
            raise DisasterRecoveryError(
                "MANIFEST_UNPARSEABLE",
                f"disaster recovery payload is not a valid manifest: {exc}",
            ) from exc
        if not (manifest.issued_at <= trusted_at <= manifest.expires_at):
            raise DisasterRecoveryError(
                "RECOVERY_WINDOW_INACTIVE",
                "trusted_at outside manifest validity window",
            )
        if manifest.backup_root_hash != recovered_backup_root_hash:
            raise DisasterRecoveryError(
                "BACKUP_ROOT_MISMATCH",
                "recovered backup root does not match the manifest binding",
            )
        if manifest.broker_account_fingerprint != expected_account_fingerprint:
            raise DisasterRecoveryError(
                "ACCOUNT_MISMATCH",
                "manifest account does not match the portfolio binding",
            )
        if manifest.recovery_epoch <= current_recovery_epoch:
            raise DisasterRecoveryError(
                "RECOVERY_EPOCH_NOT_ADVANCED",
                f"recovery epoch {manifest.recovery_epoch} must advance the"
                f" live epoch {current_recovery_epoch}",
            )
        if manifest.fencing_epoch <= current_fencing_epoch:
            raise DisasterRecoveryError(
                "FENCING_EPOCH_NOT_ADVANCED",
                f"fencing epoch {manifest.fencing_epoch} must advance the"
                f" live epoch {current_fencing_epoch}",
            )
        self._manifest = manifest
        self._recovery_epoch = manifest.recovery_epoch
        self._fencing_epoch = manifest.fencing_epoch
        self._state = RecoveryState.BACKUP_VERIFIED
        return manifest

    # -- BACKUP_VERIFIED -> STORES_RESTORED -------------------------------

    def restore_stores(self, stores: RecoveredStores) -> None:
        """Restore the durable cursors, proving each matches the manifest."""

        self._require(RecoveryState.BACKUP_VERIFIED, "restore_stores")
        manifest = self._manifest
        assert manifest is not None  # guarded by state machine
        if not stores.inbox_cursor or not stores.outbox_cursor or not stores.broker_cursor:
            raise DisasterRecoveryError(
                "MISSING_CURSOR",
                "inbox/outbox/broker cursors must all be present",
            )
        if stores.backup_root_hash != manifest.backup_root_hash:
            raise DisasterRecoveryError(
                "BACKUP_ROOT_MISMATCH",
                "restored backup root diverges from the manifest binding",
            )
        if stores.inbox_cursor != manifest.durable_inbox_cursor:
            raise DisasterRecoveryError(
                "INBOX_CURSOR_MISMATCH",
                "restored inbox cursor does not match the manifest cursor proof",
            )
        if stores.outbox_cursor != manifest.durable_outbox_cursor:
            raise DisasterRecoveryError(
                "OUTBOX_CURSOR_MISMATCH",
                "restored outbox cursor does not match the manifest cursor proof",
            )
        if stores.broker_cursor != manifest.broker_cursor:
            raise DisasterRecoveryError(
                "BROKER_CURSOR_MISMATCH",
                "restored broker cursor does not match the manifest cursor proof",
            )
        self._stores = stores
        self._state = RecoveryState.STORES_RESTORED

    # -- STORES_RESTORED -> RECONCILED ------------------------------------

    def reconcile(
        self,
        *,
        live_orders: int,
        ambiguous_orders: int,
        conservation_proven: bool,
    ) -> None:
        """Reconcile complete broker state and re-prove conservation before entry."""

        self._require(RecoveryState.STORES_RESTORED, "reconcile")
        if live_orders < 0 or ambiguous_orders < 0:
            raise DisasterRecoveryError(
                "INVALID_ORDER_COUNT", "order counts must be non-negative"
            )
        if not conservation_proven:
            raise DisasterRecoveryError(
                "CONSERVATION_NOT_PROVEN",
                "capital conservation must be re-proven before entry",
            )
        if live_orders > 0:
            raise DisasterRecoveryError(
                "LIVE_ORDER_REMAINS",
                f"{live_orders} live orders still block recovery",
            )
        if ambiguous_orders > 0:
            raise DisasterRecoveryError(
                "AMBIGUOUS_ORDER_REMAINS",
                f"{ambiguous_orders} ambiguous orders still block recovery",
            )
        self._state = RecoveryState.RECONCILED

    # -- credential re-binding --------------------------------------------

    def present_fence_proof(self, proof: RecoveryFenceProof) -> None:
        """Bind a fresh credential/session/network fence (lost credential reused = no)."""

        self._require(RecoveryState.RECONCILED, "present_fence_proof")
        if not proof.credential_re_bound:
            raise DisasterRecoveryError(
                "CREDENTIAL_NOT_RE_BOUND",
                "a fresh credential must be bound after restore",
            )
        if not proof.network_egress_re_fenced:
            raise DisasterRecoveryError(
                "NETWORK_EGRESS_NOT_RE_FENCED",
                "old network egress must be re-fenced after restore",
            )
        session_severed = proof.session_re_severed or (
            proof.termination_proof and proof.network_policy_proof
        )
        if not session_severed:
            raise DisasterRecoveryError(
                "SESSION_NOT_RE_SEVERED",
                "old session must be re-severed, or a termination proof plus"
                " network-policy proof supplied",
            )
        self._fence_proof = proof

    # -- RECONCILED -> RECOVERY_COMPLETE ----------------------------------

    def complete(self, *, new_writer_id: str) -> int:
        """Activate the new writer under the raised fencing epoch.

        Returns the recovered fencing epoch. The old writer and old epoch are
        permanently invalid after this call.
        """

        self._require(RecoveryState.RECONCILED, "complete")
        if self._fence_proof is None:
            raise DisasterRecoveryError(
                "NO_FENCE_PROOF",
                "a fresh fence proof must be presented before recovery completes",
            )
        self._active_writer_id = new_writer_id
        self._state = RecoveryState.RECOVERY_COMPLETE
        return self._fencing_epoch

    # -- fencing enforcement ----------------------------------------------

    def fence_send(self, *, writer_id: str, epoch: int) -> None:
        """Reject any send before recovery completes, or not under the new writer+epoch."""

        if self._state is not RecoveryState.RECOVERY_COMPLETE:
            raise DisasterRecoveryError(
                "ENTRY_FENCED",
                f"entry not permitted while recovery is {self._state.value}",
            )
        if writer_id != self._active_writer_id:
            raise DisasterRecoveryError(
                "WRITER_NOT_AUTHORITY",
                f"writer {writer_id!r} is not the recovered authority",
            )
        if epoch != self._fencing_epoch:
            raise DisasterRecoveryError(
                "EPOCH_SUPERSEDED",
                f"epoch {epoch} is permanently invalid (live {self._fencing_epoch})",
            )

    def _require(self, expected: RecoveryState, action: str) -> None:
        if self._state is not expected:
            raise DisasterRecoveryError(
                "ILLEGAL_RECOVERY_TRANSITION",
                f"{action} requires {expected.value}, got {self._state.value}",
            )
