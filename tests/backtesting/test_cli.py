from __future__ import annotations

from types import SimpleNamespace

import src.backtesting.cli as cli


class _ParserStub:
    def __init__(self, args):
        self._args = args

    def parse_args(self):
        return self._args


def test_main_prints_default_model_and_exits(monkeypatch, capsys):
    args = SimpleNamespace(
        show_default_model=True,
        tickers=None,
        end_date="2026-04-10",
        start_date="2026-03-10",
        initial_capital=100000.0,
        margin_requirement=0.0,
        mode="agent",
        walk_forward=False,
        ab_compare=False,
        train_months=2,
        test_months=1,
        step_months=1,
        max_test_trading_days=None,
        baseline_pct_threshold=3.0,
        baseline_top_n=10,
        report_file=None,
        report_json=None,
        model_name=None,
        model_provider=None,
        analysts=None,
        analysts_all=False,
        ollama=False,
    )

    monkeypatch.setattr(cli, "build_backtest_parser", lambda: _ParserStub(args))
    monkeypatch.setattr(cli, "init", lambda **kwargs: None)
    monkeypatch.setattr(cli, "print_default_model", lambda: print("default_model_provider=openai\ndefault_model_name=gpt-default"))

    assert cli.main() == 0

    captured = capsys.readouterr()
    assert captured.out == "default_model_provider=openai\ndefault_model_name=gpt-default\n"


def test_main_runs_engine_with_non_interactive_model_and_analysts(monkeypatch, capsys):
    args = SimpleNamespace(
        show_default_model=False,
        tickers="AAPL,MSFT",
        end_date="2026-04-10",
        start_date="2026-03-10",
        initial_capital=100000.0,
        margin_requirement=0.0,
        mode="agent",
        walk_forward=False,
        ab_compare=False,
        train_months=2,
        test_months=1,
        step_months=1,
        max_test_trading_days=None,
        baseline_pct_threshold=3.0,
        baseline_top_n=10,
        report_file=None,
        report_json=None,
        model_name="gpt-test",
        model_provider="openai",
        analysts="news_agent,fundamentals_agent",
        analysts_all=False,
        ollama=False,
    )

    class EngineStub:
        def run_backtest(self):
            return {"sharpe_ratio": 1.2, "sortino_ratio": 1.5, "max_drawdown": -3.5}

        def get_portfolio_values(self):
            return [{"Portfolio Value": 100000.0}, {"Portfolio Value": 105000.0}]

    engine_calls: list[dict] = []

    def fake_engine(**kwargs):
        engine_calls.append(kwargs)
        return EngineStub()

    monkeypatch.setattr(cli, "build_backtest_parser", lambda: _ParserStub(args))
    monkeypatch.setattr(cli, "init", lambda **kwargs: None)
    monkeypatch.setattr(cli, "BacktestEngine", fake_engine)
    monkeypatch.setattr(cli.logger, "info", lambda *args, **kwargs: None)

    assert cli.main() == 0
    assert engine_calls == [
        {
            "agent": cli.run_hedge_fund,
            "tickers": ["AAPL", "MSFT"],
            "start_date": "2026-03-10",
            "end_date": "2026-04-10",
            "initial_capital": 100000.0,
            "model_name": "gpt-test",
            "model_provider": "openai",
            "selected_analysts": ["news_agent", "fundamentals_agent"],
            "initial_margin_requirement": 0.0,
            "backtest_mode": "agent",
        }
    ]

    captured = capsys.readouterr()
    assert captured.out == (
        "\nSelected \x1b[36mopenai\x1b[0m model: \x1b[32m\x1b[1mgpt-test\x1b[0m\n\n"
        "\n\x1b[37m\x1b[1mENGINE RUN COMPLETE\x1b[0m\n"
        "Total Return: \x1b[32m5.00%\x1b[0m\n"
        "Sharpe: 1.20\n"
        "Sortino: 1.50\n"
        "Max DD: 3.50%\n"
    )


def test_run_walk_forward_mode_prints_rollout_and_promotion_summary(capsys):
    args = SimpleNamespace(
        start_date="2026-01-01",
        end_date="2026-04-30",
        train_months=1,
        test_months=1,
        step_months=1,
        max_test_trading_days=None,
        window_mode="rolling",
        walk_forward_preset=None,
    )
    original_build = cli.build_walk_forward_windows
    original_run = cli.run_walk_forward
    original_summary = cli.summarize_walk_forward
    try:
        cli.build_walk_forward_windows = lambda *args, **kwargs: [SimpleNamespace(test_start="2026-02-01", test_end="2026-02-28")]
        cli.run_walk_forward = lambda windows, factory: ["stub-result"]
        cli.summarize_walk_forward = lambda results: {
            "window_count": 1,
            "avg_sharpe": 0.1,
            "avg_sortino": 0.2,
            "avg_max_drawdown": -8.0,
            "positive_sharpe_window_count": 0,
            "negative_sharpe_window_count": 1,
            "zero_sharpe_window_count": 0,
            "non_positive_sharpe_window_count": 1,
            "positive_sharpe_window_ratio": 0.0,
            "worst_sharpe": -0.3,
            "worst_max_drawdown": -13.0,
            "max_non_positive_sharpe_streak": 1,
            "rollout_ready": False,
            "rollout_blockers": ["majority_non_positive_sharpe_windows"],
            "promotion_ready": False,
            "promotion_blockers": ["risk_budget_suppression_exceeded"],
        }
        assert cli._run_walk_forward_mode(args, lambda _start, _end: object()) == 0
    finally:
        cli.build_walk_forward_windows = original_build
        cli.run_walk_forward = original_run
        cli.summarize_walk_forward = original_summary

    captured = capsys.readouterr()
    assert "Rollout Ready: NO" in captured.out
    assert "Rollout Blockers: majority_non_positive_sharpe_windows" in captured.out
    assert "Promotion Ready: NO" in captured.out
    assert "Promotion Blockers: risk_budget_suppression_exceeded" in captured.out
