from __future__ import annotations

from typing import Any

from src.execution.models import LayerCResult
from src.screening.models import StrategySignal
from src.targets.explainability import clamp_unit_interval, derive_confidence, trim_reasons
from src.targets.models import TargetEvaluationInput, TargetEvaluationResult
from src.targets.profiles import get_active_short_trade_target_profile, use_short_trade_target_profile

STRONG_CARRYOVER_SELECTED_SCORE_TOLERANCE = 0.001


def _normalize_score(value: float) -> float:
    return clamp_unit_interval((float(value or 0.0) + 1.0) / 2.0)


def _load_signal(payload: Any) -> StrategySignal | None:
    if isinstance(payload, StrategySignal):
        return payload
    if isinstance(payload, dict) and payload:
        try:
            return StrategySignal.model_validate(payload)
        except Exception:
            return None
    return None


def _signal_signed_strength(signal: StrategySignal | None) -> float:
    if signal is None:
        return 0.0
    return max(-1.0, min(1.0, float(signal.direction) * (float(signal.confidence) / 100.0) * float(signal.completeness)))


def _positive_strength(signal: StrategySignal | None) -> float:
    return clamp_unit_interval(max(0.0, _signal_signed_strength(signal)))


def _subfactor_signed_strength(signal: StrategySignal | None, name: str) -> float:
    if signal is None:
        return 0.0
    snapshot = signal.sub_factors.get(name, {}) if isinstance(signal.sub_factors, dict) else {}
    if not isinstance(snapshot, dict):
        return 0.0
    direction = float(snapshot.get("direction", 0.0) or 0.0)
    confidence = float(snapshot.get("confidence", 0.0) or 0.0)
    completeness = float(snapshot.get("completeness", 1.0) or 1.0)
    return max(-1.0, min(1.0, direction * (confidence / 100.0) * completeness))


def _subfactor_positive_strength(signal: StrategySignal | None, name: str) -> float:
    return clamp_unit_interval(max(0.0, _subfactor_signed_strength(signal, name)))


def _subfactor_metrics(signal: StrategySignal | None, name: str) -> dict[str, Any]:
    if signal is None:
        return {}
    snapshot = signal.sub_factors.get(name, {}) if isinstance(signal.sub_factors, dict) else {}
    if not isinstance(snapshot, dict):
        return {}
    metrics = snapshot.get("metrics", {})
    return metrics if isinstance(metrics, dict) else {}


def _normalize_positive_score_weights(configured_weights: dict[str, float]) -> dict[str, float]:
    total_weight = sum(max(0.0, value) for value in configured_weights.values())
    if total_weight <= 0:
        unit_weight = round(1.0 / len(configured_weights), 4)
        return {name: unit_weight for name in configured_weights}
    return {name: max(0.0, value) / total_weight for name, value in configured_weights.items()}


def _profitability_snapshot(signal: StrategySignal | None) -> dict[str, Any]:
    if signal is None or not isinstance(signal.sub_factors, dict):
        return {}
    snapshot = signal.sub_factors.get("profitability", {})
    return snapshot if isinstance(snapshot, dict) else {}


def _historical_prior(input_data: TargetEvaluationInput) -> dict[str, Any]:
    return dict(input_data.replay_context.get("historical_prior") or {})


def _resolve_carryover_evidence_deficiency(input_data: TargetEvaluationInput) -> dict[str, Any]:
    historical_prior = _historical_prior(input_data)
    source = str(input_data.replay_context.get("source") or "").strip()
    candidate_reason_codes = {
        str(code).strip()
        for code in list(input_data.replay_context.get("candidate_reason_codes") or [])
        if str(code or "").strip()
    }
    same_ticker_sample_count = int(historical_prior.get("same_ticker_sample_count") or 0)
    same_family_sample_count = int(historical_prior.get("same_family_sample_count") or 0)
    same_family_source_sample_count = int(historical_prior.get("same_family_source_sample_count") or 0)
    same_family_source_score_catalyst_sample_count = int(historical_prior.get("same_family_source_score_catalyst_sample_count") or 0)
    same_source_score_sample_count = int(historical_prior.get("same_source_score_sample_count") or 0)
    evaluable_count = int(historical_prior.get("evaluable_count") or 0)

    gate_hits = {
        "candidate_source": source == "catalyst_theme",
        "carryover_candidate": "catalyst_theme_short_trade_carryover_candidate" in candidate_reason_codes,
        "execution_quality_label": str(historical_prior.get("execution_quality_label") or "") == "close_continuation",
        "entry_timing_bias": str(historical_prior.get("entry_timing_bias") or "") == "confirm_then_hold",
        "low_same_ticker_samples": same_ticker_sample_count < 2,
        "low_evaluable_count": evaluable_count <= 1,
        "broad_family_only": same_family_sample_count > 0,
        "no_same_family_source": same_family_source_sample_count == 0,
        "no_same_family_source_score_catalyst": same_family_source_score_catalyst_sample_count == 0,
        "no_same_source_score": same_source_score_sample_count == 0,
    }
    return {
        "enabled": bool(historical_prior),
        "evidence_deficient": all(gate_hits.values()),
        "gate_hits": gate_hits,
        "same_ticker_sample_count": same_ticker_sample_count,
        "same_family_sample_count": same_family_sample_count,
        "same_family_source_sample_count": same_family_source_sample_count,
        "same_family_source_score_catalyst_sample_count": same_family_source_score_catalyst_sample_count,
        "same_source_score_sample_count": same_source_score_sample_count,
        "evaluable_count": evaluable_count,
    }


def _preferred_entry_mode_from_historical_prior(historical_prior: dict[str, Any] | None) -> str:
    execution_quality_label = str((historical_prior or {}).get("execution_quality_label") or "unknown")
    if execution_quality_label == "intraday_only":
        return "intraday_confirmation_only"
    if execution_quality_label == "gap_chase_risk":
        return "avoid_open_chase_confirmation"
    if execution_quality_label == "close_continuation":
        return "confirm_then_hold_breakout"
    if execution_quality_label == "zero_follow_through":
        return "strong_reconfirmation_only"
    return "next_day_breakout_confirmation"


def _resolve_selected_score_tolerance(
    *,
    score_target: float,
    effective_select_threshold: float,
    upstream_shadow_catalyst_relief_applied: bool,
    upstream_shadow_catalyst_relief_reason: str,
    historical_prior: dict[str, Any],
) -> float:
    gap_to_selected = float(effective_select_threshold) - float(score_target)
    if gap_to_selected <= 0.0:
        return 0.0
    if not upstream_shadow_catalyst_relief_applied:
        return 0.0
    if upstream_shadow_catalyst_relief_reason != "catalyst_theme_short_trade_carryover":
        return 0.0
    if str(historical_prior.get("execution_quality_label") or "") != "close_continuation":
        return 0.0
    if str(historical_prior.get("entry_timing_bias") or "") != "confirm_then_hold":
        return 0.0
    return STRONG_CARRYOVER_SELECTED_SCORE_TOLERANCE if gap_to_selected <= STRONG_CARRYOVER_SELECTED_SCORE_TOLERANCE else 0.0


def _resolve_profitability_relief(
    *,
    input_data: TargetEvaluationInput,
    fundamental_signal: StrategySignal | None,
    breakout_freshness: float,
    catalyst_freshness: float,
    sector_resonance: float,
    profile: Any,
) -> dict[str, Any]:
    profitability = _profitability_snapshot(fundamental_signal)
    profitability_metrics = profitability.get("metrics", {}) if isinstance(profitability.get("metrics", {}), dict) else {}
    positive_count_raw = profitability_metrics.get("positive_count")
    try:
        profitability_positive_count = int(positive_count_raw) if positive_count_raw is not None else None
    except (TypeError, ValueError):
        profitability_positive_count = None
    profitability_confidence = float(profitability.get("confidence", 0.0) or 0.0)
    hard_cliff = profitability.get("direction") == -1 and profitability_positive_count == 0

    base_layer_c_avoid_penalty = float(profile.layer_c_avoid_penalty) if input_data.layer_c_decision == "avoid" else 0.0
    relief_gate_hits = {
        "breakout_freshness": breakout_freshness >= float(profile.profitability_relief_breakout_freshness_min),
        "catalyst_freshness": catalyst_freshness >= float(profile.profitability_relief_catalyst_freshness_min),
        "sector_resonance": sector_resonance >= float(profile.profitability_relief_sector_resonance_min),
    }
    relief_eligible = (
        bool(profile.profitability_relief_enabled)
        and input_data.layer_c_decision == "avoid"
        and hard_cliff
        and all(relief_gate_hits.values())
    )
    effective_avoid_penalty = base_layer_c_avoid_penalty
    if relief_eligible and base_layer_c_avoid_penalty > 0:
        effective_avoid_penalty = min(base_layer_c_avoid_penalty, float(profile.profitability_relief_avoid_penalty))

    return {
        "hard_cliff": hard_cliff,
        "profitability_direction": int(profitability.get("direction", 0) or 0),
        "profitability_positive_count": profitability_positive_count,
        "profitability_confidence": profitability_confidence,
        "relief_enabled": bool(profile.profitability_relief_enabled),
        "relief_gate_hits": relief_gate_hits,
        "relief_eligible": relief_eligible,
        "relief_applied": relief_eligible and effective_avoid_penalty < base_layer_c_avoid_penalty,
        "base_layer_c_avoid_penalty": base_layer_c_avoid_penalty,
        "effective_avoid_penalty": effective_avoid_penalty,
        "soft_penalty": float(profile.profitability_relief_avoid_penalty),
        "metrics": profitability_metrics,
    }


def _resolve_profitability_hard_cliff_boundary_relief(
    *,
    input_data: TargetEvaluationInput,
    profitability_hard_cliff: bool,
    breakout_freshness: float,
    trend_acceleration: float,
    catalyst_freshness: float,
    sector_resonance: float,
    close_strength: float,
    stale_trend_repair_penalty: float,
    extension_without_room_penalty: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    base_near_miss_threshold = float(profile.near_miss_threshold)
    near_miss_threshold_override = float(profile.profitability_hard_cliff_boundary_relief_near_miss_threshold)
    default_result = {
        "enabled": bool(profile.profitability_hard_cliff_boundary_relief_enabled),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "gate_hits": {},
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": base_near_miss_threshold,
        "near_miss_threshold_override": base_near_miss_threshold,
        "reason": "profitability_hard_cliff_boundary_relief",
    }
    if not bool(profile.profitability_hard_cliff_boundary_relief_enabled):
        return default_result

    gate_hits = {
        "candidate_source": source == "short_trade_boundary",
        "profitability_hard_cliff": profitability_hard_cliff,
        "layer_c_decision": input_data.layer_c_decision != "avoid",
        "breakout_freshness": breakout_freshness >= float(profile.profitability_hard_cliff_boundary_relief_breakout_freshness_min),
        "trend_acceleration": trend_acceleration >= float(profile.profitability_hard_cliff_boundary_relief_trend_acceleration_min),
        "catalyst_freshness": catalyst_freshness >= float(profile.profitability_hard_cliff_boundary_relief_catalyst_freshness_min),
        "sector_resonance": sector_resonance >= float(profile.profitability_hard_cliff_boundary_relief_sector_resonance_min),
        "close_strength": close_strength >= float(profile.profitability_hard_cliff_boundary_relief_close_strength_min),
        "stale_trend_repair_penalty": stale_trend_repair_penalty <= float(profile.profitability_hard_cliff_boundary_relief_stale_penalty_max),
        "extension_without_room_penalty": extension_without_room_penalty <= float(profile.profitability_hard_cliff_boundary_relief_extension_penalty_max),
    }
    eligible = all(gate_hits.values())
    effective_near_miss_threshold = base_near_miss_threshold
    if eligible:
        effective_near_miss_threshold = min(base_near_miss_threshold, near_miss_threshold_override)

    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and effective_near_miss_threshold < base_near_miss_threshold,
        "candidate_source": source,
        "gate_hits": gate_hits,
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": effective_near_miss_threshold,
        "near_miss_threshold_override": near_miss_threshold_override,
        "reason": "profitability_hard_cliff_boundary_relief",
    }


def _resolve_historical_execution_relief(
    *,
    input_data: TargetEvaluationInput,
    profitability_hard_cliff: bool,
    profile: Any,
) -> dict[str, Any]:
    historical_prior = _historical_prior(input_data)
    source = str(input_data.replay_context.get("source") or "").strip()
    candidate_reason_codes = {
        str(code).strip()
        for code in list(input_data.replay_context.get("candidate_reason_codes") or [])
        if str(code or "").strip()
    }
    catalyst_theme_carryover_candidate = source == "catalyst_theme" and "catalyst_theme_short_trade_carryover_candidate" in candidate_reason_codes
    base_near_miss_threshold = float(profile.near_miss_threshold)
    base_select_threshold = float(profile.select_threshold)
    execution_quality_label = str(historical_prior.get("execution_quality_label") or "unknown")
    evaluable_count = int(historical_prior.get("evaluable_count") or 0)
    next_close_positive_rate = clamp_unit_interval(float(historical_prior.get("next_close_positive_rate", 0.0) or 0.0))
    next_high_hit_rate = clamp_unit_interval(float(historical_prior.get("next_high_hit_rate_at_threshold", 0.0) or 0.0))
    next_open_to_close_return_mean = float(historical_prior.get("next_open_to_close_return_mean", 0.0) or 0.0)
    default_result = {
        "enabled": bool(historical_prior),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "execution_quality_label": execution_quality_label,
        "evaluable_count": evaluable_count,
        "next_close_positive_rate": next_close_positive_rate,
        "next_high_hit_rate_at_threshold": next_high_hit_rate,
        "next_open_to_close_return_mean": next_open_to_close_return_mean,
        "strong_close_continuation": False,
        "gate_hits": {},
        "reason": "historical_execution_relief",
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": base_near_miss_threshold,
        "near_miss_threshold_override": base_near_miss_threshold,
        "base_select_threshold": base_select_threshold,
        "effective_select_threshold": base_select_threshold,
        "select_threshold_override": base_select_threshold,
    }
    if not historical_prior:
        return default_result

    strong_close_continuation_candidate = (
        execution_quality_label == "close_continuation"
        and evaluable_count >= 2
        and next_close_positive_rate >= 0.8
        and next_high_hit_rate >= 0.8
        and next_open_to_close_return_mean >= 0.02
    )
    execution_quality_support = execution_quality_label in {"gap_chase_risk", "close_continuation"}
    if catalyst_theme_carryover_candidate:
        execution_quality_support = execution_quality_label == "close_continuation"
    if profitability_hard_cliff and execution_quality_label == "gap_chase_risk":
        execution_quality_support = execution_quality_support and next_open_to_close_return_mean >= 0.0

    gate_hits = {
        "candidate_source": source in {"short_trade_boundary", "upstream_liquidity_corridor_shadow", "post_gate_liquidity_competition_shadow"} or catalyst_theme_carryover_candidate,
        "profitability_hard_cliff": profitability_hard_cliff,
        "evaluable_count": evaluable_count >= 3 or strong_close_continuation_candidate,
        "execution_quality_support": execution_quality_support,
        "gap_chase_open_to_close_support": (not profitability_hard_cliff) or execution_quality_label != "gap_chase_risk" or next_open_to_close_return_mean >= 0.0,
        "next_close_positive_rate": next_close_positive_rate >= 0.5,
        "next_high_hit_rate": next_high_hit_rate >= 0.5,
    }
    eligible = all(gate_hits.values())
    strong_close_continuation = strong_close_continuation_candidate and eligible
    near_miss_threshold_override = base_near_miss_threshold
    select_threshold_override = base_select_threshold
    if eligible:
        near_miss_threshold_override = min(
            base_near_miss_threshold,
            0.39 if (execution_quality_label == "gap_chase_risk" and not catalyst_theme_carryover_candidate) or strong_close_continuation else 0.40,
        )
        if strong_close_continuation:
            select_threshold_override = min(base_select_threshold, 0.56)

    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and (
            near_miss_threshold_override < base_near_miss_threshold
            or select_threshold_override < base_select_threshold
        ),
        "candidate_source": source,
        "execution_quality_label": execution_quality_label,
        "evaluable_count": evaluable_count,
        "next_close_positive_rate": next_close_positive_rate,
        "next_high_hit_rate_at_threshold": next_high_hit_rate,
        "next_open_to_close_return_mean": next_open_to_close_return_mean,
        "strong_close_continuation": strong_close_continuation,
        "gate_hits": gate_hits,
        "reason": "historical_execution_relief",
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": near_miss_threshold_override,
        "near_miss_threshold_override": near_miss_threshold_override,
        "base_select_threshold": base_select_threshold,
        "effective_select_threshold": select_threshold_override,
        "select_threshold_override": select_threshold_override,
    }


def _resolve_upstream_shadow_catalyst_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    catalyst_freshness: float,
    profitability_hard_cliff: bool,
    profile: Any,
) -> dict[str, Any]:
    relief_payload = input_data.replay_context.get("short_trade_catalyst_relief")
    relief_config = dict(relief_payload) if isinstance(relief_payload, dict) else {}
    relief_reason = str(relief_config.get("reason") or "upstream_shadow_catalyst_relief")
    historical_prior = _historical_prior(input_data)
    historical_execution_quality_label = str(historical_prior.get("execution_quality_label") or "unknown")
    historical_entry_timing_bias = str(historical_prior.get("entry_timing_bias") or "unknown")
    historical_evaluable_count = int(historical_prior.get("evaluable_count") or 0)
    historical_next_close_positive_rate = clamp_unit_interval(float(historical_prior.get("next_close_positive_rate", 0.0) or 0.0))
    historical_next_high_hit_rate = clamp_unit_interval(float(historical_prior.get("next_high_hit_rate_at_threshold", 0.0) or 0.0))
    historical_next_open_to_close_return_mean = float(historical_prior.get("next_open_to_close_return_mean", 0.0) or 0.0)
    base_near_miss_threshold = float(profile.near_miss_threshold)
    base_select_threshold = float(profile.select_threshold)
    default_result = {
        "enabled": False,
        "eligible": False,
        "applied": False,
        "reason": relief_reason,
        "gate_hits": {},
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": catalyst_freshness,
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": base_near_miss_threshold,
        "base_select_threshold": base_select_threshold,
        "effective_select_threshold": base_select_threshold,
        "catalyst_freshness_floor": 0.0,
        "near_miss_threshold_override": base_near_miss_threshold,
        "select_threshold_override": base_select_threshold,
        "require_no_profitability_hard_cliff": False,
        "historical_execution_quality_label": historical_execution_quality_label,
        "historical_evaluable_count": historical_evaluable_count,
        "historical_next_close_positive_rate": historical_next_close_positive_rate,
        "historical_next_high_hit_rate_at_threshold": historical_next_high_hit_rate,
        "historical_next_open_to_close_return_mean": historical_next_open_to_close_return_mean,
        "historical_strong_close_continuation": False,
    }

    candidate_reason_codes = {
        str(code).strip()
        for code in list(input_data.replay_context.get("candidate_reason_codes") or [])
        if str(code or "").strip()
    }
    if not relief_config or not (candidate_reason_codes & {"upstream_shadow_release_candidate", "catalyst_theme_short_trade_carryover_candidate"}):
        return default_result

    enabled = bool(relief_config.get("enabled", True))
    if not enabled:
        return {**default_result, "reason": relief_reason}

    catalyst_freshness_floor = clamp_unit_interval(float(relief_config.get("catalyst_freshness_floor", 0.0) or 0.0))
    near_miss_threshold_override = clamp_unit_interval(float(relief_config.get("near_miss_threshold", base_near_miss_threshold) or base_near_miss_threshold))
    select_threshold_override = clamp_unit_interval(float(relief_config.get("selected_threshold", base_select_threshold) or base_select_threshold))
    breakout_freshness_min = clamp_unit_interval(float(relief_config.get("breakout_freshness_min", 0.0) or 0.0))
    trend_acceleration_min = clamp_unit_interval(float(relief_config.get("trend_acceleration_min", 0.0) or 0.0))
    close_strength_min = clamp_unit_interval(float(relief_config.get("close_strength_min", 0.0) or 0.0))
    require_no_profitability_hard_cliff = bool(relief_config.get("require_no_profitability_hard_cliff", False))
    carryover_history_supported = True
    required_execution_quality_labels = {
        str(label).strip()
        for label in list(relief_config.get("required_execution_quality_labels") or [])
        if str(label or "").strip()
    }
    min_historical_evaluable_count = int(relief_config.get("min_historical_evaluable_count", 0) or 0)
    min_historical_next_close_positive_rate = float(relief_config.get("min_historical_next_close_positive_rate", 0.0) or 0.0)
    min_historical_next_open_to_close_return_mean = float(
        relief_config.get("min_historical_next_open_to_close_return_mean", -1.0) or -1.0
    )
    if relief_reason == "catalyst_theme_short_trade_carryover":
        carryover_history_supported = (
            historical_execution_quality_label == "close_continuation"
            and historical_entry_timing_bias == "confirm_then_hold"
            and historical_evaluable_count >= 2
            and historical_next_close_positive_rate >= 0.5
        )
    carryover_strong_close_continuation = (
        relief_reason == "catalyst_theme_short_trade_carryover"
        and historical_execution_quality_label == "close_continuation"
        and historical_evaluable_count >= 2
        and historical_next_close_positive_rate >= 0.8
        and historical_next_high_hit_rate >= 0.8
        and historical_next_open_to_close_return_mean >= 0.02
    )
    upstream_shadow_history_supported = True
    if relief_reason == "upstream_shadow_catalyst_relief" and required_execution_quality_labels:
        upstream_shadow_history_supported = (
            historical_execution_quality_label in required_execution_quality_labels
            and historical_evaluable_count >= min_historical_evaluable_count
            and historical_next_close_positive_rate >= min_historical_next_close_positive_rate
            and historical_next_open_to_close_return_mean >= min_historical_next_open_to_close_return_mean
        )

    gate_hits = {
        "breakout_freshness": breakout_freshness >= breakout_freshness_min,
        "trend_acceleration": trend_acceleration >= trend_acceleration_min,
        "close_strength": close_strength >= close_strength_min,
        "no_profitability_hard_cliff": (not require_no_profitability_hard_cliff) or (not profitability_hard_cliff),
        **({"historical_continuation_quality": carryover_history_supported} if relief_reason == "catalyst_theme_short_trade_carryover" else {}),
        **({"historical_continuation_quality": upstream_shadow_history_supported} if relief_reason == "upstream_shadow_catalyst_relief" and required_execution_quality_labels else {}),
    }
    eligible = all(gate_hits.values())
    effective_catalyst_freshness = catalyst_freshness
    effective_near_miss_threshold = base_near_miss_threshold
    effective_select_threshold = base_select_threshold
    if eligible:
        effective_catalyst_freshness = max(catalyst_freshness, catalyst_freshness_floor)
        effective_near_miss_threshold = min(base_near_miss_threshold, near_miss_threshold_override)
        effective_select_threshold = min(base_select_threshold, select_threshold_override)
        if carryover_strong_close_continuation:
            effective_select_threshold = min(effective_select_threshold, 0.45)

    applied = eligible and (
        effective_catalyst_freshness > catalyst_freshness
        or effective_near_miss_threshold < base_near_miss_threshold
        or effective_select_threshold < base_select_threshold
    )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": applied,
        "reason": relief_reason,
        "gate_hits": gate_hits,
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": effective_catalyst_freshness,
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": effective_near_miss_threshold,
        "base_select_threshold": base_select_threshold,
        "effective_select_threshold": effective_select_threshold,
        "catalyst_freshness_floor": catalyst_freshness_floor,
        "near_miss_threshold_override": near_miss_threshold_override,
        "select_threshold_override": select_threshold_override,
        "require_no_profitability_hard_cliff": require_no_profitability_hard_cliff,
        "historical_execution_quality_label": historical_execution_quality_label,
        "historical_evaluable_count": historical_evaluable_count,
        "historical_next_close_positive_rate": historical_next_close_positive_rate,
        "historical_next_high_hit_rate_at_threshold": historical_next_high_hit_rate,
        "historical_next_open_to_close_return_mean": historical_next_open_to_close_return_mean,
        "historical_strong_close_continuation": carryover_strong_close_continuation,
    }


