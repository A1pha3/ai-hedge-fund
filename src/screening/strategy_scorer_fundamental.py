"""
Fundamental strategy sub-factor scoring functions.

Profitability, growth, financial health, growth valuation, industry PE,
and quality cap logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agents.growth_agent import (
    analyze_growth_trends,
    analyze_valuation,
    check_financial_health,
)
from src.data.models import FinancialMetrics
from src.screening.models import StrategySignal, SubFactor
from src.screening.strategy_scorer_utils import (
    FUNDAMENTAL_SUBFACTOR_WEIGHTS,
    aggregate_sub_factors,
    _make_sub_factor,
)
from src.utils.env_helpers import get_env_mode as _get_env_mode
from src.tools.api import get_financial_metrics


@dataclass(frozen=True)
class ProfitabilityEvaluationState:
    available: int
    positive: int
    zero_pass_mode: str
    metrics_payload: dict[str, float | int | str | None]


# ---------------------------------------------------------------------------
# Profitability
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Growth, financial health, growth valuation
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Industry PE
# ---------------------------------------------------------------------------

def _score_industry_pe(metrics: FinancialMetrics, industry_name: str, industry_pe_medians: dict[str, float] | None) -> SubFactor:
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
    industry_pe_medians: dict[str, float] | None,
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


# ---------------------------------------------------------------------------
# Quality cap
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Strategy orchestrator
# ---------------------------------------------------------------------------

def score_fundamental_strategy(
    ticker: str,
    trade_date: str,
    industry_name: str = "",
    industry_pe_medians: dict[str, float] | None = None,
) -> StrategySignal:
    metrics_list = get_financial_metrics(ticker=ticker, end_date=trade_date, period="ttm", limit=8)
    if not metrics_list:
        return StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={})

    sub_factors = _build_fundamental_sub_factors(
        metrics_list=metrics_list,
        industry_name=industry_name,
        industry_pe_medians=industry_pe_medians,
    )
    return _apply_fundamental_quality_cap(aggregate_sub_factors(sub_factors))


def _build_fundamental_sub_factors(
    *,
    metrics_list: list[FinancialMetrics],
    industry_name: str,
    industry_pe_medians: dict[str, float] | None,
) -> list[SubFactor]:
    latest = metrics_list[0]
    return [
        _score_profitability(latest),
        _score_growth(metrics_list),
        _score_financial_health(latest),
        _score_growth_valuation(latest),
        _score_industry_pe(latest, industry_name, industry_pe_medians),
    ]
