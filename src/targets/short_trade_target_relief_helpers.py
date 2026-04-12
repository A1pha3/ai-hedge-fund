from __future__ import annotations

from typing import Any, Callable

from src.targets.explainability import clamp_unit_interval
from src.targets.models import TargetEvaluationInput


def _build_historical_execution_relief_default_result(
    *,
    historical_prior: dict[str, Any],
    source: str,
    execution_quality_label: str,
    evaluable_count: int,
    next_close_positive_rate: float,
    next_high_hit_rate: float,
    next_open_to_close_return_mean: float,
    base_near_miss_threshold: float,
    base_select_threshold: float,
) -> dict[str, Any]:
    return {
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


def _build_upstream_shadow_catalyst_relief_default_result(
    *,
    relief_reason: str,
    catalyst_freshness: float,
    base_near_miss_threshold: float,
    base_select_threshold: float,
    historical_execution_quality_label: str,
    historical_evaluable_count: int,
    historical_next_close_positive_rate: float,
    historical_next_high_hit_rate: float,
    historical_next_open_to_close_return_mean: float,
) -> dict[str, Any]:
    return {
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


def _build_visibility_gap_continuation_relief_default_result(
    *,
    enabled: bool,
    source: str,
    candidate_pool_lane: str,
    candidate_pool_shadow_reason: str,
    shadow_visibility_gap_selected: bool,
    shadow_visibility_gap_relaxed_band: bool,
    catalyst_freshness: float,
    base_near_miss_threshold: float,
    require_relaxed_band: bool,
    historical_execution_quality_label: str,
    historical_applied_scope: str,
    historical_evaluable_count: int,
    historical_next_close_positive_rate: float,
) -> dict[str, Any]:
    return {
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


def _build_merge_approved_continuation_relief_default_result(
    *,
    enabled: bool,
    base_near_miss_threshold: float,
    base_select_threshold: float,
    require_no_profitability_hard_cliff: bool,
    historical_execution_quality_label: str,
    historical_applied_scope: str,
    historical_evaluable_count: int,
    historical_next_close_positive_rate: float,
) -> dict[str, Any]:
    return {
        "enabled": enabled,
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
        "require_no_profitability_hard_cliff": require_no_profitability_hard_cliff,
        "historical_execution_quality_label": historical_execution_quality_label,
        "historical_applied_scope": historical_applied_scope,
        "historical_evaluable_count": historical_evaluable_count,
        "historical_next_close_positive_rate": historical_next_close_positive_rate,
    }


def _build_upstream_shadow_catalyst_relief_historical_context(historical_prior: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_quality_label": str(historical_prior.get("execution_quality_label") or "unknown"),
        "entry_timing_bias": str(historical_prior.get("entry_timing_bias") or "unknown"),
        "evaluable_count": int(historical_prior.get("evaluable_count") or 0),
        "next_close_positive_rate": clamp_unit_interval(float(historical_prior.get("next_close_positive_rate", 0.0) or 0.0)),
        "next_high_hit_rate": clamp_unit_interval(float(historical_prior.get("next_high_hit_rate_at_threshold", 0.0) or 0.0)),
        "next_open_to_close_return_mean": float(historical_prior.get("next_open_to_close_return_mean", 0.0) or 0.0),
    }


def _build_historical_execution_relief_context(historical_prior: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_quality_label": str(historical_prior.get("execution_quality_label") or "unknown"),
        "evaluable_count": int(historical_prior.get("evaluable_count") or 0),
        "next_close_positive_rate": clamp_unit_interval(float(historical_prior.get("next_close_positive_rate", 0.0) or 0.0)),
        "next_high_hit_rate": clamp_unit_interval(float(historical_prior.get("next_high_hit_rate_at_threshold", 0.0) or 0.0)),
        "next_open_to_close_return_mean": float(historical_prior.get("next_open_to_close_return_mean", 0.0) or 0.0),
    }


def _resolve_historical_execution_relief_support(
    *,
    historical_context: dict[str, Any],
    profitability_hard_cliff: bool,
    catalyst_theme_carryover_candidate: bool,
    strong_carryover_history_min_evaluable_count: int,
) -> tuple[bool, bool]:
    strong_close_continuation_min_evaluable_count = strong_carryover_history_min_evaluable_count if catalyst_theme_carryover_candidate else 2
    strong_close_continuation_candidate = (
        historical_context["execution_quality_label"] == "close_continuation"
        and historical_context["evaluable_count"] >= strong_close_continuation_min_evaluable_count
        and historical_context["next_close_positive_rate"] >= 0.8
        and historical_context["next_high_hit_rate"] >= 0.8
        and historical_context["next_open_to_close_return_mean"] >= 0.02
    )
    execution_quality_support = historical_context["execution_quality_label"] in {"gap_chase_risk", "close_continuation"}
    if catalyst_theme_carryover_candidate:
        execution_quality_support = historical_context["execution_quality_label"] == "close_continuation"
    if profitability_hard_cliff and historical_context["execution_quality_label"] == "gap_chase_risk":
        execution_quality_support = execution_quality_support and historical_context["next_open_to_close_return_mean"] >= 0.0
    return strong_close_continuation_candidate, execution_quality_support


def _build_historical_execution_relief_gate_hits(
    *,
    source: str,
    profitability_hard_cliff: bool,
    catalyst_theme_carryover_candidate: bool,
    historical_context: dict[str, Any],
    strong_close_continuation_candidate: bool,
    execution_quality_support: bool,
) -> dict[str, bool]:
    return {
        "candidate_source": source in {"short_trade_boundary", "upstream_liquidity_corridor_shadow", "post_gate_liquidity_competition_shadow"} or catalyst_theme_carryover_candidate,
        "profitability_hard_cliff": profitability_hard_cliff,
        "evaluable_count": historical_context["evaluable_count"] >= 3 or strong_close_continuation_candidate,
        "execution_quality_support": execution_quality_support,
        "gap_chase_open_to_close_support": (not profitability_hard_cliff)
        or historical_context["execution_quality_label"] != "gap_chase_risk"
        or historical_context["next_open_to_close_return_mean"] >= 0.0,
        "next_close_positive_rate": historical_context["next_close_positive_rate"] >= 0.5,
        "next_high_hit_rate": historical_context["next_high_hit_rate"] >= 0.5,
    }


def _parse_upstream_shadow_catalyst_relief_config(
    *,
    relief_config: dict[str, Any],
    base_near_miss_threshold: float,
    base_select_threshold: float,
    strong_carryover_history_min_evaluable_count: int,
) -> dict[str, Any]:
    return {
        "catalyst_freshness_floor": clamp_unit_interval(float(relief_config.get("catalyst_freshness_floor", 0.0) or 0.0)),
        "near_miss_threshold_override": clamp_unit_interval(
            float(relief_config.get("near_miss_threshold", base_near_miss_threshold) or base_near_miss_threshold)
        ),
        "select_threshold_override": clamp_unit_interval(
            float(relief_config.get("selected_threshold", base_select_threshold) or base_select_threshold)
        ),
        "breakout_freshness_min": clamp_unit_interval(float(relief_config.get("breakout_freshness_min", 0.0) or 0.0)),
        "trend_acceleration_min": clamp_unit_interval(float(relief_config.get("trend_acceleration_min", 0.0) or 0.0)),
        "close_strength_min": clamp_unit_interval(float(relief_config.get("close_strength_min", 0.0) or 0.0)),
        "require_no_profitability_hard_cliff": bool(relief_config.get("require_no_profitability_hard_cliff", False)),
        "required_execution_quality_labels": {
            str(label).strip()
            for label in list(relief_config.get("required_execution_quality_labels") or [])
            if str(label or "").strip()
        },
        "min_historical_evaluable_count": int(relief_config.get("min_historical_evaluable_count", 0) or 0),
        "min_historical_next_close_positive_rate": float(relief_config.get("min_historical_next_close_positive_rate", 0.0) or 0.0),
        "min_historical_next_open_to_close_return_mean": float(
            relief_config.get("min_historical_next_open_to_close_return_mean", -1.0) or -1.0
        ),
        "carryover_min_historical_evaluable_count": int(
            relief_config.get("min_historical_evaluable_count", strong_carryover_history_min_evaluable_count)
            or strong_carryover_history_min_evaluable_count
        ),
    }


def _resolve_upstream_shadow_catalyst_relief_history_support(
    *,
    relief_reason: str,
    historical_context: dict[str, Any],
    config: dict[str, Any],
) -> tuple[bool, bool, bool]:
    carryover_history_supported = True
    if relief_reason == "catalyst_theme_short_trade_carryover":
        carryover_history_supported = (
            historical_context["execution_quality_label"] == "close_continuation"
            and historical_context["entry_timing_bias"] == "confirm_then_hold"
            and historical_context["evaluable_count"] >= config["carryover_min_historical_evaluable_count"]
            and historical_context["next_close_positive_rate"] >= 0.5
        )

    carryover_strong_close_continuation = (
        relief_reason == "catalyst_theme_short_trade_carryover"
        and historical_context["execution_quality_label"] == "close_continuation"
        and historical_context["evaluable_count"] >= config["carryover_min_historical_evaluable_count"]
        and historical_context["next_close_positive_rate"] >= 0.8
        and historical_context["next_high_hit_rate"] >= 0.8
        and historical_context["next_open_to_close_return_mean"] >= 0.02
    )

    upstream_shadow_history_supported = True
    if relief_reason == "upstream_shadow_catalyst_relief" and config["required_execution_quality_labels"]:
        upstream_shadow_history_supported = (
            historical_context["execution_quality_label"] in config["required_execution_quality_labels"]
            and historical_context["evaluable_count"] >= config["min_historical_evaluable_count"]
            and historical_context["next_close_positive_rate"] >= config["min_historical_next_close_positive_rate"]
            and historical_context["next_open_to_close_return_mean"] >= config["min_historical_next_open_to_close_return_mean"]
        )

    return carryover_history_supported, carryover_strong_close_continuation, upstream_shadow_history_supported


def _build_upstream_shadow_catalyst_relief_gate_hits(
    *,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    profitability_hard_cliff: bool,
    relief_reason: str,
    config: dict[str, Any],
    carryover_history_supported: bool,
    upstream_shadow_history_supported: bool,
) -> dict[str, bool]:
    return {
        "breakout_freshness": breakout_freshness >= config["breakout_freshness_min"],
        "trend_acceleration": trend_acceleration >= config["trend_acceleration_min"],
        "close_strength": close_strength >= config["close_strength_min"],
        "no_profitability_hard_cliff": (not config["require_no_profitability_hard_cliff"]) or (not profitability_hard_cliff),
        **({"historical_continuation_quality": carryover_history_supported} if relief_reason == "catalyst_theme_short_trade_carryover" else {}),
        **(
            {"historical_continuation_quality": upstream_shadow_history_supported}
            if relief_reason == "upstream_shadow_catalyst_relief" and config["required_execution_quality_labels"]
            else {}
        ),
    }


def _apply_upstream_shadow_catalyst_relief_thresholds(
    *,
    eligible: bool,
    catalyst_freshness: float,
    base_near_miss_threshold: float,
    base_select_threshold: float,
    config: dict[str, Any],
    carryover_strong_close_continuation: bool,
) -> tuple[float, float, float]:
    effective_catalyst_freshness = catalyst_freshness
    effective_near_miss_threshold = base_near_miss_threshold
    effective_select_threshold = base_select_threshold
    if eligible:
        effective_catalyst_freshness = max(catalyst_freshness, config["catalyst_freshness_floor"])
        effective_near_miss_threshold = min(base_near_miss_threshold, config["near_miss_threshold_override"])
        effective_select_threshold = min(base_select_threshold, config["select_threshold_override"])
        if carryover_strong_close_continuation:
            effective_select_threshold = min(effective_select_threshold, 0.45)
    return effective_catalyst_freshness, effective_near_miss_threshold, effective_select_threshold


def _build_upstream_shadow_catalyst_relief_result(
    *,
    relief_reason: str,
    gate_hits: dict[str, bool],
    eligible: bool,
    catalyst_freshness: float,
    base_near_miss_threshold: float,
    base_select_threshold: float,
    effective_catalyst_freshness: float,
    effective_near_miss_threshold: float,
    effective_select_threshold: float,
    config: dict[str, Any],
    historical_context: dict[str, Any],
    carryover_strong_close_continuation: bool,
) -> dict[str, Any]:
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
        "catalyst_freshness_floor": config["catalyst_freshness_floor"],
        "near_miss_threshold_override": config["near_miss_threshold_override"],
        "select_threshold_override": config["select_threshold_override"],
        "require_no_profitability_hard_cliff": config["require_no_profitability_hard_cliff"],
        "historical_execution_quality_label": historical_context["execution_quality_label"],
        "historical_evaluable_count": historical_context["evaluable_count"],
        "historical_next_close_positive_rate": historical_context["next_close_positive_rate"],
        "historical_next_high_hit_rate_at_threshold": historical_context["next_high_hit_rate"],
        "historical_next_open_to_close_return_mean": historical_context["next_open_to_close_return_mean"],
        "historical_strong_close_continuation": carryover_strong_close_continuation,
    }


def _has_weak_intraday_or_zero_follow_through_history(historical_prior: dict[str, Any]) -> tuple[bool, str, str, int, float]:
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
    return (
        weak_same_ticker_intraday_history or weak_zero_follow_through_history,
        historical_execution_quality_label,
        historical_applied_scope,
        historical_evaluable_count,
        historical_next_close_positive_rate,
    )


def _parse_visibility_gap_continuation_relief_config(
    *,
    profile: Any,
    base_near_miss_threshold: float,
) -> dict[str, Any]:
    return {
        "require_relaxed_band": bool(profile.visibility_gap_continuation_require_relaxed_band),
        "breakout_freshness_min": clamp_unit_interval(float(profile.visibility_gap_continuation_breakout_freshness_min or 0.0)),
        "trend_acceleration_min": clamp_unit_interval(float(profile.visibility_gap_continuation_trend_acceleration_min or 0.0)),
        "close_strength_min": clamp_unit_interval(float(profile.visibility_gap_continuation_close_strength_min or 0.0)),
        "catalyst_freshness_floor": clamp_unit_interval(float(profile.visibility_gap_continuation_catalyst_freshness_floor or 0.0)),
        "near_miss_threshold_override": clamp_unit_interval(float(profile.visibility_gap_continuation_near_miss_threshold or base_near_miss_threshold)),
    }


def _build_visibility_gap_continuation_relief_gate_hits(
    *,
    source: str,
    shadow_visibility_gap_selected: bool,
    shadow_visibility_gap_relaxed_band: bool,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    profitability_hard_cliff: bool,
    weak_history: bool,
    config: dict[str, Any],
) -> dict[str, bool]:
    return {
        "candidate_source": source in {"upstream_liquidity_corridor_shadow", "post_gate_liquidity_competition_shadow"},
        "visibility_gap_selected": shadow_visibility_gap_selected,
        "relaxed_band": (not config["require_relaxed_band"]) or shadow_visibility_gap_relaxed_band,
        "breakout_freshness": breakout_freshness >= config["breakout_freshness_min"],
        "trend_acceleration": trend_acceleration >= config["trend_acceleration_min"],
        "close_strength": close_strength >= config["close_strength_min"],
        "no_profitability_hard_cliff": not profitability_hard_cliff,
        "historical_execution_quality": not weak_history,
    }


def _parse_merge_approved_continuation_relief_config(profile: Any) -> dict[str, Any]:
    return {
        "enabled": bool(profile.merge_approved_continuation_relief_enabled),
        "near_miss_threshold_override": clamp_unit_interval(float(profile.merge_approved_continuation_near_miss_threshold)),
        "select_threshold_override": clamp_unit_interval(float(profile.merge_approved_continuation_select_threshold)),
        "breakout_freshness_min": float(profile.merge_approved_continuation_breakout_freshness_min),
        "trend_acceleration_min": float(profile.merge_approved_continuation_trend_acceleration_min),
        "close_strength_min": float(profile.merge_approved_continuation_close_strength_min),
        "require_no_profitability_hard_cliff": bool(profile.merge_approved_continuation_require_no_profitability_hard_cliff),
    }


def _build_merge_approved_continuation_relief_gate_hits(
    *,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    profitability_hard_cliff: bool,
    weak_history: bool,
    config: dict[str, Any],
) -> dict[str, bool]:
    return {
        "breakout_freshness": breakout_freshness >= config["breakout_freshness_min"],
        "trend_acceleration": trend_acceleration >= config["trend_acceleration_min"],
        "close_strength": close_strength >= config["close_strength_min"],
        "no_profitability_hard_cliff": (not config["require_no_profitability_hard_cliff"]) or (not profitability_hard_cliff),
        "historical_execution_quality": not weak_history,
    }


def resolve_historical_execution_relief(
    *,
    input_data: TargetEvaluationInput,
    profitability_hard_cliff: bool,
    profile: Any,
    historical_prior_getter: Callable[[TargetEvaluationInput], dict[str, Any]],
    normalized_reason_codes: Callable[[Any], list[str]],
    is_catalyst_theme_carryover_candidate: Callable[..., bool],
    strong_carryover_history_min_evaluable_count: int,
) -> dict[str, Any]:
    historical_prior = historical_prior_getter(input_data)
    source = str(input_data.replay_context.get("source") or "").strip()
    candidate_reason_codes = set(normalized_reason_codes(input_data.replay_context.get("candidate_reason_codes")))
    catalyst_theme_carryover_candidate = is_catalyst_theme_carryover_candidate(
        source=source,
        candidate_reason_codes=candidate_reason_codes,
    )
    base_near_miss_threshold = float(profile.near_miss_threshold)
    base_select_threshold = float(profile.select_threshold)
    historical_context = _build_historical_execution_relief_context(historical_prior)
    default_result = _build_historical_execution_relief_default_result(
        historical_prior=historical_prior,
        source=source,
        execution_quality_label=historical_context["execution_quality_label"],
        evaluable_count=historical_context["evaluable_count"],
        next_close_positive_rate=historical_context["next_close_positive_rate"],
        next_high_hit_rate=historical_context["next_high_hit_rate"],
        next_open_to_close_return_mean=historical_context["next_open_to_close_return_mean"],
        base_near_miss_threshold=base_near_miss_threshold,
        base_select_threshold=base_select_threshold,
    )
    if not historical_prior:
        return default_result

    strong_close_continuation_candidate, execution_quality_support = _resolve_historical_execution_relief_support(
        historical_context=historical_context,
        profitability_hard_cliff=profitability_hard_cliff,
        catalyst_theme_carryover_candidate=catalyst_theme_carryover_candidate,
        strong_carryover_history_min_evaluable_count=strong_carryover_history_min_evaluable_count,
    )
    gate_hits = _build_historical_execution_relief_gate_hits(
        source=source,
        profitability_hard_cliff=profitability_hard_cliff,
        catalyst_theme_carryover_candidate=catalyst_theme_carryover_candidate,
        historical_context=historical_context,
        strong_close_continuation_candidate=strong_close_continuation_candidate,
        execution_quality_support=execution_quality_support,
    )
    eligible = all(gate_hits.values())
    strong_close_continuation = strong_close_continuation_candidate and eligible
    near_miss_threshold_override = base_near_miss_threshold
    select_threshold_override = base_select_threshold
    if eligible:
        near_miss_threshold_override = min(
            base_near_miss_threshold,
            0.39
            if (
                historical_context["execution_quality_label"] == "gap_chase_risk" and not catalyst_theme_carryover_candidate
            )
            or strong_close_continuation
            else 0.40,
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
        "execution_quality_label": historical_context["execution_quality_label"],
        "evaluable_count": historical_context["evaluable_count"],
        "next_close_positive_rate": historical_context["next_close_positive_rate"],
        "next_high_hit_rate_at_threshold": historical_context["next_high_hit_rate"],
        "next_open_to_close_return_mean": historical_context["next_open_to_close_return_mean"],
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


def resolve_upstream_shadow_catalyst_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    catalyst_freshness: float,
    profitability_hard_cliff: bool,
    profile: Any,
    historical_prior_getter: Callable[[TargetEvaluationInput], dict[str, Any]],
    normalized_reason_codes: Callable[[Any], list[str]],
    strong_carryover_history_min_evaluable_count: int,
) -> dict[str, Any]:
    relief_payload = input_data.replay_context.get("short_trade_catalyst_relief")
    relief_config = dict(relief_payload) if isinstance(relief_payload, dict) else {}
    relief_reason = str(relief_config.get("reason") or "upstream_shadow_catalyst_relief")
    historical_prior = historical_prior_getter(input_data)
    historical_context = _build_upstream_shadow_catalyst_relief_historical_context(historical_prior)
    base_near_miss_threshold = float(profile.near_miss_threshold)
    base_select_threshold = float(profile.select_threshold)
    default_result = _build_upstream_shadow_catalyst_relief_default_result(
        relief_reason=relief_reason,
        catalyst_freshness=catalyst_freshness,
        base_near_miss_threshold=base_near_miss_threshold,
        base_select_threshold=base_select_threshold,
        historical_execution_quality_label=historical_context["execution_quality_label"],
        historical_evaluable_count=historical_context["evaluable_count"],
        historical_next_close_positive_rate=historical_context["next_close_positive_rate"],
        historical_next_high_hit_rate=historical_context["next_high_hit_rate"],
        historical_next_open_to_close_return_mean=historical_context["next_open_to_close_return_mean"],
    )

    candidate_reason_codes = set(normalized_reason_codes(input_data.replay_context.get("candidate_reason_codes")))
    if not relief_config or not (candidate_reason_codes & {"upstream_shadow_release_candidate", "catalyst_theme_short_trade_carryover_candidate"}):
        return default_result

    enabled = bool(relief_config.get("enabled", True))
    if not enabled:
        return {**default_result, "reason": relief_reason}

    config = _parse_upstream_shadow_catalyst_relief_config(
        relief_config=relief_config,
        base_near_miss_threshold=base_near_miss_threshold,
        base_select_threshold=base_select_threshold,
        strong_carryover_history_min_evaluable_count=strong_carryover_history_min_evaluable_count,
    )
    carryover_history_supported, carryover_strong_close_continuation, upstream_shadow_history_supported = _resolve_upstream_shadow_catalyst_relief_history_support(
        relief_reason=relief_reason,
        historical_context=historical_context,
        config=config,
    )
    gate_hits = _build_upstream_shadow_catalyst_relief_gate_hits(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        profitability_hard_cliff=profitability_hard_cliff,
        relief_reason=relief_reason,
        config=config,
        carryover_history_supported=carryover_history_supported,
        upstream_shadow_history_supported=upstream_shadow_history_supported,
    )
    eligible = all(gate_hits.values())
    effective_catalyst_freshness, effective_near_miss_threshold, effective_select_threshold = _apply_upstream_shadow_catalyst_relief_thresholds(
        eligible=eligible,
        catalyst_freshness=catalyst_freshness,
        base_near_miss_threshold=base_near_miss_threshold,
        base_select_threshold=base_select_threshold,
        config=config,
        carryover_strong_close_continuation=carryover_strong_close_continuation,
    )
    return _build_upstream_shadow_catalyst_relief_result(
        relief_reason=relief_reason,
        gate_hits=gate_hits,
        eligible=eligible,
        catalyst_freshness=catalyst_freshness,
        base_near_miss_threshold=base_near_miss_threshold,
        base_select_threshold=base_select_threshold,
        effective_catalyst_freshness=effective_catalyst_freshness,
        effective_near_miss_threshold=effective_near_miss_threshold,
        effective_select_threshold=effective_select_threshold,
        config=config,
        historical_context=historical_context,
        carryover_strong_close_continuation=carryover_strong_close_continuation,
    )


def resolve_visibility_gap_continuation_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    catalyst_freshness: float,
    profitability_hard_cliff: bool,
    profile: Any,
    historical_prior_getter: Callable[[TargetEvaluationInput], dict[str, Any]],
) -> dict[str, Any]:
    enabled = bool(profile.visibility_gap_continuation_relief_enabled)
    source = str(input_data.replay_context.get("source") or "").strip()
    candidate_pool_shadow_reason = str(input_data.replay_context.get("candidate_pool_shadow_reason") or "").strip()
    candidate_pool_lane = str(input_data.replay_context.get("candidate_pool_lane") or "").strip()
    shadow_visibility_gap_selected = bool(input_data.replay_context.get("shadow_visibility_gap_selected"))
    shadow_visibility_gap_relaxed_band = bool(input_data.replay_context.get("shadow_visibility_gap_relaxed_band"))
    historical_prior = historical_prior_getter(input_data)
    base_near_miss_threshold = float(profile.near_miss_threshold)
    config = _parse_visibility_gap_continuation_relief_config(
        profile=profile,
        base_near_miss_threshold=base_near_miss_threshold,
    )
    weak_history, historical_execution_quality_label, historical_applied_scope, historical_evaluable_count, historical_next_close_positive_rate = _has_weak_intraday_or_zero_follow_through_history(historical_prior)
    default_result = _build_visibility_gap_continuation_relief_default_result(
        enabled=enabled,
        source=source,
        candidate_pool_lane=candidate_pool_lane,
        candidate_pool_shadow_reason=candidate_pool_shadow_reason,
        shadow_visibility_gap_selected=shadow_visibility_gap_selected,
        shadow_visibility_gap_relaxed_band=shadow_visibility_gap_relaxed_band,
        catalyst_freshness=catalyst_freshness,
        base_near_miss_threshold=base_near_miss_threshold,
        require_relaxed_band=config["require_relaxed_band"],
        historical_execution_quality_label=historical_execution_quality_label,
        historical_applied_scope=historical_applied_scope,
        historical_evaluable_count=historical_evaluable_count,
        historical_next_close_positive_rate=historical_next_close_positive_rate,
    )
    if not enabled:
        return default_result

    gate_hits = _build_visibility_gap_continuation_relief_gate_hits(
        source=source,
        shadow_visibility_gap_selected=shadow_visibility_gap_selected,
        shadow_visibility_gap_relaxed_band=shadow_visibility_gap_relaxed_band,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        profitability_hard_cliff=profitability_hard_cliff,
        weak_history=weak_history,
        config=config,
    )
    eligible = all(gate_hits.values())
    effective_catalyst_freshness = catalyst_freshness
    effective_near_miss_threshold = base_near_miss_threshold
    if eligible:
        effective_catalyst_freshness = max(catalyst_freshness, config["catalyst_freshness_floor"])
        effective_near_miss_threshold = min(base_near_miss_threshold, config["near_miss_threshold_override"])

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
        "catalyst_freshness_floor": config["catalyst_freshness_floor"],
        "near_miss_threshold_override": config["near_miss_threshold_override"],
        "require_relaxed_band": config["require_relaxed_band"],
        "historical_execution_quality_label": historical_execution_quality_label,
        "historical_applied_scope": historical_applied_scope,
        "historical_evaluable_count": historical_evaluable_count,
        "historical_next_close_positive_rate": historical_next_close_positive_rate,
    }


