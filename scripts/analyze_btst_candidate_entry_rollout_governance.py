from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_FRONTIER_REPORT_PATH = REPORTS_DIR / "btst_candidate_entry_frontier_20260330.json"
DEFAULT_STRUCTURAL_VALIDATION_PATH = REPORTS_DIR / "selection_target_structural_variants_candidate_entry_current_window_20260330.json"
DEFAULT_WINDOW_SCAN_PATH = REPORTS_DIR / "btst_candidate_entry_window_scan_20260330.json"
DEFAULT_SCORE_FRONTIER_PATH = REPORTS_DIR / "btst_score_construction_frontier_20260330.json"
DEFAULT_NO_CANDIDATE_ENTRY_REPLAY_BUNDLE_PATH = REPORTS_DIR / "btst_no_candidate_entry_replay_bundle_latest.json"
DEFAULT_NO_CANDIDATE_ENTRY_FAILURE_DOSSIER_PATH = REPORTS_DIR / "btst_no_candidate_entry_failure_dossier_latest.json"
DEFAULT_WATCHLIST_RECALL_DOSSIER_PATH = REPORTS_DIR / "btst_watchlist_recall_dossier_latest.json"
DEFAULT_CANDIDATE_POOL_RECALL_DOSSIER_PATH = REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p9_candidate_entry_rollout_governance_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p9_candidate_entry_rollout_governance_20260330.md"

VARIANT_TO_STRUCTURAL_ALIAS = {
    "weak_structure_triplet": "exclude_watchlist_avoid_weak_structure_entries",
    "semantic_pair_300502": None,
    "volume_only_20260326": None,
}
TARGET_DISTINCT_WINDOW_COUNT = 2


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _safe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _score_frontier_all_zero(score_frontier_report: dict[str, Any]) -> bool:
    variant_rows = [dict(row or {}) for row in list(score_frontier_report.get("ranked_variants") or [])]
    if not variant_rows:
        return True
    return all(int(row.get("closed_cycle_tradeable_count") or 0) == 0 for row in variant_rows)


def derive_candidate_entry_shadow_state(
    *,
    rollout_readiness: str,
    preserve_misfire_report_count: int,
    distinct_window_count_with_filtered_entries: int,
    target_window_count: int = TARGET_DISTINCT_WINDOW_COUNT,
) -> dict[str, Any]:
    missing_window_count = max(int(target_window_count or 0) - max(int(distinct_window_count_with_filtered_entries or 0), 0), 0)

    if preserve_misfire_report_count > 0:
        lane_status = "research_only"
        default_upgrade_status = "blocked_by_preserve_misfire"
        upgrade_gap = "preserve_misfire_present"
    elif rollout_readiness == "shadow_only_until_second_window":
        lane_status = "shadow_only_until_second_window"
        default_upgrade_status = "blocked_by_single_window_candidate_entry_signal"
        upgrade_gap = "await_new_independent_window_data"
    elif rollout_readiness == "shadow_rollout_review_ready":
        lane_status = "shadow_rollout_review_ready"
        default_upgrade_status = "blocked_pending_additional_shadow_execution_evidence"
        upgrade_gap = "ready_for_shadow_rollout_review"
    else:
        lane_status = "research_only"
        default_upgrade_status = "blocked_by_missing_window_signal"
        upgrade_gap = "missing_window_signal"

    return {
        "lane_status": lane_status,
        "default_upgrade_status": default_upgrade_status,
        "target_window_count": int(target_window_count or 0),
        "missing_window_count": missing_window_count,
        "upgrade_gap": upgrade_gap,
    }


def _string_list(values: list[Any]) -> list[str]:
    return [str(value) for value in list(values or []) if str(value or "").strip()]


def _extract_best_variant_context(frontier_report: dict[str, Any], structural_validation: dict[str, Any]) -> dict[str, Any]:
    best_variant = dict(frontier_report.get("best_variant") or {})
    best_variant_name = str(best_variant.get("variant_name") or "")
    structural_alias = VARIANT_TO_STRUCTURAL_ALIAS.get(best_variant_name)
    structural_rows = [dict(row or {}) for row in list(structural_validation.get("rows") or [])]
    structural_row = next((row for row in structural_rows if str(row.get("structural_variant") or "") == str(structural_alias or "")), {})
    structural_analysis = dict(structural_row.get("analysis") or {})
    return {
        "best_variant": best_variant,
        "best_variant_name": best_variant_name,
        "structural_alias": structural_alias,
        "structural_row": structural_row,
        "current_window_evidence": {
            "filtered_candidate_entry_count": int(best_variant.get("filtered_candidate_entry_count") or 0),
            "focus_filtered_tickers": list(best_variant.get("focus_filtered_tickers") or []),
            "preserve_filtered_tickers": list(best_variant.get("preserve_filtered_tickers") or []),
            "filtered_next_high_hit_rate_at_threshold": best_variant.get("filtered_next_high_hit_rate_at_threshold"),
            "filtered_next_close_positive_rate": best_variant.get("filtered_next_close_positive_rate"),
            "evidence_tier": best_variant.get("evidence_tier"),
            "selection_basis": best_variant.get("selection_basis"),
        },
        "main_chain_validation": {
            "structural_variant": structural_alias,
            "decision_mismatch_count": int(structural_row.get("decision_mismatch_count") or 0),
            "released_from_blocked": list(structural_row.get("released_from_blocked") or []),
            "blocked_to_near_miss": list(structural_row.get("blocked_to_near_miss") or []),
            "blocked_to_selected": list(structural_row.get("blocked_to_selected") or []),
            "filtered_candidate_entry_counts": dict(structural_analysis.get("filtered_candidate_entry_counts") or {}),
            "candidate_entry_filter_observability": dict(structural_analysis.get("candidate_entry_filter_observability") or {}),
        },
    }


