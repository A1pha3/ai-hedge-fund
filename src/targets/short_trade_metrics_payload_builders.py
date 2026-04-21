"""Metrics payload builders for short trade target evaluation."""
from __future__ import annotations

from typing import Any

from src.targets.models import TargetEvaluationInput


def _build_historical_execution_relief_metrics_payload(historical_execution_relief: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(historical_execution_relief["enabled"]),
        "eligible": bool(historical_execution_relief["eligible"]),
        "applied": bool(historical_execution_relief["applied"]),
        "candidate_source": str(historical_execution_relief["candidate_source"]),
        "execution_quality_label": str(historical_execution_relief["execution_quality_label"]),
        "evaluable_count": int(historical_execution_relief["evaluable_count"]),
        "next_close_positive_rate": round(float(historical_execution_relief["next_close_positive_rate"]), 4),
        "next_high_hit_rate_at_threshold": round(float(historical_execution_relief["next_high_hit_rate_at_threshold"]), 4),
        "next_open_to_close_return_mean": round(float(historical_execution_relief["next_open_to_close_return_mean"]), 4),
        "strong_close_continuation": bool(historical_execution_relief["strong_close_continuation"]),
        "gate_hits": dict(historical_execution_relief["gate_hits"]),
        "base_near_miss_threshold": round(float(historical_execution_relief["base_near_miss_threshold"]), 4),
        "effective_near_miss_threshold": round(float(historical_execution_relief["effective_near_miss_threshold"]), 4),
        "near_miss_threshold_override": round(float(historical_execution_relief["near_miss_threshold_override"]), 4),
        "base_select_threshold": round(float(historical_execution_relief["base_select_threshold"]), 4),
        "effective_select_threshold": round(float(historical_execution_relief["effective_select_threshold"]), 4),
        "select_threshold_override": round(float(historical_execution_relief["select_threshold_override"]), 4),
        "profitability_hard_cliff_bypassed": bool(historical_execution_relief.get("profitability_hard_cliff_bypassed", False)),
    }


def _build_carryover_evidence_deficiency_metrics_payload(carryover_evidence_deficiency: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(carryover_evidence_deficiency["enabled"]),
        "evidence_deficient": bool(carryover_evidence_deficiency["evidence_deficient"]),
        "gate_hits": dict(carryover_evidence_deficiency["gate_hits"]),
        "same_ticker_sample_count": int(carryover_evidence_deficiency["same_ticker_sample_count"]),
        "same_family_sample_count": int(carryover_evidence_deficiency["same_family_sample_count"]),
        "same_family_source_sample_count": int(carryover_evidence_deficiency["same_family_source_sample_count"]),
        "same_family_source_score_catalyst_sample_count": int(carryover_evidence_deficiency["same_family_source_score_catalyst_sample_count"]),
        "same_source_score_sample_count": int(carryover_evidence_deficiency["same_source_score_sample_count"]),
        "evaluable_count": int(carryover_evidence_deficiency["evaluable_count"]),
    }


def _build_selected_historical_proof_deficiency_metrics_payload(selected_historical_proof_deficiency: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(selected_historical_proof_deficiency["enabled"]),
        "proof_missing": bool(selected_historical_proof_deficiency["proof_missing"]),
        "gate_hits": dict(selected_historical_proof_deficiency["gate_hits"]),
        "candidate_source": str(selected_historical_proof_deficiency["candidate_source"]),
        "evaluable_count": int(selected_historical_proof_deficiency["evaluable_count"]),
    }


def _build_profitability_metrics_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "profitability_hard_cliff": bool(snapshot["profitability_hard_cliff"]),
        "profitability_positive_count": snapshot["profitability_positive_count"],
        "profitability_confidence": round(float(snapshot["profitability_confidence"]), 4),
        "profitability_relief_enabled": bool(snapshot["profitability_relief_enabled"]),
        "profitability_relief_gate_hits": dict(snapshot["profitability_relief_gate_hits"]),
        "profitability_relief_eligible": bool(snapshot["profitability_relief_eligible"]),
        "profitability_relief_applied": bool(snapshot["profitability_relief_applied"]),
        "base_layer_c_avoid_penalty": round(float(snapshot["base_layer_c_avoid_penalty"]), 4),
        "profitability_relief_soft_penalty": round(float(snapshot["profitability_relief_soft_penalty"]), 4),
        "layer_c_avoid_penalty": round(float(snapshot["layer_c_avoid_penalty"]), 4),
    }


def _build_profitability_hard_cliff_boundary_relief_metrics_payload(profitability_hard_cliff_boundary_relief: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(profitability_hard_cliff_boundary_relief["enabled"]),
        "eligible": bool(profitability_hard_cliff_boundary_relief["eligible"]),
        "applied": bool(profitability_hard_cliff_boundary_relief["applied"]),
        "candidate_source": str(profitability_hard_cliff_boundary_relief["candidate_source"]),
        "gate_hits": dict(profitability_hard_cliff_boundary_relief["gate_hits"]),
        "base_near_miss_threshold": round(float(profitability_hard_cliff_boundary_relief["base_near_miss_threshold"]), 4),
        "effective_near_miss_threshold": round(float(profitability_hard_cliff_boundary_relief["effective_near_miss_threshold"]), 4),
        "near_miss_threshold_override": round(float(profitability_hard_cliff_boundary_relief["near_miss_threshold_override"]), 4),
    }


def _build_t_plus_2_continuation_candidate_metrics_payload(t_plus_2_continuation_candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(t_plus_2_continuation_candidate["enabled"]),
        "eligible": bool(t_plus_2_continuation_candidate["eligible"]),
        "applied": bool(t_plus_2_continuation_candidate["applied"]),
        "candidate_source": str(t_plus_2_continuation_candidate["candidate_source"]),
        "gate_hits": dict(t_plus_2_continuation_candidate["gate_hits"]),
    }


def _build_watchlist_guard_metrics_payload(watchlist_guard: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(watchlist_guard["enabled"]),
        "eligible": bool(watchlist_guard["eligible"]),
        "applied": bool(watchlist_guard["applied"]),
        "candidate_source": str(watchlist_guard["candidate_source"]),
        "gate_hits": dict(watchlist_guard["gate_hits"]),
    }


def _build_market_state_threshold_adjustment_metrics_payload(market_state_threshold_adjustment: dict[str, Any]) -> dict[str, Any]:
    payload = dict(market_state_threshold_adjustment or {})
    return {
        "enabled": bool(payload.get("enabled", False)),
        "risk_level": str(payload.get("risk_level") or "unknown"),
        "breadth_ratio": payload.get("breadth_ratio"),
        "position_scale": payload.get("position_scale"),
        "regime_gate_level": str(payload.get("regime_gate_level") or "unknown"),
        "regime_gate_reasons": list(payload.get("regime_gate_reasons") or []),
        "style_dispersion": round(float(payload.get("style_dispersion", 0.0) or 0.0), 4),
        "regime_flip_risk": round(float(payload.get("regime_flip_risk", 0.0) or 0.0), 4),
        "execution_hard_gate": bool(payload.get("execution_hard_gate", False)),
        "select_threshold_lift": round(float(payload.get("select_threshold_lift", 0.0) or 0.0), 4),
        "near_miss_threshold_lift": round(float(payload.get("near_miss_threshold_lift", 0.0) or 0.0), 4),
        "effective_select_threshold": round(float(payload.get("effective_select_threshold", 0.0) or 0.0), 4),
        "effective_near_miss_threshold": round(float(payload.get("effective_near_miss_threshold", 0.0) or 0.0), 4),
    }


