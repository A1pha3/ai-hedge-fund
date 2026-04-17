from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from collections.abc import Callable

import pandas as pd

from src.paper_trading.btst_reporting_utils import (
    OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
    OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
    OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES,
    OPPORTUNITY_POOL_MAX_ENTRIES,
    OPPORTUNITY_POOL_MIN_SCORE_TARGET,
    OPPORTUNITY_POOL_STRONG_SIGNAL_MIN,
    UPSTREAM_SHADOW_CANDIDATE_SOURCES,
    WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT,
    _as_float,
    _catalyst_bucket_label,
    _compact_trade_date,
    _format_float,
    _load_json,
    _load_selection_replay_input,
    _mean_or_none,
    _normalize_trade_date,
    _resolve_followup_trade_dates,
    _resolve_replay_input_path,
    _round_or_none,
    _score_bucket_label,
    _shadow_decision_rank,
    _source_lane_display,
    _source_lane_label,
    _sync_text_artifact_alias,
    _write_json,
    infer_next_trade_date,
    _entry_mode_action_guidance,
    _execution_priority_rank,
    _historical_execution_entry_sort_key,
    _monitor_priority_rank,
    _opportunity_pool_execution_sort_key,
    _research_historical_entry_sort_key,
    _summary_value,
)

from scripts.btst_latest_followup_utils import _choose_preferred_historical_prior
from src.paper_trading.btst_opening_watch_markdown_helpers import (
    append_catalyst_theme_watch_markdown as _append_catalyst_theme_watch_markdown_impl,
    append_opening_watch_focus_items_markdown as _append_opening_watch_focus_items_markdown_impl,
)
from src.paper_trading.btst_priority_board_markdown_helpers import (
    append_priority_board_frontier_markdown as _append_priority_board_frontier_markdown_impl,
    append_priority_board_overview_markdown as _append_priority_board_overview_markdown_impl,
    append_priority_board_rows_markdown as _append_priority_board_rows_markdown_impl,
    append_priority_board_shadow_watch_markdown as _append_priority_board_shadow_watch_markdown_impl,
)
from src.paper_trading.btst_trade_brief_shadow_markdown_helpers import (
    append_brief_catalyst_frontier_markdown as _append_brief_catalyst_frontier_markdown_impl,
    append_brief_catalyst_shadow_markdown as _append_brief_catalyst_shadow_markdown_impl,
    append_brief_upstream_shadow_markdown as _append_brief_upstream_shadow_markdown_impl,
)
from src.paper_trading.btst_shared_markdown_helpers import (
    append_frontier_priority_summary as _append_frontier_priority_summary_impl,
    append_frontier_promoted_shadow_none_block as _append_frontier_promoted_shadow_none_block_impl,
    append_frontier_section as _append_frontier_section_impl,
    append_guardrail_section as _append_guardrail_section_impl,
    append_indexed_ticker_block as _append_indexed_ticker_block_impl,
    append_indexed_ticker_blocks as _append_indexed_ticker_blocks_impl,
    append_none_block as _append_none_block_impl,
    append_source_paths_section as _append_source_paths_section_impl,
    append_titled_indexed_section as _append_titled_indexed_section_impl,
    append_titled_indexed_ticker_section as _append_titled_indexed_ticker_section_impl,
    append_upstream_shadow_core_fields as _append_upstream_shadow_core_fields_impl,
    append_upstream_shadow_section as _append_upstream_shadow_section_impl,
    append_upstream_shadow_summary as _append_upstream_shadow_summary_impl,
    append_upstream_shadow_summary_header as _append_upstream_shadow_summary_header_impl,
)
from src.paper_trading.btst_trade_brief_core_markdown_helpers import (
    append_brief_observer_lane_markdown as _append_brief_observer_lane_markdown_impl,
    append_brief_scored_entries_markdown as _append_brief_scored_entries_markdown_impl,
)
from src.paper_trading.btst_trade_brief_catalyst_markdown_helpers import (
    append_brief_catalyst_theme_markdown as _append_brief_catalyst_theme_markdown_impl,
    append_brief_excluded_research_markdown as _append_brief_excluded_research_markdown_impl,
)
from src.paper_trading.btst_trade_brief_pool_markdown_helpers import (
    append_brief_opportunity_pool_markdown as _append_brief_opportunity_pool_markdown_impl,
    append_brief_pruned_entries_markdown as _append_brief_pruned_entries_markdown_impl,
    append_brief_research_radar_markdown as _append_brief_research_radar_markdown_impl,
)
from src.paper_trading.btst_recommendation_helpers import (
    append_pool_and_observer_recommendations as _append_pool_and_observer_recommendations_impl,
    append_primary_and_near_miss_recommendations as _append_primary_and_near_miss_recommendations_impl,
    append_research_and_shadow_recommendations as _append_research_and_shadow_recommendations_impl,
)
from src.paper_trading.btst_premarket_markdown_helpers import (
    append_premarket_frontier_watch_markdown as _append_premarket_frontier_watch_markdown_impl,
    append_premarket_shadow_watch_markdown as _append_premarket_shadow_watch_markdown_impl,
)
from src.paper_trading.btst_report_artifact_helpers import (
    generate_and_register_btst_followup_artifacts as _generate_and_register_btst_followup_artifacts_impl,
    generate_btst_next_day_priority_board_artifacts as _generate_btst_next_day_priority_board_artifacts_impl,
    generate_btst_next_day_trade_brief_artifacts as _generate_btst_next_day_trade_brief_artifacts_impl,
    generate_btst_opening_watch_card_artifacts as _generate_btst_opening_watch_card_artifacts_impl,
    generate_btst_premarket_execution_card_artifacts as _generate_btst_premarket_execution_card_artifacts_impl,
    register_btst_followup_artifacts as _register_btst_followup_artifacts_impl,
    resolve_followup_artifact_context as _resolve_followup_artifact_context_impl,
)
from src.project_env import load_project_dotenv
from src.tools.akshare_api import get_prices_robust
from src.tools.api import get_price_data, prices_to_df
from src.paper_trading._btst_reporting.extractors import (
    _resolve_upstream_shadow_candidate_reason_codes,
    _build_upstream_shadow_promotion_trigger,
    _extract_short_trade_core_metrics,
    _extract_upstream_shadow_replay_only_entry,
    RESEARCH_UPSIDE_RADAR_MAX_ENTRIES,
)
from src.paper_trading._btst_reporting.classifiers import (
    _classify_historical_prior,
    _classify_execution_quality_prior,
)
from src.paper_trading._btst_reporting.entry_mode_utils import (
    _augment_execution_note as _augment_execution_note_impl,
    _selected_action_posture as _selected_action_posture_impl,
    _selected_holding_contract_note as _selected_holding_contract_note_impl,
)
from src.paper_trading._btst_reporting.catalyst_render_helpers import (
    _append_threshold_shortfalls_line as _append_threshold_shortfalls_line_impl,
    _append_catalyst_watch_metrics as _append_catalyst_watch_metrics_impl,
)
from src.paper_trading._btst_reporting.entry_transforms import (
    _apply_execution_quality_entry_mode as _apply_execution_quality_entry_mode_impl,
    _build_catalyst_theme_shadow_watch_rows as _build_catalyst_theme_shadow_watch_rows_impl,
    CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES as _CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES,
)
from src.paper_trading._btst_reporting.priority_board import (
    analyze_btst_next_day_priority_board as _analyze_btst_next_day_priority_board_impl,
)
from src.paper_trading._btst_reporting.premarket_card import (
    analyze_btst_premarket_execution_card as _analyze_btst_premarket_execution_card_impl,
)
from src.paper_trading._btst_reporting.opening_watch import (
    analyze_btst_opening_watch_card as _analyze_btst_opening_watch_card_impl,
)
from src.paper_trading._btst_reporting.entry_builders import (
    _build_catalyst_theme_frontier_priority as _build_catalyst_theme_frontier_priority_eb,
    _build_upstream_shadow_summary as _build_upstream_shadow_summary_eb,
    _discover_recent_historical_report_dirs as _discover_recent_historical_report_dirs_eb,
    _extract_catalyst_theme_entry as _extract_catalyst_theme_entry_eb,
    _extract_catalyst_theme_shadow_entry as _extract_catalyst_theme_shadow_entry_eb,
    _extract_next_day_outcome as _extract_next_day_outcome_eb,
    _extract_research_upside_radar_entry as _extract_research_upside_radar_entry_eb,
    _extract_short_trade_entry as _extract_short_trade_entry_eb,
    _extract_short_trade_opportunity_entry as _extract_short_trade_opportunity_entry_eb,
    _extract_upstream_shadow_entry as _extract_upstream_shadow_entry_eb,
    _iter_selection_snapshot_paths as _iter_selection_snapshot_paths_eb,
    _load_catalyst_theme_frontier_summary as _load_catalyst_theme_frontier_summary_eb,
    _merge_entry_historical_prior as _merge_entry_historical_prior_eb,
    _reclassify_selected_execution_quality_entries as _reclassify_selected_execution_quality_entries_eb,
    _resolve_snapshot_path as _resolve_snapshot_path_eb,
    CATALYST_THEME_MAX_ENTRIES,
    CATALYST_THEME_SHADOW_MAX_ENTRIES as CATALYST_THEME_SHADOW_MAX_ENTRIES_CONST,
)


load_project_dotenv()


CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES = 3


def _extract_upstream_shadow_entry(
    selection_entry: dict[str, Any], supplemental_entry: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    return _extract_upstream_shadow_entry_eb(selection_entry, supplemental_entry)





def _build_upstream_shadow_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return _build_upstream_shadow_summary_eb(entries)





def _load_catalyst_theme_frontier_summary(
    report_dir: str | Path | None,
) -> dict[str, Any]:
    return _load_catalyst_theme_frontier_summary_eb(report_dir)



def _build_catalyst_theme_frontier_priority(
    frontier_summary: dict[str, Any], shadow_entries: list[dict[str, Any]]
) -> dict[str, Any]:
    return _build_catalyst_theme_frontier_priority_eb(frontier_summary, shadow_entries)



def _resolve_snapshot_path(
    input_path: str | Path, trade_date: str | None
) -> tuple[Path, Path]:
    return _resolve_snapshot_path_eb(input_path, trade_date)





def _extract_next_day_outcome(
    ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]
) -> dict[str, Any]:
    return _extract_next_day_outcome_eb(ticker, trade_date, price_cache)





def _iter_selection_snapshot_paths(report_dir: Path) -> list[Path]:
    return _iter_selection_snapshot_paths_eb(report_dir)



def _discover_recent_historical_report_dirs(
    report_dir: Path,
    trade_date: str | None,
    max_reports: int = OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
) -> list[Path]:
    return _discover_recent_historical_report_dirs_eb(report_dir, trade_date, max_reports)



def _extract_short_trade_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    return _extract_short_trade_entry_eb(selection_entry)





def _apply_execution_quality_entry_mode(entry: dict[str, Any]) -> dict[str, Any]:
    return _apply_execution_quality_entry_mode_impl(entry)


def _merge_entry_historical_prior(
    entry: dict[str, Any], historical_prior: dict[str, Any]
) -> dict[str, Any]:
    return _merge_entry_historical_prior_eb(entry, historical_prior)



