from copy import deepcopy
from unittest.mock import patch

from src.screening.expected_return import compute_expected_returns
from src.screening.composite_score import (
    compute_composite_scores_for_recommendations,
)


def test_future_tracking_record_does_not_change_past_expected_return() -> None:
    records = [
        {
            "ticker": "A",
            "recommended_date": "20260601",
            "model_version": "v2",
            "recommendation_score": 0.5,
            "next_10day_return": 5.0,
        },
        {
            "ticker": "B",
            "recommended_date": "20260720",
            "model_version": "v2",
            "recommendation_score": 0.5,
            "next_10day_return": -99.0,
        },
    ]
    kwargs = dict(
        recommendations=[{"ticker": "X", "score_b": 0.5}],
        as_of="20260710",
        model_version="v2",
        history_records=records,
    )
    before = compute_expected_returns(**kwargs).to_dict()
    mutated = deepcopy(records)
    mutated[1]["next_10day_return"] = 999.0
    after = compute_expected_returns(
        **{**kwargs, "history_records": mutated}
    ).to_dict()
    assert before == after

    appended = records + [
        {
            "ticker": "C",
            "recommended_date": "20260721",
            "model_version": "v2",
            "recommendation_score": 0.5,
            "next_10day_return": 500.0,
        }
    ]
    after_append = compute_expected_returns(
        **{**kwargs, "history_records": appended}
    ).to_dict()
    assert before == after_append


def test_other_model_version_is_not_pooled() -> None:
    records = [
        {
            "ticker": "A",
            "recommended_date": "20260601",
            "model_version": "old",
            "recommendation_score": 0.5,
            "next_10day_return": 100.0,
        }
    ]
    report = compute_expected_returns(
        recommendations=[{"ticker": "X", "score_b": 0.5}],
        as_of="20260710",
        model_version="new",
        history_records=records,
    )
    assert report.total_samples == 0


def test_unmatured_label_is_not_used_before_as_of() -> None:
    report = compute_expected_returns(
        recommendations=[{"ticker": "X", "score_b": 0.5}],
        as_of="2026-07-10T15:00:00+08:00",
        model_version="v2",
        history_records=[
            {
                "ticker": "A",
                "recommended_date": "20260701",
                "model_version": "v2",
                "recommendation_score": 0.5,
                "next_10day_return": 100.0,
            }
        ],
    )

    assert report.total_samples == 1
    assert report.items[0].expected_returns["t10"] is None


def test_trading_day_label_does_not_mature_over_a_weekend() -> None:
    report = compute_expected_returns(
        recommendations=[{"ticker": "X", "score_b": 0.5}],
        as_of="20260714",
        model_version="v2",
        history_records=[
            {
                "ticker": "A",
                "recommended_date": "20260708",
                "model_version": "v2",
                "recommendation_score": 0.5,
                "next_5day_return": 100.0,
            }
        ],
    )
    assert report.items[0].expected_returns["t5"] is None


def test_label_maturity_fails_closed_across_exchange_holidays() -> None:
    report = compute_expected_returns(
        recommendations=[{"ticker": "X", "score_b": 0.5}],
        as_of="20261012",
        model_version="v2",
        history_records=[
            {
                "ticker": "A",
                "recommended_date": "20260930",
                "model_version": "v2",
                "recommendation_score": 0.5,
                "next_5day_return": 100.0,
            }
        ],
    )
    assert report.items[0].expected_returns["t5"] is None


def test_compact_timestamp_as_of_is_normalized_without_utc_date_shift() -> None:
    report = compute_expected_returns(
        recommendations=[{"ticker": "X", "score_b": 0.5}],
        as_of="20260710T233000-0400",
        model_version="v2",
        history_records=[
            {
                "ticker": "A",
                "recommended_date": "20260601",
                "model_version": "v2",
                "recommendation_score": 0.5,
                "next_10day_return": 5.0,
            }
        ],
    )
    assert report.trade_date == "20260710"
    assert report.total_samples == 1


def test_malformed_record_date_fails_closed() -> None:
    report = compute_expected_returns(
        recommendations=[{"ticker": "X", "score_b": 0.5}],
        as_of="20260710",
        model_version="v2",
        history_records=[
            {
                "ticker": "A",
                "recommended_date": "not-a-date",
                "model_version": "v2",
                "recommendation_score": 0.5,
                "next_10day_return": 100.0,
            }
        ],
    )
    assert report.total_samples == 0


def test_date_with_arbitrary_suffix_fails_closed() -> None:
    report = compute_expected_returns(
        recommendations=[{"ticker": "X", "score_b": 0.5}],
        as_of="20260710future",
        model_version="v2",
        history_records=[],
    )
    assert report.trade_date == ""
    assert report.total_samples == 0


def test_partial_strict_expected_return_arguments_do_not_read_latest() -> None:
    with patch(
        "src.screening.expected_return._load_tracking_records",
        side_effect=AssertionError("latest history must not be read"),
    ):
        report = compute_expected_returns(
            recommendations=[{"ticker": "X", "score_b": 0.5}],
            as_of="20260710",
        )
    assert report.total_samples == 0


def test_future_history_report_does_not_change_past_composite() -> None:
    history = [
        {
            "date": "20260709",
            "recommendations": [
                {"ticker": "X", "score_b": 0.4, "volume": 100.0}
            ],
        },
        {
            "date": "20260720",
            "recommendations": [
                {"ticker": "X", "score_b": 0.0, "volume": 1.0}
            ],
        },
    ]
    kwargs = dict(
        recommendations=[{"ticker": "X", "score_b": 0.5, "volume": 120.0}],
        trade_date="20260710",
        as_of="20260710",
        history_reports=history,
    )
    before = compute_composite_scores_for_recommendations(**kwargs).to_dict()
    mutated = deepcopy(history)
    mutated[1]["recommendations"][0].update(score_b=1.0, volume=1_000_000.0)
    after = compute_composite_scores_for_recommendations(
        **{**kwargs, "history_reports": mutated}
    ).to_dict()
    assert before == after


    appended = history + [
        {
            "date": "20260721",
            "recommendations": [
                {"ticker": "X", "score_b": 1.0, "volume": 1_000_000.0}
            ],
        }
    ]
    after_append = compute_composite_scores_for_recommendations(
        **{**kwargs, "history_reports": appended}
    ).to_dict()
    assert before == after_append


def test_malformed_composite_history_date_fails_closed() -> None:
    report = compute_composite_scores_for_recommendations(
        recommendations=[{"ticker": "X", "score_b": 0.5, "volume": 120.0}],
        trade_date="20260710",
        as_of="20260710",
        history_reports=[
            {
                "date": "bad-date",
                "recommendations": [
                    {"ticker": "X", "score_b": 0.0, "volume": 1.0}
                ],
            }
        ],
    )
    item = report.items[0]
    assert item.momentum_bonus == 0.0
    assert item.volume_factor == 0.0
    assert item.trend_resonance_factor == 0.0


def test_missing_current_volume_does_not_reuse_last_historical_volume() -> None:
    report = compute_composite_scores_for_recommendations(
        recommendations=[{"ticker": "X", "score_b": 0.5}],
        trade_date="20260710",
        as_of="20260710",
        history_reports=[
            {
                "date": "20260708",
                "recommendations": [
                    {"ticker": "X", "score_b": 0.4, "volume": 100.0}
                ],
            },
            {
                "date": "20260709",
                "recommendations": [
                    {"ticker": "X", "score_b": 0.45, "volume": 200.0}
                ],
            },
        ],
    )
    assert report.items[0].volume_factor == 0.0
