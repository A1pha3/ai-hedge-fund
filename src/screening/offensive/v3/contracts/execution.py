"""Public execution-contract namespace backed by one canonical definition."""

from ._execution_contracts import (
    ORDER_STATE_TRANSITIONS,
    PLAN_STATE_TRANSITIONS,
    EconomicProjectionState,
    ExecutionRevision,
    ExecutionRevisionHistory,
    ExecutionRevisionKind,
    OrderState,
    PlanState,
    validate_order_transition,
    validate_plan_transition,
)

__all__ = [
    "EconomicProjectionState",
    "ExecutionRevision",
    "ExecutionRevisionHistory",
    "ExecutionRevisionKind",
    "ORDER_STATE_TRANSITIONS",
    "OrderState",
    "PLAN_STATE_TRANSITIONS",
    "PlanState",
    "validate_order_transition",
    "validate_plan_transition",
]
