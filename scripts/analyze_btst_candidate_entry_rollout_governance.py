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

    best_variant = dict(frontier_report.get("best_variant") or {})
    best_variant_name = str(best_variant.get("variant_name") or "")
    structural_alias = VARIANT_TO_STRUCTURAL_ALIAS.get(best_variant_name)
    structural_rows = [dict(row or {}) for row in list(structural_validation.get("rows") or [])]
    structural_row = next((row for row in structural_rows if str(row.get("structural_variant") or "") == str(structural_alias or "")), {})
    structural_analysis = dict(structural_row.get("analysis") or {})

    current_window_focus_filtered = list(best_variant.get("focus_filtered_tickers") or [])
    current_window_preserve_filtered = list(best_variant.get("preserve_filtered_tickers") or [])
    current_window_filtered_count = int(best_variant.get("filtered_candidate_entry_count") or 0)
    current_window_next_high = best_variant.get("filtered_next_high_hit_rate_at_threshold")
    current_window_next_close = best_variant.get("filtered_next_close_positive_rate")

    score_frontier_all_zero = _score_frontier_all_zero(score_frontier_report)
    scan_readiness = str(window_scan.get("rollout_readiness") or "unknown")
    preserve_misfire_report_count = int(window_scan.get("preserve_misfire_report_count") or 0)
    distinct_window_count_with_filtered_entries = int(window_scan.get("distinct_window_count_with_filtered_entries") or 0)
    no_candidate_entry_priority_queue = list(no_candidate_entry_action_board.get("priority_queue") or [])
    no_candidate_entry_hotspots = list(no_candidate_entry_action_board.get("window_hotspot_rows") or [])
    no_candidate_entry_next_tasks = list(no_candidate_entry_action_board.get("next_3_tasks") or [])
    no_candidate_entry_top_tickers = [str(row.get("ticker") or "") for row in no_candidate_entry_priority_queue[:3] if row.get("ticker")]
    no_candidate_entry_top_hotspot_dirs = [str(row.get("report_dir") or "") for row in no_candidate_entry_hotspots[:2] if row.get("report_dir")]
    no_candidate_entry_promising_tickers = [
        str(value) for value in list(no_candidate_entry_replay_bundle.get("promising_priority_tickers") or []) if str(value or "").strip()
    ]
    no_candidate_entry_replay_status_counts = dict(no_candidate_entry_replay_bundle.get("candidate_entry_status_counts") or {})
    no_candidate_entry_priority_failure_class_counts = dict(no_candidate_entry_failure_dossier.get("priority_failure_class_counts") or {})
    no_candidate_entry_handoff_stage_counts = dict(no_candidate_entry_failure_dossier.get("priority_handoff_stage_counts") or {})
    no_candidate_entry_upstream_absence_tickers = [
        str(value) for value in list(no_candidate_entry_failure_dossier.get("top_upstream_absence_tickers") or []) if str(value or "").strip()
    ]
    no_candidate_entry_absent_from_watchlist_tickers = [
        str(value) for value in list(no_candidate_entry_failure_dossier.get("top_absent_from_watchlist_tickers") or []) if str(value or "").strip()
    ]
    no_candidate_entry_watchlist_handoff_gap_tickers = [
        str(value) for value in list(no_candidate_entry_failure_dossier.get("top_watchlist_visible_but_not_candidate_entry_tickers") or []) if str(value or "").strip()
    ]
    no_candidate_entry_candidate_entry_target_gap_tickers = [
        str(value) for value in list(no_candidate_entry_failure_dossier.get("top_candidate_entry_visible_but_not_selection_target_tickers") or []) if str(value or "").strip()
    ]
    watchlist_recall_stage_counts = dict(watchlist_recall_dossier.get("priority_recall_stage_counts") or {})
    watchlist_recall_absent_from_candidate_pool_tickers = [
        str(value) for value in list(watchlist_recall_dossier.get("top_absent_from_candidate_pool_tickers") or []) if str(value or "").strip()
    ]
    watchlist_recall_candidate_pool_layer_b_gap_tickers = [
        str(value) for value in list(watchlist_recall_dossier.get("top_candidate_pool_visible_but_missing_layer_b_tickers") or []) if str(value or "").strip()
    ]
    watchlist_recall_layer_b_watchlist_gap_tickers = [
        str(value) for value in list(watchlist_recall_dossier.get("top_layer_b_visible_but_missing_watchlist_tickers") or []) if str(value or "").strip()
    ]
    candidate_pool_recall_stage_counts = dict(candidate_pool_recall_dossier.get("priority_stage_counts") or {})
    candidate_pool_recall_dominant_stage = str(candidate_pool_recall_dossier.get("dominant_stage") or "").strip() or None
    candidate_pool_recall_top_stage_tickers = {
        str(key): [str(value) for value in list(values or []) if str(value or "").strip()]
        for key, values in dict(candidate_pool_recall_dossier.get("top_stage_tickers") or {}).items()
        if str(key or "").strip()
    }
    candidate_pool_recall_truncation_frontier_summary = dict(candidate_pool_recall_dossier.get("truncation_frontier_summary") or {})
    candidate_pool_recall_focus_liquidity_profile_summary = dict(candidate_pool_recall_dossier.get("focus_liquidity_profile_summary") or {})
    candidate_pool_recall_focus_liquidity_profiles = [
        dict(row)
        for row in list(candidate_pool_recall_focus_liquidity_profile_summary.get("primary_focus_tickers") or [])
    ]
    candidate_pool_recall_priority_handoff_branch_diagnoses = [
        dict(row)
        for row in list(candidate_pool_recall_dossier.get("priority_handoff_branch_diagnoses") or [])
    ]
    candidate_pool_recall_priority_handoff_branch_mechanisms = [
        dict(row)
        for row in list(candidate_pool_recall_dossier.get("priority_handoff_branch_mechanisms") or [])
    ]
    candidate_pool_recall_priority_handoff_branch_experiment_queue = [
        dict(row)
        for row in list(candidate_pool_recall_dossier.get("priority_handoff_branch_experiment_queue") or [])
    ]
    candidate_pool_recall_ranking_driver = str(candidate_pool_recall_truncation_frontier_summary.get("dominant_ranking_driver") or "").strip() or None
    candidate_pool_recall_avg_amount_share_mean = candidate_pool_recall_truncation_frontier_summary.get("avg_amount_share_of_cutoff_mean")
    candidate_pool_recall_liquidity_gap_mode = str(candidate_pool_recall_truncation_frontier_summary.get("dominant_liquidity_gap_mode") or "").strip() or None
    candidate_pool_recall_avg_amount_share_of_min_gate_mean = candidate_pool_recall_truncation_frontier_summary.get("avg_amount_share_of_min_gate_mean")
    no_candidate_entry_semantic_miss_tickers = [
        str(value) for value in list(no_candidate_entry_failure_dossier.get("top_candidate_entry_semantic_miss_tickers") or []) if str(value or "").strip()
    ]
    no_candidate_entry_outside_candidate_entry_tickers = [
        str(value) for value in list(no_candidate_entry_failure_dossier.get("top_present_but_outside_candidate_entry_tickers") or []) if str(value or "").strip()
    ]
    shadow_state = derive_candidate_entry_shadow_state(
        rollout_readiness=scan_readiness,
        preserve_misfire_report_count=preserve_misfire_report_count,
        distinct_window_count_with_filtered_entries=distinct_window_count_with_filtered_entries,
    )
    lane_status = shadow_state["lane_status"]
    default_upgrade_status = shadow_state["default_upgrade_status"]

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

    if no_candidate_entry_top_tickers:
        recommendation = (
            f"{recommendation} 同时，tradeable pool 里仍有大批 no_candidate_entry backlog，"
            f"下一批优先回放应收敛到 {no_candidate_entry_top_tickers}，"
            f"并优先检查 {no_candidate_entry_top_hotspot_dirs or ['热点窗口']} 的 watchlist recall / selective semantics，"
            "而不是继续放松 score frontier。"
        )
    if no_candidate_entry_upstream_absence_tickers:
        recommendation = (
            f"{recommendation} failure dossier 进一步说明，当前 backlog 的主矛盾首先是 {no_candidate_entry_upstream_absence_tickers} 这批票在 replay input / candidate-entry source 中缺席，"
            "因此下一步应先补 observability 与上游 handoff，而不是继续 candidate-entry semantic 调参。"
        )
    if no_candidate_entry_absent_from_watchlist_tickers:
        recommendation = (
            f"{recommendation} 进一步拆开后，当前最先要补的是 {no_candidate_entry_absent_from_watchlist_tickers} 这批票的 candidate pool -> watchlist 召回层，"
            "因为它们连 watchlist 都没有进入。"
        )
    if watchlist_recall_absent_from_candidate_pool_tickers:
        recommendation = (
            f"{recommendation} watchlist recall dossier 继续前推后还说明，{watchlist_recall_absent_from_candidate_pool_tickers} 连 candidate_pool snapshot 都没有进入，"
            "因此当前首先要修的不是 watchlist 阈值，而是 Layer A 候选池召回与池内截断观测。"
        )
    if candidate_pool_recall_dominant_stage:
        recommendation = (
            f"{recommendation} Layer A candidate_pool recall dossier 进一步确认，当前主导根因是 {candidate_pool_recall_dominant_stage}，"
            f"焦点票主要是 {candidate_pool_recall_top_stage_tickers.get(candidate_pool_recall_dominant_stage, [])}。"
        )
    if candidate_pool_recall_dominant_stage == "candidate_pool_truncated_after_filters":
        closest_distinct_cases = list(candidate_pool_recall_truncation_frontier_summary.get("closest_distinct_ticker_cases") or [])
        closest_case = dict(closest_distinct_cases[0]) if closest_distinct_cases else {}
        frontier_verdict = str(candidate_pool_recall_truncation_frontier_summary.get("frontier_verdict") or "").strip()
        if closest_case:
            gap_phrase = f"距 cutoff 仍差 {closest_case.get('pre_truncation_rank_gap_to_cutoff')} 名"
            if frontier_verdict == "near_cutoff_boundary":
                gap_phrase = f"距 cutoff 仅差 {closest_case.get('pre_truncation_rank_gap_to_cutoff')} 名"
            ranking_reason = "这还不是 top300 微边界问题。"
            if candidate_pool_recall_ranking_driver in {"avg_amount_20d_gap_dominant", "avg_amount_20d_gap"}:
                ranking_reason = f"过滤后排序弱势主要仍由 20 日成交额差距驱动，平均只达到 cutoff 的 {candidate_pool_recall_avg_amount_share_mean}。"
            elif candidate_pool_recall_ranking_driver == "market_cap_tie_break_gap":
                ranking_reason = "过滤后排序更像 cutoff 附近的市值 tie-break 差距，而不是成交额硬缺口。"
            gap_mode_reason = ""
            if candidate_pool_recall_liquidity_gap_mode == "well_above_gate_but_far_below_cutoff":
                gap_mode_reason = f" 这些票平均已经达到最低流动性门槛的 {candidate_pool_recall_avg_amount_share_of_min_gate_mean} 倍，说明主问题不是 gate 太高，而是过 gate 后仍明显弱于 cutoff。"
            elif candidate_pool_recall_liquidity_gap_mode == "barely_above_gate_and_far_below_cutoff":
                gap_mode_reason = f" 这些票平均只达到最低流动性门槛的 {candidate_pool_recall_avg_amount_share_of_min_gate_mean} 倍，说明 gate 与 cutoff 之间存在长尾质量走廊。"
            recommendation = (
                f"{recommendation} 当前最近的 distinct 截断样本是 {closest_case.get('ticker')}@{closest_case.get('trade_date')}，"
                f"pre-truncation rank={closest_case.get('pre_truncation_rank')}，{gap_phrase}。"
                f" {ranking_reason}{gap_mode_reason}"
            )
        if candidate_pool_recall_focus_liquidity_profiles:
            recommendation = (
                f"{recommendation} 焦点 ticker 画像已进一步拆成 {[(row.get('ticker'), row.get('dominant_liquidity_gap_mode'), row.get('priority_handoff')) for row in candidate_pool_recall_focus_liquidity_profiles[:3]]}，"
                "因此后续不应再把所有截断票当作同一条修复车道。"
            )
        if candidate_pool_recall_priority_handoff_branch_diagnoses:
            recommendation = (
                f"{recommendation} 分支诊断已明确拆成 {[(row.get('priority_handoff'), row.get('tickers')) for row in candidate_pool_recall_priority_handoff_branch_diagnoses[:3]]}，"
                "因此下一步应按车道分别推进 Layer A corridor 与 post-gate competition。"
            )
        if candidate_pool_recall_priority_handoff_branch_mechanisms:
            recommendation = f"{recommendation} {candidate_pool_recall_priority_handoff_branch_mechanisms[0].get('mechanism_summary')}"
            pressure_summary = str(candidate_pool_recall_priority_handoff_branch_mechanisms[0].get("pressure_cluster_summary") or "").strip()
            if pressure_summary:
                recommendation = f"{recommendation} {pressure_summary}"
            repair_summary = str(candidate_pool_recall_priority_handoff_branch_mechanisms[0].get("repair_hypothesis_summary") or "").strip()
            if repair_summary:
                recommendation = f"{recommendation} {repair_summary}"
        if candidate_pool_recall_priority_handoff_branch_experiment_queue:
            prototype_summary = str(candidate_pool_recall_priority_handoff_branch_experiment_queue[0].get("prototype_summary") or "").strip()
            if prototype_summary:
                recommendation = f"{recommendation} {prototype_summary}"
            evaluation_summary = str(candidate_pool_recall_priority_handoff_branch_experiment_queue[0].get("evaluation_summary") or "").strip()
            if evaluation_summary:
                recommendation = f"{recommendation} {evaluation_summary}"
            guardrail_summary = str(candidate_pool_recall_priority_handoff_branch_experiment_queue[0].get("guardrail_summary") or "").strip()
            if guardrail_summary:
                recommendation = f"{recommendation} {guardrail_summary}"
    elif watchlist_recall_candidate_pool_layer_b_gap_tickers:
        recommendation = (
            f"{recommendation} watchlist recall dossier 还说明，{watchlist_recall_candidate_pool_layer_b_gap_tickers} 已进入 candidate_pool，"
            "但没有进入 layer_b 过滤诊断，因此下一步应优先检查 candidate_pool -> layer_b handoff。"
        )
    elif watchlist_recall_layer_b_watchlist_gap_tickers:
        recommendation = (
            f"{recommendation} watchlist recall dossier 还说明，{watchlist_recall_layer_b_watchlist_gap_tickers} 已进入 layer_b，"
            "但没有进入 watchlist，因此下一步应优先检查 watchlist gate。"
        )
    elif no_candidate_entry_watchlist_handoff_gap_tickers:
        recommendation = (
            f"{recommendation} 更细的 handoff taxonomy 还说明，{no_candidate_entry_watchlist_handoff_gap_tickers} 已进入 watchlist，"
            "但没有进入 candidate-entry 候选源，因此下一步应优先回查 watchlist handoff。"
        )
    elif no_candidate_entry_candidate_entry_target_gap_tickers:
        recommendation = (
            f"{recommendation} 更细的 handoff taxonomy 还说明，{no_candidate_entry_candidate_entry_target_gap_tickers} 已进入 candidate-entry 源，"
            "但没有挂上 selection_targets，因此下一步应优先检查 target attachment contract。"
        )
    elif no_candidate_entry_outside_candidate_entry_tickers:
        recommendation = (
            f"{recommendation} failure dossier 进一步说明，{no_candidate_entry_outside_candidate_entry_tickers} 已出现在 replay input，"
            "但没有进入 candidate-entry 候选源，因此下一步应优先排查 watchlist 到 candidate-entry 的上游交接。"
        )
    elif no_candidate_entry_semantic_miss_tickers:
        recommendation = (
            f"{recommendation} failure dossier 进一步说明，{no_candidate_entry_semantic_miss_tickers} 已进入 candidate-entry 候选源但仍然 miss focus，"
            "因此下一步才应继续 candidate-entry semantic replay。"
        )
    if no_candidate_entry_promising_tickers:
        recommendation = (
            f"{recommendation} 当前 replay bundle 已为 {no_candidate_entry_promising_tickers} 找到 preserve-safe recall probe，"
            "因此下一步应优先接回 shadow governance，而不是继续停留在纯动作板层面。"
        )

    next_actions = [
        "把 exclude_watchlist_avoid_weak_structure_entries 固定为后续 replay / shadow 验证的唯一 candidate-entry 弱结构旁路",
        "每出现新的 paper_trading_window 报告，就重跑 candidate-entry window scan，先补第二个独立窗口命中再讨论 lane promotion",
        "维持 semantic_pair_300502 与 volume_only_20260326 为研究参考，不进入 rollout 主链",
    ]
    if no_candidate_entry_top_tickers:
        next_actions.append(
            f"沿 no_candidate_entry action board 优先回放 {no_candidate_entry_top_tickers}，并以 {no_candidate_entry_top_hotspot_dirs or ['热点窗口']} 为第一批窗口复核对象"
        )
    if no_candidate_entry_upstream_absence_tickers:
        next_actions.append(
            f"先补 {no_candidate_entry_upstream_absence_tickers} 的 replay-input / selection-artifacts observability，再继续 candidate-entry frontier"
        )
    if no_candidate_entry_absent_from_watchlist_tickers:
        next_actions.append(
            f"优先回查 {no_candidate_entry_absent_from_watchlist_tickers} 的 candidate pool -> watchlist 召回缺口"
        )
    if watchlist_recall_absent_from_candidate_pool_tickers:
        next_actions.append(
            f"优先回查 {watchlist_recall_absent_from_candidate_pool_tickers} 的 Layer A candidate_pool 召回与池内截断"
        )
    if candidate_pool_recall_dominant_stage:
        next_actions.append(
            f"沿 candidate_pool recall dossier 优先处理 {candidate_pool_recall_dominant_stage}：{candidate_pool_recall_top_stage_tickers.get(candidate_pool_recall_dominant_stage, [])}"
        )
    if candidate_pool_recall_dominant_stage == "candidate_pool_truncated_after_filters":
        closest_case = dict(list(candidate_pool_recall_truncation_frontier_summary.get("closest_cases") or [])[:1][0] if list(candidate_pool_recall_truncation_frontier_summary.get("closest_cases") or []) else {})
        if closest_case:
            next_actions.append(
                f"优先跟踪 {closest_case.get('ticker')}@{closest_case.get('trade_date')} 的 top300 cutoff gap={closest_case.get('pre_truncation_rank_gap_to_cutoff')}，评估是 rank 微调还是上游入口问题"
            )
        if candidate_pool_recall_ranking_driver in {"avg_amount_20d_gap_dominant", "avg_amount_20d_gap"}:
            next_actions.append("把 candidate_pool truncation 诊断继续下钻到 20 日成交额弱势，不再优先讨论扩大候选池上限。")
        elif candidate_pool_recall_ranking_driver == "market_cap_tie_break_gap":
            next_actions.append("把 candidate_pool truncation 诊断继续下钻到 cutoff 附近的市值 tie-break，而不是先放松 liquidity gate。")
        if candidate_pool_recall_liquidity_gap_mode == "well_above_gate_but_far_below_cutoff":
            next_actions.append("这批票多数已显著高于最低流动性门槛，下一步不要优先下调 MIN_AVG_AMOUNT_20D，而要解释为何过 gate 后仍长期输给 cutoff 竞争集。")
        elif candidate_pool_recall_liquidity_gap_mode == "barely_above_gate_and_far_below_cutoff":
            next_actions.append("这批票多数只是勉强高于最低流动性门槛，下一步应同时审查 liquidity gate 位置与 cutoff 竞争强度。")
        if candidate_pool_recall_focus_liquidity_profiles:
            next_actions.append(
                f"按焦点 ticker 画像拆分 handoff：{[(row.get('ticker'), row.get('priority_handoff')) for row in candidate_pool_recall_focus_liquidity_profiles[:3]]}。"
            )
        for diagnosis in candidate_pool_recall_priority_handoff_branch_diagnoses[:2]:
            next_step = str(diagnosis.get("next_step") or "").strip()
            if next_step:
                next_actions.append(next_step)
        for mechanism in candidate_pool_recall_priority_handoff_branch_mechanisms[:2]:
            summary = str(mechanism.get("mechanism_summary") or "").strip()
            if summary:
                next_actions.append(summary)
            pressure_summary = str(mechanism.get("pressure_cluster_summary") or "").strip()
            if pressure_summary:
                next_actions.append(pressure_summary)
            repair_summary = str(mechanism.get("repair_hypothesis_summary") or "").strip()
            if repair_summary:
                next_actions.append(repair_summary)
        for experiment in candidate_pool_recall_priority_handoff_branch_experiment_queue[:2]:
            prototype_summary = str(experiment.get("prototype_summary") or "").strip()
            if prototype_summary:
                next_actions.append(prototype_summary)
            evaluation_summary = str(experiment.get("evaluation_summary") or "").strip()
            if evaluation_summary:
                next_actions.append(evaluation_summary)
            success_signal = str(experiment.get("success_signal") or "").strip()
            if success_signal:
                next_actions.append(success_signal)
    elif watchlist_recall_candidate_pool_layer_b_gap_tickers:
        next_actions.append(
            f"优先回查 {watchlist_recall_candidate_pool_layer_b_gap_tickers} 的 candidate_pool -> layer_b handoff"
        )
    elif watchlist_recall_layer_b_watchlist_gap_tickers:
        next_actions.append(
            f"优先回查 {watchlist_recall_layer_b_watchlist_gap_tickers} 的 layer_b -> watchlist gate"
        )
    elif no_candidate_entry_watchlist_handoff_gap_tickers:
        next_actions.append(
            f"优先回查 {no_candidate_entry_watchlist_handoff_gap_tickers} 的 watchlist -> candidate-entry handoff"
        )
    elif no_candidate_entry_candidate_entry_target_gap_tickers:
        next_actions.append(
            f"优先回查 {no_candidate_entry_candidate_entry_target_gap_tickers} 的 candidate-entry -> selection_target contract"
        )
    elif no_candidate_entry_outside_candidate_entry_tickers:
        next_actions.append(
            f"优先回查 {no_candidate_entry_outside_candidate_entry_tickers} 的 watchlist -> candidate-entry handoff，而不是继续弱结构语义实验"
        )
    elif no_candidate_entry_semantic_miss_tickers:
        next_actions.append(
            f"仅把 {no_candidate_entry_semantic_miss_tickers} 继续保留在 candidate-entry semantic replay 车道"
        )
    if no_candidate_entry_promising_tickers:
        next_actions.append(
            f"把 {no_candidate_entry_promising_tickers} 作为 no-entry shadow recall probe 接回治理板，并持续核对 preserve_ticker 0 误伤"
        )

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
        "candidate_entry_rule": best_variant_name,
        "recommended_structural_variant": structural_alias,
        "lane_status": lane_status,
        "default_upgrade_status": default_upgrade_status,
        "target_window_count": shadow_state["target_window_count"],
        "missing_window_count": shadow_state["missing_window_count"],
        "upgrade_gap": shadow_state["upgrade_gap"],
        "score_frontier_all_zero": score_frontier_all_zero,
        "current_window_evidence": {
            "filtered_candidate_entry_count": current_window_filtered_count,
            "focus_filtered_tickers": current_window_focus_filtered,
            "preserve_filtered_tickers": current_window_preserve_filtered,
            "filtered_next_high_hit_rate_at_threshold": current_window_next_high,
            "filtered_next_close_positive_rate": current_window_next_close,
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
        "window_scan_summary": {
            "report_count": int(window_scan.get("report_count") or 0),
            "filtered_report_count": int(window_scan.get("filtered_report_count") or 0),
            "focus_hit_report_count": int(window_scan.get("focus_hit_report_count") or 0),
            "preserve_misfire_report_count": preserve_misfire_report_count,
            "distinct_window_count_with_filtered_entries": distinct_window_count_with_filtered_entries,
            "rollout_readiness": scan_readiness,
            "filtered_ticker_counts": dict(window_scan.get("filtered_ticker_counts") or {}),
        },
        "no_candidate_entry_action_board_summary": {
            "priority_queue_count": len(no_candidate_entry_priority_queue),
            "window_hotspot_count": len(no_candidate_entry_hotspots),
            "top_priority_tickers": no_candidate_entry_top_tickers,
            "top_hotspot_report_dirs": no_candidate_entry_top_hotspot_dirs,
            "next_task_ids": [str(task.get("task_id") or "") for task in no_candidate_entry_next_tasks[:3] if task.get("task_id")],
            "recommendation": no_candidate_entry_action_board.get("recommendation"),
        },
        "no_candidate_entry_replay_bundle_summary": {
            "promising_priority_tickers": no_candidate_entry_promising_tickers,
            "promising_hotspot_report_dirs": [
                str(value) for value in list(no_candidate_entry_replay_bundle.get("promising_hotspot_report_dirs") or []) if str(value or "").strip()
            ],
            "candidate_entry_status_counts": no_candidate_entry_replay_status_counts,
            "window_scan_rollout_readiness": dict(no_candidate_entry_replay_bundle.get("global_window_scan") or {}).get("rollout_readiness"),
            "recommendation": no_candidate_entry_replay_bundle.get("recommendation"),
        },
        "no_candidate_entry_failure_dossier_summary": {
            "priority_failure_class_counts": no_candidate_entry_priority_failure_class_counts,
            "priority_handoff_stage_counts": no_candidate_entry_handoff_stage_counts,
            "top_upstream_absence_tickers": no_candidate_entry_upstream_absence_tickers,
            "top_absent_from_watchlist_tickers": no_candidate_entry_absent_from_watchlist_tickers,
            "top_watchlist_visible_but_not_candidate_entry_tickers": no_candidate_entry_watchlist_handoff_gap_tickers,
            "top_candidate_entry_visible_but_not_selection_target_tickers": no_candidate_entry_candidate_entry_target_gap_tickers,
            "top_present_but_outside_candidate_entry_tickers": no_candidate_entry_outside_candidate_entry_tickers,
            "top_candidate_entry_semantic_miss_tickers": no_candidate_entry_semantic_miss_tickers,
            "recommendation": no_candidate_entry_failure_dossier.get("recommendation"),
        },
        "watchlist_recall_dossier_summary": {
            "priority_recall_stage_counts": watchlist_recall_stage_counts,
            "top_absent_from_candidate_pool_tickers": watchlist_recall_absent_from_candidate_pool_tickers,
            "top_candidate_pool_visible_but_missing_layer_b_tickers": watchlist_recall_candidate_pool_layer_b_gap_tickers,
            "top_layer_b_visible_but_missing_watchlist_tickers": watchlist_recall_layer_b_watchlist_gap_tickers,
            "recommendation": watchlist_recall_dossier.get("recommendation"),
        },
        "candidate_pool_recall_dossier_summary": {
            "priority_stage_counts": candidate_pool_recall_stage_counts,
            "dominant_stage": candidate_pool_recall_dominant_stage,
            "top_stage_tickers": candidate_pool_recall_top_stage_tickers,
            "truncation_frontier_summary": candidate_pool_recall_truncation_frontier_summary,
            "dominant_ranking_driver": candidate_pool_recall_ranking_driver,
            "dominant_liquidity_gap_mode": candidate_pool_recall_liquidity_gap_mode,
            "focus_liquidity_profile_summary": candidate_pool_recall_focus_liquidity_profile_summary,
            "focus_liquidity_profiles": candidate_pool_recall_focus_liquidity_profiles[:3],
            "priority_handoff_branch_diagnoses": candidate_pool_recall_priority_handoff_branch_diagnoses[:3],
            "priority_handoff_branch_mechanisms": candidate_pool_recall_priority_handoff_branch_mechanisms[:3],
            "priority_handoff_branch_experiment_queue": candidate_pool_recall_priority_handoff_branch_experiment_queue[:3],
            "recommendation": candidate_pool_recall_dossier.get("recommendation"),
        },
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


def render_btst_candidate_entry_rollout_governance_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Entry Rollout Governance")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- candidate_entry_rule: {analysis['candidate_entry_rule']}")
    lines.append(f"- recommended_structural_variant: {analysis['recommended_structural_variant']}")
    lines.append(f"- lane_status: {analysis['lane_status']}")
    lines.append(f"- default_upgrade_status: {analysis['default_upgrade_status']}")
    lines.append(f"- target_window_count: {analysis['target_window_count']}")
    lines.append(f"- missing_window_count: {analysis['missing_window_count']}")
    lines.append(f"- upgrade_gap: {analysis['upgrade_gap']}")
    lines.append(f"- score_frontier_all_zero: {analysis['score_frontier_all_zero']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    lines.append("")
    lines.append("## Current Window Evidence")
    for key, value in dict(analysis.get("current_window_evidence") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Main-Chain Validation")
    for key, value in dict(analysis.get("main_chain_validation") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Window Scan Summary")
    for key, value in dict(analysis.get("window_scan_summary") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## No Candidate Entry Action Board")
    for key, value in dict(analysis.get("no_candidate_entry_action_board_summary") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## No Candidate Entry Replay Bundle")
    for key, value in dict(analysis.get("no_candidate_entry_replay_bundle_summary") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## No Candidate Entry Failure Dossier")
    for key, value in dict(analysis.get("no_candidate_entry_failure_dossier_summary") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Watchlist Recall Dossier")
    for key, value in dict(analysis.get("watchlist_recall_dossier_summary") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Candidate Pool Recall Dossier")
    for key, value in dict(analysis.get("candidate_pool_recall_dossier_summary") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Keep Guardrails")
    for item in list(analysis.get("keep_guardrails") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Promotion Conditions")
    for item in list(analysis.get("promotion_conditions") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Next Actions")
    for item in list(analysis.get("next_actions") or []):
        lines.append(f"- {item}")
    lines.append("")
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