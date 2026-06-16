import pandas as pd

from src.backtesting.controller import AgentController
from src.backtesting.engine import BacktestEngine
from src.backtesting.engine_agent_mode import execute_agent_mode_trades
from src.backtesting.engine_market_data import MarketDataLoader
from src.backtesting.portfolio import Portfolio
from src.backtesting.trading_constraints import TradeExecutionInputs


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


def test_run_agent_mode_records_long_entry_date_on_buy(monkeypatch):
    """Test that agent mode records entry_date after successful buy execution."""
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

    monkeypatch.setattr(engine, "_load_current_prices", lambda *args, **kwargs: {"AAPL": 100.0, "MSFT": 200.0})
    monkeypatch.setattr(engine, "_append_daily_state", lambda **kwargs: None)

    # Execute agent mode for a single day where agent buys AAPL
    engine._run_agent_mode(pd.DatetimeIndex([pd.Timestamp("2024-03-04")]))

    # Verify buy execution happened
    positions = engine._portfolio.get_positions()
    assert positions["AAPL"]["long"] == 10

    # Critical check: entry_date must be recorded for T+1 enforcement
    assert positions["AAPL"]["entry_date"] == "2024-03-04", "Agent mode must record entry_date after buy execution"


def test_agent_mode_t_plus_1_blocks_same_day_sell(monkeypatch):
    """Test that T+1 enforcement works in agent mode: same-day sell is blocked."""
    
    def buy_then_sell_agent(**kwargs):
        """Agent that buys AAPL on first call, sells on second."""
        tickers = kwargs["tickers"]
        # Portfolio is a snapshot dict (not Portfolio object)
        portfolio_snapshot = kwargs["portfolio"]
        if portfolio_snapshot["positions"]["AAPL"]["long"] > 0:
            return {
                "decisions": {tickers[0]: {"action": "sell", "quantity": "10"}},
                "analyst_signals": {},
            }
        return {
            "decisions": {tickers[0]: {"action": "buy", "quantity": "10"}},
            "analyst_signals": {},
        }
    
    engine = BacktestEngine(
        agent=buy_then_sell_agent,
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="m",
        model_provider="p",
        selected_analysts=["x"],
        initial_margin_requirement=0.0,
        backtest_mode="agent",
    )

    monkeypatch.setattr(engine, "_load_current_prices", lambda *args, **kwargs: {"AAPL": 100.0})
    monkeypatch.setattr(engine, "_append_daily_state", lambda **kwargs: None)

    # Execute buy on day 1
    engine._run_agent_mode(pd.DatetimeIndex([pd.Timestamp("2024-03-04")]))
    
    # Verify buy executed and entry_date recorded
    positions_after_buy = engine._portfolio.get_positions()
    assert positions_after_buy["AAPL"]["long"] == 10
    assert positions_after_buy["AAPL"]["entry_date"] == "2024-03-04"

    # Attempt to sell on the same day (should be blocked by T+1)
    engine._run_agent_mode(pd.DatetimeIndex([pd.Timestamp("2024-03-04")]))
    
    # Position should remain intact (sell was blocked)
    positions_after_sell_attempt = engine._portfolio.get_positions()
    assert positions_after_sell_attempt["AAPL"]["long"] == 10, "T+1 must block same-day sell in agent mode"


def test_execute_agent_mode_trades_uses_baseline_execution_inputs_until_btst_payload_exists():
    captured_execution_inputs: list[TradeExecutionInputs] = []

    class StubExecutor:
        def execute_trade(self, *args, **kwargs):
            captured_execution_inputs.append(kwargs["execution_inputs"])
            return 0

    executed = execute_agent_mode_trades(
        executor=StubExecutor(),
        tickers=["AAPL"],
        decisions={"AAPL": {"action": "buy", "quantity": 10}},
        current_prices={"AAPL": 100.0},
        portfolio=Portfolio(tickers=["AAPL"], initial_cash=100000.0, margin_requirement=0.0),
        trade_date="2024-03-04",
    )

    assert executed == {"AAPL": 0}
    assert captured_execution_inputs == [TradeExecutionInputs(daily_turnover=None)]


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


def test_market_data_loader_prefetches_hs300_for_ashare_universe(monkeypatch):
    fetched_price_tickers: list[str] = []

    monkeypatch.setattr("src.backtesting.engine_market_data.get_prices", lambda ticker, *args, **kwargs: fetched_price_tickers.append(ticker) or [])
    monkeypatch.setattr("src.backtesting.engine_market_data.get_financial_metrics", lambda *args, **kwargs: [])
    monkeypatch.setattr("src.backtesting.engine_market_data.get_insider_trades", lambda *args, **kwargs: [])
    monkeypatch.setattr("src.backtesting.engine_market_data.get_company_news", lambda *args, **kwargs: [])

    loader = MarketDataLoader(
        tickers=["001309"],
        start_date="2026-04-07",
        end_date="2026-04-13",
        portfolio=Portfolio(tickers=["001309"], initial_cash=100000.0, margin_requirement=0.0),
        exit_reentry_cooldowns={},
    )

    loader.prefetch_data()

    assert "001309" in fetched_price_tickers
    assert "000300.SH" in fetched_price_tickers
    assert "SPY" not in fetched_price_tickers


