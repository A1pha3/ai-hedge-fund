"""Plan 07 Task 3 (RED): SEND_CLAIMED dispatcher + ambiguous submission.

锁定约束:
1. run_once 序列: claim_send (Gateway 线性化) -> 发送 exact immutable
   payload + exact client id -> durable append raw receipt -> report
   BROKER_ACK / SUBMISSION_AMBIGUOUS. dispatcher 不改 authorization/
   seal/reserve/capital.
2. 只发送 Gateway claim 释放的 client id; permit shrink-to-zero 的 line
   无 client id, 不发送.
3. 超时 / 未认证响应 = SUBMISSION_AMBIGUOUS (无 durable ACK); 已 ack 的
   line 的 raw revision 仍持久化.
4. 重发 (resend) 只复用 EXACT 相同 client id/payload — 生成新 ID 猜测重发
   被禁止; resend 要求状态为 SUBMISSION_AMBIGUOUS.
5. stale seal/envelope/capital/risk/stage/fence 在 claim 边界被 Gateway
   拒绝 (dispatcher 不绕过 Gateway 事务).
6. shadow/proxy/manual 输入不进入 broker 提交 (只接受真实 BrokerPort).
7. crash after claim before durable ACK => 新 dispatcher resend 复用同 ID.
"""

from __future__ import annotations

from dataclasses import replace as dc_replace
from datetime import timedelta
from pathlib import Path

import pytest

from src.screening.offensive.v3.broker.dispatcher import (
    BrokerDispatcher,
    DispatcherError,
)
from src.screening.offensive.v3.broker.fake import (
    DeterministicFakeBroker,
    FakeAction,
    FakeScript,
)
from src.screening.offensive.v3.broker.ports import BrokerAccountBinding
from src.screening.offensive.v3.broker.raw_inbox import BrokerRawInbox
from src.screening.offensive.v3.contracts import RiskLatchState
from src.screening.offensive.v3.gateway.decisions import (
    CapitalGatewayError,
    DeliveryOutcome,
)

from tests.offensive.v3.broker.helpers import Clock, drive_to_outbox
from tests.offensive.v3.contracts.checkpoint2_helpers import PERMIT_EXPIRES

FINGERPRINT = "a" * 64


def _account() -> BrokerAccountBinding:
    return BrokerAccountBinding(
        account_id="broker-account-v3",
        environment="sandbox",
        currency="CNY",
        endpoint_fingerprint=FINGERPRINT,
    )


def _scripted(actions: list[FakeAction]) -> DeterministicFakeBroker:
    return DeterministicFakeBroker(
        FakeScript(account=_account(), actions=tuple(actions))
    )


def _rig_and_dispatcher(
    tmp_path: Path,
    broker: DeterministicFakeBroker,
    *,
    name: str = "gw",
):
    db = tmp_path / f"{name}.sqlite3"
    rig = drive_to_outbox(db, Clock())
    inbox = BrokerRawInbox(str(tmp_path / f"raw-{name}.sqlite3"))
    dispatcher = BrokerDispatcher(
        gateway=rig.gateway, broker=broker, inbox=inbox, account=_account()
    )
    return dispatcher, rig, inbox


ACKS = [FakeAction.ack(broker_order_id="B-1"), FakeAction.ack(broker_order_id="B-2")]


# -- happy path -------------------------------------------------------------


def test_run_once_sends_claimed_lines_and_reports_broker_ack(tmp_path) -> None:
    dispatcher, rig, inbox = _rig_and_dispatcher(tmp_path, _scripted(list(ACKS)))
    outcome = dispatcher.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    assert outcome.delivery is DeliveryOutcome.BROKER_ACK
    assert len(outcome.submissions) == 2
    assert {s.client_order_id for s in outcome.submissions} == {
        "client-line-1",
        "client-line-2",
    }
    assert all(s.status == "acked" for s in outcome.submissions)
    assert all(s.raw_revision is not None for s in outcome.submissions)
    state = rig.gateway.entry_state(rig.seal.seal_id)
    assert state.status == "BROKER_ACK"
    assert inbox.count() == 2


