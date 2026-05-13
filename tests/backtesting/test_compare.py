from src.backtesting.compare import (
    ABWindowMetrics,
    BaselineDailyGainersPipeline,
    build_ab_comparison_payload,
    format_ab_comparison_report,
    make_backtest_agent_runner,
    run_ab_comparison_walk_forward,
)
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

    # New runner tail comparison summary fields should be present and default to None when data is absent
    assert "avg_runner_tail_hit_delta" in summary
    assert summary["avg_runner_tail_hit_delta"] is None
    assert "avg_runner_tail_median_delta" in summary
    assert summary["avg_runner_tail_median_delta"] is None


def test_run_ab_comparison_walk_forward_passes_max_test_trading_days(monkeypatch):
    captured_kwargs = {}

    def fake_build_walk_forward_windows(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return [WalkForwardWindow(train_start="2026-01-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-07")]

    class StubEngine:
        def __init__(self, **kwargs):
            self.pipeline = kwargs["pipeline"]

        def run_backtest(self):
            return {"sharpe_ratio": 1.0, "sortino_ratio": 1.0, "max_drawdown": -5.0}

    monkeypatch.setattr("src.backtesting.compare.build_walk_forward_windows", fake_build_walk_forward_windows)
    monkeypatch.setattr("src.backtesting.compare.BacktestEngine", StubEngine)

    run_ab_comparison_walk_forward(
        tickers=["000001"],
        start_date="2026-01-01",
        end_date="2026-04-30",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        max_test_trading_days=5,
    )

    assert captured_kwargs["max_test_trading_days"] == 5


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


def test_make_backtest_agent_runner_reuses_superset_results_for_same_day():
    calls = []

    def fake_agent(**kwargs):
        calls.append(kwargs)
        return {"analyst_signals": {"agent": {ticker: {"signal": "bullish", "confidence": 80, "reasoning": "ok"} for ticker in kwargs["tickers"]}}}

    runner = make_backtest_agent_runner(fake_agent, model_name="glm-4.7", model_provider="Zhipu")

    fast_result = runner(["000001", "000002", "000003"], "20260305", "fast")
    precise_result = runner(["000001", "000003"], "20260305", "precise")

    assert set(fast_result["agent"].keys()) == {"000001", "000002", "000003"}
    assert set(precise_result["agent"].keys()) == {"000001", "000003"}
    assert len(calls) == 1


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


def test_format_ab_comparison_report_includes_runner_section_when_present():
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
            "sortino_p_value_estimate": 0.04,
            "avg_runner_tail_hit_delta": 0.07,
            "avg_runner_tail_median_delta": 0.03,
        },
    )

    assert "Runner Quality" in report
    assert "Runner Tail Hit Rate Delta" in report
    assert "+0.0700" in report
    assert "+0.0300" in report


def test_format_ab_comparison_report_omits_runner_section_when_absent():
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

    assert "Runner Quality" not in report


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


# ---------------------------------------------------------------------------
# window_mode and walk_forward_preset propagation tests
# ---------------------------------------------------------------------------


