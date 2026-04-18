from __future__ import annotations

from typing import Any

from src.execution.models import LayerCResult
from src.screening.models import StrategySignal
from src.targets.explainability import clamp_unit_interval
from src.targets.models import TargetEvaluationInput, TargetEvaluationResult
from src.targets.profiles import (
    get_active_short_trade_target_profile,
    use_short_trade_target_profile,
)
from src.targets.short_trade_prepared_breakout_helpers import (
    resolve_prepared_breakout_catalyst_relief as _resolve_prepared_breakout_catalyst_relief,
)
from src.targets.short_trade_prepared_breakout_helpers import (
    resolve_prepared_breakout_continuation_relief as _resolve_prepared_breakout_continuation_relief,
)
from src.targets.short_trade_prepared_breakout_helpers import (
    resolve_prepared_breakout_penalty_relief as _resolve_prepared_breakout_penalty_relief,
)
from src.targets.short_trade_prepared_breakout_helpers import (
    resolve_prepared_breakout_selected_catalyst_relief as _resolve_prepared_breakout_selected_catalyst_relief,
)
from src.targets.short_trade_prepared_breakout_helpers import (
    resolve_prepared_breakout_volume_relief as _resolve_prepared_breakout_volume_relief,
)
from src.targets.short_trade_target_input_helpers import (
    build_item_replay_context as _build_item_replay_context_impl,
)
from src.targets.short_trade_target_input_helpers import (
    build_target_input_from_entry as _build_target_input_from_entry_impl,
)
from src.targets.short_trade_target_input_helpers import (
    build_target_input_from_item as _build_target_input_from_item_impl,
)
from src.targets.short_trade_target_prior_helpers import (
    calibrate_short_trade_historical_prior,
)
from src.targets.short_trade_target_profitability_helpers import (
    resolve_profitability_hard_cliff_boundary_relief_impl,
    resolve_profitability_relief_impl,
)
from src.targets.short_trade_target_relief_helpers import (
    resolve_historical_execution_relief as _resolve_historical_execution_relief_impl,
)
from src.targets.short_trade_target_relief_helpers import (
    resolve_merge_approved_continuation_relief as _resolve_merge_approved_continuation_relief_impl,
)
from src.targets.short_trade_target_relief_helpers import (
    resolve_upstream_shadow_catalyst_relief as _resolve_upstream_shadow_catalyst_relief_impl,
)
from src.targets.short_trade_target_relief_helpers import (
    resolve_visibility_gap_continuation_relief as _resolve_visibility_gap_continuation_relief_impl,
)
from src.targets.short_trade_target_signal_snapshot_helpers import (
    build_short_trade_signal_snapshot,
)
from src.targets.short_trade_target_snapshot_label_helpers import (
    collect_short_trade_snapshot_labels_and_gates as _collect_short_trade_snapshot_labels_and_gates_impl,
)
from src.targets.short_trade_target_snapshot_payload_helpers import (
    build_short_trade_target_snapshot_payload,
)
from src.targets.short_trade_target_watchlist_helpers import (
    resolve_t_plus_2_continuation_candidate_impl,
    resolve_watchlist_zero_catalyst_crowded_penalty_impl,
    resolve_watchlist_zero_catalyst_flat_trend_penalty_impl,
    resolve_watchlist_zero_catalyst_penalty_impl,
)

STRONG_CARRYOVER_SELECTED_SCORE_TOLERANCE = 0.001
STRONG_CARRYOVER_HISTORY_MIN_EVALUABLE_COUNT = 3
STRONG_CARRYOVER_SELECTED_TOLERANCE_MIN_EVALUABLE_COUNT = STRONG_CARRYOVER_HISTORY_MIN_EVALUABLE_COUNT
STRONG_CARRYOVER_SELECTED_TOLERANCE_MIN_CALIBRATED_NEXT_CLOSE_POSITIVE_RATE = 0.68
STRONG_CARRYOVER_SELECTED_TOLERANCE_MIN_CALIBRATED_NEXT_HIGH_HIT_RATE = 0.72
STRONG_CARRYOVER_SELECTED_TOLERANCE_MIN_CALIBRATED_NEXT_OPEN_TO_CLOSE_RETURN_MEAN = 0.017
STRONG_CARRYOVER_SELECTED_TOLERANCE_MIN_EVIDENCE_WEIGHT = 0.5
SELECTED_HISTORICAL_PROOF_REQUIRED_SOURCES = frozenset(
    {
        "upstream_liquidity_corridor_shadow",
        "post_gate_liquidity_competition_shadow",
    }
)


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


