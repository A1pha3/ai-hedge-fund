"""Storage-free capital truth state, snapshot, and economic-event contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, ClassVar, Literal, Self, TypeAlias

from pydantic import Field, model_validator

from .base import (
    CanonicalModel,
    ExactInteger,
    ExecutionMode,
    MoneyCents,
    QuantityUnits,
    SchemaVersion,
    Sha256,
    UnitQuanta,
    UtcInstant,
    domain_hash,
)
from .evidence import NonEmptyStr
from .execution import OrderState, PlanState


PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
PositiveExactInt = Annotated[ExactInteger, Field(ge=1)]
PositiveQuantity = Annotated[QuantityUnits, Field(gt=0)]
NonNegativeQuantity = Annotated[QuantityUnits, Field(ge=0)]
NonNegativeCents = Annotated[MoneyCents, Field(ge=0)]
PositiveCents = Annotated[MoneyCents, Field(gt=0)]
NonNegativeUnits = Annotated[UnitQuanta, Field(ge=0)]
DrawdownPpm = Annotated[ExactInteger, Field(ge=0, le=1_000_000)]


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
        AuthorityState.BROKER_RECONCILED: frozenset({AuthorityState.HANDOFF_COMPLETE}),
        AuthorityState.HANDOFF_COMPLETE: frozenset(),
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
    released_quantity: NonNegativeInt
    as_of: UtcInstant

    @model_validator(mode="after")
    def validate_quantities(self) -> Self:
        if (
            self.filled_quantity + self.leaves_quantity + self.released_quantity
            != self.ordered_quantity
        ):
            raise ValueError(
                "order quantity conservation requires ordered = filled + leaves + released"
            )
        if self.state in {OrderState.CREATED, OrderState.SUBMITTED}:
            if not (
                self.filled_quantity == 0
                and self.leaves_quantity == self.ordered_quantity
                and self.released_quantity == 0
            ):
                raise ValueError(
                    f"{self.state.value} state has contradictory quantities"
                )
        elif self.state is OrderState.PARTIALLY_FILLED:
            if not (
                0 < self.filled_quantity < self.ordered_quantity
                and self.leaves_quantity > 0
                and self.released_quantity == 0
            ):
                raise ValueError("PARTIALLY_FILLED state has contradictory quantities")
        elif self.state is OrderState.FILLED:
            if not (
                self.filled_quantity == self.ordered_quantity
                and self.leaves_quantity == 0
                and self.released_quantity == 0
            ):
                raise ValueError("FILLED state has contradictory quantities")
        elif self.state is OrderState.REJECTED:
            if not (
                self.filled_quantity == 0
                and self.leaves_quantity == 0
                and self.released_quantity == self.ordered_quantity
            ):
                raise ValueError("REJECTED state has contradictory quantities")
        elif self.state is OrderState.CANCEL_REQUESTED:
            if not (
                self.filled_quantity < self.ordered_quantity
                and self.leaves_quantity > 0
                and self.released_quantity == 0
            ):
                raise ValueError("CANCEL_REQUESTED state has contradictory quantities")
        elif self.state is OrderState.CANCELLED:
            if not (
                self.filled_quantity < self.ordered_quantity
                and self.leaves_quantity == 0
                and self.released_quantity > 0
            ):
                raise ValueError("CANCELLED state has contradictory quantities")
        return self


class RiskSnapshotFreshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class RiskSnapshotCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class ExposureScope(StrEnum):
    GLOBAL = "GLOBAL"
    PORTFOLIO = "PORTFOLIO"
    RESEARCH_PROGRAM = "RESEARCH_PROGRAM"
    ECONOMIC_LINEAGE = "ECONOMIC_LINEAGE"
    STAGE = "STAGE"


class RiskOrderSide(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class RiskLatchState(StrEnum):
    CLEAR = "CLEAR"
    RISK_HALTED = "RISK_HALTED"


class StageLossLatchState(StrEnum):
    CLEAR = "CLEAR"
    STAGE_LOSS_HALTED = "STAGE_LOSS_HALTED"


class ReconciliationLatchState(StrEnum):
    CLEAR = "CLEAR"
    RECONCILIATION_HALT = "RECONCILIATION_HALT"


class ExitQuantityKnowledge(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


def _validate_capital_account_mode(
    mode: ExecutionMode,
    broker_account_id: str | None,
) -> None:
    if mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
        raise ValueError("research mode cannot represent executable capital truth")
    if mode is ExecutionMode.DAILY_BAR_PROXY:
        if broker_account_id is not None:
            raise ValueError("proxy mode cannot bind a real broker account")
    elif broker_account_id is None:
        raise ValueError("manual and broker modes require an account")


class CapitalPositionRisk(CanonicalModel):
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None
    mode: ExecutionMode
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    security_id: NonEmptyStr
    producer_namespace: NonEmptyStr
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    state: PositionState
    settled_quantity: NonNegativeQuantity
    tradable_quantity: NonNegativeQuantity
    share_receivable_quantity: NonNegativeQuantity
    marked_gross_cents: NonNegativeCents

    @model_validator(mode="after")
    def validate_position_risk(self) -> Self:
        _validate_capital_account_mode(self.mode, self.broker_account_id)
        if self.state not in {PositionState.OPEN, PositionState.EXIT_PENDING}:
            raise ValueError("capital position risk requires an open position state")
        if self.tradable_quantity > self.settled_quantity:
            raise ValueError("tradable quantity cannot exceed settled quantity")
        return self


class CapitalLiveOrderRisk(CanonicalModel):
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None
    mode: ExecutionMode
    order_id: NonEmptyStr
    order_line_id: NonEmptyStr
    side: RiskOrderSide
    state: OrderState
    producer_namespace: NonEmptyStr
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    leaves_quantity: PositiveQuantity
    worst_case_leaves_notional_cents: PositiveCents

    @model_validator(mode="after")
    def validate_live_order_risk(self) -> Self:
        _validate_capital_account_mode(self.mode, self.broker_account_id)
        if self.state not in {
            OrderState.SUBMITTED,
            OrderState.PARTIALLY_FILLED,
            OrderState.CANCEL_REQUESTED,
        }:
            raise ValueError("capital live order risk requires a live leaves state")
        return self


class EntryReserveRiskComponent(CanonicalModel):
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    source_id: NonEmptyStr
    covered_live_order_id: NonEmptyStr | None
    reserved_entry_gross_cents: PositiveCents

    def identity(self) -> tuple[str, str, str, str]:
        return (
            self.research_program_id,
            self.economic_lineage_id,
            self.stage_id,
            self.source_id,
        )


class PendingStressRiskComponent(CanonicalModel):
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    source_id: NonEmptyStr
    pending_stress_cents: PositiveCents

    def identity(self) -> tuple[str, str, str, str]:
        return (
            self.research_program_id,
            self.economic_lineage_id,
            self.stage_id,
            self.source_id,
        )


class CorporateActionRiskComponent(CanonicalModel):
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    source_id: NonEmptyStr
    pending_risk_cents: PositiveCents

    def identity(self) -> tuple[str, str, str, str]:
        return (
            self.research_program_id,
            self.economic_lineage_id,
            self.stage_id,
            self.source_id,
        )


class RiskExposureBucket(CanonicalModel):
    scope: ExposureScope
    portfolio_id: NonEmptyStr | None
    research_program_id: NonEmptyStr | None
    economic_lineage_id: NonEmptyStr | None
    stage_id: NonEmptyStr | None
    position_marked_gross_cents: NonNegativeCents
    live_order_leaves_gross_cents: NonNegativeCents
    reserved_entry_gross_cents: NonNegativeCents
    pending_stress_cents: NonNegativeCents
    corporate_action_pending_risk_cents: NonNegativeCents
    unattributed_risk_cents: NonNegativeCents
    total_gross_cents: NonNegativeCents

    @model_validator(mode="after")
    def validate_exposure(self) -> Self:
        identities = (
            self.portfolio_id,
            self.research_program_id,
            self.economic_lineage_id,
            self.stage_id,
        )
        required_depth = {
            ExposureScope.GLOBAL: 0,
            ExposureScope.PORTFOLIO: 1,
            ExposureScope.RESEARCH_PROGRAM: 2,
            ExposureScope.ECONOMIC_LINEAGE: 3,
            ExposureScope.STAGE: 4,
        }[self.scope]
        if any(value is None for value in identities[:required_depth]) or any(
            value is not None for value in identities[required_depth:]
        ):
            raise ValueError("exposure scope identity is incomplete or over-specified")
        components = (
            self.position_marked_gross_cents,
            self.live_order_leaves_gross_cents,
            self.reserved_entry_gross_cents,
            self.pending_stress_cents,
            self.corporate_action_pending_risk_cents,
            self.unattributed_risk_cents,
        )
        if sum(components) != self.total_gross_cents:
            raise ValueError("exposure aggregate does not equal its named components")
        return self

    def identity(self) -> tuple[ExposureScope, str, str, str, str]:
        return (
            self.scope,
            self.portfolio_id or "",
            self.research_program_id or "",
            self.economic_lineage_id or "",
            self.stage_id or "",
        )


class StageLossLatchSnapshot(CanonicalModel):
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    stage_loss_budget_id: NonEmptyStr
    frozen_budget_cents: PositiveCents
    consumed_cents: NonNegativeCents
    stage_loss_version: PositiveExactInt
    state: StageLossLatchState

    @model_validator(mode="after")
    def validate_stage_loss(self) -> Self:
        exhausted = self.consumed_cents >= self.frozen_budget_cents
        if exhausted != (self.state is StageLossLatchState.STAGE_LOSS_HALTED):
            raise ValueError(
                "stage loss halt must match nonreplenishable budget consumption"
            )
        return self

    def identity(self) -> tuple[str, str, str]:
        return (
            self.research_program_id,
            self.economic_lineage_id,
            self.stage_id,
        )


_EXPOSURE_COMPONENT_FIELDS = (
    "position_marked_gross_cents",
    "live_order_leaves_gross_cents",
    "reserved_entry_gross_cents",
    "pending_stress_cents",
    "corporate_action_pending_risk_cents",
)


def _drawdown_ppm(nav_cents: int, high_water_mark_cents: int) -> int:
    if high_water_mark_cents == 0:
        return 0
    return ((high_water_mark_cents - nav_cents) * 1_000_000) // high_water_mark_cents


class CapitalRiskSnapshot(CanonicalModel):
    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.capital.risk-snapshot.v1"

    risk_snapshot_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None
    base_currency: NonEmptyStr
    mode: ExecutionMode
    as_of: UtcInstant
    valid_until: UtcInstant
    freshness: RiskSnapshotFreshness
    completeness: RiskSnapshotCompleteness
    available_cash_cents: NonNegativeCents
    restricted_cash_cents: NonNegativeCents
    unsettled_cash_cents: NonNegativeCents
    cash_receivable_cents: NonNegativeCents
    cash_payable_cents: NonNegativeCents
    subscription_suspense_cents: NonNegativeCents
    redemption_suspense_cents: NonNegativeCents
    reserved_cash_cents: NonNegativeCents
    issued_unit_quanta: NonNegativeUnits
    pending_redeemed_unit_quanta: NonNegativeUnits
    positions: tuple[CapitalPositionRisk, ...]
    live_orders: tuple[CapitalLiveOrderRisk, ...]
    entry_reserves: tuple[EntryReserveRiskComponent, ...]
    pending_stress_components: tuple[PendingStressRiskComponent, ...]
    corporate_action_risk_components: tuple[CorporateActionRiskComponent, ...]
    unattributed_risk_cents: NonNegativeCents
    exposures: Annotated[tuple[RiskExposureBucket, ...], Field(min_length=5)]
    total_gross_exposure_cents: NonNegativeCents
    as_observed_nav_cents: NonNegativeCents
    lifetime_high_water_mark_cents: NonNegativeCents
    active_epoch_high_water_mark_cents: NonNegativeCents
    lifetime_drawdown_ppm: DrawdownPpm
    active_epoch_drawdown_ppm: DrawdownPpm
    risk_latch: RiskLatchState
    stage_loss_latches: tuple[StageLossLatchSnapshot, ...]
    reconciliation_latch: ReconciliationLatchState
    policy_activation_hash: Sha256
    policy_epoch: PositiveExactInt
    authority_epoch: PositiveExactInt
    risk_epoch: PositiveExactInt
    registry_epoch: PositiveExactInt
    authorization_id: NonEmptyStr
    authorization_version: PositiveExactInt
    stage_loss_state_version: PositiveExactInt
    writer_fencing_epoch: PositiveExactInt
    capital_version: PositiveExactInt
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        _validate_capital_account_mode(self.mode, self.broker_account_id)
        if self.valid_until <= self.as_of:
            raise ValueError("risk snapshot validity must extend beyond as_of")
        if self.pending_redeemed_unit_quanta > self.issued_unit_quanta:
            raise ValueError("pending redeemed units cannot exceed issued units")

        position_ids = [
            (position.position_lineage_id, position.economic_lot_id)
            for position in self.positions
        ]
        if len({identity[0] for identity in position_ids}) != len(position_ids) or len(
            {identity[1] for identity in position_ids}
        ) != len(position_ids):
            raise ValueError("duplicate position or economic lot identity")
        if position_ids != sorted(position_ids):
            raise ValueError("position identities must be in canonical order")

        order_ids = [
            (order.order_id, order.order_line_id) for order in self.live_orders
        ]
        if len({identity[0] for identity in order_ids}) != len(order_ids) or len(
            {identity[1] for identity in order_ids}
        ) != len(order_ids):
            raise ValueError("duplicate live order identity")
        if order_ids != sorted(order_ids):
            raise ValueError("live order identities must be in canonical order")

        for component in (*self.positions, *self.live_orders):
            if component.portfolio_id != self.portfolio_id:
                raise ValueError("capital component portfolio does not match snapshot")
            if component.broker_account_id != self.broker_account_id:
                raise ValueError("capital component account does not match snapshot")

        latch_ids = [latch.identity() for latch in self.stage_loss_latches]
        if len(latch_ids) != len(set(latch_ids)):
            raise ValueError("duplicate stage loss latch identity")
        budget_ids = [latch.stage_loss_budget_id for latch in self.stage_loss_latches]
        if len(budget_ids) != len(set(budget_ids)):
            raise ValueError("duplicate stage loss budget identity")
        self._validate_risk_component_identities()

        self._validate_exposures()
        self._validate_nav_and_latches()
        return self

    def _validate_risk_component_identities(self) -> None:
        for components, label in (
            (self.entry_reserves, "entry reserve"),
            (self.pending_stress_components, "pending stress"),
            (self.corporate_action_risk_components, "corporate action risk"),
        ):
            identities = [component.identity() for component in components]
            if len(identities) != len(set(identities)):
                raise ValueError(f"duplicate {label} composite identity")
            if identities != sorted(identities):
                raise ValueError(f"{label} identities must be in canonical order")

        live_entry_orders = {
            order.order_id: order
            for order in self.live_orders
            if order.side is RiskOrderSide.ENTRY
        }
        for reserve in self.entry_reserves:
            if reserve.covered_live_order_id is None:
                continue
            order = live_entry_orders.get(reserve.covered_live_order_id)
            if order is None:
                raise ValueError("entry reserve covers an unknown live order")
            if (
                reserve.research_program_id,
                reserve.economic_lineage_id,
                reserve.stage_id,
            ) != (
                order.research_program_id,
                order.economic_lineage_id,
                order.stage_id,
            ):
                raise ValueError("entry reserve attribution must match live order")

        if self.reserved_cash_cents != sum(
            reserve.reserved_entry_gross_cents for reserve in self.entry_reserves
        ):
            raise ValueError("reserved cash must equal itemized entry reserves")

    def artifact_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, self.schema_major, self)

    def content_hash(self) -> str:
        return self.artifact_hash()

    def _validate_exposures(self) -> None:
        exposure_ids = [exposure.identity() for exposure in self.exposures]
        if len(exposure_ids) != len(set(exposure_ids)):
            raise ValueError("duplicate exposure identity")
        attributed_components = (
            *self.positions,
            *self.live_orders,
            *self.entry_reserves,
            *self.pending_stress_components,
            *self.corporate_action_risk_components,
        )
        program_ids = {
            component.research_program_id for component in attributed_components
        }
        lineage_ids = {
            (component.research_program_id, component.economic_lineage_id)
            for component in attributed_components
        }
        stage_ids = {
            (
                component.research_program_id,
                component.economic_lineage_id,
                component.stage_id,
            )
            for component in attributed_components
        }
        expected_ids = {
            (ExposureScope.GLOBAL, "", "", "", ""),
            (ExposureScope.PORTFOLIO, self.portfolio_id, "", "", ""),
            *{
                (
                    ExposureScope.RESEARCH_PROGRAM,
                    self.portfolio_id,
                    program_id,
                    "",
                    "",
                )
                for program_id in program_ids
            },
            *{
                (
                    ExposureScope.ECONOMIC_LINEAGE,
                    self.portfolio_id,
                    program_id,
                    lineage_id,
                    "",
                )
                for program_id, lineage_id in lineage_ids
            },
            *{
                (
                    ExposureScope.STAGE,
                    self.portfolio_id,
                    program_id,
                    lineage_id,
                    stage_id,
                )
                for program_id, lineage_id, stage_id in stage_ids
            },
        }
        if set(exposure_ids) != expected_ids:
            raise ValueError(
                "exposure hierarchy is incomplete or contains an unknown scope"
            )

        by_identity = {exposure.identity(): exposure for exposure in self.exposures}
        global_bucket = by_identity[(ExposureScope.GLOBAL, "", "", "", "")]
        portfolio_bucket = by_identity[
            (ExposureScope.PORTFOLIO, self.portfolio_id, "", "", "")
        ]
        expected_global = {
            "position_marked_gross_cents": sum(
                position.marked_gross_cents for position in self.positions
            ),
            "live_order_leaves_gross_cents": sum(
                order.worst_case_leaves_notional_cents
                for order in self.live_orders
                if order.side is RiskOrderSide.ENTRY
            ),
            "reserved_entry_gross_cents": sum(
                reserve.reserved_entry_gross_cents
                for reserve in self.entry_reserves
                if reserve.covered_live_order_id is None
            ),
            "pending_stress_cents": sum(
                component.pending_stress_cents
                for component in self.pending_stress_components
            ),
            "corporate_action_pending_risk_cents": sum(
                component.pending_risk_cents
                for component in self.corporate_action_risk_components
            ),
            "unattributed_risk_cents": self.unattributed_risk_cents,
        }
        for bucket in (global_bucket, portfolio_bucket):
            for field_name, expected_value in expected_global.items():
                if getattr(bucket, field_name) != expected_value:
                    raise ValueError(f"exposure aggregate mismatch for {field_name}")
        if global_bucket.total_gross_cents != self.total_gross_exposure_cents:
            raise ValueError("total gross exposure does not match global aggregate")
        if portfolio_bucket.total_gross_cents != global_bucket.total_gross_cents:
            raise ValueError("portfolio and global gross exposure must agree")

        program_buckets = [
            exposure
            for exposure in self.exposures
            if exposure.scope is ExposureScope.RESEARCH_PROGRAM
        ]
        for field_name in _EXPOSURE_COMPONENT_FIELDS:
            if getattr(portfolio_bucket, field_name) != sum(
                getattr(program, field_name) for program in program_buckets
            ):
                raise ValueError("portfolio exposure does not reconcile to programs")
        if portfolio_bucket.unattributed_risk_cents != self.unattributed_risk_cents:
            raise ValueError("unattributed risk must remain portfolio scoped")
        if portfolio_bucket.total_gross_cents != (
            sum(program.total_gross_cents for program in program_buckets)
            + self.unattributed_risk_cents
        ):
            raise ValueError(
                "portfolio gross exposure double-counts or omits a program"
            )

        for exposure in self.exposures:
            if exposure.scope in {ExposureScope.GLOBAL, ExposureScope.PORTFOLIO}:
                continue
            matching_positions = [
                position
                for position in self.positions
                if self._component_matches_exposure(position, exposure)
            ]
            matching_orders = [
                order
                for order in self.live_orders
                if order.side is RiskOrderSide.ENTRY
                and self._component_matches_exposure(order, exposure)
            ]
            matching_reserves = [
                reserve
                for reserve in self.entry_reserves
                if reserve.covered_live_order_id is None
                and self._component_matches_exposure(reserve, exposure)
            ]
            matching_stresses = [
                component
                for component in self.pending_stress_components
                if self._component_matches_exposure(component, exposure)
            ]
            matching_corporate_actions = [
                component
                for component in self.corporate_action_risk_components
                if self._component_matches_exposure(component, exposure)
            ]
            if exposure.position_marked_gross_cents != sum(
                position.marked_gross_cents for position in matching_positions
            ):
                raise ValueError("position exposure aggregate is inconsistent")
            if exposure.live_order_leaves_gross_cents != sum(
                order.worst_case_leaves_notional_cents for order in matching_orders
            ):
                raise ValueError("live order exposure aggregate is inconsistent")
            if exposure.reserved_entry_gross_cents != sum(
                reserve.reserved_entry_gross_cents for reserve in matching_reserves
            ):
                raise ValueError("entry reserve exposure aggregate is inconsistent")
            if exposure.pending_stress_cents != sum(
                component.pending_stress_cents for component in matching_stresses
            ):
                raise ValueError("pending stress attribution is inconsistent")
            if exposure.corporate_action_pending_risk_cents != sum(
                component.pending_risk_cents for component in matching_corporate_actions
            ):
                raise ValueError("corporate action risk attribution is inconsistent")
            if exposure.unattributed_risk_cents != 0:
                raise ValueError("attributed exposure cannot contain unattributed risk")

        self._validate_exposure_children(by_identity)

    @staticmethod
    def _component_matches_exposure(
        component: (
            CapitalPositionRisk
            | CapitalLiveOrderRisk
            | EntryReserveRiskComponent
            | PendingStressRiskComponent
            | CorporateActionRiskComponent
        ),
        exposure: RiskExposureBucket,
    ) -> bool:
        if component.research_program_id != exposure.research_program_id:
            return False
        if exposure.scope is ExposureScope.RESEARCH_PROGRAM:
            return True
        if component.economic_lineage_id != exposure.economic_lineage_id:
            return False
        if exposure.scope is ExposureScope.ECONOMIC_LINEAGE:
            return True
        return component.stage_id == exposure.stage_id

    @staticmethod
    def _validate_exposure_children(
        by_identity: dict[tuple[ExposureScope, str, str, str, str], RiskExposureBucket],
    ) -> None:
        for identity, parent in by_identity.items():
            scope, portfolio_id, program_id, lineage_id, _ = identity
            if scope is ExposureScope.RESEARCH_PROGRAM:
                child_scope = ExposureScope.ECONOMIC_LINEAGE
                children = [
                    bucket
                    for child_id, bucket in by_identity.items()
                    if child_id[0] is child_scope
                    and child_id[1] == portfolio_id
                    and child_id[2] == program_id
                ]
            elif scope is ExposureScope.ECONOMIC_LINEAGE:
                child_scope = ExposureScope.STAGE
                children = [
                    bucket
                    for child_id, bucket in by_identity.items()
                    if child_id[0] is child_scope
                    and child_id[1] == portfolio_id
                    and child_id[2] == program_id
                    and child_id[3] == lineage_id
                ]
            else:
                continue
            for field_name in _EXPOSURE_COMPONENT_FIELDS:
                if getattr(parent, field_name) != sum(
                    getattr(child, field_name) for child in children
                ):
                    raise ValueError("exposure child aggregate is inconsistent")
            if parent.total_gross_cents != (
                sum(child.total_gross_cents for child in children)
                + parent.unattributed_risk_cents
            ):
                raise ValueError("exposure hierarchy double-counts or omits risk")
        if any(
            bucket.unattributed_risk_cents != 0
            for bucket in by_identity.values()
            if bucket.scope not in {ExposureScope.GLOBAL, ExposureScope.PORTFOLIO}
        ):
            raise ValueError("program, lineage, and stage risk cannot be unattributed")

    def _validate_nav_and_latches(self) -> None:
        if self.as_observed_nav_cents > self.lifetime_high_water_mark_cents:
            raise ValueError("NAV cannot exceed lifetime high-water mark")
        if self.as_observed_nav_cents > self.active_epoch_high_water_mark_cents:
            raise ValueError("NAV cannot exceed active-epoch high-water mark")
        if self.lifetime_drawdown_ppm != _drawdown_ppm(
            self.as_observed_nav_cents,
            self.lifetime_high_water_mark_cents,
        ):
            raise ValueError("lifetime NAV drawdown is inconsistent")
        if self.active_epoch_drawdown_ppm != _drawdown_ppm(
            self.as_observed_nav_cents,
            self.active_epoch_high_water_mark_cents,
        ):
            raise ValueError("active-epoch NAV drawdown is inconsistent")
        if (
            self.active_epoch_drawdown_ppm >= 150_000
            and self.risk_latch is not RiskLatchState.RISK_HALTED
        ):
            raise ValueError("risk latch must halt at 15 percent drawdown")
        if (
            self.unattributed_risk_cents > 0
            and self.reconciliation_latch
            is not ReconciliationLatchState.RECONCILIATION_HALT
        ):
            raise ValueError(
                "NAV reconciliation latch must halt while risk is unattributed"
            )


class ExitMandate(CanonicalModel):
    """Independent exit authority derived only from authoritative capital truth."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.capital.exit-mandate.v1"

    exit_mandate_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None
    base_currency: NonEmptyStr
    mode: ExecutionMode
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    security_id: NonEmptyStr
    producer_namespace: NonEmptyStr
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    entry_plan_evidence_hash: Sha256
    fixed_exit_policy_fingerprint: Sha256
    exit_session_ordinal: PositiveExactInt
    due_session: date
    quantity_knowledge: ExitQuantityKnowledge
    reconciliation_pending: bool
    tradable_quantity: NonNegativeQuantity
    live_exit_leaves_quantity: NonNegativeQuantity
    executable_quantity: NonNegativeQuantity
    mandate_revision: PositiveExactInt
    supersedes_mandate_hash: Sha256 | None
    reopened_by_execution_revision_id: NonEmptyStr | None
    capital_version: PositiveExactInt
    writer_fencing_epoch: PositiveExactInt
    stable_client_order_id: NonEmptyStr
    issued_at: UtcInstant
    source_risk_snapshot_id: NonEmptyStr
    source_risk_snapshot_hash: Sha256
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_mandate(self) -> Self:
        _validate_capital_account_mode(self.mode, self.broker_account_id)
        if self.exit_session_ordinal != 10:
            raise ValueError("fixed exit policy requires T+10 session ordinal")
        if self.quantity_knowledge is ExitQuantityKnowledge.UNKNOWN:
            if not self.reconciliation_pending:
                raise ValueError("unknown quantity requires reconciliation pending")
            if any(
                quantity != 0
                for quantity in (
                    self.tradable_quantity,
                    self.live_exit_leaves_quantity,
                    self.executable_quantity,
                )
            ):
                raise ValueError("unknown quantity cannot expose orderable quantity")
        else:
            if self.reconciliation_pending:
                raise ValueError("known quantity cannot remain reconciliation pending")
            if self.live_exit_leaves_quantity > self.tradable_quantity:
                raise ValueError("live exit leaves cannot exceed tradable quantity")
            if self.executable_quantity != (
                self.tradable_quantity - self.live_exit_leaves_quantity
            ):
                raise ValueError(
                    "executable quantity must equal tradable quantity minus live exit leaves"
                )

        if self.mandate_revision == 1:
            if (
                self.supersedes_mandate_hash is not None
                or self.reopened_by_execution_revision_id is not None
            ):
                raise ValueError("first mandate revision cannot supersede or reopen")
        elif (
            self.supersedes_mandate_hash is None
            or self.reopened_by_execution_revision_id is None
        ):
            raise ValueError(
                "reopened mandate revision requires supersedes hash and execution provenance"
            )
        return self

    def artifact_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, self.schema_major, self)

    def content_hash(self) -> str:
        return self.artifact_hash()


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
            raise ValueError(
                "tradable receivable quantity cannot exceed total quantity"
            )
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
        EconomicEventKind.CORPORATE_CASH_SETTLED: frozenset({EconomicAssetKind.CASH}),
        EconomicEventKind.SECURITY_CONVERTED: frozenset({EconomicAssetKind.SECURITY}),
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
            leg for leg in self.legs if isinstance(leg, ValuationMarkEconomicEventLeg)
        ]
        if self.event_kind is EconomicEventKind.VALUATION:
            if len(valuation_legs) != len(self.legs):
                raise ValueError(
                    "valuation events may contain only valuation-mark legs"
                )
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
                    leg.direction for leg in self.legs if leg.asset_kind is asset_kind
                }
                for asset_kind in actual_assets
            }
            debit = EconomicLegDirection.DEBIT
            credit = EconomicLegDirection.CREDIT
            if self.event_kind is EconomicEventKind.TRADE_EXECUTED:
                cash_directions = directions_by_asset[EconomicAssetKind.CASH]
                security_directions = directions_by_asset[EconomicAssetKind.SECURITY]
                valid_trade = (
                    cash_directions == {debit} and security_directions == {credit}
                ) or (cash_directions == {credit} and security_directions == {debit})
                if not valid_trade:
                    raise ValueError(
                        "TRADE_EXECUTED violates debit/credit conservation"
                    )
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
            elif self.event_kind is EconomicEventKind.SECURITY_CONVERTED:
                security_directions = directions_by_asset[EconomicAssetKind.SECURITY]
                has_source_debit = debit in security_directions
                has_tradable_destination = credit in security_directions
                share_directions = directions_by_asset.get(
                    EconomicAssetKind.SHARE_RECEIVABLE,
                    set(),
                )
                has_receivable_destination = share_directions == {credit}
                if not has_source_debit:
                    raise ValueError(
                        "SECURITY_CONVERTED requires a source security debit"
                    )
                if has_tradable_destination == has_receivable_destination:
                    raise ValueError(
                        "SECURITY_CONVERTED requires exactly one destination representation"
                    )
            elif self.event_kind is EconomicEventKind.CORPORATE_CASH_SETTLED:
                cash_is_credit = directions_by_asset[EconomicAssetKind.CASH] == {credit}
                noncash_legs = [
                    leg
                    for leg in self.legs
                    if leg.asset_kind is not EconomicAssetKind.CASH
                ]
                noncash_is_debit = bool(noncash_legs) and all(
                    leg.direction is debit for leg in noncash_legs
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
    "POSITION_STATE_TRANSITIONS",
    "AuthoritySnapshot",
    "AuthorityState",
    "CapitalLiveOrderRisk",
    "CapitalPositionRisk",
    "CapitalRiskSnapshot",
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
    "ExitMandate",
    "ExposureScope",
    "OrderSnapshot",
    "PlanSnapshot",
    "PositionSnapshot",
    "PositionState",
    "ReconciliationLatchState",
    "RiskExposureBucket",
    "RiskLatchState",
    "RiskOrderSide",
    "RiskSnapshotCompleteness",
    "RiskSnapshotFreshness",
    "SecurityEconomicEventLeg",
    "SessionCheckpoint",
    "SessionPhase",
    "ShareReceivable",
    "ShareReceivableEconomicEventLeg",
    "StageLossLatchSnapshot",
    "StageLossLatchState",
    "ValuationMarkEconomicEventLeg",
]
