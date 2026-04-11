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
    if not _looks_like_report_dir(report_dir):
        return None
    session_summary = _safe_load_json(report_dir / "session_summary.json")
    if not session_summary:
        return None
    followup = dict(session_summary.get("btst_followup") or {})
    artifacts = dict(session_summary.get("artifacts") or {})
    priority_board_json_path = followup.get("priority_board_json") or artifacts.get("btst_next_day_priority_board_json")
    brief_json_path = followup.get("brief_json") or artifacts.get("btst_next_day_trade_brief_json")
    catalyst_theme_frontier_json_path = followup.get("catalyst_theme_frontier_json") or artifacts.get("btst_catalyst_theme_frontier_json")
    catalyst_theme_frontier_markdown_path = followup.get("catalyst_theme_frontier_markdown") or artifacts.get("btst_catalyst_theme_frontier_markdown")
    if not priority_board_json_path:
        return None

    plan_generation = dict(session_summary.get("plan_generation") or {})
    selection_target = str(plan_generation.get("selection_target") or session_summary.get("selection_target") or "") or None
    trade_date = _normalize_trade_date(followup.get("trade_date") or session_summary.get("end_date"))
    next_trade_date = _normalize_trade_date(followup.get("next_trade_date"))
    return {
        "report_dir": str(report_dir.resolve()),
        "report_dir_name": report_dir.name,
        "selection_target": selection_target,
        "trade_date": trade_date,
        "next_trade_date": next_trade_date,
        "priority_board_json_path": str(Path(priority_board_json_path).expanduser().resolve()),
        "brief_json_path": str(Path(brief_json_path).expanduser().resolve()) if brief_json_path else None,
        "catalyst_theme_frontier_json_path": str(Path(catalyst_theme_frontier_json_path).expanduser().resolve()) if catalyst_theme_frontier_json_path else None,
        "catalyst_theme_frontier_markdown_path": str(Path(catalyst_theme_frontier_markdown_path).expanduser().resolve()) if catalyst_theme_frontier_markdown_path else None,
        "rank": (trade_date or "", report_dir.stat().st_mtime_ns, report_dir.name),
    }


