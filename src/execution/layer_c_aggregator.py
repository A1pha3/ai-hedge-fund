"""Layer C 聚合器。"""

from __future__ import annotations

from collections import defaultdict

from src.execution.models import LayerCResult
from src.screening.models import FusedScore, StrategySignal
from src.utils.env_helpers import get_env_float

INVESTOR_AGENT_IDS = [
    "aswath_damodaran_agent",
    "ben_graham_agent",
    "bill_ackman_agent",
    "cathie_wood_agent",
    "charlie_munger_agent",
    "michael_burry_agent",
    "mohnish_pabrai_agent",
    "peter_lynch_agent",
    "phil_fisher_agent",
    "rakesh_jhunjhunwala_agent",
    "stanley_druckenmiller_agent",
    "warren_buffett_agent",
]

ANALYST_AGENT_IDS = [
    "technical_analyst_agent",
    "fundamentals_analyst_agent",
    "growth_analyst_agent",
    "news_sentiment_analyst_agent",
    "sentiment_analyst_agent",
    "valuation_analyst_agent",
]

DEFAULT_AGENT_WEIGHTS = dict.fromkeys(INVESTOR_AGENT_IDS, 0.06)
DEFAULT_AGENT_WEIGHTS.update({agent_id: (0.28 / len(ANALYST_AGENT_IDS)) for agent_id in ANALYST_AGENT_IDS})

QUALITY_SUBFACTOR_WEIGHTS = {
    "profitability": 0.40,
    "financial_health": 0.35,
    "growth": 0.25,
}


LAYER_C_INVESTOR_WEIGHT_SCALE = get_env_float("DAILY_PIPELINE_LAYER_C_INVESTOR_WEIGHT_SCALE", 0.90)
LAYER_C_BEARISH_INVESTOR_CONTRIBUTION_SCALE = get_env_float("DAILY_PIPELINE_LAYER_C_BEARISH_INVESTOR_CONTRIBUTION_SCALE", 0.15)
LAYER_C_BLEND_B_WEIGHT = get_env_float("DAILY_PIPELINE_LAYER_C_BLEND_B_WEIGHT", 0.25)
LAYER_C_BLEND_C_WEIGHT = get_env_float("DAILY_PIPELINE_LAYER_C_BLEND_C_WEIGHT", 0.75)
LAYER_C_AVOID_SCORE_C_THRESHOLD = get_env_float("DAILY_PIPELINE_LAYER_C_AVOID_SCORE_C_THRESHOLD", -0.30)


def _resolve_layer_c_blend_weights() -> tuple[float, float]:
    b_weight = max(0.0, LAYER_C_BLEND_B_WEIGHT)
    c_weight = max(0.0, LAYER_C_BLEND_C_WEIGHT)
    total = b_weight + c_weight
    if total <= 0:
        return 0.55, 0.45
    return b_weight / total, c_weight / total


def _apply_investor_weight_scale(agent_weights: dict[str, float]) -> dict[str, float]:
    scaled_weights = dict(agent_weights)
    for agent_id in INVESTOR_AGENT_IDS:
        if agent_id in scaled_weights:
            scaled_weights[agent_id] = scaled_weights[agent_id] * LAYER_C_INVESTOR_WEIGHT_SCALE
    return scaled_weights


def _scale_investor_bearish_contribution(agent_id: str, contribution: float) -> float:
    if agent_id not in INVESTOR_AGENT_IDS or contribution >= 0:
        return contribution
    return contribution * max(0.0, min(1.0, LAYER_C_BEARISH_INVESTOR_CONTRIBUTION_SCALE))


def _build_agent_contribution_summary(agent_signals: dict[str, StrategySignal], normalized_weights: dict[str, float]) -> tuple[dict, float, float]:
    contributions: list[dict] = []
    cohort_contributions = {"investor": 0.0, "analyst": 0.0, "other": 0.0}
    raw_score_c = 0.0
    adjusted_score_c = 0.0

    for agent_id, signal in agent_signals.items():
        normalized_weight = normalized_weights.get(agent_id, 0.0)
        raw_contribution = normalized_weight * signal.direction * (signal.confidence / 100.0) * signal.completeness
        contribution = _scale_investor_bearish_contribution(agent_id, raw_contribution)
        if agent_id in INVESTOR_AGENT_IDS:
            cohort = "investor"
        elif agent_id in ANALYST_AGENT_IDS:
            cohort = "analyst"
        else:
            cohort = "other"
        cohort_contributions[cohort] += contribution
        raw_score_c += raw_contribution
        adjusted_score_c += contribution
        contributions.append(
            {
                "agent_id": agent_id,
                "contribution": round(contribution, 4),
                "raw_contribution": round(raw_contribution, 4),
                "normalized_weight": round(normalized_weight, 4),
                "direction": signal.direction,
                "confidence": round(signal.confidence, 2),
                "completeness": round(signal.completeness, 2),
                "cohort": cohort,
            }
        )

    positive = [item for item in contributions if item["contribution"] > 0]
    negative = [item for item in contributions if item["contribution"] < 0]
    neutral = [item for item in contributions if item["contribution"] == 0]

    return (
        {
            "active_agent_count": len(contributions),
            "positive_agent_count": len(positive),
            "negative_agent_count": len(negative),
            "neutral_agent_count": len(neutral),
            "raw_score_c": round(raw_score_c, 4),
            "adjusted_score_c": round(adjusted_score_c, 4),
            "cohort_contributions": {name: round(value, 4) for name, value in cohort_contributions.items()},
            "top_positive_agents": sorted(positive, key=lambda item: item["contribution"], reverse=True)[:3],
            "top_negative_agents": sorted(negative, key=lambda item: item["contribution"])[:3],
        },
        raw_score_c,
        adjusted_score_c,
    )


