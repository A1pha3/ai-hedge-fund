from __future__ import annotations

from typing import Any

from src.screening.market_state_helpers import classify_btst_regime_gate_from_market_state_metrics
from src.targets.explainability import clamp_unit_interval


SHADOW_ONLY_GATES = frozenset({"shadow_only", "halt"})
COMMITTEE_PROFILE_BY_GATE = {
    "aggressive_trade": "ignition_breakout",
    "normal_trade": "retention_follow",
    "shadow_only": "shadow_research",
    "halt": "shadow_research",
}


def _append_unique(values: list[str], value: str) -> None:
    normalized = str(value or "").strip()
    if normalized and normalized not in values:
        values.append(normalized)


def _as_float(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(payload.get(key, default) or default)
    except Exception:
        return default


def _normalized_ratio(value: Any) -> float:
    try:
        numeric = float(value or 0.0)
    except Exception:
        return 0.0
    if numeric > 1.0 and numeric <= 100.0:
        numeric = numeric / 100.0
    return clamp_unit_interval(numeric)


def _support_score_100(value: float) -> float:
    return round(20.0 + (80.0 * clamp_unit_interval(value)), 4)


def _risk_score_100(value: float) -> float:
    return round(100.0 * clamp_unit_interval(value), 4)


def _step_score(value: float, thresholds: list[tuple[float, float]], fallback: float) -> float:
    for threshold, score in thresholds:
        if value >= threshold:
            return float(score)
    return float(fallback)


def _step_inverse_score(value: float, thresholds: list[tuple[float, float]], fallback: float) -> float:
    for threshold, score in thresholds:
        if value <= threshold:
            return float(score)
    return float(fallback)


def _resolve_committee_gate(*, input_data: Any, snapshot: dict[str, Any]) -> str:
    btst_regime_gate_payload = classify_btst_regime_gate_from_market_state_metrics(dict(input_data.market_state or {}))
    inferred_gate = str((btst_regime_gate_payload or {}).get("gate") or "").strip().lower()
    if inferred_gate:
        return inferred_gate

    historical_prior = dict(snapshot.get("historical_prior") or {})
    explicit_gate = str(historical_prior.get("btst_regime_gate") or input_data.replay_context.get("btst_regime_gate") or "").strip().lower()
    if explicit_gate:
        return explicit_gate
    return inferred_gate or "normal_trade"


def _resolve_committee_thresholds(*, profile: Any, gate: str) -> dict[str, Any]:
    if gate == "aggressive_trade":
        return {
            "alpha_min": float(getattr(profile, "committee_alpha_min_aggressive_trade", 0.0) or 0.0),
            "beta_min": float(getattr(profile, "committee_beta_min_aggressive_trade", 0.0) or 0.0),
            "gamma_min": float(getattr(profile, "committee_gamma_min_aggressive_trade", 0.0) or 0.0),
            "committee_min": float(getattr(profile, "committee_score_min_aggressive_trade", 0.0) or 0.0),
            "selected_enforced": bool(getattr(profile, "committee_enabled", False)),
            "formal_selected_allowed": True,
        }
    if gate == "normal_trade":
        return {
            "alpha_min": float(getattr(profile, "committee_alpha_min_normal_trade", 0.0) or 0.0),
            "beta_min": float(getattr(profile, "committee_beta_min_normal_trade", 0.0) or 0.0),
            "gamma_min": float(getattr(profile, "committee_gamma_min_normal_trade", 0.0) or 0.0),
            "committee_min": float(getattr(profile, "committee_score_min_normal_trade", 0.0) or 0.0),
            "selected_enforced": bool(getattr(profile, "committee_enabled", False)),
            "formal_selected_allowed": True,
        }
    return {
        "alpha_min": 0.0,
        "beta_min": 0.0,
        "gamma_min": 0.0,
        "committee_min": 0.0,
        "selected_enforced": False,
        "formal_selected_allowed": not bool(getattr(profile, "committee_shadow_only_blocks_selected", True)),
    }


def _is_committee_advisory_continuation_lane(*, input_data: Any, snapshot: dict[str, Any]) -> tuple[bool, list[str]]:
    historical_prior = dict(snapshot.get("historical_prior") or {})
    candidate_source = str(getattr(input_data, "replay_context", {}).get("source") or "").strip()
    continuation_edge = str(historical_prior.get("execution_quality_label") or "") == "close_continuation" and str(historical_prior.get("entry_timing_bias") or "") == "confirm_then_hold"
    advisory_reasons: list[str] = []
    if bool(dict(snapshot.get("historical_execution_relief") or {}).get("applied")):
        advisory_reasons.append("historical_execution_relief")
    if bool(dict(snapshot.get("visibility_gap_continuation_relief") or {}).get("applied")):
        advisory_reasons.append("visibility_gap_continuation_relief")
    if bool(dict(snapshot.get("merge_approved_continuation_relief") or {}).get("applied")):
        advisory_reasons.append("merge_approved_continuation_relief")
    if continuation_edge and candidate_source == "catalyst_theme":
        advisory_reasons.append("catalyst_theme_continuation_lane")
    return bool(advisory_reasons), advisory_reasons


def _merge_raw_candidate_metrics(input_data: Any) -> dict[str, Any]:
    replay_context = dict(getattr(input_data, "replay_context", {}) or {})
    raw_candidate_metrics = dict(replay_context.get("raw_candidate_metrics") or {})
    raw_candidate_metrics.update(dict(replay_context.get("explicit_metric_overrides") or {}))
    if "projected_theme_exposure" not in raw_candidate_metrics and replay_context.get("projected_theme_exposure") is not None:
        raw_candidate_metrics["projected_theme_exposure"] = replay_context.get("projected_theme_exposure")
    if "candidate_pool_avg_amount_share_of_cutoff" not in raw_candidate_metrics and replay_context.get("candidate_pool_avg_amount_share_of_cutoff") is not None:
        raw_candidate_metrics["candidate_pool_avg_amount_share_of_cutoff"] = replay_context.get("candidate_pool_avg_amount_share_of_cutoff")
    return raw_candidate_metrics


def _sector_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    sector_amt_share = _as_float(raw_metrics, "sector_amt_share")
    if sector_amt_share > 0.0:
        return _step_score(sector_amt_share, [(0.06, 90.0), (0.04, 75.0), (0.025, 60.0), (0.015, 40.0)], 20.0), "raw:sector_amt_share"
    proxy = (0.65 * float(snapshot.get("sector_resonance", 0.0) or 0.0)) + (0.20 * float(snapshot.get("analyst_alignment", 0.0) or 0.0)) + (0.15 * float(snapshot.get("event_signal_strength", 0.0) or 0.0))
    return _support_score_100(proxy), "proxy:sector_resonance"


def _flow_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    flow_60 = _as_float(raw_metrics, "flow_60")
    if flow_60 != 0.0 or "flow_60" in raw_metrics:
        return _step_score(flow_60, [(0.12, 90.0), (0.08, 75.0), (0.04, 60.0), (0.0, 40.0)], 20.0), "raw:flow_60"
    proxy = (0.45 * float(snapshot.get("volume_expansion_quality", 0.0) or 0.0)) + (0.30 * float(snapshot.get("score_b_strength", 0.0) or 0.0)) + (0.25 * float(snapshot.get("momentum_strength", 0.0) or 0.0))
    return _support_score_100(proxy), "proxy:flow_alignment"


def _structure_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    attack_slope_258 = _as_float(raw_metrics, "attack_slope_258")
    breakout_quality_20_atr = _as_float(raw_metrics, "breakout_quality_20_atr")
    close_structure = _as_float(raw_metrics, "close_structure")
    amount_ratio_5 = _as_float(raw_metrics, "amount_ratio_5")
    available_scores: list[tuple[float, float]] = []
    if attack_slope_258 != 0.0 or "attack_slope_258" in raw_metrics:
        available_scores.append((_step_score(attack_slope_258, [(1.30, 90.0), (0.90, 75.0), (0.45, 60.0), (0.0, 40.0)], 20.0), 0.30))
    if breakout_quality_20_atr != 0.0 or "breakout_quality_20_atr" in raw_metrics:
        available_scores.append((_step_score(breakout_quality_20_atr, [(1.0, 90.0), (0.40, 75.0), (0.0, 60.0), (-0.50, 40.0)], 20.0), 0.25))
    if close_structure != 0.0 or "close_structure" in raw_metrics:
        available_scores.append((_step_score(close_structure, [(0.70, 90.0), (0.58, 75.0), (0.45, 60.0), (0.32, 40.0)], 20.0), 0.25))
    if amount_ratio_5 != 0.0 or "amount_ratio_5" in raw_metrics:
        available_scores.append((_step_score(amount_ratio_5, [(2.0, 90.0), (1.5, 75.0), (1.1, 60.0), (0.9, 40.0)], 20.0), 0.20))
    if available_scores:
        total_weight = sum(weight for _, weight in available_scores)
        weighted_score = sum(score * weight for score, weight in available_scores) / total_weight if total_weight > 0 else 0.0
        return round(weighted_score, 4), "raw:structure_metrics"
    proxy = (0.40 * float(snapshot.get("breakout_freshness", 0.0) or 0.0)) + (0.35 * float(snapshot.get("trend_acceleration", 0.0) or 0.0)) + (0.25 * float(snapshot.get("close_strength", 0.0) or 0.0))
    return _support_score_100(proxy), "proxy:breakout_structure"


def _attention_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    attention_composite = raw_metrics.get("attention_composite")
    if attention_composite is not None:
        attention_ratio = _normalized_ratio(attention_composite)
        return _step_score(attention_ratio, [(0.80, 90.0), (0.65, 75.0), (0.50, 60.0), (0.35, 40.0)], 20.0), "raw:attention_composite"
    proxy = (0.45 * float(snapshot.get("event_signal_strength", 0.0) or 0.0)) + (0.30 * float(snapshot.get("news_sentiment_strength", 0.0) or 0.0)) + (0.25 * float(snapshot.get("investor_alignment", 0.0) or 0.0))
    return _support_score_100(proxy), "proxy:event_attention"


def _retention_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    retention_proxy = raw_metrics.get("retention_proxy")
    if retention_proxy is not None:
        return _step_score(_normalized_ratio(retention_proxy), [(0.75, 90.0), (0.65, 75.0), (0.55, 60.0), (0.45, 40.0)], 20.0), "raw:retention_proxy"
    historical_continuation_prior_score = dict(snapshot.get("historical_continuation_prior_score") or {})
    prior_retention_score = float(historical_continuation_prior_score.get("score", 0.0) or 0.0)
    proxy = (0.60 * float(snapshot.get("close_retention_score", 0.0) or 0.0)) + (0.40 * prior_retention_score)
    return _support_score_100(proxy), "proxy:retention_support"


def _close_support_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    close_support_30 = _as_float(raw_metrics, "close_support_30")
    if close_support_30 != 0.0 or "close_support_30" in raw_metrics:
        return _step_score(close_support_30, [(0.10, 90.0), (0.05, 75.0), (0.02, 60.0), (0.0, 40.0)], 20.0), "raw:close_support_30"
    proxy = (0.70 * float(snapshot.get("close_strength", 0.0) or 0.0)) + (0.30 * float(snapshot.get("intraday_strength", 0.0) or 0.0))
    return _support_score_100(proxy), "proxy:close_support"


def _close_structure_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    close_structure = raw_metrics.get("close_structure")
    if close_structure is not None:
        return _step_score(_normalized_ratio(close_structure), [(0.70, 90.0), (0.58, 75.0), (0.45, 60.0), (0.32, 40.0)], 20.0), "raw:close_structure"
    return _support_score_100(float(snapshot.get("close_strength", 0.0) or 0.0)), "proxy:close_strength"


def _supply_pressure_risk_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    supply_pressure_60 = raw_metrics.get("supply_pressure_60")
    if supply_pressure_60 is not None:
        support_score = _step_inverse_score(float(supply_pressure_60 or 0.0), [(0.08, 90.0), (0.12, 75.0), (0.18, 60.0), (0.25, 40.0)], 20.0)
        return round(100.0 - support_score, 4), "raw:supply_pressure_60"
    proxy = max(
        float(snapshot.get("overhead_supply_penalty", 0.0) or 0.0) / 0.12,
        float(snapshot.get("extension_without_room_penalty", 0.0) or 0.0) / 0.12,
        float(snapshot.get("breakout_trap_penalty", 0.0) or 0.0) / 0.12,
    )
    return _risk_score_100(proxy), "proxy:penalty_pressure"


def _gap_risk_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    gap_to_limit = raw_metrics.get("gap_to_limit")
    if gap_to_limit is not None:
        gap_value = float(gap_to_limit or 0.0)
        if gap_value >= 0.05:
            return 15.0, "raw:gap_to_limit"
        if gap_value >= 0.03:
            return 35.0, "raw:gap_to_limit"
        if gap_value >= 0.02:
            return 60.0, "raw:gap_to_limit"
        if gap_value >= 0.01:
            return 80.0, "raw:gap_to_limit"
        return 100.0, "raw:gap_to_limit"
    breakout_close_gap = float(snapshot.get("breakout_close_gap", 0.0) or 0.0)
    return _risk_score_100(breakout_close_gap / 0.16), "proxy:breakout_close_gap"


def _liquidity_capacity_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any], input_data: Any) -> tuple[float, str]:
    candidate_pool_avg_amount_share_of_cutoff = _as_float(raw_metrics, "candidate_pool_avg_amount_share_of_cutoff", _as_float(dict(input_data.replay_context or {}), "candidate_pool_avg_amount_share_of_cutoff"))
    if candidate_pool_avg_amount_share_of_cutoff > 0.0:
        return _step_score(candidate_pool_avg_amount_share_of_cutoff, [(1.40, 90.0), (1.15, 75.0), (1.00, 60.0), (0.85, 40.0)], 20.0), "raw:candidate_pool_avg_amount_share_of_cutoff"
    proxy = (0.55 * float(snapshot.get("volume_expansion_quality", 0.0) or 0.0)) + (0.25 * float(snapshot.get("close_strength", 0.0) or 0.0)) + (0.20 * float(snapshot.get("score_final_strength", 0.0) or 0.0))
    return _support_score_100(proxy), "proxy:liquidity_capacity"


