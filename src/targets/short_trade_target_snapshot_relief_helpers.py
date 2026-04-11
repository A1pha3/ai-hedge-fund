from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


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


@dataclass(frozen=True)
class WatchlistPenaltyState:
    watchlist_zero_catalyst_penalty: dict[str, Any]
    watchlist_zero_catalyst_crowded_penalty: dict[str, Any]
    watchlist_zero_catalyst_flat_trend_penalty: dict[str, Any]
    t_plus_2_continuation_candidate: dict[str, Any]
    effective_watchlist_zero_catalyst_penalty: float
    effective_watchlist_zero_catalyst_crowded_penalty: float
    effective_watchlist_zero_catalyst_flat_trend_penalty: float


@dataclass(frozen=True)
class ScorePenaltyState:
    profitability_hard_cliff_boundary_relief: dict[str, Any]
    stale_trend_repair_penalty: float
    overhead_supply_penalty: float
    extension_without_room_penalty: float
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
    continuation_relief = resolve_prepared_breakout_continuation_relief(
        input_data=input_data,
        breakout_stage=state.breakout_stage,
        breakout_freshness=state.breakout_freshness,
        trend_acceleration=state.trend_acceleration,
        close_strength=state.close_strength,
        sector_resonance=state.sector_resonance,
        layer_c_alignment=state.layer_c_alignment,
        catalyst_freshness=state.raw_catalyst_freshness,
        long_trend_strength=state.long_trend_strength,
        mean_reversion_strength=state.mean_reversion_strength,
        momentum_1m=state.momentum_1m,
        momentum_3m=state.momentum_3m,
        momentum_6m=state.momentum_6m,
        volume_momentum=state.volume_momentum,
        ema_strength=state.ema_strength,
        profile=profile,
    )
    penalty_relief = resolve_prepared_breakout_penalty_relief(
        input_data=input_data,
        breakout_stage=state.breakout_stage,
        breakout_freshness=state.breakout_freshness,
        trend_acceleration=state.trend_acceleration,
        close_strength=state.close_strength,
        sector_resonance=state.sector_resonance,
        layer_c_alignment=state.layer_c_alignment,
        catalyst_freshness=state.raw_catalyst_freshness,
        long_trend_strength=state.long_trend_strength,
        mean_reversion_strength=state.mean_reversion_strength,
        profile=profile,
    )
    catalyst_relief = resolve_prepared_breakout_catalyst_relief(
        input_data=input_data,
        breakout_stage=state.breakout_stage,
        breakout_freshness=state.breakout_freshness,
        trend_acceleration=state.trend_acceleration,
        close_strength=state.close_strength,
        sector_resonance=state.sector_resonance,
        layer_c_alignment=state.layer_c_alignment,
        catalyst_freshness=state.raw_catalyst_freshness,
        long_trend_strength=state.long_trend_strength,
        mean_reversion_strength=state.mean_reversion_strength,
        profile=profile,
    )
    volume_relief = resolve_prepared_breakout_volume_relief(
        input_data=input_data,
        breakout_stage=state.breakout_stage,
        breakout_freshness=state.breakout_freshness,
        trend_acceleration=state.trend_acceleration,
        close_strength=state.close_strength,
        sector_resonance=state.sector_resonance,
        layer_c_alignment=state.layer_c_alignment,
        catalyst_freshness=state.raw_catalyst_freshness,
        long_trend_strength=state.long_trend_strength,
        mean_reversion_strength=state.mean_reversion_strength,
        volatility_strength=state.volatility_strength,
        volume_expansion_quality=state.volume_expansion_quality,
        volatility_regime=float(state.volatility_metrics.get("volatility_regime", 0.0) or 0.0),
        atr_ratio=float(state.volatility_metrics.get("atr_ratio", 0.0) or 0.0),
        profile=profile,
    )
    return PreparedBreakoutReliefs(
        continuation_relief=continuation_relief,
        penalty_relief=penalty_relief,
        catalyst_relief=catalyst_relief,
        volume_relief=volume_relief,
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
    profitability_relief = resolve_profitability_relief(
        input_data=input_data,
        fundamental_signal=state.fundamental_signal,
        breakout_freshness=state.breakout_freshness,
        catalyst_freshness=state.raw_catalyst_freshness,
        sector_resonance=state.sector_resonance,
        profile=profile,
    )
    catalyst_relief = resolve_upstream_shadow_catalyst_relief(
        input_data=input_data,
        breakout_freshness=state.breakout_freshness,
        trend_acceleration=state.trend_acceleration,
        close_strength=state.close_strength,
        catalyst_freshness=state.raw_catalyst_freshness,
        profitability_hard_cliff=bool(profitability_relief["hard_cliff"]),
        profile=profile,
    )
    visibility_gap_continuation_relief = resolve_visibility_gap_continuation_relief(
        input_data=input_data,
        breakout_freshness=state.breakout_freshness,
        trend_acceleration=state.trend_acceleration,
        close_strength=state.close_strength,
        catalyst_freshness=state.raw_catalyst_freshness,
        profitability_hard_cliff=bool(profitability_relief["hard_cliff"]),
        profile=profile,
    )
    merge_approved_continuation_relief = resolve_merge_approved_continuation_relief(
        input_data=input_data,
        breakout_freshness=state.breakout_freshness,
        trend_acceleration=state.trend_acceleration,
        close_strength=state.close_strength,
        profitability_hard_cliff=bool(profitability_relief["hard_cliff"]),
        profile=profile,
    )
    historical_execution_relief = resolve_historical_execution_relief(
        input_data=input_data,
        profitability_hard_cliff=bool(profitability_relief["hard_cliff"]),
        profile=profile,
    )
    catalyst_freshness = float(catalyst_relief["effective_catalyst_freshness"])
    effective_near_miss_threshold = float(catalyst_relief["effective_near_miss_threshold"])
    effective_select_threshold = float(catalyst_relief["effective_select_threshold"])
    breakout_freshness = max(state.breakout_freshness, float(prepared_breakout_reliefs.continuation_relief["effective_breakout_freshness"]))
    trend_acceleration = max(state.trend_acceleration, float(prepared_breakout_reliefs.continuation_relief["effective_trend_acceleration"]))
    volume_expansion_quality = max(
        state.volume_expansion_quality,
        float(prepared_breakout_reliefs.volume_relief["effective_volume_expansion_quality"]),
    )
    catalyst_freshness = max(catalyst_freshness, float(visibility_gap_continuation_relief["effective_catalyst_freshness"]))
    catalyst_freshness = max(catalyst_freshness, float(prepared_breakout_reliefs.catalyst_relief["effective_catalyst_freshness"]))
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
    breakout_freshness = max(breakout_freshness, float(prepared_breakout_selected_catalyst_relief["effective_breakout_freshness"]))
    catalyst_freshness = max(catalyst_freshness, float(prepared_breakout_selected_catalyst_relief["effective_catalyst_freshness"]))
    effective_near_miss_threshold = min(
        effective_near_miss_threshold,
        float(visibility_gap_continuation_relief["effective_near_miss_threshold"]),
    )
    effective_near_miss_threshold = min(
        effective_near_miss_threshold,
        float(merge_approved_continuation_relief["effective_near_miss_threshold"]),
    )
    effective_near_miss_threshold = min(
        effective_near_miss_threshold,
        float(historical_execution_relief["effective_near_miss_threshold"]),
    )
    effective_select_threshold = min(
        effective_select_threshold,
        float(merge_approved_continuation_relief["effective_select_threshold"]),
    )
    effective_select_threshold = min(
        effective_select_threshold,
        float(historical_execution_relief["effective_select_threshold"]),
    )
    return SnapshotThresholdState(
        profitability_relief=profitability_relief,
        catalyst_relief=catalyst_relief,
        visibility_gap_continuation_relief=visibility_gap_continuation_relief,
        merge_approved_continuation_relief=merge_approved_continuation_relief,
        historical_execution_relief=historical_execution_relief,
        prepared_breakout_selected_catalyst_relief=prepared_breakout_selected_catalyst_relief,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        volume_expansion_quality=volume_expansion_quality,
        catalyst_freshness=catalyst_freshness,
        effective_near_miss_threshold=effective_near_miss_threshold,
        effective_select_threshold=effective_select_threshold,
        layer_c_avoid_penalty=float(profitability_relief["effective_avoid_penalty"]),
    )


def _resolve_watchlist_penalty_state(
    input_data: Any,
    *,
    profile: Any,
    state: SnapshotSignalState,
    threshold_state: SnapshotThresholdState,
    resolve_watchlist_zero_catalyst_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_crowded_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_flat_trend_penalty: Callable[..., dict[str, Any]],
    resolve_t_plus_2_continuation_candidate: Callable[..., dict[str, Any]],
) -> WatchlistPenaltyState:
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
        watchlist_zero_catalyst_penalty=watchlist_zero_catalyst_penalty,
        watchlist_zero_catalyst_crowded_penalty=watchlist_zero_catalyst_crowded_penalty,
        watchlist_zero_catalyst_flat_trend_penalty=watchlist_zero_catalyst_flat_trend_penalty,
        t_plus_2_continuation_candidate=t_plus_2_continuation_candidate,
        effective_watchlist_zero_catalyst_penalty=float(watchlist_zero_catalyst_penalty["effective_penalty"]),
        effective_watchlist_zero_catalyst_crowded_penalty=float(watchlist_zero_catalyst_crowded_penalty["effective_penalty"]),
        effective_watchlist_zero_catalyst_flat_trend_penalty=float(watchlist_zero_catalyst_flat_trend_penalty["effective_penalty"]),
    )


