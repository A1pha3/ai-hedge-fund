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