def _resolve_visibility_gap_continuation_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    catalyst_freshness: float,
    profitability_hard_cliff: bool,
    profile: Any,
) -> dict[str, Any]:
    enabled = bool(profile.visibility_gap_continuation_relief_enabled)
    source = str(input_data.replay_context.get("source") or "").strip()
    candidate_pool_shadow_reason = str(input_data.replay_context.get("candidate_pool_shadow_reason") or "").strip()
    candidate_pool_lane = str(input_data.replay_context.get("candidate_pool_lane") or "").strip()
    shadow_visibility_gap_selected = bool(input_data.replay_context.get("shadow_visibility_gap_selected"))
    shadow_visibility_gap_relaxed_band = bool(input_data.replay_context.get("shadow_visibility_gap_relaxed_band"))
    historical_prior = _historical_prior(input_data)
    require_relaxed_band = bool(profile.visibility_gap_continuation_require_relaxed_band)
    base_near_miss_threshold = float(profile.near_miss_threshold)
    historical_execution_quality_label = str(historical_prior.get("execution_quality_label") or "unknown")
    historical_applied_scope = str(historical_prior.get("applied_scope") or "")
    historical_evaluable_count = int(historical_prior.get("evaluable_count") or 0)
    historical_next_close_positive_rate = clamp_unit_interval(float(historical_prior.get("next_close_positive_rate", 0.0) or 0.0))
    weak_same_ticker_intraday_history = (
        historical_applied_scope == "same_ticker"
        and historical_execution_quality_label == "intraday_only"
        and historical_evaluable_count >= 3
        and historical_next_close_positive_rate <= 0.0
    )
    weak_zero_follow_through_history = (
        historical_execution_quality_label == "zero_follow_through"
        and historical_evaluable_count >= 3
    )
    default_result = {
        "enabled": enabled,
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "candidate_pool_lane": candidate_pool_lane,
        "candidate_pool_shadow_reason": candidate_pool_shadow_reason,
        "shadow_visibility_gap_selected": shadow_visibility_gap_selected,
        "shadow_visibility_gap_relaxed_band": shadow_visibility_gap_relaxed_band,
        "gate_hits": {},
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": catalyst_freshness,
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": base_near_miss_threshold,
        "catalyst_freshness_floor": 0.0,
        "near_miss_threshold_override": base_near_miss_threshold,
        "require_relaxed_band": require_relaxed_band,
        "historical_execution_quality_label": historical_execution_quality_label,
        "historical_applied_scope": historical_applied_scope,
        "historical_evaluable_count": historical_evaluable_count,
        "historical_next_close_positive_rate": historical_next_close_positive_rate,
    }
    if not enabled:
        return default_result

    breakout_freshness_min = clamp_unit_interval(float(profile.visibility_gap_continuation_breakout_freshness_min or 0.0))
    trend_acceleration_min = clamp_unit_interval(float(profile.visibility_gap_continuation_trend_acceleration_min or 0.0))
    close_strength_min = clamp_unit_interval(float(profile.visibility_gap_continuation_close_strength_min or 0.0))
    catalyst_freshness_floor = clamp_unit_interval(float(profile.visibility_gap_continuation_catalyst_freshness_floor or 0.0))
    near_miss_threshold_override = clamp_unit_interval(float(profile.visibility_gap_continuation_near_miss_threshold or base_near_miss_threshold))
    gate_hits = {
        "candidate_source": source in {"upstream_liquidity_corridor_shadow", "post_gate_liquidity_competition_shadow"},
        "visibility_gap_selected": shadow_visibility_gap_selected,
        "relaxed_band": (not require_relaxed_band) or shadow_visibility_gap_relaxed_band,
        "breakout_freshness": breakout_freshness >= breakout_freshness_min,
        "trend_acceleration": trend_acceleration >= trend_acceleration_min,
        "close_strength": close_strength >= close_strength_min,
        "no_profitability_hard_cliff": not profitability_hard_cliff,
        "historical_execution_quality": not (weak_same_ticker_intraday_history or weak_zero_follow_through_history),
    }
    eligible = all(gate_hits.values())
    effective_catalyst_freshness = catalyst_freshness
    effective_near_miss_threshold = base_near_miss_threshold
    if eligible:
        effective_catalyst_freshness = max(catalyst_freshness, catalyst_freshness_floor)
        effective_near_miss_threshold = min(base_near_miss_threshold, near_miss_threshold_override)

    applied = eligible and (
        effective_catalyst_freshness > catalyst_freshness
        or effective_near_miss_threshold < base_near_miss_threshold
    )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": applied,
        "candidate_source": source,
        "candidate_pool_lane": candidate_pool_lane,
        "candidate_pool_shadow_reason": candidate_pool_shadow_reason,
        "shadow_visibility_gap_selected": shadow_visibility_gap_selected,
        "shadow_visibility_gap_relaxed_band": shadow_visibility_gap_relaxed_band,
        "gate_hits": gate_hits,
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": effective_catalyst_freshness,
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": effective_near_miss_threshold,
        "catalyst_freshness_floor": catalyst_freshness_floor,
        "near_miss_threshold_override": near_miss_threshold_override,
        "require_relaxed_band": require_relaxed_band,
        "historical_execution_quality_label": historical_execution_quality_label,
        "historical_applied_scope": historical_applied_scope,
        "historical_evaluable_count": historical_evaluable_count,
        "historical_next_close_positive_rate": historical_next_close_positive_rate,
    }


def _resolve_merge_approved_continuation_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    profitability_hard_cliff: bool,
    profile: Any,
) -> dict[str, Any]:
    candidate_reason_codes = {
        str(code).strip()
        for code in list(input_data.replay_context.get("candidate_reason_codes") or [])
        if str(code or "").strip()
    }
    historical_prior = _historical_prior(input_data)
    base_near_miss_threshold = float(profile.near_miss_threshold)
    base_select_threshold = float(profile.select_threshold)
    historical_execution_quality_label = str(historical_prior.get("execution_quality_label") or "unknown")
    historical_applied_scope = str(historical_prior.get("applied_scope") or "")
    historical_evaluable_count = int(historical_prior.get("evaluable_count") or 0)
    historical_next_close_positive_rate = clamp_unit_interval(float(historical_prior.get("next_close_positive_rate", 0.0) or 0.0))
    weak_same_ticker_intraday_history = (
        historical_applied_scope == "same_ticker"
        and historical_execution_quality_label == "intraday_only"
        and historical_evaluable_count >= 3
        and historical_next_close_positive_rate <= 0.0
    )
    weak_zero_follow_through_history = (
        historical_execution_quality_label == "zero_follow_through"
        and historical_evaluable_count >= 3
    )
    default_result = {
        "enabled": bool(profile.merge_approved_continuation_relief_enabled),
        "eligible": False,
        "applied": False,
        "reason": "merge_approved_continuation_relief",
        "gate_hits": {},
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": base_near_miss_threshold,
        "base_select_threshold": base_select_threshold,
        "effective_select_threshold": base_select_threshold,
        "near_miss_threshold_override": base_near_miss_threshold,
        "select_threshold_override": base_select_threshold,
        "require_no_profitability_hard_cliff": bool(profile.merge_approved_continuation_require_no_profitability_hard_cliff),
        "historical_execution_quality_label": historical_execution_quality_label,
        "historical_applied_scope": historical_applied_scope,
        "historical_evaluable_count": historical_evaluable_count,
        "historical_next_close_positive_rate": historical_next_close_positive_rate,
    }
    if "merge_approved_continuation" not in candidate_reason_codes or not bool(profile.merge_approved_continuation_relief_enabled):
        return default_result

    near_miss_threshold_override = clamp_unit_interval(float(profile.merge_approved_continuation_near_miss_threshold))
    select_threshold_override = clamp_unit_interval(float(profile.merge_approved_continuation_select_threshold))
    gate_hits = {
        "breakout_freshness": breakout_freshness >= float(profile.merge_approved_continuation_breakout_freshness_min),
        "trend_acceleration": trend_acceleration >= float(profile.merge_approved_continuation_trend_acceleration_min),
        "close_strength": close_strength >= float(profile.merge_approved_continuation_close_strength_min),
        "no_profitability_hard_cliff": (not bool(profile.merge_approved_continuation_require_no_profitability_hard_cliff)) or (not profitability_hard_cliff),
        "historical_execution_quality": not (weak_same_ticker_intraday_history or weak_zero_follow_through_history),
    }
    eligible = all(gate_hits.values())
    effective_near_miss_threshold = base_near_miss_threshold
    effective_select_threshold = base_select_threshold
    if eligible:
        effective_near_miss_threshold = min(base_near_miss_threshold, near_miss_threshold_override)
        effective_select_threshold = min(base_select_threshold, select_threshold_override)

    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and (
            effective_near_miss_threshold < base_near_miss_threshold
            or effective_select_threshold < base_select_threshold
        ),
        "reason": "merge_approved_continuation_relief",
        "gate_hits": gate_hits,
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": effective_near_miss_threshold,
        "base_select_threshold": base_select_threshold,
        "effective_select_threshold": effective_select_threshold,
        "near_miss_threshold_override": near_miss_threshold_override,
        "select_threshold_override": select_threshold_override,
        "require_no_profitability_hard_cliff": bool(profile.merge_approved_continuation_require_no_profitability_hard_cliff),
        "historical_execution_quality_label": historical_execution_quality_label,
        "historical_applied_scope": historical_applied_scope,
        "historical_evaluable_count": historical_evaluable_count,
        "historical_next_close_positive_rate": historical_next_close_positive_rate,
    }


def _cohort_alignment(agent_contribution_summary: dict[str, Any], cohort_name: str) -> float:
    cohort_contributions = dict(agent_contribution_summary.get("cohort_contributions", {}) or {})
    return clamp_unit_interval(max(0.0, float(cohort_contributions.get(cohort_name, 0.0) or 0.0)))


def _cohort_penalty(agent_contribution_summary: dict[str, Any], cohort_name: str) -> float:
    cohort_contributions = dict(agent_contribution_summary.get("cohort_contributions", {}) or {})
    return clamp_unit_interval(max(0.0, -float(cohort_contributions.get(cohort_name, 0.0) or 0.0)))


def _resolve_watchlist_zero_catalyst_penalty(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    penalty = clamp_unit_interval(float(profile.watchlist_zero_catalyst_penalty or 0.0))
    default_result = {
        "enabled": penalty > 0.0,
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "gate_hits": {},
        "effective_penalty": 0.0,
    }
    if penalty <= 0.0 or source != "layer_c_watchlist":
        return default_result

    catalyst_freshness_max = clamp_unit_interval(float(profile.watchlist_zero_catalyst_catalyst_freshness_max or 0.0))
    close_strength_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_close_strength_min or 0.0))
    layer_c_alignment_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_layer_c_alignment_min or 0.0))
    sector_resonance_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_sector_resonance_min or 0.0))
    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "catalyst_freshness": catalyst_freshness <= catalyst_freshness_max,
        "close_strength": close_strength >= close_strength_min,
        "layer_c_alignment": layer_c_alignment >= layer_c_alignment_min,
        "sector_resonance": sector_resonance >= sector_resonance_min,
    }
    eligible = all(gate_hits.values())
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible,
        "candidate_source": source,
        "gate_hits": gate_hits,
        "effective_penalty": penalty if eligible else 0.0,
    }


def _resolve_watchlist_zero_catalyst_crowded_penalty(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    penalty = clamp_unit_interval(float(profile.watchlist_zero_catalyst_crowded_penalty or 0.0))
    default_result = {
        "enabled": penalty > 0.0,
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "gate_hits": {},
        "effective_penalty": 0.0,
    }
    if penalty <= 0.0 or source != "layer_c_watchlist":
        return default_result

    catalyst_freshness_max = clamp_unit_interval(float(profile.watchlist_zero_catalyst_crowded_catalyst_freshness_max or 0.0))
    close_strength_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_crowded_close_strength_min or 0.0))
    layer_c_alignment_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_crowded_layer_c_alignment_min or 0.0))
    sector_resonance_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_crowded_sector_resonance_min or 0.0))
    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "catalyst_freshness": catalyst_freshness <= catalyst_freshness_max,
        "close_strength": close_strength >= close_strength_min,
        "layer_c_alignment": layer_c_alignment >= layer_c_alignment_min,
        "sector_resonance": sector_resonance >= sector_resonance_min,
    }
    eligible = all(gate_hits.values())
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible,
        "candidate_source": source,
        "gate_hits": gate_hits,
        "effective_penalty": penalty if eligible else 0.0,
    }


def _resolve_watchlist_zero_catalyst_flat_trend_penalty(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    trend_acceleration: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    penalty = clamp_unit_interval(float(profile.watchlist_zero_catalyst_flat_trend_penalty or 0.0))
    default_result = {
        "enabled": penalty > 0.0,
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "gate_hits": {},
        "effective_penalty": 0.0,
    }
    if penalty <= 0.0 or source != "layer_c_watchlist":
        return default_result

    catalyst_freshness_max = clamp_unit_interval(float(profile.watchlist_zero_catalyst_flat_trend_catalyst_freshness_max or 0.0))
    close_strength_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_flat_trend_close_strength_min or 0.0))
    layer_c_alignment_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_flat_trend_layer_c_alignment_min or 0.0))
    sector_resonance_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_flat_trend_sector_resonance_min or 0.0))
    trend_acceleration_max = clamp_unit_interval(float(profile.watchlist_zero_catalyst_flat_trend_trend_acceleration_max or 0.0))
    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "catalyst_freshness": catalyst_freshness <= catalyst_freshness_max,
        "close_strength": close_strength >= close_strength_min,
        "layer_c_alignment": layer_c_alignment >= layer_c_alignment_min,
        "sector_resonance": sector_resonance >= sector_resonance_min,
        "trend_acceleration": trend_acceleration <= trend_acceleration_max,
    }
    eligible = all(gate_hits.values())
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible,
        "candidate_source": source,
        "gate_hits": gate_hits,
        "effective_penalty": penalty if eligible else 0.0,
    }


def _resolve_t_plus_2_continuation_candidate(
    *,
    input_data: TargetEvaluationInput,
    raw_catalyst_freshness: float,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    enabled = bool(profile.t_plus_2_continuation_enabled)
    default_result = {
        "enabled": enabled,
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "gate_hits": {},
    }
    if not enabled or source != "layer_c_watchlist":
        return default_result

    catalyst_freshness_max = clamp_unit_interval(float(profile.t_plus_2_continuation_catalyst_freshness_max or 0.0))
    breakout_freshness_min = clamp_unit_interval(float(profile.t_plus_2_continuation_breakout_freshness_min or 0.0))
    trend_acceleration_min = clamp_unit_interval(float(profile.t_plus_2_continuation_trend_acceleration_min or 0.0))
    trend_acceleration_max = clamp_unit_interval(float(profile.t_plus_2_continuation_trend_acceleration_max or 0.0))
    layer_c_alignment_min = clamp_unit_interval(float(profile.t_plus_2_continuation_layer_c_alignment_min or 0.0))
    layer_c_alignment_max = clamp_unit_interval(float(profile.t_plus_2_continuation_layer_c_alignment_max or 0.0))
    close_strength_max = clamp_unit_interval(float(profile.t_plus_2_continuation_close_strength_max or 0.0))
    sector_resonance_max = clamp_unit_interval(float(profile.t_plus_2_continuation_sector_resonance_max or 0.0))
    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "catalyst_freshness": raw_catalyst_freshness <= catalyst_freshness_max,
        "breakout_freshness": breakout_freshness >= breakout_freshness_min,
        "trend_acceleration": trend_acceleration >= trend_acceleration_min,
        "trend_acceleration_cap": trend_acceleration <= trend_acceleration_max,
        "layer_c_alignment_min": layer_c_alignment >= layer_c_alignment_min,
        "layer_c_alignment_max": layer_c_alignment <= layer_c_alignment_max,
        "close_strength": close_strength <= close_strength_max,
        "sector_resonance": sector_resonance <= sector_resonance_max,
    }
    eligible = all(gate_hits.values())
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible,
        "candidate_source": source,
        "gate_hits": gate_hits,
    }


def _build_target_input_from_item(*, trade_date: str, item: LayerCResult, included_in_buy_orders: bool) -> TargetEvaluationInput:
    return TargetEvaluationInput(
        trade_date=trade_date,
        ticker=item.ticker,
        score_b=float(item.score_b),
        score_c=float(item.score_c),
        score_final=float(item.score_final),
        quality_score=float(item.quality_score),
        layer_c_decision=str(item.decision or ""),
        bc_conflict=item.bc_conflict,
        strategy_signals={name: signal for name, signal in dict(item.strategy_signals or {}).items()},
        agent_contribution_summary=dict(item.agent_contribution_summary or {}),
        execution_constraints={"included_in_buy_orders": bool(included_in_buy_orders)},
        replay_context={
            "source": str(getattr(item, "candidate_source", "") or "layer_c_watchlist"),
            "candidate_reason_codes": [
                str(reason)
                for reason in list(getattr(item, "candidate_reason_codes", []) or [])
                if str(reason or "").strip()
            ],
            "historical_prior": dict(getattr(item, "historical_prior", {}) or {}),
        },
    )


def _build_target_input_from_entry(*, trade_date: str, entry: dict[str, Any]) -> TargetEvaluationInput:
    candidate_reason_codes = [
        str(reason)
        for reason in list(entry.get("candidate_reason_codes", entry.get("reasons", [])) or [])
        if str(reason or "").strip()
    ]
    candidate_source = str(entry.get("candidate_source") or "watchlist_filter_diagnostics")
    explicit_metric_overrides = {}
    if candidate_source == "catalyst_theme":
        explicit_metric_overrides = dict(entry.get("catalyst_theme_metrics") or entry.get("metrics") or {})
    return TargetEvaluationInput(
        trade_date=trade_date,
        ticker=str(entry.get("ticker") or ""),
        score_b=float(entry.get("score_b", 0.0) or 0.0),
        score_c=float(entry.get("score_c", 0.0) or 0.0),
        score_final=float(entry.get("score_final", 0.0) or 0.0),
        quality_score=float(entry.get("quality_score", 0.5) or 0.5),
        layer_c_decision=str(entry.get("decision") or ""),
        bc_conflict=entry.get("bc_conflict"),
        strategy_signals=dict(entry.get("strategy_signals") or {}),
        agent_contribution_summary=dict(entry.get("agent_contribution_summary") or {}),
        replay_context={
            "source": candidate_source,
            "reason": str(entry.get("reason") or ""),
            "candidate_reason_codes": candidate_reason_codes,
            "historical_prior": dict(entry.get("historical_prior") or {}),
            "candidate_pool_lane": str(entry.get("candidate_pool_lane") or ""),
            "candidate_pool_shadow_reason": str(entry.get("candidate_pool_shadow_reason") or ""),
            "shadow_visibility_gap_selected": bool(entry.get("shadow_visibility_gap_selected")),
            "shadow_visibility_gap_relaxed_band": bool(entry.get("shadow_visibility_gap_relaxed_band")),
            "short_trade_catalyst_relief": dict(entry.get("short_trade_catalyst_relief") or {}),
            "explicit_metric_overrides": explicit_metric_overrides,
        },
    )


def _summarize_positive_factor(name: str, value: float) -> str | None:
    if value < 0.45:
        return None
    return f"{name}={value:.2f}"


def _summarize_penalty(name: str, value: float) -> str | None:
    if value < 0.45:
        return None
    return f"{name}={value:.2f}"


def _classify_breakout_stage(*, breakout_freshness: float, trend_acceleration: float, profile: Any) -> tuple[str, bool, bool]:
    selected_gate_pass = breakout_freshness >= float(profile.selected_breakout_freshness_min) and trend_acceleration >= float(profile.selected_trend_acceleration_min)
    near_miss_gate_pass = breakout_freshness >= float(profile.near_miss_breakout_freshness_min) and trend_acceleration >= float(profile.near_miss_trend_acceleration_min)
    if selected_gate_pass:
        return "confirmed_breakout", True, True
    if near_miss_gate_pass:
        return "prepared_breakout", False, True
    return "weak_breakout", False, False


def _collect_breakout_gate_misses(*, breakout_freshness: float, trend_acceleration: float, breakout_min: float, trend_min: float, label: str) -> list[str]:
    misses: list[str] = []
    if breakout_freshness < breakout_min:
        misses.append(f"breakout_freshness_below_{label}_floor")
    if trend_acceleration < trend_min:
        misses.append(f"trend_acceleration_below_{label}_floor")
    return misses


def _resolve_positive_score_weights(profile: Any) -> dict[str, float]:
    configured_weights = {
        "breakout_freshness": float(profile.breakout_freshness_weight),
        "trend_acceleration": float(profile.trend_acceleration_weight),
        "volume_expansion_quality": float(profile.volume_expansion_quality_weight),
        "close_strength": float(profile.close_strength_weight),
        "sector_resonance": float(profile.sector_resonance_weight),
        "catalyst_freshness": float(profile.catalyst_freshness_weight),
        "layer_c_alignment": float(profile.layer_c_alignment_weight),
    }
    return _normalize_positive_score_weights(configured_weights)


