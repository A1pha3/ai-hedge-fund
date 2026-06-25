from __future__ import annotations

import pytest

from src.screening.models import FusedScore, MarketState, StrategySignal
from src.screening.signal_fusion import (
    _get_neutral_mean_reversion_partial_weight,
    _get_sub_factor_snapshot,
    _has_quality_first_red_flag,
    _is_hard_cliff_profitability,
    _should_exclude_neutral_mean_reversion,
    compute_score_decomposition,
    fuse_batch,
    fuse_signals_for_ticker,
)


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
    from src.screening.market_state_helpers import (
        classify_btst_regime_gate_from_market_state,
    )

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
    """Trend bullish + MR same-direction → nonzero score.

    Note: MR is reversed for A-share (STRATEGY_DIRECTION_MULTIPLIER=-1).
    So trend bullish (dir=1) + MR bullish (dir=1, reversed→-1) cancel out.
    Here trend bullish + MR bullish → near zero.
    """
    from src.screening.signal_fusion import compute_score_b

    signals = {
        "trend": StrategySignal(direction=1, confidence=60.0, completeness=1.0),
        "mean_reversion": StrategySignal(direction=1, confidence=60.0, completeness=1.0),
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


def test_mean_reversion_direction_reversed_in_score() -> None:
    """A股动量市场: mean_reversion 信号方向反转 (诊断 2026-06-25).

    MR bullish (超跌, 预期反弹) → A 股超跌继续跌 → 应拉低 score.
    MR bearish (超涨, 预期回调) → A 股超涨继续涨 → 应拉高 score.
    """
    from src.screening.signal_fusion import compute_score_b
    from src.screening.models import STRATEGY_DIRECTION_MULTIPLIER

    # 配置检查
    assert STRATEGY_DIRECTION_MULTIPLIER.get("mean_reversion") == -1.0, (
        "mean_reversion must be reversed for A-share momentum market"
    )

    # MR bullish (方向=1) × 反转(-1) → score 应为负
    signals_bull = {
        "mean_reversion": StrategySignal(direction=1, confidence=80.0, completeness=1.0),
    }
    score_bull = compute_score_b(signals_bull, {"mean_reversion": 1.0}, [])
    assert score_bull == pytest.approx(-0.80), (
        f"MR bullish 应拉低 score (反转后), got {score_bull}"
    )

    # MR bearish (方向=-1) × 反转(-1) → score 应为正
    signals_bear = {
        "mean_reversion": StrategySignal(direction=-1, confidence=80.0, completeness=1.0),
    }
    score_bear = compute_score_b(signals_bear, {"mean_reversion": 1.0}, [])
    assert score_bear == pytest.approx(+0.80), (
        f"MR bearish 应拉高 score (反转后), got {score_bear}"
    )


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

    # Trend bullish + MR bullish (MR reversed → negative) cancel out → score ≈ 0
    signals = {
        "trend": StrategySignal(direction=1, confidence=60.0, completeness=1.0),
        "mean_reversion": StrategySignal(direction=1, confidence=60.0, completeness=1.0),
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


# ---------------------------------------------------------------------------
# fuse_signals_for_ticker integration tests
# ---------------------------------------------------------------------------


def test_fuse_signals_for_ticker_bullish_produces_positive_score() -> None:
    """Strong bullish signals → positive score_b, buy-ish decision."""
    fused = fuse_signals_for_ticker(
        "000001",
        signals={
            "trend": StrategySignal(direction=1, confidence=85.0, completeness=1.0),
            "mean_reversion": StrategySignal(direction=1, confidence=75.0, completeness=1.0),
            "fundamental": StrategySignal(direction=1, confidence=80.0, completeness=1.0),
            "event_sentiment": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
        },
        market_state=MarketState(),
    )
    assert fused.score_b > 0.0
    assert fused.ticker == "000001"
    assert fused.decision in ("strong_buy", "watch")


def test_fuse_signals_for_ticker_bearish_produces_negative_score() -> None:
    """Strong bearish signals → negative score_b, sell-ish decision."""
    fused = fuse_signals_for_ticker(
        "000002",
        signals={
            "trend": StrategySignal(direction=-1, confidence=85.0, completeness=1.0),
            "mean_reversion": StrategySignal(direction=-1, confidence=75.0, completeness=1.0),
            "fundamental": StrategySignal(direction=-1, confidence=80.0, completeness=1.0),
            "event_sentiment": StrategySignal(direction=-1, confidence=70.0, completeness=1.0),
        },
        market_state=MarketState(),
    )
    assert fused.score_b < 0.0
    assert fused.decision in ("sell", "strong_sell")


def test_fuse_signals_for_ticker_returns_fused_score_with_weights() -> None:
    """Returns FusedScore with weights_used populated."""
    fused = fuse_signals_for_ticker(
        "000003",
        signals={"trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0)},
        market_state=MarketState(),
    )
    assert fused.score_b is not None
    assert len(fused.weights_used) > 0
    assert "trend" in fused.weights_used


def test_fuse_signals_for_ticker_uses_market_state_weights() -> None:
    """Custom market_state.adjusted_weights override defaults."""
    fused_default = fuse_signals_for_ticker(
        "000004",
        signals={"trend": StrategySignal(direction=1, confidence=80.0, completeness=1.0)},
        market_state=MarketState(),
    )
    fused_custom = fuse_signals_for_ticker(
        "000004",
        signals={"trend": StrategySignal(direction=1, confidence=80.0, completeness=1.0)},
        market_state=MarketState(adjusted_weights={"trend": 1.0, "mean_reversion": 0.0, "fundamental": 0.0, "event_sentiment": 0.0}),
    )
    # With all weight on trend, score should be higher (no dilution)
    assert fused_custom.score_b >= fused_default.score_b


def test_fuse_signals_for_ticker_arbitration_applied_populated() -> None:
    """Arbitration list is populated when consensus bonus triggers."""
    fused = fuse_signals_for_ticker(
        "000005",
        signals={
            "trend": StrategySignal(direction=1, confidence=80.0, completeness=1.0),
            "mean_reversion": StrategySignal(direction=1, confidence=80.0, completeness=1.0),
            "fundamental": StrategySignal(direction=1, confidence=80.0, completeness=1.0),
            "event_sentiment": StrategySignal(direction=1, confidence=80.0, completeness=1.0),
        },
        market_state=MarketState(),
    )
    # 4 bullish with high confidence → should trigger consensus bonus
    assert "consensus_bonus" in fused.arbitration_applied


class TestAnalysisExcludesNeutralMeanReversion:
    """Env-var parser for LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION."""

    ENV = "LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION"

    def test_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv(self.ENV, raising=False)
        from src.screening.signal_fusion import (
            _analysis_excludes_neutral_mean_reversion,
        )

        assert _analysis_excludes_neutral_mean_reversion() is False

    def test_truthy_values(self, monkeypatch):
        from src.screening.signal_fusion import (
            _analysis_excludes_neutral_mean_reversion,
        )

        for val in ("1", "true", "yes", "on"):
            monkeypatch.setenv(self.ENV, val)
            assert _analysis_excludes_neutral_mean_reversion() is True

    def test_falsy_values(self, monkeypatch):
        from src.screening.signal_fusion import (
            _analysis_excludes_neutral_mean_reversion,
        )

        for val in ("0", "false", "random"):
            monkeypatch.setenv(self.ENV, val)
            assert _analysis_excludes_neutral_mean_reversion() is False

    def test_whitespace_and_case_normalized(self, monkeypatch):
        monkeypatch.setenv(self.ENV, "  TRUE  ")
        from src.screening.signal_fusion import (
            _analysis_excludes_neutral_mean_reversion,
        )

        assert _analysis_excludes_neutral_mean_reversion() is True


class TestGetNeutralMeanReversionMode:
    """Mode resolver: MODE env takes precedence; falls back to EXCLUDE flag."""

    MODE_ENV = "LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE"
    EXCLUDE_ENV = "LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION"

    def test_mode_set_takes_precedence(self, monkeypatch):
        monkeypatch.setenv(self.MODE_ENV, "full_exclude")
        monkeypatch.setenv(self.EXCLUDE_ENV, "1")  # should be ignored
        from src.screening.signal_fusion import _get_neutral_mean_reversion_mode

        assert _get_neutral_mean_reversion_mode() == "full_exclude"

    def test_mode_empty_falls_back_to_off(self, monkeypatch):
        monkeypatch.setenv(self.MODE_ENV, "")
        monkeypatch.delenv(self.EXCLUDE_ENV, raising=False)
        from src.screening.signal_fusion import _get_neutral_mean_reversion_mode

        assert _get_neutral_mean_reversion_mode() == "off"

    def test_mode_normalized(self, monkeypatch):
        monkeypatch.setenv(self.MODE_ENV, "  PARTIAL  ")
        from src.screening.signal_fusion import _get_neutral_mean_reversion_mode

        assert _get_neutral_mean_reversion_mode() == "partial"

    def test_neither_set_returns_off(self, monkeypatch):
        monkeypatch.delenv(self.MODE_ENV, raising=False)
        monkeypatch.delenv(self.EXCLUDE_ENV, raising=False)
        from src.screening.signal_fusion import _get_neutral_mean_reversion_mode

        assert _get_neutral_mean_reversion_mode() == "off"

    def test_exclude_flag_fallback_when_mode_unset(self, monkeypatch):
        monkeypatch.delenv(self.MODE_ENV, raising=False)
        monkeypatch.setenv(self.EXCLUDE_ENV, "true")
        from src.screening.signal_fusion import _get_neutral_mean_reversion_mode

        assert _get_neutral_mean_reversion_mode() == "full_exclude"


class TestQualityFirstGuardEnabled:
    """Env-var parser for LAYER_B_ANALYSIS_QUALITY_FIRST_GUARD (defaults to True)."""

    ENV = "LAYER_B_ANALYSIS_QUALITY_FIRST_GUARD"

    def test_unset_returns_true_default(self, monkeypatch):
        monkeypatch.delenv(self.ENV, raising=False)
        from src.screening.signal_fusion import _quality_first_guard_enabled

        assert _quality_first_guard_enabled() is True

    def test_truthy_values(self, monkeypatch):
        from src.screening.signal_fusion import _quality_first_guard_enabled

        for val in ("1", "true", "yes", "on"):
            monkeypatch.setenv(self.ENV, val)
            assert _quality_first_guard_enabled() is True

    def test_falsy_values(self, monkeypatch):
        from src.screening.signal_fusion import _quality_first_guard_enabled

        for val in ("0", "false", "random", ""):
            monkeypatch.setenv(self.ENV, val)
            assert _quality_first_guard_enabled() is False

    def test_whitespace_and_case_normalized(self, monkeypatch):
        monkeypatch.setenv(self.ENV, "  TRUE  ")
        from src.screening.signal_fusion import _quality_first_guard_enabled

        assert _quality_first_guard_enabled() is True


class TestComputeRawScore:
    """_compute_raw_score: weighted sum of direction * confidence * completeness."""

    def test_single_bullish_signal(self):
        from src.screening.signal_fusion import _compute_raw_score

        signals = {"trend": StrategySignal(direction=1, confidence=80.0, completeness=1.0, sub_factors={})}
        result = _compute_raw_score({"trend": 0.5}, signals)
        assert result == pytest.approx(0.5 * 1 * 0.80 * 1.0)

    def test_single_bearish_signal_negative(self):
        from src.screening.signal_fusion import _compute_raw_score

        signals = {"trend": StrategySignal(direction=-1, confidence=60.0, completeness=1.0, sub_factors={})}
        result = _compute_raw_score({"trend": 0.5}, signals)
        assert result == pytest.approx(-0.3)

    def test_missing_weight_contributes_zero(self):
        from src.screening.signal_fusion import _compute_raw_score

        signals = {"trend": StrategySignal(direction=1, confidence=90.0, completeness=1.0, sub_factors={})}
        result = _compute_raw_score({}, signals)
        assert result == 0.0

    def test_zero_completeness_contributes_zero(self):
        from src.screening.signal_fusion import _compute_raw_score

        signals = {"trend": StrategySignal(direction=1, confidence=90.0, completeness=0.0, sub_factors={})}
        result = _compute_raw_score({"trend": 0.5}, signals)
        assert result == 0.0

    def test_multiple_signals_sum(self):
        from src.screening.signal_fusion import _compute_raw_score

        signals = {
            "trend": StrategySignal(direction=1, confidence=80.0, completeness=1.0, sub_factors={}),
            "mean_reversion": StrategySignal(direction=-1, confidence=40.0, completeness=0.5, sub_factors={}),
        }
        result = _compute_raw_score({"trend": 0.4, "mean_reversion": 0.6}, signals)
        expected = 0.4 * 1 * 0.80 * 1.0 + 0.6 * (-1) * 0.40 * 0.5
        assert result == pytest.approx(expected)


class TestSignalContribution:
    """_signal_contribution: absolute value of weight * direction * confidence * completeness."""

    def test_bullish_positive(self):
        from src.screening.signal_fusion import _signal_contribution

        signal = StrategySignal(direction=1, confidence=80.0, completeness=1.0, sub_factors={})
        assert _signal_contribution(0.5, signal) == pytest.approx(0.4)

    def test_bearish_always_positive(self):
        from src.screening.signal_fusion import _signal_contribution

        signal = StrategySignal(direction=-1, confidence=60.0, completeness=1.0, sub_factors={})
        assert _signal_contribution(0.5, signal) == pytest.approx(0.3)

    def test_zero_completeness_returns_zero(self):
        from src.screening.signal_fusion import _signal_contribution

        signal = StrategySignal(direction=1, confidence=90.0, completeness=0.0, sub_factors={})
        assert _signal_contribution(0.5, signal) == 0.0

    def test_zero_weight_returns_zero(self):
        from src.screening.signal_fusion import _signal_contribution

        signal = StrategySignal(direction=1, confidence=90.0, completeness=1.0, sub_factors={})
        assert _signal_contribution(0.0, signal) == 0.0


class TestBuildPercentileRankMap:
    """_build_percentile_rank_map: average-rank percentiles with tie handling."""

    def test_empty_returns_empty(self):
        from src.screening.signal_fusion import _build_percentile_rank_map

        assert _build_percentile_rank_map({}) == {}

    def test_single_value_returns_empty(self):
        from src.screening.signal_fusion import _build_percentile_rank_map

        assert _build_percentile_rank_map({"a": 1.0}) == {}

    def test_two_distinct_values(self):
        from src.screening.signal_fusion import _build_percentile_rank_map

        result = _build_percentile_rank_map({"a": 0.1, "b": 0.5})
        assert result == {"a": 0.5, "b": 1.0}

    def test_tied_values_get_average_rank(self):
        from src.screening.signal_fusion import _build_percentile_rank_map

        # Both tied at rank 1.5 / 2 = 0.75
        result = _build_percentile_rank_map({"a": 0.5, "b": 0.5})
        assert result == {"a": 0.75, "b": 0.75}

    def test_three_values_with_partial_tie(self):
        from src.screening.signal_fusion import _build_percentile_rank_map

        # sorted: a=0.1 (rank1), b=0.3 (rank2), c=0.3 (rank3)
        # b,c tie at avg rank (2+3)/2=2.5 -> 2.5/3
        result = _build_percentile_rank_map({"a": 0.1, "b": 0.3, "c": 0.3})
        assert result["a"] == pytest.approx(1 / 3)
        assert result["b"] == pytest.approx(2.5 / 3)
        assert result["c"] == pytest.approx(2.5 / 3)


class TestExtractAttentionComponentValues:
    """_extract_attention_component_values: extract metric with NaN/Inf/non-numeric guard."""

    def _fused(self, ticker: str, metrics: dict) -> FusedScore:
        return FusedScore(ticker=ticker, score_b=0.0, metrics=metrics)

    def test_normal_values_extracted(self):
        from src.screening.signal_fusion import _extract_attention_component_values

        results = [self._fused("a", {"ret_5d": 0.02}), self._fused("b", {"ret_5d": 0.05})]
        assert _extract_attention_component_values(results, "ret_5d") == {"a": 0.02, "b": 0.05}

    def test_missing_metric_skipped(self):
        from src.screening.signal_fusion import _extract_attention_component_values

        results = [self._fused("a", {"ret_5d": 0.02}), self._fused("b", {})]
        assert _extract_attention_component_values(results, "ret_5d") == {"a": 0.02}

    def test_nan_skipped(self):
        import math

        from src.screening.signal_fusion import _extract_attention_component_values

        results = [self._fused("a", {"v": math.nan}), self._fused("b", {"v": 0.05})]
        assert _extract_attention_component_values(results, "v") == {"b": 0.05}

    def test_inf_skipped(self):
        import math

        from src.screening.signal_fusion import _extract_attention_component_values

        results = [self._fused("a", {"v": math.inf}), self._fused("b", {"v": 0.05})]
        assert _extract_attention_component_values(results, "v") == {"b": 0.05}

    def test_absolute_flag_returns_abs(self):
        from src.screening.signal_fusion import _extract_attention_component_values

        results = [self._fused("a", {"v": -0.05})]
        assert _extract_attention_component_values(results, "v", absolute=True) == {"a": 0.05}
        assert _extract_attention_component_values(results, "v", absolute=False) == {"a": -0.05}


class TestNormalizeActiveWeights:
    """_normalize_active_weights: normalize active signal weights to sum=1 with fallback."""

    def test_two_active_signals_normalized(self):
        from src.screening.signal_fusion import _normalize_active_weights

        signals = {
            "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0, sub_factors={}),
            "fundamental": StrategySignal(direction=1, confidence=60.0, completeness=1.0, sub_factors={}),
        }
        weights = {"trend": 0.3, "fundamental": 0.3}
        result = _normalize_active_weights(weights, signals)
        assert sum(result.values()) == pytest.approx(1.0)
        assert result["trend"] == pytest.approx(0.5)
        assert result["fundamental"] == pytest.approx(0.5)

    def test_excluded_name_skipped(self):
        from src.screening.signal_fusion import _normalize_active_weights

        signals = {
            "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0, sub_factors={}),
            "mean_reversion": StrategySignal(direction=0, confidence=50.0, completeness=1.0, sub_factors={}),
        }
        weights = {"trend": 0.3, "mean_reversion": 0.2}
        result = _normalize_active_weights(weights, signals, excluded_names={"mean_reversion"})
        assert "mean_reversion" not in result
        assert result == {"trend": 1.0}

    def test_zero_completeness_skipped(self):
        from src.screening.signal_fusion import _normalize_active_weights

        signals = {
            "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0, sub_factors={}),
            "mean_reversion": StrategySignal(direction=0, confidence=50.0, completeness=0.0, sub_factors={}),
        }
        weights = {"trend": 0.3, "mean_reversion": 0.2}
        result = _normalize_active_weights(weights, signals)
        assert "mean_reversion" not in result
        assert result == {"trend": 1.0}

    def test_weight_override_applied_when_higher(self):
        from src.screening.signal_fusion import _normalize_active_weights

        signals = {
            "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0, sub_factors={}),
            "mean_reversion": StrategySignal(direction=0, confidence=50.0, completeness=1.0, sub_factors={}),
        }
        weights = {"trend": 0.3, "mean_reversion": 0.2}
        # override 0.5 > existing 0.2 → uses 0.5; 0.3 + 0.5 = 0.8 → trend=0.375, mr=0.625
        result = _normalize_active_weights(weights, signals, weight_overrides={"mean_reversion": 0.5})
        assert result["mean_reversion"] == pytest.approx(0.5 / 0.8)

    def test_all_weights_zero_falls_back_to_defaults(self):
        from src.screening.signal_fusion import _normalize_active_weights

        signals = {
            "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0, sub_factors={}),
            "fundamental": StrategySignal(direction=1, confidence=60.0, completeness=1.0, sub_factors={}),
        }
        weights = {"trend": 0.0, "fundamental": 0.0}
        result = _normalize_active_weights(weights, signals)
        # falls back to DEFAULT_STRATEGY_WEIGHTS: trend=0.30, fundamental=0.30 → each 0.5
        assert result["trend"] == pytest.approx(0.5)
        assert result["fundamental"] == pytest.approx(0.5)

    def test_all_signals_excluded_returns_empty(self):
        from src.screening.signal_fusion import _normalize_active_weights

        signals = {
            "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0, sub_factors={}),
        }
        weights = {"trend": 0.3}
        result = _normalize_active_weights(weights, signals, excluded_names={"trend"})
        assert result == {}


# ---------------------------------------------------------------------------
# _is_hard_cliff_profitability / _get_sub_factor_snapshot (was 0 direct coverage)
# ---------------------------------------------------------------------------


def _make_signal_with_profitability(
    *,
    completeness: float = 1.0,
    prof_direction: int | None = None,
    prof_metrics: dict | None = None,
) -> StrategySignal:
    """Helper: build a fundamental StrategySignal with a profitability sub-factor."""
    profitability: dict = {}
    if prof_direction is not None:
        profitability["direction"] = prof_direction
    if prof_metrics is not None:
        profitability["metrics"] = prof_metrics
    return StrategySignal(
        direction=1,
        confidence=70.0,
        completeness=completeness,
        sub_factors={"profitability": profitability},
    )


class TestIsHardCliffProfitability:
    """_is_hard_cliff_profitability — detect hard profitability cliff."""

    def test_no_fundamental_signal_returns_false(self) -> None:
        assert _is_hard_cliff_profitability({}) is False
        assert _is_hard_cliff_profitability({"trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0)}) is False

    def test_profitability_direction_not_negative_returns_false(self) -> None:
        signal = _make_signal_with_profitability(prof_direction=1, prof_metrics={"positive_count": 0})
        assert _is_hard_cliff_profitability({"fundamental": signal}) is False

    def test_negative_direction_but_positive_count_nonzero_returns_false(self) -> None:
        signal = _make_signal_with_profitability(prof_direction=-1, prof_metrics={"positive_count": 3})
        assert _is_hard_cliff_profitability({"fundamental": signal}) is False

    def test_hard_cliff_direction_neg1_and_zero_positive_count(self) -> None:
        signal = _make_signal_with_profitability(prof_direction=-1, prof_metrics={"positive_count": 0})
        assert _is_hard_cliff_profitability({"fundamental": signal}) is True

    def test_no_metrics_returns_false(self) -> None:
        # direction == -1 but no metrics key → positive_count is None != 0
        signal = _make_signal_with_profitability(prof_direction=-1)
        assert _is_hard_cliff_profitability({"fundamental": signal}) is False

    def test_no_profitability_sub_factor_returns_false(self) -> None:
        signal = StrategySignal(direction=1, confidence=70.0, completeness=1.0, sub_factors={})
        assert _is_hard_cliff_profitability({"fundamental": signal}) is False


class TestGetSubFactorSnapshot:
    """_get_sub_factor_snapshot — safely extract a sub-factor dict."""

    def test_returns_sub_factor_when_present(self) -> None:
        signal = StrategySignal(
            direction=1, confidence=70.0, completeness=1.0,
            sub_factors={"growth": {"direction": 1, "confidence": 80.0}},
        )
        result = _get_sub_factor_snapshot(signal, "growth")
        assert result == {"direction": 1, "confidence": 80.0}

    def test_returns_empty_when_absent(self) -> None:
        signal = StrategySignal(direction=1, confidence=70.0, completeness=1.0, sub_factors={})
        assert _get_sub_factor_snapshot(signal, "growth") == {}

    def test_returns_empty_when_not_a_dict(self) -> None:
        signal = StrategySignal(
            direction=1, confidence=70.0, completeness=1.0,
            sub_factors={"growth": "not a dict"},
        )
        assert _get_sub_factor_snapshot(signal, "growth") == {}

    def test_returns_empty_when_none(self) -> None:
        signal = StrategySignal(
            direction=1, confidence=70.0, completeness=1.0,
            sub_factors={"growth": None},
        )
        assert _get_sub_factor_snapshot(signal, "growth") == {}


# ---------------------------------------------------------------------------
# _should_exclude_neutral_mean_reversion / _get_neutral_mean_reversion_partial_weight
# (was 0 direct coverage — test tractable early-exit + mode-dispatch branches)
# ---------------------------------------------------------------------------

_MR_MODE_ENV = "LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE"


def _mr_signal(direction: int = 0, completeness: float = 1.0) -> StrategySignal:
    return StrategySignal(direction=direction, confidence=50.0, completeness=completeness, sub_factors={})


class TestShouldExcludeNeutralMeanReversion:
    """_should_exclude_neutral_mean_reversion — early-exit + mode-dispatch branches."""

    def test_no_mr_signal_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "full_exclude")
        assert _should_exclude_neutral_mean_reversion({}, {}) is False

    def test_mr_direction_nonzero_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "full_exclude")
        signals = {"mean_reversion": _mr_signal(direction=1)}
        assert _should_exclude_neutral_mean_reversion({}, signals) is False

    def test_mr_zero_completeness_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "full_exclude")
        signals = {"mean_reversion": _mr_signal(completeness=0.0)}
        assert _should_exclude_neutral_mean_reversion({}, signals) is False

    def test_mode_off_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "off")
        signals = {"mean_reversion": _mr_signal()}
        assert _should_exclude_neutral_mean_reversion({}, signals) is False

    def test_mode_full_exclude_returns_true(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "full_exclude")
        signals = {"mean_reversion": _mr_signal()}
        assert _should_exclude_neutral_mean_reversion({}, signals) is True

    def test_unknown_mode_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "bogus_mode")
        signals = {"mean_reversion": _mr_signal()}
        assert _should_exclude_neutral_mean_reversion({}, signals) is False

    def test_guarded_mode_non_positive_trend_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "guarded_dual_leg_033")
        signals = {
            "mean_reversion": _mr_signal(),
            "trend": StrategySignal(direction=0, confidence=70.0, completeness=1.0),
            "fundamental": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
        }
        assert _should_exclude_neutral_mean_reversion({}, signals) is False

    def test_guarded_mode_event_completeness_blocks(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "guarded_dual_leg_033")
        signals = {
            "mean_reversion": _mr_signal(),
            "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
            "fundamental": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
            "event_sentiment": StrategySignal(direction=1, confidence=60.0, completeness=0.8),
        }
        assert _should_exclude_neutral_mean_reversion({}, signals) is False


