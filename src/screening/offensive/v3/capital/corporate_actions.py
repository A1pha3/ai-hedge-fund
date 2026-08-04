"""Corporate action commands, receipts, and exact entitlement arithmetic.

Plan 02 Task 4. One real economic lot owns one corporate-action fact
stream per ``action_id``:

- ``record_entitlement`` books ex-date facts: cash dividends as cash
  receivables (DIVIDEND_RECEIVABLE) and bonus/transfer shares as share
  receivables (SHARE_RECEIVABLE), computed from exact rational
  per-share entitlements (integer numerator/denominator; never float).
  Fractional remainders stay exact rationals and may carry an
  issuer-declared cash-in-lieu receivable.
- ``settle_cash_in_lieu`` moves an outstanding cash entitlement
  receivable to cash on the pay date (DIVIDEND_CASH_SETTLED).
- ``make_shares_tradable`` converts a vested share receivable into
  settled tradable shares on the tradable date (a same-security
  SECURITY_CONVERTED representation change).
- ``apply_split_merge`` transforms quantities with the aggregate cost
  basis preserved exactly (per-share basis is a rational).
- ``convert_security`` maps a whole economic lot to a successor
  security: the successor inherits the lot identity, entry provenance,
  attribution, cost basis, and the due exit obligation (position state
  is preserved through the conversion).
- ``settle_terminal_cash`` (CORPORATE_CASH_SETTLED) and
  ``legal_write_off`` (LEGAL_WRITE_OFF) are the only two facts that may
  terminate a lot's economic obligation; both require CONFIRMED source
  authority, and write-off additionally requires a legal evidence
  reference.

Source-authority matrix: every fact carries a tier
(:class:`SourceAuthorityTier`). An AS_OBSERVED vendor fact may be
upgraded to CONFIRMED; a CONFIRMED fact can never be downgraded. A
confirmation changes only the unresolved delta: while the entitlement
receivable is unsettled the revision supersedes it (append-only
LATE_CORRECTION plus ``event_revisions`` link, the as-observed event is
preserved); once settled, settled legs/cash are never rewritten and only
a positive unresolved delta is booked as a fresh receivable.

Rounding policy: no rounding exists in this module. Entitlement cents
and successor quantities must divide exactly; anything else fails closed
(a versioned rounding policy with a residual account is a later task,
and inventing one here would silently create money).
"""

from __future__ import annotations

from enum import StrEnum
from math import gcd
from typing import Annotated

from pydantic import Field, model_validator

from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    PositionState,
    RationalQuantity,
    UtcInstant,
)
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr


PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveCents = Annotated[int, Field(gt=0)]


class SourceAuthorityTier(StrEnum):
    """The provenance tier of one corporate action fact.

    ``AS_OBSERVED`` facts come from vendor/announcement feeds;
    ``CONFIRMED`` facts are broker/legal confirmations. Authority is
    monotonic: a confirmed fact is never downgraded by a later
    as-observed one.
    """

    AS_OBSERVED = "AS_OBSERVED"
    CONFIRMED = "CONFIRMED"


SOURCE_AUTHORITY_RANK = {
    SourceAuthorityTier.AS_OBSERVED: 0,
    SourceAuthorityTier.CONFIRMED: 1,
}


class CorporateActionKind(StrEnum):
    CASH_DIVIDEND = "CASH_DIVIDEND"
    SHARE_ENTITLEMENT = "SHARE_ENTITLEMENT"
    SPLIT = "SPLIT"
    MERGE = "MERGE"
    SECURITY_CONVERSION = "SECURITY_CONVERSION"
    CASH_SETTLEMENT = "CASH_SETTLEMENT"
    LEGAL_WRITE_OFF = "LEGAL_WRITE_OFF"


ENTITLEMENT_KINDS = frozenset(
    {CorporateActionKind.CASH_DIVIDEND, CorporateActionKind.SHARE_ENTITLEMENT}
)


