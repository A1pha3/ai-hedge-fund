from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_btst_micro_window_regression import _compare_reports
from scripts.analyze_btst_profile_frontier import (
    DEFAULT_GUARDRAIL_NEXT_CLOSE_POSITIVE_RATE,
    DEFAULT_GUARDRAIL_NEXT_HIGH_HIT_RATE,
    _resolve_guardrail,
    analyze_btst_profile_replay_window,
)
from src.targets import get_short_trade_target_profile


DEFAULT_NEAR_MISS_THRESHOLD_GRID = [0.46, 0.44, 0.42]
DEFAULT_LAYER_C_AVOID_PENALTY_GRID: list[float] = []
DEFAULT_STALE_WEIGHT_GRID = [0.12, 0.10, 0.08, 0.06]
DEFAULT_EXTENSION_WEIGHT_GRID = [0.08, 0.06, 0.04, 0.02]


def _parse_float_grid(raw: str | None) -> list[float]:
    values: list[float] = []
    for token in str(raw or "").split(","):
        normalized = token.strip()
        if not normalized:
            continue
        values.append(float(normalized))
    return values


def _round(value: float) -> float:
    return round(float(value), 4)


def _unique_preserve_order(values: list[float]) -> list[float]:
    ordered: list[float] = []
    for value in values:
        normalized = _round(value)
        if normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _adjustment_cost(
    *,
    default_near_miss_threshold: float,
    default_layer_c_avoid_penalty: float,
    default_stale_weight: float,
    default_extension_weight: float,
    near_miss_threshold: float,
    layer_c_avoid_penalty: float,
    stale_weight: float,
    extension_weight: float,
) -> float:
    return _round(
        max(0.0, default_near_miss_threshold - near_miss_threshold)
        + max(0.0, default_layer_c_avoid_penalty - layer_c_avoid_penalty)
        + max(0.0, default_stale_weight - stale_weight)
        + max(0.0, default_extension_weight - extension_weight)
    )


def _variant_family(
    *,
    default_near_miss_threshold: float,
    default_layer_c_avoid_penalty: float,
    default_stale_weight: float,
    default_extension_weight: float,
    near_miss_threshold: float,
    layer_c_avoid_penalty: float,
    stale_weight: float,
    extension_weight: float,
) -> str:
    threshold_relief = _round(near_miss_threshold) < _round(default_near_miss_threshold)
    penalty_relief = (
        _round(layer_c_avoid_penalty) < _round(default_layer_c_avoid_penalty)
        or _round(stale_weight) < _round(default_stale_weight)
        or _round(extension_weight) < _round(default_extension_weight)
    )
    if threshold_relief and not penalty_relief:
        return "threshold_only"
    if penalty_relief:
        return "penalty_coupled"
    return "baseline_equivalent"


def _build_variant_name(
    *,
    near_miss_threshold: float,
    layer_c_avoid_penalty: float,
    stale_weight: float,
    extension_weight: float,
) -> str:
    return (
        f"nm_{_round(near_miss_threshold):.2f}"
        f"__avoid_{_round(layer_c_avoid_penalty):.2f}"
        f"__stale_{_round(stale_weight):.2f}"
        f"__ext_{_round(extension_weight):.2f}"
    )


def _sort_variant_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        1 if row["guardrail_status"] == "passes_closed_tradeable_guardrails" else 0,
        int(row["closed_cycle_tradeable_count"]),
        int(row["tradeable_count"]),
        -float(row["adjustment_cost"]),
        float(row["next_close_positive_rate"] if row["next_close_positive_rate"] is not None else -1.0),
        float(row["next_high_hit_rate_at_threshold"] if row["next_high_hit_rate_at_threshold"] is not None else -1.0),
    )


def _minimal_passing_variant_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        float(row["adjustment_cost"]),
        -int(row["closed_cycle_tradeable_count"]),
        -int(row["tradeable_count"]),
        -float(row["next_close_positive_rate"] if row["next_close_positive_rate"] is not None else -1.0),
        -float(row["next_high_hit_rate_at_threshold"] if row["next_high_hit_rate_at_threshold"] is not None else -1.0),
    )


def _variant_tradeable_cases(report: dict[str, Any], *, focus_ticker_set: set[str]) -> tuple[list[str], list[str]]:
    tradeable_cases: list[str] = []
    focus_tradeable_cases: list[str] = []
    for row in list(report.get("rows") or []):
        decision = str(row.get("decision") or "")
        if decision not in {"selected", "near_miss"}:
            continue
        case_key = f"{row.get('trade_date')}:{row.get('ticker')}:{decision}"
        tradeable_cases.append(case_key)
        if str(row.get("ticker") or "") in focus_ticker_set:
            focus_tradeable_cases.append(case_key)
    return tradeable_cases, focus_tradeable_cases


