from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


BuildMaterialChangeAnchor = Callable[..., dict[str, Any]]
AppendOpenReadyMaterialAnchorFocus = Callable[[list[str], dict[str, Any]], None]


def append_open_ready_basis_focus(operator_focus: list[str], comparison_basis: str, comparison_scope: str) -> None:
    if comparison_basis == "baseline_captured":
        operator_focus.append("首个 open-ready delta 基线已捕获；下一轮 nightly 后将开始提供完整 lane / replay 差分。")
    elif comparison_basis == "previous_btst_report":
        operator_focus.append("当前已生成 report 级 delta；完整治理 lane 差分将在下一轮 nightly 历史快照后可用。")
    elif comparison_scope == "same_report_rerun":
        operator_focus.append("当前 delta 对比的是同一份 report 的上一版 nightly 快照，用于识别复刷变化，而不是跨 report 切换。")


def append_open_ready_priority_focus(operator_focus: list[str], priority_delta: dict[str, Any]) -> None:
    if priority_delta.get("headline_changed"):
        operator_focus.append(f"开盘 headline 已变化：{priority_delta.get('previous_headline') or 'n/a'} -> {priority_delta.get('current_headline') or 'n/a'}")
    if priority_delta.get("added_tickers"):
        operator_focus.append("新增观察对象: " + ", ".join(item.get("ticker") or "" for item in priority_delta.get("added_tickers") or []))
    if priority_delta.get("removed_tickers"):
        operator_focus.append("移出观察对象: " + ", ".join(item.get("ticker") or "" for item in priority_delta.get("removed_tickers") or []))


def append_open_ready_governance_focus(operator_focus: list[str], governance_delta: dict[str, Any]) -> None:
    if governance_delta.get("available") and governance_delta.get("changed_lane_count"):
        operator_focus.append("治理 lane 发生变化: " + ", ".join(change.get("lane_id") or "" for change in governance_delta.get("lane_changes") or []))


def append_open_ready_replay_focus(operator_focus: list[str], replay_delta: dict[str, Any]) -> None:
    if not (replay_delta.get("available") and replay_delta.get("has_changes")):
        return
    if replay_delta.get("comparison_basis") == "nightly_history":
        operator_focus.append(
            f"replay cohort 变化: report_count {replay_delta.get('report_count_delta'):+d}, short_trade_only {replay_delta.get('short_trade_only_report_count_delta'):+d}。"
        )
        return
    if replay_delta.get("comparison_basis") == "previous_btst_report":
        summary_delta = dict(replay_delta.get("summary_delta") or {})
        operator_focus.append("本轮相对上一份 BTST 报告的观察层变化: " + ", ".join(f"{key} {int(value):+d}" for key, value in summary_delta.items() if int(value) != 0))


def append_open_ready_frontier_focus(operator_focus: list[str], delta: dict[str, Any], *, label: str, added_key: str, status_label: str) -> None:
    if not (delta.get("available") and delta.get("has_changes")):
        return
    added_values = list(delta.get(added_key) or [])
    if added_values:
        operator_focus.append(f"{label}: " + ", ".join(added_values))
        return
    if delta.get("status_changed"):
        operator_focus.append(f"{status_label}: {delta.get('previous_status') or 'n/a'} -> {delta.get('current_status') or 'n/a'}。")
        return
    if delta.get("comparison_note"):
        operator_focus.append(str(delta.get("comparison_note")))


def append_open_ready_action_focus(operator_focus: list[str], delta_sections: dict[str, Any]) -> None:
    top_priority_action_delta = dict(delta_sections.get("top_priority_action_delta") or {})
    selected_outcome_contract_delta = dict(delta_sections.get("selected_outcome_contract_delta") or {})
    carryover_peer_proof_delta = dict(delta_sections.get("carryover_peer_proof_delta") or {})
    carryover_promotion_gate_delta = dict(delta_sections.get("carryover_promotion_gate_delta") or {})
    if top_priority_action_delta.get("available") and top_priority_action_delta.get("has_changes"):
        operator_focus.append(
            f"control tower 顶级动作切换: {top_priority_action_delta.get('previous_source') or 'n/a'} -> {top_priority_action_delta.get('current_source') or 'n/a'} "
            f"({top_priority_action_delta.get('previous_title') or 'n/a'} -> {top_priority_action_delta.get('current_title') or 'n/a'})."
        )
    if selected_outcome_contract_delta.get("available") and selected_outcome_contract_delta.get("has_changes"):
        operator_focus.append(
            f"selected contract 变化: {selected_outcome_contract_delta.get('previous_focus_ticker') or 'n/a'} / "
            f"{selected_outcome_contract_delta.get('previous_focus_overall_contract_verdict') or 'n/a'} -> "
            f"{selected_outcome_contract_delta.get('current_focus_ticker') or 'n/a'} / "
            f"{selected_outcome_contract_delta.get('current_focus_overall_contract_verdict') or 'n/a'}。"
        )
    if carryover_peer_proof_delta.get("available") and carryover_peer_proof_delta.get("has_changes"):
        operator_focus.append(
            f"carryover peer proof 变化: focus {carryover_peer_proof_delta.get('previous_focus_ticker') or 'n/a'} -> {carryover_peer_proof_delta.get('current_focus_ticker') or 'n/a'}, "
            f"promotion review {carryover_peer_proof_delta.get('previous_focus_promotion_review_verdict') or 'n/a'} -> {carryover_peer_proof_delta.get('current_focus_promotion_review_verdict') or 'n/a'}。"
        )
    if carryover_promotion_gate_delta.get("available") and carryover_promotion_gate_delta.get("has_changes"):
        operator_focus.append(
            f"carryover promotion gate 变化: focus {carryover_promotion_gate_delta.get('previous_focus_ticker') or 'n/a'} -> {carryover_promotion_gate_delta.get('current_focus_ticker') or 'n/a'}, "
            f"verdict {carryover_promotion_gate_delta.get('previous_focus_gate_verdict') or 'n/a'} -> {carryover_promotion_gate_delta.get('current_focus_gate_verdict') or 'n/a'}。"
        )


