"""Post-market orchestration helpers for the daily pipeline."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

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


@dataclass(frozen=True)
class PostMarketSelectionResolution:
    counts: dict[str, Any]
    funnel_diagnostics: dict[str, Any]
    selection_targets: dict[str, Any]
    dual_target_summary: Any


@dataclass(frozen=True)
class PostMarketDiagnosticsAggregation:
    counts: dict[str, Any]
    funnel_diagnostics: dict[str, Any]
    timing_seconds: dict[str, float]


@dataclass(frozen=True)
class PlanTargetShellInputs:
    watchlist: list[Any]
    rejected_entries: list[dict[str, Any]]
    supplemental_short_trade_entries: list[dict[str, Any]]
    buy_order_tickers: set[str]


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
        "upstream_shadow_promoted_count": int((watchlist_context.short_trade_candidate_diagnostics or {}).get("promoted_to_watchlist_count") or 0),
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


def aggregate_post_market_diagnostics(
    *,
    candidate_context: PostMarketCandidateContext,
    watchlist_context: PostMarketWatchlistContext,
    order_context: PostMarketOrderContext,
    blocked_buy_tickers: dict[str, dict],
    precise_stage_skipped: bool,
    fast_agent_score_threshold: float,
    fast_agent_max_tickers: int,
    precise_agent_max_tickers: int,
    watchlist_score_threshold: float,
    candidate_timing: dict[str, float],
    order_timing: dict[str, float],
    total_post_market_seconds: float,
) -> PostMarketDiagnosticsAggregation:
    skipped_precise_ticker_count = len(candidate_context.top_precise_pool) if precise_stage_skipped else 0
    counts = build_post_market_counts(
        candidate_context=candidate_context,
        watchlist_context=watchlist_context,
        order_context=order_context,
        precise_stage_skipped=precise_stage_skipped,
        skipped_precise_ticker_count=skipped_precise_ticker_count,
        fast_agent_score_threshold=fast_agent_score_threshold,
        fast_agent_max_tickers=fast_agent_max_tickers,
        precise_agent_max_tickers=precise_agent_max_tickers,
        watchlist_score_threshold=watchlist_score_threshold,
    )
    funnel_diagnostics = build_post_market_funnel_diagnostics(
        counts=counts,
        candidate_context=candidate_context,
        watchlist_context=watchlist_context,
        order_context=order_context,
        blocked_buy_tickers=blocked_buy_tickers,
    )
    timing_seconds = build_post_market_timing_seconds(
        candidate_pool_seconds=candidate_timing["candidate_pool_seconds"],
        market_state_seconds=candidate_timing["market_state_seconds"],
        score_batch_seconds=candidate_timing["score_batch_seconds"],
        fuse_batch_seconds=candidate_timing["fuse_batch_seconds"],
        shadow_score_batch_seconds=candidate_timing["shadow_score_batch_seconds"],
        shadow_fuse_batch_seconds=candidate_timing["shadow_fuse_batch_seconds"],
        fast_agent_seconds=candidate_timing["fast_agent_seconds"],
        precise_agent_seconds=candidate_timing["precise_agent_seconds"],
        estimated_skipped_precise_seconds=candidate_timing["estimated_skipped_precise_seconds"],
        aggregate_layer_c_seconds=candidate_timing["aggregate_layer_c_seconds"],
        build_buy_orders_seconds=order_timing["build_buy_orders_seconds"],
        sell_check_seconds=order_timing["sell_check_seconds"],
        total_post_market_seconds=total_post_market_seconds,
    )
    return PostMarketDiagnosticsAggregation(
        counts=counts,
        funnel_diagnostics=funnel_diagnostics,
        timing_seconds=timing_seconds,
    )


def build_sell_order_diagnostics(
    *,
    sell_orders: list[Any],
    build_filter_summary_fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any]:
    def _extract_sell_order_value(order: Any, field_name: str, default: Any = None) -> Any:
        if isinstance(order, dict):
            return order.get(field_name, default)
        return getattr(order, field_name, default)

    entries: list[dict[str, Any]] = []
    for order in sell_orders:
        reason = _extract_sell_order_value(order, "trigger_reason") or _extract_sell_order_value(order, "level") or _extract_sell_order_value(order, "reason") or "sell_signal"
        entries.append(
            {
                "ticker": _extract_sell_order_value(order, "ticker", ""),
                "reason": str(reason),
                "level": _extract_sell_order_value(order, "level"),
                "urgency": _extract_sell_order_value(order, "urgency"),
                "sell_ratio": _extract_sell_order_value(order, "sell_ratio"),
            }
        )
    summary = build_filter_summary_fn(entries)
    summary["count"] = len(sell_orders)
    return summary


def build_watchlist_price_map(
    *,
    trade_date: str,
    tickers: list[str],
    get_daily_basic_batch_fn: Callable[[str], Any],
    to_ts_code_for_price_lookup_fn: Callable[[str], str],
) -> dict[str, float]:
    if not tickers:
        return {}

    df = get_daily_basic_batch_fn(trade_date)
    if df is None or df.empty or "ts_code" not in df.columns or "close" not in df.columns:
        return {}

    ts_to_ticker = {to_ts_code_for_price_lookup_fn(ticker): ticker for ticker in tickers}
    filtered = df[df["ts_code"].isin(ts_to_ticker.keys())]
    if filtered.empty:
        return {}

    price_map: dict[str, float] = {}
    for _, row in filtered.iterrows():
        ticker = ts_to_ticker.get(str(row["ts_code"]))
        close = row.get("close")
        if ticker and close is not None:
            try:
                price_map[ticker] = float(close)
            except (TypeError, ValueError):
                continue
    return price_map


def build_selection_target_inputs(
    *,
    trade_date: str,
    watchlist_filter_diagnostics: dict[str, Any],
    short_trade_candidate_diagnostics: dict[str, Any],
    catalyst_theme_candidate_diagnostics: dict[str, Any],
    target_mode: str,
    market_state: Any | None = None,
) -> PostMarketSelectionTargetInputs:
    market_state_payload = _serialize_market_state_payload(market_state)
    entry_filter_rules = build_default_btst_candidate_entry_filter_rules()
    released_shadow_entries = _filter_promoted_upstream_shadow_entries(
        list((short_trade_candidate_diagnostics or {}).get("released_shadow_entries", []) or [])
    )
    rejected_entries = list((watchlist_filter_diagnostics or {}).get("tickers", []) or [])
    supplemental_short_trade_entries = [
        *list((short_trade_candidate_diagnostics or {}).get("tickers", []) or []),
        *released_shadow_entries,
        *list((watchlist_filter_diagnostics or {}).get("released_shadow_entries", []) or []),
        *(list((catalyst_theme_candidate_diagnostics or {}).get("tickers", []) or []) if target_mode == "short_trade_only" else []),
    ]
    rejected_entries = _attach_market_state_to_entries(rejected_entries, market_state_payload=market_state_payload)
    supplemental_short_trade_entries = _attach_market_state_to_entries(supplemental_short_trade_entries, market_state_payload=market_state_payload)
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
            "candidate_entry_filter_observability": {rule_name: {key: int(value) for key, value in counters.items()} for rule_name, counters in sorted(candidate_entry_filter_observability.items())},
        },
    )


def _serialize_market_state_payload(market_state: Any | None) -> dict[str, Any]:
    if market_state is None:
        return {}
    if hasattr(market_state, "model_dump"):
        payload = market_state.model_dump(mode="json")
        return dict(payload or {})
    if isinstance(market_state, dict):
        return dict(market_state)
    return {}


def _filter_promoted_upstream_shadow_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(entry) for entry in list(entries or []) if not bool(dict(entry).get("promoted_to_watchlist"))]


def _attach_market_state_to_entries(entries: list[dict[str, Any]], *, market_state_payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not market_state_payload:
        return list(entries or [])
    attached_entries: list[dict[str, Any]] = []
    for entry in list(entries or []):
        updated_entry = dict(entry)
        updated_entry.setdefault("market_state", dict(market_state_payload))
        attached_entries.append(updated_entry)
    return attached_entries


def build_plan_target_shell_inputs(
    *,
    plan: Any,
    target_mode: str,
    historical_prior_by_ticker: dict[str, dict[str, Any]],
    attach_historical_prior_to_entries_fn,
    attach_historical_prior_to_watchlist_fn,
) -> PlanTargetShellInputs:
    funnel_diagnostics = dict((plan.risk_metrics or {}).get("funnel_diagnostics", {}) or {})
    funnel_filters = dict(funnel_diagnostics.get("filters", {}) or {})
    watchlist_filter_diagnostics = dict(funnel_filters.get("watchlist", {}) or {})
    short_trade_candidate_diagnostics = dict(funnel_filters.get("short_trade_candidates", {}) or {})
    released_shadow_entries = _filter_promoted_upstream_shadow_entries(
        list(short_trade_candidate_diagnostics.get("released_shadow_entries", []) or [])
    )
    catalyst_theme_candidates = list(dict(funnel_filters.get("catalyst_theme_candidates", {}) or {}).get("tickers", []) or []) if target_mode == "short_trade_only" else []
    return PlanTargetShellInputs(
        rejected_entries=attach_historical_prior_to_entries_fn(
            list(watchlist_filter_diagnostics.get("tickers", []) or []),
            prior_by_ticker=historical_prior_by_ticker,
        ),
        watchlist=attach_historical_prior_to_watchlist_fn(
            list(plan.watchlist or []),
            prior_by_ticker=historical_prior_by_ticker,
        ),
        supplemental_short_trade_entries=attach_historical_prior_to_entries_fn(
            [
                *list(short_trade_candidate_diagnostics.get("tickers", []) or []),
                *released_shadow_entries,
                *list(watchlist_filter_diagnostics.get("released_shadow_entries", []) or []),
                *catalyst_theme_candidates,
            ],
            prior_by_ticker=historical_prior_by_ticker,
        ),
        buy_order_tickers={order.ticker for order in list(plan.buy_orders or [])},
    )


def prepare_plan_target_shell_context(
    *,
    plan: Any,
    target_mode: str,
    dual_target_summary_cls: type,
    load_latest_historical_prior_by_ticker_fn: Callable[[], dict[str, dict[str, Any]]],
    attach_historical_prior_to_entries_fn,
    attach_historical_prior_to_watchlist_fn,
) -> tuple[dict[str, Any], Any, PlanTargetShellInputs]:
    selection_targets = dict(plan.selection_targets or {})
    summary = plan.dual_target_summary if isinstance(plan.dual_target_summary, dual_target_summary_cls) else dual_target_summary_cls.model_validate(plan.dual_target_summary or {})
    historical_prior_by_ticker = load_latest_historical_prior_by_ticker_fn()
    shell_inputs = build_plan_target_shell_inputs(
        plan=plan,
        target_mode=target_mode,
        historical_prior_by_ticker=historical_prior_by_ticker,
        attach_historical_prior_to_entries_fn=attach_historical_prior_to_entries_fn,
        attach_historical_prior_to_watchlist_fn=attach_historical_prior_to_watchlist_fn,
    )
    return selection_targets, summary, shell_inputs


def resolve_plan_target_shell_selection(
    *,
    plan_date: str,
    selection_targets: dict[str, Any],
    shell_inputs: PlanTargetShellInputs,
    target_mode: str,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    use_short_trade_target_profile_fn: Callable[..., Any],
    build_selection_targets_fn: Callable[..., tuple[dict[str, Any], Any]],
    summarize_selection_targets_fn: Callable[..., Any],
) -> tuple[dict[str, Any], Any]:
    if not selection_targets and (shell_inputs.watchlist or shell_inputs.rejected_entries or shell_inputs.supplemental_short_trade_entries):
        with use_short_trade_target_profile_fn(
            profile_name=short_trade_target_profile_name,
            overrides=short_trade_target_profile_overrides,
        ):
            return build_selection_targets_fn(
                trade_date=plan_date,
                watchlist=shell_inputs.watchlist,
                rejected_entries=shell_inputs.rejected_entries,
                supplemental_short_trade_entries=shell_inputs.supplemental_short_trade_entries,
                buy_order_tickers=shell_inputs.buy_order_tickers,
                target_mode=target_mode,
            )
    return selection_targets, summarize_selection_targets_fn(
        selection_targets=selection_targets,
        target_mode=target_mode,
    )


def ensure_plan_target_shells(
    *,
    plan: Any,
    target_mode: str,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    dual_target_summary_cls: type,
    load_latest_historical_prior_by_ticker_fn: Callable[[], dict[str, dict[str, Any]]],
    attach_historical_prior_to_entries_fn,
    attach_historical_prior_to_watchlist_fn,
    use_short_trade_target_profile_fn: Callable[..., Any],
    build_selection_targets_fn: Callable[..., tuple[dict[str, Any], Any]],
    summarize_selection_targets_fn: Callable[..., Any],
    attach_short_trade_target_profile_fn: Callable[..., Any],
) -> Any:
    selection_targets, summary, shell_inputs = prepare_plan_target_shell_context(
        plan=plan,
        target_mode=target_mode,
        dual_target_summary_cls=dual_target_summary_cls,
        load_latest_historical_prior_by_ticker_fn=load_latest_historical_prior_by_ticker_fn,
        attach_historical_prior_to_entries_fn=attach_historical_prior_to_entries_fn,
        attach_historical_prior_to_watchlist_fn=attach_historical_prior_to_watchlist_fn,
    )
    selection_targets, summary = resolve_plan_target_shell_selection(
        plan_date=plan.date,
        selection_targets=selection_targets,
        shell_inputs=shell_inputs,
        target_mode=target_mode,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        use_short_trade_target_profile_fn=use_short_trade_target_profile_fn,
        build_selection_targets_fn=build_selection_targets_fn,
        summarize_selection_targets_fn=summarize_selection_targets_fn,
    )
    plan.selection_targets = selection_targets
    plan.target_mode = target_mode
    plan.dual_target_summary = summary
    return attach_short_trade_target_profile_fn(
        plan,
        profile_name=short_trade_target_profile_name,
        profile_overrides=short_trade_target_profile_overrides,
    )


def resolve_post_market_selection_targets(
    *,
    trade_date: str,
    watchlist_context: PostMarketWatchlistContext,
    market_state: Any | None,
    buy_orders: list[Any],
    counts: dict[str, Any],
    funnel_diagnostics: dict[str, Any],
    target_mode: str,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    use_short_trade_target_profile_fn: Callable[..., Any],
    build_selection_target_inputs_fn: Callable[..., PostMarketSelectionTargetInputs],
    attach_historical_prior_to_entries_fn,
    build_selection_targets_fn: Callable[..., tuple[dict[str, Any], Any]],
) -> PostMarketSelectionResolution:
    with use_short_trade_target_profile_fn(
        profile_name=short_trade_target_profile_name,
        overrides=short_trade_target_profile_overrides,
    ):
        selection_target_inputs = build_selection_target_inputs_fn(
            trade_date=trade_date,
            watchlist_filter_diagnostics=watchlist_context.watchlist_filter_diagnostics,
            short_trade_candidate_diagnostics=watchlist_context.short_trade_candidate_diagnostics,
            catalyst_theme_candidate_diagnostics=watchlist_context.catalyst_theme_candidate_diagnostics,
            target_mode=target_mode,
            market_state=market_state,
        )
        resolved_counts = dict(counts)
        resolved_counts["candidate_entry_filtered_count"] = int(selection_target_inputs.candidate_entry_filter_diagnostics.get("filtered_count") or 0)
        resolved_funnel_diagnostics = dict(funnel_diagnostics)
        funnel_filters = dict(resolved_funnel_diagnostics.get("filters", {}) or {})
        funnel_filters["candidate_entry"] = selection_target_inputs.candidate_entry_filter_diagnostics
        resolved_funnel_diagnostics["filters"] = funnel_filters
        selection_targets, dual_target_summary = build_selection_targets_fn(
            trade_date=trade_date,
            watchlist=watchlist_context.watchlist,
            rejected_entries=attach_historical_prior_to_entries_fn(
                selection_target_inputs.rejected_entries,
                prior_by_ticker=watchlist_context.historical_prior_by_ticker,
            ),
            supplemental_short_trade_entries=attach_historical_prior_to_entries_fn(
                selection_target_inputs.supplemental_short_trade_entries,
                prior_by_ticker=watchlist_context.historical_prior_by_ticker,
            ),
            buy_order_tickers={order.ticker for order in buy_orders},
            target_mode=target_mode,
        )
    return PostMarketSelectionResolution(
        counts=resolved_counts,
        funnel_diagnostics=resolved_funnel_diagnostics,
        selection_targets=selection_targets,
        dual_target_summary=dual_target_summary,
    )


def build_post_market_execution_plan(
    *,
    trade_date: str,
    candidate_context: PostMarketCandidateContext,
    watchlist_context: PostMarketWatchlistContext,
    order_context: PostMarketOrderContext,
    portfolio_snapshot: dict[str, Any],
    timing_seconds: dict[str, float],
    counts: dict[str, Any],
    funnel_diagnostics: dict[str, Any],
    merge_approved_tickers: set[str],
    merge_approved_score_boost: float,
    merge_approved_watchlist_threshold_relaxation: float,
    selection_targets: dict[str, Any],
    target_mode: str,
    dual_target_summary: Any,
    short_trade_target_profile: Any,
    serialize_short_trade_target_profile_fn: Callable[[Any], dict[str, object]],
    generate_execution_plan_fn: Callable[..., Any],
) -> Any:
    return generate_execution_plan_fn(
        trade_date=trade_date,
        market_state=candidate_context.market_state,
        watchlist=watchlist_context.watchlist,
        logic_scores=candidate_context.logic_scores,
        buy_orders=order_context.buy_orders,
        sell_orders=order_context.sell_orders,
        portfolio_snapshot=portfolio_snapshot,
        risk_alerts=[],
        risk_metrics={
            "timing_seconds": timing_seconds,
            "counts": counts,
            "funnel_diagnostics": funnel_diagnostics,
            "merge_approved_context": {
                "tickers": sorted(merge_approved_tickers),
                "score_boost": round(merge_approved_score_boost, 4),
                "watchlist_threshold_relaxation": round(merge_approved_watchlist_threshold_relaxation, 4),
                "breakout_signal_uplift": candidate_context.merge_approved_breakout_signal_uplift,
                "layer_c_alignment_uplift": candidate_context.merge_approved_layer_c_alignment_uplift,
                "sector_resonance_uplift": candidate_context.merge_approved_sector_resonance_uplift,
            },
        },
        layer_a_count=len(candidate_context.candidates),
        layer_b_count=len(candidate_context.high_pool),
        layer_c_count=len(candidate_context.layer_c_results),
        selection_targets=selection_targets,
        target_mode=target_mode,
        dual_target_summary=dual_target_summary,
        short_trade_target_profile_name=short_trade_target_profile.name,
        short_trade_target_profile_config=serialize_short_trade_target_profile_fn(short_trade_target_profile),
    )
