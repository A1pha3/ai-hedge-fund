"""Growth Kernel frozen inputs and decision outputs (Plan 04 Task 1+).

The kernel is pure: no storage, no network, no clock, no I/O. Identical
canonical input must produce identical canonical output bytes/hash.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar

from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    Sha256,
    UtcInstant,
)
from src.screening.offensive.v3.contracts.base import CanonicalModel
from src.screening.offensive.v3.contracts.authorization import (
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.capital import (
    CapitalRiskSnapshot,
    NonNegativeCents,
    NonNegativeUnits,
    PositiveExactInt,
)
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr
from src.screening.offensive.v3.contracts.governance import PolicyActivation


class BlockReason(StrEnum):
    """Typed fail-closed block reasons; never zero/default fallbacks."""

    RISK_HALTED = "RISK_HALTED"
    RECONCILIATION_HALTED = "RECONCILIATION_HALTED"
    STAGE_LOSS_HALTED = "STAGE_LOSS_HALTED"
    STALE_CAPITAL = "STALE_CAPITAL"
    UNKNOWN_CAPITAL_FRESHNESS = "UNKNOWN_CAPITAL_FRESHNESS"
    UNKNOWN_EXPOSURE = "UNKNOWN_EXPOSURE"
    NEGATIVE_NAV = "NEGATIVE_NAV"
    POLICY_ENVELOPE_MISMATCH = "POLICY_ENVELOPE_MISMATCH"
    MODE_MISMATCH = "MODE_MISMATCH"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    CAPITAL_VERSION_MISMATCH = "CAPITAL_VERSION_MISMATCH"
    EVIDENCE_CUTOFF_MISSING = "EVIDENCE_CUTOFF_MISSING"
    CLOSE_NOT_FINALIZED = "CLOSE_NOT_FINALIZED"
    DEADLINE_MISSED = "DEADLINE_MISSED"
    NO_AUTHORIZED_ENVELOPE = "NO_AUTHORIZED_ENVELOPE"
    NO_SIGNAL = "NO_SIGNAL"
    CAPACITY_EXHAUSTED = "CAPACITY_EXHAUSTED"
    LOT_FLOOR_ZERO = "LOT_FLOOR_ZERO"
    MISSING_ADV = "MISSING_ADV"
    PRICE_BOUNDARY_INVALID = "PRICE_BOUNDARY_INVALID"


class RiskDecisionStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


class RiskDecision(CanonicalModel):
    """One complete portfolio risk evaluation."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.risk-decision.v1"

    status: RiskDecisionStatus
    block_reason: BlockReason | None = None
    drawdown_multiplier_ppm: int
    risk_adjustment_count: int


class RiskAdjustedTargets(CanonicalModel):
    """Lineage targets and portfolio ceiling after ONE risk application."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.risk-adjusted.v1"

    adjusted_lineage_gross_cents: tuple[tuple[str, int], ...]
    adjusted_portfolio_gross_cap_cents: int
    risk_adjustment_count: int


class RawCandidate(CanonicalModel):
    """One producer candidate signal; never carries sizing authority."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.raw-candidate.v1"

    candidate_id: NonEmptyStr
    producer_namespace: NonEmptyStr
    family_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    research_program_id: NonEmptyStr
    stage_id: NonEmptyStr
    security_id: NonEmptyStr
    direction: NonEmptyStr
    unscaled_target_gross_cents: NonNegativeCents
    behavior_fingerprint: Sha256
    execution_version: NonEmptyStr
    cost_version: NonEmptyStr
    evidence_ids: tuple[Sha256, ...] = ()


class DeadlineContract(CanonicalModel):
    """Explicit time-point contract; ordering is validated fail-closed.

    close_finalized <= seal_creation_deadline < permit_issue_deadline
    < permit_expires_at <= gateway_send_deadline < broker_cutoff.
    """

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.deadlines.v1"

    close_finalized_at: UtcInstant
    seal_creation_deadline: UtcInstant
    permit_issue_deadline: UtcInstant
    permit_expires_at: UtcInstant
    gateway_send_deadline: UtcInstant
    broker_auction_cutoff: UtcInstant

    def ordering_valid(self) -> bool:
        return (
            self.close_finalized_at <= self.seal_creation_deadline
            < self.permit_issue_deadline
            < self.permit_expires_at
            <= self.gateway_send_deadline
            < self.broker_auction_cutoff
        )


class KernelInput(CanonicalModel):
    """The complete frozen input of one growth-kernel decision cycle."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.input.v1"

    portfolio_id: NonEmptyStr
    signal_session: date
    decision_cycle_id: NonEmptyStr
    mode: ExecutionMode
    policy_activation: PolicyActivation
    envelope: CapitalAuthorizationEnvelope
    capital: CapitalRiskSnapshot
    deadlines: DeadlineContract
    trusted_evidence_cutoff: UtcInstant
    raw_candidates: tuple[RawCandidate, ...] = ()
    price_micros_by_candidate: tuple[tuple[str, int], ...] = ()
    industry_by_candidate: tuple[tuple[str, str], ...] = ()


class NoTradeDecision(CanonicalModel):
    """A deterministic no-trade decision with a typed reason."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.no-trade.v1"

    portfolio_id: NonEmptyStr
    signal_session: date
    decision_cycle_id: NonEmptyStr
    reason: BlockReason
    detail: str = ""


class PortfolioDecisionLine(CanonicalModel):
    """One proposed entry line of a complete portfolio decision."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.decision-line.v1"

    candidate_id: NonEmptyStr
    security_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    research_program_id: NonEmptyStr
    stage_id: NonEmptyStr
    direction: NonEmptyStr
    quantity_units: NonNegativeUnits
    limit_price_micros: int
    worst_case_reserve_cents: NonNegativeCents
    status: NonEmptyStr
    block_reason: BlockReason | None = None


class PortfolioDecision(CanonicalModel):
    """The complete portfolio decision proposal (never self-activated).

    The kernel assigns no repository id, active status or signature; the
    Capital Gateway owns sealing and activation.
    """

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.decision.v1"

    portfolio_id: NonEmptyStr
    signal_session: date
    decision_cycle_id: NonEmptyStr
    mode: ExecutionMode
    policy_activation_hash: Sha256
    policy_epoch: PositiveExactInt
    authority_epoch: PositiveExactInt
    risk_epoch: PositiveExactInt
    capital_snapshot_hash: Sha256
    capital_version: PositiveExactInt
    lines: tuple[PortfolioDecisionLine, ...]
    portfolio_gross_cap_cents: NonNegativeCents
    total_reserved_worst_case_cents: NonNegativeCents


__all__ = [
    "BlockReason",
    "DeadlineContract",
    "KernelInput",
    "NoTradeDecision",
    "PortfolioDecision",
    "PortfolioDecisionLine",
    "RawCandidate",
    "RiskAdjustedTargets",
    "RiskDecision",
    "RiskDecisionStatus",
]
