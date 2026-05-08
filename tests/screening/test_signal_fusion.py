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
