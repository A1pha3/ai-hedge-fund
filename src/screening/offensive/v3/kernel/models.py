"""Growth Kernel frozen inputs and decision outputs (Plan 04 Task 1+).

The kernel is pure: no storage, no network, no clock, no I/O. Identical
canonical input must produce identical canonical output bytes/hash.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, model_validator

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
from src.screening.offensive.v3.contracts.regime import RegimeObservation
from src.screening.offensive.v3.contracts.trial import (
    ShadowPolicyBinding,
    ShadowPolicySourceKind,
    TrialArm,
)
from src.screening.offensive.v3.policy.models import PolicySnapshot
from src.screening.offensive.v3.kernel.config import SizingConfig


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
    REGIME_ADMISSION_BLOCKED = "REGIME_ADMISSION_BLOCKED"


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
    policy_snapshot: PolicySnapshot
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
    kernel_input_hash: Sha256 | None = None


class CoreNoTrade:
    """Internal core no-trade result; identity-free until projected by a caller."""

    __slots__ = ("reason",)

    def __init__(self, *, reason: BlockReason) -> None:
        self.reason = reason

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CoreNoTrade) and self.reason is other.reason

    def __hash__(self) -> int:
        return hash(self.reason)


class CorePortfolioDecision:
    """Internal core decision result; projected by the executable or shadow path.

    Carries no identity, authority or provenance — those belong to the
    projection (``PortfolioDecision`` or ``ShadowDecision``).
    """

    __slots__ = ("lines", "portfolio_gross_cap_cents", "total_reserved_worst_case_cents")

    def __init__(
        self,
        *,
        lines: tuple[PortfolioDecisionLine, ...],
        portfolio_gross_cap_cents: int,
        total_reserved_worst_case_cents: int,
    ) -> None:
        self.lines = lines
        self.portfolio_gross_cap_cents = portfolio_gross_cap_cents
        self.total_reserved_worst_case_cents = total_reserved_worst_case_cents


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
    worst_case_fee_reserve_cents: NonNegativeCents
    worst_case_reserve_cents: NonNegativeCents
    status: Literal["ENTRY_PLANNED", "BLOCKED"]
    block_reason: BlockReason | None = None

    @model_validator(mode="after")
    def validate_reserve_economics(self) -> Self:
        if self.status == "ENTRY_PLANNED":
            if self.quantity_units <= 0 or self.limit_price_micros <= 0:
                raise ValueError("planned entry requires positive quantity and price")
            if self.limit_price_micros % 10_000 != 0:
                raise ValueError("planned entry price must be an exact cent tick")
            gross_cents = self.quantity_units * self.limit_price_micros // 10_000
            if self.worst_case_reserve_cents != (
                gross_cents + self.worst_case_fee_reserve_cents
            ):
                raise ValueError("decision reserve must equal gross plus fee reserve")
            if self.block_reason is not None:
                raise ValueError("planned decision line cannot carry a block reason")
        elif (
            self.quantity_units != 0
            or self.limit_price_micros != 0
            or self.worst_case_fee_reserve_cents != 0
            or self.worst_case_reserve_cents != 0
        ):
            raise ValueError("blocked decision line requires zero economics")
        elif self.block_reason is None:
            raise ValueError("blocked decision line requires a block reason")
        return self


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


class CandidateEvidenceBinding(CanonicalModel):
    """One candidate↔evidence binding for a shadow decision line.

    The evidence identity and both payload/artifact hashes are frozen by the
    caller (the shadow producer); the kernel copies them verbatim into the
    shadow decision line, so provenance is never synthesized inside the kernel.
    """

    candidate_id: NonEmptyStr
    evidence_id: NonEmptyStr
    evidence_artifact_hash: Sha256
    evidence_payload_hash: Sha256


class FrozenTradingSessionSchedule(CanonicalModel):
    """Cutoff-visible exchange sessions that define exact T+1 through T+10."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.trading-schedule.v1"

    calendar_id: NonEmptyStr
    calendar_version: NonEmptyStr
    calendar_artifact_hash: Sha256
    signal_session: date
    following_sessions: Annotated[tuple[date, ...], Field(min_length=10, max_length=10)]
    available_at: UtcInstant

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        if any(session <= self.signal_session for session in self.following_sessions):
            raise ValueError("following trading sessions must follow signal_session")
        if tuple(sorted(set(self.following_sessions))) != self.following_sessions:
            raise ValueError("following trading sessions must be unique and increasing")
        return self


