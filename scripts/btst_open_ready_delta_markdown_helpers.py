from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


RelativeLink = Callable[[str | Path | None, Path], str | None]


def append_open_ready_overview_markdown(
    lines: list[str],
    payload: dict[str, Any],
    current_reference: dict[str, Any],
    previous_reference: dict[str, Any],
) -> None:
    lines.append("# BTST Open-Ready Delta")
    lines.append("")
    append_open_ready_overview_fields(lines, payload, current_reference, previous_reference)
    append_open_ready_operator_focus_markdown(lines, list(payload.get("operator_focus") or []))


def append_open_ready_overview_fields(
    lines: list[str],
    payload: dict[str, Any],
    current_reference: dict[str, Any],
    previous_reference: dict[str, Any],
) -> None:
    lines.append("## Overview")
    lines.append(f"- generated_at: {payload.get('generated_at')}")
    lines.append(f"- comparison_basis: {payload.get('comparison_basis')}")
    lines.append(f"- comparison_scope: {payload.get('comparison_scope')}")
    lines.append(f"- overall_delta_verdict: {payload.get('overall_delta_verdict')}")
    lines.append(f"- current_report_dir: {current_reference.get('report_dir')}")
    lines.append(f"- previous_report_dir: {previous_reference.get('report_dir') or 'n/a'}")
    lines.append(f"- current_trade_date: {current_reference.get('trade_date')}")
    lines.append(f"- previous_trade_date: {previous_reference.get('trade_date') or 'n/a'}")
    lines.append(f"- previous_snapshot_generated_at: {previous_reference.get('generated_at') or 'n/a'}")
    lines.append("")


def append_open_ready_operator_focus_markdown(lines: list[str], operator_focus: list[Any]) -> None:
    lines.append("## Operator Focus")
    for item in operator_focus:
        lines.append(f"- {item}")
    lines.append("")


def append_material_change_anchor_markdown(
    lines: list[str],
    anchor: dict[str, Any],
    output_parent: Path,
    *,
    relative_link: RelativeLink,
) -> None:
    if not anchor:
        return
    lines.append("## Last Material Change Anchor")
    append_material_change_anchor_metadata(lines, anchor, output_parent, relative_link=relative_link)
    append_material_change_anchor_focus_markdown(lines, list(anchor.get("operator_focus") or []))
    lines.append("")


def append_material_change_anchor_metadata(
    lines: list[str],
    anchor: dict[str, Any],
    output_parent: Path,
    *,
    relative_link: RelativeLink,
) -> None:
    lines.append(f"- reference_generated_at: {anchor.get('reference_generated_at') or 'n/a'}")
    lines.append(f"- reference_report_dir: {anchor.get('reference_report_dir') or 'n/a'}")
    lines.append(f"- comparison_basis: {anchor.get('comparison_basis')}")
    lines.append(f"- comparison_scope: {anchor.get('comparison_scope')}")
    lines.append(f"- overall_delta_verdict: {anchor.get('overall_delta_verdict')}")
    lines.append(f"- skipped_same_report_rerun_snapshots: {anchor.get('skipped_snapshot_count') or 0}")
    changed_sections = list(anchor.get("changed_sections") or [])
    lines.append(f"- changed_sections: {', '.join(changed_sections) if changed_sections else 'none'}")
    reference_snapshot_path = anchor.get("reference_snapshot_path")
    relative_anchor_target = relative_link(reference_snapshot_path, output_parent)
    if relative_anchor_target:
        lines.append(f"- reference_snapshot_json: [{Path(reference_snapshot_path).name}]({relative_anchor_target})")
    elif reference_snapshot_path:
        lines.append(f"- reference_snapshot_json: {reference_snapshot_path}")


def append_material_change_anchor_focus_markdown(lines: list[str], operator_focus: list[Any]) -> None:
    for item in operator_focus:
        lines.append(f"- anchor_focus: {item}")


def append_priority_delta_list(
    lines: list[str],
    items: list[Any],
    formatter: Callable[[Any], str],
) -> None:
    for item in items:
        lines.append(formatter(item))


def append_priority_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    lines.append("## Priority Delta")
    lines.append(f"- previous_headline: {delta.get('previous_headline') or 'n/a'}")
    lines.append(f"- current_headline: {delta.get('current_headline') or 'n/a'}")
    lines.append(f"- summary_delta: {delta.get('summary_delta')}")
    append_priority_membership_markdown(lines, delta)
    append_priority_change_markdown(lines, delta)
    append_priority_guardrail_markdown(lines, delta)
    if not delta.get("has_changes"):
        lines.append("- no_priority_change_detected")
    lines.append("")


