from __future__ import annotations

import pytest

from src.screening.models import FusedScore, MarketState, StrategySignal
from src.screening.signal_fusion import compute_score_decomposition, fuse_batch, fuse_signals_for_ticker


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


# ---------------------------------------------------------------------------
# ALPHA-R20.11: consensus_bonus decomposition regression tests
# ---------------------------------------------------------------------------


def _make_fused_for_decomposition(*, score_b: float, arbitration_applied: list[str], weights_used: dict[str, float] | None = None) -> FusedScore:
    """Build a minimal FusedScore for testing compute_score_decomposition."""
    return FusedScore(
        ticker="TEST",
        score_b=score_b,
        strategy_signals={
            "trend": StrategySignal(
                direction=1 if score_b >= 0 else -1,
                confidence=70.0,
                completeness=1.0,
                sub_factors={},
            ),
        },
        metrics={},
        arbitration_applied=arbitration_applied,
        market_state=MarketState(),
        weights_used=weights_used or {"trend": 1.0},
        decision="watch" if score_b >= 0.35 else "neutral",
    )


def test_compute_score_decomposition_recognizes_bullish_consensus_bonus() -> None:
    """ALPHA-R20.11: ``arbitration_applied`` contains the bare enum value
    ``"consensus_bonus"`` (not ``"consensus_bonus_bullish"``).  The decomposition
    must infer direction from the sign of ``fused.score_b`` and surface the
    corresponding +0.05 / -0.05 contribution.  Previously, the decomposition
    always returned 0 because it looked for nonexistent _bullish / _bearish
    suffix strings."""
    fused = _make_fused_for_decomposition(score_b=0.30, arbitration_applied=["consensus_bonus"])
    decomp = compute_score_decomposition(fused)
    # base contribution from trend with full weight is 0.70; consensus bonus adds 0.05
    # total = 0.70 + 0.05 = 0.75.  The key invariant is consensus_bonus == +0.05.
    assert decomp["consensus_bonus"] == pytest.approx(0.05)
    assert decomp["base_contributions"]["trend"] == pytest.approx(0.70)


def test_compute_score_decomposition_recognizes_bearish_consensus_bonus() -> None:
    """ALPHA-R20.11: bearish consensus (score_b < 0) yields a -0.05 contribution."""
    fused = _make_fused_for_decomposition(score_b=-0.30, arbitration_applied=["consensus_bonus"])
    decomp = compute_score_decomposition(fused)
    assert decomp["consensus_bonus"] == pytest.approx(-0.05)
    assert decomp["base_contributions"]["trend"] == pytest.approx(-0.70)


def test_compute_score_decomposition_no_consensus_bonus_when_arb_absent() -> None:
    """ALPHA-R20.11: when ``consensus_bonus`` is not in arbitration_applied,
    the consensus_bonus decomposition must be 0."""
    fused = _make_fused_for_decomposition(score_b=0.30, arbitration_applied=["risk_off"])
    decomp = compute_score_decomposition(fused)
    assert decomp["consensus_bonus"] == 0.0


# ---------------------------------------------------------------------------
# R20.16 Beta bug-fix regression tests: breadth_ratio / position_scale
# x-or-default falsy-value folding
# ---------------------------------------------------------------------------


def test_risk_off_demotion_does_not_mask_zero_breadth_ratio() -> None:
    """R20.16 regression: breadth_ratio=0.0 is extreme bearish (zero stocks advancing).
    ``or 0.5`` would promote it to neutral, masking a crash signal and skipping
    the risk-off demotion.  The fix ensures 0.0 is preserved verbatim."""
    from unittest.mock import patch

    from src.screening.signal_fusion import _apply_risk_off_short_term_demotion

    market_state = MarketState(breadth_ratio=0.0, position_scale=1.0)
    signals = {
        "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0, sub_factors={}),
        "event_sentiment": StrategySignal(direction=1, confidence=65.0, completeness=1.0, sub_factors={}),
    }
    # breadth_ratio=0.0 <= 0.42 -> should apply risk-off demotion
    _apply_risk_off_short_term_demotion(signals, market_state, [])
    # The demoted signals should have reduced confidence
    assert signals["trend"].confidence < 70.0
    assert signals["event_sentiment"].confidence < 65.0