def _resolve_prepared_breakout_penalty_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_stage: str,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    catalyst_freshness: float,
    long_trend_strength: float,
    mean_reversion_strength: float,
    profile: Any,
) -> dict[str, Any]:
    base_positive_score_weights = {
        "breakout_freshness": float(profile.breakout_freshness_weight),
        "trend_acceleration": float(profile.trend_acceleration_weight),
        "volume_expansion_quality": float(profile.volume_expansion_quality_weight),
        "close_strength": float(profile.close_strength_weight),
        "sector_resonance": float(profile.sector_resonance_weight),
        "catalyst_freshness": float(profile.catalyst_freshness_weight),
        "layer_c_alignment": float(profile.layer_c_alignment_weight),
    }
    source = str(input_data.replay_context.get("source") or "").strip()
    base_stale_score_penalty_weight = float(profile.stale_score_penalty_weight)
    base_extension_score_penalty_weight = float(profile.extension_score_penalty_weight)
    default_result = {
        "enabled": bool(profile.prepared_breakout_penalty_relief_enabled),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": {},
        "base_positive_score_weights": dict(base_positive_score_weights),
        "effective_positive_score_weights": dict(base_positive_score_weights),
        "base_stale_score_penalty_weight": base_stale_score_penalty_weight,
        "effective_stale_score_penalty_weight": base_stale_score_penalty_weight,
        "base_extension_score_penalty_weight": base_extension_score_penalty_weight,
        "effective_extension_score_penalty_weight": base_extension_score_penalty_weight,
    }
    if not bool(profile.prepared_breakout_penalty_relief_enabled):
        return default_result

    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "prepared_breakout_stage": breakout_stage == "prepared_breakout",
        "breakout_freshness_cap": breakout_freshness <= float(profile.prepared_breakout_penalty_relief_breakout_freshness_max),
        "trend_acceleration": trend_acceleration >= float(profile.prepared_breakout_penalty_relief_trend_acceleration_min),
        "close_strength": close_strength >= float(profile.prepared_breakout_penalty_relief_close_strength_min),
        "sector_resonance": sector_resonance >= float(profile.prepared_breakout_penalty_relief_sector_resonance_min),
        "layer_c_alignment": layer_c_alignment >= float(profile.prepared_breakout_penalty_relief_layer_c_alignment_min),
        "catalyst_freshness_cap": catalyst_freshness <= float(profile.prepared_breakout_penalty_relief_catalyst_freshness_max),
        "long_trend_strength": long_trend_strength >= float(profile.prepared_breakout_penalty_relief_long_trend_strength_min),
        "mean_reversion_cap": mean_reversion_strength <= float(profile.prepared_breakout_penalty_relief_mean_reversion_strength_max),
    }
    eligible = all(gate_hits.values())
    effective_positive_score_weights = dict(base_positive_score_weights)
    effective_stale_score_penalty_weight = base_stale_score_penalty_weight
    effective_extension_score_penalty_weight = base_extension_score_penalty_weight
    if eligible:
        effective_positive_score_weights = {
            "breakout_freshness": float(profile.prepared_breakout_penalty_relief_breakout_freshness_weight),
            "trend_acceleration": float(profile.prepared_breakout_penalty_relief_trend_acceleration_weight),
            "volume_expansion_quality": float(profile.prepared_breakout_penalty_relief_volume_expansion_quality_weight),
            "close_strength": float(profile.prepared_breakout_penalty_relief_close_strength_weight),
            "sector_resonance": float(profile.prepared_breakout_penalty_relief_sector_resonance_weight),
            "catalyst_freshness": float(profile.prepared_breakout_penalty_relief_catalyst_freshness_weight),
            "layer_c_alignment": float(profile.prepared_breakout_penalty_relief_layer_c_alignment_weight),
        }
        effective_stale_score_penalty_weight = min(
            base_stale_score_penalty_weight,
            float(profile.prepared_breakout_penalty_relief_stale_score_penalty_weight),
        )
        effective_extension_score_penalty_weight = min(
            base_extension_score_penalty_weight,
            float(profile.prepared_breakout_penalty_relief_extension_score_penalty_weight),
        )
    applied = eligible and (
        dict(effective_positive_score_weights) != dict(base_positive_score_weights)
        or effective_stale_score_penalty_weight < base_stale_score_penalty_weight
        or effective_extension_score_penalty_weight < base_extension_score_penalty_weight
    )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": applied,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": gate_hits,
        "base_positive_score_weights": dict(base_positive_score_weights),
        "effective_positive_score_weights": dict(effective_positive_score_weights),
        "base_stale_score_penalty_weight": base_stale_score_penalty_weight,
        "effective_stale_score_penalty_weight": effective_stale_score_penalty_weight,
        "base_extension_score_penalty_weight": base_extension_score_penalty_weight,
        "effective_extension_score_penalty_weight": effective_extension_score_penalty_weight,
    }


def _resolve_prepared_breakout_catalyst_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_stage: str,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    catalyst_freshness: float,
    long_trend_strength: float,
    mean_reversion_strength: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    default_result = {
        "enabled": bool(profile.prepared_breakout_catalyst_relief_enabled),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": {},
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": catalyst_freshness,
        "catalyst_freshness_floor": float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_floor),
    }
    if not bool(profile.prepared_breakout_catalyst_relief_enabled):
        return default_result

    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "prepared_breakout_stage": breakout_stage == "prepared_breakout",
        "breakout_freshness_cap": breakout_freshness <= float(profile.prepared_breakout_catalyst_relief_breakout_freshness_max),
        "trend_acceleration": trend_acceleration >= float(profile.prepared_breakout_catalyst_relief_trend_acceleration_min),
        "close_strength": close_strength >= float(profile.prepared_breakout_catalyst_relief_close_strength_min),
        "sector_resonance": sector_resonance >= float(profile.prepared_breakout_catalyst_relief_sector_resonance_min),
        "layer_c_alignment": layer_c_alignment >= float(profile.prepared_breakout_catalyst_relief_layer_c_alignment_min),
        "catalyst_freshness_cap": catalyst_freshness <= float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_max),
        "long_trend_strength": long_trend_strength >= float(profile.prepared_breakout_catalyst_relief_long_trend_strength_min),
        "mean_reversion_cap": mean_reversion_strength <= float(profile.prepared_breakout_catalyst_relief_mean_reversion_strength_max),
    }
    eligible = all(gate_hits.values())
    effective_catalyst_freshness = catalyst_freshness
    if eligible:
        effective_catalyst_freshness = max(
            catalyst_freshness,
            float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_floor),
        )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and effective_catalyst_freshness > catalyst_freshness,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": gate_hits,
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": effective_catalyst_freshness,
        "catalyst_freshness_floor": float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_floor),
    }


def _resolve_prepared_breakout_volume_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_stage: str,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    catalyst_freshness: float,
    long_trend_strength: float,
    mean_reversion_strength: float,
    volatility_strength: float,
    volume_expansion_quality: float,
    volatility_regime: float,
    atr_ratio: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    default_result = {
        "enabled": bool(profile.prepared_breakout_volume_relief_enabled),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": {},
        "base_volume_expansion_quality": volume_expansion_quality,
        "effective_volume_expansion_quality": volume_expansion_quality,
        "volatility_regime": volatility_regime,
        "atr_ratio": atr_ratio,
        "volume_expansion_quality_floor": float(profile.prepared_breakout_volume_relief_volume_expansion_quality_floor),
    }
    if not bool(profile.prepared_breakout_volume_relief_enabled):
        return default_result

    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "prepared_breakout_stage": breakout_stage == "prepared_breakout",
        "breakout_freshness_cap": breakout_freshness <= float(profile.prepared_breakout_volume_relief_breakout_freshness_max),
        "trend_acceleration": trend_acceleration >= float(profile.prepared_breakout_volume_relief_trend_acceleration_min),
        "close_strength": close_strength >= float(profile.prepared_breakout_volume_relief_close_strength_min),
        "sector_resonance": sector_resonance >= float(profile.prepared_breakout_volume_relief_sector_resonance_min),
        "layer_c_alignment": layer_c_alignment >= float(profile.prepared_breakout_volume_relief_layer_c_alignment_min),
        "catalyst_freshness_cap": catalyst_freshness <= float(profile.prepared_breakout_volume_relief_catalyst_freshness_max),
        "long_trend_strength": long_trend_strength >= float(profile.prepared_breakout_volume_relief_long_trend_strength_min),
        "mean_reversion_cap": mean_reversion_strength <= float(profile.prepared_breakout_volume_relief_mean_reversion_strength_max),
        "volatility_strength_cap": volatility_strength <= float(profile.prepared_breakout_volume_relief_volatility_strength_max),
        "volatility_regime": volatility_regime >= float(profile.prepared_breakout_volume_relief_volatility_regime_min),
        "atr_ratio": atr_ratio >= float(profile.prepared_breakout_volume_relief_atr_ratio_min),
    }
    eligible = all(gate_hits.values())
    effective_volume_expansion_quality = volume_expansion_quality
    if eligible:
        effective_volume_expansion_quality = max(
            volume_expansion_quality,
            float(profile.prepared_breakout_volume_relief_volume_expansion_quality_floor),
        )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and effective_volume_expansion_quality > volume_expansion_quality,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": gate_hits,
        "base_volume_expansion_quality": volume_expansion_quality,
        "effective_volume_expansion_quality": effective_volume_expansion_quality,
        "volatility_regime": volatility_regime,
        "atr_ratio": atr_ratio,
        "volume_expansion_quality_floor": float(profile.prepared_breakout_volume_relief_volume_expansion_quality_floor),
    }


def _resolve_prepared_breakout_continuation_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_stage: str,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    catalyst_freshness: float,
    long_trend_strength: float,
    mean_reversion_strength: float,
    momentum_1m: float,
    momentum_3m: float,
    momentum_6m: float,
    volume_momentum: float,
    ema_strength: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    continuation_support = clamp_unit_interval((0.40 * momentum_3m) + (0.35 * momentum_6m) + (0.25 * volume_momentum))
    default_result = {
        "enabled": bool(profile.prepared_breakout_continuation_relief_enabled),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": {},
        "base_breakout_freshness": breakout_freshness,
        "effective_breakout_freshness": breakout_freshness,
        "base_trend_acceleration": trend_acceleration,
        "effective_trend_acceleration": trend_acceleration,
        "momentum_1m": momentum_1m,
        "momentum_3m": momentum_3m,
        "momentum_6m": momentum_6m,
        "volume_momentum": volume_momentum,
        "continuation_support": continuation_support,
        "breakout_freshness_floor": float(profile.prepared_breakout_continuation_relief_breakout_freshness_floor),
        "trend_acceleration_floor": float(profile.prepared_breakout_continuation_relief_trend_acceleration_floor),
    }
    if not bool(profile.prepared_breakout_continuation_relief_enabled):
        return default_result

    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "prepared_breakout_stage": breakout_stage == "prepared_breakout",
        "breakout_freshness_cap": breakout_freshness <= float(profile.prepared_breakout_continuation_relief_breakout_freshness_max),
        "trend_acceleration_min": trend_acceleration >= float(profile.prepared_breakout_continuation_relief_trend_acceleration_min),
        "trend_acceleration_cap": trend_acceleration <= float(profile.prepared_breakout_continuation_relief_trend_acceleration_max),
        "close_strength": close_strength >= float(profile.prepared_breakout_continuation_relief_close_strength_min),
        "sector_resonance": sector_resonance >= float(profile.prepared_breakout_continuation_relief_sector_resonance_min),
        "layer_c_alignment": layer_c_alignment >= float(profile.prepared_breakout_continuation_relief_layer_c_alignment_min),
        "catalyst_freshness_cap": catalyst_freshness <= float(profile.prepared_breakout_continuation_relief_catalyst_freshness_max),
        "long_trend_strength": long_trend_strength >= float(profile.prepared_breakout_continuation_relief_long_trend_strength_min),
        "mean_reversion_cap": mean_reversion_strength <= float(profile.prepared_breakout_continuation_relief_mean_reversion_strength_max),
        "momentum_1m_pullback": momentum_1m <= float(profile.prepared_breakout_continuation_relief_momentum_1m_max),
        "continuation_support": continuation_support >= float(profile.prepared_breakout_continuation_relief_continuation_support_min),
    }
    eligible = all(gate_hits.values())
    effective_breakout_freshness = breakout_freshness
    effective_trend_acceleration = trend_acceleration
    if eligible:
        effective_breakout_freshness = max(
            breakout_freshness,
            float(profile.prepared_breakout_continuation_relief_breakout_freshness_floor),
        )
        effective_trend_acceleration = max(
            trend_acceleration,
            min(
                float(profile.prepared_breakout_continuation_relief_trend_acceleration_floor),
                clamp_unit_interval(
                    (0.30 * continuation_support)
                    + (0.35 * ema_strength)
                    + (0.20 * long_trend_strength)
                    + (0.15 * close_strength)
                ),
            ),
        )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and (
            effective_breakout_freshness > breakout_freshness or effective_trend_acceleration > trend_acceleration
        ),
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": gate_hits,
        "base_breakout_freshness": breakout_freshness,
        "effective_breakout_freshness": effective_breakout_freshness,
        "base_trend_acceleration": trend_acceleration,
        "effective_trend_acceleration": effective_trend_acceleration,
        "momentum_1m": momentum_1m,
        "momentum_3m": momentum_3m,
        "momentum_6m": momentum_6m,
        "volume_momentum": volume_momentum,
        "continuation_support": continuation_support,
        "breakout_freshness_floor": float(profile.prepared_breakout_continuation_relief_breakout_freshness_floor),
        "trend_acceleration_floor": float(profile.prepared_breakout_continuation_relief_trend_acceleration_floor),
    }


def _resolve_prepared_breakout_selected_catalyst_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_stage: str,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    volume_expansion_quality: float,
    catalyst_freshness: float,
    long_trend_strength: float,
    mean_reversion_strength: float,
    prepared_breakout_penalty_relief: dict[str, Any],
    prepared_breakout_catalyst_relief: dict[str, Any],
    prepared_breakout_volume_relief: dict[str, Any],
    prepared_breakout_continuation_relief: dict[str, Any],
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    default_result = {
        "enabled": bool(profile.prepared_breakout_selected_catalyst_relief_enabled),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": {},
        "base_breakout_freshness": breakout_freshness,
        "effective_breakout_freshness": breakout_freshness,
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": catalyst_freshness,
        "selected_breakout_freshness_floor": float(profile.prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor),
        "catalyst_freshness_floor": float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor),
    }
    if not bool(profile.prepared_breakout_selected_catalyst_relief_enabled):
        return default_result

    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "prepared_breakout_stage": breakout_stage == "prepared_breakout",
        "penalty_relief_applied": bool(prepared_breakout_penalty_relief.get("applied")),
        "catalyst_relief_applied": bool(prepared_breakout_catalyst_relief.get("applied")),
        "volume_relief_applied": bool(prepared_breakout_volume_relief.get("applied")),
        "continuation_relief_applied": bool(prepared_breakout_continuation_relief.get("applied")),
        "breakout_freshness_min": breakout_freshness >= float(profile.prepared_breakout_selected_catalyst_relief_breakout_freshness_min),
        "trend_acceleration_min": trend_acceleration >= float(profile.prepared_breakout_selected_catalyst_relief_trend_acceleration_min),
        "close_strength": close_strength >= float(profile.prepared_breakout_selected_catalyst_relief_close_strength_min),
        "sector_resonance": sector_resonance >= float(profile.prepared_breakout_selected_catalyst_relief_sector_resonance_min),
        "layer_c_alignment": layer_c_alignment >= float(profile.prepared_breakout_selected_catalyst_relief_layer_c_alignment_min),
        "volume_expansion_quality": volume_expansion_quality >= float(profile.prepared_breakout_selected_catalyst_relief_volume_expansion_quality_min),
        "catalyst_freshness_cap": catalyst_freshness <= float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_max),
        "long_trend_strength": long_trend_strength >= float(profile.prepared_breakout_selected_catalyst_relief_long_trend_strength_min),
        "mean_reversion_cap": mean_reversion_strength <= float(profile.prepared_breakout_selected_catalyst_relief_mean_reversion_strength_max),
    }
    eligible = all(gate_hits.values())
    effective_breakout_freshness = breakout_freshness
    effective_catalyst_freshness = catalyst_freshness
    if eligible:
        effective_breakout_freshness = max(
            breakout_freshness,
            float(profile.prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor),
        )
        effective_catalyst_freshness = max(
            catalyst_freshness,
            float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor),
        )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and (
            effective_breakout_freshness > breakout_freshness or effective_catalyst_freshness > catalyst_freshness
        ),
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": gate_hits,
        "base_breakout_freshness": breakout_freshness,
        "effective_breakout_freshness": effective_breakout_freshness,
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": effective_catalyst_freshness,
        "selected_breakout_freshness_floor": float(profile.prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor),
        "catalyst_freshness_floor": float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor),
    }


def _compute_short_trade_signal_snapshot(input_data: TargetEvaluationInput, *, profile: Any) -> dict[str, Any]:
    trend_signal = _load_signal(input_data.strategy_signals.get("trend"))
    event_signal = _load_signal(input_data.strategy_signals.get("event_sentiment"))
    fundamental_signal = _load_signal(input_data.strategy_signals.get("fundamental"))
    mean_reversion_signal = _load_signal(input_data.strategy_signals.get("mean_reversion"))

    momentum_strength = _subfactor_positive_strength(trend_signal, "momentum")
    momentum_metrics = _subfactor_metrics(trend_signal, "momentum")
    momentum_1m = float(momentum_metrics.get("momentum_1m", 0.0) or 0.0)
    momentum_3m = clamp_unit_interval(float(momentum_metrics.get("momentum_3m", 0.0) or 0.0))
    momentum_6m = clamp_unit_interval(float(momentum_metrics.get("momentum_6m", 0.0) or 0.0))
    volume_momentum = clamp_unit_interval(float(momentum_metrics.get("volume_momentum", 0.0) or 0.0))
    adx_strength = _subfactor_positive_strength(trend_signal, "adx_strength")
    ema_strength = _subfactor_positive_strength(trend_signal, "ema_alignment")
    volatility_strength = _subfactor_positive_strength(trend_signal, "volatility")
    volatility_metrics = _subfactor_metrics(trend_signal, "volatility")
    volatility_regime = clamp_unit_interval(float(volatility_metrics.get("volatility_regime", 0.0) or 0.0))
    atr_ratio = clamp_unit_interval(float(volatility_metrics.get("atr_ratio", 0.0) or 0.0))
    long_trend_strength = _subfactor_positive_strength(trend_signal, "long_trend_alignment")
    event_freshness_strength = _subfactor_positive_strength(event_signal, "event_freshness")
    news_sentiment_strength = _subfactor_positive_strength(event_signal, "news_sentiment")
    event_signal_strength = _positive_strength(event_signal)
    mean_reversion_strength = _positive_strength(mean_reversion_signal)

    analyst_alignment = _cohort_alignment(input_data.agent_contribution_summary, "analyst")
    investor_alignment = _cohort_alignment(input_data.agent_contribution_summary, "investor")
    analyst_penalty = _cohort_penalty(input_data.agent_contribution_summary, "analyst")
    investor_penalty = _cohort_penalty(input_data.agent_contribution_summary, "investor")
    score_b_strength = _normalize_score(input_data.score_b)
    score_c_strength = _normalize_score(input_data.score_c)
    score_final_strength = _normalize_score(input_data.score_final)
    explicit_metric_overrides = dict(input_data.replay_context.get("explicit_metric_overrides") or {})

    breakout_freshness = clamp_unit_interval((0.40 * momentum_strength) + (0.35 * event_freshness_strength) + (0.25 * event_signal_strength))
    trend_acceleration = clamp_unit_interval((0.40 * momentum_strength) + (0.35 * adx_strength) + (0.25 * ema_strength))
    volume_expansion_quality = clamp_unit_interval((0.55 * volatility_strength) + (0.25 * momentum_strength) + (0.20 * event_signal_strength))
    close_strength = clamp_unit_interval((0.55 * ema_strength) + (0.25 * momentum_strength) + (0.20 * score_b_strength))
    sector_resonance = clamp_unit_interval((0.45 * analyst_alignment) + (0.20 * investor_alignment) + (0.20 * score_c_strength) + (0.15 * event_signal_strength))
    raw_catalyst_freshness = clamp_unit_interval((0.65 * event_freshness_strength) + (0.35 * news_sentiment_strength))
    layer_c_alignment = clamp_unit_interval((0.55 * score_c_strength) + (0.25 * analyst_alignment) + (0.20 * clamp_unit_interval(1.0 if input_data.layer_c_decision != "avoid" else 0.0)))
    if explicit_metric_overrides:
        breakout_freshness = clamp_unit_interval(float(explicit_metric_overrides.get("breakout_freshness", breakout_freshness) or breakout_freshness))
        trend_acceleration = clamp_unit_interval(float(explicit_metric_overrides.get("trend_acceleration", trend_acceleration) or trend_acceleration))
        volume_expansion_quality = clamp_unit_interval(float(explicit_metric_overrides.get("volume_expansion_quality", volume_expansion_quality) or volume_expansion_quality))
        close_strength = clamp_unit_interval(float(explicit_metric_overrides.get("close_strength", close_strength) or close_strength))
        sector_resonance = clamp_unit_interval(float(explicit_metric_overrides.get("sector_resonance", sector_resonance) or sector_resonance))
        raw_catalyst_freshness = clamp_unit_interval(float(explicit_metric_overrides.get("catalyst_freshness", raw_catalyst_freshness) or raw_catalyst_freshness))
    breakout_stage, _, _ = _classify_breakout_stage(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        profile=profile,
    )
    return {
        "trend_signal": trend_signal,
        "event_signal": event_signal,
        "fundamental_signal": fundamental_signal,
        "mean_reversion_signal": mean_reversion_signal,
        "momentum_strength": momentum_strength,
        "momentum_1m": momentum_1m,
        "momentum_3m": momentum_3m,
        "momentum_6m": momentum_6m,
        "volume_momentum": volume_momentum,
        "adx_strength": adx_strength,
        "ema_strength": ema_strength,
        "volatility_strength": volatility_strength,
        "volatility_metrics": volatility_metrics,
        "volatility_regime": volatility_regime,
        "atr_ratio": atr_ratio,
        "long_trend_strength": long_trend_strength,
        "event_freshness_strength": event_freshness_strength,
        "news_sentiment_strength": news_sentiment_strength,
        "event_signal_strength": event_signal_strength,
        "mean_reversion_strength": mean_reversion_strength,
        "analyst_alignment": analyst_alignment,
        "investor_alignment": investor_alignment,
        "analyst_penalty": analyst_penalty,
        "investor_penalty": investor_penalty,
        "score_b_strength": score_b_strength,
        "score_c_strength": score_c_strength,
        "score_final_strength": score_final_strength,
        "breakout_freshness": breakout_freshness,
        "trend_acceleration": trend_acceleration,
        "volume_expansion_quality": volume_expansion_quality,
        "close_strength": close_strength,
        "sector_resonance": sector_resonance,
        "raw_catalyst_freshness": raw_catalyst_freshness,
        "layer_c_alignment": layer_c_alignment,
        "breakout_stage": breakout_stage,
    }


