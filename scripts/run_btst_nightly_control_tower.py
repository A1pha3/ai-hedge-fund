from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from scripts.analyze_btst_latest_close_validation import generate_btst_latest_close_validation_artifacts
from scripts.btst_selected_focus import pick_selected_focus_entry
from scripts.btst_latest_followup_utils import load_latest_upstream_shadow_followup_summary
from scripts.btst_nightly_dossier_markdown_helpers import (
    append_candidate_pool_recall_corridor_details_markdown as _append_candidate_pool_recall_corridor_details_markdown_impl,
    append_candidate_pool_recall_dossier_markdown as _append_candidate_pool_recall_dossier_markdown_impl,
    append_candidate_pool_recall_followup_details_markdown as _append_candidate_pool_recall_followup_details_markdown_impl,
    append_candidate_pool_recall_priority_details_markdown as _append_candidate_pool_recall_priority_details_markdown_impl,
    append_no_candidate_entry_action_board_markdown as _append_no_candidate_entry_action_board_markdown_impl,
    append_no_candidate_entry_failure_dossier_markdown as _append_no_candidate_entry_failure_dossier_markdown_impl,
    append_no_candidate_entry_replay_bundle_markdown as _append_no_candidate_entry_replay_bundle_markdown_impl,
    append_tradeable_opportunity_pool_markdown as _append_tradeable_opportunity_pool_markdown_impl,
    append_watchlist_recall_dossier_markdown as _append_watchlist_recall_dossier_markdown_impl,
)
from scripts.btst_nightly_artifact_helpers import (
    generate_btst_nightly_control_tower_artifacts as _generate_btst_nightly_control_tower_artifacts_impl,
    resolve_nightly_control_tower_output_paths as _resolve_nightly_control_tower_output_paths_impl,
)
from scripts.btst_control_tower_snapshot_helpers import extract_control_tower_snapshot as _extract_control_tower_snapshot_impl
from scripts.btst_carryover_summary_helpers import (
    extract_carryover_aligned_peer_harvest_summary as _extract_carryover_aligned_peer_harvest_summary_impl,
    extract_carryover_aligned_peer_proof_summary as _extract_carryover_aligned_peer_proof_summary_impl,
    extract_carryover_multiday_continuation_audit_summary as _extract_carryover_multiday_continuation_audit_summary_impl,
    extract_carryover_peer_expansion_summary as _extract_carryover_peer_expansion_summary_impl,
    extract_carryover_peer_promotion_gate_summary as _extract_carryover_peer_promotion_gate_summary_impl,
    extract_selected_outcome_refresh_summary as _extract_selected_outcome_refresh_summary_impl,
    find_focus_entry as _find_focus_entry_impl,
)
from scripts.btst_latest_snapshot_helpers import (
    extract_catalyst_theme_frontier_summary as _extract_catalyst_theme_frontier_summary_impl,
    extract_latest_btst_snapshot as _extract_latest_btst_snapshot_impl,
    extract_score_fail_frontier_summary as _extract_score_fail_frontier_summary_impl,
    extract_tradeable_opportunity_pool_summary as _extract_tradeable_opportunity_pool_summary_impl,
)
from scripts.btst_dossier_summary_helpers import (
    extract_candidate_pool_recall_dossier_summary as _extract_candidate_pool_recall_dossier_summary_impl,
    extract_no_candidate_entry_action_board_summary as _extract_no_candidate_entry_action_board_summary_impl,
    extract_no_candidate_entry_failure_dossier_summary as _extract_no_candidate_entry_failure_dossier_summary_impl,
    extract_no_candidate_entry_replay_bundle_summary as _extract_no_candidate_entry_replay_bundle_summary_impl,
    extract_watchlist_recall_dossier_summary as _extract_watchlist_recall_dossier_summary_impl,
)
from scripts.btst_remaining_summary_helpers import (
    extract_candidate_pool_corridor_narrow_probe_summary as _extract_candidate_pool_corridor_narrow_probe_summary_impl,
    extract_candidate_pool_corridor_persistence_dossier_summary as _extract_candidate_pool_corridor_persistence_dossier_summary_impl,
    extract_candidate_pool_corridor_window_command_board_summary as _extract_candidate_pool_corridor_window_command_board_summary_impl,
    extract_candidate_pool_corridor_window_diagnostics_summary as _extract_candidate_pool_corridor_window_diagnostics_summary_impl,
    extract_continuation_merge_candidate_ranking_summary as _extract_continuation_merge_candidate_ranking_summary_impl,
    extract_default_merge_historical_counterfactual_summary as _extract_default_merge_historical_counterfactual_summary_impl,
    extract_default_merge_review_summary as _extract_default_merge_review_summary_impl,
    extract_default_merge_strict_counterfactual_summary as _extract_default_merge_strict_counterfactual_summary_impl,
    extract_merge_replay_validation_summary as _extract_merge_replay_validation_summary_impl,
    extract_prepared_breakout_cohort_summary as _extract_prepared_breakout_cohort_summary_impl,
    extract_prepared_breakout_relief_validation_summary as _extract_prepared_breakout_relief_validation_summary_impl,
    extract_prepared_breakout_residual_surface_summary as _extract_prepared_breakout_residual_surface_summary_impl,
)
from scripts.btst_control_tower_task_helpers import (
    build_candidate_pool_corridor_primary_shadow_task as _build_candidate_pool_corridor_primary_shadow_task_impl,
    build_lane_priority_task as _build_lane_priority_task_impl,
    build_recall_priority_task as _build_recall_priority_task_impl,
    collect_control_tower_priority_candidates as _collect_control_tower_priority_candidates_impl,
    prioritize_control_tower_next_actions as _prioritize_control_tower_next_actions_impl,
)
from scripts.btst_nightly_payload_helpers import (
    build_nightly_control_tower_analysis as _build_nightly_control_tower_analysis_impl,
    build_nightly_recommended_reading_order as _build_nightly_recommended_reading_order_impl,
    build_nightly_source_paths as _build_nightly_source_paths_impl,
)
from scripts.btst_open_ready_delta_payload_helpers import (
    build_btst_open_ready_delta_payload as _build_btst_open_ready_delta_payload_impl,
    build_open_ready_delta_analysis as _build_open_ready_delta_analysis_impl,
    build_open_ready_delta_context as _build_open_ready_delta_context_impl,
    build_open_ready_source_paths as _build_open_ready_source_paths_impl,
)
from scripts.btst_history_selection_helpers import (
    extract_btst_report_candidate as _extract_btst_report_candidate_impl,
    select_previous_btst_report_snapshot as _select_previous_btst_report_snapshot_impl,
)
from scripts.btst_open_ready_context_helpers import (
    build_material_change_anchor as _build_material_change_anchor_impl,
    resolve_open_ready_comparison_scope as _resolve_open_ready_comparison_scope_impl,
    resolve_open_ready_previous_context as _resolve_open_ready_previous_context_impl,
)
from scripts.btst_carryover_contract_helpers import (
    build_carryover_contract_next_steps as _build_carryover_contract_next_steps_impl,
    build_carryover_contract_why_now_parts as _build_carryover_contract_why_now_parts_impl,
    build_labeled_why_now_segments as _build_labeled_why_now_segments_impl,
    describe_selected_contract_style as _describe_selected_contract_style_impl,
    extract_carryover_contract_context as _extract_carryover_contract_context_impl,
    prioritize_ticker_in_list as _prioritize_ticker_in_list_impl,
)
from scripts.btst_open_ready_focus_helpers import (
    append_open_ready_action_focus as _append_open_ready_action_focus_impl,
    append_open_ready_basis_focus as _append_open_ready_basis_focus_impl,
    append_open_ready_frontier_focus as _append_open_ready_frontier_focus_impl,
    append_open_ready_governance_focus as _append_open_ready_governance_focus_impl,
    append_open_ready_material_anchor_focus as _append_open_ready_material_anchor_focus_impl,
    append_open_ready_priority_focus as _append_open_ready_priority_focus_impl,
    append_open_ready_replay_focus as _append_open_ready_replay_focus_impl,
    append_open_ready_score_fail_focus as _append_open_ready_score_fail_focus_impl,
    append_open_ready_stability_focus as _append_open_ready_stability_focus_impl,
    build_open_ready_material_change_anchor as _build_open_ready_material_change_anchor_impl,
    build_open_ready_operator_focus as _build_open_ready_operator_focus_impl,
    resolve_open_ready_overall_delta_verdict as _resolve_open_ready_overall_delta_verdict_impl,
    should_build_open_ready_material_anchor as _should_build_open_ready_material_anchor_impl,
)
from scripts.btst_snapshot_section_helpers import (
    extract_control_tower_snapshot_sections as _extract_control_tower_snapshot_sections_impl,
    extract_upstream_shadow_overlay_inputs as _extract_upstream_shadow_overlay_inputs_impl,
)
from scripts.btst_upstream_shadow_overlay_helpers import (
    build_upstream_shadow_followup_overlay as _build_upstream_shadow_followup_overlay_impl,
    ordered_without as _ordered_without_impl,
)
from scripts.btst_open_ready_diff_helpers import (
    build_carryover_promotion_gate_field_changes as _build_carryover_promotion_gate_field_changes_impl,
    build_catalyst_frontier_count_deltas as _build_catalyst_frontier_count_deltas_impl,
    build_governance_aggregate_deltas as _build_governance_aggregate_deltas_impl,
    build_governance_lane_delta as _build_governance_lane_delta_impl,
    build_governance_lane_map as _build_governance_lane_map_impl,
    build_priority_rows_by_ticker as _build_priority_rows_by_ticker_impl,
    build_priority_summary_delta as _build_priority_summary_delta_impl,
    build_rank_map as _build_rank_map_impl,
    build_score_fail_frontier_count_deltas as _build_score_fail_frontier_count_deltas_impl,
    collect_governance_lane_changes as _collect_governance_lane_changes_impl,
    collect_priority_board_membership_changes as _collect_priority_board_membership_changes_impl,
    collect_priority_board_per_ticker_changes as _collect_priority_board_per_ticker_changes_impl,
    diff_carryover_peer_proof as _diff_carryover_peer_proof_impl,
    diff_carryover_promotion_gate as _diff_carryover_promotion_gate_impl,
    diff_catalyst_frontier as _diff_catalyst_frontier_impl,
    diff_governance as _diff_governance_impl,
    diff_priority_board as _diff_priority_board_impl,
    diff_replay as _diff_replay_impl,
    diff_score_fail_frontier as _diff_score_fail_frontier_impl,
    diff_selected_outcome_contract as _diff_selected_outcome_contract_impl,
    diff_ticker_lists as _diff_ticker_lists_impl,
    diff_top_priority_action as _diff_top_priority_action_impl,
    extract_score_fail_frontier_summaries as _extract_score_fail_frontier_summaries_impl,
    has_governance_lane_delta_changes as _has_governance_lane_delta_changes_impl,
    resolve_catalyst_frontier_previous_summary as _resolve_catalyst_frontier_previous_summary_impl,
)
from scripts.btst_nightly_markdown_core_helpers import (
    append_control_tower_snapshot_markdown as _append_control_tower_snapshot_markdown_impl,
    append_independent_window_monitor_markdown as _append_independent_window_monitor_markdown_impl,
    append_latest_upstream_shadow_followup_overlay_markdown as _append_latest_upstream_shadow_followup_overlay_markdown_impl,
    append_nightly_overview_markdown as _append_nightly_overview_markdown_impl,
    append_nightly_summary_markdown as _append_nightly_summary_markdown_impl,
    append_rollout_lanes_markdown as _append_rollout_lanes_markdown_impl,
    append_tplus1_tplus2_objective_monitor_markdown as _append_tplus1_tplus2_objective_monitor_markdown_impl,
    build_control_tower_snapshot_header_lines as _build_control_tower_snapshot_header_lines_impl,
    build_nightly_overview_header_lines as _build_nightly_overview_header_lines_impl,
    build_nightly_summary_header_lines as _build_nightly_summary_header_lines_impl,
)
from scripts.btst_nightly_markdown_tail_helpers import (
    append_catalyst_theme_frontier_markdown as _append_catalyst_theme_frontier_markdown_impl,
    append_nightly_overview_candidate_pool_continuation_markdown as _append_nightly_overview_candidate_pool_continuation_markdown_impl,
    append_nightly_overview_candidate_pool_followup_markdown as _append_nightly_overview_candidate_pool_followup_markdown_impl,
    append_nightly_overview_candidate_pool_followup_tail_markdown as _append_nightly_overview_candidate_pool_followup_tail_markdown_impl,
    append_nightly_fast_links_markdown as _append_nightly_fast_links_markdown_impl,
    append_nightly_llm_health_markdown as _append_nightly_llm_health_markdown_impl,
    append_nightly_reading_order_markdown as _append_nightly_reading_order_markdown_impl,
    append_priority_board_snapshot_markdown as _append_priority_board_snapshot_markdown_impl,
    append_replay_cohort_snapshot_markdown as _append_replay_cohort_snapshot_markdown_impl,
    append_score_fail_frontier_queue_markdown as _append_score_fail_frontier_queue_markdown_impl,
)
from scripts.btst_nightly_render_helpers import (
    build_nightly_control_tower_render_context as _build_nightly_control_tower_render_context_impl,
    render_btst_nightly_control_tower_markdown as _render_btst_nightly_control_tower_markdown_impl,
)
from scripts.btst_open_ready_delta_markdown_helpers import (
    append_carryover_peer_proof_delta_markdown as _append_carryover_peer_proof_delta_markdown_impl,
    append_carryover_promotion_gate_delta_markdown as _append_carryover_promotion_gate_delta_markdown_impl,
    append_catalyst_frontier_delta_markdown as _append_catalyst_frontier_delta_markdown_impl,
    append_catalyst_frontier_delta_summary as _append_catalyst_frontier_delta_summary_impl,
    append_catalyst_frontier_delta_tickers as _append_catalyst_frontier_delta_tickers_impl,
    append_governance_delta_markdown as _append_governance_delta_markdown_impl,
    append_material_change_anchor_focus_markdown as _append_material_change_anchor_focus_markdown_impl,
    append_material_change_anchor_markdown as _append_material_change_anchor_markdown_impl,
    append_material_change_anchor_metadata as _append_material_change_anchor_metadata_impl,
    append_open_ready_fast_links_markdown as _append_open_ready_fast_links_markdown_impl,
    append_open_ready_operator_focus_markdown as _append_open_ready_operator_focus_markdown_impl,
    append_open_ready_overview_fields as _append_open_ready_overview_fields_impl,
    append_open_ready_overview_markdown as _append_open_ready_overview_markdown_impl,
    append_priority_change_markdown as _append_priority_change_markdown_impl,
    append_priority_delta_list as _append_priority_delta_list_impl,
    append_priority_delta_markdown as _append_priority_delta_markdown_impl,
    append_priority_guardrail_markdown as _append_priority_guardrail_markdown_impl,
    append_priority_membership_markdown as _append_priority_membership_markdown_impl,
    append_replay_delta_markdown as _append_replay_delta_markdown_impl,
    append_score_fail_frontier_delta_markdown as _append_score_fail_frontier_delta_markdown_impl,
    append_score_fail_frontier_delta_summary as _append_score_fail_frontier_delta_summary_impl,
    append_score_fail_frontier_delta_tickers as _append_score_fail_frontier_delta_tickers_impl,
    append_selected_outcome_contract_delta_markdown as _append_selected_outcome_contract_delta_markdown_impl,
    append_top_priority_action_delta_markdown as _append_top_priority_action_delta_markdown_impl,
    build_governance_lane_delta_markdown as _build_governance_lane_delta_markdown_impl,
    collect_governance_lane_extra_segments as _collect_governance_lane_extra_segments_impl,
    render_btst_open_ready_delta_markdown as _render_btst_open_ready_delta_markdown_impl,
)
from scripts.btst_report_utils import load_json as _load_json, looks_like_report_dir as _looks_like_report_dir, normalize_trade_date as _normalize_trade_date, safe_load_json as _safe_load_json
from scripts.generate_reports_manifest import generate_reports_manifest_artifacts


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_nightly_control_tower_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_nightly_control_tower_latest.md"
DEFAULT_DELTA_JSON = REPORTS_DIR / "btst_open_ready_delta_latest.json"
DEFAULT_DELTA_MD = REPORTS_DIR / "btst_open_ready_delta_latest.md"
DEFAULT_CLOSE_VALIDATION_JSON = REPORTS_DIR / "btst_latest_close_validation_latest.json"
DEFAULT_CLOSE_VALIDATION_MD = REPORTS_DIR / "btst_latest_close_validation_latest.md"
DEFAULT_HISTORY_DIR = REPORTS_DIR / "archive" / "btst_nightly_control_tower_history"


