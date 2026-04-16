"""Layer B 信号融合与冲突仲裁。"""

from __future__ import annotations

from datetime import datetime, timedelta
import os

from src.screening.candidate_pool import add_cooldown, get_cooled_tickers, load_cooldown_registry, save_cooldown_registry
from src.screening.models import ArbitrationAction, DEFAULT_STRATEGY_WEIGHTS, FusedScore, MarketState, StrategySignal
from src.screening.signal_fusion_arbitration_helpers import (
    apply_hold_hint,
    apply_hurst_conflict_resolution,
    initialize_arbitration_state,
    maybe_apply_forced_avoid,
)


def _analysis_excludes_neutral_mean_reversion() -> bool:
    raw_value = os.getenv("LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION")
    if raw_value is None:
        return False
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _get_neutral_mean_reversion_mode() -> str:
    raw_value = os.getenv("LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE")
    if raw_value is not None:
        value = raw_value.strip().lower()
        return value or "off"
    return "full_exclude" if _analysis_excludes_neutral_mean_reversion() else "off"


def _quality_first_guard_enabled() -> bool:
    raw_value = os.getenv("LAYER_B_ANALYSIS_QUALITY_FIRST_GUARD")
    if raw_value is None:
        return True
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_active_weights(
    weights: dict[str, float],
    signals: dict[str, StrategySignal],
    excluded_names: set[str] | None = None,
    weight_overrides: dict[str, float] | None = None,
) -> dict[str, float]:
    excluded_names = excluded_names or set()
    weight_overrides = weight_overrides or {}
    active = {
        name: max(weight_overrides.get(name, weights.get(name, 0.0)), 0.0)
        for name, signal in signals.items()
        if signal.completeness > 0 and name not in excluded_names
    }
    total = sum(active.values())
    if total <= 0:
        active = {name: DEFAULT_STRATEGY_WEIGHTS.get(name, 0.0) for name in signals if name not in excluded_names}
        total = sum(active.values())
    return {name: value / total for name, value in active.items()} if total > 0 else {}


def _compute_raw_score(normalized_weights: dict[str, float], signals: dict[str, StrategySignal]) -> float:
    score = 0.0
    for name, signal in signals.items():
        weight = normalized_weights.get(name, 0.0)
        score += weight * signal.direction * (signal.confidence / 100.0) * signal.completeness
    return score


def _is_hard_cliff_profitability(signals: dict[str, StrategySignal]) -> bool:
    fundamental_signal = signals.get("fundamental")
    if not fundamental_signal:
        return False
    profitability = fundamental_signal.sub_factors.get("profitability", {})
    if not isinstance(profitability, dict):
        return False
    metrics = profitability.get("metrics", {})
    return profitability.get("direction") == -1 and metrics.get("positive_count") == 0


def _get_sub_factor_snapshot(signal: StrategySignal, name: str) -> dict:
    sub_factor = signal.sub_factors.get(name, {})
    return sub_factor if isinstance(sub_factor, dict) else {}


def _has_quality_first_red_flag(signals: dict[str, StrategySignal]) -> bool:
    if not _quality_first_guard_enabled():
        return False

    fundamental_signal = signals.get("fundamental")
    if not fundamental_signal or fundamental_signal.completeness <= 0:
        return False

    profitability = _get_sub_factor_snapshot(fundamental_signal, "profitability")
    financial_health = _get_sub_factor_snapshot(fundamental_signal, "financial_health")
    growth = _get_sub_factor_snapshot(fundamental_signal, "growth")

    profitability_direction = profitability.get("direction")
    profitability_confidence = float(profitability.get("confidence", 0.0) or 0.0)
    financial_health_direction = financial_health.get("direction")
    financial_health_confidence = float(financial_health.get("confidence", 0.0) or 0.0)
    growth_direction = growth.get("direction")

    paired_quality_breakdown = (
        profitability_direction == -1
        and financial_health_direction == -1
        and profitability_confidence >= 55
        and financial_health_confidence >= 55
    )
    hard_cliff_with_no_offset = (
        _is_hard_cliff_profitability(signals)
        and financial_health_direction in {-1, 0}
        and growth_direction in {-1, 0, None}
    )
    return paired_quality_breakdown or hard_cliff_with_no_offset


