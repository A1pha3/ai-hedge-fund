from __future__ import annotations

from typing import Any


def build_short_trade_target_snapshot_payload(
    *,
    profile: Any,
    signal_snapshot: dict[str, Any],
    relief_snapshot: dict[str, Any],
    labels_and_gates: dict[str, Any],
) -> dict[str, Any]:
    snapshot_views = _build_short_trade_snapshot_payload_views(
        signal_snapshot=signal_snapshot,
        relief_snapshot=relief_snapshot,
    )

    payload = {
        "profile": profile,
        "breakout_freshness": relief_snapshot["breakout_freshness"],
        "trend_acceleration": relief_snapshot["trend_acceleration"],
        "volume_expansion_quality": relief_snapshot["volume_expansion_quality"],
        "close_strength": signal_snapshot["close_strength"],
        "sector_resonance": signal_snapshot["sector_resonance"],
        "raw_catalyst_freshness": signal_snapshot["raw_catalyst_freshness"],
        "catalyst_freshness": relief_snapshot["catalyst_freshness"],
        "layer_c_alignment": signal_snapshot["layer_c_alignment"],
        "effective_near_miss_threshold": relief_snapshot["effective_near_miss_threshold"],
        "effective_select_threshold": relief_snapshot["effective_select_threshold"],
        "selected_score_tolerance": relief_snapshot["selected_score_tolerance"],
        "market_state_threshold_adjustment": relief_snapshot["market_state_threshold_adjustment"],
        "layer_c_avoid_penalty": relief_snapshot["layer_c_avoid_penalty"],
        "t_plus_2_continuation_candidate": relief_snapshot["t_plus_2_continuation_candidate"],
        "visibility_gap_continuation_relief": relief_snapshot["visibility_gap_continuation_relief"],
        "merge_approved_continuation_relief": relief_snapshot["merge_approved_continuation_relief"],
        "historical_execution_relief": snapshot_views["historical_execution_relief"],
        "historical_prior": relief_snapshot["historical_prior"],
        "prepared_breakout_penalty_relief": relief_snapshot["prepared_breakout_penalty_relief"],
        "prepared_breakout_catalyst_relief": relief_snapshot["prepared_breakout_catalyst_relief"],
        "prepared_breakout_volume_relief": relief_snapshot["prepared_breakout_volume_relief"],
        "prepared_breakout_continuation_relief": relief_snapshot["prepared_breakout_continuation_relief"],
        "prepared_breakout_selected_catalyst_relief": relief_snapshot["prepared_breakout_selected_catalyst_relief"],
        "stale_trend_repair_penalty": relief_snapshot["stale_trend_repair_penalty"],
        "overhead_supply_penalty": relief_snapshot["overhead_supply_penalty"],
        "extension_without_room_penalty": relief_snapshot["extension_without_room_penalty"],
        "positive_score_weights": relief_snapshot["positive_score_weights"],
        "weighted_positive_contributions": relief_snapshot["weighted_positive_contributions"],
        "weighted_negative_contributions": relief_snapshot["weighted_negative_contributions"],
        "total_positive_contribution": relief_snapshot["total_positive_contribution"],
        "total_negative_contribution": relief_snapshot["total_negative_contribution"],
        "score_target": relief_snapshot["score_target"],
        "long_trend_strength": signal_snapshot["long_trend_strength"],
        "event_freshness_strength": signal_snapshot["event_freshness_strength"],
        "news_sentiment_strength": signal_snapshot["news_sentiment_strength"],
        "event_signal_strength": signal_snapshot["event_signal_strength"],
        "mean_reversion_strength": signal_snapshot["mean_reversion_strength"],
        "analyst_alignment": signal_snapshot["analyst_alignment"],
        "investor_alignment": signal_snapshot["investor_alignment"],
        "analyst_penalty": signal_snapshot["analyst_penalty"],
        "investor_penalty": signal_snapshot["investor_penalty"],
    }
    payload.update(_build_profitability_snapshot_payload(snapshot_views))
    payload.update(_build_catalyst_relief_snapshot_payload(snapshot_views))
    payload.update(_build_watchlist_snapshot_payload(snapshot_views, relief_snapshot))
    payload.update(_build_snapshot_labels_payload(labels_and_gates))
    payload.update(_build_signal_strength_snapshot_payload(signal_snapshot, snapshot_views))
    return payload


def _build_short_trade_snapshot_payload_views(
    *,
    signal_snapshot: dict[str, Any],
    relief_snapshot: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        "volatility_metrics": dict(signal_snapshot["volatility_metrics"]),
        "profitability_relief": dict(relief_snapshot["profitability_relief"]),
        "profitability_hard_cliff_boundary_relief": dict(relief_snapshot["profitability_hard_cliff_boundary_relief"]),
        "historical_execution_relief": dict(relief_snapshot["historical_execution_relief"]),
        "catalyst_relief": dict(relief_snapshot["upstream_shadow_catalyst_relief"]),
        "watchlist_zero_catalyst_penalty": dict(relief_snapshot["watchlist_zero_catalyst_penalty"]),
        "watchlist_zero_catalyst_crowded_penalty": dict(relief_snapshot["watchlist_zero_catalyst_crowded_penalty"]),
        "watchlist_zero_catalyst_flat_trend_penalty": dict(relief_snapshot["watchlist_zero_catalyst_flat_trend_penalty"]),
    }


