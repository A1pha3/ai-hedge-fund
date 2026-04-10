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


def test_append_daily_state_updates_portfolio_rows_and_metrics(monkeypatch):
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
    engine._portfolio_values = [
        {"Date": pd.Timestamp("2024-03-01")},
        {"Date": pd.Timestamp("2024-03-02")},
        {"Date": pd.Timestamp("2024-03-03")},
    ]
    printed_rows: list[list[list]] = []

    monkeypatch.setattr("src.backtesting.engine.calculate_portfolio_value", lambda portfolio, prices: 123456.0)
    monkeypatch.setattr(
        "src.backtesting.engine.compute_exposures",
        lambda portfolio, prices: {
            "Long Exposure": 0.6,
            "Short Exposure": 0.1,
            "Gross Exposure": 0.7,
            "Net Exposure": 0.5,
            "Long/Short Ratio": 6.0,
        },
    )
    monkeypatch.setattr(engine._benchmark, "get_return_pct", lambda *args, **kwargs: 1.2)
    monkeypatch.setattr(
        engine._results,
        "build_day_rows",
        lambda **kwargs: [[kwargs["date_str"], kwargs["total_value"], kwargs["benchmark_return_pct"]]],
    )
    monkeypatch.setattr(engine._results, "print_rows", lambda rows: printed_rows.append(rows))
    monkeypatch.setattr(engine._perf, "compute_metrics", lambda values: {"sharpe_ratio": 1.5})

    engine._append_daily_state(
        current_date=pd.Timestamp("2024-03-04"),
        current_date_str="2024-03-04",
        active_tickers=["AAPL", "MSFT"],
        agent_output={"decisions": {"AAPL": {"action": "buy", "quantity": 10}}, "analyst_signals": {}},
        executed_trades={"AAPL": 10, "MSFT": 0},
        current_prices={"AAPL": 100.0, "MSFT": 200.0},
    )

    assert engine._portfolio_values[-1]["Portfolio Value"] == 123456.0
    assert engine._portfolio_values[-1]["Long Exposure"] == 0.6
    assert engine._table_rows[0] == ["2024-03-04", 123456.0, 1.2]
    assert printed_rows[-1] == engine._table_rows
    assert engine._performance_metrics["sharpe_ratio"] == 1.5
