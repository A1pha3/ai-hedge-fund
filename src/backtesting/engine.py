from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any
from collections.abc import Callable, Sequence

import pandas as pd
from dateutil.relativedelta import relativedelta

from src.execution.daily_pipeline import DailyPipeline
from src.execution.models import ExecutionPlan, PendingOrder
from src.research.artifacts import SelectionArtifactWriter
from .engine_market_data import (
    MarketDataLoader,
    normalize_ticker,
    shift_business_days,
)
from .engine_pipeline_helpers import (
    PipelineDayContext,
    build_pipeline_active_tickers,
    build_pipeline_day_context,
    build_pipeline_event_payload,
    build_pipeline_timing_payload,
    collect_execution_plan_observations,
    initialize_pipeline_day_state,
)

from .benchmarks import BenchmarkCalculator
from .controller import AgentController
from .engine_checkpoint_helpers import (
    build_checkpoint_payload,
    deserialize_portfolio_values,
    read_checkpoint,
    restore_exit_reentry_cooldowns,
    restore_pending_orders,
    restore_pending_plan,
    serialize_portfolio_values,
    write_checkpoint,
)
from .engine_pending_helpers import (
    apply_pending_buy_result,
    apply_pending_sell_result,
    dedupe_pending_orders,
    evaluate_pending_buy_order,
    evaluate_pending_sell_order,
    process_pending_queues,
)
from .engine_agent_mode import (
    build_confirmation_inputs,
    build_pipeline_agent_output,
    execute_agent_mode_trades,
    resolve_agent_mode_day_window,
    run_agent_mode_agent,
)
from .engine_pending_plan_runner import PendingPlanRunner, PendingPlanRunResult
from .engine_pipeline_decisions import PipelineDecisionExecutor
from .engine_telemetry_helpers import (
    build_pipeline_day_record_payloads as build_pipeline_day_record_payloads_helper,
)
from .metrics import PerformanceMetricsCalculator
from .output import OutputBuilder
from .portfolio import Portfolio


@dataclass
class PipelineModeDayState:
    decisions: dict[str, dict]
    executed_trades: dict[str, int]
    pre_market_seconds: float = 0.0
    intraday_seconds: float = 0.0
    append_daily_state_seconds: float = 0.0
    post_market_seconds: float = 0.0
    previous_plan_counts: dict[str, int] = field(default_factory=dict)
    previous_plan_timing: dict[str, float] = field(default_factory=dict)
    previous_plan_funnel_diagnostics: dict = field(default_factory=dict)
    prepared_plan: ExecutionPlan | None = None


from .trader import TradeExecutor, TradingConstraints
from .types import AgentOutput, BacktestMode, PerformanceMetrics, PortfolioValuePoint
from .valuation import calculate_portfolio_value, compute_exposures


