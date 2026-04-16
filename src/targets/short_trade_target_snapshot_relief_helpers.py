from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Callable


BREAKOUT_TRAP_PENALTY_WEIGHT = 0.10
BREAKOUT_TRAP_EXECUTION_BLOCK_THRESHOLD = 0.60
BREAKOUT_TRAP_BLOCK_THRESHOLD = 0.72


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
    state: SnapshotSignalState
    market_state: dict[str, Any]
    prepared_breakout_reliefs: PreparedBreakoutReliefs
    threshold_state: SnapshotThresholdState
    watchlist_penalty_state: WatchlistPenaltyState
    score_penalty_state: ScorePenaltyState
    positive_score_weights: dict[str, float]
    score_payload: dict[str, Any]


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_reason_codes(values: Any) -> list[str]:
    return [str(reason).strip() for reason in list(values or []) if str(reason or "").strip()]


def _resolve_market_state_regime_context(market_state: dict[str, Any]) -> tuple[str, float, float, list[str]]:
    payload = dict(market_state or {})
    breadth_ratio = _safe_float(payload.get("breadth_ratio"))
    position_scale = _safe_float(payload.get("position_scale"))
    regime_flip_risk = _safe_float(payload.get("regime_flip_risk")) or 0.0
    style_dispersion = _safe_float(payload.get("style_dispersion")) or 0.0
    regime_gate_level = str(payload.get("regime_gate_level") or "").strip().lower()
    regime_gate_reasons = _safe_reason_codes(payload.get("regime_gate_reasons"))
    if regime_gate_level not in {"normal", "risk_off", "crisis"}:
        crisis = (breadth_ratio is not None and breadth_ratio <= 0.35) or (position_scale is not None and position_scale <= 0.55)
        risk_off = crisis or (breadth_ratio is not None and breadth_ratio <= 0.42) or (position_scale is not None and position_scale <= 0.75) or regime_flip_risk >= 0.58
        regime_gate_level = "crisis" if crisis else "risk_off" if risk_off else "normal"
    return regime_gate_level, style_dispersion, regime_flip_risk, regime_gate_reasons


def _build_market_state_threshold_adjustment(
    *,
    enabled: bool,
    risk_level: str,
    breadth_ratio: float | None,
    position_scale: float | None,
    regime_gate_level: str,
    regime_gate_reasons: list[str],
    style_dispersion: float,
    regime_flip_risk: float,
    execution_hard_gate: bool,
    select_threshold_lift: float,
    near_miss_threshold_lift: float,
    effective_select_threshold: float,
    effective_near_miss_threshold: float,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "risk_level": risk_level,
        "breadth_ratio": breadth_ratio,
        "position_scale": position_scale,
        "regime_gate_level": regime_gate_level,
        "regime_gate_reasons": regime_gate_reasons,
        "style_dispersion": round(float(style_dispersion), 4),
        "regime_flip_risk": round(float(regime_flip_risk), 4),
        "execution_hard_gate": bool(execution_hard_gate),
        "select_threshold_lift": round(float(select_threshold_lift), 4),
        "near_miss_threshold_lift": round(float(near_miss_threshold_lift), 4),
        "effective_select_threshold": round(float(effective_select_threshold), 4),
        "effective_near_miss_threshold": round(float(effective_near_miss_threshold), 4),
    }


