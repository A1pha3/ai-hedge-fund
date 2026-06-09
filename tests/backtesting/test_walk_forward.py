import pandas as pd
import pytest

from src.backtesting.walk_forward import (
    WalkForwardResult,
    WalkForwardWindow,
    build_walk_forward_windows,
    classify_runner_rollout_verdict,
    classify_win_rate_first_rollout_verdict,
    run_walk_forward,
    summarize_walk_forward,
    WindowMode,
)
from src.backtesting.promotion_gate import build_promotion_gate_summary


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


def test_build_walk_forward_windows_rejects_overlapping_tests_by_default():
    """ALPHA-005: step_months < test_months creates overlapping test windows.
    By default this raises ValueError to prevent double-counting trades."""
    with pytest.raises(ValueError, match="overlapping test windows"):
        build_walk_forward_windows(
            "2025-01-01", "2025-12-31",
            train_months=2, test_months=2, step_months=1,
        )


def test_build_walk_forward_windows_allows_overlap_when_opted_in():
    """ALPHA-005: allow_overlapping_tests=True bypasses the guard (for
    the "extended" preset and other intentional overlap scenarios)."""
    windows = build_walk_forward_windows(
        "2025-01-01", "2025-12-31",
        train_months=2, test_months=2, step_months=1,
        allow_overlapping_tests=True,
    )
    assert len(windows) > 0
    # Verify overlap: window 0 test_end >= window 1 test_start
    if len(windows) >= 2:
        w0_end = windows[0].test_end
        w1_start = windows[1].test_start
        assert w0_end >= w1_start, "Expected overlapping windows with allow_overlapping_tests=True"


def test_build_walk_forward_windows_non_overlapping_passes_validation():
    """Standard preset (step==test) should produce non-overlapping windows."""
    windows = build_walk_forward_windows(
        "2025-01-01", "2025-12-31",
        train_months=2, test_months=1, step_months=1,
    )
    assert len(windows) > 1
    for i in range(len(windows) - 1):
        assert windows[i].test_end < windows[i + 1].test_start, (
            f"Window {i} test_end ({windows[i].test_end}) must be < "
            f"window {i+1} test_start ({windows[i+1].test_start})"
        )


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


def test_run_walk_forward_preserves_engine_reported_test_trading_days():
    windows = [
        WalkForwardWindow(
            train_start="2026-01-01",
            train_end="2026-01-31",
            test_start="2026-02-01",
            test_end="2026-02-28",
        )
    ]

    class StubEngine:
        def run_backtest(self):
            return {"sharpe_ratio": 0.6, "sortino_ratio": 0.7, "max_drawdown": -4.0, "test_trading_days": 4}

    results = run_walk_forward(windows, lambda window: StubEngine())
    summary = summarize_walk_forward(results)

    assert results[0].metrics["test_trading_days"] == 4
    assert summary["rollout_ready"] is False
    assert "test_window_too_short" in summary["rollout_blockers"]


def test_run_walk_forward_injects_trade_calendar_test_trading_days_when_available(monkeypatch):
    monkeypatch.setattr("src.backtesting.walk_forward._get_pro", lambda: object())
    monkeypatch.setattr(
        "src.backtesting.walk_forward._cached_tushare_dataframe_call",
        lambda *args, **kwargs: pd.DataFrame({"cal_date": ["20260506", "20260507", "20260508", "20260509"]}),
    )

    windows = [
        WalkForwardWindow(
            train_start="2026-04-01",
            train_end="2026-04-30",
            test_start="2026-05-01",
            test_end="2026-05-08",
        )
    ]

    class StubEngine:
        def run_backtest(self):
            return {"sharpe_ratio": 0.6, "sortino_ratio": 0.7, "max_drawdown": -4.0}

    results = run_walk_forward(windows, lambda window: StubEngine())
    summary = summarize_walk_forward(results)

    assert results[0].metrics["test_trading_days"] == 4
    assert summary["rollout_ready"] is False
    assert "test_window_too_short" in summary["rollout_blockers"]


def test_build_promotion_gate_summary_adds_risk_budget_blocker():
    summary = build_promotion_gate_summary(
        walk_forward_summary={"rollout_ready": True, "rollout_blockers": []},
        risk_budget_summary={
            "mode": "enforce",
            "suppressed_position_summary": {"zero_budget_count": 3, "reduced_budget_count": 2},
            "formal_exposure_distribution": {"zero_budget": 3, "reduced": 2},
            "max_projected_theme_exposure": 0.36,
            "max_incremental_theme_exposure": 0.14,
        },
    )

    assert summary["promotion_ready"] is False
    assert "risk_budget_suppression_exceeded" in summary["promotion_blockers"]
    assert "theme_exposure_cap_breach" in summary["promotion_blockers"]


def test_build_promotion_gate_summary_adds_execution_feasibility_blockers():
    summary = build_promotion_gate_summary(
        walk_forward_summary={
            "rollout_ready": True,
            "rollout_blockers": [],
            "liquidity_capacity_raw_100": 45.0,
            "crowding_risk_raw_100": 72.0,
            "gap_risk_raw_100": 63.0,
        }
    )

    assert summary["promotion_ready"] is False
    assert "liquidity_capacity_floor_breach" in summary["promotion_blockers"]
    assert "crowding_risk_cap_breach" in summary["promotion_blockers"]
    assert "gap_risk_cap_breach" in summary["promotion_blockers"]


def test_summarize_walk_forward_blocks_too_short_test_windows():
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-01-01",
                train_end="2026-01-31",
                test_start="2026-02-01",
                test_end="2026-02-03",
            ),
            metrics={"sharpe_ratio": 0.6, "sortino_ratio": 0.7, "max_drawdown": -4.0},
        )
    ]

    summary = summarize_walk_forward(results)

    assert summary["rollout_ready"] is False
    assert "test_window_too_short" in summary["rollout_blockers"]
    assert summary["promotion_ready"] is False
    assert "test_window_too_short" in summary["promotion_blockers"]


def test_summarize_walk_forward_blocks_btst_quality_floor_breaches():
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-01-01",
                train_end="2026-01-31",
                test_start="2026-02-01",
                test_end="2026-02-28",
            ),
            metrics={
                "sharpe_ratio": 0.8,
                "sortino_ratio": 1.1,
                "max_drawdown": -4.0,
                "test_trading_days": 12,
                "next_close_positive_rate": 0.50,
                "next_high_hit_rate": 0.54,
                "t_plus_2_close_positive_rate": 0.50,
                "t_plus_3_close_positive_rate": 0.48,
                "t_plus_3_close_expectancy": -0.01,
                "downside_p10": -0.07,
                "sample_weight": 0.55,
            },
        )
    ]

    summary = summarize_walk_forward(results)

    assert summary["rollout_ready"] is False
    assert "btst_quality_next_close_positive_rate_floor_breach" in summary["rollout_blockers"]
    assert "btst_quality_next_high_hit_rate_floor_breach" in summary["rollout_blockers"]
    assert "btst_quality_t_plus_2_close_positive_rate_floor_breach" in summary["rollout_blockers"]
    assert "btst_quality_t_plus_3_close_positive_rate_floor_breach" in summary["rollout_blockers"]
    assert "btst_quality_t_plus_3_close_expectancy_floor_breach" in summary["rollout_blockers"]
    assert "btst_quality_downside_p10_floor_breach" in summary["rollout_blockers"]
    assert "btst_quality_sample_weight_floor_breach" in summary["rollout_blockers"]
    assert summary["promotion_ready"] is False
    assert "btst_quality_next_close_positive_rate_floor_breach" in summary["promotion_blockers"]


