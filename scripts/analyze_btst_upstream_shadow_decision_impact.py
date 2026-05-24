from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_multi_window_profile_validation import analyze_btst_multi_window_profile_validation

DEFAULT_REPORTS_ROOT = Path("data/reports")
DEFAULT_BASELINE_PROFILE = "btst_precision_v2_liquidity_shadow_release_probe"

EXPERIMENTS: list[dict[str, Any]] = [
    {
        "experiment_name": "current_probe_control",
        "profile_overrides": {},
    },
    {
        "experiment_name": "relief_free_shadow_caps",
        "profile_overrides": {
            "liquidity_shadow_source_specific_rank_cap_require_relief_applied": False,
            "upstream_shadow_source_specific_rank_cap_trend_acceleration_min": 0.0,
            "upstream_shadow_source_specific_rank_cap_close_strength_min": 0.0,
        },
    },
    {
        "experiment_name": "relief_free_quality_gate",
        "profile_overrides": {
            "liquidity_shadow_source_specific_rank_cap_require_relief_applied": False,
            "upstream_shadow_source_specific_rank_cap_trend_acceleration_min": 0.8,
            "upstream_shadow_source_specific_rank_cap_close_strength_min": 0.85,
        },
    },
    {
        "experiment_name": "relief_free_quality_gate_tighter_caps",
        "profile_overrides": {
            "liquidity_shadow_source_specific_rank_cap_require_relief_applied": False,
            "upstream_shadow_source_specific_rank_cap_trend_acceleration_min": 0.8,
            "upstream_shadow_source_specific_rank_cap_close_strength_min": 0.85,
            "liquidity_shadow_selected_rank_cap_ratio": 0.12,
            "liquidity_shadow_near_miss_rank_cap_ratio": 0.24,
        },
    },
]


def _aggregate_upstream_shadow_delta(rows: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "selected_count_delta": 0,
        "near_miss_count_delta": 0,
        "tradeable_count_delta": 0,
        "execution_eligible_count_delta": 0,
    }
    for row in list(rows or []):
        delta = dict(row.get("upstream_shadow_runtime_activation_attribution") or {})
        for key in totals:
            totals[key] += int(delta.get(key) or 0)
    return totals


def _aggregate_tradeable_surface_deltas(rows: list[dict[str, Any]]) -> dict[str, float]:
    totals = {
        "next_close_positive_rate": 0.0,
        "next_close_return_p10": 0.0,
        "t_plus_2_close_return_median": 0.0,
    }
    for row in list(rows or []):
        delta = dict(row.get("tradeable_surface_delta") or {})
        for key in totals:
            totals[key] += float(delta.get(key) or 0.0)
    return {key: round(value, 4) for key, value in totals.items()}


def _variant_sort_key(result: dict[str, Any]) -> tuple[int, int, float, float, float]:
    upstream_delta = dict(result.get("aggregate_upstream_shadow_delta") or {})
    tradeable_delta = dict(result.get("aggregate_tradeable_surface_delta") or {})
    return (
        int(upstream_delta.get("selected_count_delta") or 0),
        int(upstream_delta.get("tradeable_count_delta") or 0),
        float(tradeable_delta.get("next_close_positive_rate") or 0.0),
        float(tradeable_delta.get("next_close_return_p10") or 0.0),
        float(tradeable_delta.get("t_plus_2_close_return_median") or 0.0),
    )


def _run_experiment(*, reports_root: str | Path, experiment_name: str, profile_overrides: dict[str, Any], next_high_hit_threshold: float = 0.15) -> dict[str, Any]:
    analysis = analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile=DEFAULT_BASELINE_PROFILE,
        variant_profile=DEFAULT_BASELINE_PROFILE,
        variant_profile_overrides=profile_overrides,
        next_high_hit_threshold=next_high_hit_threshold,
    )
    rows = list(analysis.get("rows") or [])
    return {
        "experiment_name": experiment_name,
        "profile_overrides": dict(profile_overrides or {}),
        "report_dir_count": int(analysis.get("report_dir_count") or 0),
        "rows": rows,
        "keep_baseline_count": int(analysis.get("keep_baseline_count") or 0),
        "variant_supports_t1_count": int(analysis.get("variant_supports_t1_count") or 0),
        "variant_improves_t2_only_count": int(analysis.get("variant_improves_t2_only_count") or 0),
        "recommendation": str(analysis.get("recommendation") or ""),
        "aggregate_upstream_shadow_delta": _aggregate_upstream_shadow_delta(rows),
        "aggregate_tradeable_surface_delta": _aggregate_tradeable_surface_deltas(rows),
    }


