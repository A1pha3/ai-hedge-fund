import asyncio
from types import SimpleNamespace

import pandas as pd

from app.backend.services.backtest_service import BacktestService
from app.backend.services.portfolio import create_portfolio


def _build_service() -> BacktestService:
    return BacktestService(
        graph=object(),
        portfolio=create_portfolio(10_000.0, 0.5, ["AAPL"], []),
        tickers=["AAPL"],
        start_date="2026-01-05",
        end_date="2026-01-05",
        initial_capital=10_000.0,
        model_name="demo-model",
        model_provider="demo-provider",
        request=SimpleNamespace(api_keys={}),
    )


def test_execute_trade_handles_long_and_short_lifecycle():
    service = _build_service()

    assert service.execute_trade("AAPL", "buy", 10, 100.0) == 10
    assert service.portfolio["positions"]["AAPL"]["long"] == 10
    assert service.portfolio["cash"] == 9_000.0

    assert service.execute_trade("AAPL", "sell", 4, 120.0) == 4
    assert service.portfolio["positions"]["AAPL"]["long"] == 6
    assert service.portfolio["realized_gains"]["AAPL"]["long"] == 80.0

    assert service.execute_trade("AAPL", "short", 8, 50.0) == 8
    assert service.portfolio["positions"]["AAPL"]["short"] == 8
    assert service.portfolio["margin_used"] == 200.0

    assert service.execute_trade("AAPL", "cover", 3, 40.0) == 3
    assert service.portfolio["positions"]["AAPL"]["short"] == 5
    assert service.portfolio["realized_gains"]["AAPL"]["short"] == 30.0


def test_run_backtest_async_builds_results(monkeypatch):
    service = _build_service()
    updates = []

    monkeypatch.setattr(service, "prefetch_data", lambda: None)
    monkeypatch.setattr(
        "app.backend.services.backtest_service.get_price_data",
        lambda *_args, **_kwargs: pd.DataFrame([{"close": 110.0}]),
    )

    async def fake_run_graph_async(**_kwargs):
        return {
            "messages": [SimpleNamespace(content="ignored")],
            "data": {"analyst_signals": {"technical": {"AAPL": {"signal": "bullish"}}}},
        }

    monkeypatch.setattr("app.backend.services.backtest_service.run_graph_async", fake_run_graph_async)
    monkeypatch.setattr("app.backend.services.backtest_service.parse_hedge_fund_response", lambda _content: {"AAPL": {"action": "buy", "quantity": 5}})

    result = asyncio.run(service.run_backtest_async(progress_callback=updates.append))

    assert len(result["results"]) == 1
    day_result = result["results"][0]
    assert day_result["date"] == "2026-01-05"
    assert day_result["executed_trades"] == {"AAPL": 5}
    assert day_result["ticker_details"][0]["bullish_count"] == 1
    assert result["final_portfolio"]["positions"]["AAPL"]["long"] == 5
    assert any(update["type"] == "progress" for update in updates)
    assert any(update["type"] == "backtest_result" for update in updates)


# ---------------------------------------------------------------------------
# BUG B fix: calculate_portfolio_value must include margin_used
# ---------------------------------------------------------------------------


def test_calculate_portfolio_value_includes_margin_used():
    """Portfolio value must add margin_used back.  Margin used is cash locked
    as collateral for open short positions -- it belongs to the portfolio but
    is excluded from the cash balance, so it must be added back to get the
    true total value.  Consistent with risk_manager_helpers."""
    service = _build_service()

    # Start: cash=10000, no positions, margin_used=0
    assert service.calculate_portfolio_value({"AAPL": 100.0}) == 10_000.0

    # Open a short position: short 20 shares at $50
    service.execute_trade("AAPL", "short", 20, 50.0)

    # After short: cash = 10000 + 1000 (proceeds) - 500 (margin) = 10500
    # margin_used = 500
    # short position value = -20 * 50 = -1000
    # Without fix: total = 10500 - 1000 = 9500 (WRONG -- drops margin_used)
    # With fix:    total = 10500 - 1000 + 500 = 10000 (CORRECT)
    total = service.calculate_portfolio_value({"AAPL": 50.0})
    assert total == 10_000.0, f"Expected 10000.0, got {total}"


def test_calculate_portfolio_value_with_long_and_short():
    """Mixed long+short positions must include margin_used correctly."""
    service = _build_service()

    # Buy 50 shares at $100
    service.execute_trade("AAPL", "buy", 50, 100.0)
    # cash = 10000 - 5000 = 5000
    # long value = 50 * 100 = 5000

    assert service.calculate_portfolio_value({"AAPL": 100.0}) == 10_000.0

    # Short 10 shares at $120
    service.execute_trade("AAPL", "short", 10, 120.0)
    # cash = 5000 + 1200 - 600 = 5600
    # margin_used = 600
    # long value = 50 * 120 = 6000
    # short value = 10 * 120 = 1200
    # total = 5600 + 6000 - 1200 + 600 = 11000
    total = service.calculate_portfolio_value({"AAPL": 120.0})
    assert total == 11_000.0


