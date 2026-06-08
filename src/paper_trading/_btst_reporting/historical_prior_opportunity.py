"""Historical opportunity summarization: row evaluation, accumulation, and statistics.

Extracted from historical_prior.py during R20.16 refactoring.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.paper_trading.btst_reporting_utils import (
    OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
    _mean_or_none,
    _round_or_none,
)
from src.paper_trading._btst_reporting.historical_prior_price import (
    _extract_next_day_outcome,
)


def _summarize_historical_opportunity_rows(
    rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
) -> dict[str, Any]:
    summary_state = _build_empty_historical_opportunity_summary_state()

    for row in rows:
        evaluated_row = _evaluate_historical_opportunity_row(row, price_cache)
        if evaluated_row is None:
            continue
        _accumulate_historical_opportunity_summary(summary_state, evaluated_row)

    next_high_hit_rate, next_close_positive_rate = (
        _compute_historical_opportunity_rates(
            summary_state["evaluated_rows"], summary_state
        )
    )
    return _build_historical_opportunity_summary_payload(
        rows=rows,
        evaluated_rows=summary_state["evaluated_rows"],
        next_open_values=summary_state["next_open_values"],
        next_high_values=summary_state["next_high_values"],
        next_close_values=summary_state["next_close_values"],
        next_open_to_close_values=summary_state["next_open_to_close_values"],
        next_high_hit_rate=next_high_hit_rate,
        next_close_positive_rate=next_close_positive_rate,
    )


def _build_empty_historical_opportunity_summary_state() -> dict[str, Any]:
    return {
        "evaluated_rows": [],
        "next_open_values": [],
        "next_high_values": [],
        "next_close_values": [],
        "next_open_to_close_values": [],
        "hit_count": 0,
        "positive_close_count": 0,
    }


def _accumulate_historical_opportunity_summary(
    summary_state: dict[str, Any], evaluated_row: dict[str, Any]
) -> None:
    next_open_return = evaluated_row.get("next_open_return")
    next_high_return = evaluated_row.get("next_high_return")
    next_close_return = evaluated_row.get("next_close_return")
    next_open_to_close_return = evaluated_row.get("next_open_to_close_return")
    if next_open_return is not None:
        summary_state["next_open_values"].append(next_open_return)
    if next_high_return is not None:
        summary_state["next_high_values"].append(next_high_return)
        if next_high_return >= OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD:
            summary_state["hit_count"] += 1
    if next_close_return is not None:
        summary_state["next_close_values"].append(next_close_return)
        if next_close_return > 0:
            summary_state["positive_close_count"] += 1
    if next_open_to_close_return is not None:
        summary_state["next_open_to_close_values"].append(next_open_to_close_return)
    summary_state["evaluated_rows"].append(evaluated_row)


def _compute_historical_opportunity_rates(
    evaluated_rows: list[dict[str, Any]],
    summary_state: dict[str, Any],
) -> tuple[float | None, float | None]:
    evaluable_count = len(evaluated_rows)
    next_high_hit_rate = (
        round(summary_state["hit_count"] / evaluable_count, 4)
        if evaluable_count
        else None
    )
    next_close_positive_rate = (
        round(summary_state["positive_close_count"] / evaluable_count, 4)
        if evaluable_count
        else None
    )
    return next_high_hit_rate, next_close_positive_rate


def _evaluate_historical_opportunity_row(
    row: dict[str, Any],
    price_cache: dict[tuple[str, str], pd.DataFrame],
) -> dict[str, Any] | None:
    trade_date = str(row.get("trade_date") or "")
    ticker = str(row.get("ticker") or "")
    if not trade_date or not ticker:
        return None
    outcome = _extract_next_day_outcome(ticker, trade_date, price_cache)
    if outcome.get("data_status") != "ok":
        return None
    return {
        "trade_date": trade_date,
        "ticker": ticker,
        "candidate_source": row.get("candidate_source"),
        "score_target": _round_or_none(row.get("score_target")),
        "next_open_return": _round_or_none(outcome.get("next_open_return")),
        "next_high_return": _round_or_none(outcome.get("next_high_return")),
        "next_close_return": _round_or_none(outcome.get("next_close_return")),
        "next_open_to_close_return": _round_or_none(
            outcome.get("next_open_to_close_return")
        ),
    }


def _build_historical_opportunity_summary_payload(
    *,
    rows: list[dict[str, Any]],
    evaluated_rows: list[dict[str, Any]],
    next_open_values: list[float],
    next_high_values: list[float],
    next_close_values: list[float],
    next_open_to_close_values: list[float],
    next_high_hit_rate: float | None,
    next_close_positive_rate: float | None,
) -> dict[str, Any]:
    payoff_stats = _summarize_next_close_payoff(
        next_close_values, next_close_positive_rate=next_close_positive_rate
    )
    return {
        "sample_count": len(rows),
        "evaluable_count": len(evaluated_rows),
        "next_high_hit_threshold": OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
        "next_open_return_mean": _mean_or_none(next_open_values),
        "next_high_hit_rate_at_threshold": next_high_hit_rate,
        "next_close_positive_rate": next_close_positive_rate,
        **payoff_stats,
        "next_high_return_mean": _mean_or_none(next_high_values),
        "next_close_return_mean": _mean_or_none(next_close_values),
        "next_open_to_close_return_mean": _mean_or_none(next_open_to_close_values),
        "recent_examples": evaluated_rows[:3],
    }


def _summarize_next_close_payoff(
    next_close_values: list[float],
    *,
    next_close_positive_rate: float | None,
) -> dict[str, Any]:
    wins = [value for value in next_close_values if value > 0]
    losses = [abs(value) for value in next_close_values if value < 0]
    average_win = _mean_or_none(wins)
    average_loss_abs = _mean_or_none(losses)
    payoff_ratio = _compute_payoff_ratio(average_win, average_loss_abs)
    profit_factor = _compute_profit_factor(wins, losses)
    expectancy = _mean_or_none(next_close_values)
    return {
        "next_close_positive_count": len(wins),
        "next_close_negative_count": len(losses),
        "next_close_average_win": average_win,
        "next_close_average_loss_abs": average_loss_abs,
        "next_close_payoff_ratio": payoff_ratio,
        "next_close_profit_factor": profit_factor,
        "next_close_expectancy": expectancy,
        "win_rate_payoff_divergence": _detect_win_rate_payoff_divergence(
            next_close_positive_rate=next_close_positive_rate,
            payoff_ratio=payoff_ratio,
            expectancy=expectancy,
        ),
    }


def _compute_payoff_ratio(
    average_win: float | None, average_loss_abs: float | None
) -> float | None:
    if average_win is None or average_loss_abs is None or average_loss_abs <= 0:
        return None
    return _round_or_none(average_win / average_loss_abs)


def _compute_profit_factor(wins: list[float], losses: list[float]) -> float | None:
    total_loss = sum(losses)
    if not wins or total_loss <= 0:
        return None
    return _round_or_none(sum(wins) / total_loss)


def _detect_win_rate_payoff_divergence(
    *,
    next_close_positive_rate: float | None,
    payoff_ratio: float | None,
    expectancy: float | None,
) -> bool:
    if next_close_positive_rate is None or next_close_positive_rate < 0.6:
        return False
    return bool(
        (payoff_ratio is not None and payoff_ratio < 1.0)
        or (expectancy is not None and expectancy <= 0)
    )
