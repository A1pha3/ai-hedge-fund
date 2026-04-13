from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.targets.explainability import derive_confidence, trim_reasons
from src.targets.models import TargetEvaluationInput, TargetEvaluationResult


@dataclass(frozen=True)
class ShortTradeEvaluationContext:
    snapshot: dict[str, Any]
    carryover_evidence_deficiency: dict[str, Any]
    selected_historical_proof_deficiency: dict[str, Any]


@dataclass(frozen=True)
class ShortTradeThresholdState:
    breakout_freshness: float
    trend_acceleration: float
    effective_near_miss_threshold: float
    effective_select_threshold: float
    selected_score_tolerance: float
    breakout_stage: str
    selected_breakout_gate_pass: bool
    near_miss_breakout_gate_pass: bool


@dataclass(frozen=True)
class ShortTradeVerdict:
    decision: str
    confidence: float
    positive_tags: list[str]
    negative_tags: list[str]
    blockers: list[str]
    gate_status: dict[str, Any]
    top_reasons: list[str]
    rejection_reasons: list[str]


@dataclass(frozen=True)
class ShortTradeMutableVerdictState:
    gate_status: dict[str, Any]
    positive_tags: list[str]
    negative_tags: list[str]
    blockers: list[str]


@dataclass(frozen=True)
class ShortTradeDecisionSnapshotState:
    profile: Any
    breakout_freshness: float
    trend_acceleration: float
    raw_catalyst_freshness: float
    catalyst_freshness: float
    score_target: float
    effective_near_miss_threshold: float
    effective_select_threshold: float
    selected_score_tolerance: float
    positive_tags: list[str]
    negative_tags: list[str]
    blockers: list[str]
    gate_status: dict[str, Any]


@dataclass(frozen=True)
class ShortTradeTopReasonsState:
    breakout_freshness: float
    trend_acceleration: float
    raw_catalyst_freshness: float
    upstream_shadow_catalyst_relief_applied: bool
    upstream_shadow_catalyst_relief_reason: str
    visibility_gap_continuation_relief: dict[str, Any]
    merge_approved_continuation_relief: dict[str, Any]
    prepared_breakout_penalty_relief: dict[str, Any]
    prepared_breakout_catalyst_relief: dict[str, Any]
    prepared_breakout_volume_relief: dict[str, Any]
    prepared_breakout_continuation_relief: dict[str, Any]
    prepared_breakout_selected_catalyst_relief: dict[str, Any]
    profitability_relief_applied: bool
    profitability_hard_cliff_boundary_relief: dict[str, Any]
    historical_execution_relief: dict[str, Any]
    profitability_hard_cliff: bool
    breakout_stage: str
    layer_c_avoid_penalty: float
    stale_trend_repair_penalty: float
    overhead_supply_penalty: float
    extension_without_room_penalty: float
    watchlist_zero_catalyst_guard: dict[str, Any]
    watchlist_zero_catalyst_crowded_guard: dict[str, Any]
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any]
    carryover_evidence_deficiency: dict[str, Any]
    selected_historical_proof_deficiency: dict[str, Any]
    t_plus_2_continuation_candidate: dict[str, Any]
    score_target: float


@dataclass(frozen=True)
class ShortTradeExplainabilityState:
    profile: Any
    profitability_hard_cliff_boundary_relief: dict[str, Any]
    historical_execution_relief: dict[str, Any]
    visibility_gap_continuation_relief: dict[str, Any]
    merge_approved_continuation_relief: dict[str, Any]
    prepared_breakout_penalty_relief: dict[str, Any]
    prepared_breakout_catalyst_relief: dict[str, Any]
    prepared_breakout_volume_relief: dict[str, Any]
    prepared_breakout_continuation_relief: dict[str, Any]
    prepared_breakout_selected_catalyst_relief: dict[str, Any]
    watchlist_zero_catalyst_guard: dict[str, Any]
    watchlist_zero_catalyst_crowded_guard: dict[str, Any]
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any]
    t_plus_2_continuation_candidate: dict[str, Any]


def build_short_trade_evaluation_context(
    *,
    snapshot: dict[str, Any],
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
) -> ShortTradeEvaluationContext:
    return ShortTradeEvaluationContext(
        snapshot=dict(snapshot),
        carryover_evidence_deficiency=dict(carryover_evidence_deficiency),
        selected_historical_proof_deficiency=dict(selected_historical_proof_deficiency),
    )


def _summarize_positive_factor(name: str, value: float) -> str | None:
    if value >= 0.8:
        return f"{name}_strong"
    if value >= 0.65:
        return f"{name}_supportive"
    return None


def _summarize_penalty(name: str, value: float) -> str | None:
    if value >= 0.25:
        return f"{name}_heavy"
    if value >= 0.1:
        return f"{name}_active"
    return None


def _classify_breakout_stage(*, breakout_freshness: float, trend_acceleration: float, profile: Any) -> tuple[str, bool, bool]:
    selected_breakout_gate_pass = breakout_freshness >= float(profile.selected_breakout_freshness_min) and trend_acceleration >= float(profile.selected_trend_acceleration_min)
    near_miss_breakout_gate_pass = breakout_freshness >= float(profile.near_miss_breakout_freshness_min) and trend_acceleration >= float(profile.near_miss_trend_acceleration_min)
    if selected_breakout_gate_pass:
        return "confirmed_breakout", True, True
    if near_miss_breakout_gate_pass:
        return "prepared_breakout", False, True
    return "watchlist_breakout", False, False


def _collect_breakout_gate_misses(*, breakout_freshness: float, trend_acceleration: float, breakout_min: float, trend_min: float, label: str) -> list[str]:
    misses: list[str] = []
    if breakout_freshness < breakout_min:
        misses.append(f"{label}_breakout_freshness_below_min")
    if trend_acceleration < trend_min:
        misses.append(f"{label}_trend_acceleration_below_min")
    return misses


def _preferred_entry_mode_from_historical_prior(historical_prior: dict[str, Any] | None) -> str:
    execution_quality_label = str((historical_prior or {}).get("execution_quality_label") or "unknown")
    if execution_quality_label == "intraday_only":
        return "intraday_confirmation_only"
    if execution_quality_label == "gap_chase_risk":
        return "avoid_open_chase_confirmation"
    if execution_quality_label == "close_continuation":
        return "confirm_then_hold_breakout"
    if execution_quality_label == "zero_follow_through":
        return "strong_reconfirmation_only"
    return "next_day_breakout_confirmation"


def _resolve_short_trade_decision(
    *,
    blockers: list[str],
    gate_status: dict[str, Any],
    score_target: float,
    effective_near_miss_threshold: float,
    effective_select_threshold: float,
    selected_score_tolerance: float,
    selected_breakout_gate_pass: bool,
    near_miss_breakout_gate_pass: bool,
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
) -> str:
    selected_score_pass = score_target >= (effective_select_threshold - selected_score_tolerance)

    if blockers:
        decision = "blocked" if gate_status["data"] == "fail" or "layer_c_bearish_conflict" in blockers or "trend_not_constructive" in blockers else "rejected"
    elif selected_score_pass and selected_breakout_gate_pass:
        decision = "selected"
        gate_status["score"] = "pass"
    elif selected_score_pass and near_miss_breakout_gate_pass:
        decision = "near_miss"
        gate_status["score"] = "near_miss"
    elif score_target >= effective_near_miss_threshold and near_miss_breakout_gate_pass:
        decision = "near_miss"
        gate_status["score"] = "near_miss"
    else:
        decision = "rejected"

    if carryover_evidence_deficiency["evidence_deficient"] and decision in {"selected", "near_miss"}:
        gate_status["score"] = "fail"
        return "rejected"
    if selected_historical_proof_deficiency["proof_missing"] and decision == "selected":
        gate_status["score"] = "near_miss"
        return "near_miss"
    return decision


