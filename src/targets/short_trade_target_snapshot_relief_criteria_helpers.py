"""Relief criteria resolvers for short trade target snapshots.

Extracted from ``short_trade_target_snapshot_relief_helpers`` during the
R20.15 refactor.  The module groups the *criterion-level* decision
functions that decide whether and how much to lift thresholds, apply
penalties, or trigger guards given a market state / close-retention
profile / breakout-trap context.

Cohesive groups included here:

1. Market state regime context + threshold adjustment
2. Selected close retention adjustment + penalty
3. Breakout trap guard
4. Event catalyst threshold adjustments

The *orchestration* of these criteria into a final relief resolution
lives in :mod:`src.targets.short_trade_target_snapshot_relief_resolution_helpers`.
"""

from __future__ import annotations

from typing import Any

from src.screening.market_state_helpers import (
    BREADTH_RATIO_WEAK_FLOOR,
    CRISIS_BREADTH_FLOOR,
    CRISIS_POSITION_SCALE_FLOOR,
    POSITION_SCALE_WEAK_FLOOR,
    REGIME_FLIP_RISK_FLOOR,
)

from src.targets.short_trade_event_catalyst_helpers import build_event_catalyst_assessment
from src.targets.short_trade_target_snapshot_relief_models import (
    SnapshotSignalState,
    SnapshotThresholdState,
)
from src.targets.short_trade_target_prior_helpers import (
    resolve_btst_prior_shrinkage_p4_mode,
    resolve_effective_prior_metrics,
)

BREAKOUT_TRAP_PENALTY_WEIGHT = 0.10
BREAKOUT_TRAP_EXECUTION_BLOCK_THRESHOLD = 0.60
BREAKOUT_TRAP_BLOCK_THRESHOLD = 0.72


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_reason_codes(values: Any) -> list[str]:
    return [str(reason).strip() for reason in list(values or []) if str(reason or "").strip()]


def _normalized_reason_codes(values: Any) -> list[str]:
    return [str(reason) for reason in list(values or []) if str(reason or "").strip()]


def _resolve_market_state_regime_context(market_state: dict[str, Any]) -> tuple[str, float, float, list[str]]:
    payload = dict(market_state or {})
    btst_regime_gate_payload = payload.get("btst_regime_gate")
    if isinstance(btst_regime_gate_payload, dict):
        gate = str(btst_regime_gate_payload.get("gate") or "").strip().lower()
        metrics_payload = dict(btst_regime_gate_payload.get("metrics") or {})
        regime_gate_level = str(metrics_payload.get("regime_gate_level") or "").strip().lower()
        style_dispersion = _safe_float(metrics_payload.get("style_dispersion"))
        regime_flip_risk = _safe_float(metrics_payload.get("regime_flip_risk"))
        if gate in {"normal_trade", "aggressive_trade", "shadow_only", "halt"} and regime_gate_level in {"normal", "risk_off", "crisis"}:
            return (
                regime_gate_level,
                style_dispersion or 0.0,
                regime_flip_risk or 0.0,
                _safe_reason_codes(btst_regime_gate_payload.get("reason_codes")) or _safe_reason_codes(payload.get("regime_gate_reasons")),
            )
    breadth_ratio = _safe_float(payload.get("breadth_ratio"))
    position_scale = _safe_float(payload.get("position_scale"))
    regime_flip_risk = _safe_float(payload.get("regime_flip_risk")) or 0.0
    style_dispersion = _safe_float(payload.get("style_dispersion")) or 0.0
    regime_gate_level = str(payload.get("regime_gate_level") or "").strip().lower()
    regime_gate_reasons = _safe_reason_codes(payload.get("regime_gate_reasons"))
    if regime_gate_level not in {"normal", "risk_off", "crisis"}:
        crisis = (breadth_ratio is not None and breadth_ratio <= CRISIS_BREADTH_FLOOR) or (position_scale is not None and position_scale <= CRISIS_POSITION_SCALE_FLOOR)
        risk_off = crisis or (breadth_ratio is not None and breadth_ratio <= BREADTH_RATIO_WEAK_FLOOR) or (position_scale is not None and position_scale <= POSITION_SCALE_WEAK_FLOOR) or regime_flip_risk >= REGIME_FLIP_RISK_FLOOR
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


