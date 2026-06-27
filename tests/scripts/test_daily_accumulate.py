"""Daily accumulate progress tracking 测试."""
from __future__ import annotations

from unittest.mock import patch

from scripts.daily_accumulate import (
    POWER_THRESHOLD,
    get_accumulation_progress,
)


@patch("src.screening.consecutive_recommendation.resolve_report_dir")
@patch("src.screening.consecutive_recommendation.load_tracking_history")
def test_progress_returns_expected_fields(mock_load, mock_dir):
    mock_dir.return_value = "fake"
    mock_load.return_value = [
        {"recommendation_score": 0.55, "next_30day_return": 5.0, "score_decomposition": {"base_contributions": {"T": 0.3}}},
        {"recommendation_score": 0.20, "next_30day_return": -3.0},
    ]
    result = get_accumulation_progress()
    assert result["total_records"] == 2
    assert result["with_decomposition"] == 1
    assert result["high_bucket_matured"] == 1
    assert result["target"] == POWER_THRESHOLD


@patch("src.screening.consecutive_recommendation.resolve_report_dir")
@patch("src.screening.consecutive_recommendation.load_tracking_history")
def test_progress_empty_tracking_history(mock_load, mock_dir):
    mock_dir.return_value = "fake"
    mock_load.return_value = []
    result = get_accumulation_progress()
    assert result["total_records"] == 0
    assert result["high_bucket_pct"] == 0


@patch("src.screening.consecutive_recommendation.resolve_report_dir")
@patch("src.screening.consecutive_recommendation.load_tracking_history")
def test_progress_counts_only_matured_high(mock_load, mock_dir):
    mock_dir.return_value = "fake"
    mock_load.return_value = [
        {"recommendation_score": 0.55, "next_30day_return": None},
        {"recommendation_score": 0.55, "next_30day_return": 5.0},
        {"recommendation_score": 0.10, "next_30day_return": 3.0},
    ]
    result = get_accumulation_progress()
    assert result["high_bucket_matured"] == 1


def test_power_threshold_is_317():
    assert POWER_THRESHOLD == 317