def _slugify(value: Any) -> str:
    raw = str(value or "")
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)
    compact = "_".join(part for part in normalized.split("_") if part)
    return compact or "snapshot"


def _as_float(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return float(value)


def _extract_priority_summary(block: dict[str, Any]) -> dict[str, int]:
    summary = dict(block.get("summary") or {})
    if summary:
        return {
            "primary_count": int(summary.get("primary_count") or 0),
            "near_miss_count": int(summary.get("near_miss_count") or 0),
            "opportunity_pool_count": int(summary.get("opportunity_pool_count") or 0),
            "research_upside_radar_count": int(summary.get("research_upside_radar_count") or 0),
            "catalyst_theme_count": int(summary.get("catalyst_theme_count") or 0),
            "catalyst_theme_shadow_count": int(summary.get("catalyst_theme_shadow_count") or 0),
        }
    return {
        "primary_count": int(block.get("selected_count") or block.get("short_trade_selected_count") or 0),
        "near_miss_count": int(block.get("near_miss_count") or block.get("short_trade_near_miss_count") or 0),
        "opportunity_pool_count": int(block.get("opportunity_pool_count") or block.get("short_trade_opportunity_pool_count") or 0),
        "research_upside_radar_count": int(block.get("research_upside_radar_count") or block.get("short_trade_research_upside_radar_count") or 0),
        "catalyst_theme_count": int(block.get("catalyst_theme_count") or block.get("short_trade_catalyst_theme_count") or 0),
        "catalyst_theme_shadow_count": int(block.get("catalyst_theme_shadow_count") or block.get("short_trade_catalyst_theme_shadow_count") or 0),
    }


def _extract_btst_report_candidate(report_dir: Path) -> dict[str, Any] | None:
    return _extract_btst_report_candidate_impl(
        report_dir,
        looks_like_report_dir=_looks_like_report_dir,
        safe_load_json=_safe_load_json,
        normalize_trade_date=_normalize_trade_date,
    )


def _select_previous_btst_report_snapshot(
    reports_root: str | Path,
    *,
    current_report_dir: str | None,
    selection_target: str | None,
) -> dict[str, Any]:
    return _select_previous_btst_report_snapshot_impl(
        reports_root,
        current_report_dir=current_report_dir,
        selection_target=selection_target,
        extract_btst_report_candidate=_extract_btst_report_candidate,
        safe_load_json=_safe_load_json,
        extract_catalyst_theme_frontier_summary=_extract_catalyst_theme_frontier_summary,
    )


def _load_latest_archived_nightly_payload(history_dir: str | Path) -> tuple[dict[str, Any], str | None]:
    archived_payloads = _load_archived_nightly_payloads(history_dir, limit=1)
    if archived_payloads:
        return archived_payloads[0]
    return {}, None


def _load_archived_nightly_payloads(history_dir: str | Path, *, limit: int | None = None) -> list[tuple[dict[str, Any], str | None]]:
    resolved_history_dir = Path(history_dir).expanduser().resolve()
    if not resolved_history_dir.exists():
        return []

    archived_paths = sorted(
        [path for path in resolved_history_dir.glob("btst_nightly_control_tower_*.json") if path.is_file()],
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    if limit is not None:
        archived_paths = archived_paths[:limit]

    archived_payloads: list[tuple[dict[str, Any], str | None]] = []
    for path in archived_paths:
        try:
            archived_payloads.append((_load_json(path), str(path.resolve())))
        except json.JSONDecodeError:
            continue
    return archived_payloads


def _archive_nightly_payload(payload: dict[str, Any], history_dir: str | Path) -> str:
    resolved_history_dir = Path(history_dir).expanduser().resolve()
    resolved_history_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _slugify(str(payload.get("generated_at") or "unknown").replace(":", "").replace(".", "_"))
    report_slug = _slugify(dict(payload.get("latest_btst_run") or {}).get("report_dir") or "unknown_report")
    output_path = resolved_history_dir / f"btst_nightly_control_tower_{generated_at}_{report_slug}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path.as_posix()


def _relative_link(target: str | Path | None, output_parent: Path) -> str | None:
    if not target:
        return None
    resolved = Path(target).expanduser().resolve()
    if not resolved.exists():
        return None
    return Path(os.path.relpath(resolved, output_parent)).as_posix()


def _entry_by_id(manifest: dict[str, Any], entry_id: str) -> dict[str, Any]:
    return next((dict(entry or {}) for entry in list(manifest.get("entries") or []) if entry.get("id") == entry_id), {})


def _ordered_without(values: list[Any] | None, excluded: set[str]) -> list[str]:
    return _ordered_without_impl(values, excluded)


def _build_upstream_shadow_followup_overlay(
    reports_root: str | Path,
    *,
    no_candidate_entry_priority_tickers: list[Any] | None = None,
    absent_from_watchlist_tickers: list[Any] | None = None,
    watchlist_absent_from_candidate_pool_tickers: list[Any] | None = None,
    upstream_handoff_focus_tickers: list[Any] | None = None,
) -> dict[str, Any]:
    return _build_upstream_shadow_followup_overlay_impl(
        reports_root,
        no_candidate_entry_priority_tickers=no_candidate_entry_priority_tickers,
        absent_from_watchlist_tickers=absent_from_watchlist_tickers,
        watchlist_absent_from_candidate_pool_tickers=watchlist_absent_from_candidate_pool_tickers,
        upstream_handoff_focus_tickers=upstream_handoff_focus_tickers,
        load_latest_upstream_shadow_followup_summary=load_latest_upstream_shadow_followup_summary,
    )


def _extract_catalyst_theme_frontier_summary(frontier: dict[str, Any]) -> dict[str, Any]:
    return _extract_catalyst_theme_frontier_summary_impl(frontier)


def _extract_score_fail_frontier_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_score_fail_frontier_summary_impl(manifest, safe_load_json=_safe_load_json)


def _extract_tradeable_opportunity_pool_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_tradeable_opportunity_pool_summary_impl(manifest, safe_load_json=_safe_load_json)


def _extract_no_candidate_entry_action_board_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_no_candidate_entry_action_board_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_no_candidate_entry_replay_bundle_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_no_candidate_entry_replay_bundle_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_no_candidate_entry_failure_dossier_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_no_candidate_entry_failure_dossier_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_watchlist_recall_dossier_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_watchlist_recall_dossier_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_candidate_pool_recall_dossier_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_candidate_pool_recall_dossier_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_latest_btst_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_latest_btst_snapshot_impl(
        manifest,
        safe_load_json=_safe_load_json,
        extract_score_fail_frontier_summary=_extract_score_fail_frontier_summary,
        extract_catalyst_theme_frontier_summary=_extract_catalyst_theme_frontier_summary,
    )


def _extract_default_merge_review_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_default_merge_review_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_selected_outcome_refresh_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_selected_outcome_refresh_summary_impl(
        manifest,
        reports_dir=REPORTS_DIR,
        safe_load_json=_safe_load_json,
        pick_selected_focus_entry=pick_selected_focus_entry,
    )


def _find_focus_entry(entries: list[dict[str, Any]], focus_ticker: Any) -> dict[str, Any]:
    return _find_focus_entry_impl(entries, focus_ticker)


def _extract_carryover_multiday_continuation_audit_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_carryover_multiday_continuation_audit_summary_impl(
        manifest,
        reports_dir=REPORTS_DIR,
        safe_load_json=_safe_load_json,
    )


def _extract_carryover_aligned_peer_harvest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_carryover_aligned_peer_harvest_summary_impl(
        manifest,
        reports_dir=REPORTS_DIR,
        safe_load_json=_safe_load_json,
    )


def _extract_carryover_peer_expansion_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_carryover_peer_expansion_summary_impl(
        manifest,
        reports_dir=REPORTS_DIR,
        safe_load_json=_safe_load_json,
    )


def _extract_carryover_aligned_peer_proof_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_carryover_aligned_peer_proof_summary_impl(
        manifest,
        reports_dir=REPORTS_DIR,
        safe_load_json=_safe_load_json,
    )


def _extract_carryover_peer_promotion_gate_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_carryover_peer_promotion_gate_summary_impl(
        manifest,
        reports_dir=REPORTS_DIR,
        safe_load_json=_safe_load_json,
    )


def _extract_default_merge_historical_counterfactual_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_default_merge_historical_counterfactual_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_continuation_merge_candidate_ranking_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_continuation_merge_candidate_ranking_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_default_merge_strict_counterfactual_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_default_merge_strict_counterfactual_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_merge_replay_validation_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_merge_replay_validation_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_prepared_breakout_relief_validation_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_prepared_breakout_relief_validation_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_prepared_breakout_cohort_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_prepared_breakout_cohort_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_prepared_breakout_residual_surface_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_prepared_breakout_residual_surface_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_candidate_pool_corridor_persistence_dossier_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_candidate_pool_corridor_persistence_dossier_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_candidate_pool_corridor_window_command_board_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_candidate_pool_corridor_window_command_board_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_candidate_pool_corridor_window_diagnostics_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_candidate_pool_corridor_window_diagnostics_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_candidate_pool_corridor_narrow_probe_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_candidate_pool_corridor_narrow_probe_summary_impl(
        manifest,
        entry_by_id=_entry_by_id,
        safe_load_json=_safe_load_json,
    )


def _extract_control_tower_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_control_tower_snapshot_impl(
        manifest,
        extract_snapshot_sections=_extract_control_tower_snapshot_sections,
        extract_overlay_inputs=_extract_upstream_shadow_overlay_inputs,
        build_upstream_shadow_followup_overlay=_build_upstream_shadow_followup_overlay,
        reports_dir=REPORTS_DIR,
    )


def _extract_control_tower_snapshot_sections(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_control_tower_snapshot_sections_impl(
        manifest,
        safe_load_json=_safe_load_json,
        extract_tradeable_opportunity_pool_summary=_extract_tradeable_opportunity_pool_summary,
        extract_no_candidate_entry_action_board_summary=_extract_no_candidate_entry_action_board_summary,
        extract_no_candidate_entry_replay_bundle_summary=_extract_no_candidate_entry_replay_bundle_summary,
        extract_no_candidate_entry_failure_dossier_summary=_extract_no_candidate_entry_failure_dossier_summary,
        extract_watchlist_recall_dossier_summary=_extract_watchlist_recall_dossier_summary,
        extract_candidate_pool_recall_dossier_summary=_extract_candidate_pool_recall_dossier_summary,
        extract_selected_outcome_refresh_summary=_extract_selected_outcome_refresh_summary,
        extract_carryover_multiday_continuation_audit_summary=_extract_carryover_multiday_continuation_audit_summary,
        extract_carryover_aligned_peer_harvest_summary=_extract_carryover_aligned_peer_harvest_summary,
        extract_carryover_peer_expansion_summary=_extract_carryover_peer_expansion_summary,
        extract_carryover_aligned_peer_proof_summary=_extract_carryover_aligned_peer_proof_summary,
        extract_carryover_peer_promotion_gate_summary=_extract_carryover_peer_promotion_gate_summary,
        extract_default_merge_review_summary=_extract_default_merge_review_summary,
        extract_default_merge_historical_counterfactual_summary=_extract_default_merge_historical_counterfactual_summary,
        extract_continuation_merge_candidate_ranking_summary=_extract_continuation_merge_candidate_ranking_summary,
        extract_default_merge_strict_counterfactual_summary=_extract_default_merge_strict_counterfactual_summary,
        extract_merge_replay_validation_summary=_extract_merge_replay_validation_summary,
        extract_prepared_breakout_relief_validation_summary=_extract_prepared_breakout_relief_validation_summary,
        extract_prepared_breakout_cohort_summary=_extract_prepared_breakout_cohort_summary,
        extract_prepared_breakout_residual_surface_summary=_extract_prepared_breakout_residual_surface_summary,
        extract_candidate_pool_corridor_persistence_dossier_summary=_extract_candidate_pool_corridor_persistence_dossier_summary,
        extract_candidate_pool_corridor_window_command_board_summary=_extract_candidate_pool_corridor_window_command_board_summary,
        extract_candidate_pool_corridor_window_diagnostics_summary=_extract_candidate_pool_corridor_window_diagnostics_summary,
        extract_candidate_pool_corridor_narrow_probe_summary=_extract_candidate_pool_corridor_narrow_probe_summary,
    )


def _extract_upstream_shadow_overlay_inputs(snapshot_sections: dict[str, Any]) -> dict[str, list[Any]]:
    return _extract_upstream_shadow_overlay_inputs_impl(snapshot_sections)


def _build_recall_priority_task(
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    return _build_recall_priority_task_impl(
        latest_btst_snapshot,
        control_tower_snapshot,
        extract_priority_summary=_extract_priority_summary,
        resolve_priority_handoff_experiment=_resolve_priority_handoff_experiment,
        build_priority_handoff_experiment_why_now_parts=_build_priority_handoff_experiment_why_now_parts,
        build_priority_handoff_experiment_next_step=_build_priority_handoff_experiment_next_step,
    )


def _resolve_priority_handoff_experiment(
    *,
    candidate_pool_recall_dossier: dict[str, Any],
    focus_tickers: list[str],
) -> dict[str, Any]:
    experiments = [dict(row or {}) for row in list(candidate_pool_recall_dossier.get("priority_handoff_branch_experiment_queue") or [])]
    if not experiments:
        return {}

    focus_set = {str(ticker).strip() for ticker in focus_tickers if str(ticker).strip()}
    ranked: list[tuple[int, int, int, dict[str, Any]]] = []
    for row in experiments:
        tickers = [str(ticker).strip() for ticker in list(row.get("tickers") or []) if str(ticker).strip()]
        overlap_count = len(focus_set.intersection(tickers))
        priority_rank = int(row.get("priority_rank") or 999999)
        ranked.append((overlap_count, -priority_rank, len(tickers), row))
    ranked.sort(reverse=True)
    selected = ranked[0][3]
    return selected if ranked[0][0] > 0 or len(ranked) == 1 else {}


def _build_priority_handoff_experiment_why_now_parts(experiment: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    priority_handoff = str(experiment.get("priority_handoff") or "").strip()
    pressure_cluster_type = str(experiment.get("pressure_cluster_type") or "").strip()
    uplift_to_cutoff_multiple_mean = experiment.get("uplift_to_cutoff_multiple_mean")
    uplift_to_cutoff_multiple_min = experiment.get("uplift_to_cutoff_multiple_min")
    why_now = str(experiment.get("why_now") or "").strip()
    if priority_handoff:
        parts.append(f"priority_handoff={priority_handoff}")
    if pressure_cluster_type:
        parts.append(f"pressure_cluster_type={pressure_cluster_type}")
    if uplift_to_cutoff_multiple_mean is not None:
        parts.append(f"uplift_to_cutoff_multiple_mean={uplift_to_cutoff_multiple_mean}")
    if uplift_to_cutoff_multiple_min is not None:
        parts.append(f"uplift_to_cutoff_multiple_min={uplift_to_cutoff_multiple_min}")
    if why_now:
        parts.append(why_now)
    return parts


def _build_priority_handoff_experiment_next_step(experiment: dict[str, Any]) -> str:
    prototype_type = str(experiment.get("prototype_type") or "").strip()
    prototype_summary = str(experiment.get("prototype_summary") or "").strip()
    success_signal = str(experiment.get("success_signal") or "").strip()
    guardrail_summary = str(experiment.get("guardrail_summary") or "").strip()
    uplift_to_cutoff_multiple_min = experiment.get("uplift_to_cutoff_multiple_min")
    next_step_parts: list[str] = []
    if prototype_type and prototype_summary:
        next_step_parts.append(f"再按 {prototype_type} 执行：{prototype_summary}")
    elif prototype_summary:
        next_step_parts.append(prototype_summary)
    elif prototype_type:
        next_step_parts.append(f"再按 {prototype_type} 执行")
    if uplift_to_cutoff_multiple_min is not None:
        next_step_parts.append(f"当前最轻样本门槛仍需约 {uplift_to_cutoff_multiple_min} 倍成交额抬升，先验证是否存在可复制的 upstream liquidity jump。")
    if success_signal:
        next_step_parts.append(success_signal)
    if guardrail_summary:
        next_step_parts.append(guardrail_summary)
    return "；".join(next_step_parts) or "再按 priority_handoff_branch_experiment_queue 的首条实验执行。"


def _normalize_primary_shadow_replay(primary_shadow_replay_raw: Any) -> dict[str, Any]:
    if isinstance(primary_shadow_replay_raw, dict):
        return dict(primary_shadow_replay_raw)
    if isinstance(primary_shadow_replay_raw, str):
        return {"ticker": primary_shadow_replay_raw}
    if isinstance(primary_shadow_replay_raw, list) and primary_shadow_replay_raw:
        first_replay = primary_shadow_replay_raw[0]
        return dict(first_replay) if isinstance(first_replay, dict) else {"ticker": str(first_replay)}
    return {}


def _collect_control_tower_ticker_set(control_tower_snapshot: dict[str, Any], key: str) -> set[str]:
    return {str(ticker).strip() for ticker in list(control_tower_snapshot.get(key) or []) if str(ticker).strip()}


def _find_candidate_pool_focus_liquidity_profile(control_tower_snapshot: dict[str, Any], focus_ticker: str) -> dict[str, Any]:
    return next(
        (
            dict(row or {})
            for row in list(control_tower_snapshot.get("candidate_pool_recall_focus_liquidity_profiles") or [])
            if str(dict(row or {}).get("ticker") or "").strip() == focus_ticker
        ),
        {},
    )


def _append_primary_shadow_replay_context(why_now_parts: list[str], primary_shadow_replay: dict[str, Any]) -> None:
    for key in (
        "validation_priority_rank",
        "tractability_tier",
        "uplift_to_cutoff_multiple_mean",
        "closed_cycle_count",
        "t_plus_2_positive_rate",
        "t_plus_2_return_hit_rate_at_target",
        "mean_t_plus_2_return",
        "objective_fit_score",
    ):
        value = primary_shadow_replay.get(key)
        if value is not None and str(value).strip() != "":
            why_now_parts.append(f"{key}={value}")


def _append_truncation_context(
    why_now_parts: list[str],
    *,
    candidate_pool_recall_dominant_stage: str,
    focus_liquidity_profile: dict[str, Any],
) -> None:
    if candidate_pool_recall_dominant_stage != "candidate_pool_truncated_after_filters" or not focus_liquidity_profile:
        return

    for key in ("dominant_liquidity_gap_mode", "avg_amount_share_of_cutoff_mean", "min_rank_gap_to_cutoff"):
        value = focus_liquidity_profile.get(key)
        if value is not None and str(value).strip() != "":
            why_now_parts.append(f"{key}={value}")
    for key in ("pressure_peer_cluster_type", "uplift_to_cutoff_multiple_mean"):
        value = focus_liquidity_profile.get(key)
        if value is not None and str(value).strip() != "":
            why_now_parts.append(f"{key}={value}")

    closest_case = dict(focus_liquidity_profile.get("closest_case") or {})
    closest_gap = closest_case.get("pre_truncation_rank_gap_to_cutoff")
    closest_share = closest_case.get("pre_truncation_avg_amount_share_of_cutoff")
    if closest_gap is not None and str(closest_gap).strip() != "":
        why_now_parts.append(f"closest_pre_truncation_rank_gap_to_cutoff={closest_gap}")
    if closest_share is not None and str(closest_share).strip() != "":
        why_now_parts.append(f"closest_pre_truncation_avg_amount_share_of_cutoff={closest_share}")
    frontier_peer_labels = _extract_focus_frontier_peer_labels(focus_liquidity_profile)
    if frontier_peer_labels:
        why_now_parts.append(f"frontier_peers={frontier_peer_labels}")


def _extract_focus_frontier_peer_labels(focus_liquidity_profile: dict[str, Any], *, limit: int = 3) -> list[str]:
    frontier_peer_summary = dict(focus_liquidity_profile.get("frontier_peer_summary") or {})
    frontier_rows = list(frontier_peer_summary.get("top_frontier_peers") or focus_liquidity_profile.get("top_frontier_peers") or [])
    labels = [str(row.get("ticker") or "").strip() for row in frontier_rows if str(row.get("ticker") or "").strip()]
    return labels[:limit]


def _build_corridor_runbook_suffix(*, focus_ticker: str, corridor_uplift_runbook_summary: dict[str, Any]) -> str:
    runbook_primary = str(corridor_uplift_runbook_summary.get("primary_shadow_replay") or "").strip()
    runbook_step = str(corridor_uplift_runbook_summary.get("execution_step_head") or corridor_uplift_runbook_summary.get("next_step") or "").strip()
    runbook_guardrail = str(corridor_uplift_runbook_summary.get("guardrail_head") or "").strip()
    runbook_parallel = [str(ticker) for ticker in list(corridor_uplift_runbook_summary.get("parallel_watch_tickers") or []) if str(ticker).strip()]
    runbook_excluded_low_gate_tail = [str(ticker) for ticker in list(corridor_uplift_runbook_summary.get("excluded_low_gate_tail_tickers") or []) if str(ticker).strip()]
    if not focus_ticker or runbook_primary != focus_ticker or not runbook_step:
        return ""
    suffix = f"；runbook 首步：{runbook_step}"
    if runbook_parallel:
        suffix += f"；confirmatory parallel={runbook_parallel}"
    if runbook_excluded_low_gate_tail:
        suffix += f"；excluded_low_gate_tail={runbook_excluded_low_gate_tail}"
    if runbook_guardrail:
        suffix += f"；guardrail：{runbook_guardrail}"
    return suffix


def _build_truncated_corridor_shadow_next_step(*, focus_ticker: str, focus_liquidity_profile: dict[str, Any], runbook_suffix: str) -> str:
    closest_case = dict(focus_liquidity_profile.get("closest_case") or {})
    closest_gap = closest_case.get("pre_truncation_rank_gap_to_cutoff")
    closest_share = closest_case.get("pre_truncation_avg_amount_share_of_cutoff")
    prototype_type = str(focus_liquidity_profile.get("prototype_type") or "").strip()
    prototype_summary = str(focus_liquidity_profile.get("prototype_summary") or "").strip()
    frontier_peer_labels = _extract_focus_frontier_peer_labels(focus_liquidity_profile)
    gap_suffix = f"最近 distinct 样本仍差 {closest_gap} 名" if closest_gap is not None and str(closest_gap).strip() != "" else "先锁定最近 distinct 样本的排名差距"
    share_suffix = f"，avg_amount/cutoff≈{closest_share}" if closest_share is not None and str(closest_share).strip() != "" else ""
    frontier_suffix = f"；先对比最近 frontier peers {frontier_peer_labels} 的量价差" if frontier_peer_labels else ""
    prefix = f"先补 {focus_ticker} 的 pre-truncation 排名观测与 top300 frontier；{gap_suffix}{share_suffix}{frontier_suffix}"
    if prototype_type and runbook_suffix:
        return f"{prefix}，再按 {prototype_type} 执行。{runbook_suffix}"
    if prototype_type and prototype_summary:
        return f"{prefix}，再按 {prototype_type} 执行：{prototype_summary}{runbook_suffix}"
    if prototype_type:
        return f"{prefix}，再按 {prototype_type} 执行，不做 cutoff 微调。{runbook_suffix}"
    return f"{prefix}，继续按 corridor uplift shadow probe 处理，不做 cutoff 微调。{runbook_suffix}"


def _build_corridor_primary_shadow_next_step(
    *,
    focus_ticker: str,
    shadow_summary: dict[str, Any],
    corridor_uplift_runbook_summary: dict[str, Any],
    candidate_pool_recall_dominant_stage: str,
    focus_liquidity_profile: dict[str, Any],
    active_absent_from_candidate_pool_tickers: set[str],
    active_absent_from_watchlist_tickers: set[str],
    active_shadow_visible_focus_tickers: set[str],
) -> str:
    next_step = str(shadow_summary.get("next_step") or "").strip()
    runbook_suffix = _build_corridor_runbook_suffix(
        focus_ticker=focus_ticker,
        corridor_uplift_runbook_summary=corridor_uplift_runbook_summary,
    )
    if focus_ticker in active_shadow_visible_focus_tickers:
        if next_step:
            return next_step
        return f"保持 {focus_ticker} 在 focused shadow recall 可见，优先沿 shadow -> Layer B / watchlist handoff 推进 corridor uplift primary shadow replay。{runbook_suffix}"
    if focus_ticker in active_absent_from_candidate_pool_tickers:
        if candidate_pool_recall_dominant_stage == "candidate_pool_truncated_after_filters" and focus_liquidity_profile:
            return _build_truncated_corridor_shadow_next_step(
                focus_ticker=focus_ticker,
                focus_liquidity_profile=focus_liquidity_profile,
                runbook_suffix=runbook_suffix,
            )
        return f"先回查 {focus_ticker} 为什么连 candidate_pool snapshot 都没有进入，优先补 watchlist -> candidate_pool handoff，再执行 corridor uplift primary shadow replay。"
    if focus_ticker in active_absent_from_watchlist_tickers:
        return f"先回查 {focus_ticker} 为什么连 watchlist 都没有进入，优先修复 candidate pool -> watchlist handoff，再执行 corridor uplift primary shadow replay。"
    if next_step:
        return next_step
    return f"先对 {focus_ticker} 执行 corridor uplift primary shadow replay，保持 Layer A liquidity gate 与 top300 cutoff 默认口径不变。"


def _build_candidate_pool_corridor_primary_shadow_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    return _build_candidate_pool_corridor_primary_shadow_task_impl(
        control_tower_snapshot,
        normalize_primary_shadow_replay=_normalize_primary_shadow_replay,
        collect_control_tower_ticker_set=_collect_control_tower_ticker_set,
        find_candidate_pool_focus_liquidity_profile=_find_candidate_pool_focus_liquidity_profile,
        append_primary_shadow_replay_context=_append_primary_shadow_replay_context,
        append_truncation_context=_append_truncation_context,
        build_corridor_primary_shadow_next_step=_build_corridor_primary_shadow_next_step,
    )


def _build_lane_priority_task(
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
    *,
    lane_id: str,
    task_id: str,
    title_template: str,
    fallback_why_now: str,
    source: str,
) -> dict[str, Any] | None:
    return _build_lane_priority_task_impl(
        latest_btst_snapshot,
        control_tower_snapshot,
        lane_id=lane_id,
        task_id=task_id,
        title_template=title_template,
        fallback_why_now=fallback_why_now,
        source=source,
        extract_priority_summary=_extract_priority_summary,
    )


def _extract_carryover_contract_context(control_tower_snapshot: dict[str, Any]) -> dict[str, Any]:
    return _extract_carryover_contract_context_impl(control_tower_snapshot)


def _describe_selected_contract_style(*, audit_summary: dict[str, Any]) -> str:
    return _describe_selected_contract_style_impl(audit_summary=audit_summary)


def _prioritize_ticker_in_list(tickers: list[Any], prioritized_ticker: str) -> list[str]:
    return _prioritize_ticker_in_list_impl(tickers, prioritized_ticker)


def _build_labeled_why_now_segments(*segments: tuple[Any, str]) -> list[str]:
    return _build_labeled_why_now_segments_impl(*segments)


def _build_carryover_contract_why_now_parts(context: dict[str, Any]) -> list[str]:
    return _build_carryover_contract_why_now_parts_impl(context)


def _build_carryover_contract_next_steps(context: dict[str, Any]) -> list[str]:
    return _build_carryover_contract_next_steps_impl(
        context,
        build_carryover_contract_lead_step=_build_carryover_contract_lead_step,
        build_carryover_contract_broad_family_step=_build_carryover_contract_broad_family_step,
        build_carryover_contract_peer_focus_step=_build_carryover_contract_peer_focus_step,
        build_carryover_contract_priority_expansion_step=_build_carryover_contract_priority_expansion_step,
        build_carryover_contract_promotion_review_step=_build_carryover_contract_promotion_review_step,
        build_carryover_contract_promotion_gate_step=_build_carryover_contract_promotion_gate_step,
        build_carryover_contract_watch_with_risk_step=_build_carryover_contract_watch_with_risk_step,
    )


def _build_carryover_contract_peer_focus_step(*, peer_focus_ticker: str, peer_focus_status: str) -> str | None:
    if not peer_focus_ticker:
        return None
    return f"优先盯 {peer_focus_ticker} 的 {peer_focus_status or 'peer_harvest'} 闭环；只有第二个 aligned peer 完成 closed-cycle 转强后才讨论 lane 扩容。"


def _build_carryover_contract_promotion_review_step(ready_for_promotion_review_tickers: list[Any]) -> str | None:
    if not ready_for_promotion_review_tickers:
        return None
    return f"当前 ready-for-promotion-review peers: {ready_for_promotion_review_tickers}，应按第二个 aligned peer evidence 进入 promotion review。"


def _build_carryover_contract_promotion_gate_step(promotion_gate_ready_tickers: list[Any]) -> str | None:
    if not promotion_gate_ready_tickers:
        return None
    return f"当前已通过 promotion gate 的 peers: {promotion_gate_ready_tickers}，只允许在极窄 carryover lane 里讨论扩容。"


def _build_carryover_contract_broad_family_step(is_broad_family_only_multiday_unsupported: bool) -> str | None:
    if not is_broad_family_only_multiday_unsupported:
        return None
    return "broad_family_only carryover 仅保留 evidence-deficient / diagnostic 语义，不进入多日 continuation contract。"


def _build_carryover_contract_priority_expansion_step(priority_expansion_tickers: list[Any]) -> str | None:
    if not priority_expansion_tickers:
        return None
    return f"当前 priority expansion 队列先看 {priority_expansion_tickers}。"


def _build_carryover_contract_watch_with_risk_step(watch_with_risk_tickers: list[Any]) -> str | None:
    if not watch_with_risk_tickers:
        return None
    return f"{watch_with_risk_tickers} 仅保留 watch-with-risk 语义，不作为扩容依据。"


def _build_carryover_contract_lead_step(*, formal_selected_ticker: str, contract_style: str) -> str:
    if contract_style == "intraday confirmation-only":
        return f"继续把 {formal_selected_ticker} 作为 intraday confirmation-only 合约管理，不把它升级成隔夜 hold-bias 或稳定 T+3/T+4 continuation。"
    if contract_style == "confirm-then-hold + T+2 bias":
        return f"继续把 {formal_selected_ticker} 作为 confirm-then-hold + T+2 bias 合约管理，不把它包装成稳定 T+3/T+4 continuation。"
    return f"继续把 {formal_selected_ticker} 作为 confirm-then-hold 合约管理，先不要外推成更强的 T+2/T+3 continuation 语义。"


def _has_carryover_contract_priority(context: dict[str, Any]) -> bool:
    formal_selected_ticker = str(context.get("formal_selected_ticker") or "").strip()
    overall_contract_verdict = str(context.get("overall_contract_verdict") or "").strip()
    return bool(formal_selected_ticker) and "violated" not in overall_contract_verdict


def _build_carryover_contract_title(context: dict[str, Any]) -> str:
    formal_selected_ticker = str(context.get("formal_selected_ticker") or "").strip()
    peer_focus_ticker = str(context.get("peer_focus_ticker") or "").strip()
    return f"固化 {formal_selected_ticker} carryover 合约并盯 {peer_focus_ticker} 闭环" if peer_focus_ticker else f"固化 {formal_selected_ticker} carryover 合约"


def _build_carryover_contract_task_payload(context: dict[str, Any]) -> dict[str, Any]:
    return _build_control_tower_task_payload(
        task_id="carryover_contract_priority",
        title=_build_carryover_contract_title(context),
        why_now_parts=_build_carryover_contract_why_now_parts(context),
        next_steps=_build_carryover_contract_next_steps(context),
        source="carryover_contract",
    )


def _build_carryover_contract_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    context = _extract_carryover_contract_context(control_tower_snapshot)
    if not _has_carryover_contract_priority(context):
        return None

    return _build_carryover_contract_task_payload(context)


def _build_peer_selected_contract_safeguard_step(selected_contract_verdict: str, *, template: str) -> str | None:
    if not selected_contract_verdict:
        return None
    return template.format(selected_contract_verdict=selected_contract_verdict)


def _extract_selected_contract_task_context(control_tower_snapshot: dict[str, Any]) -> dict[str, Any]:
    selected_summary = dict(control_tower_snapshot.get("selected_outcome_refresh_summary") or {})
    audit_summary = dict(control_tower_snapshot.get("carryover_multiday_continuation_audit_summary") or {})
    return {
        "audit_summary": audit_summary,
        "focus_ticker": str(selected_summary.get("focus_ticker") or "").strip(),
        "overall_contract_verdict": str(selected_summary.get("focus_overall_contract_verdict") or "").strip(),
        "focus_cycle_status": str(selected_summary.get("focus_cycle_status") or "").strip(),
        "next_day_contract_verdict": str(selected_summary.get("focus_next_day_contract_verdict") or "").strip(),
        "t_plus_2_contract_verdict": str(selected_summary.get("focus_t_plus_2_contract_verdict") or "").strip(),
    }


def _build_selected_contract_why_now_parts(context: dict[str, Any]) -> list[str]:
    audit_summary = dict(context.get("audit_summary") or {})
    return _build_labeled_why_now_segments(
        (context.get("focus_ticker"), "focus_ticker"),
        (context.get("overall_contract_verdict"), "overall_contract_verdict"),
        (context.get("focus_cycle_status"), "focus_cycle_status"),
        (context.get("next_day_contract_verdict"), "next_day_contract_verdict"),
        (context.get("t_plus_2_contract_verdict"), "t_plus_2_contract_verdict"),
        (audit_summary.get("selected_preferred_entry_mode"), "selected_entry_mode"),
        (audit_summary.get("selected_execution_quality_label"), "selected_execution_quality"),
    )


def _build_selected_contract_resolution_title(context: dict[str, Any]) -> str:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    overall_contract_verdict = str(context.get("overall_contract_verdict") or "").strip()
    if "violated" in overall_contract_verdict:
        return f"优先处置 {focus_ticker} selected contract 失效"
    if "observed_without_positive_expectation" in overall_contract_verdict:
        return f"优先复核 {focus_ticker} selected contract 已闭环"
    return f"优先复核 {focus_ticker} selected contract 已兑现"


def _build_selected_contract_resolution_violated_steps(context: dict[str, Any]) -> list[str]:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    focus_cycle_status = str(context.get("focus_cycle_status") or "").strip()
    next_steps = [f"立刻把 {focus_ticker} 从 carryover 主合约语义中降级，停止把它当作次日/多日 continuation 锚点。"]
    if focus_cycle_status:
        next_steps.append(f"结合当前 cycle_status={focus_cycle_status} 复核是 next-day 失效还是 T+2 失效，并同步回看触发该票入选的 frontier 证据。")
    return next_steps


def _build_selected_contract_resolution_lead_step(context: dict[str, Any]) -> str:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    overall_contract_verdict = str(context.get("overall_contract_verdict") or "").strip()
    if "observed_without_positive_expectation" in overall_contract_verdict:
        return f"立刻复核 {focus_ticker} 已闭环的 selected contract 是否只支持 execution-quality 结论，而不是被误写成更强 continuation 兑现。"
    return f"立刻复核 {focus_ticker} 已兑现的 selected contract 是否足以支撑更高确信度的 BTST carryover 叙事，但仍避免把单票确认外推成过宽 lane。"


def _build_selected_contract_resolution_t_plus_2_followup(context: dict[str, Any]) -> str:
    t_plus_2_contract_verdict = str(context.get("t_plus_2_contract_verdict") or "").strip()
    contract_style = _describe_selected_contract_style_from_context(context)
    if contract_style == "intraday confirmation-only":
        return f"同步确认 T+2 contract verdict={t_plus_2_contract_verdict}，继续把它固定在 intraday confirmation-only / execution-quality 语义，不升级成 hold-bias。"
    return f"同步确认 T+2 contract verdict={t_plus_2_contract_verdict}，决定是继续 hold-bias 还是仅保留 confirm-then-hold 语义。"


def _build_selected_contract_resolution_next_steps(context: dict[str, Any]) -> list[str]:
    overall_contract_verdict = str(context.get("overall_contract_verdict") or "").strip()
    t_plus_2_contract_verdict = str(context.get("t_plus_2_contract_verdict") or "").strip()
    if "violated" in overall_contract_verdict:
        return _build_selected_contract_resolution_violated_steps(context)

    next_steps = [_build_selected_contract_resolution_lead_step(context)]
    if not t_plus_2_contract_verdict:
        return next_steps
    next_steps.append(_build_selected_contract_resolution_t_plus_2_followup(context))
    return next_steps


def _build_selected_contract_monitor_lead_step(context: dict[str, Any]) -> str:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    contract_style = _describe_selected_contract_style_from_context(context)
    if contract_style == "intraday confirmation-only":
        return f"优先盯 {focus_ticker} 的主票闭环，确认 next-day bar 到来后是否仍只支持 intraday confirmation-only，而不是被误读成隔夜 hold-bias。"
    if contract_style == "confirm-then-hold + T+2 bias":
        return f"优先盯 {focus_ticker} 的主票闭环，确认 next-day bar 到来后是否仍满足 confirm-then-hold with T+2 bias 的 selected contract。"
    return f"优先盯 {focus_ticker} 的主票闭环，确认 next-day bar 到来后是否仍只支持 confirm-then-hold，而不是被外推成更强 continuation 合约。"


def _build_selected_contract_monitor_followup_step(context: dict[str, Any]) -> str | None:
    overall_contract_verdict = str(context.get("overall_contract_verdict") or "").strip()
    if overall_contract_verdict == "pending_next_day":
        return "一旦 next-day bar 落地，立即复核 next_close / intraday follow-through，避免 recall 或 peer 扩容叙事抢占 formal selected 主线。"
    if overall_contract_verdict == "pending_t_plus_2":
        return "一旦 T+2 bar 落地，立即复核 hold-bias 是否兑现，并决定是否继续保留 carryover 语义。"
    return None


def _describe_selected_contract_style_from_context(context: dict[str, Any]) -> str:
    audit_summary = dict(context.get("audit_summary") or {})
    return _describe_selected_contract_style(audit_summary=audit_summary)


def _build_selected_contract_monitor_next_steps(context: dict[str, Any]) -> list[str]:
    next_steps = [_build_selected_contract_monitor_lead_step(context)]
    followup_step = _build_selected_contract_monitor_followup_step(context)
    if followup_step:
        next_steps.append(followup_step)
    return next_steps


def _build_control_tower_task_payload(
    *,
    task_id: str,
    title: str,
    why_now_parts: list[str],
    next_steps: list[str],
    source: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "title": title,
        "why_now": " | ".join(why_now_parts),
        "next_step": "；".join(next_steps),
        "source": source,
    }


def _build_selected_contract_task_payload(
    *,
    context: dict[str, Any],
    task_id: str,
    title: str,
    next_steps: list[str],
    source: str,
) -> dict[str, Any]:
    return _build_control_tower_task_payload(
        task_id=task_id,
        title=title,
        why_now_parts=_build_selected_contract_why_now_parts(context),
        next_steps=next_steps,
        source=source,
    )


def _resolve_selected_contract_gate_values(context: dict[str, Any]) -> tuple[str, str]:
    return (
        str(context.get("focus_ticker") or "").strip(),
        str(context.get("overall_contract_verdict") or "").strip(),
    )


def _selected_contract_verdict_matches_gate(overall_contract_verdict: str, *, pending: bool) -> bool:
    if not overall_contract_verdict:
        return False
    return overall_contract_verdict.startswith("pending") if pending else not overall_contract_verdict.startswith("pending")


def _has_selected_contract_priority(context: dict[str, Any], *, pending: bool) -> bool:
    focus_ticker, overall_contract_verdict = _resolve_selected_contract_gate_values(context)
    return bool(focus_ticker) and _selected_contract_verdict_matches_gate(overall_contract_verdict, pending=pending)


def _has_selected_contract_resolution_priority(context: dict[str, Any]) -> bool:
    return _has_selected_contract_priority(context, pending=False)


def _has_selected_contract_monitor_priority(context: dict[str, Any]) -> bool:
    return _has_selected_contract_priority(context, pending=True)


def _build_selected_contract_resolution_task_payload(context: dict[str, Any]) -> dict[str, Any]:
    return _build_selected_contract_task_payload(
        context=context,
        task_id="selected_contract_resolution_priority",
        title=_build_selected_contract_resolution_title(context),
        next_steps=_build_selected_contract_resolution_next_steps(context),
        source="selected_contract_resolution",
    )


def _build_selected_contract_resolution_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    context = _extract_selected_contract_task_context(control_tower_snapshot)
    if not _has_selected_contract_resolution_priority(context):
        return None

    return _build_selected_contract_resolution_task_payload(context)


def _is_low_urgency_selected_contract_resolution(control_tower_snapshot: dict[str, Any]) -> bool:
    context = _extract_selected_contract_task_context(control_tower_snapshot)
    overall_contract_verdict = str(context.get("overall_contract_verdict") or "").strip()
    if "observed_without_positive_expectation" not in overall_contract_verdict:
        return False
    return _describe_selected_contract_style_from_context(context) == "intraday confirmation-only"


def _build_selected_contract_monitor_title(context: dict[str, Any]) -> str:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    return f"优先监控 {focus_ticker} formal selected 主票闭环"


def _build_selected_contract_monitor_task_payload(context: dict[str, Any]) -> dict[str, Any]:
    return _build_selected_contract_task_payload(
        context=context,
        task_id="selected_contract_monitor_priority",
        title=_build_selected_contract_monitor_title(context),
        next_steps=_build_selected_contract_monitor_next_steps(context),
        source="selected_contract_monitor",
    )


def _build_selected_contract_monitor_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    context = _extract_selected_contract_task_context(control_tower_snapshot)
    if not _has_selected_contract_monitor_priority(context):
        return None

    return _build_selected_contract_monitor_task_payload(context)


def _extract_gate_ready_task_context(control_tower_snapshot: dict[str, Any]) -> dict[str, Any]:
    gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})
    ready_tickers = [str(ticker) for ticker in list(gate_summary.get("ready_tickers") or []) if str(ticker).strip()]
    return {
        "ready_tickers": ready_tickers,
        "selected_ticker": str(gate_summary.get("selected_ticker") or "").strip(),
        "selected_contract_verdict": str(gate_summary.get("selected_contract_verdict") or "").strip(),
        "focus_ticker": str(gate_summary.get("focus_ticker") or (ready_tickers[0] if ready_tickers else "")).strip(),
        "focus_gate_verdict": str(gate_summary.get("focus_gate_verdict") or "promotion_gate_ready").strip(),
    }


def _build_gate_ready_why_now_parts(context: dict[str, Any]) -> list[str]:
    ready_tickers = list(context.get("ready_tickers") or [])
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    focus_gate_verdict = str(context.get("focus_gate_verdict") or "").strip()
    selected_ticker = str(context.get("selected_ticker") or "").strip()
    selected_contract_verdict = str(context.get("selected_contract_verdict") or "").strip()
    why_now_parts = [f"ready_tickers={ready_tickers}", f"focus_ticker={focus_ticker}", f"focus_gate_verdict={focus_gate_verdict}"]
    if selected_ticker:
        why_now_parts.append(f"selected_ticker={selected_ticker}")
    if selected_contract_verdict:
        why_now_parts.append(f"selected_contract_verdict={selected_contract_verdict}")
    return why_now_parts


def _build_gate_ready_next_steps(context: dict[str, Any]) -> list[str]:
    ready_tickers = list(context.get("ready_tickers") or [])
    selected_ticker = str(context.get("selected_ticker") or "").strip()
    selected_contract_verdict = str(context.get("selected_contract_verdict") or "").strip()
    next_steps = [
        f"立刻把 {ready_tickers} 作为第二个 aligned peer expansion review 的最高优先级，先复核 closed-cycle 兑现与执行约束，再决定是否在极窄 carryover lane 中扩容。"
    ]
    safeguard_step = _build_peer_selected_contract_safeguard_step(
        selected_contract_verdict or "pending",
        template=f"同步确认 {selected_ticker} 当前合约仍保持 {{selected_contract_verdict}}，避免主票未闭环时误扩容。",
    ) if selected_ticker else None
    if safeguard_step:
        next_steps.append(safeguard_step)
    return next_steps


def _has_gate_ready_priority(context: dict[str, Any]) -> bool:
    return bool(list(context.get("ready_tickers") or []))


def _build_gate_ready_priority_title(context: dict[str, Any]) -> str:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    return f"优先复核 {focus_ticker} carryover gate-ready 扩容资格"


def _build_gate_ready_priority_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    context = _extract_gate_ready_task_context(control_tower_snapshot)
    if not _has_gate_ready_priority(context):
        return None

    return _build_control_tower_task_payload(
        task_id="carryover_gate_ready_priority",
        title=_build_gate_ready_priority_title(context),
        why_now_parts=_build_gate_ready_why_now_parts(context),
        next_steps=_build_gate_ready_next_steps(context),
        source="carryover_gate_ready",
    )


def _extract_peer_proof_task_context(control_tower_snapshot: dict[str, Any]) -> dict[str, Any]:
    proof_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_proof_summary") or {})
    gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})
    ready_for_promotion_review_tickers = [str(ticker) for ticker in list(proof_summary.get("ready_for_promotion_review_tickers") or []) if str(ticker).strip()]
    return {
        "ready_for_promotion_review_tickers": ready_for_promotion_review_tickers,
        "promotion_gate_ready_tickers": [str(ticker) for ticker in list(gate_summary.get("ready_tickers") or []) if str(ticker).strip()],
        "focus_ticker": str(proof_summary.get("focus_ticker") or (ready_for_promotion_review_tickers[0] if ready_for_promotion_review_tickers else "")).strip(),
        "focus_proof_verdict": str(proof_summary.get("focus_proof_verdict") or "").strip(),
        "focus_promotion_review_verdict": str(proof_summary.get("focus_promotion_review_verdict") or "ready_for_promotion_review").strip(),
        "selected_contract_verdict": str(gate_summary.get("selected_contract_verdict") or "").strip(),
    }


def _build_peer_proof_why_now_parts(context: dict[str, Any]) -> list[str]:
    ready_for_promotion_review_tickers = list(context.get("ready_for_promotion_review_tickers") or [])
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    focus_proof_verdict = str(context.get("focus_proof_verdict") or "").strip()
    focus_promotion_review_verdict = str(context.get("focus_promotion_review_verdict") or "").strip()
    selected_contract_verdict = str(context.get("selected_contract_verdict") or "").strip()
    why_now_parts = [
        f"ready_for_promotion_review_tickers={ready_for_promotion_review_tickers}",
        f"focus_ticker={focus_ticker}",
        f"focus_promotion_review_verdict={focus_promotion_review_verdict}",
    ]
    if focus_proof_verdict:
        why_now_parts.append(f"focus_proof_verdict={focus_proof_verdict}")
    if selected_contract_verdict:
        why_now_parts.append(f"selected_contract_verdict={selected_contract_verdict}")
    return why_now_parts


def _build_peer_proof_next_steps(context: dict[str, Any]) -> list[str]:
    ready_for_promotion_review_tickers = list(context.get("ready_for_promotion_review_tickers") or [])
    selected_contract_verdict = str(context.get("selected_contract_verdict") or "").strip()
    next_steps = [
        f"立刻复核 {ready_for_promotion_review_tickers} 的第二个 aligned peer close-loop 证据，确认它们是否足以进入 promotion review，但在 gate 未 ready 前不要提前扩容。"
    ]
    safeguard_step = _build_peer_selected_contract_safeguard_step(
        selected_contract_verdict,
        template="同步确认 formal selected contract 当前仍为 {selected_contract_verdict}，避免 peer proof-ready 被误读成已可扩容。",
    )
    if safeguard_step:
        next_steps.append(safeguard_step)
    return next_steps


def _has_peer_proof_priority(context: dict[str, Any]) -> bool:
    ready_for_promotion_review_tickers = list(context.get("ready_for_promotion_review_tickers") or [])
    promotion_gate_ready_tickers = list(context.get("promotion_gate_ready_tickers") or [])
    return bool(ready_for_promotion_review_tickers) and not promotion_gate_ready_tickers


def _build_peer_proof_priority_title(context: dict[str, Any]) -> str:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    return f"优先复核 {focus_ticker} peer proof-ready 资格"


def _build_peer_proof_priority_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    context = _extract_peer_proof_task_context(control_tower_snapshot)
    if not _has_peer_proof_priority(context):
        return None

    return _build_control_tower_task_payload(
        task_id="carryover_peer_proof_priority",
        title=_build_peer_proof_priority_title(context),
        why_now_parts=_build_peer_proof_why_now_parts(context),
        next_steps=_build_peer_proof_next_steps(context),
        source="carryover_peer_proof",
    )


def _extract_peer_close_loop_task_context(control_tower_snapshot: dict[str, Any]) -> dict[str, Any]:
    proof_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_proof_summary") or {})
    gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})
    return {
        "focus_ticker": str(proof_summary.get("focus_ticker") or gate_summary.get("focus_ticker") or "").strip(),
        "focus_proof_verdict": str(proof_summary.get("focus_proof_verdict") or "").strip(),
        "focus_promotion_review_verdict": str(proof_summary.get("focus_promotion_review_verdict") or "").strip(),
        "focus_gate_verdict": str(gate_summary.get("focus_gate_verdict") or "").strip(),
        "pending_next_day_tickers": [str(ticker) for ticker in list(gate_summary.get("pending_next_day_tickers") or []) if str(ticker).strip()],
        "pending_t_plus_2_tickers": [str(ticker) for ticker in list(gate_summary.get("pending_t_plus_2_tickers") or []) if str(ticker).strip()],
        "selected_contract_verdict": str(gate_summary.get("selected_contract_verdict") or "").strip(),
    }


