from __future__ import annotations

from typing import Any, Callable


AppendOverviewSection = Callable[[list[str], dict[str, Any]], None]
AppendOverviewFollowup = Callable[[list[str], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]], None]


def append_nightly_overview_markdown(
    lines: list[str],
    payload: dict[str, Any],
    latest_btst_run: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    catalyst_theme_frontier_summary: dict[str, Any],
    score_fail_frontier_summary: dict[str, Any],
    llm_error_digest: dict[str, Any],
    *,
    append_candidate_pool_priority: AppendOverviewSection,
    append_candidate_pool_corridor: AppendOverviewSection,
    append_candidate_pool_followup: AppendOverviewFollowup,
) -> None:
    lines.append("## Overview")
    lines.extend(build_nightly_overview_header_lines(payload, latest_btst_run, control_tower_snapshot))
    append_candidate_pool_priority(lines, control_tower_snapshot)
    append_candidate_pool_corridor(lines, control_tower_snapshot)
    append_candidate_pool_followup(
        lines,
        control_tower_snapshot,
        replay_cohort_snapshot,
        catalyst_theme_frontier_summary,
        score_fail_frontier_summary,
        llm_error_digest,
    )
    lines.append("")


def build_nightly_overview_header_lines(
    payload: dict[str, Any],
    latest_btst_run: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
) -> list[str]:
    return [
        f"- generated_at: {payload.get('generated_at')}",
        f"- latest_btst_report_dir: {latest_btst_run.get('report_dir')}",
        f"- latest_trade_date: {latest_btst_run.get('trade_date')}",
        f"- latest_next_trade_date: {latest_btst_run.get('next_trade_date')}",
        f"- latest_selection_target: {latest_btst_run.get('selection_target')}",
        f"- governance_verdict: {control_tower_snapshot.get('overall_verdict')}",
        f"- waiting_lane_count: {control_tower_snapshot.get('waiting_lane_count')}",
        f"- ready_lane_count: {control_tower_snapshot.get('ready_lane_count')}",
        f"- independent_window_ready_lane_count: {control_tower_snapshot.get('independent_window_ready_lane_count')}",
        f"- independent_window_waiting_lane_count: {control_tower_snapshot.get('independent_window_waiting_lane_count')}",
        f"- tplus1_tplus2_tradeable_positive_rate: {control_tower_snapshot.get('tplus1_tplus2_tradeable_positive_rate')}",
        f"- tplus1_tplus2_tradeable_return_hit_rate: {control_tower_snapshot.get('tplus1_tplus2_tradeable_return_hit_rate')}",
        f"- tplus1_tplus2_tradeable_mean_return: {control_tower_snapshot.get('tplus1_tplus2_tradeable_mean_return')}",
        f"- tplus1_tplus2_tradeable_verdict: {control_tower_snapshot.get('tplus1_tplus2_tradeable_verdict')}",
        f"- tradeable_opportunity_pool_count: {control_tower_snapshot.get('tradeable_opportunity_pool_count')}",
        f"- tradeable_opportunity_capture_rate: {control_tower_snapshot.get('tradeable_opportunity_capture_rate')}",
        f"- tradeable_opportunity_selected_or_near_miss_rate: {control_tower_snapshot.get('tradeable_opportunity_selected_or_near_miss_rate')}",
        f"- tradeable_opportunity_top_kill_switches: {control_tower_snapshot.get('tradeable_opportunity_top_kill_switches')}",
        f"- no_candidate_entry_priority_queue_count: {control_tower_snapshot.get('no_candidate_entry_priority_queue_count')}",
        f"- no_candidate_entry_priority_tickers_historical: {control_tower_snapshot.get('no_candidate_entry_priority_tickers')}",
        f"- no_candidate_entry_priority_tickers_active: {control_tower_snapshot.get('active_no_candidate_entry_priority_tickers')}",
        f"- no_candidate_entry_recall_probe_tickers: {control_tower_snapshot.get('no_candidate_entry_recall_probe_tickers')}",
        f"- no_candidate_entry_failure_class_counts: {control_tower_snapshot.get('no_candidate_entry_failure_class_counts')}",
        f"- no_candidate_entry_handoff_stage_counts: {control_tower_snapshot.get('no_candidate_entry_handoff_stage_counts')}",
        f"- no_candidate_entry_absent_from_watchlist_tickers_historical: {control_tower_snapshot.get('no_candidate_entry_absent_from_watchlist_tickers')}",
        f"- no_candidate_entry_absent_from_watchlist_tickers_active: {control_tower_snapshot.get('active_no_candidate_entry_absent_from_watchlist_tickers')}",
        f"- no_candidate_entry_watchlist_handoff_gap_tickers: {control_tower_snapshot.get('no_candidate_entry_watchlist_handoff_gap_tickers')}",
        f"- no_candidate_entry_upstream_absence_tickers: {control_tower_snapshot.get('no_candidate_entry_upstream_absence_tickers')}",
        f"- watchlist_recall_stage_counts: {control_tower_snapshot.get('watchlist_recall_stage_counts')}",
        f"- watchlist_recall_absent_from_candidate_pool_tickers_historical: {control_tower_snapshot.get('watchlist_recall_absent_from_candidate_pool_tickers')}",
        f"- watchlist_recall_absent_from_candidate_pool_tickers_active: {control_tower_snapshot.get('active_watchlist_recall_absent_from_candidate_pool_tickers')}",
        f"- watchlist_recall_candidate_pool_layer_b_gap_tickers: {control_tower_snapshot.get('watchlist_recall_candidate_pool_layer_b_gap_tickers')}",
        f"- watchlist_recall_layer_b_watchlist_gap_tickers: {control_tower_snapshot.get('watchlist_recall_layer_b_watchlist_gap_tickers')}",
        f"- candidate_pool_recall_stage_counts: {control_tower_snapshot.get('candidate_pool_recall_stage_counts')}",
        f"- candidate_pool_recall_dominant_stage: {control_tower_snapshot.get('candidate_pool_recall_dominant_stage')}",
        f"- candidate_pool_recall_top_stage_tickers: {control_tower_snapshot.get('candidate_pool_recall_top_stage_tickers')}",
        f"- candidate_pool_recall_truncation_frontier_summary: {control_tower_snapshot.get('candidate_pool_recall_truncation_frontier_summary')}",
        f"- candidate_pool_recall_dominant_ranking_driver: {control_tower_snapshot.get('candidate_pool_recall_dominant_ranking_driver')}",
        f"- candidate_pool_recall_dominant_liquidity_gap_mode: {control_tower_snapshot.get('candidate_pool_recall_dominant_liquidity_gap_mode')}",
        f"- candidate_pool_recall_focus_liquidity_profiles: {control_tower_snapshot.get('candidate_pool_recall_focus_liquidity_profiles')}",
        f"- candidate_pool_recall_shadow_visible_focus_tickers: {control_tower_snapshot.get('candidate_pool_recall_shadow_visible_focus_tickers')}",
        f"- candidate_pool_recall_shadow_visible_focus_profiles: {control_tower_snapshot.get('candidate_pool_recall_shadow_visible_focus_profiles')}",
        f"- active_candidate_pool_recall_shadow_visible_focus_tickers: {control_tower_snapshot.get('active_candidate_pool_recall_shadow_visible_focus_tickers')}",
        f"- active_candidate_pool_recall_shadow_visible_focus_profiles: {control_tower_snapshot.get('active_candidate_pool_recall_shadow_visible_focus_profiles')}",
        f"- candidate_pool_recall_priority_handoff_counts: {control_tower_snapshot.get('candidate_pool_recall_priority_handoff_counts')}",
        f"- candidate_pool_recall_priority_handoff_branch_diagnoses: {control_tower_snapshot.get('candidate_pool_recall_priority_handoff_branch_diagnoses')}",
        f"- candidate_pool_recall_priority_handoff_branch_mechanisms: {control_tower_snapshot.get('candidate_pool_recall_priority_handoff_branch_mechanisms')}",
    ]


