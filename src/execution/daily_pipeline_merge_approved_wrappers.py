"""Merge-approved uplift and watchlist wrapper functions for daily pipeline.

These thin wrappers bind the generic batch-uplift functions from
daily_pipeline_hotspot_helpers / merge_approved_breakout_uplift to concrete
callbacks and module-level settings, so the main pipeline module stays clean.
"""

from __future__ import annotations

from typing import Any

from src.execution.daily_pipeline_hotspot_helpers import (
    apply_merge_approved_breakout_signal_uplift_batch,
    apply_merge_approved_fused_boost,
    apply_merge_approved_layer_c_alignment_uplift_batch,
    apply_merge_approved_sector_resonance_uplift_batch,
    select_upstream_shadow_release_entries,
)
from src.execution.daily_pipeline_candidate_helpers import rank_scored_entries
from src.execution.daily_pipeline_watchlist_helpers import (
    build_merge_approved_watchlist,
    build_watchlist_filter_diagnostics,
    tag_merge_approved_layer_c_results,
)
from src.execution.daily_pipeline_settings import (
    UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS,
    UPSTREAM_SHADOW_RELEASE_MAX_TICKERS,
    UPSTREAM_SHADOW_RELEASE_PRIORITY_TICKERS_BY_LANE,
    WATCHLIST_DIAGNOSTICS_CONFIG,
    WATCHLIST_SCORE_THRESHOLD,
)
from src.execution.merge_approved_breakout_uplift import (
    apply_merge_approved_breakout_uplift_to_signal_map,
    apply_merge_approved_layer_c_alignment_uplift,
    apply_merge_approved_sector_resonance_uplift,
)
from src.execution.models import LayerCResult


def _merge_approved_arbitration_applied(item: Any, label: str) -> list[str]:
    updated = list(getattr(item, "arbitration_applied", None) or [])
    if label not in updated:
        updated.append(label)
    return updated


def _apply_merge_approved_fused_boost(
    fused: list[Any],
    merge_approved_tickers: set[str],
    score_boost: float,
) -> list[Any]:
    return apply_merge_approved_fused_boost(
        fused=fused,
        merge_approved_tickers=merge_approved_tickers,
        score_boost=score_boost,
        merge_approved_arbitration_applied_fn=_merge_approved_arbitration_applied,
    )


def _apply_merge_approved_breakout_signal_uplift(
    fused: list[Any],
    merge_approved_tickers: set[str],
) -> tuple[list[Any], dict[str, Any]]:
    return apply_merge_approved_breakout_signal_uplift_batch(
        fused=fused,
        merge_approved_tickers=merge_approved_tickers,
        apply_uplift_fn=apply_merge_approved_breakout_uplift_to_signal_map,
        merge_approved_arbitration_applied_fn=_merge_approved_arbitration_applied,
        build_result_fn=lambda **kw: dict(by_ticker=kw.get("by_ticker", {}), eligible_tickers=kw.get("eligible_tickers", []), applied_tickers=kw.get("applied_tickers", [])),
    )


def _breakout_diagnostics_for_ticker(
    breakout_signal_uplift: dict[str, Any],
    ticker: str,
) -> dict[str, Any]:
    return dict((breakout_signal_uplift or {}).get(ticker) or {})


def _build_batch_uplift_summary(**kw) -> dict[str, Any]:
    return dict(by_ticker=kw.get("by_ticker", {}), eligible_tickers=kw.get("eligible_tickers", []), applied_tickers=kw.get("applied_tickers", []))


def _apply_merge_approved_layer_c_alignment_uplift(
    layer_c_results: list[Any],
    merge_approved_tickers: set[str],
    breakout_signal_uplift: dict[str, Any],
) -> tuple[list[Any], dict[str, Any]]:
    return apply_merge_approved_layer_c_alignment_uplift_batch(
        layer_c_results=layer_c_results,
        merge_approved_tickers=merge_approved_tickers,
        breakout_signal_uplift=breakout_signal_uplift,
        apply_uplift_fn=apply_merge_approved_layer_c_alignment_uplift,
        breakout_diagnostics_for_ticker_fn=_breakout_diagnostics_for_ticker,
        build_result_fn=_build_batch_uplift_summary,
    )


