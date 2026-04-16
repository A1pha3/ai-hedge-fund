"""
Trend strategy sub-factor scoring functions.

Pure technical-indicator scoring for EMA alignment, long-trend alignment,
ADX strength, momentum, and volatility sub-factors.
"""

from __future__ import annotations

import pandas as pd

from src.agents.technicals import (
    calculate_adx,
    calculate_ema,
    calculate_momentum_signals,
    calculate_volatility_signals,
)
from src.screening.models import StrategySignal, SubFactor
from src.screening.strategy_scorer_utils import (
    aggregate_sub_factors,
    _clip,
    _get_trend_subfactor_weights,
    _make_sub_factor,
    _signal_to_direction,
)


# ---------------------------------------------------------------------------
# EMA alignment
# ---------------------------------------------------------------------------

def _score_ema_alignment(prices_df: pd.DataFrame, weight: float) -> SubFactor:
    if prices_df.empty or len(prices_df) < 60:
        return _make_sub_factor("ema_alignment", 0, 0.0, weight, completeness=0.0)

    ema_values, close = _build_ema_alignment_inputs(prices_df)
    direction = _resolve_ema_alignment_direction(ema_values)
    confidence = _calculate_ema_alignment_confidence(ema_values, close)

    return _make_sub_factor(
        "ema_alignment",
        direction,
        confidence,
        weight,
        metrics=ema_values,
    )


def _build_ema_alignment_inputs(prices_df: pd.DataFrame) -> tuple[dict[str, float], float]:
    ema_10 = calculate_ema(prices_df, 10)
    ema_30 = calculate_ema(prices_df, 30)
    ema_60 = calculate_ema(prices_df, 60)
    close = float(prices_df["close"].iloc[-1]) if pd.notna(prices_df["close"].iloc[-1]) else 0.0
    return _extract_latest_ema_values(ema_10, ema_30, ema_60), close


def _extract_latest_ema_values(ema_10: pd.Series, ema_30: pd.Series, ema_60: pd.Series) -> dict[str, float]:
    return {
        "ema_10": float(ema_10.iloc[-1]),
        "ema_30": float(ema_30.iloc[-1]),
        "ema_60": float(ema_60.iloc[-1]),
    }


def _resolve_ema_alignment_direction(ema_values: dict[str, float]) -> int:
    if ema_values["ema_10"] > ema_values["ema_30"] > ema_values["ema_60"]:
        return 1
    if ema_values["ema_10"] < ema_values["ema_30"] < ema_values["ema_60"]:
        return -1
    return 0


def _calculate_ema_alignment_confidence(ema_values: dict[str, float], close: float) -> float:
    if close <= 0:
        return 0.0
    spread = abs((ema_values["ema_10"] - ema_values["ema_30"]) / close) + abs((ema_values["ema_30"] - ema_values["ema_60"]) / close)
    return _clip(spread * 2500, 0.0, 100.0)


# ---------------------------------------------------------------------------
# Long trend alignment
# ---------------------------------------------------------------------------

def _score_long_trend_alignment(prices_df: pd.DataFrame, weight: float) -> SubFactor:
    if prices_df.empty or len(prices_df) < 200:
        return _make_sub_factor("long_trend_alignment", 0, 0.0, weight, completeness=0.0)

    ema_values, close = _build_long_trend_alignment_inputs(prices_df)
    direction = _resolve_long_trend_alignment_direction(ema_values)
    confidence = _calculate_long_trend_alignment_confidence(ema_values, close)

    return _make_sub_factor(
        "long_trend_alignment",
        direction,
        confidence,
        weight,
        metrics=ema_values,
    )


def _build_long_trend_alignment_inputs(prices_df: pd.DataFrame) -> tuple[dict[str, float], float]:
    ema_10 = calculate_ema(prices_df, 10)
    ema_200 = calculate_ema(prices_df, 200)
    close = float(prices_df["close"].iloc[-1]) if pd.notna(prices_df["close"].iloc[-1]) else 0.0
    return _extract_latest_long_trend_ema_values(ema_10, ema_200), close


def _extract_latest_long_trend_ema_values(ema_10: pd.Series, ema_200: pd.Series) -> dict[str, float]:
    return {
        "ema_10": float(ema_10.iloc[-1]),
        "ema_200": float(ema_200.iloc[-1]),
    }