def _resolve_peer_close_loop_phase(context: dict[str, Any]) -> str:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    focus_proof_verdict = str(context.get("focus_proof_verdict") or "").strip()
    focus_promotion_review_verdict = str(context.get("focus_promotion_review_verdict") or "").strip()
    focus_gate_verdict = str(context.get("focus_gate_verdict") or "").strip()
    pending_next_day_tickers = list(context.get("pending_next_day_tickers") or [])
    pending_t_plus_2_tickers = list(context.get("pending_t_plus_2_tickers") or [])
    if focus_ticker and (
        focus_proof_verdict == "pending_next_day_close"
        or focus_promotion_review_verdict == "await_next_day_close"
        or focus_gate_verdict == "await_peer_next_day_close"
        or focus_ticker in pending_next_day_tickers
    ):
        return "next_day"
    if focus_ticker and (
        focus_proof_verdict == "pending_t_plus_2_close"
        or focus_promotion_review_verdict == "await_t_plus_2_close"
        or focus_gate_verdict == "await_peer_t_plus_2_close"
        or focus_ticker in pending_t_plus_2_tickers
    ):
        return "t_plus_2"
    return ""


def _build_peer_close_loop_why_now_parts(context: dict[str, Any]) -> list[str]:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    focus_proof_verdict = str(context.get("focus_proof_verdict") or "").strip()
    focus_promotion_review_verdict = str(context.get("focus_promotion_review_verdict") or "").strip()
    focus_gate_verdict = str(context.get("focus_gate_verdict") or "").strip()
    pending_next_day_tickers = list(context.get("pending_next_day_tickers") or [])
    pending_t_plus_2_tickers = list(context.get("pending_t_plus_2_tickers") or [])
    selected_contract_verdict = str(context.get("selected_contract_verdict") or "").strip()
    why_now_parts = [f"focus_ticker={focus_ticker}"]
    if focus_proof_verdict:
        why_now_parts.append(f"focus_proof_verdict={focus_proof_verdict}")
    if focus_promotion_review_verdict:
        why_now_parts.append(f"focus_promotion_review_verdict={focus_promotion_review_verdict}")
    if focus_gate_verdict:
        why_now_parts.append(f"focus_gate_verdict={focus_gate_verdict}")
    if pending_next_day_tickers:
        why_now_parts.append(f"pending_next_day_tickers={pending_next_day_tickers}")
    if pending_t_plus_2_tickers:
        why_now_parts.append(f"pending_t_plus_2_tickers={pending_t_plus_2_tickers}")
    if selected_contract_verdict:
        why_now_parts.append(f"selected_contract_verdict={selected_contract_verdict}")
    return why_now_parts


