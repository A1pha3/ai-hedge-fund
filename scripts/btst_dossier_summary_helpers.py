from __future__ import annotations

from collections.abc import Callable
from typing import Any


SafeLoadJson = Callable[[str | None], dict[str, Any]]
EntryById = Callable[[dict[str, Any], str], dict[str, Any]]


def _extract_candidate_pool_shadow_visible_focus_profiles(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    focus_profiles = {
        str(row.get("ticker") or "").strip(): dict(row)
        for row in list(dict(analysis.get("focus_liquidity_profile_summary") or {}).get("primary_focus_tickers") or [])
        if str(row.get("ticker") or "").strip()
    }
    visible_profiles: list[dict[str, Any]] = []
    seen_tickers: set[str] = set()
    for dossier in list(analysis.get("priority_ticker_dossiers") or []):
        ticker = str(dossier.get("ticker") or "").strip()
        if not ticker or ticker in seen_tickers:
            continue
        occurrence = next(
            (
                dict(row)
                for row in list(dossier.get("occurrence_evidence") or [])
                if bool(row.get("candidate_pool_shadow_visible"))
            ),
            None,
        )
        if occurrence is None:
            continue
        visible_profiles.append(
            {
                **focus_profiles.get(ticker, {"ticker": ticker}),
                "candidate_pool_shadow_visible": True,
                "candidate_pool_shadow_rank": occurrence.get("candidate_pool_shadow_rank"),
                "candidate_pool_shadow_lane": occurrence.get("candidate_pool_shadow_lane"),
                "candidate_pool_shadow_reason": occurrence.get("candidate_pool_shadow_reason"),
                "candidate_pool_shadow_focus_signature": occurrence.get("candidate_pool_shadow_focus_signature"),
                "candidate_pool_shadow_snapshot_path": occurrence.get("candidate_pool_shadow_snapshot_path"),
                "dominant_blocking_stage": dossier.get("dominant_blocking_stage"),
            }
        )
        seen_tickers.add(ticker)
        if len(visible_profiles) >= 3:
            break
    return visible_profiles


def extract_no_candidate_entry_action_board_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    refresh = dict(manifest.get("candidate_entry_shadow_refresh") or {})
    action_board_entry = entry_by_id(manifest, "btst_no_candidate_entry_action_board_latest")
    analysis = safe_load_json(refresh.get("no_candidate_entry_action_board_json") or action_board_entry.get("absolute_path"))
    if not any([refresh, analysis, action_board_entry]):
        return {}

    next_tasks = list(analysis.get("next_3_tasks") or [])[:3]
    priority_queue = list(analysis.get("priority_queue") or [])[:3]
    return {
        "status": refresh.get("no_candidate_entry_action_board_status") or ("available" if analysis else None),
        "priority_queue_count": refresh.get("no_candidate_entry_priority_queue_count") or analysis.get("priority_queue_count"),
        "top_priority_tickers": refresh.get("no_candidate_entry_top_tickers") or analysis.get("top_priority_tickers"),
        "top_hotspot_report_dirs": refresh.get("no_candidate_entry_hotspot_report_dirs") or analysis.get("top_hotspot_report_dirs"),
        "next_tasks": next_tasks,
        "priority_queue": priority_queue,
        "recommendation": analysis.get("recommendation"),
        "analysis_markdown_path": action_board_entry.get("absolute_path"),
    }


def extract_no_candidate_entry_replay_bundle_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    refresh = dict(manifest.get("candidate_entry_shadow_refresh") or {})
    bundle_entry = entry_by_id(manifest, "btst_no_candidate_entry_replay_bundle_latest")
    analysis = safe_load_json(refresh.get("no_candidate_entry_replay_bundle_json") or bundle_entry.get("absolute_path"))
    if not any([refresh, analysis, bundle_entry]):
        return {}

    global_window_scan = dict(analysis.get("global_window_scan") or {})
    return {
        "status": refresh.get("no_candidate_entry_replay_bundle_status") or ("available" if analysis else None),
        "promising_priority_tickers": refresh.get("no_candidate_entry_promising_tickers") or analysis.get("promising_priority_tickers"),
        "promising_hotspot_report_dirs": analysis.get("promising_hotspot_report_dirs"),
        "candidate_entry_status_counts": analysis.get("candidate_entry_status_counts"),
        "global_window_scan_rollout_readiness": global_window_scan.get("rollout_readiness"),
        "global_window_scan_focus_hit_report_count": global_window_scan.get("focus_hit_report_count"),
        "next_actions": list(analysis.get("next_actions") or [])[:3],
        "recommendation": analysis.get("recommendation"),
        "analysis_markdown_path": bundle_entry.get("absolute_path"),
    }


def extract_no_candidate_entry_failure_dossier_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    refresh = dict(manifest.get("candidate_entry_shadow_refresh") or {})
    dossier_entry = entry_by_id(manifest, "btst_no_candidate_entry_failure_dossier_latest")
    analysis = safe_load_json(refresh.get("no_candidate_entry_failure_dossier_json") or dossier_entry.get("absolute_path"))
    if not any([refresh, analysis, dossier_entry]):
        return {}

    return {
        "status": refresh.get("no_candidate_entry_failure_dossier_status") or ("available" if analysis else None),
        "priority_failure_class_counts": analysis.get("priority_failure_class_counts"),
        "hotspot_failure_class_counts": analysis.get("hotspot_failure_class_counts"),
        "priority_handoff_stage_counts": analysis.get("priority_handoff_stage_counts"),
        "top_absent_from_watchlist_tickers": analysis.get("top_absent_from_watchlist_tickers"),
        "top_watchlist_visible_but_not_candidate_entry_tickers": analysis.get("top_watchlist_visible_but_not_candidate_entry_tickers"),
        "top_candidate_entry_visible_but_not_selection_target_tickers": analysis.get("top_candidate_entry_visible_but_not_selection_target_tickers"),
        "top_upstream_absence_tickers": refresh.get("no_candidate_entry_upstream_absence_tickers") or analysis.get("top_upstream_absence_tickers"),
        "top_candidate_entry_semantic_miss_tickers": refresh.get("no_candidate_entry_semantic_miss_tickers") or analysis.get("top_candidate_entry_semantic_miss_tickers"),
        "top_present_but_outside_candidate_entry_tickers": analysis.get("top_present_but_outside_candidate_entry_tickers"),
        "top_missing_replay_input_tickers": analysis.get("top_missing_replay_input_tickers"),
        "handoff_action_queue": list(analysis.get("priority_handoff_action_queue") or [])[:3],
        "next_actions": list(analysis.get("next_actions") or [])[:4],
        "recommendation": analysis.get("recommendation"),
        "analysis_markdown_path": dossier_entry.get("absolute_path"),
    }


def extract_watchlist_recall_dossier_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    refresh = dict(manifest.get("candidate_entry_shadow_refresh") or {})
    dossier_entry = entry_by_id(manifest, "btst_watchlist_recall_dossier_latest")
    analysis = safe_load_json(refresh.get("watchlist_recall_dossier_json") or dossier_entry.get("absolute_path"))
    if not any([refresh, analysis, dossier_entry]):
        return {}

    return {
        "status": refresh.get("watchlist_recall_dossier_status") or ("available" if analysis else None),
        "priority_recall_stage_counts": analysis.get("priority_recall_stage_counts"),
        "top_absent_from_candidate_pool_tickers": refresh.get("watchlist_recall_absent_from_candidate_pool_tickers") or analysis.get("top_absent_from_candidate_pool_tickers"),
        "top_candidate_pool_visible_but_missing_layer_b_tickers": refresh.get("watchlist_recall_candidate_pool_layer_b_gap_tickers") or analysis.get("top_candidate_pool_visible_but_missing_layer_b_tickers"),
        "top_layer_b_visible_but_missing_watchlist_tickers": refresh.get("watchlist_recall_layer_b_watchlist_gap_tickers") or analysis.get("top_layer_b_visible_but_missing_watchlist_tickers"),
        "action_queue": list(analysis.get("action_queue") or [])[:3],
        "next_actions": list(analysis.get("next_actions") or [])[:4],
        "recommendation": analysis.get("recommendation"),
        "analysis_markdown_path": dossier_entry.get("absolute_path"),
    }


def extract_candidate_pool_recall_dossier_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    refresh = dict(manifest.get("candidate_entry_shadow_refresh") or {})
    dossier_entry = entry_by_id(manifest, "btst_candidate_pool_recall_dossier_latest")
    analysis = safe_load_json(refresh.get("candidate_pool_recall_dossier_json") or dossier_entry.get("absolute_path"))
    if not any([refresh, analysis, dossier_entry]):
        return {}

    shadow_visible_focus_profiles = (
        refresh.get("candidate_pool_recall_shadow_visible_focus_profiles")
        or _extract_candidate_pool_shadow_visible_focus_profiles(analysis)
    )
    return {
        "status": refresh.get("candidate_pool_recall_dossier_status") or ("available" if analysis else None),
        "priority_stage_counts": refresh.get("candidate_pool_recall_stage_counts") or analysis.get("priority_stage_counts"),
        "dominant_stage": refresh.get("candidate_pool_recall_dominant_stage") or analysis.get("dominant_stage"),
        "top_stage_tickers": refresh.get("candidate_pool_recall_top_stage_tickers") or analysis.get("top_stage_tickers"),
        "truncation_frontier_summary": refresh.get("candidate_pool_recall_truncation_frontier_summary") or analysis.get("truncation_frontier_summary"),
        "focus_liquidity_profiles": refresh.get("candidate_pool_recall_focus_liquidity_profiles") or list(dict(analysis.get("focus_liquidity_profile_summary") or {}).get("primary_focus_tickers") or [])[:3],
        "shadow_visible_focus_tickers": refresh.get("candidate_pool_recall_shadow_visible_focus_tickers") or [row.get("ticker") for row in shadow_visible_focus_profiles if row.get("ticker")],
        "shadow_visible_focus_profiles": shadow_visible_focus_profiles,
        "priority_handoff_counts": refresh.get("candidate_pool_recall_priority_handoff_counts") or dict(dict(analysis.get("focus_liquidity_profile_summary") or {}).get("priority_handoff_counts") or {}),
        "priority_handoff_branch_diagnoses": refresh.get("candidate_pool_recall_priority_handoff_branch_diagnoses") or list(analysis.get("priority_handoff_branch_diagnoses") or [])[:3],
        "priority_handoff_branch_mechanisms": refresh.get("candidate_pool_recall_priority_handoff_branch_mechanisms") or list(analysis.get("priority_handoff_branch_mechanisms") or [])[:3],
        "priority_handoff_branch_experiment_queue": refresh.get("candidate_pool_recall_priority_handoff_branch_experiment_queue") or list(analysis.get("priority_handoff_branch_experiment_queue") or [])[:3],
        "branch_priority_board_status": refresh.get("candidate_pool_branch_priority_board_status"),
        "branch_priority_board_rows": list(refresh.get("candidate_pool_branch_priority_board_rows") or []),
        "branch_priority_alignment_status": refresh.get("candidate_pool_branch_priority_alignment_status"),
        "branch_priority_alignment_summary": refresh.get("candidate_pool_branch_priority_alignment_summary"),
        "lane_objective_support_status": refresh.get("candidate_pool_lane_objective_support_status"),
        "lane_objective_support_rows": list(refresh.get("candidate_pool_lane_objective_support_rows") or []),
        "corridor_validation_pack_status": refresh.get("candidate_pool_corridor_validation_pack_status"),
        "corridor_validation_pack_summary": dict(refresh.get("candidate_pool_corridor_validation_pack_summary") or {}),
        "corridor_shadow_pack_status": refresh.get("candidate_pool_corridor_shadow_pack_status"),
        "corridor_shadow_pack_summary": dict(refresh.get("candidate_pool_corridor_shadow_pack_summary") or {}),
        "rebucket_shadow_pack_status": refresh.get("candidate_pool_rebucket_shadow_pack_status"),
        "rebucket_shadow_pack_experiment": dict(refresh.get("candidate_pool_rebucket_shadow_pack_experiment") or {}),
        "rebucket_objective_validation_status": refresh.get("candidate_pool_rebucket_objective_validation_status"),
        "rebucket_objective_validation_summary": dict(refresh.get("candidate_pool_rebucket_objective_validation_summary") or {}),
        "rebucket_comparison_bundle_status": refresh.get("candidate_pool_rebucket_comparison_bundle_status"),
        "rebucket_comparison_bundle_summary": dict(refresh.get("candidate_pool_rebucket_comparison_bundle_summary") or {}),
        "lane_pair_board_status": refresh.get("candidate_pool_lane_pair_board_status"),
        "lane_pair_board_summary": dict(refresh.get("candidate_pool_lane_pair_board_summary") or {}),
        "continuation_focus_summary": dict(refresh.get("continuation_focus_summary") or {}),
        "continuation_promotion_ready_summary": dict(refresh.get("continuation_promotion_ready_summary") or {}),
        "transient_probe_summary": dict(refresh.get("transient_probe_summary") or {}),
        "upstream_handoff_board_status": refresh.get("candidate_pool_upstream_handoff_board_status"),
        "upstream_handoff_board_summary": dict(refresh.get("candidate_pool_upstream_handoff_board_summary") or {}),
        "corridor_uplift_runbook_status": refresh.get("candidate_pool_corridor_uplift_runbook_status"),
        "corridor_uplift_runbook_summary": dict(refresh.get("candidate_pool_corridor_uplift_runbook_summary") or {}),
        "execution_constraint_rollup": dict(refresh.get("execution_constraint_rollup") or {}),
        "action_queue": list(analysis.get("action_queue") or [])[:3],
        "next_actions": list(analysis.get("next_actions") or [])[:4],
        "recommendation": analysis.get("recommendation"),
        "analysis_markdown_path": dossier_entry.get("absolute_path"),
    }
