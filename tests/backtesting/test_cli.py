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
        # New param-grid flags (5.5) — None so we don't take the grid branch.
        param_grid=None,
        output=None,
        max_workers=None,
        sort_by="sharpe_ratio",
        walk_forward_preset=None,
        window_mode="rolling",
    )

    monkeypatch.setattr(cli, "build_backtest_parser", lambda: _ParserStub(args))
    monkeypatch.setattr(cli, "init", lambda **kwargs: None)
    monkeypatch.setattr(cli, "print_default_model", lambda: print("default_model_provider=openai\ndefault_model_name=gpt-default"))

    assert cli.main() == 0

    captured = capsys.readouterr()
    assert captured.out == "default_model_provider=openai\ndefault_model_name=gpt-default\n"


def test_positive_float_rejects_zero_and_negative():
    """R81: --initial-capital 必须为正数, 0/负数会触发 divide-by-zero in metrics."""
    import argparse

    from src.backtesting.cli_helpers import _positive_float

    # Valid positive value passes through unchanged.
    assert _positive_float("100000") == 100000.0
    assert _positive_float("0.01") == 0.01
    # Zero and negative raise ArgumentTypeError (argparse converts to exit + stderr).
    for bad in ("0", "0.0", "-1", "-100000", "-0.5"):
        try:
            _positive_float(bad)
            assert False, f"expected ArgumentTypeError for {bad!r}"
        except argparse.ArgumentTypeError:
            pass


def test_non_negative_float_rejects_negative_margin():
    """R82: --margin-requirement 必须为非负数, 负值会让保证金风控失效
    (margin_required<=cash 恒为 True, portfolio short unlimited notional).
    0 合法 (upstream default), > 1.0 合法 (over-collateralized)."""
    import argparse

    from src.backtesting.cli_helpers import _non_negative_float

    # 0 and positive (incl > 1.0) pass through.
    assert _non_negative_float("0") == 0.0
    assert _non_negative_float("0.5") == 0.5
    assert _non_negative_float("1.5") == 1.5
    # Negative raises ArgumentTypeError.
    for bad in ("-0.001", "-1", "-0.5"):
        try:
            _non_negative_float(bad)
            assert False, f"expected ArgumentTypeError for {bad!r}"
        except argparse.ArgumentTypeError:
            pass


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
        # New param-grid flags (5.5) — None so we don't take the grid branch.
        param_grid=None,
        output=None,
        max_workers=None,
        sort_by="sharpe_ratio",
        walk_forward_preset=None,
        window_mode="rolling",
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
    assert captured.out == ("\nSelected \x1b[36mopenai\x1b[0m model: \x1b[32m\x1b[1mgpt-test\x1b[0m\n\n" "\n\x1b[37m\x1b[1mENGINE RUN COMPLETE\x1b[0m\n" "Total Return: \x1b[32m5.00%\x1b[0m\n" "Sharpe: 1.20\n" "Sortino: 1.50\n" "Max DD: 3.50%\n")


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
    # Finance-quant gamma lens: backtest performance output must carry an inline
    # risk disclaimer so Sharpe/drawdown are not read as predictive guarantees.
    assert "不代表未来" in captured.out


# ---------------------------------------------------------------------------
# 5.5 — --param-grid dispatch
# ---------------------------------------------------------------------------


def test_main_dispatches_to_param_grid_runner(monkeypatch, tmp_path):
    """When --param-grid is set, main() must delegate to the grid runner."""
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
        analysts=None,
        analysts_all=False,
        ollama=False,
        param_grid="top_n=10,20",
        output=str(tmp_path / "out"),
        max_workers=1,
        sort_by="sharpe_ratio",
        walk_forward_preset=None,
        window_mode="rolling",
    )

    captured_argv: list[list[str]] = []

    def fake_grid_main(argv):
        captured_argv.append(list(argv))
        return 0

    # Replace the symbol inside the already-imported scripts module; the
    # dispatch in cli._run_param_grid_mode imports it lazily each call, so
    # mutating the module is sufficient.
    from scripts import run_backtest_param_grid as grid_module

    monkeypatch.setattr(grid_module, "main", fake_grid_main)

    monkeypatch.setattr(cli, "build_backtest_parser", lambda: _ParserStub(args))
    monkeypatch.setattr(cli, "init", lambda **kwargs: None)
    monkeypatch.setattr(cli, "resolve_selected_analysts", lambda args, logger: [])
    monkeypatch.setattr(cli, "resolve_model_selection", lambda args, logger: SimpleNamespace(name="gpt-test", provider="openai"))

    assert cli.main() == 0
    assert len(captured_argv) == 1, "grid main was not invoked exactly once"
    argv = captured_argv[0]
    # Critical flags must round-trip
    assert "--param-grid" in argv
    assert "top_n=10,20" in argv
    assert "--model-name" in argv and "gpt-test" in argv
    assert "--output" in argv and str(tmp_path / "out") in argv
    # Tickers are joined with comma
    assert "--tickers" in argv and "AAPL,MSFT" in argv


def test_run_param_grid_mode_requires_tickers():
    """The grid runner must fail loudly when --tickers is missing."""
    args = SimpleNamespace(
        tickers=None,
        start_date="2026-01-01",
        end_date="2026-04-30",
        initial_capital=100000.0,
        margin_requirement=0.0,
        mode="agent",
        model_name="gpt",
        model_provider="openai",
        walk_forward=False,
        walk_forward_preset=None,
        train_months=2,
        test_months=1,
        step_months=1,
        max_test_trading_days=None,
        window_mode="rolling",
        analysts=None,
        param_grid="top_n=10",
        output=None,
        max_workers=None,
        sort_by="sharpe_ratio",
    )
    # Without a model selection we can short-circuit the runner call entirely.
    rc = cli._run_param_grid_mode(args, SimpleNamespace(name="gpt", provider="openai"))
    assert rc == 1
