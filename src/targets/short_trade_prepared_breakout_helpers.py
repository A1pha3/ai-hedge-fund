from __future__ import annotations

from typing import Any

from src.targets.models import TargetEvaluationInput
from src.targets.explainability import clamp_unit_interval


def resolve_prepared_breakout_penalty_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_stage: str,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    catalyst_freshness: float,
    long_trend_strength: float,
    mean_reversion_strength: float,
    profile: Any,
) -> dict[str, Any]:
    base_positive_score_weights = {
        "breakout_freshness": float(profile.breakout_freshness_weight),
        "trend_acceleration": float(profile.trend_acceleration_weight),
        "volume_expansion_quality": float(profile.volume_expansion_quality_weight),
        "close_strength": float(profile.close_strength_weight),
        "sector_resonance": float(profile.sector_resonance_weight),
        "catalyst_freshness": float(profile.catalyst_freshness_weight),
        "layer_c_alignment": float(profile.layer_c_alignment_weight),
        "historical_continuation_score": float(getattr(profile, "historical_continuation_score_weight", 0.0)),
    }
    source = str(input_data.replay_context.get("source") or "").strip()
    base_stale_score_penalty_weight = float(profile.stale_score_penalty_weight)
    base_extension_score_penalty_weight = float(profile.extension_score_penalty_weight)
    default_result = {
        "enabled": bool(profile.prepared_breakout_penalty_relief_enabled),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": {},
        "base_positive_score_weights": dict(base_positive_score_weights),
        "effective_positive_score_weights": dict(base_positive_score_weights),
        "base_stale_score_penalty_weight": base_stale_score_penalty_weight,
        "effective_stale_score_penalty_weight": base_stale_score_penalty_weight,
        "base_extension_score_penalty_weight": base_extension_score_penalty_weight,
        "effective_extension_score_penalty_weight": base_extension_score_penalty_weight,
    }
    if not bool(profile.prepared_breakout_penalty_relief_enabled):
        return default_result

    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "prepared_breakout_stage": breakout_stage == "prepared_breakout",
        "breakout_freshness_cap": breakout_freshness <= float(profile.prepared_breakout_penalty_relief_breakout_freshness_max),
        "trend_acceleration": trend_acceleration >= float(profile.prepared_breakout_penalty_relief_trend_acceleration_min),
        "close_strength": close_strength >= float(profile.prepared_breakout_penalty_relief_close_strength_min),
        "sector_resonance": sector_resonance >= float(profile.prepared_breakout_penalty_relief_sector_resonance_min),
        "layer_c_alignment": layer_c_alignment >= float(profile.prepared_breakout_penalty_relief_layer_c_alignment_min),
        "catalyst_freshness_cap": catalyst_freshness <= float(profile.prepared_breakout_penalty_relief_catalyst_freshness_max),
        "long_trend_strength": long_trend_strength >= float(profile.prepared_breakout_penalty_relief_long_trend_strength_min),
        "mean_reversion_cap": mean_reversion_strength <= float(profile.prepared_breakout_penalty_relief_mean_reversion_strength_max),
    }
    eligible = all(gate_hits.values())
    effective_positive_score_weights = dict(base_positive_score_weights)
    effective_stale_score_penalty_weight = base_stale_score_penalty_weight
    effective_extension_score_penalty_weight = base_extension_score_penalty_weight
    if eligible:
        effective_positive_score_weights = {
            "breakout_freshness": float(profile.prepared_breakout_penalty_relief_breakout_freshness_weight),
            "trend_acceleration": float(profile.prepared_breakout_penalty_relief_trend_acceleration_weight),
            "volume_expansion_quality": float(profile.prepared_breakout_penalty_relief_volume_expansion_quality_weight),
            "close_strength": float(profile.prepared_breakout_penalty_relief_close_strength_weight),
            "sector_resonance": float(profile.prepared_breakout_penalty_relief_sector_resonance_weight),
            "catalyst_freshness": float(profile.prepared_breakout_penalty_relief_catalyst_freshness_weight),
            "layer_c_alignment": float(profile.prepared_breakout_penalty_relief_layer_c_alignment_weight),
            "historical_continuation_score": float(getattr(profile, "historical_continuation_score_weight", 0.0)),
        }
        effective_stale_score_penalty_weight = min(
            base_stale_score_penalty_weight,
            float(profile.prepared_breakout_penalty_relief_stale_score_penalty_weight),
        )
        effective_extension_score_penalty_weight = min(
            base_extension_score_penalty_weight,
            float(profile.prepared_breakout_penalty_relief_extension_score_penalty_weight),
        )
    applied = eligible and (
        dict(effective_positive_score_weights) != dict(base_positive_score_weights)
        or effective_stale_score_penalty_weight < base_stale_score_penalty_weight
        or effective_extension_score_penalty_weight < base_extension_score_penalty_weight
    )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": applied,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": gate_hits,
        "base_positive_score_weights": dict(base_positive_score_weights),
        "effective_positive_score_weights": dict(effective_positive_score_weights),
        "base_stale_score_penalty_weight": base_stale_score_penalty_weight,
        "effective_stale_score_penalty_weight": effective_stale_score_penalty_weight,
        "base_extension_score_penalty_weight": base_extension_score_penalty_weight,
        "effective_extension_score_penalty_weight": effective_extension_score_penalty_weight,
    }


