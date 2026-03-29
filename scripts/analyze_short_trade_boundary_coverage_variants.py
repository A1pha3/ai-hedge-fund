from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from scripts.short_trade_boundary_analysis_utils import (
    classify_boundary_candidate,
    collect_candidate_rows,
    default_boundary_thresholds,
    parse_candidate_sources,
    parse_float_grid,
    summarize,
)


def _build_variant_name(thresholds: dict[str, float]) -> str:
    return (
        f"candidate_{thresholds['candidate_score_min']:.2f}_"
        f"breakout_{thresholds['breakout_freshness_min']:.2f}_"
        f"trend_{thresholds['trend_acceleration_min']:.2f}_"
        f"volume_{thresholds['volume_expansion_quality_min']:.2f}_"
        f"catalyst_{thresholds['catalyst_freshness_min']:.2f}"
    )


def _summarize_variant_rows(rows: list[dict[str, Any]], next_high_hit_threshold: float) -> dict[str, Any]:
    ok_rows = [row for row in rows if row.get("data_status") == "ok"]
    next_high_returns = [float(row["next_high_return"]) for row in ok_rows]
    next_close_returns = [float(row["next_close_return"]) for row in ok_rows]
    next_high_hits = sum(1 for value in next_high_returns if value >= next_high_hit_threshold)
    next_close_positive = sum(1 for value in next_close_returns if value > 0)
    return {
        "selected_candidate_count": len(rows),
        "ok_outcome_count": len(ok_rows),
        "next_high_return_distribution": summarize(next_high_returns),
        "next_close_return_distribution": summarize(next_close_returns),
        "next_high_hit_rate_at_threshold": None if not ok_rows else round(next_high_hits / len(ok_rows), 4),
        "next_close_positive_rate": None if not ok_rows else round(next_close_positive / len(ok_rows), 4),
    }


