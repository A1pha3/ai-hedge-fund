from __future__ import annotations

import os
from typing import Any
from collections.abc import Mapping

from src.screening.models import StrategySignal


def _get_env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


MERGE_APPROVED_BREAKOUT_UPLIFT_SCORE_B_MIN = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_BREAKOUT_UPLIFT_SCORE_B_MIN", -0.2)
MERGE_APPROVED_BREAKOUT_UPLIFT_TREND_CONFIDENCE_MIN = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_BREAKOUT_UPLIFT_TREND_CONFIDENCE_MIN", 25.0)
MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_CONFIDENCE_MIN = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_CONFIDENCE_MIN", 50.0)
MERGE_APPROVED_BREAKOUT_UPLIFT_MOMENTUM_CONFIDENCE_MIN = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_BREAKOUT_UPLIFT_MOMENTUM_CONFIDENCE_MIN", 55.0)
MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_FRESHNESS_CONFIDENCE_MIN = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_FRESHNESS_CONFIDENCE_MIN", 55.0)
MERGE_APPROVED_BREAKOUT_UPLIFT_TREND_CONFIDENCE_FLOOR = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_BREAKOUT_UPLIFT_TREND_CONFIDENCE_FLOOR", 72.0)
MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_CONFIDENCE_FLOOR = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_CONFIDENCE_FLOOR", 68.0)
MERGE_APPROVED_BREAKOUT_UPLIFT_MOMENTUM_CONFIDENCE_FLOOR = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_BREAKOUT_UPLIFT_MOMENTUM_CONFIDENCE_FLOOR", 78.0)
MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_FRESHNESS_CONFIDENCE_FLOOR = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_FRESHNESS_CONFIDENCE_FLOOR", 82.0)
MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_CONFIDENCE_MIN = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_CONFIDENCE_MIN", 50.0)
MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_CONFIDENCE_FLOOR = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_CONFIDENCE_FLOOR", 74.0)
MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_REGIME_MIN = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_REGIME_MIN", 1.0)
MERGE_APPROVED_VOLUME_UPLIFT_ATR_RATIO_MIN = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_VOLUME_UPLIFT_ATR_RATIO_MIN", 0.06)
MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_MIN = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_MIN", -0.02)
MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_MAX = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_MAX", 0.12)
MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_FLOOR = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_FLOOR", 0.12)
MERGE_APPROVED_ALIGNMENT_UPLIFT_ANALYST_CONTRIBUTION_MAX = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_ALIGNMENT_UPLIFT_ANALYST_CONTRIBUTION_MAX", 0.02)
MERGE_APPROVED_ALIGNMENT_UPLIFT_ANALYST_CONTRIBUTION_FLOOR = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_ALIGNMENT_UPLIFT_ANALYST_CONTRIBUTION_FLOOR", 0.10)
MERGE_APPROVED_ALIGNMENT_UPLIFT_BLEND_B_WEIGHT = _get_env_float("DAILY_PIPELINE_LAYER_C_BLEND_B_WEIGHT", 0.55)
MERGE_APPROVED_ALIGNMENT_UPLIFT_BLEND_C_WEIGHT = _get_env_float("DAILY_PIPELINE_LAYER_C_BLEND_C_WEIGHT", 0.45)
MERGE_APPROVED_SECTOR_UPLIFT_INVESTOR_CONTRIBUTION_MAX = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_SECTOR_UPLIFT_INVESTOR_CONTRIBUTION_MAX", 0.02)
MERGE_APPROVED_SECTOR_UPLIFT_INVESTOR_CONTRIBUTION_FLOOR = _get_env_float("DAILY_PIPELINE_MERGE_APPROVED_SECTOR_UPLIFT_INVESTOR_CONTRIBUTION_FLOOR", 0.14)


def _coerce_signal(payload: StrategySignal | Mapping[str, Any] | None) -> StrategySignal | None:
    if isinstance(payload, StrategySignal):
        return payload
    if isinstance(payload, Mapping) and payload:
        return StrategySignal.model_validate(dict(payload))
    return None


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(100.0, float(value or 0.0)))