def _resolve_market_state_threshold_adjustment(
    *,
    market_state: dict[str, Any],
    effective_select_threshold: float,
    effective_near_miss_threshold: float,
) -> dict[str, Any]:
    market_state_payload = dict(market_state or {})
    breadth_ratio = _safe_float(market_state_payload.get("breadth_ratio"))
    position_scale = _safe_float(market_state_payload.get("position_scale"))
    regime_gate_level, style_dispersion, regime_flip_risk, regime_gate_reasons = _resolve_market_state_regime_context(market_state_payload)
    if breadth_ratio is None and position_scale is None and regime_flip_risk <= 0.0 and style_dispersion <= 0.0:
        return _build_market_state_threshold_adjustment(
            enabled=False,
            risk_level="unknown",
            breadth_ratio=breadth_ratio,
            position_scale=position_scale,
            regime_gate_level="unknown",
            regime_gate_reasons=[],
            style_dispersion=0.0,
            regime_flip_risk=0.0,
            execution_hard_gate=False,
            select_threshold_lift=0.0,
            near_miss_threshold_lift=0.0,
            effective_select_threshold=effective_select_threshold,
            effective_near_miss_threshold=effective_near_miss_threshold,
        )

    if regime_gate_level == "crisis":
        select_lift = 0.03
        near_miss_lift = 0.02
        risk_level = "crisis"
    elif regime_gate_level == "risk_off":
        if regime_flip_risk >= 0.75 or style_dispersion >= 0.65:
            select_lift = 0.025
            near_miss_lift = 0.015
        else:
            select_lift = 0.015
            near_miss_lift = 0.01
        risk_level = "risk_off"
    else:
        select_lift = 0.0
        near_miss_lift = 0.0
        risk_level = "normal"

    adjusted_select_threshold = min(0.95, float(effective_select_threshold) + select_lift)
    adjusted_near_miss_threshold = min(adjusted_select_threshold, float(effective_near_miss_threshold) + near_miss_lift)
    execution_hard_gate = risk_level in {"risk_off", "crisis"}
    return _build_market_state_threshold_adjustment(
        enabled=select_lift > 0.0 or near_miss_lift > 0.0,
        risk_level=risk_level,
        breadth_ratio=breadth_ratio,
        position_scale=position_scale,
        regime_gate_level=regime_gate_level,
        regime_gate_reasons=regime_gate_reasons,
        style_dispersion=style_dispersion,
        regime_flip_risk=regime_flip_risk,
        execution_hard_gate=execution_hard_gate,
        select_threshold_lift=select_lift,
        near_miss_threshold_lift=near_miss_lift,
        effective_select_threshold=adjusted_select_threshold,
        effective_near_miss_threshold=adjusted_near_miss_threshold,
    )


