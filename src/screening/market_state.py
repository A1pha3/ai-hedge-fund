"""Layer B 市场状态检测器。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.screening.models import DEFAULT_STRATEGY_WEIGHTS, MarketState
from src.screening.market_state_helpers import build_market_state_from_metrics, calculate_market_state_metrics, prepare_market_frame, recommend_short_trade_profile
from src.tools.tushare_api import get_daily_basic_batch, get_daily_price_batch, get_index_daily, get_limit_list, get_northbound_flow


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


def _market_breadth_ratio(price_df: pd.DataFrame | None) -> float:
    if price_df is None or price_df.empty:
        return 0.5

    pct_chg = pd.to_numeric(price_df.get("pct_chg"), errors="coerce").dropna()
    if pct_chg.empty:
        return 0.5

    advancers = float((pct_chg > 0).sum())
    decliners = float((pct_chg < 0).sum())
    total = advancers + decliners
    if total <= 0:
        return 0.5
    return advancers / total


def detect_market_state(trade_date: str) -> MarketState:
    end_dt = datetime.strptime(trade_date, "%Y%m%d")
    start_dt = (end_dt - timedelta(days=180)).strftime("%Y%m%d")
    index_df = get_index_daily("000300.SH", start_date=start_dt, end_date=trade_date, limit=180)
    if index_df is None or index_df.empty:
        return MarketState()

    metrics = calculate_market_state_metrics(
        frame=prepare_market_frame(index_df),
        price_batch=get_daily_price_batch(trade_date),
        limit_df=get_limit_list(trade_date),
        daily_basic=get_daily_basic_batch(trade_date),
        northbound_df=get_northbound_flow(end_date=trade_date, start_date=(end_dt - timedelta(days=20)).strftime("%Y%m%d"), limit=20),
        market_breadth_ratio=_market_breadth_ratio,
        northbound_streak=_northbound_streak,
    )
    return build_market_state_from_metrics(metrics=metrics, normalize_weights=_normalize_weights)
