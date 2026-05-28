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


def analyze_btst_runner_payoff_realignment(*, weekly_validation_json: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(weekly_validation_json).read_text(encoding="utf-8"))
    selected_hit_rate = _extract_surface_hit_rate(payload, decision="selected")
    near_miss_hit_rate = _extract_surface_hit_rate(payload, decision="near_miss")
    formal_source_summary = _extract_formal_source_summary(payload)
    runner_recall_hit_rate, false_negatives = _extract_runner_recall_summary(payload)
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
    }
    return report


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