def _annotate_short_trade_tags(
    *,
    positive_tags: list[str],
    negative_tags: list[str],
    breakout_stage: str,
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
) -> None:
    if breakout_stage == "confirmed_breakout":
        positive_tags.append("confirmed_breakout_stage")
    elif breakout_stage == "prepared_breakout":
        positive_tags.append("prepared_breakout_stage")

    if carryover_evidence_deficiency["evidence_deficient"]:
        negative_tags.append("evidence_deficient_broad_family_only")
    if selected_historical_proof_deficiency["proof_missing"]:
        negative_tags.append("selected_historical_proof_missing")


def _collect_short_trade_relief_reasons(
    *,
    upstream_shadow_catalyst_relief_applied: bool,
    upstream_shadow_catalyst_relief_reason: str,
    visibility_gap_continuation_relief: dict[str, Any],
    merge_approved_continuation_relief: dict[str, Any],
    prepared_breakout_penalty_relief: dict[str, Any],
    prepared_breakout_catalyst_relief: dict[str, Any],
    prepared_breakout_volume_relief: dict[str, Any],
    prepared_breakout_continuation_relief: dict[str, Any],
    prepared_breakout_selected_catalyst_relief: dict[str, Any],
    profitability_relief_applied: bool,
    profitability_hard_cliff_boundary_relief: dict[str, Any],
    historical_execution_relief: dict[str, Any],
) -> list[str | None]:
    return [
        upstream_shadow_catalyst_relief_reason if upstream_shadow_catalyst_relief_applied else None,
        "visibility_gap_continuation_relief" if visibility_gap_continuation_relief["applied"] else None,
        "merge_approved_continuation_relief" if merge_approved_continuation_relief["applied"] else None,
        "prepared_breakout_penalty_relief" if prepared_breakout_penalty_relief["applied"] else None,
        "prepared_breakout_catalyst_relief" if prepared_breakout_catalyst_relief["applied"] else None,
        "prepared_breakout_volume_relief" if prepared_breakout_volume_relief["applied"] else None,
        "prepared_breakout_continuation_relief" if prepared_breakout_continuation_relief["applied"] else None,
        "prepared_breakout_selected_catalyst_relief" if prepared_breakout_selected_catalyst_relief["applied"] else None,
        "profitability_relief_applied" if profitability_relief_applied else None,
        "profitability_hard_cliff_boundary_relief" if profitability_hard_cliff_boundary_relief.get("applied") else None,
        "historical_execution_relief" if historical_execution_relief.get("applied") else None,
    ]


def _collect_short_trade_penalty_reasons(
    *,
    profitability_hard_cliff: bool,
    profitability_relief_applied: bool,
    breakout_stage: str,
    layer_c_avoid_penalty: float,
    stale_trend_repair_penalty: float,
    overhead_supply_penalty: float,
    extension_without_room_penalty: float,
    watchlist_zero_catalyst_guard: dict[str, Any],
    watchlist_zero_catalyst_crowded_guard: dict[str, Any],
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any],
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
    t_plus_2_continuation_candidate: dict[str, Any],
    score_target: float,
) -> list[str | None]:
    return [
        "profitability_hard_cliff" if profitability_hard_cliff and not profitability_relief_applied else None,
        breakout_stage,
        _summarize_penalty("layer_c_avoid_penalty", layer_c_avoid_penalty),
        _summarize_penalty("stale_trend_repair_penalty", stale_trend_repair_penalty),
        _summarize_penalty("overhead_supply_penalty", overhead_supply_penalty),
        _summarize_penalty("extension_without_room_penalty", extension_without_room_penalty),
        "watchlist_zero_catalyst_penalty_applied" if watchlist_zero_catalyst_guard["applied"] else None,
        "watchlist_zero_catalyst_crowded_penalty_applied" if watchlist_zero_catalyst_crowded_guard["applied"] else None,
        "watchlist_zero_catalyst_flat_trend_penalty_applied" if watchlist_zero_catalyst_flat_trend_guard["applied"] else None,
        "evidence_deficient_broad_family_only" if carryover_evidence_deficiency["evidence_deficient"] else None,
        "selected_historical_proof_missing" if selected_historical_proof_deficiency["proof_missing"] else None,
        "t_plus_2_continuation_candidate" if t_plus_2_continuation_candidate["applied"] else None,
        f"score_short={score_target:.2f}",
    ]


def _build_short_trade_top_reasons(
    *,
    state: ShortTradeTopReasonsState,
) -> list[str]:
    reasons = [
        _summarize_positive_factor("breakout_freshness", state.breakout_freshness),
        _summarize_positive_factor("trend_acceleration", state.trend_acceleration),
        _summarize_positive_factor("catalyst_freshness", state.raw_catalyst_freshness),
        *_collect_short_trade_relief_reasons(
            upstream_shadow_catalyst_relief_applied=state.upstream_shadow_catalyst_relief_applied,
            upstream_shadow_catalyst_relief_reason=state.upstream_shadow_catalyst_relief_reason,
            visibility_gap_continuation_relief=state.visibility_gap_continuation_relief,
            merge_approved_continuation_relief=state.merge_approved_continuation_relief,
            prepared_breakout_penalty_relief=state.prepared_breakout_penalty_relief,
            prepared_breakout_catalyst_relief=state.prepared_breakout_catalyst_relief,
            prepared_breakout_volume_relief=state.prepared_breakout_volume_relief,
            prepared_breakout_continuation_relief=state.prepared_breakout_continuation_relief,
            prepared_breakout_selected_catalyst_relief=state.prepared_breakout_selected_catalyst_relief,
            profitability_relief_applied=state.profitability_relief_applied,
            profitability_hard_cliff_boundary_relief=state.profitability_hard_cliff_boundary_relief,
            historical_execution_relief=state.historical_execution_relief,
        ),
        *_collect_short_trade_penalty_reasons(
            profitability_hard_cliff=state.profitability_hard_cliff,
            profitability_relief_applied=state.profitability_relief_applied,
            breakout_stage=state.breakout_stage,
            layer_c_avoid_penalty=state.layer_c_avoid_penalty,
            stale_trend_repair_penalty=state.stale_trend_repair_penalty,
            overhead_supply_penalty=state.overhead_supply_penalty,
            extension_without_room_penalty=state.extension_without_room_penalty,
            watchlist_zero_catalyst_guard=state.watchlist_zero_catalyst_guard,
            watchlist_zero_catalyst_crowded_guard=state.watchlist_zero_catalyst_crowded_guard,
            watchlist_zero_catalyst_flat_trend_guard=state.watchlist_zero_catalyst_flat_trend_guard,
            carryover_evidence_deficiency=state.carryover_evidence_deficiency,
            selected_historical_proof_deficiency=state.selected_historical_proof_deficiency,
            t_plus_2_continuation_candidate=state.t_plus_2_continuation_candidate,
            score_target=state.score_target,
        ),
    ]
    return trim_reasons(
        [reason for reason in reasons if reason is not None]
    )