def _resolve_short_trade_snapshot_reliefs(
    input_data: TargetEvaluationInput,
    *,
    profile: Any,
    signal_snapshot: dict[str, Any],
) -> dict[str, Any]:
    fundamental_signal = signal_snapshot["fundamental_signal"]
    breakout_stage = str(signal_snapshot["breakout_stage"])
    breakout_freshness = float(signal_snapshot["breakout_freshness"])
    trend_acceleration = float(signal_snapshot["trend_acceleration"])
    volume_expansion_quality = float(signal_snapshot["volume_expansion_quality"])
    close_strength = float(signal_snapshot["close_strength"])
    sector_resonance = float(signal_snapshot["sector_resonance"])
    raw_catalyst_freshness = float(signal_snapshot["raw_catalyst_freshness"])
    layer_c_alignment = float(signal_snapshot["layer_c_alignment"])
    long_trend_strength = float(signal_snapshot["long_trend_strength"])
    mean_reversion_strength = float(signal_snapshot["mean_reversion_strength"])
    momentum_1m = float(signal_snapshot["momentum_1m"])
    momentum_3m = float(signal_snapshot["momentum_3m"])
    momentum_6m = float(signal_snapshot["momentum_6m"])
    volume_momentum = float(signal_snapshot["volume_momentum"])
    ema_strength = float(signal_snapshot["ema_strength"])
    volatility_strength = float(signal_snapshot["volatility_strength"])
    volatility_metrics = dict(signal_snapshot["volatility_metrics"])
    score_final_strength = float(signal_snapshot["score_final_strength"])
    analyst_penalty = float(signal_snapshot["analyst_penalty"])
    investor_penalty = float(signal_snapshot["investor_penalty"])
    historical_prior = _historical_prior(input_data)

    prepared_breakout_continuation_relief = _resolve_prepared_breakout_continuation_relief(
        input_data=input_data,
        breakout_stage=breakout_stage,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        catalyst_freshness=raw_catalyst_freshness,
        long_trend_strength=long_trend_strength,
        mean_reversion_strength=mean_reversion_strength,
        momentum_1m=momentum_1m,
        momentum_3m=momentum_3m,
        momentum_6m=momentum_6m,
        volume_momentum=volume_momentum,
        ema_strength=ema_strength,
        profile=profile,
    )
    prepared_breakout_penalty_relief = _resolve_prepared_breakout_penalty_relief(
        input_data=input_data,
        breakout_stage=breakout_stage,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        catalyst_freshness=raw_catalyst_freshness,
        long_trend_strength=long_trend_strength,
        mean_reversion_strength=mean_reversion_strength,
        profile=profile,
    )
    prepared_breakout_catalyst_relief = _resolve_prepared_breakout_catalyst_relief(
        input_data=input_data,
        breakout_stage=breakout_stage,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        catalyst_freshness=raw_catalyst_freshness,
        long_trend_strength=long_trend_strength,
        mean_reversion_strength=mean_reversion_strength,
        profile=profile,
    )
    prepared_breakout_volume_relief = _resolve_prepared_breakout_volume_relief(
        input_data=input_data,
        breakout_stage=breakout_stage,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        catalyst_freshness=raw_catalyst_freshness,
        long_trend_strength=long_trend_strength,
        mean_reversion_strength=mean_reversion_strength,
        volatility_strength=volatility_strength,
        volume_expansion_quality=volume_expansion_quality,
        volatility_regime=float(volatility_metrics.get("volatility_regime", 0.0) or 0.0),
        atr_ratio=float(volatility_metrics.get("atr_ratio", 0.0) or 0.0),
        profile=profile,
    )
    positive_score_weights = _normalize_positive_score_weights(
        dict(prepared_breakout_penalty_relief["effective_positive_score_weights"])
    )
    profitability_relief = _resolve_profitability_relief(
        input_data=input_data,
        fundamental_signal=fundamental_signal,
        breakout_freshness=breakout_freshness,
        catalyst_freshness=raw_catalyst_freshness,
        sector_resonance=sector_resonance,
        profile=profile,
    )
    catalyst_relief = _resolve_upstream_shadow_catalyst_relief(
        input_data=input_data,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        catalyst_freshness=raw_catalyst_freshness,
        profitability_hard_cliff=bool(profitability_relief["hard_cliff"]),
        profile=profile,
    )
    visibility_gap_continuation_relief = _resolve_visibility_gap_continuation_relief(
        input_data=input_data,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        catalyst_freshness=raw_catalyst_freshness,
        profitability_hard_cliff=bool(profitability_relief["hard_cliff"]),
        profile=profile,
    )
    merge_approved_continuation_relief = _resolve_merge_approved_continuation_relief(
        input_data=input_data,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        profitability_hard_cliff=bool(profitability_relief["hard_cliff"]),
        profile=profile,
    )
    historical_execution_relief = _resolve_historical_execution_relief(
        input_data=input_data,
        profitability_hard_cliff=bool(profitability_relief["hard_cliff"]),
        profile=profile,
    )
    catalyst_freshness = float(catalyst_relief["effective_catalyst_freshness"])
    effective_near_miss_threshold = float(catalyst_relief["effective_near_miss_threshold"])
    effective_select_threshold = float(catalyst_relief["effective_select_threshold"])
    breakout_freshness = max(breakout_freshness, float(prepared_breakout_continuation_relief["effective_breakout_freshness"]))
    trend_acceleration = max(trend_acceleration, float(prepared_breakout_continuation_relief["effective_trend_acceleration"]))
    volume_expansion_quality = max(volume_expansion_quality, float(prepared_breakout_volume_relief["effective_volume_expansion_quality"]))
    catalyst_freshness = max(catalyst_freshness, float(visibility_gap_continuation_relief["effective_catalyst_freshness"]))
    catalyst_freshness = max(catalyst_freshness, float(prepared_breakout_catalyst_relief["effective_catalyst_freshness"]))
    prepared_breakout_selected_catalyst_relief = _resolve_prepared_breakout_selected_catalyst_relief(
        input_data=input_data,
        breakout_stage=breakout_stage,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        volume_expansion_quality=volume_expansion_quality,
        catalyst_freshness=catalyst_freshness,
        long_trend_strength=long_trend_strength,
        mean_reversion_strength=mean_reversion_strength,
        prepared_breakout_penalty_relief=prepared_breakout_penalty_relief,
        prepared_breakout_catalyst_relief=prepared_breakout_catalyst_relief,
        prepared_breakout_volume_relief=prepared_breakout_volume_relief,
        prepared_breakout_continuation_relief=prepared_breakout_continuation_relief,
        profile=profile,
    )
    breakout_freshness = max(breakout_freshness, float(prepared_breakout_selected_catalyst_relief["effective_breakout_freshness"]))
    catalyst_freshness = max(catalyst_freshness, float(prepared_breakout_selected_catalyst_relief["effective_catalyst_freshness"]))
    effective_near_miss_threshold = min(effective_near_miss_threshold, float(visibility_gap_continuation_relief["effective_near_miss_threshold"]))
    effective_near_miss_threshold = min(effective_near_miss_threshold, float(merge_approved_continuation_relief["effective_near_miss_threshold"]))
    effective_near_miss_threshold = min(effective_near_miss_threshold, float(historical_execution_relief["effective_near_miss_threshold"]))
    effective_select_threshold = min(effective_select_threshold, float(merge_approved_continuation_relief["effective_select_threshold"]))
    effective_select_threshold = min(effective_select_threshold, float(historical_execution_relief["effective_select_threshold"]))
    layer_c_avoid_penalty = float(profitability_relief["effective_avoid_penalty"])
    watchlist_zero_catalyst_penalty = _resolve_watchlist_zero_catalyst_penalty(
        input_data=input_data,
        catalyst_freshness=raw_catalyst_freshness,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        profile=profile,
    )
    effective_watchlist_zero_catalyst_penalty = float(watchlist_zero_catalyst_penalty["effective_penalty"])
    watchlist_zero_catalyst_crowded_penalty = _resolve_watchlist_zero_catalyst_crowded_penalty(
        input_data=input_data,
        catalyst_freshness=raw_catalyst_freshness,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        profile=profile,
    )
    effective_watchlist_zero_catalyst_crowded_penalty = float(watchlist_zero_catalyst_crowded_penalty["effective_penalty"])
    watchlist_zero_catalyst_flat_trend_penalty = _resolve_watchlist_zero_catalyst_flat_trend_penalty(
        input_data=input_data,
        catalyst_freshness=raw_catalyst_freshness,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        trend_acceleration=trend_acceleration,
        profile=profile,
    )
    effective_watchlist_zero_catalyst_flat_trend_penalty = float(watchlist_zero_catalyst_flat_trend_penalty["effective_penalty"])
    t_plus_2_continuation_candidate = _resolve_t_plus_2_continuation_candidate(
        input_data=input_data,
        raw_catalyst_freshness=raw_catalyst_freshness,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        profile=profile,
    )

    stale_trend_repair_penalty = clamp_unit_interval((0.45 * mean_reversion_strength) + (0.35 * long_trend_strength) + (0.20 * max(0.0, long_trend_strength - breakout_freshness)))
    overhead_supply_penalty = clamp_unit_interval((0.45 if input_data.bc_conflict in profile.overhead_conflict_penalty_conflicts else 0.0) + (0.35 * analyst_penalty) + (0.20 * investor_penalty))
    extension_without_room_penalty = clamp_unit_interval((0.45 * long_trend_strength) + (0.35 * max(0.0, volatility_strength - catalyst_freshness)) + (0.20 * clamp_unit_interval((score_final_strength - 0.72) / 0.28)))
    profitability_hard_cliff_boundary_relief = _resolve_profitability_hard_cliff_boundary_relief(
        input_data=input_data,
        profitability_hard_cliff=bool(profitability_relief["hard_cliff"]),
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        catalyst_freshness=raw_catalyst_freshness,
        sector_resonance=sector_resonance,
        close_strength=close_strength,
        stale_trend_repair_penalty=stale_trend_repair_penalty,
        extension_without_room_penalty=extension_without_room_penalty,
        profile=profile,
    )
    effective_near_miss_threshold = min(effective_near_miss_threshold, float(profitability_hard_cliff_boundary_relief["effective_near_miss_threshold"]))
    effective_stale_score_penalty_weight = float(prepared_breakout_penalty_relief["effective_stale_score_penalty_weight"])
    effective_extension_score_penalty_weight = float(prepared_breakout_penalty_relief["effective_extension_score_penalty_weight"])

    weighted_positive_contributions = {
        "breakout_freshness": round(positive_score_weights["breakout_freshness"] * breakout_freshness, 4),
        "trend_acceleration": round(positive_score_weights["trend_acceleration"] * trend_acceleration, 4),
        "volume_expansion_quality": round(positive_score_weights["volume_expansion_quality"] * volume_expansion_quality, 4),
        "close_strength": round(positive_score_weights["close_strength"] * close_strength, 4),
        "sector_resonance": round(positive_score_weights["sector_resonance"] * sector_resonance, 4),
        "catalyst_freshness": round(positive_score_weights["catalyst_freshness"] * catalyst_freshness, 4),
        "layer_c_alignment": round(positive_score_weights["layer_c_alignment"] * layer_c_alignment, 4),
    }
    weighted_negative_contributions = {
        "stale_trend_repair_penalty": round(effective_stale_score_penalty_weight * stale_trend_repair_penalty, 4),
        "overhead_supply_penalty": round(profile.overhead_score_penalty_weight * overhead_supply_penalty, 4),
        "extension_without_room_penalty": round(effective_extension_score_penalty_weight * extension_without_room_penalty, 4),
        "layer_c_avoid_penalty": round(layer_c_avoid_penalty, 4),
        "watchlist_zero_catalyst_penalty": round(effective_watchlist_zero_catalyst_penalty, 4),
        "watchlist_zero_catalyst_crowded_penalty": round(effective_watchlist_zero_catalyst_crowded_penalty, 4),
        "watchlist_zero_catalyst_flat_trend_penalty": round(effective_watchlist_zero_catalyst_flat_trend_penalty, 4),
    }
    total_positive_contribution = round(sum(weighted_positive_contributions.values()), 4)
    total_negative_contribution = round(sum(weighted_negative_contributions.values()), 4)

    score_target = clamp_unit_interval(
        (positive_score_weights["breakout_freshness"] * breakout_freshness)
        + (positive_score_weights["trend_acceleration"] * trend_acceleration)
        + (positive_score_weights["volume_expansion_quality"] * volume_expansion_quality)
        + (positive_score_weights["close_strength"] * close_strength)
        + (positive_score_weights["sector_resonance"] * sector_resonance)
        + (positive_score_weights["catalyst_freshness"] * catalyst_freshness)
        + (positive_score_weights["layer_c_alignment"] * layer_c_alignment)
        - (effective_stale_score_penalty_weight * stale_trend_repair_penalty)
        - (profile.overhead_score_penalty_weight * overhead_supply_penalty)
        - (effective_extension_score_penalty_weight * extension_without_room_penalty)
        - layer_c_avoid_penalty
        - effective_watchlist_zero_catalyst_penalty
        - effective_watchlist_zero_catalyst_crowded_penalty
        - effective_watchlist_zero_catalyst_flat_trend_penalty
    )
    selected_score_tolerance = _resolve_selected_score_tolerance(
        score_target=score_target,
        effective_select_threshold=effective_select_threshold,
        upstream_shadow_catalyst_relief_applied=bool(catalyst_relief["applied"]),
        upstream_shadow_catalyst_relief_reason=str(catalyst_relief["reason"]),
        historical_prior=historical_prior,
    )

    return {
        "prepared_breakout_penalty_relief": prepared_breakout_penalty_relief,
        "prepared_breakout_catalyst_relief": prepared_breakout_catalyst_relief,
        "prepared_breakout_volume_relief": prepared_breakout_volume_relief,
        "prepared_breakout_continuation_relief": prepared_breakout_continuation_relief,
        "prepared_breakout_selected_catalyst_relief": prepared_breakout_selected_catalyst_relief,
        "profitability_relief": profitability_relief,
        "profitability_hard_cliff_boundary_relief": profitability_hard_cliff_boundary_relief,
        "historical_execution_relief": historical_execution_relief,
        "historical_prior": historical_prior,
        "upstream_shadow_catalyst_relief": catalyst_relief,
        "visibility_gap_continuation_relief": visibility_gap_continuation_relief,
        "merge_approved_continuation_relief": merge_approved_continuation_relief,
        "watchlist_zero_catalyst_penalty": watchlist_zero_catalyst_penalty,
        "watchlist_zero_catalyst_crowded_penalty": watchlist_zero_catalyst_crowded_penalty,
        "watchlist_zero_catalyst_flat_trend_penalty": watchlist_zero_catalyst_flat_trend_penalty,
        "t_plus_2_continuation_candidate": t_plus_2_continuation_candidate,
        "positive_score_weights": positive_score_weights,
        "weighted_positive_contributions": weighted_positive_contributions,
        "weighted_negative_contributions": weighted_negative_contributions,
        "total_positive_contribution": total_positive_contribution,
        "total_negative_contribution": total_negative_contribution,
        "score_target": score_target,
        "selected_score_tolerance": selected_score_tolerance,
        "effective_near_miss_threshold": effective_near_miss_threshold,
        "effective_select_threshold": effective_select_threshold,
        "catalyst_freshness": catalyst_freshness,
        "breakout_freshness": breakout_freshness,
        "trend_acceleration": trend_acceleration,
        "volume_expansion_quality": volume_expansion_quality,
        "layer_c_avoid_penalty": layer_c_avoid_penalty,
        "watchlist_zero_catalyst_penalty_effective": effective_watchlist_zero_catalyst_penalty,
        "watchlist_zero_catalyst_crowded_penalty_effective": effective_watchlist_zero_catalyst_crowded_penalty,
        "watchlist_zero_catalyst_flat_trend_penalty_effective": effective_watchlist_zero_catalyst_flat_trend_penalty,
        "stale_trend_repair_penalty": stale_trend_repair_penalty,
        "overhead_supply_penalty": overhead_supply_penalty,
        "extension_without_room_penalty": extension_without_room_penalty,
    }


def _append_short_trade_snapshot_profitability_tags(
    *,
    input_data: TargetEvaluationInput,
    profitability_relief: dict[str, Any],
    profitability_hard_cliff_boundary_relief: dict[str, Any],
    historical_execution_relief: dict[str, Any],
    positive_tags: list[str],
    negative_tags: list[str],
) -> None:
    if input_data.layer_c_decision == "avoid":
        negative_tags.append("layer_c_avoid_signal")
    if profitability_relief["hard_cliff"]:
        negative_tags.append("profitability_hard_cliff")
    if profitability_relief["relief_applied"]:
        positive_tags.append("profitability_relief_applied")
    elif profitability_relief["relief_enabled"] and profitability_relief["hard_cliff"] and input_data.layer_c_decision == "avoid":
        negative_tags.append("profitability_relief_not_triggered")
    if profitability_hard_cliff_boundary_relief["applied"]:
        positive_tags.append("profitability_hard_cliff_boundary_relief_applied")
    if historical_execution_relief["applied"]:
        positive_tags.append("historical_execution_relief_applied")


def _append_short_trade_snapshot_catalyst_tags(
    *,
    raw_catalyst_freshness: float,
    catalyst_relief: dict[str, Any],
    positive_tags: list[str],
    negative_tags: list[str],
) -> None:
    if catalyst_relief["applied"]:
        if str(catalyst_relief["reason"]) == "catalyst_theme_short_trade_carryover":
            positive_tags.append("catalyst_theme_short_trade_carryover_applied")
        else:
            positive_tags.append("upstream_shadow_catalyst_relief_applied")
    elif catalyst_relief["enabled"] and raw_catalyst_freshness < float(catalyst_relief["catalyst_freshness_floor"]):
        if str(catalyst_relief["reason"]) == "catalyst_theme_short_trade_carryover":
            negative_tags.append("catalyst_theme_short_trade_carryover_not_triggered")
        else:
            negative_tags.append("upstream_shadow_catalyst_relief_not_triggered")


def _append_short_trade_snapshot_continuation_relief_tags(
    *,
    visibility_gap_continuation_relief: dict[str, Any],
    merge_approved_continuation_relief: dict[str, Any],
    prepared_breakout_penalty_relief: dict[str, Any],
    prepared_breakout_catalyst_relief: dict[str, Any],
    prepared_breakout_volume_relief: dict[str, Any],
    prepared_breakout_continuation_relief: dict[str, Any],
    prepared_breakout_selected_catalyst_relief: dict[str, Any],
    positive_tags: list[str],
) -> None:
    if visibility_gap_continuation_relief["applied"]:
        positive_tags.append("visibility_gap_continuation_relief_applied")
    if merge_approved_continuation_relief["applied"]:
        positive_tags.append("merge_approved_continuation_relief_applied")
    if prepared_breakout_penalty_relief["applied"]:
        positive_tags.append("prepared_breakout_penalty_relief_applied")
    if prepared_breakout_catalyst_relief["applied"]:
        positive_tags.append("prepared_breakout_catalyst_relief_applied")
    if prepared_breakout_volume_relief["applied"]:
        positive_tags.append("prepared_breakout_volume_relief_applied")
    if prepared_breakout_continuation_relief["applied"]:
        positive_tags.append("prepared_breakout_continuation_relief_applied")
    if prepared_breakout_selected_catalyst_relief["applied"]:
        positive_tags.append("prepared_breakout_selected_catalyst_relief_applied")


def _append_short_trade_snapshot_penalty_tags(
    *,
    watchlist_zero_catalyst_penalty: dict[str, Any],
    watchlist_zero_catalyst_crowded_penalty: dict[str, Any],
    watchlist_zero_catalyst_flat_trend_penalty: dict[str, Any],
    t_plus_2_continuation_candidate: dict[str, Any],
    positive_tags: list[str],
    negative_tags: list[str],
) -> None:
    if watchlist_zero_catalyst_penalty["applied"]:
        negative_tags.append("watchlist_zero_catalyst_penalty_applied")
    if watchlist_zero_catalyst_crowded_penalty["applied"]:
        negative_tags.append("watchlist_zero_catalyst_crowded_penalty_applied")
    if watchlist_zero_catalyst_flat_trend_penalty["applied"]:
        negative_tags.append("watchlist_zero_catalyst_flat_trend_penalty_applied")
    if t_plus_2_continuation_candidate["applied"]:
        positive_tags.append("t_plus_2_continuation_candidate")


def _append_short_trade_snapshot_blockers(
    *,
    input_data: TargetEvaluationInput,
    profile: Any,
    trend_signal: Any,
    stale_trend_repair_penalty: float,
    overhead_supply_penalty: float,
    extension_without_room_penalty: float,
    blockers: list[str],
    gate_status: dict[str, Any],
) -> None:
    if trend_signal is None or float(trend_signal.completeness) <= 0:
        blockers.append("missing_trend_signal")
        gate_status["data"] = "fail"
    if input_data.bc_conflict in profile.hard_block_bearish_conflicts:
        blockers.append("layer_c_bearish_conflict")
        gate_status["structural"] = "fail"
    if _signal_signed_strength(trend_signal) <= 0.0:
        blockers.append("trend_not_constructive")
        gate_status["structural"] = "fail"
    if stale_trend_repair_penalty >= profile.stale_penalty_block_threshold:
        blockers.append("stale_trend_repair_penalty")
        gate_status["structural"] = "fail"
    if overhead_supply_penalty >= profile.overhead_penalty_block_threshold:
        blockers.append("overhead_supply_penalty")
        gate_status["structural"] = "fail"
    if extension_without_room_penalty >= profile.extension_penalty_block_threshold:
        blockers.append("extension_without_room_penalty")
        gate_status["structural"] = "fail"


def _append_short_trade_snapshot_strength_tags(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    catalyst_freshness: float,
    sector_resonance: float,
    event_signal: Any,
    positive_tags: list[str],
    negative_tags: list[str],
) -> None:
    if event_signal is None or float(event_signal.completeness) <= 0:
        negative_tags.append("event_signal_incomplete")
    if breakout_freshness >= 0.50:
        positive_tags.append("fresh_breakout_candidate")
    if trend_acceleration >= 0.50:
        positive_tags.append("trend_acceleration_confirmed")
    if catalyst_freshness >= 0.45:
        positive_tags.append("fresh_catalyst_support")
    if sector_resonance >= 0.45:
        positive_tags.append("sector_alignment_support")
    if input_data.execution_constraints.get("included_in_buy_orders"):
        positive_tags.append("execution_bridge_ready")


