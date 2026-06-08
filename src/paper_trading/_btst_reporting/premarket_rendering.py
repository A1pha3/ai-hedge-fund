"""Premarket execution card markdown rendering.

Extracted from ``btst_reporting.py`` to keep the public facade thin.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.paper_trading.btst_reporting_utils import (
 _format_float,
 _format_historical_payoff_note,
 _format_rollout_value,
)


def append_premarket_overview_markdown(lines: list[str], card: dict[str, Any]) -> None:
    summary = dict(card.get("summary") or {})
    execution_contract = dict(card.get("execution_contract") or {})
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
        f"- runner_recall_review_count: {summary.get('runner_recall_review_count')}"
    )
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
    if execution_contract:
        lines.append(
            f"- report_mode: {execution_contract.get('report_mode') or 'n/a'}"
        )
        lines.append(
            f"- effective_trade_bias: {execution_contract.get('effective_trade_bias') or 'n/a'}"
        )
        if execution_contract.get("execution_state") not in (None, ""):
            lines.append(
                f"- execution_state: {execution_contract.get('execution_state')}"
            )
        if execution_contract.get("max_allowed_state_today") not in (None, ""):
            lines.append(
                f"- max_allowed_state_today: {execution_contract.get('max_allowed_state_today')}"
            )
        lines.append(
            f"- release_authority: {execution_contract.get('release_authority') or 'none'}"
        )
    lines.append("")



def append_premarket_action_block(
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
    if entry.get("execution_state") not in (None, ""):
        lines.append(f"{prefix}execution_state: {entry.get('execution_state')}")
    if entry.get("max_allowed_state_today") not in (None, ""):
        lines.append(
            f"{prefix}max_allowed_state_today: {entry.get('max_allowed_state_today')}"
        )
    if entry.get("release_authority") not in (None, ""):
        lines.append(
            f"{prefix}release_authority: {entry.get('release_authority')}"
        )
    lines.append(f"{prefix}preferred_entry_mode: {entry.get('preferred_entry_mode')}")
    lines.append(
        f"{prefix}historical_summary: {(entry.get('historical_prior') or {}).get('summary') or 'n/a'}"
    )
    payoff_note = _format_historical_payoff_note(
        dict(entry.get("historical_prior") or {})
    )
    if payoff_note:
        lines.append(f"{prefix}historical_win_rate_payoff: {payoff_note}")
    lines.append(f"{prefix}evidence: {', '.join(entry.get('evidence') or []) or 'n/a'}")
    lines.append("- trigger_rules:")
    lines.extend(f"  - {item}" for item in entry.get("trigger_rules") or [])
    lines.append("- avoid_rules:")
    lines.extend(f"  - {item}" for item in entry.get("avoid_rules") or [])
    lines.append("")


def append_premarket_action_section(
    lines: list[str], title: str, entries: list[dict[str, Any]]
) -> None:
    _append_titled_indexed_section(
        lines,
        title=f"## {title}",
        items=entries,
        render_item=lambda inner_lines, entry, index: append_premarket_action_block(
            inner_lines, entry, indexed=index
        ),
    )


def append_candidate_watch_scoring_fields(
    lines: list[str], item: dict[str, Any]
) -> None:
    lines.append(f"- candidate_score: {_format_float(item.get('candidate_score'))}")
    lines.append(f"- filter_reason: {item.get('filter_reason') or 'n/a'}")
    lines.append(f"- total_shortfall: {_format_float(item.get('total_shortfall'))}")
    lines.append(f"- failed_threshold_count: {item.get('failed_threshold_count')}")
    lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")



def append_candidate_watch_reason_tags(
    lines: list[str], item: dict[str, Any], *, reasons_label: str
) -> None:
    lines.append(
        f"- {reasons_label}: {', '.join(item.get('top_reasons') or []) or 'n/a'}"
    )
    lines.append(
        f"- positive_tags: {', '.join(item.get('positive_tags') or []) or 'n/a'}"
    )


def append_premarket_excluded_entries_markdown(
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


def append_premarket_primary_action_markdown(
    lines: list[str], primary_action: Any
) -> None:
    lines.append("## Primary Action")
    if not primary_action:
        _append_none_block(lines)
        return
    append_premarket_action_block(lines, dict(primary_action))


def append_premarket_rollout_validation_markdown(
    lines: list[str], rollout_validation: dict[str, Any]
) -> None:
    lines.append("## Governed Rollout 观察")
    lines.append(f"- status: {rollout_validation.get('status') or 'unavailable'}")
    lines.append(f"- primary_lane: {rollout_validation.get('primary_lane') or 'n/a'}")
    lines.append(f"- summary: {rollout_validation.get('summary') or 'n/a'}")
    lines.append(
        f"- selected_hit_rate_15pct: {_format_rollout_value(rollout_validation.get('selected_hit_rate_15pct'), 4)} -> {_format_rollout_value(rollout_validation.get('shadow_hit_rate_15pct'), 4)}"
    )
    lines.append(f"- selected_count_delta: {_format_rollout_value(rollout_validation.get('selected_count_delta'))}")
    lines.append(f"- execution_eligible_delta: {_format_rollout_value(rollout_validation.get('execution_eligible_delta'))}")
    lines.append(f"- buy_order_delta: {_format_rollout_value(rollout_validation.get('buy_order_delta'))}")
    lines.append("")

def _append_titled_indexed_section(
 lines: list[str],
 *,
 title: str,
 items: list[dict[str, Any]],
 render_item: Callable[[list[str], dict[str, Any], int], None],
) -> None:
 from src.paper_trading.btst_shared_markdown_helpers import (
 append_none_block as _none_impl,
 append_titled_indexed_section as _impl,
 )

 _impl(
 lines,
 title=title,
 items=items,
 render_item=render_item,
 append_none_block_fn=_none_impl,
 )


def _append_none_block(lines: list[str]) -> None:
 from src.paper_trading.btst_shared_markdown_helpers import append_none_block as _impl

 _impl(lines)
