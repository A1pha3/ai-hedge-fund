"""Top-reasons and rejection-reasons builders for the short trade target evaluation pipeline.

Extracted from :mod:`src.targets.short_trade_target_evaluation_helpers` during the
R20.16 refactor. Contains ``_collect_*_reasons``, ``_build_short_trade_top_reasons``,
and ``_build_short_trade_rejection_reasons``.
"""

from __future__ import annotations

from typing import Any

from src.targets.explainability import trim_reasons
from src.targets.short_trade_target_evaluation_models import ShortTradeTopReasonsState


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


def _collect_breakout_gate_misses(*, breakout_freshness: float, trend_acceleration: float, breakout_min: float, trend_min: float, label: str) -> list[str]:
    misses: list[str] = []
    if breakout_freshness < breakout_min:
        misses.append(f"{label}_breakout_freshness_below_min")
    if trend_acceleration < trend_min:
        misses.append(f"{label}_trend_acceleration_below_min")
    return misses


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
    layer_c_watchlist_selected_only_shrink_guard: dict[str, Any],
    short_trade_boundary_selected_only_shrink_guard: dict[str, Any],
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
        "layer_c_watchlist_selected_only_shrink_applied" if layer_c_watchlist_selected_only_shrink_guard.get("applied") else None,
        "short_trade_boundary_selected_only_shrink_applied" if short_trade_boundary_selected_only_shrink_guard.get("applied") else None,
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
    watchlist_filter_diagnostics_selected_only_shrink_guard: dict[str, Any],
    layer_c_watchlist_selected_only_shrink_guard: dict[str, Any],
    short_trade_boundary_selected_only_shrink_guard: dict[str, Any],
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
        "watchlist_filter_diagnostics_selected_only_shrink_applied" if watchlist_filter_diagnostics_selected_only_shrink_guard.get("applied") else None,
        "layer_c_watchlist_selected_only_shrink_applied" if layer_c_watchlist_selected_only_shrink_guard.get("applied") else None,
        "short_trade_boundary_selected_only_shrink_applied" if short_trade_boundary_selected_only_shrink_guard.get("applied") else None,
        "evidence_deficient_broad_family_only" if carryover_evidence_deficiency["evidence_deficient"] else None,
        "selected_historical_proof_missing" if selected_historical_proof_deficiency["proof_missing"] else None,
        "t_plus_2_continuation_candidate" if t_plus_2_continuation_candidate["applied"] else None,
        f"score_short={score_target:.2f}",
    ]


def _collect_selected_only_shrink_top_reasons(
    *,
    watchlist_filter_diagnostics_selected_only_shrink_guard: dict[str, Any],
    layer_c_watchlist_selected_only_shrink_guard: dict[str, Any],
    short_trade_boundary_selected_only_shrink_guard: dict[str, Any],
) -> list[str]:
    return [
        reason
        for reason in [
        "watchlist_filter_diagnostics_selected_only_shrink_applied" if watchlist_filter_diagnostics_selected_only_shrink_guard.get("applied") else None,
        "layer_c_watchlist_selected_only_shrink_applied" if layer_c_watchlist_selected_only_shrink_guard.get("applied") else None,
        "short_trade_boundary_selected_only_shrink_applied" if short_trade_boundary_selected_only_shrink_guard.get("applied") else None,
        ]
        if reason is not None
    ]


def _build_short_trade_top_reasons(
    *,
    state: ShortTradeTopReasonsState,
) -> list[str]:
    reasons = [
        *_collect_selected_only_shrink_top_reasons(
            watchlist_filter_diagnostics_selected_only_shrink_guard=state.watchlist_filter_diagnostics_selected_only_shrink_guard,
            layer_c_watchlist_selected_only_shrink_guard=state.layer_c_watchlist_selected_only_shrink_guard,
            short_trade_boundary_selected_only_shrink_guard=state.short_trade_boundary_selected_only_shrink_guard,
        ),
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
            layer_c_watchlist_selected_only_shrink_guard=state.layer_c_watchlist_selected_only_shrink_guard,
            short_trade_boundary_selected_only_shrink_guard=state.short_trade_boundary_selected_only_shrink_guard,
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
            watchlist_filter_diagnostics_selected_only_shrink_guard=state.watchlist_filter_diagnostics_selected_only_shrink_guard,
            layer_c_watchlist_selected_only_shrink_guard=state.layer_c_watchlist_selected_only_shrink_guard,
            short_trade_boundary_selected_only_shrink_guard=state.short_trade_boundary_selected_only_shrink_guard,
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