def _build_breakout_trap_guard_metrics_payload(breakout_trap_guard: dict[str, Any]) -> dict[str, Any]:
    payload = dict(breakout_trap_guard or {})
    return {
        "enabled": bool(payload.get("enabled", False)),
        "eligible": bool(payload.get("eligible", False)),
        "applied": bool(payload.get("applied", False)),
        "blocked": bool(payload.get("blocked", False)),
        "execution_blocked": bool(payload.get("execution_blocked", False)),
        "candidate_source": str(payload.get("candidate_source") or ""),
        "regime_gate_level": str(payload.get("regime_gate_level") or "unknown"),
        "regime_gate_reasons": list(payload.get("regime_gate_reasons") or []),
        "style_dispersion": round(float(payload.get("style_dispersion", 0.0) or 0.0), 4),
        "regime_flip_risk": round(float(payload.get("regime_flip_risk", 0.0) or 0.0), 4),
        "breakout_pressure": round(float(payload.get("breakout_pressure", 0.0) or 0.0), 4),
        "close_retention_score": round(float(payload.get("close_retention_score", 0.0) or 0.0), 4),
        "close_failure_gap": round(float(payload.get("close_failure_gap", 0.0) or 0.0), 4),
        "stale_catalyst_pressure": round(float(payload.get("stale_catalyst_pressure", 0.0) or 0.0), 4),
        "hostile_volatility": round(float(payload.get("hostile_volatility", 0.0) or 0.0), 4),
        "historical_gap_chase_risk": round(float(payload.get("historical_gap_chase_risk", 0.0) or 0.0), 4),
        "risk": round(float(payload.get("risk", 0.0) or 0.0), 4),
        "penalty": round(float(payload.get("penalty", 0.0) or 0.0), 4),
        "block_threshold": round(float(payload.get("block_threshold", 0.0) or 0.0), 4),
        "execution_block_threshold": round(float(payload.get("execution_block_threshold", 0.0) or 0.0), 4),
        "gate_hits": dict(payload.get("gate_hits") or {}),
    }


def _build_watchlist_metrics_payload(
    *,
    snapshot: dict[str, Any],
    t_plus_2_continuation_candidate: dict[str, Any],
    catalyst_theme_guard: dict[str, Any],
    watchlist_zero_catalyst_guard: dict[str, Any],
    watchlist_zero_catalyst_crowded_guard: dict[str, Any],
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any],
    watchlist_filter_diagnostics_flat_trend_guard: dict[str, Any],
) -> dict[str, Any]:
    return {
        "catalyst_theme_penalty": round(float(snapshot["catalyst_theme_penalty"]), 4),
        "watchlist_zero_catalyst_penalty": round(float(snapshot["watchlist_zero_catalyst_penalty"]), 4),
        "watchlist_zero_catalyst_crowded_penalty": round(float(snapshot["watchlist_zero_catalyst_crowded_penalty"]), 4),
        "watchlist_zero_catalyst_flat_trend_penalty": round(float(snapshot["watchlist_zero_catalyst_flat_trend_penalty"]), 4),
        "watchlist_filter_diagnostics_flat_trend_penalty": round(float(snapshot["watchlist_filter_diagnostics_flat_trend_penalty"]), 4),
        "t_plus_2_continuation_candidate": _build_t_plus_2_continuation_candidate_metrics_payload(t_plus_2_continuation_candidate),
        "catalyst_theme_guard": _build_watchlist_guard_metrics_payload(catalyst_theme_guard),
        "watchlist_zero_catalyst_guard": _build_watchlist_guard_metrics_payload(watchlist_zero_catalyst_guard),
        "watchlist_zero_catalyst_crowded_guard": _build_watchlist_guard_metrics_payload(watchlist_zero_catalyst_crowded_guard),
        "watchlist_zero_catalyst_flat_trend_guard": _build_watchlist_guard_metrics_payload(watchlist_zero_catalyst_flat_trend_guard),
        "watchlist_filter_diagnostics_flat_trend_guard": _build_watchlist_guard_metrics_payload(watchlist_filter_diagnostics_flat_trend_guard),
    }


def _build_prepared_breakout_penalty_relief_metrics_payload(prepared_breakout_penalty_relief: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(prepared_breakout_penalty_relief["enabled"]),
        "eligible": bool(prepared_breakout_penalty_relief["eligible"]),
        "applied": bool(prepared_breakout_penalty_relief["applied"]),
        "candidate_source": str(prepared_breakout_penalty_relief["candidate_source"]),
        "breakout_stage": str(prepared_breakout_penalty_relief["breakout_stage"]),
        "gate_hits": dict(prepared_breakout_penalty_relief["gate_hits"]),
        "base_positive_score_weights": {name: round(float(value), 4) for name, value in dict(prepared_breakout_penalty_relief["base_positive_score_weights"]).items()},
        "effective_positive_score_weights": {name: round(float(value), 4) for name, value in dict(prepared_breakout_penalty_relief["effective_positive_score_weights"]).items()},
        "base_stale_score_penalty_weight": round(float(prepared_breakout_penalty_relief["base_stale_score_penalty_weight"]), 4),
        "effective_stale_score_penalty_weight": round(float(prepared_breakout_penalty_relief["effective_stale_score_penalty_weight"]), 4),
        "base_extension_score_penalty_weight": round(float(prepared_breakout_penalty_relief["base_extension_score_penalty_weight"]), 4),
        "effective_extension_score_penalty_weight": round(float(prepared_breakout_penalty_relief["effective_extension_score_penalty_weight"]), 4),
    }


def _build_prepared_breakout_catalyst_relief_metrics_payload(prepared_breakout_catalyst_relief: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(prepared_breakout_catalyst_relief["enabled"]),
        "eligible": bool(prepared_breakout_catalyst_relief["eligible"]),
        "applied": bool(prepared_breakout_catalyst_relief["applied"]),
        "candidate_source": str(prepared_breakout_catalyst_relief["candidate_source"]),
        "breakout_stage": str(prepared_breakout_catalyst_relief["breakout_stage"]),
        "gate_hits": dict(prepared_breakout_catalyst_relief["gate_hits"]),
        "base_catalyst_freshness": round(float(prepared_breakout_catalyst_relief["base_catalyst_freshness"]), 4),
        "effective_catalyst_freshness": round(float(prepared_breakout_catalyst_relief["effective_catalyst_freshness"]), 4),
        "catalyst_freshness_floor": round(float(prepared_breakout_catalyst_relief["catalyst_freshness_floor"]), 4),
    }


def _build_prepared_breakout_volume_relief_metrics_payload(prepared_breakout_volume_relief: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(prepared_breakout_volume_relief["enabled"]),
        "eligible": bool(prepared_breakout_volume_relief["eligible"]),
        "applied": bool(prepared_breakout_volume_relief["applied"]),
        "candidate_source": str(prepared_breakout_volume_relief["candidate_source"]),
        "breakout_stage": str(prepared_breakout_volume_relief["breakout_stage"]),
        "gate_hits": dict(prepared_breakout_volume_relief["gate_hits"]),
        "base_volume_expansion_quality": round(float(prepared_breakout_volume_relief["base_volume_expansion_quality"]), 4),
        "effective_volume_expansion_quality": round(float(prepared_breakout_volume_relief["effective_volume_expansion_quality"]), 4),
        "volatility_regime": round(float(prepared_breakout_volume_relief["volatility_regime"]), 4),
        "atr_ratio": round(float(prepared_breakout_volume_relief["atr_ratio"]), 4),
        "volume_expansion_quality_floor": round(float(prepared_breakout_volume_relief["volume_expansion_quality_floor"]), 4),
    }


