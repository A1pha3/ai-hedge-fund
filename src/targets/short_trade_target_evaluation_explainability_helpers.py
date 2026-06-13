"""Explainability payload builders for the short trade target evaluation pipeline.

Extracted from :mod:`src.targets.short_trade_target_evaluation_helpers` during the
R20.16 refactor. Contains all ``_build_*_explainability_payload`` functions,
the committee payload builder, and the state builders for mutable verdict,
top reasons, and explainability state objects.
"""

from __future__ import annotations

from typing import Any

from src.targets.models import TargetEvaluationInput
from src.targets.short_trade_metrics_payload_builders import (
    _build_breakout_trap_guard_metrics_payload,
    _build_carryover_evidence_deficiency_metrics_payload,
    _build_historical_execution_relief_metrics_payload,
    _build_market_state_threshold_adjustment_metrics_payload,
    _build_merge_approved_continuation_relief_metrics_payload,
    _build_prepared_breakout_continuation_relief_metrics_payload,
    _build_prepared_breakout_selected_catalyst_relief_metrics_payload,
    _build_prepared_breakout_volume_relief_metrics_payload,
    _build_profitability_explainability_payload,
    _build_profitability_hard_cliff_boundary_relief_metrics_payload,
    _build_selected_historical_proof_deficiency_metrics_payload,
    _build_t_plus_2_continuation_candidate_metrics_payload,
    _build_visibility_gap_continuation_relief_metrics_payload,
    _build_watchlist_guard_metrics_payload,
)
from src.targets.short_trade_target_evaluation_models import (
    ShortTradeEvaluationContext,
    ShortTradeExplainabilityState,
    ShortTradeThresholdState,
    ShortTradeTopReasonsState,
)


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
        "candidate_reason_codes": list(snapshot.get("candidate_reason_codes") or []),
        "payoff_first_runner_recall_candidate": bool(snapshot.get("payoff_first_runner_recall_candidate")),
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
    watchlist_filter_diagnostics_selected_only_shrink_guard: dict[str, Any],
    layer_c_watchlist_selected_only_shrink_guard: dict[str, Any],
    short_trade_boundary_selected_only_shrink_guard: dict[str, Any],
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
        "watchlist_filter_diagnostics_selected_only_shrink_guard": _build_watchlist_guard_metrics_payload(
            watchlist_filter_diagnostics_selected_only_shrink_guard
        ),
        "layer_c_watchlist_selected_only_shrink_guard": _build_watchlist_guard_metrics_payload(
            layer_c_watchlist_selected_only_shrink_guard
        ),
        "short_trade_boundary_selected_only_shrink_guard": _build_watchlist_guard_metrics_payload(
            short_trade_boundary_selected_only_shrink_guard
        ),
        "t_plus_2_continuation_candidate": _build_t_plus_2_continuation_candidate_metrics_payload(t_plus_2_continuation_candidate),
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
            watchlist_filter_diagnostics_selected_only_shrink_guard=dict(snapshot["watchlist_filter_diagnostics_selected_only_shrink_guard"]),
            layer_c_watchlist_selected_only_shrink_guard=dict(snapshot["layer_c_watchlist_selected_only_shrink_guard"]),
            short_trade_boundary_selected_only_shrink_guard=dict(snapshot["short_trade_boundary_selected_only_shrink_guard"]),
            t_plus_2_continuation_candidate=state.t_plus_2_continuation_candidate,
        ),
        "committee": _build_short_trade_committee_payload(snapshot),
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


def _build_short_trade_committee_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(snapshot.get("committee_enabled", False)),
        "gate": str(snapshot.get("committee_gate") or ""),
        "effective_gate": str(snapshot.get("committee_effective_gate") or snapshot.get("committee_gate") or ""),
        "profile": str(snapshot.get("committee_profile") or ""),
        "alpha_edge_score": round(float(snapshot.get("alpha_edge_score", 0.0) or 0.0), 4),
        "beta_execution_score": round(float(snapshot.get("beta_execution_score", 0.0) or 0.0), 4),
        "gamma_risk_score": round(float(snapshot.get("gamma_risk_score", 0.0) or 0.0), 4),
        "committee_score": round(float(snapshot.get("committee_score", 0.0) or 0.0), 4),
        "thresholds": dict(snapshot.get("committee_thresholds") or {}),
        "gate_status": dict(snapshot.get("committee_gate_status") or {}),
        "fail_reasons": list(snapshot.get("committee_fail_reasons") or []),
        "advisory_reasons": list(snapshot.get("committee_advisory_reasons") or []),
        "vetoes": list(snapshot.get("committee_vetoes") or []),
        "selected_pass": bool(snapshot.get("committee_selected_pass", False)),
        "components": dict(snapshot.get("committee_components") or {}),
        "component_sources": dict(snapshot.get("committee_component_sources") or {}),
        "kill_switch": dict(snapshot.get("committee_kill_switch") or {}),
    }


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
        watchlist_filter_diagnostics_selected_only_shrink_guard=dict(snapshot["watchlist_filter_diagnostics_selected_only_shrink_guard"]),
        layer_c_watchlist_selected_only_shrink_guard=dict(snapshot["layer_c_watchlist_selected_only_shrink_guard"]),
        short_trade_boundary_selected_only_shrink_guard=dict(snapshot["short_trade_boundary_selected_only_shrink_guard"]),
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
        watchlist_filter_diagnostics_selected_only_shrink_guard=dict(snapshot["watchlist_filter_diagnostics_selected_only_shrink_guard"]),
        layer_c_watchlist_selected_only_shrink_guard=dict(snapshot["layer_c_watchlist_selected_only_shrink_guard"]),
        short_trade_boundary_selected_only_shrink_guard=dict(snapshot["short_trade_boundary_selected_only_shrink_guard"]),
        t_plus_2_continuation_candidate=dict(snapshot["t_plus_2_continuation_candidate"]),
    )


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
