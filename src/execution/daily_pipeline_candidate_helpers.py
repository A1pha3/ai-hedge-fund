from __future__ import annotations

from typing import Any


def resolve_short_trade_candidate_context(shadow_candidate: Any) -> tuple[str, str, str, list[str]]:
    if shadow_candidate and shadow_candidate.candidate_pool_lane == "layer_a_liquidity_corridor":
        reason = "upstream_base_liquidity_uplift_shadow"
        return (
            reason,
            "upstream_liquidity_corridor_shadow",
            "candidate_pool_truncated_after_filters",
            [reason, "candidate_pool_truncated_after_filters", "layer_a_liquidity_corridor"],
        )
    if shadow_candidate and shadow_candidate.candidate_pool_lane == "post_gate_liquidity_competition":
        reason = "post_gate_liquidity_competition_shadow"
        return (
            reason,
            "post_gate_liquidity_competition_shadow",
            "candidate_pool_truncated_after_filters",
            [reason, "candidate_pool_truncated_after_filters", "post_gate_liquidity_competition"],
        )
    reason = "short_trade_candidate_score_ranked"
    return reason, "short_trade_boundary", "layer_b_boundary", [reason, "short_trade_prequalified"]


def rank_scored_entries(
    rows: list[tuple[float, ...]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    rows.sort(key=lambda row: (*row[:-1], str(row[-1].get("ticker") or "")), reverse=True)
    ranked_entries: list[dict[str, Any]] = []
    for rank, row in enumerate(rows[:limit], start=1):
        entry = row[-1]
        entry["rank"] = rank
        ranked_entries.append(entry)
    return ranked_entries


def build_catalyst_theme_tags(
    *,
    catalyst_freshness: float,
    catalyst_freshness_min: float,
    breakout_freshness: float,
    close_strength: float,
    sector_resonance: float,
    close_momentum_catalyst_relief_applied: bool,
) -> list[str]:
    theme_tags: list[str] = []
    if catalyst_freshness >= 0.65:
        theme_tags.append("strong_catalyst_freshness")
    elif catalyst_freshness >= catalyst_freshness_min:
        theme_tags.append("fresh_catalyst_support")
    elif close_momentum_catalyst_relief_applied:
        theme_tags.append("close_momentum_catalyst_relief")
    if sector_resonance >= 0.45:
        theme_tags.append("sector_alignment_support")
    if breakout_freshness >= 0.45:
        theme_tags.append("breakout_watch_ready")
    if close_strength >= 0.45:
        theme_tags.append("close_strength_support")
    return theme_tags


def build_catalyst_theme_metrics_payload(
    *,
    gate_status: dict[str, Any],
    blockers: list[str],
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    catalyst_freshness: float,
    candidate_score: float,
    effective_catalyst_freshness: float,
    close_momentum_catalyst_relief: dict[str, Any],
    threshold_checks: dict[str, float],
    threshold_metric_values: dict[str, float],
    theme_tags: list[str],
) -> dict[str, Any]:
    return {
        "breakout_freshness": breakout_freshness,
        "trend_acceleration": trend_acceleration,
        "close_strength": close_strength,
        "sector_resonance": sector_resonance,
        "catalyst_freshness": catalyst_freshness,
        "candidate_score": candidate_score,
        "gate_status": gate_status,
        "blockers": blockers,
        "theme_tags": theme_tags,
        "effective_catalyst_freshness": effective_catalyst_freshness,
        "close_momentum_catalyst_relief": close_momentum_catalyst_relief,
        "threshold_checks": threshold_checks,
        "threshold_metric_values": threshold_metric_values,
    }


def resolve_catalyst_theme_filter_reason(
    *,
    gate_status: dict[str, Any],
    effective_catalyst_freshness: float,
    catalyst_freshness_min: float,
    sector_resonance: float,
    effective_sector_min: float,
    close_strength: float,
    close_strength_min: float,
    breakout_freshness: float,
    breakout_freshness_min: float,
    candidate_score: float,
    candidate_score_min: float,
) -> str:
    if str(gate_status.get("data") or "") != "pass":
        return "metric_data_fail"
    if effective_catalyst_freshness < catalyst_freshness_min:
        return "catalyst_freshness_below_catalyst_theme_floor"
    if sector_resonance < effective_sector_min:
        return "sector_resonance_below_catalyst_theme_floor"
    if close_strength < close_strength_min:
        return "close_strength_below_catalyst_theme_floor"
    if breakout_freshness < breakout_freshness_min:
        return "breakout_freshness_below_catalyst_theme_floor"
    if candidate_score < candidate_score_min:
        return "candidate_score_below_catalyst_theme_floor"
    return "catalyst_theme_candidate_score_ranked"
