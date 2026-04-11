from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


RelativeLink = Callable[[str | Path | None, Path], str | None]


def append_priority_board_snapshot_markdown(lines: list[str], snapshot: dict[str, Any]) -> None:
    lines.append("## Priority Board Snapshot")
    lines.append(f"- summary: {snapshot.get('summary')}")
    lines.append(f"- brief_recommendation: {snapshot.get('brief_recommendation')}")
    for index, row in enumerate(list(snapshot.get("priority_rows") or []), start=1):
        lines.append(f"- {index}. {row.get('ticker')}: lane={row.get('lane')} actionability={row.get('actionability')} execution_quality_label={row.get('execution_quality_label')}")
        lines.append(f"  why_now: {row.get('why_now')}")
        lines.append(f"  suggested_action: {row.get('suggested_action')}")
        lines.append(f"  historical_summary: {row.get('historical_summary')}")
    for guardrail in list(snapshot.get("global_guardrails") or []):
        lines.append(f"- guardrail: {guardrail}")
    lines.append("")


def append_catalyst_theme_frontier_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    lines.append("## Catalyst Theme Frontier")
    if not summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {summary.get('status')}")
        lines.append(f"- shadow_candidate_count: {summary.get('shadow_candidate_count')}")
        lines.append(f"- baseline_selected_count: {summary.get('baseline_selected_count')}")
        lines.append(f"- recommended_variant_name: {summary.get('recommended_variant_name')}")
        lines.append(f"- recommended_promoted_shadow_count: {summary.get('recommended_promoted_shadow_count')}")
        lines.append(f"- recommended_relaxation_cost: {summary.get('recommended_relaxation_cost')}")
        lines.append(f"- recommended_thresholds: {summary.get('recommended_thresholds')}")
        promoted_tickers = list(summary.get("recommended_promoted_tickers") or [])
        lines.append(f"- recommended_promoted_tickers: {', '.join(promoted_tickers) if promoted_tickers else 'none'}")
        lines.append(f"- recommendation: {summary.get('recommendation')}")
    lines.append("")


def append_score_fail_frontier_queue_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    lines.append("## Score-Fail Frontier Queue")
    if not summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {summary.get('status')}")
        lines.append(f"- rejected_short_trade_boundary_count: {summary.get('rejected_short_trade_boundary_count')}")
        lines.append(f"- rescueable_case_count: {summary.get('rescueable_case_count')}")
        lines.append(f"- threshold_only_rescue_count: {summary.get('threshold_only_rescue_count')}")
        lines.append(f"- recurring_case_count: {summary.get('recurring_case_count')}")
        lines.append(f"- transition_candidate_count: {summary.get('transition_candidate_count')}")
        lines.append(f"- recurring_shadow_refresh_status: {summary.get('recurring_shadow_refresh_status')}")
        priority_queue_tickers = list(summary.get("priority_queue_tickers") or [])
        lines.append(f"- priority_queue_tickers: {', '.join(priority_queue_tickers) if priority_queue_tickers else 'none'}")
        top_rescue_tickers = list(summary.get("top_rescue_tickers") or [])
        lines.append(f"- top_rescue_tickers: {', '.join(top_rescue_tickers) if top_rescue_tickers else 'none'}")
        for row in list(summary.get("priority_queue") or []):
            lines.append(f"- recurring_priority: {row.get('ticker')} occurrence_count={row.get('occurrence_count')} minimal_adjustment_cost={row.get('minimal_adjustment_cost')} gap_to_near_miss_mean={row.get('gap_to_near_miss_mean')}")
        for row in list(summary.get("top_rescue_rows") or []):
            lines.append(f"- top_rescue_row: {row.get('trade_date')} {row.get('ticker')} baseline_score={row.get('baseline_score_target')} replayed_score={row.get('replayed_score_target')} adjustment_cost={row.get('adjustment_cost')}")
        lines.append(f"- recommendation: {summary.get('recommendation')}")
    lines.append("")


