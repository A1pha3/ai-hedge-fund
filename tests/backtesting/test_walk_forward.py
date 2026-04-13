import pytest
import pandas as pd

from src.backtesting.walk_forward import WindowMode, build_walk_forward_windows, run_walk_forward, summarize_walk_forward


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


def test_build_walk_forward_windows_truncates_test_range_to_max_trading_days(monkeypatch):
    class StubPro:
        @staticmethod
        def trade_cal(**kwargs):
            return pd.DataFrame({"cal_date": ["20260302", "20260303", "20260304", "20260305", "20260306", "20260309"]})

    monkeypatch.setattr("src.backtesting.walk_forward._get_pro", lambda: StubPro())

    windows = build_walk_forward_windows(
        "2026-01-01",
        "2026-03-31",
        train_months=2,
        test_months=1,
        step_months=1,
        max_test_trading_days=5,
    )

    assert len(windows) == 1
    assert windows[0].test_start == "2026-03-01"
    assert windows[0].test_end == "2026-03-06"


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


def test_expanding_window_anchors_train_start():
    windows = build_walk_forward_windows(
        "2026-01-01",
        "2026-09-30",
        train_months=2,
        test_months=1,
        step_months=1,
        window_mode=WindowMode.EXPANDING,
    )

    assert len(windows) >= 2
    for w in windows:
        assert w.train_start == "2026-01-01", "expanding mode should anchor train_start at overall start"

    assert windows[0].train_end == "2026-02-28"
    assert windows[0].test_start == "2026-03-01"
    assert windows[0].test_end == "2026-03-31"

    assert windows[1].train_end == "2026-03-31"
    assert windows[1].test_start == "2026-04-01"
    assert windows[1].test_end == "2026-04-30"


def test_expanding_window_train_grows_each_step():
    windows = build_walk_forward_windows(
        "2026-01-01",
        "2026-06-30",
        train_months=1,
        test_months=1,
        step_months=1,
        window_mode=WindowMode.EXPANDING,
    )

    train_end_dates = [w.train_end for w in windows]
    for i in range(1, len(train_end_dates)):
        assert train_end_dates[i] > train_end_dates[i - 1], "expanding train_end should grow monotonically"

    for w in windows:
        assert w.train_start == "2026-01-01"
