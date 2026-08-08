"""Plan 08 Task 1 (RED): BrokerRuntime send-path fence wiring.

锁定约束:
1. submit_entry/submit_resend 在触 dispatcher 前强制 fence: 非 live
   writer / stale epoch / DR 未完成 → fail-closed, fake broker 收不到任何
   命令 (dispatcher 完全不被调用, 无 claim/无 receipt).
2. fencing_epoch 从 fence 权威即时读取 (DR 存在时取 DR, 否则 handoff),
   不作构造期快照 — handoff/DR 完成后 epoch 自动跟进.
3. 正路径: live writer + live epoch + ACTIVE → 正常发送 (不破坏 dispatcher).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.screening.offensive.v3.broker.disaster_recovery import (
    DisasterRecoveryCoordinator,
    DisasterRecoveryError,
)
from src.screening.offensive.v3.broker.dispatcher import BrokerDispatcher
from src.screening.offensive.v3.broker.fake import (
    DeterministicFakeBroker,
    FakeAction,
    FakeScript,
)
from src.screening.offensive.v3.broker.handoff import (
    CursorCheckpoint,
    FenceProof,
    HandoffError,
    WriterHandoff,
)
from src.screening.offensive.v3.broker.ports import BrokerAccountBinding
from src.screening.offensive.v3.broker.raw_inbox import BrokerRawInbox
from src.screening.offensive.v3.broker.runtime import (
    BrokerRuntime,
    BrokerRuntimeError,
)
from src.screening.offensive.v3.gateway.decisions import DeliveryOutcome

from tests.offensive.v3.broker.helpers import Clock, drive_to_outbox
from tests.offensive.v3.broker.test_disaster_recovery import _full_restore

FINGERPRINT = "a" * 64

# drive_to_outbox 的默认 permit 产 2 条 order line → 正路径须脚本 2 个 ack
# (与 test_dispatcher.py 的 ACKS 一致), 否则第二条 FakeScriptExhausted.
ACKS = [FakeAction.ack(broker_order_id="B-1"), FakeAction.ack(broker_order_id="B-2")]


def _account() -> BrokerAccountBinding:
    return BrokerAccountBinding(
        account_id="broker-account-v3",
        environment="sandbox",
        currency="CNY",
        endpoint_fingerprint=FINGERPRINT,
    )


def _broker(*actions: FakeAction) -> DeterministicFakeBroker:
    return DeterministicFakeBroker(FakeScript(account=_account(), actions=tuple(actions)))


def _runtime(
    tmp_path: Path,
    broker: DeterministicFakeBroker,
    *,
    writer_id: str = "writer-1",
    handoff: WriterHandoff | None = None,
    recovery=None,
    name: str = "gw",
):
    """真实 gateway driven to outbox + runtime 包裹的 dispatcher."""

    rig = drive_to_outbox(tmp_path / f"{name}.sqlite3", Clock())
    inbox = BrokerRawInbox(str(tmp_path / f"raw-{name}.sqlite3"))
    dispatcher = BrokerDispatcher(
        gateway=rig.gateway, broker=broker, inbox=inbox, account=_account()
    )
    rt = BrokerRuntime(
        dispatcher=dispatcher,
        handoff=handoff if handoff is not None else WriterHandoff(),
        writer_id=writer_id,
        recovery=recovery,
    )
    return rt, rig, inbox, broker


def _sent(broker: DeterministicFakeBroker) -> int:
    """已派发到 fake broker 的命令数 (fail-closed 可观测锚点)."""

    return broker._cursor


# -- 正路径 -----------------------------------------------------------------


def test_submit_entry_live_writer_sends(tmp_path) -> None:
    rt, rig, inbox, broker = _runtime(tmp_path, _broker(*ACKS))
    outcome = rt.submit_entry(
        rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
    )
    assert outcome.delivery is DeliveryOutcome.BROKER_ACK
    assert _sent(broker) == 2  # 2 条 order line 全发出


# -- handoff fence ----------------------------------------------------------


def test_submit_entry_fenced_when_not_active(tmp_path) -> None:
    broker = _broker(*ACKS)
    handoff = WriterHandoff()
    handoff.begin_drain(live_orders=0, ambiguous_orders=0)  # ACTIVE -> DRAINING
    rt, rig, inbox, _ = _runtime(tmp_path, broker, handoff=handoff)
    with pytest.raises(HandoffError) as exc:
        rt.submit_entry(
            rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
        )
    assert exc.value.code == "ENTRY_FENCED"
    assert _sent(broker) == 0  # dispatcher 未被触达


def test_submit_entry_rejects_non_authority_writer(tmp_path) -> None:
    broker = _broker(*ACKS)
    rt, rig, inbox, _ = _runtime(tmp_path, broker, writer_id="intruder")
    with pytest.raises(HandoffError) as exc:
        rt.submit_entry(
            rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
        )
    assert exc.value.code == "WRITER_NOT_AUTHORITY"
    assert _sent(broker) == 0


def test_submit_entry_stale_writer_after_handoff_fenced(tmp_path) -> None:
    """M1 核心回归: handoff 完成并 re-arm writer-2 (epoch 2, ACTIVE) 后, 旧
    writer-1 的 runtime 在 send path 被实际判为非 authority, fake broker 收不到
    命令 — 而非仅靠进程内不变式."""

    broker = _broker(*ACKS)
    handoff = WriterHandoff()
    handoff.begin_drain(live_orders=0, ambiguous_orders=0)
    handoff.report_drained(remaining_live=0, remaining_ambiguous=0)
    handoff.mark_reconciled()
    handoff.present_fence_proof(
        FenceProof(
            credential_revoked=True,
            session_revoked=True,
            network_egress_removed=True,
            proven_at=Clock()(),
        )
    )
    ck = CursorCheckpoint(
        inbox_cursor="i1", outbox_cursor="o1", broker_cursor="b1",
        fencing_epoch=handoff.fencing_epoch,
    )
    new_epoch = handoff.complete(new_writer_id="writer-2", checkpoint=ck)
    assert new_epoch == 2
    # re-arm 新 writer 使状态回 ACTIVE → fence 判定走到 writer 检查.
    handoff.activate_new_writer(writer_id="writer-2", epoch=new_epoch)
    # 旧 writer runtime: writer-1 已不是 authority.
    rt, rig, inbox, _ = _runtime(tmp_path, broker, writer_id="writer-1", handoff=handoff)
    with pytest.raises(HandoffError) as exc:
        rt.submit_entry(
            rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
        )
    assert exc.value.code == "WRITER_NOT_AUTHORITY"
    assert _sent(broker) == 0


# -- DR 门 -------------------------------------------------------------------


def test_submit_entry_fenced_during_incomplete_recovery(tmp_path) -> None:
    broker = _broker(*ACKS)
    rt, rig, inbox, _ = _runtime(
        tmp_path, broker, recovery=DisasterRecoveryCoordinator()  # PRE_RESTORE
    )
    # DR fence_send 透出 DisasterRecoveryError(ENTRY_FENCED), 与 handoff 平行.
    with pytest.raises(DisasterRecoveryError) as exc:
        rt.submit_entry(
            rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
        )
    assert exc.value.code == "ENTRY_FENCED"
    assert _sent(broker) == 0


def test_submit_entry_after_recovery_uses_raised_epoch(tmp_path) -> None:
    broker = _broker(*ACKS)
    recovery = _full_restore()  # RECOVERY_COMPLETE, fencing_epoch 3, writer-2
    assert recovery.entry_permitted and recovery.fencing_epoch == 3
    # DR 是 fence 权威: 完成后 send path 经 DR.fence_send (涵盖 writer+epoch).
    rt, rig, inbox, _ = _runtime(tmp_path, broker, writer_id="writer-2", recovery=recovery)
    assert rt.current_fencing_epoch() == 3  # epoch 取自 DR, 非 handoff 快照
    outcome = rt.submit_entry(
        rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
    )
    assert outcome.delivery is DeliveryOutcome.BROKER_ACK
    assert _sent(broker) == 2


def test_submit_entry_after_recovery_rejects_old_writer(tmp_path) -> None:
    """DR 完成后, 旧 writer (非 DR 确立的 writer-2) 在 send path 被 DR fence 拦下."""

    broker = _broker(*ACKS)
    recovery = _full_restore()  # writer-2 是新 authority
    rt, rig, inbox, _ = _runtime(tmp_path, broker, writer_id="writer-1", recovery=recovery)
    with pytest.raises(DisasterRecoveryError) as exc:
        rt.submit_entry(
            rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
        )
    assert exc.value.code == "WRITER_NOT_AUTHORITY"
    assert _sent(broker) == 0


# -- resend 同样被 fence -----------------------------------------------------


def test_submit_resend_fenced_for_non_authority_writer(tmp_path) -> None:
    broker = _broker()  # 无脚本: 若 dispatcher 被触达会 FakeScriptExhausted
    rt, rig, inbox, _ = _runtime(tmp_path, broker, writer_id="intruder")
    with pytest.raises(HandoffError) as exc:
        rt.submit_resend(rig.permit, context=rig.claim_context)
    assert exc.value.code == "WRITER_NOT_AUTHORITY"
    assert _sent(broker) == 0


# -- fence 失败零副作用 ------------------------------------------------------


def test_fence_failure_leaves_no_claim_no_receipt(tmp_path) -> None:
    broker = _broker(*ACKS)
    rt, rig, inbox, _ = _runtime(tmp_path, broker, writer_id="intruder")
    with pytest.raises(HandoffError):
        rt.submit_entry(
            rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
        )
    assert _sent(broker) == 0
    # dispatcher 未被触达: inbox 无 receipt, gateway entry 无 delivery 记录.
    assert len(list(inbox.iter_all())) == 0