def _subfactor_metrics(signal: StrategySignal | None, name: str) -> dict[str, Any]:
    if signal is None:
        return {}
    snapshot = signal.sub_factors.get(name, {}) if isinstance(signal.sub_factors, dict) else {}
    if not isinstance(snapshot, dict):
        return {}
    metrics = snapshot.get("metrics", {})
    return metrics if isinstance(metrics, dict) else {}


def _normalize_positive_score_weights(configured_weights: dict[str, float]) -> dict[str, float]:
    total_weight = sum(max(0.0, value) for value in configured_weights.values())
    if total_weight <= 0:
        unit_weight = round(1.0 / len(configured_weights), 4)
        return dict.fromkeys(configured_weights, unit_weight)
    return {name: max(0.0, value) / total_weight for name, value in configured_weights.items()}


def _profitability_snapshot(signal: StrategySignal | None) -> dict[str, Any]:
    if signal is None or not isinstance(signal.sub_factors, dict):
        return {}
    snapshot = signal.sub_factors.get("profitability", {})
    return snapshot if isinstance(snapshot, dict) else {}


def _historical_prior(input_data: TargetEvaluationInput) -> dict[str, Any]:
    return calibrate_short_trade_historical_prior(dict(input_data.replay_context.get("historical_prior") or {}))


def _normalized_reason_codes(values: Any) -> list[str]:
    return [str(reason) for reason in list(values or []) if str(reason or "").strip()]


def _is_catalyst_theme_carryover_candidate(*, source: str, candidate_reason_codes: set[str]) -> bool:
    return source == "catalyst_theme" and "catalyst_theme_short_trade_carryover_candidate" in candidate_reason_codes


def _resolve_carryover_evidence_deficiency(input_data: TargetEvaluationInput) -> dict[str, Any]:
    historical_prior = _historical_prior(input_data)
    source = str(input_data.replay_context.get("source") or "").strip()
    candidate_reason_codes = set(_normalized_reason_codes(input_data.replay_context.get("candidate_reason_codes")))
    same_ticker_sample_count = int(historical_prior.get("same_ticker_sample_count") or 0)
    same_family_sample_count = int(historical_prior.get("same_family_sample_count") or 0)
    same_family_source_sample_count = int(historical_prior.get("same_family_source_sample_count") or 0)
    same_family_source_score_catalyst_sample_count = int(historical_prior.get("same_family_source_score_catalyst_sample_count") or 0)
    same_source_score_sample_count = int(historical_prior.get("same_source_score_sample_count") or 0)
    evaluable_count = int(historical_prior.get("evaluable_count") or 0)

    gate_hits = {
        "candidate_source": source == "catalyst_theme",
        "carryover_candidate": "catalyst_theme_short_trade_carryover_candidate" in candidate_reason_codes,
        "execution_quality_label": str(historical_prior.get("execution_quality_label") or "") == "close_continuation",
        "entry_timing_bias": str(historical_prior.get("entry_timing_bias") or "") == "confirm_then_hold",
        "low_same_ticker_samples": same_ticker_sample_count < 2,
        "low_evaluable_count": evaluable_count <= 1,
        "broad_family_only": same_family_sample_count > 0,
        "no_same_family_source": same_family_source_sample_count == 0,
        "no_same_family_source_score_catalyst": same_family_source_score_catalyst_sample_count == 0,
        "no_same_source_score": same_source_score_sample_count == 0,
    }
    return {
        "enabled": bool(historical_prior),
        "evidence_deficient": all(gate_hits.values()),
        "gate_hits": gate_hits,
        "same_ticker_sample_count": same_ticker_sample_count,
        "same_family_sample_count": same_family_sample_count,
        "same_family_source_sample_count": same_family_source_sample_count,
        "same_family_source_score_catalyst_sample_count": same_family_source_score_catalyst_sample_count,
        "same_source_score_sample_count": same_source_score_sample_count,
        "evaluable_count": evaluable_count,
    }


def _resolve_selected_historical_proof_deficiency(input_data: TargetEvaluationInput) -> dict[str, Any]:
    historical_prior = _historical_prior(input_data)
    source = str(input_data.replay_context.get("source") or "").strip()
    evaluable_count = int(historical_prior.get("evaluable_count") or 0)
    proof_required = source in SELECTED_HISTORICAL_PROOF_REQUIRED_SOURCES
    gate_hits = {
        "candidate_source": proof_required,
        "has_evaluable_history": evaluable_count >= 1,
    }
    return {
        "enabled": proof_required,
        "proof_missing": proof_required and evaluable_count < 1,
        "gate_hits": gate_hits,
        "candidate_source": source,
        "evaluable_count": evaluable_count,
    }


