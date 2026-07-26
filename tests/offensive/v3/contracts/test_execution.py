"""Revision 2 contract tests for entry/order and execution-revision lifecycles."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError


UTC = timezone.utc
NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
HASH = "e" * 64


def _execution():
    try:
        from src.screening.offensive.v3.contracts import execution
    except ImportError:
        pytest.fail("Revision 2 execution contracts are not implemented", pytrace=False)
    return execution


def test_plan_and_order_state_values_are_exact() -> None:
    e = _execution()
    assert [state.value for state in e.PlanState] == [
        "SEALED",
        "PERMITTED",
        "OUTBOX_DURABLE",
        "SEND_CLAIMED",
        "SUBMISSION_AMBIGUOUS",
        "BROKER_ACK",
        "PARTIALLY_EXECUTED",
        "CANCEL_PENDING",
        "SUPERSEDED",
        "CANCELLED",
        "EXPIRED",
        "REJECTED",
        "RECONCILED_NOT_ACCEPTED",
        "EXECUTED",
    ]
    assert [state.value for state in e.OrderState] == [
        "CREATED",
        "SUBMITTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "REJECTED",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "EXPIRED",
    ]


def _expected_plan_transitions(e):
    return {
        e.PlanState.SEALED: {
            e.PlanState.PERMITTED,
            e.PlanState.SUPERSEDED,
            e.PlanState.CANCELLED,
            e.PlanState.EXPIRED,
        },
        e.PlanState.PERMITTED: {
            e.PlanState.OUTBOX_DURABLE,
            e.PlanState.CANCELLED,
            e.PlanState.EXPIRED,
        },
        e.PlanState.OUTBOX_DURABLE: {
            e.PlanState.SEND_CLAIMED,
            e.PlanState.CANCELLED,
            e.PlanState.EXPIRED,
        },
        e.PlanState.SEND_CLAIMED: {
            e.PlanState.SUBMISSION_AMBIGUOUS,
            e.PlanState.BROKER_ACK,
            e.PlanState.RECONCILED_NOT_ACCEPTED,
        },
        e.PlanState.SUBMISSION_AMBIGUOUS: {
            e.PlanState.BROKER_ACK,
            e.PlanState.RECONCILED_NOT_ACCEPTED,
        },
        e.PlanState.BROKER_ACK: {
            e.PlanState.PARTIALLY_EXECUTED,
            e.PlanState.EXECUTED,
            e.PlanState.CANCEL_PENDING,
            e.PlanState.REJECTED,
            e.PlanState.EXPIRED,
        },
        e.PlanState.PARTIALLY_EXECUTED: {
            e.PlanState.PARTIALLY_EXECUTED,
            e.PlanState.EXECUTED,
            e.PlanState.CANCEL_PENDING,
            e.PlanState.EXPIRED,
        },
        e.PlanState.CANCEL_PENDING: {
            e.PlanState.CANCEL_PENDING,
            e.PlanState.EXECUTED,
            e.PlanState.CANCELLED,
            e.PlanState.EXPIRED,
        },
        e.PlanState.SUPERSEDED: set(),
        e.PlanState.CANCELLED: set(),
        e.PlanState.EXPIRED: set(),
        e.PlanState.REJECTED: set(),
        e.PlanState.RECONCILED_NOT_ACCEPTED: set(),
        e.PlanState.EXECUTED: set(),
    }


def _expected_order_transitions(e):
    return {
        e.OrderState.CREATED: {e.OrderState.SUBMITTED, e.OrderState.REJECTED},
        e.OrderState.SUBMITTED: {
            e.OrderState.PARTIALLY_FILLED,
            e.OrderState.FILLED,
            e.OrderState.REJECTED,
            e.OrderState.CANCEL_REQUESTED,
            e.OrderState.EXPIRED,
        },
        e.OrderState.PARTIALLY_FILLED: {
            e.OrderState.PARTIALLY_FILLED,
            e.OrderState.FILLED,
            e.OrderState.CANCEL_REQUESTED,
            e.OrderState.EXPIRED,
        },
        e.OrderState.CANCEL_REQUESTED: {
            e.OrderState.PARTIALLY_FILLED,
            e.OrderState.FILLED,
            e.OrderState.CANCELLED,
            e.OrderState.EXPIRED,
        },
        e.OrderState.FILLED: set(),
        e.OrderState.REJECTED: set(),
        e.OrderState.CANCELLED: set(),
        e.OrderState.EXPIRED: set(),
    }


def test_transition_tables_are_exact_and_immutable() -> None:
    e = _execution()
    expected_plan = _expected_plan_transitions(e)
    expected_order = _expected_order_transitions(e)
    assert {
        state: set(next_states)
        for state, next_states in e.PLAN_STATE_TRANSITIONS.items()
    } == expected_plan
    assert {
        state: set(next_states)
        for state, next_states in e.ORDER_STATE_TRANSITIONS.items()
    } == expected_order
    with pytest.raises(TypeError):
        e.PLAN_STATE_TRANSITIONS[e.PlanState.SEALED] = frozenset()
    with pytest.raises(AttributeError):
        e.ORDER_STATE_TRANSITIONS[e.OrderState.SUBMITTED].add(e.OrderState.FILLED)


def test_plan_transition_validator_covers_the_exhaustive_negative_matrix() -> None:
    e = _execution()
    allowed = _expected_plan_transitions(e)
    for current in e.PlanState:
        for target in e.PlanState:
            if target in allowed[current]:
                assert e.validate_plan_transition(current, target) is None
            else:
                with pytest.raises(ValueError, match="plan transition"):
                    e.validate_plan_transition(current, target)


def test_order_transition_validator_covers_the_exhaustive_negative_matrix() -> None:
    e = _execution()
    allowed = _expected_order_transitions(e)
    for current in e.OrderState:
        for target in e.OrderState:
            if target in allowed[current]:
                assert e.validate_order_transition(current, target) is None
            else:
                with pytest.raises(ValueError, match="order transition"):
                    e.validate_order_transition(current, target)


def _revision_payload(e, **overrides):
    payload = {
        "execution_id": "execution-001",
        "revision": 1,
        "revision_kind": e.ExecutionRevisionKind.RECORDED,
        "supersedes_revision": None,
        "order_id": "order-001",
        "broker_order_id": "broker-order-001",
        "broker_execution_id": "broker-execution-001",
        "historical_terminal_order_state": e.OrderState.FILLED,
        "effective_filled_quantity": 100,
        "effective_gross_cash_cents": 100_000,
        "economic_projection_state": e.EconomicProjectionState.RECONCILED,
        "effective_at": NOW,
        "observed_at": NOW + timedelta(seconds=1),
        "source_envelope_hash": HASH,
        "schema_major": 2,
    }
    payload.update(overrides)
    return payload


def test_execution_revision_contract_has_exact_schema_and_typed_states() -> None:
    e = _execution()
    assert [kind.value for kind in e.ExecutionRevisionKind] == [
        "RECORDED",
        "BUSTED",
        "CORRECTED",
    ]
    assert [state.value for state in e.EconomicProjectionState] == [
        "RECONCILED",
        "REOPENED_BY_CORRECTION",
        "RECONCILIATION_PENDING",
    ]
    assert set(e.ExecutionRevision.model_fields) == {
        "execution_id",
        "revision",
        "revision_kind",
        "supersedes_revision",
        "order_id",
        "broker_order_id",
        "broker_execution_id",
        "historical_terminal_order_state",
        "effective_filled_quantity",
        "effective_gross_cash_cents",
        "economic_projection_state",
        "effective_at",
        "observed_at",
        "source_envelope_hash",
        "schema_major",
    }
    assert set(e.ExecutionRevisionHistory.model_fields) == {
        "execution_id",
        "order_id",
        "revisions",
        "active_revision",
        "schema_major",
    }


def test_terminal_order_history_accepts_higher_bust_and_correction_revisions() -> None:
    e = _execution()
    recorded = e.ExecutionRevision(**_revision_payload(e))
    busted = e.ExecutionRevision(
        **_revision_payload(
            e,
            revision=2,
            revision_kind=e.ExecutionRevisionKind.BUSTED,
            supersedes_revision=1,
            effective_filled_quantity=0,
            effective_gross_cash_cents=0,
            economic_projection_state=e.EconomicProjectionState.REOPENED_BY_CORRECTION,
            observed_at=NOW + timedelta(minutes=1),
        )
    )
    corrected = e.ExecutionRevision(
        **_revision_payload(
            e,
            revision=3,
            revision_kind=e.ExecutionRevisionKind.CORRECTED,
            supersedes_revision=2,
            effective_filled_quantity=60,
            effective_gross_cash_cents=61_000,
            economic_projection_state=e.EconomicProjectionState.RECONCILIATION_PENDING,
            observed_at=NOW + timedelta(minutes=2),
        )
    )
    history = e.ExecutionRevisionHistory(
        execution_id="execution-001",
        order_id="order-001",
        revisions=(recorded, busted, corrected),
        active_revision=3,
        schema_major=2,
    )
    assert history.revisions[0].historical_terminal_order_state is e.OrderState.FILLED
    assert history.revisions[-1].historical_terminal_order_state is e.OrderState.FILLED
    assert (
        history.revisions[-1].economic_projection_state
        is e.EconomicProjectionState.RECONCILIATION_PENDING
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"historical_terminal_order_state": "SUBMITTED"},
        {"revision": 2, "revision_kind": "BUSTED", "supersedes_revision": None},
        {"revision": 1, "revision_kind": "CORRECTED", "supersedes_revision": 0},
        {
            "revision": 2,
            "revision_kind": "BUSTED",
            "supersedes_revision": 1,
            "effective_filled_quantity": 1,
        },
        {
            "revision": 2,
            "revision_kind": "BUSTED",
            "supersedes_revision": 1,
            "effective_gross_cash_cents": 1,
        },
        {"effective_filled_quantity": -1},
        {"effective_gross_cash_cents": -1},
        {"observed_at": NOW - timedelta(seconds=1)},
    ],
)
def test_execution_revision_rejects_nonterminal_rewrites_and_inconsistent_values(
    overrides,
) -> None:
    e = _execution()
    with pytest.raises(ValidationError):
        e.ExecutionRevision(**_revision_payload(e, **overrides))


def test_revision_history_rejects_gaps_identity_or_terminal_rewrite() -> None:
    e = _execution()
    recorded = e.ExecutionRevision(**_revision_payload(e))
    valid_bust = _revision_payload(
        e,
        revision=2,
        revision_kind=e.ExecutionRevisionKind.BUSTED,
        supersedes_revision=1,
        effective_filled_quantity=0,
        effective_gross_cash_cents=0,
        observed_at=NOW + timedelta(minutes=1),
    )
    for bad_revision, active_revision in [
        (
            e.ExecutionRevision(
                **(valid_bust | {"revision": 3, "supersedes_revision": 2})
            ),
            3,
        ),
        (e.ExecutionRevision(**(valid_bust | {"execution_id": "execution-other"})), 2),
        (e.ExecutionRevision(**(valid_bust | {"order_id": "order-other"})), 2),
        (
            e.ExecutionRevision(
                **(
                    valid_bust
                    | {"historical_terminal_order_state": e.OrderState.CANCELLED}
                )
            ),
            2,
        ),
    ]:
        with pytest.raises(ValidationError, match="revision|identity|terminal"):
            e.ExecutionRevisionHistory(
                execution_id="execution-001",
                order_id="order-001",
                revisions=(recorded, bad_revision),
                active_revision=active_revision,
                schema_major=2,
            )