def _build_prepared_breakout_continuation_relief_metrics_payload(prepared_breakout_continuation_relief: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(prepared_breakout_continuation_relief["enabled"]),
        "eligible": bool(prepared_breakout_continuation_relief["eligible"]),
        "applied": bool(prepared_breakout_continuation_relief["applied"]),
        "candidate_source": str(prepared_breakout_continuation_relief["candidate_source"]),
        "breakout_stage": str(prepared_breakout_continuation_relief["breakout_stage"]),
        "gate_hits": dict(prepared_breakout_continuation_relief["gate_hits"]),
        "base_breakout_freshness": round(float(prepared_breakout_continuation_relief["base_breakout_freshness"]), 4),
        "effective_breakout_freshness": round(float(prepared_breakout_continuation_relief["effective_breakout_freshness"]), 4),
        "base_trend_acceleration": round(float(prepared_breakout_continuation_relief["base_trend_acceleration"]), 4),
        "effective_trend_acceleration": round(float(prepared_breakout_continuation_relief["effective_trend_acceleration"]), 4),
        "momentum_1m": round(float(prepared_breakout_continuation_relief["momentum_1m"]), 4),
        "momentum_3m": round(float(prepared_breakout_continuation_relief["momentum_3m"]), 4),
        "momentum_6m": round(float(prepared_breakout_continuation_relief["momentum_6m"]), 4),
        "volume_momentum": round(float(prepared_breakout_continuation_relief["volume_momentum"]), 4),
        "continuation_support": round(float(prepared_breakout_continuation_relief["continuation_support"]), 4),
        "breakout_freshness_floor": round(float(prepared_breakout_continuation_relief["breakout_freshness_floor"]), 4),
        "trend_acceleration_floor": round(float(prepared_breakout_continuation_relief["trend_acceleration_floor"]), 4),
    }


def _build_prepared_breakout_selected_catalyst_relief_metrics_payload(prepared_breakout_selected_catalyst_relief: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(prepared_breakout_selected_catalyst_relief["enabled"]),
        "eligible": bool(prepared_breakout_selected_catalyst_relief["eligible"]),
        "applied": bool(prepared_breakout_selected_catalyst_relief["applied"]),
        "candidate_source": str(prepared_breakout_selected_catalyst_relief["candidate_source"]),
        "breakout_stage": str(prepared_breakout_selected_catalyst_relief["breakout_stage"]),
        "gate_hits": dict(prepared_breakout_selected_catalyst_relief["gate_hits"]),
        "base_breakout_freshness": round(float(prepared_breakout_selected_catalyst_relief["base_breakout_freshness"]), 4),
        "effective_breakout_freshness": round(float(prepared_breakout_selected_catalyst_relief["effective_breakout_freshness"]), 4),
        "base_catalyst_freshness": round(float(prepared_breakout_selected_catalyst_relief["base_catalyst_freshness"]), 4),
        "effective_catalyst_freshness": round(float(prepared_breakout_selected_catalyst_relief["effective_catalyst_freshness"]), 4),
        "selected_breakout_freshness_floor": round(float(prepared_breakout_selected_catalyst_relief["selected_breakout_freshness_floor"]), 4),
        "catalyst_freshness_floor": round(float(prepared_breakout_selected_catalyst_relief["catalyst_freshness_floor"]), 4),
    }


def _build_prepared_breakout_metrics_payload(
    *,
    prepared_breakout_penalty_relief: dict[str, Any],
    prepared_breakout_catalyst_relief: dict[str, Any],
    prepared_breakout_volume_relief: dict[str, Any],
    prepared_breakout_continuation_relief: dict[str, Any],
    prepared_breakout_selected_catalyst_relief: dict[str, Any],
) -> dict[str, Any]:
    return {
        "prepared_breakout_penalty_relief": _build_prepared_breakout_penalty_relief_metrics_payload(prepared_breakout_penalty_relief),
        "prepared_breakout_catalyst_relief": _build_prepared_breakout_catalyst_relief_metrics_payload(prepared_breakout_catalyst_relief),
        "prepared_breakout_volume_relief": _build_prepared_breakout_volume_relief_metrics_payload(prepared_breakout_volume_relief),
        "prepared_breakout_continuation_relief": _build_prepared_breakout_continuation_relief_metrics_payload(prepared_breakout_continuation_relief),
        "prepared_breakout_selected_catalyst_relief": _build_prepared_breakout_selected_catalyst_relief_metrics_payload(prepared_breakout_selected_catalyst_relief),
    }


