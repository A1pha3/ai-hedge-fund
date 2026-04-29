from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.targets.explainability import (
    clamp_unit_interval,
    derive_confidence,
    trim_reasons,
)
from src.targets.models import TargetEvaluationInput, TargetEvaluationResult
from src.targets.short_trade_metrics_payload_builders import (  # noqa: F401
    _build_breakout_trap_guard_metrics_payload,
    _build_carryover_evidence_deficiency_metrics_payload,
    _build_historical_execution_relief_metrics_payload,
    _build_market_state_threshold_adjustment_metrics_payload,
    _build_merge_approved_continuation_relief_metrics_payload,
    _build_prepared_breakout_catalyst_relief_metrics_payload,
    _build_prepared_breakout_catalyst_threshold_metrics_payload,
    _build_prepared_breakout_continuation_relief_metrics_payload,
    _build_prepared_breakout_continuation_threshold_metrics_payload,
    _build_prepared_breakout_metrics_payload,
    _build_prepared_breakout_penalty_relief_metrics_payload,
    _build_prepared_breakout_penalty_threshold_metrics_payload,
    _build_prepared_breakout_selected_catalyst_relief_metrics_payload,
    _build_prepared_breakout_selected_catalyst_threshold_metrics_payload,
    _build_prepared_breakout_volume_relief_metrics_payload,
    _build_prepared_breakout_volume_threshold_metrics_payload,
    _build_profitability_explainability_payload,
    _build_profitability_hard_cliff_boundary_relief_metrics_payload,
    _build_profitability_metrics_payload,
    _build_selected_historical_proof_deficiency_metrics_payload,
    _build_short_trade_context_metrics_payload,
    _build_short_trade_core_metrics_payload,
    _build_short_trade_penalty_metrics_payload,
    _build_short_trade_penalty_threshold_metrics_payload,
    _build_short_trade_relief_metrics_payload,
    _build_short_trade_threshold_core_metrics_payload,
    _build_short_trade_threshold_metrics_payload,
    _build_short_trade_threshold_profitability_metrics_payload,
    _build_t_plus_2_and_merge_threshold_metrics_payload,
    _build_t_plus_2_continuation_candidate_metrics_payload,
    _build_upstream_shadow_and_visibility_threshold_metrics_payload,
    _build_upstream_shadow_metrics_payload,
    _build_visibility_gap_continuation_relief_metrics_payload,
    _build_watchlist_guard_metrics_payload,
    _build_watchlist_metrics_payload,
    _build_watchlist_threshold_metrics_payload,
    _collect_short_trade_metrics_payload_inputs,
)
from src.targets.short_trade_target_prior_helpers import (
    calibrate_short_trade_historical_prior,
    resolve_btst_prior_shrinkage_p4_mode,
    resolve_effective_prior_metrics,
)
from src.targets.short_trade_target_rank_helpers import (
    _apply_rank_based_decision_cap,
    _apply_rank_based_threshold_tightening,
)


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
    event_catalyst_assessment: dict[str, Any]
    profitability_hard_cliff: bool
    breakout_stage: str
    layer_c_avoid_penalty: float
    stale_trend_repair_penalty: float
    overhead_supply_penalty: float
    extension_without_room_penalty: float
    breakout_trap_guard: dict[str, Any]
    market_state_threshold_adjustment: dict[str, Any]
    catalyst_theme_guard: dict[str, Any]
    watchlist_zero_catalyst_guard: dict[str, Any]
    watchlist_zero_catalyst_crowded_guard: dict[str, Any]
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any]
    watchlist_filter_diagnostics_flat_trend_guard: dict[str, Any]
    carryover_evidence_deficiency: dict[str, Any]
    selected_historical_proof_deficiency: dict[str, Any]
    t_plus_2_continuation_candidate: dict[str, Any]
    score_target: float