def _build_recommendation(
    *,
    passing_variants: list[dict[str, Any]],
    minimal_passing_variant: dict[str, Any] | None,
) -> str:
    if not passing_variants:
        return (
            "当前窗口在给定 near_miss/stale/extension 扫描空间内仍然没有形成通过 closed-tradeable guardrail 的 penalty frontier。"
            " 这说明 stale/extension 放松暂时还不能作为 broad rollout 杠杆，后续仍应维持 300383 单票 shadow 与 recurring lane 的分层治理。"
        )

    passing_family_counts = Counter(str(row.get("variant_family") or "unknown") for row in passing_variants)
    if minimal_passing_variant is None:
        return "当前 penalty frontier 已出现 passing variant，但仍缺少最小 passing row，请优先检查排序逻辑。"
    if passing_family_counts.get("threshold_only", 0) == len(passing_variants):
        return (
            f"当前所有通过 guardrail 的 release 仍停留在 threshold-only lane，最小 passing row 为 {minimal_passing_variant['variant_name']}。"
            " 说明 broad penalty relief 不是当前窗口的必要条件，继续维持低污染单票 shadow 更稳妥。"
        )
    if passing_family_counts.get("threshold_only", 0) == 0:
        return (
            f"当前能通过 guardrail 的 row 全部属于 penalty-coupled lane，最小 passing row 为 {minimal_passing_variant['variant_name']}。"
            " 说明若要继续释放当前窗口的 score frontier，必须接受 stale/extension 联动放松；但在新增独立窗口前，它仍只适合 shadow/research，不适合默认 rollout。"
        )
    return (
        f"当前窗口同时存在 threshold-only 与 penalty-coupled passing rows，但最小成本解仍是 {minimal_passing_variant['variant_name']}。"
        " 因此 broad penalty relief 仍不该直接并入默认主线，应继续把 threshold-only 与 recurring penalty lane 分开治理。"
    )


