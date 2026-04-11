from __future__ import annotations

from typing import Any, Callable


def _resolve_trend_strength_metrics(
    trend_signal: Any,
    *,
    subfactor_positive_strength_fn: Callable[[Any, str], float],
    subfactor_metrics_fn: Callable[[Any, str], dict[str, Any]],
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    momentum_strength = subfactor_positive_strength_fn(trend_signal, "momentum")
    momentum_metrics = subfactor_metrics_fn(trend_signal, "momentum")
    volatility_metrics = subfactor_metrics_fn(trend_signal, "volatility")
    return {
        "momentum_strength": momentum_strength,
        "momentum_1m": float(momentum_metrics.get("momentum_1m", 0.0) or 0.0),
        "momentum_3m": clamp_unit_interval_fn(float(momentum_metrics.get("momentum_3m", 0.0) or 0.0)),
        "momentum_6m": clamp_unit_interval_fn(float(momentum_metrics.get("momentum_6m", 0.0) or 0.0)),
        "volume_momentum": clamp_unit_interval_fn(float(momentum_metrics.get("volume_momentum", 0.0) or 0.0)),
        "adx_strength": subfactor_positive_strength_fn(trend_signal, "adx_strength"),
        "ema_strength": subfactor_positive_strength_fn(trend_signal, "ema_alignment"),
        "volatility_strength": subfactor_positive_strength_fn(trend_signal, "volatility"),
        "volatility_metrics": volatility_metrics,
        "volatility_regime": clamp_unit_interval_fn(float(volatility_metrics.get("volatility_regime", 0.0) or 0.0)),
        "atr_ratio": clamp_unit_interval_fn(float(volatility_metrics.get("atr_ratio", 0.0) or 0.0)),
        "long_trend_strength": subfactor_positive_strength_fn(trend_signal, "long_trend_alignment"),
    }


def _resolve_event_strength_metrics(
    event_signal: Any,
    mean_reversion_signal: Any,
    *,
    subfactor_positive_strength_fn: Callable[[Any, str], float],
    positive_strength_fn: Callable[[Any], float],
) -> dict[str, Any]:
    return {
        "event_freshness_strength": subfactor_positive_strength_fn(event_signal, "event_freshness"),
        "news_sentiment_strength": subfactor_positive_strength_fn(event_signal, "news_sentiment"),
        "event_signal_strength": positive_strength_fn(event_signal),
        "mean_reversion_strength": positive_strength_fn(mean_reversion_signal),
    }


def _resolve_alignment_strength_metrics(
    input_data,
    *,
    cohort_alignment_fn: Callable[[dict[str, Any], str], float],
    cohort_penalty_fn: Callable[[dict[str, Any], str], float],
    normalize_score_fn: Callable[[float], float],
) -> dict[str, Any]:
    return {
        "analyst_alignment": cohort_alignment_fn(input_data.agent_contribution_summary, "analyst"),
        "investor_alignment": cohort_alignment_fn(input_data.agent_contribution_summary, "investor"),
        "analyst_penalty": cohort_penalty_fn(input_data.agent_contribution_summary, "analyst"),
        "investor_penalty": cohort_penalty_fn(input_data.agent_contribution_summary, "investor"),
        "score_b_strength": normalize_score_fn(input_data.score_b),
        "score_c_strength": normalize_score_fn(input_data.score_c),
        "score_final_strength": normalize_score_fn(input_data.score_final),
    }


def _resolve_snapshot_scores(
    input_data,
    *,
    trend_metrics: dict[str, Any],
    event_metrics: dict[str, Any],
    alignment_metrics: dict[str, Any],
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, float]:
    breakout_freshness = clamp_unit_interval_fn(
        (0.40 * trend_metrics["momentum_strength"])
        + (0.35 * event_metrics["event_freshness_strength"])
        + (0.25 * event_metrics["event_signal_strength"])
    )
    trend_acceleration = clamp_unit_interval_fn(
        (0.40 * trend_metrics["momentum_strength"])
        + (0.35 * trend_metrics["adx_strength"])
        + (0.25 * trend_metrics["ema_strength"])
    )
    volume_expansion_quality = clamp_unit_interval_fn(
        (0.55 * trend_metrics["volatility_strength"])
        + (0.25 * trend_metrics["momentum_strength"])
        + (0.20 * event_metrics["event_signal_strength"])
    )
    close_strength = clamp_unit_interval_fn(
        (0.55 * trend_metrics["ema_strength"])
        + (0.25 * trend_metrics["momentum_strength"])
        + (0.20 * alignment_metrics["score_b_strength"])
    )
    sector_resonance = clamp_unit_interval_fn(
        (0.45 * alignment_metrics["analyst_alignment"])
        + (0.20 * alignment_metrics["investor_alignment"])
        + (0.20 * alignment_metrics["score_c_strength"])
        + (0.15 * event_metrics["event_signal_strength"])
    )
    raw_catalyst_freshness = clamp_unit_interval_fn(
        (0.65 * event_metrics["event_freshness_strength"])
        + (0.35 * event_metrics["news_sentiment_strength"])
    )
    layer_c_alignment = clamp_unit_interval_fn(
        (0.55 * alignment_metrics["score_c_strength"])
        + (0.25 * alignment_metrics["analyst_alignment"])
        + (0.20 * clamp_unit_interval_fn(1.0 if input_data.layer_c_decision != "avoid" else 0.0))
    )
    return {
        "breakout_freshness": breakout_freshness,
        "trend_acceleration": trend_acceleration,
        "volume_expansion_quality": volume_expansion_quality,
        "close_strength": close_strength,
        "sector_resonance": sector_resonance,
        "raw_catalyst_freshness": raw_catalyst_freshness,
        "layer_c_alignment": layer_c_alignment,
    }


def _apply_explicit_metric_overrides(
    *,
    scores: dict[str, float],
    explicit_metric_overrides: dict[str, Any],
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, float]:
    if not explicit_metric_overrides:
        return scores
    overridden = dict(scores)
    overridden["breakout_freshness"] = clamp_unit_interval_fn(float(explicit_metric_overrides.get("breakout_freshness", overridden["breakout_freshness"]) or overridden["breakout_freshness"]))
    overridden["trend_acceleration"] = clamp_unit_interval_fn(float(explicit_metric_overrides.get("trend_acceleration", overridden["trend_acceleration"]) or overridden["trend_acceleration"]))
    overridden["volume_expansion_quality"] = clamp_unit_interval_fn(float(explicit_metric_overrides.get("volume_expansion_quality", overridden["volume_expansion_quality"]) or overridden["volume_expansion_quality"]))
    overridden["close_strength"] = clamp_unit_interval_fn(float(explicit_metric_overrides.get("close_strength", overridden["close_strength"]) or overridden["close_strength"]))
    overridden["sector_resonance"] = clamp_unit_interval_fn(float(explicit_metric_overrides.get("sector_resonance", overridden["sector_resonance"]) or overridden["sector_resonance"]))
    overridden["raw_catalyst_freshness"] = clamp_unit_interval_fn(float(explicit_metric_overrides.get("catalyst_freshness", overridden["raw_catalyst_freshness"]) or overridden["raw_catalyst_freshness"]))
    return overridden


def build_short_trade_signal_snapshot(
    input_data,
    *,
    profile: Any,
    load_signal_fn: Callable[[Any], Any],
    subfactor_positive_strength_fn: Callable[[Any, str], float],
    subfactor_metrics_fn: Callable[[Any, str], dict[str, Any]],
    positive_strength_fn: Callable[[Any], float],
    cohort_alignment_fn: Callable[[dict[str, Any], str], float],
    cohort_penalty_fn: Callable[[dict[str, Any], str], float],
    normalize_score_fn: Callable[[float], float],
    clamp_unit_interval_fn: Callable[[float], float],
    classify_breakout_stage_fn: Callable[..., tuple[Any, Any, Any]],
) -> dict[str, Any]:
    trend_signal = load_signal_fn(input_data.strategy_signals.get("trend"))
    event_signal = load_signal_fn(input_data.strategy_signals.get("event_sentiment"))
    fundamental_signal = load_signal_fn(input_data.strategy_signals.get("fundamental"))
    mean_reversion_signal = load_signal_fn(input_data.strategy_signals.get("mean_reversion"))

    trend_metrics = _resolve_trend_strength_metrics(
        trend_signal,
        subfactor_positive_strength_fn=subfactor_positive_strength_fn,
        subfactor_metrics_fn=subfactor_metrics_fn,
        clamp_unit_interval_fn=clamp_unit_interval_fn,
    )
    event_metrics = _resolve_event_strength_metrics(
        event_signal,
        mean_reversion_signal,
        subfactor_positive_strength_fn=subfactor_positive_strength_fn,
        positive_strength_fn=positive_strength_fn,
    )
    alignment_metrics = _resolve_alignment_strength_metrics(
        input_data,
        cohort_alignment_fn=cohort_alignment_fn,
        cohort_penalty_fn=cohort_penalty_fn,
        normalize_score_fn=normalize_score_fn,
    )
    scores = _resolve_snapshot_scores(
        input_data,
        trend_metrics=trend_metrics,
        event_metrics=event_metrics,
        alignment_metrics=alignment_metrics,
        clamp_unit_interval_fn=clamp_unit_interval_fn,
    )
    scores = _apply_explicit_metric_overrides(
        scores=scores,
        explicit_metric_overrides=dict(input_data.replay_context.get("explicit_metric_overrides") or {}),
        clamp_unit_interval_fn=clamp_unit_interval_fn,
    )
    breakout_stage, _, _ = classify_breakout_stage_fn(
        breakout_freshness=scores["breakout_freshness"],
        trend_acceleration=scores["trend_acceleration"],
        profile=profile,
    )

    return {
        "trend_signal": trend_signal,
        "event_signal": event_signal,
        "fundamental_signal": fundamental_signal,
        "mean_reversion_signal": mean_reversion_signal,
        **trend_metrics,
        **event_metrics,
        **alignment_metrics,
        **scores,
        "breakout_stage": breakout_stage,
    }
