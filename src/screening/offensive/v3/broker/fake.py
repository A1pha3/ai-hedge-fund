"""Plan 07 Task 1: deterministic fake broker for fault-injection tests.

The fake is a complete ``BrokerPort`` driven by an explicit ``FakeScript``
of actions. It never touches a network, a vendor SDK, or credentials, so
dispatcher/normalizer/reconciler tests can replay ack/reject/timeout/
auth-failure/partial-fill deterministically.

Every call consumes the next scripted action; an unscripted call fails
closed (``FakeScriptExhausted``) so tests cannot accidentally drive the
adapter past its declared behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from src.screening.offensive.v3.broker.ports import (
    BrokerAccountBinding,
    BrokerPort,
    BrokerRawEnvelope,
    BrokerTimeoutError,
    CancelOrderCommand,
    NewOrderCommand,
    OrderStatus,
)

FINGERPRINT = "f" * 64


class FakeScriptExhausted(RuntimeError):
    """The fake ran out of scripted actions for the requested call."""


@dataclass(frozen=True)
class FakeAction:
    """One scripted broker response.

    ``kind`` selects which envelope shape the call emits; optional fields
    parameterize it. The fake owns monotonic source sequences and UTC
    timestamps.
    """

    kind: Literal[
        "ack",
        "duplicate_ack",
        "reject",
        "timeout",
        "auth_failure",
        "cancel_ack",
        "cancel_timeout",
        "order_state",
        "fills",
        "unknown_order",
    ]
    broker_order_id: str | None = None
    broker_code: str | None = None
    broker_message: str = ""
    status: str | None = None
    cumulative_quantity_units: int = 0
    cumulative_notional_cents: int = 0
    cumulative_fee_cents: int = 0
    leaves_quantity_units: int = 0
    execution_id: str | None = None
    last_fill_quantity_units: int | None = None
    last_fill_price_cents: int | None = None

    @staticmethod
    def ack(*, broker_order_id: str) -> FakeAction:
        return FakeAction(kind="ack", broker_order_id=broker_order_id)

    @staticmethod
    def duplicate_ack(*, broker_order_id: str) -> FakeAction:
        return FakeAction(
            kind="duplicate_ack", broker_order_id=broker_order_id
        )

    @staticmethod
    def reject(*, broker_code: str, message: str = "") -> FakeAction:
        return FakeAction(
            kind="reject", broker_code=broker_code, broker_message=message
        )

    @staticmethod
    def timeout() -> FakeAction:
        return FakeAction(kind="timeout")

    @staticmethod
    def auth_failure() -> FakeAction:
        return FakeAction(kind="auth_failure")

    @staticmethod
    def cancel_ack() -> FakeAction:
        return FakeAction(kind="cancel_ack")

    @staticmethod
    def cancel_timeout() -> FakeAction:
        return FakeAction(kind="cancel_timeout")

    @staticmethod
    def order_state(
        *,
        status: str,
        cumulative_quantity_units: int = 0,
        cumulative_notional_cents: int = 0,
        cumulative_fee_cents: int = 0,
        leaves_quantity_units: int = 0,
        execution_id: str | None = None,
        last_fill_quantity_units: int | None = None,
        last_fill_price_cents: int | None = None,
    ) -> FakeAction:
        return FakeAction(
            kind="order_state",
            status=status,
            cumulative_quantity_units=cumulative_quantity_units,
            cumulative_notional_cents=cumulative_notional_cents,
            cumulative_fee_cents=cumulative_fee_cents,
            leaves_quantity_units=leaves_quantity_units,
            execution_id=execution_id,
            last_fill_quantity_units=last_fill_quantity_units,
            last_fill_price_cents=last_fill_price_cents,
        )

    @staticmethod
    def fills(*, cumulative_quantity_units: int = 0) -> FakeAction:
        return FakeAction(
            kind="fills",
            cumulative_quantity_units=cumulative_quantity_units,
        )

    @staticmethod
    def unknown_order() -> FakeAction:
        return FakeAction(kind="unknown_order")


@dataclass(frozen=True)
class FakeScript:
    """An ordered list of scripted actions plus the account binding."""

    account: BrokerAccountBinding
    actions: tuple[FakeAction, ...] = ()

    def with_actions(self, *actions: FakeAction) -> FakeScript:
        return FakeScript(account=self.account, actions=self.actions + actions)


@dataclass
class DeterministicFakeBroker(BrokerPort):
    """A ``BrokerPort`` that replays a ``FakeScript`` deterministically."""

    script: FakeScript
    _cursor: int = field(default=0, init=False, repr=False)
    _seqs: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _broker_order_for: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _clock: datetime = field(
        default_factory=lambda: datetime(2026, 8, 7, 1, 0, 0, tzinfo=timezone.utc),
        init=False,
        repr=False,
    )

    @property
    def account(self) -> BrokerAccountBinding:
        return self.script.account

    def _advance_clock(self) -> datetime:
        self._clock = self._clock.replace(microsecond=self._clock.microsecond + 1)
        return self._clock

    def _next_seq(self, source: str) -> int:
        seq = self._seqs.get(source, 0) + 1
        self._seqs[source] = seq
        return seq

    def _envelope(
        self,
        *,
        source: str,
        payload: dict[str, object],
        authenticated: bool = True,
    ) -> BrokerRawEnvelope:
        observed = self._advance_clock()
        return BrokerRawEnvelope(
            authenticated=authenticated,
            auth_fingerprint=FINGERPRINT if authenticated else None,
            source=source,
            source_sequence=self._next_seq(source),
            parser_version="v1",
            broker_observed_at=observed,
            received_at=observed,
            account=self.script.account,
            payload=payload,
        )

    def _pop(self) -> FakeAction:
        if self._cursor >= len(self.script.actions):
            raise FakeScriptExhausted(
                f"no scripted action at index {self._cursor}"
            )
        action = self.script.actions[self._cursor]
        self._cursor += 1
        return action

    def submit(self, command: NewOrderCommand) -> BrokerRawEnvelope:
        action = self._pop()
        if action.kind == "timeout":
            raise BrokerTimeoutError("submit timed out")
        if action.kind == "auth_failure":
            return self._envelope(
                source="broker-submit",
                payload={"kind": "order_update", "auth": "failed"},
                authenticated=False,
            )
        if action.kind == "reject":
            return self._envelope(
                source="broker-submit",
                payload={
                    "kind": "order_reject",
                    "client_order_id": command.client_order_id,
                    "broker_code": action.broker_code,
                    "broker_message": action.broker_message,
                },
            )
        if action.kind in {"ack", "duplicate_ack"}:
            broker_order_id = action.broker_order_id or "B-0001"
            self._broker_order_for[command.client_order_id] = broker_order_id
            payload: dict[str, object] = {
                "kind": "order_ack",
                "client_order_id": command.client_order_id,
                "broker_order_id": broker_order_id,
            }
            if action.kind == "duplicate_ack":
                payload["duplicate"] = True
            return self._envelope(source="broker-submit", payload=payload)
        raise FakeScriptExhausted(
            f"action {action.kind!r} not valid for submit"
        )

    def cancel(self, client_order_id: str) -> BrokerRawEnvelope:
        action = self._pop()
        if action.kind == "cancel_timeout":
            raise BrokerTimeoutError("cancel timed out")
        if action.kind == "cancel_ack":
            return self._envelope(
                source="broker-cancel",
                payload={
                    "kind": "cancel_ack",
                    "client_order_id": client_order_id,
                    "broker_order_id": self._broker_order_for.get(
                        client_order_id, "B-0001"
                    ),
                },
            )
        raise FakeScriptExhausted(
            f"action {action.kind!r} not valid for cancel"
        )

    def query_order(self, client_order_id: str) -> BrokerRawEnvelope:
        action = self._pop()
        if action.kind == "unknown_order":
            return self._envelope(
                source="broker-query",
                payload={
                    "kind": "order_state",
                    "client_order_id": client_order_id,
                    "broker_order_id": self._broker_order_for.get(
                        client_order_id, ""
                    ),
                    "status": OrderStatus.UNKNOWN.value,
                    "cumulative_quantity_units": 0,
                    "cumulative_notional_cents": 0,
                    "cumulative_fee_cents": 0,
                    "leaves_quantity_units": 0,
                },
            )
        if action.kind == "order_state":
            return self._envelope(
                source="broker-query",
                payload={
                    "kind": "order_state",
                    "client_order_id": client_order_id,
                    "broker_order_id": self._broker_order_for.get(
                        client_order_id, "B-0001"
                    ),
                    "status": action.status,
                    "cumulative_quantity_units": (
                        action.cumulative_quantity_units
                    ),
                    "cumulative_notional_cents": (
                        action.cumulative_notional_cents
                    ),
                    "cumulative_fee_cents": action.cumulative_fee_cents,
                    "leaves_quantity_units": action.leaves_quantity_units,
                    "execution_id": action.execution_id,
                    "last_fill_quantity_units": (
                        action.last_fill_quantity_units
                    ),
                    "last_fill_price_cents": action.last_fill_price_cents,
                },
            )
        raise FakeScriptExhausted(
            f"action {action.kind!r} not valid for query_order"
        )

    def query_fills(self, *, account: BrokerAccountBinding) -> BrokerRawEnvelope:
        action = self._pop()
        if action.kind == "fills":
            return self._envelope(
                source="broker-fills",
                payload={
                    "kind": "fills",
                    "cumulative_quantity_units": (
                        action.cumulative_quantity_units
                    ),
                },
            )
        raise FakeScriptExhausted(
            f"action {action.kind!r} not valid for query_fills"
        )
