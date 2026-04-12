from __future__ import annotations

from typing import Any, Callable

from src.targets.models import TargetEvaluationInput


def _has_weak_t_plus_2_history(*, input_data: TargetEvaluationInput, clamp_unit_interval_fn: Callable[[float], float]) -> bool:
    historical_prior = dict(input_data.replay_context.get("historical_prior") or {})
    historical_execution_quality_label = str(historical_prior.get("execution_quality_label") or "unknown")
    historical_applied_scope = str(historical_prior.get("applied_scope") or "")
    historical_evaluable_count = int(historical_prior.get("evaluable_count") or 0)
    historical_next_close_positive_rate = clamp_unit_interval_fn(float(historical_prior.get("next_close_positive_rate", 0.0) or 0.0))
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
    return weak_same_ticker_intraday_history or weak_zero_follow_through_history


def _build_default_watchlist_rule_result(*, enabled: bool, source: str) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "gate_hits": {},
        "effective_penalty": 0.0,
    }


def resolve_watchlist_penalty_rule(
    *,
    input_data: TargetEvaluationInput,
    penalty: float,
    gate_hits: dict[str, bool],
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    default_result = _build_default_watchlist_rule_result(enabled=penalty > 0.0, source=source)
    if penalty <= 0.0 or source != "layer_c_watchlist":
        return default_result

    eligible = all(gate_hits.values())
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible,
        "candidate_source": source,
        "gate_hits": gate_hits,
        "effective_penalty": penalty if eligible else 0.0,
    }


def resolve_watchlist_zero_catalyst_penalty_impl(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    profile: Any,
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    penalty = clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_penalty or 0.0))
    return resolve_watchlist_penalty_rule(
        input_data=input_data,
        penalty=penalty,
        gate_hits={
            "candidate_source": source == "layer_c_watchlist",
            "catalyst_freshness": catalyst_freshness <= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_catalyst_freshness_max or 0.0)),
            "close_strength": close_strength >= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_close_strength_min or 0.0)),
            "layer_c_alignment": layer_c_alignment >= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_layer_c_alignment_min or 0.0)),
            "sector_resonance": sector_resonance >= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_sector_resonance_min or 0.0)),
        },
    )


def resolve_watchlist_zero_catalyst_crowded_penalty_impl(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    profile: Any,
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    penalty = clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_crowded_penalty or 0.0))
    return resolve_watchlist_penalty_rule(
        input_data=input_data,
        penalty=penalty,
        gate_hits={
            "candidate_source": source == "layer_c_watchlist",
            "catalyst_freshness": catalyst_freshness <= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_crowded_catalyst_freshness_max or 0.0)),
            "close_strength": close_strength >= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_crowded_close_strength_min or 0.0)),
            "layer_c_alignment": layer_c_alignment >= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_crowded_layer_c_alignment_min or 0.0)),
            "sector_resonance": sector_resonance >= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_crowded_sector_resonance_min or 0.0)),
        },
    )


def resolve_watchlist_zero_catalyst_flat_trend_penalty_impl(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    trend_acceleration: float,
    profile: Any,
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    penalty = clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_flat_trend_penalty or 0.0))
    return resolve_watchlist_penalty_rule(
        input_data=input_data,
        penalty=penalty,
        gate_hits={
            "candidate_source": source == "layer_c_watchlist",
            "catalyst_freshness": catalyst_freshness <= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_flat_trend_catalyst_freshness_max or 0.0)),
            "close_strength": close_strength >= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_flat_trend_close_strength_min or 0.0)),
            "layer_c_alignment": layer_c_alignment >= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_flat_trend_layer_c_alignment_min or 0.0)),
            "sector_resonance": sector_resonance >= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_flat_trend_sector_resonance_min or 0.0)),
            "trend_acceleration": trend_acceleration <= clamp_unit_interval_fn(float(profile.watchlist_zero_catalyst_flat_trend_trend_acceleration_max or 0.0)),
        },
    )


def resolve_t_plus_2_continuation_candidate_impl(
    *,
    input_data: TargetEvaluationInput,
    raw_catalyst_freshness: float,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    profile: Any,
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    enabled = bool(profile.t_plus_2_continuation_enabled)
    weak_history = _has_weak_t_plus_2_history(input_data=input_data, clamp_unit_interval_fn=clamp_unit_interval_fn)
    default_result = {
        "enabled": enabled,
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "gate_hits": {},
    }
    if not enabled or source != "layer_c_watchlist":
        return default_result

    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "catalyst_freshness": raw_catalyst_freshness <= clamp_unit_interval_fn(float(profile.t_plus_2_continuation_catalyst_freshness_max or 0.0)),
        "breakout_freshness": breakout_freshness >= clamp_unit_interval_fn(float(profile.t_plus_2_continuation_breakout_freshness_min or 0.0)),
        "trend_acceleration": trend_acceleration >= clamp_unit_interval_fn(float(profile.t_plus_2_continuation_trend_acceleration_min or 0.0)),
        "trend_acceleration_cap": trend_acceleration <= clamp_unit_interval_fn(float(profile.t_plus_2_continuation_trend_acceleration_max or 0.0)),
        "layer_c_alignment_min": layer_c_alignment >= clamp_unit_interval_fn(float(profile.t_plus_2_continuation_layer_c_alignment_min or 0.0)),
        "layer_c_alignment_max": layer_c_alignment <= clamp_unit_interval_fn(float(profile.t_plus_2_continuation_layer_c_alignment_max or 0.0)),
        "close_strength": close_strength <= clamp_unit_interval_fn(float(profile.t_plus_2_continuation_close_strength_max or 0.0)),
        "sector_resonance": sector_resonance <= clamp_unit_interval_fn(float(profile.t_plus_2_continuation_sector_resonance_max or 0.0)),
        "historical_execution_quality": not weak_history,
    }
    eligible = all(gate_hits.values())
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible,
        "candidate_source": source,
        "gate_hits": gate_hits,
    }
