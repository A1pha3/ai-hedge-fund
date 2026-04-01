from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_profile_frontier import analyze_btst_profile_replay_window
from scripts.btst_candidate_entry_utils import build_watchlist_avoid_weak_structure_filter


CANDIDATE_ENTRY_VARIANTS: dict[str, dict[str, Any]] = {
    "weak_structure_triplet": {
        "description": "Filter watchlist_avoid boundary samples only when breakout, volume, and catalyst are all near zero.",
        "evidence_tier": "window_verified_selective_rule",
        "stability_priority": 3,
        "structural_overrides": {
            "exclude_candidate_entries": [
                build_watchlist_avoid_weak_structure_filter(
                    breakout_freshness_max=0.05,
                    volume_expansion_quality_max=0.05,
                    catalyst_freshness_max=0.05,
                )
            ]
        },
    },
    "semantic_pair_300502": {
        "description": "Use the 300502 semantic separation pair observed on 2026-03-26: weak trend confirmation plus weak close strength.",
        "evidence_tier": "single_case_semantic_pair",
        "stability_priority": 2,
        "structural_overrides": {
            "exclude_candidate_entries": [
                build_watchlist_avoid_weak_structure_filter(
                    trend_acceleration_max=0.34,
                    close_strength_max=0.69,
                )
            ]
        },
    },
    "volume_only_20260326": {
        "description": "Single-dimension candidate-entry filter based on volume_expansion_quality <= 0.0. This is known to be only a single-day hypothesis.",
        "evidence_tier": "single_day_hypothesis",
        "stability_priority": 1,
        "structural_overrides": {
            "exclude_candidate_entries": [
                build_watchlist_avoid_weak_structure_filter(
                    volume_expansion_quality_max=0.0,
                )
            ]
        },
    },
}


def _parse_variant_names(values: list[str] | None) -> list[str]:
    names: list[str] = []
    for raw in values or []:
        token = str(raw or "").strip()
        if not token:
            continue
        if token not in CANDIDATE_ENTRY_VARIANTS:
            available = ", ".join(sorted(CANDIDATE_ENTRY_VARIANTS))
            raise ValueError(f"Unknown candidate-entry variant: {token}. Available: {available}")
        if token not in names:
            names.append(token)
    return names


def _parse_tickers(values: list[str] | None) -> list[str]:
    tickers: list[str] = []
    for raw in values or []:
        token = str(raw or "").strip()
        if token and token not in tickers:
            tickers.append(token)
    return tickers


def _variant_filter_cost(structural_overrides: dict[str, Any]) -> float:
    filter_rules = list(dict(structural_overrides or {}).get("exclude_candidate_entries") or [])
    cost = 0.0
    for rule in filter_rules:
        for value in dict(rule.get("metric_max_thresholds") or {}).values():
            if value is None:
                continue
            cost += float(value)
    return round(cost, 4)


