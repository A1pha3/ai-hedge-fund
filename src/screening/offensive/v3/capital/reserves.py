"""Entry reserve lifecycle DTOs for the capital kernel.

Plan 02 Task 2: ``reserve_entry`` creates a LIVE reservation that consumes
available cash; ``release_reserve`` walks it through cancel-pending to
released. Reserves are risk state, not economic events: they move cash
between the available and restricted projections and bump the capital
version without touching the economic event stream.

State machine::

    entry ----> LIVE --CANCEL_REQUESTED--> CANCEL_PENDING
                 |  \\----CANCEL_CONFIRMED/      |
                 |       ORDER_REJECTED/         | CANCEL_CONFIRMED/
                 |       ORDER_EXPIRED           | ORDER_REJECTED/
                 v                               | ORDER_EXPIRED
              RELEASED <-------------------------+
    LIVE/CANCEL_PENDING --fill consumes--> CONSUMED

``SUBMISSION_AMBIGUOUS`` never releases: the worst-case reserve stays live
until a broker-confirmed fill or a confirmed terminal order state resolves
the ambiguity.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from src.screening.offensive.v3.capital.provenance import CapitalSourceBinding
from src.screening.offensive.v3.contracts import CanonicalModel, UtcInstant
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr


PositiveCents = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class CapitalReserveState(StrEnum):
    LIVE = "LIVE"
    CANCEL_PENDING = "CANCEL_PENDING"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class ReserveReleaseReason(StrEnum):
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCEL_CONFIRMED = "CANCEL_CONFIRMED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    SUBMISSION_AMBIGUOUS = "SUBMISSION_AMBIGUOUS"


CONFIRMED_RELEASE_REASONS = frozenset(
    {
        ReserveReleaseReason.CANCEL_CONFIRMED,
        ReserveReleaseReason.ORDER_REJECTED,
        ReserveReleaseReason.ORDER_EXPIRED,
    }
)


class ReserveEntryRequest(CanonicalModel):
    """Create one LIVE entry reserve consuming available capital."""

    source_id: NonEmptyStr
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    reserved_entry_gross_cents: PositiveCents
    expected_stream_version: NonNegativeInt
    as_of: UtcInstant
    # Plan 08 Task 7: optional causal binding; the official shadow adapter
    # requires it on every decision-derived reserve.
    source_binding: CapitalSourceBinding | None = None


class ReserveReleaseRequest(CanonicalModel):
    """Walk one reserve through the cancel/release state machine."""

    source_id: NonEmptyStr
    reason: ReserveReleaseReason
    expected_stream_version: NonNegativeInt
    as_of: UtcInstant

    @model_validator(mode="after")
    def validate_reason(self) -> "ReserveReleaseRequest":
        # The type system carries every reason; future task-specific reasons
        # must extend the enum, not overload an existing one.
        return self


__all__ = [
    "CONFIRMED_RELEASE_REASONS",
    "CapitalReserveState",
    "ReserveEntryRequest",
    "ReserveReleaseReason",
    "ReserveReleaseRequest",
]
