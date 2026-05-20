from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _coerce_int(value: Any) -> int:
    return int(value or 0)


def _build_execution_eligible_evidence(rows: Iterable[dict[str, Any]]) -> dict[str, int | bool]:
    positive_window_count = 0
    non_halt_execution_eligible_count = 0
    for row in rows:
        runtime_activation_attribution = dict(row.get("runtime_activation_attribution") or {})
        execution_eligible_count_delta = _coerce_int(runtime_activation_attribution.get("execution_eligible_count_delta"))
        if execution_eligible_count_delta > 0:
            positive_window_count += 1
            non_halt_execution_eligible_count += execution_eligible_count_delta
    return {
        "positive_window_count": positive_window_count,
        "non_halt_execution_eligible_count": non_halt_execution_eligible_count,
        "has_positive_execution_eligible_evidence": non_halt_execution_eligible_count > 0,
    }


def _build_runtime_activation_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(rows)
    zero_delta_reasons: dict[str, int] = {}
    for row in items:
        runtime_activation_attribution = dict(row.get("runtime_activation_attribution") or {})
        zero_delta_reason = str(runtime_activation_attribution.get("zero_delta_reason") or "").strip()
        if zero_delta_reason:
            zero_delta_reasons[zero_delta_reason] = int(zero_delta_reasons.get(zero_delta_reason, 0)) + 1
    dominant_zero_delta_reason = None
    if zero_delta_reasons:
        dominant_zero_delta_reason = max(zero_delta_reasons.items(), key=lambda item: item[1])[0]
    return {
        "zero_delta_reason_counts": zero_delta_reasons,
        "dominant_zero_delta_reason": dominant_zero_delta_reason,
        "all_windows_zero_delta": bool(items) and sum(zero_delta_reasons.values()) == len(items),
    }


def build_trend_continuation_rollout_assessment(
    analysis: Mapping[str, Any],
    *,
    baseline_profile: str = "trend_continuation_strength_v2",
    candidate_profile: str = "trend_continuation_strength_v3",
) -> dict[str, Any]:
    rows = [dict(row) for row in list(analysis.get("rows") or []) if isinstance(row, Mapping)]
    keep_baseline_count = _coerce_int(analysis.get("keep_baseline_count"))
    variant_supports_t1_count = _coerce_int(analysis.get("variant_supports_t1_count"))
    variant_improves_t2_only_count = _coerce_int(analysis.get("variant_improves_t2_only_count"))
    mixed_count = _coerce_int(analysis.get("mixed_count"))
    execution_eligible_evidence = _build_execution_eligible_evidence(rows)
    runtime_activation_summary = _build_runtime_activation_summary(rows)

    blockers: list[str] = []
    if keep_baseline_count > 0:
        blockers.append("keep_baseline_window_present")
    if variant_supports_t1_count <= 0:
        blockers.append("no_window_supports_t1_edge")
    if not execution_eligible_evidence["has_positive_execution_eligible_evidence"]:
        blockers.append("no_execution_eligible_activation_evidence")
    if runtime_activation_summary["all_windows_zero_delta"]:
        blockers.append("no_runtime_activation_delta")
    if variant_improves_t2_only_count > 0 and variant_supports_t1_count <= 0:
        blockers.append("t2_only_tradeoff_without_t1_upgrade")

    return {
        "baseline_profile": str(analysis.get("baseline_profile") or baseline_profile),
        "candidate_profile": str(analysis.get("variant_profile") or candidate_profile),
        "report_dir_count": _coerce_int(analysis.get("report_dir_count")),
        "keep_baseline_count": keep_baseline_count,
        "variant_supports_t1_count": variant_supports_t1_count,
        "variant_improves_t2_only_count": variant_improves_t2_only_count,
        "mixed_count": mixed_count,
        "recommendation": str(analysis.get("recommendation") or ""),
        "execution_eligible_evidence": execution_eligible_evidence,
        "runtime_activation_summary": runtime_activation_summary,
        "blockers": blockers,
        "action": "hold" if blockers else "promote",
    }


def render_trend_continuation_rollout_assessment_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Trend Continuation Rollout Assessment",
        "",
        f"- action: {payload['action']}",
        f"- baseline_profile: {payload['baseline_profile']}",
        f"- candidate_profile: {payload['candidate_profile']}",
        f"- keep_baseline_count: {payload['keep_baseline_count']}",
        f"- variant_supports_t1_count: {payload['variant_supports_t1_count']}",
        f"- variant_improves_t2_only_count: {payload['variant_improves_t2_only_count']}",
        f"- mixed_count: {payload['mixed_count']}",
        "",
        "## Execution Eligible Evidence",
        "",
        f"- positive_window_count: {payload['execution_eligible_evidence']['positive_window_count']}",
        f"- non_halt_execution_eligible_count: {payload['execution_eligible_evidence']['non_halt_execution_eligible_count']}",
        f"- has_positive_execution_eligible_evidence: {payload['execution_eligible_evidence']['has_positive_execution_eligible_evidence']}",
        "",
        "## Runtime Activation Summary",
        "",
        f"- all_windows_zero_delta: {payload['runtime_activation_summary']['all_windows_zero_delta']}",
        f"- dominant_zero_delta_reason: {payload['runtime_activation_summary']['dominant_zero_delta_reason']}",
        "",
        "## Blockers",
        "",
    ]
    blockers = list(payload.get("blockers") or [])
    if blockers:
        lines.extend(f"- {blocker}" for blocker in blockers)
    else:
        lines.append("- none")
    lines.extend(["", "## Recommendation", "", f"- {payload['recommendation']}"])
    return "\n".join(lines).rstrip() + "\n"
