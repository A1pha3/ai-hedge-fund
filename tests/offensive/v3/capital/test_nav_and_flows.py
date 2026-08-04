"""Unit NAV, external flows, account lifecycle, and insolvency semantics.

Plan 02 Task 3: one-time genesis units, flow-before-price subscriptions and
redemptions with suspense cash handling, partial/full redemption with
``pending_redeemed_units``, the ``ACTIVE -> TERMINATING -> TERMINATED``
lifecycle with cancellation rules, lifetime/active-epoch high-water marks,
``RiskEpochStarted`` semantics (active baseline reset, lifetime history
preserved), as-observed vs restated-final NAV projections with append-only
restatement links, and confirmed NAV <= 0 setting ``INSOLVENT`` with the
typed ``NEGATIVE_INFINITY`` log-growth sentinel (never a persisted float).

Exact unit accounting: deposits/redemptions at the pricing instant leave the
unit price (and therefore the unit return) unchanged, and the Task 2
conservation identity balances with nonzero opening capital and external
flows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalConflict,
    CapitalRepository,
)
from src.screening.offensive.v3.capital.fills import (
    FillAttribution,
    FillRevisionRequest,
)
from src.screening.offensive.v3.capital.flows import (
    FlowCancelRequest,
    FlowPriceRequest,
    FlowRequestState,
    FlowSettleRequest,
    GenesisRequest,
    LifecycleState,
    RedemptionPaymentRequest,
    RedemptionRequest,
    RiskEpochRequest,
    SubscriptionRequest,
)
from src.screening.offensive.v3.capital.nav import (
    LogGrowthKind,
    ObservationKind,
    RestatementRequest,
    ValuationMarkInput,
    ValuationRequest,
)
from src.screening.offensive.v3.capital.reserves import ReserveEntryRequest
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    ExecutionSide,
    PositionState,
    RiskLatchState,
)


T0 = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
ENVIRONMENT_FINGERPRINT = "ab" * 32

# Genesis terms used across the tests: 10_000 units at 10.00 currency units
# each (1_000 cents per unit quanta) = 10_000_000 cents of seed capital.
GENESIS_UNITS = 10_000
GENESIS_PRICE_NUMERATOR = 1_000
GENESIS_PRICE_DENOMINATOR = 1
GENESIS_CASH_CENTS = GENESIS_UNITS * GENESIS_PRICE_NUMERATOR

ATTRIBUTION = FillAttribution(
    producer_namespace="btst",
    research_program_id="prog-1",
    economic_lineage_id="eline-1",
    stage_id="stage-1",
)


def binding() -> AccountBinding:
    return AccountBinding(
        portfolio_id="pf-test",
        mode=ExecutionMode.MANUAL_CONFIRMED,
        broker_account_id="acct-test",
        base_currency="CNY",
        environment_fingerprint=ENVIRONMENT_FINGERPRINT,
    )


def _moment(step: int) -> datetime:
    return T0 + timedelta(minutes=step)


@pytest.fixture()
def repository(tmp_path: Path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "capital.sqlite3")


def genesis(
    repository: CapitalRepository, *, step: int = 0, key: str = "genesis-1"
) -> object:
    return repository.initialize_genesis(
        GenesisRequest(
            idempotency_key=key,
            account_binding=binding(),
            unit_quanta=GENESIS_UNITS,
            unit_price_numerator=GENESIS_PRICE_NUMERATOR,
            unit_price_denominator=GENESIS_PRICE_DENOMINATOR,
            source_authority="governance.test",
            authorization_reference="gov-genesis-1",
            effective_at=_moment(step),
            as_of=_moment(step),
        )
    )


def valuation(
    repository: CapitalRepository,
    *,
    step: int,
    marks: dict[str, int],
    key: str | None = None,
) -> object:
    request = ValuationRequest(
        idempotency_key=key or f"valuation-{step}",
        source_authority="valuation.test",
        effective_at=_moment(step),
        as_of=_moment(step),
        expected_stream_version=repository.stream_version(),
        marks=tuple(
            ValuationMarkInput(security_id=security_id, price_micros=price_micros)
            for security_id, price_micros in sorted(marks.items())
        ),
    )
    return repository.close_valuation(request)


def entry_fill(
    repository: CapitalRepository,
    *,
    step: int,
    execution_id: str = "exec-entry-1",
    security_id: str = "600000.SH",
    price_micros: int = 100_000_000,
    quantity: int = 1_000,
    order_id: str = "ord-entry-1",
) -> object:
    request = FillRevisionRequest(
        execution_id=execution_id,
        revision=1,
        order_id=order_id,
        side=ExecutionSide.ENTRY,
        security_id=security_id,
        price_micros=price_micros,
        quantity=quantity,
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        attribution=ATTRIBUTION,
        source_authority="broker.test",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
    )
    return repository.record_fill_revision(request)


def exit_fill(
    repository: CapitalRepository,
    *,
    step: int,
    execution_id: str = "exec-exit-1",
    security_id: str = "600000.SH",
    price_micros: int = 100_000_000,
    quantity: int = 1_000,
    order_id: str = "ord-exit-1",
    position_lineage_id: str = "lin-1",
    economic_lot_id: str = "lot-1",
) -> object:
    request = FillRevisionRequest(
        execution_id=execution_id,
        revision=1,
        order_id=order_id,
        side=ExecutionSide.EXIT,
        security_id=security_id,
        price_micros=price_micros,
        quantity=quantity,
        position_lineage_id=position_lineage_id,
        economic_lot_id=economic_lot_id,
        attribution=ATTRIBUTION,
        source_authority="broker.test",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
    )
    return repository.record_fill_revision(request)


def subscribe(
    repository: CapitalRepository,
    *,
    request_id: str,
    cents: int,
    step: int,
) -> None:
    repository.request_subscription(
        SubscriptionRequest(
            request_id=request_id,
            cash_amount_cents=cents,
            source_authority="flows.test",
            effective_at=_moment(step),
            as_of=_moment(step),
            expected_flow_version=repository.flow_version(),
        )
    )
    repository.settle_subscription(
        FlowSettleRequest(
            request_id=request_id,
            source_authority="flows.test",
            as_of=_moment(step) + timedelta(seconds=30),
            expected_flow_version=repository.flow_version(),
        )
    )


def redeem(
    repository: CapitalRepository,
    *,
    request_id: str,
    units: int,
    step: int,
) -> None:
    repository.request_redemption(
        RedemptionRequest(
            request_id=request_id,
            unit_quanta=units,
            source_authority="flows.test",
            as_of=_moment(step),
        )
    )
    repository.settle_redemption(
        FlowSettleRequest(
            request_id=request_id,
            source_authority="flows.test",
            as_of=_moment(step) + timedelta(seconds=30),
            expected_flow_version=repository.flow_version(),
        )
    )
    repository.pay_redemption(
        RedemptionPaymentRequest(
            request_id=request_id,
            source_authority="flows.test",
            as_of=_moment(step) + timedelta(seconds=60),
            expected_flow_version=repository.flow_version(),
        )
    )


def unit_price_of(repository: CapitalRepository) -> tuple[int, int]:
    path = repository.nav_projections()
    latest = path.as_observed[-1]
    assert latest.unit_price_numerator is not None
    assert latest.unit_price_denominator is not None
    return (latest.unit_price_numerator, latest.unit_price_denominator)


# ---------------------------------------------------------------------------
# Genesis
# ---------------------------------------------------------------------------


def test_genesis_issues_explicit_units_and_seeds_nav_hwm(
    repository: CapitalRepository,
) -> None:
    receipt, snapshot = genesis(repository)

    assert snapshot.available_cash_cents == GENESIS_CASH_CENTS
    assert snapshot.issued_unit_quanta == GENESIS_UNITS
    assert snapshot.pending_redeemed_unit_quanta == 0
    assert snapshot.as_observed_nav_cents == GENESIS_CASH_CENTS
    assert snapshot.lifetime_high_water_mark_cents == GENESIS_CASH_CENTS
    assert snapshot.active_epoch_high_water_mark_cents == GENESIS_CASH_CENTS
    assert snapshot.subscription_suspense_cents == 0
    assert snapshot.redemption_suspense_cents == 0
    assert receipt.cash_amount_cents == GENESIS_CASH_CENTS
    assert receipt.unit_quanta == GENESIS_UNITS
    assert receipt.unit_price_numerator == GENESIS_PRICE_NUMERATOR
    assert receipt.unit_price_denominator == GENESIS_PRICE_DENOMINATOR
    assert repository.lifecycle_state() is LifecycleState.ACTIVE

    path = repository.nav_projections()
    assert len(path.as_observed) == 1
    first = path.as_observed[0]
    assert first.observation_kind is ObservationKind.AS_OBSERVED
    assert first.nav_cents == GENESIS_CASH_CENTS
    assert first.live_unit_quanta == GENESIS_UNITS
    assert first.unit_price_numerator == GENESIS_PRICE_NUMERATOR
    assert first.unit_price_denominator == GENESIS_PRICE_DENOMINATOR
    assert first.log_growth_kind is LogGrowthKind.NO_PRIOR_OBSERVATION

    report = repository.assert_conservation()
    assert report.opening_capital_cents == GENESIS_CASH_CENTS
    assert report.external_flow_cents == 0


def test_genesis_is_one_time(repository: CapitalRepository) -> None:
    genesis(repository)
    with pytest.raises(CapitalConflict) as excinfo:
        genesis(repository, key="genesis-2")
    assert excinfo.value.code == "genesis_already_committed"


def test_genesis_price_must_divide_to_exact_cents(tmp_path: Path) -> None:
    repository = CapitalRepository.initialize(tmp_path / "capital.sqlite3")
    with pytest.raises(CapitalConflict) as excinfo:
        repository.initialize_genesis(
            GenesisRequest(
                idempotency_key="genesis-bad",
                account_binding=binding(),
                unit_quanta=10,
                unit_price_numerator=1,
                unit_price_denominator=3,
                source_authority="governance.test",
                effective_at=T0,
                as_of=T0,
            )
        )
    assert excinfo.value.code == "genesis_price_not_exact_cents"


def test_genesis_idempotent_retry_converges(repository: CapitalRepository) -> None:
    receipt, snapshot = genesis(repository)
    retry_receipt, retry_snapshot = genesis(repository)
    assert retry_receipt.flow_event_id == receipt.flow_event_id
    assert retry_snapshot.capital_version == snapshot.capital_version
    # Financing flows never touch the economic event stream.
    assert repository.stream_version() == 0


def test_genesis_rejects_nonpositive_terms(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        GenesisRequest(
            idempotency_key="genesis-bad",
            unit_quanta=0,
            unit_price_numerator=1,
            unit_price_denominator=1,
            source_authority="governance.test",
            effective_at=T0,
            as_of=T0,
        )
    with pytest.raises(ValidationError):
        GenesisRequest(
            idempotency_key="genesis-bad",
            unit_quanta=1,
            unit_price_numerator=1,
            unit_price_denominator=0,
            source_authority="governance.test",
            effective_at=T0,
            as_of=T0,
        )


# ---------------------------------------------------------------------------
# Subscriptions: flow-before-price, suspense cash, exact unit accounting
# ---------------------------------------------------------------------------


def test_subscription_flow_before_price_ordering(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.price_subscription(
            FlowPriceRequest(
                request_id="sub-1",
                source_authority="flows.test",
                as_of=_moment(1),
            )
        )
    assert excinfo.value.code == "flow_request_unknown"
    with pytest.raises(CapitalConflict) as excinfo:
        repository.settle_subscription(
            FlowSettleRequest(
                request_id="sub-1",
                source_authority="flows.test",
                as_of=_moment(1),
                expected_flow_version=repository.flow_version(),
            )
        )
    assert excinfo.value.code == "flow_request_unknown"


def test_subscription_cash_lands_in_suspense_with_payable(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    capital_version_before = repository.capital_version()
    receipt, snapshot = repository.request_subscription(
        SubscriptionRequest(
            request_id="sub-1",
            cash_amount_cents=5_000_000,
            source_authority="flows.test",
            effective_at=_moment(1),
            as_of=_moment(1),
            expected_flow_version=repository.flow_version(),
        )
    )

    assert receipt.payable_id is not None
    # The cash is restricted suspense cash; net equity and units are unchanged.
    assert snapshot.subscription_suspense_cents == 5_000_000
    assert snapshot.cash_payable_cents == 5_000_000
    assert snapshot.issued_unit_quanta == GENESIS_UNITS
    assert snapshot.as_observed_nav_cents == GENESIS_CASH_CENTS
    assert snapshot.capital_version == capital_version_before + 1
    repository.assert_conservation()


def test_price_subscription_freezes_pre_flow_price(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    repository.request_subscription(
        SubscriptionRequest(
            request_id="sub-1",
            cash_amount_cents=5_000_000,
            source_authority="flows.test",
            effective_at=_moment(1),
            as_of=_moment(1),
            expected_flow_version=repository.flow_version(),
        )
    )
    price = repository.price_subscription(
        FlowPriceRequest(
            request_id="sub-1",
            source_authority="flows.test",
            as_of=_moment(2),
        )
    )
    # V_pre excludes this flow's suspense cash; the price is the pre-flow price.
    assert price.v_pre_cents == GENESIS_CASH_CENTS
    assert price.units_pre_quanta == GENESIS_UNITS
    assert price.unit_price_numerator == GENESIS_PRICE_NUMERATOR
    assert price.unit_price_denominator == GENESIS_PRICE_DENOMINATOR
    assert price.cash_amount_cents == 5_000_000


def test_settle_subscription_at_frozen_price_releases_suspense(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    repository.request_subscription(
        SubscriptionRequest(
            request_id="sub-1",
            cash_amount_cents=5_000_000,
            source_authority="flows.test",
            effective_at=_moment(1),
            as_of=_moment(1),
            expected_flow_version=repository.flow_version(),
        )
    )
    repository.price_subscription(
        FlowPriceRequest(
            request_id="sub-1",
            source_authority="flows.test",
            as_of=_moment(2),
        )
    )
    receipt, snapshot = repository.settle_subscription(
        FlowSettleRequest(
            request_id="sub-1",
            source_authority="flows.test",
            as_of=_moment(3),
            expected_flow_version=repository.flow_version(),
        )
    )

    assert receipt.issued_unit_quanta == 5_000
    assert snapshot.subscription_suspense_cents == 0
    assert snapshot.cash_payable_cents == 0
    assert snapshot.available_cash_cents == GENESIS_CASH_CENTS + 5_000_000
    assert snapshot.issued_unit_quanta == GENESIS_UNITS + 5_000
    assert snapshot.as_observed_nav_cents == GENESIS_CASH_CENTS + 5_000_000
    repository.assert_conservation()


def test_settle_subscription_without_price_prices_atomically(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    repository.request_subscription(
        SubscriptionRequest(
            request_id="sub-1",
            cash_amount_cents=5_000_000,
            source_authority="flows.test",
            effective_at=_moment(1),
            as_of=_moment(1),
            expected_flow_version=repository.flow_version(),
        )
    )
    receipt, snapshot = repository.settle_subscription(
        FlowSettleRequest(
            request_id="sub-1",
            source_authority="flows.test",
            as_of=_moment(2),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert receipt.issued_unit_quanta == 5_000
    assert receipt.unit_price_numerator == GENESIS_PRICE_NUMERATOR
    assert receipt.unit_price_denominator == GENESIS_PRICE_DENOMINATOR
    assert snapshot.issued_unit_quanta == GENESIS_UNITS + 5_000
    repository.assert_conservation()


def test_subscription_deposit_leaves_unit_return_unchanged(
    repository: CapitalRepository,
) -> None:
    """The classic flow-invariance property at the pricing instant."""

    genesis(repository)
    valuation(repository, step=1, marks={})
    price_before = unit_price_of(repository)

    subscribe(repository, request_id="sub-1", cents=5_000_000, step=2)
    valuation(repository, step=4, marks={})
    price_after = unit_price_of(repository)

    assert price_before == price_after == (GENESIS_PRICE_NUMERATOR, 1)


def test_subscription_residual_is_refunded_not_overissued(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    # 1_500 cents at 1_000 cents/unit buys exactly 1 unit; the residual 500
    # cents are refunded rather than over-issuing fractional unit quanta.
    repository.request_subscription(
        SubscriptionRequest(
            request_id="sub-1",
            cash_amount_cents=1_500,
            source_authority="flows.test",
            effective_at=_moment(1),
            as_of=_moment(1),
            expected_flow_version=repository.flow_version(),
        )
    )
    settle_receipt, settled = repository.settle_subscription(
        FlowSettleRequest(
            request_id="sub-1",
            source_authority="flows.test",
            as_of=_moment(2),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert settle_receipt.issued_unit_quanta == 1
    assert settle_receipt.refund_cents == 500
    assert settled.subscription_suspense_cents == 0
    assert settled.cash_payable_cents == 0
    assert settled.available_cash_cents == GENESIS_CASH_CENTS + 1_000
    assert settled.issued_unit_quanta == GENESIS_UNITS + 1
    repository.assert_conservation()


def test_stale_frozen_subscription_price_fails_closed(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    repository.request_subscription(
        SubscriptionRequest(
            request_id="sub-1",
            cash_amount_cents=5_000_000,
            source_authority="flows.test",
            effective_at=_moment(1),
            as_of=_moment(1),
            expected_flow_version=repository.flow_version(),
        )
    )
    repository.price_subscription(
        FlowPriceRequest(
            request_id="sub-1",
            source_authority="flows.test",
            as_of=_moment(2),
        )
    )
    # A confirmed valuation advances the capital version: the frozen price is
    # stale and settle must fail closed instead of issuing at an old price.
    valuation(repository, step=3, marks={})
    with pytest.raises(CapitalConflict) as excinfo:
        repository.settle_subscription(
            FlowSettleRequest(
                request_id="sub-1",
                source_authority="flows.test",
                as_of=_moment(4),
                expected_flow_version=repository.flow_version(),
            )
        )
    assert excinfo.value.code == "flow_price_stale"

    # Re-pricing refreshes the freeze and settle then succeeds.
    repository.price_subscription(
        FlowPriceRequest(
            request_id="sub-1",
            source_authority="flows.test",
            as_of=_moment(5),
        )
    )
    receipt, snapshot = repository.settle_subscription(
        FlowSettleRequest(
            request_id="sub-1",
            source_authority="flows.test",
            as_of=_moment(6),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert receipt.issued_unit_quanta == 5_000
    assert snapshot.issued_unit_quanta == GENESIS_UNITS + 5_000


def test_subscription_requires_positions_marked_before_pricing(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1)  # consumes 10_000_000 cents into a position
    repository.request_subscription(
        SubscriptionRequest(
            request_id="sub-1",
            cash_amount_cents=5_000_000,
            source_authority="flows.test",
            effective_at=_moment(2),
            as_of=_moment(2),
            expected_flow_version=repository.flow_version(),
        )
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.settle_subscription(
            FlowSettleRequest(
                request_id="sub-1",
                source_authority="flows.test",
                as_of=_moment(3),
                expected_flow_version=repository.flow_version(),
            )
        )
    assert excinfo.value.code == "valuation_required_for_pricing"

    valuation(repository, step=4, marks={"600000.SH": 100_000_000})
    receipt, _ = repository.settle_subscription(
        FlowSettleRequest(
            request_id="sub-1",
            source_authority="flows.test",
            as_of=_moment(5),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert receipt.issued_unit_quanta > 0
    repository.assert_conservation()


def test_cancel_subscription_refunds_suspense_and_clears_payable(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    repository.request_subscription(
        SubscriptionRequest(
            request_id="sub-1",
            cash_amount_cents=5_000_000,
            source_authority="flows.test",
            effective_at=_moment(1),
            as_of=_moment(1),
            expected_flow_version=repository.flow_version(),
        )
    )
    snapshot = repository.cancel_subscription(
        FlowCancelRequest(
            request_id="sub-1",
            source_authority="flows.test",
            as_of=_moment(2),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert snapshot.subscription_suspense_cents == 0
    assert snapshot.cash_payable_cents == 0
    assert snapshot.available_cash_cents == GENESIS_CASH_CENTS
    assert snapshot.issued_unit_quanta == GENESIS_UNITS
    assert repository.flow_request_state("sub-1") is FlowRequestState.CANCELLED
    repository.assert_conservation()


def test_subscription_cancellation_blocked_once_units_issued(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    subscribe(repository, request_id="sub-1", cents=5_000_000, step=1)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.cancel_subscription(
            FlowCancelRequest(
                request_id="sub-1",
                source_authority="flows.test",
                as_of=_moment(3),
                expected_flow_version=repository.flow_version(),
            )
        )
    assert excinfo.value.code == "flow_cancel_blocked_terminal_obligations"


# ---------------------------------------------------------------------------
# Redemptions: partial/full, pending_redeemed_units, TERMINATING gate
# ---------------------------------------------------------------------------


def test_request_redemption_is_memo_only(repository: CapitalRepository) -> None:
    genesis(repository)
    valuation(repository, step=1, marks={})
    snapshot_before = repository.capital_risk_snapshot(_moment(2))
    receipt = repository.request_redemption(
        RedemptionRequest(
            request_id="red-1",
            unit_quanta=4_000,
            source_authority="flows.test",
            as_of=_moment(3),
        )
    )
    snapshot_after = repository.capital_risk_snapshot(_moment(2))

    assert receipt.unit_quanta == 4_000
    assert repository.flow_request_state("red-1") is FlowRequestState.REQUESTED
    # Memo reserve: no payable, no unit change, no NAV/HWM/drawdown change,
    # and the capital version stays quiet.
    assert snapshot_after.capital_version == snapshot_before.capital_version
    assert snapshot_after.as_observed_nav_cents == snapshot_before.as_observed_nav_cents
    assert snapshot_after.issued_unit_quanta == snapshot_before.issued_unit_quanta
    assert snapshot_after.cash_payable_cents == 0
    assert snapshot_after.redemption_suspense_cents == 0
    assert (
        snapshot_after.lifetime_high_water_mark_cents
        == snapshot_before.lifetime_high_water_mark_cents
    )


def test_partial_redemption_settle_and_pay(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    valuation(repository, step=1, marks={})
    repository.request_redemption(
        RedemptionRequest(
            request_id="red-1",
            unit_quanta=4_000,
            source_authority="flows.test",
            as_of=_moment(2),
        )
    )
    price = repository.price_redemption(
        FlowPriceRequest(
            request_id="red-1",
            source_authority="flows.test",
            as_of=_moment(3),
        )
    )
    assert price.unit_price_numerator == GENESIS_PRICE_NUMERATOR
    assert price.unit_price_denominator == GENESIS_PRICE_DENOMINATOR
    assert price.cash_amount_cents == 4_000 * GENESIS_PRICE_NUMERATOR

    receipt, snapshot = repository.settle_redemption(
        FlowSettleRequest(
            request_id="red-1",
            source_authority="flows.test",
            as_of=_moment(4),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert receipt.cancelled_unit_quanta == 4_000
    assert receipt.pending_unit_quanta == 0
    assert receipt.payable_id is not None
    assert snapshot.redemption_suspense_cents == 4_000_000
    assert snapshot.cash_payable_cents == 4_000_000
    assert snapshot.issued_unit_quanta == GENESIS_UNITS - 4_000
    assert snapshot.pending_redeemed_unit_quanta == 0
    assert snapshot.available_cash_cents == GENESIS_CASH_CENTS - 4_000_000
    assert repository.lifecycle_state() is LifecycleState.ACTIVE
    repository.assert_conservation()

    pay_receipt, paid = repository.pay_redemption(
        RedemptionPaymentRequest(
            request_id="red-1",
            source_authority="flows.test",
            as_of=_moment(5),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert pay_receipt.cash_amount_cents == 4_000_000
    assert paid.redemption_suspense_cents == 0
    assert paid.cash_payable_cents == 0
    assert paid.available_cash_cents == GENESIS_CASH_CENTS - 4_000_000
    assert paid.issued_unit_quanta == GENESIS_UNITS - 4_000
    assert repository.lifecycle_state() is LifecycleState.ACTIVE
    assert repository.flow_request_state("red-1") is FlowRequestState.PAID
    repository.assert_conservation()


def test_redemption_flow_invariance(repository: CapitalRepository) -> None:
    genesis(repository)
    valuation(repository, step=1, marks={})
    price_before = unit_price_of(repository)

    redeem(repository, request_id="red-1", units=4_000, step=2)
    valuation(repository, step=5, marks={})
    assert unit_price_of(repository) == price_before


def test_full_redemption_enters_terminating_with_pending_units(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    valuation(repository, step=1, marks={})
    repository.request_redemption(
        RedemptionRequest(
            request_id="red-full",
            unit_quanta=GENESIS_UNITS,
            source_authority="flows.test",
            as_of=_moment(2),
        )
    )
    receipt, snapshot = repository.settle_redemption(
        FlowSettleRequest(
            request_id="red-full",
            source_authority="flows.test",
            as_of=_moment(3),
            expected_flow_version=repository.flow_version(),
        )
    )

    # All units atomically become pending redeemed units; the live denominator
    # is empty and the account is settle-only.
    assert receipt.pending_unit_quanta == GENESIS_UNITS
    assert receipt.cancelled_unit_quanta == 0
    assert snapshot.pending_redeemed_unit_quanta == GENESIS_UNITS
    assert snapshot.issued_unit_quanta == GENESIS_UNITS
    assert snapshot.redemption_suspense_cents == GENESIS_CASH_CENTS
    assert repository.lifecycle_state() is LifecycleState.TERMINATING
    repository.assert_conservation()

    pay_receipt, paid = repository.pay_redemption(
        RedemptionPaymentRequest(
            request_id="red-full",
            source_authority="flows.test",
            as_of=_moment(4),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert pay_receipt.burnt_unit_quanta == GENESIS_UNITS
    assert paid.issued_unit_quanta == 0
    assert paid.pending_redeemed_unit_quanta == 0
    assert paid.as_observed_nav_cents == 0
    assert paid.available_cash_cents == 0
    assert repository.lifecycle_state() is LifecycleState.TERMINATED
    repository.assert_conservation()


def test_full_redemption_cannot_erase_units_before_positions_settle(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1)  # open a position with 1_000_000 cents
    valuation(repository, step=2, marks={"600000.SH": 100_000_000})

    # Full redemption is refused while the position is open: units cannot
    # be erased before the economic obligation settles.
    repository.request_redemption(
        RedemptionRequest(
            request_id="red-full",
            unit_quanta=GENESIS_UNITS,
            source_authority="flows.test",
            as_of=_moment(3),
        )
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.settle_redemption(
            FlowSettleRequest(
                request_id="red-full",
                source_authority="flows.test",
                as_of=_moment(4),
                expected_flow_version=repository.flow_version(),
            )
        )
    assert excinfo.value.code == "full_redemption_requires_liquid_portfolio"

    # Liquidate: exit the position and confirm the liquid marks.
    exit_fill(repository, step=5)
    valuation(repository, step=6, marks={})

    # Now the full redemption settles: every unit atomically becomes a
    # pending redeemed unit and the account becomes settle-only.
    receipt, snapshot = repository.settle_redemption(
        FlowSettleRequest(
            request_id="red-full",
            source_authority="flows.test",
            as_of=_moment(7),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert receipt.pending_unit_quanta == GENESIS_UNITS
    assert snapshot.pending_redeemed_unit_quanta == GENESIS_UNITS
    assert snapshot.redemption_suspense_cents == GENESIS_CASH_CENTS
    assert snapshot.cash_payable_cents == GENESIS_CASH_CENTS
    assert snapshot.as_observed_nav_cents == 0
    assert repository.lifecycle_state() is LifecycleState.TERMINATING

    # New entry risk stays blocked while TERMINATING...
    with pytest.raises(CapitalConflict) as excinfo:
        repository.reserve_entry(
            ReserveEntryRequest(
                source_id="src-term-1",
                research_program_id="prog-1",
                economic_lineage_id="eline-1",
                stage_id="stage-1",
                reserved_entry_gross_cents=10_000,
                expected_stream_version=repository.stream_version(),
                as_of=_moment(8),
            )
        )
    assert excinfo.value.code == "lifecycle_blocks_new_risk"
    with pytest.raises(CapitalConflict):
        repository.request_subscription(
            SubscriptionRequest(
                request_id="sub-term",
                cash_amount_cents=1_000,
                source_authority="flows.test",
                effective_at=_moment(8),
                as_of=_moment(8),
                expected_flow_version=repository.flow_version(),
            )
        )
    # ...and the pending units are preserved until the payment lands.
    assert repository.flow_request_state("red-full") is FlowRequestState.SETTLED
    pending_snapshot = repository.capital_risk_snapshot(_moment(9))
    assert pending_snapshot.pending_redeemed_unit_quanta == GENESIS_UNITS
    assert pending_snapshot.issued_unit_quanta == GENESIS_UNITS

    # Only the actual payment burns the units and terminates the account.
    pay_receipt, paid = repository.pay_redemption(
        RedemptionPaymentRequest(
            request_id="red-full",
            source_authority="flows.test",
            as_of=_moment(10),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert pay_receipt.burnt_unit_quanta == GENESIS_UNITS
    assert paid.issued_unit_quanta == 0
    assert paid.pending_redeemed_unit_quanta == 0
    assert paid.as_observed_nav_cents == 0
    assert paid.available_cash_cents == 0
    assert repository.lifecycle_state() is LifecycleState.TERMINATED
    repository.assert_conservation()


def test_redemption_cannot_exceed_live_units(repository: CapitalRepository) -> None:
    genesis(repository)
    valuation(repository, step=1, marks={})
    repository.request_redemption(
        RedemptionRequest(
            request_id="red-1",
            unit_quanta=GENESIS_UNITS + 1,
            source_authority="flows.test",
            as_of=_moment(2),
        )
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.settle_redemption(
            FlowSettleRequest(
                request_id="red-1",
                source_authority="flows.test",
                as_of=_moment(3),
                expected_flow_version=repository.flow_version(),
            )
        )
    assert excinfo.value.code == "redemption_exceeds_live_units"


def test_cancel_redemption_memo_is_quiet_until_obligations_exist(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    valuation(repository, step=1, marks={})
    repository.request_redemption(
        RedemptionRequest(
            request_id="red-1",
            unit_quanta=4_000,
            source_authority="flows.test",
            as_of=_moment(2),
        )
    )
    snapshot = repository.cancel_redemption(
        FlowCancelRequest(
            request_id="red-1",
            source_authority="flows.test",
            as_of=_moment(3),
        )
    )
    # Cancelling a memo reserve has no return impact at all.
    assert snapshot.as_observed_nav_cents == GENESIS_CASH_CENTS
    assert snapshot.issued_unit_quanta == GENESIS_UNITS
    assert repository.flow_request_state("red-1") is FlowRequestState.CANCELLED

    # Once the redemption settled, the payable is a terminal obligation.
    repository.request_redemption(
        RedemptionRequest(
            request_id="red-2",
            unit_quanta=4_000,
            source_authority="flows.test",
            as_of=_moment(4),
        )
    )
    repository.settle_redemption(
        FlowSettleRequest(
            request_id="red-2",
            source_authority="flows.test",
            as_of=_moment(5),
            expected_flow_version=repository.flow_version(),
        )
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.cancel_redemption(
            FlowCancelRequest(
                request_id="red-2",
                source_authority="flows.test",
                as_of=_moment(6),
            )
        )
    assert excinfo.value.code == "flow_cancel_blocked_terminal_obligations"


# ---------------------------------------------------------------------------
# Lifecycle transitions and their one-way nature
# ---------------------------------------------------------------------------


def test_terminated_ledger_rejects_new_facts(repository: CapitalRepository) -> None:
    genesis(repository)
    valuation(repository, step=1, marks={})
    redeem(repository, request_id="red-full", units=GENESIS_UNITS, step=2)
    assert repository.lifecycle_state() is LifecycleState.TERMINATED

    with pytest.raises(CapitalConflict) as excinfo:
        repository.initialize_genesis(
            GenesisRequest(
                idempotency_key="genesis-2",
                account_binding=binding(),
                unit_quanta=1,
                unit_price_numerator=1,
                unit_price_denominator=1,
                source_authority="governance.test",
                effective_at=_moment(5),
                as_of=_moment(5),
            )
        )
    assert excinfo.value.code == "lifecycle_terminal"
    with pytest.raises(CapitalConflict):
        repository.close_valuation(
            ValuationRequest(
                idempotency_key="valuation-after-terminated",
                source_authority="valuation.test",
                effective_at=_moment(5),
                as_of=_moment(5),
                expected_stream_version=repository.stream_version(),
                marks=(),
            )
        )
    with pytest.raises(CapitalConflict):
        repository.start_risk_epoch(
            RiskEpochRequest(
                idempotency_key="epoch-after-terminated",
                risk_epoch=2,
                audited_nav_cents=0,
                source_authority="governance.test",
                effective_at=_moment(5),
                as_of=_moment(5),
            )
        )
    # TERMINATED is an authorized full redemption, not insolvency: the NAV
    # path never logged the -inf sentinel.
    path = repository.nav_projections()
    assert all(
        observation.log_growth_kind is not LogGrowthKind.NEGATIVE_INFINITY
        for observation in path.as_observed
    )


def test_lifecycle_states_are_one_way(repository: CapitalRepository) -> None:
    genesis(repository)
    assert repository.lifecycle_state() is LifecycleState.ACTIVE
    valuation(repository, step=1, marks={})
    repository.request_redemption(
        RedemptionRequest(
            request_id="red-full",
            unit_quanta=GENESIS_UNITS,
            source_authority="flows.test",
            as_of=_moment(2),
        )
    )
    repository.settle_redemption(
        FlowSettleRequest(
            request_id="red-full",
            source_authority="flows.test",
            as_of=_moment(3),
            expected_flow_version=repository.flow_version(),
        )
    )
    assert repository.lifecycle_state() is LifecycleState.TERMINATING
    # There are no live units left to redeem and no resurrection path.
    with pytest.raises(CapitalConflict):
        repository.request_redemption(
            RedemptionRequest(
                request_id="red-again",
                unit_quanta=1,
                source_authority="flows.test",
                as_of=_moment(4),
            )
        )


# ---------------------------------------------------------------------------
# High-water marks and risk epochs
# ---------------------------------------------------------------------------


def test_lifetime_and_active_hwm_track_confirmed_nav(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    _, snapshot = valuation(repository, step=1, marks={})
    assert snapshot.lifetime_high_water_mark_cents == GENESIS_CASH_CENTS
    assert snapshot.active_epoch_high_water_mark_cents == GENESIS_CASH_CENTS
    assert snapshot.as_observed_nav_cents == GENESIS_CASH_CENTS

    # A second confirmation at the same NAV keeps both water marks exact.
    _, snapshot = valuation(repository, step=2, marks={})
    assert snapshot.lifetime_high_water_mark_cents == GENESIS_CASH_CENTS
    assert snapshot.active_epoch_high_water_mark_cents == GENESIS_CASH_CENTS


def test_risk_epoch_resets_active_baseline_but_never_lifetime_history(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1)
    # Mark the position down hard: NAV falls, lifetime HWM stays at genesis.
    valuation(repository, step=2, marks={"600000.SH": 20_000_000})
    drawdown_snapshot = repository.capital_risk_snapshot(_moment(3))
    assert drawdown_snapshot.as_observed_nav_cents < GENESIS_CASH_CENTS
    assert drawdown_snapshot.lifetime_high_water_mark_cents == GENESIS_CASH_CENTS
    lifetime_hwm_before = drawdown_snapshot.lifetime_high_water_mark_cents
    audited_nav = drawdown_snapshot.as_observed_nav_cents

    receipt, snapshot = repository.start_risk_epoch(
        RiskEpochRequest(
            idempotency_key="epoch-2",
            risk_epoch=2,
            audited_nav_cents=audited_nav,
            source_authority="governance.test",
            authorization_reference="gov-recovery-1",
            effective_at=_moment(4),
            as_of=_moment(4),
        )
    )

    assert receipt.risk_epoch == 2
    assert receipt.predecessor_risk_epoch == 1
    # The active-epoch operational baseline is the audited NAV...
    assert snapshot.active_epoch_high_water_mark_cents == audited_nav
    assert snapshot.active_epoch_drawdown_ppm == 0
    # ...while the lifetime HWM and history are never reset.
    assert snapshot.lifetime_high_water_mark_cents == lifetime_hwm_before
    assert snapshot.lifetime_drawdown_ppm > 0

    history = repository.risk_epoch_history()
    assert [epoch.risk_epoch for epoch in history] == [1, 2]
    assert history[0].lifetime_high_water_mark_cents == lifetime_hwm_before
    assert history[1].lifetime_high_water_mark_cents == lifetime_hwm_before
    assert history[1].audited_nav_cents == audited_nav
    assert snapshot.risk_epoch == 2


def test_risk_epoch_idempotent_retry_and_monotonic_predecessor(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    audited = repository.capital_risk_snapshot(_moment(1)).as_observed_nav_cents
    request = RiskEpochRequest(
        idempotency_key="epoch-2",
        risk_epoch=2,
        audited_nav_cents=audited,
        source_authority="governance.test",
        effective_at=_moment(2),
        as_of=_moment(2),
    )
    receipt, snapshot = repository.start_risk_epoch(request)
    retry_receipt, retry_snapshot = repository.start_risk_epoch(request)
    assert retry_receipt.risk_epoch == receipt.risk_epoch
    assert retry_snapshot.capital_version == snapshot.capital_version

    with pytest.raises(CapitalConflict) as excinfo:
        repository.start_risk_epoch(
            RiskEpochRequest(
                idempotency_key="epoch-4",
                risk_epoch=4,
                audited_nav_cents=audited,
                source_authority="governance.test",
                effective_at=_moment(3),
                as_of=_moment(3),
            )
        )
    assert excinfo.value.code == "risk_epoch_predecessor_mismatch"

    with pytest.raises(CapitalConflict) as excinfo:
        repository.start_risk_epoch(
            RiskEpochRequest(
                idempotency_key="epoch-3-bad-audit",
                risk_epoch=3,
                audited_nav_cents=audited + 1,
                source_authority="governance.test",
                effective_at=_moment(3),
                as_of=_moment(3),
            )
        )
    assert excinfo.value.code == "risk_epoch_audit_mismatch"


# ---------------------------------------------------------------------------
# Valuation events, restatements, and the two NAV paths
# ---------------------------------------------------------------------------


def test_close_valuation_marks_positions_without_touching_cash_or_shares(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1)
    before = repository.capital_risk_snapshot(_moment(2))
    receipt, after = valuation(
        repository, step=3, marks={"600000.SH": 120_000_000}
    )

    # The valuation event only updates marks/NAV: cash, shares, and position
    # state are untouched.
    assert after.available_cash_cents == before.available_cash_cents
    assert [position.settled_quantity for position in after.positions] == [
        position.settled_quantity for position in before.positions
    ]
    assert all(
        position.state is PositionState.OPEN for position in after.positions
    )
    # marked gross = 1_000 shares x 120.00 = 12_000_000 cents
    assert after.positions[0].marked_gross_cents == 12_000_000
    assert after.total_gross_exposure_cents == 12_000_000
    assert after.as_observed_nav_cents == (
        GENESIS_CASH_CENTS - 10_000_000 + 12_000_000
    )
    assert receipt.nav_cents == after.as_observed_nav_cents
    assert receipt.log_growth_kind is LogGrowthKind.FINITE
    repository.assert_conservation()


def test_valuation_missing_mark_for_open_position_fails_closed(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1)
    with pytest.raises(CapitalConflict) as excinfo:
        valuation(repository, step=2, marks={})
    assert excinfo.value.code == "valuation_mark_missing"


def test_restatement_links_and_preserves_as_observed_path(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1)
    receipt, _ = valuation(repository, step=2, marks={"600000.SH": 100_000_000})
    original_nav = receipt.nav_cents
    capital_version_before = repository.capital_version()

    restated_receipt, snapshot = repository.restate_valuation(
        RestatementRequest(
            idempotency_key="restatement-1",
            restates_event_id=receipt.event_id,
            source_authority="audit.test",
            effective_at=_moment(3),
            as_of=_moment(3),
            expected_stream_version=repository.stream_version(),
            marks=(
                ValuationMarkInput(security_id="600000.SH", price_micros=90_000_000),
            ),
        )
    )

    # The as-observed snapshot is unchanged: restatements never rewrite the
    # decision-time NAV/HWM.
    assert snapshot.as_observed_nav_cents == original_nav
    # ...but the capital version advanced and the restated path carries the
    # corrected observation with an explicit append-only link.
    assert snapshot.capital_version == capital_version_before + 1
    path = repository.nav_projections()
    assert len(path.as_observed) == 2  # genesis + valuation, untouched
    assert len(path.restated_final) == 1
    restated = path.restated_final[0]
    assert (
        restated.supersedes_observation_id
        == path.as_observed[-1].nav_observation_id
    )
    assert restated.nav_cents == GENESIS_CASH_CENTS - 10_000_000 + 9_000_000
    assert restated.observation_kind is ObservationKind.RESTATED_FINAL
    assert restated_receipt.nav_cents == restated.nav_cents
    repository.assert_conservation()


def test_nav_projection_series_are_typed_integer_paths(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    valuation(repository, step=1, marks={})
    path = repository.nav_projections()
    for observation in (*path.as_observed, *path.restated_final):
        assert type(observation.nav_cents) is int
        assert type(observation.issued_unit_quanta) is int
        assert type(observation.live_unit_quanta) is int
        if observation.unit_price_numerator is not None:
            assert type(observation.unit_price_numerator) is int
            assert type(observation.unit_price_denominator) is int
        assert isinstance(observation.log_growth_kind, LogGrowthKind)
        # No float anywhere in the persisted path representation.
        for value in observation.model_dump().values():
            assert not isinstance(value, float)


# ---------------------------------------------------------------------------
# Insolvency
# ---------------------------------------------------------------------------


def test_confirmed_nav_zero_sets_insolvent_with_typed_negative_infinity(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    # Spend the full capital on one position, then mark it to (rounded) zero.
    entry_fill(repository, step=1)
    _, snapshot = valuation(repository, step=2, marks={"600000.SH": 1})

    assert snapshot.as_observed_nav_cents == 0
    assert repository.lifecycle_state() is LifecycleState.INSOLVENT
    assert snapshot.risk_latch is RiskLatchState.RISK_HALTED

    path = repository.nav_projections()
    insolvent_observation = path.as_observed[-1]
    assert insolvent_observation.nav_cents == 0
    assert insolvent_observation.log_growth_kind is LogGrowthKind.NEGATIVE_INFINITY
    assert insolvent_observation.log_growth_nav_numerator is not None
    assert insolvent_observation.log_growth_nav_denominator is not None
    # The sentinel is a typed marker plus integer fields: no float -inf (or
    # any float) is persisted anywhere.
    assert type(insolvent_observation.log_growth_nav_numerator) is int
    assert type(insolvent_observation.log_growth_nav_denominator) is int


def test_insolvency_blocks_new_risk_but_allows_exit_and_reconciliation(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1)
    _, snapshot = valuation(repository, step=2, marks={"600000.SH": 1})
    assert snapshot.as_observed_nav_cents == 0
    assert repository.lifecycle_state() is LifecycleState.INSOLVENT

    # No new positions, subscriptions, epochs, or genesis resets can erase
    # the failure.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.reserve_entry(
            ReserveEntryRequest(
                source_id="src-insolvent-1",
                research_program_id="prog-1",
                economic_lineage_id="eline-1",
                stage_id="stage-1",
                reserved_entry_gross_cents=10_000,
                expected_stream_version=repository.stream_version(),
                as_of=_moment(4),
            )
        )
    assert excinfo.value.code == "lifecycle_blocks_new_risk"
    with pytest.raises(CapitalConflict):
        repository.request_subscription(
            SubscriptionRequest(
                request_id="sub-insolvent",
                cash_amount_cents=1_000,
                source_authority="flows.test",
                effective_at=_moment(4),
                as_of=_moment(4),
                expected_flow_version=repository.flow_version(),
            )
        )
    with pytest.raises(CapitalConflict):
        repository.start_risk_epoch(
            RiskEpochRequest(
                idempotency_key="epoch-insolvent",
                risk_epoch=2,
                audited_nav_cents=0,
                source_authority="governance.test",
                effective_at=_moment(4),
                as_of=_moment(4),
            )
        )
    with pytest.raises(CapitalConflict):
        repository.initialize_genesis(
            GenesisRequest(
                idempotency_key="genesis-erasure",
                account_binding=binding(),
                unit_quanta=1,
                unit_price_numerator=1,
                unit_price_denominator=1,
                source_authority="governance.test",
                effective_at=_moment(4),
                as_of=_moment(4),
            )
        )

    # Exits, liquidation valuations, and reconciliation continue; insolvency
    # is sticky and cannot recover automatically even when cash returns.
    exit_fill(repository, step=5, price_micros=1_000_000)
    _, final = valuation(repository, step=6, marks={})
    assert repository.lifecycle_state() is LifecycleState.INSOLVENT
    assert final.as_observed_nav_cents > 0  # liquidation cash recovered
    repository.assert_conservation()


def test_insolvency_is_not_erasable_by_epoch_or_regenesis(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    entry_fill(repository, step=1)
    valuation(repository, step=2, marks={"600000.SH": 1})
    assert repository.lifecycle_state() is LifecycleState.INSOLVENT

    # The lifetime history and the insolvent path remain intact.
    path = repository.nav_projections()
    assert path.as_observed[-1].log_growth_kind is LogGrowthKind.NEGATIVE_INFINITY
    history = repository.risk_epoch_history()
    assert [epoch.risk_epoch for epoch in history] == [1]


# ---------------------------------------------------------------------------
# Conservation with nonzero opening capital and external flows
# ---------------------------------------------------------------------------


def test_conservation_identity_with_flows_and_redemptions(
    repository: CapitalRepository,
) -> None:
    genesis(repository)
    valuation(repository, step=1, marks={})

    # Subscription: +5_000_000 cents for 5_000 units.
    subscribe(repository, request_id="sub-1", cents=5_000_000, step=2)

    # Entry, mark, exit: realized P&L enters the identity. The entry fill
    # consumes the full 10_000_000 genesis cents; the exit returns
    # 11_000_000, so the post-exit NAV is 10M + 5M - 10M + 11M = 16M.
    entry_fill(repository, step=4)
    valuation(repository, step=5, marks={"600000.SH": 110_000_000})
    exit_fill(repository, step=6, price_micros=110_000_000)
    valuation(repository, step=7, marks={})

    # Partial redemption of 3_000 of 15_000 units: payout is exactly
    # 3_000 x 16_000_000 / 15_000 = 3_200_000 cents.
    redeem(repository, request_id="red-1", units=3_000, step=8)

    report = repository.assert_conservation()
    assert report.opening_capital_cents == GENESIS_CASH_CENTS
    assert report.external_flow_cents == 5_000_000 - 3_200_000
    assert report.event_count > 0
    # Master identity: opening + external flows + economic P&L balances the
    # closing assets minus liabilities exactly.
    assert (
        report.opening_capital_cents
        + report.external_flow_cents
        + report.economic_pnl_cents
        == report.closing_assets_cents - report.liabilities_cents
    )


def test_flow_payload_conflict_fails_closed(repository: CapitalRepository) -> None:
    genesis(repository)
    repository.request_subscription(
        SubscriptionRequest(
            request_id="sub-1",
            cash_amount_cents=5_000_000,
            source_authority="flows.test",
            effective_at=_moment(1),
            as_of=_moment(1),
            expected_flow_version=repository.flow_version(),
        )
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.request_subscription(
            SubscriptionRequest(
                request_id="sub-1",
                cash_amount_cents=6_000_000,
                source_authority="flows.test",
                effective_at=_moment(1),
                as_of=_moment(1),
                expected_flow_version=repository.flow_version(),
            )
        )
    assert excinfo.value.code == "payload_conflict"


def test_flow_stream_cas_rejects_stale_version(repository: CapitalRepository) -> None:
    genesis(repository)
    stale = repository.flow_version()
    repository.request_subscription(
        SubscriptionRequest(
            request_id="sub-1",
            cash_amount_cents=5_000_000,
            source_authority="flows.test",
            effective_at=_moment(1),
            as_of=_moment(1),
            expected_flow_version=stale,
        )
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.request_subscription(
            SubscriptionRequest(
                request_id="sub-2",
                cash_amount_cents=1_000_000,
                source_authority="flows.test",
                effective_at=_moment(2),
                as_of=_moment(2),
                expected_flow_version=stale,
            )
        )
    assert excinfo.value.code == "flow_version_mismatch"