class CorporateActionState(StrEnum):
    """Lifecycle of one corporate action fact (projection state)."""

    PENDING = "PENDING"
    CASH_SETTLED = "CASH_SETTLED"
    SHARES_TRADABLE = "SHARES_TRADABLE"
    APPLIED = "APPLIED"
    CONVERTED = "CONVERTED"
    TERMINAL_SETTLED = "TERMINAL_SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ConversionDestination(StrEnum):
    """How successor shares are received in a SECURITY_CONVERSION.

    ``TRADABLE`` credits settled tradable shares; ``RESTRICTED`` credits
    a successor share receivable that must pass its own tradable date
    before it can be sold.
    """

    TRADABLE = "TRADABLE"
    RESTRICTED = "RESTRICTED"


def split_entitlement(
    quantity: int, numerator: int, denominator: int
) -> tuple[int, int, int]:
    """Exact ``quantity * numerator / denominator`` as whole + remainder.

    Returns ``(whole_units, remainder_numerator, remainder_denominator)``
    with the remainder in lowest terms (``0/1`` when the entitlement
    divides exactly). Pure integer arithmetic: no float ever touches the
    path.
    """

    if quantity <= 0:
        raise ValueError("entitlement quantity must be positive")
    if numerator <= 0:
        raise ValueError("entitlement numerator must be positive")
    if denominator <= 0:
        raise ValueError("entitlement denominator must be positive")
    total = quantity * numerator
    whole, remainder = divmod(total, denominator)
    if remainder == 0:
        return whole, 0, 1
    divisor = gcd(remainder, denominator)
    return whole, remainder // divisor, denominator // divisor


def exact_entitlement_cents(
    quantity: int, numerator: int, denominator: int
) -> int:
    """Exact integer cents of ``quantity * numerator / denominator``.

    Fails closed when the entitlement does not divide to whole cents:
    the kernel has no frozen rounding policy (direction + residual
    account) for sub-cent entitlements yet, so approximating one would
    silently create or destroy money.
    """

    if quantity <= 0:
        raise ValueError("entitlement quantity must be positive")
    if numerator <= 0:
        raise ValueError("entitlement numerator must be positive")
    if denominator <= 0:
        raise ValueError("entitlement denominator must be positive")
    total = quantity * numerator
    if total % denominator != 0:
        raise ValueError("entitlement does not divide to exact cents")
    return total // denominator


def exact_quantity(
    quantity: int, numerator: int, denominator: int
) -> int:
    """Exact integer share count for split/merge/conversion ratios."""

    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if numerator <= 0:
        raise ValueError("ratio numerator must be positive")
    if denominator <= 0:
        raise ValueError("ratio denominator must be positive")
    total = quantity * numerator
    if total % denominator != 0:
        raise ValueError("ratio does not divide to exact share units")
    return total // denominator


def lowest_terms(numerator: int, denominator: int) -> tuple[int, int]:
    """Exact rational in lowest terms with a positive denominator."""

    if denominator == 0:
        raise ValueError("denominator must be nonzero")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    divisor = gcd(abs(numerator), denominator) or 1
    return numerator // divisor, denominator // divisor


# ---------------------------------------------------------------------------
# Canonical identities
# ---------------------------------------------------------------------------


def entitlement_idempotency_key(
    action_id: str, position_lineage_id: str, economic_lot_id: str, *, revision: int
) -> str:
    """Stable identity of one entitlement fact revision.

    Re-recording the same action/revision converges on one canonical
    event; distinct actions or revisions never collide.
    """

    return (
        f"ca:entitle:{action_id}:{position_lineage_id}:{economic_lot_id}"
        f":rev{revision}"
    )


def cash_receivable_id(
    action_id: str, position_lineage_id: str, economic_lot_id: str, *, revision: int
) -> str:
    return (
        f"rcv:ca:{action_id}:{position_lineage_id}:{economic_lot_id}:rev{revision}"
    )


def cash_in_lieu_receivable_id(
    action_id: str, position_lineage_id: str, economic_lot_id: str, *, revision: int
) -> str:
    return (
        f"rcv-cil:ca:{action_id}:{position_lineage_id}:{economic_lot_id}"
        f":rev{revision}"
    )


def share_receivable_id(
    action_id: str, position_lineage_id: str, economic_lot_id: str, *, revision: int
) -> str:
    return (
        f"rcv-share:ca:{action_id}:{position_lineage_id}:{economic_lot_id}"
        f":rev{revision}"
    )


