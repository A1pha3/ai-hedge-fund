from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


EntryById = Callable[[dict[str, Any], str], dict[str, Any]]
BuildNightlyRefreshStatus = Callable[[dict[str, Any]], dict[str, Any]]
TimestampFactory = Callable[[], str]

READING_ORDER_ENTRY_IDS: tuple[str, ...] = (
    "btst_governance_synthesis_latest",
    "btst_tplus1_tplus2_objective_monitor_latest",
    "btst_independent_window_monitor_latest",
    "btst_default_merge_review_latest",
    "btst_default_merge_historical_counterfactual_latest",
    "btst_continuation_merge_candidate_ranking_latest",
    "btst_default_merge_strict_counterfactual_latest",
    "btst_merge_replay_validation_latest",
    "btst_prepared_breakout_relief_validation_latest",
    "btst_prepared_breakout_cohort_latest",
    "btst_prepared_breakout_residual_surface_latest",
    "btst_candidate_pool_corridor_persistence_dossier_latest",
    "btst_candidate_pool_corridor_window_command_board_latest",
    "btst_candidate_pool_corridor_window_diagnostics_latest",
    "btst_candidate_pool_corridor_narrow_probe_latest",
    "btst_tradeable_opportunity_pool_march",
    "btst_no_candidate_entry_action_board_latest",
    "btst_no_candidate_entry_replay_bundle_latest",
    "btst_no_candidate_entry_failure_dossier_latest",
    "btst_watchlist_recall_dossier_latest",
    "btst_candidate_pool_recall_dossier_latest",
    "btst_tradeable_opportunity_reason_waterfall_march",
    "latest_btst_priority_board",
    "latest_btst_catalyst_theme_frontier_markdown",
    "btst_score_fail_frontier_latest",
    "btst_score_fail_recurring_frontier_latest",
    "btst_governance_validation_latest",
    "btst_replay_cohort_latest",
)

REPORT_ROOT_SOURCE_FILES: tuple[tuple[str, str], ...] = (
    ("report_manifest_json", "report_manifest_latest.json"),
    ("report_manifest_markdown", "report_manifest_latest.md"),
    ("selected_outcome_refresh_markdown", "btst_selected_outcome_refresh_board_latest.md"),
    ("carryover_multiday_continuation_audit_markdown", "btst_carryover_multiday_continuation_audit_latest.md"),
    ("carryover_aligned_peer_harvest_markdown", "btst_carryover_aligned_peer_harvest_latest.md"),
    ("carryover_peer_expansion_markdown", "btst_carryover_peer_expansion_latest.md"),
)

MANIFEST_SOURCE_PATHS: tuple[tuple[str, str], ...] = (
    ("governance_synthesis_markdown", "btst_governance_synthesis_latest"),
    ("governance_validation_markdown", "btst_governance_validation_latest"),
    ("default_merge_review_markdown", "btst_default_merge_review_latest"),
    ("default_merge_historical_counterfactual_markdown", "btst_default_merge_historical_counterfactual_latest"),
    ("continuation_merge_candidate_ranking_markdown", "btst_continuation_merge_candidate_ranking_latest"),
    ("default_merge_strict_counterfactual_markdown", "btst_default_merge_strict_counterfactual_latest"),
    ("merge_replay_validation_markdown", "btst_merge_replay_validation_latest"),
    ("prepared_breakout_relief_validation_markdown", "btst_prepared_breakout_relief_validation_latest"),
    ("prepared_breakout_cohort_markdown", "btst_prepared_breakout_cohort_latest"),
    ("prepared_breakout_residual_surface_markdown", "btst_prepared_breakout_residual_surface_latest"),
    ("candidate_pool_corridor_persistence_dossier_markdown", "btst_candidate_pool_corridor_persistence_dossier_latest"),
    ("candidate_pool_corridor_window_command_board_markdown", "btst_candidate_pool_corridor_window_command_board_latest"),
    ("candidate_pool_corridor_window_diagnostics_markdown", "btst_candidate_pool_corridor_window_diagnostics_latest"),
    ("candidate_pool_corridor_narrow_probe_markdown", "btst_candidate_pool_corridor_narrow_probe_latest"),
    ("tradeable_opportunity_pool_markdown", "btst_tradeable_opportunity_pool_march"),
    ("no_candidate_entry_action_board_markdown", "btst_no_candidate_entry_action_board_latest"),
    ("no_candidate_entry_replay_bundle_markdown", "btst_no_candidate_entry_replay_bundle_latest"),
    ("no_candidate_entry_failure_dossier_markdown", "btst_no_candidate_entry_failure_dossier_latest"),
    ("watchlist_recall_dossier_markdown", "btst_watchlist_recall_dossier_latest"),
    ("candidate_pool_recall_dossier_markdown", "btst_candidate_pool_recall_dossier_latest"),
    ("tradeable_opportunity_waterfall_markdown", "btst_tradeable_opportunity_reason_waterfall_march"),
    ("replay_cohort_markdown", "btst_replay_cohort_latest"),
    ("independent_window_monitor_markdown", "btst_independent_window_monitor_latest"),
    ("tplus1_tplus2_objective_monitor_markdown", "btst_tplus1_tplus2_objective_monitor_latest"),
)