def _resolve_breakout_trap_guard(
    input_data: Any,
    *,
    state: SnapshotSignalState,
    threshold_state: SnapshotThresholdState,
    clamp_unit_interval: Callable[[float], float],
) -> dict[str, Any]:
    market_state = dict(getattr(input_data, "market_state", {}) or {})
    regime_gate_level, style_dispersion, regime_flip_risk, regime_gate_reasons = _resolve_market_state_regime_context(market_state)
    breakout_pressure = clamp_unit_interval(max(threshold_state.breakout_freshness, threshold_state.trend_acceleration, threshold_state.volume_expansion_quality))
    close_retention_score = clamp_unit_interval((0.70 * state.close_strength) + (0.20 * state.layer_c_alignment) + (0.10 * (1.0 - state.analyst_penalty)))
    close_failure_gap = clamp_unit_interval(max(0.0, breakout_pressure - close_retention_score))
    stale_catalyst_pressure = clamp_unit_interval(max(0.0, 0.20 - threshold_state.catalyst_freshness) / 0.20)
    volatility_regime = float(state.volatility_metrics.get("volatility_regime", 0.0) or 0.0)
    atr_ratio = float(state.volatility_metrics.get("atr_ratio", 0.0) or 0.0)
    hostile_volatility = clamp_unit_interval(max((volatility_regime - 1.05) / 0.45, (atr_ratio - 0.065) / 0.045, state.volatility_strength - 0.65, 0.0))
    execution_quality_label = str(state.historical_prior.get("execution_quality_label") or "").strip()
    if execution_quality_label == "gap_chase_risk":
        historical_gap_chase_risk = 1.0
    elif execution_quality_label == "intraday_only":
        historical_gap_chase_risk = 0.6
    else:
        historical_gap_chase_risk = 0.0
    regime_pressure = clamp_unit_interval(max(regime_flip_risk, style_dispersion, 1.0 if regime_gate_level == "crisis" else 0.65 if regime_gate_level == "risk_off" else 0.0))
    enabled = breakout_pressure >= 0.35
    eligible = enabled and (close_failure_gap >= 0.15 or regime_pressure >= 0.58)
    breakout_trap_risk = (
        clamp_unit_interval(
            (0.30 * close_failure_gap)
            + (0.25 * regime_pressure)
            + (0.20 * stale_catalyst_pressure)
            + (0.15 * hostile_volatility)
            + (0.10 * historical_gap_chase_risk)
        )
        if eligible
        else 0.0
    )
    blocked = breakout_trap_risk >= BREAKOUT_TRAP_BLOCK_THRESHOLD
    execution_blocked = breakout_trap_risk >= BREAKOUT_TRAP_EXECUTION_BLOCK_THRESHOLD
    return {
        "enabled": enabled,
        "eligible": eligible,
        "applied": eligible and breakout_trap_risk > 0.0,
        "blocked": blocked,
        "execution_blocked": execution_blocked,
        "candidate_source": str(getattr(input_data, "replay_context", {}).get("source") or ""),
        "regime_gate_level": regime_gate_level,
        "regime_gate_reasons": regime_gate_reasons,
        "style_dispersion": round(float(style_dispersion), 4),
        "regime_flip_risk": round(float(regime_flip_risk), 4),
        "breakout_pressure": round(float(breakout_pressure), 4),
        "close_retention_score": round(float(close_retention_score), 4),
        "close_failure_gap": round(float(close_failure_gap), 4),
        "stale_catalyst_pressure": round(float(stale_catalyst_pressure), 4),
        "hostile_volatility": round(float(hostile_volatility), 4),
        "historical_gap_chase_risk": round(float(historical_gap_chase_risk), 4),
        "risk": round(float(breakout_trap_risk), 4),
        "penalty": round(float(BREAKOUT_TRAP_PENALTY_WEIGHT * breakout_trap_risk), 4),
        "block_threshold": round(float(BREAKOUT_TRAP_BLOCK_THRESHOLD), 4),
        "execution_block_threshold": round(float(BREAKOUT_TRAP_EXECUTION_BLOCK_THRESHOLD), 4),
        "gate_hits": {
            "breakout_pressure": breakout_pressure >= 0.35,
            "weak_close_retention": close_failure_gap >= 0.15,
            "stale_catalyst": stale_catalyst_pressure >= 0.35,
            "risk_off_regime": regime_pressure >= 0.58,
            "hostile_volatility": hostile_volatility >= 0.35,
            "historical_gap_chase": historical_gap_chase_risk >= 0.6,
        },
    }


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
        "momentum_strength": round(positive_score_weights.get("momentum_strength", 0.0) * state.momentum_strength, 4),
        "short_term_reversal": round(positive_score_weights.get("short_term_reversal", 0.0) * state.short_term_reversal, 4),
        "intraday_strength": round(positive_score_weights.get("intraday_strength", 0.0) * state.intraday_strength, 4),
        "reversal_2d": round(positive_score_weights.get("reversal_2d", 0.0) * state.reversal_2d, 4),
    }
    weighted_negative_contributions = {
        "stale_trend_repair_penalty": round(score_penalty_state.effective_stale_score_penalty_weight * score_penalty_state.stale_trend_repair_penalty, 4),
        "overhead_supply_penalty": round(profile.overhead_score_penalty_weight * score_penalty_state.overhead_supply_penalty, 4),
        "extension_without_room_penalty": round(score_penalty_state.effective_extension_score_penalty_weight * score_penalty_state.extension_without_room_penalty, 4),
        "breakout_trap_penalty": round(score_penalty_state.breakout_trap_penalty, 4),
        "layer_c_avoid_penalty": round(threshold_state.layer_c_avoid_penalty, 4),
        "watchlist_zero_catalyst_penalty": round(watchlist_penalty_state.effective_watchlist_zero_catalyst_penalty, 4),
        "watchlist_zero_catalyst_crowded_penalty": round(watchlist_penalty_state.effective_watchlist_zero_catalyst_crowded_penalty, 4),
        "watchlist_zero_catalyst_flat_trend_penalty": round(watchlist_penalty_state.effective_watchlist_zero_catalyst_flat_trend_penalty, 4),
    }
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
        + (positive_score_weights.get("momentum_strength", 0.0) * state.momentum_strength)
        + (positive_score_weights.get("short_term_reversal", 0.0) * state.short_term_reversal)
        + (positive_score_weights.get("intraday_strength", 0.0) * state.intraday_strength)
        + (positive_score_weights.get("reversal_2d", 0.0) * state.reversal_2d)
        - (score_penalty_state.effective_stale_score_penalty_weight * score_penalty_state.stale_trend_repair_penalty)
        - (profile.overhead_score_penalty_weight * score_penalty_state.overhead_supply_penalty)
        - (score_penalty_state.effective_extension_score_penalty_weight * score_penalty_state.extension_without_room_penalty)
        - score_penalty_state.breakout_trap_penalty
        - threshold_state.layer_c_avoid_penalty
        - watchlist_penalty_state.effective_watchlist_zero_catalyst_penalty
        - watchlist_penalty_state.effective_watchlist_zero_catalyst_crowded_penalty
        - watchlist_penalty_state.effective_watchlist_zero_catalyst_flat_trend_penalty
        - overbought_momentum_penalty
    )
    return {
        "weighted_positive_contributions": weighted_positive_contributions,
        "weighted_negative_contributions": weighted_negative_contributions,
        "total_positive_contribution": total_positive_contribution,
        "total_negative_contribution": total_negative_contribution,
        "overbought_momentum_penalty": round(overbought_momentum_penalty, 4),
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
        resolve_watchlist_zero_catalyst_penalty=resolve_watchlist_zero_catalyst_penalty,
        resolve_watchlist_zero_catalyst_crowded_penalty=resolve_watchlist_zero_catalyst_crowded_penalty,
        resolve_watchlist_zero_catalyst_flat_trend_penalty=resolve_watchlist_zero_catalyst_flat_trend_penalty,
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
    return SnapshotResolutionCoreState(
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
        effective_near_miss_threshold=float(market_state_threshold_adjustment["effective_near_miss_threshold"]),
        effective_select_threshold=float(market_state_threshold_adjustment["effective_select_threshold"]),
        layer_c_avoid_penalty=core_state.threshold_state.layer_c_avoid_penalty,
        market_state_threshold_adjustment=market_state_threshold_adjustment,
    )
    adjusted_score_penalty_state = ScorePenaltyState(
        profitability_hard_cliff_boundary_relief=core_state.score_penalty_state.profitability_hard_cliff_boundary_relief,
        stale_trend_repair_penalty=core_state.score_penalty_state.stale_trend_repair_penalty,
        overhead_supply_penalty=core_state.score_penalty_state.overhead_supply_penalty,
        extension_without_room_penalty=core_state.score_penalty_state.extension_without_room_penalty,
        breakout_trap_guard=core_state.score_penalty_state.breakout_trap_guard,
        breakout_trap_risk=core_state.score_penalty_state.breakout_trap_risk,
        breakout_trap_penalty=core_state.score_penalty_state.breakout_trap_penalty,
        effective_near_miss_threshold=float(market_state_threshold_adjustment["effective_near_miss_threshold"]),
        effective_stale_score_penalty_weight=core_state.score_penalty_state.effective_stale_score_penalty_weight,
        effective_extension_score_penalty_weight=core_state.score_penalty_state.effective_extension_score_penalty_weight,
    )
    selected_score_tolerance = resolve_selected_score_tolerance(
        score_target=core_state.score_payload["score_target"],
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
        score_payload=core_state.score_payload,
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
        "breakout_trap_guard": resolution.score_penalty_state.breakout_trap_guard,
        "breakout_trap_risk": resolution.score_penalty_state.breakout_trap_risk,
        "breakout_trap_penalty": resolution.score_penalty_state.breakout_trap_penalty,
        "positive_score_weights": resolution.positive_score_weights,
        "weighted_positive_contributions": resolution.score_payload["weighted_positive_contributions"],
        "weighted_negative_contributions": resolution.score_payload["weighted_negative_contributions"],
        "total_positive_contribution": resolution.score_payload["total_positive_contribution"],
        "total_negative_contribution": resolution.score_payload["total_negative_contribution"],
        "score_target": resolution.score_payload["score_target"],
        "selected_score_tolerance": resolution.selected_score_tolerance,
        "effective_near_miss_threshold": resolution.score_penalty_state.effective_near_miss_threshold,
        "effective_select_threshold": resolution.threshold_state.effective_select_threshold,
        "market_state_threshold_adjustment": resolution.threshold_state.market_state_threshold_adjustment,
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
        resolve_selected_score_tolerance=resolve_selected_score_tolerance,
    )
    return _build_short_trade_snapshot_reliefs_payload(resolution)