def test_summarize_walk_forward_allows_longer_test_windows():
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-01-01",
                train_end="2026-01-31",
                test_start="2026-02-01",
                test_end="2026-02-16",
            ),
            metrics={"sharpe_ratio": 0.6, "sortino_ratio": 0.7, "max_drawdown": -4.0},
        )
    ]

    summary = summarize_walk_forward(results)

    assert summary["rollout_ready"] is True
    assert "test_window_too_short" not in summary["rollout_blockers"]
    assert summary["promotion_ready"] is True


def test_summarize_walk_forward_prefers_explicit_test_trading_days():
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-01-01",
                train_end="2026-01-31",
                test_start="2026-02-01",
                test_end="2026-02-28",
            ),
            metrics={
                "sharpe_ratio": 0.6,
                "sortino_ratio": 0.7,
                "max_drawdown": -4.0,
                "test_trading_days": 12,
            },
        )
    ]

    summary = summarize_walk_forward(results)

    assert summary["rollout_ready"] is True
    assert "test_window_too_short" not in summary["rollout_blockers"]


def test_summarize_walk_forward_attaches_promotion_gate_summary():
    class StubEngine:
        def __init__(self, sharpe: float, sortino: float, max_drawdown: float):
            self._metrics = {
                "sharpe_ratio": sharpe,
                "sortino_ratio": sortino,
                "max_drawdown": max_drawdown,
            }

        def run_backtest(self):
            return self._metrics

    windows = build_walk_forward_windows(
        "2026-01-01",
        "2026-04-30",
        train_months=1,
        test_months=1,
        step_months=1,
    )
    results = run_walk_forward(
        windows,
        lambda window: StubEngine(
            sharpe=-0.1 if window.test_start.endswith(("02-01", "03-01")) else 0.2,
            sortino=0.1,
            max_drawdown=-8.0,
        ),
    )

    summary = summarize_walk_forward(results)

    assert summary["rollout_ready"] is False
    assert "majority_non_positive_sharpe_windows" in summary["rollout_blockers"]
    assert summary["promotion_ready"] is False
    assert "majority_non_positive_sharpe_windows" in summary["promotion_blockers"]


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


def test_summarize_walk_forward_blocks_missing_required_sharpe_data():
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-01-01",
                train_end="2026-01-31",
                test_start="2026-02-01",
                test_end="2026-02-28",
            ),
            metrics={"sharpe_ratio": None, "sortino_ratio": 0.1, "max_drawdown": -8.0},
        ),
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-02-01",
                train_end="2026-02-28",
                test_start="2026-03-01",
                test_end="2026-03-31",
            ),
            metrics={"sharpe_ratio": None, "sortino_ratio": 0.2, "max_drawdown": -6.0},
        ),
    ]

    summary = summarize_walk_forward(results)

    assert summary["rollout_ready"] is False
    assert "missing_required_sharpe_data" in summary["rollout_blockers"]
    assert summary["promotion_ready"] is False
    assert "missing_required_sharpe_data" in summary["promotion_blockers"]


def test_summarize_walk_forward_blocks_when_any_window_is_missing_required_sharpe_data():
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-01-01",
                train_end="2026-01-31",
                test_start="2026-02-01",
                test_end="2026-02-28",
            ),
            metrics={"sharpe_ratio": 0.4, "sortino_ratio": 0.5, "max_drawdown": -8.0},
        ),
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-02-01",
                train_end="2026-02-28",
                test_start="2026-03-01",
                test_end="2026-03-31",
            ),
            metrics={"sharpe_ratio": None, "sortino_ratio": 0.2, "max_drawdown": -6.0},
        ),
    ]

    summary = summarize_walk_forward(results)

    assert summary["rollout_ready"] is False
    assert "missing_required_sharpe_data" in summary["rollout_blockers"]
    assert summary["promotion_ready"] is False
    assert "missing_required_sharpe_data" in summary["promotion_blockers"]


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
        # Verify the preset can actually build windows without errors.
        # ALPHA-005: presets with step < test need allow_overlapping_tests.
        kwargs = {k: v for k, v in preset.items() if k != "max_test_trading_days"}
        if kwargs.get("step_months", 1) < kwargs.get("test_months", 1):
            kwargs["allow_overlapping_tests"] = True
        windows = build_walk_forward_windows(
            "2026-01-01",
            "2026-12-31",
            **kwargs,
        )
        assert len(windows) >= 1, f"Preset {name!r} produced no windows"


# ---------------------------------------------------------------------------
# Tests for BTST runner rollout blocker (Task 2)
# ---------------------------------------------------------------------------


def test_summarize_walk_forward_blocks_runner_tail_floor_breach() -> None:
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-01-31", test_start="2026-02-01", test_end="2026-02-28"),
            metrics={
                "sharpe_ratio": 0.8,
                "sortino_ratio": 1.0,
                "max_drawdown": -4.0,
                "test_trading_days": 12,
                "next_close_positive_rate": 0.58,
                "next_high_hit_rate": 0.60,
                "downside_p10": -0.02,
                "max_future_high_return_2_5d_hit_rate_at_20pct": 0.05,
                "runner_capture_count": 1,
            },
        )
    ]

    summary = summarize_walk_forward(results)

    assert "btst_runner_tail_hit_floor_breach" in summary["rollout_blockers"]


def test_summarize_walk_forward_stores_avg_runner_tail_hit_rate():
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-01-31", test_start="2026-02-01", test_end="2026-02-28"),
            metrics={
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.5,
                "max_drawdown": -3.0,
                "test_trading_days": 15,
                "next_close_positive_rate": 0.60,
                "next_high_hit_rate": 0.62,
                "downside_p10": -0.02,
                "max_future_high_return_2_5d_hit_rate_at_20pct": 0.18,
                "runner_capture_count": 4,
            },
        )
    ]

    summary = summarize_walk_forward(results)

    assert "avg_runner_tail_hit_rate" in summary
    assert abs(float(summary["avg_runner_tail_hit_rate"]) - 0.18) < 0.001
    assert summary["total_runner_capture_count"] == 4


def test_summarize_walk_forward_includes_runner_rollout_verdict():
    """summarize_walk_forward must include runner_rollout_verdict and runner_rollout_verdict_detail in output."""
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-01-31", test_start="2026-02-01", test_end="2026-02-28"),
            metrics={
                "sharpe_ratio": 1.5,
                "sortino_ratio": 1.8,
                "max_drawdown": -2.0,
                "test_trading_days": 15,
                "next_close_positive_rate": 0.62,
                "next_high_hit_rate": 0.64,
                "downside_p10": -0.015,
                "max_future_high_return_2_5d_hit_rate_at_20pct": 0.20,
                "runner_capture_count": 5,
            },
        )
    ]

    summary = summarize_walk_forward(results)

    assert "runner_rollout_verdict" in summary
    assert "runner_rollout_verdict_detail" in summary
    assert isinstance(summary["runner_rollout_verdict"], str)
    assert isinstance(summary["runner_rollout_verdict_detail"], dict)
    # tail_hit=0.20 >= RUNNER_TAIL_HIT_ABSOLUTE_MIN=0.12, no baseline → promotable
    assert summary["runner_rollout_verdict"] == "promotable_runner_profile"


def test_summarize_walk_forward_verdict_keep_when_empty():
    """Empty results should return runner_rollout_verdict=keep_precision_baseline."""
    summary = summarize_walk_forward([])
    assert "runner_rollout_verdict" in summary
    assert summary["runner_rollout_verdict"] == "keep_precision_baseline"