def resolve_prepared_breakout_catalyst_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_stage: str,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    catalyst_freshness: float,
    long_trend_strength: float,
    mean_reversion_strength: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    default_result = {
        "enabled": bool(profile.prepared_breakout_catalyst_relief_enabled),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": {},
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": catalyst_freshness,
        "catalyst_freshness_floor": float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_floor),
    }
    if not bool(profile.prepared_breakout_catalyst_relief_enabled):
        return default_result

    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "prepared_breakout_stage": breakout_stage == "prepared_breakout",
        "breakout_freshness_cap": breakout_freshness <= float(profile.prepared_breakout_catalyst_relief_breakout_freshness_max),
        "trend_acceleration": trend_acceleration >= float(profile.prepared_breakout_catalyst_relief_trend_acceleration_min),
        "close_strength": close_strength >= float(profile.prepared_breakout_catalyst_relief_close_strength_min),
        "sector_resonance": sector_resonance >= float(profile.prepared_breakout_catalyst_relief_sector_resonance_min),
        "layer_c_alignment": layer_c_alignment >= float(profile.prepared_breakout_catalyst_relief_layer_c_alignment_min),
        "catalyst_freshness_cap": catalyst_freshness <= float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_max),
        "long_trend_strength": long_trend_strength >= float(profile.prepared_breakout_catalyst_relief_long_trend_strength_min),
        "mean_reversion_cap": mean_reversion_strength <= float(profile.prepared_breakout_catalyst_relief_mean_reversion_strength_max),
    }
    eligible = all(gate_hits.values())
    effective_catalyst_freshness = catalyst_freshness
    if eligible:
        effective_catalyst_freshness = max(
            catalyst_freshness,
            float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_floor),
        )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and effective_catalyst_freshness > catalyst_freshness,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": gate_hits,
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": effective_catalyst_freshness,
        "catalyst_freshness_floor": float(profile.prepared_breakout_catalyst_relief_catalyst_freshness_floor),
    }


def resolve_prepared_breakout_volume_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_stage: str,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    catalyst_freshness: float,
    long_trend_strength: float,
    mean_reversion_strength: float,
    volatility_strength: float,
    volume_expansion_quality: float,
    volatility_regime: float,
    atr_ratio: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    default_result = {
        "enabled": bool(profile.prepared_breakout_volume_relief_enabled),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": {},
        "base_volume_expansion_quality": volume_expansion_quality,
        "effective_volume_expansion_quality": volume_expansion_quality,
        "volatility_regime": volatility_regime,
        "atr_ratio": atr_ratio,
        "volume_expansion_quality_floor": float(profile.prepared_breakout_volume_relief_volume_expansion_quality_floor),
    }
    if not bool(profile.prepared_breakout_volume_relief_enabled):
        return default_result

    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "prepared_breakout_stage": breakout_stage == "prepared_breakout",
        "breakout_freshness_cap": breakout_freshness <= float(profile.prepared_breakout_volume_relief_breakout_freshness_max),
        "trend_acceleration": trend_acceleration >= float(profile.prepared_breakout_volume_relief_trend_acceleration_min),
        "close_strength": close_strength >= float(profile.prepared_breakout_volume_relief_close_strength_min),
        "sector_resonance": sector_resonance >= float(profile.prepared_breakout_volume_relief_sector_resonance_min),
        "layer_c_alignment": layer_c_alignment >= float(profile.prepared_breakout_volume_relief_layer_c_alignment_min),
        "catalyst_freshness_cap": catalyst_freshness <= float(profile.prepared_breakout_volume_relief_catalyst_freshness_max),
        "long_trend_strength": long_trend_strength >= float(profile.prepared_breakout_volume_relief_long_trend_strength_min),
        "mean_reversion_cap": mean_reversion_strength <= float(profile.prepared_breakout_volume_relief_mean_reversion_strength_max),
        "volatility_strength_cap": volatility_strength <= float(profile.prepared_breakout_volume_relief_volatility_strength_max),
        "volatility_regime": volatility_regime >= float(profile.prepared_breakout_volume_relief_volatility_regime_min),
        "atr_ratio": atr_ratio >= float(profile.prepared_breakout_volume_relief_atr_ratio_min),
    }
    eligible = all(gate_hits.values())
    effective_volume_expansion_quality = volume_expansion_quality
    if eligible:
        effective_volume_expansion_quality = max(
            volume_expansion_quality,
            float(profile.prepared_breakout_volume_relief_volume_expansion_quality_floor),
        )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and effective_volume_expansion_quality > volume_expansion_quality,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": gate_hits,
        "base_volume_expansion_quality": volume_expansion_quality,
        "effective_volume_expansion_quality": effective_volume_expansion_quality,
        "volatility_regime": volatility_regime,
        "atr_ratio": atr_ratio,
        "volume_expansion_quality_floor": float(profile.prepared_breakout_volume_relief_volume_expansion_quality_floor),
    }