def _build_short_trade_rejection_reasons(
    *,
    decision: str,
    blockers: list[str],
    breakout_freshness: float,
    trend_acceleration: float,
    effective_near_miss_threshold: float,
    score_target: float,
    near_miss_breakout_gate_pass: bool,
    profile: Any,
    carryover_evidence_deficiency: dict[str, Any],
) -> list[str]:
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
    if decision == "rejected" and carryover_evidence_deficiency["evidence_deficient"]:
        return trim_reasons(["evidence_deficient_broad_family_only", *rejection_reasons])
    return rejection_reasons


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


def _build_watchlist_metrics_payload(
    *,
    snapshot: dict[str, Any],
    t_plus_2_continuation_candidate: dict[str, Any],
    watchlist_zero_catalyst_guard: dict[str, Any],
    watchlist_zero_catalyst_crowded_guard: dict[str, Any],
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any],
) -> dict[str, Any]:
    return {
        "watchlist_zero_catalyst_penalty": round(float(snapshot["watchlist_zero_catalyst_penalty"]), 4),
        "watchlist_zero_catalyst_crowded_penalty": round(float(snapshot["watchlist_zero_catalyst_crowded_penalty"]), 4),
        "watchlist_zero_catalyst_flat_trend_penalty": round(float(snapshot["watchlist_zero_catalyst_flat_trend_penalty"]), 4),
        "t_plus_2_continuation_candidate": _build_t_plus_2_continuation_candidate_metrics_payload(t_plus_2_continuation_candidate),
        "watchlist_zero_catalyst_guard": _build_watchlist_guard_metrics_payload(watchlist_zero_catalyst_guard),
        "watchlist_zero_catalyst_crowded_guard": _build_watchlist_guard_metrics_payload(watchlist_zero_catalyst_crowded_guard),
        "watchlist_zero_catalyst_flat_trend_guard": _build_watchlist_guard_metrics_payload(watchlist_zero_catalyst_flat_trend_guard),
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
        "effective_positive_score_weights": {name: round(float(value), 4) for name, value in positive_score_weights.items()},
        "stale_penalty_block_threshold": round(float(profile.stale_penalty_block_threshold), 4),
        "overhead_penalty_block_threshold": round(float(profile.overhead_penalty_block_threshold), 4),
        "extension_penalty_block_threshold": round(float(profile.extension_penalty_block_threshold), 4),
        "layer_c_avoid_penalty": round(float(profile.layer_c_avoid_penalty), 4),
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
        "sector_resonance": round(float(snapshot["sector_resonance"]), 4),
        "catalyst_freshness": round(float(snapshot["raw_catalyst_freshness"]), 4),
        "effective_catalyst_freshness": round(float(snapshot["catalyst_freshness"]), 4),
        "layer_c_alignment": round(float(snapshot["layer_c_alignment"]), 4),
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
    weighted_positive_contributions: dict[str, Any],
    weighted_negative_contributions: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stale_trend_repair_penalty": round(float(snapshot["stale_trend_repair_penalty"]), 4),
        "overhead_supply_penalty": round(float(snapshot["overhead_supply_penalty"]), 4),
        "extension_without_room_penalty": round(float(snapshot["extension_without_room_penalty"]), 4),
        "weighted_positive_contributions": weighted_positive_contributions,
        "weighted_negative_contributions": weighted_negative_contributions,
        "total_positive_contribution": round(float(snapshot["total_positive_contribution"]), 4),
        "total_negative_contribution": round(float(snapshot["total_negative_contribution"]), 4),
    }


def _collect_short_trade_metrics_payload_inputs(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "historical_execution_relief": dict(snapshot["historical_execution_relief"]),
        "profitability_hard_cliff_boundary_relief": dict(snapshot["profitability_hard_cliff_boundary_relief"]),
        "t_plus_2_continuation_candidate": dict(snapshot["t_plus_2_continuation_candidate"]),
        "watchlist_zero_catalyst_guard": dict(snapshot["watchlist_zero_catalyst_guard"]),
        "watchlist_zero_catalyst_crowded_guard": dict(snapshot["watchlist_zero_catalyst_crowded_guard"]),
        "watchlist_zero_catalyst_flat_trend_guard": dict(snapshot["watchlist_zero_catalyst_flat_trend_guard"]),
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
        "profitability_hard_cliff_boundary_relief": _build_profitability_hard_cliff_boundary_relief_metrics_payload(
            metrics_inputs["profitability_hard_cliff_boundary_relief"]
        ),
        "visibility_gap_continuation_relief": _build_visibility_gap_continuation_relief_metrics_payload(
            metrics_inputs["visibility_gap_continuation_relief"]
        ),
        "merge_approved_continuation_relief": _build_merge_approved_continuation_relief_metrics_payload(
            metrics_inputs["merge_approved_continuation_relief"]
        ),
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


def _build_upstream_shadow_explainability_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(snapshot["upstream_shadow_catalyst_relief_enabled"]),
        "eligible": bool(snapshot["upstream_shadow_catalyst_relief_eligible"]),
        "applied": bool(snapshot["upstream_shadow_catalyst_relief_applied"]),
        "reason": str(snapshot["upstream_shadow_catalyst_relief_reason"]),
        "gate_hits": dict(snapshot["upstream_shadow_catalyst_relief_gate_hits"]),
        "base_catalyst_freshness": round(float(snapshot["raw_catalyst_freshness"]), 4),
        "effective_catalyst_freshness": round(float(snapshot["catalyst_freshness"]), 4),
        "catalyst_freshness_floor": round(float(snapshot["upstream_shadow_catalyst_relief_catalyst_freshness_floor"]), 4),
        "base_near_miss_threshold": round(float(snapshot["upstream_shadow_catalyst_relief_base_near_miss_threshold"]), 4),
        "effective_near_miss_threshold": round(float(snapshot["effective_near_miss_threshold"]), 4),
        "near_miss_threshold_override": round(float(snapshot["upstream_shadow_catalyst_relief_near_miss_threshold_override"]), 4),
        "base_select_threshold": round(float(snapshot["upstream_shadow_catalyst_relief_base_select_threshold"]), 4),
        "effective_select_threshold": round(float(snapshot["effective_select_threshold"]), 4),
        "selected_score_tolerance": round(float(snapshot["selected_score_tolerance"]), 4),
        "select_threshold_override": round(float(snapshot["upstream_shadow_catalyst_relief_select_threshold_override"]), 4),
        "require_no_profitability_hard_cliff": bool(snapshot["upstream_shadow_catalyst_relief_require_no_profitability_hard_cliff"]),
    }


def _build_prepared_breakout_penalty_explainability_payload(prepared_breakout_penalty_relief: dict[str, Any]) -> dict[str, Any]:
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


