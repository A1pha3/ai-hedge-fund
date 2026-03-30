from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_btst_micro_window_regression import (
    _build_day_breakdown,
    _build_false_negative_proxy_rows,
    _build_surface_summary,
    _compare_reports,
    _extract_btst_price_outcome,
)
from scripts.replay_selection_target_calibration import (
    STRUCTURAL_VARIANTS,
    _apply_candidate_entry_filters,
    _coerce_watchlist_entries,
    _extract_short_trade_snapshot_map,
    _iter_replay_input_sources,
    _override_short_trade_thresholds,
)
from src.targets import SHORT_TRADE_TARGET_PROFILES, build_short_trade_target_profile, get_short_trade_target_profile
from src.targets.router import build_selection_targets


DEFAULT_PROFILE_VARIANTS = ["staged_breakout", "aggressive", "conservative"]
DEFAULT_GUARDRAIL_NEXT_HIGH_HIT_RATE = 0.5217
DEFAULT_GUARDRAIL_NEXT_CLOSE_POSITIVE_RATE = 0.5652


def _serialize_profile(profile: Any) -> dict[str, Any]:
    return {
        "name": profile.name,
        "select_threshold": round(float(profile.select_threshold), 4),
        "near_miss_threshold": round(float(profile.near_miss_threshold), 4),
        "selected_breakout_freshness_min": round(float(profile.selected_breakout_freshness_min), 4),
        "selected_trend_acceleration_min": round(float(profile.selected_trend_acceleration_min), 4),
        "near_miss_breakout_freshness_min": round(float(profile.near_miss_breakout_freshness_min), 4),
        "near_miss_trend_acceleration_min": round(float(profile.near_miss_trend_acceleration_min), 4),
        "breakout_freshness_weight": round(float(profile.breakout_freshness_weight), 4),
        "trend_acceleration_weight": round(float(profile.trend_acceleration_weight), 4),
        "volume_expansion_quality_weight": round(float(profile.volume_expansion_quality_weight), 4),
        "close_strength_weight": round(float(profile.close_strength_weight), 4),
        "sector_resonance_weight": round(float(profile.sector_resonance_weight), 4),
        "catalyst_freshness_weight": round(float(profile.catalyst_freshness_weight), 4),
        "layer_c_alignment_weight": round(float(profile.layer_c_alignment_weight), 4),
        "stale_penalty_block_threshold": round(float(profile.stale_penalty_block_threshold), 4),
        "overhead_penalty_block_threshold": round(float(profile.overhead_penalty_block_threshold), 4),
        "extension_penalty_block_threshold": round(float(profile.extension_penalty_block_threshold), 4),
        "layer_c_avoid_penalty": round(float(profile.layer_c_avoid_penalty), 4),
        "stale_score_penalty_weight": round(float(profile.stale_score_penalty_weight), 4),
        "overhead_score_penalty_weight": round(float(profile.overhead_score_penalty_weight), 4),
        "extension_score_penalty_weight": round(float(profile.extension_score_penalty_weight), 4),
        "hard_block_bearish_conflicts": sorted(str(item) for item in profile.hard_block_bearish_conflicts),
        "overhead_conflict_penalty_conflicts": sorted(str(item) for item in profile.overhead_conflict_penalty_conflicts),
    }


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


def _resolve_guardrail(value: float | None, baseline_value: Any, fallback: float) -> float:
    if value is not None:
        return round(float(value), 4)
    if baseline_value is None:
        return round(float(fallback), 4)
    return round(float(baseline_value), 4)