def _resolve_score_penalty_state(
    input_data: Any,
    *,
    profile: Any,
    state: SnapshotSignalState,
    threshold_state: SnapshotThresholdState,
    prepared_breakout_reliefs: PreparedBreakoutReliefs,
    clamp_unit_interval: Callable[[float], float],
    resolve_profitability_hard_cliff_boundary_relief: Callable[..., dict[str, Any]],
) -> ScorePenaltyState:
    stale_trend_repair_penalty = clamp_unit_interval(
        (0.45 * state.mean_reversion_strength)
        + (0.35 * state.long_trend_strength)
        + (0.20 * max(0.0, state.long_trend_strength - threshold_state.breakout_freshness))
    )
    overhead_supply_penalty = clamp_unit_interval(
        (0.45 if input_data.bc_conflict in profile.overhead_conflict_penalty_conflicts else 0.0)
        + (0.35 * state.analyst_penalty)
        + (0.20 * state.investor_penalty)
    )
    extension_without_room_penalty = clamp_unit_interval(
        (0.45 * state.long_trend_strength)
        + (0.35 * max(0.0, state.volatility_strength - threshold_state.catalyst_freshness))
        + (0.20 * clamp_unit_interval((state.score_final_strength - 0.72) / 0.28))
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
    clamp_unit_interval: Callable[[float], float],
) -> dict[str, Any]:
    weighted_positive_contributions = {
        "breakout_freshness": round(positive_score_weights["breakout_freshness"] * threshold_state.breakout_freshness, 4),
        "trend_acceleration": round(positive_score_weights["trend_acceleration"] * threshold_state.trend_acceleration, 4),
        "volume_expansion_quality": round(positive_score_weights["volume_expansion_quality"] * threshold_state.volume_expansion_quality, 4),
        "close_strength": round(positive_score_weights["close_strength"] * state.close_strength, 4),
        "sector_resonance": round(positive_score_weights["sector_resonance"] * state.sector_resonance, 4),
        "catalyst_freshness": round(positive_score_weights["catalyst_freshness"] * threshold_state.catalyst_freshness, 4),
        "layer_c_alignment": round(positive_score_weights["layer_c_alignment"] * state.layer_c_alignment, 4),
    }
    weighted_negative_contributions = {
        "stale_trend_repair_penalty": round(score_penalty_state.effective_stale_score_penalty_weight * score_penalty_state.stale_trend_repair_penalty, 4),
        "overhead_supply_penalty": round(profile.overhead_score_penalty_weight * score_penalty_state.overhead_supply_penalty, 4),
        "extension_without_room_penalty": round(score_penalty_state.effective_extension_score_penalty_weight * score_penalty_state.extension_without_room_penalty, 4),
        "layer_c_avoid_penalty": round(threshold_state.layer_c_avoid_penalty, 4),
        "watchlist_zero_catalyst_penalty": round(watchlist_penalty_state.effective_watchlist_zero_catalyst_penalty, 4),
        "watchlist_zero_catalyst_crowded_penalty": round(watchlist_penalty_state.effective_watchlist_zero_catalyst_crowded_penalty, 4),
        "watchlist_zero_catalyst_flat_trend_penalty": round(watchlist_penalty_state.effective_watchlist_zero_catalyst_flat_trend_penalty, 4),
    }
    total_positive_contribution = round(sum(weighted_positive_contributions.values()), 4)
    total_negative_contribution = round(sum(weighted_negative_contributions.values()), 4)
    score_target = clamp_unit_interval(
        (positive_score_weights["breakout_freshness"] * threshold_state.breakout_freshness)
        + (positive_score_weights["trend_acceleration"] * threshold_state.trend_acceleration)
        + (positive_score_weights["volume_expansion_quality"] * threshold_state.volume_expansion_quality)
        + (positive_score_weights["close_strength"] * state.close_strength)
        + (positive_score_weights["sector_resonance"] * state.sector_resonance)
        + (positive_score_weights["catalyst_freshness"] * threshold_state.catalyst_freshness)
        + (positive_score_weights["layer_c_alignment"] * state.layer_c_alignment)
        - (score_penalty_state.effective_stale_score_penalty_weight * score_penalty_state.stale_trend_repair_penalty)
        - (profile.overhead_score_penalty_weight * score_penalty_state.overhead_supply_penalty)
        - (score_penalty_state.effective_extension_score_penalty_weight * score_penalty_state.extension_without_room_penalty)
        - threshold_state.layer_c_avoid_penalty
        - watchlist_penalty_state.effective_watchlist_zero_catalyst_penalty
        - watchlist_penalty_state.effective_watchlist_zero_catalyst_crowded_penalty
        - watchlist_penalty_state.effective_watchlist_zero_catalyst_flat_trend_penalty
    )
    return {
        "weighted_positive_contributions": weighted_positive_contributions,
        "weighted_negative_contributions": weighted_negative_contributions,
        "total_positive_contribution": total_positive_contribution,
        "total_negative_contribution": total_negative_contribution,
        "score_target": score_target,
    }