# ---------------------------------------------------------------------------
# BUG C fix: _get_current_prices must not abort all tickers on single failure
# ---------------------------------------------------------------------------


def test_get_current_prices_continues_on_single_ticker_failure(monkeypatch):
    """When one ticker fails to return price data, other tickers must still
    be processed instead of aborting the entire day."""
    portfolio = create_portfolio(10_000.0, 0.5, ["AAPL", "MSFT"], [])
    service = BacktestService(
        graph=object(),
        portfolio=portfolio,
        tickers=["AAPL", "MSFT"],
        start_date="2026-01-05",
        end_date="2026-01-05",
        initial_capital=10_000.0,
        model_name="demo-model",
        model_provider="demo-provider",
        request=SimpleNamespace(api_keys={}),
    )

    call_count = {"AAPL": 0, "MSFT": 0}

    def fake_get_price_data(ticker, *_args, **_kwargs):
        call_count[ticker] = call_count.get(ticker, 0) + 1
        if ticker == "AAPL":
            return pd.DataFrame()  # empty -- simulates failure
        return pd.DataFrame([{"close": 200.0}])

    monkeypatch.setattr(
        "app.backend.services.backtest_service.get_price_data",
        fake_get_price_data,
    )

    prices = service._get_current_prices("2026-01-04", "2026-01-05")
    assert prices is not None
    assert "AAPL" not in prices
    assert "MSFT" in prices
    assert prices["MSFT"] == 200.0
    assert call_count["AAPL"] == 1
    assert call_count["MSFT"] == 1


def test_get_current_prices_returns_none_when_all_fail(monkeypatch):
    """If ALL tickers fail, return None (skip the day)."""
    portfolio = create_portfolio(10_000.0, 0.5, ["AAPL"], [])
    service = BacktestService(
        graph=object(),
        portfolio=portfolio,
        tickers=["AAPL"],
        start_date="2026-01-05",
        end_date="2026-01-05",
        initial_capital=10_000.0,
        model_name="demo-model",
        model_provider="demo-provider",
        request=SimpleNamespace(api_keys={}),
    )

    monkeypatch.setattr(
        "app.backend.services.backtest_service.get_price_data",
        lambda *_args, **_kwargs: pd.DataFrame(),  # empty for all
    )

    prices = service._get_current_prices("2026-01-04", "2026-01-05")
    assert prices is None


def test_get_current_prices_continues_on_exception(monkeypatch):
    """If one ticker throws an exception, continue with others."""
    portfolio = create_portfolio(10_000.0, 0.5, ["AAPL", "MSFT"], [])
    service = BacktestService(
        graph=object(),
        portfolio=portfolio,
        tickers=["AAPL", "MSFT"],
        start_date="2026-01-05",
        end_date="2026-01-05",
        initial_capital=10_000.0,
        model_name="demo-model",
        model_provider="demo-provider",
        request=SimpleNamespace(api_keys={}),
    )

    def fake_get_price_data(ticker, *_args, **_kwargs):
        if ticker == "AAPL":
            raise ConnectionError("API timeout")
        return pd.DataFrame([{"close": 300.0}])

    monkeypatch.setattr(
        "app.backend.services.backtest_service.get_price_data",
        fake_get_price_data,
    )

    prices = service._get_current_prices("2026-01-04", "2026-01-05")
    assert prices == {"MSFT": 300.0}


def test_execute_daily_decisions_skips_tickers_with_missing_prices():
    """Trades must not be executed for tickers missing from current_prices."""
    portfolio = create_portfolio(10_000.0, 0.5, ["AAPL", "MSFT"], [])
    service = BacktestService(
        graph=object(),
        portfolio=portfolio,
        tickers=["AAPL", "MSFT"],
        start_date="2026-01-05",
        end_date="2026-01-05",
        initial_capital=10_000.0,
        model_name="demo-model",
        model_provider="demo-provider",
        request=SimpleNamespace(api_keys={}),
    )

    decisions = {
        "AAPL": {"action": "buy", "quantity": 10},
        "MSFT": {"action": "buy", "quantity": 5},
    }
    # Only MSFT has a price; AAPL is missing
    current_prices = {"MSFT": 200.0}

    executed = service._execute_daily_decisions(decisions, current_prices)
    assert executed["AAPL"] == 0  # skipped, no trade
    assert executed["MSFT"] == 5  # executed normally
