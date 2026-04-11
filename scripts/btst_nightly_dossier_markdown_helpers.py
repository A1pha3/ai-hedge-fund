from __future__ import annotations

from typing import Any


def append_tradeable_opportunity_pool_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    lines.append("## Tradeable Opportunity Pool")
    if not summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {summary.get('status')}")
        lines.append(f"- result_truth_pool_count: {summary.get('result_truth_pool_count')}")
        lines.append(f"- tradeable_opportunity_pool_count: {summary.get('tradeable_opportunity_pool_count')}")
        lines.append(f"- system_recall_count: {summary.get('system_recall_count')}")
        lines.append(f"- selected_or_near_miss_count: {summary.get('selected_or_near_miss_count')}")
        lines.append(f"- main_execution_pool_count: {summary.get('main_execution_pool_count')}")
        lines.append(f"- strict_goal_case_count: {summary.get('strict_goal_case_count')}")
        lines.append(f"- strict_goal_false_negative_count: {summary.get('strict_goal_false_negative_count')}")
        lines.append(f"- tradeable_pool_capture_rate: {summary.get('tradeable_pool_capture_rate')}")
        lines.append(f"- tradeable_pool_selected_or_near_miss_rate: {summary.get('tradeable_pool_selected_or_near_miss_rate')}")
        lines.append(f"- tradeable_pool_main_execution_rate: {summary.get('tradeable_pool_main_execution_rate')}")
        lines.append(f"- no_candidate_entry_count: {summary.get('no_candidate_entry_count')}")
        lines.append(f"- no_candidate_entry_share_of_tradeable_pool: {summary.get('no_candidate_entry_share_of_tradeable_pool')}")
        lines.append(f"- top_no_candidate_entry_industries: {summary.get('top_no_candidate_entry_industries')}")
        lines.append(f"- top_no_candidate_entry_tickers: {summary.get('top_no_candidate_entry_tickers')}")
        lines.append(f"- top_tradeable_kill_switch_labels: {summary.get('top_tradeable_kill_switch_labels')}")
        for row in list(summary.get("top_tradeable_kill_switches") or []):
            lines.append(f"- top_tradeable_kill_switch: {row.get('kill_switch')} count={row.get('count')}")
        for row in list(summary.get("top_strict_goal_false_negative_rows") or []):
            lines.append(f"- top_strict_goal_false_negative: {row.get('trade_date')} {row.get('ticker')} kill_switch={row.get('first_kill_switch')} t_plus_2_close_return={row.get('t_plus_2_close_return')}")
        lines.append(f"- recommendation: {summary.get('recommendation')}")
    lines.append("")


def append_no_candidate_entry_action_board_markdown(lines: list[str], summary: dict[str, Any], overlay: dict[str, Any]) -> None:
    lines.append("## No Candidate Entry Action Board")
    if overlay.get("validated_tickers"):
        lines.append(f"- note: 本 section 保留历史 no-entry backlog 排名；当前 active upstream recall 已收敛到 {overlay.get('active_no_candidate_entry_priority_tickers')}，已正式 followup 验证的票请转看上面的 Latest Upstream Shadow Followup Overlay。")
    if not summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {summary.get('status')}")
        lines.append(f"- priority_queue_count: {summary.get('priority_queue_count')}")
        lines.append(f"- top_priority_tickers: {summary.get('top_priority_tickers')}")
        lines.append(f"- top_hotspot_report_dirs: {summary.get('top_hotspot_report_dirs')}")
        for row in list(summary.get("priority_queue") or []):
            lines.append(f"- no_candidate_entry_priority: {row.get('ticker')} action_tier={row.get('action_tier')} strict_goal_case_count={row.get('strict_goal_case_count')} occurrence_count={row.get('occurrence_count')}")
        for task in list(summary.get("next_tasks") or []):
            lines.append(f"- next_task: {task.get('task_id')} | {task.get('title')}")
            lines.append(f"  next_step: {task.get('next_step')}")
        lines.append(f"- recommendation: {summary.get('recommendation')}")
    lines.append("")