def _preferred_entry_mode_from_historical_prior(historical_prior: dict[str, Any] | None) -> str:
    from src.targets.short_trade_target_evaluation_helpers import (
        _preferred_entry_mode_from_historical_prior as _helper,
    )

    return _helper(historical_prior)


def _resolve_selected_score_tolerance(
    *,
    score_target: float,
    effective_select_threshold: float,
    upstream_shadow_catalyst_relief_applied: bool,
    upstream_shadow_catalyst_relief_reason: str,
    historical_prior: dict[str, Any],
) -> float:
    gap_to_selected = float(effective_select_threshold) - float(score_target)
    if gap_to_selected <= 0.0:
        return 0.0
    if not _is_eligible_for_carryover_tolerance(
        upstream_shadow_catalyst_relief_applied=upstream_shadow_catalyst_relief_applied,
        upstream_shadow_catalyst_relief_reason=upstream_shadow_catalyst_relief_reason,
        historical_prior=historical_prior,
    ):
        return 0.0
    return STRONG_CARRYOVER_SELECTED_SCORE_TOLERANCE if gap_to_selected <= STRONG_CARRYOVER_SELECTED_SCORE_TOLERANCE else 0.0


def _is_eligible_for_carryover_tolerance(
    *,
    upstream_shadow_catalyst_relief_applied: bool,
    upstream_shadow_catalyst_relief_reason: str,
    historical_prior: dict[str, Any],
) -> bool:
    if not upstream_shadow_catalyst_relief_applied:
        return False
    if upstream_shadow_catalyst_relief_reason != "catalyst_theme_short_trade_carryover":
        return False
    if str(historical_prior.get("execution_quality_label") or "") != "close_continuation":
        return False
    if str(historical_prior.get("entry_timing_bias") or "") != "confirm_then_hold":
        return False

    evaluable_count = int(historical_prior.get("evaluable_count") or 0)
    if evaluable_count < STRONG_CARRYOVER_SELECTED_TOLERANCE_MIN_EVALUABLE_COUNT:
        return False

    prior_metrics = _extract_prior_metrics(historical_prior, evaluable_count)
    if _has_calibrated_prior(historical_prior):
        return _meets_calibrated_thresholds(prior_metrics)
    return _meets_uncalibrated_thresholds(prior_metrics)


def _extract_prior_metrics(historical_prior: dict[str, Any], evaluable_count: int) -> dict[str, float]:
    prior_strength = float(historical_prior.get("prior_shrinkage_strength", 3.0) or 3.0)
    evidence_weight = clamp_unit_interval(
        float(
            historical_prior.get(
                "prior_evidence_weight",
                (float(evaluable_count) / (float(evaluable_count) + prior_strength)) if (float(evaluable_count) + prior_strength) > 0 else 0.0,
            )
            or 0.0
        )
    )
    next_close_positive_rate = clamp_unit_interval(float(historical_prior.get("calibrated_next_close_positive_rate", historical_prior.get("next_close_positive_rate", 0.0)) or 0.0))
    next_high_hit_rate = clamp_unit_interval(float(historical_prior.get("calibrated_next_high_hit_rate_at_threshold", historical_prior.get("next_high_hit_rate_at_threshold", 0.0)) or 0.0))
    next_open_to_close_return_mean = float(historical_prior.get("calibrated_next_open_to_close_return_mean", historical_prior.get("next_open_to_close_return_mean", 0.0)) or 0.0)
    return {
        "evidence_weight": evidence_weight,
        "next_close_positive_rate": next_close_positive_rate,
        "next_high_hit_rate": next_high_hit_rate,
        "next_open_to_close_return_mean": next_open_to_close_return_mean,
    }


def _has_calibrated_prior(historical_prior: dict[str, Any]) -> bool:
    return any(
        key in historical_prior
        for key in (
            "calibrated_next_close_positive_rate",
            "calibrated_next_high_hit_rate_at_threshold",
            "calibrated_next_open_to_close_return_mean",
            "prior_evidence_weight",
        )
    )


def _meets_calibrated_thresholds(metrics: dict[str, float]) -> bool:
    return (
        metrics["evidence_weight"] >= STRONG_CARRYOVER_SELECTED_TOLERANCE_MIN_EVIDENCE_WEIGHT
        and metrics["next_close_positive_rate"] >= STRONG_CARRYOVER_SELECTED_TOLERANCE_MIN_CALIBRATED_NEXT_CLOSE_POSITIVE_RATE
        and metrics["next_high_hit_rate"] >= STRONG_CARRYOVER_SELECTED_TOLERANCE_MIN_CALIBRATED_NEXT_HIGH_HIT_RATE
        and metrics["next_open_to_close_return_mean"] >= STRONG_CARRYOVER_SELECTED_TOLERANCE_MIN_CALIBRATED_NEXT_OPEN_TO_CLOSE_RETURN_MEAN
    )