def _resolve_short_trade_snapshot_relief_resolution(
    input_data: Any,
    *,
    profile: Any,
    signal_snapshot: dict[str, Any],
    historical_prior: Callable[[Any], dict[str, Any]],
    normalize_positive_score_weights: Callable[[dict[str, Any]], dict[str, float]],
    clamp_unit_interval: Callable[[float], float],
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
    resolve_watchlist_zero_catalyst_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_crowded_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_flat_trend_penalty: Callable[..., dict[str, Any]],
    resolve_t_plus_2_continuation_candidate: Callable[..., dict[str, Any]],
    resolve_profitability_hard_cliff_boundary_relief: Callable[..., dict[str, Any]],
    resolve_selected_score_tolerance: Callable[..., float],
) -> SnapshotReliefResolution:
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
        resolve_watchlist_zero_catalyst_penalty=resolve_watchlist_zero_catalyst_penalty,
        resolve_watchlist_zero_catalyst_crowded_penalty=resolve_watchlist_zero_catalyst_crowded_penalty,
        resolve_watchlist_zero_catalyst_flat_trend_penalty=resolve_watchlist_zero_catalyst_flat_trend_penalty,
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
    score_payload = _build_snapshot_score_payload(
        profile=profile,
        state=state,
        threshold_state=threshold_state,
        watchlist_penalty_state=watchlist_penalty_state,
        score_penalty_state=score_penalty_state,
        positive_score_weights=positive_score_weights,
        clamp_unit_interval=clamp_unit_interval,
    )
    selected_score_tolerance = resolve_selected_score_tolerance(
        score_target=score_payload["score_target"],
        effective_select_threshold=threshold_state.effective_select_threshold,
        upstream_shadow_catalyst_relief_applied=bool(threshold_state.catalyst_relief["applied"]),
        upstream_shadow_catalyst_relief_reason=str(threshold_state.catalyst_relief["reason"]),
        historical_prior=state.historical_prior,
    )
    return SnapshotReliefResolution(
        state=state,
        prepared_breakout_reliefs=prepared_breakout_reliefs,
        threshold_state=threshold_state,
        watchlist_penalty_state=watchlist_penalty_state,
        score_penalty_state=score_penalty_state,
        positive_score_weights=positive_score_weights,
        score_payload=score_payload,
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
        "watchlist_zero_catalyst_penalty": resolution.watchlist_penalty_state.watchlist_zero_catalyst_penalty,
        "watchlist_zero_catalyst_crowded_penalty": resolution.watchlist_penalty_state.watchlist_zero_catalyst_crowded_penalty,
        "watchlist_zero_catalyst_flat_trend_penalty": resolution.watchlist_penalty_state.watchlist_zero_catalyst_flat_trend_penalty,
        "t_plus_2_continuation_candidate": resolution.watchlist_penalty_state.t_plus_2_continuation_candidate,
        "positive_score_weights": resolution.positive_score_weights,
        "weighted_positive_contributions": resolution.score_payload["weighted_positive_contributions"],
        "weighted_negative_contributions": resolution.score_payload["weighted_negative_contributions"],
        "total_positive_contribution": resolution.score_payload["total_positive_contribution"],
        "total_negative_contribution": resolution.score_payload["total_negative_contribution"],
        "score_target": resolution.score_payload["score_target"],
        "selected_score_tolerance": resolution.selected_score_tolerance,
        "effective_near_miss_threshold": resolution.score_penalty_state.effective_near_miss_threshold,
        "effective_select_threshold": resolution.threshold_state.effective_select_threshold,
        "catalyst_freshness": resolution.threshold_state.catalyst_freshness,
        "breakout_freshness": resolution.threshold_state.breakout_freshness,
        "trend_acceleration": resolution.threshold_state.trend_acceleration,
        "volume_expansion_quality": resolution.threshold_state.volume_expansion_quality,
        "layer_c_avoid_penalty": resolution.threshold_state.layer_c_avoid_penalty,
        "watchlist_zero_catalyst_penalty_effective": resolution.watchlist_penalty_state.effective_watchlist_zero_catalyst_penalty,
        "watchlist_zero_catalyst_crowded_penalty_effective": resolution.watchlist_penalty_state.effective_watchlist_zero_catalyst_crowded_penalty,
        "watchlist_zero_catalyst_flat_trend_penalty_effective": resolution.watchlist_penalty_state.effective_watchlist_zero_catalyst_flat_trend_penalty,
        "stale_trend_repair_penalty": resolution.score_penalty_state.stale_trend_repair_penalty,
        "overhead_supply_penalty": resolution.score_penalty_state.overhead_supply_penalty,
        "extension_without_room_penalty": resolution.score_penalty_state.extension_without_room_penalty,
    }


def resolve_short_trade_snapshot_reliefs_impl(
    input_data: Any,
    *,
    profile: Any,
    signal_snapshot: dict[str, Any],
    historical_prior: Callable[[Any], dict[str, Any]],
    normalize_positive_score_weights: Callable[[dict[str, Any]], dict[str, float]],
    clamp_unit_interval: Callable[[float], float],
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
    resolve_watchlist_zero_catalyst_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_crowded_penalty: Callable[..., dict[str, Any]],
    resolve_watchlist_zero_catalyst_flat_trend_penalty: Callable[..., dict[str, Any]],
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
        resolve_watchlist_zero_catalyst_penalty=resolve_watchlist_zero_catalyst_penalty,
        resolve_watchlist_zero_catalyst_crowded_penalty=resolve_watchlist_zero_catalyst_crowded_penalty,
        resolve_watchlist_zero_catalyst_flat_trend_penalty=resolve_watchlist_zero_catalyst_flat_trend_penalty,
        resolve_t_plus_2_continuation_candidate=resolve_t_plus_2_continuation_candidate,
        resolve_profitability_hard_cliff_boundary_relief=resolve_profitability_hard_cliff_boundary_relief,
    )
    return _build_short_trade_snapshot_reliefs_payload(resolution)
