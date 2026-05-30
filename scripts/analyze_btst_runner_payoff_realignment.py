from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _as_float(value: Any) -> float:
    return float(value or 0.0)


def _as_int(value: Any) -> int:
    return int(value or 0)


def _count_formal_source_drag_entries(formal_source_summary: dict[str, Any], *, baseline_hit_rate: float) -> int:
    drag_entries = 0
    for source_summary in formal_source_summary.values():
        source_metrics = dict(source_summary or {})
        sample_count = _as_int(source_metrics.get("count"))
        source_hit_rate = _as_float(source_metrics.get("hit_rate_15pct"))
        if sample_count > 0 and source_hit_rate <= baseline_hit_rate:
            drag_entries += 1
    return drag_entries


def _extract_surface_hit_rate(payload: dict[str, Any], *, decision: str) -> float:
    legacy_summary = dict(payload.get(f"{decision}_summary") or {})
    if legacy_summary:
        return _as_float(legacy_summary.get("hit_rate_15pct"))

    weekly_surface_summaries = dict(payload.get("weekly_surface_summaries") or {})
    decision_summary = dict(weekly_surface_summaries.get(decision) or {})
    return _as_float(decision_summary.get("max_future_high_return_2_5d_hit_rate_at_15pct"))


def _extract_formal_source_summary(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    legacy_summary = dict(payload.get("formal_source_summary") or {})
    if legacy_summary:
        return legacy_summary

    breakdown = list(payload.get("selected_candidate_source_breakdown") or [])
    return {
        str(entry.get("candidate_source") or ""): {
            "count": _as_int(entry.get("count")),
            "hit_rate_15pct": _as_float(entry.get("max_future_high_return_2_5d_hit_rate_at_15pct")),
        }
        for entry in breakdown
        if str(entry.get("candidate_source") or "")
    }


def _extract_runner_recall_summary(payload: dict[str, Any]) -> tuple[float, int]:
    legacy_summary = dict(payload.get("runner_recall_summary") or {})
    if legacy_summary:
        return (
            _as_float(legacy_summary.get("hit_rate_15pct")),
            _as_int(legacy_summary.get("watchlist_filter_diagnostics_false_negatives")),
        )

    false_negative_summary = dict(payload.get("runner_false_negative_summary") or {})
    candidate_source_counts = dict(false_negative_summary.get("candidate_source_counts") or {})
    surface_metrics = dict(false_negative_summary.get("surface_metrics") or {})
    return (
        _as_float(surface_metrics.get("max_future_high_return_2_5d_hit_rate_at_15pct")),
        _as_int(candidate_source_counts.get("watchlist_filter_diagnostics")),
    )


def _extract_formal_payoff_drag_candidate_sources(
    payload: dict[str, Any],
    *,
    formal_source_summary: dict[str, dict[str, Any]],
    selected_hit_rate: float,
) -> list[str]:
    source_diagnosis = dict(payload.get("source_diagnosis") or {})
    if "formal_payoff_drag_candidate_sources" in source_diagnosis:
        return sorted(
            str(source)
            for source in list(source_diagnosis.get("formal_payoff_drag_candidate_sources") or [])
            if str(source or "")
        )

    if "selected_payoff_drag_candidate_sources" in payload:
        return sorted(
            str(source)
            for source in list(payload.get("selected_payoff_drag_candidate_sources") or [])
            if str(source or "")
        )

    return sorted(
        source
        for source, source_metrics in formal_source_summary.items()
        if _as_int(source_metrics.get("count")) > 0 and _as_float(source_metrics.get("hit_rate_15pct")) <= selected_hit_rate
    )


def _normalize_artifactized_report(payload: dict[str, Any]) -> dict[str, Any]:
    diagnosis = dict(payload.get("diagnosis") or {})
    recommendation = dict(payload.get("recommendation") or {})
    source_diagnosis = dict(payload.get("source_diagnosis") or {})
    if "selected_payoff_drag_candidate_sources" in payload:
        raise ValueError("Artifactized runner-payoff report must not include legacy selected_payoff_drag_candidate_sources")
    if "formal_payoff_drag_candidate_sources" not in source_diagnosis:
        raise ValueError("Artifactized runner-payoff report is missing source_diagnosis.formal_payoff_drag_candidate_sources")
    formal_payoff_drag_candidate_sources = sorted(
        str(source)
        for source in list(source_diagnosis.get("formal_payoff_drag_candidate_sources") or [])
        if str(source or "")
    )
    return {
        "diagnosis": {
            "primary_problem": str(diagnosis.get("primary_problem") or "selected_payoff_not_underperforming_near_miss"),
            "selected_hit_rate_15pct": round(_as_float(diagnosis.get("selected_hit_rate_15pct")), 4),
            "near_miss_hit_rate_15pct": round(_as_float(diagnosis.get("near_miss_hit_rate_15pct")), 4),
            "payoff_gap_vs_near_miss_15pct": round(_as_float(diagnosis.get("payoff_gap_vs_near_miss_15pct")), 4),
            "runner_recall_hit_rate_15pct": round(_as_float(diagnosis.get("runner_recall_hit_rate_15pct")), 4),
            "watchlist_filter_diagnostics_false_negatives": _as_int(diagnosis.get("watchlist_filter_diagnostics_false_negatives")),
            "formal_source_drag_count": _as_int(diagnosis.get("formal_source_drag_count")),
        },
        "recommendation": recommendation,
        "source_diagnosis": {
            "formal_payoff_drag_candidate_sources": formal_payoff_drag_candidate_sources,
        },
    }


def analyze_btst_runner_payoff_realignment(*, weekly_validation_json: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(weekly_validation_json).read_text(encoding="utf-8"))
    if isinstance(payload.get("diagnosis"), dict) and isinstance(payload.get("recommendation"), dict):
        return _normalize_artifactized_report(payload)

    selected_hit_rate = _extract_surface_hit_rate(payload, decision="selected")
    near_miss_hit_rate = _extract_surface_hit_rate(payload, decision="near_miss")
    formal_source_summary = _extract_formal_source_summary(payload)
    runner_recall_hit_rate, false_negatives = _extract_runner_recall_summary(payload)
    formal_payoff_drag_candidate_sources = _extract_formal_payoff_drag_candidate_sources(
        payload,
        formal_source_summary=formal_source_summary,
        selected_hit_rate=selected_hit_rate,
    )
    payoff_gap = round(near_miss_hit_rate - selected_hit_rate, 4)
    if "selected_payoff_drag_candidate_sources" in payload:
        formal_source_drag_count = len(list(payload.get("selected_payoff_drag_candidate_sources") or []))
    else:
        formal_source_drag_count = _count_formal_source_drag_entries(
            formal_source_summary,
            baseline_hit_rate=selected_hit_rate,
        )
    selected_underperforming = selected_hit_rate < near_miss_hit_rate
    runner_recall_signal_present = false_negatives > 0 and runner_recall_hit_rate > selected_hit_rate

    if selected_underperforming and runner_recall_signal_present:
        primary_problem = "formal_selected_target_misalignment"
        recommendation = {
            "status": "staged_formal_shrink_plus_runner_recall",
            "next_steps": ["formal_source_shadow", "payoff_first_runner_recall"],
        }
    elif selected_underperforming:
        primary_problem = "formal_selected_payoff_drag_without_runner_recall_confirmation"
        recommendation = {
            "status": "formal_shrink_only",
            "next_steps": ["formal_source_shadow"],
        }
    else:
        primary_problem = "selected_payoff_not_underperforming_near_miss"
        recommendation = {
            "status": "hold_current_path",
            "next_steps": ["monitor_next_window"],
        }

    report = {
        "diagnosis": {
            "primary_problem": primary_problem,
            "selected_hit_rate_15pct": round(selected_hit_rate, 4),
            "near_miss_hit_rate_15pct": round(near_miss_hit_rate, 4),
            "payoff_gap_vs_near_miss_15pct": payoff_gap,
            "runner_recall_hit_rate_15pct": round(runner_recall_hit_rate, 4),
            "watchlist_filter_diagnostics_false_negatives": false_negatives,
            "formal_source_drag_count": formal_source_drag_count,
        },
        "recommendation": recommendation,
        "source_diagnosis": {
            "formal_payoff_drag_candidate_sources": formal_payoff_drag_candidate_sources,
        },
    }
    return report


def compare_btst_runner_payoff_realignment_windows(*, weekly_validation_jsons: list[str | Path]) -> dict[str, Any]:
    if not weekly_validation_jsons:
        raise ValueError("weekly_validation_jsons must not be empty")

    window_reports: list[dict[str, Any]] = []
    drag_source_windows: dict[str, int] = {}
    recommendation_statuses: list[str] = []
    for weekly_validation_json in weekly_validation_jsons:
        report = analyze_btst_runner_payoff_realignment(weekly_validation_json=weekly_validation_json)
        window_reports.append(
            {
                "weekly_validation_json": str(Path(weekly_validation_json)),
                "report": report,
            }
        )
        recommendation_statuses.append(str(report.get("recommendation", {}).get("status") or "unknown"))
        for source in list(report.get("source_diagnosis", {}).get("formal_payoff_drag_candidate_sources") or []):
            drag_source_windows[str(source)] = int(drag_source_windows.get(str(source), 0)) + 1

    window_count = len(window_reports)
    overall_recommendation_status = recommendation_statuses[0] if len(set(recommendation_statuses)) == 1 else "mixed"
    shrink_supporting_statuses = {"staged_formal_shrink_plus_runner_recall", "formal_shrink_only"}
    all_windows_support_shrink = all(status in shrink_supporting_statuses for status in recommendation_statuses)

    if all_windows_support_shrink:
        stable_sources = sorted(source for source, count in drag_source_windows.items() if count == window_count)
        conditional_sources = sorted(source for source, count in drag_source_windows.items() if 0 < count < window_count)
    else:
        stable_sources = []
        conditional_sources = []

    if "layer_c_watchlist" in stable_sources:
        stable_formal_shrink_lane: str | None = "layer_c_watchlist"
    elif len(stable_sources) == 1:
        stable_formal_shrink_lane = stable_sources[0]
    else:
        stable_formal_shrink_lane = None

    if "layer_c_watchlist" in stable_sources:
        layer_c_watchlist_policy = "stable_formal_shrink_lane"
    elif "layer_c_watchlist" in conditional_sources:
        layer_c_watchlist_policy = "conditional_only"
    else:
        layer_c_watchlist_policy = "hold_current_path"

    if "short_trade_boundary" in stable_sources:
        short_trade_boundary_policy = "stable_formal_shrink_lane"
    elif "short_trade_boundary" in conditional_sources:
        short_trade_boundary_policy = "conditional_only"
    else:
        short_trade_boundary_policy = "hold_current_path"

    return {
        "window_count": window_count,
        "overall_recommendation_status": overall_recommendation_status,
        "window_reports": window_reports,
        "source_lane_recommendation": {
            "stable_formal_shrink_lane": stable_formal_shrink_lane,
            "stable_formal_shrink_sources": stable_sources,
            "conditional_formal_shrink_sources": conditional_sources,
            "layer_c_watchlist_policy": layer_c_watchlist_policy,
            "short_trade_boundary_policy": short_trade_boundary_policy,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze BTST runner/payoff weekly validation and summarize the staged recommendation.")
    parser.add_argument("weekly_validation_json", help="Path to the weekly validation JSON payload")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = analyze_btst_runner_payoff_realignment(weekly_validation_json=Path(args.weekly_validation_json))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
