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


def test_attention_composite_ignores_nan_metric_values() -> None:
    """NaN/Inf 因子值不应污染横截面分位数排序。

    被污染的 ticker 既不应获得任意 percentile, 其他 ticker 的排名也不应被
    NaN 在排序中的不确定位置干扰。
    """
    import math

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
            "000002": {  # NaN values across the board — should not be ranked
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
                                "turnover_ratio_20": float("nan"),
                                "amount_ratio_5": float("inf"),
                                "ret_2d": float("nan"),
                                "ret_5d": float("nan"),
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

    # 000002 had only NaN/Inf metrics. Either no attention_composite is computed,
    # or it is finite and meaningless to compare. The critical invariant is that
    # 000002 MUST NOT take a percentile slot ahead of a valid ticker
    # (000001 has real metrics — without filtering, 000002 currently steals rank 2/3).
    composite_001 = metrics_by_ticker["000001"].get("attention_composite")
    composite_003 = metrics_by_ticker["000003"].get("attention_composite")
    composite_002 = metrics_by_ticker["000002"].get("attention_composite")

    # 000001 and 000003 are the only two valid tickers; with N=2 valid values,
    # 000001 should get percentile 0.5 (lowest rank) and 000003 should get 1.0.
    assert composite_001 is not None and math.isfinite(composite_001)
    assert composite_003 is not None and math.isfinite(composite_003)
    assert composite_001 == pytest.approx(0.5, abs=1e-4), (
        f"With NaN filtered, 000001 must be rank 1/2 (percentile 0.5); got {composite_001}"
    )
    assert composite_003 == pytest.approx(1.0, abs=1e-4), (
        f"With NaN filtered, 000003 must be rank 2/2 (percentile 1.0); got {composite_003}"
    )
    # 000002 either has no composite, or it's not in (0.0, 1.0]
    if composite_002 is not None:
        assert math.isfinite(composite_002)
