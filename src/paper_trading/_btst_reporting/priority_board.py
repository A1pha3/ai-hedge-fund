"""BTST Priority Board — analysis and row building.

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
# Row building
# ---------------------------------------------------------------------------

def _build_priority_board_row(
    entry: dict[str, Any],
    *,
    lane: str,
    actionability: str,
    default_action: str,
    default_why_now: str,
    execution_note_mode: str = "historical",
    historical_default_monitor_priority: str = "unscored",
    opening_plan_key: str | None = None,
    research_score_target: Any | None = None,
) -> dict[str, Any]:
    historical_prior = dict(entry.get("historical_prior") or {})
    if lane in {"primary_entry", "selected_backup"}:
        _, trigger_rules = _selected_action_posture(entry.get("preferred_entry_mode"))
        suggested_action = trigger_rules[0] if trigger_rules else "盘中确认后再执行。"
    else:
        _, suggested_action = _entry_mode_action_guidance(
            entry.get("preferred_entry_mode"),
            default_action=default_action,
        )
    if opening_plan_key:
        suggested_action = str(entry.get(opening_plan_key) or suggested_action)
    execution_note = (
        _augment_execution_note(entry.get("preferred_entry_mode"), historical_prior)
        if execution_note_mode == "augment"
        else historical_prior.get("execution_note")
    )
    return {
        "ticker": entry.get("ticker"),
        "lane": lane,
        "actionability": actionability,
        "monitor_priority": historical_prior.get("monitor_priority")
        or historical_default_monitor_priority,
        "execution_priority": historical_prior.get("execution_priority") or "unscored",
        "execution_quality_label": historical_prior.get("execution_quality_label")
        or "unknown",
        "score_target": entry.get("score_target"),
        "research_score_target": research_score_target,
        "preferred_entry_mode": entry.get("preferred_entry_mode"),
        "why_now": ", ".join(entry.get("top_reasons") or []) or default_why_now,
        "suggested_action": suggested_action,
        "historical_summary": historical_prior.get("summary"),
        "execution_note": execution_note,
    }


def _build_priority_board_headline(
    *,
    brief: dict[str, Any],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
) -> str:
    headline = "当前没有可执行主票，priority board 只保留观察与漏票线索。"
    if brief.get("primary_entry"):
        headline = "先执行主票确认，再按 near-miss、机会池、research 漏票雷达递减关注。"
    elif brief.get("near_miss_entries"):
        headline = "当前没有主票，优先看 near-miss，其次看机会池和 research 漏票雷达。"
    elif no_history_observer_entries:
        headline = "当前没有标准 BTST 候选，只保留无历史先验观察与研究跟踪。"
    elif risky_observer_entries:
        headline = "当前没有标准 BTST 候选，只有高风险盘中观察与研究跟踪。"
    if catalyst_theme_frontier_priority.get("promoted_tickers"):
        headline = (
            headline.rstrip("。")
            + "；题材催化前沿 research priority 为 "
            + ", ".join(catalyst_theme_frontier_priority.get("promoted_tickers") or [])
            + "。"
        )
    return headline


def _build_priority_board_context(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalyst_theme_frontier_priority": dict(
            brief.get("catalyst_theme_frontier_priority") or {}
        ),
        "catalyst_theme_shadow_watch": _build_catalyst_theme_shadow_watch_rows(
            list(brief.get("catalyst_theme_shadow_entries") or [])
        ),
        "selected_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("selected_entries") or [])
        ],
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
    }


def _build_priority_board_rows(
    *,
    brief: dict[str, Any],
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        *_build_selected_priority_rows(selected_entries),
        *_build_near_miss_priority_rows(near_miss_entries),
        *_build_opportunity_pool_priority_rows(opportunity_pool_entries),
        *_build_no_history_observer_priority_rows(no_history_observer_entries),
        *_build_risky_observer_priority_rows(risky_observer_entries),
        *_build_research_upside_priority_rows(
            list(brief.get("research_upside_radar_entries") or [])
        ),
    ]


def _build_selected_priority_rows(
    selected_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="primary_entry" if index == 0 else "selected_backup",
            actionability="trade_candidate",
            default_action="盘中确认后再执行。",
            default_why_now="当前 short-trade selected。",
            execution_note_mode="augment",
            historical_default_monitor_priority="high",
        )
        for index, entry in enumerate(selected_entries)
    ]


def _build_near_miss_priority_rows(
    near_miss_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="near_miss_watch",
            actionability="watch_only",
            default_action="仅做盘中跟踪，不预设主买入动作。",
            default_why_now="当前接近 near-miss 边界。",
            execution_note_mode="augment",
        )
        for entry in near_miss_entries
    ]


def _build_opportunity_pool_priority_rows(
    opportunity_pool_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="opportunity_pool",
            actionability="upgrade_only",
            default_action=str(
                entry.get("promotion_trigger") or "只有盘中新强度确认时才升级。"
            ),
            default_why_now="结构未坏但仍在机会池。",
        )
        for entry in opportunity_pool_entries
    ]


def _build_no_history_observer_priority_rows(
    no_history_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="no_history_observer",
            actionability="observe_only_no_history",
            default_action=str(
                entry.get("promotion_trigger")
                or "暂无可评估历史先验，只做盘中新证据观察。"
            ),
            default_why_now="暂无可评估历史先验。",
        )
        for entry in no_history_observer_entries
    ]


def _build_risky_observer_priority_rows(
    risky_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="risky_observer",
            actionability="high_risk_watch_only",
            default_action="只做高风险盘中观察，不做标准 BTST 升级。",
            default_why_now="当前属于高风险观察桶。",
        )
        for entry in risky_observer_entries
    ]


def _build_research_upside_priority_rows(
    research_upside_radar_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="research_upside_radar",
            actionability="non_trade_learning_only",
            default_action="只做漏票学习，不加入当日 BTST 交易名单。",
            default_why_now="research 已选中但 BTST 未放行。",
            opening_plan_key="radar_note",
            research_score_target=entry.get("research_score_target"),
        )
        for entry in research_upside_radar_entries
    ]


def _sort_priority_board_rows(priority_rows: list[dict[str, Any]]) -> None:
    lane_rank = {
        "primary_entry": 0,
        "selected_backup": 1,
        "near_miss_watch": 2,
        "opportunity_pool": 3,
        "no_history_observer": 4,
        "risky_observer": 5,
        "research_upside_radar": 6,
    }
    priority_rows.sort(
        key=lambda row: (
            lane_rank.get(str(row.get("lane") or "research_upside_radar"), 9),
            _monitor_priority_rank(row.get("monitor_priority")),
            _execution_priority_rank(row.get("execution_priority")),
            -(row.get("research_score_target") or 0.0),
            -_as_float(row.get("score_target")),
            str(row.get("ticker") or ""),
        )
    )


def _build_priority_board_summary(
    *,
    brief: dict[str, Any],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
) -> dict[str, Any]:
    return {
        "primary_count": len(brief.get("selected_entries") or []),
        "near_miss_count": len(brief.get("near_miss_entries") or []),
        "opportunity_pool_count": len(brief.get("opportunity_pool_entries") or []),
        "no_history_observer_count": len(no_history_observer_entries),
        "risky_observer_count": len(risky_observer_entries),
        "research_upside_radar_count": len(
            brief.get("research_upside_radar_entries") or []
        ),
        "catalyst_theme_count": len(brief.get("catalyst_theme_entries") or []),
        "catalyst_theme_frontier_promoted_count": len(
            catalyst_theme_frontier_priority.get("promoted_tickers") or []
        ),
        "catalyst_theme_shadow_count": len(
            brief.get("catalyst_theme_shadow_entries") or []
        ),
    }


# ---------------------------------------------------------------------------
# Analysis entry point
# ---------------------------------------------------------------------------

def analyze_btst_next_day_priority_board(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    # Lazy import to avoid circular dependency with btst_reporting.py
    from src.paper_trading.btst_reporting import _resolve_brief_analysis

    brief = _resolve_brief_analysis(
        input_path, trade_date=trade_date, next_trade_date=next_trade_date
    )
    board_context = _build_priority_board_context(brief)
    catalyst_theme_frontier_priority = board_context["catalyst_theme_frontier_priority"]
    catalyst_theme_shadow_watch = board_context["catalyst_theme_shadow_watch"]
    selected_entries = board_context["selected_entries"]
    near_miss_entries = board_context["near_miss_entries"]
    opportunity_pool_entries = board_context["opportunity_pool_entries"]
    no_history_observer_entries = board_context["no_history_observer_entries"]
    risky_observer_entries = board_context["risky_observer_entries"]
    priority_rows = _build_priority_board_rows(
        brief=brief,
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
    )
    _sort_priority_board_rows(priority_rows)

    headline = _build_priority_board_headline(
        brief=brief,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
    )

    return {
        "trade_date": brief.get("trade_date"),
        "next_trade_date": brief.get("next_trade_date"),
        "selection_target": brief.get("selection_target"),
        "headline": headline,
        "summary": _build_priority_board_summary(
            brief=brief,
            no_history_observer_entries=no_history_observer_entries,
            risky_observer_entries=risky_observer_entries,
            catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
        ),
        "priority_rows": priority_rows,
        "catalyst_theme_frontier_priority": catalyst_theme_frontier_priority,
        "catalyst_theme_shadow_watch": catalyst_theme_shadow_watch,
        "global_guardrails": [
            "priority board 只负责排序和分层，不改变 short-trade admission 默认语义。",
            "题材催化影子池只做研究跟踪，不进入当日 BTST 交易名单。",
            "research_upside_radar 只做上涨线索学习，不进入当日 BTST 交易名单。",
            "所有交易候选都仍需盘中确认，不因历史先验直接跳过执行 guardrail。",
        ],
        "source_paths": {
            "report_dir": brief.get("report_dir"),
            "snapshot_path": brief.get("snapshot_path"),
            "session_summary_path": brief.get("session_summary_path"),
        },
    }
