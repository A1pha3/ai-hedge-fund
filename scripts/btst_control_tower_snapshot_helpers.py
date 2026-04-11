from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


ExtractSnapshotSections = Callable[[dict[str, Any]], dict[str, Any]]
ExtractOverlayInputs = Callable[[dict[str, Any]], dict[str, list[Any]]]
BuildUpstreamShadowFollowupOverlay = Callable[..., dict[str, Any]]


def extract_control_tower_snapshot(
    manifest: dict[str, Any],
    *,
    extract_snapshot_sections: ExtractSnapshotSections,
    extract_overlay_inputs: ExtractOverlayInputs,
    build_upstream_shadow_followup_overlay: BuildUpstreamShadowFollowupOverlay,
    reports_dir: Path,
) -> dict[str, Any]:
    snapshot_sections = extract_snapshot_sections(manifest)
    overlay_inputs = extract_overlay_inputs(snapshot_sections)
    upstream_shadow_followup_overlay = build_upstream_shadow_followup_overlay(
        manifest.get("reports_root") or reports_dir,
        no_candidate_entry_priority_tickers=overlay_inputs["no_candidate_entry_priority_tickers"],
        absent_from_watchlist_tickers=overlay_inputs["absent_from_watchlist_tickers"],
        watchlist_absent_from_candidate_pool_tickers=overlay_inputs["watchlist_absent_from_candidate_pool_tickers"],
        upstream_handoff_focus_tickers=overlay_inputs["upstream_handoff_focus_tickers"],
    )
    synthesis = snapshot_sections["synthesis"]
    validation = snapshot_sections["validation"]
    independent_window_monitor = snapshot_sections["independent_window_monitor"]
    tplus1_tplus2_objective_monitor = snapshot_sections["tplus1_tplus2_objective_monitor"]
    tradeable_opportunity_pool = snapshot_sections["tradeable_opportunity_pool"]
    no_candidate_entry_action_board = snapshot_sections["no_candidate_entry_action_board"]
    no_candidate_entry_replay_bundle = snapshot_sections["no_candidate_entry_replay_bundle"]
    no_candidate_entry_failure_dossier = snapshot_sections["no_candidate_entry_failure_dossier"]
    watchlist_recall_dossier = snapshot_sections["watchlist_recall_dossier"]
    candidate_pool_recall_dossier = snapshot_sections["candidate_pool_recall_dossier"]
    selected_outcome_refresh_summary = snapshot_sections["selected_outcome_refresh_summary"]
    carryover_multiday_continuation_audit_summary = snapshot_sections["carryover_multiday_continuation_audit_summary"]
    carryover_aligned_peer_harvest_summary = snapshot_sections["carryover_aligned_peer_harvest_summary"]
    carryover_peer_expansion_summary = snapshot_sections["carryover_peer_expansion_summary"]
    carryover_aligned_peer_proof_summary = snapshot_sections["carryover_aligned_peer_proof_summary"]
    carryover_peer_promotion_gate_summary = snapshot_sections["carryover_peer_promotion_gate_summary"]
    default_merge_review_summary = snapshot_sections["default_merge_review_summary"]
    default_merge_historical_counterfactual_summary = snapshot_sections["default_merge_historical_counterfactual_summary"]
    continuation_merge_candidate_ranking_summary = snapshot_sections["continuation_merge_candidate_ranking_summary"]
    default_merge_strict_counterfactual_summary = snapshot_sections["default_merge_strict_counterfactual_summary"]
    merge_replay_validation_summary = snapshot_sections["merge_replay_validation_summary"]
    prepared_breakout_relief_validation_summary = snapshot_sections["prepared_breakout_relief_validation_summary"]
    prepared_breakout_cohort_summary = snapshot_sections["prepared_breakout_cohort_summary"]
    prepared_breakout_residual_surface_summary = snapshot_sections["prepared_breakout_residual_surface_summary"]
    candidate_pool_corridor_persistence_dossier_summary = snapshot_sections["candidate_pool_corridor_persistence_dossier_summary"]
    candidate_pool_corridor_window_command_board_summary = snapshot_sections["candidate_pool_corridor_window_command_board_summary"]
    candidate_pool_corridor_window_diagnostics_summary = snapshot_sections["candidate_pool_corridor_window_diagnostics_summary"]
    candidate_pool_corridor_narrow_probe_summary = snapshot_sections["candidate_pool_corridor_narrow_probe_summary"]
    no_candidate_entry_priority_tickers = overlay_inputs["no_candidate_entry_priority_tickers"]
    absent_from_watchlist_tickers = overlay_inputs["absent_from_watchlist_tickers"]
    watchlist_absent_from_candidate_pool_tickers = overlay_inputs["watchlist_absent_from_candidate_pool_tickers"]
    shadow_visible_focus_tickers = [str(ticker) for ticker in list(candidate_pool_recall_dossier.get("shadow_visible_focus_tickers") or []) if str(ticker).strip()]
    shadow_visible_focus_profiles = [dict(row) for row in list(candidate_pool_recall_dossier.get("shadow_visible_focus_profiles") or [])]
    excluded_low_gate_tail_tickers = {
        str(ticker).strip()
        for ticker in list(dict(candidate_pool_recall_dossier.get("corridor_uplift_runbook_summary") or {}).get("excluded_low_gate_tail_tickers") or [])
        if str(ticker).strip()
    }
    rebucket_shadow_pack_status = str(candidate_pool_recall_dossier.get("rebucket_shadow_pack_status") or "").strip()
    rebucket_shadow_pack_experiment = dict(candidate_pool_recall_dossier.get("rebucket_shadow_pack_experiment") or {})
    transient_rebucket_probe_tickers = {
        str(ticker).strip()
        for ticker in list(rebucket_shadow_pack_experiment.get("tickers") or [])
        if str(ticker).strip()
    } if rebucket_shadow_pack_status == "persistence_diagnostics_only" else set()
    active_shadow_visible_focus_tickers = [
        ticker
        for ticker in shadow_visible_focus_tickers
        if ticker not in excluded_low_gate_tail_tickers and ticker not in transient_rebucket_probe_tickers
    ]
    active_shadow_visible_focus_profiles = [
        dict(row)
        for row in shadow_visible_focus_profiles
        if str(row.get("ticker") or "").strip() not in excluded_low_gate_tail_tickers
        and str(row.get("ticker") or "").strip() not in transient_rebucket_probe_tickers
    ]
    return {
        "synthesis": synthesis,
        "validation": validation,
        "independent_window_monitor": independent_window_monitor,
        "tplus1_tplus2_objective_monitor": tplus1_tplus2_objective_monitor,
        "tradeable_opportunity_pool": tradeable_opportunity_pool,
        "no_candidate_entry_action_board": no_candidate_entry_action_board,
        "no_candidate_entry_replay_bundle": no_candidate_entry_replay_bundle,
        "no_candidate_entry_failure_dossier": no_candidate_entry_failure_dossier,
        "watchlist_recall_dossier": watchlist_recall_dossier,
        "candidate_pool_recall_dossier": candidate_pool_recall_dossier,
        "selected_outcome_refresh_summary": selected_outcome_refresh_summary,
        "carryover_multiday_continuation_audit_summary": carryover_multiday_continuation_audit_summary,
        "carryover_aligned_peer_harvest_summary": carryover_aligned_peer_harvest_summary,
        "carryover_peer_expansion_summary": carryover_peer_expansion_summary,
        "carryover_aligned_peer_proof_summary": carryover_aligned_peer_proof_summary,
        "carryover_peer_promotion_gate_summary": carryover_peer_promotion_gate_summary,
        "rollout_lanes": list(synthesis.get("lane_matrix") or []),
        "waiting_lane_count": synthesis.get("waiting_lane_count"),
        "ready_lane_count": synthesis.get("ready_lane_count"),
        "recommendation": synthesis.get("recommendation"),
        "lane_status_counts": synthesis.get("lane_status_counts"),
        "closed_frontiers": list(synthesis.get("closed_frontiers") or []),
        "next_actions": list(synthesis.get("next_actions") or [])[:3],
        "independent_window_ready_lane_count": independent_window_monitor.get("ready_lane_count"),
        "independent_window_waiting_lane_count": independent_window_monitor.get("waiting_lane_count"),
        "tplus1_tplus2_tradeable_positive_rate": dict(tplus1_tplus2_objective_monitor.get("tradeable_surface") or {}).get("t_plus_2_positive_rate"),
        "tplus1_tplus2_tradeable_return_hit_rate": dict(tplus1_tplus2_objective_monitor.get("tradeable_surface") or {}).get("t_plus_2_return_hit_rate_at_target"),
        "tplus1_tplus2_tradeable_mean_return": dict(tplus1_tplus2_objective_monitor.get("tradeable_surface") or {}).get("mean_t_plus_2_return"),
        "tplus1_tplus2_tradeable_verdict": dict(tplus1_tplus2_objective_monitor.get("tradeable_surface") or {}).get("verdict"),
        "tradeable_opportunity_pool_count": tradeable_opportunity_pool.get("tradeable_opportunity_pool_count"),
        "tradeable_opportunity_capture_rate": tradeable_opportunity_pool.get("tradeable_pool_capture_rate"),
        "tradeable_opportunity_selected_or_near_miss_rate": tradeable_opportunity_pool.get("tradeable_pool_selected_or_near_miss_rate"),
        "tradeable_opportunity_top_kill_switches": tradeable_opportunity_pool.get("top_tradeable_kill_switch_labels"),
        "no_candidate_entry_priority_queue_count": no_candidate_entry_action_board.get("priority_queue_count"),
        "no_candidate_entry_priority_tickers": no_candidate_entry_priority_tickers,
        "active_no_candidate_entry_priority_tickers": upstream_shadow_followup_overlay.get("active_no_candidate_entry_priority_tickers"),
        "no_candidate_entry_recall_probe_tickers": no_candidate_entry_replay_bundle.get("promising_priority_tickers"),
        "no_candidate_entry_failure_class_counts": no_candidate_entry_failure_dossier.get("priority_failure_class_counts"),
        "no_candidate_entry_handoff_stage_counts": no_candidate_entry_failure_dossier.get("priority_handoff_stage_counts"),
        "no_candidate_entry_absent_from_watchlist_tickers": absent_from_watchlist_tickers,
        "active_no_candidate_entry_absent_from_watchlist_tickers": upstream_shadow_followup_overlay.get("active_absent_from_watchlist_tickers"),
        "no_candidate_entry_watchlist_handoff_gap_tickers": no_candidate_entry_failure_dossier.get("top_watchlist_visible_but_not_candidate_entry_tickers"),
        "no_candidate_entry_upstream_absence_tickers": no_candidate_entry_failure_dossier.get("top_upstream_absence_tickers"),
        "watchlist_recall_stage_counts": watchlist_recall_dossier.get("priority_recall_stage_counts"),
        "watchlist_recall_absent_from_candidate_pool_tickers": watchlist_absent_from_candidate_pool_tickers,
        "active_watchlist_recall_absent_from_candidate_pool_tickers": upstream_shadow_followup_overlay.get("active_watchlist_absent_from_candidate_pool_tickers"),
        "watchlist_recall_candidate_pool_layer_b_gap_tickers": watchlist_recall_dossier.get("top_candidate_pool_visible_but_missing_layer_b_tickers"),
        "watchlist_recall_layer_b_watchlist_gap_tickers": watchlist_recall_dossier.get("top_layer_b_visible_but_missing_watchlist_tickers"),
        "candidate_pool_recall_stage_counts": candidate_pool_recall_dossier.get("priority_stage_counts"),
        "candidate_pool_recall_dominant_stage": candidate_pool_recall_dossier.get("dominant_stage"),
        "candidate_pool_recall_top_stage_tickers": candidate_pool_recall_dossier.get("top_stage_tickers"),
        "candidate_pool_recall_truncation_frontier_summary": candidate_pool_recall_dossier.get("truncation_frontier_summary"),
        "candidate_pool_recall_dominant_ranking_driver": dict(candidate_pool_recall_dossier.get("truncation_frontier_summary") or {}).get("dominant_ranking_driver"),
        "candidate_pool_recall_dominant_liquidity_gap_mode": dict(candidate_pool_recall_dossier.get("truncation_frontier_summary") or {}).get("dominant_liquidity_gap_mode"),
        "candidate_pool_recall_focus_liquidity_profiles": list(candidate_pool_recall_dossier.get("focus_liquidity_profiles") or []),
        "candidate_pool_recall_shadow_visible_focus_tickers": shadow_visible_focus_tickers,
        "candidate_pool_recall_shadow_visible_focus_profiles": shadow_visible_focus_profiles,
        "active_candidate_pool_recall_shadow_visible_focus_tickers": active_shadow_visible_focus_tickers,
        "active_candidate_pool_recall_shadow_visible_focus_profiles": active_shadow_visible_focus_profiles,
        "candidate_pool_recall_priority_handoff_counts": dict(candidate_pool_recall_dossier.get("priority_handoff_counts") or {}),
        "candidate_pool_recall_priority_handoff_branch_diagnoses": list(candidate_pool_recall_dossier.get("priority_handoff_branch_diagnoses") or []),
        "candidate_pool_recall_priority_handoff_branch_mechanisms": list(candidate_pool_recall_dossier.get("priority_handoff_branch_mechanisms") or []),
        "candidate_pool_recall_priority_handoff_branch_experiment_queue": list(candidate_pool_recall_dossier.get("priority_handoff_branch_experiment_queue") or []),
        "candidate_pool_branch_priority_board_status": candidate_pool_recall_dossier.get("branch_priority_board_status"),
        "candidate_pool_branch_priority_board_rows": list(candidate_pool_recall_dossier.get("branch_priority_board_rows") or []),
        "candidate_pool_branch_priority_alignment_status": candidate_pool_recall_dossier.get("branch_priority_alignment_status"),
        "candidate_pool_branch_priority_alignment_summary": candidate_pool_recall_dossier.get("branch_priority_alignment_summary"),
        "candidate_pool_lane_objective_support_status": candidate_pool_recall_dossier.get("lane_objective_support_status"),
        "candidate_pool_lane_objective_support_rows": list(candidate_pool_recall_dossier.get("lane_objective_support_rows") or []),
        "candidate_pool_corridor_validation_pack_status": candidate_pool_recall_dossier.get("corridor_validation_pack_status"),
        "candidate_pool_corridor_validation_pack_summary": dict(candidate_pool_recall_dossier.get("corridor_validation_pack_summary") or {}),
        "candidate_pool_corridor_shadow_pack_status": candidate_pool_recall_dossier.get("corridor_shadow_pack_status"),
        "candidate_pool_corridor_shadow_pack_summary": dict(candidate_pool_recall_dossier.get("corridor_shadow_pack_summary") or {}),
        "candidate_pool_rebucket_shadow_pack_status": candidate_pool_recall_dossier.get("rebucket_shadow_pack_status"),
        "candidate_pool_rebucket_shadow_pack_experiment": dict(candidate_pool_recall_dossier.get("rebucket_shadow_pack_experiment") or {}),
        "candidate_pool_rebucket_objective_validation_status": candidate_pool_recall_dossier.get("rebucket_objective_validation_status"),
        "candidate_pool_rebucket_objective_validation_summary": dict(candidate_pool_recall_dossier.get("rebucket_objective_validation_summary") or {}),
        "candidate_pool_rebucket_comparison_bundle_status": candidate_pool_recall_dossier.get("rebucket_comparison_bundle_status"),
        "candidate_pool_rebucket_comparison_bundle_summary": dict(candidate_pool_recall_dossier.get("rebucket_comparison_bundle_summary") or {}),
        "candidate_pool_lane_pair_board_status": candidate_pool_recall_dossier.get("lane_pair_board_status"),
        "candidate_pool_lane_pair_board_summary": dict(candidate_pool_recall_dossier.get("lane_pair_board_summary") or {}),
        "continuation_focus_summary": dict(candidate_pool_recall_dossier.get("continuation_focus_summary") or {}),
        "candidate_pool_upstream_handoff_board_status": candidate_pool_recall_dossier.get("upstream_handoff_board_status"),
        "candidate_pool_upstream_handoff_board_summary": dict(candidate_pool_recall_dossier.get("upstream_handoff_board_summary") or {}),
        "active_candidate_pool_upstream_handoff_focus_tickers": upstream_shadow_followup_overlay.get("active_upstream_handoff_focus_tickers"),
        "candidate_pool_corridor_uplift_runbook_status": candidate_pool_recall_dossier.get("corridor_uplift_runbook_status"),
        "candidate_pool_corridor_uplift_runbook_summary": dict(candidate_pool_recall_dossier.get("corridor_uplift_runbook_summary") or {}),
        "continuation_promotion_ready_summary": dict(candidate_pool_recall_dossier.get("continuation_promotion_ready_summary") or {}),
        "default_merge_review_summary": default_merge_review_summary,
        "default_merge_historical_counterfactual_summary": default_merge_historical_counterfactual_summary,
        "continuation_merge_candidate_ranking_summary": continuation_merge_candidate_ranking_summary,
        "default_merge_strict_counterfactual_summary": default_merge_strict_counterfactual_summary,
        "merge_replay_validation_summary": merge_replay_validation_summary,
        "prepared_breakout_relief_validation_summary": prepared_breakout_relief_validation_summary,
        "prepared_breakout_cohort_summary": prepared_breakout_cohort_summary,
        "prepared_breakout_residual_surface_summary": prepared_breakout_residual_surface_summary,
        "candidate_pool_corridor_persistence_dossier_summary": candidate_pool_corridor_persistence_dossier_summary,
        "candidate_pool_corridor_window_command_board_summary": candidate_pool_corridor_window_command_board_summary,
        "candidate_pool_corridor_window_diagnostics_summary": candidate_pool_corridor_window_diagnostics_summary,
        "candidate_pool_corridor_narrow_probe_summary": candidate_pool_corridor_narrow_probe_summary,
        "execution_constraint_rollup": dict(candidate_pool_recall_dossier.get("execution_constraint_rollup") or {}),
        "transient_probe_summary": dict(candidate_pool_recall_dossier.get("transient_probe_summary") or {}),
        "upstream_shadow_followup_overlay": upstream_shadow_followup_overlay,
        "upstream_shadow_followup_validated_tickers": upstream_shadow_followup_overlay.get("validated_tickers"),
        "upstream_shadow_followup_decision_counts": upstream_shadow_followup_overlay.get("decision_counts"),
        "upstream_shadow_followup_near_miss_tickers": upstream_shadow_followup_overlay.get("near_miss_tickers"),
        "upstream_shadow_followup_rejected_profitability_tickers": upstream_shadow_followup_overlay.get("rejected_profitability_tickers"),
        "upstream_shadow_followup_recommendation": upstream_shadow_followup_overlay.get("recommendation"),
        "overall_verdict": validation.get("overall_verdict"),
        "warn_count": validation.get("warn_count"),
        "fail_count": validation.get("fail_count"),
    }
