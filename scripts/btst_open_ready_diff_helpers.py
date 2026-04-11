from __future__ import annotations

from collections.abc import Callable
from typing import Any


ExtractPrioritySummary = Callable[[dict[str, Any]], dict[str, int]]
AsFloat = Callable[[Any], float | None]


def build_priority_rows_by_ticker(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("ticker") or ""): dict(row) for row in rows if row.get("ticker")}


def build_rank_map(rows_by_ticker: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {ticker: index for index, ticker in enumerate(rows_by_ticker, start=1)}


def collect_priority_board_membership_changes(
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


def collect_priority_board_per_ticker_changes(
    *,
    current_by_ticker: dict[str, dict[str, Any]],
    previous_by_ticker: dict[str, dict[str, Any]],
    current_ranks: dict[str, int],
    previous_ranks: dict[str, int],
    as_float: AsFloat,
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
        current_score = as_float(current_row.get("score_target"))
        previous_score = as_float(previous_row.get("score_target"))
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


def build_priority_summary_delta(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, int]:
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


def diff_priority_board(
    current_snapshot: dict[str, Any],
    previous_board: dict[str, Any],
    *,
    previous_summary_source: dict[str, Any] | None = None,
    extract_priority_summary: ExtractPrioritySummary,
    as_float: AsFloat,
) -> dict[str, Any]:
    current_summary = extract_priority_summary(current_snapshot)
    previous_summary = extract_priority_summary(previous_summary_source or previous_board)
    current_rows = list(current_snapshot.get("priority_rows") or [])
    previous_rows = list(previous_board.get("priority_rows") or [])
    current_by_ticker = build_priority_rows_by_ticker(current_rows)
    previous_by_ticker = build_priority_rows_by_ticker(previous_rows)
    current_ranks = build_rank_map(current_by_ticker)
    previous_ranks = build_rank_map(previous_by_ticker)

    added_tickers = collect_priority_board_membership_changes(current_by_ticker, previous_by_ticker, added=True)
    removed_tickers = collect_priority_board_membership_changes(current_by_ticker, previous_by_ticker, added=False)
    per_ticker_changes = collect_priority_board_per_ticker_changes(
        current_by_ticker=current_by_ticker,
        previous_by_ticker=previous_by_ticker,
        current_ranks=current_ranks,
        previous_ranks=previous_ranks,
        as_float=as_float,
    )
    current_guardrails = list(current_snapshot.get("global_guardrails") or [])
    previous_guardrails = list(previous_board.get("global_guardrails") or [])
    guardrails_added = [item for item in current_guardrails if item not in previous_guardrails]
    guardrails_removed = [item for item in previous_guardrails if item not in current_guardrails]
    summary_delta = build_priority_summary_delta(current_summary, previous_summary)
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


def build_governance_lane_map(lane_matrix: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("lane_id") or ""): dict(row) for row in lane_matrix if row.get("lane_id")}


def build_governance_lane_delta(
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


def has_governance_lane_delta_changes(lane_delta: dict[str, Any]) -> bool:
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


def collect_governance_lane_changes(
    current_by_lane: dict[str, dict[str, Any]],
    previous_by_lane: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    lane_changes: list[dict[str, Any]] = []
    for lane_id in sorted(set(current_by_lane).union(previous_by_lane)):
        lane_delta = build_governance_lane_delta(
            lane_id,
            current_row=current_by_lane.get(lane_id),
            previous_row=previous_by_lane.get(lane_id),
        )
        if has_governance_lane_delta_changes(lane_delta):
            lane_changes.append(lane_delta)
    return lane_changes


def build_governance_aggregate_deltas(current_control: dict[str, Any], previous_control: dict[str, Any]) -> dict[str, int]:
    return {
        "waiting_lane_count_delta": int(current_control.get("waiting_lane_count") or 0) - int(previous_control.get("waiting_lane_count") or 0),
        "ready_lane_count_delta": int(current_control.get("ready_lane_count") or 0) - int(previous_control.get("ready_lane_count") or 0),
        "warn_count_delta": int(current_control.get("warn_count") or 0) - int(previous_control.get("warn_count") or 0),
        "fail_count_delta": int(current_control.get("fail_count") or 0) - int(previous_control.get("fail_count") or 0),
    }


def diff_governance(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
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
    current_by_lane = build_governance_lane_map(current_lane_matrix)
    previous_by_lane = build_governance_lane_map(previous_lane_matrix)
    lane_changes = collect_governance_lane_changes(current_by_lane, previous_by_lane)
    aggregate_deltas = build_governance_aggregate_deltas(current_control, previous_control)
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


def diff_replay(
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
    *,
    extract_priority_summary: ExtractPrioritySummary,
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
        previous_summary = extract_priority_summary(previous_report_snapshot.get("brief_summary") or {})
        current_summary = extract_priority_summary(current_latest_btst.get("brief_summary") or {})
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


def resolve_catalyst_frontier_previous_summary(
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


def diff_ticker_lists(current_tickers: list[Any], previous_tickers: list[Any]) -> dict[str, list[Any]]:
    return {
        "added": [ticker for ticker in current_tickers if ticker not in previous_tickers],
        "removed": [ticker for ticker in previous_tickers if ticker not in current_tickers],
    }


def build_catalyst_frontier_count_deltas(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, int]:
    return {
        "promoted_shadow_count_delta": int(current_summary.get("recommended_promoted_shadow_count") or 0)
        - int(previous_summary.get("recommended_promoted_shadow_count") or 0),
        "shadow_candidate_count_delta": int(current_summary.get("shadow_candidate_count") or 0) - int(previous_summary.get("shadow_candidate_count") or 0),
        "baseline_selected_count_delta": int(current_summary.get("baseline_selected_count") or 0) - int(previous_summary.get("baseline_selected_count") or 0),
    }


def diff_catalyst_frontier(
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    current_summary = dict(dict(current_payload.get("latest_btst_snapshot") or {}).get("catalyst_theme_frontier_summary") or {})
    previous_summary, comparison_basis = resolve_catalyst_frontier_previous_summary(previous_payload, previous_report_snapshot)
    if comparison_basis is None:
        return {
            "available": False,
            "comparison_basis": "none",
            "has_changes": False,
        }

    current_promoted_tickers = list(current_summary.get("recommended_promoted_tickers") or [])
    previous_promoted_tickers = list(previous_summary.get("recommended_promoted_tickers") or [])
    promoted_ticker_delta = diff_ticker_lists(current_promoted_tickers, previous_promoted_tickers)
    count_deltas = build_catalyst_frontier_count_deltas(current_summary, previous_summary)
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


def extract_score_fail_frontier_summaries(
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        dict(dict(current_payload.get("latest_btst_snapshot") or {}).get("score_fail_frontier_summary") or {}),
        dict(dict(previous_payload.get("latest_btst_snapshot") or {}).get("score_fail_frontier_summary") or {}),
    )


def build_score_fail_frontier_count_deltas(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, int]:
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


def diff_score_fail_frontier(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
    if not previous_payload:
        return {
            "available": False,
            "reason": "no_previous_nightly_snapshot",
            "has_changes": False,
        }

    current_summary, previous_summary = extract_score_fail_frontier_summaries(current_payload, previous_payload)
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
    priority_queue_delta = diff_ticker_lists(current_priority_queue_tickers, previous_priority_queue_tickers)
    top_rescue_delta = diff_ticker_lists(current_top_rescue_tickers, previous_top_rescue_tickers)
    count_deltas = build_score_fail_frontier_count_deltas(current_summary, previous_summary)
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


def build_carryover_promotion_gate_field_changes(current_summary: dict[str, Any], previous_summary: dict[str, Any]) -> dict[str, bool]:
    return {
        "focus_ticker_changed": str(current_summary.get("focus_ticker") or "") != str(previous_summary.get("focus_ticker") or ""),
        "focus_gate_verdict_changed": str(current_summary.get("focus_gate_verdict") or "") != str(previous_summary.get("focus_gate_verdict") or ""),
        "selected_contract_verdict_changed": str(current_summary.get("selected_contract_verdict") or "")
        != str(previous_summary.get("selected_contract_verdict") or ""),
    }


def diff_carryover_promotion_gate(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
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
    ready_ticker_delta = diff_ticker_lists(current_ready_tickers, previous_ready_tickers)
    blocked_open_ticker_delta = diff_ticker_lists(current_blocked_open_tickers, previous_blocked_open_tickers)
    pending_t_plus_2_ticker_delta = diff_ticker_lists(current_pending_t_plus_2_tickers, previous_pending_t_plus_2_tickers)
    field_changes = build_carryover_promotion_gate_field_changes(current_summary, previous_summary)
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


def diff_top_priority_action(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
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


def diff_selected_outcome_contract(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
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


def diff_carryover_peer_proof(current_payload: dict[str, Any], previous_payload: dict[str, Any]) -> dict[str, Any]:
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
    ready_delta = diff_ticker_lists(current_ready_tickers, previous_ready_tickers)
    risk_review_delta = diff_ticker_lists(current_risk_review_tickers, previous_risk_review_tickers)
    focus_ticker_changed = str(current_summary.get("focus_ticker") or "") != str(previous_summary.get("focus_ticker") or "")
    focus_proof_verdict_changed = str(current_summary.get("focus_proof_verdict") or "") != str(previous_summary.get("focus_proof_verdict") or "")
    focus_promotion_review_verdict_changed = str(current_summary.get("focus_promotion_review_verdict") or "") != str(previous_summary.get("focus_promotion_review_verdict") or "")
    has_changes = any(
        [
            focus_ticker_changed,
            focus_proof_verdict_changed,
            focus_promotion_review_verdict_changed,
            bool(ready_delta["added"]),
            bool(ready_delta["removed"]),
            bool(risk_review_delta["added"]),
            bool(risk_review_delta["removed"]),
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
        "added_ready_for_promotion_review_tickers": ready_delta["added"],
        "removed_ready_for_promotion_review_tickers": ready_delta["removed"],
        "previous_risk_review_tickers": previous_risk_review_tickers,
        "current_risk_review_tickers": current_risk_review_tickers,
        "added_risk_review_tickers": risk_review_delta["added"],
        "removed_risk_review_tickers": risk_review_delta["removed"],
        "has_changes": has_changes,
    }
