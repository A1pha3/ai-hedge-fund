"""Plan 07 Task 7: credential/session/network fencing and writer handoff.

Old writer -> new writer handoff is the only path that moves the single
broker egress authority. The state machine is:

    ACTIVE -> DRAINING -> BROKER_RECONCILED -> HANDOFF_COMPLETE

with a monotonically increasing fencing epoch. The old worker stops entry,
drains/reconciles its in-flight orders, then proves the external
credential/session and network egress are revoked (or that a process/host
termination proof plus network-policy proof covers an irrevocable
session). Only after those proofs AND a durable cursor checkpoint does the
new worker receive the next fencing epoch. The old epoch remains
permanently invalid: any subsequent send under it is fenced.

If the broker cannot revoke an old session, handoff cannot complete and
entry stays fenced (DRAINING/BROKER_RECONCILED hold); only exit, query,
and reconcile may continue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class HandoffError(RuntimeError):
    """Handoff/fencing failure with a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class HandoffState(StrEnum):
    ACTIVE = "active"
    DRAINING = "draining"
    BROKER_RECONCILED = "broker_reconciled"
    HANDOFF_COMPLETE = "handoff_complete"


_VALID_TRANSITIONS: dict[HandoffState, frozenset[HandoffState]] = {
    HandoffState.ACTIVE: frozenset({HandoffState.DRAINING}),
    HandoffState.DRAINING: frozenset({HandoffState.BROKER_RECONCILED}),
    HandoffState.BROKER_RECONCILED: frozenset({HandoffState.HANDOFF_COMPLETE}),
    HandoffState.HANDOFF_COMPLETE: frozenset(),
}


@dataclass(frozen=True)
class FenceProof:
    """Proof that the old writer's external reach is severed."""

    credential_revoked: bool
    session_revoked: bool
    network_egress_removed: bool
    proven_at: datetime
    # When the broker cannot revoke a session, a process/host termination
    # proof plus a network-policy proof substitutes for session revocation.
    termination_proof: bool = False
    network_policy_proof: bool = False


@dataclass(frozen=True)
class CursorCheckpoint:
    """The durable cursor the new writer resumes from."""

    inbox_cursor: str
    outbox_cursor: str
    broker_cursor: str
    fencing_epoch: int


