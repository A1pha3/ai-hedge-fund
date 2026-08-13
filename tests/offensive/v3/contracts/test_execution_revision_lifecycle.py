"""Revision 2 contract tests for entry/order and execution-revision lifecycles."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

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
        "portfolio_id": "portfolio-v3",
        "broker_account_id": "broker-account-001",
        "mode": e.ExecutionMode.BROKER_CONFIRMED,
        "security_id": "600000.SH",
        "position_lineage_id": "position-001",
        "economic_lot_id": "lot-001",
        "side": e.ExecutionSide.ENTRY,
        "broker_order_id": "broker-order-001",
        "broker_execution_id": "broker-execution-001",
        "historical_terminal_order_state": e.OrderState.FILLED,
        "effective_filled_quantity": 100,
        "effective_position_quantity": 100,
        "effective_gross_cash_cents": 100_000,
        "effective_position_state": e.EffectivePositionState.EXIT_PENDING,
        "exit_mandate_id": "exit-mandate-001",
        "exit_mandate_revision": 1,
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
    assert [side.value for side in e.ExecutionSide] == ["ENTRY", "EXIT"]
    assert [state.value for state in e.EffectivePositionState] == [
        "OPEN",
        "EXIT_PENDING",
        "FLAT",
        "RECONCILIATION_HALT",
    ]
    assert set(e.ExecutionRevision.model_fields) == {
        "execution_id",
        "revision",
        "revision_kind",
        "supersedes_revision",
        "order_id",
        "portfolio_id",
        "broker_account_id",
        "mode",
        "security_id",
        "position_lineage_id",
        "economic_lot_id",
        "side",
        "broker_order_id",
        "broker_execution_id",
        "historical_terminal_order_state",
        "effective_filled_quantity",
        "effective_position_quantity",
        "effective_gross_cash_cents",
        "effective_position_state",
        "exit_mandate_id",
        "exit_mandate_revision",
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


def test_execution_types_are_defined_by_the_public_execution_module() -> None:
    from src.screening.offensive.v3 import contracts
    from src.screening.offensive.v3.contracts import _execution_contracts, capital

    public = _execution()
    names = (
        "PlanState",
        "OrderState",
        "ExecutionRevisionKind",
        "EconomicProjectionState",
        "ExecutionSide",
        "EffectivePositionState",
        "ExecutionRevision",
        "ExecutionRevisionHistory",
    )
    for name in names:
        public_type = getattr(public, name)
        assert public_type.__module__ == (
            "src.screening.offensive.v3.contracts.execution"
        )
        assert getattr(contracts, name) is public_type
        assert getattr(_execution_contracts, name) is public_type
    assert capital.PlanState is public.PlanState
    assert capital.OrderState is public.OrderState


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
            effective_position_quantity=0,
            effective_gross_cash_cents=0,
            effective_position_state=e.EffectivePositionState.FLAT,
            exit_mandate_id=None,
            exit_mandate_revision=None,
            economic_projection_state=e.EconomicProjectionState.RECONCILED,
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
            effective_position_quantity=60,
            effective_gross_cash_cents=61_000,
            effective_position_state=e.EffectivePositionState.EXIT_PENDING,
            exit_mandate_id="exit-mandate-001",
            exit_mandate_revision=2,
            economic_projection_state=e.EconomicProjectionState.REOPENED_BY_CORRECTION,
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
        is e.EconomicProjectionState.REOPENED_BY_CORRECTION
    )
    assert history.revisions[-1].exit_mandate_revision == 2


def test_negative_long_only_position_is_preserved_as_reconciliation_halt() -> None:
    e = _execution()
    negative = e.ExecutionRevision(
        **_revision_payload(
            e,
            side=e.ExecutionSide.EXIT,
            effective_filled_quantity=120,
            effective_position_quantity=-20,
            effective_position_state=e.EffectivePositionState.RECONCILIATION_HALT,
            exit_mandate_id=None,
            exit_mandate_revision=None,
            economic_projection_state=e.EconomicProjectionState.RECONCILIATION_PENDING,
        )
    )
    assert negative.effective_position_quantity == -20
    assert (
        negative.effective_position_state
        is e.EffectivePositionState.RECONCILIATION_HALT
    )

    for impossible in (
        {"effective_position_quantity": -20},
        {
            "effective_position_quantity": 0,
            "effective_position_state": e.EffectivePositionState.RECONCILIATION_HALT,
            "exit_mandate_id": None,
            "exit_mandate_revision": None,
        },
    ):
        with pytest.raises(ValidationError, match="position|negative|reconciliation"):
            e.ExecutionRevision(**_revision_payload(e, **impossible))


@pytest.mark.parametrize("bad", [True, 100.0, Decimal("100"), "100"])
@pytest.mark.parametrize(
    "field_name", ["effective_filled_quantity", "effective_position_quantity"]
)
def test_execution_revision_quantities_require_native_integers(field_name, bad) -> None:
    e = _execution()
    with pytest.raises(ValidationError, match="integer|int"):
        e.ExecutionRevision(**_revision_payload(e, **{field_name: bad}))


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
        {
            "effective_position_quantity": 100,
            "effective_position_state": "FLAT",
        },
        {"effective_position_quantity": 100, "exit_mandate_id": None},
        {"effective_position_quantity": 100, "exit_mandate_revision": None},
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
        effective_position_quantity=0,
        effective_gross_cash_cents=0,
        effective_position_state=e.EffectivePositionState.FLAT,
        exit_mandate_id=None,
        exit_mandate_revision=None,
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
        (e.ExecutionRevision(**(valid_bust | {"portfolio_id": "portfolio-other"})), 2),
        (
            e.ExecutionRevision(
                **(valid_bust | {"broker_account_id": "broker-account-other"})
            ),
            2,
        ),
        (e.ExecutionRevision(**(valid_bust | {"security_id": "600001.SH"})), 2),
        (
            e.ExecutionRevision(
                **(valid_bust | {"position_lineage_id": "position-other"})
            ),
            2,
        ),
        (e.ExecutionRevision(**(valid_bust | {"economic_lot_id": "lot-other"})), 2),
        (e.ExecutionRevision(**(valid_bust | {"side": e.ExecutionSide.EXIT})), 2),
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


# =============================================================================
# Shared mechanical shrink resolver (Task 8)
# =============================================================================


def _mechanical_binding(e, *, order_line_id="line-1", **caps):
    all_caps = {
        "availability_cap_units": 300,
        "price_cap_units": 300,
        "capacity_cap_units": 300,
        "cash_cap_units": 300,
        "capital_risk_cap_units": 300,
    }
    all_caps.update(caps)
    return e.PermitLineMechanicalBinding(
        order_line_id=e.NonEmptyStr(order_line_id),
        predicate_policy_version="t1-open-t10-open-slippage.v2",
        preopen_fact_snapshot_id="preopen-facts-1",
        preopen_fact_snapshot_hash="a" * 64,
        preopen_fact_as_of=NOW,
        **all_caps,
    )


def test_mechanical_resolver_is_exported_and_pure() -> None:
    e = _execution()
    assert e.MechanicalQuantityResolution.__name__ == "MechanicalQuantityResolution"
    binding = _mechanical_binding(e)
    resolution = e.resolve_mechanical_quantity(300, 100, binding)
    assert isinstance(resolution, e.MechanicalQuantityResolution)
    assert resolution.permitted_quantity_units == 300
    assert resolution.reason_code is e.PermitReasonCode.UNCHANGED


def test_mechanical_resolver_never_increases_sealed_quantity() -> None:
    e = _execution()
    # A cap above the sealed quantity must clamp to the sealed value.
    binding = _mechanical_binding(e, availability_cap_units=500)
    resolution = e.resolve_mechanical_quantity(300, 100, binding)
    assert resolution.permitted_quantity_units == 300
    assert resolution.reason_code is e.PermitReasonCode.UNCHANGED


def test_mechanical_resolver_applies_lot_floor_to_every_cap() -> None:
    e = _execution()
    # 250 units is 2.5 lots; the floor must produce 200, and the reason
    # follows the binding's cap priority, not the floored quantity.
    binding = _mechanical_binding(e, capacity_cap_units=250)
    resolution = e.resolve_mechanical_quantity(300, 100, binding)
    assert resolution.permitted_quantity_units == 200
    assert resolution.reason_code is e.PermitReasonCode.CAPACITY_REDUCTION
    # A sub-lot cap floors to zero.
    binding = _mechanical_binding(e, cash_cap_units=50)
    resolution = e.resolve_mechanical_quantity(300, 100, binding)
    assert resolution.permitted_quantity_units == 0
    assert resolution.reason_code is e.PermitReasonCode.CASH_REDUCTION


def test_mechanical_resolver_reason_follows_cap_priority_on_ties() -> None:
    e = _execution()
    # Availability and price both cap at 200; priority (availability first)
    # owns the reason label.
    binding = _mechanical_binding(e, availability_cap_units=200, price_cap_units=200)
    resolution = e.resolve_mechanical_quantity(300, 100, binding)
    assert resolution.permitted_quantity_units == 200
    assert resolution.reason_code is e.PermitReasonCode.AVAILABILITY_REDUCTION
