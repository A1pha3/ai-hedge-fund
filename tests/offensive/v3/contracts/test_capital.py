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


def _risk_position(c, **overrides):
    payload = {
        "portfolio_id": "portfolio-v3",
        "broker_account_id": "broker-account-001",
        "mode": c.ExecutionMode.BROKER_CONFIRMED,
        "position_lineage_id": "position-001",
        "economic_lot_id": "lot-001",
        "security_id": "600000.SH",
        "producer_namespace": "daily-action.btst",
        "research_program_id": "program-btst",
        "economic_lineage_id": "lineage-btst",
        "stage_id": "stage-broker-2pct",
        "state": c.PositionState.OPEN,
        "settled_quantity": 100,
        "tradable_quantity": 80,
        "share_receivable_quantity": 20,
        "marked_gross_cents": 300_000,
    }
    payload.update(overrides)
    return c.CapitalPositionRisk(**payload)


def _live_order(c, **overrides):
    payload = {
        "portfolio_id": "portfolio-v3",
        "broker_account_id": "broker-account-001",
        "mode": c.ExecutionMode.BROKER_CONFIRMED,
        "order_id": "order-live-001",
        "order_line_id": "line-live-001",
        "side": c.RiskOrderSide.ENTRY,
        "state": c.OrderState.CANCEL_REQUESTED,
        "producer_namespace": "daily-action.btst",
        "research_program_id": "program-btst",
        "economic_lineage_id": "lineage-btst",
        "stage_id": "stage-broker-2pct",
        "leaves_quantity": 50,
        "worst_case_leaves_notional_cents": 100_000,
    }
    payload.update(overrides)
    return c.CapitalLiveOrderRisk(**payload)


def _exposure(c, scope, **overrides):
    identities = {
        "portfolio_id": "portfolio-v3",
        "research_program_id": None,
        "economic_lineage_id": None,
        "stage_id": None,
    }
    if scope is not c.ExposureScope.GLOBAL:
        identities["portfolio_id"] = "portfolio-v3"
    else:
        identities["portfolio_id"] = None
    if scope in {
        c.ExposureScope.RESEARCH_PROGRAM,
        c.ExposureScope.ECONOMIC_LINEAGE,
        c.ExposureScope.STAGE,
    }:
        identities["research_program_id"] = "program-btst"
    if scope in {c.ExposureScope.ECONOMIC_LINEAGE, c.ExposureScope.STAGE}:
        identities["economic_lineage_id"] = "lineage-btst"
    if scope is c.ExposureScope.STAGE:
        identities["stage_id"] = "stage-broker-2pct"
    unattributed_risk_cents = (
        5_000
        if scope
        in {
            c.ExposureScope.GLOBAL,
            c.ExposureScope.PORTFOLIO,
            c.ExposureScope.RESEARCH_PROGRAM,
        }
        else 0
    )
    payload = {
        "scope": scope,
        **identities,
        "position_marked_gross_cents": 300_000,
        "live_order_leaves_gross_cents": 100_000,
        "reserved_entry_gross_cents": 50_000,
        "pending_stress_cents": 20_000,
        "corporate_action_pending_risk_cents": 10_000,
        "unattributed_risk_cents": unattributed_risk_cents,
        "total_gross_cents": 480_000 + unattributed_risk_cents,
    }
    payload.update(overrides)
    return c.RiskExposureBucket(**payload)


def _stage_loss_latch(c, **overrides):
    payload = {
        "research_program_id": "program-btst",
        "economic_lineage_id": "lineage-btst",
        "stage_id": "stage-broker-2pct",
        "stage_loss_budget_id": "stage-loss-001",
        "frozen_budget_cents": 100_000,
        "consumed_cents": 10_000,
        "stage_loss_version": 7,
        "state": c.StageLossLatchState.CLEAR,
    }
    payload.update(overrides)
    return c.StageLossLatchSnapshot(**payload)


