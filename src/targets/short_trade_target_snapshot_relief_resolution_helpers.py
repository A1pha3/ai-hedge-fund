"""Relief resolution orchestration for short trade target snapshots.

Extracted from ``short_trade_target_snapshot_relief_helpers`` during the
R20.15 refactor.  This module glues the *criterion-level* resolvers
(living in :mod:`src.targets.short_trade_target_snapshot_relief_criteria_helpers`)
into a final :class:`SnapshotReliefResolution` payload.

Cohesive groups included here:

1. Frozen dataclasses shared across the snapshot pipeline
   (``SnapshotSignalState``, ``PreparedBreakoutReliefs``,
   ``SnapshotThresholdState``, ``WatchlistPenaltyState``,
   ``ScorePenaltyState``, ``SnapshotReliefResolution``,
   ``SnapshotCoreReliefs``, ``SnapshotResolutionCoreState``)
2. Snapshot signal state builder
3. Prepared breakout relief orchestrator
4. Snapshot core reliefs orchestrator
5. Ticker historical-prior threshold boost
6. Threshold state finalizers
7. Watchlist penalty state builder
8. Score penalty state builder
9. Snapshot score payload builder
10. Resolution orchestration + payload serialization
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.targets.short_trade_target_factor_helpers import (
    compute_trend_continuation_strength_adjustment,
)
from src.targets.short_trade_target_prior_helpers import (
    score_short_trade_historical_continuation_prior,
)
from src.targets.short_trade_target_snapshot_relief_criteria_helpers import (
    _apply_event_catalyst_threshold_adjustments,
    _build_market_state_threshold_adjustment,
    _build_selected_close_retention_adjustment,
    _resolve_breakout_trap_guard,
    _resolve_market_state_threshold_adjustment,
    _resolve_selected_close_retention_adjustment,
    _resolve_selected_close_retention_penalty,
)
from src.targets.short_trade_target_snapshot_relief_models import (
    PreparedBreakoutReliefs,
    ScorePenaltyState,
    SnapshotCoreReliefs,
    SnapshotReliefResolution,
    SnapshotResolutionCoreState,
    SnapshotSignalState,
    SnapshotThresholdState,
    WatchlistPenaltyState,
)
from src.targets.short_trade_target_watchlist_helpers import (
    resolve_layer_c_watchlist_selected_only_shrink_impl,
    resolve_short_trade_boundary_selected_only_shrink_impl,
    resolve_watchlist_filter_diagnostics_selected_only_shrink_impl,
)


def _build_snapshot_signal_state(
    signal_snapshot: dict[str, Any],
    *,
    historical_prior: dict[str, Any],
) -> SnapshotSignalState:
    return SnapshotSignalState(
        fundamental_signal=signal_snapshot["fundamental_signal"],
        breakout_stage=str(signal_snapshot["breakout_stage"]),
        breakout_freshness=float(signal_snapshot["breakout_freshness"]),
        trend_acceleration=float(signal_snapshot["trend_acceleration"]),
        volume_expansion_quality=float(signal_snapshot["volume_expansion_quality"]),
        close_strength=float(signal_snapshot["close_strength"]),
        sector_resonance=float(signal_snapshot["sector_resonance"]),
        raw_catalyst_freshness=float(signal_snapshot["raw_catalyst_freshness"]),
        layer_c_alignment=float(signal_snapshot["layer_c_alignment"]),
        long_trend_strength=float(signal_snapshot["long_trend_strength"]),
        mean_reversion_strength=float(signal_snapshot["mean_reversion_strength"]),
        momentum_strength=float(signal_snapshot.get("momentum_strength", 0.0)),
        short_term_reversal=float(signal_snapshot.get("short_term_reversal", 0.0)),
        intraday_strength=float(signal_snapshot.get("intraday_strength", 0.0)),
        reversal_2d=float(signal_snapshot.get("reversal_2d", 0.0)),
        trend_continuation=float(signal_snapshot.get("trend_continuation", 0.0)),
        trend_continuation_2d=float(signal_snapshot.get("trend_continuation_2d", 0.0)),
        momentum_1m=float(signal_snapshot["momentum_1m"]),
        momentum_3m=float(signal_snapshot["momentum_3m"]),
        momentum_6m=float(signal_snapshot["momentum_6m"]),
        volume_momentum=float(signal_snapshot["volume_momentum"]),
        ema_strength=float(signal_snapshot["ema_strength"]),
        volatility_strength=float(signal_snapshot["volatility_strength"]),
        volatility_metrics=dict(signal_snapshot["volatility_metrics"]),
        score_final_strength=float(signal_snapshot["score_final_strength"]),
        analyst_penalty=float(signal_snapshot["analyst_penalty"]),
        investor_penalty=float(signal_snapshot["investor_penalty"]),
        historical_prior=historical_prior,
    )


def _build_prepared_breakout_relief_base_kwargs(
    *,
    input_data: Any,
    profile: Any,
    state: SnapshotSignalState,
) -> dict[str, Any]:
    return {
        "input_data": input_data,
        "breakout_stage": state.breakout_stage,
        "breakout_freshness": state.breakout_freshness,
        "trend_acceleration": state.trend_acceleration,
        "close_strength": state.close_strength,
        "sector_resonance": state.sector_resonance,
        "layer_c_alignment": state.layer_c_alignment,
        "catalyst_freshness": state.raw_catalyst_freshness,
        "long_trend_strength": state.long_trend_strength,
        "mean_reversion_strength": state.mean_reversion_strength,
        "profile": profile,
    }


def _resolve_prepared_breakout_reliefs(
    input_data: Any,
    *,
    profile: Any,
    state: SnapshotSignalState,
    resolve_prepared_breakout_continuation_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_penalty_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_volume_relief: Callable[..., dict[str, Any]],
) -> PreparedBreakoutReliefs:
    base_kwargs = _build_prepared_breakout_relief_base_kwargs(
        input_data=input_data,
        profile=profile,
        state=state,
    )
    continuation_relief = resolve_prepared_breakout_continuation_relief(
        **base_kwargs,
        momentum_1m=state.momentum_1m,
        momentum_3m=state.momentum_3m,
        momentum_6m=state.momentum_6m,
        volume_momentum=state.volume_momentum,
        ema_strength=state.ema_strength,
    )
    penalty_relief = resolve_prepared_breakout_penalty_relief(
        **base_kwargs,
    )
    catalyst_relief = resolve_prepared_breakout_catalyst_relief(
        **base_kwargs,
    )
    volume_relief = resolve_prepared_breakout_volume_relief(
        **base_kwargs,
        volatility_strength=state.volatility_strength,
        volume_expansion_quality=state.volume_expansion_quality,
        volatility_regime=float(state.volatility_metrics.get("volatility_regime", 0.0) or 0.0),
        atr_ratio=float(state.volatility_metrics.get("atr_ratio", 0.0) or 0.0),
    )
    return PreparedBreakoutReliefs(
        continuation_relief=continuation_relief,
        penalty_relief=penalty_relief,
        catalyst_relief=catalyst_relief,
        volume_relief=volume_relief,
    )


def _resolve_snapshot_core_reliefs(
    input_data: Any,
    *,
    profile: Any,
    state: SnapshotSignalState,
    resolve_profitability_relief: Callable[..., dict[str, Any]],
    resolve_upstream_shadow_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_visibility_gap_continuation_relief: Callable[..., dict[str, Any]],
    resolve_merge_approved_continuation_relief: Callable[..., dict[str, Any]],
    resolve_historical_execution_relief: Callable[..., dict[str, Any]],
) -> SnapshotCoreReliefs:
    profitability_relief = resolve_profitability_relief(
        input_data=input_data,
        fundamental_signal=state.fundamental_signal,
        breakout_freshness=state.breakout_freshness,
        catalyst_freshness=state.raw_catalyst_freshness,
        sector_resonance=state.sector_resonance,
        profile=profile,
    )
    profitability_hard_cliff = bool(profitability_relief["hard_cliff"])
    return SnapshotCoreReliefs(
        profitability_relief=profitability_relief,
        catalyst_relief=resolve_upstream_shadow_catalyst_relief(
            input_data=input_data,
            breakout_freshness=state.breakout_freshness,
            trend_acceleration=state.trend_acceleration,
            close_strength=state.close_strength,
            catalyst_freshness=state.raw_catalyst_freshness,
            profitability_hard_cliff=profitability_hard_cliff,
            profile=profile,
        ),
        visibility_gap_continuation_relief=resolve_visibility_gap_continuation_relief(
            input_data=input_data,
            breakout_freshness=state.breakout_freshness,
            trend_acceleration=state.trend_acceleration,
            close_strength=state.close_strength,
            catalyst_freshness=state.raw_catalyst_freshness,
            profitability_hard_cliff=profitability_hard_cliff,
            profile=profile,
        ),
        merge_approved_continuation_relief=resolve_merge_approved_continuation_relief(
            input_data=input_data,
            breakout_freshness=state.breakout_freshness,
            trend_acceleration=state.trend_acceleration,
            close_strength=state.close_strength,
            profitability_hard_cliff=profitability_hard_cliff,
            profile=profile,
        ),
        historical_execution_relief=resolve_historical_execution_relief(
            input_data=input_data,
            profitability_hard_cliff=profitability_hard_cliff,
            profile=profile,
        ),
    )


def _apply_ticker_historical_prior_boost(
    *,
    effective_select_threshold: float,
    effective_near_miss_threshold: float,
    historical_execution_relief: dict[str, Any],
) -> tuple[float, float]:
    evaluable_count = int(historical_execution_relief.get("evaluable_count") or 0)
    next_high_hit_rate = float(historical_execution_relief.get("next_high_hit_rate_at_threshold") or 0.0)
    next_close_positive_rate = float(historical_execution_relief.get("next_close_positive_rate") or 0.0)
    if evaluable_count <= 0:
        return effective_select_threshold, effective_near_miss_threshold
    if evaluable_count > 0 and next_high_hit_rate == 0.0 and next_close_positive_rate == 0.0:
        effective_select_threshold = min(0.95, effective_select_threshold + 0.05)
        effective_near_miss_threshold = min(0.95, effective_near_miss_threshold + 0.03)
        return effective_select_threshold, effective_near_miss_threshold
    if evaluable_count >= 20 and next_close_positive_rate < 0.35:
        effective_select_threshold = min(0.95, effective_select_threshold + 0.06)
        effective_near_miss_threshold = min(effective_select_threshold, effective_near_miss_threshold + 0.03)
        return effective_select_threshold, effective_near_miss_threshold
    if evaluable_count >= 10 and next_close_positive_rate < 0.45:
        effective_select_threshold = min(0.95, effective_select_threshold + 0.03)
        effective_near_miss_threshold = min(effective_select_threshold, effective_near_miss_threshold + 0.015)
        return effective_select_threshold, effective_near_miss_threshold
    if evaluable_count >= 10 and next_high_hit_rate >= 0.80 and next_close_positive_rate >= 0.60:
        select_boost = 0.06
    elif evaluable_count >= 5 and next_high_hit_rate >= 0.70 and next_close_positive_rate >= 0.50:
        select_boost = 0.03
    else:
        select_boost = 0.0
    if select_boost > 0:
        effective_select_threshold = max(0.20, effective_select_threshold - select_boost)
        effective_near_miss_threshold = max(0.20, effective_near_miss_threshold - select_boost)
    return effective_select_threshold, effective_near_miss_threshold


def _finalize_snapshot_threshold_state(
    *,
    input_data: Any,
    profile: Any,
    state: SnapshotSignalState,
    prepared_breakout_reliefs: PreparedBreakoutReliefs,
    core_reliefs: SnapshotCoreReliefs,
    prepared_breakout_selected_catalyst_relief: dict[str, Any],
) -> SnapshotThresholdState:
    breakout_freshness = max(
        state.breakout_freshness,
        float(prepared_breakout_reliefs.continuation_relief["effective_breakout_freshness"]),
        float(prepared_breakout_selected_catalyst_relief["effective_breakout_freshness"]),
    )
    trend_acceleration = max(
        state.trend_acceleration,
        float(prepared_breakout_reliefs.continuation_relief["effective_trend_acceleration"]),
    )
    volume_expansion_quality = max(
        state.volume_expansion_quality,
        float(prepared_breakout_reliefs.volume_relief["effective_volume_expansion_quality"]),
    )
    catalyst_freshness = max(
        float(core_reliefs.catalyst_relief["effective_catalyst_freshness"]),
        float(core_reliefs.visibility_gap_continuation_relief["effective_catalyst_freshness"]),
        float(prepared_breakout_reliefs.catalyst_relief["effective_catalyst_freshness"]),
        float(prepared_breakout_selected_catalyst_relief["effective_catalyst_freshness"]),
    )
    effective_near_miss_threshold = min(
        float(core_reliefs.catalyst_relief["effective_near_miss_threshold"]),
        float(core_reliefs.visibility_gap_continuation_relief["effective_near_miss_threshold"]),
        float(core_reliefs.merge_approved_continuation_relief["effective_near_miss_threshold"]),
        float(core_reliefs.historical_execution_relief["effective_near_miss_threshold"]),
    )
    effective_select_threshold = min(
        float(core_reliefs.catalyst_relief["effective_select_threshold"]),
        float(core_reliefs.merge_approved_continuation_relief["effective_select_threshold"]),
        float(core_reliefs.historical_execution_relief["effective_select_threshold"]),
    )
    effective_select_threshold, effective_near_miss_threshold = _apply_ticker_historical_prior_boost(
        effective_select_threshold=effective_select_threshold,
        effective_near_miss_threshold=effective_near_miss_threshold,
        historical_execution_relief=core_reliefs.historical_execution_relief,
    )

    # Event catalyst assessment is now deferred until after penalties are computed
    # Placeholder returned here; real assessment applied in _apply_event_catalyst_threshold_adjustments
    event_catalyst_assessment = {
        "score": 0.0,
        "eligible": False,
        "selected_uplift": 0.0,
        "near_miss_threshold_relief": 0.0,
        "gate_hits": {},
        "component_scores": {},
        "candidate_reason_codes": [],
    }

    return SnapshotThresholdState(
        profitability_relief=core_reliefs.profitability_relief,
        catalyst_relief=core_reliefs.catalyst_relief,
        visibility_gap_continuation_relief=core_reliefs.visibility_gap_continuation_relief,
        merge_approved_continuation_relief=core_reliefs.merge_approved_continuation_relief,
        historical_execution_relief=core_reliefs.historical_execution_relief,
        prepared_breakout_selected_catalyst_relief=prepared_breakout_selected_catalyst_relief,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        volume_expansion_quality=volume_expansion_quality,
        catalyst_freshness=catalyst_freshness,
        effective_near_miss_threshold=effective_near_miss_threshold,
        effective_select_threshold=effective_select_threshold,
        layer_c_avoid_penalty=float(core_reliefs.profitability_relief["effective_avoid_penalty"]),
        market_state_threshold_adjustment=_build_market_state_threshold_adjustment(
            enabled=False,
            risk_level="unknown",
            breadth_ratio=None,
            position_scale=None,
            regime_gate_level="unknown",
            regime_gate_reasons=[],
            style_dispersion=0.0,
            regime_flip_risk=0.0,
            execution_hard_gate=False,
            select_threshold_lift=0.0,
            near_miss_threshold_lift=0.0,
            effective_select_threshold=effective_select_threshold,
            effective_near_miss_threshold=effective_near_miss_threshold,
        ),
        selected_close_retention_adjustment=_build_selected_close_retention_adjustment(
            enabled=False,
            close_retention_score=0.0,
            breakout_close_gap=0.0,
            close_retention_floor=0.0,
            breakout_close_gap_max=1.0,
            select_threshold_lift=0.0,
            effective_select_threshold=effective_select_threshold,
            effective_near_miss_threshold=effective_near_miss_threshold,
        ),
        event_catalyst_assessment=event_catalyst_assessment,
    )


def _resolve_snapshot_threshold_state(
    input_data: Any,
    *,
    profile: Any,
    state: SnapshotSignalState,
    prepared_breakout_reliefs: PreparedBreakoutReliefs,
    resolve_profitability_relief: Callable[..., dict[str, Any]],
    resolve_upstream_shadow_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_visibility_gap_continuation_relief: Callable[..., dict[str, Any]],
    resolve_merge_approved_continuation_relief: Callable[..., dict[str, Any]],
    resolve_historical_execution_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_selected_catalyst_relief: Callable[..., dict[str, Any]],
) -> SnapshotThresholdState:
    core_reliefs = _resolve_snapshot_core_reliefs(
        input_data,
        profile=profile,
        state=state,
        resolve_profitability_relief=resolve_profitability_relief,
        resolve_upstream_shadow_catalyst_relief=resolve_upstream_shadow_catalyst_relief,
        resolve_visibility_gap_continuation_relief=resolve_visibility_gap_continuation_relief,
        resolve_merge_approved_continuation_relief=resolve_merge_approved_continuation_relief,
        resolve_historical_execution_relief=resolve_historical_execution_relief,
    )
    breakout_freshness = max(
        state.breakout_freshness,
        float(prepared_breakout_reliefs.continuation_relief["effective_breakout_freshness"]),
    )
    trend_acceleration = max(
        state.trend_acceleration,
        float(prepared_breakout_reliefs.continuation_relief["effective_trend_acceleration"]),
    )
    volume_expansion_quality = max(
        state.volume_expansion_quality,
        float(prepared_breakout_reliefs.volume_relief["effective_volume_expansion_quality"]),
    )
    catalyst_freshness = max(
        float(core_reliefs.catalyst_relief["effective_catalyst_freshness"]),
        float(core_reliefs.visibility_gap_continuation_relief["effective_catalyst_freshness"]),
        float(prepared_breakout_reliefs.catalyst_relief["effective_catalyst_freshness"]),
    )
    prepared_breakout_selected_catalyst_relief = resolve_prepared_breakout_selected_catalyst_relief(
        input_data=input_data,
        breakout_stage=state.breakout_stage,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=state.close_strength,
        sector_resonance=state.sector_resonance,
        layer_c_alignment=state.layer_c_alignment,
        volume_expansion_quality=volume_expansion_quality,
        catalyst_freshness=catalyst_freshness,
        long_trend_strength=state.long_trend_strength,
        mean_reversion_strength=state.mean_reversion_strength,
        prepared_breakout_penalty_relief=prepared_breakout_reliefs.penalty_relief,
        prepared_breakout_catalyst_relief=prepared_breakout_reliefs.catalyst_relief,
        prepared_breakout_volume_relief=prepared_breakout_reliefs.volume_relief,
        prepared_breakout_continuation_relief=prepared_breakout_reliefs.continuation_relief,
        profile=profile,
    )
    return _finalize_snapshot_threshold_state(
        input_data=input_data,
        profile=profile,
        state=state,
        prepared_breakout_reliefs=prepared_breakout_reliefs,
        core_reliefs=core_reliefs,
        prepared_breakout_selected_catalyst_relief=prepared_breakout_selected_catalyst_relief,
    )


def _resolve_watchlist_penalty_state(
    input_data: Any,
    *,
    profile: Any,
    state: SnapshotSignalState,
    threshold_state: SnapshotThresholdState,
    resolve_catalyst_theme_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_crowded_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_flat_trend_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_filter_diagnostics_flat_trend_penalty: Callable[..., dict[str, Any]],
    resolve_t_plus_2_continuation_candidate: Callable[..., dict[str, Any]],
) -> WatchlistPenaltyState:
    catalyst_theme_penalty = resolve_catalyst_theme_penalty(
        input_data=input_data,
        profile=profile,
    )
    watchlist_zero_catalyst_penalty = resolve_watchlist_zero_catalyst_penalty(
        input_data=input_data,
        catalyst_freshness=state.raw_catalyst_freshness,
        close_strength=state.close_strength,
        sector_resonance=state.sector_resonance,
        layer_c_alignment=state.layer_c_alignment,
        profile=profile,
    )
    watchlist_zero_catalyst_crowded_penalty = resolve_watchlist_zero_catalyst_crowded_penalty(
        input_data=input_data,
        catalyst_freshness=state.raw_catalyst_freshness,
        close_strength=state.close_strength,
        sector_resonance=state.sector_resonance,
        layer_c_alignment=state.layer_c_alignment,
        profile=profile,
    )
    watchlist_zero_catalyst_flat_trend_penalty = resolve_watchlist_zero_catalyst_flat_trend_penalty(
        input_data=input_data,
        catalyst_freshness=state.raw_catalyst_freshness,
        close_strength=state.close_strength,
        sector_resonance=state.sector_resonance,
        layer_c_alignment=state.layer_c_alignment,
        trend_acceleration=threshold_state.trend_acceleration,
        profile=profile,
    )
    watchlist_filter_diagnostics_flat_trend_penalty = resolve_watchlist_filter_diagnostics_flat_trend_penalty(
        input_data=input_data,
        catalyst_freshness=state.raw_catalyst_freshness,
        close_strength=state.close_strength,
        trend_acceleration=threshold_state.trend_acceleration,
        profile=profile,
    )
    watchlist_filter_diagnostics_selected_only_shrink_guard = resolve_watchlist_filter_diagnostics_selected_only_shrink_impl(
        input_data=input_data,
        catalyst_freshness=state.raw_catalyst_freshness,
        close_strength=state.close_strength,
        trend_acceleration=threshold_state.trend_acceleration,
        profile=profile,
        clamp_unit_interval_fn=lambda value: max(0.0, min(1.0, float(value))),
    )
    layer_c_watchlist_selected_only_shrink_guard = resolve_layer_c_watchlist_selected_only_shrink_impl(
        source=str(input_data.replay_context.get("source") or "").strip(),
        catalyst_freshness=state.raw_catalyst_freshness,
        close_strength=state.close_strength,
        trend_acceleration=threshold_state.trend_acceleration,
        profile=profile,
        clamp_unit_interval_fn=lambda value: max(0.0, min(1.0, float(value))),
    )
    short_trade_boundary_selected_only_shrink_guard = resolve_short_trade_boundary_selected_only_shrink_impl(
        profile=profile,
        source=str(input_data.replay_context.get("source") or "").strip(),
        catalyst_freshness=state.raw_catalyst_freshness,
        close_strength=state.close_strength,
        trend_acceleration=threshold_state.trend_acceleration,
        clamp_unit_interval_fn=lambda value: max(0.0, min(1.0, float(value))),
    )
    t_plus_2_continuation_candidate = resolve_t_plus_2_continuation_candidate(
        input_data=input_data,
        raw_catalyst_freshness=state.raw_catalyst_freshness,
        breakout_freshness=threshold_state.breakout_freshness,
        trend_acceleration=threshold_state.trend_acceleration,
        close_strength=state.close_strength,
        sector_resonance=state.sector_resonance,
        layer_c_alignment=state.layer_c_alignment,
        profile=profile,
    )
    return WatchlistPenaltyState(
        catalyst_theme_penalty=catalyst_theme_penalty,
        watchlist_zero_catalyst_penalty=watchlist_zero_catalyst_penalty,
        watchlist_zero_catalyst_crowded_penalty=watchlist_zero_catalyst_crowded_penalty,
        watchlist_zero_catalyst_flat_trend_penalty=watchlist_zero_catalyst_flat_trend_penalty,
        watchlist_filter_diagnostics_flat_trend_penalty=watchlist_filter_diagnostics_flat_trend_penalty,
        watchlist_filter_diagnostics_selected_only_shrink_guard=watchlist_filter_diagnostics_selected_only_shrink_guard,
        layer_c_watchlist_selected_only_shrink_guard=layer_c_watchlist_selected_only_shrink_guard,
        short_trade_boundary_selected_only_shrink_guard=short_trade_boundary_selected_only_shrink_guard,
        t_plus_2_continuation_candidate=t_plus_2_continuation_candidate,
        effective_catalyst_theme_penalty=float(catalyst_theme_penalty["effective_penalty"]),
        effective_watchlist_zero_catalyst_penalty=float(watchlist_zero_catalyst_penalty["effective_penalty"]),
        effective_watchlist_zero_catalyst_crowded_penalty=float(watchlist_zero_catalyst_crowded_penalty["effective_penalty"]),
        effective_watchlist_zero_catalyst_flat_trend_penalty=float(watchlist_zero_catalyst_flat_trend_penalty["effective_penalty"]),
        effective_watchlist_filter_diagnostics_flat_trend_penalty=float(watchlist_filter_diagnostics_flat_trend_penalty["effective_penalty"]),
        effective_watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift=float(watchlist_filter_diagnostics_selected_only_shrink_guard["select_threshold_lift"]),
        effective_layer_c_watchlist_selected_only_shrink_select_threshold_lift=float(layer_c_watchlist_selected_only_shrink_guard["select_threshold_lift"]),
        effective_short_trade_boundary_selected_only_shrink_select_threshold_lift=float(short_trade_boundary_selected_only_shrink_guard["select_threshold_lift"]),
    )


def _resolve_score_penalty_state(
    input_data: Any,
    *,
    profile: Any,
    state: SnapshotSignalState,
    threshold_state: SnapshotThresholdState,
    prepared_breakout_reliefs: PreparedBreakoutReliefs,
    clamp_unit_interval,
    resolve_profitability_hard_cliff_boundary_relief: Callable[..., dict[str, Any]],
) -> ScorePenaltyState:
    stale_trend_repair_penalty = clamp_unit_interval((0.45 * state.mean_reversion_strength) + (0.35 * state.long_trend_strength) + (0.20 * max(0.0, state.long_trend_strength - threshold_state.breakout_freshness)))
    overhead_supply_penalty = clamp_unit_interval((0.45 if input_data.bc_conflict in profile.overhead_conflict_penalty_conflicts else 0.0) + (0.35 * state.analyst_penalty) + (0.20 * state.investor_penalty))
    extension_without_room_penalty = clamp_unit_interval((0.45 * state.long_trend_strength) + (0.35 * max(0.0, state.volatility_strength - threshold_state.catalyst_freshness)) + (0.20 * clamp_unit_interval((state.score_final_strength - 0.72) / 0.28)))
    breakout_trap_guard = _resolve_breakout_trap_guard(
        input_data,
        state=state,
        threshold_state=threshold_state,
        clamp_unit_interval=clamp_unit_interval,
    )
    profitability_hard_cliff_boundary_relief = resolve_profitability_hard_cliff_boundary_relief(
        input_data=input_data,
        profitability_hard_cliff=bool(threshold_state.profitability_relief["hard_cliff"]),
        breakout_freshness=threshold_state.breakout_freshness,
        trend_acceleration=threshold_state.trend_acceleration,
        catalyst_freshness=state.raw_catalyst_freshness,
        sector_resonance=state.sector_resonance,
        close_strength=state.close_strength,
        stale_trend_repair_penalty=stale_trend_repair_penalty,
        extension_without_room_penalty=extension_without_room_penalty,
        profile=profile,
    )
    return ScorePenaltyState(
        profitability_hard_cliff_boundary_relief=profitability_hard_cliff_boundary_relief,
        stale_trend_repair_penalty=stale_trend_repair_penalty,
        overhead_supply_penalty=overhead_supply_penalty,
        extension_without_room_penalty=extension_without_room_penalty,
        breakout_trap_guard=breakout_trap_guard,
        breakout_trap_risk=float(breakout_trap_guard["risk"]),
        breakout_trap_penalty=float(breakout_trap_guard["penalty"]),
        effective_near_miss_threshold=min(
            threshold_state.effective_near_miss_threshold,
            float(profitability_hard_cliff_boundary_relief["effective_near_miss_threshold"]),
        ),
        effective_stale_score_penalty_weight=float(prepared_breakout_reliefs.penalty_relief["effective_stale_score_penalty_weight"]),
        effective_extension_score_penalty_weight=float(prepared_breakout_reliefs.penalty_relief["effective_extension_score_penalty_weight"]),
    )


def _build_snapshot_score_payload(
    *,
    profile: Any,
    state: SnapshotSignalState,
    threshold_state: SnapshotThresholdState,
    watchlist_penalty_state: WatchlistPenaltyState,
    score_penalty_state: ScorePenaltyState,
    positive_score_weights: dict[str, float],
    clamp_unit_interval,
) -> dict[str, Any]:
    historical_continuation_prior_score = score_short_trade_historical_continuation_prior(state.historical_prior)
    trend_continuation_strength_adjustment = compute_trend_continuation_strength_adjustment(
        trend_continuation=state.trend_continuation,
        close_strength=state.close_strength,
        volume_expansion_quality=threshold_state.volume_expansion_quality,
        continuation_weight=float(getattr(profile, "trend_continuation_strength_weight", 0.0) or 0.0),
        close_support_floor=float(getattr(profile, "trend_continuation_strength_close_support_floor", 0.0) or 0.0),
        volume_support_floor=float(getattr(profile, "trend_continuation_strength_volume_support_floor", 0.0) or 0.0),
        weak_close_penalty=float(getattr(profile, "trend_continuation_strength_weak_close_penalty", 0.0) or 0.0),
    )
    trend_continuation_strength_positive_contribution = round(max(trend_continuation_strength_adjustment, 0.0), 4)
    trend_continuation_strength_negative_contribution = round(abs(min(trend_continuation_strength_adjustment, 0.0)), 4)
    weighted_positive_contributions = {
        "breakout_freshness": round(positive_score_weights["breakout_freshness"] * threshold_state.breakout_freshness, 4),
        "trend_acceleration": round(positive_score_weights["trend_acceleration"] * threshold_state.trend_acceleration, 4),
        "volume_expansion_quality": round(positive_score_weights["volume_expansion_quality"] * threshold_state.volume_expansion_quality, 4),
        "close_strength": round(positive_score_weights["close_strength"] * state.close_strength, 4),
        "sector_resonance": round(positive_score_weights["sector_resonance"] * state.sector_resonance, 4),
        "catalyst_freshness": round(positive_score_weights["catalyst_freshness"] * threshold_state.catalyst_freshness, 4),
        "layer_c_alignment": round(positive_score_weights["layer_c_alignment"] * state.layer_c_alignment, 4),
        "historical_continuation_score": round(
            positive_score_weights.get("historical_continuation_score", 0.0) * float(historical_continuation_prior_score["score"]),
            4,
        ),
        "momentum_strength": round(positive_score_weights.get("momentum_strength", 0.0) * state.momentum_strength, 4),
        "short_term_reversal": round(positive_score_weights.get("short_term_reversal", 0.0) * state.short_term_reversal, 4),
        "intraday_strength": round(positive_score_weights.get("intraday_strength", 0.0) * state.intraday_strength, 4),
        "reversal_2d": round(positive_score_weights.get("reversal_2d", 0.0) * state.reversal_2d, 4),
        "trend_continuation": round(positive_score_weights.get("trend_continuation", 0.0) * state.trend_continuation, 4),
        "trend_continuation_2d": round(positive_score_weights.get("trend_continuation_2d", 0.0) * state.trend_continuation_2d, 4),
        "trend_continuation_strength": trend_continuation_strength_positive_contribution,
    }
    weighted_negative_contributions = {
        "stale_trend_repair_penalty": round(score_penalty_state.effective_stale_score_penalty_weight * score_penalty_state.stale_trend_repair_penalty, 4),
        "overhead_supply_penalty": round(profile.overhead_score_penalty_weight * score_penalty_state.overhead_supply_penalty, 4),
        "extension_without_room_penalty": round(score_penalty_state.effective_extension_score_penalty_weight * score_penalty_state.extension_without_room_penalty, 4),
        "breakout_trap_penalty": round(score_penalty_state.breakout_trap_penalty, 4),
        "layer_c_avoid_penalty": round(threshold_state.layer_c_avoid_penalty, 4),
        "catalyst_theme_penalty": round(watchlist_penalty_state.effective_catalyst_theme_penalty, 4),
        "watchlist_zero_catalyst_penalty": round(watchlist_penalty_state.effective_watchlist_zero_catalyst_penalty, 4),
        "watchlist_zero_catalyst_crowded_penalty": round(watchlist_penalty_state.effective_watchlist_zero_catalyst_crowded_penalty, 4),
        "watchlist_zero_catalyst_flat_trend_penalty": round(watchlist_penalty_state.effective_watchlist_zero_catalyst_flat_trend_penalty, 4),
        "watchlist_filter_diagnostics_flat_trend_penalty": round(watchlist_penalty_state.effective_watchlist_filter_diagnostics_flat_trend_penalty, 4),
    }
    if trend_continuation_strength_negative_contribution > 0.0:
        weighted_negative_contributions["trend_continuation_strength_penalty"] = trend_continuation_strength_negative_contribution
    total_positive_contribution = round(sum(weighted_positive_contributions.values()), 4)
    total_negative_contribution = round(sum(weighted_negative_contributions.values()), 4)
    # Overbought momentum penalty: penalize extreme momentum (overbought) stocks
    # Research shows high trend_acceleration/breakout_freshness identify LOSERS (t=-13.4/-15.9)
    overbought_threshold = float(getattr(profile, "overbought_momentum_threshold", 1.0))
    overbought_weight = float(getattr(profile, "overbought_momentum_penalty_weight", 0.0))
    overbought_momentum_penalty = 0.0
    if overbought_weight > 0 and overbought_threshold < 1.0:
        # Penalty proportional to how far above threshold
        excess_trend = max(0.0, state.trend_acceleration - overbought_threshold)
        excess_breakout = max(0.0, threshold_state.breakout_freshness - overbought_threshold)
        overbought_momentum_penalty = overbought_weight * max(excess_trend, excess_breakout)
    score_target = clamp_unit_interval(
        (positive_score_weights["breakout_freshness"] * threshold_state.breakout_freshness)
        + (positive_score_weights["trend_acceleration"] * threshold_state.trend_acceleration)
        + (positive_score_weights["volume_expansion_quality"] * threshold_state.volume_expansion_quality)
        + (positive_score_weights["close_strength"] * state.close_strength)
        + (positive_score_weights["sector_resonance"] * state.sector_resonance)
        + (positive_score_weights["catalyst_freshness"] * threshold_state.catalyst_freshness)
        + (positive_score_weights["layer_c_alignment"] * state.layer_c_alignment)
        + (positive_score_weights.get("historical_continuation_score", 0.0) * float(historical_continuation_prior_score["score"]))
        + (positive_score_weights.get("momentum_strength", 0.0) * state.momentum_strength)
        + (positive_score_weights.get("short_term_reversal", 0.0) * state.short_term_reversal)
        + (positive_score_weights.get("intraday_strength", 0.0) * state.intraday_strength)
        + (positive_score_weights.get("reversal_2d", 0.0) * state.reversal_2d)
        + (positive_score_weights.get("trend_continuation", 0.0) * state.trend_continuation)
        + (positive_score_weights.get("trend_continuation_2d", 0.0) * state.trend_continuation_2d)
        + trend_continuation_strength_adjustment
        - (score_penalty_state.effective_stale_score_penalty_weight * score_penalty_state.stale_trend_repair_penalty)
        - (profile.overhead_score_penalty_weight * score_penalty_state.overhead_supply_penalty)
        - (score_penalty_state.effective_extension_score_penalty_weight * score_penalty_state.extension_without_room_penalty)
        - score_penalty_state.breakout_trap_penalty
        - threshold_state.layer_c_avoid_penalty
        - watchlist_penalty_state.effective_catalyst_theme_penalty
        - watchlist_penalty_state.effective_watchlist_zero_catalyst_penalty
        - watchlist_penalty_state.effective_watchlist_zero_catalyst_crowded_penalty
        - watchlist_penalty_state.effective_watchlist_zero_catalyst_flat_trend_penalty
        - watchlist_penalty_state.effective_watchlist_filter_diagnostics_flat_trend_penalty
        - overbought_momentum_penalty
    )
    return {
        "weighted_positive_contributions": weighted_positive_contributions,
        "weighted_negative_contributions": weighted_negative_contributions,
        "total_positive_contribution": total_positive_contribution,
        "total_negative_contribution": total_negative_contribution,
        "trend_continuation_strength_adjustment": round(trend_continuation_strength_adjustment, 4),
        "overbought_momentum_penalty": round(overbought_momentum_penalty, 4),
        "score_target": score_target,
        "historical_continuation_prior_score": historical_continuation_prior_score,
    }


def _resolve_short_trade_snapshot_relief_resolution(
    input_data: Any,
    *,
    profile: Any,
    signal_snapshot: dict[str, Any],
    historical_prior: Callable[[Any], dict[str, Any]],
    normalize_positive_score_weights: Callable[[dict[str, Any]], dict[str, float]],
    clamp_unit_interval,
    resolve_profitability_relief: Callable[..., dict[str, Any]],
    resolve_upstream_shadow_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_visibility_gap_continuation_relief: Callable[..., dict[str, Any]],
    resolve_merge_approved_continuation_relief: Callable[..., dict[str, Any]],
    resolve_historical_execution_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_continuation_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_penalty_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_volume_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_selected_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_catalyst_theme_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_crowded_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_flat_trend_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_filter_diagnostics_flat_trend_penalty: Callable[..., dict[str, Any]],
    resolve_t_plus_2_continuation_candidate: Callable[..., dict[str, Any]],
    resolve_profitability_hard_cliff_boundary_relief: Callable[..., dict[str, Any]],
    resolve_selected_score_tolerance: Callable[..., float],
) -> SnapshotReliefResolution:
    core_state = _build_short_trade_snapshot_resolution_core_state(
        input_data,
        profile=profile,
        signal_snapshot=signal_snapshot,
        historical_prior=historical_prior,
        normalize_positive_score_weights=normalize_positive_score_weights,
        clamp_unit_interval=clamp_unit_interval,
        resolve_profitability_relief=resolve_profitability_relief,
        resolve_upstream_shadow_catalyst_relief=resolve_upstream_shadow_catalyst_relief,
        resolve_visibility_gap_continuation_relief=resolve_visibility_gap_continuation_relief,
        resolve_merge_approved_continuation_relief=resolve_merge_approved_continuation_relief,
        resolve_historical_execution_relief=resolve_historical_execution_relief,
        resolve_prepared_breakout_continuation_relief=resolve_prepared_breakout_continuation_relief,
        resolve_prepared_breakout_penalty_relief=resolve_prepared_breakout_penalty_relief,
        resolve_prepared_breakout_catalyst_relief=resolve_prepared_breakout_catalyst_relief,
        resolve_prepared_breakout_volume_relief=resolve_prepared_breakout_volume_relief,
        resolve_prepared_breakout_selected_catalyst_relief=resolve_prepared_breakout_selected_catalyst_relief,
        resolve_catalyst_theme_penalty=resolve_catalyst_theme_penalty,
        resolve_watchlist_zero_catalyst_penalty=resolve_watchlist_zero_catalyst_penalty,
        resolve_watchlist_zero_catalyst_crowded_penalty=resolve_watchlist_zero_catalyst_crowded_penalty,
        resolve_watchlist_zero_catalyst_flat_trend_penalty=resolve_watchlist_zero_catalyst_flat_trend_penalty,
        resolve_watchlist_filter_diagnostics_flat_trend_penalty=resolve_watchlist_filter_diagnostics_flat_trend_penalty,
        resolve_t_plus_2_continuation_candidate=resolve_t_plus_2_continuation_candidate,
        resolve_profitability_hard_cliff_boundary_relief=resolve_profitability_hard_cliff_boundary_relief,
    )
    return _finalize_short_trade_snapshot_relief_resolution(
        core_state=core_state,
        resolve_selected_score_tolerance=resolve_selected_score_tolerance,
    )


def _build_short_trade_snapshot_resolution_core_state(
    input_data: Any,
    *,
    profile: Any,
    signal_snapshot: dict[str, Any],
    historical_prior: Callable[[Any], dict[str, Any]],
    normalize_positive_score_weights: Callable[[dict[str, Any]], dict[str, float]],
    clamp_unit_interval,
    resolve_profitability_relief: Callable[..., dict[str, Any]],
    resolve_upstream_shadow_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_visibility_gap_continuation_relief: Callable[..., dict[str, Any]],
    resolve_merge_approved_continuation_relief: Callable[..., dict[str, Any]],
    resolve_historical_execution_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_continuation_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_penalty_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_volume_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_selected_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_catalyst_theme_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_crowded_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_flat_trend_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_filter_diagnostics_flat_trend_penalty: Callable[..., dict[str, Any]],
    resolve_t_plus_2_continuation_candidate: Callable[..., dict[str, Any]],
    resolve_profitability_hard_cliff_boundary_relief: Callable[..., dict[str, Any]],
) -> SnapshotResolutionCoreState:
    state = _build_snapshot_signal_state(signal_snapshot, historical_prior=historical_prior(input_data))
    prepared_breakout_reliefs = _resolve_prepared_breakout_reliefs(
        input_data,
        profile=profile,
        state=state,
        resolve_prepared_breakout_continuation_relief=resolve_prepared_breakout_continuation_relief,
        resolve_prepared_breakout_penalty_relief=resolve_prepared_breakout_penalty_relief,
        resolve_prepared_breakout_catalyst_relief=resolve_prepared_breakout_catalyst_relief,
        resolve_prepared_breakout_volume_relief=resolve_prepared_breakout_volume_relief,
    )
    positive_score_weights = normalize_positive_score_weights(dict(prepared_breakout_reliefs.penalty_relief["effective_positive_score_weights"]))
    threshold_state = _resolve_snapshot_threshold_state(
        input_data,
        profile=profile,
        state=state,
        prepared_breakout_reliefs=prepared_breakout_reliefs,
        resolve_profitability_relief=resolve_profitability_relief,
        resolve_upstream_shadow_catalyst_relief=resolve_upstream_shadow_catalyst_relief,
        resolve_visibility_gap_continuation_relief=resolve_visibility_gap_continuation_relief,
        resolve_merge_approved_continuation_relief=resolve_merge_approved_continuation_relief,
        resolve_historical_execution_relief=resolve_historical_execution_relief,
        resolve_prepared_breakout_selected_catalyst_relief=resolve_prepared_breakout_selected_catalyst_relief,
    )
    watchlist_penalty_state = _resolve_watchlist_penalty_state(
        input_data,
        profile=profile,
        state=state,
        threshold_state=threshold_state,
        resolve_catalyst_theme_penalty=resolve_catalyst_theme_penalty,
        resolve_watchlist_zero_catalyst_penalty=resolve_watchlist_zero_catalyst_penalty,
        resolve_watchlist_zero_catalyst_crowded_penalty=resolve_watchlist_zero_catalyst_crowded_penalty,
        resolve_watchlist_zero_catalyst_flat_trend_penalty=resolve_watchlist_zero_catalyst_flat_trend_penalty,
        resolve_watchlist_filter_diagnostics_flat_trend_penalty=resolve_watchlist_filter_diagnostics_flat_trend_penalty,
        resolve_t_plus_2_continuation_candidate=resolve_t_plus_2_continuation_candidate,
    )
    score_penalty_state = _resolve_score_penalty_state(
        input_data,
        profile=profile,
        state=state,
        threshold_state=threshold_state,
        prepared_breakout_reliefs=prepared_breakout_reliefs,
        clamp_unit_interval=clamp_unit_interval,
        resolve_profitability_hard_cliff_boundary_relief=resolve_profitability_hard_cliff_boundary_relief,
    )
    # Apply event catalyst with real penalty values
    threshold_state = _apply_event_catalyst_threshold_adjustments(
        input_data=input_data,
        profile=profile,
        state=state,
        threshold_state=threshold_state,
        score_penalty_state=score_penalty_state,
    )
    score_payload = _build_snapshot_score_payload(
        profile=profile,
        state=state,
        threshold_state=threshold_state,
        watchlist_penalty_state=watchlist_penalty_state,
        score_penalty_state=score_penalty_state,
        positive_score_weights=positive_score_weights,
        clamp_unit_interval=clamp_unit_interval,
    )
    return SnapshotResolutionCoreState(
        profile=profile,
        state=state,
        market_state=dict(getattr(input_data, "market_state", {}) or {}),
        prepared_breakout_reliefs=prepared_breakout_reliefs,
        threshold_state=threshold_state,
        watchlist_penalty_state=watchlist_penalty_state,
        score_penalty_state=score_penalty_state,
        positive_score_weights=positive_score_weights,
        score_payload=score_payload,
    )


def _finalize_short_trade_snapshot_relief_resolution(
    *,
    core_state: SnapshotResolutionCoreState,
    resolve_selected_score_tolerance: Callable[..., float],
) -> SnapshotReliefResolution:
    market_state_threshold_adjustment = _resolve_market_state_threshold_adjustment(
        market_state=core_state.market_state,
        effective_select_threshold=core_state.threshold_state.effective_select_threshold,
        effective_near_miss_threshold=core_state.score_penalty_state.effective_near_miss_threshold,
    )
    effective_watchlist_selected_only_shrink_select_threshold = float(market_state_threshold_adjustment["effective_select_threshold"]) + (
        core_state.watchlist_penalty_state.effective_watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift + core_state.watchlist_penalty_state.effective_layer_c_watchlist_selected_only_shrink_select_threshold_lift + core_state.watchlist_penalty_state.effective_short_trade_boundary_selected_only_shrink_select_threshold_lift
    )
    selected_close_retention_adjustment = _resolve_selected_close_retention_adjustment(
        profile=core_state.profile,
        state=core_state.state,
        breakout_trap_guard=core_state.score_penalty_state.breakout_trap_guard,
        effective_select_threshold=effective_watchlist_selected_only_shrink_select_threshold,
        effective_near_miss_threshold=float(market_state_threshold_adjustment["effective_near_miss_threshold"]),
        clamp_unit_interval=lambda value: max(0.0, min(1.0, float(value))),
    )
    selected_close_retention_penalty = _resolve_selected_close_retention_penalty(
        profile=core_state.profile,
        selected_close_retention_adjustment=selected_close_retention_adjustment,
    )
    adjusted_threshold_state = SnapshotThresholdState(
        profitability_relief=core_state.threshold_state.profitability_relief,
        catalyst_relief=core_state.threshold_state.catalyst_relief,
        visibility_gap_continuation_relief=core_state.threshold_state.visibility_gap_continuation_relief,
        merge_approved_continuation_relief=core_state.threshold_state.merge_approved_continuation_relief,
        historical_execution_relief=core_state.threshold_state.historical_execution_relief,
        prepared_breakout_selected_catalyst_relief=core_state.threshold_state.prepared_breakout_selected_catalyst_relief,
        breakout_freshness=core_state.threshold_state.breakout_freshness,
        trend_acceleration=core_state.threshold_state.trend_acceleration,
        volume_expansion_quality=core_state.threshold_state.volume_expansion_quality,
        catalyst_freshness=core_state.threshold_state.catalyst_freshness,
        effective_near_miss_threshold=float(selected_close_retention_adjustment["effective_near_miss_threshold"]),
        effective_select_threshold=float(selected_close_retention_adjustment["effective_select_threshold"]),
        layer_c_avoid_penalty=core_state.threshold_state.layer_c_avoid_penalty,
        market_state_threshold_adjustment=market_state_threshold_adjustment,
        selected_close_retention_adjustment=selected_close_retention_adjustment,
        event_catalyst_assessment=core_state.threshold_state.event_catalyst_assessment,
    )
    adjusted_score_penalty_state = ScorePenaltyState(
        profitability_hard_cliff_boundary_relief=core_state.score_penalty_state.profitability_hard_cliff_boundary_relief,
        stale_trend_repair_penalty=core_state.score_penalty_state.stale_trend_repair_penalty,
        overhead_supply_penalty=core_state.score_penalty_state.overhead_supply_penalty,
        extension_without_room_penalty=core_state.score_penalty_state.extension_without_room_penalty,
        breakout_trap_guard=core_state.score_penalty_state.breakout_trap_guard,
        breakout_trap_risk=core_state.score_penalty_state.breakout_trap_risk,
        breakout_trap_penalty=core_state.score_penalty_state.breakout_trap_penalty,
        effective_near_miss_threshold=float(selected_close_retention_adjustment["effective_near_miss_threshold"]),
        effective_stale_score_penalty_weight=core_state.score_penalty_state.effective_stale_score_penalty_weight,
        effective_extension_score_penalty_weight=core_state.score_penalty_state.effective_extension_score_penalty_weight,
    )
    adjusted_score_payload = dict(core_state.score_payload)
    adjusted_weighted_negative_contributions = dict(adjusted_score_payload["weighted_negative_contributions"])
    adjusted_weighted_negative_contributions["selected_close_retention_penalty"] = round(float(selected_close_retention_penalty["penalty"]), 4)
    adjusted_score_payload["weighted_negative_contributions"] = adjusted_weighted_negative_contributions
    adjusted_score_payload["total_negative_contribution"] = round(
        float(core_state.score_payload["total_negative_contribution"]) + float(selected_close_retention_penalty["penalty"]),
        4,
    )
    adjusted_score_payload["score_target"] = max(
        0.0,
        float(core_state.score_payload["score_target"]) - float(selected_close_retention_penalty["penalty"]),
    )
    adjusted_score_payload["selected_close_retention_penalty"] = selected_close_retention_penalty
    selected_score_tolerance = resolve_selected_score_tolerance(
        score_target=adjusted_score_payload["score_target"],
        effective_select_threshold=adjusted_threshold_state.effective_select_threshold,
        upstream_shadow_catalyst_relief_applied=bool(adjusted_threshold_state.catalyst_relief["applied"]),
        upstream_shadow_catalyst_relief_reason=str(adjusted_threshold_state.catalyst_relief["reason"]),
        historical_prior=core_state.state.historical_prior,
    )
    return SnapshotReliefResolution(
        state=core_state.state,
        prepared_breakout_reliefs=core_state.prepared_breakout_reliefs,
        threshold_state=adjusted_threshold_state,
        watchlist_penalty_state=core_state.watchlist_penalty_state,
        score_penalty_state=adjusted_score_penalty_state,
        positive_score_weights=core_state.positive_score_weights,
        score_payload=adjusted_score_payload,
        selected_score_tolerance=selected_score_tolerance,
    )


def _build_short_trade_snapshot_reliefs_payload(resolution: SnapshotReliefResolution) -> dict[str, Any]:
    return {
        "prepared_breakout_penalty_relief": resolution.prepared_breakout_reliefs.penalty_relief,
        "prepared_breakout_catalyst_relief": resolution.prepared_breakout_reliefs.catalyst_relief,
        "prepared_breakout_volume_relief": resolution.prepared_breakout_reliefs.volume_relief,
        "prepared_breakout_continuation_relief": resolution.prepared_breakout_reliefs.continuation_relief,
        "prepared_breakout_selected_catalyst_relief": resolution.threshold_state.prepared_breakout_selected_catalyst_relief,
        "profitability_relief": resolution.threshold_state.profitability_relief,
        "profitability_hard_cliff_boundary_relief": resolution.score_penalty_state.profitability_hard_cliff_boundary_relief,
        "historical_execution_relief": resolution.threshold_state.historical_execution_relief,
        "historical_prior": resolution.state.historical_prior,
        "upstream_shadow_catalyst_relief": resolution.threshold_state.catalyst_relief,
        "visibility_gap_continuation_relief": resolution.threshold_state.visibility_gap_continuation_relief,
        "merge_approved_continuation_relief": resolution.threshold_state.merge_approved_continuation_relief,
        "catalyst_theme_penalty": resolution.watchlist_penalty_state.catalyst_theme_penalty,
        "watchlist_zero_catalyst_penalty": resolution.watchlist_penalty_state.watchlist_zero_catalyst_penalty,
        "watchlist_zero_catalyst_crowded_penalty": resolution.watchlist_penalty_state.watchlist_zero_catalyst_crowded_penalty,
        "watchlist_zero_catalyst_flat_trend_penalty": resolution.watchlist_penalty_state.watchlist_zero_catalyst_flat_trend_penalty,
        "watchlist_filter_diagnostics_flat_trend_penalty": resolution.watchlist_penalty_state.watchlist_filter_diagnostics_flat_trend_penalty,
        "watchlist_filter_diagnostics_selected_only_shrink_guard": resolution.watchlist_penalty_state.watchlist_filter_diagnostics_selected_only_shrink_guard,
        "layer_c_watchlist_selected_only_shrink_guard": resolution.watchlist_penalty_state.layer_c_watchlist_selected_only_shrink_guard,
        "short_trade_boundary_selected_only_shrink_guard": resolution.watchlist_penalty_state.short_trade_boundary_selected_only_shrink_guard,
        "t_plus_2_continuation_candidate": resolution.watchlist_penalty_state.t_plus_2_continuation_candidate,
        "breakout_trap_guard": resolution.score_penalty_state.breakout_trap_guard,
        "breakout_trap_risk": resolution.score_penalty_state.breakout_trap_risk,
        "breakout_trap_penalty": resolution.score_penalty_state.breakout_trap_penalty,
        "positive_score_weights": resolution.positive_score_weights,
        "weighted_positive_contributions": resolution.score_payload["weighted_positive_contributions"],
        "weighted_negative_contributions": resolution.score_payload["weighted_negative_contributions"],
        "total_positive_contribution": resolution.score_payload["total_positive_contribution"],
        "total_negative_contribution": resolution.score_payload["total_negative_contribution"],
        "historical_continuation_prior_score": resolution.score_payload["historical_continuation_prior_score"],
        "trend_continuation_strength_adjustment": resolution.score_payload["trend_continuation_strength_adjustment"],
        "score_target": resolution.score_payload["score_target"],
        "selected_score_tolerance": resolution.selected_score_tolerance,
        "effective_near_miss_threshold": resolution.score_penalty_state.effective_near_miss_threshold,
        "effective_select_threshold": resolution.threshold_state.effective_select_threshold,
        "market_state_threshold_adjustment": resolution.threshold_state.market_state_threshold_adjustment,
        "selected_close_retention_adjustment": resolution.threshold_state.selected_close_retention_adjustment,
        "selected_close_retention_penalty": resolution.score_payload["selected_close_retention_penalty"],
        "close_retention_score": resolution.threshold_state.selected_close_retention_adjustment["close_retention_score"],
        "breakout_close_gap": resolution.threshold_state.selected_close_retention_adjustment["breakout_close_gap"],
        "catalyst_freshness": resolution.threshold_state.catalyst_freshness,
        "breakout_freshness": resolution.threshold_state.breakout_freshness,
        "trend_acceleration": resolution.threshold_state.trend_acceleration,
        "volume_expansion_quality": resolution.threshold_state.volume_expansion_quality,
        "layer_c_avoid_penalty": resolution.threshold_state.layer_c_avoid_penalty,
        "catalyst_theme_penalty_effective": resolution.watchlist_penalty_state.effective_catalyst_theme_penalty,
        "watchlist_zero_catalyst_penalty_effective": resolution.watchlist_penalty_state.effective_watchlist_zero_catalyst_penalty,
        "watchlist_zero_catalyst_crowded_penalty_effective": resolution.watchlist_penalty_state.effective_watchlist_zero_catalyst_crowded_penalty,
        "watchlist_zero_catalyst_flat_trend_penalty_effective": resolution.watchlist_penalty_state.effective_watchlist_zero_catalyst_flat_trend_penalty,
        "watchlist_filter_diagnostics_flat_trend_penalty_effective": resolution.watchlist_penalty_state.effective_watchlist_filter_diagnostics_flat_trend_penalty,
        "stale_trend_repair_penalty": resolution.score_penalty_state.stale_trend_repair_penalty,
        "overhead_supply_penalty": resolution.score_penalty_state.overhead_supply_penalty,
        "extension_without_room_penalty": resolution.score_penalty_state.extension_without_room_penalty,
        "event_catalyst_assessment": resolution.threshold_state.event_catalyst_assessment,
    }


def resolve_short_trade_snapshot_reliefs_impl(
    input_data: Any,
    *,
    profile: Any,
    signal_snapshot: dict[str, Any],
    historical_prior: Callable[[Any], dict[str, Any]],
    normalize_positive_score_weights: Callable[[dict[str, Any]], dict[str, float]],
    clamp_unit_interval,
    resolve_profitability_relief: Callable[..., dict[str, Any]],
    resolve_upstream_shadow_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_visibility_gap_continuation_relief: Callable[..., dict[str, Any]],
    resolve_merge_approved_continuation_relief: Callable[..., dict[str, Any]],
    resolve_historical_execution_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_continuation_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_penalty_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_volume_relief: Callable[..., dict[str, Any]],
    resolve_prepared_breakout_selected_catalyst_relief: Callable[..., dict[str, Any]],
    resolve_catalyst_theme_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_crowded_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_flat_trend_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_filter_diagnostics_flat_trend_penalty: Callable[..., dict[str, Any]],
    resolve_t_plus_2_continuation_candidate: Callable[..., dict[str, Any]],
    resolve_profitability_hard_cliff_boundary_relief: Callable[..., dict[str, Any]],
    resolve_selected_score_tolerance: Callable[..., float],
) -> dict[str, Any]:
    resolution = _resolve_short_trade_snapshot_relief_resolution(
        input_data,
        profile=profile,
        signal_snapshot=signal_snapshot,
        historical_prior=historical_prior,
        normalize_positive_score_weights=normalize_positive_score_weights,
        clamp_unit_interval=clamp_unit_interval,
        resolve_profitability_relief=resolve_profitability_relief,
        resolve_upstream_shadow_catalyst_relief=resolve_upstream_shadow_catalyst_relief,
        resolve_visibility_gap_continuation_relief=resolve_visibility_gap_continuation_relief,
        resolve_merge_approved_continuation_relief=resolve_merge_approved_continuation_relief,
        resolve_historical_execution_relief=resolve_historical_execution_relief,
        resolve_prepared_breakout_continuation_relief=resolve_prepared_breakout_continuation_relief,
        resolve_prepared_breakout_penalty_relief=resolve_prepared_breakout_penalty_relief,
        resolve_prepared_breakout_catalyst_relief=resolve_prepared_breakout_catalyst_relief,
        resolve_prepared_breakout_volume_relief=resolve_prepared_breakout_volume_relief,
        resolve_prepared_breakout_selected_catalyst_relief=resolve_prepared_breakout_selected_catalyst_relief,
        resolve_catalyst_theme_penalty=resolve_catalyst_theme_penalty,
        resolve_watchlist_zero_catalyst_penalty=resolve_watchlist_zero_catalyst_penalty,
        resolve_watchlist_zero_catalyst_crowded_penalty=resolve_watchlist_zero_catalyst_crowded_penalty,
        resolve_watchlist_zero_catalyst_flat_trend_penalty=resolve_watchlist_zero_catalyst_flat_trend_penalty,
        resolve_watchlist_filter_diagnostics_flat_trend_penalty=resolve_watchlist_filter_diagnostics_flat_trend_penalty,
        resolve_t_plus_2_continuation_candidate=resolve_t_plus_2_continuation_candidate,
        resolve_profitability_hard_cliff_boundary_relief=resolve_profitability_hard_cliff_boundary_relief,
        resolve_selected_score_tolerance=resolve_selected_score_tolerance,
    )
    return _build_short_trade_snapshot_reliefs_payload(resolution)
