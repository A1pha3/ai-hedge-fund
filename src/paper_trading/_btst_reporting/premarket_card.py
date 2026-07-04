"""BTST Premarket Execution Card — analysis and action building.

Rendering remains in btst_reporting.py due to callback injection dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.paper_trading._btst_reporting.entry_builders import (
    _filter_execution_ready_entries,
)
from src.paper_trading._btst_reporting.entry_mode_utils import (
    _selected_action_posture,
    _selected_holding_contract_note,
)
from src.paper_trading._btst_reporting.entry_transforms import (
    _build_catalyst_theme_shadow_watch_rows,
)
from src.paper_trading._btst_reporting.execution_contract import (
    build_brief_execution_contract,
)
from src.paper_trading.btst_reporting_utils import (
    _entry_mode_action_guidance,
)
from src.utils.env_helpers import get_env_float, get_env_mode

# ---------------------------------------------------------------------------
# Environment overlays
# ---------------------------------------------------------------------------

_BTST_0422_P7_GAP_OVERLAY_MODE_ENV = "BTST_0422_P7_GAP_OVERLAY_MODE"
_BTST_0422_P7_GAP_OVERLAY_MODES = frozenset({"off", "report", "enforce"})
_BTST_0422_P7_GAP_WARN_THRESHOLD_ENV = "BTST_0422_P7_GAP_WARN_THRESHOLD"
_BTST_0422_P7_GAP_HALT_THRESHOLD_ENV = "BTST_0422_P7_GAP_HALT_THRESHOLD"


def _btst_0422_p7_gap_overlay_guardrail() -> str | None:
    mode = get_env_mode(_BTST_0422_P7_GAP_OVERLAY_MODE_ENV, "off")
    if mode not in _BTST_0422_P7_GAP_OVERLAY_MODES:
        mode = "off"
    if mode == "off":
        return None

    warn = abs(get_env_float(_BTST_0422_P7_GAP_WARN_THRESHOLD_ENV, 0.005))
    halt = abs(get_env_float(_BTST_0422_P7_GAP_HALT_THRESHOLD_ENV, 0.01))
    if warn <= 0:
        warn = 0.005
    if halt <= 0:
        halt = 0.01
    if halt < warn:
        halt = warn

    warn_pct = f"{warn * 100:.1f}%"
    halt_pct = f"{halt * 100:.1f}%"
    return f"Gap overlay (BTST 0422 P7/{mode}): 若 T+1 开盘相对 T 收盘跳空低开 ≤ -{warn_pct}，只允许确认后减仓入场；" f"若 ≤ -{halt_pct}，当日禁入。"


def _btst_regime_gate_guardrail(control_tower: dict[str, Any]) -> str | None:
    level = str(control_tower.get("regime_gate_level") or "").strip()
    if not level or level in {"n/a", "na", "none"}:
        return None

    if level == "risk_off":
        return "Regime gate (risk_off): 默认不做正式买入，只允许观察/确认性复审；" "若无明确修复信号则空仓。"

    if level in {"crisis", "halt"}:
        return f"Regime gate ({level}): 当日按门控降级执行，只允许确认后小仓试错或空仓。"

    return None


# ---------------------------------------------------------------------------
# Action building helpers
# ---------------------------------------------------------------------------


def _build_premarket_primary_action(
    primary_entry: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not primary_entry:
        return None

    posture, trigger_rules = _selected_action_posture(primary_entry.get("preferred_entry_mode"))
    historical_prior = dict(primary_entry.get("historical_prior") or {})
    if historical_prior.get("summary"):
        trigger_rules.insert(0, f"历史先验: {historical_prior['summary']}")
    if historical_prior.get("execution_note"):
        trigger_rules.append(f"执行先验: {historical_prior['execution_note']}")
    holding_contract_note = _selected_holding_contract_note(primary_entry.get("preferred_entry_mode"), historical_prior)
    if holding_contract_note:
        trigger_rules.append(f"持有 contract: {holding_contract_note}")
    return {
        "ticker": primary_entry.get("ticker"),
        "action_tier": "primary_entry",
        "execution_posture": posture,
        "watch_priority": historical_prior.get("monitor_priority") or "unscored",
        "execution_quality_label": historical_prior.get("execution_quality_label") or "unknown",
        "preferred_entry_mode": primary_entry.get("preferred_entry_mode"),
        "trigger_rules": trigger_rules,
        "avoid_rules": [
            "不把 near-miss 或 research-only 股票并入主执行名单。",
            "不因为开盘情绪强就跳过 breakout confirmation。",
        ],
        "evidence": list(primary_entry.get("top_reasons") or []),
        "positive_tags": list(primary_entry.get("positive_tags") or []),
        "metrics": dict(primary_entry.get("metrics") or {}),
        "historical_prior": historical_prior,
        "holding_contract_note": holding_contract_note,
    }


def _build_premarket_observer_action(
    entry: dict[str, Any],
    *,
    action_tier: str,
    execution_posture: str,
    default_action: str,
    secondary_rule: str,
    avoid_rules: list[str],
    include_rejection_reasons: bool,
) -> dict[str, Any]:
    historical_prior = dict(entry.get("historical_prior") or {})
    _, primary_watch_rule = _entry_mode_action_guidance(
        entry.get("preferred_entry_mode"),
        default_action=default_action,
    )
    trigger_rules = [primary_watch_rule, secondary_rule]
    if historical_prior.get("summary"):
        trigger_rules.insert(0, f"历史先验: {historical_prior['summary']}")
    evidence = list(entry.get("top_reasons") or [])
    if include_rejection_reasons:
        evidence += list(entry.get("rejection_reasons") or [])
    return {
        "ticker": entry.get("ticker"),
        "action_tier": action_tier,
        "execution_posture": execution_posture,
        "watch_priority": historical_prior.get("monitor_priority") or "unscored",
        "execution_quality_label": historical_prior.get("execution_quality_label") or "unknown",
        "preferred_entry_mode": entry.get("preferred_entry_mode"),
        "trigger_rules": trigger_rules,
        "avoid_rules": avoid_rules,
        "evidence": evidence,
        "metrics": dict(entry.get("metrics") or {}),
        "historical_prior": historical_prior,
    }


def _build_premarket_action_context(brief: dict[str, Any]) -> dict[str, Any]:
    selected_entries = _filter_execution_ready_entries(list(brief.get("selected_entries") or []))
    near_miss_entries = _filter_execution_ready_entries(list(brief.get("near_miss_entries") or []))
    opportunity_pool_entries = _filter_execution_ready_entries(list(brief.get("opportunity_pool_entries") or []))
    no_history_observer_entries = _filter_execution_ready_entries(list(brief.get("no_history_observer_entries") or []))
    risky_observer_entries = _filter_execution_ready_entries(list(brief.get("risky_observer_entries") or []))
    runner_recall_review_entries = _filter_execution_ready_entries(list(brief.get("runner_recall_review_entries") or []))
    primary_candidates = _filter_execution_ready_entries([brief.get("primary_entry")] if brief.get("primary_entry") else [])
    primary_entry = primary_candidates[0] if primary_candidates else (selected_entries[0] if selected_entries else None)
    return {
        "selected_entries": selected_entries,
        "primary_entry": primary_entry,
        "catalyst_theme_frontier_priority": dict(brief.get("catalyst_theme_frontier_priority") or {}),
        "rollout_validation": dict(brief.get("rollout_validation") or {}),
        "catalyst_theme_shadow_watch": _build_catalyst_theme_shadow_watch_rows(list(brief.get("catalyst_theme_shadow_entries") or [])),
        "primary_action": _build_premarket_primary_action(primary_entry),
        "watch_actions": _build_watch_actions(near_miss_entries),
        "opportunity_actions": _build_opportunity_actions(opportunity_pool_entries),
        "runner_recall_review_actions": _build_runner_recall_review_actions(runner_recall_review_entries),
        "no_history_observer_actions": _build_no_history_observer_actions(no_history_observer_entries),
        "risky_observer_actions": _build_risky_observer_actions(risky_observer_entries),
        "upstream_shadow_summary": dict(brief.get("upstream_shadow_summary") or {}),
    }


def _attach_primary_action_contract(
    primary_action: dict[str, Any] | None,
    primary_semantic_action: dict[str, Any],
) -> dict[str, Any] | None:
    if not primary_action:
        return primary_action
    if not primary_semantic_action:
        return primary_action
    attached = dict(primary_action)
    for field in (
        "report_mode",
        "execution_state",
        "max_allowed_state_today",
        "formal_buy_allowed",
        "allowed_sections",
        "release_authority",
        "state_reason_codes",
        "veto_owner",
    ):
        value = primary_semantic_action.get(field)
        if value not in (None, "", [], {}, ()):  # pragma: no branch - simple field gate
            attached[field] = value
    return attached


def _build_watch_actions(
    near_miss_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_premarket_observer_action(
            entry,
            action_tier="watch_only",
            execution_posture="observe_only",
            default_action="仅做盘中强度跟踪，不预设主买入动作。",
            secondary_rule="若当日需要转为可执行对象，应先回看 short-trade score 与盘中确认信号。",
            avoid_rules=[
                "near_miss 不能与 selected 同级表达。",
                "没有新增确认前，不把它视为默认替补主票。",
            ],
            include_rejection_reasons=False,
        )
        for entry in near_miss_entries
    ]


def _build_opportunity_actions(
    opportunity_pool_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_premarket_observer_action(
            entry,
            action_tier="conditional_watch_upgrade",
            execution_posture="observe_for_upgrade_only",
            default_action=str(entry.get("promotion_trigger") or "只有盘中新增强度确认时，才允许从机会池升级。"),
            secondary_rule="默认不在开盘前直接升级为主票或近似主票。",
            avoid_rules=[
                "机会池不是默认交易名单，不因情绪拉升直接入场。",
                "若结构重新转弱或强度未延续，则继续留在非交易状态。",
            ],
            include_rejection_reasons=True,
        )
        for entry in opportunity_pool_entries
    ]


def _build_no_history_observer_actions(
    no_history_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_premarket_observer_action(
            entry,
            action_tier="no_history_observer_watch",
            execution_posture="observe_only_no_history",
            default_action="暂无可评估历史先验，只做盘中新证据观察，不预设 BTST 升级。",
            secondary_rule="默认不升级为主票；只有出现新的独立强确认，才考虑重新评估。",
            avoid_rules=[
                "缺少可评估历史先验时，不把它视为标准机会池升级对象。",
                "没有新的盘中强确认前，不预设隔夜 BTST 持有。",
            ],
            include_rejection_reasons=True,
        )
        for entry in no_history_observer_entries
    ]


def _build_runner_recall_review_actions(
    runner_recall_review_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_premarket_observer_action(
            entry,
            action_tier="runner_recall_review",
            execution_posture="shadow_review_only",
            default_action="只做 payoff-first runner recall 复审，不直接加入当日 BTST 交易名单。",
            secondary_rule="只有盘中出现延迟爆发/催化共振/收盘强确认时，才允许人工复审是否提升观察优先级。",
            avoid_rules=[
                "runner recall 复审层不等于 formal BTST 执行名单。",
                "没有新增确认前，不把 watchlist_filter_diagnostics 漏票直接升级为主票。",
            ],
            include_rejection_reasons=True,
        )
        for entry in runner_recall_review_entries
    ]


def _build_risky_observer_actions(
    risky_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_premarket_observer_action(
            entry,
            action_tier="risky_observer_watch",
            execution_posture="observe_only_high_risk",
            default_action="只做高风险盘中观察，不做标准 BTST 升级预案。",
            secondary_rule="默认不升级为主票，也不把隔夜持有当成基础执行路径。",
            avoid_rules=[
                "高风险观察桶不与标准机会池混用。",
                "没有新的强确认时，不把它视为 BTST 候补交易对象。",
            ],
            include_rejection_reasons=True,
        )
        for entry in risky_observer_entries
    ]


def _build_premarket_card_summary(
    *,
    brief: dict[str, Any],
    primary_action: dict[str, Any] | None,
    watch_actions: list[dict[str, Any]],
    opportunity_actions: list[dict[str, Any]],
    runner_recall_review_actions: list[dict[str, Any]],
    no_history_observer_actions: list[dict[str, Any]],
    risky_observer_actions: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    upstream_shadow_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "primary_count": 1 if primary_action else 0,
        "watch_count": len(watch_actions),
        "opportunity_pool_count": len(opportunity_actions),
        "runner_recall_review_count": len(runner_recall_review_actions),
        "no_history_observer_count": len(no_history_observer_actions),
        "risky_observer_count": len(risky_observer_actions),
        "catalyst_theme_frontier_promoted_count": len(catalyst_theme_frontier_priority.get("promoted_tickers") or []),
        "catalyst_theme_shadow_count": len(brief.get("catalyst_theme_shadow_entries") or []),
        "upstream_shadow_candidate_count": int(upstream_shadow_summary.get("shadow_candidate_count") or 0),
        "upstream_shadow_promotable_count": int(upstream_shadow_summary.get("promotable_count") or 0),
        "excluded_research_count": len(brief.get("excluded_research_entries") or []),
    }


# ---------------------------------------------------------------------------
# Analysis entry point
# ---------------------------------------------------------------------------


def analyze_btst_premarket_execution_card(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    from src.paper_trading._btst_reporting.brief_resolver import _resolve_brief_analysis

    brief = _resolve_brief_analysis(input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    action_context = _build_premarket_action_context(brief)
    execution_contract_context = build_brief_execution_contract(
        brief=brief,
        selected_entries=list(action_context["selected_entries"] or []),
        early_runner_status="unavailable",
    )
    catalyst_theme_frontier_priority = action_context["catalyst_theme_frontier_priority"]
    catalyst_theme_shadow_watch = action_context["catalyst_theme_shadow_watch"]
    primary_action = _attach_primary_action_contract(
        action_context["primary_action"],
        execution_contract_context["primary_semantic_action"],
    )
    watch_actions = action_context["watch_actions"]
    opportunity_actions = action_context["opportunity_actions"]
    runner_recall_review_actions = action_context["runner_recall_review_actions"]
    no_history_observer_actions = action_context["no_history_observer_actions"]
    risky_observer_actions = action_context["risky_observer_actions"]
    upstream_shadow_summary = action_context["upstream_shadow_summary"]
    rollout_validation = action_context["rollout_validation"]

    global_guardrails = [
        "主执行名单只认 short-trade selected，不把 research selected 自动等价成短线可交易票。",
        "near-miss 默认只做观察，不预设与主票同级的买入动作。",
        "机会池只用于补充盯盘覆盖面，不自动升级为正式交易对象。",
        "runner recall 复审层只做影子复审，不把 watchlist_filter_diagnostics 漏票直接并入正式交易名单。",
        "题材催化影子池只做研究跟踪，不进入当日 BTST 交易名单。",
        "若 selected 当日没有出现确认信号，则允许空仓而不是强行交易。",
    ]
    gap_guardrail = _btst_0422_p7_gap_overlay_guardrail()
    if gap_guardrail:
        global_guardrails.append(gap_guardrail)

    regime_guardrail = _btst_regime_gate_guardrail(dict(execution_contract_context.get("control_tower") or {}))
    if regime_guardrail:
        global_guardrails.append(regime_guardrail)

    return {
        "trade_date": brief.get("trade_date"),
        "next_trade_date": brief.get("next_trade_date"),
        "selection_target": brief.get("selection_target"),
        "summary": _build_premarket_card_summary(
            brief=brief,
            primary_action=primary_action,
            watch_actions=watch_actions,
            opportunity_actions=opportunity_actions,
            runner_recall_review_actions=runner_recall_review_actions,
            no_history_observer_actions=no_history_observer_actions,
            risky_observer_actions=risky_observer_actions,
            catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
            upstream_shadow_summary=upstream_shadow_summary,
        ),
        "recommendation": brief.get("recommendation"),
        "execution_contract": execution_contract_context["execution_contract"],
        "primary_action": primary_action,
        "watch_actions": watch_actions,
        "opportunity_actions": opportunity_actions,
        "runner_recall_review_actions": runner_recall_review_actions,
        "no_history_observer_actions": no_history_observer_actions,
        "risky_observer_actions": risky_observer_actions,
        "catalyst_theme_frontier_priority": catalyst_theme_frontier_priority,
        "catalyst_theme_shadow_watch": catalyst_theme_shadow_watch,
        "rollout_validation": rollout_validation,
        "upstream_shadow_entries": list(brief.get("upstream_shadow_entries") or []),
        "upstream_shadow_summary": upstream_shadow_summary,
        "excluded_research_entries": list(brief.get("excluded_research_entries") or []),
        "global_guardrails": global_guardrails,
        "source_paths": {
            "report_dir": brief.get("report_dir"),
            "snapshot_path": brief.get("snapshot_path"),
            "session_summary_path": brief.get("session_summary_path"),
        },
    }
