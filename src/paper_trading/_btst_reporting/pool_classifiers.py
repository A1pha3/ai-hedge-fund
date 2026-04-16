"""
Opportunity pool classification, pruning, and demotion logic.

Functions here decide whether an opportunity-pool entry should be retained,
pruned, rebucketed as no-history observer, or flagged as risky — based on
historical execution quality metrics.
"""

from __future__ import annotations

from typing import Any

from src.paper_trading.btst_reporting_utils import (
    LOW_SCORE_NO_HISTORY_UPSTREAM_MAX_SCORE_TARGET,
    MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_BREAKOUT_FRESHNESS,
    MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE,
    MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE,
    MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_SCORE_TARGET,
    MIXED_BOUNDARY_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT,
    RISKY_OBSERVER_EXECUTION_QUALITY_LABELS,
    WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE,
    WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE,
    WEAK_BALANCED_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT,
    WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT,
    WEAK_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT,
    _as_float,
)


# ---------------------------------------------------------------------------
# Near-miss demotion
# ---------------------------------------------------------------------------

def _should_demote_weak_near_miss(historical_prior: dict[str, Any] | None) -> bool:
    prior = dict(historical_prior or {})
    evaluable_count = int(prior.get("evaluable_count") or 0)
    if evaluable_count < WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT:
        return False
    next_high_hit_rate = _as_float(prior.get("next_high_hit_rate_at_threshold"))
    next_close_positive_rate = _as_float(prior.get("next_close_positive_rate"))
    return next_high_hit_rate <= 0.0 and next_close_positive_rate <= 0.0