def test_risk_off_demotion_does_not_mask_zero_position_scale() -> None:
    """R20.16 regression: position_scale=0.0 means "no positions allowed" (extreme risk-off).
    ``or 1.0`` would promote it to full position, bypassing risk-off demotion."""
    from src.screening.signal_fusion import _apply_risk_off_short_term_demotion

    market_state = MarketState(breadth_ratio=0.5, position_scale=0.0)
    signals = {
        "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0, sub_factors={}),
        "event_sentiment": StrategySignal(direction=1, confidence=65.0, completeness=1.0, sub_factors={}),
    }
    # position_scale=0.0 <= 0.75 -> should apply risk-off demotion
    _apply_risk_off_short_term_demotion(signals, market_state, [])
    assert signals["trend"].confidence < 70.0
    assert signals["event_sentiment"].confidence < 65.0


def test_classify_btst_regime_gate_preserves_zero_breadth_ratio() -> None:
    """R20.16 regression: classify_btst_regime_gate_from_market_state with breadth_ratio=0.0
    should preserve 0.0 (extreme bearish) rather than promoting it to 0.5 (neutral)."""
    from src.screening.market_state_helpers import classify_btst_regime_gate_from_market_state

    result = classify_btst_regime_gate_from_market_state({"breadth_ratio": 0.0, "daily_return": 0.0, "style_dispersion": 0.0, "regime_flip_risk": 0.0})
    assert result is not None
    # breadth_ratio=0.0 should appear verbatim in the metrics output
    assert result["metrics"]["breadth_ratio"] == 0.0
    # Should trigger conservative profile hint (not aggressive)
    assert result["profile_hint"] == "conservative"
    assert "breadth_weak" in result["reason_codes"]


# ---------------------------------------------------------------------------
# compute_score_b tests
# ---------------------------------------------------------------------------


def test_compute_score_b_all_bullish() -> None:
    """All strategies bullish → positive score."""
    from src.screening.signal_fusion import compute_score_b

    signals = {
        "trend": StrategySignal(direction=1, confidence=80.0, completeness=1.0),
        "mean_reversion": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
        "fundamental": StrategySignal(direction=1, confidence=60.0, completeness=1.0),
        "event_sentiment": StrategySignal(direction=1, confidence=50.0, completeness=1.0),
    }
    weights = {"trend": 0.30, "mean_reversion": 0.20, "fundamental": 0.30, "event_sentiment": 0.20}
    score = compute_score_b(signals, weights, [])
    assert score > 0.0


def test_compute_score_b_all_bearish() -> None:
    """All strategies bearish → negative score."""
    from src.screening.signal_fusion import compute_score_b

    signals = {
        "trend": StrategySignal(direction=-1, confidence=80.0, completeness=1.0),
        "mean_reversion": StrategySignal(direction=-1, confidence=70.0, completeness=1.0),
        "fundamental": StrategySignal(direction=-1, confidence=60.0, completeness=1.0),
        "event_sentiment": StrategySignal(direction=-1, confidence=50.0, completeness=1.0),
    }
    weights = {"trend": 0.30, "mean_reversion": 0.20, "fundamental": 0.30, "event_sentiment": 0.20}
    score = compute_score_b(signals, weights, [])
    assert score < 0.0


def test_compute_score_b_mixed_signals() -> None:
    """Mixed signals (some bullish, some bearish) → score near zero."""
    from src.screening.signal_fusion import compute_score_b

    signals = {
        "trend": StrategySignal(direction=1, confidence=60.0, completeness=1.0),
        "mean_reversion": StrategySignal(direction=-1, confidence=60.0, completeness=1.0),
    }
    weights = {"trend": 0.50, "mean_reversion": 0.50}
    score = compute_score_b(signals, weights, [])
    assert abs(score) < 0.01


def test_compute_score_b_clamps_to_positive_one() -> None:
    """Score cannot exceed +1.0 even with extreme confidence."""
    from src.screening.signal_fusion import compute_score_b

    signals = {
        "trend": StrategySignal(direction=1, confidence=100.0, completeness=1.0),
    }
    weights = {"trend": 1.0}
    score = compute_score_b(signals, weights, [])
    assert score == 1.0


def test_compute_score_b_clamps_to_negative_one() -> None:
    """Score cannot go below -1.0 even with extreme bearish confidence."""
    from src.screening.signal_fusion import compute_score_b

    signals = {
        "trend": StrategySignal(direction=-1, confidence=100.0, completeness=1.0),
    }
    weights = {"trend": 1.0}
    score = compute_score_b(signals, weights, [])
    assert score == -1.0