def resolve_prepared_breakout_continuation_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_stage: str,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    catalyst_freshness: float,
    long_trend_strength: float,
    mean_reversion_strength: float,
    momentum_1m: float,
    momentum_3m: float,
    momentum_6m: float,
    volume_momentum: float,
    ema_strength: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    continuation_support = clamp_unit_interval((0.40 * momentum_3m) + (0.35 * momentum_6m) + (0.25 * volume_momentum))
    default_result = {
        "enabled": bool(profile.prepared_breakout_continuation_relief_enabled),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": {},
        "base_breakout_freshness": breakout_freshness,
        "effective_breakout_freshness": breakout_freshness,
        "base_trend_acceleration": trend_acceleration,
        "effective_trend_acceleration": trend_acceleration,
        "momentum_1m": momentum_1m,
        "momentum_3m": momentum_3m,
        "momentum_6m": momentum_6m,
        "volume_momentum": volume_momentum,
        "continuation_support": continuation_support,
        "breakout_freshness_floor": float(profile.prepared_breakout_continuation_relief_breakout_freshness_floor),
        "trend_acceleration_floor": float(profile.prepared_breakout_continuation_relief_trend_acceleration_floor),
    }
    if not bool(profile.prepared_breakout_continuation_relief_enabled):
        return default_result

    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "prepared_breakout_stage": breakout_stage == "prepared_breakout",
        "breakout_freshness_cap": breakout_freshness <= float(profile.prepared_breakout_continuation_relief_breakout_freshness_max),
        "trend_acceleration_min": trend_acceleration >= float(profile.prepared_breakout_continuation_relief_trend_acceleration_min),
        "trend_acceleration_cap": trend_acceleration <= float(profile.prepared_breakout_continuation_relief_trend_acceleration_max),
        "close_strength": close_strength >= float(profile.prepared_breakout_continuation_relief_close_strength_min),
        "sector_resonance": sector_resonance >= float(profile.prepared_breakout_continuation_relief_sector_resonance_min),
        "layer_c_alignment": layer_c_alignment >= float(profile.prepared_breakout_continuation_relief_layer_c_alignment_min),
        "catalyst_freshness_cap": catalyst_freshness <= float(profile.prepared_breakout_continuation_relief_catalyst_freshness_max),
        "long_trend_strength": long_trend_strength >= float(profile.prepared_breakout_continuation_relief_long_trend_strength_min),
        "mean_reversion_cap": mean_reversion_strength <= float(profile.prepared_breakout_continuation_relief_mean_reversion_strength_max),
        "momentum_1m_pullback": momentum_1m <= float(profile.prepared_breakout_continuation_relief_momentum_1m_max),
        "continuation_support": continuation_support >= float(profile.prepared_breakout_continuation_relief_continuation_support_min),
    }
    eligible = all(gate_hits.values())
    effective_breakout_freshness = breakout_freshness
    effective_trend_acceleration = trend_acceleration
    if eligible:
        effective_breakout_freshness = max(
            breakout_freshness,
            float(profile.prepared_breakout_continuation_relief_breakout_freshness_floor),
        )
        effective_trend_acceleration = max(
            trend_acceleration,
            min(
                float(profile.prepared_breakout_continuation_relief_trend_acceleration_floor),
                clamp_unit_interval(
                    (0.30 * continuation_support)
                    + (0.35 * ema_strength)
                    + (0.20 * long_trend_strength)
                    + (0.15 * close_strength)
                ),
            ),
        )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and (
            effective_breakout_freshness > breakout_freshness or effective_trend_acceleration > trend_acceleration
        ),
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": gate_hits,
        "base_breakout_freshness": breakout_freshness,
        "effective_breakout_freshness": effective_breakout_freshness,
        "base_trend_acceleration": trend_acceleration,
        "effective_trend_acceleration": effective_trend_acceleration,
        "momentum_1m": momentum_1m,
        "momentum_3m": momentum_3m,
        "momentum_6m": momentum_6m,
        "volume_momentum": volume_momentum,
        "continuation_support": continuation_support,
        "breakout_freshness_floor": float(profile.prepared_breakout_continuation_relief_breakout_freshness_floor),
        "trend_acceleration_floor": float(profile.prepared_breakout_continuation_relief_trend_acceleration_floor),
    }