def append_nightly_summary_markdown(
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
    lines.append("## Nightly Summary")
    lines.extend(
        build_nightly_summary_header_lines(
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
    )
    selected_outcome_refresh_summary = dict(control_tower_snapshot.get("selected_outcome_refresh_summary") or {})
    if selected_outcome_refresh_summary:
        lines.append(f"- selected_outcome_refresh_summary: focus_ticker={selected_outcome_refresh_summary.get('focus_ticker')} focus_cycle_status={selected_outcome_refresh_summary.get('focus_cycle_status')} focus_overall_contract_verdict={selected_outcome_refresh_summary.get('focus_overall_contract_verdict')}")
    carryover_multiday_continuation_audit_summary = dict(control_tower_snapshot.get("carryover_multiday_continuation_audit_summary") or {})
    if carryover_multiday_continuation_audit_summary:
        lines.append(f"- carryover_multiday_continuation_audit_summary: selected_ticker={carryover_multiday_continuation_audit_summary.get('selected_ticker')} selected_path_t2_bias_only={carryover_multiday_continuation_audit_summary.get('selected_path_t2_bias_only')} broad_family_only_multiday_unsupported={carryover_multiday_continuation_audit_summary.get('broad_family_only_multiday_unsupported')} aligned_peer_multiday_ready={carryover_multiday_continuation_audit_summary.get('aligned_peer_multiday_ready')}")
    carryover_aligned_peer_harvest_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_harvest_summary") or {})
    if carryover_aligned_peer_harvest_summary:
        lines.append(f"- carryover_aligned_peer_harvest_summary: focus_ticker={carryover_aligned_peer_harvest_summary.get('focus_ticker')} focus_status={carryover_aligned_peer_harvest_summary.get('focus_status')} fresh_open_cycle_tickers={carryover_aligned_peer_harvest_summary.get('fresh_open_cycle_tickers')}")
    carryover_peer_expansion_summary = dict(control_tower_snapshot.get("carryover_peer_expansion_summary") or {})
    if carryover_peer_expansion_summary:
        lines.append(f"- carryover_peer_expansion_summary: focus_ticker={carryover_peer_expansion_summary.get('focus_ticker')} focus_status={carryover_peer_expansion_summary.get('focus_status')} priority_expansion_tickers={carryover_peer_expansion_summary.get('priority_expansion_tickers')} watch_with_risk_tickers={carryover_peer_expansion_summary.get('watch_with_risk_tickers')}")
    carryover_aligned_peer_proof_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_proof_summary") or {})
    if carryover_aligned_peer_proof_summary:
        lines.append(f"- carryover_aligned_peer_proof_summary: focus_ticker={carryover_aligned_peer_proof_summary.get('focus_ticker')} focus_proof_verdict={carryover_aligned_peer_proof_summary.get('focus_proof_verdict')} focus_promotion_review_verdict={carryover_aligned_peer_proof_summary.get('focus_promotion_review_verdict')} ready_for_promotion_review_tickers={carryover_aligned_peer_proof_summary.get('ready_for_promotion_review_tickers')} risk_review_tickers={carryover_aligned_peer_proof_summary.get('risk_review_tickers')}")
    carryover_peer_promotion_gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})
    if carryover_peer_promotion_gate_summary:
        lines.append(f"- carryover_peer_promotion_gate_summary: focus_ticker={carryover_peer_promotion_gate_summary.get('focus_ticker')} focus_gate_verdict={carryover_peer_promotion_gate_summary.get('focus_gate_verdict')} default_expansion_status={carryover_peer_promotion_gate_summary.get('default_expansion_status')} ready_tickers={carryover_peer_promotion_gate_summary.get('ready_tickers')} blocked_open_tickers={carryover_peer_promotion_gate_summary.get('blocked_open_tickers')} pending_t_plus_2_tickers={carryover_peer_promotion_gate_summary.get('pending_t_plus_2_tickers')} pending_next_day_tickers={carryover_peer_promotion_gate_summary.get('pending_next_day_tickers')}")
    lines.append(f"- upstream_shadow_followup_overlay_recommendation: {control_tower_snapshot.get('upstream_shadow_followup_recommendation')}")
    if upstream_shadow_followup_overlay.get("validated_tickers"):
        lines.append(f"- upstream_backlog_interpretation_note: 以下 no-entry/watchlist/candidate-pool 建议仍是历史 backlog 画像；当前 active upstream recall 已收敛到 {upstream_shadow_followup_overlay.get('active_no_candidate_entry_priority_tickers')}。")
    lines.append(f"- candidate_pool_recall_dossier_truncation_frontier_summary: {candidate_pool_recall_dossier_summary.get('truncation_frontier_summary')}")
    lines.append(f"- catalyst_frontier_recommendation: {catalyst_theme_frontier_summary.get('recommendation')}")
    lines.append(f"- score_fail_frontier_recommendation: {score_fail_frontier_summary.get('recommendation')}")
    lines.append(f"- llm_recommendation: {llm_error_digest.get('recommendation')}")
    lines.append("")


