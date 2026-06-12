"""Historical prior computation and enrichment for BTST brief entries.

This module encapsulates all logic related to:
- Normalizing price frames and extracting next-day outcomes
- Building historical prior summaries from opportunity/watch-candidate rows
- Enriching BTST brief entry groups with historical prior data
- Postprocessing enriched groups (demotion, partition, sorting)

Refactored in R20.16: price helpers extracted to historical_prior_price.py,
opportunity summarization to historical_prior_opportunity.py, row collection and
entry application to historical_prior_collection.py, brief enrichment and
postprocessing to historical_prior_brief_enrichment.py.  This file keeps the
historical-prior builders (opportunity pool + watch-candidate) and re-exports
all public names for backward compatibility.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.paper_trading.btst_reporting_utils import (
    OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
    OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES,
    _format_float,
)
from src.paper_trading._btst_reporting.classifiers import (
    _classify_historical_prior,
    _classify_execution_quality_prior,
)
from src.paper_trading._btst_reporting.entry_builders import (
    _extract_research_upside_radar_entry,
)

# Re-export from extracted sub-modules (backward compat)
from src.paper_trading._btst_reporting.historical_prior_price import (  # noqa: F401
    _normalize_price_frame,
    _extract_next_day_outcome,
)
from src.paper_trading._btst_reporting.historical_prior_opportunity import (  # noqa: F401
    _summarize_historical_opportunity_rows,
    _build_empty_historical_opportunity_summary_state,
    _accumulate_historical_opportunity_summary,
    _compute_historical_opportunity_rates,
    _evaluate_historical_opportunity_row,
    _build_historical_opportunity_summary_payload,
    _summarize_next_close_payoff,
    _compute_payoff_ratio,
    _compute_profit_factor,
    _detect_win_rate_payoff_divergence,
)
from src.paper_trading._btst_reporting.historical_prior_collection import (  # noqa: F401
    _collect_historical_opportunity_rows,
    _collect_historical_watch_candidate_rows,
    _collect_watch_candidate_rows_from_selection_targets,
    _collect_watch_candidate_rows_from_catalyst_entries,
    _append_watch_candidate_row,
    _decorate_watch_candidate_history_entry,
    _build_btst_candidate_historical_context,
    _apply_historical_prior_to_entries,
    _apply_historical_prior_to_entry,
)
from src.paper_trading._btst_reporting.historical_prior_brief_enrichment import (  # noqa: F401
    _enrich_btst_brief_entries_with_history,
    _enrich_upstream_shadow_entries_with_history,
    _build_empty_btst_candidate_historical_context,
    _build_empty_brief_history_observer_groups,
    _build_empty_brief_history_enrichment_result,
    _postprocess_brief_history_enriched_groups,
    _apply_and_reclassify_brief_history_groups,
    _demote_and_partition_brief_history_groups,
    _sort_brief_history_enriched_groups,
    _apply_historical_prior_to_brief_entry_groups,
    _apply_execution_quality_modes_to_brief_groups,
)


# ---------------------------------------------------------------------------
# Historical prior summary builder
# ---------------------------------------------------------------------------


def _build_historical_prior_summary(
    *,
    applied_scope: str,
    evaluable_count: int,
    hit_rate: float | None,
    close_positive_rate: float | None,
    scope_label: str | None = None,
) -> str | None:
    if evaluable_count <= 0:
        return None
    resolved_scope_label = scope_label or (
        "同票" if applied_scope == "same_ticker" else "同源"
    )
    threshold_pct = OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD * 100.0
    return (
        f"{resolved_scope_label}历史 {evaluable_count} 例，next_high>={threshold_pct:.1f}% 命中率={_format_float(hit_rate)}, "
        f"next_close 正收益率={_format_float(close_positive_rate)}。"
    )


# ---------------------------------------------------------------------------
# Opportunity pool historical prior
# ---------------------------------------------------------------------------


def _build_opportunity_pool_historical_prior(
    entry: dict[str, Any],
    historical_rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
) -> dict[str, Any]:
    same_ticker_rows = [
        row for row in historical_rows if row.get("ticker") == entry.get("ticker")
    ]
    same_source_rows = [
        row
        for row in historical_rows
        if row.get("candidate_source") == entry.get("candidate_source")
    ]
    applied_scope, applied_rows = _resolve_opportunity_pool_historical_scope(
        same_ticker_rows, same_source_rows
    )

    stats = _summarize_historical_opportunity_rows(applied_rows, price_cache)
    bias_label, monitor_priority = _classify_historical_prior(
        stats.get("next_high_hit_rate_at_threshold"),
        stats.get("next_close_positive_rate"),
        int(stats.get("evaluable_count") or 0),
    )
    bias_label, monitor_priority = _apply_payoff_divergence_monitor_guardrail(
        bias_label=bias_label,
        monitor_priority=monitor_priority,
        stats=stats,
    )
    execution_quality = _classify_execution_quality_prior(
        stats.get("next_open_return_mean"),
        stats.get("next_open_to_close_return_mean"),
        stats.get("next_high_return_mean"),
        stats.get("next_close_return_mean"),
        stats.get("next_high_hit_rate_at_threshold"),
        stats.get("next_close_positive_rate"),
        int(stats.get("evaluable_count") or 0),
        bool(stats.get("win_rate_payoff_divergence")),
    )
    return _build_opportunity_pool_historical_prior_payload(
        same_ticker_rows=same_ticker_rows,
        same_source_rows=same_source_rows,
        applied_scope=applied_scope,
        stats=stats,
        bias_label=bias_label,
        monitor_priority=monitor_priority,
        execution_quality=execution_quality,
    )


def _resolve_opportunity_pool_historical_scope(
    same_ticker_rows: list[dict[str, Any]],
    same_source_rows: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    if len(same_ticker_rows) >= OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES:
        return "same_ticker", same_ticker_rows
    if same_source_rows:
        return "candidate_source", same_source_rows
    if same_ticker_rows:
        return "same_ticker", same_ticker_rows
    return "none", []


def _build_opportunity_pool_historical_prior_payload(
    *,
    same_ticker_rows: list[dict[str, Any]],
    same_source_rows: list[dict[str, Any]],
    applied_scope: str,
    stats: dict[str, Any],
    bias_label: str,
    monitor_priority: str,
    execution_quality: dict[str, str],
) -> dict[str, Any]:
    return {
        "same_ticker_sample_count": len(same_ticker_rows),
        "same_candidate_source_sample_count": len(same_source_rows),
        "applied_scope": applied_scope,
        **stats,
        "bias_label": bias_label,
        "monitor_priority": monitor_priority,
        **execution_quality,
        "summary": _build_historical_prior_summary(
            applied_scope=applied_scope,
            evaluable_count=int(stats.get("evaluable_count") or 0),
            hit_rate=stats.get("next_high_hit_rate_at_threshold"),
            close_positive_rate=stats.get("next_close_positive_rate"),
        ),
    }


# ---------------------------------------------------------------------------
# Watch-candidate historical prior
# ---------------------------------------------------------------------------


def _build_watch_candidate_historical_prior(
    entry: dict[str, Any],
    historical_rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
    *,
    family: str,
) -> dict[str, Any]:
    from src.paper_trading._btst_reporting.historical_prior_collection import (
        _decorate_watch_candidate_history_entry,
    )

    decorated_entry = _decorate_watch_candidate_history_entry(entry, family)
    row_buckets = _build_watch_candidate_historical_row_buckets(
        historical_rows=historical_rows,
        decorated_entry=decorated_entry,
        family=family,
    )
    applied_scope, scope_label, applied_rows = _resolve_watch_candidate_scope_selection(
        row_buckets
    )

    stats = _summarize_historical_opportunity_rows(applied_rows, price_cache)
    bias_label, monitor_priority = _classify_historical_prior(
        stats.get("next_high_hit_rate_at_threshold"),
        stats.get("next_close_positive_rate"),
        int(stats.get("evaluable_count") or 0),
    )
    bias_label, monitor_priority = _apply_payoff_divergence_monitor_guardrail(
        bias_label=bias_label,
        monitor_priority=monitor_priority,
        stats=stats,
    )
    execution_quality = _classify_execution_quality_prior(
        stats.get("next_open_return_mean"),
        stats.get("next_open_to_close_return_mean"),
        stats.get("next_high_return_mean"),
        stats.get("next_close_return_mean"),
        stats.get("next_high_hit_rate_at_threshold"),
        stats.get("next_close_positive_rate"),
        int(stats.get("evaluable_count") or 0),
        bool(stats.get("win_rate_payoff_divergence")),
    )
    return _build_watch_candidate_historical_prior_payload(
        family=family,
        decorated_entry=decorated_entry,
        row_buckets=row_buckets,
        applied_scope=applied_scope,
        stats=stats,
        bias_label=bias_label,
        monitor_priority=monitor_priority,
        execution_quality=execution_quality,
        scope_label=scope_label,
    )


def _build_watch_candidate_historical_prior_payload(
    *,
    family: str,
    decorated_entry: dict[str, Any],
    row_buckets: dict[str, list[dict[str, Any]]],
    applied_scope: str,
    stats: dict[str, Any],
    bias_label: str,
    monitor_priority: str,
    execution_quality: dict[str, str],
    scope_label: str | None,
) -> dict[str, Any]:
    return {
        "watch_candidate_family": family,
        "score_bucket": decorated_entry.get("score_bucket"),
        "catalyst_bucket": decorated_entry.get("catalyst_bucket"),
        "same_ticker_sample_count": len(row_buckets["same_ticker"]),
        "same_family_sample_count": len(row_buckets["same_family"]),
        "same_candidate_source_sample_count": len(row_buckets["same_source"]),
        "same_family_source_sample_count": len(row_buckets["same_family_source"]),
        "same_family_source_score_catalyst_sample_count": len(
            row_buckets["same_family_source_score_catalyst"]
        ),
        "same_source_score_sample_count": len(row_buckets["same_source_score"]),
        "applied_scope": applied_scope,
        **stats,
        "bias_label": bias_label,
        "monitor_priority": monitor_priority,
        **execution_quality,
        "summary": _build_historical_prior_summary(
            applied_scope=applied_scope,
            evaluable_count=int(stats.get("evaluable_count") or 0),
            hit_rate=stats.get("next_high_hit_rate_at_threshold"),
            close_positive_rate=stats.get("next_close_positive_rate"),
            scope_label=scope_label,
        ),
    }


def _apply_payoff_divergence_monitor_guardrail(
    *,
    bias_label: str,
    monitor_priority: str,
    stats: dict[str, Any],
) -> tuple[str, str]:
    if not stats.get("win_rate_payoff_divergence"):
        return bias_label, monitor_priority
    guarded_priority = "medium" if monitor_priority == "high" else monitor_priority
    return "mixed", guarded_priority


def _build_watch_candidate_historical_row_buckets(
    *,
    historical_rows: list[dict[str, Any]],
    decorated_entry: dict[str, Any],
    family: str,
) -> dict[str, list[dict[str, Any]]]:
    same_ticker_rows = [
        row
        for row in historical_rows
        if row.get("ticker") == decorated_entry.get("ticker")
    ]
    same_family_rows = [
        row for row in historical_rows if row.get("watch_candidate_family") == family
    ]
    same_source_rows = [
        row
        for row in historical_rows
        if row.get("candidate_source") == decorated_entry.get("candidate_source")
    ]
    same_family_source_rows = [
        row
        for row in same_family_rows
        if row.get("candidate_source") == decorated_entry.get("candidate_source")
    ]
    same_family_source_score_catalyst_rows = [
        row
        for row in same_family_source_rows
        if row.get("score_bucket") == decorated_entry.get("score_bucket")
        and row.get("catalyst_bucket") == decorated_entry.get("catalyst_bucket")
    ]
    same_source_score_rows = [
        row
        for row in same_source_rows
        if row.get("score_bucket") == decorated_entry.get("score_bucket")
    ]
    return {
        "same_ticker": same_ticker_rows,
        "same_family": same_family_rows,
        "same_source": same_source_rows,
        "same_family_source": same_family_source_rows,
        "same_family_source_score_catalyst": same_family_source_score_catalyst_rows,
        "same_source_score": same_source_score_rows,
    }


def _resolve_watch_candidate_scope_selection(
    row_buckets: dict[str, list[dict[str, Any]]],
) -> tuple[str, str | None, list[dict[str, Any]]]:
    scope_candidates = [
        (
            "same_ticker",
            "同票",
            row_buckets["same_ticker"]
            if len(row_buckets["same_ticker"])
            >= OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES
            else [],
        ),
        (
            "family_source_score_catalyst",
            "同层同源同分桶",
            row_buckets["same_family_source_score_catalyst"],
        ),
        ("family_source", "同层同源", row_buckets["same_family_source"]),
        ("source_score", "同源同分桶", row_buckets["same_source_score"]),
        ("candidate_source", "同源", row_buckets["same_source"]),
        ("same_ticker", "同票", row_buckets["same_ticker"]),
    ]
    for scope_name, label, scope_rows in scope_candidates:
        if scope_rows:
            return scope_name, label, scope_rows
    return "none", None, []


# ---------------------------------------------------------------------------
# Excluded research entry
# ---------------------------------------------------------------------------


def _extract_excluded_research_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    research_entry = selection_entry.get("research") or {}
    short_trade_entry = selection_entry.get("short_trade") or {}
    if research_entry.get("decision") != "selected":
        return None
    if short_trade_entry.get("decision") in {"selected", "near_miss"}:
        return None
    if _extract_research_upside_radar_entry(selection_entry) is not None:
        return None

    return {
        "ticker": selection_entry.get("ticker"),
        "research_score_target": research_entry.get("score_target"),
        "short_trade_decision": short_trade_entry.get("decision"),
        "short_trade_score_target": short_trade_entry.get("score_target"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "delta_summary": list(selection_entry.get("delta_summary") or []),
    }