def test_compute_score_b_consensus_bonus_bullish() -> None:
    """Bullish consensus bonus makes positive score more positive."""
    from src.screening.models import ArbitrationAction
    from src.screening.signal_fusion import compute_score_b

    signals = {
        "trend": StrategySignal(direction=1, confidence=80.0, completeness=1.0),
    }
    weights = {"trend": 1.0}
    without_bonus = compute_score_b(signals, weights, [])
    with_bonus = compute_score_b(signals, weights, [ArbitrationAction.CONSENSUS_BONUS.value])
    assert with_bonus > without_bonus
    assert with_bonus == without_bonus + 0.05


def test_compute_score_b_consensus_bonus_bearish() -> None:
    """Bearish consensus bonus makes negative score MORE negative (GAMMA-016)."""
    from src.screening.models import ArbitrationAction
    from src.screening.signal_fusion import compute_score_b

    signals = {
        "trend": StrategySignal(direction=-1, confidence=80.0, completeness=1.0),
    }
    weights = {"trend": 1.0}
    without_bonus = compute_score_b(signals, weights, [])
    with_bonus = compute_score_b(signals, weights, [ArbitrationAction.CONSENSUS_BONUS.value])
    # Bearish bonus should make score MORE bearish (lower)
    assert with_bonus < without_bonus
    assert with_bonus == without_bonus - 0.05


def test_compute_score_b_consensus_bonus_zero_score_is_noop() -> None:
    """When score is exactly 0, consensus bonus should NOT be applied (GAMMA-017b)."""
    from src.screening.models import ArbitrationAction
    from src.screening.signal_fusion import compute_score_b

    # Equal bullish and bearish signals → score ≈ 0
    signals = {
        "trend": StrategySignal(direction=1, confidence=60.0, completeness=1.0),
        "mean_reversion": StrategySignal(direction=-1, confidence=60.0, completeness=1.0),
    }
    weights = {"trend": 0.50, "mean_reversion": 0.50}
    without_bonus = compute_score_b(signals, weights, [])
    with_bonus = compute_score_b(signals, weights, [ArbitrationAction.CONSENSUS_BONUS.value])
    assert without_bonus == 0.0
    assert with_bonus == 0.0


def test_compute_score_b_low_completeness_reduces_score() -> None:
    """Low completeness should reduce the effective score contribution."""
    from src.screening.signal_fusion import compute_score_b

    full = StrategySignal(direction=1, confidence=80.0, completeness=1.0)
    partial = StrategySignal(direction=1, confidence=80.0, completeness=0.3)
    weights = {"trend": 1.0}
    score_full = compute_score_b({"trend": full}, weights, [])
    score_partial = compute_score_b({"trend": partial}, weights, [])
    assert score_full > score_partial
    assert abs(score_partial - score_full * 0.3) < 0.01


def test_compute_score_b_empty_signals() -> None:
    """Empty signals dict → score 0.0."""
    from src.screening.signal_fusion import compute_score_b

    score = compute_score_b({}, {"trend": 0.3}, [])
    assert score == 0.0


def test_compute_score_b_zero_confidence() -> None:
    """Zero confidence → zero contribution regardless of direction."""
    from src.screening.signal_fusion import compute_score_b

    signals = {"trend": StrategySignal(direction=1, confidence=0.0, completeness=1.0)}
    score = compute_score_b(signals, {"trend": 1.0}, [])
    assert score == 0.0


# ---------------------------------------------------------------------------
# _apply_risk_off_short_term_demotion tests
# ---------------------------------------------------------------------------


def test_risk_off_demotion_applies_when_low_breadth() -> None:
    """Low breadth_ratio + bullish trend → trend confidence demoted by 0.80."""
    from src.screening.signal_fusion import _apply_risk_off_short_term_demotion

    trend = StrategySignal(direction=1, confidence=80.0, completeness=1.0)
    event = StrategySignal(direction=1, confidence=70.0, completeness=1.0)
    signals = {"trend": trend, "event_sentiment": event}
    arbitration: list[str] = []

    _apply_risk_off_short_term_demotion(
        signals, MarketState(breadth_ratio=0.30, position_scale=0.80), arbitration,
    )

    assert trend.confidence == pytest.approx(64.0)  # 80 * 0.80
    assert event.confidence == pytest.approx(49.0)  # 70 * 0.70
    assert "risk_off" in arbitration