def test_submitted_commands_carry_permit_truth(tmp_path) -> None:
    dispatcher, rig, inbox = _rig_and_dispatcher(tmp_path, _scripted(list(ACKS)))
    outcome = dispatcher.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    line_by_id = {ln.order_line_id: ln for ln in rig.permit.permit_lines}
    for sub in outcome.submissions:
        line = line_by_id[sub.order_line_id]
        assert sub.security_id == line.security_id
        assert sub.quantity_units == line.permitted_quantity_units


# -- timeout / ambiguous ----------------------------------------------------


def test_timeout_records_submission_ambiguous(tmp_path) -> None:
    actions = [FakeAction.timeout(), FakeAction.ack(broker_order_id="B-2")]
    dispatcher, rig, inbox = _rig_and_dispatcher(tmp_path, _scripted(actions))
    outcome = dispatcher.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    assert outcome.delivery is DeliveryOutcome.SUBMISSION_AMBIGUOUS
    statuses = {s.client_order_id: s.status for s in outcome.submissions}
    assert statuses["client-line-1"] == "timeout"
    assert statuses["client-line-2"] == "acked"
    # The acked line's receipt is still durably persisted.
    assert inbox.count() == 1
    state = rig.gateway.entry_state(rig.seal.seal_id)
    assert state.status == "SUBMISSION_AMBIGUOUS"


def test_unauthenticated_response_is_ambiguous(tmp_path) -> None:
    actions = [FakeAction.auth_failure(), FakeAction.ack(broker_order_id="B-2")]
    dispatcher, rig, inbox = _rig_and_dispatcher(tmp_path, _scripted(actions))
    outcome = dispatcher.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    assert outcome.delivery is DeliveryOutcome.SUBMISSION_AMBIGUOUS
    assert inbox.count() == 1  # only the authenticated ack persisted


# -- resend: exact same client id, no new id --------------------------------


def test_resend_reuses_exact_client_ids_after_ambiguous(tmp_path) -> None:
    actions = [
        FakeAction.timeout(),
        FakeAction.ack(broker_order_id="B-2"),
        FakeAction.ack(broker_order_id="B-1"),
    ]
    dispatcher, rig, inbox = _rig_and_dispatcher(tmp_path, _scripted(actions))
    first = dispatcher.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    assert first.delivery is DeliveryOutcome.SUBMISSION_AMBIGUOUS
    second = dispatcher.resend(rig.permit, context=rig.claim_context)
    assert second.delivery is DeliveryOutcome.BROKER_ACK
    # Only the previously-unacked line is resent; the acked line is not
    # double-submitted. Both client ids remain the exact claimed ones.
    assert [s.client_order_id for s in second.submissions] == ["client-line-1"]
    state = rig.gateway.entry_state(rig.seal.seal_id)
    assert state.status == "BROKER_ACK"


def test_resend_requires_ambiguous_state(tmp_path) -> None:
    dispatcher, rig, inbox = _rig_and_dispatcher(tmp_path, _scripted(list(ACKS)))
    dispatcher.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    # Already BROKER_ACK — resend must refuse (no double-submit).
    with pytest.raises(DispatcherError) as excinfo:
        dispatcher.resend(rig.permit, context=rig.claim_context)
    assert excinfo.value.code == "RESEND_STATE_CONFLICT"


# -- crash recovery: claim consumed, new dispatcher resend replays same id --