def successor_share_receivable_id(
    action_id: str, position_lineage_id: str, economic_lot_id: str
) -> str:
    return f"rcv-share:ca:{action_id}:{position_lineage_id}:{economic_lot_id}:succ"


def settlement_idempotency_key(receivable_id: str) -> str:
    """One settlement fact per receivable (pay date / cash-in-lieu)."""

    return f"ca:settle:{receivable_id}"


def tradable_idempotency_key(receivable_id: str) -> str:
    """One tradable-date fact per share receivable."""

    return f"ca:tradable:{receivable_id}"


def split_merge_idempotency_key(
    action_id: str, position_lineage_id: str, economic_lot_id: str
) -> str:
    return f"ca:splitmerge:{action_id}:{position_lineage_id}:{economic_lot_id}"


def conversion_idempotency_key(
    action_id: str, position_lineage_id: str, economic_lot_id: str
) -> str:
    return f"ca:convert:{action_id}:{position_lineage_id}:{economic_lot_id}"


def terminal_cash_idempotency_key(
    action_id: str, position_lineage_id: str, economic_lot_id: str
) -> str:
    return f"ca:terminal:{action_id}:{position_lineage_id}:{economic_lot_id}"


def write_off_idempotency_key(
    action_id: str, position_lineage_id: str, economic_lot_id: str
) -> str:
    return f"ca:writeoff:{action_id}:{position_lineage_id}:{economic_lot_id}"


# ---------------------------------------------------------------------------
# Canonical payload fact (persisted on the economic event)
# ---------------------------------------------------------------------------


class CorporateActionFact(CanonicalModel):
    """The action-level context persisted with every corporate action event.

    The ``recorded_*`` and ``superseded_*`` fields freeze the inputs the
    projection consumed, so an idempotent retry can recompute the exact
    committed payload even after the position or receivable state moved
    on (a later split, settlement, etc.).
    """

    action_id: NonEmptyStr
    action_kind: CorporateActionKind
    revision: PositiveInt
    tier: SourceAuthorityTier
    entitlement: RationalQuantity | None = None
    fractional_remainder: RationalQuantity | None = None
    cash_in_lieu_cents: NonNegativeInt | None = None
    recorded_quantity_units: NonNegativeInt | None = None
    superseded_receivable_id: NonEmptyStr | None = None
    superseded_amount_cents: NonNegativeInt | None = None
    superseded_quantity_units: NonNegativeInt | None = None
    superseded_cash_in_lieu_cents: NonNegativeInt | None = None
    delta_amount_cents: NonNegativeInt | None = None
    proceeds_cents: NonNegativeInt | None = None
    successor_security_id: NonEmptyStr | None = None
    destination: ConversionDestination | None = None
    legal_evidence_reference: NonEmptyStr | None = None


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class _CorporateActionRequest(CanonicalModel):
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    tier: SourceAuthorityTier
    source_authority: NonEmptyStr
    effective_at: UtcInstant
    as_of: UtcInstant
    expected_stream_version: NonNegativeInt

    @model_validator(mode="after")
    def validate_times(self) -> "_CorporateActionRequest":
        if self.as_of < self.effective_at:
            raise ValueError("as_of cannot precede effective_at")
        return self


class EntitlementRequest(_CorporateActionRequest):
    """One ex-date entitlement fact (or one correction revision of it).

    ``revision=1`` records the as-observed/confirmed entitlement;
    ``revision=n+1`` supersedes revision ``n`` while the receivable is
    unsettled, or books only the positive unresolved delta after
    settlement. The entitlement is an exact rational per share: cents
    per share for cash dividends, new shares per held share for share
    entitlements.
    """

    action_id: NonEmptyStr
    revision: PositiveInt = 1
    security_id: NonEmptyStr
    action_kind: CorporateActionKind
    entitlement: RationalQuantity
    cash_in_lieu_cents: PositiveCents | None = None

    @model_validator(mode="after")
    def validate_kind(self) -> "EntitlementRequest":
        if self.action_kind not in ENTITLEMENT_KINDS:
            raise ValueError(
                "entitlement requests support cash dividends and share"
                " entitlements only"
            )
        if (
            self.cash_in_lieu_cents is not None
            and self.action_kind is not CorporateActionKind.SHARE_ENTITLEMENT
        ):
            raise ValueError(
                "cash-in-lieu applies to fractional share entitlements only"
            )
        return self


