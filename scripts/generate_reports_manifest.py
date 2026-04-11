from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.analyze_catalyst_theme_frontier import generate_catalyst_theme_frontier_artifacts
from scripts.btst_report_utils import discover_report_dirs as _discover_btst_report_dirs, load_json as _load_json, normalize_trade_date as _normalize_trade_date
from scripts.analyze_btst_candidate_entry_rollout_governance import (
    analyze_btst_candidate_entry_rollout_governance,
    render_btst_candidate_entry_rollout_governance_markdown,
)
from scripts.analyze_btst_candidate_entry_window_scan import (
    analyze_btst_candidate_entry_window_scan,
    render_btst_candidate_entry_window_scan_markdown,
)
from scripts.analyze_btst_no_candidate_entry_action_board import (
    analyze_btst_no_candidate_entry_action_board,
    render_btst_no_candidate_entry_action_board_markdown,
)
from scripts.analyze_btst_no_candidate_entry_failure_dossier import (
    analyze_btst_no_candidate_entry_failure_dossier,
    render_btst_no_candidate_entry_failure_dossier_markdown,
)
from scripts.analyze_btst_no_candidate_entry_replay_bundle import (
    analyze_btst_no_candidate_entry_replay_bundle,
    render_btst_no_candidate_entry_replay_bundle_markdown,
)
from scripts.analyze_btst_watchlist_recall_dossier import (
    analyze_btst_watchlist_recall_dossier,
    render_btst_watchlist_recall_dossier_markdown,
)
from scripts.analyze_btst_candidate_pool_recall_dossier import (
    analyze_btst_candidate_pool_recall_dossier,
    render_btst_candidate_pool_recall_dossier_markdown,
)
from scripts.analyze_btst_candidate_pool_branch_priority_board import (
    analyze_btst_candidate_pool_branch_priority_board,
    render_btst_candidate_pool_branch_priority_board_markdown,
)
from scripts.analyze_btst_candidate_pool_lane_objective_support import (
    analyze_btst_candidate_pool_lane_objective_support,
    render_btst_candidate_pool_lane_objective_support_markdown,
)
from scripts.analyze_btst_candidate_pool_rebucket_objective_validation import (
    analyze_btst_candidate_pool_rebucket_objective_validation,
    render_btst_candidate_pool_rebucket_objective_validation_markdown,
)
from scripts.analyze_btst_primary_roll_forward import (
    analyze_btst_primary_roll_forward,
    render_btst_primary_roll_forward_markdown,
)
from scripts.analyze_btst_primary_window_gap import (
    analyze_btst_primary_window_gap,
    render_btst_primary_window_gap_markdown,
)
from scripts.analyze_btst_primary_window_validation_runbook import (
    analyze_btst_primary_window_validation_runbook,
    render_btst_primary_window_validation_runbook_markdown,
)
from scripts.analyze_btst_recurring_shadow_runbook import (
    analyze_btst_recurring_shadow_runbook,
    render_btst_recurring_shadow_runbook_markdown,
)
from scripts.analyze_btst_governance_synthesis import (
    analyze_btst_governance_synthesis,
    render_btst_governance_synthesis_markdown,
)
from scripts.analyze_btst_rollout_governance_board import (
    analyze_btst_rollout_governance_board,
    render_btst_rollout_governance_board_markdown,
)
from scripts.analyze_btst_replay_cohort import (
    analyze_btst_replay_cohort,
    render_btst_replay_cohort_markdown,
)
from scripts.analyze_btst_tradeable_opportunity_pool import (
    generate_btst_tradeable_opportunity_pool_artifacts,
    load_btst_tradeable_opportunity_artifacts,
    summarize_btst_tradeable_opportunity_artifacts,
)
from scripts.analyze_btst_independent_window_monitor import (
    analyze_btst_independent_window_monitor,
    render_btst_independent_window_monitor_markdown,
)
from scripts.analyze_btst_tplus1_tplus2_objective_monitor import (
    analyze_btst_tplus1_tplus2_objective_monitor,
    render_btst_tplus1_tplus2_objective_monitor_markdown,
)
from scripts.analyze_multi_window_short_trade_role_candidates import (
    analyze_multi_window_short_trade_role_candidates,
    render_multi_window_short_trade_role_candidates_markdown,
)
from scripts.analyze_recurring_frontier_transition_candidates import (
    analyze_recurring_frontier_transition_candidates,
    render_recurring_frontier_transition_candidates_markdown,
)
from scripts.analyze_short_trade_boundary_recurring_frontier_cases import (
    analyze_short_trade_boundary_recurring_frontier_cases,
    render_short_trade_boundary_recurring_frontier_markdown,
)
from scripts.analyze_short_trade_boundary_score_failures import (
    analyze_short_trade_boundary_score_failures,
    render_short_trade_boundary_score_failure_markdown,
)
from scripts.analyze_short_trade_boundary_score_failures_frontier import (
    analyze_short_trade_boundary_score_failures_frontier,
    render_short_trade_boundary_score_failure_frontier_markdown,
)
from scripts.run_btst_candidate_pool_rebucket_shadow_pack import (
    render_btst_candidate_pool_rebucket_shadow_pack_markdown,
    run_btst_candidate_pool_rebucket_shadow_pack,
)
from scripts.run_btst_candidate_pool_corridor_validation_pack import (
    analyze_btst_candidate_pool_corridor_validation_pack,
    render_btst_candidate_pool_corridor_validation_pack_markdown,
)
from scripts.run_btst_candidate_pool_corridor_shadow_pack import (
    analyze_btst_candidate_pool_corridor_shadow_pack,
    render_btst_candidate_pool_corridor_shadow_pack_markdown,
)
from scripts.run_btst_candidate_pool_lane_pair_board import (
    analyze_btst_candidate_pool_lane_pair_board,
    render_btst_candidate_pool_lane_pair_board_markdown,
)
from scripts.run_btst_candidate_pool_upstream_handoff_board import (
    analyze_btst_candidate_pool_upstream_handoff_board,
    render_btst_candidate_pool_upstream_handoff_board_markdown,
)
from scripts.run_btst_candidate_pool_corridor_uplift_runbook import (
    analyze_btst_candidate_pool_corridor_uplift_runbook,
    render_btst_candidate_pool_corridor_uplift_runbook_markdown,
)
from scripts.run_btst_candidate_pool_rebucket_comparison_bundle import (
    analyze_btst_candidate_pool_rebucket_comparison_bundle,
    render_btst_candidate_pool_rebucket_comparison_bundle_markdown,
)
from scripts.btst_selected_focus import pick_selected_focus_entry
from scripts.validate_btst_governance_consistency import (
    render_btst_governance_validation_markdown,
    validate_btst_governance_consistency,
)


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "report_manifest_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "report_manifest_latest.md"


def _optional_report_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    payload = _load_json(resolved)
    return payload if isinstance(payload, dict) else {}


def _find_focus_entry(entries: list[dict[str, Any]], focus_ticker: Any) -> dict[str, Any]:
    focus_ticker_str = str(focus_ticker or "").strip()
    if focus_ticker_str:
        for entry in entries:
            if str((entry or {}).get("ticker") or "").strip() == focus_ticker_str:
                return dict(entry or {})
    return dict(entries[0] or {}) if entries else {}


def _build_continuation_focus_summary(reports_root: Path) -> dict[str, Any]:
    promotion_review = _optional_report_json(reports_root / "btst_tplus2_continuation_promotion_review_latest.json")
    promotion_gate = _optional_report_json(reports_root / "btst_tplus2_continuation_promotion_gate_latest.json")
    watchlist_execution = _optional_report_json(reports_root / "btst_tplus2_continuation_watchlist_execution_latest.json")
    eligible_gate = _optional_report_json(reports_root / "btst_tplus2_continuation_eligible_gate_latest.json")
    execution_gate = _optional_report_json(reports_root / "btst_tplus2_continuation_execution_gate_latest.json")
    execution_overlay = _optional_report_json(reports_root / "btst_tplus2_continuation_execution_overlay_latest.json")
    governance_board = _optional_report_json(reports_root / "btst_tplus2_continuation_governance_board_latest.json")
    watchboard = _optional_report_json(reports_root / "btst_tplus2_continuation_watchboard_latest.json")
    focus_ticker = str(
        promotion_review.get("focus_ticker")
        or promotion_gate.get("focus_ticker")
        or watchlist_execution.get("focus_ticker")
        or governance_board.get("focus_promotion_ticker")
        or ""
    ).strip()
    if not focus_ticker:
        return {}
    adopted_watch_row = dict(watchlist_execution.get("adopted_watch_row") or {})
    adopted_execution_row = dict(execution_overlay.get("adopted_execution_row") or {})
    return {
        "focus_ticker": focus_ticker,
        "promotion_review_verdict": promotion_review.get("promotion_review_verdict"),
        "promotion_gate_verdict": promotion_gate.get("gate_verdict"),
        "watchlist_execution_verdict": watchlist_execution.get("execution_verdict"),
        "focus_watch_validation_status": adopted_watch_row.get("watchlist_validation_status"),
        "focus_watch_recent_supporting_window_count": adopted_watch_row.get("recent_supporting_window_count"),
        "focus_watch_recent_window_count": adopted_watch_row.get("recent_window_count"),
        "focus_watch_recent_support_ratio": adopted_watch_row.get("recent_support_ratio"),
        "eligible_gate_verdict": eligible_gate.get("gate_verdict"),
        "execution_gate_verdict": execution_gate.get("gate_verdict"),
        "execution_gate_blockers": execution_gate.get("gate_blockers"),
        "execution_overlay_verdict": execution_overlay.get("execution_verdict"),
        "execution_overlay_promotion_blocker": adopted_execution_row.get("promotion_blocker"),
        "execution_overlay_persistence_requirement": adopted_execution_row.get("persistence_requirement"),
        "execution_overlay_independent_edge_requirement": adopted_execution_row.get("independent_edge_requirement"),
        "execution_overlay_lane_support_ratio": adopted_execution_row.get("lane_support_ratio"),
        "execution_overlay_t_plus_2_mean_gap_vs_watch": adopted_execution_row.get("t_plus_2_mean_gap_vs_watch"),
        "execution_overlay_next_step": adopted_execution_row.get("next_step"),
        "governance_status": governance_board.get("governance_status"),
        "watchboard_status": watchboard.get("governance_status"),
    }


def _build_transient_probe_summary(reports_root: Path) -> dict[str, Any]:
    upstream_handoff = _optional_report_json(reports_root / "btst_candidate_pool_upstream_handoff_board_latest.json")
    board_rows = list(upstream_handoff.get("board_rows") or [])
    transient_rows = [dict(row or {}) for row in board_rows if str(row.get("board_phase") or "") == "historical_shadow_probe_gap"]
    if not transient_rows:
        return {}
    focus_row = transient_rows[0]
    return {
        "ticker": focus_row.get("ticker"),
        "status": focus_row.get("downstream_followup_status"),
        "blocker": focus_row.get("downstream_followup_blocker"),
        "candidate_source": focus_row.get("latest_followup_candidate_source"),
        "score_state": dict(focus_row.get("latest_followup_gate_status") or {}).get("score"),
        "downstream_bottleneck": focus_row.get("latest_followup_downstream_bottleneck"),
        "historical_sample_count": focus_row.get("latest_followup_historical_sample_count"),
        "historical_next_close_positive_rate": focus_row.get("latest_followup_historical_next_close_positive_rate"),
        "historical_next_close_return_mean": focus_row.get("latest_followup_historical_next_close_return_mean"),
        "next_step": focus_row.get("next_step"),
    }


def _build_execution_constraint_rollup(reports_root: Path) -> dict[str, Any]:
    governance_synthesis = _optional_report_json(reports_root / "btst_governance_synthesis_latest.json")
    constraints = [dict(row or {}) for row in list(governance_synthesis.get("execution_surface_constraints") or [])]
    if not constraints:
        return {}
    continuation_constraints = [
        row for row in constraints if str(row.get("status") or "").strip() == "continuation_only_confirm_then_review"
    ]
    shadow_constraints = [
        row for row in constraints if str(row.get("status") or "").strip() == "shadow_recall_not_execution_ready"
    ]
    return {
        "constraint_count": len(constraints),
        "continuation_focus_tickers": [ticker for row in continuation_constraints for ticker in list(row.get("focus_tickers") or [])[:3]][:3],
        "continuation_blockers": [str(row.get("blocker") or "") for row in continuation_constraints if str(row.get("blocker") or "").strip()][:3],
        "shadow_focus_tickers": [ticker for row in shadow_constraints for ticker in list(row.get("focus_tickers") or [])[:3]][:3],
        "shadow_blockers": [str(row.get("blocker") or "") for row in shadow_constraints if str(row.get("blocker") or "").strip()][:3],
        "top_recommendations": [str(row.get("recommendation") or "") for row in constraints if str(row.get("recommendation") or "").strip()][:3],
    }


def _qualify_continuation_window_focus_entries(entries: list[dict[str, Any]], focus_ticker: str) -> dict[str, Any]:
    focus_entries = [dict(entry or {}) for entry in entries if str(dict(entry or {}).get("ticker") or "").strip() == focus_ticker]
    focus_buckets = sorted({str(entry.get("bucket") or "").strip() for entry in focus_entries if str(entry.get("bucket") or "").strip()})
    qualifying_bucket_allowlist = ["near_miss_entries", "selected_entries"]
    merge_review_bucket_allowlist = ["selected_entries"]
    has_bucket_data = bool(focus_buckets)
    qualifies = bool(focus_entries) and (
        not has_bucket_data or any(bucket in qualifying_bucket_allowlist for bucket in focus_buckets)
    )
    merge_review_qualifies = bool(focus_entries) and (
        not has_bucket_data or any(bucket in merge_review_bucket_allowlist for bucket in focus_buckets)
    )
    return {
        "focus_entries": focus_entries,
        "focus_buckets": focus_buckets,
        "has_bucket_data": has_bucket_data,
        "qualifies": qualifies,
        "qualifying_bucket_allowlist": qualifying_bucket_allowlist,
        "merge_review_qualifies": merge_review_qualifies,
        "merge_review_bucket_allowlist": merge_review_bucket_allowlist,
    }


def _window_supports_selected_merge_review(window: dict[str, Any]) -> bool:
    entry = dict(window or {})
    decision = str(entry.get("decision") or "").strip()
    if decision == "selected":
        return True
    tier_set = {str(item).strip() for item in list(entry.get("tier_set") or []) if str(item).strip()}
    return "governance_followup_selected" in tier_set or "selected_entries" in tier_set


def _extract_candidate_dossier_support_trade_dates(reports_root: Path, focus_ticker: str) -> dict[str, Any]:
    if not focus_ticker:
        return {}
    dossier = _optional_report_json(reports_root / f"btst_tplus2_candidate_dossier_{focus_ticker}_latest.json")
    if not dossier:
        return {}

    supporting_windows = [
        dict(item or {})
        for item in list(dossier.get("recent_window_summaries") or dossier.get("per_window_summaries") or [])
        if bool(dict(item or {}).get("supporting_window"))
    ]
    supporting_trade_dates: list[str] = []
    for item in supporting_windows:
        report_label = _normalize_trade_date(item.get("report_label"))
        if report_label:
            supporting_trade_dates.append(report_label)
    distinct_trade_dates = sorted(set(supporting_trade_dates))
    selected_supporting_windows = [item for item in supporting_windows if _window_supports_selected_merge_review(item)]
    selected_support_trade_dates: list[str] = []
    for item in selected_supporting_windows:
        report_label = _normalize_trade_date(item.get("report_label"))
        if report_label:
            selected_support_trade_dates.append(report_label)
    distinct_selected_trade_dates = sorted(set(selected_support_trade_dates))
    same_trade_date_variant_count = max(len(supporting_windows) - len(distinct_trade_dates), 0)
    same_trade_date_variant_credit = round(min(0.75, same_trade_date_variant_count * 0.25), 4)
    return {
        "recent_supporting_window_count": int(dossier.get("recent_supporting_window_count") or 0),
        "recent_window_count": int(dossier.get("recent_window_count") or 0),
        "recent_validation_verdict": str(dossier.get("recent_validation_verdict") or "").strip() or None,
        "recent_tier_verdict": str(dossier.get("recent_tier_verdict") or "").strip() or None,
        "supporting_trade_dates": distinct_trade_dates,
        "supporting_trade_date_count": len(distinct_trade_dates),
        "selected_support_trade_dates": distinct_selected_trade_dates,
        "selected_support_trade_date_count": len(distinct_selected_trade_dates),
        "supporting_window_variant_count": len(supporting_windows),
        "same_trade_date_variant_count": same_trade_date_variant_count,
        "same_trade_date_variant_credit": same_trade_date_variant_credit,
        "current_plan_visibility_summary": dict(dossier.get("current_plan_visibility_summary") or {}),
    }


def _continuation_bucket_rank(bucket_name: str | None) -> int:
    return {
        "selected_entries": 3,
        "near_miss_entries": 2,
        "opportunity_pool_entries": 1,
        "rejected_entries": 0,
    }.get(str(bucket_name or "").strip(), -1)


