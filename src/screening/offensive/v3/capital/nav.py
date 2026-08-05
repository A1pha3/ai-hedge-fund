"""Unit NAV observations, valuation requests, and log-growth semantics.

Plan 02 Task 3. The ledger persists one ``VALUATION`` economic event per
close valuation (mark-only: it never changes cash, shares, or position
state) and one append-only ``nav_observations`` row per confirmed NAV. Two
series are preserved side by side and must never be cherry-picked:

- ``AS_OBSERVED`` — the NAV visible to authoritative risk at decision time;
- ``RESTATED_FINAL`` — corrections linked to the observation they supersede
  (append-only; the as-observed row is never rewritten).

Unit prices are exact rationals (numerator/denominator integer cents per
unit quanta); there is no float in the path. When a confirmed NAV falls to
zero or below, official lifetime log growth is ``-inf``: the ledger records
that with the typed :attr:`LogGrowthKind.NEGATIVE_INFINITY` marker plus
integer NAV fields — never a persisted float ``-inf``.
"""

from __future__ import annotations

from enum import StrEnum
from math import gcd
from typing import Annotated

from pydantic import Field, model_validator

from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    UtcInstant,
)
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr


PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class ObservationKind(StrEnum):
    AS_OBSERVED = "AS_OBSERVED"
    RESTATED_FINAL = "RESTATED_FINAL"


class LogGrowthKind(StrEnum):
    """Typed log-growth sentinel for the official lifecycle NAV path.

    ``NEGATIVE_INFINITY`` is the only representation of ``-inf``: a typed
    marker paired with integer NAV fields. No float is ever persisted.
    """

    NO_PRIOR_OBSERVATION = "NO_PRIOR_OBSERVATION"
    FINITE = "FINITE"
    NEGATIVE_INFINITY = "NEGATIVE_INFINITY"


class ValuationMarkInput(CanonicalModel):
    """One close-valuation mark: versioned integer price micros per share."""

    security_id: NonEmptyStr
    price_micros: PositiveInt


class ValuationRequest(CanonicalModel):
    """One close valuation confirming marks, NAV, water marks, and lifecycle."""

    idempotency_key: NonEmptyStr
    source_authority: NonEmptyStr
    effective_at: UtcInstant
    as_of: UtcInstant
    expected_stream_version: NonNegativeInt
    marks: tuple[ValuationMarkInput, ...]

    @model_validator(mode="after")
    def validate_times(self) -> "ValuationRequest":
        if self.as_of < self.effective_at:
            raise ValueError("as_of cannot precede effective_at")
        security_ids = [mark.security_id for mark in self.marks]
        if len(security_ids) != len(set(security_ids)):
            raise ValueError("duplicate valuation mark security identity")
        return self


class ValuationReceipt(CanonicalModel):
    """The durable outcome of one close valuation."""

    event_id: NonEmptyStr
    observation_id: NonEmptyStr
    nav_cents: NonNegativeInt
    lifetime_high_water_mark_cents: NonNegativeInt
    active_epoch_high_water_mark_cents: NonNegativeInt
    log_growth_kind: LogGrowthKind
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