def build_nightly_summary_header_lines(
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
    return [
        f"- control_tower_recommendation: {control_tower_snapshot.get('recommendation')}",
        f"- priority_board_headline: {latest_priority_board_snapshot.get('headline')}",
        f"- replay_recommendation: {replay_cohort_snapshot.get('recommendation')}",
        f"- tradeable_opportunity_recommendation: {tradeable_opportunity_pool_summary.get('recommendation')}",
        f"- no_candidate_entry_action_recommendation: {no_candidate_entry_action_board_summary.get('recommendation')}",
        f"- no_candidate_entry_replay_recommendation: {no_candidate_entry_replay_bundle_summary.get('recommendation')}",
        f"- no_candidate_entry_failure_dossier_recommendation: {no_candidate_entry_failure_dossier_summary.get('recommendation')}",
        f"- watchlist_recall_dossier_recommendation: {watchlist_recall_dossier_summary.get('recommendation')}",
        f"- candidate_pool_recall_dossier_recommendation: {candidate_pool_recall_dossier_summary.get('recommendation')}",
    ]


def append_latest_upstream_shadow_followup_overlay_markdown(lines: list[str], upstream_shadow_followup_overlay: dict[str, Any]) -> None:
    lines.append("## Latest Upstream Shadow Followup Overlay")
    lines.append(f"- status: {upstream_shadow_followup_overlay.get('status')}")
    lines.append(f"- report_dir: {upstream_shadow_followup_overlay.get('report_dir')}")
    lines.append(f"- trade_date: {upstream_shadow_followup_overlay.get('trade_date')}")
    lines.append(f"- validated_tickers: {upstream_shadow_followup_overlay.get('validated_tickers')}")
    lines.append(f"- near_miss_tickers: {upstream_shadow_followup_overlay.get('near_miss_tickers')}")
    lines.append(f"- rejected_profitability_tickers: {upstream_shadow_followup_overlay.get('rejected_profitability_tickers')}")
    lines.append(f"- decision_counts: {upstream_shadow_followup_overlay.get('decision_counts')}")
    lines.append(f"- active_no_candidate_entry_priority_tickers: {upstream_shadow_followup_overlay.get('active_no_candidate_entry_priority_tickers')}")
    lines.append(f"- active_absent_from_watchlist_tickers: {upstream_shadow_followup_overlay.get('active_absent_from_watchlist_tickers')}")
    lines.append(f"- active_watchlist_absent_from_candidate_pool_tickers: {upstream_shadow_followup_overlay.get('active_watchlist_absent_from_candidate_pool_tickers')}")
    lines.append(f"- active_upstream_handoff_focus_tickers: {upstream_shadow_followup_overlay.get('active_upstream_handoff_focus_tickers')}")
    lines.append(f"- recommendation: {upstream_shadow_followup_overlay.get('recommendation')}")
    for row in list(upstream_shadow_followup_overlay.get("rows") or [])[:3]:
        lines.append(f"- followup_row: ticker={row.get('ticker')} decision={row.get('decision')} downstream_bottleneck={row.get('downstream_bottleneck')} top_reasons={row.get('top_reasons')}")
    lines.append("")


def append_control_tower_snapshot_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    lines.append("## Control Tower Snapshot")
    lines.extend(build_control_tower_snapshot_header_lines(control_tower_snapshot))
    selected_outcome_refresh_summary = dict(control_tower_snapshot.get("selected_outcome_refresh_summary") or {})
    if selected_outcome_refresh_summary:
        lines.append(f"- selected_outcome_contract: focus_ticker={selected_outcome_refresh_summary.get('focus_ticker')} overall_contract_verdict={selected_outcome_refresh_summary.get('focus_overall_contract_verdict')} focus_cycle_status={selected_outcome_refresh_summary.get('focus_cycle_status')}")
    carryover_multiday_continuation_audit_summary = dict(control_tower_snapshot.get("carryover_multiday_continuation_audit_summary") or {})
    if carryover_multiday_continuation_audit_summary:
        lines.append(f"- carryover_multiday_contract: selected_ticker={carryover_multiday_continuation_audit_summary.get('selected_ticker')} selected_path_t2_bias_only={carryover_multiday_continuation_audit_summary.get('selected_path_t2_bias_only')} broad_family_only_multiday_unsupported={carryover_multiday_continuation_audit_summary.get('broad_family_only_multiday_unsupported')}")
    carryover_aligned_peer_harvest_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_harvest_summary") or {})
    if carryover_aligned_peer_harvest_summary:
        lines.append(f"- carryover_peer_harvest_focus: focus_ticker={carryover_aligned_peer_harvest_summary.get('focus_ticker')} focus_status={carryover_aligned_peer_harvest_summary.get('focus_status')} fresh_open_cycle_tickers={carryover_aligned_peer_harvest_summary.get('fresh_open_cycle_tickers')}")
    carryover_peer_expansion_summary = dict(control_tower_snapshot.get("carryover_peer_expansion_summary") or {})
    if carryover_peer_expansion_summary:
        lines.append(f"- carryover_peer_expansion_focus: focus_ticker={carryover_peer_expansion_summary.get('focus_ticker')} focus_status={carryover_peer_expansion_summary.get('focus_status')} priority_expansion_tickers={carryover_peer_expansion_summary.get('priority_expansion_tickers')} watch_with_risk_tickers={carryover_peer_expansion_summary.get('watch_with_risk_tickers')}")
    carryover_aligned_peer_proof_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_proof_summary") or {})
    if carryover_aligned_peer_proof_summary:
        lines.append(f"- carryover_peer_proof_focus: focus_ticker={carryover_aligned_peer_proof_summary.get('focus_ticker')} focus_promotion_review_verdict={carryover_aligned_peer_proof_summary.get('focus_promotion_review_verdict')} ready_for_promotion_review_tickers={carryover_aligned_peer_proof_summary.get('ready_for_promotion_review_tickers')} risk_review_tickers={carryover_aligned_peer_proof_summary.get('risk_review_tickers')}")
    carryover_peer_promotion_gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})
    if carryover_peer_promotion_gate_summary:
        lines.append(f"- carryover_peer_promotion_gate_focus: focus_ticker={carryover_peer_promotion_gate_summary.get('focus_ticker')} focus_gate_verdict={carryover_peer_promotion_gate_summary.get('focus_gate_verdict')} default_expansion_status={carryover_peer_promotion_gate_summary.get('default_expansion_status')} ready_tickers={carryover_peer_promotion_gate_summary.get('ready_tickers')} blocked_open_tickers={carryover_peer_promotion_gate_summary.get('blocked_open_tickers')} pending_t_plus_2_tickers={carryover_peer_promotion_gate_summary.get('pending_t_plus_2_tickers')} pending_next_day_tickers={carryover_peer_promotion_gate_summary.get('pending_next_day_tickers')}")
    for frontier in list(control_tower_snapshot.get("closed_frontiers") or []):
        lines.append(f"- closed_frontier: {frontier.get('frontier_id')} status={frontier.get('status')} passing_variant_count={frontier.get('passing_variant_count')}")
        lines.append(f"  headline: {frontier.get('headline')}")
        lines.append(f"  best_variant: {frontier.get('best_variant_name')}")
    for task in list(control_tower_snapshot.get("next_actions") or []):
        lines.append(f"- next_action: {task.get('title')}")
        lines.append(f"  why_now: {task.get('why_now')}")
        lines.append(f"  next_step: {task.get('next_step')}")
    lines.append("")


