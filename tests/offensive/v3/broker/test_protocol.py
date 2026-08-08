"""Plan 07 Task 1 (RED): broker-neutral 协议边界契约测试.

锁定约束:
1. BrokerRawEnvelope 是 authenticated 的原始 broker payload: 认证位、broker
   观测时刻、本地接收时刻、账号、environment、source sequence、parser version
   全部强制; 缺失即结构拒绝 (fail-closed, 不得默认 authenticated=True).
2. 恶意/不一致的认证元数据 (authenticated=True 但空/非法 auth_fingerprint)
   必须结构拒绝 — 不得拖到 normalize 阶段才暴露.
3. BrokerAccountBinding 精确绑定 account/environment/currency/endpoint
   fingerprint — broker 侧漂移在协议边界即拒绝 (Task 2 再绑定签名清单).
4. OrderAck 提供 broker_order_id 与 broker 接收时刻; OrderReject 携带
   broker 的 code/message; OrderUpdate 覆盖 partial/cancel/reject/expire/
   late fill, cumulative 字段语义 = broker 至今累计值 (delta 由 Task 4 派生).
5. UNKNOWN status 不得映射成任何 terminal 状态 — 保持 unknown/no-entry.
6. 全部时间戳必须是 UTC instant; 数值禁止 float (Decimal/int only).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.screening.offensive.v3.broker.ports import (
    BrokerAccountBinding,
    BrokerOrderAck,
    BrokerOrderReject,
    BrokerOrderUpdate,
    BrokerRawEnvelope,
    NewOrderCommand,
    OrderStatus,
)

RECEIVED_AT = datetime(2026, 8, 7, 1, 0, 1, tzinfo=timezone.utc)
BROKER_OBSERVED_AT = datetime(2026, 8, 7, 1, 0, 0, tzinfo=timezone.utc)

FINGERPRINT = "a" * 64


def _binding() -> BrokerAccountBinding:
    return BrokerAccountBinding(
        account_id="acct-001",
        environment="sandbox",
        currency="CNY",
        endpoint_fingerprint=FINGERPRINT,
    )


def _envelope_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "authenticated": True,
        "auth_fingerprint": FINGERPRINT,
        "source": "broker-push",
        "source_sequence": 1,
        "parser_version": "v1",
        "broker_observed_at": BROKER_OBSERVED_AT,
        "received_at": RECEIVED_AT,
        "account": _binding(),
        "payload": {"kind": "order_update", "order_id": "B1"},
    }
    base.update(overrides)
    return base


def _new_order() -> NewOrderCommand:
    return NewOrderCommand(
        client_order_id="client-line-1",
        security_id="000001",
        side="BUY",
        quantity_units=900,
        order_type="LIMIT",
        limit_price_cents=1000,
        time_in_force="DAY",
        account=_binding(),
    )


# -- BrokerRawEnvelope: authentication is mandatory, never defaulted -------


def test_authenticated_envelope_round_trips_canonically() -> None:
    envelope = BrokerRawEnvelope(**_envelope_kwargs())
    assert envelope.authenticated is True
    assert envelope.content_hash() == BrokerRawEnvelope.model_validate_json(
        envelope.model_dump_json()
    ).content_hash()


def test_authentication_must_be_explicit() -> None:
    payload = _envelope_kwargs()
    del payload["authenticated"]
    with pytest.raises(ValueError):
        BrokerRawEnvelope(**payload)


@pytest.mark.parametrize("fingerprint", ["", "not-a-hash", "G" * 64])
def test_malformed_auth_fingerprint_rejected(fingerprint: str) -> None:
    with pytest.raises(ValueError):
        BrokerRawEnvelope(
            **_envelope_kwargs(auth_fingerprint=fingerprint)
        )


def test_unauthenticated_envelope_can_exist_but_never_defaults() -> None:
    # 未认证信封是合法输入 (raw inbox 原样留存), 但必须显式声明.
    envelope = BrokerRawEnvelope(
        **_envelope_kwargs(authenticated=False, auth_fingerprint=None)
    )
    assert envelope.authenticated is False
    assert envelope.auth_fingerprint is None


def test_unauthenticated_envelope_forbids_fingerprint() -> None:
    with pytest.raises(ValueError):
        BrokerRawEnvelope(**_envelope_kwargs(authenticated=False))


def test_missing_auth_fingerprint_rejected() -> None:
    with pytest.raises(ValueError):
        BrokerRawEnvelope(**_envelope_kwargs(auth_fingerprint=None))


def test_unknown_extra_field_rejected() -> None:
    with pytest.raises(ValueError):
        BrokerRawEnvelope(**_envelope_kwargs(unexpected="nope"))


# -- timestamp discipline ----------------------------------------------------


def test_naive_broker_timestamp_rejected() -> None:
    with pytest.raises(ValueError):
        BrokerRawEnvelope(
            **_envelope_kwargs(
                broker_observed_at=BROKER_OBSERVED_AT.replace(tzinfo=None)
            )
        )


def test_non_utc_offset_rejected() -> None:
    offset_time = BROKER_OBSERVED_AT.astimezone(
        timezone(timedelta(hours=8))
    )
    with pytest.raises(ValueError):
        BrokerRawEnvelope(**_envelope_kwargs(received_at=offset_time))


# -- account binding -----------------------------------------------------------


def test_account_binding_is_exact_and_frozen() -> None:
    binding = _binding()
    with pytest.raises(ValueError):
        binding.account_id = "acct-002"  # type: ignore[misc]
    other = BrokerAccountBinding(
        account_id="acct-001",
        environment="production",
        currency="CNY",
        endpoint_fingerprint=FINGERPRINT,
    )
    assert binding.content_hash() != other.content_hash()


# -- order ack / reject ---------------------------------------------------------


def test_order_ack_carries_broker_identity_and_time() -> None:
    ack = BrokerOrderAck(
        client_order_id="client-line-1",
        broker_order_id="B-9001",
        broker_received_at=BROKER_OBSERVED_AT,
        account=_binding(),
    )
    assert ack.broker_order_id == "B-9001"
    assert ack.status is OrderStatus.ACKNOWLEDGED


def test_order_reject_carries_broker_code() -> None:
    reject = BrokerOrderReject(
        client_order_id="client-line-1",
        broker_code="INSUFFICIENT_FUNDS",
        broker_message="not enough buying power",
        broker_observed_at=BROKER_OBSERVED_AT,
        account=_binding(),
    )
    assert reject.status is OrderStatus.REJECTED
    assert reject.broker_code == "INSUFFICIENT_FUNDS"


# -- order updates: partial/cancel/expire/late fill -----------------------------


def _update(**overrides: object) -> BrokerOrderUpdate:
    base: dict[str, object] = {
        "client_order_id": "client-line-1",
        "broker_order_id": "B-9001",
        "status": OrderStatus.PARTIALLY_FILLED,
        "cumulative_quantity_units": 100,
        "cumulative_notional_cents": 100_000,
        "cumulative_fee_cents": 30,
        "leaves_quantity_units": 800,
        "broker_observed_at": BROKER_OBSERVED_AT,
        "account": _binding(),
    }
    base.update(overrides)
    return BrokerOrderUpdate(**base)


def test_partial_fill_uses_cumulative_semantics() -> None:
    update = _update()
    assert update.cumulative_quantity_units == 100
    assert update.leaves_quantity_units == 800
    assert update.status is OrderStatus.PARTIALLY_FILLED


def test_terminal_states_are_distinct() -> None:
    cancelled = _update(
        status=OrderStatus.CANCELLED,
        leaves_quantity_units=0,
    )
    expired = _update(status=OrderStatus.EXPIRED, leaves_quantity_units=0)
    filled = _update(
        status=OrderStatus.FILLED,
        cumulative_quantity_units=900,
        leaves_quantity_units=0,
    )
    assert cancelled.status is OrderStatus.CANCELLED
    assert expired.status is OrderStatus.EXPIRED
    assert filled.status is OrderStatus.FILLED


def test_unknown_status_survives_without_terminal_mapping() -> None:
    unknown = _update(status=OrderStatus.UNKNOWN)
    assert unknown.status is OrderStatus.UNKNOWN
    assert unknown.status not in {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
        OrderStatus.REJECTED,
    }


def test_cumulative_fields_forbid_float_and_negative() -> None:
    with pytest.raises(ValueError):
        _update(cumulative_notional_cents=100_000.5)
    with pytest.raises(ValueError):
        _update(cumulative_quantity_units=-1)
    with pytest.raises(ValueError):
        _update(cumulative_fee_cents=-1)


def test_execution_report_links_execution_identity() -> None:
    update = _update(
        execution_id="E-1",
        last_fill_quantity_units=100,
        last_fill_price_cents=1000,
    )
    assert update.execution_id == "E-1"
    assert update.last_fill_price_cents == 1000


def test_late_fill_after_cancel_keeps_broker_truth() -> None:
    # 撤单后迟到成交是真实 broker 语义: update 必须能同时携带
    # terminal cancel 痕迹与递增的累计成交, 由 Task 4 派生经济 delta.
    late = _update(
        status=OrderStatus.CANCELLED,
        cumulative_quantity_units=150,
        cumulative_notional_cents=150_000,
        leaves_quantity_units=0,
    )
    assert late.cumulative_quantity_units == 150


# -- new order command -----------------------------------------------------------


def test_new_order_command_is_immutable_and_exact() -> None:
    command = _new_order()
    assert command.client_order_id == "client-line-1"
    with pytest.raises(ValueError):
        command.quantity_units = 1  # type: ignore[misc]
    with pytest.raises(ValueError):
        _new_order().model_copy(update={"limit_price_cents": 0}).model_validate(
            _new_order().model_copy(update={"limit_price_cents": 0}).model_dump(),
            strict=True,
        )


def test_new_order_rejects_float_price() -> None:
    with pytest.raises(ValueError):
        NewOrderCommand(
            client_order_id="c1",
            security_id="000001",
            side="BUY",
            quantity_units=900,
            order_type="LIMIT",
            limit_price_cents=1000.5,  # type: ignore[arg-type]
            time_in_force="DAY",
            account=_binding(),
        )


def test_new_order_rejects_nonpositive_quantity() -> None:
    with pytest.raises(ValueError):
        NewOrderCommand(
            client_order_id="c1",
            security_id="000001",
            side="BUY",
            quantity_units=0,
            order_type="LIMIT",
            limit_price_cents=1000,
            time_in_force="DAY",
            account=_binding(),
        )


def test_decimal_amounts_canonicalize_without_exponent() -> None:
    binding = _binding()
    assert binding.content_hash() == BrokerAccountBinding.model_validate(
        binding.model_dump(mode="python"), strict=True
    ).content_hash()
    # Decimal canonical 化不被指数表示污染 (canonical_decimal_string 语义).
    from src.screening.offensive.v3.contracts.base import canonical_decimal_string

    assert canonical_decimal_string(Decimal("0.020")) == "0.02"
