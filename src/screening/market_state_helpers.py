from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.agents.technicals import calculate_adx, calculate_atr
from src.screening.models import DEFAULT_STRATEGY_WEIGHTS, MarketState, MarketStateType


@dataclass(frozen=True)
class MarketStateMetrics:
    adx: float
    atr_ratio: float
    daily_return: float
    limit_up_count: int
    limit_down_count: int
    limit_ratio: float
    breadth_ratio: float
    total_volume: float
    northbound_flow_days: int
    is_low_volume: bool
    breadth_is_weak: bool
    breadth_is_strong: bool


def prepare_market_frame(index_df: pd.DataFrame) -> pd.DataFrame:
    frame = index_df.rename(columns={"vol": "volume"}).copy()
    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def calculate_market_state_metrics(
    *,
    frame: pd.DataFrame,
    price_batch: pd.DataFrame | None,
    limit_df: pd.DataFrame | None,
    daily_basic: pd.DataFrame | None,
    northbound_df: pd.DataFrame | None,
    market_breadth_ratio: callable,
    northbound_streak: callable,
) -> MarketStateMetrics:
    signal_frame = frame[["high", "low", "close"]].assign(volume=frame.get("volume", 0)).copy()
    adx_df = calculate_adx(signal_frame, 20)
    atr = calculate_atr(signal_frame, 20)
    close = float(frame["close"].iloc[-1]) if pd.notna(frame["close"].iloc[-1]) else 0.0
    adx = float(adx_df["adx"].iloc[-1]) if pd.notna(adx_df["adx"].iloc[-1]) else 0.0
    atr_ratio = float(atr.iloc[-1] / close) if close > 0 and pd.notna(atr.iloc[-1]) else 0.0
    daily_return = float((frame["close"].iloc[-1] / frame["close"].iloc[-2]) - 1.0) if len(frame) >= 2 else 0.0
    limit_up_count = int((limit_df["limit"] == "U").sum()) if limit_df is not None and not limit_df.empty else 0
    limit_down_count = int((limit_df["limit"] == "D").sum()) if limit_df is not None and not limit_df.empty else 0
    limit_ratio = (limit_up_count / limit_down_count) if limit_down_count > 0 else float(limit_up_count > 0)
    breadth_ratio = market_breadth_ratio(price_batch)
    total_volume = _compute_total_volume(daily_basic)
    northbound_flow_days = northbound_streak(northbound_df)
    return MarketStateMetrics(
        adx=adx,
        atr_ratio=atr_ratio,
        daily_return=daily_return,
        limit_up_count=limit_up_count,
        limit_down_count=limit_down_count,
        limit_ratio=limit_ratio,
        breadth_ratio=breadth_ratio,
        total_volume=total_volume,
        northbound_flow_days=northbound_flow_days,
        is_low_volume=total_volume < 5000.0 if total_volume > 0 else False,
        breadth_is_weak=breadth_ratio <= 0.42,
        breadth_is_strong=breadth_ratio >= 0.58,
    )


def recommend_short_trade_profile(
    *,
    breadth_ratio: float,
    daily_return: float,
    limit_ratio: float,
    adx: float,
) -> str:
    """基于市场状态推荐BTST短线交易profile。

    规则：
    - 强势市场(breadth>0.60, return>0.005): ic_optimized (激进)
    - 危机市场(breadth<0.35, return<-0.03): conservative (保守)
    - 其他: default (默认)
    """
    if breadth_ratio >= 0.58 and daily_return > 0.003 and adx > 25:
        return "ic_optimized"
    if breadth_ratio <= 0.35 or daily_return <= -0.02:
        return "conservative"
    return "default"


