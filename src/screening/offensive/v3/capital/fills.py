"""Fill and fee revision commands for the capital kernel.

Plan 02 Task 2: one fact / one event. A fill revision records one broker
execution report (integer price micros and integer quantity) as a canonical
TRADE_EXECUTED event whose cash and security legs land atomically in one
capital transaction. A fee revision is linked to its fill but is a DISTINCT
FEE_CHARGED event. Unattributed or plan-violating fills are preserved under
sentinel attribution and flagged, never dropped.

Revision semantics: each broker execution report owns its own
``execution_id`` and starts at ``revision=1`` (the RECORDED fact); partial
fills of one order are distinct execution reports. Higher revisions
(BUSTED/CORRECTED supersessions) land through Plan 02 Task 6
(:mod:`capital.execution_revisions`); ``record_fill_revision`` dispatches
``revision > 1`` requests to that machinery.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from src.screening.offensive.v3.capital.fees import FeePolicy, FeeRevisionKind
from src.screening.offensive.v3.capital.provenance import CapitalSourceBinding
from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    ExecutionRevisionKind,
    ExecutionSide,
    UtcInstant,
)
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr


PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeCents = Annotated[int, Field(ge=0)]

UNATTRIBUTED_PRODUCER = "UNATTRIBUTED"
UNATTRIBUTED_PROGRAM = "UNATTRIBUTED"
UNATTRIBUTED_LINEAGE = "UNATTRIBUTED"
UNATTRIBUTED_STAGE = "UNATTRIBUTED"
UNATTRIBUTED_LOT_PREFIX = "unattributed:"


class FillAttribution(CanonicalModel):
    """Complete risk attribution for an attributed fill."""

    producer_namespace: NonEmptyStr
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr


class FillRevisionRequest(CanonicalModel):
    """One broker execution report for an order.

    The fill carries integer price micros and integer quantity; the gross
    cash leg is derived with the frozen round-half-even policy and lands
    atomically with the security leg in one capital transaction.
    """

    execution_id: NonEmptyStr
    revision: PositiveInt
    # Plan 02 Task 6: revision 1 is the RECORDED fill fact and carries no
    # revision kind; higher revisions are BUSTED/CORRECTED supersessions
    # dispatched to the execution-revision machinery.
    revision_kind: ExecutionRevisionKind | None = None
    order_id: NonEmptyStr
    side: ExecutionSide
    security_id: NonEmptyStr
    price_micros: PositiveInt
    quantity: PositiveInt
    position_lineage_id: NonEmptyStr | None = None
    economic_lot_id: NonEmptyStr | None = None
    attribution: FillAttribution | None = None
    reserve_source_id: NonEmptyStr | None = None
    source_authority: NonEmptyStr
    effective_at: UtcInstant
    as_of: UtcInstant
    expected_stream_version: NonNegativeInt
    # Plan 08 Task 7: optional causal binding; the official shadow adapter
    # requires it on every decision-derived fill.
    source_binding: CapitalSourceBinding | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "FillRevisionRequest":
        if self.as_of < self.effective_at:
            raise ValueError("as_of cannot precede effective_at")
        if self.revision == 1:
            if self.revision_kind is not None:
                raise ValueError(
                    "revision 1 is the RECORDED fill fact and carries no"
                    " revision kind"
                )
        else:
            if self.revision_kind not in (
                ExecutionRevisionKind.BUSTED,
                ExecutionRevisionKind.CORRECTED,
            ):
                raise ValueError(
                    "higher revisions require a BUSTED or CORRECTED kind"
                )
            # Bust/correction restate or replace facts of the recorded
            # fill; lot identity and attribution come from history, so the
            # entry-attribution rules below apply to revision 1 only.
            if self.reserve_source_id is not None:
                raise ValueError(
                    "execution revisions never consume a reserve"
                )
            return self
        has_lineage = self.position_lineage_id is not None
        has_lot = self.economic_lot_id is not None
        if has_lineage != has_lot:
            raise ValueError(
                "position_lineage_id and economic_lot_id are all-or-none"
            )
        if self.side is ExecutionSide.EXIT and not has_lineage:
            raise ValueError("exit fills require an explicit economic lot")
        if self.attribution is not None and not has_lineage:
            raise ValueError(
                "attributed fills require an explicit economic lot identity"
            )
        if (
            self.side is ExecutionSide.ENTRY
            and self.attribution is None
            and has_lineage
        ):
            raise ValueError(
                "entry fills with explicit lot identity require attribution"
            )
        if self.reserve_source_id is not None and self.side is not ExecutionSide.ENTRY:
            raise ValueError("only entry fills may consume a reserve")
        return self


class FillRevisionReceipt(CanonicalModel):
    """The durable outcome of one recorded fill revision."""

    execution_id: NonEmptyStr
    order_id: NonEmptyStr
    revision: PositiveInt
    event_id: NonEmptyStr
    side: ExecutionSide
    security_id: NonEmptyStr
    gross_cents: PositiveInt
    quantity: PositiveInt
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    unattributed: bool
    reserve_consumed_cents: NonNegativeCents | None
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


class FeeRevisionRequest(CanonicalModel):
    """One fee revision linked to its fill (a DISTINCT economic event).

    Revision 1 (``INITIAL``) charges the fill's fee under the versioned
    policy. Higher revisions (Plan 02 Task 6) follow a busted/corrected
    fill: they recompute the order's fee target from the active fill
    facts and book the signed delta against what the order's fee streams
    have actually charged.
    """

    fill_execution_id: NonEmptyStr
    revision: PositiveInt
    revision_kind: FeeRevisionKind = FeeRevisionKind.INITIAL
    fee_policy: FeePolicy
    source_authority: NonEmptyStr
    effective_at: UtcInstant
    as_of: UtcInstant
    expected_stream_version: NonNegativeInt
    # Plan 08 Task 7: optional causal binding; the official shadow adapter
    # requires it on every decision-derived fee.
    source_binding: CapitalSourceBinding | None = None

    @model_validator(mode="after")
    def validate_times(self) -> "FeeRevisionRequest":
        if self.as_of < self.effective_at:
            raise ValueError("as_of cannot precede effective_at")
        if self.revision == 1:
            if self.revision_kind is not FeeRevisionKind.INITIAL:
                raise ValueError(
                    "fee revision 1 is the INITIAL charge of the stream"
                )
        elif self.revision_kind is FeeRevisionKind.INITIAL:
            raise ValueError(
                "higher fee revisions require a BUSTED or CORRECTED kind"
            )
        return self


class FeeRevisionReceipt(CanonicalModel):
    """The durable outcome of one recorded fee revision.

    ``event_id`` is ``None`` exactly when the booked delta is zero: the
    registry row still records the fee fact, but no capital changed so no
    economic event exists and the capital version stays quiet.

    For the INITIAL revision the component fields and ``total_cents`` are
    the charged amounts (and ``booked_delta_cents`` equals the total). For
    Task 6 bust/correction revisions the component fields restate the
    order's recomputed fee target under the request's policy, and
    ``booked_delta_cents`` is the signed amount actually booked (a refund
    when negative).
    """

    fill_execution_id: NonEmptyStr
    order_id: NonEmptyStr
    revision: PositiveInt
    revision_kind: FeeRevisionKind
    event_id: NonEmptyStr | None
    fee_policy_version: NonEmptyStr
    commission_cents: NonNegativeCents
    stamp_tax_cents: NonNegativeCents
    transfer_fee_cents: NonNegativeCents
    total_cents: NonNegativeCents
    booked_delta_cents: int
    capital_version: NonNegativeInt
    stream_version: NonNegativeInt


def fill_idempotency_key(execution_id: str, revision: int) -> str:
    """Canonical idempotency identity of one fill revision."""

    return f"fill:{execution_id}:{revision}"


def fee_idempotency_key(fill_execution_id: str, revision: int) -> str:
    """Canonical idempotency identity of one fee revision."""

    return f"fee:{fill_execution_id}:{revision}"


def unattributed_position_identity(execution_id: str) -> tuple[str, str]:
    """Derive the sentinel lot identity for an unattributed fill.

    The fill itself is the only provenance, so both the lineage and lot are
    derived from the execution report identity; fills of one unattributed
    execution accumulate into one sentinel lot.
    """

    lineage = f"{UNATTRIBUTED_LOT_PREFIX}{execution_id}"
    return lineage, lineage


__all__ = [
    "UNATTRIBUTED_LINEAGE",
    "UNATTRIBUTED_LOT_PREFIX",
    "UNATTRIBUTED_PRODUCER",
    "UNATTRIBUTED_PROGRAM",
    "UNATTRIBUTED_STAGE",
    "FeeRevisionRequest",
    "FeeRevisionReceipt",
    "FillAttribution",
    "FillRevisionRequest",
    "FillRevisionReceipt",
    "fee_idempotency_key",
    "fill_idempotency_key",
    "unattributed_position_identity",
]
