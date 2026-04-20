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


def _extract_gate_status_and_blockers(snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    gate_status = dict(snapshot.get("gate_status") or {})
    blockers = sorted({str(blocker) for blocker in list(snapshot.get("blockers") or []) if str(blocker or "").strip()})
    return gate_status, blockers


def build_short_trade_boundary_metrics_payload(
    *,
    snapshot: dict[str, Any],
    compute_candidate_score_fn,
) -> dict[str, Any]:
    gate_status, blockers = _extract_gate_status_and_blockers(snapshot)
    return {
        "breakout_freshness": round(float(snapshot.get("breakout_freshness", 0.0) or 0.0), 4),
        "trend_acceleration": round(float(snapshot.get("trend_acceleration", 0.0) or 0.0), 4),
        "volume_expansion_quality": round(float(snapshot.get("volume_expansion_quality", 0.0) or 0.0), 4),
        "catalyst_freshness": round(float(snapshot.get("catalyst_freshness", 0.0) or 0.0), 4),
        "close_strength": round(float(snapshot.get("close_strength", 0.0) or 0.0), 4),
        "candidate_score": compute_candidate_score_fn(snapshot),
        "gate_status": gate_status,
        "blockers": blockers,
    }


def resolve_short_trade_boundary_filter_reason(
    *,
    metrics_payload: dict[str, Any],
    breakout_min: float,
    trend_min: float,
    volume_min: float,
    catalyst_min: float,
    candidate_score_min: float,
) -> str:
    gate_status = dict(metrics_payload.get("gate_status") or {})
    blockers = list(metrics_payload.get("blockers") or [])
    if str(gate_status.get("data") or "") != "pass":
        return "metric_data_fail"
    if str(gate_status.get("structural") or "") == "fail" or blockers:
        return "structural_prefilter_fail"
    if float(metrics_payload.get("breakout_freshness", 0.0) or 0.0) < breakout_min:
        return "breakout_freshness_below_short_trade_boundary_floor"
    if float(metrics_payload.get("trend_acceleration", 0.0) or 0.0) < trend_min:
        return "trend_acceleration_below_short_trade_boundary_floor"
    if float(metrics_payload.get("volume_expansion_quality", 0.0) or 0.0) < volume_min:
        return "volume_expansion_below_short_trade_boundary_floor"
    if float(metrics_payload.get("catalyst_freshness", 0.0) or 0.0) < catalyst_min:
        return "catalyst_freshness_below_short_trade_boundary_floor"
    if float(metrics_payload.get("candidate_score", 0.0) or 0.0) < candidate_score_min:
        return "candidate_score_below_short_trade_boundary_floor"
    return "short_trade_prequalified"


def qualify_short_trade_boundary_candidate_from_snapshot(
    *,
    snapshot: dict[str, Any],
    compute_candidate_score_fn,
    breakout_min: float,
    trend_min: float,
    volume_min: float,
    catalyst_min: float,
    candidate_score_min: float,
) -> tuple[bool, str, dict[str, Any]]:
    metrics_payload = build_short_trade_boundary_metrics_payload(
        snapshot=snapshot,
        compute_candidate_score_fn=compute_candidate_score_fn,
    )
    filter_reason = resolve_short_trade_boundary_filter_reason(
        metrics_payload=metrics_payload,
        breakout_min=breakout_min,
        trend_min=trend_min,
        volume_min=volume_min,
        catalyst_min=catalyst_min,
        candidate_score_min=candidate_score_min,
    )
    return filter_reason == "short_trade_prequalified", filter_reason, metrics_payload


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
    quality_score: float,
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
        "quality_score": quality_score,
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
    quality_score: float,
    quality_score_min: float,
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
    if quality_score < quality_score_min:
        return "quality_score_below_catalyst_theme_floor"
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


def qualify_catalyst_theme_candidate_from_snapshot(
    *,
    snapshot: dict[str, Any],
    resolve_close_momentum_relief_fn,
    compute_candidate_score_fn,
    catalyst_theme_sector_min: float,
    catalyst_theme_candidate_score_min: float,
    catalyst_theme_breakout_min: float,
    catalyst_theme_close_min: float,
    catalyst_theme_catalyst_min: float,
    catalyst_theme_quality_min: float,
) -> tuple[bool, str, dict[str, Any]]:
    gate_status, blockers = _extract_gate_status_and_blockers(snapshot)
    breakout_freshness = round(float(snapshot.get("breakout_freshness", 0.0) or 0.0), 4)
    trend_acceleration = round(float(snapshot.get("trend_acceleration", 0.0) or 0.0), 4)
    close_strength = round(float(snapshot.get("close_strength", 0.0) or 0.0), 4)
    quality_score = round(float(snapshot.get("quality_score", 0.5) or 0.5), 4)
    sector_resonance = round(float(snapshot.get("sector_resonance", 0.0) or 0.0), 4)
    catalyst_freshness = round(float(snapshot.get("catalyst_freshness", 0.0) or 0.0), 4)
    close_momentum_catalyst_relief = resolve_close_momentum_relief_fn(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        catalyst_freshness=catalyst_freshness,
    )
    effective_catalyst_freshness = round(
        float(close_momentum_catalyst_relief.get("effective_catalyst_freshness") or catalyst_freshness),
        4,
    )
    effective_sector_min = round(
        float(close_momentum_catalyst_relief.get("effective_sector_min") or catalyst_theme_sector_min),
        4,
    )
    candidate_score = compute_candidate_score_fn(
        {
            "breakout_freshness": breakout_freshness,
            "trend_acceleration": trend_acceleration,
            "close_strength": close_strength,
            "sector_resonance": sector_resonance,
            "catalyst_freshness": effective_catalyst_freshness,
        }
    )
    threshold_checks = {
        "candidate_score": round(float(catalyst_theme_candidate_score_min), 4),
        "breakout_freshness": round(float(catalyst_theme_breakout_min), 4),
        "close_strength": round(float(catalyst_theme_close_min), 4),
        "quality_score": round(float(catalyst_theme_quality_min), 4),
        "sector_resonance": effective_sector_min,
        "catalyst_freshness": round(float(catalyst_theme_catalyst_min), 4),
    }
    threshold_metric_values = {
        "candidate_score": candidate_score,
        "breakout_freshness": breakout_freshness,
        "close_strength": close_strength,
        "quality_score": quality_score,
        "sector_resonance": sector_resonance,
        "catalyst_freshness": effective_catalyst_freshness,
    }
    metrics_payload = build_catalyst_theme_metrics_payload(
        gate_status=gate_status,
        blockers=blockers,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        quality_score=quality_score,
        sector_resonance=sector_resonance,
        catalyst_freshness=catalyst_freshness,
        candidate_score=candidate_score,
        effective_catalyst_freshness=effective_catalyst_freshness,
        close_momentum_catalyst_relief=close_momentum_catalyst_relief,
        threshold_checks=threshold_checks,
        threshold_metric_values=threshold_metric_values,
        theme_tags=build_catalyst_theme_tags(
            catalyst_freshness=catalyst_freshness,
            catalyst_freshness_min=catalyst_theme_catalyst_min,
            breakout_freshness=breakout_freshness,
            close_strength=close_strength,
            sector_resonance=sector_resonance,
            close_momentum_catalyst_relief_applied=bool(close_momentum_catalyst_relief.get("applied")),
        ),
    )
    filter_reason = resolve_catalyst_theme_filter_reason(
        gate_status=gate_status,
        effective_catalyst_freshness=effective_catalyst_freshness,
        catalyst_freshness_min=catalyst_theme_catalyst_min,
        quality_score=quality_score,
        quality_score_min=catalyst_theme_quality_min,
        sector_resonance=sector_resonance,
        effective_sector_min=effective_sector_min,
        close_strength=close_strength,
        close_strength_min=catalyst_theme_close_min,
        breakout_freshness=breakout_freshness,
        breakout_freshness_min=catalyst_theme_breakout_min,
        candidate_score=candidate_score,
        candidate_score_min=catalyst_theme_candidate_score_min,
    )
    return filter_reason == "catalyst_theme_candidate_score_ranked", filter_reason, metrics_payload
