from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SelectionTargetType = Literal["research", "short_trade"]
TargetDecision = Literal["selected", "near_miss", "rejected", "blocked"]
TargetMode = Literal["research_only", "short_trade_only", "dual_target"]


class TargetEvaluationInput(BaseModel):
    trade_date: str
    ticker: str
    market: str = "CN"
    market_state: dict[str, Any] = Field(default_factory=dict)
    score_b: float = 0.0
    score_c: float = 0.0
    score_final: float = 0.0
    quality_score: float = 0.5
    layer_c_decision: str = ""
    bc_conflict: str | None = None
    strategy_signals: dict[str, Any] = Field(default_factory=dict)
    agent_contribution_summary: dict[str, Any] = Field(default_factory=dict)
    execution_constraints: dict[str, Any] = Field(default_factory=dict)
    replay_context: dict[str, Any] = Field(default_factory=dict)


class TargetEvaluationResult(BaseModel):
    target_type: SelectionTargetType
    decision: TargetDecision | None = None
    score_target: float = 0.0
    confidence: float = 0.0
    rank_hint: int | None = None
    positive_tags: list[str] = Field(default_factory=list)
    negative_tags: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    top_reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    gate_status: dict[str, str] = Field(default_factory=dict)
    expected_holding_window: str | None = None
    preferred_entry_mode: str | None = None
    candidate_source: str | None = None
    effective_near_miss_threshold: float | None = None
    effective_select_threshold: float | None = None
    breakout_freshness: float | None = None
    trend_acceleration: float | None = None
    volume_expansion_quality: float | None = None
    close_strength: float | None = None
    sector_resonance: float | None = None
    catalyst_freshness: float | None = None
    layer_c_alignment: float | None = None
    momentum_strength: float | None = None
    weighted_positive_contributions: dict[str, Any] = Field(default_factory=dict)
    weighted_negative_contributions: dict[str, Any] = Field(default_factory=dict)
    metrics_payload: dict[str, Any] = Field(default_factory=dict)
    explainability_payload: dict[str, Any] = Field(default_factory=dict)


class DualTargetEvaluation(BaseModel):
    ticker: str
    trade_date: str
    research: TargetEvaluationResult | None = None
    short_trade: TargetEvaluationResult | None = None
    candidate_source: str | None = None
    candidate_reason_codes: list[str] = Field(default_factory=list)
    delta_classification: str | None = None
    delta_summary: list[str] = Field(default_factory=list)


class DualTargetSummary(BaseModel):
    target_mode: TargetMode = "research_only"
    selection_target_count: int = 0
    research_target_count: int = 0
    short_trade_target_count: int = 0
    research_selected_count: int = 0
    research_near_miss_count: int = 0
    research_rejected_count: int = 0
    short_trade_selected_count: int = 0
    short_trade_near_miss_count: int = 0
    short_trade_blocked_count: int = 0
    short_trade_rejected_count: int = 0
    shell_target_count: int = 0
    delta_classification_counts: dict[str, int] = Field(default_factory=dict)
