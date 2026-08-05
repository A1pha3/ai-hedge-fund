"""Versioned fee policy and exact fee computation for fills.

Plan 02 Task 2 scope: per-fill commission base, per-order minimum
commission, sell-side stamp tax, both-side transfer fee. Plan 01 contracts
deliberately do not freeze a fee schedule DTO, so the kernel carries this
minimal versioned policy; every amount is integer cents and every rounding
decision is round-half-even via :mod:`capital.rounding`.

Fee revision semantics:

- A fill revision records only the gross cash/security fact. Its fee is a
  DISTINCT ``FEE_CHARGED`` event recorded through ``record_fee_revision``,
  linked to the fill by the execution-revision registry.
- Commission base, stamp tax, and transfer fee are each rounded half-even
  independently from the fill notional, then summed.
- The minimum commission is a per-ORDER rule: the cumulative commission
  owed after each fill is ``max(min_commission, cumulative_base)`` and each
  fee revision charges the non-negative delta against the cumulative amount
  already charged for the order. The minimum is therefore charged exactly
  once per order, regardless of how many partial fills it took.
- Stamp tax applies to EXIT (sell) fills only; the transfer fee applies to
  both sides. Different ``fee_policy_version`` schedules change the charged
  amounts; the version is part of the fee receipt provenance.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from src.screening.offensive.v3.capital.rounding import (
    PPM_SCALE,
    round_half_even_div,
)
from src.screening.offensive.v3.contracts import CanonicalModel, ExecutionSide
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr


NonNegativeInt = Annotated[int, Field(ge=0)]


class FeeRevisionKind(StrEnum):
    """The lifecycle kind of one fee revision of a fill execution.

    ``INITIAL`` is revision 1, the first charge of the fill's fee stream.
    ``BUSTED``/``CORRECTED`` (Plan 02 Task 6) follow a busted/corrected
    fill and recompute the order's fee target from the active fill facts;
    they book the signed delta against what the order's fee streams have
    actually charged (a refund when the delta is negative).
    """

    INITIAL = "INITIAL"
    BUSTED = "BUSTED"
    CORRECTED = "CORRECTED"


class FeePolicy(CanonicalModel):
    """One frozen, versioned schedule of execution costs.

    Rates are integer parts-per-million of the fill notional. The minimum
    commission applies once per order (across partial fills), to the
    commission component only; stamp tax applies to exit (sell) fills only;
    the transfer fee applies to both sides.
    """

    fee_policy_version: NonEmptyStr
    commission_rate_ppm: NonNegativeInt
    min_commission_cents: NonNegativeInt
    stamp_tax_rate_ppm: NonNegativeInt
    transfer_fee_rate_ppm: NonNegativeInt


class FeeComponents(CanonicalModel):
    """Per-fill fee amounts before the per-order minimum commission."""

    commission_base_cents: NonNegativeInt
    stamp_tax_cents: NonNegativeInt
    transfer_fee_cents: NonNegativeInt

    @property
    def total_cents(self) -> int:
        return (
            self.commission_base_cents
            + self.stamp_tax_cents
            + self.transfer_fee_cents
        )


def fee_execution_id(fill_execution_id: str) -> str:
    """Namespace the fee revision stream of one fill execution.

    Fee revisions live in ``execution_revisions`` under their own identity
    so the UNIQUE(execution_id, revision) constraint gives each fill a
    monotonic fee stream without colliding with the fill's own revisions.
    """

    return f"fee:{fill_execution_id}"


def compute_fee_components(
    notional_cents: int, side: ExecutionSide, policy: FeePolicy
) -> FeeComponents:
    """Per-fill commission base / stamp tax / transfer fee (no minimum).

    Each component is independently rounded half-even from the exact ratio
    ``notional_cents * rate_ppm / 1_000_000``, then the components are
    summed; there is no cross-component rounding.
    """

    if notional_cents < 0:
        raise ValueError("notional cents cannot be negative")
    commission_base = round_half_even_div(
        notional_cents * policy.commission_rate_ppm, PPM_SCALE
    )
    stamp_tax = (
        round_half_even_div(notional_cents * policy.stamp_tax_rate_ppm, PPM_SCALE)
        if side is ExecutionSide.EXIT
        else 0
    )
    transfer_fee = round_half_even_div(
        notional_cents * policy.transfer_fee_rate_ppm, PPM_SCALE
    )
    return FeeComponents(
        commission_base_cents=commission_base,
        stamp_tax_cents=stamp_tax,
        transfer_fee_cents=transfer_fee,
    )


def commission_charge_cents(
    cumulative_base_now_cents: int,
    cumulative_base_before_cents: int,
    min_commission_cents: int,
) -> int:
    """Incremental per-order minimum-commission charge for one fill.

    The cumulative commission owed after N fills is
    ``max(min_commission, cumulative_base_N)``; each fill charges the delta
    against the previously owed cumulative, which is always non-negative
    because the cumulative base only grows within an order. A zero
    ``cumulative_base_before`` denotes the order's first fill (nothing
    charged yet), so the minimum is charged in full there. The kernel's fee
    engine applies the same rule against the actually charged history, which
    additionally stays exact when fee-policy versions change mid-order.
    """

    if cumulative_base_now_cents < cumulative_base_before_cents:
        raise ValueError("cumulative commission base must be monotonic")
    owed_now = max(min_commission_cents, cumulative_base_now_cents)
    owed_before = (
        0
        if cumulative_base_before_cents == 0
        else max(min_commission_cents, cumulative_base_before_cents)
    )
    return owed_now - owed_before


__all__ = [
    "FeeComponents",
    "FeePolicy",
    "FeeRevisionKind",
    "commission_charge_cents",
    "compute_fee_components",
    "fee_execution_id",
]
