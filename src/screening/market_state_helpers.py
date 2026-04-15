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
    style_dispersion: float
    regime_flip_risk: float


def _clamp_unit_interval(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _compute_style_dispersion(*, breadth_ratio: float, daily_return: float, limit_ratio: float) -> float:
    weak_breadth_gap = _clamp_unit_interval((0.50 - breadth_ratio) / 0.18)
    narrow_leadership = weak_breadth_gap * _clamp_unit_interval((limit_ratio - 1.50) / 2.50)
    index_resilience_divergence = weak_breadth_gap * _clamp_unit_interval((daily_return + 0.0020) / 0.0100)
    return round(_clamp_unit_interval((0.55 * narrow_leadership) + (0.45 * index_resilience_divergence)), 6)


def _compute_regime_flip_risk(*, breadth_ratio: float, daily_return: float, northbound_flow_days: int, style_dispersion: float) -> float:
    breadth_deterioration = _clamp_unit_interval((0.46 - breadth_ratio) / 0.14)
    dispersion_pressure = _clamp_unit_interval((style_dispersion - 0.35) / 0.45)
    index_mismatch = _clamp_unit_interval((daily_return + 0.0015) / 0.0080) if breadth_ratio <= 0.42 else 0.0
    if northbound_flow_days <= -3:
        flow_headwind = 1.0
    elif northbound_flow_days <= -1:
        flow_headwind = 0.5
    else:
        flow_headwind = 0.0
    return round(
        _clamp_unit_interval(
            (0.40 * breadth_deterioration)
            + (0.25 * dispersion_pressure)
            + (0.20 * index_mismatch)
            + (0.15 * flow_headwind)
        ),
        6,
    )


def _resolve_regime_gate(*, metrics: MarketStateMetrics, position_scale: float) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if metrics.breadth_ratio <= 0.42:
        reasons.append("breadth_weak")
    if metrics.style_dispersion >= 0.45:
        reasons.append("style_dispersion")
    if metrics.regime_flip_risk >= 0.58:
        reasons.append("regime_flip_risk")
    if position_scale <= 0.75:
        reasons.append("position_scale_reduced")
    if metrics.is_low_volume:
        reasons.append("low_volume")

    crisis = metrics.breadth_ratio <= 0.35 or position_scale <= 0.55 or (metrics.regime_flip_risk >= 0.82 and metrics.style_dispersion >= 0.55)
    risk_off = crisis or metrics.breadth_ratio <= 0.42 or position_scale <= 0.75 or metrics.regime_flip_risk >= 0.58
    if crisis:
        return "crisis", reasons
    if risk_off:
        return "risk_off", reasons
    return "normal", reasons


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
    style_dispersion = _compute_style_dispersion(
        breadth_ratio=breadth_ratio,
        daily_return=daily_return,
        limit_ratio=limit_ratio,
    )
    regime_flip_risk = _compute_regime_flip_risk(
        breadth_ratio=breadth_ratio,
        daily_return=daily_return,
        northbound_flow_days=northbound_flow_days,
        style_dispersion=style_dispersion,
    )
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
        style_dispersion=style_dispersion,
        regime_flip_risk=regime_flip_risk,
    )


def recommend_short_trade_profile(
    *,
    breadth_ratio: float,
    daily_return: float,
    limit_ratio: float,
    adx: float,
    style_dispersion: float | None = None,
    regime_flip_risk: float | None = None,
    regime_gate_level: str | None = None,
) -> str:
    """基于市场状态推荐BTST短线交易profile。

    基于2026Q1 40天回测+市场状态因子IC分析的研究发现：
    - 大跌后(bounce regime, daily_return<-1%): 次日WR=54%, 收益+0.54% → 使用btst_precision_v2（激进）
    - 正常下跌(slight_drop, -1%~-0.3%): WR尚可 → btst_precision_v2
    - 正常上涨(slight_rise, -0.3%~+1%): 次日收益-0.23% → 提高阈值但保持v2
    - 大涨后(euphoria, daily_return>+1%): 次日WR=37%, 收益-0.73% → conservative（保守）
    """
    normalized_regime_gate_level = str(regime_gate_level or "").strip().lower()
    if normalized_regime_gate_level in {"risk_off", "crisis"}:
        return "conservative"
    if (regime_flip_risk or 0.0) >= 0.58 or (style_dispersion or 0.0) >= 0.55:
        return "conservative"
    if daily_return <= -0.01:
        # Bounce regime: market dropped, expect recovery → aggressive
        return "btst_precision_v2"
    if daily_return >= 0.01:
        # Euphoria regime: market rose too much, expect pullback → conservative
        return "conservative"
    # Neutral regime: slight moves in either direction
    if breadth_ratio <= 0.35:
        return "conservative"
    return "btst_precision_v2"


def build_market_state_from_metrics(*, metrics: MarketStateMetrics, normalize_weights: callable) -> MarketState:
    adjusted = DEFAULT_STRATEGY_WEIGHTS.copy()
    position_scale = 0.5 if metrics.is_low_volume else 1.0
    state_type, position_scale = _apply_base_state_adjustments(metrics=metrics, adjusted=adjusted, position_scale=position_scale)
    _apply_limit_ratio_adjustments(metrics=metrics, adjusted=adjusted)
    position_scale = _apply_breadth_adjustments(metrics=metrics, adjusted=adjusted, position_scale=position_scale)
    _apply_northbound_adjustments(metrics=metrics, adjusted=adjusted)
    position_scale = max(0.2, min(1.0, position_scale))
    regime_gate_level, regime_gate_reasons = _resolve_regime_gate(metrics=metrics, position_scale=position_scale)
    return MarketState(
        state_type=state_type,
        adx=round(metrics.adx, 4),
        atr_price_ratio=round(metrics.atr_ratio, 6),
        breadth_ratio=round(metrics.breadth_ratio, 6),
        daily_return=round(metrics.daily_return, 6),
        limit_up_count=metrics.limit_up_count,
        limit_down_count=metrics.limit_down_count,
        limit_up_down_ratio=round(metrics.limit_ratio, 6),
        total_volume=round(metrics.total_volume, 4),
        northbound_flow_days=metrics.northbound_flow_days,
        is_low_volume=metrics.is_low_volume,
        style_dispersion=round(metrics.style_dispersion, 6),
        regime_flip_risk=round(metrics.regime_flip_risk, 6),
        regime_gate_level=regime_gate_level,
        regime_gate_reasons=regime_gate_reasons,
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
    if metrics.limit_down_count > 0 and metrics.limit_ratio >= 3.0 or metrics.limit_up_count > 0 and metrics.limit_ratio <= (1 / 3):
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