def resolve_prepared_breakout_selected_catalyst_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_stage: str,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    volume_expansion_quality: float,
    catalyst_freshness: float,
    long_trend_strength: float,
    mean_reversion_strength: float,
    prepared_breakout_penalty_relief: dict[str, Any],
    prepared_breakout_catalyst_relief: dict[str, Any],
    prepared_breakout_volume_relief: dict[str, Any],
    prepared_breakout_continuation_relief: dict[str, Any],
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    default_result = {
        "enabled": bool(profile.prepared_breakout_selected_catalyst_relief_enabled),
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": {},
        "base_breakout_freshness": breakout_freshness,
        "effective_breakout_freshness": breakout_freshness,
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": catalyst_freshness,
        "selected_breakout_freshness_floor": float(profile.prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor),
        "catalyst_freshness_floor": float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor),
    }
    if not bool(profile.prepared_breakout_selected_catalyst_relief_enabled):
        return default_result

    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "prepared_breakout_stage": breakout_stage == "prepared_breakout",
        "penalty_relief_applied": bool(prepared_breakout_penalty_relief.get("applied")),
        "catalyst_relief_applied": bool(prepared_breakout_catalyst_relief.get("applied")),
        "volume_relief_applied": bool(prepared_breakout_volume_relief.get("applied")),
        "continuation_relief_applied": bool(prepared_breakout_continuation_relief.get("applied")),
        "breakout_freshness_min": breakout_freshness >= float(profile.prepared_breakout_selected_catalyst_relief_breakout_freshness_min),
        "trend_acceleration_min": trend_acceleration >= float(profile.prepared_breakout_selected_catalyst_relief_trend_acceleration_min),
        "close_strength": close_strength >= float(profile.prepared_breakout_selected_catalyst_relief_close_strength_min),
        "sector_resonance": sector_resonance >= float(profile.prepared_breakout_selected_catalyst_relief_sector_resonance_min),
        "layer_c_alignment": layer_c_alignment >= float(profile.prepared_breakout_selected_catalyst_relief_layer_c_alignment_min),
        "volume_expansion_quality": volume_expansion_quality >= float(profile.prepared_breakout_selected_catalyst_relief_volume_expansion_quality_min),
        "catalyst_freshness_cap": catalyst_freshness <= float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_max),
        "long_trend_strength": long_trend_strength >= float(profile.prepared_breakout_selected_catalyst_relief_long_trend_strength_min),
        "mean_reversion_cap": mean_reversion_strength <= float(profile.prepared_breakout_selected_catalyst_relief_mean_reversion_strength_max),
    }
    eligible = all(gate_hits.values())
    effective_breakout_freshness = breakout_freshness
    effective_catalyst_freshness = catalyst_freshness
    if eligible:
        effective_breakout_freshness = max(
            breakout_freshness,
            float(profile.prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor),
        )
        effective_catalyst_freshness = max(
            catalyst_freshness,
            float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor),
        )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible and (
            effective_breakout_freshness > breakout_freshness or effective_catalyst_freshness > catalyst_freshness
        ),
        "candidate_source": source,
        "breakout_stage": breakout_stage,
        "gate_hits": gate_hits,
        "base_breakout_freshness": breakout_freshness,
        "effective_breakout_freshness": effective_breakout_freshness,
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": effective_catalyst_freshness,
        "selected_breakout_freshness_floor": float(profile.prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor),
        "catalyst_freshness_floor": float(profile.prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor),
    }
