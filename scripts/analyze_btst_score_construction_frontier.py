from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_micro_window_regression import _compare_reports
from scripts.analyze_btst_profile_frontier import (
    _resolve_guardrail,
    analyze_btst_profile_replay_window,
)


SCORE_CONSTRUCTION_VARIANTS: dict[str, dict[str, Any]] = {
    "prepared_breakout_balance": {
        "breakout_freshness_weight": 0.08,
        "trend_acceleration_weight": 0.20,
        "volume_expansion_quality_weight": 0.20,
        "close_strength_weight": 0.06,
        "sector_resonance_weight": 0.04,
        "catalyst_freshness_weight": 0.20,
        "layer_c_alignment_weight": 0.22,
    },
    "catalyst_volume_balance": {
        "breakout_freshness_weight": 0.16,
        "trend_acceleration_weight": 0.18,
        "volume_expansion_quality_weight": 0.22,
        "close_strength_weight": 0.10,
        "sector_resonance_weight": 0.08,
        "catalyst_freshness_weight": 0.16,
        "layer_c_alignment_weight": 0.10,
    },
    "trend_alignment_balance": {
        "breakout_freshness_weight": 0.16,
        "trend_acceleration_weight": 0.24,
        "volume_expansion_quality_weight": 0.16,
        "close_strength_weight": 0.08,
        "sector_resonance_weight": 0.08,
        "catalyst_freshness_weight": 0.12,
        "layer_c_alignment_weight": 0.16,
    },
}

DEFAULT_GUARDRAIL_NEXT_HIGH_HIT_RATE = 0.5217
DEFAULT_GUARDRAIL_NEXT_CLOSE_POSITIVE_RATE = 0.5652


def _parse_variant_names(values: list[str] | None) -> list[str]:
    names: list[str] = []
    for raw in values or []:
        token = str(raw or "").strip()
        if not token:
            continue
        if token not in SCORE_CONSTRUCTION_VARIANTS:
            available = ", ".join(sorted(SCORE_CONSTRUCTION_VARIANTS))
            raise ValueError(f"Unknown score construction variant: {token}. Available: {available}")
        if token not in names:
            names.append(token)
    return names


def analyze_btst_score_construction_frontier(
    input_path: str | Path,
    *,
    baseline_profile: str = "default",
    variant_names: list[str] | None = None,
    next_high_hit_threshold: float = 0.02,
    guardrail_next_high_hit_rate: float | None = None,
    guardrail_next_close_positive_rate: float | None = None,
) -> dict[str, Any]:
    resolved_variant_names = _parse_variant_names(variant_names) or list(SCORE_CONSTRUCTION_VARIANTS)

    baseline = analyze_btst_profile_replay_window(
        input_path,
        profile_name=baseline_profile,
        label="baseline",
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

    variants = [
        analyze_btst_profile_replay_window(
            input_path,
            profile_name=baseline_profile,
            label=variant_name,
            next_high_hit_threshold=next_high_hit_threshold,
            profile_overrides=SCORE_CONSTRUCTION_VARIANTS[variant_name],
        )
        for variant_name in resolved_variant_names
    ]
    comparisons = [
        _compare_reports(
            baseline,
            variant,
            guardrail_next_high_hit_rate=effective_guardrail_next_high_hit_rate,
            guardrail_next_close_positive_rate=effective_guardrail_next_close_positive_rate,
        )
        for variant in variants
    ]

    ranked_variants: list[dict[str, Any]] = []
    for variant, comparison in zip(variants, comparisons):
        tradeable_surface = dict(variant["surface_summaries"]["tradeable"])
        ranked_variants.append(
            {
                "variant_name": variant["label"],
                "profile_name": variant["profile_name"],
                "profile_overrides": dict(variant.get("profile_overrides") or {}),
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
        "baseline_profile": baseline_profile,
        "baseline": baseline,
        "variants": variants,
        "comparisons": comparisons,
        "ranked_variants": ranked_variants,
        "best_variant": best_variant,
        "next_high_hit_threshold": round(float(next_high_hit_threshold), 4),
        "guardrail_next_high_hit_rate": effective_guardrail_next_high_hit_rate,
        "guardrail_next_close_positive_rate": effective_guardrail_next_close_positive_rate,
    }


def render_btst_score_construction_frontier_markdown(analysis: dict[str, Any]) -> str:
    baseline = dict(analysis["baseline"])
    lines: list[str] = []
    lines.append("# BTST Score Construction Frontier Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- input_path: {analysis['input_path']}")
    lines.append(f"- baseline_profile: {analysis['baseline_profile']}")
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
    lines.append("## Variant Comparison")
    for variant, comparison in zip(analysis["variants"], analysis["comparisons"]):
        lines.append(f"### {variant['label']}")
        lines.append(f"- profile_overrides: {variant['profile_overrides']}")
        lines.append(f"- profile_config: {variant['profile_config']}")
        lines.append(f"- decision_counts: {variant['decision_counts']}")
        lines.append(f"- tradeable_surface: {variant['surface_summaries']['tradeable']}")
        lines.append(f"- false_negative_proxy_summary: {variant['false_negative_proxy_summary']}")
        lines.append(f"- guardrail_status: {comparison['guardrail_status']}")
        lines.append(f"- comparison_note: {comparison['comparison_note']}")
        lines.append(f"- tradeable_surface_delta: {comparison['tradeable_surface_delta']}")
        lines.append(f"- false_negative_proxy_delta: {comparison['false_negative_proxy_delta']}")
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
    parser = argparse.ArgumentParser(description="Compare BTST score-construction variants on a replay window using closed-cycle outcomes.")
    parser.add_argument("input_path", help="Path to a selection_target_replay_input.json file, selection_artifacts directory, or report directory.")
    parser.add_argument("--baseline-profile", default="default", help="Base short-trade profile used for score construction variants.")
    parser.add_argument("--variant", action="append", default=[], help="Named score construction variants to compare. Available: " + ", ".join(sorted(SCORE_CONSTRUCTION_VARIANTS.keys())))
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--guardrail-next-high-hit-rate", type=float, default=None)
    parser.add_argument("--guardrail-next-close-positive-rate", type=float, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analysis = analyze_btst_score_construction_frontier(
        args.input_path,
        baseline_profile=args.baseline_profile,
        variant_names=list(args.variant),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
        guardrail_next_high_hit_rate=args.guardrail_next_high_hit_rate,
        guardrail_next_close_positive_rate=args.guardrail_next_close_positive_rate,
    )
    if args.output_json is not None:
        args.output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md is not None:
        args.output_md.write_text(render_btst_score_construction_frontier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()