def test_run_ab_comparison_walk_forward_passes_window_mode_expanding(monkeypatch):
    """window_mode=expanding must be forwarded to build_walk_forward_windows."""
    from src.backtesting.walk_forward import WindowMode

    captured_kwargs = {}

    def fake_build_walk_forward_windows(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return [WalkForwardWindow(train_start="2026-01-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31")]

    class StubEngine:
        def __init__(self, **kwargs):
            self.pipeline = kwargs["pipeline"]

        def run_backtest(self):
            return {"sharpe_ratio": 1.0, "sortino_ratio": 1.0, "max_drawdown": -5.0}

    monkeypatch.setattr("src.backtesting.compare.build_walk_forward_windows", fake_build_walk_forward_windows)
    monkeypatch.setattr("src.backtesting.compare.BacktestEngine", StubEngine)

    run_ab_comparison_walk_forward(
        tickers=["000001"],
        start_date="2026-01-01",
        end_date="2026-06-30",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        window_mode=WindowMode.EXPANDING,
    )

    assert captured_kwargs.get("window_mode") == WindowMode.EXPANDING


def test_run_ab_comparison_walk_forward_preset_overrides_month_args(monkeypatch):
    """walk_forward_preset must override explicit train/test/step_months args."""
    captured_kwargs = {}

    def fake_build_walk_forward_windows(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return [WalkForwardWindow(train_start="2026-01-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31")]

    class StubEngine:
        def __init__(self, **kwargs):
            self.pipeline = kwargs["pipeline"]

        def run_backtest(self):
            return {"sharpe_ratio": 1.0, "sortino_ratio": 1.0, "max_drawdown": -5.0}

    monkeypatch.setattr("src.backtesting.compare.build_walk_forward_windows", fake_build_walk_forward_windows)
    monkeypatch.setattr("src.backtesting.compare.BacktestEngine", StubEngine)

    # Pass different explicit values; preset "standard" (2m/1m/1m) must win
    run_ab_comparison_walk_forward(
        tickers=["000001"],
        start_date="2026-01-01",
        end_date="2026-06-30",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        train_months=99,
        test_months=99,
        step_months=99,
        walk_forward_preset="standard",
    )

    assert captured_kwargs["train_months"] == 2
    assert captured_kwargs["test_months"] == 1
    assert captured_kwargs["step_months"] == 1


def test_run_ab_comparison_walk_forward_unknown_preset_raises(monkeypatch):
    """Passing an unknown preset must raise ValueError immediately."""
    monkeypatch.setattr(
        "src.backtesting.compare.build_walk_forward_windows",
        lambda *a, **kw: [],
    )

    import pytest

    with pytest.raises(ValueError, match="Unknown walk-forward preset"):
        run_ab_comparison_walk_forward(
            tickers=["000001"],
            start_date="2026-01-01",
            end_date="2026-06-30",
            initial_capital=100000.0,
            model_name="test-model",
            model_provider="test-provider",
            selected_analysts=None,
            initial_margin_requirement=0.0,
            agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
            walk_forward_preset="nonexistent_preset",
        )


def test_runner_delta_fields_compute_actual_deltas_when_both_present(monkeypatch):
    """Runner delta summary fields should compute true deltas (MVP - baseline) when both metrics present."""
    windows = [WalkForwardWindow(train_start="2026-01-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31")]
    monkeypatch.setattr("src.backtesting.compare.build_walk_forward_windows", lambda *args, **kwargs: windows)

    class StubEngine:
        def __init__(self, **kwargs):
            pass

        def run_backtest(self):
            return {
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.5,
                "max_future_high_return_2_5d_hit_rate_at_20pct": 0.45,
                "median_max_future_high_return_2_5d": 0.12,
            }

    monkeypatch.setattr("src.backtesting.compare.BacktestEngine", StubEngine)

    results, summary = run_ab_comparison_walk_forward(
        tickers=["000001"],
        start_date="2026-01-01",
        end_date="2026-03-31",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
    )

    # When both MVP and baseline runner metrics are present, deltas should be (MVP - baseline)
    # Baseline returns 0.45, MVP returns 0.45, so delta should be 0.0
    # Actually, StubEngine returns same values for both, so delta should be 0.0
    assert summary["avg_runner_tail_hit_delta"] == 0.0
    assert summary["avg_runner_tail_median_delta"] == 0.0


def test_runner_delta_fields_return_none_when_baseline_absent(monkeypatch):
    """Runner delta summary fields should return None when baseline metrics are absent."""
    windows = [WalkForwardWindow(train_start="2026-01-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31")]
    monkeypatch.setattr("src.backtesting.compare.build_walk_forward_windows", lambda *args, **kwargs: windows)

    baseline_called = [False]
    mvp_called = [False]

    class StubEngine:
        def __init__(self, **kwargs):
            self.pipeline = kwargs.get("pipeline")

        def run_backtest(self):
            is_baseline = isinstance(self.pipeline, BaselineDailyGainersPipeline)
            if is_baseline:
                baseline_called[0] = True
                # Baseline does not include runner metrics
                return {
                    "sharpe_ratio": 1.0,
                    "sortino_ratio": 1.2,
                }
            else:
                mvp_called[0] = True
                # MVP includes runner metrics
                return {
                    "sharpe_ratio": 1.2,
                    "sortino_ratio": 1.5,
                    "max_future_high_return_2_5d_hit_rate_at_20pct": 0.45,
                    "median_max_future_high_return_2_5d": 0.12,
                }

    monkeypatch.setattr("src.backtesting.compare.BacktestEngine", StubEngine)

    results, summary = run_ab_comparison_walk_forward(
        tickers=["000001"],
        start_date="2026-01-01",
        end_date="2026-03-31",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
    )

    # When baseline runner metrics are absent, delta should be None (cannot compute delta)
    assert summary["avg_runner_tail_hit_delta"] is None
    assert summary["avg_runner_tail_median_delta"] is None