def append_nightly_llm_health_markdown(lines: list[str], llm_error_digest: dict[str, Any]) -> None:
    lines.append("## LLM Health")
    lines.append(f"- status: {llm_error_digest.get('status')}")
    lines.append(f"- error_count: {llm_error_digest.get('error_count')}")
    lines.append(f"- rate_limit_error_count: {llm_error_digest.get('rate_limit_error_count')}")
    lines.append(f"- fallback_attempt_count: {llm_error_digest.get('fallback_attempt_count')}")
    lines.append(f"- affected_provider_count: {llm_error_digest.get('affected_provider_count')}")
    lines.append(f"- fallback_gap_detected: {llm_error_digest.get('fallback_gap_detected')}")
    top_error_types = list(llm_error_digest.get("top_error_types") or [])
    if top_error_types:
        for row in top_error_types:
            lines.append(f"- top_error_type: {row.get('error_type')} count={row.get('count')}")
    else:
        lines.append("- top_error_type: none")
    affected_providers = list(llm_error_digest.get("affected_providers") or [])
    if affected_providers:
        for row in affected_providers:
            lines.append(f"- provider_health: {row.get('provider')} errors={row.get('errors')} attempts={row.get('attempts')} error_rate={row.get('error_rate')} fallback_attempts={row.get('fallback_attempts')}")
    else:
        lines.append("- provider_health: none")
    sample_errors = list(llm_error_digest.get("sample_errors") or [])
    if sample_errors:
        for row in sample_errors:
            lines.append(f"- sample_error: {row.get('provider')} {row.get('error_type')} stage={row.get('pipeline_stage')} tier={row.get('model_tier')} message={row.get('message')}")
    else:
        lines.append("- sample_error: none")
    lines.append("")


def append_replay_cohort_snapshot_markdown(lines: list[str], replay_cohort_snapshot: dict[str, Any]) -> None:
    lines.append("## Replay Cohort Snapshot")
    lines.append(f"- short_trade_summary: {replay_cohort_snapshot.get('short_trade_summary')}")
    lines.append(f"- frozen_summary: {replay_cohort_snapshot.get('frozen_summary')}")
    latest_short_trade_row = dict(replay_cohort_snapshot.get("latest_short_trade_row") or {})
    if latest_short_trade_row:
        lines.append(f"- latest_short_trade_report: {latest_short_trade_row.get('report_dir_name')}")
        lines.append(f"  total_return_pct: {latest_short_trade_row.get('total_return_pct')}")
        lines.append(f"  near_miss_count: {latest_short_trade_row.get('near_miss_count')}")
        lines.append(f"  opportunity_pool_count: {latest_short_trade_row.get('opportunity_pool_count')}")
    for row in list(replay_cohort_snapshot.get("top_return_rows") or []):
        lines.append(f"- top_return_row: {row.get('report_dir_name')} | selection_target={row.get('selection_target')} | total_return_pct={row.get('total_return_pct')} | near_miss_count={row.get('near_miss_count')}")
    lines.append("")


def append_nightly_reading_order_markdown(lines: list[str], payload: dict[str, Any]) -> None:
    lines.append("## Reading Order")
    for item in list(payload.get("recommended_reading_order") or []):
        lines.append(f"- {item.get('entry_id')}: {item.get('question')} | {item.get('report_path')}")
    lines.append("")


def append_nightly_fast_links_markdown(
    lines: list[str],
    source_paths: dict[str, Any],
    output_parent: Path,
    *,
    relative_link: RelativeLink,
) -> None:
    lines.append("## Fast Links")
    for label, source_path in source_paths.items():
        relative_target = relative_link(source_path, output_parent)
        if relative_target:
            lines.append(f"- {label}: [{Path(source_path).name}]({relative_target})")
        else:
            lines.append(f"- {label}: {source_path}")
    lines.append("")


