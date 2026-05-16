from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _summarize_regime_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        gate = str(row.get("gate") or "unknown").strip() or "unknown"
        bucket = summary.setdefault(
            gate,
            {
                "row_count": 0,
                "execution_eligible_count": 0,
                "selected_count": 0,
                "near_miss_count": 0,
                "blocked_count": 0,
            },
        )
        bucket["row_count"] += 1
        if bool(row.get("execution_eligible")):
            bucket["execution_eligible_count"] += 1
        decision = str(row.get("decision") or "").strip()
        if decision == "selected":
            bucket["selected_count"] += 1
        elif decision == "near_miss":
            bucket["near_miss_count"] += 1
        elif decision == "blocked":
            bucket["blocked_count"] += 1
    return summary


def _summarize_multi_window_validation(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload or not isinstance(payload, Mapping):
        return None
    rows = list(payload.get("rows") or [])
    changed_window_labels: list[str] = []
    for row in rows:
        delta = dict(row.get("tradeable_surface_delta") or {})
        baseline_count = dict(row.get("baseline_tradeable") or {}).get("total_count")
        variant_count = dict(row.get("variant_tradeable") or {}).get("total_count")
        if any(delta.get(key) not in (None, 0, 0.0) for key in ("next_close_positive_rate", "next_close_return_p10", "next_close_payoff_ratio", "t_plus_2_close_return_median", "t_plus_2_close_positive_rate")) or baseline_count != variant_count:
            changed_window_labels.append(str(row.get("report_label") or "unknown"))
    return {
        "report_dir_count": int(payload.get("report_dir_count") or 0),
        "changed_window_count": len(changed_window_labels),
        "changed_window_labels": changed_window_labels,
        "recommendation": str(payload.get("recommendation") or ""),
    }


def _compute_expansion_ratio(*, baseline_count: int, variant_count: int) -> float:
    if baseline_count <= 0:
        return 1.0 if variant_count > 0 else 0.0
    return (float(variant_count) - float(baseline_count)) / float(baseline_count)


def _extract_surface_total_count(row: dict[str, Any], *, prefix: str, surface_name: str) -> int:
    surface_payload = row.get(f"{prefix}_{surface_name}")
    if surface_payload is None:
        surface_payload = dict(row.get(f"{prefix}_surface_summaries") or {}).get(surface_name)
    if isinstance(surface_payload, dict):
        return int(surface_payload.get("total_count") or 0)
    return int(surface_payload or 0)


def _summarize_structural_guardrail(payload: dict[str, Any] | None) -> dict[str, Any]:
    selected_ratio_threshold = 0.15
    near_miss_ratio_threshold = 0.20
    excessive_window_labels: list[str] = []
    rows = list(payload.get("rows") or []) if isinstance(payload, Mapping) else []
    for row in rows:
        if str(row.get("window_recommendation") or "").strip() == "variant_supports_t1_edge":
            continue
        selected_ratio = _compute_expansion_ratio(
            baseline_count=_extract_surface_total_count(row, prefix="baseline", surface_name="selected"),
            variant_count=_extract_surface_total_count(row, prefix="variant", surface_name="selected"),
        )
        near_miss_ratio = _compute_expansion_ratio(
            baseline_count=_extract_surface_total_count(row, prefix="baseline", surface_name="near_miss"),
            variant_count=_extract_surface_total_count(row, prefix="variant", surface_name="near_miss"),
        )
        if selected_ratio > selected_ratio_threshold or near_miss_ratio > near_miss_ratio_threshold:
            excessive_window_labels.append(str(row.get("report_label") or "unknown"))
    excessive_window_count = len(excessive_window_labels)
    return {
        "selected_ratio_threshold": selected_ratio_threshold,
        "near_miss_ratio_threshold": near_miss_ratio_threshold,
        "excessive_window_count": excessive_window_count,
        "excessive_window_labels": excessive_window_labels,
        "blocker_candidate": excessive_window_count >= 2,
    }


def build_admission_replay_summary(
    *,
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    regime_rows: list[dict[str, Any]],
    baseline_metrics: dict[str, Any],
    prior_audit: dict[str, Any],
    multi_window_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    approximate_surface_changed = (
        baseline_payload.get("selected") != candidate_payload.get("selected")
        or baseline_payload.get("near_miss") != candidate_payload.get("near_miss")
    )
    regime_counts = _summarize_regime_rows(regime_rows)
    multi_window_summary = _summarize_multi_window_validation(multi_window_validation)
    structural_guardrail = _summarize_structural_guardrail(multi_window_validation)
    blind_spot_reasons: list[str] = []
    if not approximate_surface_changed:
        blind_spot_reasons.append("identical_selected_and_near_miss_surfaces")
        blind_spot_reasons.append("approximate_backtest_ignores_regime_prior_and_execution_contract_logic")

    requires_runtime_replay = not approximate_surface_changed
    runtime_recommendation = "runtime_replay_required_before_conclusion"
    if approximate_surface_changed and regime_counts.get("normal_trade", {}).get("execution_eligible_count", 0) > 0:
        requires_runtime_replay = False
        runtime_recommendation = "candidate_ready_for_replay_window_validation"
    if multi_window_summary and int(multi_window_summary.get("report_dir_count") or 0) > 0 and int(multi_window_summary.get("changed_window_count") or 0) == 0:
        requires_runtime_replay = False
        runtime_recommendation = "keep_baseline_default_no_replay_delta"
        blind_spot_reasons.append("multi_window_replay_showed_no_observable_delta")
    return {
        "approximate_surface_changed": approximate_surface_changed,
        "requires_runtime_replay": requires_runtime_replay,
        "runtime_recommendation": runtime_recommendation,
        "blind_spot_reasons": blind_spot_reasons,
        "baseline_metrics": dict(baseline_metrics),
        "prior_audit": dict(prior_audit),
        "regime_counts": regime_counts,
        "multi_window_validation": multi_window_summary,
        "structural_guardrail": structural_guardrail,
        "baseline_selected_count": len(list(baseline_payload.get("selected") or [])),
        "candidate_selected_count": len(list(candidate_payload.get("selected") or [])),
        "baseline_near_miss_count": len(list(baseline_payload.get("near_miss") or [])),
        "candidate_near_miss_count": len(list(candidate_payload.get("near_miss") or [])),
    }


def _parse_execution_contract_markdown(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        if "ticker" in line and "execution_eligible" in line:
            continue
        if line.startswith("|---"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) != 7:
            continue
        ticker, _bucket, decision, execution_eligible, _downgrade_reasons, gate, prior = parts
        rows.append(
            {
                "ticker": ticker,
                "decision": decision,
                "execution_eligible": _parse_bool(execution_eligible),
                "gate": gate,
                "prior": prior,
            }
        )
    return rows


def _render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Admission Edge Replay Validation",
        "",
        f"- approximate_surface_changed: {summary['approximate_surface_changed']}",
        f"- requires_runtime_replay: {summary['requires_runtime_replay']}",
        f"- runtime_recommendation: {summary['runtime_recommendation']}",
        "",
        "## Blind Spot Reasons",
        "",
    ]
    blind_spot_reasons = list(summary.get("blind_spot_reasons") or [])
    if blind_spot_reasons:
        for reason in blind_spot_reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("- none")

    lines.extend(["", "## Regime Counts", ""])
    for gate, counts in (summary.get("regime_counts") or {}).items():
        lines.append(f"### {gate}")
        lines.append("")
        for key, value in counts.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    multi_window_summary = dict(summary.get("multi_window_validation") or {})
    if multi_window_summary:
        lines.extend(["## Multi-Window Replay", ""])
        lines.append(f"- report_dir_count: {multi_window_summary.get('report_dir_count', 0)}")
        lines.append(f"- changed_window_count: {multi_window_summary.get('changed_window_count', 0)}")
        lines.append(f"- changed_window_labels: {multi_window_summary.get('changed_window_labels', [])}")
        lines.append(f"- recommendation: {multi_window_summary.get('recommendation', '')}")
        lines.append("")

    structural_guardrail = dict(summary.get("structural_guardrail") or {})
    if structural_guardrail:
        lines.extend(["## Structural Guardrail", ""])
        lines.append(f"- selected_ratio_threshold: {structural_guardrail.get('selected_ratio_threshold')}")
        lines.append(f"- near_miss_ratio_threshold: {structural_guardrail.get('near_miss_ratio_threshold')}")
        lines.append(f"- excessive_window_count: {structural_guardrail.get('excessive_window_count')}")
        lines.append(f"- excessive_window_labels: {structural_guardrail.get('excessive_window_labels')}")
        lines.append(f"- blocker_candidate: {structural_guardrail.get('blocker_candidate')}")
        lines.append("")

    lines.extend(["## Baseline Metrics", ""])
    for key, value in (summary.get("baseline_metrics") or {}).items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate whether btst_admission_edge_recovery needs replay/runtime validation.")
    parser.add_argument("--approximate-json", required=True)
    parser.add_argument("--baseline-json", required=True)
    parser.add_argument("--prior-audit-json", required=True)
    parser.add_argument("--execution-contract-md", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--multi-window-json")
    parser.add_argument("--baseline-profile", default="btst_precision_v2")
    parser.add_argument("--candidate-profile", default="btst_admission_edge_recovery")
    args = parser.parse_args(argv)

    approximate_payload = json.loads(Path(args.approximate_json).read_text(encoding="utf-8"))
    baseline_json_payload = json.loads(Path(args.baseline_json).read_text(encoding="utf-8"))
    prior_audit_payload = json.loads(Path(args.prior_audit_json).read_text(encoding="utf-8"))
    multi_window_payload = json.loads(Path(args.multi_window_json).read_text(encoding="utf-8")) if args.multi_window_json else None
    regime_rows = _parse_execution_contract_markdown(Path(args.execution_contract_md))

    summary = build_admission_replay_summary(
        baseline_payload=dict(approximate_payload.get(args.baseline_profile) or {}),
        candidate_payload=dict(approximate_payload.get(args.candidate_profile) or {}),
        regime_rows=regime_rows,
        baseline_metrics=dict(baseline_json_payload.get("baseline_metrics") or {}),
        prior_audit=dict(prior_audit_payload),
        multi_window_validation=multi_window_payload,
    )

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(_render_markdown(summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
