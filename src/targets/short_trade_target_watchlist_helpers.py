from __future__ import annotations

from collections.abc import Callable
from typing import Any

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


def _build_default_source_penalty_result(*, enabled: bool, source: str) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "gate_hits": {},
        "effective_penalty": 0.0,
    }


def _build_default_selected_threshold_lift_result(*, enabled: bool, source: str) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "gate_hits": {},
        "select_threshold_lift": 0.0,
        "reason_code": None,
    }


def _resolve_selected_only_shrink_guard(
    *,
    profile: Any,
    source: str,
    eligible_source: str,
    reason_code: str,
    select_threshold_lift_attr: str,
    catalyst_freshness_max_attr: str,
    trend_acceleration_max_attr: str,
    close_strength_max_attr: str,
    catalyst_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    enabled = bool(getattr(profile, f"{eligible_source}_selected_only_shrink_enabled", False))
    default_result = _build_default_selected_threshold_lift_result(enabled=enabled, source=source)
    if not enabled or source != eligible_source:
        return default_result

    gate_hits = {
        "candidate_source": source == eligible_source,
        "catalyst_freshness": catalyst_freshness <= clamp_unit_interval_fn(float(getattr(profile, catalyst_freshness_max_attr, 0.0) or 0.0)),
        "trend_acceleration": trend_acceleration <= clamp_unit_interval_fn(float(getattr(profile, trend_acceleration_max_attr, 0.0) or 0.0)),
        "close_strength": close_strength <= clamp_unit_interval_fn(float(getattr(profile, close_strength_max_attr, 0.0) or 0.0)),
    }
    eligible = all(gate_hits.values())
    select_threshold_lift = clamp_unit_interval_fn(float(getattr(profile, select_threshold_lift_attr, 0.0) or 0.0)) if eligible else 0.0
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and select_threshold_lift > 0.0,
        "candidate_source": source,
        "gate_hits": gate_hits,
        "select_threshold_lift": select_threshold_lift,
        "reason_code": reason_code if eligible else None,
    }


def resolve_watchlist_penalty_rule(
    *,
    input_data: TargetEvaluationInput,
    penalty: float,
    gate_hits: dict[str, bool],
    eligible_source: str = "layer_c_watchlist",
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    default_result = _build_default_watchlist_rule_result(enabled=penalty > 0.0, source=source)
    if penalty <= 0.0 or source != eligible_source:
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


def resolve_catalyst_theme_penalty_impl(
    *,
    input_data: TargetEvaluationInput,
    profile: Any,
    normalized_reason_codes: Callable[[Any], list[str]],
    exempt_carryover_candidate_fn: Callable[..., bool],
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    penalty = clamp_unit_interval_fn(float(profile.catalyst_theme_penalty or 0.0))
    candidate_reason_codes = set(normalized_reason_codes(input_data.replay_context.get("candidate_reason_codes")))
    carryover_exempt = exempt_carryover_candidate_fn(source=source, candidate_reason_codes=candidate_reason_codes)
    default_result = _build_default_source_penalty_result(enabled=penalty > 0.0, source=source)
    if penalty <= 0.0 or source != "catalyst_theme" or carryover_exempt:
        return {
            **default_result,
            "gate_hits": {
                "candidate_source": source == "catalyst_theme",
                "carryover_exempt": not carryover_exempt,
            },
        }

    return {
        "enabled": True,
        "eligible": True,
        "applied": True,
        "candidate_source": source,
        "gate_hits": {
            "candidate_source": True,
            "carryover_exempt": True,
        },
        "effective_penalty": penalty,
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


def resolve_watchlist_filter_diagnostics_flat_trend_penalty_impl(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    trend_acceleration: float,
    profile: Any,
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    penalty = clamp_unit_interval_fn(float(profile.watchlist_filter_diagnostics_flat_trend_penalty or 0.0))
    return resolve_watchlist_penalty_rule(
        input_data=input_data,
        penalty=penalty,
        eligible_source="watchlist_filter_diagnostics",
        gate_hits={
            "candidate_source": source == "watchlist_filter_diagnostics",
            "catalyst_freshness": catalyst_freshness <= clamp_unit_interval_fn(float(profile.watchlist_filter_diagnostics_flat_trend_catalyst_freshness_max or 0.0)),
            "close_strength": close_strength >= clamp_unit_interval_fn(float(profile.watchlist_filter_diagnostics_flat_trend_close_strength_min or 0.0)),
            "trend_acceleration": trend_acceleration <= clamp_unit_interval_fn(float(profile.watchlist_filter_diagnostics_flat_trend_trend_acceleration_max or 0.0)),
        },
    )


def resolve_watchlist_filter_diagnostics_selected_only_shrink_impl(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    trend_acceleration: float,
    profile: Any,
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    return _resolve_selected_only_shrink_guard(
        profile=profile,
        source=source,
        eligible_source="watchlist_filter_diagnostics",
        reason_code="watchlist_filter_diagnostics_selected_only_shrink",
        select_threshold_lift_attr="watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift",
        catalyst_freshness_max_attr="watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max",
        trend_acceleration_max_attr="watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max",
        close_strength_max_attr="watchlist_filter_diagnostics_selected_only_shrink_close_strength_max",
        catalyst_freshness=catalyst_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        clamp_unit_interval_fn=clamp_unit_interval_fn,
    )


def resolve_layer_c_watchlist_selected_only_shrink_impl(
    *,
    source: str,
    catalyst_freshness: float,
    close_strength: float,
    trend_acceleration: float,
    profile: Any,
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    return _resolve_selected_only_shrink_guard(
        profile=profile,
        source=source,
        eligible_source="layer_c_watchlist",
        reason_code="layer_c_watchlist_selected_only_shrink",
        select_threshold_lift_attr="layer_c_watchlist_selected_only_shrink_select_threshold_lift",
        catalyst_freshness_max_attr="layer_c_watchlist_selected_only_shrink_catalyst_freshness_max",
        trend_acceleration_max_attr="layer_c_watchlist_selected_only_shrink_trend_acceleration_max",
        close_strength_max_attr="layer_c_watchlist_selected_only_shrink_close_strength_max",
        catalyst_freshness=catalyst_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        clamp_unit_interval_fn=clamp_unit_interval_fn,
    )


def resolve_short_trade_boundary_selected_only_shrink_impl(
    *,
    profile: Any,
    source: str,
    close_strength: float,
    catalyst_freshness: float,
    trend_acceleration: float,
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    return _resolve_selected_only_shrink_guard(
        profile=profile,
        source=source,
        eligible_source="short_trade_boundary",
        reason_code="short_trade_boundary_selected_only_shrink",
        select_threshold_lift_attr="short_trade_boundary_selected_only_shrink_select_threshold_lift",
        catalyst_freshness_max_attr="short_trade_boundary_selected_only_shrink_catalyst_freshness_max",
        trend_acceleration_max_attr="short_trade_boundary_selected_only_shrink_trend_acceleration_max",
        close_strength_max_attr="short_trade_boundary_selected_only_shrink_close_strength_max",
        catalyst_freshness=catalyst_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        clamp_unit_interval_fn=clamp_unit_interval_fn,
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
    eligible_sources = {"layer_c_watchlist", "short_trade_boundary"}
    enabled = bool(profile.t_plus_2_continuation_enabled)
    weak_history = _has_weak_t_plus_2_history(input_data=input_data, clamp_unit_interval_fn=clamp_unit_interval_fn)
    default_result = {
        "enabled": enabled,
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "gate_hits": {},
    }
    if not enabled or source not in eligible_sources:
        return default_result

    gate_hits = {
        "candidate_source": source in eligible_sources,
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