def append_no_candidate_entry_replay_bundle_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    lines.append("## No Candidate Entry Replay Bundle")
    if not summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {summary.get('status')}")
        lines.append(f"- promising_priority_tickers: {summary.get('promising_priority_tickers')}")
        lines.append(f"- promising_hotspot_report_dirs: {summary.get('promising_hotspot_report_dirs')}")
        lines.append(f"- candidate_entry_status_counts: {summary.get('candidate_entry_status_counts')}")
        lines.append(f"- global_window_scan_rollout_readiness: {summary.get('global_window_scan_rollout_readiness')}")
        lines.append(f"- global_window_scan_focus_hit_report_count: {summary.get('global_window_scan_focus_hit_report_count')}")
        for item in list(summary.get("next_actions") or []):
            lines.append(f"- next_action: {item}")
        lines.append(f"- recommendation: {summary.get('recommendation')}")
    lines.append("")


def append_no_candidate_entry_failure_dossier_markdown(lines: list[str], summary: dict[str, Any], overlay: dict[str, Any]) -> None:
    lines.append("## No Candidate Entry Failure Dossier")
    if overlay.get("validated_tickers"):
        lines.append(f"- note: 本 section 反映历史 failure dossier 断点；当前 active absent_from_watchlist 只剩 {overlay.get('active_absent_from_watchlist_tickers')}。")
    if not summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {summary.get('status')}")
        lines.append(f"- priority_failure_class_counts: {summary.get('priority_failure_class_counts')}")
        lines.append(f"- hotspot_failure_class_counts: {summary.get('hotspot_failure_class_counts')}")
        lines.append(f"- priority_handoff_stage_counts: {summary.get('priority_handoff_stage_counts')}")
        lines.append(f"- top_absent_from_watchlist_tickers: {summary.get('top_absent_from_watchlist_tickers')}")
        lines.append(f"- top_watchlist_visible_but_not_candidate_entry_tickers: {summary.get('top_watchlist_visible_but_not_candidate_entry_tickers')}")
        lines.append(f"- top_candidate_entry_visible_but_not_selection_target_tickers: {summary.get('top_candidate_entry_visible_but_not_selection_target_tickers')}")
        lines.append(f"- top_upstream_absence_tickers: {summary.get('top_upstream_absence_tickers')}")
        lines.append(f"- top_candidate_entry_semantic_miss_tickers: {summary.get('top_candidate_entry_semantic_miss_tickers')}")
        lines.append(f"- top_present_but_outside_candidate_entry_tickers: {summary.get('top_present_but_outside_candidate_entry_tickers')}")
        lines.append(f"- top_missing_replay_input_tickers: {summary.get('top_missing_replay_input_tickers')}")
        for row in list(summary.get("handoff_action_queue") or []):
            lines.append(f"- handoff_task: {row.get('task_id')} stage={row.get('handoff_stage')} tier={row.get('action_tier')}")
            lines.append(f"  next_step: {row.get('next_step')}")
        for item in list(summary.get("next_actions") or []):
            lines.append(f"- next_action: {item}")
        lines.append(f"- recommendation: {summary.get('recommendation')}")
    lines.append("")


def append_watchlist_recall_dossier_markdown(lines: list[str], summary: dict[str, Any], overlay: dict[str, Any]) -> None:
    lines.append("## Watchlist Recall Dossier")
    if overlay.get("validated_tickers"):
        lines.append(f"- note: 本 section 保留历史 watchlist recall backlog；当前 active absent_from_candidate_pool 只剩 {overlay.get('active_watchlist_absent_from_candidate_pool_tickers')}。")
    if not summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {summary.get('status')}")
        lines.append(f"- priority_recall_stage_counts: {summary.get('priority_recall_stage_counts')}")
        lines.append(f"- top_absent_from_candidate_pool_tickers: {summary.get('top_absent_from_candidate_pool_tickers')}")
        lines.append(f"- top_candidate_pool_visible_but_missing_layer_b_tickers: {summary.get('top_candidate_pool_visible_but_missing_layer_b_tickers')}")
        lines.append(f"- top_layer_b_visible_but_missing_watchlist_tickers: {summary.get('top_layer_b_visible_but_missing_watchlist_tickers')}")
        for row in list(summary.get("action_queue") or []):
            lines.append(f"- watchlist_recall_task: {row.get('task_id')} stage={row.get('dominant_recall_stage')} tier={row.get('action_tier')}")
            lines.append(f"  next_step: {row.get('next_step')}")
        for item in list(summary.get("next_actions") or []):
            lines.append(f"- next_action: {item}")
        lines.append(f"- recommendation: {summary.get('recommendation')}")
    lines.append("")


