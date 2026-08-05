"""Genesis, subscription/redemption flows, and account lifecycle DTOs.

Plan 02 Task 3. External financing flows are a distinct fact class from the
economic event stream: they move cash and fund units, never securities, and
feed the conservation identity's opening-capital and external-flow terms.

Lifecycle state machine (one-way; terminal states are irreversible)::

    ACTIVE --full redemption settle--> TERMINATING --all obligations zero--> TERMINATED
    ACTIVE --confirmed NAV <= 0------> INSOLVENT

``TERMINATING`` is settle-only: exits, liquidation valuations, and
redemption payments continue, but no new entry risk, subscription, or risk
epoch may start. ``INSOLVENT`` is not auto-recoverable: only exits,
liquidation, and reconciliation continue; units/HWM/history are never reset
to erase the failure. ``TERMINATED`` (an authorized full redemption) is not
insolvency.

Subscription flow (flow-before-price)::

    request_subscription (cash received -> suspense + subscription payable)
      -> [price_subscription freezes V_pre / unit price]
      -> settle_subscription (issue units at the pre-flow price, release
         suspense, clear the payable) -- or cancel_subscription (refund)
         before units exist.

Redemption flow::

    request_redemption (off-ledger memo reserve; no NAV/HWM/drawdown impact)
      -> [price_redemption freezes unit price / payout]
      -> settle_redemption (partial: cancel units + redemption payable +
         reserved cash; full: every live unit becomes ``pending_redeemed``
         and the account enters TERMINATING) -- or cancel_redemption while
         it is still a memo.
      -> pay_redemption (pay the payable; burn pending units only once the
         payable and every other obligation are zero).

All unit prices are exact rationals (integer numerator/denominator cents
per unit quanta); ``fractions.Fraction`` may be used internally for exact
arithmetic but only integers are persisted.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from src.screening.offensive.v3.capital.identity import AccountBinding
from src.screening.offensive.v3.contracts import CanonicalModel, UtcInstant
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr


PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveCents = Annotated[int, Field(gt=0)]


class LifecycleState(StrEnum):
    ACTIVE = "ACTIVE"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"
    INSOLVENT = "INSOLVENT"


#: States in which no new entry risk, subscription, genesis, or risk epoch
#: may start. Exits, liquidation valuations, and redemption payments
#: continue in TERMINATING/INSOLVENT by design.
NEW_RISK_BLOCKED_STATES = frozenset(
    {
        LifecycleState.TERMINATING,
        LifecycleState.TERMINATED,
        LifecycleState.INSOLVENT,
    }
)


class FlowKind(StrEnum):
    GENESIS = "GENESIS"
    SUBSCRIPTION_RECEIVED = "SUBSCRIPTION_RECEIVED"
    SUBSCRIPTION_SETTLED = "SUBSCRIPTION_SETTLED"
    SUBSCRIPTION_CANCELLED = "SUBSCRIPTION_CANCELLED"
    REDEMPTION_SETTLED = "REDEMPTION_SETTLED"
    REDEMPTION_PAID = "REDEMPTION_PAID"


class FlowRequestKind(StrEnum):
    SUBSCRIPTION = "SUBSCRIPTION"
    REDEMPTION = "REDEMPTION"


class PayableState(StrEnum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


SUBSCRIPTION_PAYABLE = "SUBSCRIPTION_PAYABLE"
REDEMPTION_PAYABLE = "REDEMPTION_PAYABLE"


class FlowRequestState(StrEnum):
    RECEIVED = "RECEIVED"
    REQUESTED = "REQUESTED"
    PRICED = "PRICED"
    SETTLED = "SETTLED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class GenesisRequest(CanonicalModel):
    """The one-time genesis issuance of explicit units.

    Governance freezes base currency, integer unit quanta, and the genesis
    unit price before genesis; the price must divide to exact integer cents
    (no rounding at genesis). The account binding travels with the genesis
    request because genesis is the operation that binds the ledger.
    """

    idempotency_key: NonEmptyStr
    account_binding: AccountBinding
    unit_quanta: PositiveInt
    unit_price_numerator: PositiveInt
    unit_price_denominator: PositiveInt
    source_authority: NonEmptyStr
    authorization_reference: NonEmptyStr | None = None
    effective_at: UtcInstant
    as_of: UtcInstant

    @model_validator(mode="after")
    def validate_times(self) -> "GenesisRequest":
        if self.as_of < self.effective_at:
            raise ValueError("as_of cannot precede effective_at")
        return self


class GenesisReceipt(CanonicalModel):
    flow_event_id: NonEmptyStr
    observation_id: NonEmptyStr
    cash_amount_cents: PositiveCents
    unit_quanta: PositiveInt
    unit_price_numerator: PositiveInt
    unit_price_denominator: PositiveInt
    capital_version: NonNegativeInt
    flow_version: NonNegativeInt


class SubscriptionRequest(CanonicalModel):
    """Receive subscription cash into suspense with an equal payable."""

    request_id: NonEmptyStr
    cash_amount_cents: PositiveCents
    source_authority: NonEmptyStr
    effective_at: UtcInstant
    as_of: UtcInstant
    expected_flow_version: NonNegativeInt

    @model_validator(mode="after")
    def validate_times(self) -> "SubscriptionRequest":
        if self.as_of < self.effective_at:
            raise ValueError("as_of cannot precede effective_at")
        return self


class SubscriptionReceipt(CanonicalModel):
    request_id: NonEmptyStr
    flow_event_id: NonEmptyStr
    cash_amount_cents: PositiveCents
    payable_id: NonEmptyStr
    capital_version: NonNegativeInt
    flow_version: NonNegativeInt


class RedemptionRequest(CanonicalModel):
    """Record an off-ledger memo redemption reserve (no capital impact)."""

    request_id: NonEmptyStr
    unit_quanta: PositiveInt
    source_authority: NonEmptyStr
    as_of: UtcInstant


class RedemptionRequestReceipt(CanonicalModel):
    request_id: NonEmptyStr
    unit_quanta: PositiveInt


class FlowPriceRequest(CanonicalModel):
    """Freeze V_pre and the issue/redemption price for one flow request."""

    request_id: NonEmptyStr
    source_authority: NonEmptyStr
    as_of: UtcInstant


class FlowPriceReceipt(CanonicalModel):
    request_id: NonEmptyStr
    v_pre_cents: NonNegativeInt
    units_pre_quanta: NonNegativeInt
    unit_price_numerator: NonNegativeInt
    unit_price_denominator: PositiveInt
    cash_amount_cents: PositiveCents
    frozen_capital_version: NonNegativeInt


class FlowSettleRequest(CanonicalModel):
    """Settle one priced (or priceable) flow request."""

    request_id: NonEmptyStr
    source_authority: NonEmptyStr
    as_of: UtcInstant
    expected_flow_version: NonNegativeInt


class FlowSettleReceipt(CanonicalModel):
    request_id: NonEmptyStr
    flow_event_id: NonEmptyStr
    issued_unit_quanta: NonNegativeInt = 0
    cancelled_unit_quanta: NonNegativeInt = 0
    pending_unit_quanta: NonNegativeInt = 0
    refund_cents: NonNegativeInt = 0
    unit_price_numerator: NonNegativeInt
    unit_price_denominator: PositiveInt
    payable_id: NonEmptyStr | None = None
    lifecycle_state: LifecycleState
    capital_version: NonNegativeInt
    flow_version: NonNegativeInt


class FlowCancelRequest(CanonicalModel):
    """Cancel one unsettled flow request (subscription refund / memo)."""

    request_id: NonEmptyStr
    source_authority: NonEmptyStr
    as_of: UtcInstant
    expected_flow_version: NonNegativeInt = 0


class RedemptionPaymentRequest(CanonicalModel):
    """Pay (part of) a settled redemption payable and burn units when the
    payable and every other obligation reach zero."""

    request_id: NonEmptyStr
    source_authority: NonEmptyStr
    as_of: UtcInstant
    expected_flow_version: NonNegativeInt


class RedemptionPaymentReceipt(CanonicalModel):
    request_id: NonEmptyStr
    flow_event_id: NonEmptyStr
    cash_amount_cents: PositiveCents
    suspense_in_cents: NonNegativeInt = 0
    burnt_unit_quanta: NonNegativeInt = 0
    remaining_payable_cents: NonNegativeInt
    lifecycle_state: LifecycleState
    capital_version: NonNegativeInt
    flow_version: NonNegativeInt


class RiskEpochRequest(CanonicalModel):
    """Start a new monotonic risk epoch from an audited capital snapshot.

    ``RiskEpochStarted`` never resets the lifetime high-water mark or any
    history; it only establishes the active-epoch operational baseline (the
    audited NAV) used for the new epoch's drawdown authority.
    """

    idempotency_key: NonEmptyStr
    risk_epoch: PositiveInt
    audited_nav_cents: NonNegativeInt
    source_authority: NonEmptyStr
    authorization_reference: NonEmptyStr | None = None
    effective_at: UtcInstant
    as_of: UtcInstant

    @model_validator(mode="after")
    def validate_times(self) -> "RiskEpochRequest":
        if self.as_of < self.effective_at:
            raise ValueError("as_of cannot precede effective_at")
        return self


class RiskEpochReceipt(CanonicalModel):
    risk_epoch: PositiveInt
    predecessor_risk_epoch: NonNegativeInt
    audited_nav_cents: NonNegativeInt
    active_epoch_baseline_nav_cents: NonNegativeInt
    lifetime_high_water_mark_cents: NonNegativeInt
    capital_version: NonNegativeInt


class RiskEpochRecord(CanonicalModel):
    """One durable row of the append-only risk-epoch chain (read model)."""

    risk_epoch: PositiveInt
    predecessor_risk_epoch: NonNegativeInt
    audited_nav_cents: NonNegativeInt
    active_epoch_baseline_nav_cents: NonNegativeInt
    lifetime_high_water_mark_cents: NonNegativeInt
    source_authority: NonEmptyStr
    authorization_reference: NonEmptyStr | None
    started_at: UtcInstant


def genesis_cash_cents(
    unit_quanta: int, price_numerator: int, price_denominator: int
) -> int | None:
    """Exact genesis cash in cents, or ``None`` when the frozen price does
    not divide to an exact integer amount (genesis never rounds)."""

    total = unit_quanta * price_numerator
    if total % price_denominator != 0:
        return None
    return total // price_denominator


__all__ = [
    "NEW_RISK_BLOCKED_STATES",
    "REDEMPTION_PAYABLE",
    "SUBSCRIPTION_PAYABLE",
    "FlowCancelRequest",
    "FlowKind",
    "FlowPriceReceipt",
    "FlowPriceRequest",
    "FlowRequestKind",
    "FlowRequestState",
    "FlowSettleReceipt",
    "FlowSettleRequest",
    "GenesisReceipt",
    "GenesisRequest",
    "LifecycleState",
    "PayableState",
    "RedemptionPaymentReceipt",
    "RedemptionPaymentRequest",
    "RedemptionRequest",
    "RedemptionRequestReceipt",
    "RiskEpochReceipt",
    "RiskEpochRecord",
    "RiskEpochRequest",
    "SubscriptionReceipt",
    "SubscriptionRequest",
    "genesis_cash_cents",
]
