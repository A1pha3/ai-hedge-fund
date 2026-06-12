"""Tests for investability ranking helpers."""

from __future__ import annotations

from src.screening.composite_score import CompositeEntry, CompositeReport
from src.screening.expected_return import ExpectedReturn, ExpectedReturnReport
from src.screening.investability import (
    build_front_door_verdict,
    rank_recommendations_by_investability,
    select_representative_candidates,
)


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


def test_select_representative_candidates_prefers_unique_industry_clusters() -> None:
    ranked = [
        {"ticker": "000001", "industry_sw": "电子", "composite_score": 0.82},
        {"ticker": "000002", "industry_sw": "电子", "composite_score": 0.79},
        {"ticker": "000003", "industry_sw": "银行", "composite_score": 0.76},
        {"ticker": "000004", "industry_sw": "医药", "composite_score": 0.72},
    ]

    selected = select_representative_candidates(ranked, count=3)

    assert [item["ticker"] for item in selected] == ["000001", "000003", "000004"]
    assert selected[0]["cluster_label"] == "电子"
    assert selected[0]["cluster_size"] == 2
    assert selected[0]["cluster_alternatives"] == ["000002"]


def test_select_representative_candidates_backfills_duplicates_when_clusters_insufficient() -> None:
    ranked = [
        {"ticker": "000001", "industry_sw": "电子", "composite_score": 0.82},
        {"ticker": "000002", "industry_sw": "电子", "composite_score": 0.79},
        {"ticker": "000003", "industry_sw": "银行", "composite_score": 0.76},
    ]

    selected = select_representative_candidates(ranked, count=3)

    assert [item["ticker"] for item in selected] == ["000001", "000003", "000002"]


def test_build_front_door_verdict_promotes_high_quality_pick_to_buy() -> None:
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            "expected_returns": {"t30": 9.4},
            "win_rates": {"t30": 0.63},
            "bucket_sample_count": 48,
            "momentum_bonus": 0.05,
            "sector_bonus": 0.03,
            "consistency_adj": 0.02,
            "volume_factor": 0.01,
            "trend_resonance_factor": 0.04,
        },
        market_regime="trend",
    )

    assert verdict["action"] == "BUY"
    assert "edge" in verdict["invalidation_reason"]


def test_build_front_door_verdict_respects_risk_off_gate() -> None:
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.71,
            "expected_returns": {"t30": 11.2},
            "win_rates": {"t30": 0.66},
            "bucket_sample_count": 52,
        },
        market_regime="risk_off",
    )

    assert verdict["action"] == "HOLD"