def _extract_window_scan_context(window_scan: dict[str, Any], score_frontier_report: dict[str, Any]) -> dict[str, Any]:
    scan_readiness = str(window_scan.get("rollout_readiness") or "unknown")
    preserve_misfire_report_count = int(window_scan.get("preserve_misfire_report_count") or 0)
    distinct_window_count_with_filtered_entries = int(window_scan.get("distinct_window_count_with_filtered_entries") or 0)
    shadow_state = derive_candidate_entry_shadow_state(
        rollout_readiness=scan_readiness,
        preserve_misfire_report_count=preserve_misfire_report_count,
        distinct_window_count_with_filtered_entries=distinct_window_count_with_filtered_entries,
    )
    return {
        "scan_readiness": scan_readiness,
        "preserve_misfire_report_count": preserve_misfire_report_count,
        "distinct_window_count_with_filtered_entries": distinct_window_count_with_filtered_entries,
        "shadow_state": shadow_state,
        "score_frontier_all_zero": _score_frontier_all_zero(score_frontier_report),
        "window_scan_summary": {
            "report_count": int(window_scan.get("report_count") or 0),
            "filtered_report_count": int(window_scan.get("filtered_report_count") or 0),
            "focus_hit_report_count": int(window_scan.get("focus_hit_report_count") or 0),
            "preserve_misfire_report_count": preserve_misfire_report_count,
            "distinct_window_count_with_filtered_entries": distinct_window_count_with_filtered_entries,
            "rollout_readiness": scan_readiness,
            "filtered_ticker_counts": dict(window_scan.get("filtered_ticker_counts") or {}),
        },
    }


def _extract_no_candidate_entry_context(
    no_candidate_entry_action_board: dict[str, Any],
    no_candidate_entry_replay_bundle: dict[str, Any],
    no_candidate_entry_failure_dossier: dict[str, Any],
) -> dict[str, Any]:
    priority_queue = list(no_candidate_entry_action_board.get("priority_queue") or [])
    hotspot_rows = list(no_candidate_entry_action_board.get("window_hotspot_rows") or [])
    next_tasks = list(no_candidate_entry_action_board.get("next_3_tasks") or [])
    top_tickers = [str(row.get("ticker") or "") for row in priority_queue[:3] if row.get("ticker")]
    top_hotspot_dirs = [str(row.get("report_dir") or "") for row in hotspot_rows[:2] if row.get("report_dir")]
    promising_tickers = _string_list(list(no_candidate_entry_replay_bundle.get("promising_priority_tickers") or []))
    upstream_absence_tickers = _string_list(list(no_candidate_entry_failure_dossier.get("top_upstream_absence_tickers") or []))
    absent_from_watchlist_tickers = _string_list(list(no_candidate_entry_failure_dossier.get("top_absent_from_watchlist_tickers") or []))
    watchlist_handoff_gap_tickers = _string_list(list(no_candidate_entry_failure_dossier.get("top_watchlist_visible_but_not_candidate_entry_tickers") or []))
    candidate_entry_target_gap_tickers = _string_list(list(no_candidate_entry_failure_dossier.get("top_candidate_entry_visible_but_not_selection_target_tickers") or []))
    semantic_miss_tickers = _string_list(list(no_candidate_entry_failure_dossier.get("top_candidate_entry_semantic_miss_tickers") or []))
    outside_candidate_entry_tickers = _string_list(list(no_candidate_entry_failure_dossier.get("top_present_but_outside_candidate_entry_tickers") or []))
    return {
        "top_tickers": top_tickers,
        "top_hotspot_dirs": top_hotspot_dirs,
        "promising_tickers": promising_tickers,
        "upstream_absence_tickers": upstream_absence_tickers,
        "absent_from_watchlist_tickers": absent_from_watchlist_tickers,
        "watchlist_handoff_gap_tickers": watchlist_handoff_gap_tickers,
        "candidate_entry_target_gap_tickers": candidate_entry_target_gap_tickers,
        "semantic_miss_tickers": semantic_miss_tickers,
        "outside_candidate_entry_tickers": outside_candidate_entry_tickers,
        "action_board_summary": {
            "priority_queue_count": len(priority_queue),
            "window_hotspot_count": len(hotspot_rows),
            "top_priority_tickers": top_tickers,
            "top_hotspot_report_dirs": top_hotspot_dirs,
            "next_task_ids": [str(task.get("task_id") or "") for task in next_tasks[:3] if task.get("task_id")],
            "recommendation": no_candidate_entry_action_board.get("recommendation"),
        },
        "replay_bundle_summary": {
            "promising_priority_tickers": promising_tickers,
            "promising_hotspot_report_dirs": _string_list(list(no_candidate_entry_replay_bundle.get("promising_hotspot_report_dirs") or [])),
            "candidate_entry_status_counts": dict(no_candidate_entry_replay_bundle.get("candidate_entry_status_counts") or {}),
            "window_scan_rollout_readiness": dict(no_candidate_entry_replay_bundle.get("global_window_scan") or {}).get("rollout_readiness"),
            "recommendation": no_candidate_entry_replay_bundle.get("recommendation"),
        },
        "failure_dossier_summary": {
            "priority_failure_class_counts": dict(no_candidate_entry_failure_dossier.get("priority_failure_class_counts") or {}),
            "priority_handoff_stage_counts": dict(no_candidate_entry_failure_dossier.get("priority_handoff_stage_counts") or {}),
            "top_upstream_absence_tickers": upstream_absence_tickers,
            "top_absent_from_watchlist_tickers": absent_from_watchlist_tickers,
            "top_watchlist_visible_but_not_candidate_entry_tickers": watchlist_handoff_gap_tickers,
            "top_candidate_entry_visible_but_not_selection_target_tickers": candidate_entry_target_gap_tickers,
            "top_present_but_outside_candidate_entry_tickers": outside_candidate_entry_tickers,
            "top_candidate_entry_semantic_miss_tickers": semantic_miss_tickers,
            "recommendation": no_candidate_entry_failure_dossier.get("recommendation"),
        },
    }


