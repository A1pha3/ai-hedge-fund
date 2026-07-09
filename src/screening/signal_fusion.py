"""Layer B 信号融合与冲突仲裁。"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta

from src.screening.candidate_pool import (
    add_cooldown,
    get_cooled_tickers,
    load_cooldown_registry,
    save_cooldown_registry,
)
from src.screening.custom_weights import STRATEGY_KEYS
from src.screening.market_state_helpers import (
    BREADTH_RATIO_WEAK_FLOOR,
    POSITION_SCALE_WEAK_FLOOR,
)
from src.screening.models import (
    ArbitrationAction,
    DEFAULT_STRATEGY_WEIGHTS,
    FusedScore,
    MarketState,
    StrategySignal,
)
from src.screening.signal_fusion_arbitration_helpers import (
    apply_hold_hint,
    apply_hurst_conflict_resolution,
    initialize_arbitration_state,
    maybe_apply_forced_avoid,
)

#: NS-17: signal_fusion (打分核心) 之前零 logger — 无法回答 "为什么 X 得 0.32"。
#: 模块 logger 供 per-ticker score breakdown (DEBUG, opt-in via LOG_LEVEL=DEBUG)。
logger = logging.getLogger(__name__)


def _analysis_excludes_neutral_mean_reversion() -> bool:
    raw_value = os.getenv("LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION")
    if raw_value is None:
        return False
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_cooldown_date(value: str | None) -> datetime | None:
    """Parse a YYYYMMDD string into a datetime, returning None on any error.

    Cooldown registry entries come from external sources (tushare, akshare, manual
    edits) and may be malformed. Returning None lets callers treat it as "no
    early release" rather than crashing the entire score_b computation.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y%m%d")
    except (ValueError, TypeError):
        return None


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
    active = {name: max(weight_overrides.get(name, weights.get(name, 0.0)), 0.0) for name, signal in signals.items() if signal.completeness > 0 and name not in excluded_names}
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

    paired_quality_breakdown = profitability_direction == -1 and financial_health_direction == -1 and profitability_confidence >= 55 and financial_health_confidence >= 55
    hard_cliff_with_no_offset = _is_hard_cliff_profitability(signals) and financial_health_direction in {-1, 0} and growth_direction in {-1, 0, None}
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
    breadth_ratio = float(getattr(market_state, "breadth_ratio", 0.5))
    position_scale = float(getattr(market_state, "position_scale", 1.0))
    if breadth_ratio > BREADTH_RATIO_WEAK_FLOOR and position_scale > POSITION_SCALE_WEAK_FLOOR:
        return

    trend_signal = signals.get("trend")
    event_signal = signals.get("event_sentiment")
    fundamental_signal = signals.get("fundamental", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))
    if not trend_signal and not event_signal:
        return

    short_term_bullish = any(signal is not None and signal.completeness > 0 and signal.direction > 0 and signal.confidence >= 60 for signal in (trend_signal, event_signal))
    if not short_term_bullish:
        return

    strong_fundamental_support = fundamental_signal.completeness > 0 and fundamental_signal.direction > 0 and fundamental_signal.confidence >= 65
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

    breadth_ratio = float(getattr(market_state, "breadth_ratio", 0.5))
    position_scale = float(getattr(market_state, "position_scale", 1.0))
    fundamental_signal = signals.get("fundamental", StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={}))
    strong_fundamental_support = fundamental_signal.completeness > 0 and fundamental_signal.direction > 0 and fundamental_signal.confidence >= 65
    return not ((breadth_ratio <= BREADTH_RATIO_WEAK_FLOOR or position_scale <= POSITION_SCALE_WEAK_FLOOR) and not strong_fundamental_support)