class ShadowSharedInput(CanonicalModel):
    """The shared frozen world of one paired-trial session; identical for both arms.

    The frozen trusted time lives here, so both arm calls consume exactly one
    observation and ``decide_shadow`` never takes a ``trusted_at`` argument.
    """

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.shadow-shared.v1"

    signal_session: date
    decision_cycle_id: NonEmptyStr
    trial_manifest_hash: Sha256
    sap_manifest_hash: Sha256
    mode: ExecutionMode
    trusted_evidence_cutoff: UtcInstant
    evidence_set_merkle_root: Sha256
    regime_observation: RegimeObservation
    trial_id: NonEmptyStr
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    stage_manifest_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveExactInt
    trusted_at: UtcInstant
    trading_session_schedule: FrozenTradingSessionSchedule

    @model_validator(mode="after")
    def validate_shared(self) -> Self:
        if self.mode is not ExecutionMode.DAILY_BAR_PROXY:
            raise ValueError("a shadow trial session must run in DAILY_BAR_PROXY mode")
        if self.regime_observation.signal_session != self.signal_session:
            raise ValueError(
                "regime observation signal_session must match the shared session"
            )
        if self.stage_manifest_hash == "0" * 64:
            raise ValueError("stage manifest hash cannot use the zero sentinel")
        schedule = self.trading_session_schedule
        if schedule.signal_session != self.signal_session:
            raise ValueError("trading schedule signal_session must match shared session")
        if schedule.available_at > self.trusted_evidence_cutoff:
            raise ValueError("trading schedule must be available by evidence cutoff")
        return self


