"""Exact conservation recomputation for the append-only capital ledger.

Plan 02 Task 2: ``assert_conservation`` recomputes every stored projection
from the economic event stream and fails loudly on any unexplained cent,
share, or unit.

The master identity (all terms integer cents) is::

    opening_capital + external_flows + economic_pnl
        == closing_assets - liabilities

with, in kernel revision 2 (genesis units and external flows land in
Task 3, so the first two terms are exactly zero here)::

    economic_pnl     = realized_pnl_ex_fees + dividend_income - total_fees
    realized_pnl_ex_fees = exit_gross - cost_basis_consumed_on_exits
    closing_assets   = cash + outstanding_receivables + open_cost_basis

The identity holds by construction for any correct projection of the event
stream: fees are kept out of realized market P&L (they are a separate
charge), and cost basis is consumed on exits with the same versioned
average-cost rule the projector applies. Conservation additionally checks
the cash split (available/restricted against live reserves), per-lot share
and basis equality, receivable equality, fee registry/event linkage, and
stream contiguity — so any tampered or drifted projection row breaks at
least one check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from src.screening.offensive.v3.capital.rounding import round_half_even_div
from src.screening.offensive.v3.contracts import (
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import sqlalchemy.engine


@dataclass(frozen=True)
class ConservationReport:
    """Every recomputed term of the conservation identity."""

    event_count: int
    opening_capital_cents: int
    external_flow_cents: int
    entry_gross_cents: int
    exit_gross_cents: int
    consumed_cost_basis_cents: int
    realized_pnl_ex_fees_cents: int
    dividend_income_cents: int
    total_fee_cents: int
    economic_pnl_cents: int
    closing_cash_cents: int
    closing_receivable_cents: int
    closing_cost_basis_cents: int
    closing_assets_cents: int
    liabilities_cents: int
    available_cash_cents: int
    restricted_cash_cents: int
    reserved_cash_cents: int


def _violation(message: str, **details: object) -> Exception:
    # Lazy import keeps the conservation module free of a repository
    # import cycle while reusing the kernel's fail-closed exception type.
    from src.screening.offensive.v3.capital.repository import CapitalConflict

    return CapitalConflict("conservation_violation", message, **details)


def _fail(message: str, **details: object) -> None:
    raise _violation(message, **details)


def verify_conservation(
    connection: "sqlalchemy.engine.Connection",
    metadata: sa.MetaData,
) -> ConservationReport:
    """Recompute all identities on one connection; raise on any mismatch."""

    events_table = metadata.tables["economic_events"]
    legs_table = metadata.tables["economic_event_legs"]

    binding_row = connection.execute(
        metadata.tables["account_capital_truth"].select()
    ).first()
    if binding_row is None:
        # An unbound ledger holds no economic facts: conservation is void.
        return ConservationReport(
            event_count=0,
            opening_capital_cents=0,
            external_flow_cents=0,
            entry_gross_cents=0,
            exit_gross_cents=0,
            consumed_cost_basis_cents=0,
            realized_pnl_ex_fees_cents=0,
            dividend_income_cents=0,
            total_fee_cents=0,
            economic_pnl_cents=0,
            closing_cash_cents=0,
            closing_receivable_cents=0,
            closing_cost_basis_cents=0,
            closing_assets_cents=0,
            liabilities_cents=0,
            available_cash_cents=0,
            restricted_cash_cents=0,
            reserved_cash_cents=0,
        )

    # -- replay inputs ---------------------------------------------------------

    rows = connection.execute(
        sa.text(
            "SELECT e.stream_version AS stream_version,"
            " e.event_kind AS event_kind,"
            " e.position_lineage_id AS position_lineage_id,"
            " e.economic_lot_id AS economic_lot_id,"
            " e.payload_content_hash AS payload_content_hash,"
            " l.asset_kind AS asset_kind,"
            " l.direction AS direction,"
            " l.cash_amount_cents AS cash_amount_cents,"
            " l.quantity_units AS quantity_units,"
            " l.receivable_id AS receivable_id"
            " FROM economic_events e"
            " JOIN economic_event_legs l"
            " ON l.economic_event_id = e.economic_event_id"
            " ORDER BY e.stream_version, l.sequence"
        )
    ).all()
    event_count = connection.execute(
        sa.text("SELECT COUNT(*) AS n FROM economic_events")
    ).scalar()
    versions = connection.execute(
        sa.text("SELECT stream_version FROM economic_events ORDER BY stream_version")
    ).scalars().all()
    if list(versions) != list(range(1, len(versions) + 1)):
        _fail("economic event stream is not contiguous", versions=versions)

    cash_credit_total = 0
    cash_debit_total = 0
    entry_gross = 0
    exit_gross = 0
    fee_total = 0
    dividend_income = 0
    quantity_by_lot: dict[tuple[str, str], int] = {}
    basis_by_lot: dict[tuple[str, str], int] = {}
    consumed_basis_total = 0
    receivable_by_id: dict[str, int] = {}
    trade_event_hashes: set[str] = set()
    fee_event_hashes: set[str] = set()

    # Entry cost basis is the cash debit of the same TRADE_EXECUTED event;
    # precompute it per stream version so the replay stays linear.
    trade_cash_debit_by_version: dict[int, int] = {}
    for row in rows:
        if (
            EconomicEventKind(row.event_kind) is EconomicEventKind.TRADE_EXECUTED
            and EconomicAssetKind(row.asset_kind) is EconomicAssetKind.CASH
            and EconomicLegDirection(row.direction) is EconomicLegDirection.DEBIT
        ):
            trade_cash_debit_by_version[row.stream_version] = (
                trade_cash_debit_by_version.get(row.stream_version, 0)
                + int(row.cash_amount_cents)
            )

    for row in rows:
        event_kind = EconomicEventKind(row.event_kind)
        asset_kind = EconomicAssetKind(row.asset_kind)
        direction = EconomicLegDirection(row.direction)

        if asset_kind is EconomicAssetKind.CASH:
            amount = int(row.cash_amount_cents)
            if direction is EconomicLegDirection.CREDIT:
                cash_credit_total += amount
            else:
                cash_debit_total += amount
            if event_kind is EconomicEventKind.TRADE_EXECUTED:
                key = (row.position_lineage_id, row.economic_lot_id)
                if direction is EconomicLegDirection.DEBIT:
                    entry_gross += amount
                else:
                    exit_gross += amount
                trade_event_hashes.add(row.payload_content_hash)
            elif event_kind is EconomicEventKind.FEE_CHARGED:
                if direction is not EconomicLegDirection.DEBIT:
                    _fail(
                        "fee event cash leg must be a debit",
                        stream_version=row.stream_version,
                    )
                fee_total += amount
                fee_event_hashes.add(row.payload_content_hash)

        elif asset_kind is EconomicAssetKind.SECURITY:
            key = (row.position_lineage_id, row.economic_lot_id)
            quantity = int(row.quantity_units)
            if direction is EconomicLegDirection.CREDIT:
                quantity_by_lot[key] = quantity_by_lot.get(key, 0) + quantity
                if event_kind is EconomicEventKind.TRADE_EXECUTED:
                    # Entry gross cash becomes cost basis (one fact, one
                    # event: the cash debit of the same event).
                    gross = trade_cash_debit_by_version.get(row.stream_version, 0)
                    basis_by_lot[key] = basis_by_lot.get(key, 0) + gross
            else:
                before = quantity_by_lot.get(key, 0)
                if quantity > before:
                    _fail(
                        "security debit exceeds replayed position quantity",
                        position_lineage_id=key[0],
                        economic_lot_id=key[1],
                    )
                quantity_by_lot[key] = before - quantity
                if event_kind is EconomicEventKind.TRADE_EXECUTED:
                    basis_before = basis_by_lot.get(key, 0)
                    if quantity == before:
                        consumed = basis_before
                    else:
                        consumed = round_half_even_div(
                            basis_before * quantity, before
                        )
                    basis_by_lot[key] = basis_before - consumed
                    consumed_basis_total += consumed

        elif asset_kind is EconomicAssetKind.CASH_RECEIVABLE:
            amount = int(row.cash_amount_cents)
            if direction is EconomicLegDirection.CREDIT:
                if row.receivable_id in receivable_by_id:
                    _fail(
                        "receivable credited twice",
                        receivable_id=row.receivable_id,
                    )
                receivable_by_id[row.receivable_id] = amount
                if event_kind is EconomicEventKind.DIVIDEND_RECEIVABLE:
                    dividend_income += amount
            else:
                outstanding = receivable_by_id.get(row.receivable_id)
                if outstanding is None:
                    _fail(
                        "receivable debit against unknown receivable",
                        receivable_id=row.receivable_id,
                    )
                if outstanding != amount:
                    _fail(
                        "receivable settlement amount mismatch",
                        receivable_id=row.receivable_id,
                    )
                del receivable_by_id[row.receivable_id]

    # -- stored projections ------------------------------------------------------

    projection = connection.execute(
        metadata.tables["capital_projection"].select()
    ).one()
    available = int(projection.available_cash_cents)
    restricted = int(projection.restricted_cash_cents)
    unsettled = int(projection.unsettled_cash_cents)

    cash_recomputed = cash_credit_total - cash_debit_total
    if cash_recomputed != available + restricted + unsettled:
        _fail(
            "cash conservation violated",
            recomputed_cents=cash_recomputed,
            stored_available_cents=available,
            stored_restricted_cents=restricted,
            stored_unsettled_cents=unsettled,
        )

    reserve_rows = connection.execute(
        sa.text(
            "SELECT reserved_entry_gross_cents FROM reserves"
            " WHERE state IN ('LIVE', 'CANCEL_PENDING')"
        )
    ).all()
    reserved_total = sum(int(row.reserved_entry_gross_cents) for row in reserve_rows)
    if restricted != reserved_total:
        _fail(
            "restricted cash does not equal live reserves",
            restricted_cents=restricted,
            reserved_cents=reserved_total,
        )
    if available != cash_recomputed - restricted - unsettled:
        _fail(
            "available cash split violated",
            available_cents=available,
            expected_cents=cash_recomputed - restricted - unsettled,
        )

    position_rows = connection.execute(metadata.tables["positions"].select()).all()
    stored_lots = set()
    for row in position_rows:
        key = (row.position_lineage_id, row.economic_lot_id)
        if key in stored_lots:
            _fail("duplicate position row", position=key)
        stored_lots.add(key)
        expected_quantity = quantity_by_lot.get(key, 0)
        if int(row.settled_quantity_units) != expected_quantity:
            _fail(
                "position quantity drifted from event history",
                position_lineage_id=key[0],
                economic_lot_id=key[1],
                stored_units=int(row.settled_quantity_units),
                recomputed_units=expected_quantity,
            )
        if int(row.tradable_quantity_units) != expected_quantity:
            _fail(
                "tradable quantity drifted from settled quantity",
                position_lineage_id=key[0],
                economic_lot_id=key[1],
            )
        expected_basis = basis_by_lot.get(key, 0)
        if int(row.cost_basis_cents) != expected_basis:
            _fail(
                "cost basis drifted from event history",
                position_lineage_id=key[0],
                economic_lot_id=key[1],
                stored_cents=int(row.cost_basis_cents),
                recomputed_cents=expected_basis,
            )
        if expected_quantity == 0 and row.state not in ("CLOSED", "LEGAL_TERMINAL"):
            _fail("flat position must be terminal", position=key, state=row.state)
        if expected_quantity > 0 and row.state not in ("OPEN", "EXIT_PENDING"):
            _fail("open position must be live", position=key, state=row.state)
    for key, quantity in quantity_by_lot.items():
        if quantity > 0 and key not in stored_lots:
            _fail("replayed position missing its projection row", position=key)

    receivable_rows = connection.execute(
        sa.text("SELECT * FROM receivables")
    ).all()
    recomputed_outstanding = sum(receivable_by_id.values())
    stored_outstanding = sum(
        int(row.amount_cents) for row in receivable_rows if int(row.settled) == 0
    )
    if recomputed_outstanding != stored_outstanding:
        _fail(
            "receivable conservation violated",
            recomputed_cents=recomputed_outstanding,
            stored_cents=stored_outstanding,
        )
    for row in receivable_rows:
        if int(row.settled) == 0:
            expected = receivable_by_id.get(row.receivable_id)
            if expected is None or int(row.amount_cents) != expected:
                _fail(
                    "outstanding receivable drifted from event history",
                    receivable_id=row.receivable_id,
                )

    # Fee registry linkage: every fee event must have exactly one registry
    # row and every fill row must link back to a trade event.
    fee_registry_rows = connection.execute(
        sa.text(
            "SELECT payload_content_hash FROM execution_revisions"
            " WHERE revision_kind = 'FEE'"
        )
    ).all()
    fee_registry_hashes = {row.payload_content_hash for row in fee_registry_rows}
    if len(fee_registry_hashes) != len(fee_registry_rows):
        _fail("duplicate fee revision registry entry")
    missing_fee_rows = fee_event_hashes - fee_registry_hashes
    if missing_fee_rows:
        _fail(
            "fee event missing its execution revision registry row",
            missing=sorted(missing_fee_rows),
        )
    fill_registry_rows = connection.execute(
        sa.text(
            "SELECT payload_content_hash FROM execution_revisions"
            " WHERE revision_kind = 'FILL'"
        )
    ).all()
    orphan_fills = {
        row.payload_content_hash for row in fill_registry_rows
    } - trade_event_hashes
    if orphan_fills:
        _fail(
            "fill registry row without a canonical trade event",
            orphans=sorted(orphan_fills),
        )

    payables_total = int(
        connection.execute(
            sa.text("SELECT COALESCE(SUM(amount_cents), 0) AS total FROM payables")
        ).scalar()
    )

    realized_pnl_ex_fees = exit_gross - consumed_basis_total
    economic_pnl = realized_pnl_ex_fees + dividend_income - fee_total
    closing_cash = cash_recomputed
    closing_basis = sum(basis_by_lot.values())
    closing_assets = closing_cash + recomputed_outstanding + closing_basis
    liabilities = payables_total

    opening_capital = 0  # genesis units land in Task 3
    external_flows = 0  # subscriptions/redemptions land in Task 3
    if (
        opening_capital + external_flows + economic_pnl
        != closing_assets - liabilities
    ):
        _fail(
            "master conservation identity violated",
            opening_capital_cents=opening_capital,
            external_flow_cents=external_flows,
            economic_pnl_cents=economic_pnl,
            closing_assets_cents=closing_assets,
            liabilities_cents=liabilities,
        )

    return ConservationReport(
        event_count=int(event_count),
        opening_capital_cents=opening_capital,
        external_flow_cents=external_flows,
        entry_gross_cents=entry_gross,
        exit_gross_cents=exit_gross,
        consumed_cost_basis_cents=consumed_basis_total,
        realized_pnl_ex_fees_cents=realized_pnl_ex_fees,
        dividend_income_cents=dividend_income,
        total_fee_cents=fee_total,
        economic_pnl_cents=economic_pnl,
        closing_cash_cents=closing_cash,
        closing_receivable_cents=recomputed_outstanding,
        closing_cost_basis_cents=closing_basis,
        closing_assets_cents=closing_assets,
        liabilities_cents=liabilities,
        available_cash_cents=available,
        restricted_cash_cents=restricted,
        reserved_cash_cents=reserved_total,
    )


__all__ = ["ConservationReport", "verify_conservation"]
