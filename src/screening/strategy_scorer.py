"""Layer B 四策略评分器。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Iterable, Optional

import pandas as pd

from src.agents.growth_agent import (
    analyze_growth_trends,
    analyze_insider_conviction,
    analyze_valuation,
    check_financial_health,
)
from src.agents.technicals import (
    calculate_adx,
    calculate_ema,
    calculate_hurst_exponent,
    calculate_mean_reversion_signals,
    calculate_momentum_signals,
    calculate_rsi,
    calculate_stat_arb_signals,
    calculate_volatility_signals,
)
from src.data.models import CompanyNews, FinancialMetrics, InsiderTrade
from src.screening.models import CandidateStock, StrategySignal, SubFactor
from src.tools.api import (
    get_company_news,
    get_financial_metrics,
    get_insider_trades,
    get_prices,
    prices_to_df,
)
from src.tools.tushare_api import get_all_stock_basic, get_daily_basic_batch, get_sw_industry_classification

LIGHT_STRATEGY_WEIGHTS = {
    "trend": 0.65,
    "mean_reversion": 0.35,
}
_DEFAULT_CANDIDATE_POOL_SIZE = int(os.getenv("MAX_CANDIDATE_POOL_SIZE", "300"))
TECHNICAL_SCORE_MAX_CANDIDATES = int(
    os.getenv(
        "SCORE_BATCH_TECHNICAL_MAX_CANDIDATES",
        str(max(160, math.ceil(_DEFAULT_CANDIDATE_POOL_SIZE * 0.75))),
    )
)
FUNDAMENTAL_SCORE_MAX_CANDIDATES = int(
    os.getenv(
        "SCORE_BATCH_FUNDAMENTAL_MAX_CANDIDATES",
        str(max(100, math.ceil(_DEFAULT_CANDIDATE_POOL_SIZE * 0.47))),
    )
)
EVENT_SENTIMENT_MAX_CANDIDATES = int(
    os.getenv(
        "SCORE_BATCH_EVENT_SENTIMENT_MAX_CANDIDATES",
        str(max(40, math.ceil(_DEFAULT_CANDIDATE_POOL_SIZE * 0.20))),
    )
)
HEAVY_SCORE_MIN_PROVISIONAL_SCORE = float(os.getenv("SCORE_BATCH_MIN_PROVISIONAL_SCORE", "0.05"))
HEAVY_SCORE_MIN_TREND_CONFIDENCE = float(os.getenv("SCORE_BATCH_MIN_TREND_CONFIDENCE", "35"))
TECHNICAL_STAGE_LIQUIDITY_RANK_BUCKET = float(os.getenv("CANDIDATE_POOL_BTST_LIQUIDITY_RANK_BUCKET", "2500"))

TREND_SUBFACTOR_WEIGHTS = {
    "ema_alignment": 0.35,
    "adx_strength": 0.18,
    "momentum": 0.30,
    "volatility": 0.17,
}

TREND_SUBFACTOR_WEIGHTS_WITH_LONG_TREND = {
    "ema_alignment": 0.30,
    "adx_strength": 0.16,
    "momentum": 0.24,
    "volatility": 0.15,
    "long_trend_alignment": 0.15,
}

MEAN_REVERSION_SUBFACTOR_WEIGHTS = {
    "zscore_bbands": 0.30,
    "rsi_extreme": 0.28,
    "stat_arb": 0.22,
    "hurst_regime": 0.20,
}

FUNDAMENTAL_SUBFACTOR_WEIGHTS = {
    "profitability": 0.25,
    "growth": 0.25,
    "financial_health": 0.20,
    "growth_valuation": 0.15,
    "industry_pe": 0.15,
}

EVENT_SUBFACTOR_WEIGHTS = {
    "news_sentiment": 0.55,
    "insider_conviction": 0.25,
    "event_freshness": 0.20,
}

POSITIVE_NEWS_KEYWORDS = {
    "beat", "upgrade", "contract", "growth", "record", "profit", "buyback", "dividend",
    "approval", "rebound", "breakthrough", "订单", "中标", "回购", "分红", "增长", "盈利", "超预期",
}
NEGATIVE_NEWS_KEYWORDS = {
    "miss", "downgrade", "lawsuit", "fraud", "loss", "probe", "warning", "default",
    "layoff", "recall", "risk", "亏损", "减持", "调查", "诉讼", "暴雷", "违约", "风险",
}


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _signal_to_direction(signal: str) -> int:
    mapping = {"bullish": 1, "neutral": 0, "bearish": -1}
    return mapping.get(str(signal).lower(), 0)


def _get_env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _get_env_mode(name: str, default: str) -> str:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    return value or default


def _get_trend_subfactor_weights() -> dict[str, float]:
    if _get_env_flag("LAYER_B_ANALYSIS_ENABLE_LONG_TREND_ALIGNMENT", default=True):
        return TREND_SUBFACTOR_WEIGHTS_WITH_LONG_TREND
    return TREND_SUBFACTOR_WEIGHTS


def _safe_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(date_str[:19], fmt)
        except ValueError:
            continue
    return None


def compute_event_decay(days_old: int) -> float:
    """事件衰减函数，按文档要求使用 e^(-0.35t)。"""
    return math.exp(-0.35 * max(days_old, 0))


def _event_weight_multiplier(days_old: int, strength: int) -> float:
    multiplier = 1.0
    if strength <= 0:
        return 0.0
    if strength == 1 and days_old > 2:
        return 0.0
    if strength == 1:
        multiplier *= 0.55
    if days_old > 3:
        multiplier *= 0.75
    if days_old > 5:
        multiplier *= 0.55
    if days_old > 10:
        multiplier *= 0.25
    return multiplier


def derive_completeness(sub_factors: Iterable[SubFactor]) -> float:
    available = [factor for factor in sub_factors if factor.completeness > 0]
    if not available:
        return 0.0

    total_weight = sum(factor.weight for factor in available)
    if total_weight <= 0:
        return 0.0

    return _clip(
        sum((factor.weight / total_weight) * factor.completeness for factor in available),
        0.0,
        1.0,
    )


def aggregate_sub_factors(sub_factors: list[SubFactor]) -> StrategySignal:
    """按 Phase 2.2 的规则聚合子因子。"""
    available = _filter_available_sub_factors(sub_factors)
    sub_factor_map = _build_sub_factor_map(sub_factors)
    if not available:
        return StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors=sub_factor_map)

    normalized = _normalize_sub_factor_weights(available)
    score = _calculate_weighted_sub_factor_score(normalized)
    direction = 1 if score > 0 else -1 if score < 0 else 0
    consistency = _calculate_sub_factor_consistency(normalized, direction)
    confidence = _calculate_weighted_sub_factor_confidence(normalized, consistency)
    completeness = derive_completeness(sub_factors)
    return _build_aggregated_strategy_signal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factor_map=sub_factor_map,
    )

def _build_aggregated_strategy_signal(
    *,
    direction: int,
    confidence: float,
    completeness: float,
    sub_factor_map: dict[str, dict],
) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=_clip(confidence, 0.0, 100.0),
        completeness=completeness,
        sub_factors=sub_factor_map,
    )


def _filter_available_sub_factors(sub_factors: list[SubFactor]) -> list[SubFactor]:
    return [factor for factor in sub_factors if factor.completeness > 0]


def _build_sub_factor_map(sub_factors: list[SubFactor]) -> dict[str, dict]:
    return {factor.name: factor.model_dump() for factor in sub_factors}


def _normalize_sub_factor_weights(available: list[SubFactor]) -> list[tuple[SubFactor, float]]:
    total_weight = sum(factor.weight for factor in available)
    if total_weight <= 0:
        return []
    return [(factor, factor.weight / total_weight) for factor in available]


def _calculate_weighted_sub_factor_score(normalized: list[tuple[SubFactor, float]]) -> float:
    return sum(weight * factor.direction * (factor.confidence / 100.0) for factor, weight in normalized)


def _calculate_sub_factor_consistency(normalized: list[tuple[SubFactor, float]], direction: int) -> float:
    if not normalized:
        return 0.0
    majority_direction = 0 if direction == 0 else direction
    majority_count = sum(1 for factor, _ in normalized if factor.direction == majority_direction)
    return majority_count / len(normalized)


def _calculate_weighted_sub_factor_confidence(normalized: list[tuple[SubFactor, float]], consistency: float) -> float:
    return sum(weight * factor.confidence for factor, weight in normalized) * consistency


def _make_sub_factor(
    name: str,
    direction: int,
    confidence: float,
    weight: float,
    completeness: float = 1.0,
    metrics: Optional[dict] = None,
) -> SubFactor:
    return SubFactor(
        name=name,
        direction=direction,
        confidence=_clip(confidence, 0.0, 100.0),
        completeness=_clip(completeness, 0.0, 1.0),
        weight=weight,
        metrics=metrics or {},
    )


def _empty_signal() -> StrategySignal:
    return StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={})


def _load_price_frame(ticker: str, trade_date: str, lookback_days: int = 400) -> pd.DataFrame:
    start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
    prices = get_prices(ticker=ticker, start_date=start_date, end_date=end_date)
    if not prices:
        return pd.DataFrame()
    return prices_to_df(prices)


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


@dataclass(frozen=True)
class HurstRegimeSnapshot:
    hurst: float
    z_score: float | None
    completeness: float


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


def _score_profitability(metrics: FinancialMetrics) -> SubFactor:
    state = _build_profitability_evaluation_state(metrics)
    if state.available == 0:
        return _build_incomplete_profitability_factor()

    if state.positive == 0 and state.zero_pass_mode == "inactive":
        return _build_inactive_profitability_factor(state.metrics_payload)

    direction = _resolve_profitability_direction(state.positive, state.zero_pass_mode)
    confidence = _calculate_profitability_confidence(available=state.available, positive=state.positive, direction=direction)
    return _build_profitability_scored_factor(
        direction=direction,
        confidence=confidence,
        available=state.available,
        metrics_payload=state.metrics_payload,
    )


@dataclass(frozen=True)
class ProfitabilityEvaluationState:
    available: int
    positive: int
    zero_pass_mode: str
    metrics_payload: dict[str, float | int | str | None]


def _build_profitability_evaluation_state(metrics: FinancialMetrics) -> ProfitabilityEvaluationState:
    zero_pass_mode = _get_env_mode("LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE", "bearish")
    metric_map = _build_profitability_metric_map(metrics)
    available, positive = _count_profitability_passes(metric_map)
    return ProfitabilityEvaluationState(
        available=available,
        positive=positive,
        zero_pass_mode=zero_pass_mode,
        metrics_payload=_build_profitability_metrics_payload(metric_map, available, positive, zero_pass_mode),
    )


def _build_incomplete_profitability_factor() -> SubFactor:
    return _make_sub_factor("profitability", 0, 0.0, FUNDAMENTAL_SUBFACTOR_WEIGHTS["profitability"], completeness=0.0)


def _build_inactive_profitability_factor(metrics_payload: dict[str, float | int | str | None]) -> SubFactor:
    return _make_sub_factor(
        "profitability",
        0,
        0.0,
        FUNDAMENTAL_SUBFACTOR_WEIGHTS["profitability"],
        completeness=0.0,
        metrics=metrics_payload,
    )


def _build_profitability_scored_factor(
    *,
    direction: int,
    confidence: float,
    available: int,
    metrics_payload: dict[str, float | int | str | None],
) -> SubFactor:
    return _make_sub_factor(
        "profitability",
        direction,
        confidence,
        FUNDAMENTAL_SUBFACTOR_WEIGHTS["profitability"],
        completeness=available / 3.0,
        metrics=metrics_payload,
    )


def _calculate_profitability_confidence(*, available: int, positive: int, direction: int) -> float:
    return 100.0 * positive / available if direction >= 0 else 100.0 * (available - positive) / available


def _build_profitability_metric_map(metrics: FinancialMetrics) -> dict[str, tuple[float | None, float]]:
    return {
        "return_on_equity": (metrics.return_on_equity, 0.15),
        "net_margin": (metrics.net_margin, 0.20),
        "operating_margin": (metrics.operating_margin, 0.15),
    }


def _count_profitability_passes(metric_map: dict[str, tuple[float | None, float]]) -> tuple[int, int]:
    available = 0
    positive = 0
    for value, threshold in metric_map.values():
        if value is None:
            continue
        available += 1
        if value >= threshold:
            positive += 1
    return available, positive


def _build_profitability_metrics_payload(metric_map: dict[str, tuple[float | None, float]], available: int, positive: int, zero_pass_mode: str) -> dict[str, float | int | str | None]:
    return {
        **{key: value for key, (value, _) in metric_map.items()},
        "available_count": available,
        "positive_count": positive,
        "zero_pass_mode": zero_pass_mode,
    }


def _resolve_profitability_direction(positive: int, zero_pass_mode: str) -> int:
    if positive >= 2:
        return 1
    if positive == 0 and zero_pass_mode == "neutral":
        return 0
    if positive == 0:
        return -1
    return 0


def _score_growth(metrics_list: list[FinancialMetrics]) -> SubFactor:
    if len(metrics_list) < 4:
        return _make_sub_factor("growth", 0, 0.0, FUNDAMENTAL_SUBFACTOR_WEIGHTS["growth"], completeness=0.0)
    analysis = analyze_growth_trends(metrics_list)
    direction, confidence = _resolve_growth_direction_and_confidence(float(analysis["score"]))
    return _make_sub_factor(
        "growth",
        direction,
        confidence,
        FUNDAMENTAL_SUBFACTOR_WEIGHTS["growth"],
        metrics=analysis,
    )


def _resolve_growth_direction_and_confidence(score: float) -> tuple[int, float]:
    return (1 if score > 0.6 else -1 if score < 0.4 else 0), abs(score - 0.5) * 200.0


def _score_financial_health(metrics: FinancialMetrics) -> SubFactor:
    analysis = check_financial_health(metrics)
    direction, confidence = _resolve_financial_health_direction_and_confidence(float(analysis["score"]))
    return _make_sub_factor(
        "financial_health",
        direction,
        confidence,
        FUNDAMENTAL_SUBFACTOR_WEIGHTS["financial_health"],
        metrics=analysis,
    )


def _resolve_financial_health_direction_and_confidence(score: float) -> tuple[int, float]:
    return (1 if score > 0.6 else -1 if score < 0.4 else 0), abs(score - 0.5) * 200.0


def _score_growth_valuation(metrics: FinancialMetrics) -> SubFactor:
    analysis = analyze_valuation(metrics)
    direction, confidence = _resolve_growth_valuation_direction_and_confidence(float(analysis["score"]))
    return _make_sub_factor(
        "growth_valuation",
        direction,
        confidence,
        FUNDAMENTAL_SUBFACTOR_WEIGHTS["growth_valuation"],
        metrics=analysis,
    )


def _resolve_growth_valuation_direction_and_confidence(score: float) -> tuple[int, float]:
    return (1 if score > 0.6 else -1 if score == 0 else 0), abs(score - 0.5) * 200.0 if score > 0 else 65.0


def _score_industry_pe(metrics: FinancialMetrics, industry_name: str, industry_pe_medians: Optional[dict[str, float]]) -> SubFactor:
    premium_inputs = _resolve_industry_pe_inputs(metrics, industry_name, industry_pe_medians)
    if premium_inputs is None:
        return _make_sub_factor("industry_pe", 0, 0.0, FUNDAMENTAL_SUBFACTOR_WEIGHTS["industry_pe"], completeness=0.0)

    current_pe, industry_median = premium_inputs
    premium = current_pe / industry_median
    direction, confidence = _resolve_industry_pe_direction_and_confidence(premium)
    return _make_sub_factor(
        "industry_pe",
        direction,
        confidence,
        FUNDAMENTAL_SUBFACTOR_WEIGHTS["industry_pe"],
        metrics=_build_industry_pe_metrics(industry_name, current_pe, industry_median, premium),
    )


def _build_industry_pe_metrics(industry_name: str, current_pe: float, industry_median: float, premium: float) -> dict[str, float | str]:
    return {
        "industry": industry_name,
        "current_pe": current_pe,
        "industry_pe_median": industry_median,
        "premium_ratio": premium,
    }


def _resolve_industry_pe_inputs(
    metrics: FinancialMetrics,
    industry_name: str,
    industry_pe_medians: Optional[dict[str, float]],
) -> tuple[float, float] | None:
    if not industry_name or not industry_pe_medians or metrics.price_to_earnings_ratio is None:
        return None
    industry_median = industry_pe_medians.get(industry_name)
    if industry_median is None or industry_median <= 0:
        return None
    return metrics.price_to_earnings_ratio, industry_median


def _resolve_industry_pe_direction_and_confidence(premium: float) -> tuple[int, float]:
    if premium <= 0.8:
        return 1, min(100.0, (1.0 - premium) * 250.0)
    if premium >= 1.2:
        return -1, min(100.0, (premium - 1.0) * 150.0)
    return 0, 50.0


def _apply_fundamental_quality_cap(signal: StrategySignal) -> StrategySignal:
    if not _should_apply_fundamental_quality_cap(signal):
        return signal

    capped_sub_factors = dict(signal.sub_factors)
    capped_sub_factors["quality_cap"] = _build_fundamental_quality_cap_payload(signal)
    return StrategySignal(
        direction=0,
        confidence=min(signal.confidence, 45.0),
        completeness=signal.completeness,
        sub_factors=capped_sub_factors,
    )


def _should_apply_fundamental_quality_cap(signal: StrategySignal) -> bool:
    if signal.direction <= 0 or signal.completeness <= 0:
        return False

    profitability = signal.sub_factors.get("profitability", {})
    financial_health = signal.sub_factors.get("financial_health", {})
    if not isinstance(profitability, dict) or not isinstance(financial_health, dict):
        return False

    profitability_direction = int(profitability.get("direction", 0) or 0)
    financial_health_direction = int(financial_health.get("direction", 0) or 0)
    return profitability_direction <= 0 and financial_health_direction <= 0


def _build_fundamental_quality_cap_payload(signal: StrategySignal) -> dict:
    return {
        "applied": True,
        "reason": "profitability_and_financial_health_not_bullish",
        "original_direction": signal.direction,
        "original_confidence": signal.confidence,
    }


def score_fundamental_strategy(
    ticker: str,
    trade_date: str,
    industry_name: str = "",
    industry_pe_medians: Optional[dict[str, float]] = None,
) -> StrategySignal:
    metrics_list = _load_fundamental_metrics_history(ticker=ticker, trade_date=trade_date)
    if not metrics_list:
        return _build_empty_strategy_signal()

    sub_factors = _build_fundamental_sub_factors(
        metrics_list=metrics_list,
        industry_name=industry_name,
        industry_pe_medians=industry_pe_medians,
    )
    return _build_fundamental_strategy_signal(sub_factors)


def _build_fundamental_strategy_signal(sub_factors: list[SubFactor]) -> StrategySignal:
    return _apply_fundamental_quality_cap(aggregate_sub_factors(sub_factors))


def _load_fundamental_metrics_history(*, ticker: str, trade_date: str) -> list[FinancialMetrics]:
    return get_financial_metrics(ticker=ticker, end_date=trade_date, period="ttm", limit=8)


def _build_empty_strategy_signal() -> StrategySignal:
    return StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={})


def _build_fundamental_sub_factors(
    *,
    metrics_list: list[FinancialMetrics],
    industry_name: str,
    industry_pe_medians: Optional[dict[str, float]],
) -> list[SubFactor]:
    latest = metrics_list[0]
    return [
        _score_profitability(latest),
        _score_growth(metrics_list),
        _score_financial_health(latest),
        _score_growth_valuation(latest),
        _score_industry_pe(latest, industry_name, industry_pe_medians),
    ]


def _score_news_sentiment(news_items: list[CompanyNews], trade_date: str) -> SubFactor:
    if not news_items:
        return _make_sub_factor("news_sentiment", 0, 0.0, EVENT_SUBFACTOR_WEIGHTS["news_sentiment"], completeness=0.0)

    article_metrics = _build_news_sentiment_article_metrics(news_items, trade_date)
    normalized_score, recent_count, informative_count = _aggregate_news_article_metrics(article_metrics)
    direction, confidence, completeness = _resolve_news_sentiment_signal(
        normalized_score=normalized_score,
        informative_count=informative_count,
    )
    return _build_news_sentiment_sub_factor(
        direction,
        confidence,
        completeness,
        normalized_score=normalized_score,
        recent_count=recent_count,
        informative_count=informative_count,
        article_metrics=article_metrics,
    )


def _build_news_sentiment_article_metrics(news_items: list[CompanyNews], trade_date: str) -> list[dict]:
    trade_dt = datetime.strptime(trade_date, "%Y%m%d")
    return [_score_news_article(item, trade_dt) for item in news_items[:20]]


def _build_news_sentiment_sub_factor(
    direction: int,
    confidence: float,
    completeness: float,
    *,
    normalized_score: float,
    recent_count: int,
    informative_count: int,
    article_metrics: list[dict],
) -> SubFactor:
    return _make_sub_factor(**_build_news_sentiment_sub_factor_payload(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        normalized_score=normalized_score,
        recent_count=recent_count,
        informative_count=informative_count,
        article_metrics=article_metrics,
    ))


def _build_news_sentiment_sub_factor_payload(
    *,
    direction: int,
    confidence: float,
    completeness: float,
    normalized_score: float,
    recent_count: int,
    informative_count: int,
    article_metrics: list[dict],
) -> dict:
    return {
        "name": "news_sentiment",
        "direction": direction,
        "confidence": confidence,
        "weight": EVENT_SUBFACTOR_WEIGHTS["news_sentiment"],
        "completeness": completeness,
        "metrics": _build_news_sentiment_metrics_payload(
            normalized_score=normalized_score,
            recent_count=recent_count,
            informative_count=informative_count,
            article_metrics=article_metrics,
        ),
    }


def _resolve_news_sentiment_signal(*, normalized_score: float, informative_count: int) -> tuple[int, float, float]:
    direction = 1 if normalized_score > 0.08 else -1 if normalized_score < -0.08 else 0
    confidence = min(100.0, abs(normalized_score) * 130.0)
    completeness = min(1.0, informative_count / 3.0)
    return direction, confidence, completeness


def _build_news_sentiment_metrics_payload(
    *,
    normalized_score: float,
    recent_count: int,
    informative_count: int,
    article_metrics: list[dict],
) -> dict[str, float | int | list[dict]]:
    return {
        "weighted_score": normalized_score,
        "recent_articles": recent_count,
        "informative_articles": informative_count,
        "articles": article_metrics[:5],
    }


def _score_news_article(item: CompanyNews, trade_dt: datetime) -> dict:
    days_old = _resolve_news_article_days_old(item.date, trade_dt)
    decay = compute_event_decay(days_old)
    pos_hits, neg_hits = _count_event_keyword_hits(item)
    direction, strength = _resolve_news_direction_and_strength(pos_hits, neg_hits)
    effective_weight = decay * _event_weight_multiplier(days_old, strength)
    confidence = min(100.0, 45.0 + strength * 18.0) if strength > 0 else 0.0
    return _build_news_article_metrics(item.title, days_old, decay, direction, confidence, effective_weight)


def _build_news_article_metrics(
    title: str,
    days_old: int,
    decay: float,
    direction: int,
    confidence: float,
    effective_weight: float,
) -> dict[str, str | int | float]:
    return {
        "title": title,
        "days_old": days_old,
        "decay": decay,
        "direction": direction,
        "confidence": confidence,
        "effective_weight": effective_weight,
    }


def _resolve_news_article_days_old(news_date: str, trade_dt: datetime) -> int:
    item_dt = _safe_date(news_date)
    return (trade_dt - item_dt).days if item_dt else 0


def _resolve_news_direction_and_strength(pos_hits: int, neg_hits: int) -> tuple[int, int]:
    if pos_hits > neg_hits:
        return 1, pos_hits - neg_hits
    if neg_hits > pos_hits:
        return -1, neg_hits - pos_hits
    return 0, 0


def _aggregate_news_article_metrics(article_metrics: list[dict]) -> tuple[float, int, int]:
    weighted_score = 0.0
    total_weight = 0.0
    recent_count = 0
    informative_count = 0
    for metric in article_metrics:
        weighted_delta, effective_weight, recent_delta, informative_delta = _resolve_news_metric_contribution(metric)
        weighted_score += weighted_delta
        total_weight += effective_weight
        recent_count += recent_delta
        informative_count += informative_delta
    normalized_score = weighted_score / total_weight if total_weight > 0 else 0.0
    return normalized_score, recent_count, informative_count


def _resolve_news_metric_contribution(metric: dict) -> tuple[float, float, int, int]:
    effective_weight = float(metric["effective_weight"])
    confidence = float(metric["confidence"])
    direction = int(metric["direction"])
    return (
        direction * (confidence / 100.0) * effective_weight,
        effective_weight,
        1 if int(metric["days_old"]) <= 5 else 0,
        1 if effective_weight > 0 else 0,
    )


def _score_insider_conviction(trades: list[InsiderTrade]) -> SubFactor:
    if not trades:
        return _make_sub_factor("insider_conviction", 0, 0.0, EVENT_SUBFACTOR_WEIGHTS["insider_conviction"], completeness=0.0)
    analysis = analyze_insider_conviction(trades)
    direction, confidence = _resolve_insider_conviction_direction_and_confidence(float(analysis["score"]))
    return _make_sub_factor(
        "insider_conviction",
        direction,
        confidence,
        EVENT_SUBFACTOR_WEIGHTS["insider_conviction"],
        metrics=analysis,
    )


def _resolve_insider_conviction_direction_and_confidence(score: float) -> tuple[int, float]:
    return (1 if score > 0.6 else -1 if score < 0.4 else 0), abs(score - 0.5) * 200.0


def _score_event_freshness(news_items: list[CompanyNews], trade_date: str) -> SubFactor:
    if not news_items:
        return _make_sub_factor("event_freshness", 0, 0.0, EVENT_SUBFACTOR_WEIGHTS["event_freshness"], completeness=0.0)
    return _build_event_freshness_factor(_build_event_freshness_snapshot(news_items[0], trade_date))


@dataclass(frozen=True)
class EventFreshnessSnapshot:
    days_old: int
    decay: float
    positive_hits: int
    negative_hits: int
    freshness_weight: float
    strength: int


def _build_event_freshness_snapshot(item: CompanyNews, trade_date: str) -> EventFreshnessSnapshot:
    days_old = _resolve_event_freshness_days_old(item.date, trade_date)
    decay = compute_event_decay(days_old)
    positive_hits, negative_hits = _count_event_keyword_hits(item)
    strength = abs(positive_hits - negative_hits)
    freshness_weight = _event_weight_multiplier(days_old, strength)
    return EventFreshnessSnapshot(
        days_old=days_old,
        decay=decay,
        positive_hits=positive_hits,
        negative_hits=negative_hits,
        freshness_weight=freshness_weight,
        strength=strength,
    )


def _build_event_freshness_factor(snapshot: EventFreshnessSnapshot) -> SubFactor:
    direction = _resolve_event_freshness_direction(
        pos_hits=snapshot.positive_hits,
        neg_hits=snapshot.negative_hits,
        strength=snapshot.strength,
        freshness_weight=snapshot.freshness_weight,
    )
    return _make_sub_factor(
        "event_freshness",
        direction,
        snapshot.decay * snapshot.freshness_weight * 100.0,
        EVENT_SUBFACTOR_WEIGHTS["event_freshness"],
        metrics=_build_event_freshness_metrics(snapshot),
    )


def _build_event_freshness_metrics(snapshot: EventFreshnessSnapshot) -> dict[str, int | float]:
    return {
        "days_old": snapshot.days_old,
        "decay": snapshot.decay,
        "positive_hits": snapshot.positive_hits,
        "negative_hits": snapshot.negative_hits,
        "freshness_weight": snapshot.freshness_weight,
    }


def _resolve_event_freshness_days_old(news_date: str, trade_date: str) -> int:
    trade_dt = datetime.strptime(trade_date, "%Y%m%d")
    latest_dt = _safe_date(news_date)
    return (trade_dt - latest_dt).days if latest_dt else 0


def _count_event_keyword_hits(news_item: CompanyNews) -> tuple[int, int]:
    text = f"{news_item.title or ''} {news_item.content or ''}".lower()
    pos_hits = sum(1 for word in POSITIVE_NEWS_KEYWORDS if word in text)
    neg_hits = sum(1 for word in NEGATIVE_NEWS_KEYWORDS if word in text)
    return pos_hits, neg_hits


def _resolve_event_freshness_direction(*, pos_hits: int, neg_hits: int, strength: int, freshness_weight: float) -> int:
    if freshness_weight <= 0 or freshness_weight < 0.35 or strength < 2:
        return 0
    if pos_hits > neg_hits:
        return 1
    if neg_hits > pos_hits:
        return -1
    return 0


def score_event_sentiment_strategy(ticker: str, trade_date: str) -> StrategySignal:
    start_date, end_date = _resolve_event_sentiment_date_window(trade_date)
    news_items, trades = _load_event_sentiment_inputs(ticker=ticker, start_date=start_date, end_date=end_date)
    return _build_event_sentiment_strategy_signal(news_items=news_items, trades=trades, trade_date=trade_date)


def _build_event_sentiment_strategy_signal(
    *, news_items: list[CompanyNews], trades: list[InsiderTrade], trade_date: str
) -> StrategySignal:
    return aggregate_sub_factors(
        _build_event_sentiment_sub_factors(news_items=news_items, trades=trades, trade_date=trade_date)
    )


def _resolve_event_sentiment_date_window(trade_date: str) -> tuple[str, str]:
    trade_dt = datetime.strptime(trade_date, "%Y%m%d")
    return (trade_dt - timedelta(days=30)).strftime("%Y-%m-%d"), trade_dt.strftime("%Y-%m-%d")


def _load_event_sentiment_inputs(*, ticker: str, start_date: str, end_date: str) -> tuple[list[CompanyNews], list[InsiderTrade]]:
    news_items = get_company_news(ticker=ticker, start_date=start_date, end_date=end_date, limit=50)
    trades = get_insider_trades(ticker=ticker, end_date=end_date, start_date=start_date, limit=100)
    return news_items, trades


def _build_event_sentiment_sub_factors(
    *,
    news_items: list[CompanyNews],
    trades: list[InsiderTrade],
    trade_date: str,
) -> list[SubFactor]:
    return _assemble_event_sentiment_sub_factors(
        _score_news_sentiment(news_items, trade_date),
        _score_insider_conviction(trades),
        _score_event_freshness(news_items, trade_date),
    )


def _assemble_event_sentiment_sub_factors(
    news_sentiment: SubFactor, insider_conviction: SubFactor, event_freshness: SubFactor
) -> list[SubFactor]:
    return [news_sentiment, insider_conviction, event_freshness]


def _build_symbol_to_industry_map(stock_basic: pd.DataFrame, sw_map: dict[str, str]) -> dict[str, str]:
    symbol_to_industry: dict[str, str] = {}
    for _, row in stock_basic.iterrows():
        ts_code = str(row["ts_code"])
        symbol = str(row["symbol"])
        symbol_to_industry[symbol] = sw_map.get(ts_code, str(row.get("industry", "")))
    return symbol_to_industry


def _group_industry_pe_values(daily_df: pd.DataFrame, symbol_to_industry: dict[str, str]) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for _, row in daily_df.iterrows():
        pe_ttm = row.get("pe_ttm")
        if pd.isna(pe_ttm) or pe_ttm is None or float(pe_ttm) <= 0:
            continue
        symbol = str(row["ts_code"]).split(".")[0]
        industry = symbol_to_industry.get(symbol, "")
        if industry:
            grouped[industry].append(float(pe_ttm))
    return grouped


def _build_industry_pe_medians(trade_date: str) -> dict[str, float]:
    daily_df = get_daily_basic_batch(trade_date)
    stock_basic = get_all_stock_basic()
    sw_map = get_sw_industry_classification() or {}
    if daily_df is None or daily_df.empty or stock_basic is None or stock_basic.empty:
        return {}

    symbol_to_industry = _build_symbol_to_industry_map(stock_basic, sw_map)
    grouped = _group_industry_pe_values(daily_df, symbol_to_industry)
    return {industry: median(values) for industry, values in grouped.items() if values}


def score_candidate(
    candidate: CandidateStock,
    trade_date: str,
    industry_pe_medians: Optional[dict[str, float]] = None,
    prices_df: Optional[pd.DataFrame] = None,
) -> dict[str, StrategySignal]:
    prices_df = prices_df if prices_df is not None else _load_price_frame(candidate.ticker, trade_date)
    industry_pe_medians = industry_pe_medians if industry_pe_medians is not None else {}
    return {
        "trend": score_trend_strategy(prices_df),
        "mean_reversion": score_mean_reversion_strategy(prices_df),
        "fundamental": score_fundamental_strategy(candidate.ticker, trade_date, candidate.industry_sw, industry_pe_medians),
        "event_sentiment": score_event_sentiment_strategy(candidate.ticker, trade_date),
    }


def _compute_light_signals(candidate: CandidateStock, trade_date: str) -> tuple[dict[str, StrategySignal], pd.DataFrame]:
    prices_df = _load_price_frame(candidate.ticker, trade_date)
    return _build_light_signal_map(prices_df), prices_df


def _build_light_signal_map(prices_df: pd.DataFrame) -> dict[str, StrategySignal]:
    return {
        "trend": score_trend_strategy(prices_df),
        "mean_reversion": score_mean_reversion_strategy(prices_df),
        "fundamental": _empty_signal(),
        "event_sentiment": _empty_signal(),
    }


def _provisional_score(signals: dict[str, StrategySignal]) -> float:
    score = 0.0
    total_weight = 0.0
    for name, weight in LIGHT_STRATEGY_WEIGHTS.items():
        signal = signals.get(name)
        if signal is None or signal.completeness <= 0:
            continue
        total_weight += weight
        score += weight * signal.direction * (signal.confidence / 100.0) * signal.completeness
    if total_weight <= 0:
        return 0.0
    return score / total_weight


def _rank_candidates_for_technical_stage(candidates: list[CandidateStock]) -> list[CandidateStock]:
    return sorted(
        candidates,
        key=_technical_stage_ranking_key,
        reverse=True,
    )


def _technical_stage_ranking_key(candidate: CandidateStock) -> tuple[int, float, float, str]:
    liquidity_band = int(float(candidate.avg_volume_20d) / max(TECHNICAL_STAGE_LIQUIDITY_RANK_BUCKET, 1.0))
    return (
        liquidity_band,
        -float(candidate.market_cap),
        float(candidate.avg_volume_20d),
        str(candidate.ticker),
    )


def _initialize_score_batch_results(candidates: list[CandidateStock]) -> dict[str, dict[str, StrategySignal]]:
    return {
        candidate.ticker: {
            "trend": _empty_signal(),
            "mean_reversion": _empty_signal(),
            "fundamental": _empty_signal(),
            "event_sentiment": _empty_signal(),
        }
        for candidate in candidates
    }


def _build_provisional_ranking(
    candidates: list[CandidateStock],
    trade_date: str,
    results: dict[str, dict[str, StrategySignal]],
) -> list[tuple[float, CandidateStock]]:
    provisional_ranking: list[tuple[float, CandidateStock]] = []
    technical_candidates = _rank_candidates_for_technical_stage(candidates)[:TECHNICAL_SCORE_MAX_CANDIDATES]

    for candidate in technical_candidates:
        light_signals, _ = _compute_light_signals(candidate, trade_date)
        results[candidate.ticker] = light_signals
        provisional_ranking.append((_provisional_score(light_signals), candidate))
    return _append_unranked_candidates_to_provisional_ranking(provisional_ranking, candidates)


def _append_unranked_candidates_to_provisional_ranking(
    provisional_ranking: list[tuple[float, CandidateStock]], candidates: list[CandidateStock]
) -> list[tuple[float, CandidateStock]]:
    ranked_tickers = {ranked_candidate.ticker for _, ranked_candidate in provisional_ranking}
    for candidate in candidates:
        if candidate.ticker in ranked_tickers:
            continue
        provisional_ranking.append((0.0, candidate))
    return provisional_ranking


def _rank_candidates_for_heavy_scoring(provisional_ranking: list[tuple[float, CandidateStock]]) -> list[tuple[float, CandidateStock]]:
    return sorted(
        provisional_ranking,
        key=_heavy_score_ranking_key,
        reverse=True,
    )


def _heavy_score_ranking_key(item: tuple[float, CandidateStock]) -> tuple[float, float, float]:
    return item[0], item[1].avg_volume_20d, item[1].market_cap


def _select_fundamental_candidates(
    ranked_candidates: list[tuple[float, CandidateStock]],
    results: dict[str, dict[str, StrategySignal]],
) -> list[CandidateStock]:
    return [
        candidate
        for score, candidate in ranked_candidates
        if _is_heavy_score_eligible(score, results.get(candidate.ticker, {}))
    ][:FUNDAMENTAL_SCORE_MAX_CANDIDATES]


def _is_heavy_score_eligible(score: float, signals: dict[str, StrategySignal]) -> bool:
    return score >= HEAVY_SCORE_MIN_PROVISIONAL_SCORE and _has_positive_trend_confirmation(signals)


def _has_positive_trend_confirmation(signals: dict[str, StrategySignal]) -> bool:
    trend_signal = signals.get("trend")
    if trend_signal is None or trend_signal.completeness <= 0:
        return False
    return trend_signal.direction > 0 and trend_signal.confidence >= HEAVY_SCORE_MIN_TREND_CONFIDENCE


def _populate_heavy_signals(
    results: dict[str, dict[str, StrategySignal]],
    fundamental_candidates: list[CandidateStock],
    trade_date: str,
    industry_pe_medians: dict[str, float],
) -> None:
    for candidate in fundamental_candidates:
        results[candidate.ticker]["fundamental"] = score_fundamental_strategy(
            candidate.ticker,
            trade_date,
            candidate.industry_sw,
            industry_pe_medians,
        )

    for candidate in _select_event_sentiment_candidates(fundamental_candidates):
        results[candidate.ticker]["event_sentiment"] = score_event_sentiment_strategy(candidate.ticker, trade_date)


def _select_event_sentiment_candidates(fundamental_candidates: list[CandidateStock]) -> list[CandidateStock]:
    return fundamental_candidates[:EVENT_SENTIMENT_MAX_CANDIDATES]


def score_batch(candidates: list[CandidateStock], trade_date: str) -> dict[str, dict[str, StrategySignal]]:
    industry_pe_medians = _build_industry_pe_medians(trade_date)
    results = _initialize_score_batch_results(candidates)
    fundamental_candidates = _prepare_heavy_score_candidates(candidates, trade_date, results)
    _populate_heavy_signals(results, fundamental_candidates, trade_date, industry_pe_medians)
    return results


def _prepare_heavy_score_candidates(
    candidates: list[CandidateStock],
    trade_date: str,
    results: dict[str, dict[str, StrategySignal]],
) -> list[CandidateStock]:
    provisional_ranking = _build_provisional_ranking(candidates, trade_date, results)
    ranked_candidates = _rank_candidates_for_heavy_scoring(provisional_ranking)
    return _select_fundamental_candidates(ranked_candidates, results)
