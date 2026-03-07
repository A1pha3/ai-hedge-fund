from __future__ import annotations

from datetime import datetime
from typing import Dict, Sequence

import pandas as pd
from dateutil.relativedelta import relativedelta

from src.execution.daily_pipeline import DailyPipeline
from src.execution.models import ExecutionPlan
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
        self._pipeline = pipeline or (DailyPipeline() if backtest_mode == "pipeline" else None)

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

    def _run_pipeline_mode(self, dates: pd.DatetimeIndex) -> PerformanceMetrics:
        pending_plan: ExecutionPlan | None = None

        for current_date in dates:
            current_date_str = current_date.strftime("%Y-%m-%d")
            trade_date_compact = current_date.strftime("%Y%m%d")
            previous_date_str = (current_date - relativedelta(days=1)).strftime("%Y-%m-%d")

            active_ticker_set = set(self._tickers)
            active_ticker_set.update(self._portfolio.get_positions().keys())
            if pending_plan is not None:
                active_ticker_set.update(order.ticker for order in pending_plan.buy_orders)
                active_ticker_set.update(order.ticker for order in pending_plan.sell_orders)
            active_tickers = sorted(active_ticker_set)

            current_prices = self._load_current_prices(active_tickers, previous_date_str, current_date_str)
            if current_prices is None:
                continue
            daily_turnovers = self._get_daily_turnovers(active_tickers, previous_date_str, current_date_str)
            limit_up, limit_down = self._get_limit_state(trade_date_compact)

            decisions: Dict[str, dict] = {}
            executed_trades: Dict[str, int] = {ticker: 0 for ticker in active_tickers}

            if pending_plan is not None and self._pipeline is not None:
                prepared_plan = self._pipeline.run_pre_market(pending_plan, trade_date_compact)
                confirmation_inputs = self._build_confirmation_inputs(prepared_plan, current_prices)
                confirmed_orders, exits, crisis_response = self._pipeline.run_intraday(
                    prepared_plan,
                    trade_date_compact,
                    confirmation_inputs=confirmation_inputs,
                    crisis_inputs={"drawdown_pct": 0.0},
                )

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

            agent_output = self._build_pipeline_agent_output(decisions, active_tickers)
            self._append_daily_state(
                current_date=current_date,
                current_date_str=current_date_str,
                active_tickers=active_tickers,
                agent_output=agent_output,
                executed_trades=executed_trades,
                current_prices=current_prices,
            )

            if self._pipeline is not None:
                pending_plan = self._pipeline.run_post_market(trade_date_compact, self._portfolio.get_snapshot())

        return self._performance_metrics

    def run_backtest(self) -> PerformanceMetrics:
        self._prefetch_data()

        dates = self._iter_backtest_dates()
        if len(dates) > 0:
            self._portfolio_values = [{"Date": dates[0], "Portfolio Value": self._initial_capital}]
        else:
            self._portfolio_values = []

        if self._backtest_mode == "pipeline":
            return self._run_pipeline_mode(dates)
        return self._run_agent_mode(dates)

    def get_portfolio_values(self) -> Sequence[PortfolioValuePoint]:
        return list(self._portfolio_values)