def _extract_watchlist_recall_context(watchlist_recall_dossier: dict[str, Any]) -> dict[str, Any]:
    absent_from_candidate_pool_tickers = _string_list(list(watchlist_recall_dossier.get("top_absent_from_candidate_pool_tickers") or []))
    candidate_pool_layer_b_gap_tickers = _string_list(list(watchlist_recall_dossier.get("top_candidate_pool_visible_but_missing_layer_b_tickers") or []))
    layer_b_watchlist_gap_tickers = _string_list(list(watchlist_recall_dossier.get("top_layer_b_visible_but_missing_watchlist_tickers") or []))
    return {
        "absent_from_candidate_pool_tickers": absent_from_candidate_pool_tickers,
        "candidate_pool_layer_b_gap_tickers": candidate_pool_layer_b_gap_tickers,
        "layer_b_watchlist_gap_tickers": layer_b_watchlist_gap_tickers,
        "summary": {
            "priority_recall_stage_counts": dict(watchlist_recall_dossier.get("priority_recall_stage_counts") or {}),
            "top_absent_from_candidate_pool_tickers": absent_from_candidate_pool_tickers,
            "top_candidate_pool_visible_but_missing_layer_b_tickers": candidate_pool_layer_b_gap_tickers,
            "top_layer_b_visible_but_missing_watchlist_tickers": layer_b_watchlist_gap_tickers,
            "recommendation": watchlist_recall_dossier.get("recommendation"),
        },
    }


def _extract_candidate_pool_recall_context(candidate_pool_recall_dossier: dict[str, Any]) -> dict[str, Any]:
    top_stage_tickers = {
        str(key): _string_list(list(values or []))
        for key, values in dict(candidate_pool_recall_dossier.get("top_stage_tickers") or {}).items()
        if str(key or "").strip()
    }
    truncation_frontier_summary = dict(candidate_pool_recall_dossier.get("truncation_frontier_summary") or {})
    focus_liquidity_profile_summary = dict(candidate_pool_recall_dossier.get("focus_liquidity_profile_summary") or {})
    focus_liquidity_profiles = [dict(row) for row in list(focus_liquidity_profile_summary.get("primary_focus_tickers") or [])]
    priority_handoff_branch_diagnoses = [dict(row) for row in list(candidate_pool_recall_dossier.get("priority_handoff_branch_diagnoses") or [])]
    priority_handoff_branch_mechanisms = [dict(row) for row in list(candidate_pool_recall_dossier.get("priority_handoff_branch_mechanisms") or [])]
    priority_handoff_branch_experiment_queue = [dict(row) for row in list(candidate_pool_recall_dossier.get("priority_handoff_branch_experiment_queue") or [])]
    dominant_stage = str(candidate_pool_recall_dossier.get("dominant_stage") or "").strip() or None
    dominant_ranking_driver = str(truncation_frontier_summary.get("dominant_ranking_driver") or "").strip() or None
    dominant_liquidity_gap_mode = str(truncation_frontier_summary.get("dominant_liquidity_gap_mode") or "").strip() or None
    return {
        "dominant_stage": dominant_stage,
        "top_stage_tickers": top_stage_tickers,
        "truncation_frontier_summary": truncation_frontier_summary,
        "dominant_ranking_driver": dominant_ranking_driver,
        "avg_amount_share_of_cutoff_mean": truncation_frontier_summary.get("avg_amount_share_of_cutoff_mean"),
        "dominant_liquidity_gap_mode": dominant_liquidity_gap_mode,
        "avg_amount_share_of_min_gate_mean": truncation_frontier_summary.get("avg_amount_share_of_min_gate_mean"),
        "focus_liquidity_profile_summary": focus_liquidity_profile_summary,
        "focus_liquidity_profiles": focus_liquidity_profiles,
        "priority_handoff_branch_diagnoses": priority_handoff_branch_diagnoses,
        "priority_handoff_branch_mechanisms": priority_handoff_branch_mechanisms,
        "priority_handoff_branch_experiment_queue": priority_handoff_branch_experiment_queue,
        "summary": {
            "priority_stage_counts": dict(candidate_pool_recall_dossier.get("priority_stage_counts") or {}),
            "dominant_stage": dominant_stage,
            "top_stage_tickers": top_stage_tickers,
            "truncation_frontier_summary": truncation_frontier_summary,
            "dominant_ranking_driver": dominant_ranking_driver,
            "dominant_liquidity_gap_mode": dominant_liquidity_gap_mode,
            "focus_liquidity_profile_summary": focus_liquidity_profile_summary,
            "focus_liquidity_profiles": focus_liquidity_profiles[:3],
            "priority_handoff_branch_diagnoses": priority_handoff_branch_diagnoses[:3],
            "priority_handoff_branch_mechanisms": priority_handoff_branch_mechanisms[:3],
            "priority_handoff_branch_experiment_queue": priority_handoff_branch_experiment_queue[:3],
            "recommendation": candidate_pool_recall_dossier.get("recommendation"),
        },
    }


