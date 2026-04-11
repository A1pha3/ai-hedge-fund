from __future__ import annotations

from collections.abc import Callable
from typing import Any


RenderTickerEntry = Callable[[list[str], dict[str, Any]], None]
RenderTickerSection = Callable[..., None]
RenderSummarySection = Callable[..., None]


def append_brief_catalyst_frontier_markdown(
    lines: list[str],
    frontier_priority: dict[str, Any],
    *,
    append_frontier_section: Callable[[list[str], dict[str, Any], Callable[[list[str], list[dict[str, Any]]], None]], None],
    append_threshold_shortfalls_line: Callable[[list[str], dict[str, Any]], None],
    append_catalyst_watch_metrics: Callable[[list[str], dict[str, Any]], None],
    format_float: Callable[[Any], str],
) -> None:
    def render_entries(inner_lines: list[str], entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            inner_lines.append(f"### {entry['ticker']}")
            inner_lines.append("- frontier_role: promoted_shadow_priority")
            inner_lines.append("- execution_posture: research_followup_priority")
            inner_lines.append(f"- candidate_score: {format_float(entry.get('candidate_score'))}")
            inner_lines.append(f"- filter_reason: {entry.get('filter_reason') or 'n/a'}")
            inner_lines.append(f"- total_shortfall: {format_float(entry.get('total_shortfall'))}")
            inner_lines.append(f"- failed_threshold_count: {entry.get('failed_threshold_count')}")
            inner_lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            inner_lines.append(f"- promotion_trigger: {entry.get('promotion_trigger') or '若催化继续发酵，才允许升级到题材催化研究池。'}")
            inner_lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
            inner_lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
            append_threshold_shortfalls_line(inner_lines, dict(entry.get("threshold_shortfalls") or {}))
            append_catalyst_watch_metrics(inner_lines, dict(entry.get("metrics") or {}))
            inner_lines.append("")

    append_frontier_section(lines, frontier_priority, render_entries)


def append_brief_catalyst_shadow_markdown(
    lines: list[str],
    entries: list[dict[str, Any]],
    *,
    append_brief_ticker_section: RenderTickerSection,
    append_threshold_shortfalls_line: Callable[[list[str], dict[str, Any]], None],
    append_catalyst_watch_metrics: Callable[[list[str], dict[str, Any]], None],
    append_gate_status_line: Callable[[list[str], dict[str, Any]], None],
    format_float: Callable[[Any], str],
) -> None:
    def render_entry(inner_lines: list[str], entry: dict[str, Any]) -> None:
        inner_lines.append(f"- candidate_score: {format_float(entry.get('score_target'))}")
        inner_lines.append(f"- filter_reason: {entry.get('filter_reason') or 'n/a'}")
        inner_lines.append(f"- total_shortfall: {format_float(entry.get('total_shortfall'))}")
        inner_lines.append(f"- failed_threshold_count: {entry.get('failed_threshold_count')}")
        inner_lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
        inner_lines.append(f"- candidate_source: {entry.get('candidate_source')}")
        inner_lines.append(f"- promotion_trigger: {entry.get('promotion_trigger')}")
        inner_lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
        inner_lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
        append_threshold_shortfalls_line(inner_lines, dict(entry.get("threshold_shortfalls") or {}))
        inner_lines.append(f"- blockers: {', '.join(entry.get('blockers') or []) or 'none'}")
        append_catalyst_watch_metrics(inner_lines, dict(entry.get("metrics") or {}))
        append_gate_status_line(inner_lines, entry.get("gate_status") or {})

    append_brief_ticker_section(
        lines,
        title="Catalyst Theme Shadow Watch",
        entries=entries,
        render_entry=render_entry,
    )


def append_brief_upstream_shadow_markdown(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    upstream_shadow_entries: list[dict[str, Any]],
    *,
    append_brief_summary_ticker_section: RenderSummarySection,
    append_upstream_shadow_summary: Callable[[list[str], dict[str, Any]], None],
    append_gate_status_line: Callable[[list[str], dict[str, Any]], None],
    format_float: Callable[[Any], str],
) -> None:
    def append_summary(inner_lines: list[str]) -> None:
        append_upstream_shadow_summary(inner_lines, upstream_shadow_summary)

    def render_entry(inner_lines: list[str], entry: dict[str, Any]) -> None:
        inner_lines.append(f"- decision: {entry.get('decision')}")
        inner_lines.append(f"- score_target: {format_float(entry.get('score_target'))}")
        inner_lines.append(f"- confidence: {format_float(entry.get('confidence'))}")
        inner_lines.append(f"- candidate_source: {entry.get('candidate_source')}")
        inner_lines.append(f"- candidate_pool_lane: {entry.get('candidate_pool_lane_display')}")
        inner_lines.append(f"- candidate_pool_rank: {entry.get('candidate_pool_rank') if entry.get('candidate_pool_rank') is not None else 'n/a'}")
        inner_lines.append(f"- share_of_cutoff: {format_float(entry.get('candidate_pool_avg_amount_share_of_cutoff'))}")
        inner_lines.append(f"- share_of_min_gate: {format_float(entry.get('candidate_pool_avg_amount_share_of_min_gate'))}")
        inner_lines.append(f"- upstream_candidate_source: {entry.get('upstream_candidate_source')}")
        inner_lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
        inner_lines.append(f"- promotion_trigger: {entry.get('promotion_trigger')}")
        inner_lines.append(f"- candidate_reason_codes: {', '.join(entry.get('candidate_reason_codes') or []) or 'n/a'}")
        inner_lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
        inner_lines.append(f"- rejection_reasons: {', '.join(entry.get('rejection_reasons') or []) or 'n/a'}")
        inner_lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
        _append_brief_upstream_shadow_metrics(inner_lines, dict(entry.get("metrics") or {}), format_float=format_float)
        append_gate_status_line(inner_lines, entry.get("gate_status") or {})

    append_brief_summary_ticker_section(
        lines,
        title="Upstream Shadow Recall",
        entries=upstream_shadow_entries,
        append_summary=append_summary,
        render_entry=render_entry,
    )


def _append_brief_upstream_shadow_metrics(
    lines: list[str],
    metrics: dict[str, Any],
    *,
    format_float: Callable[[Any], str],
) -> None:
    lines.append(
        "- key_metrics: "
        + ", ".join(
            [
                f"breakout={format_float(metrics.get('breakout_freshness'))}",
                f"trend={format_float(metrics.get('trend_acceleration'))}",
                f"volume={format_float(metrics.get('volume_expansion_quality'))}",
                f"close={format_float(metrics.get('close_strength'))}",
                f"catalyst={format_float(metrics.get('catalyst_freshness'))}",
            ]
        )
    )