def _collect_short_trade_snapshot_labels_and_gates(
    input_data: TargetEvaluationInput,
    *,
    profile: Any,
    signal_snapshot: dict[str, Any],
    relief_snapshot: dict[str, Any],
) -> dict[str, Any]:
    trend_signal = signal_snapshot["trend_signal"]
    event_signal = signal_snapshot["event_signal"]
    breakout_freshness = float(relief_snapshot["breakout_freshness"])
    trend_acceleration = float(relief_snapshot["trend_acceleration"])
    raw_catalyst_freshness = float(signal_snapshot["raw_catalyst_freshness"])
    catalyst_freshness = float(relief_snapshot["catalyst_freshness"])
    sector_resonance = float(signal_snapshot["sector_resonance"])
    profitability_relief = dict(relief_snapshot["profitability_relief"])
    profitability_hard_cliff_boundary_relief = dict(relief_snapshot["profitability_hard_cliff_boundary_relief"])
    historical_execution_relief = dict(relief_snapshot["historical_execution_relief"])
    catalyst_relief = dict(relief_snapshot["upstream_shadow_catalyst_relief"])
    visibility_gap_continuation_relief = dict(relief_snapshot["visibility_gap_continuation_relief"])
    merge_approved_continuation_relief = dict(relief_snapshot["merge_approved_continuation_relief"])
    prepared_breakout_penalty_relief = dict(relief_snapshot["prepared_breakout_penalty_relief"])
    prepared_breakout_catalyst_relief = dict(relief_snapshot["prepared_breakout_catalyst_relief"])
    prepared_breakout_volume_relief = dict(relief_snapshot["prepared_breakout_volume_relief"])
    prepared_breakout_continuation_relief = dict(relief_snapshot["prepared_breakout_continuation_relief"])
    prepared_breakout_selected_catalyst_relief = dict(relief_snapshot["prepared_breakout_selected_catalyst_relief"])
    watchlist_zero_catalyst_penalty = dict(relief_snapshot["watchlist_zero_catalyst_penalty"])
    watchlist_zero_catalyst_crowded_penalty = dict(relief_snapshot["watchlist_zero_catalyst_crowded_penalty"])
    watchlist_zero_catalyst_flat_trend_penalty = dict(relief_snapshot["watchlist_zero_catalyst_flat_trend_penalty"])
    t_plus_2_continuation_candidate = dict(relief_snapshot["t_plus_2_continuation_candidate"])
    stale_trend_repair_penalty = float(relief_snapshot["stale_trend_repair_penalty"])
    overhead_supply_penalty = float(relief_snapshot["overhead_supply_penalty"])
    extension_without_room_penalty = float(relief_snapshot["extension_without_room_penalty"])

    positive_tags: list[str] = []
    negative_tags: list[str] = []
    blockers: list[str] = []
    gate_status = {
        "data": "pass",
        "execution": "pass" if input_data.execution_constraints.get("included_in_buy_orders") else "proxy_only",
        "structural": "pass",
        "score": "fail",
    }

    _append_short_trade_snapshot_profitability_tags(
        input_data=input_data,
        profitability_relief=profitability_relief,
        profitability_hard_cliff_boundary_relief=profitability_hard_cliff_boundary_relief,
        historical_execution_relief=historical_execution_relief,
        positive_tags=positive_tags,
        negative_tags=negative_tags,
    )
    _append_short_trade_snapshot_catalyst_tags(
        raw_catalyst_freshness=raw_catalyst_freshness,
        catalyst_relief=catalyst_relief,
        positive_tags=positive_tags,
        negative_tags=negative_tags,
    )
    _append_short_trade_snapshot_continuation_relief_tags(
        visibility_gap_continuation_relief=visibility_gap_continuation_relief,
        merge_approved_continuation_relief=merge_approved_continuation_relief,
        prepared_breakout_penalty_relief=prepared_breakout_penalty_relief,
        prepared_breakout_catalyst_relief=prepared_breakout_catalyst_relief,
        prepared_breakout_volume_relief=prepared_breakout_volume_relief,
        prepared_breakout_continuation_relief=prepared_breakout_continuation_relief,
        prepared_breakout_selected_catalyst_relief=prepared_breakout_selected_catalyst_relief,
        positive_tags=positive_tags,
    )
    _append_short_trade_snapshot_penalty_tags(
        watchlist_zero_catalyst_penalty=watchlist_zero_catalyst_penalty,
        watchlist_zero_catalyst_crowded_penalty=watchlist_zero_catalyst_crowded_penalty,
        watchlist_zero_catalyst_flat_trend_penalty=watchlist_zero_catalyst_flat_trend_penalty,
        t_plus_2_continuation_candidate=t_plus_2_continuation_candidate,
        positive_tags=positive_tags,
        negative_tags=negative_tags,
    )
    _append_short_trade_snapshot_blockers(
        input_data=input_data,
        profile=profile,
        trend_signal=trend_signal,
        stale_trend_repair_penalty=stale_trend_repair_penalty,
        overhead_supply_penalty=overhead_supply_penalty,
        extension_without_room_penalty=extension_without_room_penalty,
        blockers=blockers,
        gate_status=gate_status,
    )
    _append_short_trade_snapshot_strength_tags(
        input_data=input_data,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        catalyst_freshness=catalyst_freshness,
        sector_resonance=sector_resonance,
        event_signal=event_signal,
        positive_tags=positive_tags,
        negative_tags=negative_tags,
    )

    return {
        "positive_tags": positive_tags,
        "negative_tags": negative_tags,
        "blockers": blockers,
        "gate_status": gate_status,
    }


def _build_short_trade_target_snapshot(input_data: TargetEvaluationInput) -> dict[str, Any]:
    profile = get_active_short_trade_target_profile()
    signal_snapshot = _compute_short_trade_signal_snapshot(input_data, profile=profile)
    relief_snapshot = _resolve_short_trade_snapshot_reliefs(
        input_data,
        profile=profile,
        signal_snapshot=signal_snapshot,
    )
    labels_and_gates = _collect_short_trade_snapshot_labels_and_gates(
        input_data,
        profile=profile,
        signal_snapshot=signal_snapshot,
        relief_snapshot=relief_snapshot,
    )

    volatility_metrics = dict(signal_snapshot["volatility_metrics"])
    profitability_relief = dict(relief_snapshot["profitability_relief"])
    profitability_hard_cliff_boundary_relief = dict(relief_snapshot["profitability_hard_cliff_boundary_relief"])
    historical_execution_relief = dict(relief_snapshot["historical_execution_relief"])
    catalyst_relief = dict(relief_snapshot["upstream_shadow_catalyst_relief"])
    watchlist_zero_catalyst_penalty = dict(relief_snapshot["watchlist_zero_catalyst_penalty"])
    watchlist_zero_catalyst_crowded_penalty = dict(relief_snapshot["watchlist_zero_catalyst_crowded_penalty"])
    watchlist_zero_catalyst_flat_trend_penalty = dict(relief_snapshot["watchlist_zero_catalyst_flat_trend_penalty"])

    return {
        "profile": profile,
        "breakout_freshness": relief_snapshot["breakout_freshness"],
        "trend_acceleration": relief_snapshot["trend_acceleration"],
        "volume_expansion_quality": relief_snapshot["volume_expansion_quality"],
        "close_strength": signal_snapshot["close_strength"],
        "sector_resonance": signal_snapshot["sector_resonance"],
        "raw_catalyst_freshness": signal_snapshot["raw_catalyst_freshness"],
        "catalyst_freshness": relief_snapshot["catalyst_freshness"],
        "layer_c_alignment": signal_snapshot["layer_c_alignment"],
        "effective_near_miss_threshold": relief_snapshot["effective_near_miss_threshold"],
        "effective_select_threshold": relief_snapshot["effective_select_threshold"],
        "selected_score_tolerance": relief_snapshot["selected_score_tolerance"],
        "profitability_hard_cliff": profitability_relief["hard_cliff"],
        "profitability_positive_count": profitability_relief["profitability_positive_count"],
        "profitability_confidence": profitability_relief["profitability_confidence"],
        "profitability_relief_enabled": profitability_relief["relief_enabled"],
        "profitability_relief_gate_hits": profitability_relief["relief_gate_hits"],
        "profitability_relief_eligible": profitability_relief["relief_eligible"],
        "profitability_relief_applied": profitability_relief["relief_applied"],
        "profitability_hard_cliff_boundary_relief": profitability_hard_cliff_boundary_relief,
        "profitability_relief_soft_penalty": profitability_relief["soft_penalty"],
        "base_layer_c_avoid_penalty": profitability_relief["base_layer_c_avoid_penalty"],
        "layer_c_avoid_penalty": relief_snapshot["layer_c_avoid_penalty"],
        "watchlist_zero_catalyst_guard": watchlist_zero_catalyst_penalty,
        "watchlist_zero_catalyst_penalty": relief_snapshot["watchlist_zero_catalyst_penalty_effective"],
        "watchlist_zero_catalyst_crowded_guard": watchlist_zero_catalyst_crowded_penalty,
        "watchlist_zero_catalyst_crowded_penalty": relief_snapshot["watchlist_zero_catalyst_crowded_penalty_effective"],
        "watchlist_zero_catalyst_flat_trend_guard": watchlist_zero_catalyst_flat_trend_penalty,
        "watchlist_zero_catalyst_flat_trend_penalty": relief_snapshot["watchlist_zero_catalyst_flat_trend_penalty_effective"],
        "t_plus_2_continuation_candidate": relief_snapshot["t_plus_2_continuation_candidate"],
        "upstream_shadow_catalyst_relief_enabled": catalyst_relief["enabled"],
        "upstream_shadow_catalyst_relief_gate_hits": catalyst_relief["gate_hits"],
        "upstream_shadow_catalyst_relief_eligible": catalyst_relief["eligible"],
        "upstream_shadow_catalyst_relief_applied": catalyst_relief["applied"],
        "upstream_shadow_catalyst_relief_reason": catalyst_relief["reason"],
        "upstream_shadow_catalyst_relief_catalyst_freshness_floor": catalyst_relief["catalyst_freshness_floor"],
        "upstream_shadow_catalyst_relief_base_near_miss_threshold": catalyst_relief["base_near_miss_threshold"],
        "upstream_shadow_catalyst_relief_near_miss_threshold_override": catalyst_relief["near_miss_threshold_override"],
        "upstream_shadow_catalyst_relief_base_select_threshold": catalyst_relief["base_select_threshold"],
        "upstream_shadow_catalyst_relief_select_threshold_override": catalyst_relief["select_threshold_override"],
        "upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff": catalyst_relief["require_no_profitability_hard_cliff"],
        "visibility_gap_continuation_relief": relief_snapshot["visibility_gap_continuation_relief"],
        "merge_approved_continuation_relief": relief_snapshot["merge_approved_continuation_relief"],
        "historical_execution_relief": historical_execution_relief,
        "historical_prior": relief_snapshot["historical_prior"],
        "prepared_breakout_penalty_relief": relief_snapshot["prepared_breakout_penalty_relief"],
        "prepared_breakout_catalyst_relief": relief_snapshot["prepared_breakout_catalyst_relief"],
        "prepared_breakout_volume_relief": relief_snapshot["prepared_breakout_volume_relief"],
        "prepared_breakout_continuation_relief": relief_snapshot["prepared_breakout_continuation_relief"],
        "prepared_breakout_selected_catalyst_relief": relief_snapshot["prepared_breakout_selected_catalyst_relief"],
        "stale_trend_repair_penalty": relief_snapshot["stale_trend_repair_penalty"],
        "overhead_supply_penalty": relief_snapshot["overhead_supply_penalty"],
        "extension_without_room_penalty": relief_snapshot["extension_without_room_penalty"],
        "positive_score_weights": relief_snapshot["positive_score_weights"],
        "weighted_positive_contributions": relief_snapshot["weighted_positive_contributions"],
        "weighted_negative_contributions": relief_snapshot["weighted_negative_contributions"],
        "total_positive_contribution": relief_snapshot["total_positive_contribution"],
        "total_negative_contribution": relief_snapshot["total_negative_contribution"],
        "score_target": relief_snapshot["score_target"],
        "positive_tags": labels_and_gates["positive_tags"],
        "negative_tags": labels_and_gates["negative_tags"],
        "blockers": labels_and_gates["blockers"],
        "gate_status": labels_and_gates["gate_status"],
        "score_b_strength": signal_snapshot["score_b_strength"],
        "score_c_strength": signal_snapshot["score_c_strength"],
        "score_final_strength": signal_snapshot["score_final_strength"],
        "momentum_strength": signal_snapshot["momentum_strength"],
        "momentum_1m": signal_snapshot["momentum_1m"],
        "momentum_3m": signal_snapshot["momentum_3m"],
        "momentum_6m": signal_snapshot["momentum_6m"],
        "volume_momentum": signal_snapshot["volume_momentum"],
        "adx_strength": signal_snapshot["adx_strength"],
        "ema_strength": signal_snapshot["ema_strength"],
        "volatility_strength": signal_snapshot["volatility_strength"],
        "volatility_regime": float(volatility_metrics.get("volatility_regime", 0.0) or 0.0),
        "atr_ratio": float(volatility_metrics.get("atr_ratio", 0.0) or 0.0),
        "long_trend_strength": signal_snapshot["long_trend_strength"],
        "event_freshness_strength": signal_snapshot["event_freshness_strength"],
        "news_sentiment_strength": signal_snapshot["news_sentiment_strength"],
        "event_signal_strength": signal_snapshot["event_signal_strength"],
        "mean_reversion_strength": signal_snapshot["mean_reversion_strength"],
        "analyst_alignment": signal_snapshot["analyst_alignment"],
        "investor_alignment": signal_snapshot["investor_alignment"],
        "analyst_penalty": signal_snapshot["analyst_penalty"],
        "investor_penalty": signal_snapshot["investor_penalty"],
    }


def _resolve_short_trade_decision(
    *,
    blockers: list[str],
    gate_status: dict[str, Any],
    score_target: float,
    effective_near_miss_threshold: float,
    effective_select_threshold: float,
    selected_score_tolerance: float,
    selected_breakout_gate_pass: bool,
    near_miss_breakout_gate_pass: bool,
    carryover_evidence_deficiency: dict[str, Any],
) -> str:
    selected_score_pass = score_target >= (effective_select_threshold - selected_score_tolerance)

    if blockers:
        decision = "blocked" if gate_status["data"] == "fail" or "layer_c_bearish_conflict" in blockers or "trend_not_constructive" in blockers else "rejected"
    elif selected_score_pass and selected_breakout_gate_pass:
        decision = "selected"
        gate_status["score"] = "pass"
    elif selected_score_pass and near_miss_breakout_gate_pass:
        decision = "near_miss"
        gate_status["score"] = "near_miss"
    elif score_target >= effective_near_miss_threshold and near_miss_breakout_gate_pass:
        decision = "near_miss"
        gate_status["score"] = "near_miss"
    else:
        decision = "rejected"

    if carryover_evidence_deficiency["evidence_deficient"] and decision in {"selected", "near_miss"}:
        gate_status["score"] = "fail"
        return "rejected"
    return decision


def _annotate_short_trade_tags(
    *,
    positive_tags: list[str],
    negative_tags: list[str],
    breakout_stage: str,
    carryover_evidence_deficiency: dict[str, Any],
) -> None:
    if breakout_stage == "confirmed_breakout":
        positive_tags.append("confirmed_breakout_stage")
    elif breakout_stage == "prepared_breakout":
        positive_tags.append("prepared_breakout_stage")

    if carryover_evidence_deficiency["evidence_deficient"]:
        negative_tags.append("evidence_deficient_broad_family_only")


def _build_short_trade_top_reasons(
    *,
    breakout_freshness: float,
    trend_acceleration: float,
    raw_catalyst_freshness: float,
    upstream_shadow_catalyst_relief_applied: bool,
    upstream_shadow_catalyst_relief_reason: str,
    visibility_gap_continuation_relief: dict[str, Any],
    merge_approved_continuation_relief: dict[str, Any],
    prepared_breakout_penalty_relief: dict[str, Any],
    prepared_breakout_catalyst_relief: dict[str, Any],
    prepared_breakout_volume_relief: dict[str, Any],
    prepared_breakout_continuation_relief: dict[str, Any],
    prepared_breakout_selected_catalyst_relief: dict[str, Any],
    profitability_relief_applied: bool,
    profitability_hard_cliff_boundary_relief: dict[str, Any],
    historical_execution_relief: dict[str, Any],
    profitability_hard_cliff: bool,
    breakout_stage: str,
    layer_c_avoid_penalty: float,
    stale_trend_repair_penalty: float,
    overhead_supply_penalty: float,
    extension_without_room_penalty: float,
    watchlist_zero_catalyst_guard: dict[str, Any],
    watchlist_zero_catalyst_crowded_guard: dict[str, Any],
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any],
    carryover_evidence_deficiency: dict[str, Any],
    t_plus_2_continuation_candidate: dict[str, Any],
    score_target: float,
) -> list[str]:
    return trim_reasons(
        [
            reason
            for reason in [
                _summarize_positive_factor("breakout_freshness", breakout_freshness),
                _summarize_positive_factor("trend_acceleration", trend_acceleration),
                _summarize_positive_factor("catalyst_freshness", raw_catalyst_freshness),
                upstream_shadow_catalyst_relief_reason if upstream_shadow_catalyst_relief_applied else None,
                "visibility_gap_continuation_relief" if visibility_gap_continuation_relief["applied"] else None,
                "merge_approved_continuation_relief" if merge_approved_continuation_relief["applied"] else None,
                "prepared_breakout_penalty_relief" if prepared_breakout_penalty_relief["applied"] else None,
                "prepared_breakout_catalyst_relief" if prepared_breakout_catalyst_relief["applied"] else None,
                "prepared_breakout_volume_relief" if prepared_breakout_volume_relief["applied"] else None,
                "prepared_breakout_continuation_relief" if prepared_breakout_continuation_relief["applied"] else None,
                "prepared_breakout_selected_catalyst_relief" if prepared_breakout_selected_catalyst_relief["applied"] else None,
                "profitability_relief_applied" if profitability_relief_applied else None,
                "profitability_hard_cliff_boundary_relief" if profitability_hard_cliff_boundary_relief.get("applied") else None,
                "historical_execution_relief" if historical_execution_relief.get("applied") else None,
                "profitability_hard_cliff" if profitability_hard_cliff and not profitability_relief_applied else None,
                breakout_stage,
                _summarize_penalty("layer_c_avoid_penalty", layer_c_avoid_penalty),
                _summarize_penalty("stale_trend_repair_penalty", stale_trend_repair_penalty),
                _summarize_penalty("overhead_supply_penalty", overhead_supply_penalty),
                _summarize_penalty("extension_without_room_penalty", extension_without_room_penalty),
                "watchlist_zero_catalyst_penalty_applied" if watchlist_zero_catalyst_guard["applied"] else None,
                "watchlist_zero_catalyst_crowded_penalty_applied" if watchlist_zero_catalyst_crowded_guard["applied"] else None,
                "watchlist_zero_catalyst_flat_trend_penalty_applied" if watchlist_zero_catalyst_flat_trend_guard["applied"] else None,
                "evidence_deficient_broad_family_only" if carryover_evidence_deficiency["evidence_deficient"] else None,
                "t_plus_2_continuation_candidate" if t_plus_2_continuation_candidate["applied"] else None,
                f"score_short={score_target:.2f}",
            ]
            if reason is not None
        ]
    )


def _build_short_trade_rejection_reasons(
    *,
    decision: str,
    blockers: list[str],
    breakout_freshness: float,
    trend_acceleration: float,
    effective_near_miss_threshold: float,
    score_target: float,
    near_miss_breakout_gate_pass: bool,
    profile: Any,
    carryover_evidence_deficiency: dict[str, Any],
) -> list[str]:
    rejection_reasons = trim_reasons(
        blockers
        if blockers
        else _collect_breakout_gate_misses(
            breakout_freshness=breakout_freshness,
            trend_acceleration=trend_acceleration,
            breakout_min=float(profile.near_miss_breakout_freshness_min),
            trend_min=float(profile.near_miss_trend_acceleration_min),
            label="near_miss",
        )
        if decision == "rejected" and score_target >= effective_near_miss_threshold and not near_miss_breakout_gate_pass
        else ["score_short_below_threshold"]
        if decision == "rejected"
        else []
    )
    if decision == "rejected" and carryover_evidence_deficiency["evidence_deficient"]:
        return trim_reasons(["evidence_deficient_broad_family_only", *rejection_reasons])
    return rejection_reasons