class CashInLieuRequest(_CorporateActionRequest):
    """Settle the action's outstanding cash entitlement receivable.

    Used for dividend payments on the pay date and for cash-in-lieu
    receipts; the settled amount always equals the outstanding
    receivable exactly.
    """

    action_id: NonEmptyStr


class SharesTradableRequest(_CorporateActionRequest):
    """Move the action's vested share receivable into settled tradable
    shares on the tradable date."""

    action_id: NonEmptyStr


class SplitMergeRequest(_CorporateActionRequest):
    """Apply a split (ratio > 1) or merge (ratio < 1) to a whole lot.

    The aggregate cost basis is preserved exactly; the per-share basis
    becomes the rational ``basis / new_quantity``.
    """

    action_id: NonEmptyStr
    security_id: NonEmptyStr
    action_kind: CorporateActionKind
    ratio: RationalQuantity

    @model_validator(mode="after")
    def validate_kind(self) -> "SplitMergeRequest":
        if self.action_kind not in (
            CorporateActionKind.SPLIT,
            CorporateActionKind.MERGE,
        ):
            raise ValueError("split/merge requests require a SPLIT or MERGE kind")
        return self


class ConversionRequest(_CorporateActionRequest):
    """Convert a whole economic lot into a successor security.

    The successor inherits the lot identity, provenance, attribution,
    cost basis, and the due exit obligation (position state).
    """

    action_id: NonEmptyStr
    source_security_id: NonEmptyStr
    successor_security_id: NonEmptyStr
    ratio: RationalQuantity
    destination: ConversionDestination


class TerminalCashRequest(_CorporateActionRequest):
    """Legal terminal cash settlement of one lot (cash buyout, delisting
    settlement). Requires CONFIRMED authority; sweeps every remaining
    share and share receivable of the lot."""

    action_id: NonEmptyStr
    security_id: NonEmptyStr
    proceeds_cents: PositiveCents
    sweep_receivable_ids: tuple[NonEmptyStr, ...] = ()
    legal_evidence_reference: NonEmptyStr | None = None


class WriteOffRequest(_CorporateActionRequest):
    """Legal derecognition of a worthless lot. Requires CONFIRMED
    authority and an explicit legal evidence reference; the remaining
    basis leaves as a realized loss and swept entitlement receivables
    reverse their income."""

    action_id: NonEmptyStr
    security_id: NonEmptyStr
    sweep_receivable_ids: tuple[NonEmptyStr, ...] = ()
    legal_evidence_reference: NonEmptyStr


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


class EntitlementReceipt(CanonicalModel):
    action_id: NonEmptyStr
    revision: PositiveInt
    event_id: NonEmptyStr
    receivable_id: NonEmptyStr | None
    cash_amount_cents: NonNegativeInt | None
    share_quantity: NonNegativeInt | None
    fractional_remainder_numerator: NonNegativeInt
    fractional_remainder_denominator: PositiveInt
    cash_in_lieu_cents: NonNegativeInt | None
    cash_in_lieu_receivable_id: NonEmptyStr | None
    source_authority_tier: SourceAuthorityTier
    correction: bool
    supersedes_event_id: NonEmptyStr | None
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


class CashInLieuReceipt(CanonicalModel):
    action_id: NonEmptyStr
    receivable_id: NonEmptyStr
    event_id: NonEmptyStr
    amount_cents: PositiveCents
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


class SharesTradableReceipt(CanonicalModel):
    action_id: NonEmptyStr
    receivable_id: NonEmptyStr
    event_id: NonEmptyStr
    quantity: PositiveInt
    shares_became_tradable_at: UtcInstant
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


