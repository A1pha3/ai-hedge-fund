"""
Mean reversion strategy sub-factor scoring functions.

Scoring for RSI extremes, Bollinger z-score, stat-arb, and Hurst regime.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.agents.technicals import (
    calculate_hurst_exponent,
    calculate_mean_reversion_signals,
    calculate_rsi,
    calculate_stat_arb_signals,
)
from src.screening.models import StrategySignal, SubFactor
from src.screening.strategy_scorer_utils import (
    MEAN_REVERSION_SUBFACTOR_WEIGHTS,
    aggregate_sub_factors,
    _make_sub_factor,
    _signal_to_direction,
)


@dataclass(frozen=True)
class HurstRegimeSnapshot:
    hurst: float
    z_score: float | None
    completeness: float


def score_mean_reversion_strategy(prices_df: pd.DataFrame) -> StrategySignal:
    mean_reversion_signal = calculate_mean_reversion_signals(prices_df) if len(prices_df) >= 50 else None
    stat_arb_signal = calculate_stat_arb_signals(prices_df) if len(prices_df) >= 80 else None
    return aggregate_sub_factors(
        _build_mean_reversion_sub_factors(
            prices_df=prices_df,
            mean_reversion_signal=mean_reversion_signal,
            stat_arb_signal=stat_arb_signal,
        )
    )


def _build_mean_reversion_sub_factors(
    *, prices_df: pd.DataFrame, mean_reversion_signal: dict | None, stat_arb_signal: dict | None
) -> list[SubFactor]:
    return [
        _build_optional_mean_reversion_factor("zscore_bbands", mean_reversion_signal),
        _build_rsi_extreme_factor(prices_df),
        _build_optional_mean_reversion_factor("stat_arb", stat_arb_signal),
        _build_hurst_regime_factor(prices_df),
    ]


def _build_rsi_extreme_factor(prices_df: pd.DataFrame) -> SubFactor:
    if len(prices_df) < 28:
        return _make_sub_factor("rsi_extreme", 0, 0.0, MEAN_REVERSION_SUBFACTOR_WEIGHTS["rsi_extreme"], completeness=0.0)
    last_rsi_14, last_rsi_28 = _build_rsi_extreme_snapshot(prices_df)
    rsi_direction, rsi_conf = _resolve_rsi_extreme_signal(last_rsi_14, last_rsi_28)
    return _build_rsi_extreme_sub_factor(last_rsi_14, last_rsi_28, rsi_direction, rsi_conf)


def _build_rsi_extreme_snapshot(prices_df: pd.DataFrame) -> tuple[float, float]:
    rsi_14 = calculate_rsi(prices_df, 14)
    rsi_28 = calculate_rsi(prices_df, 28)
    last_rsi_14 = float(rsi_14.iloc[-1]) if pd.notna(rsi_14.iloc[-1]) else 50.0
    last_rsi_28 = float(rsi_28.iloc[-1]) if pd.notna(rsi_28.iloc[-1]) else 50.0
    return last_rsi_14, last_rsi_28


def _resolve_rsi_extreme_signal(last_rsi_14: float, last_rsi_28: float) -> tuple[int, float]:
    if last_rsi_14 < 30 and last_rsi_28 < 40:
        return 1, min(100.0, (40.0 - last_rsi_14) * 3)
    if last_rsi_14 > 70 and last_rsi_28 > 60:
        return -1, min(100.0, (last_rsi_14 - 60.0) * 3)
    return 0, 50.0


def _build_rsi_extreme_sub_factor(last_rsi_14: float, last_rsi_28: float, direction: int, confidence: float) -> SubFactor:
    return _make_sub_factor(
        "rsi_extreme",
        direction,
        confidence,
        MEAN_REVERSION_SUBFACTOR_WEIGHTS["rsi_extreme"],
        metrics={"rsi_14": last_rsi_14, "rsi_28": last_rsi_28},
    )


def _build_hurst_regime_factor(prices_df: pd.DataFrame) -> SubFactor:
    snapshot = _build_hurst_regime_snapshot(prices_df)
    hurst_direction, hurst_conf = _resolve_hurst_regime_signal(snapshot)

    return _make_sub_factor(
        "hurst_regime",
        hurst_direction,
        hurst_conf,
        MEAN_REVERSION_SUBFACTOR_WEIGHTS["hurst_regime"],
        completeness=snapshot.completeness,
        metrics={"hurst_exponent": snapshot.hurst, "z_score": snapshot.z_score},
    )


def _build_hurst_regime_snapshot(prices_df: pd.DataFrame) -> HurstRegimeSnapshot:
    hurst = calculate_hurst_exponent(prices_df["close"]) if len(prices_df) >= 80 else 0.5
    z_score = None
    if len(prices_df) >= 50:
        ma_50 = prices_df["close"].rolling(window=50).mean()
        std_50 = prices_df["close"].rolling(window=50).std()
        latest_z_score = ((prices_df["close"] - ma_50) / std_50).iloc[-1]
        z_score = float(latest_z_score) if pd.notna(latest_z_score) else 0.0
    return HurstRegimeSnapshot(hurst=hurst, z_score=z_score, completeness=1.0 if len(prices_df) >= 80 else 0.0)


def _resolve_hurst_regime_signal(snapshot: HurstRegimeSnapshot) -> tuple[int, float]:
    if snapshot.hurst < 0.45 and snapshot.z_score is not None:
        return (1 if snapshot.z_score < -1.0 else -1 if snapshot.z_score > 1.0 else 0), min(100.0, (0.55 - snapshot.hurst) * 180)
    if snapshot.hurst > 0.55:
        return (-1 if snapshot.z_score is not None and snapshot.z_score < 0 else 1 if snapshot.z_score is not None and snapshot.z_score > 0 else 0), min(100.0, (snapshot.hurst - 0.45) * 120)
    return 0, 45.0


def _build_optional_mean_reversion_factor(name: str, signal: dict | None) -> SubFactor:
    direction, confidence, completeness, metrics = _resolve_optional_mean_reversion_factor_inputs(signal)
    return _make_sub_factor(name, direction, confidence, MEAN_REVERSION_SUBFACTOR_WEIGHTS[name], completeness=completeness, metrics=metrics)


def _resolve_optional_mean_reversion_factor_inputs(signal: dict | None) -> tuple[int, float, float, dict]:
    if signal is None:
        return 0, 0.0, 0.0, {}
    return _signal_to_direction(signal["signal"]), signal["confidence"] * 100.0, 1.0, signal["metrics"]