def test_summarize_walk_forward_verdict_keep_when_low_tail_hit():
    """Low avg_runner_tail_hit_rate should result in keep_precision_baseline verdict."""
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-01-31", test_start="2026-02-01", test_end="2026-02-28"),
            metrics={
                "sharpe_ratio": 1.5,
                "sortino_ratio": 1.8,
                "max_drawdown": -2.0,
                "test_trading_days": 15,
                "next_close_positive_rate": 0.60,
                "next_high_hit_rate": 0.60,
                "downside_p10": -0.02,
                "max_future_high_return_2_5d_hit_rate_at_20pct": 0.05,
                "runner_capture_count": 2,
            },
        )
    ]

    summary = summarize_walk_forward(results)
    assert summary["runner_rollout_verdict"] == "keep_precision_baseline"


def test_classify_runner_rollout_verdict_promotable_no_baseline():
    verdict, detail = classify_runner_rollout_verdict(
        {"avg_runner_tail_hit_rate": 0.18, "next_close_positive_rate": 0.60, "downside_p10": -0.02}
    )
    assert verdict == "promotable_runner_profile"
    assert detail["verdict_reason"] == "meets_all_runner_criteria"


def test_classify_runner_rollout_verdict_keep_precision_baseline_below_floor():
    verdict, detail = classify_runner_rollout_verdict(
        {"avg_runner_tail_hit_rate": 0.08, "next_close_positive_rate": 0.60, "downside_p10": -0.02}
    )
    assert verdict == "keep_precision_baseline"
    assert detail["verdict_reason"] == "tail_hit_below_absolute_min"


def test_classify_runner_rollout_verdict_tail_hit_better_but_t1_risky():
    runner = {"avg_runner_tail_hit_rate": 0.22, "next_close_positive_rate": 0.52, "downside_p10": -0.02}
    baseline = {"avg_runner_tail_hit_rate": 0.14, "next_close_positive_rate": 0.58, "downside_p10": -0.02}
    verdict, detail = classify_runner_rollout_verdict(runner, baseline)
    # tail_hit_delta = 0.08 >= 0.05, but t1 regression = 0.52-0.58 = -0.06 < -0.04
    assert verdict == "tail_hit_better_but_t1_risky"
    assert detail["verdict_reason"] == "t1_or_downside_regression"


def test_classify_runner_rollout_verdict_coverage_only_not_runner_better():
    runner = {"avg_runner_tail_hit_rate": 0.15, "next_close_positive_rate": 0.60, "downside_p10": -0.02}
    baseline = {"avg_runner_tail_hit_rate": 0.13, "next_close_positive_rate": 0.60, "downside_p10": -0.02}
    verdict, detail = classify_runner_rollout_verdict(runner, baseline)
    # tail_hit_delta = 0.02 < 0.05
    assert verdict == "coverage_only_not_runner_better"
    assert detail["verdict_reason"] == "insufficient_tail_hit_improvement"


def test_classify_runner_rollout_verdict_promotable_with_baseline():
    # t2/t3 explicitly provided to clear the absolute-minimum floor (GAMMA-004).
    runner = {"avg_runner_tail_hit_rate": 0.22, "next_close_positive_rate": 0.60, "downside_p10": -0.02, "t_plus_2_close_positive_rate": 0.55, "t_plus_3_close_positive_rate": 0.55}
    baseline = {"avg_runner_tail_hit_rate": 0.14, "next_close_positive_rate": 0.60, "downside_p10": -0.02, "t_plus_2_close_positive_rate": 0.55, "t_plus_3_close_positive_rate": 0.55}
    verdict, detail = classify_runner_rollout_verdict(runner, baseline)
    # tail_hit_delta = 0.08 >= 0.05, no T+1 or downside regression
    assert verdict == "promotable_runner_profile"
    assert abs(detail["tail_hit_delta"] - 0.08) < 0.001


def test_classify_runner_rollout_verdict_rejects_zero_t2_win_rate():
    """GAMMA-004 regression guard: candidate with 0% T+2 win rate is risky,
    not safe. The `> 0.0` guard on t2/t3 made such candidates pass when
    t2_regression was trivially 0.0 (any - 0 = 0 > -0.02 floor).
    A 0% T+2 win rate must be treated as at least as risky as a known-bad
    regression, mirroring how T+1 is evaluated (no > 0.0 guard)."""
    runner = {
        "avg_runner_tail_hit_rate": 0.22,
        "next_close_positive_rate": 0.60,
        "t_plus_2_close_positive_rate": 0.0,
        "t_plus_3_close_positive_rate": 0.60,
        "downside_p10": -0.02,
    }
    baseline = {
        "avg_runner_tail_hit_rate": 0.14,
        "next_close_positive_rate": 0.60,
        "t_plus_2_close_positive_rate": 0.0,
        "t_plus_3_close_positive_rate": 0.60,
        "downside_p10": -0.02,
    }
    verdict, detail = classify_runner_rollout_verdict(runner, baseline)
    # tail_hit_delta = 0.08 >= 0.05, no T+1 or downside regression,
    # but t2_win_rate = 0.0 should be treated as risky and disqualify promotion.
    assert verdict == "tail_hit_better_but_t1_risky"
    assert detail["verdict_reason"] == "t1_or_downside_regression"


def test_classify_runner_rollout_verdict_rejects_zero_t3_win_rate():
    """GAMMA-004: same as t2 — 0% t3 win rate must not be ignored."""
    runner = {
        "avg_runner_tail_hit_rate": 0.22,
        "next_close_positive_rate": 0.60,
        "t_plus_2_close_positive_rate": 0.60,
        "t_plus_3_close_positive_rate": 0.0,
        "downside_p10": -0.02,
    }
    baseline = {
        "avg_runner_tail_hit_rate": 0.14,
        "next_close_positive_rate": 0.60,
        "t_plus_2_close_positive_rate": 0.60,
        "t_plus_3_close_positive_rate": 0.0,
        "downside_p10": -0.02,
    }
    verdict, detail = classify_runner_rollout_verdict(runner, baseline)
    assert verdict == "tail_hit_better_but_t1_risky"
    assert detail["verdict_reason"] == "t1_or_downside_regression"


def test_classify_win_rate_first_rollout_verdict_accepts_bounded_tradeoffs():
    candidate = {
        "rollout_blockers": [],
        "next_close_positive_rate": 0.612,
        "next_high_hit_rate": 0.624,
        "realized_payoff_ratio": 1.22,
        "window_coverage": 0.81,
    }
    baseline = {
        "rollout_blockers": [],
        "next_close_positive_rate": 0.600,
        "next_high_hit_rate": 0.615,
        "realized_payoff_ratio": 1.30,
        "window_coverage": 0.83,
    }

    verdict, detail = classify_win_rate_first_rollout_verdict(candidate, baseline)

    assert verdict == "accepted"
    assert detail["verdict_reason"] == "meets_win_rate_first_criteria"
    assert detail["next_close_positive_rate_delta"] == pytest.approx(0.012)
    assert detail["next_high_hit_rate_delta"] == pytest.approx(0.009)
    assert detail["realized_payoff_ratio_delta"] == pytest.approx(-0.08)
    assert detail["window_coverage_delta"] == pytest.approx(-0.02)


def test_classify_win_rate_first_rollout_verdict_rejects_candidate_with_blockers_and_no_baseline():
    """Task B final fix: candidate with rollout_blockers but no baseline must be rejected, not neutral."""
    candidate = {
        "rollout_blockers": ["worst_max_drawdown_floor"],
        "next_close_positive_rate": 0.612,
        "next_high_hit_rate": 0.624,
        "realized_payoff_ratio": 1.22,
        "window_coverage": 0.81,
    }
    # No baseline → would normally return neutral, but blockers must force rejection
    verdict, detail = classify_win_rate_first_rollout_verdict(candidate, baseline_summary=None)

    assert verdict == "rejected", "Candidate with rollout_blockers must be rejected regardless of baseline availability"
    assert "rollout_blocked" in detail["rejection_reasons"]
    assert detail["verdict_reason"] == "rollout_blocked"


