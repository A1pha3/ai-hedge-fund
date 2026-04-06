from __future__ import annotations

from typing import Any

from src.execution.models import LayerCResult
from src.screening.models import StrategySignal
from src.targets.explainability import clamp_unit_interval, derive_confidence, trim_reasons
from src.targets.models import TargetEvaluationInput, TargetEvaluationResult
from src.targets.profiles import get_active_short_trade_target_profile, use_short_trade_target_profile


def _normalize_score(value: float) -> float:
    return clamp_unit_interval((float(value or 0.0) + 1.0) / 2.0)


def _load_signal(payload: Any) -> StrategySignal | None:
    if isinstance(payload, StrategySignal):
        return payload
    if isinstance(payload, dict) and payload:
        try:
            return StrategySignal.model_validate(payload)
        except Exception:
            return None
    return None


def _signal_signed_strength(signal: StrategySignal | None) -> float:
    if signal is None:
        return 0.0
    return max(-1.0, min(1.0, float(signal.direction) * (float(signal.confidence) / 100.0) * float(signal.completeness)))


def _positive_strength(signal: StrategySignal | None) -> float:
    return clamp_unit_interval(max(0.0, _signal_signed_strength(signal)))


def _subfactor_signed_strength(signal: StrategySignal | None, name: str) -> float:
    if signal is None:
        return 0.0
    snapshot = signal.sub_factors.get(name, {}) if isinstance(signal.sub_factors, dict) else {}
    if not isinstance(snapshot, dict):
        return 0.0
    direction = float(snapshot.get("direction", 0.0) or 0.0)
    confidence = float(snapshot.get("confidence", 0.0) or 0.0)
    completeness = float(snapshot.get("completeness", 1.0) or 1.0)
    return max(-1.0, min(1.0, direction * (confidence / 100.0) * completeness))


def _subfactor_positive_strength(signal: StrategySignal | None, name: str) -> float:
    return clamp_unit_interval(max(0.0, _subfactor_signed_strength(signal, name)))


def _profitability_snapshot(signal: StrategySignal | None) -> dict[str, Any]:
    if signal is None or not isinstance(signal.sub_factors, dict):
        return {}
    snapshot = signal.sub_factors.get("profitability", {})
    return snapshot if isinstance(snapshot, dict) else {}


def _resolve_profitability_relief(
    *,
    input_data: TargetEvaluationInput,
    fundamental_signal: StrategySignal | None,
    breakout_freshness: float,
    catalyst_freshness: float,
    sector_resonance: float,
    profile: Any,
) -> dict[str, Any]:
    profitability = _profitability_snapshot(fundamental_signal)
    profitability_metrics = profitability.get("metrics", {}) if isinstance(profitability.get("metrics", {}), dict) else {}
    positive_count_raw = profitability_metrics.get("positive_count")
    try:
        profitability_positive_count = int(positive_count_raw) if positive_count_raw is not None else None
    except (TypeError, ValueError):
        profitability_positive_count = None
    profitability_confidence = float(profitability.get("confidence", 0.0) or 0.0)
    hard_cliff = profitability.get("direction") == -1 and profitability_positive_count == 0

    base_layer_c_avoid_penalty = float(profile.layer_c_avoid_penalty) if input_data.layer_c_decision == "avoid" else 0.0
    relief_gate_hits = {
        "breakout_freshness": breakout_freshness >= float(profile.profitability_relief_breakout_freshness_min),
        "catalyst_freshness": catalyst_freshness >= float(profile.profitability_relief_catalyst_freshness_min),
        "sector_resonance": sector_resonance >= float(profile.profitability_relief_sector_resonance_min),
    }
    relief_eligible = (
        bool(profile.profitability_relief_enabled)
        and input_data.layer_c_decision == "avoid"
        and hard_cliff
        and all(relief_gate_hits.values())
    )
    effective_avoid_penalty = base_layer_c_avoid_penalty
    if relief_eligible and base_layer_c_avoid_penalty > 0:
        effective_avoid_penalty = min(base_layer_c_avoid_penalty, float(profile.profitability_relief_avoid_penalty))

    return {
        "hard_cliff": hard_cliff,
        "profitability_direction": int(profitability.get("direction", 0) or 0),
        "profitability_positive_count": profitability_positive_count,
        "profitability_confidence": profitability_confidence,
        "relief_enabled": bool(profile.profitability_relief_enabled),
        "relief_gate_hits": relief_gate_hits,
        "relief_eligible": relief_eligible,
        "relief_applied": relief_eligible and effective_avoid_penalty < base_layer_c_avoid_penalty,
        "base_layer_c_avoid_penalty": base_layer_c_avoid_penalty,
        "effective_avoid_penalty": effective_avoid_penalty,
        "soft_penalty": float(profile.profitability_relief_avoid_penalty),
        "metrics": profitability_metrics,
    }