def _meets_uncalibrated_thresholds(metrics: dict[str, float]) -> bool:
    return (
        metrics["next_close_positive_rate"] >= 0.8
        and metrics["next_high_hit_rate"] >= 0.8
        and metrics["next_open_to_close_return_mean"] >= 0.02
    )


def _resolve_profitability_relief(
    *,
    input_data: TargetEvaluationInput,
    fundamental_signal: StrategySignal | None,
    breakout_freshness: float,
    catalyst_freshness: float,
    sector_resonance: float,
    profile: Any,
) -> dict[str, Any]:
    return resolve_profitability_relief_impl(
        input_data=input_data,
        fundamental_signal=fundamental_signal,
        breakout_freshness=breakout_freshness,
        catalyst_freshness=catalyst_freshness,
        sector_resonance=sector_resonance,
        profile=profile,
        profitability_snapshot_fn=_profitability_snapshot,
    )


def _resolve_profitability_hard_cliff_boundary_relief(
    *,
    input_data: TargetEvaluationInput,
    profitability_hard_cliff: bool,
    breakout_freshness: float,
    trend_acceleration: float,
    catalyst_freshness: float,
    sector_resonance: float,
    close_strength: float,
    stale_trend_repair_penalty: float,
    extension_without_room_penalty: float,
    profile: Any,
) -> dict[str, Any]:
    return resolve_profitability_hard_cliff_boundary_relief_impl(
        input_data=input_data,
        profitability_hard_cliff=profitability_hard_cliff,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        catalyst_freshness=catalyst_freshness,
        sector_resonance=sector_resonance,
        close_strength=close_strength,
        stale_trend_repair_penalty=stale_trend_repair_penalty,
        extension_without_room_penalty=extension_without_room_penalty,
        profile=profile,
    )


def _build_item_replay_context(item: LayerCResult) -> dict[str, Any]:
    return _build_item_replay_context_impl(
        item,
        normalized_reason_codes_fn=_normalized_reason_codes,
    )


def _resolve_historical_execution_relief(
    *,
    input_data: TargetEvaluationInput,
    profitability_hard_cliff: bool,
    profile: Any,
) -> dict[str, Any]:
    return _resolve_historical_execution_relief_impl(
        input_data=input_data,
        profitability_hard_cliff=profitability_hard_cliff,
        profile=profile,
        historical_prior_getter=_historical_prior,
        normalized_reason_codes=_normalized_reason_codes,
        is_catalyst_theme_carryover_candidate=_is_catalyst_theme_carryover_candidate,
        strong_carryover_history_min_evaluable_count=STRONG_CARRYOVER_HISTORY_MIN_EVALUABLE_COUNT,
    )


def _resolve_upstream_shadow_catalyst_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    catalyst_freshness: float,
    profitability_hard_cliff: bool,
    profile: Any,
) -> dict[str, Any]:
    return _resolve_upstream_shadow_catalyst_relief_impl(
        input_data=input_data,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        catalyst_freshness=catalyst_freshness,
        profitability_hard_cliff=profitability_hard_cliff,
        profile=profile,
        historical_prior_getter=_historical_prior,
        normalized_reason_codes=_normalized_reason_codes,
        strong_carryover_history_min_evaluable_count=STRONG_CARRYOVER_HISTORY_MIN_EVALUABLE_COUNT,
    )


def _resolve_visibility_gap_continuation_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    catalyst_freshness: float,
    profitability_hard_cliff: bool,
    profile: Any,
) -> dict[str, Any]:
    return _resolve_visibility_gap_continuation_relief_impl(
        input_data=input_data,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        catalyst_freshness=catalyst_freshness,
        profitability_hard_cliff=profitability_hard_cliff,
        profile=profile,
        historical_prior_getter=_historical_prior,
    )


def _resolve_merge_approved_continuation_relief(
    *,
    input_data: TargetEvaluationInput,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    profitability_hard_cliff: bool,
    profile: Any,
) -> dict[str, Any]:
    return _resolve_merge_approved_continuation_relief_impl(
        input_data=input_data,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        profitability_hard_cliff=profitability_hard_cliff,
        profile=profile,
        historical_prior_getter=_historical_prior,
    )


