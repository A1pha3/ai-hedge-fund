"""Strict raw-candidate payload carried by BTST ``SignalEvidence``.

The payload is producer evidence, never an authorization.  All economic
quantities use integer units so historical replay does not depend on binary
floating-point serialization.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .base import CanonicalModel, ExactInteger, Sha256, SignalStage


NonEmptyStr = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]
SecurityId = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9]{6}\.(?:SH|SZ|BJ)$"),
]
PositiveExactInt = Annotated[ExactInteger, Field(ge=1)]
TriggerStrengthPpm = Annotated[ExactInteger, Field(ge=0, le=1_000_000)]
WeightPpm = Annotated[ExactInteger, Field(ge=1, le=1_000_000)]


class BtstCandidateIndustryState(StrEnum):
    """Whether the PIT snapshot supplied a named industry."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class BtstRawCandidatePayload(CanonicalModel):
    """One durable, replayable BTST candidate at one funnel stage.

    ``target_weight_ppm`` is the producer's raw target.  Downstream policy,
    risk, capacity, cash, and lot constraints may only clamp it; this payload
    does not apply a portfolio or NAV-derived allocation.
    """

    payload_kind: Literal["btst_raw_candidate"]
    schema_major: Annotated[ExactInteger, Field(ge=1, le=1)]
    candidate_id: NonEmptyStr
    producer_namespace: Literal["btst"]
    security_id: SecurityId
    signal_stage: SignalStage
    signal_session: date
    entry_price_micros: PositiveExactInt
    setup: Literal["btst_breakout"]
    setup_version: NonEmptyStr
    target_weight_ppm: WeightPpm
    trigger_strength_ppm: TriggerStrengthPpm
    priority: PositiveExactInt
    industry_state: BtstCandidateIndustryState
    industry: NonEmptyStr | None
    snapshot_id: NonEmptyStr
    setup_consumed_fingerprint: NonEmptyStr
    strategy_semver: NonEmptyStr
    behavior_fingerprint: Sha256
    execution_version: NonEmptyStr
    cost_version: NonEmptyStr

    @model_validator(mode="after")
    def validate_industry_state(self) -> "BtstRawCandidatePayload":
        if self.industry_state is BtstCandidateIndustryState.KNOWN:
            if self.industry is None:
                raise ValueError("KNOWN industry_state requires industry")
        elif self.industry is not None:
            raise ValueError("UNKNOWN industry_state requires industry=None")
        return self


__all__ = [
    "BtstCandidateIndustryState",
    "BtstRawCandidatePayload",
]
