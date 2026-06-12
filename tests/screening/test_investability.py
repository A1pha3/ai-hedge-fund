"""Tests for investability ranking helpers."""

from __future__ import annotations

from src.screening.composite_score import CompositeEntry, CompositeReport
from src.screening.expected_return import ExpectedReturn, ExpectedReturnReport
from src.screening.investability import rank_recommendations_by_investability


def test_rank_recommendations_prefers_30d_edge_when_composite_ties() -> None:
    recommendations = [
        {"ticker": "000001", "name": "Alpha", "score_b": 0.70},
        {"ticker": "000002", "name": "Beta", "score_b": 0.71},
        {"ticker": "000003", "name": "Gamma", "score_b": 0.69},
    ]
    composite = CompositeReport(
        trade_date="20260612",
        items=[
            CompositeEntry(ticker="000001", name="Alpha", base_score=0.70, composite_score=0.85),
            CompositeEntry(ticker="000002", name="Beta", base_score=0.71, composite_score=0.85),
            CompositeEntry(ticker="000003", name="Gamma", base_score=0.69, composite_score=0.82),
        ],
    )
    expected = ExpectedReturnReport(
        trade_date="20260612",
        lookback_days=60,
        total_samples=120,
        items=[
            ExpectedReturn(
                ticker="000001",
                score_b=0.70,
                bucket_label="高 (>0.8)",
                bucket_sample_count=40,
                expected_returns={"t1": 1.0, "t5": 2.0, "t10": 3.0, "t20": 6.0, "t30": 7.0},
                win_rates={"t1": 0.55, "t5": 0.56, "t10": 0.57, "t20": 0.58, "t30": 0.59},
            ),
            ExpectedReturn(
                ticker="000002",
                score_b=0.71,
                bucket_label="高 (>0.8)",
                bucket_sample_count=45,
                expected_returns={"t1": 1.0, "t5": 2.0, "t10": 3.0, "t20": 6.0, "t30": 9.0},
                win_rates={"t1": 0.55, "t5": 0.56, "t10": 0.57, "t20": 0.60, "t30": 0.62},
            ),
            ExpectedReturn(
                ticker="000003",
                score_b=0.69,
                bucket_label="中高 (0.7-0.8)",
                bucket_sample_count=60,
                expected_returns={"t1": 1.0, "t5": 1.5, "t10": 2.0, "t20": 4.0, "t30": 5.0},
                win_rates={"t1": 0.54, "t5": 0.55, "t10": 0.56, "t20": 0.57, "t30": 0.58},
            ),
        ],
    )

    ranked = rank_recommendations_by_investability(recommendations, composite, expected)

    assert [item["ticker"] for item in ranked] == ["000002", "000001", "000003"]
    assert ranked[0]["composite_score"] == 0.85
    assert ranked[0]["expected_returns"]["t30"] == 9.0
    assert ranked[0]["win_rates"]["t30"] == 0.62
    assert ranked[0]["bucket_sample_count"] == 45
    assert ranked[0]["composite_grade"] == "A"