def _build_short_trade_threshold_core_metrics_payload(*, profile: Any, snapshot: dict[str, Any], positive_score_weights: dict[str, float]) -> dict[str, Any]:
    return {
        "profile_name": profile.name,
        "select_threshold": round(float(profile.select_threshold), 4),
        "effective_select_threshold": round(float(snapshot["effective_select_threshold"]), 4),
        "selected_score_tolerance": round(float(snapshot["selected_score_tolerance"]), 4),
        "near_miss_threshold": round(float(snapshot["effective_near_miss_threshold"]), 4),
        "base_near_miss_threshold": round(float(profile.near_miss_threshold), 4),
        "selected_breakout_freshness_min": round(float(profile.selected_breakout_freshness_min), 4),
        "selected_trend_acceleration_min": round(float(profile.selected_trend_acceleration_min), 4),
        "near_miss_breakout_freshness_min": round(float(profile.near_miss_breakout_freshness_min), 4),
        "near_miss_trend_acceleration_min": round(float(profile.near_miss_trend_acceleration_min), 4),
        "breakout_freshness_weight": round(float(profile.breakout_freshness_weight), 4),
        "trend_acceleration_weight": round(float(profile.trend_acceleration_weight), 4),
        "volume_expansion_quality_weight": round(float(profile.volume_expansion_quality_weight), 4),
        "close_strength_weight": round(float(profile.close_strength_weight), 4),
        "sector_resonance_weight": round(float(profile.sector_resonance_weight), 4),
        "catalyst_freshness_weight": round(float(profile.catalyst_freshness_weight), 4),
        "layer_c_alignment_weight": round(float(profile.layer_c_alignment_weight), 4),
        "historical_continuation_score_weight": round(float(getattr(profile, "historical_continuation_score_weight", 0.0) or 0.0), 4),
        "momentum_strength_weight": round(float(getattr(profile, "momentum_strength_weight", 0.0)), 4),
        "short_term_reversal_weight": round(float(getattr(profile, "short_term_reversal_weight", 0.0)), 4),
        "intraday_strength_weight": round(float(getattr(profile, "intraday_strength_weight", 0.0)), 4),
        "reversal_2d_weight": round(float(getattr(profile, "reversal_2d_weight", 0.0)), 4),
        "effective_positive_score_weights": {name: round(float(value), 4) for name, value in positive_score_weights.items()},
        "stale_penalty_block_threshold": round(float(profile.stale_penalty_block_threshold), 4),
        "overhead_penalty_block_threshold": round(float(profile.overhead_penalty_block_threshold), 4),
        "extension_penalty_block_threshold": round(float(profile.extension_penalty_block_threshold), 4),
        "layer_c_avoid_penalty": round(float(profile.layer_c_avoid_penalty), 4),
        "rank_threshold_tightening": dict(snapshot.get("rank_threshold_tightening") or {}),
        "rank_decision_cap": dict(snapshot.get("rank_decision_cap") or {}),
        "selected_rank_cap_relief_score_margin_min": round(float(getattr(profile, "selected_rank_cap_relief_score_margin_min", 0.0)), 4),
        "selected_rank_cap_relief_rank_buffer": int(getattr(profile, "selected_rank_cap_relief_rank_buffer", 0) or 0),
        "selected_rank_cap_relief_rank_buffer_ratio": round(float(getattr(profile, "selected_rank_cap_relief_rank_buffer_ratio", 0.0) or 0.0), 4),
        "selected_rank_cap_relief_sector_resonance_min": round(float(getattr(profile, "selected_rank_cap_relief_sector_resonance_min", 0.0) or 0.0), 4),
        "liquidity_shadow_selected_rank_cap_ratio": None if getattr(profile, "liquidity_shadow_selected_rank_cap_ratio", None) is None else round(float(getattr(profile, "liquidity_shadow_selected_rank_cap_ratio", 0.0) or 0.0), 4),
        "liquidity_shadow_near_miss_rank_cap_ratio": None if getattr(profile, "liquidity_shadow_near_miss_rank_cap_ratio", None) is None else round(float(getattr(profile, "liquidity_shadow_near_miss_rank_cap_ratio", 0.0) or 0.0), 4),
        "liquidity_shadow_source_specific_rank_cap_require_relief_applied": bool(getattr(profile, "liquidity_shadow_source_specific_rank_cap_require_relief_applied", True)),
        "selected_rank_cap_relief_catalyst_theme_research_enabled": bool(getattr(profile, "selected_rank_cap_relief_catalyst_theme_research_enabled", False)),
        "selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_min": round(float(getattr(profile, "selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_min", 0.0) or 0.0), 4),
        "selected_rank_cap_relief_catalyst_theme_research_sector_resonance_min": round(float(getattr(profile, "selected_rank_cap_relief_catalyst_theme_research_sector_resonance_min", 0.0) or 0.0), 4),
        "selected_rank_cap_relief_catalyst_theme_research_close_strength_max": round(float(getattr(profile, "selected_rank_cap_relief_catalyst_theme_research_close_strength_max", 1.0) or 1.0), 4),
        "catalyst_theme_source_specific_rank_cap_close_strength_min": round(float(getattr(profile, "catalyst_theme_source_specific_rank_cap_close_strength_min", 0.0) or 0.0), 4),
        "selected_rank_cap_relief_require_confirmed_breakout": bool(getattr(profile, "selected_rank_cap_relief_require_confirmed_breakout", False)),
        "selected_rank_cap_relief_require_t_plus_2_candidate": bool(getattr(profile, "selected_rank_cap_relief_require_t_plus_2_candidate", False)),
        "selected_rank_cap_relief_allow_risk_off": bool(getattr(profile, "selected_rank_cap_relief_allow_risk_off", True)),
        "selected_rank_cap_relief_allow_crisis": bool(getattr(profile, "selected_rank_cap_relief_allow_crisis", True)),
        "market_state_threshold_adjustment": dict(snapshot.get("market_state_threshold_adjustment") or {}),
        "selected_close_retention_min": round(float(getattr(profile, "selected_close_retention_min", 0.0) or 0.0), 4),
        "selected_close_retention_threshold_lift": round(float(getattr(profile, "selected_close_retention_threshold_lift", 0.0) or 0.0), 4),
        "selected_breakout_close_gap_max": round(float(getattr(profile, "selected_breakout_close_gap_max", 1.0) or 1.0), 4),
        "selected_breakout_close_gap_threshold_lift": round(float(getattr(profile, "selected_breakout_close_gap_threshold_lift", 0.0) or 0.0), 4),
        "selected_close_retention_penalty_weight": round(float(getattr(profile, "selected_close_retention_penalty_weight", 0.0) or 0.0), 4),
        "selected_close_retention_adjustment": dict(snapshot.get("selected_close_retention_adjustment") or {}),
    }


def _build_short_trade_threshold_profitability_metrics_payload(profile: Any) -> dict[str, Any]:
    return {
        "profitability_relief_enabled": bool(profile.profitability_relief_enabled),
        "profitability_relief_breakout_freshness_min": round(float(profile.profitability_relief_breakout_freshness_min), 4),
        "profitability_relief_catalyst_freshness_min": round(float(profile.profitability_relief_catalyst_freshness_min), 4),
        "profitability_relief_sector_resonance_min": round(float(profile.profitability_relief_sector_resonance_min), 4),
        "profitability_relief_avoid_penalty": round(float(profile.profitability_relief_avoid_penalty), 4),
        "profitability_hard_cliff_boundary_relief_enabled": bool(profile.profitability_hard_cliff_boundary_relief_enabled),
        "profitability_hard_cliff_boundary_relief_breakout_freshness_min": round(float(profile.profitability_hard_cliff_boundary_relief_breakout_freshness_min), 4),
        "profitability_hard_cliff_boundary_relief_trend_acceleration_min": round(float(profile.profitability_hard_cliff_boundary_relief_trend_acceleration_min), 4),
        "profitability_hard_cliff_boundary_relief_catalyst_freshness_min": round(float(profile.profitability_hard_cliff_boundary_relief_catalyst_freshness_min), 4),
        "profitability_hard_cliff_boundary_relief_sector_resonance_min": round(float(profile.profitability_hard_cliff_boundary_relief_sector_resonance_min), 4),
        "profitability_hard_cliff_boundary_relief_close_strength_min": round(float(profile.profitability_hard_cliff_boundary_relief_close_strength_min), 4),
        "profitability_hard_cliff_boundary_relief_stale_penalty_max": round(float(profile.profitability_hard_cliff_boundary_relief_stale_penalty_max), 4),
        "profitability_hard_cliff_boundary_relief_extension_penalty_max": round(float(profile.profitability_hard_cliff_boundary_relief_extension_penalty_max), 4),
        "profitability_hard_cliff_boundary_relief_near_miss_threshold": round(float(profile.profitability_hard_cliff_boundary_relief_near_miss_threshold), 4),
    }


def _build_prepared_breakout_penalty_threshold_metrics_payload(profile: Any) -> dict[str, Any]:
    return {
        "prepared_breakout_penalty_relief_enabled": bool(profile.prepared_breakout_penalty_relief_enabled),
        "prepared_breakout_penalty_relief_breakout_freshness_max": round(float(profile.prepared_breakout_penalty_relief_breakout_freshness_max), 4),
        "prepared_breakout_penalty_relief_trend_acceleration_min": round(float(profile.prepared_breakout_penalty_relief_trend_acceleration_min), 4),
        "prepared_breakout_penalty_relief_close_strength_min": round(float(profile.prepared_breakout_penalty_relief_close_strength_min), 4),
        "prepared_breakout_penalty_relief_sector_resonance_min": round(float(profile.prepared_breakout_penalty_relief_sector_resonance_min), 4),
        "prepared_breakout_penalty_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_penalty_relief_layer_c_alignment_min), 4),
        "prepared_breakout_penalty_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_penalty_relief_catalyst_freshness_max), 4),
        "prepared_breakout_penalty_relief_long_trend_strength_min": round(float(profile.prepared_breakout_penalty_relief_long_trend_strength_min), 4),
        "prepared_breakout_penalty_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_penalty_relief_mean_reversion_strength_max), 4),
        "prepared_breakout_penalty_relief_breakout_freshness_weight": round(float(profile.prepared_breakout_penalty_relief_breakout_freshness_weight), 4),
        "prepared_breakout_penalty_relief_trend_acceleration_weight": round(float(profile.prepared_breakout_penalty_relief_trend_acceleration_weight), 4),
        "prepared_breakout_penalty_relief_volume_expansion_quality_weight": round(float(profile.prepared_breakout_penalty_relief_volume_expansion_quality_weight), 4),
        "prepared_breakout_penalty_relief_close_strength_weight": round(float(profile.prepared_breakout_penalty_relief_close_strength_weight), 4),
        "prepared_breakout_penalty_relief_sector_resonance_weight": round(float(profile.prepared_breakout_penalty_relief_sector_resonance_weight), 4),
        "prepared_breakout_penalty_relief_catalyst_freshness_weight": round(float(profile.prepared_breakout_penalty_relief_catalyst_freshness_weight), 4),
        "prepared_breakout_penalty_relief_layer_c_alignment_weight": round(float(profile.prepared_breakout_penalty_relief_layer_c_alignment_weight), 4),
        "prepared_breakout_penalty_relief_stale_score_penalty_weight": round(float(profile.prepared_breakout_penalty_relief_stale_score_penalty_weight), 4),
        "prepared_breakout_penalty_relief_extension_score_penalty_weight": round(float(profile.prepared_breakout_penalty_relief_extension_score_penalty_weight), 4),
    }