def _build_rollout_recommendation(
    window_scan_context: dict[str, Any],
    no_candidate_entry_context: dict[str, Any],
    watchlist_recall_context: dict[str, Any],
    candidate_pool_recall_context: dict[str, Any],
) -> str:
    lane_status = str(window_scan_context["shadow_state"]["lane_status"])
    recommendation = (
        "当前 candidate-entry 主结论应收敛为：保留 weak-structure selective rule 作为 shadow-only 入口治理语义，"
        "不要把 semantic_pair 或 volume-only 规则直接提升为默认，更不要把它误写成 score frontier 的替代品。"
    )
    if lane_status == "shadow_rollout_review_ready":
        recommendation = (
            "当前 candidate-entry 主结论应收敛为：weak-structure selective rule 已具备进入 shadow rollout review 的条件，"
            "但仍不能单独作为默认升级依据，必须继续以 preserve-misfire=0 和新增独立窗口命中作为守门条件。"
        )
    elif lane_status == "research_only":
        recommendation = (
            "当前 candidate-entry 主结论应收敛为：弱结构规则仍停留在 research-only 或单窗证据阶段，"
            "不能进入 rollout，更不能替代当前 default admission 基线。"
        )
    recommendation = _append_no_candidate_entry_recommendation(recommendation, no_candidate_entry_context)
    recommendation = _append_watchlist_recall_recommendation(recommendation, watchlist_recall_context)
    recommendation = _append_candidate_pool_recall_recommendation(recommendation, candidate_pool_recall_context)
    if no_candidate_entry_context["promising_tickers"]:
        return (
            f"{recommendation} 当前 replay bundle 已为 {no_candidate_entry_context['promising_tickers']} 找到 preserve-safe recall probe，"
            "因此下一步应优先接回 shadow governance，而不是继续停留在纯动作板层面。"
        )
    return recommendation


def _append_no_candidate_entry_recommendation(recommendation: str, context: dict[str, Any]) -> str:
    if context["top_tickers"]:
        recommendation = (
            f"{recommendation} 同时，tradeable pool 里仍有大批 no_candidate_entry backlog，"
            f"下一批优先回放应收敛到 {context['top_tickers']}，"
            f"并优先检查 {context['top_hotspot_dirs'] or ['热点窗口']} 的 watchlist recall / selective semantics，"
            "而不是继续放松 score frontier。"
        )
    if context["upstream_absence_tickers"]:
        recommendation = (
            f"{recommendation} failure dossier 进一步说明，当前 backlog 的主矛盾首先是 {context['upstream_absence_tickers']} 这批票在 replay input / candidate-entry source 中缺席，"
            "因此下一步应先补 observability 与上游 handoff，而不是继续 candidate-entry semantic 调参。"
        )
    if context["absent_from_watchlist_tickers"]:
        recommendation = (
            f"{recommendation} 进一步拆开后，当前最先要补的是 {context['absent_from_watchlist_tickers']} 这批票的 candidate pool -> watchlist 召回层，"
            "因为它们连 watchlist 都没有进入。"
        )
    return recommendation


def _append_watchlist_recall_recommendation(recommendation: str, context: dict[str, Any]) -> str:
    if context["absent_from_candidate_pool_tickers"]:
        return (
            f"{recommendation} watchlist recall dossier 继续前推后还说明，{context['absent_from_candidate_pool_tickers']} 连 candidate_pool snapshot 都没有进入，"
            "因此当前首先要修的不是 watchlist 阈值，而是 Layer A 候选池召回与池内截断观测。"
        )
    if context["candidate_pool_layer_b_gap_tickers"]:
        return (
            f"{recommendation} watchlist recall dossier 还说明，{context['candidate_pool_layer_b_gap_tickers']} 已进入 candidate_pool，"
            "但没有进入 layer_b 过滤诊断，因此下一步应优先检查 candidate_pool -> layer_b handoff。"
        )
    if context["layer_b_watchlist_gap_tickers"]:
        return (
            f"{recommendation} watchlist recall dossier 还说明，{context['layer_b_watchlist_gap_tickers']} 已进入 layer_b，"
            "但没有进入 watchlist，因此下一步应优先检查 watchlist gate。"
        )
    return recommendation


def _append_candidate_pool_recall_recommendation(recommendation: str, context: dict[str, Any]) -> str:
    dominant_stage = context["dominant_stage"]
    if dominant_stage:
        recommendation = (
            f"{recommendation} Layer A candidate_pool recall dossier 进一步确认，当前主导根因是 {dominant_stage}，"
            f"焦点票主要是 {context['top_stage_tickers'].get(dominant_stage, [])}。"
        )
    if dominant_stage == "candidate_pool_truncated_after_filters":
        return _append_candidate_pool_truncation_recommendation(recommendation, context)
    return _append_non_truncation_gap_recommendation(recommendation, context)


def _append_candidate_pool_truncation_recommendation(recommendation: str, context: dict[str, Any]) -> str:
    closest_distinct_cases = list(context["truncation_frontier_summary"].get("closest_distinct_ticker_cases") or [])
    closest_case = dict(closest_distinct_cases[0]) if closest_distinct_cases else {}
    frontier_verdict = str(context["truncation_frontier_summary"].get("frontier_verdict") or "").strip()
    if closest_case:
        gap_phrase = f"距 cutoff 仍差 {closest_case.get('pre_truncation_rank_gap_to_cutoff')} 名"
        if frontier_verdict == "near_cutoff_boundary":
            gap_phrase = f"距 cutoff 仅差 {closest_case.get('pre_truncation_rank_gap_to_cutoff')} 名"
        ranking_reason = _build_candidate_pool_ranking_reason(context)
        gap_mode_reason = _build_candidate_pool_gap_mode_reason(context)
        recommendation = (
            f"{recommendation} 当前最近的 distinct 截断样本是 {closest_case.get('ticker')}@{closest_case.get('trade_date')}，"
            f"pre-truncation rank={closest_case.get('pre_truncation_rank')}，{gap_phrase}。"
            f" {ranking_reason}{gap_mode_reason}"
        )
    if context["focus_liquidity_profiles"]:
        recommendation = (
            f"{recommendation} 焦点 ticker 画像已进一步拆成 {[(row.get('ticker'), row.get('dominant_liquidity_gap_mode'), row.get('priority_handoff')) for row in context['focus_liquidity_profiles'][:3]]}，"
            "因此后续不应再把所有截断票当作同一条修复车道。"
        )
    if context["priority_handoff_branch_diagnoses"]:
        recommendation = (
            f"{recommendation} 分支诊断已明确拆成 {[(row.get('priority_handoff'), row.get('tickers')) for row in context['priority_handoff_branch_diagnoses'][:3]]}，"
            "因此下一步应按车道分别推进 Layer A corridor 与 post-gate competition。"
        )
    return _append_candidate_pool_branch_recommendation(recommendation, context)