def _pick_recommended_variant(variants: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not variants:
        return None
    baseline = next((variant for variant in variants if variant.get("is_baseline")), variants[0])
    baseline_count = int(baseline.get("selected_candidate_count") or 0)
    baseline_close_rate = baseline.get("next_close_positive_rate")
    baseline_high_rate = baseline.get("next_high_hit_rate_at_threshold")
    baseline_close_mean = dict(baseline.get("next_close_return_distribution") or {}).get("mean")

    if baseline_count == 0:
        quality_first = [
            variant
            for variant in variants
            if int(variant.get("selected_candidate_count") or 0) > 0
            and float(variant.get("next_close_positive_rate") or 0.0) >= 0.6
            and float(variant.get("next_high_hit_rate_at_threshold") or 0.0) >= 0.6
            and float(dict(variant.get("next_close_return_distribution") or {}).get("mean") or -999.0) >= 0.0
        ]
        if quality_first:
            quality_first.sort(
                key=lambda variant: (
                    int(variant.get("selected_candidate_count") or 0),
                    float(variant.get("next_close_positive_rate") or -1.0),
                    float(variant.get("next_high_hit_rate_at_threshold") or -1.0),
                    float(dict(variant.get("next_close_return_distribution") or {}).get("mean") or -999.0),
                    -float(variant.get("threshold_relaxation_cost") or 0.0),
                ),
                reverse=True,
            )
            return quality_first[0]

        fallback_positive = [variant for variant in variants if int(variant.get("selected_candidate_count") or 0) > 0]
        if fallback_positive:
            fallback_positive.sort(
                key=lambda variant: (
                    float(variant.get("next_close_positive_rate") or -1.0),
                    float(variant.get("next_high_hit_rate_at_threshold") or -1.0),
                    float(dict(variant.get("next_close_return_distribution") or {}).get("mean") or -999.0),
                    int(variant.get("selected_candidate_count") or 0),
                    -float(variant.get("threshold_relaxation_cost") or 0.0),
                ),
                reverse=True,
            )
            return fallback_positive[0]

    eligible: list[dict[str, Any]] = []
    for variant in variants:
        if variant is baseline:
            continue
        if int(variant.get("selected_candidate_count") or 0) <= baseline_count:
            continue
        close_rate = variant.get("next_close_positive_rate")
        high_rate = variant.get("next_high_hit_rate_at_threshold")
        close_mean = dict(variant.get("next_close_return_distribution") or {}).get("mean")
        if baseline_close_rate is not None and close_rate is not None and close_rate < baseline_close_rate - 0.10:
            continue
        if baseline_high_rate is not None and high_rate is not None and high_rate < baseline_high_rate - 0.15:
            continue
        if baseline_close_mean is not None and close_mean is not None and close_mean < baseline_close_mean - 0.02:
            continue
        eligible.append(variant)

    if not eligible:
        return baseline
    eligible.sort(
        key=lambda variant: (
            int(variant.get("selected_candidate_count") or 0),
            -float(variant.get("threshold_relaxation_cost") or 0.0),
            float(variant.get("next_close_positive_rate") or -1.0),
            float(dict(variant.get("next_close_return_distribution") or {}).get("mean") or -999.0),
        ),
        reverse=True,
    )
    return eligible[0]


def render_short_trade_boundary_coverage_variants_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Short Trade Boundary Coverage Variant Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- candidate_sources_filter: {analysis['candidate_sources_filter']}")
    lines.append(f"- candidate_pool_count: {analysis['candidate_pool_count']}")
    lines.append(f"- data_status_counts: {analysis['data_status_counts']}")
    lines.append(f"- candidate_source_counts: {analysis['candidate_source_counts']}")
    lines.append(f"- max_candidates_per_trade_date: {analysis['max_candidates_per_trade_date']}")
    lines.append("")
    lines.append("## Baseline")
    lines.append(f"- baseline_variant: {analysis['baseline_variant']['variant_name']}")
    lines.append(f"- baseline_selected_candidate_count: {analysis['baseline_variant']['selected_candidate_count']}")
    lines.append(f"- baseline_next_high_hit_rate_at_threshold: {analysis['baseline_variant']['next_high_hit_rate_at_threshold']}")
    lines.append(f"- baseline_next_close_positive_rate: {analysis['baseline_variant']['next_close_positive_rate']}")
    lines.append("")
    lines.append("## Recommended Variant")
    recommended = analysis.get("recommended_variant") or {}
    lines.append(f"- variant_name: {recommended.get('variant_name')}")
    lines.append(f"- thresholds: {recommended.get('thresholds')}")
    lines.append(f"- selected_candidate_count: {recommended.get('selected_candidate_count')}")
    lines.append(f"- next_high_return_distribution: {recommended.get('next_high_return_distribution')}")
    lines.append(f"- next_close_return_distribution: {recommended.get('next_close_return_distribution')}")
    lines.append(f"- next_high_hit_rate_at_threshold: {recommended.get('next_high_hit_rate_at_threshold')}")
    lines.append(f"- next_close_positive_rate: {recommended.get('next_close_positive_rate')}")
    lines.append("")
    lines.append("## Variant Ranking")
    for variant in analysis["variants"][:10]:
        lines.append(
            f"- {variant['variant_name']}: selected={variant['selected_candidate_count']}, qualified_pool={variant['qualified_pool_count']}, close_mean={dict(variant['next_close_return_distribution']).get('mean')}, close_positive_rate={variant['next_close_positive_rate']}, high_hit_rate={variant['next_high_hit_rate_at_threshold']}, filtered_reason_counts={variant['filtered_reason_counts']}"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_short_trade_boundary_coverage_variants(
    report_dir: str | Path,
    *,
    candidate_sources: set[str] | None = None,
    candidate_score_min_grid: list[float] | None = None,
    breakout_min_grid: list[float] | None = None,
    trend_min_grid: list[float] | None = None,
    volume_min_grid: list[float] | None = None,
    catalyst_min_grid: list[float] | None = None,
    max_candidates_per_trade_date: int = 6,
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    candidate_payload = collect_candidate_rows(
        report_dir,
        candidate_sources=candidate_sources,
        next_high_hit_threshold=next_high_hit_threshold,
    )
    candidate_rows = list(candidate_payload["rows"])
    default_thresholds = default_boundary_thresholds()
    variants: list[dict[str, Any]] = []

    candidate_score_values = candidate_score_min_grid or [default_thresholds["candidate_score_min"]]
    breakout_values = breakout_min_grid or [default_thresholds["breakout_freshness_min"]]
    trend_values = trend_min_grid or [default_thresholds["trend_acceleration_min"]]
    volume_values = volume_min_grid or [default_thresholds["volume_expansion_quality_min"]]
    catalyst_values = catalyst_min_grid or [default_thresholds["catalyst_freshness_min"]]

    for candidate_score_min, breakout_min, trend_min, volume_min, catalyst_min in itertools.product(
        candidate_score_values,
        breakout_values,
        trend_values,
        volume_values,
        catalyst_values,
    ):
        thresholds = {
            "candidate_score_min": round(float(candidate_score_min), 4),
            "breakout_freshness_min": round(float(breakout_min), 4),
            "trend_acceleration_min": round(float(trend_min), 4),
            "volume_expansion_quality_min": round(float(volume_min), 4),
            "catalyst_freshness_min": round(float(catalyst_min), 4),
        }
        qualified_by_trade_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        filtered_reason_counts: Counter[str] = Counter()

        for row in candidate_rows:
            classification = classify_boundary_candidate(row, thresholds)
            if not classification["qualified"]:
                filtered_reason_counts[str(classification["primary_reason"])] += 1
                continue
            qualified_by_trade_date[str(row.get("trade_date") or "")].append({**row, **classification})

        selected_rows: list[dict[str, Any]] = []
        selected_candidate_count_by_trade_date: dict[str, int] = {}
        for trade_date, rows in sorted(qualified_by_trade_date.items()):
            ranked_rows = sorted(rows, key=lambda row: (float(row.get("candidate_score") or 0.0), float(row.get("score_b") or 0.0), str(row.get("ticker") or "")), reverse=True)
            chosen_rows = ranked_rows[:max_candidates_per_trade_date]
            selected_candidate_count_by_trade_date[trade_date] = len(chosen_rows)
            selected_rows.extend(chosen_rows)

        variant_summary = _summarize_variant_rows(selected_rows, next_high_hit_threshold)
        threshold_relaxation_cost = round(
            max(0.0, default_thresholds["candidate_score_min"] - thresholds["candidate_score_min"])
            + max(0.0, default_thresholds["breakout_freshness_min"] - thresholds["breakout_freshness_min"])
            + max(0.0, default_thresholds["trend_acceleration_min"] - thresholds["trend_acceleration_min"])
            + max(0.0, default_thresholds["volume_expansion_quality_min"] - thresholds["volume_expansion_quality_min"])
            + max(0.0, default_thresholds["catalyst_freshness_min"] - thresholds["catalyst_freshness_min"]),
            4,
        )
        variants.append(
            {
                "variant_name": _build_variant_name(thresholds),
                "thresholds": thresholds,
                "is_baseline": thresholds == default_thresholds,
                "qualified_pool_count": sum(len(rows) for rows in qualified_by_trade_date.values()),
                "selected_candidate_count_by_trade_date": selected_candidate_count_by_trade_date,
                "filtered_reason_counts": dict(filtered_reason_counts.most_common()),
                "threshold_relaxation_cost": threshold_relaxation_cost,
                "top_selected_rows": sorted(selected_rows, key=lambda row: float(row.get("next_high_return") or -999.0), reverse=True)[:8],
                **variant_summary,
            }
        )

    variants.sort(
        key=lambda variant: (
            int(variant.get("selected_candidate_count") or 0),
            float(variant.get("next_close_positive_rate") or -1.0),
            float(dict(variant.get("next_close_return_distribution") or {}).get("mean") or -999.0),
            -float(variant.get("threshold_relaxation_cost") or 0.0),
        ),
        reverse=True,
    )
    baseline_variant = next((variant for variant in variants if variant.get("is_baseline")), variants[0] if variants else None)
    recommended_variant = _pick_recommended_variant(variants)
    if baseline_variant and recommended_variant:
        recommendation = (
            f"在当前候选池上，baseline 可留下 {baseline_variant['selected_candidate_count']} 个样本；"
            f"推荐变体 {recommended_variant['variant_name']} 可留下 {recommended_variant['selected_candidate_count']} 个样本，"
            f"next_close_positive_rate={recommended_variant['next_close_positive_rate']}，"
            f"next_high_hit_rate@{round(next_high_hit_threshold, 4)}={recommended_variant['next_high_hit_rate_at_threshold']}。"
        )
    else:
        recommendation = "当前报告里没有可分析的 short-trade supplemental candidates。"

    return {
        "report_dir": candidate_payload["report_dir"],
        "candidate_sources_filter": candidate_payload["candidate_sources_filter"],
        "candidate_pool_count": len(candidate_rows),
        "data_status_counts": candidate_payload["data_status_counts"],
        "candidate_source_counts": candidate_payload["candidate_source_counts"],
        "max_candidates_per_trade_date": int(max_candidates_per_trade_date),
        "next_high_hit_threshold": round(float(next_high_hit_threshold), 4),
        "baseline_variant": baseline_variant,
        "recommended_variant": recommended_variant,
        "variants": variants,
        "recommendation": recommendation,
    }


def main() -> None:
    defaults = default_boundary_thresholds()
    parser = argparse.ArgumentParser(description="Analyze short-trade boundary coverage expansion variants on pre-Layer C candidates.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--candidate-sources", default="layer_b_boundary")
    parser.add_argument("--candidate-score-min-grid", default=f"{defaults['candidate_score_min']},0.22,0.20")
    parser.add_argument("--breakout-min-grid", default=f"{defaults['breakout_freshness_min']},0.16,0.14,0.12,0.10")
    parser.add_argument("--trend-min-grid", default=f"{defaults['trend_acceleration_min']},0.20,0.18")
    parser.add_argument("--volume-min-grid", default=f"{defaults['volume_expansion_quality_min']},0.12,0.10")
    parser.add_argument("--catalyst-min-grid", default=f"{defaults['catalyst_freshness_min']},0.10,0.08")
    parser.add_argument("--max-candidates-per-trade-date", type=int, default=6)
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_short_trade_boundary_coverage_variants(
        args.report_dir,
        candidate_sources=parse_candidate_sources(args.candidate_sources),
        candidate_score_min_grid=parse_float_grid(args.candidate_score_min_grid, default=defaults["candidate_score_min"]),
        breakout_min_grid=parse_float_grid(args.breakout_min_grid, default=defaults["breakout_freshness_min"]),
        trend_min_grid=parse_float_grid(args.trend_min_grid, default=defaults["trend_acceleration_min"]),
        volume_min_grid=parse_float_grid(args.volume_min_grid, default=defaults["volume_expansion_quality_min"]),
        catalyst_min_grid=parse_float_grid(args.catalyst_min_grid, default=defaults["catalyst_freshness_min"]),
        max_candidates_per_trade_date=int(args.max_candidates_per_trade_date),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_boundary_coverage_variants_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()