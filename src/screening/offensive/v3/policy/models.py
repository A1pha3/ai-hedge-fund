"""Immutable, complete policy contracts for the v3 growth kernel."""

from __future__ import annotations

from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Annotated, ClassVar, Self

from pydantic import Field, StringConstraints, model_validator

from ..contracts.base import CanonicalModel, content_hash

SUPPORTED_POLICY_SCHEMA_MAJOR = 1

VersionStr = Annotated[
    str,
    StringConstraints(
        min_length=1,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:+/-]*$",
    ),
]
IdentifierStr = Annotated[
    str,
    StringConstraints(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
SemVer = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"),
]
Fraction = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
PositiveInt = Annotated[int, Field(ge=1)]


class RuntimeMode(StrEnum):
    """Governed runtime modes, ordered operationally but not by risk."""

    OFF = "off"
    SHADOW = "shadow"
    BTST_CANARY = "btst_canary"
    AUTHORITATIVE = "authoritative"


class MissingAdvBehavior(StrEnum):
    """Only fail-closed ADV handling is admitted by this schema."""

    FAIL_CLOSED = "fail_closed"


class CapitalTier(IntEnum):
    """Governed lineage gross-risk tiers, expressed as whole percentages."""

    EXPLORATION = 2
    CANARY = 5
    MAXIMUM = 10


class CapitalPolicy(CanonicalModel):
    """Portfolio and stage ceilings; all fractions use Decimal truth."""

    governed_tiers: tuple[CapitalTier, ...]
    exploration_aggregate_gross_cap: Fraction
    portfolio_gross_cap: Fraction
    single_name_gross_cap: Fraction
    industry_gross_cap: Fraction
    daily_entry_gross_cap: Fraction
    stage_loss_budget_cap: Fraction

    @model_validator(mode="after")
    def validate_capital_policy(self) -> Self:
        if self.governed_tiers != (
            CapitalTier.EXPLORATION,
            CapitalTier.CANARY,
            CapitalTier.MAXIMUM,
        ):
            raise ValueError("governed capital tiers must be exactly 2/5/10 percent")
        if self.exploration_aggregate_gross_cap > Decimal("0.02"):
            raise ValueError("aggregate exploration gross cap cannot exceed 2 percent")
        if self.portfolio_gross_cap > Decimal("0.10"):
            raise ValueError("portfolio gross cap cannot exceed 10 percent")
        for name in (
            "single_name_gross_cap",
            "industry_gross_cap",
            "daily_entry_gross_cap",
        ):
            if getattr(self, name) > self.portfolio_gross_cap:
                raise ValueError(f"{name} cannot exceed portfolio_gross_cap")
        return self


class RiskPolicy(CanonicalModel):
    """Fixed drawdown boundary values from the architecture constitution."""

    drawdown_scale_start: Fraction
    drawdown_halt: Fraction
    halt_is_latched: bool
    inherited_risk_counts_on_restart: bool

    @model_validator(mode="after")
    def validate_fixed_drawdown_contract(self) -> Self:
        if self.drawdown_scale_start != Decimal("0.10"):
            raise ValueError("drawdown scaling must start at exactly 10 percent")
        if self.drawdown_halt != Decimal("0.15"):
            raise ValueError("drawdown halt must begin at exactly 15 percent")
        if not self.halt_is_latched:
            raise ValueError("the 15 percent drawdown halt must latch")
        if not self.inherited_risk_counts_on_restart:
            raise ValueError("inherited risk must count on restart")
        return self


class AdvPolicy(CanonicalModel):
    """PIT ADV capacity rule used before any entry order can be created."""

    lookback_sessions: PositiveInt
    max_participation_rate: Annotated[Decimal, Field(gt=Decimal("0"), le=Decimal("1"))]
    missing_data_behavior: MissingAdvBehavior


class ProducerPolicy(CanonicalModel):
    """Explicit producer and sizing switches; no environment fallback exists."""

    btst_enabled: bool
    oversold_bounce_enabled: bool
    regime_sizing_enabled: bool
    streak_sizing_enabled: bool
    trigger_strength_sizing_enabled: bool
    composite_sizing_enabled: bool

    def any_enabled(self) -> bool:
        return any(self.model_dump(mode="python").values())


class ExecutionPolicy(CanonicalModel):
    """Fixed T0/T+1/T+10 order contract and internal deadline margins."""

    entry_session_ordinal: Annotated[int, Field(ge=1)]
    exit_session_ordinal: Annotated[int, Field(ge=1)]
    order_type: IdentifierStr
    time_in_force: IdentifierStr
    seal_deadline_after_t0_close_minutes: PositiveInt
    permit_deadline_before_auction_minutes: PositiveInt
    gateway_send_deadline_before_auction_minutes: PositiveInt
    broker_auction_submission_cutoff_cn: Annotated[str, StringConstraints(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]$")]
    worst_case_cost_multiplier: Annotated[Decimal, Field(ge=Decimal("1"))]

    @model_validator(mode="after")
    def validate_execution_contract(self) -> Self:
        if self.entry_session_ordinal != 1 or self.exit_session_ordinal != 10:
            raise ValueError("economic contract must enter T+1 and exit T+10")
        if self.permit_deadline_before_auction_minutes <= self.gateway_send_deadline_before_auction_minutes:
            raise ValueError("permit deadline must precede gateway send deadline")
        return self


class VersionBindings(CanonicalModel):
    """Every behavior/execution dependency that must match at runtime."""

    execution_contract_version: VersionStr
    cost_version: VersionStr
    board_rule_version: VersionStr
    calendar_version: VersionStr
    lot_rule_version: VersionStr
    price_boundary_version: VersionStr
    setup_version: VersionStr
    exit_policy_version: VersionStr
    governance_version: VersionStr


class EvidenceGatePolicy(CanonicalModel):
    """Initial necessary evidence gates; satisfying them is never sufficient alone."""

    min_mature_outcomes: Annotated[int, Field(ge=150)]
    min_decision_days: Annotated[int, Field(ge=60)]
    min_effective_sample_size: Annotated[Decimal, Field(ge=Decimal("60"))]
    min_distinct_tickers: Annotated[int, Field(ge=80)]
    min_forward_months: Annotated[int, Field(ge=12)]
    adverse_window_required: bool
    chronological_fold_gate_required: bool
    capacity_stress_required: bool
    tail_risk_gate_required: bool
    fresh_evidence_per_tier_required: bool
    slippage_stress_multiple: Annotated[Decimal, Field(ge=Decimal("2"))]
    minimum_economic_effect: Annotated[Decimal, Field(gt=Decimal("0"))]
    incremental_minimum_economic_effect: Annotated[Decimal, Field(gt=Decimal("0"))]

    @model_validator(mode="after")
    def validate_required_gates(self) -> Self:
        required = (
            self.adverse_window_required,
            self.chronological_fold_gate_required,
            self.capacity_stress_required,
            self.tail_risk_gate_required,
            self.fresh_evidence_per_tier_required,
        )
        if not all(required):
            raise ValueError("all initial evidence and stress gates must be required")
        return self


class ProducerIdentity(CanonicalModel):
    """Small typed identity needed to distinguish producer behavior generations."""

    producer_namespace: IdentifierStr
    strategy_semver: SemVer


class PolicySnapshot(CanonicalModel):
    """One immutable, canonically hashable policy generation."""

    _DRAWDOWN_SCALE_START: ClassVar[Decimal] = Decimal("0.10")
    _DRAWDOWN_HALT: ClassVar[Decimal] = Decimal("0.15")
    _DRAWDOWN_RAMP_WIDTH: ClassVar[Decimal] = Decimal("0.05")

    schema_major: int
    policy_id: IdentifierStr
    policy_version: VersionStr
    policy_epoch: PositiveInt
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    runtime_mode: RuntimeMode
    capital: CapitalPolicy
    risk: RiskPolicy
    adv: AdvPolicy
    producers: ProducerPolicy
    execution: ExecutionPolicy
    versions: VersionBindings
    evidence_gates: EvidenceGatePolicy

    @property
    def policy_fingerprint(self) -> str:
        """Hash the entire canonical policy payload; the hash is not stored in it."""

        return _revalidate_policy_snapshot(self).content_hash()

    @staticmethod
    def drawdown_multiplier(drawdown: Decimal) -> Decimal:
        """Return the one exact portfolio risk multiplier from design section 11.1."""

        if not isinstance(drawdown, Decimal):
            raise TypeError("drawdown must be a Decimal")
        if not drawdown.is_finite() or drawdown < 0:
            raise ValueError("drawdown must be a finite non-negative Decimal")
        if drawdown < PolicySnapshot._DRAWDOWN_SCALE_START:
            return Decimal("1")
        if drawdown < PolicySnapshot._DRAWDOWN_HALT:
            return (PolicySnapshot._DRAWDOWN_HALT - drawdown) / PolicySnapshot._DRAWDOWN_RAMP_WIDTH
        return Decimal("0")

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.schema_major != SUPPORTED_POLICY_SCHEMA_MAJOR:
            raise ValueError(f"unsupported policy schema major: {self.schema_major}; " f"expected {SUPPORTED_POLICY_SCHEMA_MAJOR}")
        if self.runtime_mode is RuntimeMode.OFF:
            caps = (
                self.capital.exploration_aggregate_gross_cap,
                self.capital.portfolio_gross_cap,
                self.capital.single_name_gross_cap,
                self.capital.industry_gross_cap,
                self.capital.daily_entry_gross_cap,
                self.capital.stage_loss_budget_cap,
            )
            if any(cap != 0 for cap in caps):
                raise ValueError("off runtime mode requires every executable risk cap to be zero")
            if self.producers.any_enabled():
                raise ValueError("off runtime mode requires every producer switch to be disabled")
        return self


def behavior_fingerprint(
    producer: ProducerIdentity,
    policy: PolicySnapshot,
) -> str:
    """Hash only typed producer identity and explicit behavior-affecting policy."""

    if not isinstance(producer, ProducerIdentity):
        raise TypeError("producer must be a ProducerIdentity")
    if not isinstance(policy, PolicySnapshot):
        raise TypeError("policy must be a PolicySnapshot")
    validated_producer = ProducerIdentity.model_validate(producer.model_dump(mode="python", round_trip=True), strict=True)
    validated_policy = _revalidate_policy_snapshot(policy)
    behavior_policy = {
        "runtime_mode": validated_policy.runtime_mode,
        "capital": validated_policy.capital,
        "risk": validated_policy.risk,
        "adv": validated_policy.adv,
        "producers": validated_policy.producers,
        "execution": validated_policy.execution,
        "versions": validated_policy.versions,
        "evidence_gates": validated_policy.evidence_gates,
    }
    return content_hash({"producer": validated_producer, "policy": behavior_policy})


def _revalidate_policy_snapshot(policy: PolicySnapshot) -> PolicySnapshot:
    return PolicySnapshot.model_validate(policy.model_dump(mode="python", round_trip=True), strict=True)


__all__ = [
    "AdvPolicy",
    "CapitalPolicy",
    "CapitalTier",
    "EvidenceGatePolicy",
    "ExecutionPolicy",
    "MissingAdvBehavior",
    "PolicySnapshot",
    "ProducerIdentity",
    "ProducerPolicy",
    "RiskPolicy",
    "RuntimeMode",
    "SUPPORTED_POLICY_SCHEMA_MAJOR",
    "VersionBindings",
    "behavior_fingerprint",
]
