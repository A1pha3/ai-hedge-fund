"""
Shared utilities for strategy scoring.

Contains the sub-factor aggregation framework and small helper functions
used by all strategy scorer modules.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.screening.models import StrategySignal, SubFactor
from src.utils.env_helpers import get_env_flag
from src.utils.numeric import clip

# ---------------------------------------------------------------------------
# Weight constants (shared across scorer modules)
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _signal_to_direction(signal: str) -> int:
    mapping = {"bullish": 1, "neutral": 0, "bearish": -1}
    return mapping.get(str(signal).lower(), 0)


def _get_trend_subfactor_weights() -> dict[str, float]:
    if get_env_flag("LAYER_B_ANALYSIS_ENABLE_LONG_TREND_ALIGNMENT", default=True):
        return TREND_SUBFACTOR_WEIGHTS_WITH_LONG_TREND
    return TREND_SUBFACTOR_WEIGHTS


# ---------------------------------------------------------------------------
# Sub-factor factory
# ---------------------------------------------------------------------------


def _make_sub_factor(
    name: str,
    direction: int,
    confidence: float,
    weight: float,
    completeness: float = 1.0,
    metrics: dict | None = None,
) -> SubFactor:
    return SubFactor(
        name=name,
        direction=direction,
        confidence=clip(confidence, 0.0, 100.0),
        completeness=clip(completeness, 0.0, 1.0),
        weight=weight,
        metrics=metrics or {},
    )


# ---------------------------------------------------------------------------
# Aggregation framework
# ---------------------------------------------------------------------------


def derive_completeness(sub_factors: Iterable[SubFactor]) -> float:
    available = [factor for factor in sub_factors if factor.completeness > 0]
    if not available:
        return 0.0

    total_weight = sum(factor.weight for factor in available)
    if total_weight <= 0:
        return 0.0

    return clip(
        sum((factor.weight / total_weight) * factor.completeness for factor in available),
        0.0,
        1.0,
    )


def aggregate_sub_factors(sub_factors: list[SubFactor]) -> StrategySignal:
    """Aggregate sub-factors into a single strategy signal."""
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
        confidence=clip(confidence, 0.0, 100.0),
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
