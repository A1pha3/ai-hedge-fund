"""Exact integer rounding policy for the capital kernel.

Plan 02 Task 2: every rounding decision in the fills/fees/reserves path
uses banker's rounding (round-half-even) on exact integer ratios. Money is
persisted in integer cents, prices in integer micros (1e-6 of the currency
unit), quantities in integer units; ``Decimal`` only appears at boundary
conversion and never as persisted truth.

Rounding is applied exactly at these points and nowhere else:

1. ``fill_gross_cents`` — a fill's ``price_micros * quantity`` notional in
   micros becomes integer cents (divide by 10_000, round-half-even).
2. Fee components — each of commission base, stamp tax, and transfer fee is
   rounded half-even independently from ``notional_cents * rate_ppm / 1e6``,
   then summed; the per-order minimum commission applies to exact integers
   and adds no rounding.
3. Exit cost-basis consumption — ``basis * qty_exit / qty_before`` is
   rounded half-even; a fill exhausting the lot consumes the exact
   remaining basis so closed lots never carry a rounding residue.
"""

from __future__ import annotations

MICROS_PER_CENT: int = 10_000
PPM_SCALE: int = 1_000_000


def round_half_even_div(numerator: int, denominator: int) -> int:
    """Return ``numerator / denominator`` rounded half-even, exact integers.

    This is the single rounding primitive every Task 2 computation uses;
    there is no float anywhere in the path.
    """

    if denominator == 0:
        raise ValueError("division by zero has no rounding policy")
    quotient, remainder = divmod(numerator, denominator)
    doubled = abs(2 * remainder)
    if doubled > abs(denominator):
        step = 1 if denominator > 0 else -1
        quotient += step
    elif doubled == abs(denominator):
        # Exact tie: round toward the even quotient.
        if quotient % 2 != 0:
            step = 1 if denominator > 0 else -1
            quotient += step
    return quotient


def fill_gross_cents(price_micros: int, quantity: int) -> int:
    """Convert a fill's integer price micros and quantity into gross cents.

    ``price_micros * quantity`` is the exact notional in micros; dividing by
    10_000 converts micros to cents (1e6 / 1e2) with round-half-even.
    """

    if price_micros <= 0:
        raise ValueError("price micros must be positive")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    return round_half_even_div(price_micros * quantity, MICROS_PER_CENT)