def analyze_btst_penalty_frontier(
    input_path: str | Path,
    *,
    baseline_profile: str = "default",
    near_miss_threshold_grid: list[float] | None = None,
    layer_c_avoid_penalty_grid: list[float] | None = None,
    stale_weight_grid: list[float] | None = None,
    extension_weight_grid: list[float] | None = None,
    next_high_hit_threshold: float = 0.02,
    guardrail_next_high_hit_rate: float | None = None,
    guardrail_next_close_positive_rate: float | None = None,
    focus_tickers: list[str] | None = None,
) -> dict[str, Any]:
    profile = get_short_trade_target_profile(baseline_profile)
    default_near_miss_threshold = float(profile.near_miss_threshold)
    default_layer_c_avoid_penalty = float(profile.layer_c_avoid_penalty)
    default_stale_weight = float(profile.stale_score_penalty_weight)
    default_extension_weight = float(profile.extension_score_penalty_weight)

    near_miss_values = _unique_preserve_order(near_miss_threshold_grid or DEFAULT_NEAR_MISS_THRESHOLD_GRID)
    layer_c_avoid_penalty_values = _unique_preserve_order(layer_c_avoid_penalty_grid or DEFAULT_LAYER_C_AVOID_PENALTY_GRID or [default_layer_c_avoid_penalty])
    stale_values = _unique_preserve_order(stale_weight_grid or DEFAULT_STALE_WEIGHT_GRID)
    extension_values = _unique_preserve_order(extension_weight_grid or DEFAULT_EXTENSION_WEIGHT_GRID)
    focus_ticker_set = {str(ticker).strip() for ticker in (focus_tickers or []) if str(ticker or "").strip()}

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

    variants: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    ranked_variants: list[dict[str, Any]] = []
    passing_case_frequency: Counter[str] = Counter()

    for near_miss_threshold in near_miss_values:
        for layer_c_avoid_penalty in layer_c_avoid_penalty_values:
            for stale_weight in stale_values:
                for extension_weight in extension_values:
                    if (
                        _round(near_miss_threshold) == _round(default_near_miss_threshold)
                        and _round(layer_c_avoid_penalty) == _round(default_layer_c_avoid_penalty)
                        and _round(stale_weight) == _round(default_stale_weight)
                        and _round(extension_weight) == _round(default_extension_weight)
                    ):
                        continue

                    variant_name = _build_variant_name(
                        near_miss_threshold=near_miss_threshold,
                        layer_c_avoid_penalty=layer_c_avoid_penalty,
                        stale_weight=stale_weight,
                        extension_weight=extension_weight,
                    )
                    variant = analyze_btst_profile_replay_window(
                        input_path,
                        profile_name=baseline_profile,
                        label=variant_name,
                        next_high_hit_threshold=next_high_hit_threshold,
                        near_miss_threshold=near_miss_threshold,
                        structural_overrides={
                            "layer_c_avoid_penalty": float(layer_c_avoid_penalty),
                            "stale_score_penalty_weight": float(stale_weight),
                            "extension_score_penalty_weight": float(extension_weight),
                        },
                    )
                    comparison = _compare_reports(
                        baseline,
                        variant,
                        guardrail_next_high_hit_rate=effective_guardrail_next_high_hit_rate,
                        guardrail_next_close_positive_rate=effective_guardrail_next_close_positive_rate,
                    )
                    tradeable_surface = dict(variant["surface_summaries"]["tradeable"])
                    tradeable_cases, focus_tradeable_cases = _variant_tradeable_cases(variant, focus_ticker_set=focus_ticker_set)
                    ranked_row = {
                        "variant_name": variant_name,
                        "variant_family": _variant_family(
                            default_near_miss_threshold=default_near_miss_threshold,
                            default_layer_c_avoid_penalty=default_layer_c_avoid_penalty,
                            default_stale_weight=default_stale_weight,
                            default_extension_weight=default_extension_weight,
                            near_miss_threshold=near_miss_threshold,
                            layer_c_avoid_penalty=layer_c_avoid_penalty,
                            stale_weight=stale_weight,
                            extension_weight=extension_weight,
                        ),
                        "profile_name": variant["profile_name"],
                        "near_miss_threshold": _round(near_miss_threshold),
                        "layer_c_avoid_penalty": _round(layer_c_avoid_penalty),
                        "stale_score_penalty_weight": _round(stale_weight),
                        "extension_score_penalty_weight": _round(extension_weight),
                        "adjustment_cost": _adjustment_cost(
                            default_near_miss_threshold=default_near_miss_threshold,
                            default_layer_c_avoid_penalty=default_layer_c_avoid_penalty,
                            default_stale_weight=default_stale_weight,
                            default_extension_weight=default_extension_weight,
                            near_miss_threshold=near_miss_threshold,
                            layer_c_avoid_penalty=layer_c_avoid_penalty,
                            stale_weight=stale_weight,
                            extension_weight=extension_weight,
                        ),
                        "guardrail_status": comparison["guardrail_status"],
                        "closed_cycle_tradeable_count": int(tradeable_surface.get("closed_cycle_count", 0)),
                        "tradeable_count": int(tradeable_surface.get("total_count", 0)),
                        "next_high_hit_rate_at_threshold": tradeable_surface.get("next_high_hit_rate_at_threshold"),
                        "next_close_positive_rate": tradeable_surface.get("next_close_positive_rate"),
                        "t_plus_2_close_positive_rate": tradeable_surface.get("t_plus_2_close_positive_rate"),
                        "comparison_note": comparison["comparison_note"],
                        "tradeable_cases": tradeable_cases,
                        "focus_tradeable_cases": focus_tradeable_cases,
                    }
                    variants.append(variant)
                    comparisons.append(comparison)
                    ranked_variants.append(ranked_row)
                    if ranked_row["guardrail_status"] == "passes_closed_tradeable_guardrails":
                        passing_case_frequency.update(case_key.rsplit(":", 1)[0] for case_key in tradeable_cases)

    ranked_variants.sort(key=_sort_variant_key, reverse=True)
    passing_variants = [row for row in ranked_variants if row["guardrail_status"] == "passes_closed_tradeable_guardrails"]
    best_variant = ranked_variants[0] if ranked_variants else None
    if best_variant is not None:
        best_variant = dict(best_variant)
        best_variant["selection_basis"] = "guardrail_passing_frontier" if passing_variants else "fallback_highest_tradeable_surface"
    minimal_passing_variant = min(passing_variants, key=_minimal_passing_variant_key) if passing_variants else None

    return {
        "input_path": str(Path(input_path).expanduser().resolve()),
        "baseline_profile": baseline_profile,
        "baseline": baseline,
        "variants": variants,
        "comparisons": comparisons,
        "ranked_variants": ranked_variants,
        "best_variant": best_variant,
        "minimal_passing_variant": minimal_passing_variant,
        "near_miss_threshold_grid": near_miss_values,
        "layer_c_avoid_penalty_grid": layer_c_avoid_penalty_values,
        "stale_weight_grid": stale_values,
        "extension_weight_grid": extension_values,
        "next_high_hit_threshold": _round(next_high_hit_threshold),
        "guardrail_next_high_hit_rate": effective_guardrail_next_high_hit_rate,
        "guardrail_next_close_positive_rate": effective_guardrail_next_close_positive_rate,
        "focus_tickers": sorted(focus_ticker_set),
        "passing_variant_count": len(passing_variants),
        "passing_case_frequency": [
            {"case_key": case_key, "passing_variant_count": int(count)}
            for case_key, count in passing_case_frequency.most_common()
        ],
        "recommendation": _build_recommendation(
            passing_variants=passing_variants,
            minimal_passing_variant=minimal_passing_variant,
        ),
    }


