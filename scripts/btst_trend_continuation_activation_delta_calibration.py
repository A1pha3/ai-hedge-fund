from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_multi_window_profile_validation import analyze_btst_multi_window_profile_validation
from scripts.btst_trend_continuation_activation_delta_diagnostics import (
    build_trend_continuation_activation_delta_diagnostics,
)

CALIBRATION_CANDIDATES = [
    {
        "candidate_name": "lift_0p04",
        "profile_overrides": {
            "watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift": 0.04,
            "watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max": 0.10,
            "watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max": 0.40,
            "watchlist_filter_diagnostics_selected_only_shrink_close_strength_max": 0.58,
        },
    },
    {
        "candidate_name": "lift_0p03_relaxed_close",
        "profile_overrides": {
            "watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift": 0.03,
            "watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max": 0.10,
            "watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max": 0.40,
            "watchlist_filter_diagnostics_selected_only_shrink_close_strength_max": 0.62,
        },
    },
    {
        "candidate_name": "lift_0p03_relaxed_trend",
        "profile_overrides": {
            "watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift": 0.03,
            "watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max": 0.10,
            "watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max": 0.45,
            "watchlist_filter_diagnostics_selected_only_shrink_close_strength_max": 0.58,
        },
    },
]

def rank_calibration_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        results,
        key=lambda item: (
            -(int(dict(item["diagnostics"]).get("execution_eligible_positive_window_count") or 0)),
            -(int(dict(item["analysis"]).get("variant_supports_t1_count") or 0)),
            int(dict(item["analysis"]).get("mixed_count") or 0),
            item["candidate_name"],
        ),
    )

def run_calibration(*, reports_root: str | Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for candidate in CALIBRATION_CANDIDATES:
        analysis = analyze_btst_multi_window_profile_validation(
            reports_root,
            baseline_profile="trend_continuation_strength_v2",
            variant_profile="trend_continuation_strength_v3",
            variant_profile_overrides=dict(candidate["profile_overrides"]),
        )
        diagnostics = build_trend_continuation_activation_delta_diagnostics(analysis)
        results.append(
            {
                "candidate_name": candidate["candidate_name"],
                "profile_overrides": dict(candidate["profile_overrides"]),
                "analysis": analysis,
                "diagnostics": diagnostics,
            }
        )
    ranked = rank_calibration_candidates(results)
    return {
        "baseline_profile": "trend_continuation_strength_v2",
        "candidate_profile": "trend_continuation_strength_v3",
        "ranked_candidates": ranked,
        "best_candidate": ranked[0] if ranked else None,
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a narrow activation-delta calibration grid for trend continuation v3.")
    parser.add_argument("--reports-root", default="data/reports")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)

    payload = run_calibration(reports_root=args.reports_root)

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Trend Continuation Activation Delta Calibration",
        "",
        f"- best_candidate: {dict(payload.get('best_candidate') or {}).get('candidate_name')}",
        "",
        "## Ranked Candidates",
        "",
    ]
    for item in list(payload.get("ranked_candidates") or []):
        diagnostics = dict(item.get("diagnostics") or {})
        analysis = dict(item.get("analysis") or {})
        lines.append(
            f"- {item['candidate_name']}: execution_eligible_positive_window_count={diagnostics.get('execution_eligible_positive_window_count')}, "
            f"variant_supports_t1_count={analysis.get('variant_supports_t1_count')}, mixed_count={analysis.get('mixed_count')}"
        )
    output_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return 0