@dataclass(frozen=True)
class ShortTradeExplainabilityState:
    profile: Any
    market_state_threshold_adjustment: dict[str, Any]
    breakout_trap_guard: dict[str, Any]
    profitability_hard_cliff_boundary_relief: dict[str, Any]
    historical_execution_relief: dict[str, Any]
    visibility_gap_continuation_relief: dict[str, Any]
    merge_approved_continuation_relief: dict[str, Any]
    prepared_breakout_penalty_relief: dict[str, Any]
    prepared_breakout_catalyst_relief: dict[str, Any]
    prepared_breakout_volume_relief: dict[str, Any]
    prepared_breakout_continuation_relief: dict[str, Any]
    prepared_breakout_selected_catalyst_relief: dict[str, Any]
    catalyst_theme_guard: dict[str, Any]
    watchlist_zero_catalyst_guard: dict[str, Any]
    watchlist_zero_catalyst_crowded_guard: dict[str, Any]
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any]
    watchlist_filter_diagnostics_flat_trend_guard: dict[str, Any]
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
    prior = dict(historical_prior or {})
    has_calibrated_prior = any(
        key in prior
        for key in (
            "calibrated_next_close_positive_rate",
            "prior_evidence_weight",
        )
    )
    evaluable_count = int(prior.get("evaluable_count") or 0)
    prior_strength = float(prior.get("prior_shrinkage_strength", 3.0) or 3.0)
    execution_quality_label = str(prior.get("execution_quality_label") or "unknown")
    if resolve_btst_prior_shrinkage_p4_mode() == "enforce":
        effective_metrics = resolve_effective_prior_metrics(prior)
        calibrated_next_close_positive_rate = clamp_unit_interval(float(effective_metrics.get("next_close_positive_rate", 0.0) or 0.0))
        evidence_weight = clamp_unit_interval(float(effective_metrics.get("reliability", 0.0) or 0.0))
    else:
        calibrated_next_close_positive_rate = clamp_unit_interval(float(prior.get("calibrated_next_close_positive_rate", prior.get("next_close_positive_rate", 0.0)) or 0.0))
        evidence_weight = clamp_unit_interval(
            float(
                prior.get(
                    "prior_evidence_weight",
                    (float(evaluable_count) / (float(evaluable_count) + prior_strength)) if (float(evaluable_count) + prior_strength) > 0 else 0.0,
                )
                or 0.0
            )
        )
    if execution_quality_label == "intraday_only":
        return "intraday_confirmation_only"
    if execution_quality_label == "gap_chase_risk":
        return "avoid_open_chase_confirmation"
    if execution_quality_label == "close_continuation":
        if has_calibrated_prior and (evidence_weight < 0.4 or calibrated_next_close_positive_rate < 0.60):
            return "next_day_breakout_confirmation"
        return "confirm_then_hold_breakout"
    if execution_quality_label == "zero_follow_through":
        return "strong_reconfirmation_only"
    return "next_day_breakout_confirmation"


def _determine_initial_decision(
    *,
    blockers: list[str],
    gate_status: dict[str, Any],
    score_target: float,
    effective_near_miss_threshold: float,
    effective_select_threshold: float,
    selected_score_tolerance: float,
    selected_breakout_gate_pass: bool,
    near_miss_breakout_gate_pass: bool,
) -> str:
    selected_score_pass = score_target >= (effective_select_threshold - selected_score_tolerance)
    hard_block = gate_status["data"] == "fail" or gate_status.get("execution") == "fail" or "layer_c_bearish_conflict" in blockers or "trend_not_constructive" in blockers

    if blockers:
        return "blocked" if hard_block else "rejected"
    if selected_score_pass and selected_breakout_gate_pass:
        gate_status["score"] = "pass"
        return "selected"
    if selected_score_pass and near_miss_breakout_gate_pass:
        gate_status["score"] = "near_miss"
        return "near_miss"
    if score_target >= effective_near_miss_threshold and near_miss_breakout_gate_pass:
        gate_status["score"] = "near_miss"
        return "near_miss"
    return "rejected"