def _resolve_upstream_shadow_catalyst_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    catalyst_freshness: float,
    profitability_hard_cliff: bool,
    profile: Any,
) -> dict[str, Any]:
    relief_payload = input_data.replay_context.get("short_trade_catalyst_relief")
    relief_config = dict(relief_payload) if isinstance(relief_payload, dict) else {}
    relief_reason = str(relief_config.get("reason") or "upstream_shadow_catalyst_relief")
    base_near_miss_threshold = float(profile.near_miss_threshold)
    default_result = {
        "enabled": False,
        "eligible": False,
        "applied": False,
        "reason": relief_reason,
        "gate_hits": {},
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": catalyst_freshness,
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": base_near_miss_threshold,
        "catalyst_freshness_floor": 0.0,
        "near_miss_threshold_override": base_near_miss_threshold,
        "require_no_profitability_hard_cliff": False,
    }

    candidate_reason_codes = {
        str(code).strip()
        for code in list(input_data.replay_context.get("candidate_reason_codes") or [])
        if str(code or "").strip()
    }
    if not relief_config or "upstream_shadow_release_candidate" not in candidate_reason_codes:
        return default_result

    enabled = bool(relief_config.get("enabled", True))
    if not enabled:
        return {**default_result, "reason": relief_reason}

    catalyst_freshness_floor = clamp_unit_interval(float(relief_config.get("catalyst_freshness_floor", 0.0) or 0.0))
    near_miss_threshold_override = clamp_unit_interval(float(relief_config.get("near_miss_threshold", base_near_miss_threshold) or base_near_miss_threshold))
    breakout_freshness_min = clamp_unit_interval(float(relief_config.get("breakout_freshness_min", 0.0) or 0.0))
    trend_acceleration_min = clamp_unit_interval(float(relief_config.get("trend_acceleration_min", 0.0) or 0.0))
    close_strength_min = clamp_unit_interval(float(relief_config.get("close_strength_min", 0.0) or 0.0))
    require_no_profitability_hard_cliff = bool(relief_config.get("require_no_profitability_hard_cliff", False))

    gate_hits = {
        "breakout_freshness": breakout_freshness >= breakout_freshness_min,
        "trend_acceleration": trend_acceleration >= trend_acceleration_min,
        "close_strength": close_strength >= close_strength_min,
        "no_profitability_hard_cliff": (not require_no_profitability_hard_cliff) or (not profitability_hard_cliff),
    }
    eligible = all(gate_hits.values())
    effective_catalyst_freshness = catalyst_freshness
    effective_near_miss_threshold = base_near_miss_threshold
    if eligible:
        effective_catalyst_freshness = max(catalyst_freshness, catalyst_freshness_floor)
        effective_near_miss_threshold = min(base_near_miss_threshold, near_miss_threshold_override)

    applied = eligible and (
        effective_catalyst_freshness > catalyst_freshness
        or effective_near_miss_threshold < base_near_miss_threshold
    )
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": applied,
        "reason": relief_reason,
        "gate_hits": gate_hits,
        "base_catalyst_freshness": catalyst_freshness,
        "effective_catalyst_freshness": effective_catalyst_freshness,
        "base_near_miss_threshold": base_near_miss_threshold,
        "effective_near_miss_threshold": effective_near_miss_threshold,
        "catalyst_freshness_floor": catalyst_freshness_floor,
        "near_miss_threshold_override": near_miss_threshold_override,
        "require_no_profitability_hard_cliff": require_no_profitability_hard_cliff,
    }


def _cohort_alignment(agent_contribution_summary: dict[str, Any], cohort_name: str) -> float:
    cohort_contributions = dict(agent_contribution_summary.get("cohort_contributions", {}) or {})
    return clamp_unit_interval(max(0.0, float(cohort_contributions.get(cohort_name, 0.0) or 0.0)))


def _cohort_penalty(agent_contribution_summary: dict[str, Any], cohort_name: str) -> float:
    cohort_contributions = dict(agent_contribution_summary.get("cohort_contributions", {}) or {})
    return clamp_unit_interval(max(0.0, -float(cohort_contributions.get(cohort_name, 0.0) or 0.0)))


def _resolve_watchlist_zero_catalyst_penalty(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    profile: Any,
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    penalty = clamp_unit_interval(float(profile.watchlist_zero_catalyst_penalty or 0.0))
    default_result = {
        "enabled": penalty > 0.0,
        "eligible": False,
        "applied": False,
        "candidate_source": source,
        "gate_hits": {},
        "effective_penalty": 0.0,
    }
    if penalty <= 0.0 or source != "layer_c_watchlist":
        return default_result

    catalyst_freshness_max = clamp_unit_interval(float(profile.watchlist_zero_catalyst_catalyst_freshness_max or 0.0))
    close_strength_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_close_strength_min or 0.0))
    layer_c_alignment_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_layer_c_alignment_min or 0.0))
    sector_resonance_min = clamp_unit_interval(float(profile.watchlist_zero_catalyst_sector_resonance_min or 0.0))
    gate_hits = {
        "candidate_source": source == "layer_c_watchlist",
        "catalyst_freshness": catalyst_freshness <= catalyst_freshness_max,
        "close_strength": close_strength >= close_strength_min,
        "layer_c_alignment": layer_c_alignment >= layer_c_alignment_min,
        "sector_resonance": sector_resonance >= sector_resonance_min,
    }
    eligible = all(gate_hits.values())
    return {
        "enabled": True,
        "eligible": eligible,
        "applied": eligible,
        "candidate_source": source,
        "gate_hits": gate_hits,
        "effective_penalty": penalty if eligible else 0.0,
    }


def _build_target_input_from_item(*, trade_date: str, item: LayerCResult, included_in_buy_orders: bool) -> TargetEvaluationInput:
    return TargetEvaluationInput(
        trade_date=trade_date,
        ticker=item.ticker,
        score_b=float(item.score_b),
        score_c=float(item.score_c),
        score_final=float(item.score_final),
        quality_score=float(item.quality_score),
        layer_c_decision=str(item.decision or ""),
        bc_conflict=item.bc_conflict,
        strategy_signals={name: signal for name, signal in dict(item.strategy_signals or {}).items()},
        agent_contribution_summary=dict(item.agent_contribution_summary or {}),
        execution_constraints={"included_in_buy_orders": bool(included_in_buy_orders)},
        replay_context={"source": "layer_c_watchlist"},
    )


def _build_target_input_from_entry(*, trade_date: str, entry: dict[str, Any]) -> TargetEvaluationInput:
    candidate_reason_codes = [
        str(reason)
        for reason in list(entry.get("candidate_reason_codes", entry.get("reasons", [])) or [])
        if str(reason or "").strip()
    ]
    return TargetEvaluationInput(
        trade_date=trade_date,
        ticker=str(entry.get("ticker") or ""),
        score_b=float(entry.get("score_b", 0.0) or 0.0),
        score_c=float(entry.get("score_c", 0.0) or 0.0),
        score_final=float(entry.get("score_final", 0.0) or 0.0),
        quality_score=float(entry.get("quality_score", 0.5) or 0.5),
        layer_c_decision=str(entry.get("decision") or ""),
        bc_conflict=entry.get("bc_conflict"),
        strategy_signals=dict(entry.get("strategy_signals") or {}),
        agent_contribution_summary=dict(entry.get("agent_contribution_summary") or {}),
        replay_context={
            "source": str(entry.get("candidate_source") or "watchlist_filter_diagnostics"),
            "reason": str(entry.get("reason") or ""),
            "candidate_reason_codes": candidate_reason_codes,
            "short_trade_catalyst_relief": dict(entry.get("short_trade_catalyst_relief") or {}),
        },
    )