def _demote_weak_near_miss_entries(
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    retained_entries: list[dict[str, Any]] = []
    updated_opportunity_pool_entries = list(opportunity_pool_entries)
    for entry in near_miss_entries:
        historical_prior = dict(entry.get("historical_prior") or {})
        if not _should_demote_weak_near_miss(historical_prior):
            retained_entries.append(entry)
            continue

        demoted_entry = dict(entry)
        demoted_prior = dict(historical_prior)
        demoted_prior["demoted_from_near_miss"] = True
        demoted_prior["demotion_reason"] = "historical_zero_follow_through"
        demoted_prior["summary"] = (
            (demoted_prior.get("summary") or "")
            + (" " if demoted_prior.get("summary") else "")
            + "历史同层兑现为 0，降级到机会池等待新增强度。"
        )
        demoted_entry["historical_prior"] = demoted_prior
        demoted_entry["demoted_from_decision"] = "near_miss"
        demoted_entry["reporting_bucket"] = "opportunity_pool_demoted"
        demoted_entry["reporting_decision"] = "opportunity_pool"
        demoted_entry["promotion_trigger"] = (
            "历史同层兑现极弱，先降为机会池；只有盘中新强度确认时再考虑回到观察层。"
        )
        top_reasons = [
            str(reason)
            for reason in list(demoted_entry.get("top_reasons") or [])
            if str(reason or "").strip()
        ]
        if "historical_zero_follow_through_demoted" not in top_reasons:
            top_reasons.append("historical_zero_follow_through_demoted")
        demoted_entry["top_reasons"] = top_reasons
        updated_opportunity_pool_entries.append(demoted_entry)
    return retained_entries, updated_opportunity_pool_entries


# ---------------------------------------------------------------------------
# Pruning predicates
# ---------------------------------------------------------------------------

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


def _should_prune_mixed_boundary_opportunity_pool_entry(
    entry: dict[str, Any], historical_prior: dict[str, Any]
) -> bool:
    prior = dict(historical_prior or {})
    if str(entry.get("candidate_source") or "") != "short_trade_boundary":
        return False
    if (
        str(prior.get("execution_quality_label") or "unknown")
        != "balanced_confirmation"
    ):
        return False
    if str(prior.get("applied_scope") or "none") != "family_source_score_catalyst":
        return False
    evaluable_count = int(prior.get("evaluable_count") or 0)
    if evaluable_count < MIXED_BOUNDARY_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT:
        return False
    top_reasons = {
        str(reason or "").strip()
        for reason in list(entry.get("top_reasons") or [])
        if str(reason or "").strip()
    }
    if "profitability_hard_cliff" not in top_reasons:
        return False
    if (
        _as_float(entry.get("score_target"))
        >= MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_SCORE_TARGET
    ):
        return False
    breakout_freshness = _as_float(
        (entry.get("metrics") or {}).get("breakout_freshness")
    )
    next_high_hit_rate = _as_float(prior.get("next_high_hit_rate_at_threshold"))
    next_close_positive_rate = _as_float(prior.get("next_close_positive_rate"))
    return (
        breakout_freshness < MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_BREAKOUT_FRESHNESS
        and next_high_hit_rate <= MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE
        and next_close_positive_rate
        <= MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE
    )


def _should_rebucket_no_history_opportunity_pool_entry(
    historical_prior: dict[str, Any],
) -> bool:
    prior = dict(historical_prior or {})
    execution_quality_label = str(prior.get("execution_quality_label") or "unknown")
    evaluable_count = int(prior.get("evaluable_count") or 0)
    applied_scope = str(prior.get("applied_scope") or "none")
    return (
        execution_quality_label == "unknown"
        and evaluable_count <= 0
        and applied_scope == "none"
    )


def _should_prune_low_score_no_history_opportunity_pool_entry(
    entry: dict[str, Any], historical_prior: dict[str, Any]
) -> bool:
    if not _should_rebucket_no_history_opportunity_pool_entry(historical_prior):
        return False
    if str(entry.get("candidate_source") or "") != "upstream_liquidity_corridor_shadow":
        return False
    top_reasons = {
        str(reason or "").strip()
        for reason in list(entry.get("top_reasons") or [])
        if str(reason or "").strip()
    }
    if "prepared_breakout" not in top_reasons or "confirmed_breakout" in top_reasons:
        return False
    if not any(reason.startswith("score_short=") for reason in top_reasons):
        return False
    return (
        _as_float(entry.get("score_target"))
        < LOW_SCORE_NO_HISTORY_UPSTREAM_MAX_SCORE_TARGET
    )


def _should_prune_weak_catalyst_no_history_opportunity_pool_entry(
    entry: dict[str, Any], historical_prior: dict[str, Any]
) -> bool:
    if not _should_rebucket_no_history_opportunity_pool_entry(historical_prior):
        return False
    if str(entry.get("candidate_source") or "") != "catalyst_theme":
        return False
    top_reasons = {
        str(reason or "").strip()
        for reason in list(entry.get("top_reasons") or [])
        if str(reason or "").strip()
    }
    return (
        "confirmed_breakout" in top_reasons
        and "profitability_hard_cliff" not in top_reasons
    )


# ---------------------------------------------------------------------------
# Entry builder helper
# ---------------------------------------------------------------------------

def _build_reporting_bucket_entry(
    entry: dict[str, Any],
    historical_prior: dict[str, Any],
    *,
    bucket: str,
    flag_key: str,
    reason_key: str,
    reason_value: str,
    summary_suffix: str,
    promotion_trigger: str,
    top_reason: str | None = None,
) -> dict[str, Any]:
    updated_entry = dict(entry)
    updated_prior = dict(historical_prior)
    updated_prior[flag_key] = True
    updated_prior[reason_key] = reason_value
    updated_prior["summary"] = (
        (updated_prior.get("summary") or "")
        + (" " if updated_prior.get("summary") else "")
        + summary_suffix
    )
    updated_entry["historical_prior"] = updated_prior
    updated_entry["reporting_bucket"] = bucket
    updated_entry["promotion_trigger"] = promotion_trigger
    if top_reason:
        top_reasons = [
            str(reason)
            for reason in list(updated_entry.get("top_reasons") or [])
            if str(reason or "").strip()
        ]
        if top_reason not in top_reasons:
            top_reasons.append(top_reason)
        updated_entry["top_reasons"] = top_reasons
    return updated_entry


# ---------------------------------------------------------------------------
# Classification dispatchers
# ---------------------------------------------------------------------------

def _classify_opportunity_pool_entry(
    *,
    updated_entry: dict[str, Any],
    historical_prior: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    pruned_bucket = _classify_pruned_opportunity_pool_entry(
        updated_entry, historical_prior
    )
    if pruned_bucket is not None:
        return pruned_bucket

    no_history_bucket = _classify_no_history_opportunity_pool_entry(
        updated_entry, historical_prior
    )
    if no_history_bucket is not None:
        return no_history_bucket

    risky_bucket = _classify_risky_opportunity_pool_entry(
        updated_entry, historical_prior
    )
    if risky_bucket is not None:
        return risky_bucket
    return "retained", updated_entry


def _classify_pruned_opportunity_pool_entry(
    updated_entry: dict[str, Any],
    historical_prior: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    if _should_prune_weak_opportunity_pool_entry(historical_prior):
        return "weak_history_pruned", _build_reporting_bucket_entry(
            updated_entry,
            historical_prior,
            bucket="weak_history_pruned",
            flag_key="pruned_from_opportunity_pool",
            reason_key="prune_reason",
            reason_value="historical_zero_follow_through",
            summary_suffix="历史兑现接近 0，已从机会池移除。",
            promotion_trigger="历史兑现接近 0，不进入机会池；除非后续出现新的独立强确认，否则只保留低优先级影子观察。",
            top_reason="historical_zero_follow_through_pruned",
        )
    if _should_prune_low_score_no_history_opportunity_pool_entry(
        updated_entry, historical_prior
    ):
        return "weak_history_pruned", _build_reporting_bucket_entry(
            updated_entry,
            historical_prior,
            bucket="weak_history_pruned",
            flag_key="pruned_from_opportunity_pool",
            reason_key="prune_reason",
            reason_value="no_history_low_score_prepared_breakout",
            summary_suffix="暂无可评估历史先验，且当前仅是低分 prepared-breakout，已移出观察桶。",
            promotion_trigger="缺少历史先验且当前分数/形态偏弱，不保留在观察桶；除非后续出现新的独立强确认，否则不再继续跟踪。",
            top_reason="no_history_low_score_pruned",
        )
    if _should_prune_mixed_boundary_opportunity_pool_entry(
        updated_entry, historical_prior
    ):
        return "weak_history_pruned", _build_reporting_bucket_entry(
            updated_entry,
            historical_prior,
            bucket="weak_history_pruned",
            flag_key="pruned_from_opportunity_pool",
            reason_key="prune_reason",
            reason_value="mixed_boundary_follow_through",
            summary_suffix="同层同源同分桶历史仅属混合延续质量，且当前仍受 profitability_hard_cliff 压制，已移出标准机会池。",
            promotion_trigger="历史延续质量只有中性混合，且当前仍受 profitability_hard_cliff 压制；除非后续出现新的独立强确认，否则不再占用标准机会池名额。",
            top_reason="mixed_boundary_follow_through_pruned",
        )
    if _should_prune_weak_catalyst_no_history_opportunity_pool_entry(
        updated_entry, historical_prior
    ):
        return "weak_history_pruned", _build_reporting_bucket_entry(
            updated_entry,
            historical_prior,
            bucket="weak_history_pruned",
            flag_key="pruned_from_opportunity_pool",
            reason_key="prune_reason",
            reason_value="catalyst_no_history_without_profitability_support",
            summary_suffix="暂无可评估历史先验，且题材 confirmed-breakout 缺少 profitability_hard_cliff 支撑，已移出观察桶。",
            promotion_trigger="缺少历史先验且题材强度支撑不足，不保留在观察桶；除非后续出现新的独立强确认，否则不再继续跟踪。",
            top_reason="catalyst_no_history_pruned",
        )
    return None


def _classify_no_history_opportunity_pool_entry(
    updated_entry: dict[str, Any],
    historical_prior: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    if _should_rebucket_no_history_opportunity_pool_entry(historical_prior):
        return "no_history_observer", _build_reporting_bucket_entry(
            updated_entry,
            historical_prior,
            bucket="no_history_observer",
            flag_key="rebucketed_from_opportunity_pool",
            reason_key="rebucket_reason",
            reason_value="no_evaluable_history",
            summary_suffix="暂无可评估历史先验，已移入 no-history observer。",
            promotion_trigger="暂无可评估历史先验；只有盘中新证据显著增强时，才允许从 no-history observer 升级。",
            top_reason="no_history_observer_rebucket",
        )
    return None


def _classify_risky_opportunity_pool_entry(
    updated_entry: dict[str, Any],
    historical_prior: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    if (
        str(historical_prior.get("execution_quality_label") or "unknown")
        in RISKY_OBSERVER_EXECUTION_QUALITY_LABELS
    ):
        risky_entry = dict(updated_entry)
        risky_entry["reporting_bucket"] = "risky_observer"
        risky_entry["promotion_trigger"] = (
            "只做高风险盘中确认观察，不作为标准 BTST 机会池升级对象。"
        )
        return "risky_observer", risky_entry
    return None


# ---------------------------------------------------------------------------
# Top-level partitioner
# ---------------------------------------------------------------------------

def _partition_opportunity_pool_entries(
    opportunity_pool_entries: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    retained_entries: list[dict[str, Any]] = []
    no_history_observer_entries: list[dict[str, Any]] = []
    risky_observer_entries: list[dict[str, Any]] = []
    pruned_entries: list[dict[str, Any]] = []

    for entry in opportunity_pool_entries:
        updated_entry = dict(entry)
        historical_prior = dict(updated_entry.get("historical_prior") or {})
        bucket_name, bucket_entry = _classify_opportunity_pool_entry(
            updated_entry=updated_entry,
            historical_prior=historical_prior,
        )
        if bucket_name == "weak_history_pruned":
            pruned_entries.append(bucket_entry)
            continue
        if bucket_name == "no_history_observer":
            no_history_observer_entries.append(bucket_entry)
            continue
        if bucket_name == "risky_observer":
            risky_observer_entries.append(bucket_entry)
            continue
        retained_entries.append(bucket_entry)

    return (
        retained_entries,
        no_history_observer_entries,
        risky_observer_entries,
        pruned_entries,
    )