def _alignment_diagnostics_for_ticker(
    alignment_uplift: dict[str, Any],
    ticker: str,
) -> dict[str, Any]:
    return dict((alignment_uplift or {}).get(ticker) or {})


def _apply_merge_approved_sector_resonance_uplift(
    layer_c_results: list[Any],
    merge_approved_tickers: set[str],
    alignment_uplift: dict[str, Any],
) -> tuple[list[Any], dict[str, Any]]:
    return apply_merge_approved_sector_resonance_uplift_batch(
        layer_c_results=layer_c_results,
        merge_approved_tickers=merge_approved_tickers,
        layer_c_alignment_uplift=alignment_uplift,
        apply_uplift_fn=apply_merge_approved_sector_resonance_uplift,
        alignment_diagnostics_for_ticker_fn=_alignment_diagnostics_for_ticker,
        build_result_fn=_build_batch_uplift_summary,
    )


def _tag_merge_approved_layer_c_results(
    layer_c_results: list[LayerCResult],
    merge_approved_tickers: set[str],
) -> list[LayerCResult]:
    return tag_merge_approved_layer_c_results(
        layer_c_results,
        merge_approved_tickers,
    )


def _classify_watchlist_entry_default(item: LayerCResult) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if item.decision == "avoid":
        reasons.append("decision_avoid")
    if item.score_final < WATCHLIST_SCORE_THRESHOLD:
        reasons.append("score_final_below_watchlist_threshold")
    if item.bc_conflict:
        reasons.append("bc_conflict")
    primary = reasons[0] if reasons else "retained"
    return primary, reasons


def _build_merge_approved_watchlist(
    layer_c_results: list[LayerCResult],
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
) -> list[LayerCResult]:
    return build_merge_approved_watchlist(
        layer_c_results,
        merge_approved_tickers,
        threshold_relaxation,
        watchlist_score_threshold=WATCHLIST_SCORE_THRESHOLD,
    )


def _build_layer_b_filter_diagnostics(
    fused: list[Any],
    high_pool: list[Any],
    build_filter_summary_fn: Any,
) -> dict[str, Any]:
    high_tickers = {item.ticker for item in high_pool}
    return build_filter_summary_fn(
        [{"ticker": item.ticker, "score_b": float(item.score_b), "decision": item.decision} for item in fused if item.ticker not in high_tickers]
    )


def _build_watchlist_filter_diagnostics(
    layer_c_results: list[LayerCResult],
    watchlist: list[LayerCResult],
    *,
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
    build_filter_summary_fn: Any,
) -> dict[str, Any]:
    return build_watchlist_filter_diagnostics(
        layer_c_results,
        watchlist,
        merge_approved_tickers=merge_approved_tickers,
        threshold_relaxation=threshold_relaxation,
        config=WATCHLIST_DIAGNOSTICS_CONFIG,
        classify_watchlist_filter=_classify_watchlist_entry_default,
        build_filter_summary=build_filter_summary_fn,
    )


def _select_upstream_shadow_release_entries(
    ranked_released_shadow_entries: list[tuple[float, float, float, dict[str, Any]]],
    max_tickers: int,
    lane_max_tickers: dict[str, int],
    priority_tickers_by_lane: dict[str, list[str]],
) -> list[dict[str, Any]]:
    def _lane_limit(lane: str) -> int:
        return int(lane_max_tickers.get(lane, max_tickers))

    def _priority_rank(lane: str, ticker: str) -> int | None:
        tickers = list(priority_tickers_by_lane.get(lane, []))
        try:
            return tickers.index(ticker)
        except ValueError:
            return None

    return select_upstream_shadow_release_entries(
        ranked_released_shadow_entries=ranked_released_shadow_entries,
        resolve_priority_rank_fn=_priority_rank,
        resolve_lane_limit_fn=_lane_limit,
        max_tickers=max_tickers,
        rank_scored_entries_fn=rank_scored_entries,
    )
