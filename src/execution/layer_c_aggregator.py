"""Layer C 聚合器。"""

from __future__ import annotations

from collections import defaultdict

from src.execution.models import LayerCResult
from src.screening.models import FusedScore, StrategySignal

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

DEFAULT_AGENT_WEIGHTS = {agent_id: 0.06 for agent_id in INVESTOR_AGENT_IDS}
DEFAULT_AGENT_WEIGHTS.update({agent_id: (0.28 / len(ANALYST_AGENT_IDS)) for agent_id in ANALYST_AGENT_IDS})


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


def aggregate_layer_c_results(
    fused_scores: list[FusedScore],
    analyst_signals: dict[str, dict[str, dict]],
    agent_weights: dict[str, float] | None = None,
) -> list[LayerCResult]:
    agent_weights = agent_weights or DEFAULT_AGENT_WEIGHTS
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
        normalized_weights = _normalize_agent_weights(ticker_agent_signals, agent_weights)
        score_c = 0.0
        for agent_id, signal in ticker_agent_signals.items():
            score_c += normalized_weights.get(agent_id, 0.0) * signal.direction * (signal.confidence / 100.0) * signal.completeness
        score_c = max(-1.0, min(1.0, score_c))

        score_final = (0.4 * fused.score_b) + (0.6 * score_c)
        bc_conflict = None
        decision = fused.decision
        if fused.score_b > 0.50 and score_c < 0:
            bc_conflict = "b_strong_buy_c_negative"
            decision = "watch"
        if fused.score_b > 0 and score_c < -0.30:
            bc_conflict = "b_positive_c_strong_bearish"
            decision = "avoid"

        results.append(
            LayerCResult(
                ticker=ticker,
                score_c=score_c,
                score_final=score_final,
                score_b=fused.score_b,
                agent_signals=ticker_agent_signals,
                bc_conflict=bc_conflict,
                decision=decision,
            )
        )

    return results