def append_priority_membership_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    append_priority_delta_list(
        lines,
        list(delta.get("added_tickers") or []),
        lambda item: f"- added_ticker: {item.get('ticker')} | lane={item.get('lane')} | actionability={item.get('actionability')}",
    )
    append_priority_delta_list(
        lines,
        list(delta.get("removed_tickers") or []),
        lambda item: f"- removed_ticker: {item.get('ticker')} | lane={item.get('lane')} | actionability={item.get('actionability')}",
    )


def append_priority_change_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    append_priority_delta_list(lines, list(delta.get("lane_changes") or []), lambda item: f"- lane_change: {item.get('ticker')} | {item.get('previous_lane')} -> {item.get('current_lane')}")
    append_priority_delta_list(
        lines,
        list(delta.get("actionability_changes") or []),
        lambda item: f"- actionability_change: {item.get('ticker')} | {item.get('previous_actionability')} -> {item.get('current_actionability')}",
    )
    append_priority_delta_list(
        lines,
        list(delta.get("execution_quality_changes") or []),
        lambda item: f"- execution_quality_change: {item.get('ticker')} | {item.get('previous_execution_quality_label')} -> {item.get('current_execution_quality_label')}",
    )
    append_priority_delta_list(lines, list(delta.get("rank_changes") or []), lambda item: f"- rank_change: {item.get('ticker')} | {item.get('previous_rank')} -> {item.get('current_rank')}")
    append_priority_delta_list(
        lines,
        list(delta.get("score_changes") or []),
        lambda item: f"- score_change: {item.get('ticker')} | {item.get('previous_score_target')} -> {item.get('current_score_target')} (delta={item.get('score_target_delta')})",
    )


def append_priority_guardrail_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    append_priority_delta_list(lines, list(delta.get("guardrails_added") or []), lambda item: f"- guardrail_added: {item}")
    append_priority_delta_list(lines, list(delta.get("guardrails_removed") or []), lambda item: f"- guardrail_removed: {item}")


def append_catalyst_frontier_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    lines.append("## Catalyst Theme Frontier Delta")
    if not delta.get("available"):
        lines.append("- unavailable")
    else:
        append_catalyst_frontier_delta_summary(lines, delta)
        append_catalyst_frontier_delta_tickers(lines, delta)
        if not delta.get("has_changes"):
            lines.append("- no_catalyst_frontier_change_detected")
    lines.append("")


def append_catalyst_frontier_delta_summary(lines: list[str], delta: dict[str, Any]) -> None:
    lines.append(f"- comparison_basis: {delta.get('comparison_basis')}")
    lines.append(f"- previous_data_available: {delta.get('previous_data_available')}")
    lines.append(f"- previous_status: {delta.get('previous_status') or 'n/a'}")
    lines.append(f"- current_status: {delta.get('current_status') or 'n/a'}")
    lines.append(f"- shadow_candidate_count_delta: {delta.get('shadow_candidate_count_delta')}")
    lines.append(f"- promoted_shadow_count_delta: {delta.get('promoted_shadow_count_delta')}")
    lines.append(f"- baseline_selected_count_delta: {delta.get('baseline_selected_count_delta')}")
    lines.append(f"- previous_recommended_variant_name: {delta.get('previous_recommended_variant_name') or 'n/a'}")
    lines.append(f"- current_recommended_variant_name: {delta.get('current_recommended_variant_name') or 'n/a'}")
    if delta.get("comparison_note"):
        lines.append(f"- note: {delta.get('comparison_note')}")


def append_catalyst_frontier_delta_tickers(lines: list[str], delta: dict[str, Any]) -> None:
    previous_promoted_tickers = list(delta.get("previous_promoted_tickers") or [])
    current_promoted_tickers = list(delta.get("current_promoted_tickers") or [])
    lines.append(f"- previous_promoted_tickers: {', '.join(previous_promoted_tickers) if previous_promoted_tickers else 'none'}")
    lines.append(f"- current_promoted_tickers: {', '.join(current_promoted_tickers) if current_promoted_tickers else 'none'}")
    for ticker in list(delta.get("added_promoted_tickers") or []):
        lines.append(f"- added_promoted_ticker: {ticker}")
    for ticker in list(delta.get("removed_promoted_tickers") or []):
        lines.append(f"- removed_promoted_ticker: {ticker}")


