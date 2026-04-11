from __future__ import annotations

from typing import Any


def _execution_quality_support_delta(execution_quality_label: str) -> float:
    if execution_quality_label == "close_continuation":
        return 0.10
    if execution_quality_label == "gap_chase_risk":
        return 0.08
    if execution_quality_label == "balanced_confirmation":
        return 0.05
    if execution_quality_label == "intraday_only":
        return -0.08
    if execution_quality_label == "zero_follow_through":
        return -0.12
    return 0.0


def _apply_historical_rate_support(
    *,
    support_score: float,
    evaluable_count: int,
    next_close_positive_rate: float | None,
    next_high_hit_rate: float | None,
) -> float:
    if evaluable_count >= 3 and next_close_positive_rate is not None:
        if next_close_positive_rate >= 0.5:
            support_score += 0.04
        elif next_close_positive_rate <= 0.0:
            support_score -= 0.04
    if evaluable_count >= 3 and next_high_hit_rate is not None:
        if next_high_hit_rate >= 0.5:
            support_score += 0.04
        elif next_high_hit_rate < 0.25:
            support_score -= 0.02
    return support_score


def _is_sparse_weak_history(
    *,
    evaluable_count: int,
    next_close_positive_rate: float | None,
    next_high_hit_rate: float | None,
) -> bool:
    return (
        0 < evaluable_count < 3
        and next_close_positive_rate is not None
        and next_close_positive_rate <= 0.0
        and next_high_hit_rate is not None
        and next_high_hit_rate <= 0.0
    )


def _should_suppress_shadow_release(
    *,
    applied_scope: str,
    execution_quality_label: str,
    evaluable_count: int,
    next_close_positive_rate: float | None,
    pruned_from_opportunity_pool: bool,
    prune_reason: str,
) -> bool:
    if pruned_from_opportunity_pool and prune_reason == "historical_zero_follow_through":
        return True
    return evaluable_count >= 3 and (
        execution_quality_label == "zero_follow_through"
        or (execution_quality_label == "intraday_only" and (next_close_positive_rate or 0.0) <= 0.0)
        or (applied_scope == "same_ticker" and execution_quality_label == "intraday_only" and (next_close_positive_rate or 0.0) <= 0.0)
    )


def _support_verdict(*, suppress_release: bool, support_score: float) -> str:
    if suppress_release:
        return "suppress_release"
    if support_score > 0:
        return "supportive"
    if support_score < 0:
        return "caution"
    return "neutral"


def summarize_shadow_release_historical_support(
    *,
    execution_quality_label: str,
    applied_scope: str,
    evaluable_count: int,
    next_close_positive_rate: float | None,
    next_high_hit_rate: float | None,
    pruned_from_opportunity_pool: bool = False,
    prune_reason: str = "",
) -> dict[str, Any]:
    support_score = _execution_quality_support_delta(execution_quality_label)
    support_score = _apply_historical_rate_support(
        support_score=support_score,
        evaluable_count=evaluable_count,
        next_close_positive_rate=next_close_positive_rate,
        next_high_hit_rate=next_high_hit_rate,
    )
    sparse_weak_history = _is_sparse_weak_history(
        evaluable_count=evaluable_count,
        next_close_positive_rate=next_close_positive_rate,
        next_high_hit_rate=next_high_hit_rate,
    )
    if sparse_weak_history:
        support_score = min(support_score, -0.01)
    suppress_release = _should_suppress_shadow_release(
        applied_scope=applied_scope,
        execution_quality_label=execution_quality_label,
        evaluable_count=evaluable_count,
        next_close_positive_rate=next_close_positive_rate,
        pruned_from_opportunity_pool=pruned_from_opportunity_pool,
        prune_reason=prune_reason,
    )
    return {
        "support_score": round(support_score, 4),
        "verdict": _support_verdict(suppress_release=suppress_release, support_score=support_score),
        "suppress_release": suppress_release,
        "sparse_weak_history": sparse_weak_history,
    }


