"""Checkpoint 2 RED lifecycle boundaries without Gateway behavior."""

from __future__ import annotations

import pytest


def _checkpoint2_artifacts():
    from src.screening.offensive.v3 import contracts

    required = ("PortfolioDecisionSeal", "ShadowDecision", "ExecutionPermit")
    missing = [name for name in required if not hasattr(contracts, name)]
    if missing:
        pytest.fail(
            f"Checkpoint 2 lifecycle artifacts are missing: {missing}",
            pytrace=False,
        )
    return tuple(getattr(contracts, name) for name in required)


def test_seal_permit_and_outbox_existence_alone_grant_no_send_authority() -> None:
    seal, shadow, permit = _checkpoint2_artifacts()
    forbidden = {
        "execution_authorized",
        "send_authorized",
        "send_claimed",
        "send_claimed_at",
        "broker_call_authorized",
    }
    assert forbidden.isdisjoint(seal.model_fields)
    assert forbidden.isdisjoint(shadow.model_fields)
    assert forbidden.isdisjoint(permit.model_fields)


def test_plan_state_transition_table_is_exact() -> None:
    from src.screening.offensive.v3.contracts import (
        PLAN_STATE_TRANSITIONS,
        PlanState,
    )

    expected = {
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
    assert dict(PLAN_STATE_TRANSITIONS) == expected


def test_send_claimed_has_only_ambiguous_ack_or_reconciled_not_accepted_successors() -> (
    None
):
    from src.screening.offensive.v3.contracts import (
        PLAN_STATE_TRANSITIONS,
        PlanState,
    )

    assert PLAN_STATE_TRANSITIONS[PlanState.SEND_CLAIMED] == frozenset(
        {
            PlanState.SUBMISSION_AMBIGUOUS,
            PlanState.BROKER_ACK,
            PlanState.RECONCILED_NOT_ACCEPTED,
        }
    )
    assert {
        PlanState.CANCELLED,
        PlanState.EXPIRED,
        PlanState.SUPERSEDED,
    }.isdisjoint(PLAN_STATE_TRANSITIONS[PlanState.SEND_CLAIMED])