def append_score_fail_frontier_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    lines.append("## Score-Fail Frontier Delta")
    if not delta.get("available"):
        lines.append(f"- unavailable: {delta.get('reason')}")
    else:
        append_score_fail_frontier_delta_summary(lines, delta)
        append_score_fail_frontier_delta_tickers(lines, delta)
        if not delta.get("has_changes"):
            lines.append("- no_score_fail_frontier_change_detected")
    lines.append("")


def append_score_fail_frontier_delta_summary(lines: list[str], delta: dict[str, Any]) -> None:
    lines.append(f"- previous_data_available: {delta.get('previous_data_available')}")
    lines.append(f"- previous_status: {delta.get('previous_status') or 'n/a'}")
    lines.append(f"- current_status: {delta.get('current_status') or 'n/a'}")
    lines.append(f"- rejected_case_count_delta: {delta.get('rejected_case_count_delta')}")
    lines.append(f"- rescueable_case_count_delta: {delta.get('rescueable_case_count_delta')}")
    lines.append(f"- threshold_only_rescue_count_delta: {delta.get('threshold_only_rescue_count_delta')}")
    lines.append(f"- recurring_case_count_delta: {delta.get('recurring_case_count_delta')}")
    lines.append(f"- transition_candidate_count_delta: {delta.get('transition_candidate_count_delta')}")
    if delta.get("comparison_note"):
        lines.append(f"- note: {delta.get('comparison_note')}")


def append_score_fail_frontier_delta_tickers(lines: list[str], delta: dict[str, Any]) -> None:
    previous_priority_queue = list(delta.get("previous_priority_queue_tickers") or [])
    current_priority_queue = list(delta.get("current_priority_queue_tickers") or [])
    lines.append(f"- previous_priority_queue_tickers: {', '.join(previous_priority_queue) if previous_priority_queue else 'none'}")
    lines.append(f"- current_priority_queue_tickers: {', '.join(current_priority_queue) if current_priority_queue else 'none'}")
    for ticker in list(delta.get("added_priority_tickers") or []):
        lines.append(f"- added_priority_ticker: {ticker}")
    for ticker in list(delta.get("removed_priority_tickers") or []):
        lines.append(f"- removed_priority_ticker: {ticker}")
    for ticker in list(delta.get("added_top_rescue_tickers") or []):
        lines.append(f"- added_top_rescue_ticker: {ticker}")
    for ticker in list(delta.get("removed_top_rescue_tickers") or []):
        lines.append(f"- removed_top_rescue_ticker: {ticker}")


def append_top_priority_action_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    lines.append("## Top Priority Action Delta")
    if not delta.get("available"):
        lines.append(f"- unavailable: {delta.get('reason')}")
    else:
        lines.append(f"- previous_task_id: {delta.get('previous_task_id') or 'n/a'}")
        lines.append(f"- current_task_id: {delta.get('current_task_id') or 'n/a'}")
        lines.append(f"- previous_source: {delta.get('previous_source') or 'n/a'}")
        lines.append(f"- current_source: {delta.get('current_source') or 'n/a'}")
        lines.append(f"- previous_title: {delta.get('previous_title') or 'n/a'}")
        lines.append(f"- current_title: {delta.get('current_title') or 'n/a'}")
        if not delta.get("has_changes"):
            lines.append("- no_top_priority_action_change_detected")
    lines.append("")


def append_selected_outcome_contract_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    lines.append("## Selected Outcome Contract Delta")
    if not delta.get("available"):
        lines.append(f"- unavailable: {delta.get('reason')}")
    else:
        fields = [
            "previous_focus_ticker",
            "current_focus_ticker",
            "previous_focus_cycle_status",
            "current_focus_cycle_status",
            "previous_focus_overall_contract_verdict",
            "current_focus_overall_contract_verdict",
            "previous_focus_next_day_contract_verdict",
            "current_focus_next_day_contract_verdict",
            "previous_focus_t_plus_2_contract_verdict",
            "current_focus_t_plus_2_contract_verdict",
        ]
        for field in fields:
            lines.append(f"- {field}: {delta.get(field) or 'n/a'}")
        if not delta.get("has_changes"):
            lines.append("- no_selected_outcome_contract_change_detected")
    lines.append("")