def test_classify_win_rate_first_rollout_verdict_prioritizes_blocker_reason_over_other_rejections():
    """Task B final fix: when rollout_blockers are present along with other rejection reasons,
    verdict_reason must be 'rollout_blocked', not 'bounded_tradeoff_check_failed'."""
    candidate = {
        "rollout_blockers": ["worst_max_drawdown_floor"],
        "next_close_positive_rate": 0.602,  # minimal uplift
        "next_high_hit_rate": 0.612,  # minimal uplift
        "realized_payoff_ratio": 1.22,
        "window_coverage": 0.81,
    }
    baseline = {
        "rollout_blockers": [],
        "next_close_positive_rate": 0.600,
        "next_high_hit_rate": 0.610,
        "realized_payoff_ratio": 1.30,
        "window_coverage": 0.83,
    }
    # Win rate deltas are too small (< 0.005), so we'd have both
    # rollout_blocked AND win_rate_uplift_missing in rejection_reasons.
    # But verdict_reason should prioritize rollout_blocked.
    
    verdict, detail = classify_win_rate_first_rollout_verdict(candidate, baseline)
    
    assert verdict == "rejected"
    assert "rollout_blocked" in detail["rejection_reasons"]
    assert "win_rate_uplift_missing" in detail["rejection_reasons"]
    # The spec gap: currently this would be "bounded_tradeoff_check_failed"
    # but it MUST be "rollout_blocked" when blockers are present
    assert detail["verdict_reason"] == "rollout_blocked", \
        "verdict_reason must prioritize rollout_blocked when blockers are present, even with other rejection reasons"


# ---------------------------------------------------------------------------
# Round 11 Task 4 — Walk-forward recency weighting
# ---------------------------------------------------------------------------

from src.backtesting.walk_forward import (
    _compute_walk_forward_recency_weight,
    WALK_FORWARD_RECENCY_HALF_LIFE_DAYS,
    WALK_FORWARD_RECENCY_DECAY_MIN_FACTOR,
)


def test_compute_walk_forward_recency_weight_same_date_returns_one() -> None:
    """Window with test_start equal to reference_date must receive weight 1.0."""
    assert _compute_walk_forward_recency_weight("2026-03-20", "2026-03-20") == pytest.approx(1.0)


def test_compute_walk_forward_recency_weight_older_window_less_than_one() -> None:
    """A window 90 days before the reference should receive weight ~0.5 (half life)."""
    weight = _compute_walk_forward_recency_weight("2025-12-20", "2026-03-20")  # ~90 days
    assert weight < 1.0
    assert weight >= WALK_FORWARD_RECENCY_DECAY_MIN_FACTOR
    # Approximately 0.5 at the half-life
    assert weight == pytest.approx(0.5, abs=0.05)


def test_compute_walk_forward_recency_weight_respects_floor() -> None:
    """A very old window must not go below WALK_FORWARD_RECENCY_DECAY_MIN_FACTOR."""
    weight = _compute_walk_forward_recency_weight("2020-01-01", "2026-03-20")
    assert weight == pytest.approx(WALK_FORWARD_RECENCY_DECAY_MIN_FACTOR)


def test_compute_walk_forward_recency_weight_future_date_clamps_to_one() -> None:
    """A window with test_start after reference_date must return 1.0 (no bonus for future windows)."""
    weight = _compute_walk_forward_recency_weight("2026-06-01", "2026-03-20")
    assert weight == pytest.approx(1.0)


def test_summarize_walk_forward_time_weights_btst_quality_metrics() -> None:
    """Recent windows must dominate BTST quality averages when they differ substantially.

    Two windows have identical Sharpe/drawdown but very different BTST quality metrics.
    The recent window (large next_close_positive_rate) must pull the weighted average up
    compared to an equal-weight average.
    """
    def _make_result(test_start: str, next_close_positive_rate: float) -> WalkForwardResult:
        return WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2025-01-01",
                train_end="2025-01-31",
                test_start=test_start,
                test_end=test_start,
            ),
            metrics={
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.5,
                "max_drawdown": -3.0,
                "test_trading_days": 15,
                "next_close_positive_rate": next_close_positive_rate,
                "next_high_hit_rate_at_threshold": 0.65,
                "downside_p10": -0.018,
            },
        )

    # Old window: poor next_close_positive_rate; recent window: high rate.
    old_result = _make_result("2025-01-01", next_close_positive_rate=0.30)
    new_result = _make_result("2026-04-01", next_close_positive_rate=0.90)

    summary = summarize_walk_forward([old_result, new_result])

    # The weighted average of next_close_positive_rate must be closer to 0.90 than 0.60
    # (which is the simple equal-weight average of 0.30 and 0.90).
    weighted_avg = summary.get("next_close_positive_rate")
    simple_avg = 0.60  # (0.30 + 0.90) / 2
    assert weighted_avg is not None
    assert float(weighted_avg) > simple_avg, (
        f"Recency-weighted avg {weighted_avg:.3f} should exceed simple avg {simple_avg:.3f}"
    )


def test_summarize_walk_forward_single_window_unaffected_by_recency() -> None:
    """With a single window, recency weighting must produce the same result as a plain average."""
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-01-31", test_start="2026-02-01", test_end="2026-02-28"),
            metrics={
                "sharpe_ratio": 1.4,
                "sortino_ratio": 1.8,
                "max_drawdown": -2.5,
                "test_trading_days": 18,
                "next_close_positive_rate": 0.66,
                "next_high_hit_rate_at_threshold": 0.68,
                "downside_p10": -0.016,
            },
        )
    ]

    summary = summarize_walk_forward(results)

    # Single window → weight is 1.0 → weighted avg equals plain value
    assert summary.get("next_close_positive_rate") == pytest.approx(0.66, abs=0.001)


def test_summarize_walk_forward_exposes_recency_half_life_days() -> None:
    """summarize_walk_forward must expose recency_half_life_days in the summary for transparency."""
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-01-31", test_start="2026-02-01", test_end="2026-02-28"),
            metrics={"sharpe_ratio": 1.2, "sortino_ratio": 1.4, "max_drawdown": -3.0, "test_trading_days": 12},
        )
    ]
    summary = summarize_walk_forward(results)
    assert "recency_half_life_days" in summary
    assert summary["recency_half_life_days"] == WALK_FORWARD_RECENCY_HALF_LIFE_DAYS


# ---------------------------------------------------------------------------
# Round 12 Task 2 — Multi-candidate rollout selection
# ---------------------------------------------------------------------------

from src.backtesting.walk_forward import select_best_promotable_candidate


def _promotable_summary(tail_hit: float = 0.20) -> dict:
    """Build a runner summary that classify_runner_rollout_verdict marks 'promotable_runner_profile'."""
    return {"avg_runner_tail_hit_rate": tail_hit, "next_close_positive_rate": 0.62, "downside_p10": -0.02}


def _keep_baseline_summary() -> dict:
    """Build a runner summary that yields 'keep_precision_baseline'."""
    return {"avg_runner_tail_hit_rate": 0.08, "next_close_positive_rate": 0.62, "downside_p10": -0.02}


def test_select_best_promotable_candidate_returns_none_for_empty_list() -> None:
    """Empty candidate list must return (None, None, {})."""
    label, verdict, detail = select_best_promotable_candidate([])
    assert label is None
    assert verdict is None
    assert detail == {}


def test_select_best_promotable_candidate_single_promotable_is_returned() -> None:
    """Single promotable candidate must be returned as best."""
    candidates = [("profile_a", _promotable_summary())]
    label, verdict, detail = select_best_promotable_candidate(candidates)
    assert label == "profile_a"
    assert verdict == "promotable_runner_profile"


