"""Pure weighted-signal math shared by production and custom reweighting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SignalScoreInput:
    """The three numeric fields consumed by Layer-B score fusion."""

    direction: float
    confidence: float
    completeness: float


def normalize_active_weights(
    weights: Mapping[str, float],
    signals: Mapping[str, SignalScoreInput],
    *,
    fallback_weights: Mapping[str, float],
    excluded_names: set[str] | None = None,
    weight_overrides: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Normalize weights over signals with usable completeness."""

    excluded_names = excluded_names or set()
    weight_overrides = weight_overrides or {}
    active = {
        name: max(float(weight_overrides.get(name, weights.get(name, 0.0))), 0.0)
        for name, signal in signals.items()
        if signal.completeness > 0 and name not in excluded_names
    }
    total = sum(active.values())
    if total <= 0:
        active = {
            name: max(float(fallback_weights.get(name, 0.0)), 0.0)
            for name in signals
            if name not in excluded_names
        }
        total = sum(active.values())
    return (
        {name: value / total for name, value in active.items()}
        if total > 0
        else {}
    )


def compute_weighted_signal_score(
    signals: Mapping[str, SignalScoreInput],
    normalized_weights: Mapping[str, float],
) -> float:
    """Compute the unclamped Layer-B score from normalized active weights."""

    return sum(
        float(normalized_weights.get(name, 0.0))
        * signal.direction
        * (signal.confidence / 100.0)
        * signal.completeness
        for name, signal in signals.items()
    )