def _build_candidate_pool_ranking_reason(context: dict[str, Any]) -> str:
    ranking_driver = context["dominant_ranking_driver"]
    if ranking_driver in {"avg_amount_20d_gap_dominant", "avg_amount_20d_gap"}:
        return f"过滤后排序弱势主要仍由 20 日成交额差距驱动，平均只达到 cutoff 的 {context['avg_amount_share_of_cutoff_mean']}。"
    if ranking_driver == "market_cap_tie_break_gap":
        return "过滤后排序更像 cutoff 附近的市值 tie-break 差距，而不是成交额硬缺口。"
    return "这还不是 top300 微边界问题。"


def _build_candidate_pool_gap_mode_reason(context: dict[str, Any]) -> str:
    gap_mode = context["dominant_liquidity_gap_mode"]
    if gap_mode == "well_above_gate_but_far_below_cutoff":
        return f" 这些票平均已经达到最低流动性门槛的 {context['avg_amount_share_of_min_gate_mean']} 倍，说明主问题不是 gate 太高，而是过 gate 后仍明显弱于 cutoff。"
    if gap_mode == "barely_above_gate_and_far_below_cutoff":
        return f" 这些票平均只达到最低流动性门槛的 {context['avg_amount_share_of_min_gate_mean']} 倍，说明 gate 与 cutoff 之间存在长尾质量走廊。"
    return ""


def _append_candidate_pool_branch_recommendation(recommendation: str, context: dict[str, Any]) -> str:
    if context["priority_handoff_branch_mechanisms"]:
        recommendation = f"{recommendation} {context['priority_handoff_branch_mechanisms'][0].get('mechanism_summary')}"
        pressure_summary = str(context["priority_handoff_branch_mechanisms"][0].get("pressure_cluster_summary") or "").strip()
        if pressure_summary:
            recommendation = f"{recommendation} {pressure_summary}"
        repair_summary = str(context["priority_handoff_branch_mechanisms"][0].get("repair_hypothesis_summary") or "").strip()
        if repair_summary:
            recommendation = f"{recommendation} {repair_summary}"
    if context["priority_handoff_branch_experiment_queue"]:
        prototype_summary = str(context["priority_handoff_branch_experiment_queue"][0].get("prototype_summary") or "").strip()
        if prototype_summary:
            recommendation = f"{recommendation} {prototype_summary}"
        evaluation_summary = str(context["priority_handoff_branch_experiment_queue"][0].get("evaluation_summary") or "").strip()
        if evaluation_summary:
            recommendation = f"{recommendation} {evaluation_summary}"
        guardrail_summary = str(context["priority_handoff_branch_experiment_queue"][0].get("guardrail_summary") or "").strip()
        if guardrail_summary:
            recommendation = f"{recommendation} {guardrail_summary}"
    return recommendation


def _append_non_truncation_gap_recommendation(recommendation: str, candidate_pool_context: dict[str, Any]) -> str:
    if candidate_pool_context["dominant_stage"]:
        return recommendation
    return recommendation


def _build_rollout_next_actions(
    no_candidate_entry_context: dict[str, Any],
    watchlist_recall_context: dict[str, Any],
    candidate_pool_recall_context: dict[str, Any],
) -> list[str]:
    next_actions = [
        "把 exclude_watchlist_avoid_weak_structure_entries 固定为后续 replay / shadow 验证的唯一 candidate-entry 弱结构旁路",
        "每出现新的 paper_trading_window 报告，就重跑 candidate-entry window scan，先补第二个独立窗口命中再讨论 lane promotion",
        "维持 semantic_pair_300502 与 volume_only_20260326 为研究参考，不进入 rollout 主链",
    ]
    if no_candidate_entry_context["top_tickers"]:
        next_actions.append(
            f"沿 no_candidate_entry action board 优先回放 {no_candidate_entry_context['top_tickers']}，并以 {no_candidate_entry_context['top_hotspot_dirs'] or ['热点窗口']} 为第一批窗口复核对象"
        )
    if no_candidate_entry_context["upstream_absence_tickers"]:
        next_actions.append(
            f"先补 {no_candidate_entry_context['upstream_absence_tickers']} 的 replay-input / selection-artifacts observability，再继续 candidate-entry frontier"
        )
    if no_candidate_entry_context["absent_from_watchlist_tickers"]:
        next_actions.append(
            f"优先回查 {no_candidate_entry_context['absent_from_watchlist_tickers']} 的 candidate pool -> watchlist 召回缺口"
        )
    if watchlist_recall_context["absent_from_candidate_pool_tickers"]:
        next_actions.append(
            f"优先回查 {watchlist_recall_context['absent_from_candidate_pool_tickers']} 的 Layer A candidate_pool 召回与池内截断"
        )
    next_actions.extend(_build_candidate_pool_recall_next_actions(candidate_pool_recall_context))
    next_actions.extend(_build_handoff_gap_next_actions(no_candidate_entry_context, watchlist_recall_context, candidate_pool_recall_context))
    if no_candidate_entry_context["promising_tickers"]:
        next_actions.append(
            f"把 {no_candidate_entry_context['promising_tickers']} 作为 no-entry shadow recall probe 接回治理板，并持续核对 preserve_ticker 0 误伤"
        )
    return next_actions