def _build_prepared_breakout_catalyst_threshold_metrics_payload(profile: Any) -> dict[str, Any]:
    return {
        "prepared_breakout_catalyst_relief_enabled": bool(profile.prepared_breakout_catalyst_relief_enabled),
        "prepared_breakout_catalyst_relief_breakout_freshness_max": round(float(profile.prepared_breakout_catalyst_relief_breakout_freshness_max), 4),
        "prepared_breakout_catalyst_relief_trend_acceleration_min": round(float(profile.prepared_breakout_catalyst_relief_trend_acceleration_min), 4),
        "prepared_breakout_catalyst_relief_close_strength_min": round(float(profile.prepared_breakout_catalyst_relief_close_strength_min), 4),
        "prepared_breakout_catalyst_relief_sector_resonance_min": round(float(profile.prepared_breakout_catalyst_relief_sector_resonance_min), 4),
        "prepared_breakout_catalyst_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_catalyst_relief_layer_c_alignment_min), 4),
        "prepared_breakout_catalyst_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_max), 4),
        "prepared_breakout_catalyst_relief_long_trend_strength_min": round(float(profile.prepared_breakout_catalyst_relief_long_trend_strength_min), 4),
        "prepared_breakout_catalyst_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_catalyst_relief_mean_reversion_strength_max), 4),
        "prepared_breakout_catalyst_relief_catalyst_freshness_floor": round(float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_floor), 4),
    }


def _build_prepared_breakout_volume_threshold_metrics_payload(profile: Any) -> dict[str, Any]:
    return {
        "prepared_breakout_volume_relief_enabled": bool(profile.prepared_breakout_volume_relief_enabled),
        "prepared_breakout_volume_relief_breakout_freshness_max": round(float(profile.prepared_breakout_volume_relief_breakout_freshness_max), 4),
        "prepared_breakout_volume_relief_trend_acceleration_min": round(float(profile.prepared_breakout_volume_relief_trend_acceleration_min), 4),
        "prepared_breakout_volume_relief_close_strength_min": round(float(profile.prepared_breakout_volume_relief_close_strength_min), 4),
        "prepared_breakout_volume_relief_sector_resonance_min": round(float(profile.prepared_breakout_volume_relief_sector_resonance_min), 4),
        "prepared_breakout_volume_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_volume_relief_layer_c_alignment_min), 4),
        "prepared_breakout_volume_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_volume_relief_catalyst_freshness_max), 4),
        "prepared_breakout_volume_relief_long_trend_strength_min": round(float(profile.prepared_breakout_volume_relief_long_trend_strength_min), 4),
        "prepared_breakout_volume_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_volume_relief_mean_reversion_strength_max), 4),
        "prepared_breakout_volume_relief_volatility_strength_max": round(float(profile.prepared_breakout_volume_relief_volatility_strength_max), 4),
        "prepared_breakout_volume_relief_volatility_regime_min": round(float(profile.prepared_breakout_volume_relief_volatility_regime_min), 4),
        "prepared_breakout_volume_relief_atr_ratio_min": round(float(profile.prepared_breakout_volume_relief_atr_ratio_min), 4),
        "prepared_breakout_volume_relief_volume_expansion_quality_floor": round(float(profile.prepared_breakout_volume_relief_volume_expansion_quality_floor), 4),
    }


def _build_prepared_breakout_continuation_threshold_metrics_payload(profile: Any) -> dict[str, Any]:
    return {
        "prepared_breakout_continuation_relief_enabled": bool(profile.prepared_breakout_continuation_relief_enabled),
        "prepared_breakout_continuation_relief_breakout_freshness_max": round(float(profile.prepared_breakout_continuation_relief_breakout_freshness_max), 4),
        "prepared_breakout_continuation_relief_trend_acceleration_min": round(float(profile.prepared_breakout_continuation_relief_trend_acceleration_min), 4),
        "prepared_breakout_continuation_relief_trend_acceleration_max": round(float(profile.prepared_breakout_continuation_relief_trend_acceleration_max), 4),
        "prepared_breakout_continuation_relief_close_strength_min": round(float(profile.prepared_breakout_continuation_relief_close_strength_min), 4),
        "prepared_breakout_continuation_relief_sector_resonance_min": round(float(profile.prepared_breakout_continuation_relief_sector_resonance_min), 4),
        "prepared_breakout_continuation_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_continuation_relief_layer_c_alignment_min), 4),
        "prepared_breakout_continuation_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_continuation_relief_catalyst_freshness_max), 4),
        "prepared_breakout_continuation_relief_long_trend_strength_min": round(float(profile.prepared_breakout_continuation_relief_long_trend_strength_min), 4),
        "prepared_breakout_continuation_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_continuation_relief_mean_reversion_strength_max), 4),
        "prepared_breakout_continuation_relief_momentum_1m_max": round(float(profile.prepared_breakout_continuation_relief_momentum_1m_max), 4),
        "prepared_breakout_continuation_relief_continuation_support_min": round(float(profile.prepared_breakout_continuation_relief_continuation_support_min), 4),
        "prepared_breakout_continuation_relief_breakout_freshness_floor": round(float(profile.prepared_breakout_continuation_relief_breakout_freshness_floor), 4),
        "prepared_breakout_continuation_relief_trend_acceleration_floor": round(float(profile.prepared_breakout_continuation_relief_trend_acceleration_floor), 4),
    }


def _build_prepared_breakout_selected_catalyst_threshold_metrics_payload(profile: Any) -> dict[str, Any]:
    return {
        "prepared_breakout_selected_catalyst_relief_enabled": bool(profile.prepared_breakout_selected_catalyst_relief_enabled),
        "prepared_breakout_selected_catalyst_relief_breakout_freshness_min": round(float(profile.prepared_breakout_selected_catalyst_relief_breakout_freshness_min), 4),
        "prepared_breakout_selected_catalyst_relief_trend_acceleration_min": round(float(profile.prepared_breakout_selected_catalyst_relief_trend_acceleration_min), 4),
        "prepared_breakout_selected_catalyst_relief_close_strength_min": round(float(profile.prepared_breakout_selected_catalyst_relief_close_strength_min), 4),
        "prepared_breakout_selected_catalyst_relief_sector_resonance_min": round(float(profile.prepared_breakout_selected_catalyst_relief_sector_resonance_min), 4),
        "prepared_breakout_selected_catalyst_relief_layer_c_alignment_min": round(float(profile.prepared_breakout_selected_catalyst_relief_layer_c_alignment_min), 4),
        "prepared_breakout_selected_catalyst_relief_volume_expansion_quality_min": round(float(profile.prepared_breakout_selected_catalyst_relief_volume_expansion_quality_min), 4),
        "prepared_breakout_selected_catalyst_relief_catalyst_freshness_max": round(float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_max), 4),
        "prepared_breakout_selected_catalyst_relief_long_trend_strength_min": round(float(profile.prepared_breakout_selected_catalyst_relief_long_trend_strength_min), 4),
        "prepared_breakout_selected_catalyst_relief_mean_reversion_strength_max": round(float(profile.prepared_breakout_selected_catalyst_relief_mean_reversion_strength_max), 4),
        "prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor": round(float(profile.prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor), 4),
        "prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor": round(float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor), 4),
    }


