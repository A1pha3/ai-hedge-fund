"""Layer B 市场状态检测器。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.agents.technicals import calculate_adx, calculate_atr
from src.screening.models import DEFAULT_STRATEGY_WEIGHTS, MarketState, MarketStateType
from src.tools.tushare_api import get_daily_basic_batch, get_index_daily, get_limit_list, get_northbound_flow


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(value, 0.0) for value in weights.values())
    if total <= 0:
        return DEFAULT_STRATEGY_WEIGHTS.copy()
    return {key: round(max(value, 0.0) / total, 6) for key, value in weights.items()}


def _northbound_streak(flow_df: pd.DataFrame) -> int:
    if flow_df is None or flow_df.empty or "north_money" not in flow_df.columns:
        return 0
    streak = 0
    for value in reversed(flow_df["north_money"].tolist()):
        if pd.isna(value):
            break
        numeric = float(value)
        if numeric > 0:
            if streak < 0:
                break
            streak += 1
        elif numeric < 0:
            if streak > 0:
                break
            streak -= 1
        else:
            break
    return streak


def detect_market_state(trade_date: str) -> MarketState:
    end_dt = datetime.strptime(trade_date, "%Y%m%d")
    start_dt = (end_dt - timedelta(days=180)).strftime("%Y%m%d")
    index_df = get_index_daily("000300.SH", start_date=start_dt, end_date=trade_date, limit=180)
    if index_df is None or index_df.empty:
        return MarketState()

    frame = index_df.rename(columns={"vol": "volume"}).copy()
    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    adx_df = calculate_adx(frame[["high", "low", "close"]].assign(volume=frame.get("volume", 0)).copy(), 20)
    atr = calculate_atr(frame[["high", "low", "close"]].assign(volume=frame.get("volume", 0)).copy(), 20)
    close = float(frame["close"].iloc[-1]) if pd.notna(frame["close"].iloc[-1]) else 0.0
    adx = float(adx_df["adx"].iloc[-1]) if pd.notna(adx_df["adx"].iloc[-1]) else 0.0
    atr_ratio = float(atr.iloc[-1] / close) if close > 0 and pd.notna(atr.iloc[-1]) else 0.0
    daily_return = float((frame["close"].iloc[-1] / frame["close"].iloc[-2]) - 1.0) if len(frame) >= 2 else 0.0

    limit_df = get_limit_list(trade_date)
    limit_up_count = int((limit_df["limit"] == "U").sum()) if limit_df is not None and not limit_df.empty else 0
    limit_down_count = int((limit_df["limit"] == "D").sum()) if limit_df is not None and not limit_df.empty else 0
    limit_ratio = (limit_up_count / limit_down_count) if limit_down_count > 0 else float(limit_up_count > 0)

    daily_basic = get_daily_basic_batch(trade_date)
    total_volume = 0.0
    if daily_basic is not None and not daily_basic.empty:
        circ_mv = pd.to_numeric(daily_basic.get("circ_mv"), errors="coerce").fillna(0.0)
        turnover_rate = pd.to_numeric(daily_basic.get("turnover_rate"), errors="coerce").fillna(0.0)
        total_volume = float(((circ_mv * (turnover_rate / 100.0)).sum()) / 10000.0)

    northbound_df = get_northbound_flow(end_date=trade_date, start_date=(end_dt - timedelta(days=20)).strftime("%Y%m%d"), limit=20)
    northbound_flow_days = _northbound_streak(northbound_df)
    is_low_volume = total_volume < 5000.0 if total_volume > 0 else False

    adjusted = DEFAULT_STRATEGY_WEIGHTS.copy()
    position_scale = 0.5 if is_low_volume else 1.0

    if daily_return <= -0.05 or limit_down_count > 500:
        state_type = MarketStateType.CRISIS
        position_scale = 0.3
        adjusted["fundamental"] += 0.10
        adjusted["trend"] -= 0.10
    elif adx > 30 and atr_ratio < 0.012:
        state_type = MarketStateType.TREND
        adjusted["trend"] += 0.12
        adjusted["mean_reversion"] -= 0.08
        adjusted["event_sentiment"] -= 0.04
    elif atr_ratio < 0.012 and adx < 25:
        state_type = MarketStateType.RANGE
        adjusted["mean_reversion"] += 0.12
        adjusted["trend"] -= 0.08
        adjusted["fundamental"] -= 0.04
    else:
        state_type = MarketStateType.MIXED

    if limit_down_count > 0 and limit_ratio >= 3.0:
        adjusted["event_sentiment"] *= 0.5
        adjusted["fundamental"] *= 1.3
    elif limit_up_count > 0 and limit_ratio <= (1 / 3):
        adjusted["event_sentiment"] *= 0.5
        adjusted["fundamental"] *= 1.3

    if northbound_flow_days >= 3:
        adjusted["fundamental"] += 0.05
        adjusted["trend"] += 0.02
        adjusted["mean_reversion"] -= 0.07
    elif northbound_flow_days <= -3:
        adjusted["fundamental"] -= 0.05
        adjusted["event_sentiment"] += 0.02
        adjusted["mean_reversion"] += 0.03

    return MarketState(
        state_type=state_type,
        adx=round(adx, 4),
        atr_price_ratio=round(atr_ratio, 6),
        limit_up_count=limit_up_count,
        limit_down_count=limit_down_count,
        limit_up_down_ratio=round(limit_ratio, 6),
        total_volume=round(total_volume, 4),
        northbound_flow_days=northbound_flow_days,
        is_low_volume=is_low_volume,
        position_scale=position_scale,
        adjusted_weights=_normalize_weights(adjusted),
    )