def _risk_snapshot_payload(c, **overrides):
    payload = {
        "risk_snapshot_id": "risk-snapshot-019",
        "portfolio_id": "portfolio-v3",
        "broker_account_id": "broker-account-001",
        "base_currency": "CNY",
        "mode": c.ExecutionMode.BROKER_CONFIRMED,
        "as_of": datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        "valid_until": datetime(2026, 7, 19, 8, 5, tzinfo=UTC),
        "freshness": c.RiskSnapshotFreshness.FRESH,
        "completeness": c.RiskSnapshotCompleteness.COMPLETE,
        "available_cash_cents": 400_000,
        "restricted_cash_cents": 10_000,
        "unsettled_cash_cents": 20_000,
        "cash_receivable_cents": 30_000,
        "cash_payable_cents": 5_000,
        "subscription_suspense_cents": 4_000,
        "redemption_suspense_cents": 3_000,
        "reserved_cash_cents": 50_000,
        "issued_unit_quanta": 1_000_000,
        "pending_redeemed_unit_quanta": 10_000,
        "positions": (_risk_position(c),),
        "live_orders": (_live_order(c),),
        "pending_stress_cents": 20_000,
        "corporate_action_pending_risk_cents": 10_000,
        "unattributed_risk_cents": 5_000,
        "exposures": tuple(_exposure(c, scope) for scope in c.ExposureScope),
        "total_gross_exposure_cents": 485_000,
        "as_observed_nav_cents": 950_000,
        "lifetime_high_water_mark_cents": 1_000_000,
        "active_epoch_high_water_mark_cents": 1_000_000,
        "lifetime_drawdown_ppm": 50_000,
        "active_epoch_drawdown_ppm": 50_000,
        "risk_latch": c.RiskLatchState.CLEAR,
        "stage_loss_latches": (_stage_loss_latch(c),),
        "reconciliation_latch": c.ReconciliationLatchState.RECONCILIATION_HALT,
        "policy_activation_hash": HASH,
        "policy_epoch": 4,
        "authority_epoch": 5,
        "risk_epoch": 6,
        "registry_epoch": 7,
        "authorization_id": "authorization-001",
        "authorization_version": 8,
        "stage_loss_version": 7,
        "writer_fencing_epoch": 9,
        "capital_version": 10,
        "payload_content_hash": HASH,
        "schema_major": 2,
    }
    payload.update(overrides)
    return payload


