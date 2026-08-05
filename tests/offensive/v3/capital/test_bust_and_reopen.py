"""Plan 02 Task 6: execution bust/correction, reopen, and negative halt.

Broker busts and corrections append linked revisions even for terminal
orders; capital is re-projected from the append-only history and never
patched in place. Negative positions are a reconciliation halt (preserved,
never clamped), and a correction that makes a flat/emptied lot reappear
recreates the real exposure with a durable reopened exit obligation that
Plan 04's ExitMandate projection consumes.

Covered here:

- fill -> exit -> closed -> bust (both entry and exit busts);
- corrected quantity/price/fee with exact revision linkage;
- duplicate / out-of-order / unknown revisions;
- cancel-late-fill bust under sentinel attribution;
- corrections that would create negative shares (halt, never clamp);
- entry tombstones (invalidated entries) and reopen on reappearing lots;
- stage-loss monotonicity under corrections;
- conservation through arbitrary interleaved bust/correction/reopen
  sequences (Hypothesis property test).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.screening.offensive.v3.capital.execution_revisions import (
    ExecutionRevisionFact,
    ExecutionRevisionReceipt,
    ExecutionRevisionRequest,
    ReopenedEconomicLot,
)
from src.screening.offensive.v3.capital.fees import FeePolicy, FeeRevisionKind
from src.screening.offensive.v3.capital.fills import (
    FeeRevisionRequest,
    FillAttribution,
    FillRevisionRequest,
)
from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalCommand,
    CapitalCommandPayload,
    CapitalConflict,
    CapitalRepository,
)
from src.screening.offensive.v3.capital.reserves import (
    ReserveEntryRequest,
    ReserveReleaseReason,
    ReserveReleaseRequest,
)
from src.screening.offensive.v3.capital.rounding import round_half_even_div
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
    RiskSnapshotCompleteness,
)


T0 = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)
ENVIRONMENT_FINGERPRINT = "cd" * 32

POLICY = FeePolicy(
    fee_policy_version="fee-schedule-2026-v1",
    commission_rate_ppm=3_000,
    min_commission_cents=500,
    stamp_tax_rate_ppm=1_000,
    transfer_fee_rate_ppm=20,
)

ATTRIBUTION = FillAttribution(
    producer_namespace="btst",
    research_program_id="prog-1",
    economic_lineage_id="eline-1",
    stage_id="stage-1",
)


def binding() -> AccountBinding:
    return AccountBinding(
        portfolio_id="pf-bust",
        mode=ExecutionMode.BROKER_CONFIRMED,
        broker_account_id="acct-bust",
        base_currency="CNY",
        environment_fingerprint=ENVIRONMENT_FINGERPRINT,
    )


@pytest.fixture()
def repository(tmp_path: Path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "capital.sqlite3")


def _moment(step: int) -> datetime:
    return T0 + timedelta(minutes=step)


def deposit(repository: CapitalRepository, cents: int, sequence: int) -> None:
    """Seed cash with the pre-genesis receivable/settlement pair."""

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
    repository: CapitalRepository,
    *,
    order_id: str = "ord-1",
    side: ExecutionSide = ExecutionSide.ENTRY,
    security_id: str = "600000.SH",
    price_micros: int = 10_000_000,
    quantity: int = 100,
    attribution: FillAttribution | None = ATTRIBUTION,
    position_lineage_id: str | None = "lin-1",
    economic_lot_id: str | None = "lot-1",
    step: int = 0,
) -> FillRevisionRequest:
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
        source_authority="broker.test",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
    )


def bust_request(
    execution_id: str,
    repository: CapitalRepository,
    *,
    revision: int = 2,
    order_id: str = "ord-1",
    side: ExecutionSide = ExecutionSide.ENTRY,
    security_id: str = "600000.SH",
    position_lineage_id: str | None = "lin-1",
    economic_lot_id: str | None = "lot-1",
    superseded_quantity: int | None = 100,
    step: int = 0,
) -> ExecutionRevisionRequest:
    return ExecutionRevisionRequest(
        execution_id=execution_id,
        revision=revision,
        revision_kind=ExecutionRevisionKind.BUSTED,
        order_id=order_id,
        side=side,
        security_id=security_id,
        position_lineage_id=position_lineage_id,
        economic_lot_id=economic_lot_id,
        superseded_quantity=superseded_quantity,
        source_authority="broker.test",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
    )


def correction_request(
    execution_id: str,
    repository: CapitalRepository,
    *,
    revision: int = 2,
    order_id: str = "ord-1",
    side: ExecutionSide = ExecutionSide.ENTRY,
    security_id: str = "600000.SH",
    position_lineage_id: str | None = "lin-1",
    economic_lot_id: str | None = "lot-1",
    superseded_quantity: int | None = 100,
    corrected_price_micros: int = 9_000_000,
    corrected_quantity: int = 90,
    step: int = 0,
) -> ExecutionRevisionRequest:
    return ExecutionRevisionRequest(
        execution_id=execution_id,
        revision=revision,
        revision_kind=ExecutionRevisionKind.CORRECTED,
        order_id=order_id,
        side=side,
        security_id=security_id,
        position_lineage_id=position_lineage_id,
        economic_lot_id=economic_lot_id,
        superseded_quantity=superseded_quantity,
        corrected_price_micros=corrected_price_micros,
        corrected_quantity=corrected_quantity,
        source_authority="broker.test",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
    )


def fee_request(
    fill_execution_id: str,
    repository: CapitalRepository,
    *,
    revision: int = 1,
    revision_kind: FeeRevisionKind = FeeRevisionKind.INITIAL,
    step: int = 0,
) -> FeeRevisionRequest:
    return FeeRevisionRequest(
        fill_execution_id=fill_execution_id,
        revision=revision,
        revision_kind=revision_kind,
        fee_policy=POLICY,
        source_authority="broker.test",
        effective_at=_moment(step),
        as_of=_moment(step) + timedelta(seconds=1),
        expected_stream_version=repository.stream_version(),
    )


def _position_row(repository: CapitalRepository, lot: str = "lot-1"):
    with repository.engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT * FROM positions WHERE economic_lot_id = :lot"
            ),
            {"lot": lot},
        ).first()


def _registry_rows(repository: CapitalRepository, execution_id: str):
    with repository.engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT * FROM execution_revisions"
                " WHERE execution_id = :execution_id ORDER BY revision"
            ),
            {"execution_id": execution_id},
        ).all()


def _tombstone_rows(repository: CapitalRepository):
    with repository.engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT * FROM entry_tombstones ORDER BY entry_identity")
        ).all()


def _open_lots(repository: CapitalRepository) -> dict[tuple[str, str], int]:
    snapshot = repository.capital_risk_snapshot(_moment(500))
    return {
        (position.position_lineage_id, position.economic_lot_id): (
            position.settled_quantity
        )
        for position in snapshot.positions
    }


# ---------------------------------------------------------------------------
# Entry bust after a terminal lot: append-only revision, negative halt
# ---------------------------------------------------------------------------


def test_entry_bust_after_closed_lot_reverses_legs_and_halts(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    entry_receipt, _ = repository.record_fill_revision(
        fill_request("exec-e", repository, step=1)
    )
    repository.record_fill_revision(
        fill_request(
            "exec-x",
            repository,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            price_micros=11_000_000,
            quantity=100,
            step=2,
        )
    )
    closed = _position_row(repository)
    assert closed.state == PositionState.CLOSED.value
    assert closed.settled_quantity_units == 0

    stream_before = repository.stream_version()
    receipt, snapshot = repository.record_execution_revision(
        bust_request(
            "exec-e",
            repository,
            side=ExecutionSide.ENTRY,
            step=3,
        )
    )

    # The bust appended a revision even though the order history is terminal.
    assert isinstance(receipt, ExecutionRevisionReceipt)
    assert receipt.revision == 2
    assert receipt.revision_kind is ExecutionRevisionKind.BUSTED
    assert receipt.reversed_gross_cents == 100_000
    assert receipt.reversed_quantity == 100
    assert receipt.applied_quantity == 0
    assert receipt.reopened is False
    assert receipt.reconciliation_halted is True
    assert repository.stream_version() == stream_before + 1

    # The original fill fact is preserved untouched; the revision links it.
    rows = _registry_rows(repository, "exec-e")
    assert [row.revision for row in rows] == [1, 2]
    assert rows[0].revision_kind == "FILL"
    assert rows[1].revision_kind == "FILL_BUST"
    with repository.engine.connect() as conn:
        links = conn.execute(
            sa.text(
                "SELECT canonical_event_id, revision_event_id, revision_kind"
                " FROM event_revisions"
            )
        ).all()
    assert len(links) == 1
    assert links[0].canonical_event_id == entry_receipt.event_id
    assert links[0].revision_event_id == receipt.event_id
    assert links[0].revision_kind == "EXECUTION_REVISION"

    # Negative position is preserved exactly: never clamped, never dropped.
    row = _position_row(repository)
    assert row.settled_quantity_units == -100
    assert row.tradable_quantity_units == -100
    assert row.cost_basis_cents == -100_000
    discrepancies = repository.reconciliation_discrepancies()
    assert len(discrepancies) == 1
    assert discrepancies[0].economic_lot_id == "lot-1"
    assert discrepancies[0].settled_quantity_units == -100

    # Cash leg reversed exactly: the entry's 1000.00 yuan returned.
    assert snapshot.available_cash_cents == 1_000_000 - 100_000 + 110_000 + 100_000
    assert snapshot.reconciliation_latch is (
        ReconciliationLatchState.RECONCILIATION_HALT
    )
    # The frozen snapshot contract cannot carry negative quantities: the
    # discrepancy stays in the ledger and the snapshot fails closed as
    # INCOMPLETE instead of silently representing it.
    assert snapshot.completeness is RiskSnapshotCompleteness.INCOMPLETE
    assert snapshot.positions == ()

    report = repository.assert_conservation()
    # Busted entry removed from both sides of the realized identity.
    assert report.entry_gross_cents == 0
    assert report.exit_gross_cents == 110_000
    assert report.consumed_cost_basis_cents == 0


def test_entry_bust_on_open_lot_flattens_and_tombstones_entry(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(fill_request("exec-e", repository, step=1))
    receipt, snapshot = repository.record_execution_revision(
        bust_request("exec-e", repository, step=2)
    )
    assert receipt.reconciliation_halted is False
    assert receipt.reopened is False

    row = _position_row(repository)
    assert row.settled_quantity_units == 0
    assert row.state == PositionState.CLOSED.value
    assert snapshot.available_cash_cents == 1_000_000
    assert snapshot.completeness is RiskSnapshotCompleteness.COMPLETE
    assert snapshot.reconciliation_latch is ReconciliationLatchState.CLEAR

    # The flattened entry identity is tombstoned in the same transaction:
    # Plan 04 must never silently revive it.
    tombstones = _tombstone_rows(repository)
    assert len(tombstones) == 1
    assert tombstones[0].entry_identity == "lot:lin-1:lot-1"
    assert tombstones[0].tombstone_reason == "EXECUTION_BUSTED"
    assert tombstones[0].capital_version == repository.capital_version()

    # The tombstone is append-only audit: a re-bust diverges (nothing left).
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_execution_revision(
            bust_request("exec-e", repository, revision=3, step=3)
        )
    assert excinfo.value.code == "revision_active_fact_missing"
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Exit bust: the closed lot reappears and the exit obligation reopens
# ---------------------------------------------------------------------------


def test_exit_bust_reopens_position_and_exit_obligation(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-e", repository, price_micros=10_000_000, quantity=100, step=1)
    )
    repository.record_fill_revision(
        fill_request(
            "exec-x",
            repository,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            price_micros=11_000_000,
            quantity=100,
            step=2,
        )
    )
    assert _position_row(repository).state == PositionState.CLOSED.value

    receipt, snapshot = repository.record_execution_revision(
        bust_request(
            "exec-x",
            repository,
            revision=2,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            step=3,
        )
    )
    assert receipt.revision_kind is ExecutionRevisionKind.BUSTED
    assert receipt.reversed_gross_cents == 110_000
    assert receipt.reversed_quantity == 100
    # Exit bust consumed basis is refunded exactly (the whole-lot remainder).
    assert receipt.reversed_consumed_basis_cents == 100_000
    assert receipt.reopened is True
    assert receipt.reconciliation_halted is False

    # The lot is live again with its original basis restored.
    row = _position_row(repository)
    assert row.settled_quantity_units == 100
    assert row.cost_basis_cents == 100_000
    assert row.state == PositionState.EXIT_PENDING.value

    # Cash reversal exact: the exit proceeds leave again.
    assert snapshot.available_cash_cents == 1_000_000 - 100_000
    assert snapshot.completeness is RiskSnapshotCompleteness.COMPLETE
    assert _open_lots(repository) == {("lin-1", "lot-1"): 100}

    # Durable reopen state for Plan 04's ExitMandate projection: the stable
    # lot identity, its attribution, and the REOPENED_BY_CORRECTION kind.
    reopens = repository.reopen_exit_obligations()
    assert len(reopens) == 1
    reopen = reopens[0]
    assert isinstance(reopen, ReopenedEconomicLot)
    assert reopen.position_lineage_id == "lin-1"
    assert reopen.economic_lot_id == "lot-1"
    assert reopen.security_id == "600000.SH"
    assert reopen.reopened_quantity_units == 100
    assert reopen.position_state is PositionState.EXIT_PENDING
    assert reopen.reopened_by_execution_revision_id == (
        "fill:exec-x:2"
    )
    assert reopen.reopened_by_event_id == receipt.event_id
    # Revision 1 belongs to INITIAL mandates only: a reopen starts at >= 2.
    assert reopen.mandate_revision_floor == 2
    assert reopen.research_program_id == "prog-1"

    report = repository.assert_conservation()
    assert report.exit_gross_cents == 0
    assert report.consumed_cost_basis_cents == 0
    assert report.closing_cost_basis_cents == 100_000


# ---------------------------------------------------------------------------
# Corrections: quantity/price replaced through linked revisions only
# ---------------------------------------------------------------------------


def test_correction_replaces_price_and_quantity_preserving_original(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    entry_receipt, _ = repository.record_fill_revision(
        fill_request("exec-e", repository, price_micros=10_000_000, quantity=100, step=1)
    )

    receipt, snapshot = repository.record_execution_correction(
        correction_request(
            "exec-e",
            repository,
            corrected_price_micros=9_000_000,
            corrected_quantity=90,
            step=2,
        )
    )
    assert receipt.revision_kind is ExecutionRevisionKind.CORRECTED
    assert receipt.reversed_gross_cents == 100_000
    assert receipt.reversed_quantity == 100
    assert receipt.applied_gross_cents == 81_000
    assert receipt.applied_quantity == 90
    assert receipt.reopened is False

    row = _position_row(repository)
    assert row.settled_quantity_units == 90
    assert row.cost_basis_cents == 81_000
    assert row.state == PositionState.OPEN.value
    assert snapshot.available_cash_cents == 1_000_000 - 81_000

    # The correction is one canonical event superseding the recorded fact.
    with repository.engine.connect() as conn:
        event = conn.execute(
            sa.text(
                "SELECT correction_of_event_id, event_kind FROM economic_events"
                " WHERE economic_event_id = :event_id"
            ),
            {"event_id": receipt.event_id},
        ).one()
        original = conn.execute(
            sa.text(
                "SELECT payload_content_hash FROM economic_events"
                " WHERE economic_event_id = :event_id"
            ),
            {"event_id": entry_receipt.event_id},
        ).one()
    assert event.correction_of_event_id == entry_receipt.event_id
    assert event.event_kind == EconomicEventKind.LATE_CORRECTION.value
    # Original registry fact still points at the unchanged original event.
    assert _registry_rows(repository, "exec-e")[0].payload_content_hash == (
        original.payload_content_hash
    )
    repository.assert_conservation()


def test_correction_after_bust_recreates_exposure_from_tombstone(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(fill_request("exec-e", repository, step=1))
    repository.record_execution_revision(
        bust_request("exec-e", repository, step=2)
    )
    tombstones = _tombstone_rows(repository)
    assert len(tombstones) == 1

    # The bust left the lot flat; a corrected fact reappears through the
    # reopen machinery - real exposure recreated, never silently revived.
    receipt, snapshot = repository.record_execution_correction(
        correction_request(
            "exec-e",
            repository,
            revision=3,
            superseded_quantity=None,
            corrected_price_micros=10_500_000,
            corrected_quantity=105,
            step=3,
        )
    )
    assert receipt.reopened is True
    assert receipt.reversed_quantity == 0
    assert receipt.applied_quantity == 105
    row = _position_row(repository)
    assert row.settled_quantity_units == 105
    assert row.cost_basis_cents == 110_250
    assert row.state == PositionState.EXIT_PENDING.value
    assert _open_lots(repository) == {("lin-1", "lot-1"): 105}

    # The tombstone stays as append-only audit; the reopen row names the
    # correction that recreated the exposure.
    assert len(_tombstone_rows(repository)) == 1
    reopens = repository.reopen_exit_obligations()
    assert len(reopens) == 1
    assert reopens[0].reopened_quantity_units == 105
    assert reopens[0].reopened_by_execution_revision_id == "fill:exec-e:3"
    assert snapshot.available_cash_cents == 1_000_000 - 110_250
    repository.assert_conservation()


def test_exit_correction_consumes_basis_recomputed_half_even(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-e", repository, price_micros=333_333, quantity=3, step=1)
    )
    exit_receipt, _ = repository.record_fill_revision(
        fill_request(
            "exec-x",
            repository,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            price_micros=400_000,
            quantity=1,
            step=2,
        )
    )
    row = _position_row(repository)
    assert row.cost_basis_cents == 67  # 100 - round_half_even(100/3)

    # Correct the exit to 2 shares: the superseded exit's consumed basis
    # (33) refunds; the corrected exit consumes round_half_even(100*2/3)=67.
    receipt, snapshot = repository.record_execution_correction(
        correction_request(
            "exec-x",
            repository,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            superseded_quantity=1,
            corrected_price_micros=400_000,
            corrected_quantity=2,
            step=3,
        )
    )
    assert receipt.reversed_consumed_basis_cents == 33
    assert receipt.applied_consumed_basis_cents == 67
    row = _position_row(repository)
    assert row.settled_quantity_units == 1
    assert row.cost_basis_cents == 33
    assert row.state == PositionState.EXIT_PENDING.value
    # Cash: original exit proceeds reversed, corrected proceeds applied
    # (the recorded exit's +40 proceeds landed before the revision).
    assert snapshot.available_cash_cents == (
        1_000_000 - 100 + 40 - 40 + 80
    )
    report = repository.assert_conservation()
    assert report.exit_gross_cents == 80
    assert report.consumed_cost_basis_cents == 67


# ---------------------------------------------------------------------------
# Revision linkage: duplicates converge, divergence and gaps fail closed
# ---------------------------------------------------------------------------


def test_duplicate_revision_converges_and_divergent_content_conflicts(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(fill_request("exec-e", repository, step=1))
    receipt, snapshot = repository.record_execution_revision(
        bust_request("exec-e", repository, step=2)
    )
    # Identical retry converges on the committed revision (no new event).
    stream = repository.stream_version()
    retry, retry_snapshot = repository.record_execution_revision(
        bust_request("exec-e", repository, step=2)
    )
    assert retry.event_id == receipt.event_id
    assert retry_snapshot.capital_version == snapshot.capital_version
    assert repository.stream_version() == stream

    # Divergent content under the same (execution_id, revision) identity.
    divergent = bust_request("exec-e", repository, step=2)
    object.__setattr__(divergent, "superseded_quantity", 99)
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_execution_revision(divergent)
    assert excinfo.value.code == "payload_conflict"
    repository.assert_conservation()


def test_out_of_order_and_unknown_revisions_fail_closed(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(fill_request("exec-e", repository, step=1))

    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_execution_revision(
            bust_request("exec-e", repository, revision=3, step=2)
        )
    assert excinfo.value.code == "revision_sequence_conflict"

    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_execution_revision(
            bust_request("exec-ghost", repository, step=2)
        )
    assert excinfo.value.code == "execution_unknown"

    # Restating a different superseded fact than the active one is rejected.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_execution_revision(
            bust_request("exec-e", repository, superseded_quantity=99, step=2)
        )
    assert excinfo.value.code == "revision_content_conflict"

    # A correction that changes nothing is not an economic fact.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_execution_correction(
            correction_request(
                "exec-e",
                repository,
                corrected_price_micros=10_000_000,
                corrected_quantity=100,
                step=2,
            )
        )
    assert excinfo.value.code == "revision_changes_nothing"
    repository.assert_conservation()


def test_correction_creating_negative_shares_preserves_and_halts(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-e", repository, quantity=100, step=1)
    )
    repository.record_fill_revision(
        fill_request(
            "exec-x",
            repository,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            quantity=100,
            step=2,
        )
    )
    # Correcting the exit to 150 shares exports -50 shares: a long-only
    # impossibility. It is preserved (never clamped) and latched.
    receipt, snapshot = repository.record_execution_correction(
        correction_request(
            "exec-x",
            repository,
            order_id="ord-exit",
            side=ExecutionSide.EXIT,
            superseded_quantity=100,
            corrected_price_micros=10_000_000,
            corrected_quantity=150,
            step=3,
        )
    )
    assert receipt.reconciliation_halted is True
    row = _position_row(repository)
    assert row.settled_quantity_units == -50
    assert row.cost_basis_cents == 0  # whole-lot basis was consumed at 100
    assert snapshot.reconciliation_latch is (
        ReconciliationLatchState.RECONCILIATION_HALT
    )
    assert snapshot.completeness is RiskSnapshotCompleteness.INCOMPLETE

    # The halt latches one-way: later facts never silently clear it.
    repository.record_fill_revision(
        fill_request(
            "exec-e2",
            repository,
            position_lineage_id="lin-2",
            economic_lot_id="lot-2",
            quantity=10,
            step=4,
        )
    )
    snapshot = repository.capital_risk_snapshot(_moment(5))
    assert snapshot.reconciliation_latch is (
        ReconciliationLatchState.RECONCILIATION_HALT
    )
    discrepancies = repository.reconciliation_discrepancies()
    assert [item.economic_lot_id for item in discrepancies] == ["lot-1"]
    repository.assert_conservation()


def test_bust_of_cancel_late_fill_under_sentinel_attribution(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.reserve_entry(
        ReserveEntryRequest(
            source_id="entry-1",
            research_program_id="prog-1",
            economic_lineage_id="eline-1",
            stage_id="stage-1",
            reserved_entry_gross_cents=100_000,
            expected_stream_version=repository.stream_version(),
            as_of=_moment(1),
        )
    )
    repository.release_reserve(
        ReserveReleaseRequest(
            source_id="entry-1",
            reason=ReserveReleaseReason.CANCEL_CONFIRMED,
            expected_stream_version=repository.stream_version(),
            as_of=_moment(2),
        )
    )
    # The invalidated entry is tombstoned atomically with the release.
    tombstones = _tombstone_rows(repository)
    assert [row.entry_identity for row in tombstones] == ["reserve:entry-1"]

    # A fill arriving after the confirmed cancel is plan-violating: it is
    # preserved under sentinel attribution (Task 2), and its bust still
    # reverses the legs exactly.
    late_receipt, _ = repository.record_fill_revision(
        fill_request(
            "exec-late",
            repository,
            position_lineage_id=None,
            economic_lot_id=None,
            attribution=None,
            step=3,
        )
    )
    sentinel_lot = f"unattributed:exec-late"
    assert late_receipt.position_lineage_id == sentinel_lot
    receipt, _ = repository.record_execution_revision(
        bust_request(
            "exec-late",
            repository,
            order_id="ord-1",
            position_lineage_id=sentinel_lot,
            economic_lot_id=sentinel_lot,
            step=4,
        )
    )
    assert receipt.reversed_gross_cents == 100_000
    assert receipt.reconciliation_halted is False
    snapshot = repository.capital_risk_snapshot(_moment(5))
    assert snapshot.available_cash_cents == 1_000_000
    assert snapshot.unattributed_risk_cents == 0
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Fee revisions follow fill revisions
# ---------------------------------------------------------------------------


def test_fee_bust_refunds_after_fill_bust(repository: CapitalRepository) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(fill_request("exec-e", repository, step=1))
    fee_receipt, _ = repository.record_fee_revision(
        fee_request("exec-e", repository, step=2)
    )
    # 300 commission base but the 500 minimum dominates; plus 2 transfer.
    assert fee_receipt.total_cents == 502

    # A fee bust before the fill bust is rejected: fees follow fills.
    with pytest.raises(CapitalConflict) as excinfo:
        repository.record_fee_revision(
            fee_request(
                "exec-e", repository, revision=2,
                revision_kind=FeeRevisionKind.BUSTED, step=3,
            )
        )
    assert excinfo.value.code == "fee_revision_requires_fill_revision"

    repository.record_execution_revision(
        bust_request("exec-e", repository, step=4)
    )
    bust_receipt, snapshot = repository.record_fee_revision(
        fee_request(
            "exec-e", repository, revision=2,
            revision_kind=FeeRevisionKind.BUSTED, step=5,
        )
    )
    assert bust_receipt.revision_kind is FeeRevisionKind.BUSTED
    # The whole order fee refunds: no active fill, no commission owed.
    assert bust_receipt.booked_delta_cents == -502
    assert bust_receipt.total_cents == 0
    assert snapshot.available_cash_cents == 1_000_000
    report = repository.assert_conservation()
    assert report.total_fee_cents == 0


def test_fee_correction_recomputes_after_fill_correction(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(
        fill_request("exec-e", repository, price_micros=10_000_000, quantity=100, step=1)
    )
    fee_receipt, _ = repository.record_fee_revision(
        fee_request("exec-e", repository, step=2)
    )
    assert fee_receipt.total_cents == 502

    repository.record_execution_correction(
        correction_request(
            "exec-e",
            repository,
            corrected_price_micros=50_000_000,
            corrected_quantity=100,
            step=3,
        )
    )
    correction_receipt, snapshot = repository.record_fee_revision(
        fee_request(
            "exec-e", repository, revision=2,
            revision_kind=FeeRevisionKind.CORRECTED, step=4,
        )
    )
    # Corrected notional 5000.00 yuan: commission 1500 (minimum no longer
    # dominates), transfer 10 (20ppm of 500_000 cents, same basis as the
    # initial charge); delta against the 502 already charged.
    assert correction_receipt.commission_cents == 1_500
    assert correction_receipt.transfer_fee_cents == 10
    assert correction_receipt.total_cents == 1_510
    assert correction_receipt.booked_delta_cents == 1_510 - 502
    assert snapshot.available_cash_cents == (
        1_000_000 - 500_000 - 1_510
    )
    report = repository.assert_conservation()
    assert report.total_fee_cents == 1_510
    repository.assert_conservation()


def test_zero_delta_fee_correction_is_registry_only(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(fill_request("exec-e", repository, step=1))
    repository.record_fee_revision(fee_request("exec-e", repository, step=2))
    # Correct the fill to an identical notional class: the order fee target
    # is unchanged (minimum still dominates), so no capital moves.
    repository.record_execution_correction(
        correction_request(
            "exec-e",
            repository,
            corrected_price_micros=5_000_000,
            corrected_quantity=200,
            step=3,
        )
    )
    stream = repository.stream_version()
    receipt, _ = repository.record_fee_revision(
        fee_request(
            "exec-e", repository, revision=2,
            revision_kind=FeeRevisionKind.CORRECTED, step=4,
        )
    )
    assert receipt.event_id is None
    assert receipt.booked_delta_cents == 0
    assert repository.stream_version() == stream
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Stage loss stays monotone under corrections
# ---------------------------------------------------------------------------


def test_stage_loss_consumption_never_refunds_under_correction(
    repository: CapitalRepository,
) -> None:
    from src.screening.offensive.v3.capital.risk_snapshot import (
        GLOBAL_STAGE_LOSS_IDENTITY,
        StageLossBudgetActivationRequest,
    )

    deposit(repository, 1_000_000, 1)
    repository.activate_stage_loss_budget(
        StageLossBudgetActivationRequest(
            idempotency_key="activate-budget-global",
            stage_loss_budget_id="budget-global",
            research_program_id=GLOBAL_STAGE_LOSS_IDENTITY[0],
            economic_lineage_id=GLOBAL_STAGE_LOSS_IDENTITY[1],
            stage_id=GLOBAL_STAGE_LOSS_IDENTITY[2],
            frozen_budget_cents=100_000,
            source_authority="governance.test",
            authorization_reference="auth-test",
            as_of=_moment(1),
            expected_stage_loss_state_version=(
                repository.capital_risk_snapshot(_moment(1))
                .stage_loss_state_version
            ),
        )
    )

    # Entry at 1000.00 yuan, mark down to 500.00: unrealized floor 50_000
    # plus the 502 fee floor consumes 50_502 of the frozen budget.
    repository.record_fill_revision(fill_request("exec-e", repository, step=2))
    repository.record_fee_revision(fee_request("exec-e", repository, step=3))
    snapshot = repository.capital_risk_snapshot(_moment(4))
    latch = snapshot.stage_loss_latches[0]
    consumed_at_loss = latch.consumed_cents
    assert consumed_at_loss == 502  # no mark yet: only the fee floor

    # A correction that lowers the entry price increases the fee floor only
    # through the recomputed fee; consumption must move monotonically.
    repository.record_execution_correction(
        correction_request(
            "exec-e",
            repository,
            corrected_price_micros=20_000_000,
            corrected_quantity=100,
            step=5,
        )
    )
    repository.record_fee_revision(
        fee_request(
            "exec-e", repository, revision=2,
            revision_kind=FeeRevisionKind.CORRECTED, step=6,
        )
    )
    snapshot = repository.capital_risk_snapshot(_moment(7))
    latch = snapshot.stage_loss_latches[0]
    # Fee target 600 commission (200_000 cents x 3000ppm; minimum no
    # longer dominates) + 4 transfer = 604 charged total; the floor
    # advanced and was never refunded by the earlier 502 payment.
    assert latch.consumed_cents == 604
    assert latch.consumed_cents >= consumed_at_loss

    # Now bust the corrected fill (revision 3) and refund the fee: the
    # consumed budget stays.
    repository.record_execution_revision(
        bust_request("exec-e", repository, revision=3, step=8)
    )
    repository.record_fee_revision(
        fee_request(
            "exec-e", repository, revision=3,
            revision_kind=FeeRevisionKind.BUSTED, step=9,
        )
    )
    snapshot = repository.capital_risk_snapshot(_moment(10))
    latch = snapshot.stage_loss_latches[0]
    assert latch.consumed_cents == 604  # monotone: never refunded
    repository.assert_conservation()


# ---------------------------------------------------------------------------
# Convergence: the same canonical revisions reach identical capital state
# ---------------------------------------------------------------------------


def test_bust_then_fee_bust_converges_in_either_order(
    repository: CapitalRepository, tmp_path: Path
) -> None:
    """Fee revisions follow fill revisions, and retries converge.

    A fee bust before the linked fill bust stays rejected (fees follow
    fills); once both busts are committed, idempotent retries of either
    bust in any order converge on the identical committed state.
    """
    other = CapitalRepository.initialize(tmp_path / "other.sqlite3")

    for repo, fee_retry_first in ((repository, False), (other, True)):
        deposit(repo, 1_000_000, 1)
        repo.record_fill_revision(fill_request("exec-e", repo, step=2))
        repo.record_fee_revision(fee_request("exec-e", repo, step=3))
        # A fee bust before the fill bust is rejected: fees follow fills.
        with pytest.raises(CapitalConflict) as excinfo:
            repo.record_fee_revision(
                fee_request(
                    "exec-e", repo, revision=2,
                    revision_kind=FeeRevisionKind.BUSTED, step=4,
                )
            )
        assert excinfo.value.code == "fee_revision_requires_fill_revision"
        repo.record_execution_revision(
            bust_request("exec-e", repo, step=5)
        )
        repo.record_fee_revision(
            fee_request(
                "exec-e", repo, revision=2,
                revision_kind=FeeRevisionKind.BUSTED, step=6,
            )
        )
        # Idempotent retries of both busts (identical content, opposite
        # orders) converge on the committed revisions.
        if fee_retry_first:
            repo.record_fee_revision(
                fee_request(
                    "exec-e", repo, revision=2,
                    revision_kind=FeeRevisionKind.BUSTED, step=6,
                )
            )
            repo.record_execution_revision(
                bust_request("exec-e", repo, step=5)
            )
        else:
            repo.record_execution_revision(
                bust_request("exec-e", repo, step=5)
            )
            repo.record_fee_revision(
                fee_request(
                    "exec-e", repo, revision=2,
                    revision_kind=FeeRevisionKind.BUSTED, step=6,
                )
            )
        repo.assert_conservation()

    left = repository.capital_risk_snapshot(_moment(99))
    right = other.capital_risk_snapshot(_moment(99))
    assert left.available_cash_cents == right.available_cash_cents == 1_000_000
    assert left.positions == right.positions == ()
    assert left.capital_version == right.capital_version
    assert left.total_gross_exposure_cents == right.total_gross_exposure_cents == 0


# ---------------------------------------------------------------------------
# Property: conservation holds through interleaved bust/correction/reopen
# ---------------------------------------------------------------------------


class _LotState:
    def __init__(self) -> None:
        self.quantity = 0
        self.basis = 0
        self.entries: list[dict[str, int]] = []
        self.exits: list[dict[str, int]] = []
        self.entry_blocked = False  # flat/terminal lots accept no entries

    @property
    def impossible(self) -> bool:
        return self.quantity < 0 or self.basis < 0


@settings(
    deadline=None,
    max_examples=25,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(data=st.data())
def test_property_interleaved_bust_correction_sequences_conserve(
    data, tmp_path: Path
) -> None:
    repository = CapitalRepository.initialize(
        tmp_path / f"capital-{uuid.uuid4().hex}.sqlite3"
    )
    deposit(repository, 10_000_000, 0)

    lot = _LotState()
    fill_counter = 0
    step = 1

    def record_entry(quantity: int) -> str:
        nonlocal fill_counter, step
        fill_counter += 1
        execution_id = f"exec-e{fill_counter}"
        repository.record_fill_revision(
            fill_request(
                execution_id,
                repository,
                price_micros=10_000_000,
                quantity=quantity,
                step=step,
            )
        )
        step += 1
        lot.quantity += quantity
        lot.basis += 100_000 * quantity // 100
        lot.entries.append(
            {
                "execution_id": execution_id,
                "quantity": quantity,
                "gross": 100_000 * quantity // 100,
                "active": True,
            }
        )
        return execution_id

    def record_exit(quantity: int) -> str:
        nonlocal fill_counter, step
        fill_counter += 1
        execution_id = f"exec-x{fill_counter}"
        before_quantity = lot.quantity
        repository.record_fill_revision(
            fill_request(
                execution_id,
                repository,
                order_id="ord-exit",
                side=ExecutionSide.EXIT,
                price_micros=11_000_000,
                quantity=quantity,
                step=step,
            )
        )
        step += 1
        consumed = (
            lot.basis
            if quantity == before_quantity
            else round_half_even_div(lot.basis * quantity, before_quantity)
        )
        lot.quantity -= quantity
        lot.basis -= consumed
        # Any exit moves the lot to EXIT_PENDING permanently; the kernel
        # rejects entries into exiting or closed lots.
        lot.entry_blocked = True
        lot.exits.append(
            {
                "execution_id": execution_id,
                "quantity": quantity,
                "gross": 110_000 * quantity // 100,
                "consumed": consumed,
                "active": True,
            }
        )
        return execution_id

    operations = data.draw(st.integers(min_value=1, max_value=12))
    for _ in range(operations):
        active_entries = [entry for entry in lot.entries if entry["active"]]
        active_exits = [exit_ for exit_ in lot.exits if exit_["active"]]
        choices = []
        if not lot.entry_blocked:
            choices.append("entry")
        if lot.quantity > 0:
            choices.append("exit")
        if active_entries:
            choices.append("bust_entry")
            choices.append("correct_entry")
        if active_exits:
            choices.append("bust_exit")
            choices.append("correct_exit")
        if not choices:
            break
        choice = data.draw(st.sampled_from(choices))

        if choice == "entry":
            record_entry(data.draw(st.sampled_from([50, 100])))
        elif choice == "exit":
            quantity = data.draw(
                st.sampled_from(sorted({lot.quantity, max(1, lot.quantity // 2)}))
            )
            record_exit(quantity)
        elif choice == "bust_entry":
            entry = data.draw(st.sampled_from(active_entries))
            receipt, _ = repository.record_execution_revision(
                bust_request(
                    entry["execution_id"],
                    repository,
                    revision=_next_revision(repository, entry["execution_id"]),
                    superseded_quantity=entry["quantity"],
                    step=step,
                )
            )
            step += 1
            entry["active"] = False
            lot.quantity -= entry["quantity"]
            lot.basis -= entry["gross"]
            if lot.quantity <= 0:
                lot.entry_blocked = True
            assert receipt.reconciliation_halted == lot.impossible
        elif choice == "bust_exit":
            exit_ = data.draw(st.sampled_from(active_exits))
            receipt, _ = repository.record_execution_revision(
                bust_request(
                    exit_["execution_id"],
                    repository,
                    revision=_next_revision(repository, exit_["execution_id"]),
                    order_id="ord-exit",
                    side=ExecutionSide.EXIT,
                    superseded_quantity=exit_["quantity"],
                    step=step,
                )
            )
            step += 1
            exit_["active"] = False
            quantity_before = lot.quantity
            lot.quantity += exit_["quantity"]
            lot.basis += exit_["consumed"]
            if lot.quantity > 0:
                # Reopen is the flat/nonpositive-to-positive transition:
                # a partial exit bust keeps the lot live without one.
                assert receipt.reopened is (quantity_before <= 0)
            else:
                lot.entry_blocked = True
        elif choice == "correct_entry":
            entry = data.draw(st.sampled_from(active_entries))
            quantity = data.draw(st.sampled_from([25, 50, 75]))
            if quantity == entry["quantity"]:
                continue  # identical fact: not an economic correction
            receipt, _ = repository.record_execution_correction(
                correction_request(
                    entry["execution_id"],
                    repository,
                    revision=_next_revision(repository, entry["execution_id"]),
                    superseded_quantity=entry["quantity"],
                    corrected_price_micros=10_000_000,
                    corrected_quantity=quantity,
                    step=step,
                )
            )
            step += 1
            lot.quantity += quantity - entry["quantity"]
            new_gross = 100_000 * quantity // 100
            lot.basis += new_gross - entry["gross"]
            entry["quantity"] = quantity
            entry["gross"] = new_gross
            if lot.quantity <= 0:
                lot.entry_blocked = True
        elif choice == "correct_exit":
            exit_ = data.draw(st.sampled_from(active_exits))
            ceiling = max(1, lot.quantity + exit_["quantity"])
            quantity = data.draw(
                st.integers(min_value=1, max_value=ceiling + 25)
            )
            if quantity == exit_["quantity"]:
                continue
            receipt, _ = repository.record_execution_correction(
                correction_request(
                    exit_["execution_id"],
                    repository,
                    order_id="ord-exit",
                    side=ExecutionSide.EXIT,
                    revision=_next_revision(repository, exit_["execution_id"]),
                    superseded_quantity=exit_["quantity"],
                    corrected_price_micros=11_000_000,
                    corrected_quantity=quantity,
                    step=step,
                )
            )
            step += 1
            before_quantity = lot.quantity + exit_["quantity"]
            basis_after_reversal = lot.basis + exit_["consumed"]
            new_consumed = (
                basis_after_reversal
                if quantity == before_quantity
                else round_half_even_div(
                    basis_after_reversal * quantity, before_quantity
                )
                if before_quantity > 0
                else 0
            )
            # The kernel caps consumption at the lot's available basis;
            # the excess corrected quantity stays as preserved negative
            # shares.
            new_consumed = min(new_consumed, max(basis_after_reversal, 0))
            lot.quantity += exit_["quantity"] - quantity
            lot.basis += exit_["consumed"] - new_consumed
            exit_["quantity"] = quantity
            exit_["consumed"] = new_consumed
            if lot.quantity <= 0:
                lot.entry_blocked = True

        # Conservation must hold through every interleaving, including
        # halted negative projections.
        repository.assert_conservation()
        row = _position_row(repository)
        assert int(row.settled_quantity_units) == lot.quantity
        assert int(row.cost_basis_cents) == lot.basis
        snapshot = repository.capital_risk_snapshot(_moment(step + 100))
        if lot.impossible:
            assert snapshot.reconciliation_latch is (
                ReconciliationLatchState.RECONCILIATION_HALT
            )
            assert snapshot.completeness is (
                RiskSnapshotCompleteness.INCOMPLETE
            )
        else:
            assert snapshot.completeness is RiskSnapshotCompleteness.COMPLETE


def _next_revision(repository: CapitalRepository, execution_id: str) -> int:
    rows = _registry_rows(repository, execution_id)
    return max(int(row.revision) for row in rows) + 1


# ---------------------------------------------------------------------------
# Dispatch: record_fill_revision accepts revision > 1 through Task 6
# ---------------------------------------------------------------------------


def test_fill_revision_dispatches_bust_beyond_revision_one(
    repository: CapitalRepository,
) -> None:
    deposit(repository, 1_000_000, 1)
    repository.record_fill_revision(fill_request("exec-e", repository, step=1))
    base = fill_request("exec-e", repository, step=2)
    busted = FillRevisionRequest.model_validate(
        {
            **base.model_dump(mode="python"),
            "revision": 2,
            "revision_kind": ExecutionRevisionKind.BUSTED,
        }
    )
    receipt, snapshot = repository.record_fill_revision(busted)
    assert isinstance(receipt, ExecutionRevisionReceipt)
    assert receipt.revision_kind is ExecutionRevisionKind.BUSTED
    assert snapshot.available_cash_cents == 1_000_000

    # A revision > 1 without a kind stays fail-closed at the model layer.
    with pytest.raises(Exception):
        FillRevisionRequest.model_validate(
            {**base.model_dump(mode="python"), "revision": 2}
        )
    repository.assert_conservation()