def render_btst_penalty_frontier_markdown(analysis: dict[str, Any]) -> str:
    baseline = dict(analysis["baseline"])
    lines: list[str] = []
    lines.append("# BTST Penalty Frontier Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- input_path: {analysis['input_path']}")
    lines.append(f"- baseline_profile: {analysis['baseline_profile']}")
    lines.append(f"- trade_dates: {baseline['trade_dates']}")
    lines.append(f"- near_miss_threshold_grid: {analysis['near_miss_threshold_grid']}")
    lines.append(f"- layer_c_avoid_penalty_grid: {analysis['layer_c_avoid_penalty_grid']}")
    lines.append(f"- stale_weight_grid: {analysis['stale_weight_grid']}")
    lines.append(f"- extension_weight_grid: {analysis['extension_weight_grid']}")
    lines.append(f"- focus_tickers: {analysis['focus_tickers']}")
    lines.append(f"- next_high_hit_threshold: {analysis['next_high_hit_threshold']}")
    lines.append(f"- guardrail_next_high_hit_rate: {analysis['guardrail_next_high_hit_rate']}")
    lines.append(f"- guardrail_next_close_positive_rate: {analysis['guardrail_next_close_positive_rate']}")
    lines.append(f"- best_variant: {analysis['best_variant']}")
    lines.append(f"- minimal_passing_variant: {analysis['minimal_passing_variant']}")
    lines.append(f"- passing_variant_count: {analysis['passing_variant_count']}")
    lines.append("")
    lines.append("## Baseline Summary")
    lines.append(f"- profile_config: {baseline['profile_config']}")
    lines.append(f"- decision_counts: {baseline['decision_counts']}")
    lines.append(f"- tradeable_surface: {baseline['surface_summaries']['tradeable']}")
    lines.append(f"- false_negative_proxy_summary: {baseline['false_negative_proxy_summary']}")
    lines.append("")
    lines.append("## Passing Case Frequency")
    for row in analysis["passing_case_frequency"]:
        lines.append(f"- {row['case_key']}: {row['passing_variant_count']}")
    if not analysis["passing_case_frequency"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Ranked Variants")
    for row in analysis["ranked_variants"]:
        lines.append(
            "- "
            f"{row['variant_name']}: family={row['variant_family']}, cost={row['adjustment_cost']}, "
            f"tradeable={row['tradeable_count']}, closed_cycle_tradeable={row['closed_cycle_tradeable_count']}, "
            f"near_miss={row['near_miss_threshold']}, avoid={row['layer_c_avoid_penalty']}, "
            f"stale={row['stale_score_penalty_weight']}, ext={row['extension_score_penalty_weight']}, "
            f"guardrail={row['guardrail_status']}, next_high_hit_rate={row['next_high_hit_rate_at_threshold']}, "
            f"next_close_positive_rate={row['next_close_positive_rate']}, focus_cases={row['focus_tradeable_cases']}, "
            f"note={row['comparison_note']}"
        )
    if not analysis["ranked_variants"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare BTST threshold and penalty relief rows on a replay window using closed-cycle outcomes.")
    parser.add_argument("input_path", help="Path to a selection_target_replay_input.json file, selection_artifacts directory, or report directory.")
    parser.add_argument("--baseline-profile", default="default")
    parser.add_argument("--near-miss-threshold-grid", default="0.46,0.44,0.42")
    parser.add_argument("--layer-c-avoid-penalty-grid", default="")
    parser.add_argument("--stale-weight-grid", default="0.12,0.10,0.08,0.06")
    parser.add_argument("--extension-weight-grid", default="0.08,0.06,0.04,0.02")
    parser.add_argument("--focus-tickers", default="")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--guardrail-next-high-hit-rate", type=float, default=None)
    parser.add_argument("--guardrail-next-close-positive-rate", type=float, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analysis = analyze_btst_penalty_frontier(
        args.input_path,
        baseline_profile=args.baseline_profile,
        near_miss_threshold_grid=_parse_float_grid(args.near_miss_threshold_grid),
        layer_c_avoid_penalty_grid=_parse_float_grid(args.layer_c_avoid_penalty_grid),
        stale_weight_grid=_parse_float_grid(args.stale_weight_grid),
        extension_weight_grid=_parse_float_grid(args.extension_weight_grid),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
        guardrail_next_high_hit_rate=args.guardrail_next_high_hit_rate,
        guardrail_next_close_positive_rate=args.guardrail_next_close_positive_rate,
        focus_tickers=[token.strip() for token in str(args.focus_tickers or "").split(",") if token.strip()],
    )
    if args.output_json is not None:
        args.output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md is not None:
        args.output_md.write_text(render_btst_penalty_frontier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()