def _build_prepared_breakout_catalyst_explainability_payload(prepared_breakout_catalyst_relief: dict[str, Any]) -> dict[str, Any]:
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


def _build_watchlist_guard_explainability_payload(watchlist_guard: dict[str, Any], *, effective_penalty: float) -> dict[str, Any]:
    return {
        **_build_watchlist_guard_metrics_payload(watchlist_guard),
        "effective_penalty": round(float(effective_penalty), 4),
    }


def _build_short_trade_core_explainability_payload(
    *,
    input_data: TargetEvaluationInput,
    profile: Any,
    snapshot: dict[str, Any],
    breakout_stage: str,
) -> dict[str, Any]:
    return {
        "source": str(input_data.replay_context.get("source") or "short_trade_target_rules_v1"),
        "target_profile": profile.name,
        "breakout_stage": breakout_stage,
        "trade_date": input_data.trade_date,
        "layer_c_decision": input_data.layer_c_decision,
        "bc_conflict": input_data.bc_conflict,
        "candidate_source": str(input_data.replay_context.get("source") or ""),
        "available_strategy_signals": sorted(str(name) for name in dict(input_data.strategy_signals or {}).keys()),
        "profitability_relief": _build_profitability_explainability_payload(snapshot),
        "upstream_shadow_catalyst_relief": _build_upstream_shadow_explainability_payload(snapshot),
    }


def _build_short_trade_historical_explainability_payload(
    *,
    snapshot: dict[str, Any],
    profitability_hard_cliff_boundary_relief: dict[str, Any],
    historical_execution_relief: dict[str, Any],
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
) -> dict[str, Any]:
    return {
        "profitability_hard_cliff_boundary_relief": _build_profitability_hard_cliff_boundary_relief_metrics_payload(profitability_hard_cliff_boundary_relief),
        "historical_prior": dict(snapshot["historical_prior"]),
        "historical_execution_relief": _build_historical_execution_relief_metrics_payload(historical_execution_relief),
        "carryover_evidence_deficiency": _build_carryover_evidence_deficiency_metrics_payload(carryover_evidence_deficiency),
        "selected_historical_proof_deficiency": _build_selected_historical_proof_deficiency_metrics_payload(selected_historical_proof_deficiency),
    }


def _build_short_trade_continuation_explainability_payload(
    *,
    visibility_gap_continuation_relief: dict[str, Any],
    merge_approved_continuation_relief: dict[str, Any],
) -> dict[str, Any]:
    return {
        "visibility_gap_continuation_relief": _build_visibility_gap_continuation_relief_metrics_payload(visibility_gap_continuation_relief),
        "merge_approved_continuation_relief": _build_merge_approved_continuation_relief_metrics_payload(merge_approved_continuation_relief),
    }


def _build_short_trade_prepared_breakout_explainability_payload(
    *,
    prepared_breakout_penalty_relief: dict[str, Any],
    prepared_breakout_catalyst_relief: dict[str, Any],
    prepared_breakout_volume_relief: dict[str, Any],
    prepared_breakout_continuation_relief: dict[str, Any],
    prepared_breakout_selected_catalyst_relief: dict[str, Any],
) -> dict[str, Any]:
    return {
        "prepared_breakout_penalty_relief": _build_prepared_breakout_penalty_explainability_payload(prepared_breakout_penalty_relief),
        "prepared_breakout_catalyst_relief": _build_prepared_breakout_catalyst_explainability_payload(prepared_breakout_catalyst_relief),
        "prepared_breakout_volume_relief": _build_prepared_breakout_volume_relief_metrics_payload(prepared_breakout_volume_relief),
        "prepared_breakout_continuation_relief": _build_prepared_breakout_continuation_relief_metrics_payload(prepared_breakout_continuation_relief),
        "prepared_breakout_selected_catalyst_relief": _build_prepared_breakout_selected_catalyst_relief_metrics_payload(prepared_breakout_selected_catalyst_relief),
    }


def _build_short_trade_watchlist_explainability_payload(
    *,
    snapshot: dict[str, Any],
    watchlist_zero_catalyst_guard: dict[str, Any],
    watchlist_zero_catalyst_crowded_guard: dict[str, Any],
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any],
    t_plus_2_continuation_candidate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "watchlist_zero_catalyst_guard": _build_watchlist_guard_explainability_payload(
            watchlist_zero_catalyst_guard,
            effective_penalty=float(snapshot["watchlist_zero_catalyst_penalty"]),
        ),
        "watchlist_zero_catalyst_crowded_guard": _build_watchlist_guard_explainability_payload(
            watchlist_zero_catalyst_crowded_guard,
            effective_penalty=float(snapshot["watchlist_zero_catalyst_crowded_penalty"]),
        ),
        "watchlist_zero_catalyst_flat_trend_guard": _build_watchlist_guard_explainability_payload(
            watchlist_zero_catalyst_flat_trend_guard,
            effective_penalty=float(snapshot["watchlist_zero_catalyst_flat_trend_penalty"]),
        ),
        "t_plus_2_continuation_candidate": _build_t_plus_2_continuation_candidate_metrics_payload(t_plus_2_continuation_candidate),
    }


def _build_short_trade_metrics_payload(
    *,
    input_data: TargetEvaluationInput,
    profile: Any,
    snapshot: dict[str, Any],
    breakout_stage: str,
    selected_breakout_gate_pass: bool,
    near_miss_breakout_gate_pass: bool,
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
) -> dict[str, Any]:
    metrics_inputs = _collect_short_trade_metrics_payload_inputs(snapshot)
    return {
        **_build_short_trade_core_metrics_payload(
            input_data=input_data,
            snapshot=snapshot,
            positive_score_weights=metrics_inputs["positive_score_weights"],
            breakout_freshness=float(snapshot["breakout_freshness"]),
            trend_acceleration=float(snapshot["trend_acceleration"]),
            breakout_stage=breakout_stage,
            selected_breakout_gate_pass=selected_breakout_gate_pass,
            near_miss_breakout_gate_pass=near_miss_breakout_gate_pass,
        ),
        **_build_profitability_metrics_payload(snapshot),
        **_build_short_trade_context_metrics_payload(
            carryover_evidence_deficiency=carryover_evidence_deficiency,
            selected_historical_proof_deficiency=selected_historical_proof_deficiency,
        ),
        **_build_watchlist_metrics_payload(
            snapshot=snapshot,
            t_plus_2_continuation_candidate=metrics_inputs["t_plus_2_continuation_candidate"],
            watchlist_zero_catalyst_guard=metrics_inputs["watchlist_zero_catalyst_guard"],
            watchlist_zero_catalyst_crowded_guard=metrics_inputs["watchlist_zero_catalyst_crowded_guard"],
            watchlist_zero_catalyst_flat_trend_guard=metrics_inputs["watchlist_zero_catalyst_flat_trend_guard"],
        ),
        **_build_upstream_shadow_metrics_payload(snapshot),
        **_build_short_trade_relief_metrics_payload(metrics_inputs),
        **_build_short_trade_penalty_metrics_payload(
            snapshot=snapshot,
            weighted_positive_contributions=metrics_inputs["weighted_positive_contributions"],
            weighted_negative_contributions=metrics_inputs["weighted_negative_contributions"],
        ),
        "thresholds": _build_short_trade_threshold_metrics_payload(
            profile=profile,
            snapshot=snapshot,
            positive_score_weights=metrics_inputs["positive_score_weights"],
        ),
    }