def append_candidate_pool_recall_priority_details_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    branch_experiment_queue = list(summary.get("priority_handoff_branch_experiment_queue") or [])
    lines.append("- priority_handoff_branch_experiment_queue: structured_summary")
    lines.append(f"- priority_handoff_branch_experiment_queue_count: {len(branch_experiment_queue)}")
    for experiment in branch_experiment_queue[:3]:
        lines.append(f"- branch_experiment: task_id={experiment.get('task_id')} handoff={experiment.get('priority_handoff')} readiness={experiment.get('prototype_readiness')} tickers={experiment.get('tickers')}")
        lines.append(f"  prototype_summary: {experiment.get('prototype_summary')}")
        lines.append(f"  evaluation_summary: {experiment.get('evaluation_summary')}")
        lines.append(f"  guardrail_summary: {experiment.get('guardrail_summary')}")
    lines.append(f"- branch_priority_board_status: {summary.get('branch_priority_board_status')}")
    lines.append(f"- branch_priority_alignment_status: {summary.get('branch_priority_alignment_status')}")
    if summary.get("branch_priority_alignment_summary"):
        lines.append(f"- branch_priority_alignment_summary: {summary.get('branch_priority_alignment_summary')}")
    for row in list(summary.get("branch_priority_board_rows") or [])[:3]:
        lines.append(f"- branch_priority: handoff={row.get('priority_handoff')} readiness={row.get('prototype_readiness')} execution_priority_rank={row.get('execution_priority_rank')} tickers={row.get('tickers')}")
    lines.append(f"- lane_objective_support_status: {summary.get('lane_objective_support_status')}")
    for row in list(summary.get("lane_objective_support_rows") or [])[:3]:
        lines.append(f"- lane_objective_support: handoff={row.get('priority_handoff')} verdict={row.get('support_verdict')} closed_cycle_count={row.get('closed_cycle_count')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')}")


def append_candidate_pool_recall_corridor_details_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    lines.append(f"- corridor_validation_pack_status: {summary.get('corridor_validation_pack_status')}")
    corridor_summary = dict(summary.get("corridor_validation_pack_summary") or {})
    if corridor_summary:
        lines.append(
            f"- corridor_validation_pack_summary: pack_status={corridor_summary.get('pack_status')} primary_validation_ticker={corridor_summary.get('primary_validation_ticker')} promotion_readiness_status={corridor_summary.get('promotion_readiness_status')} parallel_watch_tickers={corridor_summary.get('parallel_watch_tickers')}"
        )
    lines.append(f"- corridor_shadow_pack_status: {summary.get('corridor_shadow_pack_status')}")
    corridor_shadow_summary = dict(summary.get("corridor_shadow_pack_summary") or {})
    if corridor_shadow_summary:
        lines.append(f"- corridor_shadow_pack_summary: shadow_status={corridor_shadow_summary.get('shadow_status')} primary_shadow_replay={corridor_shadow_summary.get('primary_shadow_replay')} parallel_watch_tickers={corridor_shadow_summary.get('parallel_watch_tickers')}")
    lines.append(f"- rebucket_shadow_pack_status: {summary.get('rebucket_shadow_pack_status')}")
    rebucket_experiment = dict(summary.get("rebucket_shadow_pack_experiment") or {})
    if rebucket_experiment:
        lines.append(f"- rebucket_shadow_pack_experiment: handoff={rebucket_experiment.get('priority_handoff')} readiness={rebucket_experiment.get('prototype_readiness')} tickers={rebucket_experiment.get('tickers')}")
    lines.append(f"- rebucket_objective_validation_status: {summary.get('rebucket_objective_validation_status')}")
    rebucket_validation_summary = dict(summary.get("rebucket_objective_validation_summary") or {})
    if rebucket_validation_summary:
        lines.append(f"- rebucket_objective_validation_summary: validation_status={rebucket_validation_summary.get('validation_status')} support_verdict={rebucket_validation_summary.get('support_verdict')} mean_t_plus_2_return={rebucket_validation_summary.get('mean_t_plus_2_return')}")
    lines.append(f"- rebucket_comparison_bundle_status: {summary.get('rebucket_comparison_bundle_status')}")
    rebucket_comparison_summary = dict(summary.get("rebucket_comparison_bundle_summary") or {})
    if rebucket_comparison_summary:
        lines.append(f"- rebucket_comparison_bundle_summary: bundle_status={rebucket_comparison_summary.get('bundle_status')} structural_leader={rebucket_comparison_summary.get('structural_leader')} objective_leader={rebucket_comparison_summary.get('objective_leader')}")
    lines.append(f"- lane_pair_board_status: {summary.get('lane_pair_board_status')}")
    lane_pair_summary = dict(summary.get("lane_pair_board_summary") or {})
    if lane_pair_summary:
        lines.append(f"- lane_pair_board_summary: pair_status={lane_pair_summary.get('pair_status')} board_leader={lane_pair_summary.get('board_leader')} leader_lane_family={lane_pair_summary.get('leader_lane_family')} leader_governance_status={lane_pair_summary.get('leader_governance_status')} leader_governance_execution_quality={lane_pair_summary.get('leader_governance_execution_quality')} leader_governance_entry_timing_bias={lane_pair_summary.get('leader_governance_entry_timing_bias')} parallel_watch_ticker={lane_pair_summary.get('parallel_watch_ticker')} parallel_watch_governance_blocker={lane_pair_summary.get('parallel_watch_governance_blocker')} parallel_watch_same_source_sample_count={lane_pair_summary.get('parallel_watch_same_source_sample_count')} parallel_watch_next_close_positive_rate={lane_pair_summary.get('parallel_watch_next_close_positive_rate')} parallel_watch_next_close_return_mean={lane_pair_summary.get('parallel_watch_next_close_return_mean')}")


