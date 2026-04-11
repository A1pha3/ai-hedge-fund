from __future__ import annotations

from collections.abc import Callable
from typing import Any


RenderTickerItem = Callable[[list[str], dict[str, Any]], None]
RenderTickerSection = Callable[[list[str], list[dict[str, Any]], RenderTickerItem], None]
RenderFrontierSection = Callable[[list[str], dict[str, Any], Callable[[list[str], list[dict[str, Any]]], None]], None]


def append_priority_board_overview_markdown(lines: list[str], board: dict[str, Any]) -> None:
    lines.append("# BTST Next-Day Priority Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- trade_date: {board.get('trade_date')}")
    lines.append(f"- next_trade_date: {board.get('next_trade_date') or 'n/a'}")
    lines.append(f"- selection_target: {board.get('selection_target')}")
    lines.append(f"- headline: {board.get('headline')}")
    summary = dict(board.get("summary") or {})
    lines.append(f"- primary_count: {summary.get('primary_count')}")
    lines.append(f"- near_miss_count: {summary.get('near_miss_count')}")
    lines.append(f"- opportunity_pool_count: {summary.get('opportunity_pool_count')}")
    lines.append(f"- no_history_observer_count: {summary.get('no_history_observer_count')}")
    lines.append(f"- risky_observer_count: {summary.get('risky_observer_count')}")
    lines.append(f"- research_upside_radar_count: {summary.get('research_upside_radar_count')}")
    lines.append(f"- catalyst_theme_count: {summary.get('catalyst_theme_count')}")
    lines.append(f"- catalyst_theme_frontier_promoted_count: {summary.get('catalyst_theme_frontier_promoted_count')}")
    lines.append(f"- catalyst_theme_shadow_count: {summary.get('catalyst_theme_shadow_count')}")
    lines.append("")


def append_priority_board_rows_markdown(
    lines: list[str],
    priority_rows: list[dict[str, Any]],
    *,
    append_titled_indexed_ticker_section: RenderTickerSection,
    format_float: Callable[[Any], str],
) -> None:
    def render_row(inner_lines: list[str], row: dict[str, Any]) -> None:
        inner_lines.append(f"- lane: {row.get('lane')}")
        inner_lines.append(f"- actionability: {row.get('actionability')}")
        inner_lines.append(f"- monitor_priority: {row.get('monitor_priority')}")
        inner_lines.append(f"- execution_priority: {row.get('execution_priority')}")
        inner_lines.append(f"- execution_quality_label: {row.get('execution_quality_label')}")
        inner_lines.append(f"- score_target: {format_float(row.get('score_target'))}")
        if row.get("research_score_target") is not None:
            inner_lines.append(f"- research_score_target: {format_float(row.get('research_score_target'))}")
        inner_lines.append(f"- preferred_entry_mode: {row.get('preferred_entry_mode')}")
        inner_lines.append(f"- why_now: {row.get('why_now')}")
        inner_lines.append(f"- suggested_action: {row.get('suggested_action')}")
        inner_lines.append(f"- historical_summary: {row.get('historical_summary') or 'n/a'}")
        inner_lines.append(f"- execution_note: {row.get('execution_note') or 'n/a'}")

    append_titled_indexed_ticker_section(
        lines,
        title="## Priority Rows",
        items=priority_rows,
        render_item=render_row,
    )


def append_priority_board_frontier_markdown(
    lines: list[str],
    catalyst_theme_frontier_priority: dict[str, Any],
    *,
    append_frontier_section: RenderFrontierSection,
    append_indexed_ticker_blocks: RenderTickerSection,
    append_threshold_shortfalls_line: Callable[[list[str], dict[str, Any]], None],
    append_catalyst_watch_metrics: Callable[[list[str], dict[str, Any]], None],
    format_float: Callable[[Any], str],
) -> None:
    def render_entries(inner_lines: list[str], items: list[dict[str, Any]]) -> None:
        append_indexed_ticker_blocks(inner_lines, items, render_frontier_item)

    def render_frontier_item(inner_lines: list[str], item: dict[str, Any]) -> None:
        append_priority_board_catalyst_item_core_fields(inner_lines, item, lane="catalyst_theme_frontier_priority", actionability="research_followup_priority", format_float=format_float)
        append_threshold_shortfalls_line(inner_lines, dict(item.get("threshold_shortfalls") or {}))
        append_catalyst_watch_metrics(inner_lines, dict(item.get("metrics") or {}))

    append_frontier_section(lines, catalyst_theme_frontier_priority, render_entries)


def append_priority_board_shadow_watch_markdown(
    lines: list[str],
    catalyst_theme_shadow_watch: list[dict[str, Any]],
    *,
    append_titled_indexed_ticker_section: RenderTickerSection,
    append_threshold_shortfalls_line: Callable[[list[str], dict[str, Any]], None],
    append_catalyst_watch_metrics: Callable[[list[str], dict[str, Any]], None],
    format_float: Callable[[Any], str],
) -> None:
    def render_shadow_item(inner_lines: list[str], item: dict[str, Any]) -> None:
        append_priority_board_catalyst_item_core_fields(inner_lines, item, lane="catalyst_theme_shadow_watch", actionability="research_followup_only", format_float=format_float)
        append_threshold_shortfalls_line(inner_lines, dict(item.get("threshold_shortfalls") or {}))
        append_catalyst_watch_metrics(inner_lines, dict(item.get("metrics") or {}))

    append_titled_indexed_ticker_section(
        lines,
        title="## Catalyst Theme Shadow Watch",
        items=catalyst_theme_shadow_watch,
        render_item=render_shadow_item,
    )


def append_priority_board_catalyst_item_core_fields(
    lines: list[str],
    item: dict[str, Any],
    *,
    lane: str,
    actionability: str,
    format_float: Callable[[Any], str],
) -> None:
    lines.append(f"- lane: {lane}")
    lines.append(f"- actionability: {actionability}")
    lines.append(f"- candidate_score: {format_float(item.get('candidate_score'))}")
    lines.append(f"- filter_reason: {item.get('filter_reason') or 'n/a'}")
    lines.append(f"- total_shortfall: {format_float(item.get('total_shortfall'))}")
    lines.append(f"- failed_threshold_count: {item.get('failed_threshold_count')}")
    lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")
    lines.append(f"- suggested_action: {item.get('promotion_trigger') or '只做研究跟踪，不进入当日 BTST 交易名单。'}")
    lines.append(f"- top_reasons: {', '.join(item.get('top_reasons') or []) or 'n/a'}")
    lines.append(f"- positive_tags: {', '.join(item.get('positive_tags') or []) or 'n/a'}")