def maybe_release_cooldown_early(ticker: str, trade_date: str, fundamental_signal: StrategySignal, min_hold_days: int = 5) -> bool:
    if fundamental_signal.direction <= 0:
        return False

    registry = load_cooldown_registry()
    expire_date = registry.get(ticker)
    if not expire_date:
        return False

    expire_dt = _parse_cooldown_date(expire_date)
    trade_dt = _parse_cooldown_date(trade_date)
    if expire_dt is None or trade_dt is None:
        return False
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
    # A 股动量市场: mean_reversion 信号方向由 NS-4 (commit 023acd74) 在 generator
    # 层翻转对齐 T+1, multiplier=1.0 不再反转. 见 models.py:STRATEGY_DIRECTION_MULTIPLIER.
    from src.screening.models import STRATEGY_DIRECTION_MULTIPLIER

    score = 0.0
    for name, signal in signals.items():
        weight = normalized_weights.get(name, 0.0)
        multiplier = STRATEGY_DIRECTION_MULTIPLIER.get(name, 1.0)
        score += weight * signal.direction * multiplier * (signal.confidence / 100.0) * signal.completeness

    if ArbitrationAction.CONSENSUS_BONUS.value in arbitration_applied:
        # GAMMA-016: apply bonus in the direction of the consensus, not
        # always positive.  A bearish consensus (score < 0) should make
        # the score MORE bearish, not less (the old `score + 0.05` was
        # weakening bearish consensus signals).
        # R20.10 (GAMMA-017b): score == 0 is genuinely neutral — apply no bonus.
        # Only tilt the score when there is a directional consensus (> 0 or < 0).
        if score > 0:
            bonus = 0.05
        elif score < 0:
            bonus = -0.05
        else:
            bonus = 0.0
        score = score + bonus
    return max(-1.0, min(1.0, score))


def _collect_raw_metrics_from_signals(signals: dict[str, StrategySignal]) -> dict[str, float]:
    collected: dict[str, float] = {}
    for signal in signals.values():
        sub_factors = dict(getattr(signal, "sub_factors", {}) or {})
        for payload in sub_factors.values():
            metrics = dict((payload or {}).get("metrics") or {}) if isinstance(payload, dict) else dict(getattr(payload, "metrics", {}) or {})
            for key, value in metrics.items():
                collected.setdefault(str(key), value)
    return collected


def _build_percentile_rank_map(values: dict[str, float]) -> dict[str, float]:
    if len(values) < 2:
        return {}
    sorted_pairs = sorted(values.items(), key=lambda item: item[1])
    total = len(sorted_pairs)
    percentile_map: dict[str, float] = {}
    idx = 0
    while idx < total:
        end_idx = idx
        while end_idx + 1 < total and sorted_pairs[end_idx + 1][1] == sorted_pairs[idx][1]:
            end_idx += 1
        average_rank = ((idx + 1) + (end_idx + 1)) / 2.0
        percentile = average_rank / total
        for ticker, _ in sorted_pairs[idx : end_idx + 1]:
            percentile_map[ticker] = percentile
        idx = end_idx + 1
    return percentile_map


