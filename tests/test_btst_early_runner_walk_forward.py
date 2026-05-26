from __future__ import annotations

from types import SimpleNamespace

import src.backtesting.early_runner_walk_forward as walk_forward_module
from src.backtesting.early_runner_walk_forward import build_early_runner_walk_forward_summary


def test_build_early_runner_walk_forward_summary_handles_no_first_entry_rows() -> None:
    """An empty first-entry sample should return an empty walk-forward summary without crashing."""
    summary = build_early_runner_walk_forward_summary(
        [
            {
                "trade_date": "2026-03-30",
                "bucket": "second_entry_reentry",
                "confirm_score": 0.70,
            }
        ],
        walk_forward_grid={
            "ret_5d_max": [0.18],
            "ret_10d_max": [0.40],
            "gap_max": [0.05],
            "close_strength_max": [0.95],
            "volume_quality_max": [0.90],
            "confirm_score_min": [0.55],
        },
    )

    assert summary["candidate_grid_size"] == 1
    assert summary["window_count"] == 0
    assert summary["shared_window_mode_enabled"] is False
    assert summary["best_param_set_by_window"] == {}


def test_build_early_runner_walk_forward_summary_uses_shared_windows_and_counts_passes(monkeypatch) -> None:
    """Shared walk-forward windows should be preferred when enough trade dates are available."""
    monkeypatch.setattr(
        walk_forward_module,
        "build_walk_forward_windows",
        lambda *args, **kwargs: [
            SimpleNamespace(train_start="2026-03-01", train_end="2026-03-15", test_start="2026-03-16", test_end="2026-03-20")
        ],
    )
    rows = [
        {
            "trade_date": "2026-03-16",
            "bucket": "early_runner_first_entry",
            "ret_5d": 0.06,
            "ret_10d": 0.12,
            "next_open_return": 0.01,
            "close_strength": 0.72,
            "volume_expansion_quality": 0.45,
            "confirm_score": 0.78,
            "next_close_return_after_cost": 0.025,
            "next_low_return": -0.02,
            "future_high_hit_15pct_2_5d": True,
            "entry_status": "filled",
        },
        {
            "trade_date": "2026-03-18",
            "bucket": "early_runner_first_entry",
            "ret_5d": 0.08,
            "ret_10d": 0.14,
            "next_open_return": 0.015,
            "close_strength": 0.70,
            "volume_expansion_quality": 0.40,
            "confirm_score": 0.74,
            "next_close_return_after_cost": 0.018,
            "next_low_return": -0.015,
            "future_high_hit_15pct_2_5d": True,
            "entry_status": "filled",
        },
        {
            "trade_date": "2026-03-20",
            "bucket": "early_runner_first_entry",
            "ret_5d": 0.05,
            "ret_10d": 0.10,
            "next_open_return": 0.01,
            "close_strength": 0.68,
            "volume_expansion_quality": 0.35,
            "confirm_score": 0.80,
            "next_close_return_after_cost": 0.022,
            "next_low_return": -0.01,
            "future_high_hit_15pct_2_5d": True,
            "entry_status": "filled",
        },
    ]

    summary = build_early_runner_walk_forward_summary(
        rows,
        walk_forward_grid={
            "ret_5d_max": [0.18],
            "ret_10d_max": [0.40],
            "gap_max": [0.05],
            "close_strength_max": [0.95],
            "volume_quality_max": [0.90],
            "confirm_score_min": [0.55],
        },
    )

    assert summary["shared_window_mode_enabled"] is True
    assert summary["window_count"] == 2
    assert summary["month_oos_pass_count"] == 2
    window_modes = {window["window_mode"] for window in summary["best_param_set_by_window"].values()}
    assert window_modes == {"rolling", "expanding"}
    assert all(window["row_count"] == 3 for window in summary["best_param_set_by_window"].values())
    assert all(window["after_cost_expectancy"] == 0.0217 for window in summary["best_param_set_by_window"].values())
