from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_multi_window_profile_validation import analyze_btst_multi_window_profile_validation
from scripts.btst_trend_continuation_activation_delta_diagnostics import (
    build_trend_continuation_activation_delta_diagnostics,
)

DEFAULT_BASELINE_PROFILE = "trend_continuation_strength_v2"
DEFAULT_CANDIDATE_PROFILE = "trend_continuation_strength_v3"

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


def _coerce_int(value: Any) -> int:
    return int(value or 0)


def build_calibration_candidate_governance_blockers(
    item: dict[str, Any] | None,
    *,
    baseline_profile: str = DEFAULT_BASELINE_PROFILE,
    candidate_profile: str = DEFAULT_CANDIDATE_PROFILE,
) -> list[str]:
    candidate = dict(item or {})
    analysis = dict(candidate.get("analysis") or {})
    diagnostics = dict(candidate.get("diagnostics") or {})

    resolved_baseline_profile = str(candidate.get("baseline_profile") or analysis.get("baseline_profile") or diagnostics.get("baseline_profile") or "").strip()
    resolved_candidate_profile = str(candidate.get("candidate_profile") or analysis.get("variant_profile") or diagnostics.get("candidate_profile") or "").strip()

    blockers: list[str] = []
    if resolved_baseline_profile != baseline_profile:
        blockers.append("best_candidate_baseline_profile_mismatch")
    if resolved_candidate_profile != candidate_profile:
        blockers.append("best_candidate_candidate_profile_mismatch")
    if _coerce_int(diagnostics.get("report_dir_count")) <= 0:
        blockers.append("best_candidate_missing_report_dirs")
    if bool(diagnostics.get("all_windows_zero_delta")):
        blockers.append("best_candidate_all_windows_zero_delta")
    if _coerce_int(diagnostics.get("execution_eligible_positive_window_count")) <= 0:
        blockers.append("best_candidate_missing_execution_eligible_activation")
    if _coerce_int(analysis.get("keep_baseline_count")) > 0:
        blockers.append("best_candidate_keeps_baseline")
    if _coerce_int(analysis.get("variant_supports_t1_count")) <= 0:
        blockers.append("best_candidate_lacks_t1_support")
    return blockers


def _candidate_is_selection_eligible(item: dict[str, Any]) -> bool:
    return not build_calibration_candidate_governance_blockers(item)


def rank_calibration_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        results,
        key=lambda item: (
            0 if _candidate_is_selection_eligible(item) else 1,
            -(int(dict(item.get("diagnostics") or {}).get("execution_eligible_positive_window_count") or 0)),
            -(int(dict(item.get("analysis") or {}).get("variant_supports_t1_count") or 0)),
            int(dict(item.get("analysis") or {}).get("mixed_count") or 0),
            str(item.get("candidate_name") or ""),
        ),
    )


def run_calibration(*, reports_root: str | Path) -> dict[str, Any]:
    baseline_profile = DEFAULT_BASELINE_PROFILE
    candidate_profile = DEFAULT_CANDIDATE_PROFILE
    calibration_results: list[dict[str, Any]] = []
    resolved_reports_root = Path(reports_root)

    for candidate in CALIBRATION_CANDIDATES:
        profile_overrides = dict(candidate["profile_overrides"])
        analysis = analyze_btst_multi_window_profile_validation(
            resolved_reports_root,
            baseline_profile=baseline_profile,
            variant_profile=candidate_profile,
            variant_profile_overrides=profile_overrides,
        )
        diagnostics = build_trend_continuation_activation_delta_diagnostics(analysis)
        calibration_results.append(
            {
                "candidate_name": str(candidate["candidate_name"]),
                "profile_overrides": profile_overrides,
                "analysis": analysis,
                "diagnostics": diagnostics,
            }
        )

    ranked_candidates = rank_calibration_candidates(calibration_results)
    best_candidate = next((item for item in ranked_candidates if _candidate_is_selection_eligible(item)), None)
    return {
        "baseline_profile": baseline_profile,
        "candidate_profile": candidate_profile,
        "ranked_candidates": ranked_candidates,
        "best_candidate": best_candidate,
    }


def render_calibration_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Trend Continuation Activation Delta Calibration",
        "",
        f"- baseline_profile: {payload.get('baseline_profile')}",
        f"- candidate_profile: {payload.get('candidate_profile')}",
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
    return "\n".join(lines).rstrip() + "\n"


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
    output_md.write_text(render_calibration_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