class TestGetNeutralMeanReversionPartialWeight:
    """_get_neutral_mean_reversion_partial_weight — early-exit branches."""

    def test_no_mr_signal_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "partial_mr_half_dual_leg_033_no_hard_cliff")
        assert _get_neutral_mean_reversion_partial_weight({}, {}) is None

    def test_mr_direction_nonzero_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "partial_mr_half_dual_leg_033_no_hard_cliff")
        signals = {"mean_reversion": _mr_signal(direction=-1)}
        assert _get_neutral_mean_reversion_partial_weight({}, signals) is None

    def test_unknown_mode_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "off")
        signals = {"mean_reversion": _mr_signal()}
        assert _get_neutral_mean_reversion_partial_weight({}, signals) is None

    def test_partial_mode_non_positive_trend_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "partial_mr_half_dual_leg_033_no_hard_cliff")
        signals = {
            "mean_reversion": _mr_signal(),
            "trend": StrategySignal(direction=0, confidence=70.0, completeness=1.0),
            "fundamental": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
        }
        assert _get_neutral_mean_reversion_partial_weight({"mean_reversion": 0.25}, signals) is None

    def test_partial_mode_negative_event_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv(_MR_MODE_ENV, "partial_mr_half_dual_leg_033_no_hard_cliff")
        signals = {
            "mean_reversion": _mr_signal(),
            "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
            "fundamental": StrategySignal(direction=1, confidence=70.0, completeness=1.0),
            "event_sentiment": StrategySignal(direction=-1, confidence=60.0, completeness=0.8),
        }
        assert _get_neutral_mean_reversion_partial_weight({"mean_reversion": 0.25}, signals) is None


