from __future__ import annotations

from functools import lru_cache
import importlib.util
import os
import sys
from typing import Any

from src.screening.market_state_helpers import classify_btst_regime_gate_from_market_state_metrics
from src.targets.short_trade_target_kill_switch_helpers import resolve_btst_kill_switch
from src.targets.explainability import clamp_unit_interval

SHADOW_ONLY_GATES = frozenset({"shadow_only", "halt"})
COMMITTEE_PROFILE_BY_GATE = {
    "aggressive_trade": "ignition_breakout",
    "normal_trade": "retention_follow",
    "shadow_only": "shadow_research",
    "halt": "shadow_research",
}


@lru_cache(maxsize=1)
def _get_btst_evaluation_bundle_module() -> Any:
    eval_module_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backtesting", "evaluation_bundle.py"))
    spec = importlib.util.spec_from_file_location("evaluation_bundle_cached", eval_module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load evaluation_bundle from {eval_module_path}")
    eval_module = sys.modules.get("evaluation_bundle_cached")
    if eval_module is None:
        eval_module = importlib.util.module_from_spec(spec)
        sys.modules["evaluation_bundle_cached"] = eval_module
        spec.loader.exec_module(eval_module)
    return eval_module


def _get_btst_gap_risk_cap_raw_100() -> float | None:
    eval_module = _get_btst_evaluation_bundle_module()
    return eval_module.coerce_numeric_metric_value(eval_module.BTST_EXECUTION_GUARDRAILS.get("gap_risk_raw_100", {}).get("max"))


def _append_unique(values: list[str], value: str) -> None:
    normalized = str(value or "").strip()
    if normalized and normalized not in values:
        values.append(normalized)


def _as_float(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(payload.get(key, default) or default)
    except Exception:
        return default


def _optional_float(payload: dict[str, Any], key: str) -> float | None:
    try:
        value = payload.get(key)
    except Exception:
        return None
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


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


def _shrink_support_score_for_evidence(base_support_score_100: float, evidence_weight: Any) -> float:
    reliability = clamp_unit_interval(float(evidence_weight or 0.0))
    multiplier = 0.70 + (0.30 * reliability)
    return round(50.0 + ((float(base_support_score_100 or 50.0) - 50.0) * multiplier), 4)


def _apply_prior_payoff_asymmetry_to_support_score(base_support_score_100: float, snapshot: dict[str, Any]) -> float:
    historical_prior = dict(snapshot.get("historical_prior") or {})
    if not historical_prior:
        return round(float(base_support_score_100 or 0.0), 4)

    next_close_positive_rate = _optional_float(historical_prior, "effective_next_close_positive_rate")
    if next_close_positive_rate is None:
        next_close_positive_rate = _optional_float(historical_prior, "shrunk_close_positive_rate")
    if next_close_positive_rate is None:
        next_close_positive_rate = _optional_float(historical_prior, "next_close_positive_rate")
    if next_close_positive_rate is None:
        next_close_positive_rate = _optional_float(historical_prior, "raw_next_close_positive_rate")

    next_high_hit_rate = _optional_float(historical_prior, "effective_next_high_hit_rate_at_threshold")
    if next_high_hit_rate is None:
        next_high_hit_rate = _optional_float(historical_prior, "shrunk_high_hit_rate")
    if next_high_hit_rate is None:
        next_high_hit_rate = _optional_float(historical_prior, "next_high_hit_rate_at_threshold")
    if next_high_hit_rate is None:
        next_high_hit_rate = _optional_float(historical_prior, "raw_next_high_hit_rate_at_threshold")

    next_open_to_close_return_mean = _optional_float(historical_prior, "effective_next_open_to_close_return_mean")
    if next_open_to_close_return_mean is None:
        next_open_to_close_return_mean = _optional_float(historical_prior, "next_open_to_close_return_mean")

    penalty_points = 0.0
    if next_open_to_close_return_mean is not None:
        if next_open_to_close_return_mean <= 0.0:
            penalty_points += 15.0
        elif next_open_to_close_return_mean < 0.01:
            penalty_points += 7.5

    if next_high_hit_rate is not None and next_close_positive_rate is not None:
        follow_through_gap = max(0.0, float(next_high_hit_rate) - float(next_close_positive_rate))
        if follow_through_gap >= 0.20:
            penalty_points += 10.0
        elif follow_through_gap >= 0.12:
            penalty_points += 5.0

    if penalty_points <= 0.0:
        return round(float(base_support_score_100 or 0.0), 4)

    evidence_weight = clamp_unit_interval(float(historical_prior.get("evidence_weight", 0.0) or 0.0))
    adjusted_score = float(base_support_score_100 or 0.0) - (penalty_points * (0.55 + (0.45 * evidence_weight)))
    return round(max(20.0, adjusted_score), 4)


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


def _committee_group_score(raw_score_100: float) -> float:
    if raw_score_100 >= 60.0:
        return round(min(100.0, 2.0 * abs(raw_score_100 - 50.0)) / 100.0, 4)
    if raw_score_100 <= 40.0:
        return round(-min(100.0, 2.0 * abs(raw_score_100 - 50.0)) / 100.0, 4)
    return 0.0


def _committee_excess_ratio(raw_score_100: float, floor_100: float) -> float:
    if floor_100 >= 100.0:
        return 0.0
    return clamp_unit_interval((float(raw_score_100 or 0.0) - float(floor_100 or 0.0)) / max(1.0, 100.0 - float(floor_100 or 0.0)))


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
            "sector_group_score_min": float(getattr(profile, "committee_sector_group_score_min_aggressive_trade", 0.05) or 0.05),
            "flow_group_score_min": float(getattr(profile, "committee_flow_group_score_min_aggressive_trade", 0.08) or 0.08),
            "retention_group_score_min": float(getattr(profile, "committee_retention_group_score_min_aggressive_trade", 0.0) or 0.0),
            "penalty_total_max": float(getattr(profile, "committee_penalty_total_max", 0.12) or 0.12),
            "selected_enforced": bool(getattr(profile, "committee_enabled", False)),
            "formal_selected_allowed": True,
        }
    if gate == "normal_trade":
        return {
            "alpha_min": float(getattr(profile, "committee_alpha_min_normal_trade", 0.0) or 0.0),
            "beta_min": float(getattr(profile, "committee_beta_min_normal_trade", 0.0) or 0.0),
            "gamma_min": float(getattr(profile, "committee_gamma_min_normal_trade", 0.0) or 0.0),
            "committee_min": float(getattr(profile, "committee_score_min_normal_trade", 0.0) or 0.0),
            "sector_group_score_min": float(getattr(profile, "committee_sector_group_score_min_normal_trade", 0.05) or 0.05),
            "flow_group_score_min": float(getattr(profile, "committee_flow_group_score_min_normal_trade", 0.05) or 0.05),
            "retention_group_score_min": float(getattr(profile, "committee_retention_group_score_min_normal_trade", 0.05) or 0.05),
            "penalty_total_max": float(getattr(profile, "committee_penalty_total_max", 0.12) or 0.12),
            "selected_enforced": bool(getattr(profile, "committee_enabled", False)),
            "formal_selected_allowed": True,
        }
    return {
        "alpha_min": 0.0,
        "beta_min": 0.0,
        "gamma_min": 0.0,
        "committee_min": 0.0,
        "sector_group_score_min": 0.0,
        "flow_group_score_min": 0.0,
        "retention_group_score_min": 0.0,
        "penalty_total_max": float(getattr(profile, "committee_penalty_total_max", 0.12) or 0.12),
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


def _resolve_runner_escape(*, profile: Any, snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    if not bool(getattr(profile, "runner_escape_enabled", False)):
        return False, []
    reasons: list[str] = []
    breakout = _as_float(snapshot, "breakout_freshness", 0.0)
    trend = _as_float(snapshot, "trend_acceleration", 0.0)
    volume = _as_float(snapshot, "volume_expansion_quality", 0.0)
    projected_theme_exposure = _optional_float(raw_metrics, "projected_theme_exposure")
    gap_risk_raw_100 = _optional_float(raw_metrics, "gap_risk_raw_100")
    amount_share = _optional_float(raw_metrics, "candidate_pool_avg_amount_share_of_cutoff")
    if breakout >= getattr(profile, "runner_escape_breakout_freshness_min", 1.0):
        reasons.append("runner_escape_breakout")
    if trend >= getattr(profile, "runner_escape_trend_acceleration_min", 1.0):
        reasons.append("runner_escape_trend")
    if volume >= getattr(profile, "runner_escape_volume_expansion_quality_min", 1.0):
        reasons.append("runner_escape_volume")
    escaped = len(reasons) == 3 and (gap_risk_raw_100 or 999.0) <= getattr(profile, "runner_escape_gap_risk_raw_100_max", 0.0) and (projected_theme_exposure or 999.0) <= getattr(profile, "runner_escape_projected_theme_exposure_max", 0.0) and (amount_share or 0.0) >= getattr(profile, "runner_escape_candidate_pool_avg_amount_share_of_cutoff_min", 999.0)
    return escaped, reasons


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
    available_scores: list[tuple[float, float]] = []
    sector_amt_share = _as_float(raw_metrics, "sector_amt_share")
    if sector_amt_share > 0.0:
        available_scores.append((_step_score(sector_amt_share, [(0.06, 90.0), (0.04, 75.0), (0.025, 60.0), (0.015, 40.0)], 20.0), 0.30))
    sector_breadth_3 = raw_metrics.get("sector_breadth_3")
    if sector_breadth_3 is not None:
        available_scores.append((_step_score(float(sector_breadth_3 or 0.0), [(0.35, 90.0), (0.25, 75.0), (0.18, 60.0), (0.10, 40.0)], 20.0), 0.25))
    follow_ratio_2 = raw_metrics.get("follow_ratio_2")
    if follow_ratio_2 is not None:
        available_scores.append((_step_score(float(follow_ratio_2 or 0.0), [(0.30, 90.0), (0.22, 75.0), (0.15, 60.0), (0.08, 40.0)], 20.0), 0.25))
    catalyst_freshness = raw_metrics.get("catalyst_freshness")
    if catalyst_freshness is not None:
        available_scores.append((_step_score(float(catalyst_freshness or 0.0), [(0.70, 90.0), (0.50, 75.0), (0.35, 60.0), (0.20, 40.0)], 20.0), 0.20))
    if available_scores:
        if len(available_scores) == 1 and sector_amt_share > 0.0:
            return available_scores[0][0], "raw:sector_amt_share"
        total_weight = sum(weight for _, weight in available_scores)
        weighted_score = sum(score * weight for score, weight in available_scores) / total_weight if total_weight > 0 else 0.0
        return round(weighted_score, 4), "raw:sector_metrics"
    proxy = (0.65 * float(snapshot.get("sector_resonance", 0.0) or 0.0)) + (0.20 * float(snapshot.get("analyst_alignment", 0.0) or 0.0)) + (0.15 * float(snapshot.get("event_signal_strength", 0.0) or 0.0))
    return _support_score_100(proxy), "proxy:sector_resonance"


def _flow_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    available_scores: list[tuple[float, float]] = []
    flow_60 = _as_float(raw_metrics, "flow_60")
    if flow_60 != 0.0 or "flow_60" in raw_metrics:
        available_scores.append((_step_score(flow_60, [(0.12, 90.0), (0.08, 75.0), (0.04, 60.0), (0.0, 40.0)], 20.0), 0.40))
    persist_120 = raw_metrics.get("persist_120")
    if persist_120 is not None:
        persist_120_thresholds = [(0.65, 90.0), (0.58, 75.0), (0.52, 60.0), (0.45, 40.0)]
        if str(raw_metrics.get("persist_120_source") or "").strip() == "bar_proxy":
            persist_120_thresholds = [(0.60, 90.0), (0.53, 75.0), (0.43, 60.0), (0.36, 40.0)]
        available_scores.append((_step_score(float(persist_120 or 0.0), persist_120_thresholds, 20.0), 0.30))
    close_support_30 = raw_metrics.get("close_support_30")
    if close_support_30 is not None:
        available_scores.append((_step_score(float(close_support_30 or 0.0), [(0.10, 90.0), (0.05, 75.0), (0.02, 60.0), (0.0, 40.0)], 20.0), 0.30))
    if available_scores:
        total_weight = sum(weight for _, weight in available_scores)
        weighted_score = sum(score * weight for score, weight in available_scores) / total_weight if total_weight > 0 else 0.0
        return round(weighted_score, 4), "raw:flow_metrics"
    proxy = (0.45 * float(snapshot.get("volume_expansion_quality", 0.0) or 0.0)) + (0.30 * float(snapshot.get("score_b_strength", 0.0) or 0.0)) + (0.25 * float(snapshot.get("momentum_strength", 0.0) or 0.0))
    return _support_score_100(proxy), "proxy:flow_alignment"


def _flow_60_raw_score(raw_metrics: dict[str, Any]) -> float | None:
    if "flow_60" not in raw_metrics:
        return None
    return _step_score(float(raw_metrics.get("flow_60") or 0.0), [(0.12, 90.0), (0.08, 75.0), (0.04, 60.0), (0.0, 40.0)], 20.0)


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
    available_scores: list[tuple[float, float]] = []
    turnover_ratio_20 = raw_metrics.get("turnover_ratio_20")
    if turnover_ratio_20 is not None:
        available_scores.append((_step_score(float(turnover_ratio_20 or 0.0), [(2.20, 90.0), (1.60, 75.0), (1.20, 60.0), (0.90, 40.0)], 20.0), 0.30))
    attention_composite = raw_metrics.get("attention_composite")
    if attention_composite is not None:
        attention_ratio = _normalized_ratio(attention_composite)
        available_scores.append((_step_score(attention_ratio, [(0.80, 90.0), (0.65, 75.0), (0.50, 60.0), (0.35, 40.0)], 20.0), 0.35))
    limit_up_memory_259 = raw_metrics.get("limit_up_memory_259")
    if limit_up_memory_259 is not None:
        available_scores.append((_step_score(_normalized_ratio(limit_up_memory_259), [(0.80, 85.0), (0.50, 70.0), (0.30, 55.0)], 35.0), 0.20))
    dragon_tiger_bonus = raw_metrics.get("dragon_tiger_bonus")
    if dragon_tiger_bonus is not None:
        available_scores.append((80.0 if float(dragon_tiger_bonus or 0.0) >= 1.0 else 50.0, 0.15))
    if available_scores:
        total_weight = sum(weight for _, weight in available_scores)
        weighted_score = sum(score * weight for score, weight in available_scores) / total_weight if total_weight > 0 else 0.0
        return round(weighted_score, 4), "raw:attention_metrics"
    proxy = (0.45 * float(snapshot.get("event_signal_strength", 0.0) or 0.0)) + (0.30 * float(snapshot.get("news_sentiment_strength", 0.0) or 0.0)) + (0.25 * float(snapshot.get("investor_alignment", 0.0) or 0.0))
    return _support_score_100(proxy), "proxy:event_attention"


def _retention_raw_score(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[float, str]:
    available_scores: list[tuple[float, float]] = []
    retention_proxy = raw_metrics.get("retention_proxy")
    if retention_proxy is not None:
        available_scores.append((_step_score(_normalized_ratio(retention_proxy), [(0.75, 90.0), (0.65, 75.0), (0.55, 60.0), (0.45, 40.0)], 20.0), 0.30))
    supply_pressure_60 = raw_metrics.get("supply_pressure_60")
    if supply_pressure_60 is not None:
        available_scores.append((_step_inverse_score(float(supply_pressure_60 or 0.0), [(0.08, 90.0), (0.12, 75.0), (0.18, 60.0), (0.25, 40.0)], 20.0), 0.20))
    failed_breakout_10 = raw_metrics.get("failed_breakout_10")
    if failed_breakout_10 is not None:
        available_scores.append((_step_inverse_score(float(failed_breakout_10 or 0.0), [(0.0, 90.0), (1.0, 75.0), (2.0, 55.0)], 30.0), 0.20))
    prior_retention_score = raw_metrics.get("prior_retention_score")
    if prior_retention_score is not None:
        prior_retention_value = float(prior_retention_score or 0.0)
        if prior_retention_value <= 1.0:
            prior_retention_value = _support_score_100(prior_retention_value)
        prior_retention_value = _apply_prior_payoff_asymmetry_to_support_score(prior_retention_value, snapshot)
        available_scores.append((_step_score(prior_retention_value, [(75.0, 90.0), (65.0, 75.0), (55.0, 60.0), (45.0, 40.0)], 20.0), 0.30))
    else:
        historical_continuation_prior_score = dict(snapshot.get("historical_continuation_prior_score") or {})
        if historical_continuation_prior_score:
            prior_retention_ratio = float(historical_continuation_prior_score.get("score", 0.0) or 0.0)
            prior_retention_value = _shrink_support_score_for_evidence(
                _support_score_100(prior_retention_ratio),
                historical_continuation_prior_score.get("evidence_weight"),
            )
            prior_retention_value = _apply_prior_payoff_asymmetry_to_support_score(prior_retention_value, snapshot)
            available_scores.append((_step_score(prior_retention_value, [(75.0, 90.0), (65.0, 75.0), (55.0, 60.0), (45.0, 40.0)], 20.0), 0.30))
    if available_scores:
        total_weight = sum(weight for _, weight in available_scores)
        weighted_score = sum(score * weight for score, weight in available_scores) / total_weight if total_weight > 0 else 0.0
        return round(weighted_score, 4), "raw:retention_metrics"
    historical_continuation_prior_score = dict(snapshot.get("historical_continuation_prior_score") or {})
    prior_retention_score = float(historical_continuation_prior_score.get("score", 0.0) or 0.0)
    prior_retention_score = clamp_unit_interval(0.5 + ((prior_retention_score - 0.5) * (0.70 + (0.30 * clamp_unit_interval(float(historical_continuation_prior_score.get("evidence_weight", 0.0) or 0.0))))))
    prior_retention_support_100 = _apply_prior_payoff_asymmetry_to_support_score(_support_score_100(prior_retention_score), snapshot)
    prior_retention_score = clamp_unit_interval((prior_retention_support_100 - 20.0) / 80.0)
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


def _fragile_breakout_activation_raw_score(raw_metrics: dict[str, Any], *, attention_raw_100: float, crowding_risk_raw_100: float) -> tuple[float, str]:
    activation_raw_100 = _weighted_average([(attention_raw_100, 0.55), (crowding_risk_raw_100, 0.45)])
    activation_source = "derived:attention_crowding_activation"
    turnover_ratio_20 = raw_metrics.get("turnover_ratio_20")
    limit_up_memory_259 = raw_metrics.get("limit_up_memory_259")
    turnover_boost = 0.0
    memory_boost = 0.0
    if turnover_ratio_20 is not None:
        turnover_value = float(turnover_ratio_20 or 0.0)
        if turnover_value >= 2.5:
            turnover_boost = 8.0
        elif turnover_value >= 2.0:
            turnover_boost = 5.0
        elif turnover_value >= 1.5:
            turnover_boost = 2.0
    if limit_up_memory_259 is not None:
        limit_up_value = _normalized_ratio(limit_up_memory_259)
        if limit_up_value >= 0.8:
            memory_boost = 8.0
        elif limit_up_value >= 0.5:
            memory_boost = 4.0
        elif limit_up_value >= 0.3:
            memory_boost = 1.5
    if turnover_boost > 0.0 or memory_boost > 0.0:
        activation_raw_100 += turnover_boost + memory_boost
        if turnover_boost >= 5.0 and memory_boost >= 4.0:
            activation_raw_100 += 4.0
        activation_source = "derived:attention_crowding_turnover_memory_activation"
    return round(min(100.0, activation_raw_100), 4), activation_source


def _fragile_breakout_fragility_raw_score(
    raw_metrics: dict[str, Any],
    *,
    close_structure_raw_100: float,
    retention_raw_100: float,
    gap_risk_raw_100: float,
    supply_pressure_risk_raw_100: float,
) -> tuple[float, str]:
    close_structure_risk_raw_100 = max(0.0, 100.0 - float(close_structure_raw_100 or 0.0))
    retention_risk_raw_100 = max(0.0, 100.0 - float(retention_raw_100 or 0.0))
    fragility_base_raw_100 = _weighted_average(
        [
            (close_structure_risk_raw_100, 0.20),
            (retention_risk_raw_100, 0.30),
            (gap_risk_raw_100, 0.20),
            (supply_pressure_risk_raw_100, 0.30),
        ]
    )
    fragility_raw_100 = min(100.0, max(0.0, (fragility_base_raw_100 * 1.5) - 10.0))
    fragility_source = "derived:close_structure_retention_gap_supply_fragility"
    failed_breakout_10 = raw_metrics.get("failed_breakout_10")
    if failed_breakout_10 is not None:
        failed_breakout_value = float(failed_breakout_10 or 0.0)
        if failed_breakout_value >= 3.0:
            fragility_raw_100 += 12.0
        elif failed_breakout_value >= 2.0:
            fragility_raw_100 += 7.0
        elif failed_breakout_value >= 1.0:
            fragility_raw_100 += 3.0
        fragility_source = "derived:close_structure_retention_gap_supply_failed_breakout_fragility"
    return round(min(100.0, fragility_raw_100), 4), fragility_source


def _fragile_breakout_risk_scores(profile: Any, *, activation_raw_100: float, fragility_raw_100: float) -> tuple[float, float, dict[str, float]]:
    activation_excess_ratio = _committee_excess_ratio(activation_raw_100, float(getattr(profile, "committee_fragile_breakout_activation_floor", 60.0) or 60.0))
    fragility_excess_ratio = _committee_excess_ratio(fragility_raw_100, float(getattr(profile, "committee_fragile_breakout_fragility_floor", 55.0) or 55.0))
    neutral_band = 0.03
    interaction_ratio = activation_excess_ratio * fragility_excess_ratio
    effective_interaction_ratio = clamp_unit_interval((interaction_ratio - neutral_band) / max(0.01, 0.18 - neutral_band))
    fragile_breakout_risk_raw_100 = round(float(getattr(profile, "committee_fragile_breakout_risk_cap", 85.0) or 85.0) * effective_interaction_ratio, 4)
    fragile_breakout_quality_raw_100 = round(100.0 - fragile_breakout_risk_raw_100, 4)
    return (
        fragile_breakout_risk_raw_100,
        fragile_breakout_quality_raw_100,
        {
            "activation_excess_ratio": round(activation_excess_ratio, 4),
            "fragility_excess_ratio": round(fragility_excess_ratio, 4),
            "interaction_ratio": round(interaction_ratio, 4),
            "effective_interaction_ratio": round(effective_interaction_ratio, 4),
        },
    )


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


def _resolve_committee_kill_switch(raw_metrics: dict[str, Any], gate: str) -> dict[str, Any]:
    return resolve_btst_kill_switch(raw_metrics, gate)


def _build_committee_penalties(snapshot: dict[str, Any], raw_metrics: dict[str, Any]) -> tuple[dict[str, float], float]:
    turnover_ratio_20 = raw_metrics.get("turnover_ratio_20")
    amount_ratio_5 = raw_metrics.get("amount_ratio_5")
    limit_up_memory_259 = raw_metrics.get("limit_up_memory_259")
    close_structure = raw_metrics.get("close_structure")
    close_support_30 = raw_metrics.get("close_support_30")
    supply_pressure_60 = raw_metrics.get("supply_pressure_60")

    overheat_penalty = 0.0
    if turnover_ratio_20 is not None and amount_ratio_5 is not None:
        turnover_value = float(turnover_ratio_20 or 0.0)
        amount_ratio_value = float(amount_ratio_5 or 0.0)
        limit_up_value = _normalized_ratio(limit_up_memory_259 or 0.0)
        if turnover_value >= 2.5 and limit_up_value >= 0.8 and amount_ratio_value >= 2.0:
            overheat_penalty = 0.08
        elif turnover_value >= 2.0 and amount_ratio_value >= 1.8:
            overheat_penalty = 0.04

    weak_close_penalty = 0.0
    if close_structure is not None:
        close_structure_value = float(close_structure or 0.0)
        close_support_value = float(close_support_30 or 0.0) if close_support_30 is not None else float(snapshot.get("close_strength", 0.0) or 0.0)
        if close_structure_value < 0.45 and close_support_value < 0.02:
            weak_close_penalty = 0.06
        elif close_structure_value < 0.50:
            weak_close_penalty = 0.03

    congestion_penalty = 0.0
    if supply_pressure_60 is not None:
        supply_pressure_value = float(supply_pressure_60 or 0.0)
        if supply_pressure_value > 0.25:
            congestion_penalty = 0.05
        elif supply_pressure_value > 0.18:
            congestion_penalty = 0.02

    penalties = {
        "overheat_penalty": round(overheat_penalty, 4),
        "weak_close_penalty": round(weak_close_penalty, 4),
        "congestion_penalty": round(congestion_penalty, 4),
    }
    penalty_total = round(sum(penalties.values()), 4)
    return penalties, penalty_total


def build_short_trade_committee_snapshot(*, input_data: Any, snapshot: dict[str, Any], profile: Any) -> dict[str, Any]:
    raw_metrics = _merge_raw_candidate_metrics(input_data)
    gate = _resolve_committee_gate(input_data=input_data, snapshot=snapshot)
    kill_switch = _resolve_committee_kill_switch(raw_metrics, gate)
    effective_gate = str(kill_switch["effective_gate"])
    thresholds = _resolve_committee_thresholds(profile=profile, gate=effective_gate)
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
    gap_risk_cap_raw_100 = _get_btst_gap_risk_cap_raw_100()
    liquidity_capacity_raw_100, liquidity_capacity_source = _liquidity_capacity_raw_score(snapshot, raw_metrics, input_data)
    crowding_risk_raw_100, crowding_source = _crowding_risk_raw_score(snapshot, raw_metrics)
    fragile_breakout_activation_raw_100, fragile_breakout_activation_source = _fragile_breakout_activation_raw_score(
        raw_metrics,
        attention_raw_100=attention_raw_100,
        crowding_risk_raw_100=crowding_risk_raw_100,
    )
    fragile_breakout_fragility_raw_100, fragile_breakout_fragility_source = _fragile_breakout_fragility_raw_score(
        raw_metrics,
        close_structure_raw_100=close_structure_raw_100,
        retention_raw_100=retention_raw_100,
        gap_risk_raw_100=gap_risk_raw_100,
        supply_pressure_risk_raw_100=supply_pressure_risk_raw_100,
    )
    fragile_breakout_risk_raw_100, fragile_breakout_quality_raw_100, fragile_breakout_risk_details = _fragile_breakout_risk_scores(
        profile,
        activation_raw_100=fragile_breakout_activation_raw_100,
        fragility_raw_100=fragile_breakout_fragility_raw_100,
    )
    theme_concentration_after_trade_raw_100, theme_source = _theme_concentration_risk_raw_score(raw_metrics, input_data)
    projected_theme_exposure = _as_float(raw_metrics, "projected_theme_exposure", _as_float(dict(input_data.replay_context or {}), "projected_theme_exposure"))
    incremental_theme_exposure = _as_float(raw_metrics, "incremental_theme_exposure", _as_float(dict(input_data.replay_context or {}), "incremental_theme_exposure"))
    theme_direction_peer_count = _as_float(raw_metrics, "theme_direction_peer_count")
    theme_direction_rank = _as_float(raw_metrics, "theme_direction_rank")
    sector_group_score = _committee_group_score(sector_raw_100)
    flow_group_score = _committee_group_score(flow_raw_100)
    retention_group_score = _committee_group_score(retention_raw_100)
    flow_60_raw_100 = _flow_60_raw_score(raw_metrics)
    penalties, penalty_total = _build_committee_penalties(snapshot, raw_metrics)

    fragile_breakout_enabled = bool(getattr(profile, "committee_fragile_breakout_risk_enabled", False))
    if fragile_breakout_enabled:
        fragile_breakout_alpha_weight = float(getattr(profile, "committee_fragile_breakout_alpha_weight", 0.10) or 0.10)
        alpha_components = [
            (sector_raw_100, 0.30),
            (flow_raw_100, 0.30),
            (structure_raw_100, 0.25),
            (attention_raw_100, max(0.0, 0.15 - fragile_breakout_alpha_weight)),
            (fragile_breakout_quality_raw_100, max(0.0, fragile_breakout_alpha_weight)),
        ]
    else:
        alpha_components = [
            (sector_raw_100, 0.30),
            (flow_raw_100, 0.30),
            (structure_raw_100, 0.25),
            (attention_raw_100, 0.15),
        ]
    alpha_edge_score = _weighted_average(alpha_components)
    beta_execution_score = _weighted_average(
        [
            (retention_raw_100, 0.40),
            (close_support_raw_100, 0.20),
            (100.0 - supply_pressure_risk_raw_100, 0.20),
            (100.0 - gap_risk_raw_100, 0.20),
        ]
    )

    gamma_components: list[tuple[float, float]] = [
        (100.0 if effective_gate == "aggressive_trade" else 75.0 if effective_gate == "normal_trade" else 20.0 if effective_gate == "shadow_only" else 0.0, 0.40),
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
    if bool(getattr(profile, "committee_isolated_attention_veto_enabled", True)) and attention_raw_100 >= float(getattr(profile, "committee_isolated_attention_min", 80.0) or 80.0) and sector_raw_100 <= float(getattr(profile, "committee_isolated_attention_sector_max", 60.0) or 60.0) and flow_60_raw_100 is not None and flow_60_raw_100 <= float(getattr(profile, "committee_isolated_attention_flow_max", 60.0) or 60.0):
        vetoes.append("committee_isolated_attention_veto")
    if bool(getattr(profile, "committee_weak_close_veto_enabled", True)) and flow_60_raw_100 is not None and flow_60_raw_100 >= float(getattr(profile, "committee_weak_close_flow_min", 75.0) or 75.0) and close_structure_raw_100 <= float(getattr(profile, "committee_weak_close_structure_max", 45.0) or 45.0) and close_support_raw_100 <= float(getattr(profile, "committee_weak_close_close_support_max", 60.0) or 60.0):
        vetoes.append("committee_weak_close_execution_veto")
    gap_to_limit = raw_metrics.get("gap_to_limit")
    if bool(getattr(profile, "committee_gap_to_limit_veto_enabled", True)) and gap_to_limit is not None and float(gap_to_limit or 0.0) <= float(getattr(profile, "committee_gap_to_limit_max", 0.01) or 0.01):
        vetoes.append("committee_gap_to_limit_veto")
    breakout_trap_guard = dict(snapshot.get("breakout_trap_guard") or {})
    historical_gap_chase_risk = float(breakout_trap_guard.get("historical_gap_chase_risk", 0.0) or 0.0)
    if bool(getattr(profile, "committee_failed_breakout_history_veto_enabled", True)) and historical_gap_chase_risk >= float(getattr(profile, "committee_failed_breakout_history_min", 1.0) or 1.0) and close_structure_raw_100 <= float(getattr(profile, "committee_weak_close_structure_max", 45.0) or 45.0):
        vetoes.append("committee_failed_breakout_history_veto")
    failed_breakout_10 = raw_metrics.get("failed_breakout_10")
    if bool(getattr(profile, "committee_failed_breakout_metric_veto_enabled", True)) and failed_breakout_10 is not None and float(failed_breakout_10 or 0.0) >= float(getattr(profile, "committee_failed_breakout_metric_min", 3.0) or 3.0) and close_structure_raw_100 <= float(getattr(profile, "committee_weak_close_structure_max", 45.0) or 45.0):
        vetoes.append("committee_failed_breakout_metric_veto")

    fail_reasons: list[str] = []
    # Shared BTST gap-risk guardrail must remain active even when advisory continuation
    # lanes disable selected_enforced; otherwise high-gap-risk candidates can still be
    # formally selected through the advisory path.
    if bool(getattr(profile, "committee_enabled", False)) and gap_risk_cap_raw_100 is not None:
        gap_risk_val = _get_btst_evaluation_bundle_module().coerce_numeric_metric_value(gap_risk_raw_100)
        # If we cannot coerce the observed gap risk to a finite number treat conservatively and block
        if gap_risk_val is None:
            fail_reasons.append("committee_gap_risk_cap_exceeded")
        elif gap_risk_val > gap_risk_cap_raw_100:
            fail_reasons.append("committee_gap_risk_cap_exceeded")

    if bool(thresholds["selected_enforced"]):
        if alpha_edge_score < float(thresholds["alpha_min"]):
            fail_reasons.append("committee_alpha_below_selected_min")
        if beta_execution_score < float(thresholds["beta_min"]):
            fail_reasons.append("committee_beta_below_selected_min")
        if gamma_risk_score < float(thresholds["gamma_min"]):
            fail_reasons.append("committee_gamma_below_selected_min")
        if committee_score < float(thresholds["committee_min"]):
            fail_reasons.append("committee_score_below_selected_min")
        if sector_group_score < float(thresholds["sector_group_score_min"]):
            fail_reasons.append("committee_sector_hard_gate_failed")
        if flow_group_score < float(thresholds["flow_group_score_min"]):
            fail_reasons.append("committee_flow_hard_gate_failed")
        if retention_group_score < float(thresholds["retention_group_score_min"]):
            fail_reasons.append("committee_retention_hard_gate_failed")
        if sector_group_score < 0.0 or flow_group_score < 0.0:
            fail_reasons.append("committee_negative_sector_or_flow_block")
        if penalty_total > float(thresholds["penalty_total_max"]):
            fail_reasons.append("committee_penalty_total_exceeded")
        if projected_theme_exposure > float(getattr(profile, "committee_theme_exposure_cap", 0.25) or 0.25):
            fail_reasons.append("committee_theme_exposure_cap_exceeded")
        if incremental_theme_exposure > float(getattr(profile, "committee_incremental_theme_exposure_cap", 0.18) or 0.18):
            fail_reasons.append("committee_incremental_theme_exposure_cap_exceeded")
        if bool(getattr(profile, "committee_isolated_theme_direction_enabled", True)) and theme_direction_peer_count > 0.0 and theme_direction_peer_count < float(getattr(profile, "committee_isolated_theme_peer_count_min", 2.0) or 2.0):
            fail_reasons.append("committee_isolated_theme_direction_block")
        if bool(getattr(profile, "committee_theme_direction_rank_enabled", True)) and theme_direction_rank > float(getattr(profile, "committee_theme_direction_rank_max", 5.0) or 5.0):
            fail_reasons.append("committee_theme_direction_rank_exceeded")

    if bool(kill_switch["active"]) and effective_gate in SHADOW_ONLY_GATES:
        fail_reasons.append("committee_kill_switch_active")

    formal_selected_allowed = bool(thresholds["formal_selected_allowed"])
    if effective_gate in SHADOW_ONLY_GATES and bool(getattr(profile, "committee_shadow_only_blocks_selected", True)):
        formal_selected_allowed = False
        fail_reasons.append("committee_shadow_profile_only")

    runner_escape_passed, runner_escape_reasons = _resolve_runner_escape(profile=profile, snapshot=snapshot, raw_metrics=raw_metrics)

    selected_pass = formal_selected_allowed and not vetoes and not fail_reasons
    component_status = {
        "alpha": "pass" if alpha_edge_score >= float(thresholds["alpha_min"]) else "advisory" if not bool(thresholds["selected_enforced"]) else "fail",
        "beta": "pass" if beta_execution_score >= float(thresholds["beta_min"]) else "advisory" if not bool(thresholds["selected_enforced"]) else "fail",
        "gamma": "pass" if gamma_risk_score >= float(thresholds["gamma_min"]) else "advisory" if not bool(thresholds["selected_enforced"]) else "fail",
        "committee": "pass" if committee_score >= float(thresholds["committee_min"]) else "advisory" if not bool(thresholds["selected_enforced"]) else "fail",
        "veto": "fail" if vetoes else "pass",
        "formal_selected": "pass" if selected_pass else "shadow_only" if effective_gate in SHADOW_ONLY_GATES and bool(getattr(profile, "committee_shadow_only_blocks_selected", True)) else "fail" if bool(thresholds["selected_enforced"]) or vetoes or fail_reasons else "advisory",
        "runner_escape": "pass" if runner_escape_passed else "fail",
    }
    if runner_escape_passed and component_status.get("formal_selected") == "fail":
        component_status["formal_selected"] = "advisory"

    return {
        "committee_enabled": bool(getattr(profile, "committee_enabled", False)),
        "committee_gate": gate,
        "committee_effective_gate": effective_gate,
        "committee_profile": COMMITTEE_PROFILE_BY_GATE.get(effective_gate, "retention_follow"),
        "committee_thresholds": {
            "alpha_min": round(float(thresholds["alpha_min"]), 4),
            "beta_min": round(float(thresholds["beta_min"]), 4),
            "gamma_min": round(float(thresholds["gamma_min"]), 4),
            "committee_min": round(float(thresholds["committee_min"]), 4),
            "sector_group_score_min": round(float(thresholds["sector_group_score_min"]), 4),
            "flow_group_score_min": round(float(thresholds["flow_group_score_min"]), 4),
            "retention_group_score_min": round(float(thresholds["retention_group_score_min"]), 4),
            "penalty_total_max": round(float(thresholds["penalty_total_max"]), 4),
            "selected_enforced": bool(thresholds["selected_enforced"]),
            "formal_selected_allowed": formal_selected_allowed,
            "theme_exposure_cap": round(float(getattr(profile, "committee_theme_exposure_cap", 0.25) or 0.25), 4),
            "incremental_theme_exposure_cap": round(float(getattr(profile, "committee_incremental_theme_exposure_cap", 0.18) or 0.18), 4),
            "gap_risk_cap_raw_100": round(float(gap_risk_cap_raw_100), 4) if gap_risk_cap_raw_100 is not None else None,
            "isolated_theme_peer_count_min": round(float(getattr(profile, "committee_isolated_theme_peer_count_min", 2.0) or 2.0), 4),
            "theme_direction_rank_max": round(float(getattr(profile, "committee_theme_direction_rank_max", 5.0) or 5.0), 4),
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
            "fragile_breakout_activation_raw_100": round(fragile_breakout_activation_raw_100, 4),
            "fragile_breakout_fragility_raw_100": round(fragile_breakout_fragility_raw_100, 4),
            "fragile_breakout_risk_raw_100": round(fragile_breakout_risk_raw_100, 4),
            "fragile_breakout_quality_raw_100": round(fragile_breakout_quality_raw_100, 4),
            "theme_concentration_after_trade_raw_100": round(theme_concentration_after_trade_raw_100, 4) if theme_concentration_after_trade_raw_100 is not None else None,
            "projected_theme_exposure": round(projected_theme_exposure, 4) if projected_theme_exposure > 0.0 else None,
            "incremental_theme_exposure": round(incremental_theme_exposure, 4) if incremental_theme_exposure > 0.0 else None,
            "theme_direction_peer_count": round(theme_direction_peer_count, 4) if theme_direction_peer_count > 0.0 else None,
            "theme_direction_rank": round(theme_direction_rank, 4) if theme_direction_rank > 0.0 else None,
            "sector_group_score": round(sector_group_score, 4),
            "flow_group_score": round(flow_group_score, 4),
            "retention_group_score": round(retention_group_score, 4),
            "overheat_penalty": penalties["overheat_penalty"],
            "weak_close_penalty": penalties["weak_close_penalty"],
            "congestion_penalty": penalties["congestion_penalty"],
            "penalty_total": penalty_total,
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
            "fragile_breakout_activation_raw_100": fragile_breakout_activation_source,
            "fragile_breakout_fragility_raw_100": fragile_breakout_fragility_source,
            "fragile_breakout_risk_raw_100": "derived:fragile_breakout_formula",
            "fragile_breakout_quality_raw_100": "derived:fragile_breakout_formula",
            "theme_concentration_after_trade_raw_100": theme_source,
            "projected_theme_exposure": "raw:projected_theme_exposure" if projected_theme_exposure > 0.0 else "missing",
            "incremental_theme_exposure": "raw:incremental_theme_exposure" if incremental_theme_exposure > 0.0 else "missing",
            "theme_direction_peer_count": "raw:theme_direction_context" if theme_direction_peer_count > 0.0 else "missing",
            "theme_direction_rank": "raw:theme_direction_context" if theme_direction_rank > 0.0 else "missing",
            "sector_group_score": "derived:raw_score_mapping",
            "flow_group_score": "derived:raw_score_mapping",
            "retention_group_score": "derived:raw_score_mapping",
            "penalty_total": "raw:committee_penalty_formula",
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
        "runner_escape_reasons": runner_escape_reasons,
        "committee_kill_switch": kill_switch,
        "committee_fragile_breakout_risk_details": fragile_breakout_risk_details,
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
        if "committee_kill_switch_active" in threshold_fail_reasons:
            _append_unique(blockers, "committee_kill_switch_active")
            _append_unique(negative_tags, "committee_kill_switch_active")
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
        if "committee_gap_to_limit_veto" in vetoes:
            _append_unique(blockers, "committee_gap_to_limit_veto")
            gate_status["committee"] = "veto"
            gate_status["score"] = "fail"
            return "rejected", downgrade_reasons
        if "committee_failed_breakout_history_veto" in vetoes:
            _append_unique(blockers, "committee_failed_breakout_history_veto")
            gate_status["committee"] = "veto"
            gate_status["score"] = "fail"
            return "rejected", downgrade_reasons
        if "committee_failed_breakout_metric_veto" in vetoes:
            _append_unique(blockers, "committee_failed_breakout_metric_veto")
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