def _summarize_positive_factor(name: str, value: float) -> str | None:
    if value < 0.45:
        return None
    return f"{name}={value:.2f}"


def _summarize_penalty(name: str, value: float) -> str | None:
    if value < 0.45:
        return None
    return f"{name}={value:.2f}"


def _classify_breakout_stage(*, breakout_freshness: float, trend_acceleration: float, profile: Any) -> tuple[str, bool, bool]:
    selected_gate_pass = breakout_freshness >= float(profile.selected_breakout_freshness_min) and trend_acceleration >= float(profile.selected_trend_acceleration_min)
    near_miss_gate_pass = breakout_freshness >= float(profile.near_miss_breakout_freshness_min) and trend_acceleration >= float(profile.near_miss_trend_acceleration_min)
    if selected_gate_pass:
        return "confirmed_breakout", True, True
    if near_miss_gate_pass:
        return "prepared_breakout", False, True
    return "weak_breakout", False, False


def _collect_breakout_gate_misses(*, breakout_freshness: float, trend_acceleration: float, breakout_min: float, trend_min: float, label: str) -> list[str]:
    misses: list[str] = []
    if breakout_freshness < breakout_min:
        misses.append(f"breakout_freshness_below_{label}_floor")
    if trend_acceleration < trend_min:
        misses.append(f"trend_acceleration_below_{label}_floor")
    return misses


def _resolve_positive_score_weights(profile: Any) -> dict[str, float]:
    configured_weights = {
        "breakout_freshness": float(profile.breakout_freshness_weight),
        "trend_acceleration": float(profile.trend_acceleration_weight),
        "volume_expansion_quality": float(profile.volume_expansion_quality_weight),
        "close_strength": float(profile.close_strength_weight),
        "sector_resonance": float(profile.sector_resonance_weight),
        "catalyst_freshness": float(profile.catalyst_freshness_weight),
        "layer_c_alignment": float(profile.layer_c_alignment_weight),
    }
    total_weight = sum(max(0.0, value) for value in configured_weights.values())
    if total_weight <= 0:
        unit_weight = round(1.0 / len(configured_weights), 4)
        return {name: unit_weight for name in configured_weights}
    return {name: max(0.0, value) / total_weight for name, value in configured_weights.items()}


