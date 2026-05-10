import pandas as pd
import pytest

from src.backtesting.walk_forward import (
    build_walk_forward_windows,
    run_walk_forward,
    summarize_walk_forward,
    WindowMode,
)


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


def test_summarize_walk_forward_surfaces_rollout_robustness_stats():
    class StubEngine:
        def __init__(self, metrics):
            self._metrics = metrics

        def run_backtest(self):
            return self._metrics

    windows = build_walk_forward_windows(
        "2026-01-01",
        "2026-04-30",
        train_months=1,
        test_months=1,
        step_months=1,
    )
    metrics_by_window = [
        {"sharpe_ratio": 1.2, "sortino_ratio": 1.5, "max_drawdown": -6.0},
        {"sharpe_ratio": 0.0, "sortino_ratio": 0.3, "max_drawdown": -8.0},
        {"sharpe_ratio": -0.4, "sortino_ratio": -0.2, "max_drawdown": -14.0},
    ]
    results = run_walk_forward(
        windows,
        lambda window: StubEngine(metrics_by_window[windows.index(window)]),
    )

    summary = summarize_walk_forward(results)

    assert summary["positive_sharpe_window_count"] == 1
    assert summary["negative_sharpe_window_count"] == 1
    assert summary["zero_sharpe_window_count"] == 1
    assert summary["positive_sharpe_window_ratio"] == pytest.approx(1 / 3)
    assert summary["worst_sharpe"] == pytest.approx(-0.4)
    assert summary["worst_max_drawdown"] == pytest.approx(-14.0)


def test_summarize_walk_forward_surfaces_rollout_readiness_and_streaks():
    class StubEngine:
        def __init__(self, metrics):
            self._metrics = metrics

        def run_backtest(self):
            return self._metrics

    windows = build_walk_forward_windows(
        "2026-01-01",
        "2026-05-31",
        train_months=1,
        test_months=1,
        step_months=1,
    )
    metrics_by_window = [
        {"sharpe_ratio": 1.0, "sortino_ratio": 1.3, "max_drawdown": -5.0},
        {"sharpe_ratio": 0.0, "sortino_ratio": 0.1, "max_drawdown": -8.0},
        {"sharpe_ratio": -0.2, "sortino_ratio": -0.1, "max_drawdown": -13.0},
        {"sharpe_ratio": -0.1, "sortino_ratio": -0.2, "max_drawdown": -9.0},
    ]
    results = run_walk_forward(
        windows,
        lambda window: StubEngine(metrics_by_window[windows.index(window)]),
    )

    summary = summarize_walk_forward(results)

    assert summary["non_positive_sharpe_window_count"] == 3
    assert summary["max_non_positive_sharpe_streak"] == 3
    assert summary["rollout_ready"] is False
    assert "majority_non_positive_sharpe_windows" in list(summary["rollout_blockers"] or [])
    assert "non_positive_sharpe_streak_exceeded" in list(summary["rollout_blockers"] or [])
    assert "worst_drawdown_breach" in list(summary["rollout_blockers"] or [])


def test_rollout_majority_gate_ignores_missing_sharpe_windows() -> None:
    class StubEngine:
        def __init__(self, metrics):
            self._metrics = metrics

        def run_backtest(self):
            return self._metrics

    windows = build_walk_forward_windows(
        "2026-01-01",
        "2026-06-30",
        train_months=1,
        test_months=1,
        step_months=1,
    )
    metrics_by_window = [
        {"sharpe_ratio": 1.5, "sortino_ratio": 1.2, "max_drawdown": -6.0},
        {"sharpe_ratio": 0.8, "sortino_ratio": 0.7, "max_drawdown": -7.0},
        {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": -5.0},
        {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": -4.0},
        {"sharpe_ratio": -0.3, "sortino_ratio": -0.1, "max_drawdown": -8.0},
    ]
    results = run_walk_forward(
        windows,
        lambda window: StubEngine(metrics_by_window[windows.index(window)]),
    )

    summary = summarize_walk_forward(results)

    assert summary["positive_sharpe_window_count"] == 2
    assert summary["non_positive_sharpe_window_count"] == 1
    assert summary["positive_sharpe_window_ratio"] == pytest.approx(2 / 3)
    assert "majority_non_positive_sharpe_windows" not in list(summary["rollout_blockers"] or [])


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


def test_fast_preset_has_no_tushare_dependency():
    """fast preset must not require a Tushare connection.

    The fast preset is designed as the cheapest locally-runnable window shape.
    Adding max_test_trading_days to it would silently introduce a live API
    dependency, defeating that purpose.  This test ensures the preset can
    produce windows without patching _get_pro.
    """
    from src.backtesting.walk_forward import WALK_FORWARD_PRESETS

    preset = WALK_FORWARD_PRESETS["fast"]
    assert "max_test_trading_days" not in preset, (
        "fast preset must not include max_test_trading_days; "
        "use --max-test-trading-days explicitly when Tushare is available"
    )
    windows = build_walk_forward_windows(
        "2026-01-01",
        "2026-04-30",
        **preset,
    )
    assert len(windows) >= 1
    assert windows[0].train_start == "2026-01-01"
    assert windows[0].train_end == "2026-01-31"
    assert windows[0].test_start == "2026-02-01"


def test_all_presets_have_required_month_keys():
    """Every preset must provide the three month-length keys."""
    from src.backtesting.walk_forward import WALK_FORWARD_PRESETS

    for name, preset in WALK_FORWARD_PRESETS.items():
        for key in ("train_months", "test_months", "step_months"):
            assert key in preset, f"Preset {name!r} is missing required key {key!r}"
        # Verify the preset can actually build windows without errors
        windows = build_walk_forward_windows(
            "2026-01-01",
            "2026-12-31",
            **{k: v for k, v in preset.items() if k != "max_test_trading_days"},
        )
        assert len(windows) >= 1, f"Preset {name!r} produced no windows"
