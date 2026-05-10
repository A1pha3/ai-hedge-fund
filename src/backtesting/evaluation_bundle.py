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
    "t_plus_3_close_positive_rate",
    "t_plus_3_close_expectancy",
    "sample_weight",
)
_GUARDRAIL_KEYS = (
    "downside_p10",
    "incremental_theme_exposure",
)
_CONTEXT_KEYS = (
    "projected_theme_exposure",
    "theme_direction_peer_count",
    "theme_direction_rank",
    "liquidity_capacity_raw_100",
    "crowding_risk_raw_100",
    "gap_risk_raw_100",
)


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


def _collect_numeric_metrics(metrics: dict[str, Any], keys: Sequence[str]) -> dict[str, float | None]:
    collected: dict[str, float | None] = {}
    for key in keys:
        value = metrics.get(key)
        if value is None:
            collected[key] = None
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            collected[key] = None
            continue
        collected[key] = parsed if math.isfinite(parsed) else None
    return collected


def build_canonical_btst_evaluation_bundle(metrics: dict[str, Any] | None) -> CanonicalBTSTEvaluationBundle:
    payload = dict(metrics or {})
    return CanonicalBTSTEvaluationBundle(
        objective_metrics=_collect_numeric_metrics(payload, _OBJECTIVE_KEYS),
        guardrail_metrics=_collect_numeric_metrics(payload, _GUARDRAIL_KEYS),
        context_metrics=_collect_numeric_metrics(payload, _CONTEXT_KEYS),
    )