def _resolve_long_trend_alignment_direction(ema_values: dict[str, float]) -> int:
    if ema_values["ema_10"] > ema_values["ema_200"]:
        return 1
    if ema_values["ema_10"] < ema_values["ema_200"]:
        return -1
    return 0


def _calculate_long_trend_alignment_confidence(ema_values: dict[str, float], close: float) -> float:
    if close <= 0:
        return 0.0
    spread = abs((ema_values["ema_10"] - ema_values["ema_200"]) / close)
    return _clip(spread * 400, 0.0, 100.0)


# ---------------------------------------------------------------------------
# ADX strength
# ---------------------------------------------------------------------------

def _score_adx_strength(prices_df: pd.DataFrame, weight: float) -> SubFactor:
    if prices_df.empty or len(prices_df) < 30:
        return _make_sub_factor("adx_strength", 0, 0.0, weight, completeness=0.0)

    adx_metrics = _build_adx_strength_metrics(prices_df)
    direction = _resolve_adx_strength_direction(adx_metrics)

    return _make_sub_factor(
        "adx_strength",
        direction,
        adx_metrics["adx"],
        weight,
        metrics=adx_metrics,
    )


def _build_adx_strength_metrics(prices_df: pd.DataFrame) -> dict[str, float]:
    return _extract_adx_strength_metrics(calculate_adx(prices_df.copy(), 20))


def _extract_adx_strength_metrics(adx_df: pd.DataFrame) -> dict[str, float]:
    return {
        "adx": float(adx_df["adx"].iloc[-1]) if pd.notna(adx_df["adx"].iloc[-1]) else 0.0,
        "+di": float(adx_df["+di"].iloc[-1]) if pd.notna(adx_df["+di"].iloc[-1]) else 0.0,
        "-di": float(adx_df["-di"].iloc[-1]) if pd.notna(adx_df["-di"].iloc[-1]) else 0.0,
    }


def _resolve_adx_strength_direction(adx_metrics: dict[str, float]) -> int:
    if adx_metrics["adx"] < 20:
        return 0
    if adx_metrics["+di"] > adx_metrics["-di"]:
        return 1
    if adx_metrics["-di"] > adx_metrics["+di"]:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Trend strategy orchestrator
# ---------------------------------------------------------------------------

def score_trend_strategy(prices_df: pd.DataFrame) -> StrategySignal:
    trend_weights = _get_trend_subfactor_weights()
    momentum_signal = calculate_momentum_signals(prices_df) if len(prices_df) >= 126 else None
    volatility_signal = calculate_volatility_signals(prices_df) if len(prices_df) >= 126 else None
    return aggregate_sub_factors(
        _build_trend_sub_factors(
            prices_df=prices_df,
            trend_weights=trend_weights,
            momentum_signal=momentum_signal,
            volatility_signal=volatility_signal,
        )
    )


def _build_trend_sub_factors(
    *,
    prices_df: pd.DataFrame,
    trend_weights: dict[str, float],
    momentum_signal: dict | None,
    volatility_signal: dict | None,
) -> list[SubFactor]:
    sub_factors = [
        _score_ema_alignment(prices_df, trend_weights["ema_alignment"]),
        _score_adx_strength(prices_df, trend_weights["adx_strength"]),
        _build_optional_trend_factor("momentum", momentum_signal, trend_weights["momentum"]),
        _build_optional_trend_factor("volatility", volatility_signal, trend_weights["volatility"]),
    ]
    if "long_trend_alignment" in trend_weights:
        _append_long_trend_factor(sub_factors, prices_df, trend_weights["long_trend_alignment"])
    return sub_factors


def _build_optional_trend_factor(name: str, signal: dict | None, weight: float) -> SubFactor:
    direction, confidence, completeness, metrics = _resolve_optional_trend_factor_inputs(signal)
    return _make_sub_factor(name, direction, confidence, weight, completeness=completeness, metrics=metrics)


def _resolve_optional_trend_factor_inputs(signal: dict | None) -> tuple[int, float, float, dict]:
    if signal is None:
        return 0, 0.0, 0.0, {}
    return _signal_to_direction(signal["signal"]), signal["confidence"] * 100.0, 1.0, signal["metrics"]


def _append_long_trend_factor(sub_factors: list[SubFactor], prices_df: pd.DataFrame, weight: float) -> None:
    sub_factors.append(_score_long_trend_alignment(prices_df, weight))
