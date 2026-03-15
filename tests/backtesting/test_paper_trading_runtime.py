from __future__ import annotations

import json

import pandas as pd

from src.execution.models import ExecutionPlan
from src.paper_trading.runtime import run_paper_trading_session
from src.portfolio.models import PositionPlan


class StubPipeline:
    def __init__(self, post_market_plans, intraday_responses):
        self.post_market_plans = list(post_market_plans)
        self.intraday_responses = list(intraday_responses)

    def run_post_market(self, trade_date: str, portfolio_snapshot: dict | None = None) -> ExecutionPlan:
        if self.post_market_plans:
            return self.post_market_plans.pop(0)
        return ExecutionPlan(date=trade_date, portfolio_snapshot=portfolio_snapshot or {})

    def run_pre_market(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs) -> ExecutionPlan:
        return plan

    def run_intraday(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs):
        if self.intraday_responses:
            return self.intraday_responses.pop(0)
        return [], [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0}


def _patch_market_data(monkeypatch, closes_by_ticker: dict[str, dict[str, float]]) -> None:
    monkeypatch.setattr("src.backtesting.engine.get_prices", lambda *a, **k: None)
    monkeypatch.setattr("src.backtesting.engine.get_financial_metrics", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.engine.get_insider_trades", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.engine.get_company_news", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.output.print_backtest_results", lambda *a, **k: None)
    monkeypatch.setattr("src.backtesting.engine.get_limit_list", lambda *a, **k: None)

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


def test_run_paper_trading_session_writes_artifacts(tmp_path, monkeypatch):
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
        risk_metrics={"counts": {"watchlist_count": 1}},
    )
    pipeline = StubPipeline(
        post_market_plans=[plan, ExecutionPlan(date="20240304", portfolio_snapshot={})],
        intraday_responses=[(plan.buy_orders, [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )

    artifacts = run_paper_trading_session(
        start_date="2024-03-01",
        end_date="2024-03-05",
        output_dir=tmp_path / "paper_trading",
        tickers=["AAPL"],
        model_name="test-model",
        model_provider="test-provider",
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        pipeline=pipeline,
    )

    assert artifacts.daily_events_path.exists()
    assert artifacts.timing_log_path.exists()
    assert artifacts.summary_path.exists()

    lines = [json.loads(line) for line in artifacts.daily_events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    assert lines[0]["event"] == "paper_trading_day"
    assert "current_plan" in lines[0]

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["mode"] == "paper_trading"
    assert summary["daily_event_stats"]["day_count"] >= 1
    assert summary["artifacts"]["summary"] == str(artifacts.summary_path)