def resolve_merge_approved_continuation_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    profitability_hard_cliff: bool,
    profile: Any,
    historical_prior_getter: Callable[[TargetEvaluationInput], dict[str, Any]],
) -> dict[str, Any]:
    candidate_reason_codes = {
        str(code).strip()
        for code in list(input_data.replay_context.get("candidate_reason_codes") or [])
        if str(code or "").strip()
    }
    historical_prior = historical_prior_getter(input_data)
    base_near_miss_threshold = float(profile.near_miss_threshold)
    base_select_threshold = float(profile.select_threshold)
    config = _parse_merge_approved_continuation_relief_config(profile)
    weak_history, historical_execution_quality_label, historical_applied_scope, historical_evaluable_count, historical_next_close_positive_rate = _has_weak_intraday_or_zero_follow_through_history(historical_prior)
    default_result = _build_merge_approved_continuation_relief_default_result(
        enabled=config["enabled"],
        base_near_miss_threshold=base_near_miss_threshold,
        base_select_threshold=base_select_threshold,
        require_no_profitability_hard_cliff=config["require_no_profitability_hard_cliff"],
        historical_execution_quality_label=historical_execution_quality_label,
        historical_applied_scope=historical_applied_scope,
        historical_evaluable_count=historical_evaluable_count,
        historical_next_close_positive_rate=historical_next_close_positive_rate,
    )
    if "merge_approved_continuation" not in candidate_reason_codes or not config["enabled"]:
        return default_result

    gate_hits = _build_merge_approved_continuation_relief_gate_hits(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        profitability_hard_cliff=profitability_hard_cliff,
        weak_history=weak_history,
        config=config,
    )
    eligible = all(gate_hits.values())
    effective_near_miss_threshold = base_near_miss_threshold
    effective_select_threshold = base_select_threshold
    if eligible:
        effective_near_miss_threshold = min(base_near_miss_threshold, config["near_miss_threshold_override"])
        effective_select_threshold = min(base_select_threshold, config["select_threshold_override"])

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
        "near_miss_threshold_override": config["near_miss_threshold_override"],
        "select_threshold_override": config["select_threshold_override"],
        "require_no_profitability_hard_cliff": config["require_no_profitability_hard_cliff"],
        "historical_execution_quality_label": historical_execution_quality_label,
        "historical_applied_scope": historical_applied_scope,
        "historical_evaluable_count": historical_evaluable_count,
        "historical_next_close_positive_rate": historical_next_close_positive_rate,
    }
