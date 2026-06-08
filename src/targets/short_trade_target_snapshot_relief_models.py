"""Shared dataclasses for short trade target snapshot relief pipeline.

Extracted during the R20.15 refactor to break a circular import between
:mod:`src.targets.short_trade_target_snapshot_relief_criteria_helpers` and
:mod:`src.targets.short_trade_target_snapshot_relief_resolution_helpers`.

This module hosts *only* the frozen dataclasses used across both layers
(:class:`SnapshotSignalState`, :class:`PreparedBreakoutReliefs`,
:class:`SnapshotThresholdState`, :class:`WatchlistPenaltyState`,
:class:`ScorePenaltyState`, :class:`SnapshotReliefResolution`,
:class:`SnapshotCoreReliefs`, :class:`SnapshotResolutionCoreState`).
The orchestration that produces them lives in the two sibling modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SnapshotSignalState:
    fundamental_signal: dict[str, Any]
    breakout_stage: str
    breakout_freshness: float
    trend_acceleration: float
    volume_expansion_quality: float
    close_strength: float
    sector_resonance: float
    raw_catalyst_freshness: float
    layer_c_alignment: float
    long_trend_strength: float
    mean_reversion_strength: float
    momentum_strength: float
    short_term_reversal: float
    intraday_strength: float
    reversal_2d: float
    trend_continuation: float
    trend_continuation_2d: float
    momentum_1m: float
    momentum_3m: float
    momentum_6m: float
    volume_momentum: float
    ema_strength: float
    volatility_strength: float
    volatility_metrics: dict[str, Any]
    score_final_strength: float
    analyst_penalty: float
    investor_penalty: float
    historical_prior: dict[str, Any]


@dataclass(frozen=True)
class PreparedBreakoutReliefs:
    continuation_relief: dict[str, Any]
    penalty_relief: dict[str, Any]
    catalyst_relief: dict[str, Any]
    volume_relief: dict[str, Any]


@dataclass(frozen=True)
class SnapshotThresholdState:
    profitability_relief: dict[str, Any]
    catalyst_relief: dict[str, Any]
    visibility_gap_continuation_relief: dict[str, Any]
    merge_approved_continuation_relief: dict[str, Any]
    historical_execution_relief: dict[str, Any]
    prepared_breakout_selected_catalyst_relief: dict[str, Any]
    breakout_freshness: float
    trend_acceleration: float
    volume_expansion_quality: float
    catalyst_freshness: float
    effective_near_miss_threshold: float
    effective_select_threshold: float
    layer_c_avoid_penalty: float
    market_state_threshold_adjustment: dict[str, Any]
    selected_close_retention_adjustment: dict[str, Any]
    event_catalyst_assessment: dict[str, Any]


@dataclass(frozen=True)
class WatchlistPenaltyState:
    catalyst_theme_penalty: dict[str, Any]
    watchlist_zero_catalyst_penalty: dict[str, Any]
    watchlist_zero_catalyst_crowded_penalty: dict[str, Any]
    watchlist_zero_catalyst_flat_trend_penalty: dict[str, Any]
    watchlist_filter_diagnostics_flat_trend_penalty: dict[str, Any]
    watchlist_filter_diagnostics_selected_only_shrink_guard: dict[str, Any]
    layer_c_watchlist_selected_only_shrink_guard: dict[str, Any]
    short_trade_boundary_selected_only_shrink_guard: dict[str, Any]
    t_plus_2_continuation_candidate: dict[str, Any]
    effective_catalyst_theme_penalty: float
    effective_watchlist_zero_catalyst_penalty: float
    effective_watchlist_zero_catalyst_crowded_penalty: float
    effective_watchlist_zero_catalyst_flat_trend_penalty: float
    effective_watchlist_filter_diagnostics_flat_trend_penalty: float
    effective_watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift: float
    effective_layer_c_watchlist_selected_only_shrink_select_threshold_lift: float
    effective_short_trade_boundary_selected_only_shrink_select_threshold_lift: float


@dataclass(frozen=True)
class ScorePenaltyState:
    profitability_hard_cliff_boundary_relief: dict[str, Any]
    stale_trend_repair_penalty: float
    overhead_supply_penalty: float
    extension_without_room_penalty: float
    breakout_trap_guard: dict[str, Any]
    breakout_trap_risk: float
    breakout_trap_penalty: float
    effective_near_miss_threshold: float
    effective_stale_score_penalty_weight: float
    effective_extension_score_penalty_weight: float


@dataclass(frozen=True)
class SnapshotReliefResolution:
    state: SnapshotSignalState
    prepared_breakout_reliefs: PreparedBreakoutReliefs
    threshold_state: SnapshotThresholdState
    watchlist_penalty_state: WatchlistPenaltyState
    score_penalty_state: ScorePenaltyState
    positive_score_weights: dict[str, float]
    score_payload: dict[str, Any]
    selected_score_tolerance: float


@dataclass(frozen=True)
class SnapshotCoreReliefs:
    profitability_relief: dict[str, Any]
    catalyst_relief: dict[str, Any]
    visibility_gap_continuation_relief: dict[str, Any]
    merge_approved_continuation_relief: dict[str, Any]
    historical_execution_relief: dict[str, Any]


@dataclass(frozen=True)
class SnapshotResolutionCoreState:
    profile: Any
    state: SnapshotSignalState
    market_state: dict[str, Any]
    prepared_breakout_reliefs: PreparedBreakoutReliefs
    threshold_state: SnapshotThresholdState
    watchlist_penalty_state: WatchlistPenaltyState
    score_penalty_state: ScorePenaltyState
    positive_score_weights: dict[str, float]
    score_payload: dict[str, Any]
