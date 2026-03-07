from src.backtesting.compare import ABWindowMetrics, BaselineDailyGainersPipeline, build_ab_comparison_payload, format_ab_comparison_report, make_backtest_agent_runner, run_ab_comparison_walk_forward
from src.backtesting.walk_forward import WalkForwardWindow
from src.screening.models import MarketState, MarketStateType


def test_baseline_daily_gainers_pipeline(monkeypatch):
    monkeypatch.setattr(
        "src.backtesting.compare.get_ashare_daily_gainers_with_tushare",
        lambda trade_date, pct_threshold, include_name: [
            {"ts_code": "000001.SZ", "name": "平安银行"},
            {"ts_code": "000002.SZ", "name": "万科A"},
        ],
    )
    monkeypatch.setattr(
        "src.backtesting.compare.detect_market_state",
        lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}),
    )

    calls = []

    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        calls.append((tickers, model))
        return {
            "aswath_damodaran_agent": {ticker: {"signal": "bullish", "confidence": 80, "reasoning": "ok"} for ticker in tickers},
        }

    pipeline = BaselineDailyGainersPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], top_n=1)
    plan = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 500000, "positions": {}})

    assert plan.layer_a_count == 1
    assert plan.layer_b_count == 0
    assert len(plan.watchlist) == 1
    assert calls == [(["000001"], "precise")]


def test_run_ab_comparison_walk_forward(monkeypatch):
    windows = [WalkForwardWindow(train_start="2026-01-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31")]
    monkeypatch.setattr("src.backtesting.compare.build_walk_forward_windows", lambda *args, **kwargs: windows)

    class StubEngine:
        def __init__(self, **kwargs):
            self.pipeline = kwargs["pipeline"]

        def run_backtest(self):
            if isinstance(self.pipeline, BaselineDailyGainersPipeline):
                return {"sharpe_ratio": 0.8, "sortino_ratio": 1.1, "max_drawdown": -9.0}
            return {"sharpe_ratio": 1.2, "sortino_ratio": 1.6, "max_drawdown": -7.0}

    monkeypatch.setattr("src.backtesting.compare.BacktestEngine", StubEngine)

    results, summary = run_ab_comparison_walk_forward(
        tickers=["000001"],
        start_date="2026-01-01",
        end_date="2026-04-30",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
    )

    assert len(results) == 1
    assert summary["baseline_avg_sortino"] == 1.1
    assert summary["mvp_avg_sortino"] == 1.6
    assert summary["avg_sortino_delta"] == 0.5


def test_make_backtest_agent_runner_uses_explicit_model():
    calls = []

    def fake_agent(**kwargs):
        calls.append(kwargs)
        return {"analyst_signals": {"agent": {"000001": {"signal": "bullish", "confidence": 80, "reasoning": "ok"}}}}

    runner = make_backtest_agent_runner(fake_agent, model_name="gpt-4.1-mini", model_provider="OpenAI")
    result = runner(["000001"], "20260305", "fast")

    assert "agent" in result
    assert calls[0]["model_name"] == "gpt-4.1-mini"
    assert calls[0]["model_provider"] == "OpenAI"
    assert calls[0]["start_date"] == "2025-03-05"
    assert calls[0]["end_date"] == "2026-03-05"


def test_format_ab_comparison_report():
    results = [
        ABWindowMetrics(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31"),
            baseline={"sharpe_ratio": 0.8, "sortino_ratio": 1.1, "max_drawdown": -9.0},
            mvp={"sharpe_ratio": 1.2, "sortino_ratio": 1.6, "max_drawdown": -7.0},
        )
    ]
    report = format_ab_comparison_report(
        results,
        {
            "window_count": 1,
            "baseline_avg_sharpe": 0.8,
            "baseline_avg_sortino": 1.1,
            "mvp_avg_sharpe": 1.2,
            "mvp_avg_sortino": 1.6,
            "avg_sortino_delta": 0.5,
            "sortino_p_value_estimate": None,
        },
    )

    assert "A/B Walk-Forward Comparison" in report
    assert "2026-03-01..2026-03-31" in report
    assert "MVP Avg Sortino: 1.60" in report


def test_build_ab_comparison_payload():
    results = [
        ABWindowMetrics(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31"),
            baseline={"sharpe_ratio": 0.8, "sortino_ratio": 1.1},
            mvp={"sharpe_ratio": 1.2, "sortino_ratio": 1.6},
        )
    ]
    payload = build_ab_comparison_payload(results, {"window_count": 1, "mvp_avg_sortino": 1.6})

    assert payload["summary"]["window_count"] == 1
    assert payload["windows"][0]["window"]["test_start"] == "2026-03-01"
    assert payload["windows"][0]["mvp"]["sortino_ratio"] == 1.6