def _clone_snapshot(snapshot: Any) -> dict[str, Any]:
    if isinstance(snapshot, Mapping):
        return dict(snapshot)
    return {}


def _signal_snapshot(signal: StrategySignal | None, subfactor_name: str | None = None) -> dict[str, Any]:
    if signal is None:
        return {}
    if subfactor_name is None:
        return {"direction": int(signal.direction), "confidence": _clamp_confidence(signal.confidence), "completeness": float(signal.completeness)}
    snapshot = _clone_snapshot(signal.sub_factors.get(subfactor_name, {}))
    return {
        "direction": int(snapshot.get("direction", 0) or 0),
        "confidence": _clamp_confidence(snapshot.get("confidence", 0.0) or 0.0),
        "completeness": float(snapshot.get("completeness", 1.0) or 1.0),
    }


def _positive_complete(snapshot: dict[str, Any], *, confidence_min: float) -> bool:
    return int(snapshot.get("direction", 0) or 0) > 0 and float(snapshot.get("completeness", 0.0) or 0.0) > 0 and float(snapshot.get("confidence", 0.0) or 0.0) >= confidence_min


def _boost_snapshot(snapshot: dict[str, Any], *, confidence_floor: float) -> tuple[dict[str, Any], bool]:
    updated = dict(snapshot)
    boosted_confidence = max(_clamp_confidence(snapshot.get("confidence", 0.0) or 0.0), _clamp_confidence(confidence_floor))
    changed = boosted_confidence > float(snapshot.get("confidence", 0.0) or 0.0)
    updated["confidence"] = boosted_confidence
    return updated, changed


def _carryover_snapshot(snapshot: dict[str, Any], *, confidence_floor: float) -> tuple[dict[str, Any], bool]:
    updated = dict(snapshot)
    changed = False
    if int(updated.get("direction", 0) or 0) <= 0:
        updated["direction"] = 1
        changed = True
    if float(updated.get("completeness", 0.0) or 0.0) <= 0:
        updated["completeness"] = 1.0
        changed = True
    updated, boosted = _boost_snapshot(updated, confidence_floor=confidence_floor)
    return updated, bool(changed or boosted)


def _metric_value(snapshot: dict[str, Any], name: str) -> float:
    metrics = dict(snapshot.get("metrics") or {})
    return float(metrics.get(name, 0.0) or 0.0)


def _volume_carryover_supported(snapshot: dict[str, Any]) -> bool:
    confidence_ok = _clamp_confidence(snapshot.get("confidence", 0.0) or 0.0) >= MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_CONFIDENCE_MIN
    regime_ok = _metric_value(snapshot, "volatility_regime") >= MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_REGIME_MIN
    atr_ratio_ok = _metric_value(snapshot, "atr_ratio") >= MERGE_APPROVED_VOLUME_UPLIFT_ATR_RATIO_MIN
    return confidence_ok and regime_ok and atr_ratio_ok


def _resolve_alignment_blend_weights() -> tuple[float, float]:
    b_weight = max(0.0, MERGE_APPROVED_ALIGNMENT_UPLIFT_BLEND_B_WEIGHT)
    c_weight = max(0.0, MERGE_APPROVED_ALIGNMENT_UPLIFT_BLEND_C_WEIGHT)
    total = b_weight + c_weight
    if total <= 0:
        return 0.55, 0.45
    return b_weight / total, c_weight / total