def append_carryover_peer_proof_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    lines.append("## Carryover Peer Proof Delta")
    if not delta.get("available"):
        lines.append(f"- unavailable: {delta.get('reason')}")
    else:
        fields = [
            "previous_focus_ticker",
            "current_focus_ticker",
            "previous_focus_proof_verdict",
            "current_focus_proof_verdict",
            "previous_focus_promotion_review_verdict",
            "current_focus_promotion_review_verdict",
            "previous_ready_for_promotion_review_tickers",
            "current_ready_for_promotion_review_tickers",
        ]
        for field in fields:
            lines.append(f"- {field}: {delta.get(field) or 'n/a'}")
        for ticker in list(delta.get("added_ready_for_promotion_review_tickers") or []):
            lines.append(f"- added_ready_for_promotion_review_ticker: {ticker}")
        for ticker in list(delta.get("removed_ready_for_promotion_review_tickers") or []):
            lines.append(f"- removed_ready_for_promotion_review_ticker: {ticker}")
        if not delta.get("has_changes"):
            lines.append("- no_carryover_peer_proof_change_detected")
    lines.append("")


def append_carryover_promotion_gate_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    lines.append("## Carryover Promotion Gate Delta")
    if not delta.get("available"):
        lines.append(f"- unavailable: {delta.get('reason')}")
    else:
        fields = [
            "previous_focus_ticker",
            "current_focus_ticker",
            "previous_focus_gate_verdict",
            "current_focus_gate_verdict",
            "previous_selected_contract_verdict",
            "current_selected_contract_verdict",
            "previous_ready_tickers",
            "current_ready_tickers",
        ]
        for field in fields:
            lines.append(f"- {field}: {delta.get(field) or 'n/a'}")
        for ticker in list(delta.get("added_ready_tickers") or []):
            lines.append(f"- added_promotion_gate_ready_ticker: {ticker}")
        for ticker in list(delta.get("removed_ready_tickers") or []):
            lines.append(f"- removed_promotion_gate_ready_ticker: {ticker}")
        for ticker in list(delta.get("added_pending_t_plus_2_tickers") or []):
            lines.append(f"- added_pending_t_plus_2_ticker: {ticker}")
        for ticker in list(delta.get("removed_pending_t_plus_2_tickers") or []):
            lines.append(f"- removed_pending_t_plus_2_ticker: {ticker}")
        if not delta.get("has_changes"):
            lines.append("- no_carryover_promotion_gate_change_detected")
    lines.append("")


def append_governance_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    lines.append("## Governance Delta")
    if not delta.get("available"):
        lines.append(f"- unavailable: {delta.get('reason')}")
    else:
        lines.append(f"- previous_overall_verdict: {delta.get('previous_overall_verdict')}")
        lines.append(f"- current_overall_verdict: {delta.get('current_overall_verdict')}")
        lines.append(f"- waiting_lane_count_delta: {delta.get('waiting_lane_count_delta')}")
        lines.append(f"- ready_lane_count_delta: {delta.get('ready_lane_count_delta')}")
        lines.append(f"- warn_count_delta: {delta.get('warn_count_delta')}")
        lines.append(f"- fail_count_delta: {delta.get('fail_count_delta')}")
        lane_changes = list(delta.get("lane_changes") or [])
        if lane_changes:
            for item in lane_changes:
                lines.append(build_governance_lane_delta_markdown(item))
        else:
            lines.append("- no_governance_change_detected")
    lines.append("")


def build_governance_lane_delta_markdown(item: dict[str, Any]) -> str:
    extra_segments = collect_governance_lane_extra_segments(item)
    extra_suffix = f" | {' | '.join(extra_segments)}" if extra_segments else ""
    return (
        f"- lane_delta: {item.get('lane_id')} | status {item.get('previous_lane_status')} -> {item.get('current_lane_status')} "
        f"| blocker {item.get('previous_blocker')} -> {item.get('current_blocker')}{extra_suffix}"
    )


def collect_governance_lane_extra_segments(item: dict[str, Any]) -> list[str]:
    extra_segments: list[str] = []
    if item.get("previous_missing_window_count") is not None or item.get("current_missing_window_count") is not None:
        extra_segments.append(f"missing_window_count {item.get('previous_missing_window_count')} -> {item.get('current_missing_window_count')}")
    if item.get("previous_distinct_window_count_with_filtered_entries") is not None or item.get("current_distinct_window_count_with_filtered_entries") is not None:
        extra_segments.append(
            f"distinct_window_count {item.get('previous_distinct_window_count_with_filtered_entries')} -> {item.get('current_distinct_window_count_with_filtered_entries')}"
        )
    if item.get("previous_preserve_misfire_report_count") is not None or item.get("current_preserve_misfire_report_count") is not None:
        extra_segments.append(
            f"preserve_misfire_report_count {item.get('previous_preserve_misfire_report_count')} -> {item.get('current_preserve_misfire_report_count')}"
        )
    if item.get("previous_filtered_report_count") is not None or item.get("current_filtered_report_count") is not None:
        extra_segments.append(f"filtered_report_count {item.get('previous_filtered_report_count')} -> {item.get('current_filtered_report_count')}")
    if item.get("previous_upgrade_gap") or item.get("current_upgrade_gap"):
        extra_segments.append(f"upgrade_gap {item.get('previous_upgrade_gap')} -> {item.get('current_upgrade_gap')}")
    return extra_segments


