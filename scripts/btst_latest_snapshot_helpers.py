from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


SafeLoadJson = Callable[[str | Path | None], dict[str, Any]]
ExtractScoreFailFrontierSummary = Callable[[dict[str, Any]], dict[str, Any]]
ExtractCatalystThemeFrontierSummary = Callable[[dict[str, Any]], dict[str, Any]]


def extract_catalyst_theme_frontier_summary(frontier: dict[str, Any]) -> dict[str, Any]:
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
        "shadow_threshold_blocker_summary": dict(frontier.get("shadow_threshold_blocker_summary") or {}),
        "recommended_variant_name": recommended_variant.get("variant_name"),
        "recommended_promoted_shadow_count": promoted_shadow_count,
        "recommended_relaxation_cost": recommended_variant.get("threshold_relaxation_cost"),
        "recommended_thresholds": dict(recommended_variant.get("thresholds") or {}),
        "recommended_promoted_tickers": [str(row.get("ticker") or "") for row in top_promoted_rows if row.get("ticker")][:3],
        "recommendation": frontier.get("recommendation"),
    }


def extract_score_fail_frontier_summary(
    manifest: dict[str, Any],
    *,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    refresh = dict(manifest.get("btst_score_fail_frontier_refresh") or {})
    score_fail_analysis = safe_load_json(refresh.get("analysis_json"))
    score_fail_frontier = safe_load_json(refresh.get("frontier_json"))
    recurring_frontier = safe_load_json(refresh.get("recurring_json"))
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


def extract_tradeable_opportunity_pool_summary(
    manifest: dict[str, Any],
    *,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    refresh = dict(manifest.get("btst_tradeable_opportunity_pool_refresh") or {})
    analysis = safe_load_json(refresh.get("analysis_json"))
    waterfall = safe_load_json(refresh.get("waterfall_json"))
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


def extract_latest_btst_snapshot(
    manifest: dict[str, Any],
    *,
    safe_load_json: SafeLoadJson,
    extract_score_fail_frontier_summary: ExtractScoreFailFrontierSummary,
    extract_catalyst_theme_frontier_summary: ExtractCatalystThemeFrontierSummary,
) -> dict[str, Any]:
    latest_btst_run = dict(manifest.get("latest_btst_run") or {})
    report_dir_abs = latest_btst_run.get("report_dir_abs")
    if not report_dir_abs:
        return {}

    session_summary_path = Path(report_dir_abs).expanduser().resolve() / "session_summary.json"
    session_summary = safe_load_json(session_summary_path)
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

    priority_board = safe_load_json(priority_board_json_path)
    brief = safe_load_json(brief_json_path)
    catalyst_theme_frontier = safe_load_json(catalyst_theme_frontier_json_path)
    brief_summary = dict(brief.get("summary") or {})
    score_fail_frontier_summary = extract_score_fail_frontier_summary(manifest)

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
        "catalyst_theme_frontier_summary": extract_catalyst_theme_frontier_summary(catalyst_theme_frontier),
        "score_fail_frontier_summary": score_fail_frontier_summary,
        "llm_error_digest": dict(session_summary.get("llm_error_digest") or {}),
    }
