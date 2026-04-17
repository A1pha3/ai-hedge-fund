"""BTST Opening Watch Card — analysis and row building.

Rendering remains in btst_reporting.py due to callback injection dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.paper_trading._btst_reporting.entry_mode_utils import (
    _augment_execution_note,
    _selected_action_posture,
)
from src.paper_trading._btst_reporting.entry_transforms import (
    _apply_execution_quality_entry_mode,
    _build_catalyst_theme_shadow_watch_rows,
)
from src.paper_trading.btst_reporting_utils import (
    _as_float,
    _entry_mode_action_guidance,
    _execution_priority_rank,
    _monitor_priority_rank,
)


# ---------------------------------------------------------------------------
# Focus item building
# ---------------------------------------------------------------------------

def _build_opening_primary_focus_item(
    primary_entry: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not primary_entry:
        return None
    posture, trigger_rules = _selected_action_posture(
        primary_entry.get("preferred_entry_mode")
    )
    historical_prior = dict(primary_entry.get("historical_prior") or {})
    return {
        "ticker": primary_entry.get("ticker"),
        "focus_tier": "primary_entry",
        "monitor_priority": "execute",
        "execution_posture": posture,
        "score_target": primary_entry.get("score_target"),
        "preferred_entry_mode": primary_entry.get("preferred_entry_mode"),
        "why_now": ", ".join(primary_entry.get("top_reasons") or [])
        or "当前 short-trade 正式 selected。",
        "opening_plan": trigger_rules[0] if trigger_rules else "只在确认出现后执行。",
        "historical_summary": historical_prior.get("summary"),
        "execution_note": _augment_execution_note(
            primary_entry.get("preferred_entry_mode"), historical_prior
        ),
    }


def _build_opening_focus_item(
    entry: dict[str, Any],
    *,
    focus_tier: str,
    execution_posture: str,
    default_action: str,
    default_why_now: str,
    execution_note_mode: str = "historical",
    opening_plan_key: str | None = None,
) -> dict[str, Any]:
    historical_prior = dict(entry.get("historical_prior") or {})
    _, opening_plan = _entry_mode_action_guidance(
        entry.get("preferred_entry_mode"),
        default_action=default_action,
    )
    if opening_plan_key:
        opening_plan = str(entry.get(opening_plan_key) or opening_plan)
    execution_note = (
        _augment_execution_note(entry.get("preferred_entry_mode"), historical_prior)
        if execution_note_mode == "augment"
        else historical_prior.get("execution_note")
    )
    return {
        "ticker": entry.get("ticker"),
        "focus_tier": focus_tier,
        "monitor_priority": historical_prior.get("monitor_priority") or "unscored",
        "execution_posture": execution_posture,
        "score_target": entry.get("score_target"),
        "preferred_entry_mode": entry.get("preferred_entry_mode"),
        "why_now": ", ".join(entry.get("top_reasons") or []) or default_why_now,
        "opening_plan": opening_plan,
        "historical_summary": historical_prior.get("summary"),
        "execution_note": execution_note,
    }


def _build_opening_headline(
    *,
    primary_entry: dict[str, Any],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    upstream_shadow_summary: dict[str, Any],
) -> str:
    headline = "当前没有正式交易票，开盘只做观察。"
    if primary_entry:
        headline = "先看主票确认，再看 near-miss 和机会池是否出现升级信号。"
    elif near_miss_entries:
        headline = "当前没有正式主票，开盘只保留 near-miss 与机会池观察，不预设交易。"
    elif opportunity_pool_entries:
        headline = "当前只有机会池可跟踪，除非盘中新强度确认，否则不交易。"
    elif no_history_observer_entries:
        headline = "当前没有标准 BTST 机会池，只保留无历史先验观察，不预设交易。"
    elif risky_observer_entries:
        headline = "当前没有标准 BTST 机会池，只保留高风险盘中观察，不预设交易。"
    if catalyst_theme_frontier_priority.get("promoted_tickers"):
        headline = (
            headline.rstrip("。")
            + "；题材催化前沿优先跟踪 "
            + ", ".join(catalyst_theme_frontier_priority.get("promoted_tickers") or [])
            + "，但仍只做研究跟踪。"
        )
    if upstream_shadow_summary.get("shadow_candidate_count"):
        headline = (
            headline.rstrip("。")
            + "；上游影子召回关注 "
            + ", ".join(upstream_shadow_summary.get("top_focus_tickers") or [])
            + "。"
        )
    return headline


def _build_opening_watch_context(brief: dict[str, Any]) -> dict[str, Any]:
    selected_entries = [
        _apply_execution_quality_entry_mode(entry)
        for entry in list(brief.get("selected_entries") or [])
    ]
    return {
        "catalyst_theme_frontier_priority": dict(
            brief.get("catalyst_theme_frontier_priority") or {}
        ),
        "catalyst_theme_shadow_watch": _build_catalyst_theme_shadow_watch_rows(
            list(brief.get("catalyst_theme_shadow_entries") or [])
        ),
        "selected_entries": selected_entries,
        "near_miss_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("near_miss_entries") or [])
        ],
        "opportunity_pool_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("opportunity_pool_entries") or [])
        ],
        "no_history_observer_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("no_history_observer_entries") or [])
        ],
        "risky_observer_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("risky_observer_entries") or [])
        ],
        "primary_entry": _resolve_opening_primary_entry(brief, selected_entries),
        "upstream_shadow_summary": dict(brief.get("upstream_shadow_summary") or {}),
    }


def _resolve_opening_primary_entry(
    brief: dict[str, Any], selected_entries: list[dict[str, Any]]
) -> dict[str, Any]:
    primary_entry = dict(brief.get("primary_entry") or {})
    if not primary_entry and selected_entries:
        return dict(selected_entries[0])
    if primary_entry:
        return _apply_execution_quality_entry_mode(primary_entry)
    return {}


def _build_opening_focus_items(
    *,
    brief: dict[str, Any],
    primary_entry: dict[str, Any],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    focus_items = _build_primary_focus_items(primary_entry)
    focus_items.extend(_build_near_miss_focus_items(near_miss_entries))
    focus_items.extend(_build_opportunity_pool_focus_items(opportunity_pool_entries))
    focus_items.extend(_build_risky_observer_focus_items(risky_observer_entries))
    focus_items.extend(
        _build_no_history_observer_focus_items(no_history_observer_entries)
    )
    focus_items.extend(
        _build_research_upside_focus_items(
            list(brief.get("research_upside_radar_entries") or [])
        )
    )
    return focus_items


def _build_primary_focus_items(primary_entry: dict[str, Any]) -> list[dict[str, Any]]:
    primary_focus_item = _build_opening_primary_focus_item(primary_entry)
    return [primary_focus_item] if primary_focus_item else []


def _build_near_miss_focus_items(
    near_miss_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_opening_focus_item(
            entry,
            focus_tier="near_miss_watch",
            execution_posture="observe_only",
            default_action="只观察，不预设与主票同级的买入动作。",
            default_why_now="当前接近 near-miss 边界。",
            execution_note_mode="augment",
        )
        for entry in near_miss_entries
    ]


def _build_opportunity_pool_focus_items(
    opportunity_pool_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_opening_focus_item(
            entry,
            focus_tier="opportunity_pool",
            execution_posture="observe_for_upgrade_only",
            default_action=str(
                entry.get("promotion_trigger")
                or "只有盘中新增强度确认时，才允许从机会池升级。"
            ),
            default_why_now="结构未坏，但暂未进入正式 short-trade 名单。",
        )
        for entry in opportunity_pool_entries
    ]


def _build_risky_observer_focus_items(
    risky_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_opening_focus_item(
            entry,
            focus_tier="risky_observer",
            execution_posture="risk_observer_only",
            default_action="只做高风险盘中确认观察，不预设隔夜 BTST 升级。",
            default_why_now="当前属于高风险盘中观察桶。",
        )
        for entry in risky_observer_entries
    ]


def _build_no_history_observer_focus_items(
    no_history_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_opening_focus_item(
            entry,
            focus_tier="no_history_observer",
            execution_posture="observe_only_no_history",
            default_action="暂无可评估历史先验，只做盘中新证据观察，不预设 BTST 升级。",
            default_why_now="当前暂无可评估历史先验，只保留观察。",
        )
        for entry in no_history_observer_entries
    ]


def _build_research_upside_focus_items(
    research_upside_radar_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_opening_focus_item(
            entry,
            focus_tier="research_upside_radar",
            execution_posture="non_trade_learning_only",
            default_action="只做漏票学习，不加入当日 BTST 交易名单。",
            default_why_now="research 已选中但 BTST 未放行。",
            opening_plan_key="radar_note",
        )
        for entry in research_upside_radar_entries
    ]


def _sort_opening_focus_items(focus_items: list[dict[str, Any]]) -> None:
    focus_items.sort(
        key=lambda item: (
            0
            if item.get("focus_tier") == "primary_entry"
            else 1
            if item.get("focus_tier") == "near_miss_watch"
            else 2
            if item.get("focus_tier") == "opportunity_pool"
            else 3
            if item.get("focus_tier") == "no_history_observer"
            else 4,
            _monitor_priority_rank(item.get("monitor_priority")),
            _execution_priority_rank(
                (item.get("execution_note") and "medium") or "unscored"
            ),
            -_as_float(item.get("score_target")),
            str(item.get("ticker") or ""),
        )
    )


def _build_opening_watch_summary(
    *,
    brief: dict[str, Any],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    upstream_shadow_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "primary_count": len(brief.get("selected_entries") or []),
        "near_miss_count": len(brief.get("near_miss_entries") or []),
        "opportunity_pool_count": len(brief.get("opportunity_pool_entries") or []),
        "no_history_observer_count": len(no_history_observer_entries),
        "risky_observer_count": len(risky_observer_entries),
        "catalyst_theme_frontier_promoted_count": len(
            catalyst_theme_frontier_priority.get("promoted_tickers") or []
        ),
        "catalyst_theme_shadow_count": len(
            brief.get("catalyst_theme_shadow_entries") or []
        ),
        "upstream_shadow_candidate_count": int(
            upstream_shadow_summary.get("shadow_candidate_count") or 0
        ),
        "upstream_shadow_promotable_count": int(
            upstream_shadow_summary.get("promotable_count") or 0
        ),
    }


# ---------------------------------------------------------------------------
# Analysis entry point
# ---------------------------------------------------------------------------

def analyze_btst_opening_watch_card(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    # Lazy import to avoid circular dependency with btst_reporting.py
    from src.paper_trading.btst_reporting import _resolve_brief_analysis

    brief = _resolve_brief_analysis(
        input_path, trade_date=trade_date, next_trade_date=next_trade_date
    )
    opening_context = _build_opening_watch_context(brief)
    catalyst_theme_frontier_priority = opening_context[
        "catalyst_theme_frontier_priority"
    ]
    catalyst_theme_shadow_watch = opening_context["catalyst_theme_shadow_watch"]
    near_miss_entries = opening_context["near_miss_entries"]
    opportunity_pool_entries = opening_context["opportunity_pool_entries"]
    no_history_observer_entries = opening_context["no_history_observer_entries"]
    risky_observer_entries = opening_context["risky_observer_entries"]
    primary_entry = opening_context["primary_entry"]
    focus_items = _build_opening_focus_items(
        brief=brief,
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
    )
    _sort_opening_focus_items(focus_items)
    upstream_shadow_summary = opening_context["upstream_shadow_summary"]
    headline = _build_opening_headline(
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
        upstream_shadow_summary=upstream_shadow_summary,
    )

    return {
        "trade_date": brief.get("trade_date"),
        "next_trade_date": brief.get("next_trade_date"),
        "selection_target": brief.get("selection_target"),
        "headline": headline,
        "recommendation": brief.get("recommendation"),
        "summary": _build_opening_watch_summary(
            brief=brief,
            no_history_observer_entries=no_history_observer_entries,
            risky_observer_entries=risky_observer_entries,
            catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
            upstream_shadow_summary=upstream_shadow_summary,
        ),
        "focus_items": focus_items,
        "no_history_observer_entries": no_history_observer_entries,
        "risky_observer_entries": risky_observer_entries,
        "catalyst_theme_frontier_priority": catalyst_theme_frontier_priority,
        "catalyst_theme_shadow_watch": catalyst_theme_shadow_watch,
        "upstream_shadow_entries": list(brief.get("upstream_shadow_entries") or []),
        "upstream_shadow_summary": upstream_shadow_summary,
        "global_guardrails": [
            "selected 之外的对象默认都不是开盘直接交易名单。",
            "机会池只做覆盖扩容，不因情绪走强直接升级为正式交易票。",
            "题材催化影子池只做研究跟踪，不进入当日 BTST 交易名单。",
            "research 漏票雷达只做上涨线索学习，不加入当日 BTST 交易名单。",
            "若主票缺少确认信号，则允许空仓，不强行补票。",
        ],
        "source_paths": {
            "report_dir": brief.get("report_dir"),
            "snapshot_path": brief.get("snapshot_path"),
            "session_summary_path": brief.get("session_summary_path"),
        },
    }
