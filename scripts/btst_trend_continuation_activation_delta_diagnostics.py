from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


def build_trend_continuation_activation_delta_diagnostics(analysis: Mapping[str, Any]) -> dict[str, Any]:
    rows = [dict(row) for row in list(analysis.get("rows") or []) if isinstance(row, Mapping)]
    zero_delta_reason_counts: Counter[str] = Counter()
    windows_with_activation_change: list[str] = []
    execution_eligible_positive_window_count = 0
    shrink_guard_applied_window_count = 0
    shrink_boundary_overlap_window_count = 0

    for row in rows:
        label = str(row.get("report_label") or row.get("report_dir") or "")
        attribution = dict(row.get("runtime_activation_attribution") or {})
        zero_delta_reason = str(attribution.get("zero_delta_reason") or "").strip()
        if zero_delta_reason:
            zero_delta_reason_counts[zero_delta_reason] += 1
        if int(attribution.get("execution_eligible_count_delta") or 0) > 0:
            execution_eligible_positive_window_count += 1
        if attribution.get("activation_change_labels"):
            windows_with_activation_change.append(label)
        if int(attribution.get("watchlist_shrink_guard_applied_count") or 0) > 0:
            shrink_guard_applied_window_count += 1
        if int(attribution.get("watchlist_shrink_selected_boundary_overlap_count") or 0) > 0:
            shrink_boundary_overlap_window_count += 1

    dominant_zero_delta_reason = None
    if zero_delta_reason_counts:
        dominant_zero_delta_reason = max(zero_delta_reason_counts.items(), key=lambda item: item[1])[0]

    return {
        "baseline_profile": str(analysis.get("baseline_profile") or "trend_continuation_strength_v2"),
        "candidate_profile": str(analysis.get("variant_profile") or "trend_continuation_strength_v3"),
        "report_dir_count": int(analysis.get("report_dir_count") or len(rows)),
        "zero_delta_reason_counts": dict(zero_delta_reason_counts),
        "dominant_zero_delta_reason": dominant_zero_delta_reason,
        "execution_eligible_positive_window_count": execution_eligible_positive_window_count,
        "windows_with_activation_change": sorted(label for label in windows_with_activation_change if label),
        "shrink_guard_applied_window_count": shrink_guard_applied_window_count,
        "shrink_boundary_overlap_window_count": shrink_boundary_overlap_window_count,
        "all_windows_zero_delta": bool(rows) and len(windows_with_activation_change) == 0,
    }


def render_trend_continuation_activation_delta_diagnostics_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Trend Continuation Activation Delta Diagnostics",
        "",
        f"- baseline_profile: {payload['baseline_profile']}",
        f"- candidate_profile: {payload['candidate_profile']}",
        f"- report_dir_count: {payload['report_dir_count']}",
        f"- all_windows_zero_delta: {payload['all_windows_zero_delta']}",
        f"- dominant_zero_delta_reason: {payload['dominant_zero_delta_reason']}",
        f"- execution_eligible_positive_window_count: {payload['execution_eligible_positive_window_count']}",
        "",
        "## Zero Delta Reasons",
        "",
    ]
    reason_counts = dict(payload.get("zero_delta_reason_counts") or {})
    if reason_counts:
        for key, value in sorted(reason_counts.items()):
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize why trend continuation validation did or did not create runtime activation delta.")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)

    analysis = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    payload = build_trend_continuation_activation_delta_diagnostics(analysis)

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_trend_continuation_activation_delta_diagnostics_markdown(payload), encoding="utf-8")
    return 0
