from __future__ import annotations

from typing import Any

_BTST_SHADOW_PROMOTION_MIN_EVALUABLE_COUNT = 3
_BTST_SHADOW_PROMOTION_MIN_NEXT_CLOSE_POSITIVE_RATE = 0.55
_BTST_SHADOW_PROMOTION_MIN_NEXT_HIGH_HIT_RATE = 0.60
_BTST_HALT_RELIEF_MIN_EVALUABLE_COUNT = 5
_BTST_HALT_RELIEF_MIN_NEXT_CLOSE_POSITIVE_RATE = 0.65
_BTST_HALT_RELIEF_MIN_NEXT_HIGH_HIT_RATE = 0.75
_BTST_RELIEF_MIN_SCORE_TARGET = 0.50
_BTST_SHADOW_FIVE_DAY_PRIORITY_MIN_EVALUABLE_COUNT = 8
_BTST_SHADOW_FIVE_DAY_WEAK_HIT_RATE_AT_15PCT = 0.25
_BTST_SHADOW_FIVE_DAY_WEAK_MEAN_MAX_RETURN_2_5D = 0.10
_BTST_SHADOW_FIVE_DAY_FRAGILE_HIT_RATE_AT_15PCT = 0.35
_BTST_SHADOW_FIVE_DAY_FRAGILE_MEAN_MAX_RETURN_2_5D = 0.11
_BTST_SHADOW_FIVE_DAY_PRIORITY_WEAK_PENALTY = 0.18
_BTST_SHADOW_FIVE_DAY_PRIORITY_FRAGILE_PENALTY = 0.08
_BTST_RELIEF_CATALYST_SUPPORT_TAGS = {
    "fresh_catalyst_support",
    "catalyst_theme_short_trade_carryover_applied",
}

_BTST_REGIME_RELIEF_RULES = {
    "shadow_only": {
        "min_evaluable_count": _BTST_SHADOW_PROMOTION_MIN_EVALUABLE_COUNT,
        "min_next_close_positive_rate": _BTST_SHADOW_PROMOTION_MIN_NEXT_CLOSE_POSITIVE_RATE,
        "min_next_high_hit_rate": _BTST_SHADOW_PROMOTION_MIN_NEXT_HIGH_HIT_RATE,
        "risk_budget_gate": "shadow_promotion",
        "execution_contract_bucket": "shadow_promoted",
        "formal_risk_budget_ratio": 0.25,
        "reason": "shadow_only_close_continuation_promotion",
    },
    "halt": {
        "min_evaluable_count": _BTST_HALT_RELIEF_MIN_EVALUABLE_COUNT,
        "min_next_close_positive_rate": _BTST_HALT_RELIEF_MIN_NEXT_CLOSE_POSITIVE_RATE,
        "min_next_high_hit_rate": _BTST_HALT_RELIEF_MIN_NEXT_HIGH_HIT_RATE,
        "risk_budget_gate": "halt_relief",
        "execution_contract_bucket": "halt_promoted",
        "formal_risk_budget_ratio": 0.10,
        "reason": "halt_close_continuation_relief",
    },
}


def _read_field(payload: Any, field_name: str) -> Any:
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload.get(field_name)
    return getattr(payload, field_name, None)


