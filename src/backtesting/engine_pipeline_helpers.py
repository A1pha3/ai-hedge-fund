from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import pandas as pd

from src.execution.models import ExecutionPlan


@dataclass(frozen=True)
class PipelineDayContext:
    current_date: pd.Timestamp
    current_date_str: str
    trade_date_compact: str
    previous_date_str: str
    active_tickers: list[str]
    current_prices: dict[str, float]
    daily_turnovers: dict[str, float]
    limit_up: set[str]
    limit_down: set[str]
    load_market_data_seconds: float


def build_pipeline_active_tickers(
    *,
    base_tickers: Sequence[str],
    position_tickers: Sequence[str],
    pending_plan: ExecutionPlan | None,
) -> list[str]:
    active_ticker_set = set(base_tickers)
    active_ticker_set.update(position_tickers)
    if pending_plan is not None:
        active_ticker_set.update(order.ticker for order in pending_plan.buy_orders)
        active_ticker_set.update(order.ticker for order in pending_plan.sell_orders)
    return sorted(active_ticker_set)


def build_pipeline_day_context(
    *,
    current_date: pd.Timestamp,
    active_tickers: list[str],
    current_prices: dict[str, float],
    daily_turnovers: dict[str, float],
    limit_up: set[str],
    limit_down: set[str],
    load_market_data_seconds: float,
) -> PipelineDayContext:
    return PipelineDayContext(
        current_date=current_date,
        current_date_str=current_date.strftime("%Y-%m-%d"),
        trade_date_compact=current_date.strftime("%Y%m%d"),
        previous_date_str=(current_date - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        active_tickers=active_tickers,
        current_prices=current_prices,
        daily_turnovers=daily_turnovers,
        limit_up=limit_up,
        limit_down=limit_down,
        load_market_data_seconds=load_market_data_seconds,
    )


def initialize_pipeline_day_state(active_tickers: Sequence[str]) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    return {}, {ticker: 0 for ticker in active_tickers}


def extract_plan_risk_metrics(plan: ExecutionPlan | None) -> tuple[dict[str, int], dict[str, float], dict[str, Any]]:
    if plan is None:
        return {}, {}, {}
    risk_metrics = dict(plan.risk_metrics or {})
    return (
        dict(risk_metrics.get("counts", {})),
        dict(risk_metrics.get("timing_seconds", {})),
        dict(risk_metrics.get("funnel_diagnostics", {})),
    )


def collect_execution_plan_observations(pipeline: Any, trade_date_compact: str) -> list[dict[str, Any]]:
    return [
        dict(observation)
        for observation in list(getattr(pipeline, "execution_plan_provenance_log", []) or [])
        if str(observation.get("trade_date") or "") == trade_date_compact
    ]


def build_pipeline_timing_payload(
    *,
    trade_date_compact: str,
    active_tickers: Sequence[str],
    pending_buy_queue_count: int,
    pending_sell_queue_count: int,
    executed_trades: dict[str, int],
    execution_plan_observations: list[dict[str, Any]],
    load_market_data_seconds: float,
    pre_market_seconds: float,
    intraday_seconds: float,
    append_daily_state_seconds: float,
    post_market_seconds: float,
    total_day_seconds: float,
    pending_plan: ExecutionPlan | None,
    previous_plan_counts: dict[str, int],
    previous_plan_timing: dict[str, float],
    previous_plan_funnel_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    executed_order_count = sum(1 for quantity in executed_trades.values() if quantity)
    return {
        "event": "pipeline_day_timing",
        "trade_date": trade_date_compact,
        "active_ticker_count": len(active_tickers),
        "pending_buy_queue_count": pending_buy_queue_count,
        "pending_sell_queue_count": pending_sell_queue_count,
        "executed_order_count": executed_order_count,
        "execution_plan_provenance": execution_plan_observations,
        "timing_seconds": {
            "load_market_data": round(load_market_data_seconds, 3),
            "pre_market": round(pre_market_seconds, 3),
            "intraday": round(intraday_seconds, 3),
            "append_daily_state": round(append_daily_state_seconds, 3),
            "post_market": round(post_market_seconds, 3),
            "total_day": round(total_day_seconds, 3),
        },
        "current_plan": {
            "counts": dict((pending_plan.risk_metrics or {}).get("counts", {})) if pending_plan is not None else {},
            "timing_seconds": dict((pending_plan.risk_metrics or {}).get("timing_seconds", {})) if pending_plan is not None else {},
            "funnel_diagnostics": dict((pending_plan.risk_metrics or {}).get("funnel_diagnostics", {})) if pending_plan is not None else {},
            "target_mode": str(getattr(pending_plan, "target_mode", "research_only") or "research_only") if pending_plan is not None else "research_only",
            "selection_target_count": len(dict(getattr(pending_plan, "selection_targets", {}) or {})) if pending_plan is not None else 0,
            "dual_target_summary": pending_plan.dual_target_summary.model_dump(mode="json") if pending_plan is not None else {},
            "selection_artifacts": dict(getattr(pending_plan, "selection_artifacts", {}) or {}) if pending_plan is not None else {},
        },
        "previous_plan": {
            "counts": previous_plan_counts,
            "timing_seconds": previous_plan_timing,
            "funnel_diagnostics": previous_plan_funnel_diagnostics,
        },
    }


def build_pipeline_event_payload(
    *,
    trade_date_compact: str,
    active_tickers: Sequence[str],
    executed_trades: dict[str, int],
    decisions: dict[str, dict[str, Any]],
    current_prices: dict[str, float],
    portfolio_snapshot: dict[str, Any],
    pending_buy_queue: Sequence[Any],
    pending_sell_queue: Sequence[Any],
    exit_reentry_cooldowns: dict[str, Any],
    prepared_plan: ExecutionPlan | None,
    pending_plan: ExecutionPlan | None,
    execution_plan_observations: list[dict[str, Any]],
    timing_seconds: dict[str, float],
) -> dict[str, Any]:
    return {
        "event": "paper_trading_day",
        "trade_date": trade_date_compact,
        "active_tickers": list(active_tickers),
        "executed_trades": dict(executed_trades),
        "decisions": dict(decisions),
        "current_prices": {ticker: float(price) for ticker, price in current_prices.items()},
        "portfolio_snapshot": portfolio_snapshot,
        "pending_buy_queue": [order.model_dump() for order in pending_buy_queue],
        "pending_sell_queue": [order.model_dump() for order in pending_sell_queue],
        "exit_reentry_cooldowns": dict(exit_reentry_cooldowns),
        "prepared_plan": prepared_plan.model_dump() if prepared_plan is not None else None,
        "current_plan": pending_plan.model_dump() if pending_plan is not None else None,
        "execution_plan_provenance": execution_plan_observations,
        "timing_seconds": timing_seconds,
    }