def test_capital_risk_snapshot_contract_has_exact_schema_and_typed_statuses() -> None:
    c = _contracts()
    assert [value.value for value in c.RiskSnapshotFreshness] == [
        "FRESH",
        "STALE",
        "UNKNOWN",
    ]
    assert [value.value for value in c.RiskSnapshotCompleteness] == [
        "COMPLETE",
        "INCOMPLETE",
        "UNKNOWN",
    ]
    assert [value.value for value in c.ExposureScope] == [
        "GLOBAL",
        "PORTFOLIO",
        "RESEARCH_PROGRAM",
        "ECONOMIC_LINEAGE",
        "STAGE",
    ]
    assert [value.value for value in c.RiskOrderSide] == ["ENTRY", "EXIT"]
    assert [value.value for value in c.RiskLatchState] == ["CLEAR", "RISK_HALTED"]
    assert [value.value for value in c.StageLossLatchState] == [
        "CLEAR",
        "STAGE_LOSS_HALTED",
    ]
    assert [value.value for value in c.ReconciliationLatchState] == [
        "CLEAR",
        "RECONCILIATION_HALT",
    ]
    assert set(c.CapitalPositionRisk.model_fields) == {
        "portfolio_id",
        "broker_account_id",
        "mode",
        "position_lineage_id",
        "economic_lot_id",
        "security_id",
        "producer_namespace",
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "state",
        "settled_quantity",
        "tradable_quantity",
        "share_receivable_quantity",
        "marked_gross_cents",
    }
    assert set(c.CapitalLiveOrderRisk.model_fields) == {
        "portfolio_id",
        "broker_account_id",
        "mode",
        "order_id",
        "order_line_id",
        "side",
        "state",
        "producer_namespace",
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "leaves_quantity",
        "worst_case_leaves_notional_cents",
    }
    assert set(c.RiskExposureBucket.model_fields) == {
        "scope",
        "portfolio_id",
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "position_marked_gross_cents",
        "live_order_leaves_gross_cents",
        "reserved_entry_gross_cents",
        "pending_stress_cents",
        "corporate_action_pending_risk_cents",
        "unattributed_risk_cents",
        "total_gross_cents",
    }
    assert set(c.StageLossLatchSnapshot.model_fields) == {
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "stage_loss_budget_id",
        "frozen_budget_cents",
        "consumed_cents",
        "stage_loss_version",
        "state",
    }
    assert set(c.CapitalRiskSnapshot.model_fields) == {
        "risk_snapshot_id",
        "portfolio_id",
        "broker_account_id",
        "base_currency",
        "mode",
        "as_of",
        "valid_until",
        "freshness",
        "completeness",
        "available_cash_cents",
        "restricted_cash_cents",
        "unsettled_cash_cents",
        "cash_receivable_cents",
        "cash_payable_cents",
        "subscription_suspense_cents",
        "redemption_suspense_cents",
        "reserved_cash_cents",
        "issued_unit_quanta",
        "pending_redeemed_unit_quanta",
        "positions",
        "live_orders",
        "pending_stress_cents",
        "corporate_action_pending_risk_cents",
        "unattributed_risk_cents",
        "exposures",
        "total_gross_exposure_cents",
        "as_observed_nav_cents",
        "lifetime_high_water_mark_cents",
        "active_epoch_high_water_mark_cents",
        "lifetime_drawdown_ppm",
        "active_epoch_drawdown_ppm",
        "risk_latch",
        "stage_loss_latches",
        "reconciliation_latch",
        "policy_activation_hash",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "registry_epoch",
        "authorization_id",
        "authorization_version",
        "stage_loss_version",
        "writer_fencing_epoch",
        "capital_version",
        "payload_content_hash",
        "schema_major",
    }


def test_complete_risk_snapshot_is_frozen_and_exact() -> None:
    c = _contracts()
    snapshot = c.CapitalRiskSnapshot(**_risk_snapshot_payload(c))
    assert snapshot.positions[0].tradable_quantity == 80
    assert snapshot.live_orders[0].leaves_quantity == 50
    assert snapshot.issued_unit_quanta == 1_000_000
    assert snapshot.total_gross_exposure_cents == 485_000
    with pytest.raises(ValidationError, match="frozen_instance"):
        snapshot.capital_version = 11


@pytest.mark.parametrize("bad", [True, 100.0, Decimal("100")])
@pytest.mark.parametrize(
    "dimension",
    ["money", "shares", "unit_quanta", "version", "drawdown"],
)
def test_capital_risk_snapshot_rejects_bool_float_and_decimal_integer_laundering(
    bad, dimension
) -> None:
    c = _contracts()
    payload = _risk_snapshot_payload(c)
    if dimension == "money":
        payload["available_cash_cents"] = bad
    elif dimension == "shares":
        position = _risk_position(c).model_dump(mode="python")
        position["settled_quantity"] = bad
        payload["positions"] = (position,)
    elif dimension == "unit_quanta":
        payload["issued_unit_quanta"] = bad
    elif dimension == "version":
        payload["capital_version"] = bad
    else:
        payload["active_epoch_drawdown_ppm"] = bad
    with pytest.raises(ValidationError, match="integer|int"):
        c.CapitalRiskSnapshot(**payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": "research_reconstruction", "broker_account_id": None},
        {"mode": "daily_bar_proxy", "broker_account_id": "broker-account-001"},
        {"mode": "manual_confirmed", "broker_account_id": None},
        {"mode": "broker_confirmed", "broker_account_id": None},
    ],
)
def test_capital_risk_snapshot_rejects_mode_account_mismatches(overrides) -> None:
    c = _contracts()
    with pytest.raises(ValidationError, match="mode|account|research"):
        c.CapitalRiskSnapshot(**_risk_snapshot_payload(c, **overrides))