def _build_peer_close_loop_next_steps(context: dict[str, Any]) -> list[str]:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    selected_contract_verdict = str(context.get("selected_contract_verdict") or "").strip()
    close_loop_phase = _resolve_peer_close_loop_phase(context)
    if close_loop_phase == "next_day":
        next_steps = [f"优先盯 {focus_ticker} 的 peer next-day close-loop，等待 next-day bar 落地后确认是否从 pending_next_day_close 翻到 pending_t_plus_2_close / proof-ready。"]
    else:
        next_steps = [f"优先盯 {focus_ticker} 的 peer close-loop，等待 T+2 bar 落地后确认是否从 pending_t_plus_2_close 翻到 proof-ready / promotion-review-ready。"]
    safeguard_step = _build_peer_selected_contract_safeguard_step(
        selected_contract_verdict,
        template="同步确认 formal selected contract 仍为 {selected_contract_verdict}，避免主票未闭环时提前把 peer 读成可扩容。",
    )
    if safeguard_step:
        next_steps.append(safeguard_step)
    return next_steps


def _is_pending_peer_close_loop(context: dict[str, Any]) -> bool:
    return bool(_resolve_peer_close_loop_phase(context))


def _build_peer_close_loop_monitor_title(context: dict[str, Any]) -> str:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    close_loop_phase = _resolve_peer_close_loop_phase(context)
    if close_loop_phase == "next_day":
        return f"优先监控 {focus_ticker} peer next-day close-loop"
    return f"优先监控 {focus_ticker} peer T+2 close-loop"