class BacktestEngine:
    """Coordinates the backtest loop using the new components.

    This implementation mirrors the semantics of src/backtester.py while
    avoiding any changes to that file. It orchestrates agent decisions,
    trade execution, valuation, exposures and performance metrics.
    """

    def __init__(
        self,
        *,
        agent,
        tickers: list[str],
        start_date: str,
        end_date: str,
        initial_capital: float,
        model_name: str,
        model_provider: str,
        selected_analysts: list[str] | None,
        initial_margin_requirement: float,
        backtest_mode: BacktestMode = "agent",
        pipeline: DailyPipeline | None = None,
        checkpoint_path: str | None = None,
        pipeline_event_recorder: Callable[[dict], None] | None = None,
        selection_artifact_writer: SelectionArtifactWriter | None = None,
    ) -> None:
        self._initialize_engine_configuration(
            agent=agent,
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            model_name=model_name,
            model_provider=model_provider,
            selected_analysts=selected_analysts,
            backtest_mode=backtest_mode,
            pipeline=pipeline,
            checkpoint_path=checkpoint_path,
            pipeline_event_recorder=pipeline_event_recorder,
            selection_artifact_writer=selection_artifact_writer,
        )
        self._initialize_engine_components(
            tickers=tickers,
            initial_capital=initial_capital,
            initial_margin_requirement=initial_margin_requirement,
            backtest_mode=backtest_mode,
        )
        self._initialize_engine_runtime_state()

    def _initialize_engine_configuration(
        self,
        *,
        agent,
        tickers: list[str],
        start_date: str,
        end_date: str,
        initial_capital: float,
        model_name: str,
        model_provider: str,
        selected_analysts: list[str] | None,
        backtest_mode: BacktestMode,
        pipeline: DailyPipeline | None,
        checkpoint_path: str | None,
        pipeline_event_recorder: Callable[[dict], None] | None,
        selection_artifact_writer: SelectionArtifactWriter | None,
    ) -> None:
        self._agent = agent
        self._tickers = tickers
        self._start_date = start_date
        self._end_date = end_date
        self._initial_capital = float(initial_capital)
        self._model_name = model_name
        self._model_provider = model_provider
        self._selected_analysts = selected_analysts
        self._backtest_mode = backtest_mode
        self._pipeline = pipeline or (DailyPipeline(base_model_name=model_name, base_model_provider=model_provider) if backtest_mode == "pipeline" else None)
        self._checkpoint_path = Path(checkpoint_path) if checkpoint_path else None
        self._timing_log_path = self._resolve_timing_log_path()
        self._pipeline_event_recorder = pipeline_event_recorder
        self._selection_artifact_writer = selection_artifact_writer

    def _initialize_engine_components(
        self,
        *,
        tickers: list[str],
        initial_capital: float,
        initial_margin_requirement: float,
        backtest_mode: BacktestMode,
    ) -> None:
        self._portfolio = Portfolio(
            tickers=tickers,
            initial_cash=initial_capital,
            margin_requirement=initial_margin_requirement,
        )
        self._executor = TradeExecutor(TradingConstraints() if backtest_mode == "pipeline" else TradingConstraints(commission_rate=0.0, stamp_duty_rate=0.0, base_slippage_rate=0.0, low_liquidity_slippage_rate=0.0))
        self._agent_controller = AgentController()
        self._perf = PerformanceMetricsCalculator()
        self._results = OutputBuilder(initial_capital=self._initial_capital)

        # Benchmark calculator
        self._benchmark = BenchmarkCalculator()

    def _initialize_engine_runtime_state(self) -> None:
        self._portfolio_values: list[PortfolioValuePoint] = []
        self._table_rows: list[list] = []
        self._performance_metrics: PerformanceMetrics = {
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "max_drawdown": None,
            "long_short_ratio": None,
            "gross_exposure": None,
            "net_exposure": None,
        }
        self._pending_buy_queue: list[PendingOrder] = []
        self._pending_sell_queue: list[PendingOrder] = []
        self._exit_reentry_cooldowns: dict[str, dict] = {}
        self._market_loader = self._create_market_loader()
        self._decision_executor = PipelineDecisionExecutor(
            portfolio=self._portfolio,
            executor=self._executor,
            register_cooldown_fn=self._register_exit_reentry_cooldown,
        )
        self._pending_plan_runner = self._build_pending_plan_runner()

    def _build_pending_plan_runner(self) -> PendingPlanRunner:
        if self._pipeline is None:
            return None  # type: ignore[return-value]
        return PendingPlanRunner(
            pipeline=self._pipeline,
            decision_executor=self._decision_executor,
            portfolio=self._portfolio,
        )

    def _build_process_pending_queues_fn(
        self,
        pending_buy_queue: list[PendingOrder],
        pending_sell_queue: list[PendingOrder],
    ) -> Callable[..., tuple[list[PendingOrder], list[PendingOrder], list[str]]]:
        def _process_pending_queues_with_queues(
            *,
            prepared_plan: ExecutionPlan,
            trade_date_compact: str,
            current_prices: dict[str, float],
            limit_up: set[str],
            limit_down: set[str],
            decisions: dict[str, dict],
            **_kwargs: Any,
        ) -> tuple[list[PendingOrder], list[PendingOrder], list[str]]:
            return self._process_pending_queues(
                prepared_plan=prepared_plan,
                trade_date_compact=trade_date_compact,
                current_prices=current_prices,
                limit_up=limit_up,
                limit_down=limit_down,
                decisions=decisions,
            )
        return _process_pending_queues_with_queues

    def _resolve_timing_log_path(self) -> Path | None:
        explicit_path = os.getenv("BACKTEST_TIMING_LOG_PATH")
        if explicit_path:
            return Path(explicit_path)
        if self._checkpoint_path is not None:
            return self._checkpoint_path.with_name(f"{self._checkpoint_path.stem}.timings.jsonl")
        return None

    def _append_timing_log(self, payload: dict) -> None:
        if self._timing_log_path is None:
            return
        self._timing_log_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "logged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": self._backtest_mode,
            **payload,
        }
        with self._timing_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _append_pipeline_event(self, payload: dict) -> None:
        if self._pipeline_event_recorder is None:
            return
        self._pipeline_event_recorder(payload)

    def _write_selection_artifacts(self, plan: ExecutionPlan, trade_date_compact: str) -> None:
        if self._selection_artifact_writer is None:
            return
        try:
            result = self._selection_artifact_writer.write_for_plan(
                plan=plan,
                trade_date=trade_date_compact,
                pipeline=self._pipeline,
                selected_analysts=self._selected_analysts,
            )
            plan.selection_artifacts = result.model_dump(mode="json", exclude_none=True)
        except Exception as error:
            plan.selection_artifacts = {
                "write_status": "failed",
                "error_message": str(error),
            }

    def _serialize_portfolio_values(self) -> list[dict]:
        return serialize_portfolio_values(self._portfolio_values)

    def _save_checkpoint(self, last_processed_date: str, pending_plan: ExecutionPlan | None = None) -> None:
        if self._checkpoint_path is None:
            return

        payload = build_checkpoint_payload(
            last_processed_date=last_processed_date,
            portfolio_snapshot=self._portfolio.get_snapshot(),
            portfolio_values=self._portfolio_values,
            performance_metrics=dict(self._performance_metrics),
            pending_buy_queue=self._pending_buy_queue,
            pending_sell_queue=self._pending_sell_queue,
            exit_reentry_cooldowns=self._exit_reentry_cooldowns,
            pending_plan=pending_plan,
        )
        write_checkpoint(self._checkpoint_path, payload)

    def _load_checkpoint(self) -> tuple[str | None, ExecutionPlan | None]:
        if self._checkpoint_path is None or not self._checkpoint_path.exists():
            return None, None

        payload = read_checkpoint(self._checkpoint_path)
        self._portfolio.load_snapshot(payload["portfolio_snapshot"])
        self._portfolio_values = deserialize_portfolio_values(payload.get("portfolio_values", []))
        self._performance_metrics.update(payload.get("performance_metrics", {}))
        self._pending_buy_queue = restore_pending_orders(payload.get("pending_buy_queue", []))
        self._pending_sell_queue = restore_pending_orders(payload.get("pending_sell_queue", []))
        self._exit_reentry_cooldowns = restore_exit_reentry_cooldowns(payload.get("exit_reentry_cooldowns", {}))
        pending_plan = restore_pending_plan(payload.get("pending_plan"))
        return payload.get("last_processed_date"), pending_plan

    def _clear_checkpoint(self) -> None:
        if self._checkpoint_path is not None and self._checkpoint_path.exists():
            self._checkpoint_path.unlink()

    # ------------------------------------------------------------------
    # MarketDataLoader delegation
    # ------------------------------------------------------------------

    def _create_market_loader(self) -> MarketDataLoader:
        return MarketDataLoader(
            tickers=self._tickers,
            start_date=self._start_date,
            end_date=self._end_date,
            portfolio=self._portfolio,
            exit_reentry_cooldowns=self._exit_reentry_cooldowns,
        )

    def _prefetch_data(self) -> None:
        self._market_loader.prefetch_data()

    def _iter_backtest_dates(self) -> pd.DatetimeIndex:
        return self._market_loader.iter_backtest_dates()

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        return normalize_ticker(ticker)

    @staticmethod
    def _shift_business_days(trade_date_compact: str, business_days: int) -> str:
        return shift_business_days(trade_date_compact, business_days)

    def _register_exit_reentry_cooldown(self, ticker: str, trade_date_compact: str, trigger_reason: str) -> None:
        self._market_loader.register_exit_reentry_cooldown(ticker, trade_date_compact, trigger_reason)

    def _get_active_exit_reentry_cooldowns(self, trade_date_compact: str) -> dict[str, dict]:
        return self._market_loader.get_active_exit_reentry_cooldowns(trade_date_compact)

    def _get_limit_state(self, trade_date_compact: str) -> tuple[set[str], set[str]]:
        return self._market_loader.get_limit_state(trade_date_compact)

    def _get_daily_turnovers(self, active_tickers: Sequence[str], previous_date_str: str, current_date_str: str) -> dict[str, float]:
        return self._market_loader.get_daily_turnovers(active_tickers, previous_date_str, current_date_str)

    def _load_current_prices(self, tickers: Sequence[str], previous_date_str: str, current_date_str: str) -> dict[str, float] | None:
        return self._market_loader.load_current_prices(tickers, previous_date_str, current_date_str)

    def _hydrate_position_prices(self, current_prices: dict[str, float], previous_date_str: str, current_date_str: str) -> dict[str, float]:
        return self._market_loader.hydrate_position_prices(current_prices, previous_date_str, current_date_str)

    def _append_daily_state(
        self,
        *,
        current_date,
        current_date_str: str,
        active_tickers: Sequence[str],
        agent_output: AgentOutput,
        executed_trades: dict[str, int],
        current_prices: dict[str, float],
    ) -> None:
        total_value, point = self._build_daily_portfolio_point(current_date=current_date, current_prices=current_prices)
        self._portfolio_values.append(point)

        rows = self._build_daily_state_rows(
            date_str=current_date_str,
            tickers=active_tickers,
            agent_output=agent_output,
            executed_trades=executed_trades,
            current_prices=current_prices,
            total_value=total_value,
        )
        self._table_rows = rows + self._table_rows
        self._results.print_rows(self._table_rows)

        self._update_daily_performance_metrics()

    def _build_daily_portfolio_point(
        self,
        *,
        current_date,
        current_prices: dict[str, float],
    ) -> tuple[float, PortfolioValuePoint]:
        total_value = calculate_portfolio_value(self._portfolio, current_prices)
        exposures = compute_exposures(self._portfolio, current_prices)
        point: PortfolioValuePoint = {
            "Date": current_date,
            "Portfolio Value": total_value,
            "Long Exposure": exposures["Long Exposure"],
            "Short Exposure": exposures["Short Exposure"],
            "Gross Exposure": exposures["Gross Exposure"],
            "Net Exposure": exposures["Net Exposure"],
            "Long/Short Ratio": exposures["Long/Short Ratio"],
        }
        return total_value, point

    def _build_daily_state_rows(
        self,
        *,
        date_str: str,
        tickers: Sequence[str],
        agent_output: AgentOutput,
        executed_trades: dict[str, int],
        current_prices: dict[str, float],
        total_value: float,
    ) -> list[list]:
        return self._results.build_day_rows(
            date_str=date_str,
            tickers=tickers,
            agent_output=agent_output,
            executed_trades=executed_trades,
            current_prices=current_prices,
            portfolio=self._portfolio,
            performance_metrics=self._performance_metrics,
            total_value=total_value,
            benchmark_return_pct=self._benchmark.get_return_pct("SPY", self._start_date, date_str),
        )

    def _update_daily_performance_metrics(self) -> None:
        if len(self._portfolio_values) <= 3:
            return
        computed = self._perf.compute_metrics(self._portfolio_values)
        if computed:
            self._performance_metrics.update(computed)

    def _run_agent_mode(self, dates: pd.DatetimeIndex) -> PerformanceMetrics:
        for current_date in dates:
            day_window = resolve_agent_mode_day_window(current_date)
            if day_window is None:
                continue
            lookback_start, current_date_str, previous_date_str = day_window

            current_prices = self._load_current_prices(self._tickers, previous_date_str, current_date_str)
            if current_prices is None:
                continue

            agent_output = run_agent_mode_agent(
                agent_controller=self._agent_controller,
                agent=self._agent,
                tickers=self._tickers,
                lookback_start=lookback_start,
                current_date_str=current_date_str,
                portfolio=self._portfolio,
                model_name=self._model_name,
                model_provider=self._model_provider,
                selected_analysts=self._selected_analysts,
            )
            executed_trades = execute_agent_mode_trades(
                executor=self._executor,
                tickers=self._tickers,
                decisions=agent_output["decisions"],
                current_prices=current_prices,
                portfolio=self._portfolio,
            )
            self._append_daily_state(
                current_date=current_date,
                current_date_str=current_date_str,
                active_tickers=self._tickers,
                agent_output=agent_output,
                executed_trades=executed_trades,
                current_prices=current_prices,
            )

        return self._performance_metrics

    def _build_confirmation_inputs(self, plan: ExecutionPlan, current_prices: dict[str, float]) -> dict[str, dict]:
        return build_confirmation_inputs(plan, current_prices)

    def _build_pipeline_agent_output(self, decisions: dict[str, dict], active_tickers: Sequence[str]) -> AgentOutput:
        return build_pipeline_agent_output(decisions, active_tickers)

    @staticmethod
    def _dedupe_pending_orders(orders: Sequence[PendingOrder]) -> list[PendingOrder]:
        return dedupe_pending_orders(orders)

    def _process_single_pending_buy(
        self,
        *,
        order: PendingOrder,
        current_prices: dict[str, float],
        limit_up: set[str],
        watch_scores: dict[str, float],
        decisions: dict[str, dict],
        next_pending_buy: list[PendingOrder],
        alerts: list[str],
    ) -> None:
        normalized_ticker = self._normalize_ticker(order.ticker)
        price = current_prices.get(order.ticker)
        if price is None:
            next_pending_buy.append(order)
            return
        result = self._evaluate_pending_buy_order(**self._build_pending_buy_evaluation_kwargs(
            order=order,
            price=price,
            normalized_ticker=normalized_ticker,
            watch_scores=watch_scores,
            limit_up=limit_up,
        ))
        self._apply_pending_buy_result(
            order=order,
            result=result,
            decisions=decisions,
            next_pending_buy=next_pending_buy,
            alerts=alerts,
        )

    @staticmethod
    def _build_pending_buy_evaluation_kwargs(
        *,
        order: PendingOrder,
        price: float,
        normalized_ticker: str,
        watch_scores: dict[str, float],
        limit_up: set[str],
    ) -> dict[str, Any]:
        return {
            "order": order,
            "current_score": watch_scores.get(order.ticker, order.original_score),
            "is_limit_up": normalized_ticker in limit_up,
            "price": price,
        }

    @staticmethod
    def _evaluate_pending_buy_order(
        *,
        order: PendingOrder,
        current_score: float,
        is_limit_up: bool,
        price: float,
    ) -> dict:
        return evaluate_pending_buy_order(
            order=order,
            current_score=current_score,
            is_limit_up=is_limit_up,
            price=price,
        )

    @staticmethod
    def _apply_pending_buy_result(
        *,
        order: PendingOrder,
        result: dict,
        decisions: dict[str, dict],
        next_pending_buy: list[PendingOrder],
        alerts: list[str],
    ) -> None:
        apply_pending_buy_result(
            order=order,
            result=result,
            decisions=decisions,
            next_pending_buy=next_pending_buy,
            alerts=alerts,
        )

    def _process_single_pending_sell(
        self,
        *,
        order: PendingOrder,
        limit_down: set[str],
        decisions: dict[str, dict],
        next_pending_sell: list[PendingOrder],
        alerts: list[str],
    ) -> None:
        normalized_ticker = self._normalize_ticker(order.ticker)
        result = self._evaluate_pending_sell_order(order=order, is_limit_down=normalized_ticker in limit_down)
        self._apply_pending_sell_result(
            order=order,
            result=result,
            decisions=decisions,
            next_pending_sell=next_pending_sell,
            alerts=alerts,
        )

    @staticmethod
    def _evaluate_pending_sell_order(*, order: PendingOrder, is_limit_down: bool) -> dict:
        return evaluate_pending_sell_order(order=order, is_limit_down=is_limit_down)

    @staticmethod
    def _apply_pending_sell_result(
        *,
        order: PendingOrder,
        result: dict,
        decisions: dict[str, dict],
        next_pending_sell: list[PendingOrder],
        alerts: list[str],
    ) -> None:
        apply_pending_sell_result(
            order=order,
            result=result,
            decisions=decisions,
            next_pending_sell=next_pending_sell,
            alerts=alerts,
        )

    def _process_pending_queues(
        self,
        *,
        prepared_plan: ExecutionPlan,
        trade_date_compact: str,
        current_prices: dict[str, float],
        limit_up: set[str],
        limit_down: set[str],
        decisions: dict[str, dict],
    ) -> tuple[list[PendingOrder], list[PendingOrder], list[str]]:
        return process_pending_queues(
            pending_buy_queue=self._pending_buy_queue,
            pending_sell_queue=self._pending_sell_queue,
            prepared_plan=prepared_plan,
            current_prices=current_prices,
            limit_up=limit_up,
            limit_down=limit_down,
            decisions=decisions,
            process_single_pending_buy=self._process_single_pending_buy,
            process_single_pending_sell=self._process_single_pending_sell,
            dedupe_pending_orders_fn=self._dedupe_pending_orders,
        )

    def _load_pipeline_day_context(
        self,
        *,
        current_date: pd.Timestamp,
        pending_plan: ExecutionPlan | None,
    ) -> PipelineDayContext | None:
        active_tickers = self._build_pipeline_active_tickers(pending_plan)
        stage_started_at = perf_counter()
        current_date_str, previous_date_str = self._resolve_pipeline_day_dates(current_date)
        market_snapshot = self._load_pipeline_market_snapshot(
            active_tickers=active_tickers,
            previous_date_str=previous_date_str,
            current_date_str=current_date_str,
        )
        if market_snapshot is None:
            return None
        current_prices, daily_turnovers = market_snapshot
        limit_up, limit_down = self._load_pipeline_limit_state(current_date)
        return build_pipeline_day_context(**self._build_pipeline_day_context_kwargs(
            current_date=current_date,
            active_tickers=active_tickers,
            current_prices=current_prices,
            daily_turnovers=daily_turnovers,
            limit_up=limit_up,
            limit_down=limit_down,
            stage_started_at=stage_started_at,
        ))

    @staticmethod
    def _build_pipeline_day_context_kwargs(
        *,
        current_date: pd.Timestamp,
        active_tickers: list[str],
        current_prices: dict[str, float],
        daily_turnovers: dict[str, float],
        limit_up: set[str],
        limit_down: set[str],
        stage_started_at: float,
    ) -> dict[str, Any]:
        return {
            "current_date": current_date,
            "active_tickers": active_tickers,
            "current_prices": current_prices,
            "daily_turnovers": daily_turnovers,
            "limit_up": limit_up,
            "limit_down": limit_down,
            "load_market_data_seconds": perf_counter() - stage_started_at,
        }

    def _build_pipeline_active_tickers(self, pending_plan: ExecutionPlan | None) -> list[str]:
        return build_pipeline_active_tickers(
            base_tickers=self._tickers,
            position_tickers=self._portfolio.get_positions().keys(),
            pending_plan=pending_plan,
        )

    @staticmethod
    def _resolve_pipeline_day_dates(current_date: pd.Timestamp) -> tuple[str, str]:
        current_date_str = current_date.strftime("%Y-%m-%d")
        previous_date_str = (current_date - relativedelta(days=1)).strftime("%Y-%m-%d")
        return current_date_str, previous_date_str

    def _load_pipeline_market_snapshot(
        self,
        *,
        active_tickers: Sequence[str],
        previous_date_str: str,
        current_date_str: str,
    ) -> tuple[dict[str, float], dict[str, float]] | None:
        current_prices = self._load_current_prices(active_tickers, previous_date_str, current_date_str)
        if current_prices is None:
            return None
        return (
            self._hydrate_position_prices(current_prices, previous_date_str, current_date_str),
            self._get_daily_turnovers(active_tickers, previous_date_str, current_date_str),
        )

    def _load_pipeline_limit_state(self, current_date: pd.Timestamp) -> tuple[set[str], set[str]]:
        return self._get_limit_state(current_date.strftime("%Y%m%d"))

    def _run_pipeline_mode(self, dates: pd.DatetimeIndex, pending_plan: ExecutionPlan | None = None) -> PerformanceMetrics:
        for current_date in dates:
            day_started_at = perf_counter()
            day_context = self._load_pipeline_day_context(current_date=current_date, pending_plan=pending_plan)
            if day_context is None:
                continue

            day_state = self._initialize_pipeline_mode_day_state(day_context.active_tickers)
            self._run_pipeline_mode_pending_plan_if_present(day_context=day_context, pending_plan=pending_plan, day_state=day_state)
            current_prices = self._append_pipeline_mode_daily_state(day_context=day_context, day_state=day_state)
            pending_plan = self._run_pipeline_mode_post_market(day_context=day_context, pending_plan=pending_plan, day_state=day_state)
            self._record_pipeline_mode_day(
                day_context=day_context,
                day_state=day_state,
                pending_plan=pending_plan,
                current_prices=current_prices,
                day_started_at=day_started_at,
            )
            self._save_checkpoint(day_context.current_date_str, pending_plan)

        return self._performance_metrics

    def _initialize_pipeline_mode_day_state(self, active_tickers: Sequence[str]) -> PipelineModeDayState:
        decisions, executed_trades = initialize_pipeline_day_state(active_tickers)
        return PipelineModeDayState(decisions=decisions, executed_trades=executed_trades)

    def _run_pipeline_mode_pending_plan_if_present(
        self,
        *,
        day_context: PipelineDayContext,
        pending_plan: ExecutionPlan | None,
        day_state: PipelineModeDayState,
    ) -> None:
        if pending_plan is None or self._pending_plan_runner is None:
            return
        result = self._pending_plan_runner.run_pending_pipeline_plan(
            pending_plan=pending_plan,
            day_context=day_context,
            decisions=day_state.decisions,
            executed_trades=day_state.executed_trades,
            pending_buy_queue=self._pending_buy_queue,
            pending_sell_queue=self._pending_sell_queue,
            build_confirmation_inputs_fn=self._build_confirmation_inputs,
            process_pending_queues_fn=self._build_process_pending_queues_fn(
                self._pending_buy_queue,
                self._pending_sell_queue,
            ),
        )
        day_state.prepared_plan = result.prepared_plan
        day_state.pre_market_seconds = result.pre_market_seconds
        day_state.intraday_seconds = result.intraday_seconds
        day_state.previous_plan_counts = result.previous_plan_counts
        day_state.previous_plan_timing = result.previous_plan_timing
        day_state.previous_plan_funnel_diagnostics = result.previous_plan_funnel_diagnostics
        self._pending_buy_queue = result.pending_buy_queue
        self._pending_sell_queue = result.pending_sell_queue

    def _append_pipeline_mode_daily_state(
        self,
        *,
        day_context: PipelineDayContext,
        day_state: PipelineModeDayState,
    ) -> dict[str, float]:
        self._portfolio.refresh_position_lifecycle(day_context.current_prices, day_context.trade_date_compact)
        current_prices = self._hydrate_position_prices(
            day_context.current_prices,
            day_context.previous_date_str,
            day_context.current_date_str,
        )
        agent_output = self._build_pipeline_agent_output(day_state.decisions, day_context.active_tickers)
        stage_started_at = perf_counter()
        self._append_daily_state(
            current_date=day_context.current_date,
            current_date_str=day_context.current_date_str,
            active_tickers=day_context.active_tickers,
            agent_output=agent_output,
            executed_trades=day_state.executed_trades,
            current_prices=current_prices,
        )
        day_state.append_daily_state_seconds = perf_counter() - stage_started_at
        return current_prices

    def _run_pipeline_mode_post_market(
        self,
        *,
        day_context: PipelineDayContext,
        pending_plan: ExecutionPlan | None,
        day_state: PipelineModeDayState,
    ) -> ExecutionPlan | None:
        if self._pipeline is None:
            return pending_plan
        stage_started_at = perf_counter()
        next_pending_plan = self._pipeline.run_post_market(
            day_context.trade_date_compact,
            self._portfolio.get_snapshot(),
            blocked_buy_tickers=self._get_active_exit_reentry_cooldowns(day_context.trade_date_compact),
        )
        next_pending_plan.pending_buy_queue = list(self._pending_buy_queue)
        next_pending_plan.pending_sell_queue = list(self._pending_sell_queue)
        self._write_selection_artifacts(next_pending_plan, day_context.trade_date_compact)
        day_state.post_market_seconds = perf_counter() - stage_started_at
        return next_pending_plan

    def _record_pipeline_mode_day(
        self,
        *,
        day_context: PipelineDayContext,
        day_state: PipelineModeDayState,
        pending_plan: ExecutionPlan | None,
        current_prices: dict[str, float],
        day_started_at: float,
    ) -> None:
        execution_plan_observations = self._collect_pipeline_day_observations(day_context.trade_date_compact)
        timing_payload, event_payload = self._build_pipeline_day_record_payloads(
            day_context=day_context,
            day_state=day_state,
            pending_plan=pending_plan,
            current_prices=current_prices,
            day_started_at=day_started_at,
            execution_plan_observations=execution_plan_observations,
        )
        self._emit_pipeline_day_records(timing_payload=timing_payload, event_payload=event_payload)

    def _build_pipeline_day_record_payloads(
        self,
        *,
        day_context: PipelineDayContext,
        day_state: PipelineModeDayState,
        pending_plan: ExecutionPlan | None,
        current_prices: dict[str, float],
        day_started_at: float,
        execution_plan_observations: list[dict],
    ) -> tuple[dict, dict]:
        return build_pipeline_day_record_payloads_helper(
            day_context=day_context,
            day_state=day_state,
            pending_plan=pending_plan,
            current_prices=current_prices,
            day_started_at=day_started_at,
            execution_plan_observations=execution_plan_observations,
            pending_buy_queue=self._pending_buy_queue,
            pending_sell_queue=self._pending_sell_queue,
            portfolio_snapshot=self._portfolio.get_snapshot(),
            exit_reentry_cooldowns=self._exit_reentry_cooldowns,
            timing_payload_builder=build_pipeline_timing_payload,
            event_payload_builder=build_pipeline_event_payload,
        )

    def _collect_pipeline_day_observations(self, trade_date_compact: str) -> list[dict]:
        if self._pipeline is None:
            return []
        return collect_execution_plan_observations(self._pipeline, trade_date_compact)

    def _emit_pipeline_day_records(self, *, timing_payload: dict, event_payload: dict) -> None:
        self._append_timing_log(timing_payload)
        self._append_pipeline_event(event_payload)

    def run_backtest(self) -> PerformanceMetrics:
        self._prefetch_with_timing_log()
        dates, pending_plan = self._prepare_run_dates_and_plan()
        metrics = self._run_selected_backtest_mode(dates, pending_plan)
        self._clear_checkpoint()
        return metrics

    def _prefetch_with_timing_log(self) -> None:
        prefetch_started_at = perf_counter()
        self._prefetch_data()
        self._append_timing_log(
            {
                "event": "prefetch_complete",
                "start_date": self._start_date,
                "end_date": self._end_date,
                "ticker_count": len(self._tickers),
                "timing_seconds": {"prefetch": round(perf_counter() - prefetch_started_at, 3)},
            }
        )

    def _prepare_run_dates_and_plan(self) -> tuple[pd.DatetimeIndex, ExecutionPlan | None]:
        dates = self._iter_backtest_dates()
        last_processed_date, pending_plan = self._load_checkpoint()
        if last_processed_date is not None:
            dates = pd.DatetimeIndex([date for date in dates if date.strftime("%Y-%m-%d") > last_processed_date])
        elif len(dates) > 0:
            self._portfolio_values = [{"Date": dates[0], "Portfolio Value": self._initial_capital}]
        else:
            self._portfolio_values = []
        return dates, pending_plan

    def _run_selected_backtest_mode(
        self,
        dates: pd.DatetimeIndex,
        pending_plan: ExecutionPlan | None,
    ) -> PerformanceMetrics:
        if self._backtest_mode == "pipeline":
            return self._run_pipeline_mode(dates, pending_plan=pending_plan)
        return self._run_agent_mode(dates)

    def get_portfolio_values(self) -> Sequence[PortfolioValuePoint]:
        return list(self._portfolio_values)

    def get_portfolio_snapshot(self) -> dict:
        return self._portfolio.get_snapshot()