def _first_numeric(*values: Any) -> float | None:
    for value in values:
        try:
            if value is None or value == "":
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_int(*values: Any) -> int:
    for value in values:
        try:
            if value is None or value == "":
                continue
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def resolve_btst_shadow_five_day_quality_signal(*, historical_prior: dict[str, Any] | None) -> dict[str, Any]:
    historical_prior = dict(historical_prior or {})
    evaluable_count = _first_int(
        historical_prior.get("five_day_evaluable_count"),
        historical_prior.get("historical_five_day_evaluable_count"),
    )
    hit_rate_at_15pct = _first_numeric(
        historical_prior.get("five_day_hit_rate_at_15pct"),
        historical_prior.get("historical_five_day_hit_rate_at_15pct"),
    )
    mean_max_return_2_5d = _first_numeric(
        historical_prior.get("five_day_mean_max_future_high_return_2_5d"),
        historical_prior.get("historical_five_day_mean_max_future_high_return_2_5d"),
    )
    if evaluable_count < _BTST_SHADOW_FIVE_DAY_PRIORITY_MIN_EVALUABLE_COUNT or hit_rate_at_15pct is None or mean_max_return_2_5d is None:
        return {
            "label": "insufficient",
            "reason": "",
            "priority_penalty": 0.0,
            "evaluable_count": evaluable_count,
            "hit_rate_at_15pct": round(float(hit_rate_at_15pct or 0.0), 4),
            "mean_max_future_high_return_2_5d": round(float(mean_max_return_2_5d or 0.0), 4),
        }
    if hit_rate_at_15pct < _BTST_SHADOW_FIVE_DAY_WEAK_HIT_RATE_AT_15PCT and mean_max_return_2_5d < _BTST_SHADOW_FIVE_DAY_WEAK_MEAN_MAX_RETURN_2_5D:
        return {
            "label": "weak",
            "reason": "five_day_boundary_quality_insufficient",
            "priority_penalty": _BTST_SHADOW_FIVE_DAY_PRIORITY_WEAK_PENALTY,
            "evaluable_count": evaluable_count,
            "hit_rate_at_15pct": round(float(hit_rate_at_15pct), 4),
            "mean_max_future_high_return_2_5d": round(float(mean_max_return_2_5d), 4),
        }
    if hit_rate_at_15pct < _BTST_SHADOW_FIVE_DAY_FRAGILE_HIT_RATE_AT_15PCT and mean_max_return_2_5d < _BTST_SHADOW_FIVE_DAY_FRAGILE_MEAN_MAX_RETURN_2_5D:
        return {
            "label": "fragile",
            "reason": "five_day_boundary_quality_fragile",
            "priority_penalty": _BTST_SHADOW_FIVE_DAY_PRIORITY_FRAGILE_PENALTY,
            "evaluable_count": evaluable_count,
            "hit_rate_at_15pct": round(float(hit_rate_at_15pct), 4),
            "mean_max_future_high_return_2_5d": round(float(mean_max_return_2_5d), 4),
        }
    return {
        "label": "supportive",
        "reason": "",
        "priority_penalty": 0.0,
        "evaluable_count": evaluable_count,
        "hit_rate_at_15pct": round(float(hit_rate_at_15pct), 4),
        "mean_max_future_high_return_2_5d": round(float(mean_max_return_2_5d), 4),
    }


