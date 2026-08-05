"""Exact conservation recomputation for the append-only capital ledger.

Plan 02 Task 2 established the master identity; Plan 02 Task 3 extends it
with genesis units, external flows, suspense cash, payables, and the NAV
observation paths. ``assert_conservation`` recomputes every stored
projection from the economic event stream **and** the financing flow
stream and fails loudly on any unexplained cent, share, or unit.

The master identity (all terms integer cents) is::

    opening_capital + external_flows + economic_pnl
        == closing_assets - liabilities

with::

    opening_capital  = genesis cash received
    external_flows   = subscription consumed cash - redemption settled
                       payouts (equity leaves the unit holders when the
                       redemption payable is confirmed; the later cash
                       payment is equity-neutral)
    economic_pnl     = realized_pnl_ex_fees + dividend_income - total_fees
    realized_pnl_ex_fees = exit_gross - cost_basis_consumed_on_exits
    closing_assets   = cash + outstanding_receivables + open_cost_basis

Cash replay covers both streams: economic cash legs plus the flow stream
(genesis and subscription receipts in; refunds and redemption payments
out). The identity holds by construction for any correct projection:
subscription suspense always equals open subscription payables,
redemption suspense equals the ring-fenced portion of open redemption
payables, units replay exactly from flow events, and the NAV observation
paths stay internally consistent (exact rational unit prices, typed
log-growth sentinels, and append-only restatement links).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import gcd
from typing import TYPE_CHECKING

import sqlalchemy as sa

from src.screening.offensive.v3.capital.flows import (
    REDEMPTION_PAYABLE,
    SUBSCRIPTION_PAYABLE,
    FlowKind,
    PayableState,
)
from src.screening.offensive.v3.capital.nav import (
    LogGrowthKind,
    ObservationKind,
)
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
    flow_event_count: int
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
    subscription_suspense_cents: int
    redemption_suspense_cents: int
    issued_unit_quanta: int
    pending_redeemed_unit_quanta: int


def _violation(message: str, **details: object) -> Exception:
    # Lazy import keeps the conservation module free of a repository
    # import cycle while reusing the kernel's fail-closed exception type.
    from src.screening.offensive.v3.capital.repository import CapitalConflict

    return CapitalConflict("conservation_violation", message, **details)


def _fail(message: str, **details: object) -> None:
    raise _violation(message, **details)


def _parse_execution_revision_fact(
    payload_json: str,
) -> dict[str, object] | None:
    """The execution revision fact of one event payload, when present.

    Returns None for payloads without an execution revision (e.g. the
    receivable-only corporate corrections). The kernel verified the fact's
    exact frozen shape at append time; the replay reads the canonical dict
    fields directly.
    """

    payload = json.loads(payload_json)
    fact = payload.get("execution_revision")
    if not isinstance(fact, dict):
        return None
    return fact


def _recompute_consumed_basis(
    connection: "sqlalchemy.engine.Connection",
    lot_key: tuple[str, str],
) -> int:
    """Consumed basis of one lot replayed from its final active facts.

    Re-projection is retroactive: the lot's true history is the latest
    committed revision of every execution that touched it (busts leave no
    fact). Replaying that final set in original stream order is
    order-independent, unlike incremental consumption attribution across
    interleaved busts and corrections. Impossible states stay signed: an
    exit beyond the replayed entries exports preserved negative shares,
    and consumption is capped at the lot's available basis.
    """

    revision_rows = connection.execute(
        sa.text(
            "SELECT er.execution_id AS execution_id,"
            " er.revision AS revision,"
            " er.revision_kind AS revision_kind,"
            " e.payload_json AS payload_json,"
            " e.stream_version AS stream_version,"
            " e.economic_event_id AS economic_event_id"
            " FROM execution_revisions er"
            " JOIN economic_events e"
            " ON e.payload_content_hash = er.payload_content_hash"
            " WHERE e.position_lineage_id = :lineage"
            " AND e.economic_lot_id = :lot"
            " ORDER BY er.execution_id, er.revision"
        ),
        {"lineage": lot_key[0], "lot": lot_key[1]},
    ).all()

    # Latest committed revision per execution wins (rows arrive sorted by
    # revision); first-seen stream versions fix the replay order.
    final_by_execution: dict[str, object] = {}
    first_seen: dict[str, int] = {}
    for row in revision_rows:
        execution_id = row.execution_id
        stream_version = int(row.stream_version)
        if execution_id not in first_seen:
            first_seen[execution_id] = stream_version
        final_by_execution[execution_id] = row

    # Revision-1 fills carry no execution-revision fact: their quantity,
    # gross and side come from their own legs.
    legs_by_event: dict[str, list[tuple[str, str, int, int]]] = {}
    leg_rows = connection.execute(
        sa.text(
            "SELECT e.economic_event_id AS economic_event_id,"
            " l.asset_kind AS asset_kind,"
            " l.direction AS direction,"
            " l.cash_amount_cents AS cash_amount_cents,"
            " l.quantity_units AS quantity_units"
            " FROM economic_events e"
            " JOIN economic_event_legs l"
            " ON l.economic_event_id = e.economic_event_id"
            " WHERE e.position_lineage_id = :lineage"
            " AND e.economic_lot_id = :lot"
        ),
        {"lineage": lot_key[0], "lot": lot_key[1]},
    ).all()
    for leg in leg_rows:
        legs_by_event.setdefault(str(leg.economic_event_id), []).append(
            (
                leg.asset_kind,
                leg.direction,
                int(leg.cash_amount_cents or 0),
                int(leg.quantity_units or 0),
            )
        )

    active_by_execution: dict[str, tuple[str, int, int] | None] = {}
    for execution_id, row in final_by_execution.items():
        if row.revision_kind == "FILL_BUST":
            active_by_execution[execution_id] = None
        elif row.revision_kind == "FILL_CORRECTION":
            fact = _parse_execution_revision_fact(str(row.payload_json))
            assert fact is not None
            active_by_execution[execution_id] = (
                str(fact["side"]),
                int(fact["corrected_quantity"] or 0),
                int(fact["corrected_gross_cents"] or 0),
            )
        else:  # FILL
            quantity = 0
            gross = 0
            side = "ENTRY"
            for asset_kind, direction, cash, qty in legs_by_event.get(
                str(row.economic_event_id), []
            ):
                if asset_kind == "SECURITY":
                    quantity = qty
                    side = "ENTRY" if direction == "CREDIT" else "EXIT"
                elif asset_kind == "CASH":
                    gross = cash
            active_by_execution[execution_id] = (side, quantity, gross)

    quantity = 0
    basis = 0
    consumed_total = 0
    for execution_id in sorted(first_seen, key=lambda k: first_seen[k]):
        active = active_by_execution.get(execution_id)
        if active is None:
            continue
        side, fill_quantity, gross = active
        if side == "ENTRY":
            quantity += fill_quantity
            basis += gross
        else:
            if fill_quantity == quantity:
                consumed = basis
            elif quantity > 0:
                consumed = round_half_even_div(
                    basis * fill_quantity, quantity
                )
            else:
                consumed = 0
            consumed = max(0, min(consumed, max(basis, 0)))
            consumed_total += consumed
            quantity -= fill_quantity
            basis -= consumed
    return consumed_total


def _empty_report() -> ConservationReport:
    return ConservationReport(
        event_count=0,
        flow_event_count=0,
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
        subscription_suspense_cents=0,
        redemption_suspense_cents=0,
        issued_unit_quanta=0,
        pending_redeemed_unit_quanta=0,
    )


def _replay_economic_events(
    connection: "sqlalchemy.engine.Connection",
) -> dict[str, object]:
    """Replay the economic event legs exactly as Task 2 did."""

    rows = connection.execute(
        sa.text(
            "SELECT e.stream_version AS stream_version,"
            " e.event_kind AS event_kind,"
            " e.position_lineage_id AS position_lineage_id,"
            " e.economic_lot_id AS economic_lot_id,"
            " e.payload_content_hash AS payload_content_hash,"
            " e.payload_json AS payload_json,"
            " l.asset_kind AS asset_kind,"
            " l.direction AS direction,"
            " l.cash_amount_cents AS cash_amount_cents,"
            " l.quantity_units AS quantity_units,"
            " l.receivable_id AS receivable_id,"
            " l.security_id AS security_id"
            " FROM economic_events e"
            " JOIN economic_event_legs l"
            " ON l.economic_event_id = e.economic_event_id"
            " ORDER BY e.stream_version, l.sequence"
        )
    ).all()
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
    # Plan 02 Task 6: per-lot consumed basis. Lots touched by execution
    # revisions are recomputed from their final active fact set below
    # (retroactive re-projection makes incremental attribution
    # order-dependent).
    consumed_basis_by_lot: dict[tuple[str, str], int] = {}
    lots_with_revisions: set[tuple[str, str]] = set()
    receivable_by_id: dict[str, int] = {}
    share_receivable_by_id: dict[str, int] = {}
    share_receivable_by_lot: dict[tuple[str, str], int] = {}
    receivable_origin_dividend: dict[str, bool] = {}
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

    def book_cash_receivable(
        receivable_id: str, amount: int, *, income: bool
    ) -> None:
        nonlocal dividend_income
        if receivable_id in receivable_by_id:
            _fail("receivable credited twice", receivable_id=receivable_id)
        receivable_by_id[receivable_id] = amount
        receivable_origin_dividend[receivable_id] = income
        if income:
            dividend_income += amount

    def settle_cash_receivable(
        receivable_id: str, amount: int, *, reverse_income: bool
    ) -> None:
        nonlocal dividend_income
        outstanding = receivable_by_id.get(receivable_id)
        if outstanding is None:
            _fail(
                "receivable debit against unknown receivable",
                receivable_id=receivable_id,
            )
        if outstanding != amount:
            _fail(
                "receivable settlement amount mismatch",
                receivable_id=receivable_id,
            )
        del receivable_by_id[receivable_id]
        was_dividend = receivable_origin_dividend.pop(receivable_id, False)
        if reverse_income and was_dividend:
            dividend_income -= amount

    def book_share_receivable(
        key: tuple[str, str], receivable_id: str, quantity: int
    ) -> None:
        if receivable_id in share_receivable_by_id:
            _fail(
                "share receivable credited twice",
                receivable_id=receivable_id,
            )
        share_receivable_by_id[receivable_id] = quantity
        share_receivable_by_lot[key] = (
            share_receivable_by_lot.get(key, 0) + quantity
        )

    def settle_share_receivable(
        key: tuple[str, str], receivable_id: str, quantity: int
    ) -> None:
        outstanding = share_receivable_by_id.get(receivable_id)
        if outstanding is None:
            _fail(
                "share receivable debit against unknown receivable",
                receivable_id=receivable_id,
            )
        if outstanding != quantity:
            _fail(
                "share receivable settlement quantity mismatch",
                receivable_id=receivable_id,
            )
        del share_receivable_by_id[receivable_id]
        share_receivable_by_lot[key] = (
            share_receivable_by_lot.get(key, 0) - quantity
        )

    def consume_basis_for_lot(key: tuple[str, str], full: bool) -> None:
        """Consume lot basis: whole-lot takes the exact remainder."""

        nonlocal consumed_basis_total
        basis_before = basis_by_lot.get(key, 0)
        if full:
            consumed = basis_before
        else:
            consumed = basis_before  # pragma: no cover - callers use full
        basis_by_lot[key] = basis_before - consumed
        consumed_basis_total += consumed

    # Plan 02 Task 4: corporate action replay is event-shaped, because
    # conversion shapes, correction origin inheritance, and whole-lot
    # sweeps are event-level invariants.
    events: list[dict[str, object]] = []
    for row in rows:
        if not events or events[-1]["stream_version"] != row.stream_version:
            events.append(
                {
                    "stream_version": row.stream_version,
                    "event_kind": row.event_kind,
                    "lineage": row.position_lineage_id,
                    "lot": row.economic_lot_id,
                    "hash": row.payload_content_hash,
                    "payload_json": row.payload_json,
                    "legs": [],
                }
            )
        events[-1]["legs"].append(row)  # type: ignore[union-attr]

    for event in events:
        event_kind = EconomicEventKind(event["event_kind"])  # type: ignore[arg-type]
        event_legs = event["legs"]  # type: ignore[assignment]
        key = (event["lineage"], event["lot"])  # type: ignore[assignment]

        if event_kind is EconomicEventKind.VALUATION:
            # Mark-only legs carry no direction and move no cash, shares,
            # or receivables: conservation ignores them (NAV consistency is
            # verified against the observation path instead).
            continue

        for row in event_legs:
            if EconomicAssetKind(row.asset_kind) is EconomicAssetKind.COST_BASIS:
                _fail(
                    "COST_BASIS legs remain fail-closed in conservation",
                    stream_version=event["stream_version"],
                )

        if event_kind is EconomicEventKind.LATE_CORRECTION:
            revision_fact = _parse_execution_revision_fact(
                event["payload_json"]  # type: ignore[arg-type]
            )
            if revision_fact is not None:
                # Plan 02 Task 6: one execution bust/correction fact is
                # replayed from its frozen revision fields — the exact
                # signed reversal of the superseded contribution, then the
                # corrected contribution. Negative replayed quantities and
                # basis are preserved exactly (never clamped), mirroring
                # the kernel projection.
                for row in event_legs:
                    if (
                        EconomicAssetKind(row.asset_kind)
                        is EconomicAssetKind.CASH
                    ):
                        amount = int(row.cash_amount_cents)
                        if (
                            EconomicLegDirection(row.direction)
                            is EconomicLegDirection.CREDIT
                        ):
                            cash_credit_total += amount
                        else:
                            cash_debit_total += amount
                if revision_fact["fact_kind"] == "FEE":
                    fee_total += (
                        int(revision_fact["fee_commission_delta_cents"] or 0)
                        + int(revision_fact["fee_stamp_tax_delta_cents"] or 0)
                        + int(revision_fact["fee_transfer_fee_delta_cents"] or 0)
                    )
                    continue
                side = revision_fact["side"]
                superseded_quantity = int(
                    revision_fact["superseded_quantity"] or 0
                )
                superseded_gross = int(
                    revision_fact["superseded_gross_cents"] or 0
                )
                reversed_basis = int(
                    revision_fact["reversed_consumed_basis_cents"] or 0
                )
                corrected_quantity = int(
                    revision_fact["corrected_quantity"] or 0
                )
                corrected_gross = int(
                    revision_fact["corrected_gross_cents"] or 0
                )
                if superseded_quantity:
                    if side == "ENTRY":
                        entry_gross -= superseded_gross
                        quantity_by_lot[key] = (
                            quantity_by_lot.get(key, 0) - superseded_quantity
                        )
                        basis_by_lot[key] = (
                            basis_by_lot.get(key, 0) - superseded_gross
                        )
                    else:
                        exit_gross -= superseded_gross
                        quantity_by_lot[key] = (
                            quantity_by_lot.get(key, 0) + superseded_quantity
                        )
                        basis_by_lot[key] = (
                            basis_by_lot.get(key, 0) + reversed_basis
                        )
                        consumed_basis_total -= reversed_basis
                        consumed_basis_by_lot[key] = (
                            consumed_basis_by_lot.get(key, 0) - reversed_basis
                        )
                if corrected_quantity:
                    if side == "ENTRY":
                        entry_gross += corrected_gross
                        quantity_by_lot[key] = (
                            quantity_by_lot.get(key, 0) + corrected_quantity
                        )
                        basis_by_lot[key] = (
                            basis_by_lot.get(key, 0) + corrected_gross
                        )
                    else:
                        exit_gross += corrected_gross
                        before = quantity_by_lot.get(key, 0)
                        basis_before = basis_by_lot.get(key, 0)
                        if corrected_quantity == before:
                            consumed = basis_before
                        elif before > 0:
                            consumed = round_half_even_div(
                                basis_before * corrected_quantity, before
                            )
                        else:
                            consumed = 0
                        # Consumption is capped at the lot's available
                        # basis; the excess corrected quantity stays as a
                        # preserved negative replayed quantity.
                        consumed = min(consumed, max(basis_before, 0))
                        basis_by_lot[key] = basis_before - consumed
                        consumed_basis_total += consumed
                        consumed_basis_by_lot[key] = (
                            consumed_basis_by_lot.get(key, 0) + consumed
                        )
                        quantity_by_lot[key] = before - corrected_quantity
                # Lots touched by revisions get their consumed basis
                # recomputed from the final active fact set after the
                # stream walk: re-projection is retroactive, so
                # incremental consumption attribution is order-dependent
                # while the final-set recomputation is not.
                lots_with_revisions.add(key)
                continue
            cash_debit_ids = [
                row.receivable_id
                for row in event_legs
                if EconomicAssetKind(row.asset_kind)
                is EconomicAssetKind.CASH_RECEIVABLE
                and EconomicLegDirection(row.direction)
                is EconomicLegDirection.DEBIT
            ]
            inherited = bool(cash_debit_ids) and all(
                receivable_origin_dividend.get(receivable_id, False)
                for receivable_id in cash_debit_ids
            )
            for row in event_legs:
                asset_kind = EconomicAssetKind(row.asset_kind)
                direction = EconomicLegDirection(row.direction)
                if asset_kind is EconomicAssetKind.CASH_RECEIVABLE:
                    amount = int(row.cash_amount_cents)
                    if direction is EconomicLegDirection.CREDIT:
                        book_cash_receivable(
                            row.receivable_id, amount, income=inherited
                        )
                    else:
                        settle_cash_receivable(
                            row.receivable_id, amount, reverse_income=True
                        )
                elif asset_kind is EconomicAssetKind.SHARE_RECEIVABLE:
                    quantity = int(row.quantity_units)
                    if direction is EconomicLegDirection.CREDIT:
                        book_share_receivable(key, row.receivable_id, quantity)
                    else:
                        settle_share_receivable(
                            key, row.receivable_id, quantity
                        )
                else:
                    _fail(
                        "corporate action corrections are limited to"
                        " receivable deltas",
                        stream_version=event["stream_version"],
                        asset_kind=row.asset_kind,
                    )
            continue

        if event_kind is EconomicEventKind.SECURITY_CONVERTED:
            security_legs = [
                row
                for row in event_legs
                if EconomicAssetKind(row.asset_kind)
                is EconomicAssetKind.SECURITY
            ]
            security_debits = [
                row
                for row in security_legs
                if EconomicLegDirection(row.direction)
                is EconomicLegDirection.DEBIT
            ]
            security_credits = [
                row
                for row in security_legs
                if EconomicLegDirection(row.direction)
                is EconomicLegDirection.CREDIT
            ]
            share_debits = [
                row
                for row in event_legs
                if EconomicAssetKind(row.asset_kind)
                is EconomicAssetKind.SHARE_RECEIVABLE
                and EconomicLegDirection(row.direction)
                is EconomicLegDirection.DEBIT
            ]
            share_credits = [
                row
                for row in event_legs
                if EconomicAssetKind(row.asset_kind)
                is EconomicAssetKind.SHARE_RECEIVABLE
                and EconomicLegDirection(row.direction)
                is EconomicLegDirection.CREDIT
            ]
            representation_change = (
                len(security_debits) == 1
                and len(security_credits) == 1
                and security_debits[0].security_id
                == security_credits[0].security_id
                and int(security_debits[0].quantity_units)
                == int(security_credits[0].quantity_units)
                and bool(share_debits)
                and not share_credits
            )
            if representation_change:
                quantity = int(security_debits[0].quantity_units)
                share_debit_total = sum(
                    int(row.quantity_units) for row in share_debits
                )
                if share_debit_total != quantity:
                    _fail(
                        "tradable-date conversion legs do not balance",
                        stream_version=event["stream_version"],
                    )
                for row in share_debits:
                    settle_share_receivable(
                        key, row.receivable_id, int(row.quantity_units)
                    )
                    # Vested receivable shares become settled tradable
                    # quantity; the same-security pair is a representation
                    # change only and nets to zero settled shares.
                    quantity_by_lot[key] = (
                        quantity_by_lot.get(key, 0) + int(row.quantity_units)
                    )
                continue
            # Whole-lot conversion: the security debits sweep the whole
            # economic holding (settled shares plus vested receivable
            # shares), the share debits settle every outstanding share
            # receivable row, and the single destination credit carries
            # the lot forward. Conversions preserve the aggregate cost
            # basis: the lot identity and its basis move through to the
            # successor untouched.
            settled_before = quantity_by_lot.get(key, 0)
            receivable_before = share_receivable_by_lot.get(key, 0)
            security_debit_total = sum(
                int(row.quantity_units) for row in security_debits
            )
            if security_debit_total != settled_before + receivable_before:
                _fail(
                    "conversion must sweep the whole economic holding",
                    position_lineage_id=key[0],
                    economic_lot_id=key[1],
                    replayed_settled_units=settled_before,
                    replayed_receivable_units=receivable_before,
                    debited_units=security_debit_total,
                )
            share_debit_total = 0
            for row in share_debits:
                settle_share_receivable(
                    key, row.receivable_id, int(row.quantity_units)
                )
                share_debit_total += int(row.quantity_units)
            if share_debit_total != receivable_before:
                _fail(
                    "conversion must settle every outstanding share"
                    " receivable of the lot",
                    position_lineage_id=key[0],
                    economic_lot_id=key[1],
                    replayed_receivable_units=receivable_before,
                    settled_units=share_debit_total,
                )
            quantity_by_lot[key] = 0
            for row in security_credits:
                quantity_by_lot[key] = quantity_by_lot.get(key, 0) + int(
                    row.quantity_units
                )
            for row in share_credits:
                book_share_receivable(
                    key, row.receivable_id, int(row.quantity_units)
                )
            continue

        if event_kind in (EconomicEventKind.SPLIT, EconomicEventKind.MERGE):
            for row in event_legs:
                asset_kind = EconomicAssetKind(row.asset_kind)
                if asset_kind is not EconomicAssetKind.SECURITY:
                    _fail(
                        "split/merge events carry security legs only",
                        stream_version=event["stream_version"],
                    )
                quantity = int(row.quantity_units)
                if EconomicLegDirection(row.direction) is (
                    EconomicLegDirection.CREDIT
                ):
                    quantity_by_lot[key] = (
                        quantity_by_lot.get(key, 0) + quantity
                    )
                else:
                    before = quantity_by_lot.get(key, 0)
                    if quantity > before:
                        _fail(
                            "security debit exceeds replayed position"
                            " quantity",
                            position_lineage_id=key[0],
                            economic_lot_id=key[1],
                        )
                    # Splits/merges preserve the aggregate basis exactly.
                    quantity_by_lot[key] = before - quantity
            continue

        if event_kind in (
            EconomicEventKind.CORPORATE_CASH_SETTLED,
            EconomicEventKind.LEGAL_WRITE_OFF,
        ):
            cash_settled = (
                event_kind is EconomicEventKind.CORPORATE_CASH_SETTLED
            )
            security_debit_total = 0
            for row in event_legs:
                asset_kind = EconomicAssetKind(row.asset_kind)
                direction = EconomicLegDirection(row.direction)
                if asset_kind is EconomicAssetKind.SECURITY:
                    if direction is not EconomicLegDirection.DEBIT:
                        _fail(
                            "terminal corporate action security legs must be"
                            " debits",
                            stream_version=event["stream_version"],
                        )
                    security_debit_total += int(row.quantity_units)
                elif asset_kind is EconomicAssetKind.SHARE_RECEIVABLE:
                    if direction is not EconomicLegDirection.DEBIT:
                        _fail(
                            "terminal corporate action share receivable legs"
                            " must be debits",
                            stream_version=event["stream_version"],
                        )
                    settle_share_receivable(
                        key, row.receivable_id, int(row.quantity_units)
                    )
                elif asset_kind is EconomicAssetKind.CASH_RECEIVABLE:
                    if direction is not EconomicLegDirection.DEBIT:
                        _fail(
                            "terminal corporate action receivable legs must"
                            " be debits",
                            stream_version=event["stream_version"],
                        )
                    # The swept receivable never pays as its own cash leg:
                    # a cash settlement folds it into the proceeds and a
                    # write-off loses it outright. Both reverse the income
                    # accrued at the ex date, so the proceeds (or the loss)
                    # carry the whole economic result exactly once.
                    settle_cash_receivable(
                        row.receivable_id,
                        int(row.cash_amount_cents),
                        reverse_income=True,
                    )
                elif asset_kind is EconomicAssetKind.CASH:
                    if direction is not EconomicLegDirection.CREDIT:
                        _fail(
                            "terminal corporate action cash legs must be"
                            " credits",
                            stream_version=event["stream_version"],
                        )
                    if not cash_settled:
                        _fail(
                            "legal write-off cannot move cash",
                            stream_version=event["stream_version"],
                        )
                    amount = int(row.cash_amount_cents)
                    cash_credit_total += amount
                    # Terminal disposal proceeds are realized results.
                    exit_gross += amount
                else:  # pragma: no cover - matrix is closed
                    _fail(
                        "unsupported terminal corporate action leg",
                        asset_kind=row.asset_kind,
                    )
            before = quantity_by_lot.get(key, 0)
            if security_debit_total != before:
                _fail(
                    "terminal corporate action must sweep the whole lot",
                    position_lineage_id=key[0],
                    economic_lot_id=key[1],
                    replayed_units=before,
                    debited_units=security_debit_total,
                )
            quantity_by_lot[key] = 0
            consume_basis_for_lot(key, full=True)
            continue

        for row in event_legs:
            asset_kind = EconomicAssetKind(row.asset_kind)
            if asset_kind is EconomicAssetKind.VALUATION_MARK:
                continue
            direction = EconomicLegDirection(row.direction)

            if asset_kind is EconomicAssetKind.CASH:
                amount = int(row.cash_amount_cents)
                if direction is EconomicLegDirection.CREDIT:
                    cash_credit_total += amount
                else:
                    cash_debit_total += amount
                if event_kind is EconomicEventKind.TRADE_EXECUTED:
                    if direction is EconomicLegDirection.DEBIT:
                        entry_gross += amount
                    else:
                        exit_gross += amount
                    trade_event_hashes.add(event["hash"])  # type: ignore[arg-type]
                elif event_kind is EconomicEventKind.FEE_CHARGED:
                    if direction is not EconomicLegDirection.DEBIT:
                        _fail(
                            "fee event cash leg must be a debit",
                            stream_version=event["stream_version"],
                        )
                    fee_total += amount
                    fee_event_hashes.add(event["hash"])  # type: ignore[arg-type]

            elif asset_kind is EconomicAssetKind.SECURITY:
                quantity = int(row.quantity_units)
                if direction is EconomicLegDirection.CREDIT:
                    quantity_by_lot[key] = (
                        quantity_by_lot.get(key, 0) + quantity
                    )
                    if event_kind is EconomicEventKind.TRADE_EXECUTED:
                        # Entry gross cash becomes cost basis (one fact, one
                        # event: the cash debit of the same event).
                        gross = trade_cash_debit_by_version.get(
                            event["stream_version"], 0  # type: ignore[arg-type]
                        )
                        basis_by_lot[key] = basis_by_lot.get(key, 0) + gross
                else:
                    before = quantity_by_lot.get(key, 0)
                    if quantity > before:
                        _fail(
                            "security debit exceeds replayed position"
                            " quantity",
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
                        consumed_basis_by_lot[key] = (
                            consumed_basis_by_lot.get(key, 0) + consumed
                        )

            elif asset_kind is EconomicAssetKind.CASH_RECEIVABLE:
                amount = int(row.cash_amount_cents)
                if direction is EconomicLegDirection.CREDIT:
                    book_cash_receivable(
                        row.receivable_id,
                        amount,
                        income=(
                            event_kind
                            is EconomicEventKind.DIVIDEND_RECEIVABLE
                        ),
                    )
                else:
                    # Payment of a booked entitlement is an asset swap: the
                    # income was recognized at the ex date and is never
                    # reversed by settlement.
                    settle_cash_receivable(
                        row.receivable_id, amount, reverse_income=False
                    )

            elif asset_kind is EconomicAssetKind.SHARE_RECEIVABLE:
                quantity = int(row.quantity_units)
                if direction is EconomicLegDirection.CREDIT:
                    book_share_receivable(key, row.receivable_id, quantity)
                else:
                    settle_share_receivable(
                        key, row.receivable_id, quantity
                    )

    # Plan 02 Task 6: consumed basis of revision-touched lots is the
    # final-active-fact recomputation (order-independent); the incremental
    # attribution above is exact only for lots without revisions.
    for lot_key in lots_with_revisions:
        recomputed = _recompute_consumed_basis(connection, lot_key)
        consumed_basis_total += recomputed - consumed_basis_by_lot.get(
            lot_key, 0
        )
        consumed_basis_by_lot[lot_key] = recomputed

    return {
        "cash_delta": cash_credit_total - cash_debit_total,
        "entry_gross": entry_gross,
        "exit_gross": exit_gross,
        "fee_total": fee_total,
        "dividend_income": dividend_income,
        "quantity_by_lot": quantity_by_lot,
        "basis_by_lot": basis_by_lot,
        "consumed_basis_total": consumed_basis_total,
        "receivable_by_id": receivable_by_id,
        "share_receivable_by_id": share_receivable_by_id,
        "share_receivable_by_lot": share_receivable_by_lot,
        "trade_event_hashes": trade_event_hashes,
        "fee_event_hashes": fee_event_hashes,
    }


def _replay_flow_events(
    connection: "sqlalchemy.engine.Connection",
) -> dict[str, object]:
    """Replay the append-only financing flow stream.

    Cash deltas: genesis and subscription receipts add cash; subscription
    refunds/cancellations and redemption payments remove cash. Unit quanta
    and payables replay from the same rows, and the redemption-suspense
    bucket follows the deterministic pay-from-suspense-first rule.
    """

    rows = connection.execute(
        sa.text("SELECT * FROM capital_flow_events ORDER BY flow_version")
    ).all()
    versions = [int(row.flow_version) for row in rows]
    if versions != list(range(1, len(versions) + 1)):
        _fail("flow event stream is not contiguous", versions=versions)

    opening_capital = 0
    external_flows = 0
    cash_delta = 0
    issued_units = 0
    pending_units = 0
    sub_suspense = 0
    red_suspense = 0
    payables: dict[str, dict[str, object]] = {}

    for row in rows:
        kind = FlowKind(row.flow_kind)
        if kind is FlowKind.GENESIS:
            opening_capital += int(row.cash_amount_cents)
            cash_delta += int(row.cash_amount_cents)
            issued_units += int(row.issued_unit_quanta)
        elif kind is FlowKind.SUBSCRIPTION_RECEIVED:
            cash_delta += int(row.cash_amount_cents)
            sub_suspense += int(row.cash_amount_cents)
            payable_id = row.payable_id
            if payable_id is None or payable_id in payables:
                _fail(
                    "subscription receipt payable identity conflict",
                    flow_version=row.flow_version,
                )
            payables[payable_id] = {
                "kind": SUBSCRIPTION_PAYABLE,
                "amount": int(row.cash_amount_cents),
                "open": True,
            }
        elif kind is FlowKind.SUBSCRIPTION_SETTLED:
            consumed = int(row.cash_amount_cents)
            refund = int(row.refund_cents or 0)
            cash_delta -= refund
            external_flows += consumed
            issued_units += int(row.issued_unit_quanta)
            sub_suspense -= consumed + refund
            payable = payables.get(row.payable_id)
            if payable is None or not payable["open"]:
                _fail(
                    "subscription settle references no open payable",
                    flow_version=row.flow_version,
                )
            payable["open"] = False
        elif kind is FlowKind.SUBSCRIPTION_CANCELLED:
            refund = int(row.refund_cents)
            cash_delta -= refund
            sub_suspense -= refund
            payable = payables.get(row.payable_id)
            if payable is None or not payable["open"]:
                _fail(
                    "subscription cancellation references no open payable",
                    flow_version=row.flow_version,
                )
            payable["open"] = False
        elif kind is FlowKind.REDEMPTION_SETTLED:
            payout = int(row.cash_amount_cents)
            reserved = int(row.reserved_cents or 0)
            red_suspense += reserved
            # Equity leaves the unit holders when the payable is confirmed,
            # not when the cash is later paid out: the payment discharges
            # assets and liabilities together and is equity-neutral.
            external_flows -= payout
            cancelled = int(row.cancelled_unit_quanta or 0)
            pending = int(row.pending_unit_quanta or 0)
            issued_units -= cancelled
            pending_units += pending
            payable_id = row.payable_id
            if payable_id is None or payable_id in payables:
                _fail(
                    "redemption settle payable identity conflict",
                    flow_version=row.flow_version,
                )
            payables[payable_id] = {
                "kind": REDEMPTION_PAYABLE,
                "amount": payout,
                "open": True,
            }
        elif kind is FlowKind.REDEMPTION_PAID:
            paid = int(row.cash_amount_cents)
            from_suspense = min(red_suspense, paid)
            red_suspense -= from_suspense
            cash_delta -= paid
            payable = payables.get(row.payable_id)
            if payable is None or not payable["open"]:
                _fail(
                    "redemption payment references no open payable",
                    flow_version=row.flow_version,
                )
            remaining = int(payable["amount"]) - paid
            if remaining < 0:
                _fail(
                    "redemption payment exceeds the open payable",
                    flow_version=row.flow_version,
                )
            payable["amount"] = remaining
            if remaining == 0:
                payable["open"] = False
            pending_units -= int(row.burnt_unit_quanta or 0)
            issued_units -= int(row.burnt_unit_quanta or 0)
        else:  # pragma: no cover - FlowKind is a closed enum
            _fail("unknown flow kind", flow_kind=row.flow_kind)

        if sub_suspense < 0 or red_suspense < 0:
            _fail(
                "suspense replay went negative",
                flow_version=row.flow_version,
            )
        if pending_units < 0 or issued_units < 0:
            _fail(
                "unit replay went negative",
                flow_version=row.flow_version,
            )

    return {
        "flow_event_count": len(rows),
        "opening_capital": opening_capital,
        "external_flows": external_flows,
        "cash_delta": cash_delta,
        "issued_units": issued_units,
        "pending_units": pending_units,
        "sub_suspense": sub_suspense,
        "red_suspense": red_suspense,
        "payables": payables,
    }


def _verify_nav_observations(
    connection: "sqlalchemy.engine.Connection",
) -> None:
    """Internal consistency of the two preserved NAV paths.

    Unit prices are exact lowest-terms rationals; log growth uses the typed
    sentinels with integer ratio fields; restated observations carry an
    explicit append-only link back to the as-observed row and the matching
    ``event_revisions`` entry.
    """

    rows = connection.execute(
        sa.text("SELECT * FROM nav_observations ORDER BY rowid")
    ).all()
    by_id = {row.nav_observation_id: row for row in rows}
    series: dict[str, list[object]] = {
        ObservationKind.AS_OBSERVED.value: [],
        ObservationKind.RESTATED_FINAL.value: [],
    }
    for row in rows:
        series[row.observation_kind].append(row)

    event_by_id = {
        event_row.economic_event_id: event_row
        for event_row in connection.execute(
            sa.text(
                "SELECT economic_event_id, event_kind, correction_of_event_id"
                " FROM economic_events"
            )
        ).all()
    }
    revision_links = {
        (revision.canonical_event_id, revision.revision_event_id)
        for revision in connection.execute(
            sa.text("SELECT canonical_event_id, revision_event_id FROM event_revisions")
        ).all()
    }

    for kind_name, observations in series.items():
        prior_nav: int | None = None
        for row in observations:
            nav = int(row.nav_cents)
            live = int(row.live_unit_quanta)
            if live > 0:
                if (
                    row.unit_price_numerator is None
                    or row.unit_price_denominator is None
                ):
                    _fail(
                        "NAV observation missing its unit price rational",
                        nav_observation_id=row.nav_observation_id,
                    )
                numerator = int(row.unit_price_numerator)
                denominator = int(row.unit_price_denominator)
                if nav == 0:
                    expected = (0, 1)
                else:
                    divisor = gcd(abs(nav), live)
                    expected = (nav // divisor, live // divisor)
                if (numerator, denominator) != expected:
                    _fail(
                        "unit price is not the exact lowest-terms rational",
                        nav_observation_id=row.nav_observation_id,
                        stored=(numerator, denominator),
                        expected=expected,
                    )
            elif (
                row.unit_price_numerator is not None
                or row.unit_price_denominator is not None
            ):
                _fail(
                    "empty live denominator cannot carry a unit price",
                    nav_observation_id=row.nav_observation_id,
                )

            growth = LogGrowthKind(row.log_growth_kind)
            if growth is LogGrowthKind.NO_PRIOR_OBSERVATION:
                if (
                    row.log_growth_nav_numerator is not None
                    or row.log_growth_nav_denominator is not None
                ):
                    _fail(
                        "first observation cannot carry a growth ratio",
                        nav_observation_id=row.nav_observation_id,
                    )
            else:
                if (
                    row.log_growth_nav_numerator is None
                    or row.log_growth_nav_denominator is None
                ):
                    _fail(
                        "log growth requires integer ratio fields",
                        nav_observation_id=row.nav_observation_id,
                    )
                numerator = int(row.log_growth_nav_numerator)
                denominator = int(row.log_growth_nav_denominator)
                if growth is LogGrowthKind.NEGATIVE_INFINITY:
                    if numerator != 0:
                        _fail(
                            "negative-infinity sentinel requires zero numerator",
                            nav_observation_id=row.nav_observation_id,
                        )
                    if prior_nav is None or (nav > 0 and prior_nav > 0):
                        _fail(
                            "negative-infinity sentinel without an undefined"
                            " log return",
                            nav_observation_id=row.nav_observation_id,
                        )
                else:
                    if prior_nav is None or prior_nav <= 0 or nav <= 0:
                        _fail(
                            "finite log growth requires positive NAV pair",
                            nav_observation_id=row.nav_observation_id,
                        )
                    divisor = gcd(abs(nav), prior_nav)
                    if (numerator, denominator) != (
                        nav // divisor,
                        prior_nav // divisor,
                    ):
                        _fail(
                            "log growth ratio does not match the NAV pair",
                            nav_observation_id=row.nav_observation_id,
                        )
            prior_nav = nav

    for row in series[ObservationKind.RESTATED_FINAL.value]:
        superseded = by_id.get(row.supersedes_observation_id)
        if superseded is None:
            _fail(
                "restated observation lost its superseded link",
                nav_observation_id=row.nav_observation_id,
            )
        if (
            superseded.observation_kind
            != ObservationKind.AS_OBSERVED.value
        ):
            _fail(
                "restated observation must supersede an as-observed row",
                nav_observation_id=row.nav_observation_id,
            )
        restating_event = event_by_id.get(row.created_by_event_id)
        if (
            restating_event is None
            or restating_event.correction_of_event_id
            != superseded.created_by_event_id
        ):
            _fail(
                "restated observation event does not correct the restated"
                " valuation",
                nav_observation_id=row.nav_observation_id,
            )
        if (
            superseded.created_by_event_id,
            row.created_by_event_id,
        ) not in revision_links:
            _fail(
                "restatement missing its append-only event revision link",
                nav_observation_id=row.nav_observation_id,
            )


def verify_conservation(
    connection: "sqlalchemy.engine.Connection",
    metadata: sa.MetaData,
) -> ConservationReport:
    """Recompute all identities on one connection; raise on any mismatch."""

    binding_row = connection.execute(
        metadata.tables["account_capital_truth"].select()
    ).first()
    if binding_row is None:
        # An unbound ledger holds no economic facts: conservation is void.
        return _empty_report()

    # Every committed event must carry a frozen economic kind; the replay
    # consumes only typed facts, so an unknown kind fails closed here even
    # when the event carries no legs.
    known_kinds = {kind.value for kind in EconomicEventKind}
    distinct_kinds = connection.execute(
        sa.text("SELECT DISTINCT event_kind FROM economic_events")
    ).all()
    for row in distinct_kinds:
        if row.event_kind not in known_kinds:
            _fail(
                "unknown event kind in the economic history",
                event_kind=row.event_kind,
            )

    # -- replay inputs ---------------------------------------------------------

    economic = _replay_economic_events(connection)
    flows = _replay_flow_events(connection)

    event_count = connection.execute(
        sa.text("SELECT COUNT(*) AS n FROM economic_events")
    ).scalar()

    quantity_by_lot = economic["quantity_by_lot"]
    basis_by_lot = economic["basis_by_lot"]
    receivable_by_id = economic["receivable_by_id"]
    share_receivable_by_id = economic["share_receivable_by_id"]
    share_receivable_by_lot = economic["share_receivable_by_lot"]

    # -- stored projections ------------------------------------------------------

    projection = connection.execute(
        metadata.tables["capital_projection"].select()
    ).one()
    available = int(projection.available_cash_cents)
    restricted = int(projection.restricted_cash_cents)
    unsettled = int(projection.unsettled_cash_cents)
    sub_suspense_stored = int(projection.subscription_suspense_cash_cents)
    red_suspense_stored = int(projection.redemption_suspense_cash_cents)

    cash_recomputed = int(economic["cash_delta"]) + int(flows["cash_delta"])
    bucket_total = (
        available + restricted + unsettled + sub_suspense_stored
        + red_suspense_stored
    )
    if cash_recomputed != bucket_total:
        _fail(
            "cash conservation violated",
            recomputed_cents=cash_recomputed,
            stored_available_cents=available,
            stored_restricted_cents=restricted,
            stored_unsettled_cents=unsettled,
            stored_subscription_suspense_cents=sub_suspense_stored,
            stored_redemption_suspense_cents=red_suspense_stored,
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
    if available != (
        cash_recomputed - restricted - unsettled - sub_suspense_stored
        - red_suspense_stored
    ):
        _fail(
            "available cash split violated",
            available_cents=available,
            expected_cents=(
                cash_recomputed - restricted - unsettled - sub_suspense_stored
                - red_suspense_stored
            ),
        )
    if sub_suspense_stored != int(flows["sub_suspense"]):
        _fail(
            "subscription suspense drifted from flow history",
            stored_cents=sub_suspense_stored,
            recomputed_cents=int(flows["sub_suspense"]),
        )
    if red_suspense_stored != int(flows["red_suspense"]):
        _fail(
            "redemption suspense drifted from flow history",
            stored_cents=red_suspense_stored,
            recomputed_cents=int(flows["red_suspense"]),
        )
    if int(projection.issued_unit_quanta) != int(flows["issued_units"]):
        _fail(
            "issued unit quanta drifted from flow history",
            stored_units=int(projection.issued_unit_quanta),
            recomputed_units=int(flows["issued_units"]),
        )
    if int(projection.pending_redeemed_unit_quanta) != int(
        flows["pending_units"]
    ):
        _fail(
            "pending redeemed units drifted from flow history",
            stored_units=int(projection.pending_redeemed_unit_quanta),
            recomputed_units=int(flows["pending_units"]),
        )

    # Payables: every replayed open payable matches a stored OPEN row for
    # the exact amount, and every replayed settled payable matches a stored
    # SETTLED row.
    payable_rows = connection.execute(
        sa.text("SELECT * FROM payables")
    ).all()
    replayed_payables = flows["payables"]
    stored_by_id = {row.payable_id: row for row in payable_rows}
    for payable_id, replayed in replayed_payables.items():
        stored = stored_by_id.get(payable_id)
        if stored is None:
            _fail("replayed payable missing its stored row", payable_id=payable_id)
        if stored.payable_kind != replayed["kind"]:
            _fail("payable kind drifted from flow history", payable_id=payable_id)
        expected_state = (
            PayableState.OPEN.value
            if replayed["open"]
            else PayableState.SETTLED.value
        )
        if stored.state != expected_state:
            _fail(
                "payable state drifted from flow history",
                payable_id=payable_id,
                stored_state=stored.state,
                expected_state=expected_state,
            )
        if replayed["open"] and int(stored.amount_cents) != int(
            replayed["amount"]
        ):
            _fail(
                "open payable amount drifted from flow history",
                payable_id=payable_id,
                stored_cents=int(stored.amount_cents),
                recomputed_cents=int(replayed["amount"]),
            )
    for payable_id in stored_by_id:
        if payable_id not in replayed_payables:
            _fail("stored payable without flow history", payable_id=payable_id)
    # Subscription suspense equals open subscription payables exactly.
    open_subscription_payables = sum(
        int(replayed["amount"])
        for replayed in replayed_payables.values()
        if replayed["open"] and replayed["kind"] == SUBSCRIPTION_PAYABLE
    )
    if sub_suspense_stored != open_subscription_payables:
        _fail(
            "subscription suspense does not equal open subscription payables",
            suspense_cents=sub_suspense_stored,
            payable_cents=open_subscription_payables,
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
        expected_share_receivable = share_receivable_by_lot.get(key, 0)
        if (
            int(row.share_receivable_quantity_units)
            != expected_share_receivable
        ):
            _fail(
                "share receivable quantity drifted from event history",
                position_lineage_id=key[0],
                economic_lot_id=key[1],
                stored_units=int(row.share_receivable_quantity_units),
                recomputed_units=expected_share_receivable,
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
        # A lot is live while it holds settled OR vested-not-yet-tradable
        # shares (a restricted successor keeps the economic obligation).
        total_held = expected_quantity + expected_share_receivable
        if total_held == 0 and row.state not in ("CLOSED", "LEGAL_TERMINAL"):
            _fail("flat position must be terminal", position=key, state=row.state)
        if total_held > 0 and row.state not in ("OPEN", "EXIT_PENDING"):
            _fail("open position must be live", position=key, state=row.state)
    for key, quantity in quantity_by_lot.items():
        share_quantity = share_receivable_by_lot.get(key, 0)
        if (quantity > 0 or share_quantity > 0) and key not in stored_lots:
            _fail("replayed position missing its projection row", position=key)
    for key, share_quantity in share_receivable_by_lot.items():
        if share_quantity > 0 and key not in stored_lots:
            _fail("replayed position missing its projection row", position=key)

    receivable_rows = connection.execute(
        sa.text("SELECT * FROM receivables")
    ).all()
    cash_receivable_rows = [
        row for row in receivable_rows if row.receivable_kind == "CASH"
    ]
    share_receivable_rows = [
        row for row in receivable_rows if row.receivable_kind == "SHARE"
    ]
    recomputed_outstanding = sum(receivable_by_id.values())
    stored_outstanding = sum(
        int(row.amount_cents)
        for row in cash_receivable_rows
        if int(row.settled) == 0
    )
    if recomputed_outstanding != stored_outstanding:
        _fail(
            "receivable conservation violated",
            recomputed_cents=recomputed_outstanding,
            stored_cents=stored_outstanding,
        )
    for row in cash_receivable_rows:
        if int(row.settled) == 0:
            expected = receivable_by_id.get(row.receivable_id)
            if expected is None or int(row.amount_cents) != expected:
                _fail(
                    "outstanding receivable drifted from event history",
                    receivable_id=row.receivable_id,
                )
    for row in share_receivable_rows:
        if int(row.settled) == 0:
            expected = share_receivable_by_id.get(row.receivable_id)
            if expected is None or int(row.quantity_units) != expected:
                _fail(
                    "outstanding share receivable drifted from event history",
                    receivable_id=row.receivable_id,
                )
    outstanding_share_ids = {
        row.receivable_id
        for row in share_receivable_rows
        if int(row.settled) == 0
    }
    if outstanding_share_ids != set(share_receivable_by_id):
        _fail("share receivable projection drifted from event history")

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
    missing_fee_rows = economic["fee_event_hashes"] - fee_registry_hashes
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
    } - economic["trade_event_hashes"]
    if orphan_fills:
        _fail(
            "fill registry row without a canonical trade event",
            orphans=sorted(orphan_fills),
        )

    _verify_nav_observations(connection)

    # -- master identity ---------------------------------------------------------

    payables_total = sum(
        int(replayed["amount"])
        for replayed in replayed_payables.values()
        if replayed["open"]
    )

    realized_pnl_ex_fees = int(economic["exit_gross"]) - int(
        economic["consumed_basis_total"]
    )
    economic_pnl = (
        realized_pnl_ex_fees
        + int(economic["dividend_income"])
        - int(economic["fee_total"])
    )
    closing_cash = cash_recomputed
    # Plan 02 Task 6: impossible (negative) replayed states are preserved
    # signed in the ledger and surfaced by reconciliation_discrepancies(),
    # but they are not assets: the master identity closes over the sane
    # lots only.
    closing_basis = sum(
        basis
        for lot_key, basis in basis_by_lot.items()
        if basis > 0 and quantity_by_lot.get(lot_key, 0) >= 0
    )
    closing_assets = closing_cash + recomputed_outstanding + closing_basis
    liabilities = payables_total

    opening_capital = int(flows["opening_capital"])
    external_flows = int(flows["external_flows"])
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
        flow_event_count=int(flows["flow_event_count"]),
        opening_capital_cents=opening_capital,
        external_flow_cents=external_flows,
        entry_gross_cents=int(economic["entry_gross"]),
        exit_gross_cents=int(economic["exit_gross"]),
        consumed_cost_basis_cents=int(economic["consumed_basis_total"]),
        realized_pnl_ex_fees_cents=realized_pnl_ex_fees,
        dividend_income_cents=int(economic["dividend_income"]),
        total_fee_cents=int(economic["fee_total"]),
        economic_pnl_cents=economic_pnl,
        closing_cash_cents=closing_cash,
        closing_receivable_cents=recomputed_outstanding,
        closing_cost_basis_cents=closing_basis,
        closing_assets_cents=closing_assets,
        liabilities_cents=liabilities,
        available_cash_cents=available,
        restricted_cash_cents=restricted,
        reserved_cash_cents=reserved_total,
        subscription_suspense_cents=sub_suspense_stored,
        redemption_suspense_cents=red_suspense_stored,
        issued_unit_quanta=int(flows["issued_units"]),
        pending_redeemed_unit_quanta=int(flows["pending_units"]),
    )


__all__ = ["ConservationReport", "verify_conservation"]