class RestatementRequest(CanonicalModel):
    """Restate one valuation with corrected marks (append-only link).

    The restated observation supersedes the as-observed observation of the
    restated valuation for the official ``restated_final`` path; the
    as-observed series, decision-time NAV, and water marks are preserved.
    """

    idempotency_key: NonEmptyStr
    restates_event_id: NonEmptyStr
    source_authority: NonEmptyStr
    effective_at: UtcInstant
    as_of: UtcInstant
    expected_stream_version: NonNegativeInt
    marks: Annotated[tuple[ValuationMarkInput, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_times(self) -> "RestatementRequest":
        if self.as_of < self.effective_at:
            raise ValueError("as_of cannot precede effective_at")
        security_ids = [mark.security_id for mark in self.marks]
        if len(security_ids) != len(set(security_ids)):
            raise ValueError("duplicate restatement mark security identity")
        return self


class RestatementReceipt(CanonicalModel):
    """The durable outcome of one restated valuation."""

    event_id: NonEmptyStr
    restates_event_id: NonEmptyStr
    observation_id: NonEmptyStr
    nav_cents: NonNegativeInt
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


class NavObservation(CanonicalModel):
    """One typed row of the unit NAV path (read model)."""

    nav_observation_id: NonEmptyStr
    observation_kind: ObservationKind
    supersedes_observation_id: NonEmptyStr | None
    as_of: UtcInstant
    capital_version: NonNegativeInt
    created_by_event_id: NonEmptyStr
    nav_cents: int
    issued_unit_quanta: NonNegativeInt
    live_unit_quanta: NonNegativeInt
    unit_price_numerator: NonNegativeInt | None
    unit_price_denominator: PositiveInt | None
    log_growth_kind: LogGrowthKind
    log_growth_nav_numerator: int | None
    log_growth_nav_denominator: int | None

    @model_validator(mode="after")
    def validate_representation(self) -> "NavObservation":
        if (self.unit_price_numerator is None) != (
            self.unit_price_denominator is None
        ):
            raise ValueError("unit price rational is incomplete")
        if self.log_growth_kind is LogGrowthKind.NO_PRIOR_OBSERVATION:
            if (
                self.log_growth_nav_numerator is not None
                or self.log_growth_nav_denominator is not None
            ):
                raise ValueError(
                    "first observation has no prior NAV to compare"
                )
        else:
            if (
                self.log_growth_nav_numerator is None
                or self.log_growth_nav_denominator is None
            ):
                raise ValueError("log growth requires integer NAV ratio fields")
            if self.log_growth_nav_denominator <= 0:
                raise ValueError("log growth denominator must be positive")
        return self


class NavProjectionPath(CanonicalModel):
    """Both preserved NAV series: as-observed and restated-final."""

    as_observed: tuple[NavObservation, ...]
    restated_final: tuple[NavObservation, ...]


def unit_price_lowest_terms(
    nav_cents: int, live_unit_quanta: int
) -> tuple[int, int] | None:
    """Exact rational unit price in lowest terms; ``None`` on an empty
    live denominator (the empty denominator is never reused for NAV or new
    risk while units are pending redemption)."""

    if live_unit_quanta <= 0:
        return None
    if nav_cents == 0:
        return (0, 1)
    divisor = gcd(abs(nav_cents), live_unit_quanta)
    return (nav_cents // divisor, live_unit_quanta // divisor)


def nav_ratio_lowest_terms(
    nav_cents: int, prior_nav_cents: int
) -> tuple[int, int]:
    """Exact ``nav / prior_nav`` rational in lowest terms.

    Callers must guarantee ``prior_nav_cents > 0``; a nonpositive prior NAV
    means log growth was already ``-inf`` and no finite ratio exists.
    """

    if prior_nav_cents <= 0:
        raise ValueError("prior NAV must be positive for a finite ratio")
    if nav_cents <= 0:
        return (0, 1)
    divisor = gcd(abs(nav_cents), prior_nav_cents)
    return (nav_cents // divisor, prior_nav_cents // divisor)


def log_growth_kind_for(nav_cents: int, prior_nav_cents: int | None) -> LogGrowthKind:
    """The typed log-growth sentinel for one confirmed NAV step.

    Once the confirmed NAV has touched zero (or below), the lifetime log
    growth stays ``NEGATIVE_INFINITY``: the path cannot be restarted or
    deleted to hide the failure.
    """

    if prior_nav_cents is None:
        return LogGrowthKind.NO_PRIOR_OBSERVATION
    if nav_cents <= 0 or prior_nav_cents <= 0:
        return LogGrowthKind.NEGATIVE_INFINITY
    return LogGrowthKind.FINITE


__all__ = [
    "LogGrowthKind",
    "NavObservation",
    "NavProjectionPath",
    "ObservationKind",
    "RestatementReceipt",
    "RestatementRequest",
    "ValuationMarkInput",
    "ValuationReceipt",
    "ValuationRequest",
    "log_growth_kind_for",
    "nav_ratio_lowest_terms",
    "unit_price_lowest_terms",
]
