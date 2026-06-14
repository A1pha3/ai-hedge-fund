from __future__ import annotations

from typing import Any, Iterable

ROUND89_SUMMARY_METRICS = (
    "win_rate",
    "avg_ret",
    "payoff_ratio",
    "expectancy",
    "downside_p10",
    "tplus2_expectancy",
    "tplus2_payoff_ratio",
)

ROUND89_HIGHER_IS_BETTER_METRICS = {
    "win_rate",
    "avg_ret",
    "payoff_ratio",
    "expectancy",
    "tplus2_expectancy",
    "tplus2_payoff_ratio",
}

ROUND89_LOWER_IS_BETTER_METRICS = {
    "downside_p10",
}

ROUND89_SELECTED_GUARDRAILS = (
    "win_rate",
    "avg_ret",
    "payoff_ratio",
    "expectancy",
    "downside_p10",
)


def summarize_round89_surface(rows: Iterable[dict[str, Any]]) -> dict[str, float | int]:
    items = list(rows)
    if not items:
        return {"n_days": 0}

    summary: dict[str, float | int] = {"n_days": len(items)}
    for metric in ROUND89_SUMMARY_METRICS:
        values = [float(item[metric]) for item in items if item.get(metric) is not None]
        if values:
            summary[metric] = float(sum(values) / len(values))
    return summary


def _build_surface_delta(candidate_summary: dict[str, Any], baseline_summary: dict[str, Any], surface_name: str) -> dict[str, float]:
    delta_summary: dict[str, float] = {}
    for metric in ROUND89_SELECTED_GUARDRAILS:
        candidate_value = candidate_summary.get(metric)
        baseline_value = baseline_summary.get(metric)
        if candidate_value is None or baseline_value is None:
            continue
        delta_summary[f"{surface_name}_{metric}_delta"] = float(candidate_value) - float(baseline_value)
    return delta_summary


def build_round89_rollout_assessment(
    payload: dict[str, Any],
    *,
    candidate_profile: str = "trend_corrected_v1",
    baseline_profiles: tuple[str, ...] = ("ic_v5", "momentum_optimized"),
    surface_name: str = "selected",
) -> dict[str, Any]:
    surface_summaries: dict[str, dict[str, Any]] = {}
    for profile_name, surfaces in payload.items():
        if not isinstance(surfaces, dict):
            continue
        profile_surface_summaries = {
            candidate_surface_name: summarize_round89_surface(candidate_rows)
            for candidate_surface_name, candidate_rows in surfaces.items()
            if isinstance(candidate_rows, list)
        }
        surface_summaries[profile_name] = profile_surface_summaries

    candidate_surface_summary = surface_summaries.get(candidate_profile, {}).get(surface_name) or {"n_days": 0}
    comparison_summary: dict[str, dict[str, float]] = {}
    blockers: list[str] = []

    for baseline_profile in baseline_profiles:
        baseline_surface_summary = surface_summaries.get(baseline_profile, {}).get(surface_name) or {"n_days": 0}
        baseline_comparison = _build_surface_delta(candidate_surface_summary, baseline_surface_summary, surface_name)
        comparison_summary[baseline_profile] = baseline_comparison

        for metric in ROUND89_SELECTED_GUARDRAILS:
            delta_key = f"{surface_name}_{metric}_delta"
            delta_value = baseline_comparison.get(delta_key)
            if delta_value is None:
                blockers.append(f"missing_{delta_key}_vs_{baseline_profile}")
                continue
            if metric in ROUND89_HIGHER_IS_BETTER_METRICS and delta_value < 0:
                blockers.append(f"{surface_name}_{metric}_regressed_vs_{baseline_profile}")
            if metric in ROUND89_LOWER_IS_BETTER_METRICS and delta_value < 0:
                blockers.append(f"{surface_name}_{metric}_regressed_vs_{baseline_profile}")

    deduped_blockers = list(dict.fromkeys(blockers))
    return {
        "candidate_profile": candidate_profile,
        "surface_name": surface_name,
        "surface_summaries": surface_summaries,
        "comparison_summary": comparison_summary,
        "action": "promote" if not deduped_blockers else "hold",
        "blockers": deduped_blockers,
    }