def build_control_tower_snapshot_header_lines(control_tower_snapshot: dict[str, Any]) -> list[str]:
    return [
        f"- lane_status_counts: {control_tower_snapshot.get('lane_status_counts')}",
        f"- warn_count: {control_tower_snapshot.get('warn_count')}",
        f"- fail_count: {control_tower_snapshot.get('fail_count')}",
    ]


def append_rollout_lanes_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    lines.append("## Rollout Lanes")
    rollout_lanes = list(control_tower_snapshot.get("rollout_lanes") or [])
    if not rollout_lanes:
        lines.append("- unavailable")
    else:
        for row in rollout_lanes:
            lines.append(f"- lane_id={row.get('lane_id')} ticker={row.get('ticker')} governance_tier={row.get('governance_tier')} lane_status={row.get('lane_status')} blocker={row.get('blocker')}")
            lines.append(f"  validation_verdict: {row.get('validation_verdict')}")
            lines.append(f"  missing_window_count: {row.get('missing_window_count')}")
            lines.append(f"  next_step: {row.get('next_step')}")
    lines.append("")


def append_independent_window_monitor_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    lines.append("## Independent Window Monitor")
    independent_window_monitor = dict(control_tower_snapshot.get("independent_window_monitor") or {})
    if not independent_window_monitor:
        lines.append("- unavailable")
    else:
        lines.append(f"- report_dir_count: {independent_window_monitor.get('report_dir_count')}")
        lines.append(f"- recommendation: {independent_window_monitor.get('recommendation')}")
        for row in list(independent_window_monitor.get("rows") or []):
            lines.append(f"- ticker={row.get('ticker')} lane_id={row.get('lane_id')} readiness={row.get('readiness')} distinct_window_count={row.get('distinct_window_count')} missing_window_count={row.get('missing_window_count')}")
            lines.append(f"  next_step: {row.get('next_step')}")
    lines.append("")


