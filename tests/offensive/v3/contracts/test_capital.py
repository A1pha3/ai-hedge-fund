"""Contract tests for immutable capital truth snapshots and event shapes."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError


UTC = timezone.utc
HASH = "d" * 64


def _contracts():
    try:
        from src.screening.offensive.v3.contracts import capital
    except ImportError:
        pytest.fail("capital contracts are not implemented", pytrace=False)
    if not hasattr(capital, "CapitalSnapshot"):
        pytest.fail("capital contracts are not implemented", pytrace=False)
    return capital


def test_legal_state_enum_values_are_exact() -> None:
    capital = _contracts()
    assert [state.value for state in capital.PositionState] == [
        "OPEN",
        "EXIT_PENDING",
        "CLOSED",
        "LEGAL_TERMINAL",
    ]
    assert [state.value for state in capital.AuthorityState] == [
        "ACTIVE",
        "DRAINING",
        "BROKER_RECONCILED",
        "HANDOFF_COMPLETE",
    ]
    assert [state.value for state in capital.PlanState] == [
        "SEALED",
        "PERMITTED",
        "ORDER_DURABLE",
        "PARTIALLY_EXECUTED",
        "CANCEL_PENDING",
        "SUPERSEDED",
        "CANCELLED",
        "EXPIRED",
        "EXECUTED",
    ]
    assert [state.value for state in capital.OrderState] == [
        "CREATED",
        "SUBMITTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "REJECTED",
        "CANCEL_REQUESTED",
        "CANCELLED",
    ]


def test_plan_state_transition_table_is_exact() -> None:
    c = _contracts()
    expected = {
        c.PlanState.SEALED: {
            c.PlanState.PERMITTED,
            c.PlanState.SUPERSEDED,
            c.PlanState.CANCELLED,
            c.PlanState.EXPIRED,
        },
        c.PlanState.PERMITTED: {
            c.PlanState.ORDER_DURABLE,
            c.PlanState.CANCELLED,
            c.PlanState.EXPIRED,
        },
        c.PlanState.ORDER_DURABLE: {
            c.PlanState.PARTIALLY_EXECUTED,
            c.PlanState.EXECUTED,
            c.PlanState.CANCEL_PENDING,
        },
        c.PlanState.PARTIALLY_EXECUTED: {
            c.PlanState.EXECUTED,
            c.PlanState.CANCEL_PENDING,
        },
        c.PlanState.CANCEL_PENDING: {
            c.PlanState.CANCEL_PENDING,
            c.PlanState.EXECUTED,
            c.PlanState.CANCELLED,
        },
        c.PlanState.SUPERSEDED: set(),
        c.PlanState.CANCELLED: set(),
        c.PlanState.EXPIRED: set(),
        c.PlanState.EXECUTED: set(),
    }
    assert {state: set(next_states) for state, next_states in c.PLAN_STATE_TRANSITIONS.items()} == expected


def test_order_state_transition_table_is_exact() -> None:
    c = _contracts()
    expected = {
        c.OrderState.CREATED: {c.OrderState.SUBMITTED, c.OrderState.REJECTED},
        c.OrderState.SUBMITTED: {
            c.OrderState.PARTIALLY_FILLED,
            c.OrderState.FILLED,
            c.OrderState.REJECTED,
            c.OrderState.CANCEL_REQUESTED,
        },
        c.OrderState.PARTIALLY_FILLED: {
            c.OrderState.PARTIALLY_FILLED,
            c.OrderState.FILLED,
            c.OrderState.CANCEL_REQUESTED,
        },
        c.OrderState.CANCEL_REQUESTED: {
            c.OrderState.PARTIALLY_FILLED,
            c.OrderState.FILLED,
            c.OrderState.CANCELLED,
        },
        c.OrderState.FILLED: set(),
        c.OrderState.REJECTED: set(),
        c.OrderState.CANCELLED: set(),
    }
    assert {state: set(next_states) for state, next_states in c.ORDER_STATE_TRANSITIONS.items()} == expected


def test_session_checkpoint_phases_are_monotonic_and_exact() -> None:
    c = _contracts()
    assert [phase.value for phase in c.SessionPhase] == [
        "CORPORATE_ACTIONS_APPLIED",
        "PREOPEN_RISK_LOCKED",
        "ORDER_INTENTS_DURABLE",
        "OPEN_RECONCILED",
        "CLOSE_VALUED",
        "SESSION_FINALIZED",
    ]
    checkpoint = c.SessionCheckpoint(
        session=date(2026, 7, 19),
        phase=c.SessionPhase.CLOSE_VALUED,
        stream_version=11,
        recorded_at=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
    )
    assert checkpoint.stream_version == 11


def test_capital_snapshot_is_frozen_and_preserves_cash_and_share_dimensions() -> None:
    c = _contracts()
    position = c.PositionSnapshot(
        position_lineage_id="position-001",
        economic_lot_id="lot-001",
        security_id="600000.SH",
        state=c.PositionState.OPEN,
        settled_quantity=1000,
        tradable_quantity=800,
        share_receivable_quantity=200,
        cost_basis=Decimal("10000.00"),
    )
    snapshot = c.CapitalSnapshot(
        capital_snapshot_id="capital-019",
        portfolio_id="paper-v3",
        authority_epoch=3,
        risk_epoch=8,
        capital_version=19,
        stream_version=29,
        mode=c.ExecutionMode.BROKER_CONFIRMED,
        as_of=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        cash=Decimal("50000.00"),
        nav=Decimal("100000.00"),
        gross_exposure=Decimal("50000.00"),
        high_water_mark=Decimal("101000.00"),
        positions=(position,),
        payload_content_hash=HASH,
    )
    assert snapshot.positions[0].share_receivable_quantity == 200
    with pytest.raises(ValidationError, match="frozen_instance"):
        snapshot.cash = Decimal("1")


def test_capital_aggregate_shapes_reject_impossible_quantities() -> None:
    c = _contracts()
    now = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)

    with pytest.raises(ValidationError, match="executed"):
        c.PlanSnapshot(
            seal_id="seal-001",
            order_line_id="line-600000-entry",
            seal_revision=1,
            portfolio_id="paper-v3",
            state=c.PlanState.EXECUTED,
            sealed_quantity=100,
            executed_quantity=101,
            as_of=now,
        )
    with pytest.raises(ValidationError, match="filled|leaves"):
        c.OrderSnapshot(
            order_id="order-001",
            seal_id="seal-001",
            order_line_id="line-600000-entry",
            order_revision=1,
            state=c.OrderState.PARTIALLY_FILLED,
            ordered_quantity=100,
            filled_quantity=80,
            leaves_quantity=30,
            released_quantity=0,
            as_of=now,
        )


def test_capital_plan_and_order_snapshots_preserve_sealed_line_identity() -> None:
    c = _contracts()
    now = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
    plan = c.PlanSnapshot(
        seal_id="seal-001",
        order_line_id="line-600000-entry",
        seal_revision=1,
        portfolio_id="paper-v3",
        state=c.PlanState.PERMITTED,
        sealed_quantity=100,
        executed_quantity=0,
        as_of=now,
    )
    order = c.OrderSnapshot(
        order_id="order-001",
        seal_id=plan.seal_id,
        order_line_id=plan.order_line_id,
        order_revision=1,
        state=c.OrderState.SUBMITTED,
        ordered_quantity=100,
        filled_quantity=0,
        leaves_quantity=100,
        released_quantity=0,
        as_of=now,
    )
    assert order.order_line_id == plan.order_line_id
    with pytest.raises(ValidationError, match="tradable"):
        c.ShareReceivable(
            receivable_id="shares-001",
            position_lineage_id="position-001",
            security_id="600001.SH",
            effective_date=date(2026, 7, 1),
            tradable_date=date(2026, 7, 20),
            quantity=100,
            tradable_quantity=101,
        )


@pytest.mark.parametrize(
    ("state", "filled", "leaves", "released"),
    [
        ("CREATED", 0, 100, 0),
        ("SUBMITTED", 0, 100, 0),
        ("PARTIALLY_FILLED", 40, 60, 0),
        ("FILLED", 100, 0, 0),
        ("REJECTED", 0, 0, 100),
        ("CANCEL_REQUESTED", 40, 60, 0),
        ("CANCELLED", 40, 0, 60),
    ],
)
def test_order_snapshot_accepts_exact_state_quantity_classes(
    state, filled, leaves, released
) -> None:
    c = _contracts()
    snapshot = c.OrderSnapshot(
        order_id="order-state",
        seal_id="seal-001",
        order_line_id="line-600000-entry",
        order_revision=1,
        state=c.OrderState(state),
        ordered_quantity=100,
        filled_quantity=filled,
        leaves_quantity=leaves,
        released_quantity=released,
        as_of=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
    )
    assert snapshot.ordered_quantity == (
        snapshot.filled_quantity
        + snapshot.leaves_quantity
        + snapshot.released_quantity
    )


@pytest.mark.parametrize(
    ("state", "filled", "leaves", "released"),
    [
        ("CREATED", 1, 99, 0),
        ("SUBMITTED", 1, 99, 0),
        ("PARTIALLY_FILLED", 0, 100, 0),
        ("FILLED", 99, 1, 0),
        ("REJECTED", 0, 100, 0),
        ("CANCEL_REQUESTED", 0, 99, 1),
        ("CANCELLED", 40, 1, 59),
    ],
)
def test_order_snapshot_rejects_state_quantity_contradictions(
    state, filled, leaves, released
) -> None:
    c = _contracts()
    with pytest.raises(ValidationError, match="state|quantity|conservation"):
        c.OrderSnapshot(
            order_id="order-state-invalid",
            seal_id="seal-001",
            order_line_id="line-600000-entry",
            order_revision=1,
            state=c.OrderState(state),
            ordered_quantity=100,
            filled_quantity=filled,
            leaves_quantity=leaves,
            released_quantity=released,
            as_of=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        )


def test_economic_event_supports_multi_leg_company_actions_and_late_corrections() -> None:
    c = _contracts()
    event = c.EconomicEvent(
        economic_event_id="event-001",
        event_kind=c.EconomicEventKind.SECURITY_CONVERTED,
        portfolio_id="paper-v3",
        position_lineage_id="position-001",
        economic_lot_id="lot-001",
        mode=c.ExecutionMode.BROKER_CONFIRMED,
        source_authority="broker-confirmation",
        effective_at=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        stream_version=30,
        correction_of_event_id=None,
        legs=(
            c.SecurityEconomicEventLeg(
                leg_id="old-security",
                asset_kind=c.EconomicAssetKind.SECURITY,
                direction=c.EconomicLegDirection.DEBIT,
                security_id="600000.SH",
                quantity=1000,
            ),
            c.SecurityEconomicEventLeg(
                leg_id="new-security",
                asset_kind=c.EconomicAssetKind.SECURITY,
                direction=c.EconomicLegDirection.CREDIT,
                security_id="600001.SH",
                quantity=750,
            ),
        ),
        payload_content_hash=HASH,
    )
    assert len(event.legs) == 2
    assert event.effective_at < event.recorded_at

    with pytest.raises(ValidationError, match="leg"):
        c.EconomicEvent.model_validate(event.model_dump() | {"legs": ()})

    source_debit = event.legs[0]
    receivable_credit = c.ShareReceivableEconomicEventLeg(
        leg_id="replacement-receivable",
        asset_kind=c.EconomicAssetKind.SHARE_RECEIVABLE,
        direction=c.EconomicLegDirection.CREDIT,
        receivable_id="replacement-shares-001",
        security_id="600001.SH",
        quantity=750,
    )
    receivable_conversion = c.EconomicEvent.model_validate(
        event.model_dump()
        | {
            "economic_event_id": "event-receivable-conversion",
            "legs": (source_debit, receivable_credit),
        }
    )
    assert receivable_conversion.legs[1] == receivable_credit

    with pytest.raises(ValidationError, match="destination|double"):
        c.EconomicEvent.model_validate(
            event.model_dump()
            | {
                "economic_event_id": "event-double-destination",
                "legs": (source_debit, event.legs[1], receivable_credit),
            }
        )


def test_economic_event_leg_discriminator_prevents_ambiguous_dimensions() -> None:
    c = _contracts()
    with pytest.raises(ValidationError):
        c.CashEconomicEventLeg(
            leg_id="cash",
            asset_kind=c.EconomicAssetKind.CASH,
            direction=c.EconomicLegDirection.DEBIT,
            cash_amount=Decimal("-1.00"),
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        c.CashReceivableEconomicEventLeg.model_validate(
            {
                "leg_id": "dividend",
                "asset_kind": c.EconomicAssetKind.CASH_RECEIVABLE,
                "direction": c.EconomicLegDirection.CREDIT,
                "receivable_id": "receivable-001",
                "security_id": "600000.SH",
                "cash_amount": Decimal("10.00"),
                "quantity": 100,
            }
        )
    with pytest.raises(ValidationError):
        c.CostBasisEconomicEventLeg(
            leg_id="basis",
            asset_kind=c.EconomicAssetKind.COST_BASIS,
            direction=c.EconomicLegDirection.DEBIT,
            security_id="600000.SH",
            cost_basis_amount=Decimal("-0.01"),
        )


def test_valuation_and_late_correction_events_have_exact_semantics() -> None:
    c = _contracts()
    base = {
        "economic_event_id": "event-valuation",
        "portfolio_id": "paper-v3",
        "position_lineage_id": "position-001",
        "economic_lot_id": "lot-001",
        "mode": c.ExecutionMode.BROKER_CONFIRMED,
        "source_authority": "broker-confirmation",
        "effective_at": datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        "recorded_at": datetime(2026, 7, 19, 8, 1, tzinfo=UTC),
        "stream_version": 31,
        "correction_of_event_id": None,
        "payload_content_hash": HASH,
    }
    cash_leg = c.CashEconomicEventLeg(
        leg_id="cash",
        asset_kind=c.EconomicAssetKind.CASH,
        direction=c.EconomicLegDirection.CREDIT,
        cash_amount=Decimal("1.00"),
    )
    with pytest.raises(ValidationError, match="valuation"):
        c.EconomicEvent.model_validate(
            base | {"event_kind": c.EconomicEventKind.VALUATION, "legs": (cash_leg,)}
        )

    mark = c.ValuationMarkEconomicEventLeg(
        leg_id="mark",
        asset_kind=c.EconomicAssetKind.VALUATION_MARK,
        security_id="600000.SH",
        mark_price=Decimal("10.50"),
    )
    valuation = c.EconomicEvent.model_validate(
        base | {"event_kind": c.EconomicEventKind.VALUATION, "legs": (mark,)}
    )
    assert valuation.legs == (mark,)

    with pytest.raises(ValidationError, match="correction_of_event_id"):
        c.EconomicEvent.model_validate(
            base
            | {
                "event_kind": c.EconomicEventKind.LATE_CORRECTION,
                "legs": (cash_leg,),
            }
        )


def test_nonvaluation_event_kinds_reject_incompatible_economic_legs() -> None:
    c = _contracts()
    base = {
        "economic_event_id": "event-kind-check",
        "portfolio_id": "paper-v3",
        "position_lineage_id": "position-001",
        "economic_lot_id": "lot-001",
        "mode": c.ExecutionMode.BROKER_CONFIRMED,
        "source_authority": "broker-confirmation",
        "effective_at": datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        "recorded_at": datetime(2026, 7, 19, 8, 1, tzinfo=UTC),
        "stream_version": 32,
        "correction_of_event_id": None,
        "payload_content_hash": HASH,
    }
    security_leg = c.SecurityEconomicEventLeg(
        leg_id="shares",
        asset_kind=c.EconomicAssetKind.SECURITY,
        direction=c.EconomicLegDirection.DEBIT,
        security_id="600000.SH",
        quantity=100,
    )
    cash_credit = c.CashEconomicEventLeg(
        leg_id="cash-credit",
        asset_kind=c.EconomicAssetKind.CASH,
        direction=c.EconomicLegDirection.CREDIT,
        cash_amount=Decimal("1000.00"),
    )
    security_credit = c.SecurityEconomicEventLeg(
        leg_id="shares-credit",
        asset_kind=c.EconomicAssetKind.SECURITY,
        direction=c.EconomicLegDirection.CREDIT,
        security_id="600000.SH",
        quantity=100,
    )
    with pytest.raises(ValidationError, match="FEE_CHARGED"):
        c.EconomicEvent.model_validate(
            base
            | {
                "event_kind": c.EconomicEventKind.FEE_CHARGED,
                "legs": (security_leg,),
            }
        )
    with pytest.raises(ValidationError, match="TRADE_EXECUTED"):
        c.EconomicEvent.model_validate(
            base
            | {
                "event_kind": c.EconomicEventKind.TRADE_EXECUTED,
                "legs": (security_leg,),
            }
        )
    with pytest.raises(ValidationError, match="direction|conservation"):
        c.EconomicEvent.model_validate(
            base
            | {
                "event_kind": c.EconomicEventKind.TRADE_EXECUTED,
                "legs": (security_credit, cash_credit),
            }
        )
    with pytest.raises(ValidationError, match="direction|conservation"):
        c.EconomicEvent.model_validate(
            base
            | {
                "event_kind": c.EconomicEventKind.FEE_CHARGED,
                "legs": (cash_credit,),
            }
        )
    with pytest.raises(ValidationError, match="asset debit|conservation"):
        c.EconomicEvent.model_validate(
            base
            | {
                "event_kind": c.EconomicEventKind.CORPORATE_CASH_SETTLED,
                "legs": (cash_credit,),
            }
        )
    cost_debit = c.CostBasisEconomicEventLeg(
        leg_id="basis-debit",
        asset_kind=c.EconomicAssetKind.COST_BASIS,
        direction=c.EconomicLegDirection.DEBIT,
        security_id="600000.SH",
        cost_basis_amount=Decimal("1000.00"),
    )
    with pytest.raises(ValidationError, match="security debit|conservation"):
        c.EconomicEvent.model_validate(
            base
            | {
                "event_kind": c.EconomicEventKind.SECURITY_CONVERTED,
                "legs": (security_credit, cost_debit),
            }
        )
