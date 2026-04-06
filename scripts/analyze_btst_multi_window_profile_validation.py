from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import compare_reports as _compare_reports, resolve_guardrail as _resolve_guardrail
from scripts.btst_profile_replay_utils import (
    DEFAULT_GUARDRAIL_NEXT_CLOSE_POSITIVE_RATE,
    DEFAULT_GUARDRAIL_NEXT_HIGH_HIT_RATE,
    analyze_btst_profile_replay_window,
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

    if (
        next_close_positive_rate_delta is not None
        and float(next_close_positive_rate_delta) < 0
        and next_close_return_p10_delta is not None
        and float(next_close_return_p10_delta) < 0
    ):
        return "keep_baseline_default"
    if (
        next_close_positive_rate_delta is not None
        and float(next_close_positive_rate_delta) >= 0
        and next_close_return_p10_delta is not None
        and float(next_close_return_p10_delta) >= 0
        and (
            float(next_close_positive_rate_delta) > 0
            or float(next_close_return_p10_delta) > 0
        )
    ):
        return "variant_supports_t1_edge"
    if (
        t_plus_2_close_return_median_delta is not None
        and float(t_plus_2_close_return_median_delta) > 0
        and t_plus_2_close_positive_rate_delta is not None
        and float(t_plus_2_close_positive_rate_delta) >= 0
    ):
        return "variant_improves_t2_but_not_t1"
    return "mixed"


def _summarize_row(*, report_dir: Path, baseline: dict[str, Any], variant: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_window(comparison)
    return {
        "report_dir": str(report_dir),
        "report_label": report_dir.name,
        "trade_dates": list(baseline.get("trade_dates") or []),
        "baseline_profile": baseline["profile_name"],
        "variant_profile": variant["profile_name"],
        "baseline_tradeable": dict(baseline["surface_summaries"]["tradeable"]),
        "variant_tradeable": dict(variant["surface_summaries"]["tradeable"]),
        "tradeable_surface_delta": dict(comparison.get("tradeable_surface_delta") or {}),
        "guardrail_status": str(comparison.get("guardrail_status") or ""),
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
