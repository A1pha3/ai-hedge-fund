"""Plan 02 Task 2: fills, fees, reserves, positions, and exact conservation.

Property and unit coverage for one-fact/one-event fill semantics, versioned
fee revisions with per-order minimum commission, reserve lifecycle
(live / cancel-pending / released / consumed), late-fill and unattributed
fill handling, the SUBMISSION_AMBIGUOUS worst-case rule, the round-half-even
policy, and the append-only conservation invariant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from src.screening.offensive.v3.capital.conservation import ConservationReport
from src.screening.offensive.v3.capital.fees import (
    FeePolicy,
    commission_charge_cents,
    compute_fee_components,
    fee_execution_id,
)
from src.screening.offensive.v3.capital.fills import (
    UNATTRIBUTED_LINEAGE,
    UNATTRIBUTED_PRODUCER,
    UNATTRIBUTED_PROGRAM,
    UNATTRIBUTED_STAGE,
    FeeRevisionRequest,
    FillAttribution,
    FillRevisionRequest,
    fee_idempotency_key,
    fill_idempotency_key,
)
from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalCommand,
    CapitalCommandPayload,
    CapitalConflict,
    CapitalRepository,
)
from src.screening.offensive.v3.capital.reserves import (
    CapitalReserveState,
    ReserveEntryRequest,
    ReserveReleaseReason,
    ReserveReleaseRequest,
)
from src.screening.offensive.v3.capital.rounding import (
    fill_gross_cents,
    round_half_even_div,
)
from src.screening.offensive.v3.contracts import (
    CashEconomicEventLeg,
    CashReceivableEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
    ExecutionMode,
    ExecutionRevisionKind,
    ExecutionSide,
    PositionState,
    ReconciliationLatchState,
)


T0 = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
ENVIRONMENT_FINGERPRINT = "ab" * 32

# Versioned fee policy used across the Task 2 tests: 30bps commission with a
# 5 yuan per-order minimum, 10bps sell-side stamp tax, 2bps transfer fee.
POLICY_V1 = FeePolicy(
    fee_policy_version="fee-schedule-2026-v1",
    commission_rate_ppm=3_000,
    min_commission_cents=500,
    stamp_tax_rate_ppm=1_000,
    transfer_fee_rate_ppm=20,
)
POLICY_V2 = FeePolicy(
    fee_policy_version="fee-schedule-2026-v2",
    commission_rate_ppm=3_000,
    min_commission_cents=500,
    stamp_tax_rate_ppm=500,
    transfer_fee_rate_ppm=20,
)


def binding() -> AccountBinding:
    return AccountBinding(
        portfolio_id="pf-test",
        mode=ExecutionMode.BROKER_CONFIRMED,
        broker_account_id="acct-test",
        base_currency="CNY",
        environment_fingerprint=ENVIRONMENT_FINGERPRINT,
    )


ATTRIBUTION = FillAttribution(
    producer_namespace="btst",
    research_program_id="prog-1",
    economic_lineage_id="eline-1",
    stage_id="stage-1",
)


@pytest.fixture()
def repository(tmp_path: Path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "capital.sqlite3")


def _moment(step: int) -> datetime:
    return T0 + timedelta(minutes=step)


def deposit(repository: CapitalRepository, cents: int, sequence: int) -> None:
    """Seed cash with the only inflow available before Task 3 genesis."""

    amount = Decimal(cents) / 100
    receivable_id = f"rcv-{sequence}"
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"declare-{sequence}",
            account_binding=binding(),
            expected_stream_version=repository.stream_version(),
            as_of=_moment(sequence),
            payload=CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
                effective_at=_moment(sequence),
                source_authority="test.seed",
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"declare-{sequence}-r",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id="000001.SZ",
                        cash_amount=amount,
                    ),
                ),
            ),
        )
    )
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"settle-{sequence}",
            account_binding=binding(),
            expected_stream_version=repository.stream_version(),
            as_of=_moment(sequence) + timedelta(seconds=30),
            payload=CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_CASH_SETTLED,
                effective_at=_moment(sequence) + timedelta(seconds=30),
                source_authority="test.seed",
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"settle-{sequence}-r",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id="000001.SZ",
                        cash_amount=amount,
                    ),
                    CashEconomicEventLeg(
                        leg_id=f"settle-{sequence}-c",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH,
                        cash_amount=amount,
                    ),
                ),
            ),
        )
    )


def fill_request(
    execution_id: str,
    *,
    order_id: str = "ord-1",
    side: ExecutionSide = ExecutionSide.ENTRY,
    security_id: str = "600000.SH",
    price_micros: int = 10_000_000,
    quantity: int = 100,
    attribution: FillAttribution | None = ATTRIBUTION,
    position_lineage_id: str | None = "lin-1",
    economic_lot_id: str | None = "lot-1",
    reserve_source_id: str | None = None,
    step: int = 0,
    expected_stream_version: int | None = None,
    repository: CapitalRepository | None = None,
) -> FillRevisionRequest:
    if expected_stream_version is None:
        assert repository is not None
        expected_stream_version = repository.stream_version()
    return FillRevisionRequest(
        execution_id=execution_id,
        revision=1,
        order_id=order_id,
        side=side,
        security_id=security_id,
        price_micros=price_micros,
        quantity=quantity,
        position_lineage_id=position_lineage_id,
        economic_lot_id=economic_lot_id,
        attribution=attribution,
        reserve_source_id=reserve_source_id,
        source_authority="broker.test",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=expected_stream_version,
    )


def reserve_request(
    source_id: str,
    cents: int,
    repository: CapitalRepository,
    *,
    step: int = 0,
) -> ReserveEntryRequest:
    return ReserveEntryRequest(
        source_id=source_id,
        research_program_id="prog-1",
        economic_lineage_id="eline-1",
        stage_id="stage-1",
        reserved_entry_gross_cents=cents,
        expected_stream_version=repository.stream_version(),
        as_of=_moment(step),
    )


def release_request(
    source_id: str,
    reason: ReserveReleaseReason,
    repository: CapitalRepository,
    *,
    step: int = 0,
) -> ReserveReleaseRequest:
    return ReserveReleaseRequest(
        source_id=source_id,
        reason=reason,
        expected_stream_version=repository.stream_version(),
        as_of=_moment(step),
    )


def fee_request(
    fill_execution_id: str,
    repository: CapitalRepository,
    *,
    policy: FeePolicy = POLICY_V1,
    step: int = 0,
) -> FeeRevisionRequest:
    return FeeRevisionRequest(
        fill_execution_id=fill_execution_id,
        revision=1,
        fee_policy=policy,
        source_authority="broker.test",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
    )


# ---------------------------------------------------------------------------
# Rounding policy
# ---------------------------------------------------------------------------


def test_round_half_even_is_exact_and_bankers() -> None:
    assert round_half_even_div(0, 7) == 0
    assert round_half_even_div(10, 2) == 5
    assert round_half_even_div(1, 2) == 0  # 0.5 -> even 0
    assert round_half_even_div(3, 2) == 2  # 1.5 -> even 2
    assert round_half_even_div(5, 2) == 2  # 2.5 -> even 2
    assert round_half_even_div(7, 2) == 4  # 3.5 -> even 4
    assert round_half_even_div(-3, 2) == -2
    assert round_half_even_div(100_000 * 3_000, 1_000_000) == 300
    assert round_half_even_div(12_345 * 1_000, 1_000_000) == 12
    with pytest.raises(ValueError):
        round_half_even_div(1, 0)


def test_fill_gross_converts_price_micros_with_round_half_even() -> None:
    # 1.005 yuan x 1 = 100.5 cents -> 100 (even)
    assert fill_gross_cents(1_005_000, 1) == 100
    # 1.015 yuan x 1 = 101.5 cents -> 102 (even)
    assert fill_gross_cents(1_015_000, 1) == 102
    # 0.010005 yuan x 1000 = 1000.5 cents -> 1000
    assert fill_gross_cents(10_005, 1_000) == 1_000
    # 10.00 yuan x 100 = exactly 100_000 cents
    assert fill_gross_cents(10_000_000, 100) == 100_000
    with pytest.raises(ValueError):
        fill_gross_cents(0, 100)
    with pytest.raises(ValueError):
        fill_gross_cents(10_000_000, 0)


def test_fill_gross_that_rounds_to_zero_is_rejected(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 100_000, 1)
    request = fill_request(
        "exec-tiny",
        repository=repository,
        price_micros=4_999,  # 0.004999 yuan x 1 share -> 0.4999 cents
        quantity=1,
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_fill_revision(request)
    assert excinfo.value.code == "fill_gross_rounds_to_zero"
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Partial fills, positions, and cost basis
# ---------------------------------------------------------------------------


def test_partial_entry_fills_accumulate_position_and_basis(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)

    receipt_a, snapshot_a = repository.record_fill_revision(
        fill_request(
            "exec-1",
            repository=repository,
            price_micros=10_000_000,
            quantity=100,
            step=1,
        )
    )
    assert receipt_a.gross_cents == 100_000
    assert receipt_a.unattributed is False
    assert snapshot_a.positions[0].settled_quantity == 100
    assert snapshot_a.available_cash_cents == 900_000

    receipt_b, snapshot_b = repository.record_fill_revision(
        fill_request(
            "exec-2",
            repository=repository,
            price_micros=10_500_000,
            quantity=100,
            step=2,
        )
    )
    assert receipt_b.gross_cents == 105_000

    position = snapshot_b.positions[0]
    assert position.settled_quantity == 200
    assert position.tradable_quantity == 200
    assert position.state is PositionState.OPEN
    assert snapshot_b.available_cash_cents == 795_000

    with repository.engine.connect() as conn:
        basis = conn.execute(
            sa.text("SELECT cost_basis_cents FROM positions")
        ).scalar()
    assert basis == 205_000
    repository.assert_conservation()


def test_partial_exit_fills_consume_average_cost_basis_half_even(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    # 3 shares for exactly 99.9999 yuan: average cost 33.3333 cents each.
    repository.record_fill_revision(
        fill_request(
            "exec-1",
            repository=repository,
            price_micros=333_333,
            quantity=3,
            step=1,
        )
    )
    with repository.engine.connect() as conn:
        entry_basis = conn.execute(
            sa.text("SELECT cost_basis_cents FROM positions")
        ).scalar()
    assert entry_basis == 100  # 3 x 0.333333 yuan = 0.999999 yuan -> 100 cents

    repository.record_fill_revision(
        fill_request(
            "exec-exit-1",
            repository=repository,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            price_micros=400_000,
            quantity=1,
            step=2,
        )
    )

    with repository.engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT state, settled_quantity_units, cost_basis_cents"
                " FROM positions"
            )
        ).one()
    # round-half-even(100 * 1 / 3) = 33 consumed, 67 remaining.
    assert row.cost_basis_cents == 67
    assert row.settled_quantity_units == 2
    assert row.state == PositionState.EXIT_PENDING.value

    repository.record_fill_revision(
        fill_request(
            "exec-exit-2",
            repository=repository,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            price_micros=400_000,
            quantity=2,
            step=3,
        )
    )
    with repository.engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT state, settled_quantity_units, cost_basis_cents"
                " FROM positions"
            )
        ).one()
    # Full exit consumes the exact remainder: no rounding residue.
    assert row.settled_quantity_units == 0
    assert row.cost_basis_cents == 0
    assert row.state == PositionState.CLOSED.value
    snapshot = repository.capital_risk_snapshot(_moment(4))
    assert snapshot.positions == ()
    repository.assert_conservation()


def test_full_exit_closes_lot_and_keeps_snapshot_consistent(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    receipt, snapshot = repository.record_fill_revision(
        fill_request(
            "exec-exit-1",
            repository=repository,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            price_micros=11_000_000,
            quantity=100,
            step=2,
        )
    )
    assert receipt.gross_cents == 110_000
    assert snapshot.positions == ()
    assert snapshot.available_cash_cents == 1_000_000 - 100_000 + 110_000
    report = repository.assert_conservation()
    assert report.realized_pnl_ex_fees_cents == 10_000
    assert report.closing_cost_basis_cents == 0


def test_exit_beyond_position_is_rejected_and_rolled_back(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    stream = repository.stream_version()
    capital = repository.capital_version()
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_fill_revision(
            fill_request(
                "exec-exit-big",
                repository=repository,
                order_id="ord-exit",
                side=ExecutionSide.EXIT,
                quantity=101,
                step=2,
            )
        )
    assert excinfo.value.code == "projection_rejected"
    assert repository.stream_version() == stream
    assert repository.capital_version() == capital
    repository.assert_conservation()


def test_entry_into_exiting_lot_is_rejected(repository: CapitalRepository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    repository.record_fill_revision(
        fill_request(
            "exec-exit-1",
            repository=repository,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            quantity=40,
            step=2,
        )
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_fill_revision(
            fill_request("exec-2", repository=repository, quantity=10, step=3)
        )
    assert excinfo.value.code == "projection_rejected"
    repository.assert_conservation()


def test_fill_revision_beyond_recorded_dispatches_to_execution_revisions(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    request = fill_request("exec-1", repository=repository, quantity=100, step=1)
    with pytest.raises(ValidationError):
        FillRevisionRequest.model_validate(
            {**request.model_dump(mode="python"), "revision": 0}
        )
    repository.record_fill_revision(request)
    # Plan 02 Task 6: revision > 1 is a broker bust/correction
    # supersession, re-projected from the append-only history.
    later = FillRevisionRequest.model_validate(
        {
            **request.model_dump(mode="python"),
            "revision": 2,
            "revision_kind": ExecutionRevisionKind.BUSTED,
            "expected_stream_version": repository.stream_version(),
        }
    )
    receipt, snapshot = repository.record_fill_revision(later)
    assert receipt.revision == 2
    assert receipt.revision_kind is ExecutionRevisionKind.BUSTED
    assert snapshot.positions == ()
    repository.assert_conservation()
    # A revision against an execution with no recorded fill stays rejected.
    unknown = FillRevisionRequest.model_validate(
        {
            **fill_request(
                "exec-none", repository=repository, quantity=100, step=2
            ).model_dump(mode="python"),
            "revision": 2,
            "revision_kind": ExecutionRevisionKind.BUSTED,
        }
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_fill_revision(unknown)
    assert excinfo.value.code == "execution_unknown"


# ---------------------------------------------------------------------------
# Fee revisions: minimum commission, stamp tax versions, transfer fee
# ---------------------------------------------------------------------------


def test_fee_components_round_half_even_and_stamp_only_on_exit() -> None:
    components = compute_fee_components(100_000, ExecutionSide.ENTRY, POLICY_V1)
    assert components.commission_base_cents == 300
    assert components.stamp_tax_cents == 0
    assert components.transfer_fee_cents == 2

    exit_side = compute_fee_components(12_345, ExecutionSide.EXIT, POLICY_V1)
    assert exit_side.commission_base_cents == 37  # 37.035 -> 37
    assert exit_side.stamp_tax_cents == 12  # 12.345 -> 12
    assert exit_side.transfer_fee_cents == 0  # 0.2468 -> 0

    half_even = compute_fee_components(10_000, ExecutionSide.EXIT, POLICY_V2)
    # stamp v2: 10_000 * 500 / 1e6 = exactly 5
    assert half_even.stamp_tax_cents == 5
    # commission 30.0 -> 30 (exact)
    assert half_even.commission_base_cents == 30


def test_minimum_commission_charged_once_per_order(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 5_000_000, 1)
    repository.record_fill_revision(
        fill_request(
            "exec-1",
            repository=repository,
            price_micros=10_000_000,
            quantity=100,
            step=1,
        )
    )
    receipt, snapshot = repository.record_fee_revision(
        fee_request("exec-1", repository, step=2)
    )
    # base commission 300 < 500 minimum -> shortfall charged once.
    assert receipt.commission_cents == 500
    assert receipt.stamp_tax_cents == 0
    assert receipt.transfer_fee_cents == 2
    assert receipt.total_cents == 502
    assert snapshot.available_cash_cents == 5_000_000 - 100_000 - 502

    repository.record_fill_revision(
        fill_request(
            "exec-2",
            repository=repository,
            price_micros=10_000_000,
            quantity=100,
            step=3,
        )
    )
    receipt_b, _ = repository.record_fee_revision(
        fee_request("exec-2", repository, step=4)
    )
    # cumulative base 600 exceeds the 500 already charged -> +100 delta.
    assert receipt_b.commission_cents == 100
    assert receipt_b.transfer_fee_cents == 2
    assert receipt_b.total_cents == 102

    report = repository.assert_conservation()
    assert report.total_fee_cents == 502 + 102
    # The per-order minimum commission rule in isolation.
    assert commission_charge_cents(600, 300, 500) == 100
    assert commission_charge_cents(300, 0, 500) == 500
    assert commission_charge_cents(30_600, 600, 500) == 30_000


def test_commission_shortfall_progresses_with_cumulative_base(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 20_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    first, _ = repository.record_fee_revision(fee_request("exec-1", repository, step=2))
    assert first.commission_cents == 500

    repository.record_fill_revision(
        fill_request("exec-2", repository=repository, quantity=100, step=3)
    )
    second, _ = repository.record_fee_revision(fee_request("exec-2", repository, step=4))
    assert second.commission_cents == 100  # cumulative base 600 - 500 charged

    repository.record_fill_revision(
        fill_request(
            "exec-3",
            repository=repository,
            price_micros=100_000_000,
            quantity=1_000,
            step=5,
        )
    )
    third, _ = repository.record_fee_revision(fee_request("exec-3", repository, step=6))
    assert third.commission_cents == 30_000  # base 30_000 on the large fill
    assert 500 + 100 + 30_000 == max(500, 300 + 300 + 30_000)
    repository.assert_conservation()


def test_stamp_tax_version_changes_exit_charge(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 5_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    repository.record_fill_revision(
        fill_request(
            "exec-exit-1",
            repository=repository,
            order_id="ord-exit-1",
            side=ExecutionSide.EXIT,
            quantity=50,
            step=2,
        )
    )
    receipt_v1, _ = repository.record_fee_revision(
        fee_request("exec-exit-1", repository, policy=POLICY_V1, step=3)
    )
    assert receipt_v1.fee_policy_version == "fee-schedule-2026-v1"
    assert receipt_v1.stamp_tax_cents == 50  # 50_000 * 1000 / 1e6

    repository.record_fill_revision(
        fill_request(
            "exec-exit-2",
            repository=repository,
            order_id="ord-exit-2",
            side=ExecutionSide.EXIT,
            quantity=50,
            step=4,
        )
    )
    receipt_v2, _ = repository.record_fee_revision(
        fee_request("exec-exit-2", repository, policy=POLICY_V2, step=5)
    )
    assert receipt_v2.fee_policy_version == "fee-schedule-2026-v2"
    assert receipt_v2.stamp_tax_cents == 25  # 50_000 * 500 / 1e6
    repository.assert_conservation()


def test_transfer_fee_applies_to_both_sides(repository: CapitalRepository) -> None:
    deposit(repository, 5_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    entry_fee, _ = repository.record_fee_revision(fee_request("exec-1", repository, step=2))
    repository.record_fill_revision(
        fill_request(
            "exec-exit-1",
            repository=repository,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            quantity=100,
            step=3,
        )
    )
    exit_fee, _ = repository.record_fee_revision(
        fee_request("exec-exit-1", repository, step=4)
    )
    assert entry_fee.transfer_fee_cents == 2
    assert exit_fee.transfer_fee_cents == 2
    repository.assert_conservation()


def test_fee_revision_requires_a_recorded_fill(repository: CapitalRepository) -> None:
    deposit(repository, 5_000_000, 1)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_fee_revision(fee_request("exec-ghost", repository, step=1))
    assert excinfo.value.code == "fill_unknown"
    repository.assert_conservation()


def test_fee_revision_duplicate_is_idempotent_and_divergence_conflicts(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 5_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    request = fee_request("exec-1", repository, step=2)
    first_receipt, first_snapshot = repository.record_fee_revision(request)
    retry_receipt, retry_snapshot = repository.record_fee_revision(request)
    assert retry_receipt == first_receipt
    assert retry_snapshot.capital_version == first_snapshot.capital_version
    # deposit (2 events) + fill + fee
    assert repository.stream_version() == 4
    assert repository.capital_version() == 4
    repository.assert_conservation()

    divergent = fee_request("exec-1", repository, policy=POLICY_V2, step=2)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_fee_revision(divergent)
    assert excinfo.value.code == "payload_conflict"
    repository.assert_conservation()


def test_zero_total_fee_revision_records_registry_without_event(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 5_000_000, 1)
    zero_policy = FeePolicy(
        fee_policy_version="fee-zero",
        commission_rate_ppm=0,
        min_commission_cents=0,
        stamp_tax_rate_ppm=0,
        transfer_fee_rate_ppm=0,
    )
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    stream = repository.stream_version()
    capital = repository.capital_version()
    receipt, snapshot = repository.record_fee_revision(
        fee_request("exec-1", repository, policy=zero_policy, step=2)
    )
    assert receipt.total_cents == 0
    assert receipt.event_id is None
    # Registry row only: no economic event and no capital fact, so both
    # versions stay quiet (a zero charge changes no capital).
    assert repository.stream_version() == stream
    assert snapshot.capital_version == capital
    retry_receipt, retry_snapshot = repository.record_fee_revision(
        fee_request("exec-1", repository, policy=zero_policy, step=2)
    )
    assert retry_receipt == receipt
    assert retry_snapshot.capital_version == capital
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Reserve lifecycle
# ---------------------------------------------------------------------------


def test_reserve_entry_moves_cash_to_restricted_and_publishes_component(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    stream = repository.stream_version()
    snapshot = repository.reserve_entry(reserve_request("src-1", 400_000, repository))

    assert repository.stream_version() == stream  # reserves are not events
    assert snapshot.capital_version == stream + 1
    assert snapshot.available_cash_cents == 600_000
    assert snapshot.restricted_cash_cents == 400_000
    assert snapshot.reserved_cash_cents == 400_000
    assert len(snapshot.entry_reserves) == 1
    component = snapshot.entry_reserves[0]
    assert component.source_id == "src-1"
    assert component.reserved_entry_gross_cents == 400_000
    assert component.covered_live_order_id is None
    assert component.research_program_id == "prog-1"
    global_bucket = snapshot.exposures[0]
    assert global_bucket.reserved_entry_gross_cents == 400_000
    assert snapshot.total_gross_exposure_cents == 400_000
    repository.assert_conservation()


def test_reserve_entry_requires_available_cash(repository: CapitalRepository) -> None:
    deposit(repository, 100_000, 1)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.reserve_entry(reserve_request("src-1", 100_001, repository))
    assert excinfo.value.code == "insufficient_available_cash"
    snapshot = repository.capital_risk_snapshot(_moment(9))
    assert snapshot.available_cash_cents == 100_000
    assert snapshot.reserved_cash_cents == 0
    repository.assert_conservation()


def test_reserve_entry_source_id_conflicts_and_idempotence(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    request = reserve_request("src-1", 400_000, repository)
    first = repository.reserve_entry(request)
    retry = repository.reserve_entry(request)
    assert retry.reserved_cash_cents == first.reserved_cash_cents
    assert retry.capital_version == first.capital_version

    divergent = reserve_request("src-1", 300_000, repository)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.reserve_entry(divergent)
    assert excinfo.value.code == "reserve_source_conflict"
    repository.assert_conservation()


def test_cancel_request_moves_reserve_to_cancel_pending_keeping_restriction(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(reserve_request("src-1", 400_000, repository))
    snapshot = repository.release_reserve(
        release_request("src-1", ReserveReleaseReason.CANCEL_REQUESTED, repository)
    )
    assert snapshot.restricted_cash_cents == 400_000
    assert snapshot.available_cash_cents == 600_000
    assert snapshot.reserved_cash_cents == 400_000
    assert len(snapshot.entry_reserves) == 1
    repository.assert_conservation()

    # Repeating the cancel request is a quiet no-op (no version growth).
    capital = repository.capital_version()
    again = repository.release_reserve(
        release_request("src-1", ReserveReleaseReason.CANCEL_REQUESTED, repository)
    )
    assert again.capital_version == capital
    repository.assert_conservation()


@pytest.mark.parametrize(
    "confirm_reason",
    [
        ReserveReleaseReason.CANCEL_CONFIRMED,
        ReserveReleaseReason.ORDER_REJECTED,
        ReserveReleaseReason.ORDER_EXPIRED,
    ],
)
def test_confirmed_release_returns_cash(
    repository: CapitalRepository, confirm_reason: ReserveReleaseReason
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(reserve_request("src-1", 400_000, repository))
    snapshot = repository.release_reserve(
        release_request("src-1", confirm_reason, repository)
    )
    assert snapshot.restricted_cash_cents == 0
    assert snapshot.available_cash_cents == 1_000_000
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.entry_reserves == ()
    repository.assert_conservation()


def test_cancel_pending_then_confirmed_release(repository: CapitalRepository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(reserve_request("src-1", 400_000, repository))
    repository.release_reserve(
        release_request("src-1", ReserveReleaseReason.CANCEL_REQUESTED, repository)
    )
    snapshot = repository.release_reserve(
        release_request("src-1", ReserveReleaseReason.CANCEL_CONFIRMED, repository)
    )
    assert snapshot.restricted_cash_cents == 0
    assert snapshot.available_cash_cents == 1_000_000
    assert snapshot.reserved_cash_cents == 0
    repository.assert_conservation()


def test_submission_ambiguous_release_keeps_worst_case_reserve(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    before = repository.reserve_entry(reserve_request("src-1", 400_000, repository))
    capital = repository.capital_version()
    with pytest.raises(CapitalConflict) as excinfo:
        repository.release_reserve(
            release_request(
                "src-1", ReserveReleaseReason.SUBMISSION_AMBIGUOUS, repository
            )
        )
    assert excinfo.value.code == "submission_ambiguous_worst_case_retained"

    snapshot = repository.capital_risk_snapshot(_moment(9))
    assert snapshot.reserved_cash_cents == before.reserved_cash_cents
    assert snapshot.restricted_cash_cents == 400_000
    assert snapshot.available_cash_cents == 600_000
    assert repository.capital_version() == capital
    repository.assert_conservation()


def test_release_unknown_or_consumed_reserve_conflicts(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.release_reserve(
            release_request(
                "src-ghost", ReserveReleaseReason.CANCEL_CONFIRMED, repository
            )
        )
    assert excinfo.value.code == "reserve_unknown"

    repository.reserve_entry(reserve_request("src-1", 400_000, repository))
    repository.record_fill_revision(
        fill_request(
            "exec-1",
            repository=repository,
            price_micros=10_000_000,
            quantity=100,
            reserve_source_id="src-1",
            step=1,
        )
    )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.release_reserve(
            release_request("src-1", ReserveReleaseReason.CANCEL_CONFIRMED, repository)
        )
    assert excinfo.value.code == "reserve_state_conflict"
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Fills against reserves, late fills, and unattributed fills
# ---------------------------------------------------------------------------


def test_entry_fill_consumes_live_reserve_and_releases_surplus(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(reserve_request("src-1", 400_000, repository))
    receipt, snapshot = repository.record_fill_revision(
        fill_request(
            "exec-1",
            repository=repository,
            price_micros=10_000_000,
            quantity=100,
            reserve_source_id="src-1",
            step=1,
        )
    )
    assert receipt.reserve_consumed_cents == 400_000
    # restricted pays the fill; the surplus returns to available.
    assert snapshot.restricted_cash_cents == 0
    assert snapshot.available_cash_cents == 600_000 + 400_000 - 100_000
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.entry_reserves == ()
    repository.assert_conservation()


def test_fill_larger_than_reserve_draws_remainder_from_available(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(reserve_request("src-1", 150_000, repository))
    receipt, snapshot = repository.record_fill_revision(
        fill_request(
            "exec-1",
            repository=repository,
            price_micros=20_000_000,
            quantity=100,
            reserve_source_id="src-1",
            step=1,
        )
    )
    assert receipt.gross_cents == 200_000
    assert snapshot.available_cash_cents == 850_000 + 150_000 - 200_000
    assert snapshot.restricted_cash_cents == 0
    repository.assert_conservation()


def test_cancel_pending_reserve_can_still_be_filled_without_flag(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(reserve_request("src-1", 400_000, repository))
    repository.release_reserve(
        release_request("src-1", ReserveReleaseReason.CANCEL_REQUESTED, repository)
    )
    receipt, snapshot = repository.record_fill_revision(
        fill_request(
            "exec-1",
            repository=repository,
            price_micros=10_000_000,
            quantity=100,
            reserve_source_id="src-1",
            step=1,
        )
    )
    assert receipt.unattributed is False
    assert receipt.reserve_consumed_cents == 400_000
    assert snapshot.reconciliation_latch is ReconciliationLatchState.CLEAR
    assert snapshot.unattributed_risk_cents == 0
    assert snapshot.restricted_cash_cents == 0
    repository.assert_conservation()


def test_late_fill_after_confirmed_cancel_is_preserved_and_flagged(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(reserve_request("src-1", 400_000, repository))
    repository.release_reserve(
        release_request("src-1", ReserveReleaseReason.CANCEL_CONFIRMED, repository)
    )
    receipt, snapshot = repository.record_fill_revision(
        fill_request(
            "exec-late",
            repository=repository,
            price_micros=10_000_000,
            quantity=100,
            reserve_source_id="src-1",
            step=1,
        )
    )
    # The fill is economically real: cash moved and shares are preserved.
    assert snapshot.available_cash_cents == 1_000_000 - 100_000
    assert receipt.unattributed is True
    assert len(snapshot.positions) == 1
    position = snapshot.positions[0]
    assert position.settled_quantity == 100
    assert position.research_program_id == UNATTRIBUTED_PROGRAM
    # Flagged: unattributed risk at cost and reconciliation halt.
    assert snapshot.unattributed_risk_cents == 100_000
    assert snapshot.reconciliation_latch is ReconciliationLatchState.RECONCILIATION_HALT
    global_bucket = snapshot.exposures[0]
    assert global_bucket.unattributed_risk_cents == 100_000
    assert snapshot.total_gross_exposure_cents == 100_000
    repository.assert_conservation()


def test_unattributed_entry_fill_preserved_and_flagged(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    receipt, snapshot = repository.record_fill_revision(
        fill_request(
            "exec-stray",
            repository=repository,
            attribution=None,
            position_lineage_id=None,
            economic_lot_id=None,
            quantity=100,
            step=1,
        )
    )
    assert receipt.unattributed is True
    assert receipt.position_lineage_id == receipt.economic_lot_id
    assert receipt.position_lineage_id.startswith("unattributed:")
    position = snapshot.positions[0]
    assert position.producer_namespace == UNATTRIBUTED_PRODUCER
    assert position.research_program_id == UNATTRIBUTED_PROGRAM
    assert position.economic_lineage_id == UNATTRIBUTED_LINEAGE
    assert position.stage_id == UNATTRIBUTED_STAGE
    assert snapshot.unattributed_risk_cents == 100_000
    assert snapshot.reconciliation_latch is ReconciliationLatchState.RECONCILIATION_HALT
    repository.assert_conservation()


def test_unattributed_exit_reduces_and_clears_flag_when_flat(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    receipt, _ = repository.record_fill_revision(
        fill_request(
            "exec-stray",
            repository=repository,
            attribution=None,
            position_lineage_id=None,
            economic_lot_id=None,
            quantity=100,
            step=1,
        )
    )
    exit_request = fill_request(
        "exec-stray-exit",
        repository=repository,
        order_id="ord-stray-exit",
        side=ExecutionSide.EXIT,
        attribution=None,
        position_lineage_id=receipt.position_lineage_id,
        economic_lot_id=receipt.economic_lot_id,
        quantity=100,
        step=2,
    )
    _, snapshot = repository.record_fill_revision(exit_request)
    assert snapshot.positions == ()
    assert snapshot.unattributed_risk_cents == 0
    assert snapshot.reconciliation_latch is ReconciliationLatchState.CLEAR
    repository.assert_conservation()


def test_duplicate_fill_revision_is_idempotent(repository: CapitalRepository) -> None:
    deposit(repository, 1_000_000, 1)
    request = fill_request("exec-1", repository=repository, quantity=100, step=1)
    first_receipt, first_snapshot = repository.record_fill_revision(request)
    retry_receipt, retry_snapshot = repository.record_fill_revision(request)
    assert retry_receipt == first_receipt
    assert retry_snapshot.available_cash_cents == first_snapshot.available_cash_cents
    assert retry_snapshot.capital_version == first_snapshot.capital_version
    assert repository.stream_version() == 3
    assert repository.capital_version() == 3
    repository.assert_conservation()


def test_divergent_fill_revision_payload_conflicts(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    divergent = fill_request("exec-1", repository=repository, quantity=200, step=1)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_fill_revision(divergent)
    assert excinfo.value.code == "payload_conflict"
    repository.assert_conservation()


def test_fill_and_fee_idempotency_keys_are_deterministic() -> None:
    assert fill_idempotency_key("exec-1", 1) == fill_idempotency_key("exec-1", 1)
    assert fill_idempotency_key("exec-1", 1) != fill_idempotency_key("exec-2", 1)
    assert fee_idempotency_key("exec-1", 1) != fill_idempotency_key("exec-1", 1)
    assert fee_execution_id("exec-1") != "exec-1"


# ---------------------------------------------------------------------------
# Snapshot reads and conservation
# ---------------------------------------------------------------------------


def test_capital_risk_snapshot_is_a_quiet_read(repository: CapitalRepository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(reserve_request("src-1", 400_000, repository))
    capital = repository.capital_version()
    stream = repository.stream_version()
    first = repository.capital_risk_snapshot(_moment(5))
    second = repository.capital_risk_snapshot(_moment(6))
    assert first.risk_snapshot_id == second.risk_snapshot_id
    assert first.capital_version == capital
    assert repository.capital_version() == capital
    assert repository.stream_version() == stream


def test_capital_risk_snapshot_requires_bound_account(tmp_path: Path) -> None:
    empty = CapitalRepository.initialize(tmp_path / "empty.sqlite3")
    with pytest.raises(CapitalConflict) as excinfo:
        empty.capital_risk_snapshot(T0)
    assert excinfo.value.code == "account_not_bound"


def test_assert_conservation_on_interleaved_sequence(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(reserve_request("src-1", 400_000, repository, step=1))
    repository.record_fill_revision(
        fill_request(
            "exec-1",
            order_id="ord-a",
            repository=repository,
            price_micros=10_000_000,
            quantity=100,
            reserve_source_id="src-1",
            step=2,
        )
    )
    repository.record_fee_revision(fee_request("exec-1", repository, step=3))
    repository.record_fill_revision(
        fill_request(
            "exec-2",
            order_id="ord-a",
            repository=repository,
            price_micros=10_000_000,
            quantity=100,
            step=4,
        )
    )
    repository.record_fee_revision(fee_request("exec-2", repository, step=5))
    repository.record_fill_revision(
        fill_request(
            "exec-3",
            order_id="ord-b",
            repository=repository,
            side=ExecutionSide.EXIT,
            price_micros=11_000_000,
            quantity=100,
            step=6,
        )
    )
    repository.record_fee_revision(fee_request("exec-3", repository, step=7))

    report = repository.assert_conservation()
    assert isinstance(report, ConservationReport)
    assert report.opening_capital_cents == 0
    assert report.external_flow_cents == 0
    assert report.entry_gross_cents == 200_000
    assert report.exit_gross_cents == 110_000
    assert report.consumed_cost_basis_cents == 100_000
    assert report.realized_pnl_ex_fees_cents == 10_000
    assert report.total_fee_cents == 502 + 102 + 612
    assert report.dividend_income_cents == 1_000_000
    assert report.economic_pnl_cents == (
        report.realized_pnl_ex_fees_cents
        + report.dividend_income_cents
        - report.total_fee_cents
    )
    assert report.closing_cash_cents == 908_784
    assert report.closing_cost_basis_cents == 100_000
    assert report.closing_receivable_cents == 0
    assert report.closing_assets_cents == 908_784 + 100_000
    assert report.liabilities_cents == 0
    assert (
        report.opening_capital_cents
        + report.external_flow_cents
        + report.economic_pnl_cents
        == report.closing_assets_cents - report.liabilities_cents
    )
    assert report.reserved_cash_cents == 0


def test_conservation_detects_tampered_cash(repository: CapitalRepository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    with repository.engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE capital_projection SET available_cash_cents ="
                " available_cash_cents + 1"
            )
        )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.assert_conservation()
    assert excinfo.value.code == "conservation_violation"
    assert "cash" in str(excinfo.value)


def test_conservation_detects_tampered_position_quantity(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    with repository.engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE positions SET settled_quantity_units ="
                " settled_quantity_units + 10"
            )
        )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.assert_conservation()
    assert excinfo.value.code == "conservation_violation"


def test_conservation_detects_tampered_reserve(repository: CapitalRepository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(reserve_request("src-1", 400_000, repository))
    with repository.engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE reserves SET reserved_entry_gross_cents ="
                " reserved_entry_gross_cents + 1"
            )
        )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.assert_conservation()
    assert excinfo.value.code == "conservation_violation"


def test_conservation_detects_orphan_fee_event(repository: CapitalRepository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-1", repository=repository, quantity=100, step=1)
    )
    repository.record_fee_revision(fee_request("exec-1", repository, step=2))
    # Tamper with the append-only registry from outside the kernel to prove
    # the cross-check catches registry/event drift.
    with repository.engine.connect() as conn:
        conn.exec_driver_sql("DROP TRIGGER IF EXISTS no_delete_execution_revisions")
    try:
        with repository.engine.begin() as conn:
            conn.execute(
                sa.text(
                    "DELETE FROM execution_revisions WHERE revision_kind = 'FEE'"
                )
            )
    finally:
        with repository.engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TRIGGER IF NOT EXISTS no_delete_execution_revisions"
                " BEFORE DELETE ON execution_revisions"
                " BEGIN SELECT RAISE(ABORT, 'immutable table: execution_revisions"
                " rejects DELETE'); END;"
            )
    with pytest.raises(CapitalConflict) as excinfo:
        repository.assert_conservation()
    assert excinfo.value.code == "conservation_violation"


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


@dataclass
class LedgerModel:
    """Pure-python mirror of the kernel projections for property tests."""

    available: int = 0
    restricted: int = 0
    stream_version: int = 0
    capital_version: int = 0
    reserves: dict = field(default_factory=dict)
    lots: dict = field(default_factory=dict)
    fills_by_order: dict = field(default_factory=dict)
    fee_charged: dict = field(default_factory=dict)
    fees_recorded: set = field(default_factory=set)
    lot_by_order: dict = field(default_factory=dict)
    exited_lots: set = field(default_factory=set)


@dataclass(frozen=True)
class ModelOp:
    kind: str
    params: dict


def _commission_base_cents(notional_cents: int, policy: FeePolicy) -> int:
    return round_half_even_div(notional_cents * policy.commission_rate_ppm, 1_000_000)


def model_fee_charge(
    model: LedgerModel, order_id: str, fill_execution_id: str, policy: FeePolicy
) -> tuple[int, int]:
    """Expected ``(total, commission)`` for the next fee revision of a fill.

    Mirrors the kernel exactly: the commission delta is owed against the
    cumulative commission actually charged by the order's earlier fee
    revisions (``max(minimum, cumulative base) - charged``), plus the fill's
    own stamp tax and transfer fee.
    """

    fills = model.fills_by_order[order_id]
    fill = next(
        item for item in fills if item["execution_id"] == fill_execution_id
    )
    base_now = sum(
        _commission_base_cents(item["notional"], policy) for item in fills
    )
    charged_before = model.fee_charged.get(order_id, 0)
    commission = max(
        0, max(policy.min_commission_cents, base_now) - charged_before
    )
    stamp = (
        round_half_even_div(fill["notional"] * policy.stamp_tax_rate_ppm, 1_000_000)
        if fill["side"] is ExecutionSide.EXIT
        else 0
    )
    transfer = round_half_even_div(
        fill["notional"] * policy.transfer_fee_rate_ppm, 1_000_000
    )
    return commission + stamp + transfer, commission


def _model_fee_total(order_fills: list[tuple[int, ExecutionSide]]) -> int:
    """Cross-check helper: cumulative order fee under POLICY_V1."""

    model = LedgerModel()
    order_id = "ord-check"
    total = 0
    for index, (notional, side) in enumerate(order_fills):
        execution_id = f"check-{index}"
        model.fills_by_order.setdefault(order_id, []).append(
            {"execution_id": execution_id, "notional": notional, "side": side}
        )
        charge, commission = model_fee_charge(
            model, order_id, execution_id, POLICY_V1
        )
        model.fee_charged[order_id] = (
            model.fee_charged.get(order_id, 0) + commission
        )
        total += charge
    return total


@st.composite
def capital_operation_sequences(draw) -> list[ModelOp]:
    """Interleaved valid entry/exit/fill/fee/reserve sequences.

    The model decides validity before each draw, so every generated sequence
    is executable and shrinking drops operations from the tail.
    """

    model = LedgerModel()
    ops: list[ModelOp] = []
    steps = draw(st.integers(min_value=4, max_value=14))

    for _ in range(steps):
        actions: list[tuple[str, dict]] = [("deposit", {})]

        if model.available > 0:
            actions.append(
                ("reserve_entry", {"max_cents": min(model.available, 5_000_000)})
            )

        for source, reserve in sorted(model.reserves.items()):
            if reserve["state"] is CapitalReserveState.LIVE:
                actions.append(("cancel_request", {"source_id": source}))
                actions.append(("confirm_cancel", {"source_id": source}))
                actions.append(("ambiguous_release", {"source_id": source}))
            elif reserve["state"] is CapitalReserveState.CANCEL_PENDING:
                actions.append(("confirm_cancel", {"source_id": source}))

        for source, reserve in sorted(model.reserves.items()):
            if reserve["state"] in (
                CapitalReserveState.LIVE,
                CapitalReserveState.CANCEL_PENDING,
            ):
                cap = model.available + reserve["cents"]
                if cap >= 1:
                    actions.append(
                        ("entry_fill", {"reserve_source_id": source, "cap": cap})
                    )
        if model.available >= 1:
            actions.append(
                ("entry_fill", {"reserve_source_id": None, "cap": model.available})
            )
            actions.append(("unattributed_fill", {"cap": model.available}))

        # Partial fills of an EXISTING order exercise the per-order minimum
        # commission accumulation in the property test. Lots that already saw
        # an exit are exiting (entries into them are rejected by the kernel).
        for order_id, key in sorted(model.lot_by_order.items()):
            if key in model.exited_lots:
                continue
            position = model.lots.get(key)
            if position is not None and model.available >= 1:
                actions.append(
                    (
                        "extend_fill",
                        {
                            "order_id": order_id,
                            "lineage": key[0],
                            "lot": key[1],
                            "cap": model.available,
                        },
                    )
                )

        for (lineage, lot), position in sorted(model.lots.items()):
            if position["qty"] > 0:
                actions.append(
                    (
                        "exit_fill",
                        {
                            "lineage": lineage,
                            "lot": lot,
                            "max_qty": position["qty"],
                        },
                    )
                )

        for order_id, fills in sorted(model.fills_by_order.items()):
            for fill in fills:
                if fill["execution_id"] not in model.fees_recorded:
                    charge, _commission = model_fee_charge(
                        model, order_id, fill["execution_id"], POLICY_V1
                    )
                    # The kernel rejects fees it cannot pay; only offer
                    # fee revisions the model cash can cover.
                    if charge <= model.available:
                        actions.append(
                            ("fee", {"fill_execution_id": fill["execution_id"]})
                        )

        name, params = draw(st.sampled_from(actions))

        if name == "deposit":
            cents = draw(st.integers(min_value=1, max_value=5_000_000))
            model.available += cents
            model.stream_version += 2
            model.capital_version += 2
            ops.append(
                ModelOp("deposit", {"cents": cents, "sequence": len(ops) + 1})
            )
            continue

        if name == "reserve_entry":
            cents = draw(st.integers(min_value=1, max_value=params["max_cents"]))
            source_id = f"src-{len(ops)}"
            model.reserves[source_id] = {
                "cents": cents,
                "state": CapitalReserveState.LIVE,
            }
            model.available -= cents
            model.restricted += cents
            model.capital_version += 1
            ops.append(
                ModelOp("reserve_entry", {"source_id": source_id, "cents": cents})
            )
            continue

        if name == "cancel_request":
            model.reserves[params["source_id"]]["state"] = (
                CapitalReserveState.CANCEL_PENDING
            )
            model.capital_version += 1
            ops.append(ModelOp("cancel_request", dict(params)))
            continue

        if name == "confirm_cancel":
            reserve = model.reserves[params["source_id"]]
            reserve["state"] = CapitalReserveState.RELEASED
            model.restricted -= reserve["cents"]
            model.available += reserve["cents"]
            model.capital_version += 1
            ops.append(ModelOp("confirm_cancel", dict(params)))
            continue

        if name == "ambiguous_release":
            ops.append(ModelOp("ambiguous_release", dict(params)))
            continue

        if name in ("entry_fill", "unattributed_fill"):
            cap = params["cap"]
            quantity = draw(st.integers(min_value=1, max_value=500))
            max_price = max(1, (cap * 10_000) // quantity)
            min_price = 5_000 // quantity + 1
            if max_price < min_price:
                continue
            price_micros = draw(
                st.integers(min_value=min_price, max_value=max_price)
            )
            gross = fill_gross_cents(price_micros, quantity)
            if gross < 1 or gross > cap:
                continue
            reserve_source = params.get("reserve_source_id")
            execution_id = f"exec-{len(ops)}"
            order_id = f"ord-{len(ops)}"
            if name == "unattributed_fill":
                lineage = f"unattributed:{execution_id}"
                lot = lineage
            else:
                lineage = f"lin-{len(ops)}"
                lot = f"lot-{len(ops)}"
            if reserve_source is not None:
                reserve = model.reserves[reserve_source]
                model.restricted -= reserve["cents"]
                model.available += reserve["cents"] - gross
                reserve["state"] = CapitalReserveState.CONSUMED
            else:
                model.available -= gross
            model.lots[(lineage, lot)] = {"qty": quantity, "basis": gross}
            if name == "entry_fill":
                model.lot_by_order[order_id] = (lineage, lot)
            model.stream_version += 1
            model.capital_version += 1
            model.fills_by_order.setdefault(order_id, []).append(
                {
                    "execution_id": execution_id,
                    "notional": gross,
                    "side": ExecutionSide.ENTRY,
                }
            )
            ops.append(
                ModelOp(
                    name,
                    {
                        "execution_id": execution_id,
                        "order_id": order_id,
                        "price_micros": price_micros,
                        "quantity": quantity,
                        "gross": gross,
                        "reserve_source_id": reserve_source,
                        "lineage": lineage,
                        "lot": lot,
                    },
                )
            )
            continue

        if name == "extend_fill":
            cap = params["cap"]
            quantity = draw(st.integers(min_value=1, max_value=500))
            max_price = max(1, (cap * 10_000) // quantity)
            min_price = 5_000 // quantity + 1
            if max_price < min_price:
                continue
            price_micros = draw(
                st.integers(min_value=min_price, max_value=max_price)
            )
            gross = fill_gross_cents(price_micros, quantity)
            if gross < 1 or gross > cap:
                continue
            execution_id = f"exec-{len(ops)}"
            model.available -= gross
            position = model.lots[(params["lineage"], params["lot"])]
            position["qty"] += quantity
            position["basis"] += gross
            model.stream_version += 1
            model.capital_version += 1
            model.fills_by_order[params["order_id"]].append(
                {
                    "execution_id": execution_id,
                    "notional": gross,
                    "side": ExecutionSide.ENTRY,
                }
            )
            ops.append(
                ModelOp(
                    "extend_fill",
                    {
                        "execution_id": execution_id,
                        "order_id": params["order_id"],
                        "price_micros": price_micros,
                        "quantity": quantity,
                        "gross": gross,
                        "lineage": params["lineage"],
                        "lot": params["lot"],
                    },
                )
            )
            continue

        if name == "exit_fill":
            position = model.lots[(params["lineage"], params["lot"])]
            quantity = draw(st.integers(min_value=1, max_value=params["max_qty"]))
            price_micros = draw(st.integers(min_value=1, max_value=50_000_000))
            gross = fill_gross_cents(price_micros, quantity)
            if gross < 1:
                continue
            before_qty = position["qty"]
            consumed = (
                position["basis"]
                if quantity == before_qty
                else round_half_even_div(position["basis"] * quantity, before_qty)
            )
            position["basis"] -= consumed
            position["qty"] -= quantity
            model.exited_lots.add((params["lineage"], params["lot"]))
            model.available += gross
            model.stream_version += 1
            model.capital_version += 1
            execution_id = f"exec-{len(ops)}"
            order_id = f"ord-{len(ops)}"
            model.fills_by_order.setdefault(order_id, []).append(
                {
                    "execution_id": execution_id,
                    "notional": gross,
                    "side": ExecutionSide.EXIT,
                }
            )
            ops.append(
                ModelOp(
                    "exit_fill",
                    {
                        "execution_id": execution_id,
                        "order_id": order_id,
                        "price_micros": price_micros,
                        "quantity": quantity,
                        "gross": gross,
                        "lineage": params["lineage"],
                        "lot": params["lot"],
                    },
                )
            )
            continue

        if name == "fee":
            fill_execution_id = params["fill_execution_id"]
            target_order = next(
                order_id
                for order_id, fills in model.fills_by_order.items()
                if any(
                    item["execution_id"] == fill_execution_id for item in fills
                )
            )
            charge, commission = model_fee_charge(
                model, target_order, fill_execution_id, POLICY_V1
            )
            model.fees_recorded.add(fill_execution_id)
            model.fee_charged[target_order] = (
                model.fee_charged.get(target_order, 0) + commission
            )
            if charge > 0:
                model.stream_version += 1
                model.available -= charge
                model.capital_version += 1
            ops.append(
                ModelOp(
                    "fee",
                    {
                        "fill_execution_id": fill_execution_id,
                        "expected_total": charge,
                        "expected_commission": commission,
                        "order_id": target_order,
                    },
                )
            )

    return ops


def replay_ops(
    repository: CapitalRepository,
    ops: list[ModelOp],
    *,
    fills_and_fees_only: bool = False,
) -> None:
    step = 0
    for op in ops:
        step += 1
        if fills_and_fees_only and op.kind not in (
            "entry_fill",
            "unattributed_fill",
            "extend_fill",
            "exit_fill",
            "fee",
        ):
            continue
        if op.kind == "deposit":
            deposit(repository, op.params["cents"], op.params["sequence"])
        elif op.kind == "reserve_entry":
            repository.reserve_entry(
                reserve_request(
                    op.params["source_id"], op.params["cents"], repository, step=step
                )
            )
        elif op.kind == "cancel_request":
            repository.release_reserve(
                release_request(
                    op.params["source_id"],
                    ReserveReleaseReason.CANCEL_REQUESTED,
                    repository,
                    step=step,
                )
            )
        elif op.kind == "confirm_cancel":
            repository.release_reserve(
                release_request(
                    op.params["source_id"],
                    ReserveReleaseReason.CANCEL_CONFIRMED,
                    repository,
                    step=step,
                )
            )
        elif op.kind == "ambiguous_release":
            with pytest.raises(CapitalConflict) as excinfo:
                repository.release_reserve(
                    release_request(
                        op.params["source_id"],
                        ReserveReleaseReason.SUBMISSION_AMBIGUOUS,
                        repository,
                        step=step,
                    )
                )
            assert excinfo.value.code == "submission_ambiguous_worst_case_retained"
        elif op.kind in ("entry_fill", "unattributed_fill"):
            attributed = op.kind == "entry_fill"
            repository.record_fill_revision(
                fill_request(
                    op.params["execution_id"],
                    order_id=op.params["order_id"],
                    price_micros=op.params["price_micros"],
                    quantity=op.params["quantity"],
                    attribution=ATTRIBUTION if attributed else None,
                    position_lineage_id=op.params["lineage"] if attributed else None,
                    economic_lot_id=op.params["lot"] if attributed else None,
                    reserve_source_id=op.params["reserve_source_id"],
                    step=step,
                    repository=repository,
                )
            )
        elif op.kind == "extend_fill":
            repository.record_fill_revision(
                fill_request(
                    op.params["execution_id"],
                    order_id=op.params["order_id"],
                    price_micros=op.params["price_micros"],
                    quantity=op.params["quantity"],
                    position_lineage_id=op.params["lineage"],
                    economic_lot_id=op.params["lot"],
                    step=step,
                    repository=repository,
                )
            )
        elif op.kind == "exit_fill":
            repository.record_fill_revision(
                fill_request(
                    op.params["execution_id"],
                    order_id=op.params["order_id"],
                    side=ExecutionSide.EXIT,
                    price_micros=op.params["price_micros"],
                    quantity=op.params["quantity"],
                    position_lineage_id=op.params["lineage"],
                    economic_lot_id=op.params["lot"],
                    step=step,
                    repository=repository,
                )
            )
        elif op.kind == "fee":
            receipt, _ = repository.record_fee_revision(
                fee_request(op.params["fill_execution_id"], repository, step=step)
            )
            assert receipt.total_cents == op.params["expected_total"]


def assert_model_agreement(repository: CapitalRepository, model: LedgerModel) -> None:
    snapshot = repository.capital_risk_snapshot(_moment(99))
    assert snapshot.available_cash_cents == model.available
    assert snapshot.restricted_cash_cents == model.restricted
    expected_reserved = sum(
        reserve["cents"]
        for reserve in model.reserves.values()
        if reserve["state"]
        in (CapitalReserveState.LIVE, CapitalReserveState.CANCEL_PENDING)
    )
    assert snapshot.reserved_cash_cents == expected_reserved
    assert repository.stream_version() == model.stream_version
    assert repository.capital_version() == model.capital_version

    visible = {
        (position.position_lineage_id, position.economic_lot_id): position
        for position in snapshot.positions
    }
    expected_visible = {
        key: position
        for key, position in model.lots.items()
        if position["qty"] > 0
    }
    assert set(visible) == set(expected_visible)
    for key, expected in expected_visible.items():
        assert visible[key].settled_quantity == expected["qty"]

    sentinel_basis = sum(
        position["basis"]
        for (lineage, _), position in model.lots.items()
        if lineage.startswith("unattributed:")
    )
    # The latch keys on any remaining sentinel quantity OR basis: rounding
    # can consume a sentinel's whole basis while shares remain.
    sentinel_exposure = any(
        position["qty"] > 0 or position["basis"] > 0
        for (lineage, _), position in model.lots.items()
        if lineage.startswith("unattributed:")
    )
    assert snapshot.unattributed_risk_cents == sentinel_basis
    if sentinel_exposure:
        assert (
            snapshot.reconciliation_latch
            is ReconciliationLatchState.RECONCILIATION_HALT
        )
    else:
        assert snapshot.reconciliation_latch is ReconciliationLatchState.CLEAR

    repository.assert_conservation()


def _property_repository(tmp_path: Path) -> CapitalRepository:
    # hypothesis examples share one function-scoped tmp_path; isolate each
    # example ledger in its own subdirectory (never under data/).
    return CapitalRepository.initialize(
        tmp_path / f"capital-{uuid.uuid4().hex}.sqlite3"
    )


@settings(
    deadline=None,
    max_examples=30,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(data=st.data())
def test_property_interleaved_sequences_conserve(data, tmp_path: Path) -> None:
    ops = data.draw(capital_operation_sequences())
    repository = _property_repository(tmp_path)
    replay_ops(repository, ops)

    model = LedgerModel()
    rebuild_model(model, ops)
    assert_model_agreement(repository, model)


@settings(
    deadline=None,
    max_examples=12,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(data=st.data())
def test_property_duplicate_fill_and_fee_revisions_are_idempotent(
    data, tmp_path: Path
) -> None:
    ops = data.draw(capital_operation_sequences())
    repository = _property_repository(tmp_path)
    replay_ops(repository, ops)
    # Every broker fill/fee report may be delivered twice: state converges.
    replay_ops(repository, ops, fills_and_fees_only=True)

    model = LedgerModel()
    rebuild_model(model, ops)
    assert_model_agreement(repository, model)


def rebuild_model(model: LedgerModel, ops: list[ModelOp]) -> None:
    """Replay the model effects of ops onto a fresh LedgerModel."""

    for op in ops:
        if op.kind == "deposit":
            model.available += op.params["cents"]
            model.stream_version += 2
            model.capital_version += 2
        elif op.kind == "reserve_entry":
            model.reserves[op.params["source_id"]] = {
                "cents": op.params["cents"],
                "state": CapitalReserveState.LIVE,
            }
            model.available -= op.params["cents"]
            model.restricted += op.params["cents"]
            model.capital_version += 1
        elif op.kind == "cancel_request":
            model.reserves[op.params["source_id"]]["state"] = (
                CapitalReserveState.CANCEL_PENDING
            )
            model.capital_version += 1
        elif op.kind == "confirm_cancel":
            reserve = model.reserves[op.params["source_id"]]
            reserve["state"] = CapitalReserveState.RELEASED
            model.restricted -= reserve["cents"]
            model.available += reserve["cents"]
            model.capital_version += 1
        elif op.kind in ("entry_fill", "unattributed_fill"):
            reserve_source = op.params["reserve_source_id"]
            if reserve_source is not None:
                reserve = model.reserves[reserve_source]
                model.restricted -= reserve["cents"]
                model.available += reserve["cents"] - op.params["gross"]
                reserve["state"] = CapitalReserveState.CONSUMED
            else:
                model.available -= op.params["gross"]
            model.lots[(op.params["lineage"], op.params["lot"])] = {
                "qty": op.params["quantity"],
                "basis": op.params["gross"],
            }
            if op.kind == "entry_fill":
                model.lot_by_order[op.params["order_id"]] = (
                    op.params["lineage"],
                    op.params["lot"],
                )
            model.stream_version += 1
            model.capital_version += 1
        elif op.kind == "extend_fill":
            model.available -= op.params["gross"]
            position = model.lots[(op.params["lineage"], op.params["lot"])]
            position["qty"] += op.params["quantity"]
            position["basis"] += op.params["gross"]
            model.stream_version += 1
            model.capital_version += 1
        elif op.kind == "exit_fill":
            position = model.lots[(op.params["lineage"], op.params["lot"])]
            quantity = op.params["quantity"]
            before_qty = position["qty"]
            consumed = (
                position["basis"]
                if quantity == before_qty
                else round_half_even_div(position["basis"] * quantity, before_qty)
            )
            position["basis"] -= consumed
            position["qty"] -= quantity
            model.exited_lots.add((op.params["lineage"], op.params["lot"]))
            model.available += op.params["gross"]
            model.stream_version += 1
            model.capital_version += 1
        elif op.kind == "fee":
            model.fee_charged[op.params["order_id"]] = (
                model.fee_charged.get(op.params["order_id"], 0)
                + op.params["expected_commission"]
            )
            if op.params["expected_total"] > 0:
                model.stream_version += 1
                model.available -= op.params["expected_total"]
                model.capital_version += 1


def test_model_fee_total_helper_matches_manual_accounting() -> None:
    # One order: two small buys (minimum dominates) then a large buy.
    fills = [
        (100_000, ExecutionSide.ENTRY),
        (100_000, ExecutionSide.ENTRY),
        (10_000_000, ExecutionSide.ENTRY),
    ]
    bases = [300, 300, 30_000]
    assert _model_fee_total(fills) == (
        max(500, bases[0])
        + max(0, max(500, bases[0] + bases[1]) - max(500, bases[0]))
        + max(0, max(500, sum(bases)) - max(500, bases[0] + bases[1]))
        + 2 + 2 + 200  # transfer fees
    )
    # Exit-only order: stamp tax applies.
    exit_fills = [(110_000, ExecutionSide.EXIT)]
    assert _model_fee_total(exit_fills) == 500 + 110 + 2