class ShadowCapitalCheckpoint(CanonicalModel):
    """One arm-specific frozen capital truth; never an executable authority."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.shadow-capital-checkpoint.v2"

    trial_id: NonEmptyStr
    arm: TrialArm
    portfolio_id: NonEmptyStr
    mode: ExecutionMode
    capital_store_id: NonEmptyStr
    trial_genesis_manifest_hash: Sha256
    arm_capital_genesis_root: Sha256
    capital_snapshot_hash: Sha256
    capital_snapshot: CapitalRiskSnapshot

    @model_validator(mode="after")
    def validate_checkpoint(self) -> Self:
        if self.mode is not ExecutionMode.DAILY_BAR_PROXY:
            raise ValueError("shadow capital checkpoint mode must be DAILY_BAR_PROXY")
        if self.capital_snapshot.portfolio_id != self.portfolio_id:
            raise ValueError("capital checkpoint portfolio does not match snapshot")
        if self.capital_snapshot.mode is not self.mode:
            raise ValueError("capital checkpoint mode does not match snapshot")
        if self.capital_snapshot.broker_account_id is not None:
            raise ValueError("shadow capital checkpoint cannot bind a broker account")
        if self.trial_genesis_manifest_hash == "0" * 64:
            raise ValueError("trial genesis manifest hash cannot use the zero sentinel")
        if self.arm_capital_genesis_root == "0" * 64:
            raise ValueError("arm capital genesis root cannot use the zero sentinel")
        if self.capital_snapshot.content_hash() != self.capital_snapshot_hash:
            raise ValueError(
                "capital checkpoint hash does not match the embedded snapshot"
            )
        return self


class ShadowKernelInput(CanonicalModel):
    """The exact, authority-free frozen input of one arm decision.

    Deliberately carries no ``PolicyActivation`` object, no
    ``CapitalAuthorizationEnvelope``, no permit nonce and no broker account:
    the shadow admission maps the bound ``PolicySnapshot`` into the same
    ``DecisionConstraints`` the executable admission derives from its grant.
    """

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.kernel.shadow-input.v1"

    portfolio_id: NonEmptyStr
    arm: TrialArm
    shared: ShadowSharedInput
    policy_snapshot: PolicySnapshot
    shadow_policy_binding: ShadowPolicyBinding
    capital_checkpoint: ShadowCapitalCheckpoint
    deadlines: DeadlineContract
    sizing_config: SizingConfig
    candidate_evidence_bindings: tuple[CandidateEvidenceBinding, ...] = ()
    raw_candidates: tuple[RawCandidate, ...] = ()
    price_micros_by_candidate: tuple[tuple[str, int], ...] = ()
    industry_by_candidate: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="after")
    def validate_shadow_input(self) -> Self:
        _validate_shadow_policy_binding(
            self.arm, self.policy_snapshot, self.shadow_policy_binding
        )
        checkpoint = self.capital_checkpoint
        if checkpoint.trial_id != self.shared.trial_id:
            raise ValueError("capital checkpoint trial does not match shared input")
        if checkpoint.arm is not self.arm:
            raise ValueError("capital checkpoint arm does not match shared input")
        if checkpoint.portfolio_id != self.portfolio_id:
            raise ValueError("capital checkpoint portfolio does not match shared input")
        if checkpoint.mode is not self.shared.mode:
            raise ValueError("capital checkpoint mode does not match shared input")
        if (
            self.shared.trading_session_schedule.calendar_version
            != self.policy_snapshot.versions.calendar_version
        ):
            raise ValueError("trading schedule version must match the bound policy")
        for binding in self.candidate_evidence_bindings:
            if binding.candidate_id not in {c.candidate_id for c in self.raw_candidates}:
                raise ValueError(
                    "candidate evidence binding references an unknown candidate"
                )
        return self


def _validate_shadow_policy_binding(
    arm: TrialArm,
    policy: PolicySnapshot,
    binding: ShadowPolicyBinding,
) -> None:
    """The arm's binding must exactly match the arm policy and the shared session.

    The Champion arm binds the trial's baseline policy activation; the
    Challenger arm binds the target policy registration. Either way the
    binding's policy snapshot hash and fingerprint must match the embedded
    ``PolicySnapshot``, and a binding whose source kind contradicts the arm
    (or the trial/SAP hashes carried by the shared input) is rejected.
    """

    if binding.policy_snapshot_hash != policy.content_hash():
        raise ValueError("shadow policy binding snapshot hash does not match the policy")
    if binding.policy_fingerprint != policy.policy_fingerprint:
        raise ValueError("shadow policy binding fingerprint does not match the policy")
    if arm is TrialArm.CHAMPION:
        if binding.source_kind is not ShadowPolicySourceKind.BASELINE_POLICY_ACTIVATION:
            raise ValueError("a champion arm must bind the baseline policy activation")
    elif binding.source_kind is not ShadowPolicySourceKind.TARGET_POLICY_REGISTRATION:
        raise ValueError("a challenger arm must bind the target policy registration")


__all__ = [
    "BlockReason",
    "CandidateEvidenceBinding",
    "CoreNoTrade",
    "CorePortfolioDecision",
    "DeadlineContract",
    "FrozenTradingSessionSchedule",
    "KernelInput",
    "NoTradeDecision",
    "PortfolioDecision",
    "PortfolioDecisionLine",
    "RawCandidate",
    "RiskAdjustedTargets",
    "RiskDecision",
    "RiskDecisionStatus",
    "ShadowCapitalCheckpoint",
    "ShadowKernelInput",
    "ShadowSharedInput",
]
