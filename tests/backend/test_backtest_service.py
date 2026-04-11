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
