"""Tests for ``scripts/run_backtest_param_grid.py`` CLI wrapper.

These tests exercise the CLI surface in isolation: the underlying backtest
engine is replaced with a stub that returns deterministic metrics, so the
integration can run without network / LLM access.  The goal is to validate
the *plumbing* — argument parsing, output paths, evaluator wiring — not
the inner backtest semantics (those are covered by
``tests/backtesting/test_param_grid.py``).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

# Load the script as a module.  Going through importlib lets us monkeypatch
# the heavy ``BacktestEngine`` / ``run_hedge_fund`` imports cleanly.
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_backtest_param_grid.py"
_spec = importlib.util.spec_from_file_location("run_backtest_param_grid", _SCRIPT_PATH)
assert _spec and _spec.loader, f"could not load spec for {_SCRIPT_PATH}"
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_engine_factory():
    """Return ``(FakeEngine, captured)`` where ``captured`` records kwargs."""

    class FakeEngine:
        last_kwargs: dict | None = None

        def __init__(self, **kwargs):
            FakeEngine.last_kwargs = kwargs
            # Different kwargs -> different metrics so we can verify the
            # grid was actually swept.
            capital = float(kwargs.get("initial_capital", 100_000))
            FakeEngine.last_kwargs = kwargs
            self._sharpe = 0.5 + (capital - 100_000) / 1_000_000

        def run_backtest(self):
            return {
                "sharpe_ratio": self._sharpe,
                "sortino_ratio": self._sharpe * 2,
                "max_drawdown": -0.05,
                "win_rate": 0.55,
            }

        def get_portfolio_values(self):
            return [
                {"Portfolio Value": 100_000.0},
                {"Portfolio Value": 110_000.0},
            ]

    return FakeEngine


def _base_argv(tmp_path: Path) -> list[str]:
    return [
        "--tickers",
        "AAPL,MSFT",
        "--start-date",
        "2026-01-01",
        "--end-date",
        "2026-04-30",
        "--model-name",
        "gpt-test",
        "--model-provider",
        "openai",
        "--param-grid",
        "initial_capital=100000,200000",
        "--output",
        str(tmp_path / "out"),
        "--quiet",
    ]


@pytest.fixture()
def stub_engine(monkeypatch):
    FakeEngine = _stub_engine_factory()

    # Patch the symbol that the script imported at module load time so the
    # closure picks up our stub.
    monkeypatch.setattr(_module, "BacktestEngine", FakeEngine)
    # run_hedge_fund is looked up lazily inside the evaluator; provide a
    # benign sentinel.
    fake_main = ModuleType("src.main")
    fake_main.run_hedge_fund = lambda **kwargs: {}
    monkeypatch.setitem(sys.modules, "src.main", fake_main)
    return FakeEngine


# ---------------------------------------------------------------------------
# Argument parsing & entry point
# ---------------------------------------------------------------------------


def test_build_parser_requires_param_grid():
    parser = _module.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--tickers", "AAPL"])


def test_build_parser_accepts_minimal_valid_argv(tmp_path: Path):
    parser = _module.build_parser()
    args = parser.parse_args(_base_argv(tmp_path))
    assert args.param_grid == "initial_capital=100000,200000"
    assert args.tickers == "AAPL,MSFT"
    assert args.max_workers is None
    assert args.sort_by == "sharpe_ratio"


def test_main_returns_zero_on_success(tmp_path: Path, stub_engine, capsys):
    argv = _base_argv(tmp_path)
    rc = _module.main(argv)
    captured = capsys.readouterr()
    # Summary line + path list are always printed (the table is suppressed
    # by --quiet in _base_argv).
    assert "Completed" in captured.out
    assert "CSV report" in captured.out
    assert "MD report" in captured.out
    assert "JSON report" in captured.out
    assert rc == 0


def test_main_emits_three_artefacts(tmp_path: Path, stub_engine):
    _module.main(_base_argv(tmp_path))
    output_dir = tmp_path / "out"
    assert output_dir.is_dir()
    files = sorted(p.name for p in output_dir.iterdir())
    # One CSV, one MD, one JSON.
    assert sum(name.endswith(".csv") for name in files) == 1
    assert sum(name.endswith(".md") for name in files) == 1
    assert sum(name.endswith(".json") for name in files) == 1


def test_main_uses_engine_per_trial(tmp_path: Path, stub_engine, monkeypatch):
    """Every grid combination must instantiate a fresh BacktestEngine."""
    instances: list[dict] = []

    real_init = stub_engine.__init__

    def _spy(self, **kwargs):
        instances.append(kwargs)
        real_init(self, **kwargs)

    monkeypatch.setattr(stub_engine, "__init__", _spy)
    _module.main(_base_argv(tmp_path))

    # 2 combinations -> 2 engines
    assert len(instances) == 2
    capitals = sorted({kwargs["initial_capital"] for kwargs in instances})
    assert capitals == [100_000.0, 200_000.0]


def test_main_returns_nonzero_when_a_trial_fails(tmp_path: Path, stub_engine, monkeypatch):
    class FlakyEngine(stub_engine):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            if float(kwargs.get("initial_capital", 0)) >= 200_000:
                self._sharpe = 0.0  # irrelevant; we will override run_backtest

        def run_backtest(self):
            if self.last_kwargs and float(self.last_kwargs.get("initial_capital", 0)) >= 200_000:
                raise RuntimeError("LLM provider rate limit")
            return super().run_backtest()

    monkeypatch.setattr(_module, "BacktestEngine", FlakyEngine)
    rc = _module.main(_base_argv(tmp_path))
    assert rc == 1


def test_main_invalid_param_grid_returns_parser_error(tmp_path: Path, stub_engine, capsys):
    argv = _base_argv(tmp_path)
    # Replace the grid spec with a malformed value
    argv[argv.index("--param-grid") + 1] = "this_is_not_a_grid"
    with pytest.raises(SystemExit) as exc_info:
        _module.main(argv)
    # argparse calls sys.exit(2) on error
    assert exc_info.value.code == 2


def test_main_prints_console_table_when_not_quiet(tmp_path: Path, stub_engine, capsys):
    argv = _base_argv(tmp_path)
    argv.remove("--quiet")
    _module.main(argv)
    captured = capsys.readouterr()
    # Console table separator pattern from the renderer.
    assert "-+-" in captured.out
    # Header line includes the metric column.
    assert "sharpe_ratio" in captured.out


def test_main_total_return_appears_in_csv(tmp_path: Path, stub_engine):
    _module.main(_base_argv(tmp_path))
    output_dir = tmp_path / "out"
    csv_path = next(p for p in output_dir.iterdir() if p.suffix == ".csv")
    csv_text = csv_path.read_text(encoding="utf-8")
    # total_return column must be present and populated for both trials.
    assert "total_return" in csv_text
    # Both engine runs produced a 10% gain.
    assert csv_text.count("0.1000") >= 2


def test_main_walk_forward_path_invokes_summarizer(tmp_path: Path, stub_engine, monkeypatch):
    """When --walk-forward is set, the evaluator must take the walk-forward path."""
    from src.backtesting import walk_forward as wf

    monkeypatch.setattr(_module, "BacktestEngine", stub_engine)

    captured: dict = {}

    def fake_windows(*args, **kwargs):
        captured["windows"] = True
        return []

    def fake_run_wf(windows, factory):
        captured["ran"] = True
        return []

    def fake_summarize(results):
        captured["summarized"] = True
        return {
            "avg_sharpe": 0.42,
            "avg_sortino": 0.84,
            "avg_max_drawdown": -0.10,
            "window_count": 3,
        }

    monkeypatch.setattr(wf, "build_walk_forward_windows", fake_windows)
    monkeypatch.setattr(wf, "run_walk_forward", fake_run_wf)
    monkeypatch.setattr(wf, "summarize_walk_forward", fake_summarize)

    argv = _base_argv(tmp_path) + ["--walk-forward", "--walk-forward-preset", "fast"]
    rc = _module.main(argv)
    assert rc == 0
    assert captured == {"windows": True, "ran": True, "summarized": True}


# ---------------------------------------------------------------------------
# Direct helpers
# ---------------------------------------------------------------------------


def test_resolve_analysts_returns_none_when_flag_omitted():
    args = SimpleNamespace(analysts=None)
    assert _module._resolve_analysts(args) is None


def test_resolve_analysts_splits_and_strips_csv():
    args = SimpleNamespace(analysts=" news_agent , fundamentals_agent ,")
    assert _module._resolve_analysts(args) == ["news_agent", "fundamentals_agent"]


def test_compute_total_return_handles_empty_curve(caplog):
    with caplog.at_level("DEBUG", logger=_module.logger.name):
        assert _module._compute_total_return([], _module.logger) is None


def test_compute_total_return_handles_missing_keys(caplog):
    curve = [{"Date": "2026-01-01"}]  # no Portfolio Value
    assert _module._compute_total_return(curve, _module.logger) is None


def test_compute_total_return_handles_non_positive_start():
    curve = [{"Portfolio Value": 0.0}, {"Portfolio Value": 1.0}]
    assert _module._compute_total_return(curve, _module.logger) is None


def test_compute_total_return_computes_fraction():
    curve = [{"Portfolio Value": 100.0}, {"Portfolio Value": 110.0}, {"Portfolio Value": 121.0}]
    assert _module._compute_total_return(curve, _module.logger) == pytest.approx(0.21)


def test_make_evaluator_raises_for_unsupported_grid_dimension(tmp_path: Path, stub_engine):
    """A grid key outside the whitelist must fail loudly inside the worker."""
    parser = _module.build_parser()
    argv = _base_argv(tmp_path)
    # Replace the grid spec with one that contains an unsupported key.
    argv[argv.index("--param-grid") + 1] = "tickers=FOO,BAR"
    args = parser.parse_args(argv)
    evaluator = _module.make_evaluator(args)
    with pytest.raises(Exception) as exc_info:
        evaluator({"tickers": "FOO,BAR"})
    # The error class may be ParamGridError, ValueError, or a wrapper
    # raised inside the worker; the key is that "tickers" is mentioned
    # somewhere in the error chain.
    assert "tickers" in str(exc_info.value)


def test_make_evaluator_quietly_drops_baseline_keys_in_agent_mode(tmp_path: Path, stub_engine):
    """In agent mode, baseline_* keys should be ignored (no error)."""
    parser = _module.build_parser()
    argv = _base_argv(tmp_path)
    argv[argv.index("--param-grid") + 1] = "baseline_pct_threshold=2.0,3.0"
    args = parser.parse_args(argv)
    evaluator = _module.make_evaluator(args)
    # No exception: in agent mode the baseline_* keys are dropped.
    metrics = evaluator({"baseline_pct_threshold": 3.0})
    assert "sharpe_ratio" in metrics