def _build_candidate_pool_recall_next_actions(context: dict[str, Any]) -> list[str]:
    dominant_stage = context["dominant_stage"]
    if not dominant_stage:
        return []
    next_actions = [
        f"沿 candidate_pool recall dossier 优先处理 {dominant_stage}：{context['top_stage_tickers'].get(dominant_stage, [])}"
    ]
    if dominant_stage != "candidate_pool_truncated_after_filters":
        return next_actions
    next_actions.extend(_build_candidate_pool_truncation_next_actions(context))
    return next_actions


def _build_candidate_pool_truncation_next_actions(context: dict[str, Any]) -> list[str]:
    next_actions: list[str] = []
    next_actions.extend(_build_candidate_pool_closest_case_action(context))
    next_actions.extend(_build_candidate_pool_ranking_gap_actions(context))
    next_actions.extend(_build_candidate_pool_branch_extension_actions(context))
    return next_actions


def _build_candidate_pool_closest_case_action(context: dict[str, Any]) -> list[str]:
    closest_cases = list(context["truncation_frontier_summary"].get("closest_cases") or [])
    closest_case = dict(closest_cases[0]) if closest_cases else {}
    if not closest_case:
        return []
    return [
        f"优先跟踪 {closest_case.get('ticker')}@{closest_case.get('trade_date')} 的 top300 cutoff gap={closest_case.get('pre_truncation_rank_gap_to_cutoff')}，评估是 rank 微调还是上游入口问题"
    ]


def _build_candidate_pool_ranking_gap_actions(context: dict[str, Any]) -> list[str]:
    next_actions: list[str] = []
    ranking_driver = context["dominant_ranking_driver"]
    if ranking_driver in {"avg_amount_20d_gap_dominant", "avg_amount_20d_gap"}:
        next_actions.append("把 candidate_pool truncation 诊断继续下钻到 20 日成交额弱势，不再优先讨论扩大候选池上限。")
    elif ranking_driver == "market_cap_tie_break_gap":
        next_actions.append("把 candidate_pool truncation 诊断继续下钻到 cutoff 附近的市值 tie-break，而不是先放松 liquidity gate。")
    gap_mode = context["dominant_liquidity_gap_mode"]
    if gap_mode == "well_above_gate_but_far_below_cutoff":
        next_actions.append("这批票多数已显著高于最低流动性门槛，下一步不要优先下调 MIN_AVG_AMOUNT_20D，而要解释为何过 gate 后仍长期输给 cutoff 竞争集。")
    elif gap_mode == "barely_above_gate_and_far_below_cutoff":
        next_actions.append("这批票多数只是勉强高于最低流动性门槛，下一步应同时审查 liquidity gate 位置与 cutoff 竞争强度。")
    return next_actions


def _build_candidate_pool_branch_extension_actions(context: dict[str, Any]) -> list[str]:
    next_actions: list[str] = []
    if context["focus_liquidity_profiles"]:
        next_actions.append(f"按焦点 ticker 画像拆分 handoff：{[(row.get('ticker'), row.get('priority_handoff')) for row in context['focus_liquidity_profiles'][:3]]}。")
    for diagnosis in context["priority_handoff_branch_diagnoses"][:2]:
        next_step = str(diagnosis.get("next_step") or "").strip()
        if next_step:
            next_actions.append(next_step)
    for mechanism in context["priority_handoff_branch_mechanisms"][:2]:
        next_actions.extend(_collect_branch_mechanism_actions(mechanism))
    for experiment in context["priority_handoff_branch_experiment_queue"][:2]:
        next_actions.extend(_collect_branch_experiment_actions(experiment))
    return next_actions


