from __future__ import annotations

import pytest

from src.screening.models import MarketState, StrategySignal
from src.screening.signal_fusion import fuse_batch, fuse_signals_for_ticker


def test_fuse_signals_for_ticker_preserves_sub_factor_raw_metrics() -> None:
    fused = fuse_signals_for_ticker(
        "300999",
        signals={
            "trend": StrategySignal(
                direction=1,
                confidence=75.0,
                completeness=1.0,
                sub_factors={
                    "momentum": {
                        "direction": 1,
                        "confidence": 88.0,
                        "completeness": 1.0,
                        "metrics": {
                            "failed_breakout_10": 3,
                            "close_structure": 0.30,
                            "amount_ratio_5": 2.14,
                        },
                    }
                },
            )
        },
        market_state=MarketState(),
    )

    assert fused.metrics == {
        "failed_breakout_10": 3,
        "close_structure": 0.30,
        "amount_ratio_5": 2.14,
    }


def test_fuse_batch_computes_cross_sectional_attention_composite() -> None:
    fused_scores = fuse_batch(
        {
            "000001": {
                "trend": StrategySignal(
                    direction=1,
                    confidence=70.0,
                    completeness=1.0,
                    sub_factors={
                        "momentum": {
                            "direction": 1,
                            "confidence": 70.0,
                            "completeness": 1.0,
                            "metrics": {
                                "turnover_ratio_20": 1.0,
                                "amount_ratio_5": 1.0,
                                "ret_2d": 0.01,
                                "ret_5d": 0.02,
                            },
                        }
                    },
                )
            },
            "000002": {
                "trend": StrategySignal(
                    direction=1,
                    confidence=70.0,
                    completeness=1.0,
                    sub_factors={
                        "momentum": {
                            "direction": 1,
                            "confidence": 70.0,
                            "completeness": 1.0,
                            "metrics": {
                                "turnover_ratio_20": 2.0,
                                "amount_ratio_5": 2.0,
                                "ret_2d": 0.03,
                                "ret_5d": 0.05,
                            },
                        }
                    },
                )
            },
            "000003": {
                "trend": StrategySignal(
                    direction=1,
                    confidence=70.0,
                    completeness=1.0,
                    sub_factors={
                        "momentum": {
                            "direction": 1,
                            "confidence": 70.0,
                            "completeness": 1.0,
                            "metrics": {
                                "turnover_ratio_20": 3.0,
                                "amount_ratio_5": 3.0,
                                "ret_2d": 0.05,
                                "ret_5d": 0.08,
                            },
                        }
                    },
                )
            },
        },
        market_state=MarketState(),
    )

    metrics_by_ticker = {item.ticker: item.metrics for item in fused_scores}
    assert metrics_by_ticker["000001"]["attention_composite"] == pytest.approx(1.0 / 3.0, abs=1e-4)
    assert metrics_by_ticker["000002"]["attention_composite"] == pytest.approx(2.0 / 3.0, abs=1e-4)
    assert metrics_by_ticker["000003"]["attention_composite"] == pytest.approx(1.0, abs=1e-4)


def test_fuse_batch_propagates_name_and_industry_from_candidates() -> None:
    """fuse_batch should propagate name and industry_sw from CandidateStock list."""
    from src.screening.models import CandidateStock

    candidates = [
        CandidateStock(ticker="000001", name="平安银行", industry_sw="银行"),
        CandidateStock(ticker="000002", name="万科A", industry_sw="房地产"),
    ]
    fused_scores = fuse_batch(
        {
            "000001": {
                "trend": StrategySignal(
                    direction=1, confidence=70.0, completeness=1.0, sub_factors={}
                )
            },
            "000002": {
                "trend": StrategySignal(
                    direction=1, confidence=70.0, completeness=1.0, sub_factors={}
                )
            },
        },
        market_state=MarketState(),
        candidates=candidates,
    )

    by_ticker = {f.ticker: f for f in fused_scores}
    assert by_ticker["000001"].name == "平安银行"
    assert by_ticker["000001"].industry_sw == "银行"
    assert by_ticker["000002"].name == "万科A"
    assert by_ticker["000002"].industry_sw == "房地产"


def test_fuse_batch_without_candidates_leaves_name_industry_empty() -> None:
    """fuse_batch without candidates parameter should still work (backward compat)."""
    fused_scores = fuse_batch(
        {
            "000001": {
                "trend": StrategySignal(
                    direction=1, confidence=70.0, completeness=1.0, sub_factors={}
                )
            }
        },
        market_state=MarketState(),
    )
    assert fused_scores[0].name == ""
    assert fused_scores[0].industry_sw == ""


def test_fuse_batch_ignores_candidates_not_in_signals() -> None:
    """Candidates whose tickers have no signals should be silently ignored."""
    from src.screening.models import CandidateStock

    candidates = [
        CandidateStock(ticker="000001", name="在池中", industry_sw="银行"),
        CandidateStock(ticker="000999", name="未评分", industry_sw="—"),
    ]
    fused_scores = fuse_batch(
        {
            "000001": {
                "trend": StrategySignal(
                    direction=1, confidence=70.0, completeness=1.0, sub_factors={}
                )
            }
        },
        market_state=MarketState(),
        candidates=candidates,
    )
    assert len(fused_scores) == 1
    assert fused_scores[0].name == "在池中"