def apply_merge_approved_breakout_uplift_to_signal_map(
    strategy_signals: Mapping[str, StrategySignal | Mapping[str, Any]] | None,
    *,
    score_b: float,
) -> tuple[dict[str, StrategySignal], dict[str, Any]]:
    trend_signal = _coerce_signal((strategy_signals or {}).get("trend"))
    event_signal = _coerce_signal((strategy_signals or {}).get("event_sentiment"))
    if event_signal is None:
        event_signal = StrategySignal(direction=0, confidence=0.0, completeness=1.0, sub_factors={})
    momentum_snapshot = _signal_snapshot(trend_signal, "momentum")
    volatility_snapshot = _clone_snapshot((trend_signal.sub_factors or {}).get("volatility", {})) if trend_signal is not None else {}
    event_freshness_snapshot = _signal_snapshot(event_signal, "event_freshness")
    trend_snapshot = _signal_snapshot(trend_signal)
    event_snapshot = _signal_snapshot(event_signal)
    carryover_gate = _positive_complete(trend_snapshot, confidence_min=MERGE_APPROVED_BREAKOUT_UPLIFT_TREND_CONFIDENCE_MIN) and _positive_complete(
        momentum_snapshot,
        confidence_min=MERGE_APPROVED_BREAKOUT_UPLIFT_MOMENTUM_CONFIDENCE_MIN,
    )
    event_signal_supported = _positive_complete(event_snapshot, confidence_min=MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_CONFIDENCE_MIN) or carryover_gate
    event_freshness_supported = _positive_complete(
        event_freshness_snapshot,
        confidence_min=MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_FRESHNESS_CONFIDENCE_MIN,
    ) or carryover_gate
    volume_carryover_gate = carryover_gate and _volume_carryover_supported(volatility_snapshot)
    gate_hits = {
        "score_b": float(score_b) >= MERGE_APPROVED_BREAKOUT_UPLIFT_SCORE_B_MIN,
        "trend_signal": _positive_complete(trend_snapshot, confidence_min=MERGE_APPROVED_BREAKOUT_UPLIFT_TREND_CONFIDENCE_MIN),
        "momentum_subfactor": _positive_complete(momentum_snapshot, confidence_min=MERGE_APPROVED_BREAKOUT_UPLIFT_MOMENTUM_CONFIDENCE_MIN),
        "event_signal": event_signal_supported,
        "event_freshness_subfactor": event_freshness_supported,
        "carryover_gate": carryover_gate,
        "volatility_subfactor": volume_carryover_gate,
    }
    eligible = all(gate_hits[key] for key in ("score_b", "trend_signal", "momentum_subfactor", "event_signal", "event_freshness_subfactor", "carryover_gate"))
    diagnostics = {
        "enabled": True,
        "eligible": eligible,
        "applied": False,
        "gate_hits": gate_hits,
        "score_b": round(float(score_b), 4),
        "before": {
            "trend_confidence": round(float(trend_snapshot.get("confidence", 0.0) or 0.0), 4),
            "event_confidence": round(float(event_snapshot.get("confidence", 0.0) or 0.0), 4),
            "momentum_confidence": round(float(momentum_snapshot.get("confidence", 0.0) or 0.0), 4),
            "event_freshness_confidence": round(float(event_freshness_snapshot.get("confidence", 0.0) or 0.0), 4),
            "volatility_confidence": round(float(volatility_snapshot.get("confidence", 0.0) or 0.0), 4),
        },
    }
    if not eligible or trend_signal is None:
        diagnostics["after"] = dict(diagnostics["before"])
        return {name: _coerce_signal(payload) or StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}) for name, payload in dict(strategy_signals or {}).items()}, diagnostics

    boosted_trend_snapshot, trend_changed = _boost_snapshot(trend_snapshot, confidence_floor=MERGE_APPROVED_BREAKOUT_UPLIFT_TREND_CONFIDENCE_FLOOR)
    boosted_event_snapshot, event_changed = (
        _boost_snapshot(event_snapshot, confidence_floor=MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_CONFIDENCE_FLOOR)
        if _positive_complete(event_snapshot, confidence_min=MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_CONFIDENCE_MIN)
        else _carryover_snapshot(event_snapshot, confidence_floor=MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_CONFIDENCE_FLOOR)
    )
    boosted_momentum_snapshot, momentum_changed = _boost_snapshot(momentum_snapshot, confidence_floor=MERGE_APPROVED_BREAKOUT_UPLIFT_MOMENTUM_CONFIDENCE_FLOOR)
    boosted_volatility_snapshot, volatility_changed = (
        _carryover_snapshot(volatility_snapshot, confidence_floor=MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_CONFIDENCE_FLOOR)
        if volume_carryover_gate
        else (dict(volatility_snapshot), False)
    )
    boosted_event_freshness_snapshot, event_freshness_changed = (
        _boost_snapshot(
            event_freshness_snapshot,
            confidence_floor=MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_FRESHNESS_CONFIDENCE_FLOOR,
        )
        if _positive_complete(event_freshness_snapshot, confidence_min=MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_FRESHNESS_CONFIDENCE_MIN)
        else _carryover_snapshot(
            event_freshness_snapshot,
            confidence_floor=MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_FRESHNESS_CONFIDENCE_FLOOR,
        )
    )

    updated_trend_sub_factors = dict(trend_signal.sub_factors or {})
    updated_trend_sub_factors["momentum"] = boosted_momentum_snapshot
    if boosted_volatility_snapshot:
        updated_trend_sub_factors["volatility"] = boosted_volatility_snapshot
    updated_event_sub_factors = dict(event_signal.sub_factors or {})
    updated_event_sub_factors["event_freshness"] = boosted_event_freshness_snapshot

    updated_signals = {name: _coerce_signal(payload) or StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}) for name, payload in dict(strategy_signals or {}).items()}
    updated_signals["trend"] = trend_signal.model_copy(update={"confidence": boosted_trend_snapshot["confidence"], "sub_factors": updated_trend_sub_factors})
    updated_signals["event_sentiment"] = event_signal.model_copy(
        update={
            "direction": boosted_event_snapshot["direction"],
            "confidence": boosted_event_snapshot["confidence"],
            "completeness": boosted_event_snapshot["completeness"],
            "sub_factors": updated_event_sub_factors,
        }
    )

    diagnostics["applied"] = bool(trend_changed or event_changed or momentum_changed or volatility_changed or event_freshness_changed)
    diagnostics["carryover_applied"] = bool(
        (int(event_snapshot.get("direction", 0) or 0) <= 0 and int(boosted_event_snapshot.get("direction", 0) or 0) > 0)
        or (int(event_freshness_snapshot.get("direction", 0) or 0) <= 0 and int(boosted_event_freshness_snapshot.get("direction", 0) or 0) > 0)
    )
    diagnostics["volume_carryover_applied"] = bool(
        int(volatility_snapshot.get("direction", 0) or 0) <= 0 and int(boosted_volatility_snapshot.get("direction", 0) or 0) > 0
    )
    diagnostics["after"] = {
        "trend_confidence": round(float(boosted_trend_snapshot["confidence"]), 4),
        "event_confidence": round(float(boosted_event_snapshot["confidence"]), 4),
        "momentum_confidence": round(float(boosted_momentum_snapshot["confidence"]), 4),
        "event_freshness_confidence": round(float(boosted_event_freshness_snapshot["confidence"]), 4),
        "volatility_confidence": round(float(boosted_volatility_snapshot.get("confidence", 0.0) or 0.0), 4),
    }
    diagnostics["confidence_delta"] = {
        "trend_confidence": round(float(boosted_trend_snapshot["confidence"]) - float(trend_snapshot.get("confidence", 0.0) or 0.0), 4),
        "event_confidence": round(float(boosted_event_snapshot["confidence"]) - float(event_snapshot.get("confidence", 0.0) or 0.0), 4),
        "momentum_confidence": round(float(boosted_momentum_snapshot["confidence"]) - float(momentum_snapshot.get("confidence", 0.0) or 0.0), 4),
        "event_freshness_confidence": round(float(boosted_event_freshness_snapshot["confidence"]) - float(event_freshness_snapshot.get("confidence", 0.0) or 0.0), 4),
        "volatility_confidence": round(float(boosted_volatility_snapshot.get("confidence", 0.0) or 0.0) - float(volatility_snapshot.get("confidence", 0.0) or 0.0), 4),
    }
    return updated_signals, diagnostics