def _cohort_alignment(agent_contribution_summary: dict[str, Any], cohort_name: str) -> float:
    cohort_contributions = dict(agent_contribution_summary.get("cohort_contributions", {}) or {})
    return clamp_unit_interval(max(0.0, float(cohort_contributions.get(cohort_name, 0.0) or 0.0)))


def _cohort_penalty(agent_contribution_summary: dict[str, Any], cohort_name: str) -> float:
    cohort_contributions = dict(agent_contribution_summary.get("cohort_contributions", {}) or {})
    return clamp_unit_interval(max(0.0, -float(cohort_contributions.get(cohort_name, 0.0) or 0.0)))


def _resolve_watchlist_zero_catalyst_penalty(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    profile: Any,
) -> dict[str, Any]:
    return resolve_watchlist_zero_catalyst_penalty_impl(
        input_data=input_data,
        catalyst_freshness=catalyst_freshness,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        profile=profile,
        clamp_unit_interval_fn=clamp_unit_interval,
    )


def _resolve_watchlist_zero_catalyst_crowded_penalty(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    profile: Any,
) -> dict[str, Any]:
    return resolve_watchlist_zero_catalyst_crowded_penalty_impl(
        input_data=input_data,
        catalyst_freshness=catalyst_freshness,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        profile=profile,
        clamp_unit_interval_fn=clamp_unit_interval,
    )


def _resolve_watchlist_zero_catalyst_flat_trend_penalty(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    trend_acceleration: float,
    profile: Any,
) -> dict[str, Any]:
    return resolve_watchlist_zero_catalyst_flat_trend_penalty_impl(
        input_data=input_data,
        catalyst_freshness=catalyst_freshness,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        trend_acceleration=trend_acceleration,
        profile=profile,
        clamp_unit_interval_fn=clamp_unit_interval,
    )


def _resolve_t_plus_2_continuation_candidate(
    *,
    input_data: TargetEvaluationInput,
    raw_catalyst_freshness: float,
    breakout_freshness: float,
    trend_acceleration: float,
    close_strength: float,
    sector_resonance: float,
    layer_c_alignment: float,
    profile: Any,
) -> dict[str, Any]:
    return resolve_t_plus_2_continuation_candidate_impl(
        input_data=input_data,
        raw_catalyst_freshness=raw_catalyst_freshness,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        close_strength=close_strength,
        sector_resonance=sector_resonance,
        layer_c_alignment=layer_c_alignment,
        profile=profile,
        clamp_unit_interval_fn=clamp_unit_interval,
    )


def _build_target_input_from_item(*, trade_date: str, item: LayerCResult, included_in_buy_orders: bool) -> TargetEvaluationInput:
    return _build_target_input_from_item_impl(
        trade_date=trade_date,
        item=item,
        included_in_buy_orders=included_in_buy_orders,
        build_item_replay_context_fn=_build_item_replay_context,
    )


def _build_target_input_from_entry(*, trade_date: str, entry: dict[str, Any]) -> TargetEvaluationInput:
    return _build_target_input_from_entry_impl(
        trade_date=trade_date,
        entry=entry,
        normalized_reason_codes_fn=_normalized_reason_codes,
    )


def _summarize_positive_factor(name: str, value: float) -> str | None:
    if value < 0.45:
        return None
    return f"{name}={value:.2f}"


def _summarize_penalty(name: str, value: float) -> str | None:
    if value < 0.45:
        return None
    return f"{name}={value:.2f}"


def _classify_breakout_stage(*, breakout_freshness: float, trend_acceleration: float, profile: Any) -> tuple[str, bool, bool]:
    selected_gate_pass = breakout_freshness >= float(profile.selected_breakout_freshness_min) and trend_acceleration >= float(profile.selected_trend_acceleration_min)
    near_miss_gate_pass = breakout_freshness >= float(profile.near_miss_breakout_freshness_min) and trend_acceleration >= float(profile.near_miss_trend_acceleration_min)
    if selected_gate_pass:
        return "confirmed_breakout", True, True
    if near_miss_gate_pass:
        return "prepared_breakout", False, True
    return "weak_breakout", False, False


def _collect_breakout_gate_misses(*, breakout_freshness: float, trend_acceleration: float, breakout_min: float, trend_min: float, label: str) -> list[str]:
    misses: list[str] = []
    if breakout_freshness < breakout_min:
        misses.append(f"breakout_freshness_below_{label}_floor")
    if trend_acceleration < trend_min:
        misses.append(f"trend_acceleration_below_{label}_floor")
    return misses


