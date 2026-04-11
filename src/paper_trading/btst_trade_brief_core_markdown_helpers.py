from __future__ import annotations

from collections.abc import Callable
from typing import Any


AppendBriefTickerSection = Callable[..., None]
AppendHistoricalPriorFields = Callable[..., None]


def append_brief_scored_entries_markdown(
    lines: list[str],
    title: str,
    entries: list[dict[str, Any]],
    *,
    append_brief_ticker_section: AppendBriefTickerSection,
    append_brief_historical_prior_fields: AppendHistoricalPriorFields,
    append_brief_short_trade_metrics: Callable[[list[str], dict[str, Any]], None],
    append_brief_historical_recent_examples: Callable[[list[str], dict[str, Any]], None],
    append_gate_status_line: Callable[[list[str], dict[str, Any]], None],
    format_float: Callable[[Any], str],
) -> None:
    def render_entry(inner_lines: list[str], entry: dict[str, Any]) -> None:
        historical_prior = dict(entry.get("historical_prior") or {})
        inner_lines.append(f"- decision: {entry['decision']}")
        inner_lines.append(f"- score_target: {format_float(entry.get('score_target'))}")
        inner_lines.append(f"- confidence: {format_float(entry.get('confidence'))}")
        inner_lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
        inner_lines.append(f"- candidate_source: {entry.get('candidate_source')}")
        if historical_prior:
            append_brief_historical_prior_fields(
                inner_lines,
                historical_prior,
                include_monitor_priority=True,
                include_execution_quality=True,
                include_execution_note=True,
            )
        inner_lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
        inner_lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
        append_brief_short_trade_metrics(inner_lines, dict(entry.get("metrics") or {}))
        append_brief_historical_recent_examples(inner_lines, historical_prior)
        append_gate_status_line(inner_lines, entry.get("gate_status") or {})

    append_brief_ticker_section(lines, title=title, entries=entries, render_entry=render_entry)


def append_brief_observer_lane_markdown(
    lines: list[str],
    title: str,
    entries: list[dict[str, Any]],
    include_execution_note: bool,
    *,
    append_brief_ticker_section: AppendBriefTickerSection,
    append_brief_historical_prior_fields: AppendHistoricalPriorFields,
) -> None:
    def render_entry(inner_lines: list[str], entry: dict[str, Any]) -> None:
        historical_prior = dict(entry.get("historical_prior") or {})
        inner_lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
        inner_lines.append(f"- candidate_source: {entry.get('candidate_source')}")
        inner_lines.append(f"- promotion_trigger: {entry.get('promotion_trigger')}")
        append_brief_historical_prior_fields(inner_lines, historical_prior, include_execution_quality=True)
        inner_lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
        if include_execution_note:
            append_brief_historical_prior_fields(inner_lines, historical_prior, include_summary=False, include_execution_note=True)

    append_brief_ticker_section(lines, title=title, entries=entries, render_entry=render_entry)