def build_market_state_from_metrics(*, metrics: MarketStateMetrics, normalize_weights: callable) -> MarketState:
    adjusted = DEFAULT_STRATEGY_WEIGHTS.copy()
    position_scale = 0.5 if metrics.is_low_volume else 1.0
    state_type, position_scale = _apply_base_state_adjustments(metrics=metrics, adjusted=adjusted, position_scale=position_scale)
    _apply_limit_ratio_adjustments(metrics=metrics, adjusted=adjusted)
    position_scale = _apply_breadth_adjustments(metrics=metrics, adjusted=adjusted, position_scale=position_scale)
    _apply_northbound_adjustments(metrics=metrics, adjusted=adjusted)
    position_scale = max(0.2, min(1.0, position_scale))
    return MarketState(
        state_type=state_type,
        adx=round(metrics.adx, 4),
        atr_price_ratio=round(metrics.atr_ratio, 6),
        breadth_ratio=round(metrics.breadth_ratio, 6),
        limit_up_count=metrics.limit_up_count,
        limit_down_count=metrics.limit_down_count,
        limit_up_down_ratio=round(metrics.limit_ratio, 6),
        total_volume=round(metrics.total_volume, 4),
        northbound_flow_days=metrics.northbound_flow_days,
        is_low_volume=metrics.is_low_volume,
        position_scale=position_scale,
        adjusted_weights=normalize_weights(adjusted),
    )


def _compute_total_volume(daily_basic: pd.DataFrame | None) -> float:
    if daily_basic is None or daily_basic.empty:
        return 0.0
    circ_mv = pd.to_numeric(daily_basic.get("circ_mv"), errors="coerce").fillna(0.0)
    turnover_rate = pd.to_numeric(daily_basic.get("turnover_rate"), errors="coerce").fillna(0.0)
    return float(((circ_mv * (turnover_rate / 100.0)).sum()) / 10000.0)


def _apply_base_state_adjustments(*, metrics: MarketStateMetrics, adjusted: dict[str, float], position_scale: float) -> tuple[MarketStateType, float]:
    if metrics.daily_return <= -0.05 or metrics.limit_down_count > 500 or (metrics.breadth_ratio <= 0.28 and metrics.limit_down_count >= 120):
        adjusted["fundamental"] += 0.10
        adjusted["trend"] -= 0.10
        adjusted["event_sentiment"] -= 0.05
        adjusted["mean_reversion"] += 0.05
        return MarketStateType.CRISIS, 0.3
    if metrics.adx > 30 and metrics.atr_ratio < 0.012 and metrics.breadth_ratio >= 0.52:
        adjusted["trend"] += 0.12
        adjusted["mean_reversion"] -= 0.08
        adjusted["event_sentiment"] -= 0.04
        return MarketStateType.TREND, position_scale
    if metrics.atr_ratio < 0.012 and metrics.adx < 25:
        adjusted["mean_reversion"] += 0.12
        adjusted["trend"] -= 0.08
        adjusted["fundamental"] -= 0.04
        return MarketStateType.RANGE, position_scale
    return MarketStateType.MIXED, position_scale


def _apply_limit_ratio_adjustments(*, metrics: MarketStateMetrics, adjusted: dict[str, float]) -> None:
    if metrics.limit_down_count > 0 and metrics.limit_ratio >= 3.0:
        adjusted["event_sentiment"] *= 0.5
        adjusted["fundamental"] *= 1.3
    elif metrics.limit_up_count > 0 and metrics.limit_ratio <= (1 / 3):
        adjusted["event_sentiment"] *= 0.5
        adjusted["fundamental"] *= 1.3


def _apply_breadth_adjustments(*, metrics: MarketStateMetrics, adjusted: dict[str, float], position_scale: float) -> float:
    if metrics.breadth_is_weak:
        adjusted["trend"] -= 0.06
        adjusted["event_sentiment"] -= 0.04
        adjusted["fundamental"] += 0.06
        adjusted["mean_reversion"] += 0.04
        return position_scale * 0.75
    if metrics.breadth_is_strong:
        adjusted["trend"] += 0.04
        adjusted["event_sentiment"] += 0.02
        adjusted["fundamental"] -= 0.04
        adjusted["mean_reversion"] -= 0.02
    return position_scale


def _apply_northbound_adjustments(*, metrics: MarketStateMetrics, adjusted: dict[str, float]) -> None:
    if metrics.northbound_flow_days >= 3:
        adjusted["fundamental"] += 0.05
        adjusted["trend"] += 0.02
        adjusted["mean_reversion"] -= 0.07
    elif metrics.northbound_flow_days <= -3:
        adjusted["fundamental"] -= 0.05
        adjusted["event_sentiment"] += 0.02
        adjusted["mean_reversion"] += 0.03
