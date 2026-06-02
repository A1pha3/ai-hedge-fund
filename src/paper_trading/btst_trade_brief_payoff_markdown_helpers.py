from __future__ import annotations

from collections.abc import Callable
from typing import Any


def append_brief_payoff_review_lane_markdown(
    lines: list[str],
    entries: list[dict[str, Any]],
    *,
    append_brief_historical_prior_fields: Callable[..., None],
    append_brief_short_trade_metrics: Callable[[list[str], dict[str, Any]], None],
    append_brief_historical_recent_examples: Callable[[list[str], dict[str, Any]], None],
    append_gate_status_line: Callable[[list[str], dict[str, Any]], None],
    format_float: Callable[[Any], str],
) -> None:
    if not entries:
        return

    lines.append("## Payoff-first Review Lane")
    lines.append(
        "- 复审层（review-only）：不等于下单；用于优先盯 5D payoff 线索，需盘中确认后再决策。"
    )
    lines.append("")

    for entry in entries:
        lines.append(f"### {entry['ticker']}")
        historical_prior = dict(entry.get("historical_prior") or {})
        comps = dict(entry.get("payoff_review_lane_components") or {})
        prior_hit = comps.get("prior_next_high_hit_rate_at_threshold")
        if prior_hit is None:
            prior_hit = historical_prior.get("next_high_hit_rate_at_threshold")

        lines.append(f"- review_semantics: {entry.get('review_semantics') or 'review_only'}")
        lines.append(
            f"- payoff_review_lane_rank: {int(entry.get('payoff_review_lane_rank') or 0)}"
        )
        lines.append(
            f"- payoff_review_lane_score: {float(entry.get('payoff_review_lane_score') or 0.0):.4f}"
        )
        lines.append(
            "- payoff_components: "
            + ", ".join(
                [
                    f"prior_hit={format_float(prior_hit)}",
                    f"evaluable={int(comps.get('evaluable_count') or historical_prior.get('evaluable_count') or 0)}",
                    f"exec_quality={comps.get('execution_quality_label') or historical_prior.get('execution_quality_label') or 'n/a'}",
                ]
            )
        )
        lines.append(f"- decision: {entry.get('decision')}")
        lines.append(f"- candidate_source: {entry.get('candidate_source')}")
        append_brief_historical_prior_fields(
            lines,
            historical_prior,
            include_monitor_priority=True,
            include_execution_quality=True,
            include_execution_note=True,
        )
        lines.append(
            f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}"
        )
        append_brief_short_trade_metrics(lines, dict(entry.get("metrics") or {}))
        append_brief_historical_recent_examples(lines, historical_prior)
        append_gate_status_line(lines, entry.get("gate_status") or {})
        lines.append("")