def _build_peer_close_loop_monitor_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    context = _extract_peer_close_loop_task_context(control_tower_snapshot)
    if not _is_pending_peer_close_loop(context):
        return None

    return _build_control_tower_task_payload(
        task_id="carryover_peer_close_loop_monitor_priority",
        title=_build_peer_close_loop_monitor_title(context),
        why_now_parts=_build_peer_close_loop_why_now_parts(context),
        next_steps=_build_peer_close_loop_next_steps(context),
        source="carryover_peer_close_loop_monitor",
    )


def _collect_control_tower_priority_candidates(
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
) -> list[dict[str, Any] | None]:
    return _collect_control_tower_priority_candidates_impl(
        latest_btst_snapshot,
        control_tower_snapshot,
        build_selected_contract_resolution_task=_build_selected_contract_resolution_task,
        is_low_urgency_selected_contract_resolution=_is_low_urgency_selected_contract_resolution,
        build_selected_contract_monitor_task=_build_selected_contract_monitor_task,
        build_gate_ready_priority_task=_build_gate_ready_priority_task,
        build_peer_proof_priority_task=_build_peer_proof_priority_task,
        build_peer_close_loop_monitor_task=_build_peer_close_loop_monitor_task,
        build_carryover_contract_task=_build_carryover_contract_task,
        build_candidate_pool_corridor_primary_shadow_task=_build_candidate_pool_corridor_primary_shadow_task,
        build_recall_priority_task=_build_recall_priority_task,
        build_lane_priority_task=_build_lane_priority_task,
    )


def _dedupe_control_tower_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for task in tasks:
        dedupe_key = (str(task.get("title") or "").strip(), str(task.get("next_step") or "").strip())
        if not any(dedupe_key):
            continue
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(task)
    return deduped