def _build_profitability_snapshot_payload(snapshot_views: dict[str, dict[str, Any]]) -> dict[str, Any]:
    profitability_relief = snapshot_views["profitability_relief"]
    return {
        "profitability_hard_cliff": profitability_relief["hard_cliff"],
        "profitability_positive_count": profitability_relief["profitability_positive_count"],
        "profitability_confidence": profitability_relief["profitability_confidence"],
        "profitability_relief_enabled": profitability_relief["relief_enabled"],
        "profitability_relief_gate_hits": profitability_relief["relief_gate_hits"],
        "profitability_relief_eligible": profitability_relief["relief_eligible"],
        "profitability_relief_applied": profitability_relief["relief_applied"],
        "profitability_hard_cliff_boundary_relief": snapshot_views["profitability_hard_cliff_boundary_relief"],
        "profitability_relief_soft_penalty": profitability_relief["soft_penalty"],
        "base_layer_c_avoid_penalty": profitability_relief["base_layer_c_avoid_penalty"],
    }


def _build_catalyst_relief_snapshot_payload(snapshot_views: dict[str, dict[str, Any]]) -> dict[str, Any]:
    catalyst_relief = snapshot_views["catalyst_relief"]
    return {
        "upstream_shadow_catalyst_relief_enabled": catalyst_relief["enabled"],
        "upstream_shadow_catalyst_relief_gate_hits": catalyst_relief["gate_hits"],
        "upstream_shadow_catalyst_relief_eligible": catalyst_relief["eligible"],
        "upstream_shadow_catalyst_relief_applied": catalyst_relief["applied"],
        "upstream_shadow_catalyst_relief_reason": catalyst_relief["reason"],
        "upstream_shadow_catalyst_relief_catalyst_freshness_floor": catalyst_relief["catalyst_freshness_floor"],
        "upstream_shadow_catalyst_relief_base_near_miss_threshold": catalyst_relief["base_near_miss_threshold"],
        "upstream_shadow_catalyst_relief_near_miss_threshold_override": catalyst_relief["near_miss_threshold_override"],
        "upstream_shadow_catalyst_relief_base_select_threshold": catalyst_relief["base_select_threshold"],
        "upstream_shadow_catalyst_relief_select_threshold_override": catalyst_relief["select_threshold_override"],
        "upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff": catalyst_relief["require_no_profitability_hard_cliff"],
    }


def _build_watchlist_snapshot_payload(
    snapshot_views: dict[str, dict[str, Any]],
    relief_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return {
        "watchlist_zero_catalyst_guard": snapshot_views["watchlist_zero_catalyst_penalty"],
        "watchlist_zero_catalyst_penalty": relief_snapshot["watchlist_zero_catalyst_penalty_effective"],
        "watchlist_zero_catalyst_crowded_guard": snapshot_views["watchlist_zero_catalyst_crowded_penalty"],
        "watchlist_zero_catalyst_crowded_penalty": relief_snapshot["watchlist_zero_catalyst_crowded_penalty_effective"],
        "watchlist_zero_catalyst_flat_trend_guard": snapshot_views["watchlist_zero_catalyst_flat_trend_penalty"],
        "watchlist_zero_catalyst_flat_trend_penalty": relief_snapshot["watchlist_zero_catalyst_flat_trend_penalty_effective"],
    }


def _build_snapshot_labels_payload(labels_and_gates: dict[str, Any]) -> dict[str, Any]:
    return {
        "positive_tags": labels_and_gates["positive_tags"],
        "negative_tags": labels_and_gates["negative_tags"],
        "blockers": labels_and_gates["blockers"],
        "gate_status": labels_and_gates["gate_status"],
    }


def _build_signal_strength_snapshot_payload(
    signal_snapshot: dict[str, Any],
    snapshot_views: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    volatility_metrics = snapshot_views["volatility_metrics"]
    return {
        "score_b_strength": signal_snapshot["score_b_strength"],
        "score_c_strength": signal_snapshot["score_c_strength"],
        "score_final_strength": signal_snapshot["score_final_strength"],
        "momentum_strength": signal_snapshot["momentum_strength"],
        "momentum_1m": signal_snapshot["momentum_1m"],
        "momentum_3m": signal_snapshot["momentum_3m"],
        "momentum_6m": signal_snapshot["momentum_6m"],
        "volume_momentum": signal_snapshot["volume_momentum"],
        "adx_strength": signal_snapshot["adx_strength"],
        "ema_strength": signal_snapshot["ema_strength"],
        "volatility_strength": signal_snapshot["volatility_strength"],
        "volatility_regime": float(volatility_metrics.get("volatility_regime", 0.0) or 0.0),
        "atr_ratio": float(volatility_metrics.get("atr_ratio", 0.0) or 0.0),
    }