def _build_short_trade_explainability_payload(
    *,
    input_data: TargetEvaluationInput,
    snapshot: dict[str, Any],
    breakout_stage: str,
    state: ShortTradeExplainabilityState,
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
) -> dict[str, Any]:
    return {
        **_build_short_trade_core_explainability_payload(
            input_data=input_data,
            profile=state.profile,
            snapshot=snapshot,
            breakout_stage=breakout_stage,
        ),
        **_build_short_trade_historical_explainability_payload(
            snapshot=snapshot,
            profitability_hard_cliff_boundary_relief=state.profitability_hard_cliff_boundary_relief,
            historical_execution_relief=state.historical_execution_relief,
            carryover_evidence_deficiency=carryover_evidence_deficiency,
            selected_historical_proof_deficiency=selected_historical_proof_deficiency,
        ),
        **_build_short_trade_continuation_explainability_payload(
            visibility_gap_continuation_relief=state.visibility_gap_continuation_relief,
            merge_approved_continuation_relief=state.merge_approved_continuation_relief,
        ),
        **_build_short_trade_prepared_breakout_explainability_payload(
            prepared_breakout_penalty_relief=state.prepared_breakout_penalty_relief,
            prepared_breakout_catalyst_relief=state.prepared_breakout_catalyst_relief,
            prepared_breakout_volume_relief=state.prepared_breakout_volume_relief,
            prepared_breakout_continuation_relief=state.prepared_breakout_continuation_relief,
            prepared_breakout_selected_catalyst_relief=state.prepared_breakout_selected_catalyst_relief,
        ),
        **_build_short_trade_watchlist_explainability_payload(
            snapshot=snapshot,
            watchlist_zero_catalyst_guard=state.watchlist_zero_catalyst_guard,
            watchlist_zero_catalyst_crowded_guard=state.watchlist_zero_catalyst_crowded_guard,
            watchlist_zero_catalyst_flat_trend_guard=state.watchlist_zero_catalyst_flat_trend_guard,
            t_plus_2_continuation_candidate=state.t_plus_2_continuation_candidate,
        ),
        "replay_context": dict(input_data.replay_context or {}),
    }


def resolve_short_trade_thresholds(context: ShortTradeEvaluationContext) -> ShortTradeThresholdState:
    snapshot = context.snapshot
    profile = snapshot["profile"]
    breakout_freshness = float(snapshot["breakout_freshness"])
    trend_acceleration = float(snapshot["trend_acceleration"])
    breakout_stage, selected_breakout_gate_pass, near_miss_breakout_gate_pass = _classify_breakout_stage(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        profile=profile,
    )
    return ShortTradeThresholdState(
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        effective_near_miss_threshold=float(snapshot["effective_near_miss_threshold"]),
        effective_select_threshold=float(snapshot["effective_select_threshold"]),
        selected_score_tolerance=float(snapshot["selected_score_tolerance"]),
        breakout_stage=breakout_stage,
        selected_breakout_gate_pass=selected_breakout_gate_pass,
        near_miss_breakout_gate_pass=near_miss_breakout_gate_pass,
    )


def _build_short_trade_mutable_verdict_state(snapshot: dict[str, Any]) -> ShortTradeMutableVerdictState:
    return ShortTradeMutableVerdictState(
        gate_status=dict(snapshot["gate_status"]),
        positive_tags=list(snapshot["positive_tags"]),
        negative_tags=list(snapshot["negative_tags"]),
        blockers=list(snapshot["blockers"]),
    )


def _build_short_trade_top_reasons_state(
    *,
    snapshot: dict[str, Any],
    context: ShortTradeEvaluationContext,
    thresholds: ShortTradeThresholdState,
) -> ShortTradeTopReasonsState:
    return ShortTradeTopReasonsState(
        breakout_freshness=thresholds.breakout_freshness,
        trend_acceleration=thresholds.trend_acceleration,
        raw_catalyst_freshness=float(snapshot["raw_catalyst_freshness"]),
        upstream_shadow_catalyst_relief_applied=bool(snapshot["upstream_shadow_catalyst_relief_applied"]),
        upstream_shadow_catalyst_relief_reason=str(snapshot["upstream_shadow_catalyst_relief_reason"]),
        visibility_gap_continuation_relief=dict(snapshot["visibility_gap_continuation_relief"]),
        merge_approved_continuation_relief=dict(snapshot["merge_approved_continuation_relief"]),
        prepared_breakout_penalty_relief=dict(snapshot["prepared_breakout_penalty_relief"]),
        prepared_breakout_catalyst_relief=dict(snapshot["prepared_breakout_catalyst_relief"]),
        prepared_breakout_volume_relief=dict(snapshot["prepared_breakout_volume_relief"]),
        prepared_breakout_continuation_relief=dict(snapshot["prepared_breakout_continuation_relief"]),
        prepared_breakout_selected_catalyst_relief=dict(snapshot["prepared_breakout_selected_catalyst_relief"]),
        profitability_relief_applied=bool(snapshot["profitability_relief_applied"]),
        profitability_hard_cliff_boundary_relief=dict(snapshot["profitability_hard_cliff_boundary_relief"]),
        historical_execution_relief=dict(snapshot["historical_execution_relief"]),
        profitability_hard_cliff=bool(snapshot["profitability_hard_cliff"]),
        breakout_stage=thresholds.breakout_stage,
        layer_c_avoid_penalty=float(snapshot["layer_c_avoid_penalty"]),
        stale_trend_repair_penalty=float(snapshot["stale_trend_repair_penalty"]),
        overhead_supply_penalty=float(snapshot["overhead_supply_penalty"]),
        extension_without_room_penalty=float(snapshot["extension_without_room_penalty"]),
        watchlist_zero_catalyst_guard=dict(snapshot["watchlist_zero_catalyst_guard"]),
        watchlist_zero_catalyst_crowded_guard=dict(snapshot["watchlist_zero_catalyst_crowded_guard"]),
        watchlist_zero_catalyst_flat_trend_guard=dict(snapshot["watchlist_zero_catalyst_flat_trend_guard"]),
        carryover_evidence_deficiency=context.carryover_evidence_deficiency,
        selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
        t_plus_2_continuation_candidate=dict(snapshot["t_plus_2_continuation_candidate"]),
        score_target=float(snapshot["score_target"]),
    )


