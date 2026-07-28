"""Public immutable execution lifecycle and broker-revision contracts."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Self

from pydantic import Field, model_validator

from .base import (
    CanonicalModel,
    ExactInteger,
    ExecutionMode,
    MoneyCents,
    QuantityUnits,
    SchemaVersion,
    Sha256,
    UtcInstant,
)
from .evidence import NonEmptyStr


PositiveInt = Annotated[ExactInteger, Field(ge=1)]
NonNegativeQuantity = Annotated[QuantityUnits, Field(ge=0)]
SignedQuantity = QuantityUnits
NonNegativeCents = Annotated[MoneyCents, Field(ge=0)]


class PlanState(StrEnum):
    SEALED = "SEALED"
    PERMITTED = "PERMITTED"
    OUTBOX_DURABLE = "OUTBOX_DURABLE"
    SEND_CLAIMED = "SEND_CLAIMED"
    SUBMISSION_AMBIGUOUS = "SUBMISSION_AMBIGUOUS"
    BROKER_ACK = "BROKER_ACK"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    CANCEL_PENDING = "CANCEL_PENDING"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    RECONCILED_NOT_ACCEPTED = "RECONCILED_NOT_ACCEPTED"
    EXECUTED = "EXECUTED"


class OrderState(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


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
            {PlanState.OUTBOX_DURABLE, PlanState.CANCELLED, PlanState.EXPIRED}
        ),
        PlanState.OUTBOX_DURABLE: frozenset(
            {PlanState.SEND_CLAIMED, PlanState.CANCELLED, PlanState.EXPIRED}
        ),
        PlanState.SEND_CLAIMED: frozenset(
            {
                PlanState.SUBMISSION_AMBIGUOUS,
                PlanState.BROKER_ACK,
                PlanState.RECONCILED_NOT_ACCEPTED,
            }
        ),
        PlanState.SUBMISSION_AMBIGUOUS: frozenset(
            {PlanState.BROKER_ACK, PlanState.RECONCILED_NOT_ACCEPTED}
        ),
        PlanState.BROKER_ACK: frozenset(
            {
                PlanState.PARTIALLY_EXECUTED,
                PlanState.EXECUTED,
                PlanState.CANCEL_PENDING,
                PlanState.REJECTED,
                PlanState.EXPIRED,
            }
        ),
        PlanState.PARTIALLY_EXECUTED: frozenset(
            {
                PlanState.PARTIALLY_EXECUTED,
                PlanState.EXECUTED,
                PlanState.CANCEL_PENDING,
                PlanState.EXPIRED,
            }
        ),
        PlanState.CANCEL_PENDING: frozenset(
            {
                PlanState.CANCEL_PENDING,
                PlanState.EXECUTED,
                PlanState.CANCELLED,
                PlanState.EXPIRED,
            }
        ),
        PlanState.SUPERSEDED: frozenset(),
        PlanState.CANCELLED: frozenset(),
        PlanState.EXPIRED: frozenset(),
        PlanState.REJECTED: frozenset(),
        PlanState.RECONCILED_NOT_ACCEPTED: frozenset(),
        PlanState.EXECUTED: frozenset(),
    }
)


ORDER_STATE_TRANSITIONS = MappingProxyType(
    {
        OrderState.CREATED: frozenset({OrderState.SUBMITTED, OrderState.REJECTED}),
        OrderState.SUBMITTED: frozenset(
            {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.REJECTED,
                OrderState.CANCEL_REQUESTED,
                OrderState.EXPIRED,
            }
        ),
        OrderState.PARTIALLY_FILLED: frozenset(
            {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.CANCEL_REQUESTED,
                OrderState.EXPIRED,
            }
        ),
        OrderState.CANCEL_REQUESTED: frozenset(
            {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.CANCELLED,
                OrderState.EXPIRED,
            }
        ),
        OrderState.FILLED: frozenset(),
        OrderState.REJECTED: frozenset(),
        OrderState.CANCELLED: frozenset(),
        OrderState.EXPIRED: frozenset(),
    }
)


def validate_plan_transition(current: PlanState, target: PlanState) -> None:
    if target not in PLAN_STATE_TRANSITIONS[current]:
        raise ValueError(f"invalid plan transition: {current.value} -> {target.value}")


def validate_order_transition(current: OrderState, target: OrderState) -> None:
    if target not in ORDER_STATE_TRANSITIONS[current]:
        raise ValueError(f"invalid order transition: {current.value} -> {target.value}")


class ExecutionRevisionKind(StrEnum):
    RECORDED = "RECORDED"
    BUSTED = "BUSTED"
    CORRECTED = "CORRECTED"


class EconomicProjectionState(StrEnum):
    RECONCILED = "RECONCILED"
    REOPENED_BY_CORRECTION = "REOPENED_BY_CORRECTION"
    RECONCILIATION_PENDING = "RECONCILIATION_PENDING"


class ExecutionSide(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class EffectivePositionState(StrEnum):
    OPEN = "OPEN"
    EXIT_PENDING = "EXIT_PENDING"
    FLAT = "FLAT"
    RECONCILIATION_HALT = "RECONCILIATION_HALT"


_TERMINAL_ORDER_STATES = frozenset(
    {
        OrderState.FILLED,
        OrderState.REJECTED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
    }
)


def _validate_execution_account_mode(
    mode: ExecutionMode,
    broker_account_id: str | None,
) -> None:
    if mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
        raise ValueError("research mode cannot represent an execution fact")
    if mode is ExecutionMode.DAILY_BAR_PROXY:
        if broker_account_id is not None:
            raise ValueError("proxy execution cannot bind a broker account")
    elif broker_account_id is None:
        raise ValueError("manual and broker execution require an account")


class ExecutionRevision(CanonicalModel):
    """One append-only revision of a broker execution's economic effect."""

    execution_id: NonEmptyStr
    revision: PositiveInt
    revision_kind: ExecutionRevisionKind
    supersedes_revision: PositiveInt | None
    order_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    broker_account_id: NonEmptyStr | None
    mode: ExecutionMode
    security_id: NonEmptyStr
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    side: ExecutionSide
    broker_order_id: NonEmptyStr
    broker_execution_id: NonEmptyStr
    historical_terminal_order_state: OrderState
    effective_filled_quantity: NonNegativeQuantity
    effective_position_quantity: SignedQuantity
    effective_gross_cash_cents: NonNegativeCents
    effective_position_state: EffectivePositionState
    exit_mandate_id: NonEmptyStr | None
    exit_mandate_revision: PositiveInt | None
    economic_projection_state: EconomicProjectionState
    effective_at: UtcInstant
    observed_at: UtcInstant
    source_envelope_hash: Sha256
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        _validate_execution_account_mode(self.mode, self.broker_account_id)
        if self.historical_terminal_order_state not in _TERMINAL_ORDER_STATES:
            raise ValueError("historical terminal order state must remain terminal")
        if self.observed_at < self.effective_at:
            raise ValueError("observed_at cannot precede effective_at")
        if self.revision_kind is ExecutionRevisionKind.RECORDED:
            if self.revision != 1 or self.supersedes_revision is not None:
                raise ValueError("RECORDED must be revision 1 without a predecessor")
        elif self.revision <= 1 or self.supersedes_revision != self.revision - 1:
            raise ValueError(
                "BUSTED/CORRECTED must supersede the immediately prior revision"
            )
        if self.revision_kind is ExecutionRevisionKind.BUSTED and (
            self.effective_filled_quantity != 0
            or self.effective_position_quantity != 0
            or self.effective_gross_cash_cents != 0
        ):
            raise ValueError(
                "BUSTED revision must have zero effective quantity and cash"
            )

        mandate_pair = (self.exit_mandate_id, self.exit_mandate_revision)
        if (mandate_pair[0] is None) != (mandate_pair[1] is None):
            raise ValueError("exit mandate ID and revision must be an all-or-none pair")
        if self.effective_position_quantity > 0:
            if self.effective_position_state not in {
                EffectivePositionState.OPEN,
                EffectivePositionState.EXIT_PENDING,
            }:
                raise ValueError(
                    "positive position requires OPEN or EXIT_PENDING state"
                )
            if mandate_pair[0] is None:
                raise ValueError("positive position requires an exit mandate revision")
        elif self.effective_position_quantity == 0:
            if self.effective_position_state is not EffectivePositionState.FLAT:
                raise ValueError("zero position requires FLAT state")
            if mandate_pair[0] is not None:
                raise ValueError("flat position cannot retain an exit mandate")
        else:
            if (
                self.effective_position_state
                is not EffectivePositionState.RECONCILIATION_HALT
                or self.economic_projection_state
                is not EconomicProjectionState.RECONCILIATION_PENDING
            ):
                raise ValueError(
                    "negative long-only position requires reconciliation halt"
                )
            if mandate_pair[0] is not None:
                raise ValueError(
                    "negative position cannot expose orderable exit quantity"
                )

        if (
            self.economic_projection_state
            is EconomicProjectionState.REOPENED_BY_CORRECTION
            and self.revision_kind is not ExecutionRevisionKind.CORRECTED
        ):
            raise ValueError("only a correction can reopen an economic projection")
        return self


