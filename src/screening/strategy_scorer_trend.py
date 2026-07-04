"""
Trend strategy sub-factor scoring functions.

Pure technical-indicator scoring for EMA alignment, long-trend alignment,
ADX strength, momentum, and volatility sub-factors.
"""

from __future__ import annotations

import math

import pandas as pd

from src.agents.technicals import (
    calculate_adx,
    calculate_atr,
    calculate_ema,
    calculate_momentum_signals,
    calculate_volatility_signals,
)
from src.screening.models import StrategySignal, SubFactor
from src.screening.strategy_scorer_utils import (
    _get_trend_subfactor_weights,
    _make_sub_factor,
    _signal_to_direction,
    aggregate_sub_factors,
)
from src.tools.ashare_board_utils import get_ashare_symbol
from src.utils.numeric import clip as _clip

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


def score_trend_strategy(prices_df: pd.DataFrame, *, ticker: str | None = None) -> StrategySignal:
    trend_weights = _get_trend_subfactor_weights()
    momentum_signal = calculate_momentum_signals(prices_df) if len(prices_df) >= 126 else None
    if momentum_signal is not None:
        momentum_signal = {
            **momentum_signal,
            "metrics": {
                **dict(momentum_signal.get("metrics") or {}),
                **_build_short_trade_doc_metrics(prices_df, ticker=ticker),
            },
        }
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


def _build_short_trade_doc_metrics(prices_df: pd.DataFrame, *, ticker: str | None = None) -> dict[str, float]:
    if prices_df.empty:
        return {}
    resolved_ticker = _resolve_price_frame_ticker(prices_df, ticker=ticker)
    metrics = {
        "attack_slope_258": _compute_attack_slope_258(prices_df),
        "breakout_quality_20_atr": _compute_breakout_quality_20_atr(prices_df),
        "close_structure": _compute_close_structure(prices_df),
        "retention_proxy": _compute_retention_proxy(prices_df),
        "supply_pressure_60": _compute_supply_pressure_60(prices_df),
        "amount_ratio_5": _compute_amount_ratio_5(prices_df),
        "turnover_ratio_20": _compute_turnover_ratio_20(prices_df),
        "limit_up_memory_259": _compute_limit_up_memory_259(prices_df, ticker=resolved_ticker),
        "ret_2d": _compute_close_return(prices_df, sessions=2),
        "ret_5d": _compute_close_return(prices_df, sessions=5),
        "failed_breakout_10": float(_count_failed_breakouts(prices_df, lookback=10, breakout_window=20)),
    }
    gap_to_limit = _compute_gap_to_limit(prices_df, ticker=resolved_ticker)
    if gap_to_limit is not None:
        metrics["gap_to_limit"] = gap_to_limit
    return metrics


def _resolve_price_frame_ticker(prices_df: pd.DataFrame, *, ticker: str | None = None) -> str:
    if ticker:
        return str(ticker).strip()
    for column in ("ticker", "symbol", "ts_code"):
        if column in prices_df.columns and not prices_df.empty:
            value = prices_df[column].iloc[-1]
            if pd.notna(value):
                return str(value).strip()
    return ""


def _compute_attack_slope_258(prices_df: pd.DataFrame) -> float:
    if "close" not in prices_df.columns:
        return 0.0
    close = prices_df["close"]
    return round(
        100.0 * ((0.45 * _log_regression_slope(close, 2)) + (0.35 * _log_regression_slope(close, 5)) + (0.20 * _log_regression_slope(close, 8))),
        4,
    )


def _log_regression_slope(close: pd.Series, window: int) -> float:
    if len(close) < window or window < 2:
        return 0.0
    values = [float(value) for value in close.tail(window)]
    if any(math.isnan(value) or value <= 0.0 for value in values):
        return 0.0
    log_values = [math.log(value) for value in values]
    x_mean = (window - 1) / 2.0
    y_mean = sum(log_values) / window
    denominator = sum((idx - x_mean) ** 2 for idx in range(window))
    if denominator <= 0.0:
        return 0.0
    numerator = sum((idx - x_mean) * (value - y_mean) for idx, value in enumerate(log_values))
    return float(numerator / denominator)


