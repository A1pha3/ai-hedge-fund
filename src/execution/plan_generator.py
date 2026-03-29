"""执行计划生成器。"""

from __future__ import annotations

from src.execution.models import ExecutionPlan, LayerCResult
from src.portfolio.models import ExitSignal, PositionPlan
from src.screening.models import MarketState
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetMode


def generate_execution_plan(
    trade_date: str,
    market_state: MarketState,
    watchlist: list[LayerCResult],
    logic_scores: dict[str, float],
    buy_orders: list[PositionPlan],
    sell_orders: list[ExitSignal],
    portfolio_snapshot: dict,
    risk_alerts: list[str] | None = None,
    risk_metrics: dict | None = None,
    layer_a_count: int = 0,
    layer_b_count: int = 0,
    layer_c_count: int = 0,
    selection_targets: dict[str, DualTargetEvaluation] | None = None,
    target_mode: TargetMode = "research_only",
    dual_target_summary: DualTargetSummary | None = None,
    short_trade_target_profile_name: str = "default",
    short_trade_target_profile_config: dict | None = None,
) -> ExecutionPlan:
    return ExecutionPlan(
        date=trade_date,
        market_state=market_state,
        strategy_weights=market_state.adjusted_weights,
        logic_scores=logic_scores,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
        portfolio_snapshot=portfolio_snapshot,
        risk_alerts=risk_alerts or [],
        risk_metrics=risk_metrics or {},
        layer_a_count=layer_a_count,
        layer_b_count=layer_b_count,
        layer_c_count=layer_c_count,
        watchlist=watchlist,
        selection_targets=selection_targets or {},
        target_mode=target_mode,
        dual_target_summary=dual_target_summary or DualTargetSummary(target_mode=target_mode),
        short_trade_target_profile_name=str(short_trade_target_profile_name or "default"),
        short_trade_target_profile_config=dict(short_trade_target_profile_config or {}),
    )