def convert_agent_signal_to_strategy_signal(agent_payload: dict) -> StrategySignal:
    signal = str(agent_payload.get("signal", "neutral")).lower()
    direction = 1 if signal == "bullish" else -1 if signal == "bearish" else 0
    confidence = float(agent_payload.get("confidence", 0.0) or 0.0)
    reasoning = agent_payload.get("reasoning")

    completeness = 1.0
    if signal not in {"bullish", "bearish", "neutral"}:
        completeness = 0.0
        direction = 0
    if isinstance(reasoning, dict) and reasoning.get("error"):
        completeness = 0.0
    if confidence <= 0:
        completeness = 0.0 if reasoning else min(completeness, 0.5)

    return StrategySignal(
        direction=direction,
        confidence=max(0.0, min(100.0, confidence)),
        completeness=max(0.0, min(1.0, completeness)),
        sub_factors={},
    )


def _normalize_agent_weights(agent_signals: dict[str, StrategySignal], agent_weights: dict[str, float]) -> dict[str, float]:
    active = {agent_id: agent_weights.get(agent_id, 0.0) for agent_id, signal in agent_signals.items() if signal.completeness > 0}
    total = sum(active.values())
    if total <= 0:
        return {}
    return {agent_id: weight / total for agent_id, weight in active.items()}


def _derive_quality_score(fused: FusedScore) -> float:
    fundamental_signal = fused.strategy_signals.get("fundamental")
    if not fundamental_signal or fundamental_signal.completeness <= 0:
        return 0.5

    weighted_total = 0.0
    weighted_score = 0.0
    for sub_factor_name, weight in QUALITY_SUBFACTOR_WEIGHTS.items():
        snapshot = fundamental_signal.sub_factors.get(sub_factor_name, {})
        if not isinstance(snapshot, dict):
            continue
        direction = snapshot.get("direction")
        if direction not in {-1, 0, 1}:
            continue
        confidence = max(0.0, min(100.0, float(snapshot.get("confidence", 0.0) or 0.0)))
        completeness = max(0.0, min(1.0, float(snapshot.get("completeness", 1.0) or 1.0)))
        effective_weight = weight * completeness
        if effective_weight <= 0:
            continue
        sub_score = max(0.0, min(1.0, 0.5 + (0.5 * direction * (confidence / 100.0))))
        weighted_total += effective_weight
        weighted_score += effective_weight * sub_score

    if weighted_total <= 0:
        return max(
            0.0,
            min(
                1.0,
                0.5 + (0.5 * fundamental_signal.direction * (fundamental_signal.confidence / 100.0) * fundamental_signal.completeness),
            ),
        )
    return max(0.0, min(1.0, weighted_score / weighted_total))


def aggregate_layer_c_results(
    fused_scores: list[FusedScore],
    analyst_signals: dict[str, dict[str, dict]],
    agent_weights: dict[str, float] | None = None,
) -> list[LayerCResult]:
    agent_weights = agent_weights or DEFAULT_AGENT_WEIGHTS
    adjusted_agent_weights = _apply_investor_weight_scale(agent_weights)
    blend_b_weight, blend_c_weight = _resolve_layer_c_blend_weights()
    results: list[LayerCResult] = []
    fused_by_ticker = {item.ticker: item for item in fused_scores}

    signals_by_ticker: dict[str, dict[str, StrategySignal]] = defaultdict(dict)
    for agent_id, ticker_payload in analyst_signals.items():
        if agent_id not in agent_weights:
            continue
        for ticker, payload in ticker_payload.items():
            signals_by_ticker[ticker][agent_id] = convert_agent_signal_to_strategy_signal(payload)

    for ticker, fused in fused_by_ticker.items():
        ticker_agent_signals = signals_by_ticker.get(ticker, {})
        normalized_weights = _normalize_agent_weights(ticker_agent_signals, adjusted_agent_weights)
        agent_contribution_summary, raw_score_c, adjusted_score_c = _build_agent_contribution_summary(ticker_agent_signals, normalized_weights)
        raw_score_c = max(-1.0, min(1.0, raw_score_c))
        score_c = max(-1.0, min(1.0, adjusted_score_c))
        quality_score = _derive_quality_score(fused)

        score_final = (blend_b_weight * fused.score_b) + (blend_c_weight * score_c)
        bc_conflict = None
        decision = fused.decision
        if fused.score_b > 0.50 and raw_score_c < 0:
            bc_conflict = "b_strong_buy_c_negative"
            decision = "watch"
        if fused.score_b > 0 and raw_score_c < LAYER_C_AVOID_SCORE_C_THRESHOLD:
            bc_conflict = "b_positive_c_strong_bearish"
            decision = "avoid"

        results.append(
            LayerCResult(
                ticker=ticker,
                score_c=score_c,
                score_final=score_final,
                score_b=fused.score_b,
                quality_score=quality_score,
                market_state=fused.market_state.model_dump(mode="json") if fused.market_state is not None else {},
                strategy_signals=fused.strategy_signals,
                agent_signals=ticker_agent_signals,
                agent_contribution_summary=agent_contribution_summary,
                bc_conflict=bc_conflict,
                decision=decision,
            )
        )

    return results
