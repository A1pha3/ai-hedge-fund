import pandas as pd

from src.backtesting.engine import BacktestEngine
from src.execution.models import ExecutionPlan
from src.portfolio.models import PositionPlan


class StubPipeline:
    def __init__(self, post_market_plans, intraday_responses):
        self.post_market_plans = list(post_market_plans)
        self.intraday_responses = list(intraday_responses)
        self.post_market_calls = []
        self.pre_market_calls = []
        self.intraday_calls = []

    def run_post_market(self, trade_date: str, portfolio_snapshot: dict | None = None) -> ExecutionPlan:
        self.post_market_calls.append((trade_date, portfolio_snapshot or {}))
        if self.post_market_plans:
            return self.post_market_plans.pop(0)
        return ExecutionPlan(date=trade_date, portfolio_snapshot=portfolio_snapshot or {})

    def run_pre_market(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs) -> ExecutionPlan:
        self.pre_market_calls.append((trade_date_t1, plan))
        return plan

    def run_intraday(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs):
        self.intraday_calls.append((trade_date_t1, kwargs))
        if self.intraday_responses:
            return self.intraday_responses.pop(0)
        return [], [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0}


def _patch_market_data(monkeypatch, closes_by_ticker: dict[str, dict[str, float]]) -> None:
    monkeypatch.setattr("src.backtesting.engine.get_prices", lambda *a, **k: None)
    monkeypatch.setattr("src.backtesting.engine.get_financial_metrics", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.engine.get_insider_trades", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.engine.get_company_news", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.output.print_backtest_results", lambda *a, **k: None)

    def fake_get_price_data(ticker: str, start_date: str, end_date: str, api_key=None):
        closes = closes_by_ticker[ticker]
        rows = [
            {"date": date_str, "close": close, "open": close, "high": close, "low": close, "volume": 1_000_000}
            for date_str, close in closes.items()
            if start_date <= date_str <= end_date
        ]
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        frame["date"] = pd.to_datetime(frame["date"])
        frame.set_index("date", inplace=True)
        return frame[["open", "close", "high", "low", "volume"]]

    monkeypatch.setattr("src.backtesting.engine.get_price_data", fake_get_price_data)
    monkeypatch.setattr("src.backtesting.benchmarks.get_price_data", fake_get_price_data)


def test_pipeline_mode_executes_buy_on_t_plus_one(monkeypatch):
    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
                "2024-03-05": 12.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
                "2024-03-05": 102.0,
            },
        },
    )
    plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
    )
    pipeline = StubPipeline(
        post_market_plans=[plan, ExecutionPlan(date="20240304", portfolio_snapshot={})],
        intraday_responses=[(plan.buy_orders, [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )

    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=pipeline,
    )

    engine.run_backtest()

    snapshot = engine._portfolio.get_snapshot()
    assert snapshot["positions"]["AAPL"]["long"] == 100
    assert pipeline.post_market_calls[0][0] == "20240301"
    assert pipeline.pre_market_calls[0][0] == "20240304"
    assert pipeline.intraday_calls[0][0] == "20240304"


def test_pipeline_mode_crisis_reduce_trims_existing_position(monkeypatch):
    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
                "2024-03-05": 12.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
                "2024-03-05": 102.0,
            },
        },
    )
    empty_plan = ExecutionPlan(date="20240301", portfolio_snapshot={"cash": 98000.0, "positions": {}})
    pipeline = StubPipeline(
        post_market_plans=[empty_plan, ExecutionPlan(date="20240304", portfolio_snapshot={})],
        intraday_responses=[([], [], {"pause_new_buys": True, "forced_reduce_ratio": 0.5})],
    )

    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=pipeline,
    )
    engine._portfolio.apply_long_buy("AAPL", 200, 10.0)

    engine.run_backtest()

    snapshot = engine._portfolio.get_snapshot()
    assert snapshot["positions"]["AAPL"]["long"] == 100