def append_tplus1_tplus2_objective_monitor_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    lines.append("## T+1/T+2 Objective Monitor")
    tplus1_tplus2_objective_monitor = dict(control_tower_snapshot.get("tplus1_tplus2_objective_monitor") or {})
    if not tplus1_tplus2_objective_monitor:
        lines.append("- unavailable")
    else:
        tradeable_surface = dict(tplus1_tplus2_objective_monitor.get("tradeable_surface") or {})
        lines.append(f"- report_dir_count: {tplus1_tplus2_objective_monitor.get('report_dir_count')}")
        lines.append(f"- recommendation: {tplus1_tplus2_objective_monitor.get('recommendation')}")
        lines.append(f"- tradeable_closed_cycle_count: {tradeable_surface.get('closed_cycle_count')}")
        lines.append(f"- tradeable_positive_rate: {tradeable_surface.get('t_plus_2_positive_rate')}")
        lines.append(f"- tradeable_return_hit_rate_at_target: {tradeable_surface.get('t_plus_2_return_hit_rate_at_target')}")
        lines.append(f"- tradeable_mean_t_plus_2_return: {tradeable_surface.get('mean_t_plus_2_return')}")
        lines.append(f"- tradeable_verdict: {tradeable_surface.get('verdict')}")
        for row in list(tplus1_tplus2_objective_monitor.get("ticker_leaderboard") or [])[:3]:
            lines.append(f"- ticker_objective_leader: {row.get('group_label')} closed_cycle_count={row.get('closed_cycle_count')} positive_rate={row.get('t_plus_2_positive_rate')} return_hit_rate={row.get('t_plus_2_return_hit_rate_at_target')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')}")
    lines.append("")