def _crowding_risk_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    turnover_ratio_20 = raw_metrics.get("turnover_ratio_20")
    limit_up_memory_259 = raw_metrics.get("limit_up_memory_259")
    if turnover_ratio_20 is not None:
        turnover_value = float(turnover_ratio_20 or 0.0)
        limit_up_value = _normalized_ratio(limit_up_memory_259 or 0.0)
        if turnover_value >= 2.5 and limit_up_value >= 0.8:
            return 85.0, "raw:turnover_ratio_20_limit_up_memory_259"
        if turnover_value >= 2.0:
            return 65.0, "raw:turnover_ratio_20_limit_up_memory_259"
        if turnover_value >= 1.5:
            return 45.0, "raw:turnover_ratio_20_limit_up_memory_259"
        return 25.0, "raw:turnover_ratio_20_limit_up_memory_259"
    proxy = (0.45 * max(float(snapshot.get("event_signal_strength", 0.0) or 0.0), float(snapshot.get("news_sentiment_strength", 0.0) or 0.0))) + (0.35 * max(0.0, float(snapshot.get("momentum_strength", 0.0) or 0.0) - float(snapshot.get("close_retention_score", 0.0) or 0.0))) + (0.20 * float(snapshot.get("investor_alignment", 0.0) or 0.0))
    return _risk_score_100(proxy), "proxy:crowding_risk"