def _select_previous_btst_report_snapshot(
    reports_root: str | Path,
    *,
    current_report_dir: str | None,
    selection_target: str | None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    candidates = [
        candidate
        for candidate in (_extract_btst_report_candidate(path) for path in resolved_reports_root.iterdir())
        if candidate and candidate.get("report_dir") != current_report_dir
    ]
    if selection_target:
        scoped_candidates = [candidate for candidate in candidates if candidate.get("selection_target") == selection_target]
        if scoped_candidates:
            candidates = scoped_candidates
    if not candidates:
        return {}

    selected_candidate = max(candidates, key=lambda candidate: candidate["rank"])
    priority_board = _safe_load_json(selected_candidate.get("priority_board_json_path"))
    brief = _safe_load_json(selected_candidate.get("brief_json_path"))
    catalyst_theme_frontier = _safe_load_json(selected_candidate.get("catalyst_theme_frontier_json_path"))
    return {
        "reference_kind": "previous_btst_report",
        "report_dir": selected_candidate.get("report_dir_name"),
        "report_dir_abs": selected_candidate.get("report_dir"),
        "selection_target": selected_candidate.get("selection_target"),
        "trade_date": selected_candidate.get("trade_date"),
        "next_trade_date": selected_candidate.get("next_trade_date"),
        "priority_board": priority_board,
        "brief_summary": dict(brief.get("summary") or {}),
        "priority_board_json_path": selected_candidate.get("priority_board_json_path"),
        "catalyst_theme_frontier_summary": _extract_catalyst_theme_frontier_summary(catalyst_theme_frontier),
        "catalyst_theme_frontier_json_path": selected_candidate.get("catalyst_theme_frontier_json_path"),
        "catalyst_theme_frontier_markdown_path": selected_candidate.get("catalyst_theme_frontier_markdown_path"),
    }


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
    ordered: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        token = str(value or "").strip()
        if not token or token in excluded or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _build_upstream_shadow_followup_overlay(
    reports_root: str | Path,
    *,
    no_candidate_entry_priority_tickers: list[Any] | None = None,
    absent_from_watchlist_tickers: list[Any] | None = None,
    watchlist_absent_from_candidate_pool_tickers: list[Any] | None = None,
    upstream_handoff_focus_tickers: list[Any] | None = None,
) -> dict[str, Any]:
    summary = load_latest_upstream_shadow_followup_summary(reports_root)
    validated_tickers = [str(value or "") for value in list(summary.get("validated_tickers") or []) if str(value or "").strip()]
    validated_set = set(validated_tickers)

    active_priority_tickers = _ordered_without(no_candidate_entry_priority_tickers, validated_set)
    active_absent_from_watchlist_tickers = _ordered_without(absent_from_watchlist_tickers, validated_set)
    active_watchlist_absent_from_candidate_pool_tickers = _ordered_without(watchlist_absent_from_candidate_pool_tickers, validated_set)
    active_upstream_handoff_focus_tickers = _ordered_without(upstream_handoff_focus_tickers, validated_set)

    recommendation = summary.get("recommendation")
    if summary.get("status") == "validated_upstream_shadow_followup_available":
        if active_priority_tickers:
            recommendation = (
                f"最新正式 upstream shadow followup 已把 {validated_tickers} 转入 downstream decision 分层；"
                f"当前 upstream recall backlog 应收敛到 {active_priority_tickers}，避免对已验证票重复做 absent_from_watchlist / candidate_pool recall。"
            )
        else:
            recommendation = (
                f"最新正式 upstream shadow followup 已把 {validated_tickers} 全部转入 downstream decision 分层；"
                "当前 control tower 不应再把这些票作为 upstream recall 主任务。"
            )

    return {
        **summary,
        "validated_tickers": validated_tickers,
        "active_no_candidate_entry_priority_tickers": active_priority_tickers,
        "active_absent_from_watchlist_tickers": active_absent_from_watchlist_tickers,
        "active_watchlist_absent_from_candidate_pool_tickers": active_watchlist_absent_from_candidate_pool_tickers,
        "active_upstream_handoff_focus_tickers": active_upstream_handoff_focus_tickers,
        "recommendation": recommendation,
    }


def _extract_catalyst_theme_frontier_summary(frontier: dict[str, Any]) -> dict[str, Any]:
    if not frontier:
        return {}

    recommended_variant = dict(frontier.get("recommended_variant") or {})
    promoted_shadow_count = int(recommended_variant.get("promoted_shadow_count") or 0)
    shadow_candidate_count = int(frontier.get("shadow_candidate_count") or 0)
    baseline_selected_count = int(frontier.get("baseline_selected_count") or 0)
    if promoted_shadow_count > 0:
        status = "promotable_shadow_exists"
    elif shadow_candidate_count > 0:
        status = "shadow_only_no_promotion"
    elif baseline_selected_count > 0:
        status = "selected_only_no_shadow"
    else:
        status = "no_catalyst_theme_candidates"

    top_promoted_rows = list(recommended_variant.get("top_promoted_rows") or [])
    return {
        "status": status,
        "shadow_candidate_count": shadow_candidate_count,
        "baseline_selected_count": baseline_selected_count,
        "recommended_variant_name": recommended_variant.get("variant_name"),
        "recommended_promoted_shadow_count": promoted_shadow_count,
        "recommended_relaxation_cost": recommended_variant.get("threshold_relaxation_cost"),
        "recommended_thresholds": dict(recommended_variant.get("thresholds") or {}),
        "recommended_promoted_tickers": [str(row.get("ticker") or "") for row in top_promoted_rows if row.get("ticker")][:3],
        "recommendation": frontier.get("recommendation"),
    }


def _extract_score_fail_frontier_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    refresh = dict(manifest.get("btst_score_fail_frontier_refresh") or {})
    score_fail_analysis = _safe_load_json(refresh.get("analysis_json"))
    score_fail_frontier = _safe_load_json(refresh.get("frontier_json"))
    recurring_frontier = _safe_load_json(refresh.get("recurring_json"))
    if not any([refresh, score_fail_analysis, score_fail_frontier, recurring_frontier]):
        return {}

    top_rescue_rows = list(score_fail_frontier.get("minimal_near_miss_rows") or [])[:3]
    priority_queue = list(recurring_frontier.get("priority_queue") or [])[:3]
    return {
        "status": refresh.get("status"),
        "report_dir": refresh.get("report_dir"),
        "rejected_short_trade_boundary_count": score_fail_analysis.get("rejected_short_trade_boundary_count"),
        "rescueable_case_count": score_fail_frontier.get("rescueable_case_count"),
        "threshold_only_rescue_count": score_fail_frontier.get("rescueable_with_threshold_only_count"),
        "recurring_case_count": recurring_frontier.get("recurring_case_count"),
        "transition_candidate_count": refresh.get("transition_candidate_count"),
        "recurring_shadow_refresh_status": refresh.get("recurring_shadow_refresh_status"),
        "priority_queue_tickers": [str(row.get("ticker") or "") for row in priority_queue if row.get("ticker")],
        "top_rescue_tickers": [str(row.get("ticker") or "") for row in top_rescue_rows if row.get("ticker")],
        "top_rescue_rows": top_rescue_rows,
        "priority_queue": priority_queue,
        "recommendation": recurring_frontier.get("recommendation") or score_fail_frontier.get("recommendation") or score_fail_analysis.get("recommendation"),
        "analysis_markdown_path": refresh.get("analysis_markdown"),
        "frontier_markdown_path": refresh.get("frontier_markdown"),
        "recurring_markdown_path": refresh.get("recurring_markdown"),
        "transition_markdown_path": refresh.get("transition_markdown"),
    }


def _extract_tradeable_opportunity_pool_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    refresh = dict(manifest.get("btst_tradeable_opportunity_pool_refresh") or {})
    analysis = _safe_load_json(refresh.get("analysis_json"))
    waterfall = _safe_load_json(refresh.get("waterfall_json"))
    if not any([refresh, analysis, waterfall]):
        return {}

    top_tradeable_kill_switches = list(waterfall.get("top_tradeable_kill_switches") or refresh.get("top_tradeable_kill_switches") or [])[:3]
    top_strict_goal_rows = list(analysis.get("top_strict_goal_false_negative_rows") or waterfall.get("top_strict_goal_false_negative_rows") or [])[:3]
    return {
        "status": refresh.get("status"),
        "result_truth_pool_count": refresh.get("result_truth_pool_count") or analysis.get("result_truth_pool_count"),
        "tradeable_opportunity_pool_count": refresh.get("tradeable_opportunity_pool_count") or analysis.get("tradeable_opportunity_pool_count"),
        "system_recall_count": refresh.get("system_recall_count") or analysis.get("system_recall_count"),
        "selected_or_near_miss_count": refresh.get("selected_or_near_miss_count") or analysis.get("selected_or_near_miss_count"),
        "main_execution_pool_count": refresh.get("main_execution_pool_count") or analysis.get("main_execution_pool_count"),
        "strict_goal_case_count": refresh.get("strict_goal_case_count") or analysis.get("strict_goal_case_count"),
        "strict_goal_false_negative_count": refresh.get("strict_goal_false_negative_count") or analysis.get("strict_goal_false_negative_count"),
        "tradeable_pool_capture_rate": refresh.get("tradeable_pool_capture_rate") or analysis.get("tradeable_pool_capture_rate"),
        "tradeable_pool_selected_or_near_miss_rate": refresh.get("tradeable_pool_selected_or_near_miss_rate") or analysis.get("tradeable_pool_selected_or_near_miss_rate"),
        "tradeable_pool_main_execution_rate": refresh.get("tradeable_pool_main_execution_rate") or analysis.get("tradeable_pool_main_execution_rate"),
        "no_candidate_entry_count": refresh.get("no_candidate_entry_count") or dict(analysis.get("no_candidate_entry_summary") or {}).get("count"),
        "no_candidate_entry_share_of_tradeable_pool": refresh.get("no_candidate_entry_share_of_tradeable_pool") or dict(analysis.get("no_candidate_entry_summary") or {}).get("share_of_tradeable_pool"),
        "top_no_candidate_entry_industries": refresh.get("top_no_candidate_entry_industries") or list(dict(dict(analysis.get("no_candidate_entry_summary") or {}).get("industry_counts") or {}).keys())[:3],
        "top_no_candidate_entry_tickers": refresh.get("top_no_candidate_entry_tickers") or [
            str(row.get("ticker") or "")
            for row in list(dict(analysis.get("no_candidate_entry_summary") or {}).get("top_ticker_rows") or [])[:3]
            if row.get("ticker")
        ],
        "top_tradeable_kill_switches": top_tradeable_kill_switches,
        "top_tradeable_kill_switch_labels": [str(row.get("kill_switch") or "") for row in top_tradeable_kill_switches if row.get("kill_switch")],
        "top_strict_goal_false_negative_tickers": [str(row.get("ticker") or "") for row in top_strict_goal_rows if row.get("ticker")],
        "top_strict_goal_false_negative_rows": top_strict_goal_rows,
        "recommendation": refresh.get("recommendation") or analysis.get("recommendation") or waterfall.get("recommendation"),
        "analysis_markdown_path": refresh.get("analysis_markdown"),
        "waterfall_markdown_path": refresh.get("waterfall_markdown"),
    }


def _extract_no_candidate_entry_action_board_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    refresh = dict(manifest.get("candidate_entry_shadow_refresh") or {})
    action_board_entry = _entry_by_id(manifest, "btst_no_candidate_entry_action_board_latest")
    analysis = _safe_load_json(refresh.get("no_candidate_entry_action_board_json") or action_board_entry.get("absolute_path"))
    if not any([refresh, analysis, action_board_entry]):
        return {}

    next_tasks = list(analysis.get("next_3_tasks") or [])[:3]
    priority_queue = list(analysis.get("priority_queue") or [])[:3]
    return {
        "status": refresh.get("no_candidate_entry_action_board_status") or ("available" if analysis else None),
        "priority_queue_count": refresh.get("no_candidate_entry_priority_queue_count") or analysis.get("priority_queue_count"),
        "top_priority_tickers": refresh.get("no_candidate_entry_top_tickers") or analysis.get("top_priority_tickers"),
        "top_hotspot_report_dirs": refresh.get("no_candidate_entry_hotspot_report_dirs") or analysis.get("top_hotspot_report_dirs"),
        "next_tasks": next_tasks,
        "priority_queue": priority_queue,
        "recommendation": analysis.get("recommendation"),
        "analysis_markdown_path": action_board_entry.get("absolute_path"),
    }


def _extract_no_candidate_entry_replay_bundle_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    refresh = dict(manifest.get("candidate_entry_shadow_refresh") or {})
    bundle_entry = _entry_by_id(manifest, "btst_no_candidate_entry_replay_bundle_latest")
    analysis = _safe_load_json(refresh.get("no_candidate_entry_replay_bundle_json") or bundle_entry.get("absolute_path"))
    if not any([refresh, analysis, bundle_entry]):
        return {}

    global_window_scan = dict(analysis.get("global_window_scan") or {})
    return {
        "status": refresh.get("no_candidate_entry_replay_bundle_status") or ("available" if analysis else None),
        "promising_priority_tickers": refresh.get("no_candidate_entry_promising_tickers") or analysis.get("promising_priority_tickers"),
        "promising_hotspot_report_dirs": analysis.get("promising_hotspot_report_dirs"),
        "candidate_entry_status_counts": analysis.get("candidate_entry_status_counts"),
        "global_window_scan_rollout_readiness": global_window_scan.get("rollout_readiness"),
        "global_window_scan_focus_hit_report_count": global_window_scan.get("focus_hit_report_count"),
        "next_actions": list(analysis.get("next_actions") or [])[:3],
        "recommendation": analysis.get("recommendation"),
        "analysis_markdown_path": bundle_entry.get("absolute_path"),
    }


def _extract_no_candidate_entry_failure_dossier_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    refresh = dict(manifest.get("candidate_entry_shadow_refresh") or {})
    dossier_entry = _entry_by_id(manifest, "btst_no_candidate_entry_failure_dossier_latest")
    analysis = _safe_load_json(refresh.get("no_candidate_entry_failure_dossier_json") or dossier_entry.get("absolute_path"))
    if not any([refresh, analysis, dossier_entry]):
        return {}

    return {
        "status": refresh.get("no_candidate_entry_failure_dossier_status") or ("available" if analysis else None),
        "priority_failure_class_counts": analysis.get("priority_failure_class_counts"),
        "hotspot_failure_class_counts": analysis.get("hotspot_failure_class_counts"),
        "priority_handoff_stage_counts": analysis.get("priority_handoff_stage_counts"),
        "top_absent_from_watchlist_tickers": analysis.get("top_absent_from_watchlist_tickers"),
        "top_watchlist_visible_but_not_candidate_entry_tickers": analysis.get("top_watchlist_visible_but_not_candidate_entry_tickers"),
        "top_candidate_entry_visible_but_not_selection_target_tickers": analysis.get("top_candidate_entry_visible_but_not_selection_target_tickers"),
        "top_upstream_absence_tickers": refresh.get("no_candidate_entry_upstream_absence_tickers") or analysis.get("top_upstream_absence_tickers"),
        "top_candidate_entry_semantic_miss_tickers": refresh.get("no_candidate_entry_semantic_miss_tickers") or analysis.get("top_candidate_entry_semantic_miss_tickers"),
        "top_present_but_outside_candidate_entry_tickers": analysis.get("top_present_but_outside_candidate_entry_tickers"),
        "top_missing_replay_input_tickers": analysis.get("top_missing_replay_input_tickers"),
        "handoff_action_queue": list(analysis.get("priority_handoff_action_queue") or [])[:3],
        "next_actions": list(analysis.get("next_actions") or [])[:4],
        "recommendation": analysis.get("recommendation"),
        "analysis_markdown_path": dossier_entry.get("absolute_path"),
    }


def _extract_watchlist_recall_dossier_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    refresh = dict(manifest.get("candidate_entry_shadow_refresh") or {})
    dossier_entry = _entry_by_id(manifest, "btst_watchlist_recall_dossier_latest")
    analysis = _safe_load_json(refresh.get("watchlist_recall_dossier_json") or dossier_entry.get("absolute_path"))
    if not any([refresh, analysis, dossier_entry]):
        return {}

    return {
        "status": refresh.get("watchlist_recall_dossier_status") or ("available" if analysis else None),
        "priority_recall_stage_counts": analysis.get("priority_recall_stage_counts"),
        "top_absent_from_candidate_pool_tickers": refresh.get("watchlist_recall_absent_from_candidate_pool_tickers") or analysis.get("top_absent_from_candidate_pool_tickers"),
        "top_candidate_pool_visible_but_missing_layer_b_tickers": refresh.get("watchlist_recall_candidate_pool_layer_b_gap_tickers") or analysis.get("top_candidate_pool_visible_but_missing_layer_b_tickers"),
        "top_layer_b_visible_but_missing_watchlist_tickers": refresh.get("watchlist_recall_layer_b_watchlist_gap_tickers") or analysis.get("top_layer_b_visible_but_missing_watchlist_tickers"),
        "action_queue": list(analysis.get("action_queue") or [])[:3],
        "next_actions": list(analysis.get("next_actions") or [])[:4],
        "recommendation": analysis.get("recommendation"),
        "analysis_markdown_path": dossier_entry.get("absolute_path"),
    }


def _extract_candidate_pool_recall_dossier_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    refresh = dict(manifest.get("candidate_entry_shadow_refresh") or {})
    dossier_entry = _entry_by_id(manifest, "btst_candidate_pool_recall_dossier_latest")
    analysis = _safe_load_json(refresh.get("candidate_pool_recall_dossier_json") or dossier_entry.get("absolute_path"))
    if not any([refresh, analysis, dossier_entry]):
        return {}

    return {
        "status": refresh.get("candidate_pool_recall_dossier_status") or ("available" if analysis else None),
        "priority_stage_counts": refresh.get("candidate_pool_recall_stage_counts") or analysis.get("priority_stage_counts"),
        "dominant_stage": refresh.get("candidate_pool_recall_dominant_stage") or analysis.get("dominant_stage"),
        "top_stage_tickers": refresh.get("candidate_pool_recall_top_stage_tickers") or analysis.get("top_stage_tickers"),
        "truncation_frontier_summary": refresh.get("candidate_pool_recall_truncation_frontier_summary") or analysis.get("truncation_frontier_summary"),
        "focus_liquidity_profiles": refresh.get("candidate_pool_recall_focus_liquidity_profiles") or list(dict(analysis.get("focus_liquidity_profile_summary") or {}).get("primary_focus_tickers") or [])[:3],
        "priority_handoff_counts": refresh.get("candidate_pool_recall_priority_handoff_counts") or dict(dict(analysis.get("focus_liquidity_profile_summary") or {}).get("priority_handoff_counts") or {}),
        "priority_handoff_branch_diagnoses": refresh.get("candidate_pool_recall_priority_handoff_branch_diagnoses") or list(analysis.get("priority_handoff_branch_diagnoses") or [])[:3],
        "priority_handoff_branch_mechanisms": refresh.get("candidate_pool_recall_priority_handoff_branch_mechanisms") or list(analysis.get("priority_handoff_branch_mechanisms") or [])[:3],
        "priority_handoff_branch_experiment_queue": refresh.get("candidate_pool_recall_priority_handoff_branch_experiment_queue") or list(analysis.get("priority_handoff_branch_experiment_queue") or [])[:3],
        "branch_priority_board_status": refresh.get("candidate_pool_branch_priority_board_status"),
        "branch_priority_board_rows": list(refresh.get("candidate_pool_branch_priority_board_rows") or []),
        "branch_priority_alignment_status": refresh.get("candidate_pool_branch_priority_alignment_status"),
        "branch_priority_alignment_summary": refresh.get("candidate_pool_branch_priority_alignment_summary"),
        "lane_objective_support_status": refresh.get("candidate_pool_lane_objective_support_status"),
        "lane_objective_support_rows": list(refresh.get("candidate_pool_lane_objective_support_rows") or []),
        "corridor_validation_pack_status": refresh.get("candidate_pool_corridor_validation_pack_status"),
        "corridor_validation_pack_summary": dict(refresh.get("candidate_pool_corridor_validation_pack_summary") or {}),
        "corridor_shadow_pack_status": refresh.get("candidate_pool_corridor_shadow_pack_status"),
        "corridor_shadow_pack_summary": dict(refresh.get("candidate_pool_corridor_shadow_pack_summary") or {}),
        "rebucket_shadow_pack_status": refresh.get("candidate_pool_rebucket_shadow_pack_status"),
        "rebucket_shadow_pack_experiment": dict(refresh.get("candidate_pool_rebucket_shadow_pack_experiment") or {}),
        "rebucket_objective_validation_status": refresh.get("candidate_pool_rebucket_objective_validation_status"),
        "rebucket_objective_validation_summary": dict(refresh.get("candidate_pool_rebucket_objective_validation_summary") or {}),
        "rebucket_comparison_bundle_status": refresh.get("candidate_pool_rebucket_comparison_bundle_status"),
        "rebucket_comparison_bundle_summary": dict(refresh.get("candidate_pool_rebucket_comparison_bundle_summary") or {}),
        "lane_pair_board_status": refresh.get("candidate_pool_lane_pair_board_status"),
        "lane_pair_board_summary": dict(refresh.get("candidate_pool_lane_pair_board_summary") or {}),
        "continuation_focus_summary": dict(refresh.get("continuation_focus_summary") or {}),
        "continuation_promotion_ready_summary": dict(refresh.get("continuation_promotion_ready_summary") or {}),
        "transient_probe_summary": dict(refresh.get("transient_probe_summary") or {}),
        "upstream_handoff_board_status": refresh.get("candidate_pool_upstream_handoff_board_status"),
        "upstream_handoff_board_summary": dict(refresh.get("candidate_pool_upstream_handoff_board_summary") or {}),
        "corridor_uplift_runbook_status": refresh.get("candidate_pool_corridor_uplift_runbook_status"),
        "corridor_uplift_runbook_summary": dict(refresh.get("candidate_pool_corridor_uplift_runbook_summary") or {}),
        "execution_constraint_rollup": dict(refresh.get("execution_constraint_rollup") or {}),
        "action_queue": list(analysis.get("action_queue") or [])[:3],
        "next_actions": list(analysis.get("next_actions") or [])[:4],
        "recommendation": analysis.get("recommendation"),
        "analysis_markdown_path": dossier_entry.get("absolute_path"),
    }


def _extract_latest_btst_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    latest_btst_run = dict(manifest.get("latest_btst_run") or {})
    report_dir_abs = latest_btst_run.get("report_dir_abs")
    if not report_dir_abs:
        return {}

    session_summary_path = Path(report_dir_abs).expanduser().resolve() / "session_summary.json"
    session_summary = _safe_load_json(session_summary_path)
    followup = dict(session_summary.get("btst_followup") or {})
    artifacts = dict(session_summary.get("artifacts") or {})

    priority_board_json_path = followup.get("priority_board_json") or artifacts.get("btst_next_day_priority_board_json")
    priority_board_markdown_path = followup.get("priority_board_markdown") or artifacts.get("btst_next_day_priority_board_markdown")
    brief_json_path = followup.get("brief_json") or artifacts.get("btst_next_day_trade_brief_json")
    brief_markdown_path = followup.get("brief_markdown") or artifacts.get("btst_next_day_trade_brief_markdown")
    execution_card_markdown_path = followup.get("execution_card_markdown") or artifacts.get("btst_premarket_execution_card_markdown")
    opening_watch_card_markdown_path = followup.get("opening_watch_card_markdown") or artifacts.get("btst_opening_watch_card_markdown")
    catalyst_theme_frontier_json_path = followup.get("catalyst_theme_frontier_json") or artifacts.get("btst_catalyst_theme_frontier_json")
    catalyst_theme_frontier_markdown_path = followup.get("catalyst_theme_frontier_markdown") or artifacts.get("btst_catalyst_theme_frontier_markdown")

    priority_board = _safe_load_json(priority_board_json_path)
    brief = _safe_load_json(brief_json_path)
    catalyst_theme_frontier = _safe_load_json(catalyst_theme_frontier_json_path)
    brief_summary = dict(brief.get("summary") or {})
    score_fail_frontier_summary = _extract_score_fail_frontier_summary(manifest)

    return {
        "report_dir_abs": report_dir_abs,
        "report_dir": latest_btst_run.get("report_dir"),
        "selection_target": latest_btst_run.get("selection_target"),
        "trade_date": latest_btst_run.get("trade_date"),
        "next_trade_date": latest_btst_run.get("next_trade_date"),
        "priority_board_json_path": str(Path(priority_board_json_path).expanduser().resolve()) if priority_board_json_path else None,
        "priority_board_markdown_path": str(Path(priority_board_markdown_path).expanduser().resolve()) if priority_board_markdown_path else None,
        "brief_json_path": str(Path(brief_json_path).expanduser().resolve()) if brief_json_path else None,
        "brief_markdown_path": str(Path(brief_markdown_path).expanduser().resolve()) if brief_markdown_path else None,
        "execution_card_markdown_path": str(Path(execution_card_markdown_path).expanduser().resolve()) if execution_card_markdown_path else None,
        "opening_watch_card_markdown_path": str(Path(opening_watch_card_markdown_path).expanduser().resolve()) if opening_watch_card_markdown_path else None,
        "catalyst_theme_frontier_json_path": str(Path(catalyst_theme_frontier_json_path).expanduser().resolve()) if catalyst_theme_frontier_json_path else None,
        "catalyst_theme_frontier_markdown_path": str(Path(catalyst_theme_frontier_markdown_path).expanduser().resolve()) if catalyst_theme_frontier_markdown_path else None,
        "score_fail_frontier_markdown_path": score_fail_frontier_summary.get("frontier_markdown_path"),
        "score_fail_recurring_markdown_path": score_fail_frontier_summary.get("recurring_markdown_path"),
        "score_fail_transition_markdown_path": score_fail_frontier_summary.get("transition_markdown_path"),
        "priority_board": priority_board,
        "brief_recommendation": brief.get("recommendation"),
        "brief_summary": brief_summary,
        "catalyst_theme_frontier_summary": _extract_catalyst_theme_frontier_summary(catalyst_theme_frontier),
        "score_fail_frontier_summary": score_fail_frontier_summary,
        "llm_error_digest": dict(session_summary.get("llm_error_digest") or {}),
    }


def _extract_default_merge_review_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("default_merge_review_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_default_merge_review_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_selected_outcome_refresh_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("selected_outcome_refresh_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or REPORTS_DIR).expanduser().resolve()
    refresh_board = _safe_load_json(reports_root / "btst_selected_outcome_refresh_board_latest.json")
    entries = [dict(entry or {}) for entry in list(refresh_board.get("entries") or [])]
    focus_entry = pick_selected_focus_entry(entries)
    if not refresh_board and not focus_entry:
        return {}
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


def _find_focus_entry(entries: list[dict[str, Any]], focus_ticker: Any) -> dict[str, Any]:
    focus_ticker_str = str(focus_ticker or "").strip()
    if focus_ticker_str:
        for entry in entries:
            if str((entry or {}).get("ticker") or "").strip() == focus_ticker_str:
                return dict(entry or {})
    return dict(entries[0] or {}) if entries else {}


def _extract_carryover_multiday_continuation_audit_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("carryover_multiday_continuation_audit_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or REPORTS_DIR).expanduser().resolve()
    audit = _safe_load_json(reports_root / "btst_carryover_multiday_continuation_audit_latest.json")
    if not audit:
        return {}
    policy_checks = dict(audit.get("policy_checks") or {})
    selected_historical = dict(audit.get("selected_historical_proof_summary") or {})
    broad_family_only = dict(audit.get("broad_family_only_summary") or {})
    return {
        "selected_ticker": audit.get("selected_ticker"),
        "selected_trade_date": audit.get("selected_trade_date"),
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


def _extract_carryover_aligned_peer_harvest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("carryover_aligned_peer_harvest_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or REPORTS_DIR).expanduser().resolve()
    harvest = _safe_load_json(reports_root / "btst_carryover_aligned_peer_harvest_latest.json")
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


def _extract_carryover_peer_expansion_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("carryover_peer_expansion_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or REPORTS_DIR).expanduser().resolve()
    expansion = _safe_load_json(reports_root / "btst_carryover_peer_expansion_latest.json")
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


def _extract_carryover_aligned_peer_proof_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("carryover_aligned_peer_proof_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or REPORTS_DIR).expanduser().resolve()
    proof_board = _safe_load_json(reports_root / "btst_carryover_aligned_peer_proof_board_latest.json")
    if not proof_board:
        return {}
    entries = [dict(entry or {}) for entry in list(proof_board.get("entries") or [])]
    focus_entry = _find_focus_entry(entries, proof_board.get("focus_ticker"))
    return {
        "selected_ticker": proof_board.get("selected_ticker"),
        "selected_trade_date": proof_board.get("selected_trade_date"),
        "selected_cycle_status": proof_board.get("selected_cycle_status"),
        "selected_contract_verdict": proof_board.get("selected_contract_verdict"),
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


def _extract_carryover_peer_promotion_gate_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("carryover_peer_promotion_gate_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or REPORTS_DIR).expanduser().resolve()
    promotion_gate = _safe_load_json(reports_root / "btst_carryover_peer_promotion_gate_latest.json")
    if not promotion_gate:
        return {}
    entries = [dict(entry or {}) for entry in list(promotion_gate.get("entries") or [])]
    focus_entry = _find_focus_entry(entries, promotion_gate.get("focus_ticker"))
    return {
        "selected_ticker": promotion_gate.get("selected_ticker"),
        "selected_trade_date": promotion_gate.get("selected_trade_date"),
        "selected_contract_verdict": promotion_gate.get("selected_contract_verdict"),
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


def _extract_default_merge_historical_counterfactual_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("default_merge_historical_counterfactual_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_default_merge_historical_counterfactual_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_continuation_merge_candidate_ranking_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("continuation_merge_candidate_ranking_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_continuation_merge_candidate_ranking_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_default_merge_strict_counterfactual_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("default_merge_strict_counterfactual_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_default_merge_strict_counterfactual_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_merge_replay_validation_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("merge_replay_validation_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_merge_replay_validation_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_prepared_breakout_relief_validation_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("prepared_breakout_relief_validation_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_prepared_breakout_relief_validation_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_prepared_breakout_cohort_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("prepared_breakout_cohort_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_prepared_breakout_cohort_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_prepared_breakout_residual_surface_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("prepared_breakout_residual_surface_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_prepared_breakout_residual_surface_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_candidate_pool_corridor_persistence_dossier_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("candidate_pool_corridor_persistence_dossier_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_candidate_pool_corridor_persistence_dossier_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_candidate_pool_corridor_window_command_board_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("candidate_pool_corridor_window_command_board_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_candidate_pool_corridor_window_command_board_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_candidate_pool_corridor_window_diagnostics_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("candidate_pool_corridor_window_diagnostics_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_candidate_pool_corridor_window_diagnostics_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_candidate_pool_corridor_narrow_probe_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = dict(manifest.get("candidate_pool_corridor_narrow_probe_summary") or {})
    if summary:
        return summary
    entry = _entry_by_id(manifest, "btst_candidate_pool_corridor_narrow_probe_latest")
    if not entry:
        return {}
    return _safe_load_json(entry.get("absolute_path"))


def _extract_control_tower_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    return _extract_control_tower_snapshot_impl(
        manifest,
        extract_snapshot_sections=_extract_control_tower_snapshot_sections,
        extract_overlay_inputs=_extract_upstream_shadow_overlay_inputs,
        build_upstream_shadow_followup_overlay=_build_upstream_shadow_followup_overlay,
        reports_dir=REPORTS_DIR,
    )


def _extract_control_tower_snapshot_sections(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "synthesis": _safe_load_json(dict(manifest.get("btst_governance_synthesis_refresh") or {}).get("output_json")),
        "validation": _safe_load_json(dict(manifest.get("btst_governance_validation_refresh") or {}).get("output_json")),
        "independent_window_monitor": _safe_load_json(dict(manifest.get("btst_independent_window_monitor_refresh") or {}).get("output_json")),
        "tplus1_tplus2_objective_monitor": _safe_load_json(dict(manifest.get("btst_tplus1_tplus2_objective_monitor_refresh") or {}).get("output_json")),
        "tradeable_opportunity_pool": _extract_tradeable_opportunity_pool_summary(manifest),
        "no_candidate_entry_action_board": _extract_no_candidate_entry_action_board_summary(manifest),
        "no_candidate_entry_replay_bundle": _extract_no_candidate_entry_replay_bundle_summary(manifest),
        "no_candidate_entry_failure_dossier": _extract_no_candidate_entry_failure_dossier_summary(manifest),
        "watchlist_recall_dossier": _extract_watchlist_recall_dossier_summary(manifest),
        "candidate_pool_recall_dossier": _extract_candidate_pool_recall_dossier_summary(manifest),
        "selected_outcome_refresh_summary": _extract_selected_outcome_refresh_summary(manifest),
        "carryover_multiday_continuation_audit_summary": _extract_carryover_multiday_continuation_audit_summary(manifest),
        "carryover_aligned_peer_harvest_summary": _extract_carryover_aligned_peer_harvest_summary(manifest),
        "carryover_peer_expansion_summary": _extract_carryover_peer_expansion_summary(manifest),
        "carryover_aligned_peer_proof_summary": _extract_carryover_aligned_peer_proof_summary(manifest),
        "carryover_peer_promotion_gate_summary": _extract_carryover_peer_promotion_gate_summary(manifest),
        "default_merge_review_summary": _extract_default_merge_review_summary(manifest),
        "default_merge_historical_counterfactual_summary": _extract_default_merge_historical_counterfactual_summary(manifest),
        "continuation_merge_candidate_ranking_summary": _extract_continuation_merge_candidate_ranking_summary(manifest),
        "default_merge_strict_counterfactual_summary": _extract_default_merge_strict_counterfactual_summary(manifest),
        "merge_replay_validation_summary": _extract_merge_replay_validation_summary(manifest),
        "prepared_breakout_relief_validation_summary": _extract_prepared_breakout_relief_validation_summary(manifest),
        "prepared_breakout_cohort_summary": _extract_prepared_breakout_cohort_summary(manifest),
        "prepared_breakout_residual_surface_summary": _extract_prepared_breakout_residual_surface_summary(manifest),
        "candidate_pool_corridor_persistence_dossier_summary": _extract_candidate_pool_corridor_persistence_dossier_summary(manifest),
        "candidate_pool_corridor_window_command_board_summary": _extract_candidate_pool_corridor_window_command_board_summary(manifest),
        "candidate_pool_corridor_window_diagnostics_summary": _extract_candidate_pool_corridor_window_diagnostics_summary(manifest),
        "candidate_pool_corridor_narrow_probe_summary": _extract_candidate_pool_corridor_narrow_probe_summary(manifest),
    }


def _extract_upstream_shadow_overlay_inputs(snapshot_sections: dict[str, Any]) -> dict[str, list[Any]]:
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


def _build_recall_priority_task(
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    priority_summary = _extract_priority_summary(latest_btst_snapshot)
    if int(priority_summary.get("primary_count") or 0) > 0:
        return None

    candidate_pool_recall_dossier = dict(control_tower_snapshot.get("candidate_pool_recall_dossier") or {})
    dominant_stage = str(candidate_pool_recall_dossier.get("dominant_stage") or "").strip()
    if not dominant_stage:
        return None

    active_upstream_focus_tickers = list(control_tower_snapshot.get("active_candidate_pool_upstream_handoff_focus_tickers") or [])[:3]
    top_stage_tickers = list(dict(candidate_pool_recall_dossier.get("top_stage_tickers") or {}).get(dominant_stage) or [])[:3]
    focus_tickers = (
        active_upstream_focus_tickers
        if dominant_stage == "candidate_pool_truncated_after_filters" and active_upstream_focus_tickers
        else top_stage_tickers
    )
    priority_handoff_experiment = _resolve_priority_handoff_experiment(
        candidate_pool_recall_dossier=candidate_pool_recall_dossier,
        focus_tickers=focus_tickers,
    )
    frontier_verdict = str(dict(candidate_pool_recall_dossier.get("truncation_frontier_summary") or {}).get("frontier_verdict") or "").strip()
    why_now_parts = [
        "latest BTST still has 0 primary selections",
        f"dominant recall stage={dominant_stage}",
    ]
    if focus_tickers:
        why_now_parts.append(f"focus_tickers={focus_tickers}")
    if frontier_verdict:
        why_now_parts.append(f"frontier_verdict={frontier_verdict}")
    if priority_handoff_experiment:
        why_now_parts.extend(_build_priority_handoff_experiment_why_now_parts(priority_handoff_experiment))

    next_actions = list(candidate_pool_recall_dossier.get("next_actions") or [])
    next_step_default = str(candidate_pool_recall_dossier.get("recommendation") or "").strip() or "review candidate-pool recall dossier and upstream hard-filter stages"
    prioritized_handoff_next_step = None
    if dominant_stage == "candidate_pool_truncated_after_filters" and active_upstream_focus_tickers:
        prioritized_handoff_next_step = (
            f"先补 {active_upstream_focus_tickers} 的 pre-truncation 排名观测与 top300 frontier，"
            "确认它们为何通过 Layer A 过滤后仍在 candidate_pool truncation 被压掉。"
        )
        if priority_handoff_experiment:
            prioritized_handoff_next_step = "；".join(
                [
                    prioritized_handoff_next_step,
                    _build_priority_handoff_experiment_next_step(priority_handoff_experiment),
                ]
            )
        next_step_default = prioritized_handoff_next_step
    elif priority_handoff_experiment:
        next_step_default = _build_priority_handoff_experiment_next_step(priority_handoff_experiment)
    next_step = prioritized_handoff_next_step or next(
        (str(action).strip() for action in next_actions if str(action).strip()),
        next_step_default,
    )
    return {
        "task_id": "candidate_pool_recall_priority",
        "title": (
            "优先修复 Layer A candidate-pool truncation 主链路"
            if dominant_stage == "candidate_pool_truncated_after_filters" and active_upstream_focus_tickers
            else f"优先修复 {dominant_stage} recall 主链路"
        ),
        "why_now": " | ".join(why_now_parts),
        "next_step": str(next_step),
        "source": "candidate_pool_recall_dossier",
    }


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
        "mean_t_plus_2_return",
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
) -> str:
    next_step = str(shadow_summary.get("next_step") or "").strip()
    runbook_suffix = _build_corridor_runbook_suffix(
        focus_ticker=focus_ticker,
        corridor_uplift_runbook_summary=corridor_uplift_runbook_summary,
    )
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
    shadow_status = str(control_tower_snapshot.get("candidate_pool_corridor_shadow_pack_status") or "").strip()
    shadow_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_shadow_pack_summary") or {})
    primary_shadow_replay = _normalize_primary_shadow_replay(shadow_summary.get("primary_shadow_replay"))
    focus_ticker = str(primary_shadow_replay.get("ticker") or "").strip()
    if shadow_status != "ready_for_primary_shadow_replay" or not focus_ticker:
        return None

    why_now_parts = [f"focus_ticker={focus_ticker}", f"shadow_status={shadow_status}"]
    active_absent_from_watchlist_tickers = _collect_control_tower_ticker_set(control_tower_snapshot, "active_no_candidate_entry_absent_from_watchlist_tickers")
    active_absent_from_candidate_pool_tickers = _collect_control_tower_ticker_set(control_tower_snapshot, "active_watchlist_recall_absent_from_candidate_pool_tickers")
    candidate_pool_recall_dominant_stage = str(control_tower_snapshot.get("candidate_pool_recall_dominant_stage") or "").strip()
    focus_liquidity_profile = _find_candidate_pool_focus_liquidity_profile(control_tower_snapshot, focus_ticker)
    corridor_uplift_runbook_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_uplift_runbook_summary") or {})
    _append_primary_shadow_replay_context(why_now_parts, primary_shadow_replay)
    if focus_ticker in active_absent_from_candidate_pool_tickers:
        why_now_parts.append("earliest_breakpoint=absent_from_candidate_pool")
    elif focus_ticker in active_absent_from_watchlist_tickers:
        why_now_parts.append("earliest_breakpoint=absent_from_watchlist")
    _append_truncation_context(
        why_now_parts,
        candidate_pool_recall_dominant_stage=candidate_pool_recall_dominant_stage,
        focus_liquidity_profile=focus_liquidity_profile,
    )
    next_step = _build_corridor_primary_shadow_next_step(
        focus_ticker=focus_ticker,
        shadow_summary=shadow_summary,
        corridor_uplift_runbook_summary=corridor_uplift_runbook_summary,
        candidate_pool_recall_dominant_stage=candidate_pool_recall_dominant_stage,
        focus_liquidity_profile=focus_liquidity_profile,
        active_absent_from_candidate_pool_tickers=active_absent_from_candidate_pool_tickers,
        active_absent_from_watchlist_tickers=active_absent_from_watchlist_tickers,
    )

    return {
        "task_id": "candidate_pool_corridor_primary_shadow_priority",
        "title": f"优先推进 {focus_ticker} corridor primary shadow replay",
        "why_now": " | ".join(why_now_parts),
        "next_step": next_step,
        "source": "candidate_pool_corridor_shadow_replay",
    }


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
    lane_row = next((dict(row or {}) for row in list(control_tower_snapshot.get("rollout_lanes") or []) if row.get("lane_id") == lane_id), {})
    if not lane_row:
        return None

    ticker = str(lane_row.get("ticker") or "").strip()
    if not ticker:
        return None

    lane_status = str(lane_row.get("lane_status") or "").strip()
    blocker = str(lane_row.get("blocker") or "").strip()
    why_now_parts = [fallback_why_now]
    if lane_status:
        why_now_parts.append(f"lane_status={lane_status}")
    if blocker:
        why_now_parts.append(f"blocker={blocker}")

    next_step = str(lane_row.get("next_step") or "").strip()
    if lane_id == "primary_roll_forward":
        priority_summary = _extract_priority_summary(latest_btst_snapshot)
        if int(priority_summary.get("primary_count") or 0) == 0:
            why_now_parts.append("evidence_only_not_current_formal_selected")
            if next_step:
                next_step = f"{next_step}；仅作独立窗口证据补充，不把它包装成当前 formal selected 主票。"
            else:
                next_step = "仅作独立窗口证据补充，不把它包装成当前 formal selected 主票。"

    return {
        "task_id": task_id,
        "title": title_template.format(ticker=ticker),
        "why_now": " | ".join(why_now_parts),
        "next_step": next_step,
        "source": source,
    }


def _extract_carryover_contract_context(control_tower_snapshot: dict[str, Any]) -> dict[str, Any]:
    selected_summary = dict(control_tower_snapshot.get("selected_outcome_refresh_summary") or {})
    audit_summary = dict(control_tower_snapshot.get("carryover_multiday_continuation_audit_summary") or {})
    peer_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_harvest_summary") or {})
    peer_expansion_summary = dict(control_tower_snapshot.get("carryover_peer_expansion_summary") or {})
    peer_proof_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_proof_summary") or {})
    peer_promotion_gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})
    peer_focus_ticker = str(
        peer_promotion_gate_summary.get("focus_ticker")
        or peer_proof_summary.get("focus_ticker")
        or peer_expansion_summary.get("focus_ticker")
        or peer_summary.get("focus_ticker")
        or ""
    ).strip()
    peer_focus_status = str(
        peer_promotion_gate_summary.get("focus_gate_verdict")
        or peer_proof_summary.get("focus_promotion_review_verdict")
        or peer_expansion_summary.get("focus_status")
        or peer_summary.get("focus_status")
        or ""
    ).strip()
    return {
        "audit_summary": audit_summary,
        "formal_selected_ticker": str(selected_summary.get("focus_ticker") or audit_summary.get("selected_ticker") or "").strip(),
        "overall_contract_verdict": str(selected_summary.get("focus_overall_contract_verdict") or "").strip(),
        "selected_preferred_entry_mode": str(audit_summary.get("selected_preferred_entry_mode") or "").strip(),
        "selected_execution_quality_label": str(audit_summary.get("selected_execution_quality_label") or "").strip(),
        "selected_entry_timing_bias": str(audit_summary.get("selected_entry_timing_bias") or "").strip(),
        "peer_focus_ticker": peer_focus_ticker,
        "peer_focus_status": peer_focus_status,
        "peer_proof_focus_ticker": str(peer_proof_summary.get("focus_ticker") or "").strip(),
        "peer_proof_focus_verdict": str(peer_proof_summary.get("focus_promotion_review_verdict") or "").strip(),
        "peer_promotion_gate_focus_ticker": str(peer_promotion_gate_summary.get("focus_ticker") or "").strip(),
        "peer_promotion_gate_focus_verdict": str(peer_promotion_gate_summary.get("focus_gate_verdict") or "").strip(),
        "priority_expansion_tickers": list(peer_expansion_summary.get("priority_expansion_tickers") or []),
        "watch_with_risk_tickers": list(peer_expansion_summary.get("watch_with_risk_tickers") or []),
        "ready_for_promotion_review_tickers": list(peer_proof_summary.get("ready_for_promotion_review_tickers") or []),
        "promotion_gate_ready_tickers": list(peer_promotion_gate_summary.get("ready_tickers") or []),
    }


def _describe_selected_contract_style(*, audit_summary: dict[str, Any]) -> str:
    preferred_entry_mode = str(audit_summary.get("selected_preferred_entry_mode") or "").strip()
    execution_quality_label = str(audit_summary.get("selected_execution_quality_label") or "").strip()
    entry_timing_bias = str(audit_summary.get("selected_entry_timing_bias") or "").strip()
    if preferred_entry_mode == "intraday_confirmation_only" or execution_quality_label in {"intraday_only", "gap_chase_risk"} or entry_timing_bias == "confirm_then_reduce":
        return "intraday confirmation-only"
    if audit_summary.get("selected_path_t2_bias_only"):
        return "confirm-then-hold + T+2 bias"
    return "confirm-then-hold"


def _prioritize_ticker_in_list(tickers: list[Any], prioritized_ticker: str) -> list[str]:
    normalized_prioritized_ticker = str(prioritized_ticker or "").strip()
    ordered = [str(ticker).strip() for ticker in tickers if str(ticker).strip()]
    if normalized_prioritized_ticker and normalized_prioritized_ticker in ordered:
        ordered = [normalized_prioritized_ticker] + [ticker for ticker in ordered if ticker != normalized_prioritized_ticker]
    return ordered


def _build_labeled_why_now_segments(*segments: tuple[Any, str]) -> list[str]:
    labeled_segments: list[str] = []
    for value, label in segments:
        if value:
            labeled_segments.append(f"{label}={value}")
    return labeled_segments


def _build_carryover_contract_why_now_parts(context: dict[str, Any]) -> list[str]:
    audit_summary = dict(context.get("audit_summary") or {})
    why_now_parts = [f"formal_selected={context.get('formal_selected_ticker')}"]
    why_now_parts.extend(
        _build_labeled_why_now_segments(
            (context.get("overall_contract_verdict"), "contract_verdict"),
            (context.get("peer_focus_ticker"), "peer_focus"),
            (context.get("peer_focus_status"), "peer_status"),
            (context.get("peer_proof_focus_ticker"), "peer_proof_focus"),
            (context.get("peer_proof_focus_verdict"), "peer_proof_verdict"),
            (context.get("peer_promotion_gate_focus_ticker"), "peer_gate_focus"),
            (context.get("peer_promotion_gate_focus_verdict"), "peer_gate_verdict"),
        )
    )
    if audit_summary.get("selected_path_t2_bias_only"):
        why_now_parts.append("t_plus_2_bias_only")
    if audit_summary.get("broad_family_only_multiday_unsupported"):
        why_now_parts.append("broad_family_only_not_multiday_ready")
    why_now_parts.extend(
        _build_labeled_why_now_segments(
            (context.get("selected_preferred_entry_mode"), "selected_entry_mode"),
            (context.get("selected_execution_quality_label"), "selected_execution_quality"),
        )
    )
    if context.get("watch_with_risk_tickers"):
        why_now_parts.append(f"watch_with_risk={context.get('watch_with_risk_tickers')}")
    return why_now_parts


def _build_carryover_contract_next_steps(context: dict[str, Any]) -> list[str]:
    audit_summary = dict(context.get("audit_summary") or {})
    formal_selected_ticker = str(context.get("formal_selected_ticker") or "").strip()
    peer_focus_ticker = str(context.get("peer_focus_ticker") or "").strip()
    peer_focus_status = str(context.get("peer_focus_status") or "").strip()
    priority_expansion_tickers = _prioritize_ticker_in_list(list(context.get("priority_expansion_tickers") or []), peer_focus_ticker)
    ready_for_promotion_review_tickers = list(context.get("ready_for_promotion_review_tickers") or [])
    promotion_gate_ready_tickers = list(context.get("promotion_gate_ready_tickers") or [])
    watch_with_risk_tickers = list(context.get("watch_with_risk_tickers") or [])
    contract_style = _describe_selected_contract_style(audit_summary=audit_summary)

    next_steps = [_build_carryover_contract_lead_step(formal_selected_ticker=formal_selected_ticker, contract_style=contract_style)]
    broad_family_step = _build_carryover_contract_broad_family_step(bool(audit_summary.get("broad_family_only_multiday_unsupported")))
    if broad_family_step:
        next_steps.append(broad_family_step)
    peer_focus_step = _build_carryover_contract_peer_focus_step(peer_focus_ticker=peer_focus_ticker, peer_focus_status=peer_focus_status)
    if peer_focus_step:
        next_steps.append(peer_focus_step)
    priority_expansion_step = _build_carryover_contract_priority_expansion_step(priority_expansion_tickers)
    if priority_expansion_step:
        next_steps.append(priority_expansion_step)
    promotion_review_step = _build_carryover_contract_promotion_review_step(ready_for_promotion_review_tickers)
    if promotion_review_step:
        next_steps.append(promotion_review_step)
    promotion_gate_step = _build_carryover_contract_promotion_gate_step(promotion_gate_ready_tickers)
    if promotion_gate_step:
        next_steps.append(promotion_gate_step)
    watch_with_risk_step = _build_carryover_contract_watch_with_risk_step(watch_with_risk_tickers)
    if watch_with_risk_step:
        next_steps.append(watch_with_risk_step)
    return next_steps


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
        "pending_t_plus_2_tickers": [str(ticker) for ticker in list(gate_summary.get("pending_t_plus_2_tickers") or []) if str(ticker).strip()],
        "selected_contract_verdict": str(gate_summary.get("selected_contract_verdict") or "").strip(),
    }


def _build_peer_close_loop_why_now_parts(context: dict[str, Any]) -> list[str]:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    focus_proof_verdict = str(context.get("focus_proof_verdict") or "").strip()
    focus_promotion_review_verdict = str(context.get("focus_promotion_review_verdict") or "").strip()
    focus_gate_verdict = str(context.get("focus_gate_verdict") or "").strip()
    pending_t_plus_2_tickers = list(context.get("pending_t_plus_2_tickers") or [])
    selected_contract_verdict = str(context.get("selected_contract_verdict") or "").strip()
    why_now_parts = [f"focus_ticker={focus_ticker}"]
    if focus_proof_verdict:
        why_now_parts.append(f"focus_proof_verdict={focus_proof_verdict}")
    if focus_promotion_review_verdict:
        why_now_parts.append(f"focus_promotion_review_verdict={focus_promotion_review_verdict}")
    if focus_gate_verdict:
        why_now_parts.append(f"focus_gate_verdict={focus_gate_verdict}")
    if pending_t_plus_2_tickers:
        why_now_parts.append(f"pending_t_plus_2_tickers={pending_t_plus_2_tickers}")
    if selected_contract_verdict:
        why_now_parts.append(f"selected_contract_verdict={selected_contract_verdict}")
    return why_now_parts


def _build_peer_close_loop_next_steps(context: dict[str, Any]) -> list[str]:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    selected_contract_verdict = str(context.get("selected_contract_verdict") or "").strip()
    next_steps = [f"优先盯 {focus_ticker} 的 peer close-loop，等待 T+2 bar 落地后确认是否从 pending_t_plus_2_close 翻到 proof-ready / promotion-review-ready。"]
    safeguard_step = _build_peer_selected_contract_safeguard_step(
        selected_contract_verdict,
        template="同步确认 formal selected contract 仍为 {selected_contract_verdict}，避免主票未闭环时提前把 peer 读成可扩容。",
    )
    if safeguard_step:
        next_steps.append(safeguard_step)
    return next_steps


def _is_pending_peer_close_loop(context: dict[str, Any]) -> bool:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    focus_proof_verdict = str(context.get("focus_proof_verdict") or "").strip()
    focus_promotion_review_verdict = str(context.get("focus_promotion_review_verdict") or "").strip()
    focus_gate_verdict = str(context.get("focus_gate_verdict") or "").strip()
    pending_t_plus_2_tickers = list(context.get("pending_t_plus_2_tickers") or [])
    return bool(
        focus_ticker
        and (
            focus_proof_verdict == "pending_t_plus_2_close"
            or focus_promotion_review_verdict == "await_t_plus_2_close"
            or focus_gate_verdict == "await_peer_t_plus_2_close"
            or focus_ticker in pending_t_plus_2_tickers
        )
    )


def _build_peer_close_loop_monitor_title(context: dict[str, Any]) -> str:
    focus_ticker = str(context.get("focus_ticker") or "").strip()
    return f"优先监控 {focus_ticker} peer close-loop 闭环"


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
    selected_contract_resolution_task = _build_selected_contract_resolution_task(control_tower_snapshot)
    low_urgency_selected_contract_resolution = _is_low_urgency_selected_contract_resolution(control_tower_snapshot)
    prioritized_tasks = [
        _build_selected_contract_monitor_task(control_tower_snapshot),
        _build_gate_ready_priority_task(control_tower_snapshot),
        _build_peer_proof_priority_task(control_tower_snapshot),
        _build_peer_close_loop_monitor_task(control_tower_snapshot),
        _build_carryover_contract_task(control_tower_snapshot),
        _build_candidate_pool_corridor_primary_shadow_task(control_tower_snapshot),
        _build_recall_priority_task(latest_btst_snapshot, control_tower_snapshot),
    ]
    if low_urgency_selected_contract_resolution:
        prioritized_tasks.append(selected_contract_resolution_task)
    else:
        prioritized_tasks.insert(0, selected_contract_resolution_task)
    return prioritized_tasks + [
        _build_lane_priority_task(
            latest_btst_snapshot,
            control_tower_snapshot,
            lane_id="primary_roll_forward",
            task_id="primary_roll_forward_priority",
            title_template="推进 {ticker} primary controlled follow-through",
            fallback_why_now="唯一 primary 主线仍需补独立窗口证据",
            source="rollout_lane_primary",
        ),
        _build_lane_priority_task(
            latest_btst_snapshot,
            control_tower_snapshot,
            lane_id="single_name_shadow",
            task_id="single_name_shadow_priority",
            title_template="保持 {ticker} shadow 单票验证",
            fallback_why_now="shadow 只允许单票低污染验证，不能抢占 primary 主线",
            source="rollout_lane_shadow",
        ),
    ]


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
    prioritized = [task for task in _collect_control_tower_priority_candidates(latest_btst_snapshot, control_tower_snapshot) if task]
    merged_tasks = prioritized + list(control_tower_snapshot.get("next_actions") or [])
    return _dedupe_control_tower_tasks(merged_tasks)[:3]


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
    current_summary = _extract_priority_summary(current_snapshot)
    previous_summary = _extract_priority_summary(previous_summary_source or previous_board)
    current_rows = list(current_snapshot.get("priority_rows") or [])
    previous_rows = list(previous_board.get("priority_rows") or [])
    current_by_ticker = _build_priority_rows_by_ticker(current_rows)
    previous_by_ticker = _build_priority_rows_by_ticker(previous_rows)
    current_ranks = _build_rank_map(current_by_ticker)
    previous_ranks = _build_rank_map(previous_by_ticker)

    added_tickers = _collect_priority_board_membership_changes(current_by_ticker, previous_by_ticker, added=True)
    removed_tickers = _collect_priority_board_membership_changes(current_by_ticker, previous_by_ticker, added=False)
    per_ticker_changes = _collect_priority_board_per_ticker_changes(
        current_by_ticker=current_by_ticker,
        previous_by_ticker=previous_by_ticker,
        current_ranks=current_ranks,
        previous_ranks=previous_ranks,
    )
    current_guardrails = list(current_snapshot.get("global_guardrails") or [])
    previous_guardrails = list(previous_board.get("global_guardrails") or [])
    guardrails_added = [item for item in current_guardrails if item not in previous_guardrails]
    guardrails_removed = [item for item in previous_guardrails if item not in current_guardrails]
    summary_delta = _build_priority_summary_delta(current_summary, previous_summary)
    has_changes = any(
        [
            str(current_snapshot.get("headline") or "") != str(previous_board.get("headline") or ""),
            any(value != 0 for value in summary_delta.values()),
            bool(added_tickers),
            bool(removed_tickers),
            bool(per_ticker_changes["lane_changes"]),
            bool(per_ticker_changes["actionability_changes"]),
            bool(per_ticker_changes["execution_quality_changes"]),
            bool(per_ticker_changes["rank_changes"]),
            bool(per_ticker_changes["score_changes"]),
            bool(guardrails_added),
            bool(guardrails_removed),
        ]
    )
    return {
        "current_headline": current_snapshot.get("headline"),
        "previous_headline": previous_board.get("headline"),
        "headline_changed": str(current_snapshot.get("headline") or "") != str(previous_board.get("headline") or ""),
        "summary_delta": summary_delta,
        "added_tickers": added_tickers,
        "removed_tickers": removed_tickers,
        "lane_changes": per_ticker_changes["lane_changes"],
        "actionability_changes": per_ticker_changes["actionability_changes"],
        "execution_quality_changes": per_ticker_changes["execution_quality_changes"],
        "rank_changes": per_ticker_changes["rank_changes"],
        "score_changes": per_ticker_changes["score_changes"],
        "guardrails_added": guardrails_added,
        "guardrails_removed": guardrails_removed,
        "has_changes": has_changes,
    }


def _build_priority_rows_by_ticker(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("ticker") or ""): dict(row) for row in rows if row.get("ticker")}


def _build_rank_map(rows_by_ticker: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {ticker: index for index, ticker in enumerate(rows_by_ticker, start=1)}


def _collect_priority_board_membership_changes(
    current_by_ticker: dict[str, dict[str, Any]],
    previous_by_ticker: dict[str, dict[str, Any]],
    *,
    added: bool,
) -> list[dict[str, Any]]:
    source_by_ticker = current_by_ticker if added else previous_by_ticker
    target_by_ticker = previous_by_ticker if added else current_by_ticker
    return [
        {
            "ticker": ticker,
            "lane": source_by_ticker[ticker].get("lane"),
            "actionability": source_by_ticker[ticker].get("actionability"),
        }
        for ticker in source_by_ticker
        if ticker not in target_by_ticker
    ]


def _collect_priority_board_per_ticker_changes(
    *,
    current_by_ticker: dict[str, dict[str, Any]],
    previous_by_ticker: dict[str, dict[str, Any]],
    current_ranks: dict[str, int],
    previous_ranks: dict[str, int],
) -> dict[str, list[dict[str, Any]]]:
    lane_changes: list[dict[str, Any]] = []
    actionability_changes: list[dict[str, Any]] = []
    execution_quality_changes: list[dict[str, Any]] = []
    rank_changes: list[dict[str, Any]] = []
    score_changes: list[dict[str, Any]] = []

    for ticker in sorted(set(current_by_ticker).intersection(previous_by_ticker)):
        current_row = current_by_ticker[ticker]
        previous_row = previous_by_ticker[ticker]
        if str(current_row.get("lane") or "") != str(previous_row.get("lane") or ""):
            lane_changes.append(
                {
                    "ticker": ticker,
                    "previous_lane": previous_row.get("lane"),
                    "current_lane": current_row.get("lane"),
                }
            )
        if str(current_row.get("actionability") or "") != str(previous_row.get("actionability") or ""):
            actionability_changes.append(
                {
                    "ticker": ticker,
                    "previous_actionability": previous_row.get("actionability"),
                    "current_actionability": current_row.get("actionability"),
                }
            )
        if str(current_row.get("execution_quality_label") or "") != str(previous_row.get("execution_quality_label") or ""):
            execution_quality_changes.append(
                {
                    "ticker": ticker,
                    "previous_execution_quality_label": previous_row.get("execution_quality_label"),
                    "current_execution_quality_label": current_row.get("execution_quality_label"),
                }
            )
        if current_ranks.get(ticker) != previous_ranks.get(ticker):
            rank_changes.append(
                {
                    "ticker": ticker,
                    "previous_rank": previous_ranks.get(ticker),
                    "current_rank": current_ranks.get(ticker),
                }
            )
        current_score = _as_float(current_row.get("score_target"))
        previous_score = _as_float(previous_row.get("score_target"))
        if current_score is not None and previous_score is not None:
            score_delta = round(current_score - previous_score, 4)
            if score_delta != 0.0:
                score_changes.append(
                    {
                        "ticker": ticker,
                        "previous_score_target": round(previous_score, 4),
                        "current_score_target": round(current_score, 4),
                        "score_target_delta": score_delta,
                    }
                )

    return {
        "lane_changes": lane_changes,
        "actionability_changes": actionability_changes,
        "execution_quality_changes": execution_quality_changes,
        "rank_changes": rank_changes,
        "score_changes": score_changes,
    }


def _build_priority_summary_delta(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, int]:
    return {
        key: int(current_summary.get(key) or 0) - int(previous_summary.get(key) or 0)
        for key in (
            "primary_count",
            "near_miss_count",
            "opportunity_pool_count",
            "research_upside_radar_count",
            "catalyst_theme_count",
            "catalyst_theme_shadow_count",
        )
    }


def _diff_governance(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    if not previous_payload:
        return {
            "available": False,
            "reason": "no_previous_nightly_snapshot",
            "has_changes": False,
        }

    current_control = dict(current_payload.get("control_tower_snapshot") or {})
    previous_control = dict(previous_payload.get("control_tower_snapshot") or {})
    current_lane_matrix = list(dict(current_control.get("synthesis") or {}).get("lane_matrix") or [])
    previous_lane_matrix = list(dict(previous_control.get("synthesis") or {}).get("lane_matrix") or [])
    current_by_lane = _build_governance_lane_map(current_lane_matrix)
    previous_by_lane = _build_governance_lane_map(previous_lane_matrix)
    lane_changes = _collect_governance_lane_changes(current_by_lane, previous_by_lane)
    aggregate_deltas = _build_governance_aggregate_deltas(current_control, previous_control)
    overall_verdict_changed = str(current_control.get("overall_verdict") or "") != str(previous_control.get("overall_verdict") or "")
    has_changes = any(
        [
            bool(lane_changes),
            aggregate_deltas["waiting_lane_count_delta"] != 0,
            aggregate_deltas["ready_lane_count_delta"] != 0,
            aggregate_deltas["warn_count_delta"] != 0,
            aggregate_deltas["fail_count_delta"] != 0,
            overall_verdict_changed,
        ]
    )
    return {
        "available": True,
        "current_overall_verdict": current_control.get("overall_verdict"),
        "previous_overall_verdict": previous_control.get("overall_verdict"),
        "overall_verdict_changed": overall_verdict_changed,
        **aggregate_deltas,
        "lane_changes": lane_changes,
        "changed_lane_count": len(lane_changes),
        "has_changes": has_changes,
    }


def _build_governance_lane_map(lane_matrix: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("lane_id") or ""): dict(row) for row in lane_matrix if row.get("lane_id")}


def _build_governance_lane_delta(
    lane_id: str,
    *,
    current_row: dict[str, Any] | None,
    previous_row: dict[str, Any] | None,
) -> dict[str, Any]:
    if current_row is None or previous_row is None:
        return {
            "lane_id": lane_id,
            "previous_lane_status": (previous_row or {}).get("lane_status"),
            "current_lane_status": (current_row or {}).get("lane_status"),
            "previous_blocker": (previous_row or {}).get("blocker"),
            "current_blocker": (current_row or {}).get("blocker"),
        }
    return {
        "lane_id": lane_id,
        "ticker": current_row.get("ticker") or previous_row.get("ticker"),
        "previous_lane_status": previous_row.get("lane_status"),
        "current_lane_status": current_row.get("lane_status"),
        "previous_blocker": previous_row.get("blocker"),
        "current_blocker": current_row.get("blocker"),
        "previous_validation_verdict": previous_row.get("validation_verdict"),
        "current_validation_verdict": current_row.get("validation_verdict"),
        "previous_missing_window_count": previous_row.get("missing_window_count"),
        "current_missing_window_count": current_row.get("missing_window_count"),
        "previous_upgrade_gap": previous_row.get("upgrade_gap"),
        "current_upgrade_gap": current_row.get("upgrade_gap"),
        "previous_filtered_report_count": previous_row.get("filtered_report_count"),
        "current_filtered_report_count": current_row.get("filtered_report_count"),
        "previous_distinct_window_count_with_filtered_entries": previous_row.get("distinct_window_count_with_filtered_entries"),
        "current_distinct_window_count_with_filtered_entries": current_row.get("distinct_window_count_with_filtered_entries"),
        "previous_preserve_misfire_report_count": previous_row.get("preserve_misfire_report_count"),
        "current_preserve_misfire_report_count": current_row.get("preserve_misfire_report_count"),
    }


def _has_governance_lane_delta_changes(lane_delta: dict[str, Any]) -> bool:
    if "ticker" not in lane_delta:
        return True
    return any(
        lane_delta[key] != lane_delta[key.replace("current_", "previous_")]
        for key in (
            "current_lane_status",
            "current_blocker",
            "current_validation_verdict",
            "current_missing_window_count",
            "current_upgrade_gap",
            "current_filtered_report_count",
            "current_distinct_window_count_with_filtered_entries",
            "current_preserve_misfire_report_count",
        )
    )


def _collect_governance_lane_changes(
    current_by_lane: dict[str, dict[str, Any]],
    previous_by_lane: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    lane_changes: list[dict[str, Any]] = []
    for lane_id in sorted(set(current_by_lane).union(previous_by_lane)):
        lane_delta = _build_governance_lane_delta(
            lane_id,
            current_row=current_by_lane.get(lane_id),
            previous_row=previous_by_lane.get(lane_id),
        )
        if _has_governance_lane_delta_changes(lane_delta):
            lane_changes.append(lane_delta)
    return lane_changes


def _build_governance_aggregate_deltas(current_control: dict[str, Any], previous_control: dict[str, Any]) -> dict[str, int]:
    return {
        "waiting_lane_count_delta": int(current_control.get("waiting_lane_count") or 0) - int(previous_control.get("waiting_lane_count") or 0),
        "ready_lane_count_delta": int(current_control.get("ready_lane_count") or 0) - int(previous_control.get("ready_lane_count") or 0),
        "warn_count_delta": int(current_control.get("warn_count") or 0) - int(previous_control.get("warn_count") or 0),
        "fail_count_delta": int(current_control.get("fail_count") or 0) - int(previous_control.get("fail_count") or 0),
    }


def _diff_replay(
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    current_replay = dict(current_payload.get("replay_cohort_snapshot") or {})
    current_latest_btst = dict(current_payload.get("latest_btst_snapshot") or {})
    if previous_payload:
        previous_replay = dict(previous_payload.get("replay_cohort_snapshot") or {})
        current_selection_target_counts = dict(current_replay.get("selection_target_counts") or {})
        previous_selection_target_counts = dict(previous_replay.get("selection_target_counts") or {})
        current_latest_short_trade_row = dict(current_replay.get("latest_short_trade_row") or {})
        previous_latest_short_trade_row = dict(previous_replay.get("latest_short_trade_row") or {})
        report_count_delta = int(current_replay.get("report_count") or 0) - int(previous_replay.get("report_count") or 0)
        short_trade_only_report_count_delta = int(current_selection_target_counts.get("short_trade_only") or 0) - int(previous_selection_target_counts.get("short_trade_only") or 0)
        dual_target_report_count_delta = int(current_selection_target_counts.get("dual_target") or 0) - int(previous_selection_target_counts.get("dual_target") or 0)
        latest_report_changed = str(current_latest_short_trade_row.get("report_dir_name") or "") != str(previous_latest_short_trade_row.get("report_dir_name") or "")
        latest_near_miss_delta = int(current_latest_short_trade_row.get("near_miss_count") or 0) - int(previous_latest_short_trade_row.get("near_miss_count") or 0)
        latest_opportunity_delta = int(current_latest_short_trade_row.get("opportunity_pool_count") or 0) - int(previous_latest_short_trade_row.get("opportunity_pool_count") or 0)
        has_changes = any([report_count_delta != 0, short_trade_only_report_count_delta != 0, dual_target_report_count_delta != 0, latest_report_changed, latest_near_miss_delta != 0, latest_opportunity_delta != 0])
        return {
            "available": True,
            "comparison_basis": "nightly_history",
            "report_count_delta": report_count_delta,
            "short_trade_only_report_count_delta": short_trade_only_report_count_delta,
            "dual_target_report_count_delta": dual_target_report_count_delta,
            "previous_latest_short_trade_report": previous_latest_short_trade_row.get("report_dir_name"),
            "current_latest_short_trade_report": current_latest_short_trade_row.get("report_dir_name"),
            "latest_short_trade_report_changed": latest_report_changed,
            "latest_near_miss_delta": latest_near_miss_delta,
            "latest_opportunity_pool_delta": latest_opportunity_delta,
            "has_changes": has_changes,
        }

    if previous_report_snapshot:
        previous_summary = _extract_priority_summary(previous_report_snapshot.get("brief_summary") or {})
        current_summary = _extract_priority_summary(current_latest_btst.get("brief_summary") or {})
        summary_delta = {
            key: int(current_summary.get(key) or 0) - int(previous_summary.get(key) or 0)
            for key in ("primary_count", "near_miss_count", "opportunity_pool_count", "research_upside_radar_count", "catalyst_theme_count", "catalyst_theme_shadow_count")
        }
        has_changes = any(value != 0 for value in summary_delta.values()) or str(previous_report_snapshot.get("report_dir") or "") != str(current_payload.get("latest_btst_run", {}).get("report_dir") or "")
        return {
            "available": True,
            "comparison_basis": "previous_btst_report",
            "previous_report_dir": previous_report_snapshot.get("report_dir"),
            "current_report_dir": dict(current_payload.get("latest_btst_run") or {}).get("report_dir"),
            "summary_delta": summary_delta,
            "has_changes": has_changes,
        }

    return {
        "available": False,
        "comparison_basis": "none",
        "has_changes": False,
    }


def _diff_catalyst_frontier(
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    current_summary = dict(dict(current_payload.get("latest_btst_snapshot") or {}).get("catalyst_theme_frontier_summary") or {})
    previous_summary, comparison_basis = _resolve_catalyst_frontier_previous_summary(previous_payload, previous_report_snapshot)
    if comparison_basis is None:
        return {
            "available": False,
            "comparison_basis": "none",
            "has_changes": False,
        }

    current_promoted_tickers = list(current_summary.get("recommended_promoted_tickers") or [])
    previous_promoted_tickers = list(previous_summary.get("recommended_promoted_tickers") or [])
    promoted_ticker_delta = _diff_ticker_lists(current_promoted_tickers, previous_promoted_tickers)
    count_deltas = _build_catalyst_frontier_count_deltas(current_summary, previous_summary)
    status_changed = str(current_summary.get("status") or "") != str(previous_summary.get("status") or "")
    recommended_variant_changed = str(current_summary.get("recommended_variant_name") or "") != str(previous_summary.get("recommended_variant_name") or "")
    previous_data_available = bool(previous_summary)
    comparison_note = None
    if not previous_data_available and current_summary:
        if comparison_basis == "nightly_history":
            comparison_note = "上一版 nightly 快照尚未记录题材催化前沿摘要，本轮是首个可比较的前沿暴露。"
        else:
            comparison_note = "上一份 BTST 报告尚未记录题材催化前沿摘要，本轮是首个可比较的前沿暴露。"
    has_changes = any(
        [
            status_changed,
            recommended_variant_changed,
            any(value != 0 for value in count_deltas.values()),
            bool(promoted_ticker_delta["added"]),
            bool(promoted_ticker_delta["removed"]),
        ]
    )
    return {
        "available": True,
        "comparison_basis": comparison_basis,
        "previous_status": previous_summary.get("status"),
        "current_status": current_summary.get("status"),
        "previous_data_available": previous_data_available,
        "comparison_note": comparison_note,
        "status_changed": status_changed,
        "previous_recommended_variant_name": previous_summary.get("recommended_variant_name"),
        "current_recommended_variant_name": current_summary.get("recommended_variant_name"),
        "recommended_variant_changed": recommended_variant_changed,
        "previous_promoted_tickers": previous_promoted_tickers,
        "current_promoted_tickers": current_promoted_tickers,
        "added_promoted_tickers": promoted_ticker_delta["added"],
        "removed_promoted_tickers": promoted_ticker_delta["removed"],
        **count_deltas,
        "previous_recommendation": previous_summary.get("recommendation"),
        "current_recommendation": current_summary.get("recommendation"),
        "has_changes": has_changes,
    }


def _resolve_catalyst_frontier_previous_summary(
    previous_payload: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    if previous_payload:
        return (
            dict(dict(previous_payload.get("latest_btst_snapshot") or {}).get("catalyst_theme_frontier_summary") or {}),
            "nightly_history",
        )
    if previous_report_snapshot:
        return (
            dict(previous_report_snapshot.get("catalyst_theme_frontier_summary") or {}),
            "previous_btst_report",
        )
    return {}, None


def _build_catalyst_frontier_count_deltas(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, int]:
    return {
        "promoted_shadow_count_delta": int(current_summary.get("recommended_promoted_shadow_count") or 0)
        - int(previous_summary.get("recommended_promoted_shadow_count") or 0),
        "shadow_candidate_count_delta": int(current_summary.get("shadow_candidate_count") or 0) - int(previous_summary.get("shadow_candidate_count") or 0),
        "baseline_selected_count_delta": int(current_summary.get("baseline_selected_count") or 0) - int(previous_summary.get("baseline_selected_count") or 0),
    }


def _diff_score_fail_frontier(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    if not previous_payload:
        return {
            "available": False,
            "reason": "no_previous_nightly_snapshot",
            "has_changes": False,
        }

    current_summary, previous_summary = _extract_score_fail_frontier_summaries(current_payload, previous_payload)
    if not current_summary and not previous_summary:
        return {
            "available": False,
            "reason": "no_score_fail_frontier_summary",
            "has_changes": False,
        }

    current_priority_queue_tickers = list(current_summary.get("priority_queue_tickers") or [])
    previous_priority_queue_tickers = list(previous_summary.get("priority_queue_tickers") or [])
    current_top_rescue_tickers = list(current_summary.get("top_rescue_tickers") or [])
    previous_top_rescue_tickers = list(previous_summary.get("top_rescue_tickers") or [])
    priority_queue_delta = _diff_ticker_lists(current_priority_queue_tickers, previous_priority_queue_tickers)
    top_rescue_delta = _diff_ticker_lists(current_top_rescue_tickers, previous_top_rescue_tickers)
    count_deltas = _build_score_fail_frontier_count_deltas(current_summary, previous_summary)
    status_changed = str(current_summary.get("status") or "") != str(previous_summary.get("status") or "")
    previous_data_available = bool(previous_summary)
    comparison_note = None
    if not previous_data_available and current_summary:
        comparison_note = "上一版 nightly 快照尚未记录 score-fail frontier 摘要，本轮是首个可比较的 frontier queue 暴露。"

    has_changes = any(
        [
            status_changed,
            any(value != 0 for value in count_deltas.values()),
            bool(priority_queue_delta["added"]),
            bool(priority_queue_delta["removed"]),
            bool(top_rescue_delta["added"]),
            bool(top_rescue_delta["removed"]),
        ]
    )
    return {
        "available": True,
        "previous_data_available": previous_data_available,
        "comparison_note": comparison_note,
        "previous_status": previous_summary.get("status"),
        "current_status": current_summary.get("status"),
        "status_changed": status_changed,
        **count_deltas,
        "previous_priority_queue_tickers": previous_priority_queue_tickers,
        "current_priority_queue_tickers": current_priority_queue_tickers,
        "added_priority_tickers": priority_queue_delta["added"],
        "removed_priority_tickers": priority_queue_delta["removed"],
        "previous_top_rescue_tickers": previous_top_rescue_tickers,
        "current_top_rescue_tickers": current_top_rescue_tickers,
        "added_top_rescue_tickers": top_rescue_delta["added"],
        "removed_top_rescue_tickers": top_rescue_delta["removed"],
        "has_changes": has_changes,
    }


def _extract_score_fail_frontier_summaries(
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        dict(dict(current_payload.get("latest_btst_snapshot") or {}).get("score_fail_frontier_summary") or {}),
        dict(dict(previous_payload.get("latest_btst_snapshot") or {}).get("score_fail_frontier_summary") or {}),
    )


def _diff_ticker_lists(current_tickers: list[Any], previous_tickers: list[Any]) -> dict[str, list[Any]]:
    return {
        "added": [ticker for ticker in current_tickers if ticker not in previous_tickers],
        "removed": [ticker for ticker in previous_tickers if ticker not in current_tickers],
    }


def _build_score_fail_frontier_count_deltas(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, int]:
    return {
        "rejected_case_count_delta": int(current_summary.get("rejected_short_trade_boundary_count") or 0)
        - int(previous_summary.get("rejected_short_trade_boundary_count") or 0),
        "rescueable_case_count_delta": int(current_summary.get("rescueable_case_count") or 0) - int(previous_summary.get("rescueable_case_count") or 0),
        "threshold_only_rescue_count_delta": int(current_summary.get("threshold_only_rescue_count") or 0)
        - int(previous_summary.get("threshold_only_rescue_count") or 0),
        "recurring_case_count_delta": int(current_summary.get("recurring_case_count") or 0) - int(previous_summary.get("recurring_case_count") or 0),
        "transition_candidate_count_delta": int(current_summary.get("transition_candidate_count") or 0)
        - int(previous_summary.get("transition_candidate_count") or 0),
    }


def _diff_carryover_promotion_gate(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    if not previous_payload:
        return {
            "available": False,
            "reason": "no_previous_nightly_snapshot",
            "has_changes": False,
        }

    current_summary = dict(dict(current_payload.get("control_tower_snapshot") or {}).get("carryover_peer_promotion_gate_summary") or {})
    previous_summary = dict(dict(previous_payload.get("control_tower_snapshot") or {}).get("carryover_peer_promotion_gate_summary") or {})
    if not current_summary and not previous_summary:
        return {
            "available": False,
            "reason": "no_carryover_peer_promotion_gate_summary",
            "has_changes": False,
        }

    current_ready_tickers = list(current_summary.get("ready_tickers") or [])
    previous_ready_tickers = list(previous_summary.get("ready_tickers") or [])
    current_blocked_open_tickers = list(current_summary.get("blocked_open_tickers") or [])
    previous_blocked_open_tickers = list(previous_summary.get("blocked_open_tickers") or [])
    current_pending_t_plus_2_tickers = list(current_summary.get("pending_t_plus_2_tickers") or [])
    previous_pending_t_plus_2_tickers = list(previous_summary.get("pending_t_plus_2_tickers") or [])
    ready_ticker_delta = _diff_ticker_lists(current_ready_tickers, previous_ready_tickers)
    blocked_open_ticker_delta = _diff_ticker_lists(current_blocked_open_tickers, previous_blocked_open_tickers)
    pending_t_plus_2_ticker_delta = _diff_ticker_lists(current_pending_t_plus_2_tickers, previous_pending_t_plus_2_tickers)
    field_changes = _build_carryover_promotion_gate_field_changes(current_summary, previous_summary)
    has_changes = any(
        [
            field_changes["focus_ticker_changed"],
            field_changes["focus_gate_verdict_changed"],
            field_changes["selected_contract_verdict_changed"],
            bool(ready_ticker_delta["added"]),
            bool(ready_ticker_delta["removed"]),
            bool(blocked_open_ticker_delta["added"]),
            bool(blocked_open_ticker_delta["removed"]),
            bool(pending_t_plus_2_ticker_delta["added"]),
            bool(pending_t_plus_2_ticker_delta["removed"]),
        ]
    )
    return {
        "available": True,
        "previous_focus_ticker": previous_summary.get("focus_ticker"),
        "current_focus_ticker": current_summary.get("focus_ticker"),
        "focus_ticker_changed": field_changes["focus_ticker_changed"],
        "previous_focus_gate_verdict": previous_summary.get("focus_gate_verdict"),
        "current_focus_gate_verdict": current_summary.get("focus_gate_verdict"),
        "focus_gate_verdict_changed": field_changes["focus_gate_verdict_changed"],
        "previous_selected_contract_verdict": previous_summary.get("selected_contract_verdict"),
        "current_selected_contract_verdict": current_summary.get("selected_contract_verdict"),
        "selected_contract_verdict_changed": field_changes["selected_contract_verdict_changed"],
        "previous_ready_tickers": previous_ready_tickers,
        "current_ready_tickers": current_ready_tickers,
        "added_ready_tickers": ready_ticker_delta["added"],
        "removed_ready_tickers": ready_ticker_delta["removed"],
        "previous_blocked_open_tickers": previous_blocked_open_tickers,
        "current_blocked_open_tickers": current_blocked_open_tickers,
        "added_blocked_open_tickers": blocked_open_ticker_delta["added"],
        "removed_blocked_open_tickers": blocked_open_ticker_delta["removed"],
        "previous_pending_t_plus_2_tickers": previous_pending_t_plus_2_tickers,
        "current_pending_t_plus_2_tickers": current_pending_t_plus_2_tickers,
        "added_pending_t_plus_2_tickers": pending_t_plus_2_ticker_delta["added"],
        "removed_pending_t_plus_2_tickers": pending_t_plus_2_ticker_delta["removed"],
        "has_changes": has_changes,
    }


def _build_carryover_promotion_gate_field_changes(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, bool]:
    return {
        "focus_ticker_changed": str(current_summary.get("focus_ticker") or "") != str(previous_summary.get("focus_ticker") or ""),
        "focus_gate_verdict_changed": str(current_summary.get("focus_gate_verdict") or "") != str(previous_summary.get("focus_gate_verdict") or ""),
        "selected_contract_verdict_changed": str(current_summary.get("selected_contract_verdict") or "")
        != str(previous_summary.get("selected_contract_verdict") or ""),
    }


def _diff_top_priority_action(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    if not previous_payload:
        return {
            "available": False,
            "reason": "no_previous_nightly_snapshot",
            "has_changes": False,
        }

    current_actions = list(dict(current_payload.get("control_tower_snapshot") or {}).get("next_actions") or [])
    previous_actions = list(dict(previous_payload.get("control_tower_snapshot") or {}).get("next_actions") or [])
    current_top = dict(current_actions[0] or {}) if current_actions else {}
    previous_top = dict(previous_actions[0] or {}) if previous_actions else {}
    if not current_top and not previous_top:
        return {
            "available": False,
            "reason": "no_next_actions",
            "has_changes": False,
        }

    task_id_changed = str(current_top.get("task_id") or "") != str(previous_top.get("task_id") or "")
    source_changed = str(current_top.get("source") or "") != str(previous_top.get("source") or "")
    title_changed = str(current_top.get("title") or "") != str(previous_top.get("title") or "")
    has_changes = task_id_changed or source_changed or title_changed
    return {
        "available": True,
        "previous_task_id": previous_top.get("task_id"),
        "current_task_id": current_top.get("task_id"),
        "task_id_changed": task_id_changed,
        "previous_source": previous_top.get("source"),
        "current_source": current_top.get("source"),
        "source_changed": source_changed,
        "previous_title": previous_top.get("title"),
        "current_title": current_top.get("title"),
        "title_changed": title_changed,
        "has_changes": has_changes,
    }


def _diff_selected_outcome_contract(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    if not previous_payload:
        return {
            "available": False,
            "reason": "no_previous_nightly_snapshot",
            "has_changes": False,
        }

    current_summary = dict(dict(current_payload.get("control_tower_snapshot") or {}).get("selected_outcome_refresh_summary") or {})
    previous_summary = dict(dict(previous_payload.get("control_tower_snapshot") or {}).get("selected_outcome_refresh_summary") or {})
    if not current_summary and not previous_summary:
        return {
            "available": False,
            "reason": "no_selected_outcome_refresh_summary",
            "has_changes": False,
        }

    focus_ticker_changed = str(current_summary.get("focus_ticker") or "") != str(previous_summary.get("focus_ticker") or "")
    focus_cycle_status_changed = str(current_summary.get("focus_cycle_status") or "") != str(previous_summary.get("focus_cycle_status") or "")
    overall_contract_verdict_changed = str(current_summary.get("focus_overall_contract_verdict") or "") != str(previous_summary.get("focus_overall_contract_verdict") or "")
    next_day_contract_verdict_changed = str(current_summary.get("focus_next_day_contract_verdict") or "") != str(previous_summary.get("focus_next_day_contract_verdict") or "")
    t_plus_2_contract_verdict_changed = str(current_summary.get("focus_t_plus_2_contract_verdict") or "") != str(previous_summary.get("focus_t_plus_2_contract_verdict") or "")
    has_changes = any(
        [
            focus_ticker_changed,
            focus_cycle_status_changed,
            overall_contract_verdict_changed,
            next_day_contract_verdict_changed,
            t_plus_2_contract_verdict_changed,
        ]
    )
    return {
        "available": True,
        "previous_focus_ticker": previous_summary.get("focus_ticker"),
        "current_focus_ticker": current_summary.get("focus_ticker"),
        "focus_ticker_changed": focus_ticker_changed,
        "previous_focus_cycle_status": previous_summary.get("focus_cycle_status"),
        "current_focus_cycle_status": current_summary.get("focus_cycle_status"),
        "focus_cycle_status_changed": focus_cycle_status_changed,
        "previous_focus_overall_contract_verdict": previous_summary.get("focus_overall_contract_verdict"),
        "current_focus_overall_contract_verdict": current_summary.get("focus_overall_contract_verdict"),
        "focus_overall_contract_verdict_changed": overall_contract_verdict_changed,
        "previous_focus_next_day_contract_verdict": previous_summary.get("focus_next_day_contract_verdict"),
        "current_focus_next_day_contract_verdict": current_summary.get("focus_next_day_contract_verdict"),
        "focus_next_day_contract_verdict_changed": next_day_contract_verdict_changed,
        "previous_focus_t_plus_2_contract_verdict": previous_summary.get("focus_t_plus_2_contract_verdict"),
        "current_focus_t_plus_2_contract_verdict": current_summary.get("focus_t_plus_2_contract_verdict"),
        "focus_t_plus_2_contract_verdict_changed": t_plus_2_contract_verdict_changed,
        "has_changes": has_changes,
    }


def _diff_carryover_peer_proof(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    if not previous_payload:
        return {
            "available": False,
            "reason": "no_previous_nightly_snapshot",
            "has_changes": False,
        }

    current_summary = dict(dict(current_payload.get("control_tower_snapshot") or {}).get("carryover_aligned_peer_proof_summary") or {})
    previous_summary = dict(dict(previous_payload.get("control_tower_snapshot") or {}).get("carryover_aligned_peer_proof_summary") or {})
    if not current_summary and not previous_summary:
        return {
            "available": False,
            "reason": "no_carryover_aligned_peer_proof_summary",
            "has_changes": False,
        }

    current_ready_tickers = list(current_summary.get("ready_for_promotion_review_tickers") or [])
    previous_ready_tickers = list(previous_summary.get("ready_for_promotion_review_tickers") or [])
    current_risk_review_tickers = list(current_summary.get("risk_review_tickers") or [])
    previous_risk_review_tickers = list(previous_summary.get("risk_review_tickers") or [])
    added_ready_tickers = [ticker for ticker in current_ready_tickers if ticker not in previous_ready_tickers]
    removed_ready_tickers = [ticker for ticker in previous_ready_tickers if ticker not in current_ready_tickers]
    added_risk_review_tickers = [ticker for ticker in current_risk_review_tickers if ticker not in previous_risk_review_tickers]
    removed_risk_review_tickers = [ticker for ticker in previous_risk_review_tickers if ticker not in current_risk_review_tickers]
    focus_ticker_changed = str(current_summary.get("focus_ticker") or "") != str(previous_summary.get("focus_ticker") or "")
    focus_proof_verdict_changed = str(current_summary.get("focus_proof_verdict") or "") != str(previous_summary.get("focus_proof_verdict") or "")
    focus_promotion_review_verdict_changed = str(current_summary.get("focus_promotion_review_verdict") or "") != str(previous_summary.get("focus_promotion_review_verdict") or "")
    has_changes = any(
        [
            focus_ticker_changed,
            focus_proof_verdict_changed,
            focus_promotion_review_verdict_changed,
            bool(added_ready_tickers),
            bool(removed_ready_tickers),
            bool(added_risk_review_tickers),
            bool(removed_risk_review_tickers),
        ]
    )
    return {
        "available": True,
        "previous_focus_ticker": previous_summary.get("focus_ticker"),
        "current_focus_ticker": current_summary.get("focus_ticker"),
        "focus_ticker_changed": focus_ticker_changed,
        "previous_focus_proof_verdict": previous_summary.get("focus_proof_verdict"),
        "current_focus_proof_verdict": current_summary.get("focus_proof_verdict"),
        "focus_proof_verdict_changed": focus_proof_verdict_changed,
        "previous_focus_promotion_review_verdict": previous_summary.get("focus_promotion_review_verdict"),
        "current_focus_promotion_review_verdict": current_summary.get("focus_promotion_review_verdict"),
        "focus_promotion_review_verdict_changed": focus_promotion_review_verdict_changed,
        "previous_ready_for_promotion_review_tickers": previous_ready_tickers,
        "current_ready_for_promotion_review_tickers": current_ready_tickers,
        "added_ready_for_promotion_review_tickers": added_ready_tickers,
        "removed_ready_for_promotion_review_tickers": removed_ready_tickers,
        "previous_risk_review_tickers": previous_risk_review_tickers,
        "current_risk_review_tickers": current_risk_review_tickers,
        "added_risk_review_tickers": added_risk_review_tickers,
        "removed_risk_review_tickers": removed_risk_review_tickers,
        "has_changes": has_changes,
    }


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
    skipped_snapshot_count = 0
    for candidate_payload, candidate_path in historical_payload_candidates:
        anchor_delta = build_btst_open_ready_delta_payload(
            current_payload,
            reports_root=reports_root,
            current_nightly_json_path=current_nightly_json_path,
            previous_payload=candidate_payload,
            previous_payload_path=candidate_path,
            historical_payload_candidates=None,
            enable_material_anchor=False,
        )
        changed_sections = _list_changed_delta_sections(anchor_delta)
        if not changed_sections and anchor_delta.get("comparison_scope") == "same_report_rerun" and anchor_delta.get("overall_delta_verdict") == "stable":
            skipped_snapshot_count += 1
            continue
        return {
            "reference_generated_at": candidate_payload.get("generated_at"),
            "reference_report_dir": dict(candidate_payload.get("latest_btst_run") or {}).get("report_dir"),
            "reference_snapshot_path": candidate_path,
            "comparison_basis": anchor_delta.get("comparison_basis"),
            "comparison_scope": anchor_delta.get("comparison_scope"),
            "overall_delta_verdict": anchor_delta.get("overall_delta_verdict"),
            "changed_sections": changed_sections,
            "operator_focus": list(anchor_delta.get("operator_focus") or [])[:4],
            "skipped_snapshot_count": skipped_snapshot_count,
        }
    return {}


def _resolve_open_ready_previous_context(
    *,
    latest_btst_run: dict[str, Any],
    previous_payload: dict[str, Any],
    reports_root: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    previous_report_snapshot = {} if previous_payload else _select_previous_btst_report_snapshot(
        reports_root,
        current_report_dir=latest_btst_run.get("report_dir_abs"),
        selection_target=latest_btst_run.get("selection_target"),
    )
    if previous_payload:
        previous_priority_board = dict(previous_payload.get("latest_priority_board_snapshot") or {})
        previous_reference = dict(previous_payload.get("latest_btst_run") or {})
        previous_reference["generated_at"] = previous_payload.get("generated_at")
        previous_reference["reference_kind"] = "nightly_history"
        return previous_report_snapshot, previous_priority_board, "nightly_history", previous_reference
    if previous_report_snapshot:
        return (
            previous_report_snapshot,
            dict(previous_report_snapshot.get("priority_board") or {}),
            "previous_btst_report",
            {
                "report_dir": previous_report_snapshot.get("report_dir"),
                "report_dir_abs": previous_report_snapshot.get("report_dir_abs"),
                "selection_target": previous_report_snapshot.get("selection_target"),
                "trade_date": previous_report_snapshot.get("trade_date"),
                "next_trade_date": previous_report_snapshot.get("next_trade_date"),
                "generated_at": None,
                "reference_kind": "previous_btst_report",
            },
        )
    return previous_report_snapshot, {}, "baseline_captured", {}


def _resolve_open_ready_comparison_scope(comparison_basis: str, previous_reference: dict[str, Any], latest_btst_run: dict[str, Any]) -> str:
    if comparison_basis == "nightly_history":
        if str(previous_reference.get("report_dir") or "") == str(latest_btst_run.get("report_dir") or ""):
            return "same_report_rerun"
        return "report_rollforward"
    if comparison_basis == "previous_btst_report":
        return "previous_btst_report"
    return "baseline_captured"


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
    if comparison_basis == "baseline_captured":
        operator_focus.append("首个 open-ready delta 基线已捕获；下一轮 nightly 后将开始提供完整 lane / replay 差分。")
    elif comparison_basis == "previous_btst_report":
        operator_focus.append("当前已生成 report 级 delta；完整治理 lane 差分将在下一轮 nightly 历史快照后可用。")
    elif comparison_scope == "same_report_rerun":
        operator_focus.append("当前 delta 对比的是同一份 report 的上一版 nightly 快照，用于识别复刷变化，而不是跨 report 切换。")


def _append_open_ready_priority_focus(operator_focus: list[str], priority_delta: dict[str, Any]) -> None:
    if priority_delta.get("headline_changed"):
        operator_focus.append(f"开盘 headline 已变化：{priority_delta.get('previous_headline') or 'n/a'} -> {priority_delta.get('current_headline') or 'n/a'}")
    if priority_delta.get("added_tickers"):
        operator_focus.append("新增观察对象: " + ", ".join(item.get("ticker") or "" for item in priority_delta.get("added_tickers") or []))
    if priority_delta.get("removed_tickers"):
        operator_focus.append("移出观察对象: " + ", ".join(item.get("ticker") or "" for item in priority_delta.get("removed_tickers") or []))


def _append_open_ready_governance_focus(operator_focus: list[str], governance_delta: dict[str, Any]) -> None:
    if governance_delta.get("available") and governance_delta.get("changed_lane_count"):
        operator_focus.append("治理 lane 发生变化: " + ", ".join(change.get("lane_id") or "" for change in governance_delta.get("lane_changes") or []))


def _append_open_ready_replay_focus(operator_focus: list[str], replay_delta: dict[str, Any]) -> None:
    if not (replay_delta.get("available") and replay_delta.get("has_changes")):
        return
    if replay_delta.get("comparison_basis") == "nightly_history":
        operator_focus.append(
            f"replay cohort 变化: report_count {replay_delta.get('report_count_delta'):+d}, short_trade_only {replay_delta.get('short_trade_only_report_count_delta'):+d}。"
        )
        return
    if replay_delta.get("comparison_basis") == "previous_btst_report":
        summary_delta = dict(replay_delta.get("summary_delta") or {})
        operator_focus.append("本轮相对上一份 BTST 报告的观察层变化: " + ", ".join(f"{key} {int(value):+d}" for key, value in summary_delta.items() if int(value) != 0))


def _append_open_ready_frontier_focus(operator_focus: list[str], delta: dict[str, Any], *, label: str, added_key: str, status_label: str) -> None:
    if not (delta.get("available") and delta.get("has_changes")):
        return
    added_values = list(delta.get(added_key) or [])
    if added_values:
        operator_focus.append(f"{label}: " + ", ".join(added_values))
        return
    if delta.get("status_changed"):
        operator_focus.append(f"{status_label}: {delta.get('previous_status') or 'n/a'} -> {delta.get('current_status') or 'n/a'}。")
        return
    if delta.get("comparison_note"):
        operator_focus.append(str(delta.get("comparison_note")))


def _append_open_ready_action_focus(operator_focus: list[str], delta_sections: dict[str, Any]) -> None:
    top_priority_action_delta = dict(delta_sections.get("top_priority_action_delta") or {})
    selected_outcome_contract_delta = dict(delta_sections.get("selected_outcome_contract_delta") or {})
    carryover_peer_proof_delta = dict(delta_sections.get("carryover_peer_proof_delta") or {})
    carryover_promotion_gate_delta = dict(delta_sections.get("carryover_promotion_gate_delta") or {})
    if top_priority_action_delta.get("available") and top_priority_action_delta.get("has_changes"):
        operator_focus.append(
            f"control tower 顶级动作切换: {top_priority_action_delta.get('previous_source') or 'n/a'} -> {top_priority_action_delta.get('current_source') or 'n/a'} "
            f"({top_priority_action_delta.get('previous_title') or 'n/a'} -> {top_priority_action_delta.get('current_title') or 'n/a'})."
        )
    if selected_outcome_contract_delta.get("available") and selected_outcome_contract_delta.get("has_changes"):
        operator_focus.append(
            f"selected contract 变化: {selected_outcome_contract_delta.get('previous_focus_ticker') or 'n/a'} / "
            f"{selected_outcome_contract_delta.get('previous_focus_overall_contract_verdict') or 'n/a'} -> "
            f"{selected_outcome_contract_delta.get('current_focus_ticker') or 'n/a'} / "
            f"{selected_outcome_contract_delta.get('current_focus_overall_contract_verdict') or 'n/a'}。"
        )
    if carryover_peer_proof_delta.get("available") and carryover_peer_proof_delta.get("has_changes"):
        operator_focus.append(
            f"carryover peer proof 变化: focus {carryover_peer_proof_delta.get('previous_focus_ticker') or 'n/a'} -> {carryover_peer_proof_delta.get('current_focus_ticker') or 'n/a'}, "
            f"promotion review {carryover_peer_proof_delta.get('previous_focus_promotion_review_verdict') or 'n/a'} -> {carryover_peer_proof_delta.get('current_focus_promotion_review_verdict') or 'n/a'}。"
        )
    if carryover_promotion_gate_delta.get("available") and carryover_promotion_gate_delta.get("has_changes"):
        operator_focus.append(
            f"carryover promotion gate 变化: focus {carryover_promotion_gate_delta.get('previous_focus_ticker') or 'n/a'} -> {carryover_promotion_gate_delta.get('current_focus_ticker') or 'n/a'}, "
            f"verdict {carryover_promotion_gate_delta.get('previous_focus_gate_verdict') or 'n/a'} -> {carryover_promotion_gate_delta.get('current_focus_gate_verdict') or 'n/a'}。"
        )


def _append_open_ready_score_fail_focus(operator_focus: list[str], score_fail_delta: dict[str, Any]) -> None:
    if not (score_fail_delta.get("available") and score_fail_delta.get("has_changes") and not score_fail_delta.get("added_priority_tickers")):
        return
    if score_fail_delta.get("added_top_rescue_tickers"):
        operator_focus.append("score-fail frontier 新增 near-miss rescue 票: " + ", ".join(score_fail_delta.get("added_top_rescue_tickers") or []))
    elif score_fail_delta.get("comparison_note") and not score_fail_delta.get("status_changed"):
        operator_focus.append(str(score_fail_delta.get("comparison_note")))


def _append_open_ready_stability_focus(operator_focus: list[str]) -> None:
    if not operator_focus:
        operator_focus.append(
            "本轮相对上一轮没有检测到 priority / governance / replay / score-fail frontier / top priority action / selected contract / carryover peer proof / carryover promotion gate 的结构变化，可视为稳定复跑。"
        )


def _build_open_ready_operator_focus(comparison_basis: str, comparison_scope: str, delta_sections: dict[str, Any]) -> list[str]:
    operator_focus: list[str] = []
    _append_open_ready_basis_focus(operator_focus, comparison_basis, comparison_scope)
    _append_open_ready_priority_focus(operator_focus, dict(delta_sections.get("priority_delta") or {}))
    _append_open_ready_governance_focus(operator_focus, dict(delta_sections.get("governance_delta") or {}))
    _append_open_ready_replay_focus(operator_focus, dict(delta_sections.get("replay_delta") or {}))
    _append_open_ready_frontier_focus(
        operator_focus,
        dict(delta_sections.get("catalyst_frontier_delta") or {}),
        label="题材催化前沿新增可晋级票",
        added_key="added_promoted_tickers",
        status_label="题材催化前沿状态变化",
    )
    _append_open_ready_frontier_focus(
        operator_focus,
        dict(delta_sections.get("score_fail_frontier_delta") or {}),
        label="score-fail recurring 队列新增重点票",
        added_key="added_priority_tickers",
        status_label="score-fail frontier 状态变化",
    )
    score_fail_delta = dict(delta_sections.get("score_fail_frontier_delta") or {})
    _append_open_ready_score_fail_focus(operator_focus, score_fail_delta)
    _append_open_ready_action_focus(operator_focus, delta_sections)
    _append_open_ready_stability_focus(operator_focus)
    return operator_focus


def _resolve_open_ready_overall_delta_verdict(comparison_basis: str, delta_sections: dict[str, Any]) -> str:
    if comparison_basis == "baseline_captured":
        return "baseline_captured"
    has_changes = any(
        dict(delta_sections.get(section) or {}).get("has_changes")
        for section in [
            "priority_delta",
            "governance_delta",
            "replay_delta",
            "catalyst_frontier_delta",
            "score_fail_frontier_delta",
            "top_priority_action_delta",
            "selected_outcome_contract_delta",
            "carryover_peer_proof_delta",
            "carryover_promotion_gate_delta",
        ]
    )
    return "changed" if has_changes else "stable"


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
    if not _should_build_open_ready_material_anchor(
        historical_payload_candidates=historical_payload_candidates,
        enable_material_anchor=enable_material_anchor,
        comparison_scope=comparison_scope,
        overall_delta_verdict=overall_delta_verdict,
    ):
        return {}
    material_change_anchor = _build_material_change_anchor(
        current_payload,
        reports_root=reports_root,
        current_nightly_json_path=current_nightly_json_path,
        historical_payload_candidates=historical_payload_candidates,
    )
    _append_open_ready_material_anchor_focus(operator_focus, material_change_anchor)
    return material_change_anchor


def _should_build_open_ready_material_anchor(
    *,
    historical_payload_candidates: list[tuple[dict[str, Any], str | None]] | None,
    enable_material_anchor: bool,
    comparison_scope: str,
    overall_delta_verdict: str,
) -> bool:
    return bool(enable_material_anchor and historical_payload_candidates and comparison_scope == "same_report_rerun" and overall_delta_verdict == "stable")


def _append_open_ready_material_anchor_focus(operator_focus: list[str], material_change_anchor: dict[str, Any]) -> None:
    if not material_change_anchor:
        return
    changed_sections = ", ".join(material_change_anchor.get("changed_sections") or []) or "n/a"
    operator_focus.append(f"最近一次实质变化锚点: {material_change_anchor.get('reference_generated_at') or 'n/a'} | sections={changed_sections}。")


def _build_open_ready_source_paths(
    *,
    current_payload: dict[str, Any],
    current_nightly_json_path: str | Path,
    previous_payload: dict[str, Any],
    previous_payload_path: str | None,
    previous_report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    latest_btst_snapshot = dict(current_payload.get("latest_btst_snapshot") or {})
    previous_btst_snapshot = dict(previous_payload.get("latest_btst_snapshot") or {})
    return {
        "current_nightly_control_tower_json": str(Path(current_nightly_json_path).expanduser().resolve()),
        "previous_nightly_control_tower_json": previous_payload_path,
        **_build_current_open_ready_source_paths(latest_btst_snapshot),
        **_build_previous_open_ready_source_paths(previous_payload, previous_btst_snapshot, previous_report_snapshot),
        "report_manifest_json": dict(current_payload.get("source_paths") or {}).get("report_manifest_json"),
        "report_manifest_markdown": dict(current_payload.get("source_paths") or {}).get("report_manifest_markdown"),
    }


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
    return {
        "generated_at": current_payload.get("generated_at"),
        "comparison_basis": comparison_basis,
        "comparison_scope": comparison_scope,
        "overall_delta_verdict": overall_delta_verdict,
        "current_reference": latest_btst_run,
        "previous_reference": previous_reference,
        "operator_focus": operator_focus[:6],
        **_build_open_ready_delta_analysis_sections(delta_sections),
        "material_change_anchor": material_change_anchor,
        "source_paths": source_paths,
    }


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
    context = _build_open_ready_delta_context(
        current_payload=current_payload,
        previous_payload=previous_payload,
        reports_root=reports_root,
    )
    comparison_scope = _resolve_open_ready_comparison_scope(
        context["comparison_basis"],
        context["previous_reference"],
        context["latest_btst_run"],
    )
    delta_sections = _build_open_ready_deltas(
        current_payload=current_payload,
        previous_payload=context["previous_payload"],
        previous_report_snapshot=context["previous_report_snapshot"],
        current_priority_snapshot=context["current_priority_snapshot"],
        previous_priority_board=context["previous_priority_board"],
    )
    operator_focus = _build_open_ready_operator_focus(context["comparison_basis"], comparison_scope, delta_sections)
    overall_delta_verdict = _resolve_open_ready_overall_delta_verdict(context["comparison_basis"], delta_sections)
    material_change_anchor = _build_open_ready_material_change_anchor(
        current_payload=current_payload,
        reports_root=reports_root,
        current_nightly_json_path=current_nightly_json_path,
        historical_payload_candidates=historical_payload_candidates,
        enable_material_anchor=enable_material_anchor,
        comparison_scope=comparison_scope,
        overall_delta_verdict=overall_delta_verdict,
        operator_focus=operator_focus,
    )
    source_paths = _build_open_ready_source_paths(
        current_payload=current_payload,
        current_nightly_json_path=current_nightly_json_path,
        previous_payload=context["previous_payload"],
        previous_payload_path=previous_payload_path,
        previous_report_snapshot=context["previous_report_snapshot"],
    )
    return _build_open_ready_delta_analysis(
        current_payload=current_payload,
        latest_btst_run=context["latest_btst_run"],
        previous_reference=context["previous_reference"],
        comparison_basis=context["comparison_basis"],
        comparison_scope=comparison_scope,
        overall_delta_verdict=overall_delta_verdict,
        operator_focus=operator_focus,
        delta_sections=delta_sections,
        material_change_anchor=material_change_anchor,
        source_paths=source_paths,
    )


def _build_open_ready_delta_context(
    *,
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any] | None,
    reports_root: str | Path,
) -> dict[str, Any]:
    latest_btst_run = dict(current_payload.get("latest_btst_run") or {})
    current_priority_snapshot = dict(current_payload.get("latest_priority_board_snapshot") or {})
    normalized_previous_payload = dict(previous_payload or {})
    previous_report_snapshot, previous_priority_board, comparison_basis, previous_reference = _resolve_open_ready_previous_context(
        latest_btst_run=latest_btst_run,
        previous_payload=normalized_previous_payload,
        reports_root=reports_root,
    )
    return {
        "latest_btst_run": latest_btst_run,
        "current_priority_snapshot": current_priority_snapshot,
        "previous_payload": normalized_previous_payload,
        "previous_report_snapshot": previous_report_snapshot,
        "previous_priority_board": previous_priority_board,
        "comparison_basis": comparison_basis,
        "previous_reference": previous_reference,
    }


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
    recommended_reading_order: list[dict[str, Any]] = []
    for entry_id in (
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
    ):
        entry = _entry_by_id(manifest, entry_id)
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


def _build_nightly_source_paths(manifest: dict[str, Any], latest_btst_snapshot: dict[str, Any]) -> dict[str, Any]:
    reports_root = Path(manifest.get("reports_root") or REPORTS_DIR)
    return {
        "report_manifest_json": str((reports_root / "report_manifest_latest.json").expanduser().resolve()),
        "report_manifest_markdown": str((reports_root / "report_manifest_latest.md").expanduser().resolve()),
        "governance_synthesis_markdown": _entry_by_id(manifest, "btst_governance_synthesis_latest").get("absolute_path"),
        "governance_validation_markdown": _entry_by_id(manifest, "btst_governance_validation_latest").get("absolute_path"),
        "default_merge_review_markdown": _entry_by_id(manifest, "btst_default_merge_review_latest").get("absolute_path"),
        "default_merge_historical_counterfactual_markdown": _entry_by_id(manifest, "btst_default_merge_historical_counterfactual_latest").get("absolute_path"),
        "continuation_merge_candidate_ranking_markdown": _entry_by_id(manifest, "btst_continuation_merge_candidate_ranking_latest").get("absolute_path"),
        "default_merge_strict_counterfactual_markdown": _entry_by_id(manifest, "btst_default_merge_strict_counterfactual_latest").get("absolute_path"),
        "merge_replay_validation_markdown": _entry_by_id(manifest, "btst_merge_replay_validation_latest").get("absolute_path"),
        "prepared_breakout_relief_validation_markdown": _entry_by_id(manifest, "btst_prepared_breakout_relief_validation_latest").get("absolute_path"),
        "prepared_breakout_cohort_markdown": _entry_by_id(manifest, "btst_prepared_breakout_cohort_latest").get("absolute_path"),
        "prepared_breakout_residual_surface_markdown": _entry_by_id(manifest, "btst_prepared_breakout_residual_surface_latest").get("absolute_path"),
        "candidate_pool_corridor_persistence_dossier_markdown": _entry_by_id(manifest, "btst_candidate_pool_corridor_persistence_dossier_latest").get("absolute_path"),
        "candidate_pool_corridor_window_command_board_markdown": _entry_by_id(manifest, "btst_candidate_pool_corridor_window_command_board_latest").get("absolute_path"),
        "candidate_pool_corridor_window_diagnostics_markdown": _entry_by_id(manifest, "btst_candidate_pool_corridor_window_diagnostics_latest").get("absolute_path"),
        "candidate_pool_corridor_narrow_probe_markdown": _entry_by_id(manifest, "btst_candidate_pool_corridor_narrow_probe_latest").get("absolute_path"),
        "selected_outcome_refresh_markdown": str((reports_root / "btst_selected_outcome_refresh_board_latest.md").expanduser().resolve()),
        "carryover_multiday_continuation_audit_markdown": str((reports_root / "btst_carryover_multiday_continuation_audit_latest.md").expanduser().resolve()),
        "carryover_aligned_peer_harvest_markdown": str((reports_root / "btst_carryover_aligned_peer_harvest_latest.md").expanduser().resolve()),
        "carryover_peer_expansion_markdown": str((reports_root / "btst_carryover_peer_expansion_latest.md").expanduser().resolve()),
        "priority_board_markdown": latest_btst_snapshot.get("priority_board_markdown_path"),
        "brief_markdown": latest_btst_snapshot.get("brief_markdown_path"),
        "execution_card_markdown": latest_btst_snapshot.get("execution_card_markdown_path"),
        "opening_watch_card_markdown": latest_btst_snapshot.get("opening_watch_card_markdown_path"),
        "catalyst_theme_frontier_markdown": latest_btst_snapshot.get("catalyst_theme_frontier_markdown_path"),
        "score_fail_frontier_markdown": latest_btst_snapshot.get("score_fail_frontier_markdown_path"),
        "score_fail_recurring_markdown": latest_btst_snapshot.get("score_fail_recurring_markdown_path"),
        "score_fail_transition_markdown": latest_btst_snapshot.get("score_fail_transition_markdown_path"),
        "tradeable_opportunity_pool_markdown": _entry_by_id(manifest, "btst_tradeable_opportunity_pool_march").get("absolute_path"),
        "no_candidate_entry_action_board_markdown": _entry_by_id(manifest, "btst_no_candidate_entry_action_board_latest").get("absolute_path"),
        "no_candidate_entry_replay_bundle_markdown": _entry_by_id(manifest, "btst_no_candidate_entry_replay_bundle_latest").get("absolute_path"),
        "no_candidate_entry_failure_dossier_markdown": _entry_by_id(manifest, "btst_no_candidate_entry_failure_dossier_latest").get("absolute_path"),
        "watchlist_recall_dossier_markdown": _entry_by_id(manifest, "btst_watchlist_recall_dossier_latest").get("absolute_path"),
        "candidate_pool_recall_dossier_markdown": _entry_by_id(manifest, "btst_candidate_pool_recall_dossier_latest").get("absolute_path"),
        "tradeable_opportunity_waterfall_markdown": _entry_by_id(manifest, "btst_tradeable_opportunity_reason_waterfall_march").get("absolute_path"),
        "replay_cohort_markdown": _entry_by_id(manifest, "btst_replay_cohort_latest").get("absolute_path"),
        "independent_window_monitor_markdown": _entry_by_id(manifest, "btst_independent_window_monitor_latest").get("absolute_path"),
        "tplus1_tplus2_objective_monitor_markdown": _entry_by_id(manifest, "btst_tplus1_tplus2_objective_monitor_latest").get("absolute_path"),
    }


def _build_nightly_control_tower_analysis(
    manifest: dict[str, Any],
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    effective_brief_recommendation: Any,
    recommended_reading_order: list[dict[str, Any]],
    source_paths: dict[str, Any],
) -> dict[str, Any]:
    priority_board = dict(latest_btst_snapshot.get("priority_board") or {})
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reports_root": manifest.get("reports_root"),
        "latest_btst_run": manifest.get("latest_btst_run"),
        "refresh_status": _build_nightly_refresh_status(manifest),
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


def render_btst_open_ready_delta_markdown(payload: dict[str, Any], *, output_parent: str | Path) -> str:
    return _render_btst_open_ready_delta_markdown_impl(
        payload,
        output_parent=output_parent,
        relative_link=_relative_link,
    )


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
        lines.append(f"- candidate_pool_corridor_validation_pack_summary: pack_status={corridor_validation_summary.get('pack_status')} primary_validation_ticker={corridor_validation_summary.get('primary_validation_ticker')} parallel_watch_tickers={corridor_validation_summary.get('parallel_watch_tickers')}")
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


def _append_nightly_overview_candidate_pool_followup_tail_markdown(
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
    lines.append(f"- score_fail_frontier_status: {score_fail_frontier_summary.get('status') or 'unavailable'}")
    lines.append(f"- score_fail_rejected_case_count: {score_fail_frontier_summary.get('rejected_short_trade_boundary_count')}")
    lines.append(f"- score_fail_recurring_case_count: {score_fail_frontier_summary.get('recurring_case_count')}")
    lines.append(f"- llm_health_status: {llm_error_digest.get('status')}")
    lines.append(f"- llm_error_count: {llm_error_digest.get('error_count')}")
    lines.append(f"- llm_fallback_attempt_count: {llm_error_digest.get('fallback_attempt_count')}")


def _append_nightly_overview_candidate_pool_followup_markdown(
    lines: list[str],
    control_tower_snapshot: dict[str, Any],
    replay_cohort_snapshot: dict[str, Any],
    catalyst_theme_frontier_summary: dict[str, Any],
    score_fail_frontier_summary: dict[str, Any],
    llm_error_digest: dict[str, Any],
) -> None:
    _append_nightly_overview_candidate_pool_continuation_markdown(lines, control_tower_snapshot)
    _append_nightly_overview_candidate_pool_followup_tail_markdown(
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