def _build_short_trade_explainability_state(snapshot: dict[str, Any]) -> ShortTradeExplainabilityState:
    return ShortTradeExplainabilityState(
        profile=snapshot["profile"],
        profitability_hard_cliff_boundary_relief=dict(snapshot["profitability_hard_cliff_boundary_relief"]),
        historical_execution_relief=dict(snapshot["historical_execution_relief"]),
        visibility_gap_continuation_relief=dict(snapshot["visibility_gap_continuation_relief"]),
        merge_approved_continuation_relief=dict(snapshot["merge_approved_continuation_relief"]),
        prepared_breakout_penalty_relief=dict(snapshot["prepared_breakout_penalty_relief"]),
        prepared_breakout_catalyst_relief=dict(snapshot["prepared_breakout_catalyst_relief"]),
        prepared_breakout_volume_relief=dict(snapshot["prepared_breakout_volume_relief"]),
        prepared_breakout_continuation_relief=dict(snapshot["prepared_breakout_continuation_relief"]),
        prepared_breakout_selected_catalyst_relief=dict(snapshot["prepared_breakout_selected_catalyst_relief"]),
        watchlist_zero_catalyst_guard=dict(snapshot["watchlist_zero_catalyst_guard"]),
        watchlist_zero_catalyst_crowded_guard=dict(snapshot["watchlist_zero_catalyst_crowded_guard"]),
        watchlist_zero_catalyst_flat_trend_guard=dict(snapshot["watchlist_zero_catalyst_flat_trend_guard"]),
        t_plus_2_continuation_candidate=dict(snapshot["t_plus_2_continuation_candidate"]),
    )


def _build_short_trade_verdict_reasons(
    *,
    snapshot: dict[str, Any],
    context: ShortTradeEvaluationContext,
    thresholds: ShortTradeThresholdState,
    decision: str,
    mutable_state: ShortTradeMutableVerdictState,
) -> tuple[list[str], list[str]]:
    top_reasons = _build_short_trade_top_reasons(
        state=_build_short_trade_top_reasons_state(
            snapshot=snapshot,
            context=context,
            thresholds=thresholds,
        )
    )
    rejection_reasons = _build_short_trade_rejection_reasons(
        decision=decision,
        blockers=mutable_state.blockers,
        breakout_freshness=thresholds.breakout_freshness,
        trend_acceleration=thresholds.trend_acceleration,
        effective_near_miss_threshold=thresholds.effective_near_miss_threshold,
        score_target=float(snapshot["score_target"]),
        near_miss_breakout_gate_pass=thresholds.near_miss_breakout_gate_pass,
        profile=snapshot["profile"],
        carryover_evidence_deficiency=context.carryover_evidence_deficiency,
    )
    return top_reasons, rejection_reasons


def _finalize_short_trade_verdict(
    *,
    snapshot: dict[str, Any],
    thresholds: ShortTradeThresholdState,
    quality_score: float,
    decision: str,
    mutable_state: ShortTradeMutableVerdictState,
    top_reasons: list[str],
    rejection_reasons: list[str],
) -> ShortTradeVerdict:
    confidence = derive_confidence(
        float(snapshot["score_target"]),
        thresholds.breakout_freshness,
        thresholds.trend_acceleration,
        float(snapshot["catalyst_freshness"]),
        quality_score,
    )
    return ShortTradeVerdict(
        decision=decision,
        confidence=confidence,
        positive_tags=mutable_state.positive_tags,
        negative_tags=trim_reasons(mutable_state.negative_tags),
        blockers=trim_reasons(mutable_state.blockers),
        gate_status=mutable_state.gate_status,
        top_reasons=top_reasons,
        rejection_reasons=rejection_reasons,
    )


def resolve_short_trade_verdict(
    context: ShortTradeEvaluationContext,
    *,
    thresholds: ShortTradeThresholdState,
    quality_score: float,
) -> ShortTradeVerdict:
    snapshot = context.snapshot
    mutable_state = _build_short_trade_mutable_verdict_state(snapshot)

    decision = _resolve_short_trade_decision(
        blockers=mutable_state.blockers,
        gate_status=mutable_state.gate_status,
        score_target=float(snapshot["score_target"]),
        effective_near_miss_threshold=thresholds.effective_near_miss_threshold,
        effective_select_threshold=thresholds.effective_select_threshold,
        selected_score_tolerance=thresholds.selected_score_tolerance,
        selected_breakout_gate_pass=thresholds.selected_breakout_gate_pass,
        near_miss_breakout_gate_pass=thresholds.near_miss_breakout_gate_pass,
        carryover_evidence_deficiency=context.carryover_evidence_deficiency,
        selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
    )
    _annotate_short_trade_tags(
        positive_tags=mutable_state.positive_tags,
        negative_tags=mutable_state.negative_tags,
        breakout_stage=thresholds.breakout_stage,
        carryover_evidence_deficiency=context.carryover_evidence_deficiency,
        selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
    )
    top_reasons, rejection_reasons = _build_short_trade_verdict_reasons(
        snapshot=snapshot,
        context=context,
        thresholds=thresholds,
        decision=decision,
        mutable_state=mutable_state,
    )
    return _finalize_short_trade_verdict(
        snapshot=snapshot,
        thresholds=thresholds,
        quality_score=quality_score,
        decision=decision,
        mutable_state=mutable_state,
        top_reasons=top_reasons,
        rejection_reasons=rejection_reasons,
    )


def build_short_trade_metrics_payload(
    *,
    context: ShortTradeEvaluationContext,
    thresholds: ShortTradeThresholdState,
    input_data: TargetEvaluationInput,
) -> dict[str, Any]:
    snapshot = context.snapshot
    positive_score_weights = dict(snapshot["positive_score_weights"])
    return {
        **_build_short_trade_core_metrics_payload(
            input_data=input_data,
            snapshot=snapshot,
            positive_score_weights=positive_score_weights,
            breakout_freshness=thresholds.breakout_freshness,
            trend_acceleration=thresholds.trend_acceleration,
            breakout_stage=thresholds.breakout_stage,
            selected_breakout_gate_pass=thresholds.selected_breakout_gate_pass,
            near_miss_breakout_gate_pass=thresholds.near_miss_breakout_gate_pass,
        ),
        **_build_short_trade_context_metrics_payload(
            carryover_evidence_deficiency=context.carryover_evidence_deficiency,
            selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
        ),
        "thresholds": {
            "profile_name": snapshot["profile"].name,
            "effective_select_threshold": round(thresholds.effective_select_threshold, 4),
            "selected_score_tolerance": round(thresholds.selected_score_tolerance, 4),
            "near_miss_threshold": round(thresholds.effective_near_miss_threshold, 4),
        },
    }


def build_short_trade_explainability_payload(
    *,
    context: ShortTradeEvaluationContext,
    thresholds: ShortTradeThresholdState,
    input_data: TargetEvaluationInput,
) -> dict[str, Any]:
    snapshot = context.snapshot
    return {
        "source": str(input_data.replay_context.get("source") or "short_trade_target_rules_v1"),
        "target_profile": snapshot["profile"].name,
        "breakout_stage": thresholds.breakout_stage,
        "trade_date": input_data.trade_date,
        "layer_c_decision": input_data.layer_c_decision,
        "bc_conflict": input_data.bc_conflict,
        "candidate_source": str(input_data.replay_context.get("source") or ""),
        "available_strategy_signals": sorted(str(name) for name in dict(input_data.strategy_signals or {}).keys()),
        "historical_prior": dict(snapshot["historical_prior"]),
        "carryover_evidence_deficiency": dict(context.carryover_evidence_deficiency),
        "selected_historical_proof_deficiency": dict(context.selected_historical_proof_deficiency),
        "replay_context": dict(input_data.replay_context or {}),
    }