def _build_short_trade_penalty_threshold_metrics_payload(profile: Any) -> dict[str, Any]:
    return {
        "stale_score_penalty_weight": round(float(profile.stale_score_penalty_weight), 4),
        "overhead_score_penalty_weight": round(float(profile.overhead_score_penalty_weight), 4),
        "extension_score_penalty_weight": round(float(profile.extension_score_penalty_weight), 4),
    }


def _build_watchlist_threshold_metrics_payload(profile: Any) -> dict[str, Any]:
    return {
        "watchlist_zero_catalyst_penalty": round(float(profile.watchlist_zero_catalyst_penalty), 4),
        "watchlist_zero_catalyst_catalyst_freshness_max": round(float(profile.watchlist_zero_catalyst_catalyst_freshness_max), 4),
        "watchlist_zero_catalyst_close_strength_min": round(float(profile.watchlist_zero_catalyst_close_strength_min), 4),
        "watchlist_zero_catalyst_layer_c_alignment_min": round(float(profile.watchlist_zero_catalyst_layer_c_alignment_min), 4),
        "watchlist_zero_catalyst_sector_resonance_min": round(float(profile.watchlist_zero_catalyst_sector_resonance_min), 4),
        "watchlist_zero_catalyst_crowded_penalty": round(float(profile.watchlist_zero_catalyst_crowded_penalty), 4),
        "watchlist_zero_catalyst_crowded_catalyst_freshness_max": round(float(profile.watchlist_zero_catalyst_crowded_catalyst_freshness_max), 4),
        "watchlist_zero_catalyst_crowded_close_strength_min": round(float(profile.watchlist_zero_catalyst_crowded_close_strength_min), 4),
        "watchlist_zero_catalyst_crowded_layer_c_alignment_min": round(float(profile.watchlist_zero_catalyst_crowded_layer_c_alignment_min), 4),
        "watchlist_zero_catalyst_crowded_sector_resonance_min": round(float(profile.watchlist_zero_catalyst_crowded_sector_resonance_min), 4),
        "watchlist_zero_catalyst_flat_trend_penalty": round(float(profile.watchlist_zero_catalyst_flat_trend_penalty), 4),
        "watchlist_zero_catalyst_flat_trend_catalyst_freshness_max": round(float(profile.watchlist_zero_catalyst_flat_trend_catalyst_freshness_max), 4),
        "watchlist_zero_catalyst_flat_trend_close_strength_min": round(float(profile.watchlist_zero_catalyst_flat_trend_close_strength_min), 4),
        "watchlist_zero_catalyst_flat_trend_layer_c_alignment_min": round(float(profile.watchlist_zero_catalyst_flat_trend_layer_c_alignment_min), 4),
        "watchlist_zero_catalyst_flat_trend_sector_resonance_min": round(float(profile.watchlist_zero_catalyst_flat_trend_sector_resonance_min), 4),
        "watchlist_zero_catalyst_flat_trend_trend_acceleration_max": round(float(profile.watchlist_zero_catalyst_flat_trend_trend_acceleration_max), 4),
    }


def _build_t_plus_2_and_merge_threshold_metrics_payload(profile: Any) -> dict[str, Any]:
    return {
        "t_plus_2_continuation_enabled": bool(profile.t_plus_2_continuation_enabled),
        "t_plus_2_continuation_catalyst_freshness_max": round(float(profile.t_plus_2_continuation_catalyst_freshness_max), 4),
        "t_plus_2_continuation_breakout_freshness_min": round(float(profile.t_plus_2_continuation_breakout_freshness_min), 4),
        "t_plus_2_continuation_trend_acceleration_min": round(float(profile.t_plus_2_continuation_trend_acceleration_min), 4),
        "t_plus_2_continuation_trend_acceleration_max": round(float(profile.t_plus_2_continuation_trend_acceleration_max), 4),
        "t_plus_2_continuation_layer_c_alignment_min": round(float(profile.t_plus_2_continuation_layer_c_alignment_min), 4),
        "t_plus_2_continuation_layer_c_alignment_max": round(float(profile.t_plus_2_continuation_layer_c_alignment_max), 4),
        "t_plus_2_continuation_close_strength_max": round(float(profile.t_plus_2_continuation_close_strength_max), 4),
        "t_plus_2_continuation_sector_resonance_max": round(float(profile.t_plus_2_continuation_sector_resonance_max), 4),
        "merge_approved_continuation_relief_enabled": bool(profile.merge_approved_continuation_relief_enabled),
        "merge_approved_continuation_select_threshold": round(float(profile.merge_approved_continuation_select_threshold), 4),
        "merge_approved_continuation_near_miss_threshold": round(float(profile.merge_approved_continuation_near_miss_threshold), 4),
        "hard_block_bearish_conflicts": sorted(str(item) for item in profile.hard_block_bearish_conflicts),
        "overhead_conflict_penalty_conflicts": sorted(str(item) for item in profile.overhead_conflict_penalty_conflicts),
        "hard_block_conflict_score_b_relief_min": None if profile.hard_block_conflict_score_b_relief_min is None else round(float(profile.hard_block_conflict_score_b_relief_min), 4),
        "hard_block_conflict_score_c_relief_min": None if profile.hard_block_conflict_score_c_relief_min is None else round(float(profile.hard_block_conflict_score_c_relief_min), 4),
    }


def _build_upstream_shadow_and_visibility_threshold_metrics_payload(*, profile: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "upstream_shadow_catalyst_relief_enabled": bool(snapshot["upstream_shadow_catalyst_relief_enabled"]),
        "upstream_shadow_catalyst_relief_applied": bool(snapshot["upstream_shadow_catalyst_relief_applied"]),
        "upstream_shadow_catalyst_relief_catalyst_freshness_floor": round(float(snapshot["upstream_shadow_catalyst_relief_catalyst_freshness_floor"]), 4),
        "upstream_shadow_catalyst_relief_near_miss_threshold_override": round(float(snapshot["upstream_shadow_catalyst_relief_near_miss_threshold_override"]), 4),
        "upstream_shadow_catalyst_relief_base_select_threshold": round(float(snapshot["upstream_shadow_catalyst_relief_base_select_threshold"]), 4),
        "upstream_shadow_catalyst_relief_select_threshold_override": round(float(snapshot["upstream_shadow_catalyst_relief_select_threshold_override"]), 4),
        "visibility_gap_continuation_relief_enabled": bool(profile.visibility_gap_continuation_relief_enabled),
        "visibility_gap_continuation_breakout_freshness_min": round(float(profile.visibility_gap_continuation_breakout_freshness_min), 4),
        "visibility_gap_continuation_trend_acceleration_min": round(float(profile.visibility_gap_continuation_trend_acceleration_min), 4),
        "visibility_gap_continuation_close_strength_min": round(float(profile.visibility_gap_continuation_close_strength_min), 4),
        "visibility_gap_continuation_catalyst_freshness_floor": round(float(profile.visibility_gap_continuation_catalyst_freshness_floor), 4),
        "visibility_gap_continuation_near_miss_threshold": round(float(profile.visibility_gap_continuation_near_miss_threshold), 4),
        "visibility_gap_continuation_require_relaxed_band": bool(profile.visibility_gap_continuation_require_relaxed_band),
    }


