from __future__ import annotations

from typing import Any, Callable


def build_upstream_short_trade_candidates(
    *,
    fused: list[Any],
    high_pool: list[Any],
    shadow_fused: list[Any] | None,
) -> list[Any]:
    selected_tickers = {item.ticker for item in high_pool}
    upstream_candidates_by_ticker = {item.ticker: item for item in fused if item.ticker not in selected_tickers}
    for item in list(shadow_fused or []):
        if item.ticker not in selected_tickers:
            upstream_candidates_by_ticker.setdefault(item.ticker, item)
    return sorted(upstream_candidates_by_ticker.values(), key=lambda current: current.score_b, reverse=True)


def collect_short_trade_diagnostic_rankings(
    *,
    upstream_candidates: list[Any],
    trade_date: str,
    shadow_candidate_by_ticker: dict[str, Any],
    historical_prior_by_ticker: dict[str, dict[str, Any]],
    resolve_short_trade_candidate_context_fn: Callable[[Any], tuple[str, str, str, list[str]]],
    build_short_trade_boundary_entry_fn: Callable[..., dict[str, Any]],
    resolve_historical_prior_for_ticker_fn: Callable[..., dict[str, Any]],
    qualifies_short_trade_boundary_candidate_fn: Callable[..., tuple[bool, str, dict[str, Any]]],
    summarize_shadow_release_historical_support_fn: Callable[[dict[str, Any]], dict[str, Any]],
    should_release_upstream_shadow_candidate_fn: Callable[..., tuple[bool, str | None]],
    build_upstream_shadow_release_entry_fn: Callable[..., dict[str, Any]],
    build_upstream_shadow_observation_entry_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    filtered_reason_counts: dict[str, int] = {}
    ranked_candidates: list[tuple[float, float, dict[str, Any]]] = []
    ranked_shadow_observations: list[tuple[float, float, dict[str, Any]]] = []
    ranked_released_shadow_entries: list[tuple[float, float, dict[str, Any]]] = []

    for item in upstream_candidates:
        shadow_candidate = shadow_candidate_by_ticker.get(item.ticker)
        diagnostic = process_short_trade_candidate_diagnostic(
            item=item,
            trade_date=trade_date,
            shadow_candidate=shadow_candidate,
            historical_prior_by_ticker=historical_prior_by_ticker,
            resolve_short_trade_candidate_context_fn=resolve_short_trade_candidate_context_fn,
            build_short_trade_boundary_entry_fn=build_short_trade_boundary_entry_fn,
            resolve_historical_prior_for_ticker_fn=resolve_historical_prior_for_ticker_fn,
            qualifies_short_trade_boundary_candidate_fn=qualifies_short_trade_boundary_candidate_fn,
            summarize_shadow_release_historical_support_fn=summarize_shadow_release_historical_support_fn,
            should_release_upstream_shadow_candidate_fn=should_release_upstream_shadow_candidate_fn,
            build_upstream_shadow_release_entry_fn=build_upstream_shadow_release_entry_fn,
            build_upstream_shadow_observation_entry_fn=build_upstream_shadow_observation_entry_fn,
        )
        accumulate_short_trade_diagnostic_result(
            diagnostic=diagnostic,
            ranked_candidates=ranked_candidates,
            ranked_shadow_observations=ranked_shadow_observations,
            ranked_released_shadow_entries=ranked_released_shadow_entries,
            filtered_reason_counts=filtered_reason_counts,
        )

    return {
        "filtered_reason_counts": filtered_reason_counts,
        "ranked_candidates": ranked_candidates,
        "ranked_shadow_observations": ranked_shadow_observations,
        "ranked_released_shadow_entries": ranked_released_shadow_entries,
    }


def accumulate_short_trade_diagnostic_result(
    *,
    diagnostic: dict[str, Any],
    ranked_candidates: list[tuple[float, float, dict[str, Any]]],
    ranked_shadow_observations: list[tuple[float, float, dict[str, Any]]],
    ranked_released_shadow_entries: list[tuple[float, float, dict[str, Any]]],
    filtered_reason_counts: dict[str, int],
) -> None:
    if diagnostic["qualified"]:
        ranked_candidates.append(diagnostic["candidate_ranked"])
        return

    filter_reason = str(diagnostic["filter_reason"] or "")
    filtered_reason_counts[filter_reason] = filtered_reason_counts.get(filter_reason, 0) + 1
    if diagnostic.get("released_shadow_ranked") is not None:
        ranked_released_shadow_entries.append(diagnostic["released_shadow_ranked"])
    if diagnostic.get("shadow_observation_ranked") is not None:
        ranked_shadow_observations.append(diagnostic["shadow_observation_ranked"])


def build_short_trade_ranked_outputs(
    *,
    ranked_candidates: list[tuple[float, float, dict[str, Any]]],
    ranked_shadow_observations: list[tuple[float, float, dict[str, Any]]],
    ranked_released_shadow_entries: list[tuple[float, float, dict[str, Any]]],
    rank_scored_entries_fn: Callable[..., list[dict[str, Any]]],
    select_upstream_shadow_release_entries_fn: Callable[[list[tuple[float, float, dict[str, Any]]]], list[dict[str, Any]]],
    short_trade_boundary_max_tickers: int,
    upstream_shadow_observation_max_tickers: int,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}
    for entry in rank_scored_entries_fn(ranked_candidates, limit=short_trade_boundary_max_tickers):
        reason = str(entry.get("reason") or "short_trade_candidate_score_ranked")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        entries.append(entry)

    shadow_observation_entries = rank_scored_entries_fn(
        ranked_shadow_observations,
        limit=upstream_shadow_observation_max_tickers,
    )
    released_shadow_entries = select_upstream_shadow_release_entries_fn(ranked_released_shadow_entries)
    return {
        "entries": entries,
        "reason_counts": reason_counts,
        "shadow_observation_entries": shadow_observation_entries,
        "released_shadow_entries": released_shadow_entries,
    }


def process_short_trade_candidate_diagnostic(
    *,
    item,
    trade_date: str,
    shadow_candidate,
    historical_prior_by_ticker: dict[str, dict[str, Any]],
    resolve_short_trade_candidate_context_fn: Callable[[Any], tuple[str, str, str, list[str]]],
    build_short_trade_boundary_entry_fn: Callable[..., dict[str, Any]],
    resolve_historical_prior_for_ticker_fn: Callable[..., dict[str, Any]],
    qualifies_short_trade_boundary_candidate_fn: Callable[..., tuple[bool, str, dict[str, Any]]],
    summarize_shadow_release_historical_support_fn: Callable[[dict[str, Any]], dict[str, Any]],
    should_release_upstream_shadow_candidate_fn: Callable[..., tuple[bool, str | None]],
    build_upstream_shadow_release_entry_fn: Callable[..., dict[str, Any]],
    build_upstream_shadow_observation_entry_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    reason, candidate_source, upstream_candidate_source, candidate_reason_codes = resolve_short_trade_candidate_context_fn(shadow_candidate)
    candidate_entry = build_short_trade_boundary_entry_fn(
        item=item,
        **_build_short_trade_boundary_entry_kwargs(
            shadow_candidate=shadow_candidate,
            reason=reason,
            candidate_source=candidate_source,
            upstream_candidate_source=upstream_candidate_source,
            candidate_reason_codes=candidate_reason_codes,
        ),
    )
    historical_prior = resolve_historical_prior_for_ticker_fn(
        ticker=str(item.ticker or ""),
        historical_prior=dict(candidate_entry.get("historical_prior") or {}),
        prior_by_ticker=historical_prior_by_ticker,
    )
    if historical_prior:
        candidate_entry["historical_prior"] = historical_prior

    qualified, filter_reason, metrics_payload = qualifies_short_trade_boundary_candidate_fn(
        trade_date=trade_date,
        entry=candidate_entry,
    )
    historical_support = summarize_shadow_release_historical_support_fn(historical_prior)
    candidate_score = float(metrics_payload.get("candidate_score", 0.0) or 0.0)
    base_rank = (
        float(historical_support.get("support_score", 0.0) or 0.0),
        candidate_score,
        float(item.score_b),
    )
    if qualified:
        return _build_qualified_short_trade_candidate_result(
            base_rank=base_rank,
            filter_reason=filter_reason,
            candidate_entry=candidate_entry,
            metrics_payload=metrics_payload,
            historical_prior=historical_prior,
            historical_support=historical_support,
        )

    result: dict[str, Any] = {
        "qualified": False,
        "filter_reason": filter_reason,
        "shadow_observation_ranked": None,
        "released_shadow_ranked": None,
    }
    if shadow_candidate is None:
        return result

    should_release, release_reason = should_release_upstream_shadow_candidate_fn(
        candidate_entry=candidate_entry,
        filter_reason=filter_reason,
        metrics_payload=metrics_payload,
        historical_support=historical_support,
    )
    result["shadow_observation_ranked"] = (
        *base_rank,
        build_upstream_shadow_observation_entry_fn(
            candidate_entry=candidate_entry,
            filter_reason=filter_reason,
            metrics_payload=metrics_payload,
        ),
    )
    if should_release and release_reason is not None:
        result["released_shadow_ranked"] = (
            *base_rank,
            build_upstream_shadow_release_entry_fn(
                candidate_entry=candidate_entry,
                filter_reason=filter_reason,
                metrics_payload=metrics_payload,
                release_reason=release_reason,
            ),
        )
    return result


def _build_short_trade_boundary_entry_kwargs(
    *,
    shadow_candidate: Any,
    reason: str,
    candidate_source: str,
    upstream_candidate_source: str,
    candidate_reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "reason": reason,
        "rank": 0,
        "candidate_source": candidate_source,
        "upstream_candidate_source": upstream_candidate_source,
        "candidate_reason_codes": candidate_reason_codes,
        "candidate_pool_rank": int(shadow_candidate.candidate_pool_rank or 0) if shadow_candidate else None,
        "candidate_pool_lane": str(shadow_candidate.candidate_pool_lane or "") if shadow_candidate else None,
        "candidate_pool_shadow_reason": str(shadow_candidate.candidate_pool_shadow_reason or "") if shadow_candidate else None,
        "candidate_pool_avg_amount_share_of_cutoff": round(float(shadow_candidate.candidate_pool_avg_amount_share_of_cutoff), 4) if shadow_candidate else None,
        "candidate_pool_avg_amount_share_of_min_gate": round(float(shadow_candidate.candidate_pool_avg_amount_share_of_min_gate), 4) if shadow_candidate else None,
        "shadow_visibility_gap_selected": bool(shadow_candidate.shadow_visibility_gap_selected) if shadow_candidate else False,
        "shadow_visibility_gap_relaxed_band": bool(shadow_candidate.shadow_visibility_gap_relaxed_band) if shadow_candidate else False,
    }


def _build_qualified_short_trade_candidate_result(
    *,
    base_rank: tuple[float, float, float],
    filter_reason: str,
    candidate_entry: dict[str, Any],
    metrics_payload: dict[str, Any],
    historical_prior: dict[str, Any],
    historical_support: dict[str, Any],
) -> dict[str, Any]:
    ranked_candidate_entry = {
        **candidate_entry,
        "short_trade_boundary_metrics": metrics_payload,
        **({"shadow_release_historical_support": historical_support} if historical_prior else {}),
    }
    return {
        "qualified": True,
        "filter_reason": filter_reason,
        "candidate_ranked": (*base_rank, ranked_candidate_entry),
    }


def build_short_trade_candidate_diagnostics_payload(
    *,
    upstream_candidates: list[Any],
    entries: list[dict[str, Any]],
    shadow_observation_entries: list[dict[str, Any]],
    released_shadow_entries: list[dict[str, Any]],
    reason_counts: dict[str, int],
    filtered_reason_counts: dict[str, int],
    prefilter_thresholds: dict[str, Any],
    score_buffer: float,
    minimum_score_b: float,
    max_candidates: int,
) -> dict[str, Any]:
    return {
        "upstream_candidate_count": len(upstream_candidates),
        "candidate_count": len(entries),
        "shadow_observation_count": len(shadow_observation_entries),
        "released_shadow_count": len(released_shadow_entries),
        "reason_counts": reason_counts,
        "filtered_reason_counts": filtered_reason_counts,
        "prefilter_thresholds": prefilter_thresholds,
        "selected_tickers": [entry["ticker"] for entry in entries],
        "shadow_observation_tickers": [entry["ticker"] for entry in shadow_observation_entries],
        "released_shadow_tickers": [entry["ticker"] for entry in released_shadow_entries],
        "score_buffer": round(score_buffer, 4),
        "minimum_score_b": round(minimum_score_b, 4),
        "max_candidates": max_candidates,
        "tickers": entries,
        "shadow_observation_entries": shadow_observation_entries,
        "released_shadow_entries": released_shadow_entries,
    }


def prepare_short_trade_candidate_diagnostics_state(
    *,
    fused: list[Any],
    high_pool: list[Any],
    shadow_fused: list[Any] | None,
    trade_date: str,
    shadow_candidate_by_ticker: dict[str, Any],
    historical_prior_by_ticker: dict[str, dict[str, Any]],
    collect_short_trade_diagnostic_rankings_fn: Callable[..., dict[str, Any]],
    resolve_short_trade_candidate_context_fn: Callable[[Any], tuple[str, str, str, list[str]]],
    build_short_trade_boundary_entry_fn: Callable[..., dict[str, Any]],
    resolve_historical_prior_for_ticker_fn: Callable[..., dict[str, Any]],
    qualifies_short_trade_boundary_candidate_fn: Callable[..., tuple[bool, str, dict[str, Any]]],
    summarize_shadow_release_historical_support_fn: Callable[[dict[str, Any]], dict[str, Any]],
    should_release_upstream_shadow_candidate_fn: Callable[..., tuple[bool, str | None]],
    build_upstream_shadow_release_entry_fn: Callable[..., dict[str, Any]],
    build_upstream_shadow_observation_entry_fn: Callable[..., dict[str, Any]],
    build_short_trade_ranked_outputs_fn: Callable[..., dict[str, Any]],
    rank_scored_entries_fn: Callable[..., list[dict[str, Any]]],
    select_upstream_shadow_release_entries_fn: Callable[[list[tuple[float, float, dict[str, Any]]]], list[dict[str, Any]]],
    short_trade_boundary_max_tickers: int,
    upstream_shadow_observation_max_tickers: int,
) -> tuple[list[Any], dict[str, Any], dict[str, Any]]:
    upstream_candidates = build_upstream_short_trade_candidates(
        fused=fused,
        high_pool=high_pool,
        shadow_fused=shadow_fused,
    )
    ranking_state = collect_short_trade_diagnostic_rankings_fn(
        upstream_candidates=upstream_candidates,
        trade_date=trade_date,
        shadow_candidate_by_ticker=shadow_candidate_by_ticker,
        historical_prior_by_ticker=historical_prior_by_ticker,
        resolve_short_trade_candidate_context_fn=resolve_short_trade_candidate_context_fn,
        build_short_trade_boundary_entry_fn=build_short_trade_boundary_entry_fn,
        resolve_historical_prior_for_ticker_fn=resolve_historical_prior_for_ticker_fn,
        qualifies_short_trade_boundary_candidate_fn=qualifies_short_trade_boundary_candidate_fn,
        summarize_shadow_release_historical_support_fn=summarize_shadow_release_historical_support_fn,
        should_release_upstream_shadow_candidate_fn=should_release_upstream_shadow_candidate_fn,
        build_upstream_shadow_release_entry_fn=build_upstream_shadow_release_entry_fn,
        build_upstream_shadow_observation_entry_fn=build_upstream_shadow_observation_entry_fn,
    )
    ranked_outputs = build_short_trade_ranked_outputs_fn(
        ranked_candidates=ranking_state["ranked_candidates"],
        ranked_shadow_observations=ranking_state["ranked_shadow_observations"],
        ranked_released_shadow_entries=ranking_state["ranked_released_shadow_entries"],
        rank_scored_entries_fn=rank_scored_entries_fn,
        select_upstream_shadow_release_entries_fn=select_upstream_shadow_release_entries_fn,
        short_trade_boundary_max_tickers=short_trade_boundary_max_tickers,
        upstream_shadow_observation_max_tickers=upstream_shadow_observation_max_tickers,
    )
    return upstream_candidates, ranking_state, ranked_outputs


def finalize_short_trade_candidate_diagnostics(
    *,
    upstream_candidates: list[Any],
    ranking_state: dict[str, Any],
    ranked_outputs: dict[str, Any],
    build_short_trade_candidate_diagnostics_payload_fn: Callable[..., dict[str, Any]],
    build_short_trade_prefilter_thresholds_fn: Callable[..., dict[str, Any]],
    resolve_no_profitability_hard_cliff_fn: Callable[[str], bool],
    short_trade_boundary_candidate_score_min: float,
    short_trade_boundary_breakout_min: float,
    short_trade_boundary_trend_min: float,
    short_trade_boundary_volume_min: float,
    short_trade_boundary_catalyst_min: float,
    upstream_shadow_release_candidate_score_min: float,
    upstream_shadow_catalyst_relief_candidate_score_min: float,
    upstream_shadow_catalyst_relief_breakout_min: float,
    upstream_shadow_catalyst_relief_trend_min: float,
    upstream_shadow_catalyst_relief_close_min: float,
    upstream_shadow_catalyst_relief_catalyst_freshness_floor: float,
    upstream_shadow_catalyst_relief_near_miss_threshold: float,
    upstream_shadow_catalyst_relief_post_gate_selected_threshold: float,
    upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff_default: bool,
    upstream_shadow_release_lanes: list[str],
    upstream_shadow_release_lane_score_mins: dict[str, float],
    upstream_shadow_release_lane_max_tickers: dict[str, int],
    upstream_shadow_release_priority_tickers_by_lane: dict[str, list[str] | tuple[str, ...]],
    score_buffer: float,
    minimum_score_b: float,
    max_candidates: int,
) -> dict[str, Any]:
    return build_short_trade_candidate_diagnostics_payload_fn(
        upstream_candidates=upstream_candidates,
        entries=ranked_outputs["entries"],
        shadow_observation_entries=ranked_outputs["shadow_observation_entries"],
        released_shadow_entries=ranked_outputs["released_shadow_entries"],
        reason_counts=ranked_outputs["reason_counts"],
        filtered_reason_counts=ranking_state["filtered_reason_counts"],
        prefilter_thresholds=build_short_trade_prefilter_thresholds_fn(
            short_trade_boundary_candidate_score_min=short_trade_boundary_candidate_score_min,
            short_trade_boundary_breakout_min=short_trade_boundary_breakout_min,
            short_trade_boundary_trend_min=short_trade_boundary_trend_min,
            short_trade_boundary_volume_min=short_trade_boundary_volume_min,
            short_trade_boundary_catalyst_min=short_trade_boundary_catalyst_min,
            upstream_shadow_release_candidate_score_min=upstream_shadow_release_candidate_score_min,
            upstream_shadow_catalyst_relief_candidate_score_min=upstream_shadow_catalyst_relief_candidate_score_min,
            upstream_shadow_catalyst_relief_breakout_min=upstream_shadow_catalyst_relief_breakout_min,
            upstream_shadow_catalyst_relief_trend_min=upstream_shadow_catalyst_relief_trend_min,
            upstream_shadow_catalyst_relief_close_min=upstream_shadow_catalyst_relief_close_min,
            upstream_shadow_catalyst_relief_catalyst_freshness_floor=upstream_shadow_catalyst_relief_catalyst_freshness_floor,
            upstream_shadow_catalyst_relief_near_miss_threshold=upstream_shadow_catalyst_relief_near_miss_threshold,
            upstream_shadow_catalyst_relief_post_gate_selected_threshold=upstream_shadow_catalyst_relief_post_gate_selected_threshold,
            upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff_default=upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff_default,
            upstream_shadow_release_lanes=upstream_shadow_release_lanes,
            resolve_no_profitability_hard_cliff_fn=resolve_no_profitability_hard_cliff_fn,
            upstream_shadow_release_lane_score_mins=upstream_shadow_release_lane_score_mins,
            upstream_shadow_release_lane_max_tickers=upstream_shadow_release_lane_max_tickers,
            upstream_shadow_release_priority_tickers_by_lane=upstream_shadow_release_priority_tickers_by_lane,
        ),
        score_buffer=score_buffer,
        minimum_score_b=minimum_score_b,
        max_candidates=max_candidates,
    )


def build_short_trade_candidate_diagnostics(
    *,
    fused: list[Any],
    high_pool: list[Any],
    trade_date: str,
    shadow_fused: list[Any] | None,
    shadow_candidate_by_ticker: dict[str, Any],
    historical_prior_by_ticker: dict[str, dict[str, Any]],
    prepare_short_trade_candidate_diagnostics_state_fn: Callable[..., tuple[list[Any], dict[str, Any], dict[str, Any]]],
    finalize_short_trade_candidate_diagnostics_fn: Callable[..., dict[str, Any]],
    collect_short_trade_diagnostic_rankings_fn: Callable[..., dict[str, Any]],
    resolve_short_trade_candidate_context_fn: Callable[[Any], tuple[str, str, str, list[str]]],
    build_short_trade_boundary_entry_fn: Callable[..., dict[str, Any]],
    resolve_historical_prior_for_ticker_fn: Callable[..., dict[str, Any]],
    qualifies_short_trade_boundary_candidate_fn: Callable[..., tuple[bool, str, dict[str, Any]]],
    summarize_shadow_release_historical_support_fn: Callable[[dict[str, Any]], dict[str, Any]],
    should_release_upstream_shadow_candidate_fn: Callable[..., tuple[bool, str | None]],
    build_upstream_shadow_release_entry_fn: Callable[..., dict[str, Any]],
    build_upstream_shadow_observation_entry_fn: Callable[..., dict[str, Any]],
    build_short_trade_ranked_outputs_fn: Callable[..., dict[str, Any]],
    rank_scored_entries_fn: Callable[..., list[dict[str, Any]]],
    select_upstream_shadow_release_entries_fn: Callable[[list[tuple[float, float, dict[str, Any]]]], list[dict[str, Any]]],
    build_short_trade_candidate_diagnostics_payload_fn: Callable[..., dict[str, Any]],
    build_short_trade_prefilter_thresholds_fn: Callable[..., dict[str, Any]],
    resolve_no_profitability_hard_cliff_fn: Callable[[str], bool],
    short_trade_boundary_candidate_score_min: float,
    short_trade_boundary_breakout_min: float,
    short_trade_boundary_trend_min: float,
    short_trade_boundary_volume_min: float,
    short_trade_boundary_catalyst_min: float,
    upstream_shadow_release_candidate_score_min: float,
    upstream_shadow_catalyst_relief_candidate_score_min: float,
    upstream_shadow_catalyst_relief_breakout_min: float,
    upstream_shadow_catalyst_relief_trend_min: float,
    upstream_shadow_catalyst_relief_close_min: float,
    upstream_shadow_catalyst_relief_catalyst_freshness_floor: float,
    upstream_shadow_catalyst_relief_near_miss_threshold: float,
    upstream_shadow_catalyst_relief_post_gate_selected_threshold: float,
    upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff_default: bool,
    upstream_shadow_release_lanes: list[str],
    upstream_shadow_release_lane_score_mins: dict[str, float],
    upstream_shadow_release_lane_max_tickers: dict[str, int],
    upstream_shadow_release_priority_tickers_by_lane: dict[str, list[str] | tuple[str, ...]],
    short_trade_boundary_max_tickers: int,
    upstream_shadow_observation_max_tickers: int,
    score_buffer: float,
    minimum_score_b: float,
    max_candidates: int,
) -> dict[str, Any]:
    upstream_candidates, ranking_state, ranked_outputs = prepare_short_trade_candidate_diagnostics_state_fn(
        fused=fused,
        high_pool=high_pool,
        shadow_fused=shadow_fused,
        trade_date=trade_date,
        shadow_candidate_by_ticker=shadow_candidate_by_ticker,
        historical_prior_by_ticker=historical_prior_by_ticker,
        collect_short_trade_diagnostic_rankings_fn=collect_short_trade_diagnostic_rankings_fn,
        resolve_short_trade_candidate_context_fn=resolve_short_trade_candidate_context_fn,
        build_short_trade_boundary_entry_fn=build_short_trade_boundary_entry_fn,
        resolve_historical_prior_for_ticker_fn=resolve_historical_prior_for_ticker_fn,
        qualifies_short_trade_boundary_candidate_fn=qualifies_short_trade_boundary_candidate_fn,
        summarize_shadow_release_historical_support_fn=summarize_shadow_release_historical_support_fn,
        should_release_upstream_shadow_candidate_fn=should_release_upstream_shadow_candidate_fn,
        build_upstream_shadow_release_entry_fn=build_upstream_shadow_release_entry_fn,
        build_upstream_shadow_observation_entry_fn=build_upstream_shadow_observation_entry_fn,
        build_short_trade_ranked_outputs_fn=build_short_trade_ranked_outputs_fn,
        rank_scored_entries_fn=rank_scored_entries_fn,
        select_upstream_shadow_release_entries_fn=select_upstream_shadow_release_entries_fn,
        short_trade_boundary_max_tickers=short_trade_boundary_max_tickers,
        upstream_shadow_observation_max_tickers=upstream_shadow_observation_max_tickers,
    )
    return finalize_short_trade_candidate_diagnostics_fn(
        upstream_candidates=upstream_candidates,
        ranking_state=ranking_state,
        ranked_outputs=ranked_outputs,
        build_short_trade_candidate_diagnostics_payload_fn=build_short_trade_candidate_diagnostics_payload_fn,
        build_short_trade_prefilter_thresholds_fn=build_short_trade_prefilter_thresholds_fn,
        resolve_no_profitability_hard_cliff_fn=resolve_no_profitability_hard_cliff_fn,
        short_trade_boundary_candidate_score_min=short_trade_boundary_candidate_score_min,
        short_trade_boundary_breakout_min=short_trade_boundary_breakout_min,
        short_trade_boundary_trend_min=short_trade_boundary_trend_min,
        short_trade_boundary_volume_min=short_trade_boundary_volume_min,
        short_trade_boundary_catalyst_min=short_trade_boundary_catalyst_min,
        upstream_shadow_release_candidate_score_min=upstream_shadow_release_candidate_score_min,
        upstream_shadow_catalyst_relief_candidate_score_min=upstream_shadow_catalyst_relief_candidate_score_min,
        upstream_shadow_catalyst_relief_breakout_min=upstream_shadow_catalyst_relief_breakout_min,
        upstream_shadow_catalyst_relief_trend_min=upstream_shadow_catalyst_relief_trend_min,
        upstream_shadow_catalyst_relief_close_min=upstream_shadow_catalyst_relief_close_min,
        upstream_shadow_catalyst_relief_catalyst_freshness_floor=upstream_shadow_catalyst_relief_catalyst_freshness_floor,
        upstream_shadow_catalyst_relief_near_miss_threshold=upstream_shadow_catalyst_relief_near_miss_threshold,
        upstream_shadow_catalyst_relief_post_gate_selected_threshold=upstream_shadow_catalyst_relief_post_gate_selected_threshold,
        upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff_default=upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff_default,
        upstream_shadow_release_lanes=upstream_shadow_release_lanes,
        upstream_shadow_release_lane_score_mins=upstream_shadow_release_lane_score_mins,
        upstream_shadow_release_lane_max_tickers=upstream_shadow_release_lane_max_tickers,
        upstream_shadow_release_priority_tickers_by_lane=upstream_shadow_release_priority_tickers_by_lane,
        score_buffer=score_buffer,
        minimum_score_b=minimum_score_b,
        max_candidates=max_candidates,
    )


def build_short_trade_prefilter_thresholds(
    *,
    short_trade_boundary_candidate_score_min: float,
    short_trade_boundary_breakout_min: float,
    short_trade_boundary_trend_min: float,
    short_trade_boundary_volume_min: float,
    short_trade_boundary_catalyst_min: float,
    upstream_shadow_release_candidate_score_min: float,
    upstream_shadow_catalyst_relief_candidate_score_min: float,
    upstream_shadow_catalyst_relief_breakout_min: float,
    upstream_shadow_catalyst_relief_trend_min: float,
    upstream_shadow_catalyst_relief_close_min: float,
    upstream_shadow_catalyst_relief_catalyst_freshness_floor: float,
    upstream_shadow_catalyst_relief_near_miss_threshold: float,
    upstream_shadow_catalyst_relief_post_gate_selected_threshold: float,
    upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff_default: bool,
    upstream_shadow_release_lanes: list[str],
    resolve_no_profitability_hard_cliff_fn: Callable[[str], bool],
    upstream_shadow_release_lane_score_mins: dict[str, float],
    upstream_shadow_release_lane_max_tickers: dict[str, int],
    upstream_shadow_release_priority_tickers_by_lane: dict[str, list[str] | tuple[str, ...]],
) -> dict[str, Any]:
    return {
        "candidate_score_min": round(short_trade_boundary_candidate_score_min, 4),
        "breakout_freshness_min": round(short_trade_boundary_breakout_min, 4),
        "trend_acceleration_min": round(short_trade_boundary_trend_min, 4),
        "volume_expansion_quality_min": round(short_trade_boundary_volume_min, 4),
        "catalyst_freshness_min": round(short_trade_boundary_catalyst_min, 4),
        "upstream_shadow_release_candidate_score_min": round(upstream_shadow_release_candidate_score_min, 4),
        "upstream_shadow_catalyst_relief_candidate_score_min": round(upstream_shadow_catalyst_relief_candidate_score_min, 4),
        "upstream_shadow_catalyst_relief_breakout_min": round(upstream_shadow_catalyst_relief_breakout_min, 4),
        "upstream_shadow_catalyst_relief_trend_min": round(upstream_shadow_catalyst_relief_trend_min, 4),
        "upstream_shadow_catalyst_relief_close_min": round(upstream_shadow_catalyst_relief_close_min, 4),
        "upstream_shadow_catalyst_relief_catalyst_freshness_floor": round(upstream_shadow_catalyst_relief_catalyst_freshness_floor, 4),
        "upstream_shadow_catalyst_relief_near_miss_threshold": round(upstream_shadow_catalyst_relief_near_miss_threshold, 4),
        "upstream_shadow_catalyst_relief_post_gate_selected_threshold": round(upstream_shadow_catalyst_relief_post_gate_selected_threshold, 4),
        "upstream_shadow_catalyst_relief_visibility_gap_corridor_selected_threshold": round(upstream_shadow_catalyst_relief_post_gate_selected_threshold, 4),
        "upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff": upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff_default,
        "upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff_by_lane": {
            lane: resolve_no_profitability_hard_cliff_fn(lane)
            for lane in sorted(upstream_shadow_release_lanes)
        },
        "upstream_shadow_release_lane_score_mins": {
            lane: round(float(score_min), 4)
            for lane, score_min in upstream_shadow_release_lane_score_mins.items()
        },
        "upstream_shadow_release_lane_max_tickers": {
            lane: int(limit)
            for lane, limit in upstream_shadow_release_lane_max_tickers.items()
        },
        "upstream_shadow_release_priority_tickers_by_lane": {
            lane: list(priority_tickers)
            for lane, priority_tickers in sorted(upstream_shadow_release_priority_tickers_by_lane.items())
            if priority_tickers
        },
    }