def _normalize_experiment_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result or {})
    rows = list(normalized.get("rows") or [])
    normalized.setdefault("profile_overrides", {})
    normalized.setdefault("report_dir_count", 0)
    normalized.setdefault("keep_baseline_count", 0)
    normalized.setdefault("variant_supports_t1_count", 0)
    normalized.setdefault("variant_improves_t2_only_count", 0)
    normalized.setdefault("recommendation", "")
    normalized["aggregate_upstream_shadow_delta"] = _aggregate_upstream_shadow_delta(rows)
    normalized["aggregate_tradeable_surface_delta"] = _aggregate_tradeable_surface_deltas(rows)
    return normalized


def analyze_upstream_shadow_decision_impact(*, reports_root: str | Path, output_label: str, next_high_hit_threshold: float = 0.15) -> dict[str, Any]:
    control_variant: dict[str, Any] | None = None
    ranked_variants: list[dict[str, Any]] = []
    rejected_variants: list[dict[str, Any]] = []

    for experiment in EXPERIMENTS:
        result = _normalize_experiment_result(
            _run_experiment(
            reports_root=reports_root,
            experiment_name=str(experiment["experiment_name"]),
            profile_overrides=dict(experiment.get("profile_overrides") or {}),
            next_high_hit_threshold=next_high_hit_threshold,
            )
        )
        if result["experiment_name"] == "current_probe_control":
            control_variant = result
            continue
        if int(result.get("keep_baseline_count") or 0) > 0:
            rejected_variants.append(result)
            continue
        ranked_variants.append(result)

    ranked_variants.sort(key=_variant_sort_key, reverse=True)

    return {
        "output_label": output_label,
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "baseline_profile": DEFAULT_BASELINE_PROFILE,
        "control_variant": control_variant,
        "best_variant": ranked_variants[0] if ranked_variants else None,
        "ranked_variants": ranked_variants,
        "rejected_variants": rejected_variants,
    }


def render_upstream_shadow_decision_impact_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Upstream Shadow Decision Impact")
    lines.append("")
    lines.append(f"- output_label: {analysis.get('output_label')}")
    lines.append(f"- baseline_profile: {analysis.get('baseline_profile')}")
    lines.append("")
    best_variant = dict(analysis.get("best_variant") or {})
    if best_variant:
        upstream_delta = dict(best_variant.get("aggregate_upstream_shadow_delta") or {})
        tradeable_delta = dict(best_variant.get("aggregate_tradeable_surface_delta") or {})
        lines.append("## Best Variant")
        lines.append(f"- experiment_name: {best_variant.get('experiment_name')}")
        lines.append(f"- selected_count_delta: {upstream_delta.get('selected_count_delta')}")
        lines.append(f"- near_miss_count_delta: {upstream_delta.get('near_miss_count_delta')}")
        lines.append(f"- tradeable_count_delta: {upstream_delta.get('tradeable_count_delta')}")
        lines.append(f"- execution_eligible_count_delta: {upstream_delta.get('execution_eligible_count_delta')}")
        lines.append(f"- next_close_positive_rate_delta: {tradeable_delta.get('next_close_positive_rate')}")
        lines.append(f"- next_close_return_p10_delta: {tradeable_delta.get('next_close_return_p10')}")
        lines.append(f"- t_plus_2_close_return_median_delta: {tradeable_delta.get('t_plus_2_close_return_median')}")
        lines.append("")
    else:
        lines.append("## Best Variant")
        lines.append("- none")
        lines.append("")

    lines.append("## Ranked Variants")
    for variant in list(analysis.get("ranked_variants") or []):
        upstream_delta = dict(variant.get("aggregate_upstream_shadow_delta") or {})
        lines.append(
            f"- {variant.get('experiment_name')}: selected_count_delta={upstream_delta.get('selected_count_delta')}, "
            f"tradeable_count_delta={upstream_delta.get('tradeable_count_delta')}, recommendation={variant.get('recommendation')}"
        )
    if not list(analysis.get("ranked_variants") or []):
        lines.append("- none")
    lines.append("")

    lines.append("## Rejected Variants")
    for variant in list(analysis.get("rejected_variants") or []):
        lines.append(f"- {variant.get('experiment_name')}: keep_baseline_count={variant.get('keep_baseline_count')}, recommendation={variant.get('recommendation')}")
    if not list(analysis.get("rejected_variants") or []):
        lines.append("- none")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze upstream shadow rollout variants for measurable decision impact.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-label", default="latest")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.15)
    args = parser.parse_args()

    analysis = analyze_upstream_shadow_decision_impact(
        reports_root=args.reports_root,
        output_label=str(args.output_label),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
    )

    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_upstream_shadow_decision_impact_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
