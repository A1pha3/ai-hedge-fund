"""Plan 07 Task 7 (RED): credential/session/network fencing + writer handoff.

锁定约束:
1. 状态机 ACTIVE -> DRAINING -> BROKER_RECONCILED -> HANDOFF_COMPLETE 严格
   单向; 非法跳转 = ILLEGAL_HANDOFF_TRANSITION.
2. entry 只在 ACTIVE 许可; DRAINING/BROKER_RECONCILED 期间 entry fenced,
   exit/query/reconcile 继续.
3. drain: live/ambiguous order 未清零 = LIVE/AMBIGUOUS_ORDER_REMAINS, 不前进.
4. fence proof: credential 必撤 / network egress 必移除 / session 撤销 或
   (termination_proof + network_policy_proof); 否则 SESSION_NOT_SEVERED.
5. complete: 必须先 reconciled + fence proof + cursor checkpoint; 返回新
   fencing epoch; 旧 epoch 永久失效.
6. fence_send: 非活跃 writer 或过期 epoch 的 send = WRITER_NOT_AUTHORITY /
   EPOCH_SUPERSEDED (旧 writer 复活 / 旧 socket/fd 重发被拒).
7. activate_new_writer 后新 worker 在新 epoch 下 ACTIVE.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.screening.offensive.v3.broker.handoff import (
    CursorCheckpoint,
    FenceProof,
    HandoffError,
    HandoffState,
    WriterHandoff,
)

T0 = datetime(2026, 8, 7, 10, 0, 0, tzinfo=timezone.utc)


def _proof(
    *,
    credential_revoked: bool = True,
    session_revoked: bool = True,
    network_egress_removed: bool = True,
    termination_proof: bool = False,
    network_policy_proof: bool = False,
) -> FenceProof:
    return FenceProof(
        credential_revoked=credential_revoked,
        session_revoked=session_revoked,
        network_egress_removed=network_egress_removed,
        termination_proof=termination_proof,
        network_policy_proof=network_policy_proof,
        proven_at=T0,
    )


def _checkpoint(epoch: int = 1) -> CursorCheckpoint:
    return CursorCheckpoint(
        inbox_cursor="inbox-1",
        outbox_cursor="outbox-1",
        broker_cursor="broker-1",
        fencing_epoch=epoch,
    )


def _drained_handoff() -> WriterHandoff:
    h = WriterHandoff()
    h.begin_drain(live_orders=2, ambiguous_orders=0)
    h.report_drained(remaining_live=0, remaining_ambiguous=0)
    h.mark_reconciled()
    return h


# -- state machine transitions ----------------------------------------------


def test_state_machine_progresses_in_order() -> None:
    h = WriterHandoff()
    assert h.state is HandoffState.ACTIVE
    assert h.entry_permitted is True
    h.begin_drain(live_orders=0, ambiguous_orders=0)
    assert h.state is HandoffState.DRAINING
    assert h.entry_permitted is False  # entry fenced while draining
    h.report_drained(remaining_live=0, remaining_ambiguous=0)
    assert h.state is HandoffState.BROKER_RECONCILED
    h.mark_reconciled()
    h.present_fence_proof(_proof())
    new_epoch = h.complete(new_writer_id="writer-2", checkpoint=_checkpoint())
    assert h.state is HandoffState.HANDOFF_COMPLETE
    assert new_epoch == 2


def test_illegal_skip_transition_rejected() -> None:
    h = WriterHandoff()
    with pytest.raises(HandoffError) as excinfo:
        h.report_drained(remaining_live=0, remaining_ambiguous=0)
    assert excinfo.value.code == "ILLEGAL_HANDOFF_TRANSITION"


def test_complete_before_reconciled_rejected() -> None:
    h = WriterHandoff()
    h.begin_drain(live_orders=0, ambiguous_orders=0)
    h.report_drained(remaining_live=0, remaining_ambiguous=0)
    with pytest.raises(HandoffError) as excinfo:
        h.complete(new_writer_id="w2", checkpoint=_checkpoint())
    assert excinfo.value.code == "NOT_RECONCILED"


# -- drain blocks ----------------------------------------------------------


def test_live_order_remaining_blocks_handoff() -> None:
    h = WriterHandoff()
    h.begin_drain(live_orders=1, ambiguous_orders=0)
    with pytest.raises(HandoffError) as excinfo:
        h.report_drained(remaining_live=1, remaining_ambiguous=0)
    assert excinfo.value.code == "LIVE_ORDER_REMAINS"
    assert h.state is HandoffState.DRAINING


def test_ambiguous_order_remaining_blocks_handoff() -> None:
    h = WriterHandoff()
    h.begin_drain(live_orders=0, ambiguous_orders=1)
    with pytest.raises(HandoffError) as excinfo:
        h.report_drained(remaining_live=0, remaining_ambiguous=1)
    assert excinfo.value.code == "AMBIGUOUS_ORDER_REMAINS"


# -- fence proof -----------------------------------------------------------


def test_credential_not_revoked_rejected() -> None:
    h = _drained_handoff()
    with pytest.raises(HandoffError) as excinfo:
        h.present_fence_proof(_proof(credential_revoked=False))
    assert excinfo.value.code == "CREDENTIAL_NOT_REVOKED"


def test_network_egress_not_removed_rejected() -> None:
    h = _drained_handoff()
    with pytest.raises(HandoffError) as excinfo:
        h.present_fence_proof(_proof(network_egress_removed=False))
    assert excinfo.value.code == "NETWORK_EGRESS_NOT_REMOVED"


def test_irrevocable_session_requires_termination_and_policy_proof() -> None:
    h = _drained_handoff()
    # Session not revocable, and no termination proof -> rejected.
    with pytest.raises(HandoffError) as excinfo:
        h.present_fence_proof(
            _proof(session_revoked=False, termination_proof=False, network_policy_proof=False)
        )
    assert excinfo.value.code == "SESSION_NOT_SEVERED"
    # With termination proof + network-policy proof, accepted.
    h.present_fence_proof(
        _proof(
            session_revoked=False,
            termination_proof=True,
            network_policy_proof=True,
        )
    )


def test_no_fence_proof_blocks_complete() -> None:
    h = _drained_handoff()
    # Skip present_fence_proof.
    with pytest.raises(HandoffError) as excinfo:
        h.complete(new_writer_id="w2", checkpoint=_checkpoint())
    assert excinfo.value.code == "NO_FENCE_PROOF"


def test_cursor_epoch_mismatch_rejected() -> None:
    h = _drained_handoff()
    h.present_fence_proof(_proof())
    with pytest.raises(HandoffError) as excinfo:
        h.complete(new_writer_id="w2", checkpoint=_checkpoint(epoch=99))
    assert excinfo.value.code == "CURSOR_EPOCH_MISMATCH"


# -- fencing enforcement ---------------------------------------------------


def test_old_writer_cannot_send_after_handoff() -> None:
    h = _drained_handoff()
    h.present_fence_proof(_proof())
    h.complete(new_writer_id="writer-2", checkpoint=_checkpoint())
    h.activate_new_writer(writer_id="writer-2", epoch=2)
    # Old writer (writer-1) at the old epoch is fenced.
    with pytest.raises(HandoffError) as excinfo:
        h.fence_send(writer_id="writer-1", epoch=1)
    assert excinfo.value.code == "WRITER_NOT_AUTHORITY"
    # New writer at the live epoch is permitted.
    h.fence_send(writer_id="writer-2", epoch=2)


def test_old_epoch_permanently_invalid() -> None:
    h = _drained_handoff()
    h.present_fence_proof(_proof())
    h.complete(new_writer_id="writer-2", checkpoint=_checkpoint())
    h.activate_new_writer(writer_id="writer-2", epoch=2)
    # Even presenting the OLD writer's id is rejected; and a stale epoch
    # under the NEW writer is rejected.
    with pytest.raises(HandoffError) as excinfo:
        h.fence_send(writer_id="writer-2", epoch=1)
    assert excinfo.value.code == "EPOCH_SUPERSEDED"


def test_send_while_draining_is_fenced() -> None:
    h = WriterHandoff()
    h.begin_drain(live_orders=0, ambiguous_orders=0)
    with pytest.raises(HandoffError) as excinfo:
        h.fence_send(writer_id="writer-1", epoch=1)
    assert excinfo.value.code == "ENTRY_FENCED"


def test_new_writer_early_send_before_activation_rejected() -> None:
    h = _drained_handoff()
    h.present_fence_proof(_proof())
    h.complete(new_writer_id="writer-2", checkpoint=_checkpoint())
    # HANDOFF_COMPLETE but not yet activated -> entry fenced.
    with pytest.raises(HandoffError) as excinfo:
        h.fence_send(writer_id="writer-2", epoch=2)
    assert excinfo.value.code == "ENTRY_FENCED"


def test_activate_requires_completed_handoff() -> None:
    h = _drained_handoff()
    with pytest.raises(HandoffError) as excinfo:
        h.activate_new_writer(writer_id="writer-2", epoch=2)
    assert excinfo.value.code == "HANDOFF_INCOMPLETE"
