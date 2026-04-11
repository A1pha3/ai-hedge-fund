from __future__ import annotations

from collections.abc import Callable
from typing import Any


RenderTickerItem = Callable[[list[str], dict[str, Any]], None]
RenderIndexedItem = Callable[[list[str], dict[str, Any], int], None]
RenderEntryList = Callable[[list[str], list[dict[str, Any]]], None]
AppendSummary = Callable[[list[str]], None]


def append_source_paths_section(
    lines: list[str],
    *,
    report_dir: Any,
    snapshot_path: Any,
    session_summary_path: Any,
    replay_input_path: Any | None = None,
) -> None:
    lines.append("## Source Paths")
    lines.append(f"- report_dir: {report_dir}")
    lines.append(f"- snapshot_path: {snapshot_path}")
    if replay_input_path is not None:
        lines.append(f"- replay_input_path: {replay_input_path or 'n/a'}")
    lines.append(f"- session_summary_path: {session_summary_path or 'n/a'}")


def append_none_block(lines: list[str]) -> None:
    lines.append("- none")
    lines.append("")


def append_frontier_promoted_shadow_none_block(lines: list[str]) -> None:
    lines.append("- promoted_shadow_watch: none")
    lines.append("")


def append_frontier_priority_summary(
    lines: list[str],
    frontier_priority: dict[str, Any],
    *,
    format_float: Callable[[Any], str],
) -> None:
    lines.append(f"- status: {frontier_priority.get('status')}")
    lines.append(f"- recommended_variant_name: {frontier_priority.get('recommended_variant_name') or 'n/a'}")
    lines.append(f"- promoted_shadow_count: {frontier_priority.get('promoted_shadow_count')}")
    lines.append(f"- promoted_tickers: {', '.join(frontier_priority.get('promoted_tickers') or []) or 'none'}")
    lines.append(f"- recommended_relaxation_cost: {format_float(frontier_priority.get('recommended_relaxation_cost'))}")
    lines.append(f"- recommendation: {frontier_priority.get('recommendation') or 'n/a'}")
    lines.append(f"- frontier_markdown_path: {frontier_priority.get('markdown_path') or 'n/a'}")


def append_frontier_section(
    lines: list[str],
    frontier_priority: dict[str, Any],
    render_entries: RenderEntryList,
    *,
    append_none_block_fn: Callable[[list[str]], None],
    append_frontier_priority_summary_fn: Callable[[list[str], dict[str, Any]], None],
    append_frontier_promoted_shadow_none_block_fn: Callable[[list[str]], None],
) -> None:
    lines.append("## Catalyst Theme Frontier Priority")
    if not frontier_priority:
        append_none_block_fn(lines)
        return
    append_frontier_priority_summary_fn(lines, frontier_priority)
    lines.append("")
    promoted_shadow_watch = list(frontier_priority.get("promoted_shadow_watch") or [])
    if not promoted_shadow_watch:
        append_frontier_promoted_shadow_none_block_fn(lines)
        return
    render_entries(lines, promoted_shadow_watch)


def append_upstream_shadow_summary_header(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    *,
    append_upstream_shadow_summary_fn: Callable[[list[str], dict[str, Any]], None],
) -> None:
    append_upstream_shadow_summary_fn(lines, upstream_shadow_summary)
    lines.append("")


def append_upstream_shadow_summary(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    *,
    empty_lane_counts_label: str,
) -> None:
    lane_counts = dict(upstream_shadow_summary.get("lane_counts") or {})
    lines.append(f"- shadow_candidate_count: {upstream_shadow_summary.get('shadow_candidate_count')}")
    lines.append(f"- promotable_count: {upstream_shadow_summary.get('promotable_count')}")
    lines.append(
        "- lane_counts: "
        + (", ".join(f"{key}={value}" for key, value in lane_counts.items()) if lane_counts else empty_lane_counts_label)
    )


def append_upstream_shadow_core_fields(
    lines: list[str],
    entry: dict[str, Any],
    *,
    opening_plan_label: str,
    reasons_label: str,
) -> None:
    lines.append(f"- candidate_source: {entry.get('candidate_source')}")
    lines.append(f"- candidate_pool_lane: {entry.get('candidate_pool_lane_display')}")
    lines.append(f"- decision: {entry.get('decision')}")
    lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
    lines.append(f"- {opening_plan_label}: {entry.get('promotion_trigger')}")
    lines.append(f"- {reasons_label}: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
    lines.append(f"- rejection_reasons: {', '.join(entry.get('rejection_reasons') or []) or 'n/a'}")


def append_upstream_shadow_section(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    upstream_shadow_entries: list[dict[str, Any]],
    render_item: RenderIndexedItem,
    *,
    append_none_block_fn: Callable[[list[str]], None],
    append_upstream_shadow_summary_header_fn: Callable[[list[str], dict[str, Any]], None],
) -> None:
    lines.append("## Upstream Shadow Recall")
    if not upstream_shadow_entries:
        append_none_block_fn(lines)
        return
    append_upstream_shadow_summary_header_fn(lines, upstream_shadow_summary)
    for index, item in enumerate(upstream_shadow_entries, start=1):
        render_item(lines, item, index)
        lines.append("")


def append_guardrail_section(lines: list[str], title: str, guardrails: list[str]) -> None:
    lines.append(title)
    for item in guardrails:
        lines.append(f"- {item}")
    lines.append("")


def append_indexed_ticker_blocks(lines: list[str], items: list[dict[str, Any]], render_item: RenderTickerItem) -> None:
    for index, item in enumerate(items, start=1):
        lines.append(f"### {index}. {item.get('ticker')}")
        render_item(lines, item)
        lines.append("")


def append_indexed_ticker_block(
    lines: list[str],
    item: dict[str, Any],
    index: int,
    render_item: RenderTickerItem,
) -> None:
    lines.append(f"### {index}. {item.get('ticker')}")
    render_item(lines, item)
    lines.append("")


def append_titled_indexed_section(
    lines: list[str],
    *,
    title: str,
    items: list[dict[str, Any]],
    render_item: RenderIndexedItem,
    append_none_block_fn: Callable[[list[str]], None],
) -> None:
    lines.append(title)
    if not items:
        append_none_block_fn(lines)
        return
    for index, item in enumerate(items, start=1):
        render_item(lines, item, index)


def append_titled_indexed_ticker_section(
    lines: list[str],
    *,
    title: str,
    items: list[dict[str, Any]],
    render_item: RenderTickerItem,
    append_titled_indexed_section_fn: Callable[..., None],
    append_indexed_ticker_block_fn: Callable[[list[str], dict[str, Any], int, RenderTickerItem], None],
) -> None:
    append_titled_indexed_section_fn(
        lines,
        title=title,
        items=items,
        render_item=lambda inner_lines, item, index: append_indexed_ticker_block_fn(inner_lines, item, index, render_item),
    )
