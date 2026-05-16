from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import compare_reports as _compare_reports
from scripts.btst_analysis_utils import resolve_guardrail as _resolve_guardrail
from scripts.btst_profile_replay_utils import (
    analyze_btst_profile_replay_window,
    DEFAULT_GUARDRAIL_NEXT_CLOSE_POSITIVE_RATE,
    DEFAULT_GUARDRAIL_NEXT_HIGH_HIT_RATE,
)
from scripts.btst_report_utils import discover_report_dirs

REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_multi_window_profile_validation_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_multi_window_profile_validation_latest.md"


def _classify_window(comparison: dict[str, Any]) -> str:
    delta = dict(comparison.get("tradeable_surface_delta") or {})
    next_close_positive_rate_delta = delta.get("next_close_positive_rate")
    next_close_return_p10_delta = delta.get("next_close_return_p10")
    t_plus_2_close_return_median_delta = delta.get("t_plus_2_close_return_median")
    t_plus_2_close_positive_rate_delta = delta.get("t_plus_2_close_positive_rate")

    if next_close_positive_rate_delta is not None and float(next_close_positive_rate_delta) < 0 and next_close_return_p10_delta is not None and float(next_close_return_p10_delta) < 0:
        return "keep_baseline_default"
    if next_close_positive_rate_delta is not None and float(next_close_positive_rate_delta) >= 0 and next_close_return_p10_delta is not None and float(next_close_return_p10_delta) >= 0 and (float(next_close_positive_rate_delta) > 0 or float(next_close_return_p10_delta) > 0):
        return "variant_supports_t1_edge"
    if t_plus_2_close_return_median_delta is not None and float(t_plus_2_close_return_median_delta) > 0 and t_plus_2_close_positive_rate_delta is not None and float(t_plus_2_close_positive_rate_delta) >= 0:
        return "variant_improves_t2_but_not_t1"
    return "mixed"


def _resolve_guardrail_status(
    report: dict[str, Any],
    *,
    guardrail_next_high_hit_rate: float,
    guardrail_next_close_positive_rate: float,
) -> str:
    tradeable = dict(dict(report.get("surface_summaries") or {}).get("tradeable") or {})
    if not int(tradeable.get("closed_cycle_count") or 0):
        return "not_enough_closed_tradeable_rows"
    next_high_hit_rate = tradeable.get("next_high_hit_rate_at_threshold")
    next_close_positive_rate = tradeable.get("next_close_positive_rate")
    if next_high_hit_rate is not None and next_close_positive_rate is not None and float(next_high_hit_rate) >= float(guardrail_next_high_hit_rate) and float(next_close_positive_rate) >= float(guardrail_next_close_positive_rate):
        return "passes_closed_tradeable_guardrails"
    return "fails_closed_tradeable_guardrails"


def _resolve_surface_total_count(report: dict[str, Any], surface_name: str) -> int:
    surface_summary = dict(dict(report.get("surface_summaries") or {}).get(surface_name) or {})
    return int(surface_summary.get("total_count") or 0)


def _resolve_threshold_delta(baseline_value: Any, variant_value: Any) -> float | None:
    if baseline_value is None or variant_value is None:
        return None
    return round(float(variant_value) - float(baseline_value), 4)


