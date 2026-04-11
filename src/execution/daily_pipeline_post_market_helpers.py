"""Post-market orchestration helpers for the daily pipeline."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.execution.models import LayerCResult
from src.screening.models import CandidateStock
from src.targets.candidate_entry_filters import (
    apply_candidate_entry_filters,
    build_default_btst_candidate_entry_filter_rules,
    summarize_candidate_entry_filter_observability,
)
from src.targets.models import DualTargetEvaluation


@dataclass(frozen=True)
class PostMarketCandidateContext:
    candidates: list[CandidateStock]
    shadow_candidates: list[CandidateStock]
    candidate_pool_shadow_summary: dict[str, Any]
    market_state: Any
    fused: list[Any]
    shadow_fused: list[Any]
    high_pool: list[Any]
    top_precise_pool: list[Any]
    layer_c_results: list[LayerCResult]
    logic_scores: dict[str, float]
    merge_approved_breakout_signal_uplift: dict[str, Any]
    merge_approved_layer_c_alignment_uplift: dict[str, Any]
    merge_approved_sector_resonance_uplift: dict[str, Any]


@dataclass(frozen=True)
class PostMarketWatchlistContext:
    watchlist: list[LayerCResult]
    layer_b_filter_diagnostics: dict[str, Any]
    watchlist_filter_diagnostics: dict[str, Any]
    historical_prior_by_ticker: dict[str, dict[str, Any]]
    short_trade_candidate_diagnostics: dict[str, Any]
    catalyst_theme_candidate_diagnostics: dict[str, Any]
    candidate_by_ticker: dict[str, CandidateStock]
    price_map: dict[str, float]


@dataclass(frozen=True)
class PostMarketOrderContext:
    prebuy_selection_targets: dict[str, DualTargetEvaluation]
    buy_orders: list[Any]
    buy_order_filter_diagnostics: dict[str, Any]
    sell_orders: list[Any]
    sell_order_diagnostics: dict[str, Any]


@dataclass(frozen=True)
class PostMarketSelectionTargetInputs:
    rejected_entries: list[dict[str, Any]]
    supplemental_short_trade_entries: list[dict[str, Any]]
    candidate_entry_filter_diagnostics: dict[str, Any]


def build_high_pool(
    fused: list[Any],
    *,
    score_threshold: float,
    max_tickers: int,
) -> list[Any]:
    return sorted(
        [item for item in fused if item.score_b >= score_threshold],
        key=lambda item: item.score_b,
        reverse=True,
    )[:max_tickers]


def merge_agent_results(
    agent_results: dict[str, dict[str, dict]],
    precise_results: dict[str, dict[str, dict]],
) -> dict[str, dict[str, dict]]:
    merged_results = {agent_id: dict(ticker_payload) for agent_id, ticker_payload in agent_results.items()}
    for agent_id, ticker_payload in precise_results.items():
        merged_results.setdefault(agent_id, {}).update(ticker_payload)
    return merged_results


def build_post_market_counts(
    *,
    candidate_context: PostMarketCandidateContext,
    watchlist_context: PostMarketWatchlistContext,
    order_context: PostMarketOrderContext,
    precise_stage_skipped: bool,
    skipped_precise_ticker_count: int,
    fast_agent_score_threshold: float,
    fast_agent_max_tickers: int,
    precise_agent_max_tickers: int,
    watchlist_score_threshold: float,
) -> dict[str, Any]:
    return {
        "layer_a_count": len(candidate_context.candidates),
        "layer_b_count": len(candidate_context.high_pool),
        "layer_c_count": len(candidate_context.layer_c_results),
        "watchlist_count": len(watchlist_context.watchlist),
        "buy_order_count": len(order_context.buy_orders),
        "sell_order_count": len(order_context.sell_orders),
        "catalyst_theme_candidate_count": int((watchlist_context.catalyst_theme_candidate_diagnostics or {}).get("candidate_count") or 0),
        "catalyst_theme_shadow_candidate_count": int((watchlist_context.catalyst_theme_candidate_diagnostics or {}).get("shadow_candidate_count") or 0),
        "candidate_pool_shadow_candidate_count": len(candidate_context.shadow_candidates),
        "upstream_shadow_observation_count": int((watchlist_context.short_trade_candidate_diagnostics or {}).get("shadow_observation_count") or 0),
        "upstream_shadow_released_count": int((watchlist_context.short_trade_candidate_diagnostics or {}).get("released_shadow_count") or 0),
        "watchlist_shadow_released_count": int((watchlist_context.watchlist_filter_diagnostics or {}).get("released_shadow_count") or 0),
        "fast_agent_ticker_count": len(candidate_context.high_pool),
        "precise_agent_ticker_count": len(candidate_context.top_precise_pool),
        "precise_stage_skipped": precise_stage_skipped,
        "skipped_precise_ticker_count": skipped_precise_ticker_count,
        "fast_agent_score_threshold": fast_agent_score_threshold,
        "fast_agent_max_tickers": fast_agent_max_tickers,
        "precise_agent_max_tickers": precise_agent_max_tickers,
        "watchlist_score_threshold": watchlist_score_threshold,
    }


def build_post_market_funnel_diagnostics(
    *,
    counts: dict[str, Any],
    candidate_context: PostMarketCandidateContext,
    watchlist_context: PostMarketWatchlistContext,
    order_context: PostMarketOrderContext,
    blocked_buy_tickers: dict[str, dict],
) -> dict[str, Any]:
    return {
        "counts": counts,
        "filters": {
            "layer_b": watchlist_context.layer_b_filter_diagnostics,
            "candidate_pool_shadow": candidate_context.candidate_pool_shadow_summary,
            "watchlist": watchlist_context.watchlist_filter_diagnostics,
            "short_trade_candidates": watchlist_context.short_trade_candidate_diagnostics,
            "catalyst_theme_candidates": watchlist_context.catalyst_theme_candidate_diagnostics,
            "buy_orders": order_context.buy_order_filter_diagnostics,
        },
        "sell_orders": order_context.sell_order_diagnostics,
        "blocked_buy_tickers": blocked_buy_tickers,
    }


def build_post_market_timing_seconds(
    *,
    candidate_pool_seconds: float,
    market_state_seconds: float,
    score_batch_seconds: float,
    fuse_batch_seconds: float,
    shadow_score_batch_seconds: float,
    shadow_fuse_batch_seconds: float,
    fast_agent_seconds: float,
    precise_agent_seconds: float,
    estimated_skipped_precise_seconds: float,
    aggregate_layer_c_seconds: float,
    build_buy_orders_seconds: float,
    sell_check_seconds: float,
    total_post_market_seconds: float,
) -> dict[str, float]:
    return {
        "candidate_pool": round(candidate_pool_seconds, 3),
        "market_state": round(market_state_seconds, 3),
        "score_batch": round(score_batch_seconds, 3),
        "fuse_batch": round(fuse_batch_seconds, 3),
        "shadow_score_batch": round(shadow_score_batch_seconds, 3),
        "shadow_fuse_batch": round(shadow_fuse_batch_seconds, 3),
        "fast_agent": round(fast_agent_seconds, 3),
        "precise_agent": round(precise_agent_seconds, 3),
        "estimated_skipped_precise": round(estimated_skipped_precise_seconds, 3),
        "aggregate_layer_c": round(aggregate_layer_c_seconds, 3),
        "build_buy_orders": round(build_buy_orders_seconds, 3),
        "sell_check": round(sell_check_seconds, 3),
        "total_post_market": round(total_post_market_seconds, 3),
    }


def build_selection_target_inputs(
    *,
    trade_date: str,
    watchlist_filter_diagnostics: dict[str, Any],
    short_trade_candidate_diagnostics: dict[str, Any],
    catalyst_theme_candidate_diagnostics: dict[str, Any],
    target_mode: str,
) -> PostMarketSelectionTargetInputs:
    entry_filter_rules = build_default_btst_candidate_entry_filter_rules()
    rejected_entries = list((watchlist_filter_diagnostics or {}).get("tickers", []) or [])
    supplemental_short_trade_entries = [
        *list((short_trade_candidate_diagnostics or {}).get("tickers", []) or []),
        *list((short_trade_candidate_diagnostics or {}).get("released_shadow_entries", []) or []),
        *list((watchlist_filter_diagnostics or {}).get("released_shadow_entries", []) or []),
        *(
            list((catalyst_theme_candidate_diagnostics or {}).get("tickers", []) or [])
            if target_mode == "short_trade_only"
            else []
        ),
    ]
    rejected_filter_observability = summarize_candidate_entry_filter_observability(
        rejected_entries,
        entry_filter_rules,
        trade_date=trade_date,
        default_candidate_source="watchlist_filter_diagnostics",
    )
    supplemental_filter_observability = summarize_candidate_entry_filter_observability(
        supplemental_short_trade_entries,
        entry_filter_rules,
        trade_date=trade_date,
        default_candidate_source="layer_b_boundary",
    )
    filtered_rejected_entries: list[dict[str, Any]]
    filtered_supplemental_entries: list[dict[str, Any]]
    rejected_entries, filtered_rejected_entries = apply_candidate_entry_filters(
        rejected_entries,
        entry_filter_rules,
        trade_date=trade_date,
        default_candidate_source="watchlist_filter_diagnostics",
    )
    supplemental_short_trade_entries, filtered_supplemental_entries = apply_candidate_entry_filters(
        supplemental_short_trade_entries,
        entry_filter_rules,
        trade_date=trade_date,
        default_candidate_source="layer_b_boundary",
    )
    candidate_entry_filter_observability: dict[str, Counter[str]] = {}
    for observability in [rejected_filter_observability, supplemental_filter_observability]:
        for rule_name, counters in observability.items():
            candidate_entry_filter_observability.setdefault(rule_name, Counter()).update(counters)
    filtered_entries = filtered_rejected_entries + filtered_supplemental_entries
    filtered_reason_counts = Counter(str(entry.get("matched_filter") or "unknown") for entry in filtered_entries)
    return PostMarketSelectionTargetInputs(
        rejected_entries=rejected_entries,
        supplemental_short_trade_entries=supplemental_short_trade_entries,
        candidate_entry_filter_diagnostics={
            "rule_names": [str(rule.get("name") or "unnamed_filter") for rule in entry_filter_rules],
            "filtered_count": len(filtered_entries),
            "filtered_tickers": [str(entry.get("ticker") or "") for entry in filtered_entries],
            "filtered_entries": filtered_entries,
            "filtered_rejected_entries": filtered_rejected_entries,
            "filtered_supplemental_entries": filtered_supplemental_entries,
            "filtered_reason_counts": {key: int(value) for key, value in sorted(filtered_reason_counts.items())},
            "candidate_entry_filter_observability": {
                rule_name: {key: int(value) for key, value in counters.items()}
                for rule_name, counters in sorted(candidate_entry_filter_observability.items())
            },
        },
    )
