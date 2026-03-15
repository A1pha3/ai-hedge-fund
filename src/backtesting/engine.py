from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Callable, Dict, Sequence

import pandas as pd
from dateutil.relativedelta import relativedelta

from src.execution.daily_pipeline import DailyPipeline
from src.execution.models import ExecutionPlan, PendingOrder
from src.portfolio.limit_handler import process_pending_buy, process_pending_sell, queue_pending_buy, queue_pending_sell
from src.tools.tushare_api import get_limit_list
from src.tools.api import (
    get_company_news,
    get_financial_metrics,
    get_insider_trades,
    get_price_data,
    get_prices,
)

from .benchmarks import BenchmarkCalculator
from .controller import AgentController
from .metrics import PerformanceMetricsCalculator
from .output import OutputBuilder
from .portfolio import Portfolio
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

    def _serialize_portfolio_values(self) -> list[dict]:
        serialized: list[dict] = []
        for point in self._portfolio_values:
            payload = dict(point)
            date_value = payload.get("Date")
            if isinstance(date_value, datetime):
                payload["Date"] = date_value.strftime("%Y-%m-%d")
            serialized.append(payload)
        return serialized

    def _save_checkpoint(self, last_processed_date: str, pending_plan: ExecutionPlan | None = None) -> None:
        if self._checkpoint_path is None:
            return

        payload = {
            "last_processed_date": last_processed_date,
            "portfolio_snapshot": self._portfolio.get_snapshot(),
            "portfolio_values": self._serialize_portfolio_values(),
            "performance_metrics": dict(self._performance_metrics),
            "pending_buy_queue": [order.model_dump() for order in self._pending_buy_queue],
            "pending_sell_queue": [order.model_dump() for order in self._pending_sell_queue],
            "pending_plan": pending_plan.model_dump() if pending_plan is not None else None,
        }
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def _load_checkpoint(self) -> tuple[str | None, ExecutionPlan | None]:
        if self._checkpoint_path is None or not self._checkpoint_path.exists():
            return None, None

        payload = json.loads(self._checkpoint_path.read_text(encoding="utf-8"))
        self._portfolio.load_snapshot(payload["portfolio_snapshot"])
        self._portfolio_values = []
        for item in payload.get("portfolio_values", []):
            restored = dict(item)
            date_value = restored.get("Date")
            if isinstance(date_value, str) and date_value:
                restored["Date"] = datetime.strptime(date_value, "%Y-%m-%d")
            self._portfolio_values.append(restored)
        self._performance_metrics.update(payload.get("performance_metrics", {}))
        self._pending_buy_queue = [PendingOrder.model_validate(item) for item in payload.get("pending_buy_queue", [])]
        self._pending_sell_queue = [PendingOrder.model_validate(item) for item in payload.get("pending_sell_queue", [])]
        pending_plan_payload = payload.get("pending_plan")
        pending_plan = ExecutionPlan.model_validate(pending_plan_payload) if pending_plan_payload else None
        return payload.get("last_processed_date"), pending_plan

    def _clear_checkpoint(self) -> None:
        if self._checkpoint_path is not None and self._checkpoint_path.exists():
            self._checkpoint_path.unlink()

    def _prefetch_data(self) -> None:
        end_date_dt = datetime.strptime(self._end_date, "%Y-%m-%d")
        start_date_dt = end_date_dt - relativedelta(years=1)
        start_date_str = start_date_dt.strftime("%Y-%m-%d")

        for ticker in self._tickers:
            get_prices(ticker, start_date_str, self._end_date)
            get_financial_metrics(ticker, self._end_date, limit=10)
            get_insider_trades(ticker, self._end_date, start_date=self._start_date, limit=1000)
            get_company_news(ticker, self._end_date, start_date=self._start_date, limit=1000)

        # Preload data for SPY for benchmark comparison
        get_prices("SPY", self._start_date, self._end_date)

    def _iter_backtest_dates(self) -> pd.DatetimeIndex:
        return pd.date_range(self._start_date, self._end_date, freq="B")

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        return str(ticker).split(".")[0].upper()

    def _get_limit_state(self, trade_date_compact: str) -> tuple[set[str], set[str]]:
        limit_df = get_limit_list(trade_date_compact)
        if limit_df is None or limit_df.empty:
            return set(), set()
        limit_up = {
            self._normalize_ticker(ts_code)
            for ts_code in limit_df.loc[limit_df["limit"] == "U", "ts_code"].tolist()
        }
        limit_down = {
            self._normalize_ticker(ts_code)
            for ts_code in limit_df.loc[limit_df["limit"] == "D", "ts_code"].tolist()
        }
        return limit_up, limit_down

    def _get_daily_turnovers(self, active_tickers: Sequence[str], previous_date_str: str, current_date_str: str) -> Dict[str, float]:
        turnovers: Dict[str, float] = {}
        for ticker in active_tickers:
            try:
                price_data = get_price_data(ticker, previous_date_str, current_date_str)
                if price_data.empty:
                    continue
                row = price_data.iloc[-1]
                turnovers[ticker] = float(row.get("close", 0.0)) * float(row.get("volume", 0.0))
            except Exception:
                continue
        return turnovers

    def _load_current_prices(self, tickers: Sequence[str], previous_date_str: str, current_date_str: str) -> Dict[str, float] | None:
        current_prices: Dict[str, float] = {}
        for ticker in tickers:
            try:
                price_data = get_price_data(ticker, previous_date_str, current_date_str)
                if price_data.empty:
                    return None
                current_prices[ticker] = float(price_data.iloc[-1]["close"])
            except Exception:
                return None
        return current_prices

    def _append_daily_state(
        self,
        *,
        current_date,
        current_date_str: str,
        active_tickers: Sequence[str],
        agent_output: AgentOutput,
        executed_trades: Dict[str, int],
        current_prices: Dict[str, float],
    ) -> None:
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
        self._portfolio_values.append(point)

        rows = self._results.build_day_rows(
            date_str=current_date_str,
            tickers=active_tickers,
            agent_output=agent_output,
            executed_trades=executed_trades,
            current_prices=current_prices,
            portfolio=self._portfolio,
            performance_metrics=self._performance_metrics,
            total_value=total_value,
            benchmark_return_pct=self._benchmark.get_return_pct("SPY", self._start_date, current_date_str),
        )
        self._table_rows = rows + self._table_rows
        self._results.print_rows(self._table_rows)

        if len(self._portfolio_values) > 3:
            computed = self._perf.compute_metrics(self._portfolio_values)
            if computed:
                self._performance_metrics.update(computed)

    def _run_agent_mode(self, dates: pd.DatetimeIndex) -> PerformanceMetrics:
        for current_date in dates:
            lookback_start = (current_date - relativedelta(months=1)).strftime("%Y-%m-%d")
            current_date_str = current_date.strftime("%Y-%m-%d")
            previous_date_str = (current_date - relativedelta(days=1)).strftime("%Y-%m-%d")
            if lookback_start == current_date_str:
                continue

            current_prices = self._load_current_prices(self._tickers, previous_date_str, current_date_str)
            if current_prices is None:
                continue

            agent_output = self._agent_controller.run_agent(
                self._agent,
                tickers=self._tickers,
                start_date=lookback_start,
                end_date=current_date_str,
                portfolio=self._portfolio,
                model_name=self._model_name,
                model_provider=self._model_provider,
                selected_analysts=self._selected_analysts,
            )
            decisions = agent_output["decisions"]

            executed_trades: Dict[str, int] = {}
            for ticker in self._tickers:
                d = decisions.get(ticker, {"action": "hold", "quantity": 0})
                action = d.get("action", "hold")
                qty = d.get("quantity", 0)
                executed_qty = self._executor.execute_trade(ticker, action, qty, current_prices[ticker], self._portfolio)
                executed_trades[ticker] = executed_qty

            self._append_daily_state(
                current_date=current_date,
                current_date_str=current_date_str,
                active_tickers=self._tickers,
                agent_output=agent_output,
                executed_trades=executed_trades,
                current_prices=current_prices,
            )

        return self._performance_metrics

    def _build_confirmation_inputs(self, plan: ExecutionPlan, current_prices: Dict[str, float]) -> Dict[str, dict]:
        confirmation_inputs: Dict[str, dict] = {}
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

    def _build_pipeline_agent_output(self, decisions: Dict[str, dict], active_tickers: Sequence[str]) -> AgentOutput:
        normalized = {
            ticker: decisions.get(ticker, {"action": "hold", "quantity": 0})
            for ticker in active_tickers
        }
        return {"decisions": normalized, "analyst_signals": {}}

    @staticmethod
    def _dedupe_pending_orders(orders: Sequence[PendingOrder]) -> list[PendingOrder]:
        by_key: dict[tuple[str, str], PendingOrder] = {}
        for order in orders:
            by_key[(order.ticker, order.order_type)] = order
        return list(by_key.values())

    def _process_pending_queues(
        self,
        *,
        prepared_plan: ExecutionPlan,
        trade_date_compact: str,
        current_prices: Dict[str, float],
        limit_up: set[str],
        limit_down: set[str],
        decisions: Dict[str, dict],
    ) -> tuple[list[PendingOrder], list[PendingOrder], list[str]]:
        next_pending_buy: list[PendingOrder] = []
        next_pending_sell: list[PendingOrder] = []
        alerts: list[str] = []
        watch_scores = {item.ticker: item.score_final for item in prepared_plan.watchlist}

        for order in self._pending_buy_queue:
            normalized_ticker = self._normalize_ticker(order.ticker)
            price = current_prices.get(order.ticker)
            if price is None:
                next_pending_buy.append(order)
                continue
            result = process_pending_buy(
                order,
                current_score=watch_scores.get(order.ticker, order.original_score),
                is_limit_up=normalized_ticker in limit_up,
                opened_board=normalized_ticker not in limit_up,
                current_price=price,
                reference_close=price,
            )
            if result["action"] == "execute" and order.shares > 0:
                existing_qty = int(decisions.get(order.ticker, {}).get("quantity", 0))
                decisions[order.ticker] = {"action": "buy", "quantity": max(existing_qty, order.shares)}
                alerts.append(f"pending_buy_execute:{order.ticker}")
            elif result["action"] == "keep":
                next_pending_buy.append(order.model_copy(update={"queue_days": int(result["queue_days"])}))
            elif result["action"] == "remove":
                alerts.append(f"pending_buy_remove:{order.ticker}:{result['reason']}")

        for order in self._pending_sell_queue:
            normalized_ticker = self._normalize_ticker(order.ticker)
            result = process_pending_sell(order, is_limit_down=normalized_ticker in limit_down)
            if result["action"] == "execute" and order.shares > 0:
                existing_qty = int(decisions.get(order.ticker, {}).get("quantity", 0))
                decisions[order.ticker] = {"action": "sell", "quantity": max(existing_qty, order.shares)}
                alerts.append(f"pending_sell_execute:{order.ticker}")
            elif result["action"] == "keep":
                next_pending_sell.append(order.model_copy(update={"queue_days": int(result["queue_days"])}))
            elif result["action"] == "risk_reduce_others":
                next_pending_sell.append(order.model_copy(update={"queue_days": int(result["queue_days"])}))
                alerts.append(f"pending_sell_risk_reduce:{order.ticker}")

        return self._dedupe_pending_orders(next_pending_buy), self._dedupe_pending_orders(next_pending_sell), alerts

    def _run_pipeline_mode(self, dates: pd.DatetimeIndex, pending_plan: ExecutionPlan | None = None) -> PerformanceMetrics:

        for current_date in dates:
            day_started_at = perf_counter()
            current_date_str = current_date.strftime("%Y-%m-%d")
            trade_date_compact = current_date.strftime("%Y%m%d")
            previous_date_str = (current_date - relativedelta(days=1)).strftime("%Y-%m-%d")

            active_ticker_set = set(self._tickers)
            active_ticker_set.update(self._portfolio.get_positions().keys())
            if pending_plan is not None:
                active_ticker_set.update(order.ticker for order in pending_plan.buy_orders)
                active_ticker_set.update(order.ticker for order in pending_plan.sell_orders)
            active_tickers = sorted(active_ticker_set)

            stage_started_at = perf_counter()
            current_prices = self._load_current_prices(active_tickers, previous_date_str, current_date_str)
            if current_prices is None:
                continue
            daily_turnovers = self._get_daily_turnovers(active_tickers, previous_date_str, current_date_str)
            limit_up, limit_down = self._get_limit_state(trade_date_compact)
            load_market_data_seconds = perf_counter() - stage_started_at

            decisions: Dict[str, dict] = {}
            executed_trades: Dict[str, int] = {ticker: 0 for ticker in active_tickers}
            pre_market_seconds = 0.0
            intraday_seconds = 0.0
            append_daily_state_seconds = 0.0
            post_market_seconds = 0.0
            previous_plan_counts: dict[str, int] = {}
            previous_plan_timing: dict[str, float] = {}
            previous_plan_funnel_diagnostics: dict = {}
            prepared_plan: ExecutionPlan | None = None

            if pending_plan is not None and self._pipeline is not None:
                stage_started_at = perf_counter()
                prepared_plan = self._pipeline.run_pre_market(pending_plan, trade_date_compact)
                pre_market_seconds = perf_counter() - stage_started_at

                previous_plan_counts = dict((pending_plan.risk_metrics or {}).get("counts", {}))
                previous_plan_timing = dict((pending_plan.risk_metrics or {}).get("timing_seconds", {}))
                previous_plan_funnel_diagnostics = dict((pending_plan.risk_metrics or {}).get("funnel_diagnostics", {}))

                stage_started_at = perf_counter()
                confirmation_inputs = self._build_confirmation_inputs(prepared_plan, current_prices)
                next_pending_buy, next_pending_sell, queue_alerts = self._process_pending_queues(
                    prepared_plan=prepared_plan,
                    trade_date_compact=trade_date_compact,
                    current_prices=current_prices,
                    limit_up=limit_up,
                    limit_down=limit_down,
                    decisions=decisions,
                )
                confirmed_orders, exits, crisis_response = self._pipeline.run_intraday(
                    prepared_plan,
                    trade_date_compact,
                    confirmation_inputs=confirmation_inputs,
                    crisis_inputs={"drawdown_pct": 0.0},
                )
                intraday_seconds = perf_counter() - stage_started_at

                if crisis_response.get("pause_new_buys"):
                    confirmed_orders = []

                for order in confirmed_orders:
                    self._portfolio.ensure_ticker(order.ticker)
                    decisions[order.ticker] = {"action": "buy", "quantity": order.shares}

                for exit_signal in exits:
                    self._portfolio.ensure_ticker(exit_signal.ticker)
                    long_shares = self._portfolio.get_positions()[exit_signal.ticker]["long"]
                    sell_quantity = int(long_shares * exit_signal.sell_ratio)
                    if sell_quantity > 0:
                        decisions[exit_signal.ticker] = {"action": "sell", "quantity": sell_quantity}

                reduce_ratio = float(crisis_response.get("forced_reduce_ratio", 0.0) or 0.0)
                if reduce_ratio > 0:
                    for ticker, position in self._portfolio.get_positions().items():
                        if position["long"] <= 0:
                            continue
                        sell_quantity = int(position["long"] * reduce_ratio)
                        if sell_quantity <= 0:
                            continue
                        decisions[ticker] = {"action": "sell", "quantity": max(sell_quantity, decisions.get(ticker, {}).get("quantity", 0))}

                for ticker, decision in decisions.items():
                    price = current_prices.get(ticker)
                    if price is None:
                        continue
                    normalized_ticker = self._normalize_ticker(ticker)
                    if decision["action"] == "buy" and normalized_ticker in limit_up:
                        matching_order = next((order for order in prepared_plan.buy_orders if order.ticker == ticker), None)
                        next_pending_buy.append(
                            queue_pending_buy(
                                ticker,
                                original_score=matching_order.score_final if matching_order is not None else 0.0,
                                queue_date=trade_date_compact,
                                shares=int(decision["quantity"]),
                                amount=matching_order.amount if matching_order is not None else 0.0,
                            )
                        )
                        executed_trades[ticker] = 0
                        continue
                    if decision["action"] == "sell" and normalized_ticker in limit_down:
                        long_shares = self._portfolio.get_positions().get(ticker, {}).get("long", 0)
                        sell_ratio = (int(decision["quantity"]) / long_shares) if long_shares else 1.0
                        next_pending_sell.append(
                            queue_pending_sell(
                                ticker,
                                original_score=-1.0,
                                queue_date=trade_date_compact,
                                shares=int(decision["quantity"]),
                                sell_ratio=sell_ratio,
                            )
                        )
                        executed_trades[ticker] = 0
                        continue
                    executed_qty = self._executor.execute_trade(
                        ticker,
                        decision["action"],
                        decision["quantity"],
                        price,
                        self._portfolio,
                        is_limit_up=normalized_ticker in limit_up,
                        is_limit_down=normalized_ticker in limit_down,
                        daily_turnover=daily_turnovers.get(ticker),
                    )
                    executed_trades[ticker] = executed_qty
                prepared_plan.risk_alerts.extend(queue_alerts)
                self._pending_buy_queue = self._dedupe_pending_orders(next_pending_buy)
                self._pending_sell_queue = self._dedupe_pending_orders(next_pending_sell)

            agent_output = self._build_pipeline_agent_output(decisions, active_tickers)
            stage_started_at = perf_counter()
            self._append_daily_state(
                current_date=current_date,
                current_date_str=current_date_str,
                active_tickers=active_tickers,
                agent_output=agent_output,
                executed_trades=executed_trades,
                current_prices=current_prices,
            )
            append_daily_state_seconds = perf_counter() - stage_started_at

            if self._pipeline is not None:
                stage_started_at = perf_counter()
                pending_plan = self._pipeline.run_post_market(trade_date_compact, self._portfolio.get_snapshot())
                pending_plan.pending_buy_queue = list(self._pending_buy_queue)
                pending_plan.pending_sell_queue = list(self._pending_sell_queue)
                post_market_seconds = perf_counter() - stage_started_at

            executed_order_count = sum(1 for quantity in executed_trades.values() if quantity)
            timing_payload = {
                "event": "pipeline_day_timing",
                "trade_date": trade_date_compact,
                "active_ticker_count": len(active_tickers),
                "pending_buy_queue_count": len(self._pending_buy_queue),
                "pending_sell_queue_count": len(self._pending_sell_queue),
                "executed_order_count": executed_order_count,
                "timing_seconds": {
                    "load_market_data": round(load_market_data_seconds, 3),
                    "pre_market": round(pre_market_seconds, 3),
                    "intraday": round(intraday_seconds, 3),
                    "append_daily_state": round(append_daily_state_seconds, 3),
                    "post_market": round(post_market_seconds, 3),
                    "total_day": round(perf_counter() - day_started_at, 3),
                },
                "current_plan": {
                    "counts": dict((pending_plan.risk_metrics or {}).get("counts", {})) if pending_plan is not None else {},
                    "timing_seconds": dict((pending_plan.risk_metrics or {}).get("timing_seconds", {})) if pending_plan is not None else {},
                    "funnel_diagnostics": dict((pending_plan.risk_metrics or {}).get("funnel_diagnostics", {})) if pending_plan is not None else {},
                },
                "previous_plan": {
                    "counts": previous_plan_counts,
                    "timing_seconds": previous_plan_timing,
                    "funnel_diagnostics": previous_plan_funnel_diagnostics,
                },
            }
            self._append_timing_log(timing_payload)
            self._append_pipeline_event(
                {
                    "event": "paper_trading_day",
                    "trade_date": trade_date_compact,
                    "active_tickers": list(active_tickers),
                    "executed_trades": dict(executed_trades),
                    "decisions": dict(decisions),
                    "current_prices": {ticker: float(price) for ticker, price in current_prices.items()},
                    "portfolio_snapshot": self._portfolio.get_snapshot(),
                    "pending_buy_queue": [order.model_dump() for order in self._pending_buy_queue],
                    "pending_sell_queue": [order.model_dump() for order in self._pending_sell_queue],
                    "prepared_plan": prepared_plan.model_dump() if prepared_plan is not None else None,
                    "current_plan": pending_plan.model_dump() if pending_plan is not None else None,
                    "timing_seconds": timing_payload["timing_seconds"],
                }
            )

            self._save_checkpoint(current_date_str, pending_plan)

        return self._performance_metrics

    def run_backtest(self) -> PerformanceMetrics:
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

        dates = self._iter_backtest_dates()
        last_processed_date, pending_plan = self._load_checkpoint()
        if last_processed_date is not None:
            dates = pd.DatetimeIndex([date for date in dates if date.strftime("%Y-%m-%d") > last_processed_date])
        elif len(dates) > 0:
            self._portfolio_values = [{"Date": dates[0], "Portfolio Value": self._initial_capital}]
        else:
            self._portfolio_values = []

        if self._backtest_mode == "pipeline":
            metrics = self._run_pipeline_mode(dates, pending_plan=pending_plan)
        else:
            metrics = self._run_agent_mode(dates)

        self._clear_checkpoint()
        return metrics

    def get_portfolio_values(self) -> Sequence[PortfolioValuePoint]:
        return list(self._portfolio_values)

    def get_portfolio_snapshot(self) -> dict:
        return self._portfolio.get_snapshot()
