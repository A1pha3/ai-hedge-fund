from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.btst_analysis_utils import compare_reports as _compare_reports, resolve_guardrail as _resolve_guardrail
from scripts.btst_profile_replay_utils import (
    DEFAULT_GUARDRAIL_NEXT_CLOSE_POSITIVE_RATE,
    DEFAULT_GUARDRAIL_NEXT_HIGH_HIT_RATE,
    analyze_btst_profile_replay_window,
)
from src.targets import SHORT_TRADE_TARGET_PROFILES, get_short_trade_target_profile


DEFAULT_PROFILE_VARIANTS = ["staged_breakout", "staged_breakout_profitability_relief", "aggressive", "conservative"]


def _parse_profile_names(values: list[str] | None) -> list[str]:
    names: list[str] = []
    for raw in values or []:
        token = str(raw or "").strip()
        if not token:
            continue
        get_short_trade_target_profile(token)
        if token not in names:
            names.append(token)
    return names


def _resolve_variant_profiles(*, baseline_profile: str, variant_profiles: list[str] | None) -> list[str]:
    parsed = _parse_profile_names(variant_profiles)
    if parsed:
        return [name for name in parsed if name != baseline_profile]
    return [name for name in DEFAULT_PROFILE_VARIANTS if name in SHORT_TRADE_TARGET_PROFILES and name != baseline_profile]


