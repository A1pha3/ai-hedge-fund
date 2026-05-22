from __future__ import annotations

from scripts.btst_round1_unclassified_split_helpers import (
    classify_unclassified_bucket,
    summarize_unclassified_recoverability,
)


def test_classify_unclassified_bucket_marks_rows_with_no_round1_features_as_missing_all_core_features() -> None:
    row = {
        "event_prototype": "unclassified",
        "breakout_freshness": None,
        "trend_acceleration": None,
        "volume_expansion_quality": None,
        "close_strength": None,
        "candidate_source": "layer_c_watchlist",
        "decision": "blocked",
    }

    assert classify_unclassified_bucket(row) == "missing_all_core_features"


def test_classify_unclassified_bucket_marks_rows_near_trend_threshold() -> None:
    row = {
        "event_prototype": "unclassified",
        "trend_acceleration": 0.53,
        "close_strength": 0.59,
        "breakout_freshness": 0.31,
        "volume_expansion_quality": 0.42,
        "candidate_source": "short_trade_boundary",
        "decision": "near_miss",
    }

    assert classify_unclassified_bucket(row) == "near_trend_threshold"


def test_summarize_unclassified_recoverability_flags_near_threshold_rows_as_recoverable() -> None:
    row = {
        "bucket": "near_breakout_threshold",
        "future_high_hit_15pct_2_5d": True,
        "max_future_high_return_2_5d": 0.16,
        "beta_tradeable": True,
        "gamma_closed_cycle": True,
    }

    verdict = summarize_unclassified_recoverability(row)

    assert verdict == "recover_threshold_near_miss"