def test_select_best_promotable_candidate_prefers_promotable_over_keep_baseline() -> None:
    """promotable_runner_profile must beat keep_precision_baseline regardless of order."""
    candidates = [
        ("keep", _keep_baseline_summary()),
        ("promote", _promotable_summary()),
    ]
    label, verdict, detail = select_best_promotable_candidate(candidates)
    assert label == "promote"
    assert verdict == "promotable_runner_profile"


def test_select_best_promotable_candidate_prefers_higher_tail_hit_when_same_verdict() -> None:
    """When two candidates share the same verdict, the one with higher tail hit rate wins."""
    candidates = [
        ("low", _promotable_summary(tail_hit=0.18)),
        ("high", _promotable_summary(tail_hit=0.25)),
    ]
    label, verdict, detail = select_best_promotable_candidate(candidates)
    assert label == "high"
    assert verdict == "promotable_runner_profile"


def test_select_best_promotable_candidate_keeps_single_keep_baseline_candidate() -> None:
    """When all candidates are keep_precision_baseline the best one is still returned."""
    candidates = [("only_keep", _keep_baseline_summary())]
    label, verdict, detail = select_best_promotable_candidate(candidates)
    assert label == "only_keep"
    assert verdict == "keep_precision_baseline"


def test_select_best_promotable_candidate_verdict_priority_order() -> None:
    """Priority: promotable > tail_risky > coverage_only > keep_baseline."""
    # coverage_only: small tail hit delta vs baseline, no regression
    baseline = {"avg_runner_tail_hit_rate": 0.13, "next_close_positive_rate": 0.60, "downside_p10": -0.02}
    coverage_only = {"avg_runner_tail_hit_rate": 0.15, "next_close_positive_rate": 0.60, "downside_p10": -0.02}
    # tail_risky: big delta but T+1 regression
    tail_risky = {"avg_runner_tail_hit_rate": 0.22, "next_close_positive_rate": 0.52, "downside_p10": -0.02}

    candidates = [
        ("keep", _keep_baseline_summary()),
        ("coverage", coverage_only),
        ("risky", tail_risky),
    ]
    label, verdict, detail = select_best_promotable_candidate(candidates, baseline_summary=baseline)
    # tail_risky wins over coverage_only and keep_baseline even with no promotable
    assert label == "risky"
    assert verdict == "tail_hit_better_but_t1_risky"


def test_select_best_promotable_candidate_uses_baseline_for_all_candidates() -> None:
    """baseline_summary must be forwarded to each individual verdict classification."""
    # t2/t3 explicitly provided to clear the absolute-minimum floor (GAMMA-004).
    baseline = {"avg_runner_tail_hit_rate": 0.14, "next_close_positive_rate": 0.60, "downside_p10": -0.02, "t_plus_2_close_positive_rate": 0.55, "t_plus_3_close_positive_rate": 0.55}
    # This runner would be promotable only when compared against the baseline
    runner = {"avg_runner_tail_hit_rate": 0.22, "next_close_positive_rate": 0.60, "downside_p10": -0.02, "t_plus_2_close_positive_rate": 0.55, "t_plus_3_close_positive_rate": 0.55}
    candidates = [("runner", runner)]
    label, verdict, _detail = select_best_promotable_candidate(candidates, baseline_summary=baseline)
    assert label == "runner"
    assert verdict == "promotable_runner_profile"


# ---------------------------------------------------------------------------
# Round 13 — Task 1: Escape Cost Model (avg_escape_gap_cost floor guardrail)
# ---------------------------------------------------------------------------


def test_summarize_walk_forward_blocks_avg_escape_gap_cost_floor_breach() -> None:
    """avg_escape_gap_cost below -0.03 must trigger a rollout blocker (Task 1, Round 13).

    When the average open-return for escaped runner rows is worse than -3 % across walk-forward
    windows, the aggregated summary must contain a blocker key to prevent promotion.
    """
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-01-01",
                train_end="2026-01-31",
                test_start="2026-02-01",
                test_end="2026-02-28",
            ),
            metrics={
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.5,
                "max_drawdown": -3.0,
                "test_trading_days": 15,
                "next_close_positive_rate": 0.62,
                "next_high_hit_rate_at_threshold": 0.65,
                "downside_p10": -0.018,
                # avg_escape_gap_cost below floor of -0.03
                "avg_escape_gap_cost": -0.05,
            },
        )
    ]

    summary = summarize_walk_forward(results)

    assert "btst_quality_avg_escape_gap_cost_floor_breach" in summary.get("rollout_blockers", []), (
        "Expected floor-breach blocker for avg_escape_gap_cost but got: "
        f"{summary.get('rollout_blockers')}"
    )


def test_summarize_walk_forward_no_blocker_when_avg_escape_gap_cost_acceptable() -> None:
    """avg_escape_gap_cost at or above -0.03 must NOT trigger a floor-breach blocker (Task 1, Round 13)."""
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-01-01",
                train_end="2026-01-31",
                test_start="2026-02-01",
                test_end="2026-02-28",
            ),
            metrics={
                "sharpe_ratio": 1.4,
                "sortino_ratio": 1.8,
                "max_drawdown": -2.5,
                "test_trading_days": 18,
                "next_close_positive_rate": 0.66,
                "next_high_hit_rate_at_threshold": 0.68,
                "downside_p10": -0.016,
                # avg_escape_gap_cost just above the floor
                "avg_escape_gap_cost": -0.02,
            },
        )
    ]

    summary = summarize_walk_forward(results)

    assert "btst_quality_avg_escape_gap_cost_floor_breach" not in summary.get("rollout_blockers", []), (
        "Unexpected floor-breach blocker when avg_escape_gap_cost is acceptable: "
        f"{summary.get('rollout_blockers')}"
    )


def test_summarize_walk_forward_avg_escape_gap_cost_missing_does_not_raise() -> None:
    """When avg_escape_gap_cost is absent from all windows, the summary must not raise and must
    omit the metric key entirely (Task 1, Round 13).
    """
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-01-01",
                train_end="2026-01-31",
                test_start="2026-02-01",
                test_end="2026-02-28",
            ),
            metrics={
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.5,
                "max_drawdown": -3.0,
                "test_trading_days": 15,
                "next_close_positive_rate": 0.62,
                "next_high_hit_rate_at_threshold": 0.65,
                "downside_p10": -0.018,
                # avg_escape_gap_cost intentionally absent
            },
        )
    ]

    summary = summarize_walk_forward(results)

    # Must not raise; blocker should NOT fire when data is absent
    assert "btst_quality_avg_escape_gap_cost_floor_breach" not in summary.get("rollout_blockers", [])


# ---------------------------------------------------------------------------
# Round 13 — Task 2: T+1 Return Kurtosis Detection (next_close_return_kurtosis cap guardrail)
# ---------------------------------------------------------------------------


def test_summarize_walk_forward_blocks_next_close_return_kurtosis_cap_breach() -> None:
    """next_close_return_kurtosis above 5.0 must trigger a cap-breach blocker (Task 2, Round 13).

    Fat-tailed return distributions inflate apparent performance metrics.  When the average
    excess kurtosis across walk-forward windows exceeds 5.0 the aggregated summary must block
    rollout promotion.
    """
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-01-01",
                train_end="2026-01-31",
                test_start="2026-02-01",
                test_end="2026-02-28",
            ),
            metrics={
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.5,
                "max_drawdown": -3.0,
                "test_trading_days": 15,
                "next_close_positive_rate": 0.62,
                "next_high_hit_rate_at_threshold": 0.65,
                "downside_p10": -0.018,
                # kurtosis above cap of 5.0
                "next_close_return_kurtosis": 7.2,
            },
        )
    ]

    summary = summarize_walk_forward(results)

    assert "btst_quality_next_close_return_kurtosis_cap_breach" in summary.get("rollout_blockers", []), (
        "Expected cap-breach blocker for next_close_return_kurtosis but got: "
        f"{summary.get('rollout_blockers')}"
    )


