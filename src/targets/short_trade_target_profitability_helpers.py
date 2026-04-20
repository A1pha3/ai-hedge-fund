from __future__ import annotations

from typing import Any
from collections.abc import Callable

from src.screening.models import StrategySignal
from src.targets.explainability import clamp_unit_interval
from src.targets.models import TargetEvaluationInput


def _has_weak_profitability_hard_cliff_boundary_history(input_data: TargetEvaluationInput) -> bool:
    historical_prior = dict(input_data.replay_context.get("historical_prior") or {})
    historical_execution_quality_label = str(historical_prior.get("execution_quality_label") or "unknown")
    historical_applied_scope = str(historical_prior.get("applied_scope") or "")
    historical_evaluable_count = int(historical_prior.get("evaluable_count") or 0)
    historical_next_close_positive_rate = clamp_unit_interval(float(historical_prior.get("next_close_positive_rate", 0.0) or 0.0))
    historical_next_close_return_mean = float(historical_prior.get("next_close_return_mean", 0.0) or 0.0)
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
    weak_family_source_catalyst_history = (
        historical_applied_scope in {"family_source_score_catalyst", "same_family_source_score_catalyst"}
        and historical_evaluable_count >= 8
        and historical_next_close_return_mean < 0.0
    )
    return weak_same_ticker_intraday_history or weak_zero_follow_through_history or weak_family_source_catalyst_history


def resolve_profitability_relief_impl(
    *,
    input_data: TargetEvaluationInput,
    fundamental_signal: StrategySignal | None,
    breakout_freshness: float,
    catalyst_freshness: float,
    sector_resonance: float,
    profile: Any,
    profitability_snapshot_fn: Callable[[StrategySignal | None], dict[str, Any]],
) -> dict[str, Any]:
    profitability = profitability_snapshot_fn(fundamental_signal)
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


def resolve_profitability_hard_cliff_boundary_relief_impl(
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
    weak_history = _has_weak_profitability_hard_cliff_boundary_history(input_data)
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
        "historical_execution_quality": not weak_history,
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