def resolve_catalyst_relief_thresholds(
    *,
    candidate_pool_lane: str,
    profitability_hard_cliff: bool,
    historical_next_close_positive_rate: float | None,
    candidate_score_min: float,
    trend_acceleration_min: float,
    close_strength_min: float,
    near_miss_threshold: float,
    post_gate_history_next_close_min: float,
    post_gate_hard_cliff_candidate_score_min: float,
    post_gate_hard_cliff_trend_min: float,
    post_gate_hard_cliff_close_min: float,
    post_gate_hard_cliff_near_miss_threshold: float,
) -> dict[str, float] | None:
    if candidate_pool_lane == "post_gate_liquidity_competition" and profitability_hard_cliff:
        if historical_next_close_positive_rate is not None and historical_next_close_positive_rate < post_gate_history_next_close_min:
            return None
        candidate_score_min = min(candidate_score_min, post_gate_hard_cliff_candidate_score_min)
        trend_acceleration_min = min(trend_acceleration_min, post_gate_hard_cliff_trend_min)
        close_strength_min = min(close_strength_min, post_gate_hard_cliff_close_min)
        near_miss_threshold = min(near_miss_threshold, post_gate_hard_cliff_near_miss_threshold)

    if candidate_pool_lane == "post_gate_liquidity_competition" and historical_next_close_positive_rate is not None and historical_next_close_positive_rate < post_gate_history_next_close_min:
        return None

    return {
        "candidate_score_min": candidate_score_min,
        "trend_acceleration_min": trend_acceleration_min,
        "close_strength_min": close_strength_min,
        "near_miss_threshold": near_miss_threshold,
    }


def resolve_selected_threshold(
    *,
    candidate_pool_lane: str,
    profitability_hard_cliff: bool,
    shadow_visibility_gap_selected: bool,
    post_gate_selected_threshold: float,
    post_gate_hard_cliff_selected_threshold: float,
) -> tuple[bool, float]:
    selected_threshold_override_enabled = candidate_pool_lane == "post_gate_liquidity_competition" or (
        candidate_pool_lane == "layer_a_liquidity_corridor" and shadow_visibility_gap_selected
    )
    selected_threshold = post_gate_selected_threshold
    if candidate_pool_lane == "post_gate_liquidity_competition" and profitability_hard_cliff:
        selected_threshold = min(selected_threshold, post_gate_hard_cliff_selected_threshold)
    return selected_threshold_override_enabled, selected_threshold


def build_upstream_shadow_catalyst_relief_payload(
    *,
    near_miss_threshold: float,
    selected_threshold_override_enabled: bool,
    selected_threshold: float,
    breakout_freshness_min: float,
    trend_acceleration_min: float,
    close_strength_min: float,
    require_no_profitability_hard_cliff: bool,
    required_execution_quality_labels: set[str],
    min_historical_evaluable_count: int,
    min_historical_next_close_positive_rate: float,
    min_historical_next_open_to_close_return_mean: float,
    catalyst_freshness_floor: float,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "reason": "upstream_shadow_catalyst_relief",
        "catalyst_freshness_floor": round(catalyst_freshness_floor, 4),
        "near_miss_threshold": round(near_miss_threshold, 4),
        **({"selected_threshold": round(selected_threshold, 4)} if selected_threshold_override_enabled else {}),
        "breakout_freshness_min": round(breakout_freshness_min, 4),
        "trend_acceleration_min": round(trend_acceleration_min, 4),
        "close_strength_min": round(close_strength_min, 4),
        "require_no_profitability_hard_cliff": require_no_profitability_hard_cliff,
        "required_execution_quality_labels": sorted(required_execution_quality_labels),
        "min_historical_evaluable_count": int(min_historical_evaluable_count),
        "min_historical_next_close_positive_rate": round(min_historical_next_close_positive_rate, 4),
        "min_historical_next_open_to_close_return_mean": round(min_historical_next_open_to_close_return_mean, 4),
    }
