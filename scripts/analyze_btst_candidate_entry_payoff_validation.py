from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import compare_reports as _compare_reports
from scripts.btst_candidate_entry_utils import (
    build_watchlist_avoid_weak_structure_filter,
)
from scripts.btst_profile_replay_utils import (
    analyze_btst_profile_replay_window,
    DEFAULT_GUARDRAIL_NEXT_CLOSE_POSITIVE_RATE,
    DEFAULT_GUARDRAIL_NEXT_HIGH_HIT_RATE,
)
from scripts.btst_report_utils import (
    discover_nested_report_dirs as discover_report_dirs,
)

REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_entry_payoff_validation_20260520.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_entry_payoff_validation_20260520.md"


def build_variant_structural_overrides(
    *,
    breakout_freshness_max: float | None = None,
    trend_acceleration_max: float | None = None,
    volume_expansion_quality_max: float | None = None,
    close_strength_max: float | None = None,
    catalyst_freshness_max: float | None = None,
) -> dict[str, Any] | None:
    if (
        breakout_freshness_max is None
        and trend_acceleration_max is None
        and volume_expansion_quality_max is None
        and close_strength_max is None
        and catalyst_freshness_max is None
    ):
        return None
    return {
        "exclude_candidate_entries": [
            build_watchlist_avoid_weak_structure_filter(
                breakout_freshness_max=breakout_freshness_max,
                trend_acceleration_max=trend_acceleration_max,
                volume_expansion_quality_max=volume_expansion_quality_max,
                close_strength_max=close_strength_max,
                catalyst_freshness_max=catalyst_freshness_max,
            )
        ]
    }


def _resolve_surface_total_count(report: dict[str, Any], surface_name: str) -> int:
    surface_summary = dict(dict(report.get("surface_summaries") or {}).get(surface_name) or {})
    return int(surface_summary.get("total_count") or 0)


def _classify_window(*, comparison: dict[str, Any], baseline: dict[str, Any], variant: dict[str, Any]) -> str:
    tradeable_delta = dict(comparison.get("tradeable_surface_delta") or {})
    selected_delta = dict(comparison.get("selected_surface_delta") or {})
    filtered_delta = int(dict(variant.get("filtered_candidate_entry_summary") or {}).get("count") or 0) - int(dict(baseline.get("filtered_candidate_entry_summary") or {}).get("count") or 0)
    execution_eligible_count_delta = _resolve_surface_total_count(variant, "execution_eligible") - _resolve_surface_total_count(baseline, "execution_eligible")
    false_negative_delta = int(dict(comparison.get("false_negative_proxy_delta") or {}).get("count") or 0)
    next_close_positive_rate_delta = tradeable_delta.get("next_close_positive_rate")
    next_close_return_p10_delta = tradeable_delta.get("next_close_return_p10")

    if next_close_positive_rate_delta is not None and float(next_close_positive_rate_delta) < 0 and next_close_return_p10_delta is not None and float(next_close_return_p10_delta) < 0:
        return "keep_baseline_default"
    if next_close_positive_rate_delta is not None and float(next_close_positive_rate_delta) >= 0 and next_close_return_p10_delta is not None and float(next_close_return_p10_delta) >= 0 and (float(next_close_positive_rate_delta) > 0 or float(next_close_return_p10_delta) > 0):
        return "variant_supports_t1_actionable_edge"
    if (
        filtered_delta > 0
        and int(tradeable_delta.get("total_count") or 0) == 0
        and int(selected_delta.get("total_count") or 0) == 0
        and execution_eligible_count_delta == 0
        and false_negative_delta == 0
    ):
        return "entry_cleanup_without_actionable_delta"
    if (
        filtered_delta > 0
        and int(tradeable_delta.get("total_count") or 0) == 0
        and int(selected_delta.get("total_count") or 0) == 0
        and execution_eligible_count_delta == 0
        and false_negative_delta < 0
    ):
        return "entry_cleanup_reduces_false_negative_proxy"
    return "mixed"