def _build_short_trade_threshold_metrics_payload(*, profile: Any, snapshot: dict[str, Any], positive_score_weights: dict[str, float]) -> dict[str, Any]:
    return {
        **_build_short_trade_threshold_core_metrics_payload(profile=profile, snapshot=snapshot, positive_score_weights=positive_score_weights),
        **_build_short_trade_threshold_profitability_metrics_payload(profile),
        **_build_prepared_breakout_penalty_threshold_metrics_payload(profile),
        **_build_prepared_breakout_catalyst_threshold_metrics_payload(profile),
        **_build_prepared_breakout_volume_threshold_metrics_payload(profile),
        **_build_prepared_breakout_continuation_threshold_metrics_payload(profile),
        **_build_prepared_breakout_selected_catalyst_threshold_metrics_payload(profile),
        **_build_short_trade_penalty_threshold_metrics_payload(profile),
        **_build_watchlist_threshold_metrics_payload(profile),
        **_build_t_plus_2_and_merge_threshold_metrics_payload(profile),
        **_build_upstream_shadow_and_visibility_threshold_metrics_payload(profile=profile, snapshot=snapshot),
    }


def _build_short_trade_core_metrics_payload(
    *,
    input_data: TargetEvaluationInput,
    snapshot: dict[str, Any],
    positive_score_weights: dict[str, Any],
    breakout_freshness: float,
    trend_acceleration: float,
    breakout_stage: str,
    selected_breakout_gate_pass: bool,
    near_miss_breakout_gate_pass: bool,
) -> dict[str, Any]:
    return {
        "score_b": round(float(input_data.score_b), 4),
        "score_c": round(float(input_data.score_c), 4),
        "score_final": round(float(input_data.score_final), 4),
        "quality_score": round(float(input_data.quality_score), 4),
        "score_b_strength": round(float(snapshot["score_b_strength"]), 4),
        "score_c_strength": round(float(snapshot["score_c_strength"]), 4),
        "score_final_strength": round(float(snapshot["score_final_strength"]), 4),
        "momentum_strength": round(float(snapshot["momentum_strength"]), 4),
        "momentum_1m": round(float(snapshot["momentum_1m"]), 4),
        "momentum_3m": round(float(snapshot["momentum_3m"]), 4),
        "momentum_6m": round(float(snapshot["momentum_6m"]), 4),
        "volume_momentum": round(float(snapshot["volume_momentum"]), 4),
        "adx_strength": round(float(snapshot["adx_strength"]), 4),
        "ema_strength": round(float(snapshot["ema_strength"]), 4),
        "volatility_strength": round(float(snapshot["volatility_strength"]), 4),
        "volatility_regime": round(float(snapshot["volatility_regime"]), 4),
        "atr_ratio": round(float(snapshot["atr_ratio"]), 4),
        "long_trend_strength": round(float(snapshot["long_trend_strength"]), 4),
        "event_freshness_strength": round(float(snapshot["event_freshness_strength"]), 4),
        "news_sentiment_strength": round(float(snapshot["news_sentiment_strength"]), 4),
        "event_signal_strength": round(float(snapshot["event_signal_strength"]), 4),
        "mean_reversion_strength": round(float(snapshot["mean_reversion_strength"]), 4),
        "analyst_alignment": round(float(snapshot["analyst_alignment"]), 4),
        "investor_alignment": round(float(snapshot["investor_alignment"]), 4),
        "analyst_penalty": round(float(snapshot["analyst_penalty"]), 4),
        "investor_penalty": round(float(snapshot["investor_penalty"]), 4),
        "breakout_freshness": round(float(breakout_freshness), 4),
        "trend_acceleration": round(float(trend_acceleration), 4),
        "volume_expansion_quality": round(float(snapshot["volume_expansion_quality"]), 4),
        "close_strength": round(float(snapshot["close_strength"]), 4),
        "close_retention_score": round(float(snapshot.get("close_retention_score", 0.0)), 4),
        "breakout_close_gap": round(float(snapshot.get("breakout_close_gap", 0.0)), 4),
        "sector_resonance": round(float(snapshot["sector_resonance"]), 4),
        "catalyst_freshness": round(float(snapshot["raw_catalyst_freshness"]), 4),
        "effective_catalyst_freshness": round(float(snapshot["catalyst_freshness"]), 4),
        "layer_c_alignment": round(float(snapshot["layer_c_alignment"]), 4),
        "historical_continuation_prior_score": dict(snapshot.get("historical_continuation_prior_score") or {}),
        "short_term_reversal": round(float(snapshot.get("short_term_reversal", 0.0)), 4),
        "intraday_strength": round(float(snapshot.get("intraday_strength", 0.0)), 4),
        "reversal_2d": round(float(snapshot.get("reversal_2d", 0.0)), 4),
        "positive_score_weights": {name: round(float(value), 4) for name, value in positive_score_weights.items()},
        "breakout_stage": breakout_stage,
        "selected_breakout_gate_pass": selected_breakout_gate_pass,
        "near_miss_breakout_gate_pass": near_miss_breakout_gate_pass,
    }


def _build_short_trade_context_metrics_payload(
    *,
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
) -> dict[str, Any]:
    return {
        "carryover_evidence_deficiency": _build_carryover_evidence_deficiency_metrics_payload(carryover_evidence_deficiency),
        "selected_historical_proof_deficiency": _build_selected_historical_proof_deficiency_metrics_payload(selected_historical_proof_deficiency),
    }


def _build_visibility_gap_continuation_relief_metrics_payload(visibility_gap_continuation_relief: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(visibility_gap_continuation_relief["enabled"]),
        "eligible": bool(visibility_gap_continuation_relief["eligible"]),
        "applied": bool(visibility_gap_continuation_relief["applied"]),
        "candidate_source": str(visibility_gap_continuation_relief["candidate_source"]),
        "candidate_pool_lane": str(visibility_gap_continuation_relief["candidate_pool_lane"]),
        "candidate_pool_shadow_reason": str(visibility_gap_continuation_relief["candidate_pool_shadow_reason"]),
        "shadow_visibility_gap_selected": bool(visibility_gap_continuation_relief["shadow_visibility_gap_selected"]),
        "shadow_visibility_gap_relaxed_band": bool(visibility_gap_continuation_relief["shadow_visibility_gap_relaxed_band"]),
        "gate_hits": dict(visibility_gap_continuation_relief["gate_hits"]),
        "historical_execution_quality_label": str(visibility_gap_continuation_relief["historical_execution_quality_label"]),
        "historical_applied_scope": str(visibility_gap_continuation_relief["historical_applied_scope"]),
        "historical_evaluable_count": int(visibility_gap_continuation_relief["historical_evaluable_count"]),
        "historical_next_close_positive_rate": round(float(visibility_gap_continuation_relief["historical_next_close_positive_rate"]), 4),
        "catalyst_freshness_floor": round(float(visibility_gap_continuation_relief["catalyst_freshness_floor"]), 4),
        "near_miss_threshold_override": round(float(visibility_gap_continuation_relief["near_miss_threshold_override"]), 4),
        "require_relaxed_band": bool(visibility_gap_continuation_relief["require_relaxed_band"]),
    }


