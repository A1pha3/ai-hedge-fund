"""Execution bust/correction commands, receipts, and reopen facts.

Plan 02 Task 6. Order lifecycle may be terminal, but economic truth is
correctable: a broker ``BUSTED``/``CORRECTED`` report appends a new
execution revision (charter item 16 / spec 15.1) and the capital
projection is recomputed from the append-only history — never patched in
place.

Revision semantics
------------------

- Revision 1 is the RECORDED fill fact (Plan 02 Task 2). Higher revisions
  are keyed by ``(execution_id, revision)``: ``BUSTED`` appends an exact
  compensation of the active fact (its effective filled quantity and gross
  cash become zero); ``CORRECTED`` equals busting the active value and
  applying the corrected value in one canonical event.
- Revisions are contiguous and monotonic: revision ``n`` requires the
  committed revision ``n - 1``; identical retries converge, divergent
  content under one revision identity fails closed.
- Fee revisions follow fill revisions: a fee bust/correction is accepted
  only after the linked fill has been busted/corrected, and recomputes the
  order's fee target from the active fill facts under the versioned fee
  policy.

Impossible states
-----------------

If the active revisions export negative shares or any other long-only
impossibility, the projection preserves the signed values exactly (never
clamped to zero, never dropped) and latches ``RECONCILIATION_HALT``; only
a source-authorized correction or legal settlement resolves it. Cash stays
fail-closed: a revision that would overdraw the cash projection is
rejected, because the kernel has no representation for negative cash in
the frozen snapshot contract.

Reopen
------

Whenever the same economic lot transitions from a flat/nonpositive
projection back to a positive holding through a correction or an exit
bust, the lot re-enters ``EXIT_PENDING`` with the
``REOPENED_BY_CORRECTION`` projection and one durable
:class:`ReopenedEconomicLot` fact is appended for Plan 04's ExitMandate
projection. The reopen row carries the stable lot identity, its full risk
attribution, and a mandate revision floor of 2: revision 1 belongs to
INITIAL mandates only, and Plan 04 must advance the floor strictly beyond
every mandate revision the lot has ever seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from src.screening.offensive.v3.capital.fees import FeeRevisionKind
from src.screening.offensive.v3.capital.rounding import round_half_even_div
from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    CashEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventLeg,
    EconomicLegDirection,
    ExecutionRevisionKind,
    ExecutionSide,
    PositionState,
    SecurityEconomicEventLeg,
    UtcInstant,
)
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr
from src.screening.offensive.v3.storage.metadata import CENT_SCALE


PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
RevisionNumber = Annotated[int, Field(ge=2)]

REOPEN_POSITION_STATE = PositionState.EXIT_PENDING
"""A reopened lot always carries a due exit obligation (charter item 9)."""

MANDATE_REVISION_FLOOR = 2
"""Revision 1 belongs to INITIAL mandates only; a reopen starts at >= 2."""

# Registry revision_kind values (append-only execution_revisions rows).
FILL_KIND = "FILL"
FEE_KIND = "FEE"
FILL_BUST_KIND = "FILL_BUST"
FILL_CORRECTION_KIND = "FILL_CORRECTION"
FEE_BUST_KIND = "FEE_BUST"
FEE_CORRECTION_KIND = "FEE_CORRECTION"

FILL_REVISION_KINDS = frozenset({FILL_KIND, FILL_BUST_KIND, FILL_CORRECTION_KIND})
FEE_REVISION_KINDS = frozenset({FEE_KIND, FEE_BUST_KIND, FEE_CORRECTION_KIND})

# entry_tombstones identities and reasons.
LOT_TOMBSTONE_PREFIX = "lot:"
RESERVE_TOMBSTONE_PREFIX = "reserve:"
TOMBSTONE_REASON_EXECUTION_BUSTED = "EXECUTION_BUSTED"
TOMBSTONE_REASON_ENTRY_INVALIDATED = "ENTRY_INVALIDATED"

# event_revisions.revision_kind values.
EVENT_REVISION_LINK_KIND = "EXECUTION_REVISION"


def registry_kind_for_fill_revision(kind: ExecutionRevisionKind) -> str:
    if kind is ExecutionRevisionKind.BUSTED:
        return FILL_BUST_KIND
    if kind is ExecutionRevisionKind.CORRECTED:
        return FILL_CORRECTION_KIND
    return FILL_KIND


def registry_kind_for_fee_revision(kind: FeeRevisionKind) -> str:
    if kind is FeeRevisionKind.BUSTED:
        return FEE_BUST_KIND
    if kind is FeeRevisionKind.CORRECTED:
        return FEE_CORRECTION_KIND
    return FEE_KIND


def lot_tombstone_identity(position_lineage_id: str, economic_lot_id: str) -> str:
    return f"{LOT_TOMBSTONE_PREFIX}{position_lineage_id}:{economic_lot_id}"


def reserve_tombstone_identity(source_id: str) -> str:
    return f"{RESERVE_TOMBSTONE_PREFIX}{source_id}"


class ExecutionRevisionRequest(CanonicalModel):
    """One bust/correction revision of a recorded fill execution.

    ``BUSTED`` restates the active fact being superseded (the kernel
    verifies it against history and appends the exact compensation).
    ``CORRECTED`` restates the superseded fact (or nothing, when the
    active fact is already busted) and carries the corrected price and
    quantity. Identity fields (order, side, security, lot) must match the
    recorded fill exactly.
    """

    execution_id: NonEmptyStr
    revision: RevisionNumber
    revision_kind: ExecutionRevisionKind
    order_id: NonEmptyStr
    side: ExecutionSide
    security_id: NonEmptyStr
    # Lot identity is optional: omitted identities are resolved from the
    # recorded fill (and verified when given), so unattributed sentinel
    # lots can be revised without restating their derived identity.
    position_lineage_id: NonEmptyStr | None = None
    economic_lot_id: NonEmptyStr | None = None
    superseded_quantity: PositiveInt | None = None
    corrected_price_micros: PositiveInt | None = None
    corrected_quantity: PositiveInt | None = None
    source_authority: NonEmptyStr
    effective_at: UtcInstant
    as_of: UtcInstant
    expected_stream_version: NonNegativeInt

    @model_validator(mode="after")
    def validate_revision_shape(self) -> "ExecutionRevisionRequest":
        if self.as_of < self.effective_at:
            raise ValueError("as_of cannot precede effective_at")
        if self.revision_kind is ExecutionRevisionKind.RECORDED:
            raise ValueError("revision 1 facts are recorded as fills")
        has_lineage = self.position_lineage_id is not None
        has_lot = self.economic_lot_id is not None
        if has_lineage != has_lot:
            raise ValueError(
                "position_lineage_id and economic_lot_id are all-or-none"
            )
        corrected = (self.corrected_price_micros, self.corrected_quantity)
        if any(value is not None for value in corrected) and not all(
            value is not None for value in corrected
        ):
            raise ValueError("corrected price and quantity are all-or-none")
        if self.revision_kind is ExecutionRevisionKind.BUSTED:
            if self.superseded_quantity is None:
                raise ValueError("a bust restates the active fact it removes")
            if any(value is not None for value in corrected):
                raise ValueError("a bust applies no corrected fact")
        else:
            if any(value is None for value in corrected):
                raise ValueError("a correction carries the corrected fact")
        return self


class ExecutionRevisionReceipt(CanonicalModel):
    """The durable outcome of one recorded execution bust/correction."""

    execution_id: NonEmptyStr
    order_id: NonEmptyStr
    revision: RevisionNumber
    revision_kind: ExecutionRevisionKind
    event_id: NonEmptyStr
    superseded_event_id: NonEmptyStr | None
    side: ExecutionSide
    security_id: NonEmptyStr
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    reversed_gross_cents: NonNegativeInt
    reversed_quantity: NonNegativeInt
    reversed_consumed_basis_cents: NonNegativeInt | None
    applied_gross_cents: NonNegativeInt
    applied_quantity: NonNegativeInt
    applied_consumed_basis_cents: NonNegativeInt | None
    reopened: bool
    reconciliation_halted: bool
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


class ExecutionRevisionFactKind(StrEnum):
    """Which execution fact stream one revision event belongs to."""

    FILL = "FILL"
    FEE = "FEE"


class ExecutionRevisionFact(CanonicalModel):
    """The canonical fact persisted on one execution revision event.

    The projection and the conservation replay both recompute from these
    frozen fields; the replay additionally cross-verifies every recorded
    amount against its own deterministic walk of the event history.
    """

    fact_kind: ExecutionRevisionFactKind
    revision_kind: ExecutionRevisionKind
    execution_id: NonEmptyStr
    revision: RevisionNumber
    order_id: NonEmptyStr
    side: ExecutionSide | None = None
    security_id: NonEmptyStr | None = None
    position_lineage_id: NonEmptyStr | None = None
    economic_lot_id: NonEmptyStr | None = None
    producer_namespace: NonEmptyStr | None = None
    research_program_id: NonEmptyStr | None = None
    economic_lineage_id: NonEmptyStr | None = None
    stage_id: NonEmptyStr | None = None
    superseded_quantity: PositiveInt | None = None
    superseded_gross_cents: PositiveInt | None = None
    reversed_consumed_basis_cents: NonNegativeInt | None = None
    corrected_price_micros: PositiveInt | None = None
    corrected_quantity: PositiveInt | None = None
    corrected_gross_cents: PositiveInt | None = None
    corrected_consumed_basis_cents: NonNegativeInt | None = None
    # Fee revisions book one signed delta per fee component so the order's
    # charged history stays decomposed (a refund is negative).
    fee_commission_delta_cents: int | None = None
    fee_stamp_tax_delta_cents: int | None = None
    fee_transfer_fee_delta_cents: int | None = None

    @model_validator(mode="after")
    def validate_fact_shape(self) -> "ExecutionRevisionFact":
        fee_deltas = (
            self.fee_commission_delta_cents,
            self.fee_stamp_tax_delta_cents,
            self.fee_transfer_fee_delta_cents,
        )
        if self.fact_kind is ExecutionRevisionFactKind.FEE:
            if any(delta is None for delta in fee_deltas):
                raise ValueError("fee revisions record their booked deltas")
            if self.revision_kind is ExecutionRevisionKind.RECORDED:
                raise ValueError("fee revisions bust or correct")
            return self
        if any(delta is not None for delta in fee_deltas):
            raise ValueError("fill revisions carry no fee deltas")
        required = (
            self.side,
            self.security_id,
            self.position_lineage_id,
            self.economic_lot_id,
            self.producer_namespace,
            self.research_program_id,
            self.economic_lineage_id,
            self.stage_id,
        )
        if any(value is None for value in required):
            raise ValueError(
                "fill revisions carry lot identity and full attribution"
            )
        superseded = (
            self.superseded_quantity,
            self.superseded_gross_cents,
        )
        if any(value is not None for value in superseded) and not all(
            value is not None for value in superseded
        ):
            raise ValueError("superseded fill facts are all-or-none")
        corrected = (
            self.corrected_price_micros,
            self.corrected_quantity,
            self.corrected_gross_cents,
        )
        if any(value is not None for value in corrected) and not all(
            value is not None for value in corrected
        ):
            raise ValueError("corrected fill facts are all-or-none")
        if self.revision_kind is ExecutionRevisionKind.BUSTED:
            if any(value is None for value in superseded):
                raise ValueError("a bust reverses the superseded fill fact")
            if any(value is not None for value in corrected):
                raise ValueError("a bust applies no corrected fill fact")
            if self.reversed_consumed_basis_cents is None and (
                self.side is ExecutionSide.EXIT
            ):
                raise ValueError("an exit bust records its basis refund")
        elif self.revision_kind is ExecutionRevisionKind.CORRECTED:
            if any(value is None for value in corrected):
                raise ValueError("a correction applies the corrected fact")
            if self.corrected_consumed_basis_cents is None and (
                self.side is ExecutionSide.EXIT
            ):
                raise ValueError("an exit correction records consumed basis")
        else:
            raise ValueError("recorded facts are fills, not revisions")
        return self


class ReopenedEconomicLot(CanonicalModel):
    """One durable reopened exit obligation (Plan 04 consumption seam).

    Appended exactly when a bust/correction transitions an economic lot
    from a flat or nonpositive projection back to a positive holding. The
    row names the stable lot identity, its risk attribution, the position
    state the reopen restores (``EXIT_PENDING``), and the execution
    revision provenance; ``mandate_revision_floor`` is the kernel's floor
    for the reopened ExitMandate revision (strictly greater than 1, since
    revision 1 belongs to INITIAL mandates).
    """

    reopen_id: NonEmptyStr
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    security_id: NonEmptyStr
    producer_namespace: NonEmptyStr
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    reopened_quantity_units: PositiveInt
    position_state: PositionState
    reopen_reason: NonEmptyStr
    mandate_revision_floor: PositiveInt
    reopened_by_execution_revision_id: NonEmptyStr
    reopened_by_event_id: NonEmptyStr
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


class ReconciliationDiscrepancy(CanonicalModel):
    """One preserved impossible position state under reconciliation halt.

    Negative (or otherwise long-only impossible) projections are kept
    signed in the ledger and surfaced here; they are never clamped to
    zero, dropped, or papered over with valuation events.
    """

    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    security_id: NonEmptyStr
    settled_quantity_units: int
    tradable_quantity_units: int
    cost_basis_cents: int


@dataclass(frozen=True)
class LotEventFact:
    """One lot-affecting fact in stream order (pure replay input)."""

    event_id: str
    stream_version: int
    kind: str  # "TRADE" or "REVISION"
    side: ExecutionSide | None = None
    gross_cents: int = 0
    quantity: int = 0
    # Revision facts (kind == "REVISION"):
    revision_kind: ExecutionRevisionKind | None = None
    superseded_side: ExecutionSide | None = None
    superseded_gross_cents: int = 0
    superseded_quantity: int = 0
    reversed_consumed_basis_cents: int = 0
    corrected_gross_cents: int = 0
    corrected_quantity: int = 0
    corrected_consumed_basis_cents: int = 0


@dataclass
class LotReplayState:
    """Deterministic state of one economic lot replayed in stream order."""

    quantity: int = 0
    basis_cents: int = 0
    consumed_basis_total_cents: int = 0
    consumed_basis_by_exit_event: dict[str, int] | None = None
    facts_by_event: dict[str, LotEventFact] | None = None


def replay_lot_fact(state: LotReplayState, fact: LotEventFact) -> None:
    """Apply one lot fact with the exact Task 2 basis rules.

    Entry gross cash becomes cost basis; exits consume basis
    round-half-even with the exact remainder on whole-lot exits. Revision
    facts reverse their superseded contribution (refunding the recorded
    consumed basis for exits) and then apply their corrected fact; the
    kernel and the conservation replay share this one implementation, and
    impossible (negative) projections are preserved, never clamped.
    """

    if state.consumed_basis_by_exit_event is None:
        state.consumed_basis_by_exit_event = {}
    if state.facts_by_event is None:
        state.facts_by_event = {}
    state.facts_by_event[fact.event_id] = fact

    if fact.kind == "TRADE":
        if fact.side is ExecutionSide.ENTRY:
            state.quantity += fact.quantity
            state.basis_cents += fact.gross_cents
        else:
            before = state.quantity
            if fact.quantity == before:
                consumed = state.basis_cents
            elif before > 0:
                consumed = round_half_even_div(
                    state.basis_cents * fact.quantity, before
                )
            else:
                consumed = 0
            state.consumed_basis_by_exit_event[fact.event_id] = consumed
            state.consumed_basis_total_cents += consumed
            state.quantity -= fact.quantity
            state.basis_cents -= consumed
        return

    # Revision facts: reverse the superseded contribution, then apply the
    # corrected one (busts have no corrected fact).
    if fact.superseded_side is ExecutionSide.ENTRY:
        state.quantity -= fact.superseded_quantity
        state.basis_cents -= fact.superseded_gross_cents
    elif fact.superseded_side is ExecutionSide.EXIT:
        state.quantity += fact.superseded_quantity
        state.basis_cents += fact.reversed_consumed_basis_cents
        state.consumed_basis_total_cents -= fact.reversed_consumed_basis_cents
    if fact.revision_kind is ExecutionRevisionKind.CORRECTED:
        if fact.superseded_side is ExecutionSide.ENTRY:
            state.quantity += fact.corrected_quantity
            state.basis_cents += fact.corrected_gross_cents
        else:
            before = state.quantity
            if fact.corrected_quantity == before:
                consumed = state.basis_cents
            elif before > 0:
                consumed = round_half_even_div(
                    state.basis_cents * fact.corrected_quantity, before
                )
            else:
                consumed = 0
            # A corrected exit can never consume basis the lot does not
            # hold: an oversized corrected quantity exports the excess as
            # preserved negative shares with no additional basis consumed.
            consumed = min(consumed, max(state.basis_cents, 0))
            if state.consumed_basis_by_exit_event is not None:
                # The corrected exit consumes at correction time; record it
                # under the revision event identity for later reversals.
                state.consumed_basis_by_exit_event[fact.event_id] = consumed
            state.consumed_basis_total_cents += consumed
            state.quantity -= fact.corrected_quantity
            state.basis_cents -= consumed


def execution_revision_legs(
    idempotency_key: str, fact: ExecutionRevisionFact
) -> tuple[EconomicEventLeg, ...]:
    """Canonical legs of one execution revision event.

    Fill revisions carry the exact reversal of the superseded fact (and
    the corrected fact's legs): cash amounts reuse the recorded gross
    cents, so a busted fill reverses its cash and security legs exactly,
    rounding residue included. Fee revisions carry one signed cash leg
    per nonzero booked delta component. The kernel projection and the
    conservation replay share this one implementation.
    """

    legs: list[EconomicEventLeg] = []
    if fact.fact_kind is ExecutionRevisionFactKind.FEE:
        for name, delta in (
            ("commission", fact.fee_commission_delta_cents),
            ("stamp_tax", fact.fee_stamp_tax_delta_cents),
            ("transfer_fee", fact.fee_transfer_fee_delta_cents),
        ):
            if not delta:
                continue
            legs.append(
                CashEconomicEventLeg(
                    leg_id=f"{idempotency_key}:{name}",
                    direction=(
                        EconomicLegDirection.DEBIT
                        if int(delta) > 0
                        else EconomicLegDirection.CREDIT
                    ),
                    asset_kind=EconomicAssetKind.CASH,
                    cash_amount=Decimal(abs(int(delta))) / CENT_SCALE,
                )
            )
        return tuple(legs)

    def cash_leg(
        label: str, direction: EconomicLegDirection, cents: int
    ) -> CashEconomicEventLeg:
        return CashEconomicEventLeg(
            leg_id=f"{idempotency_key}:{label}",
            direction=direction,
            asset_kind=EconomicAssetKind.CASH,
            cash_amount=Decimal(cents) / CENT_SCALE,
        )

    def security_leg(
        label: str, direction: EconomicLegDirection, quantity: int
    ) -> SecurityEconomicEventLeg:
        assert fact.security_id is not None
        return SecurityEconomicEventLeg(
            leg_id=f"{idempotency_key}:{label}",
            direction=direction,
            asset_kind=EconomicAssetKind.SECURITY,
            security_id=fact.security_id,
            quantity=quantity,
        )

    if fact.superseded_gross_cents is not None:
        superseded_gross = int(fact.superseded_gross_cents)
        assert fact.superseded_quantity is not None
        superseded_quantity = int(fact.superseded_quantity)
        if fact.side is ExecutionSide.ENTRY:
            legs.append(
                cash_leg(
                    "reverse:cash",
                    EconomicLegDirection.CREDIT,
                    superseded_gross,
                )
            )
            legs.append(
                security_leg(
                    "reverse:security",
                    EconomicLegDirection.DEBIT,
                    superseded_quantity,
                )
            )
        else:
            legs.append(
                cash_leg(
                    "reverse:cash",
                    EconomicLegDirection.DEBIT,
                    superseded_gross,
                )
            )
            legs.append(
                security_leg(
                    "reverse:security",
                    EconomicLegDirection.CREDIT,
                    superseded_quantity,
                )
            )
    if fact.corrected_gross_cents is not None:
        corrected_gross = int(fact.corrected_gross_cents)
        assert fact.corrected_quantity is not None
        corrected_quantity = int(fact.corrected_quantity)
        if fact.side is ExecutionSide.ENTRY:
            legs.append(
                cash_leg(
                    "corrected:cash",
                    EconomicLegDirection.DEBIT,
                    corrected_gross,
                )
            )
            legs.append(
                security_leg(
                    "corrected:security",
                    EconomicLegDirection.CREDIT,
                    corrected_quantity,
                )
            )
        else:
            legs.append(
                cash_leg(
                    "corrected:cash",
                    EconomicLegDirection.CREDIT,
                    corrected_gross,
                )
            )
            legs.append(
                security_leg(
                    "corrected:security",
                    EconomicLegDirection.DEBIT,
                    corrected_quantity,
                )
            )
    return tuple(legs)


def lot_fact_for_revision(
    fact: ExecutionRevisionFact, event_id: str, stream_version: int
) -> LotEventFact:
    """The pure replay fact of one fill revision event."""

    return LotEventFact(
        event_id=event_id,
        stream_version=stream_version,
        kind="REVISION",
        revision_kind=fact.revision_kind,
        superseded_side=fact.side,
        superseded_gross_cents=(
            int(fact.superseded_gross_cents)
            if fact.superseded_gross_cents is not None
            else 0
        ),
        superseded_quantity=(
            int(fact.superseded_quantity)
            if fact.superseded_quantity is not None
            else 0
        ),
        reversed_consumed_basis_cents=(
            int(fact.reversed_consumed_basis_cents)
            if fact.reversed_consumed_basis_cents is not None
            else 0
        ),
        corrected_gross_cents=(
            int(fact.corrected_gross_cents)
            if fact.corrected_gross_cents is not None
            else 0
        ),
        corrected_quantity=(
            int(fact.corrected_quantity)
            if fact.corrected_quantity is not None
            else 0
        ),
        corrected_consumed_basis_cents=(
            int(fact.corrected_consumed_basis_cents)
            if fact.corrected_consumed_basis_cents is not None
            else 0
        ),
    )


__all__ = [
    "EVENT_REVISION_LINK_KIND",
    "FEE_BUST_KIND",
    "FEE_CORRECTION_KIND",
    "FEE_KIND",
    "FEE_REVISION_KINDS",
    "FILL_BUST_KIND",
    "FILL_CORRECTION_KIND",
    "FILL_KIND",
    "FILL_REVISION_KINDS",
    "LOT_TOMBSTONE_PREFIX",
    "MANDATE_REVISION_FLOOR",
    "REOPEN_POSITION_STATE",
    "RESERVE_TOMBSTONE_PREFIX",
    "TOMBSTONE_REASON_ENTRY_INVALIDATED",
    "TOMBSTONE_REASON_EXECUTION_BUSTED",
    "ExecutionRevisionFact",
    "ExecutionRevisionFactKind",
    "ExecutionRevisionReceipt",
    "ExecutionRevisionRequest",
    "LotEventFact",
    "LotReplayState",
    "ReconciliationDiscrepancy",
    "ReopenedEconomicLot",
    "execution_revision_legs",
    "lot_fact_for_revision",
    "lot_tombstone_identity",
    "registry_kind_for_fee_revision",
    "registry_kind_for_fill_revision",
    "replay_lot_fact",
    "reserve_tombstone_identity",
]
