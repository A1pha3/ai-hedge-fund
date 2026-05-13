from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

_OBJECTIVE_KEYS = (
    "next_close_positive_rate",
    "next_close_payoff_ratio",
    "next_close_expectancy",
    "next_high_hit_rate",
    "t_plus_2_close_positive_rate",
    "t_plus_2_close_payoff_ratio",
    "t_plus_3_close_positive_rate",
    "t_plus_3_close_expectancy",
    "t_plus_3_close_payoff_ratio",
    "sample_weight",
    "max_future_high_return_2_5d_hit_rate_at_20pct",
    "median_max_future_high_return_2_5d",
    "next_open_return",
    "next_open_to_close_return",
    "time_to_hit_20pct_median",
)
_GUARDRAIL_KEYS = (
    "downside_p10",
    "window_coverage",
    "incremental_theme_exposure",
    "avg_composite_score_escaped",
)
_CONTEXT_KEYS = (
    "projected_theme_exposure",
    "theme_direction_peer_count",
    "theme_direction_rank",
    "liquidity_capacity_raw_100",
    "crowding_risk_raw_100",
    "gap_risk_raw_100",
)
BTST_QUALITY_FLOORS: dict[str, float] = {
    "next_close_positive_rate": 0.54,
    "next_high_hit_rate": 0.56,
    "t_plus_2_close_positive_rate": 0.52,
    "t_plus_2_close_payoff_ratio": 1.0,
    "t_plus_3_close_positive_rate": 0.50,
    "t_plus_3_close_expectancy": 0.0,
    "t_plus_3_close_payoff_ratio": 1.0,
    "downside_p10": -0.06,
    "sample_weight": 0.60,
    "window_coverage": 0.60,
    "avg_composite_score_escaped": 0.45,
}
BTST_EXECUTION_GUARDRAILS: dict[str, dict[str, float]] = {
    "liquidity_capacity_raw_100": {"min": 50.0},
    "crowding_risk_raw_100": {"max": 70.0},
    "gap_risk_raw_100": {"max": 60.0},
}


@dataclass(frozen=True)
class CanonicalBTSTEvaluationBundle:
    objective_metrics: dict[str, float | None]
    guardrail_metrics: dict[str, float | None]
    context_metrics: dict[str, float | None]

    def lookup(self, key: str) -> float | None:
        if key in self.objective_metrics:
            return self.objective_metrics[key]
        if key in self.guardrail_metrics:
            return self.guardrail_metrics[key]
        return self.context_metrics.get(key)

    def to_payload(self) -> dict[str, dict[str, float | None]]:
        return {
            "objective_metrics": dict(self.objective_metrics),
            "guardrail_metrics": dict(self.guardrail_metrics),
            "context_metrics": dict(self.context_metrics),
        }


def coerce_numeric_metric_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _collect_numeric_metrics(metrics: dict[str, Any], keys: Sequence[str]) -> dict[str, float | None]:
    collected: dict[str, float | None] = {}
    for key in keys:
        collected[key] = coerce_numeric_metric_value(metrics.get(key))
    return collected


def build_canonical_btst_evaluation_bundle(metrics: dict[str, Any] | None) -> CanonicalBTSTEvaluationBundle:
    payload = dict(metrics or {})
    return CanonicalBTSTEvaluationBundle(
        objective_metrics=_collect_numeric_metrics(payload, _OBJECTIVE_KEYS),
        guardrail_metrics=_collect_numeric_metrics(payload, _GUARDRAIL_KEYS),
        context_metrics=_collect_numeric_metrics(payload, _CONTEXT_KEYS),
    )


def build_btst_quality_floor_blockers(metrics: dict[str, Any] | None, *, prefix: str = "btst_quality") -> list[str]:
    bundle = build_canonical_btst_evaluation_bundle(metrics)
    blockers: list[str] = []
    for metric_key, floor in BTST_QUALITY_FLOORS.items():
        value = bundle.lookup(metric_key)
        if value is None:
            continue
        if float(value) < float(floor):
            blockers.append(f"{prefix}_{metric_key}_floor_breach")
    return blockers


def build_btst_execution_blockers(metrics: dict[str, Any] | None) -> list[str]:
    bundle = build_canonical_btst_evaluation_bundle(metrics)
    blockers: list[str] = []
    for metric_key, guardrail in BTST_EXECUTION_GUARDRAILS.items():
        value = bundle.lookup(metric_key)
        if value is None:
            continue
        min_floor = guardrail.get("min")
        max_cap = guardrail.get("max")
        if min_floor is not None and float(value) < float(min_floor):
            blockers.append(f"{metric_key.removesuffix('_raw_100')}_floor_breach")
        if max_cap is not None and float(value) > float(max_cap):
            blockers.append(f"{metric_key.removesuffix('_raw_100')}_cap_breach")
    return blockers
