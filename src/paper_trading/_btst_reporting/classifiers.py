from __future__ import annotations
from typing import Any
from src.paper_trading.btst_reporting_utils import (
    WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE,
    WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE,
    WEAK_BALANCED_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT,
    WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT,
    WEAK_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT,
    _as_float,
    _build_execution_quality_balanced_confirmation_result,
    _build_execution_quality_close_continuation_result,
    _build_execution_quality_gap_chase_risk_result,
    _build_execution_quality_intraday_only_result,
    _build_execution_quality_unknown_result,
    _build_execution_quality_zero_follow_through_result,
)


def _classify_historical_prior(
    hit_rate: float | None, close_positive_rate: float | None, evaluable_count: int
) -> tuple[str, str]:
    if evaluable_count <= 0:
        return "unknown", "unscored"
    if evaluable_count < 3:
        if (hit_rate or 0.0) >= 0.5 or (close_positive_rate or 0.0) >= 0.5:
            return "mixed", "medium"
        return "weak", "low"
    if (hit_rate or 0.0) >= 0.6 and (close_positive_rate or 0.0) >= 0.5:
        return "positive", "high"
    if (hit_rate or 0.0) >= 0.4 or (close_positive_rate or 0.0) >= 0.4:
        return "mixed", "medium"
    return "weak", "low"


def _classify_execution_quality_prior(
    next_open_return_mean: float | None,
    next_open_to_close_return_mean: float | None,
    next_high_return_mean: float | None,
    next_close_return_mean: float | None,
    next_high_hit_rate: float | None,
    next_close_positive_rate: float | None,
    evaluable_count: int,
) -> dict[str, str]:
    if evaluable_count <= 0:
        return _build_execution_quality_unknown_result()

    open_mean = next_open_return_mean or 0.0
    open_to_close_mean = next_open_to_close_return_mean or 0.0
    high_mean = next_high_return_mean or 0.0
    close_mean = next_close_return_mean or 0.0
    high_hit_rate = next_high_hit_rate or 0.0
    close_positive_hit_rate = next_close_positive_rate or 0.0

    if (
        evaluable_count >= WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT
        and high_hit_rate <= 0.0
        and close_positive_hit_rate <= 0.0
    ):
        return _build_execution_quality_zero_follow_through_result()

    if open_mean >= 0.02 and open_to_close_mean < 0:
        return _build_execution_quality_gap_chase_risk_result()
    if close_mean >= 0.02 and open_to_close_mean >= 0:
        return _build_execution_quality_close_continuation_result()
    if high_mean >= 0.03 and close_mean <= 0:
        return _build_execution_quality_intraday_only_result()
    return _build_execution_quality_balanced_confirmation_result()


def _demote_weak_near_miss_entries(
    near_miss_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    retained_near_misses: list[dict[str, Any]] = []
    demoted_to_opportunity_pool: list[dict[str, Any]] = []

    for entry in near_miss_entries:
        updated_entry = dict(entry)
        historical_prior = dict(updated_entry.get("historical_prior") or {})
        execution_quality_label = str(
            historical_prior.get("execution_quality_label") or "unknown"
        )
        evaluable_count = int(historical_prior.get("evaluable_count") or 0)
        next_high_hit_rate = _as_float(historical_prior.get("next_high_hit_rate"))
        next_close_positive_rate = _as_float(
            historical_prior.get("next_close_positive_rate")
        )
        next_open_to_close_return_mean = _as_float(
            historical_prior.get("next_open_to_close_return_mean")
        )
        if (
            execution_quality_label == "zero_follow_through"
            and evaluable_count >= WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT
        ):
            demoted_entry = dict(updated_entry)
            demoted_entry["demoted_from_decision"] = "near_miss"
            demoted_entry["reporting_bucket"] = "near_miss_weak_historical_demoted"
            demoted_entry["reporting_decision"] = "opportunity_pool"
            demoted_entry["promotion_trigger"] = (
                "History shows zero follow-through for this pattern, demoted to opportunity pool. "
                "Only consider if new strong pre-market confirmation appears."
            )
            top_reasons = [
                str(reason)
                for reason in list(demoted_entry.get("top_reasons") or [])
                if str(reason or "").strip()
            ]
            if "historical_zero_follow_through_near_miss_demoted" not in top_reasons:
                top_reasons.append("historical_zero_follow_through_near_miss_demoted")
            demoted_entry["top_reasons"] = top_reasons
            demoted_to_opportunity_pool.append(demoted_entry)
            continue

        if (
            execution_quality_label == "balanced_confirmation"
            and evaluable_count
            >= WEAK_BALANCED_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT
            and next_high_hit_rate
            <= WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE
            and next_close_positive_rate
            < WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE
            and next_open_to_close_return_mean < 0.0
        ):
            demoted_entry = dict(updated_entry)
            demoted_entry["demoted_from_decision"] = "near_miss"
            demoted_entry["reporting_bucket"] = "near_miss_weak_historical_demoted"
            demoted_entry["reporting_decision"] = "opportunity_pool"
            demoted_entry["promotion_trigger"] = (
                "Historical follow-through is very weak for this pattern, demoted to opportunity pool. "
                "Only consider if strong intraday confirmation appears after open."
            )
            top_reasons = [
                str(reason)
                for reason in list(demoted_entry.get("top_reasons") or [])
                if str(reason or "").strip()
            ]
            if "historical_weak_balanced_near_miss_demoted" not in top_reasons:
                top_reasons.append("historical_weak_balanced_near_miss_demoted")
            demoted_entry["top_reasons"] = top_reasons
            demoted_to_opportunity_pool.append(demoted_entry)
            continue

        retained_near_misses.append(updated_entry)

    return retained_near_misses, demoted_to_opportunity_pool


def _should_prune_weak_opportunity_pool_entry(historical_prior: dict[str, Any]) -> bool:
    prior = dict(historical_prior or {})
    execution_quality_label = str(prior.get("execution_quality_label") or "unknown")
    evaluable_count = int(prior.get("evaluable_count") or 0)
    if evaluable_count < WEAK_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT:
        return False
    next_high_hit_rate = _as_float(prior.get("next_high_hit_rate_at_threshold"))
    next_close_positive_rate = _as_float(prior.get("next_close_positive_rate"))
    next_open_to_close_return_mean = _as_float(
        prior.get("next_open_to_close_return_mean")
    )
    if (
        next_high_hit_rate <= 0.0
        and next_close_positive_rate <= 0.0
        and next_open_to_close_return_mean < 0.0
    ):
        return True
    return (
        execution_quality_label == "balanced_confirmation"
        and evaluable_count >= WEAK_BALANCED_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT
        and next_high_hit_rate <= WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE
        and next_close_positive_rate
        < WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE
        and next_open_to_close_return_mean < 0.0
    )