def _resolve_positive_score_weights(profile: Any) -> dict[str, float]:
    configured_weights = {
        "breakout_freshness": float(profile.breakout_freshness_weight),
        "trend_acceleration": float(profile.trend_acceleration_weight),
        "volume_expansion_quality": float(profile.volume_expansion_quality_weight),
        "close_strength": float(profile.close_strength_weight),
        "sector_resonance": float(profile.sector_resonance_weight),
        "catalyst_freshness": float(profile.catalyst_freshness_weight),
        "layer_c_alignment": float(profile.layer_c_alignment_weight),
        "historical_continuation_score": float(getattr(profile, "historical_continuation_score_weight", 0.0)),
        "momentum_strength": float(getattr(profile, "momentum_strength_weight", 0.0)),
        "short_term_reversal": float(getattr(profile, "short_term_reversal_weight", 0.0)),
        "intraday_strength": float(getattr(profile, "intraday_strength_weight", 0.0)),
        "reversal_2d": float(getattr(profile, "reversal_2d_weight", 0.0)),
    }
    return _normalize_positive_score_weights(configured_weights)


def _compute_short_trade_signal_snapshot(input_data: TargetEvaluationInput, *, profile: Any) -> dict[str, Any]:
    return build_short_trade_signal_snapshot(
        input_data,
        profile=profile,
        load_signal_fn=_load_signal,
        subfactor_positive_strength_fn=_subfactor_positive_strength,
        subfactor_metrics_fn=_subfactor_metrics,
        positive_strength_fn=_positive_strength,
        cohort_alignment_fn=_cohort_alignment,
        cohort_penalty_fn=_cohort_penalty,
        normalize_score_fn=_normalize_score,
        clamp_unit_interval_fn=clamp_unit_interval,
        classify_breakout_stage_fn=_classify_breakout_stage,
    )


def _resolve_short_trade_snapshot_reliefs(
    input_data: TargetEvaluationInput,
    *,
    profile: Any,
    signal_snapshot: dict[str, Any],
) -> dict[str, Any]:
    from src.targets.short_trade_target_snapshot_relief_helpers import (
        resolve_short_trade_snapshot_reliefs_impl,
    )

    return resolve_short_trade_snapshot_reliefs_impl(
        input_data,
        profile=profile,
        signal_snapshot=signal_snapshot,
        historical_prior=_historical_prior,
        normalize_positive_score_weights=_normalize_positive_score_weights,
        clamp_unit_interval=clamp_unit_interval,
        resolve_profitability_relief=_resolve_profitability_relief,
        resolve_upstream_shadow_catalyst_relief=_resolve_upstream_shadow_catalyst_relief,
        resolve_visibility_gap_continuation_relief=_resolve_visibility_gap_continuation_relief,
        resolve_merge_approved_continuation_relief=_resolve_merge_approved_continuation_relief,
        resolve_historical_execution_relief=_resolve_historical_execution_relief,
        resolve_prepared_breakout_continuation_relief=_resolve_prepared_breakout_continuation_relief,
        resolve_prepared_breakout_penalty_relief=_resolve_prepared_breakout_penalty_relief,
        resolve_prepared_breakout_catalyst_relief=_resolve_prepared_breakout_catalyst_relief,
        resolve_prepared_breakout_volume_relief=_resolve_prepared_breakout_volume_relief,
        resolve_prepared_breakout_selected_catalyst_relief=_resolve_prepared_breakout_selected_catalyst_relief,
        resolve_watchlist_zero_catalyst_penalty=_resolve_watchlist_zero_catalyst_penalty,
        resolve_watchlist_zero_catalyst_crowded_penalty=_resolve_watchlist_zero_catalyst_crowded_penalty,
        resolve_watchlist_zero_catalyst_flat_trend_penalty=_resolve_watchlist_zero_catalyst_flat_trend_penalty,
        resolve_t_plus_2_continuation_candidate=_resolve_t_plus_2_continuation_candidate,
        resolve_profitability_hard_cliff_boundary_relief=_resolve_profitability_hard_cliff_boundary_relief,
        resolve_selected_score_tolerance=_resolve_selected_score_tolerance,
    )