class ExecutionRevisionHistory(CanonicalModel):
    """A complete, contiguous append-only execution revision chain."""

    execution_id: NonEmptyStr
    order_id: NonEmptyStr
    revisions: Annotated[tuple[ExecutionRevision, ...], Field(min_length=1)]
    active_revision: PositiveInt
    schema_major: SchemaVersion

    @model_validator(mode="after")
    def validate_history(self) -> Self:
        first = self.revisions[0]
        if (
            first.revision != 1
            or first.revision_kind is not ExecutionRevisionKind.RECORDED
        ):
            raise ValueError("revision history must begin with RECORDED revision 1")

        stable_identity = (
            first.portfolio_id,
            first.broker_account_id,
            first.mode,
            first.security_id,
            first.position_lineage_id,
            first.economic_lot_id,
            first.side,
            first.broker_order_id,
            first.broker_execution_id,
            first.historical_terminal_order_state,
        )
        previous_observed_at = first.observed_at
        for expected_revision, revision in enumerate(self.revisions, start=1):
            if revision.revision != expected_revision:
                raise ValueError("revision history must be contiguous and canonical")
            if (
                revision.execution_id != self.execution_id
                or revision.order_id != self.order_id
            ):
                raise ValueError("revision identity must match history identity")
            current_identity = (
                revision.portfolio_id,
                revision.broker_account_id,
                revision.mode,
                revision.security_id,
                revision.position_lineage_id,
                revision.economic_lot_id,
                revision.side,
                revision.broker_order_id,
                revision.broker_execution_id,
                revision.historical_terminal_order_state,
            )
            if current_identity != stable_identity:
                raise ValueError(
                    "execution, account, position, broker, and terminal identity "
                    "cannot change across revisions"
                )
            if expected_revision > 1:
                if revision.supersedes_revision != expected_revision - 1:
                    raise ValueError("revision predecessor must be contiguous")
                if revision.observed_at < previous_observed_at:
                    raise ValueError("revision observations must be monotonic")
            previous_observed_at = revision.observed_at

        if self.active_revision != self.revisions[-1].revision:
            raise ValueError("active revision must be the highest appended revision")
        return self


__all__ = [
    "EconomicProjectionState",
    "EffectivePositionState",
    "ExecutionMode",
    "ExecutionRevision",
    "ExecutionRevisionHistory",
    "ExecutionRevisionKind",
    "ExecutionSide",
    "ORDER_STATE_TRANSITIONS",
    "OrderState",
    "PLAN_STATE_TRANSITIONS",
    "PlanState",
    "validate_order_transition",
    "validate_plan_transition",
]