def analyze_btst_profile_frontier(
    input_path: str | Path,
    *,
    baseline_profile: str = "default",
    variant_profiles: list[str] | None = None,
    next_high_hit_threshold: float = 0.02,
    guardrail_next_high_hit_rate: float | None = None,
    guardrail_next_close_positive_rate: float | None = None,
) -> dict[str, Any]:
    baseline_profile = str(baseline_profile or "default")
    get_short_trade_target_profile(baseline_profile)
    resolved_variant_profiles = _resolve_variant_profiles(baseline_profile=baseline_profile, variant_profiles=variant_profiles)

    baseline = analyze_btst_profile_replay_window(
        input_path,
        profile_name=baseline_profile,
        label=baseline_profile,
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

    variant_analyses = [
        analyze_btst_profile_replay_window(
            input_path,
            profile_name=profile_name,
            label=profile_name,
            next_high_hit_threshold=next_high_hit_threshold,
        )
        for profile_name in resolved_variant_profiles
    ]
    comparisons = [
        _compare_reports(
            baseline,
            variant,
            guardrail_next_high_hit_rate=effective_guardrail_next_high_hit_rate,
            guardrail_next_close_positive_rate=effective_guardrail_next_close_positive_rate,
        )
        for variant in variant_analyses
    ]

    ranked_variants: list[dict[str, Any]] = []
    for variant, comparison in zip(variant_analyses, comparisons):
        tradeable_surface = dict(variant["surface_summaries"]["tradeable"])
        ranked_variants.append(
            {
                "profile_name": variant["profile_name"],
                "label": variant["label"],
                "guardrail_status": comparison["guardrail_status"],
                "closed_cycle_tradeable_count": int(tradeable_surface.get("closed_cycle_count", 0)),
                "tradeable_count": int(tradeable_surface.get("total_count", 0)),
                "next_high_hit_rate_at_threshold": tradeable_surface.get("next_high_hit_rate_at_threshold"),
                "next_close_positive_rate": tradeable_surface.get("next_close_positive_rate"),
                "t_plus_2_close_positive_rate": tradeable_surface.get("t_plus_2_close_positive_rate"),
                "comparison_note": comparison["comparison_note"],
            }
        )

    passing_variants = [row for row in ranked_variants if row["guardrail_status"] == "passes_closed_tradeable_guardrails"]
    best_variant_pool = passing_variants if passing_variants else ranked_variants
    best_variant = None
    if best_variant_pool:
        best_variant = max(
            best_variant_pool,
            key=lambda row: (
                int(row["closed_cycle_tradeable_count"]),
                int(row["tradeable_count"]),
                float(row["next_close_positive_rate"] if row["next_close_positive_rate"] is not None else -1.0),
                float(row["next_high_hit_rate_at_threshold"] if row["next_high_hit_rate_at_threshold"] is not None else -1.0),
            ),
        )
        best_variant["selection_basis"] = "guardrail_passing_frontier" if passing_variants else "fallback_highest_tradeable_surface"

    return {
        "input_path": str(Path(input_path).expanduser().resolve()),
        "baseline": baseline,
        "variants": variant_analyses,
        "comparisons": comparisons,
        "ranked_variants": ranked_variants,
        "best_variant": best_variant,
        "next_high_hit_threshold": round(float(next_high_hit_threshold), 4),
        "guardrail_next_high_hit_rate": effective_guardrail_next_high_hit_rate,
        "guardrail_next_close_positive_rate": effective_guardrail_next_close_positive_rate,
    }


def render_btst_profile_frontier_markdown(analysis: dict[str, Any]) -> str:
    baseline = dict(analysis["baseline"])
    lines: list[str] = []
    lines.append("# BTST Profile Frontier Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- input_path: {analysis['input_path']}")
    lines.append(f"- baseline_profile: {baseline['profile_name']}")
    lines.append(f"- trade_dates: {baseline['trade_dates']}")
    lines.append(f"- next_high_hit_threshold: {analysis['next_high_hit_threshold']}")
    lines.append(f"- guardrail_next_high_hit_rate: {analysis['guardrail_next_high_hit_rate']}")
    lines.append(f"- guardrail_next_close_positive_rate: {analysis['guardrail_next_close_positive_rate']}")
    lines.append(f"- best_variant: {analysis['best_variant']}")
    lines.append("")
    lines.append("## Baseline Summary")
    lines.append(f"- profile_config: {baseline['profile_config']}")
    lines.append(f"- decision_counts: {baseline['decision_counts']}")
    lines.append(f"- tradeable_surface: {baseline['surface_summaries']['tradeable']}")
    lines.append(f"- false_negative_proxy_summary: {baseline['false_negative_proxy_summary']}")
    lines.append(f"- recommendation: {baseline['recommendation']}")
    lines.append("")
    if analysis["variants"]:
        lines.append("## Variant Comparison")
        for variant, comparison in zip(analysis["variants"], analysis["comparisons"]):
            lines.append(f"### {variant['profile_name']}")
            lines.append(f"- profile_config: {variant['profile_config']}")
            lines.append(f"- decision_counts: {variant['decision_counts']}")
            lines.append(f"- tradeable_surface: {variant['surface_summaries']['tradeable']}")
            lines.append(f"- false_negative_proxy_summary: {variant['false_negative_proxy_summary']}")
            lines.append(f"- guardrail_status: {comparison['guardrail_status']}")
            lines.append(f"- comparison_note: {comparison['comparison_note']}")
            lines.append(f"- tradeable_surface_delta: {comparison['tradeable_surface_delta']}")
            lines.append(f"- false_negative_proxy_delta: {comparison['false_negative_proxy_delta']}")
            lines.append(f"- top_tradeable_event_catalyst: {[row.get('explainability_payload', {}).get('event_catalyst') for row in variant['top_tradeable_rows'][:3]]}")
            lines.append("")
    lines.append("## Baseline Top False Negatives")
    for row in baseline["top_false_negative_rows"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: decision={row['decision']}, next_high_return={row['next_high_return']}, next_close_return={row['next_close_return']}, score_target={row['score_target']}, reasons={row['false_negative_proxy_reasons']}"
        )
    if not baseline["top_false_negative_rows"]:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay BTST windows under multiple short-trade profiles and compare closed-cycle outcomes.")
    parser.add_argument("input_path", help="Path to a selection_target_replay_input.json file, selection_artifacts directory, or report directory.")
    parser.add_argument("--baseline-profile", default="default", help="Baseline short-trade profile. Available: " + ", ".join(sorted(SHORT_TRADE_TARGET_PROFILES.keys())))
    parser.add_argument("--profile", action="append", default=[], help="Additional short-trade profile(s) to compare against baseline.")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--guardrail-next-high-hit-rate", type=float, default=None)
    parser.add_argument("--guardrail-next-close-positive-rate", type=float, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analysis = analyze_btst_profile_frontier(
        args.input_path,
        baseline_profile=args.baseline_profile,
        variant_profiles=list(args.profile),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
        guardrail_next_high_hit_rate=args.guardrail_next_high_hit_rate,
        guardrail_next_close_positive_rate=args.guardrail_next_close_positive_rate,
    )
    if args.output_json is not None:
        args.output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md is not None:
        args.output_md.write_text(render_btst_profile_frontier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()