def _build_runtime_activation_attribution(
    *,
    baseline: dict[str, Any],
    variant: dict[str, Any],
    comparison: dict[str, Any],
    guardrail_next_high_hit_rate: float,
    guardrail_next_close_positive_rate: float,
) -> dict[str, Any]:
    baseline_profile_config = dict(baseline.get("profile_config") or {})
    variant_profile_config = dict(variant.get("profile_config") or {})
    threshold_delta = {
        "select_threshold": _resolve_threshold_delta(baseline_profile_config.get("select_threshold"), variant_profile_config.get("select_threshold")),
        "near_miss_threshold": _resolve_threshold_delta(baseline_profile_config.get("near_miss_threshold"), variant_profile_config.get("near_miss_threshold")),
    }
    selected_count_delta = _resolve_surface_total_count(variant, "selected") - _resolve_surface_total_count(baseline, "selected")
    near_miss_count_delta = _resolve_surface_total_count(variant, "near_miss") - _resolve_surface_total_count(baseline, "near_miss")
    tradeable_count_delta = _resolve_surface_total_count(variant, "tradeable") - _resolve_surface_total_count(baseline, "tradeable")
    execution_eligible_count_delta = _resolve_surface_total_count(variant, "execution_eligible") - _resolve_surface_total_count(baseline, "execution_eligible")
    false_negative_count_delta = int(dict(comparison.get("false_negative_proxy_delta") or {}).get("count") or 0)
    baseline_guardrail_status = _resolve_guardrail_status(
        baseline,
        guardrail_next_high_hit_rate=guardrail_next_high_hit_rate,
        guardrail_next_close_positive_rate=guardrail_next_close_positive_rate,
    )
    variant_guardrail_status = str(comparison.get("guardrail_status") or "")
    guardrail_status_changed = baseline_guardrail_status != variant_guardrail_status
    threshold_probe_active = any(value not in (None, 0, 0.0) for value in threshold_delta.values())
    activation_change_labels: list[str] = []
    if tradeable_count_delta != 0:
        activation_change_labels.append("tradeable_surface")
    if selected_count_delta != 0:
        activation_change_labels.append("selected_surface")
    if near_miss_count_delta != 0:
        activation_change_labels.append("near_miss_surface")
    if execution_eligible_count_delta != 0:
        activation_change_labels.append("execution_eligible_surface")
    if false_negative_count_delta != 0:
        activation_change_labels.append("false_negative_proxy")
    if guardrail_status_changed:
        activation_change_labels.append("guardrail_status")
    zero_delta_reason = None
    if not activation_change_labels:
        if threshold_probe_active:
            zero_delta_reason = "threshold_probe_without_runtime_activation_delta"
        elif dict(variant.get("profile_overrides") or {}):
            zero_delta_reason = "profile_override_without_runtime_activation_delta"
        elif str(baseline.get("profile_name") or "") != str(variant.get("profile_name") or ""):
            zero_delta_reason = "profile_variant_without_runtime_activation_delta"
        else:
            zero_delta_reason = "no_runtime_activation_delta"
    return {
        "selected_count_delta": selected_count_delta,
        "near_miss_count_delta": near_miss_count_delta,
        "tradeable_count_delta": tradeable_count_delta,
        "execution_eligible_count_delta": execution_eligible_count_delta,
        "false_negative_count_delta": false_negative_count_delta,
        "threshold_delta": threshold_delta,
        "threshold_probe_active": threshold_probe_active,
        "profile_override_keys": sorted(dict(variant.get("profile_overrides") or {}).keys()),
        "baseline_guardrail_status": baseline_guardrail_status,
        "variant_guardrail_status": variant_guardrail_status,
        "guardrail_status_changed": guardrail_status_changed,
        "activation_change_labels": activation_change_labels,
        "zero_delta_reason": zero_delta_reason,
    }


