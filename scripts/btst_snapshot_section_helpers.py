from __future__ import annotations

from collections.abc import Callable
from typing import Any


SafeLoadJson = Callable[[str | None], dict[str, Any]]
ManifestExtractor = Callable[[dict[str, Any]], dict[str, Any]]


def extract_control_tower_snapshot_sections(
    manifest: dict[str, Any],
    *,
    safe_load_json: SafeLoadJson,
    extract_tradeable_opportunity_pool_summary: ManifestExtractor,
    extract_no_candidate_entry_action_board_summary: ManifestExtractor,
    extract_no_candidate_entry_replay_bundle_summary: ManifestExtractor,
    extract_no_candidate_entry_failure_dossier_summary: ManifestExtractor,
    extract_watchlist_recall_dossier_summary: ManifestExtractor,
    extract_candidate_pool_recall_dossier_summary: ManifestExtractor,
    extract_selected_outcome_refresh_summary: ManifestExtractor,
    extract_carryover_multiday_continuation_audit_summary: ManifestExtractor,
    extract_carryover_aligned_peer_harvest_summary: ManifestExtractor,
    extract_carryover_peer_expansion_summary: ManifestExtractor,
    extract_carryover_aligned_peer_proof_summary: ManifestExtractor,
    extract_carryover_peer_promotion_gate_summary: ManifestExtractor,
    extract_default_merge_review_summary: ManifestExtractor,
    extract_default_merge_historical_counterfactual_summary: ManifestExtractor,
    extract_continuation_merge_candidate_ranking_summary: ManifestExtractor,
    extract_default_merge_strict_counterfactual_summary: ManifestExtractor,
    extract_merge_replay_validation_summary: ManifestExtractor,
    extract_prepared_breakout_relief_validation_summary: ManifestExtractor,
    extract_prepared_breakout_cohort_summary: ManifestExtractor,
    extract_prepared_breakout_residual_surface_summary: ManifestExtractor,
    extract_candidate_pool_corridor_persistence_dossier_summary: ManifestExtractor,
    extract_candidate_pool_corridor_window_command_board_summary: ManifestExtractor,
    extract_candidate_pool_corridor_window_diagnostics_summary: ManifestExtractor,
    extract_candidate_pool_corridor_narrow_probe_summary: ManifestExtractor,
) -> dict[str, Any]:
    return {
        "synthesis": safe_load_json(dict(manifest.get("btst_governance_synthesis_refresh") or {}).get("output_json")),
        "validation": safe_load_json(dict(manifest.get("btst_governance_validation_refresh") or {}).get("output_json")),
        "independent_window_monitor": safe_load_json(dict(manifest.get("btst_independent_window_monitor_refresh") or {}).get("output_json")),
        "tplus1_tplus2_objective_monitor": safe_load_json(dict(manifest.get("btst_tplus1_tplus2_objective_monitor_refresh") or {}).get("output_json")),
        "tradeable_opportunity_pool": extract_tradeable_opportunity_pool_summary(manifest),
        "no_candidate_entry_action_board": extract_no_candidate_entry_action_board_summary(manifest),
        "no_candidate_entry_replay_bundle": extract_no_candidate_entry_replay_bundle_summary(manifest),
        "no_candidate_entry_failure_dossier": extract_no_candidate_entry_failure_dossier_summary(manifest),
        "watchlist_recall_dossier": extract_watchlist_recall_dossier_summary(manifest),
        "candidate_pool_recall_dossier": extract_candidate_pool_recall_dossier_summary(manifest),
        "selected_outcome_refresh_summary": extract_selected_outcome_refresh_summary(manifest),
        "carryover_multiday_continuation_audit_summary": extract_carryover_multiday_continuation_audit_summary(manifest),
        "carryover_aligned_peer_harvest_summary": extract_carryover_aligned_peer_harvest_summary(manifest),
        "carryover_peer_expansion_summary": extract_carryover_peer_expansion_summary(manifest),
        "carryover_aligned_peer_proof_summary": extract_carryover_aligned_peer_proof_summary(manifest),
        "carryover_peer_promotion_gate_summary": extract_carryover_peer_promotion_gate_summary(manifest),
        "default_merge_review_summary": extract_default_merge_review_summary(manifest),
        "default_merge_historical_counterfactual_summary": extract_default_merge_historical_counterfactual_summary(manifest),
        "continuation_merge_candidate_ranking_summary": extract_continuation_merge_candidate_ranking_summary(manifest),
        "default_merge_strict_counterfactual_summary": extract_default_merge_strict_counterfactual_summary(manifest),
        "merge_replay_validation_summary": extract_merge_replay_validation_summary(manifest),
        "prepared_breakout_relief_validation_summary": extract_prepared_breakout_relief_validation_summary(manifest),
        "prepared_breakout_cohort_summary": extract_prepared_breakout_cohort_summary(manifest),
        "prepared_breakout_residual_surface_summary": extract_prepared_breakout_residual_surface_summary(manifest),
        "candidate_pool_corridor_persistence_dossier_summary": extract_candidate_pool_corridor_persistence_dossier_summary(manifest),
        "candidate_pool_corridor_window_command_board_summary": extract_candidate_pool_corridor_window_command_board_summary(manifest),
        "candidate_pool_corridor_window_diagnostics_summary": extract_candidate_pool_corridor_window_diagnostics_summary(manifest),
        "candidate_pool_corridor_narrow_probe_summary": extract_candidate_pool_corridor_narrow_probe_summary(manifest),
    }


def extract_upstream_shadow_overlay_inputs(snapshot_sections: dict[str, Any]) -> dict[str, list[Any]]:
    no_candidate_entry_action_board = snapshot_sections["no_candidate_entry_action_board"]
    no_candidate_entry_failure_dossier = snapshot_sections["no_candidate_entry_failure_dossier"]
    watchlist_recall_dossier = snapshot_sections["watchlist_recall_dossier"]
    candidate_pool_recall_dossier = snapshot_sections["candidate_pool_recall_dossier"]
    return {
        "no_candidate_entry_priority_tickers": list(no_candidate_entry_action_board.get("top_priority_tickers") or []),
        "absent_from_watchlist_tickers": list(no_candidate_entry_failure_dossier.get("top_absent_from_watchlist_tickers") or []),
        "watchlist_absent_from_candidate_pool_tickers": list(watchlist_recall_dossier.get("top_absent_from_candidate_pool_tickers") or []),
        "upstream_handoff_focus_tickers": list(dict(candidate_pool_recall_dossier.get("upstream_handoff_board_summary") or {}).get("focus_tickers") or []),
    }