def _collect_branch_mechanism_actions(mechanism: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for key in ("mechanism_summary", "pressure_cluster_summary", "repair_hypothesis_summary"):
        summary = str(mechanism.get(key) or "").strip()
        if summary:
            actions.append(summary)
    return actions


def _collect_branch_experiment_actions(experiment: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for key in ("prototype_summary", "evaluation_summary", "success_signal"):
        summary = str(experiment.get(key) or "").strip()
        if summary:
            actions.append(summary)
    return actions


def _build_handoff_gap_next_actions(
    no_candidate_entry_context: dict[str, Any],
    watchlist_recall_context: dict[str, Any],
    candidate_pool_recall_context: dict[str, Any],
) -> list[str]:
    if candidate_pool_recall_context["dominant_stage"] == "candidate_pool_truncated_after_filters":
        return []
    if watchlist_recall_context["candidate_pool_layer_b_gap_tickers"]:
        return [f"优先回查 {watchlist_recall_context['candidate_pool_layer_b_gap_tickers']} 的 candidate_pool -> layer_b handoff"]
    if watchlist_recall_context["layer_b_watchlist_gap_tickers"]:
        return [f"优先回查 {watchlist_recall_context['layer_b_watchlist_gap_tickers']} 的 layer_b -> watchlist gate"]
    if no_candidate_entry_context["watchlist_handoff_gap_tickers"]:
        return [f"优先回查 {no_candidate_entry_context['watchlist_handoff_gap_tickers']} 的 watchlist -> candidate-entry handoff"]
    if no_candidate_entry_context["candidate_entry_target_gap_tickers"]:
        return [f"优先回查 {no_candidate_entry_context['candidate_entry_target_gap_tickers']} 的 candidate-entry -> selection_target contract"]
    if no_candidate_entry_context["outside_candidate_entry_tickers"]:
        return [f"优先回查 {no_candidate_entry_context['outside_candidate_entry_tickers']} 的 watchlist -> candidate-entry handoff，而不是继续弱结构语义实验"]
    if no_candidate_entry_context["semantic_miss_tickers"]:
        return [f"仅把 {no_candidate_entry_context['semantic_miss_tickers']} 继续保留在 candidate-entry semantic replay 车道"]
    return []


def _build_analysis_paths(
    frontier_report_path: str | Path,
    *,
    structural_validation_path: str | Path,
    window_scan_path: str | Path,
    score_frontier_path: str | Path,
    no_candidate_entry_action_board_path: str | Path | None,
    no_candidate_entry_replay_bundle_path: str | Path | None,
    no_candidate_entry_failure_dossier_path: str | Path | None,
    watchlist_recall_dossier_path: str | Path | None,
    candidate_pool_recall_dossier_path: str | Path | None,
) -> dict[str, str | None]:
    return {
        "frontier_report": str(Path(frontier_report_path).expanduser().resolve()),
        "structural_validation_report": str(Path(structural_validation_path).expanduser().resolve()),
        "window_scan_report": str(Path(window_scan_path).expanduser().resolve()),
        "score_frontier_report": str(Path(score_frontier_path).expanduser().resolve()),
        "no_candidate_entry_action_board": str(Path(no_candidate_entry_action_board_path).expanduser().resolve()) if no_candidate_entry_action_board_path else None,
        "no_candidate_entry_replay_bundle": str(Path(no_candidate_entry_replay_bundle_path).expanduser().resolve()) if no_candidate_entry_replay_bundle_path else None,
        "no_candidate_entry_failure_dossier": str(Path(no_candidate_entry_failure_dossier_path).expanduser().resolve()) if no_candidate_entry_failure_dossier_path else None,
        "watchlist_recall_dossier": str(Path(watchlist_recall_dossier_path).expanduser().resolve()) if watchlist_recall_dossier_path else None,
        "candidate_pool_recall_dossier": str(Path(candidate_pool_recall_dossier_path).expanduser().resolve()) if candidate_pool_recall_dossier_path else None,
    }


def analyze_btst_candidate_entry_rollout_governance(
    frontier_report_path: str | Path,
    *,
    structural_validation_path: str | Path,
    window_scan_path: str | Path,
    score_frontier_path: str | Path,
    no_candidate_entry_action_board_path: str | Path | None = None,
    no_candidate_entry_replay_bundle_path: str | Path | None = None,
    no_candidate_entry_failure_dossier_path: str | Path | None = None,
    watchlist_recall_dossier_path: str | Path | None = None,
    candidate_pool_recall_dossier_path: str | Path | None = None,
) -> dict[str, Any]:
    frontier_report = _load_json(frontier_report_path)
    structural_validation = _load_json(structural_validation_path)
    window_scan = _load_json(window_scan_path)
    score_frontier_report = _load_json(score_frontier_path)
    no_candidate_entry_action_board = _safe_load_json(no_candidate_entry_action_board_path)
    no_candidate_entry_replay_bundle = _safe_load_json(no_candidate_entry_replay_bundle_path)
    no_candidate_entry_failure_dossier = _safe_load_json(no_candidate_entry_failure_dossier_path)
    watchlist_recall_dossier = _safe_load_json(watchlist_recall_dossier_path)
    candidate_pool_recall_dossier = _safe_load_json(candidate_pool_recall_dossier_path)
    best_variant_context = _extract_best_variant_context(frontier_report, structural_validation)
    window_scan_context = _extract_window_scan_context(window_scan, score_frontier_report)
    no_candidate_entry_context = _extract_no_candidate_entry_context(
        no_candidate_entry_action_board,
        no_candidate_entry_replay_bundle,
        no_candidate_entry_failure_dossier,
    )
    watchlist_recall_context = _extract_watchlist_recall_context(watchlist_recall_dossier)
    candidate_pool_recall_context = _extract_candidate_pool_recall_context(candidate_pool_recall_dossier)
    shadow_state = dict(window_scan_context["shadow_state"])
    recommendation = _build_rollout_recommendation(
        window_scan_context,
        no_candidate_entry_context,
        watchlist_recall_context,
        candidate_pool_recall_context,
    )
    next_actions = _build_rollout_next_actions(
        no_candidate_entry_context,
        watchlist_recall_context,
        candidate_pool_recall_context,
    )

    return {
        **_build_analysis_paths(
            frontier_report_path,
            structural_validation_path=structural_validation_path,
            window_scan_path=window_scan_path,
            score_frontier_path=score_frontier_path,
            no_candidate_entry_action_board_path=no_candidate_entry_action_board_path,
            no_candidate_entry_replay_bundle_path=no_candidate_entry_replay_bundle_path,
            no_candidate_entry_failure_dossier_path=no_candidate_entry_failure_dossier_path,
            watchlist_recall_dossier_path=watchlist_recall_dossier_path,
            candidate_pool_recall_dossier_path=candidate_pool_recall_dossier_path,
        ),
        "candidate_entry_rule": best_variant_context["best_variant_name"],
        "recommended_structural_variant": best_variant_context["structural_alias"],
        "lane_status": shadow_state["lane_status"],
        "default_upgrade_status": shadow_state["default_upgrade_status"],
        "target_window_count": shadow_state["target_window_count"],
        "missing_window_count": shadow_state["missing_window_count"],
        "upgrade_gap": shadow_state["upgrade_gap"],
        "score_frontier_all_zero": window_scan_context["score_frontier_all_zero"],
        "current_window_evidence": best_variant_context["current_window_evidence"],
        "main_chain_validation": best_variant_context["main_chain_validation"],
        "window_scan_summary": window_scan_context["window_scan_summary"],
        "no_candidate_entry_action_board_summary": no_candidate_entry_context["action_board_summary"],
        "no_candidate_entry_replay_bundle_summary": no_candidate_entry_context["replay_bundle_summary"],
        "no_candidate_entry_failure_dossier_summary": no_candidate_entry_context["failure_dossier_summary"],
        "watchlist_recall_dossier_summary": watchlist_recall_context["summary"],
        "candidate_pool_recall_dossier_summary": candidate_pool_recall_context["summary"],
        "do_not_promote_variants": ["semantic_pair_300502", "volume_only_20260326"],
        "keep_guardrails": [
            "score frontier 仍为 0 actionable 时，candidate-entry 规则只能当作入口清洗语义，不能误写成默认升级依据",
            "preserve_tickers 必须持续保持 0 误伤，当前锚点是 300394 不得被弱结构规则过滤",
            "弱结构规则进入主链时只能以 exclude_watchlist_avoid_weak_structure_entries structural variant 形式复用，不再另造平行规则",
            "若 main-chain 验证不再是 blocked->none 的单点释放，而开始扩大到非目标样本，就必须回退到 research-only",
        ],
        "promotion_conditions": [
            "新增独立窗口后，弱结构规则至少在第 2 个 window_key 上再次过滤到 candidate-entry 样本",
            "window scan 继续保持 preserve_misfire_report_count == 0",
            "当前窗口型 filtered cohort 仍需维持 next_high_hit_rate@2% 与 next_close_positive_rate 同时低于 baseline false-negative pool",
            "在 shadow rollout review 中，语义仍应优先 weak_structure_triplet / exclude_watchlist_avoid_weak_structure_entries，而不是 semantic_pair 或 volume-only",
        ],
        "next_actions": next_actions,
        "recommendation": recommendation,
    }


def _append_markdown_section(lines: list[str], title: str, payload: dict[str, Any]) -> None:
    lines.append(f"## {title}")
    for key, value in payload.items():
        lines.append(f"- {key}: {value}")
    lines.append("")


def _append_markdown_list_section(lines: list[str], title: str, items: list[Any]) -> None:
    lines.append(f"## {title}")
    for item in items:
        lines.append(f"- {item}")
    lines.append("")


def _append_governance_overview_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Overview")
    for key in (
        "candidate_entry_rule",
        "recommended_structural_variant",
        "lane_status",
        "default_upgrade_status",
        "target_window_count",
        "missing_window_count",
        "upgrade_gap",
        "score_frontier_all_zero",
        "recommendation",
    ):
        lines.append(f"- {key}: {analysis[key]}")
    lines.append("")


def render_btst_candidate_entry_rollout_governance_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Entry Rollout Governance")
    lines.append("")
    _append_governance_overview_markdown(lines, analysis)
    _append_markdown_section(lines, "Current Window Evidence", dict(analysis.get("current_window_evidence") or {}))
    _append_markdown_section(lines, "Main-Chain Validation", dict(analysis.get("main_chain_validation") or {}))
    _append_markdown_section(lines, "Window Scan Summary", dict(analysis.get("window_scan_summary") or {}))
    _append_markdown_section(lines, "No Candidate Entry Action Board", dict(analysis.get("no_candidate_entry_action_board_summary") or {}))
    _append_markdown_section(lines, "No Candidate Entry Replay Bundle", dict(analysis.get("no_candidate_entry_replay_bundle_summary") or {}))
    _append_markdown_section(lines, "No Candidate Entry Failure Dossier", dict(analysis.get("no_candidate_entry_failure_dossier_summary") or {}))
    _append_markdown_section(lines, "Watchlist Recall Dossier", dict(analysis.get("watchlist_recall_dossier_summary") or {}))
    _append_markdown_section(lines, "Candidate Pool Recall Dossier", dict(analysis.get("candidate_pool_recall_dossier_summary") or {}))
    _append_markdown_list_section(lines, "Keep Guardrails", list(analysis.get("keep_guardrails") or []))
    _append_markdown_list_section(lines, "Promotion Conditions", list(analysis.get("promotion_conditions") or []))
    _append_markdown_list_section(lines, "Next Actions", list(analysis.get("next_actions") or []))
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rollout governance for BTST candidate-entry weak-structure rule.")
    parser.add_argument("--frontier-report", default=str(DEFAULT_FRONTIER_REPORT_PATH))
    parser.add_argument("--structural-validation-report", default=str(DEFAULT_STRUCTURAL_VALIDATION_PATH))
    parser.add_argument("--window-scan-report", default=str(DEFAULT_WINDOW_SCAN_PATH))
    parser.add_argument("--score-frontier-report", default=str(DEFAULT_SCORE_FRONTIER_PATH))
    parser.add_argument("--no-candidate-entry-action-board", default="")
    parser.add_argument("--no-candidate-entry-replay-bundle", default="")
    parser.add_argument("--no-candidate-entry-failure-dossier", default="")
    parser.add_argument("--watchlist-recall-dossier", default="")
    parser.add_argument("--candidate-pool-recall-dossier", default="")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_entry_rollout_governance(
        args.frontier_report,
        structural_validation_path=args.structural_validation_report,
        window_scan_path=args.window_scan_report,
        score_frontier_path=args.score_frontier_report,
        no_candidate_entry_action_board_path=args.no_candidate_entry_action_board or None,
        no_candidate_entry_replay_bundle_path=args.no_candidate_entry_replay_bundle or None,
        no_candidate_entry_failure_dossier_path=args.no_candidate_entry_failure_dossier or None,
        watchlist_recall_dossier_path=args.watchlist_recall_dossier or None,
        candidate_pool_recall_dossier_path=args.candidate_pool_recall_dossier or None,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_candidate_entry_rollout_governance_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