def _reclassify_selected_execution_quality_entries(
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    return _reclassify_selected_execution_quality_entries_eb(selected_entries, near_miss_entries, opportunity_pool_entries)



def _extract_short_trade_opportunity_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    return _extract_short_trade_opportunity_entry_eb(selection_entry)









def _extract_research_upside_radar_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    return _extract_research_upside_radar_entry_eb(selection_entry)



def _extract_catalyst_theme_entry(candidate: dict[str, Any]) -> dict[str, Any] | None:
    return _extract_catalyst_theme_entry_eb(candidate)



def _extract_catalyst_theme_shadow_entry(
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    return _extract_catalyst_theme_shadow_entry_eb(candidate)



def _build_catalyst_theme_shadow_watch_rows(
    entries: list[dict[str, Any]],
    *,
    limit: int = _CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES,
) -> list[dict[str, Any]]:
    return _build_catalyst_theme_shadow_watch_rows_impl(entries, limit=limit)


def _decorate_watch_candidate_history_entry(
    entry: dict[str, Any], family: str
) -> dict[str, Any]:
    metrics = dict(entry.get("metrics") or {})
    return {
        **entry,
        "watch_candidate_family": family,
        "score_bucket": _score_bucket_label(entry.get("score_target")),
        "catalyst_bucket": _catalyst_bucket_label(metrics),
    }


def _collect_historical_opportunity_rows(
    report_dir: Path, trade_date: str | None
) -> dict[str, Any]:
    historical_report_dirs = [
        report_dir,
        *_discover_recent_historical_report_dirs(report_dir, trade_date),
    ]
    rows: list[dict[str, Any]] = []
    contributing_reports: set[str] = set()

    for historical_report_dir in historical_report_dirs:
        for snapshot_path in _iter_selection_snapshot_paths(historical_report_dir):
            snapshot = _load_json(snapshot_path)
            snapshot_trade_date = _normalize_trade_date(
                snapshot.get("trade_date") or snapshot_path.parent.name
            )
            if trade_date and snapshot_trade_date and snapshot_trade_date >= trade_date:
                continue
            selection_targets = snapshot.get("selection_targets") or {}
            for selection_entry in selection_targets.values():
                opportunity_entry = _extract_short_trade_opportunity_entry(
                    dict(selection_entry)
                )
                if opportunity_entry is None:
                    continue
                rows.append(
                    {
                        **opportunity_entry,
                        "trade_date": snapshot_trade_date,
                        "report_dir": str(historical_report_dir),
                        "snapshot_path": str(snapshot_path),
                    }
                )
                contributing_reports.add(str(historical_report_dir))

    rows.sort(
        key=lambda row: (row.get("trade_date") or "", row.get("ticker") or ""),
        reverse=True,
    )
    return {
        "rows": rows,
        "historical_report_dirs": historical_report_dirs,
        "contributing_report_count": len(contributing_reports),
    }


def _collect_historical_watch_candidate_rows(
    report_dir: Path, trade_date: str | None
) -> dict[str, Any]:
    historical_report_dirs = [
        report_dir,
        *_discover_recent_historical_report_dirs(report_dir, trade_date),
    ]
    rows: list[dict[str, Any]] = []
    contributing_reports: set[str] = set()
    family_counts = {
        "selected": 0,
        "near_miss": 0,
        "opportunity_pool": 0,
        "research_upside_radar": 0,
        "catalyst_theme": 0,
    }

    for historical_report_dir in historical_report_dirs:
        for snapshot_path in _iter_selection_snapshot_paths(historical_report_dir):
            snapshot = _load_json(snapshot_path)
            snapshot_trade_date = _normalize_trade_date(
                snapshot.get("trade_date") or snapshot_path.parent.name
            )
            if trade_date and snapshot_trade_date and snapshot_trade_date >= trade_date:
                continue
            _collect_watch_candidate_rows_from_selection_targets(
                rows=rows,
                family_counts=family_counts,
                contributing_reports=contributing_reports,
                historical_report_dir=historical_report_dir,
                snapshot_path=snapshot_path,
                snapshot_trade_date=snapshot_trade_date,
                selection_targets=snapshot.get("selection_targets") or {},
            )
            _collect_watch_candidate_rows_from_catalyst_entries(
                rows=rows,
                family_counts=family_counts,
                contributing_reports=contributing_reports,
                historical_report_dir=historical_report_dir,
                snapshot_path=snapshot_path,
                snapshot_trade_date=snapshot_trade_date,
                catalyst_entries=snapshot.get("catalyst_theme_candidates") or [],
            )

    rows.sort(
        key=lambda row: (row.get("trade_date") or "", row.get("ticker") or ""),
        reverse=True,
    )
    return {
        "rows": rows,
        "historical_report_dirs": historical_report_dirs,
        "contributing_report_count": len(contributing_reports),
        "family_counts": family_counts,
    }


def _collect_watch_candidate_rows_from_selection_targets(
    *,
    rows: list[dict[str, Any]],
    family_counts: dict[str, int],
    contributing_reports: set[str],
    historical_report_dir: Path,
    snapshot_path: Path,
    snapshot_trade_date: str | None,
    selection_targets: dict[str, Any],
) -> None:
    history_context = {
        "trade_date": snapshot_trade_date,
        "report_dir": str(historical_report_dir),
        "snapshot_path": str(snapshot_path),
    }
    for selection_entry in selection_targets.values():
        normalized_selection_entry = dict(selection_entry)
        _append_watch_candidate_row(
            rows=rows,
            family_counts=family_counts,
            contributing_reports=contributing_reports,
            report_dir=str(historical_report_dir),
            family=str(
                (_extract_short_trade_entry(normalized_selection_entry) or {}).get(
                    "decision"
                )
                or ""
            ),
            entry=_extract_short_trade_entry(normalized_selection_entry),
            history_context=history_context,
        )
        _append_watch_candidate_row(
            rows=rows,
            family_counts=family_counts,
            contributing_reports=contributing_reports,
            report_dir=str(historical_report_dir),
            family="opportunity_pool",
            entry=_extract_short_trade_opportunity_entry(normalized_selection_entry),
            history_context=history_context,
        )
        _append_watch_candidate_row(
            rows=rows,
            family_counts=family_counts,
            contributing_reports=contributing_reports,
            report_dir=str(historical_report_dir),
            family="research_upside_radar",
            entry=_extract_research_upside_radar_entry(normalized_selection_entry),
            history_context=history_context,
        )


def _collect_watch_candidate_rows_from_catalyst_entries(
    *,
    rows: list[dict[str, Any]],
    family_counts: dict[str, int],
    contributing_reports: set[str],
    historical_report_dir: Path,
    snapshot_path: Path,
    snapshot_trade_date: str | None,
    catalyst_entries: list[dict[str, Any]],
) -> None:
    history_context = {
        "trade_date": snapshot_trade_date,
        "report_dir": str(historical_report_dir),
        "snapshot_path": str(snapshot_path),
    }
    for catalyst_entry in catalyst_entries:
        _append_watch_candidate_row(
            rows=rows,
            family_counts=family_counts,
            contributing_reports=contributing_reports,
            report_dir=str(historical_report_dir),
            family="catalyst_theme",
            entry=_extract_catalyst_theme_entry(dict(catalyst_entry)),
            history_context=history_context,
        )


def _append_watch_candidate_row(
    *,
    rows: list[dict[str, Any]],
    family_counts: dict[str, int],
    contributing_reports: set[str],
    report_dir: str,
    family: str,
    entry: dict[str, Any] | None,
    history_context: dict[str, Any],
) -> None:
    if entry is None:
        return
    rows.append(
        {**_decorate_watch_candidate_history_entry(entry, family), **history_context}
    )
    family_counts[family] = int(family_counts.get(family) or 0) + 1
    contributing_reports.add(report_dir)


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


from src.paper_trading._btst_reporting.pool_classifiers import (
    _demote_weak_near_miss_entries,
    _partition_opportunity_pool_entries,
)


def _append_primary_and_near_miss_recommendations(
    recommendation_lines: list[str],
    *,
    primary_entry: dict[str, Any] | None,
    near_miss_entries: list[dict[str, Any]],
) -> None:
    _append_primary_and_near_miss_recommendations_impl(
        recommendation_lines,
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
        selected_holding_contract_note=_selected_holding_contract_note,
    )


def _append_pool_and_observer_recommendations(
    recommendation_lines: list[str],
    *,
    opportunity_pool_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
) -> None:
    _append_pool_and_observer_recommendations_impl(
        recommendation_lines,
        opportunity_pool_entries=opportunity_pool_entries,
        risky_observer_entries=risky_observer_entries,
        no_history_observer_entries=no_history_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
    )


def _append_opportunity_pool_recommendation_lines(
    recommendation_lines: list[str], *, opportunity_pool_entries: list[dict[str, Any]]
) -> None:
    _append_recommendation_line_if_entries(
        recommendation_lines,
        opportunity_pool_entries,
        prefix="自动扩容候选池为 ",
        suffix="，这些票结构未坏，但还没进入正式名单，只能在盘中新增强度确认后升级。",
    )
    _append_historical_prior_recommendation(
        recommendation_lines,
        entries=opportunity_pool_entries,
        prefix="机会池历史先验参考: ",
    )


def _append_observer_bucket_recommendation_lines(
    recommendation_lines: list[str],
    *,
    risky_observer_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
) -> None:
    _append_recommendation_line_if_entries(
        recommendation_lines,
        risky_observer_entries,
        prefix="高风险观察桶为 ",
        suffix="，这些票更像盘中确认/避免追高对象，不与标准 BTST 机会池混用。",
    )
    _append_recommendation_line_if_entries(
        recommendation_lines,
        no_history_observer_entries,
        prefix="无历史先验观察桶为 ",
        suffix="，这些票暂无可评估历史先验，不再占用标准 BTST 机会池名额，只保留盘中新证据观察。",
    )
    _append_recommendation_line_if_entries(
        recommendation_lines,
        weak_history_pruned_entries,
        prefix="已从标准观察池剔除的低质量样本有 ",
        suffix="，这些名字要么历史兑现接近 0，要么缺少历史先验且当前分数/形态偏弱，不应继续占用明日观察名额。",
    )


def _append_recommendation_line_if_entries(
    recommendation_lines: list[str],
    entries: list[dict[str, Any]],
    *,
    prefix: str,
    suffix: str,
) -> None:
    _append_recommendation_line_if_tickers(
        recommendation_lines,
        [entry["ticker"] for entry in entries],
        prefix=prefix,
        suffix=suffix,
    )


def _append_recommendation_line_if_tickers(
    recommendation_lines: list[str],
    tickers: list[str],
    *,
    prefix: str,
    suffix: str,
) -> None:
    if tickers:
        recommendation_lines.append(prefix + ", ".join(tickers) + suffix)


def _append_historical_prior_recommendation(
    recommendation_lines: list[str],
    *,
    entries: list[dict[str, Any]],
    prefix: str,
) -> None:
    historical_prior_lines = [
        f"{entry['ticker']}={entry.get('historical_prior', {}).get('summary')}"
        for entry in entries
        if (entry.get("historical_prior") or {}).get("summary")
    ]
    if historical_prior_lines:
        recommendation_lines.append(prefix + "；".join(historical_prior_lines))


def _append_research_and_shadow_recommendations(
    recommendation_lines: list[str],
    *,
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    excluded_research_entries: list[dict[str, Any]],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_research_and_shadow_recommendations_impl(
        recommendation_lines,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        excluded_research_entries=excluded_research_entries,
        upstream_shadow_entries=upstream_shadow_entries,
    )


def _summarize_historical_opportunity_rows(
    rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
) -> dict[str, Any]:
    summary_state = _build_empty_historical_opportunity_summary_state()

    for row in rows:
        evaluated_row = _evaluate_historical_opportunity_row(row, price_cache)
        if evaluated_row is None:
            continue
        _accumulate_historical_opportunity_summary(summary_state, evaluated_row)

    next_high_hit_rate, next_close_positive_rate = (
        _compute_historical_opportunity_rates(
            summary_state["evaluated_rows"], summary_state
        )
    )
    return _build_historical_opportunity_summary_payload(
        rows=rows,
        evaluated_rows=summary_state["evaluated_rows"],
        next_open_values=summary_state["next_open_values"],
        next_high_values=summary_state["next_high_values"],
        next_close_values=summary_state["next_close_values"],
        next_open_to_close_values=summary_state["next_open_to_close_values"],
        next_high_hit_rate=next_high_hit_rate,
        next_close_positive_rate=next_close_positive_rate,
    )


def _build_empty_historical_opportunity_summary_state() -> dict[str, Any]:
    return {
        "evaluated_rows": [],
        "next_open_values": [],
        "next_high_values": [],
        "next_close_values": [],
        "next_open_to_close_values": [],
        "hit_count": 0,
        "positive_close_count": 0,
    }


def _accumulate_historical_opportunity_summary(
    summary_state: dict[str, Any], evaluated_row: dict[str, Any]
) -> None:
    next_open_return = evaluated_row.get("next_open_return")
    next_high_return = evaluated_row.get("next_high_return")
    next_close_return = evaluated_row.get("next_close_return")
    next_open_to_close_return = evaluated_row.get("next_open_to_close_return")
    if next_open_return is not None:
        summary_state["next_open_values"].append(next_open_return)
    if next_high_return is not None:
        summary_state["next_high_values"].append(next_high_return)
        if next_high_return >= OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD:
            summary_state["hit_count"] += 1
    if next_close_return is not None:
        summary_state["next_close_values"].append(next_close_return)
        if next_close_return > 0:
            summary_state["positive_close_count"] += 1
    if next_open_to_close_return is not None:
        summary_state["next_open_to_close_values"].append(next_open_to_close_return)
    summary_state["evaluated_rows"].append(evaluated_row)


def _compute_historical_opportunity_rates(
    evaluated_rows: list[dict[str, Any]],
    summary_state: dict[str, Any],
) -> tuple[float | None, float | None]:
    evaluable_count = len(evaluated_rows)
    next_high_hit_rate = (
        round(summary_state["hit_count"] / evaluable_count, 4)
        if evaluable_count
        else None
    )
    next_close_positive_rate = (
        round(summary_state["positive_close_count"] / evaluable_count, 4)
        if evaluable_count
        else None
    )
    return next_high_hit_rate, next_close_positive_rate


def _evaluate_historical_opportunity_row(
    row: dict[str, Any],
    price_cache: dict[tuple[str, str], pd.DataFrame],
) -> dict[str, Any] | None:
    trade_date = str(row.get("trade_date") or "")
    ticker = str(row.get("ticker") or "")
    if not trade_date or not ticker:
        return None
    outcome = _extract_next_day_outcome(ticker, trade_date, price_cache)
    if outcome.get("data_status") != "ok":
        return None
    return {
        "trade_date": trade_date,
        "ticker": ticker,
        "candidate_source": row.get("candidate_source"),
        "score_target": _round_or_none(row.get("score_target")),
        "next_open_return": _round_or_none(outcome.get("next_open_return")),
        "next_high_return": _round_or_none(outcome.get("next_high_return")),
        "next_close_return": _round_or_none(outcome.get("next_close_return")),
        "next_open_to_close_return": _round_or_none(
            outcome.get("next_open_to_close_return")
        ),
    }


def _build_historical_opportunity_summary_payload(
    *,
    rows: list[dict[str, Any]],
    evaluated_rows: list[dict[str, Any]],
    next_open_values: list[float],
    next_high_values: list[float],
    next_close_values: list[float],
    next_open_to_close_values: list[float],
    next_high_hit_rate: float | None,
    next_close_positive_rate: float | None,
) -> dict[str, Any]:
    return {
        "sample_count": len(rows),
        "evaluable_count": len(evaluated_rows),
        "next_high_hit_threshold": OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
        "next_open_return_mean": _mean_or_none(next_open_values),
        "next_high_hit_rate_at_threshold": next_high_hit_rate,
        "next_close_positive_rate": next_close_positive_rate,
        "next_high_return_mean": _mean_or_none(next_high_values),
        "next_close_return_mean": _mean_or_none(next_close_values),
        "next_open_to_close_return_mean": _mean_or_none(next_open_to_close_values),
        "recent_examples": evaluated_rows[:3],
    }


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
    execution_quality = _classify_execution_quality_prior(
        stats.get("next_open_return_mean"),
        stats.get("next_open_to_close_return_mean"),
        stats.get("next_high_return_mean"),
        stats.get("next_close_return_mean"),
        stats.get("next_high_hit_rate_at_threshold"),
        stats.get("next_close_positive_rate"),
        int(stats.get("evaluable_count") or 0),
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


def _build_watch_candidate_historical_prior(
    entry: dict[str, Any],
    historical_rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
    *,
    family: str,
) -> dict[str, Any]:
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
    execution_quality = _classify_execution_quality_prior(
        stats.get("next_open_return_mean"),
        stats.get("next_open_to_close_return_mean"),
        stats.get("next_high_return_mean"),
        stats.get("next_close_return_mean"),
        stats.get("next_high_hit_rate_at_threshold"),
        stats.get("next_close_positive_rate"),
        int(stats.get("evaluable_count") or 0),
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


def _build_btst_candidate_historical_context(
    historical_payload: dict[str, Any],
) -> dict[str, Any]:
    family_counts = dict(historical_payload.get("family_counts") or {})
    return {
        "lookback_report_limit": OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
        "historical_report_count": int(
            historical_payload.get("contributing_report_count") or 0
        ),
        "historical_btst_candidate_count": len(historical_payload.get("rows") or []),
        "historical_watch_candidate_count": len(historical_payload.get("rows") or []),
        "historical_selected_candidate_count": int(family_counts.get("selected") or 0),
        "historical_near_miss_candidate_count": int(
            family_counts.get("near_miss") or 0
        ),
        "historical_opportunity_candidate_count": int(
            family_counts.get("opportunity_pool") or 0
        ),
        "historical_research_upside_radar_count": int(
            family_counts.get("research_upside_radar") or 0
        ),
        "historical_catalyst_theme_count": int(
            family_counts.get("catalyst_theme") or 0
        ),
        "next_high_hit_threshold": OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
    }


def _apply_historical_prior_to_entries(
    entries: list[dict[str, Any]],
    *,
    historical_rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
    family: str,
) -> list[dict[str, Any]]:
    return [
        _apply_historical_prior_to_entry(
            entry=entry,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family=family,
        )
        for entry in entries
    ]


def _apply_historical_prior_to_entry(
    *,
    entry: dict[str, Any],
    historical_rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
    family: str,
) -> dict[str, Any]:
    enriched_entry = dict(entry)
    enriched_entry.update(
        _merge_entry_historical_prior(
            enriched_entry,
            _build_watch_candidate_historical_prior(
                enriched_entry,
                historical_rows,
                price_cache,
                family=family,
            ),
        )
    )
    return enriched_entry


def _enrich_btst_brief_entries_with_history(
    *,
    report_dir: Path,
    actual_trade_date: str | None,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    default_context = _build_empty_btst_candidate_historical_context()
    no_history_observer_entries, risky_observer_entries, weak_history_pruned_entries = (
        _build_empty_brief_history_observer_groups()
    )
    if not (
        selected_entries
        or near_miss_entries
        or opportunity_pool_entries
        or research_upside_radar_entries
        or catalyst_theme_entries
    ):
        return _build_empty_brief_history_enrichment_result(
            selected_entries,
            near_miss_entries,
            opportunity_pool_entries,
            research_upside_radar_entries,
            catalyst_theme_entries,
            no_history_observer_entries,
            risky_observer_entries,
            weak_history_pruned_entries,
            default_context,
        )

    historical_payload = _collect_historical_watch_candidate_rows(
        report_dir, actual_trade_date
    )
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        research_upside_radar_entries,
        catalyst_theme_entries,
    ) = _apply_historical_prior_to_brief_entry_groups(
        historical_rows=historical_payload["rows"],
        price_cache=price_cache,
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
    )

    (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
    ) = _postprocess_brief_history_enriched_groups(
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
    )
    _sort_brief_history_enriched_groups(
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
    )

    return (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        research_upside_radar_entries,
        catalyst_theme_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
        _build_btst_candidate_historical_context(historical_payload),
    )


def _build_empty_btst_candidate_historical_context() -> dict[str, Any]:
    return {
        "lookback_report_limit": OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
        "historical_report_count": 0,
        "historical_btst_candidate_count": 0,
        "historical_watch_candidate_count": 0,
        "historical_selected_candidate_count": 0,
        "historical_near_miss_candidate_count": 0,
        "historical_opportunity_candidate_count": 0,
        "historical_research_upside_radar_count": 0,
        "historical_catalyst_theme_count": 0,
        "next_high_hit_threshold": OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
    }


def _build_empty_brief_history_observer_groups() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    return [], [], []


def _build_empty_brief_history_enrichment_result(
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    default_context: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    return (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        research_upside_radar_entries,
        catalyst_theme_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
        default_context,
    )


def _postprocess_brief_history_enriched_groups(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    selected_entries, near_miss_entries, opportunity_pool_entries = (
        _apply_and_reclassify_brief_history_groups(
            selected_entries=selected_entries,
            near_miss_entries=near_miss_entries,
            opportunity_pool_entries=opportunity_pool_entries,
        )
    )
    (
        near_miss_entries,
        opportunity_pool_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
    ) = _demote_and_partition_brief_history_groups(
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
    )
    return (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
    )


def _apply_and_reclassify_brief_history_groups(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    selected_entries, near_miss_entries, opportunity_pool_entries = (
        _apply_execution_quality_modes_to_brief_groups(
            selected_entries=selected_entries,
            near_miss_entries=near_miss_entries,
            opportunity_pool_entries=opportunity_pool_entries,
        )
    )
    return _reclassify_selected_execution_quality_entries(
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
    )


def _demote_and_partition_brief_history_groups(
    *,
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    near_miss_entries, opportunity_pool_entries = _demote_weak_near_miss_entries(
        near_miss_entries,
        opportunity_pool_entries,
    )
    (
        opportunity_pool_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
    ) = _partition_opportunity_pool_entries(
        opportunity_pool_entries,
    )
    return (
        near_miss_entries,
        opportunity_pool_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
    )


def _sort_brief_history_enriched_groups(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
) -> None:
    selected_entries.sort(key=_historical_execution_entry_sort_key)
    near_miss_entries.sort(key=_historical_execution_entry_sort_key)
    opportunity_pool_entries.sort(key=_opportunity_pool_execution_sort_key)
    no_history_observer_entries.sort(key=_opportunity_pool_execution_sort_key)
    risky_observer_entries.sort(key=_opportunity_pool_execution_sort_key)
    research_upside_radar_entries.sort(key=_research_historical_entry_sort_key)
    catalyst_theme_entries.sort(key=_historical_execution_entry_sort_key)


def _apply_historical_prior_to_brief_entry_groups(
    *,
    historical_rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    return (
        _apply_historical_prior_to_entries(
            selected_entries,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family="selected",
        ),
        _apply_historical_prior_to_entries(
            near_miss_entries,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family="near_miss",
        ),
        _apply_historical_prior_to_entries(
            opportunity_pool_entries,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family="opportunity_pool",
        ),
        _apply_historical_prior_to_entries(
            research_upside_radar_entries,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family="research_upside_radar",
        ),
        _apply_historical_prior_to_entries(
            catalyst_theme_entries,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family="catalyst_theme",
        ),
    )


def _apply_execution_quality_modes_to_brief_groups(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        [_apply_execution_quality_entry_mode(entry) for entry in selected_entries],
        [_apply_execution_quality_entry_mode(entry) for entry in near_miss_entries],
        [
            _apply_execution_quality_entry_mode(entry)
            for entry in opportunity_pool_entries
        ],
    )


def _build_btst_recommendation_lines(
    *,
    primary_entry: dict[str, Any] | None,
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    excluded_research_entries: list[dict[str, Any]],
    upstream_shadow_entries: list[dict[str, Any]],
) -> list[str]:
    recommendation_lines: list[str] = []
    _append_btst_recommendation_line_groups(
        recommendation_lines=recommendation_lines,
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        risky_observer_entries=risky_observer_entries,
        no_history_observer_entries=no_history_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        excluded_research_entries=excluded_research_entries,
        upstream_shadow_entries=upstream_shadow_entries,
    )
    return recommendation_lines


def _append_btst_recommendation_line_groups(
    *,
    recommendation_lines: list[str],
    primary_entry: dict[str, Any] | None,
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    excluded_research_entries: list[dict[str, Any]],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_primary_and_near_miss_recommendations(
        recommendation_lines,
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
    )
    _append_pool_and_observer_recommendations(
        recommendation_lines,
        opportunity_pool_entries=opportunity_pool_entries,
        risky_observer_entries=risky_observer_entries,
        no_history_observer_entries=no_history_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
    )
    _append_research_and_shadow_recommendations(
        recommendation_lines,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        excluded_research_entries=excluded_research_entries,
        upstream_shadow_entries=upstream_shadow_entries,
    )


def analyze_btst_next_day_trade_brief(
    input_path: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    brief_inputs = _load_btst_brief_inputs(input_path=input_path, trade_date=trade_date)
    snapshot_path = brief_inputs["snapshot_path"]
    report_dir = brief_inputs["report_dir"]
    snapshot = brief_inputs["snapshot"]
    session_summary_path = brief_inputs["session_summary_path"]
    session_summary = brief_inputs["session_summary"]
    actual_trade_date = brief_inputs["actual_trade_date"]
    selection_targets = brief_inputs["selection_targets"]
    candidate_groups = _build_btst_brief_candidate_groups(
        snapshot=snapshot, selection_targets=selection_targets
    )
    brief_candidate_context = _build_btst_brief_candidate_context(candidate_groups)
    selected_entries = brief_candidate_context["selected_entries"]
    near_miss_entries = brief_candidate_context["near_miss_entries"]
    opportunity_pool_entries = brief_candidate_context["opportunity_pool_entries"]
    research_upside_radar_entries = brief_candidate_context[
        "research_upside_radar_entries"
    ]
    catalyst_theme_entries = brief_candidate_context["catalyst_theme_entries"]
    catalyst_theme_shadow_entries = brief_candidate_context[
        "catalyst_theme_shadow_entries"
    ]
    brief_frontier_context = _build_btst_brief_frontier_context(
        report_dir=report_dir,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        selection_targets=selection_targets,
        replay_input=brief_inputs["replay_input"],
    )
    history_context = _build_btst_brief_history_context(
        report_dir=report_dir,
        actual_trade_date=actual_trade_date,
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
    )
    selected_entries = history_context["selected_entries"]
    near_miss_entries = history_context["near_miss_entries"]
    opportunity_pool_entries = history_context["opportunity_pool_entries"]
    research_upside_radar_entries = history_context["research_upside_radar_entries"]
    catalyst_theme_entries = history_context["catalyst_theme_entries"]
    no_history_observer_entries = history_context["no_history_observer_entries"]
    risky_observer_entries = history_context["risky_observer_entries"]
    weak_history_pruned_entries = history_context["weak_history_pruned_entries"]
    btst_candidate_historical_context = history_context[
        "btst_candidate_historical_context"
    ]

    excluded_research_entries = _build_excluded_research_entries(selection_targets)
    recommendation_lines = _build_btst_brief_recommendation_lines(
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        risky_observer_entries=risky_observer_entries,
        no_history_observer_entries=no_history_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        excluded_research_entries=excluded_research_entries,
        brief_frontier_context=brief_frontier_context,
    )

    return _build_btst_next_day_trade_brief_payload(
        report_dir=report_dir,
        snapshot_path=snapshot_path,
        session_summary_path=session_summary_path,
        actual_trade_date=actual_trade_date,
        next_trade_date=next_trade_date,
        snapshot=snapshot,
        session_summary=session_summary,
        selection_targets=selection_targets,
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        btst_candidate_historical_context=btst_candidate_historical_context,
        excluded_research_entries=excluded_research_entries,
        recommendation_lines=recommendation_lines,
        brief_frontier_context=brief_frontier_context,
    )


def _build_btst_brief_history_context(
    *,
    report_dir: Path,
    actual_trade_date: str | None,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        research_upside_radar_entries,
        catalyst_theme_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
        btst_candidate_historical_context,
    ) = _enrich_btst_brief_entries_with_history(
        report_dir=report_dir,
        actual_trade_date=actual_trade_date,
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
    )
    return {
        "selected_entries": selected_entries,
        "near_miss_entries": near_miss_entries,
        "opportunity_pool_entries": opportunity_pool_entries,
        "research_upside_radar_entries": research_upside_radar_entries,
        "catalyst_theme_entries": catalyst_theme_entries,
        "no_history_observer_entries": no_history_observer_entries,
        "risky_observer_entries": risky_observer_entries,
        "weak_history_pruned_entries": weak_history_pruned_entries,
        "btst_candidate_historical_context": btst_candidate_historical_context,
    }


def _build_btst_brief_candidate_context(
    candidate_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "selected_entries": candidate_groups["selected_entries"],
        "near_miss_entries": candidate_groups["near_miss_entries"],
        "opportunity_pool_entries": candidate_groups["opportunity_pool_entries"],
        "research_upside_radar_entries": candidate_groups[
            "research_upside_radar_entries"
        ],
        "catalyst_theme_entries": candidate_groups["catalyst_theme_entries"],
        "catalyst_theme_shadow_entries": candidate_groups[
            "catalyst_theme_shadow_entries"
        ],
    }


def _build_btst_brief_recommendation_lines(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    excluded_research_entries: list[dict[str, Any]],
    brief_frontier_context: dict[str, Any],
) -> list[str]:
    primary_entry = selected_entries[0] if selected_entries else None
    return _build_btst_recommendation_lines(
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        risky_observer_entries=risky_observer_entries,
        no_history_observer_entries=no_history_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_frontier_priority=brief_frontier_context[
            "catalyst_theme_frontier_priority"
        ],
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        excluded_research_entries=excluded_research_entries,
        upstream_shadow_entries=brief_frontier_context["upstream_shadow_entries"],
    )


def _build_btst_brief_frontier_context(
    *,
    report_dir: Path,
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    selection_targets: dict[str, Any],
    replay_input: dict[str, Any],
) -> dict[str, Any]:
    catalyst_theme_frontier_summary = _load_catalyst_theme_frontier_summary(report_dir)
    catalyst_theme_frontier_priority = _build_catalyst_theme_frontier_priority(
        catalyst_theme_frontier_summary, catalyst_theme_shadow_entries
    )
    upstream_shadow_entries = _build_upstream_shadow_entries(
        selection_targets=selection_targets,
        replay_input=replay_input,
    )
    return {
        "catalyst_theme_frontier_summary": catalyst_theme_frontier_summary,
        "catalyst_theme_frontier_priority": catalyst_theme_frontier_priority,
        "upstream_shadow_entries": upstream_shadow_entries,
        "upstream_shadow_summary": _build_upstream_shadow_summary(
            upstream_shadow_entries
        ),
    }


def _build_btst_next_day_trade_brief_payload(
    *,
    report_dir: Path,
    snapshot_path: Path,
    session_summary_path: Path,
    actual_trade_date: str | None,
    next_trade_date: str | None,
    snapshot: dict[str, Any],
    session_summary: dict[str, Any],
    selection_targets: dict[str, Any],
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    btst_candidate_historical_context: dict[str, Any],
    excluded_research_entries: list[dict[str, Any]],
    recommendation_lines: list[str],
    brief_frontier_context: dict[str, Any],
) -> dict[str, Any]:
    primary_entry = selected_entries[0] if selected_entries else None
    return {
        **_build_btst_next_day_trade_brief_metadata(
            report_dir=report_dir,
            snapshot_path=snapshot_path,
            session_summary_path=session_summary_path,
            actual_trade_date=actual_trade_date,
            next_trade_date=next_trade_date,
            snapshot=snapshot,
            session_summary=session_summary,
        ),
        **_build_btst_next_day_trade_brief_content(
            snapshot=snapshot,
            selection_targets=selection_targets,
            primary_entry=primary_entry,
            selected_entries=selected_entries,
            near_miss_entries=near_miss_entries,
            opportunity_pool_entries=opportunity_pool_entries,
            no_history_observer_entries=no_history_observer_entries,
            risky_observer_entries=risky_observer_entries,
            weak_history_pruned_entries=weak_history_pruned_entries,
            research_upside_radar_entries=research_upside_radar_entries,
            catalyst_theme_entries=catalyst_theme_entries,
            catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
            btst_candidate_historical_context=btst_candidate_historical_context,
            excluded_research_entries=excluded_research_entries,
            recommendation_lines=recommendation_lines,
            brief_frontier_context=brief_frontier_context,
        ),
    }


def _build_btst_next_day_trade_brief_content(
    *,
    snapshot: dict[str, Any],
    selection_targets: dict[str, Any],
    primary_entry: dict[str, Any] | None,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    btst_candidate_historical_context: dict[str, Any],
    excluded_research_entries: list[dict[str, Any]],
    recommendation_lines: list[str],
    brief_frontier_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "summary": _build_btst_brief_summary(
            snapshot=snapshot,
            selection_targets=selection_targets,
            selected_entries=selected_entries,
            near_miss_entries=near_miss_entries,
            opportunity_pool_entries=opportunity_pool_entries,
            no_history_observer_entries=no_history_observer_entries,
            risky_observer_entries=risky_observer_entries,
            weak_history_pruned_entries=weak_history_pruned_entries,
            research_upside_radar_entries=research_upside_radar_entries,
            catalyst_theme_entries=catalyst_theme_entries,
            catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
            catalyst_theme_frontier_priority=brief_frontier_context[
                "catalyst_theme_frontier_priority"
            ],
            upstream_shadow_summary=brief_frontier_context["upstream_shadow_summary"],
        ),
        **_build_btst_next_day_trade_brief_sections(
            primary_entry=primary_entry,
            selected_entries=selected_entries,
            near_miss_entries=near_miss_entries,
            opportunity_pool_entries=opportunity_pool_entries,
            no_history_observer_entries=no_history_observer_entries,
            risky_observer_entries=risky_observer_entries,
            weak_history_pruned_entries=weak_history_pruned_entries,
            research_upside_radar_entries=research_upside_radar_entries,
            catalyst_theme_entries=catalyst_theme_entries,
            catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
            btst_candidate_historical_context=btst_candidate_historical_context,
            excluded_research_entries=excluded_research_entries,
            brief_frontier_context=brief_frontier_context,
        ),
        "recommendation": " ".join(recommendation_lines),
    }


def _build_btst_next_day_trade_brief_metadata(
    *,
    report_dir: Path,
    snapshot_path: Path,
    session_summary_path: Path,
    actual_trade_date: str | None,
    next_trade_date: str | None,
    snapshot: dict[str, Any],
    session_summary: dict[str, Any],
) -> dict[str, Any]:
    replay_input_path = _resolve_replay_input_path(snapshot_path)
    return {
        "report_dir": str(report_dir),
        "snapshot_path": str(snapshot_path),
        "replay_input_path": str(replay_input_path)
        if replay_input_path.exists()
        else None,
        "session_summary_path": str(session_summary_path)
        if session_summary_path.exists()
        else None,
        "trade_date": actual_trade_date,
        "next_trade_date": _normalize_trade_date(next_trade_date),
        "target_mode": snapshot.get("target_mode"),
        "selection_target": (session_summary.get("plan_generation") or {}).get(
            "selection_target"
        )
        or snapshot.get("target_mode"),
    }


def _build_btst_next_day_trade_brief_sections(
    *,
    primary_entry: dict[str, Any] | None,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    btst_candidate_historical_context: dict[str, Any],
    excluded_research_entries: list[dict[str, Any]],
    brief_frontier_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "primary_entry": primary_entry,
        "selected_entries": selected_entries,
        "near_miss_entries": near_miss_entries,
        "opportunity_pool_entries": opportunity_pool_entries,
        "no_history_observer_entries": no_history_observer_entries,
        "risky_observer_entries": risky_observer_entries,
        "weak_history_pruned_entries": weak_history_pruned_entries,
        "research_upside_radar_entries": research_upside_radar_entries,
        "catalyst_theme_entries": catalyst_theme_entries,
        "catalyst_theme_shadow_entries": catalyst_theme_shadow_entries,
        "catalyst_theme_frontier_summary": brief_frontier_context[
            "catalyst_theme_frontier_summary"
        ],
        "catalyst_theme_frontier_priority": brief_frontier_context[
            "catalyst_theme_frontier_priority"
        ],
        "upstream_shadow_entries": brief_frontier_context["upstream_shadow_entries"],
        "upstream_shadow_summary": brief_frontier_context["upstream_shadow_summary"],
        "btst_candidate_historical_context": btst_candidate_historical_context,
        "watch_candidate_historical_context": btst_candidate_historical_context,
        "opportunity_pool_historical_context": btst_candidate_historical_context,
        "excluded_research_entries": excluded_research_entries,
    }


def _load_btst_brief_inputs(
    input_path: str | Path, trade_date: str | None
) -> dict[str, Any]:
    snapshot_path, report_dir = _resolve_snapshot_path(input_path, trade_date)
    snapshot = _load_json(snapshot_path)
    replay_input = _load_selection_replay_input(snapshot_path)
    session_summary_path = report_dir / "session_summary.json"
    return {
        "snapshot_path": snapshot_path,
        "report_dir": report_dir,
        "snapshot": snapshot,
        "replay_input": replay_input,
        "session_summary_path": session_summary_path,
        "session_summary": _load_json(session_summary_path)
        if session_summary_path.exists()
        else {},
        "actual_trade_date": _normalize_trade_date(
            snapshot.get("trade_date") or trade_date
        ),
        "selection_targets": snapshot.get("selection_targets") or {},
    }


def _build_btst_brief_candidate_groups(
    *, snapshot: dict[str, Any], selection_targets: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    short_trade_entries = _build_btst_brief_short_trade_entries(selection_targets)
    opportunity_pool_entries = _build_btst_brief_opportunity_pool_entries(
        selection_targets
    )
    research_upside_radar_entries = _build_btst_brief_research_upside_radar_entries(
        selection_targets
    )
    catalyst_theme_entries = _build_btst_brief_catalyst_theme_entries(snapshot)
    catalyst_theme_shadow_entries = _build_btst_brief_catalyst_theme_shadow_entries(
        snapshot
    )
    return {
        "selected_entries": [
            entry for entry in short_trade_entries if entry["decision"] == "selected"
        ],
        "near_miss_entries": [
            entry for entry in short_trade_entries if entry["decision"] == "near_miss"
        ],
        "opportunity_pool_entries": opportunity_pool_entries[
            :OPPORTUNITY_POOL_MAX_ENTRIES
        ],
        "research_upside_radar_entries": research_upside_radar_entries[
            :RESEARCH_UPSIDE_RADAR_MAX_ENTRIES
        ],
        "catalyst_theme_entries": catalyst_theme_entries[:CATALYST_THEME_MAX_ENTRIES],
        "catalyst_theme_shadow_entries": catalyst_theme_shadow_entries[
            :CATALYST_THEME_SHADOW_MAX_ENTRIES
        ],
    }


def _build_btst_brief_short_trade_entries(
    selection_targets: dict[str, Any],
) -> list[dict[str, Any]]:
    short_trade_entries = [
        candidate
        for candidate in (
            _extract_short_trade_entry(entry) for entry in selection_targets.values()
        )
        if candidate is not None
    ]
    short_trade_entries.sort(
        key=lambda entry: (
            0 if entry["decision"] == "selected" else 1,
            -(entry.get("score_target") or 0.0),
            entry.get("ticker") or "",
        )
    )
    return short_trade_entries


def _build_btst_brief_opportunity_pool_entries(
    selection_targets: dict[str, Any],
) -> list[dict[str, Any]]:
    opportunity_pool_entries = [
        candidate
        for candidate in (
            _extract_short_trade_opportunity_entry(entry)
            for entry in selection_targets.values()
        )
        if candidate is not None
    ]
    opportunity_pool_entries.sort(
        key=lambda entry: (
            entry.get("score_gap_to_near_miss")
            if entry.get("score_gap_to_near_miss") is not None
            else 999.0,
            -(entry.get("score_target") or 0.0),
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            -_as_float((entry.get("metrics") or {}).get("breakout_freshness")),
            entry.get("ticker") or "",
        )
    )
    return opportunity_pool_entries


def _build_btst_brief_research_upside_radar_entries(
    selection_targets: dict[str, Any],
) -> list[dict[str, Any]]:
    research_upside_radar_entries = [
        candidate
        for candidate in (
            _extract_research_upside_radar_entry(entry)
            for entry in selection_targets.values()
        )
        if candidate is not None
    ]
    research_upside_radar_entries.sort(
        key=lambda entry: (
            -(entry.get("research_score_target") or 0.0),
            -(entry.get("score_target") or 0.0),
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            entry.get("ticker") or "",
        )
    )
    return research_upside_radar_entries


def _build_btst_brief_catalyst_theme_entries(
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    catalyst_theme_entries = [
        candidate
        for candidate in (
            _extract_catalyst_theme_entry(entry)
            for entry in (snapshot.get("catalyst_theme_candidates") or [])
        )
        if candidate is not None
    ]
    catalyst_theme_entries.sort(
        key=lambda entry: (
            -(entry.get("score_target") or 0.0),
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            -_as_float((entry.get("metrics") or {}).get("sector_resonance")),
            entry.get("ticker") or "",
        )
    )
    return catalyst_theme_entries


def _build_btst_brief_catalyst_theme_shadow_entries(
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    catalyst_theme_shadow_entries = [
        candidate
        for candidate in (
            _extract_catalyst_theme_shadow_entry(entry)
            for entry in (snapshot.get("catalyst_theme_shadow_candidates") or [])
        )
        if candidate is not None
    ]
    catalyst_theme_shadow_entries.sort(
        key=lambda entry: (
            -(entry.get("score_target") or 0.0),
            entry.get("total_shortfall")
            if entry.get("total_shortfall") is not None
            else 999.0,
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            entry.get("ticker") or "",
        )
    )
    return catalyst_theme_shadow_entries


def _build_upstream_shadow_entries(
    *, selection_targets: dict[str, Any], replay_input: dict[str, Any]
) -> list[dict[str, Any]]:
    supplemental_short_trade_entry_by_ticker = (
        _build_supplemental_short_trade_entry_map(replay_input)
    )
    upstream_shadow_entries_by_ticker = _build_upstream_shadow_entry_map(
        selection_targets=selection_targets,
        supplemental_short_trade_entry_by_ticker=supplemental_short_trade_entry_by_ticker,
    )
    _merge_replay_only_upstream_shadow_entries(
        upstream_shadow_entries_by_ticker, replay_input
    )
    upstream_shadow_entries = list(upstream_shadow_entries_by_ticker.values())
    upstream_shadow_entries.sort(
        key=lambda entry: (
            _shadow_decision_rank(entry.get("decision")),
            -(entry.get("score_target") or 0.0),
            entry.get("candidate_pool_rank")
            if entry.get("candidate_pool_rank") is not None
            else 999999,
            entry.get("ticker") or "",
        )
    )
    return upstream_shadow_entries


def _build_supplemental_short_trade_entry_map(
    replay_input: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        str(entry.get("ticker") or ""): dict(entry)
        for entry in list(replay_input.get("supplemental_short_trade_entries") or [])
        if entry.get("ticker")
    }


def _build_upstream_shadow_entry_map(
    *,
    selection_targets: dict[str, Any],
    supplemental_short_trade_entry_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(candidate.get("ticker") or ""): candidate
        for candidate in (
            _extract_upstream_shadow_entry(
                entry,
                supplemental_short_trade_entry_by_ticker.get(
                    str(entry.get("ticker") or "")
                ),
            )
            for entry in selection_targets.values()
        )
        if candidate is not None and candidate.get("ticker")
    }


def _merge_replay_only_upstream_shadow_entries(
    upstream_shadow_entries_by_ticker: dict[str, dict[str, Any]],
    replay_input: dict[str, Any],
) -> None:
    for candidate in (
        _extract_upstream_shadow_replay_only_entry(entry)
        for entry in list(replay_input.get("upstream_shadow_observation_entries") or [])
        if entry.get("ticker")
    ):
        if candidate is None or not candidate.get("ticker"):
            continue
        upstream_shadow_entries_by_ticker.setdefault(
            str(candidate.get("ticker") or ""), candidate
        )


def _build_excluded_research_entries(
    selection_targets: dict[str, Any],
) -> list[dict[str, Any]]:
    excluded_research_entries = [
        candidate
        for candidate in (
            _extract_excluded_research_entry(entry)
            for entry in selection_targets.values()
        )
        if candidate is not None
    ]
    excluded_research_entries.sort(
        key=lambda entry: (
            -(entry.get("research_score_target") or 0.0),
            entry.get("ticker") or "",
        )
    )
    return excluded_research_entries


def _build_btst_brief_summary(
    *,
    snapshot: dict[str, Any],
    selection_targets: dict[str, Any],
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    upstream_shadow_summary: dict[str, Any],
) -> dict[str, Any]:
    dual_target_summary = snapshot.get("dual_target_summary") or {}
    brief_decision_counts = _build_btst_brief_decision_counts(selection_targets)
    return {
        "selection_target_count": _summary_value(
            dual_target_summary, "selection_target_count", len(selection_targets)
        ),
        "short_trade_selected_count": len(selected_entries),
        "short_trade_near_miss_count": len(near_miss_entries),
        "short_trade_blocked_count": _summary_value(
            dual_target_summary,
            "short_trade_blocked_count",
            brief_decision_counts["blocked_count"],
        ),
        "short_trade_rejected_count": _summary_value(
            dual_target_summary,
            "short_trade_rejected_count",
            brief_decision_counts["rejected_count"],
        ),
        "short_trade_opportunity_pool_count": len(opportunity_pool_entries),
        "no_history_observer_count": len(no_history_observer_entries),
        "risky_observer_count": len(risky_observer_entries),
        "weak_history_pruned_count": len(weak_history_pruned_entries),
        "research_upside_radar_count": len(research_upside_radar_entries),
        "catalyst_theme_count": len(catalyst_theme_entries),
        "catalyst_theme_shadow_count": len(catalyst_theme_shadow_entries),
        "catalyst_theme_frontier_promoted_count": len(
            catalyst_theme_frontier_priority.get("promoted_tickers") or []
        ),
        "upstream_shadow_candidate_count": upstream_shadow_summary.get(
            "shadow_candidate_count"
        )
        or 0,
        "upstream_shadow_promotable_count": upstream_shadow_summary.get(
            "promotable_count"
        )
        or 0,
        "research_selected_count": _summary_value(
            dual_target_summary,
            "research_selected_count",
            brief_decision_counts["research_selected_count"],
        ),
    }


def _build_btst_brief_decision_counts(
    selection_targets: dict[str, Any],
) -> dict[str, int]:
    short_trade_decisions = [
        (entry.get("short_trade") or {}).get("decision")
        for entry in selection_targets.values()
        if entry.get("short_trade")
    ]
    return {
        "blocked_count": sum(
            1 for decision in short_trade_decisions if decision == "blocked"
        ),
        "rejected_count": sum(
            1 for decision in short_trade_decisions if decision == "rejected"
        ),
        "research_selected_count": sum(
            1
            for entry in selection_targets.values()
            if (entry.get("research") or {}).get("decision") == "selected"
        ),
    }


def _append_brief_overview_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    historical_context = (
        analysis.get("btst_candidate_historical_context")
        or analysis.get("watch_candidate_historical_context")
        or analysis.get("opportunity_pool_historical_context")
        or {}
    )
    summary = analysis["summary"]
    lines.append("# BTST Next-Day Trade Brief")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- trade_date: {analysis.get('trade_date')}")
    lines.append(f"- next_trade_date: {analysis.get('next_trade_date') or 'n/a'}")
    lines.append(f"- target_mode: {analysis.get('target_mode')}")
    lines.append(f"- selection_target: {analysis.get('selection_target')}")
    lines.append(
        f"- short_trade_selected_count: {summary.get('short_trade_selected_count')}"
    )
    lines.append(
        f"- short_trade_near_miss_count: {summary.get('short_trade_near_miss_count')}"
    )
    lines.append(
        f"- short_trade_blocked_count: {summary.get('short_trade_blocked_count')}"
    )
    lines.append(
        f"- short_trade_rejected_count: {summary.get('short_trade_rejected_count')}"
    )
    lines.append(
        f"- short_trade_opportunity_pool_count: {summary.get('short_trade_opportunity_pool_count')}"
    )
    lines.append(
        f"- no_history_observer_count: {summary.get('no_history_observer_count')}"
    )
    lines.append(
        f"- research_upside_radar_count: {summary.get('research_upside_radar_count')}"
    )
    lines.append(f"- catalyst_theme_count: {summary.get('catalyst_theme_count')}")
    lines.append(
        f"- catalyst_theme_shadow_count: {summary.get('catalyst_theme_shadow_count')}"
    )
    lines.append(
        f"- catalyst_theme_frontier_promoted_count: {summary.get('catalyst_theme_frontier_promoted_count')}"
    )
    lines.append(
        f"- upstream_shadow_candidate_count: {summary.get('upstream_shadow_candidate_count')}"
    )
    lines.append(
        f"- upstream_shadow_promotable_count: {summary.get('upstream_shadow_promotable_count')}"
    )
    lines.append(
        f"- opportunity_pool_historical_report_count: {historical_context.get('historical_report_count')}"
    )
    lines.append(
        f"- btst_candidate_historical_count: {historical_context.get('historical_btst_candidate_count')}"
    )
    lines.append(
        f"- watch_candidate_historical_count: {historical_context.get('historical_watch_candidate_count')}"
    )
    lines.append(
        f"- watch_selected_historical_count: {historical_context.get('historical_selected_candidate_count')}"
    )
    lines.append(
        f"- watch_near_miss_historical_count: {historical_context.get('historical_near_miss_candidate_count')}"
    )
    lines.append(
        f"- opportunity_pool_historical_candidate_count: {historical_context.get('historical_opportunity_candidate_count')}"
    )
    lines.append(
        f"- research_upside_radar_historical_count: {historical_context.get('historical_research_upside_radar_count')}"
    )
    lines.append(
        f"- catalyst_theme_historical_count: {historical_context.get('historical_catalyst_theme_count')}"
    )
    lines.append(
        f"- excluded_research_selected_count: {len(analysis.get('excluded_research_entries') or [])}"
    )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")


def _append_brief_scored_entries_markdown(
    lines: list[str], title: str, entries: list[dict[str, Any]]
) -> None:
    _append_brief_scored_entries_markdown_impl(
        lines,
        title,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
        append_brief_short_trade_metrics=_append_brief_short_trade_metrics,
        append_brief_historical_recent_examples=_append_brief_historical_recent_examples,
        append_gate_status_line=_append_gate_status_line,
        format_float=_format_float,
    )


def _append_brief_ticker_section(
    lines: list[str],
    *,
    title: str,
    entries: list[dict[str, Any]],
    render_entry: Callable[[list[str], dict[str, Any]], None],
) -> None:
    lines.append(f"## {title}")
    if not entries:
        _append_none_block(lines)
        return
    for entry in entries:
        lines.append(f"### {entry['ticker']}")
        render_entry(lines, entry)
        lines.append("")


def _append_brief_historical_prior_fields(
    lines: list[str],
    historical_prior: dict[str, Any],
    *,
    include_summary: bool = True,
    include_monitor_priority: bool = False,
    include_execution_quality: bool = False,
    include_execution_note: bool = False,
) -> None:
    if include_monitor_priority:
        lines.append(
            f"- historical_monitor_priority: {historical_prior.get('monitor_priority') or 'n/a'}"
        )
    if include_summary:
        lines.append(
            f"- historical_summary: {historical_prior.get('summary') or 'n/a'}"
        )
    if include_execution_quality:
        lines.append(
            f"- historical_execution_quality: {historical_prior.get('execution_quality_label') or 'n/a'}"
        )
    if include_execution_note:
        lines.append(
            f"- historical_execution_note: {historical_prior.get('execution_note') or 'n/a'}"
        )


def _append_brief_scored_entry_metrics(
    lines: list[str], metrics: dict[str, Any]
) -> None:
    _append_brief_short_trade_metrics(lines, metrics)


def _append_brief_short_trade_metrics(
    lines: list[str], metrics: dict[str, Any]
) -> None:
    lines.append(
        "- key_metrics: "
        + ", ".join(
            [
                f"breakout={_format_float(metrics.get('breakout_freshness'))}",
                f"trend={_format_float(metrics.get('trend_acceleration'))}",
                f"volume={_format_float(metrics.get('volume_expansion_quality'))}",
                f"close={_format_float(metrics.get('close_strength'))}",
                f"catalyst={_format_float(metrics.get('catalyst_freshness'))}",
            ]
        )
    )


def _append_brief_historical_recent_examples(
    lines: list[str], historical_prior: dict[str, Any]
) -> None:
    recent_examples = historical_prior.get("recent_examples") or []
    if recent_examples:
        lines.append(
            "- historical_recent_examples: "
            + "; ".join(
                f"{sample.get('trade_date')} {sample.get('ticker')} open={_format_float(sample.get('next_open_return'))}, high={_format_float(sample.get('next_high_return'))}, close={_format_float(sample.get('next_close_return'))}"
                for sample in recent_examples
            )
        )


def _append_brief_opportunity_pool_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_opportunity_pool_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
        append_brief_short_trade_metrics=_append_brief_short_trade_metrics,
        append_brief_historical_recent_examples=_append_brief_historical_recent_examples,
        append_gate_status_line=_append_gate_status_line,
        format_float=_format_float,
    )


def _append_gate_status_line(lines: list[str], gate_status: dict[str, Any]) -> None:
    lines.append(
        "- gate_status: "
        + ", ".join(f"{key}={value}" for key, value in gate_status.items())
    )


def _append_brief_observer_lane_markdown(
    lines: list[str],
    title: str,
    entries: list[dict[str, Any]],
    include_execution_note: bool,
) -> None:
    _append_brief_observer_lane_markdown_impl(
        lines,
        title,
        entries,
        include_execution_note,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
    )


def _append_brief_pruned_entries_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_pruned_entries_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
    )


def _append_brief_research_radar_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_research_radar_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
        format_float=_format_float,
    )


def _append_brief_catalyst_theme_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_catalyst_theme_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
        append_gate_status_line=_append_gate_status_line,
        format_float=_format_float,
    )


def _append_brief_catalyst_frontier_markdown(
    lines: list[str], frontier_priority: dict[str, Any]
) -> None:
    _append_brief_catalyst_frontier_markdown_impl(
        lines,
        frontier_priority,
        append_frontier_section=_append_frontier_section,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        format_float=_format_float,
    )


def _append_frontier_priority_summary(
    lines: list[str], frontier_priority: dict[str, Any]
) -> None:
    _append_frontier_priority_summary_impl(
        lines, frontier_priority, format_float=_format_float
    )


def _append_frontier_section(
    lines: list[str],
    frontier_priority: dict[str, Any],
    render_entries: Callable[[list[str], list[dict[str, Any]]], None],
) -> None:
    _append_frontier_section_impl(
        lines,
        frontier_priority,
        render_entries,
        append_none_block_fn=_append_none_block,
        append_frontier_priority_summary_fn=_append_frontier_priority_summary,
        append_frontier_promoted_shadow_none_block_fn=_append_frontier_promoted_shadow_none_block,
    )


def _append_brief_catalyst_shadow_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_catalyst_shadow_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        append_gate_status_line=_append_gate_status_line,
        format_float=_format_float,
    )


def _append_brief_excluded_research_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_excluded_research_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        format_float=_format_float,
    )


def _append_brief_upstream_shadow_markdown(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_brief_upstream_shadow_markdown_impl(
        lines,
        upstream_shadow_summary,
        upstream_shadow_entries,
        append_brief_summary_ticker_section=_append_brief_summary_ticker_section,
        append_upstream_shadow_summary=_append_brief_upstream_shadow_summary,
        append_gate_status_line=_append_gate_status_line,
        format_float=_format_float,
    )


def _append_brief_summary_ticker_section(
    lines: list[str],
    *,
    title: str,
    entries: list[dict[str, Any]],
    append_summary: Callable[[list[str]], None],
    render_entry: Callable[[list[str], dict[str, Any]], None],
) -> None:
    lines.append(f"## {title}")
    if not entries:
        _append_none_block(lines)
        return
    append_summary(lines)
    for entry in entries:
        lines.append(f"### {entry['ticker']}")
        render_entry(lines, entry)
        lines.append("")


def _append_brief_upstream_shadow_summary(
    lines: list[str], upstream_shadow_summary: dict[str, Any]
) -> None:
    _append_upstream_shadow_summary(
        lines,
        upstream_shadow_summary,
        empty_lane_counts_label="none",
    )


def render_btst_next_day_trade_brief_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    _append_brief_overview_markdown(lines, analysis)
    _append_brief_scored_entries_markdown(
        lines, "Selected Entries", list(analysis.get("selected_entries") or [])
    )
    _append_brief_scored_entries_markdown(
        lines, "Near-Miss Watchlist", list(analysis.get("near_miss_entries") or [])
    )
    _append_brief_opportunity_pool_markdown(
        lines, list(analysis.get("opportunity_pool_entries") or [])
    )
    _append_brief_observer_lane_markdown(
        lines,
        "Risky Observer Lane",
        list(analysis.get("risky_observer_entries") or []),
        include_execution_note=True,
    )
    _append_brief_observer_lane_markdown(
        lines,
        "No-History Observer Lane",
        list(analysis.get("no_history_observer_entries") or []),
        include_execution_note=False,
    )
    _append_brief_pruned_entries_markdown(
        lines, list(analysis.get("weak_history_pruned_entries") or [])
    )
    _append_brief_research_radar_markdown(
        lines, list(analysis.get("research_upside_radar_entries") or [])
    )
    _append_brief_catalyst_theme_markdown(
        lines, list(analysis.get("catalyst_theme_entries") or [])
    )
    _append_brief_catalyst_frontier_markdown(
        lines, dict(analysis.get("catalyst_theme_frontier_priority") or {})
    )
    _append_brief_catalyst_shadow_markdown(
        lines, list(analysis.get("catalyst_theme_shadow_entries") or [])
    )
    _append_brief_excluded_research_markdown(
        lines, list(analysis.get("excluded_research_entries") or [])
    )
    _append_brief_upstream_shadow_markdown(
        lines,
        dict(analysis.get("upstream_shadow_summary") or {}),
        list(analysis.get("upstream_shadow_entries") or []),
    )
    _append_brief_source_paths_markdown(lines, analysis)
    return "\n".join(lines) + "\n"


def _append_source_paths_section(
    lines: list[str],
    *,
    report_dir: Any,
    snapshot_path: Any,
    session_summary_path: Any,
    replay_input_path: Any | None = None,
) -> None:
    _append_source_paths_section_impl(
        lines,
        report_dir=report_dir,
        snapshot_path=snapshot_path,
        session_summary_path=session_summary_path,
        replay_input_path=replay_input_path,
    )


def _append_none_block(lines: list[str]) -> None:
    _append_none_block_impl(lines)


def _append_frontier_promoted_shadow_none_block(lines: list[str]) -> None:
    _append_frontier_promoted_shadow_none_block_impl(lines)


def _append_brief_source_paths_markdown(
    lines: list[str], analysis: dict[str, Any]
) -> None:
    _append_source_paths_section(
        lines,
        report_dir=analysis.get("report_dir"),
        snapshot_path=analysis.get("snapshot_path"),
        replay_input_path=analysis.get("replay_input_path"),
        session_summary_path=analysis.get("session_summary_path"),
    )


def _resolve_brief_analysis(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None,
    next_trade_date: str | None,
) -> dict[str, Any]:
    payload = dict(input_path) if isinstance(input_path, dict) else {}

    if not payload:
        resolved_input = Path(input_path).expanduser().resolve()
        if resolved_input.is_file():
            payload = _load_json(resolved_input)
            if "selected_entries" not in payload or "near_miss_entries" not in payload:
                return analyze_btst_next_day_trade_brief(
                    resolved_input,
                    trade_date=trade_date,
                    next_trade_date=next_trade_date,
                )
        else:
            return analyze_btst_next_day_trade_brief(
                resolved_input, trade_date=trade_date, next_trade_date=next_trade_date
            )

    if next_trade_date and not payload.get("next_trade_date"):
        payload["next_trade_date"] = _normalize_trade_date(next_trade_date)

    frontier_summary = dict(payload.get("catalyst_theme_frontier_summary") or {})
    frontier_priority = dict(payload.get("catalyst_theme_frontier_priority") or {})
    if not frontier_summary or not frontier_priority:
        frontier_summary = frontier_summary or _load_catalyst_theme_frontier_summary(
            payload.get("report_dir")
        )
        frontier_priority = (
            frontier_priority
            or _build_catalyst_theme_frontier_priority(
                frontier_summary,
                list(payload.get("catalyst_theme_shadow_entries") or []),
            )
        )
        payload["catalyst_theme_frontier_summary"] = frontier_summary
        payload["catalyst_theme_frontier_priority"] = frontier_priority

    summary = dict(payload.get("summary") or {})
    summary.setdefault(
        "catalyst_theme_frontier_promoted_count",
        len(frontier_priority.get("promoted_tickers") or []),
    )
    payload["summary"] = summary
    payload.setdefault("upstream_shadow_entries", [])
    payload.setdefault(
        "upstream_shadow_summary",
        {
            "shadow_candidate_count": 0,
            "promotable_count": 0,
            "lane_counts": {},
            "decision_counts": {},
            "top_focus_tickers": [],
        },
    )
    return payload


def _selected_action_posture(preferred_entry_mode: str | None) -> tuple[str, list[str]]:
    return _selected_action_posture_impl(preferred_entry_mode)


def _selected_holding_contract_note(
    preferred_entry_mode: str | None, historical_prior: dict[str, Any] | None
) -> str | None:
    return _selected_holding_contract_note_impl(preferred_entry_mode, historical_prior)


def _augment_execution_note(
    preferred_entry_mode: str | None, historical_prior: dict[str, Any] | None
) -> str | None:
    return _augment_execution_note_impl(preferred_entry_mode, historical_prior)


def analyze_btst_premarket_execution_card(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    return _analyze_btst_premarket_execution_card_impl(
        input_path, trade_date=trade_date, next_trade_date=next_trade_date
    )


def _append_premarket_overview_markdown(lines: list[str], card: dict[str, Any]) -> None:
    summary = dict(card.get("summary") or {})
    lines.append("# BTST Premarket Execution Card")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- trade_date: {card.get('trade_date')}")
    lines.append(f"- next_trade_date: {card.get('next_trade_date') or 'n/a'}")
    lines.append(f"- selection_target: {card.get('selection_target')}")
    lines.append(f"- primary_count: {summary.get('primary_count')}")
    lines.append(f"- watch_count: {summary.get('watch_count')}")
    lines.append(f"- opportunity_pool_count: {summary.get('opportunity_pool_count')}")
    lines.append(
        f"- no_history_observer_count: {summary.get('no_history_observer_count')}"
    )
    lines.append(f"- risky_observer_count: {summary.get('risky_observer_count')}")
    lines.append(
        f"- catalyst_theme_frontier_promoted_count: {summary.get('catalyst_theme_frontier_promoted_count')}"
    )
    lines.append(
        f"- catalyst_theme_shadow_count: {summary.get('catalyst_theme_shadow_count')}"
    )
    lines.append(
        f"- upstream_shadow_candidate_count: {summary.get('upstream_shadow_candidate_count')}"
    )
    lines.append(
        f"- upstream_shadow_promotable_count: {summary.get('upstream_shadow_promotable_count')}"
    )
    lines.append(f"- excluded_research_count: {summary.get('excluded_research_count')}")
    lines.append(f"- recommendation: {card.get('recommendation')}")
    lines.append("")


def _append_premarket_action_block(
    lines: list[str], entry: dict[str, Any], *, indexed: int | None = None
) -> None:
    label = f"### {indexed}. {entry.get('ticker')}" if indexed is not None else None
    if label:
        lines.append(label)
    else:
        lines.append(f"- ticker: {entry.get('ticker')}")
    prefix = "- " if label else "- "
    lines.append(f"{prefix}action_tier: {entry.get('action_tier')}")
    lines.append(f"{prefix}execution_posture: {entry.get('execution_posture')}")
    lines.append(f"{prefix}watch_priority: {entry.get('watch_priority')}")
    lines.append(
        f"{prefix}execution_quality_label: {entry.get('execution_quality_label')}"
    )
    lines.append(f"{prefix}preferred_entry_mode: {entry.get('preferred_entry_mode')}")
    lines.append(
        f"{prefix}historical_summary: {(entry.get('historical_prior') or {}).get('summary') or 'n/a'}"
    )
    lines.append(f"{prefix}evidence: {', '.join(entry.get('evidence') or []) or 'n/a'}")
    lines.append("- trigger_rules:")
    lines.extend(f"  - {item}" for item in entry.get("trigger_rules") or [])
    lines.append("- avoid_rules:")
    lines.extend(f"  - {item}" for item in entry.get("avoid_rules") or [])
    lines.append("")


def _append_premarket_action_section(
    lines: list[str], title: str, entries: list[dict[str, Any]]
) -> None:
    _append_titled_indexed_section(
        lines,
        title=f"## {title}",
        items=entries,
        render_item=lambda inner_lines, entry, index: _append_premarket_action_block(
            inner_lines, entry, indexed=index
        ),
    )


def _append_premarket_frontier_watch_markdown(
    lines: list[str], frontier_priority: dict[str, Any]
) -> None:
    _append_premarket_frontier_watch_markdown_impl(
        lines,
        frontier_priority,
        append_frontier_section=_append_frontier_section,
        append_indexed_ticker_blocks=_append_indexed_ticker_blocks,
        append_candidate_watch_scoring_fields=_append_candidate_watch_scoring_fields,
        append_candidate_watch_reason_tags=_append_candidate_watch_reason_tags,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        format_float=_format_float,
    )


def _append_premarket_shadow_watch_markdown(
    lines: list[str], shadow_watch: list[dict[str, Any]]
) -> None:
    _append_premarket_shadow_watch_markdown_impl(
        lines,
        shadow_watch,
        append_titled_indexed_ticker_section=_append_titled_indexed_ticker_section,
        append_candidate_watch_scoring_fields=_append_candidate_watch_scoring_fields,
        append_candidate_watch_reason_tags=_append_candidate_watch_reason_tags,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        format_float=_format_float,
    )


def _append_candidate_watch_scoring_fields(
    lines: list[str], item: dict[str, Any]
) -> None:
    lines.append(f"- candidate_score: {_format_float(item.get('candidate_score'))}")
    lines.append(f"- filter_reason: {item.get('filter_reason') or 'n/a'}")
    lines.append(f"- total_shortfall: {_format_float(item.get('total_shortfall'))}")
    lines.append(f"- failed_threshold_count: {item.get('failed_threshold_count')}")
    lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")


def _append_candidate_watch_reason_tags(
    lines: list[str], item: dict[str, Any], *, reasons_label: str
) -> None:
    lines.append(
        f"- {reasons_label}: {', '.join(item.get('top_reasons') or []) or 'n/a'}"
    )
    lines.append(
        f"- positive_tags: {', '.join(item.get('positive_tags') or []) or 'n/a'}"
    )


def _append_threshold_shortfalls_line(
    lines: list[str], threshold_shortfalls: dict[str, Any]
) -> None:
    _append_threshold_shortfalls_line_impl(lines, threshold_shortfalls)


def _append_catalyst_watch_metrics(lines: list[str], metrics: dict[str, Any]) -> None:
    _append_catalyst_watch_metrics_impl(lines, metrics)


def _append_premarket_excluded_entries_markdown(
    lines: list[str], excluded_entries: list[dict[str, Any]]
) -> None:
    lines.append("## Explicit Non-Trades")
    if not excluded_entries:
        _append_none_block(lines)
        return
    lines.extend(
        f"- {entry.get('ticker')}: research selected, but short_trade={entry.get('short_trade_decision')} so it stays outside the short-trade execution list."
        for entry in excluded_entries
    )
    lines.append("")


def _append_upstream_shadow_summary_header(
    lines: list[str], upstream_shadow_summary: dict[str, Any]
) -> None:
    _append_upstream_shadow_summary_header_impl(
        lines,
        upstream_shadow_summary,
        append_upstream_shadow_summary_fn=lambda inner_lines, summary: (
            _append_upstream_shadow_summary(
                inner_lines,
                summary,
                empty_lane_counts_label="",
            )
        ),
    )


def _append_upstream_shadow_summary(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    *,
    empty_lane_counts_label: str,
) -> None:
    _append_upstream_shadow_summary_impl(
        lines,
        upstream_shadow_summary,
        empty_lane_counts_label=empty_lane_counts_label,
    )


def _append_upstream_shadow_core_fields(
    lines: list[str],
    entry: dict[str, Any],
    *,
    opening_plan_label: str,
    reasons_label: str,
) -> None:
    _append_upstream_shadow_core_fields_impl(
        lines,
        entry,
        opening_plan_label=opening_plan_label,
        reasons_label=reasons_label,
    )


def _append_upstream_shadow_section(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    upstream_shadow_entries: list[dict[str, Any]],
    render_item: Callable[[list[str], dict[str, Any], int], None],
) -> None:
    _append_upstream_shadow_section_impl(
        lines,
        upstream_shadow_summary,
        upstream_shadow_entries,
        render_item,
        append_none_block_fn=_append_none_block,
        append_upstream_shadow_summary_header_fn=_append_upstream_shadow_summary_header,
    )


def _append_premarket_upstream_shadow_item(
    lines: list[str], entry: dict[str, Any], index: int
) -> None:
    del index
    lines.append(f"### {entry.get('ticker')}")
    _append_upstream_shadow_core_fields(
        lines,
        entry,
        opening_plan_label="promotion_trigger",
        reasons_label="evidence",
    )


def _append_premarket_upstream_shadow_markdown(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_upstream_shadow_section(
        lines,
        upstream_shadow_summary,
        upstream_shadow_entries,
        _append_premarket_upstream_shadow_item,
    )


def _append_opening_upstream_shadow_item(
    lines: list[str], item: dict[str, Any], index: int
) -> None:
    lines.append(f"### {index}. {item.get('ticker')}")
    lines.append("- focus_tier: upstream_shadow_recall")
    _append_upstream_shadow_core_fields(
        lines,
        item,
        opening_plan_label="opening_plan",
        reasons_label="top_reasons",
    )


def render_btst_premarket_execution_card_markdown(card: dict[str, Any]) -> str:
    lines: list[str] = []
    _append_premarket_overview_markdown(lines, card)
    _append_premarket_primary_action_markdown(lines, card.get("primary_action"))
    _append_premarket_action_section(
        lines, "Watchlist Actions", list(card.get("watch_actions") or [])
    )
    _append_premarket_action_section(
        lines, "Opportunity Pool Actions", list(card.get("opportunity_actions") or [])
    )
    _append_premarket_action_section(
        lines, "Risky Observer Actions", list(card.get("risky_observer_actions") or [])
    )
    _append_premarket_action_section(
        lines,
        "No-History Observer Actions",
        list(card.get("no_history_observer_actions") or []),
    )
    _append_premarket_frontier_watch_markdown(
        lines, dict(card.get("catalyst_theme_frontier_priority") or {})
    )
    _append_premarket_shadow_watch_markdown(
        lines, list(card.get("catalyst_theme_shadow_watch") or [])
    )
    _append_premarket_excluded_entries_markdown(
        lines, list(card.get("excluded_research_entries") or [])
    )
    _append_premarket_upstream_shadow_markdown(
        lines,
        dict(card.get("upstream_shadow_summary") or {}),
        list(card.get("upstream_shadow_entries") or []),
    )
    _append_premarket_guardrails_markdown(
        lines, list(card.get("global_guardrails") or [])
    )
    _append_premarket_source_paths_markdown(lines, dict(card.get("source_paths") or {}))
    return "\n".join(lines) + "\n"


def _append_premarket_primary_action_markdown(
    lines: list[str], primary_action: Any
) -> None:
    lines.append("## Primary Action")
    if not primary_action:
        _append_none_block(lines)
        return
    _append_premarket_action_block(lines, dict(primary_action))


def _append_guardrail_section(
    lines: list[str], title: str, guardrails: list[str]
) -> None:
    _append_guardrail_section_impl(lines, title, guardrails)


def _append_premarket_guardrails_markdown(
    lines: list[str], guardrails: list[str]
) -> None:
    _append_guardrail_section(lines, "## Global Guardrails", guardrails)


def _append_premarket_source_paths_markdown(
    lines: list[str], source_paths: dict[str, Any]
) -> None:
    _append_source_paths_section(
        lines,
        report_dir=source_paths.get("report_dir"),
        snapshot_path=source_paths.get("snapshot_path"),
        session_summary_path=source_paths.get("session_summary_path"),
    )


def analyze_btst_opening_watch_card(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    return _analyze_btst_opening_watch_card_impl(
        input_path, trade_date=trade_date, next_trade_date=next_trade_date
    )



def render_btst_opening_watch_card_markdown(card: dict[str, Any]) -> str:
    lines: list[str] = []
    _append_opening_watch_overview_markdown(lines, card)
    _append_opening_watch_focus_items_markdown(
        lines, list(card.get("focus_items") or [])
    )
    _append_opening_watch_frontier_markdown(
        lines, dict(card.get("catalyst_theme_frontier_priority") or {})
    )
    _append_catalyst_theme_watch_markdown(
        lines,
        title="## Catalyst Theme Shadow Watch",
        items=list(card.get("catalyst_theme_shadow_watch") or []),
        focus_tier="catalyst_theme_shadow",
        execution_posture="research_followup_only",
    )

    _append_upstream_shadow_recall_markdown(
        lines,
        dict(card.get("upstream_shadow_summary") or {}),
        list(card.get("upstream_shadow_entries") or []),
    )
    _append_opening_watch_guardrails_markdown(
        lines, list(card.get("global_guardrails") or [])
    )
    _append_opening_watch_source_paths_markdown(
        lines, dict(card.get("source_paths") or {})
    )
    return "\n".join(lines) + "\n"


def _append_opening_watch_overview_markdown(
    lines: list[str], card: dict[str, Any]
) -> None:
    summary = dict(card.get("summary") or {})
    lines.append("# BTST Opening Watch Card")
    lines.append("")
    lines.append("## Opening Headline")
    lines.append(f"- trade_date: {card.get('trade_date')}")
    lines.append(f"- next_trade_date: {card.get('next_trade_date') or 'n/a'}")
    lines.append(f"- selection_target: {card.get('selection_target')}")
    lines.append(f"- headline: {card.get('headline')}")
    lines.append(f"- primary_count: {summary.get('primary_count')}")
    lines.append(f"- near_miss_count: {summary.get('near_miss_count')}")
    lines.append(f"- opportunity_pool_count: {summary.get('opportunity_pool_count')}")
    lines.append(
        f"- no_history_observer_count: {summary.get('no_history_observer_count')}"
    )
    lines.append(f"- risky_observer_count: {summary.get('risky_observer_count')}")
    lines.append(
        f"- catalyst_theme_frontier_promoted_count: {summary.get('catalyst_theme_frontier_promoted_count')}"
    )
    lines.append(
        f"- catalyst_theme_shadow_count: {summary.get('catalyst_theme_shadow_count')}"
    )
    lines.append(
        f"- upstream_shadow_candidate_count: {summary.get('upstream_shadow_candidate_count')}"
    )
    lines.append(
        f"- upstream_shadow_promotable_count: {summary.get('upstream_shadow_promotable_count')}"
    )
    lines.append(f"- recommendation: {card.get('recommendation')}")
    lines.append("")


def _append_opening_watch_frontier_markdown(
    lines: list[str], catalyst_theme_frontier_priority: dict[str, Any]
) -> None:
    _append_frontier_section(
        lines, catalyst_theme_frontier_priority, _append_opening_frontier_entries
    )


def _append_opening_frontier_entries(
    lines: list[str], items: list[dict[str, Any]]
) -> None:
    _append_catalyst_theme_watch_markdown(
        lines,
        title="",
        items=items,
        focus_tier="catalyst_theme_frontier_priority",
        execution_posture="research_followup_priority",
    )


def _append_opening_watch_guardrails_markdown(
    lines: list[str], guardrails: list[str]
) -> None:
    _append_guardrail_section(lines, "## Guardrails", guardrails)


def _append_opening_watch_source_paths_markdown(
    lines: list[str], source_paths: dict[str, Any]
) -> None:
    _append_source_paths_section(
        lines,
        report_dir=source_paths.get("report_dir"),
        snapshot_path=source_paths.get("snapshot_path"),
        session_summary_path=source_paths.get("session_summary_path"),
    )


def _append_indexed_ticker_blocks(
    lines: list[str],
    items: list[dict[str, Any]],
    render_item: Callable[[list[str], dict[str, Any]], None],
) -> None:
    _append_indexed_ticker_blocks_impl(lines, items, render_item)


def _append_titled_indexed_section(
    lines: list[str],
    *,
    title: str,
    items: list[dict[str, Any]],
    render_item: Callable[[list[str], dict[str, Any], int], None],
) -> None:
    _append_titled_indexed_section_impl(
        lines,
        title=title,
        items=items,
        render_item=render_item,
        append_none_block_fn=_append_none_block,
    )


def _append_titled_indexed_ticker_section(
    lines: list[str],
    *,
    title: str,
    items: list[dict[str, Any]],
    render_item: Callable[[list[str], dict[str, Any]], None],
) -> None:
    _append_titled_indexed_ticker_section_impl(
        lines,
        title=title,
        items=items,
        render_item=render_item,
        append_titled_indexed_section_fn=_append_titled_indexed_section,
        append_indexed_ticker_block_fn=_append_indexed_ticker_block,
    )


def _append_opening_watch_focus_items_markdown(
    lines: list[str], focus_items: list[dict[str, Any]]
) -> None:
    _append_opening_watch_focus_items_markdown_impl(
        lines,
        focus_items,
        append_titled_indexed_ticker_section=_append_titled_indexed_ticker_section,
        format_float=_format_float,
    )


def _append_catalyst_theme_watch_markdown(
    lines: list[str],
    *,
    title: str,
    items: list[dict[str, Any]],
    focus_tier: str,
    execution_posture: str,
) -> None:
    _append_catalyst_theme_watch_markdown_impl(
        lines,
        title=title,
        items=items,
        focus_tier=focus_tier,
        execution_posture=execution_posture,
        append_none_block=_append_none_block,
        append_indexed_ticker_blocks=_append_indexed_ticker_blocks,
        append_candidate_watch_scoring_fields=_append_candidate_watch_scoring_fields,
        append_candidate_watch_reason_tags=_append_candidate_watch_reason_tags,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
    )


def _append_upstream_shadow_recall_markdown(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_upstream_shadow_section(
        lines,
        upstream_shadow_summary,
        upstream_shadow_entries,
        _append_opening_upstream_shadow_item,
    )


def _append_indexed_ticker_block(
    lines: list[str],
    item: dict[str, Any],
    index: int,
    render_item: Callable[[list[str], dict[str, Any]], None],
) -> None:
    _append_indexed_ticker_block_impl(lines, item, index, render_item)


def analyze_btst_next_day_priority_board(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    return _analyze_btst_next_day_priority_board_impl(
        input_path, trade_date=trade_date, next_trade_date=next_trade_date
    )



def render_btst_next_day_priority_board_markdown(board: dict[str, Any]) -> str:
    lines: list[str] = []
    _append_priority_board_overview_markdown(lines, board)
    _append_priority_board_rows_markdown(lines, list(board.get("priority_rows") or []))
    _append_priority_board_frontier_markdown(
        lines, dict(board.get("catalyst_theme_frontier_priority") or {})
    )
    _append_priority_board_shadow_watch_markdown(
        lines, list(board.get("catalyst_theme_shadow_watch") or [])
    )
    _append_priority_board_guardrails_markdown(
        lines, list(board.get("global_guardrails") or [])
    )
    _append_priority_board_source_paths_markdown(
        lines, dict(board.get("source_paths") or {})
    )
    return "\n".join(lines) + "\n"


def _append_priority_board_overview_markdown(
    lines: list[str], board: dict[str, Any]
) -> None:
    _append_priority_board_overview_markdown_impl(lines, board)


def _append_priority_board_rows_markdown(
    lines: list[str], priority_rows: list[dict[str, Any]]
) -> None:
    _append_priority_board_rows_markdown_impl(
        lines,
        priority_rows,
        append_titled_indexed_ticker_section=_append_titled_indexed_ticker_section,
        format_float=_format_float,
    )


def _append_priority_board_frontier_markdown(
    lines: list[str], catalyst_theme_frontier_priority: dict[str, Any]
) -> None:
    _append_priority_board_frontier_markdown_impl(
        lines,
        catalyst_theme_frontier_priority,
        append_frontier_section=_append_frontier_section,
        append_indexed_ticker_blocks=_append_indexed_ticker_blocks,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        format_float=_format_float,
    )


def _append_priority_board_shadow_watch_markdown(
    lines: list[str], catalyst_theme_shadow_watch: list[dict[str, Any]]
) -> None:
    _append_priority_board_shadow_watch_markdown_impl(
        lines,
        catalyst_theme_shadow_watch,
        append_titled_indexed_ticker_section=_append_titled_indexed_ticker_section,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        format_float=_format_float,
    )


def _append_priority_board_guardrails_markdown(
    lines: list[str], guardrails: list[str]
) -> None:
    _append_guardrail_section(lines, "## Guardrails", guardrails)


def _append_priority_board_source_paths_markdown(
    lines: list[str], source_paths: dict[str, Any]
) -> None:
    _append_source_paths_section(
        lines,
        report_dir=source_paths.get("report_dir"),
        snapshot_path=source_paths.get("snapshot_path"),
        session_summary_path=source_paths.get("session_summary_path"),
    )


def _build_output_file_stem(
    prefix: str, trade_date: str | None, next_trade_date: str | None
) -> str:
    compact_trade_date = _compact_trade_date(trade_date) or "unknown"
    compact_next_trade_date = _compact_trade_date(next_trade_date) or "unknown"
    return f"{prefix}_{compact_trade_date}_for_{compact_next_trade_date}"


def _build_next_trade_date_file_stem(prefix: str, next_trade_date: str | None) -> str:
    return f"{prefix}_{_compact_trade_date(next_trade_date) or 'unknown'}"


def _write_analysis_artifacts(
    *,
    payload: dict[str, Any],
    render_markdown: Callable[[dict[str, Any]], str],
    resolved_output_dir: Path,
    stem: str,
) -> dict[str, Any]:
    output_json = resolved_output_dir / f"{stem}.json"
    output_md = resolved_output_dir / f"{stem}.md"
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output_md.write_text(render_markdown(payload), encoding="utf-8")
    return {
        "analysis": payload,
        "json_path": str(output_json),
        "markdown_path": str(output_md),
    }


def _resolve_followup_artifact_context(
    *,
    report_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None,
    brief_file_stem: str,
) -> tuple[Path, str | None, str | None, dict[str, Any]]:
    return _resolve_followup_artifact_context_impl(
        report_dir=report_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        brief_file_stem=brief_file_stem,
        normalize_trade_date=_normalize_trade_date,
        infer_next_trade_date=infer_next_trade_date,
        generate_btst_next_day_trade_brief_artifacts=generate_btst_next_day_trade_brief_artifacts,
    )


def generate_btst_next_day_trade_brief_artifacts(
    input_path: str | Path,
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    return _generate_btst_next_day_trade_brief_artifacts_impl(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze_btst_next_day_trade_brief=analyze_btst_next_day_trade_brief,
        render_btst_next_day_trade_brief_markdown=render_btst_next_day_trade_brief_markdown,
        build_output_file_stem=_build_output_file_stem,
        write_analysis_artifacts=_write_analysis_artifacts,
    )


def generate_btst_premarket_execution_card_artifacts(
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    return _generate_btst_premarket_execution_card_artifacts_impl(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze_btst_premarket_execution_card=analyze_btst_premarket_execution_card,
        render_btst_premarket_execution_card_markdown=render_btst_premarket_execution_card_markdown,
        build_output_file_stem=_build_output_file_stem,
        write_analysis_artifacts=_write_analysis_artifacts,
    )


def generate_btst_opening_watch_card_artifacts(
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    return _generate_btst_opening_watch_card_artifacts_impl(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze_btst_opening_watch_card=analyze_btst_opening_watch_card,
        render_btst_opening_watch_card_markdown=render_btst_opening_watch_card_markdown,
        build_next_trade_date_file_stem=_build_next_trade_date_file_stem,
        write_analysis_artifacts=_write_analysis_artifacts,
    )


def generate_btst_next_day_priority_board_artifacts(
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    return _generate_btst_next_day_priority_board_artifacts_impl(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze_btst_next_day_priority_board=analyze_btst_next_day_priority_board,
        render_btst_next_day_priority_board_markdown=render_btst_next_day_priority_board_markdown,
        build_next_trade_date_file_stem=_build_next_trade_date_file_stem,
        write_analysis_artifacts=_write_analysis_artifacts,
    )


def register_btst_followup_artifacts(
    report_dir: str | Path,
    *,
    trade_date: str | None,
    next_trade_date: str | None,
    brief_json_path: str | Path,
    brief_markdown_path: str | Path,
    card_json_path: str | Path,
    card_markdown_path: str | Path,
    opening_card_json_path: str | Path,
    opening_card_markdown_path: str | Path,
    priority_board_json_path: str | Path,
    priority_board_markdown_path: str | Path,
) -> dict[str, Any]:
    return _register_btst_followup_artifacts_impl(
        report_dir=report_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        brief_json_path=brief_json_path,
        brief_markdown_path=brief_markdown_path,
        card_json_path=card_json_path,
        card_markdown_path=card_markdown_path,
        opening_card_json_path=opening_card_json_path,
        opening_card_markdown_path=opening_card_markdown_path,
        priority_board_json_path=priority_board_json_path,
        priority_board_markdown_path=priority_board_markdown_path,
        load_json=_load_json,
        resolve_followup_trade_dates=_resolve_followup_trade_dates,
        sync_text_artifact_alias=_sync_text_artifact_alias,
        write_json=_write_json,
    )


def generate_and_register_btst_followup_artifacts(
    report_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None = None,
    *,
    brief_file_stem: str = "btst_next_day_trade_brief_latest",
    card_file_stem: str = "btst_premarket_execution_card_latest",
    opening_card_file_stem: str | None = None,
    priority_board_file_stem: str | None = None,
) -> dict[str, Any]:
    return _generate_and_register_btst_followup_artifacts_impl(
        report_dir=report_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        brief_file_stem=brief_file_stem,
        card_file_stem=card_file_stem,
        opening_card_file_stem=opening_card_file_stem,
        priority_board_file_stem=priority_board_file_stem,
        build_next_trade_date_file_stem=_build_next_trade_date_file_stem,
        resolve_followup_artifact_context=_resolve_followup_artifact_context,
        generate_btst_premarket_execution_card_artifacts=generate_btst_premarket_execution_card_artifacts,
        generate_btst_opening_watch_card_artifacts=generate_btst_opening_watch_card_artifacts,
        generate_btst_next_day_priority_board_artifacts=generate_btst_next_day_priority_board_artifacts,
        register_btst_followup_artifacts=register_btst_followup_artifacts,
    )
