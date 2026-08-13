"""Canonical economic configuration consumed by the pure kernel."""

from __future__ import annotations

from pydantic import Field
from typing import Annotated

from src.screening.offensive.v3.contracts.base import CanonicalModel


NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]


class SizingConfig(CanonicalModel):
    """Complete integer sizing configuration for one decision.

    Shadow inputs embed this object so changing process construction state
    cannot change the output of the same canonical input.
    """

    per_ticker_gross_cap_cents: NonNegativeInt
    per_industry_gross_cap_cents: NonNegativeInt
    per_day_gross_cap_cents: NonNegativeInt
    portfolio_gross_cap_cents: NonNegativeInt
    worst_case_fee_ppm: NonNegativeInt
    min_lot_units: PositiveInt = 100


__all__ = ["SizingConfig"]
