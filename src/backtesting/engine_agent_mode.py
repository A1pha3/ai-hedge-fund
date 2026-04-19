"""Agent-mode backtest helpers extracted from BacktestEngine.

This module contains pure functions and a runner class for the agent-mode
backtest loop.  The engine delegates day-resolution, agent invocation and
trade execution to these helpers while retaining its own orchestration
loop (``_run_agent_mode``) so it can call engine-level helpers for price
loading and daily-state bookkeeping.

Two shared helpers -- ``build_confirmation_inputs`` and
``build_pipeline_agent_output`` -- are also used by the pipeline mode and
are therefore public standalone functions rather than class methods.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd
from dateutil.relativedelta import relativedelta

from src.execution.models import ExecutionPlan

from .controller import AgentController
from .portfolio import Portfolio
from .trader import TradeExecutor
from .types import AgentOutput


# ---------------------------------------------------------------------------
# Shared helpers (used by both agent-mode and pipeline-mode)
# ---------------------------------------------------------------------------


def build_confirmation_inputs(plan: ExecutionPlan, current_prices: dict[str, float]) -> dict[str, dict]:
    """Build synthetic confirmation inputs for pipeline buy orders.

    When no real-time intraday data is available the engine substitutes
    the current close price for every technical field so that the
    confirmation logic can still evaluate orders without error.
    """
    confirmation_inputs: dict[str, dict] = {}
    for order in plan.buy_orders:
        price = current_prices.get(order.ticker, 0.0)
        if price <= 0:
            continue
        confirmation_inputs[order.ticker] = {
            "day_low": price,
            "ema30": price * 0.99,
            "current_price": price,
            "vwap": price * 0.995,
            "intraday_volume": 1.0,
            "avg_same_time_volume": 1.0,
            "industry_percentile": 0.5,
            "stock_pct_change": 0.0,
            "industry_pct_change": 0.0,
        }
    return confirmation_inputs


def build_pipeline_agent_output(decisions: dict[str, dict], active_tickers: Sequence[str]) -> AgentOutput:
    """Normalise *decisions* into a full :class:`AgentOutput` payload.

    Tickers without an explicit decision receive a ``hold / 0`` default.
    ``analyst_signals`` is left empty because the pipeline mode does not
    produce per-analyst breakdowns.
    """
    normalized = {
        ticker: decisions.get(ticker, {"action": "hold", "quantity": 0})
        for ticker in active_tickers
    }
    return {"decisions": normalized, "analyst_signals": {}}


# ---------------------------------------------------------------------------
# Agent-mode helpers
# ---------------------------------------------------------------------------


def resolve_agent_mode_day_window(current_date: pd.Timestamp) -> tuple[str, str, str] | None:
    """Return ``(lookback_start, current_date_str, previous_date_str)`` or ``None``.

    Returns ``None`` when the lookback window collapses to a single day
    (i.e. at the very start of the date range).
    """
    lookback_start = (current_date - relativedelta(months=1)).strftime("%Y-%m-%d")
    current_date_str = current_date.strftime("%Y-%m-%d")
    if lookback_start == current_date_str:
        return None
    previous_date_str = (current_date - relativedelta(days=1)).strftime("%Y-%m-%d")
    return lookback_start, current_date_str, previous_date_str


def run_agent_mode_agent(
    *,
    agent_controller: AgentController,
    agent,
    tickers: list[str],
    lookback_start: str,
    current_date_str: str,
    portfolio: Portfolio,
    model_name: str,
    model_provider: str,
    selected_analysts: list[str] | None,
) -> AgentOutput:
    """Invoke the agent controller for a single day in agent mode."""
    return agent_controller.run_agent(
        agent,
        tickers=tickers,
        start_date=lookback_start,
        end_date=current_date_str,
        portfolio=portfolio,
        model_name=model_name,
        model_provider=model_provider,
        selected_analysts=selected_analysts,
    )


def execute_agent_mode_trades(
    *,
    executor: TradeExecutor,
    tickers: list[str],
    decisions: dict[str, dict],
    current_prices: dict[str, float],
    portfolio: Portfolio,
) -> dict[str, int]:
    """Execute trades for every ticker and return ``{ticker: quantity}``."""
    executed_trades: dict[str, int] = {}
    for ticker in tickers:
        decision = decisions.get(ticker, {"action": "hold", "quantity": 0})
        executed_trades[ticker] = executor.execute_trade(
            ticker,
            decision.get("action", "hold"),
            decision.get("quantity", 0),
            current_prices[ticker],
            portfolio,
        )
    return executed_trades
