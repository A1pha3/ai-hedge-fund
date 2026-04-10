from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.analyze_btst_latest_close_validation import generate_btst_latest_close_validation_artifacts
from scripts.btst_latest_followup_utils import load_latest_upstream_shadow_followup_summary
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
    focus_entry = entries[0] if entries else {}
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
    focus_entry = entries[0] if entries else {}
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
    focus_entry = entries[0] if entries else {}
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
    focus_entry = entries[0] if entries else {}
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
    focus_entry = entries[0] if entries else {}
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
    synthesis = _safe_load_json(dict(manifest.get("btst_governance_synthesis_refresh") or {}).get("output_json"))
    validation = _safe_load_json(dict(manifest.get("btst_governance_validation_refresh") or {}).get("output_json"))
    independent_window_monitor = _safe_load_json(dict(manifest.get("btst_independent_window_monitor_refresh") or {}).get("output_json"))
    tplus1_tplus2_objective_monitor = _safe_load_json(dict(manifest.get("btst_tplus1_tplus2_objective_monitor_refresh") or {}).get("output_json"))
    tradeable_opportunity_pool = _extract_tradeable_opportunity_pool_summary(manifest)
    no_candidate_entry_action_board = _extract_no_candidate_entry_action_board_summary(manifest)
    no_candidate_entry_replay_bundle = _extract_no_candidate_entry_replay_bundle_summary(manifest)
    no_candidate_entry_failure_dossier = _extract_no_candidate_entry_failure_dossier_summary(manifest)
    watchlist_recall_dossier = _extract_watchlist_recall_dossier_summary(manifest)
    candidate_pool_recall_dossier = _extract_candidate_pool_recall_dossier_summary(manifest)
    selected_outcome_refresh_summary = _extract_selected_outcome_refresh_summary(manifest)
    carryover_multiday_continuation_audit_summary = _extract_carryover_multiday_continuation_audit_summary(manifest)
    carryover_aligned_peer_harvest_summary = _extract_carryover_aligned_peer_harvest_summary(manifest)
    carryover_peer_expansion_summary = _extract_carryover_peer_expansion_summary(manifest)
    carryover_aligned_peer_proof_summary = _extract_carryover_aligned_peer_proof_summary(manifest)
    carryover_peer_promotion_gate_summary = _extract_carryover_peer_promotion_gate_summary(manifest)
    default_merge_review_summary = _extract_default_merge_review_summary(manifest)
    default_merge_historical_counterfactual_summary = _extract_default_merge_historical_counterfactual_summary(manifest)
    continuation_merge_candidate_ranking_summary = _extract_continuation_merge_candidate_ranking_summary(manifest)
    default_merge_strict_counterfactual_summary = _extract_default_merge_strict_counterfactual_summary(manifest)
    merge_replay_validation_summary = _extract_merge_replay_validation_summary(manifest)
    prepared_breakout_relief_validation_summary = _extract_prepared_breakout_relief_validation_summary(manifest)
    prepared_breakout_cohort_summary = _extract_prepared_breakout_cohort_summary(manifest)
    prepared_breakout_residual_surface_summary = _extract_prepared_breakout_residual_surface_summary(manifest)
    candidate_pool_corridor_persistence_dossier_summary = _extract_candidate_pool_corridor_persistence_dossier_summary(manifest)
    candidate_pool_corridor_window_command_board_summary = _extract_candidate_pool_corridor_window_command_board_summary(manifest)
    candidate_pool_corridor_window_diagnostics_summary = _extract_candidate_pool_corridor_window_diagnostics_summary(manifest)
    candidate_pool_corridor_narrow_probe_summary = _extract_candidate_pool_corridor_narrow_probe_summary(manifest)
    no_candidate_entry_priority_tickers = list(no_candidate_entry_action_board.get("top_priority_tickers") or [])
    absent_from_watchlist_tickers = list(no_candidate_entry_failure_dossier.get("top_absent_from_watchlist_tickers") or [])
    watchlist_absent_from_candidate_pool_tickers = list(watchlist_recall_dossier.get("top_absent_from_candidate_pool_tickers") or [])
    upstream_handoff_focus_tickers = list(dict(candidate_pool_recall_dossier.get("upstream_handoff_board_summary") or {}).get("focus_tickers") or [])
    upstream_shadow_followup_overlay = _build_upstream_shadow_followup_overlay(
        manifest.get("reports_root") or REPORTS_DIR,
        no_candidate_entry_priority_tickers=no_candidate_entry_priority_tickers,
        absent_from_watchlist_tickers=absent_from_watchlist_tickers,
        watchlist_absent_from_candidate_pool_tickers=watchlist_absent_from_candidate_pool_tickers,
        upstream_handoff_focus_tickers=upstream_handoff_focus_tickers,
    )
    return {
        "synthesis": synthesis,
        "validation": validation,
        "independent_window_monitor": independent_window_monitor,
        "tplus1_tplus2_objective_monitor": tplus1_tplus2_objective_monitor,
        "tradeable_opportunity_pool": tradeable_opportunity_pool,
        "no_candidate_entry_action_board": no_candidate_entry_action_board,
        "no_candidate_entry_replay_bundle": no_candidate_entry_replay_bundle,
        "no_candidate_entry_failure_dossier": no_candidate_entry_failure_dossier,
        "watchlist_recall_dossier": watchlist_recall_dossier,
        "candidate_pool_recall_dossier": candidate_pool_recall_dossier,
        "selected_outcome_refresh_summary": selected_outcome_refresh_summary,
        "carryover_multiday_continuation_audit_summary": carryover_multiday_continuation_audit_summary,
        "carryover_aligned_peer_harvest_summary": carryover_aligned_peer_harvest_summary,
        "carryover_peer_expansion_summary": carryover_peer_expansion_summary,
        "carryover_aligned_peer_proof_summary": carryover_aligned_peer_proof_summary,
        "carryover_peer_promotion_gate_summary": carryover_peer_promotion_gate_summary,
        "rollout_lanes": list(synthesis.get("lane_matrix") or []),
        "waiting_lane_count": synthesis.get("waiting_lane_count"),
        "ready_lane_count": synthesis.get("ready_lane_count"),
        "recommendation": synthesis.get("recommendation"),
        "lane_status_counts": synthesis.get("lane_status_counts"),
        "closed_frontiers": list(synthesis.get("closed_frontiers") or []),
        "next_actions": list(synthesis.get("next_actions") or [])[:3],
        "independent_window_ready_lane_count": independent_window_monitor.get("ready_lane_count"),
        "independent_window_waiting_lane_count": independent_window_monitor.get("waiting_lane_count"),
        "tplus1_tplus2_tradeable_positive_rate": dict(tplus1_tplus2_objective_monitor.get("tradeable_surface") or {}).get("t_plus_2_positive_rate"),
        "tplus1_tplus2_tradeable_return_hit_rate": dict(tplus1_tplus2_objective_monitor.get("tradeable_surface") or {}).get("t_plus_2_return_hit_rate_at_target"),
        "tplus1_tplus2_tradeable_mean_return": dict(tplus1_tplus2_objective_monitor.get("tradeable_surface") or {}).get("mean_t_plus_2_return"),
        "tplus1_tplus2_tradeable_verdict": dict(tplus1_tplus2_objective_monitor.get("tradeable_surface") or {}).get("verdict"),
        "tradeable_opportunity_pool_count": tradeable_opportunity_pool.get("tradeable_opportunity_pool_count"),
        "tradeable_opportunity_capture_rate": tradeable_opportunity_pool.get("tradeable_pool_capture_rate"),
        "tradeable_opportunity_selected_or_near_miss_rate": tradeable_opportunity_pool.get("tradeable_pool_selected_or_near_miss_rate"),
        "tradeable_opportunity_top_kill_switches": tradeable_opportunity_pool.get("top_tradeable_kill_switch_labels"),
        "no_candidate_entry_priority_queue_count": no_candidate_entry_action_board.get("priority_queue_count"),
        "no_candidate_entry_priority_tickers": no_candidate_entry_priority_tickers,
        "active_no_candidate_entry_priority_tickers": upstream_shadow_followup_overlay.get("active_no_candidate_entry_priority_tickers"),
        "no_candidate_entry_recall_probe_tickers": no_candidate_entry_replay_bundle.get("promising_priority_tickers"),
        "no_candidate_entry_failure_class_counts": no_candidate_entry_failure_dossier.get("priority_failure_class_counts"),
        "no_candidate_entry_handoff_stage_counts": no_candidate_entry_failure_dossier.get("priority_handoff_stage_counts"),
        "no_candidate_entry_absent_from_watchlist_tickers": absent_from_watchlist_tickers,
        "active_no_candidate_entry_absent_from_watchlist_tickers": upstream_shadow_followup_overlay.get("active_absent_from_watchlist_tickers"),
        "no_candidate_entry_watchlist_handoff_gap_tickers": no_candidate_entry_failure_dossier.get("top_watchlist_visible_but_not_candidate_entry_tickers"),
        "no_candidate_entry_upstream_absence_tickers": no_candidate_entry_failure_dossier.get("top_upstream_absence_tickers"),
        "watchlist_recall_stage_counts": watchlist_recall_dossier.get("priority_recall_stage_counts"),
        "watchlist_recall_absent_from_candidate_pool_tickers": watchlist_absent_from_candidate_pool_tickers,
        "active_watchlist_recall_absent_from_candidate_pool_tickers": upstream_shadow_followup_overlay.get("active_watchlist_absent_from_candidate_pool_tickers"),
        "watchlist_recall_candidate_pool_layer_b_gap_tickers": watchlist_recall_dossier.get("top_candidate_pool_visible_but_missing_layer_b_tickers"),
        "watchlist_recall_layer_b_watchlist_gap_tickers": watchlist_recall_dossier.get("top_layer_b_visible_but_missing_watchlist_tickers"),
        "candidate_pool_recall_stage_counts": candidate_pool_recall_dossier.get("priority_stage_counts"),
        "candidate_pool_recall_dominant_stage": candidate_pool_recall_dossier.get("dominant_stage"),
        "candidate_pool_recall_top_stage_tickers": candidate_pool_recall_dossier.get("top_stage_tickers"),
        "candidate_pool_recall_truncation_frontier_summary": candidate_pool_recall_dossier.get("truncation_frontier_summary"),
        "candidate_pool_recall_dominant_ranking_driver": dict(candidate_pool_recall_dossier.get("truncation_frontier_summary") or {}).get("dominant_ranking_driver"),
        "candidate_pool_recall_dominant_liquidity_gap_mode": dict(candidate_pool_recall_dossier.get("truncation_frontier_summary") or {}).get("dominant_liquidity_gap_mode"),
        "candidate_pool_recall_focus_liquidity_profiles": list(candidate_pool_recall_dossier.get("focus_liquidity_profiles") or []),
        "candidate_pool_recall_priority_handoff_counts": dict(candidate_pool_recall_dossier.get("priority_handoff_counts") or {}),
        "candidate_pool_recall_priority_handoff_branch_diagnoses": list(candidate_pool_recall_dossier.get("priority_handoff_branch_diagnoses") or []),
        "candidate_pool_recall_priority_handoff_branch_mechanisms": list(candidate_pool_recall_dossier.get("priority_handoff_branch_mechanisms") or []),
        "candidate_pool_recall_priority_handoff_branch_experiment_queue": list(candidate_pool_recall_dossier.get("priority_handoff_branch_experiment_queue") or []),
        "candidate_pool_branch_priority_board_status": candidate_pool_recall_dossier.get("branch_priority_board_status"),
        "candidate_pool_branch_priority_board_rows": list(candidate_pool_recall_dossier.get("branch_priority_board_rows") or []),
        "candidate_pool_branch_priority_alignment_status": candidate_pool_recall_dossier.get("branch_priority_alignment_status"),
        "candidate_pool_branch_priority_alignment_summary": candidate_pool_recall_dossier.get("branch_priority_alignment_summary"),
        "candidate_pool_lane_objective_support_status": candidate_pool_recall_dossier.get("lane_objective_support_status"),
        "candidate_pool_lane_objective_support_rows": list(candidate_pool_recall_dossier.get("lane_objective_support_rows") or []),
        "candidate_pool_corridor_validation_pack_status": candidate_pool_recall_dossier.get("corridor_validation_pack_status"),
        "candidate_pool_corridor_validation_pack_summary": dict(candidate_pool_recall_dossier.get("corridor_validation_pack_summary") or {}),
        "candidate_pool_corridor_shadow_pack_status": candidate_pool_recall_dossier.get("corridor_shadow_pack_status"),
        "candidate_pool_corridor_shadow_pack_summary": dict(candidate_pool_recall_dossier.get("corridor_shadow_pack_summary") or {}),
        "candidate_pool_rebucket_shadow_pack_status": candidate_pool_recall_dossier.get("rebucket_shadow_pack_status"),
        "candidate_pool_rebucket_shadow_pack_experiment": dict(candidate_pool_recall_dossier.get("rebucket_shadow_pack_experiment") or {}),
        "candidate_pool_rebucket_objective_validation_status": candidate_pool_recall_dossier.get("rebucket_objective_validation_status"),
        "candidate_pool_rebucket_objective_validation_summary": dict(candidate_pool_recall_dossier.get("rebucket_objective_validation_summary") or {}),
        "candidate_pool_rebucket_comparison_bundle_status": candidate_pool_recall_dossier.get("rebucket_comparison_bundle_status"),
        "candidate_pool_rebucket_comparison_bundle_summary": dict(candidate_pool_recall_dossier.get("rebucket_comparison_bundle_summary") or {}),
        "candidate_pool_lane_pair_board_status": candidate_pool_recall_dossier.get("lane_pair_board_status"),
        "candidate_pool_lane_pair_board_summary": dict(candidate_pool_recall_dossier.get("lane_pair_board_summary") or {}),
        "continuation_focus_summary": dict(candidate_pool_recall_dossier.get("continuation_focus_summary") or {}),
        "candidate_pool_upstream_handoff_board_status": candidate_pool_recall_dossier.get("upstream_handoff_board_status"),
        "candidate_pool_upstream_handoff_board_summary": dict(candidate_pool_recall_dossier.get("upstream_handoff_board_summary") or {}),
        "active_candidate_pool_upstream_handoff_focus_tickers": upstream_shadow_followup_overlay.get("active_upstream_handoff_focus_tickers"),
        "candidate_pool_corridor_uplift_runbook_status": candidate_pool_recall_dossier.get("corridor_uplift_runbook_status"),
        "candidate_pool_corridor_uplift_runbook_summary": dict(candidate_pool_recall_dossier.get("corridor_uplift_runbook_summary") or {}),
        "continuation_promotion_ready_summary": dict(candidate_pool_recall_dossier.get("continuation_promotion_ready_summary") or {}),
        "default_merge_review_summary": default_merge_review_summary,
        "default_merge_historical_counterfactual_summary": default_merge_historical_counterfactual_summary,
        "continuation_merge_candidate_ranking_summary": continuation_merge_candidate_ranking_summary,
        "default_merge_strict_counterfactual_summary": default_merge_strict_counterfactual_summary,
        "merge_replay_validation_summary": merge_replay_validation_summary,
        "prepared_breakout_relief_validation_summary": prepared_breakout_relief_validation_summary,
        "prepared_breakout_cohort_summary": prepared_breakout_cohort_summary,
        "prepared_breakout_residual_surface_summary": prepared_breakout_residual_surface_summary,
        "candidate_pool_corridor_persistence_dossier_summary": candidate_pool_corridor_persistence_dossier_summary,
        "candidate_pool_corridor_window_command_board_summary": candidate_pool_corridor_window_command_board_summary,
        "candidate_pool_corridor_window_diagnostics_summary": candidate_pool_corridor_window_diagnostics_summary,
        "candidate_pool_corridor_narrow_probe_summary": candidate_pool_corridor_narrow_probe_summary,
        "execution_constraint_rollup": dict(candidate_pool_recall_dossier.get("execution_constraint_rollup") or {}),
        "transient_probe_summary": dict(candidate_pool_recall_dossier.get("transient_probe_summary") or {}),
        "upstream_shadow_followup_overlay": upstream_shadow_followup_overlay,
        "upstream_shadow_followup_validated_tickers": upstream_shadow_followup_overlay.get("validated_tickers"),
        "upstream_shadow_followup_decision_counts": upstream_shadow_followup_overlay.get("decision_counts"),
        "upstream_shadow_followup_near_miss_tickers": upstream_shadow_followup_overlay.get("near_miss_tickers"),
        "upstream_shadow_followup_rejected_profitability_tickers": upstream_shadow_followup_overlay.get("rejected_profitability_tickers"),
        "upstream_shadow_followup_recommendation": upstream_shadow_followup_overlay.get("recommendation"),
        "overall_verdict": validation.get("overall_verdict"),
        "warn_count": validation.get("warn_count"),
        "fail_count": validation.get("fail_count"),
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
    frontier_verdict = str(dict(candidate_pool_recall_dossier.get("truncation_frontier_summary") or {}).get("frontier_verdict") or "").strip()
    why_now_parts = [
        "latest BTST still has 0 primary selections",
        f"dominant recall stage={dominant_stage}",
    ]
    if focus_tickers:
        why_now_parts.append(f"focus_tickers={focus_tickers}")
    if frontier_verdict:
        why_now_parts.append(f"frontier_verdict={frontier_verdict}")

    next_actions = list(candidate_pool_recall_dossier.get("next_actions") or [])
    next_step_default = str(candidate_pool_recall_dossier.get("recommendation") or "").strip() or "review candidate-pool recall dossier and upstream hard-filter stages"
    prioritized_handoff_next_step = None
    if dominant_stage == "candidate_pool_truncated_after_filters" and active_upstream_focus_tickers:
        prioritized_handoff_next_step = f"先补 {active_upstream_focus_tickers} 的 candidate pool -> watchlist 召回观测，确认它们为何连 watchlist 都没进入。"
        next_step_default = prioritized_handoff_next_step
    next_step = prioritized_handoff_next_step or next(
        (str(action).strip() for action in next_actions if str(action).strip()),
        next_step_default,
    )
    return {
        "task_id": "candidate_pool_recall_priority",
        "title": (
            "优先修复 Layer A recall / handoff 主链路"
            if dominant_stage == "candidate_pool_truncated_after_filters" and active_upstream_focus_tickers
            else f"优先修复 {dominant_stage} recall 主链路"
        ),
        "why_now": " | ".join(why_now_parts),
        "next_step": str(next_step),
        "source": "candidate_pool_recall_dossier",
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


def _build_carryover_contract_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    selected_summary = dict(control_tower_snapshot.get("selected_outcome_refresh_summary") or {})
    audit_summary = dict(control_tower_snapshot.get("carryover_multiday_continuation_audit_summary") or {})
    peer_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_harvest_summary") or {})
    peer_expansion_summary = dict(control_tower_snapshot.get("carryover_peer_expansion_summary") or {})
    peer_proof_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_proof_summary") or {})
    peer_promotion_gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})

    formal_selected_ticker = str(selected_summary.get("focus_ticker") or audit_summary.get("selected_ticker") or "").strip()
    if not formal_selected_ticker:
        return None

    overall_contract_verdict = str(selected_summary.get("focus_overall_contract_verdict") or "").strip()
    peer_focus_ticker = str(peer_expansion_summary.get("focus_ticker") or peer_summary.get("focus_ticker") or "").strip()
    peer_focus_status = str(peer_expansion_summary.get("focus_status") or peer_summary.get("focus_status") or "").strip()
    peer_proof_focus_ticker = str(peer_proof_summary.get("focus_ticker") or "").strip()
    peer_proof_focus_verdict = str(peer_proof_summary.get("focus_promotion_review_verdict") or "").strip()
    peer_promotion_gate_focus_ticker = str(peer_promotion_gate_summary.get("focus_ticker") or "").strip()
    peer_promotion_gate_focus_verdict = str(peer_promotion_gate_summary.get("focus_gate_verdict") or "").strip()
    priority_expansion_tickers = list(peer_expansion_summary.get("priority_expansion_tickers") or [])
    watch_with_risk_tickers = list(peer_expansion_summary.get("watch_with_risk_tickers") or [])
    ready_for_promotion_review_tickers = list(peer_proof_summary.get("ready_for_promotion_review_tickers") or [])
    promotion_gate_ready_tickers = list(peer_promotion_gate_summary.get("ready_tickers") or [])

    why_now_parts = [f"formal_selected={formal_selected_ticker}"]
    if overall_contract_verdict:
        why_now_parts.append(f"contract_verdict={overall_contract_verdict}")
    if audit_summary.get("selected_path_t2_bias_only"):
        why_now_parts.append("t_plus_2_bias_only")
    if audit_summary.get("broad_family_only_multiday_unsupported"):
        why_now_parts.append("broad_family_only_not_multiday_ready")
    if peer_focus_ticker:
        why_now_parts.append(f"peer_focus={peer_focus_ticker}")
    if peer_focus_status:
        why_now_parts.append(f"peer_status={peer_focus_status}")
    if peer_proof_focus_ticker:
        why_now_parts.append(f"peer_proof_focus={peer_proof_focus_ticker}")
    if peer_proof_focus_verdict:
        why_now_parts.append(f"peer_proof_verdict={peer_proof_focus_verdict}")
    if peer_promotion_gate_focus_ticker:
        why_now_parts.append(f"peer_gate_focus={peer_promotion_gate_focus_ticker}")
    if peer_promotion_gate_focus_verdict:
        why_now_parts.append(f"peer_gate_verdict={peer_promotion_gate_focus_verdict}")
    if watch_with_risk_tickers:
        why_now_parts.append(f"watch_with_risk={watch_with_risk_tickers}")

    next_steps = [
        f"继续把 {formal_selected_ticker} 作为 confirm-then-hold + T+2 bias 合约管理，不把它包装成稳定 T+3/T+4 continuation。"
    ]
    if audit_summary.get("broad_family_only_multiday_unsupported"):
        next_steps.append("broad_family_only carryover 仅保留 evidence-deficient / diagnostic 语义，不进入多日 continuation contract。")
    if peer_focus_ticker:
        next_steps.append(
            f"优先盯 {peer_focus_ticker} 的 {peer_focus_status or 'peer_harvest'} 闭环；只有第二个 aligned peer 完成 closed-cycle 转强后才讨论 lane 扩容。"
        )
    if priority_expansion_tickers:
        next_steps.append(f"当前 priority expansion 队列先看 {priority_expansion_tickers}。")
    if ready_for_promotion_review_tickers:
        next_steps.append(f"当前 ready-for-promotion-review peers: {ready_for_promotion_review_tickers}，应按第二个 aligned peer evidence 进入 promotion review。")
    if promotion_gate_ready_tickers:
        next_steps.append(f"当前已通过 promotion gate 的 peers: {promotion_gate_ready_tickers}，只允许在极窄 carryover lane 里讨论扩容。")
    if watch_with_risk_tickers:
        next_steps.append(f"{watch_with_risk_tickers} 仅保留 watch-with-risk 语义，不作为扩容依据。")

    title = (
        f"固化 {formal_selected_ticker} carryover 合约并盯 {peer_focus_ticker} 闭环"
        if peer_focus_ticker
        else f"固化 {formal_selected_ticker} carryover 合约"
    )
    return {
        "task_id": "carryover_contract_priority",
        "title": title,
        "why_now": " | ".join(why_now_parts),
        "next_step": "；".join(next_steps),
        "source": "carryover_contract",
    }