def test_summarize_walk_forward_no_blocker_when_kurtosis_below_cap() -> None:
    """next_close_return_kurtosis at or below 5.0 must NOT trigger a cap-breach blocker (Task 2, Round 13)."""
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2026-01-01",
                train_end="2026-01-31",
                test_start="2026-02-01",
                test_end="2026-02-28",
            ),
            metrics={
                "sharpe_ratio": 1.4,
                "sortino_ratio": 1.8,
                "max_drawdown": -2.5,
                "test_trading_days": 18,
                "next_close_positive_rate": 0.66,
                "next_high_hit_rate_at_threshold": 0.68,
                "downside_p10": -0.016,
                # kurtosis within acceptable range
                "next_close_return_kurtosis": 3.1,
            },
        )
    ]

    summary = summarize_walk_forward(results)

    assert "btst_quality_next_close_return_kurtosis_cap_breach" not in summary.get("rollout_blockers", []), (
        "Unexpected cap-breach blocker when kurtosis is acceptable: "
        f"{summary.get('rollout_blockers')}"
    )


def test_summarize_walk_forward_kurtosis_multi_window_plain_average() -> None:
    """Cap metrics use plain (unweighted) average across windows, not recency-weighted (Task 2, Round 13).

    Two windows with very different kurtosis values and very different test_start dates must produce
    a plain arithmetic average, not a recency-biased average.
    """
    def _make_result(test_start: str, kurtosis: float) -> WalkForwardResult:
        return WalkForwardResult(
            window=WalkForwardWindow(
                train_start="2025-01-01",
                train_end="2025-01-31",
                test_start=test_start,
                test_end=test_start,
            ),
            metrics={
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.5,
                "max_drawdown": -3.0,
                "test_trading_days": 15,
                "next_close_positive_rate": 0.62,
                "next_high_hit_rate_at_threshold": 0.65,
                "downside_p10": -0.018,
                "next_close_return_kurtosis": kurtosis,
            },
        )

    # Old window: kurtosis = 2.0; recent window: kurtosis = 6.0 → plain avg = 4.0
    old_result = _make_result("2025-01-01", kurtosis=2.0)
    new_result = _make_result("2026-04-01", kurtosis=6.0)

    summary = summarize_walk_forward([old_result, new_result])

    # Plain average is 4.0 (no cap breach).  Recency-weighted would be >> 4.0 (would breach cap).
    kurtosis_avg = summary.get("next_close_return_kurtosis")
    assert kurtosis_avg is not None
    assert float(kurtosis_avg) == pytest.approx(4.0, abs=0.05), (
        f"Expected plain average ~4.0 but got {kurtosis_avg}"
    )
    # 4.0 ≤ 5.0 cap → no blocker expected
    assert "btst_quality_next_close_return_kurtosis_cap_breach" not in summary.get("rollout_blockers", [])


# ---------------------------------------------------------------------------
# Round 14 — Task 1: Consecutive Window Consistency (assess_profile_stability)
# ---------------------------------------------------------------------------

from src.backtesting.walk_forward import assess_profile_stability, PROFILE_STABILITY_NON_PROMOTABLE_STREAK_THRESHOLD, PROFILE_STABILITY_NON_PROMOTABLE_FRACTION_THRESHOLD


def test_assess_profile_stability_empty_returns_insufficient_data() -> None:
    """Empty verdict list must return stability_verdict='insufficient_data' (Task 1, Round 14)."""
    result = assess_profile_stability([])
    assert result["stability_verdict"] == "insufficient_data"
    assert result["stability_score"] is None
    assert result["max_consecutive_non_promotable"] == 0
    assert result["non_promotable_count"] == 0
    assert result["total_window_count"] == 0


def test_assess_profile_stability_all_promotable_is_stable() -> None:
    """All-promotable windows → stable_profile with stability_score=1.0 (Task 1, Round 14)."""
    verdicts: list[tuple[str, dict]] = [("promotable_runner_profile", {}) for _ in range(4)]
    result = assess_profile_stability(verdicts)
    assert result["stability_verdict"] == "stable_profile"
    assert result["stability_score"] == pytest.approx(1.0, abs=1e-4)
    assert result["non_promotable_count"] == 0
    assert result["max_consecutive_non_promotable"] == 0


def test_assess_profile_stability_consecutive_streak_triggers_unstable() -> None:
    """Two or more consecutive non-promotable verdicts must produce unstable_profile (Task 1, Round 14).

    PROFILE_STABILITY_NON_PROMOTABLE_STREAK_THRESHOLD = 2.
    """
    verdicts: list[tuple[str, dict]] = [
        ("promotable_runner_profile", {}),
        ("keep_precision_baseline", {}),
        ("keep_precision_baseline", {}),
        ("promotable_runner_profile", {}),
    ]
    result = assess_profile_stability(verdicts)
    assert result["stability_verdict"] == "unstable_profile", f"Expected unstable due to streak=2 but got: {result}"
    assert result["max_consecutive_non_promotable"] == 2
    assert result["non_promotable_count"] == 2


def test_assess_profile_stability_single_non_promotable_no_streak_stable() -> None:
    """A single isolated non-promotable window with < 50% non-promotable fraction → stable (Task 1, Round 14)."""
    verdicts: list[tuple[str, dict]] = [
        ("promotable_runner_profile", {}),
        ("keep_precision_baseline", {}),
        ("promotable_runner_profile", {}),
        ("promotable_runner_profile", {}),
    ]
    result = assess_profile_stability(verdicts)
    # streak=1 < threshold=2; fraction=1/4=0.25 < 0.5 → stable
    assert result["stability_verdict"] == "stable_profile"
    assert result["max_consecutive_non_promotable"] == 1
    assert result["non_promotable_count"] == 1


def test_assess_profile_stability_majority_non_promotable_triggers_unstable() -> None:
    """≥50 % non-promotable windows must trigger unstable_profile even without consecutive streak (Task 1, Round 14)."""
    verdicts: list[tuple[str, dict]] = [
        ("promotable_runner_profile", {}),
        ("coverage_only_not_runner_better", {}),
        ("tail_hit_better_but_t1_risky", {}),
        ("promotable_runner_profile", {}),
    ]
    # Non-promotable: 2/4 = 50 % → triggers fraction threshold
    result = assess_profile_stability(verdicts)
    assert result["stability_verdict"] == "unstable_profile", f"Expected unstable due to 50% fraction but got: {result}"
    assert result["non_promotable_count"] == 2


def test_assess_profile_stability_score_calculation() -> None:
    """stability_score = 1 - (non_promotable_count / total) (Task 1, Round 14)."""
    verdicts: list[tuple[str, dict]] = [
        ("promotable_runner_profile", {}),
        ("promotable_runner_profile", {}),
        ("keep_precision_baseline", {}),
        ("promotable_runner_profile", {}),
    ]
    result = assess_profile_stability(verdicts)
    expected_score = 1.0 - (1.0 / 4.0)  # = 0.75
    assert result["stability_score"] == pytest.approx(expected_score, abs=1e-4)


