"""Plan 07 Task 1: broker-neutral protocol boundary and envelopes.

The Gateway (Plan 04) remains the sole authority over entry/capital. A
broker adapter never modifies authorization, seals, reserves, or capital;
it only sends immutable commands that already hold ``SEND_CLAIMED`` and
returns authenticated raw responses. This module defines the port, the
authenticated raw envelope, the stable order/execution/fee revision
contracts, and the broker-account binding.

Design rules enforced here:
- Authentication is explicit and never defaulted. An unauthenticated
  envelope is a legal raw input but it must declare ``authenticated=False``
  and cannot also carry an ``auth_fingerprint``.
- All timestamps are UTC instants; all money is exact integer cents and
  quantities are exact integer units. Floats are forbidden.
- The account binding pins account id, environment, currency, and endpoint
  fingerprint so that broker-side drift is rejected at the protocol edge.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Annotated, ClassVar, Literal

from pydantic import Field, StringConstraints, model_validator

from src.screening.offensive.v3.contracts.base import (
    CanonicalModel,
    ExactInteger,
    MoneyCents,
    QuantityUnits,
    Sha256,
    UtcInstant,
)

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]
PositiveInt = Annotated[ExactInteger, Field(ge=1)]
PositiveCents = Annotated[MoneyCents, Field(gt=0)]
NonNegativeCents = Annotated[MoneyCents, Field(ge=0)]
PositiveQuantity = Annotated[QuantityUnits, Field(gt=0)]
NonNegativeQuantity = Annotated[QuantityUnits, Field(ge=0)]


class OrderStatus(StrEnum):
    """Broker-observed order status; ``UNKNOWN`` is never terminal."""

    UNKNOWN = "unknown"
    ACKNOWLEDGED = "acknowledged"
    WORKING = "working"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.REJECTED,
        }


class BrokerAccountBinding(CanonicalModel):
    """Exact account/environment/currency/endpoint binding.

    The broker adapter may only act for one binding; drift at the protocol
    edge (a response stamped with a different account) is rejected by
    normalizers rather than silently accepted.
    """

    account_id: NonEmptyStr
    environment: NonEmptyStr
    currency: NonEmptyStr
    endpoint_fingerprint: Sha256


class BrokerRawEnvelope(CanonicalModel):
    """One authenticated raw broker payload, durably append-only.

    ``payload`` is an opaque JSON-serializable mapping that the normalizer
    (Task 4) interprets under ``parser_version``. The envelope itself only
    carries the authentication/audit truth; it never mutates capital.
    """

    authenticated: bool
    auth_fingerprint: Sha256 | None
    source: NonEmptyStr
    source_sequence: PositiveInt
    parser_version: NonEmptyStr
    broker_observed_at: UtcInstant
    received_at: UtcInstant
    account: BrokerAccountBinding
    payload: dict[str, object]

    @model_validator(mode="after")
    def validate_authentication_binding(self) -> BrokerRawEnvelope:
        if self.authenticated:
            if self.auth_fingerprint is None:
                raise ValueError(
                    "authenticated envelope must carry an auth_fingerprint"
                )
        else:
            if self.auth_fingerprint is not None:
                raise ValueError(
                    "unauthenticated envelope must not carry an auth_fingerprint"
                )
        return self


class NewOrderCommand(CanonicalModel):
    """An immutable entry order payload released by a Gateway send claim."""

    client_order_id: NonEmptyStr
    security_id: NonEmptyStr
    side: Literal["BUY", "SELL"]
    quantity_units: PositiveQuantity
    order_type: NonEmptyStr
    limit_price_cents: PositiveCents
    time_in_force: NonEmptyStr
    account: BrokerAccountBinding


class CancelOrderCommand(CanonicalModel):
    """An immutable cancel for an existing client order id."""

    client_order_id: NonEmptyStr
    account: BrokerAccountBinding


class BrokerOrderAck(CanonicalModel):
    """Broker acceptance of a new order: client id -> broker id mapping."""

    kind: ClassVar[str] = "order_ack"
    client_order_id: NonEmptyStr
    broker_order_id: NonEmptyStr
    broker_received_at: UtcInstant
    account: BrokerAccountBinding
    status: OrderStatus = OrderStatus.ACKNOWLEDGED


class BrokerOrderReject(CanonicalModel):
    """Broker rejection of a new order with a stable broker code."""

    kind: ClassVar[str] = "order_reject"
    client_order_id: NonEmptyStr
    broker_code: NonEmptyStr
    broker_message: str
    broker_observed_at: UtcInstant
    account: BrokerAccountBinding
    status: OrderStatus = OrderStatus.REJECTED


class BrokerOrderUpdate(CanonicalModel):
    """Broker order state update.

    ``cumulative_*`` fields are broker-truth totals as of the observation
    time; the normalizer derives deltas. A late fill may arrive even after
    a terminal cancel, so cumulative truth is independent of terminal
    status here.
    """

    kind: ClassVar[str] = "order_update"
    client_order_id: NonEmptyStr
    broker_order_id: NonEmptyStr
    status: OrderStatus
    cumulative_quantity_units: NonNegativeQuantity
    cumulative_notional_cents: NonNegativeCents
    cumulative_fee_cents: NonNegativeCents
    leaves_quantity_units: NonNegativeQuantity
    broker_observed_at: UtcInstant
    account: BrokerAccountBinding
    execution_id: NonEmptyStr | None = None
    last_fill_quantity_units: PositiveQuantity | None = None
    last_fill_price_cents: PositiveCents | None = None


class BrokerTimeoutError(RuntimeError):
    """The broker did not return an authenticated response in time."""


class BrokerPort(ABC):
    """Broker-neutral submission/cancel/query port.

    Every method returns a ``BrokerRawEnvelope`` wrapping the authenticated
    raw response, so the dispatcher can durably persist before any
    normalization. The port never claims broker acceptance without an
    authenticated receipt.
    """

    @abstractmethod
    def submit(self, command: NewOrderCommand) -> BrokerRawEnvelope:
        """Submit a new order; return the authenticated raw envelope."""

    @abstractmethod
    def cancel(self, client_order_id: str) -> BrokerRawEnvelope:
        """Cancel an outstanding order by its client order id."""

    @abstractmethod
    def query_order(self, client_order_id: str) -> BrokerRawEnvelope:
        """Query the current order state; UNKNOWN if the broker has no record."""

    @abstractmethod
    def query_fills(self, *, account: BrokerAccountBinding) -> BrokerRawEnvelope:
        """Query the fill history for one account (paginated upstream)."""

    @property
    @abstractmethod
    def account(self) -> BrokerAccountBinding:
        """The single binding this adapter may act for."""


def now_utc() -> datetime:
    """Return a timezone-aware UTC instant (helper for fakes/tests)."""

    from datetime import timezone

    return datetime.now(tz=timezone.utc)