def _extract_variant_rule_summary(structural_overrides: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for rule in list(dict(structural_overrides or {}).get("exclude_candidate_entries") or []):
        summaries.append(
            {
                "name": str(rule.get("name") or "unnamed_filter"),
                "candidate_sources": [str(value) for value in list(rule.get("candidate_sources") or []) if str(value or "").strip()],
                "all_reason_codes": [str(value) for value in list(rule.get("all_reason_codes") or []) if str(value or "").strip()],
                "metric_max_thresholds": {
                    str(metric): round(float(value), 4)
                    for metric, value in dict(rule.get("metric_max_thresholds") or {}).items()
                    if value is not None
                },
            }
        )
    return summaries


def _extract_ticker_hits(rows: list[dict[str, Any]], tickers: list[str]) -> list[str]:
    ticker_set = {str(ticker) for ticker in tickers if str(ticker or "").strip()}
    if not ticker_set:
        return []
    return sorted({str(row.get("ticker") or "") for row in rows if str(row.get("ticker") or "") in ticker_set})


def _is_filtered_pool_weaker_than_false_negative_pool(filtered_surface: dict[str, Any], baseline_false_negative_surface: dict[str, Any]) -> bool:
    filtered_high = filtered_surface.get("next_high_hit_rate_at_threshold")
    filtered_close = filtered_surface.get("next_close_positive_rate")
    baseline_high = baseline_false_negative_surface.get("next_high_hit_rate_at_threshold")
    baseline_close = baseline_false_negative_surface.get("next_close_positive_rate")
    if filtered_high is None or filtered_close is None or baseline_high is None or baseline_close is None:
        return False
    return float(filtered_high) < float(baseline_high) and float(filtered_close) < float(baseline_close)


def _build_candidate_entry_comparison(
    baseline: dict[str, Any],
    variant: dict[str, Any],
    *,
    focus_tickers: list[str],
    preserve_tickers: list[str],
) -> dict[str, Any]:
    filtered_rows = list(variant.get("filtered_candidate_entry_rows") or [])
    filtered_summary = dict(variant.get("filtered_candidate_entry_summary") or {})
    filtered_surface = dict(filtered_summary.get("surface_metrics") or {})
    baseline_false_negative_surface = dict(baseline.get("false_negative_proxy_summary", {}).get("surface_metrics") or {})
    focus_filtered_tickers = _extract_ticker_hits(filtered_rows, focus_tickers)
    preserve_filtered_tickers = _extract_ticker_hits(filtered_rows, preserve_tickers)
    filtered_count = int(filtered_summary.get("count", 0))
    weaker_pool = _is_filtered_pool_weaker_than_false_negative_pool(filtered_surface, baseline_false_negative_surface)

    if preserve_filtered_tickers:
        status = "filters_preserve_tickers"
        comparison_note = f"{variant['label']} 误伤 preserve_tickers={preserve_filtered_tickers}，说明 candidate-entry 规则过宽。"
    elif filtered_count == 0:
        status = "no_candidate_entries_filtered"
        comparison_note = f"{variant['label']} 没有过滤任何 candidate-entry 样本，当前窗口上没有形成可用分离面。"
    elif focus_tickers and not focus_filtered_tickers:
        status = "misses_focus_tickers"
        comparison_note = f"{variant['label']} 过滤了 {filtered_count} 个样本，但没有命中 focus_tickers={focus_tickers}。"
    elif focus_tickers and weaker_pool:
        status = "filters_focus_and_weaker_than_false_negative_pool"
        comparison_note = f"{variant['label']} 命中 focus_tickers={focus_filtered_tickers}，且 filtered cohort 的 closed-cycle 质量弱于 baseline false-negative pool。"
    elif focus_tickers:
        status = "filters_focus_but_filtered_pool_too_strong"
        comparison_note = f"{variant['label']} 虽然命中 focus_tickers={focus_filtered_tickers}，但 filtered cohort 的后验质量仍偏强，暂不适合直接收紧为默认入口规则。"
    elif weaker_pool:
        status = "filters_weaker_than_false_negative_pool"
        comparison_note = f"{variant['label']} 过滤出的 cohort 质量弱于 baseline false-negative pool，更像 candidate-entry 清洗而不是误伤强样本。"
    else:
        status = "filtered_pool_too_strong"
        comparison_note = f"{variant['label']} 过滤出的 cohort 仍包含较强 closed-cycle 表现，当前不宜直接提升为默认 candidate-entry 规则。"

    return {
        "variant_name": variant["label"],
        "candidate_entry_status": status,
        "comparison_note": comparison_note,
        "filtered_candidate_entry_count": filtered_count,
        "focus_filtered_tickers": focus_filtered_tickers,
        "preserve_filtered_tickers": preserve_filtered_tickers,
        "filtered_candidate_entry_surface": filtered_surface,
        "baseline_false_negative_surface": baseline_false_negative_surface,
        "matched_filter_counts": dict(filtered_summary.get("matched_filter_counts") or {}),
        "candidate_entry_filter_observability": dict(variant.get("candidate_entry_filter_observability") or {}),
    }


def _candidate_entry_status_rank(status: str) -> int:
    ranking = {
        "filters_focus_and_weaker_than_false_negative_pool": 5,
        "filters_weaker_than_false_negative_pool": 4,
        "misses_focus_tickers": 3,
        "no_candidate_entries_filtered": 2,
        "filtered_pool_too_strong": 1,
        "filters_focus_but_filtered_pool_too_strong": 1,
        "filters_preserve_tickers": 0,
    }
    return int(ranking.get(str(status or ""), -1))


def analyze_btst_candidate_entry_frontier(
    input_path: str | Path,
    *,
    baseline_profile: str = "default",
    variant_names: list[str] | None = None,
    focus_tickers: list[str] | None = None,
    preserve_tickers: list[str] | None = None,
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    resolved_variant_names = _parse_variant_names(variant_names) or list(CANDIDATE_ENTRY_VARIANTS)
    focus_ticker_list = _parse_tickers(focus_tickers)
    preserve_ticker_list = _parse_tickers(preserve_tickers)

    baseline = analyze_btst_profile_replay_window(
        input_path,
        profile_name=baseline_profile,
        label="baseline",
        next_high_hit_threshold=next_high_hit_threshold,
    )

    variants: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    ranked_variants: list[dict[str, Any]] = []
    for variant_name in resolved_variant_names:
        variant_definition = dict(CANDIDATE_ENTRY_VARIANTS[variant_name])
        structural_overrides = dict(variant_definition.get("structural_overrides") or {})
        variant = analyze_btst_profile_replay_window(
            input_path,
            profile_name=baseline_profile,
            label=variant_name,
            next_high_hit_threshold=next_high_hit_threshold,
            structural_overrides=structural_overrides,
        )
        variant["variant_description"] = str(variant_definition.get("description") or "")
        variant["variant_evidence_tier"] = str(variant_definition.get("evidence_tier") or "unlabeled")
        variant["variant_stability_priority"] = int(variant_definition.get("stability_priority") or 0)
        variant["variant_filter_cost"] = _variant_filter_cost(structural_overrides)
        variant["variant_filter_rules"] = _extract_variant_rule_summary(structural_overrides)
        variants.append(variant)

        comparison = _build_candidate_entry_comparison(
            baseline,
            variant,
            focus_tickers=focus_ticker_list,
            preserve_tickers=preserve_ticker_list,
        )
        comparisons.append(comparison)
        filtered_surface = dict(comparison.get("filtered_candidate_entry_surface") or {})
        ranked_variants.append(
            {
                "variant_name": variant_name,
                "candidate_entry_status": comparison["candidate_entry_status"],
                "filtered_candidate_entry_count": int(comparison["filtered_candidate_entry_count"]),
                "focus_filtered_tickers": list(comparison["focus_filtered_tickers"]),
                "preserve_filtered_tickers": list(comparison["preserve_filtered_tickers"]),
                "filtered_next_high_hit_rate_at_threshold": filtered_surface.get("next_high_hit_rate_at_threshold"),
                "filtered_next_close_positive_rate": filtered_surface.get("next_close_positive_rate"),
                "evidence_tier": variant["variant_evidence_tier"],
                "stability_priority": int(variant["variant_stability_priority"]),
                "filter_cost": float(variant["variant_filter_cost"]),
                "comparison_note": comparison["comparison_note"],
            }
        )

    best_variant = None
    if ranked_variants:
        best_variant = max(
            ranked_variants,
            key=lambda row: (
                _candidate_entry_status_rank(str(row.get("candidate_entry_status") or "")),
                len(list(row.get("focus_filtered_tickers") or [])),
                -len(list(row.get("preserve_filtered_tickers") or [])),
                -(float(row["filtered_next_close_positive_rate"]) if row.get("filtered_next_close_positive_rate") is not None else 1.0),
                -(float(row["filtered_next_high_hit_rate_at_threshold"]) if row.get("filtered_next_high_hit_rate_at_threshold") is not None else 1.0),
                int(row.get("filtered_candidate_entry_count") or 0),
                int(row.get("stability_priority") or 0),
                -float(row.get("filter_cost") or 0.0),
            ),
        )
        best_variant["selection_basis"] = "candidate_entry_frontier_priority"

    return {
        "input_path": str(Path(input_path).expanduser().resolve()),
        "baseline_profile": baseline_profile,
        "focus_tickers": focus_ticker_list,
        "preserve_tickers": preserve_ticker_list,
        "baseline": baseline,
        "variants": variants,
        "comparisons": comparisons,
        "ranked_variants": ranked_variants,
        "best_variant": best_variant,
        "next_high_hit_threshold": round(float(next_high_hit_threshold), 4),
    }


def render_btst_candidate_entry_frontier_markdown(analysis: dict[str, Any]) -> str:
    baseline = dict(analysis["baseline"])
    lines: list[str] = []
    lines.append("# BTST Candidate Entry Frontier Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- input_path: {analysis['input_path']}")
    lines.append(f"- baseline_profile: {analysis['baseline_profile']}")
    lines.append(f"- trade_dates: {baseline['trade_dates']}")
    lines.append(f"- focus_tickers: {analysis['focus_tickers']}")
    lines.append(f"- preserve_tickers: {analysis['preserve_tickers']}")
    lines.append(f"- next_high_hit_threshold: {analysis['next_high_hit_threshold']}")
    lines.append(f"- best_variant: {analysis['best_variant']}")
    lines.append("")
    lines.append("## Baseline Summary")
    lines.append(f"- profile_config: {baseline['profile_config']}")
    lines.append(f"- decision_counts: {baseline['decision_counts']}")
    lines.append(f"- tradeable_surface: {baseline['surface_summaries']['tradeable']}")
    lines.append(f"- false_negative_proxy_summary: {baseline['false_negative_proxy_summary']}")
    lines.append(f"- filtered_candidate_entry_summary: {baseline['filtered_candidate_entry_summary']}")
    lines.append(f"- recommendation: {baseline['recommendation']}")
    lines.append("")
    lines.append("## Variant Comparison")
    for variant, comparison in zip(analysis["variants"], analysis["comparisons"]):
        lines.append(f"### {variant['label']}")
        lines.append(f"- description: {variant['variant_description']}")
        lines.append(f"- evidence_tier: {variant['variant_evidence_tier']}")
        lines.append(f"- filter_rules: {variant['variant_filter_rules']}")
        lines.append(f"- filter_cost: {variant['variant_filter_cost']}")
        lines.append(f"- filtered_candidate_entry_summary: {variant['filtered_candidate_entry_summary']}")
        lines.append(f"- candidate_entry_filter_observability: {variant['candidate_entry_filter_observability']}")
        lines.append(f"- candidate_entry_status: {comparison['candidate_entry_status']}")
        lines.append(f"- comparison_note: {comparison['comparison_note']}")
        lines.append(f"- focus_filtered_tickers: {comparison['focus_filtered_tickers']}")
        lines.append(f"- preserve_filtered_tickers: {comparison['preserve_filtered_tickers']}")
        lines.append(f"- filtered_candidate_entry_surface: {comparison['filtered_candidate_entry_surface']}")
        lines.append(f"- tradeable_surface: {variant['surface_summaries']['tradeable']}")
        lines.append("")
    lines.append("## Baseline Top False Negatives")
    for row in baseline["top_false_negative_rows"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: decision={row['decision']}, next_high_return={row['next_high_return']}, next_close_return={row['next_close_return']}, score_target={row['score_target']}, reasons={row['false_negative_proxy_reasons']}"
        )
    if not baseline["top_false_negative_rows"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Variant Top Filtered Entries")
    for variant in analysis["variants"]:
        lines.append(f"### {variant['label']}")
        filtered_rows = list(variant.get("top_filtered_candidate_entry_rows") or [])
        if not filtered_rows:
            lines.append("- none")
            continue
        for row in filtered_rows:
            lines.append(
                f"- {row['trade_date']} {row['ticker']}: matched_filter={row['matched_filter']}, next_high_return={row['next_high_return']}, next_close_return={row['next_close_return']}, candidate_source={row['candidate_source']}, metrics={row['metric_snapshot']}"
            )
    lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare BTST candidate-entry variants on a replay window using closed-cycle outcomes.")
    parser.add_argument("input_path", help="Path to a selection_target_replay_input.json file, selection_artifacts directory, or report directory.")
    parser.add_argument("--baseline-profile", default="default", help="Base short-trade profile used for candidate-entry frontier variants.")
    parser.add_argument("--variant", action="append", default=[], help="Named candidate-entry variants to compare. Available: " + ", ".join(sorted(CANDIDATE_ENTRY_VARIANTS.keys())))
    parser.add_argument("--focus-ticker", action="append", default=[], help="Ticker that the frontier is expected to filter if the candidate-entry rule is useful.")
    parser.add_argument("--preserve-ticker", action="append", default=[], help="Ticker that should not be filtered by the candidate-entry rule.")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analysis = analyze_btst_candidate_entry_frontier(
        args.input_path,
        baseline_profile=args.baseline_profile,
        variant_names=list(args.variant),
        focus_tickers=list(args.focus_ticker),
        preserve_tickers=list(args.preserve_ticker),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
    )
    if args.output_json is not None:
        args.output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md is not None:
        args.output_md.write_text(render_btst_candidate_entry_frontier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()