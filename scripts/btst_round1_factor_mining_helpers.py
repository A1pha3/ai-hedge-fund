from __future__ import annotations

from statistics import mean
from typing import Any

from scripts.btst_analysis_utils import round_or_none, safe_float


def _factor_value(evaluation: dict[str, Any], name: str) -> float | None:
    short_trade = dict((evaluation or {}).get("short_trade") or {})
    explainability = dict(short_trade.get("explainability_payload") or {})
    for source in (explainability, short_trade, evaluation):
        value = safe_float(source.get(name))
        if value is not None:
            return value
    return None


def _mean_or_none(values: list[float | None]) -> float | None:
    populated = [value for value in values if value is not None]
    if not populated:
        return None
    return round_or_none(mean(populated))


def classify_round1_event_prototype(row: dict[str, Any]) -> str:
    breakout = safe_float(row.get("breakout_freshness")) or 0.0
    trend = safe_float(row.get("trend_acceleration")) or 0.0
    volume = safe_float(row.get("volume_expansion_quality")) or 0.0
    close = safe_float(row.get("close_strength")) or 0.0
    if breakout >= 0.55 and volume >= 0.55:
        return "breakout_ignition"
    if trend >= 0.55 and close >= 0.60:
        return "trend_continuation"
    if volume >= 0.60 and close >= 0.55 and breakout < 0.55:
        return "volume_quality_release"
    return "unclassified"


def compute_round1_factor_family_scores(row: dict[str, Any]) -> dict[str, float | None]:
    trend_continuation = safe_float(row.get("trend_continuation"))
    short_term_reversal = safe_float(row.get("short_term_reversal"))
    trend_signal = trend_continuation
    if trend_signal is None and short_term_reversal is not None:
        trend_signal = 1.0 - short_term_reversal
    trend_values = [
        safe_float(row.get("trend_acceleration")),
        safe_float(row.get("close_strength")),
        trend_signal,
    ]
    breakout_values = [
        safe_float(row.get("breakout_freshness")),
        safe_float(row.get("close_strength")),
        safe_float(row.get("volume_expansion_quality")),
    ]
    volume_values = [
        safe_float(row.get("volume_expansion_quality")),
        safe_float(row.get("t0_tail_strength")),
        safe_float(row.get("close_strength")),
    ]
    return {
        "trend_family": _mean_or_none(trend_values),
        "breakout_family": _mean_or_none(breakout_values),
        "volume_quality_family": _mean_or_none(volume_values),
    }


def compute_round1_interaction_scores(row: dict[str, Any]) -> dict[str, float | None]:
    trend = safe_float(row.get("trend_acceleration"))
    close = safe_float(row.get("close_strength"))
    breakout = safe_float(row.get("breakout_freshness"))
    volume = safe_float(row.get("volume_expansion_quality"))
    return {
        "trend_x_close_strength": round_or_none((trend or 0.0) * (close or 0.0)),
        "breakout_x_volume_quality": round_or_none((breakout or 0.0) * (volume or 0.0)),
    }


def summarize_round1_row_gates(row: dict[str, Any]) -> dict[str, bool]:
    next_open_return = safe_float(row.get("next_open_return"))
    return {
        "alpha_observable": row.get("future_high_hit_15pct_2_5d") is not None,
        "beta_tradeable": next_open_return is not None and next_open_return <= 0.03,
        "gamma_closed_cycle": str(row.get("cycle_status") or "") == "closed_cycle",
    }


def build_round1_research_row(
    *,
    ticker: str,
    trade_date: str,
    report_dir_name: str,
    evaluation: dict[str, Any],
    price_outcome: dict[str, Any],
) -> dict[str, Any]:
    base_row = {
        "report_dir_name": report_dir_name,
        "trade_date": trade_date,
        "ticker": ticker,
        "decision": str(dict((evaluation or {}).get("short_trade") or {}).get("decision") or "unknown"),
        "candidate_source": str((evaluation or {}).get("candidate_source") or "unknown"),
        "breakout_freshness": _factor_value(evaluation, "breakout_freshness"),
        "trend_acceleration": _factor_value(evaluation, "trend_acceleration"),
        "volume_expansion_quality": _factor_value(evaluation, "volume_expansion_quality"),
        "close_strength": _factor_value(evaluation, "close_strength"),
        "t0_tail_strength": _factor_value(evaluation, "t0_tail_strength"),
        "trend_continuation": _factor_value(evaluation, "trend_continuation"),
        "short_term_reversal": _factor_value(evaluation, "short_term_reversal"),
        **price_outcome,
    }
    family_scores = compute_round1_factor_family_scores(base_row)
    interaction_scores = compute_round1_interaction_scores(base_row)
    row_gates = summarize_round1_row_gates(base_row)
    return {
        **base_row,
        "event_prototype": classify_round1_event_prototype(base_row),
        **family_scores,
        **interaction_scores,
        **row_gates,
    }