def _should_exclude_neutral_mean_reversion(weights: dict[str, float], signals: dict[str, StrategySignal]) -> bool:
    mean_reversion_signal = signals.get("mean_reversion")
    if not mean_reversion_signal or mean_reversion_signal.completeness <= 0 or mean_reversion_signal.direction != 0:
        return False

    mode = _get_neutral_mean_reversion_mode()
    if mode == "off":
        return False
    if mode == "full_exclude":
        return True

    trend_signal = signals.get("trend", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))
    fundamental_signal = signals.get("fundamental", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))
    event_signal = signals.get("event_sentiment", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))

    if trend_signal.direction <= 0 or fundamental_signal.direction <= 0:
        return False
    if event_signal.completeness > 0:
        return False

    threshold_by_mode = {
        "guarded_dual_leg_033": 0.33,
        "guarded_dual_leg_032": 0.32,
        "guarded_dual_leg_033_no_hard_cliff": 0.33,
        "guarded_dual_leg_032_no_hard_cliff": 0.32,
    }
    min_score = threshold_by_mode.get(mode)
    if min_score is None:
        return False

    if mode.endswith("_no_hard_cliff") and _is_hard_cliff_profitability(signals):
        return False

    baseline_weights = _normalize_active_weights(weights, signals)
    baseline_score = _compute_raw_score(baseline_weights, signals)
    return baseline_score >= min_score


def _get_neutral_mean_reversion_partial_weight(weights: dict[str, float], signals: dict[str, StrategySignal]) -> float | None:
    mean_reversion_signal = signals.get("mean_reversion")
    if not mean_reversion_signal or mean_reversion_signal.completeness <= 0 or mean_reversion_signal.direction != 0:
        return None

    mode = _get_neutral_mean_reversion_mode()
    partial_modes = {
        "partial_mr_half_dual_leg_033_no_hard_cliff": {
            "min_score": 0.33,
            "multiplier": 0.5,
            "require_event_positive": False,
        },
        "partial_mr_third_dual_leg_034_no_hard_cliff": {
            "min_score": 0.34,
            "multiplier": 1.0 / 3.0,
            "require_event_positive": False,
        },
        "partial_mr_quarter_dual_leg_034_event_positive_no_hard_cliff": {
            "min_score": 0.34,
            "multiplier": 0.25,
            "require_event_positive": True,
        },
        "partial_mr_quarter_dual_leg_034_event_non_negative_no_hard_cliff": {
            "min_score": 0.34,
            "multiplier": 0.25,
            "require_event_positive": False,
        },
        "partial_mr_quarter_dual_leg_034_event_non_negative_trend24_fund50_no_hard_cliff": {
            "min_score": 0.34,
            "multiplier": 0.25,
            "require_event_positive": False,
            "min_trend_confidence": 24.0,
            "min_fundamental_confidence": 50.0,
        },
    }
    config = partial_modes.get(mode)
    if config is None:
        return None

    trend_signal = signals.get("trend", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))
    fundamental_signal = signals.get("fundamental", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))
    event_signal = signals.get("event_sentiment", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))

    if trend_signal.direction <= 0 or fundamental_signal.direction <= 0:
        return None
    if event_signal.direction < 0:
        return None
    if config.get("require_event_positive") and event_signal.direction <= 0:
        return None
    if float(trend_signal.confidence) < float(config.get("min_trend_confidence", 0.0)):
        return None
    if float(fundamental_signal.confidence) < float(config.get("min_fundamental_confidence", 0.0)):
        return None
    if _is_hard_cliff_profitability(signals):
        return None

    baseline_weights = _normalize_active_weights(weights, signals)
    baseline_score = _compute_raw_score(baseline_weights, signals)
    if baseline_score < float(config["min_score"]):
        return None

    return max(weights.get("mean_reversion", 0.0), 0.0) * float(config["multiplier"])


def _is_active_for_normalization(name: str, signal: StrategySignal) -> bool:
    if signal.completeness <= 0:
        return False
    return not (name == "mean_reversion" and signal.direction == 0 and _get_neutral_mean_reversion_mode() == "full_exclude")


def _normalize_for_available_signals(weights: dict[str, float], signals: dict[str, StrategySignal]) -> dict[str, float]:
    excluded_names: set[str] = set()
    weight_overrides: dict[str, float] = {}
    if _should_exclude_neutral_mean_reversion(weights, signals):
        excluded_names.add("mean_reversion")
    else:
        partial_weight = _get_neutral_mean_reversion_partial_weight(weights, signals)
        if partial_weight is not None:
            weight_overrides["mean_reversion"] = partial_weight
    return _normalize_active_weights(weights, signals, excluded_names, weight_overrides)