def _compute_breakout_quality_20_atr(prices_df: pd.DataFrame) -> float:
    if len(prices_df) < 21 or not {"high", "low", "close"}.issubset(prices_df.columns):
        return 0.0
    atr = calculate_atr(prices_df)
    current_atr = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else 0.0
    if current_atr <= 0.0:
        return 0.0
    prev_high = float(prices_df["high"].iloc[-21:-1].max())
    close = float(prices_df["close"].iloc[-1])
    if math.isnan(prev_high) or math.isnan(close):
        return 0.0
    return round((close - prev_high) / current_atr, 4)


def _compute_close_structure(prices_df: pd.DataFrame) -> float:
    if not {"open", "high", "low", "close"}.issubset(prices_df.columns):
        return 0.0
    close_structure, _ = _compute_close_structure_components(prices_df)
    return close_structure


def _compute_close_structure_components(prices_df: pd.DataFrame) -> tuple[float, float]:
    if not {"open", "high", "low", "close"}.issubset(prices_df.columns):
        return 0.0, 0.0
    high = float(prices_df["high"].iloc[-1])
    low = float(prices_df["low"].iloc[-1])
    open_ = float(prices_df["open"].iloc[-1])
    close = float(prices_df["close"].iloc[-1])
    if any(math.isnan(v) for v in (high, low, open_, close)):
        return 0.0, 0.0
    trading_range = high - low
    if trading_range <= 0.0:
        return 0.0, 0.0
    clv = (close - low) / trading_range
    upper_shadow_ratio = (high - max(open_, close)) / trading_range
    return round(clv - (0.5 * upper_shadow_ratio), 4), round(upper_shadow_ratio, 4)


def _compute_retention_proxy(prices_df: pd.DataFrame) -> float:
    close_structure, upper_shadow_ratio = _compute_close_structure_components(prices_df)
    vwap_ratio = _compute_close_to_vwap_ratio(prices_df)
    vwap_support = _clip(vwap_ratio / 0.03, 0.0, 1.0)
    return round((0.5 * close_structure) + (0.3 * (1.0 - upper_shadow_ratio)) + (0.2 * vwap_support), 4)


def _compute_close_to_vwap_ratio(prices_df: pd.DataFrame) -> float:
    if not {"close", "amount", "volume"}.issubset(prices_df.columns):
        return 0.0
    amount = float(prices_df["amount"].iloc[-1]) if pd.notna(prices_df["amount"].iloc[-1]) else 0.0
    volume = float(prices_df["volume"].iloc[-1]) if pd.notna(prices_df["volume"].iloc[-1]) else 0.0
    close = float(prices_df["close"].iloc[-1]) if pd.notna(prices_df["close"].iloc[-1]) else 0.0
    if amount <= 0.0 or volume <= 0.0 or close <= 0.0:
        return 0.0
    vwap = amount / volume
    if vwap <= 0.0:
        return 0.0
    return max(0.0, (close / vwap) - 1.0)


def _compute_supply_pressure_60(prices_df: pd.DataFrame) -> float:
    if "close" not in prices_df.columns or len(prices_df) < 2:
        return 0.0
    close_series = pd.to_numeric(prices_df["close"], errors="coerce").dropna()
    if len(close_series) < 2:
        return 0.0
    current_close = float(close_series.iloc[-1])
    if current_close <= 0.0:
        return 0.0
    prior_closes = close_series.iloc[:-1].tail(60)
    if prior_closes.empty:
        return 0.0
    upper_bound = 1.03 * current_close
    matches = ((prior_closes >= current_close) & (prior_closes <= upper_bound)).sum()
    # GAMMA-003: divide by actual count of prior closes examined,
    # not the hardcoded 60 — avoids undercounting when fewer than 60 bars exist.
    return round(float(matches) / float(len(prior_closes)), 4)


