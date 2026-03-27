"""Phase 2: Layer B 策略评分、市场状态、信号融合测试。"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import mkdtemp

import pandas as pd
from unittest.mock import patch

from src.screening.candidate_pool import load_cooldown_registry, save_cooldown_registry
from src.screening.market_state import detect_market_state
from src.screening.models import MarketState, MarketStateType, StrategySignal, SubFactor
from src.screening.signal_fusion import _normalize_for_available_signals, compute_score_b, fuse_signals_for_ticker, maybe_release_cooldown_early
from src.screening.strategy_scorer import aggregate_sub_factors, compute_event_decay, score_trend_strategy


def _make_price_frame(periods: int = 180, trend: float = 0.3) -> pd.DataFrame:
    close = [10 + (index * trend / periods) for index in range(periods)]
    high = [value * 1.02 for value in close]
    low = [value * 0.98 for value in close]
    open_values = [value * 0.995 for value in close]
    volume = [1_000_000 + index * 1000 for index in range(periods)]
    return pd.DataFrame(
        {
            "open": open_values,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=pd.date_range("2025-01-01", periods=periods, freq="D"),
    )


def _make_price_frame_from_close(close_values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": close_values,
            "high": [value * 1.02 for value in close_values],
            "low": [value * 0.98 for value in close_values],
            "close": close_values,
            "volume": [1_000_000 for _ in close_values],
        },
        index=pd.date_range("2025-01-01", periods=len(close_values), freq="D"),
    )


def _make_index_frame(adx_close_move: float = 0.1) -> pd.DataFrame:
    frame = _make_price_frame(periods=120, trend=adx_close_move)
    frame = frame.reset_index(drop=True)
    frame["trade_date"] = pd.date_range("2025-10-01", periods=120, freq="D").strftime("%Y%m%d")
    frame["ts_code"] = "000300.SH"
    frame["pre_close"] = frame["close"].shift(1).fillna(frame["close"])
    frame["change"] = frame["close"] - frame["pre_close"]
    frame["pct_chg"] = frame["change"] / frame["pre_close"] * 100
    frame["vol"] = frame["volume"]
    frame["amount"] = frame["close"] * frame["volume"] / 100000
    return frame[["ts_code", "trade_date", "close", "open", "high", "low", "pre_close", "change", "pct_chg", "vol", "amount"]]


def _signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(direction=direction, confidence=confidence, completeness=completeness, sub_factors=sub_factors or {})


def _profitability_sub_factor(direction: int, positive_count: int) -> dict:
    return {
        "profitability": {
            "confidence": 100,
            "metrics": {
                "positive_count": positive_count,
            },
            "direction": direction,
        }
    }


def _quality_guard_sub_factors(
    profitability_direction: int,
    profitability_positive_count: int,
    financial_health_direction: int,
    growth_direction: int,
    profitability_confidence: float = 100.0,
    financial_health_confidence: float = 85.0,
    growth_confidence: float = 75.0,
) -> dict:
    return {
        "profitability": {
            "direction": profitability_direction,
            "confidence": profitability_confidence,
            "metrics": {
                "positive_count": profitability_positive_count,
            },
        },
        "financial_health": {
            "direction": financial_health_direction,
            "confidence": financial_health_confidence,
            "metrics": {},
        },
        "growth": {
            "direction": growth_direction,
            "confidence": growth_confidence,
            "metrics": {},
        },
    }


def test_completeness_derivation():
    factors = [
        SubFactor(name="a", direction=1, confidence=70, completeness=1.0, weight=0.5, metrics={}),
        SubFactor(name="b", direction=1, confidence=60, completeness=0.0, weight=0.5, metrics={}),
    ]
    signal = aggregate_sub_factors(factors)
    assert signal.completeness == 1.0
    assert signal.direction == 1
    assert signal.confidence == 70.0


def test_ema_period_override():
    result = score_trend_strategy(_make_price_frame())
    metrics = result.sub_factors["ema_alignment"]["metrics"]
    assert "ema_10" in metrics
    assert "ema_30" in metrics
    assert "ema_60" in metrics
    assert "long_trend_alignment" in result.sub_factors
    assert "ema_8" not in metrics
    assert "ema_21" not in metrics
    assert "ema_55" not in metrics


def test_long_trend_alignment_enabled_by_default():
    close_values = [
        152.46, 151.14, 151.19, 150.84, 150.68, 147.49, 150.15, 150.08, 151.24, 151.02,
        148.47, 148.79, 146.07, 148.89, 151.54, 148.69, 145.24, 141.79, 140.93, 144.56,
    ]
    prices_df = _make_price_frame_from_close([80.0] * 220 + close_values)

    with patch.dict(os.environ, {}, clear=False):
        result = score_trend_strategy(prices_df)

    long_trend = result.sub_factors["long_trend_alignment"]
    assert long_trend["direction"] == 1
    assert long_trend["confidence"] > 0
    assert "ema_10" in long_trend["metrics"]
    assert "ema_200" in long_trend["metrics"]


def test_long_trend_alignment_requires_200_bars():
    with patch.dict(os.environ, {}, clear=False):
        result = score_trend_strategy(_make_price_frame(periods=180, trend=12.0))

    long_trend = result.sub_factors["long_trend_alignment"]
    assert long_trend["completeness"] == 0.0
    assert long_trend["confidence"] == 0.0


def test_long_trend_alignment_can_be_disabled_for_analysis():
    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_ENABLE_LONG_TREND_ALIGNMENT": "0"}, clear=False):
        result = score_trend_strategy(_make_price_frame())

    assert "long_trend_alignment" not in result.sub_factors


def test_event_decay():
    assert compute_event_decay(0) == 1.0
    assert compute_event_decay(1) > compute_event_decay(3)


def test_trend_market_weights():
    index_df = _make_index_frame(adx_close_move=15.0)
    limit_df = pd.DataFrame([
        {"limit": "U"}, {"limit": "U"}, {"limit": "U"}, {"limit": "D"}
    ])
    daily_basic = pd.DataFrame([
        {"circ_mv": 5_000_000, "turnover_rate": 2.0},
        {"circ_mv": 4_000_000, "turnover_rate": 2.0},
    ])
    northbound = pd.DataFrame([
        {"trade_date": "20260303", "north_money": 10},
        {"trade_date": "20260304", "north_money": 12},
        {"trade_date": "20260305", "north_money": 8},
    ])
    with patch("src.screening.market_state.get_index_daily", return_value=index_df), \
         patch("src.screening.market_state.get_limit_list", return_value=limit_df), \
         patch("src.screening.market_state.get_daily_basic_batch", return_value=daily_basic), \
         patch("src.screening.market_state.get_northbound_flow", return_value=northbound), \
         patch("src.screening.market_state.calculate_adx", return_value=pd.DataFrame({"adx": [35.0], "+di": [40.0], "-di": [20.0]})), \
         patch("src.screening.market_state.calculate_atr", return_value=pd.Series([0.1])):
        state = detect_market_state("20260305")
    assert state.state_type == MarketStateType.TREND
    assert abs(sum(state.adjusted_weights.values()) - 1.0) < 1e-6
    assert state.adjusted_weights["trend"] > state.adjusted_weights["mean_reversion"]


def test_low_volume_position_scale():
    index_df = _make_index_frame(adx_close_move=0.1)
    daily_basic = pd.DataFrame([
        {"circ_mv": 100_000, "turnover_rate": 1.0},
        {"circ_mv": 200_000, "turnover_rate": 1.0},
    ])
    with patch("src.screening.market_state.get_index_daily", return_value=index_df), \
         patch("src.screening.market_state.get_limit_list", return_value=pd.DataFrame()), \
         patch("src.screening.market_state.get_daily_basic_batch", return_value=daily_basic), \
         patch("src.screening.market_state.get_northbound_flow", return_value=pd.DataFrame()):
        state = detect_market_state("20260305")
    assert state.is_low_volume is True
    assert state.position_scale == 0.5


def test_safety_first_rule():
    market_state = MarketState(adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
    signals = {
        "trend": _signal(-1, 80),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(-1, 76),
        "event_sentiment": _signal(1, 40),
    }
    temp_dir = Path(mkdtemp())
    cooldown_file = temp_dir / "cooldown.json"
    with patch("src.screening.candidate_pool._SNAPSHOT_DIR", temp_dir), \
         patch("src.screening.candidate_pool._COOLDOWN_FILE", cooldown_file):
        fused = fuse_signals_for_ticker("000001", signals, market_state, "20260305")
        registry = load_cooldown_registry()
    assert fused.decision == "strong_sell"
    assert "avoid" in fused.arbitration_applied
    assert registry["000001"]


def test_hurst_arbitration():
    market_state = MarketState(adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
    signals = {
        "trend": _signal(1, 80),
        "mean_reversion": _signal(-1, 80, sub_factors={"hurst_regime": {"metrics": {"hurst_exponent": 0.60}}}),
        "fundamental": _signal(1, 60),
        "event_sentiment": _signal(0, 50),
    }
    fused = fuse_signals_for_ticker("000001", signals, market_state)
    assert "trust_trend" in fused.arbitration_applied
    assert fused.strategy_signals["mean_reversion"].confidence == 40


def test_consensus_bonus_and_score_range():
    market_state = MarketState(adjusted_weights={"trend": 0.25, "mean_reversion": 0.25, "fundamental": 0.25, "event_sentiment": 0.25})
    signals = {
        "trend": _signal(1, 80),
        "mean_reversion": _signal(1, 70),
        "fundamental": _signal(1, 90),
        "event_sentiment": _signal(-1, 30),
    }
    base_score = compute_score_b(signals, market_state.adjusted_weights, [])
    fused = fuse_signals_for_ticker("000001", signals, market_state)
    assert "consensus_bonus" in fused.arbitration_applied
    assert fused.score_b > base_score
    assert -1.0 <= fused.score_b <= 1.0


def test_quality_first_guard_blocks_low_quality_candidates_despite_positive_momentum():
    market_state = MarketState(adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
    signals = {
        "trend": _signal(1, 85),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(1, 70, sub_factors=_quality_guard_sub_factors(-1, 0, -1, 1)),
        "event_sentiment": _signal(1, 70),
    }

    with patch.dict(os.environ, {}, clear=False):
        fused = fuse_signals_for_ticker("000001", signals, market_state, "20260305")

    assert fused.decision == "strong_sell"
    assert "avoid" in fused.arbitration_applied
    assert fused.score_b == -1.0


def test_quality_first_guard_can_be_disabled_when_analyzing_other_hypotheses():
    market_state = MarketState(adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
    signals = {
        "trend": _signal(1, 85),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(1, 70, sub_factors=_quality_guard_sub_factors(-1, 0, -1, 1)),
        "event_sentiment": _signal(1, 70),
    }

    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_QUALITY_FIRST_GUARD": "0"}, clear=False):
        fused = fuse_signals_for_ticker("000001", signals, market_state)

    assert fused.decision == "strong_buy"
    assert "avoid" not in fused.arbitration_applied
    assert fused.score_b > 0.5


def test_cooldown_early_release():
    temp_dir = Path(mkdtemp())
    cooldown_file = temp_dir / "cooldown.json"
    with patch("src.screening.candidate_pool._SNAPSHOT_DIR", temp_dir), \
         patch("src.screening.candidate_pool._COOLDOWN_FILE", cooldown_file):
        save_cooldown_registry({"000001": "20260320"})
        released = maybe_release_cooldown_early("000001", "20260307", _signal(1, 85))
        registry = load_cooldown_registry()
    assert released is True
    assert "000001" not in registry


def test_neutral_mean_reversion_remains_active_by_default():
    weights = {"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}
    signals = {
        "trend": _signal(1, 80),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(1, 75),
        "event_sentiment": _signal(0, 0, completeness=0.0),
    }

    with patch.dict(os.environ, {}, clear=False):
        normalized = _normalize_for_available_signals(weights, signals)

    assert abs(normalized["trend"] - 0.375) < 1e-12
    assert normalized["mean_reversion"] == 0.25
    assert abs(normalized["fundamental"] - 0.375) < 1e-12


def test_neutral_mean_reversion_can_be_excluded_for_analysis():
    weights = {"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}
    signals = {
        "trend": _signal(1, 80),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(1, 75),
        "event_sentiment": _signal(0, 0, completeness=0.0),
    }

    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION": "1"}, clear=False):
        normalized = _normalize_for_available_signals(weights, signals)

    assert normalized == {"trend": 0.5, "fundamental": 0.5}


def test_guarded_neutral_mean_reversion_excludes_only_near_threshold_dual_leg_candidates():
    weights = {"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}
    signals = {
        "trend": _signal(1, 80),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(1, 80, sub_factors=_profitability_sub_factor(1, 2)),
        "event_sentiment": _signal(0, 0, completeness=0.0),
    }

    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE": "guarded_dual_leg_033_no_hard_cliff"}, clear=False):
        normalized = _normalize_for_available_signals(weights, signals)

    assert normalized == {"trend": 0.5, "fundamental": 0.5}


def test_guarded_neutral_mean_reversion_keeps_hard_cliff_candidates_active():
    weights = {"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}
    signals = {
        "trend": _signal(1, 80),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(1, 80, sub_factors=_profitability_sub_factor(-1, 0)),
        "event_sentiment": _signal(0, 0, completeness=0.0),
    }

    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE": "guarded_dual_leg_033_no_hard_cliff"}, clear=False):
        normalized = _normalize_for_available_signals(weights, signals)

    assert abs(normalized["trend"] - 0.375) < 1e-12
    assert normalized["mean_reversion"] == 0.25
    assert abs(normalized["fundamental"] - 0.375) < 1e-12


def test_partial_weight_neutral_mean_reversion_creates_intermediate_active_weight():
    weights = {"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}
    signals = {
        "trend": _signal(1, 80),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(1, 80, sub_factors=_profitability_sub_factor(1, 2)),
        "event_sentiment": _signal(1, 60),
    }

    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE": "partial_mr_half_dual_leg_033_no_hard_cliff"}, clear=False):
        normalized = _normalize_for_available_signals(weights, signals)

    assert abs(normalized["trend"] - (0.3 / 0.9)) < 1e-12
    assert abs(normalized["mean_reversion"] - (0.1 / 0.9)) < 1e-12
    assert abs(normalized["fundamental"] - (0.3 / 0.9)) < 1e-12
    assert abs(normalized["event_sentiment"] - (0.2 / 0.9)) < 1e-12


def test_partial_weight_neutral_mean_reversion_keeps_negative_event_candidates_unchanged():
    weights = {"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}
    signals = {
        "trend": _signal(1, 80),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(1, 80, sub_factors=_profitability_sub_factor(1, 2)),
        "event_sentiment": _signal(-1, 60),
    }

    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE": "partial_mr_half_dual_leg_033_no_hard_cliff"}, clear=False):
        normalized = _normalize_for_available_signals(weights, signals)

    assert abs(normalized["trend"] - 0.3) < 1e-12
    assert abs(normalized["mean_reversion"] - 0.2) < 1e-12
    assert abs(normalized["fundamental"] - 0.3) < 1e-12
    assert abs(normalized["event_sentiment"] - 0.2) < 1e-12


def test_partial_weight_third_mode_is_more_conservative_than_half_mode():
    weights = {"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}
    signals = {
        "trend": _signal(1, 80),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(1, 80, sub_factors=_profitability_sub_factor(1, 2)),
        "event_sentiment": _signal(1, 60),
    }

    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE": "partial_mr_third_dual_leg_034_no_hard_cliff"}, clear=False):
        normalized = _normalize_for_available_signals(weights, signals)

    assert abs(normalized["trend"] - (0.3 / (0.3 + (1 / 15) + 0.3 + 0.2))) < 1e-12
    assert abs(normalized["mean_reversion"] - ((1 / 15) / (0.3 + (1 / 15) + 0.3 + 0.2))) < 1e-12
    assert abs(normalized["fundamental"] - (0.3 / (0.3 + (1 / 15) + 0.3 + 0.2))) < 1e-12
    assert abs(normalized["event_sentiment"] - (0.2 / (0.3 + (1 / 15) + 0.3 + 0.2))) < 1e-12


def test_partial_weight_quarter_mode_requires_positive_event_signal():
    weights = {"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}
    signals = {
        "trend": _signal(1, 80),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(1, 80, sub_factors=_profitability_sub_factor(1, 2)),
        "event_sentiment": _signal(0, 60),
    }

    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE": "partial_mr_quarter_dual_leg_034_event_positive_no_hard_cliff"}, clear=False):
        normalized = _normalize_for_available_signals(weights, signals)

    assert abs(normalized["trend"] - 0.3) < 1e-12
    assert abs(normalized["mean_reversion"] - 0.2) < 1e-12
    assert abs(normalized["fundamental"] - 0.3) < 1e-12
    assert abs(normalized["event_sentiment"] - 0.2) < 1e-12


def test_partial_weight_quarter_mode_releases_only_with_positive_event_signal():
    weights = {"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}
    signals = {
        "trend": _signal(1, 80),
        "mean_reversion": _signal(0, 50),
        "fundamental": _signal(1, 80, sub_factors=_profitability_sub_factor(1, 2)),
        "event_sentiment": _signal(1, 60),
    }

    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE": "partial_mr_quarter_dual_leg_034_event_positive_no_hard_cliff"}, clear=False):
        normalized = _normalize_for_available_signals(weights, signals)

    assert abs(normalized["trend"] - (0.3 / 0.85)) < 1e-12
    assert abs(normalized["mean_reversion"] - (0.05 / 0.85)) < 1e-12
    assert abs(normalized["fundamental"] - (0.3 / 0.85)) < 1e-12
    assert abs(normalized["event_sentiment"] - (0.2 / 0.85)) < 1e-12
