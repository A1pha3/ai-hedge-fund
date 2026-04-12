from __future__ import annotations

from typing import Any, Callable

from src.targets.models import TargetEvaluationInput


def _append_short_trade_snapshot_profitability_tags(
    *,
    input_data: TargetEvaluationInput,
    profitability_relief: dict[str, Any],
    profitability_hard_cliff_boundary_relief: dict[str, Any],
    historical_execution_relief: dict[str, Any],
    positive_tags: list[str],
    negative_tags: list[str],
) -> None:
    if input_data.layer_c_decision == "avoid":
        negative_tags.append("layer_c_avoid_signal")
    if profitability_relief["hard_cliff"]:
        negative_tags.append("profitability_hard_cliff")
    if profitability_relief["relief_applied"]:
        positive_tags.append("profitability_relief_applied")
    elif profitability_relief["relief_enabled"] and profitability_relief["hard_cliff"] and input_data.layer_c_decision == "avoid":
        negative_tags.append("profitability_relief_not_triggered")
    if profitability_hard_cliff_boundary_relief["applied"]:
        positive_tags.append("profitability_hard_cliff_boundary_relief_applied")
    if historical_execution_relief["applied"]:
        positive_tags.append("historical_execution_relief_applied")


def _append_short_trade_snapshot_catalyst_tags(
    *,
    raw_catalyst_freshness: float,
    catalyst_relief: dict[str, Any],
    positive_tags: list[str],
    negative_tags: list[str],
) -> None:
    if catalyst_relief["applied"]:
        if str(catalyst_relief["reason"]) == "catalyst_theme_short_trade_carryover":
            positive_tags.append("catalyst_theme_short_trade_carryover_applied")
        else:
            positive_tags.append("upstream_shadow_catalyst_relief_applied")
    elif catalyst_relief["enabled"] and raw_catalyst_freshness < float(catalyst_relief["catalyst_freshness_floor"]):
        if str(catalyst_relief["reason"]) == "catalyst_theme_short_trade_carryover":
            negative_tags.append("catalyst_theme_short_trade_carryover_not_triggered")
        else:
            negative_tags.append("upstream_shadow_catalyst_relief_not_triggered")


def _append_short_trade_snapshot_continuation_relief_tags(
    *,
    visibility_gap_continuation_relief: dict[str, Any],
    merge_approved_continuation_relief: dict[str, Any],
    prepared_breakout_penalty_relief: dict[str, Any],
    prepared_breakout_catalyst_relief: dict[str, Any],
    prepared_breakout_volume_relief: dict[str, Any],
    prepared_breakout_continuation_relief: dict[str, Any],
    prepared_breakout_selected_catalyst_relief: dict[str, Any],
    positive_tags: list[str],
) -> None:
    if visibility_gap_continuation_relief["applied"]:
        positive_tags.append("visibility_gap_continuation_relief_applied")
    if merge_approved_continuation_relief["applied"]:
        positive_tags.append("merge_approved_continuation_relief_applied")
    if prepared_breakout_penalty_relief["applied"]:
        positive_tags.append("prepared_breakout_penalty_relief_applied")
    if prepared_breakout_catalyst_relief["applied"]:
        positive_tags.append("prepared_breakout_catalyst_relief_applied")
    if prepared_breakout_volume_relief["applied"]:
        positive_tags.append("prepared_breakout_volume_relief_applied")
    if prepared_breakout_continuation_relief["applied"]:
        positive_tags.append("prepared_breakout_continuation_relief_applied")
    if prepared_breakout_selected_catalyst_relief["applied"]:
        positive_tags.append("prepared_breakout_selected_catalyst_relief_applied")


def _append_short_trade_snapshot_penalty_tags(
    *,
    watchlist_zero_catalyst_penalty: dict[str, Any],
    watchlist_zero_catalyst_crowded_penalty: dict[str, Any],
    watchlist_zero_catalyst_flat_trend_penalty: dict[str, Any],
    t_plus_2_continuation_candidate: dict[str, Any],
    positive_tags: list[str],
    negative_tags: list[str],
) -> None:
    if watchlist_zero_catalyst_penalty["applied"]:
        negative_tags.append("watchlist_zero_catalyst_penalty_applied")
    if watchlist_zero_catalyst_crowded_penalty["applied"]:
        negative_tags.append("watchlist_zero_catalyst_crowded_penalty_applied")
    if watchlist_zero_catalyst_flat_trend_penalty["applied"]:
        negative_tags.append("watchlist_zero_catalyst_flat_trend_penalty_applied")
    if t_plus_2_continuation_candidate["applied"]:
        positive_tags.append("t_plus_2_continuation_candidate")