@pytest.mark.parametrize(
    "component",
    [
        lambda c: {"positions": (_risk_position(c, portfolio_id="other"),)},
        lambda c: {"positions": (_risk_position(c, broker_account_id="other"),)},
        lambda c: {"live_orders": (_live_order(c, portfolio_id="other"),)},
        lambda c: {"live_orders": (_live_order(c, broker_account_id="other"),)},
    ],
)
def test_capital_risk_snapshot_rejects_cross_portfolio_or_account_components(
    component,
) -> None:
    c = _contracts()
    with pytest.raises(ValidationError, match="portfolio|account"):
        c.CapitalRiskSnapshot(**_risk_snapshot_payload(c, **component(c)))


def test_account_snapshot_keeps_mixed_execution_provenance() -> None:
    c = _contracts()
    manual_position = _risk_position(c, mode=c.ExecutionMode.MANUAL_CONFIRMED)
    snapshot = c.CapitalRiskSnapshot(
        **_risk_snapshot_payload(c, positions=(manual_position,))
    )
    assert snapshot.positions[0].mode is c.ExecutionMode.MANUAL_CONFIRMED
    assert snapshot.mode is c.ExecutionMode.BROKER_CONFIRMED


def test_position_risk_rejects_bad_state_or_account_mode() -> None:
    c = _contracts()
    for changes in (
        {"state": c.PositionState.CLOSED},
        {"state": c.PositionState.LEGAL_TERMINAL},
        {"tradable_quantity": 101},
        {"settled_quantity": -1},
        {"mode": c.ExecutionMode.DAILY_BAR_PROXY},
        {"mode": c.ExecutionMode.BROKER_CONFIRMED, "broker_account_id": None},
    ):
        with pytest.raises(
            ValidationError, match="state|tradable|quantity|mode|account"
        ):
            _risk_position(c, **changes)


@pytest.mark.parametrize("state", ["SUBMITTED", "PARTIALLY_FILLED", "CANCEL_REQUESTED"])
def test_capital_live_order_risk_counts_every_live_leaves_state(state) -> None:
    c = _contracts()
    order = _live_order(c, state=c.OrderState(state))
    assert order.leaves_quantity == 50


@pytest.mark.parametrize(
    "state",
    ["CREATED", "FILLED", "REJECTED", "CANCELLED", "EXPIRED"],
)
def test_capital_live_order_risk_rejects_nonlive_order_states(state) -> None:
    c = _contracts()
    with pytest.raises(ValidationError, match="live|state"):
        _live_order(c, state=c.OrderState(state))


def test_capital_risk_snapshot_rejects_unknown_or_incomplete_facts() -> None:
    c = _contracts()
    position = _risk_position(c).model_dump(mode="python")
    position["tradable_quantity"] = "UNKNOWN"
    for changes in (
        {"freshness": c.RiskSnapshotFreshness.UNKNOWN},
        {"completeness": c.RiskSnapshotCompleteness.UNKNOWN},
        {"completeness": c.RiskSnapshotCompleteness.INCOMPLETE},
        {"positions": (position,)},
    ):
        with pytest.raises(ValidationError, match="unknown|complete|integer"):
            c.CapitalRiskSnapshot(**_risk_snapshot_payload(c, **changes))

    missing = _risk_snapshot_payload(c)
    missing.pop("cash_receivable_cents")
    with pytest.raises(ValidationError, match="cash_receivable_cents|Field required"):
        c.CapitalRiskSnapshot(**missing)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        c.CapitalRiskSnapshot(**(_risk_snapshot_payload(c) | {"unknown_risk_cents": 1}))


