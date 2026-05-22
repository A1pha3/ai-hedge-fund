from __future__ import annotations

from scripts.btst_near_trend_threshold_recovery_helpers import (
    build_near_trend_recovery_candidate,
    summarize_near_trend_recovery_governance_verdict,
)


def test_build_near_trend_recovery_candidate_marks_rows_that_barely_miss_trend_classification() -> None:
    row = {
        "event_prototype": "unclassified",
        "bucket": "near_trend_threshold",
        "trend_acceleration": 0.53,
        "close_strength": 0.59,
        "beta_tradeable": True,
        "gamma_closed_cycle": True,
    }

    candidate = build_near_trend_recovery_candidate(row)

    assert candidate["is_recovery_candidate"] is True
    assert candidate["recovery_reason"] == "near_trend_threshold_window"


def test_build_near_trend_recovery_candidate_rejects_non_target_buckets() -> None:
    row = {
        "event_prototype": "unclassified",
        "bucket": "missing_all_core_features",
        "trend_acceleration": None,
        "close_strength": None,
    }

    candidate = build_near_trend_recovery_candidate(row)

    assert candidate["is_recovery_candidate"] is False


def test_summarize_near_trend_recovery_governance_verdict_advances_when_recovered_cohort_is_better_and_tradeable() -> None:
    verdict = summarize_near_trend_recovery_governance_verdict(
        recovered_hit_rate=0.60,
        recovered_mean_return=0.17,
        recovered_tradeable_rate=0.90,
        recovered_row_count=6,
        baseline_hit_rate=0.20,
        baseline_mean_return=0.08,
    )

    assert verdict == "advance_recovery_validation"