def _build_short_trade_decision_snapshot_state(snapshot: dict[str, Any]) -> ShortTradeDecisionSnapshotState:
    return ShortTradeDecisionSnapshotState(
        profile=snapshot["profile"],
        breakout_freshness=float(snapshot["breakout_freshness"]),
        trend_acceleration=float(snapshot["trend_acceleration"]),
        raw_catalyst_freshness=float(snapshot["raw_catalyst_freshness"]),
        catalyst_freshness=float(snapshot["catalyst_freshness"]),
        score_target=float(snapshot["score_target"]),
        effective_near_miss_threshold=float(snapshot["effective_near_miss_threshold"]),
        effective_select_threshold=float(snapshot["effective_select_threshold"]),
        selected_score_tolerance=float(snapshot["selected_score_tolerance"]),
        positive_tags=list(snapshot["positive_tags"]),
        negative_tags=list(snapshot["negative_tags"]),
        blockers=list(snapshot["blockers"]),
        gate_status=dict(snapshot["gate_status"]),
    )


def _build_short_trade_context_and_thresholds(
    *,
    input_data: TargetEvaluationInput,
    snapshot: dict[str, Any],
    decision_snapshot: ShortTradeDecisionSnapshotState,
    resolve_carryover_evidence_deficiency: Any,
    resolve_selected_historical_proof_deficiency: Any,
    classify_breakout_stage: Any,
) -> tuple[ShortTradeEvaluationContext, ShortTradeThresholdState]:
    carryover_evidence_deficiency = resolve_carryover_evidence_deficiency(input_data)
    selected_historical_proof_deficiency = resolve_selected_historical_proof_deficiency(input_data)
    context = build_short_trade_evaluation_context(
        snapshot=snapshot,
        carryover_evidence_deficiency=carryover_evidence_deficiency,
        selected_historical_proof_deficiency=selected_historical_proof_deficiency,
    )
    breakout_stage, selected_breakout_gate_pass, near_miss_breakout_gate_pass = classify_breakout_stage(
        breakout_freshness=decision_snapshot.breakout_freshness,
        trend_acceleration=decision_snapshot.trend_acceleration,
        profile=decision_snapshot.profile,
    )
    thresholds = ShortTradeThresholdState(
        breakout_freshness=decision_snapshot.breakout_freshness,
        trend_acceleration=decision_snapshot.trend_acceleration,
        effective_near_miss_threshold=decision_snapshot.effective_near_miss_threshold,
        effective_select_threshold=decision_snapshot.effective_select_threshold,
        selected_score_tolerance=decision_snapshot.selected_score_tolerance,
        breakout_stage=breakout_stage,
        selected_breakout_gate_pass=selected_breakout_gate_pass,
        near_miss_breakout_gate_pass=near_miss_breakout_gate_pass,
    )
    return context, thresholds


def _build_short_trade_decision_reasoning(
    *,
    snapshot: dict[str, Any],
    decision_snapshot: ShortTradeDecisionSnapshotState,
    context: ShortTradeEvaluationContext,
    thresholds: ShortTradeThresholdState,
    decision: str,
    build_short_trade_top_reasons: Any,
    build_short_trade_rejection_reasons: Any,
) -> tuple[list[str], list[str]]:
    top_reasons = build_short_trade_top_reasons(
        breakout_freshness=decision_snapshot.breakout_freshness,
        trend_acceleration=decision_snapshot.trend_acceleration,
        raw_catalyst_freshness=decision_snapshot.raw_catalyst_freshness,
        upstream_shadow_catalyst_relief_applied=bool(snapshot["upstream_shadow_catalyst_relief_applied"]),
        upstream_shadow_catalyst_relief_reason=str(snapshot["upstream_shadow_catalyst_relief_reason"]),
        visibility_gap_continuation_relief=dict(snapshot["visibility_gap_continuation_relief"]),
        merge_approved_continuation_relief=dict(snapshot["merge_approved_continuation_relief"]),
        prepared_breakout_penalty_relief=dict(snapshot["prepared_breakout_penalty_relief"]),
        prepared_breakout_catalyst_relief=dict(snapshot["prepared_breakout_catalyst_relief"]),
        prepared_breakout_volume_relief=dict(snapshot["prepared_breakout_volume_relief"]),
        prepared_breakout_continuation_relief=dict(snapshot["prepared_breakout_continuation_relief"]),
        prepared_breakout_selected_catalyst_relief=dict(snapshot["prepared_breakout_selected_catalyst_relief"]),
        profitability_relief_applied=bool(snapshot["profitability_relief_applied"]),
        profitability_hard_cliff_boundary_relief=dict(snapshot["profitability_hard_cliff_boundary_relief"]),
        historical_execution_relief=dict(snapshot["historical_execution_relief"]),
        profitability_hard_cliff=bool(snapshot["profitability_hard_cliff"]),
        breakout_stage=thresholds.breakout_stage,
        layer_c_avoid_penalty=float(snapshot["layer_c_avoid_penalty"]),
        stale_trend_repair_penalty=float(snapshot["stale_trend_repair_penalty"]),
        overhead_supply_penalty=float(snapshot["overhead_supply_penalty"]),
        extension_without_room_penalty=float(snapshot["extension_without_room_penalty"]),
        watchlist_zero_catalyst_guard=dict(snapshot["watchlist_zero_catalyst_guard"]),
        watchlist_zero_catalyst_crowded_guard=dict(snapshot["watchlist_zero_catalyst_crowded_guard"]),
        watchlist_zero_catalyst_flat_trend_guard=dict(snapshot["watchlist_zero_catalyst_flat_trend_guard"]),
        carryover_evidence_deficiency=context.carryover_evidence_deficiency,
        selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
        t_plus_2_continuation_candidate=dict(snapshot["t_plus_2_continuation_candidate"]),
        score_target=decision_snapshot.score_target,
    )
    rejection_reasons = build_short_trade_rejection_reasons(
        decision=decision,
        blockers=decision_snapshot.blockers,
        breakout_freshness=decision_snapshot.breakout_freshness,
        trend_acceleration=decision_snapshot.trend_acceleration,
        effective_near_miss_threshold=decision_snapshot.effective_near_miss_threshold,
        score_target=decision_snapshot.score_target,
        near_miss_breakout_gate_pass=thresholds.near_miss_breakout_gate_pass,
        profile=decision_snapshot.profile,
        carryover_evidence_deficiency=context.carryover_evidence_deficiency,
    )
    return top_reasons, rejection_reasons


def _build_short_trade_verdict(
    *,
    input_data: TargetEvaluationInput,
    decision_snapshot: ShortTradeDecisionSnapshotState,
    decision: str,
    top_reasons: list[str],
    rejection_reasons: list[str],
) -> ShortTradeVerdict:
    confidence = derive_confidence(
        decision_snapshot.score_target,
        decision_snapshot.breakout_freshness,
        decision_snapshot.trend_acceleration,
        decision_snapshot.catalyst_freshness,
        float(input_data.quality_score or 0.0),
    )
    return ShortTradeVerdict(
        decision=decision,
        confidence=confidence,
        positive_tags=decision_snapshot.positive_tags,
        negative_tags=trim_reasons(decision_snapshot.negative_tags),
        blockers=trim_reasons(decision_snapshot.blockers),
        gate_status=decision_snapshot.gate_status,
        top_reasons=top_reasons,
        rejection_reasons=rejection_reasons,
    )