def build_short_trade_target_snapshot_from_entry(
    *,
    trade_date: str,
    entry: dict[str, Any],
    profile_name: str | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if profile_name is not None or profile_overrides:
        with use_short_trade_target_profile(profile_name=profile_name or "default", overrides=profile_overrides):
            return build_short_trade_target_snapshot_from_entry(
                trade_date=trade_date,
                entry=entry,
            )
    return _build_short_trade_target_snapshot(_build_target_input_from_entry(trade_date=trade_date, entry=entry))


def _evaluate_short_trade_target(input_data: TargetEvaluationInput, *, rank_hint: int | None = None) -> TargetEvaluationResult:
    snapshot = _build_short_trade_target_snapshot(input_data)
    profile = snapshot["profile"]
    breakout_freshness = float(snapshot["breakout_freshness"])
    trend_acceleration = float(snapshot["trend_acceleration"])
    raw_catalyst_freshness = float(snapshot["raw_catalyst_freshness"])
    catalyst_freshness = float(snapshot["catalyst_freshness"])
    score_target = float(snapshot["score_target"])
    effective_near_miss_threshold = float(snapshot["effective_near_miss_threshold"])
    effective_select_threshold = float(snapshot["effective_select_threshold"])
    base_layer_c_avoid_penalty = float(snapshot["base_layer_c_avoid_penalty"])
    layer_c_avoid_penalty = float(snapshot["layer_c_avoid_penalty"])
    watchlist_zero_catalyst_guard = dict(snapshot["watchlist_zero_catalyst_guard"])
    effective_watchlist_zero_catalyst_penalty = float(snapshot["watchlist_zero_catalyst_penalty"])
    watchlist_zero_catalyst_crowded_guard = dict(snapshot["watchlist_zero_catalyst_crowded_guard"])
    effective_watchlist_zero_catalyst_crowded_penalty = float(snapshot["watchlist_zero_catalyst_crowded_penalty"])
    watchlist_zero_catalyst_flat_trend_guard = dict(snapshot["watchlist_zero_catalyst_flat_trend_guard"])
    effective_watchlist_zero_catalyst_flat_trend_penalty = float(snapshot["watchlist_zero_catalyst_flat_trend_penalty"])
    t_plus_2_continuation_candidate = dict(snapshot["t_plus_2_continuation_candidate"])
    profitability_hard_cliff = bool(snapshot["profitability_hard_cliff"])
    profitability_positive_count = snapshot["profitability_positive_count"]
    profitability_confidence = float(snapshot["profitability_confidence"])
    profitability_relief_enabled = bool(snapshot["profitability_relief_enabled"])
    profitability_relief_gate_hits = dict(snapshot["profitability_relief_gate_hits"])
    profitability_relief_eligible = bool(snapshot["profitability_relief_eligible"])
    profitability_relief_applied = bool(snapshot["profitability_relief_applied"])
    profitability_hard_cliff_boundary_relief = dict(snapshot["profitability_hard_cliff_boundary_relief"])
    historical_execution_relief = dict(snapshot["historical_execution_relief"])
    historical_prior = dict(snapshot["historical_prior"])
    carryover_evidence_deficiency = _resolve_carryover_evidence_deficiency(input_data)
    profitability_relief_soft_penalty = float(snapshot["profitability_relief_soft_penalty"])
    upstream_shadow_catalyst_relief_enabled = bool(snapshot["upstream_shadow_catalyst_relief_enabled"])
    upstream_shadow_catalyst_relief_gate_hits = dict(snapshot["upstream_shadow_catalyst_relief_gate_hits"])
    upstream_shadow_catalyst_relief_eligible = bool(snapshot["upstream_shadow_catalyst_relief_eligible"])
    upstream_shadow_catalyst_relief_applied = bool(snapshot["upstream_shadow_catalyst_relief_applied"])
    upstream_shadow_catalyst_relief_reason = str(snapshot["upstream_shadow_catalyst_relief_reason"])
    upstream_shadow_catalyst_relief_catalyst_freshness_floor = float(snapshot["upstream_shadow_catalyst_relief_catalyst_freshness_floor"])
    upstream_shadow_catalyst_relief_base_near_miss_threshold = float(snapshot["upstream_shadow_catalyst_relief_base_near_miss_threshold"])
    upstream_shadow_catalyst_relief_near_miss_threshold_override = float(snapshot["upstream_shadow_catalyst_relief_near_miss_threshold_override"])
    upstream_shadow_catalyst_relief_base_select_threshold = float(snapshot["upstream_shadow_catalyst_relief_base_select_threshold"])
    upstream_shadow_catalyst_relief_select_threshold_override = float(snapshot["upstream_shadow_catalyst_relief_select_threshold_override"])
    upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff = bool(snapshot["upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff"])
    selected_score_tolerance = float(snapshot["selected_score_tolerance"])
    visibility_gap_continuation_relief = dict(snapshot["visibility_gap_continuation_relief"])
    merge_approved_continuation_relief = dict(snapshot["merge_approved_continuation_relief"])
    prepared_breakout_penalty_relief = dict(snapshot["prepared_breakout_penalty_relief"])
    prepared_breakout_catalyst_relief = dict(snapshot["prepared_breakout_catalyst_relief"])
    prepared_breakout_volume_relief = dict(snapshot["prepared_breakout_volume_relief"])
    prepared_breakout_continuation_relief = dict(snapshot["prepared_breakout_continuation_relief"])
    prepared_breakout_selected_catalyst_relief = dict(snapshot["prepared_breakout_selected_catalyst_relief"])
    stale_trend_repair_penalty = float(snapshot["stale_trend_repair_penalty"])
    overhead_supply_penalty = float(snapshot["overhead_supply_penalty"])
    extension_without_room_penalty = float(snapshot["extension_without_room_penalty"])
    weighted_positive_contributions = dict(snapshot["weighted_positive_contributions"])
    weighted_negative_contributions = dict(snapshot["weighted_negative_contributions"])
    total_positive_contribution = float(snapshot["total_positive_contribution"])
    total_negative_contribution = float(snapshot["total_negative_contribution"])
    positive_tags = list(snapshot["positive_tags"])
    negative_tags = list(snapshot["negative_tags"])
    blockers = list(snapshot["blockers"])
    gate_status = dict(snapshot["gate_status"])
    score_b_strength = float(snapshot["score_b_strength"])
    score_c_strength = float(snapshot["score_c_strength"])
    score_final_strength = float(snapshot["score_final_strength"])
    momentum_strength = float(snapshot["momentum_strength"])
    momentum_1m = float(snapshot["momentum_1m"])
    momentum_3m = float(snapshot["momentum_3m"])
    momentum_6m = float(snapshot["momentum_6m"])
    volume_momentum = float(snapshot["volume_momentum"])
    adx_strength = float(snapshot["adx_strength"])
    ema_strength = float(snapshot["ema_strength"])
    volatility_strength = float(snapshot["volatility_strength"])
    volatility_regime = float(snapshot["volatility_regime"])
    atr_ratio = float(snapshot["atr_ratio"])
    long_trend_strength = float(snapshot["long_trend_strength"])
    event_freshness_strength = float(snapshot["event_freshness_strength"])
    news_sentiment_strength = float(snapshot["news_sentiment_strength"])
    event_signal_strength = float(snapshot["event_signal_strength"])
    mean_reversion_strength = float(snapshot["mean_reversion_strength"])
    analyst_alignment = float(snapshot["analyst_alignment"])
    investor_alignment = float(snapshot["investor_alignment"])
    analyst_penalty = float(snapshot["analyst_penalty"])
    investor_penalty = float(snapshot["investor_penalty"])
    volume_expansion_quality = float(snapshot["volume_expansion_quality"])
    close_strength = float(snapshot["close_strength"])
    sector_resonance = float(snapshot["sector_resonance"])
    layer_c_alignment = float(snapshot["layer_c_alignment"])
    positive_score_weights = dict(snapshot["positive_score_weights"])
    breakout_stage, selected_breakout_gate_pass, near_miss_breakout_gate_pass = _classify_breakout_stage(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        profile=profile,
    )

    decision = _resolve_short_trade_decision(
        blockers=blockers,
        gate_status=gate_status,
        score_target=score_target,
        effective_near_miss_threshold=effective_near_miss_threshold,
        effective_select_threshold=effective_select_threshold,
        selected_score_tolerance=selected_score_tolerance,
        selected_breakout_gate_pass=selected_breakout_gate_pass,
        near_miss_breakout_gate_pass=near_miss_breakout_gate_pass,
        carryover_evidence_deficiency=carryover_evidence_deficiency,
    )
    _annotate_short_trade_tags(
        positive_tags=positive_tags,
        negative_tags=negative_tags,
        breakout_stage=breakout_stage,
        carryover_evidence_deficiency=carryover_evidence_deficiency,
    )

    top_reasons = _build_short_trade_top_reasons(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        raw_catalyst_freshness=raw_catalyst_freshness,
        upstream_shadow_catalyst_relief_applied=upstream_shadow_catalyst_relief_applied,
        upstream_shadow_catalyst_relief_reason=upstream_shadow_catalyst_relief_reason,
        visibility_gap_continuation_relief=visibility_gap_continuation_relief,
        merge_approved_continuation_relief=merge_approved_continuation_relief,
        prepared_breakout_penalty_relief=prepared_breakout_penalty_relief,
        prepared_breakout_catalyst_relief=prepared_breakout_catalyst_relief,
        prepared_breakout_volume_relief=prepared_breakout_volume_relief,
        prepared_breakout_continuation_relief=prepared_breakout_continuation_relief,
        prepared_breakout_selected_catalyst_relief=prepared_breakout_selected_catalyst_relief,
        profitability_relief_applied=profitability_relief_applied,
        profitability_hard_cliff_boundary_relief=profitability_hard_cliff_boundary_relief,
        historical_execution_relief=historical_execution_relief,
        profitability_hard_cliff=profitability_hard_cliff,
        breakout_stage=breakout_stage,
        layer_c_avoid_penalty=layer_c_avoid_penalty,
        stale_trend_repair_penalty=stale_trend_repair_penalty,
        overhead_supply_penalty=overhead_supply_penalty,
        extension_without_room_penalty=extension_without_room_penalty,
        watchlist_zero_catalyst_guard=watchlist_zero_catalyst_guard,
        watchlist_zero_catalyst_crowded_guard=watchlist_zero_catalyst_crowded_guard,
        watchlist_zero_catalyst_flat_trend_guard=watchlist_zero_catalyst_flat_trend_guard,
        carryover_evidence_deficiency=carryover_evidence_deficiency,
        t_plus_2_continuation_candidate=t_plus_2_continuation_candidate,
        score_target=score_target,
    )
    rejection_reasons = _build_short_trade_rejection_reasons(
        decision=decision,
        blockers=blockers,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        effective_near_miss_threshold=effective_near_miss_threshold,
        score_target=score_target,
        near_miss_breakout_gate_pass=near_miss_breakout_gate_pass,
        profile=profile,
        carryover_evidence_deficiency=carryover_evidence_deficiency,
    )
    confidence = derive_confidence(score_target, breakout_freshness, trend_acceleration, catalyst_freshness, float(input_data.quality_score or 0.0))

    return TargetEvaluationResult(
        target_type="short_trade",
        decision=decision,
        score_target=score_target,
        confidence=confidence,
        rank_hint=rank_hint,
        positive_tags=positive_tags,
        negative_tags=trim_reasons(negative_tags),
        blockers=trim_reasons(blockers),
        top_reasons=top_reasons,
        rejection_reasons=rejection_reasons,
        gate_status=gate_status,
        expected_holding_window="t1_short_trade",
        preferred_entry_mode=_preferred_entry_mode_from_historical_prior(historical_prior),
        candidate_source=str(input_data.replay_context.get("source") or "") or None,
        effective_near_miss_threshold=round(effective_near_miss_threshold, 4),
        effective_select_threshold=round(effective_select_threshold, 4),
        breakout_freshness=round(breakout_freshness, 4),
        trend_acceleration=round(trend_acceleration, 4),
        volume_expansion_quality=round(volume_expansion_quality, 4),
        close_strength=round(close_strength, 4),
        sector_resonance=round(sector_resonance, 4),
        catalyst_freshness=round(raw_catalyst_freshness, 4),
        layer_c_alignment=round(layer_c_alignment, 4),
        weighted_positive_contributions={name: round(float(value), 4) for name, value in weighted_positive_contributions.items()},
        weighted_negative_contributions={name: round(float(value), 4) for name, value in weighted_negative_contributions.items()},
        metrics_payload={
            "score_b": round(float(input_data.score_b), 4),
            "score_c": round(float(input_data.score_c), 4),
            "score_final": round(float(input_data.score_final), 4),
            "quality_score": round(float(input_data.quality_score), 4),
            "score_b_strength": round(score_b_strength, 4),
            "score_c_strength": round(score_c_strength, 4),
            "score_final_strength": round(score_final_strength, 4),
            "momentum_strength": round(momentum_strength, 4),
            "momentum_1m": round(momentum_1m, 4),
            "momentum_3m": round(momentum_3m, 4),
            "momentum_6m": round(momentum_6m, 4),
            "volume_momentum": round(volume_momentum, 4),
            "adx_strength": round(adx_strength, 4),
            "ema_strength": round(ema_strength, 4),
            "volatility_strength": round(volatility_strength, 4),
            "volatility_regime": round(volatility_regime, 4),
            "atr_ratio": round(atr_ratio, 4),
            "long_trend_strength": round(long_trend_strength, 4),
            "event_freshness_strength": round(event_freshness_strength, 4),
            "news_sentiment_strength": round(news_sentiment_strength, 4),
            "event_signal_strength": round(event_signal_strength, 4),
            "mean_reversion_strength": round(mean_reversion_strength, 4),
            "analyst_alignment": round(analyst_alignment, 4),
            "investor_alignment": round(investor_alignment, 4),
            "analyst_penalty": round(analyst_penalty, 4),
            "investor_penalty": round(investor_penalty, 4),
            "breakout_freshness": round(breakout_freshness, 4),
            "trend_acceleration": round(trend_acceleration, 4),
            "volume_expansion_quality": round(volume_expansion_quality, 4),
            "close_strength": round(close_strength, 4),
            "sector_resonance": round(sector_resonance, 4),
            "catalyst_freshness": round(raw_catalyst_freshness, 4),
            "effective_catalyst_freshness": round(catalyst_freshness, 4),
            "layer_c_alignment": round(layer_c_alignment, 4),
            "positive_score_weights": {name: round(float(value), 4) for name, value in positive_score_weights.items()},
            "breakout_stage": breakout_stage,
            "selected_breakout_gate_pass": selected_breakout_gate_pass,
            "near_miss_breakout_gate_pass": near_miss_breakout_gate_pass,
            "profitability_hard_cliff": profitability_hard_cliff,
            "profitability_positive_count": profitability_positive_count,
            "profitability_confidence": round(profitability_confidence, 4),
            "profitability_relief_enabled": profitability_relief_enabled,
            "profitability_relief_gate_hits": profitability_relief_gate_hits,
            "profitability_relief_eligible": profitability_relief_eligible,
            "profitability_relief_applied": profitability_relief_applied,
            "historical_execution_relief": {
                "enabled": bool(historical_execution_relief["enabled"]),
                "eligible": bool(historical_execution_relief["eligible"]),
                "applied": bool(historical_execution_relief["applied"]),
                "candidate_source": str(historical_execution_relief["candidate_source"]),
                "execution_quality_label": str(historical_execution_relief["execution_quality_label"]),
                "evaluable_count": int(historical_execution_relief["evaluable_count"]),
                "next_close_positive_rate": round(float(historical_execution_relief["next_close_positive_rate"]), 4),
                "next_high_hit_rate_at_threshold": round(float(historical_execution_relief["next_high_hit_rate_at_threshold"]), 4),
                "next_open_to_close_return_mean": round(float(historical_execution_relief["next_open_to_close_return_mean"]), 4),
                "strong_close_continuation": bool(historical_execution_relief["strong_close_continuation"]),
                "gate_hits": dict(historical_execution_relief["gate_hits"]),
                "base_near_miss_threshold": round(float(historical_execution_relief["base_near_miss_threshold"]), 4),
                "effective_near_miss_threshold": round(float(historical_execution_relief["effective_near_miss_threshold"]), 4),
                "near_miss_threshold_override": round(float(historical_execution_relief["near_miss_threshold_override"]), 4),
                "base_select_threshold": round(float(historical_execution_relief["base_select_threshold"]), 4),
                "effective_select_threshold": round(float(historical_execution_relief["effective_select_threshold"]), 4),
                "select_threshold_override": round(float(historical_execution_relief["select_threshold_override"]), 4),
            },
            "carryover_evidence_deficiency": {
                "enabled": bool(carryover_evidence_deficiency["enabled"]),
                "evidence_deficient": bool(carryover_evidence_deficiency["evidence_deficient"]),
                "gate_hits": dict(carryover_evidence_deficiency["gate_hits"]),
                "same_ticker_sample_count": int(carryover_evidence_deficiency["same_ticker_sample_count"]),
                "same_family_sample_count": int(carryover_evidence_deficiency["same_family_sample_count"]),
                "same_family_source_sample_count": int(carryover_evidence_deficiency["same_family_source_sample_count"]),
                "same_family_source_score_catalyst_sample_count": int(carryover_evidence_deficiency["same_family_source_score_catalyst_sample_count"]),
                "same_source_score_sample_count": int(carryover_evidence_deficiency["same_source_score_sample_count"]),
                "evaluable_count": int(carryover_evidence_deficiency["evaluable_count"]),
            },
            "base_layer_c_avoid_penalty": round(base_layer_c_avoid_penalty, 4),
            "profitability_relief_soft_penalty": round(profitability_relief_soft_penalty, 4),
            "layer_c_avoid_penalty": round(layer_c_avoid_penalty, 4),
            "watchlist_zero_catalyst_penalty": round(effective_watchlist_zero_catalyst_penalty, 4),
            "watchlist_zero_catalyst_crowded_penalty": round(effective_watchlist_zero_catalyst_crowded_penalty, 4),
            "watchlist_zero_catalyst_flat_trend_penalty": round(effective_watchlist_zero_catalyst_flat_trend_penalty, 4),
            "t_plus_2_continuation_candidate": {
                "enabled": bool(t_plus_2_continuation_candidate["enabled"]),
                "eligible": bool(t_plus_2_continuation_candidate["eligible"]),
                "applied": bool(t_plus_2_continuation_candidate["applied"]),
                "candidate_source": str(t_plus_2_continuation_candidate["candidate_source"]),
                "gate_hits": dict(t_plus_2_continuation_candidate["gate_hits"]),
            },
            "watchlist_zero_catalyst_guard": {
                "enabled": bool(watchlist_zero_catalyst_guard["enabled"]),
                "eligible": bool(watchlist_zero_catalyst_guard["eligible"]),
                "applied": bool(watchlist_zero_catalyst_guard["applied"]),
                "candidate_source": str(watchlist_zero_catalyst_guard["candidate_source"]),
                "gate_hits": dict(watchlist_zero_catalyst_guard["gate_hits"]),
            },
            "watchlist_zero_catalyst_crowded_guard": {
                "enabled": bool(watchlist_zero_catalyst_crowded_guard["enabled"]),
                "eligible": bool(watchlist_zero_catalyst_crowded_guard["eligible"]),
                "applied": bool(watchlist_zero_catalyst_crowded_guard["applied"]),
                "candidate_source": str(watchlist_zero_catalyst_crowded_guard["candidate_source"]),
                "gate_hits": dict(watchlist_zero_catalyst_crowded_guard["gate_hits"]),
            },
            "watchlist_zero_catalyst_flat_trend_guard": {
                "enabled": bool(watchlist_zero_catalyst_flat_trend_guard["enabled"]),
                "eligible": bool(watchlist_zero_catalyst_flat_trend_guard["eligible"]),
                "applied": bool(watchlist_zero_catalyst_flat_trend_guard["applied"]),
                "candidate_source": str(watchlist_zero_catalyst_flat_trend_guard["candidate_source"]),
                "gate_hits": dict(watchlist_zero_catalyst_flat_trend_guard["gate_hits"]),
            },
            "upstream_shadow_catalyst_relief_enabled": upstream_shadow_catalyst_relief_enabled,
            "upstream_shadow_catalyst_relief_gate_hits": upstream_shadow_catalyst_relief_gate_hits,
            "upstream_shadow_catalyst_relief_eligible": upstream_shadow_catalyst_relief_eligible,
            "upstream_shadow_catalyst_relief_applied": upstream_shadow_catalyst_relief_applied,
            "upstream_shadow_catalyst_relief_reason": upstream_shadow_catalyst_relief_reason,
            "upstream_shadow_catalyst_relief_catalyst_freshness_floor": round(upstream_shadow_catalyst_relief_catalyst_freshness_floor, 4),
            "upstream_shadow_catalyst_relief_base_near_miss_threshold": round(upstream_shadow_catalyst_relief_base_near_miss_threshold, 4),
            "upstream_shadow_catalyst_relief_near_miss_threshold_override": round(upstream_shadow_catalyst_relief_near_miss_threshold_override, 4),
            "upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff": upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff,
            "profitability_hard_cliff_boundary_relief": {
                "enabled": bool(profitability_hard_cliff_boundary_relief["enabled"]),
                "eligible": bool(profitability_hard_cliff_boundary_relief["eligible"]),
                "applied": bool(profitability_hard_cliff_boundary_relief["applied"]),
                "candidate_source": str(profitability_hard_cliff_boundary_relief["candidate_source"]),
                "gate_hits": dict(profitability_hard_cliff_boundary_relief["gate_hits"]),
                "base_near_miss_threshold": round(float(profitability_hard_cliff_boundary_relief["base_near_miss_threshold"]), 4),
                "effective_near_miss_threshold": round(float(profitability_hard_cliff_boundary_relief["effective_near_miss_threshold"]), 4),
                "near_miss_threshold_override": round(float(profitability_hard_cliff_boundary_relief["near_miss_threshold_override"]), 4),
            },
            "historical_execution_relief": {
                "enabled": bool(historical_execution_relief["enabled"]),
                "eligible": bool(historical_execution_relief["eligible"]),
                "applied": bool(historical_execution_relief["applied"]),
                "candidate_source": str(historical_execution_relief["candidate_source"]),
                "execution_quality_label": str(historical_execution_relief["execution_quality_label"]),
                "evaluable_count": int(historical_execution_relief["evaluable_count"]),
                "next_close_positive_rate": round(float(historical_execution_relief["next_close_positive_rate"]), 4),
                "next_high_hit_rate_at_threshold": round(float(historical_execution_relief["next_high_hit_rate_at_threshold"]), 4),
                "next_open_to_close_return_mean": round(float(historical_execution_relief["next_open_to_close_return_mean"]), 4),
                "strong_close_continuation": bool(historical_execution_relief["strong_close_continuation"]),
                "gate_hits": dict(historical_execution_relief["gate_hits"]),
                "base_near_miss_threshold": round(float(historical_execution_relief["base_near_miss_threshold"]), 4),
                "effective_near_miss_threshold": round(float(historical_execution_relief["effective_near_miss_threshold"]), 4),
                "near_miss_threshold_override": round(float(historical_execution_relief["near_miss_threshold_override"]), 4),
                "base_select_threshold": round(float(historical_execution_relief["base_select_threshold"]), 4),
                "effective_select_threshold": round(float(historical_execution_relief["effective_select_threshold"]), 4),
                "select_threshold_override": round(float(historical_execution_relief["select_threshold_override"]), 4),
            },
            "visibility_gap_continuation_relief": {
                "enabled": bool(visibility_gap_continuation_relief["enabled"]),
                "eligible": bool(visibility_gap_continuation_relief["eligible"]),
                "applied": bool(visibility_gap_continuation_relief["applied"]),
                "candidate_source": str(visibility_gap_continuation_relief["candidate_source"]),
                "candidate_pool_lane": str(visibility_gap_continuation_relief["candidate_pool_lane"]),
                "candidate_pool_shadow_reason": str(visibility_gap_continuation_relief["candidate_pool_shadow_reason"]),
                "shadow_visibility_gap_selected": bool(visibility_gap_continuation_relief["shadow_visibility_gap_selected"]),
                "shadow_visibility_gap_relaxed_band": bool(visibility_gap_continuation_relief["shadow_visibility_gap_relaxed_band"]),
                "gate_hits": dict(visibility_gap_continuation_relief["gate_hits"]),
                "historical_execution_quality_label": str(visibility_gap_continuation_relief["historical_execution_quality_label"]),
                "historical_applied_scope": str(visibility_gap_continuation_relief["historical_applied_scope"]),
                "historical_evaluable_count": int(visibility_gap_continuation_relief["historical_evaluable_count"]),
                "historical_next_close_positive_rate": round(float(visibility_gap_continuation_relief["historical_next_close_positive_rate"]), 4),
                "catalyst_freshness_floor": round(float(visibility_gap_continuation_relief["catalyst_freshness_floor"]), 4),
                "near_miss_threshold_override": round(float(visibility_gap_continuation_relief["near_miss_threshold_override"]), 4),
                "require_relaxed_band": bool(visibility_gap_continuation_relief["require_relaxed_band"]),
            },
            "merge_approved_continuation_relief": {
                "enabled": bool(merge_approved_continuation_relief["enabled"]),
                "eligible": bool(merge_approved_continuation_relief["eligible"]),
                "applied": bool(merge_approved_continuation_relief["applied"]),
                "reason": str(merge_approved_continuation_relief["reason"]),
                "gate_hits": dict(merge_approved_continuation_relief["gate_hits"]),
                "historical_execution_quality_label": str(merge_approved_continuation_relief["historical_execution_quality_label"]),
                "historical_applied_scope": str(merge_approved_continuation_relief["historical_applied_scope"]),
                "historical_evaluable_count": int(merge_approved_continuation_relief["historical_evaluable_count"]),
                "historical_next_close_positive_rate": round(float(merge_approved_continuation_relief["historical_next_close_positive_rate"]), 4),
                "base_near_miss_threshold": round(float(merge_approved_continuation_relief["base_near_miss_threshold"]), 4),
                "effective_near_miss_threshold": round(float(merge_approved_continuation_relief["effective_near_miss_threshold"]), 4),
                "near_miss_threshold_override": round(float(merge_approved_continuation_relief["near_miss_threshold_override"]), 4),
                "base_select_threshold": round(float(merge_approved_continuation_relief["base_select_threshold"]), 4),
                "effective_select_threshold": round(float(merge_approved_continuation_relief["effective_select_threshold"]), 4),
                "select_threshold_override": round(float(merge_approved_continuation_relief["select_threshold_override"]), 4),
                "require_no_profitability_hard_cliff": bool(merge_approved_continuation_relief["require_no_profitability_hard_cliff"]),
            },
            "prepared_breakout_penalty_relief": {
                "enabled": bool(prepared_breakout_penalty_relief["enabled"]),
                "eligible": bool(prepared_breakout_penalty_relief["eligible"]),
                "applied": bool(prepared_breakout_penalty_relief["applied"]),
                "candidate_source": str(prepared_breakout_penalty_relief["candidate_source"]),
                "breakout_stage": str(prepared_breakout_penalty_relief["breakout_stage"]),
                "gate_hits": dict(prepared_breakout_penalty_relief["gate_hits"]),
                "base_positive_score_weights": {name: round(float(value), 4) for name, value in dict(prepared_breakout_penalty_relief["base_positive_score_weights"]).items()},
                "effective_positive_score_weights": {name: round(float(value), 4) for name, value in dict(prepared_breakout_penalty_relief["effective_positive_score_weights"]).items()},
                "base_stale_score_penalty_weight": round(float(prepared_breakout_penalty_relief["base_stale_score_penalty_weight"]), 4),
                "effective_stale_score_penalty_weight": round(float(prepared_breakout_penalty_relief["effective_stale_score_penalty_weight"]), 4),
                "base_extension_score_penalty_weight": round(float(prepared_breakout_penalty_relief["base_extension_score_penalty_weight"]), 4),
                "effective_extension_score_penalty_weight": round(float(prepared_breakout_penalty_relief["effective_extension_score_penalty_weight"]), 4),
            },
            "prepared_breakout_catalyst_relief": {
                "enabled": bool(prepared_breakout_catalyst_relief["enabled"]),
                "eligible": bool(prepared_breakout_catalyst_relief["eligible"]),
                "applied": bool(prepared_breakout_catalyst_relief["applied"]),
                "candidate_source": str(prepared_breakout_catalyst_relief["candidate_source"]),
                "breakout_stage": str(prepared_breakout_catalyst_relief["breakout_stage"]),
                "gate_hits": dict(prepared_breakout_catalyst_relief["gate_hits"]),
                "base_catalyst_freshness": round(float(prepared_breakout_catalyst_relief["base_catalyst_freshness"]), 4),
                "effective_catalyst_freshness": round(float(prepared_breakout_catalyst_relief["effective_catalyst_freshness"]), 4),
                "catalyst_freshness_floor": round(float(prepared_breakout_catalyst_relief["catalyst_freshness_floor"]), 4),
            },
            "prepared_breakout_volume_relief": {
                "enabled": bool(prepared_breakout_volume_relief["enabled"]),
                "eligible": bool(prepared_breakout_volume_relief["eligible"]),
                "applied": bool(prepared_breakout_volume_relief["applied"]),
                "candidate_source": str(prepared_breakout_volume_relief["candidate_source"]),
                "breakout_stage": str(prepared_breakout_volume_relief["breakout_stage"]),
                "gate_hits": dict(prepared_breakout_volume_relief["gate_hits"]),
                "base_volume_expansion_quality": round(float(prepared_breakout_volume_relief["base_volume_expansion_quality"]), 4),
                "effective_volume_expansion_quality": round(float(prepared_breakout_volume_relief["effective_volume_expansion_quality"]), 4),
                "volatility_regime": round(float(prepared_breakout_volume_relief["volatility_regime"]), 4),
                "atr_ratio": round(float(prepared_breakout_volume_relief["atr_ratio"]), 4),
                "volume_expansion_quality_floor": round(float(prepared_breakout_volume_relief["volume_expansion_quality_floor"]), 4),
            },
            "prepared_breakout_continuation_relief": {
                "enabled": bool(prepared_breakout_continuation_relief["enabled"]),
                "eligible": bool(prepared_breakout_continuation_relief["eligible"]),
                "applied": bool(prepared_breakout_continuation_relief["applied"]),
                "candidate_source": str(prepared_breakout_continuation_relief["candidate_source"]),
                "breakout_stage": str(prepared_breakout_continuation_relief["breakout_stage"]),
                "gate_hits": dict(prepared_breakout_continuation_relief["gate_hits"]),
                "base_breakout_freshness": round(float(prepared_breakout_continuation_relief["base_breakout_freshness"]), 4),
                "effective_breakout_freshness": round(float(prepared_breakout_continuation_relief["effective_breakout_freshness"]), 4),
                "base_trend_acceleration": round(float(prepared_breakout_continuation_relief["base_trend_acceleration"]), 4),
                "effective_trend_acceleration": round(float(prepared_breakout_continuation_relief["effective_trend_acceleration"]), 4),
                "momentum_1m": round(float(prepared_breakout_continuation_relief["momentum_1m"]), 4),
                "momentum_3m": round(float(prepared_breakout_continuation_relief["momentum_3m"]), 4),
                "momentum_6m": round(float(prepared_breakout_continuation_relief["momentum_6m"]), 4),
                "volume_momentum": round(float(prepared_breakout_continuation_relief["volume_momentum"]), 4),
                "continuation_support": round(float(prepared_breakout_continuation_relief["continuation_support"]), 4),
                "breakout_freshness_floor": round(float(prepared_breakout_continuation_relief["breakout_freshness_floor"]), 4),
                "trend_acceleration_floor": round(float(prepared_breakout_continuation_relief["trend_acceleration_floor"]), 4),
            },
            "prepared_breakout_selected_catalyst_relief": {
                "enabled": bool(prepared_breakout_selected_catalyst_relief["enabled"]),
                "eligible": bool(prepared_breakout_selected_catalyst_relief["eligible"]),
                "applied": bool(prepared_breakout_selected_catalyst_relief["applied"]),
                "candidate_source": str(prepared_breakout_selected_catalyst_relief["candidate_source"]),
                "breakout_stage": str(prepared_breakout_selected_catalyst_relief["breakout_stage"]),
                "gate_hits": dict(prepared_breakout_selected_catalyst_relief["gate_hits"]),
                "base_breakout_freshness": round(float(prepared_breakout_selected_catalyst_relief["base_breakout_freshness"]), 4),
                "effective_breakout_freshness": round(float(prepared_breakout_selected_catalyst_relief["effective_breakout_freshness"]), 4),
                "base_catalyst_freshness": round(float(prepared_breakout_selected_catalyst_relief["base_catalyst_freshness"]), 4),
                "effective_catalyst_freshness": round(float(prepared_breakout_selected_catalyst_relief["effective_catalyst_freshness"]), 4),
                "selected_breakout_freshness_floor": round(float(prepared_breakout_selected_catalyst_relief["selected_breakout_freshness_floor"]), 4),
                "catalyst_freshness_floor": round(float(prepared_breakout_selected_catalyst_relief["catalyst_freshness_floor"]), 4),
            },
            "stale_trend_repair_penalty": round(stale_trend_repair_penalty, 4),
            "overhead_supply_penalty": round(overhead_supply_penalty, 4),
            "extension_without_room_penalty": round(extension_without_room_penalty, 4),
            "weighted_positive_contributions": weighted_positive_contributions,
            "weighted_negative_contributions": weighted_negative_contributions,
            "total_positive_contribution": total_positive_contribution,
            "total_negative_contribution": total_negative_contribution,
            "thresholds": {
                "profile_name": profile.name,
                "select_threshold": round(float(profile.select_threshold), 4),
                "effective_select_threshold": round(effective_select_threshold, 4),
                "selected_score_tolerance": round(selected_score_tolerance, 4),
                "near_miss_threshold": round(effective_near_miss_threshold, 4),
                "base_near_miss_threshold": round(float(profile.near_miss_threshold), 4),
                "selected_breakout_freshness_min": round(float(profile.selected_breakout_freshness_min), 4),
                "selected_trend_acceleration_min": round(float(profile.selected_trend_acceleration_min), 4),
                "near_miss_breakout_freshness_min": round(float(profile.near_miss_breakout_freshness_min), 4),
                "near_miss_trend_acceleration_min": round(float(profile.near_miss_trend_acceleration_min), 4),
                "breakout_freshness_weight": round(float(profile.breakout_freshness_weight), 4),
                "trend_acceleration_weight": round(float(profile.trend_acceleration_weight), 4),
                "volume_expansion_quality_weight": round(float(profile.volume_expansion_quality_weight), 4),
                "close_strength_weight": round(float(profile.close_strength_weight), 4),
                "sector_resonance_weight": round(float(profile.sector_resonance_weight), 4),
                "catalyst_freshness_weight": round(float(profile.catalyst_freshness_weight), 4),
                "layer_c_alignment_weight": round(float(profile.layer_c_alignment_weight), 4),
                "effective_positive_score_weights": {name: round(float(value), 4) for name, value in positive_score_weights.items()},
                "stale_penalty_block_threshold": round(float(profile.stale_penalty_block_threshold), 4),
                "overhead_penalty_block_threshold": round(float(profile.overhead_penalty_block_threshold), 4),
                "extension_penalty_block_threshold": round(float(profile.extension_penalty_block_threshold), 4),
                "layer_c_avoid_penalty": round(float(profile.layer_c_avoid_penalty), 4),
                "profitability_relief_enabled": bool(profile.profitability_relief_enabled),
                "profitability_relief_breakout_freshness_min": round(float(profile.profitability_relief_breakout_freshness_min), 4),
                "profitability_relief_catalyst_freshness_min": round(float(profile.profitability_relief_catalyst_freshness_min), 4),
                "profitability_relief_sector_resonance_min": round(float(profile.profitability_relief_sector_resonance_min), 4),
                "profitability_relief_avoid_penalty": round(float(profile.profitability_relief_avoid_penalty), 4),
                "profitability_hard_cliff_boundary_relief_enabled": bool(profile.profitability_hard_cliff_boundary_relief_enabled),
                "profitability_hard_cliff_boundary_relief_breakout_freshness_min": round(float(profile.profitability_hard_cliff_boundary_relief_breakout_freshness_min), 4),
                "profitability_hard_cliff_boundary_relief_trend_acceleration_min": round(float(profile.profitability_hard_cliff_boundary_relief_trend_acceleration_min), 4),
                "profitability_hard_cliff_boundary_relief_catalyst_freshness_min": round(float(profile.profitability_hard_cliff_boundary_relief_catalyst_freshness_min), 4),
                "profitability_hard_cliff_boundary_relief_sector_resonance_min": round(float(profile.profitability_hard_cliff_boundary_relief_sector_resonance_min), 4),
                "profitability_hard_cliff_boundary_relief_close_strength_min": round(float(profile.profitability_hard_cliff_boundary_relief_close_strength_min), 4),
                "profitability_hard_cliff_boundary_relief_stale_penalty_max": round(float(profile.profitability_hard_cliff_boundary_relief_stale_penalty_max), 4),
                "profitability_hard_cliff_boundary_relief_extension_penalty_max": round(float(profile.profitability_hard_cliff_boundary_relief_extension_penalty_max), 4),
                "profitability_hard_cliff_boundary_relief_near_miss_threshold": round(float(profile.profitability_hard_cliff_boundary_relief_near_miss_threshold), 4),
                "prepared_breakout_penalty_relief_enabled": bool(profile.prepared_breakout_penalty_relief_enabled),
                "prepared_breakout_penalty_relief_breakout_freshness_max": round(float(profile.prepared_breakout_penalty_relief_breakout_freshness_max), 4),
                "prepared_breakout_penalty_relief_trend_acceleration_min": round(float(profile.prepared_breakout_penalty_relief_trend_acceleration_min), 4),
                "prepared_breakout_penalty_relief_close_strength_min": round(float(profile.prepared_breakout_penalty_relief_close_strength_min), 4),
                "prepared_breakout_penalty_relief_sector_resonance_min": round(float(profile.prepared_breakout_penalty_relief_sector_resonance_min), 4),
                "prepared_breakout_penalty_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_penalty_relief_layer_c_alignment_min), 4),
                "prepared_breakout_penalty_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_penalty_relief_catalyst_freshness_max), 4),
                "prepared_breakout_penalty_relief_long_trend_strength_min": round(float(profile.prepared_breakout_penalty_relief_long_trend_strength_min), 4),
                "prepared_breakout_penalty_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_penalty_relief_mean_reversion_strength_max), 4),
                "prepared_breakout_penalty_relief_breakout_freshness_weight": round(float(profile.prepared_breakout_penalty_relief_breakout_freshness_weight), 4),
                "prepared_breakout_penalty_relief_trend_acceleration_weight": round(float(profile.prepared_breakout_penalty_relief_trend_acceleration_weight), 4),
                "prepared_breakout_penalty_relief_volume_expansion_quality_weight": round(float(profile.prepared_breakout_penalty_relief_volume_expansion_quality_weight), 4),
                "prepared_breakout_penalty_relief_close_strength_weight": round(float(profile.prepared_breakout_penalty_relief_close_strength_weight), 4),
                "prepared_breakout_penalty_relief_sector_resonance_weight": round(float(profile.prepared_breakout_penalty_relief_sector_resonance_weight), 4),
                "prepared_breakout_penalty_relief_catalyst_freshness_weight": round(float(profile.prepared_breakout_penalty_relief_catalyst_freshness_weight), 4),
                "prepared_breakout_penalty_relief_layer_c_alignment_weight": round(float(profile.prepared_breakout_penalty_relief_layer_c_alignment_weight), 4),
                "prepared_breakout_penalty_relief_stale_score_penalty_weight": round(float(profile.prepared_breakout_penalty_relief_stale_score_penalty_weight), 4),
                "prepared_breakout_penalty_relief_extension_score_penalty_weight": round(float(profile.prepared_breakout_penalty_relief_extension_score_penalty_weight), 4),
                "prepared_breakout_catalyst_relief_enabled": bool(profile.prepared_breakout_catalyst_relief_enabled),
                "prepared_breakout_catalyst_relief_breakout_freshness_max": round(float(profile.prepared_breakout_catalyst_relief_breakout_freshness_max), 4),
                "prepared_breakout_catalyst_relief_trend_acceleration_min": round(float(profile.prepared_breakout_catalyst_relief_trend_acceleration_min), 4),
                "prepared_breakout_catalyst_relief_close_strength_min": round(float(profile.prepared_breakout_catalyst_relief_close_strength_min), 4),
                "prepared_breakout_catalyst_relief_sector_resonance_min": round(float(profile.prepared_breakout_catalyst_relief_sector_resonance_min), 4),
                "prepared_breakout_catalyst_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_catalyst_relief_layer_c_alignment_min), 4),
                "prepared_breakout_catalyst_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_max), 4),
                "prepared_breakout_catalyst_relief_long_trend_strength_min": round(float(profile.prepared_breakout_catalyst_relief_long_trend_strength_min), 4),
                "prepared_breakout_catalyst_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_catalyst_relief_mean_reversion_strength_max), 4),
                "prepared_breakout_catalyst_relief_catalyst_freshness_floor": round(float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_floor), 4),
                "prepared_breakout_volume_relief_enabled": bool(profile.prepared_breakout_volume_relief_enabled),
                "prepared_breakout_volume_relief_breakout_freshness_max": round(float(profile.prepared_breakout_volume_relief_breakout_freshness_max), 4),
                "prepared_breakout_volume_relief_trend_acceleration_min": round(float(profile.prepared_breakout_volume_relief_trend_acceleration_min), 4),
                "prepared_breakout_volume_relief_close_strength_min": round(float(profile.prepared_breakout_volume_relief_close_strength_min), 4),
                "prepared_breakout_volume_relief_sector_resonance_min": round(float(profile.prepared_breakout_volume_relief_sector_resonance_min), 4),
                "prepared_breakout_volume_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_volume_relief_layer_c_alignment_min), 4),
                "prepared_breakout_volume_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_volume_relief_catalyst_freshness_max), 4),
                "prepared_breakout_volume_relief_long_trend_strength_min": round(float(profile.prepared_breakout_volume_relief_long_trend_strength_min), 4),
                "prepared_breakout_volume_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_volume_relief_mean_reversion_strength_max), 4),
                "prepared_breakout_volume_relief_volatility_strength_max": round(float(profile.prepared_breakout_volume_relief_volatility_strength_max), 4),
                "prepared_breakout_volume_relief_volatility_regime_min": round(float(profile.prepared_breakout_volume_relief_volatility_regime_min), 4),
                "prepared_breakout_volume_relief_atr_ratio_min": round(float(profile.prepared_breakout_volume_relief_atr_ratio_min), 4),
                "prepared_breakout_volume_relief_volume_expansion_quality_floor": round(float(profile.prepared_breakout_volume_relief_volume_expansion_quality_floor), 4),
                "prepared_breakout_continuation_relief_enabled": bool(profile.prepared_breakout_continuation_relief_enabled),
                "prepared_breakout_continuation_relief_breakout_freshness_max": round(float(profile.prepared_breakout_continuation_relief_breakout_freshness_max), 4),
                "prepared_breakout_continuation_relief_trend_acceleration_min": round(float(profile.prepared_breakout_continuation_relief_trend_acceleration_min), 4),
                "prepared_breakout_continuation_relief_trend_acceleration_max": round(float(profile.prepared_breakout_continuation_relief_trend_acceleration_max), 4),
                "prepared_breakout_continuation_relief_close_strength_min": round(float(profile.prepared_breakout_continuation_relief_close_strength_min), 4),
                "prepared_breakout_continuation_relief_sector_resonance_min": round(float(profile.prepared_breakout_continuation_relief_sector_resonance_min), 4),
                "prepared_breakout_continuation_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_continuation_relief_layer_c_alignment_min), 4),
                "prepared_breakout_continuation_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_continuation_relief_catalyst_freshness_max), 4),
                "prepared_breakout_continuation_relief_long_trend_strength_min": round(float(profile.prepared_breakout_continuation_relief_long_trend_strength_min), 4),
                "prepared_breakout_continuation_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_continuation_relief_mean_reversion_strength_max), 4),
                "prepared_breakout_continuation_relief_momentum_1m_max": round(float(profile.prepared_breakout_continuation_relief_momentum_1m_max), 4),
                "prepared_breakout_continuation_relief_continuation_support_min": round(float(profile.prepared_breakout_continuation_relief_continuation_support_min), 4),
                "prepared_breakout_continuation_relief_breakout_freshness_floor": round(float(profile.prepared_breakout_continuation_relief_breakout_freshness_floor), 4),
                "prepared_breakout_continuation_relief_trend_acceleration_floor": round(float(profile.prepared_breakout_continuation_relief_trend_acceleration_floor), 4),
                "prepared_breakout_selected_catalyst_relief_enabled": bool(profile.prepared_breakout_selected_catalyst_relief_enabled),
                "prepared_breakout_selected_catalyst_relief_breakout_freshness_min": round(float(profile.prepared_breakout_selected_catalyst_relief_breakout_freshness_min), 4),
                "prepared_breakout_selected_catalyst_relief_trend_acceleration_min": round(float(profile.prepared_breakout_selected_catalyst_relief_trend_acceleration_min), 4),
                "prepared_breakout_selected_catalyst_relief_close_strength_min": round(float(profile.prepared_breakout_selected_catalyst_relief_close_strength_min), 4),
                "prepared_breakout_selected_catalyst_relief_sector_resonance_min": round(float(profile.prepared_breakout_selected_catalyst_relief_sector_resonance_min), 4),
                "prepared_breakout_selected_catalyst_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_selected_catalyst_relief_layer_c_alignment_min), 4),
                "prepared_breakout_selected_catalyst_relief_volume_expansion_quality_min": round(float(profile.prepared_breakout_selected_catalyst_relief_volume_expansion_quality_min), 4),
                "prepared_breakout_selected_catalyst_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_max), 4),
                "prepared_breakout_selected_catalyst_relief_long_trend_strength_min": round(float(profile.prepared_breakout_selected_catalyst_relief_long_trend_strength_min), 4),
                "prepared_breakout_selected_catalyst_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_selected_catalyst_relief_mean_reversion_strength_max), 4),
                "prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor": round(float(profile.prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor), 4),
                "prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor": round(float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor), 4),
                "stale_score_penalty_weight": round(float(profile.stale_score_penalty_weight), 4),
                "overhead_score_penalty_weight": round(float(profile.overhead_score_penalty_weight), 4),
                "extension_score_penalty_weight": round(float(profile.extension_score_penalty_weight), 4),
                "watchlist_zero_catalyst_penalty": round(float(profile.watchlist_zero_catalyst_penalty), 4),
                "watchlist_zero_catalyst_catalyst_freshness_max": round(float(profile.watchlist_zero_catalyst_catalyst_freshness_max), 4),
                "watchlist_zero_catalyst_close_strength_min": round(float(profile.watchlist_zero_catalyst_close_strength_min), 4),
                "watchlist_zero_catalyst_layer_c_alignment_min": round(float(profile.watchlist_zero_catalyst_layer_c_alignment_min), 4),
                "watchlist_zero_catalyst_sector_resonance_min": round(float(profile.watchlist_zero_catalyst_sector_resonance_min), 4),
                "watchlist_zero_catalyst_crowded_penalty": round(float(profile.watchlist_zero_catalyst_crowded_penalty), 4),
                "watchlist_zero_catalyst_crowded_catalyst_freshness_max": round(float(profile.watchlist_zero_catalyst_crowded_catalyst_freshness_max), 4),
                "watchlist_zero_catalyst_crowded_close_strength_min": round(float(profile.watchlist_zero_catalyst_crowded_close_strength_min), 4),
                "watchlist_zero_catalyst_crowded_layer_c_alignment_min": round(float(profile.watchlist_zero_catalyst_crowded_layer_c_alignment_min), 4),
                "watchlist_zero_catalyst_crowded_sector_resonance_min": round(float(profile.watchlist_zero_catalyst_crowded_sector_resonance_min), 4),
                "watchlist_zero_catalyst_flat_trend_penalty": round(float(profile.watchlist_zero_catalyst_flat_trend_penalty), 4),
                "watchlist_zero_catalyst_flat_trend_catalyst_freshness_max": round(float(profile.watchlist_zero_catalyst_flat_trend_catalyst_freshness_max), 4),
                "watchlist_zero_catalyst_flat_trend_close_strength_min": round(float(profile.watchlist_zero_catalyst_flat_trend_close_strength_min), 4),
                "watchlist_zero_catalyst_flat_trend_layer_c_alignment_min": round(float(profile.watchlist_zero_catalyst_flat_trend_layer_c_alignment_min), 4),
                "watchlist_zero_catalyst_flat_trend_sector_resonance_min": round(float(profile.watchlist_zero_catalyst_flat_trend_sector_resonance_min), 4),
                "watchlist_zero_catalyst_flat_trend_trend_acceleration_max": round(float(profile.watchlist_zero_catalyst_flat_trend_trend_acceleration_max), 4),
                "t_plus_2_continuation_enabled": bool(profile.t_plus_2_continuation_enabled),
                "t_plus_2_continuation_catalyst_freshness_max": round(float(profile.t_plus_2_continuation_catalyst_freshness_max), 4),
                "t_plus_2_continuation_breakout_freshness_min": round(float(profile.t_plus_2_continuation_breakout_freshness_min), 4),
                "t_plus_2_continuation_trend_acceleration_min": round(float(profile.t_plus_2_continuation_trend_acceleration_min), 4),
                "t_plus_2_continuation_trend_acceleration_max": round(float(profile.t_plus_2_continuation_trend_acceleration_max), 4),
                "t_plus_2_continuation_layer_c_alignment_min": round(float(profile.t_plus_2_continuation_layer_c_alignment_min), 4),
                "t_plus_2_continuation_layer_c_alignment_max": round(float(profile.t_plus_2_continuation_layer_c_alignment_max), 4),
                "t_plus_2_continuation_close_strength_max": round(float(profile.t_plus_2_continuation_close_strength_max), 4),
                "t_plus_2_continuation_sector_resonance_max": round(float(profile.t_plus_2_continuation_sector_resonance_max), 4),
                "merge_approved_continuation_relief_enabled": bool(profile.merge_approved_continuation_relief_enabled),
                "merge_approved_continuation_select_threshold": round(float(profile.merge_approved_continuation_select_threshold), 4),
                "merge_approved_continuation_near_miss_threshold": round(float(profile.merge_approved_continuation_near_miss_threshold), 4),
                "hard_block_bearish_conflicts": sorted(str(item) for item in profile.hard_block_bearish_conflicts),
                "overhead_conflict_penalty_conflicts": sorted(str(item) for item in profile.overhead_conflict_penalty_conflicts),
                "upstream_shadow_catalyst_relief_enabled": upstream_shadow_catalyst_relief_enabled,
                "upstream_shadow_catalyst_relief_applied": upstream_shadow_catalyst_relief_applied,
                "upstream_shadow_catalyst_relief_catalyst_freshness_floor": round(upstream_shadow_catalyst_relief_catalyst_freshness_floor, 4),
                "upstream_shadow_catalyst_relief_near_miss_threshold_override": round(upstream_shadow_catalyst_relief_near_miss_threshold_override, 4),
                "upstream_shadow_catalyst_relief_base_select_threshold": round(upstream_shadow_catalyst_relief_base_select_threshold, 4),
                "upstream_shadow_catalyst_relief_select_threshold_override": round(upstream_shadow_catalyst_relief_select_threshold_override, 4),
                "visibility_gap_continuation_relief_enabled": bool(profile.visibility_gap_continuation_relief_enabled),
                "visibility_gap_continuation_breakout_freshness_min": round(float(profile.visibility_gap_continuation_breakout_freshness_min), 4),
                "visibility_gap_continuation_trend_acceleration_min": round(float(profile.visibility_gap_continuation_trend_acceleration_min), 4),
                "visibility_gap_continuation_close_strength_min": round(float(profile.visibility_gap_continuation_close_strength_min), 4),
                "visibility_gap_continuation_catalyst_freshness_floor": round(float(profile.visibility_gap_continuation_catalyst_freshness_floor), 4),
                "visibility_gap_continuation_near_miss_threshold": round(float(profile.visibility_gap_continuation_near_miss_threshold), 4),
                "visibility_gap_continuation_require_relaxed_band": bool(profile.visibility_gap_continuation_require_relaxed_band),
            },
        },
        explainability_payload={
            "source": str(input_data.replay_context.get("source") or "short_trade_target_rules_v1"),
            "target_profile": profile.name,
            "breakout_stage": breakout_stage,
            "trade_date": input_data.trade_date,
            "layer_c_decision": input_data.layer_c_decision,
            "bc_conflict": input_data.bc_conflict,
            "candidate_source": str(input_data.replay_context.get("source") or ""),
            "available_strategy_signals": sorted(str(name) for name in dict(input_data.strategy_signals or {}).keys()),
            "profitability_relief": {
                "enabled": profitability_relief_enabled,
                "hard_cliff": profitability_hard_cliff,
                "eligible": profitability_relief_eligible,
                "applied": profitability_relief_applied,
                "gate_hits": profitability_relief_gate_hits,
                "base_layer_c_avoid_penalty": round(base_layer_c_avoid_penalty, 4),
                "effective_layer_c_avoid_penalty": round(layer_c_avoid_penalty, 4),
                "soft_penalty": round(profitability_relief_soft_penalty, 4),
            },
            "profitability_hard_cliff_boundary_relief": {
                "enabled": bool(profitability_hard_cliff_boundary_relief["enabled"]),
                "eligible": bool(profitability_hard_cliff_boundary_relief["eligible"]),
                "applied": bool(profitability_hard_cliff_boundary_relief["applied"]),
                "candidate_source": str(profitability_hard_cliff_boundary_relief["candidate_source"]),
                "gate_hits": dict(profitability_hard_cliff_boundary_relief["gate_hits"]),
                "base_near_miss_threshold": round(float(profitability_hard_cliff_boundary_relief["base_near_miss_threshold"]), 4),
                "effective_near_miss_threshold": round(float(profitability_hard_cliff_boundary_relief["effective_near_miss_threshold"]), 4),
                "near_miss_threshold_override": round(float(profitability_hard_cliff_boundary_relief["near_miss_threshold_override"]), 4),
            },
            "historical_prior": historical_prior,
            "historical_execution_relief": {
                "enabled": bool(historical_execution_relief["enabled"]),
                "eligible": bool(historical_execution_relief["eligible"]),
                "applied": bool(historical_execution_relief["applied"]),
                "candidate_source": str(historical_execution_relief["candidate_source"]),
                "execution_quality_label": str(historical_execution_relief["execution_quality_label"]),
                "evaluable_count": int(historical_execution_relief["evaluable_count"]),
                "next_close_positive_rate": round(float(historical_execution_relief["next_close_positive_rate"]), 4),
                "next_high_hit_rate_at_threshold": round(float(historical_execution_relief["next_high_hit_rate_at_threshold"]), 4),
                "next_open_to_close_return_mean": round(float(historical_execution_relief["next_open_to_close_return_mean"]), 4),
                "strong_close_continuation": bool(historical_execution_relief["strong_close_continuation"]),
                "gate_hits": dict(historical_execution_relief["gate_hits"]),
                "base_near_miss_threshold": round(float(historical_execution_relief["base_near_miss_threshold"]), 4),
                "effective_near_miss_threshold": round(float(historical_execution_relief["effective_near_miss_threshold"]), 4),
                "near_miss_threshold_override": round(float(historical_execution_relief["near_miss_threshold_override"]), 4),
                "base_select_threshold": round(float(historical_execution_relief["base_select_threshold"]), 4),
                "effective_select_threshold": round(float(historical_execution_relief["effective_select_threshold"]), 4),
                "select_threshold_override": round(float(historical_execution_relief["select_threshold_override"]), 4),
            },
            "carryover_evidence_deficiency": {
                "enabled": bool(carryover_evidence_deficiency["enabled"]),
                "evidence_deficient": bool(carryover_evidence_deficiency["evidence_deficient"]),
                "gate_hits": dict(carryover_evidence_deficiency["gate_hits"]),
                "same_ticker_sample_count": int(carryover_evidence_deficiency["same_ticker_sample_count"]),
                "same_family_sample_count": int(carryover_evidence_deficiency["same_family_sample_count"]),
                "same_family_source_sample_count": int(carryover_evidence_deficiency["same_family_source_sample_count"]),
                "same_family_source_score_catalyst_sample_count": int(carryover_evidence_deficiency["same_family_source_score_catalyst_sample_count"]),
                "same_source_score_sample_count": int(carryover_evidence_deficiency["same_source_score_sample_count"]),
                "evaluable_count": int(carryover_evidence_deficiency["evaluable_count"]),
            },
            "upstream_shadow_catalyst_relief": {
                "enabled": upstream_shadow_catalyst_relief_enabled,
                "eligible": upstream_shadow_catalyst_relief_eligible,
                "applied": upstream_shadow_catalyst_relief_applied,
                "reason": upstream_shadow_catalyst_relief_reason,
                "gate_hits": upstream_shadow_catalyst_relief_gate_hits,
                "base_catalyst_freshness": round(raw_catalyst_freshness, 4),
                "effective_catalyst_freshness": round(catalyst_freshness, 4),
                "catalyst_freshness_floor": round(upstream_shadow_catalyst_relief_catalyst_freshness_floor, 4),
                "base_near_miss_threshold": round(upstream_shadow_catalyst_relief_base_near_miss_threshold, 4),
                "effective_near_miss_threshold": round(effective_near_miss_threshold, 4),
                "near_miss_threshold_override": round(upstream_shadow_catalyst_relief_near_miss_threshold_override, 4),
                "base_select_threshold": round(upstream_shadow_catalyst_relief_base_select_threshold, 4),
                "effective_select_threshold": round(effective_select_threshold, 4),
                "selected_score_tolerance": round(selected_score_tolerance, 4),
                "select_threshold_override": round(upstream_shadow_catalyst_relief_select_threshold_override, 4),
                "require_no_profitability_hard_cliff": upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff,
            },
            "visibility_gap_continuation_relief": {
                "enabled": bool(visibility_gap_continuation_relief["enabled"]),
                "eligible": bool(visibility_gap_continuation_relief["eligible"]),
                "applied": bool(visibility_gap_continuation_relief["applied"]),
                "candidate_source": str(visibility_gap_continuation_relief["candidate_source"]),
                "candidate_pool_lane": str(visibility_gap_continuation_relief["candidate_pool_lane"]),
                "candidate_pool_shadow_reason": str(visibility_gap_continuation_relief["candidate_pool_shadow_reason"]),
                "shadow_visibility_gap_selected": bool(visibility_gap_continuation_relief["shadow_visibility_gap_selected"]),
                "shadow_visibility_gap_relaxed_band": bool(visibility_gap_continuation_relief["shadow_visibility_gap_relaxed_band"]),
                "gate_hits": dict(visibility_gap_continuation_relief["gate_hits"]),
                "historical_execution_quality_label": str(visibility_gap_continuation_relief["historical_execution_quality_label"]),
                "historical_applied_scope": str(visibility_gap_continuation_relief["historical_applied_scope"]),
                "historical_evaluable_count": int(visibility_gap_continuation_relief["historical_evaluable_count"]),
                "historical_next_close_positive_rate": round(float(visibility_gap_continuation_relief["historical_next_close_positive_rate"]), 4),
                "base_catalyst_freshness": round(float(visibility_gap_continuation_relief["base_catalyst_freshness"]), 4),
                "effective_catalyst_freshness": round(float(visibility_gap_continuation_relief["effective_catalyst_freshness"]), 4),
                "base_near_miss_threshold": round(float(visibility_gap_continuation_relief["base_near_miss_threshold"]), 4),
                "effective_near_miss_threshold": round(float(visibility_gap_continuation_relief["effective_near_miss_threshold"]), 4),
                "catalyst_freshness_floor": round(float(visibility_gap_continuation_relief["catalyst_freshness_floor"]), 4),
                "near_miss_threshold_override": round(float(visibility_gap_continuation_relief["near_miss_threshold_override"]), 4),
                "require_relaxed_band": bool(visibility_gap_continuation_relief["require_relaxed_band"]),
            },
            "merge_approved_continuation_relief": {
                "enabled": bool(merge_approved_continuation_relief["enabled"]),
                "eligible": bool(merge_approved_continuation_relief["eligible"]),
                "applied": bool(merge_approved_continuation_relief["applied"]),
                "reason": str(merge_approved_continuation_relief["reason"]),
                "gate_hits": dict(merge_approved_continuation_relief["gate_hits"]),
                "historical_execution_quality_label": str(merge_approved_continuation_relief["historical_execution_quality_label"]),
                "historical_applied_scope": str(merge_approved_continuation_relief["historical_applied_scope"]),
                "historical_evaluable_count": int(merge_approved_continuation_relief["historical_evaluable_count"]),
                "historical_next_close_positive_rate": round(float(merge_approved_continuation_relief["historical_next_close_positive_rate"]), 4),
                "base_near_miss_threshold": round(float(merge_approved_continuation_relief["base_near_miss_threshold"]), 4),
                "effective_near_miss_threshold": round(float(merge_approved_continuation_relief["effective_near_miss_threshold"]), 4),
                "near_miss_threshold_override": round(float(merge_approved_continuation_relief["near_miss_threshold_override"]), 4),
                "base_select_threshold": round(float(merge_approved_continuation_relief["base_select_threshold"]), 4),
                "effective_select_threshold": round(float(merge_approved_continuation_relief["effective_select_threshold"]), 4),
                "select_threshold_override": round(float(merge_approved_continuation_relief["select_threshold_override"]), 4),
                "require_no_profitability_hard_cliff": bool(merge_approved_continuation_relief["require_no_profitability_hard_cliff"]),
            },
            "prepared_breakout_penalty_relief": {
                "enabled": bool(prepared_breakout_penalty_relief["enabled"]),
                "eligible": bool(prepared_breakout_penalty_relief["eligible"]),
                "applied": bool(prepared_breakout_penalty_relief["applied"]),
                "candidate_source": str(prepared_breakout_penalty_relief["candidate_source"]),
                "breakout_stage": str(prepared_breakout_penalty_relief["breakout_stage"]),
                "gate_hits": dict(prepared_breakout_penalty_relief["gate_hits"]),
                "base_positive_score_weights": {name: round(float(value), 4) for name, value in dict(prepared_breakout_penalty_relief["base_positive_score_weights"]).items()},
                "effective_positive_score_weights": {name: round(float(value), 4) for name, value in dict(prepared_breakout_penalty_relief["effective_positive_score_weights"]).items()},
                "base_stale_score_penalty_weight": round(float(prepared_breakout_penalty_relief["base_stale_score_penalty_weight"]), 4),
                "effective_stale_score_penalty_weight": round(float(prepared_breakout_penalty_relief["effective_stale_score_penalty_weight"]), 4),
                "base_extension_score_penalty_weight": round(float(prepared_breakout_penalty_relief["base_extension_score_penalty_weight"]), 4),
                "effective_extension_score_penalty_weight": round(float(prepared_breakout_penalty_relief["effective_extension_score_penalty_weight"]), 4),
            },
            "prepared_breakout_catalyst_relief": {
                "enabled": bool(prepared_breakout_catalyst_relief["enabled"]),
                "eligible": bool(prepared_breakout_catalyst_relief["eligible"]),
                "applied": bool(prepared_breakout_catalyst_relief["applied"]),
                "candidate_source": str(prepared_breakout_catalyst_relief["candidate_source"]),
                "breakout_stage": str(prepared_breakout_catalyst_relief["breakout_stage"]),
                "gate_hits": dict(prepared_breakout_catalyst_relief["gate_hits"]),
                "base_catalyst_freshness": round(float(prepared_breakout_catalyst_relief["base_catalyst_freshness"]), 4),
                "effective_catalyst_freshness": round(float(prepared_breakout_catalyst_relief["effective_catalyst_freshness"]), 4),
                "catalyst_freshness_floor": round(float(prepared_breakout_catalyst_relief["catalyst_freshness_floor"]), 4),
            },
            "prepared_breakout_volume_relief": {
                "enabled": bool(prepared_breakout_volume_relief["enabled"]),
                "eligible": bool(prepared_breakout_volume_relief["eligible"]),
                "applied": bool(prepared_breakout_volume_relief["applied"]),
                "candidate_source": str(prepared_breakout_volume_relief["candidate_source"]),
                "breakout_stage": str(prepared_breakout_volume_relief["breakout_stage"]),
                "gate_hits": dict(prepared_breakout_volume_relief["gate_hits"]),
                "base_volume_expansion_quality": round(float(prepared_breakout_volume_relief["base_volume_expansion_quality"]), 4),
                "effective_volume_expansion_quality": round(float(prepared_breakout_volume_relief["effective_volume_expansion_quality"]), 4),
                "volatility_regime": round(float(prepared_breakout_volume_relief["volatility_regime"]), 4),
                "atr_ratio": round(float(prepared_breakout_volume_relief["atr_ratio"]), 4),
                "volume_expansion_quality_floor": round(float(prepared_breakout_volume_relief["volume_expansion_quality_floor"]), 4),
            },
            "prepared_breakout_continuation_relief": {
                "enabled": bool(prepared_breakout_continuation_relief["enabled"]),
                "eligible": bool(prepared_breakout_continuation_relief["eligible"]),
                "applied": bool(prepared_breakout_continuation_relief["applied"]),
                "candidate_source": str(prepared_breakout_continuation_relief["candidate_source"]),
                "breakout_stage": str(prepared_breakout_continuation_relief["breakout_stage"]),
                "gate_hits": dict(prepared_breakout_continuation_relief["gate_hits"]),
                "base_breakout_freshness": round(float(prepared_breakout_continuation_relief["base_breakout_freshness"]), 4),
                "effective_breakout_freshness": round(float(prepared_breakout_continuation_relief["effective_breakout_freshness"]), 4),
                "base_trend_acceleration": round(float(prepared_breakout_continuation_relief["base_trend_acceleration"]), 4),
                "effective_trend_acceleration": round(float(prepared_breakout_continuation_relief["effective_trend_acceleration"]), 4),
                "momentum_1m": round(float(prepared_breakout_continuation_relief["momentum_1m"]), 4),
                "momentum_3m": round(float(prepared_breakout_continuation_relief["momentum_3m"]), 4),
                "momentum_6m": round(float(prepared_breakout_continuation_relief["momentum_6m"]), 4),
                "volume_momentum": round(float(prepared_breakout_continuation_relief["volume_momentum"]), 4),
                "continuation_support": round(float(prepared_breakout_continuation_relief["continuation_support"]), 4),
                "breakout_freshness_floor": round(float(prepared_breakout_continuation_relief["breakout_freshness_floor"]), 4),
                "trend_acceleration_floor": round(float(prepared_breakout_continuation_relief["trend_acceleration_floor"]), 4),
            },
            "prepared_breakout_selected_catalyst_relief": {
                "enabled": bool(prepared_breakout_selected_catalyst_relief["enabled"]),
                "eligible": bool(prepared_breakout_selected_catalyst_relief["eligible"]),
                "applied": bool(prepared_breakout_selected_catalyst_relief["applied"]),
                "candidate_source": str(prepared_breakout_selected_catalyst_relief["candidate_source"]),
                "breakout_stage": str(prepared_breakout_selected_catalyst_relief["breakout_stage"]),
                "gate_hits": dict(prepared_breakout_selected_catalyst_relief["gate_hits"]),
                "base_breakout_freshness": round(float(prepared_breakout_selected_catalyst_relief["base_breakout_freshness"]), 4),
                "effective_breakout_freshness": round(float(prepared_breakout_selected_catalyst_relief["effective_breakout_freshness"]), 4),
                "base_catalyst_freshness": round(float(prepared_breakout_selected_catalyst_relief["base_catalyst_freshness"]), 4),
                "effective_catalyst_freshness": round(float(prepared_breakout_selected_catalyst_relief["effective_catalyst_freshness"]), 4),
                "selected_breakout_freshness_floor": round(float(prepared_breakout_selected_catalyst_relief["selected_breakout_freshness_floor"]), 4),
                "catalyst_freshness_floor": round(float(prepared_breakout_selected_catalyst_relief["catalyst_freshness_floor"]), 4),
            },
            "watchlist_zero_catalyst_guard": {
                "enabled": bool(watchlist_zero_catalyst_guard["enabled"]),
                "eligible": bool(watchlist_zero_catalyst_guard["eligible"]),
                "applied": bool(watchlist_zero_catalyst_guard["applied"]),
                "candidate_source": str(watchlist_zero_catalyst_guard["candidate_source"]),
                "gate_hits": dict(watchlist_zero_catalyst_guard["gate_hits"]),
                "effective_penalty": round(effective_watchlist_zero_catalyst_penalty, 4),
            },
            "watchlist_zero_catalyst_crowded_guard": {
                "enabled": bool(watchlist_zero_catalyst_crowded_guard["enabled"]),
                "eligible": bool(watchlist_zero_catalyst_crowded_guard["eligible"]),
                "applied": bool(watchlist_zero_catalyst_crowded_guard["applied"]),
                "candidate_source": str(watchlist_zero_catalyst_crowded_guard["candidate_source"]),
                "gate_hits": dict(watchlist_zero_catalyst_crowded_guard["gate_hits"]),
                "effective_penalty": round(effective_watchlist_zero_catalyst_crowded_penalty, 4),
            },
            "watchlist_zero_catalyst_flat_trend_guard": {
                "enabled": bool(watchlist_zero_catalyst_flat_trend_guard["enabled"]),
                "eligible": bool(watchlist_zero_catalyst_flat_trend_guard["eligible"]),
                "applied": bool(watchlist_zero_catalyst_flat_trend_guard["applied"]),
                "candidate_source": str(watchlist_zero_catalyst_flat_trend_guard["candidate_source"]),
                "gate_hits": dict(watchlist_zero_catalyst_flat_trend_guard["gate_hits"]),
                "effective_penalty": round(effective_watchlist_zero_catalyst_flat_trend_penalty, 4),
            },
            "t_plus_2_continuation_candidate": {
                "enabled": bool(t_plus_2_continuation_candidate["enabled"]),
                "eligible": bool(t_plus_2_continuation_candidate["eligible"]),
                "applied": bool(t_plus_2_continuation_candidate["applied"]),
                "candidate_source": str(t_plus_2_continuation_candidate["candidate_source"]),
                "gate_hits": dict(t_plus_2_continuation_candidate["gate_hits"]),
            },
            "replay_context": dict(input_data.replay_context or {}),
        },
    )


