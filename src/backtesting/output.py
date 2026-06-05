from __future__ import annotations

from collections.abc import Mapping, Sequence

from src.utils.display import format_backtest_row, print_backtest_results

from .portfolio import Portfolio
from .types import AgentOutput
from .valuation import compute_portfolio_summary


class OutputBuilder:
    """Builds daily output rows and prints results using display utils.

    Stateless: callers provide inputs and receive rows back.
    """

    def __init__(self, *, initial_capital: float | None = None) -> None:
        self._initial_capital = initial_capital

    def build_day_rows(
        self,
        *,
        date_str: str,
        tickers: Sequence[str],
        agent_output: AgentOutput,
        executed_trades: Mapping[str, int],
        current_prices: Mapping[str, float],
        portfolio: Portfolio,
        performance_metrics: Mapping[str, float | None],
        total_value: float,
        benchmark_return_pct: float | None = None,
    ) -> list[list]:
        date_rows: list[list] = []

        decisions = agent_output.get("decisions", {})
        positions = portfolio.get_positions()

        for ticker in tickers:
            # Analyst signal counts removed from day table

            pos = positions.get(ticker)
            long_shares = int(pos["long"]) if pos is not None else 0
            short_shares = int(pos["short"]) if pos is not None else 0
            ticker_price = float(current_prices.get(ticker, 0.0))
            long_val = long_shares * ticker_price
            short_val = short_shares * ticker_price
            net_position_value = long_val - short_val

            action = decisions.get(ticker, {}).get("action", "hold")
            quantity = executed_trades.get(ticker, 0)

            date_rows.append(
                format_backtest_row(
                    date=date_str,
                    ticker=ticker,
                    action=action,
                    quantity=quantity,
                    price=ticker_price,
                    long_shares=long_shares,
                    short_shares=short_shares,
                    position_value=net_position_value,
                )
            )

        # Summary row
        initial_value = self._initial_capital if self._initial_capital is not None else total_value
        summary = compute_portfolio_summary(
            portfolio=portfolio,
            total_value=total_value,
            initial_value=initial_value,
            performance_metrics=performance_metrics,
        )

        date_rows.append(
            format_backtest_row(
                date=date_str,
                ticker="",
                action="",
                quantity=0,
                price=0,
                long_shares=0,
                short_shares=0,
                position_value=0,
                is_summary=True,
                total_value=summary["total_value"],
                return_pct=summary["return_pct"],
                cash_balance=summary["cash_balance"],
                total_position_value=summary["total_position_value"],
                sharpe_ratio=summary["sharpe_ratio"],
                sortino_ratio=summary["sortino_ratio"],
                max_drawdown=summary["max_drawdown"],
                benchmark_return_pct=benchmark_return_pct,
            )
        )

        return date_rows

    def print_rows(self, rows: list[list]) -> None:
        print_backtest_results(rows)
