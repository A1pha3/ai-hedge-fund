from __future__ import annotations

import pandas as pd

from src.backtesting.engine_pending_plan_runner import PendingPlanRunner
from src.backtesting.engine_pipeline_helpers import build_pipeline_day_context
from src.backtesting.portfolio import Portfolio
from src.execution.models import ExecutionPlan
from src.portfolio.models import PositionPlan


class CapturingPipeline:
    def __init__(self) -> None:
        self.last_open_gap_pct = None
        self.last_confirmation_inputs = None

    def run_pre_market(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs) -> ExecutionPlan:
        self.last_open_gap_pct = kwargs.get("open_gap_pct")
        return plan

    def run_intraday(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs):
        self.last_confirmation_inputs = kwargs.get("confirmation_inputs")
        return [], [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0}


class NoopDecisionExecutor:
    def apply_decisions(self, **kwargs) -> None:
        return None


def test_pending_plan_runner_passes_open_gap_pct_to_pre_market():
    pipeline = CapturingPipeline()
    portfolio = Portfolio(tickers=["000001"], initial_cash=100_000.0, margin_requirement=0.0)
    runner = PendingPlanRunner(pipeline=pipeline, decision_executor=NoopDecisionExecutor(), portfolio=portfolio)

    pending_plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="000001", shares=100, amount=10_000.0)],
    )

    day_context = build_pipeline_day_context(
        current_date=pd.Timestamp("2024-03-04"),
        active_tickers=["000001"],
        current_prices={"000001": 10.0},
        daily_turnovers={},
        limit_up=set(),
        limit_down=set(),
        load_market_data_seconds=0.0,
    )

    def build_confirmation_inputs_fn(plan: ExecutionPlan, current_prices: dict[str, float], previous_date_str: str, current_date_str: str) -> dict[str, dict]:
        return {"000001": {"open_gap_pct": -0.02}}

    def process_pending_queues_fn(**kwargs):
        return [], [], []

    runner.run_pending_pipeline_plan(
        pending_plan=pending_plan,
        day_context=day_context,
        decisions={},
        executed_trades={},
        pending_buy_queue=[],
        pending_sell_queue=[],
        build_confirmation_inputs_fn=build_confirmation_inputs_fn,
        process_pending_queues_fn=process_pending_queues_fn,
    )

    assert pipeline.last_open_gap_pct == {"000001": -0.02}
    assert pipeline.last_confirmation_inputs == {"000001": {"open_gap_pct": -0.02}}