def evaluate_short_trade_selected_target(
    *,
    trade_date: str,
    item: LayerCResult,
    rank_hint: int | None = None,
    included_in_buy_orders: bool = False,
    profile_name: str | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> TargetEvaluationResult:
    if profile_name is not None or profile_overrides:
        with use_short_trade_target_profile(profile_name=profile_name or "default", overrides=profile_overrides):
            return evaluate_short_trade_selected_target(
                trade_date=trade_date,
                item=item,
                rank_hint=rank_hint,
                included_in_buy_orders=included_in_buy_orders,
            )
    return _evaluate_short_trade_target(
        _build_target_input_from_item(trade_date=trade_date, item=item, included_in_buy_orders=included_in_buy_orders),
        rank_hint=rank_hint,
    )


def evaluate_short_trade_rejected_target(
    *,
    trade_date: str,
    entry: dict[str, Any],
    rank_hint: int | None = None,
    profile_name: str | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> TargetEvaluationResult:
    if profile_name is not None or profile_overrides:
        with use_short_trade_target_profile(profile_name=profile_name or "default", overrides=profile_overrides):
            return evaluate_short_trade_rejected_target(
                trade_date=trade_date,
                entry=entry,
                rank_hint=rank_hint,
            )
    return _evaluate_short_trade_target(_build_target_input_from_entry(trade_date=trade_date, entry=entry), rank_hint=rank_hint)
