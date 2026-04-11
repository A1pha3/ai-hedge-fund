from __future__ import annotations

from collections.abc import Callable
from typing import Any


RenderTickerItem = Callable[[list[str], dict[str, Any]], None]
RenderTickerSection = Callable[[list[str], list[dict[str, Any]], RenderTickerItem], None]


def append_opening_watch_focus_items_markdown(
    lines: list[str],
    focus_items: list[dict[str, Any]],
    *,
    append_titled_indexed_ticker_section: RenderTickerSection,
    format_float: Callable[[Any], str],
) -> None:
    def render_focus_item(inner_lines: list[str], item: dict[str, Any]) -> None:
        inner_lines.append(f"- focus_tier: {item.get('focus_tier')}")
        inner_lines.append(f"- monitor_priority: {item.get('monitor_priority')}")
        inner_lines.append(f"- execution_posture: {item.get('execution_posture')}")
        inner_lines.append(f"- score_target: {format_float(item.get('score_target'))}")
        inner_lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")
        inner_lines.append(f"- why_now: {item.get('why_now')}")
        inner_lines.append(f"- opening_plan: {item.get('opening_plan')}")
        inner_lines.append(f"- historical_summary: {item.get('historical_summary') or 'n/a'}")
        inner_lines.append(f"- execution_note: {item.get('execution_note') or 'n/a'}")

    append_titled_indexed_ticker_section(
        lines,
        title="## Focus Order",
        items=focus_items,
        render_item=render_focus_item,
    )


def append_catalyst_theme_watch_markdown(
    lines: list[str],
    *,
    title: str,
    items: list[dict[str, Any]],
    focus_tier: str,
    execution_posture: str,
    append_none_block: Callable[[list[str]], None],
    append_indexed_ticker_blocks: RenderTickerSection,
    append_candidate_watch_scoring_fields: RenderTickerItem,
    append_candidate_watch_reason_tags: Callable[[list[str], dict[str, Any], str], None],
    append_threshold_shortfalls_line: Callable[[list[str], dict[str, Any]], None],
    append_catalyst_watch_metrics: Callable[[list[str], dict[str, Any]], None],
) -> None:
    lines.append(title)
    if not items:
        append_none_block(lines)
        return

    def render_watch_item(inner_lines: list[str], item: dict[str, Any]) -> None:
        inner_lines.append(f"- focus_tier: {focus_tier}")
        inner_lines.append(f"- execution_posture: {execution_posture}")
        append_candidate_watch_scoring_fields(inner_lines, item)
        inner_lines.append(f"- opening_plan: {item.get('promotion_trigger') or '只做研究跟踪，不进入当日 BTST 交易名单。'}")
        append_candidate_watch_reason_tags(inner_lines, item, reasons_label="top_reasons")
        append_threshold_shortfalls_line(inner_lines, dict(item.get("threshold_shortfalls") or {}))
        append_catalyst_watch_metrics(inner_lines, dict(item.get("metrics") or {}))

    append_indexed_ticker_blocks(lines, items, render_watch_item)