def append_open_ready_score_fail_focus(operator_focus: list[str], score_fail_delta: dict[str, Any]) -> None:
    if not (score_fail_delta.get("available") and score_fail_delta.get("has_changes") and not score_fail_delta.get("added_priority_tickers")):
        return
    if score_fail_delta.get("added_top_rescue_tickers"):
        operator_focus.append("score-fail frontier 新增 near-miss rescue 票: " + ", ".join(score_fail_delta.get("added_top_rescue_tickers") or []))
    elif score_fail_delta.get("comparison_note") and not score_fail_delta.get("status_changed"):
        operator_focus.append(str(score_fail_delta.get("comparison_note")))


def append_open_ready_stability_focus(operator_focus: list[str]) -> None:
    if not operator_focus:
        operator_focus.append(
            "本轮相对上一轮没有检测到 priority / governance / replay / score-fail frontier / top priority action / selected contract / carryover peer proof / carryover promotion gate 的结构变化，可视为稳定复跑。"
        )


def build_open_ready_operator_focus(comparison_basis: str, comparison_scope: str, delta_sections: dict[str, Any]) -> list[str]:
    operator_focus: list[str] = []
    append_open_ready_basis_focus(operator_focus, comparison_basis, comparison_scope)
    append_open_ready_priority_focus(operator_focus, dict(delta_sections.get("priority_delta") or {}))
    append_open_ready_governance_focus(operator_focus, dict(delta_sections.get("governance_delta") or {}))
    append_open_ready_replay_focus(operator_focus, dict(delta_sections.get("replay_delta") or {}))
    append_open_ready_frontier_focus(
        operator_focus,
        dict(delta_sections.get("catalyst_frontier_delta") or {}),
        label="题材催化前沿新增可晋级票",
        added_key="added_promoted_tickers",
        status_label="题材催化前沿状态变化",
    )
    append_open_ready_frontier_focus(
        operator_focus,
        dict(delta_sections.get("score_fail_frontier_delta") or {}),
        label="score-fail recurring 队列新增重点票",
        added_key="added_priority_tickers",
        status_label="score-fail frontier 状态变化",
    )
    score_fail_delta = dict(delta_sections.get("score_fail_frontier_delta") or {})
    append_open_ready_score_fail_focus(operator_focus, score_fail_delta)
    append_open_ready_action_focus(operator_focus, delta_sections)
    append_open_ready_stability_focus(operator_focus)
    return operator_focus


def resolve_open_ready_overall_delta_verdict(comparison_basis: str, delta_sections: dict[str, Any]) -> str:
    if comparison_basis == "baseline_captured":
        return "baseline_captured"
    has_changes = any(
        dict(delta_sections.get(section) or {}).get("has_changes")
        for section in [
            "priority_delta",
            "governance_delta",
            "replay_delta",
            "catalyst_frontier_delta",
            "score_fail_frontier_delta",
            "top_priority_action_delta",
            "selected_outcome_contract_delta",
            "carryover_peer_proof_delta",
            "carryover_promotion_gate_delta",
        ]
    )
    return "changed" if has_changes else "stable"


def should_build_open_ready_material_anchor(
    *,
    historical_payload_candidates: list[tuple[dict[str, Any], str | None]] | None,
    enable_material_anchor: bool,
    comparison_scope: str,
    overall_delta_verdict: str,
) -> bool:
    return bool(enable_material_anchor and historical_payload_candidates and comparison_scope == "same_report_rerun" and overall_delta_verdict == "stable")


def append_open_ready_material_anchor_focus(operator_focus: list[str], material_change_anchor: dict[str, Any]) -> None:
    if not material_change_anchor:
        return
    changed_sections = ", ".join(material_change_anchor.get("changed_sections") or []) or "n/a"
    operator_focus.append(f"最近一次实质变化锚点: {material_change_anchor.get('reference_generated_at') or 'n/a'} | sections={changed_sections}。")


def build_open_ready_material_change_anchor(
    *,
    current_payload: dict[str, Any],
    reports_root: str | Path,
    current_nightly_json_path: str | Path,
    historical_payload_candidates: list[tuple[dict[str, Any], str | None]] | None,
    enable_material_anchor: bool,
    comparison_scope: str,
    overall_delta_verdict: str,
    operator_focus: list[str],
    build_material_change_anchor: BuildMaterialChangeAnchor,
    append_open_ready_material_anchor_focus: AppendOpenReadyMaterialAnchorFocus,
) -> dict[str, Any]:
    if not should_build_open_ready_material_anchor(
        historical_payload_candidates=historical_payload_candidates,
        enable_material_anchor=enable_material_anchor,
        comparison_scope=comparison_scope,
        overall_delta_verdict=overall_delta_verdict,
    ):
        return {}
    material_change_anchor = build_material_change_anchor(
        current_payload,
        reports_root=reports_root,
        current_nightly_json_path=current_nightly_json_path,
        historical_payload_candidates=historical_payload_candidates,
    )
    append_open_ready_material_anchor_focus(operator_focus, material_change_anchor)
    return material_change_anchor
