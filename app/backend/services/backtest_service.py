import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from app.backend.services.backtest_result_builder import (
    append_portfolio_snapshot,
    build_backtest_day_result,
    calculate_exposures,
    create_performance_metrics,
)
from app.backend.services.backtest_trade_helpers import (
    execute_buy_trade,
    execute_cover_trade,
    execute_sell_trade,
    execute_short_trade,
    normalize_trade_quantity,
)
from app.backend.services.graph import parse_hedge_fund_response, run_graph_async
from app.backend.services.portfolio import create_portfolio
from src.llm.defaults import get_default_model_config
from src.tools.api import (
    get_company_news,
    get_financial_metrics,
    get_insider_trades,
    get_price_data,
    get_prices,
)

logger = logging.getLogger(__name__)


class BacktestService:
    """
    Core backtesting service that focuses purely on backtesting logic.
    Uses a pre-compiled graph and portfolio for trading decisions.
    """

    def __init__(
        self,
        graph: Any,
        portfolio: dict[str, Any],
        tickers: list[str],
        start_date: str,
        end_date: str,
        initial_capital: float,
        model_name: str | None = None,
        model_provider: str | None = None,
        request: Any | None = None,
    ) -> None:
        self.graph = graph
        self.portfolio = portfolio
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        resolved_model_name, resolved_model_provider = (model_name, model_provider) if model_name and model_provider else get_default_model_config()
        self.model_name = resolved_model_name
        self.model_provider = resolved_model_provider
        self.request = request
        self.portfolio_values: list[dict[str, Any]] = []
        self.performance_metrics: dict[str, Any] = create_performance_metrics()

    def execute_trade(self, ticker: str, action: str, quantity: float, current_price: float) -> int:
        """Execute trades with support for both long and short positions."""
        normalized_quantity = normalize_trade_quantity(quantity)
        if normalized_quantity <= 0:
            return 0

        if action == "buy":
            return execute_buy_trade(self.portfolio, ticker, normalized_quantity, current_price)
        if action == "sell":
            return execute_sell_trade(self.portfolio, ticker, normalized_quantity, current_price)
        if action == "short":
            return execute_short_trade(self.portfolio, ticker, normalized_quantity, current_price)
        if action == "cover":
            return execute_cover_trade(self.portfolio, ticker, normalized_quantity, current_price)
        return 0

    def calculate_portfolio_value(self, current_prices: dict[str, float]) -> float:
        """Calculate total portfolio value.

        Includes cash, net position value, and margin_used (which is cash
        locked as collateral for open short positions and excluded from the
        cash balance).  Consistent with ``_calculate_total_portfolio_value``
        in ``risk_manager_helpers``.

        Tickers missing from ``current_prices`` are skipped (their position
        value is not included), which handles the case where some price
        fetches failed while others succeeded.
        """
        total_value = self.portfolio["cash"]
        for ticker in self.tickers:
            price = current_prices.get(ticker)
            if price is None:
                continue
            position = self.portfolio["positions"][ticker]
            total_value += position["long"] * price
            total_value -= position["short"] * price
        total_value += float(self.portfolio.get("margin_used", 0.0))
        return total_value

    def prefetch_data(self) -> None:
        """Pre-fetch all data needed for the backtest period."""
        end_date_dt = datetime.strptime(self.end_date, "%Y-%m-%d")
        start_date_dt = end_date_dt - relativedelta(years=1)
        start_date_str = start_date_dt.strftime("%Y-%m-%d")
        api_keys = getattr(self.request, "api_keys", None) or {}
        api_key = api_keys.get("FINANCIAL_DATASETS_API_KEY")

        for ticker in self.tickers:
            get_prices(ticker, start_date_str, self.end_date, api_key=api_key)
            get_financial_metrics(ticker, self.end_date, limit=10, api_key=api_key)
            get_insider_trades(ticker, self.end_date, start_date=self.start_date, limit=1000, api_key=api_key)
            get_company_news(ticker, self.end_date, start_date=self.start_date, limit=1000, api_key=api_key)

    def _update_performance_metrics(self, performance_metrics: dict[str, Any]) -> None:
        """Update performance metrics using daily returns."""
        values_df = pd.DataFrame(self.portfolio_values).set_index("Date")
        values_df["Daily Return"] = values_df["Portfolio Value"].pct_change()
        clean_returns = values_df["Daily Return"].dropna()

        if len(clean_returns) < 2:
            return

        daily_risk_free_rate = 0.0434 / 252
        excess_returns = clean_returns - daily_risk_free_rate
        mean_excess_return = excess_returns.mean()
        std_excess_return = excess_returns.std()

        performance_metrics["sharpe_ratio"] = np.sqrt(252) * (mean_excess_return / std_excess_return) if std_excess_return > 1e-12 else 0.0

        negative_returns = excess_returns[excess_returns < 0]
        if len(negative_returns) > 0:
            downside_std = negative_returns.std()
            performance_metrics["sortino_ratio"] = np.sqrt(252) * (mean_excess_return / downside_std) if downside_std > 1e-12 else (None if mean_excess_return > 0 else 0)
        else:
            performance_metrics["sortino_ratio"] = None if mean_excess_return > 0 else 0

        rolling_max = values_df["Portfolio Value"].cummax()
        drawdown = (values_df["Portfolio Value"] - rolling_max) / rolling_max
        if len(drawdown) == 0:
            performance_metrics["max_drawdown"] = 0.0
            performance_metrics["max_drawdown_date"] = None
            return

        min_drawdown = drawdown.min()
        performance_metrics["max_drawdown"] = min_drawdown * 100
        performance_metrics["max_drawdown_date"] = drawdown.idxmin().strftime("%Y-%m-%d") if min_drawdown < 0 else None

    def _publish_progress(self, progress_callback: Callable[[dict[str, Any]], None] | None, current_date_str: str, current_step: int, total_dates: int) -> None:
        if progress_callback is None:
            return

        progress_callback(
            {
                "type": "progress",
                "current_date": current_date_str,
                "progress": current_step / total_dates,
                "total_dates": total_dates,
                "current_step": current_step,
            }
        )

    def _get_current_prices(self, previous_date_str: str, current_date_str: str) -> dict[str, float] | None:
        current_prices: dict[str, float] = {}

        for ticker in self.tickers:
            try:
                price_data = get_price_data(ticker, previous_date_str, current_date_str)
            except Exception:
                continue

            if price_data.empty:
                continue

            current_prices[ticker] = price_data.iloc[-1]["close"]

        return current_prices if current_prices else None

    def _create_portfolio_for_graph(self) -> dict[str, Any]:
        portfolio_for_graph = create_portfolio(
            initial_cash=self.portfolio["cash"],
            margin_requirement=self.portfolio["margin_requirement"],
            tickers=self.tickers,
            portfolio_positions=[],
        )
        portfolio_for_graph.update(self.portfolio)
        return portfolio_for_graph

    async def _run_graph_for_date(self, lookback_start: str, current_date_str: str, run_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            result = await run_graph_async(
                graph=self.graph,
                portfolio=self._create_portfolio_for_graph(),
                tickers=self.tickers,
                start_date=lookback_start,
                end_date=current_date_str,
                model_name=self.model_name,
                model_provider=self.model_provider,
                request=self.request,
                run_id=run_id,
            )
        except Exception as error:
            logger.warning("Error running graph for %s: %s", current_date_str, error, exc_info=True)
            return {}, {}

        if not result or not result.get("messages"):
            return {}, {}

        return parse_hedge_fund_response(result["messages"][-1].content), result.get("data", {}).get("analyst_signals", {})

    def _execute_daily_decisions(self, decisions: dict[str, Any], current_prices: dict[str, float]) -> dict[str, int]:
        executed_trades: dict[str, int] = {}

        for ticker in self.tickers:
            price = current_prices.get(ticker)
            if price is None:
                executed_trades[ticker] = 0
                continue
            decision = decisions.get(ticker, {"action": "hold", "quantity": 0})
            executed_trades[ticker] = self.execute_trade(
                ticker=ticker,
                action=decision.get("action", "hold"),
                quantity=decision.get("quantity", 0),
                current_price=price,
            )

        return executed_trades

    def _finalize_backtest(self, backtest_results: list[dict[str, Any]], performance_metrics: dict[str, Any]) -> dict[str, Any]:
        if len(self.portfolio_values) > 1:
            self._update_performance_metrics(performance_metrics)

        if backtest_results:
            final_result = backtest_results[-1]
            performance_metrics["gross_exposure"] = final_result["gross_exposure"]
            performance_metrics["net_exposure"] = final_result["net_exposure"]
            performance_metrics["long_short_ratio"] = final_result["long_short_ratio"]

        self.performance_metrics = performance_metrics
        return {
            "results": backtest_results,
            "performance_metrics": performance_metrics,
            "portfolio_values": self.portfolio_values,
            "final_portfolio": self.portfolio,
        }

    async def run_backtest_async(self, progress_callback: Callable[[dict[str, Any]], None] | None = None, run_id: str | None = None) -> dict[str, Any]:
        """
        Run the backtest asynchronously with optional progress callbacks.
        Uses the pre-compiled graph for trading decisions.
        """
        self.prefetch_data()

        dates = pd.date_range(self.start_date, self.end_date, freq="B")
        performance_metrics = create_performance_metrics()
        # Seed the initial-capital anchor at the calendar day BEFORE the first
        # backtest bar; the run loop appends a real post-trade snapshot for
        # every date (including dates[0]). Seeding at dates[0] itself produced a
        # duplicate Date index (phantom intra-day pct_change, non-unique index
        # for max_drawdown_date / frontend rendering). Anchoring one day earlier
        # keeps iloc[0] == initial_capital (total_return unchanged) with a unique
        # Date index. Mirrors src/backtesting/engine.py _prepare_run_dates_and_plan
        # (BH-001 drain).
        if len(dates) > 0:
            self.portfolio_values = [
                {"Date": dates[0] - pd.Timedelta(days=1), "Portfolio Value": self.initial_capital}
            ]
        else:
            self.portfolio_values = []
        backtest_results: list[dict[str, Any]] = []

        for current_step, current_date in enumerate(dates, start=1):
            await asyncio.sleep(0)

            lookback_start = (current_date - timedelta(days=30)).strftime("%Y-%m-%d")
            current_date_str = current_date.strftime("%Y-%m-%d")
            if lookback_start == current_date_str:
                continue

            previous_date_str = (current_date - timedelta(days=1)).strftime("%Y-%m-%d")
            self._publish_progress(progress_callback, current_date_str, current_step, len(dates))

            current_prices = self._get_current_prices(previous_date_str, current_date_str)
            if current_prices is None:
                continue

            decisions, analyst_signals = await self._run_graph_for_date(lookback_start, current_date_str, run_id=run_id)
            executed_trades = self._execute_daily_decisions(decisions, current_prices)
            total_value = self.calculate_portfolio_value(current_prices)
            exposures = calculate_exposures(self.portfolio, self.tickers, current_prices)
            append_portfolio_snapshot(self.portfolio_values, current_date, total_value, exposures)

            if len(self.portfolio_values) > 2:
                self._update_performance_metrics(performance_metrics)

            portfolio_return = (total_value / self.initial_capital - 1) * 100
            date_result = build_backtest_day_result(
                current_date_str=current_date_str,
                total_value=total_value,
                portfolio=self.portfolio,
                decisions=decisions,
                executed_trades=executed_trades,
                analyst_signals=analyst_signals,
                current_prices=current_prices,
                exposures=exposures,
                portfolio_return=portfolio_return,
                performance_metrics=performance_metrics,
                tickers=self.tickers,
            )
            backtest_results.append(date_result)

            if progress_callback is not None:
                progress_callback({"type": "backtest_result", "data": date_result})

        return self._finalize_backtest(backtest_results, performance_metrics)

    def run_backtest_sync(self) -> dict[str, Any]:
        """
        Run the backtest synchronously.
        This version can be used by the CLI.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.run_backtest_async())
        finally:
            loop.close()

    def analyze_performance(self) -> pd.DataFrame:
        """Analyze performance and return DataFrame with metrics."""
        if not self.portfolio_values:
            return pd.DataFrame()

        performance_df = pd.DataFrame(self.portfolio_values).set_index("Date")
        if performance_df.empty:
            return performance_df

        performance_df["Daily Return"] = performance_df["Portfolio Value"].pct_change().fillna(0)
        return performance_df