def append_replay_delta_markdown(lines: list[str], delta: dict[str, Any]) -> None:
    lines.append("## Replay Delta")
    if not delta.get("available"):
        lines.append("- unavailable")
    else:
        lines.append(f"- comparison_basis: {delta.get('comparison_basis')}")
        if delta.get("comparison_basis") == "nightly_history":
            lines.append(f"- report_count_delta: {delta.get('report_count_delta')}")
            lines.append(f"- short_trade_only_report_count_delta: {delta.get('short_trade_only_report_count_delta')}")
            lines.append(f"- dual_target_report_count_delta: {delta.get('dual_target_report_count_delta')}")
            lines.append(f"- previous_latest_short_trade_report: {delta.get('previous_latest_short_trade_report')}")
            lines.append(f"- current_latest_short_trade_report: {delta.get('current_latest_short_trade_report')}")
            lines.append(f"- latest_near_miss_delta: {delta.get('latest_near_miss_delta')}")
            lines.append(f"- latest_opportunity_pool_delta: {delta.get('latest_opportunity_pool_delta')}")
        else:
            lines.append(f"- current_report_dir: {delta.get('current_report_dir')}")
            lines.append(f"- previous_report_dir: {delta.get('previous_report_dir')}")
            lines.append(f"- summary_delta: {delta.get('summary_delta')}")
    lines.append("")


def append_open_ready_fast_links_markdown(
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


def render_btst_open_ready_delta_markdown(
    payload: dict[str, Any],
    *,
    output_parent: str | Path,
    relative_link: RelativeLink,
) -> str:
    resolved_output_parent = Path(output_parent).expanduser().resolve()
    current_reference = dict(payload.get("current_reference") or {})
    previous_reference = dict(payload.get("previous_reference") or {})
    priority_delta = dict(payload.get("priority_delta") or {})
    catalyst_frontier_delta = dict(payload.get("catalyst_frontier_delta") or {})
    score_fail_frontier_delta = dict(payload.get("score_fail_frontier_delta") or {})
    top_priority_action_delta = dict(payload.get("top_priority_action_delta") or {})
    selected_outcome_contract_delta = dict(payload.get("selected_outcome_contract_delta") or {})
    carryover_peer_proof_delta = dict(payload.get("carryover_peer_proof_delta") or {})
    carryover_promotion_gate_delta = dict(payload.get("carryover_promotion_gate_delta") or {})
    governance_delta = dict(payload.get("governance_delta") or {})
    replay_delta = dict(payload.get("replay_delta") or {})
    material_change_anchor = dict(payload.get("material_change_anchor") or {})
    source_paths = dict(payload.get("source_paths") or {})

    lines: list[str] = []
    append_open_ready_overview_markdown(lines, payload, current_reference, previous_reference)
    append_material_change_anchor_markdown(lines, material_change_anchor, resolved_output_parent, relative_link=relative_link)
    append_priority_delta_markdown(lines, priority_delta)
    append_catalyst_frontier_delta_markdown(lines, catalyst_frontier_delta)
    append_score_fail_frontier_delta_markdown(lines, score_fail_frontier_delta)
    append_top_priority_action_delta_markdown(lines, top_priority_action_delta)
    append_selected_outcome_contract_delta_markdown(lines, selected_outcome_contract_delta)
    append_carryover_peer_proof_delta_markdown(lines, carryover_peer_proof_delta)
    append_carryover_promotion_gate_delta_markdown(lines, carryover_promotion_gate_delta)
    append_governance_delta_markdown(lines, governance_delta)
    append_replay_delta_markdown(lines, replay_delta)
    append_open_ready_fast_links_markdown(lines, source_paths, resolved_output_parent, relative_link=relative_link)
    return "\n".join(lines) + "\n"