def _enforce_rank_cap(
    *,
    decision: str,
    blockers: list[str],
    gate_status: dict[str, Any],
    score_target: float,
    effective_near_miss_threshold: float,
    near_miss_breakout_gate_pass: bool,
    rank_decision_cap: dict[str, Any],
) -> str | None:
    selected_cap_exceeded = bool(rank_decision_cap.get("selected_cap_exceeded_effective", rank_decision_cap.get("selected_cap_exceeded")))
    near_miss_cap_exceeded = bool(rank_decision_cap.get("near_miss_cap_exceeded"))

    if decision == "selected" and rank_decision_cap.get("selected_cap_soft_relief_applied"):
        gate_status["rank"] = "selected_cap_soft_relief"
    if decision == "selected" and selected_cap_exceeded:
        gate_status["rank"] = "selected_cap_exceeded"
        if score_target >= effective_near_miss_threshold and near_miss_breakout_gate_pass and not near_miss_cap_exceeded:
            gate_status["score"] = "near_miss"
            return "near_miss"
        gate_status["score"] = "fail"
        if "selected_rank_cap_exceeded" not in blockers:
            blockers.append("selected_rank_cap_exceeded")
        return "rejected"
    if decision == "near_miss" and near_miss_cap_exceeded:
        gate_status["rank"] = "near_miss_cap_exceeded"
        gate_status["score"] = "fail"
        if "near_miss_rank_cap_exceeded" not in blockers:
            blockers.append("near_miss_rank_cap_exceeded")
        return "rejected"
    return None


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
    rank_decision_cap: dict[str, Any],
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
) -> str:
    decision = _determine_initial_decision(
        blockers=blockers,
        gate_status=gate_status,
        score_target=score_target,
        effective_near_miss_threshold=effective_near_miss_threshold,
        effective_select_threshold=effective_select_threshold,
        selected_score_tolerance=selected_score_tolerance,
        selected_breakout_gate_pass=selected_breakout_gate_pass,
        near_miss_breakout_gate_pass=near_miss_breakout_gate_pass,
    )

    cap_override = _enforce_rank_cap(
        decision=decision,
        blockers=blockers,
        gate_status=gate_status,
        score_target=score_target,
        effective_near_miss_threshold=effective_near_miss_threshold,
        near_miss_breakout_gate_pass=near_miss_breakout_gate_pass,
        rank_decision_cap=rank_decision_cap,
    )
    if cap_override is not None:
        return cap_override

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
    event_catalyst_assessment: dict[str, Any],
) -> list[str | None]:
    event_catalyst_applied = event_catalyst_assessment.get("selected_uplift", 0.0) > 0.0 or event_catalyst_assessment.get("near_miss_threshold_relief", 0.0) > 0.0
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
        "event_catalyst_relief" if event_catalyst_applied else None,
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
    breakout_trap_guard: dict[str, Any],
    market_state_threshold_adjustment: dict[str, Any],
    catalyst_theme_guard: dict[str, Any],
    watchlist_zero_catalyst_guard: dict[str, Any],
    watchlist_zero_catalyst_crowded_guard: dict[str, Any],
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any],
    watchlist_filter_diagnostics_flat_trend_guard: dict[str, Any],
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
    t_plus_2_continuation_candidate: dict[str, Any],
    score_target: float,
) -> list[str | None]:
    market_risk_level = str(market_state_threshold_adjustment.get("risk_level") or "unknown").strip().lower()
    regime_gate_level = str(market_state_threshold_adjustment.get("regime_gate_level") or market_risk_level or "unknown").strip().lower()
    return [
        "profitability_hard_cliff" if profitability_hard_cliff and not profitability_relief_applied else None,
        breakout_stage,
        _summarize_penalty("layer_c_avoid_penalty", layer_c_avoid_penalty),
        _summarize_penalty("stale_trend_repair_penalty", stale_trend_repair_penalty),
        _summarize_penalty("overhead_supply_penalty", overhead_supply_penalty),
        _summarize_penalty("extension_without_room_penalty", extension_without_room_penalty),
        "breakout_trap_penalty_applied" if breakout_trap_guard["applied"] else None,
        "breakout_trap_risk_high" if breakout_trap_guard["blocked"] or breakout_trap_guard["execution_blocked"] else None,
        f"market_risk_{market_risk_level}" if market_risk_level in {"risk_off", "crisis"} else None,
        f"regime_gate_{regime_gate_level}" if regime_gate_level in {"risk_off", "crisis"} else None,
        "catalyst_theme_penalty_applied" if catalyst_theme_guard["applied"] else None,
        "watchlist_zero_catalyst_penalty_applied" if watchlist_zero_catalyst_guard["applied"] else None,
        "watchlist_zero_catalyst_crowded_penalty_applied" if watchlist_zero_catalyst_crowded_guard["applied"] else None,
        "watchlist_zero_catalyst_flat_trend_penalty_applied" if watchlist_zero_catalyst_flat_trend_guard["applied"] else None,
        "watchlist_filter_diagnostics_flat_trend_penalty_applied" if watchlist_filter_diagnostics_flat_trend_guard["applied"] else None,
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
            event_catalyst_assessment=state.event_catalyst_assessment,
        ),
        *_collect_short_trade_penalty_reasons(
            profitability_hard_cliff=state.profitability_hard_cliff,
            profitability_relief_applied=state.profitability_relief_applied,
            breakout_stage=state.breakout_stage,
            layer_c_avoid_penalty=state.layer_c_avoid_penalty,
            stale_trend_repair_penalty=state.stale_trend_repair_penalty,
            overhead_supply_penalty=state.overhead_supply_penalty,
            extension_without_room_penalty=state.extension_without_room_penalty,
            breakout_trap_guard=state.breakout_trap_guard,
            market_state_threshold_adjustment=state.market_state_threshold_adjustment,
            catalyst_theme_guard=state.catalyst_theme_guard,
            watchlist_zero_catalyst_guard=state.watchlist_zero_catalyst_guard,
            watchlist_zero_catalyst_crowded_guard=state.watchlist_zero_catalyst_crowded_guard,
            watchlist_zero_catalyst_flat_trend_guard=state.watchlist_zero_catalyst_flat_trend_guard,
            watchlist_filter_diagnostics_flat_trend_guard=state.watchlist_filter_diagnostics_flat_trend_guard,
            carryover_evidence_deficiency=state.carryover_evidence_deficiency,
            selected_historical_proof_deficiency=state.selected_historical_proof_deficiency,
            t_plus_2_continuation_candidate=state.t_plus_2_continuation_candidate,
            score_target=state.score_target,
        ),
    ]
    return trim_reasons([reason for reason in reasons if reason is not None])


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
        else (
            _collect_breakout_gate_misses(
                breakout_freshness=breakout_freshness,
                trend_acceleration=trend_acceleration,
                breakout_min=float(profile.near_miss_breakout_freshness_min),
                trend_min=float(profile.near_miss_trend_acceleration_min),
                label="near_miss",
            )
            if decision == "rejected" and score_target >= effective_near_miss_threshold and not near_miss_breakout_gate_pass
            else ["score_short_below_threshold"] if decision == "rejected" else []
        )
    )
    if decision == "rejected" and carryover_evidence_deficiency["evidence_deficient"]:
        return trim_reasons(["evidence_deficient_broad_family_only", *rejection_reasons])
    return rejection_reasons


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
        "available_strategy_signals": sorted(str(name) for name in dict(input_data.strategy_signals or {})),
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
    catalyst_theme_guard: dict[str, Any],
    watchlist_zero_catalyst_guard: dict[str, Any],
    watchlist_zero_catalyst_crowded_guard: dict[str, Any],
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any],
    watchlist_filter_diagnostics_flat_trend_guard: dict[str, Any],
    t_plus_2_continuation_candidate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "catalyst_theme_guard": _build_watchlist_guard_explainability_payload(
            catalyst_theme_guard,
            effective_penalty=float(snapshot["catalyst_theme_penalty"]),
        ),
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
        "watchlist_filter_diagnostics_flat_trend_guard": _build_watchlist_guard_explainability_payload(
            watchlist_filter_diagnostics_flat_trend_guard,
            effective_penalty=float(snapshot["watchlist_filter_diagnostics_flat_trend_penalty"]),
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
            catalyst_theme_guard=metrics_inputs["catalyst_theme_guard"],
            watchlist_zero_catalyst_guard=metrics_inputs["watchlist_zero_catalyst_guard"],
            watchlist_zero_catalyst_crowded_guard=metrics_inputs["watchlist_zero_catalyst_crowded_guard"],
            watchlist_zero_catalyst_flat_trend_guard=metrics_inputs["watchlist_zero_catalyst_flat_trend_guard"],
            watchlist_filter_diagnostics_flat_trend_guard=metrics_inputs["watchlist_filter_diagnostics_flat_trend_guard"],
        ),
        **_build_upstream_shadow_metrics_payload(snapshot),
        **_build_short_trade_relief_metrics_payload(metrics_inputs),
        **_build_short_trade_penalty_metrics_payload(
            snapshot=snapshot,
            breakout_trap_guard=metrics_inputs["breakout_trap_guard"],
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
    payload = {
        **_build_short_trade_core_explainability_payload(
            input_data=input_data,
            profile=state.profile,
            snapshot=snapshot,
            breakout_stage=breakout_stage,
        ),
        "market_state_threshold_adjustment": _build_market_state_threshold_adjustment_metrics_payload(state.market_state_threshold_adjustment),
        "breakout_trap_guard": _build_breakout_trap_guard_metrics_payload(state.breakout_trap_guard),
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
            catalyst_theme_guard=state.catalyst_theme_guard,
            watchlist_zero_catalyst_guard=state.watchlist_zero_catalyst_guard,
            watchlist_zero_catalyst_crowded_guard=state.watchlist_zero_catalyst_crowded_guard,
            watchlist_zero_catalyst_flat_trend_guard=state.watchlist_zero_catalyst_flat_trend_guard,
            watchlist_filter_diagnostics_flat_trend_guard=state.watchlist_filter_diagnostics_flat_trend_guard,
            t_plus_2_continuation_candidate=state.t_plus_2_continuation_candidate,
        ),
        "replay_context": dict(input_data.replay_context or {}),
    }
    
    # Only add event_catalyst explainability if it's meaningful (actually applied)
    event_catalyst_assessment = dict(snapshot.get("event_catalyst_assessment") or {})
    if event_catalyst_assessment and (event_catalyst_assessment.get("selected_uplift", 0.0) > 0 or event_catalyst_assessment.get("near_miss_threshold_relief", 0.0) > 0):
        payload["event_catalyst"] = {
            "score": round(event_catalyst_assessment["score"], 4),
            "eligible": event_catalyst_assessment["eligible"],
            "applied": True,
            "selected_uplift": round(event_catalyst_assessment["selected_uplift"], 4),
            "near_miss_threshold_relief": round(event_catalyst_assessment["near_miss_threshold_relief"], 4),
            "gate_hits": dict(event_catalyst_assessment["gate_hits"]),
            "component_scores": {k: round(v, 4) for k, v in event_catalyst_assessment["component_scores"].items()},
        }
    
    return payload


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
        event_catalyst_assessment=dict(snapshot.get("event_catalyst_assessment") or {}),
        profitability_hard_cliff=bool(snapshot["profitability_hard_cliff"]),
        breakout_stage=thresholds.breakout_stage,
        layer_c_avoid_penalty=float(snapshot["layer_c_avoid_penalty"]),
        stale_trend_repair_penalty=float(snapshot["stale_trend_repair_penalty"]),
        overhead_supply_penalty=float(snapshot["overhead_supply_penalty"]),
        extension_without_room_penalty=float(snapshot["extension_without_room_penalty"]),
        breakout_trap_guard=dict(snapshot.get("breakout_trap_guard") or {}),
        market_state_threshold_adjustment=dict(snapshot.get("market_state_threshold_adjustment") or {}),
        catalyst_theme_guard=dict(snapshot["catalyst_theme_guard"]),
        watchlist_zero_catalyst_guard=dict(snapshot["watchlist_zero_catalyst_guard"]),
        watchlist_zero_catalyst_crowded_guard=dict(snapshot["watchlist_zero_catalyst_crowded_guard"]),
        watchlist_zero_catalyst_flat_trend_guard=dict(snapshot["watchlist_zero_catalyst_flat_trend_guard"]),
        watchlist_filter_diagnostics_flat_trend_guard=dict(snapshot["watchlist_filter_diagnostics_flat_trend_guard"]),
        carryover_evidence_deficiency=context.carryover_evidence_deficiency,
        selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
        t_plus_2_continuation_candidate=dict(snapshot["t_plus_2_continuation_candidate"]),
        score_target=float(snapshot["score_target"]),
    )