def _signal_contribution(weight: float, signal: StrategySignal) -> float:
    return abs(weight * signal.direction * (signal.confidence / 100.0) * signal.completeness)


def _apply_risk_off_short_term_demotion(
    signals: dict[str, StrategySignal],
    market_state: MarketState,
    arbitration_applied: list[str],
) -> None:
    breadth_ratio = float(getattr(market_state, "breadth_ratio", 0.5) or 0.5)
    position_scale = float(getattr(market_state, "position_scale", 1.0) or 1.0)
    if breadth_ratio > 0.42 and position_scale > 0.75:
        return

    trend_signal = signals.get("trend")
    event_signal = signals.get("event_sentiment")
    fundamental_signal = signals.get("fundamental", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))
    if not trend_signal and not event_signal:
        return

    short_term_bullish = any(
        signal is not None and signal.completeness > 0 and signal.direction > 0 and signal.confidence >= 60
        for signal in (trend_signal, event_signal)
    )
    if not short_term_bullish:
        return

    strong_fundamental_support = (
        fundamental_signal.completeness > 0
        and fundamental_signal.direction > 0
        and fundamental_signal.confidence >= 65
    )
    if strong_fundamental_support:
        return

    if trend_signal and trend_signal.direction > 0:
        trend_signal.confidence *= 0.80
    if event_signal and event_signal.direction > 0:
        event_signal.confidence *= 0.70
    arbitration_applied.append(ArbitrationAction.RISK_OFF.value)


def _should_apply_consensus_bonus(
    signals: dict[str, StrategySignal],
    market_state: MarketState,
) -> bool:
    same_direction: dict[int, int] = {}
    for signal in signals.values():
        if signal.direction != 0 and signal.confidence > 60:
            same_direction[signal.direction] = same_direction.get(signal.direction, 0) + 1

    if not any(count >= 3 for count in same_direction.values()):
        return False

    bullish_consensus = same_direction.get(1, 0) >= 3
    if not bullish_consensus:
        return True

    breadth_ratio = float(getattr(market_state, "breadth_ratio", 0.5) or 0.5)
    position_scale = float(getattr(market_state, "position_scale", 1.0) or 1.0)
    fundamental_signal = signals.get("fundamental", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))
    strong_fundamental_support = (
        fundamental_signal.completeness > 0
        and fundamental_signal.direction > 0
        and fundamental_signal.confidence >= 65
    )
    return not ((breadth_ratio <= 0.42 or position_scale <= 0.75) and not strong_fundamental_support)


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
    trade_date: str | None = None,
) -> tuple[dict[str, StrategySignal], list[str], str | None, bool]:
    state = initialize_arbitration_state(market_state)
    if maybe_apply_forced_avoid(
        ticker=ticker,
        signals=signals,
        state=state,
        trade_date=trade_date,
        maybe_release_cooldown_early=maybe_release_cooldown_early,
        has_quality_first_red_flag=_has_quality_first_red_flag,
        add_cooldown=add_cooldown,
    ):
        return signals, state.arbitration_applied, state.hold_hint, state.forced_avoid
    apply_hold_hint(signals=signals, state=state, signal_contribution=_signal_contribution)
    _apply_risk_off_short_term_demotion(signals, market_state, state.arbitration_applied)
    apply_hurst_conflict_resolution(signals=signals, state=state)
    if _should_apply_consensus_bonus(signals, market_state):
        state.arbitration_applied.append(ArbitrationAction.CONSENSUS_BONUS.value)
    return signals, state.arbitration_applied, state.hold_hint, state.forced_avoid


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
    trade_date: str | None = None,
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
    trade_date: str | None = None,
) -> list[FusedScore]:
    results = []
    current_cooldown = get_cooled_tickers(trade_date) if trade_date else set()
    for ticker, signals in scored_signals.items():
        if trade_date and ticker in current_cooldown and signals.get("fundamental") and signals["fundamental"].direction > 0:
            maybe_release_cooldown_early(ticker, trade_date, signals["fundamental"])
        results.append(fuse_signals_for_ticker(ticker, signals, market_state, trade_date))
    return results