def _theme_concentration_risk_raw_score(raw_metrics: dict[str, Any], input_data: Any) -> tuple[float | None, str]:
    projected_theme_exposure = _as_float(raw_metrics, "projected_theme_exposure", _as_float(dict(input_data.replay_context or {}), "projected_theme_exposure"))
    if projected_theme_exposure <= 0.0:
        return None, "missing"
    if projected_theme_exposure >= 0.35:
        return 90.0, "raw:projected_theme_exposure"
    if projected_theme_exposure >= 0.25:
        return 70.0, "raw:projected_theme_exposure"
    if projected_theme_exposure >= 0.18:
        return 45.0, "raw:projected_theme_exposure"
    return 20.0, "raw:projected_theme_exposure"


def _weighted_average(scores: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in scores)
    if total_weight <= 0.0:
        return 0.0
    return round(sum(score * weight for score, weight in scores) / total_weight, 4)


def build_short_trade_committee_snapshot(*, input_data: Any, snapshot: dict[str, Any], profile: Any) -> dict[str, Any]:
    raw_metrics = _merge_raw_candidate_metrics(input_data)
    gate = _resolve_committee_gate(input_data=input_data, snapshot=snapshot)
    thresholds = _resolve_committee_thresholds(profile=profile, gate=gate)
    advisory_only, advisory_reasons = _is_committee_advisory_continuation_lane(input_data=input_data, snapshot=snapshot)
    if advisory_only:
        thresholds = {**thresholds, "selected_enforced": False}

    sector_raw_100, sector_source = _sector_raw_score(snapshot, raw_metrics)
    flow_raw_100, flow_source = _flow_raw_score(snapshot, raw_metrics)
    structure_raw_100, structure_source = _structure_raw_score(snapshot, raw_metrics)
    attention_raw_100, attention_source = _attention_raw_score(snapshot, raw_metrics)
    retention_raw_100, retention_source = _retention_raw_score(snapshot, raw_metrics)
    close_support_raw_100, close_support_source = _close_support_raw_score(snapshot, raw_metrics)
    close_structure_raw_100, close_structure_source = _close_structure_raw_score(snapshot, raw_metrics)
    supply_pressure_risk_raw_100, supply_pressure_source = _supply_pressure_risk_raw_score(snapshot, raw_metrics)
    gap_risk_raw_100, gap_risk_source = _gap_risk_raw_score(snapshot, raw_metrics)
    liquidity_capacity_raw_100, liquidity_capacity_source = _liquidity_capacity_raw_score(snapshot, raw_metrics, input_data)
    crowding_risk_raw_100, crowding_source = _crowding_risk_raw_score(snapshot, raw_metrics)
    theme_concentration_after_trade_raw_100, theme_source = _theme_concentration_risk_raw_score(raw_metrics, input_data)

    alpha_edge_score = _weighted_average(
        [
            (sector_raw_100, 0.30),
            (flow_raw_100, 0.30),
            (structure_raw_100, 0.25),
            (attention_raw_100, 0.15),
        ]
    )
    beta_execution_score = _weighted_average(
        [
            (retention_raw_100, 0.40),
            (close_support_raw_100, 0.20),
            (100.0 - supply_pressure_risk_raw_100, 0.20),
            (100.0 - gap_risk_raw_100, 0.20),
        ]
    )

    gamma_components: list[tuple[float, float]] = [
        (100.0 if gate == "aggressive_trade" else 75.0 if gate == "normal_trade" else 20.0 if gate == "shadow_only" else 0.0, 0.40),
        (liquidity_capacity_raw_100, 0.25),
        (100.0 - crowding_risk_raw_100, 0.20),
    ]
    if theme_concentration_after_trade_raw_100 is not None:
        gamma_components.append((100.0 - theme_concentration_after_trade_raw_100, 0.15))
    gamma_risk_score = _weighted_average(gamma_components)

    committee_score = _weighted_average(
        [
            (alpha_edge_score, float(getattr(profile, "committee_alpha_weight", 0.55) or 0.55)),
            (beta_execution_score, float(getattr(profile, "committee_beta_weight", 0.25) or 0.25)),
            (gamma_risk_score, float(getattr(profile, "committee_gamma_weight", 0.20) or 0.20)),
        ]
    )

    vetoes: list[str] = []
    if bool(getattr(profile, "committee_isolated_attention_veto_enabled", True)) and attention_raw_100 >= float(getattr(profile, "committee_isolated_attention_min", 80.0) or 80.0) and sector_raw_100 <= float(getattr(profile, "committee_isolated_attention_sector_max", 60.0) or 60.0) and flow_raw_100 <= float(getattr(profile, "committee_isolated_attention_flow_max", 60.0) or 60.0):
        vetoes.append("committee_isolated_attention_veto")
    if bool(getattr(profile, "committee_weak_close_veto_enabled", True)) and flow_raw_100 >= float(getattr(profile, "committee_weak_close_flow_min", 75.0) or 75.0) and close_structure_raw_100 <= float(getattr(profile, "committee_weak_close_structure_max", 45.0) or 45.0) and close_support_raw_100 <= float(getattr(profile, "committee_weak_close_close_support_max", 60.0) or 60.0):
        vetoes.append("committee_weak_close_execution_veto")

    fail_reasons: list[str] = []
    if bool(thresholds["selected_enforced"]):
        if alpha_edge_score < float(thresholds["alpha_min"]):
            fail_reasons.append("committee_alpha_below_selected_min")
        if beta_execution_score < float(thresholds["beta_min"]):
            fail_reasons.append("committee_beta_below_selected_min")
        if gamma_risk_score < float(thresholds["gamma_min"]):
            fail_reasons.append("committee_gamma_below_selected_min")
        if committee_score < float(thresholds["committee_min"]):
            fail_reasons.append("committee_score_below_selected_min")

    formal_selected_allowed = bool(thresholds["formal_selected_allowed"])
    if gate in SHADOW_ONLY_GATES and bool(getattr(profile, "committee_shadow_only_blocks_selected", True)):
        formal_selected_allowed = False
        fail_reasons.append("committee_shadow_profile_only")

    selected_pass = formal_selected_allowed and not vetoes and (not bool(thresholds["selected_enforced"]) or not fail_reasons)
    component_status = {
        "alpha": "pass" if alpha_edge_score >= float(thresholds["alpha_min"]) else "advisory" if not bool(thresholds["selected_enforced"]) else "fail",
        "beta": "pass" if beta_execution_score >= float(thresholds["beta_min"]) else "advisory" if not bool(thresholds["selected_enforced"]) else "fail",
        "gamma": "pass" if gamma_risk_score >= float(thresholds["gamma_min"]) else "advisory" if not bool(thresholds["selected_enforced"]) else "fail",
        "committee": "pass" if committee_score >= float(thresholds["committee_min"]) else "advisory" if not bool(thresholds["selected_enforced"]) else "fail",
        "veto": "fail" if vetoes else "pass",
        "formal_selected": "pass" if selected_pass else "shadow_only" if gate in SHADOW_ONLY_GATES and bool(getattr(profile, "committee_shadow_only_blocks_selected", True)) else "fail" if bool(thresholds["selected_enforced"]) or vetoes else "advisory",
    }

    return {
        "committee_enabled": bool(getattr(profile, "committee_enabled", False)),
        "committee_gate": gate,
        "committee_profile": COMMITTEE_PROFILE_BY_GATE.get(gate, "retention_follow"),
        "committee_thresholds": {
            "alpha_min": round(float(thresholds["alpha_min"]), 4),
            "beta_min": round(float(thresholds["beta_min"]), 4),
            "gamma_min": round(float(thresholds["gamma_min"]), 4),
            "committee_min": round(float(thresholds["committee_min"]), 4),
            "selected_enforced": bool(thresholds["selected_enforced"]),
            "formal_selected_allowed": formal_selected_allowed,
        },
        "committee_components": {
            "sector_raw_100": round(sector_raw_100, 4),
            "flow_raw_100": round(flow_raw_100, 4),
            "structure_raw_100": round(structure_raw_100, 4),
            "attention_raw_100": round(attention_raw_100, 4),
            "retention_raw_100": round(retention_raw_100, 4),
            "close_support_raw_100": round(close_support_raw_100, 4),
            "close_structure_raw_100": round(close_structure_raw_100, 4),
            "supply_pressure_risk_raw_100": round(supply_pressure_risk_raw_100, 4),
            "gap_risk_raw_100": round(gap_risk_raw_100, 4),
            "regime_admissibility_raw_100": round(gamma_components[0][0], 4),
            "liquidity_capacity_raw_100": round(liquidity_capacity_raw_100, 4),
            "crowding_risk_raw_100": round(crowding_risk_raw_100, 4),
            "theme_concentration_after_trade_raw_100": round(theme_concentration_after_trade_raw_100, 4) if theme_concentration_after_trade_raw_100 is not None else None,
        },
        "committee_component_sources": {
            "sector_raw_100": sector_source,
            "flow_raw_100": flow_source,
            "structure_raw_100": structure_source,
            "attention_raw_100": attention_source,
            "retention_raw_100": retention_source,
            "close_support_raw_100": close_support_source,
            "close_structure_raw_100": close_structure_source,
            "supply_pressure_risk_raw_100": supply_pressure_source,
            "gap_risk_raw_100": gap_risk_source,
            "liquidity_capacity_raw_100": liquidity_capacity_source,
            "crowding_risk_raw_100": crowding_source,
            "theme_concentration_after_trade_raw_100": theme_source,
        },
        "alpha_edge_score": round(alpha_edge_score, 4),
        "beta_execution_score": round(beta_execution_score, 4),
        "gamma_risk_score": round(gamma_risk_score, 4),
        "committee_score": round(committee_score, 4),
        "committee_vetoes": vetoes,
        "committee_fail_reasons": fail_reasons,
        "committee_selected_pass": selected_pass,
        "committee_gate_status": component_status,
        "committee_advisory_reasons": advisory_reasons,
    }