def _build_short_trade_explainability_state(snapshot: dict[str, Any]) -> ShortTradeExplainabilityState:
    return ShortTradeExplainabilityState(
        profile=snapshot["profile"],
        market_state_threshold_adjustment=dict(snapshot.get("market_state_threshold_adjustment") or {}),
        breakout_trap_guard=dict(snapshot.get("breakout_trap_guard") or {}),
        profitability_hard_cliff_boundary_relief=dict(snapshot["profitability_hard_cliff_boundary_relief"]),
        historical_execution_relief=dict(snapshot["historical_execution_relief"]),
        visibility_gap_continuation_relief=dict(snapshot["visibility_gap_continuation_relief"]),
        merge_approved_continuation_relief=dict(snapshot["merge_approved_continuation_relief"]),
        prepared_breakout_penalty_relief=dict(snapshot["prepared_breakout_penalty_relief"]),
        prepared_breakout_catalyst_relief=dict(snapshot["prepared_breakout_catalyst_relief"]),
        prepared_breakout_volume_relief=dict(snapshot["prepared_breakout_volume_relief"]),
        prepared_breakout_continuation_relief=dict(snapshot["prepared_breakout_continuation_relief"]),
        prepared_breakout_selected_catalyst_relief=dict(snapshot["prepared_breakout_selected_catalyst_relief"]),
        catalyst_theme_guard=dict(snapshot["catalyst_theme_guard"]),
        watchlist_zero_catalyst_guard=dict(snapshot["watchlist_zero_catalyst_guard"]),
        watchlist_zero_catalyst_crowded_guard=dict(snapshot["watchlist_zero_catalyst_crowded_guard"]),
        watchlist_zero_catalyst_flat_trend_guard=dict(snapshot["watchlist_zero_catalyst_flat_trend_guard"]),
        watchlist_filter_diagnostics_flat_trend_guard=dict(snapshot["watchlist_filter_diagnostics_flat_trend_guard"]),
        t_plus_2_continuation_candidate=dict(snapshot["t_plus_2_continuation_candidate"]),
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
            "rank_threshold_tightening": dict(snapshot.get("rank_threshold_tightening") or {}),
            "rank_decision_cap": dict(snapshot.get("rank_decision_cap") or {}),
            "market_state_threshold_adjustment": dict(snapshot.get("market_state_threshold_adjustment") or {}),
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
        "available_strategy_signals": sorted(str(name) for name in dict(input_data.strategy_signals or {})),
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
        state=_build_short_trade_top_reasons_state(
            snapshot=snapshot,
            context=context,
            thresholds=thresholds,
        ),
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
    historical_prior = calibrate_short_trade_historical_prior(dict(input_data.replay_context.get("historical_prior") or {}))
    if resolve_btst_prior_shrinkage_p4_mode() == "enforce":
        effective_metrics = resolve_effective_prior_metrics(historical_prior)
        calibrated_next_close_positive_rate = clamp_unit_interval(float(effective_metrics.get("next_close_positive_rate", 0.0) or 0.0))
        calibrated_next_high_hit_rate = clamp_unit_interval(float(effective_metrics.get("next_high_hit_rate_at_threshold", 0.0) or 0.0))
        evidence_weight = clamp_unit_interval(float(effective_metrics.get("reliability", 0.0) or 0.0))
    else:
        calibrated_next_close_positive_rate = clamp_unit_interval(float(historical_prior.get("calibrated_next_close_positive_rate", historical_prior.get("next_close_positive_rate", 0.0)) or 0.0))
        calibrated_next_high_hit_rate = clamp_unit_interval(float(historical_prior.get("calibrated_next_high_hit_rate_at_threshold", historical_prior.get("next_high_hit_rate_at_threshold", 0.0)) or 0.0))
        evidence_weight = clamp_unit_interval(float(historical_prior.get("prior_evidence_weight", 0.0) or 0.0))
    structural_confidence = (0.30 * clamp_unit_interval(decision_snapshot.score_target)) + (0.20 * clamp_unit_interval(decision_snapshot.breakout_freshness)) + (0.18 * clamp_unit_interval(decision_snapshot.trend_acceleration)) + (0.12 * clamp_unit_interval(decision_snapshot.catalyst_freshness)) + (0.20 * clamp_unit_interval(float(input_data.quality_score or 0.0)))
    historical_confidence = (0.60 * calibrated_next_close_positive_rate) + (0.40 * calibrated_next_high_hit_rate)
    confidence = clamp_unit_interval((structural_confidence * (1.0 - (0.35 * evidence_weight))) + (historical_confidence * (0.35 * evidence_weight)))
    confidence = derive_confidence(confidence)
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
        rank_decision_cap=dict(snapshot.get("rank_decision_cap") or {}),
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
    rank_population: int | None = None,
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
    snapshot = _apply_rank_based_threshold_tightening(snapshot, rank_hint=rank_hint)
    snapshot = _apply_rank_based_decision_cap(
        snapshot,
        rank_hint=rank_hint,
        rank_population=rank_population,
        candidate_source=str(input_data.replay_context.get("source") or ""),
        candidate_reason_codes=list(input_data.replay_context.get("candidate_reason_codes") or []),
    )
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
        momentum_strength=round(float(snapshot.get("momentum_strength", 0.0)), 4),
        short_term_reversal=round(float(snapshot.get("short_term_reversal", 0.0)), 4),
        intraday_strength=round(float(snapshot.get("intraday_strength", 0.0)), 4),
        reversal_2d=round(float(snapshot.get("reversal_2d", 0.0)), 4),
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
