"""Pending plan runner logic extracted from BacktestEngine.

This module encapsulates the full pending plan lifecycle: running the
pre-market preparation stage, executing the intraday stage (pending queues,
confirmation, exits, crisis), merging decisions, and applying them to the
portfolio via PipelineDecisionExecutor.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any
from collections.abc import Callable

from src.execution.daily_pipeline import DailyPipeline
from src.execution.models import ExecutionPlan, PendingOrder

from .engine_pipeline_decisions import PipelineDecisionExecutor
from .engine_pipeline_helpers import PipelineDayContext, extract_plan_risk_metrics
from .portfolio import Portfolio


@dataclass(frozen=True)
class PendingPipelinePreparationState:
    prepared_plan: ExecutionPlan
    pre_market_seconds: float
    previous_plan_counts: dict[str, int]
    previous_plan_timing: dict[str, float]
    previous_plan_funnel_diagnostics: dict


@dataclass(frozen=True)
class PendingPipelineIntradayState:
    confirmed_orders: list[Any]
    exits: list[Any]
    crisis_response: dict
    queue_alerts: list[str]
    intraday_seconds: float


@dataclass(frozen=True)
class PendingPlanRunResult:
    prepared_plan: ExecutionPlan
    pre_market_seconds: float
    intraday_seconds: float
    previous_plan_counts: dict[str, int]
    previous_plan_timing: dict[str, float]
    previous_plan_funnel_diagnostics: dict
    pending_buy_queue: list[PendingOrder]
    pending_sell_queue: list[PendingOrder]


class PendingPlanRunner:
    """Encapsulates the full pending plan lifecycle for pipeline-mode backtesting.

    Coordinates pre-market preparation, intraday execution (pending queues,
    order confirmation, exits, crisis response), decision merging, and
    application of decisions to the portfolio.
    """

    def __init__(
        self,
        *,
        pipeline: DailyPipeline,
        decision_executor: PipelineDecisionExecutor,
        portfolio: Portfolio,
    ) -> None:
        self._pipeline = pipeline
        self._decision_executor = decision_executor
        self._portfolio = portfolio

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_pending_pipeline_plan(
        self,
        *,
        pending_plan: ExecutionPlan,
        day_context: PipelineDayContext,
        decisions: dict[str, dict],
        executed_trades: dict[str, int],
        pending_buy_queue: list[PendingOrder],
        pending_sell_queue: list[PendingOrder],
        build_confirmation_inputs_fn: Callable[[ExecutionPlan, dict[str, float]], dict[str, dict]],
        process_pending_queues_fn: Callable[..., tuple[list[PendingOrder], list[PendingOrder], list[str]]],
    ) -> PendingPlanRunResult:
        preparation = self._build_pending_pipeline_preparation_state(
            pending_plan=pending_plan,
            trade_date_compact=day_context.trade_date_compact,
        )
        intraday_state, updated_buy_queue, updated_sell_queue = self._build_pending_pipeline_intraday_state(
            prepared_plan=preparation.prepared_plan,
            day_context=day_context,
            decisions=decisions,
            pending_buy_queue=pending_buy_queue,
            pending_sell_queue=pending_sell_queue,
            build_confirmation_inputs_fn=build_confirmation_inputs_fn,
            process_pending_queues_fn=process_pending_queues_fn,
        )
        self._apply_pending_plan_intraday_results(
            prepared_plan=preparation.prepared_plan,
            day_context=day_context,
            decisions=decisions,
            executed_trades=executed_trades,
            confirmed_orders=intraday_state.confirmed_orders,
            exits=intraday_state.exits,
            crisis_response=intraday_state.crisis_response,
            queue_alerts=intraday_state.queue_alerts,
            pending_buy_queue=updated_buy_queue,
            pending_sell_queue=updated_sell_queue,
        )
        return PendingPlanRunResult(
            prepared_plan=preparation.prepared_plan,
            pre_market_seconds=preparation.pre_market_seconds,
            intraday_seconds=intraday_state.intraday_seconds,
            previous_plan_counts=preparation.previous_plan_counts,
            previous_plan_timing=preparation.previous_plan_timing,
            previous_plan_funnel_diagnostics=preparation.previous_plan_funnel_diagnostics,
            pending_buy_queue=updated_buy_queue,
            pending_sell_queue=updated_sell_queue,
        )

    # ------------------------------------------------------------------
    # Preparation state
    # ------------------------------------------------------------------

    def _build_pending_pipeline_preparation_state(
        self,
        *,
        pending_plan: ExecutionPlan,
        trade_date_compact: str,
    ) -> PendingPipelinePreparationState:
        (
            prepared_plan,
            pre_market_seconds,
            previous_plan_counts,
            previous_plan_timing,
            previous_plan_funnel_diagnostics,
        ) = self._prepare_pending_pipeline_plan(
            pending_plan=pending_plan,
            trade_date_compact=trade_date_compact,
        )
        return PendingPipelinePreparationState(
            prepared_plan=prepared_plan,
            pre_market_seconds=pre_market_seconds,
            previous_plan_counts=previous_plan_counts,
            previous_plan_timing=previous_plan_timing,
            previous_plan_funnel_diagnostics=previous_plan_funnel_diagnostics,
        )

    def _prepare_pending_pipeline_plan(
        self,
        *,
        pending_plan: ExecutionPlan,
        trade_date_compact: str,
    ) -> tuple[ExecutionPlan, float, dict[str, int], dict[str, float], dict]:
        stage_started_at = perf_counter()
        prepared_plan = self._pipeline.run_pre_market(pending_plan, trade_date_compact)
        pre_market_seconds = perf_counter() - stage_started_at
        previous_plan_counts, previous_plan_timing, previous_plan_funnel_diagnostics = extract_plan_risk_metrics(pending_plan)
        return prepared_plan, pre_market_seconds, previous_plan_counts, previous_plan_timing, previous_plan_funnel_diagnostics

    # ------------------------------------------------------------------
    # Intraday state
    # ------------------------------------------------------------------

    def _build_pending_pipeline_intraday_state(
        self,
        *,
        prepared_plan: ExecutionPlan,
        day_context: PipelineDayContext,
        decisions: dict[str, dict],
        pending_buy_queue: list[PendingOrder],
        pending_sell_queue: list[PendingOrder],
        build_confirmation_inputs_fn: Callable[[ExecutionPlan, dict[str, float]], dict[str, dict]],
        process_pending_queues_fn: Callable[..., tuple[list[PendingOrder], list[PendingOrder], list[str]]],
    ) -> tuple[PendingPipelineIntradayState, list[PendingOrder], list[PendingOrder]]:
        stage_started_at = perf_counter()
        confirmation_inputs = build_confirmation_inputs_fn(prepared_plan, day_context.current_prices)
        updated_buy_queue, updated_sell_queue, queue_alerts = self._run_pending_intraday_queue_stage(
            prepared_plan=prepared_plan,
            day_context=day_context,
            decisions=decisions,
            pending_buy_queue=pending_buy_queue,
            pending_sell_queue=pending_sell_queue,
            process_pending_queues_fn=process_pending_queues_fn,
        )
        confirmed_orders, exits, crisis_response = self._run_pending_intraday_pipeline(
            prepared_plan=prepared_plan,
            trade_date_compact=day_context.trade_date_compact,
            confirmation_inputs=confirmation_inputs,
        )
        intraday_seconds = perf_counter() - stage_started_at
        return (
            PendingPipelineIntradayState(
                confirmed_orders=confirmed_orders,
                exits=exits,
                crisis_response=crisis_response,
                queue_alerts=queue_alerts,
                intraday_seconds=intraday_seconds,
            ),
            updated_buy_queue,
            updated_sell_queue,
        )

    def _run_pending_intraday_queue_stage(
        self,
        *,
        prepared_plan: ExecutionPlan,
        day_context: PipelineDayContext,
        decisions: dict[str, dict],
        pending_buy_queue: list[PendingOrder],
        pending_sell_queue: list[PendingOrder],
        process_pending_queues_fn: Callable[..., tuple[list[PendingOrder], list[PendingOrder], list[str]]],
    ) -> tuple[list[PendingOrder], list[PendingOrder], list[str]]:
        return process_pending_queues_fn(
            prepared_plan=prepared_plan,
            trade_date_compact=day_context.trade_date_compact,
            current_prices=day_context.current_prices,
            limit_up=day_context.limit_up,
            limit_down=day_context.limit_down,
            decisions=decisions,
            pending_buy_queue=pending_buy_queue,
            pending_sell_queue=pending_sell_queue,
        )

    def _run_pending_intraday_pipeline(
        self,
        *,
        prepared_plan: ExecutionPlan,
        trade_date_compact: str,
        confirmation_inputs: list[dict[str, Any]],
    ) -> tuple[list, list, dict]:
        return self._pipeline.run_intraday(
            prepared_plan,
            trade_date_compact,
            confirmation_inputs=confirmation_inputs,
            crisis_inputs={"drawdown_pct": 0.0},
        )

    # ------------------------------------------------------------------
    # Apply intraday results
    # ------------------------------------------------------------------

    def _apply_pending_plan_intraday_results(
        self,
        *,
        prepared_plan: ExecutionPlan,
        day_context: PipelineDayContext,
        decisions: dict[str, dict],
        executed_trades: dict[str, int],
        confirmed_orders: list[Any],
        exits: list[Any],
        crisis_response: dict,
        queue_alerts: list[str],
        pending_buy_queue: list[PendingOrder],
        pending_sell_queue: list[PendingOrder],
    ) -> None:
        self._merge_pending_intraday_decisions(
            decisions=decisions,
            confirmed_orders=confirmed_orders,
            exits=exits,
            crisis_response=crisis_response,
        )
        self._apply_pipeline_decisions(
            prepared_plan=prepared_plan,
            current_prices=day_context.current_prices,
            daily_turnovers=day_context.daily_turnovers,
            limit_up=day_context.limit_up,
            limit_down=day_context.limit_down,
            trade_date_compact=day_context.trade_date_compact,
            decisions=decisions,
            executed_trades=executed_trades,
            pending_buy_queue=pending_buy_queue,
            pending_sell_queue=pending_sell_queue,
        )
        prepared_plan.risk_alerts.extend(queue_alerts)

    def _apply_pipeline_decisions(
        self,
        *,
        prepared_plan: ExecutionPlan,
        current_prices: dict[str, float],
        daily_turnovers: dict[str, float],
        limit_up: set[str],
        limit_down: set[str],
        trade_date_compact: str,
        decisions: dict[str, dict],
        executed_trades: dict[str, int],
        pending_buy_queue: list[PendingOrder],
        pending_sell_queue: list[PendingOrder],
    ) -> None:
        self._decision_executor.apply_decisions(
            prepared_plan=prepared_plan,
            current_prices=current_prices,
            daily_turnovers=daily_turnovers,
            limit_up=limit_up,
            limit_down=limit_down,
            trade_date_compact=trade_date_compact,
            decisions=decisions,
            executed_trades=executed_trades,
            pending_buy_queue=pending_buy_queue,
            pending_sell_queue=pending_sell_queue,
        )

    # ------------------------------------------------------------------
    # Merge decisions
    # ------------------------------------------------------------------

    def _merge_pending_intraday_decisions(self, *, decisions: dict[str, dict], confirmed_orders: list, exits: list, crisis_response: dict) -> None:
        if crisis_response.get("pause_new_buys"):
            confirmed_orders = []
        self._apply_confirmed_order_decisions(decisions=decisions, confirmed_orders=confirmed_orders)
        self._apply_exit_signal_decisions(decisions=decisions, exits=exits)
        self._apply_crisis_reduce_decisions(decisions=decisions, crisis_response=crisis_response)

    def _apply_confirmed_order_decisions(self, *, decisions: dict[str, dict], confirmed_orders: list) -> None:
        for order in confirmed_orders:
            self._portfolio.ensure_ticker(order.ticker)
            decisions[order.ticker] = {"action": "buy", "quantity": order.shares}

    def _apply_exit_signal_decisions(self, *, decisions: dict[str, dict], exits: list) -> None:
        for exit_signal in exits:
            self._portfolio.ensure_ticker(exit_signal.ticker)
            long_shares = self._portfolio.get_positions()[exit_signal.ticker]["long"]
            sell_quantity = int(long_shares * exit_signal.sell_ratio)
            if sell_quantity > 0:
                decisions[exit_signal.ticker] = {"action": "sell", "quantity": sell_quantity, "reason": str(getattr(exit_signal, "trigger_reason", "") or "")}

    def _apply_crisis_reduce_decisions(self, *, decisions: dict[str, dict], crisis_response: dict) -> None:
        reduce_ratio = float(crisis_response.get("forced_reduce_ratio", 0.0) or 0.0)
        if reduce_ratio <= 0:
            return
        for ticker, position in self._portfolio.get_positions().items():
            if position["long"] <= 0:
                continue
            sell_quantity = int(position["long"] * reduce_ratio)
            if sell_quantity <= 0:
                continue
            decisions[ticker] = {"action": "sell", "quantity": max(sell_quantity, decisions.get(ticker, {}).get("quantity", 0))}