def _prioritize_control_tower_next_actions(
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    return _prioritize_control_tower_next_actions_impl(
        latest_btst_snapshot,
        control_tower_snapshot,
        collect_control_tower_priority_candidates=_collect_control_tower_priority_candidates,
        dedupe_control_tower_tasks=_dedupe_control_tower_tasks,
    )


def _extract_replay_cohort_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    cohort = _safe_load_json(dict(manifest.get("btst_replay_cohort_refresh") or {}).get("output_json"))
    cohort_summaries = list(cohort.get("cohort_summaries") or [])
    short_trade_summary = next((dict(summary or {}) for summary in cohort_summaries if summary.get("label") == "short_trade_only"), {})
    frozen_summary = next((dict(summary or {}) for summary in cohort_summaries if summary.get("label") == "frozen_replay"), {})
    return {
        "cohort": cohort,
        "report_count": cohort.get("report_count"),
        "selection_target_counts": cohort.get("selection_target_counts"),
        "recommendation": cohort.get("recommendation"),
        "latest_short_trade_row": cohort.get("latest_short_trade_row"),
        "short_trade_summary": short_trade_summary,
        "frozen_summary": frozen_summary,
        "top_return_rows": list(cohort.get("top_return_rows") or [])[:3],
    }


def _diff_priority_board(
    current_snapshot: dict[str, Any],
    previous_board: dict[str, Any],
    *,
    previous_summary_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _diff_priority_board_impl(
        current_snapshot,
        previous_board,
        previous_summary_source=previous_summary_source,
        extract_priority_summary=_extract_priority_summary,
        as_float=_as_float,
    )


def _build_priority_rows_by_ticker(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return _build_priority_rows_by_ticker_impl(rows)


def _build_rank_map(rows_by_ticker: dict[str, dict[str, Any]]) -> dict[str, int]:
    return _build_rank_map_impl(rows_by_ticker)


def _collect_priority_board_membership_changes(
    current_by_ticker: dict[str, dict[str, Any]],
    previous_by_ticker: dict[str, dict[str, Any]],
    *,
    added: bool,
) -> list[dict[str, Any]]:
    return _collect_priority_board_membership_changes_impl(
        current_by_ticker,
        previous_by_ticker,
        added=added,
    )


def _collect_priority_board_per_ticker_changes(
    *,
    current_by_ticker: dict[str, dict[str, Any]],
    previous_by_ticker: dict[str, dict[str, Any]],
    current_ranks: dict[str, int],
    previous_ranks: dict[str, int],
) -> dict[str, list[dict[str, Any]]]:
    return _collect_priority_board_per_ticker_changes_impl(
        current_by_ticker=current_by_ticker,
        previous_by_ticker=previous_by_ticker,
        current_ranks=current_ranks,
        previous_ranks=previous_ranks,
        as_float=_as_float,
    )


def _build_priority_summary_delta(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, int]:
    return _build_priority_summary_delta_impl(current_summary, previous_summary)


def _diff_governance(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    return _diff_governance_impl(current_payload, previous_payload)


def _build_governance_lane_map(lane_matrix: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return _build_governance_lane_map_impl(lane_matrix)


def _build_governance_lane_delta(
    lane_id: str,
    *,
    current_row: dict[str, Any] | None,
    previous_row: dict[str, Any] | None,
) -> dict[str, Any]:
    return _build_governance_lane_delta_impl(
        lane_id,
        current_row=current_row,
        previous_row=previous_row,
    )


def _has_governance_lane_delta_changes(lane_delta: dict[str, Any]) -> bool:
    return _has_governance_lane_delta_changes_impl(lane_delta)


def _collect_governance_lane_changes(
    current_by_lane: dict[str, dict[str, Any]],
    previous_by_lane: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return _collect_governance_lane_changes_impl(current_by_lane, previous_by_lane)


def _build_governance_aggregate_deltas(current_control: dict[str, Any], previous_control: dict[str, Any]) -> dict[str, int]:
    return _build_governance_aggregate_deltas_impl(current_control, previous_control)


def _diff_replay(
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return _diff_replay_impl(
        current_payload,
        previous_payload,
        previous_report_snapshot,
        extract_priority_summary=_extract_priority_summary,
    )


def _diff_catalyst_frontier(
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return _diff_catalyst_frontier_impl(current_payload, previous_payload, previous_report_snapshot)


def _resolve_catalyst_frontier_previous_summary(
    previous_payload: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    return _resolve_catalyst_frontier_previous_summary_impl(previous_payload, previous_report_snapshot)


def _build_catalyst_frontier_count_deltas(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, int]:
    return _build_catalyst_frontier_count_deltas_impl(current_summary, previous_summary)


def _diff_score_fail_frontier(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    return _diff_score_fail_frontier_impl(current_payload, previous_payload)


def _extract_score_fail_frontier_summaries(
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _extract_score_fail_frontier_summaries_impl(current_payload, previous_payload)


def _diff_ticker_lists(current_tickers: list[Any], previous_tickers: list[Any]) -> dict[str, list[Any]]:
    return _diff_ticker_lists_impl(current_tickers, previous_tickers)


def _build_score_fail_frontier_count_deltas(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, int]:
    return _build_score_fail_frontier_count_deltas_impl(current_summary, previous_summary)


def _diff_carryover_promotion_gate(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    return _diff_carryover_promotion_gate_impl(current_payload, previous_payload)


def _build_carryover_promotion_gate_field_changes(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, bool]:
    return _build_carryover_promotion_gate_field_changes_impl(current_summary, previous_summary)


def _diff_top_priority_action(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    return _diff_top_priority_action_impl(current_payload, previous_payload)


def _diff_selected_outcome_contract(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    return _diff_selected_outcome_contract_impl(current_payload, previous_payload)


def _diff_carryover_peer_proof(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    return _diff_carryover_peer_proof_impl(current_payload, previous_payload)


def _list_changed_delta_sections(delta_payload: dict[str, Any]) -> list[str]:
    changed_sections: list[str] = []
    if dict(delta_payload.get("priority_delta") or {}).get("has_changes"):
        changed_sections.append("priority")
    if dict(delta_payload.get("catalyst_frontier_delta") or {}).get("has_changes"):
        changed_sections.append("catalyst_frontier")
    if dict(delta_payload.get("score_fail_frontier_delta") or {}).get("has_changes"):
        changed_sections.append("score_fail_frontier")
    if dict(delta_payload.get("top_priority_action_delta") or {}).get("has_changes"):
        changed_sections.append("top_priority_action")
    if dict(delta_payload.get("selected_outcome_contract_delta") or {}).get("has_changes"):
        changed_sections.append("selected_outcome_contract")
    if dict(delta_payload.get("carryover_peer_proof_delta") or {}).get("has_changes"):
        changed_sections.append("carryover_peer_proof")
    if dict(delta_payload.get("carryover_promotion_gate_delta") or {}).get("has_changes"):
        changed_sections.append("carryover_promotion_gate")
    if dict(delta_payload.get("governance_delta") or {}).get("has_changes"):
        changed_sections.append("governance")
    if dict(delta_payload.get("replay_delta") or {}).get("has_changes"):
        changed_sections.append("replay")
    return changed_sections


def _build_material_change_anchor(
    current_payload: dict[str, Any],
    *,
    reports_root: str | Path,
    current_nightly_json_path: str | Path,
    historical_payload_candidates: list[tuple[dict[str, Any], str | None]],
) -> dict[str, Any]:
    return _build_material_change_anchor_impl(
        current_payload,
        reports_root=reports_root,
        current_nightly_json_path=current_nightly_json_path,
        historical_payload_candidates=historical_payload_candidates,
        build_btst_open_ready_delta_payload=build_btst_open_ready_delta_payload,
        list_changed_delta_sections=_list_changed_delta_sections,
    )


def _resolve_open_ready_previous_context(
    *,
    latest_btst_run: dict[str, Any],
    previous_payload: dict[str, Any],
    reports_root: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    return _resolve_open_ready_previous_context_impl(
        latest_btst_run=latest_btst_run,
        previous_payload=previous_payload,
        reports_root=reports_root,
        select_previous_btst_report_snapshot=_select_previous_btst_report_snapshot,
    )


def _resolve_open_ready_comparison_scope(comparison_basis: str, previous_reference: dict[str, Any], latest_btst_run: dict[str, Any]) -> str:
    return _resolve_open_ready_comparison_scope_impl(comparison_basis, previous_reference, latest_btst_run)


def _build_open_ready_deltas(
    *,
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
    current_priority_snapshot: dict[str, Any],
    previous_priority_board: dict[str, Any],
) -> dict[str, Any]:
    previous_summary_source = _resolve_open_ready_previous_summary_source(previous_payload, previous_report_snapshot)
    return _build_open_ready_delta_sections(
        current_payload=current_payload,
        previous_payload=previous_payload,
        previous_report_snapshot=previous_report_snapshot,
        current_priority_snapshot=current_priority_snapshot,
        previous_priority_board=previous_priority_board,
        previous_summary_source=previous_summary_source,
    )


def _resolve_open_ready_previous_summary_source(
    previous_payload: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    if previous_payload:
        return dict((previous_payload.get("latest_btst_snapshot") or {}).get("brief_summary") or {})
    return dict(previous_report_snapshot.get("brief_summary") or {})


def _build_open_ready_delta_sections(
    *,
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
    current_priority_snapshot: dict[str, Any],
    previous_priority_board: dict[str, Any],
    previous_summary_source: dict[str, Any],
) -> dict[str, Any]:
    return {
        "priority_delta": _diff_priority_board(current_priority_snapshot, previous_priority_board, previous_summary_source=previous_summary_source),
        "governance_delta": _diff_governance(current_payload, previous_payload),
        "replay_delta": _diff_replay(current_payload, previous_payload, previous_report_snapshot),
        "catalyst_frontier_delta": _diff_catalyst_frontier(current_payload, previous_payload, previous_report_snapshot),
        "score_fail_frontier_delta": _diff_score_fail_frontier(current_payload, previous_payload),
        "top_priority_action_delta": _diff_top_priority_action(current_payload, previous_payload),
        "selected_outcome_contract_delta": _diff_selected_outcome_contract(current_payload, previous_payload),
        "carryover_peer_proof_delta": _diff_carryover_peer_proof(current_payload, previous_payload),
        "carryover_promotion_gate_delta": _diff_carryover_promotion_gate(current_payload, previous_payload),
    }


def _append_open_ready_basis_focus(operator_focus: list[str], comparison_basis: str, comparison_scope: str) -> None:
    _append_open_ready_basis_focus_impl(operator_focus, comparison_basis, comparison_scope)


def _append_open_ready_priority_focus(operator_focus: list[str], priority_delta: dict[str, Any]) -> None:
    _append_open_ready_priority_focus_impl(operator_focus, priority_delta)


def _append_open_ready_governance_focus(operator_focus: list[str], governance_delta: dict[str, Any]) -> None:
    _append_open_ready_governance_focus_impl(operator_focus, governance_delta)


def _append_open_ready_replay_focus(operator_focus: list[str], replay_delta: dict[str, Any]) -> None:
    _append_open_ready_replay_focus_impl(operator_focus, replay_delta)


def _append_open_ready_frontier_focus(operator_focus: list[str], delta: dict[str, Any], *, label: str, added_key: str, status_label: str) -> None:
    _append_open_ready_frontier_focus_impl(operator_focus, delta, label=label, added_key=added_key, status_label=status_label)


def _append_open_ready_action_focus(operator_focus: list[str], delta_sections: dict[str, Any]) -> None:
    _append_open_ready_action_focus_impl(operator_focus, delta_sections)


def _append_open_ready_score_fail_focus(operator_focus: list[str], score_fail_delta: dict[str, Any]) -> None:
    _append_open_ready_score_fail_focus_impl(operator_focus, score_fail_delta)


def _append_open_ready_stability_focus(operator_focus: list[str]) -> None:
    _append_open_ready_stability_focus_impl(operator_focus)


def _build_open_ready_operator_focus(comparison_basis: str, comparison_scope: str, delta_sections: dict[str, Any]) -> list[str]:
    return _build_open_ready_operator_focus_impl(comparison_basis, comparison_scope, delta_sections)


def _resolve_open_ready_overall_delta_verdict(comparison_basis: str, delta_sections: dict[str, Any]) -> str:
    return _resolve_open_ready_overall_delta_verdict_impl(comparison_basis, delta_sections)


def _build_open_ready_material_change_anchor(
    *,
    current_payload: dict[str, Any],
    reports_root: str | Path,
    current_nightly_json_path: str | Path,
    historical_payload_candidates: list[tuple[dict[str, Any], str | None]] | None,
    enable_material_anchor: bool,
    comparison_scope: str,
    overall_delta_verdict: str,
    operator_focus: list[str],
) -> dict[str, Any]:
    return _build_open_ready_material_change_anchor_impl(
        current_payload=current_payload,
        reports_root=reports_root,
        current_nightly_json_path=current_nightly_json_path,
        historical_payload_candidates=historical_payload_candidates,
        enable_material_anchor=enable_material_anchor,
        comparison_scope=comparison_scope,
        overall_delta_verdict=overall_delta_verdict,
        operator_focus=operator_focus,
        build_material_change_anchor=_build_material_change_anchor,
        append_open_ready_material_anchor_focus=_append_open_ready_material_anchor_focus,
    )


def _should_build_open_ready_material_anchor(
    *,
    historical_payload_candidates: list[tuple[dict[str, Any], str | None]] | None,
    enable_material_anchor: bool,
    comparison_scope: str,
    overall_delta_verdict: str,
) -> bool:
    return _should_build_open_ready_material_anchor_impl(
        historical_payload_candidates=historical_payload_candidates,
        enable_material_anchor=enable_material_anchor,
        comparison_scope=comparison_scope,
        overall_delta_verdict=overall_delta_verdict,
    )


def _append_open_ready_material_anchor_focus(operator_focus: list[str], material_change_anchor: dict[str, Any]) -> None:
    _append_open_ready_material_anchor_focus_impl(operator_focus, material_change_anchor)


def _build_open_ready_source_paths(
    *,
    current_payload: dict[str, Any],
    current_nightly_json_path: str | Path,
    previous_payload: dict[str, Any],
    previous_payload_path: str | None,
    previous_report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return _build_open_ready_source_paths_impl(
        current_payload=current_payload,
        current_nightly_json_path=current_nightly_json_path,
        previous_payload=previous_payload,
        previous_payload_path=previous_payload_path,
        previous_report_snapshot=previous_report_snapshot,
    )


def _build_current_open_ready_source_paths(latest_btst_snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_priority_board_json": latest_btst_snapshot.get("priority_board_json_path"),
        "current_catalyst_theme_frontier_markdown": latest_btst_snapshot.get("catalyst_theme_frontier_markdown_path"),
        "current_score_fail_frontier_markdown": latest_btst_snapshot.get("score_fail_frontier_markdown_path"),
        "current_score_fail_recurring_markdown": latest_btst_snapshot.get("score_fail_recurring_markdown_path"),
    }


def _build_previous_open_ready_source_paths(
    previous_payload: dict[str, Any],
    previous_btst_snapshot: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    if previous_payload:
        return {
            "previous_priority_board_json": previous_btst_snapshot.get("priority_board_json_path"),
            "previous_catalyst_theme_frontier_markdown": previous_btst_snapshot.get("catalyst_theme_frontier_markdown_path"),
            "previous_score_fail_frontier_markdown": previous_btst_snapshot.get("score_fail_frontier_markdown_path"),
            "previous_score_fail_recurring_markdown": previous_btst_snapshot.get("score_fail_recurring_markdown_path"),
        }
    return {
        "previous_priority_board_json": previous_report_snapshot.get("priority_board_json_path"),
        "previous_catalyst_theme_frontier_markdown": previous_report_snapshot.get("catalyst_theme_frontier_markdown_path"),
        "previous_score_fail_frontier_markdown": None,
        "previous_score_fail_recurring_markdown": None,
    }


def _build_open_ready_delta_analysis(
    *,
    current_payload: dict[str, Any],
    latest_btst_run: dict[str, Any],
    previous_reference: dict[str, Any],
    comparison_basis: str,
    comparison_scope: str,
    overall_delta_verdict: str,
    operator_focus: list[str],
    delta_sections: dict[str, Any],
    material_change_anchor: dict[str, Any],
    source_paths: dict[str, Any],
) -> dict[str, Any]:
    return _build_open_ready_delta_analysis_impl(
        current_payload=current_payload,
        latest_btst_run=latest_btst_run,
        previous_reference=previous_reference,
        comparison_basis=comparison_basis,
        comparison_scope=comparison_scope,
        overall_delta_verdict=overall_delta_verdict,
        operator_focus=operator_focus,
        delta_sections=delta_sections,
        material_change_anchor=material_change_anchor,
        source_paths=source_paths,
    )


def _build_open_ready_delta_analysis_sections(delta_sections: dict[str, Any]) -> dict[str, Any]:
    return {
        "priority_delta": delta_sections["priority_delta"],
        "catalyst_frontier_delta": delta_sections["catalyst_frontier_delta"],
        "score_fail_frontier_delta": delta_sections["score_fail_frontier_delta"],
        "top_priority_action_delta": delta_sections["top_priority_action_delta"],
        "selected_outcome_contract_delta": delta_sections["selected_outcome_contract_delta"],
        "carryover_peer_proof_delta": delta_sections["carryover_peer_proof_delta"],
        "carryover_promotion_gate_delta": delta_sections["carryover_promotion_gate_delta"],
        "governance_delta": delta_sections["governance_delta"],
        "replay_delta": delta_sections["replay_delta"],
    }


def build_btst_open_ready_delta_payload(
    current_payload: dict[str, Any],
    *,
    reports_root: str | Path,
    current_nightly_json_path: str | Path,
    previous_payload: dict[str, Any] | None = None,
    previous_payload_path: str | None = None,
    historical_payload_candidates: list[tuple[dict[str, Any], str | None]] | None = None,
    enable_material_anchor: bool = True,
) -> dict[str, Any]:
    return _build_btst_open_ready_delta_payload_impl(
        current_payload,
        reports_root=reports_root,
        current_nightly_json_path=current_nightly_json_path,
        previous_payload=previous_payload,
        previous_payload_path=previous_payload_path,
        historical_payload_candidates=historical_payload_candidates,
        enable_material_anchor=enable_material_anchor,
        build_open_ready_delta_context=_build_open_ready_delta_context,
        resolve_open_ready_comparison_scope=_resolve_open_ready_comparison_scope,
        build_open_ready_deltas=_build_open_ready_deltas,
        build_open_ready_operator_focus=_build_open_ready_operator_focus,
        resolve_open_ready_overall_delta_verdict=_resolve_open_ready_overall_delta_verdict,
        build_open_ready_material_change_anchor=_build_open_ready_material_change_anchor,
        build_open_ready_source_paths=_build_open_ready_source_paths,
        build_open_ready_delta_analysis=_build_open_ready_delta_analysis,
    )


def _build_open_ready_delta_context(
    *,
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any] | None,
    reports_root: str | Path,
) -> dict[str, Any]:
    return _build_open_ready_delta_context_impl(
        current_payload=current_payload,
        previous_payload=previous_payload,
        reports_root=reports_root,
        resolve_previous_context=_resolve_open_ready_previous_context,
    )


def _append_open_ready_overview_markdown(
    lines: list[str],
    payload: dict[str, Any],
    current_reference: dict[str, Any],
    previous_reference: dict[str, Any],
) -> None:
    _append_open_ready_overview_markdown_impl(lines, payload, current_reference, previous_reference)


def _append_open_ready_overview_fields(
    lines: list[str],
    payload: dict[str, Any],
    current_reference: dict[str, Any],
    previous_reference: dict[str, Any],
) -> None:
    _append_open_ready_overview_fields_impl(lines, payload, current_reference, previous_reference)


def _append_open_ready_operator_focus_markdown(lines: list[str], operator_focus: list[Any]) -> None:
    _append_open_ready_operator_focus_markdown_impl(lines, operator_focus)


def _append_material_change_anchor_markdown(lines: list[str], anchor: dict[str, Any], output_parent: Path) -> None:
    _append_material_change_anchor_markdown_impl(lines, anchor, output_parent, relative_link=_relative_link)


def _append_material_change_anchor_metadata(lines: list[str], anchor: dict[str, Any], output_parent: Path) -> None:
    _append_material_change_anchor_metadata_impl(lines, anchor, output_parent, relative_link=_relative_link)


def _append_material_change_anchor_focus_markdown(lines: list[str], operator_focus: list[Any]) -> None:
    _append_material_change_anchor_focus_markdown_impl(lines, operator_focus)


def _append_priority_delta_list(
    lines: list[str],
    items: list[Any],
    formatter: Callable[[Any], str],
) -> None:
    _append_priority_delta_list_impl(lines, items, formatter)


def _append_priority_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_priority_delta_markdown_impl(lines, delta)


def _append_priority_membership_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_priority_membership_markdown_impl(lines, delta)


def _append_priority_change_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_priority_change_markdown_impl(lines, delta)


def _append_priority_guardrail_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_priority_guardrail_markdown_impl(lines, delta)


def _append_catalyst_frontier_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_catalyst_frontier_delta_markdown_impl(lines, delta)


def _append_catalyst_frontier_delta_summary(lines: list[str], delta: dict[str, Any]) -> None:
    _append_catalyst_frontier_delta_summary_impl(lines, delta)


def _append_catalyst_frontier_delta_tickers(lines: list[str], delta: dict[str, Any]) -> None:
    _append_catalyst_frontier_delta_tickers_impl(lines, delta)


def _append_score_fail_frontier_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_score_fail_frontier_delta_markdown_impl(lines, delta)


def _append_score_fail_frontier_delta_summary(lines: list[str], delta: dict[str, Any]) -> None:
    _append_score_fail_frontier_delta_summary_impl(lines, delta)


def _append_score_fail_frontier_delta_tickers(lines: list[str], delta: dict[str, Any]) -> None:
    _append_score_fail_frontier_delta_tickers_impl(lines, delta)


def _append_top_priority_action_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_top_priority_action_delta_markdown_impl(lines, delta)


def _append_selected_outcome_contract_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_selected_outcome_contract_delta_markdown_impl(lines, delta)


def _append_carryover_peer_proof_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_carryover_peer_proof_delta_markdown_impl(lines, delta)


def _append_carryover_promotion_gate_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_carryover_promotion_gate_delta_markdown_impl(lines, delta)


def _append_governance_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_governance_delta_markdown_impl(lines, delta)


def _build_governance_lane_delta_markdown(item: dict[str, Any]) -> str:
    return _build_governance_lane_delta_markdown_impl(item)


def _collect_governance_lane_extra_segments(item: dict[str, Any]) -> list[str]:
    return _collect_governance_lane_extra_segments_impl(item)


def _append_replay_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    _append_replay_delta_markdown_impl(lines, delta)


def _append_open_ready_fast_links_markdown(lines: list[str], source_paths: dict[str, Any], output_parent: Path) -> None:
    _append_open_ready_fast_links_markdown_impl(lines, source_paths, output_parent, relative_link=_relative_link)


def _build_nightly_refresh_status(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "btst_window_evidence_refresh": dict(manifest.get("btst_window_evidence_refresh") or {}).get("status"),
        "candidate_entry_shadow_refresh": dict(manifest.get("candidate_entry_shadow_refresh") or {}).get("status"),
        "btst_score_fail_frontier_refresh": dict(manifest.get("btst_score_fail_frontier_refresh") or {}).get("status"),
        "btst_governance_synthesis_refresh": dict(manifest.get("btst_governance_synthesis_refresh") or {}).get("status"),
        "btst_governance_validation_refresh": dict(manifest.get("btst_governance_validation_refresh") or {}).get("status"),
        "btst_replay_cohort_refresh": dict(manifest.get("btst_replay_cohort_refresh") or {}).get("status"),
        "btst_independent_window_monitor_refresh": dict(manifest.get("btst_independent_window_monitor_refresh") or {}).get("status"),
        "btst_tradeable_opportunity_pool_refresh": dict(manifest.get("btst_tradeable_opportunity_pool_refresh") or {}).get("status"),
    }


def _build_nightly_recommended_reading_order(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return _build_nightly_recommended_reading_order_impl(manifest, entry_by_id=_entry_by_id)


def _build_nightly_source_paths(manifest: dict[str, Any], latest_btst_snapshot: dict[str, Any]) -> dict[str, Any]:
    return _build_nightly_source_paths_impl(
        manifest,
        latest_btst_snapshot,
        entry_by_id=_entry_by_id,
        reports_dir=REPORTS_DIR,
    )


def _build_nightly_control_tower_analysis(
    manifest: dict[str, Any],
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    effective_brief_recommendation: Any,
    recommended_reading_order: list[dict[str, Any]],
    source_paths: dict[str, Any],
) -> dict[str, Any]:
    return _build_nightly_control_tower_analysis_impl(
        manifest,
        latest_btst_snapshot,
        control_tower_snapshot,
        replay_cohort_snapshot,
        effective_brief_recommendation,
        recommended_reading_order,
        source_paths,
        build_nightly_refresh_status=_build_nightly_refresh_status,
        timestamp_factory=lambda: datetime.now().isoformat(timespec="seconds"),
    )


def render_btst_open_ready_delta_markdown(payload: dict[str, Any], *, output_parent: str | Path) -> str:
    return _render_btst_open_ready_delta_markdown_impl(
        payload,
        output_parent=output_parent,
        relative_link=_relative_link,
    )


def _surface_zero_executable_blocked_recommendation(
    latest_btst_snapshot: dict[str, Any], recommendation: Any
) -> Any:
    brief_summary = dict(latest_btst_snapshot.get("brief_summary") or {})
    if int(brief_summary.get("short_trade_selected_count") or 0) > 0:
        return recommendation
    blocked_count = int(brief_summary.get("execution_blocked_candidate_count") or 0)
    if blocked_count <= 0:
        return recommendation
    blocked_tickers = [
        str(ticker)
        for ticker in list(brief_summary.get("execution_blocked_tickers") or [])
        if str(ticker or "").strip()
    ]
    preview = ", ".join(blocked_tickers[:3])
    suffix = " 等" if len(blocked_tickers) > 3 else ""
    blocked_message = (
        f"当前 formal BTST 执行名单为空；{preview}{suffix} 已被 halt/block/prior gate 拦截，只保留非执行观察层。"
        if preview
        else "当前 formal BTST 执行名单为空；halt/block/prior gate 仍未解除，只保留非执行观察层。"
    )
    if isinstance(recommendation, str) and recommendation.lstrip().startswith("当前 formal BTST 执行名单为空；"):
        return recommendation
    if not recommendation:
        return blocked_message
    return f"{blocked_message} {recommendation}"


def build_btst_nightly_control_tower_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    latest_btst_snapshot = _extract_latest_btst_snapshot(manifest)
    control_tower_snapshot = _extract_control_tower_snapshot(manifest)
    control_tower_snapshot["next_actions"] = _prioritize_control_tower_next_actions(latest_btst_snapshot, control_tower_snapshot)
    replay_cohort_snapshot = _extract_replay_cohort_snapshot(manifest)
    default_merge_review_summary = dict(control_tower_snapshot.get("default_merge_review_summary") or {})
    default_merge_review_ready = (
        str(default_merge_review_summary.get("merge_review_verdict") or "").strip() == "ready_for_default_btst_merge_review"
    )
    effective_brief_recommendation = (
        default_merge_review_summary.get("recommendation")
        if default_merge_review_ready and default_merge_review_summary.get("recommendation")
        else latest_btst_snapshot.get("brief_recommendation") or default_merge_review_summary.get("recommendation")
    )
    effective_brief_recommendation = _surface_zero_executable_blocked_recommendation(
        latest_btst_snapshot, effective_brief_recommendation
    )
    recommended_reading_order = _build_nightly_recommended_reading_order(manifest)
    source_paths = _build_nightly_source_paths(manifest, latest_btst_snapshot)
    return _build_nightly_control_tower_analysis(
        manifest,
        latest_btst_snapshot,
        control_tower_snapshot,
        replay_cohort_snapshot,
        effective_brief_recommendation,
        recommended_reading_order,
        source_paths,
    )



def _append_nightly_overview_candidate_pool_priority_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    branch_experiment_queue = list(control_tower_snapshot.get("candidate_pool_recall_priority_handoff_branch_experiment_queue") or [])
    lines.append("- candidate_pool_recall_priority_handoff_branch_experiment_queue: structured_summary")
    lines.append(f"- candidate_pool_recall_priority_handoff_branch_experiment_queue_count: {len(branch_experiment_queue)}")
    for experiment in branch_experiment_queue[:3]:
        lines.append(f"- candidate_pool_recall_branch_experiment: task_id={experiment.get('task_id')} handoff={experiment.get('priority_handoff')} readiness={experiment.get('prototype_readiness')} tickers={experiment.get('tickers')}")
        lines.append(f"  prototype_summary: {experiment.get('prototype_summary')}")
        lines.append(f"  evaluation_summary: {experiment.get('evaluation_summary')}")
        lines.append(f"  guardrail_summary: {experiment.get('guardrail_summary')}")
    lines.append(f"- candidate_pool_branch_priority_board_status: {control_tower_snapshot.get('candidate_pool_branch_priority_board_status')}")
    lines.append(f"- candidate_pool_branch_priority_alignment_status: {control_tower_snapshot.get('candidate_pool_branch_priority_alignment_status')}")
    if control_tower_snapshot.get("candidate_pool_branch_priority_alignment_summary"):
        lines.append(f"- candidate_pool_branch_priority_alignment_summary: {control_tower_snapshot.get('candidate_pool_branch_priority_alignment_summary')}")
    for row in list(control_tower_snapshot.get("candidate_pool_branch_priority_board_rows") or [])[:3]:
        lines.append(f"- candidate_pool_branch_priority: handoff={row.get('priority_handoff')} readiness={row.get('prototype_readiness')} execution_priority_rank={row.get('execution_priority_rank')} tickers={row.get('tickers')}")
    lines.append(f"- candidate_pool_lane_objective_support_status: {control_tower_snapshot.get('candidate_pool_lane_objective_support_status')}")
    for row in list(control_tower_snapshot.get("candidate_pool_lane_objective_support_rows") or [])[:3]:
        lines.append(f"- candidate_pool_lane_objective_support: handoff={row.get('priority_handoff')} verdict={row.get('support_verdict')} closed_cycle_count={row.get('closed_cycle_count')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')}")


def _append_nightly_overview_candidate_pool_corridor_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    lines.append(f"- candidate_pool_corridor_validation_pack_status: {control_tower_snapshot.get('candidate_pool_corridor_validation_pack_status')}")
    corridor_validation_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_validation_pack_summary") or {})
    if corridor_validation_summary:
        lines.append(
            f"- candidate_pool_corridor_validation_pack_summary: pack_status={corridor_validation_summary.get('pack_status')} primary_validation_ticker={corridor_validation_summary.get('primary_validation_ticker')} promotion_readiness_status={corridor_validation_summary.get('promotion_readiness_status')} parallel_watch_tickers={corridor_validation_summary.get('parallel_watch_tickers')}"
        )
    lines.append(f"- candidate_pool_corridor_shadow_pack_status: {control_tower_snapshot.get('candidate_pool_corridor_shadow_pack_status')}")
    corridor_shadow_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_shadow_pack_summary") or {})
    if corridor_shadow_summary:
        lines.append(f"- candidate_pool_corridor_shadow_pack_summary: shadow_status={corridor_shadow_summary.get('shadow_status')} primary_shadow_replay={corridor_shadow_summary.get('primary_shadow_replay')} parallel_watch_tickers={corridor_shadow_summary.get('parallel_watch_tickers')}")
    lines.append(f"- candidate_pool_rebucket_shadow_pack_status: {control_tower_snapshot.get('candidate_pool_rebucket_shadow_pack_status')}")
    rebucket_experiment = dict(control_tower_snapshot.get("candidate_pool_rebucket_shadow_pack_experiment") or {})
    if rebucket_experiment:
        lines.append(f"- candidate_pool_rebucket_shadow_pack_experiment: handoff={rebucket_experiment.get('priority_handoff')} readiness={rebucket_experiment.get('prototype_readiness')} tickers={rebucket_experiment.get('tickers')}")
    lines.append(f"- candidate_pool_rebucket_objective_validation_status: {control_tower_snapshot.get('candidate_pool_rebucket_objective_validation_status')}")
    rebucket_validation_summary = dict(control_tower_snapshot.get("candidate_pool_rebucket_objective_validation_summary") or {})
    if rebucket_validation_summary:
        lines.append(f"- candidate_pool_rebucket_objective_validation_summary: validation_status={rebucket_validation_summary.get('validation_status')} support_verdict={rebucket_validation_summary.get('support_verdict')} mean_t_plus_2_return={rebucket_validation_summary.get('mean_t_plus_2_return')}")
    lines.append(f"- candidate_pool_rebucket_comparison_bundle_status: {control_tower_snapshot.get('candidate_pool_rebucket_comparison_bundle_status')}")
    rebucket_comparison_summary = dict(control_tower_snapshot.get("candidate_pool_rebucket_comparison_bundle_summary") or {})
    if rebucket_comparison_summary:
        lines.append(f"- candidate_pool_rebucket_comparison_bundle_summary: bundle_status={rebucket_comparison_summary.get('bundle_status')} structural_leader={rebucket_comparison_summary.get('structural_leader')} objective_leader={rebucket_comparison_summary.get('objective_leader')}")
    lines.append(f"- candidate_pool_lane_pair_board_status: {control_tower_snapshot.get('candidate_pool_lane_pair_board_status')}")
    lane_pair_board_summary = dict(control_tower_snapshot.get("candidate_pool_lane_pair_board_summary") or {})
    if lane_pair_board_summary:
        lines.append(f"- candidate_pool_lane_pair_board_summary: pair_status={lane_pair_board_summary.get('pair_status')} board_leader={lane_pair_board_summary.get('board_leader')} leader_lane_family={lane_pair_board_summary.get('leader_lane_family')} leader_governance_status={lane_pair_board_summary.get('leader_governance_status')} leader_governance_execution_quality={lane_pair_board_summary.get('leader_governance_execution_quality')} leader_governance_entry_timing_bias={lane_pair_board_summary.get('leader_governance_entry_timing_bias')} parallel_watch_ticker={lane_pair_board_summary.get('parallel_watch_ticker')} parallel_watch_governance_blocker={lane_pair_board_summary.get('parallel_watch_governance_blocker')} parallel_watch_same_source_sample_count={lane_pair_board_summary.get('parallel_watch_same_source_sample_count')} parallel_watch_next_close_positive_rate={lane_pair_board_summary.get('parallel_watch_next_close_positive_rate')} parallel_watch_next_close_return_mean={lane_pair_board_summary.get('parallel_watch_next_close_return_mean')}")



def _append_nightly_overview_candidate_pool_continuation_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    _append_nightly_overview_candidate_pool_continuation_markdown_impl(lines, control_tower_snapshot)


def _append_nightly_overview_candidate_pool_followup_tail_markdown(
    lines: list[str],
    control_tower_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    catalyst_theme_frontier_summary: dict[str, Any],
    score_fail_frontier_summary: dict[str, Any],
    llm_error_digest: dict[str, Any],
) -> None:
    _append_nightly_overview_candidate_pool_followup_tail_markdown_impl(
        lines,
        control_tower_snapshot,
        replay_cohort_snapshot,
        catalyst_theme_frontier_summary,
        score_fail_frontier_summary,
        llm_error_digest,
    )


def _append_nightly_overview_candidate_pool_followup_markdown(
    lines: list[str],
    control_tower_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    catalyst_theme_frontier_summary: dict[str, Any],
    score_fail_frontier_summary: dict[str, Any],
    llm_error_digest: dict[str, Any],
) -> None:
    _append_nightly_overview_candidate_pool_followup_markdown_impl(
        lines,
        control_tower_snapshot,
        replay_cohort_snapshot,
        catalyst_theme_frontier_summary,
        score_fail_frontier_summary,
        llm_error_digest,
    )


def _append_nightly_overview_markdown(
    lines: list[str],
    payload: dict[str, Any],
    latest_btst_run: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    catalyst_theme_frontier_summary: dict[str, Any],
    score_fail_frontier_summary: dict[str, Any],
    llm_error_digest: dict[str, Any],
) -> None:
    _append_nightly_overview_markdown_impl(
        lines,
        payload,
        latest_btst_run,
        control_tower_snapshot,
        replay_cohort_snapshot,
        catalyst_theme_frontier_summary,
        score_fail_frontier_summary,
        llm_error_digest,
        append_candidate_pool_priority=_append_nightly_overview_candidate_pool_priority_markdown,
        append_candidate_pool_corridor=_append_nightly_overview_candidate_pool_corridor_markdown,
        append_candidate_pool_followup=_append_nightly_overview_candidate_pool_followup_markdown,
    )


def _build_nightly_overview_header_lines(
    payload: dict[str, Any],
    latest_btst_run: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
) -> list[str]:
    return _build_nightly_overview_header_lines_impl(payload, latest_btst_run, control_tower_snapshot)


def _append_nightly_summary_markdown(
    lines: list[str],
    control_tower_snapshot: dict[str, Any],
    latest_priority_board_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    tradeable_opportunity_pool_summary: dict[str, Any],
    no_candidate_entry_action_board_summary: dict[str, Any],
    no_candidate_entry_replay_bundle_summary: dict[str, Any],
    no_candidate_entry_failure_dossier_summary: dict[str, Any],
    watchlist_recall_dossier_summary: dict[str, Any],
    candidate_pool_recall_dossier_summary: dict[str, Any],
    upstream_shadow_followup_overlay: dict[str, Any],
    catalyst_theme_frontier_summary: dict[str, Any],
    score_fail_frontier_summary: dict[str, Any],
    llm_error_digest: dict[str, Any],
) -> None:
    _append_nightly_summary_markdown_impl(
        lines,
        control_tower_snapshot,
        latest_priority_board_snapshot,
        replay_cohort_snapshot,
        tradeable_opportunity_pool_summary,
        no_candidate_entry_action_board_summary,
        no_candidate_entry_replay_bundle_summary,
        no_candidate_entry_failure_dossier_summary,
        watchlist_recall_dossier_summary,
        candidate_pool_recall_dossier_summary,
        upstream_shadow_followup_overlay,
        catalyst_theme_frontier_summary,
        score_fail_frontier_summary,
        llm_error_digest,
    )


def _build_nightly_summary_header_lines(
    *,
    control_tower_snapshot: dict[str, Any],
    latest_priority_board_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    tradeable_opportunity_pool_summary: dict[str, Any],
    no_candidate_entry_action_board_summary: dict[str, Any],
    no_candidate_entry_replay_bundle_summary: dict[str, Any],
    no_candidate_entry_failure_dossier_summary: dict[str, Any],
    watchlist_recall_dossier_summary: dict[str, Any],
    candidate_pool_recall_dossier_summary: dict[str, Any],
) -> list[str]:
    return _build_nightly_summary_header_lines_impl(
        control_tower_snapshot=control_tower_snapshot,
        latest_priority_board_snapshot=latest_priority_board_snapshot,
        replay_cohort_snapshot=replay_cohort_snapshot,
        tradeable_opportunity_pool_summary=tradeable_opportunity_pool_summary,
        no_candidate_entry_action_board_summary=no_candidate_entry_action_board_summary,
        no_candidate_entry_replay_bundle_summary=no_candidate_entry_replay_bundle_summary,
        no_candidate_entry_failure_dossier_summary=no_candidate_entry_failure_dossier_summary,
        watchlist_recall_dossier_summary=watchlist_recall_dossier_summary,
        candidate_pool_recall_dossier_summary=candidate_pool_recall_dossier_summary,
    )


def _append_latest_upstream_shadow_followup_overlay_markdown(lines: list[str], upstream_shadow_followup_overlay: dict[str, Any]) -> None:
    _append_latest_upstream_shadow_followup_overlay_markdown_impl(lines, upstream_shadow_followup_overlay)


def _append_control_tower_snapshot_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    _append_control_tower_snapshot_markdown_impl(lines, control_tower_snapshot)


def _build_control_tower_snapshot_header_lines(control_tower_snapshot: dict[str, Any]) -> list[str]:
    return _build_control_tower_snapshot_header_lines_impl(control_tower_snapshot)


def _append_rollout_lanes_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    _append_rollout_lanes_markdown_impl(lines, control_tower_snapshot)


def _append_independent_window_monitor_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    _append_independent_window_monitor_markdown_impl(lines, control_tower_snapshot)


def _append_tplus1_tplus2_objective_monitor_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    _append_tplus1_tplus2_objective_monitor_markdown_impl(lines, control_tower_snapshot)


def _append_tradeable_opportunity_pool_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    _append_tradeable_opportunity_pool_markdown_impl(lines, summary)


def _append_no_candidate_entry_action_board_markdown(lines: list[str], summary: dict[str, Any], overlay: dict[str, Any]) -> None:
    _append_no_candidate_entry_action_board_markdown_impl(lines, summary, overlay)


def _append_no_candidate_entry_replay_bundle_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    _append_no_candidate_entry_replay_bundle_markdown_impl(lines, summary)


def _append_no_candidate_entry_failure_dossier_markdown(lines: list[str], summary: dict[str, Any], overlay: dict[str, Any]) -> None:
    _append_no_candidate_entry_failure_dossier_markdown_impl(lines, summary, overlay)


def _append_watchlist_recall_dossier_markdown(lines: list[str], summary: dict[str, Any], overlay: dict[str, Any]) -> None:
    _append_watchlist_recall_dossier_markdown_impl(lines, summary, overlay)



def _append_candidate_pool_recall_priority_details_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    _append_candidate_pool_recall_priority_details_markdown_impl(lines, summary)


def _append_candidate_pool_recall_corridor_details_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    _append_candidate_pool_recall_corridor_details_markdown_impl(lines, summary)


def _append_candidate_pool_recall_followup_details_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    _append_candidate_pool_recall_followup_details_markdown_impl(lines, summary)


def _append_candidate_pool_recall_dossier_markdown(lines: list[str], summary: dict[str, Any], overlay: dict[str, Any]) -> None:
    _append_candidate_pool_recall_dossier_markdown_impl(lines, summary, overlay)


def _append_priority_board_snapshot_markdown(lines: list[str], snapshot: dict[str, Any]) -> None:
    _append_priority_board_snapshot_markdown_impl(lines, snapshot)


def _append_catalyst_theme_frontier_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    _append_catalyst_theme_frontier_markdown_impl(lines, summary)


def _append_score_fail_frontier_queue_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    _append_score_fail_frontier_queue_markdown_impl(lines, summary)


def _append_nightly_llm_health_markdown(lines: list[str], llm_error_digest: dict[str, Any]) -> None:
    _append_nightly_llm_health_markdown_impl(lines, llm_error_digest)


def _append_replay_cohort_snapshot_markdown(lines: list[str], replay_cohort_snapshot: dict[str, Any]) -> None:
    _append_replay_cohort_snapshot_markdown_impl(lines, replay_cohort_snapshot)


def _append_nightly_reading_order_markdown(lines: list[str], payload: dict[str, Any]) -> None:
    _append_nightly_reading_order_markdown_impl(lines, payload)


def _append_nightly_fast_links_markdown(lines: list[str], source_paths: dict[str, Any], output_parent: Path) -> None:
    _append_nightly_fast_links_markdown_impl(lines, source_paths, output_parent, relative_link=_relative_link)


def render_btst_nightly_control_tower_markdown(payload: dict[str, Any], *, output_parent: str | Path) -> str:
    return _render_btst_nightly_control_tower_markdown_impl(
        payload,
        output_parent=output_parent,
        build_render_context=_build_nightly_control_tower_render_context,
        append_overview=_append_nightly_overview_markdown,
        append_summary=_append_nightly_summary_markdown,
        append_followup_overlay=_append_latest_upstream_shadow_followup_overlay_markdown,
        append_control_tower_snapshot=_append_control_tower_snapshot_markdown,
        append_rollout_lanes=_append_rollout_lanes_markdown,
        append_independent_window_monitor=_append_independent_window_monitor_markdown,
        append_tplus1_tplus2_objective_monitor=_append_tplus1_tplus2_objective_monitor_markdown,
        append_tradeable_opportunity_pool=_append_tradeable_opportunity_pool_markdown,
        append_no_candidate_entry_action_board=_append_no_candidate_entry_action_board_markdown,
        append_no_candidate_entry_replay_bundle=_append_no_candidate_entry_replay_bundle_markdown,
        append_no_candidate_entry_failure_dossier=_append_no_candidate_entry_failure_dossier_markdown,
        append_watchlist_recall_dossier=_append_watchlist_recall_dossier_markdown,
        append_candidate_pool_recall_dossier=_append_candidate_pool_recall_dossier_markdown,
        append_priority_board_snapshot=_append_priority_board_snapshot_markdown,
        append_catalyst_theme_frontier=_append_catalyst_theme_frontier_markdown,
        append_score_fail_frontier_queue=_append_score_fail_frontier_queue_markdown,
        append_nightly_llm_health=_append_nightly_llm_health_markdown,
        append_replay_cohort_snapshot=_append_replay_cohort_snapshot_markdown,
        append_nightly_reading_order=_append_nightly_reading_order_markdown,
        append_nightly_fast_links=_append_nightly_fast_links_markdown,
    )


def _build_nightly_control_tower_render_context(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _build_nightly_control_tower_render_context_impl(payload)


def generate_btst_nightly_control_tower_artifacts(
    reports_root: str | Path,
    *,
    output_json: str | Path | None = None,
    output_md: str | Path | None = None,
    delta_output_json: str | Path | None = None,
    delta_output_md: str | Path | None = None,
    close_validation_output_json: str | Path | None = None,
    close_validation_output_md: str | Path | None = None,
    history_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _generate_btst_nightly_control_tower_artifacts_impl(
        reports_root,
        output_json=output_json,
        output_md=output_md,
        delta_output_json=delta_output_json,
        delta_output_md=delta_output_md,
        close_validation_output_json=close_validation_output_json,
        close_validation_output_md=close_validation_output_md,
        history_dir=history_dir,
        resolve_output_paths=_resolve_nightly_control_tower_output_paths,
        generate_reports_manifest_artifacts=generate_reports_manifest_artifacts,
        build_btst_nightly_control_tower_payload=build_btst_nightly_control_tower_payload,
        load_archived_nightly_payloads=_load_archived_nightly_payloads,
        build_btst_open_ready_delta_payload=build_btst_open_ready_delta_payload,
        render_btst_open_ready_delta_markdown=render_btst_open_ready_delta_markdown,
        render_btst_nightly_control_tower_markdown=render_btst_nightly_control_tower_markdown,
        generate_btst_latest_close_validation_artifacts=generate_btst_latest_close_validation_artifacts,
        archive_nightly_payload=_archive_nightly_payload,
    )


def _resolve_nightly_control_tower_output_paths(
    *,
    resolved_reports_root: Path,
    output_json: str | Path | None,
    output_md: str | Path | None,
    delta_output_json: str | Path | None,
    delta_output_md: str | Path | None,
    close_validation_output_json: str | Path | None,
    close_validation_output_md: str | Path | None,
    history_dir: str | Path | None,
) -> dict[str, Path]:
    return _resolve_nightly_control_tower_output_paths_impl(
        resolved_reports_root=resolved_reports_root,
        output_json=output_json,
        output_md=output_md,
        delta_output_json=delta_output_json,
        delta_output_md=delta_output_md,
        close_validation_output_json=close_validation_output_json,
        close_validation_output_md=close_validation_output_md,
        history_dir=history_dir,
        default_output_json=DEFAULT_OUTPUT_JSON,
        default_output_md=DEFAULT_OUTPUT_MD,
        default_delta_json=DEFAULT_DELTA_JSON,
        default_delta_md=DEFAULT_DELTA_MD,
        default_close_validation_json=DEFAULT_CLOSE_VALIDATION_JSON,
        default_close_validation_md=DEFAULT_CLOSE_VALIDATION_MD,
        default_history_dir=DEFAULT_HISTORY_DIR,
        reports_dir=REPORTS_DIR,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the BTST control tower stack and write a one-click nightly control tower artifact.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR), help="Reports root directory to scan")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON artifact path")
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD), help="Output Markdown artifact path")
    parser.add_argument("--delta-output-json", default=str(DEFAULT_DELTA_JSON), help="Output JSON path for the open-ready delta artifact")
    parser.add_argument("--delta-output-md", default=str(DEFAULT_DELTA_MD), help="Output Markdown path for the open-ready delta artifact")
    parser.add_argument("--close-validation-output-json", default=str(DEFAULT_CLOSE_VALIDATION_JSON), help="Output JSON path for the latest close validation artifact")
    parser.add_argument("--close-validation-output-md", default=str(DEFAULT_CLOSE_VALIDATION_MD), help="Output Markdown path for the latest close validation artifact")
    parser.add_argument("--history-dir", default=str(DEFAULT_HISTORY_DIR), help="Directory used to archive historical nightly control tower JSON snapshots")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = generate_btst_nightly_control_tower_artifacts(
        reports_root=args.reports_root,
        output_json=args.output_json,
        output_md=args.output_md,
        delta_output_json=args.delta_output_json,
        delta_output_md=args.delta_output_md,
        close_validation_output_json=args.close_validation_output_json,
        close_validation_output_md=args.close_validation_output_md,
        history_dir=args.history_dir,
    )
    print(f"btst_open_ready_delta_json={result['delta_json_path']}")
    print(f"btst_open_ready_delta_markdown={result['delta_markdown_path']}")
    print(f"btst_nightly_control_tower_json={result['json_path']}")
    print(f"btst_nightly_control_tower_markdown={result['markdown_path']}")
    print(f"btst_latest_close_validation_json={result['close_validation_json_path']}")
    print(f"btst_latest_close_validation_markdown={result['close_validation_markdown_path']}")
    print(f"btst_nightly_control_tower_manifest_json={result['manifest_json']}")
    print(f"btst_nightly_control_tower_manifest_markdown={result['manifest_markdown']}")


if __name__ == "__main__":
    main()