LATEST_BTST_SOURCE_PATHS: tuple[tuple[str, str], ...] = (
    ("priority_board_markdown", "priority_board_markdown_path"),
    ("brief_markdown", "brief_markdown_path"),
    ("execution_card_markdown", "execution_card_markdown_path"),
    ("opening_watch_card_markdown", "opening_watch_card_markdown_path"),
    ("catalyst_theme_frontier_markdown", "catalyst_theme_frontier_markdown_path"),
    ("score_fail_frontier_markdown", "score_fail_frontier_markdown_path"),
    ("score_fail_recurring_markdown", "score_fail_recurring_markdown_path"),
    ("score_fail_transition_markdown", "score_fail_transition_markdown_path"),
)


def build_nightly_recommended_reading_order(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
) -> list[dict[str, Any]]:
    recommended_reading_order: list[dict[str, Any]] = []
    for entry_id in READING_ORDER_ENTRY_IDS:
        entry = entry_by_id(manifest, entry_id)
        if not entry:
            continue
        recommended_reading_order.append(
            {
                "entry_id": entry.get("id"),
                "report_path": entry.get("report_path"),
                "question": entry.get("question"),
            }
        )
    return recommended_reading_order


def _build_report_root_source_paths(reports_root: Path) -> dict[str, str]:
    return {
        key: str((reports_root / filename).expanduser().resolve())
        for key, filename in REPORT_ROOT_SOURCE_FILES
    }


def _build_manifest_source_paths(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
) -> dict[str, Any]:
    return {
        key: entry_by_id(manifest, entry_id).get("absolute_path")
        for key, entry_id in MANIFEST_SOURCE_PATHS
    }


def _build_latest_btst_source_paths(latest_btst_snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: latest_btst_snapshot.get(snapshot_key)
        for key, snapshot_key in LATEST_BTST_SOURCE_PATHS
    }


def build_nightly_source_paths(
    manifest: dict[str, Any],
    latest_btst_snapshot: dict[str, Any],
    *,
    entry_by_id: EntryById,
    reports_dir: Path,
) -> dict[str, Any]:
    reports_root = Path(manifest.get("reports_root") or reports_dir)
    source_paths = _build_report_root_source_paths(reports_root)
    source_paths.update(_build_manifest_source_paths(manifest, entry_by_id=entry_by_id))
    source_paths.update(_build_latest_btst_source_paths(latest_btst_snapshot))
    return source_paths


def build_nightly_control_tower_analysis(
    manifest: dict[str, Any],
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    effective_brief_recommendation: Any,
    recommended_reading_order: list[dict[str, Any]],
    source_paths: dict[str, Any],
    *,
    build_nightly_refresh_status: BuildNightlyRefreshStatus,
    timestamp_factory: TimestampFactory,
) -> dict[str, Any]:
    priority_board = dict(latest_btst_snapshot.get("priority_board") or {})
    return {
        "generated_at": timestamp_factory(),
        "reports_root": manifest.get("reports_root"),
        "latest_btst_run": manifest.get("latest_btst_run"),
        "refresh_status": build_nightly_refresh_status(manifest),
        "control_tower_snapshot": control_tower_snapshot,
        "merge_replay_validation_summary": dict(control_tower_snapshot.get("merge_replay_validation_summary") or {}),
        "prepared_breakout_relief_validation_summary": dict(control_tower_snapshot.get("prepared_breakout_relief_validation_summary") or {}),
        "prepared_breakout_cohort_summary": dict(control_tower_snapshot.get("prepared_breakout_cohort_summary") or {}),
        "prepared_breakout_residual_surface_summary": dict(control_tower_snapshot.get("prepared_breakout_residual_surface_summary") or {}),
        "candidate_pool_corridor_persistence_dossier_summary": dict(control_tower_snapshot.get("candidate_pool_corridor_persistence_dossier_summary") or {}),
        "candidate_pool_corridor_window_command_board_summary": dict(control_tower_snapshot.get("candidate_pool_corridor_window_command_board_summary") or {}),
        "candidate_pool_corridor_window_diagnostics_summary": dict(control_tower_snapshot.get("candidate_pool_corridor_window_diagnostics_summary") or {}),
        "candidate_pool_corridor_narrow_probe_summary": dict(control_tower_snapshot.get("candidate_pool_corridor_narrow_probe_summary") or {}),
        "selected_outcome_refresh_summary": dict(control_tower_snapshot.get("selected_outcome_refresh_summary") or {}),
        "carryover_multiday_continuation_audit_summary": dict(control_tower_snapshot.get("carryover_multiday_continuation_audit_summary") or {}),
        "carryover_aligned_peer_harvest_summary": dict(control_tower_snapshot.get("carryover_aligned_peer_harvest_summary") or {}),
        "carryover_peer_expansion_summary": dict(control_tower_snapshot.get("carryover_peer_expansion_summary") or {}),
        "carryover_aligned_peer_proof_summary": dict(control_tower_snapshot.get("carryover_aligned_peer_proof_summary") or {}),
        "carryover_peer_promotion_gate_summary": dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {}),
        "latest_priority_board_snapshot": {
            "headline": priority_board.get("headline"),
            "summary": priority_board.get("summary"),
            "priority_rows": list(priority_board.get("priority_rows") or [])[:3],
            "global_guardrails": list(priority_board.get("global_guardrails") or []),
            "brief_recommendation": effective_brief_recommendation,
        },
        "replay_cohort_snapshot": replay_cohort_snapshot,
        "latest_btst_snapshot": latest_btst_snapshot,
        "recommended_reading_order": recommended_reading_order,
        "source_paths": source_paths,
    }
