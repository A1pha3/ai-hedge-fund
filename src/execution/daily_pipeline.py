"""日度执行流水线。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from inspect import signature
from time import perf_counter
from typing import Any, Callable, Optional

from scripts.btst_latest_followup_utils import load_latest_btst_historical_prior_by_ticker
from src.execution.daily_pipeline_candidate_helpers import (
    qualify_catalyst_theme_candidate_from_snapshot,
    qualify_short_trade_boundary_candidate_from_snapshot,
    rank_scored_entries,
    resolve_short_trade_candidate_context,
)
from src.execution.daily_pipeline_catalyst_diagnostics_helpers import (
    build_catalyst_theme_candidate_diagnostics as build_catalyst_theme_candidate_diagnostics_impl,
    build_catalyst_theme_shadow_entry as build_catalyst_theme_shadow_entry_impl,
    build_catalyst_theme_candidate_diagnostics_payload,
    build_catalyst_theme_short_trade_carryover_relief_config as build_catalyst_theme_short_trade_carryover_relief_config_impl,
    compute_catalyst_theme_threshold_shortfalls as compute_catalyst_theme_threshold_shortfalls_impl,
    finalize_catalyst_theme_candidate_diagnostics,
    build_catalyst_theme_prefilter_thresholds,
    build_catalyst_theme_ranked_outputs,
    build_upstream_catalyst_theme_candidates,
    collect_catalyst_theme_diagnostic_rankings,
    resolve_catalyst_theme_close_momentum_relief as resolve_catalyst_theme_close_momentum_relief_impl,
)
from src.execution.daily_pipeline_buy_diagnostics_helpers import (
    build_buy_orders_with_diagnostics as build_buy_orders_with_diagnostics_impl,
    build_reentry_filter_payload,
)
from src.execution.daily_pipeline_hotspot_helpers import (
    apply_merge_approved_fused_boost as apply_merge_approved_fused_boost_impl,
    apply_merge_approved_breakout_signal_uplift_batch,
    apply_merge_approved_layer_c_alignment_uplift_batch,
    apply_merge_approved_sector_resonance_uplift_batch,
    summarize_upstream_shadow_release_historical_support as summarize_upstream_shadow_release_historical_support_impl,
    build_upstream_shadow_release_entry as build_upstream_shadow_release_entry_impl,
    build_upstream_shadow_catalyst_relief_config as build_upstream_shadow_catalyst_relief_config_impl,
    resolve_selected_threshold,
    select_upstream_shadow_release_entries as select_upstream_shadow_release_entries_impl,
    summarize_shadow_release_historical_support,
)
from src.execution.daily_pipeline_phase4_entry_helpers import (
    _build_short_trade_boundary_entry,
    _build_upstream_shadow_observation_entry,
)
from src.execution.daily_pipeline_short_trade_diagnostics_helpers import (
    build_short_trade_candidate_diagnostics as build_short_trade_candidate_diagnostics_impl,
    build_short_trade_candidate_diagnostics_payload,
    finalize_short_trade_candidate_diagnostics,
    build_short_trade_prefilter_thresholds,
    build_short_trade_ranked_outputs,
    collect_short_trade_diagnostic_rankings,
    prepare_short_trade_candidate_diagnostics_state,
)
from src.execution.daily_pipeline_post_market_helpers import (
    PostMarketCandidateContext,
    PostMarketDiagnosticsAggregation,
    PostMarketOrderContext,
    PostMarketSelectionResolution,
    PostMarketWatchlistContext,
    aggregate_post_market_diagnostics,
    build_post_market_execution_plan,
    build_sell_order_diagnostics as build_sell_order_diagnostics_impl,
    build_watchlist_price_map as build_watchlist_price_map_impl,
    build_high_pool,
    ensure_plan_target_shells as ensure_plan_target_shells_impl,
    build_selection_target_inputs,
    merge_agent_results,
    resolve_post_market_selection_targets,
)
from src.execution.daily_pipeline_runtime_helpers import (
    build_filter_summary as _build_filter_summary_impl,
    default_exit_checker as _default_exit_checker_impl,
    load_candidate_pool_bundle as _load_candidate_pool_bundle_impl,
    load_latest_historical_prior_by_ticker as _load_latest_historical_prior_by_ticker_impl,
    resolve_historical_prior_for_ticker as _resolve_historical_prior_for_ticker_impl,
)
from src.execution.daily_pipeline_settings import (
    BTST_REPORTS_ROOT,
    CATALYST_THEME_BREAKOUT_MIN,
    CATALYST_THEME_CANDIDATE_SCORE_MIN,
    CATALYST_THEME_CATALYST_MIN,
    CATALYST_THEME_CLOSE_MIN,
    CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_BREAKOUT_MIN,
    CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_CLOSE_MIN,
    CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_SECTOR_MIN,
    CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_TREND_MIN,
    CATALYST_THEME_MAX_TICKERS,
    CATALYST_THEME_SECTOR_MIN,
    CATALYST_THEME_SHADOW_MAX_TICKERS,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_CANDIDATE_SCORE_MIN,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_CATALYST_FRESHNESS_FLOOR,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_MIN_HISTORICAL_EVALUABLE_COUNT,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_NEAR_MISS_THRESHOLD,
    CATALYST_THEME_SHORT_TRADE_CARRYOVER_REQUIRE_NO_PROFITABILITY_HARD_CLIFF,
    CONTINUATION_EXECUTION_ENABLED,
    CONTINUATION_WATCHLIST_EDGE_EXECUTION_RATIO,
    CONTINUATION_WATCHLIST_MIN_SCORE,
    EXIT_REENTRY_CONFIRM_SCORE_MIN,
    EXIT_REENTRY_WEAK_CONFIRMATION_SCORE_MIN,
    FAST_AGENT_MAX_TICKERS,
    FAST_AGENT_SCORE_THRESHOLD,
    MERGE_APPROVED_MERGE_REVIEW_PATH,
    MERGE_APPROVED_RANKING_PATH,
    MERGE_APPROVED_SCORE_BOOST,
    MERGE_APPROVED_TICKERS,
    MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION,
    PRECISE_AGENT_MAX_TICKERS,
    SHORT_TRADE_BOUNDARY_BREAKOUT_MIN,
    SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN,
    SHORT_TRADE_BOUNDARY_CATALYST_MIN,
    SHORT_TRADE_BOUNDARY_MAX_TICKERS,
    SHORT_TRADE_BOUNDARY_SCORE_BUFFER,
    SHORT_TRADE_BOUNDARY_TREND_MIN,
    SHORT_TRADE_BOUNDARY_VOLUME_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_CANDIDATE_SCORE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_CATALYST_FRESHNESS_FLOOR,
    UPSTREAM_SHADOW_CATALYST_RELIEF_CLOSE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_MIN_EVALUABLE_COUNT,
    UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_CLOSE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_OPEN_TO_CLOSE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_REQUIRED_EXECUTION_QUALITY,
    UPSTREAM_SHADOW_CATALYST_RELIEF_NEAR_MISS_THRESHOLD,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CANDIDATE_SCORE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CLOSE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_HISTORY_NEXT_CLOSE_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_NEAR_MISS_THRESHOLD,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_SELECTED_THRESHOLD,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_TREND_MIN,
    UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_SELECTED_THRESHOLD,
    UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_BY_LANE,
    UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_DEFAULT,
    UPSTREAM_SHADOW_CATALYST_RELIEF_TREND_MIN,
    UPSTREAM_SHADOW_OBSERVATION_MAX_TICKERS,
    UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN,
    UPSTREAM_SHADOW_RELEASE_LANES,
    UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS,
    UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS,
    UPSTREAM_SHADOW_RELEASE_MAX_TICKERS,
    UPSTREAM_SHADOW_RELEASE_PRIORITY_TICKERS_BY_LANE,
    WATCHLIST_DIAGNOSTICS_CONFIG,
    WATCHLIST_SCORE_THRESHOLD,
)
from src.execution.daily_pipeline_watchlist_helpers import (
    build_merge_approved_watchlist,
    build_watchlist_filter_diagnostics,
    tag_merge_approved_layer_c_results,
)
from src.execution.crisis_handler import evaluate_crisis_response
from src.execution.layer_c_aggregator import aggregate_layer_c_results
from src.execution.merge_approved_loader import load_merge_approved_tickers
from src.execution.merge_approved_breakout_uplift import (
    apply_merge_approved_breakout_uplift_to_signal_map,
    apply_merge_approved_layer_c_alignment_uplift,
    apply_merge_approved_sector_resonance_uplift,
    summarize_merge_approved_breakout_uplift_config,
)
from src.execution.models import ExecutionPlan, LayerCResult
from src.execution.plan_generator import generate_execution_plan
from src.execution.signal_decay import apply_signal_decay
from src.execution.t1_confirmation import confirm_buy_signal
from src.portfolio.exit_manager import check_exit_signal
from src.portfolio.models import HoldingState
from src.portfolio.position_calculator import calculate_position, enforce_daily_trade_limit
from src.screening.candidate_pool import build_candidate_pool, build_candidate_pool_with_shadow
from src.screening.models import CandidateStock
from src.screening.market_state import detect_market_state
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetMode
from src.targets.profiles import build_short_trade_target_profile, use_short_trade_target_profile
from src.targets.router import build_selection_targets, summarize_selection_targets
from src.targets.short_trade_target import build_short_trade_target_snapshot_from_entry
from src.llm.defaults import get_default_model_config
from src.tools.tushare_api import get_daily_basic_batch


AgentRunner = Callable[[list[str], str, str], dict[str, dict[str, dict]]]
ExitChecker = Callable[..., list]
_ORIGINAL_BUILD_CANDIDATE_POOL = build_candidate_pool
_ORIGINAL_BUILD_CANDIDATE_POOL_WITH_SHADOW = build_candidate_pool_with_shadow
WEAK_CONFIRMATION_REENTRY_NEGATIVE_TAGS = frozenset(
    {
        "watchlist_zero_catalyst_penalty_applied",
        "watchlist_zero_catalyst_crowded_penalty_applied",
        "watchlist_zero_catalyst_flat_trend_penalty_applied",
    }
)
WEAK_CONFIRMATION_REENTRY_GUARD_KEYS = (
    "watchlist_zero_catalyst_guard",
    "watchlist_zero_catalyst_crowded_guard",
    "watchlist_zero_catalyst_flat_trend_guard",
)


def _load_candidate_pool_bundle(trade_date: str) -> tuple[list[CandidateStock], list[CandidateStock], dict[str, Any]]:
    return _load_candidate_pool_bundle_impl(
        trade_date,
        build_candidate_pool=build_candidate_pool,
        build_candidate_pool_with_shadow=build_candidate_pool_with_shadow,
        original_build_candidate_pool=_ORIGINAL_BUILD_CANDIDATE_POOL,
        original_build_candidate_pool_with_shadow=_ORIGINAL_BUILD_CANDIDATE_POOL_WITH_SHADOW,
    )


def _resolve_pipeline_model_config(model_tier: str, base_model_name: str, base_model_provider: str) -> tuple[str, str]:
    """Resolves fast/precise pipeline model settings without silently switching providers."""
    provider_name = str(base_model_provider or "")
    model_name = str(base_model_name or "")

    if not provider_name or not model_name:
        default_model_name, default_model_provider = get_default_model_config()
        provider_name = provider_name or str(default_model_provider)
        model_name = model_name or str(default_model_name)

    if provider_name == "OpenAI" and model_name in {"gpt-4.1", "gpt-4.1-mini"}:
        return ("gpt-4.1-mini" if model_tier == "fast" else "gpt-4.1"), provider_name

    return model_name, provider_name


def _should_skip_precise_stage(base_model_name: str, base_model_provider: str) -> bool:
    """Skips precise reruns when fast/precise tiers resolve to the same config."""
    fast_model_name, fast_provider_name = _resolve_pipeline_model_config("fast", base_model_name, base_model_provider)
    precise_model_name, precise_provider_name = _resolve_pipeline_model_config("precise", base_model_name, base_model_provider)
    return fast_model_name == precise_model_name and fast_provider_name == precise_provider_name


def _estimate_skipped_precise_seconds(fast_agent_seconds: float, fast_ticker_count: int, skipped_precise_ticker_count: int) -> float:
    """Estimates the avoided precise-stage cost when the same model config would have been rerun."""
    if fast_ticker_count <= 0 or skipped_precise_ticker_count <= 0:
        return 0.0
    return fast_agent_seconds * (skipped_precise_ticker_count / fast_ticker_count)


def _build_logic_score_map(layer_c_results: list[LayerCResult]) -> dict[str, float]:
    return {item.ticker: float(item.score_final) for item in layer_c_results}


def _default_exit_checker(portfolio_snapshot: dict, trade_date: str, logic_scores: dict[str, float] | None = None) -> list:
    return _default_exit_checker_impl(
        portfolio_snapshot,
        trade_date,
        logic_scores,
        build_watchlist_price_map=build_watchlist_price_map,
        check_exit_signal=check_exit_signal,
        holding_state_cls=HoldingState,
    )


def _build_filter_summary(entries: list[dict]) -> dict:
    return _build_filter_summary_impl(entries)


def _load_latest_btst_historical_prior_by_ticker() -> dict[str, dict[str, Any]]:
    return _load_latest_historical_prior_by_ticker_impl(
        reports_root=BTST_REPORTS_ROOT,
        loader=load_latest_btst_historical_prior_by_ticker,
    )


def _resolve_historical_prior_for_ticker(*, ticker: str, historical_prior: dict[str, Any] | None, prior_by_ticker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return _resolve_historical_prior_for_ticker_impl(
        ticker=ticker,
        historical_prior=historical_prior,
        prior_by_ticker=prior_by_ticker,
    )


def _refresh_attached_entry_relief(entry: dict[str, Any]) -> dict[str, Any]:
    updated_entry = dict(entry)
    candidate_pool_lane = str(updated_entry.get("candidate_pool_lane") or "")
    historical_prior = dict(updated_entry.get("historical_prior") or {})
    current_relief = dict(updated_entry.get("short_trade_catalyst_relief") or {})
    if candidate_pool_lane != "post_gate_liquidity_competition":
        return updated_entry
    if str(current_relief.get("reason") or "") != "upstream_shadow_catalyst_relief":
        return updated_entry
    next_close_positive_rate = historical_prior.get("next_close_positive_rate")
    if next_close_positive_rate is not None and float(next_close_positive_rate) < 0.5:
        updated_entry.pop("short_trade_catalyst_relief", None)
    return updated_entry


def _attach_historical_prior_to_entries(entries: list[dict[str, Any]], *, prior_by_ticker: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    attached_entries: list[dict[str, Any]] = []
    for entry in entries:
        updated_entry = dict(entry)
        ticker = str(updated_entry.get("ticker") or "")
        historical_prior = _resolve_historical_prior_for_ticker(
            ticker=ticker,
            historical_prior=dict(updated_entry.get("historical_prior") or {}),
            prior_by_ticker=prior_by_ticker,
        )
        if historical_prior:
            updated_entry["historical_prior"] = historical_prior
        updated_entry = _refresh_attached_entry_relief(updated_entry)
        attached_entries.append(updated_entry)
    return attached_entries


def _attach_historical_prior_to_watchlist(
    watchlist: list[LayerCResult],
    *,
    prior_by_ticker: dict[str, dict[str, Any]],
) -> list[LayerCResult]:
    attached_watchlist: list[LayerCResult] = []
    for item in list(watchlist or []):
        historical_prior = dict(prior_by_ticker.get(str(item.ticker or "")) or {})
        if historical_prior:
            attached_watchlist.append(item.model_copy(update={"historical_prior": historical_prior}))
        else:
            attached_watchlist.append(item)
    return attached_watchlist


def _historical_prior_float(prior: dict[str, Any], key: str) -> float | None:
    value = prior.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _historical_prior_int(prior: dict[str, Any], key: str) -> int | None:
    value = prior.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _summarize_upstream_shadow_release_historical_support(historical_prior: dict[str, Any]) -> dict[str, Any]:
    return summarize_upstream_shadow_release_historical_support_impl(
        historical_prior=historical_prior,
        historical_prior_int_fn=_historical_prior_int,
        historical_prior_float_fn=_historical_prior_float,
        summarize_shadow_release_historical_support_fn=summarize_shadow_release_historical_support,
    )


def _supports_upstream_shadow_catalyst_relief_history(historical_prior: dict[str, Any] | None) -> bool:
    prior = dict(historical_prior or {})
    execution_quality_label = str(prior.get("execution_quality_label") or "").strip()
    evaluable_count = _historical_prior_int(prior, "evaluable_count") or 0
    next_close_positive_rate = _historical_prior_float(prior, "next_close_positive_rate")
    next_open_to_close_return_mean = _historical_prior_float(prior, "next_open_to_close_return_mean")

    return (
        execution_quality_label in UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_REQUIRED_EXECUTION_QUALITY
        and evaluable_count >= UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_MIN_EVALUABLE_COUNT
        and next_close_positive_rate is not None
        and next_close_positive_rate >= UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_CLOSE_MIN
        and next_open_to_close_return_mean is not None
        and next_open_to_close_return_mean >= UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_OPEN_TO_CLOSE_MIN
    )


def _build_layer_b_filter_diagnostics(fused: list, high_pool: list) -> dict:
    selected_tickers = {item.ticker for item in high_pool}
    entries: list[dict] = []
    for rank, item in enumerate(sorted(fused, key=lambda current: current.score_b, reverse=True), start=1):
        if item.ticker in selected_tickers:
            continue
        reason = "below_fast_score_threshold" if item.score_b < FAST_AGENT_SCORE_THRESHOLD else "high_pool_truncated_by_max_size"
        entries.append(
            {
                "ticker": item.ticker,
                "reason": reason,
                "score_b": round(item.score_b, 4),
                "decision": item.decision,
                "rank": rank,
            }
        )
    summary = _build_filter_summary(entries)
    summary["selected_tickers"] = [item.ticker for item in high_pool]
    return summary


def _classify_watchlist_filter(item: LayerCResult) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if item.decision == "avoid":
        reasons.append("decision_avoid")
    if item.score_final < WATCHLIST_SCORE_THRESHOLD:
        reasons.append("score_final_below_watchlist_threshold")
    if not reasons:
        reasons.append("filtered_from_watchlist")
    return reasons[0], reasons


def _build_watchlist_filter_diagnostics(
    layer_c_results: list[LayerCResult],
    watchlist: list[LayerCResult],
    *,
    merge_approved_tickers: set[str],
    threshold_relaxation: float,
) -> dict:
    return build_watchlist_filter_diagnostics(
        layer_c_results,
        watchlist,
        merge_approved_tickers=merge_approved_tickers,
        threshold_relaxation=threshold_relaxation,
        config=WATCHLIST_DIAGNOSTICS_CONFIG,
        classify_watchlist_filter=_classify_watchlist_filter,
        build_filter_summary=_build_filter_summary,
    )


def _apply_merge_approved_fused_boost(
    fused: list,
    merge_approved_tickers: set[str],
    score_boost: float,
) -> list:
    if not merge_approved_tickers or score_boost <= 0:
        return fused
    return apply_merge_approved_fused_boost_impl(
        fused=fused,
        merge_approved_tickers=merge_approved_tickers,
        score_boost=score_boost,
        merge_approved_arbitration_applied_fn=_merge_approved_arbitration_applied,
    )


def _merge_approved_arbitration_applied(item: Any, tag: str) -> list[str]:
    arbitration_applied = list(item.arbitration_applied or [])
    if tag not in arbitration_applied:
        arbitration_applied.append(tag)
    return arbitration_applied


def _empty_merge_approved_breakout_signal_uplift_result() -> dict[str, Any]:
    return {
        "applied_tickers": [],
        "eligible_tickers": [],
        "by_ticker": {},
        "config": summarize_merge_approved_breakout_uplift_config(),
    }


def _build_merge_approved_breakout_signal_uplift_result(
    *,
    by_ticker: dict[str, Any],
    eligible_tickers: list[str],
    applied_tickers: list[str],
) -> dict[str, Any]:
    return {
        "config": summarize_merge_approved_breakout_uplift_config(),
        "eligible_tickers": sorted(eligible_tickers),
        "applied_tickers": sorted(applied_tickers),
        "by_ticker": by_ticker,
    }


def _empty_merge_approved_layer_c_alignment_uplift_result() -> dict[str, Any]:
    return {
        "applied_tickers": [],
        "eligible_tickers": [],
        "by_ticker": {},
    }


def _build_merge_approved_layer_c_alignment_uplift_result(
    *,
    by_ticker: dict[str, Any],
    eligible_tickers: list[str],
    applied_tickers: list[str],
) -> dict[str, Any]:
    return {
        "eligible_tickers": sorted(eligible_tickers),
        "applied_tickers": sorted(applied_tickers),
        "by_ticker": by_ticker,
    }


def _empty_merge_approved_sector_resonance_uplift_result() -> dict[str, Any]:
    return {
        "applied_tickers": [],
        "eligible_tickers": [],
        "by_ticker": {},
    }


def _build_merge_approved_sector_resonance_uplift_result(
    *,
    by_ticker: dict[str, Any],
    eligible_tickers: list[str],
    applied_tickers: list[str],
) -> dict[str, Any]:
    return {
        "eligible_tickers": sorted(eligible_tickers),
        "applied_tickers": sorted(applied_tickers),
        "by_ticker": by_ticker,
    }


def _merge_approved_breakout_diagnostics_for_ticker(breakout_signal_uplift: dict[str, Any], ticker: str) -> dict[str, Any]:
    breakout_by_ticker = dict(breakout_signal_uplift.get("by_ticker") or {})
    return dict(breakout_by_ticker.get(ticker) or {})


def _merge_approved_alignment_diagnostics_for_ticker(layer_c_alignment_uplift: dict[str, Any], ticker: str) -> dict[str, Any]:
    alignment_by_ticker = dict(layer_c_alignment_uplift.get("by_ticker") or {})
    return dict(alignment_by_ticker.get(ticker) or {})


def _apply_merge_approved_breakout_signal_uplift(
    fused: list,
    merge_approved_tickers: set[str],
) -> tuple[list, dict[str, Any]]:
    if not merge_approved_tickers:
        return fused, _empty_merge_approved_breakout_signal_uplift_result()
    uplifted, diagnostics = apply_merge_approved_breakout_signal_uplift_batch(
        fused=fused,
        merge_approved_tickers=merge_approved_tickers,
        apply_uplift_fn=apply_merge_approved_breakout_uplift_to_signal_map,
        merge_approved_arbitration_applied_fn=_merge_approved_arbitration_applied,
        build_result_fn=_build_merge_approved_breakout_signal_uplift_result,
    )
    return uplifted, diagnostics


def _apply_merge_approved_layer_c_alignment_uplift(
    layer_c_results: list[LayerCResult],
    merge_approved_tickers: set[str],
    breakout_signal_uplift: dict[str, Any],
) -> tuple[list[LayerCResult], dict[str, Any]]:
    if not merge_approved_tickers:
        return layer_c_results, _empty_merge_approved_layer_c_alignment_uplift_result()
    uplifted, diagnostics = apply_merge_approved_layer_c_alignment_uplift_batch(
        layer_c_results=layer_c_results,
        merge_approved_tickers=merge_approved_tickers,
        breakout_signal_uplift=breakout_signal_uplift,
        apply_uplift_fn=apply_merge_approved_layer_c_alignment_uplift,
        breakout_diagnostics_for_ticker_fn=_merge_approved_breakout_diagnostics_for_ticker,
        build_result_fn=_build_merge_approved_layer_c_alignment_uplift_result,
    )
    return uplifted, diagnostics


def _apply_merge_approved_sector_resonance_uplift(
    layer_c_results: list[LayerCResult],
    merge_approved_tickers: set[str],
    layer_c_alignment_uplift: dict[str, Any],
) -> tuple[list[LayerCResult], dict[str, Any]]:
    if not merge_approved_tickers:
        return layer_c_results, _empty_merge_approved_sector_resonance_uplift_result()
    uplifted, diagnostics = apply_merge_approved_sector_resonance_uplift_batch(
        layer_c_results=layer_c_results,
        merge_approved_tickers=merge_approved_tickers,
        layer_c_alignment_uplift=layer_c_alignment_uplift,
        apply_uplift_fn=apply_merge_approved_sector_resonance_uplift,
        alignment_diagnostics_for_ticker_fn=_merge_approved_alignment_diagnostics_for_ticker,
        build_result_fn=_build_merge_approved_sector_resonance_uplift_result,
    )
    return uplifted, diagnostics


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


def _tag_merge_approved_layer_c_results(layer_c_results: list[LayerCResult], merge_approved_tickers: set[str]) -> list[LayerCResult]:
    return tag_merge_approved_layer_c_results(layer_c_results, merge_approved_tickers)


def _compute_short_trade_boundary_candidate_score(snapshot: dict) -> float:
    return round(
        (0.30 * float(snapshot.get("breakout_freshness", 0.0) or 0.0))
        + (0.25 * float(snapshot.get("trend_acceleration", 0.0) or 0.0))
        + (0.20 * float(snapshot.get("volume_expansion_quality", 0.0) or 0.0))
        + (0.15 * float(snapshot.get("catalyst_freshness", 0.0) or 0.0))
        + (0.10 * float(snapshot.get("close_strength", 0.0) or 0.0)),
        4,
    )


def _should_release_upstream_shadow_candidate(
    *,
    candidate_entry: dict[str, Any],
    filter_reason: str,
    metrics_payload: dict[str, Any],
    historical_support: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    candidate_pool_lane = str(candidate_entry.get("candidate_pool_lane") or "")
    candidate_score = float(metrics_payload.get("candidate_score", 0.0) or 0.0)
    lane_score_floor = float(UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS.get(candidate_pool_lane, UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN))

    if candidate_pool_lane not in UPSTREAM_SHADOW_RELEASE_LANES:
        return False, None
    if filter_reason in {"metric_data_fail", "structural_prefilter_fail"}:
        return False, None
    if candidate_score < lane_score_floor:
        return False, None
    if bool((historical_support or {}).get("suppress_release")):
        return False, None
    if bool((historical_support or {}).get("sparse_weak_history")):
        return False, None
    if str((historical_support or {}).get("verdict") or "") == "supportive":
        return True, "upstream_shadow_release_supported_by_historical_prior"
    return True, "upstream_shadow_release_score_floor_pass"


def _resolve_upstream_shadow_release_max_tickers(candidate_pool_lane: str) -> int:
    return int(UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS.get(candidate_pool_lane, UPSTREAM_SHADOW_RELEASE_MAX_TICKERS))


def _resolve_upstream_shadow_release_priority_rank(candidate_pool_lane: str, ticker: str) -> int | None:
    priority_tickers = list(UPSTREAM_SHADOW_RELEASE_PRIORITY_TICKERS_BY_LANE.get(candidate_pool_lane, []))
    try:
        return priority_tickers.index(ticker)
    except ValueError:
        return None


def _select_upstream_shadow_release_entries(
    ranked_released_shadow_entries: list[tuple[float, float, float, dict[str, Any]]],
) -> list[dict[str, Any]]:
    return select_upstream_shadow_release_entries_impl(
        ranked_released_shadow_entries=ranked_released_shadow_entries,
        resolve_priority_rank_fn=_resolve_upstream_shadow_release_priority_rank,
        resolve_lane_limit_fn=_resolve_upstream_shadow_release_max_tickers,
        max_tickers=UPSTREAM_SHADOW_RELEASE_MAX_TICKERS,
        rank_scored_entries_fn=rank_scored_entries,
    )


def _resolve_upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff(candidate_pool_lane: str) -> bool:
    return bool(
        UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_BY_LANE.get(
            candidate_pool_lane,
            UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_DEFAULT,
        )
    )


def _parse_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_upstream_shadow_catalyst_relief_metrics(metrics_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_score": float(metrics_payload.get("candidate_score", 0.0) or 0.0),
        "breakout_freshness": float(metrics_payload.get("breakout_freshness", 0.0) or 0.0),
        "trend_acceleration": float(metrics_payload.get("trend_acceleration", 0.0) or 0.0),
        "close_strength": float(metrics_payload.get("close_strength", 0.0) or 0.0),
        "profitability_hard_cliff": bool(metrics_payload.get("profitability_hard_cliff")),
    }


def _passes_upstream_shadow_catalyst_relief_gates(
    *,
    threshold_config: dict[str, float],
    historical_prior: dict[str, Any] | None,
    metric_snapshot: dict[str, Any],
) -> bool:
    if not _supports_upstream_shadow_catalyst_relief_history(historical_prior):
        return False
    if float(metric_snapshot["candidate_score"]) < threshold_config["candidate_score_min"]:
        return False
    if float(metric_snapshot["breakout_freshness"]) < UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN:
        return False
    if float(metric_snapshot["trend_acceleration"]) < threshold_config["trend_acceleration_min"]:
        return False
    if float(metric_snapshot["close_strength"]) < threshold_config["close_strength_min"]:
        return False
    return True


def _build_upstream_shadow_catalyst_relief_threshold_inputs(
    *,
    candidate_pool_lane: str,
    profitability_hard_cliff: bool,
    historical_next_close_positive_rate: float | None,
) -> dict[str, Any]:
    return {
        "candidate_pool_lane": candidate_pool_lane,
        "profitability_hard_cliff": profitability_hard_cliff,
        "historical_next_close_positive_rate": historical_next_close_positive_rate,
        "candidate_score_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_CANDIDATE_SCORE_MIN),
        "trend_acceleration_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_TREND_MIN),
        "close_strength_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_CLOSE_MIN),
        "near_miss_threshold": float(UPSTREAM_SHADOW_CATALYST_RELIEF_NEAR_MISS_THRESHOLD),
        "post_gate_history_next_close_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_HISTORY_NEXT_CLOSE_MIN),
        "post_gate_hard_cliff_candidate_score_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CANDIDATE_SCORE_MIN),
        "post_gate_hard_cliff_trend_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_TREND_MIN),
        "post_gate_hard_cliff_close_min": float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_CLOSE_MIN),
        "post_gate_hard_cliff_near_miss_threshold": float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_NEAR_MISS_THRESHOLD),
    }


def _resolve_upstream_shadow_selected_threshold(
    *,
    candidate_pool_lane: str,
    profitability_hard_cliff: bool,
    shadow_visibility_gap_selected: bool,
) -> tuple[bool, float]:
    return resolve_selected_threshold(
        candidate_pool_lane=candidate_pool_lane,
        profitability_hard_cliff=profitability_hard_cliff,
        shadow_visibility_gap_selected=shadow_visibility_gap_selected,
        post_gate_selected_threshold=float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_SELECTED_THRESHOLD),
        post_gate_hard_cliff_selected_threshold=float(UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_HARD_CLIFF_SELECTED_THRESHOLD),
    )


def _build_upstream_shadow_catalyst_relief_payload_kwargs(
    *,
    threshold_config: dict[str, float],
    selected_threshold_override_enabled: bool,
    selected_threshold: float,
    require_no_profitability_hard_cliff: bool,
) -> dict[str, Any]:
    return {
        "near_miss_threshold": threshold_config["near_miss_threshold"],
        "selected_threshold_override_enabled": selected_threshold_override_enabled,
        "selected_threshold": selected_threshold,
        "breakout_freshness_min": UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN,
        "trend_acceleration_min": threshold_config["trend_acceleration_min"],
        "close_strength_min": threshold_config["close_strength_min"],
        "require_no_profitability_hard_cliff": require_no_profitability_hard_cliff,
        "required_execution_quality_labels": UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_REQUIRED_EXECUTION_QUALITY,
        "min_historical_evaluable_count": UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_MIN_EVALUABLE_COUNT,
        "min_historical_next_close_positive_rate": UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_CLOSE_MIN,
        "min_historical_next_open_to_close_return_mean": UPSTREAM_SHADOW_CATALYST_RELIEF_HISTORY_NEXT_OPEN_TO_CLOSE_MIN,
        "catalyst_freshness_floor": UPSTREAM_SHADOW_CATALYST_RELIEF_CATALYST_FRESHNESS_FLOOR,
    }


def _build_upstream_shadow_catalyst_relief_config(
    *,
    candidate_pool_lane: str,
    filter_reason: str,
    metrics_payload: dict[str, Any],
    historical_prior: dict[str, Any] | None = None,
    shadow_visibility_gap_selected: bool = False,
) -> dict[str, Any]:
    return build_upstream_shadow_catalyst_relief_config_impl(
        candidate_pool_lane=candidate_pool_lane,
        filter_reason=filter_reason,
        metrics_payload=metrics_payload,
        historical_prior=historical_prior,
        shadow_visibility_gap_selected=shadow_visibility_gap_selected,
        extract_metric_snapshot_fn=_extract_upstream_shadow_catalyst_relief_metrics,
        parse_optional_float_fn=_parse_optional_float,
        build_threshold_inputs_fn=_build_upstream_shadow_catalyst_relief_threshold_inputs,
        passes_relief_gates_fn=_passes_upstream_shadow_catalyst_relief_gates,
        resolve_require_no_profitability_hard_cliff_fn=_resolve_upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff,
        resolve_selected_threshold_fn=_resolve_upstream_shadow_selected_threshold,
        build_payload_kwargs_fn=_build_upstream_shadow_catalyst_relief_payload_kwargs,
    )


def _build_catalyst_theme_short_trade_carryover_relief_config(*, metrics_payload: dict[str, Any]) -> dict[str, Any]:
    return build_catalyst_theme_short_trade_carryover_relief_config_impl(
        metrics_payload=metrics_payload,
        candidate_score_min=CATALYST_THEME_SHORT_TRADE_CARRYOVER_CANDIDATE_SCORE_MIN,
        breakout_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_BREAKOUT_MIN,
        trend_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_TREND_MIN,
        close_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_CLOSE_MIN,
        catalyst_freshness_floor=CATALYST_THEME_SHORT_TRADE_CARRYOVER_CATALYST_FRESHNESS_FLOOR,
        near_miss_threshold=CATALYST_THEME_SHORT_TRADE_CARRYOVER_NEAR_MISS_THRESHOLD,
        min_historical_evaluable_count=CATALYST_THEME_SHORT_TRADE_CARRYOVER_MIN_HISTORICAL_EVALUABLE_COUNT,
        require_no_profitability_hard_cliff=CATALYST_THEME_SHORT_TRADE_CARRYOVER_REQUIRE_NO_PROFITABILITY_HARD_CLIFF,
    )


def _build_upstream_shadow_release_entry(*, candidate_entry: dict[str, Any], filter_reason: str, metrics_payload: dict[str, Any], release_reason: str) -> dict[str, Any]:
    return build_upstream_shadow_release_entry_impl(
        candidate_entry=candidate_entry,
        filter_reason=filter_reason,
        metrics_payload=metrics_payload,
        release_reason=release_reason,
        upstream_shadow_release_lane_score_mins=UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS,
        upstream_shadow_release_candidate_score_min=UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN,
        summarize_shadow_release_historical_support_fn=_summarize_upstream_shadow_release_historical_support,
        build_upstream_shadow_catalyst_relief_config_fn=_build_upstream_shadow_catalyst_relief_config,
    )


def _qualifies_short_trade_boundary_candidate(*, trade_date: str, entry: dict) -> tuple[bool, str, dict]:
    snapshot = build_short_trade_target_snapshot_from_entry(trade_date=trade_date, entry=entry)
    return qualify_short_trade_boundary_candidate_from_snapshot(
        snapshot=snapshot,
        compute_candidate_score_fn=_compute_short_trade_boundary_candidate_score,
        breakout_min=SHORT_TRADE_BOUNDARY_BREAKOUT_MIN,
        trend_min=SHORT_TRADE_BOUNDARY_TREND_MIN,
        volume_min=SHORT_TRADE_BOUNDARY_VOLUME_MIN,
        catalyst_min=SHORT_TRADE_BOUNDARY_CATALYST_MIN,
        candidate_score_min=SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN,
    )


def _build_short_trade_candidate_diagnostics(
    fused: list,
    high_pool: list,
    trade_date: str,
    *,
    shadow_fused: list | None = None,
    shadow_candidate_by_ticker: dict[str, CandidateStock] | None = None,
    historical_prior_by_ticker: dict[str, dict[str, Any]] | None = None,
) -> dict:
    return build_short_trade_candidate_diagnostics_impl(
        fused=fused,
        high_pool=high_pool,
        trade_date=trade_date,
        shadow_fused=shadow_fused,
        shadow_candidate_by_ticker=dict(shadow_candidate_by_ticker or {}),
        historical_prior_by_ticker=historical_prior_by_ticker or {},
        prepare_short_trade_candidate_diagnostics_state_fn=prepare_short_trade_candidate_diagnostics_state,
        finalize_short_trade_candidate_diagnostics_fn=finalize_short_trade_candidate_diagnostics,
        collect_short_trade_diagnostic_rankings_fn=collect_short_trade_diagnostic_rankings,
        resolve_short_trade_candidate_context_fn=resolve_short_trade_candidate_context,
        build_short_trade_boundary_entry_fn=_build_short_trade_boundary_entry,
        resolve_historical_prior_for_ticker_fn=_resolve_historical_prior_for_ticker,
        qualifies_short_trade_boundary_candidate_fn=_qualifies_short_trade_boundary_candidate,
        summarize_shadow_release_historical_support_fn=_summarize_upstream_shadow_release_historical_support,
        should_release_upstream_shadow_candidate_fn=_should_release_upstream_shadow_candidate,
        build_upstream_shadow_release_entry_fn=_build_upstream_shadow_release_entry,
        build_upstream_shadow_observation_entry_fn=_build_upstream_shadow_observation_entry,
        build_short_trade_ranked_outputs_fn=build_short_trade_ranked_outputs,
        rank_scored_entries_fn=rank_scored_entries,
        select_upstream_shadow_release_entries_fn=_select_upstream_shadow_release_entries,
        build_short_trade_candidate_diagnostics_payload_fn=build_short_trade_candidate_diagnostics_payload,
        build_short_trade_prefilter_thresholds_fn=build_short_trade_prefilter_thresholds,
        resolve_no_profitability_hard_cliff_fn=_resolve_upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff,
        short_trade_boundary_candidate_score_min=SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN,
        short_trade_boundary_breakout_min=SHORT_TRADE_BOUNDARY_BREAKOUT_MIN,
        short_trade_boundary_trend_min=SHORT_TRADE_BOUNDARY_TREND_MIN,
        short_trade_boundary_volume_min=SHORT_TRADE_BOUNDARY_VOLUME_MIN,
        short_trade_boundary_catalyst_min=SHORT_TRADE_BOUNDARY_CATALYST_MIN,
        upstream_shadow_release_candidate_score_min=UPSTREAM_SHADOW_RELEASE_CANDIDATE_SCORE_MIN,
        upstream_shadow_catalyst_relief_candidate_score_min=UPSTREAM_SHADOW_CATALYST_RELIEF_CANDIDATE_SCORE_MIN,
        upstream_shadow_catalyst_relief_breakout_min=UPSTREAM_SHADOW_CATALYST_RELIEF_BREAKOUT_MIN,
        upstream_shadow_catalyst_relief_trend_min=UPSTREAM_SHADOW_CATALYST_RELIEF_TREND_MIN,
        upstream_shadow_catalyst_relief_close_min=UPSTREAM_SHADOW_CATALYST_RELIEF_CLOSE_MIN,
        upstream_shadow_catalyst_relief_catalyst_freshness_floor=UPSTREAM_SHADOW_CATALYST_RELIEF_CATALYST_FRESHNESS_FLOOR,
        upstream_shadow_catalyst_relief_near_miss_threshold=UPSTREAM_SHADOW_CATALYST_RELIEF_NEAR_MISS_THRESHOLD,
        upstream_shadow_catalyst_relief_post_gate_selected_threshold=UPSTREAM_SHADOW_CATALYST_RELIEF_POST_GATE_SELECTED_THRESHOLD,
        upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff_default=UPSTREAM_SHADOW_CATALYST_RELIEF_REQUIRE_NO_PROFITABILITY_HARD_CLIFF_DEFAULT,
        upstream_shadow_release_lanes=list(UPSTREAM_SHADOW_RELEASE_LANES),
        upstream_shadow_release_lane_score_mins=UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS,
        upstream_shadow_release_lane_max_tickers=UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS,
        upstream_shadow_release_priority_tickers_by_lane=UPSTREAM_SHADOW_RELEASE_PRIORITY_TICKERS_BY_LANE,
        short_trade_boundary_max_tickers=SHORT_TRADE_BOUNDARY_MAX_TICKERS,
        upstream_shadow_observation_max_tickers=UPSTREAM_SHADOW_OBSERVATION_MAX_TICKERS,
        score_buffer=SHORT_TRADE_BOUNDARY_SCORE_BUFFER,
        minimum_score_b=FAST_AGENT_SCORE_THRESHOLD - SHORT_TRADE_BOUNDARY_SCORE_BUFFER,
        max_candidates=SHORT_TRADE_BOUNDARY_MAX_TICKERS,
    )


def _build_catalyst_theme_entry(*, item, reason: str, rank: int) -> dict:
    return {
        "ticker": item.ticker,
        "decision": "catalyst_theme",
        "score_b": round(float(item.score_b), 4),
        "score_c": 0.0,
        "score_final": round(float(item.score_b), 4),
        "quality_score": 0.5,
        "preferred_entry_mode": "theme_research_followup",
        "reason": reason,
        "reasons": [reason, "catalyst_theme_research_candidate"],
        "candidate_source": "catalyst_theme",
        "upstream_candidate_source": "layer_b_fused_universe",
        "candidate_reason_codes": [reason, "catalyst_theme_research_candidate"],
        "strategy_signals": {
            name: signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal or {})
            for name, signal in dict(item.strategy_signals or {}).items()
        },
        "agent_contribution_summary": {},
        "rank": rank,
    }


def _compute_catalyst_theme_candidate_score(snapshot: dict[str, Any]) -> float:
    return round(
        (0.40 * float(snapshot.get("catalyst_freshness", 0.0) or 0.0))
        + (0.25 * float(snapshot.get("sector_resonance", 0.0) or 0.0))
        + (0.15 * float(snapshot.get("breakout_freshness", 0.0) or 0.0))
        + (0.10 * float(snapshot.get("close_strength", 0.0) or 0.0))
        + (0.10 * float(snapshot.get("trend_acceleration", 0.0) or 0.0)),
        4,
    )


def _resolve_catalyst_theme_close_momentum_relief(
    *,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    catalyst_freshness: float,
) -> dict[str, Any]:
    return resolve_catalyst_theme_close_momentum_relief_impl(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        catalyst_freshness=catalyst_freshness,
        catalyst_theme_catalyst_min=CATALYST_THEME_CATALYST_MIN,
        catalyst_theme_close_momentum_relief_breakout_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_BREAKOUT_MIN,
        catalyst_theme_close_momentum_relief_trend_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_TREND_MIN,
        catalyst_theme_close_momentum_relief_close_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_CLOSE_MIN,
        catalyst_theme_close_momentum_relief_sector_min=CATALYST_THEME_CLOSE_MOMENTUM_RELIEF_SECTOR_MIN,
        catalyst_theme_sector_min=CATALYST_THEME_SECTOR_MIN,
    )


def _compute_catalyst_theme_threshold_shortfalls(metric_values: dict[str, Any], threshold_checks: dict[str, float] | None = None) -> dict[str, float]:
    return compute_catalyst_theme_threshold_shortfalls_impl(
        metric_values=metric_values,
        threshold_checks=threshold_checks,
        catalyst_theme_candidate_score_min=CATALYST_THEME_CANDIDATE_SCORE_MIN,
        catalyst_theme_breakout_min=CATALYST_THEME_BREAKOUT_MIN,
        catalyst_theme_close_min=CATALYST_THEME_CLOSE_MIN,
        catalyst_theme_sector_min=CATALYST_THEME_SECTOR_MIN,
        catalyst_theme_catalyst_min=CATALYST_THEME_CATALYST_MIN,
    )


def _build_catalyst_theme_shadow_entry(*, item, filter_reason: str, metrics_payload: dict[str, Any]) -> dict[str, Any]:
    return build_catalyst_theme_shadow_entry_impl(
        item=item,
        filter_reason=filter_reason,
        metrics_payload=metrics_payload,
        build_catalyst_theme_entry_fn=_build_catalyst_theme_entry,
        compute_threshold_shortfalls_fn=_compute_catalyst_theme_threshold_shortfalls,
    )


def _qualifies_catalyst_theme_candidate(*, trade_date: str, entry: dict) -> tuple[bool, str, dict[str, Any]]:
    snapshot = build_short_trade_target_snapshot_from_entry(trade_date=trade_date, entry=entry)
    return qualify_catalyst_theme_candidate_from_snapshot(
        snapshot=snapshot,
        resolve_close_momentum_relief_fn=_resolve_catalyst_theme_close_momentum_relief,
        compute_candidate_score_fn=_compute_catalyst_theme_candidate_score,
        catalyst_theme_sector_min=CATALYST_THEME_SECTOR_MIN,
        catalyst_theme_candidate_score_min=CATALYST_THEME_CANDIDATE_SCORE_MIN,
        catalyst_theme_breakout_min=CATALYST_THEME_BREAKOUT_MIN,
        catalyst_theme_close_min=CATALYST_THEME_CLOSE_MIN,
        catalyst_theme_catalyst_min=CATALYST_THEME_CATALYST_MIN,
    )


def _build_catalyst_theme_candidate_diagnostics(
    fused: list,
    watchlist: list[LayerCResult],
    short_trade_candidate_diagnostics: dict[str, Any],
    trade_date: str,
) -> dict[str, Any]:
    return build_catalyst_theme_candidate_diagnostics_impl(
        fused=fused,
        watchlist=watchlist,
        short_trade_candidate_diagnostics=short_trade_candidate_diagnostics,
        trade_date=trade_date,
        build_upstream_catalyst_theme_candidates_fn=build_upstream_catalyst_theme_candidates,
        collect_catalyst_theme_diagnostic_rankings_fn=collect_catalyst_theme_diagnostic_rankings,
        build_catalyst_theme_ranked_outputs_fn=build_catalyst_theme_ranked_outputs,
        finalize_catalyst_theme_candidate_diagnostics_fn=finalize_catalyst_theme_candidate_diagnostics,
        build_catalyst_theme_entry_fn=_build_catalyst_theme_entry,
        qualifies_catalyst_theme_candidate_fn=_qualifies_catalyst_theme_candidate,
        build_catalyst_theme_shadow_entry_fn=_build_catalyst_theme_shadow_entry,
        build_catalyst_theme_short_trade_carryover_relief_config_fn=_build_catalyst_theme_short_trade_carryover_relief_config,
        build_catalyst_theme_candidate_diagnostics_payload_fn=build_catalyst_theme_candidate_diagnostics_payload,
        build_catalyst_theme_prefilter_thresholds_fn=build_catalyst_theme_prefilter_thresholds,
        catalyst_theme_candidate_score_min=CATALYST_THEME_CANDIDATE_SCORE_MIN,
        catalyst_theme_breakout_min=CATALYST_THEME_BREAKOUT_MIN,
        catalyst_theme_close_min=CATALYST_THEME_CLOSE_MIN,
        catalyst_theme_sector_min=CATALYST_THEME_SECTOR_MIN,
        catalyst_theme_catalyst_min=CATALYST_THEME_CATALYST_MIN,
        short_trade_carryover_candidate_score_min=CATALYST_THEME_SHORT_TRADE_CARRYOVER_CANDIDATE_SCORE_MIN,
        short_trade_carryover_catalyst_freshness_floor=CATALYST_THEME_SHORT_TRADE_CARRYOVER_CATALYST_FRESHNESS_FLOOR,
        short_trade_carryover_near_miss_threshold=CATALYST_THEME_SHORT_TRADE_CARRYOVER_NEAR_MISS_THRESHOLD,
        short_trade_carryover_min_historical_evaluable_count=CATALYST_THEME_SHORT_TRADE_CARRYOVER_MIN_HISTORICAL_EVALUABLE_COUNT,
        short_trade_carryover_require_no_profitability_hard_cliff=CATALYST_THEME_SHORT_TRADE_CARRYOVER_REQUIRE_NO_PROFITABILITY_HARD_CLIFF,
        catalyst_theme_max_tickers=CATALYST_THEME_MAX_TICKERS,
        catalyst_theme_shadow_max_tickers=CATALYST_THEME_SHADOW_MAX_TICKERS,
    )


def _build_sell_order_diagnostics(sell_orders: list) -> dict:
    return build_sell_order_diagnostics_impl(
        sell_orders=sell_orders,
        build_filter_summary_fn=_build_filter_summary,
    )


def _normalize_blocked_buy_tickers(blocked_buy_tickers: dict[str, dict] | None) -> dict[str, dict]:
    normalized: dict[str, dict] = {}
    for ticker, payload in (blocked_buy_tickers or {}).items():
        normalized[str(ticker)] = dict(payload or {})
    return normalized


def _selection_target_has_weak_confirmation_reentry_risk(selection_target: DualTargetEvaluation | None) -> bool:
    short_trade = selection_target.short_trade if selection_target is not None else None
    if short_trade is None:
        return False
    negative_tags = {str(tag) for tag in short_trade.negative_tags}
    if negative_tags & WEAK_CONFIRMATION_REENTRY_NEGATIVE_TAGS:
        return True
    metrics_payload = dict(short_trade.metrics_payload or {})
    for metric_key in WEAK_CONFIRMATION_REENTRY_GUARD_KEYS:
        metric_value = metrics_payload.get(metric_key)
        if isinstance(metric_value, dict) and bool(metric_value.get("applied")):
            return True
    return False


def _resolve_reentry_required_score(cooldown_payload: dict, selection_target: DualTargetEvaluation | None) -> tuple[float, bool]:
    required_score = float(cooldown_payload.get("reentry_min_score", EXIT_REENTRY_CONFIRM_SCORE_MIN))
    weak_confirmation_reentry_guard = _selection_target_has_weak_confirmation_reentry_risk(selection_target)
    if weak_confirmation_reentry_guard:
        required_score = max(required_score, EXIT_REENTRY_WEAK_CONFIRMATION_SCORE_MIN)
    return required_score, weak_confirmation_reentry_guard


def _build_reentry_filter_payload(
    ticker: str,
    score_final: float,
    cooldown_payload: dict,
    trade_date: str,
    selection_target: DualTargetEvaluation | None = None,
) -> dict | None:
    return build_reentry_filter_payload(
        ticker=ticker,
        score_final=score_final,
        cooldown_payload=cooldown_payload,
        trade_date=trade_date,
        selection_target=selection_target,
        resolve_reentry_required_score_fn=_resolve_reentry_required_score,
    )


def _build_reentry_filter_entry(
    item: LayerCResult,
    cooldown_payload: dict,
    trade_date: str,
    selection_target: DualTargetEvaluation | None = None,
) -> dict | None:
    return _build_reentry_filter_payload(item.ticker, item.score_final, cooldown_payload, trade_date, selection_target=selection_target)


def _to_ts_code_for_price_lookup(ticker: str) -> str:
    ticker = ticker.strip().lower()
    if ticker.startswith("sh"):
        return f"{ticker[2:]}.SH"
    if ticker.startswith("sz"):
        return f"{ticker[2:]}.SZ"
    if ticker.startswith("bj"):
        return f"{ticker[2:]}.BJ"
    if ticker.startswith(("6", "68", "51", "56", "58", "60")):
        return f"{ticker}.SH"
    if ticker.startswith(("0", "3", "15", "16", "18", "20")):
        return f"{ticker}.SZ"
    if ticker.startswith(("4", "8", "43", "83", "87", "92")):
        return f"{ticker}.BJ"
    return f"{ticker}.SZ"


def build_watchlist_price_map(trade_date: str, tickers: list[str]) -> dict[str, float]:
    return build_watchlist_price_map_impl(
        trade_date=trade_date,
        tickers=tickers,
        get_daily_basic_batch_fn=get_daily_basic_batch,
        to_ts_code_for_price_lookup_fn=_to_ts_code_for_price_lookup,
    )


def _serialize_short_trade_target_profile(profile) -> dict[str, object]:
    return {
        "select_threshold": float(profile.select_threshold),
        "near_miss_threshold": float(profile.near_miss_threshold),
        "stale_penalty_block_threshold": float(profile.stale_penalty_block_threshold),
        "overhead_penalty_block_threshold": float(profile.overhead_penalty_block_threshold),
        "extension_penalty_block_threshold": float(profile.extension_penalty_block_threshold),
        "layer_c_avoid_penalty": float(profile.layer_c_avoid_penalty),
        "profitability_relief_enabled": bool(profile.profitability_relief_enabled),
        "profitability_relief_breakout_freshness_min": float(profile.profitability_relief_breakout_freshness_min),
        "profitability_relief_catalyst_freshness_min": float(profile.profitability_relief_catalyst_freshness_min),
        "profitability_relief_sector_resonance_min": float(profile.profitability_relief_sector_resonance_min),
        "profitability_relief_avoid_penalty": float(profile.profitability_relief_avoid_penalty),
        "stale_score_penalty_weight": float(profile.stale_score_penalty_weight),
        "overhead_score_penalty_weight": float(profile.overhead_score_penalty_weight),
        "extension_score_penalty_weight": float(profile.extension_score_penalty_weight),
        "strong_bearish_conflicts": sorted(str(item) for item in profile.strong_bearish_conflicts),
        "hard_block_bearish_conflicts": sorted(str(item) for item in profile.hard_block_bearish_conflicts),
        "overhead_conflict_penalty_conflicts": sorted(str(item) for item in profile.overhead_conflict_penalty_conflicts),
    }


def _attach_short_trade_target_profile(
    plan: ExecutionPlan,
    *,
    profile_name: str,
    profile_overrides: dict[str, object] | None,
) -> ExecutionPlan:
    profile = build_short_trade_target_profile(profile_name, profile_overrides)
    plan.short_trade_target_profile_name = profile.name
    plan.short_trade_target_profile_config = _serialize_short_trade_target_profile(profile)
    return plan


def _ensure_plan_target_shells(
    plan: ExecutionPlan,
    target_mode: TargetMode,
    *,
    short_trade_target_profile_name: str = "default",
    short_trade_target_profile_overrides: dict[str, object] | None = None,
) -> ExecutionPlan:
    return ensure_plan_target_shells_impl(
        plan=plan,
        target_mode=target_mode,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        dual_target_summary_cls=DualTargetSummary,
        load_latest_historical_prior_by_ticker_fn=_load_latest_btst_historical_prior_by_ticker,
        attach_historical_prior_to_entries_fn=_attach_historical_prior_to_entries,
        attach_historical_prior_to_watchlist_fn=_attach_historical_prior_to_watchlist,
        use_short_trade_target_profile_fn=use_short_trade_target_profile,
        build_selection_targets_fn=build_selection_targets,
        summarize_selection_targets_fn=summarize_selection_targets,
        attach_short_trade_target_profile_fn=_attach_short_trade_target_profile,
    )


def build_buy_orders_with_diagnostics(
    watchlist: list[LayerCResult],
    portfolio_snapshot: dict,
    trade_date: str = "",
    candidate_by_ticker: dict[str, CandidateStock] | None = None,
    price_map: dict[str, float] | None = None,
    blocked_buy_tickers: dict[str, dict] | None = None,
    selection_targets: dict[str, DualTargetEvaluation] | None = None,
) -> tuple[list, dict]:
    return build_buy_orders_with_diagnostics_impl(
        watchlist=watchlist,
        portfolio_snapshot=portfolio_snapshot,
        trade_date=trade_date,
        candidate_by_ticker=candidate_by_ticker,
        price_map=price_map,
        blocked_buy_tickers=blocked_buy_tickers,
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=_normalize_blocked_buy_tickers,
        build_filter_summary_fn=_build_filter_summary,
        build_reentry_filter_entry_fn=_build_reentry_filter_entry,
        resolve_continuation_execution_overrides_fn=_resolve_continuation_execution_overrides,
        calculate_position_fn=calculate_position,
        enforce_daily_trade_limit_fn=enforce_daily_trade_limit,
    )


def _resolve_continuation_execution_overrides(*, item: LayerCResult, selection_target: DualTargetEvaluation | None) -> dict[str, Any]:
    if not CONTINUATION_EXECUTION_ENABLED or selection_target is None or selection_target.short_trade is None:
        return {}

    short_trade = selection_target.short_trade
    positive_tags = {str(tag).strip() for tag in list(short_trade.positive_tags or []) if str(tag or "").strip()}
    continuation_payload = dict((short_trade.metrics_payload or {}).get("t_plus_2_continuation_candidate") or {})
    if "t_plus_2_continuation_candidate" not in positive_tags or not bool(continuation_payload.get("applied")):
        return {}

    return {
        "applied": True,
        "watchlist_min_score_override": CONTINUATION_WATCHLIST_MIN_SCORE,
        "watchlist_edge_execution_ratio_override": CONTINUATION_WATCHLIST_EDGE_EXECUTION_RATIO,
        "candidate_source": str(continuation_payload.get("candidate_source") or ""),
        "ticker": item.ticker,
    }


@dataclass
class DailyPipeline:
    agent_runner: AgentRunner | None = None
    exit_checker: ExitChecker = _default_exit_checker
    base_model_name: str = ""
    base_model_provider: str = ""
    selected_analysts: list[str] | None = None
    fast_selected_analysts: list[str] | None = None
    frozen_post_market_plans: dict[str, ExecutionPlan] | None = None
    frozen_plan_source: str | None = None
    target_mode: TargetMode = "research_only"
    short_trade_target_profile_name: str = "default"
    short_trade_target_profile_overrides: dict[str, object] = field(default_factory=dict)
    merge_approved_tickers: set[str] = field(default_factory=set)
    execution_plan_provenance_log: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        uses_default_agent_runner = self.agent_runner is None
        if uses_default_agent_runner:
            if not self.base_model_name or not self.base_model_provider:
                default_model_name, default_model_provider = get_default_model_config()
                self.base_model_name = str(self.base_model_name or default_model_name)
                self.base_model_provider = str(self.base_model_provider or default_model_provider)
            self.agent_runner = self._run_agents_with_base_model
        if self.base_model_name and self.base_model_provider:
            self._skip_precise_stage = _should_skip_precise_stage(self.base_model_name, self.base_model_provider)
        else:
            self._skip_precise_stage = not uses_default_agent_runner
        self._exit_checker_accepts_logic_scores = len(signature(self.exit_checker).parameters) >= 3
        self.short_trade_target_profile_name = str(self.short_trade_target_profile_name or "default")
        self.short_trade_target_profile_overrides = dict(self.short_trade_target_profile_overrides or {})
        self.merge_approved_tickers = load_merge_approved_tickers(
            explicit_tickers=set(self.merge_approved_tickers or set()).union(MERGE_APPROVED_TICKERS),
            merge_review_path=MERGE_APPROVED_MERGE_REVIEW_PATH or None,
            merge_ranking_path=MERGE_APPROVED_RANKING_PATH or None,
        )
        self._short_trade_target_profile = build_short_trade_target_profile(
            self.short_trade_target_profile_name,
            self.short_trade_target_profile_overrides,
        )
        if self.frozen_post_market_plans is not None:
            self.frozen_post_market_plans = {
                str(trade_date): _ensure_plan_target_shells(
                    ExecutionPlan.model_validate(plan),
                    self.target_mode,
                    short_trade_target_profile_name=self.short_trade_target_profile_name,
                    short_trade_target_profile_overrides=self.short_trade_target_profile_overrides,
                )
                for trade_date, plan in self.frozen_post_market_plans.items()
            }

    def _run_exit_checker(self, portfolio_snapshot: dict, trade_date: str, logic_scores: dict[str, float] | None = None) -> list:
        if self._exit_checker_accepts_logic_scores:
            return self.exit_checker(portfolio_snapshot, trade_date, logic_scores or {})
        return self.exit_checker(portfolio_snapshot, trade_date)

    def _resolve_selected_analysts_for_tier(self, model_tier: str) -> list[str] | None:
        if model_tier == "fast" and self.fast_selected_analysts is not None:
            return list(self.fast_selected_analysts)
        if self.selected_analysts is not None:
            return list(self.selected_analysts)
        return None

    def _run_agents_with_base_model(self, tickers: list[str], trade_date: str, model_tier: str) -> dict[str, dict[str, dict]]:
        from src.main import run_hedge_fund

        start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=365)).strftime("%Y-%m-%d")
        end_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
        model_name, model_provider = _resolve_pipeline_model_config(model_tier, self.base_model_name, self.base_model_provider)
        selected_analysts = self._resolve_selected_analysts_for_tier(model_tier)
        llm_observability = {
            "trade_date": trade_date,
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": model_tier,
        }
        if selected_analysts is not None:
            llm_observability["selected_analysts"] = list(selected_analysts)
        result = run_hedge_fund(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            portfolio={"cash": 1_000_000, "positions": {}, "margin_requirement": 0.0, "margin_used": 0.0, "realized_gains": {}},
            show_reasoning=False,
            selected_analysts=selected_analysts or [],
            model_name=model_name,
            model_provider=model_provider,
            llm_observability=llm_observability,
        )
        execution_plan_provenance = result.get("execution_plan_provenance")
        if isinstance(execution_plan_provenance, dict):
            execution_observation = {
                "trade_date": trade_date,
                "model_tier": model_tier,
                "tickers": list(tickers),
                "execution_plan_provenance": execution_plan_provenance,
            }
            if selected_analysts is not None:
                execution_observation["selected_analysts"] = list(selected_analysts)
            self.execution_plan_provenance_log.append(
                execution_observation
            )
        return result.get("analyst_signals", {})

    def _apply_frozen_buy_order_filters(self, frozen_plan: ExecutionPlan, trade_date: str, blocked_buy_tickers: dict[str, dict]) -> ExecutionPlan:
        plan = frozen_plan.model_copy(deep=True)
        plan = _ensure_plan_target_shells(
            plan,
            self.target_mode,
            short_trade_target_profile_name=self.short_trade_target_profile_name,
            short_trade_target_profile_overrides=self.short_trade_target_profile_overrides,
        )
        if not blocked_buy_tickers or not plan.buy_orders:
            return plan

        watchlist_by_ticker = {item.ticker: item for item in plan.watchlist}
        selection_targets = dict(plan.selection_targets or {})
        retained_orders = []
        filtered_entries: list[dict] = []
        for order in plan.buy_orders:
            cooldown_payload = blocked_buy_tickers.get(order.ticker)
            if cooldown_payload is None:
                retained_orders.append(order)
                continue

            watch_item = watchlist_by_ticker.get(order.ticker)
            score_final = float(watch_item.score_final if watch_item is not None else order.score_final)
            filter_entry = _build_reentry_filter_payload(
                order.ticker,
                score_final,
                cooldown_payload,
                trade_date,
                selection_target=selection_targets.get(order.ticker),
            )
            if filter_entry is None:
                retained_orders.append(order)
                continue
            filtered_entries.append(filter_entry)

        if not filtered_entries:
            return plan

        plan.buy_orders = retained_orders
        risk_metrics = dict(plan.risk_metrics or {})
        counts = dict(risk_metrics.get("counts", {}))
        funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}))
        filters = dict(funnel_diagnostics.get("filters", {}))
        existing_buy_order_summary = dict(filters.get("buy_orders", {}))
        existing_entries = list(existing_buy_order_summary.get("tickers", []))
        existing_entries.extend(filtered_entries)
        buy_order_summary = _build_filter_summary(existing_entries)
        buy_order_summary["selected_tickers"] = [order.ticker for order in retained_orders]
        filters["buy_orders"] = buy_order_summary
        funnel_diagnostics["filters"] = filters
        funnel_diagnostics["blocked_buy_tickers"] = blocked_buy_tickers
        counts["buy_order_count"] = len(retained_orders)
        risk_metrics["counts"] = counts
        risk_metrics["funnel_diagnostics"] = funnel_diagnostics
        plan.risk_metrics = risk_metrics
        return plan

    def run_post_market(self, trade_date: str, portfolio_snapshot: Optional[dict] = None, blocked_buy_tickers: dict[str, dict] | None = None) -> ExecutionPlan:
        blocked_buy_tickers = _normalize_blocked_buy_tickers(blocked_buy_tickers)
        if self.frozen_post_market_plans is not None:
            frozen_plan = self.frozen_post_market_plans.get(trade_date)
            if frozen_plan is None:
                raise ValueError(f"Missing frozen current_plan for trade_date={trade_date}")
            return self._apply_frozen_buy_order_filters(frozen_plan, trade_date, blocked_buy_tickers)

        total_started_at = perf_counter()
        portfolio_snapshot = portfolio_snapshot or {"cash": 1_000_000, "positions": {}}
        candidate_context, candidate_timing = self._collect_post_market_candidate_context(trade_date)
        watchlist_context = self._build_post_market_watchlist_context(candidate_context, trade_date)
        order_context, order_timing = self._build_post_market_order_context(
            trade_date=trade_date,
            portfolio_snapshot=portfolio_snapshot,
            blocked_buy_tickers=blocked_buy_tickers,
            watchlist_context=watchlist_context,
            logic_scores=candidate_context.logic_scores,
        )

        diagnostics_aggregation: PostMarketDiagnosticsAggregation = aggregate_post_market_diagnostics(
            candidate_context=candidate_context,
            watchlist_context=watchlist_context,
            order_context=order_context,
            blocked_buy_tickers=blocked_buy_tickers,
            precise_stage_skipped=self._skip_precise_stage,
            fast_agent_score_threshold=FAST_AGENT_SCORE_THRESHOLD,
            fast_agent_max_tickers=FAST_AGENT_MAX_TICKERS,
            precise_agent_max_tickers=PRECISE_AGENT_MAX_TICKERS,
            watchlist_score_threshold=WATCHLIST_SCORE_THRESHOLD,
            candidate_timing=candidate_timing,
            order_timing=order_timing,
            total_post_market_seconds=perf_counter() - total_started_at,
        )
        counts = diagnostics_aggregation.counts
        funnel_diagnostics = diagnostics_aggregation.funnel_diagnostics
        timing_seconds = diagnostics_aggregation.timing_seconds
        selection_resolution: PostMarketSelectionResolution = resolve_post_market_selection_targets(
            trade_date=trade_date,
            watchlist_context=watchlist_context,
            buy_orders=order_context.buy_orders,
            counts=counts,
            funnel_diagnostics=funnel_diagnostics,
            target_mode=self.target_mode,
            short_trade_target_profile_name=self.short_trade_target_profile_name,
            short_trade_target_profile_overrides=self.short_trade_target_profile_overrides,
            use_short_trade_target_profile_fn=use_short_trade_target_profile,
            build_selection_target_inputs_fn=build_selection_target_inputs,
            attach_historical_prior_to_entries_fn=_attach_historical_prior_to_entries,
            build_selection_targets_fn=build_selection_targets,
        )
        counts = selection_resolution.counts
        funnel_diagnostics = selection_resolution.funnel_diagnostics
        selection_targets = selection_resolution.selection_targets
        dual_target_summary = selection_resolution.dual_target_summary
        return build_post_market_execution_plan(
            trade_date=trade_date,
            candidate_context=candidate_context,
            watchlist_context=watchlist_context,
            order_context=order_context,
            portfolio_snapshot=portfolio_snapshot,
            timing_seconds=timing_seconds,
            counts=counts,
            funnel_diagnostics=funnel_diagnostics,
            merge_approved_tickers=self.merge_approved_tickers,
            merge_approved_score_boost=MERGE_APPROVED_SCORE_BOOST,
            merge_approved_watchlist_threshold_relaxation=MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION,
            selection_targets=selection_targets,
            target_mode=self.target_mode,
            dual_target_summary=dual_target_summary,
            short_trade_target_profile=self._short_trade_target_profile,
            serialize_short_trade_target_profile_fn=_serialize_short_trade_target_profile,
            generate_execution_plan_fn=generate_execution_plan,
        )

    def _collect_post_market_candidate_context(self, trade_date: str) -> tuple[PostMarketCandidateContext, dict[str, float]]:
        stage_started_at = perf_counter()
        candidates, shadow_candidates, candidate_pool_shadow_summary = _load_candidate_pool_bundle(trade_date)
        candidate_pool_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        market_state = detect_market_state(trade_date)
        market_state_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        scored = score_batch(candidates, trade_date)
        score_batch_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        shadow_scored = score_batch(shadow_candidates, trade_date) if shadow_candidates else {}
        shadow_score_batch_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        fused = fuse_batch(scored, market_state, trade_date)
        fused = _apply_merge_approved_fused_boost(fused, self.merge_approved_tickers, MERGE_APPROVED_SCORE_BOOST)
        fused, merge_approved_breakout_signal_uplift = _apply_merge_approved_breakout_signal_uplift(fused, self.merge_approved_tickers)
        fuse_batch_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        shadow_fused = fuse_batch(shadow_scored, market_state, trade_date) if shadow_scored else []
        shadow_fuse_batch_seconds = perf_counter() - stage_started_at

        high_pool = build_high_pool(
            fused,
            score_threshold=FAST_AGENT_SCORE_THRESHOLD,
            max_tickers=FAST_AGENT_MAX_TICKERS,
        )
        top_precise_pool = high_pool[:PRECISE_AGENT_MAX_TICKERS]

        stage_started_at = perf_counter()
        agent_results = self.agent_runner([item.ticker for item in high_pool], trade_date, "fast") if high_pool else {}
        fast_agent_seconds = perf_counter() - stage_started_at

        skipped_precise_ticker_count = len(top_precise_pool) if self._skip_precise_stage else 0
        estimated_skipped_precise_seconds = _estimate_skipped_precise_seconds(fast_agent_seconds, len(high_pool), skipped_precise_ticker_count)
        stage_started_at = perf_counter()
        precise_results = self.agent_runner([item.ticker for item in top_precise_pool], trade_date, "precise") if top_precise_pool and not self._skip_precise_stage else {}
        precise_agent_seconds = perf_counter() - stage_started_at
        merged_agent_results = merge_agent_results(agent_results, precise_results)

        stage_started_at = perf_counter()
        layer_c_results = aggregate_layer_c_results(high_pool, merged_agent_results)
        layer_c_results, merge_approved_layer_c_alignment_uplift = _apply_merge_approved_layer_c_alignment_uplift(
            layer_c_results,
            self.merge_approved_tickers,
            merge_approved_breakout_signal_uplift,
        )
        layer_c_results, merge_approved_sector_resonance_uplift = _apply_merge_approved_sector_resonance_uplift(
            layer_c_results,
            self.merge_approved_tickers,
            merge_approved_layer_c_alignment_uplift,
        )
        layer_c_results = _tag_merge_approved_layer_c_results(layer_c_results, self.merge_approved_tickers)
        aggregate_layer_c_seconds = perf_counter() - stage_started_at

        return (
            PostMarketCandidateContext(
                candidates=candidates,
                shadow_candidates=shadow_candidates,
                candidate_pool_shadow_summary=candidate_pool_shadow_summary,
                market_state=market_state,
                fused=fused,
                shadow_fused=shadow_fused,
                high_pool=high_pool,
                top_precise_pool=top_precise_pool,
                layer_c_results=layer_c_results,
                logic_scores=_build_logic_score_map(layer_c_results),
                merge_approved_breakout_signal_uplift=merge_approved_breakout_signal_uplift,
                merge_approved_layer_c_alignment_uplift=merge_approved_layer_c_alignment_uplift,
                merge_approved_sector_resonance_uplift=merge_approved_sector_resonance_uplift,
            ),
            {
                "candidate_pool_seconds": candidate_pool_seconds,
                "market_state_seconds": market_state_seconds,
                "score_batch_seconds": score_batch_seconds,
                "shadow_score_batch_seconds": shadow_score_batch_seconds,
                "fuse_batch_seconds": fuse_batch_seconds,
                "shadow_fuse_batch_seconds": shadow_fuse_batch_seconds,
                "fast_agent_seconds": fast_agent_seconds,
                "precise_agent_seconds": precise_agent_seconds,
                "estimated_skipped_precise_seconds": estimated_skipped_precise_seconds,
                "aggregate_layer_c_seconds": aggregate_layer_c_seconds,
            },
        )

    def _build_post_market_watchlist_context(
        self,
        candidate_context: PostMarketCandidateContext,
        trade_date: str,
    ) -> PostMarketWatchlistContext:
        watchlist = _build_merge_approved_watchlist(
            candidate_context.layer_c_results,
            self.merge_approved_tickers,
            MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION,
        )
        layer_b_filter_diagnostics = _build_layer_b_filter_diagnostics(candidate_context.fused, candidate_context.high_pool)
        watchlist_filter_diagnostics = _build_watchlist_filter_diagnostics(
            candidate_context.layer_c_results,
            watchlist,
            merge_approved_tickers=self.merge_approved_tickers,
            threshold_relaxation=MERGE_APPROVED_WATCHLIST_THRESHOLD_RELAXATION,
        )
        historical_prior_by_ticker = _load_latest_btst_historical_prior_by_ticker()
        short_trade_candidate_diagnostics = _build_short_trade_candidate_diagnostics(
            candidate_context.fused,
            candidate_context.high_pool,
            trade_date,
            shadow_fused=candidate_context.shadow_fused,
            shadow_candidate_by_ticker={candidate.ticker: candidate for candidate in candidate_context.shadow_candidates},
            historical_prior_by_ticker=historical_prior_by_ticker,
        )
        watchlist = _attach_historical_prior_to_watchlist(
            watchlist,
            prior_by_ticker=historical_prior_by_ticker,
        )
        catalyst_theme_candidate_diagnostics = _build_catalyst_theme_candidate_diagnostics(
            candidate_context.fused,
            watchlist,
            short_trade_candidate_diagnostics,
            trade_date,
        )
        return PostMarketWatchlistContext(
            watchlist=watchlist,
            layer_b_filter_diagnostics=layer_b_filter_diagnostics,
            watchlist_filter_diagnostics=watchlist_filter_diagnostics,
            historical_prior_by_ticker=historical_prior_by_ticker,
            short_trade_candidate_diagnostics=short_trade_candidate_diagnostics,
            catalyst_theme_candidate_diagnostics=catalyst_theme_candidate_diagnostics,
            candidate_by_ticker={candidate.ticker: candidate for candidate in candidate_context.candidates},
            price_map=build_watchlist_price_map(trade_date, [item.ticker for item in watchlist]),
        )

    def _build_post_market_order_context(
        self,
        *,
        trade_date: str,
        portfolio_snapshot: dict,
        blocked_buy_tickers: dict[str, dict],
        watchlist_context: PostMarketWatchlistContext,
        logic_scores: dict[str, float],
    ) -> tuple[PostMarketOrderContext, dict[str, float]]:
        with use_short_trade_target_profile(profile_name=self.short_trade_target_profile_name, overrides=self.short_trade_target_profile_overrides):
            prebuy_selection_targets, _ = build_selection_targets(
                trade_date=trade_date,
                watchlist=watchlist_context.watchlist,
                rejected_entries=[],
                supplemental_short_trade_entries=[],
                buy_order_tickers=set(),
                target_mode=self.target_mode,
            )

        stage_started_at = perf_counter()
        buy_orders, buy_order_filter_diagnostics = self._build_buy_orders_with_diagnostics(
            watchlist_context.watchlist,
            portfolio_snapshot,
            trade_date=trade_date,
            candidate_by_ticker=watchlist_context.candidate_by_ticker,
            price_map=watchlist_context.price_map,
            blocked_buy_tickers=blocked_buy_tickers,
            selection_targets=prebuy_selection_targets,
        )
        build_buy_orders_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        sell_orders = self._run_exit_checker(portfolio_snapshot, trade_date, logic_scores)
        sell_check_seconds = perf_counter() - stage_started_at
        return (
            PostMarketOrderContext(
                prebuy_selection_targets=prebuy_selection_targets,
                buy_orders=buy_orders,
                buy_order_filter_diagnostics=buy_order_filter_diagnostics,
                sell_orders=sell_orders,
                sell_order_diagnostics=_build_sell_order_diagnostics(sell_orders),
            ),
            {
                "build_buy_orders_seconds": build_buy_orders_seconds,
                "sell_check_seconds": sell_check_seconds,
            },
        )

    def run_pre_market(
        self,
        plan: ExecutionPlan,
        trade_date_t1: str,
        refreshed_scores: dict[str, float] | None = None,
        atr_values: dict[str, float] | None = None,
        open_gap_pct: dict[str, float] | None = None,
        negative_news_tickers: set[str] | None = None,
    ) -> ExecutionPlan:
        return apply_signal_decay(
            plan,
            trade_date_t1,
            refreshed_scores=refreshed_scores,
            atr_values=atr_values,
            open_gap_pct=open_gap_pct,
            negative_news_tickers=negative_news_tickers,
        )

    def run_intraday(
        self,
        plan: ExecutionPlan,
        trade_date_t1: str,
        confirmation_inputs: dict[str, dict] | None = None,
        crisis_inputs: dict | None = None,
    ) -> tuple[list, list, dict]:
        confirmation_inputs = confirmation_inputs or {}
        confirmed_orders = []
        for order in plan.buy_orders:
            data = confirmation_inputs.get(order.ticker, {})
            result = confirm_buy_signal(
                day_low=float(data.get("day_low", 0.0)),
                ema30=float(data.get("ema30", 0.0)),
                current_price=float(data.get("current_price", 0.0)),
                vwap=float(data.get("vwap", 0.0)),
                intraday_volume=float(data.get("intraday_volume", 0.0)),
                avg_same_time_volume=float(data.get("avg_same_time_volume", 1.0)),
                industry_percentile=float(data.get("industry_percentile", 1.0)),
                stock_pct_change=float(data.get("stock_pct_change", 0.0)),
                industry_pct_change=float(data.get("industry_pct_change", 0.0)),
            )
            if result["confirmed"]:
                confirmed_orders.append(order)

        crisis_inputs = crisis_inputs or {}
        crisis_response = evaluate_crisis_response(
            hs300_daily_return=float(crisis_inputs.get("hs300_daily_return", 0.0)),
            limit_down_count=int(crisis_inputs.get("limit_down_count", 0)),
            recent_total_volumes=list(crisis_inputs.get("recent_total_volumes", [])),
            drawdown_pct=float(crisis_inputs.get("drawdown_pct", 0.0)),
        )
        exits = self._run_exit_checker(plan.portfolio_snapshot, trade_date_t1, plan.logic_scores)
        return confirmed_orders, exits, crisis_response

    def _build_buy_orders_with_diagnostics(
        self,
        watchlist: list[LayerCResult],
        portfolio_snapshot: dict,
        trade_date: str = "",
        candidate_by_ticker: dict[str, CandidateStock] | None = None,
        price_map: dict[str, float] | None = None,
        blocked_buy_tickers: dict[str, dict] | None = None,
        selection_targets: dict[str, DualTargetEvaluation] | None = None,
    ) -> tuple[list, dict]:
        return build_buy_orders_with_diagnostics(
            watchlist,
            portfolio_snapshot,
            trade_date=trade_date,
            candidate_by_ticker=candidate_by_ticker,
            price_map=price_map,
            blocked_buy_tickers=blocked_buy_tickers,
            selection_targets=selection_targets,
        )