@dataclass
class WriterHandoff:
    """Coordinates old -> new broker writer handoff under a fencing epoch."""

    _state: HandoffState = HandoffState.ACTIVE
    _fencing_epoch: int = 1
    _active_writer_id: str = "writer-1"
    _live_orders: int = 0
    _ambiguous_orders: int = 0
    _reconciled: bool = False
    _fence_proof: FenceProof | None = None

    @property
    def state(self) -> HandoffState:
        return self._state

    @property
    def fencing_epoch(self) -> int:
        return self._fencing_epoch

    @property
    def active_writer_id(self) -> str:
        return self._active_writer_id

    @property
    def entry_permitted(self) -> bool:
        """Entry is only permitted while ACTIVE under the live epoch."""

        return self._state is HandoffState.ACTIVE

    # -- old-worker drain path --------------------------------------------

    def begin_drain(
        self, *, live_orders: int, ambiguous_orders: int
    ) -> None:
        """Old worker stops entry and reports its in-flight order truth."""

        self._require(HandoffState.ACTIVE, "begin_drain")
        if live_orders < 0 or ambiguous_orders < 0:
            raise HandoffError(
                "INVALID_ORDER_COUNT", "order counts must be non-negative"
            )
        self._live_orders = live_orders
        self._ambiguous_orders = ambiguous_orders
        self._state = HandoffState.DRAINING

    def report_drained(self, *, remaining_live: int, remaining_ambiguous: int) -> None:
        """Advance DRAINING -> BROKER_RECONCILED once no live/ambiguous remain."""

        self._require(HandoffState.DRAINING, "report_drained")
        if remaining_live > 0:
            raise HandoffError(
                "LIVE_ORDER_REMAINS",
                f"{remaining_live} live orders still block handoff",
            )
        if remaining_ambiguous > 0:
            raise HandoffError(
                "AMBIGUOUS_ORDER_REMAINS",
                f"{remaining_ambiguous} ambiguous orders still block handoff",
            )
        self._live_orders = 0
        self._ambiguous_orders = 0
        self._state = HandoffState.BROKER_RECONCILED

    def mark_reconciled(self) -> None:
        """Record that the final broker reconciliation completed."""

        self._require(HandoffState.BROKER_RECONCILED, "mark_reconciled")
        self._reconciled = True

    def present_fence_proof(self, proof: FenceProof) -> None:
        """Bind the external credential/session/network fence proof."""

        self._require(HandoffState.BROKER_RECONCILED, "present_fence_proof")
        if not proof.credential_revoked:
            raise HandoffError(
                "CREDENTIAL_NOT_REVOKED",
                "old credential must be revoked before handoff",
            )
        if not proof.network_egress_removed:
            raise HandoffError(
                "NETWORK_EGRESS_NOT_REMOVED",
                "old network egress must be removed before handoff",
            )
        session_severed = proof.session_revoked or (
            proof.termination_proof and proof.network_policy_proof
        )
        if not session_severed:
            raise HandoffError(
                "SESSION_NOT_SEVERED",
                "broker session not revocable; termination proof +"
                " network-policy proof required",
            )
        self._fence_proof = proof

    # -- new-worker install path ------------------------------------------

    def complete(
        self,
        *,
        new_writer_id: str,
        checkpoint: CursorCheckpoint,
    ) -> int:
        """Install the new writer under the next fencing epoch.

        Returns the new epoch. The old epoch is permanently invalid after
        this call; any send presented under it is fenced.
        """

        self._require(HandoffState.BROKER_RECONCILED, "complete")
        if not self._reconciled:
            raise HandoffError(
                "NOT_RECONCILED", "broker reconciliation must complete first"
            )
        if self._fence_proof is None:
            raise HandoffError(
                "NO_FENCE_PROOF", "external fence proof must be presented first"
            )
        if checkpoint.fencing_epoch != self._fencing_epoch:
            raise HandoffError(
                "CURSOR_EPOCH_MISMATCH",
                f"checkpoint epoch {checkpoint.fencing_epoch} != current"
                f" {self._fencing_epoch}",
            )
        if not checkpoint.inbox_cursor or not checkpoint.outbox_cursor:
            raise HandoffError(
                "INCOMPLETE_CHECKPOINT",
                "inbox/outbox cursors must be present",
            )
        self._fencing_epoch += 1
        self._active_writer_id = new_writer_id
        self._state = HandoffState.HANDOFF_COMPLETE
        return self._fencing_epoch

    def activate_new_writer(self, *, writer_id: str, epoch: int) -> None:
        """Re-arm a fresh ACTIVE writer after a completed handoff."""

        if self._state is not HandoffState.HANDOFF_COMPLETE:
            raise HandoffError(
                "HANDOFF_INCOMPLETE", "cannot activate before HANDOFF_COMPLETE"
            )
        if epoch != self._fencing_epoch:
            raise HandoffError(
                "EPOCH_SUPERSEDED",
                f"presented epoch {epoch} != live {self._fencing_epoch}",
            )
        self._active_writer_id = writer_id
        self._state = HandoffState.ACTIVE

    # -- fencing enforcement ----------------------------------------------

    def fence_send(self, *, writer_id: str, epoch: int) -> None:
        """Reject any send not under the live writer + live epoch."""

        if self._state is not HandoffState.ACTIVE:
            raise HandoffError(
                "ENTRY_FENCED",
                f"entry not permitted in state {self._state.value}",
            )
        if writer_id != self._active_writer_id:
            raise HandoffError(
                "WRITER_NOT_AUTHORITY",
                f"writer {writer_id!r} is not the active authority",
            )
        if epoch != self._fencing_epoch:
            raise HandoffError(
                "EPOCH_SUPERSEDED",
                f"epoch {epoch} is permanently invalid (live"
                f" {self._fencing_epoch})",
            )

    def _require(self, expected: HandoffState, action: str) -> None:
        if self._state is not expected:
            raise HandoffError(
                "ILLEGAL_HANDOFF_TRANSITION",
                f"{action} requires {expected.value}, got {self._state.value}",
            )
