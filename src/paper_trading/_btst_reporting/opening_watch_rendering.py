"""Opening watch card markdown rendering.

Extracted from ``btst_reporting.py`` to keep the public facade thin.
"""

from __future__ import annotations

from typing import Any


def append_opening_watch_overview_markdown(
    lines: list[str], card: dict[str, Any]
) -> None:
    summary = dict(card.get("summary") or {})
    execution_contract = dict(card.get("execution_contract") or {})
    lines.append("# BTST Opening Watch Card")
    lines.append("")
    lines.append("## Opening Headline")
    lines.append(f"- trade_date: {card.get('trade_date')}")
    lines.append(f"- next_trade_date: {card.get('next_trade_date') or 'n/a'}")
    lines.append(f"- selection_target: {card.get('selection_target')}")
    lines.append(f"- headline: {card.get('headline')}")
    lines.append(f"- primary_count: {summary.get('primary_count')}")
    lines.append(f"- near_miss_count: {summary.get('near_miss_count')}")
    lines.append(f"- opportunity_pool_count: {summary.get('opportunity_pool_count')}")
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


def append_opening_frontier_entries(
    lines: list[str], items: list[dict[str, Any]]
) -> None:
    from src.paper_trading.btst_reporting import (
     _append_catalyst_theme_watch_markdown as _impl,
    )

    _impl(
        lines,
        title="",
        items=items,
        focus_tier="catalyst_theme_frontier_priority",
        execution_posture="research_followup_priority",
    )
