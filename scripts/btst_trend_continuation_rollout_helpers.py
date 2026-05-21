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


def _build_activation_delta_diagnostics_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    diagnostics = dict(payload or {})
    return {
        "provided": bool(diagnostics),
        "report_dir_count": _coerce_int(diagnostics.get("report_dir_count")),
        "all_windows_zero_delta": bool(diagnostics.get("all_windows_zero_delta")) if diagnostics else None,
        "dominant_zero_delta_reason": diagnostics.get("dominant_zero_delta_reason"),
        "execution_eligible_positive_window_count": _coerce_int(diagnostics.get("execution_eligible_positive_window_count")),
    }


def _build_activation_delta_calibration_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    calibration = dict(payload or {})
    ranked_candidates = [dict(item) for item in list(calibration.get("ranked_candidates") or []) if isinstance(item, Mapping)]
    best_candidate = dict(calibration.get("best_candidate") or {})
    best_analysis = dict(best_candidate.get("analysis") or {})
    best_diagnostics = dict(best_candidate.get("diagnostics") or {})

    best_candidate_blockers: list[str] = []
    if best_candidate:
        if _coerce_int(best_diagnostics.get("report_dir_count")) <= 0:
            best_candidate_blockers.append("best_candidate_missing_report_dirs")
        if bool(best_diagnostics.get("all_windows_zero_delta")):
            best_candidate_blockers.append("best_candidate_all_windows_zero_delta")
        if _coerce_int(best_diagnostics.get("execution_eligible_positive_window_count")) <= 0:
            best_candidate_blockers.append("best_candidate_missing_execution_eligible_activation")
        if _coerce_int(best_analysis.get("keep_baseline_count")) > 0:
            best_candidate_blockers.append("best_candidate_keeps_baseline")
        if _coerce_int(best_analysis.get("variant_supports_t1_count")) <= 0:
            best_candidate_blockers.append("best_candidate_lacks_t1_support")

    return {
        "provided": bool(calibration),
        "ranked_candidate_count": len(ranked_candidates),
        "best_candidate_name": str(best_candidate.get("candidate_name") or "") or None,
        "best_candidate_report_dir_count": _coerce_int(best_diagnostics.get("report_dir_count")),
        "best_candidate_execution_eligible_positive_window_count": _coerce_int(best_diagnostics.get("execution_eligible_positive_window_count")),
        "best_candidate_all_windows_zero_delta": bool(best_diagnostics.get("all_windows_zero_delta")) if best_candidate else None,
        "best_candidate_blockers": best_candidate_blockers,
        "best_candidate_governance_safe": bool(best_candidate) and not best_candidate_blockers,
    }


def build_trend_continuation_rollout_assessment(
    analysis: Mapping[str, Any],
    *,
    baseline_profile: str = "trend_continuation_strength_v2",
    candidate_profile: str = "trend_continuation_strength_v3",
    activation_delta_diagnostics: Mapping[str, Any] | None = None,
    activation_delta_calibration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [dict(row) for row in list(analysis.get("rows") or []) if isinstance(row, Mapping)]
    keep_baseline_count = _coerce_int(analysis.get("keep_baseline_count"))
    variant_supports_t1_count = _coerce_int(analysis.get("variant_supports_t1_count"))
    variant_improves_t2_only_count = _coerce_int(analysis.get("variant_improves_t2_only_count"))
    mixed_count = _coerce_int(analysis.get("mixed_count"))
    execution_eligible_evidence = _build_execution_eligible_evidence(rows)
    runtime_activation_summary = _build_runtime_activation_summary(rows)
    activation_delta_diagnostics_summary = _build_activation_delta_diagnostics_summary(activation_delta_diagnostics)
    activation_delta_calibration_summary = _build_activation_delta_calibration_summary(activation_delta_calibration)

    blockers: list[str] = []
    if keep_baseline_count > 0:
        blockers.append("keep_baseline_window_present")
    if variant_supports_t1_count <= 0:
        blockers.append("no_window_supports_t1_edge")
    if not execution_eligible_evidence["has_positive_execution_eligible_evidence"]:
        blockers.append("no_execution_eligible_activation_evidence")
    if runtime_activation_summary["all_windows_zero_delta"]:
        blockers.append("no_runtime_activation_delta")
    if activation_delta_diagnostics_summary["provided"]:
        if activation_delta_diagnostics_summary["all_windows_zero_delta"]:
            blockers.append("no_runtime_activation_delta")
        if (
            activation_delta_diagnostics_summary["all_windows_zero_delta"] is False
            and activation_delta_diagnostics_summary["execution_eligible_positive_window_count"] <= 0
        ):
            blockers.append("activation_delta_without_execution_eligible_support")
    if not activation_delta_calibration_summary["provided"]:
        blockers.append("missing_calibration_evidence")
    else:
        if activation_delta_calibration_summary["ranked_candidate_count"] <= 0:
            blockers.append("no_qualifying_calibration_best_candidate")
        if activation_delta_calibration_summary["best_candidate_report_dir_count"] <= 0:
            blockers.append("no_calibration_report_dirs")
        if activation_delta_calibration_summary["best_candidate_name"] is None:
            blockers.append("no_qualifying_calibration_best_candidate")
        elif not activation_delta_calibration_summary["best_candidate_governance_safe"]:
            blockers.append("calibration_best_candidate_not_governance_safe")
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
        "activation_delta_diagnostics": activation_delta_diagnostics_summary,
        "activation_delta_calibration": activation_delta_calibration_summary,
        "blockers": list(dict.fromkeys(blockers)),
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
        "## Activation Delta Diagnostics",
        "",
        f"- provided: {payload['activation_delta_diagnostics']['provided']}",
        f"- report_dir_count: {payload['activation_delta_diagnostics']['report_dir_count']}",
        f"- all_windows_zero_delta: {payload['activation_delta_diagnostics']['all_windows_zero_delta']}",
        f"- dominant_zero_delta_reason: {payload['activation_delta_diagnostics']['dominant_zero_delta_reason']}",
        f"- execution_eligible_positive_window_count: {payload['activation_delta_diagnostics']['execution_eligible_positive_window_count']}",
        "",
        "## Activation Delta Calibration",
        "",
        f"- provided: {payload['activation_delta_calibration']['provided']}",
        f"- ranked_candidate_count: {payload['activation_delta_calibration']['ranked_candidate_count']}",
        f"- best_candidate_name: {payload['activation_delta_calibration']['best_candidate_name']}",
        f"- best_candidate_report_dir_count: {payload['activation_delta_calibration']['best_candidate_report_dir_count']}",
        f"- best_candidate_execution_eligible_positive_window_count: {payload['activation_delta_calibration']['best_candidate_execution_eligible_positive_window_count']}",
        f"- best_candidate_all_windows_zero_delta: {payload['activation_delta_calibration']['best_candidate_all_windows_zero_delta']}",
        f"- best_candidate_governance_safe: {payload['activation_delta_calibration']['best_candidate_governance_safe']}",
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