def _build_selected_contract_resolution_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    selected_summary = dict(control_tower_snapshot.get("selected_outcome_refresh_summary") or {})
    focus_ticker = str(selected_summary.get("focus_ticker") or "").strip()
    overall_contract_verdict = str(selected_summary.get("focus_overall_contract_verdict") or "").strip()
    focus_cycle_status = str(selected_summary.get("focus_cycle_status") or "").strip()
    next_day_contract_verdict = str(selected_summary.get("focus_next_day_contract_verdict") or "").strip()
    t_plus_2_contract_verdict = str(selected_summary.get("focus_t_plus_2_contract_verdict") or "").strip()
    if not focus_ticker or not overall_contract_verdict or overall_contract_verdict.startswith("pending"):
        return None

    is_violated = "violated" in overall_contract_verdict
    title = (
        f"优先处置 {focus_ticker} selected contract 失效"
        if is_violated
        else f"优先复核 {focus_ticker} selected contract 已兑现"
    )
    why_now_parts = [f"focus_ticker={focus_ticker}", f"overall_contract_verdict={overall_contract_verdict}"]
    if focus_cycle_status:
        why_now_parts.append(f"focus_cycle_status={focus_cycle_status}")
    if next_day_contract_verdict:
        why_now_parts.append(f"next_day_contract_verdict={next_day_contract_verdict}")
    if t_plus_2_contract_verdict:
        why_now_parts.append(f"t_plus_2_contract_verdict={t_plus_2_contract_verdict}")

    if is_violated:
        next_steps = [
            f"立刻把 {focus_ticker} 从 carryover 主合约语义中降级，停止把它当作次日/多日 continuation 锚点。"
        ]
        if focus_cycle_status:
            next_steps.append(f"结合当前 cycle_status={focus_cycle_status} 复核是 next-day 失效还是 T+2 失效，并同步回看触发该票入选的 frontier 证据。")
    else:
        next_steps = [
            f"立刻复核 {focus_ticker} 已兑现的 selected contract 是否足以支撑更高确信度的 BTST carryover 叙事，但仍避免把单票确认外推成过宽 lane。"
        ]
        if t_plus_2_contract_verdict:
            next_steps.append(f"同步确认 T+2 contract verdict={t_plus_2_contract_verdict}，决定是继续 hold-bias 还是仅保留 confirm-then-hold 语义。")

    return {
        "task_id": "selected_contract_resolution_priority",
        "title": title,
        "why_now": " | ".join(why_now_parts),
        "next_step": "；".join(next_steps),
        "source": "selected_contract_resolution",
    }


def _build_selected_contract_monitor_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    selected_summary = dict(control_tower_snapshot.get("selected_outcome_refresh_summary") or {})
    focus_ticker = str(selected_summary.get("focus_ticker") or "").strip()
    overall_contract_verdict = str(selected_summary.get("focus_overall_contract_verdict") or "").strip()
    focus_cycle_status = str(selected_summary.get("focus_cycle_status") or "").strip()
    next_day_contract_verdict = str(selected_summary.get("focus_next_day_contract_verdict") or "").strip()
    t_plus_2_contract_verdict = str(selected_summary.get("focus_t_plus_2_contract_verdict") or "").strip()
    if not focus_ticker or not overall_contract_verdict or not overall_contract_verdict.startswith("pending"):
        return None

    why_now_parts = [f"focus_ticker={focus_ticker}", f"overall_contract_verdict={overall_contract_verdict}"]
    if focus_cycle_status:
        why_now_parts.append(f"focus_cycle_status={focus_cycle_status}")
    if next_day_contract_verdict:
        why_now_parts.append(f"next_day_contract_verdict={next_day_contract_verdict}")
    if t_plus_2_contract_verdict:
        why_now_parts.append(f"t_plus_2_contract_verdict={t_plus_2_contract_verdict}")

    next_steps = [f"优先盯 {focus_ticker} 的主票闭环，确认 next-day bar 到来后是否仍满足 confirm-then-hold with T+2 bias 的 selected contract。"]
    if overall_contract_verdict == "pending_next_day":
        next_steps.append("一旦 next-day bar 落地，立即复核 next_close / intraday follow-through，避免 recall 或 peer 扩容叙事抢占 formal selected 主线。")
    elif overall_contract_verdict == "pending_t_plus_2":
        next_steps.append("一旦 T+2 bar 落地，立即复核 hold-bias 是否兑现，并决定是否继续保留 carryover 语义。")

    return {
        "task_id": "selected_contract_monitor_priority",
        "title": f"优先监控 {focus_ticker} formal selected 主票闭环",
        "why_now": " | ".join(why_now_parts),
        "next_step": "；".join(next_steps),
        "source": "selected_contract_monitor",
    }


def _build_gate_ready_priority_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})
    ready_tickers = [str(ticker) for ticker in list(gate_summary.get("ready_tickers") or []) if str(ticker).strip()]
    if not ready_tickers:
        return None

    selected_ticker = str(gate_summary.get("selected_ticker") or "").strip()
    selected_contract_verdict = str(gate_summary.get("selected_contract_verdict") or "").strip()
    focus_ticker = str(gate_summary.get("focus_ticker") or ready_tickers[0]).strip()
    focus_gate_verdict = str(gate_summary.get("focus_gate_verdict") or "promotion_gate_ready").strip()
    why_now_parts = [f"ready_tickers={ready_tickers}", f"focus_ticker={focus_ticker}", f"focus_gate_verdict={focus_gate_verdict}"]
    if selected_ticker:
        why_now_parts.append(f"selected_ticker={selected_ticker}")
    if selected_contract_verdict:
        why_now_parts.append(f"selected_contract_verdict={selected_contract_verdict}")
    next_steps = [
        f"立刻把 {ready_tickers} 作为第二个 aligned peer expansion review 的最高优先级，先复核 closed-cycle 兑现与执行约束，再决定是否在极窄 carryover lane 中扩容。"
    ]
    if selected_ticker:
        next_steps.append(f"同步确认 {selected_ticker} 当前合约仍保持 {selected_contract_verdict or 'pending'}，避免主票未闭环时误扩容。")
    return {
        "task_id": "carryover_gate_ready_priority",
        "title": f"优先复核 {focus_ticker} carryover gate-ready 扩容资格",
        "why_now": " | ".join(why_now_parts),
        "next_step": "；".join(next_steps),
        "source": "carryover_gate_ready",
    }


def _build_peer_proof_priority_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    proof_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_proof_summary") or {})
    gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})
    ready_for_promotion_review_tickers = [str(ticker) for ticker in list(proof_summary.get("ready_for_promotion_review_tickers") or []) if str(ticker).strip()]
    promotion_gate_ready_tickers = [str(ticker) for ticker in list(gate_summary.get("ready_tickers") or []) if str(ticker).strip()]
    if not ready_for_promotion_review_tickers or promotion_gate_ready_tickers:
        return None

    focus_ticker = str(proof_summary.get("focus_ticker") or ready_for_promotion_review_tickers[0]).strip()
    focus_proof_verdict = str(proof_summary.get("focus_proof_verdict") or "").strip()
    focus_promotion_review_verdict = str(proof_summary.get("focus_promotion_review_verdict") or "ready_for_promotion_review").strip()
    selected_contract_verdict = str(gate_summary.get("selected_contract_verdict") or "").strip()
    why_now_parts = [
        f"ready_for_promotion_review_tickers={ready_for_promotion_review_tickers}",
        f"focus_ticker={focus_ticker}",
        f"focus_promotion_review_verdict={focus_promotion_review_verdict}",
    ]
    if focus_proof_verdict:
        why_now_parts.append(f"focus_proof_verdict={focus_proof_verdict}")
    if selected_contract_verdict:
        why_now_parts.append(f"selected_contract_verdict={selected_contract_verdict}")

    next_steps = [
        f"立刻复核 {ready_for_promotion_review_tickers} 的第二个 aligned peer close-loop 证据，确认它们是否足以进入 promotion review，但在 gate 未 ready 前不要提前扩容。"
    ]
    if selected_contract_verdict:
        next_steps.append(f"同步确认 formal selected contract 当前仍为 {selected_contract_verdict}，避免 peer proof-ready 被误读成已可扩容。")

    return {
        "task_id": "carryover_peer_proof_priority",
        "title": f"优先复核 {focus_ticker} peer proof-ready 资格",
        "why_now": " | ".join(why_now_parts),
        "next_step": "；".join(next_steps),
        "source": "carryover_peer_proof",
    }


def _build_peer_close_loop_monitor_task(control_tower_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    proof_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_proof_summary") or {})
    gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})
    focus_ticker = str(proof_summary.get("focus_ticker") or gate_summary.get("focus_ticker") or "").strip()
    focus_proof_verdict = str(proof_summary.get("focus_proof_verdict") or "").strip()
    focus_promotion_review_verdict = str(proof_summary.get("focus_promotion_review_verdict") or "").strip()
    focus_gate_verdict = str(gate_summary.get("focus_gate_verdict") or "").strip()
    pending_t_plus_2_tickers = [str(ticker) for ticker in list(gate_summary.get("pending_t_plus_2_tickers") or []) if str(ticker).strip()]
    selected_contract_verdict = str(gate_summary.get("selected_contract_verdict") or "").strip()

    is_pending_peer_close_loop = (
        focus_ticker
        and (
            focus_proof_verdict == "pending_t_plus_2_close"
            or focus_promotion_review_verdict == "await_t_plus_2_close"
            or focus_gate_verdict == "await_peer_t_plus_2_close"
            or focus_ticker in pending_t_plus_2_tickers
        )
    )
    if not is_pending_peer_close_loop:
        return None

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

    next_steps = [f"优先盯 {focus_ticker} 的 peer close-loop，等待 T+2 bar 落地后确认是否从 pending_t_plus_2_close 翻到 proof-ready / promotion-review-ready。"]
    if selected_contract_verdict:
        next_steps.append(f"同步确认 formal selected contract 仍为 {selected_contract_verdict}，避免主票未闭环时提前把 peer 读成可扩容。")

    return {
        "task_id": "carryover_peer_close_loop_monitor_priority",
        "title": f"优先监控 {focus_ticker} peer close-loop 闭环",
        "why_now": " | ".join(why_now_parts),
        "next_step": "；".join(next_steps),
        "source": "carryover_peer_close_loop_monitor",
    }


