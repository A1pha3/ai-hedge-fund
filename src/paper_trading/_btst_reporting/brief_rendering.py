"""BTST trade brief markdown rendering.

Pure functions that render the next-day trade brief as markdown text.
Each section delegates to a specialized markdown helper module,
injecting local callback functions for shared sub-renderers.
"""

from __future__ import annotations

from typing import Any
from collections.abc import Callable

from src.paper_trading.btst_reporting_utils import _format_float
from src.paper_trading._btst_reporting.catalyst_render_helpers import (
    _append_threshold_shortfalls_line,
    _append_catalyst_watch_metrics,
)
from src.paper_trading.btst_trade_brief_core_markdown_helpers import (
    append_brief_observer_lane_markdown as _append_brief_observer_lane_markdown_impl,
    append_brief_scored_entries_markdown as _append_brief_scored_entries_markdown_impl,
)
from src.paper_trading.btst_trade_brief_pool_markdown_helpers import (
    append_brief_opportunity_pool_markdown as _append_brief_opportunity_pool_markdown_impl,
    append_brief_pruned_entries_markdown as _append_brief_pruned_entries_markdown_impl,
    append_brief_research_radar_markdown as _append_brief_research_radar_markdown_impl,
)
from src.paper_trading.btst_trade_brief_catalyst_markdown_helpers import (
    append_brief_catalyst_theme_markdown as _append_brief_catalyst_theme_markdown_impl,
    append_brief_excluded_research_markdown as _append_brief_excluded_research_markdown_impl,
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
    append_none_block as _append_none_block_impl,
    append_source_paths_section as _append_source_paths_section_impl,
    append_upstream_shadow_summary as _append_upstream_shadow_summary,
)


# ---------------------------------------------------------------------------
# Sub-renderers (local callbacks injected into _impl functions)
# ---------------------------------------------------------------------------

def _append_none_block(lines: list[str]) -> None:
    _append_none_block_impl(lines)


def _append_frontier_promoted_shadow_none_block(lines: list[str]) -> None:
    _append_frontier_promoted_shadow_none_block_impl(lines)


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


def _append_gate_status_line(lines: list[str], gate_status: dict[str, Any]) -> None:
    lines.append(
        "- gate_status: "
        + ", ".join(f"{key}={value}" for key, value in gate_status.items())
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


# ---------------------------------------------------------------------------
# Section renderers (inject local callbacks into _impl functions)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Top-level brief overview (large pure markdown generator)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

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
