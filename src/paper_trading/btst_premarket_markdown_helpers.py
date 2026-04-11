from __future__ import annotations

from collections.abc import Callable
from typing import Any


RenderTickerItem = Callable[[list[str], dict[str, Any]], None]
RenderTickerSection = Callable[[list[str], list[dict[str, Any]], RenderTickerItem], None]
RenderFrontierSection = Callable[[list[str], dict[str, Any], Callable[[list[str], list[dict[str, Any]]], None]], None]
AppendReasonTags = Callable[[list[str], dict[str, Any], str], None]
AppendThresholdShortfalls = Callable[[list[str], dict[str, Any]], None]
AppendMetrics = Callable[[list[str], dict[str, Any]], None]


def append_premarket_frontier_watch_markdown(
    lines: list[str],
    frontier_priority: dict[str, Any],
    *,
    append_frontier_section: RenderFrontierSection,
    append_indexed_ticker_blocks: RenderTickerSection,
    append_candidate_watch_scoring_fields: RenderTickerItem,
    append_candidate_watch_reason_tags: AppendReasonTags,
    append_threshold_shortfalls_line: AppendThresholdShortfalls,
    append_catalyst_watch_metrics: AppendMetrics,
    format_float: Callable[[Any], str],
) -> None:
    def render_entries(inner_lines: list[str], items: list[dict[str, Any]]) -> None:
        append_indexed_ticker_blocks(inner_lines, items, render_frontier_entry_item)

    def render_frontier_entry_item(inner_lines: list[str], item: dict[str, Any]) -> None:
        append_premarket_watch_header(
            inner_lines,
            item,
            action_tier="catalyst_theme_frontier_priority",
            execution_posture="research_followup_priority",
            append_candidate_watch_scoring_fields=append_candidate_watch_scoring_fields,
            append_candidate_watch_reason_tags=append_candidate_watch_reason_tags,
        )
        threshold_shortfalls = dict(item.get("threshold_shortfalls") or {})
        append_threshold_shortfalls_line(inner_lines, threshold_shortfalls)
        append_catalyst_watch_metrics(inner_lines, dict(item.get("metrics") or {}))
        append_premarket_watch_rules(
            inner_lines,
            item,
            threshold_shortfalls,
            second_avoid_rule="不把题材催化前沿 priority 与 short-trade watchlist 混用。",
            format_float=format_float,
        )

    append_frontier_section(lines, frontier_priority, render_entries)


def append_premarket_shadow_watch_markdown(
    lines: list[str],
    shadow_watch: list[dict[str, Any]],
    *,
    append_titled_indexed_ticker_section: RenderTickerSection,
    append_candidate_watch_scoring_fields: RenderTickerItem,
    append_candidate_watch_reason_tags: AppendReasonTags,
    append_threshold_shortfalls_line: AppendThresholdShortfalls,
    append_catalyst_watch_metrics: AppendMetrics,
    format_float: Callable[[Any], str],
) -> None:
    def render_shadow_watch_item(inner_lines: list[str], item: dict[str, Any]) -> None:
        append_premarket_watch_header(
            inner_lines,
            item,
            action_tier="research_followup_only",
            execution_posture="research_followup_only",
            append_candidate_watch_scoring_fields=append_candidate_watch_scoring_fields,
            append_candidate_watch_reason_tags=append_candidate_watch_reason_tags,
        )
        threshold_shortfalls = dict(item.get("threshold_shortfalls") or {})
        append_threshold_shortfalls_line(inner_lines, threshold_shortfalls)
        append_catalyst_watch_metrics(inner_lines, dict(item.get("metrics") or {}))
        append_premarket_watch_rules(
            inner_lines,
            item,
            threshold_shortfalls,
            second_avoid_rule="不把题材催化研究跟踪对象与 short-trade watchlist 混用。",
            format_float=format_float,
        )

    append_titled_indexed_ticker_section(
        lines,
        title="## Catalyst Theme Shadow Watch",
        items=shadow_watch,
        render_item=render_shadow_watch_item,
    )


def append_premarket_watch_header(
    lines: list[str],
    item: dict[str, Any],
    *,
    action_tier: str,
    execution_posture: str,
    append_candidate_watch_scoring_fields: RenderTickerItem,
    append_candidate_watch_reason_tags: AppendReasonTags,
) -> None:
    lines.append(f"- action_tier: {action_tier}")
    lines.append(f"- execution_posture: {execution_posture}")
    append_candidate_watch_scoring_fields(lines, item)
    append_candidate_watch_reason_tags(lines, item, reasons_label="evidence")


def append_premarket_watch_rules(
    lines: list[str],
    item: dict[str, Any],
    threshold_shortfalls: dict[str, Any],
    *,
    second_avoid_rule: str,
    format_float: Callable[[Any], str],
) -> None:
    lines.append("- trigger_rules:")
    lines.append(f"  - {item.get('promotion_trigger') or '若催化继续发酵，才允许升级到题材催化研究池。'}")
    if threshold_shortfalls:
        lines.append(
            "  - 需先补齐阈值缺口: "
            + ", ".join(f"{key}={format_float(value)}" for key, value in threshold_shortfalls.items())
        )
    lines.append("- avoid_rules:")
    lines.append("  - 不进入当日 BTST 交易名单。")
    lines.append(f"  - {second_avoid_rule}")