def _prioritize_control_tower_next_actions(
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    prioritized: list[dict[str, Any]] = []

    for task in (
        _build_selected_contract_resolution_task(control_tower_snapshot),
        _build_selected_contract_monitor_task(control_tower_snapshot),
        _build_gate_ready_priority_task(control_tower_snapshot),
        _build_peer_proof_priority_task(control_tower_snapshot),
        _build_peer_close_loop_monitor_task(control_tower_snapshot),
        _build_carryover_contract_task(control_tower_snapshot),
        _build_recall_priority_task(latest_btst_snapshot, control_tower_snapshot),
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
    ):
        if task:
            prioritized.append(task)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for task in prioritized + list(control_tower_snapshot.get("next_actions") or []):
        dedupe_key = (str(task.get("title") or "").strip(), str(task.get("next_step") or "").strip())
        if not any(dedupe_key):
            continue
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(task)
    return deduped[:3]


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
    current_by_ticker = {str(row.get("ticker") or ""): dict(row) for row in current_rows if row.get("ticker")}
    previous_by_ticker = {str(row.get("ticker") or ""): dict(row) for row in previous_rows if row.get("ticker")}
    current_ranks = {ticker: index for index, ticker in enumerate(current_by_ticker, start=1)}
    previous_ranks = {ticker: index for index, ticker in enumerate(previous_by_ticker, start=1)}

    added_tickers = [
        {
            "ticker": ticker,
            "lane": current_by_ticker[ticker].get("lane"),
            "actionability": current_by_ticker[ticker].get("actionability"),
        }
        for ticker in current_by_ticker
        if ticker not in previous_by_ticker
    ]
    removed_tickers = [
        {
            "ticker": ticker,
            "lane": previous_by_ticker[ticker].get("lane"),
            "actionability": previous_by_ticker[ticker].get("actionability"),
        }
        for ticker in previous_by_ticker
        if ticker not in current_by_ticker
    ]
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

    current_guardrails = list(current_snapshot.get("global_guardrails") or [])
    previous_guardrails = list(previous_board.get("global_guardrails") or [])
    guardrails_added = [item for item in current_guardrails if item not in previous_guardrails]
    guardrails_removed = [item for item in previous_guardrails if item not in current_guardrails]
    summary_delta = {
        key: int(current_summary.get(key) or 0) - int(previous_summary.get(key) or 0)
        for key in ("primary_count", "near_miss_count", "opportunity_pool_count", "research_upside_radar_count", "catalyst_theme_count", "catalyst_theme_shadow_count")
    }
    has_changes = any(
        [
            str(current_snapshot.get("headline") or "") != str(previous_board.get("headline") or ""),
            any(value != 0 for value in summary_delta.values()),
            bool(added_tickers),
            bool(removed_tickers),
            bool(lane_changes),
            bool(actionability_changes),
            bool(execution_quality_changes),
            bool(rank_changes),
            bool(score_changes),
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
        "lane_changes": lane_changes,
        "actionability_changes": actionability_changes,
        "execution_quality_changes": execution_quality_changes,
        "rank_changes": rank_changes,
        "score_changes": score_changes,
        "guardrails_added": guardrails_added,
        "guardrails_removed": guardrails_removed,
        "has_changes": has_changes,
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
    current_by_lane = {str(row.get("lane_id") or ""): dict(row) for row in current_lane_matrix if row.get("lane_id")}
    previous_by_lane = {str(row.get("lane_id") or ""): dict(row) for row in previous_lane_matrix if row.get("lane_id")}
    lane_changes: list[dict[str, Any]] = []
    for lane_id in sorted(set(current_by_lane).union(previous_by_lane)):
        current_row = current_by_lane.get(lane_id)
        previous_row = previous_by_lane.get(lane_id)
        if current_row is None or previous_row is None:
            lane_changes.append(
                {
                    "lane_id": lane_id,
                    "previous_lane_status": (previous_row or {}).get("lane_status"),
                    "current_lane_status": (current_row or {}).get("lane_status"),
                    "previous_blocker": (previous_row or {}).get("blocker"),
                    "current_blocker": (current_row or {}).get("blocker"),
                }
            )
            continue
        lane_delta = {
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
        if any(
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
        ):
            lane_changes.append(lane_delta)

    waiting_lane_count_delta = int(current_control.get("waiting_lane_count") or 0) - int(previous_control.get("waiting_lane_count") or 0)
    ready_lane_count_delta = int(current_control.get("ready_lane_count") or 0) - int(previous_control.get("ready_lane_count") or 0)
    warn_count_delta = int(current_control.get("warn_count") or 0) - int(previous_control.get("warn_count") or 0)
    fail_count_delta = int(current_control.get("fail_count") or 0) - int(previous_control.get("fail_count") or 0)
    overall_verdict_changed = str(current_control.get("overall_verdict") or "") != str(previous_control.get("overall_verdict") or "")
    has_changes = any(
        [
            bool(lane_changes),
            waiting_lane_count_delta != 0,
            ready_lane_count_delta != 0,
            warn_count_delta != 0,
            fail_count_delta != 0,
            overall_verdict_changed,
        ]
    )
    return {
        "available": True,
        "current_overall_verdict": current_control.get("overall_verdict"),
        "previous_overall_verdict": previous_control.get("overall_verdict"),
        "overall_verdict_changed": overall_verdict_changed,
        "waiting_lane_count_delta": waiting_lane_count_delta,
        "ready_lane_count_delta": ready_lane_count_delta,
        "warn_count_delta": warn_count_delta,
        "fail_count_delta": fail_count_delta,
        "lane_changes": lane_changes,
        "changed_lane_count": len(lane_changes),
        "has_changes": has_changes,
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
    if previous_payload:
        previous_summary = dict(dict(previous_payload.get("latest_btst_snapshot") or {}).get("catalyst_theme_frontier_summary") or {})
        comparison_basis = "nightly_history"
    elif previous_report_snapshot:
        previous_summary = dict(previous_report_snapshot.get("catalyst_theme_frontier_summary") or {})
        comparison_basis = "previous_btst_report"
    else:
        return {
            "available": False,
            "comparison_basis": "none",
            "has_changes": False,
        }

    current_promoted_tickers = list(current_summary.get("recommended_promoted_tickers") or [])
    previous_promoted_tickers = list(previous_summary.get("recommended_promoted_tickers") or [])
    added_promoted_tickers = [ticker for ticker in current_promoted_tickers if ticker not in previous_promoted_tickers]
    removed_promoted_tickers = [ticker for ticker in previous_promoted_tickers if ticker not in current_promoted_tickers]
    promoted_shadow_count_delta = int(current_summary.get("recommended_promoted_shadow_count") or 0) - int(previous_summary.get("recommended_promoted_shadow_count") or 0)
    shadow_candidate_count_delta = int(current_summary.get("shadow_candidate_count") or 0) - int(previous_summary.get("shadow_candidate_count") or 0)
    baseline_selected_count_delta = int(current_summary.get("baseline_selected_count") or 0) - int(previous_summary.get("baseline_selected_count") or 0)
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
            promoted_shadow_count_delta != 0,
            shadow_candidate_count_delta != 0,
            baseline_selected_count_delta != 0,
            bool(added_promoted_tickers),
            bool(removed_promoted_tickers),
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
        "added_promoted_tickers": added_promoted_tickers,
        "removed_promoted_tickers": removed_promoted_tickers,
        "promoted_shadow_count_delta": promoted_shadow_count_delta,
        "shadow_candidate_count_delta": shadow_candidate_count_delta,
        "baseline_selected_count_delta": baseline_selected_count_delta,
        "previous_recommendation": previous_summary.get("recommendation"),
        "current_recommendation": current_summary.get("recommendation"),
        "has_changes": has_changes,
    }


def _diff_score_fail_frontier(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    if not previous_payload:
        return {
            "available": False,
            "reason": "no_previous_nightly_snapshot",
            "has_changes": False,
        }

    current_summary = dict(dict(current_payload.get("latest_btst_snapshot") or {}).get("score_fail_frontier_summary") or {})
    previous_summary = dict(dict(previous_payload.get("latest_btst_snapshot") or {}).get("score_fail_frontier_summary") or {})
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
    added_priority_tickers = [ticker for ticker in current_priority_queue_tickers if ticker not in previous_priority_queue_tickers]
    removed_priority_tickers = [ticker for ticker in previous_priority_queue_tickers if ticker not in current_priority_queue_tickers]
    added_top_rescue_tickers = [ticker for ticker in current_top_rescue_tickers if ticker not in previous_top_rescue_tickers]
    removed_top_rescue_tickers = [ticker for ticker in previous_top_rescue_tickers if ticker not in current_top_rescue_tickers]

    rejected_case_count_delta = int(current_summary.get("rejected_short_trade_boundary_count") or 0) - int(previous_summary.get("rejected_short_trade_boundary_count") or 0)
    rescueable_case_count_delta = int(current_summary.get("rescueable_case_count") or 0) - int(previous_summary.get("rescueable_case_count") or 0)
    threshold_only_rescue_count_delta = int(current_summary.get("threshold_only_rescue_count") or 0) - int(previous_summary.get("threshold_only_rescue_count") or 0)
    recurring_case_count_delta = int(current_summary.get("recurring_case_count") or 0) - int(previous_summary.get("recurring_case_count") or 0)
    transition_candidate_count_delta = int(current_summary.get("transition_candidate_count") or 0) - int(previous_summary.get("transition_candidate_count") or 0)
    status_changed = str(current_summary.get("status") or "") != str(previous_summary.get("status") or "")
    previous_data_available = bool(previous_summary)
    comparison_note = None
    if not previous_data_available and current_summary:
        comparison_note = "上一版 nightly 快照尚未记录 score-fail frontier 摘要，本轮是首个可比较的 frontier queue 暴露。"

    has_changes = any(
        [
            status_changed,
            rejected_case_count_delta != 0,
            rescueable_case_count_delta != 0,
            threshold_only_rescue_count_delta != 0,
            recurring_case_count_delta != 0,
            transition_candidate_count_delta != 0,
            bool(added_priority_tickers),
            bool(removed_priority_tickers),
            bool(added_top_rescue_tickers),
            bool(removed_top_rescue_tickers),
        ]
    )
    return {
        "available": True,
        "previous_data_available": previous_data_available,
        "comparison_note": comparison_note,
        "previous_status": previous_summary.get("status"),
        "current_status": current_summary.get("status"),
        "status_changed": status_changed,
        "rejected_case_count_delta": rejected_case_count_delta,
        "rescueable_case_count_delta": rescueable_case_count_delta,
        "threshold_only_rescue_count_delta": threshold_only_rescue_count_delta,
        "recurring_case_count_delta": recurring_case_count_delta,
        "transition_candidate_count_delta": transition_candidate_count_delta,
        "previous_priority_queue_tickers": previous_priority_queue_tickers,
        "current_priority_queue_tickers": current_priority_queue_tickers,
        "added_priority_tickers": added_priority_tickers,
        "removed_priority_tickers": removed_priority_tickers,
        "previous_top_rescue_tickers": previous_top_rescue_tickers,
        "current_top_rescue_tickers": current_top_rescue_tickers,
        "added_top_rescue_tickers": added_top_rescue_tickers,
        "removed_top_rescue_tickers": removed_top_rescue_tickers,
        "has_changes": has_changes,
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
    added_ready_tickers = [ticker for ticker in current_ready_tickers if ticker not in previous_ready_tickers]
    removed_ready_tickers = [ticker for ticker in previous_ready_tickers if ticker not in current_ready_tickers]
    added_blocked_open_tickers = [ticker for ticker in current_blocked_open_tickers if ticker not in previous_blocked_open_tickers]
    removed_blocked_open_tickers = [ticker for ticker in previous_blocked_open_tickers if ticker not in current_blocked_open_tickers]
    added_pending_t_plus_2_tickers = [ticker for ticker in current_pending_t_plus_2_tickers if ticker not in previous_pending_t_plus_2_tickers]
    removed_pending_t_plus_2_tickers = [ticker for ticker in previous_pending_t_plus_2_tickers if ticker not in current_pending_t_plus_2_tickers]
    focus_ticker_changed = str(current_summary.get("focus_ticker") or "") != str(previous_summary.get("focus_ticker") or "")
    focus_gate_verdict_changed = str(current_summary.get("focus_gate_verdict") or "") != str(previous_summary.get("focus_gate_verdict") or "")
    selected_contract_verdict_changed = str(current_summary.get("selected_contract_verdict") or "") != str(previous_summary.get("selected_contract_verdict") or "")
    has_changes = any(
        [
            focus_ticker_changed,
            focus_gate_verdict_changed,
            selected_contract_verdict_changed,
            bool(added_ready_tickers),
            bool(removed_ready_tickers),
            bool(added_blocked_open_tickers),
            bool(removed_blocked_open_tickers),
            bool(added_pending_t_plus_2_tickers),
            bool(removed_pending_t_plus_2_tickers),
        ]
    )
    return {
        "available": True,
        "previous_focus_ticker": previous_summary.get("focus_ticker"),
        "current_focus_ticker": current_summary.get("focus_ticker"),
        "focus_ticker_changed": focus_ticker_changed,
        "previous_focus_gate_verdict": previous_summary.get("focus_gate_verdict"),
        "current_focus_gate_verdict": current_summary.get("focus_gate_verdict"),
        "focus_gate_verdict_changed": focus_gate_verdict_changed,
        "previous_selected_contract_verdict": previous_summary.get("selected_contract_verdict"),
        "current_selected_contract_verdict": current_summary.get("selected_contract_verdict"),
        "selected_contract_verdict_changed": selected_contract_verdict_changed,
        "previous_ready_tickers": previous_ready_tickers,
        "current_ready_tickers": current_ready_tickers,
        "added_ready_tickers": added_ready_tickers,
        "removed_ready_tickers": removed_ready_tickers,
        "previous_blocked_open_tickers": previous_blocked_open_tickers,
        "current_blocked_open_tickers": current_blocked_open_tickers,
        "added_blocked_open_tickers": added_blocked_open_tickers,
        "removed_blocked_open_tickers": removed_blocked_open_tickers,
        "previous_pending_t_plus_2_tickers": previous_pending_t_plus_2_tickers,
        "current_pending_t_plus_2_tickers": current_pending_t_plus_2_tickers,
        "added_pending_t_plus_2_tickers": added_pending_t_plus_2_tickers,
        "removed_pending_t_plus_2_tickers": removed_pending_t_plus_2_tickers,
        "has_changes": has_changes,
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
    latest_btst_run = dict(current_payload.get("latest_btst_run") or {})
    current_priority_snapshot = dict(current_payload.get("latest_priority_board_snapshot") or {})
    previous_payload = dict(previous_payload or {})
    previous_report_snapshot = {} if previous_payload else _select_previous_btst_report_snapshot(
        reports_root,
        current_report_dir=latest_btst_run.get("report_dir_abs"),
        selection_target=latest_btst_run.get("selection_target"),
    )
    if previous_payload:
        previous_priority_board = dict(previous_payload.get("latest_priority_board_snapshot") or {})
        comparison_basis = "nightly_history"
        previous_reference = dict(previous_payload.get("latest_btst_run") or {})
        previous_reference["generated_at"] = previous_payload.get("generated_at")
        previous_reference["reference_kind"] = "nightly_history"
    elif previous_report_snapshot:
        previous_priority_board = dict(previous_report_snapshot.get("priority_board") or {})
        comparison_basis = "previous_btst_report"
        previous_reference = {
            "report_dir": previous_report_snapshot.get("report_dir"),
            "report_dir_abs": previous_report_snapshot.get("report_dir_abs"),
            "selection_target": previous_report_snapshot.get("selection_target"),
            "trade_date": previous_report_snapshot.get("trade_date"),
            "next_trade_date": previous_report_snapshot.get("next_trade_date"),
            "generated_at": None,
            "reference_kind": "previous_btst_report",
        }
    else:
        previous_priority_board = {}
        comparison_basis = "baseline_captured"
        previous_reference = {}

    comparison_scope = "baseline_captured"
    if comparison_basis == "nightly_history":
        comparison_scope = (
            "same_report_rerun"
            if str(previous_reference.get("report_dir") or "") == str(latest_btst_run.get("report_dir") or "")
            else "report_rollforward"
        )
    elif comparison_basis == "previous_btst_report":
        comparison_scope = "previous_btst_report"

    priority_delta = _diff_priority_board(
        current_priority_snapshot,
        previous_priority_board,
        previous_summary_source=(previous_payload.get("latest_btst_snapshot") or {}).get("brief_summary") if previous_payload else previous_report_snapshot.get("brief_summary"),
    )
    governance_delta = _diff_governance(current_payload, previous_payload)
    replay_delta = _diff_replay(current_payload, previous_payload, previous_report_snapshot)
    catalyst_frontier_delta = _diff_catalyst_frontier(current_payload, previous_payload, previous_report_snapshot)
    score_fail_frontier_delta = _diff_score_fail_frontier(current_payload, previous_payload)
    top_priority_action_delta = _diff_top_priority_action(current_payload, previous_payload)
    selected_outcome_contract_delta = _diff_selected_outcome_contract(current_payload, previous_payload)
    carryover_peer_proof_delta = _diff_carryover_peer_proof(current_payload, previous_payload)
    carryover_promotion_gate_delta = _diff_carryover_promotion_gate(current_payload, previous_payload)

    operator_focus: list[str] = []
    if comparison_basis == "baseline_captured":
        operator_focus.append("首个 open-ready delta 基线已捕获；下一轮 nightly 后将开始提供完整 lane / replay 差分。")
    elif comparison_basis == "previous_btst_report":
        operator_focus.append("当前已生成 report 级 delta；完整治理 lane 差分将在下一轮 nightly 历史快照后可用。")
    elif comparison_scope == "same_report_rerun":
        operator_focus.append("当前 delta 对比的是同一份 report 的上一版 nightly 快照，用于识别复刷变化，而不是跨 report 切换。")
    if priority_delta.get("headline_changed"):
        operator_focus.append(f"开盘 headline 已变化：{priority_delta.get('previous_headline') or 'n/a'} -> {priority_delta.get('current_headline') or 'n/a'}")
    if priority_delta.get("added_tickers"):
        operator_focus.append("新增观察对象: " + ", ".join(item.get("ticker") or "" for item in priority_delta.get("added_tickers") or []))
    if priority_delta.get("removed_tickers"):
        operator_focus.append("移出观察对象: " + ", ".join(item.get("ticker") or "" for item in priority_delta.get("removed_tickers") or []))
    if governance_delta.get("available") and governance_delta.get("changed_lane_count"):
        operator_focus.append("治理 lane 发生变化: " + ", ".join(change.get("lane_id") or "" for change in governance_delta.get("lane_changes") or []))
    if replay_delta.get("available") and replay_delta.get("has_changes"):
        if replay_delta.get("comparison_basis") == "nightly_history":
            operator_focus.append(
                f"replay cohort 变化: report_count {replay_delta.get('report_count_delta'):+d}, short_trade_only {replay_delta.get('short_trade_only_report_count_delta'):+d}。"
            )
        elif replay_delta.get("comparison_basis") == "previous_btst_report":
            summary_delta = dict(replay_delta.get("summary_delta") or {})
            operator_focus.append(
                "本轮相对上一份 BTST 报告的观察层变化: "
                + ", ".join(f"{key} {int(value):+d}" for key, value in summary_delta.items() if int(value) != 0)
            )
    if catalyst_frontier_delta.get("available") and catalyst_frontier_delta.get("has_changes"):
        if catalyst_frontier_delta.get("added_promoted_tickers"):
            operator_focus.append("题材催化前沿新增可晋级票: " + ", ".join(catalyst_frontier_delta.get("added_promoted_tickers") or []))
        elif catalyst_frontier_delta.get("status_changed"):
            operator_focus.append(
                f"题材催化前沿状态变化: {catalyst_frontier_delta.get('previous_status') or 'n/a'} -> {catalyst_frontier_delta.get('current_status') or 'n/a'}。"
            )
        elif catalyst_frontier_delta.get("comparison_note"):
            operator_focus.append(str(catalyst_frontier_delta.get("comparison_note")))
    if score_fail_frontier_delta.get("available") and score_fail_frontier_delta.get("has_changes"):
        if score_fail_frontier_delta.get("added_priority_tickers"):
            operator_focus.append("score-fail recurring 队列新增重点票: " + ", ".join(score_fail_frontier_delta.get("added_priority_tickers") or []))
        elif score_fail_frontier_delta.get("added_top_rescue_tickers"):
            operator_focus.append("score-fail frontier 新增 near-miss rescue 票: " + ", ".join(score_fail_frontier_delta.get("added_top_rescue_tickers") or []))
        elif score_fail_frontier_delta.get("status_changed"):
            operator_focus.append(
                f"score-fail frontier 状态变化: {score_fail_frontier_delta.get('previous_status') or 'n/a'} -> {score_fail_frontier_delta.get('current_status') or 'n/a'}。"
            )
        elif score_fail_frontier_delta.get("comparison_note"):
            operator_focus.append(str(score_fail_frontier_delta.get("comparison_note")))
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
    if not operator_focus:
        operator_focus.append("本轮相对上一轮没有检测到 priority / governance / replay / score-fail frontier / top priority action / selected contract / carryover peer proof / carryover promotion gate 的结构变化，可视为稳定复跑。")

    overall_delta_verdict = "baseline_captured"
    if comparison_basis != "baseline_captured":
        overall_delta_verdict = "changed" if any([priority_delta.get("has_changes"), governance_delta.get("has_changes"), replay_delta.get("has_changes"), catalyst_frontier_delta.get("has_changes"), score_fail_frontier_delta.get("has_changes"), top_priority_action_delta.get("has_changes"), selected_outcome_contract_delta.get("has_changes"), carryover_peer_proof_delta.get("has_changes"), carryover_promotion_gate_delta.get("has_changes")]) else "stable"

    material_change_anchor: dict[str, Any] = {}
    if enable_material_anchor and historical_payload_candidates and comparison_scope == "same_report_rerun" and overall_delta_verdict == "stable":
        material_change_anchor = _build_material_change_anchor(
            current_payload,
            reports_root=reports_root,
            current_nightly_json_path=current_nightly_json_path,
            historical_payload_candidates=historical_payload_candidates,
        )
        if material_change_anchor:
            changed_sections = ", ".join(material_change_anchor.get("changed_sections") or []) or "n/a"
            operator_focus.append(
                f"最近一次实质变化锚点: {material_change_anchor.get('reference_generated_at') or 'n/a'} | sections={changed_sections}。"
            )

    return {
        "generated_at": current_payload.get("generated_at"),
        "comparison_basis": comparison_basis,
        "comparison_scope": comparison_scope,
        "overall_delta_verdict": overall_delta_verdict,
        "current_reference": latest_btst_run,
        "previous_reference": previous_reference,
        "operator_focus": operator_focus[:6],
        "priority_delta": priority_delta,
        "catalyst_frontier_delta": catalyst_frontier_delta,
        "score_fail_frontier_delta": score_fail_frontier_delta,
        "top_priority_action_delta": top_priority_action_delta,
        "selected_outcome_contract_delta": selected_outcome_contract_delta,
        "carryover_peer_proof_delta": carryover_peer_proof_delta,
        "carryover_promotion_gate_delta": carryover_promotion_gate_delta,
        "governance_delta": governance_delta,
        "replay_delta": replay_delta,
        "material_change_anchor": material_change_anchor,
        "source_paths": {
            "current_nightly_control_tower_json": str(Path(current_nightly_json_path).expanduser().resolve()),
            "previous_nightly_control_tower_json": previous_payload_path,
            "current_priority_board_json": dict(current_payload.get("latest_btst_snapshot") or {}).get("priority_board_json_path"),
            "previous_priority_board_json": previous_payload.get("latest_btst_snapshot", {}).get("priority_board_json_path") if previous_payload else previous_report_snapshot.get("priority_board_json_path"),
            "current_catalyst_theme_frontier_markdown": dict(current_payload.get("latest_btst_snapshot") or {}).get("catalyst_theme_frontier_markdown_path"),
            "previous_catalyst_theme_frontier_markdown": previous_payload.get("latest_btst_snapshot", {}).get("catalyst_theme_frontier_markdown_path") if previous_payload else previous_report_snapshot.get("catalyst_theme_frontier_markdown_path"),
            "current_score_fail_frontier_markdown": dict(current_payload.get("latest_btst_snapshot") or {}).get("score_fail_frontier_markdown_path"),
            "previous_score_fail_frontier_markdown": previous_payload.get("latest_btst_snapshot", {}).get("score_fail_frontier_markdown_path") if previous_payload else None,
            "current_score_fail_recurring_markdown": dict(current_payload.get("latest_btst_snapshot") or {}).get("score_fail_recurring_markdown_path"),
            "previous_score_fail_recurring_markdown": previous_payload.get("latest_btst_snapshot", {}).get("score_fail_recurring_markdown_path") if previous_payload else None,
            "report_manifest_json": dict(current_payload.get("source_paths") or {}).get("report_manifest_json"),
            "report_manifest_markdown": dict(current_payload.get("source_paths") or {}).get("report_manifest_markdown"),
        },
    }


def render_btst_open_ready_delta_markdown(payload: dict[str, Any], *, output_parent: str | Path) -> str:
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
    lines.append("# BTST Open-Ready Delta")
    lines.append("")
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

    lines.append("## Operator Focus")
    for item in list(payload.get("operator_focus") or []):
        lines.append(f"- {item}")
    lines.append("")

    if material_change_anchor:
        lines.append("## Last Material Change Anchor")
        lines.append(f"- reference_generated_at: {material_change_anchor.get('reference_generated_at') or 'n/a'}")
        lines.append(f"- reference_report_dir: {material_change_anchor.get('reference_report_dir') or 'n/a'}")
        lines.append(f"- comparison_basis: {material_change_anchor.get('comparison_basis')}")
        lines.append(f"- comparison_scope: {material_change_anchor.get('comparison_scope')}")
        lines.append(f"- overall_delta_verdict: {material_change_anchor.get('overall_delta_verdict')}")
        lines.append(f"- skipped_same_report_rerun_snapshots: {material_change_anchor.get('skipped_snapshot_count') or 0}")
        changed_sections = list(material_change_anchor.get("changed_sections") or [])
        lines.append(f"- changed_sections: {', '.join(changed_sections) if changed_sections else 'none'}")
        reference_snapshot_path = material_change_anchor.get("reference_snapshot_path")
        relative_anchor_target = _relative_link(reference_snapshot_path, resolved_output_parent)
        if relative_anchor_target:
            lines.append(f"- reference_snapshot_json: [{Path(reference_snapshot_path).name}]({relative_anchor_target})")
        elif reference_snapshot_path:
            lines.append(f"- reference_snapshot_json: {reference_snapshot_path}")
        for item in list(material_change_anchor.get("operator_focus") or []):
            lines.append(f"- anchor_focus: {item}")
        lines.append("")

    lines.append("## Priority Delta")
    lines.append(f"- previous_headline: {priority_delta.get('previous_headline') or 'n/a'}")
    lines.append(f"- current_headline: {priority_delta.get('current_headline') or 'n/a'}")
    lines.append(f"- summary_delta: {priority_delta.get('summary_delta')}")
    if priority_delta.get("added_tickers"):
        for item in list(priority_delta.get("added_tickers") or []):
            lines.append(f"- added_ticker: {item.get('ticker')} | lane={item.get('lane')} | actionability={item.get('actionability')}")
    if priority_delta.get("removed_tickers"):
        for item in list(priority_delta.get("removed_tickers") or []):
            lines.append(f"- removed_ticker: {item.get('ticker')} | lane={item.get('lane')} | actionability={item.get('actionability')}")
    if priority_delta.get("lane_changes"):
        for item in list(priority_delta.get("lane_changes") or []):
            lines.append(f"- lane_change: {item.get('ticker')} | {item.get('previous_lane')} -> {item.get('current_lane')}")
    if priority_delta.get("actionability_changes"):
        for item in list(priority_delta.get("actionability_changes") or []):
            lines.append(f"- actionability_change: {item.get('ticker')} | {item.get('previous_actionability')} -> {item.get('current_actionability')}")
    if priority_delta.get("execution_quality_changes"):
        for item in list(priority_delta.get("execution_quality_changes") or []):
            lines.append(f"- execution_quality_change: {item.get('ticker')} | {item.get('previous_execution_quality_label')} -> {item.get('current_execution_quality_label')}")
    if priority_delta.get("rank_changes"):
        for item in list(priority_delta.get("rank_changes") or []):
            lines.append(f"- rank_change: {item.get('ticker')} | {item.get('previous_rank')} -> {item.get('current_rank')}")
    if priority_delta.get("score_changes"):
        for item in list(priority_delta.get("score_changes") or []):
            lines.append(f"- score_change: {item.get('ticker')} | {item.get('previous_score_target')} -> {item.get('current_score_target')} (delta={item.get('score_target_delta')})")
    if priority_delta.get("guardrails_added"):
        for item in list(priority_delta.get("guardrails_added") or []):
            lines.append(f"- guardrail_added: {item}")
    if priority_delta.get("guardrails_removed"):
        for item in list(priority_delta.get("guardrails_removed") or []):
            lines.append(f"- guardrail_removed: {item}")
    if not priority_delta.get("has_changes"):
        lines.append("- no_priority_change_detected")
    lines.append("")

    lines.append("## Catalyst Theme Frontier Delta")
    if not catalyst_frontier_delta.get("available"):
        lines.append("- unavailable")
    else:
        lines.append(f"- comparison_basis: {catalyst_frontier_delta.get('comparison_basis')}")
        lines.append(f"- previous_data_available: {catalyst_frontier_delta.get('previous_data_available')}")
        lines.append(f"- previous_status: {catalyst_frontier_delta.get('previous_status') or 'n/a'}")
        lines.append(f"- current_status: {catalyst_frontier_delta.get('current_status') or 'n/a'}")
        lines.append(f"- shadow_candidate_count_delta: {catalyst_frontier_delta.get('shadow_candidate_count_delta')}")
        lines.append(f"- promoted_shadow_count_delta: {catalyst_frontier_delta.get('promoted_shadow_count_delta')}")
        lines.append(f"- baseline_selected_count_delta: {catalyst_frontier_delta.get('baseline_selected_count_delta')}")
        lines.append(f"- previous_recommended_variant_name: {catalyst_frontier_delta.get('previous_recommended_variant_name') or 'n/a'}")
        lines.append(f"- current_recommended_variant_name: {catalyst_frontier_delta.get('current_recommended_variant_name') or 'n/a'}")
        if catalyst_frontier_delta.get("comparison_note"):
            lines.append(f"- note: {catalyst_frontier_delta.get('comparison_note')}")
        previous_promoted_tickers = list(catalyst_frontier_delta.get("previous_promoted_tickers") or [])
        current_promoted_tickers = list(catalyst_frontier_delta.get("current_promoted_tickers") or [])
        lines.append(f"- previous_promoted_tickers: {', '.join(previous_promoted_tickers) if previous_promoted_tickers else 'none'}")
        lines.append(f"- current_promoted_tickers: {', '.join(current_promoted_tickers) if current_promoted_tickers else 'none'}")
        for ticker in list(catalyst_frontier_delta.get("added_promoted_tickers") or []):
            lines.append(f"- added_promoted_ticker: {ticker}")
        for ticker in list(catalyst_frontier_delta.get("removed_promoted_tickers") or []):
            lines.append(f"- removed_promoted_ticker: {ticker}")
        if not catalyst_frontier_delta.get("has_changes"):
            lines.append("- no_catalyst_frontier_change_detected")
    lines.append("")

    lines.append("## Score-Fail Frontier Delta")
    if not score_fail_frontier_delta.get("available"):
        lines.append(f"- unavailable: {score_fail_frontier_delta.get('reason')}")
    else:
        lines.append(f"- previous_data_available: {score_fail_frontier_delta.get('previous_data_available')}")
        lines.append(f"- previous_status: {score_fail_frontier_delta.get('previous_status') or 'n/a'}")
        lines.append(f"- current_status: {score_fail_frontier_delta.get('current_status') or 'n/a'}")
        lines.append(f"- rejected_case_count_delta: {score_fail_frontier_delta.get('rejected_case_count_delta')}")
        lines.append(f"- rescueable_case_count_delta: {score_fail_frontier_delta.get('rescueable_case_count_delta')}")
        lines.append(f"- threshold_only_rescue_count_delta: {score_fail_frontier_delta.get('threshold_only_rescue_count_delta')}")
        lines.append(f"- recurring_case_count_delta: {score_fail_frontier_delta.get('recurring_case_count_delta')}")
        lines.append(f"- transition_candidate_count_delta: {score_fail_frontier_delta.get('transition_candidate_count_delta')}")
        if score_fail_frontier_delta.get("comparison_note"):
            lines.append(f"- note: {score_fail_frontier_delta.get('comparison_note')}")
        previous_priority_queue = list(score_fail_frontier_delta.get("previous_priority_queue_tickers") or [])
        current_priority_queue = list(score_fail_frontier_delta.get("current_priority_queue_tickers") or [])
        lines.append(f"- previous_priority_queue_tickers: {', '.join(previous_priority_queue) if previous_priority_queue else 'none'}")
        lines.append(f"- current_priority_queue_tickers: {', '.join(current_priority_queue) if current_priority_queue else 'none'}")
        for ticker in list(score_fail_frontier_delta.get("added_priority_tickers") or []):
            lines.append(f"- added_priority_ticker: {ticker}")
        for ticker in list(score_fail_frontier_delta.get("removed_priority_tickers") or []):
            lines.append(f"- removed_priority_ticker: {ticker}")
        for ticker in list(score_fail_frontier_delta.get("added_top_rescue_tickers") or []):
            lines.append(f"- added_top_rescue_ticker: {ticker}")
        for ticker in list(score_fail_frontier_delta.get("removed_top_rescue_tickers") or []):
            lines.append(f"- removed_top_rescue_ticker: {ticker}")
        if not score_fail_frontier_delta.get("has_changes"):
            lines.append("- no_score_fail_frontier_change_detected")
    lines.append("")

    lines.append("## Top Priority Action Delta")
    if not top_priority_action_delta.get("available"):
        lines.append(f"- unavailable: {top_priority_action_delta.get('reason')}")
    else:
        lines.append(f"- previous_task_id: {top_priority_action_delta.get('previous_task_id') or 'n/a'}")
        lines.append(f"- current_task_id: {top_priority_action_delta.get('current_task_id') or 'n/a'}")
        lines.append(f"- previous_source: {top_priority_action_delta.get('previous_source') or 'n/a'}")
        lines.append(f"- current_source: {top_priority_action_delta.get('current_source') or 'n/a'}")
        lines.append(f"- previous_title: {top_priority_action_delta.get('previous_title') or 'n/a'}")
        lines.append(f"- current_title: {top_priority_action_delta.get('current_title') or 'n/a'}")
        if not top_priority_action_delta.get("has_changes"):
            lines.append("- no_top_priority_action_change_detected")
    lines.append("")

    lines.append("## Selected Outcome Contract Delta")
    if not selected_outcome_contract_delta.get("available"):
        lines.append(f"- unavailable: {selected_outcome_contract_delta.get('reason')}")
    else:
        lines.append(f"- previous_focus_ticker: {selected_outcome_contract_delta.get('previous_focus_ticker') or 'n/a'}")
        lines.append(f"- current_focus_ticker: {selected_outcome_contract_delta.get('current_focus_ticker') or 'n/a'}")
        lines.append(f"- previous_focus_cycle_status: {selected_outcome_contract_delta.get('previous_focus_cycle_status') or 'n/a'}")
        lines.append(f"- current_focus_cycle_status: {selected_outcome_contract_delta.get('current_focus_cycle_status') or 'n/a'}")
        lines.append(
            f"- previous_focus_overall_contract_verdict: {selected_outcome_contract_delta.get('previous_focus_overall_contract_verdict') or 'n/a'}"
        )
        lines.append(
            f"- current_focus_overall_contract_verdict: {selected_outcome_contract_delta.get('current_focus_overall_contract_verdict') or 'n/a'}"
        )
        lines.append(
            f"- previous_focus_next_day_contract_verdict: {selected_outcome_contract_delta.get('previous_focus_next_day_contract_verdict') or 'n/a'}"
        )
        lines.append(
            f"- current_focus_next_day_contract_verdict: {selected_outcome_contract_delta.get('current_focus_next_day_contract_verdict') or 'n/a'}"
        )
        lines.append(
            f"- previous_focus_t_plus_2_contract_verdict: {selected_outcome_contract_delta.get('previous_focus_t_plus_2_contract_verdict') or 'n/a'}"
        )
        lines.append(
            f"- current_focus_t_plus_2_contract_verdict: {selected_outcome_contract_delta.get('current_focus_t_plus_2_contract_verdict') or 'n/a'}"
        )
        if not selected_outcome_contract_delta.get("has_changes"):
            lines.append("- no_selected_outcome_contract_change_detected")
    lines.append("")

    lines.append("## Carryover Peer Proof Delta")
    if not carryover_peer_proof_delta.get("available"):
        lines.append(f"- unavailable: {carryover_peer_proof_delta.get('reason')}")
    else:
        lines.append(f"- previous_focus_ticker: {carryover_peer_proof_delta.get('previous_focus_ticker') or 'n/a'}")
        lines.append(f"- current_focus_ticker: {carryover_peer_proof_delta.get('current_focus_ticker') or 'n/a'}")
        lines.append(f"- previous_focus_proof_verdict: {carryover_peer_proof_delta.get('previous_focus_proof_verdict') or 'n/a'}")
        lines.append(f"- current_focus_proof_verdict: {carryover_peer_proof_delta.get('current_focus_proof_verdict') or 'n/a'}")
        lines.append(
            f"- previous_focus_promotion_review_verdict: {carryover_peer_proof_delta.get('previous_focus_promotion_review_verdict') or 'n/a'}"
        )
        lines.append(
            f"- current_focus_promotion_review_verdict: {carryover_peer_proof_delta.get('current_focus_promotion_review_verdict') or 'n/a'}"
        )
        lines.append(
            f"- previous_ready_for_promotion_review_tickers: {carryover_peer_proof_delta.get('previous_ready_for_promotion_review_tickers') or []}"
        )
        lines.append(
            f"- current_ready_for_promotion_review_tickers: {carryover_peer_proof_delta.get('current_ready_for_promotion_review_tickers') or []}"
        )
        for ticker in list(carryover_peer_proof_delta.get("added_ready_for_promotion_review_tickers") or []):
            lines.append(f"- added_ready_for_promotion_review_ticker: {ticker}")
        for ticker in list(carryover_peer_proof_delta.get("removed_ready_for_promotion_review_tickers") or []):
            lines.append(f"- removed_ready_for_promotion_review_ticker: {ticker}")
        if not carryover_peer_proof_delta.get("has_changes"):
            lines.append("- no_carryover_peer_proof_change_detected")
    lines.append("")

    lines.append("## Carryover Promotion Gate Delta")
    if not carryover_promotion_gate_delta.get("available"):
        lines.append(f"- unavailable: {carryover_promotion_gate_delta.get('reason')}")
    else:
        lines.append(f"- previous_focus_ticker: {carryover_promotion_gate_delta.get('previous_focus_ticker') or 'n/a'}")
        lines.append(f"- current_focus_ticker: {carryover_promotion_gate_delta.get('current_focus_ticker') or 'n/a'}")
        lines.append(f"- previous_focus_gate_verdict: {carryover_promotion_gate_delta.get('previous_focus_gate_verdict') or 'n/a'}")
        lines.append(f"- current_focus_gate_verdict: {carryover_promotion_gate_delta.get('current_focus_gate_verdict') or 'n/a'}")
        lines.append(f"- previous_selected_contract_verdict: {carryover_promotion_gate_delta.get('previous_selected_contract_verdict') or 'n/a'}")
        lines.append(f"- current_selected_contract_verdict: {carryover_promotion_gate_delta.get('current_selected_contract_verdict') or 'n/a'}")
        lines.append(f"- previous_ready_tickers: {carryover_promotion_gate_delta.get('previous_ready_tickers') or []}")
        lines.append(f"- current_ready_tickers: {carryover_promotion_gate_delta.get('current_ready_tickers') or []}")
        for ticker in list(carryover_promotion_gate_delta.get("added_ready_tickers") or []):
            lines.append(f"- added_promotion_gate_ready_ticker: {ticker}")
        for ticker in list(carryover_promotion_gate_delta.get("removed_ready_tickers") or []):
            lines.append(f"- removed_promotion_gate_ready_ticker: {ticker}")
        for ticker in list(carryover_promotion_gate_delta.get("added_pending_t_plus_2_tickers") or []):
            lines.append(f"- added_pending_t_plus_2_ticker: {ticker}")
        for ticker in list(carryover_promotion_gate_delta.get("removed_pending_t_plus_2_tickers") or []):
            lines.append(f"- removed_pending_t_plus_2_ticker: {ticker}")
        if not carryover_promotion_gate_delta.get("has_changes"):
            lines.append("- no_carryover_promotion_gate_change_detected")
    lines.append("")

    lines.append("## Governance Delta")
    if not governance_delta.get("available"):
        lines.append(f"- unavailable: {governance_delta.get('reason')}")
    else:
        lines.append(f"- previous_overall_verdict: {governance_delta.get('previous_overall_verdict')}")
        lines.append(f"- current_overall_verdict: {governance_delta.get('current_overall_verdict')}")
        lines.append(f"- waiting_lane_count_delta: {governance_delta.get('waiting_lane_count_delta')}")
        lines.append(f"- ready_lane_count_delta: {governance_delta.get('ready_lane_count_delta')}")
        lines.append(f"- warn_count_delta: {governance_delta.get('warn_count_delta')}")
        lines.append(f"- fail_count_delta: {governance_delta.get('fail_count_delta')}")
        if governance_delta.get("lane_changes"):
            for item in list(governance_delta.get("lane_changes") or []):
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

                extra_suffix = f" | {' | '.join(extra_segments)}" if extra_segments else ""
                lines.append(
                    f"- lane_delta: {item.get('lane_id')} | status {item.get('previous_lane_status')} -> {item.get('current_lane_status')} | blocker {item.get('previous_blocker')} -> {item.get('current_blocker')}{extra_suffix}"
                )
        else:
            lines.append("- no_governance_change_detected")
    lines.append("")

    lines.append("## Replay Delta")
    if not replay_delta.get("available"):
        lines.append("- unavailable")
    else:
        lines.append(f"- comparison_basis: {replay_delta.get('comparison_basis')}")
        if replay_delta.get("comparison_basis") == "nightly_history":
            lines.append(f"- report_count_delta: {replay_delta.get('report_count_delta')}")
            lines.append(f"- short_trade_only_report_count_delta: {replay_delta.get('short_trade_only_report_count_delta')}")
            lines.append(f"- dual_target_report_count_delta: {replay_delta.get('dual_target_report_count_delta')}")
            lines.append(f"- previous_latest_short_trade_report: {replay_delta.get('previous_latest_short_trade_report')}")
            lines.append(f"- current_latest_short_trade_report: {replay_delta.get('current_latest_short_trade_report')}")
            lines.append(f"- latest_near_miss_delta: {replay_delta.get('latest_near_miss_delta')}")
            lines.append(f"- latest_opportunity_pool_delta: {replay_delta.get('latest_opportunity_pool_delta')}")
        else:
            lines.append(f"- current_report_dir: {replay_delta.get('current_report_dir')}")
            lines.append(f"- previous_report_dir: {replay_delta.get('previous_report_dir')}")
            lines.append(f"- summary_delta: {replay_delta.get('summary_delta')}")
    lines.append("")

    lines.append("## Fast Links")
    for label, source_path in source_paths.items():
        relative_target = _relative_link(source_path, resolved_output_parent)
        if relative_target:
            lines.append(f"- {label}: [{Path(source_path).name}]({relative_target})")
        else:
            lines.append(f"- {label}: {source_path}")
    lines.append("")
    return "\n".join(lines) + "\n"


def build_btst_nightly_control_tower_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    latest_btst_snapshot = _extract_latest_btst_snapshot(manifest)
    control_tower_snapshot = _extract_control_tower_snapshot(manifest)
    control_tower_snapshot["next_actions"] = _prioritize_control_tower_next_actions(latest_btst_snapshot, control_tower_snapshot)
    replay_cohort_snapshot = _extract_replay_cohort_snapshot(manifest)
    priority_board = dict(latest_btst_snapshot.get("priority_board") or {})
    default_merge_review_summary = dict(control_tower_snapshot.get("default_merge_review_summary") or {})
    default_merge_review_ready = (
        str(default_merge_review_summary.get("merge_review_verdict") or "").strip() == "ready_for_default_btst_merge_review"
    )
    effective_brief_recommendation = (
        default_merge_review_summary.get("recommendation")
        if default_merge_review_ready and default_merge_review_summary.get("recommendation")
        else latest_btst_snapshot.get("brief_recommendation") or default_merge_review_summary.get("recommendation")
    )

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

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reports_root": manifest.get("reports_root"),
        "latest_btst_run": manifest.get("latest_btst_run"),
        "refresh_status": {
            "btst_window_evidence_refresh": dict(manifest.get("btst_window_evidence_refresh") or {}).get("status"),
            "candidate_entry_shadow_refresh": dict(manifest.get("candidate_entry_shadow_refresh") or {}).get("status"),
            "btst_score_fail_frontier_refresh": dict(manifest.get("btst_score_fail_frontier_refresh") or {}).get("status"),
            "btst_governance_synthesis_refresh": dict(manifest.get("btst_governance_synthesis_refresh") or {}).get("status"),
            "btst_governance_validation_refresh": dict(manifest.get("btst_governance_validation_refresh") or {}).get("status"),
            "btst_replay_cohort_refresh": dict(manifest.get("btst_replay_cohort_refresh") or {}).get("status"),
            "btst_independent_window_monitor_refresh": dict(manifest.get("btst_independent_window_monitor_refresh") or {}).get("status"),
            "btst_tradeable_opportunity_pool_refresh": dict(manifest.get("btst_tradeable_opportunity_pool_refresh") or {}).get("status"),
        },
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
        "source_paths": {
            "report_manifest_json": str((Path(manifest.get("reports_root") or REPORTS_DIR) / "report_manifest_latest.json").expanduser().resolve()),
            "report_manifest_markdown": str((Path(manifest.get("reports_root") or REPORTS_DIR) / "report_manifest_latest.md").expanduser().resolve()),
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
            "selected_outcome_refresh_markdown": str((Path(manifest.get("reports_root") or REPORTS_DIR) / "btst_selected_outcome_refresh_board_latest.md").expanduser().resolve()),
            "carryover_multiday_continuation_audit_markdown": str((Path(manifest.get("reports_root") or REPORTS_DIR) / "btst_carryover_multiday_continuation_audit_latest.md").expanduser().resolve()),
            "carryover_aligned_peer_harvest_markdown": str((Path(manifest.get("reports_root") or REPORTS_DIR) / "btst_carryover_aligned_peer_harvest_latest.md").expanduser().resolve()),
            "carryover_peer_expansion_markdown": str((Path(manifest.get("reports_root") or REPORTS_DIR) / "btst_carryover_peer_expansion_latest.md").expanduser().resolve()),
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
        },
    }


def render_btst_nightly_control_tower_markdown(payload: dict[str, Any], *, output_parent: str | Path) -> str:
    resolved_output_parent = Path(output_parent).expanduser().resolve()
    latest_btst_run = dict(payload.get("latest_btst_run") or {})
    control_tower_snapshot = dict(payload.get("control_tower_snapshot") or {})
    latest_priority_board_snapshot = dict(payload.get("latest_priority_board_snapshot") or {})
    replay_cohort_snapshot = dict(payload.get("replay_cohort_snapshot") or {})
    latest_btst_snapshot = dict(payload.get("latest_btst_snapshot") or {})
    catalyst_theme_frontier_summary = dict(latest_btst_snapshot.get("catalyst_theme_frontier_summary") or {})
    score_fail_frontier_summary = dict(latest_btst_snapshot.get("score_fail_frontier_summary") or {})
    tradeable_opportunity_pool_summary = dict(control_tower_snapshot.get("tradeable_opportunity_pool") or {})
    no_candidate_entry_action_board_summary = dict(control_tower_snapshot.get("no_candidate_entry_action_board") or {})
    no_candidate_entry_replay_bundle_summary = dict(control_tower_snapshot.get("no_candidate_entry_replay_bundle") or {})
    no_candidate_entry_failure_dossier_summary = dict(control_tower_snapshot.get("no_candidate_entry_failure_dossier") or {})
    watchlist_recall_dossier_summary = dict(control_tower_snapshot.get("watchlist_recall_dossier") or {})
    candidate_pool_recall_dossier_summary = dict(control_tower_snapshot.get("candidate_pool_recall_dossier") or {})
    upstream_shadow_followup_overlay = dict(control_tower_snapshot.get("upstream_shadow_followup_overlay") or {})
    llm_error_digest = dict(latest_btst_snapshot.get("llm_error_digest") or {})
    source_paths = dict(payload.get("source_paths") or {})

    lines: list[str] = []
    lines.append("# BTST Nightly Control Tower")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- generated_at: {payload.get('generated_at')}")
    lines.append(f"- latest_btst_report_dir: {latest_btst_run.get('report_dir')}")
    lines.append(f"- latest_trade_date: {latest_btst_run.get('trade_date')}")
    lines.append(f"- latest_next_trade_date: {latest_btst_run.get('next_trade_date')}")
    lines.append(f"- latest_selection_target: {latest_btst_run.get('selection_target')}")
    lines.append(f"- governance_verdict: {control_tower_snapshot.get('overall_verdict')}")
    lines.append(f"- waiting_lane_count: {control_tower_snapshot.get('waiting_lane_count')}")
    lines.append(f"- ready_lane_count: {control_tower_snapshot.get('ready_lane_count')}")
    lines.append(f"- independent_window_ready_lane_count: {control_tower_snapshot.get('independent_window_ready_lane_count')}")
    lines.append(f"- independent_window_waiting_lane_count: {control_tower_snapshot.get('independent_window_waiting_lane_count')}")
    lines.append(f"- tplus1_tplus2_tradeable_positive_rate: {control_tower_snapshot.get('tplus1_tplus2_tradeable_positive_rate')}")
    lines.append(f"- tplus1_tplus2_tradeable_return_hit_rate: {control_tower_snapshot.get('tplus1_tplus2_tradeable_return_hit_rate')}")
    lines.append(f"- tplus1_tplus2_tradeable_mean_return: {control_tower_snapshot.get('tplus1_tplus2_tradeable_mean_return')}")
    lines.append(f"- tplus1_tplus2_tradeable_verdict: {control_tower_snapshot.get('tplus1_tplus2_tradeable_verdict')}")
    lines.append(f"- tradeable_opportunity_pool_count: {control_tower_snapshot.get('tradeable_opportunity_pool_count')}")
    lines.append(f"- tradeable_opportunity_capture_rate: {control_tower_snapshot.get('tradeable_opportunity_capture_rate')}")
    lines.append(f"- tradeable_opportunity_selected_or_near_miss_rate: {control_tower_snapshot.get('tradeable_opportunity_selected_or_near_miss_rate')}")
    lines.append(f"- tradeable_opportunity_top_kill_switches: {control_tower_snapshot.get('tradeable_opportunity_top_kill_switches')}")
    lines.append(f"- no_candidate_entry_priority_queue_count: {control_tower_snapshot.get('no_candidate_entry_priority_queue_count')}")
    lines.append(f"- no_candidate_entry_priority_tickers_historical: {control_tower_snapshot.get('no_candidate_entry_priority_tickers')}")
    lines.append(f"- no_candidate_entry_priority_tickers_active: {control_tower_snapshot.get('active_no_candidate_entry_priority_tickers')}")
    lines.append(f"- no_candidate_entry_recall_probe_tickers: {control_tower_snapshot.get('no_candidate_entry_recall_probe_tickers')}")
    lines.append(f"- no_candidate_entry_failure_class_counts: {control_tower_snapshot.get('no_candidate_entry_failure_class_counts')}")
    lines.append(f"- no_candidate_entry_handoff_stage_counts: {control_tower_snapshot.get('no_candidate_entry_handoff_stage_counts')}")
    lines.append(f"- no_candidate_entry_absent_from_watchlist_tickers_historical: {control_tower_snapshot.get('no_candidate_entry_absent_from_watchlist_tickers')}")
    lines.append(f"- no_candidate_entry_absent_from_watchlist_tickers_active: {control_tower_snapshot.get('active_no_candidate_entry_absent_from_watchlist_tickers')}")
    lines.append(f"- no_candidate_entry_watchlist_handoff_gap_tickers: {control_tower_snapshot.get('no_candidate_entry_watchlist_handoff_gap_tickers')}")
    lines.append(f"- no_candidate_entry_upstream_absence_tickers: {control_tower_snapshot.get('no_candidate_entry_upstream_absence_tickers')}")
    lines.append(f"- watchlist_recall_stage_counts: {control_tower_snapshot.get('watchlist_recall_stage_counts')}")
    lines.append(f"- watchlist_recall_absent_from_candidate_pool_tickers_historical: {control_tower_snapshot.get('watchlist_recall_absent_from_candidate_pool_tickers')}")
    lines.append(f"- watchlist_recall_absent_from_candidate_pool_tickers_active: {control_tower_snapshot.get('active_watchlist_recall_absent_from_candidate_pool_tickers')}")
    lines.append(f"- watchlist_recall_candidate_pool_layer_b_gap_tickers: {control_tower_snapshot.get('watchlist_recall_candidate_pool_layer_b_gap_tickers')}")
    lines.append(f"- watchlist_recall_layer_b_watchlist_gap_tickers: {control_tower_snapshot.get('watchlist_recall_layer_b_watchlist_gap_tickers')}")
    lines.append(f"- candidate_pool_recall_stage_counts: {control_tower_snapshot.get('candidate_pool_recall_stage_counts')}")
    lines.append(f"- candidate_pool_recall_dominant_stage: {control_tower_snapshot.get('candidate_pool_recall_dominant_stage')}")
    lines.append(f"- candidate_pool_recall_top_stage_tickers: {control_tower_snapshot.get('candidate_pool_recall_top_stage_tickers')}")
    lines.append(f"- candidate_pool_recall_truncation_frontier_summary: {control_tower_snapshot.get('candidate_pool_recall_truncation_frontier_summary')}")
    lines.append(f"- candidate_pool_recall_dominant_ranking_driver: {control_tower_snapshot.get('candidate_pool_recall_dominant_ranking_driver')}")
    lines.append(f"- candidate_pool_recall_dominant_liquidity_gap_mode: {control_tower_snapshot.get('candidate_pool_recall_dominant_liquidity_gap_mode')}")
    lines.append(f"- candidate_pool_recall_focus_liquidity_profiles: {control_tower_snapshot.get('candidate_pool_recall_focus_liquidity_profiles')}")
    lines.append(f"- candidate_pool_recall_priority_handoff_counts: {control_tower_snapshot.get('candidate_pool_recall_priority_handoff_counts')}")
    lines.append(f"- candidate_pool_recall_priority_handoff_branch_diagnoses: {control_tower_snapshot.get('candidate_pool_recall_priority_handoff_branch_diagnoses')}")
    lines.append(f"- candidate_pool_recall_priority_handoff_branch_mechanisms: {control_tower_snapshot.get('candidate_pool_recall_priority_handoff_branch_mechanisms')}")
    branch_experiment_queue = list(control_tower_snapshot.get("candidate_pool_recall_priority_handoff_branch_experiment_queue") or [])
    lines.append("- candidate_pool_recall_priority_handoff_branch_experiment_queue: structured_summary")
    lines.append(f"- candidate_pool_recall_priority_handoff_branch_experiment_queue_count: {len(branch_experiment_queue)}")
    for experiment in branch_experiment_queue[:3]:
        lines.append(
            f"- candidate_pool_recall_branch_experiment: task_id={experiment.get('task_id')} handoff={experiment.get('priority_handoff')} readiness={experiment.get('prototype_readiness')} tickers={experiment.get('tickers')}"
        )
        lines.append(f"  prototype_summary: {experiment.get('prototype_summary')}")
        lines.append(f"  evaluation_summary: {experiment.get('evaluation_summary')}")
        lines.append(f"  guardrail_summary: {experiment.get('guardrail_summary')}")
    lines.append(f"- candidate_pool_branch_priority_board_status: {control_tower_snapshot.get('candidate_pool_branch_priority_board_status')}")
    lines.append(f"- candidate_pool_branch_priority_alignment_status: {control_tower_snapshot.get('candidate_pool_branch_priority_alignment_status')}")
    if control_tower_snapshot.get("candidate_pool_branch_priority_alignment_summary"):
        lines.append(f"- candidate_pool_branch_priority_alignment_summary: {control_tower_snapshot.get('candidate_pool_branch_priority_alignment_summary')}")
    for row in list(control_tower_snapshot.get("candidate_pool_branch_priority_board_rows") or [])[:3]:
        lines.append(
            f"- candidate_pool_branch_priority: handoff={row.get('priority_handoff')} readiness={row.get('prototype_readiness')} execution_priority_rank={row.get('execution_priority_rank')} tickers={row.get('tickers')}"
        )
    lines.append(f"- candidate_pool_lane_objective_support_status: {control_tower_snapshot.get('candidate_pool_lane_objective_support_status')}")
    for row in list(control_tower_snapshot.get("candidate_pool_lane_objective_support_rows") or [])[:3]:
        lines.append(
            f"- candidate_pool_lane_objective_support: handoff={row.get('priority_handoff')} verdict={row.get('support_verdict')} closed_cycle_count={row.get('closed_cycle_count')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')}"
        )
    lines.append(f"- candidate_pool_corridor_validation_pack_status: {control_tower_snapshot.get('candidate_pool_corridor_validation_pack_status')}")
    corridor_validation_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_validation_pack_summary") or {})
    if corridor_validation_summary:
        lines.append(
            f"- candidate_pool_corridor_validation_pack_summary: pack_status={corridor_validation_summary.get('pack_status')} primary_validation_ticker={corridor_validation_summary.get('primary_validation_ticker')} parallel_watch_tickers={corridor_validation_summary.get('parallel_watch_tickers')}"
        )
    lines.append(f"- candidate_pool_corridor_shadow_pack_status: {control_tower_snapshot.get('candidate_pool_corridor_shadow_pack_status')}")
    corridor_shadow_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_shadow_pack_summary") or {})
    if corridor_shadow_summary:
        lines.append(
            f"- candidate_pool_corridor_shadow_pack_summary: shadow_status={corridor_shadow_summary.get('shadow_status')} primary_shadow_replay={corridor_shadow_summary.get('primary_shadow_replay')} parallel_watch_tickers={corridor_shadow_summary.get('parallel_watch_tickers')}"
        )
    lines.append(f"- candidate_pool_rebucket_shadow_pack_status: {control_tower_snapshot.get('candidate_pool_rebucket_shadow_pack_status')}")
    rebucket_experiment = dict(control_tower_snapshot.get("candidate_pool_rebucket_shadow_pack_experiment") or {})
    if rebucket_experiment:
        lines.append(
            f"- candidate_pool_rebucket_shadow_pack_experiment: handoff={rebucket_experiment.get('priority_handoff')} readiness={rebucket_experiment.get('prototype_readiness')} tickers={rebucket_experiment.get('tickers')}"
        )
    lines.append(f"- candidate_pool_rebucket_objective_validation_status: {control_tower_snapshot.get('candidate_pool_rebucket_objective_validation_status')}")
    rebucket_validation_summary = dict(control_tower_snapshot.get("candidate_pool_rebucket_objective_validation_summary") or {})
    if rebucket_validation_summary:
        lines.append(
            f"- candidate_pool_rebucket_objective_validation_summary: validation_status={rebucket_validation_summary.get('validation_status')} support_verdict={rebucket_validation_summary.get('support_verdict')} mean_t_plus_2_return={rebucket_validation_summary.get('mean_t_plus_2_return')}"
        )
    lines.append(f"- candidate_pool_rebucket_comparison_bundle_status: {control_tower_snapshot.get('candidate_pool_rebucket_comparison_bundle_status')}")
    rebucket_comparison_summary = dict(control_tower_snapshot.get("candidate_pool_rebucket_comparison_bundle_summary") or {})
    if rebucket_comparison_summary:
        lines.append(
            f"- candidate_pool_rebucket_comparison_bundle_summary: bundle_status={rebucket_comparison_summary.get('bundle_status')} structural_leader={rebucket_comparison_summary.get('structural_leader')} objective_leader={rebucket_comparison_summary.get('objective_leader')}"
        )
    lines.append(f"- candidate_pool_lane_pair_board_status: {control_tower_snapshot.get('candidate_pool_lane_pair_board_status')}")
    lane_pair_board_summary = dict(control_tower_snapshot.get("candidate_pool_lane_pair_board_summary") or {})
    if lane_pair_board_summary:
        lines.append(
            f"- candidate_pool_lane_pair_board_summary: pair_status={lane_pair_board_summary.get('pair_status')} board_leader={lane_pair_board_summary.get('board_leader')} leader_lane_family={lane_pair_board_summary.get('leader_lane_family')} leader_governance_status={lane_pair_board_summary.get('leader_governance_status')} leader_governance_execution_quality={lane_pair_board_summary.get('leader_governance_execution_quality')} leader_governance_entry_timing_bias={lane_pair_board_summary.get('leader_governance_entry_timing_bias')} parallel_watch_ticker={lane_pair_board_summary.get('parallel_watch_ticker')} parallel_watch_governance_blocker={lane_pair_board_summary.get('parallel_watch_governance_blocker')} parallel_watch_same_source_sample_count={lane_pair_board_summary.get('parallel_watch_same_source_sample_count')} parallel_watch_next_close_positive_rate={lane_pair_board_summary.get('parallel_watch_next_close_positive_rate')} parallel_watch_next_close_return_mean={lane_pair_board_summary.get('parallel_watch_next_close_return_mean')}"
        )
    continuation_focus_summary = dict(control_tower_snapshot.get("continuation_focus_summary") or {})
    if continuation_focus_summary:
        lines.append(
            f"- continuation_focus_summary: focus_ticker={continuation_focus_summary.get('focus_ticker')} promotion_review_verdict={continuation_focus_summary.get('promotion_review_verdict')} promotion_gate_verdict={continuation_focus_summary.get('promotion_gate_verdict')} watchlist_execution_verdict={continuation_focus_summary.get('watchlist_execution_verdict')} focus_watch_validation_status={continuation_focus_summary.get('focus_watch_validation_status')} focus_watch_recent_supporting_window_count={continuation_focus_summary.get('focus_watch_recent_supporting_window_count')} eligible_gate_verdict={continuation_focus_summary.get('eligible_gate_verdict')} execution_gate_verdict={continuation_focus_summary.get('execution_gate_verdict')} execution_gate_blockers={continuation_focus_summary.get('execution_gate_blockers')} execution_overlay_verdict={continuation_focus_summary.get('execution_overlay_verdict')} execution_overlay_promotion_blocker={continuation_focus_summary.get('execution_overlay_promotion_blocker')} execution_overlay_persistence_requirement={continuation_focus_summary.get('execution_overlay_persistence_requirement')} execution_overlay_lane_support_ratio={continuation_focus_summary.get('execution_overlay_lane_support_ratio')} governance_status={continuation_focus_summary.get('governance_status')}"
        )
    continuation_promotion_ready_summary = dict(control_tower_snapshot.get("continuation_promotion_ready_summary") or {})
    if continuation_promotion_ready_summary:
        lines.append(
            f"- continuation_promotion_ready_summary: focus_ticker={continuation_promotion_ready_summary.get('focus_ticker')} promotion_path_status={continuation_promotion_ready_summary.get('promotion_path_status')} blockers_remaining_count={continuation_promotion_ready_summary.get('blockers_remaining_count')} observed_independent_window_count={continuation_promotion_ready_summary.get('observed_independent_window_count')} missing_independent_window_count={continuation_promotion_ready_summary.get('missing_independent_window_count')} candidate_dossier_support_trade_date_count={continuation_promotion_ready_summary.get('candidate_dossier_support_trade_date_count')} candidate_dossier_same_trade_date_variant_count={continuation_promotion_ready_summary.get('candidate_dossier_same_trade_date_variant_count')} persistence_verdict={continuation_promotion_ready_summary.get('persistence_verdict')} provisional_default_btst_edge_verdict={continuation_promotion_ready_summary.get('provisional_default_btst_edge_verdict')} edge_threshold_verdict={continuation_promotion_ready_summary.get('edge_threshold_verdict')} promotion_merge_review_verdict={continuation_promotion_ready_summary.get('promotion_merge_review_verdict')} ready_after_next_qualifying_window={continuation_promotion_ready_summary.get('ready_after_next_qualifying_window')} next_window_requirement={continuation_promotion_ready_summary.get('next_window_requirement')} next_window_duplicate_trade_date_verdict={continuation_promotion_ready_summary.get('next_window_duplicate_trade_date_verdict')} next_window_quality_requirement={continuation_promotion_ready_summary.get('next_window_quality_requirement')} next_window_disqualified_bucket_verdict={continuation_promotion_ready_summary.get('next_window_disqualified_bucket_verdict')} next_window_qualified_merge_review_verdict={continuation_promotion_ready_summary.get('next_window_qualified_merge_review_verdict')} t_plus_2_positive_rate_delta_vs_default_btst={continuation_promotion_ready_summary.get('t_plus_2_positive_rate_delta_vs_default_btst')} t_plus_2_mean_return_delta_vs_default_btst={continuation_promotion_ready_summary.get('t_plus_2_mean_return_delta_vs_default_btst')}"
        )
    corridor_window_diagnostics_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_window_diagnostics_summary") or {})
    if corridor_window_diagnostics_summary:
        near_miss_window = dict(corridor_window_diagnostics_summary.get("near_miss_upgrade_window") or {})
        visibility_gap_window = dict(corridor_window_diagnostics_summary.get("visibility_gap_window") or {})
        lines.append(
            f"- candidate_pool_corridor_window_diagnostics_summary: focus_ticker={corridor_window_diagnostics_summary.get('focus_ticker')} near_miss_trade_date={near_miss_window.get('trade_date')} near_miss_verdict={near_miss_window.get('verdict')} visibility_gap_verdict={visibility_gap_window.get('verdict')} recoverable_report_dir_count={visibility_gap_window.get('recoverable_report_dir_count')}"
        )
    corridor_narrow_probe_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_narrow_probe_summary") or {})
    if corridor_narrow_probe_summary:
        deepest_corridor_focus_tickers = list(corridor_narrow_probe_summary.get("deepest_corridor_focus_tickers") or [])
        if deepest_corridor_focus_tickers:
            lines.append(
                f"- candidate_pool_corridor_narrow_probe_summary: focus_ticker={corridor_narrow_probe_summary.get('focus_ticker')} verdict={corridor_narrow_probe_summary.get('verdict')} deepest_corridor_focus_tickers={deepest_corridor_focus_tickers} excluded_low_gate_tail_tickers={corridor_narrow_probe_summary.get('excluded_low_gate_tail_tickers')} low_gate_focus_max_cutoff_share={corridor_narrow_probe_summary.get('low_gate_focus_max_cutoff_share')}"
            )
        else:
            lines.append(
                f"- candidate_pool_corridor_narrow_probe_summary: focus_ticker={corridor_narrow_probe_summary.get('focus_ticker')} verdict={corridor_narrow_probe_summary.get('verdict')} threshold_override_gap_vs_anchor={corridor_narrow_probe_summary.get('threshold_override_gap_vs_anchor')} target_gap_to_selected={corridor_narrow_probe_summary.get('target_gap_to_selected')}"
            )
    default_merge_review_summary = dict(control_tower_snapshot.get("default_merge_review_summary") or {})
    if default_merge_review_summary:
        counterfactual = dict(default_merge_review_summary.get("counterfactual_validation") or {})
        lines.append(
            f"- default_merge_review_summary: focus_ticker={default_merge_review_summary.get('focus_ticker')} merge_review_verdict={default_merge_review_summary.get('merge_review_verdict')} operator_action={default_merge_review_summary.get('operator_action')} counterfactual_verdict={counterfactual.get('counterfactual_verdict')} t_plus_2_positive_rate_delta_vs_default_btst={default_merge_review_summary.get('t_plus_2_positive_rate_delta_vs_default_btst')} t_plus_2_positive_rate_margin_vs_threshold={counterfactual.get('t_plus_2_positive_rate_margin_vs_threshold')} t_plus_2_mean_return_delta_vs_default_btst={default_merge_review_summary.get('t_plus_2_mean_return_delta_vs_default_btst')} t_plus_2_mean_return_margin_vs_threshold={counterfactual.get('t_plus_2_mean_return_margin_vs_threshold')}"
        )
    default_merge_historical_counterfactual_summary = dict(control_tower_snapshot.get("default_merge_historical_counterfactual_summary") or {})
    if default_merge_historical_counterfactual_summary:
        uplift = dict(default_merge_historical_counterfactual_summary.get("uplift_vs_default_btst") or {})
        lines.append(
            f"- default_merge_historical_counterfactual_summary: focus_ticker={default_merge_historical_counterfactual_summary.get('focus_ticker')} counterfactual_verdict={default_merge_historical_counterfactual_summary.get('counterfactual_verdict')} merged_positive_rate_uplift={uplift.get('t_plus_2_positive_rate_uplift')} merged_mean_return_uplift={uplift.get('mean_t_plus_2_return_uplift')}"
        )
    continuation_merge_candidate_ranking_summary = dict(control_tower_snapshot.get("continuation_merge_candidate_ranking_summary") or {})
    if continuation_merge_candidate_ranking_summary:
        top_candidate = dict(continuation_merge_candidate_ranking_summary.get("top_candidate") or {})
        lines.append(
            f"- continuation_merge_candidate_ranking_summary: candidate_count={continuation_merge_candidate_ranking_summary.get('candidate_count')} top_ticker={top_candidate.get('ticker')} top_stage={top_candidate.get('promotion_path_status') or top_candidate.get('promotion_readiness_verdict')} top_positive_rate_delta={top_candidate.get('t_plus_2_positive_rate_delta_vs_default_btst')} top_mean_return_delta={top_candidate.get('mean_t_plus_2_return_delta_vs_default_btst')}"
        )
    default_merge_strict_counterfactual_summary = dict(control_tower_snapshot.get("default_merge_strict_counterfactual_summary") or {})
    if default_merge_strict_counterfactual_summary:
        uplift = dict(default_merge_strict_counterfactual_summary.get("strict_uplift_vs_default_btst") or {})
        overlap = dict(default_merge_strict_counterfactual_summary.get("overlap_diagnostics") or {})
        lines.append(
            f"- default_merge_strict_counterfactual_summary: focus_ticker={default_merge_strict_counterfactual_summary.get('focus_ticker')} strict_counterfactual_verdict={default_merge_strict_counterfactual_summary.get('strict_counterfactual_verdict')} overlap_case_count={overlap.get('overlap_case_count')} strict_positive_rate_uplift={uplift.get('t_plus_2_positive_rate_uplift')} strict_mean_return_uplift={uplift.get('mean_t_plus_2_return_uplift')}"
        )
    merge_replay_validation_summary = dict(control_tower_snapshot.get("merge_replay_validation_summary") or {})
    if merge_replay_validation_summary:
        lines.append(
            f"- merge_replay_validation_summary: overall_verdict={merge_replay_validation_summary.get('overall_verdict')} focus_tickers={merge_replay_validation_summary.get('focus_tickers')} promoted_to_selected_count={merge_replay_validation_summary.get('promoted_to_selected_count')} promoted_to_near_miss_count={merge_replay_validation_summary.get('promoted_to_near_miss_count')} relief_applied_count={merge_replay_validation_summary.get('relief_applied_count')} relief_actionable_applied_count={merge_replay_validation_summary.get('relief_actionable_applied_count')} relief_already_selected_count={merge_replay_validation_summary.get('relief_already_selected_count')} relief_positive_promotion_precision={merge_replay_validation_summary.get('relief_positive_promotion_precision')} relief_actionable_positive_promotion_precision={merge_replay_validation_summary.get('relief_actionable_positive_promotion_precision')} relief_no_promotion_ratio={merge_replay_validation_summary.get('relief_no_promotion_ratio')} relief_actionable_no_promotion_ratio={merge_replay_validation_summary.get('relief_actionable_no_promotion_ratio')} relief_decision_deteriorated_count={merge_replay_validation_summary.get('relief_decision_deteriorated_count')} recommended_next_lever={merge_replay_validation_summary.get('recommended_next_lever')} recommended_signal_levers={merge_replay_validation_summary.get('recommended_signal_levers')}"
        )
    transient_probe_summary = dict(control_tower_snapshot.get("transient_probe_summary") or {})
    if transient_probe_summary:
        lines.append(
            f"- transient_probe_summary: ticker={transient_probe_summary.get('ticker')} status={transient_probe_summary.get('status')} blocker={transient_probe_summary.get('blocker')} candidate_source={transient_probe_summary.get('candidate_source')} score_state={transient_probe_summary.get('score_state')} downstream_bottleneck={transient_probe_summary.get('downstream_bottleneck')} historical_sample_count={transient_probe_summary.get('historical_sample_count')} historical_next_close_positive_rate={transient_probe_summary.get('historical_next_close_positive_rate')}"
        )
    execution_constraint_rollup = dict(control_tower_snapshot.get("execution_constraint_rollup") or {})
    if execution_constraint_rollup:
        lines.append(
            f"- execution_constraint_rollup: constraint_count={execution_constraint_rollup.get('constraint_count')} continuation_focus_tickers={execution_constraint_rollup.get('continuation_focus_tickers')} continuation_blockers={execution_constraint_rollup.get('continuation_blockers')} shadow_focus_tickers={execution_constraint_rollup.get('shadow_focus_tickers')} shadow_blockers={execution_constraint_rollup.get('shadow_blockers')}"
        )
    lines.append(f"- candidate_pool_upstream_handoff_board_status: {control_tower_snapshot.get('candidate_pool_upstream_handoff_board_status')}")
    upstream_handoff_summary = dict(control_tower_snapshot.get("candidate_pool_upstream_handoff_board_summary") or {})
    if upstream_handoff_summary:
        lines.append(
            f"- candidate_pool_upstream_handoff_board_summary: board_status={upstream_handoff_summary.get('board_status')} focus_tickers={upstream_handoff_summary.get('focus_tickers')} first_broken_handoff_counts={upstream_handoff_summary.get('first_broken_handoff_counts')}"
        )
    lines.append(f"- candidate_pool_upstream_handoff_focus_tickers_active: {control_tower_snapshot.get('active_candidate_pool_upstream_handoff_focus_tickers')}")
    lines.append(f"- upstream_shadow_followup_validated_tickers: {control_tower_snapshot.get('upstream_shadow_followup_validated_tickers')}")
    lines.append(f"- upstream_shadow_followup_decision_counts: {control_tower_snapshot.get('upstream_shadow_followup_decision_counts')}")
    lines.append(f"- upstream_shadow_followup_near_miss_tickers: {control_tower_snapshot.get('upstream_shadow_followup_near_miss_tickers')}")
    lines.append(f"- upstream_shadow_followup_rejected_profitability_tickers: {control_tower_snapshot.get('upstream_shadow_followup_rejected_profitability_tickers')}")
    lines.append(f"- candidate_pool_corridor_uplift_runbook_status: {control_tower_snapshot.get('candidate_pool_corridor_uplift_runbook_status')}")
    corridor_uplift_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_uplift_runbook_summary") or {})
    if corridor_uplift_summary:
        lines.append(
            f"- candidate_pool_corridor_uplift_runbook_summary: runbook_status={corridor_uplift_summary.get('runbook_status')} primary_shadow_replay={corridor_uplift_summary.get('primary_shadow_replay')} parallel_watch_tickers={corridor_uplift_summary.get('parallel_watch_tickers')}"
        )
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
    lines.append("")

    lines.append("## Nightly Summary")
    lines.append(f"- control_tower_recommendation: {control_tower_snapshot.get('recommendation')}")
    lines.append(f"- priority_board_headline: {latest_priority_board_snapshot.get('headline')}")
    lines.append(f"- replay_recommendation: {replay_cohort_snapshot.get('recommendation')}")
    lines.append(f"- tradeable_opportunity_recommendation: {tradeable_opportunity_pool_summary.get('recommendation')}")
    lines.append(f"- no_candidate_entry_action_recommendation: {no_candidate_entry_action_board_summary.get('recommendation')}")
    lines.append(f"- no_candidate_entry_replay_recommendation: {no_candidate_entry_replay_bundle_summary.get('recommendation')}")
    lines.append(f"- no_candidate_entry_failure_dossier_recommendation: {no_candidate_entry_failure_dossier_summary.get('recommendation')}")
    lines.append(f"- watchlist_recall_dossier_recommendation: {watchlist_recall_dossier_summary.get('recommendation')}")
    lines.append(f"- candidate_pool_recall_dossier_recommendation: {candidate_pool_recall_dossier_summary.get('recommendation')}")
    selected_outcome_refresh_summary = dict(control_tower_snapshot.get("selected_outcome_refresh_summary") or {})
    if selected_outcome_refresh_summary:
        lines.append(
            f"- selected_outcome_refresh_summary: focus_ticker={selected_outcome_refresh_summary.get('focus_ticker')} focus_cycle_status={selected_outcome_refresh_summary.get('focus_cycle_status')} focus_overall_contract_verdict={selected_outcome_refresh_summary.get('focus_overall_contract_verdict')}"
        )
    carryover_multiday_continuation_audit_summary = dict(control_tower_snapshot.get("carryover_multiday_continuation_audit_summary") or {})
    if carryover_multiday_continuation_audit_summary:
        lines.append(
            f"- carryover_multiday_continuation_audit_summary: selected_ticker={carryover_multiday_continuation_audit_summary.get('selected_ticker')} selected_path_t2_bias_only={carryover_multiday_continuation_audit_summary.get('selected_path_t2_bias_only')} broad_family_only_multiday_unsupported={carryover_multiday_continuation_audit_summary.get('broad_family_only_multiday_unsupported')} aligned_peer_multiday_ready={carryover_multiday_continuation_audit_summary.get('aligned_peer_multiday_ready')}"
        )
    carryover_aligned_peer_harvest_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_harvest_summary") or {})
    if carryover_aligned_peer_harvest_summary:
        lines.append(
            f"- carryover_aligned_peer_harvest_summary: focus_ticker={carryover_aligned_peer_harvest_summary.get('focus_ticker')} focus_status={carryover_aligned_peer_harvest_summary.get('focus_status')} fresh_open_cycle_tickers={carryover_aligned_peer_harvest_summary.get('fresh_open_cycle_tickers')}"
        )
    carryover_peer_expansion_summary = dict(control_tower_snapshot.get("carryover_peer_expansion_summary") or {})
    if carryover_peer_expansion_summary:
        lines.append(
            f"- carryover_peer_expansion_summary: focus_ticker={carryover_peer_expansion_summary.get('focus_ticker')} focus_status={carryover_peer_expansion_summary.get('focus_status')} priority_expansion_tickers={carryover_peer_expansion_summary.get('priority_expansion_tickers')} watch_with_risk_tickers={carryover_peer_expansion_summary.get('watch_with_risk_tickers')}"
        )
    carryover_aligned_peer_proof_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_proof_summary") or {})
    if carryover_aligned_peer_proof_summary:
        lines.append(
            f"- carryover_aligned_peer_proof_summary: focus_ticker={carryover_aligned_peer_proof_summary.get('focus_ticker')} focus_proof_verdict={carryover_aligned_peer_proof_summary.get('focus_proof_verdict')} focus_promotion_review_verdict={carryover_aligned_peer_proof_summary.get('focus_promotion_review_verdict')} ready_for_promotion_review_tickers={carryover_aligned_peer_proof_summary.get('ready_for_promotion_review_tickers')} risk_review_tickers={carryover_aligned_peer_proof_summary.get('risk_review_tickers')}"
        )
    carryover_peer_promotion_gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})
    if carryover_peer_promotion_gate_summary:
        lines.append(
            f"- carryover_peer_promotion_gate_summary: focus_ticker={carryover_peer_promotion_gate_summary.get('focus_ticker')} focus_gate_verdict={carryover_peer_promotion_gate_summary.get('focus_gate_verdict')} ready_tickers={carryover_peer_promotion_gate_summary.get('ready_tickers')} blocked_open_tickers={carryover_peer_promotion_gate_summary.get('blocked_open_tickers')} pending_t_plus_2_tickers={carryover_peer_promotion_gate_summary.get('pending_t_plus_2_tickers')}"
        )
    lines.append(f"- upstream_shadow_followup_overlay_recommendation: {control_tower_snapshot.get('upstream_shadow_followup_recommendation')}")
    if upstream_shadow_followup_overlay.get("validated_tickers"):
        lines.append(
            f"- upstream_backlog_interpretation_note: 以下 no-entry/watchlist/candidate-pool 建议仍是历史 backlog 画像；当前 active upstream recall 已收敛到 {upstream_shadow_followup_overlay.get('active_no_candidate_entry_priority_tickers')}。"
        )
    lines.append(f"- candidate_pool_recall_dossier_truncation_frontier_summary: {candidate_pool_recall_dossier_summary.get('truncation_frontier_summary')}")
    lines.append(f"- catalyst_frontier_recommendation: {catalyst_theme_frontier_summary.get('recommendation')}")
    lines.append(f"- score_fail_frontier_recommendation: {score_fail_frontier_summary.get('recommendation')}")
    lines.append(f"- llm_recommendation: {llm_error_digest.get('recommendation')}")
    lines.append("")

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
        lines.append(
            f"- followup_row: ticker={row.get('ticker')} decision={row.get('decision')} downstream_bottleneck={row.get('downstream_bottleneck')} top_reasons={row.get('top_reasons')}"
        )
    lines.append("")

    lines.append("## Control Tower Snapshot")
    lines.append(f"- lane_status_counts: {control_tower_snapshot.get('lane_status_counts')}")
    lines.append(f"- warn_count: {control_tower_snapshot.get('warn_count')}")
    lines.append(f"- fail_count: {control_tower_snapshot.get('fail_count')}")
    if selected_outcome_refresh_summary:
        lines.append(
            f"- selected_outcome_contract: focus_ticker={selected_outcome_refresh_summary.get('focus_ticker')} overall_contract_verdict={selected_outcome_refresh_summary.get('focus_overall_contract_verdict')} focus_cycle_status={selected_outcome_refresh_summary.get('focus_cycle_status')}"
        )
    if carryover_multiday_continuation_audit_summary:
        lines.append(
            f"- carryover_multiday_contract: selected_ticker={carryover_multiday_continuation_audit_summary.get('selected_ticker')} selected_path_t2_bias_only={carryover_multiday_continuation_audit_summary.get('selected_path_t2_bias_only')} broad_family_only_multiday_unsupported={carryover_multiday_continuation_audit_summary.get('broad_family_only_multiday_unsupported')}"
        )
    if carryover_aligned_peer_harvest_summary:
        lines.append(
            f"- carryover_peer_harvest_focus: focus_ticker={carryover_aligned_peer_harvest_summary.get('focus_ticker')} focus_status={carryover_aligned_peer_harvest_summary.get('focus_status')} fresh_open_cycle_tickers={carryover_aligned_peer_harvest_summary.get('fresh_open_cycle_tickers')}"
        )
    if carryover_peer_expansion_summary:
        lines.append(
            f"- carryover_peer_expansion_focus: focus_ticker={carryover_peer_expansion_summary.get('focus_ticker')} focus_status={carryover_peer_expansion_summary.get('focus_status')} priority_expansion_tickers={carryover_peer_expansion_summary.get('priority_expansion_tickers')} watch_with_risk_tickers={carryover_peer_expansion_summary.get('watch_with_risk_tickers')}"
        )
    if carryover_aligned_peer_proof_summary:
        lines.append(
            f"- carryover_peer_proof_focus: focus_ticker={carryover_aligned_peer_proof_summary.get('focus_ticker')} focus_promotion_review_verdict={carryover_aligned_peer_proof_summary.get('focus_promotion_review_verdict')} ready_for_promotion_review_tickers={carryover_aligned_peer_proof_summary.get('ready_for_promotion_review_tickers')} risk_review_tickers={carryover_aligned_peer_proof_summary.get('risk_review_tickers')}"
        )
    if carryover_peer_promotion_gate_summary:
        lines.append(
            f"- carryover_peer_promotion_gate_focus: focus_ticker={carryover_peer_promotion_gate_summary.get('focus_ticker')} focus_gate_verdict={carryover_peer_promotion_gate_summary.get('focus_gate_verdict')} ready_tickers={carryover_peer_promotion_gate_summary.get('ready_tickers')} blocked_open_tickers={carryover_peer_promotion_gate_summary.get('blocked_open_tickers')} pending_t_plus_2_tickers={carryover_peer_promotion_gate_summary.get('pending_t_plus_2_tickers')}"
        )
    for frontier in list(control_tower_snapshot.get("closed_frontiers") or []):
        lines.append(
            f"- closed_frontier: {frontier.get('frontier_id')} status={frontier.get('status')} passing_variant_count={frontier.get('passing_variant_count')}"
        )
        lines.append(f"  headline: {frontier.get('headline')}")
        lines.append(f"  best_variant: {frontier.get('best_variant_name')}")
    for task in list(control_tower_snapshot.get("next_actions") or []):
        lines.append(f"- next_action: {task.get('title')}")
        lines.append(f"  why_now: {task.get('why_now')}")
        lines.append(f"  next_step: {task.get('next_step')}")
    lines.append("")

    lines.append("## Rollout Lanes")
    rollout_lanes = list(control_tower_snapshot.get("rollout_lanes") or [])
    if not rollout_lanes:
        lines.append("- unavailable")
    else:
        for row in rollout_lanes:
            lines.append(
                f"- lane_id={row.get('lane_id')} ticker={row.get('ticker')} governance_tier={row.get('governance_tier')} lane_status={row.get('lane_status')} blocker={row.get('blocker')}"
            )
            lines.append(f"  validation_verdict: {row.get('validation_verdict')}")
            lines.append(f"  missing_window_count: {row.get('missing_window_count')}")
            lines.append(f"  next_step: {row.get('next_step')}")
    lines.append("")

    lines.append("## Independent Window Monitor")
    independent_window_monitor = dict(control_tower_snapshot.get("independent_window_monitor") or {})
    if not independent_window_monitor:
        lines.append("- unavailable")
    else:
        lines.append(f"- report_dir_count: {independent_window_monitor.get('report_dir_count')}")
        lines.append(f"- recommendation: {independent_window_monitor.get('recommendation')}")
        for row in list(independent_window_monitor.get("rows") or []):
            lines.append(
                f"- ticker={row.get('ticker')} lane_id={row.get('lane_id')} readiness={row.get('readiness')} distinct_window_count={row.get('distinct_window_count')} missing_window_count={row.get('missing_window_count')}"
            )
            lines.append(f"  next_step: {row.get('next_step')}")
    lines.append("")

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
            lines.append(
                f"- ticker_objective_leader: {row.get('group_label')} closed_cycle_count={row.get('closed_cycle_count')} positive_rate={row.get('t_plus_2_positive_rate')} return_hit_rate={row.get('t_plus_2_return_hit_rate_at_target')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')}"
            )
    lines.append("")

    lines.append("## Tradeable Opportunity Pool")
    if not tradeable_opportunity_pool_summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {tradeable_opportunity_pool_summary.get('status')}")
        lines.append(f"- result_truth_pool_count: {tradeable_opportunity_pool_summary.get('result_truth_pool_count')}")
        lines.append(f"- tradeable_opportunity_pool_count: {tradeable_opportunity_pool_summary.get('tradeable_opportunity_pool_count')}")
        lines.append(f"- system_recall_count: {tradeable_opportunity_pool_summary.get('system_recall_count')}")
        lines.append(f"- selected_or_near_miss_count: {tradeable_opportunity_pool_summary.get('selected_or_near_miss_count')}")
        lines.append(f"- main_execution_pool_count: {tradeable_opportunity_pool_summary.get('main_execution_pool_count')}")
        lines.append(f"- strict_goal_case_count: {tradeable_opportunity_pool_summary.get('strict_goal_case_count')}")
        lines.append(f"- strict_goal_false_negative_count: {tradeable_opportunity_pool_summary.get('strict_goal_false_negative_count')}")
        lines.append(f"- tradeable_pool_capture_rate: {tradeable_opportunity_pool_summary.get('tradeable_pool_capture_rate')}")
        lines.append(f"- tradeable_pool_selected_or_near_miss_rate: {tradeable_opportunity_pool_summary.get('tradeable_pool_selected_or_near_miss_rate')}")
        lines.append(f"- tradeable_pool_main_execution_rate: {tradeable_opportunity_pool_summary.get('tradeable_pool_main_execution_rate')}")
        lines.append(f"- no_candidate_entry_count: {tradeable_opportunity_pool_summary.get('no_candidate_entry_count')}")
        lines.append(f"- no_candidate_entry_share_of_tradeable_pool: {tradeable_opportunity_pool_summary.get('no_candidate_entry_share_of_tradeable_pool')}")
        lines.append(f"- top_no_candidate_entry_industries: {tradeable_opportunity_pool_summary.get('top_no_candidate_entry_industries')}")
        lines.append(f"- top_no_candidate_entry_tickers: {tradeable_opportunity_pool_summary.get('top_no_candidate_entry_tickers')}")
        lines.append(f"- top_tradeable_kill_switch_labels: {tradeable_opportunity_pool_summary.get('top_tradeable_kill_switch_labels')}")
        for row in list(tradeable_opportunity_pool_summary.get("top_tradeable_kill_switches") or []):
            lines.append(f"- top_tradeable_kill_switch: {row.get('kill_switch')} count={row.get('count')}")
        for row in list(tradeable_opportunity_pool_summary.get("top_strict_goal_false_negative_rows") or []):
            lines.append(
                f"- top_strict_goal_false_negative: {row.get('trade_date')} {row.get('ticker')} kill_switch={row.get('first_kill_switch')} t_plus_2_close_return={row.get('t_plus_2_close_return')}"
            )
        lines.append(f"- recommendation: {tradeable_opportunity_pool_summary.get('recommendation')}")
    lines.append("")

    lines.append("## No Candidate Entry Action Board")
    if upstream_shadow_followup_overlay.get("validated_tickers"):
        lines.append(
            f"- note: 本 section 保留历史 no-entry backlog 排名；当前 active upstream recall 已收敛到 {upstream_shadow_followup_overlay.get('active_no_candidate_entry_priority_tickers')}，已正式 followup 验证的票请转看上面的 Latest Upstream Shadow Followup Overlay。"
        )
    if not no_candidate_entry_action_board_summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {no_candidate_entry_action_board_summary.get('status')}")
        lines.append(f"- priority_queue_count: {no_candidate_entry_action_board_summary.get('priority_queue_count')}")
        lines.append(f"- top_priority_tickers: {no_candidate_entry_action_board_summary.get('top_priority_tickers')}")
        lines.append(f"- top_hotspot_report_dirs: {no_candidate_entry_action_board_summary.get('top_hotspot_report_dirs')}")
        for row in list(no_candidate_entry_action_board_summary.get("priority_queue") or []):
            lines.append(
                f"- no_candidate_entry_priority: {row.get('ticker')} action_tier={row.get('action_tier')} strict_goal_case_count={row.get('strict_goal_case_count')} occurrence_count={row.get('occurrence_count')}"
            )
        for task in list(no_candidate_entry_action_board_summary.get("next_tasks") or []):
            lines.append(f"- next_task: {task.get('task_id')} | {task.get('title')}")
            lines.append(f"  next_step: {task.get('next_step')}")
        lines.append(f"- recommendation: {no_candidate_entry_action_board_summary.get('recommendation')}")
    lines.append("")

    lines.append("## No Candidate Entry Replay Bundle")
    if not no_candidate_entry_replay_bundle_summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {no_candidate_entry_replay_bundle_summary.get('status')}")
        lines.append(f"- promising_priority_tickers: {no_candidate_entry_replay_bundle_summary.get('promising_priority_tickers')}")
        lines.append(f"- promising_hotspot_report_dirs: {no_candidate_entry_replay_bundle_summary.get('promising_hotspot_report_dirs')}")
        lines.append(f"- candidate_entry_status_counts: {no_candidate_entry_replay_bundle_summary.get('candidate_entry_status_counts')}")
        lines.append(f"- global_window_scan_rollout_readiness: {no_candidate_entry_replay_bundle_summary.get('global_window_scan_rollout_readiness')}")
        lines.append(f"- global_window_scan_focus_hit_report_count: {no_candidate_entry_replay_bundle_summary.get('global_window_scan_focus_hit_report_count')}")
        for item in list(no_candidate_entry_replay_bundle_summary.get("next_actions") or []):
            lines.append(f"- next_action: {item}")
        lines.append(f"- recommendation: {no_candidate_entry_replay_bundle_summary.get('recommendation')}")
    lines.append("")

    lines.append("## No Candidate Entry Failure Dossier")
    if upstream_shadow_followup_overlay.get("validated_tickers"):
        lines.append(
            f"- note: 本 section 反映历史 failure dossier 断点；当前 active absent_from_watchlist 只剩 {upstream_shadow_followup_overlay.get('active_absent_from_watchlist_tickers')}。"
        )
    if not no_candidate_entry_failure_dossier_summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {no_candidate_entry_failure_dossier_summary.get('status')}")
        lines.append(f"- priority_failure_class_counts: {no_candidate_entry_failure_dossier_summary.get('priority_failure_class_counts')}")
        lines.append(f"- hotspot_failure_class_counts: {no_candidate_entry_failure_dossier_summary.get('hotspot_failure_class_counts')}")
        lines.append(f"- priority_handoff_stage_counts: {no_candidate_entry_failure_dossier_summary.get('priority_handoff_stage_counts')}")
        lines.append(f"- top_absent_from_watchlist_tickers: {no_candidate_entry_failure_dossier_summary.get('top_absent_from_watchlist_tickers')}")
        lines.append(f"- top_watchlist_visible_but_not_candidate_entry_tickers: {no_candidate_entry_failure_dossier_summary.get('top_watchlist_visible_but_not_candidate_entry_tickers')}")
        lines.append(f"- top_candidate_entry_visible_but_not_selection_target_tickers: {no_candidate_entry_failure_dossier_summary.get('top_candidate_entry_visible_but_not_selection_target_tickers')}")
        lines.append(f"- top_upstream_absence_tickers: {no_candidate_entry_failure_dossier_summary.get('top_upstream_absence_tickers')}")
        lines.append(f"- top_candidate_entry_semantic_miss_tickers: {no_candidate_entry_failure_dossier_summary.get('top_candidate_entry_semantic_miss_tickers')}")
        lines.append(f"- top_present_but_outside_candidate_entry_tickers: {no_candidate_entry_failure_dossier_summary.get('top_present_but_outside_candidate_entry_tickers')}")
        lines.append(f"- top_missing_replay_input_tickers: {no_candidate_entry_failure_dossier_summary.get('top_missing_replay_input_tickers')}")
        for row in list(no_candidate_entry_failure_dossier_summary.get("handoff_action_queue") or []):
            lines.append(f"- handoff_task: {row.get('task_id')} stage={row.get('handoff_stage')} tier={row.get('action_tier')}")
            lines.append(f"  next_step: {row.get('next_step')}")
        for item in list(no_candidate_entry_failure_dossier_summary.get("next_actions") or []):
            lines.append(f"- next_action: {item}")
        lines.append(f"- recommendation: {no_candidate_entry_failure_dossier_summary.get('recommendation')}")
    lines.append("")

    lines.append("## Watchlist Recall Dossier")
    if upstream_shadow_followup_overlay.get("validated_tickers"):
        lines.append(
            f"- note: 本 section 保留历史 watchlist recall backlog；当前 active absent_from_candidate_pool 只剩 {upstream_shadow_followup_overlay.get('active_watchlist_absent_from_candidate_pool_tickers')}。"
        )
    if not watchlist_recall_dossier_summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {watchlist_recall_dossier_summary.get('status')}")
        lines.append(f"- priority_recall_stage_counts: {watchlist_recall_dossier_summary.get('priority_recall_stage_counts')}")
        lines.append(f"- top_absent_from_candidate_pool_tickers: {watchlist_recall_dossier_summary.get('top_absent_from_candidate_pool_tickers')}")
        lines.append(f"- top_candidate_pool_visible_but_missing_layer_b_tickers: {watchlist_recall_dossier_summary.get('top_candidate_pool_visible_but_missing_layer_b_tickers')}")
        lines.append(f"- top_layer_b_visible_but_missing_watchlist_tickers: {watchlist_recall_dossier_summary.get('top_layer_b_visible_but_missing_watchlist_tickers')}")
        for row in list(watchlist_recall_dossier_summary.get("action_queue") or []):
            lines.append(f"- watchlist_recall_task: {row.get('task_id')} stage={row.get('dominant_recall_stage')} tier={row.get('action_tier')}")
            lines.append(f"  next_step: {row.get('next_step')}")
        for item in list(watchlist_recall_dossier_summary.get("next_actions") or []):
            lines.append(f"- next_action: {item}")
        lines.append(f"- recommendation: {watchlist_recall_dossier_summary.get('recommendation')}")
    lines.append("")

    lines.append("## Candidate Pool Recall Dossier")
    if upstream_shadow_followup_overlay.get("validated_tickers"):
        lines.append(
            f"- note: 本 section 的 Layer A 截断画像保留为历史 lane 背景；当前 active upstream handoff focus 已收敛到 {upstream_shadow_followup_overlay.get('active_upstream_handoff_focus_tickers')}。"
        )
    if not candidate_pool_recall_dossier_summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {candidate_pool_recall_dossier_summary.get('status')}")
        lines.append(f"- priority_stage_counts: {candidate_pool_recall_dossier_summary.get('priority_stage_counts')}")
        lines.append(f"- dominant_stage: {candidate_pool_recall_dossier_summary.get('dominant_stage')}")
        lines.append(f"- top_stage_tickers: {candidate_pool_recall_dossier_summary.get('top_stage_tickers')}")
        lines.append(f"- priority_handoff_branch_diagnoses: {candidate_pool_recall_dossier_summary.get('priority_handoff_branch_diagnoses')}")
        lines.append(f"- priority_handoff_branch_mechanisms: {candidate_pool_recall_dossier_summary.get('priority_handoff_branch_mechanisms')}")
        branch_experiment_queue = list(candidate_pool_recall_dossier_summary.get("priority_handoff_branch_experiment_queue") or [])
        lines.append("- priority_handoff_branch_experiment_queue: structured_summary")
        lines.append(f"- priority_handoff_branch_experiment_queue_count: {len(branch_experiment_queue)}")
        for experiment in branch_experiment_queue[:3]:
            lines.append(
                f"- branch_experiment: task_id={experiment.get('task_id')} handoff={experiment.get('priority_handoff')} readiness={experiment.get('prototype_readiness')} tickers={experiment.get('tickers')}"
            )
            lines.append(f"  prototype_summary: {experiment.get('prototype_summary')}")
            lines.append(f"  evaluation_summary: {experiment.get('evaluation_summary')}")
            lines.append(f"  guardrail_summary: {experiment.get('guardrail_summary')}")
        lines.append(f"- branch_priority_board_status: {candidate_pool_recall_dossier_summary.get('branch_priority_board_status')}")
        lines.append(f"- branch_priority_alignment_status: {candidate_pool_recall_dossier_summary.get('branch_priority_alignment_status')}")
        if candidate_pool_recall_dossier_summary.get("branch_priority_alignment_summary"):
            lines.append(f"- branch_priority_alignment_summary: {candidate_pool_recall_dossier_summary.get('branch_priority_alignment_summary')}")
        for row in list(candidate_pool_recall_dossier_summary.get("branch_priority_board_rows") or [])[:3]:
            lines.append(
                f"- branch_priority: handoff={row.get('priority_handoff')} readiness={row.get('prototype_readiness')} execution_priority_rank={row.get('execution_priority_rank')} tickers={row.get('tickers')}"
            )
        lines.append(f"- lane_objective_support_status: {candidate_pool_recall_dossier_summary.get('lane_objective_support_status')}")
        for row in list(candidate_pool_recall_dossier_summary.get("lane_objective_support_rows") or [])[:3]:
            lines.append(
                f"- lane_objective_support: handoff={row.get('priority_handoff')} verdict={row.get('support_verdict')} closed_cycle_count={row.get('closed_cycle_count')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')}"
            )
        lines.append(f"- corridor_validation_pack_status: {candidate_pool_recall_dossier_summary.get('corridor_validation_pack_status')}")
        corridor_summary = dict(candidate_pool_recall_dossier_summary.get("corridor_validation_pack_summary") or {})
        if corridor_summary:
            lines.append(
                f"- corridor_validation_pack_summary: pack_status={corridor_summary.get('pack_status')} primary_validation_ticker={corridor_summary.get('primary_validation_ticker')} parallel_watch_tickers={corridor_summary.get('parallel_watch_tickers')}"
            )
        lines.append(f"- corridor_shadow_pack_status: {candidate_pool_recall_dossier_summary.get('corridor_shadow_pack_status')}")
        corridor_shadow_summary = dict(candidate_pool_recall_dossier_summary.get("corridor_shadow_pack_summary") or {})
        if corridor_shadow_summary:
            lines.append(
                f"- corridor_shadow_pack_summary: shadow_status={corridor_shadow_summary.get('shadow_status')} primary_shadow_replay={corridor_shadow_summary.get('primary_shadow_replay')} parallel_watch_tickers={corridor_shadow_summary.get('parallel_watch_tickers')}"
            )
        lines.append(f"- rebucket_shadow_pack_status: {candidate_pool_recall_dossier_summary.get('rebucket_shadow_pack_status')}")
        rebucket_experiment = dict(candidate_pool_recall_dossier_summary.get("rebucket_shadow_pack_experiment") or {})
        if rebucket_experiment:
            lines.append(
                f"- rebucket_shadow_pack_experiment: handoff={rebucket_experiment.get('priority_handoff')} readiness={rebucket_experiment.get('prototype_readiness')} tickers={rebucket_experiment.get('tickers')}"
            )
        lines.append(f"- rebucket_objective_validation_status: {candidate_pool_recall_dossier_summary.get('rebucket_objective_validation_status')}")
        rebucket_validation_summary = dict(candidate_pool_recall_dossier_summary.get("rebucket_objective_validation_summary") or {})
        if rebucket_validation_summary:
            lines.append(
                f"- rebucket_objective_validation_summary: validation_status={rebucket_validation_summary.get('validation_status')} support_verdict={rebucket_validation_summary.get('support_verdict')} mean_t_plus_2_return={rebucket_validation_summary.get('mean_t_plus_2_return')}"
            )
        lines.append(f"- rebucket_comparison_bundle_status: {candidate_pool_recall_dossier_summary.get('rebucket_comparison_bundle_status')}")
        rebucket_comparison_summary = dict(candidate_pool_recall_dossier_summary.get("rebucket_comparison_bundle_summary") or {})
        if rebucket_comparison_summary:
            lines.append(
                f"- rebucket_comparison_bundle_summary: bundle_status={rebucket_comparison_summary.get('bundle_status')} structural_leader={rebucket_comparison_summary.get('structural_leader')} objective_leader={rebucket_comparison_summary.get('objective_leader')}"
            )
        lines.append(f"- lane_pair_board_status: {candidate_pool_recall_dossier_summary.get('lane_pair_board_status')}")
        lane_pair_summary = dict(candidate_pool_recall_dossier_summary.get("lane_pair_board_summary") or {})
        if lane_pair_summary:
            lines.append(
                f"- lane_pair_board_summary: pair_status={lane_pair_summary.get('pair_status')} board_leader={lane_pair_summary.get('board_leader')} leader_lane_family={lane_pair_summary.get('leader_lane_family')} leader_governance_status={lane_pair_summary.get('leader_governance_status')} leader_governance_execution_quality={lane_pair_summary.get('leader_governance_execution_quality')} leader_governance_entry_timing_bias={lane_pair_summary.get('leader_governance_entry_timing_bias')} parallel_watch_ticker={lane_pair_summary.get('parallel_watch_ticker')} parallel_watch_governance_blocker={lane_pair_summary.get('parallel_watch_governance_blocker')} parallel_watch_same_source_sample_count={lane_pair_summary.get('parallel_watch_same_source_sample_count')} parallel_watch_next_close_positive_rate={lane_pair_summary.get('parallel_watch_next_close_positive_rate')} parallel_watch_next_close_return_mean={lane_pair_summary.get('parallel_watch_next_close_return_mean')}"
            )
        continuation_focus_summary = dict(candidate_pool_recall_dossier_summary.get("continuation_focus_summary") or {})
        if continuation_focus_summary:
            lines.append(
                f"- continuation_focus_summary: focus_ticker={continuation_focus_summary.get('focus_ticker')} promotion_review_verdict={continuation_focus_summary.get('promotion_review_verdict')} promotion_gate_verdict={continuation_focus_summary.get('promotion_gate_verdict')} watchlist_execution_verdict={continuation_focus_summary.get('watchlist_execution_verdict')} focus_watch_validation_status={continuation_focus_summary.get('focus_watch_validation_status')} focus_watch_recent_supporting_window_count={continuation_focus_summary.get('focus_watch_recent_supporting_window_count')} eligible_gate_verdict={continuation_focus_summary.get('eligible_gate_verdict')} execution_gate_verdict={continuation_focus_summary.get('execution_gate_verdict')} execution_gate_blockers={continuation_focus_summary.get('execution_gate_blockers')} execution_overlay_verdict={continuation_focus_summary.get('execution_overlay_verdict')} execution_overlay_promotion_blocker={continuation_focus_summary.get('execution_overlay_promotion_blocker')} execution_overlay_persistence_requirement={continuation_focus_summary.get('execution_overlay_persistence_requirement')} execution_overlay_lane_support_ratio={continuation_focus_summary.get('execution_overlay_lane_support_ratio')} governance_status={continuation_focus_summary.get('governance_status')}"
            )
        continuation_promotion_ready_summary = dict(candidate_pool_recall_dossier_summary.get("continuation_promotion_ready_summary") or {})
        if continuation_promotion_ready_summary:
            lines.append(
                f"- continuation_promotion_ready_summary: focus_ticker={continuation_promotion_ready_summary.get('focus_ticker')} promotion_path_status={continuation_promotion_ready_summary.get('promotion_path_status')} blockers_remaining_count={continuation_promotion_ready_summary.get('blockers_remaining_count')} observed_independent_window_count={continuation_promotion_ready_summary.get('observed_independent_window_count')} missing_independent_window_count={continuation_promotion_ready_summary.get('missing_independent_window_count')} candidate_dossier_support_trade_date_count={continuation_promotion_ready_summary.get('candidate_dossier_support_trade_date_count')} candidate_dossier_same_trade_date_variant_count={continuation_promotion_ready_summary.get('candidate_dossier_same_trade_date_variant_count')} persistence_verdict={continuation_promotion_ready_summary.get('persistence_verdict')} provisional_default_btst_edge_verdict={continuation_promotion_ready_summary.get('provisional_default_btst_edge_verdict')} edge_threshold_verdict={continuation_promotion_ready_summary.get('edge_threshold_verdict')} promotion_merge_review_verdict={continuation_promotion_ready_summary.get('promotion_merge_review_verdict')} ready_after_next_qualifying_window={continuation_promotion_ready_summary.get('ready_after_next_qualifying_window')} next_window_requirement={continuation_promotion_ready_summary.get('next_window_requirement')} next_window_duplicate_trade_date_verdict={continuation_promotion_ready_summary.get('next_window_duplicate_trade_date_verdict')} next_window_quality_requirement={continuation_promotion_ready_summary.get('next_window_quality_requirement')} next_window_disqualified_bucket_verdict={continuation_promotion_ready_summary.get('next_window_disqualified_bucket_verdict')} next_window_qualified_merge_review_verdict={continuation_promotion_ready_summary.get('next_window_qualified_merge_review_verdict')} t_plus_2_positive_rate_delta_vs_default_btst={continuation_promotion_ready_summary.get('t_plus_2_positive_rate_delta_vs_default_btst')} t_plus_2_mean_return_delta_vs_default_btst={continuation_promotion_ready_summary.get('t_plus_2_mean_return_delta_vs_default_btst')}"
            )
        transient_probe_summary = dict(candidate_pool_recall_dossier_summary.get("transient_probe_summary") or {})
        if transient_probe_summary:
            lines.append(
                f"- transient_probe_summary: ticker={transient_probe_summary.get('ticker')} status={transient_probe_summary.get('status')} blocker={transient_probe_summary.get('blocker')} candidate_source={transient_probe_summary.get('candidate_source')} score_state={transient_probe_summary.get('score_state')} downstream_bottleneck={transient_probe_summary.get('downstream_bottleneck')} historical_sample_count={transient_probe_summary.get('historical_sample_count')} historical_next_close_positive_rate={transient_probe_summary.get('historical_next_close_positive_rate')}"
            )
        execution_constraint_rollup = dict(candidate_pool_recall_dossier_summary.get("execution_constraint_rollup") or {})
        if execution_constraint_rollup:
            lines.append(
                f"- execution_constraint_rollup: constraint_count={execution_constraint_rollup.get('constraint_count')} continuation_focus_tickers={execution_constraint_rollup.get('continuation_focus_tickers')} continuation_blockers={execution_constraint_rollup.get('continuation_blockers')} shadow_focus_tickers={execution_constraint_rollup.get('shadow_focus_tickers')} shadow_blockers={execution_constraint_rollup.get('shadow_blockers')}"
            )
        lines.append(f"- upstream_handoff_board_status: {candidate_pool_recall_dossier_summary.get('upstream_handoff_board_status')}")
        upstream_handoff_summary = dict(candidate_pool_recall_dossier_summary.get("upstream_handoff_board_summary") or {})
        if upstream_handoff_summary:
            lines.append(
                f"- upstream_handoff_board_summary: board_status={upstream_handoff_summary.get('board_status')} focus_tickers={upstream_handoff_summary.get('focus_tickers')} first_broken_handoff_counts={upstream_handoff_summary.get('first_broken_handoff_counts')}"
            )
        lines.append(f"- corridor_uplift_runbook_status: {candidate_pool_recall_dossier_summary.get('corridor_uplift_runbook_status')}")
        corridor_uplift_summary = dict(candidate_pool_recall_dossier_summary.get("corridor_uplift_runbook_summary") or {})
        if corridor_uplift_summary:
            lines.append(
                f"- corridor_uplift_runbook_summary: runbook_status={corridor_uplift_summary.get('runbook_status')} primary_shadow_replay={corridor_uplift_summary.get('primary_shadow_replay')} parallel_watch_tickers={corridor_uplift_summary.get('parallel_watch_tickers')}"
            )
        for row in list(candidate_pool_recall_dossier_summary.get("action_queue") or []):
            lines.append(f"- candidate_pool_recall_task: {row.get('task_id')} stage={row.get('dominant_blocking_stage')} tier={row.get('action_tier')}")
            lines.append(f"  next_step: {row.get('next_step')}")
        for item in list(candidate_pool_recall_dossier_summary.get("next_actions") or []):
            lines.append(f"- next_action: {item}")
        lines.append(f"- recommendation: {candidate_pool_recall_dossier_summary.get('recommendation')}")
    lines.append("")

    lines.append("## Priority Board Snapshot")
    lines.append(f"- summary: {latest_priority_board_snapshot.get('summary')}")
    lines.append(f"- brief_recommendation: {latest_priority_board_snapshot.get('brief_recommendation')}")
    for index, row in enumerate(list(latest_priority_board_snapshot.get("priority_rows") or []), start=1):
        lines.append(
            f"- {index}. {row.get('ticker')}: lane={row.get('lane')} actionability={row.get('actionability')} execution_quality_label={row.get('execution_quality_label')}"
        )
        lines.append(f"  why_now: {row.get('why_now')}")
        lines.append(f"  suggested_action: {row.get('suggested_action')}")
        lines.append(f"  historical_summary: {row.get('historical_summary')}")
    for guardrail in list(latest_priority_board_snapshot.get("global_guardrails") or []):
        lines.append(f"- guardrail: {guardrail}")
    lines.append("")

    lines.append("## Catalyst Theme Frontier")
    if not catalyst_theme_frontier_summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {catalyst_theme_frontier_summary.get('status')}")
        lines.append(f"- shadow_candidate_count: {catalyst_theme_frontier_summary.get('shadow_candidate_count')}")
        lines.append(f"- baseline_selected_count: {catalyst_theme_frontier_summary.get('baseline_selected_count')}")
        lines.append(f"- recommended_variant_name: {catalyst_theme_frontier_summary.get('recommended_variant_name')}")
        lines.append(f"- recommended_promoted_shadow_count: {catalyst_theme_frontier_summary.get('recommended_promoted_shadow_count')}")
        lines.append(f"- recommended_relaxation_cost: {catalyst_theme_frontier_summary.get('recommended_relaxation_cost')}")
        lines.append(f"- recommended_thresholds: {catalyst_theme_frontier_summary.get('recommended_thresholds')}")
        promoted_tickers = list(catalyst_theme_frontier_summary.get("recommended_promoted_tickers") or [])
        lines.append(f"- recommended_promoted_tickers: {', '.join(promoted_tickers) if promoted_tickers else 'none'}")
        lines.append(f"- recommendation: {catalyst_theme_frontier_summary.get('recommendation')}")
    lines.append("")

    lines.append("## Score-Fail Frontier Queue")
    if not score_fail_frontier_summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {score_fail_frontier_summary.get('status')}")
        lines.append(f"- rejected_short_trade_boundary_count: {score_fail_frontier_summary.get('rejected_short_trade_boundary_count')}")
        lines.append(f"- rescueable_case_count: {score_fail_frontier_summary.get('rescueable_case_count')}")
        lines.append(f"- threshold_only_rescue_count: {score_fail_frontier_summary.get('threshold_only_rescue_count')}")
        lines.append(f"- recurring_case_count: {score_fail_frontier_summary.get('recurring_case_count')}")
        lines.append(f"- transition_candidate_count: {score_fail_frontier_summary.get('transition_candidate_count')}")
        lines.append(f"- recurring_shadow_refresh_status: {score_fail_frontier_summary.get('recurring_shadow_refresh_status')}")
        priority_queue_tickers = list(score_fail_frontier_summary.get("priority_queue_tickers") or [])
        lines.append(f"- priority_queue_tickers: {', '.join(priority_queue_tickers) if priority_queue_tickers else 'none'}")
        top_rescue_tickers = list(score_fail_frontier_summary.get("top_rescue_tickers") or [])
        lines.append(f"- top_rescue_tickers: {', '.join(top_rescue_tickers) if top_rescue_tickers else 'none'}")
        for row in list(score_fail_frontier_summary.get("priority_queue") or []):
            lines.append(
                f"- recurring_priority: {row.get('ticker')} occurrence_count={row.get('occurrence_count')} minimal_adjustment_cost={row.get('minimal_adjustment_cost')} gap_to_near_miss_mean={row.get('gap_to_near_miss_mean')}"
            )
        for row in list(score_fail_frontier_summary.get("top_rescue_rows") or []):
            lines.append(
                f"- top_rescue_row: {row.get('trade_date')} {row.get('ticker')} baseline_score={row.get('baseline_score_target')} replayed_score={row.get('replayed_score_target')} adjustment_cost={row.get('adjustment_cost')}"
            )
        lines.append(f"- recommendation: {score_fail_frontier_summary.get('recommendation')}")
    lines.append("")

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
            lines.append(
                f"- provider_health: {row.get('provider')} errors={row.get('errors')} attempts={row.get('attempts')} error_rate={row.get('error_rate')} fallback_attempts={row.get('fallback_attempts')}"
            )
    else:
        lines.append("- provider_health: none")
    sample_errors = list(llm_error_digest.get("sample_errors") or [])
    if sample_errors:
        for row in sample_errors:
            lines.append(
                f"- sample_error: {row.get('provider')} {row.get('error_type')} stage={row.get('pipeline_stage')} tier={row.get('model_tier')} message={row.get('message')}"
            )
    else:
        lines.append("- sample_error: none")
    lines.append("")

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
        lines.append(
            f"- top_return_row: {row.get('report_dir_name')} | selection_target={row.get('selection_target')} | total_return_pct={row.get('total_return_pct')} | near_miss_count={row.get('near_miss_count')}"
        )
    lines.append("")

    lines.append("## Reading Order")
    for item in list(payload.get("recommended_reading_order") or []):
        lines.append(f"- {item.get('entry_id')}: {item.get('question')} | {item.get('report_path')}")
    lines.append("")

    lines.append("## Fast Links")
    for label, source_path in source_paths.items():
        relative_target = _relative_link(source_path, resolved_output_parent)
        if relative_target:
            lines.append(f"- {label}: [{Path(source_path).name}]({relative_target})")
        else:
            lines.append(f"- {label}: {source_path}")
    lines.append("")
    return "\n".join(lines) + "\n"


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
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_output_json = Path(output_json).expanduser().resolve() if output_json else (resolved_reports_root / DEFAULT_OUTPUT_JSON.name).resolve()
    resolved_output_md = Path(output_md).expanduser().resolve() if output_md else (resolved_reports_root / DEFAULT_OUTPUT_MD.name).resolve()
    resolved_delta_output_json = Path(delta_output_json).expanduser().resolve() if delta_output_json else (resolved_reports_root / DEFAULT_DELTA_JSON.name).resolve()
    resolved_delta_output_md = Path(delta_output_md).expanduser().resolve() if delta_output_md else (resolved_reports_root / DEFAULT_DELTA_MD.name).resolve()
    resolved_close_validation_output_json = Path(close_validation_output_json).expanduser().resolve() if close_validation_output_json else (resolved_reports_root / DEFAULT_CLOSE_VALIDATION_JSON.name).resolve()
    resolved_close_validation_output_md = Path(close_validation_output_md).expanduser().resolve() if close_validation_output_md else (resolved_reports_root / DEFAULT_CLOSE_VALIDATION_MD.name).resolve()
    resolved_history_dir = Path(history_dir).expanduser().resolve() if history_dir else (resolved_reports_root / DEFAULT_HISTORY_DIR.relative_to(REPORTS_DIR)).resolve()

    pre_manifest_result = generate_reports_manifest_artifacts(reports_root=resolved_reports_root)
    bootstrap_payload = build_btst_nightly_control_tower_payload(pre_manifest_result["manifest"])
    historical_payload_candidates = _load_archived_nightly_payloads(resolved_history_dir)
    previous_payload, previous_payload_path = historical_payload_candidates[0] if historical_payload_candidates else ({}, None)
    bootstrap_delta_payload = build_btst_open_ready_delta_payload(
        bootstrap_payload,
        reports_root=resolved_reports_root,
        current_nightly_json_path=resolved_output_json,
        previous_payload=previous_payload,
        previous_payload_path=previous_payload_path,
        historical_payload_candidates=historical_payload_candidates,
    )
    resolved_delta_output_json.write_text(json.dumps(bootstrap_delta_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resolved_delta_output_md.write_text(render_btst_open_ready_delta_markdown(bootstrap_delta_payload, output_parent=resolved_delta_output_md.parent), encoding="utf-8")
    resolved_output_json.write_text(json.dumps(bootstrap_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resolved_output_md.write_text(render_btst_nightly_control_tower_markdown(bootstrap_payload, output_parent=resolved_output_md.parent), encoding="utf-8")
    post_manifest_result = generate_reports_manifest_artifacts(reports_root=resolved_reports_root)
    payload = build_btst_nightly_control_tower_payload(post_manifest_result["manifest"])
    delta_payload = build_btst_open_ready_delta_payload(
        payload,
        reports_root=resolved_reports_root,
        current_nightly_json_path=resolved_output_json,
        previous_payload=previous_payload,
        previous_payload_path=previous_payload_path,
        historical_payload_candidates=historical_payload_candidates,
    )
    resolved_delta_output_json.write_text(json.dumps(delta_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resolved_delta_output_md.write_text(render_btst_open_ready_delta_markdown(delta_payload, output_parent=resolved_delta_output_md.parent), encoding="utf-8")
    resolved_output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resolved_output_md.write_text(render_btst_nightly_control_tower_markdown(payload, output_parent=resolved_output_md.parent), encoding="utf-8")
    close_validation_result = generate_btst_latest_close_validation_artifacts(
        nightly_payload=payload,
        delta_payload=delta_payload,
        nightly_json_path=resolved_output_json,
        delta_json_path=resolved_delta_output_json,
        output_json=resolved_close_validation_output_json,
        output_md=resolved_close_validation_output_md,
    )
    history_json_path = _archive_nightly_payload(payload, resolved_history_dir)
    final_manifest_result = generate_reports_manifest_artifacts(reports_root=resolved_reports_root)

    return {
        "payload": payload,
        "delta_payload": delta_payload,
        "json_path": resolved_output_json.as_posix(),
        "markdown_path": resolved_output_md.as_posix(),
        "delta_json_path": resolved_delta_output_json.as_posix(),
        "delta_markdown_path": resolved_delta_output_md.as_posix(),
        "close_validation_json_path": close_validation_result["json_path"],
        "close_validation_markdown_path": close_validation_result["markdown_path"],
        "history_json_path": history_json_path,
        "catalyst_theme_frontier_json": dict(payload.get("latest_btst_snapshot") or {}).get("catalyst_theme_frontier_json_path"),
        "catalyst_theme_frontier_markdown": dict(payload.get("latest_btst_snapshot") or {}).get("catalyst_theme_frontier_markdown_path"),
        "manifest_json": final_manifest_result["json_path"],
        "manifest_markdown": final_manifest_result["markdown_path"],
    }


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