def test_risk_snapshot_rejects_double_counted_aggregates() -> None:
    c = _contracts()
    invalid = (
        {"total_gross_exposure_cents": 485_001},
        {"positions": (_risk_position(c), _risk_position(c))},
        {"live_orders": (_live_order(c), _live_order(c))},
    )
    for changes in invalid:
        with pytest.raises(
            ValidationError, match="aggregate|duplicate|gross|position|order"
        ):
            c.CapitalRiskSnapshot(**_risk_snapshot_payload(c, **changes))


def test_capital_risk_snapshot_requires_one_complete_exposure_hierarchy() -> None:
    c = _contracts()
    valid = _risk_snapshot_payload(c)["exposures"]
    inconsistent_stage = valid[-1].model_dump(mode="python")
    inconsistent_stage["total_gross_cents"] = 480_001
    invalid_exposure_sets = (
        valid[1:],
        valid + (valid[-1],),
        valid[:-1],
        valid[:-1] + (inconsistent_stage,),
    )
    for exposures in invalid_exposure_sets:
        with pytest.raises(ValidationError, match="exposure|scope|duplicate|aggregate"):
            c.CapitalRiskSnapshot(**_risk_snapshot_payload(c, exposures=exposures))


def test_risk_snapshot_rejects_nav_latch_inconsistency() -> None:
    c = _contracts()
    invalid = (
        {"as_observed_nav_cents": 1_000_001},
        {"active_epoch_drawdown_ppm": 49_999},
        {"stage_loss_latches": (_stage_loss_latch(c, stage_loss_version=8),)},
        {"stage_loss_latches": (_stage_loss_latch(c), _stage_loss_latch(c))},
        {"reconciliation_latch": c.ReconciliationLatchState.CLEAR},
        {
            "as_observed_nav_cents": 850_000,
            "lifetime_drawdown_ppm": 150_000,
            "active_epoch_drawdown_ppm": 150_000,
            "risk_latch": c.RiskLatchState.CLEAR,
        },
    )
    for changes in invalid:
        with pytest.raises(
            ValidationError, match="NAV|drawdown|stage|duplicate|version"
        ):
            c.CapitalRiskSnapshot(**_risk_snapshot_payload(c, **changes))


def test_stage_loss_latch_state_matches_nonreplenishable_consumption() -> None:
    c = _contracts()
    halted = _stage_loss_latch(
        c,
        consumed_cents=125_000,
        state=c.StageLossLatchState.STAGE_LOSS_HALTED,
    )
    assert halted.consumed_cents > halted.frozen_budget_cents
    for changes in (
        {"consumed_cents": 100_000, "state": c.StageLossLatchState.CLEAR},
        {
            "consumed_cents": 99_999,
            "state": c.StageLossLatchState.STAGE_LOSS_HALTED,
        },
    ):
        with pytest.raises(ValidationError, match="stage|budget|halt|consumed"):
            _stage_loss_latch(c, **changes)


def _exit_mandate_payload(c, **overrides):
    payload = {
        "exit_mandate_id": "exit-mandate-001",
        "portfolio_id": "portfolio-v3",
        "broker_account_id": "broker-account-001",
        "base_currency": "CNY",
        "mode": c.ExecutionMode.BROKER_CONFIRMED,
        "position_lineage_id": "position-001",
        "economic_lot_id": "lot-001",
        "security_id": "600000.SH",
        "producer_namespace": "daily-action.btst",
        "research_program_id": "program-btst",
        "economic_lineage_id": "lineage-btst",
        "stage_id": "stage-broker-2pct",
        "entry_plan_evidence_hash": HASH,
        "fixed_exit_policy_fingerprint": HASH,
        "exit_session_ordinal": 10,
        "due_session": date(2026, 7, 30),
        "tradable_quantity": 100,
        "live_exit_leaves_quantity": 40,
        "executable_quantity": 60,
        "capital_version": 10,
        "writer_fencing_epoch": 9,
        "stable_client_order_id": "exit-client-portfolio-v3-lot-001-10",
        "issued_at": datetime(2026, 7, 29, 8, 0, tzinfo=UTC),
        "source_risk_snapshot_id": "risk-snapshot-019",
        "source_risk_snapshot_hash": HASH,
        "schema_major": 2,
    }
    payload.update(overrides)
    return payload


