from typing import Any


def create_performance_metrics() -> dict[str, float | None]:
    return {
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "max_drawdown": 0.0,
        "long_short_ratio": 0.0,
        "gross_exposure": 0.0,
        "net_exposure": 0.0,
    }


def calculate_exposures(portfolio: dict[str, Any], tickers: list[str], current_prices: dict[str, float]) -> dict[str, float | None]:
    long_exposure = sum(portfolio["positions"][ticker]["long"] * current_prices[ticker] for ticker in tickers)
    short_exposure = sum(portfolio["positions"][ticker]["short"] * current_prices[ticker] for ticker in tickers)
    gross_exposure = long_exposure + short_exposure
    net_exposure = long_exposure - short_exposure
    long_short_ratio = long_exposure / short_exposure if short_exposure > 1e-9 else None
    return {
        "long_exposure": long_exposure,
        "short_exposure": short_exposure,
        "gross_exposure": gross_exposure,
        "net_exposure": net_exposure,
        "long_short_ratio": long_short_ratio,
    }


def append_portfolio_snapshot(
    portfolio_values: list[dict[str, Any]],
    current_date: Any,
    total_value: float,
    exposures: dict[str, float | None],
) -> None:
    portfolio_values.append(
        {
            "Date": current_date,
            "Portfolio Value": total_value,
            "Long Exposure": exposures["long_exposure"],
            "Short Exposure": exposures["short_exposure"],
            "Gross Exposure": exposures["gross_exposure"],
            "Net Exposure": exposures["net_exposure"],
            "Long/Short Ratio": exposures["long_short_ratio"],
        }
    )


def build_ticker_details(
    portfolio: dict[str, Any],
    tickers: list[str],
    current_prices: dict[str, float],
    decisions: dict[str, Any],
    executed_trades: dict[str, int],
    analyst_signals: dict[str, Any],
) -> list[dict[str, Any]]:
    ticker_details = []

    for ticker in tickers:
        ticker_signals = {agent_name: signals[ticker] for agent_name, signals in analyst_signals.items() if ticker in signals}
        bullish_count = len([signal for signal in ticker_signals.values() if signal.get("signal", "").lower() == "bullish"])
        bearish_count = len([signal for signal in ticker_signals.values() if signal.get("signal", "").lower() == "bearish"])
        neutral_count = len([signal for signal in ticker_signals.values() if signal.get("signal", "").lower() == "neutral"])

        position = portfolio["positions"][ticker]
        long_value = position["long"] * current_prices[ticker]
        short_value = position["short"] * current_prices[ticker]

        ticker_details.append(
            {
                "ticker": ticker,
                "action": decisions.get(ticker, {}).get("action", "hold"),
                "quantity": executed_trades.get(ticker, 0),
                "price": current_prices[ticker],
                "shares_owned": position["long"] - position["short"],
                "long_shares": position["long"],
                "short_shares": position["short"],
                "position_value": long_value - short_value,
                "bullish_count": bullish_count,
                "bearish_count": bearish_count,
                "neutral_count": neutral_count,
            }
        )

    return ticker_details


def build_backtest_day_result(
    current_date_str: str,
    total_value: float,
    portfolio: dict[str, Any],
    decisions: dict[str, Any],
    executed_trades: dict[str, int],
    analyst_signals: dict[str, Any],
    current_prices: dict[str, float],
    exposures: dict[str, float | None],
    portfolio_return: float,
    performance_metrics: dict[str, Any],
    tickers: list[str],
) -> dict[str, Any]:
    return {
        "date": current_date_str,
        "portfolio_value": total_value,
        "cash": portfolio["cash"],
        "decisions": decisions,
        "executed_trades": executed_trades,
        "analyst_signals": analyst_signals,
        "current_prices": current_prices,
        "long_exposure": exposures["long_exposure"],
        "short_exposure": exposures["short_exposure"],
        "gross_exposure": exposures["gross_exposure"],
        "net_exposure": exposures["net_exposure"],
        "long_short_ratio": exposures["long_short_ratio"],
        "portfolio_return": portfolio_return,
        "performance_metrics": performance_metrics.copy(),
        "ticker_details": build_ticker_details(
            portfolio=portfolio,
            tickers=tickers,
            current_prices=current_prices,
            decisions=decisions,
            executed_trades=executed_trades,
            analyst_signals=analyst_signals,
        ),
    }