def test_append_daily_state_uses_hs300_benchmark_for_ashare_universe(monkeypatch):
    engine = BacktestEngine(
        agent=dummy_agent,
        tickers=["001309"],
        start_date="2026-04-07",
        end_date="2026-04-13",
        initial_capital=100000.0,
        model_name="m",
        model_provider="p",
        selected_analysts=["x"],
        initial_margin_requirement=0.0,
        backtest_mode="agent",
    )
    engine._portfolio_values = [
        {"Date": pd.Timestamp("2026-04-07")},
        {"Date": pd.Timestamp("2026-04-08")},
        {"Date": pd.Timestamp("2026-04-09")},
    ]
    benchmark_tickers: list[str] = []

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
    monkeypatch.setattr(engine._benchmark, "get_return_pct", lambda ticker, *args, **kwargs: benchmark_tickers.append(ticker) or 1.2)
    monkeypatch.setattr(engine._results, "build_day_rows", lambda **kwargs: [[kwargs["date_str"], kwargs["total_value"], kwargs["benchmark_return_pct"]]])
    monkeypatch.setattr(engine._results, "print_rows", lambda rows: None)
    monkeypatch.setattr(engine._perf, "compute_metrics", lambda values: {"sharpe_ratio": 1.5})

    engine._append_daily_state(
        current_date=pd.Timestamp("2026-04-10"),
        current_date_str="2026-04-10",
        active_tickers=["001309"],
        agent_output={"decisions": {"001309": {"action": "buy", "quantity": 10}}, "analyst_signals": {}},
        executed_trades={"001309": 10},
        current_prices={"001309": 100.0},
    )

    assert benchmark_tickers == ["000300.SH"]


def test_build_daily_state_rows_uses_first_portfolio_date_for_benchmark_anchor(monkeypatch):
    engine = BacktestEngine(
        agent=dummy_agent,
        tickers=["AAPL"],
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
        {"Date": pd.Timestamp("2024-03-04"), "Portfolio Value": 100000.0},
    ]
    benchmark_calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        engine._benchmark,
        "get_return_pct",
        lambda ticker, start_date, end_date: benchmark_calls.append((ticker, start_date, end_date)) or 0.0,
    )
    monkeypatch.setattr(
        engine._results,
        "build_day_rows",
        lambda **kwargs: [[kwargs["date_str"], kwargs["benchmark_return_pct"]]],
    )

    rows = engine._build_daily_state_rows(
        date_str="2024-03-05",
        tickers=["AAPL"],
        agent_output={"decisions": {"AAPL": {"action": "hold", "quantity": 0}}, "analyst_signals": {}},
        executed_trades={"AAPL": 0},
        current_prices={"AAPL": 100.0},
        total_value=100000.0,
    )

    assert rows == [["2024-03-05", 0.0]]
    assert benchmark_calls == [("SPY", "2024-03-04", "2024-03-05")]


def test_update_daily_performance_metrics_updates_with_three_points(monkeypatch):
    engine = BacktestEngine(
        agent=dummy_agent,
        tickers=["AAPL"],
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
        {"Date": pd.Timestamp("2024-03-01"), "Portfolio Value": 100000.0},
        {"Date": pd.Timestamp("2024-03-04"), "Portfolio Value": 101000.0},
        {"Date": pd.Timestamp("2024-03-05"), "Portfolio Value": 99000.0},
    ]
    compute_calls: list[list[dict]] = []

    monkeypatch.setattr(
        engine._perf,
        "compute_metrics",
        lambda values: compute_calls.append(list(values)) or {"sharpe_ratio": 1.23},
    )

    engine._update_daily_performance_metrics()

    assert len(compute_calls) == 1
    assert engine._performance_metrics["sharpe_ratio"] == 1.23


