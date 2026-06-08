"""Shared dataclasses for the short trade target evaluation pipeline.

Extracted from :mod:`src.targets.short_trade_target_evaluation_helpers` during the
R20.16 refactor to reduce the 1400-line file to a more manageable size.

This module hosts the frozen dataclasses used across evaluation helpers
(decision, reasons, explainability, and orchestration layers).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ShortTradeEvaluationContext:
    snapshot: dict[str, Any]
    carryover_evidence_deficiency: dict[str, Any]
    selected_historical_proof_deficiency: dict[str, Any]


@dataclass(frozen=True)
class ShortTradeThresholdState:
    breakout_freshness: float
    trend_acceleration: float
    effective_near_miss_threshold: float
    effective_select_threshold: float
    selected_score_tolerance: float
    breakout_stage: str
    selected_breakout_gate_pass: bool
    near_miss_breakout_gate_pass: bool


@dataclass(frozen=True)
class ShortTradeVerdict:
    decision: str
    confidence: float
    positive_tags: list[str]
    negative_tags: list[str]
    blockers: list[str]
    gate_status: dict[str, Any]
    top_reasons: list[str]
    rejection_reasons: list[str]
    downgrade_reasons: list[str]


@dataclass(frozen=True)
class ShortTradeMutableVerdictState:
    gate_status: dict[str, Any]
    positive_tags: list[str]
    negative_tags: list[str]
    blockers: list[str]


@dataclass(frozen=True)
class ShortTradeDecisionSnapshotState:
    profile: Any
    breakout_freshness: float
    trend_acceleration: float
    raw_catalyst_freshness: float
    catalyst_freshness: float
    score_target: float
    effective_near_miss_threshold: float
    effective_select_threshold: float
    selected_score_tolerance: float
    positive_tags: list[str]
    negative_tags: list[str]
    blockers: list[str]
    gate_status: dict[str, Any]


@dataclass(frozen=True)
class ShortTradeTopReasonsState:
    breakout_freshness: float
    trend_acceleration: float
    raw_catalyst_freshness: float
    upstream_shadow_catalyst_relief_applied: bool
    upstream_shadow_catalyst_relief_reason: str
    visibility_gap_continuation_relief: dict[str, Any]
    merge_approved_continuation_relief: dict[str, Any]
    prepared_breakout_penalty_relief: dict[str, Any]
    prepared_breakout_catalyst_relief: dict[str, Any]
    prepared_breakout_volume_relief: dict[str, Any]
    prepared_breakout_continuation_relief: dict[str, Any]
    prepared_breakout_selected_catalyst_relief: dict[str, Any]
    profitability_relief_applied: bool
    profitability_hard_cliff_boundary_relief: dict[str, Any]
    historical_execution_relief: dict[str, Any]
    event_catalyst_assessment: dict[str, Any]
    profitability_hard_cliff: bool
    breakout_stage: str
    layer_c_avoid_penalty: float
    stale_trend_repair_penalty: float
    overhead_supply_penalty: float
    extension_without_room_penalty: float
    breakout_trap_guard: dict[str, Any]
    market_state_threshold_adjustment: dict[str, Any]
    catalyst_theme_guard: dict[str, Any]
    watchlist_zero_catalyst_guard: dict[str, Any]
    watchlist_zero_catalyst_crowded_guard: dict[str, Any]
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any]
    watchlist_filter_diagnostics_flat_trend_guard: dict[str, Any]
    watchlist_filter_diagnostics_selected_only_shrink_guard: dict[str, Any]
    layer_c_watchlist_selected_only_shrink_guard: dict[str, Any]
    short_trade_boundary_selected_only_shrink_guard: dict[str, Any]
    carryover_evidence_deficiency: dict[str, Any]
    selected_historical_proof_deficiency: dict[str, Any]
    t_plus_2_continuation_candidate: dict[str, Any]
    score_target: float


@dataclass(frozen=True)
class ShortTradeExplainabilityState:
    profile: Any
    market_state_threshold_adjustment: dict[str, Any]
    breakout_trap_guard: dict[str, Any]
    profitability_hard_cliff_boundary_relief: dict[str, Any]
    historical_execution_relief: dict[str, Any]
    visibility_gap_continuation_relief: dict[str, Any]
    merge_approved_continuation_relief: dict[str, Any]
    prepared_breakout_penalty_relief: dict[str, Any]
    prepared_breakout_catalyst_relief: dict[str, Any]
    prepared_breakout_volume_relief: dict[str, Any]
    prepared_breakout_continuation_relief: dict[str, Any]
    prepared_breakout_selected_catalyst_relief: dict[str, Any]
    catalyst_theme_guard: dict[str, Any]
    watchlist_zero_catalyst_guard: dict[str, Any]
    watchlist_zero_catalyst_crowded_guard: dict[str, Any]
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any]
    watchlist_filter_diagnostics_flat_trend_guard: dict[str, Any]
    watchlist_filter_diagnostics_selected_only_shrink_guard: dict[str, Any]
    layer_c_watchlist_selected_only_shrink_guard: dict[str, Any]
    short_trade_boundary_selected_only_shrink_guard: dict[str, Any]
    t_plus_2_continuation_candidate: dict[str, Any]
