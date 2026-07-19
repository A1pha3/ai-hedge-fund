"""Storage-free capital truth state, snapshot, and economic-event contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import Field, model_validator

from .base import CanonicalModel, ExecutionMode, Sha256, UtcInstant
from .evidence import NonEmptyStr


PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]


class PositionState(StrEnum):
    OPEN = "OPEN"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    LEGAL_TERMINAL = "LEGAL_TERMINAL"


class AuthorityState(StrEnum):
    ACTIVE = "ACTIVE"
    DRAINING = "DRAINING"
    BROKER_RECONCILED = "BROKER_RECONCILED"
    HANDOFF_COMPLETE = "HANDOFF_COMPLETE"


class PlanState(StrEnum):
    SEALED = "SEALED"
    PERMITTED = "PERMITTED"
    ORDER_DURABLE = "ORDER_DURABLE"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    CANCEL_PENDING = "CANCEL_PENDING"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    EXECUTED = "EXECUTED"


class OrderState(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


class SessionPhase(StrEnum):
    CORPORATE_ACTIONS_APPLIED = "CORPORATE_ACTIONS_APPLIED"
    PREOPEN_RISK_LOCKED = "PREOPEN_RISK_LOCKED"
    ORDER_INTENTS_DURABLE = "ORDER_INTENTS_DURABLE"
    OPEN_RECONCILED = "OPEN_RECONCILED"
    CLOSE_VALUED = "CLOSE_VALUED"
    SESSION_FINALIZED = "SESSION_FINALIZED"


POSITION_STATE_TRANSITIONS = MappingProxyType(
    {
        PositionState.OPEN: frozenset({PositionState.EXIT_PENDING}),
        PositionState.EXIT_PENDING: frozenset(
            {PositionState.CLOSED, PositionState.LEGAL_TERMINAL}
        ),
        PositionState.CLOSED: frozenset(),
        PositionState.LEGAL_TERMINAL: frozenset(),
    }
)

AUTHORITY_STATE_TRANSITIONS = MappingProxyType(
    {
        AuthorityState.ACTIVE: frozenset({AuthorityState.DRAINING}),
        AuthorityState.DRAINING: frozenset({AuthorityState.BROKER_RECONCILED}),
        AuthorityState.BROKER_RECONCILED: frozenset(
            {AuthorityState.HANDOFF_COMPLETE}
        ),
        AuthorityState.HANDOFF_COMPLETE: frozenset(),
    }
)

PLAN_STATE_TRANSITIONS = MappingProxyType(
    {
        PlanState.SEALED: frozenset(
            {
                PlanState.PERMITTED,
                PlanState.SUPERSEDED,
                PlanState.CANCELLED,
                PlanState.EXPIRED,
            }
        ),
        PlanState.PERMITTED: frozenset(
            {PlanState.ORDER_DURABLE, PlanState.CANCELLED, PlanState.EXPIRED}
        ),
        PlanState.ORDER_DURABLE: frozenset(
            {
                PlanState.PARTIALLY_EXECUTED,
                PlanState.EXECUTED,
                PlanState.CANCEL_PENDING,
            }
        ),
        PlanState.PARTIALLY_EXECUTED: frozenset(
            {PlanState.EXECUTED, PlanState.CANCEL_PENDING}
        ),
        PlanState.CANCEL_PENDING: frozenset(
            {
                PlanState.CANCEL_PENDING,
                PlanState.EXECUTED,
                PlanState.CANCELLED,
            }
        ),
        PlanState.SUPERSEDED: frozenset(),
        PlanState.CANCELLED: frozenset(),
        PlanState.EXPIRED: frozenset(),
        PlanState.EXECUTED: frozenset(),
    }
)

ORDER_STATE_TRANSITIONS = MappingProxyType(
    {
        OrderState.CREATED: frozenset(
            {OrderState.SUBMITTED, OrderState.REJECTED}
        ),
        OrderState.SUBMITTED: frozenset(
            {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.REJECTED,
                OrderState.CANCEL_REQUESTED,
            }
        ),
        OrderState.PARTIALLY_FILLED: frozenset(
            {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.CANCEL_REQUESTED,
            }
        ),
        OrderState.CANCEL_REQUESTED: frozenset(
            {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.CANCELLED,
            }
        ),
        OrderState.FILLED: frozenset(),
        OrderState.REJECTED: frozenset(),
        OrderState.CANCELLED: frozenset(),
    }
)


class SessionCheckpoint(CanonicalModel):
    session: date
    phase: SessionPhase
    stream_version: PositiveInt
    recorded_at: UtcInstant


class PositionSnapshot(CanonicalModel):
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    security_id: NonEmptyStr
    state: PositionState
    settled_quantity: NonNegativeInt
    tradable_quantity: NonNegativeInt
    share_receivable_quantity: NonNegativeInt
    cost_basis: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_quantities(self) -> Self:
        if self.tradable_quantity > self.settled_quantity:
            raise ValueError("tradable quantity cannot exceed settled quantity")
        return self


class CapitalSnapshot(CanonicalModel):
    capital_snapshot_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    capital_version: PositiveInt
    stream_version: PositiveInt
    mode: ExecutionMode
    as_of: UtcInstant
    cash: Decimal
    nav: NonNegativeDecimal
    gross_exposure: NonNegativeDecimal
    high_water_mark: NonNegativeDecimal
    positions: tuple[PositionSnapshot, ...]
    payload_content_hash: Sha256


class AuthoritySnapshot(CanonicalModel):
    portfolio_id: NonEmptyStr
    authority_epoch: PositiveInt
    state: AuthorityState
    capital_version: PositiveInt
    fencing_epoch: PositiveInt
    as_of: UtcInstant


class PlanSnapshot(CanonicalModel):
    seal_id: NonEmptyStr
    order_line_id: NonEmptyStr
    seal_revision: PositiveInt
    portfolio_id: NonEmptyStr
    state: PlanState
    sealed_quantity: PositiveInt
    executed_quantity: NonNegativeInt
    as_of: UtcInstant

    @model_validator(mode="after")
    def validate_quantity(self) -> Self:
        if self.executed_quantity > self.sealed_quantity:
            raise ValueError("executed quantity cannot exceed sealed quantity")
        return self


class OrderSnapshot(CanonicalModel):
    order_id: NonEmptyStr
    seal_id: NonEmptyStr
    order_line_id: NonEmptyStr
    order_revision: PositiveInt
    state: OrderState
    ordered_quantity: PositiveInt
    filled_quantity: NonNegativeInt
    leaves_quantity: NonNegativeInt
    as_of: UtcInstant

    @model_validator(mode="after")
    def validate_quantities(self) -> Self:
        if self.filled_quantity + self.leaves_quantity > self.ordered_quantity:
            raise ValueError("filled plus leaves quantity cannot exceed ordered quantity")
        return self


class DividendReceivable(CanonicalModel):
    receivable_id: NonEmptyStr
    position_lineage_id: NonEmptyStr
    security_id: NonEmptyStr
    ex_date: date
    payment_date: date | None
    amount: NonNegativeDecimal
    settled: bool


class ShareReceivable(CanonicalModel):
    receivable_id: NonEmptyStr
    position_lineage_id: NonEmptyStr
    security_id: NonEmptyStr
    effective_date: date
    tradable_date: date | None
    quantity: PositiveInt
    tradable_quantity: NonNegativeInt

    @model_validator(mode="after")
    def validate_quantity(self) -> Self:
        if self.tradable_quantity > self.quantity:
            raise ValueError("tradable receivable quantity cannot exceed total quantity")
        return self


class EconomicEventKind(StrEnum):
    TRADE_EXECUTED = "TRADE_EXECUTED"
    FEE_CHARGED = "FEE_CHARGED"
    DIVIDEND_RECEIVABLE = "DIVIDEND_RECEIVABLE"
    DIVIDEND_CASH_SETTLED = "DIVIDEND_CASH_SETTLED"
    SHARE_RECEIVABLE = "SHARE_RECEIVABLE"
    SPLIT = "SPLIT"
    MERGE = "MERGE"
    CORPORATE_CASH_SETTLED = "CORPORATE_CASH_SETTLED"
    SECURITY_CONVERTED = "SECURITY_CONVERTED"
    LEGAL_WRITE_OFF = "LEGAL_WRITE_OFF"
    VALUATION = "VALUATION"
    LATE_CORRECTION = "LATE_CORRECTION"


class EconomicAssetKind(StrEnum):
    CASH = "CASH"
    SECURITY = "SECURITY"
    CASH_RECEIVABLE = "CASH_RECEIVABLE"
    SHARE_RECEIVABLE = "SHARE_RECEIVABLE"
    COST_BASIS = "COST_BASIS"
    VALUATION_MARK = "VALUATION_MARK"


class EconomicLegDirection(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


_EVENT_ALLOWED_ASSETS = MappingProxyType(
    {
        EconomicEventKind.TRADE_EXECUTED: frozenset(
            {EconomicAssetKind.CASH, EconomicAssetKind.SECURITY}
        ),
        EconomicEventKind.FEE_CHARGED: frozenset({EconomicAssetKind.CASH}),
        EconomicEventKind.DIVIDEND_RECEIVABLE: frozenset(
            {EconomicAssetKind.CASH_RECEIVABLE}
        ),
        EconomicEventKind.DIVIDEND_CASH_SETTLED: frozenset(
            {EconomicAssetKind.CASH, EconomicAssetKind.CASH_RECEIVABLE}
        ),
        EconomicEventKind.SHARE_RECEIVABLE: frozenset(
            {EconomicAssetKind.SHARE_RECEIVABLE}
        ),
        EconomicEventKind.SPLIT: frozenset(
            {EconomicAssetKind.SECURITY, EconomicAssetKind.COST_BASIS}
        ),
        EconomicEventKind.MERGE: frozenset(
            {EconomicAssetKind.SECURITY, EconomicAssetKind.COST_BASIS}
        ),
        EconomicEventKind.CORPORATE_CASH_SETTLED: frozenset(
            {
                EconomicAssetKind.CASH,
                EconomicAssetKind.SECURITY,
                EconomicAssetKind.CASH_RECEIVABLE,
                EconomicAssetKind.SHARE_RECEIVABLE,
                EconomicAssetKind.COST_BASIS,
            }
        ),
        EconomicEventKind.SECURITY_CONVERTED: frozenset(
            {
                EconomicAssetKind.SECURITY,
                EconomicAssetKind.SHARE_RECEIVABLE,
                EconomicAssetKind.COST_BASIS,
            }
        ),
        EconomicEventKind.LEGAL_WRITE_OFF: frozenset(
            {
                EconomicAssetKind.SECURITY,
                EconomicAssetKind.CASH_RECEIVABLE,
                EconomicAssetKind.SHARE_RECEIVABLE,
                EconomicAssetKind.COST_BASIS,
            }
        ),
    }
)

_EVENT_REQUIRED_ASSETS = MappingProxyType(
    {
        EconomicEventKind.TRADE_EXECUTED: frozenset(
            {EconomicAssetKind.CASH, EconomicAssetKind.SECURITY}
        ),
        EconomicEventKind.FEE_CHARGED: frozenset({EconomicAssetKind.CASH}),
        EconomicEventKind.DIVIDEND_RECEIVABLE: frozenset(
            {EconomicAssetKind.CASH_RECEIVABLE}
        ),
        EconomicEventKind.DIVIDEND_CASH_SETTLED: frozenset(
            {EconomicAssetKind.CASH, EconomicAssetKind.CASH_RECEIVABLE}
        ),
        EconomicEventKind.SHARE_RECEIVABLE: frozenset(
            {EconomicAssetKind.SHARE_RECEIVABLE}
        ),
        EconomicEventKind.SPLIT: frozenset({EconomicAssetKind.SECURITY}),
        EconomicEventKind.MERGE: frozenset({EconomicAssetKind.SECURITY}),
        EconomicEventKind.CORPORATE_CASH_SETTLED: frozenset(
            {EconomicAssetKind.CASH}
        ),
        EconomicEventKind.SECURITY_CONVERTED: frozenset(
            {EconomicAssetKind.SECURITY}
        ),
        EconomicEventKind.LEGAL_WRITE_OFF: frozenset(),
    }
)


class _EconomicEventLeg(CanonicalModel):
    leg_id: NonEmptyStr
    direction: EconomicLegDirection


class CashEconomicEventLeg(_EconomicEventLeg):
    asset_kind: Literal[EconomicAssetKind.CASH]
    cash_amount: Annotated[Decimal, Field(gt=0)]


class SecurityEconomicEventLeg(_EconomicEventLeg):
    asset_kind: Literal[EconomicAssetKind.SECURITY]
    security_id: NonEmptyStr
    quantity: PositiveInt


class CashReceivableEconomicEventLeg(_EconomicEventLeg):
    asset_kind: Literal[EconomicAssetKind.CASH_RECEIVABLE]
    receivable_id: NonEmptyStr
    security_id: NonEmptyStr
    cash_amount: Annotated[Decimal, Field(gt=0)]


class ShareReceivableEconomicEventLeg(_EconomicEventLeg):
    asset_kind: Literal[EconomicAssetKind.SHARE_RECEIVABLE]
    receivable_id: NonEmptyStr
    security_id: NonEmptyStr
    quantity: PositiveInt


class CostBasisEconomicEventLeg(_EconomicEventLeg):
    asset_kind: Literal[EconomicAssetKind.COST_BASIS]
    security_id: NonEmptyStr
    cost_basis_amount: Annotated[Decimal, Field(gt=0)]


class ValuationMarkEconomicEventLeg(CanonicalModel):
    """A mark-only leg which cannot change cash, shares, or receivables."""

    leg_id: NonEmptyStr
    asset_kind: Literal[EconomicAssetKind.VALUATION_MARK]
    security_id: NonEmptyStr
    mark_price: Annotated[Decimal, Field(gt=0)]


EconomicEventLeg: TypeAlias = Annotated[
    CashEconomicEventLeg
    | SecurityEconomicEventLeg
    | CashReceivableEconomicEventLeg
    | ShareReceivableEconomicEventLeg
    | CostBasisEconomicEventLeg
    | ValuationMarkEconomicEventLeg,
    Field(discriminator="asset_kind"),
]


class EconomicEvent(CanonicalModel):
    economic_event_id: NonEmptyStr
    event_kind: EconomicEventKind
    portfolio_id: NonEmptyStr
    position_lineage_id: NonEmptyStr | None
    economic_lot_id: NonEmptyStr | None
    mode: ExecutionMode
    source_authority: NonEmptyStr
    effective_at: UtcInstant
    recorded_at: UtcInstant
    stream_version: PositiveInt
    correction_of_event_id: NonEmptyStr | None
    legs: Annotated[tuple[EconomicEventLeg, ...], Field(min_length=1)]
    payload_content_hash: Sha256

    @model_validator(mode="after")
    def validate_legs(self) -> Self:
        leg_ids = [leg.leg_id for leg in self.legs]
        if len(leg_ids) != len(set(leg_ids)):
            raise ValueError("economic event leg IDs must be unique")
        valuation_legs = [
            leg
            for leg in self.legs
            if isinstance(leg, ValuationMarkEconomicEventLeg)
        ]
        if self.event_kind is EconomicEventKind.VALUATION:
            if len(valuation_legs) != len(self.legs):
                raise ValueError("valuation events may contain only valuation-mark legs")
        elif valuation_legs:
            raise ValueError("valuation-mark legs require event_kind=VALUATION")
        elif self.event_kind is not EconomicEventKind.LATE_CORRECTION:
            actual_assets = {leg.asset_kind for leg in self.legs}
            allowed_assets = _EVENT_ALLOWED_ASSETS[self.event_kind]
            required_assets = _EVENT_REQUIRED_ASSETS[self.event_kind]
            if not actual_assets <= allowed_assets:
                raise ValueError(
                    f"{self.event_kind.value} contains incompatible economic leg"
                )
            if not required_assets <= actual_assets:
                raise ValueError(
                    f"{self.event_kind.value} is missing a required economic leg"
                )
            directions_by_asset = {
                asset_kind: {
                    leg.direction
                    for leg in self.legs
                    if leg.asset_kind is asset_kind
                }
                for asset_kind in actual_assets
            }
            debit = EconomicLegDirection.DEBIT
            credit = EconomicLegDirection.CREDIT
            if self.event_kind is EconomicEventKind.TRADE_EXECUTED:
                cash_directions = directions_by_asset[EconomicAssetKind.CASH]
                security_directions = directions_by_asset[EconomicAssetKind.SECURITY]
                valid_trade = (
                    cash_directions == {debit}
                    and security_directions == {credit}
                ) or (
                    cash_directions == {credit}
                    and security_directions == {debit}
                )
                if not valid_trade:
                    raise ValueError("TRADE_EXECUTED violates debit/credit conservation")
            elif self.event_kind is EconomicEventKind.FEE_CHARGED:
                if directions_by_asset[EconomicAssetKind.CASH] != {debit}:
                    raise ValueError("FEE_CHARGED requires a cash debit direction")
            elif self.event_kind is EconomicEventKind.DIVIDEND_RECEIVABLE:
                if directions_by_asset[EconomicAssetKind.CASH_RECEIVABLE] != {credit}:
                    raise ValueError("DIVIDEND_RECEIVABLE requires a receivable credit")
            elif self.event_kind is EconomicEventKind.DIVIDEND_CASH_SETTLED:
                if not (
                    directions_by_asset[EconomicAssetKind.CASH] == {credit}
                    and directions_by_asset[EconomicAssetKind.CASH_RECEIVABLE]
                    == {debit}
                ):
                    raise ValueError(
                        "DIVIDEND_CASH_SETTLED requires receivable debit and cash credit"
                    )
            elif self.event_kind is EconomicEventKind.SHARE_RECEIVABLE:
                if directions_by_asset[EconomicAssetKind.SHARE_RECEIVABLE] != {credit}:
                    raise ValueError("SHARE_RECEIVABLE requires a receivable credit")
            elif self.event_kind in {
                EconomicEventKind.SPLIT,
                EconomicEventKind.MERGE,
                EconomicEventKind.SECURITY_CONVERTED,
            }:
                security_directions = {
                    leg.direction
                    for leg in self.legs
                    if leg.asset_kind is EconomicAssetKind.SECURITY
                }
                if security_directions != {debit, credit}:
                    raise ValueError(
                        f"{self.event_kind.value} requires security debit and credit legs"
                    )
            elif self.event_kind is EconomicEventKind.CORPORATE_CASH_SETTLED:
                cash_is_credit = directions_by_asset[EconomicAssetKind.CASH] == {
                    credit
                }
                noncash_legs = [
                    leg
                    for leg in self.legs
                    if leg.asset_kind is not EconomicAssetKind.CASH
                ]
                noncash_is_debit = bool(noncash_legs) and all(
                    leg.direction is debit
                    for leg in noncash_legs
                )
                if not cash_is_credit or not noncash_is_debit:
                    raise ValueError(
                        "CORPORATE_CASH_SETTLED requires asset debit and cash credit"
                    )
            elif self.event_kind is EconomicEventKind.LEGAL_WRITE_OFF:
                if any(leg.direction is not debit for leg in self.legs):
                    raise ValueError("LEGAL_WRITE_OFF requires debit directions")
        if (
            self.event_kind is EconomicEventKind.LATE_CORRECTION
            and self.correction_of_event_id is None
        ):
            raise ValueError("LATE_CORRECTION requires correction_of_event_id")
        return self


__all__ = [
    "AUTHORITY_STATE_TRANSITIONS",
    "ORDER_STATE_TRANSITIONS",
    "PLAN_STATE_TRANSITIONS",
    "POSITION_STATE_TRANSITIONS",
    "AuthoritySnapshot",
    "AuthorityState",
    "CapitalSnapshot",
    "CashEconomicEventLeg",
    "CashReceivableEconomicEventLeg",
    "CostBasisEconomicEventLeg",
    "DividendReceivable",
    "EconomicAssetKind",
    "EconomicEvent",
    "EconomicEventKind",
    "EconomicEventLeg",
    "EconomicLegDirection",
    "OrderSnapshot",
    "OrderState",
    "PlanSnapshot",
    "PlanState",
    "PositionSnapshot",
    "PositionState",
    "SecurityEconomicEventLeg",
    "SessionCheckpoint",
    "SessionPhase",
    "ShareReceivable",
    "ShareReceivableEconomicEventLeg",
    "ValuationMarkEconomicEventLeg",
]