def _append_short_trade_snapshot_blockers(
    *,
    input_data: TargetEvaluationInput,
    profile: Any,
    trend_signal: Any,
    stale_trend_repair_penalty: float,
    overhead_supply_penalty: float,
    extension_without_room_penalty: float,
    blockers: list[str],
    gate_status: dict[str, Any],
    signal_signed_strength_fn: Callable[[Any], float],
) -> None:
    if trend_signal is None or float(trend_signal.completeness) <= 0:
        blockers.append("missing_trend_signal")
        gate_status["data"] = "fail"
    if input_data.bc_conflict in profile.hard_block_bearish_conflicts:
        blockers.append("layer_c_bearish_conflict")
        gate_status["structural"] = "fail"
    if signal_signed_strength_fn(trend_signal) <= 0.0:
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


def _append_short_trade_snapshot_strength_tags(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    catalyst_freshness: float,
    sector_resonance: float,
    event_signal: Any,
    positive_tags: list[str],
    negative_tags: list[str],
) -> None:
    if event_signal is None or float(event_signal.completeness) <= 0:
        negative_tags.append("event_signal_incomplete")
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


def _build_short_trade_snapshot_label_inputs(
    *,
    signal_snapshot: dict[str, Any],
    relief_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return {
        "trend_signal": signal_snapshot["trend_signal"],
        "event_signal": signal_snapshot["event_signal"],
        "breakout_freshness": float(relief_snapshot["breakout_freshness"]),
        "trend_acceleration": float(relief_snapshot["trend_acceleration"]),
        "raw_catalyst_freshness": float(signal_snapshot["raw_catalyst_freshness"]),
        "catalyst_freshness": float(relief_snapshot["catalyst_freshness"]),
        "sector_resonance": float(signal_snapshot["sector_resonance"]),
        "profitability_relief": dict(relief_snapshot["profitability_relief"]),
        "profitability_hard_cliff_boundary_relief": dict(relief_snapshot["profitability_hard_cliff_boundary_relief"]),
        "historical_execution_relief": dict(relief_snapshot["historical_execution_relief"]),
        "catalyst_relief": dict(relief_snapshot["upstream_shadow_catalyst_relief"]),
        "visibility_gap_continuation_relief": dict(relief_snapshot["visibility_gap_continuation_relief"]),
        "merge_approved_continuation_relief": dict(relief_snapshot["merge_approved_continuation_relief"]),
        "prepared_breakout_penalty_relief": dict(relief_snapshot["prepared_breakout_penalty_relief"]),
        "prepared_breakout_catalyst_relief": dict(relief_snapshot["prepared_breakout_catalyst_relief"]),
        "prepared_breakout_volume_relief": dict(relief_snapshot["prepared_breakout_volume_relief"]),
        "prepared_breakout_continuation_relief": dict(relief_snapshot["prepared_breakout_continuation_relief"]),
        "prepared_breakout_selected_catalyst_relief": dict(relief_snapshot["prepared_breakout_selected_catalyst_relief"]),
        "watchlist_zero_catalyst_penalty": dict(relief_snapshot["watchlist_zero_catalyst_penalty"]),
        "watchlist_zero_catalyst_crowded_penalty": dict(relief_snapshot["watchlist_zero_catalyst_crowded_penalty"]),
        "watchlist_zero_catalyst_flat_trend_penalty": dict(relief_snapshot["watchlist_zero_catalyst_flat_trend_penalty"]),
        "t_plus_2_continuation_candidate": dict(relief_snapshot["t_plus_2_continuation_candidate"]),
        "stale_trend_repair_penalty": float(relief_snapshot["stale_trend_repair_penalty"]),
        "overhead_supply_penalty": float(relief_snapshot["overhead_supply_penalty"]),
        "extension_without_room_penalty": float(relief_snapshot["extension_without_room_penalty"]),
    }


def _initialize_short_trade_snapshot_label_state(input_data: TargetEvaluationInput) -> tuple[list[str], list[str], list[str], dict[str, str]]:
    return (
        [],
        [],
        [],
        {
            "data": "pass",
            "execution": "pass" if input_data.execution_constraints.get("included_in_buy_orders") else "proxy_only",
            "structural": "pass",
            "score": "fail",
        },
    )


def collect_short_trade_snapshot_labels_and_gates(
    input_data: TargetEvaluationInput,
    *,
    profile: Any,
    signal_snapshot: dict[str, Any],
    relief_snapshot: dict[str, Any],
    signal_signed_strength_fn: Callable[[Any], float],
) -> dict[str, Any]:
    inputs = _build_short_trade_snapshot_label_inputs(
        signal_snapshot=signal_snapshot,
        relief_snapshot=relief_snapshot,
    )
    positive_tags, negative_tags, blockers, gate_status = _initialize_short_trade_snapshot_label_state(input_data)

    _append_short_trade_snapshot_profitability_tags(
        input_data=input_data,
        profitability_relief=inputs["profitability_relief"],
        profitability_hard_cliff_boundary_relief=inputs["profitability_hard_cliff_boundary_relief"],
        historical_execution_relief=inputs["historical_execution_relief"],
        positive_tags=positive_tags,
        negative_tags=negative_tags,
    )
    _append_short_trade_snapshot_catalyst_tags(
        raw_catalyst_freshness=inputs["raw_catalyst_freshness"],
        catalyst_relief=inputs["catalyst_relief"],
        positive_tags=positive_tags,
        negative_tags=negative_tags,
    )
    _append_short_trade_snapshot_continuation_relief_tags(
        visibility_gap_continuation_relief=inputs["visibility_gap_continuation_relief"],
        merge_approved_continuation_relief=inputs["merge_approved_continuation_relief"],
        prepared_breakout_penalty_relief=inputs["prepared_breakout_penalty_relief"],
        prepared_breakout_catalyst_relief=inputs["prepared_breakout_catalyst_relief"],
        prepared_breakout_volume_relief=inputs["prepared_breakout_volume_relief"],
        prepared_breakout_continuation_relief=inputs["prepared_breakout_continuation_relief"],
        prepared_breakout_selected_catalyst_relief=inputs["prepared_breakout_selected_catalyst_relief"],
        positive_tags=positive_tags,
    )
    _append_short_trade_snapshot_penalty_tags(
        watchlist_zero_catalyst_penalty=inputs["watchlist_zero_catalyst_penalty"],
        watchlist_zero_catalyst_crowded_penalty=inputs["watchlist_zero_catalyst_crowded_penalty"],
        watchlist_zero_catalyst_flat_trend_penalty=inputs["watchlist_zero_catalyst_flat_trend_penalty"],
        t_plus_2_continuation_candidate=inputs["t_plus_2_continuation_candidate"],
        positive_tags=positive_tags,
        negative_tags=negative_tags,
    )
    _append_short_trade_snapshot_blockers(
        input_data=input_data,
        profile=profile,
        trend_signal=inputs["trend_signal"],
        stale_trend_repair_penalty=inputs["stale_trend_repair_penalty"],
        overhead_supply_penalty=inputs["overhead_supply_penalty"],
        extension_without_room_penalty=inputs["extension_without_room_penalty"],
        blockers=blockers,
        gate_status=gate_status,
        signal_signed_strength_fn=signal_signed_strength_fn,
    )
    _append_short_trade_snapshot_strength_tags(
        input_data=input_data,
        breakout_freshness=inputs["breakout_freshness"],
        trend_acceleration=inputs["trend_acceleration"],
        catalyst_freshness=inputs["catalyst_freshness"],
        sector_resonance=inputs["sector_resonance"],
        event_signal=inputs["event_signal"],
        positive_tags=positive_tags,
        negative_tags=negative_tags,
    )

    return {
        "positive_tags": positive_tags,
        "negative_tags": negative_tags,
        "blockers": blockers,
        "gate_status": gate_status,
    }