def test_crash_after_claim_resumes_via_resend(tmp_path) -> None:
    actions = [
        FakeAction.timeout(),
        FakeAction.ack(broker_order_id="B-2"),
        FakeAction.ack(broker_order_id="B-1"),
    ]
    broker = _scripted(actions)
    db = tmp_path / "gw.sqlite3"
    rig = drive_to_outbox(db, Clock())
    inbox = BrokerRawInbox(str(tmp_path / "raw.sqlite3"))
    dispatcher = BrokerDispatcher(
        gateway=rig.gateway, broker=broker, inbox=inbox, account=_account()
    )
    dispatcher.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    # Simulate a process restart: a NEW dispatcher over the same stores.
    restarted = BrokerDispatcher(
        gateway=rig.gateway, broker=broker, inbox=inbox, account=_account()
    )
    outcome = restarted.resend(rig.permit, context=rig.claim_context)
    assert outcome.delivery is DeliveryOutcome.BROKER_ACK


# -- reject is never an ACK (audit C1) ----------------------------------------


def test_broker_reject_is_not_an_ack(tmp_path) -> None:
    """A durable REJECT must not let the entry claim BROKER_ACK (audit C1)."""
    actions = [
        FakeAction.reject(broker_code="INSUFFICIENT_FUNDS"),
        FakeAction.ack(broker_order_id="B-2"),
    ]
    dispatcher, rig, inbox = _rig_and_dispatcher(tmp_path, _scripted(actions))
    outcome = dispatcher.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    # The rejected line is terminal but NOT accepted → the entry stays
    # ambiguous pending reconciliation; it never claims full BROKER_ACK.
    assert outcome.delivery is DeliveryOutcome.SUBMISSION_AMBIGUOUS
    statuses = {s.client_order_id: s.status for s in outcome.submissions}
    assert statuses["client-line-1"] == "rejected"
    assert statuses["client-line-2"] == "acked"
    assert inbox.count() == 2  # both receipts durably persisted
    assert rig.gateway.entry_state(rig.seal.seal_id).status == "SUBMISSION_AMBIGUOUS"


def test_resend_after_reject_never_promotes_to_ack(tmp_path) -> None:
    """A reject followed by a successful resend of the other line still must
    not promote the entry to BROKER_ACK (audit C1)."""
    actions = [
        FakeAction.reject(broker_code="INSUFFICIENT_FUNDS"),
        FakeAction.timeout(),
        FakeAction.ack(broker_order_id="B-2"),
    ]
    dispatcher, rig, inbox = _rig_and_dispatcher(tmp_path, _scripted(actions))
    first = dispatcher.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    assert first.delivery is DeliveryOutcome.SUBMISSION_AMBIGUOUS
    # Resend retries only the timed-out line; the rejected line is terminal.
    second = dispatcher.resend(rig.permit, context=rig.claim_context)
    assert [s.client_order_id for s in second.submissions] == ["client-line-2"]
    # Even though every line now holds a terminal receipt, line-1 was REJECTED,
    # so the entry must remain ambiguous rather than claim BROKER_ACK.
    assert second.delivery is DeliveryOutcome.SUBMISSION_AMBIGUOUS
    assert rig.gateway.entry_state(rig.seal.seal_id).status == "SUBMISSION_AMBIGUOUS"


# -- resend preconditions: certified idempotency + broker cutoff (audit M4) ---


def test_resend_after_cutoff_refused(tmp_path) -> None:
    """A resend past the broker cutoff must be refused, not re-fired (M4)."""
    actions = [FakeAction.timeout(), FakeAction.timeout()]
    dispatcher, rig, inbox = _rig_and_dispatcher(tmp_path, _scripted(actions))
    dispatcher.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    with pytest.raises(DispatcherError) as excinfo:
        dispatcher.resend(
            rig.permit,
            context=rig.claim_context,
            broker_cutoff=PERMIT_EXPIRES,
            now=PERMIT_EXPIRES + timedelta(minutes=5),  # past cutoff
        )
    assert excinfo.value.code == "BROKER_CUTOFF_PASSED"


def test_resend_without_certified_idempotency_refused(tmp_path) -> None:
    """A resend whose client-id idempotency is not certified is refused (M4)."""
    actions = [FakeAction.timeout(), FakeAction.timeout()]
    dispatcher, rig, inbox = _rig_and_dispatcher(tmp_path, _scripted(actions))
    dispatcher.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    with pytest.raises(DispatcherError) as excinfo:
        dispatcher.resend(
            rig.permit,
            context=rig.claim_context,
            certified_idempotent=False,
        )
    assert excinfo.value.code == "IDEMPOTENCY_UNPROVEN"