def resolve_btst_shadow_promotion_payload(*, evaluation: Any, short_trade_result: Any | None = None, gate: str | None = None) -> dict[str, Any]:
    short_trade_result = short_trade_result if short_trade_result is not None else _read_field(evaluation, "short_trade")
    decision = str(_read_field(short_trade_result, "decision") or "").strip().lower()
    candidate_source = str(_read_field(evaluation, "candidate_source") or _read_field(short_trade_result, "candidate_source") or "").strip().lower()
    preferred_entry_mode = str(_read_field(short_trade_result, "preferred_entry_mode") or "").strip().lower()
    positive_tags = {str(tag).strip().lower() for tag in list(_read_field(short_trade_result, "positive_tags") or []) if str(tag or "").strip()}
    metrics_payload = dict(_read_field(short_trade_result, "metrics_payload") or {})
    explainability_payload = dict(_read_field(short_trade_result, "explainability_payload") or {})
    replay_context = dict(explainability_payload.get("replay_context") or {})
    historical_prior = dict(metrics_payload.get("historical_prior") or explainability_payload.get("historical_prior") or {})
    gate = str(gate or _read_field(evaluation, "btst_regime_gate") or _read_field(short_trade_result, "btst_regime_gate") or historical_prior.get("btst_regime_gate") or "").strip().lower()
    gate_rule = _BTST_REGIME_RELIEF_RULES.get(gate, {})
    execution_quality_label = str(historical_prior.get("execution_quality_label") or "").strip().lower()
    candidate_reason_codes = {str(code).strip().lower() for code in list(replay_context.get("candidate_reason_codes") or _read_field(evaluation, "candidate_reason_codes") or []) if str(code or "").strip()}
    short_trade_catalyst_relief = dict(replay_context.get("short_trade_catalyst_relief") or explainability_payload.get("short_trade_catalyst_relief") or metrics_payload.get("short_trade_catalyst_relief") or {})
    upstream_shadow_catalyst_relief = dict(explainability_payload.get("upstream_shadow_catalyst_relief") or metrics_payload.get("upstream_shadow_catalyst_relief") or {})
    evaluable_count = _first_int(
        historical_prior.get("prior_evidence_count"),
        historical_prior.get("evaluable_count"),
        historical_prior.get("same_ticker_sample_count"),
        historical_prior.get("n_selected"),
    )
    next_close_positive_rate = _first_numeric(
        historical_prior.get("effective_next_close_positive_rate"),
        historical_prior.get("shrunk_close_positive_rate"),
        historical_prior.get("next_close_positive_rate"),
        historical_prior.get("raw_next_close_positive_rate"),
    )
    next_high_hit_rate = _first_numeric(
        historical_prior.get("effective_next_high_hit_rate_at_threshold"),
        historical_prior.get("shrunk_high_hit_rate"),
        historical_prior.get("next_high_hit_rate_at_threshold"),
        historical_prior.get("raw_next_high_hit_rate_at_threshold"),
    )
    score_target = _first_numeric(
        _read_field(short_trade_result, "score_target"),
        historical_prior.get("score_target"),
    )
    has_catalyst_support = bool(positive_tags & _BTST_RELIEF_CATALYST_SUPPORT_TAGS)
    has_carryover_support = str(upstream_shadow_catalyst_relief.get("reason") or short_trade_catalyst_relief.get("reason") or "").strip().lower() == "catalyst_theme_short_trade_carryover" and ("catalyst_theme_short_trade_carryover_candidate" in candidate_reason_codes or "catalyst_theme_short_trade_carryover_applied" in positive_tags)
    relief_context_supported = has_catalyst_support or has_carryover_support
    five_day_quality_signal = resolve_btst_shadow_five_day_quality_signal(historical_prior=historical_prior)

    close_continuation_eligible = (
        bool(gate_rule)
        and decision in {"selected", "near_miss"}
        and candidate_source not in {"research_only", "upgrade_only"}
        and (score_target or 0.0) >= _BTST_RELIEF_MIN_SCORE_TARGET
        and relief_context_supported
        and preferred_entry_mode == "confirm_then_hold_breakout"
        and execution_quality_label == "close_continuation"
        and evaluable_count >= int(gate_rule.get("min_evaluable_count") or 0)
        and (next_close_positive_rate or 0.0) >= float(gate_rule.get("min_next_close_positive_rate") or 0.0)
        and (next_high_hit_rate or 0.0) >= float(gate_rule.get("min_next_high_hit_rate") or 0.0)
        and not bool(_read_field(evaluation, "p3_execution_blocked"))
    )
    carryover_relief_eligible = bool(gate_rule) and decision == "selected" and candidate_source not in {"research_only", "upgrade_only"} and (score_target or 0.0) >= _BTST_RELIEF_MIN_SCORE_TARGET and preferred_entry_mode == "confirm_then_hold_breakout" and not bool(_read_field(evaluation, "p3_execution_blocked")) and bool(upstream_shadow_catalyst_relief.get("applied")) and has_carryover_support
    eligible = close_continuation_eligible or carryover_relief_eligible
    relief_reason = ""
    if close_continuation_eligible:
        relief_reason = str(gate_rule.get("reason") or "")
    elif carryover_relief_eligible:
        relief_reason = "catalyst_theme_short_trade_carryover_relief"

    return {
        "eligible": eligible,
        "gate": gate,
        "decision": decision,
        "candidate_source": candidate_source,
        "preferred_entry_mode": preferred_entry_mode,
        "execution_quality_label": execution_quality_label,
        "score_target": round(float(score_target or 0.0), 4),
        "relief_context_supported": relief_context_supported,
        "evaluable_count": evaluable_count,
        "next_close_positive_rate": round(float(next_close_positive_rate or 0.0), 4),
        "next_high_hit_rate_at_threshold": round(float(next_high_hit_rate or 0.0), 4),
        "promoted_from_near_miss": eligible and decision == "near_miss",
        "preserved_selected": eligible and decision == "selected",
        "risk_budget_gate": str(gate_rule.get("risk_budget_gate") or gate) if eligible else gate or None,
        "execution_contract_bucket": str(gate_rule.get("execution_contract_bucket") or "") if eligible else None,
        "formal_risk_budget_ratio": float(gate_rule.get("formal_risk_budget_ratio") or 0.0) if eligible else 0.0,
        "reason": relief_reason,
        "five_day_quality_label": str(five_day_quality_signal.get("label") or "insufficient"),
        "five_day_quality_reason": str(five_day_quality_signal.get("reason") or ""),
        "five_day_priority_penalty": float(five_day_quality_signal.get("priority_penalty") or 0.0),
        "five_day_evaluable_count": int(five_day_quality_signal.get("evaluable_count") or 0),
        "five_day_hit_rate_at_15pct": float(five_day_quality_signal.get("hit_rate_at_15pct") or 0.0),
        "five_day_mean_max_future_high_return_2_5d": float(five_day_quality_signal.get("mean_max_future_high_return_2_5d") or 0.0),
    }