def _build_short_trade_decision_stage(
    *,
    input_data: TargetEvaluationInput,
    snapshot: dict[str, Any],
    resolve_carryover_evidence_deficiency: Any,
    resolve_selected_historical_proof_deficiency: Any,
    classify_breakout_stage: Any,
    resolve_short_trade_decision: Any,
    annotate_short_trade_tags: Any,
    build_short_trade_top_reasons: Any,
    build_short_trade_rejection_reasons: Any,
) -> tuple[ShortTradeEvaluationContext, ShortTradeThresholdState, ShortTradeVerdict]:
    decision_snapshot = _build_short_trade_decision_snapshot_state(snapshot)
    context, thresholds = _build_short_trade_context_and_thresholds(
        input_data=input_data,
        snapshot=snapshot,
        decision_snapshot=decision_snapshot,
        resolve_carryover_evidence_deficiency=resolve_carryover_evidence_deficiency,
        resolve_selected_historical_proof_deficiency=resolve_selected_historical_proof_deficiency,
        classify_breakout_stage=classify_breakout_stage,
    )
    decision = resolve_short_trade_decision(
        blockers=decision_snapshot.blockers,
        gate_status=decision_snapshot.gate_status,
        score_target=decision_snapshot.score_target,
        effective_near_miss_threshold=decision_snapshot.effective_near_miss_threshold,
        effective_select_threshold=decision_snapshot.effective_select_threshold,
        selected_score_tolerance=decision_snapshot.selected_score_tolerance,
        selected_breakout_gate_pass=thresholds.selected_breakout_gate_pass,
        near_miss_breakout_gate_pass=thresholds.near_miss_breakout_gate_pass,
        carryover_evidence_deficiency=context.carryover_evidence_deficiency,
        selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
    )
    annotate_short_trade_tags(
        positive_tags=decision_snapshot.positive_tags,
        negative_tags=decision_snapshot.negative_tags,
        breakout_stage=thresholds.breakout_stage,
        carryover_evidence_deficiency=context.carryover_evidence_deficiency,
        selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
    )
    top_reasons, rejection_reasons = _build_short_trade_decision_reasoning(
        snapshot=snapshot,
        decision_snapshot=decision_snapshot,
        context=context,
        thresholds=thresholds,
        decision=decision,
        build_short_trade_top_reasons=build_short_trade_top_reasons,
        build_short_trade_rejection_reasons=build_short_trade_rejection_reasons,
    )
    verdict = _build_short_trade_verdict(
        input_data=input_data,
        decision_snapshot=decision_snapshot,
        decision=decision,
        top_reasons=top_reasons,
        rejection_reasons=rejection_reasons,
    )
    return context, thresholds, verdict


def evaluate_short_trade_target_impl(
    input_data: TargetEvaluationInput,
    *,
    rank_hint: int | None = None,
    build_short_trade_target_snapshot: Any,
    resolve_carryover_evidence_deficiency: Any,
    resolve_selected_historical_proof_deficiency: Any,
    classify_breakout_stage: Any,
    resolve_short_trade_decision: Any,
    annotate_short_trade_tags: Any,
    build_short_trade_top_reasons: Any,
    build_short_trade_rejection_reasons: Any,
    preferred_entry_mode_from_historical_prior: Any,
) -> TargetEvaluationResult:
    snapshot = build_short_trade_target_snapshot(input_data)
    context, thresholds, verdict = _build_short_trade_decision_stage(
        input_data=input_data,
        snapshot=snapshot,
        resolve_carryover_evidence_deficiency=resolve_carryover_evidence_deficiency,
        resolve_selected_historical_proof_deficiency=resolve_selected_historical_proof_deficiency,
        classify_breakout_stage=classify_breakout_stage,
        resolve_short_trade_decision=resolve_short_trade_decision,
        annotate_short_trade_tags=annotate_short_trade_tags,
        build_short_trade_top_reasons=build_short_trade_top_reasons,
        build_short_trade_rejection_reasons=build_short_trade_rejection_reasons,
    )
    return build_short_trade_target_result(
        context=context,
        thresholds=thresholds,
        verdict=verdict,
        input_data=input_data,
        rank_hint=rank_hint,
        preferred_entry_mode_from_historical_prior=preferred_entry_mode_from_historical_prior,
    )



def build_short_trade_target_result(
    *,
    context: ShortTradeEvaluationContext,
    thresholds: ShortTradeThresholdState,
    verdict: ShortTradeVerdict,
    input_data: TargetEvaluationInput,
    rank_hint: int | None,
    preferred_entry_mode_from_historical_prior: Any = _preferred_entry_mode_from_historical_prior,
) -> TargetEvaluationResult:
    snapshot = context.snapshot
    return TargetEvaluationResult(
        target_type="short_trade",
        decision=verdict.decision,
        score_target=float(snapshot["score_target"]),
        confidence=verdict.confidence,
        rank_hint=rank_hint,
        positive_tags=verdict.positive_tags,
        negative_tags=verdict.negative_tags,
        blockers=verdict.blockers,
        top_reasons=verdict.top_reasons,
        rejection_reasons=verdict.rejection_reasons,
        gate_status=verdict.gate_status,
        expected_holding_window="t1_short_trade",
        preferred_entry_mode=preferred_entry_mode_from_historical_prior(dict(snapshot["historical_prior"])),
        candidate_source=str(input_data.replay_context.get("source") or "") or None,
        effective_near_miss_threshold=round(thresholds.effective_near_miss_threshold, 4),
        effective_select_threshold=round(thresholds.effective_select_threshold, 4),
        breakout_freshness=round(thresholds.breakout_freshness, 4),
        trend_acceleration=round(thresholds.trend_acceleration, 4),
        volume_expansion_quality=round(float(snapshot["volume_expansion_quality"]), 4),
        close_strength=round(float(snapshot["close_strength"]), 4),
        sector_resonance=round(float(snapshot["sector_resonance"]), 4),
        catalyst_freshness=round(float(snapshot["raw_catalyst_freshness"]), 4),
        layer_c_alignment=round(float(snapshot["layer_c_alignment"]), 4),
        weighted_positive_contributions={name: round(float(value), 4) for name, value in dict(snapshot["weighted_positive_contributions"]).items()},
        weighted_negative_contributions={name: round(float(value), 4) for name, value in dict(snapshot["weighted_negative_contributions"]).items()},
        metrics_payload=_build_short_trade_metrics_payload(
            input_data=input_data,
            profile=snapshot["profile"],
            snapshot=snapshot,
            breakout_stage=thresholds.breakout_stage,
            selected_breakout_gate_pass=thresholds.selected_breakout_gate_pass,
            near_miss_breakout_gate_pass=thresholds.near_miss_breakout_gate_pass,
            carryover_evidence_deficiency=context.carryover_evidence_deficiency,
            selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
        ),
        explainability_payload=_build_short_trade_explainability_payload(
            input_data=input_data,
            snapshot=snapshot,
            breakout_stage=thresholds.breakout_stage,
            state=_build_short_trade_explainability_state(snapshot),
            carryover_evidence_deficiency=context.carryover_evidence_deficiency,
            selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
        ),
    )