class SplitMergeReceipt(CanonicalModel):
    action_id: NonEmptyStr
    event_id: NonEmptyStr
    prior_quantity: PositiveInt
    new_quantity: PositiveInt
    cost_basis_cents: NonNegativeInt
    per_share_basis_numerator: NonNegativeInt
    per_share_basis_denominator: PositiveInt
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


class ConversionReceipt(CanonicalModel):
    action_id: NonEmptyStr
    event_id: NonEmptyStr
    source_security_id: NonEmptyStr
    successor_security_id: NonEmptyStr
    prior_settled_quantity: NonNegativeInt
    prior_share_receivable_quantity: NonNegativeInt
    successor_quantity: PositiveInt
    destination: ConversionDestination
    successor_receivable_id: NonEmptyStr | None
    # Typed as the contract enum so callers can rely on member identity:
    # the successor inherits the due exit obligation, and the receipt must
    # expose it as such (a raw string would silently lose the type).
    inherited_position_state: PositionState
    cost_basis_cents: NonNegativeInt
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


class TerminalCashReceipt(CanonicalModel):
    action_id: NonEmptyStr
    event_id: NonEmptyStr
    proceeds_cents: PositiveCents
    swept_quantity: NonNegativeInt
    consumed_basis_cents: NonNegativeInt
    realized_pnl_cents: int
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


class WriteOffReceipt(CanonicalModel):
    action_id: NonEmptyStr
    event_id: NonEmptyStr
    written_off_quantity: NonNegativeInt
    share_receivable_written_off: NonNegativeInt
    written_off_basis_cents: NonNegativeInt
    receivables_written_off: tuple[NonEmptyStr, ...]
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


# ---------------------------------------------------------------------------
# Projection read model
# ---------------------------------------------------------------------------


class CorporateActionRecord(CanonicalModel):
    """One ``corporate_actions`` projection row (typed read model).

    Plan 04 ExitMandate projection and Plan 02 Task 6 consume the
    successor mapping and ``inherited_position_state`` to keep due exit
    obligations alive across conversions.
    """

    action_id: NonEmptyStr
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    action_kind: CorporateActionKind
    state: CorporateActionState
    source_authority_tier: SourceAuthorityTier
    source_authority: NonEmptyStr
    security_id: NonEmptyStr
    revision: PositiveInt
    entitlement: tuple[int, int] | None
    fractional_remainder: tuple[int, int] | None
    cash_in_lieu_cents: NonNegativeInt | None
    receivable_id: NonEmptyStr | None
    cash_in_lieu_receivable_id: NonEmptyStr | None
    ex_effective_at: UtcInstant
    pay_effective_at: UtcInstant | None
    tradable_effective_at: UtcInstant | None
    successor_security_id: NonEmptyStr | None
    successor_quantity_units: NonNegativeInt | None
    successor_receivable_id: NonEmptyStr | None
    inherited_position_state: NonEmptyStr | None
    opened_by_event_id: NonEmptyStr
    updated_by_event_id: NonEmptyStr
    updated_at: UtcInstant


__all__ = [
    "ENTITLEMENT_KINDS",
    "SOURCE_AUTHORITY_RANK",
    "CashInLieuReceipt",
    "CashInLieuRequest",
    "ConversionDestination",
    "ConversionReceipt",
    "ConversionRequest",
    "CorporateActionFact",
    "CorporateActionKind",
    "CorporateActionRecord",
    "CorporateActionState",
    "EntitlementReceipt",
    "EntitlementRequest",
    "SharesTradableReceipt",
    "SharesTradableRequest",
    "SourceAuthorityTier",
    "SplitMergeReceipt",
    "SplitMergeRequest",
    "TerminalCashReceipt",
    "TerminalCashRequest",
    "WriteOffReceipt",
    "WriteOffRequest",
    "cash_in_lieu_receivable_id",
    "cash_receivable_id",
    "conversion_idempotency_key",
    "entitlement_idempotency_key",
    "exact_entitlement_cents",
    "exact_quantity",
    "lowest_terms",
    "settlement_idempotency_key",
    "share_receivable_id",
    "split_entitlement",
    "split_merge_idempotency_key",
    "successor_share_receivable_id",
    "terminal_cash_idempotency_key",
    "tradable_idempotency_key",
    "write_off_idempotency_key",
]