def test_prepare_run_dates_seeds_anchor_before_first_bar_not_on_it(monkeypatch):
    """BH-001: the initial-capital seed must NOT share its Date with the first
    backtest bar. Previously the seed was labelled ``dates[0]`` and the run loop
    also appended a real post-trade point for ``dates[0]``, producing a
    duplicate Date index whose phantom intra-day ``pct_change`` distorted
    per-bar return attribution and left ``max_drawdown_date`` / frontend
    rendering with a non-unique index.

    The fix anchors the seed at ``dates[0] - 1 calendar day``: ``iloc[0]``
    stays ``initial_capital`` (total_return unchanged) while the Date index is
    unique. This test pins that invariant so a regression is caught.
    """
    engine = BacktestEngine(
        agent=dummy_agent,
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="m",
        model_provider="p",
        selected_analysts=["x"],
        initial_margin_requirement=0.0,
        backtest_mode="agent",
    )
    fixed_dates = pd.DatetimeIndex(
        [pd.Timestamp("2024-03-04"), pd.Timestamp("2024-03-05")]
    )
    monkeypatch.setattr(engine, "_iter_backtest_dates", lambda: fixed_dates)
    # Fresh run (no checkpoint) → seed path under test.
    monkeypatch.setattr(engine, "_load_checkpoint", lambda: (None, None))

    returned_dates, _ = engine._prepare_run_dates_and_plan()

    assert len(engine._portfolio_values) == 1
    seed = engine._portfolio_values[0]
    seed_date = pd.Timestamp(seed["Date"])
    first_bar_date = fixed_dates[0]

    # Seed value is the initial capital (total_return anchor unchanged).
    assert seed["Portfolio Value"] == 100000.0
    # Seed Date is strictly BEFORE the first bar — never on it (the bug).
    assert seed_date < first_bar_date
    # Returned dates are unaffected (the loop still processes every bar).
    assert list(returned_dates) == list(fixed_dates)


def test_agent_mode_run_produces_unique_date_index(monkeypatch):
    """BH-001 drain: a fresh agent-mode run must yield a portfolio_values series
    with a unique Date index. Before the fix the seed shared ``dates[0]`` with
    the first real bar, so the index had a duplicate."""
    engine = BacktestEngine(
        agent=dummy_agent,
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="m",
        model_provider="p",
        selected_analysts=["x"],
        initial_margin_requirement=0.0,
        backtest_mode="agent",
    )
    # Seed via the production path under test.
    fixed_dates = pd.DatetimeIndex([pd.Timestamp("2024-03-04"), pd.Timestamp("2024-03-05")])
    monkeypatch.setattr(engine, "_iter_backtest_dates", lambda: fixed_dates)
    monkeypatch.setattr(engine, "_load_checkpoint", lambda: (None, None))
    engine._prepare_run_dates_and_plan()

    monkeypatch.setattr(engine, "_load_current_prices", lambda *a, **k: {"AAPL": 100.0})
    # Let _append_daily_state run for real so real bars get appended.

    engine._run_agent_mode(fixed_dates)

    dates = [pd.Timestamp(p["Date"]) for p in engine._portfolio_values]
    # Seed + one bar per processed date => no duplicate Date.
    assert len(dates) == len(set(dates)), f"Duplicate Date index: {dates}"


def test_iter_backtest_dates_prefers_a_share_trading_calendar(monkeypatch):
    """R38: iter_backtest_dates must use the real A-share trading calendar
    (trade_cal) when available, so Chinese public holidays are excluded —
    otherwise they produce phantom zero-return bars that dilute Sharpe."""
    engine = BacktestEngine(
        agent=dummy_agent,
        tickers=["AAPL"],
        start_date="2026-02-23",  # spans a weekday but Spring Festival holiday region
        end_date="2026-02-27",
        initial_capital=100000.0,
        model_name="m",
        model_provider="p",
        selected_analysts=["x"],
        initial_margin_requirement=0.0,
        backtest_mode="agent",
    )
    # trade_cal returns only 2 trading days (simulate holiday exclusion).
    monkeypatch.setattr(
        "src.tools.tushare_api.get_open_trade_dates",
        lambda start, end: ["20260225", "20260226"],
    )
    dates = engine._iter_backtest_dates()
    assert list(dates) == [pd.Timestamp("20260225"), pd.Timestamp("20260226")]
    # Holidays (Feb 23/24/27) excluded — no phantom zero-return bars.


def test_iter_backtest_dates_falls_back_to_business_days_when_no_calendar(monkeypatch):
    """R38: when trade_cal is unavailable (no token / API failure → empty
    list), iter_backtest_dates must fall back to freq='B' so the backtest still
    runs rather than failing."""
    engine = BacktestEngine(
        agent=dummy_agent,
        tickers=["AAPL"],
        start_date="2026-02-23",
        end_date="2026-02-27",
        initial_capital=100000.0,
        model_name="m",
        model_provider="p",
        selected_analysts=["x"],
        initial_margin_requirement=0.0,
        backtest_mode="agent",
    )
    # No token / API failure → empty list → fallback to Mon–Fri business days.
    monkeypatch.setattr(
        "src.tools.tushare_api.get_open_trade_dates",
        lambda start, end: [],
    )
    dates = engine._iter_backtest_dates()
    # Mon 2026-02-23 through Fri 2026-02-27 = 5 business days (no holiday exclusion).
    assert len(dates) == 5