def test_summarize_walk_forward_includes_profile_stability_fields() -> None:
    """summarize_walk_forward must include profile_stability_* fields in its output (Task 1, Round 14)."""
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-01-31", test_start="2026-02-01", test_end="2026-02-28"),
            metrics={"sharpe_ratio": 1.2, "sortino_ratio": 1.5, "max_drawdown": -3.0, "test_trading_days": 15},
        ),
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-02-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31"),
            metrics={"sharpe_ratio": 1.4, "sortino_ratio": 1.8, "max_drawdown": -2.5, "test_trading_days": 20},
        ),
    ]
    summary = summarize_walk_forward(results)
    assert "profile_stability_score" in summary
    assert "profile_stability_max_consecutive_non_promotable" in summary
    assert "profile_stability_verdict" in summary


def test_summarize_walk_forward_unstable_profile_adds_blocker() -> None:
    """An unstable profile must add 'profile_stability_unstable' to rollout_blockers (Task 1, Round 14).

    Force instability: populate two consecutive windows where avg_runner_tail_hit_rate is below
    the absolute floor (< 0.12), which forces verdict='keep_precision_baseline'.
    """
    def _non_promotable_window(test_start: str) -> WalkForwardResult:
        return WalkForwardResult(
            window=WalkForwardWindow(train_start="2025-12-01", train_end="2025-12-31", test_start=test_start, test_end=test_start),
            metrics={
                "sharpe_ratio": 1.0,
                "sortino_ratio": 1.2,
                "max_drawdown": -4.0,
                "test_trading_days": 10,
                # Tail hit below absolute floor → keep_precision_baseline
                "max_future_high_return_2_5d_hit_rate_at_20pct": 0.05,
            },
        )

    results = [
        _non_promotable_window("2026-01-01"),
        _non_promotable_window("2026-02-01"),
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-02-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31"),
            metrics={"sharpe_ratio": 1.5, "sortino_ratio": 2.0, "max_drawdown": -2.0, "test_trading_days": 20, "max_future_high_return_2_5d_hit_rate_at_20pct": 0.05},
        ),
    ]
    summary = summarize_walk_forward(results)
    assert "profile_stability_unstable" in summary.get("rollout_blockers", []), (
        f"Expected profile_stability_unstable blocker but got: {summary.get('rollout_blockers')}"
    )
    assert summary.get("profile_stability_verdict") == "unstable_profile"


def test_summarize_walk_forward_stable_profile_no_stability_blocker() -> None:
    """A consistently promotable (or single-window) profile must not add a stability blocker (Task 1, Round 14)."""
    result = WalkForwardResult(
        window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-01-31", test_start="2026-02-01", test_end="2026-02-28"),
        metrics={"sharpe_ratio": 1.5, "sortino_ratio": 2.0, "max_drawdown": -2.5, "test_trading_days": 20},
    )
    summary = summarize_walk_forward([result])
    assert "profile_stability_unstable" not in summary.get("rollout_blockers", []), (
        f"Unexpected stability blocker: {summary.get('rollout_blockers')}"
    )


# ---------------------------------------------------------------------------
# Round 14 — Task 2: Candidate Pool Size Adaptive Awareness
# ---------------------------------------------------------------------------

from src.backtesting.walk_forward import CANDIDATE_POOL_SCARCE_THRESHOLD, CANDIDATE_POOL_ABUNDANT_THRESHOLD


def test_summarize_walk_forward_includes_pool_size_fields() -> None:
    """summarize_walk_forward must expose avg_candidate_pool_size and related fields (Task 2, Round 14)."""
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-01-31", test_start="2026-02-01", test_end="2026-02-28"),
            metrics={"sharpe_ratio": 1.2, "sortino_ratio": 1.5, "max_drawdown": -3.0, "test_trading_days": 15, "candidate_pool_size": 35},
        ),
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-02-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31"),
            metrics={"sharpe_ratio": 1.4, "sortino_ratio": 1.8, "max_drawdown": -2.5, "test_trading_days": 20, "candidate_pool_size": 65},
        ),
    ]
    summary = summarize_walk_forward(results)
    assert "avg_candidate_pool_size" in summary
    assert "scarce_market_window_count" in summary
    assert "abundant_market_window_count" in summary
    assert "market_size_classification" in summary
    assert summary["avg_candidate_pool_size"] == pytest.approx(50.0, abs=1e-4)
    assert summary["scarce_market_window_count"] == 0
    assert summary["abundant_market_window_count"] == 0
    assert summary["market_size_classification"] == "mixed"


def test_summarize_walk_forward_detects_scarce_dominated_market() -> None:
    """More than 50% of windows with pool size < 20 → scarce_dominated classification (Task 2, Round 14)."""
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-01-31", test_start="2026-02-01", test_end="2026-02-28"),
            metrics={"sharpe_ratio": 1.0, "sortino_ratio": 1.2, "max_drawdown": -5.0, "test_trading_days": 10, "candidate_pool_size": 8},
        ),
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-02-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31"),
            metrics={"sharpe_ratio": 1.1, "sortino_ratio": 1.3, "max_drawdown": -4.5, "test_trading_days": 12, "candidate_pool_size": 12},
        ),
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-03-01", train_end="2026-03-31", test_start="2026-04-01", test_end="2026-04-30"),
            metrics={"sharpe_ratio": 1.2, "sortino_ratio": 1.4, "max_drawdown": -3.5, "test_trading_days": 15, "candidate_pool_size": 50},
        ),
    ]
    summary = summarize_walk_forward(results)
    # 2/3 windows have pool size < CANDIDATE_POOL_SCARCE_THRESHOLD (20) → scarce_dominated
    assert summary["scarce_market_window_count"] == 2
    assert summary["market_size_classification"] == "scarce_dominated"


def test_summarize_walk_forward_detects_abundant_dominated_market() -> None:
    """More than 50% of windows with pool size > 100 → abundant_dominated classification (Task 2, Round 14)."""
    results = [
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-01-01", train_end="2026-01-31", test_start="2026-02-01", test_end="2026-02-28"),
            metrics={"sharpe_ratio": 1.5, "sortino_ratio": 1.9, "max_drawdown": -2.0, "test_trading_days": 18, "candidate_pool_size": 150},
        ),
        WalkForwardResult(
            window=WalkForwardWindow(train_start="2026-02-01", train_end="2026-02-28", test_start="2026-03-01", test_end="2026-03-31"),
            metrics={"sharpe_ratio": 1.6, "sortino_ratio": 2.1, "max_drawdown": -1.8, "test_trading_days": 20, "candidate_pool_size": 120},
        ),
    ]
    summary = summarize_walk_forward(results)
    assert summary["abundant_market_window_count"] == 2
    assert summary["market_size_classification"] == "abundant_dominated"


def test_summarize_walk_forward_empty_results_pool_fields_unknown() -> None:
    """Empty results must return market_size_classification='unknown' (Task 2, Round 14)."""
    summary = summarize_walk_forward([])
    assert summary["market_size_classification"] == "unknown"
    assert summary["avg_candidate_pool_size"] is None
    assert summary["scarce_market_window_count"] == 0
    assert summary["abundant_market_window_count"] == 0