def apply_merge_approved_layer_c_alignment_uplift(
    payload: Mapping[str, Any] | None,
    *,
    breakout_diagnostics: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = dict(payload or {})
    score_b = float(normalized.get("score_b", 0.0) or 0.0)
    score_c = float(normalized.get("score_c", 0.0) or 0.0)
    score_final = float(normalized.get("score_final", 0.0) or 0.0)
    decision = str(normalized.get("decision") or "")
    bc_conflict = str(normalized.get("bc_conflict") or "")
    agent_contribution_summary = dict(normalized.get("agent_contribution_summary") or {})
    cohort_contributions = dict(agent_contribution_summary.get("cohort_contributions") or {})
    analyst_contribution = float(cohort_contributions.get("analyst", 0.0) or 0.0)
    active_agent_count = int(agent_contribution_summary.get("active_agent_count", 0) or 0)
    negative_agent_count = int(agent_contribution_summary.get("negative_agent_count", 0) or 0)
    breakout_applied = bool((breakout_diagnostics or {}).get("applied"))
    volume_carryover_applied = bool((breakout_diagnostics or {}).get("volume_carryover_applied"))
    weak_context = active_agent_count == 0 or (negative_agent_count == 0 and analyst_contribution <= MERGE_APPROVED_ALIGNMENT_UPLIFT_ANALYST_CONTRIBUTION_MAX)
    gate_hits = {
        "breakout_applied": breakout_applied,
        "volume_carryover_applied": volume_carryover_applied,
        "decision_not_avoid": decision != "avoid",
        "no_bc_conflict": not bc_conflict,
        "score_c_band": MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_MIN <= score_c <= MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_MAX,
        "weak_context": weak_context,
    }
    eligible = all(gate_hits.values())
    diagnostics = {
        "enabled": True,
        "eligible": eligible,
        "applied": False,
        "gate_hits": gate_hits,
        "before": {
            "score_c": round(score_c, 4),
            "score_final": round(score_final, 4),
            "analyst_contribution": round(analyst_contribution, 4),
            "decision": decision,
            "active_agent_count": active_agent_count,
            "negative_agent_count": negative_agent_count,
        },
    }
    if not eligible:
        diagnostics["after"] = dict(diagnostics["before"])
        diagnostics["delta"] = {"score_c": 0.0, "score_final": 0.0, "analyst_contribution": 0.0}
        return normalized, diagnostics

    updated = dict(normalized)
    updated_score_c = max(score_c, MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_FLOOR)
    updated_cohort_contributions = dict(cohort_contributions)
    updated_analyst_contribution = max(analyst_contribution, MERGE_APPROVED_ALIGNMENT_UPLIFT_ANALYST_CONTRIBUTION_FLOOR)
    updated_cohort_contributions["analyst"] = round(updated_analyst_contribution, 4)
    updated_agent_contribution_summary = dict(agent_contribution_summary)
    updated_agent_contribution_summary["cohort_contributions"] = updated_cohort_contributions
    updated_agent_contribution_summary["adjusted_score_c"] = round(max(float(updated_agent_contribution_summary.get("adjusted_score_c", score_c) or score_c), updated_score_c), 4)
    updated_agent_contribution_summary["raw_score_c"] = round(max(float(updated_agent_contribution_summary.get("raw_score_c", score_c) or score_c), updated_score_c), 4)
    updated_agent_contribution_summary["active_agent_count"] = max(active_agent_count, 1)
    updated_agent_contribution_summary["positive_agent_count"] = max(int(updated_agent_contribution_summary.get("positive_agent_count", 0) or 0), 1)
    synthetic_positive = {
        "agent_id": "merge_approved_alignment_carryover",
        "contribution": round(updated_analyst_contribution, 4),
        "raw_contribution": round(updated_analyst_contribution, 4),
        "normalized_weight": 0.0,
        "direction": 1,
        "confidence": 100.0,
        "completeness": 1.0,
        "cohort": "analyst",
    }
    top_positive_agents = [dict(item) for item in list(updated_agent_contribution_summary.get("top_positive_agents") or []) if dict(item).get("agent_id") != synthetic_positive["agent_id"]]
    top_positive_agents.append(synthetic_positive)
    updated_agent_contribution_summary["top_positive_agents"] = sorted(top_positive_agents, key=lambda item: float(item.get("contribution", 0.0) or 0.0), reverse=True)[:3]
    updated_decision = "watch" if decision in {"", "neutral", "observation"} else decision
    blend_b, blend_c = _resolve_alignment_blend_weights()
    updated_score_final = (blend_b * score_b) + (blend_c * updated_score_c)

    updated["score_c"] = round(updated_score_c, 4)
    updated["score_final"] = round(updated_score_final, 4)
    updated["decision"] = updated_decision
    updated["agent_contribution_summary"] = updated_agent_contribution_summary

    diagnostics["applied"] = True
    diagnostics["after"] = {
        "score_c": round(updated_score_c, 4),
        "score_final": round(updated_score_final, 4),
        "analyst_contribution": round(updated_analyst_contribution, 4),
        "decision": updated_decision,
        "active_agent_count": updated_agent_contribution_summary["active_agent_count"],
        "negative_agent_count": negative_agent_count,
    }
    diagnostics["delta"] = {
        "score_c": round(updated_score_c - score_c, 4),
        "score_final": round(updated_score_final - score_final, 4),
        "analyst_contribution": round(updated_analyst_contribution - analyst_contribution, 4),
    }
    return updated, diagnostics


def apply_merge_approved_sector_resonance_uplift(
    payload: Mapping[str, Any] | None,
    *,
    alignment_diagnostics: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = dict(payload or {})
    score_c = float(normalized.get("score_c", 0.0) or 0.0)
    decision = str(normalized.get("decision") or "")
    bc_conflict = str(normalized.get("bc_conflict") or "")
    agent_contribution_summary = dict(normalized.get("agent_contribution_summary") or {})
    cohort_contributions = dict(agent_contribution_summary.get("cohort_contributions") or {})
    analyst_contribution = float(cohort_contributions.get("analyst", 0.0) or 0.0)
    investor_contribution = float(cohort_contributions.get("investor", 0.0) or 0.0)
    alignment_applied = bool((alignment_diagnostics or {}).get("applied"))
    weak_investor_context = investor_contribution <= MERGE_APPROVED_SECTOR_UPLIFT_INVESTOR_CONTRIBUTION_MAX
    gate_hits = {
        "alignment_applied": alignment_applied,
        "decision_not_avoid": decision != "avoid",
        "no_bc_conflict": not bc_conflict,
        "analyst_context_present": analyst_contribution >= MERGE_APPROVED_ALIGNMENT_UPLIFT_ANALYST_CONTRIBUTION_FLOOR,
        "weak_investor_context": weak_investor_context,
        "score_c_non_negative": score_c >= 0.0,
    }
    eligible = all(gate_hits.values())
    diagnostics = {
        "enabled": True,
        "eligible": eligible,
        "applied": False,
        "gate_hits": gate_hits,
        "before": {
            "investor_contribution": round(investor_contribution, 4),
            "analyst_contribution": round(analyst_contribution, 4),
        },
    }
    if not eligible:
        diagnostics["after"] = dict(diagnostics["before"])
        diagnostics["delta"] = {"investor_contribution": 0.0}
        return normalized, diagnostics

    updated = dict(normalized)
    updated_investor_contribution = max(investor_contribution, MERGE_APPROVED_SECTOR_UPLIFT_INVESTOR_CONTRIBUTION_FLOOR)
    updated_cohort_contributions = dict(cohort_contributions)
    updated_cohort_contributions["investor"] = round(updated_investor_contribution, 4)
    updated_agent_contribution_summary = dict(agent_contribution_summary)
    updated_agent_contribution_summary["cohort_contributions"] = updated_cohort_contributions
    updated_agent_contribution_summary["active_agent_count"] = max(int(updated_agent_contribution_summary.get("active_agent_count", 0) or 0), 2)
    updated_agent_contribution_summary["positive_agent_count"] = max(int(updated_agent_contribution_summary.get("positive_agent_count", 0) or 0), 2)
    synthetic_positive = {
        "agent_id": "merge_approved_sector_carryover",
        "contribution": round(updated_investor_contribution, 4),
        "raw_contribution": round(updated_investor_contribution, 4),
        "normalized_weight": 0.0,
        "direction": 1,
        "confidence": 100.0,
        "completeness": 1.0,
        "cohort": "investor",
    }
    top_positive_agents = [dict(item) for item in list(updated_agent_contribution_summary.get("top_positive_agents") or []) if dict(item).get("agent_id") != synthetic_positive["agent_id"]]
    top_positive_agents.append(synthetic_positive)
    updated_agent_contribution_summary["top_positive_agents"] = sorted(top_positive_agents, key=lambda item: float(item.get("contribution", 0.0) or 0.0), reverse=True)[:3]
    updated["agent_contribution_summary"] = updated_agent_contribution_summary

    diagnostics["applied"] = True
    diagnostics["after"] = {
        "investor_contribution": round(updated_investor_contribution, 4),
        "analyst_contribution": round(analyst_contribution, 4),
    }
    diagnostics["delta"] = {"investor_contribution": round(updated_investor_contribution - investor_contribution, 4)}
    return updated, diagnostics


def summarize_merge_approved_breakout_uplift_config() -> dict[str, Any]:
    return {
        "score_b_min": round(MERGE_APPROVED_BREAKOUT_UPLIFT_SCORE_B_MIN, 4),
        "trend_confidence_min": round(MERGE_APPROVED_BREAKOUT_UPLIFT_TREND_CONFIDENCE_MIN, 4),
        "event_confidence_min": round(MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_CONFIDENCE_MIN, 4),
        "momentum_confidence_min": round(MERGE_APPROVED_BREAKOUT_UPLIFT_MOMENTUM_CONFIDENCE_MIN, 4),
        "event_freshness_confidence_min": round(MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_FRESHNESS_CONFIDENCE_MIN, 4),
        "trend_confidence_floor": round(MERGE_APPROVED_BREAKOUT_UPLIFT_TREND_CONFIDENCE_FLOOR, 4),
        "event_confidence_floor": round(MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_CONFIDENCE_FLOOR, 4),
        "momentum_confidence_floor": round(MERGE_APPROVED_BREAKOUT_UPLIFT_MOMENTUM_CONFIDENCE_FLOOR, 4),
        "event_freshness_confidence_floor": round(MERGE_APPROVED_BREAKOUT_UPLIFT_EVENT_FRESHNESS_CONFIDENCE_FLOOR, 4),
        "volatility_confidence_min": round(MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_CONFIDENCE_MIN, 4),
        "volatility_confidence_floor": round(MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_CONFIDENCE_FLOOR, 4),
        "volatility_regime_min": round(MERGE_APPROVED_VOLUME_UPLIFT_VOLATILITY_REGIME_MIN, 4),
        "atr_ratio_min": round(MERGE_APPROVED_VOLUME_UPLIFT_ATR_RATIO_MIN, 4),
        "alignment_score_c_min": round(MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_MIN, 4),
        "alignment_score_c_max": round(MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_MAX, 4),
        "alignment_score_c_floor": round(MERGE_APPROVED_ALIGNMENT_UPLIFT_SCORE_C_FLOOR, 4),
        "alignment_analyst_contribution_max": round(MERGE_APPROVED_ALIGNMENT_UPLIFT_ANALYST_CONTRIBUTION_MAX, 4),
        "alignment_analyst_contribution_floor": round(MERGE_APPROVED_ALIGNMENT_UPLIFT_ANALYST_CONTRIBUTION_FLOOR, 4),
        "sector_investor_contribution_max": round(MERGE_APPROVED_SECTOR_UPLIFT_INVESTOR_CONTRIBUTION_MAX, 4),
        "sector_investor_contribution_floor": round(MERGE_APPROVED_SECTOR_UPLIFT_INVESTOR_CONTRIBUTION_FLOOR, 4),
    }
