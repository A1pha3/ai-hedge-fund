"""Layer B 信号融合与冲突仲裁。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from src.screening.candidate_pool import add_cooldown, get_cooled_tickers, load_cooldown_registry, save_cooldown_registry
from src.screening.models import ArbitrationAction, DEFAULT_STRATEGY_WEIGHTS, FusedScore, MarketState, StrategySignal

SHORT_HOLD_STRATEGIES = {"trend", "event_sentiment"}
LONG_HOLD_STRATEGIES = {"fundamental"}


def _normalize_for_available_signals(weights: dict[str, float], signals: dict[str, StrategySignal]) -> dict[str, float]:
    active = {
        name: max(weights.get(name, 0.0), 0.0)
        for name, signal in signals.items()
        if signal.completeness > 0
    }
    total = sum(active.values())
    if total <= 0:
        active = {name: DEFAULT_STRATEGY_WEIGHTS.get(name, 0.0) for name in signals}
        total = sum(active.values())
    return {name: value / total for name, value in active.items()} if total > 0 else {}


def _signal_contribution(weight: float, signal: StrategySignal) -> float:
    return abs(weight * signal.direction * (signal.confidence / 100.0) * signal.completeness)


def maybe_release_cooldown_early(ticker: str, trade_date: str, fundamental_signal: StrategySignal, min_hold_days: int = 5) -> bool:
    if fundamental_signal.direction <= 0:
        return False

    registry = load_cooldown_registry()
    expire_date = registry.get(ticker)
    if not expire_date:
        return False

    expire_dt = datetime.strptime(expire_date, "%Y%m%d")
    trade_dt = datetime.strptime(trade_date, "%Y%m%d")
    approx_start_dt = expire_dt - timedelta(days=int(15 * 1.5))
    if (trade_dt - approx_start_dt).days < min_hold_days:
        return False

    del registry[ticker]
    save_cooldown_registry(registry)
    return True


def apply_arbitration_rules(
    ticker: str,
    signals: dict[str, StrategySignal],
    market_state: MarketState,
    trade_date: Optional[str] = None,
) -> tuple[dict[str, StrategySignal], list[str], Optional[str], bool]:
    weights = market_state.adjusted_weights or DEFAULT_STRATEGY_WEIGHTS.copy()
    arbitration_applied: list[str] = []
    hold_hint: Optional[str] = None
    forced_avoid = False

    fundamental_signal = signals.get("fundamental", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))

    if trade_date:
        maybe_release_cooldown_early(ticker, trade_date, fundamental_signal)

    if fundamental_signal.direction == -1 and any(
        signal.direction == -1 and signal.confidence >= 75
        for signal in signals.values()
    ):
        arbitration_applied.append(ArbitrationAction.AVOID.value)
        if trade_date:
            add_cooldown(ticker, trade_date, days=15)
        forced_avoid = True
        return signals, arbitration_applied, hold_hint, forced_avoid

    short_contrib = sum(_signal_contribution(weights.get(name, 0.0), signal) for name, signal in signals.items() if name in SHORT_HOLD_STRATEGIES)
    long_contrib = sum(_signal_contribution(weights.get(name, 0.0), signal) for name, signal in signals.items() if name in LONG_HOLD_STRATEGIES)
    total_contrib = sum(_signal_contribution(weights.get(name, 0.0), signal) for name, signal in signals.items())
    if total_contrib > 0:
        if short_contrib / total_contrib >= 0.60:
            arbitration_applied.append(ArbitrationAction.SHORT_HOLD.value)
            hold_hint = ArbitrationAction.SHORT_HOLD.value
        elif long_contrib / total_contrib >= 0.60:
            arbitration_applied.append(ArbitrationAction.LONG_HOLD.value)
            hold_hint = ArbitrationAction.LONG_HOLD.value

    trend_signal = signals.get("trend")
    mean_reversion_signal = signals.get("mean_reversion")
    if trend_signal and mean_reversion_signal and trend_signal.direction != 0 and mean_reversion_signal.direction != 0 and trend_signal.direction != mean_reversion_signal.direction:
        hurst = None
        sub_factor = mean_reversion_signal.sub_factors.get("hurst_regime", {})
        metrics = sub_factor.get("metrics", {}) if isinstance(sub_factor, dict) else {}
        hurst = metrics.get("hurst_exponent")
        if hurst is not None and hurst > 0.55:
            mean_reversion_signal.confidence *= 0.5
            arbitration_applied.append(ArbitrationAction.TRUST_TREND.value)
        elif hurst is not None and hurst < 0.45:
            trend_signal.confidence *= 0.5
            arbitration_applied.append(ArbitrationAction.TRUST_REVERSION.value)
        else:
            trend_signal.confidence *= 0.5
            mean_reversion_signal.confidence *= 0.5
            arbitration_applied.append(ArbitrationAction.BOTH_DEMOTE.value)

    same_direction = {}
    for signal in signals.values():
        if signal.direction != 0 and signal.confidence > 60:
            same_direction[signal.direction] = same_direction.get(signal.direction, 0) + 1
    if any(count >= 3 for count in same_direction.values()):
        arbitration_applied.append(ArbitrationAction.CONSENSUS_BONUS.value)

    return signals, arbitration_applied, hold_hint, forced_avoid


def compute_score_b(signals: dict[str, StrategySignal], weights: dict[str, float], arbitration_applied: list[str]) -> float:
    normalized_weights = _normalize_for_available_signals(weights, signals)
    score = 0.0
    for name, signal in signals.items():
        weight = normalized_weights.get(name, 0.0)
        score += weight * signal.direction * (signal.confidence / 100.0) * signal.completeness

    if ArbitrationAction.CONSENSUS_BONUS.value in arbitration_applied:
        score *= 1.15
    return max(-1.0, min(1.0, score))


def fuse_signals_for_ticker(
    ticker: str,
    signals: dict[str, StrategySignal],
    market_state: MarketState,
    trade_date: Optional[str] = None,
) -> FusedScore:
    adjusted_signals, arbitration_applied, _, forced_avoid = apply_arbitration_rules(ticker, signals, market_state, trade_date)
    weights_used = _normalize_for_available_signals(market_state.adjusted_weights or DEFAULT_STRATEGY_WEIGHTS, adjusted_signals)

    if forced_avoid:
        score_b = -1.0
        decision = "strong_sell"
    else:
        score_b = compute_score_b(adjusted_signals, weights_used, arbitration_applied)
        decision = FusedScore.classify_decision(score_b)

    return FusedScore(
        ticker=ticker,
        score_b=score_b,
        strategy_signals=adjusted_signals,
        arbitration_applied=arbitration_applied,
        market_state=market_state,
        weights_used=weights_used,
        decision=decision,
    )


def fuse_batch(
    scored_signals: dict[str, dict[str, StrategySignal]],
    market_state: MarketState,
    trade_date: Optional[str] = None,
) -> list[FusedScore]:
    results = []
    current_cooldown = get_cooled_tickers(trade_date) if trade_date else set()
    for ticker, signals in scored_signals.items():
        if trade_date and ticker in current_cooldown and signals.get("fundamental") and signals["fundamental"].direction > 0:
            maybe_release_cooldown_early(ticker, trade_date, signals["fundamental"])
        results.append(fuse_signals_for_ticker(ticker, signals, market_state, trade_date))
    return results
