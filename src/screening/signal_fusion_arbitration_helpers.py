from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable

from src.screening.models import ArbitrationAction, DEFAULT_STRATEGY_WEIGHTS, MarketState, StrategySignal

SHORT_HOLD_STRATEGIES = {"trend", "event_sentiment"}
LONG_HOLD_STRATEGIES = {"fundamental"}


@dataclass
class ArbitrationState:
    weights: dict[str, float]
    arbitration_applied: list[str] = field(default_factory=list)
    hold_hint: str | None = None
    forced_avoid: bool = False


def initialize_arbitration_state(market_state: MarketState) -> ArbitrationState:
    return ArbitrationState(weights=market_state.adjusted_weights or DEFAULT_STRATEGY_WEIGHTS.copy())


def maybe_apply_forced_avoid(
    *,
    ticker: str,
    signals: dict[str, StrategySignal],
    state: ArbitrationState,
    trade_date: str | None,
    maybe_release_cooldown_early: Callable[[str, str, StrategySignal], bool],
    has_quality_first_red_flag: Callable[[dict[str, StrategySignal]], bool],
    add_cooldown: Callable[[str, str, int], None],
) -> bool:
    fundamental_signal = signals.get("fundamental", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))
    if trade_date:
        maybe_release_cooldown_early(ticker, trade_date, fundamental_signal)
    should_avoid = has_quality_first_red_flag(signals) or _has_bearish_fundamental_consensus(signals, fundamental_signal)
    if not should_avoid:
        return False
    state.arbitration_applied.append(ArbitrationAction.AVOID.value)
    if trade_date:
        add_cooldown(ticker, trade_date, days=15)
    state.forced_avoid = True
    return True


def apply_hold_hint(
    *,
    signals: dict[str, StrategySignal],
    state: ArbitrationState,
    signal_contribution: Callable[[float, StrategySignal], float],
) -> None:
    short_contrib = sum(signal_contribution(state.weights.get(name, 0.0), signal) for name, signal in signals.items() if name in SHORT_HOLD_STRATEGIES)
    long_contrib = sum(signal_contribution(state.weights.get(name, 0.0), signal) for name, signal in signals.items() if name in LONG_HOLD_STRATEGIES)
    total_contrib = sum(signal_contribution(state.weights.get(name, 0.0), signal) for name, signal in signals.items())
    if total_contrib <= 0:
        return
    if short_contrib / total_contrib >= 0.60:
        state.arbitration_applied.append(ArbitrationAction.SHORT_HOLD.value)
        state.hold_hint = ArbitrationAction.SHORT_HOLD.value
    elif long_contrib / total_contrib >= 0.60:
        state.arbitration_applied.append(ArbitrationAction.LONG_HOLD.value)
        state.hold_hint = ArbitrationAction.LONG_HOLD.value


def apply_hurst_conflict_resolution(*, signals: dict[str, StrategySignal], state: ArbitrationState) -> None:
    trend_signal = signals.get("trend")
    mean_reversion_signal = signals.get("mean_reversion")
    if not _has_conflicting_trend_and_reversion(trend_signal, mean_reversion_signal):
        return
    hurst = _extract_hurst_exponent(mean_reversion_signal)
    if hurst is not None and hurst > 0.55:
        mean_reversion_signal.confidence *= 0.5
        state.arbitration_applied.append(ArbitrationAction.TRUST_TREND.value)
    elif hurst is not None and hurst < 0.45:
        trend_signal.confidence *= 0.5
        state.arbitration_applied.append(ArbitrationAction.TRUST_REVERSION.value)
    else:
        trend_signal.confidence *= 0.5
        mean_reversion_signal.confidence *= 0.5
        state.arbitration_applied.append(ArbitrationAction.BOTH_DEMOTE.value)


def _has_bearish_fundamental_consensus(signals: dict[str, StrategySignal], fundamental_signal: StrategySignal) -> bool:
    return fundamental_signal.direction == -1 and any(signal.direction == -1 and signal.confidence >= 75 for signal in signals.values())


def _has_conflicting_trend_and_reversion(trend_signal: StrategySignal | None, mean_reversion_signal: StrategySignal | None) -> bool:
    return (
        trend_signal is not None
        and mean_reversion_signal is not None
        and trend_signal.direction != 0
        and mean_reversion_signal.direction != 0
        and trend_signal.direction != mean_reversion_signal.direction
    )


def _extract_hurst_exponent(mean_reversion_signal: StrategySignal) -> float | None:
    sub_factor = mean_reversion_signal.sub_factors.get("hurst_regime", {})
    metrics = sub_factor.get("metrics", {}) if isinstance(sub_factor, dict) else {}
    return metrics.get("hurst_exponent")