def _collect_short_trade_snapshot_labels_and_gates(
    input_data: TargetEvaluationInput,
    *,
    profile: Any,
    signal_snapshot: dict[str, Any],
    relief_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return _collect_short_trade_snapshot_labels_and_gates_impl(
        input_data,
        profile=profile,
        signal_snapshot=signal_snapshot,
        relief_snapshot=relief_snapshot,
        signal_signed_strength_fn=_signal_signed_strength,
    )


def _build_short_trade_target_snapshot(input_data: TargetEvaluationInput) -> dict[str, Any]:
    profile = get_active_short_trade_target_profile()
    signal_snapshot = _compute_short_trade_signal_snapshot(input_data, profile=profile)
    relief_snapshot = _resolve_short_trade_snapshot_reliefs(
        input_data,
        profile=profile,
        signal_snapshot=signal_snapshot,
    )
    labels_and_gates = _collect_short_trade_snapshot_labels_and_gates(
        input_data,
        profile=profile,
        signal_snapshot=signal_snapshot,
        relief_snapshot=relief_snapshot,
    )
    return build_short_trade_target_snapshot_payload(
        profile=profile,
        signal_snapshot=signal_snapshot,
        relief_snapshot=relief_snapshot,
        labels_and_gates=labels_and_gates,
    )


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
    from src.targets.short_trade_target_evaluation_helpers import (
        _resolve_short_trade_decision as _helper,
    )

    return _helper(
        blockers=blockers,
        gate_status=gate_status,
        score_target=score_target,
        effective_near_miss_threshold=effective_near_miss_threshold,
        effective_select_threshold=effective_select_threshold,
        selected_score_tolerance=selected_score_tolerance,
        selected_breakout_gate_pass=selected_breakout_gate_pass,
        near_miss_breakout_gate_pass=near_miss_breakout_gate_pass,
        rank_decision_cap=rank_decision_cap,
        carryover_evidence_deficiency=carryover_evidence_deficiency,
        selected_historical_proof_deficiency=selected_historical_proof_deficiency,
    )


def _annotate_short_trade_tags(
    *,
    positive_tags: list[str],
    negative_tags: list[str],
    breakout_stage: str,
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
) -> None:
    from src.targets.short_trade_target_evaluation_helpers import (
        _annotate_short_trade_tags as _helper,
    )

    _helper(
        positive_tags=positive_tags,
        negative_tags=negative_tags,
        breakout_stage=breakout_stage,
        carryover_evidence_deficiency=carryover_evidence_deficiency,
        selected_historical_proof_deficiency=selected_historical_proof_deficiency,
    )


def _build_short_trade_top_reasons(
    *,
    breakout_freshness: float,
    trend_acceleration: float,
    raw_catalyst_freshness: float,
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
    profitability_hard_cliff: bool,
    breakout_stage: str,
    layer_c_avoid_penalty: float,
    stale_trend_repair_penalty: float,
    overhead_supply_penalty: float,
    extension_without_room_penalty: float,
    breakout_trap_guard: dict[str, Any] | None = None,
    market_state_threshold_adjustment: dict[str, Any] | None = None,
    watchlist_zero_catalyst_guard: dict[str, Any],
    watchlist_zero_catalyst_crowded_guard: dict[str, Any],
    watchlist_zero_catalyst_flat_trend_guard: dict[str, Any],
    carryover_evidence_deficiency: dict[str, Any],
    selected_historical_proof_deficiency: dict[str, Any],
    t_plus_2_continuation_candidate: dict[str, Any],
    score_target: float,
) -> list[str]:
    from src.targets.short_trade_target_evaluation_helpers import (
        _build_short_trade_top_reasons as _helper,
    )
    from src.targets.short_trade_target_evaluation_helpers import (
        ShortTradeTopReasonsState,
    )

    return _helper(
        state=ShortTradeTopReasonsState(
            breakout_freshness=breakout_freshness,
            trend_acceleration=trend_acceleration,
            raw_catalyst_freshness=raw_catalyst_freshness,
            upstream_shadow_catalyst_relief_applied=upstream_shadow_catalyst_relief_applied,
            upstream_shadow_catalyst_relief_reason=upstream_shadow_catalyst_relief_reason,
            visibility_gap_continuation_relief=visibility_gap_continuation_relief,
            merge_approved_continuation_relief=merge_approved_continuation_relief,
            prepared_breakout_penalty_relief=prepared_breakout_penalty_relief,
            prepared_breakout_catalyst_relief=prepared_breakout_catalyst_relief,
            prepared_breakout_volume_relief=prepared_breakout_volume_relief,
            prepared_breakout_continuation_relief=prepared_breakout_continuation_relief,
            prepared_breakout_selected_catalyst_relief=prepared_breakout_selected_catalyst_relief,
            profitability_relief_applied=profitability_relief_applied,
            profitability_hard_cliff_boundary_relief=profitability_hard_cliff_boundary_relief,
            historical_execution_relief=historical_execution_relief,
            profitability_hard_cliff=profitability_hard_cliff,
            breakout_stage=breakout_stage,
            layer_c_avoid_penalty=layer_c_avoid_penalty,
            stale_trend_repair_penalty=stale_trend_repair_penalty,
            overhead_supply_penalty=overhead_supply_penalty,
            extension_without_room_penalty=extension_without_room_penalty,
            breakout_trap_guard=dict(breakout_trap_guard or {}),
            market_state_threshold_adjustment=dict(market_state_threshold_adjustment or {}),
            watchlist_zero_catalyst_guard=watchlist_zero_catalyst_guard,
            watchlist_zero_catalyst_crowded_guard=watchlist_zero_catalyst_crowded_guard,
            watchlist_zero_catalyst_flat_trend_guard=watchlist_zero_catalyst_flat_trend_guard,
            carryover_evidence_deficiency=carryover_evidence_deficiency,
            selected_historical_proof_deficiency=selected_historical_proof_deficiency,
            t_plus_2_continuation_candidate=t_plus_2_continuation_candidate,
            score_target=score_target,
        )
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
    from src.targets.short_trade_target_evaluation_helpers import (
        _build_short_trade_rejection_reasons as _helper,
    )

    return _helper(
        decision=decision,
        blockers=blockers,
        breakout_freshness=breakout_freshness,
        trend_acceleration=trend_acceleration,
        effective_near_miss_threshold=effective_near_miss_threshold,
        score_target=score_target,
        near_miss_breakout_gate_pass=near_miss_breakout_gate_pass,
        profile=profile,
        carryover_evidence_deficiency=carryover_evidence_deficiency,
    )


def build_short_trade_target_snapshot_from_entry(
    *,
    trade_date: str,
    entry: dict[str, Any],
    profile_name: str | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if profile_name is not None or profile_overrides:
        with use_short_trade_target_profile(profile_name=profile_name or "default", overrides=profile_overrides):
            return build_short_trade_target_snapshot_from_entry(
                trade_date=trade_date,
                entry=entry,
            )
    return _build_short_trade_target_snapshot(_build_target_input_from_entry(trade_date=trade_date, entry=entry))


def _evaluate_short_trade_target(
    input_data: TargetEvaluationInput,
    *,
    rank_hint: int | None = None,
    rank_population: int | None = None,
) -> TargetEvaluationResult:
    from src.targets.short_trade_target_evaluation_helpers import (
        evaluate_short_trade_target_impl,
    )

    return evaluate_short_trade_target_impl(
        input_data,
        rank_hint=rank_hint,
        rank_population=rank_population,
        build_short_trade_target_snapshot=_build_short_trade_target_snapshot,
        resolve_carryover_evidence_deficiency=_resolve_carryover_evidence_deficiency,
        resolve_selected_historical_proof_deficiency=_resolve_selected_historical_proof_deficiency,
        classify_breakout_stage=_classify_breakout_stage,
        resolve_short_trade_decision=_resolve_short_trade_decision,
        annotate_short_trade_tags=_annotate_short_trade_tags,
        build_short_trade_top_reasons=_build_short_trade_top_reasons,
        build_short_trade_rejection_reasons=_build_short_trade_rejection_reasons,
        preferred_entry_mode_from_historical_prior=_preferred_entry_mode_from_historical_prior,
    )


def evaluate_short_trade_selected_target(
    *,
    trade_date: str,
    item: LayerCResult,
    rank_hint: int | None = None,
    rank_population: int | None = None,
    included_in_buy_orders: bool = False,
    profile_name: str | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> TargetEvaluationResult:
    if profile_name is not None or profile_overrides:
        with use_short_trade_target_profile(profile_name=profile_name or "default", overrides=profile_overrides):
            return evaluate_short_trade_selected_target(
                trade_date=trade_date,
                item=item,
                rank_hint=rank_hint,
                rank_population=rank_population,
                included_in_buy_orders=included_in_buy_orders,
            )
    return _evaluate_short_trade_target(
        _build_target_input_from_item(trade_date=trade_date, item=item, included_in_buy_orders=included_in_buy_orders),
        rank_hint=rank_hint,
        rank_population=rank_population,
    )


def evaluate_short_trade_rejected_target(
    *,
    trade_date: str,
    entry: dict[str, Any],
    rank_hint: int | None = None,
    rank_population: int | None = None,
    profile_name: str | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> TargetEvaluationResult:
    if profile_name is not None or profile_overrides:
        with use_short_trade_target_profile(profile_name=profile_name or "default", overrides=profile_overrides):
            return evaluate_short_trade_rejected_target(
                trade_date=trade_date,
                entry=entry,
                rank_hint=rank_hint,
                rank_population=rank_population,
            )
    return _evaluate_short_trade_target(
        _build_target_input_from_entry(trade_date=trade_date, entry=entry),
        rank_hint=rank_hint,
        rank_population=rank_population,
    )