def _extract_attention_component_values(results: list[FusedScore], metric_name: str, *, absolute: bool = False) -> dict[str, float]:
    values: dict[str, float] = {}
    for result in results:
        metric_value = result.metrics.get(metric_name)
        if metric_value is None:
            continue
        # ALPHA-003: 防御 NaN/Inf/非数值输入 — 否则会让 sorted() 顺序不确定
        # (NaN 比较恒为 False, 会卡在任意位置), 并污染所有 ticker 的分位数排序。
        try:
            value = float(metric_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        values[result.ticker] = abs(value) if absolute else value
    return values


def _apply_cross_sectional_attention_metrics(results: list[FusedScore]) -> None:
    component_weights = {
        "turnover_ratio_20": 0.40,
        "amount_ratio_5": 0.30,
        "ret_2d": 0.15,
        "ret_5d": 0.15,
    }
    rank_maps = {
        "turnover_ratio_20": _build_percentile_rank_map(_extract_attention_component_values(results, "turnover_ratio_20")),
        "amount_ratio_5": _build_percentile_rank_map(_extract_attention_component_values(results, "amount_ratio_5")),
        "ret_2d": _build_percentile_rank_map(_extract_attention_component_values(results, "ret_2d", absolute=True)),
        "ret_5d": _build_percentile_rank_map(_extract_attention_component_values(results, "ret_5d", absolute=True)),
    }

    for result in results:
        weighted_score = 0.0
        available_weight = 0.0
        for metric_name, weight in component_weights.items():
            percentile = rank_maps[metric_name].get(result.ticker)
            if percentile is None:
                continue
            weighted_score += weight * percentile
            available_weight += weight
        if available_weight > 0.0:
            result.metrics["attention_composite"] = round(weighted_score / available_weight, 4)


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

    # NS-17: per-ticker DEBUG score breakdown — answers "why did X get score_b Y".
    # Opt-in via LOG_LEVEL=DEBUG (avoids noise on full-universe runs). Surfaces the
    # arbitration rules applied + per-strategy direction/confidence + final score_b.
    if logger.isEnabledFor(logging.DEBUG):
        strat_summary = " ".join(f"{name}(d={sig.direction},c={sig.confidence:.0f})" for name, sig in adjusted_signals.items())
        logger.debug(
            "score_b breakdown ticker=%s trade_date=%s decision=%s score_b=%.4f " "forced_avoid=%s arbitration=[%s] weights=%s signals=[%s]",
            ticker,
            trade_date,
            decision,
            score_b,
            forced_avoid,
            ", ".join(arbitration_applied) or "none",
            {k: round(float(v), 3) for k, v in weights_used.items()},
            strat_summary,
        )

    return FusedScore(
        ticker=ticker,
        score_b=score_b,
        strategy_signals=adjusted_signals,
        metrics=_collect_raw_metrics_from_signals(adjusted_signals),
        arbitration_applied=arbitration_applied,
        market_state=market_state,
        weights_used=weights_used,
        decision=decision,
    )


def _compute_relative_strength(results: list[FusedScore]) -> None:
    """P4-1: 计算行业内相对强度 — 标的 score_b 相对其行业同行的百分位排名。

    一个 score_b=0.4 的标的, 如果所在行业平均 score_b=0.1, 相对强度远高于
    一个同 score_b=0.4 但行业平均 score_b=0.5 的标的。

    结果写入 ``result.metrics["industry_relative_strength"]`` (0.0~1.0):
      - 1.0 = 行业内最强
      - 0.5 = 行业中位数
      - 0.0 = 行业内最弱

    至少需要同行业 >= 2 只标的才计算, 否则设为 0.5 (中性)。
    """
    # Group by industry
    by_industry: dict[str, list[FusedScore]] = {}
    for r in results:
        industry = str(r.industry_sw or "").strip() or "未知"
        by_industry.setdefault(industry, []).append(r)

    for industry, group in by_industry.items():
        if len(group) < 2:
            # Only one stock in industry — neutral
            for r in group:
                r.metrics["industry_relative_strength"] = 0.5
            continue

        # Sort by score_b desc to compute percentile
        sorted_group = sorted(group, key=lambda r: r.score_b)
        n = len(sorted_group)
        for rank_idx, r in enumerate(sorted_group):
            # Percentile rank: 0.0 (worst) to 1.0 (best)
            # Use (rank) / (n-1) to map to 0-1 range
            percentile = rank_idx / (n - 1) if n > 1 else 0.5
            r.metrics["industry_relative_strength"] = round(percentile, 4)


def fuse_batch(
    scored_signals: dict[str, dict[str, StrategySignal]],
    market_state: MarketState,
    trade_date: str | None = None,
    candidates: list | None = None,
) -> list[FusedScore]:
    results = []
    current_cooldown = get_cooled_tickers(trade_date) if trade_date else set()
    # Build lookup from candidates for name/industry propagation
    cand_lookup: dict[str, dict[str, str]] = {}
    if candidates:
        for c in candidates:
            ticker = getattr(c, "ticker", None)
            if ticker:
                cand_lookup[ticker] = {
                    "name": getattr(c, "name", ""),
                    "industry_sw": getattr(c, "industry_sw", ""),
                }
    for ticker, signals in scored_signals.items():
        if trade_date and ticker in current_cooldown and signals.get("fundamental") and signals["fundamental"].direction > 0:
            maybe_release_cooldown_early(ticker, trade_date, signals["fundamental"])
        fused = fuse_signals_for_ticker(ticker, signals, market_state, trade_date)
        # Propagate name/industry from candidate pool
        if ticker in cand_lookup:
            fused.name = cand_lookup[ticker]["name"]
            fused.industry_sw = cand_lookup[ticker]["industry_sw"]
        results.append(fused)
    _apply_cross_sectional_attention_metrics(results)
    _compute_relative_strength(results)
    return results


# ============================================================
# R20.5: 因子瀑布 (Factor-level Waterfall)
# ============================================================


def compute_score_decomposition(fused: FusedScore, consecutive_info: dict | None = None) -> dict:
    """Decompose a FusedScore's score_b into its individual adjustment components.

    Returns a dict with the following keys, all floats:
      - base_contributions: dict[str, float] — per-strategy (T/MR/F/E) weighted
        contribution: ``weight * direction * (confidence/100) * completeness``
      - attention_contribution: float — attention_composite cross-sectional
        percentile (METADATA: non-additive context, NOT part of score_b)
      - stability_bonus: float — consecutive-day bonus (METADATA: non-additive
        context, NOT part of score_b; lives on the rec dict, 0-10 scale)
      - consensus_bonus: float — bullish/bearish consensus bonus (additive, ±0.05)
      - other_adjustments: float — residual = score_b - (base_sum + consensus_bonus).
        Only non-zero when compute_score_b's [-1, +1] clamp truncates the raw score.
      - total: float — the canonical score_b

    score_b composition (authoritative, see compute_score_b lines 359-385):
        score_b = clamp(base_sum + consensus_bonus, -1, +1)
    ``attention_contribution`` and ``stability_bonus`` are reported for
    transparency but are NOT added into score_b (they are orthogonal metadata),
    so they are excluded from the components_sum that defines other_adjustments.
    """
    consecutive_info = consecutive_info or {}
    weights = fused.weights_used or {}
    signals = fused.strategy_signals or {}

    base_contributions: dict[str, float] = {}
    for sname in STRATEGY_KEYS:
        w = float(weights.get(sname, 0.0) or 0.0)
        sig = signals.get(sname)
        if sig is None or w == 0.0:
            base_contributions[sname] = 0.0
            continue
        confidence = float(getattr(sig, "confidence", 0.0) or 0.0)
        direction = float(getattr(sig, "direction", 0.0) or 0.0)
        completeness = float(getattr(sig, "completeness", 1.0) if getattr(sig, "completeness", 1.0) is not None else 1.0)
        base_contributions[sname] = w * direction * (confidence / 100.0) * completeness

    attention = float((fused.metrics or {}).get("attention_composite", 0.0) or 0.0)
    stability_bonus = float(consecutive_info.get("stability_bonus", 0.0) or 0.0)

    # Consensus bonus: 0.05 if bullish, -0.05 if bearish (matching GAMMA-016 fix).
    # The actual applied bonus is tracked in arbitrage_applied as the bare enum
    # value ("consensus_bonus"); the direction is inferred from the sign of
    # fused.score_b since the arbitrator has already applied the bonus with the
    # correct sign (see compute_score_b's `score > 0 / < 0` branches).
    consensus_bonus = 0.0
    arb = fused.arbitration_applied or []
    if "consensus_bonus" in arb:
        consensus_bonus = 0.05 if float(fused.score_b) > 0 else -0.05 if float(fused.score_b) < 0 else 0.0

    base_sum = sum(base_contributions.values())
    # Only base_sum + consensus_bonus are genuinely additive components of
    # score_b (see compute_score_b). ``attention`` (attention_composite) and
    # ``stability_bonus`` are orthogonal metadata — they are NEVER summed into
    # score_b — so they must NOT be in components_sum, otherwise
    # other_adjustments would carry a false offset (e.g. stability_bonus=10.0
    # on a ±1 score would force other=-10.0 to "cancel" it). other_adjustments
    # is now the true residual, non-zero only when the [-1,+1] clamp truncates.
    components_sum = base_sum + consensus_bonus
    other_adjustments = float(fused.score_b) - components_sum

    return {
        "base_contributions": base_contributions,
        "attention_contribution": attention,
        "stability_bonus": stability_bonus,
        "consensus_bonus": consensus_bonus,
        "other_adjustments": other_adjustments,
        "total": float(fused.score_b),
    }
