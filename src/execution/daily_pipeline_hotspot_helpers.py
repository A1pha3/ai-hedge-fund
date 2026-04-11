from __future__ import annotations

from typing import Any, Callable


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


def build_upstream_shadow_catalyst_relief_config(
    *,
    candidate_pool_lane: str,
    filter_reason: str,
    metrics_payload: dict[str, Any],
    historical_prior: dict[str, Any] | None,
    shadow_visibility_gap_selected: bool,
    extract_metric_snapshot_fn: Callable[[dict[str, Any]], dict[str, Any]],
    parse_optional_float_fn: Callable[[Any], float | None],
    build_threshold_inputs_fn: Callable[..., dict[str, Any]],
    passes_relief_gates_fn: Callable[..., bool],
    resolve_require_no_profitability_hard_cliff_fn: Callable[[str], bool],
    resolve_selected_threshold_fn: Callable[..., tuple[bool, float]],
    build_payload_kwargs_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if filter_reason != "catalyst_freshness_below_short_trade_boundary_floor":
        return {}

    metric_snapshot = extract_metric_snapshot_fn(metrics_payload)
    profitability_hard_cliff = bool(metric_snapshot["profitability_hard_cliff"])
    historical_next_close_positive_rate = parse_optional_float_fn(dict(historical_prior or {}).get("next_close_positive_rate"))
    threshold_config = resolve_catalyst_relief_thresholds(
        **build_threshold_inputs_fn(
            candidate_pool_lane=candidate_pool_lane,
            profitability_hard_cliff=profitability_hard_cliff,
            historical_next_close_positive_rate=historical_next_close_positive_rate,
        )
    )
    if threshold_config is None:
        return {}
    if not passes_relief_gates_fn(
        threshold_config=threshold_config,
        historical_prior=historical_prior,
        metric_snapshot=metric_snapshot,
    ):
        return {}

    require_no_profitability_hard_cliff = resolve_require_no_profitability_hard_cliff_fn(candidate_pool_lane)
    selected_threshold_override_enabled, selected_threshold = resolve_selected_threshold_fn(
        candidate_pool_lane=candidate_pool_lane,
        profitability_hard_cliff=profitability_hard_cliff,
        shadow_visibility_gap_selected=shadow_visibility_gap_selected,
    )
    return build_upstream_shadow_catalyst_relief_payload(
        **build_payload_kwargs_fn(
            threshold_config=threshold_config,
            selected_threshold_override_enabled=selected_threshold_override_enabled,
            selected_threshold=selected_threshold,
            require_no_profitability_hard_cliff=require_no_profitability_hard_cliff,
        )
    )


def build_upstream_shadow_release_entry(
    *,
    candidate_entry: dict[str, Any],
    filter_reason: str,
    metrics_payload: dict[str, Any],
    release_reason: str,
    upstream_shadow_release_lane_score_mins: dict[str, float],
    upstream_shadow_release_candidate_score_min: float,
    summarize_shadow_release_historical_support_fn: Callable[[dict[str, Any]], dict[str, Any]],
    build_upstream_shadow_catalyst_relief_config_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    candidate_score = round(float(metrics_payload.get("candidate_score", 0.0) or 0.0), 4)
    candidate_pool_lane = str(candidate_entry.get("candidate_pool_lane") or "")
    lane_score_floor = round(float(upstream_shadow_release_lane_score_mins.get(candidate_pool_lane, upstream_shadow_release_candidate_score_min)), 4)
    historical_prior = dict(candidate_entry.get("historical_prior") or {})
    historical_support = summarize_shadow_release_historical_support_fn(historical_prior)
    catalyst_relief_config = build_upstream_shadow_catalyst_relief_config_fn(
        candidate_pool_lane=candidate_pool_lane,
        filter_reason=filter_reason,
        metrics_payload=metrics_payload,
        historical_prior=historical_prior,
        shadow_visibility_gap_selected=bool(candidate_entry.get("shadow_visibility_gap_selected")),
    )
    resolved_reason_codes = [
        str(code)
        for code in list(candidate_entry.get("candidate_reason_codes") or candidate_entry.get("reasons") or [])
        if str(code or "").strip()
    ]
    for code in [filter_reason, release_reason, "upstream_shadow_release_candidate"]:
        if code not in resolved_reason_codes:
            resolved_reason_codes.append(code)
    return {
        **candidate_entry,
        "reasons": resolved_reason_codes,
        "candidate_reason_codes": resolved_reason_codes,
        "short_trade_boundary_metrics": dict(metrics_payload),
        "shadow_release_filter_reason": filter_reason,
        "shadow_release_reason": release_reason,
        "shadow_release_score_floor": lane_score_floor,
        "shadow_release_candidate_score": candidate_score,
        "shadow_release_historical_support": historical_support,
        "promotion_trigger": "受控 upstream shadow release 样本，仅进入 short-trade supplemental replay，默认不直接进入正式买入名单。",
        **({"short_trade_catalyst_relief": catalyst_relief_config} if catalyst_relief_config else {}),
    }


def summarize_upstream_shadow_release_historical_support(
    *,
    historical_prior: dict[str, Any],
    historical_prior_int_fn: Callable[[dict[str, Any], str], int | None],
    historical_prior_float_fn: Callable[[dict[str, Any], str], float | None],
    summarize_shadow_release_historical_support_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    prior = dict(historical_prior or {})
    execution_quality_label = str(prior.get("execution_quality_label") or "").strip()
    applied_scope = str(prior.get("applied_scope") or "").strip()
    evaluable_count = historical_prior_int_fn(prior, "evaluable_count") or 0
    next_close_positive_rate = historical_prior_float_fn(prior, "next_close_positive_rate")
    next_high_hit_rate = historical_prior_float_fn(prior, "next_high_hit_rate_at_threshold")
    pruned_from_opportunity_pool = bool(prior.get("pruned_from_opportunity_pool"))
    prune_reason = str(prior.get("prune_reason") or "").strip()
    support_summary = summarize_shadow_release_historical_support_fn(
        execution_quality_label=execution_quality_label,
        applied_scope=applied_scope,
        evaluable_count=evaluable_count,
        next_close_positive_rate=next_close_positive_rate,
        next_high_hit_rate=next_high_hit_rate,
        pruned_from_opportunity_pool=pruned_from_opportunity_pool,
        prune_reason=prune_reason,
    )
    return {
        "execution_quality_label": execution_quality_label or None,
        "applied_scope": applied_scope or None,
        "evaluable_count": evaluable_count,
        "next_close_positive_rate": round(float(next_close_positive_rate), 4) if next_close_positive_rate is not None else None,
        "next_high_hit_rate_at_threshold": round(float(next_high_hit_rate), 4) if next_high_hit_rate is not None else None,
        "pruned_from_opportunity_pool": pruned_from_opportunity_pool,
        "prune_reason": prune_reason or None,
        **support_summary,
    }


def apply_merge_approved_fused_boost(
    *,
    fused: list[Any],
    merge_approved_tickers: set[str],
    score_boost: float,
    merge_approved_arbitration_applied_fn: Callable[[Any, str], list[str]],
) -> list[Any]:
    boosted: list[Any] = []
    for item in fused:
        if item.ticker not in merge_approved_tickers:
            boosted.append(item)
            continue
        boosted_score_b = min(1.0, float(item.score_b) + score_boost)
        boosted.append(
            item.model_copy(
                update={
                    "score_b": boosted_score_b,
                    "decision": item.classify_decision(boosted_score_b),
                    "arbitration_applied": merge_approved_arbitration_applied_fn(item, "merge_approved_score_boost_applied"),
                }
            )
        )
    return boosted


def select_upstream_shadow_release_entries(
    *,
    ranked_released_shadow_entries: list[tuple[float, float, float, dict[str, Any]]],
    resolve_priority_rank_fn: Callable[[str, str], int | None],
    resolve_lane_limit_fn: Callable[[str], int],
    max_tickers: int,
    rank_scored_entries_fn: Callable[..., list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    def _sort_key(row: tuple[float, float, float, dict[str, Any]]) -> tuple[float, float, float, float, str]:
        entry = row[-1]
        priority_rank = resolve_priority_rank_fn(
            str(entry.get("candidate_pool_lane") or ""),
            str(entry.get("ticker") or ""),
        )
        return (
            1.0 if priority_rank is not None else 0.0,
            float(-(priority_rank or 0)),
            float(row[0]),
            float(row[1]),
            str(entry.get("ticker") or ""),
        )

    ranked_released_shadow_entries.sort(key=_sort_key, reverse=True)
    selected_rows: list[tuple[float, float, float, dict[str, Any]]] = []
    lane_counts: dict[str, int] = {}
    for row in ranked_released_shadow_entries:
        entry = dict(row[-1])
        candidate_pool_lane = str(entry.get("candidate_pool_lane") or "")
        lane_limit = resolve_lane_limit_fn(candidate_pool_lane)
        if lane_limit <= 0:
            continue
        if lane_counts.get(candidate_pool_lane, 0) >= lane_limit:
            continue
        priority_rank = resolve_priority_rank_fn(candidate_pool_lane, str(entry.get("ticker") or ""))
        if priority_rank is not None:
            entry["shadow_release_priority_selected"] = True
            entry["shadow_release_priority_rank"] = int(priority_rank + 1)
        selected_rows.append((row[0], row[1], row[2], entry))
        lane_counts[candidate_pool_lane] = lane_counts.get(candidate_pool_lane, 0) + 1
        if len(selected_rows) >= max_tickers:
            break
    return rank_scored_entries_fn(selected_rows, limit=len(selected_rows))


def apply_merge_approved_layer_c_alignment_uplift_batch(
    *,
    layer_c_results: list[Any],
    merge_approved_tickers: set[str],
    breakout_signal_uplift: dict[str, Any],
    apply_uplift_fn: Callable[..., tuple[dict[str, Any], dict[str, Any]]],
    breakout_diagnostics_for_ticker_fn: Callable[[dict[str, Any], str], dict[str, Any]],
    build_result_fn: Callable[..., dict[str, Any]],
) -> tuple[list[Any], dict[str, Any]]:
    uplifted: list[Any] = []
    by_ticker: dict[str, Any] = {}
    applied_tickers: list[str] = []
    eligible_tickers: list[str] = []
    for item in layer_c_results:
        if item.ticker not in merge_approved_tickers:
            uplifted.append(item)
            continue
        updated_payload, diagnostics = apply_uplift_fn(
            item.model_dump(mode="json"),
            breakout_diagnostics=breakout_diagnostics_for_ticker_fn(breakout_signal_uplift, item.ticker),
        )
        by_ticker[item.ticker] = diagnostics
        if diagnostics.get("eligible"):
            eligible_tickers.append(item.ticker)
        if diagnostics.get("applied"):
            applied_tickers.append(item.ticker)
            uplifted.append(
                item.model_copy(
                    update={
                        "score_c": updated_payload["score_c"],
                        "score_final": updated_payload["score_final"],
                        "decision": updated_payload["decision"],
                        "agent_contribution_summary": updated_payload["agent_contribution_summary"],
                    }
                )
            )
            continue
        uplifted.append(item)
    return uplifted, build_result_fn(
        by_ticker=by_ticker,
        eligible_tickers=eligible_tickers,
        applied_tickers=applied_tickers,
    )


def apply_merge_approved_breakout_signal_uplift_batch(
    *,
    fused: list[Any],
    merge_approved_tickers: set[str],
    apply_uplift_fn: Callable[..., tuple[dict[str, Any], dict[str, Any]]],
    merge_approved_arbitration_applied_fn: Callable[[Any, str], list[str]],
    build_result_fn: Callable[..., dict[str, Any]],
) -> tuple[list[Any], dict[str, Any]]:
    uplifted: list[Any] = []
    by_ticker: dict[str, Any] = {}
    applied_tickers: list[str] = []
    eligible_tickers: list[str] = []
    for item in fused:
        if item.ticker not in merge_approved_tickers:
            uplifted.append(item)
            continue
        updated_signals, diagnostics = apply_uplift_fn(
            item.strategy_signals,
            score_b=float(item.score_b),
        )
        by_ticker[item.ticker] = diagnostics
        if diagnostics.get("eligible"):
            eligible_tickers.append(item.ticker)
        if diagnostics.get("applied"):
            applied_tickers.append(item.ticker)
            uplifted.append(
                item.model_copy(
                    update={
                        "strategy_signals": updated_signals,
                        "arbitration_applied": merge_approved_arbitration_applied_fn(item, "merge_approved_breakout_signal_uplift_applied"),
                    }
                )
            )
            continue
        uplifted.append(item)
    return uplifted, build_result_fn(
        by_ticker=by_ticker,
        eligible_tickers=eligible_tickers,
        applied_tickers=applied_tickers,
    )


def apply_merge_approved_sector_resonance_uplift_batch(
    *,
    layer_c_results: list[Any],
    merge_approved_tickers: set[str],
    layer_c_alignment_uplift: dict[str, Any],
    apply_uplift_fn: Callable[..., tuple[dict[str, Any], dict[str, Any]]],
    alignment_diagnostics_for_ticker_fn: Callable[[dict[str, Any], str], dict[str, Any]],
    build_result_fn: Callable[..., dict[str, Any]],
) -> tuple[list[Any], dict[str, Any]]:
    uplifted: list[Any] = []
    by_ticker: dict[str, Any] = {}
    applied_tickers: list[str] = []
    eligible_tickers: list[str] = []
    for item in layer_c_results:
        if item.ticker not in merge_approved_tickers:
            uplifted.append(item)
            continue
        updated_payload, diagnostics = apply_uplift_fn(
            item.model_dump(mode="json"),
            alignment_diagnostics=alignment_diagnostics_for_ticker_fn(layer_c_alignment_uplift, item.ticker),
        )
        by_ticker[item.ticker] = diagnostics
        if diagnostics.get("eligible"):
            eligible_tickers.append(item.ticker)
        if diagnostics.get("applied"):
            applied_tickers.append(item.ticker)
            uplifted.append(item.model_copy(update={"agent_contribution_summary": updated_payload["agent_contribution_summary"]}))
            continue
        uplifted.append(item)
    return uplifted, build_result_fn(
        by_ticker=by_ticker,
        eligible_tickers=eligible_tickers,
        applied_tickers=applied_tickers,
    )