def append_candidate_pool_recall_followup_details_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    continuation_focus_summary = dict(summary.get("continuation_focus_summary") or {})
    if continuation_focus_summary:
        lines.append(f"- continuation_focus_summary: focus_ticker={continuation_focus_summary.get('focus_ticker')} promotion_review_verdict={continuation_focus_summary.get('promotion_review_verdict')} promotion_gate_verdict={continuation_focus_summary.get('promotion_gate_verdict')} watchlist_execution_verdict={continuation_focus_summary.get('watchlist_execution_verdict')} focus_watch_validation_status={continuation_focus_summary.get('focus_watch_validation_status')} focus_watch_recent_supporting_window_count={continuation_focus_summary.get('focus_watch_recent_supporting_window_count')} eligible_gate_verdict={continuation_focus_summary.get('eligible_gate_verdict')} execution_gate_verdict={continuation_focus_summary.get('execution_gate_verdict')} execution_gate_blockers={continuation_focus_summary.get('execution_gate_blockers')} execution_overlay_verdict={continuation_focus_summary.get('execution_overlay_verdict')} execution_overlay_promotion_blocker={continuation_focus_summary.get('execution_overlay_promotion_blocker')} execution_overlay_persistence_requirement={continuation_focus_summary.get('execution_overlay_persistence_requirement')} execution_overlay_lane_support_ratio={continuation_focus_summary.get('execution_overlay_lane_support_ratio')} governance_status={continuation_focus_summary.get('governance_status')}")
    continuation_promotion_ready_summary = dict(summary.get("continuation_promotion_ready_summary") or {})
    if continuation_promotion_ready_summary:
        lines.append(f"- continuation_promotion_ready_summary: focus_ticker={continuation_promotion_ready_summary.get('focus_ticker')} promotion_path_status={continuation_promotion_ready_summary.get('promotion_path_status')} blockers_remaining_count={continuation_promotion_ready_summary.get('blockers_remaining_count')} observed_independent_window_count={continuation_promotion_ready_summary.get('observed_independent_window_count')} missing_independent_window_count={continuation_promotion_ready_summary.get('missing_independent_window_count')} candidate_dossier_support_trade_date_count={continuation_promotion_ready_summary.get('candidate_dossier_support_trade_date_count')} candidate_dossier_same_trade_date_variant_count={continuation_promotion_ready_summary.get('candidate_dossier_same_trade_date_variant_count')} persistence_verdict={continuation_promotion_ready_summary.get('persistence_verdict')} provisional_default_btst_edge_verdict={continuation_promotion_ready_summary.get('provisional_default_btst_edge_verdict')} edge_threshold_verdict={continuation_promotion_ready_summary.get('edge_threshold_verdict')} promotion_merge_review_verdict={continuation_promotion_ready_summary.get('promotion_merge_review_verdict')} ready_after_next_qualifying_window={continuation_promotion_ready_summary.get('ready_after_next_qualifying_window')} next_window_requirement={continuation_promotion_ready_summary.get('next_window_requirement')} next_window_duplicate_trade_date_verdict={continuation_promotion_ready_summary.get('next_window_duplicate_trade_date_verdict')} next_window_quality_requirement={continuation_promotion_ready_summary.get('next_window_quality_requirement')} next_window_disqualified_bucket_verdict={continuation_promotion_ready_summary.get('next_window_disqualified_bucket_verdict')} next_window_qualified_merge_review_verdict={continuation_promotion_ready_summary.get('next_window_qualified_merge_review_verdict')} t_plus_2_positive_rate_delta_vs_default_btst={continuation_promotion_ready_summary.get('t_plus_2_positive_rate_delta_vs_default_btst')} t_plus_2_mean_return_delta_vs_default_btst={continuation_promotion_ready_summary.get('t_plus_2_mean_return_delta_vs_default_btst')}")
    transient_probe_summary = dict(summary.get("transient_probe_summary") or {})
    if transient_probe_summary:
        lines.append(f"- transient_probe_summary: ticker={transient_probe_summary.get('ticker')} status={transient_probe_summary.get('status')} blocker={transient_probe_summary.get('blocker')} candidate_source={transient_probe_summary.get('candidate_source')} score_state={transient_probe_summary.get('score_state')} downstream_bottleneck={transient_probe_summary.get('downstream_bottleneck')} historical_sample_count={transient_probe_summary.get('historical_sample_count')} historical_next_close_positive_rate={transient_probe_summary.get('historical_next_close_positive_rate')}")
    execution_constraint_rollup = dict(summary.get("execution_constraint_rollup") or {})
    if execution_constraint_rollup:
        lines.append(f"- execution_constraint_rollup: constraint_count={execution_constraint_rollup.get('constraint_count')} continuation_focus_tickers={execution_constraint_rollup.get('continuation_focus_tickers')} continuation_blockers={execution_constraint_rollup.get('continuation_blockers')} shadow_focus_tickers={execution_constraint_rollup.get('shadow_focus_tickers')} shadow_blockers={execution_constraint_rollup.get('shadow_blockers')}")
    lines.append(f"- upstream_handoff_board_status: {summary.get('upstream_handoff_board_status')}")
    upstream_handoff_summary = dict(summary.get("upstream_handoff_board_summary") or {})
    if upstream_handoff_summary:
        lines.append(f"- upstream_handoff_board_summary: board_status={upstream_handoff_summary.get('board_status')} focus_tickers={upstream_handoff_summary.get('focus_tickers')} first_broken_handoff_counts={upstream_handoff_summary.get('first_broken_handoff_counts')}")
    lines.append(f"- corridor_uplift_runbook_status: {summary.get('corridor_uplift_runbook_status')}")
    corridor_uplift_summary = dict(summary.get("corridor_uplift_runbook_summary") or {})
    if corridor_uplift_summary:
        lines.append(f"- corridor_uplift_runbook_summary: runbook_status={corridor_uplift_summary.get('runbook_status')} primary_shadow_replay={corridor_uplift_summary.get('primary_shadow_replay')} parallel_watch_tickers={corridor_uplift_summary.get('parallel_watch_tickers')}")
    for row in list(summary.get("action_queue") or []):
        lines.append(f"- candidate_pool_recall_task: {row.get('task_id')} stage={row.get('dominant_blocking_stage')} tier={row.get('action_tier')}")
        lines.append(f"  next_step: {row.get('next_step')}")
    for item in list(summary.get("next_actions") or []):
        lines.append(f"- next_action: {item}")
    lines.append(f"- recommendation: {summary.get('recommendation')}")


def append_candidate_pool_recall_dossier_markdown(lines: list[str], summary: dict[str, Any], overlay: dict[str, Any]) -> None:
    lines.append("## Candidate Pool Recall Dossier")
    if overlay.get("validated_tickers"):
        lines.append(f"- note: 本 section 的 Layer A 截断画像保留为历史 lane 背景；当前 active upstream handoff focus 已收敛到 {overlay.get('active_upstream_handoff_focus_tickers')}。")
    if not summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {summary.get('status')}")
        lines.append(f"- priority_stage_counts: {summary.get('priority_stage_counts')}")
        lines.append(f"- dominant_stage: {summary.get('dominant_stage')}")
        lines.append(f"- top_stage_tickers: {summary.get('top_stage_tickers')}")
        lines.append(f"- priority_handoff_branch_diagnoses: {summary.get('priority_handoff_branch_diagnoses')}")
        lines.append(f"- priority_handoff_branch_mechanisms: {summary.get('priority_handoff_branch_mechanisms')}")
        append_candidate_pool_recall_priority_details_markdown(lines, summary)
        append_candidate_pool_recall_corridor_details_markdown(lines, summary)
        append_candidate_pool_recall_followup_details_markdown(lines, summary)
    lines.append("")
