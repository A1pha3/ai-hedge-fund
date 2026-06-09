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

import pandas as pd
from dateutil.relativedelta import relativedelta

from src.execution.models import ExecutionPlan
from src.tools.api import get_price_data

from .controller import AgentController
from .portfolio import Portfolio
from .trader import TradeExecutor
from .trading_constraints import TradeExecutionInputs
from .types import AgentOutput


# ---------------------------------------------------------------------------
# Shared helpers (used by both agent-mode and pipeline-mode)
# ---------------------------------------------------------------------------


def build_confirmation_inputs(
    plan: ExecutionPlan,
    current_prices: dict[str, float],
    previous_date_str: str = "",
    current_date_str: str = "",
) -> dict[str, dict]:
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
        payload = {
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
        if previous_date_str and current_date_str:
            try:
                price_data = get_price_data(order.ticker, previous_date_str, current_date_str)
            except Exception:
                price_data = None
            if price_data is not None and len(price_data) < 2:
                fallback_start = (pd.Timestamp(current_date_str) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
                try:
                    fallback_price_data = get_price_data(order.ticker, fallback_start, current_date_str)
                except Exception:
                    fallback_price_data = None
                if fallback_price_data is not None and not fallback_price_data.empty:
                    price_data = fallback_price_data
            if price_data is not None and not price_data.empty:
                current_row = price_data.iloc[-1]
                previous_row = price_data.iloc[-2] if len(price_data) >= 2 else None
                open_price = float(current_row.get("open", 0.0) or 0.0)
                prev_close = float(previous_row.get("close", 0.0) or 0.0) if previous_row is not None else 0.0
                day_low = float(current_row.get("low", price) or price)
                day_high = float(current_row.get("high", price) or price)
                # NOTE: 0.0 是合法 volume (停牌/无成交), 不能用 `or 1.0` 静默覆盖。
                _vol_raw = current_row.get("volume", 1.0)
                current_volume = float(_vol_raw) if _vol_raw is not None else 1.0
                _pvol_raw = previous_row.get("volume", current_volume) if previous_row is not None else current_volume
                previous_volume = float(_pvol_raw) if _pvol_raw is not None else current_volume
                payload.update(
                    {
                        "day_low": day_low if day_low > 0 else price,
                        "vwap": ((day_high + max(day_low, 0.0) + price) / 3.0) if day_high > 0 else price,
                        "intraday_volume": max(current_volume, 1.0),
                        "avg_same_time_volume": max(previous_volume, 1.0),
                        "stock_pct_change": ((price / prev_close) - 1.0) if prev_close > 0 else 0.0,
                        "open_price": open_price,
                        "prev_close": prev_close,
                        "open_gap_pct": ((open_price / prev_close) - 1.0) if open_price > 0 and prev_close > 0 else None,
                        "minutes_since_open": 10,
                    }
                )
        confirmation_inputs[order.ticker] = payload
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
    trade_date: str | None = None,
) -> dict[str, int]:
    """Execute trades for every ticker and return ``{ticker: quantity}``."""
    executed_trades: dict[str, int] = {}
    for ticker in tickers:
        decision = decisions.get(ticker, {"action": "hold", "quantity": 0})
        action = decision.get("action", "hold")
        
        # Capture position before execution for entry date tracking
        existing_long_before = int(portfolio.get_positions()[ticker]["long"])
        
        executed_qty = executor.execute_trade(
            ticker,
            action,
            decision.get("quantity", 0),
            current_prices[ticker],
            portfolio,
            execution_inputs=_build_agent_mode_execution_inputs(),
            trade_date=trade_date,
        )
        executed_trades[ticker] = executed_qty
        
        # Record long entry lifecycle data for successful buy executions
        if executed_qty > 0 and action == "buy" and trade_date is not None:
            _record_agent_mode_buy_execution(
                portfolio=portfolio,
                ticker=ticker,
                executed_qty=executed_qty,
                existing_long_before=existing_long_before,
                trade_date_compact=trade_date,
            )
    return executed_trades


def _build_agent_mode_execution_inputs() -> TradeExecutionInputs:
    """Keep agent-mode executions on the baseline resolver path.

    Agent mode currently submits action/quantity decisions without the BTST
    fragility payload that pipeline mode can attach, so these trades should
    resolve against baseline execution constraints until that data exists.
    """
    return TradeExecutionInputs(daily_turnover=None)


def _record_agent_mode_buy_execution(
    *,
    portfolio: Portfolio,
    ticker: str,
    executed_qty: int,
    existing_long_before: int,
    trade_date_compact: str,
) -> None:
    """Record long entry lifecycle data after successful buy execution.
    
    Reuses the same portfolio lifecycle pattern as pipeline mode to ensure
    T+1 enforcement functions correctly in agent mode.
    """
    portfolio.record_long_entry(
        ticker,
        trade_date_compact,
        reset=existing_long_before <= 0,
        entry_score=0.0,
        quality_score=0.5,
        industry_sw="",
        is_fundamental_driven=False,
    )