def test_stale_risk_halt_blocks_claim_and_sends_nothing(tmp_path) -> None:
    broker = _scripted(list(ACKS))
    dispatcher, rig, inbox = _rig_and_dispatcher(tmp_path, broker)
    halted = dc_replace(rig.claim_context, risk_latch=RiskLatchState.RISK_HALTED)
    with pytest.raises(CapitalGatewayError) as excinfo:
        dispatcher.run_once(
            rig.permit, rig.permit.send_claim_expected_versions,
            context=halted,
        )
    assert excinfo.value.code == "risk_halt_blocks_send"
    # No broker submit occurred (the claim rejected before any send).
    assert broker._cursor == 0
    assert inbox.count() == 0


def test_expired_send_deadline_blocks_claim(tmp_path) -> None:
    broker = _scripted(list(ACKS))
    clock = Clock()
    db = tmp_path / "gw.sqlite3"
    rig = drive_to_outbox(db, clock)
    inbox = BrokerRawInbox(str(tmp_path / "raw.sqlite3"))
    dispatcher = BrokerDispatcher(
        gateway=rig.gateway, broker=broker, inbox=inbox, account=_account()
    )
    clock.now_value = PERMIT_EXPIRES
    with pytest.raises(CapitalGatewayError) as excinfo:
        dispatcher.run_once(
            rig.permit, rig.permit.send_claim_expected_versions,
            context=rig.claim_context,
        )
    assert excinfo.value.code == "send_deadline_missed"
    assert broker._cursor == 0


# -- only a real BrokerPort is accepted (no shadow/proxy/manual leakage) ----


class _NotABrokerPort:
    """A stand-in that does not implement BrokerPort."""

    def submit(self, command):  # pragma: no cover - structural guard
        raise AssertionError("shadow/proxy/manual must never reach submit")


def test_dispatcher_requires_real_broker_port(tmp_path) -> None:
    db = tmp_path / "gw.sqlite3"
    rig = drive_to_outbox(db, Clock())
    inbox = BrokerRawInbox(str(tmp_path / "raw.sqlite3"))
    # Constructing the dispatcher with a non-BrokerPort must fail immediately
    # — shadow/proxy/manual inputs never reach broker submission.
    with pytest.raises(TypeError):
        BrokerDispatcher(
            gateway=rig.gateway,
            broker=_NotABrokerPort(),  # type: ignore[arg-type]
            inbox=inbox,
            account=_account(),
        )


# -- duplicate dispatcher over the same outbox: only one claim wins --------


def test_duplicate_dispatcher_only_one_claim_wins(tmp_path) -> None:
    broker = _scripted(list(ACKS))
    db = tmp_path / "gw.sqlite3"
    rig = drive_to_outbox(db, Clock())
    inbox = BrokerRawInbox(str(tmp_path / "raw.sqlite3"))
    dispatcher_a = BrokerDispatcher(
        gateway=rig.gateway, broker=broker, inbox=inbox, account=_account()
    )
    dispatcher_b = BrokerDispatcher(
        gateway=rig.gateway, broker=broker, inbox=inbox, account=_account()
    )
    outcome_a = dispatcher_a.run_once(
        rig.permit, rig.permit.send_claim_expected_versions,
        context=rig.claim_context,
    )
    assert outcome_a.delivery is DeliveryOutcome.BROKER_ACK
    # The second dispatcher cannot re-claim the already-claimed entry.
    with pytest.raises(CapitalGatewayError) as excinfo:
        dispatcher_b.run_once(
            rig.permit, rig.permit.send_claim_expected_versions,
            context=rig.claim_context,
        )
    assert excinfo.value.code == "send_claim_conflict"
