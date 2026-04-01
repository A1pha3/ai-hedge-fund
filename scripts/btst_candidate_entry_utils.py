from __future__ import annotations

from typing import Any


def build_watchlist_avoid_weak_structure_filter(
    *,
    breakout_freshness_max: float | None = None,
    trend_acceleration_max: float | None = None,
    volume_expansion_quality_max: float | None = None,
    close_strength_max: float | None = None,
    catalyst_freshness_max: float | None = None,
) -> dict[str, Any]:
    metric_max_thresholds: dict[str, float] = {}
    if breakout_freshness_max is not None:
        metric_max_thresholds["breakout_freshness"] = float(breakout_freshness_max)
    if trend_acceleration_max is not None:
        metric_max_thresholds["trend_acceleration"] = float(trend_acceleration_max)
    if volume_expansion_quality_max is not None:
        metric_max_thresholds["volume_expansion_quality"] = float(volume_expansion_quality_max)
    if close_strength_max is not None:
        metric_max_thresholds["close_strength"] = float(close_strength_max)
    if catalyst_freshness_max is not None:
        metric_max_thresholds["catalyst_freshness"] = float(catalyst_freshness_max)
    return {
        "name": "watchlist_avoid_boundary_weak_structure_entry",
        "candidate_sources": ["watchlist_filter_diagnostics"],
        "all_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "metric_max_thresholds": metric_max_thresholds,
    }