def append_nightly_overview_candidate_pool_continuation_markdown(lines: list[str], control_tower_snapshot: dict[str, Any]) -> None:
    continuation_focus_summary = dict(control_tower_snapshot.get("continuation_focus_summary") or {})
    if continuation_focus_summary:
        lines.append(f"- continuation_focus_summary: focus_ticker={continuation_focus_summary.get('focus_ticker')} promotion_review_verdict={continuation_focus_summary.get('promotion_review_verdict')} promotion_gate_verdict={continuation_focus_summary.get('promotion_gate_verdict')} watchlist_execution_verdict={continuation_focus_summary.get('watchlist_execution_verdict')} focus_watch_validation_status={continuation_focus_summary.get('focus_watch_validation_status')} focus_watch_recent_supporting_window_count={continuation_focus_summary.get('focus_watch_recent_supporting_window_count')} eligible_gate_verdict={continuation_focus_summary.get('eligible_gate_verdict')} execution_gate_verdict={continuation_focus_summary.get('execution_gate_verdict')} execution_gate_blockers={continuation_focus_summary.get('execution_gate_blockers')} execution_overlay_verdict={continuation_focus_summary.get('execution_overlay_verdict')} execution_overlay_promotion_blocker={continuation_focus_summary.get('execution_overlay_promotion_blocker')} execution_overlay_persistence_requirement={continuation_focus_summary.get('execution_overlay_persistence_requirement')} execution_overlay_lane_support_ratio={continuation_focus_summary.get('execution_overlay_lane_support_ratio')} governance_status={continuation_focus_summary.get('governance_status')}")
    continuation_promotion_ready_summary = dict(control_tower_snapshot.get("continuation_promotion_ready_summary") or {})
    if continuation_promotion_ready_summary:
        lines.append(f"- continuation_promotion_ready_summary: focus_ticker={continuation_promotion_ready_summary.get('focus_ticker')} promotion_path_status={continuation_promotion_ready_summary.get('promotion_path_status')} blockers_remaining_count={continuation_promotion_ready_summary.get('blockers_remaining_count')} observed_independent_window_count={continuation_promotion_ready_summary.get('observed_independent_window_count')} missing_independent_window_count={continuation_promotion_ready_summary.get('missing_independent_window_count')} candidate_dossier_support_trade_date_count={continuation_promotion_ready_summary.get('candidate_dossier_support_trade_date_count')} candidate_dossier_same_trade_date_variant_count={continuation_promotion_ready_summary.get('candidate_dossier_same_trade_date_variant_count')} persistence_verdict={continuation_promotion_ready_summary.get('persistence_verdict')} provisional_default_btst_edge_verdict={continuation_promotion_ready_summary.get('provisional_default_btst_edge_verdict')} edge_threshold_verdict={continuation_promotion_ready_summary.get('edge_threshold_verdict')} promotion_merge_review_verdict={continuation_promotion_ready_summary.get('promotion_merge_review_verdict')} ready_after_next_qualifying_window={continuation_promotion_ready_summary.get('ready_after_next_qualifying_window')} next_window_requirement={continuation_promotion_ready_summary.get('next_window_requirement')} next_window_duplicate_trade_date_verdict={continuation_promotion_ready_summary.get('next_window_duplicate_trade_date_verdict')} next_window_quality_requirement={continuation_promotion_ready_summary.get('next_window_quality_requirement')} next_window_disqualified_bucket_verdict={continuation_promotion_ready_summary.get('next_window_disqualified_bucket_verdict')} next_window_qualified_merge_review_verdict={continuation_promotion_ready_summary.get('next_window_qualified_merge_review_verdict')} t_plus_2_positive_rate_delta_vs_default_btst={continuation_promotion_ready_summary.get('t_plus_2_positive_rate_delta_vs_default_btst')} t_plus_2_mean_return_delta_vs_default_btst={continuation_promotion_ready_summary.get('t_plus_2_mean_return_delta_vs_default_btst')}")
    corridor_window_diagnostics_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_window_diagnostics_summary") or {})
    if corridor_window_diagnostics_summary:
        near_miss_window = dict(corridor_window_diagnostics_summary.get("near_miss_upgrade_window") or {})
        visibility_gap_window = dict(corridor_window_diagnostics_summary.get("visibility_gap_window") or {})
        lines.append(f"- candidate_pool_corridor_window_diagnostics_summary: focus_ticker={corridor_window_diagnostics_summary.get('focus_ticker')} near_miss_trade_date={near_miss_window.get('trade_date')} near_miss_verdict={near_miss_window.get('verdict')} visibility_gap_verdict={visibility_gap_window.get('verdict')} recoverable_report_dir_count={visibility_gap_window.get('recoverable_report_dir_count')}")
    corridor_narrow_probe_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_narrow_probe_summary") or {})
    if corridor_narrow_probe_summary:
        deepest_corridor_focus_tickers = list(corridor_narrow_probe_summary.get("deepest_corridor_focus_tickers") or [])
        if deepest_corridor_focus_tickers:
            lines.append(f"- candidate_pool_corridor_narrow_probe_summary: focus_ticker={corridor_narrow_probe_summary.get('focus_ticker')} verdict={corridor_narrow_probe_summary.get('verdict')} deepest_corridor_focus_tickers={deepest_corridor_focus_tickers} excluded_low_gate_tail_tickers={corridor_narrow_probe_summary.get('excluded_low_gate_tail_tickers')} low_gate_focus_max_cutoff_share={corridor_narrow_probe_summary.get('low_gate_focus_max_cutoff_share')}")
        else:
            lines.append(f"- candidate_pool_corridor_narrow_probe_summary: focus_ticker={corridor_narrow_probe_summary.get('focus_ticker')} verdict={corridor_narrow_probe_summary.get('verdict')} threshold_override_gap_vs_anchor={corridor_narrow_probe_summary.get('threshold_override_gap_vs_anchor')} target_gap_to_selected={corridor_narrow_probe_summary.get('target_gap_to_selected')}")
    default_merge_review_summary = dict(control_tower_snapshot.get("default_merge_review_summary") or {})
    if default_merge_review_summary:
        counterfactual = dict(default_merge_review_summary.get("counterfactual_validation") or {})
        lines.append(f"- default_merge_review_summary: focus_ticker={default_merge_review_summary.get('focus_ticker')} merge_review_verdict={default_merge_review_summary.get('merge_review_verdict')} operator_action={default_merge_review_summary.get('operator_action')} counterfactual_verdict={counterfactual.get('counterfactual_verdict')} t_plus_2_positive_rate_delta_vs_default_btst={default_merge_review_summary.get('t_plus_2_positive_rate_delta_vs_default_btst')} t_plus_2_positive_rate_margin_vs_threshold={counterfactual.get('t_plus_2_positive_rate_margin_vs_threshold')} t_plus_2_mean_return_delta_vs_default_btst={default_merge_review_summary.get('t_plus_2_mean_return_delta_vs_default_btst')} t_plus_2_mean_return_margin_vs_threshold={counterfactual.get('t_plus_2_mean_return_margin_vs_threshold')}")
    default_merge_historical_counterfactual_summary = dict(control_tower_snapshot.get("default_merge_historical_counterfactual_summary") or {})
    if default_merge_historical_counterfactual_summary:
        uplift = dict(default_merge_historical_counterfactual_summary.get("uplift_vs_default_btst") or {})
        lines.append(f"- default_merge_historical_counterfactual_summary: focus_ticker={default_merge_historical_counterfactual_summary.get('focus_ticker')} counterfactual_verdict={default_merge_historical_counterfactual_summary.get('counterfactual_verdict')} merged_positive_rate_uplift={uplift.get('t_plus_2_positive_rate_uplift')} merged_mean_return_uplift={uplift.get('mean_t_plus_2_return_uplift')}")


