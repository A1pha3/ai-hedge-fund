from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.analyze_btst_latest_close_validation import generate_btst_latest_close_validation_artifacts
from scripts.generate_reports_manifest import generate_reports_manifest_artifacts


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_nightly_control_tower_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_nightly_control_tower_latest.md"
DEFAULT_DELTA_JSON = REPORTS_DIR / "btst_open_ready_delta_latest.json"
DEFAULT_DELTA_MD = REPORTS_DIR / "btst_open_ready_delta_latest.md"
DEFAULT_CLOSE_VALIDATION_JSON = REPORTS_DIR / "btst_latest_close_validation_latest.json"
DEFAULT_CLOSE_VALIDATION_MD = REPORTS_DIR / "btst_latest_close_validation_latest.md"
DEFAULT_HISTORY_DIR = REPORTS_DIR / "archive" / "btst_nightly_control_tower_history"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _safe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _normalize_trade_date(value: Any) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    if len(digits) != 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"


def _looks_like_report_dir(path: Path) -> bool:
    return path.is_dir() and (path / "session_summary.json").exists() and (path / "selection_artifacts").exists()


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


def _extract_control_tower_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    synthesis = _safe_load_json(dict(manifest.get("btst_governance_synthesis_refresh") or {}).get("output_json"))
    validation = _safe_load_json(dict(manifest.get("btst_governance_validation_refresh") or {}).get("output_json"))
    independent_window_monitor = _safe_load_json(dict(manifest.get("btst_independent_window_monitor_refresh") or {}).get("output_json"))
    tplus1_tplus2_objective_monitor = _safe_load_json(dict(manifest.get("btst_tplus1_tplus2_objective_monitor_refresh") or {}).get("output_json"))
    return {
        "synthesis": synthesis,
        "validation": validation,
        "independent_window_monitor": independent_window_monitor,
        "tplus1_tplus2_objective_monitor": tplus1_tplus2_objective_monitor,
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
        "overall_verdict": validation.get("overall_verdict"),
        "warn_count": validation.get("warn_count"),
        "fail_count": validation.get("fail_count"),
    }


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


def _list_changed_delta_sections(delta_payload: dict[str, Any]) -> list[str]:
    changed_sections: list[str] = []
    if dict(delta_payload.get("priority_delta") or {}).get("has_changes"):
        changed_sections.append("priority")
    if dict(delta_payload.get("catalyst_frontier_delta") or {}).get("has_changes"):
        changed_sections.append("catalyst_frontier")
    if dict(delta_payload.get("score_fail_frontier_delta") or {}).get("has_changes"):
        changed_sections.append("score_fail_frontier")
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
    if not operator_focus:
        operator_focus.append("本轮相对上一轮没有检测到 priority / governance / replay / score-fail frontier 的结构变化，可视为稳定复跑。")

    overall_delta_verdict = "baseline_captured"
    if comparison_basis != "baseline_captured":
        overall_delta_verdict = "changed" if any([priority_delta.get("has_changes"), governance_delta.get("has_changes"), replay_delta.get("has_changes"), catalyst_frontier_delta.get("has_changes"), score_fail_frontier_delta.get("has_changes")]) else "stable"

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
    replay_cohort_snapshot = _extract_replay_cohort_snapshot(manifest)
    priority_board = dict(latest_btst_snapshot.get("priority_board") or {})

    recommended_reading_order: list[dict[str, Any]] = []
    for entry_id in (
        "btst_governance_synthesis_latest",
        "btst_tplus1_tplus2_objective_monitor_latest",
        "btst_independent_window_monitor_latest",
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
        },
        "control_tower_snapshot": control_tower_snapshot,
        "latest_priority_board_snapshot": {
            "headline": priority_board.get("headline"),
            "summary": priority_board.get("summary"),
            "priority_rows": list(priority_board.get("priority_rows") or [])[:3],
            "global_guardrails": list(priority_board.get("global_guardrails") or []),
            "brief_recommendation": latest_btst_snapshot.get("brief_recommendation"),
        },
        "replay_cohort_snapshot": replay_cohort_snapshot,
        "latest_btst_snapshot": latest_btst_snapshot,
        "recommended_reading_order": recommended_reading_order,
        "source_paths": {
            "report_manifest_json": str((Path(manifest.get("reports_root") or REPORTS_DIR) / "report_manifest_latest.json").expanduser().resolve()),
            "report_manifest_markdown": str((Path(manifest.get("reports_root") or REPORTS_DIR) / "report_manifest_latest.md").expanduser().resolve()),
            "governance_synthesis_markdown": _entry_by_id(manifest, "btst_governance_synthesis_latest").get("absolute_path"),
            "governance_validation_markdown": _entry_by_id(manifest, "btst_governance_validation_latest").get("absolute_path"),
            "priority_board_markdown": latest_btst_snapshot.get("priority_board_markdown_path"),
            "brief_markdown": latest_btst_snapshot.get("brief_markdown_path"),
            "execution_card_markdown": latest_btst_snapshot.get("execution_card_markdown_path"),
            "opening_watch_card_markdown": latest_btst_snapshot.get("opening_watch_card_markdown_path"),
            "catalyst_theme_frontier_markdown": latest_btst_snapshot.get("catalyst_theme_frontier_markdown_path"),
            "score_fail_frontier_markdown": latest_btst_snapshot.get("score_fail_frontier_markdown_path"),
            "score_fail_recurring_markdown": latest_btst_snapshot.get("score_fail_recurring_markdown_path"),
            "score_fail_transition_markdown": latest_btst_snapshot.get("score_fail_transition_markdown_path"),
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
    lines.append(f"- catalyst_frontier_recommendation: {catalyst_theme_frontier_summary.get('recommendation')}")
    lines.append(f"- score_fail_frontier_recommendation: {score_fail_frontier_summary.get('recommendation')}")
    lines.append(f"- llm_recommendation: {llm_error_digest.get('recommendation')}")
    lines.append("")

    lines.append("## Control Tower Snapshot")
    lines.append(f"- lane_status_counts: {control_tower_snapshot.get('lane_status_counts')}")
    lines.append(f"- warn_count: {control_tower_snapshot.get('warn_count')}")
    lines.append(f"- fail_count: {control_tower_snapshot.get('fail_count')}")
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
    payload = build_btst_nightly_control_tower_payload(pre_manifest_result["manifest"])
    historical_payload_candidates = _load_archived_nightly_payloads(resolved_history_dir)
    previous_payload, previous_payload_path = historical_payload_candidates[0] if historical_payload_candidates else ({}, None)
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
    post_manifest_result = generate_reports_manifest_artifacts(reports_root=resolved_reports_root)

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
        "manifest_json": post_manifest_result["json_path"],
        "manifest_markdown": post_manifest_result["markdown_path"],
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