def _build_merge_approved_continuation_relief_metrics_payload(merge_approved_continuation_relief: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(merge_approved_continuation_relief["enabled"]),
        "eligible": bool(merge_approved_continuation_relief["eligible"]),
        "applied": bool(merge_approved_continuation_relief["applied"]),
        "reason": str(merge_approved_continuation_relief["reason"]),
        "gate_hits": dict(merge_approved_continuation_relief["gate_hits"]),
        "historical_execution_quality_label": str(merge_approved_continuation_relief["historical_execution_quality_label"]),
        "historical_applied_scope": str(merge_approved_continuation_relief["historical_applied_scope"]),
        "historical_evaluable_count": int(merge_approved_continuation_relief["historical_evaluable_count"]),
        "historical_next_close_positive_rate": round(float(merge_approved_continuation_relief["historical_next_close_positive_rate"]), 4),
        "base_near_miss_threshold": round(float(merge_approved_continuation_relief["base_near_miss_threshold"]), 4),
        "effective_near_miss_threshold": round(float(merge_approved_continuation_relief["effective_near_miss_threshold"]), 4),
        "near_miss_threshold_override": round(float(merge_approved_continuation_relief["near_miss_threshold_override"]), 4),
        "base_select_threshold": round(float(merge_approved_continuation_relief["base_select_threshold"]), 4),
        "effective_select_threshold": round(float(merge_approved_continuation_relief["effective_select_threshold"]), 4),
        "select_threshold_override": round(float(merge_approved_continuation_relief["select_threshold_override"]), 4),
        "require_no_profitability_hard_cliff": bool(merge_approved_continuation_relief["require_no_profitability_hard_cliff"]),
    }


def _build_upstream_shadow_metrics_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "upstream_shadow_catalyst_relief_enabled": bool(snapshot["upstream_shadow_catalyst_relief_enabled"]),
        "upstream_shadow_catalyst_relief_gate_hits": dict(snapshot["upstream_shadow_catalyst_relief_gate_hits"]),
        "upstream_shadow_catalyst_relief_eligible": bool(snapshot["upstream_shadow_catalyst_relief_eligible"]),
        "upstream_shadow_catalyst_relief_applied": bool(snapshot["upstream_shadow_catalyst_relief_applied"]),
        "upstream_shadow_catalyst_relief_reason": str(snapshot["upstream_shadow_catalyst_relief_reason"]),
        "upstream_shadow_catalyst_relief_catalyst_freshness_floor": round(float(snapshot["upstream_shadow_catalyst_relief_catalyst_freshness_floor"]), 4),
        "upstream_shadow_catalyst_relief_base_near_miss_threshold": round(float(snapshot["upstream_shadow_catalyst_relief_base_near_miss_threshold"]), 4),
        "upstream_shadow_catalyst_relief_near_miss_threshold_override": round(float(snapshot["upstream_shadow_catalyst_relief_near_miss_threshold_override"]), 4),
        "upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff": bool(snapshot["upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff"]),
    }


def _build_short_trade_penalty_metrics_payload(
    *,
    snapshot: dict[str, Any],
    breakout_trap_guard: dict[str, Any],
    weighted_positive_contributions: dict[str, Any],
    weighted_negative_contributions: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stale_trend_repair_penalty": round(float(snapshot["stale_trend_repair_penalty"]), 4),
        "overhead_supply_penalty": round(float(snapshot["overhead_supply_penalty"]), 4),
        "extension_without_room_penalty": round(float(snapshot["extension_without_room_penalty"]), 4),
        "selected_close_retention_penalty": dict(snapshot.get("selected_close_retention_penalty") or {}),
        "breakout_trap_guard": _build_breakout_trap_guard_metrics_payload(breakout_trap_guard),
        "weighted_positive_contributions": weighted_positive_contributions,
        "weighted_negative_contributions": weighted_negative_contributions,
        "total_positive_contribution": round(float(snapshot["total_positive_contribution"]), 4),
        "total_negative_contribution": round(float(snapshot["total_negative_contribution"]), 4),
    }


def _collect_short_trade_metrics_payload_inputs(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_state_threshold_adjustment": dict(snapshot.get("market_state_threshold_adjustment") or {}),
        "breakout_trap_guard": dict(snapshot.get("breakout_trap_guard") or {}),
        "historical_execution_relief": dict(snapshot["historical_execution_relief"]),
        "profitability_hard_cliff_boundary_relief": dict(snapshot["profitability_hard_cliff_boundary_relief"]),
        "t_plus_2_continuation_candidate": dict(snapshot["t_plus_2_continuation_candidate"]),
        "catalyst_theme_guard": dict(snapshot["catalyst_theme_guard"]),
        "watchlist_zero_catalyst_guard": dict(snapshot["watchlist_zero_catalyst_guard"]),
        "watchlist_zero_catalyst_crowded_guard": dict(snapshot["watchlist_zero_catalyst_crowded_guard"]),
        "watchlist_zero_catalyst_flat_trend_guard": dict(snapshot["watchlist_zero_catalyst_flat_trend_guard"]),
        "watchlist_filter_diagnostics_flat_trend_guard": dict(snapshot["watchlist_filter_diagnostics_flat_trend_guard"]),
        "visibility_gap_continuation_relief": dict(snapshot["visibility_gap_continuation_relief"]),
        "merge_approved_continuation_relief": dict(snapshot["merge_approved_continuation_relief"]),
        "prepared_breakout_penalty_relief": dict(snapshot["prepared_breakout_penalty_relief"]),
        "prepared_breakout_catalyst_relief": dict(snapshot["prepared_breakout_catalyst_relief"]),
        "prepared_breakout_volume_relief": dict(snapshot["prepared_breakout_volume_relief"]),
        "prepared_breakout_continuation_relief": dict(snapshot["prepared_breakout_continuation_relief"]),
        "prepared_breakout_selected_catalyst_relief": dict(snapshot["prepared_breakout_selected_catalyst_relief"]),
        "positive_score_weights": dict(snapshot["positive_score_weights"]),
        "weighted_positive_contributions": dict(snapshot["weighted_positive_contributions"]),
        "weighted_negative_contributions": dict(snapshot["weighted_negative_contributions"]),
    }


def _build_short_trade_relief_metrics_payload(metrics_inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "historical_execution_relief": _build_historical_execution_relief_metrics_payload(metrics_inputs["historical_execution_relief"]),
        "profitability_hard_cliff_boundary_relief": _build_profitability_hard_cliff_boundary_relief_metrics_payload(metrics_inputs["profitability_hard_cliff_boundary_relief"]),
        "visibility_gap_continuation_relief": _build_visibility_gap_continuation_relief_metrics_payload(metrics_inputs["visibility_gap_continuation_relief"]),
        "merge_approved_continuation_relief": _build_merge_approved_continuation_relief_metrics_payload(metrics_inputs["merge_approved_continuation_relief"]),
        **_build_prepared_breakout_metrics_payload(
            prepared_breakout_penalty_relief=metrics_inputs["prepared_breakout_penalty_relief"],
            prepared_breakout_catalyst_relief=metrics_inputs["prepared_breakout_catalyst_relief"],
            prepared_breakout_volume_relief=metrics_inputs["prepared_breakout_volume_relief"],
            prepared_breakout_continuation_relief=metrics_inputs["prepared_breakout_continuation_relief"],
            prepared_breakout_selected_catalyst_relief=metrics_inputs["prepared_breakout_selected_catalyst_relief"],
        ),
    }


def _build_profitability_explainability_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(snapshot["profitability_relief_enabled"]),
        "hard_cliff": bool(snapshot["profitability_hard_cliff"]),
        "eligible": bool(snapshot["profitability_relief_eligible"]),
        "applied": bool(snapshot["profitability_relief_applied"]),
        "gate_hits": dict(snapshot["profitability_relief_gate_hits"]),
        "base_layer_c_avoid_penalty": round(float(snapshot["base_layer_c_avoid_penalty"]), 4),
        "effective_layer_c_avoid_penalty": round(float(snapshot["layer_c_avoid_penalty"]), 4),
        "soft_penalty": round(float(snapshot["profitability_relief_soft_penalty"]), 4),
    }
