"""Phase 2: Layer B 策略评分、市场状态、信号融合测试。"""

from __future__ import annotations

from pathlib import Path
from tempfile import mkdtemp

import pandas as pd
from unittest.mock import patch

from src.screening.candidate_pool import load_cooldown_registry, save_cooldown_registry
from src.screening.market_state import detect_market_state
from src.screening.models import CandidateStock, MarketState, MarketStateType, StrategySignal, SubFactor
from src.screening.signal_fusion import compute_score_b, fuse_signals_for_ticker, maybe_release_cooldown_early
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
    assert "ema_8" not in metrics
    assert "ema_21" not in metrics
    assert "ema_55" not in metrics


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
