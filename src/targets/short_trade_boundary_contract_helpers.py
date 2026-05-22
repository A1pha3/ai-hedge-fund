from __future__ import annotations

from typing import Any, Mapping

BOUNDARY_CONTRACT_CORE_KEYS = (
    "breakout_freshness",
    "close_strength",
    "short_term_reversal",
    "trend_acceleration",
    "trend_continuation",
    "volume_expansion_quality",
)


def build_boundary_contract_core_payload(
    *,
    explicit_values: Mapping[str, Any] | None = None,
    metrics_payload: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    payload: dict[str, float] = {}
    explicit = dict(explicit_values or {})
    metrics = dict(metrics_payload or {})
    for key in BOUNDARY_CONTRACT_CORE_KEYS:
        value = explicit.get(key)
        if value is None:
            value = metrics.get(key)
        if value is not None:
            payload[key] = round(float(value), 4)
    return payload


def merge_boundary_contract_core_payload(
    *,
    explainability_payload: Mapping[str, Any] | None = None,
    core_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(explainability_payload or {})
    for key, value in dict(core_payload or {}).items():
        merged.setdefault(str(key), value)
    return merged
