from __future__ import annotations

from typing import Any

from src.execution.models import LayerCResult
from src.screening.models import StrategySignal
from src.targets.explainability import clamp_unit_interval, derive_confidence, trim_reasons
from src.targets.models import TargetEvaluationInput, TargetEvaluationResult


SELECT_THRESHOLD = 0.58
NEAR_MISS_THRESHOLD = 0.46
STALE_PENALTY_BLOCK_THRESHOLD = 0.72
OVERHEAD_PENALTY_BLOCK_THRESHOLD = 0.68
EXTENSION_PENALTY_BLOCK_THRESHOLD = 0.74
STRONG_BEARISH_CONFLICTS = {"b_positive_c_strong_bearish", "b_strong_buy_c_negative"}


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


def _cohort_alignment(agent_contribution_summary: dict[str, Any], cohort_name: str) -> float:
    cohort_contributions = dict(agent_contribution_summary.get("cohort_contributions", {}) or {})
    return clamp_unit_interval(max(0.0, float(cohort_contributions.get(cohort_name, 0.0) or 0.0)))


def _cohort_penalty(agent_contribution_summary: dict[str, Any], cohort_name: str) -> float:
    cohort_contributions = dict(agent_contribution_summary.get("cohort_contributions", {}) or {})
    return clamp_unit_interval(max(0.0, -float(cohort_contributions.get(cohort_name, 0.0) or 0.0)))


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
        replay_context={"source": "watchlist_filter_diagnostics", "reason": str(entry.get("reason") or "")},
    )


def _summarize_positive_factor(name: str, value: float) -> str | None:
    if value < 0.45:
        return None
    return f"{name}={value:.2f}"


def _summarize_penalty(name: str, value: float) -> str | None:
    if value < 0.45:
        return None
    return f"{name}={value:.2f}"


def _evaluate_short_trade_target(input_data: TargetEvaluationInput, *, rank_hint: int | None = None) -> TargetEvaluationResult:
    trend_signal = _load_signal(input_data.strategy_signals.get("trend"))
    event_signal = _load_signal(input_data.strategy_signals.get("event_sentiment"))
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
    catalyst_freshness = clamp_unit_interval((0.65 * event_freshness_strength) + (0.35 * news_sentiment_strength))
    layer_c_alignment = clamp_unit_interval((0.55 * score_c_strength) + (0.25 * analyst_alignment) + (0.20 * clamp_unit_interval(1.0 if input_data.layer_c_decision != "avoid" else 0.0)))

    stale_trend_repair_penalty = clamp_unit_interval((0.45 * mean_reversion_strength) + (0.35 * long_trend_strength) + (0.20 * max(0.0, long_trend_strength - breakout_freshness)))
    overhead_supply_penalty = clamp_unit_interval((0.45 if input_data.bc_conflict in STRONG_BEARISH_CONFLICTS else 0.0) + (0.35 * analyst_penalty) + (0.20 * investor_penalty))
    extension_without_room_penalty = clamp_unit_interval((0.45 * long_trend_strength) + (0.35 * max(0.0, volatility_strength - catalyst_freshness)) + (0.20 * clamp_unit_interval((score_final_strength - 0.72) / 0.28)))

    score_target = clamp_unit_interval(
        (0.22 * breakout_freshness)
        + (0.18 * trend_acceleration)
        + (0.16 * volume_expansion_quality)
        + (0.14 * close_strength)
        + (0.12 * sector_resonance)
        + (0.08 * catalyst_freshness)
        + (0.10 * layer_c_alignment)
        - (0.12 * stale_trend_repair_penalty)
        - (0.10 * overhead_supply_penalty)
        - (0.08 * extension_without_room_penalty)
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
    if input_data.bc_conflict in STRONG_BEARISH_CONFLICTS or input_data.layer_c_decision == "avoid":
        blockers.append("layer_c_bearish_conflict")
        gate_status["structural"] = "fail"
    if _signal_signed_strength(trend_signal) <= 0.0:
        blockers.append("trend_not_constructive")
        gate_status["structural"] = "fail"
    if stale_trend_repair_penalty >= STALE_PENALTY_BLOCK_THRESHOLD:
        blockers.append("stale_trend_repair_penalty")
        gate_status["structural"] = "fail"
    if overhead_supply_penalty >= OVERHEAD_PENALTY_BLOCK_THRESHOLD:
        blockers.append("overhead_supply_penalty")
        gate_status["structural"] = "fail"
    if extension_without_room_penalty >= EXTENSION_PENALTY_BLOCK_THRESHOLD:
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

    if blockers:
        decision = "blocked" if gate_status["data"] == "fail" or "layer_c_bearish_conflict" in blockers or "trend_not_constructive" in blockers else "rejected"
    elif score_target >= SELECT_THRESHOLD and breakout_freshness >= 0.35 and trend_acceleration >= 0.38:
        decision = "selected"
        gate_status["score"] = "pass"
    elif score_target >= NEAR_MISS_THRESHOLD:
        decision = "near_miss"
        gate_status["score"] = "near_miss"
    else:
        decision = "rejected"

    top_reasons = trim_reasons(
        [
            reason
            for reason in [
                _summarize_positive_factor("breakout_freshness", breakout_freshness),
                _summarize_positive_factor("trend_acceleration", trend_acceleration),
                _summarize_positive_factor("catalyst_freshness", catalyst_freshness),
                _summarize_penalty("stale_trend_repair_penalty", stale_trend_repair_penalty),
                _summarize_penalty("overhead_supply_penalty", overhead_supply_penalty),
                _summarize_penalty("extension_without_room_penalty", extension_without_room_penalty),
                f"score_short={score_target:.2f}",
            ]
            if reason is not None
        ]
    )

    rejection_reasons = trim_reasons(blockers if blockers else ["score_short_below_threshold"] if decision == "rejected" else [])
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
            "breakout_freshness": round(breakout_freshness, 4),
            "trend_acceleration": round(trend_acceleration, 4),
            "volume_expansion_quality": round(volume_expansion_quality, 4),
            "close_strength": round(close_strength, 4),
            "sector_resonance": round(sector_resonance, 4),
            "catalyst_freshness": round(catalyst_freshness, 4),
            "layer_c_alignment": round(layer_c_alignment, 4),
            "stale_trend_repair_penalty": round(stale_trend_repair_penalty, 4),
            "overhead_supply_penalty": round(overhead_supply_penalty, 4),
            "extension_without_room_penalty": round(extension_without_room_penalty, 4),
        },
        explainability_payload={
            "source": str(input_data.replay_context.get("source") or "short_trade_target_rules_v1"),
            "trade_date": input_data.trade_date,
            "layer_c_decision": input_data.layer_c_decision,
            "bc_conflict": input_data.bc_conflict,
            "available_strategy_signals": sorted(str(name) for name in dict(input_data.strategy_signals or {}).keys()),
            "replay_context": dict(input_data.replay_context or {}),
        },
    )


def evaluate_short_trade_selected_target(*, trade_date: str, item: LayerCResult, rank_hint: int | None = None, included_in_buy_orders: bool = False) -> TargetEvaluationResult:
    return _evaluate_short_trade_target(
        _build_target_input_from_item(trade_date=trade_date, item=item, included_in_buy_orders=included_in_buy_orders),
        rank_hint=rank_hint,
    )


def evaluate_short_trade_rejected_target(*, trade_date: str, entry: dict[str, Any], rank_hint: int | None = None) -> TargetEvaluationResult:
    return _evaluate_short_trade_target(_build_target_input_from_entry(trade_date=trade_date, entry=entry), rank_hint=rank_hint)