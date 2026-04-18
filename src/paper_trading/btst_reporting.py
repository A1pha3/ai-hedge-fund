from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from collections.abc import Callable


from src.paper_trading.btst_reporting_utils import (
    OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
    _compact_trade_date,
    _format_float,
    _load_json,
    _normalize_trade_date,
    _resolve_followup_trade_dates,
    _sync_text_artifact_alias,
    _write_json,
    infer_next_trade_date,
)

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
from src.paper_trading.btst_shared_markdown_helpers import (
    append_guardrail_section as _append_guardrail_section_impl,
    append_indexed_ticker_block as _append_indexed_ticker_block_impl,
    append_indexed_ticker_blocks as _append_indexed_ticker_blocks_impl,
    append_titled_indexed_section as _append_titled_indexed_section_impl,
    append_titled_indexed_ticker_section as _append_titled_indexed_ticker_section_impl,
    append_upstream_shadow_core_fields as _append_upstream_shadow_core_fields_impl,
    append_upstream_shadow_section as _append_upstream_shadow_section_impl,
    append_upstream_shadow_summary as _append_upstream_shadow_summary_impl,
    append_upstream_shadow_summary_header as _append_upstream_shadow_summary_header_impl,
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

    _extract_research_upside_radar_entry as _extract_research_upside_radar_entry_eb,
    _extract_short_trade_entry as _extract_short_trade_entry_eb,
    _extract_short_trade_opportunity_entry as _extract_short_trade_opportunity_entry_eb,
    _extract_upstream_shadow_entry as _extract_upstream_shadow_entry_eb,
    _iter_selection_snapshot_paths as _iter_selection_snapshot_paths_eb,
    _load_catalyst_theme_frontier_summary as _load_catalyst_theme_frontier_summary_eb,
    _merge_entry_historical_prior as _merge_entry_historical_prior_eb,
    _reclassify_selected_execution_quality_entries as _reclassify_selected_execution_quality_entries_eb,
    _resolve_snapshot_path as _resolve_snapshot_path_eb,
)
from src.paper_trading._btst_reporting.brief_resolver import (
    _resolve_brief_analysis as _resolve_brief_analysis_impl,
)
from src.paper_trading._btst_reporting.historical_prior import (  # noqa: F401
    _collect_historical_watch_candidate_rows,
    _extract_next_day_outcome,
    _summarize_historical_opportunity_rows,
    _build_watch_candidate_historical_prior,
    _apply_historical_prior_to_entries,
    _enrich_btst_brief_entries_with_history,
)
from src.paper_trading._btst_reporting.pool_classifiers import (  # noqa: F401
    _partition_opportunity_pool_entries,
)
from src.tools.akshare_api import get_prices_robust  # noqa: F401
from src.tools.api import get_price_data  # noqa: F401
from src.paper_trading._btst_reporting.brief_rendering import (
    _append_brief_catalyst_frontier_markdown as _append_brief_catalyst_frontier_markdown_br,
    _append_brief_catalyst_shadow_markdown as _append_brief_catalyst_shadow_markdown_br,
    _append_brief_catalyst_theme_markdown as _append_brief_catalyst_theme_markdown_br,
    _append_brief_excluded_research_markdown as _append_brief_excluded_research_markdown_br,
    _append_brief_observer_lane_markdown as _append_brief_observer_lane_markdown_br,
    _append_brief_opportunity_pool_markdown as _append_brief_opportunity_pool_markdown_br,
    _append_brief_scored_entries_markdown as _append_brief_scored_entries_markdown_br,
    _append_brief_upstream_shadow_markdown as _append_brief_upstream_shadow_markdown_br,
    render_btst_next_day_trade_brief_markdown as render_btst_next_day_trade_brief_br,
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



from src.paper_trading._btst_reporting.brief_builder import (
    analyze_btst_next_day_trade_brief,
)


def _append_brief_overview_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_brief_overview_markdown as _impl
    _impl(lines, analysis)


def _append_brief_scored_entries_markdown(
    lines: list[str], title: str, entries: list[dict[str, Any]]
) -> None:
    _append_brief_scored_entries_markdown_br(lines, title, entries)


def _append_brief_ticker_section(
    lines: list[str],
    *,
    title: str,
    entries: list[dict[str, Any]],
    render_entry: Callable[[list[str], dict[str, Any]], None],
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_brief_ticker_section as _impl
    _impl(lines, title=title, entries=entries, render_entry=render_entry)


def _append_brief_historical_prior_fields(
    lines: list[str],
    historical_prior: dict[str, Any],
    *,
    include_summary: bool = True,
    include_monitor_priority: bool = False,
    include_execution_quality: bool = False,
    include_execution_note: bool = False,
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_brief_historical_prior_fields as _impl
    _impl(lines, historical_prior, include_summary=include_summary, include_monitor_priority=include_monitor_priority, include_execution_quality=include_execution_quality, include_execution_note=include_execution_note)


def _append_brief_scored_entry_metrics(
    lines: list[str], metrics: dict[str, Any]
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_brief_scored_entry_metrics as _impl
    _impl(lines, metrics)


def _append_brief_short_trade_metrics(
    lines: list[str], metrics: dict[str, Any]
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_brief_short_trade_metrics as _impl
    _impl(lines, metrics)


def _append_brief_historical_recent_examples(
    lines: list[str], historical_prior: dict[str, Any]
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_brief_historical_recent_examples as _impl
    _impl(lines, historical_prior)


def _append_brief_opportunity_pool_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_opportunity_pool_markdown_br(lines, entries)


def _append_gate_status_line(lines: list[str], gate_status: dict[str, Any]) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_gate_status_line as _impl
    _impl(lines, gate_status)


def _append_brief_observer_lane_markdown(
    lines: list[str],
    title: str,
    entries: list[dict[str, Any]],
    include_execution_note: bool,
) -> None:
    _append_brief_observer_lane_markdown_br(lines, title, entries, include_execution_note)


def _append_brief_pruned_entries_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_brief_pruned_entries_markdown as _impl
    _impl(lines, entries)


def _append_brief_research_radar_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_brief_research_radar_markdown as _impl
    _impl(lines, entries)


def _append_brief_catalyst_theme_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_catalyst_theme_markdown_br(lines, entries)


def _append_frontier_priority_summary(
    lines: list[str], frontier_priority: dict[str, Any]
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_frontier_priority_summary as _impl
    _impl(lines, frontier_priority)


def _append_frontier_section(
    lines: list[str],
    frontier_priority: dict[str, Any],
    render_entries: Callable[[list[str], list[dict[str, Any]]], None],
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_frontier_section as _impl
    _impl(lines, frontier_priority, render_entries)


def _append_brief_catalyst_frontier_markdown(
    lines: list[str], frontier_priority: dict[str, Any]
) -> None:
    _append_brief_catalyst_frontier_markdown_br(lines, frontier_priority)


def _append_brief_catalyst_shadow_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_catalyst_shadow_markdown_br(lines, entries)


def _append_brief_excluded_research_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_excluded_research_markdown_br(lines, entries)


def _append_brief_summary_ticker_section(
    lines: list[str],
    *,
    title: str,
    entries: list[dict[str, Any]],
    append_summary: Callable[[list[str]], None],
    render_entry: Callable[[list[str], dict[str, Any]], None],
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_brief_summary_ticker_section as _impl
    _impl(lines, title=title, entries=entries, append_summary=append_summary, render_entry=render_entry)


def _append_brief_upstream_shadow_summary(
    lines: list[str], upstream_shadow_summary: dict[str, Any]
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_brief_upstream_shadow_summary as _impl
    _impl(lines, upstream_shadow_summary)


def _append_brief_upstream_shadow_markdown(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_brief_upstream_shadow_markdown_br(lines, upstream_shadow_summary, upstream_shadow_entries)


def render_btst_next_day_trade_brief_markdown(analysis: dict[str, Any]) -> str:
    return render_btst_next_day_trade_brief_br(analysis)


def _append_source_paths_section(
    lines: list[str],
    *,
    report_dir: Any,
    snapshot_path: Any,
    session_summary_path: Any,
    replay_input_path: Any | None = None,
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_source_paths_section as _impl
    _impl(lines, report_dir=report_dir, snapshot_path=snapshot_path, session_summary_path=session_summary_path, replay_input_path=replay_input_path)


def _append_none_block(lines: list[str]) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_none_block as _impl
    _impl(lines)


def _append_frontier_promoted_shadow_none_block(lines: list[str]) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_frontier_promoted_shadow_none_block as _impl
    _impl(lines)


def _append_brief_source_paths_markdown(
    lines: list[str], analysis: dict[str, Any]
) -> None:
    from src.paper_trading._btst_reporting.brief_rendering import _append_brief_source_paths_markdown as _impl
    _impl(lines, analysis)



def _resolve_brief_analysis(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None,
    next_trade_date: str | None,
) -> dict[str, Any]:
    return _resolve_brief_analysis_impl(input_path, trade_date, next_trade_date)


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
