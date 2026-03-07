import pytest

from src.backtesting.walk_forward import build_walk_forward_windows, run_walk_forward, summarize_walk_forward


def test_build_walk_forward_windows_generates_rolling_ranges():
    windows = build_walk_forward_windows(
        "2026-01-01",
        "2026-06-30",
        train_months=2,
        test_months=1,
        step_months=1,
    )

    assert len(windows) == 4
    assert windows[0].train_start == "2026-01-01"
    assert windows[0].train_end == "2026-02-28"
    assert windows[0].test_start == "2026-03-01"
    assert windows[0].test_end == "2026-03-31"
    assert windows[-1].test_end == "2026-06-30"


def test_build_walk_forward_windows_rejects_non_positive_lengths():
    with pytest.raises(ValueError):
        build_walk_forward_windows("2026-01-01", "2026-06-30", train_months=0)


def test_run_and_summarize_walk_forward():
    windows = build_walk_forward_windows(
        "2026-01-01",
        "2026-04-30",
        train_months=1,
        test_months=1,
        step_months=1,
    )

    class StubEngine:
        def __init__(self, sharpe: float, sortino: float, max_drawdown: float):
            self._metrics = {
                "sharpe_ratio": sharpe,
                "sortino_ratio": sortino,
                "max_drawdown": max_drawdown,
            }

        def run_backtest(self):
            return self._metrics

    results = run_walk_forward(
        windows,
        lambda window: StubEngine(
            sharpe=float(window.test_start[-2:]),
            sortino=float(window.test_end[-2:]),
            max_drawdown=-10.0,
        ),
    )
    summary = summarize_walk_forward(results)

    assert summary["window_count"] == len(windows)
    assert summary["avg_sharpe"] is not None
    assert summary["avg_sortino"] is not None
    assert summary["avg_max_drawdown"] == -10.0