def test_summarize_walk_forward_exposes_win_rate_first_verdict_fields():
    """Task B: summarize_walk_forward must expose win-rate-first verdict derived from classify_win_rate_first_rollout_verdict."""
    windows = [
        WalkForwardWindow(
            train_start="2026-01-01",
            train_end="2026-01-31",
            test_start="2026-02-01",
            test_end="2026-02-28",
        )
    ]

    class StubEngine:
        def run_backtest(self):
            return {
                "sharpe_ratio": 0.8,
                "sortino_ratio": 0.9,
                "max_drawdown": -5.0,
                "test_trading_days": 10,
                "next_close_positive_rate": 0.58,
                "next_high_hit_rate": 0.63,
                "realized_payoff_ratio": 1.8,
                "next_close_expectancy": 0.015,
                "window_coverage": 0.92,
            }

    results = run_walk_forward(windows, lambda window: StubEngine())
    summary = summarize_walk_forward(results)

    # Task B: win-rate-first verdict fields must exist in summary
    assert "win_rate_first_verdict" in summary, "summary must include win_rate_first_verdict"
    assert "win_rate_first_verdict_detail" in summary, "summary must include win_rate_first_verdict_detail"
    assert summary["win_rate_first_verdict"] in {"accepted", "rejected", "neutral"}
    
    # The detail payload should have the standard structure from classify_win_rate_first_rollout_verdict
    detail = summary["win_rate_first_verdict_detail"]
    assert "verdict_reason" in detail
    assert "rejection_reasons" in detail
    assert isinstance(detail["rejection_reasons"], list)


def test_summarize_walk_forward_without_baseline_returns_not_evaluable_verdict():
    """Task B spec fix: when no baseline and no delta fields, verdict must be neutral (not_evaluable), not falsely rejected."""
    windows = [
        WalkForwardWindow(
            train_start="2026-01-01",
            train_end="2026-01-31",
            test_start="2026-02-01",
            test_end="2026-02-28",
        )
    ]

    class StubEngine:
        def run_backtest(self):
            return {
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.3,
                "max_drawdown": -4.0,
                "test_trading_days": 12,
                "next_close_positive_rate": 0.62,
                "next_high_hit_rate": 0.65,
                "realized_payoff_ratio": 1.9,
                "next_close_expectancy": 0.018,
                "window_coverage": 0.88,
            }

    results = run_walk_forward(windows, lambda window: StubEngine())
    summary = summarize_walk_forward(results)  # no baseline provided

    # Must NOT falsely reject with win_rate_uplift_missing when no baseline/deltas available
    verdict = summary["win_rate_first_verdict"]
    detail = summary["win_rate_first_verdict_detail"]
    
    # Expect a neutral verdict, not rejected
    assert verdict != "rejected" or detail["verdict_reason"] != "win_rate_uplift_missing", \
        "Without baseline/deltas, verdict must not be win_rate_uplift_missing rejection"
    
    # Should be neutral/not-evaluable
    assert detail["verdict_reason"] in ["not_evaluable", "insufficient_baseline"], \
        f"Expected neutral verdict reason, got: {detail['verdict_reason']}"


def test_summarize_walk_forward_with_baseline_computes_real_verdict():
    """Task B spec fix: when baseline is provided, win-rate-first verdict must use real uplift signals."""
    windows = [
        WalkForwardWindow(
            train_start="2026-01-01",
            train_end="2026-01-31",
            test_start="2026-02-01",
            test_end="2026-02-28",
        )
    ]

    class CandidateEngine:
        def run_backtest(self):
            return {
                "sharpe_ratio": 1.3,
                "sortino_ratio": 1.4,
                "max_drawdown": -3.5,
                "test_trading_days": 12,
                "next_close_positive_rate": 0.68,  # +0.06 vs baseline
                "next_high_hit_rate": 0.70,        # +0.07 vs baseline
                "realized_payoff_ratio": 1.85,     # -0.05 vs baseline (acceptable)
                "next_close_expectancy": 0.020,
                "window_coverage": 0.90,           # +0.02 vs baseline
            }

    results = run_walk_forward(windows, lambda window: CandidateEngine())
    
    baseline_summary = {
        "next_close_positive_rate": 0.62,
        "next_high_hit_rate": 0.63,
        "realized_payoff_ratio": 1.90,
        "next_close_expectancy": 0.018,
        "window_coverage": 0.88,
        "rollout_blockers": [],
    }
    
    summary = summarize_walk_forward(results, baseline_summary=baseline_summary)

    # Must accept based on real deltas computed from baseline
    verdict = summary["win_rate_first_verdict"]
    detail = summary["win_rate_first_verdict_detail"]
    
    assert verdict == "accepted", f"Expected accepted verdict with good uplifts, got {verdict}"
    assert detail["verdict_reason"] == "meets_win_rate_first_criteria"
    
    # Verify deltas were computed from baseline
    assert detail["next_close_positive_rate_delta"] == pytest.approx(0.06, abs=0.01)
    assert detail["next_high_hit_rate_delta"] == pytest.approx(0.07, abs=0.01)


def test_classify_win_rate_first_rollout_verdict_rejects_when_all_deltas_none_r26g_regression():
    """R20.26-G regression: when window_count=0 (no replay data with complete metrics),
    all win-rate deltas are None → verdict MUST reject with win_rate_uplift_missing,
    never accept (false-pass). Reproduces r.json rollout_blocked safety behavior.

    Scenario: candidate & baseline both have all-None metrics (e.g. replay evaluator
    returned window_count=0 because no input had complete t+2/t+3 horizons).
    _delta returns None for every metric → close_positive_delta is None →
    rejection_reasons gets 'win_rate_uplift_missing'. Verdict must be 'rejected'.
    """
    candidate = {
        "rollout_blockers": [],
        "next_close_positive_rate": None,
        "next_high_hit_rate": None,
        "realized_payoff_ratio": None,
        "next_close_expectancy": None,
        "window_coverage": 0.0,
        # r.json-style: comparison_summary entry with null {metric}_delta values
        "next_close_positive_rate_delta": None,
        "next_high_hit_rate_delta": None,
    }
    baseline = {
        "rollout_blockers": [],
        "next_close_positive_rate": None,
        "next_high_hit_rate": None,
        "realized_payoff_ratio": None,
        "next_close_expectancy": None,
        "window_coverage": 0.0,
    }

    verdict, detail = classify_win_rate_first_rollout_verdict(candidate, baseline)

    # Safety invariant: null deltas must never produce a false "accepted" verdict.
    assert verdict == "rejected", "All-None deltas (window_count=0) must reject, not accept"
    assert "win_rate_uplift_missing" in detail["rejection_reasons"]
    assert detail["next_close_positive_rate_delta"] is None
    assert detail["next_high_hit_rate_delta"] is None
    # With no blockers and only win_rate_uplift_missing, verdict_reason is that code.
    assert detail["verdict_reason"] == "win_rate_uplift_missing"


def test_classify_win_rate_first_rollout_verdict_no_baseline_no_deltas_returns_neutral_or_blocked():
    """R20.26-G: no baseline + all-None deltas is NOT false-accepted. Without rollout_blockers
    it returns 'neutral' (cannot evaluate); with blockers it returns 'rejected'.
    Both paths avoid a false 'accepted' verdict — this is the safety invariant.
    """
    # Case 1: no blockers, no baseline, all-None deltas → neutral (not accepted)
    candidate_neutral = {
        "rollout_blockers": [],
        "next_close_positive_rate_delta": None,
        "next_high_hit_rate_delta": None,
        "realized_payoff_ratio_delta": None,
        "next_close_expectancy_delta": None,
        "window_coverage_delta": 0.0,
    }
    verdict, detail = classify_win_rate_first_rollout_verdict(candidate_neutral, baseline_summary=None)
    assert verdict != "accepted", "All-None deltas with no baseline must never be accepted"
    assert verdict == "neutral"
    assert detail["verdict_reason"] == "not_evaluable"

    # Case 2: with blockers → rejected (blockers always force rejection)
    candidate_blocked = {**candidate_neutral, "rollout_blockers": ["worst_max_drawdown_floor"]}
    verdict, detail = classify_win_rate_first_rollout_verdict(candidate_blocked, baseline_summary=None)
    assert verdict == "rejected"
    assert detail["verdict_reason"] == "rollout_blocked"
    assert "rollout_blocked" in detail["rejection_reasons"]