def _build_row(*, report_dir: Path, baseline: dict[str, Any], variant: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    baseline_filtered = dict(baseline.get("filtered_candidate_entry_summary") or {})
    variant_filtered = dict(variant.get("filtered_candidate_entry_summary") or {})
    classification = _classify_window(comparison=comparison, baseline=baseline, variant=variant)
    execution_eligible_count_delta = _resolve_surface_total_count(variant, "execution_eligible") - _resolve_surface_total_count(baseline, "execution_eligible")
    return {
        "report_dir": str(report_dir),
        "report_label": report_dir.name,
        "trade_dates": list(baseline.get("trade_dates") or []),
        "profile_name": str(baseline.get("profile_name") or ""),
        "baseline_structural_variant": str(baseline.get("structural_variant") or "baseline"),
        "variant_structural_variant": str(variant.get("structural_variant") or ""),
        "variant_structural_overrides": dict(variant.get("structural_overrides") or {}),
        "tradeable_surface_delta": dict(comparison.get("tradeable_surface_delta") or {}),
        "selected_surface_delta": dict(comparison.get("selected_surface_delta") or {}),
        "false_negative_proxy_delta": dict(comparison.get("false_negative_proxy_delta") or {}),
        "guardrail_status": str(comparison.get("guardrail_status") or ""),
        "selected_guardrail_status": str(comparison.get("selected_guardrail_status") or ""),
        "comparison_note": str(comparison.get("comparison_note") or ""),
        "baseline_filtered_candidate_entry_count": int(baseline_filtered.get("count") or 0),
        "variant_filtered_candidate_entry_count": int(variant_filtered.get("count") or 0),
        "filtered_candidate_entry_delta": int(variant_filtered.get("count") or 0) - int(baseline_filtered.get("count") or 0),
        "variant_filtered_candidate_entry_surface": dict(variant_filtered.get("surface_metrics") or {}),
        "execution_eligible_count_delta": execution_eligible_count_delta,
        "candidate_entry_filter_observability": dict(variant.get("candidate_entry_filter_observability") or {}),
        "payoff_classification": classification,
    }


def analyze_btst_candidate_entry_payoff_validation(
    reports_root: str | Path,
    *,
    profile_name: str = "default",
    baseline_structural_variant: str = "baseline",
    variant_structural_variant: str = "exclude_watchlist_avoid_weak_structure_entries",
    variant_structural_overrides: dict[str, Any] | None = None,
    report_name_contains: str = "paper_trading_window",
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    report_dirs = discover_report_dirs([reports_root], report_name_contains=report_name_contains)
    rows: list[dict[str, Any]] = []

    for report_dir in report_dirs:
        baseline = analyze_btst_profile_replay_window(
            report_dir,
            profile_name=profile_name,
            structural_variant=baseline_structural_variant,
            label=f"{report_dir.name}:{baseline_structural_variant}",
            next_high_hit_threshold=next_high_hit_threshold,
        )
        variant = analyze_btst_profile_replay_window(
            report_dir,
            profile_name=profile_name,
            structural_variant=variant_structural_variant,
            label=f"{report_dir.name}:{variant_structural_variant}",
            structural_overrides=variant_structural_overrides,
            next_high_hit_threshold=next_high_hit_threshold,
        )
        comparison = _compare_reports(
            baseline,
            variant,
            guardrail_next_high_hit_rate=DEFAULT_GUARDRAIL_NEXT_HIGH_HIT_RATE,
            guardrail_next_close_positive_rate=DEFAULT_GUARDRAIL_NEXT_CLOSE_POSITIVE_RATE,
        )
        rows.append(_build_row(report_dir=report_dir, baseline=baseline, variant=variant, comparison=comparison))

    keep_baseline_count = sum(1 for row in rows if row["payoff_classification"] == "keep_baseline_default")
    variant_supports_t1_count = sum(1 for row in rows if row["payoff_classification"] == "variant_supports_t1_actionable_edge")
    cleanup_only_count = sum(1 for row in rows if row["payoff_classification"] == "entry_cleanup_without_actionable_delta")
    false_negative_relief_count = sum(1 for row in rows if row["payoff_classification"] == "entry_cleanup_reduces_false_negative_proxy")
    mixed_count = sum(1 for row in rows if row["payoff_classification"] == "mixed")

    if keep_baseline_count > 0:
        recommendation = "Baseline should remain the default: weak-structure candidate-entry filtering hurts actionable T+1 quality in at least one window."
    elif variant_supports_t1_count > 0 and keep_baseline_count == 0:
        recommendation = "Weak-structure candidate-entry rule shows actionable T+1 payoff support in the observed windows and merits deeper rollout review."
    elif cleanup_only_count > 0 and variant_supports_t1_count == 0 and keep_baseline_count == 0:
        recommendation = "Weak-structure candidate-entry rule is currently behaving like entry cleanup rather than direct actionable payoff uplift; keep it in shadow governance until execution evidence or payoff edge improves."
    elif false_negative_relief_count > 0 and keep_baseline_count == 0:
        recommendation = "Weak-structure candidate-entry rule may be reducing false-negative pressure without harming actionable surfaces, but it still lacks direct actionable payoff uplift."
    elif rows:
        recommendation = "Observed windows are mixed; keep the weak-structure rule in governed shadow review until payoff evidence becomes clearer."
    else:
        recommendation = "No matching report windows were found."

    return {
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "report_name_contains": report_name_contains,
        "report_dir_count": len(report_dirs),
        "report_dirs": [str(path) for path in report_dirs],
        "profile_name": profile_name,
        "baseline_structural_variant": baseline_structural_variant,
        "variant_structural_variant": variant_structural_variant,
        "variant_structural_overrides": dict(variant_structural_overrides or {}),
        "next_high_hit_threshold": round(float(next_high_hit_threshold), 4),
        "rows": rows,
        "keep_baseline_count": keep_baseline_count,
        "variant_supports_t1_count": variant_supports_t1_count,
        "cleanup_only_count": cleanup_only_count,
        "false_negative_relief_count": false_negative_relief_count,
        "mixed_count": mixed_count,
        "recommendation": recommendation,
    }


def render_btst_candidate_entry_payoff_validation_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Entry Payoff Validation")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- reports_root: {analysis['reports_root']}")
    lines.append(f"- report_dir_count: {analysis['report_dir_count']}")
    lines.append(f"- report_name_contains: {analysis['report_name_contains']}")
    lines.append(f"- profile_name: {analysis['profile_name']}")
    lines.append(f"- baseline_structural_variant: {analysis['baseline_structural_variant']}")
    lines.append(f"- variant_structural_variant: {analysis['variant_structural_variant']}")
    if analysis.get("variant_structural_overrides"):
        lines.append(f"- variant_structural_overrides: {analysis['variant_structural_overrides']}")
    lines.append("")
    lines.append("## Window Summary")
    for row in list(analysis.get("rows") or []):
        lines.append(
            f"- {row['report_label']}: payoff_classification={row['payoff_classification']}, "
            f"filtered_candidate_entry_delta={row['filtered_candidate_entry_delta']}, "
            f"tradeable_total_delta={row['tradeable_surface_delta'].get('total_count')}, "
            f"selected_total_delta={row['selected_surface_delta'].get('total_count')}, "
            f"execution_eligible_delta={row['execution_eligible_count_delta']}, "
            f"next_close_positive_rate_delta={row['tradeable_surface_delta'].get('next_close_positive_rate')}, "
            f"next_close_return_p10_delta={row['tradeable_surface_delta'].get('next_close_return_p10')}, "
            f"false_negative_delta={row['false_negative_proxy_delta'].get('count')}"
        )
        if row.get("variant_filtered_candidate_entry_surface"):
            lines.append(
                "  - "
                f"filtered_candidate_entry_surface={row['variant_filtered_candidate_entry_surface']}"
            )
        if row.get("variant_structural_overrides"):
            lines.append(f"  - variant_structural_overrides={row['variant_structural_overrides']}")
        if row.get("comparison_note"):
            lines.append(f"  - comparison_note={row['comparison_note']}")
    if not list(analysis.get("rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Aggregate Verdict")
    lines.append(f"- keep_baseline_count: {analysis['keep_baseline_count']}")
    lines.append(f"- variant_supports_t1_count: {analysis['variant_supports_t1_count']}")
    lines.append(f"- cleanup_only_count: {analysis['cleanup_only_count']}")
    lines.append(f"- false_negative_relief_count: {analysis['false_negative_relief_count']}")
    lines.append(f"- mixed_count: {analysis['mixed_count']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the payoff impact of a BTST candidate-entry structural rule across multiple replay windows.")
    parser.add_argument("--reports-root", default="data/reports")
    parser.add_argument("--report-name-contains", default="paper_trading_window")
    parser.add_argument("--profile-name", default="default")
    parser.add_argument("--baseline-structural-variant", default="baseline")
    parser.add_argument("--variant-structural-variant", default="exclude_watchlist_avoid_weak_structure_entries")
    parser.add_argument("--variant-breakout-freshness-max", type=float)
    parser.add_argument("--variant-trend-acceleration-max", type=float)
    parser.add_argument("--variant-volume-expansion-quality-max", type=float)
    parser.add_argument("--variant-close-strength-max", type=float)
    parser.add_argument("--variant-catalyst-freshness-max", type=float)
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    variant_structural_overrides = build_variant_structural_overrides(
        breakout_freshness_max=args.variant_breakout_freshness_max,
        trend_acceleration_max=args.variant_trend_acceleration_max,
        volume_expansion_quality_max=args.variant_volume_expansion_quality_max,
        close_strength_max=args.variant_close_strength_max,
        catalyst_freshness_max=args.variant_catalyst_freshness_max,
    )
    analysis = analyze_btst_candidate_entry_payoff_validation(
        args.reports_root,
        profile_name=str(args.profile_name or "default"),
        baseline_structural_variant=str(args.baseline_structural_variant or "baseline"),
        variant_structural_variant=str(args.variant_structural_variant or "exclude_watchlist_avoid_weak_structure_entries"),
        variant_structural_overrides=variant_structural_overrides,
        report_name_contains=str(args.report_name_contains or "paper_trading_window"),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
    )

    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_candidate_entry_payoff_validation_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