def _build_short_trade_target_snapshot(input_data: TargetEvaluationInput) -> dict[str, Any]:
    profile = get_active_short_trade_target_profile()
    positive_score_weights = _resolve_positive_score_weights(profile)
    trend_signal = _load_signal(input_data.strategy_signals.get("trend"))
    event_signal = _load_signal(input_data.strategy_signals.get("event_sentiment"))
    fundamental_signal = _load_signal(input_data.strategy_signals.get("fundamental"))
    mean_reversion_signal = _load_signal(input_data.strategy_signals.get("mean_reversion"))

    momentum_strength = _subfactor_positive_strength(trend_signal, "momentum")
    adx_strength = _subfactor_positive_strength(trend_signal, "adx_strength")
    ema_strength = _subfactor_positive_strength(trend_signal, "ema_alignment")
    volatility_strength = _subfactor_positive_strength(trend_signal, "volatility")
    long_trend_strength = _subfactor_positive_strength(trend_signal, "long_trend_alignment")
    event_freshness_strength = _subfactor_positive_strength(event_signal, "event_freshness")
    news_sentiment_strength = _subfactor_positive_strength(event_signal, "news_sentiment")
    event_signal_strength = _positive_strength(event_signal)
    mean_reversion_strength = _positive_strength(mean_reversion_signal)

    analyst_alignment = _cohort_alignment(input_data.agent_contribution_summary, "analyst")
    investor_alignment = _cohort_alignment(input_data.agent_contribution_summary, "investor")
    analyst_penalty = _cohort_penalty(input_data.agent_contribution_summary, "analyst")
    investor_penalty = _cohort_penalty(input_data.agent_contribution_summary, "investor")
    score_b_strength = _normalize_score(input_data.score_b)
    score_c_strength = _normalize_score(input_data.score_c)
    score_final_strength = _normalize_score(input_data.score_final)

    breakout_freshness = clamp_unit_interval((0.40 * momentum_strength) + (0.35 * event_freshness_strength) + (0.25 * event_signal_strength))
    trend_acceleration = clamp_unit_interval((0.40 * momentum_strength) + (0.35 * adx_strength) + (0.25 * ema_strength))
    volume_expansion_quality = clamp_unit_interval((0.55 * volatility_strength) + (0.25 * momentum_strength) + (0.20 * event_signal_strength))
    close_strength = clamp_unit_interval((0.55 * ema_strength) + (0.25 * momentum_strength) + (0.20 * score_b_strength))
    sector_resonance = clamp_unit_interval((0.45 * analyst_alignment) + (0.20 * investor_alignment) + (0.20 * score_c_strength) + (0.15 * event_signal_strength))
    raw_catalyst_freshness = clamp_unit_interval((0.65 * event_freshness_strength) + (0.35 * news_sentiment_strength))
    layer_c_alignment = clamp_unit_interval((0.55 * score_c_strength) + (0.25 * analyst_alignment) + (0.20 * clamp_unit_interval(1.0 if input_data.layer_c_decision != "avoid" else 0.0)))
    profitability_relief = _resolve_profitability_relief(
        input_data=input_data,
        fundamental_signal=fundamental_signal,
        breakout_freshness=breakout_freshness,
        catalyst_freshness=raw_catalyst_freshness,
        sector_resonance=sector_resonance,
        profile=profile,
    )
    catalyst_relief = _resolve_upstream_shadow_catalyst_relief(
        input_data=input_data,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        catalyst_freshness=raw_catalyst_freshness,
        profitability_hard_cliff=bool(profitability_relief["hard_cliff"]),
        profile=profile,
    )
    catalyst_freshness = float(catalyst_relief["effective_catalyst_freshness"])
    effective_near_miss_threshold = float(catalyst_relief["effective_near_miss_threshold"])
    layer_c_avoid_penalty = float(profitability_relief["effective_avoid_penalty"])
    watchlist_zero_catalyst_penalty = _resolve_watchlist_zero_catalyst_penalty(
        input_data=input_data,
        catalyst_freshness=raw_catalyst_freshness,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        profile=profile,
    )
    effective_watchlist_zero_catalyst_penalty = float(watchlist_zero_catalyst_penalty["effective_penalty"])

    stale_trend_repair_penalty = clamp_unit_interval((0.45 * mean_reversion_strength) + (0.35 * long_trend_strength) + (0.20 * max(0.0, long_trend_strength - breakout_freshness)))
    overhead_supply_penalty = clamp_unit_interval((0.45 if input_data.bc_conflict in profile.overhead_conflict_penalty_conflicts else 0.0) + (0.35 * analyst_penalty) + (0.20 * investor_penalty))
    extension_without_room_penalty = clamp_unit_interval((0.45 * long_trend_strength) + (0.35 * max(0.0, volatility_strength - catalyst_freshness)) + (0.20 * clamp_unit_interval((score_final_strength - 0.72) / 0.28)))

    weighted_positive_contributions = {
        "breakout_freshness": round(positive_score_weights["breakout_freshness"] * breakout_freshness, 4),
        "trend_acceleration": round(positive_score_weights["trend_acceleration"] * trend_acceleration, 4),
        "volume_expansion_quality": round(positive_score_weights["volume_expansion_quality"] * volume_expansion_quality, 4),
        "close_strength": round(positive_score_weights["close_strength"] * close_strength, 4),
        "sector_resonance": round(positive_score_weights["sector_resonance"] * sector_resonance, 4),
        "catalyst_freshness": round(positive_score_weights["catalyst_freshness"] * catalyst_freshness, 4),
        "layer_c_alignment": round(positive_score_weights["layer_c_alignment"] * layer_c_alignment, 4),
    }
    weighted_negative_contributions = {
        "stale_trend_repair_penalty": round(profile.stale_score_penalty_weight * stale_trend_repair_penalty, 4),
        "overhead_supply_penalty": round(profile.overhead_score_penalty_weight * overhead_supply_penalty, 4),
        "extension_without_room_penalty": round(profile.extension_score_penalty_weight * extension_without_room_penalty, 4),
        "layer_c_avoid_penalty": round(layer_c_avoid_penalty, 4),
        "watchlist_zero_catalyst_penalty": round(effective_watchlist_zero_catalyst_penalty, 4),
    }
    total_positive_contribution = round(sum(weighted_positive_contributions.values()), 4)
    total_negative_contribution = round(sum(weighted_negative_contributions.values()), 4)

    score_target = clamp_unit_interval(
        (positive_score_weights["breakout_freshness"] * breakout_freshness)
        + (positive_score_weights["trend_acceleration"] * trend_acceleration)
        + (positive_score_weights["volume_expansion_quality"] * volume_expansion_quality)
        + (positive_score_weights["close_strength"] * close_strength)
        + (positive_score_weights["sector_resonance"] * sector_resonance)
        + (positive_score_weights["catalyst_freshness"] * catalyst_freshness)
        + (positive_score_weights["layer_c_alignment"] * layer_c_alignment)
        - (profile.stale_score_penalty_weight * stale_trend_repair_penalty)
        - (profile.overhead_score_penalty_weight * overhead_supply_penalty)
        - (profile.extension_score_penalty_weight * extension_without_room_penalty)
        - layer_c_avoid_penalty
        - effective_watchlist_zero_catalyst_penalty
    )

    positive_tags: list[str] = []
    negative_tags: list[str] = []
    blockers: list[str] = []
    gate_status = {
        "data": "pass",
        "execution": "pass" if input_data.execution_constraints.get("included_in_buy_orders") else "proxy_only",
        "structural": "pass",
        "score": "fail",
    }

    if trend_signal is None or float(trend_signal.completeness) <= 0:
        blockers.append("missing_trend_signal")
        gate_status["data"] = "fail"
    if event_signal is None or float(event_signal.completeness) <= 0:
        negative_tags.append("event_signal_incomplete")
    if input_data.layer_c_decision == "avoid":
        negative_tags.append("layer_c_avoid_signal")
    if profitability_relief["hard_cliff"]:
        negative_tags.append("profitability_hard_cliff")
    if profitability_relief["relief_applied"]:
        positive_tags.append("profitability_relief_applied")
    elif profitability_relief["relief_enabled"] and profitability_relief["hard_cliff"] and input_data.layer_c_decision == "avoid":
        negative_tags.append("profitability_relief_not_triggered")
    if catalyst_relief["applied"]:
        positive_tags.append("upstream_shadow_catalyst_relief_applied")
    elif catalyst_relief["enabled"] and raw_catalyst_freshness < float(catalyst_relief["catalyst_freshness_floor"]):
        negative_tags.append("upstream_shadow_catalyst_relief_not_triggered")
    if watchlist_zero_catalyst_penalty["applied"]:
        negative_tags.append("watchlist_zero_catalyst_penalty_applied")
    if input_data.bc_conflict in profile.hard_block_bearish_conflicts:
        blockers.append("layer_c_bearish_conflict")
        gate_status["structural"] = "fail"
    if _signal_signed_strength(trend_signal) <= 0.0:
        blockers.append("trend_not_constructive")
        gate_status["structural"] = "fail"
    if stale_trend_repair_penalty >= profile.stale_penalty_block_threshold:
        blockers.append("stale_trend_repair_penalty")
        gate_status["structural"] = "fail"
    if overhead_supply_penalty >= profile.overhead_penalty_block_threshold:
        blockers.append("overhead_supply_penalty")
        gate_status["structural"] = "fail"
    if extension_without_room_penalty >= profile.extension_penalty_block_threshold:
        blockers.append("extension_without_room_penalty")
        gate_status["structural"] = "fail"

    if breakout_freshness >= 0.50:
        positive_tags.append("fresh_breakout_candidate")
    if trend_acceleration >= 0.50:
        positive_tags.append("trend_acceleration_confirmed")
    if catalyst_freshness >= 0.45:
        positive_tags.append("fresh_catalyst_support")
    if sector_resonance >= 0.45:
        positive_tags.append("sector_alignment_support")
    if input_data.execution_constraints.get("included_in_buy_orders"):
        positive_tags.append("execution_bridge_ready")

    return {
        "profile": profile,
        "breakout_freshness": breakout_freshness,
        "trend_acceleration": trend_acceleration,
        "volume_expansion_quality": volume_expansion_quality,
        "close_strength": close_strength,
        "sector_resonance": sector_resonance,
        "raw_catalyst_freshness": raw_catalyst_freshness,
        "catalyst_freshness": catalyst_freshness,
        "layer_c_alignment": layer_c_alignment,
        "effective_near_miss_threshold": effective_near_miss_threshold,
        "profitability_hard_cliff": profitability_relief["hard_cliff"],
        "profitability_positive_count": profitability_relief["profitability_positive_count"],
        "profitability_confidence": profitability_relief["profitability_confidence"],
        "profitability_relief_enabled": profitability_relief["relief_enabled"],
        "profitability_relief_gate_hits": profitability_relief["relief_gate_hits"],
        "profitability_relief_eligible": profitability_relief["relief_eligible"],
        "profitability_relief_applied": profitability_relief["relief_applied"],
        "profitability_relief_soft_penalty": profitability_relief["soft_penalty"],
        "base_layer_c_avoid_penalty": profitability_relief["base_layer_c_avoid_penalty"],
        "layer_c_avoid_penalty": layer_c_avoid_penalty,
        "watchlist_zero_catalyst_guard": watchlist_zero_catalyst_penalty,
        "watchlist_zero_catalyst_penalty": effective_watchlist_zero_catalyst_penalty,
        "upstream_shadow_catalyst_relief_enabled": catalyst_relief["enabled"],
        "upstream_shadow_catalyst_relief_gate_hits": catalyst_relief["gate_hits"],
        "upstream_shadow_catalyst_relief_eligible": catalyst_relief["eligible"],
        "upstream_shadow_catalyst_relief_applied": catalyst_relief["applied"],
        "upstream_shadow_catalyst_relief_reason": catalyst_relief["reason"],
        "upstream_shadow_catalyst_relief_catalyst_freshness_floor": catalyst_relief["catalyst_freshness_floor"],
        "upstream_shadow_catalyst_relief_base_near_miss_threshold": catalyst_relief["base_near_miss_threshold"],
        "upstream_shadow_catalyst_relief_near_miss_threshold_override": catalyst_relief["near_miss_threshold_override"],
        "upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff": catalyst_relief["require_no_profitability_hard_cliff"],
        "stale_trend_repair_penalty": stale_trend_repair_penalty,
        "overhead_supply_penalty": overhead_supply_penalty,
        "extension_without_room_penalty": extension_without_room_penalty,
        "positive_score_weights": positive_score_weights,
        "weighted_positive_contributions": weighted_positive_contributions,
        "weighted_negative_contributions": weighted_negative_contributions,
        "total_positive_contribution": total_positive_contribution,
        "total_negative_contribution": total_negative_contribution,
        "score_target": score_target,
        "positive_tags": positive_tags,
        "negative_tags": negative_tags,
        "blockers": blockers,
        "gate_status": gate_status,
        "score_b_strength": score_b_strength,
        "score_c_strength": score_c_strength,
        "score_final_strength": score_final_strength,
        "momentum_strength": momentum_strength,
        "adx_strength": adx_strength,
        "ema_strength": ema_strength,
        "volatility_strength": volatility_strength,
        "long_trend_strength": long_trend_strength,
        "event_freshness_strength": event_freshness_strength,
        "news_sentiment_strength": news_sentiment_strength,
        "event_signal_strength": event_signal_strength,
        "mean_reversion_strength": mean_reversion_strength,
        "analyst_alignment": analyst_alignment,
        "investor_alignment": investor_alignment,
        "analyst_penalty": analyst_penalty,
        "investor_penalty": investor_penalty,
    }