def _compute_amount_ratio_5(prices_df: pd.DataFrame) -> float:
    source_column = "amount" if "amount" in prices_df.columns else "volume" if "volume" in prices_df.columns else ""
    if not source_column or len(prices_df) < 5:
        return 0.0
    current_amount = float(prices_df[source_column].iloc[-1])
    amount_ma_5 = float(prices_df[source_column].tail(5).mean())
    if math.isnan(current_amount) or math.isnan(amount_ma_5) or amount_ma_5 <= 0.0:
        return 0.0
    return round(current_amount / amount_ma_5, 4)


def _compute_turnover_ratio_20(prices_df: pd.DataFrame) -> float:
    if "turnover_rate" not in prices_df.columns or len(prices_df) < 21:
        return 0.0
    turnover_rate = pd.to_numeric(prices_df["turnover_rate"], errors="coerce")
    current_turnover = float(turnover_rate.iloc[-1]) if pd.notna(turnover_rate.iloc[-1]) else 0.0
    prior_turnover = turnover_rate.iloc[-21:-1].dropna()
    if current_turnover <= 0.0 or prior_turnover.empty:
        return 0.0
    prior_median = float(prior_turnover.median())
    if prior_median <= 0.0:
        return 0.0
    return round(current_turnover / prior_median, 4)


def _compute_limit_up_memory_259(prices_df: pd.DataFrame, *, ticker: str) -> float:
    if len(prices_df) < 10 or "close" not in prices_df.columns:
        return 0.0
    price_limit_pct = _resolve_ashare_price_limit_pct(ticker)
    returns = prices_df["close"].pct_change().fillna(0.0)
    last_2d = _has_recent_limit_up(returns, window=2, price_limit_pct=price_limit_pct)
    last_5d = _has_recent_limit_up(returns, window=5, price_limit_pct=price_limit_pct)
    last_9d = _has_recent_limit_up(returns, window=9, price_limit_pct=price_limit_pct)
    return round((0.5 * float(last_2d)) + (0.3 * float(last_5d)) + (0.2 * float(last_9d)), 4)


def _resolve_ashare_price_limit_pct(ticker: str) -> float:
    symbol = get_ashare_symbol(ticker)
    return 0.20 if symbol.startswith(("300", "301", "688")) else 0.10


def _has_recent_limit_up(returns: pd.Series, *, window: int, price_limit_pct: float) -> bool:
    if len(returns) < window:
        return False
    tolerance = 0.001
    return bool((returns.tail(window) >= (price_limit_pct - tolerance)).any())


def _compute_close_return(prices_df: pd.DataFrame, *, sessions: int) -> float:
    if len(prices_df) <= sessions or "close" not in prices_df.columns:
        return 0.0
    current_close = float(prices_df["close"].iloc[-1])
    prior_close = float(prices_df["close"].iloc[-(sessions + 1)])
    if math.isnan(current_close) or math.isnan(prior_close) or prior_close <= 0.0:
        return 0.0
    return round((current_close / prior_close) - 1.0, 4)


def _compute_gap_to_limit(prices_df: pd.DataFrame, *, ticker: str) -> float | None:
    if len(prices_df) < 2 or "close" not in prices_df.columns or not ticker:
        return None
    close_series = pd.to_numeric(prices_df["close"], errors="coerce").dropna()
    if len(close_series) < 2:
        return None
    current_close = float(close_series.iloc[-1])
    prior_close = float(close_series.iloc[-2])
    if current_close <= 0.0 or prior_close <= 0.0:
        return None
    limit_up_price = prior_close * (1.0 + _resolve_ashare_price_limit_pct(ticker))
    return round(max(0.0, (limit_up_price - current_close) / current_close), 4)


def _count_failed_breakouts(prices_df: pd.DataFrame, *, lookback: int, breakout_window: int) -> int:
    if not {"open", "high", "close"}.issubset(prices_df.columns):
        return 0
    failed_breakouts = 0
    start_idx = max(breakout_window, len(prices_df) - lookback)
    for idx in range(start_idx, len(prices_df)):
        prior_high = float(prices_df["high"].iloc[idx - breakout_window : idx].max())
        high = float(prices_df["high"].iloc[idx])
        open_ = float(prices_df["open"].iloc[idx])
        close = float(prices_df["close"].iloc[idx])
        if high > prior_high and close < open_:
            failed_breakouts += 1
    return failed_breakouts
