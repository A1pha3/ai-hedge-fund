from __future__ import annotations

from typing import Any


DEFAULT_NEAR_MISS_THRESHOLD = 0.46
DEFAULT_STALE_WEIGHT = 0.12
DEFAULT_OVERHEAD_WEIGHT = 0.1
DEFAULT_EXTENSION_WEIGHT = 0.08
DEFAULT_AVOID_WEIGHT = 1.0


def resolve_default_thresholds(row: dict[str, Any]) -> dict[str, float]:
    thresholds = dict(row.get("thresholds") or {})
    return {
        "near_miss_threshold": float(thresholds.get("near_miss_threshold") or DEFAULT_NEAR_MISS_THRESHOLD),
        "stale_score_penalty_weight": float(thresholds.get("stale_score_penalty_weight") or DEFAULT_STALE_WEIGHT),
        "overhead_score_penalty_weight": float(thresholds.get("overhead_score_penalty_weight") or DEFAULT_OVERHEAD_WEIGHT),
        "extension_score_penalty_weight": float(thresholds.get("extension_score_penalty_weight") or DEFAULT_EXTENSION_WEIGHT),
        "layer_c_avoid_penalty": float(thresholds.get("layer_c_avoid_penalty") or DEFAULT_AVOID_WEIGHT),
    }


def compute_replayed_score(
    *,
    row: dict[str, Any],
    stale_weight: float,
    overhead_weight: float,
    extension_weight: float,
    avoid_weight: float,
) -> float:
    total_positive = float(row.get("total_positive_contribution") or 0.0)
    stale_penalty = float(row.get("stale_trend_repair_penalty") or 0.0) * stale_weight
    overhead_penalty = float(row.get("overhead_supply_penalty") or 0.0) * overhead_weight
    extension_penalty = float(row.get("extension_without_room_penalty") or 0.0) * extension_weight
    avoid_penalty = float(row.get("layer_c_avoid_penalty") or 0.0) * avoid_weight
    return total_positive - stale_penalty - overhead_penalty - extension_penalty - avoid_penalty