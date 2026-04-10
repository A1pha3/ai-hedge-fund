import pandas as pd

from src.backtesting.engine import BacktestEngine
from src.backtesting.controller import AgentController


def dummy_agent(**kwargs):
    # Echo basic structure with only one decision
    tickers = kwargs["tickers"]
    return {
        "decisions": {tickers[0]: {"action": "buy", "quantity": "10"}},
        "analyst_signals": {"agentA": {tickers[0]: {"signal": "bullish"}}},
    }


def test_agent_controller_normalizes_and_snapshots(portfolio):
    ctrl = AgentController()
    out = ctrl.run_agent(
        dummy_agent,
        tickers=["AAPL", "MSFT"],
        start_date="2024-01-01",
        end_date="2024-01-10",
        portfolio=portfolio,
        model_name="m",
        model_provider="p",
        selected_analysts=["x"],
    )

    # Decisions normalized for all tickers
    assert out["decisions"]["AAPL"]["action"] == "buy"
    assert out["decisions"]["AAPL"]["quantity"] == 10.0
    # Missing ticker defaults to hold/0
    assert out["decisions"]["MSFT"]["action"] == "hold"
    assert out["decisions"]["MSFT"]["quantity"] == 0.0
    # Analyst signals are passed through
    assert "agentA" in out["analyst_signals"]


def test_run_agent_mode_executes_and_appends_state(monkeypatch):
    engine = BacktestEngine(
        agent=dummy_agent,
        tickers=["AAPL", "MSFT"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="m",
        model_provider="p",
        selected_analysts=["x"],
        initial_margin_requirement=0.0,
        backtest_mode="agent",
    )
    append_calls: list[dict] = []

    monkeypatch.setattr(engine, "_load_current_prices", lambda *args, **kwargs: {"AAPL": 100.0, "MSFT": 200.0})
    monkeypatch.setattr(engine, "_append_daily_state", lambda **kwargs: append_calls.append(kwargs))

    engine._run_agent_mode(pd.DatetimeIndex([pd.Timestamp("2024-03-04")]))

    assert engine._portfolio.get_positions()["AAPL"]["long"] == 10
    assert append_calls[0]["executed_trades"] == {"AAPL": 10, "MSFT": 0}
    assert append_calls[0]["current_date_str"] == "2024-03-04"


def test_run_agent_mode_skips_day_without_prices(monkeypatch):
    engine = BacktestEngine(
        agent=dummy_agent,
        tickers=["AAPL", "MSFT"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="m",
        model_provider="p",
        selected_analysts=["x"],
        initial_margin_requirement=0.0,
        backtest_mode="agent",
    )
    run_agent_calls: list[dict] = []
    append_calls: list[dict] = []

    monkeypatch.setattr(engine, "_load_current_prices", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine._agent_controller, "run_agent", lambda *args, **kwargs: run_agent_calls.append(kwargs) or dummy_agent(**kwargs))
    monkeypatch.setattr(engine, "_append_daily_state", lambda **kwargs: append_calls.append(kwargs))

    engine._run_agent_mode(pd.DatetimeIndex([pd.Timestamp("2024-03-04")]))

    assert run_agent_calls == []
    assert append_calls == []