def test_exit_mandate_has_exact_independent_schema_and_hash() -> None:
    c = _contracts()
    expected_fields = {
        "exit_mandate_id",
        "portfolio_id",
        "broker_account_id",
        "base_currency",
        "mode",
        "position_lineage_id",
        "economic_lot_id",
        "security_id",
        "producer_namespace",
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "entry_plan_evidence_hash",
        "fixed_exit_policy_fingerprint",
        "exit_session_ordinal",
        "due_session",
        "tradable_quantity",
        "live_exit_leaves_quantity",
        "executable_quantity",
        "capital_version",
        "writer_fencing_epoch",
        "stable_client_order_id",
        "issued_at",
        "source_risk_snapshot_id",
        "source_risk_snapshot_hash",
        "schema_major",
    }
    assert set(c.ExitMandate.model_fields) == expected_fields
    assert not expected_fields & {
        "authorization_id",
        "authorization_version",
        "capital_authorization_id",
        "capital_authorization_envelope",
        "edge_authorization_id",
        "execution_permit_nonce",
    }
    mandate = c.ExitMandate(**_exit_mandate_payload(c))
    assert mandate.executable_quantity == 60
    assert mandate.artifact_hash() == mandate.artifact_hash()
    changed = c.ExitMandate(
        **_exit_mandate_payload(c, stable_client_order_id="exit-client-changed")
    )
    assert mandate.artifact_hash() != changed.artifact_hash()


@pytest.mark.parametrize(
    "changes",
    [
        {"tradable_quantity": "UNKNOWN"},
        {
            "tradable_quantity": 0,
            "live_exit_leaves_quantity": 0,
            "executable_quantity": 0,
        },
        {
            "tradable_quantity": 100,
            "live_exit_leaves_quantity": 101,
            "executable_quantity": 1,
        },
        {
            "tradable_quantity": 100,
            "live_exit_leaves_quantity": 40,
            "executable_quantity": 61,
        },
        {
            "tradable_quantity": -1,
            "live_exit_leaves_quantity": 0,
            "executable_quantity": 1,
        },
        {"live_exit_leaves_quantity": -1},
        {"executable_quantity": -1},
    ],
)
def test_exit_mandate_rejects_unknown_untradable_oversell_and_negative_quantity(
    changes,
) -> None:
    c = _contracts()
    with pytest.raises(ValidationError, match="quantity|tradable|integer|oversell"):
        c.ExitMandate(**_exit_mandate_payload(c, **changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "research_reconstruction", "broker_account_id": None},
        {"mode": "daily_bar_proxy", "broker_account_id": "broker-account-001"},
        {"mode": "manual_confirmed", "broker_account_id": None},
        {"mode": "broker_confirmed", "broker_account_id": None},
    ],
)
def test_exit_mandate_rejects_mode_account_mismatch(changes) -> None:
    c = _contracts()
    with pytest.raises(ValidationError, match="mode|account|research"):
        c.ExitMandate(**_exit_mandate_payload(c, **changes))


@pytest.mark.parametrize("bad", [True, 60.0, Decimal("60")])
def test_exit_mandate_rejects_non_native_integer_quantity(bad) -> None:
    c = _contracts()
    with pytest.raises(ValidationError, match="integer|int"):
        c.ExitMandate(**_exit_mandate_payload(c, executable_quantity=bad))