def _collapse_same_trade_date_followups_for_focus(followups: list[dict[str, Any]], focus_ticker: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for followup in followups:
        row = dict(followup or {})
        group_key = str(row.get("trade_date") or row.get("report_dir") or "").strip()
        grouped.setdefault(group_key, []).append(row)

    collapsed: list[dict[str, Any]] = []
    for group_key, rows in grouped.items():
        best_row: dict[str, Any] | None = None
        best_entry: dict[str, Any] | None = None
        best_rank: tuple[Any, ...] | None = None
        for row in rows:
            entries = [dict(entry or {}) for entry in list(row.get("entries") or [])]
            focus_entries = [entry for entry in entries if str(entry.get("ticker") or "").strip() == focus_ticker]
            if not focus_entries:
                continue
            entry = max(
                focus_entries,
                key=lambda candidate: (
                    _continuation_bucket_rank(candidate.get("bucket")),
                    float(candidate.get("score_target") or -999.0),
                ),
            )
            rank = (
                _continuation_bucket_rank(entry.get("bucket")),
                float(entry.get("score_target") or -999.0),
                str(row.get("report_dir") or ""),
            )
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_row = row
                best_entry = entry
        if best_row is None or best_entry is None:
            continue
        collapsed.append(
            {
                "trade_date": best_row.get("trade_date"),
                "report_dir": best_row.get("report_dir"),
                "entries": [best_entry],
            }
        )
    collapsed.sort(key=lambda row: (str(row.get("trade_date") or ""), str(row.get("report_dir") or "")))
    return collapsed


def _collect_continuation_promotion_followup_evidence(
    governance_synthesis: dict[str, Any],
    *,
    focus_ticker: str,
) -> dict[str, Any]:
    evidence_trade_dates: list[str] = []
    evidence_report_dirs: list[str] = []
    merge_review_evidence_trade_dates: list[str] = []
    merge_review_evidence_report_dirs: list[str] = []
    disqualified_trade_dates: list[str] = []
    qualifying_window_buckets: list[str] = []
    merge_review_window_buckets: list[str] = []
    disqualified_window_buckets: list[str] = []
    qualifying_bucket_allowlist: list[str] = ["near_miss_entries", "selected_entries"]
    merge_review_bucket_allowlist: list[str] = ["selected_entries"]
    collapsed_followups = _collapse_same_trade_date_followups_for_focus(
        list(governance_synthesis.get("evidence_btst_followups") or []),
        focus_ticker,
    )
    for followup in collapsed_followups:
        row = dict(followup or {})
        entries = [dict(entry or {}) for entry in list(row.get("entries") or [])]
        qualification = _qualify_continuation_window_focus_entries(entries, focus_ticker)
        focus_entries = list(qualification.get("focus_entries") or [])
        if not focus_entries:
            continue

        trade_date = str(row.get("trade_date") or "").strip()
        report_dir = str(row.get("report_dir") or "").strip()
        focus_buckets = list(qualification.get("focus_buckets") or [])
        qualifying_bucket_allowlist = list(qualification.get("qualifying_bucket_allowlist") or qualifying_bucket_allowlist)
        merge_review_bucket_allowlist = list(qualification.get("merge_review_bucket_allowlist") or merge_review_bucket_allowlist)

        if qualification.get("qualifies"):
            qualifying_window_buckets.extend(focus_buckets)
            if trade_date:
                evidence_trade_dates.append(trade_date)
            if report_dir:
                evidence_report_dirs.append(report_dir)
        if qualification.get("merge_review_qualifies"):
            merge_review_window_buckets.extend(focus_buckets)
            if trade_date:
                merge_review_evidence_trade_dates.append(trade_date)
            if report_dir:
                merge_review_evidence_report_dirs.append(report_dir)
            continue

        disqualified_window_buckets.extend(focus_buckets)
        if trade_date:
            disqualified_trade_dates.append(trade_date)

    return {
        "evidence_trade_dates": sorted(set(evidence_trade_dates)),
        "evidence_report_dirs": sorted(set(evidence_report_dirs)),
        "merge_review_evidence_trade_dates": sorted(set(merge_review_evidence_trade_dates)),
        "merge_review_evidence_report_dirs": sorted(set(merge_review_evidence_report_dirs)),
        "disqualified_trade_dates": sorted(set(disqualified_trade_dates)),
        "qualifying_window_buckets": sorted(set(qualifying_window_buckets)),
        "merge_review_window_buckets": sorted(set(merge_review_window_buckets)),
        "disqualified_window_buckets": sorted(set(disqualified_window_buckets)),
        "qualifying_bucket_allowlist": qualifying_bucket_allowlist,
        "merge_review_bucket_allowlist": merge_review_bucket_allowlist,
    }


def _build_continuation_promotion_edge_summary(
    adopted_execution_row: dict[str, Any],
    objective_monitor: dict[str, Any],
) -> dict[str, Any]:
    required_positive_rate_delta = 0.1
    required_mean_return_delta = 0.02
    tradeable_surface = dict(objective_monitor.get("tradeable_surface") or {})
    focus_positive_rate = adopted_execution_row.get("t_plus_2_close_positive_rate")
    default_positive_rate = tradeable_surface.get("t_plus_2_positive_rate")
    focus_mean_return = adopted_execution_row.get("t_plus_2_close_return_mean")
    default_mean_return = tradeable_surface.get("mean_t_plus_2_return")
    positive_rate_delta = (
        round(float(focus_positive_rate) - float(default_positive_rate), 4)
        if focus_positive_rate is not None and default_positive_rate is not None
        else None
    )
    mean_return_delta = (
        round(float(focus_mean_return) - float(default_mean_return), 4)
        if focus_mean_return is not None and default_mean_return is not None
        else None
    )
    if positive_rate_delta is None or mean_return_delta is None:
        edge_verdict = "insufficient_default_btst_edge_data"
    elif positive_rate_delta > 0 and mean_return_delta > 0:
        edge_verdict = "provisionally_outperforming_default_btst"
    elif positive_rate_delta > 0 or mean_return_delta > 0:
        edge_verdict = "mixed_edge_vs_default_btst"
    else:
        edge_verdict = "not_outperforming_default_btst"

    positive_rate_delta_gap_to_threshold = (
        round(required_positive_rate_delta - float(positive_rate_delta), 4) if positive_rate_delta is not None else None
    )
    mean_return_delta_gap_to_threshold = (
        round(required_mean_return_delta - float(mean_return_delta), 4) if mean_return_delta is not None else None
    )
    if positive_rate_delta is None or mean_return_delta is None:
        edge_threshold_verdict = "insufficient_default_btst_edge_data"
    elif positive_rate_delta >= required_positive_rate_delta and mean_return_delta >= required_mean_return_delta:
        edge_threshold_verdict = "edge_threshold_satisfied"
    elif positive_rate_delta >= required_positive_rate_delta:
        edge_threshold_verdict = "mean_return_delta_below_threshold"
    elif mean_return_delta >= required_mean_return_delta:
        edge_threshold_verdict = "positive_rate_delta_below_threshold"
    else:
        edge_threshold_verdict = "edge_threshold_not_satisfied"

    return {
        "required_positive_rate_delta": required_positive_rate_delta,
        "required_mean_return_delta": required_mean_return_delta,
        "focus_positive_rate": focus_positive_rate,
        "default_positive_rate": default_positive_rate,
        "positive_rate_delta": positive_rate_delta,
        "positive_rate_delta_gap_to_threshold": positive_rate_delta_gap_to_threshold,
        "focus_mean_return": focus_mean_return,
        "default_mean_return": default_mean_return,
        "mean_return_delta": mean_return_delta,
        "mean_return_delta_gap_to_threshold": mean_return_delta_gap_to_threshold,
        "edge_verdict": edge_verdict,
        "edge_threshold_verdict": edge_threshold_verdict,
    }


def _build_continuation_promotion_path_summary(
    *,
    observed_window_count: int,
    target_window_count: int,
    edge_threshold_verdict: str,
    distinct_trade_dates: list[str],
) -> dict[str, Any]:
    missing_window_count = max(target_window_count - observed_window_count, 0)
    persistence_verdict = (
        "independent_window_requirement_satisfied"
        if observed_window_count >= target_window_count
        else "await_additional_independent_window_persistence"
    )
    if persistence_verdict != "independent_window_requirement_satisfied":
        promotion_merge_review_verdict = "await_additional_independent_window_persistence"
    elif edge_threshold_verdict != "edge_threshold_satisfied":
        promotion_merge_review_verdict = "await_stronger_edge_vs_default_btst"
    else:
        promotion_merge_review_verdict = "ready_for_default_btst_merge_review"

    unresolved_requirements: list[str] = []
    if missing_window_count > 0:
        unresolved_requirements.append("new_independent_trade_date")
    if edge_threshold_verdict != "edge_threshold_satisfied":
        unresolved_requirements.append("edge_threshold_vs_default_btst")
    ready_after_next_qualifying_window = bool(
        missing_window_count == 1 and edge_threshold_verdict == "edge_threshold_satisfied"
    )
    promotion_path_status = (
        "merge_review_ready"
        if promotion_merge_review_verdict == "ready_for_default_btst_merge_review"
        else (
            "one_qualifying_window_away"
            if ready_after_next_qualifying_window
            else (
                "collect_more_independent_windows"
                if missing_window_count > 0
                else "repair_edge_threshold"
            )
        )
    )
    next_window_requirement = (
        "capture_one_new_independent_trade_date_with_edge_thresholds_still_satisfied"
        if ready_after_next_qualifying_window
        else "collect_additional_independent_window_and_recheck_edge_thresholds"
    )
    next_window_trade_date_rule = (
        f"must be a new trade_date outside {distinct_trade_dates}"
        if distinct_trade_dates
        else "must be a newly observed independent continuation trade_date"
    )
    next_window_qualified_merge_review_verdict = (
        "ready_for_default_btst_merge_review"
        if ready_after_next_qualifying_window
        else (
            "await_additional_independent_window_persistence"
            if missing_window_count > 1
            else promotion_merge_review_verdict
        )
    )
    next_step = (
        "Wait for one more independent continuation window before governance can evaluate merge readiness."
        if promotion_merge_review_verdict == "await_additional_independent_window_persistence"
        else (
            "Independent-window requirement is satisfied; keep the lane isolated until its edge exceeds the default BTST merge thresholds."
            if promotion_merge_review_verdict == "await_stronger_edge_vs_default_btst"
            else "Independent-window and edge thresholds are satisfied; governance can review whether the continuation lane is ready to merge into default BTST."
        )
    )

    return {
        "missing_window_count": missing_window_count,
        "persistence_verdict": persistence_verdict,
        "promotion_merge_review_verdict": promotion_merge_review_verdict,
        "unresolved_requirements": unresolved_requirements,
        "blockers_remaining_count": len(unresolved_requirements),
        "ready_after_next_qualifying_window": ready_after_next_qualifying_window,
        "promotion_path_status": promotion_path_status,
        "next_window_requirement": next_window_requirement,
        "next_window_trade_date_rule": next_window_trade_date_rule,
        "next_window_duplicate_trade_date_verdict": "independent_window_count_unchanged",
        "next_window_quality_requirement": "must land in selected_entries",
        "next_window_disqualified_bucket_verdict": "await_higher_quality_window_bucket",
        "next_window_edge_regression_merge_review_verdict": "await_stronger_edge_vs_default_btst",
        "next_window_qualified_merge_review_verdict": next_window_qualified_merge_review_verdict,
        "next_step": next_step,
    }


def _build_continuation_promotion_ready_summary(reports_root: Path) -> dict[str, Any]:
    execution_overlay = _optional_report_json(reports_root / "btst_tplus2_continuation_execution_overlay_latest.json")
    governance_synthesis = _optional_report_json(reports_root / "btst_governance_synthesis_latest.json")
    objective_monitor = _optional_report_json(reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json")
    adopted_execution_row = dict(execution_overlay.get("adopted_execution_row") or {})
    focus_ticker = str(execution_overlay.get("focus_ticker") or adopted_execution_row.get("ticker") or "").strip()
    if not focus_ticker:
        return {}

    followup_summary = _collect_continuation_promotion_followup_evidence(
        governance_synthesis,
        focus_ticker=focus_ticker,
    )
    distinct_trade_dates = list(followup_summary.get("evidence_trade_dates") or [])
    distinct_report_dirs = list(followup_summary.get("evidence_report_dirs") or [])
    distinct_merge_review_trade_dates = list(followup_summary.get("merge_review_evidence_trade_dates") or [])
    distinct_merge_review_report_dirs = list(followup_summary.get("merge_review_evidence_report_dirs") or [])
    distinct_disqualified_trade_dates = list(followup_summary.get("disqualified_trade_dates") or [])
    candidate_dossier_support = _extract_candidate_dossier_support_trade_dates(reports_root, focus_ticker)
    candidate_dossier_support_trade_dates = list(candidate_dossier_support.get("supporting_trade_dates") or [])
    candidate_dossier_selected_support_trade_dates = list(candidate_dossier_support.get("selected_support_trade_dates") or [])
    candidate_dossier_support_trade_date_count = int(candidate_dossier_support.get("supporting_trade_date_count") or 0)
    combined_trade_dates = sorted(set(distinct_trade_dates) | set(candidate_dossier_support_trade_dates))
    combined_merge_review_trade_dates = sorted(set(distinct_merge_review_trade_dates) | set(candidate_dossier_selected_support_trade_dates))
    target_window_count = 2
    exploratory_window_count = len(combined_trade_dates) or len(distinct_report_dirs)
    observed_window_count = len(combined_merge_review_trade_dates) or len(distinct_merge_review_report_dirs)
    candidate_dossier_same_trade_date_variant_credit = float(candidate_dossier_support.get("same_trade_date_variant_credit") or 0.0)
    current_plan_visibility_summary = dict(candidate_dossier_support.get("current_plan_visibility_summary") or {})
    weighted_observed_window_credit = round(min(float(target_window_count), observed_window_count + candidate_dossier_same_trade_date_variant_credit), 4)
    weighted_missing_window_credit = round(max(0.0, float(target_window_count) - weighted_observed_window_credit), 4)
    edge_summary = _build_continuation_promotion_edge_summary(
        adopted_execution_row,
        objective_monitor,
    )
    path_summary = _build_continuation_promotion_path_summary(
        observed_window_count=observed_window_count,
        target_window_count=target_window_count,
        edge_threshold_verdict=str(edge_summary.get("edge_threshold_verdict") or ""),
        distinct_trade_dates=distinct_trade_dates,
    )

    return {
        "focus_ticker": focus_ticker,
        "observed_independent_window_count": observed_window_count,
        "exploratory_window_count": exploratory_window_count,
        "target_independent_window_count": target_window_count,
        "missing_independent_window_count": path_summary["missing_window_count"],
        "evidence_trade_dates": distinct_trade_dates,
        "combined_evidence_trade_dates": combined_trade_dates,
        "merge_ready_evidence_trade_dates": distinct_merge_review_trade_dates,
        "combined_merge_ready_evidence_trade_dates": combined_merge_review_trade_dates,
        "qualifying_bucket_allowlist": followup_summary["qualifying_bucket_allowlist"],
        "qualifying_window_buckets": followup_summary["qualifying_window_buckets"],
        "merge_review_bucket_allowlist": followup_summary["merge_review_bucket_allowlist"],
        "merge_ready_window_buckets": followup_summary["merge_review_window_buckets"],
        "disqualified_window_trade_dates": distinct_disqualified_trade_dates,
        "disqualified_window_buckets": followup_summary["disqualified_window_buckets"],
        "candidate_dossier_support_trade_dates": candidate_dossier_support_trade_dates,
        "candidate_dossier_support_trade_date_count": candidate_dossier_support_trade_date_count,
        "candidate_dossier_selected_support_trade_dates": candidate_dossier_selected_support_trade_dates,
        "candidate_dossier_selected_support_trade_date_count": int(candidate_dossier_support.get("selected_support_trade_date_count") or 0),
        "candidate_dossier_supporting_window_variant_count": int(candidate_dossier_support.get("supporting_window_variant_count") or 0),
        "candidate_dossier_same_trade_date_variant_count": int(candidate_dossier_support.get("same_trade_date_variant_count") or 0),
        "candidate_dossier_same_trade_date_variant_credit": candidate_dossier_same_trade_date_variant_credit,
        "candidate_dossier_current_plan_visible_trade_dates": list(current_plan_visibility_summary.get("current_plan_visible_trade_dates") or []),
        "candidate_dossier_current_plan_visible_trade_date_count": int(current_plan_visibility_summary.get("current_plan_visible_trade_date_count") or 0),
        "candidate_dossier_current_plan_visibility_gap_trade_dates": list(current_plan_visibility_summary.get("current_plan_visibility_gap_trade_dates") or []),
        "candidate_dossier_current_plan_visibility_gap_trade_date_count": int(current_plan_visibility_summary.get("current_plan_visibility_gap_trade_date_count") or 0),
        "candidate_dossier_raw_daily_events_trade_dates": list(current_plan_visibility_summary.get("raw_daily_events_trade_dates") or []),
        "candidate_dossier_raw_daily_events_trade_date_count": int(current_plan_visibility_summary.get("raw_daily_events_trade_date_count") or 0),
        "candidate_dossier_recent_supporting_window_count": int(candidate_dossier_support.get("recent_supporting_window_count") or 0),
        "candidate_dossier_recent_window_count": int(candidate_dossier_support.get("recent_window_count") or 0),
        "candidate_dossier_recent_validation_verdict": candidate_dossier_support.get("recent_validation_verdict"),
        "candidate_dossier_recent_tier_verdict": candidate_dossier_support.get("recent_tier_verdict"),
        "weighted_observed_window_credit": weighted_observed_window_credit,
        "weighted_missing_window_credit": weighted_missing_window_credit,
        "promotion_path_status": path_summary["promotion_path_status"],
        "blockers_remaining_count": path_summary["blockers_remaining_count"],
        "unresolved_requirements": path_summary["unresolved_requirements"],
        "persistence_verdict": path_summary["persistence_verdict"],
        "provisional_default_btst_edge_verdict": edge_summary["edge_verdict"],
        "required_positive_rate_delta_vs_default_btst": edge_summary["required_positive_rate_delta"],
        "required_mean_return_delta_vs_default_btst": edge_summary["required_mean_return_delta"],
        "focus_t_plus_2_positive_rate": edge_summary["focus_positive_rate"],
        "default_btst_t_plus_2_positive_rate": edge_summary["default_positive_rate"],
        "t_plus_2_positive_rate_delta_vs_default_btst": edge_summary["positive_rate_delta"],
        "t_plus_2_positive_rate_delta_gap_to_threshold": edge_summary["positive_rate_delta_gap_to_threshold"],
        "focus_t_plus_2_mean_return": edge_summary["focus_mean_return"],
        "default_btst_t_plus_2_mean_return": edge_summary["default_mean_return"],
        "t_plus_2_mean_return_delta_vs_default_btst": edge_summary["mean_return_delta"],
        "t_plus_2_mean_return_delta_gap_to_threshold": edge_summary["mean_return_delta_gap_to_threshold"],
        "edge_threshold_verdict": edge_summary["edge_threshold_verdict"],
        "promotion_merge_review_verdict": path_summary["promotion_merge_review_verdict"],
        "ready_after_next_qualifying_window": path_summary["ready_after_next_qualifying_window"],
        "next_window_requirement": path_summary["next_window_requirement"],
        "next_window_trade_date_rule": path_summary["next_window_trade_date_rule"],
        "next_window_duplicate_trade_date_verdict": path_summary["next_window_duplicate_trade_date_verdict"],
        "next_window_quality_requirement": path_summary["next_window_quality_requirement"],
        "next_window_disqualified_bucket_verdict": path_summary["next_window_disqualified_bucket_verdict"],
        "next_window_edge_regression_merge_review_verdict": path_summary["next_window_edge_regression_merge_review_verdict"],
        "next_window_qualified_merge_review_verdict": path_summary["next_window_qualified_merge_review_verdict"],
        "next_step": path_summary["next_step"],
    }


def _build_default_merge_review_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_default_merge_review_latest.json")


def _build_selected_outcome_refresh_summary(reports_root: Path) -> dict[str, Any]:
    refresh_board = _optional_report_json(reports_root / "btst_selected_outcome_refresh_board_latest.json")
    if not refresh_board:
        return {}
    entries = [dict(entry or {}) for entry in list(refresh_board.get("entries") or [])]
    focus_entry = pick_selected_focus_entry(entries)
    return {
        "trade_date": refresh_board.get("trade_date"),
        "selected_count": refresh_board.get("selected_count"),
        "current_cycle_status_counts": dict(refresh_board.get("current_cycle_status_counts") or {}),
        "focus_ticker": focus_entry.get("ticker"),
        "focus_cycle_status": focus_entry.get("current_cycle_status"),
        "focus_data_status": focus_entry.get("current_data_status"),
        "focus_next_close_return": focus_entry.get("current_next_close_return"),
        "focus_t_plus_2_close_return": focus_entry.get("current_t_plus_2_close_return"),
        "focus_historical_next_close_positive_rate": focus_entry.get("historical_next_close_positive_rate"),
        "focus_historical_t_plus_2_close_positive_rate": focus_entry.get("historical_t_plus_2_close_positive_rate"),
        "focus_next_day_contract_verdict": focus_entry.get("next_day_contract_verdict"),
        "focus_t_plus_2_contract_verdict": focus_entry.get("t_plus_2_contract_verdict"),
        "focus_overall_contract_verdict": focus_entry.get("overall_contract_verdict"),
        "recommendation": refresh_board.get("recommendation"),
    }


def _build_carryover_multiday_continuation_audit_summary(reports_root: Path) -> dict[str, Any]:
    audit = _optional_report_json(reports_root / "btst_carryover_multiday_continuation_audit_latest.json")
    if not audit:
        return {}
    policy_checks = dict(audit.get("policy_checks") or {})
    selected_historical = dict(audit.get("selected_historical_proof_summary") or {})
    broad_family_only = dict(audit.get("broad_family_only_summary") or {})
    return {
        "selected_ticker": audit.get("selected_ticker"),
        "selected_trade_date": audit.get("selected_trade_date"),
        "selected_preferred_entry_mode": audit.get("selected_preferred_entry_mode"),
        "selected_current_contract_status": audit.get("selected_current_contract_status"),
        "selected_current_data_status": audit.get("selected_current_data_status"),
        "selected_current_cycle_status": audit.get("selected_current_cycle_status"),
        "selected_current_next_trade_date": audit.get("selected_current_next_trade_date"),
        "selected_current_next_close_return": audit.get("selected_current_next_close_return"),
        "selected_current_t_plus_2_close_return": audit.get("selected_current_t_plus_2_close_return"),
        "selected_trade_anchor_date": audit.get("selected_trade_anchor_date"),
        "selected_trade_date_was_non_trading": audit.get("selected_trade_date_was_non_trading"),
        "selected_execution_quality_label": audit.get("selected_execution_quality_label"),
        "selected_entry_timing_bias": audit.get("selected_entry_timing_bias"),
        "supportive_case_count": audit.get("supportive_case_count"),
        "peer_status_counts": dict(audit.get("peer_status_counts") or {}),
        "selected_path_t2_bias_only": policy_checks.get("selected_path_t2_bias_only"),
        "broad_family_only_multiday_unsupported": policy_checks.get("broad_family_only_multiday_unsupported"),
        "aligned_peer_multiday_ready": policy_checks.get("aligned_peer_multiday_ready"),
        "open_selected_case_count": policy_checks.get("open_selected_case_count"),
        "selected_next_close_positive_rate": selected_historical.get("next_close_positive_rate"),
        "selected_t_plus_2_close_positive_rate": selected_historical.get("t_plus_2_close_positive_rate"),
        "selected_t_plus_3_close_positive_rate": selected_historical.get("t_plus_3_close_positive_rate"),
        "broad_family_only_next_close_positive_rate": broad_family_only.get("next_close_positive_rate"),
        "broad_family_only_t_plus_2_close_positive_rate": broad_family_only.get("t_plus_2_close_positive_rate"),
        "policy_recommendations": list(audit.get("policy_recommendations") or [])[:3],
        "recommendation": audit.get("recommendation"),
    }


def _build_carryover_aligned_peer_harvest_summary(reports_root: Path) -> dict[str, Any]:
    harvest = _optional_report_json(reports_root / "btst_carryover_aligned_peer_harvest_latest.json")
    if not harvest:
        return {}
    entries = [dict(entry or {}) for entry in list(harvest.get("harvest_entries") or [])]
    focus_entry = _find_focus_entry(entries, harvest.get("focus_ticker"))
    fresh_open_cycle_tickers = [
        str(entry.get("ticker") or "")
        for entry in entries
        if str(entry.get("harvest_status") or "") == "fresh_open_cycle" and entry.get("ticker")
    ][:4]
    return {
        "ticker": harvest.get("ticker"),
        "peer_row_count": harvest.get("peer_row_count"),
        "peer_count": harvest.get("peer_count"),
        "status_counts": dict(harvest.get("status_counts") or {}),
        "focus_ticker": harvest.get("focus_ticker") or focus_entry.get("ticker"),
        "focus_status": harvest.get("focus_status") or focus_entry.get("harvest_status"),
        "focus_latest_trade_date": focus_entry.get("latest_trade_date"),
        "focus_latest_scope": focus_entry.get("latest_scope"),
        "focus_closed_cycle_count": focus_entry.get("closed_cycle_count"),
        "focus_next_day_available_count": focus_entry.get("next_day_available_count"),
        "focus_recommendation": focus_entry.get("recommendation"),
        "fresh_open_cycle_tickers": fresh_open_cycle_tickers,
        "recommendation": harvest.get("recommendation"),
    }


def _build_carryover_peer_expansion_summary(reports_root: Path) -> dict[str, Any]:
    expansion = _optional_report_json(reports_root / "btst_carryover_peer_expansion_latest.json")
    if not expansion:
        return {}
    entries = [dict(entry or {}) for entry in list(expansion.get("entries") or [])]
    focus_entry = _find_focus_entry(entries, expansion.get("focus_ticker"))
    return {
        "selected_ticker": expansion.get("selected_ticker"),
        "selected_path_t2_bias_only": expansion.get("selected_path_t2_bias_only"),
        "broad_family_only_multiday_unsupported": expansion.get("broad_family_only_multiday_unsupported"),
        "peer_count": expansion.get("peer_count"),
        "expansion_status_counts": dict(expansion.get("expansion_status_counts") or {}),
        "priority_expansion_tickers": list(expansion.get("priority_expansion_tickers") or []),
        "watch_with_risk_tickers": list(expansion.get("watch_with_risk_tickers") or []),
        "focus_ticker": expansion.get("focus_ticker") or focus_entry.get("ticker"),
        "focus_status": expansion.get("focus_status") or focus_entry.get("expansion_status"),
        "focus_latest_trade_date": focus_entry.get("latest_trade_date"),
        "focus_latest_scope": focus_entry.get("latest_scope"),
        "focus_recommendation": focus_entry.get("recommendation"),
        "recommendation": expansion.get("recommendation"),
    }


def _build_carryover_aligned_peer_proof_summary(reports_root: Path) -> dict[str, Any]:
    proof_board = _optional_report_json(reports_root / "btst_carryover_aligned_peer_proof_board_latest.json")
    if not proof_board:
        return {}
    selected_refresh_summary = _build_selected_outcome_refresh_summary(reports_root)
    entries = [dict(entry or {}) for entry in list(proof_board.get("entries") or [])]
    focus_entry = _find_focus_entry(entries, proof_board.get("focus_ticker"))
    return {
        "selected_ticker": selected_refresh_summary.get("focus_ticker") or proof_board.get("selected_ticker"),
        "selected_trade_date": selected_refresh_summary.get("trade_date") or proof_board.get("selected_trade_date"),
        "selected_cycle_status": selected_refresh_summary.get("focus_cycle_status") or proof_board.get("selected_cycle_status"),
        "selected_contract_verdict": selected_refresh_summary.get("focus_overall_contract_verdict") or proof_board.get("selected_contract_verdict"),
        "peer_count": proof_board.get("peer_count"),
        "proof_verdict_counts": dict(proof_board.get("proof_verdict_counts") or {}),
        "promotion_review_verdict_counts": dict(proof_board.get("promotion_review_verdict_counts") or {}),
        "ready_for_promotion_review_tickers": list(proof_board.get("ready_for_promotion_review_tickers") or []),
        "risk_review_tickers": list(proof_board.get("risk_review_tickers") or []),
        "pending_t_plus_2_tickers": list(proof_board.get("pending_t_plus_2_tickers") or []),
        "focus_ticker": proof_board.get("focus_ticker") or focus_entry.get("ticker"),
        "focus_proof_verdict": proof_board.get("focus_proof_verdict") or focus_entry.get("proof_verdict"),
        "focus_promotion_review_verdict": proof_board.get("focus_promotion_review_verdict") or focus_entry.get("promotion_review_verdict"),
        "focus_latest_trade_date": focus_entry.get("latest_trade_date"),
        "focus_latest_scope": focus_entry.get("latest_scope"),
        "focus_recommendation": focus_entry.get("recommendation"),
        "recommendation": proof_board.get("recommendation"),
    }


def _build_carryover_peer_promotion_gate_summary(reports_root: Path) -> dict[str, Any]:
    promotion_gate = _optional_report_json(reports_root / "btst_carryover_peer_promotion_gate_latest.json")
    if not promotion_gate:
        return {}
    selected_refresh_summary = _build_selected_outcome_refresh_summary(reports_root)
    entries = [dict(entry or {}) for entry in list(promotion_gate.get("entries") or [])]
    focus_entry = _find_focus_entry(entries, promotion_gate.get("focus_ticker"))
    return {
        "selected_ticker": selected_refresh_summary.get("focus_ticker") or promotion_gate.get("selected_ticker"),
        "selected_trade_date": selected_refresh_summary.get("trade_date") or promotion_gate.get("selected_trade_date"),
        "selected_contract_verdict": selected_refresh_summary.get("focus_overall_contract_verdict") or promotion_gate.get("selected_contract_verdict"),
        "peer_count": promotion_gate.get("peer_count"),
        "gate_verdict_counts": dict(promotion_gate.get("gate_verdict_counts") or {}),
        "ready_tickers": list(promotion_gate.get("ready_tickers") or []),
        "blocked_open_tickers": list(promotion_gate.get("blocked_open_tickers") or []),
        "risk_review_tickers": list(promotion_gate.get("risk_review_tickers") or []),
        "pending_t_plus_2_tickers": list(promotion_gate.get("pending_t_plus_2_tickers") or []),
        "focus_ticker": promotion_gate.get("focus_ticker") or focus_entry.get("ticker"),
        "focus_gate_verdict": promotion_gate.get("focus_gate_verdict") or focus_entry.get("gate_verdict"),
        "focus_recommendation": focus_entry.get("recommendation"),
        "recommendation": promotion_gate.get("recommendation"),
    }


def _build_default_merge_historical_counterfactual_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_default_merge_historical_counterfactual_latest.json")


def _build_continuation_merge_candidate_ranking_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_continuation_merge_candidate_ranking_latest.json")


def _build_default_merge_strict_counterfactual_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_default_merge_strict_counterfactual_latest.json")


def _build_merge_replay_validation_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_merge_replay_validation_latest.json")


def _build_prepared_breakout_relief_validation_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_prepared_breakout_relief_validation_latest.json")


def _build_prepared_breakout_cohort_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_prepared_breakout_cohort_latest.json")


def _build_prepared_breakout_residual_surface_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_prepared_breakout_residual_surface_latest.json")


def _build_candidate_pool_corridor_persistence_dossier_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_candidate_pool_corridor_persistence_dossier_latest.json")


def _build_candidate_pool_corridor_window_command_board_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_candidate_pool_corridor_window_command_board_latest.json")


def _build_candidate_pool_corridor_window_diagnostics_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_candidate_pool_corridor_window_diagnostics_latest.json")


def _build_candidate_pool_corridor_narrow_probe_summary(reports_root: Path) -> dict[str, Any]:
    return _optional_report_json(reports_root / "btst_candidate_pool_corridor_narrow_probe_latest.json")


def _collect_governance_synthesis_evidence_dirs(reports_root: Path, latest_btst_run: dict[str, Any] | None = None) -> list[str]:
    evidence_dirs: list[str] = []
    if latest_btst_run:
        latest_report_dir = str(latest_btst_run.get("report_dir") or "").strip()
        if latest_report_dir:
            evidence_dirs.append(latest_report_dir)
    upstream_handoff = _optional_report_json(reports_root / "btst_candidate_pool_upstream_handoff_board_latest.json")
    for row in list(upstream_handoff.get("board_rows") or []):
        report_dir = str(dict(row or {}).get("latest_followup_report_dir") or "").strip()
        if report_dir:
            evidence_dirs.append(report_dir)
    deduped_dirs: list[str] = []
    seen: set[str] = set()
    for report_dir in evidence_dirs:
        if report_dir in seen:
            continue
        seen.add(report_dir)
        deduped_dirs.append(report_dir)
    return deduped_dirs
CANDIDATE_ENTRY_FRONTIER_JSON = "btst_candidate_entry_frontier_20260330.json"
CANDIDATE_ENTRY_STRUCTURAL_VALIDATION_JSON = "selection_target_structural_variants_candidate_entry_current_window_20260330.json"
CANDIDATE_ENTRY_SCORE_FRONTIER_JSON = "btst_score_construction_frontier_20260330.json"
CANDIDATE_ENTRY_WINDOW_SCAN_JSON = "btst_candidate_entry_window_scan_20260330.json"
CANDIDATE_ENTRY_WINDOW_SCAN_MD = "btst_candidate_entry_window_scan_20260330.md"
CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_JSON = "p9_candidate_entry_rollout_governance_20260330.json"
CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_MD = "p9_candidate_entry_rollout_governance_20260330.md"
ACTION_BOARD_JSON = "p3_top3_post_execution_action_board_20260401.json"
PRIMARY_ROLL_FORWARD_JSON = "p4_primary_roll_forward_validation_001309_20260330.json"
PRIMARY_ROLL_FORWARD_MD = "p4_primary_roll_forward_validation_001309_20260330.md"
SHADOW_EXPANSION_JSON = "p4_shadow_entry_expansion_board_300383_20260330.json"
SHADOW_LANE_PRIORITY_JSON = "p4_shadow_lane_priority_board_20260401.json"
ROLLOUT_GOVERNANCE_JSON = "p5_btst_rollout_governance_board_20260401.json"
ROLLOUT_GOVERNANCE_MD = "p5_btst_rollout_governance_board_20260401.md"
PRIMARY_WINDOW_GAP_JSON = "p6_primary_window_gap_001309_20260330.json"
PRIMARY_WINDOW_GAP_MD = "p6_primary_window_gap_001309_20260330.md"
RECURRING_SHADOW_RUNBOOK_JSON = "p6_recurring_shadow_runbook_20260401.json"
RECURRING_SHADOW_RUNBOOK_MD = "p6_recurring_shadow_runbook_20260401.md"
RECURRING_CLOSE_BUNDLE_JSON = "btst_recurring_shadow_close_bundle_300113_20260401.json"
RECURRING_CLOSE_BUNDLE_MD = "btst_recurring_shadow_close_bundle_300113_20260401.md"
PRIMARY_WINDOW_VALIDATION_RUNBOOK_JSON = "p7_primary_window_validation_runbook_001309_20260330.json"
PRIMARY_WINDOW_VALIDATION_RUNBOOK_MD = "p7_primary_window_validation_runbook_001309_20260330.md"
SHADOW_PEER_SCAN_JSON = "p7_shadow_peer_scan_300383_20260401.json"
STRUCTURAL_SHADOW_RUNBOOK_JSON = "p8_structural_shadow_runbook_300724_20260330.json"
BTST_PENALTY_FRONTIER_JSON = "btst_penalty_frontier_current_window_20260331.json"
BTST_PENALTY_FRONTIER_MD = "btst_penalty_frontier_current_window_20260331.md"
CATALYST_THEME_FRONTIER_LATEST_JSON = "catalyst_theme_frontier_latest.json"
CATALYST_THEME_FRONTIER_LATEST_MD = "catalyst_theme_frontier_latest.md"
BTST_GOVERNANCE_SYNTHESIS_JSON = "btst_governance_synthesis_latest.json"
BTST_GOVERNANCE_SYNTHESIS_MD = "btst_governance_synthesis_latest.md"
BTST_GOVERNANCE_VALIDATION_JSON = "btst_governance_validation_latest.json"
BTST_GOVERNANCE_VALIDATION_MD = "btst_governance_validation_latest.md"
BTST_REPLAY_COHORT_JSON = "btst_replay_cohort_latest.json"
BTST_REPLAY_COHORT_MD = "btst_replay_cohort_latest.md"
BTST_INDEPENDENT_WINDOW_MONITOR_JSON = "btst_independent_window_monitor_latest.json"
BTST_INDEPENDENT_WINDOW_MONITOR_MD = "btst_independent_window_monitor_latest.md"
BTST_TPLUS1_TPLUS2_OBJECTIVE_MONITOR_JSON = "btst_tplus1_tplus2_objective_monitor_latest.json"
BTST_TPLUS1_TPLUS2_OBJECTIVE_MONITOR_MD = "btst_tplus1_tplus2_objective_monitor_latest.md"
BTST_TRADEABLE_OPPORTUNITY_POOL_JSON = "btst_tradeable_opportunity_pool_march.json"
BTST_TRADEABLE_OPPORTUNITY_POOL_MD = "btst_tradeable_opportunity_pool_march.md"
BTST_TRADEABLE_OPPORTUNITY_POOL_CSV = "btst_tradeable_opportunity_pool_march.csv"
BTST_TRADEABLE_OPPORTUNITY_WATERFALL_JSON = "btst_tradeable_opportunity_reason_waterfall_march.json"
BTST_TRADEABLE_OPPORTUNITY_WATERFALL_MD = "btst_tradeable_opportunity_reason_waterfall_march.md"
BTST_NO_CANDIDATE_ENTRY_ACTION_BOARD_JSON = "btst_no_candidate_entry_action_board_latest.json"
BTST_NO_CANDIDATE_ENTRY_ACTION_BOARD_MD = "btst_no_candidate_entry_action_board_latest.md"
BTST_NO_CANDIDATE_ENTRY_REPLAY_BUNDLE_JSON = "btst_no_candidate_entry_replay_bundle_latest.json"
BTST_NO_CANDIDATE_ENTRY_REPLAY_BUNDLE_MD = "btst_no_candidate_entry_replay_bundle_latest.md"
BTST_NO_CANDIDATE_ENTRY_FAILURE_DOSSIER_JSON = "btst_no_candidate_entry_failure_dossier_latest.json"
BTST_NO_CANDIDATE_ENTRY_FAILURE_DOSSIER_MD = "btst_no_candidate_entry_failure_dossier_latest.md"
BTST_WATCHLIST_RECALL_DOSSIER_JSON = "btst_watchlist_recall_dossier_latest.json"
BTST_WATCHLIST_RECALL_DOSSIER_MD = "btst_watchlist_recall_dossier_latest.md"
BTST_CANDIDATE_POOL_RECALL_DOSSIER_JSON = "btst_candidate_pool_recall_dossier_latest.json"
BTST_CANDIDATE_POOL_RECALL_DOSSIER_MD = "btst_candidate_pool_recall_dossier_latest.md"
BTST_CANDIDATE_POOL_BRANCH_PRIORITY_BOARD_JSON = "btst_candidate_pool_branch_priority_board_latest.json"
BTST_CANDIDATE_POOL_BRANCH_PRIORITY_BOARD_MD = "btst_candidate_pool_branch_priority_board_latest.md"
BTST_CANDIDATE_POOL_LANE_OBJECTIVE_SUPPORT_JSON = "btst_candidate_pool_lane_objective_support_latest.json"
BTST_CANDIDATE_POOL_LANE_OBJECTIVE_SUPPORT_MD = "btst_candidate_pool_lane_objective_support_latest.md"
BTST_CANDIDATE_POOL_REBUCKET_SHADOW_PACK_JSON = "btst_candidate_pool_rebucket_shadow_pack_latest.json"
BTST_CANDIDATE_POOL_REBUCKET_SHADOW_PACK_MD = "btst_candidate_pool_rebucket_shadow_pack_latest.md"
BTST_CANDIDATE_POOL_REBUCKET_OBJECTIVE_VALIDATION_JSON = "btst_candidate_pool_rebucket_objective_validation_latest.json"
BTST_CANDIDATE_POOL_REBUCKET_OBJECTIVE_VALIDATION_MD = "btst_candidate_pool_rebucket_objective_validation_latest.md"
BTST_CANDIDATE_POOL_REBUCKET_COMPARISON_BUNDLE_JSON = "btst_candidate_pool_rebucket_comparison_bundle_latest.json"
BTST_CANDIDATE_POOL_REBUCKET_COMPARISON_BUNDLE_MD = "btst_candidate_pool_rebucket_comparison_bundle_latest.md"
BTST_CANDIDATE_POOL_CORRIDOR_VALIDATION_PACK_JSON = "btst_candidate_pool_corridor_validation_pack_latest.json"
BTST_CANDIDATE_POOL_CORRIDOR_VALIDATION_PACK_MD = "btst_candidate_pool_corridor_validation_pack_latest.md"
BTST_CANDIDATE_POOL_CORRIDOR_SHADOW_PACK_JSON = "btst_candidate_pool_corridor_shadow_pack_latest.json"
BTST_CANDIDATE_POOL_CORRIDOR_SHADOW_PACK_MD = "btst_candidate_pool_corridor_shadow_pack_latest.md"
BTST_CANDIDATE_POOL_LANE_PAIR_BOARD_JSON = "btst_candidate_pool_lane_pair_board_latest.json"
BTST_CANDIDATE_POOL_LANE_PAIR_BOARD_MD = "btst_candidate_pool_lane_pair_board_latest.md"
BTST_CANDIDATE_POOL_UPSTREAM_HANDOFF_BOARD_JSON = "btst_candidate_pool_upstream_handoff_board_latest.json"
BTST_CANDIDATE_POOL_UPSTREAM_HANDOFF_BOARD_MD = "btst_candidate_pool_upstream_handoff_board_latest.md"
BTST_CANDIDATE_POOL_CORRIDOR_UPLIFT_RUNBOOK_JSON = "btst_candidate_pool_corridor_uplift_runbook_latest.json"
BTST_CANDIDATE_POOL_CORRIDOR_UPLIFT_RUNBOOK_MD = "btst_candidate_pool_corridor_uplift_runbook_latest.md"
MULTI_WINDOW_ROLE_CANDIDATES_LATEST_JSON = "multi_window_short_trade_role_candidates_latest.json"
MULTI_WINDOW_ROLE_CANDIDATES_LATEST_MD = "multi_window_short_trade_role_candidates_latest.md"
RECURRING_FRONTIER_TRANSITION_LATEST_JSON = "recurring_frontier_transition_candidates_latest.json"
RECURRING_FRONTIER_TRANSITION_LATEST_MD = "recurring_frontier_transition_candidates_latest.md"
SHORT_TRADE_BOUNDARY_SCORE_FAILURES_LATEST_JSON = "short_trade_boundary_score_failures_latest.json"
SHORT_TRADE_BOUNDARY_SCORE_FAILURES_LATEST_MD = "short_trade_boundary_score_failures_latest.md"
SHORT_TRADE_BOUNDARY_SCORE_FAILURES_FRONTIER_LATEST_JSON = "short_trade_boundary_score_failures_frontier_latest.json"
SHORT_TRADE_BOUNDARY_SCORE_FAILURES_FRONTIER_LATEST_MD = "short_trade_boundary_score_failures_frontier_latest.md"
SHORT_TRADE_BOUNDARY_RECURRING_FRONTIER_LATEST_JSON = "short_trade_boundary_recurring_frontier_cases_latest.json"
SHORT_TRADE_BOUNDARY_RECURRING_FRONTIER_LATEST_MD = "short_trade_boundary_recurring_frontier_cases_latest.md"
RECURRING_PAIR_COMPARISON_JSON = "recurring_frontier_release_pair_comparison_600821_vs_300113_catalyst_floor_zero_refresh_20260401.json"
TRADEABLE_OPPORTUNITY_POOL_START_DATE = "2026-03-01"
TRADEABLE_OPPORTUNITY_POOL_END_DATE = "2026-03-31"
CANDIDATE_ENTRY_FOCUS_TICKERS: tuple[str, ...] = ("300502",)
CANDIDATE_ENTRY_PRESERVE_TICKERS: tuple[str, ...] = ("300394",)
STATIC_ENTRY_GLOB_OVERRIDES: dict[str, str] = {
    "p2_top3_execution_summary": "p2_top3_experiment_execution_summary_*.json",
    "p3_post_execution_action_board": "p3_top3_post_execution_action_board_*.json",
    "p5_rollout_governance_board": "p5_btst_rollout_governance_board_*.json",
    "p6_primary_window_gap": "p6_primary_window_gap_001309_*.json",
    "p6_recurring_shadow_runbook": "p6_recurring_shadow_runbook_*.json",
    "btst_recurring_shadow_close_bundle": "btst_recurring_shadow_close_bundle_*.json",
    "p7_primary_window_validation_runbook": "p7_primary_window_validation_runbook_001309_*.json",
    "p8_structural_shadow_runbook": "p8_structural_shadow_runbook_300724_*.json",
}

STATIC_ENTRY_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "btst_open_ready_delta_latest",
        "path": "data/reports/btst_open_ready_delta_latest.md",
        "report_type": "btst_open_ready_delta",
        "topic": "btst_followup",
        "usage": "tomorrow_open",
        "priority": 1,
        "is_latest": True,
        "question": "相对上一轮，今晚最该知道的 delta 是什么",
        "view_order": 0,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_nightly_control_tower_latest",
        "path": "data/reports/btst_nightly_control_tower_latest.md",
        "report_type": "btst_nightly_control_tower",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "今晚 control tower 的一页总览是什么",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_latest_close_validation_latest",
        "path": "data/reports/btst_latest_close_validation_latest.md",
        "report_type": "btst_latest_close_validation",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "今天收盘到底验证了什么，明天该如何理解当前 BTST 结论",
        "view_order": 2,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_selected_outcome_refresh_board_latest",
        "path": "data/reports/btst_selected_outcome_refresh_board_latest.md",
        "report_type": "btst_selected_outcome_refresh_board",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "当前 formal selected 的实时兑现状态与历史 proof 是否一致",
        "view_order": 3,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_default_merge_review_latest",
        "path": "data/reports/btst_default_merge_review_latest.md",
        "report_type": "btst_default_merge_review",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "当前哪个 continuation 焦点票已经 ready for default BTST merge review",
        "view_order": 3,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_default_merge_historical_counterfactual_latest",
        "path": "data/reports/btst_default_merge_historical_counterfactual_latest.md",
        "report_type": "btst_default_merge_historical_counterfactual",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "如果把 merge-review-ready continuation edge 并入 default BTST，历史胜率和收益会怎样变化",
        "view_order": 4,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_continuation_merge_candidate_ranking_latest",
        "path": "data/reports/btst_continuation_merge_candidate_ranking_latest.md",
        "report_type": "btst_continuation_merge_candidate_ranking",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "当前 continuation 候选里，哪只票最值得沿 default BTST merge 路径继续推进",
        "view_order": 5,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_default_merge_strict_counterfactual_latest",
        "path": "data/reports/btst_default_merge_strict_counterfactual_latest.md",
        "report_type": "btst_default_merge_strict_counterfactual",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "在去重重叠样本后，merge-review-ready continuation edge 并入 default BTST 是否仍有明显 uplift",
        "view_order": 6,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_merge_replay_validation_latest",
        "path": "data/reports/btst_merge_replay_validation_latest.md",
        "report_type": "btst_merge_replay_validation",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "当前 merge-approved continuation edge 在历史 replay 输入上，能否把焦点票从 baseline 提升到 near_miss 或 selected",
        "view_order": 7,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_prepared_breakout_relief_validation_latest",
        "path": "data/reports/btst_prepared_breakout_relief_validation_latest.md",
        "report_type": "btst_prepared_breakout_relief_validation",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "prepared-breakout relief 在多窗口上是否稳定支撑当前焦点票",
        "view_order": 8,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_prepared_breakout_cohort_latest",
        "path": "data/reports/btst_prepared_breakout_cohort_latest.md",
        "report_type": "btst_prepared_breakout_cohort",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "当前 profile 下哪些 prepared-breakout ticker 与 300505 最像、下一只该验证谁",
        "view_order": 9,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_prepared_breakout_residual_surface_latest",
        "path": "data/reports/btst_prepared_breakout_residual_surface_latest.md",
        "report_type": "btst_prepared_breakout_residual_surface",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "为什么 600988 这类 prepared-breakout residual surface 不能直接继承 300505 uplift",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "reports_hub_readme",
        "path": "data/reports/README.md",
        "report_type": "report_hub_readme",
        "topic": "reports_navigation",
        "usage": "navigation",
        "priority": 1,
        "is_latest": True,
        "question": "reports 根入口是什么",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "stable_entry_page",
    },
    {
        "id": "optimize0330_readme",
        "path": "docs/zh-cn/factors/BTST/optimize0330/README.md",
        "report_type": "source_of_truth_doc",
        "topic": "btst_optimize0330",
        "usage": "truth_source",
        "priority": 1,
        "is_latest": True,
        "question": "0330 BTST 当前主线逻辑是什么",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "source_of_truth",
    },
    {
        "id": "optimize0330_checklist",
        "path": "docs/zh-cn/factors/BTST/optimize0330/01-0330-research-execution-checklist.md",
        "report_type": "execution_checklist",
        "topic": "btst_optimize0330",
        "usage": "truth_source",
        "priority": 2,
        "is_latest": True,
        "question": "0330 BTST 当前执行状态和下一步动作是什么",
        "view_order": 2,
        "time_scope": {"label": "rolling"},
        "source_kind": "source_of_truth",
    },
    {
        "id": "arch_optimize_implementation",
        "path": "docs/zh-cn/product/arch/arch_optimize_implementation.md",
        "report_type": "implementation_truth_doc",
        "topic": "upstream_architecture",
        "usage": "truth_source",
        "priority": 3,
        "is_latest": True,
        "question": "上游真实落地事实与系统边界是什么",
        "view_order": 3,
        "time_scope": {"label": "rolling"},
        "source_kind": "source_of_truth",
    },
    {
        "id": "btst_recurring_shadow_split_summary_20260401",
        "path": "docs/zh-cn/product/arch/btst_recurring_shadow_split_summary_20260401.md",
        "report_type": "btst_recurring_shadow_split_summary",
        "topic": "btst_governance",
        "usage": "truth_source",
        "priority": 2,
        "is_latest": True,
        "question": "当前 recurring shadow 的 300113/600821 split 应如何执行",
        "view_order": 4,
        "time_scope": {"label": "rolling"},
        "source_kind": "source_of_truth",
    },
    {
        "id": "btst_governance_synthesis_latest",
        "path": "data/reports/btst_governance_synthesis_latest.md",
        "report_type": "btst_governance_synthesis",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 1,
        "is_latest": True,
        "question": "当前 BTST 治理总览板是什么",
        "view_order": 1,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_governance_validation_latest",
        "path": "data/reports/btst_governance_validation_latest.md",
        "report_type": "btst_governance_validation",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 2,
        "is_latest": True,
        "question": "当前 BTST 治理结论之间是否一致",
        "view_order": 2,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "p2_top3_execution_summary",
        "path": "data/reports/p2_top3_experiment_execution_summary_20260330.json",
        "report_type": "btst_execution_summary",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 1,
        "is_latest": True,
        "question": "Top 3 case-based 执行结果是什么",
        "view_order": 1,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p3_post_execution_action_board",
        "path": "data/reports/p3_top3_post_execution_action_board_20260401.json",
        "report_type": "btst_action_board",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 2,
        "is_latest": True,
        "question": "当前 lane 分流后的动作板是什么",
        "view_order": 2,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p5_rollout_governance_board",
        "path": "data/reports/p5_btst_rollout_governance_board_20260401.json",
        "report_type": "btst_rollout_governance_board",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 3,
        "is_latest": True,
        "question": "当前 default / shadow / freeze 治理结论是什么",
        "view_order": 3,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_micro_window_regression_review",
        "path": "data/reports/btst_micro_window_regression_march_refresh.md",
        "report_type": "btst_micro_window_regression_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 4,
        "is_latest": True,
        "question": "0323-0326 闭环 baseline 与 catalyst_floor_zero 的微窗口回归结果是什么",
        "view_order": 4,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_profile_frontier_review",
        "path": "data/reports/btst_profile_frontier_20260330.md",
        "report_type": "btst_profile_frontier_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 5,
        "is_latest": True,
        "question": "默认 profile 与 staged_breakout/aggressive/conservative 的闭环 frontier 结果是什么",
        "view_order": 5,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_score_construction_frontier_review",
        "path": "data/reports/btst_score_construction_frontier_20260330.md",
        "report_type": "btst_score_construction_frontier_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 6,
        "is_latest": True,
        "question": "只调正向 score weight 的闭环 frontier 结果是什么",
        "view_order": 6,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_penalty_frontier_review",
        "path": "data/reports/btst_penalty_frontier_current_window_20260331.md",
        "report_type": "btst_penalty_frontier_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 7,
        "is_latest": True,
        "question": "broad stale/extension penalty relief 为什么不再是 rollout 路线",
        "view_order": 7,
        "time_scope": {"label": "current_window_20260331"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_candidate_entry_frontier_review",
        "path": "data/reports/btst_candidate_entry_frontier_20260330.md",
        "report_type": "btst_candidate_entry_frontier_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 8,
        "is_latest": True,
        "question": "哪条 candidate entry selective rule 能过滤 300502 并保住 300394",
        "view_order": 8,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_candidate_entry_window_scan_review",
        "path": "data/reports/btst_candidate_entry_window_scan_20260330.md",
        "report_type": "btst_candidate_entry_window_scan_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 9,
        "is_latest": True,
        "question": "弱结构 candidate entry 规则是否已经跨多个独立窗口命中且没有误伤 preserve 样本",
        "view_order": 9,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p9_candidate_entry_rollout_governance",
        "path": "data/reports/p9_candidate_entry_rollout_governance_20260330.md",
        "report_type": "btst_candidate_entry_rollout_governance",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "为什么弱结构 candidate entry 规则当前只能 shadow-only 而不能升级默认",
        "view_order": 10,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_independent_window_monitor_latest",
        "path": "data/reports/btst_independent_window_monitor_latest.md",
        "report_type": "btst_independent_window_monitor",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "001309、300113、600821 还差几个独立窗口，哪条 lane 已经具备重审条件",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_tplus1_tplus2_objective_monitor_latest",
        "path": "data/reports/btst_tplus1_tplus2_objective_monitor_latest.md",
        "report_type": "btst_tplus1_tplus2_objective_monitor",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "当前 BTST 距离“明天买、后天卖，80% 胜率且 5% 收益”目标还有多远",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_lane_objective_support_latest",
        "path": "data/reports/btst_candidate_pool_lane_objective_support_latest.md",
        "report_type": "btst_candidate_pool_lane_objective_support",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "candidate-pool recall 各 lane 的后验收益支持到底如何",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_rebucket_objective_validation_latest",
        "path": "data/reports/btst_candidate_pool_rebucket_objective_validation_latest.md",
        "report_type": "btst_candidate_pool_rebucket_objective_validation",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "rebucket shadow lane 是否已有足够收益支持继续优先推进",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_rebucket_comparison_bundle_latest",
        "path": "data/reports/btst_candidate_pool_rebucket_comparison_bundle_latest.md",
        "report_type": "btst_candidate_pool_rebucket_comparison_bundle",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "rebucket lane 现在该如何和 corridor objective leader 做并行对照",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_corridor_validation_pack_latest",
        "path": "data/reports/btst_candidate_pool_corridor_validation_pack_latest.md",
        "report_type": "btst_candidate_pool_corridor_validation_pack",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "corridor objective leader 应先验证哪只票、并行盯哪只票",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_corridor_shadow_pack_latest",
        "path": "data/reports/btst_candidate_pool_corridor_shadow_pack_latest.md",
        "report_type": "btst_candidate_pool_corridor_shadow_pack",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "corridor lane 当前 primary shadow replay 该先跑谁、并行盯谁",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_lane_pair_board_latest",
        "path": "data/reports/btst_candidate_pool_lane_pair_board_latest.md",
        "report_type": "btst_candidate_pool_lane_pair_board",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "corridor 与 rebucket 当前谁应占据第一 replay 槽位",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_upstream_handoff_board_latest",
        "path": "data/reports/btst_candidate_pool_upstream_handoff_board_latest.md",
        "report_type": "btst_candidate_pool_upstream_handoff_board",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "300720/003036/301292 在 upstream handoff 链路里最先断在哪一层",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_corridor_uplift_runbook_latest",
        "path": "data/reports/btst_candidate_pool_corridor_uplift_runbook_latest.md",
        "report_type": "btst_candidate_pool_corridor_uplift_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "corridor upstream liquidity uplift probe 当前应如何执行",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_corridor_persistence_dossier_latest",
        "path": "data/reports/btst_candidate_pool_corridor_persistence_dossier_latest.md",
        "report_type": "btst_candidate_pool_corridor_persistence_dossier",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "300720 为什么还不能 merge-ready，当前 corridor primary 还差什么",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_corridor_window_command_board_latest",
        "path": "data/reports/btst_candidate_pool_corridor_window_command_board_latest.md",
        "report_type": "btst_candidate_pool_corridor_window_command_board",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "300720 下一步最该追哪几个独立窗口，如何补第二个 selected 样本",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_corridor_window_diagnostics_latest",
        "path": "data/reports/btst_candidate_pool_corridor_window_diagnostics_latest.md",
        "report_type": "btst_candidate_pool_corridor_window_diagnostics",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "300720 的 near-miss 窄缺口与 visibility gap 哪个更该先追",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_corridor_narrow_probe_latest",
        "path": "data/reports/btst_candidate_pool_corridor_narrow_probe_latest.md",
        "report_type": "btst_candidate_pool_corridor_narrow_probe",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "2026-04-06 的 300720 到底差的是全局 edge，还是 lane-specific select threshold override",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_tradeable_opportunity_pool_march",
        "path": "data/reports/btst_tradeable_opportunity_pool_march.md",
        "report_type": "btst_tradeable_opportunity_pool",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 11,
        "is_latest": True,
        "question": "3 月可交易机会池到底有多大，系统召回率卡在什么位置",
        "view_order": 11,
        "time_scope": {"label": "march_2026"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_no_candidate_entry_action_board_latest",
        "path": "data/reports/btst_no_candidate_entry_action_board_latest.md",
        "report_type": "btst_no_candidate_entry_action_board",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 12,
        "is_latest": True,
        "question": "no_candidate_entry 这批漏召回样本该先打哪几个票、哪几个窗口",
        "view_order": 12,
        "time_scope": {"label": "march_2026"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_no_candidate_entry_replay_bundle_latest",
        "path": "data/reports/btst_no_candidate_entry_replay_bundle_latest.md",
        "report_type": "btst_no_candidate_entry_replay_bundle",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 12,
        "is_latest": True,
        "question": "当前 no_candidate_entry backlog 里哪些票已经形成 preserve-safe recall probe",
        "view_order": 13,
        "time_scope": {"label": "march_2026"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_no_candidate_entry_failure_dossier_latest",
        "path": "data/reports/btst_no_candidate_entry_failure_dossier_latest.md",
        "report_type": "btst_no_candidate_entry_failure_dossier",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 12,
        "is_latest": True,
        "question": "当前 no_candidate_entry backlog 主要是 upstream 缺失，还是 candidate-entry 语义未命中",
        "view_order": 14,
        "time_scope": {"label": "march_2026"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_watchlist_recall_dossier_latest",
        "path": "data/reports/btst_watchlist_recall_dossier_latest.md",
        "report_type": "btst_watchlist_recall_dossier",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 12,
        "is_latest": True,
        "question": "absent_from_watchlist 这批票具体断在 candidate_pool、layer_b，还是 watchlist gate",
        "view_order": 15,
        "time_scope": {"label": "march_2026"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_candidate_pool_recall_dossier_latest",
        "path": "data/reports/btst_candidate_pool_recall_dossier_latest.md",
        "report_type": "btst_candidate_pool_recall_dossier",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 12,
        "is_latest": True,
        "question": "absent_from_candidate_pool 这批票具体卡在 Layer A 哪个过滤或 top300 边界",
        "view_order": 16,
        "time_scope": {"label": "march_2026"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_tradeable_opportunity_reason_waterfall_march",
        "path": "data/reports/btst_tradeable_opportunity_reason_waterfall_march.md",
        "report_type": "btst_tradeable_opportunity_reason_waterfall",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 13,
        "is_latest": True,
        "question": "3 月可交易机会池最早死在什么地方，错杀瀑布怎么排",
        "view_order": 13,
        "time_scope": {"label": "march_2026"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_multi_window_role_candidates_latest",
        "path": "data/reports/multi_window_short_trade_role_candidates_latest.md",
        "report_type": "btst_multi_window_role_candidates",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 11,
        "is_latest": True,
        "question": "当前跨窗口 short-trade 角色候选名单是什么",
        "view_order": 11,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_recurring_frontier_transition_latest",
        "path": "data/reports/recurring_frontier_transition_candidates_latest.md",
        "report_type": "btst_recurring_frontier_transition",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 12,
        "is_latest": True,
        "question": "recurring frontier 候选里哪些已接近跨窗口稳定",
        "view_order": 12,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_score_fail_frontier_latest",
        "path": "data/reports/short_trade_boundary_score_failures_frontier_latest.md",
        "report_type": "btst_score_fail_frontier",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 13,
        "is_latest": True,
        "question": "当前 short-trade score-fail 样本里哪些最接近 near-miss rescue",
        "view_order": 13,
        "time_scope": {"label": "latest_btst_followup"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_score_fail_recurring_frontier_latest",
        "path": "data/reports/short_trade_boundary_recurring_frontier_cases_latest.md",
        "report_type": "btst_score_fail_recurring_frontier",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 14,
        "is_latest": True,
        "question": "当前 score-fail recurring 队列里最值得跟踪的 ticker 是谁",
        "view_order": 14,
        "time_scope": {"label": "latest_btst_followup"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "p6_primary_window_gap",
        "path": "data/reports/p6_primary_window_gap_001309_20260330.json",
        "report_type": "btst_window_gap_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 15,
        "is_latest": True,
        "question": "001309 还缺什么窗口证据",
        "view_order": 15,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p6_recurring_shadow_runbook",
        "path": "data/reports/p6_recurring_shadow_runbook_20260401.json",
        "report_type": "btst_recurring_shadow_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 16,
        "is_latest": True,
        "question": "recurring shadow lane 该如何阅读和执行",
        "view_order": 16,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_recurring_shadow_close_bundle",
        "path": "data/reports/btst_recurring_shadow_close_bundle_300113_20260401.json",
        "report_type": "btst_recurring_shadow_close_bundle",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 17,
        "is_latest": True,
        "question": "300113 close-candidate shadow bundle 该如何直接复用",
        "view_order": 17,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p7_primary_window_validation_runbook",
        "path": "data/reports/p7_primary_window_validation_runbook_001309_20260330.json",
        "report_type": "btst_primary_validation_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 17,
        "is_latest": True,
        "question": "001309 后续复跑命令与判断条件是什么",
        "view_order": 17,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p8_structural_shadow_runbook",
        "path": "data/reports/p8_structural_shadow_runbook_300724_20260330.json",
        "report_type": "btst_structural_shadow_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 18,
        "is_latest": True,
        "question": "300724 为什么保持 structural shadow hold",
        "view_order": 18,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_replay_cohort_latest",
        "path": "data/reports/btst_replay_cohort_latest.md",
        "report_type": "btst_replay_cohort",
        "topic": "replay_artifacts",
        "usage": "replay_history",
        "priority": 1,
        "is_latest": True,
        "question": "当前 BTST live/frozen replay 队列和 short-trade 样本汇总是什么",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "replay_artifacts_stock_selection_manual",
        "path": "docs/zh-cn/manual/replay-artifacts-stock-selection-manual.md",
        "report_type": "manual",
        "topic": "replay_artifacts",
        "usage": "replay_history",
        "priority": 1,
        "is_latest": True,
        "question": "Replay Artifacts 工作台如何查报告",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "manual",
    },
    {
        "id": "historical_edge_artifact_index",
        "path": "docs/zh-cn/analysis/historical-edge-artifact-index-20260318.md",
        "report_type": "artifact_index",
        "topic": "historical_edge",
        "usage": "replay_history",
        "priority": 2,
        "is_latest": True,
        "question": "历史 edge 专题从哪里进入",
        "view_order": 2,
        "time_scope": {"label": "historical_archive"},
        "source_kind": "artifact_index",
    },
)

READING_PATH_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "navigation",
        "title": "入口导航",
        "description": "先看稳定入口，不直接翻 data/reports 目录。",
        "entry_ids": ["reports_hub_readme", "optimize0330_readme", "optimize0330_checklist", "arch_optimize_implementation", "btst_recurring_shadow_split_summary_20260401"],
    },
    {
        "id": "btst_control_tower",
        "title": "BTST 控制塔",
        "description": "先看相对上一轮的 delta，再看当前 lane 状态，最后确认历史回放样本。",
        "entry_ids": [
            "btst_open_ready_delta_latest",
            "btst_latest_close_validation_latest",
            "btst_selected_outcome_refresh_board_latest",
            "btst_default_merge_review_latest",
            "btst_default_merge_historical_counterfactual_latest",
            "btst_continuation_merge_candidate_ranking_latest",
            "btst_default_merge_strict_counterfactual_latest",
            "btst_merge_replay_validation_latest",
            "btst_prepared_breakout_relief_validation_latest",
            "btst_prepared_breakout_cohort_latest",
            "btst_prepared_breakout_residual_surface_latest",
            "btst_nightly_control_tower_latest",
            "btst_governance_synthesis_latest",
            "btst_tplus1_tplus2_objective_monitor_latest",
            "btst_independent_window_monitor_latest",
            "btst_candidate_pool_lane_objective_support_latest",
            "btst_candidate_pool_rebucket_objective_validation_latest",
            "btst_candidate_pool_rebucket_comparison_bundle_latest",
            "btst_candidate_pool_corridor_validation_pack_latest",
            "btst_candidate_pool_corridor_shadow_pack_latest",
            "btst_candidate_pool_lane_pair_board_latest",
            "btst_candidate_pool_upstream_handoff_board_latest",
            "btst_candidate_pool_corridor_uplift_runbook_latest",
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
            "p5_rollout_governance_board",
            "btst_recurring_shadow_close_bundle",
            "p9_candidate_entry_rollout_governance",
        ],
    },
    {
        "id": "tomorrow_open",
        "title": "明天开盘",
        "description": "开盘前的最短阅读路径，优先解决明天到底交易什么。",
        "entry_ids": ["btst_open_ready_delta_latest", "btst_latest_close_validation_latest", "latest_btst_priority_board", "latest_btst_opening_watch_card", "latest_btst_execution_card_markdown", "latest_btst_brief_markdown"],
    },
    {
        "id": "nightly_review",
        "title": "晚间复盘",
        "description": "晚间确认本次运行发生了什么、明日结论为何如此。",
        "entry_ids": [
            "btst_open_ready_delta_latest",
            "btst_latest_close_validation_latest",
            "btst_selected_outcome_refresh_board_latest",
            "btst_default_merge_review_latest",
            "btst_default_merge_historical_counterfactual_latest",
            "btst_continuation_merge_candidate_ranking_latest",
            "btst_default_merge_strict_counterfactual_latest",
            "btst_merge_replay_validation_latest",
            "btst_prepared_breakout_relief_validation_latest",
            "btst_prepared_breakout_cohort_latest",
            "btst_prepared_breakout_residual_surface_latest",
            "btst_tplus1_tplus2_objective_monitor_latest",
            "btst_candidate_pool_lane_objective_support_latest",
            "btst_candidate_pool_rebucket_objective_validation_latest",
            "btst_candidate_pool_rebucket_comparison_bundle_latest",
            "btst_candidate_pool_corridor_validation_pack_latest",
            "btst_candidate_pool_corridor_shadow_pack_latest",
            "btst_candidate_pool_lane_pair_board_latest",
            "btst_candidate_pool_upstream_handoff_board_latest",
            "btst_candidate_pool_corridor_uplift_runbook_latest",
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
            "btst_nightly_control_tower_latest",
            "latest_btst_session_summary",
            "latest_btst_brief_json",
            "latest_btst_execution_card_json",
            "latest_btst_catalyst_theme_frontier_markdown",
            "btst_score_fail_frontier_latest",
            "latest_btst_selection_snapshot",
        ],
    },
    {
        "id": "btst_governance",
        "title": "BTST 治理主线",
        "description": "解释当前 lane 为什么被保留、冻结或只允许 shadow。",
        "entry_ids": [
            "btst_governance_synthesis_latest",
            "btst_governance_validation_latest",
            "p2_top3_execution_summary",
            "p3_post_execution_action_board",
            "p5_rollout_governance_board",
            "btst_micro_window_regression_review",
            "btst_profile_frontier_review",
            "btst_score_construction_frontier_review",
            "btst_penalty_frontier_review",
            "btst_candidate_entry_frontier_review",
            "btst_candidate_entry_window_scan_review",
            "p9_candidate_entry_rollout_governance",
            "btst_tplus1_tplus2_objective_monitor_latest",
            "btst_independent_window_monitor_latest",
            "btst_candidate_pool_lane_objective_support_latest",
            "btst_candidate_pool_rebucket_objective_validation_latest",
            "btst_candidate_pool_rebucket_comparison_bundle_latest",
            "btst_candidate_pool_corridor_validation_pack_latest",
            "btst_candidate_pool_corridor_shadow_pack_latest",
            "btst_candidate_pool_lane_pair_board_latest",
            "btst_candidate_pool_upstream_handoff_board_latest",
            "btst_candidate_pool_corridor_uplift_runbook_latest",
            "btst_tradeable_opportunity_pool_march",
            "btst_no_candidate_entry_action_board_latest",
            "btst_no_candidate_entry_replay_bundle_latest",
            "btst_no_candidate_entry_failure_dossier_latest",
            "btst_watchlist_recall_dossier_latest",
            "btst_candidate_pool_recall_dossier_latest",
            "btst_tradeable_opportunity_reason_waterfall_march",
            "btst_multi_window_role_candidates_latest",
            "btst_recurring_frontier_transition_latest",
            "btst_score_fail_frontier_latest",
            "btst_score_fail_recurring_frontier_latest",
            "p6_primary_window_gap",
            "p6_recurring_shadow_runbook",
            "btst_recurring_shadow_close_bundle",
            "p7_primary_window_validation_runbook",
            "p8_structural_shadow_runbook",
        ],
    },
    {
        "id": "truth_source",
        "title": "真相源文档",
        "description": "专题逻辑、执行状态和上游实现事实的固定 source of truth。",
        "entry_ids": ["optimize0330_readme", "optimize0330_checklist", "arch_optimize_implementation", "btst_recurring_shadow_split_summary_20260401"],
    },
    {
        "id": "replay_history",
        "title": "Replay 与历史专题",
        "description": "需要从工作台或历史专题入口回查时，固定从这里进入。",
        "entry_ids": ["btst_replay_cohort_latest", "replay_artifacts_stock_selection_manual", "historical_edge_artifact_index"],
    },
)


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: str | Path, content: str) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")


def _discover_report_dirs(reports_root: Path) -> list[Path]:
    resolved_reports_root = reports_root.expanduser().resolve()
    if not resolved_reports_root.exists():
        return []
    return _discover_btst_report_dirs(resolved_reports_root, report_name_prefix="paper_trading")


def _resolve_existing_artifact_path(
    reports_root: str | Path,
    preferred_name: str,
    *,
    glob_pattern: str | None = None,
) -> Path:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    preferred_path = resolved_reports_root / preferred_name
    if preferred_path.exists():
        return preferred_path
    if not glob_pattern:
        return preferred_path

    matches = sorted(
        [path for path in resolved_reports_root.glob(glob_pattern) if path.is_file()],
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    return matches[0] if matches else preferred_path


def _resolve_repo_root(reports_root: Path) -> Path:
    resolved_reports_root = reports_root.expanduser().resolve()
    if resolved_reports_root.name == "reports" and resolved_reports_root.parent.name == "data":
        return resolved_reports_root.parent.parent
    return resolved_reports_root.parent


def _repo_relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _build_entry(
    *,
    entry_id: str,
    absolute_path: Path,
    repo_root: Path,
    report_type: str,
    topic: str,
    usage: str,
    priority: int,
    is_latest: bool,
    question: str,
    view_order: int,
    time_scope: dict[str, Any],
    source_kind: str,
    report_dir: str | None = None,
) -> dict[str, Any] | None:
    resolved_path = absolute_path.expanduser().resolve()
    if not resolved_path.exists():
        return None
    return {
        "id": entry_id,
        "report_path": _repo_relative_path(resolved_path, repo_root),
        "absolute_path": resolved_path.as_posix(),
        "report_type": report_type,
        "topic": topic,
        "usage": usage,
        "priority": priority,
        "is_latest": is_latest,
        "question": question,
        "view_order": view_order,
        "time_scope": time_scope,
        "source_kind": source_kind,
        "report_dir": report_dir,
    }


def _extract_btst_candidate(report_dir: Path, repo_root: Path) -> dict[str, Any] | None:
    summary = _load_json(report_dir / "session_summary.json")
    followup = dict(summary.get("btst_followup") or {})
    artifacts = dict(summary.get("artifacts") or {})
    selection_target = str(summary.get("plan_generation", {}).get("selection_target") or summary.get("selection_target") or "")

    brief_json_path = followup.get("brief_json") or artifacts.get("btst_next_day_trade_brief_json")
    brief_markdown_path = followup.get("brief_markdown") or artifacts.get("btst_next_day_trade_brief_markdown")
    card_json_path = followup.get("execution_card_json") or artifacts.get("btst_premarket_execution_card_json")
    card_markdown_path = followup.get("execution_card_markdown") or artifacts.get("btst_premarket_execution_card_markdown")
    opening_card_markdown_path = followup.get("opening_watch_card_markdown") or artifacts.get("btst_opening_watch_card_markdown")
    priority_board_markdown_path = followup.get("priority_board_markdown") or artifacts.get("btst_next_day_priority_board_markdown")
    catalyst_theme_frontier_json_path = followup.get("catalyst_theme_frontier_json") or artifacts.get("btst_catalyst_theme_frontier_json")
    catalyst_theme_frontier_markdown_path = followup.get("catalyst_theme_frontier_markdown") or artifacts.get("btst_catalyst_theme_frontier_markdown")
    if not any([brief_json_path, brief_markdown_path, card_json_path, card_markdown_path]):
        return None

    trade_date = _normalize_trade_date(followup.get("trade_date") or summary.get("end_date"))
    next_trade_date = _normalize_trade_date(followup.get("next_trade_date"))
    selection_snapshot_path = report_dir / "selection_artifacts" / trade_date / "selection_snapshot.json" if trade_date else None
    opening_card_path = Path(opening_card_markdown_path).expanduser().resolve() if opening_card_markdown_path else None
    if opening_card_path is None and next_trade_date:
        opening_card_path = report_dir / f"btst_opening_watch_card_{next_trade_date.replace('-', '')}.md"

    trade_date_rank = trade_date or _normalize_trade_date(summary.get("end_date")) or ""
    selection_target_rank = 2 if selection_target == "short_trade_only" else 1

    return {
        "report_dir": report_dir.resolve(),
        "report_dir_name": report_dir.name,
        "report_dir_path": _repo_relative_path(report_dir, repo_root),
        "selection_target": selection_target or None,
        "trade_date": trade_date,
        "next_trade_date": next_trade_date,
        "brief_json_path": Path(brief_json_path).expanduser().resolve() if brief_json_path else None,
        "brief_markdown_path": Path(brief_markdown_path).expanduser().resolve() if brief_markdown_path else None,
        "card_json_path": Path(card_json_path).expanduser().resolve() if card_json_path else None,
        "card_markdown_path": Path(card_markdown_path).expanduser().resolve() if card_markdown_path else None,
        "session_summary_path": (report_dir / "session_summary.json").resolve(),
        "selection_snapshot_path": selection_snapshot_path.resolve() if selection_snapshot_path and selection_snapshot_path.exists() else None,
        "opening_card_path": opening_card_path.resolve() if opening_card_path and opening_card_path.exists() else None,
        "priority_board_markdown_path": Path(priority_board_markdown_path).expanduser().resolve() if priority_board_markdown_path else None,
        "catalyst_theme_frontier_json_path": Path(catalyst_theme_frontier_json_path).expanduser().resolve() if catalyst_theme_frontier_json_path else None,
        "catalyst_theme_frontier_markdown_path": Path(catalyst_theme_frontier_markdown_path).expanduser().resolve() if catalyst_theme_frontier_markdown_path else None,
        "rank": (selection_target_rank, trade_date_rank, report_dir.stat().st_mtime_ns, report_dir.name),
    }


def _select_latest_btst_candidate(reports_root: Path, repo_root: Path) -> dict[str, Any] | None:
    candidates = [candidate for candidate in (_extract_btst_candidate(path, repo_root) for path in _discover_report_dirs(reports_root)) if candidate]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate["rank"])


def _build_static_entries(repo_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for spec in STATIC_ENTRY_SPECS:
        absolute_path = repo_root / spec["path"]
        if not absolute_path.exists() and spec["id"] in STATIC_ENTRY_GLOB_OVERRIDES and str(spec["path"]).startswith("data/reports/"):
            resolved_reports_root = repo_root / "data" / "reports"
            relative_name = str(spec["path"]).replace("data/reports/", "", 1)
            absolute_path = _resolve_existing_artifact_path(
                resolved_reports_root,
                relative_name,
                glob_pattern=STATIC_ENTRY_GLOB_OVERRIDES[spec["id"]],
            )
        entry = _build_entry(
            entry_id=spec["id"],
            absolute_path=absolute_path,
            repo_root=repo_root,
            report_type=spec["report_type"],
            topic=spec["topic"],
            usage=spec["usage"],
            priority=int(spec["priority"]),
            is_latest=bool(spec["is_latest"]),
            question=spec["question"],
            view_order=int(spec["view_order"]),
            time_scope=dict(spec["time_scope"]),
            source_kind=spec["source_kind"],
        )
        if entry:
            entries.append(entry)
    return entries


def _build_dynamic_latest_btst_entries(latest_btst_run: dict[str, Any] | None, repo_root: Path) -> list[dict[str, Any]]:
    if not latest_btst_run:
        return []

    report_dir = latest_btst_run["report_dir_path"]
    time_scope = {
        "label": "latest_btst_followup",
        "trade_date": latest_btst_run.get("trade_date"),
        "next_trade_date": latest_btst_run.get("next_trade_date"),
    }

    dynamic_specs = [
        {
            "id": "latest_btst_priority_board",
            "path": latest_btst_run.get("priority_board_markdown_path"),
            "report_type": "btst_next_day_priority_board_markdown",
            "topic": "btst_followup",
            "usage": "tomorrow_open",
            "priority": 1,
            "is_latest": True,
            "question": "明天应该按什么顺序看票",
            "view_order": 1,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_opening_watch_card",
            "path": latest_btst_run.get("opening_card_path"),
            "report_type": "btst_opening_watch_card",
            "topic": "btst_followup",
            "usage": "tomorrow_open",
            "priority": 2,
            "is_latest": True,
            "question": "明天开盘第一眼该看什么",
            "view_order": 2,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_execution_card_markdown",
            "path": latest_btst_run.get("card_markdown_path"),
            "report_type": "btst_premarket_execution_card_markdown",
            "topic": "btst_followup",
            "usage": "tomorrow_open",
            "priority": 3,
            "is_latest": True,
            "question": "当前执行姿态和 guardrails 是什么",
            "view_order": 3,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_brief_markdown",
            "path": latest_btst_run.get("brief_markdown_path"),
            "report_type": "btst_next_day_trade_brief_markdown",
            "topic": "btst_followup",
            "usage": "tomorrow_open",
            "priority": 4,
            "is_latest": True,
            "question": "明日主票、观察票和排除票结论是什么",
            "view_order": 4,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_session_summary",
            "path": latest_btst_run.get("session_summary_path"),
            "report_type": "paper_trading_session_summary",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 1,
            "is_latest": True,
            "question": "这次运行整体发生了什么",
            "view_order": 1,
            "source_kind": "generated_runtime_artifact",
        },
        {
            "id": "latest_btst_brief_json",
            "path": latest_btst_run.get("brief_json_path"),
            "report_type": "btst_next_day_trade_brief_json",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 2,
            "is_latest": True,
            "question": "结构化主票与观察票结论是什么",
            "view_order": 2,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_execution_card_json",
            "path": latest_btst_run.get("card_json_path"),
            "report_type": "btst_premarket_execution_card_json",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 3,
            "is_latest": True,
            "question": "结构化执行 guardrails 是什么",
            "view_order": 3,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_catalyst_theme_frontier_markdown",
            "path": latest_btst_run.get("catalyst_theme_frontier_markdown_path"),
            "report_type": "catalyst_theme_frontier_markdown",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 4,
            "is_latest": True,
            "question": "题材催化影子池离正式研究池还差什么",
            "view_order": 4,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_selection_snapshot",
            "path": latest_btst_run.get("selection_snapshot_path"),
            "report_type": "selection_snapshot",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 5,
            "is_latest": True,
            "question": "逐票底层证据是什么",
            "view_order": 5,
            "source_kind": "generated_runtime_artifact",
        },
    ]

    entries: list[dict[str, Any]] = []
    for spec in dynamic_specs:
        path = spec.get("path")
        if not path:
            continue
        entry = _build_entry(
            entry_id=spec["id"],
            absolute_path=Path(path),
            repo_root=repo_root,
            report_type=spec["report_type"],
            topic=spec["topic"],
            usage=spec["usage"],
            priority=int(spec["priority"]),
            is_latest=bool(spec["is_latest"]),
            question=spec["question"],
            view_order=int(spec["view_order"]),
            time_scope=dict(time_scope),
            source_kind=spec["source_kind"],
            report_dir=report_dir,
        )
        if entry:
            entries.append(entry)
    return entries


def refresh_latest_btst_catalyst_theme_frontier_artifacts(latest_btst_run: dict[str, Any] | None) -> dict[str, Any]:
    if not latest_btst_run:
        return {
            "status": "skipped_no_latest_btst_run",
        }

    report_dir = Path(latest_btst_run["report_dir"]).expanduser().resolve()
    summary_path = report_dir / "session_summary.json"
    if not summary_path.exists():
        return {
            "status": "skipped_missing_session_summary",
            "report_dir": report_dir.name,
        }

    try:
        frontier_result = generate_catalyst_theme_frontier_artifacts(
            report_dir,
            output_json=report_dir / CATALYST_THEME_FRONTIER_LATEST_JSON,
            output_md=report_dir / CATALYST_THEME_FRONTIER_LATEST_MD,
        )
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "report_dir": report_dir.name,
            "error": str(exc),
        }

    summary = _load_json(summary_path)
    followup = dict(summary.get("btst_followup") or {})
    followup.update(
        {
            "catalyst_theme_frontier_json": frontier_result["json_path"],
            "catalyst_theme_frontier_markdown": frontier_result["markdown_path"],
        }
    )
    summary["btst_followup"] = followup

    artifacts = dict(summary.get("artifacts") or {})
    artifacts.update(
        {
            "btst_catalyst_theme_frontier_json": frontier_result["json_path"],
            "btst_catalyst_theme_frontier_markdown": frontier_result["markdown_path"],
        }
    )
    summary["artifacts"] = artifacts
    _write_json(summary_path, summary)

    analysis = dict(frontier_result.get("analysis") or {})
    recommended_variant = dict(analysis.get("recommended_variant") or {})
    return {
        "status": "refreshed",
        "report_dir": report_dir.name,
        "shadow_candidate_count": int(analysis.get("shadow_candidate_count") or 0),
        "baseline_selected_count": int(analysis.get("baseline_selected_count") or 0),
        "recommended_variant_name": recommended_variant.get("variant_name"),
        "recommended_promoted_shadow_count": int(recommended_variant.get("promoted_shadow_count") or 0),
        "recommended_relaxation_cost": recommended_variant.get("threshold_relaxation_cost"),
        "output_json": frontier_result["json_path"],
        "output_markdown": frontier_result["markdown_path"],
    }


def refresh_btst_candidate_entry_shadow_lane_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    frontier_report_path = resolved_reports_root / CANDIDATE_ENTRY_FRONTIER_JSON
    structural_validation_path = resolved_reports_root / CANDIDATE_ENTRY_STRUCTURAL_VALIDATION_JSON
    score_frontier_path = resolved_reports_root / CANDIDATE_ENTRY_SCORE_FRONTIER_JSON
    tradeable_opportunity_pool_json_path = resolved_reports_root / BTST_TRADEABLE_OPPORTUNITY_POOL_JSON
    window_scan_json_path = resolved_reports_root / CANDIDATE_ENTRY_WINDOW_SCAN_JSON
    window_scan_md_path = resolved_reports_root / CANDIDATE_ENTRY_WINDOW_SCAN_MD
    rollout_governance_json_path = resolved_reports_root / CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_JSON
    rollout_governance_md_path = resolved_reports_root / CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_MD
    no_candidate_entry_action_board_json_path = resolved_reports_root / BTST_NO_CANDIDATE_ENTRY_ACTION_BOARD_JSON
    no_candidate_entry_action_board_md_path = resolved_reports_root / BTST_NO_CANDIDATE_ENTRY_ACTION_BOARD_MD
    no_candidate_entry_replay_bundle_json_path = resolved_reports_root / BTST_NO_CANDIDATE_ENTRY_REPLAY_BUNDLE_JSON
    no_candidate_entry_replay_bundle_md_path = resolved_reports_root / BTST_NO_CANDIDATE_ENTRY_REPLAY_BUNDLE_MD
    no_candidate_entry_failure_dossier_json_path = resolved_reports_root / BTST_NO_CANDIDATE_ENTRY_FAILURE_DOSSIER_JSON
    no_candidate_entry_failure_dossier_md_path = resolved_reports_root / BTST_NO_CANDIDATE_ENTRY_FAILURE_DOSSIER_MD
    watchlist_recall_dossier_json_path = resolved_reports_root / BTST_WATCHLIST_RECALL_DOSSIER_JSON
    watchlist_recall_dossier_md_path = resolved_reports_root / BTST_WATCHLIST_RECALL_DOSSIER_MD
    candidate_pool_recall_dossier_json_path = resolved_reports_root / BTST_CANDIDATE_POOL_RECALL_DOSSIER_JSON
    candidate_pool_recall_dossier_md_path = resolved_reports_root / BTST_CANDIDATE_POOL_RECALL_DOSSIER_MD
    candidate_pool_branch_priority_board_json_path = resolved_reports_root / BTST_CANDIDATE_POOL_BRANCH_PRIORITY_BOARD_JSON
    candidate_pool_branch_priority_board_md_path = resolved_reports_root / BTST_CANDIDATE_POOL_BRANCH_PRIORITY_BOARD_MD
    candidate_pool_lane_objective_support_json_path = resolved_reports_root / BTST_CANDIDATE_POOL_LANE_OBJECTIVE_SUPPORT_JSON
    candidate_pool_lane_objective_support_md_path = resolved_reports_root / BTST_CANDIDATE_POOL_LANE_OBJECTIVE_SUPPORT_MD
    candidate_pool_rebucket_shadow_pack_json_path = resolved_reports_root / BTST_CANDIDATE_POOL_REBUCKET_SHADOW_PACK_JSON
    candidate_pool_rebucket_shadow_pack_md_path = resolved_reports_root / BTST_CANDIDATE_POOL_REBUCKET_SHADOW_PACK_MD
    candidate_pool_rebucket_objective_validation_json_path = resolved_reports_root / BTST_CANDIDATE_POOL_REBUCKET_OBJECTIVE_VALIDATION_JSON
    candidate_pool_rebucket_objective_validation_md_path = resolved_reports_root / BTST_CANDIDATE_POOL_REBUCKET_OBJECTIVE_VALIDATION_MD
    candidate_pool_rebucket_comparison_bundle_json_path = resolved_reports_root / BTST_CANDIDATE_POOL_REBUCKET_COMPARISON_BUNDLE_JSON
    candidate_pool_rebucket_comparison_bundle_md_path = resolved_reports_root / BTST_CANDIDATE_POOL_REBUCKET_COMPARISON_BUNDLE_MD
    candidate_pool_corridor_validation_pack_json_path = resolved_reports_root / BTST_CANDIDATE_POOL_CORRIDOR_VALIDATION_PACK_JSON
    candidate_pool_corridor_validation_pack_md_path = resolved_reports_root / BTST_CANDIDATE_POOL_CORRIDOR_VALIDATION_PACK_MD
    candidate_pool_corridor_shadow_pack_json_path = resolved_reports_root / BTST_CANDIDATE_POOL_CORRIDOR_SHADOW_PACK_JSON
    candidate_pool_corridor_shadow_pack_md_path = resolved_reports_root / BTST_CANDIDATE_POOL_CORRIDOR_SHADOW_PACK_MD
    candidate_pool_lane_pair_board_json_path = resolved_reports_root / BTST_CANDIDATE_POOL_LANE_PAIR_BOARD_JSON
    candidate_pool_lane_pair_board_md_path = resolved_reports_root / BTST_CANDIDATE_POOL_LANE_PAIR_BOARD_MD
    candidate_pool_upstream_handoff_board_json_path = resolved_reports_root / BTST_CANDIDATE_POOL_UPSTREAM_HANDOFF_BOARD_JSON
    candidate_pool_upstream_handoff_board_md_path = resolved_reports_root / BTST_CANDIDATE_POOL_UPSTREAM_HANDOFF_BOARD_MD
    candidate_pool_corridor_uplift_runbook_json_path = resolved_reports_root / BTST_CANDIDATE_POOL_CORRIDOR_UPLIFT_RUNBOOK_JSON
    candidate_pool_corridor_uplift_runbook_md_path = resolved_reports_root / BTST_CANDIDATE_POOL_CORRIDOR_UPLIFT_RUNBOOK_MD

    required_inputs = {
        "frontier_report": frontier_report_path,
        "structural_validation": structural_validation_path,
        "score_frontier_report": score_frontier_path,
    }
    no_candidate_entry_action_board_analysis: dict[str, Any] = {}
    no_candidate_entry_action_board_status = "skipped_missing_tradeable_opportunity_pool"
    no_candidate_entry_replay_bundle_analysis: dict[str, Any] = {}
    no_candidate_entry_replay_bundle_status = "skipped_missing_action_board"
    no_candidate_entry_failure_dossier_analysis: dict[str, Any] = {}
    no_candidate_entry_failure_dossier_status = "skipped_missing_action_board"
    watchlist_recall_dossier_analysis: dict[str, Any] = {}
    watchlist_recall_dossier_status = "skipped_missing_failure_dossier"
    candidate_pool_recall_dossier_analysis: dict[str, Any] = {}
    candidate_pool_recall_dossier_status = "skipped_missing_watchlist_recall_dossier"
    candidate_pool_branch_priority_board_analysis: dict[str, Any] = {}
    candidate_pool_branch_priority_board_status = "skipped_missing_candidate_pool_recall_dossier"
    candidate_pool_lane_objective_support_analysis: dict[str, Any] = {}
    candidate_pool_lane_objective_support_status = "skipped_missing_candidate_pool_recall_dossier"
    candidate_pool_corridor_validation_pack_analysis: dict[str, Any] = {}
    candidate_pool_corridor_validation_pack_status = "skipped_missing_candidate_pool_recall_dossier"
    candidate_pool_corridor_shadow_pack_analysis: dict[str, Any] = {}
    candidate_pool_corridor_shadow_pack_status = "skipped_missing_candidate_pool_recall_dossier"
    candidate_pool_rebucket_shadow_pack_analysis: dict[str, Any] = {}
    candidate_pool_rebucket_shadow_pack_status = "skipped_missing_candidate_pool_recall_dossier"
    candidate_pool_rebucket_objective_validation_analysis: dict[str, Any] = {}
    candidate_pool_rebucket_objective_validation_status = "skipped_missing_candidate_pool_recall_dossier"
    candidate_pool_rebucket_comparison_bundle_analysis: dict[str, Any] = {}
    candidate_pool_rebucket_comparison_bundle_status = "skipped_missing_candidate_pool_recall_dossier"
    candidate_pool_lane_pair_board_analysis: dict[str, Any] = {}
    candidate_pool_lane_pair_board_status = "skipped_missing_candidate_pool_recall_dossier"
    candidate_pool_upstream_handoff_board_analysis: dict[str, Any] = {}
    candidate_pool_upstream_handoff_board_status = "skipped_missing_candidate_pool_recall_dossier"
    candidate_pool_corridor_uplift_runbook_analysis: dict[str, Any] = {}
    candidate_pool_corridor_uplift_runbook_status = "skipped_missing_candidate_pool_recall_dossier"
    if tradeable_opportunity_pool_json_path.exists():
        try:
            no_candidate_entry_action_board_analysis = analyze_btst_no_candidate_entry_action_board(
                tradeable_opportunity_pool_json_path,
                preserve_tickers=list(CANDIDATE_ENTRY_PRESERVE_TICKERS),
            )
            no_candidate_entry_action_board_json_path.write_text(json.dumps(no_candidate_entry_action_board_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            no_candidate_entry_action_board_md_path.write_text(render_btst_no_candidate_entry_action_board_markdown(no_candidate_entry_action_board_analysis), encoding="utf-8")
            no_candidate_entry_action_board_status = "refreshed"

            replay_report_dir_names = {
                str(row.get("primary_report_dir") or "").strip()
                for row in list(no_candidate_entry_action_board_analysis.get("priority_queue") or [])
                if str(row.get("primary_report_dir") or "").strip()
            }
            replay_report_dir_names.update(
                str(row.get("report_dir") or "").strip()
                for row in list(no_candidate_entry_action_board_analysis.get("window_hotspot_rows") or [])
                if str(row.get("report_dir") or "").strip()
            )
            available_replay_report_dir_names = [
                report_dir_name
                for report_dir_name in replay_report_dir_names
                if (resolved_reports_root / report_dir_name).exists()
            ]
            if available_replay_report_dir_names:
                no_candidate_entry_replay_bundle_analysis = analyze_btst_no_candidate_entry_replay_bundle(
                    no_candidate_entry_action_board_json_path,
                )
                no_candidate_entry_replay_bundle_json_path.write_text(json.dumps(no_candidate_entry_replay_bundle_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                no_candidate_entry_replay_bundle_md_path.write_text(render_btst_no_candidate_entry_replay_bundle_markdown(no_candidate_entry_replay_bundle_analysis), encoding="utf-8")
                no_candidate_entry_replay_bundle_status = "refreshed"
            else:
                no_candidate_entry_replay_bundle_status = "skipped_missing_replay_reports"

            no_candidate_entry_failure_dossier_analysis = analyze_btst_no_candidate_entry_failure_dossier(
                tradeable_opportunity_pool_json_path,
                action_board_path=no_candidate_entry_action_board_json_path,
                replay_bundle_path=no_candidate_entry_replay_bundle_json_path if no_candidate_entry_replay_bundle_analysis else None,
            )
            no_candidate_entry_failure_dossier_json_path.write_text(json.dumps(no_candidate_entry_failure_dossier_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            no_candidate_entry_failure_dossier_md_path.write_text(render_btst_no_candidate_entry_failure_dossier_markdown(no_candidate_entry_failure_dossier_analysis), encoding="utf-8")
            no_candidate_entry_failure_dossier_status = "refreshed"

            watchlist_recall_dossier_analysis = analyze_btst_watchlist_recall_dossier(
                tradeable_opportunity_pool_json_path,
                failure_dossier_path=no_candidate_entry_failure_dossier_json_path if no_candidate_entry_failure_dossier_analysis else None,
            )
            watchlist_recall_dossier_json_path.write_text(json.dumps(watchlist_recall_dossier_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            watchlist_recall_dossier_md_path.write_text(render_btst_watchlist_recall_dossier_markdown(watchlist_recall_dossier_analysis), encoding="utf-8")
            watchlist_recall_dossier_status = "refreshed"

            candidate_pool_recall_dossier_analysis = analyze_btst_candidate_pool_recall_dossier(
                tradeable_opportunity_pool_json_path,
                watchlist_recall_dossier_path=watchlist_recall_dossier_json_path if watchlist_recall_dossier_analysis else None,
                failure_dossier_path=no_candidate_entry_failure_dossier_json_path if no_candidate_entry_failure_dossier_analysis else None,
            )
            candidate_pool_recall_dossier_json_path.write_text(json.dumps(candidate_pool_recall_dossier_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_pool_recall_dossier_md_path.write_text(render_btst_candidate_pool_recall_dossier_markdown(candidate_pool_recall_dossier_analysis), encoding="utf-8")
            candidate_pool_recall_dossier_status = "refreshed"

            objective_monitor_json_path = resolved_reports_root / BTST_TPLUS1_TPLUS2_OBJECTIVE_MONITOR_JSON
            candidate_pool_lane_objective_support_analysis = analyze_btst_candidate_pool_lane_objective_support(
                candidate_pool_recall_dossier_json_path,
                objective_monitor_path=objective_monitor_json_path if objective_monitor_json_path.exists() else None,
            )
            candidate_pool_lane_objective_support_json_path.write_text(json.dumps(candidate_pool_lane_objective_support_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_pool_lane_objective_support_md_path.write_text(render_btst_candidate_pool_lane_objective_support_markdown(candidate_pool_lane_objective_support_analysis), encoding="utf-8")
            candidate_pool_lane_objective_support_status = "refreshed"

            candidate_pool_branch_priority_board_analysis = analyze_btst_candidate_pool_branch_priority_board(
                candidate_pool_recall_dossier_json_path,
                lane_objective_support_path=candidate_pool_lane_objective_support_json_path,
            )
            candidate_pool_branch_priority_board_json_path.write_text(json.dumps(candidate_pool_branch_priority_board_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_pool_branch_priority_board_md_path.write_text(render_btst_candidate_pool_branch_priority_board_markdown(candidate_pool_branch_priority_board_analysis), encoding="utf-8")
            candidate_pool_branch_priority_board_status = "refreshed"

            candidate_pool_corridor_validation_pack_analysis = analyze_btst_candidate_pool_corridor_validation_pack(
                candidate_pool_recall_dossier_json_path,
                lane_objective_support_path=candidate_pool_lane_objective_support_json_path,
                branch_priority_board_path=candidate_pool_branch_priority_board_json_path,
                objective_monitor_path=objective_monitor_json_path if objective_monitor_json_path.exists() else None,
            )
            candidate_pool_corridor_validation_pack_json_path.write_text(json.dumps(candidate_pool_corridor_validation_pack_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_pool_corridor_validation_pack_md_path.write_text(render_btst_candidate_pool_corridor_validation_pack_markdown(candidate_pool_corridor_validation_pack_analysis), encoding="utf-8")
            candidate_pool_corridor_validation_pack_status = str(candidate_pool_corridor_validation_pack_analysis.get("pack_status") or "refreshed")

            candidate_pool_corridor_shadow_pack_analysis = analyze_btst_candidate_pool_corridor_shadow_pack(candidate_pool_corridor_validation_pack_json_path)
            candidate_pool_corridor_shadow_pack_json_path.write_text(json.dumps(candidate_pool_corridor_shadow_pack_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_pool_corridor_shadow_pack_md_path.write_text(render_btst_candidate_pool_corridor_shadow_pack_markdown(candidate_pool_corridor_shadow_pack_analysis), encoding="utf-8")
            candidate_pool_corridor_shadow_pack_status = str(candidate_pool_corridor_shadow_pack_analysis.get("shadow_status") or "refreshed")

            rebucket_candidates = [
                dict(row)
                for row in list(candidate_pool_recall_dossier_analysis.get("priority_handoff_branch_experiment_queue") or [])
                if str(row.get("prototype_type") or "") == "post_gate_competition_rebucket_probe"
            ]
            rebucket_ticker = str(list(rebucket_candidates[0].get("tickers") or [None])[0] or "") or None if rebucket_candidates else None
            candidate_pool_rebucket_shadow_pack_analysis = run_btst_candidate_pool_rebucket_shadow_pack(
                candidate_pool_recall_dossier_json_path,
                output_dir=resolved_reports_root,
                ticker=rebucket_ticker,
            )
            candidate_pool_rebucket_shadow_pack_json_path.write_text(json.dumps(candidate_pool_rebucket_shadow_pack_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_pool_rebucket_shadow_pack_md_path.write_text(render_btst_candidate_pool_rebucket_shadow_pack_markdown(candidate_pool_rebucket_shadow_pack_analysis), encoding="utf-8")
            candidate_pool_rebucket_shadow_pack_status = str(candidate_pool_rebucket_shadow_pack_analysis.get("shadow_status") or "skipped_no_rebucket_candidate")

            candidate_pool_rebucket_objective_validation_analysis = analyze_btst_candidate_pool_rebucket_objective_validation(
                candidate_pool_recall_dossier_json_path,
                objective_monitor_path=objective_monitor_json_path if objective_monitor_json_path.exists() else None,
                lane_objective_support_path=candidate_pool_lane_objective_support_json_path if candidate_pool_lane_objective_support_analysis else None,
                ticker=rebucket_ticker,
            )
            candidate_pool_rebucket_objective_validation_json_path.write_text(json.dumps(candidate_pool_rebucket_objective_validation_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_pool_rebucket_objective_validation_md_path.write_text(render_btst_candidate_pool_rebucket_objective_validation_markdown(candidate_pool_rebucket_objective_validation_analysis), encoding="utf-8")
            if rebucket_candidates:
                candidate_pool_rebucket_objective_validation_status = "refreshed"
            else:
                candidate_pool_rebucket_objective_validation_status = str(candidate_pool_rebucket_objective_validation_analysis.get("validation_status") or "skipped_no_rebucket_candidate")

            candidate_pool_rebucket_comparison_bundle_analysis = analyze_btst_candidate_pool_rebucket_comparison_bundle(
                candidate_pool_recall_dossier_json_path,
                lane_objective_support_path=candidate_pool_lane_objective_support_json_path,
                branch_priority_board_path=candidate_pool_branch_priority_board_json_path,
                rebucket_shadow_pack_path=candidate_pool_rebucket_shadow_pack_json_path,
                rebucket_objective_validation_path=candidate_pool_rebucket_objective_validation_json_path,
                objective_monitor_path=objective_monitor_json_path if objective_monitor_json_path.exists() else None,
            )
            candidate_pool_rebucket_comparison_bundle_json_path.write_text(json.dumps(candidate_pool_rebucket_comparison_bundle_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_pool_rebucket_comparison_bundle_md_path.write_text(render_btst_candidate_pool_rebucket_comparison_bundle_markdown(candidate_pool_rebucket_comparison_bundle_analysis), encoding="utf-8")
            candidate_pool_rebucket_comparison_bundle_status = str(candidate_pool_rebucket_comparison_bundle_analysis.get("bundle_status") or "refreshed")

            candidate_pool_upstream_handoff_board_analysis = analyze_btst_candidate_pool_upstream_handoff_board(
                no_candidate_entry_failure_dossier_json_path,
                watchlist_recall_dossier_path=watchlist_recall_dossier_json_path,
                candidate_pool_recall_dossier_path=candidate_pool_recall_dossier_json_path,
            )
            candidate_pool_upstream_handoff_board_json_path.write_text(json.dumps(candidate_pool_upstream_handoff_board_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_pool_upstream_handoff_board_md_path.write_text(render_btst_candidate_pool_upstream_handoff_board_markdown(candidate_pool_upstream_handoff_board_analysis), encoding="utf-8")
            candidate_pool_upstream_handoff_board_status = str(candidate_pool_upstream_handoff_board_analysis.get("board_status") or "refreshed")

            candidate_pool_lane_pair_board_analysis = analyze_btst_candidate_pool_lane_pair_board(
                candidate_pool_corridor_shadow_pack_json_path,
                candidate_pool_rebucket_comparison_bundle_json_path,
                upstream_handoff_board_path=candidate_pool_upstream_handoff_board_json_path,
            )
            candidate_pool_lane_pair_board_json_path.write_text(json.dumps(candidate_pool_lane_pair_board_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_pool_lane_pair_board_md_path.write_text(render_btst_candidate_pool_lane_pair_board_markdown(candidate_pool_lane_pair_board_analysis), encoding="utf-8")
            candidate_pool_lane_pair_board_status = str(candidate_pool_lane_pair_board_analysis.get("pair_status") or "refreshed")

            candidate_pool_corridor_uplift_runbook_analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
                candidate_pool_recall_dossier_json_path,
                corridor_shadow_pack_path=candidate_pool_corridor_shadow_pack_json_path,
                lane_pair_board_path=candidate_pool_lane_pair_board_json_path,
            )
            candidate_pool_corridor_uplift_runbook_json_path.write_text(json.dumps(candidate_pool_corridor_uplift_runbook_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_pool_corridor_uplift_runbook_md_path.write_text(render_btst_candidate_pool_corridor_uplift_runbook_markdown(candidate_pool_corridor_uplift_runbook_analysis), encoding="utf-8")
            candidate_pool_corridor_uplift_runbook_status = str(candidate_pool_corridor_uplift_runbook_analysis.get("runbook_status") or "refreshed")
        except Exception as exc:
            return {
                "status": "skipped_refresh_error",
                "missing_inputs": [],
                "window_report_count": 0,
                "error": str(exc),
            }

    missing_inputs = [label for label, path in required_inputs.items() if not path.exists()]
    if missing_inputs:
        return {
            "status": "skipped_missing_inputs",
            "missing_inputs": missing_inputs,
            "window_report_count": 0,
            "no_candidate_entry_action_board_status": no_candidate_entry_action_board_status,
            "no_candidate_entry_priority_queue_count": no_candidate_entry_action_board_analysis.get("priority_queue_count"),
            "no_candidate_entry_top_tickers": no_candidate_entry_action_board_analysis.get("top_priority_tickers"),
            "no_candidate_entry_hotspot_report_dirs": no_candidate_entry_action_board_analysis.get("top_hotspot_report_dirs"),
            "no_candidate_entry_action_board_json": no_candidate_entry_action_board_json_path.as_posix() if no_candidate_entry_action_board_analysis else None,
            "no_candidate_entry_replay_bundle_status": no_candidate_entry_replay_bundle_status,
            "no_candidate_entry_replay_bundle_json": no_candidate_entry_replay_bundle_json_path.as_posix() if no_candidate_entry_replay_bundle_analysis else None,
            "no_candidate_entry_promising_tickers": no_candidate_entry_replay_bundle_analysis.get("promising_priority_tickers"),
            "no_candidate_entry_failure_dossier_status": no_candidate_entry_failure_dossier_status,
            "no_candidate_entry_failure_dossier_json": no_candidate_entry_failure_dossier_json_path.as_posix() if no_candidate_entry_failure_dossier_analysis else None,
            "no_candidate_entry_upstream_absence_tickers": no_candidate_entry_failure_dossier_analysis.get("top_upstream_absence_tickers"),
            "no_candidate_entry_handoff_stage_counts": no_candidate_entry_failure_dossier_analysis.get("priority_handoff_stage_counts"),
            "no_candidate_entry_absent_from_watchlist_tickers": no_candidate_entry_failure_dossier_analysis.get("top_absent_from_watchlist_tickers"),
            "no_candidate_entry_watchlist_handoff_gap_tickers": no_candidate_entry_failure_dossier_analysis.get("top_watchlist_visible_but_not_candidate_entry_tickers"),
            "no_candidate_entry_candidate_entry_target_gap_tickers": no_candidate_entry_failure_dossier_analysis.get("top_candidate_entry_visible_but_not_selection_target_tickers"),
            "no_candidate_entry_handoff_action_queue_task_ids": [
                str(row.get("task_id") or "")
                for row in list(no_candidate_entry_failure_dossier_analysis.get("priority_handoff_action_queue") or [])[:3]
                if str(row.get("task_id") or "").strip()
            ],
            "no_candidate_entry_semantic_miss_tickers": no_candidate_entry_failure_dossier_analysis.get("top_candidate_entry_semantic_miss_tickers"),
            "watchlist_recall_dossier_status": watchlist_recall_dossier_status,
            "watchlist_recall_dossier_json": watchlist_recall_dossier_json_path.as_posix() if watchlist_recall_dossier_analysis else None,
            "watchlist_recall_stage_counts": watchlist_recall_dossier_analysis.get("priority_recall_stage_counts"),
            "watchlist_recall_absent_from_candidate_pool_tickers": watchlist_recall_dossier_analysis.get("top_absent_from_candidate_pool_tickers"),
            "watchlist_recall_candidate_pool_layer_b_gap_tickers": watchlist_recall_dossier_analysis.get("top_candidate_pool_visible_but_missing_layer_b_tickers"),
            "watchlist_recall_layer_b_watchlist_gap_tickers": watchlist_recall_dossier_analysis.get("top_layer_b_visible_but_missing_watchlist_tickers"),
            "watchlist_recall_action_queue_task_ids": [
                str(row.get("task_id") or "")
                for row in list(watchlist_recall_dossier_analysis.get("action_queue") or [])[:3]
                if str(row.get("task_id") or "").strip()
            ],
            "candidate_pool_recall_dossier_status": candidate_pool_recall_dossier_status,
            "candidate_pool_recall_dossier_json": candidate_pool_recall_dossier_json_path.as_posix() if candidate_pool_recall_dossier_analysis else None,
            "candidate_pool_recall_stage_counts": candidate_pool_recall_dossier_analysis.get("priority_stage_counts"),
            "candidate_pool_recall_dominant_stage": candidate_pool_recall_dossier_analysis.get("dominant_stage"),
            "candidate_pool_recall_top_stage_tickers": candidate_pool_recall_dossier_analysis.get("top_stage_tickers"),
            "candidate_pool_recall_truncation_frontier_summary": candidate_pool_recall_dossier_analysis.get("truncation_frontier_summary"),
            "candidate_pool_recall_dominant_liquidity_gap_mode": dict(candidate_pool_recall_dossier_analysis.get("truncation_frontier_summary") or {}).get("dominant_liquidity_gap_mode"),
            "candidate_pool_recall_focus_liquidity_profiles": list(dict(candidate_pool_recall_dossier_analysis.get("focus_liquidity_profile_summary") or {}).get("primary_focus_tickers") or [])[:3],
            "candidate_pool_recall_priority_handoff_counts": dict(dict(candidate_pool_recall_dossier_analysis.get("focus_liquidity_profile_summary") or {}).get("priority_handoff_counts") or {}),
            "candidate_pool_recall_priority_handoff_branch_diagnoses": list(candidate_pool_recall_dossier_analysis.get("priority_handoff_branch_diagnoses") or [])[:3],
            "candidate_pool_recall_priority_handoff_branch_mechanisms": list(candidate_pool_recall_dossier_analysis.get("priority_handoff_branch_mechanisms") or [])[:3],
            "candidate_pool_recall_priority_handoff_branch_experiment_queue": list(candidate_pool_recall_dossier_analysis.get("priority_handoff_branch_experiment_queue") or [])[:3],
            "candidate_pool_branch_priority_board_status": candidate_pool_branch_priority_board_status,
            "candidate_pool_branch_priority_board_json": candidate_pool_branch_priority_board_json_path.as_posix() if candidate_pool_branch_priority_board_analysis else None,
            "candidate_pool_branch_priority_board_rows": list(candidate_pool_branch_priority_board_analysis.get("branch_rows") or [])[:3],
            "candidate_pool_branch_priority_alignment_status": candidate_pool_branch_priority_board_analysis.get("priority_alignment_status"),
            "candidate_pool_branch_priority_alignment_summary": candidate_pool_branch_priority_board_analysis.get("alignment_summary"),
            "candidate_pool_corridor_validation_pack_status": candidate_pool_corridor_validation_pack_status,
            "candidate_pool_corridor_validation_pack_json": candidate_pool_corridor_validation_pack_json_path.as_posix() if candidate_pool_corridor_validation_pack_analysis else None,
            "candidate_pool_corridor_validation_pack_summary": {
                "pack_status": candidate_pool_corridor_validation_pack_analysis.get("pack_status"),
                "focus_ticker": candidate_pool_corridor_validation_pack_analysis.get("focus_ticker"),
                "primary_validation_ticker": dict(candidate_pool_corridor_validation_pack_analysis.get("primary_validation_ticker") or {}).get("ticker"),
                "leader_gap_to_target": candidate_pool_corridor_validation_pack_analysis.get("leader_gap_to_target"),
                "promotion_readiness_status": candidate_pool_corridor_validation_pack_analysis.get("promotion_readiness_status"),
                "parallel_watch_tickers": [str(row.get("ticker") or "") for row in list(candidate_pool_corridor_validation_pack_analysis.get("parallel_watch_tickers") or [])[:3] if str(row.get("ticker") or "").strip()],
            },
            "candidate_pool_corridor_shadow_pack_status": candidate_pool_corridor_shadow_pack_status,
            "candidate_pool_corridor_shadow_pack_json": candidate_pool_corridor_shadow_pack_json_path.as_posix() if candidate_pool_corridor_shadow_pack_analysis else None,
            "candidate_pool_corridor_shadow_pack_summary": {
                "shadow_status": candidate_pool_corridor_shadow_pack_analysis.get("shadow_status"),
                "primary_shadow_replay": dict(candidate_pool_corridor_shadow_pack_analysis.get("primary_shadow_replay") or {}).get("ticker"),
                "parallel_watch_tickers": [str(row.get("ticker") or "") for row in list(candidate_pool_corridor_shadow_pack_analysis.get("parallel_watch_lanes") or [])[:3] if str(row.get("ticker") or "").strip()],
            },
            "candidate_pool_lane_objective_support_status": candidate_pool_lane_objective_support_status,
            "candidate_pool_lane_objective_support_json": candidate_pool_lane_objective_support_json_path.as_posix() if candidate_pool_lane_objective_support_analysis else None,
            "candidate_pool_lane_objective_support_rows": list(candidate_pool_lane_objective_support_analysis.get("branch_rows") or [])[:3],
            "candidate_pool_rebucket_shadow_pack_status": candidate_pool_rebucket_shadow_pack_status,
            "candidate_pool_rebucket_shadow_pack_json": candidate_pool_rebucket_shadow_pack_json_path.as_posix() if candidate_pool_rebucket_shadow_pack_analysis else None,
            "candidate_pool_rebucket_shadow_pack_experiment": dict(candidate_pool_rebucket_shadow_pack_analysis.get("experiment") or {}),
            "candidate_pool_rebucket_objective_validation_status": candidate_pool_rebucket_objective_validation_status,
            "candidate_pool_rebucket_objective_validation_json": candidate_pool_rebucket_objective_validation_json_path.as_posix() if candidate_pool_rebucket_objective_validation_analysis else None,
            "candidate_pool_rebucket_objective_validation_summary": {
                "validation_status": candidate_pool_rebucket_objective_validation_analysis.get("validation_status"),
                "support_verdict": dict(candidate_pool_rebucket_objective_validation_analysis.get("branch_objective_row") or {}).get("support_verdict"),
                "mean_t_plus_2_return": dict(candidate_pool_rebucket_objective_validation_analysis.get("branch_objective_row") or {}).get("mean_t_plus_2_return"),
            },
            "candidate_pool_rebucket_comparison_bundle_status": candidate_pool_rebucket_comparison_bundle_status,
            "candidate_pool_rebucket_comparison_bundle_json": candidate_pool_rebucket_comparison_bundle_json_path.as_posix() if candidate_pool_rebucket_comparison_bundle_analysis else None,
            "candidate_pool_rebucket_comparison_bundle_summary": {
                "bundle_status": candidate_pool_rebucket_comparison_bundle_analysis.get("bundle_status"),
                "structural_leader": dict(candidate_pool_rebucket_comparison_bundle_analysis.get("structural_leader") or {}).get("priority_handoff"),
                "objective_leader": dict(candidate_pool_rebucket_comparison_bundle_analysis.get("objective_leader") or {}).get("priority_handoff"),
                "rebucket_ticker": dict(candidate_pool_rebucket_comparison_bundle_analysis.get("rebucket_objective_row") or {}).get("ticker")
                or (list(dict(candidate_pool_rebucket_comparison_bundle_analysis.get("rebucket_objective_row") or {}).get("tickers") or [])[:1] or [None])[0],
                "objective_fit_gap_vs_corridor": dict(candidate_pool_rebucket_comparison_bundle_analysis.get("comparison") or {}).get("objective_fit_gap_vs_corridor"),
                "mean_t_plus_2_return_gap_vs_corridor": dict(candidate_pool_rebucket_comparison_bundle_analysis.get("comparison") or {}).get("mean_t_plus_2_return_gap_vs_corridor"),
            },
            "candidate_pool_lane_pair_board_status": candidate_pool_lane_pair_board_status,
            "candidate_pool_lane_pair_board_json": candidate_pool_lane_pair_board_json_path.as_posix() if candidate_pool_lane_pair_board_analysis else None,
            "candidate_pool_lane_pair_board_summary": {
                "pair_status": candidate_pool_lane_pair_board_analysis.get("pair_status"),
                "board_leader": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("ticker"),
                "leader_lane_family": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("lane_family"),
                "leader_governance_status": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("governance_status"),
                "leader_governance_blocker": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("governance_blocker"),
                "leader_governance_execution_quality": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("governance_execution_quality_label"),
                "leader_governance_entry_timing_bias": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("governance_entry_timing_bias"),
                "leader_current_decision": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("current_decision"),
                "parallel_watch_ticker": next(
                    (row.get("ticker") for row in list(candidate_pool_lane_pair_board_analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"),
                    None,
                ),
                "parallel_watch_governance_blocker": next(
                    (row.get("governance_blocker") for row in list(candidate_pool_lane_pair_board_analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"),
                    None,
                ),
                "parallel_watch_same_source_sample_count": next(
                    (row.get("governance_same_source_sample_count") for row in list(candidate_pool_lane_pair_board_analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"),
                    None,
                ),
                "parallel_watch_next_close_positive_rate": next(
                    (row.get("governance_same_source_next_close_positive_rate") for row in list(candidate_pool_lane_pair_board_analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"),
                    None,
                ),
                "parallel_watch_next_close_return_mean": next(
                    (row.get("governance_same_source_next_close_return_mean") for row in list(candidate_pool_lane_pair_board_analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"),
                    None,
                ),
            },
            "candidate_pool_upstream_handoff_board_status": candidate_pool_upstream_handoff_board_status,
            "candidate_pool_upstream_handoff_board_json": candidate_pool_upstream_handoff_board_json_path.as_posix() if candidate_pool_upstream_handoff_board_analysis else None,
            "candidate_pool_upstream_handoff_board_summary": {
                "board_status": candidate_pool_upstream_handoff_board_analysis.get("board_status"),
                "focus_tickers": list(candidate_pool_upstream_handoff_board_analysis.get("focus_tickers") or [])[:3],
                "first_broken_handoff_counts": dict(dict(candidate_pool_upstream_handoff_board_analysis.get("stage_summary") or {}).get("first_broken_handoff_counts") or {}),
                "historical_shadow_probe_tickers": [
                    str(row.get("ticker") or "")
                    for row in list(candidate_pool_upstream_handoff_board_analysis.get("board_rows") or [])
                    if str(row.get("board_phase") or "") == "historical_shadow_probe_gap" and str(row.get("ticker") or "").strip()
                ][:3],
            },
            "candidate_pool_corridor_uplift_runbook_status": candidate_pool_corridor_uplift_runbook_status,
            "candidate_pool_corridor_uplift_runbook_json": candidate_pool_corridor_uplift_runbook_json_path.as_posix() if candidate_pool_corridor_uplift_runbook_analysis else None,
            "candidate_pool_corridor_uplift_runbook_summary": {
                "runbook_status": candidate_pool_corridor_uplift_runbook_analysis.get("runbook_status"),
                "primary_shadow_replay": candidate_pool_corridor_uplift_runbook_analysis.get("primary_shadow_replay"),
                "parallel_watch_tickers": list(candidate_pool_corridor_uplift_runbook_analysis.get("parallel_watch_tickers") or [])[:3],
                "excluded_low_gate_tail_tickers": list(candidate_pool_corridor_uplift_runbook_analysis.get("excluded_low_gate_tail_tickers") or [])[:3],
                "prototype_type": candidate_pool_corridor_uplift_runbook_analysis.get("prototype_type"),
                "next_step": candidate_pool_corridor_uplift_runbook_analysis.get("next_step"),
                "execution_step_head": next(iter(list(candidate_pool_corridor_uplift_runbook_analysis.get("execution_steps") or [])), None),
                "execution_command_head": next(iter(list(candidate_pool_corridor_uplift_runbook_analysis.get("execution_commands") or [])), None),
                "guardrail_head": next(iter(list(candidate_pool_corridor_uplift_runbook_analysis.get("guardrails") or [])), None),
            },
            "continuation_focus_summary": _build_continuation_focus_summary(resolved_reports_root),
            "selected_outcome_refresh_summary": _build_selected_outcome_refresh_summary(resolved_reports_root),
            "carryover_multiday_continuation_audit_summary": _build_carryover_multiday_continuation_audit_summary(resolved_reports_root),
            "carryover_aligned_peer_harvest_summary": _build_carryover_aligned_peer_harvest_summary(resolved_reports_root),
            "carryover_peer_expansion_summary": _build_carryover_peer_expansion_summary(resolved_reports_root),
            "carryover_aligned_peer_proof_summary": _build_carryover_aligned_peer_proof_summary(resolved_reports_root),
            "carryover_peer_promotion_gate_summary": _build_carryover_peer_promotion_gate_summary(resolved_reports_root),
            "continuation_promotion_ready_summary": _build_continuation_promotion_ready_summary(resolved_reports_root),
            "default_merge_review_summary": _build_default_merge_review_summary(resolved_reports_root),
            "default_merge_historical_counterfactual_summary": _build_default_merge_historical_counterfactual_summary(resolved_reports_root),
            "continuation_merge_candidate_ranking_summary": _build_continuation_merge_candidate_ranking_summary(resolved_reports_root),
            "default_merge_strict_counterfactual_summary": _build_default_merge_strict_counterfactual_summary(resolved_reports_root),
            "merge_replay_validation_summary": _build_merge_replay_validation_summary(resolved_reports_root),
            "transient_probe_summary": _build_transient_probe_summary(resolved_reports_root),
            "execution_constraint_rollup": _build_execution_constraint_rollup(resolved_reports_root),
            "candidate_pool_recall_action_queue_task_ids": [
                str(row.get("task_id") or "")
                for row in list(candidate_pool_recall_dossier_analysis.get("action_queue") or [])[:3]
                if str(row.get("task_id") or "").strip()
            ],
        }

    report_dirs = [path for path in _discover_report_dirs(resolved_reports_root) if "paper_trading_window" in path.name]
    if not report_dirs:
        return {
            "status": "skipped_no_window_reports",
            "missing_inputs": [],
            "window_report_count": 0,
            "no_candidate_entry_action_board_status": no_candidate_entry_action_board_status,
            "no_candidate_entry_priority_queue_count": no_candidate_entry_action_board_analysis.get("priority_queue_count"),
            "no_candidate_entry_top_tickers": no_candidate_entry_action_board_analysis.get("top_priority_tickers"),
            "no_candidate_entry_hotspot_report_dirs": no_candidate_entry_action_board_analysis.get("top_hotspot_report_dirs"),
            "no_candidate_entry_action_board_json": no_candidate_entry_action_board_json_path.as_posix() if no_candidate_entry_action_board_analysis else None,
            "no_candidate_entry_replay_bundle_status": no_candidate_entry_replay_bundle_status,
            "no_candidate_entry_replay_bundle_json": no_candidate_entry_replay_bundle_json_path.as_posix() if no_candidate_entry_replay_bundle_analysis else None,
            "no_candidate_entry_promising_tickers": no_candidate_entry_replay_bundle_analysis.get("promising_priority_tickers"),
            "no_candidate_entry_failure_dossier_status": no_candidate_entry_failure_dossier_status,
            "no_candidate_entry_failure_dossier_json": no_candidate_entry_failure_dossier_json_path.as_posix() if no_candidate_entry_failure_dossier_analysis else None,
            "no_candidate_entry_upstream_absence_tickers": no_candidate_entry_failure_dossier_analysis.get("top_upstream_absence_tickers"),
            "no_candidate_entry_handoff_stage_counts": no_candidate_entry_failure_dossier_analysis.get("priority_handoff_stage_counts"),
            "no_candidate_entry_absent_from_watchlist_tickers": no_candidate_entry_failure_dossier_analysis.get("top_absent_from_watchlist_tickers"),
            "no_candidate_entry_watchlist_handoff_gap_tickers": no_candidate_entry_failure_dossier_analysis.get("top_watchlist_visible_but_not_candidate_entry_tickers"),
            "no_candidate_entry_candidate_entry_target_gap_tickers": no_candidate_entry_failure_dossier_analysis.get("top_candidate_entry_visible_but_not_selection_target_tickers"),
            "no_candidate_entry_handoff_action_queue_task_ids": [
                str(row.get("task_id") or "")
                for row in list(no_candidate_entry_failure_dossier_analysis.get("priority_handoff_action_queue") or [])[:3]
                if str(row.get("task_id") or "").strip()
            ],
            "no_candidate_entry_semantic_miss_tickers": no_candidate_entry_failure_dossier_analysis.get("top_candidate_entry_semantic_miss_tickers"),
            "watchlist_recall_dossier_status": watchlist_recall_dossier_status,
            "watchlist_recall_dossier_json": watchlist_recall_dossier_json_path.as_posix() if watchlist_recall_dossier_analysis else None,
            "watchlist_recall_stage_counts": watchlist_recall_dossier_analysis.get("priority_recall_stage_counts"),
            "watchlist_recall_absent_from_candidate_pool_tickers": watchlist_recall_dossier_analysis.get("top_absent_from_candidate_pool_tickers"),
            "watchlist_recall_candidate_pool_layer_b_gap_tickers": watchlist_recall_dossier_analysis.get("top_candidate_pool_visible_but_missing_layer_b_tickers"),
            "watchlist_recall_layer_b_watchlist_gap_tickers": watchlist_recall_dossier_analysis.get("top_layer_b_visible_but_missing_watchlist_tickers"),
            "watchlist_recall_action_queue_task_ids": [
                str(row.get("task_id") or "")
                for row in list(watchlist_recall_dossier_analysis.get("action_queue") or [])[:3]
                if str(row.get("task_id") or "").strip()
            ],
            "candidate_pool_recall_dossier_status": candidate_pool_recall_dossier_status,
            "candidate_pool_recall_dossier_json": candidate_pool_recall_dossier_json_path.as_posix() if candidate_pool_recall_dossier_analysis else None,
            "candidate_pool_recall_stage_counts": candidate_pool_recall_dossier_analysis.get("priority_stage_counts"),
            "candidate_pool_recall_dominant_stage": candidate_pool_recall_dossier_analysis.get("dominant_stage"),
            "candidate_pool_recall_top_stage_tickers": candidate_pool_recall_dossier_analysis.get("top_stage_tickers"),
            "candidate_pool_recall_truncation_frontier_summary": candidate_pool_recall_dossier_analysis.get("truncation_frontier_summary"),
            "candidate_pool_recall_dominant_liquidity_gap_mode": dict(candidate_pool_recall_dossier_analysis.get("truncation_frontier_summary") or {}).get("dominant_liquidity_gap_mode"),
            "candidate_pool_recall_focus_liquidity_profiles": list(dict(candidate_pool_recall_dossier_analysis.get("focus_liquidity_profile_summary") or {}).get("primary_focus_tickers") or [])[:3],
            "candidate_pool_recall_priority_handoff_counts": dict(dict(candidate_pool_recall_dossier_analysis.get("focus_liquidity_profile_summary") or {}).get("priority_handoff_counts") or {}),
            "candidate_pool_recall_priority_handoff_branch_diagnoses": list(candidate_pool_recall_dossier_analysis.get("priority_handoff_branch_diagnoses") or [])[:3],
            "candidate_pool_recall_priority_handoff_branch_mechanisms": list(candidate_pool_recall_dossier_analysis.get("priority_handoff_branch_mechanisms") or [])[:3],
            "candidate_pool_recall_priority_handoff_branch_experiment_queue": list(candidate_pool_recall_dossier_analysis.get("priority_handoff_branch_experiment_queue") or [])[:3],
            "candidate_pool_branch_priority_board_status": candidate_pool_branch_priority_board_status,
            "candidate_pool_branch_priority_board_json": candidate_pool_branch_priority_board_json_path.as_posix() if candidate_pool_branch_priority_board_analysis else None,
            "candidate_pool_branch_priority_board_rows": list(candidate_pool_branch_priority_board_analysis.get("branch_rows") or [])[:3],
            "candidate_pool_branch_priority_alignment_status": candidate_pool_branch_priority_board_analysis.get("priority_alignment_status"),
            "candidate_pool_branch_priority_alignment_summary": candidate_pool_branch_priority_board_analysis.get("alignment_summary"),
            "candidate_pool_lane_objective_support_status": candidate_pool_lane_objective_support_status,
            "candidate_pool_lane_objective_support_json": candidate_pool_lane_objective_support_json_path.as_posix() if candidate_pool_lane_objective_support_analysis else None,
            "candidate_pool_lane_objective_support_rows": list(candidate_pool_lane_objective_support_analysis.get("branch_rows") or [])[:3],
            "candidate_pool_rebucket_shadow_pack_status": candidate_pool_rebucket_shadow_pack_status,
            "candidate_pool_rebucket_shadow_pack_json": candidate_pool_rebucket_shadow_pack_json_path.as_posix() if candidate_pool_rebucket_shadow_pack_analysis else None,
            "candidate_pool_rebucket_shadow_pack_experiment": dict(candidate_pool_rebucket_shadow_pack_analysis.get("experiment") or {}),
            "candidate_pool_rebucket_objective_validation_status": candidate_pool_rebucket_objective_validation_status,
            "candidate_pool_rebucket_objective_validation_json": candidate_pool_rebucket_objective_validation_json_path.as_posix() if candidate_pool_rebucket_objective_validation_analysis else None,
            "candidate_pool_rebucket_objective_validation_summary": {
                "validation_status": candidate_pool_rebucket_objective_validation_analysis.get("validation_status"),
                "support_verdict": dict(candidate_pool_rebucket_objective_validation_analysis.get("branch_objective_row") or {}).get("support_verdict"),
                "mean_t_plus_2_return": dict(candidate_pool_rebucket_objective_validation_analysis.get("branch_objective_row") or {}).get("mean_t_plus_2_return"),
            },
            "candidate_pool_recall_action_queue_task_ids": [
                str(row.get("task_id") or "")
                for row in list(candidate_pool_recall_dossier_analysis.get("action_queue") or [])[:3]
                if str(row.get("task_id") or "").strip()
            ],
        }

    try:
        window_scan_analysis = analyze_btst_candidate_entry_window_scan(
            report_dirs,
            structural_variant="exclude_watchlist_avoid_weak_structure_entries",
            focus_tickers=list(CANDIDATE_ENTRY_FOCUS_TICKERS),
            preserve_tickers=list(CANDIDATE_ENTRY_PRESERVE_TICKERS),
        )
        window_scan_json_path.write_text(json.dumps(window_scan_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        window_scan_md_path.write_text(render_btst_candidate_entry_window_scan_markdown(window_scan_analysis), encoding="utf-8")

        rollout_governance_analysis = analyze_btst_candidate_entry_rollout_governance(
            frontier_report_path,
            structural_validation_path=structural_validation_path,
            window_scan_path=window_scan_json_path,
            score_frontier_path=score_frontier_path,
            no_candidate_entry_action_board_path=no_candidate_entry_action_board_json_path if no_candidate_entry_action_board_analysis else None,
            no_candidate_entry_replay_bundle_path=no_candidate_entry_replay_bundle_json_path if no_candidate_entry_replay_bundle_analysis else None,
            no_candidate_entry_failure_dossier_path=no_candidate_entry_failure_dossier_json_path if no_candidate_entry_failure_dossier_analysis else None,
            watchlist_recall_dossier_path=watchlist_recall_dossier_json_path if watchlist_recall_dossier_analysis else None,
            candidate_pool_recall_dossier_path=candidate_pool_recall_dossier_json_path if candidate_pool_recall_dossier_analysis else None,
        )
        rollout_governance_json_path.write_text(json.dumps(rollout_governance_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rollout_governance_md_path.write_text(render_btst_candidate_entry_rollout_governance_markdown(rollout_governance_analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "missing_inputs": [],
            "window_report_count": len(report_dirs),
            "error": str(exc),
        }

    return {
        "status": "refreshed",
        "missing_inputs": [],
        "window_report_count": len(report_dirs),
        "filtered_report_count": window_scan_analysis.get("filtered_report_count"),
        "focus_hit_report_count": window_scan_analysis.get("focus_hit_report_count"),
        "preserve_misfire_report_count": window_scan_analysis.get("preserve_misfire_report_count"),
        "rollout_readiness": window_scan_analysis.get("rollout_readiness"),
        "lane_status": rollout_governance_analysis.get("lane_status"),
        "no_candidate_entry_action_board_status": no_candidate_entry_action_board_status,
        "no_candidate_entry_priority_queue_count": no_candidate_entry_action_board_analysis.get("priority_queue_count"),
        "no_candidate_entry_top_tickers": no_candidate_entry_action_board_analysis.get("top_priority_tickers"),
        "no_candidate_entry_hotspot_report_dirs": no_candidate_entry_action_board_analysis.get("top_hotspot_report_dirs"),
        "no_candidate_entry_action_board_json": no_candidate_entry_action_board_json_path.as_posix() if no_candidate_entry_action_board_analysis else None,
        "no_candidate_entry_replay_bundle_status": no_candidate_entry_replay_bundle_status,
        "no_candidate_entry_replay_bundle_json": no_candidate_entry_replay_bundle_json_path.as_posix() if no_candidate_entry_replay_bundle_analysis else None,
        "no_candidate_entry_promising_tickers": no_candidate_entry_replay_bundle_analysis.get("promising_priority_tickers"),
        "no_candidate_entry_failure_dossier_status": no_candidate_entry_failure_dossier_status,
        "no_candidate_entry_failure_dossier_json": no_candidate_entry_failure_dossier_json_path.as_posix() if no_candidate_entry_failure_dossier_analysis else None,
        "no_candidate_entry_upstream_absence_tickers": no_candidate_entry_failure_dossier_analysis.get("top_upstream_absence_tickers"),
        "no_candidate_entry_semantic_miss_tickers": no_candidate_entry_failure_dossier_analysis.get("top_candidate_entry_semantic_miss_tickers"),
        "watchlist_recall_dossier_status": watchlist_recall_dossier_status,
        "watchlist_recall_dossier_json": watchlist_recall_dossier_json_path.as_posix() if watchlist_recall_dossier_analysis else None,
        "watchlist_recall_stage_counts": watchlist_recall_dossier_analysis.get("priority_recall_stage_counts"),
        "watchlist_recall_absent_from_candidate_pool_tickers": watchlist_recall_dossier_analysis.get("top_absent_from_candidate_pool_tickers"),
        "watchlist_recall_candidate_pool_layer_b_gap_tickers": watchlist_recall_dossier_analysis.get("top_candidate_pool_visible_but_missing_layer_b_tickers"),
        "watchlist_recall_layer_b_watchlist_gap_tickers": watchlist_recall_dossier_analysis.get("top_layer_b_visible_but_missing_watchlist_tickers"),
        "watchlist_recall_action_queue_task_ids": [
            str(row.get("task_id") or "")
            for row in list(watchlist_recall_dossier_analysis.get("action_queue") or [])[:3]
            if str(row.get("task_id") or "").strip()
        ],
        "candidate_pool_recall_dossier_status": candidate_pool_recall_dossier_status,
        "candidate_pool_recall_dossier_json": candidate_pool_recall_dossier_json_path.as_posix() if candidate_pool_recall_dossier_analysis else None,
        "candidate_pool_recall_stage_counts": candidate_pool_recall_dossier_analysis.get("priority_stage_counts"),
        "candidate_pool_recall_dominant_stage": candidate_pool_recall_dossier_analysis.get("dominant_stage"),
        "candidate_pool_recall_top_stage_tickers": candidate_pool_recall_dossier_analysis.get("top_stage_tickers"),
        "candidate_pool_recall_truncation_frontier_summary": candidate_pool_recall_dossier_analysis.get("truncation_frontier_summary"),
        "candidate_pool_recall_dominant_liquidity_gap_mode": dict(candidate_pool_recall_dossier_analysis.get("truncation_frontier_summary") or {}).get("dominant_liquidity_gap_mode"),
        "candidate_pool_recall_focus_liquidity_profiles": list(dict(candidate_pool_recall_dossier_analysis.get("focus_liquidity_profile_summary") or {}).get("primary_focus_tickers") or [])[:3],
        "candidate_pool_recall_priority_handoff_counts": dict(dict(candidate_pool_recall_dossier_analysis.get("focus_liquidity_profile_summary") or {}).get("priority_handoff_counts") or {}),
        "candidate_pool_recall_priority_handoff_branch_diagnoses": list(candidate_pool_recall_dossier_analysis.get("priority_handoff_branch_diagnoses") or [])[:3],
        "candidate_pool_recall_priority_handoff_branch_mechanisms": list(candidate_pool_recall_dossier_analysis.get("priority_handoff_branch_mechanisms") or [])[:3],
        "candidate_pool_recall_priority_handoff_branch_experiment_queue": list(candidate_pool_recall_dossier_analysis.get("priority_handoff_branch_experiment_queue") or [])[:3],
        "candidate_pool_branch_priority_board_status": candidate_pool_branch_priority_board_status,
        "candidate_pool_branch_priority_board_json": candidate_pool_branch_priority_board_json_path.as_posix() if candidate_pool_branch_priority_board_analysis else None,
        "candidate_pool_branch_priority_board_rows": list(candidate_pool_branch_priority_board_analysis.get("branch_rows") or [])[:3],
        "candidate_pool_branch_priority_alignment_status": candidate_pool_branch_priority_board_analysis.get("priority_alignment_status"),
        "candidate_pool_branch_priority_alignment_summary": candidate_pool_branch_priority_board_analysis.get("alignment_summary"),
        "candidate_pool_corridor_validation_pack_status": candidate_pool_corridor_validation_pack_status,
        "candidate_pool_corridor_validation_pack_json": candidate_pool_corridor_validation_pack_json_path.as_posix() if candidate_pool_corridor_validation_pack_analysis else None,
            "candidate_pool_corridor_validation_pack_summary": {
                "pack_status": candidate_pool_corridor_validation_pack_analysis.get("pack_status"),
                "focus_ticker": candidate_pool_corridor_validation_pack_analysis.get("focus_ticker"),
                "primary_validation_ticker": dict(candidate_pool_corridor_validation_pack_analysis.get("primary_validation_ticker") or {}).get("ticker"),
                "leader_gap_to_target": candidate_pool_corridor_validation_pack_analysis.get("leader_gap_to_target"),
                "promotion_readiness_status": candidate_pool_corridor_validation_pack_analysis.get("promotion_readiness_status"),
                "parallel_watch_tickers": [str(row.get("ticker") or "") for row in list(candidate_pool_corridor_validation_pack_analysis.get("parallel_watch_tickers") or [])[:3] if str(row.get("ticker") or "").strip()],
            },
        "candidate_pool_corridor_shadow_pack_status": candidate_pool_corridor_shadow_pack_status,
        "candidate_pool_corridor_shadow_pack_json": candidate_pool_corridor_shadow_pack_json_path.as_posix() if candidate_pool_corridor_shadow_pack_analysis else None,
        "candidate_pool_corridor_shadow_pack_summary": {
            "shadow_status": candidate_pool_corridor_shadow_pack_analysis.get("shadow_status"),
            "primary_shadow_replay": dict(candidate_pool_corridor_shadow_pack_analysis.get("primary_shadow_replay") or {}).get("ticker"),
            "parallel_watch_tickers": [str(row.get("ticker") or "") for row in list(candidate_pool_corridor_shadow_pack_analysis.get("parallel_watch_lanes") or [])[:3] if str(row.get("ticker") or "").strip()],
        },
        "candidate_pool_lane_objective_support_status": candidate_pool_lane_objective_support_status,
        "candidate_pool_lane_objective_support_json": candidate_pool_lane_objective_support_json_path.as_posix() if candidate_pool_lane_objective_support_analysis else None,
        "candidate_pool_lane_objective_support_rows": list(candidate_pool_lane_objective_support_analysis.get("branch_rows") or [])[:3],
        "candidate_pool_rebucket_shadow_pack_status": candidate_pool_rebucket_shadow_pack_status,
        "candidate_pool_rebucket_shadow_pack_json": candidate_pool_rebucket_shadow_pack_json_path.as_posix() if candidate_pool_rebucket_shadow_pack_analysis else None,
        "candidate_pool_rebucket_shadow_pack_experiment": dict(candidate_pool_rebucket_shadow_pack_analysis.get("experiment") or {}),
        "candidate_pool_rebucket_objective_validation_status": candidate_pool_rebucket_objective_validation_status,
        "candidate_pool_rebucket_objective_validation_json": candidate_pool_rebucket_objective_validation_json_path.as_posix() if candidate_pool_rebucket_objective_validation_analysis else None,
        "candidate_pool_rebucket_objective_validation_summary": {
            "validation_status": candidate_pool_rebucket_objective_validation_analysis.get("validation_status"),
            "support_verdict": dict(candidate_pool_rebucket_objective_validation_analysis.get("branch_objective_row") or {}).get("support_verdict"),
            "mean_t_plus_2_return": dict(candidate_pool_rebucket_objective_validation_analysis.get("branch_objective_row") or {}).get("mean_t_plus_2_return"),
        },
        "candidate_pool_rebucket_comparison_bundle_status": candidate_pool_rebucket_comparison_bundle_status,
        "candidate_pool_rebucket_comparison_bundle_json": candidate_pool_rebucket_comparison_bundle_json_path.as_posix() if candidate_pool_rebucket_comparison_bundle_analysis else None,
            "candidate_pool_rebucket_comparison_bundle_summary": {
                "bundle_status": candidate_pool_rebucket_comparison_bundle_analysis.get("bundle_status"),
                "structural_leader": dict(candidate_pool_rebucket_comparison_bundle_analysis.get("structural_leader") or {}).get("priority_handoff"),
                "objective_leader": dict(candidate_pool_rebucket_comparison_bundle_analysis.get("objective_leader") or {}).get("priority_handoff"),
                "rebucket_ticker": dict(candidate_pool_rebucket_comparison_bundle_analysis.get("rebucket_objective_row") or {}).get("ticker")
                or (list(dict(candidate_pool_rebucket_comparison_bundle_analysis.get("rebucket_objective_row") or {}).get("tickers") or [])[:1] or [None])[0],
                "objective_fit_gap_vs_corridor": dict(candidate_pool_rebucket_comparison_bundle_analysis.get("comparison") or {}).get("objective_fit_gap_vs_corridor"),
                "mean_t_plus_2_return_gap_vs_corridor": dict(candidate_pool_rebucket_comparison_bundle_analysis.get("comparison") or {}).get("mean_t_plus_2_return_gap_vs_corridor"),
            },
        "candidate_pool_lane_pair_board_status": candidate_pool_lane_pair_board_status,
        "candidate_pool_lane_pair_board_json": candidate_pool_lane_pair_board_json_path.as_posix() if candidate_pool_lane_pair_board_analysis else None,
        "candidate_pool_lane_pair_board_summary": {
            "pair_status": candidate_pool_lane_pair_board_analysis.get("pair_status"),
            "board_leader": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("ticker"),
            "leader_lane_family": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("lane_family"),
            "leader_governance_status": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("governance_status"),
            "leader_governance_blocker": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("governance_blocker"),
            "leader_governance_execution_quality": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("governance_execution_quality_label"),
            "leader_governance_entry_timing_bias": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("governance_entry_timing_bias"),
            "leader_current_decision": dict(candidate_pool_lane_pair_board_analysis.get("board_leader") or {}).get("current_decision"),
            "parallel_watch_ticker": next(
                (row.get("ticker") for row in list(candidate_pool_lane_pair_board_analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"),
                None,
            ),
            "parallel_watch_governance_blocker": next(
                (row.get("governance_blocker") for row in list(candidate_pool_lane_pair_board_analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"),
                None,
            ),
            "parallel_watch_same_source_sample_count": next(
                (row.get("governance_same_source_sample_count") for row in list(candidate_pool_lane_pair_board_analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"),
                None,
            ),
            "parallel_watch_next_close_positive_rate": next(
                (row.get("governance_same_source_next_close_positive_rate") for row in list(candidate_pool_lane_pair_board_analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"),
                None,
            ),
            "parallel_watch_next_close_return_mean": next(
                (row.get("governance_same_source_next_close_return_mean") for row in list(candidate_pool_lane_pair_board_analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"),
                None,
            ),
        },
        "candidate_pool_upstream_handoff_board_status": candidate_pool_upstream_handoff_board_status,
        "candidate_pool_upstream_handoff_board_json": candidate_pool_upstream_handoff_board_json_path.as_posix() if candidate_pool_upstream_handoff_board_analysis else None,
        "candidate_pool_upstream_handoff_board_summary": {
            "board_status": candidate_pool_upstream_handoff_board_analysis.get("board_status"),
            "focus_tickers": list(candidate_pool_upstream_handoff_board_analysis.get("focus_tickers") or [])[:3],
            "first_broken_handoff_counts": dict(dict(candidate_pool_upstream_handoff_board_analysis.get("stage_summary") or {}).get("first_broken_handoff_counts") or {}),
            "historical_shadow_probe_tickers": [
                str(row.get("ticker") or "")
                for row in list(candidate_pool_upstream_handoff_board_analysis.get("board_rows") or [])
                if str(row.get("board_phase") or "") == "historical_shadow_probe_gap" and str(row.get("ticker") or "").strip()
            ][:3],
        },
        "candidate_pool_corridor_uplift_runbook_status": candidate_pool_corridor_uplift_runbook_status,
        "candidate_pool_corridor_uplift_runbook_json": candidate_pool_corridor_uplift_runbook_json_path.as_posix() if candidate_pool_corridor_uplift_runbook_analysis else None,
        "candidate_pool_corridor_uplift_runbook_summary": {
            "runbook_status": candidate_pool_corridor_uplift_runbook_analysis.get("runbook_status"),
            "primary_shadow_replay": candidate_pool_corridor_uplift_runbook_analysis.get("primary_shadow_replay"),
            "parallel_watch_tickers": list(candidate_pool_corridor_uplift_runbook_analysis.get("parallel_watch_tickers") or [])[:3],
            "excluded_low_gate_tail_tickers": list(candidate_pool_corridor_uplift_runbook_analysis.get("excluded_low_gate_tail_tickers") or [])[:3],
            "prototype_type": candidate_pool_corridor_uplift_runbook_analysis.get("prototype_type"),
            "next_step": candidate_pool_corridor_uplift_runbook_analysis.get("next_step"),
            "execution_step_head": next(iter(list(candidate_pool_corridor_uplift_runbook_analysis.get("execution_steps") or [])), None),
            "execution_command_head": next(iter(list(candidate_pool_corridor_uplift_runbook_analysis.get("execution_commands") or [])), None),
            "guardrail_head": next(iter(list(candidate_pool_corridor_uplift_runbook_analysis.get("guardrails") or [])), None),
        },
        "continuation_focus_summary": _build_continuation_focus_summary(resolved_reports_root),
        "selected_outcome_refresh_summary": _build_selected_outcome_refresh_summary(resolved_reports_root),
        "carryover_multiday_continuation_audit_summary": _build_carryover_multiday_continuation_audit_summary(resolved_reports_root),
        "carryover_aligned_peer_harvest_summary": _build_carryover_aligned_peer_harvest_summary(resolved_reports_root),
        "carryover_peer_expansion_summary": _build_carryover_peer_expansion_summary(resolved_reports_root),
        "carryover_aligned_peer_proof_summary": _build_carryover_aligned_peer_proof_summary(resolved_reports_root),
        "carryover_peer_promotion_gate_summary": _build_carryover_peer_promotion_gate_summary(resolved_reports_root),
        "continuation_promotion_ready_summary": _build_continuation_promotion_ready_summary(resolved_reports_root),
        "default_merge_review_summary": _build_default_merge_review_summary(resolved_reports_root),
        "default_merge_historical_counterfactual_summary": _build_default_merge_historical_counterfactual_summary(resolved_reports_root),
        "continuation_merge_candidate_ranking_summary": _build_continuation_merge_candidate_ranking_summary(resolved_reports_root),
        "default_merge_strict_counterfactual_summary": _build_default_merge_strict_counterfactual_summary(resolved_reports_root),
        "merge_replay_validation_summary": _build_merge_replay_validation_summary(resolved_reports_root),
        "prepared_breakout_relief_validation_summary": _build_prepared_breakout_relief_validation_summary(resolved_reports_root),
        "prepared_breakout_cohort_summary": _build_prepared_breakout_cohort_summary(resolved_reports_root),
        "prepared_breakout_residual_surface_summary": _build_prepared_breakout_residual_surface_summary(resolved_reports_root),
        "candidate_pool_corridor_persistence_dossier_summary": _build_candidate_pool_corridor_persistence_dossier_summary(resolved_reports_root),
        "candidate_pool_corridor_window_command_board_summary": _build_candidate_pool_corridor_window_command_board_summary(resolved_reports_root),
        "candidate_pool_corridor_window_diagnostics_summary": _build_candidate_pool_corridor_window_diagnostics_summary(resolved_reports_root),
        "candidate_pool_corridor_narrow_probe_summary": _build_candidate_pool_corridor_narrow_probe_summary(resolved_reports_root),
        "transient_probe_summary": _build_transient_probe_summary(resolved_reports_root),
        "execution_constraint_rollup": _build_execution_constraint_rollup(resolved_reports_root),
        "candidate_pool_recall_action_queue_task_ids": [
            str(row.get("task_id") or "")
            for row in list(candidate_pool_recall_dossier_analysis.get("action_queue") or [])[:3]
            if str(row.get("task_id") or "").strip()
        ],
        "window_scan_json": window_scan_json_path.as_posix(),
        "rollout_governance_json": rollout_governance_json_path.as_posix(),
    }


def refresh_btst_window_evidence_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    report_dirs = [path for path in _discover_report_dirs(resolved_reports_root) if "paper_trading_window" in path.name]
    if not report_dirs:
        return {
            "status": "skipped_no_window_reports",
            "window_report_count": 0,
        }

    candidate_json_path = resolved_reports_root / MULTI_WINDOW_ROLE_CANDIDATES_LATEST_JSON
    candidate_md_path = resolved_reports_root / MULTI_WINDOW_ROLE_CANDIDATES_LATEST_MD
    try:
        candidate_analysis = analyze_multi_window_short_trade_role_candidates(
            report_dirs,
            min_short_trade_trade_dates=2,
        )
        _write_json(candidate_json_path, candidate_analysis)
        _write_markdown(candidate_md_path, render_multi_window_short_trade_role_candidates_markdown(candidate_analysis))
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "window_report_count": len(report_dirs),
            "error": str(exc),
        }

    refresh: dict[str, Any] = {
        "status": "refreshed",
        "window_report_count": len(report_dirs),
        "candidate_count": candidate_analysis.get("candidate_count"),
        "stable_candidate_count": candidate_analysis.get("stable_candidate_count"),
        "candidate_report_json": candidate_json_path.as_posix(),
        "candidate_report_markdown": candidate_md_path.as_posix(),
        "primary_refresh_status": "skipped_missing_execution_summary",
        "primary_window_gap_status": "skipped_missing_primary_roll_forward",
        "primary_window_validation_status": "skipped_missing_primary_window_gap",
    }

    execution_summary_path = resolved_reports_root / "p2_top3_experiment_execution_summary_20260330.json"
    if not execution_summary_path.exists():
        return refresh

    primary_roll_forward_json_path = resolved_reports_root / PRIMARY_ROLL_FORWARD_JSON
    primary_roll_forward_md_path = resolved_reports_root / PRIMARY_ROLL_FORWARD_MD
    try:
        primary_analysis = analyze_btst_primary_roll_forward(
            execution_summary_path,
            candidate_report_path=candidate_json_path,
            ticker="001309",
        )
        _write_json(primary_roll_forward_json_path, primary_analysis)
        _write_markdown(primary_roll_forward_md_path, render_btst_primary_roll_forward_markdown(primary_analysis))
        refresh["primary_refresh_status"] = "refreshed"
        refresh["primary_roll_forward_verdict"] = primary_analysis.get("roll_forward_verdict")
        refresh["primary_distinct_window_count"] = primary_analysis.get("distinct_window_count")
    except Exception as exc:
        refresh["primary_refresh_status"] = "skipped_refresh_error"
        refresh["primary_refresh_error"] = str(exc)
        return refresh

    primary_window_gap_json_path = resolved_reports_root / PRIMARY_WINDOW_GAP_JSON
    primary_window_gap_md_path = resolved_reports_root / PRIMARY_WINDOW_GAP_MD
    try:
        primary_gap_analysis = analyze_btst_primary_window_gap(
            primary_roll_forward_json_path,
            candidate_report_path=candidate_json_path,
            ticker="001309",
        )
        _write_json(primary_window_gap_json_path, primary_gap_analysis)
        _write_markdown(primary_window_gap_md_path, render_btst_primary_window_gap_markdown(primary_gap_analysis))
        refresh["primary_window_gap_status"] = "refreshed"
        refresh["primary_missing_window_count"] = primary_gap_analysis.get("missing_window_count")
    except Exception as exc:
        refresh["primary_window_gap_status"] = "skipped_refresh_error"
        refresh["primary_window_gap_error"] = str(exc)
        return refresh

    primary_window_validation_json_path = resolved_reports_root / PRIMARY_WINDOW_VALIDATION_RUNBOOK_JSON
    primary_window_validation_md_path = resolved_reports_root / PRIMARY_WINDOW_VALIDATION_RUNBOOK_MD
    try:
        primary_validation_analysis = analyze_btst_primary_window_validation_runbook(
            candidate_json_path,
            primary_roll_forward_path=primary_roll_forward_json_path,
            primary_window_gap_path=primary_window_gap_json_path,
            ticker="001309",
        )
        _write_json(primary_window_validation_json_path, primary_validation_analysis)
        _write_markdown(primary_window_validation_md_path, render_btst_primary_window_validation_runbook_markdown(primary_validation_analysis))
        refresh["primary_window_validation_status"] = "refreshed"
        refresh["primary_validation_verdict"] = primary_validation_analysis.get("validation_verdict")
    except Exception as exc:
        refresh["primary_window_validation_status"] = "skipped_refresh_error"
        refresh["primary_window_validation_error"] = str(exc)

    return refresh


def refresh_btst_score_fail_frontier_artifacts(
    reports_root: str | Path,
    *,
    latest_btst_run: dict[str, Any] | None = None,
    window_evidence_refresh: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    if not latest_btst_run:
        return {
            "status": "skipped_no_latest_btst_run",
        }

    report_dir_value = latest_btst_run.get("report_dir")
    report_dir = Path(report_dir_value).expanduser().resolve() if report_dir_value else None
    if report_dir is None or not report_dir.exists():
        return {
            "status": "skipped_missing_latest_report_dir",
        }

    analysis_json_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_SCORE_FAILURES_LATEST_JSON
    analysis_md_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_SCORE_FAILURES_LATEST_MD
    frontier_json_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_SCORE_FAILURES_FRONTIER_LATEST_JSON
    frontier_md_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_SCORE_FAILURES_FRONTIER_LATEST_MD
    recurring_json_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_RECURRING_FRONTIER_LATEST_JSON
    recurring_md_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_RECURRING_FRONTIER_LATEST_MD

    try:
        score_fail_analysis = analyze_short_trade_boundary_score_failures(report_dir)
        score_fail_frontier_analysis = analyze_short_trade_boundary_score_failures_frontier(report_dir)
        recurring_frontier_analysis = analyze_short_trade_boundary_recurring_frontier_cases(report_dir)
        _write_json(analysis_json_path, score_fail_analysis)
        _write_markdown(analysis_md_path, render_short_trade_boundary_score_failure_markdown(score_fail_analysis))
        _write_json(frontier_json_path, score_fail_frontier_analysis)
        _write_markdown(frontier_md_path, render_short_trade_boundary_score_failure_frontier_markdown(score_fail_frontier_analysis))
        _write_json(recurring_json_path, recurring_frontier_analysis)
        _write_markdown(recurring_md_path, render_short_trade_boundary_recurring_frontier_markdown(recurring_frontier_analysis))
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "report_dir": report_dir.name,
            "error": str(exc),
        }

    refresh: dict[str, Any] = {
        "status": "refreshed",
        "report_dir": report_dir.name,
        "rejected_short_trade_boundary_count": score_fail_analysis.get("rejected_short_trade_boundary_count"),
        "rescueable_case_count": score_fail_frontier_analysis.get("rescueable_case_count"),
        "threshold_only_rescue_count": score_fail_frontier_analysis.get("rescueable_with_threshold_only_count"),
        "recurring_case_count": recurring_frontier_analysis.get("recurring_case_count"),
        "priority_queue_tickers": [
            str(row.get("ticker") or "")
            for row in list(recurring_frontier_analysis.get("priority_queue") or [])[:3]
            if row.get("ticker")
        ],
        "top_rescue_tickers": [
            str(row.get("ticker") or "")
            for row in list(score_fail_frontier_analysis.get("minimal_near_miss_rows") or [])[:3]
            if row.get("ticker")
        ],
        "analysis_json": analysis_json_path.as_posix(),
        "analysis_markdown": analysis_md_path.as_posix(),
        "frontier_json": frontier_json_path.as_posix(),
        "frontier_markdown": frontier_md_path.as_posix(),
        "recurring_json": recurring_json_path.as_posix(),
        "recurring_markdown": recurring_md_path.as_posix(),
        "transition_refresh_status": "skipped_no_window_reports",
        "recurring_shadow_refresh_status": "skipped_missing_inputs",
    }

    report_dirs = [path for path in _discover_report_dirs(resolved_reports_root) if "paper_trading_window" in path.name]
    recurring_transition_json_path = resolved_reports_root / RECURRING_FRONTIER_TRANSITION_LATEST_JSON
    recurring_transition_md_path = resolved_reports_root / RECURRING_FRONTIER_TRANSITION_LATEST_MD
    if report_dirs:
        try:
            recurring_transition_analysis = analyze_recurring_frontier_transition_candidates(
                recurring_json_path,
                role_history_report_dirs=report_dirs,
            )
            _write_json(recurring_transition_json_path, recurring_transition_analysis)
            _write_markdown(recurring_transition_md_path, render_recurring_frontier_transition_candidates_markdown(recurring_transition_analysis))
            refresh["transition_refresh_status"] = "refreshed"
            refresh["transition_candidate_count"] = len(list(recurring_transition_analysis.get("candidates") or []))
            refresh["transition_json"] = recurring_transition_json_path.as_posix()
            refresh["transition_markdown"] = recurring_transition_md_path.as_posix()
        except Exception as exc:
            refresh["transition_refresh_status"] = "skipped_refresh_error"
            refresh["transition_refresh_error"] = str(exc)

    candidate_report_json = str((window_evidence_refresh or {}).get("candidate_report_json") or "")
    shadow_lane_priority_path = _resolve_existing_artifact_path(
        resolved_reports_root,
        SHADOW_LANE_PRIORITY_JSON,
        glob_pattern="p4_shadow_lane_priority_board_*.json",
    )
    recurring_pair_comparison_path = _resolve_existing_artifact_path(
        resolved_reports_root,
        RECURRING_PAIR_COMPARISON_JSON,
        glob_pattern="recurring_frontier_release_pair_comparison_*.json",
    )
    recurring_shadow_inputs = {
        "shadow_lane_priority": shadow_lane_priority_path,
        "recurring_pair_comparison": recurring_pair_comparison_path,
        "candidate_report": Path(candidate_report_json).expanduser().resolve() if candidate_report_json else None,
        "recurring_transition_report": recurring_transition_json_path if recurring_transition_json_path.exists() else None,
        "recurring_close_bundle": _resolve_existing_artifact_path(
            resolved_reports_root,
            RECURRING_CLOSE_BUNDLE_JSON,
            glob_pattern="btst_recurring_shadow_close_bundle_*.json",
        ),
    }
    missing_recurring_shadow_inputs = [
        label
        for label, path in recurring_shadow_inputs.items()
        if path is None or not Path(path).exists()
    ]
    if missing_recurring_shadow_inputs:
        refresh["recurring_shadow_refresh_status"] = "skipped_missing_inputs"
        refresh["missing_recurring_shadow_inputs"] = missing_recurring_shadow_inputs
        return refresh

    recurring_shadow_json_path = resolved_reports_root / RECURRING_SHADOW_RUNBOOK_JSON
    recurring_shadow_md_path = resolved_reports_root / RECURRING_SHADOW_RUNBOOK_MD
    try:
        recurring_shadow_analysis = analyze_btst_recurring_shadow_runbook(
            recurring_shadow_inputs["shadow_lane_priority"],
            recurring_pair_comparison_path=recurring_shadow_inputs["recurring_pair_comparison"],
            candidate_report_path=recurring_shadow_inputs["candidate_report"],
            recurring_transition_report_path=recurring_shadow_inputs["recurring_transition_report"],
            recurring_close_bundle_path=recurring_shadow_inputs["recurring_close_bundle"] if recurring_shadow_inputs["recurring_close_bundle"].exists() else None,
        )
        _write_json(recurring_shadow_json_path, recurring_shadow_analysis)
        _write_markdown(recurring_shadow_md_path, render_btst_recurring_shadow_runbook_markdown(recurring_shadow_analysis))
        refresh["recurring_shadow_refresh_status"] = "refreshed"
        refresh["recurring_shadow_global_validation_verdict"] = recurring_shadow_analysis.get("global_validation_verdict")
        refresh["recurring_shadow_close_candidate_status"] = dict(recurring_shadow_analysis.get("close_candidate") or {}).get("lane_status")
        refresh["recurring_shadow_intraday_control_status"] = dict(recurring_shadow_analysis.get("intraday_control") or {}).get("lane_status")
    except Exception as exc:
        refresh["recurring_shadow_refresh_status"] = "skipped_refresh_error"
        refresh["recurring_shadow_refresh_error"] = str(exc)

    return refresh


def refresh_btst_rollout_governance_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    required_inputs = {
        "action_board": _resolve_existing_artifact_path(resolved_reports_root, ACTION_BOARD_JSON, glob_pattern="p3_top3_post_execution_action_board_*.json"),
        "primary_roll_forward": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_ROLL_FORWARD_JSON, glob_pattern="p4_primary_roll_forward_validation_001309_*.json"),
        "shadow_expansion": _resolve_existing_artifact_path(resolved_reports_root, SHADOW_EXPANSION_JSON, glob_pattern="p4_shadow_entry_expansion_board_300383_*.json"),
        "shadow_lane_priority": _resolve_existing_artifact_path(resolved_reports_root, SHADOW_LANE_PRIORITY_JSON, glob_pattern="p4_shadow_lane_priority_board_*.json"),
        "primary_window_gap": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_GAP_JSON, glob_pattern="p6_primary_window_gap_001309_*.json"),
        "recurring_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, RECURRING_SHADOW_RUNBOOK_JSON, glob_pattern="p6_recurring_shadow_runbook_*.json"),
        "primary_window_validation_runbook": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_VALIDATION_RUNBOOK_JSON, glob_pattern="p7_primary_window_validation_runbook_001309_*.json"),
        "shadow_peer_scan": _resolve_existing_artifact_path(resolved_reports_root, SHADOW_PEER_SCAN_JSON, glob_pattern="p7_shadow_peer_scan_300383_*.json"),
        "structural_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, STRUCTURAL_SHADOW_RUNBOOK_JSON, glob_pattern="p8_structural_shadow_runbook_300724_*.json"),
        "recurring_close_bundle": _resolve_existing_artifact_path(resolved_reports_root, RECURRING_CLOSE_BUNDLE_JSON, glob_pattern="btst_recurring_shadow_close_bundle_*.json"),
    }
    missing_inputs = [label for label, path in required_inputs.items() if label != "recurring_close_bundle" and not path.exists()]
    if missing_inputs:
        return {
            "status": "skipped_missing_inputs",
            "missing_inputs": missing_inputs,
        }

    output_json_path = resolved_reports_root / ROLLOUT_GOVERNANCE_JSON
    output_md_path = resolved_reports_root / ROLLOUT_GOVERNANCE_MD
    penalty_frontier_path = resolved_reports_root / BTST_PENALTY_FRONTIER_JSON
    try:
        analysis = analyze_btst_rollout_governance_board(
            required_inputs["action_board"],
            primary_roll_forward_path=required_inputs["primary_roll_forward"],
            shadow_expansion_path=required_inputs["shadow_expansion"],
            shadow_lane_priority_path=required_inputs["shadow_lane_priority"],
            primary_window_gap_path=required_inputs["primary_window_gap"],
            recurring_shadow_runbook_path=required_inputs["recurring_shadow_runbook"],
            recurring_close_bundle_path=required_inputs["recurring_close_bundle"] if required_inputs["recurring_close_bundle"].exists() else None,
            primary_window_validation_runbook_path=required_inputs["primary_window_validation_runbook"],
            shadow_peer_scan_path=required_inputs["shadow_peer_scan"],
            structural_shadow_runbook_path=required_inputs["structural_shadow_runbook"],
            penalty_frontier_path=penalty_frontier_path if penalty_frontier_path.exists() else None,
        )
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_rollout_governance_board_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "missing_inputs": [],
            "error": str(exc),
        }

    penalty_frontier_summary = dict(analysis.get("penalty_frontier_summary") or {})
    return {
        "status": "refreshed",
        "missing_inputs": [],
        "governance_row_count": len(list(analysis.get("governance_rows") or [])),
        "next_task_count": len(list(analysis.get("next_3_tasks") or [])),
        "penalty_frontier_status": penalty_frontier_summary.get("status"),
        "penalty_frontier_passing_variant_count": penalty_frontier_summary.get("passing_variant_count"),
        "output_json": output_json_path.as_posix(),
    }


def refresh_btst_governance_synthesis_artifacts(
    reports_root: str | Path,
    *,
    latest_btst_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    required_inputs = {
        "action_board": _resolve_existing_artifact_path(resolved_reports_root, ACTION_BOARD_JSON, glob_pattern="p3_top3_post_execution_action_board_*.json"),
        "rollout_governance": _resolve_existing_artifact_path(resolved_reports_root, ROLLOUT_GOVERNANCE_JSON, glob_pattern="p5_btst_rollout_governance_board_*.json"),
        "primary_window_gap": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_GAP_JSON, glob_pattern="p6_primary_window_gap_001309_*.json"),
        "recurring_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, RECURRING_SHADOW_RUNBOOK_JSON, glob_pattern="p6_recurring_shadow_runbook_*.json"),
        "primary_window_validation_runbook": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_VALIDATION_RUNBOOK_JSON, glob_pattern="p7_primary_window_validation_runbook_001309_*.json"),
        "structural_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, STRUCTURAL_SHADOW_RUNBOOK_JSON, glob_pattern="p8_structural_shadow_runbook_300724_*.json"),
        "candidate_entry_governance": _resolve_existing_artifact_path(resolved_reports_root, CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_JSON, glob_pattern="p9_candidate_entry_rollout_governance_*.json"),
    }
    missing_inputs = [label for label, path in required_inputs.items() if not path.exists()]
    if missing_inputs:
        return {
            "status": "skipped_missing_inputs",
            "missing_inputs": missing_inputs,
        }

    output_json_path = resolved_reports_root / BTST_GOVERNANCE_SYNTHESIS_JSON
    output_md_path = resolved_reports_root / BTST_GOVERNANCE_SYNTHESIS_MD
    evidence_btst_report_dirs = _collect_governance_synthesis_evidence_dirs(resolved_reports_root, latest_btst_run=latest_btst_run)
    try:
        analysis = analyze_btst_governance_synthesis(
            resolved_reports_root,
            action_board_path=required_inputs["action_board"],
            rollout_governance_path=required_inputs["rollout_governance"],
            primary_window_gap_path=required_inputs["primary_window_gap"],
            recurring_shadow_runbook_path=required_inputs["recurring_shadow_runbook"],
            primary_window_validation_runbook_path=required_inputs["primary_window_validation_runbook"],
            structural_shadow_runbook_path=required_inputs["structural_shadow_runbook"],
            candidate_entry_governance_path=required_inputs["candidate_entry_governance"],
            latest_btst_report_dir=latest_btst_run.get("report_dir") if latest_btst_run else None,
            evidence_btst_report_dirs=evidence_btst_report_dirs or None,
        )
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_governance_synthesis_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "missing_inputs": [],
            "error": str(exc),
        }

    latest_followup = dict(analysis.get("latest_btst_followup") or {})
    return {
        "status": "refreshed",
        "missing_inputs": [],
        "ready_lane_count": analysis.get("ready_lane_count"),
        "waiting_lane_count": analysis.get("waiting_lane_count"),
        "latest_trade_date": latest_followup.get("trade_date"),
        "latest_selected_count": latest_followup.get("selected_count"),
        "evidence_btst_report_dir_count": len(evidence_btst_report_dirs),
        "output_json": output_json_path.as_posix(),
    }


def refresh_btst_governance_validation_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    required_inputs = {
        "action_board": _resolve_existing_artifact_path(resolved_reports_root, ACTION_BOARD_JSON, glob_pattern="p3_top3_post_execution_action_board_*.json"),
        "rollout_governance": _resolve_existing_artifact_path(resolved_reports_root, ROLLOUT_GOVERNANCE_JSON, glob_pattern="p5_btst_rollout_governance_board_*.json"),
        "primary_window_gap": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_GAP_JSON, glob_pattern="p6_primary_window_gap_001309_*.json"),
        "recurring_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, RECURRING_SHADOW_RUNBOOK_JSON, glob_pattern="p6_recurring_shadow_runbook_*.json"),
        "primary_window_validation_runbook": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_VALIDATION_RUNBOOK_JSON, glob_pattern="p7_primary_window_validation_runbook_001309_*.json"),
        "structural_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, STRUCTURAL_SHADOW_RUNBOOK_JSON, glob_pattern="p8_structural_shadow_runbook_300724_*.json"),
        "candidate_entry_governance": _resolve_existing_artifact_path(resolved_reports_root, CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_JSON, glob_pattern="p9_candidate_entry_rollout_governance_*.json"),
        "governance_synthesis": resolved_reports_root / BTST_GOVERNANCE_SYNTHESIS_JSON,
    }
    missing_inputs = [label for label, path in required_inputs.items() if not path.exists()]
    if missing_inputs:
        return {
            "status": "skipped_missing_inputs",
            "missing_inputs": missing_inputs,
        }

    output_json_path = resolved_reports_root / BTST_GOVERNANCE_VALIDATION_JSON
    output_md_path = resolved_reports_root / BTST_GOVERNANCE_VALIDATION_MD
    try:
        analysis = validate_btst_governance_consistency(
            action_board_path=required_inputs["action_board"],
            rollout_governance_path=required_inputs["rollout_governance"],
            primary_window_gap_path=required_inputs["primary_window_gap"],
            recurring_shadow_runbook_path=required_inputs["recurring_shadow_runbook"],
            primary_window_validation_runbook_path=required_inputs["primary_window_validation_runbook"],
            structural_shadow_runbook_path=required_inputs["structural_shadow_runbook"],
            candidate_entry_governance_path=required_inputs["candidate_entry_governance"],
            governance_synthesis_path=required_inputs["governance_synthesis"],
            nightly_control_tower_path=resolved_reports_root / "btst_nightly_control_tower_latest.json",
        )
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_governance_validation_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "missing_inputs": [],
            "error": str(exc),
        }

    return {
        "status": "refreshed",
        "missing_inputs": [],
        "overall_verdict": analysis.get("overall_verdict"),
        "pass_count": analysis.get("pass_count"),
        "warn_count": analysis.get("warn_count"),
        "fail_count": analysis.get("fail_count"),
        "output_json": output_json_path.as_posix(),
    }


def refresh_btst_replay_cohort_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    output_json_path = resolved_reports_root / BTST_REPLAY_COHORT_JSON
    output_md_path = resolved_reports_root / BTST_REPLAY_COHORT_MD
    try:
        analysis = analyze_btst_replay_cohort(resolved_reports_root)
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_replay_cohort_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "error": str(exc),
            "report_count": 0,
        }

    selection_target_counts = dict(analysis.get("selection_target_counts") or {})
    latest_short_trade = dict(analysis.get("latest_short_trade_row") or {})
    return {
        "status": "refreshed",
        "report_count": analysis.get("report_count"),
        "short_trade_only_report_count": selection_target_counts.get("short_trade_only"),
        "dual_target_report_count": selection_target_counts.get("dual_target"),
        "latest_short_trade_report": latest_short_trade.get("report_dir_name"),
        "output_json": output_json_path.as_posix(),
    }


def refresh_btst_independent_window_monitor_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    output_json_path = resolved_reports_root / BTST_INDEPENDENT_WINDOW_MONITOR_JSON
    output_md_path = resolved_reports_root / BTST_INDEPENDENT_WINDOW_MONITOR_MD
    try:
        analysis = analyze_btst_independent_window_monitor(resolved_reports_root)
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_independent_window_monitor_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "error": str(exc),
            "report_dir_count": 0,
        }

    return {
        "status": "refreshed",
        "report_dir_count": analysis.get("report_dir_count"),
        "ready_lane_count": analysis.get("ready_lane_count"),
        "waiting_lane_count": analysis.get("waiting_lane_count"),
        "no_evidence_lane_count": analysis.get("no_evidence_lane_count"),
        "output_json": output_json_path.as_posix(),
    }


def refresh_btst_tplus1_tplus2_objective_monitor_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    output_json_path = resolved_reports_root / BTST_TPLUS1_TPLUS2_OBJECTIVE_MONITOR_JSON
    output_md_path = resolved_reports_root / BTST_TPLUS1_TPLUS2_OBJECTIVE_MONITOR_MD
    try:
        analysis = analyze_btst_tplus1_tplus2_objective_monitor(resolved_reports_root)
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_tplus1_tplus2_objective_monitor_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "error": str(exc),
            "report_dir_count": 0,
        }

    tradeable_surface = dict(analysis.get("tradeable_surface") or {})
    ticker_leaderboard = list(analysis.get("ticker_leaderboard") or [])
    best_ticker_row = ticker_leaderboard[0] if ticker_leaderboard else {}
    return {
        "status": "refreshed",
        "report_dir_count": analysis.get("report_dir_count"),
        "closed_cycle_row_count": dict(analysis.get("all_surface") or {}).get("closed_cycle_count"),
        "tradeable_closed_cycle_count": tradeable_surface.get("closed_cycle_count"),
        "tradeable_positive_rate": tradeable_surface.get("t_plus_2_positive_rate"),
        "tradeable_return_hit_rate": tradeable_surface.get("t_plus_2_return_hit_rate_at_target"),
        "tradeable_mean_t_plus_2_return": tradeable_surface.get("mean_t_plus_2_return"),
        "tradeable_verdict": tradeable_surface.get("verdict"),
        "best_ticker": best_ticker_row.get("group_label"),
        "best_ticker_objective_fit_score": best_ticker_row.get("objective_fit_score"),
        "output_json": output_json_path.as_posix(),
    }


def refresh_btst_tradeable_opportunity_pool_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    output_json_path = resolved_reports_root / BTST_TRADEABLE_OPPORTUNITY_POOL_JSON
    output_md_path = resolved_reports_root / BTST_TRADEABLE_OPPORTUNITY_POOL_MD
    output_csv_path = resolved_reports_root / BTST_TRADEABLE_OPPORTUNITY_POOL_CSV
    waterfall_json_path = resolved_reports_root / BTST_TRADEABLE_OPPORTUNITY_WATERFALL_JSON
    waterfall_md_path = resolved_reports_root / BTST_TRADEABLE_OPPORTUNITY_WATERFALL_MD

    existing_analysis, existing_waterfall = load_btst_tradeable_opportunity_artifacts(
        resolved_reports_root,
        output_json=output_json_path,
        waterfall_json=waterfall_json_path,
    )
    if existing_analysis and existing_waterfall and int(existing_analysis.get("artifact_schema_version") or 0) >= 2:
        summary = summarize_btst_tradeable_opportunity_artifacts(existing_analysis, existing_waterfall)
        return {
            "status": "loaded_existing",
            "report_dir_count": len(_discover_report_dirs(resolved_reports_root)),
            "analysis_json": output_json_path.as_posix(),
            "analysis_markdown": output_md_path.as_posix(),
            "analysis_csv": output_csv_path.as_posix(),
            "waterfall_json": waterfall_json_path.as_posix(),
            "waterfall_markdown": waterfall_md_path.as_posix(),
            **summary,
        }

    report_dir_count = len(_discover_report_dirs(resolved_reports_root))
    if report_dir_count <= 0:
        return {
            "status": "skipped_no_reports",
            "report_dir_count": 0,
        }

    try:
        result = generate_btst_tradeable_opportunity_pool_artifacts(
            resolved_reports_root,
            start_date=TRADEABLE_OPPORTUNITY_POOL_START_DATE,
            end_date=TRADEABLE_OPPORTUNITY_POOL_END_DATE,
            output_json=output_json_path,
            output_md=output_md_path,
            output_csv=output_csv_path,
            waterfall_output_json=waterfall_json_path,
            waterfall_output_md=waterfall_md_path,
        )
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "report_dir_count": report_dir_count,
            "error": str(exc),
        }

    summary = summarize_btst_tradeable_opportunity_artifacts(result["analysis"], result["waterfall"])
    return {
        "status": "refreshed",
        "report_dir_count": report_dir_count,
        "analysis_json": result["json_path"],
        "analysis_markdown": result["markdown_path"],
        "analysis_csv": result["csv_path"],
        "waterfall_json": result["waterfall_json_path"],
        "waterfall_markdown": result["waterfall_markdown_path"],
        **summary,
    }


def generate_reports_manifest(
    reports_root: str | Path,
    *,
    latest_btst_run: dict[str, Any] | None = None,
    catalyst_theme_frontier_refresh: dict[str, Any] | None = None,
    btst_window_evidence_refresh: dict[str, Any] | None = None,
    candidate_entry_shadow_refresh: dict[str, Any] | None = None,
    btst_score_fail_frontier_refresh: dict[str, Any] | None = None,
    btst_rollout_governance_refresh: dict[str, Any] | None = None,
    btst_governance_synthesis_refresh: dict[str, Any] | None = None,
    btst_governance_validation_refresh: dict[str, Any] | None = None,
    btst_replay_cohort_refresh: dict[str, Any] | None = None,
    btst_independent_window_monitor_refresh: dict[str, Any] | None = None,
    btst_tplus1_tplus2_objective_monitor_refresh: dict[str, Any] | None = None,
    btst_tradeable_opportunity_pool_refresh: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    repo_root = _resolve_repo_root(resolved_reports_root)
    latest_btst_run = latest_btst_run or _select_latest_btst_candidate(resolved_reports_root, repo_root)

    entries = _build_static_entries(repo_root) + _build_dynamic_latest_btst_entries(latest_btst_run, repo_root)
    entries.sort(key=lambda entry: (entry["usage"], entry["priority"], entry["view_order"], entry["id"]))

    entry_ids = {entry["id"] for entry in entries}
    reading_paths: list[dict[str, Any]] = []
    for spec in READING_PATH_SPECS:
        resolved_entry_ids = [entry_id for entry_id in spec["entry_ids"] if entry_id in entry_ids]
        if not resolved_entry_ids:
            continue
        reading_paths.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "description": spec["description"],
                "entry_ids": resolved_entry_ids,
            }
        )

    entry_count_by_usage: dict[str, int] = {}
    for entry in entries:
        entry_count_by_usage[entry["usage"]] = entry_count_by_usage.get(entry["usage"], 0) + 1

    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repo_root": repo_root.as_posix(),
        "reports_root": resolved_reports_root.as_posix(),
        "entry_count": len(entries),
        "entry_count_by_usage": entry_count_by_usage,
        "catalyst_theme_frontier_refresh": catalyst_theme_frontier_refresh,
        "btst_window_evidence_refresh": btst_window_evidence_refresh,
        "candidate_entry_shadow_refresh": candidate_entry_shadow_refresh,
        "btst_score_fail_frontier_refresh": btst_score_fail_frontier_refresh,
        "btst_rollout_governance_refresh": btst_rollout_governance_refresh,
        "btst_governance_synthesis_refresh": btst_governance_synthesis_refresh,
        "btst_governance_validation_refresh": btst_governance_validation_refresh,
        "btst_replay_cohort_refresh": btst_replay_cohort_refresh,
        "btst_independent_window_monitor_refresh": btst_independent_window_monitor_refresh,
        "btst_tplus1_tplus2_objective_monitor_refresh": btst_tplus1_tplus2_objective_monitor_refresh,
        "btst_tradeable_opportunity_pool_refresh": btst_tradeable_opportunity_pool_refresh,
        "continuation_focus_summary": _build_continuation_focus_summary(resolved_reports_root),
        "selected_outcome_refresh_summary": _build_selected_outcome_refresh_summary(resolved_reports_root),
        "carryover_multiday_continuation_audit_summary": _build_carryover_multiday_continuation_audit_summary(resolved_reports_root),
        "carryover_aligned_peer_harvest_summary": _build_carryover_aligned_peer_harvest_summary(resolved_reports_root),
        "carryover_peer_expansion_summary": _build_carryover_peer_expansion_summary(resolved_reports_root),
        "carryover_aligned_peer_proof_summary": _build_carryover_aligned_peer_proof_summary(resolved_reports_root),
        "carryover_peer_promotion_gate_summary": _build_carryover_peer_promotion_gate_summary(resolved_reports_root),
        "continuation_promotion_ready_summary": _build_continuation_promotion_ready_summary(resolved_reports_root),
        "default_merge_review_summary": _build_default_merge_review_summary(resolved_reports_root),
        "default_merge_historical_counterfactual_summary": _build_default_merge_historical_counterfactual_summary(resolved_reports_root),
        "continuation_merge_candidate_ranking_summary": _build_continuation_merge_candidate_ranking_summary(resolved_reports_root),
        "default_merge_strict_counterfactual_summary": _build_default_merge_strict_counterfactual_summary(resolved_reports_root),
        "merge_replay_validation_summary": _build_merge_replay_validation_summary(resolved_reports_root),
        "prepared_breakout_relief_validation_summary": _build_prepared_breakout_relief_validation_summary(resolved_reports_root),
        "prepared_breakout_cohort_summary": _build_prepared_breakout_cohort_summary(resolved_reports_root),
        "prepared_breakout_residual_surface_summary": _build_prepared_breakout_residual_surface_summary(resolved_reports_root),
        "candidate_pool_corridor_persistence_dossier_summary": _build_candidate_pool_corridor_persistence_dossier_summary(resolved_reports_root),
        "candidate_pool_corridor_window_command_board_summary": _build_candidate_pool_corridor_window_command_board_summary(resolved_reports_root),
        "candidate_pool_corridor_window_diagnostics_summary": _build_candidate_pool_corridor_window_diagnostics_summary(resolved_reports_root),
        "candidate_pool_corridor_narrow_probe_summary": _build_candidate_pool_corridor_narrow_probe_summary(resolved_reports_root),
        "transient_probe_summary": _build_transient_probe_summary(resolved_reports_root),
        "execution_constraint_rollup": _build_execution_constraint_rollup(resolved_reports_root),
        "latest_btst_run": None,
        "reading_paths": reading_paths,
        "entries": entries,
    }
    if latest_btst_run:
        manifest["latest_btst_run"] = {
            "report_dir": latest_btst_run["report_dir_path"],
            "report_dir_abs": latest_btst_run["report_dir"].as_posix(),
            "selection_target": latest_btst_run.get("selection_target"),
            "trade_date": latest_btst_run.get("trade_date"),
            "next_trade_date": latest_btst_run.get("next_trade_date"),
        }
    return manifest


def _build_markdown_link(entry: dict[str, Any], output_parent: Path) -> str:
    relative_target = Path(os.path.relpath(entry["absolute_path"], output_parent)).as_posix()
    return f"[{entry['report_path']}]({relative_target})"


def _append_markdown_field_lines(
    lines: list[str],
    *,
    payload: dict[str, Any],
    field_specs: list[tuple[str, str, str]],
) -> None:
    for label, key, mode in field_specs:
        value = payload.get(key)
        if mode == "not_none" and value is None:
            continue
        if mode == "truthy" and not value:
            continue
        lines.append(f"- {label}: {value}")


def _append_manifest_header(lines: list[str], manifest: dict[str, Any]) -> None:
    lines.append("# Reports Manifest Latest")
    lines.append("")
    lines.append(f"- generated_at: {manifest['generated_at']}")
    lines.append(f"- entry_count: {manifest['entry_count']}")
    lines.append(f"- reports_root: {manifest['reports_root']}")
    for refresh_key, field_specs in (
        (
            "catalyst_theme_frontier_refresh",
            [
                ("catalyst_theme_frontier_refresh_status", "status", "always"),
                ("catalyst_theme_frontier_shadow_candidate_count", "shadow_candidate_count", "always"),
                ("catalyst_theme_frontier_promoted_shadow_count", "recommended_promoted_shadow_count", "always"),
                ("catalyst_theme_frontier_recommended_variant", "recommended_variant_name", "always"),
            ],
        ),
        (
            "btst_window_evidence_refresh",
            [
                ("btst_window_evidence_refresh_status", "status", "always"),
                ("btst_window_evidence_window_report_count", "window_report_count", "always"),
                ("btst_window_evidence_candidate_count", "candidate_count", "always"),
                ("btst_window_evidence_stable_candidate_count", "stable_candidate_count", "always"),
                ("btst_window_evidence_primary_refresh_status", "primary_refresh_status", "always"),
                ("btst_window_evidence_primary_missing_window_count", "primary_missing_window_count", "always"),
            ],
        ),
    ):
        payload = dict(manifest.get(refresh_key) or {})
        if payload:
            _append_markdown_field_lines(lines, payload=payload, field_specs=field_specs)


def _append_candidate_entry_shadow_refresh(lines: list[str], payload: dict[str, Any]) -> None:
    if not payload:
        return
    _append_markdown_field_lines(
        lines,
        payload=payload,
        field_specs=[
            ("candidate_entry_shadow_refresh_status", "status", "always"),
            ("candidate_entry_shadow_refresh_window_reports", "window_report_count", "always"),
            ("candidate_entry_shadow_refresh_filtered_reports", "filtered_report_count", "always"),
            ("candidate_entry_shadow_refresh_rollout_readiness", "rollout_readiness", "always"),
            ("candidate_entry_shadow_no_candidate_entry_action_board_status", "no_candidate_entry_action_board_status", "not_none"),
            ("candidate_entry_shadow_no_candidate_entry_priority_queue_count", "no_candidate_entry_priority_queue_count", "not_none"),
            ("candidate_entry_shadow_no_candidate_entry_top_tickers", "no_candidate_entry_top_tickers", "not_none"),
            ("candidate_entry_shadow_no_candidate_entry_replay_bundle_status", "no_candidate_entry_replay_bundle_status", "not_none"),
            ("candidate_entry_shadow_no_candidate_entry_promising_tickers", "no_candidate_entry_promising_tickers", "not_none"),
            ("candidate_entry_shadow_no_candidate_entry_failure_dossier_status", "no_candidate_entry_failure_dossier_status", "not_none"),
            ("candidate_entry_shadow_no_candidate_entry_upstream_absence_tickers", "no_candidate_entry_upstream_absence_tickers", "not_none"),
            ("candidate_entry_shadow_no_candidate_entry_semantic_miss_tickers", "no_candidate_entry_semantic_miss_tickers", "not_none"),
            ("candidate_entry_shadow_watchlist_recall_dossier_status", "watchlist_recall_dossier_status", "not_none"),
            ("candidate_entry_shadow_watchlist_recall_stage_counts", "watchlist_recall_stage_counts", "not_none"),
            ("candidate_entry_shadow_watchlist_recall_absent_from_candidate_pool_tickers", "watchlist_recall_absent_from_candidate_pool_tickers", "not_none"),
            ("candidate_entry_shadow_watchlist_recall_candidate_pool_layer_b_gap_tickers", "watchlist_recall_candidate_pool_layer_b_gap_tickers", "not_none"),
            ("candidate_entry_shadow_watchlist_recall_layer_b_watchlist_gap_tickers", "watchlist_recall_layer_b_watchlist_gap_tickers", "not_none"),
            ("candidate_entry_shadow_candidate_pool_recall_dossier_status", "candidate_pool_recall_dossier_status", "not_none"),
            ("candidate_entry_shadow_candidate_pool_recall_stage_counts", "candidate_pool_recall_stage_counts", "not_none"),
            ("candidate_entry_shadow_candidate_pool_recall_dominant_stage", "candidate_pool_recall_dominant_stage", "not_none"),
            ("candidate_entry_shadow_candidate_pool_recall_top_stage_tickers", "candidate_pool_recall_top_stage_tickers", "not_none"),
            ("candidate_entry_shadow_candidate_pool_recall_truncation_frontier_summary", "candidate_pool_recall_truncation_frontier_summary", "not_none"),
            ("candidate_entry_shadow_candidate_pool_recall_dominant_liquidity_gap_mode", "candidate_pool_recall_dominant_liquidity_gap_mode", "not_none"),
            ("candidate_entry_shadow_candidate_pool_recall_focus_liquidity_profiles", "candidate_pool_recall_focus_liquidity_profiles", "truthy"),
            ("candidate_entry_shadow_candidate_pool_recall_priority_handoff_counts", "candidate_pool_recall_priority_handoff_counts", "truthy"),
            ("candidate_entry_shadow_candidate_pool_recall_priority_handoff_branch_diagnoses", "candidate_pool_recall_priority_handoff_branch_diagnoses", "truthy"),
            ("candidate_entry_shadow_candidate_pool_recall_priority_handoff_branch_mechanisms", "candidate_pool_recall_priority_handoff_branch_mechanisms", "truthy"),
            ("candidate_entry_shadow_candidate_pool_branch_priority_board_status", "candidate_pool_branch_priority_board_status", "not_none"),
            ("candidate_entry_shadow_candidate_pool_branch_priority_alignment_status", "candidate_pool_branch_priority_alignment_status", "not_none"),
            ("candidate_entry_shadow_candidate_pool_branch_priority_alignment_summary", "candidate_pool_branch_priority_alignment_summary", "truthy"),
            ("candidate_entry_shadow_candidate_pool_lane_objective_support_status", "candidate_pool_lane_objective_support_status", "not_none"),
            ("candidate_entry_shadow_candidate_pool_corridor_validation_pack_status", "candidate_pool_corridor_validation_pack_status", "not_none"),
            ("candidate_entry_shadow_candidate_pool_corridor_shadow_pack_status", "candidate_pool_corridor_shadow_pack_status", "not_none"),
            ("candidate_entry_shadow_candidate_pool_rebucket_shadow_pack_status", "candidate_pool_rebucket_shadow_pack_status", "not_none"),
            ("candidate_entry_shadow_candidate_pool_rebucket_objective_validation_status", "candidate_pool_rebucket_objective_validation_status", "not_none"),
            ("candidate_entry_shadow_candidate_pool_rebucket_comparison_bundle_status", "candidate_pool_rebucket_comparison_bundle_status", "not_none"),
            ("candidate_entry_shadow_candidate_pool_lane_pair_board_status", "candidate_pool_lane_pair_board_status", "not_none"),
            ("candidate_entry_shadow_candidate_pool_upstream_handoff_board_status", "candidate_pool_upstream_handoff_board_status", "not_none"),
            ("candidate_entry_shadow_candidate_pool_corridor_uplift_runbook_status", "candidate_pool_corridor_uplift_runbook_status", "not_none"),
        ],
    )
    branch_experiment_queue = list(payload.get("candidate_pool_recall_priority_handoff_branch_experiment_queue") or [])
    if branch_experiment_queue:
        lines.append("- candidate_entry_shadow_candidate_pool_recall_priority_handoff_branch_experiment_queue: structured_summary")
        lines.append(f"- candidate_entry_shadow_candidate_pool_recall_priority_handoff_branch_experiment_queue_count: {len(branch_experiment_queue)}")
        for experiment in branch_experiment_queue[:3]:
            lines.append(
                f"- candidate_entry_shadow_branch_experiment: task_id={experiment.get('task_id')} handoff={experiment.get('priority_handoff')} readiness={experiment.get('prototype_readiness')} tickers={experiment.get('tickers')}"
            )
            lines.append(f"  prototype_summary: {experiment.get('prototype_summary')}")
            lines.append(f"  evaluation_summary: {experiment.get('evaluation_summary')}")
            lines.append(f"  guardrail_summary: {experiment.get('guardrail_summary')}")
    for row in list(payload.get("candidate_pool_branch_priority_board_rows") or [])[:3]:
        lines.append(
            f"- candidate_entry_shadow_candidate_pool_branch_priority: handoff={row.get('priority_handoff')} readiness={row.get('prototype_readiness')} execution_priority_rank={row.get('execution_priority_rank')} tickers={row.get('tickers')}"
        )
    for row in list(payload.get("candidate_pool_lane_objective_support_rows") or [])[:3]:
        lines.append(
            f"- candidate_entry_shadow_candidate_pool_lane_objective_support: handoff={row.get('priority_handoff')} verdict={row.get('support_verdict')} closed_cycle_count={row.get('closed_cycle_count')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')}"
        )
    for key, formatter in (
        (
            "candidate_pool_corridor_validation_pack_summary",
            lambda summary: f"- candidate_entry_shadow_candidate_pool_corridor_validation_pack_summary: pack_status={summary.get('pack_status')} primary_validation_ticker={summary.get('primary_validation_ticker')} parallel_watch_tickers={summary.get('parallel_watch_tickers')}",
        ),
        (
            "candidate_pool_corridor_shadow_pack_summary",
            lambda summary: f"- candidate_entry_shadow_candidate_pool_corridor_shadow_pack_summary: shadow_status={summary.get('shadow_status')} primary_shadow_replay={summary.get('primary_shadow_replay')} parallel_watch_tickers={summary.get('parallel_watch_tickers')}",
        ),
        (
            "candidate_pool_rebucket_shadow_pack_experiment",
            lambda summary: f"- candidate_entry_shadow_candidate_pool_rebucket_shadow_pack_experiment: handoff={summary.get('priority_handoff')} readiness={summary.get('prototype_readiness')} tickers={summary.get('tickers')}",
        ),
        (
            "candidate_pool_rebucket_objective_validation_summary",
            lambda summary: f"- candidate_entry_shadow_candidate_pool_rebucket_objective_validation_summary: validation_status={summary.get('validation_status')} support_verdict={summary.get('support_verdict')} mean_t_plus_2_return={summary.get('mean_t_plus_2_return')}",
        ),
        (
            "candidate_pool_rebucket_comparison_bundle_summary",
            lambda summary: f"- candidate_entry_shadow_candidate_pool_rebucket_comparison_bundle_summary: bundle_status={summary.get('bundle_status')} structural_leader={summary.get('structural_leader')} objective_leader={summary.get('objective_leader')}",
        ),
        (
            "candidate_pool_lane_pair_board_summary",
            lambda summary: f"- candidate_entry_shadow_candidate_pool_lane_pair_board_summary: pair_status={summary.get('pair_status')} board_leader={summary.get('board_leader')} leader_lane_family={summary.get('leader_lane_family')} leader_governance_status={summary.get('leader_governance_status')} leader_governance_execution_quality={summary.get('leader_governance_execution_quality')} leader_governance_entry_timing_bias={summary.get('leader_governance_entry_timing_bias')} parallel_watch_ticker={summary.get('parallel_watch_ticker')} parallel_watch_governance_blocker={summary.get('parallel_watch_governance_blocker')} parallel_watch_same_source_sample_count={summary.get('parallel_watch_same_source_sample_count')} parallel_watch_next_close_positive_rate={summary.get('parallel_watch_next_close_positive_rate')} parallel_watch_next_close_return_mean={summary.get('parallel_watch_next_close_return_mean')}",
        ),
        (
            "candidate_pool_upstream_handoff_board_summary",
            lambda summary: f"- candidate_entry_shadow_candidate_pool_upstream_handoff_board_summary: board_status={summary.get('board_status')} focus_tickers={summary.get('focus_tickers')} first_broken_handoff_counts={summary.get('first_broken_handoff_counts')}",
        ),
        (
            "candidate_pool_corridor_uplift_runbook_summary",
            lambda summary: f"- candidate_entry_shadow_candidate_pool_corridor_uplift_runbook_summary: runbook_status={summary.get('runbook_status')} primary_shadow_replay={summary.get('primary_shadow_replay')} parallel_watch_tickers={summary.get('parallel_watch_tickers')}",
        ),
    ):
        summary = dict(payload.get(key) or {})
        if summary:
            lines.append(formatter(summary))


def _append_manifest_summary_sections(lines: list[str], manifest: dict[str, Any]) -> None:
    for key, formatter in (
        (
            "continuation_focus_summary",
            lambda summary: f"- continuation_focus_summary: focus_ticker={summary.get('focus_ticker')} promotion_review_verdict={summary.get('promotion_review_verdict')} promotion_gate_verdict={summary.get('promotion_gate_verdict')} watchlist_execution_verdict={summary.get('watchlist_execution_verdict')} focus_watch_validation_status={summary.get('focus_watch_validation_status')} focus_watch_recent_supporting_window_count={summary.get('focus_watch_recent_supporting_window_count')} eligible_gate_verdict={summary.get('eligible_gate_verdict')} execution_gate_verdict={summary.get('execution_gate_verdict')} execution_gate_blockers={summary.get('execution_gate_blockers')} execution_overlay_verdict={summary.get('execution_overlay_verdict')} execution_overlay_promotion_blocker={summary.get('execution_overlay_promotion_blocker')} execution_overlay_persistence_requirement={summary.get('execution_overlay_persistence_requirement')} execution_overlay_lane_support_ratio={summary.get('execution_overlay_lane_support_ratio')} governance_status={summary.get('governance_status')}",
        ),
        (
            "selected_outcome_refresh_summary",
            lambda summary: f"- selected_outcome_refresh_summary: trade_date={summary.get('trade_date')} selected_count={summary.get('selected_count')} focus_ticker={summary.get('focus_ticker')} focus_cycle_status={summary.get('focus_cycle_status')} focus_data_status={summary.get('focus_data_status')} focus_next_close_return={summary.get('focus_next_close_return')} focus_t_plus_2_close_return={summary.get('focus_t_plus_2_close_return')} focus_historical_next_close_positive_rate={summary.get('focus_historical_next_close_positive_rate')} focus_historical_t_plus_2_close_positive_rate={summary.get('focus_historical_t_plus_2_close_positive_rate')} focus_next_day_contract_verdict={summary.get('focus_next_day_contract_verdict')} focus_t_plus_2_contract_verdict={summary.get('focus_t_plus_2_contract_verdict')} focus_overall_contract_verdict={summary.get('focus_overall_contract_verdict')}",
        ),
        (
            "carryover_multiday_continuation_audit_summary",
            lambda summary: f"- carryover_multiday_continuation_audit_summary: selected_ticker={summary.get('selected_ticker')} supportive_case_count={summary.get('supportive_case_count')} peer_status_counts={summary.get('peer_status_counts')} selected_path_t2_bias_only={summary.get('selected_path_t2_bias_only')} broad_family_only_multiday_unsupported={summary.get('broad_family_only_multiday_unsupported')} aligned_peer_multiday_ready={summary.get('aligned_peer_multiday_ready')} open_selected_case_count={summary.get('open_selected_case_count')} selected_t_plus_3_close_positive_rate={summary.get('selected_t_plus_3_close_positive_rate')} broad_family_only_next_close_positive_rate={summary.get('broad_family_only_next_close_positive_rate')}",
        ),
        ("carryover_aligned_peer_harvest_summary", lambda summary: f"- carryover_aligned_peer_harvest_summary: focus_ticker={summary.get('focus_ticker')} focus_status={summary.get('focus_status')} focus_latest_trade_date={summary.get('focus_latest_trade_date')} focus_latest_scope={summary.get('focus_latest_scope')} focus_closed_cycle_count={summary.get('focus_closed_cycle_count')} focus_next_day_available_count={summary.get('focus_next_day_available_count')} fresh_open_cycle_tickers={summary.get('fresh_open_cycle_tickers')}"),
        ("carryover_peer_expansion_summary", lambda summary: f"- carryover_peer_expansion_summary: focus_ticker={summary.get('focus_ticker')} focus_status={summary.get('focus_status')} priority_expansion_tickers={summary.get('priority_expansion_tickers')} watch_with_risk_tickers={summary.get('watch_with_risk_tickers')} expansion_status_counts={summary.get('expansion_status_counts')}"),
        ("carryover_aligned_peer_proof_summary", lambda summary: f"- carryover_aligned_peer_proof_summary: focus_ticker={summary.get('focus_ticker')} focus_proof_verdict={summary.get('focus_proof_verdict')} focus_promotion_review_verdict={summary.get('focus_promotion_review_verdict')} ready_for_promotion_review_tickers={summary.get('ready_for_promotion_review_tickers')} risk_review_tickers={summary.get('risk_review_tickers')} pending_t_plus_2_tickers={summary.get('pending_t_plus_2_tickers')}"),
        ("carryover_peer_promotion_gate_summary", lambda summary: f"- carryover_peer_promotion_gate_summary: focus_ticker={summary.get('focus_ticker')} focus_gate_verdict={summary.get('focus_gate_verdict')} ready_tickers={summary.get('ready_tickers')} blocked_open_tickers={summary.get('blocked_open_tickers')} risk_review_tickers={summary.get('risk_review_tickers')} pending_t_plus_2_tickers={summary.get('pending_t_plus_2_tickers')}"),
        ("continuation_promotion_ready_summary", lambda summary: f"- continuation_promotion_ready_summary: focus_ticker={summary.get('focus_ticker')} promotion_path_status={summary.get('promotion_path_status')} blockers_remaining_count={summary.get('blockers_remaining_count')} observed_independent_window_count={summary.get('observed_independent_window_count')} weighted_observed_window_credit={summary.get('weighted_observed_window_credit')} missing_independent_window_count={summary.get('missing_independent_window_count')} weighted_missing_window_credit={summary.get('weighted_missing_window_credit')} candidate_dossier_support_trade_date_count={summary.get('candidate_dossier_support_trade_date_count')} candidate_dossier_same_trade_date_variant_count={summary.get('candidate_dossier_same_trade_date_variant_count')} candidate_dossier_same_trade_date_variant_credit={summary.get('candidate_dossier_same_trade_date_variant_credit')} persistence_verdict={summary.get('persistence_verdict')} provisional_default_btst_edge_verdict={summary.get('provisional_default_btst_edge_verdict')} edge_threshold_verdict={summary.get('edge_threshold_verdict')} promotion_merge_review_verdict={summary.get('promotion_merge_review_verdict')} ready_after_next_qualifying_window={summary.get('ready_after_next_qualifying_window')} next_window_requirement={summary.get('next_window_requirement')} next_window_duplicate_trade_date_verdict={summary.get('next_window_duplicate_trade_date_verdict')} next_window_quality_requirement={summary.get('next_window_quality_requirement')} next_window_disqualified_bucket_verdict={summary.get('next_window_disqualified_bucket_verdict')} next_window_qualified_merge_review_verdict={summary.get('next_window_qualified_merge_review_verdict')} t_plus_2_positive_rate_delta_vs_default_btst={summary.get('t_plus_2_positive_rate_delta_vs_default_btst')} t_plus_2_mean_return_delta_vs_default_btst={summary.get('t_plus_2_mean_return_delta_vs_default_btst')}"),
        ("default_merge_review_summary", lambda summary: f"- default_merge_review_summary: focus_ticker={summary.get('focus_ticker')} merge_review_verdict={summary.get('merge_review_verdict')} operator_action={summary.get('operator_action')} counterfactual_verdict={dict(summary.get('counterfactual_validation') or {}).get('counterfactual_verdict')} t_plus_2_positive_rate_delta_vs_default_btst={summary.get('t_plus_2_positive_rate_delta_vs_default_btst')} t_plus_2_positive_rate_margin_vs_threshold={dict(summary.get('counterfactual_validation') or {}).get('t_plus_2_positive_rate_margin_vs_threshold')} t_plus_2_mean_return_delta_vs_default_btst={summary.get('t_plus_2_mean_return_delta_vs_default_btst')} t_plus_2_mean_return_margin_vs_threshold={dict(summary.get('counterfactual_validation') or {}).get('t_plus_2_mean_return_margin_vs_threshold')}"),
        ("default_merge_historical_counterfactual_summary", lambda summary: f"- default_merge_historical_counterfactual_summary: focus_ticker={summary.get('focus_ticker')} counterfactual_verdict={summary.get('counterfactual_verdict')} merged_positive_rate_uplift={dict(summary.get('uplift_vs_default_btst') or {}).get('t_plus_2_positive_rate_uplift')} merged_mean_return_uplift={dict(summary.get('uplift_vs_default_btst') or {}).get('mean_t_plus_2_return_uplift')}"),
        ("continuation_merge_candidate_ranking_summary", lambda summary: f"- continuation_merge_candidate_ranking_summary: candidate_count={summary.get('candidate_count')} top_ticker={dict(summary.get('top_candidate') or {}).get('ticker')} top_stage={dict(summary.get('top_candidate') or {}).get('promotion_path_status') or dict(summary.get('top_candidate') or {}).get('promotion_readiness_verdict')} top_positive_rate_delta={dict(summary.get('top_candidate') or {}).get('t_plus_2_positive_rate_delta_vs_default_btst')} top_mean_return_delta={dict(summary.get('top_candidate') or {}).get('t_plus_2_mean_return_delta_vs_default_btst')}"),
        ("default_merge_strict_counterfactual_summary", lambda summary: f"- default_merge_strict_counterfactual_summary: focus_ticker={summary.get('focus_ticker')} strict_counterfactual_verdict={summary.get('strict_counterfactual_verdict')} overlap_case_count={dict(summary.get('overlap_diagnostics') or {}).get('overlap_case_count')} strict_positive_rate_uplift={dict(summary.get('strict_uplift_vs_default_btst') or {}).get('t_plus_2_positive_rate_uplift')} strict_mean_return_uplift={dict(summary.get('strict_uplift_vs_default_btst') or {}).get('mean_t_plus_2_return_uplift')}"),
        ("merge_replay_validation_summary", lambda summary: f"- merge_replay_validation_summary: overall_verdict={summary.get('overall_verdict')} focus_tickers={summary.get('focus_tickers')} promoted_to_selected_count={summary.get('promoted_to_selected_count')} promoted_to_near_miss_count={summary.get('promoted_to_near_miss_count')} relief_applied_count={summary.get('relief_applied_count')} relief_actionable_applied_count={summary.get('relief_actionable_applied_count')} relief_already_selected_count={summary.get('relief_already_selected_count')} relief_positive_promotion_precision={summary.get('relief_positive_promotion_precision')} relief_actionable_positive_promotion_precision={summary.get('relief_actionable_positive_promotion_precision')} relief_no_promotion_ratio={summary.get('relief_no_promotion_ratio')} relief_actionable_no_promotion_ratio={summary.get('relief_actionable_no_promotion_ratio')} relief_decision_deteriorated_count={summary.get('relief_decision_deteriorated_count')} recommended_next_lever={summary.get('recommended_next_lever')} recommended_signal_levers={summary.get('recommended_signal_levers')}"),
        ("prepared_breakout_relief_validation_summary", lambda summary: f"- prepared_breakout_relief_validation_summary: focus_ticker={summary.get('focus_ticker')} verdict={summary.get('verdict')} selected_relief_window_count={summary.get('selected_relief_window_count')} selected_relief_alignment_rate={summary.get('selected_relief_alignment_rate')} outcome_support={dict(summary.get('outcome_support') or {}).get('evidence_status')}"),
        ("prepared_breakout_cohort_summary", lambda summary: f"- prepared_breakout_cohort_summary: verdict={summary.get('verdict')} candidate_count={summary.get('candidate_count')} selected_frontier_candidate_count={summary.get('selected_frontier_candidate_count')} next_candidate={dict(summary.get('next_candidate') or {}).get('ticker')}"),
        ("prepared_breakout_residual_surface_summary", lambda summary: f"- prepared_breakout_residual_surface_summary: focus_ticker={summary.get('focus_ticker')} verdict={summary.get('verdict')} focus_report_dir_count={summary.get('focus_report_dir_count')}"),
        ("candidate_pool_corridor_persistence_dossier_summary", lambda summary: f"- candidate_pool_corridor_persistence_dossier_summary: focus_ticker={summary.get('focus_ticker')} verdict={summary.get('verdict')} next_confirmation_requirement={summary.get('next_confirmation_requirement')}"),
        ("candidate_pool_corridor_window_command_board_summary", lambda summary: f"- candidate_pool_corridor_window_command_board_summary: focus_ticker={summary.get('focus_ticker')} verdict={summary.get('verdict')} next_target_trade_dates={summary.get('next_target_trade_dates')}"),
        ("candidate_pool_corridor_window_diagnostics_summary", lambda summary: f"- candidate_pool_corridor_window_diagnostics_summary: focus_ticker={summary.get('focus_ticker')} near_miss_verdict={dict(summary.get('near_miss_upgrade_window') or {}).get('verdict')} visibility_gap_verdict={dict(summary.get('visibility_gap_window') or {}).get('verdict')} recommendation={summary.get('recommendation')}"),
        ("candidate_pool_corridor_narrow_probe_summary", lambda summary: f"- candidate_pool_corridor_narrow_probe_summary: focus_ticker={summary.get('focus_ticker')} verdict={summary.get('verdict')} threshold_override_gap_vs_anchor={summary.get('threshold_override_gap_vs_anchor')} target_gap_to_selected={summary.get('target_gap_to_selected')}"),
        ("transient_probe_summary", lambda summary: f"- transient_probe_summary: ticker={summary.get('ticker')} status={summary.get('status')} blocker={summary.get('blocker')} candidate_source={summary.get('candidate_source')} score_state={summary.get('score_state')} downstream_bottleneck={summary.get('downstream_bottleneck')} historical_sample_count={summary.get('historical_sample_count')} historical_next_close_positive_rate={summary.get('historical_next_close_positive_rate')}"),
        ("execution_constraint_rollup", lambda summary: f"- execution_constraint_rollup: constraint_count={summary.get('constraint_count')} continuation_focus_tickers={summary.get('continuation_focus_tickers')} continuation_blockers={summary.get('continuation_blockers')} shadow_focus_tickers={summary.get('shadow_focus_tickers')} shadow_blockers={summary.get('shadow_blockers')}"),
    ):
        summary = dict(manifest.get(key) or {})
        if summary:
            lines.append(formatter(summary))


def _append_manifest_trailing_refreshes(lines: list[str], manifest: dict[str, Any]) -> None:
    for refresh_key, field_specs in (
        ("btst_score_fail_frontier_refresh", [("btst_score_fail_frontier_refresh_status", "status", "always"), ("btst_score_fail_frontier_rejected_case_count", "rejected_short_trade_boundary_count", "always"), ("btst_score_fail_frontier_rescueable_case_count", "rescueable_case_count", "always"), ("btst_score_fail_frontier_recurring_case_count", "recurring_case_count", "always"), ("btst_score_fail_frontier_transition_refresh_status", "transition_refresh_status", "always"), ("btst_score_fail_frontier_recurring_shadow_refresh_status", "recurring_shadow_refresh_status", "always")]),
        ("btst_rollout_governance_refresh", [("btst_rollout_governance_refresh_status", "status", "always"), ("btst_rollout_governance_row_count", "governance_row_count", "always"), ("btst_rollout_governance_penalty_status", "penalty_frontier_status", "always")]),
        ("btst_governance_synthesis_refresh", [("btst_governance_synthesis_status", "status", "always"), ("btst_governance_synthesis_waiting_lane_count", "waiting_lane_count", "always"), ("btst_governance_synthesis_ready_lane_count", "ready_lane_count", "always")]),
        ("btst_governance_validation_refresh", [("btst_governance_validation_status", "status", "always"), ("btst_governance_validation_overall_verdict", "overall_verdict", "always")]),
        ("btst_replay_cohort_refresh", [("btst_replay_cohort_status", "status", "always"), ("btst_replay_cohort_report_count", "report_count", "always"), ("btst_replay_cohort_short_trade_only_report_count", "short_trade_only_report_count", "always")]),
        ("btst_independent_window_monitor_refresh", [("btst_independent_window_monitor_status", "status", "always"), ("btst_independent_window_monitor_report_dir_count", "report_dir_count", "always"), ("btst_independent_window_monitor_ready_lane_count", "ready_lane_count", "always"), ("btst_independent_window_monitor_waiting_lane_count", "waiting_lane_count", "always")]),
        ("btst_tplus1_tplus2_objective_monitor_refresh", [("btst_tplus1_tplus2_objective_monitor_status", "status", "always"), ("btst_tplus1_tplus2_objective_monitor_report_dir_count", "report_dir_count", "always"), ("btst_tplus1_tplus2_objective_monitor_tradeable_closed_cycle_count", "tradeable_closed_cycle_count", "always"), ("btst_tplus1_tplus2_objective_monitor_tradeable_positive_rate", "tradeable_positive_rate", "always"), ("btst_tplus1_tplus2_objective_monitor_tradeable_return_hit_rate", "tradeable_return_hit_rate", "always"), ("btst_tplus1_tplus2_objective_monitor_best_ticker", "best_ticker", "always")]),
        ("btst_tradeable_opportunity_pool_refresh", [("btst_tradeable_opportunity_pool_refresh_status", "status", "always"), ("btst_tradeable_opportunity_pool_result_truth_count", "result_truth_pool_count", "always"), ("btst_tradeable_opportunity_pool_tradeable_count", "tradeable_opportunity_pool_count", "always"), ("btst_tradeable_opportunity_pool_capture_rate", "tradeable_pool_capture_rate", "always"), ("btst_tradeable_opportunity_pool_selected_or_near_miss_rate", "tradeable_pool_selected_or_near_miss_rate", "always"), ("btst_tradeable_opportunity_pool_strict_goal_false_negative_count", "strict_goal_false_negative_count", "always"), ("btst_tradeable_opportunity_pool_top_kill_switches", "top_tradeable_kill_switch_labels", "always"), ("btst_tradeable_opportunity_pool_no_candidate_entry_count", "no_candidate_entry_count", "always"), ("btst_tradeable_opportunity_pool_top_no_candidate_entry_industries", "top_no_candidate_entry_industries", "always"), ("btst_tradeable_opportunity_pool_top_no_candidate_entry_tickers", "top_no_candidate_entry_tickers", "always")]),
        ("latest_btst_run", [("latest_btst_report_dir", "report_dir", "always"), ("latest_btst_trade_date", "trade_date", "always"), ("latest_btst_next_trade_date", "next_trade_date", "always"), ("latest_btst_selection_target", "selection_target", "always")]),
    ):
        payload = dict(manifest.get(refresh_key) or {})
        if payload:
            _append_markdown_field_lines(lines, payload=payload, field_specs=field_specs)


def _append_manifest_reading_paths(
    lines: list[str],
    *,
    reading_paths: list[dict[str, Any]],
    entries_by_id: dict[str, dict[str, Any]],
    resolved_output_parent: Path,
) -> None:
    lines.append("")
    for reading_path in reading_paths:
        lines.append(f"## {reading_path['title']}")
        lines.append("")
        lines.append(reading_path["description"])
        lines.append("")
        for index, entry_id in enumerate(list(reading_path.get("entry_ids") or []), start=1):
            entry = entries_by_id[entry_id]
            lines.append(f"{index}. {_build_markdown_link(entry, resolved_output_parent)}")
            lines.append(f"   用途：{entry['question']}")
            lines.append(f"   类型：{entry['report_type']} | usage={entry['usage']} | priority={entry['priority']}")
        lines.append("")


def render_reports_manifest_markdown(manifest: dict[str, Any], *, output_parent: str | Path) -> str:
    resolved_output_parent = Path(output_parent).expanduser().resolve()
    entries_by_id = {entry["id"]: entry for entry in list(manifest.get("entries") or [])}

    lines: list[str] = []
    _append_manifest_header(lines, manifest)
    _append_candidate_entry_shadow_refresh(lines, dict(manifest.get("candidate_entry_shadow_refresh") or {}))
    _append_manifest_summary_sections(lines, manifest)
    
    _append_manifest_trailing_refreshes(lines, manifest)
    _append_manifest_reading_paths(
        lines,
        reading_paths=list(manifest.get("reading_paths") or []),
        entries_by_id=entries_by_id,
        resolved_output_parent=resolved_output_parent,
    )

    return "\n".join(lines).rstrip() + "\n"


def generate_reports_manifest_artifacts(
    reports_root: str | Path,
    *,
    output_json: str | Path | None = None,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_output_json = Path(output_json).expanduser().resolve() if output_json else (resolved_reports_root / DEFAULT_OUTPUT_JSON.name).resolve()
    resolved_output_md = Path(output_md).expanduser().resolve() if output_md else (resolved_reports_root / DEFAULT_OUTPUT_MD.name).resolve()
    repo_root = _resolve_repo_root(resolved_reports_root)
    latest_btst_run = _select_latest_btst_candidate(resolved_reports_root, repo_root)
    catalyst_theme_frontier_refresh = refresh_latest_btst_catalyst_theme_frontier_artifacts(latest_btst_run)
    if latest_btst_run:
        latest_btst_run = _extract_btst_candidate(latest_btst_run["report_dir"], repo_root)
    btst_window_evidence_refresh = refresh_btst_window_evidence_artifacts(resolved_reports_root)
    btst_independent_window_monitor_refresh = refresh_btst_independent_window_monitor_artifacts(resolved_reports_root)
    btst_tplus1_tplus2_objective_monitor_refresh = refresh_btst_tplus1_tplus2_objective_monitor_artifacts(resolved_reports_root)
    btst_tradeable_opportunity_pool_refresh = refresh_btst_tradeable_opportunity_pool_artifacts(resolved_reports_root)
    candidate_entry_shadow_refresh = refresh_btst_candidate_entry_shadow_lane_artifacts(resolved_reports_root)
    btst_score_fail_frontier_refresh = refresh_btst_score_fail_frontier_artifacts(
        resolved_reports_root,
        latest_btst_run=latest_btst_run,
        window_evidence_refresh=btst_window_evidence_refresh,
    )
    btst_rollout_governance_refresh = refresh_btst_rollout_governance_artifacts(resolved_reports_root)
    btst_governance_synthesis_refresh = refresh_btst_governance_synthesis_artifacts(
        resolved_reports_root,
        latest_btst_run=latest_btst_run,
    )
    btst_governance_validation_refresh = refresh_btst_governance_validation_artifacts(resolved_reports_root)
    btst_replay_cohort_refresh = refresh_btst_replay_cohort_artifacts(resolved_reports_root)
    manifest = generate_reports_manifest(
        resolved_reports_root,
        latest_btst_run=latest_btst_run,
        catalyst_theme_frontier_refresh=catalyst_theme_frontier_refresh,
        btst_window_evidence_refresh=btst_window_evidence_refresh,
        candidate_entry_shadow_refresh=candidate_entry_shadow_refresh,
        btst_score_fail_frontier_refresh=btst_score_fail_frontier_refresh,
        btst_rollout_governance_refresh=btst_rollout_governance_refresh,
        btst_governance_synthesis_refresh=btst_governance_synthesis_refresh,
        btst_governance_validation_refresh=btst_governance_validation_refresh,
        btst_replay_cohort_refresh=btst_replay_cohort_refresh,
        btst_independent_window_monitor_refresh=btst_independent_window_monitor_refresh,
        btst_tplus1_tplus2_objective_monitor_refresh=btst_tplus1_tplus2_objective_monitor_refresh,
        btst_tradeable_opportunity_pool_refresh=btst_tradeable_opportunity_pool_refresh,
    )
    resolved_output_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resolved_output_md.write_text(render_reports_manifest_markdown(manifest, output_parent=resolved_output_md.parent), encoding="utf-8")
    return {
        "manifest": manifest,
        "catalyst_theme_frontier_refresh": catalyst_theme_frontier_refresh,
        "btst_window_evidence_refresh": btst_window_evidence_refresh,
        "candidate_entry_shadow_refresh": candidate_entry_shadow_refresh,
        "btst_score_fail_frontier_refresh": btst_score_fail_frontier_refresh,
        "btst_rollout_governance_refresh": btst_rollout_governance_refresh,
        "btst_governance_synthesis_refresh": btst_governance_synthesis_refresh,
        "btst_governance_validation_refresh": btst_governance_validation_refresh,
        "btst_replay_cohort_refresh": btst_replay_cohort_refresh,
        "btst_independent_window_monitor_refresh": btst_independent_window_monitor_refresh,
        "btst_tplus1_tplus2_objective_monitor_refresh": btst_tplus1_tplus2_objective_monitor_refresh,
        "btst_tradeable_opportunity_pool_refresh": btst_tradeable_opportunity_pool_refresh,
        "json_path": resolved_output_json.as_posix(),
        "markdown_path": resolved_output_md.as_posix(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a machine-readable manifest for frequently reviewed reports under data/reports.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR), help="Reports root directory to scan")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON manifest path")
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD), help="Output Markdown manifest path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = generate_reports_manifest_artifacts(
        reports_root=args.reports_root,
        output_json=args.output_json,
        output_md=args.output_md,
    )
    print(f"report_manifest_json={result['json_path']}")
    print(f"report_manifest_markdown={result['markdown_path']}")


if __name__ == "__main__":
    main()