def apply_short_trade_committee_governance(
    *,
    decision: str,
    snapshot: dict[str, Any],
    positive_tags: list[str],
    negative_tags: list[str],
    blockers: list[str],
    gate_status: dict[str, Any],
) -> tuple[str, list[str]]:
    committee_enabled = bool(snapshot.get("committee_enabled", False))
    committee_gate_status = dict(snapshot.get("committee_gate_status") or {})
    gate_status["committee_veto"] = str(committee_gate_status.get("veto") or "pass")
    gate_status["committee"] = str(committee_gate_status.get("formal_selected") or ("disabled" if not committee_enabled else "advisory"))

    if not committee_enabled:
        return decision, []

    threshold_fail_reasons = list(snapshot.get("committee_fail_reasons") or [])
    vetoes = list(snapshot.get("committee_vetoes") or [])
    downgrade_reasons: list[str] = []

    if decision != "selected":
        if vetoes:
            for veto in vetoes:
                _append_unique(negative_tags, veto)
        return decision, downgrade_reasons

    if "committee_shadow_profile_only" in threshold_fail_reasons:
        _append_unique(blockers, "committee_shadow_profile_only")
        _append_unique(negative_tags, "committee_shadow_profile_only")
        gate_status["committee"] = "shadow_only"
        gate_status["score"] = "fail"
        return "blocked", ["committee_shadow_profile_only"]

    if vetoes:
        for veto in vetoes:
            _append_unique(negative_tags, veto)
            _append_unique(downgrade_reasons, veto)
        if "committee_isolated_attention_veto" in vetoes:
            _append_unique(blockers, "committee_isolated_attention_veto")
            gate_status["committee"] = "veto"
            gate_status["score"] = "fail"
            return "rejected", downgrade_reasons
        gate_status["committee"] = "veto"
        gate_status["score"] = "near_miss"
        return "near_miss", downgrade_reasons

    if threshold_fail_reasons:
        for reason in threshold_fail_reasons:
            _append_unique(negative_tags, reason)
            _append_unique(downgrade_reasons, reason)
        gate_status["committee"] = "fail"
        gate_status["score"] = "near_miss"
        return "near_miss", downgrade_reasons

    _append_unique(positive_tags, "committee_selected_pass")
    gate_status["committee"] = "pass"
    return decision, downgrade_reasons