def test_risk_off_demotion_skips_when_good_breadth() -> None:
    """Good breadth_ratio (>0.42) and position_scale (>0.75) → no demotion."""
    from src.screening.signal_fusion import _apply_risk_off_short_term_demotion

    trend = StrategySignal(direction=1, confidence=80.0, completeness=1.0)
    signals = {"trend": trend}
    arbitration: list[str] = []

    _apply_risk_off_short_term_demotion(
        signals, MarketState(breadth_ratio=0.50, position_scale=0.90), arbitration,
    )

    assert trend.confidence == 80.0  # unchanged
    assert arbitration == []


def test_risk_off_demotion_skips_when_no_bullish_signals() -> None:
    """Bearish signals are not demoted by risk-off logic."""
    from src.screening.signal_fusion import _apply_risk_off_short_term_demotion

    trend = StrategySignal(direction=-1, confidence=80.0, completeness=1.0)
    signals = {"trend": trend}
    arbitration: list[str] = []

    _apply_risk_off_short_term_demotion(
        signals, MarketState(breadth_ratio=0.30, position_scale=0.50), arbitration,
    )

    assert trend.confidence == 80.0  # unchanged
    assert arbitration == []


def test_risk_off_demotion_skips_with_strong_fundamental() -> None:
    """Strong fundamental support (direction>0, confidence>=65) prevents demotion."""
    from src.screening.signal_fusion import _apply_risk_off_short_term_demotion

    trend = StrategySignal(direction=1, confidence=80.0, completeness=1.0)
    fundamental = StrategySignal(direction=1, confidence=70.0, completeness=1.0)
    signals = {"trend": trend, "fundamental": fundamental}
    arbitration: list[str] = []

    _apply_risk_off_short_term_demotion(
        signals, MarketState(breadth_ratio=0.30, position_scale=0.50), arbitration,
    )

    assert trend.confidence == 80.0  # unchanged — fundamental protects
    assert arbitration == []


# ---------------------------------------------------------------------------
# _should_apply_consensus_bonus tests
# ---------------------------------------------------------------------------


def test_consensus_bonus_applies_with_3_plus_bullish() -> None:
    """3+ bullish strategies with confidence > 60 → consensus bonus."""
    from src.screening.signal_fusion import _should_apply_consensus_bonus

    signals = {
        "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
        "mean_reversion": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
        "fundamental": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
        "event_sentiment": StrategySignal(direction=0, confidence=50.0, completeness=1.0),
    }
    assert _should_apply_consensus_bonus(signals, MarketState()) is True


def test_consensus_bonus_applies_with_3_plus_bearish() -> None:
    """3+ bearish strategies with confidence > 60 → consensus bonus."""
    from src.screening.signal_fusion import _should_apply_consensus_bonus

    signals = {
        "trend": StrategySignal(direction=-1, confidence=70.0, completeness=1.0),
        "mean_reversion": StrategySignal(direction=-1, confidence=70.0, completeness=1.0),
        "fundamental": StrategySignal(direction=-1, confidence=70.0, completeness=1.0),
    }
    assert _should_apply_consensus_bonus(signals, MarketState()) is True


def test_consensus_bonus_skips_with_fewer_than_3() -> None:
    """Only 2 bullish strategies → no consensus bonus."""
    from src.screening.signal_fusion import _should_apply_consensus_bonus

    signals = {
        "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
        "mean_reversion": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
        "fundamental": StrategySignal(direction=-1, confidence=70.0, completeness=1.0),
    }
    assert _should_apply_consensus_bonus(signals, MarketState()) is False


def test_consensus_bonus_skips_low_confidence() -> None:
    """3 bullish but confidence ≤ 60 → no consensus bonus."""
    from src.screening.signal_fusion import _should_apply_consensus_bonus

    signals = {
        "trend": StrategySignal(direction=1, confidence=60.0, completeness=1.0),
        "mean_reversion": StrategySignal(direction=1, confidence=60.0, completeness=1.0),
        "fundamental": StrategySignal(direction=1, confidence=60.0, completeness=1.0),
    }
    assert _should_apply_consensus_bonus(signals, MarketState()) is False


def test_consensus_bonus_bullish_withdrawn_in_risk_off_without_fundamental() -> None:
    """Bullish consensus bonus WITHHELD in risk-off mode without strong fundamental (R20.17)."""
    from src.screening.signal_fusion import _should_apply_consensus_bonus

    signals = {
        "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
        "mean_reversion": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
        "fundamental": StrategySignal(direction=0, confidence=50.0, completeness=0.5),
        "event_sentiment": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
    }
    # Risk-off: low breadth + low position_scale, no strong fundamental
    result = _should_apply_consensus_bonus(signals, MarketState(breadth_ratio=0.30, position_scale=0.50))
    assert result is False
