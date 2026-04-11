from __future__ import annotations

from collections.abc import Callable
from typing import Any


AppendBriefTickerSection = Callable[..., None]
AppendHistoricalPriorFields = Callable[..., None]


def append_brief_catalyst_theme_markdown(
    lines: list[str],
    entries: list[dict[str, Any]],
    *,
    append_brief_ticker_section: AppendBriefTickerSection,
    append_brief_historical_prior_fields: AppendHistoricalPriorFields,
    append_gate_status_line: Callable[[list[str], dict[str, Any]], None],
    format_float: Callable[[Any], str],
) -> None:
    def render_entry(inner_lines: list[str], entry: dict[str, Any]) -> None:
        historical_prior = dict(entry.get("historical_prior") or {})
        metrics = dict(entry.get("metrics") or {})
        inner_lines.append(f"- candidate_score: {format_float(entry.get('score_target'))}")
        inner_lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
        inner_lines.append(f"- candidate_source: {entry.get('candidate_source')}")
        inner_lines.append(f"- promotion_trigger: {entry.get('promotion_trigger')}")
        append_brief_historical_prior_fields(inner_lines, historical_prior, include_monitor_priority=True)
        inner_lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
        inner_lines.append(f"- blockers: {', '.join(entry.get('blockers') or []) or 'none'}")
        inner_lines.append(
            "- key_metrics: "
            + ", ".join(
                [
                    f"breakout={format_float(metrics.get('breakout_freshness'))}",
                    f"trend={format_float(metrics.get('trend_acceleration'))}",
                    f"close={format_float(metrics.get('close_strength'))}",
                    f"sector={format_float(metrics.get('sector_resonance'))}",
                    f"catalyst={format_float(metrics.get('catalyst_freshness'))}",
                ]
            )
        )
        append_gate_status_line(inner_lines, entry.get("gate_status") or {})

    append_brief_ticker_section(lines, title="Catalyst Theme Research Lane", entries=entries, render_entry=render_entry)


def append_brief_excluded_research_markdown(
    lines: list[str],
    entries: list[dict[str, Any]],
    *,
    append_brief_ticker_section: AppendBriefTickerSection,
    format_float: Callable[[Any], str],
) -> None:
    def render_entry(inner_lines: list[str], entry: dict[str, Any]) -> None:
        inner_lines.append(f"- research_score_target: {format_float(entry.get('research_score_target'))}")
        inner_lines.append(f"- short_trade_decision: {entry.get('short_trade_decision')}")
        inner_lines.append(f"- short_trade_score_target: {format_float(entry.get('short_trade_score_target'))}")
        inner_lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
        inner_lines.append(f"- delta_summary: {', '.join(entry.get('delta_summary') or []) or 'n/a'}")

    append_brief_ticker_section(
        lines,
        title="Research Picks Excluded From Short-Trade Brief",
        entries=entries,
        render_entry=render_entry,
    )
