from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


AppendOverview = Callable[[list[str], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]], None]
AppendSummary = Callable[[list[str], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]], None]
AppendSimple = Callable[[list[str], dict[str, Any]], None]
AppendOverlay = Callable[[list[str], dict[str, Any], dict[str, Any]], None]
AppendFastLinks = Callable[[list[str], dict[str, Any], Path], None]
AppendReadingOrder = Callable[[list[str], dict[str, Any]], None]


def build_nightly_control_tower_render_context(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest_btst_run = dict(payload.get("latest_btst_run") or {})
    control_tower_snapshot = dict(payload.get("control_tower_snapshot") or {})
    latest_priority_board_snapshot = dict(payload.get("latest_priority_board_snapshot") or {})
    replay_cohort_snapshot = dict(payload.get("replay_cohort_snapshot") or {})
    latest_btst_snapshot = dict(payload.get("latest_btst_snapshot") or {})
    return {
        "latest_btst_run": latest_btst_run,
        "control_tower_snapshot": control_tower_snapshot,
        "latest_priority_board_snapshot": latest_priority_board_snapshot,
        "replay_cohort_snapshot": replay_cohort_snapshot,
        "catalyst_theme_frontier_summary": dict(latest_btst_snapshot.get("catalyst_theme_frontier_summary") or {}),
        "score_fail_frontier_summary": dict(latest_btst_snapshot.get("score_fail_frontier_summary") or {}),
        "tradeable_opportunity_pool_summary": dict(control_tower_snapshot.get("tradeable_opportunity_pool") or {}),
        "no_candidate_entry_action_board_summary": dict(control_tower_snapshot.get("no_candidate_entry_action_board") or {}),
        "no_candidate_entry_replay_bundle_summary": dict(control_tower_snapshot.get("no_candidate_entry_replay_bundle") or {}),
        "no_candidate_entry_failure_dossier_summary": dict(control_tower_snapshot.get("no_candidate_entry_failure_dossier") or {}),
        "watchlist_recall_dossier_summary": dict(control_tower_snapshot.get("watchlist_recall_dossier") or {}),
        "candidate_pool_recall_dossier_summary": dict(control_tower_snapshot.get("candidate_pool_recall_dossier") or {}),
        "upstream_shadow_followup_overlay": dict(control_tower_snapshot.get("upstream_shadow_followup_overlay") or {}),
        "llm_error_digest": dict(latest_btst_snapshot.get("llm_error_digest") or {}),
        "source_paths": dict(payload.get("source_paths") or {}),
    }


def render_btst_nightly_control_tower_markdown(
    payload: dict[str, Any],
    *,
    output_parent: str | Path,
    build_render_context: Callable[[dict[str, Any]], dict[str, dict[str, Any]]],
    append_overview: AppendOverview,
    append_summary: AppendSummary,
    append_followup_overlay: AppendSimple,
    append_control_tower_snapshot: AppendSimple,
    append_rollout_lanes: AppendSimple,
    append_independent_window_monitor: AppendSimple,
    append_tplus1_tplus2_objective_monitor: AppendSimple,
    append_tradeable_opportunity_pool: AppendSimple,
    append_no_candidate_entry_action_board: AppendOverlay,
    append_no_candidate_entry_replay_bundle: AppendSimple,
    append_no_candidate_entry_failure_dossier: AppendOverlay,
    append_watchlist_recall_dossier: AppendOverlay,
    append_candidate_pool_recall_dossier: AppendOverlay,
    append_priority_board_snapshot: AppendSimple,
    append_catalyst_theme_frontier: AppendSimple,
    append_score_fail_frontier_queue: AppendSimple,
    append_nightly_llm_health: AppendSimple,
    append_replay_cohort_snapshot: AppendSimple,
    append_nightly_reading_order: AppendReadingOrder,
    append_nightly_fast_links: AppendFastLinks,
) -> str:
    resolved_output_parent = Path(output_parent).expanduser().resolve()
    render_context = build_render_context(payload)
    latest_btst_run = render_context["latest_btst_run"]
    control_tower_snapshot = render_context["control_tower_snapshot"]
    latest_priority_board_snapshot = render_context["latest_priority_board_snapshot"]
    replay_cohort_snapshot = render_context["replay_cohort_snapshot"]
    catalyst_theme_frontier_summary = render_context["catalyst_theme_frontier_summary"]
    score_fail_frontier_summary = render_context["score_fail_frontier_summary"]
    tradeable_opportunity_pool_summary = render_context["tradeable_opportunity_pool_summary"]
    no_candidate_entry_action_board_summary = render_context["no_candidate_entry_action_board_summary"]
    no_candidate_entry_replay_bundle_summary = render_context["no_candidate_entry_replay_bundle_summary"]
    no_candidate_entry_failure_dossier_summary = render_context["no_candidate_entry_failure_dossier_summary"]
    watchlist_recall_dossier_summary = render_context["watchlist_recall_dossier_summary"]
    candidate_pool_recall_dossier_summary = render_context["candidate_pool_recall_dossier_summary"]
    upstream_shadow_followup_overlay = render_context["upstream_shadow_followup_overlay"]
    llm_error_digest = render_context["llm_error_digest"]
    source_paths = render_context["source_paths"]

    lines: list[str] = []
    lines.append("# BTST Nightly Control Tower")
    lines.append("")
    append_overview(
        lines,
        payload,
        latest_btst_run,
        control_tower_snapshot,
        replay_cohort_snapshot,
        catalyst_theme_frontier_summary,
        score_fail_frontier_summary,
        llm_error_digest,
    )
    append_summary(
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
    append_followup_overlay(lines, upstream_shadow_followup_overlay)
    append_control_tower_snapshot(lines, control_tower_snapshot)
    append_rollout_lanes(lines, control_tower_snapshot)
    append_independent_window_monitor(lines, control_tower_snapshot)
    append_tplus1_tplus2_objective_monitor(lines, control_tower_snapshot)
    append_tradeable_opportunity_pool(lines, tradeable_opportunity_pool_summary)
    append_no_candidate_entry_action_board(lines, no_candidate_entry_action_board_summary, upstream_shadow_followup_overlay)
    append_no_candidate_entry_replay_bundle(lines, no_candidate_entry_replay_bundle_summary)
    append_no_candidate_entry_failure_dossier(lines, no_candidate_entry_failure_dossier_summary, upstream_shadow_followup_overlay)
    append_watchlist_recall_dossier(lines, watchlist_recall_dossier_summary, upstream_shadow_followup_overlay)
    append_candidate_pool_recall_dossier(lines, candidate_pool_recall_dossier_summary, upstream_shadow_followup_overlay)
    append_priority_board_snapshot(lines, latest_priority_board_snapshot)
    append_catalyst_theme_frontier(lines, catalyst_theme_frontier_summary)
    append_score_fail_frontier_queue(lines, score_fail_frontier_summary)
    append_nightly_llm_health(lines, llm_error_digest)
    append_replay_cohort_snapshot(lines, replay_cohort_snapshot)
    append_nightly_reading_order(lines, payload)
    append_nightly_fast_links(lines, source_paths, resolved_output_parent)
    return "\n".join(lines).rstrip() + "\n"