# ---------------------------------------------------------------------------
# _has_quality_first_red_flag (was 0 direct coverage)
# ---------------------------------------------------------------------------

_QUALITY_GUARD_ENV = "LAYER_B_ANALYSIS_QUALITY_FIRST_GUARD"


def _fundamental_signal_with_subs(
    *,
    completeness: float = 1.0,
    profitability: dict | None = None,
    financial_health: dict | None = None,
    growth: dict | None = None,
) -> StrategySignal:
    sub_factors: dict[str, dict] = {}
    if profitability is not None:
        sub_factors["profitability"] = profitability
    if financial_health is not None:
        sub_factors["financial_health"] = financial_health
    if growth is not None:
        sub_factors["growth"] = growth
    return StrategySignal(direction=1, confidence=70.0, completeness=completeness, sub_factors=sub_factors)


class TestHasQualityFirstRedFlag:
    """_has_quality_first_red_flag — quality-first guard for fundamental breakdown."""

    def test_guard_disabled_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_QUALITY_GUARD_ENV, "0")
        signals = {"fundamental": _fundamental_signal_with_subs(
            profitability={"direction": -1, "confidence": 80},
            financial_health={"direction": -1, "confidence": 80},
        )}
        assert _has_quality_first_red_flag(signals) is False

    def test_no_fundamental_signal_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_QUALITY_GUARD_ENV, "1")
        assert _has_quality_first_red_flag({}) is False

    def test_zero_completeness_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_QUALITY_GUARD_ENV, "1")
        signals = {"fundamental": _fundamental_signal_with_subs(
            completeness=0.0,
            profitability={"direction": -1, "confidence": 80},
            financial_health={"direction": -1, "confidence": 80},
        )}
        assert _has_quality_first_red_flag(signals) is False

    def test_paired_quality_breakdown_high_confidence_returns_true(self, monkeypatch) -> None:
        monkeypatch.setenv(_QUALITY_GUARD_ENV, "1")
        signals = {"fundamental": _fundamental_signal_with_subs(
            profitability={"direction": -1, "confidence": 70},
            financial_health={"direction": -1, "confidence": 70},
            growth={"direction": 1, "confidence": 50},  # growth positive, but paired pair triggers
        )}
        assert _has_quality_first_red_flag(signals) is True

    def test_paired_breakdown_below_confidence_threshold_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_QUALITY_GUARD_ENV, "1")
        # Both directions -1 but confidences below 55
        signals = {"fundamental": _fundamental_signal_with_subs(
            profitability={"direction": -1, "confidence": 50},
            financial_health={"direction": -1, "confidence": 50},
        )}
        assert _has_quality_first_red_flag(signals) is False

    def test_only_one_negative_direction_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_QUALITY_GUARD_ENV, "1")
        signals = {"fundamental": _fundamental_signal_with_subs(
            profitability={"direction": -1, "confidence": 80},
            financial_health={"direction": 0, "confidence": 80},  # not negative
            growth={"direction": 1, "confidence": 50},  # offset, no hard-cliff
        )}
        assert _has_quality_first_red_flag(signals) is False

    def test_hard_cliff_with_no_offset_returns_true(self, monkeypatch) -> None:
        monkeypatch.setenv(_QUALITY_GUARD_ENV, "1")
        # Hard cliff: profitability direction=-1, positive_count=0
        # financial_health direction in {-1, 0}, growth direction in {-1, 0, None}
        signals = {"fundamental": _fundamental_signal_with_subs(
            profitability={"direction": -1, "confidence": 30, "metrics": {"positive_count": 0}},
            financial_health={"direction": 0, "confidence": 40},
            growth={"direction": 0, "confidence": 30},
        )}
        assert _has_quality_first_red_flag(signals) is True

    def test_hard_cliff_offset_by_positive_growth_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_QUALITY_GUARD_ENV, "1")
        signals = {"fundamental": _fundamental_signal_with_subs(
            profitability={"direction": -1, "confidence": 30, "metrics": {"positive_count": 0}},
            financial_health={"direction": 0, "confidence": 40},
            growth={"direction": 1, "confidence": 60},  # positive growth offsets
        )}
        assert _has_quality_first_red_flag(signals) is False

    def test_hard_cliff_offset_by_positive_financial_health_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv(_QUALITY_GUARD_ENV, "1")
        signals = {"fundamental": _fundamental_signal_with_subs(
            profitability={"direction": -1, "confidence": 30, "metrics": {"positive_count": 0}},
            financial_health={"direction": 1, "confidence": 70},  # positive offsets
            growth={"direction": 0, "confidence": 30},
        )}
        assert _has_quality_first_red_flag(signals) is False