def append_nightly_overview_candidate_pool_followup_tail_markdown(
    lines: list[str],
    control_tower_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    catalyst_theme_frontier_summary: dict[str, Any],
    score_fail_frontier_summary: dict[str, Any],
    llm_error_digest: dict[str, Any],
) -> None:
    continuation_merge_candidate_ranking_summary = dict(control_tower_snapshot.get("continuation_merge_candidate_ranking_summary") or {})
    if continuation_merge_candidate_ranking_summary:
        top_candidate = dict(continuation_merge_candidate_ranking_summary.get("top_candidate") or {})
        lines.append(f"- continuation_merge_candidate_ranking_summary: candidate_count={continuation_merge_candidate_ranking_summary.get('candidate_count')} top_ticker={top_candidate.get('ticker')} top_stage={top_candidate.get('promotion_path_status') or top_candidate.get('promotion_readiness_verdict')} top_positive_rate_delta={top_candidate.get('t_plus_2_positive_rate_delta_vs_default_btst')} top_mean_return_delta={top_candidate.get('mean_t_plus_2_return_delta_vs_default_btst')}")
    default_merge_strict_counterfactual_summary = dict(control_tower_snapshot.get("default_merge_strict_counterfactual_summary") or {})
    if default_merge_strict_counterfactual_summary:
        uplift = dict(default_merge_strict_counterfactual_summary.get("strict_uplift_vs_default_btst") or {})
        overlap = dict(default_merge_strict_counterfactual_summary.get("overlap_diagnostics") or {})
        lines.append(f"- default_merge_strict_counterfactual_summary: focus_ticker={default_merge_strict_counterfactual_summary.get('focus_ticker')} strict_counterfactual_verdict={default_merge_strict_counterfactual_summary.get('strict_counterfactual_verdict')} overlap_case_count={overlap.get('overlap_case_count')} strict_positive_rate_uplift={uplift.get('t_plus_2_positive_rate_uplift')} strict_mean_return_uplift={uplift.get('t_plus_2_mean_return_uplift')}")
    merge_replay_validation_summary = dict(control_tower_snapshot.get("merge_replay_validation_summary") or {})
    if merge_replay_validation_summary:
        lines.append(f"- merge_replay_validation_summary: overall_verdict={merge_replay_validation_summary.get('overall_verdict')} focus_tickers={merge_replay_validation_summary.get('focus_tickers')} promoted_to_selected_count={merge_replay_validation_summary.get('promoted_to_selected_count')} promoted_to_near_miss_count={merge_replay_validation_summary.get('promoted_to_near_miss_count')} relief_applied_count={merge_replay_validation_summary.get('relief_applied_count')} relief_actionable_applied_count={merge_replay_validation_summary.get('relief_actionable_applied_count')} relief_already_selected_count={merge_replay_validation_summary.get('relief_already_selected_count')} relief_positive_promotion_precision={merge_replay_validation_summary.get('relief_positive_promotion_precision')} relief_actionable_positive_promotion_precision={merge_replay_validation_summary.get('relief_actionable_positive_promotion_precision')} relief_no_promotion_ratio={merge_replay_validation_summary.get('relief_no_promotion_ratio')} relief_actionable_no_promotion_ratio={merge_replay_validation_summary.get('relief_actionable_no_promotion_ratio')} relief_decision_deteriorated_count={merge_replay_validation_summary.get('relief_decision_deteriorated_count')} recommended_next_lever={merge_replay_validation_summary.get('recommended_next_lever')} recommended_signal_levers={merge_replay_validation_summary.get('recommended_signal_levers')}")
    transient_probe_summary = dict(control_tower_snapshot.get("transient_probe_summary") or {})
    if transient_probe_summary:
        lines.append(f"- transient_probe_summary: ticker={transient_probe_summary.get('ticker')} status={transient_probe_summary.get('status')} blocker={transient_probe_summary.get('blocker')} candidate_source={transient_probe_summary.get('candidate_source')} score_state={transient_probe_summary.get('score_state')} downstream_bottleneck={transient_probe_summary.get('downstream_bottleneck')} historical_sample_count={transient_probe_summary.get('historical_sample_count')} historical_next_close_positive_rate={transient_probe_summary.get('historical_next_close_positive_rate')}")
    execution_constraint_rollup = dict(control_tower_snapshot.get("execution_constraint_rollup") or {})
    if execution_constraint_rollup:
        lines.append(f"- execution_constraint_rollup: constraint_count={execution_constraint_rollup.get('constraint_count')} continuation_focus_tickers={execution_constraint_rollup.get('continuation_focus_tickers')} continuation_blockers={execution_constraint_rollup.get('continuation_blockers')} shadow_focus_tickers={execution_constraint_rollup.get('shadow_focus_tickers')} shadow_blockers={execution_constraint_rollup.get('shadow_blockers')}")
    lines.append(f"- candidate_pool_upstream_handoff_board_status: {control_tower_snapshot.get('candidate_pool_upstream_handoff_board_status')}")
    upstream_handoff_summary = dict(control_tower_snapshot.get("candidate_pool_upstream_handoff_board_summary") or {})
    if upstream_handoff_summary:
        lines.append(f"- candidate_pool_upstream_handoff_board_summary: board_status={upstream_handoff_summary.get('board_status')} focus_tickers={upstream_handoff_summary.get('focus_tickers')} first_broken_handoff_counts={upstream_handoff_summary.get('first_broken_handoff_counts')}")
    lines.append(f"- candidate_pool_upstream_handoff_focus_tickers_active: {control_tower_snapshot.get('active_candidate_pool_upstream_handoff_focus_tickers')}")
    lines.append(f"- upstream_shadow_followup_validated_tickers: {control_tower_snapshot.get('upstream_shadow_followup_validated_tickers')}")
    lines.append(f"- upstream_shadow_followup_decision_counts: {control_tower_snapshot.get('upstream_shadow_followup_decision_counts')}")
    lines.append(f"- upstream_shadow_followup_near_miss_tickers: {control_tower_snapshot.get('upstream_shadow_followup_near_miss_tickers')}")
    lines.append(f"- upstream_shadow_followup_rejected_profitability_tickers: {control_tower_snapshot.get('upstream_shadow_followup_rejected_profitability_tickers')}")
    lines.append(f"- candidate_pool_corridor_uplift_runbook_status: {control_tower_snapshot.get('candidate_pool_corridor_uplift_runbook_status')}")
    corridor_uplift_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_uplift_runbook_summary") or {})
    if corridor_uplift_summary:
        lines.append(f"- candidate_pool_corridor_uplift_runbook_summary: runbook_status={corridor_uplift_summary.get('runbook_status')} primary_shadow_replay={corridor_uplift_summary.get('primary_shadow_replay')} parallel_watch_tickers={corridor_uplift_summary.get('parallel_watch_tickers')}")
    lines.append(f"- replay_report_count: {replay_cohort_snapshot.get('report_count')}")
    lines.append(f"- replay_selection_target_counts: {replay_cohort_snapshot.get('selection_target_counts')}")
    lines.append(f"- catalyst_frontier_status: {catalyst_theme_frontier_summary.get('status') or 'unavailable'}")
    lines.append(f"- catalyst_frontier_promoted_shadow_count: {catalyst_theme_frontier_summary.get('recommended_promoted_shadow_count')}")
    lines.append(f"- catalyst_frontier_shadow_threshold_blocker_summary: {catalyst_theme_frontier_summary.get('shadow_threshold_blocker_summary')}")
    lines.append(f"- score_fail_frontier_status: {score_fail_frontier_summary.get('status') or 'unavailable'}")
    lines.append(f"- score_fail_rejected_case_count: {score_fail_frontier_summary.get('rejected_short_trade_boundary_count')}")
    lines.append(f"- score_fail_recurring_case_count: {score_fail_frontier_summary.get('recurring_case_count')}")
    lines.append(f"- llm_health_status: {llm_error_digest.get('status')}")
    lines.append(f"- llm_error_count: {llm_error_digest.get('error_count')}")
    lines.append(f"- llm_fallback_attempt_count: {llm_error_digest.get('fallback_attempt_count')}")


def append_nightly_overview_candidate_pool_followup_markdown(
    lines: list[str],
    control_tower_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    catalyst_theme_frontier_summary: dict[str, Any],
    score_fail_frontier_summary: dict[str, Any],
    llm_error_digest: dict[str, Any],
) -> None:
    append_nightly_overview_candidate_pool_continuation_markdown(lines, control_tower_snapshot)
    append_nightly_overview_candidate_pool_followup_tail_markdown(
        lines,
        control_tower_snapshot,
        replay_cohort_snapshot,
        catalyst_theme_frontier_summary,
        score_fail_frontier_summary,
        llm_error_digest,
    )
