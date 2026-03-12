"""执行计划生成器。"""

from __future__ import annotations

from src.execution.models import ExecutionPlan, LayerCResult
from src.portfolio.models import ExitSignal, PositionPlan
from src.screening.models import MarketState


def generate_execution_plan(
    trade_date: str,
    market_state: MarketState,
    watchlist: list[LayerCResult],
    buy_orders: list[PositionPlan],
    sell_orders: list[ExitSignal],
    portfolio_snapshot: dict,
    risk_alerts: list[str] | None = None,
    risk_metrics: dict | None = None,
    layer_a_count: int = 0,
    layer_b_count: int = 0,
    layer_c_count: int = 0,
) -> ExecutionPlan:
    return ExecutionPlan(
        date=trade_date,
        market_state=market_state,
        strategy_weights=market_state.adjusted_weights,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
        portfolio_snapshot=portfolio_snapshot,
        risk_alerts=risk_alerts or [],
        risk_metrics=risk_metrics or {},
        layer_a_count=layer_a_count,
        layer_b_count=layer_b_count,
        layer_c_count=layer_c_count,
        watchlist=watchlist,
    )