def build_short_trade_target_snapshot_from_entry(
    *,
    trade_date: str,
    entry: dict[str, Any],
    profile_name: str | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if profile_name is not None or profile_overrides:
        with use_short_trade_target_profile(profile_name=profile_name or "default", overrides=profile_overrides):
            return build_short_trade_target_snapshot_from_entry(
                trade_date=trade_date,
                entry=entry,
            )
    return _build_short_trade_target_snapshot(_build_target_input_from_entry(trade_date=trade_date, entry=entry))


def _evaluate_short_trade_target(input_data: TargetEvaluationInput, *, rank_hint: int | None = None) -> TargetEvaluationResult:
    snapshot = _build_short_trade_target_snapshot(input_data)
    profile = snapshot["profile"]
    breakout_freshness = float(snapshot["breakout_freshness"])
    trend_acceleration = float(snapshot["trend_acceleration"])
    raw_catalyst_freshness = float(snapshot["raw_catalyst_freshness"])
    catalyst_freshness = float(snapshot["catalyst_freshness"])
    score_target = float(snapshot["score_target"])
    effective_near_miss_threshold = float(snapshot["effective_near_miss_threshold"])
    base_layer_c_avoid_penalty = float(snapshot["base_layer_c_avoid_penalty"])
    layer_c_avoid_penalty = float(snapshot["layer_c_avoid_penalty"])
    watchlist_zero_catalyst_guard = dict(snapshot["watchlist_zero_catalyst_guard"])
    effective_watchlist_zero_catalyst_penalty = float(snapshot["watchlist_zero_catalyst_penalty"])
    profitability_hard_cliff = bool(snapshot["profitability_hard_cliff"])
    profitability_positive_count = snapshot["profitability_positive_count"]
    profitability_confidence = float(snapshot["profitability_confidence"])
    profitability_relief_enabled = bool(snapshot["profitability_relief_enabled"])
    profitability_relief_gate_hits = dict(snapshot["profitability_relief_gate_hits"])
    profitability_relief_eligible = bool(snapshot["profitability_relief_eligible"])
    profitability_relief_applied = bool(snapshot["profitability_relief_applied"])
    profitability_relief_soft_penalty = float(snapshot["profitability_relief_soft_penalty"])
    upstream_shadow_catalyst_relief_enabled = bool(snapshot["upstream_shadow_catalyst_relief_enabled"])
    upstream_shadow_catalyst_relief_gate_hits = dict(snapshot["upstream_shadow_catalyst_relief_gate_hits"])
    upstream_shadow_catalyst_relief_eligible = bool(snapshot["upstream_shadow_catalyst_relief_eligible"])
    upstream_shadow_catalyst_relief_applied = bool(snapshot["upstream_shadow_catalyst_relief_applied"])
    upstream_shadow_catalyst_relief_reason = str(snapshot["upstream_shadow_catalyst_relief_reason"])
    upstream_shadow_catalyst_relief_catalyst_freshness_floor = float(snapshot["upstream_shadow_catalyst_relief_catalyst_freshness_floor"])
    upstream_shadow_catalyst_relief_base_near_miss_threshold = float(snapshot["upstream_shadow_catalyst_relief_base_near_miss_threshold"])
    upstream_shadow_catalyst_relief_near_miss_threshold_override = float(snapshot["upstream_shadow_catalyst_relief_near_miss_threshold_override"])
    upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff = bool(snapshot["upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff"])
    stale_trend_repair_penalty = float(snapshot["stale_trend_repair_penalty"])
    overhead_supply_penalty = float(snapshot["overhead_supply_penalty"])
    extension_without_room_penalty = float(snapshot["extension_without_room_penalty"])
    weighted_positive_contributions = dict(snapshot["weighted_positive_contributions"])
    weighted_negative_contributions = dict(snapshot["weighted_negative_contributions"])
    total_positive_contribution = float(snapshot["total_positive_contribution"])
    total_negative_contribution = float(snapshot["total_negative_contribution"])
    positive_tags = list(snapshot["positive_tags"])
    negative_tags = list(snapshot["negative_tags"])
    blockers = list(snapshot["blockers"])
    gate_status = dict(snapshot["gate_status"])
    score_b_strength = float(snapshot["score_b_strength"])
    score_c_strength = float(snapshot["score_c_strength"])
    score_final_strength = float(snapshot["score_final_strength"])
    momentum_strength = float(snapshot["momentum_strength"])
    adx_strength = float(snapshot["adx_strength"])
    ema_strength = float(snapshot["ema_strength"])
    volatility_strength = float(snapshot["volatility_strength"])
    long_trend_strength = float(snapshot["long_trend_strength"])
    event_freshness_strength = float(snapshot["event_freshness_strength"])
    news_sentiment_strength = float(snapshot["news_sentiment_strength"])
    event_signal_strength = float(snapshot["event_signal_strength"])
    mean_reversion_strength = float(snapshot["mean_reversion_strength"])
    analyst_alignment = float(snapshot["analyst_alignment"])
    investor_alignment = float(snapshot["investor_alignment"])
    analyst_penalty = float(snapshot["analyst_penalty"])
    investor_penalty = float(snapshot["investor_penalty"])
    volume_expansion_quality = float(snapshot["volume_expansion_quality"])
    close_strength = float(snapshot["close_strength"])
    sector_resonance = float(snapshot["sector_resonance"])
    layer_c_alignment = float(snapshot["layer_c_alignment"])
    positive_score_weights = dict(snapshot["positive_score_weights"])
    breakout_stage, selected_breakout_gate_pass, near_miss_breakout_gate_pass = _classify_breakout_stage(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        profile=profile,
    )

    if blockers:
        decision = "blocked" if gate_status["data"] == "fail" or "layer_c_bearish_conflict" in blockers or "trend_not_constructive" in blockers else "rejected"
    elif score_target >= profile.select_threshold and selected_breakout_gate_pass:
        decision = "selected"
        gate_status["score"] = "pass"
    elif score_target >= profile.select_threshold and near_miss_breakout_gate_pass:
        decision = "near_miss"
        gate_status["score"] = "near_miss"
    elif score_target >= effective_near_miss_threshold and near_miss_breakout_gate_pass:
        decision = "near_miss"
        gate_status["score"] = "near_miss"
    else:
        decision = "rejected"

    if breakout_stage == "confirmed_breakout":
        positive_tags.append("confirmed_breakout_stage")
    elif breakout_stage == "prepared_breakout":
        positive_tags.append("prepared_breakout_stage")

    top_reasons = trim_reasons(
        [
            reason
            for reason in [
                _summarize_positive_factor("breakout_freshness", breakout_freshness),
                _summarize_positive_factor("trend_acceleration", trend_acceleration),
                _summarize_positive_factor("catalyst_freshness", raw_catalyst_freshness),
                upstream_shadow_catalyst_relief_reason if upstream_shadow_catalyst_relief_applied else None,
                "profitability_relief_applied" if profitability_relief_applied else None,
                "profitability_hard_cliff" if profitability_hard_cliff and not profitability_relief_applied else None,
                breakout_stage,
                _summarize_penalty("layer_c_avoid_penalty", layer_c_avoid_penalty),
                _summarize_penalty("stale_trend_repair_penalty", stale_trend_repair_penalty),
                _summarize_penalty("overhead_supply_penalty", overhead_supply_penalty),
                _summarize_penalty("extension_without_room_penalty", extension_without_room_penalty),
                "watchlist_zero_catalyst_penalty_applied" if watchlist_zero_catalyst_guard["applied"] else None,
                f"score_short={score_target:.2f}",
            ]
            if reason is not None
        ]
    )

    rejection_reasons = trim_reasons(
        blockers
        if blockers
        else _collect_breakout_gate_misses(
            breakout_freshness=breakout_freshness,
            trend_acceleration=trend_acceleration,
            breakout_min=float(profile.near_miss_breakout_freshness_min),
            trend_min=float(profile.near_miss_trend_acceleration_min),
            label="near_miss",
        )
        if decision == "rejected" and score_target >= effective_near_miss_threshold and not near_miss_breakout_gate_pass
        else ["score_short_below_threshold"]
        if decision == "rejected"
        else []
    )
    confidence = derive_confidence(score_target, breakout_freshness, trend_acceleration, catalyst_freshness, float(input_data.quality_score or 0.0))

    return TargetEvaluationResult(
        target_type="short_trade",
        decision=decision,
        score_target=score_target,
        confidence=confidence,
        rank_hint=rank_hint,
        positive_tags=positive_tags,
        negative_tags=trim_reasons(negative_tags),
        blockers=trim_reasons(blockers),
        top_reasons=top_reasons,
        rejection_reasons=rejection_reasons,
        gate_status=gate_status,
        expected_holding_window="t1_short_trade",
        preferred_entry_mode="next_day_breakout_confirmation",
        metrics_payload={
            "score_b": round(float(input_data.score_b), 4),
            "score_c": round(float(input_data.score_c), 4),
            "score_final": round(float(input_data.score_final), 4),
            "quality_score": round(float(input_data.quality_score), 4),
            "score_b_strength": round(score_b_strength, 4),
            "score_c_strength": round(score_c_strength, 4),
            "score_final_strength": round(score_final_strength, 4),
            "momentum_strength": round(momentum_strength, 4),
            "adx_strength": round(adx_strength, 4),
            "ema_strength": round(ema_strength, 4),
            "volatility_strength": round(volatility_strength, 4),
            "long_trend_strength": round(long_trend_strength, 4),
            "event_freshness_strength": round(event_freshness_strength, 4),
            "news_sentiment_strength": round(news_sentiment_strength, 4),
            "event_signal_strength": round(event_signal_strength, 4),
            "mean_reversion_strength": round(mean_reversion_strength, 4),
            "analyst_alignment": round(analyst_alignment, 4),
            "investor_alignment": round(investor_alignment, 4),
            "analyst_penalty": round(analyst_penalty, 4),
            "investor_penalty": round(investor_penalty, 4),
            "breakout_freshness": round(breakout_freshness, 4),
            "trend_acceleration": round(trend_acceleration, 4),
            "volume_expansion_quality": round(volume_expansion_quality, 4),
            "close_strength": round(close_strength, 4),
            "sector_resonance": round(sector_resonance, 4),
            "catalyst_freshness": round(raw_catalyst_freshness, 4),
            "effective_catalyst_freshness": round(catalyst_freshness, 4),
            "layer_c_alignment": round(layer_c_alignment, 4),
            "positive_score_weights": {name: round(float(value), 4) for name, value in positive_score_weights.items()},
            "breakout_stage": breakout_stage,
            "selected_breakout_gate_pass": selected_breakout_gate_pass,
            "near_miss_breakout_gate_pass": near_miss_breakout_gate_pass,
            "profitability_hard_cliff": profitability_hard_cliff,
            "profitability_positive_count": profitability_positive_count,
            "profitability_confidence": round(profitability_confidence, 4),
            "profitability_relief_enabled": profitability_relief_enabled,
            "profitability_relief_gate_hits": profitability_relief_gate_hits,
            "profitability_relief_eligible": profitability_relief_eligible,
            "profitability_relief_applied": profitability_relief_applied,
            "base_layer_c_avoid_penalty": round(base_layer_c_avoid_penalty, 4),
            "profitability_relief_soft_penalty": round(profitability_relief_soft_penalty, 4),
            "layer_c_avoid_penalty": round(layer_c_avoid_penalty, 4),
            "watchlist_zero_catalyst_penalty": round(effective_watchlist_zero_catalyst_penalty, 4),
            "watchlist_zero_catalyst_guard": {
                "enabled": bool(watchlist_zero_catalyst_guard["enabled"]),
                "eligible": bool(watchlist_zero_catalyst_guard["eligible"]),
                "applied": bool(watchlist_zero_catalyst_guard["applied"]),
                "candidate_source": str(watchlist_zero_catalyst_guard["candidate_source"]),
                "gate_hits": dict(watchlist_zero_catalyst_guard["gate_hits"]),
            },
            "upstream_shadow_catalyst_relief_enabled": upstream_shadow_catalyst_relief_enabled,
            "upstream_shadow_catalyst_relief_gate_hits": upstream_shadow_catalyst_relief_gate_hits,
            "upstream_shadow_catalyst_relief_eligible": upstream_shadow_catalyst_relief_eligible,
            "upstream_shadow_catalyst_relief_applied": upstream_shadow_catalyst_relief_applied,
            "upstream_shadow_catalyst_relief_reason": upstream_shadow_catalyst_relief_reason,
            "upstream_shadow_catalyst_relief_catalyst_freshness_floor": round(upstream_shadow_catalyst_relief_catalyst_freshness_floor, 4),
            "upstream_shadow_catalyst_relief_base_near_miss_threshold": round(upstream_shadow_catalyst_relief_base_near_miss_threshold, 4),
            "upstream_shadow_catalyst_relief_near_miss_threshold_override": round(upstream_shadow_catalyst_relief_near_miss_threshold_override, 4),
            "upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff": upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff,
            "stale_trend_repair_penalty": round(stale_trend_repair_penalty, 4),
            "overhead_supply_penalty": round(overhead_supply_penalty, 4),
            "extension_without_room_penalty": round(extension_without_room_penalty, 4),
            "weighted_positive_contributions": weighted_positive_contributions,
            "weighted_negative_contributions": weighted_negative_contributions,
            "total_positive_contribution": total_positive_contribution,
            "total_negative_contribution": total_negative_contribution,
            "thresholds": {
                "profile_name": profile.name,
                "select_threshold": round(float(profile.select_threshold), 4),
                "near_miss_threshold": round(effective_near_miss_threshold, 4),
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
                "effective_positive_score_weights": {name: round(float(value), 4) for name, value in positive_score_weights.items()},
                "stale_penalty_block_threshold": round(float(profile.stale_penalty_block_threshold), 4),
                "overhead_penalty_block_threshold": round(float(profile.overhead_penalty_block_threshold), 4),
                "extension_penalty_block_threshold": round(float(profile.extension_penalty_block_threshold), 4),
                "layer_c_avoid_penalty": round(float(profile.layer_c_avoid_penalty), 4),
                "profitability_relief_enabled": bool(profile.profitability_relief_enabled),
                "profitability_relief_breakout_freshness_min": round(float(profile.profitability_relief_breakout_freshness_min), 4),
                "profitability_relief_catalyst_freshness_min": round(float(profile.profitability_relief_catalyst_freshness_min), 4),
                "profitability_relief_sector_resonance_min": round(float(profile.profitability_relief_sector_resonance_min), 4),
                "profitability_relief_avoid_penalty": round(float(profile.profitability_relief_avoid_penalty), 4),
                "stale_score_penalty_weight": round(float(profile.stale_score_penalty_weight), 4),
                "overhead_score_penalty_weight": round(float(profile.overhead_score_penalty_weight), 4),
                "extension_score_penalty_weight": round(float(profile.extension_score_penalty_weight), 4),
                "watchlist_zero_catalyst_penalty": round(float(profile.watchlist_zero_catalyst_penalty), 4),
                "watchlist_zero_catalyst_catalyst_freshness_max": round(float(profile.watchlist_zero_catalyst_catalyst_freshness_max), 4),
                "watchlist_zero_catalyst_close_strength_min": round(float(profile.watchlist_zero_catalyst_close_strength_min), 4),
                "watchlist_zero_catalyst_layer_c_alignment_min": round(float(profile.watchlist_zero_catalyst_layer_c_alignment_min), 4),
                "watchlist_zero_catalyst_sector_resonance_min": round(float(profile.watchlist_zero_catalyst_sector_resonance_min), 4),
                "hard_block_bearish_conflicts": sorted(str(item) for item in profile.hard_block_bearish_conflicts),
                "overhead_conflict_penalty_conflicts": sorted(str(item) for item in profile.overhead_conflict_penalty_conflicts),
                "upstream_shadow_catalyst_relief_enabled": upstream_shadow_catalyst_relief_enabled,
                "upstream_shadow_catalyst_relief_applied": upstream_shadow_catalyst_relief_applied,
                "upstream_shadow_catalyst_relief_catalyst_freshness_floor": round(upstream_shadow_catalyst_relief_catalyst_freshness_floor, 4),
                "upstream_shadow_catalyst_relief_near_miss_threshold_override": round(upstream_shadow_catalyst_relief_near_miss_threshold_override, 4),
            },
        },
        explainability_payload={
            "source": str(input_data.replay_context.get("source") or "short_trade_target_rules_v1"),
            "target_profile": profile.name,
            "breakout_stage": breakout_stage,
            "trade_date": input_data.trade_date,
            "layer_c_decision": input_data.layer_c_decision,
            "bc_conflict": input_data.bc_conflict,
            "candidate_source": str(input_data.replay_context.get("source") or ""),
            "available_strategy_signals": sorted(str(name) for name in dict(input_data.strategy_signals or {}).keys()),
            "profitability_relief": {
                "enabled": profitability_relief_enabled,
                "hard_cliff": profitability_hard_cliff,
                "eligible": profitability_relief_eligible,
                "applied": profitability_relief_applied,
                "gate_hits": profitability_relief_gate_hits,
                "base_layer_c_avoid_penalty": round(base_layer_c_avoid_penalty, 4),
                "effective_layer_c_avoid_penalty": round(layer_c_avoid_penalty, 4),
                "soft_penalty": round(profitability_relief_soft_penalty, 4),
            },
            "upstream_shadow_catalyst_relief": {
                "enabled": upstream_shadow_catalyst_relief_enabled,
                "eligible": upstream_shadow_catalyst_relief_eligible,
                "applied": upstream_shadow_catalyst_relief_applied,
                "reason": upstream_shadow_catalyst_relief_reason,
                "gate_hits": upstream_shadow_catalyst_relief_gate_hits,
                "base_catalyst_freshness": round(raw_catalyst_freshness, 4),
                "effective_catalyst_freshness": round(catalyst_freshness, 4),
                "catalyst_freshness_floor": round(upstream_shadow_catalyst_relief_catalyst_freshness_floor, 4),
                "base_near_miss_threshold": round(upstream_shadow_catalyst_relief_base_near_miss_threshold, 4),
                "effective_near_miss_threshold": round(effective_near_miss_threshold, 4),
                "near_miss_threshold_override": round(upstream_shadow_catalyst_relief_near_miss_threshold_override, 4),
                "require_no_profitability_hard_cliff": upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff,
            },
            "watchlist_zero_catalyst_guard": {
                "enabled": bool(watchlist_zero_catalyst_guard["enabled"]),
                "eligible": bool(watchlist_zero_catalyst_guard["eligible"]),
                "applied": bool(watchlist_zero_catalyst_guard["applied"]),
                "candidate_source": str(watchlist_zero_catalyst_guard["candidate_source"]),
                "gate_hits": dict(watchlist_zero_catalyst_guard["gate_hits"]),
                "effective_penalty": round(effective_watchlist_zero_catalyst_penalty, 4),
            },
            "replay_context": dict(input_data.replay_context or {}),
        },
    )


def evaluate_short_trade_selected_target(
    *,
    trade_date: str,
    item: LayerCResult,
    rank_hint: int | None = None,
    included_in_buy_orders: bool = False,
    profile_name: str | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> TargetEvaluationResult:
    if profile_name is not None or profile_overrides:
        with use_short_trade_target_profile(profile_name=profile_name or "default", overrides=profile_overrides):
            return evaluate_short_trade_selected_target(
                trade_date=trade_date,
                item=item,
                rank_hint=rank_hint,
                included_in_buy_orders=included_in_buy_orders,
            )
    return _evaluate_short_trade_target(
        _build_target_input_from_item(trade_date=trade_date, item=item, included_in_buy_orders=included_in_buy_orders),
        rank_hint=rank_hint,
    )


def evaluate_short_trade_rejected_target(
    *,
    trade_date: str,
    entry: dict[str, Any],
    rank_hint: int | None = None,
    profile_name: str | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> TargetEvaluationResult:
    if profile_name is not None or profile_overrides:
        with use_short_trade_target_profile(profile_name=profile_name or "default", overrides=profile_overrides):
            return evaluate_short_trade_rejected_target(
                trade_date=trade_date,
                entry=entry,
                rank_hint=rank_hint,
            )
    return _evaluate_short_trade_target(_build_target_input_from_entry(trade_date=trade_date, entry=entry), rank_hint=rank_hint)