def _summarize_row(*, report_dir: Path, baseline: dict[str, Any], variant: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_window(comparison)
    baseline_surface_summaries = dict(baseline.get("surface_summaries") or {})
    variant_surface_summaries = dict(variant.get("surface_summaries") or {})
    return {
        "report_dir": str(report_dir),
        "report_label": report_dir.name,
        "trade_dates": list(baseline.get("trade_dates") or []),
        "baseline_profile": baseline["profile_name"],
        "variant_profile": variant["profile_name"],
        "baseline_tradeable": dict(baseline_surface_summaries.get("tradeable") or {}),
        "variant_tradeable": dict(variant_surface_summaries.get("tradeable") or {}),
        "baseline_selected": dict(baseline_surface_summaries.get("selected") or {}),
        "variant_selected": dict(variant_surface_summaries.get("selected") or {}),
        "baseline_near_miss": dict(baseline_surface_summaries.get("near_miss") or {}),
        "variant_near_miss": dict(variant_surface_summaries.get("near_miss") or {}),
        "baseline_frontier_source_family_summaries": dict(baseline.get("frontier_source_family_summaries") or {}),
        "variant_frontier_source_family_summaries": dict(variant.get("frontier_source_family_summaries") or {}),
        "baseline_source_coverage_summary": dict(baseline.get("source_coverage_summary") or {}),
        "variant_source_coverage_summary": dict(variant.get("source_coverage_summary") or {}),
        "tradeable_surface_delta": dict(comparison.get("tradeable_surface_delta") or {}),
        "guardrail_status": str(comparison.get("guardrail_status") or ""),
        "runtime_activation_attribution": dict(comparison.get("runtime_activation_attribution") or {}),
        "window_recommendation": classification,
    }


def analyze_btst_multi_window_profile_validation(
    reports_root: str | Path,
    *,
    baseline_profile: str,
    variant_profile: str,
    variant_select_threshold: float | None = None,
    variant_near_miss_threshold: float | None = None,
    variant_profile_overrides: dict[str, Any] | None = None,
    report_name_contains: str = "paper_trading_window",
    next_high_hit_threshold: float = 0.02,
    guardrail_next_high_hit_rate: float | None = None,
    guardrail_next_close_positive_rate: float | None = None,
) -> dict[str, Any]:
    report_dirs = discover_report_dirs(reports_root, report_name_contains=report_name_contains)
    resolved_variant_profile_overrides = dict(variant_profile_overrides or {})

    rows: list[dict[str, Any]] = []
    for report_dir in report_dirs:
        baseline = analyze_btst_profile_replay_window(
            report_dir,
            profile_name=baseline_profile,
            label=f"{report_dir.name}:{baseline_profile}",
            next_high_hit_threshold=next_high_hit_threshold,
        )
        baseline_false_negative_surface = dict(baseline["false_negative_proxy_summary"].get("surface_metrics") or {})
        effective_guardrail_next_high_hit_rate = _resolve_guardrail(
            guardrail_next_high_hit_rate,
            baseline_false_negative_surface.get("next_high_hit_rate_at_threshold"),
            DEFAULT_GUARDRAIL_NEXT_HIGH_HIT_RATE,
        )
        effective_guardrail_next_close_positive_rate = _resolve_guardrail(
            guardrail_next_close_positive_rate,
            baseline_false_negative_surface.get("next_close_positive_rate"),
            DEFAULT_GUARDRAIL_NEXT_CLOSE_POSITIVE_RATE,
        )
        variant = analyze_btst_profile_replay_window(
            report_dir,
            profile_name=variant_profile,
            select_threshold=variant_select_threshold,
            near_miss_threshold=variant_near_miss_threshold,
            profile_overrides=resolved_variant_profile_overrides,
            label=f"{report_dir.name}:{variant_profile}",
            next_high_hit_threshold=next_high_hit_threshold,
        )
        comparison = _compare_reports(
            baseline,
            variant,
            guardrail_next_high_hit_rate=effective_guardrail_next_high_hit_rate,
            guardrail_next_close_positive_rate=effective_guardrail_next_close_positive_rate,
        )
        comparison["runtime_activation_attribution"] = _build_runtime_activation_attribution(
            baseline=baseline,
            variant=variant,
            comparison=comparison,
            guardrail_next_high_hit_rate=effective_guardrail_next_high_hit_rate,
            guardrail_next_close_positive_rate=effective_guardrail_next_close_positive_rate,
        )
        rows.append(_summarize_row(report_dir=report_dir, baseline=baseline, variant=variant, comparison=comparison))

    keep_baseline_count = sum(1 for row in rows if row["window_recommendation"] == "keep_baseline_default")
    variant_supports_t1_count = sum(1 for row in rows if row["window_recommendation"] == "variant_supports_t1_edge")
    variant_improves_t2_only_count = sum(1 for row in rows if row["window_recommendation"] == "variant_improves_t2_but_not_t1")
    mixed_count = sum(1 for row in rows if row["window_recommendation"] == "mixed")

    if keep_baseline_count > 0 and variant_supports_t1_count == 0:
        recommendation = "Baseline should remain the default: the variant loses T+1 edge in at least one window without offsetting T+1 improvement elsewhere."
    elif variant_supports_t1_count > 0 and keep_baseline_count == 0:
        recommendation = "Variant is promising across the observed windows and may be ready for a deeper rollout review."
    elif variant_improves_t2_only_count > 0:
        recommendation = "Variant behaves like a T+2 tradeoff rather than a strict BTST upgrade; keep the baseline default unless the objective changes."
    elif rows:
        recommendation = "The observed windows are mixed; keep the baseline default until more evidence accumulates."
    else:
        recommendation = "No matching report windows were found."

    return {
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "report_name_contains": report_name_contains,
        "report_dir_count": len(report_dirs),
        "report_dirs": [str(path) for path in report_dirs],
        "baseline_profile": baseline_profile,
        "variant_profile": variant_profile,
        "variant_select_threshold": variant_select_threshold,
        "variant_near_miss_threshold": variant_near_miss_threshold,
        "variant_profile_overrides": resolved_variant_profile_overrides,
        "next_high_hit_threshold": next_high_hit_threshold,
        "guardrail_next_high_hit_rate": None if not report_dirs else effective_guardrail_next_high_hit_rate,
        "guardrail_next_close_positive_rate": None if not report_dirs else effective_guardrail_next_close_positive_rate,
        "rows": rows,
        "keep_baseline_count": keep_baseline_count,
        "variant_supports_t1_count": variant_supports_t1_count,
        "variant_improves_t2_only_count": variant_improves_t2_only_count,
        "mixed_count": mixed_count,
        "recommendation": recommendation,
    }


def render_btst_multi_window_profile_validation_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Multi-Window Profile Validation")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- reports_root: {analysis['reports_root']}")
    lines.append(f"- report_dir_count: {analysis['report_dir_count']}")
    lines.append(f"- report_name_contains: {analysis['report_name_contains']}")
    lines.append(f"- baseline_profile: {analysis['baseline_profile']}")
    lines.append(f"- variant_profile: {analysis['variant_profile']}")
    lines.append(f"- variant_select_threshold: {analysis['variant_select_threshold']}")
    lines.append(f"- variant_near_miss_threshold: {analysis['variant_near_miss_threshold']}")
    lines.append("")
    lines.append("## Window Summary")
    for row in list(analysis.get("rows") or []):
        lines.append(
            f"- {row['report_label']}: recommendation={row['window_recommendation']}, "
            f"baseline_tradeable={row['baseline_tradeable'].get('total_count')}, "
            f"variant_tradeable={row['variant_tradeable'].get('total_count')}, "
            f"next_close_positive_rate_delta={row['tradeable_surface_delta'].get('next_close_positive_rate')}, "
            f"next_close_return_p10_delta={row['tradeable_surface_delta'].get('next_close_return_p10')}, "
            f"t_plus_2_close_return_median_delta={row['tradeable_surface_delta'].get('t_plus_2_close_return_median')}"
        )
        frontier_source_families = sorted(
            {
                *dict(row.get("baseline_frontier_source_family_summaries") or {}).keys(),
                *dict(row.get("variant_frontier_source_family_summaries") or {}).keys(),
            }
        )
        for source_family in frontier_source_families:
            baseline_summary = dict(dict(row.get("baseline_frontier_source_family_summaries") or {}).get(source_family) or {})
            variant_summary = dict(dict(row.get("variant_frontier_source_family_summaries") or {}).get(source_family) or {})
            lines.append(f"  - frontier_source={source_family}, " f"baseline_tradeable={dict(baseline_summary.get('tradeable') or {}).get('total_count')}, " f"variant_tradeable={dict(variant_summary.get('tradeable') or {}).get('total_count')}, " f"baseline_selected={dict(baseline_summary.get('selected') or {}).get('total_count')}, " f"variant_selected={dict(variant_summary.get('selected') or {}).get('total_count')}")
        baseline_source_coverage = dict(row.get("baseline_source_coverage_summary") or {})
        variant_source_coverage = dict(row.get("variant_source_coverage_summary") or {})
        runtime_activation_attribution = dict(row.get("runtime_activation_attribution") or {})
        if runtime_activation_attribution:
            lines.append(
                "  - "
                f"activation_attribution={runtime_activation_attribution.get('zero_delta_reason') or 'runtime_activation_changed'}, "
                f"selected_delta={runtime_activation_attribution.get('selected_count_delta')}, "
                f"near_miss_delta={runtime_activation_attribution.get('near_miss_count_delta')}, "
                f"tradeable_delta={runtime_activation_attribution.get('tradeable_count_delta')}, "
                f"execution_eligible_delta={runtime_activation_attribution.get('execution_eligible_count_delta')}, "
                f"guardrail_changed={runtime_activation_attribution.get('guardrail_status_changed')}"
            )
        if baseline_source_coverage or variant_source_coverage:
            lines.append(f"  - source_coverage:")
            flow_sources = sorted(
                {
                    *dict(baseline_source_coverage.get("flow_60_source_counts") or {}).keys(),
                    *dict(variant_source_coverage.get("flow_60_source_counts") or {}).keys(),
                }
            )
            for source in flow_sources:
                baseline_count = dict(baseline_source_coverage.get("flow_60_source_counts") or {}).get(source, 0)
                variant_count = dict(variant_source_coverage.get("flow_60_source_counts") or {}).get(source, 0)
                lines.append(f"    - flow_60={source}: baseline={baseline_count}, variant={variant_count}")
            persist_sources = sorted(
                {
                    *dict(baseline_source_coverage.get("persist_120_source_counts") or {}).keys(),
                    *dict(variant_source_coverage.get("persist_120_source_counts") or {}).keys(),
                }
            )
            for source in persist_sources:
                baseline_count = dict(baseline_source_coverage.get("persist_120_source_counts") or {}).get(source, 0)
                variant_count = dict(variant_source_coverage.get("persist_120_source_counts") or {}).get(source, 0)
                lines.append(f"    - persist_120={source}: baseline={baseline_count}, variant={variant_count}")
            close_support_sources = sorted(
                {
                    *dict(baseline_source_coverage.get("close_support_30_source_counts") or {}).keys(),
                    *dict(variant_source_coverage.get("close_support_30_source_counts") or {}).keys(),
                }
            )
            for source in close_support_sources:
                baseline_count = dict(baseline_source_coverage.get("close_support_30_source_counts") or {}).get(source, 0)
                variant_count = dict(variant_source_coverage.get("close_support_30_source_counts") or {}).get(source, 0)
                lines.append(f"    - close_support_30={source}: baseline={baseline_count}, variant={variant_count}")
            committee_sources = sorted(
                {
                    *dict(baseline_source_coverage.get("committee_component_sources_counts") or {}).keys(),
                    *dict(variant_source_coverage.get("committee_component_sources_counts") or {}).keys(),
                }
            )
            for source in committee_sources:
                baseline_count = dict(baseline_source_coverage.get("committee_component_sources_counts") or {}).get(source, 0)
                variant_count = dict(variant_source_coverage.get("committee_component_sources_counts") or {}).get(source, 0)
                lines.append(f"    - committee={source}: baseline={baseline_count}, variant={variant_count}")
    if not list(analysis.get("rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Aggregate Verdict")
    lines.append(f"- keep_baseline_count: {analysis['keep_baseline_count']}")
    lines.append(f"- variant_supports_t1_count: {analysis['variant_supports_t1_count']}")
    lines.append(f"- variant_improves_t2_only_count: {analysis['variant_improves_t2_only_count']}")
    lines.append(f"- mixed_count: {analysis['mixed_count']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a BTST profile variant against a baseline across multiple replay windows.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--report-name-contains", default="paper_trading_window")
    parser.add_argument("--baseline-profile", default="watchlist_zero_catalyst_guard_relief")
    parser.add_argument("--variant-profile", default="watchlist_zero_catalyst_guard_relief")
    parser.add_argument("--variant-select-threshold", type=float, default=None)
    parser.add_argument("--variant-near-miss-threshold", type=float, default=None)
    parser.add_argument("--variant-profile-overrides", default="{}")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--guardrail-next-high-hit-rate", type=float, default=None)
    parser.add_argument("--guardrail-next-close-positive-rate", type=float, default=None)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_multi_window_profile_validation(
        args.reports_root,
        baseline_profile=str(args.baseline_profile),
        variant_profile=str(args.variant_profile),
        variant_select_threshold=args.variant_select_threshold,
        variant_near_miss_threshold=args.variant_near_miss_threshold,
        variant_profile_overrides=json.loads(str(args.variant_profile_overrides or "{}")),
        report_name_contains=str(args.report_name_contains or "paper_trading_window"),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
        guardrail_next_high_hit_rate=args.guardrail_next_high_hit_rate,
        guardrail_next_close_positive_rate=args.guardrail_next_close_positive_rate,
    )

    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_multi_window_profile_validation_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