def analyze_btst_profile_replay_window(
    input_path: str | Path,
    *,
    profile_name: str,
    label: str | None = None,
    next_high_hit_threshold: float = 0.02,
    structural_variant: str = "baseline",
    select_threshold: float | None = None,
    near_miss_threshold: float | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    replay_input_sources = _iter_replay_input_sources(input_path)
    if not replay_input_sources:
        raise FileNotFoundError(f"No replay inputs found under: {input_path}")

    effective_structural_overrides = dict(STRUCTURAL_VARIANTS.get(structural_variant, {}))
    entry_filter_rules = list(effective_structural_overrides.get("exclude_candidate_entries") or [])
    effective_profile_overrides = {
        key: value
        for key, value in {
            **dict(profile_overrides or {}),
            "select_threshold": select_threshold,
            "near_miss_threshold": near_miss_threshold,
        }.items()
        if value is not None
    }
    profile = build_short_trade_target_profile(profile_name, overrides=effective_profile_overrides)

    rows: list[dict[str, Any]] = []
    price_cache: dict[tuple[str, str], Any] = {}
    decision_counts: Counter[str] = Counter()
    candidate_source_counts: Counter[str] = Counter()
    cycle_status_counts: Counter[str] = Counter()
    data_status_counts: Counter[str] = Counter()
    target_modes: Counter[str] = Counter()

    with _override_short_trade_thresholds(
        profile_name=profile_name,
        select_threshold=effective_profile_overrides.get("select_threshold"),
        near_miss_threshold=effective_profile_overrides.get("near_miss_threshold"),
        breakout_freshness_weight=effective_profile_overrides.get("breakout_freshness_weight"),
        trend_acceleration_weight=effective_profile_overrides.get("trend_acceleration_weight"),
        volume_expansion_quality_weight=effective_profile_overrides.get("volume_expansion_quality_weight"),
        close_strength_weight=effective_profile_overrides.get("close_strength_weight"),
        sector_resonance_weight=effective_profile_overrides.get("sector_resonance_weight"),
        catalyst_freshness_weight=effective_profile_overrides.get("catalyst_freshness_weight"),
        layer_c_alignment_weight=effective_profile_overrides.get("layer_c_alignment_weight"),
        stale_penalty_block_threshold=effective_structural_overrides.get("stale_penalty_block_threshold"),
        overhead_penalty_block_threshold=effective_structural_overrides.get("overhead_penalty_block_threshold"),
        extension_penalty_block_threshold=effective_structural_overrides.get("extension_penalty_block_threshold"),
        layer_c_avoid_penalty=effective_structural_overrides.get("layer_c_avoid_penalty"),
        strong_bearish_conflicts=effective_structural_overrides.get("strong_bearish_conflicts"),
        stale_score_penalty_weight=effective_structural_overrides.get("stale_score_penalty_weight"),
        overhead_score_penalty_weight=effective_structural_overrides.get("overhead_score_penalty_weight"),
        extension_score_penalty_weight=effective_structural_overrides.get("extension_score_penalty_weight"),
    ):
        for replay_input_path, payload in replay_input_sources:
            trade_date = str(payload.get("trade_date") or "")
            target_mode = str(payload.get("target_mode") or "research_only")
            target_modes[target_mode] += 1
            rejected_entries, _ = _apply_candidate_entry_filters(
                list(payload.get("rejected_entries") or []),
                entry_filter_rules,
                trade_date=trade_date,
                default_candidate_source="watchlist_filter_diagnostics",
            )
            supplemental_entries, _ = _apply_candidate_entry_filters(
                list(payload.get("supplemental_short_trade_entries") or []),
                entry_filter_rules,
                trade_date=trade_date,
                default_candidate_source="layer_b_boundary",
            )
            watchlist = _coerce_watchlist_entries(list(payload.get("watchlist") or []))
            buy_order_tickers = {str(ticker) for ticker in list(payload.get("buy_order_tickers") or []) if str(ticker or "").strip()}
            replayed_targets, _ = build_selection_targets(
                trade_date=trade_date.replace("-", ""),
                watchlist=watchlist,
                rejected_entries=rejected_entries,
                supplemental_short_trade_entries=supplemental_entries,
                buy_order_tickers=buy_order_tickers,
                target_mode=target_mode,
            )
            replayed_snapshots = _extract_short_trade_snapshot_map(replayed_targets)
            stored_targets = dict(payload.get("selection_targets") or {})

            for ticker, replayed_snapshot in replayed_snapshots.items():
                if not replayed_snapshot:
                    continue
                stored_evaluation = dict(stored_targets.get(ticker) or {})
                stored_short_trade = dict(stored_evaluation.get("short_trade") or {})
                price_outcome = _extract_btst_price_outcome(str(ticker), trade_date, price_cache)
                candidate_source = str(
                    stored_evaluation.get("candidate_source")
                    or dict(replayed_snapshot.get("explainability_payload") or {}).get("candidate_source")
                    or "unknown"
                )
                row = {
                    "report_label": label or profile_name,
                    "profile_name": profile_name,
                    "trade_date": trade_date,
                    "ticker": str(ticker),
                    "stored_decision": stored_short_trade.get("decision"),
                    "decision": replayed_snapshot.get("decision"),
                    "score_target": replayed_snapshot.get("score_target"),
                    "candidate_source": candidate_source,
                    "candidate_reason_codes": list(stored_evaluation.get("candidate_reason_codes") or []),
                    "delta_classification": stored_evaluation.get("delta_classification"),
                    "blockers": list(replayed_snapshot.get("blockers") or []),
                    "gate_status": dict(replayed_snapshot.get("gate_status") or {}),
                    "metrics_payload": dict(replayed_snapshot.get("metrics_payload") or {}),
                    "explainability_payload": dict(replayed_snapshot.get("explainability_payload") or {}),
                    "target_mode": target_mode,
                    "replay_input_path": str(replay_input_path),
                    **price_outcome,
                }
                rows.append(row)
                decision_counts[str(row.get("decision") or "unknown")] += 1
                candidate_source_counts[candidate_source] += 1
                cycle_status_counts[str(row.get("cycle_status") or "unknown")] += 1
                data_status_counts[str(row.get("data_status") or "unknown")] += 1

    rows.sort(key=lambda row: (str(row.get("trade_date") or ""), str(row.get("ticker") or "")))
    actionable_rows = [row for row in rows if row.get("decision") in {"selected", "near_miss"}]
    selected_rows = [row for row in rows if row.get("decision") == "selected"]
    near_miss_rows = [row for row in rows if row.get("decision") == "near_miss"]
    blocked_rows = [row for row in rows if row.get("decision") == "blocked"]
    rejected_rows = [row for row in rows if row.get("decision") == "rejected"]
    false_negative_rows = _build_false_negative_proxy_rows(rows, next_high_hit_threshold=next_high_hit_threshold)

    top_tradeable_rows = sorted(
        actionable_rows,
        key=lambda row: (
            1 if row.get("decision") == "selected" else 0,
            float(row.get("score_target") or -999.0),
            float(row.get("next_high_return") or -999.0),
        ),
        reverse=True,
    )[:8]

    if actionable_rows:
        recommendation = f"{profile_name} 已形成可研究的 actionable surface，下一步优先检查其 closed-cycle 质量是否优于 baseline false negative proxy。"
    elif false_negative_rows:
        recommendation = f"{profile_name} 仍未形成 actionable surface，但 false negative proxy 仍存在，说明还需要继续优化 score frontier 或 profile 语义。"
    else:
        recommendation = f"{profile_name} 既没有 actionable surface，也没有可用 false negative proxy，先检查样本窗口与 replay 输入质量。"

    false_negative_source_counts: Counter[str] = Counter(str(row.get("candidate_source") or "unknown") for row in false_negative_rows)
    false_negative_decision_counts: Counter[str] = Counter(str(row.get("decision") or "unknown") for row in false_negative_rows)

    return {
        "label": label or profile_name,
        "profile_name": profile_name,
        "profile_config": _serialize_profile(profile),
        "profile_overrides": effective_profile_overrides,
        "input_path": str(Path(input_path).expanduser().resolve()),
        "target_mode": target_modes.most_common(1)[0][0] if target_modes else "unknown",
        "trade_dates": sorted({str(row.get("trade_date") or "") for row in rows}),
        "row_count": len(rows),
        "decision_counts": dict(decision_counts),
        "candidate_source_counts": dict(candidate_source_counts),
        "cycle_status_counts": dict(cycle_status_counts),
        "data_status_counts": dict(data_status_counts),
        "surface_summaries": {
            "all": _build_surface_summary(rows, next_high_hit_threshold=next_high_hit_threshold),
            "tradeable": _build_surface_summary(actionable_rows, next_high_hit_threshold=next_high_hit_threshold),
            "selected": _build_surface_summary(selected_rows, next_high_hit_threshold=next_high_hit_threshold),
            "near_miss": _build_surface_summary(near_miss_rows, next_high_hit_threshold=next_high_hit_threshold),
            "blocked": _build_surface_summary(blocked_rows, next_high_hit_threshold=next_high_hit_threshold),
            "rejected": _build_surface_summary(rejected_rows, next_high_hit_threshold=next_high_hit_threshold),
        },
        "false_negative_proxy_summary": {
            "count": len(false_negative_rows),
            "candidate_source_counts": dict(false_negative_source_counts),
            "decision_counts": dict(false_negative_decision_counts),
            "surface_metrics": _build_surface_summary(false_negative_rows, next_high_hit_threshold=next_high_hit_threshold),
        },
        "top_tradeable_rows": top_tradeable_rows,
        "top_false_negative_rows": false_negative_rows[:8],
        "day_breakdown": _build_day_breakdown(rows),
        "recommendation": recommendation,
        "rows": rows,
    }


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