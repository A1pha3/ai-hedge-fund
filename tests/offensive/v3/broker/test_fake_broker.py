"""Plan 07 Task 1 (RED): DeterministicFakeBroker 行为测试.

锁定约束:
1. fake 实现完整 BrokerPort: submit/cancel/query_order/query_fills, 全部
   经 script 驱动, 行为确定性 (同 script 重放 = 同结果).
2. fake 与 dispatcher 之间只交换 BrokerRawEnvelope (authenticated raw
   payload), 绝不泄漏解析后对象 — durable-before-normalize 的边界在
   fake 上就可验证.
3. fake 支持脚本化 ack/reject/timeout/auth-failure/partial fill, 供
   Task 3 的 crash/timeout/ACK-persistence 矩阵复用.
4. fake 对同 client_order_id 重复 submit 的行为由脚本显式声明
   (duplicate_ack / duplicate_reject), 用于 Task 2 能力探针.
5. ProductionBrokerAdapter 未认证时 raise BROKER_ADAPTER_NOT_CERTIFIED;
   不导入任何 vendor SDK / 不读任何 credential env.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.screening.offensive.v3.broker.adapters.production import (
    ProductionBrokerAdapter,
    ProductionAdapterError,
)
from src.screening.offensive.v3.broker.ports import (
    BrokerAccountBinding,
    BrokerPort,
    BrokerTimeoutError,
    NewOrderCommand,
    OrderStatus,
)
from src.screening.offensive.v3.broker.fake import (
    DeterministicFakeBroker,
    FakeAction,
    FakeScript,
)

T0 = datetime(2026, 8, 7, 1, 0, 0, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64


def _binding() -> BrokerAccountBinding:
    return BrokerAccountBinding(
        account_id="acct-001",
        environment="sandbox",
        currency="CNY",
        endpoint_fingerprint=FINGERPRINT,
    )


def _command(client_order_id: str = "client-line-1") -> NewOrderCommand:
    return NewOrderCommand(
        client_order_id=client_order_id,
        security_id="000001",
        side="BUY",
        quantity_units=900,
        order_type="LIMIT",
        limit_price_cents=1000,
        time_in_force="DAY",
        account=_binding(),
    )


def _scripted(actions: list[FakeAction]) -> DeterministicFakeBroker:
    script = FakeScript(account=_binding(), actions=tuple(actions))
    return DeterministicFakeBroker(script)


def test_fake_is_a_broker_port() -> None:
    broker = _scripted([])
    assert isinstance(broker, BrokerPort)


def test_ack_action_returns_authenticated_envelope() -> None:
    broker = _scripted([FakeAction.ack(broker_order_id="B-9001")])
    envelope = broker.submit(_command())
    assert envelope.authenticated is True
    assert envelope.payload["kind"] == "order_ack"
    assert envelope.payload["broker_order_id"] == "B-9001"
    assert envelope.payload["client_order_id"] == "client-line-1"


def test_reject_action_returns_broker_code() -> None:
    broker = _scripted(
        [FakeAction.reject(broker_code="INSUFFICIENT_FUNDS")]
    )
    envelope = broker.submit(_command())
    assert envelope.payload["kind"] == "order_reject"
    assert envelope.payload["broker_code"] == "INSUFFICIENT_FUNDS"


def test_timeout_action_raises_broker_timeout() -> None:
    broker = _scripted([FakeAction.timeout()])
    with pytest.raises(BrokerTimeoutError):
        broker.submit(_command())


def test_duplicate_submit_same_client_id_is_scripted() -> None:
    broker = _scripted(
        [
            FakeAction.ack(broker_order_id="B-9001"),
            FakeAction.duplicate_ack(broker_order_id="B-9001"),
        ]
    )
    command = _command()
    first = broker.submit(command)
    second = broker.submit(command)
    assert (
        first.payload["broker_order_id"] == second.payload["broker_order_id"]
    )
    assert second.payload["duplicate"] is True


def test_script_replay_is_deterministic() -> None:
    actions = [
        FakeAction.ack(broker_order_id="B-1"),
        FakeAction.timeout(),
        FakeAction.reject(broker_code="X"),
    ]
    run_one = _scripted(list(actions))
    run_two = _scripted(list(actions))
    results_one: list[str] = []
    results_two: list[str] = []
    for broker, sink in ((run_one, results_one), (run_two, results_two)):
        for client_id in ("c1", "c2", "c3"):
            try:
                envelope = broker.submit(_command(client_id))
                sink.append(envelope.payload["kind"])
            except BrokerTimeoutError:
                sink.append("timeout")
    assert results_one == results_two == ["order_ack", "timeout", "order_reject"]


def test_cancel_action_returns_cancel_envelope() -> None:
    broker = _scripted(
        [
            FakeAction.ack(broker_order_id="B-9001"),
            FakeAction.cancel_ack(),
        ]
    )
    broker.submit(_command())
    envelope = broker.cancel("client-line-1")
    assert envelope.payload["kind"] == "cancel_ack"


def test_query_order_returns_authenticated_snapshot() -> None:
    broker = _scripted(
        [
            FakeAction.ack(broker_order_id="B-9001"),
            FakeAction.order_state(
                status=OrderStatus.PARTIALLY_FILLED.value,
                cumulative_quantity_units=100,
                cumulative_notional_cents=100_000,
                cumulative_fee_cents=30,
                leaves_quantity_units=800,
            ),
        ]
    )
    broker.submit(_command())
    envelope = broker.query_order("client-line-1")
    assert envelope.payload["kind"] == "order_state"
    assert envelope.payload["status"] == OrderStatus.PARTIALLY_FILLED.value


def test_unknown_client_query_is_unknown_not_error() -> None:
    broker = _scripted([FakeAction.unknown_order()])
    envelope = broker.query_order("never-seen")
    assert envelope.payload["status"] == OrderStatus.UNKNOWN.value


def test_unscripted_call_fails_closed() -> None:
    broker = _scripted([])
    with pytest.raises(Exception):
        broker.submit(_command())


# -- production adapter: disabled by default --------------------------------


def test_production_adapter_is_not_certified_by_default() -> None:
    with pytest.raises(ProductionAdapterError) as excinfo:
        ProductionBrokerAdapter()
    assert excinfo.value.code == "BROKER_ADAPTER_NOT_CERTIFIED"


def test_production_adapter_never_reads_credentials_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROKER_API_KEY", "leaked")
    monkeypatch.setenv("BROKER_API_SECRET", "leaked")
    with pytest.raises(ProductionAdapterError) as excinfo:
        ProductionBrokerAdapter()
    assert excinfo.value.code == "BROKER_ADAPTER_NOT_CERTIFIED"