def _build_selected_close_retention_adjustment(
    *,
    enabled: bool,
    close_retention_score: float,
    breakout_close_gap: float,
    close_retention_floor: float,
    breakout_close_gap_max: float,
    select_threshold_lift: float,
    effective_select_threshold: float,
    effective_near_miss_threshold: float,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "close_retention_score": round(float(close_retention_score), 4),
        "breakout_close_gap": round(float(breakout_close_gap), 4),
        "close_retention_floor": round(float(close_retention_floor), 4),
        "breakout_close_gap_max": round(float(breakout_close_gap_max), 4),
        "close_retention_weak": bool(enabled and close_retention_score < close_retention_floor),
        "breakout_close_gap_excessive": bool(enabled and breakout_close_gap > breakout_close_gap_max),
        "select_threshold_lift": round(float(select_threshold_lift), 4),
        "effective_select_threshold": round(float(effective_select_threshold), 4),
        "effective_near_miss_threshold": round(float(effective_near_miss_threshold), 4),
    }


def _build_selected_close_retention_penalty(
    *,
    enabled: bool,
    applied: bool,
    weight: float,
    close_shortfall: float,
    breakout_close_gap_excess: float,
    severity: float,
    penalty: float,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "applied": bool(applied),
        "weight": round(float(weight), 4),
        "close_shortfall": round(float(close_shortfall), 4),
        "breakout_close_gap_excess": round(float(breakout_close_gap_excess), 4),
        "severity": round(float(severity), 4),
        "penalty": round(float(penalty), 4),
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

    # Round 89 Task 3: 分级仓位 — 温和危机豁免执行封锁
    # 数据支持: HALT 日 near_miss 股票胜率=56%(+2.31%); Breadth≥25% 危机日 near_miss 胜率=68%(+3.29%)
    # Breadth≥25% 说明超过1/4股票上涨，不是真正的系统性崩溃，允许执行但保持危机仓位压缩(12%/5%)
    # Breadth<25% 危机: 保持全封锁; risk_off: 仍封锁(历史数据不足，保守处理)
    _MILD_CRISIS_BREADTH_THRESHOLD = 0.25
    mild_crisis_override = (
        risk_level == "crisis"
        and breadth_ratio is not None
        and breadth_ratio >= _MILD_CRISIS_BREADTH_THRESHOLD
    )
    execution_hard_gate = risk_level in {"risk_off", "crisis"} and not mild_crisis_override
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


def _resolve_selected_close_retention_adjustment(
    *,
    profile: Any,
    state: SnapshotSignalState,
    breakout_trap_guard: dict[str, Any],
    effective_select_threshold: float,
    effective_near_miss_threshold: float,
    clamp_unit_interval,
) -> dict[str, Any]:
    close_retention_floor = max(0.0, float(getattr(profile, "selected_close_retention_min", 0.0) or 0.0))
    breakout_close_gap_max = min(1.0, max(0.0, float(getattr(profile, "selected_breakout_close_gap_max", 1.0) if getattr(profile, "selected_breakout_close_gap_max", 1.0) is not None else 1.0)))
    close_retention_lift = max(0.0, float(getattr(profile, "selected_close_retention_threshold_lift", 0.0) or 0.0))
    breakout_close_gap_lift = max(0.0, float(getattr(profile, "selected_breakout_close_gap_threshold_lift", 0.0) or 0.0))
    enabled = close_retention_lift > 0.0 or breakout_close_gap_lift > 0.0
    if resolve_btst_prior_shrinkage_p4_mode() == "enforce":
        effective_prior_metrics = resolve_effective_prior_metrics(state.historical_prior)
        calibrated_next_close_positive_rate = clamp_unit_interval(float(effective_prior_metrics.get("next_close_positive_rate", 0.0) or 0.0))
    else:
        calibrated_next_close_positive_rate = clamp_unit_interval(float(state.historical_prior.get("calibrated_next_close_positive_rate", state.historical_prior.get("next_close_positive_rate", 0.0)) or 0.0))
    trap_close_retention_score = clamp_unit_interval(float(breakout_trap_guard.get("close_retention_score", 0.0) or 0.0))
    close_retention_score = clamp_unit_interval((0.85 * trap_close_retention_score) + (0.15 * calibrated_next_close_positive_rate))
    breakout_close_gap = clamp_unit_interval(
        max(
            0.0,
            float(breakout_trap_guard.get("close_failure_gap", 0.0) or 0.0),
            float(breakout_trap_guard.get("breakout_pressure", 0.0) or 0.0) - close_retention_score,
        )
    )
    select_threshold_lift = 0.0
    if enabled and close_retention_score < close_retention_floor:
        select_threshold_lift += close_retention_lift
    if enabled and breakout_close_gap > breakout_close_gap_max:
        select_threshold_lift += breakout_close_gap_lift

    adjusted_select_threshold = min(0.95, float(effective_select_threshold) + float(select_threshold_lift))
    adjusted_near_miss_threshold = min(adjusted_select_threshold, float(effective_near_miss_threshold))
    return _build_selected_close_retention_adjustment(
        enabled=enabled,
        close_retention_score=close_retention_score,
        breakout_close_gap=breakout_close_gap,
        close_retention_floor=close_retention_floor,
        breakout_close_gap_max=breakout_close_gap_max,
        select_threshold_lift=select_threshold_lift,
        effective_select_threshold=adjusted_select_threshold,
        effective_near_miss_threshold=adjusted_near_miss_threshold,
    )


def _resolve_selected_close_retention_penalty(*, profile: Any, selected_close_retention_adjustment: dict[str, Any]) -> dict[str, Any]:
    weight = max(0.0, float(getattr(profile, "selected_close_retention_penalty_weight", 0.0) or 0.0))
    close_shortfall = max(
        0.0,
        float(selected_close_retention_adjustment.get("close_retention_floor", 0.0) or 0.0) - float(selected_close_retention_adjustment.get("close_retention_score", 0.0) or 0.0),
    )
    # NOTE: breakout_close_gap_max = 0 是合法值 (零容忍 gap), 不能用 `or 1.0` 静默覆盖。
    _bcg_raw = selected_close_retention_adjustment.get("breakout_close_gap", 0.0)
    _bcgm_raw = selected_close_retention_adjustment.get("breakout_close_gap_max", 1.0)
    _bcg = float(_bcg_raw) if _bcg_raw is not None else 0.0
    _bcgm = float(_bcgm_raw) if _bcgm_raw is not None else 1.0
    breakout_close_gap_excess = max(
        0.0,
        _bcg - _bcgm,
    )
    severity = min(1.0, (close_shortfall / 0.12) + (breakout_close_gap_excess / 0.10))
    penalty = min(weight, weight * severity)
    return _build_selected_close_retention_penalty(
        enabled=weight > 0.0,
        applied=penalty > 0.0,
        weight=weight,
        close_shortfall=close_shortfall,
        breakout_close_gap_excess=breakout_close_gap_excess,
        severity=severity,
        penalty=penalty,
    )


def _resolve_breakout_trap_guard(
    input_data: Any,
    *,
    state: SnapshotSignalState,
    threshold_state: SnapshotThresholdState,
    clamp_unit_interval,
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
    breakout_trap_risk = clamp_unit_interval((0.30 * close_failure_gap) + (0.25 * regime_pressure) + (0.20 * stale_catalyst_pressure) + (0.15 * hostile_volatility) + (0.10 * historical_gap_chase_risk)) if eligible else 0.0
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


def _apply_event_catalyst_threshold_adjustments(
    *,
    input_data: Any,
    profile: Any,
    state: SnapshotSignalState,
    threshold_state: SnapshotThresholdState,
    score_penalty_state,
) -> SnapshotThresholdState:
    """Apply event catalyst assessment with real penalty values and adjust thresholds.

    This function is called after score penalties are computed, ensuring that
    the event catalyst safety gates see the real penalty values rather than
    hardcoded zeros.

    Args:
        input_data: Input data with replay context
        profile: Target profile with event_catalyst_* configuration
        state: Signal state with raw features
        threshold_state: Threshold state with base thresholds (pre-event-catalyst)
        score_penalty_state: Penalty state with computed penalty values

    Returns:
        Updated threshold state with event catalyst assessment and adjusted thresholds
    """
    # Build snapshot with real penalty values
    snapshot_for_event_catalyst = {
        "breakout_freshness": threshold_state.breakout_freshness,
        "trend_acceleration": threshold_state.trend_acceleration,
        "volume_expansion_quality": threshold_state.volume_expansion_quality,
        "catalyst_freshness": threshold_state.catalyst_freshness,
        "close_strength": state.close_strength,
        "sector_resonance": state.sector_resonance,
        "extension_without_room_penalty": score_penalty_state.extension_without_room_penalty,
        "stale_trend_repair_penalty": score_penalty_state.stale_trend_repair_penalty,
        "overhead_supply_penalty": score_penalty_state.overhead_supply_penalty,
    }

    event_catalyst_assessment_result = build_event_catalyst_assessment(
        snapshot=snapshot_for_event_catalyst,
        profile=profile,
        candidate_source=str(input_data.replay_context.get("source") or input_data.replay_context.get("candidate_source") or ""),
        candidate_reason_codes=set(_normalized_reason_codes(input_data.replay_context.get("candidate_reason_codes"))),
    )

    # Apply threshold adjustments
    effective_select_threshold = max(0.0, threshold_state.effective_select_threshold - event_catalyst_assessment_result.selected_uplift)
    effective_near_miss_threshold = max(0.0, threshold_state.effective_near_miss_threshold - event_catalyst_assessment_result.near_miss_threshold_relief)

    event_catalyst_assessment = {
        "score": event_catalyst_assessment_result.score,
        "eligible": event_catalyst_assessment_result.eligible,
        "selected_uplift": event_catalyst_assessment_result.selected_uplift,
        "near_miss_threshold_relief": event_catalyst_assessment_result.near_miss_threshold_relief,
        "gate_hits": dict(event_catalyst_assessment_result.gate_hits),
        "component_scores": dict(event_catalyst_assessment_result.component_scores),
        "candidate_reason_codes": list(event_catalyst_assessment_result.candidate_reason_codes),
    }

    # Return updated threshold state with event catalyst applied
    return SnapshotThresholdState(
        profitability_relief=threshold_state.profitability_relief,
        catalyst_relief=threshold_state.catalyst_relief,
        visibility_gap_continuation_relief=threshold_state.visibility_gap_continuation_relief,
        merge_approved_continuation_relief=threshold_state.merge_approved_continuation_relief,
        historical_execution_relief=threshold_state.historical_execution_relief,
        prepared_breakout_selected_catalyst_relief=threshold_state.prepared_breakout_selected_catalyst_relief,
        breakout_freshness=threshold_state.breakout_freshness,
        trend_acceleration=threshold_state.trend_acceleration,
        volume_expansion_quality=threshold_state.volume_expansion_quality,
        catalyst_freshness=threshold_state.catalyst_freshness,
        effective_near_miss_threshold=effective_near_miss_threshold,
        effective_select_threshold=effective_select_threshold,
        layer_c_avoid_penalty=threshold_state.layer_c_avoid_penalty,
        market_state_threshold_adjustment=threshold_state.market_state_threshold_adjustment,
        selected_close_retention_adjustment=threshold_state.selected_close_retention_adjustment,
        event_catalyst_assessment=event_catalyst_assessment,
    )
