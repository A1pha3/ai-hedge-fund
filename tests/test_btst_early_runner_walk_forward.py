from __future__ import annotations

from types import SimpleNamespace

import src.backtesting.early_runner_walk_forward as walk_forward_module
from src.backtesting.early_runner_walk_forward import (
    build_early_runner_walk_forward_summary,
)


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
        lambda *args, **kwargs: [SimpleNamespace(train_start="2026-03-01", train_end="2026-03-15", test_start="2026-03-16", test_end="2026-03-20")],
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


# ---------------------------------------------------------------------------
# ALPHA-003: hit_rate_5d15_on_fills uses filled-only denominator
# ---------------------------------------------------------------------------


def test_hit_rate_5d15_on_fills_uses_filled_only_denominator() -> None:
    """ALPHA-003: hit_rate_5d15_on_fills must exclude unfilled rows from the
    denominator. If 5 of 10 filtered rows are unfilled (hit=False) and 4 of
    the 5 filled rows hit, then:
      hit_rate_5d15 = 4/10 = 0.40 (all attempts, old behavior preserved)
      hit_rate_5d15_on_fills = 4/5 = 0.80 (filled-only, new field)
    Without the fix, there was no way to distinguish a 40% hit rate from
    bad signals vs a 40% hit rate caused by 50% unfilled rate."""
    from src.backtesting.early_runner_walk_forward import _summarize_param_set

    rows = [
        # 5 filled rows: 4 hit, 1 miss
        {"entry_status": "filled", "future_high_hit_15pct_2_5d": True, "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8, "next_close_return_after_cost": 0.03, "next_low_return": -0.02},
        {"entry_status": "filled", "future_high_hit_15pct_2_5d": True, "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8, "next_close_return_after_cost": 0.03, "next_low_return": -0.02},
        {"entry_status": "filled", "future_high_hit_15pct_2_5d": True, "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8, "next_close_return_after_cost": 0.03, "next_low_return": -0.02},
        {"entry_status": "filled", "future_high_hit_15pct_2_5d": True, "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8, "next_close_return_after_cost": 0.03, "next_low_return": -0.02},
        {"entry_status": "filled", "future_high_hit_15pct_2_5d": False, "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8, "next_close_return_after_cost": -0.01, "next_low_return": -0.04},
        # 5 unfilled rows: all hit=False (no entry = no future)
        {"entry_status": "unfilled", "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8},
        {"entry_status": "unfilled", "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8},
        {"entry_status": "unfilled", "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8},
        {"entry_status": "unfilled", "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8},
        {"entry_status": "unfilled", "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8},
    ]
    # Use a permissive param set that passes all rows
    param_set = {"ret_5d_max": 1.0, "ret_10d_max": 1.0, "gap_max": 1.0, "close_strength_max": 1.0, "volume_quality_max": 1.0, "confirm_score_min": 0.0}
    result = _summarize_param_set(rows, param_set)
    assert result["hit_rate_5d15"] == 0.4, f"Expected 0.4 (4/10), got {result['hit_rate_5d15']}"
    assert result["hit_rate_5d15_on_fills"] == 0.8, f"Expected 0.8 (4/5 filled), got {result['hit_rate_5d15_on_fills']}"
    assert result["unfilled_rate"] == 0.5


def test_hit_rate_on_fills_none_when_all_unfilled() -> None:
    """When all filtered rows are unfilled, hit_rate_on_fills should be None
    (no filled population to measure)."""
    from src.backtesting.early_runner_walk_forward import _summarize_param_set

    rows = [
        {"entry_status": "unfilled", "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8},
        {"entry_status": "unfilled", "ret_5d": 0.01, "ret_10d": 0.02, "next_open_return": 0.01, "close_strength": 0.5, "volume_expansion_quality": 0.5, "confirm_score": 0.8},
    ]
    param_set = {"ret_5d_max": 1.0, "ret_10d_max": 1.0, "gap_max": 1.0, "close_strength_max": 1.0, "volume_quality_max": 1.0, "confirm_score_min": 0.0}
    result = _summarize_param_set(rows, param_set)
    assert result["hit_rate_5d15_on_fills"] is None


# ---------------------------------------------------------------------------
# GAMMA-R20.16: _ranking_key treats 0.0 as real data, not missing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ALPHA-006: _distribution_p10 collapses to min for small N (no interpolation)
# ---------------------------------------------------------------------------


def test_distribution_p10_interpolates_for_small_samples() -> None:
    """ALPHA-006: for N<11 the old ``floor((N-1)*0.10)`` index was always 0,
    so p10 returned the *minimum* (worst drawdown) instead of a real p10.

    With 5 drawdowns sorted ascending [-0.10, -0.08, -0.05, -0.03, -0.01],
    the true p10 (linear-interpolation, numpy default 'linear') is about
    -0.092, not -0.10. The legacy discrete index returned ordered[0] = -0.10,
    overstating tail risk on every small walk-forward window."""
    from src.backtesting.early_runner_walk_forward import _distribution_p10

    values = [-0.01, -0.03, -0.05, -0.08, -0.10]
    result = _distribution_p10(values)
    # numpy.percentile 'linear' p10 of these 5 points = -0.092
    assert result != -0.10, "ALPHA-006 regression: p10 still returns min for N<11"
    assert round(result, 4) == -0.092, f"expected interpolated p10 -0.092, got {result}"


def test_distribution_p10_exact_for_large_samples() -> None:
    """For N>=11 the discrete index is >=1 and matches a real percentile
    position; ensure the fix keeps the 10% tail behavior on a large sample
    (regression guard against over-shooting to median or beyond)."""
    from src.backtesting.early_runner_walk_forward import _distribution_p10

    # 20 evenly spaced values 0..19; p10 should land near 1.9 (linear) — at
    # or just below the 2nd-smallest, never at the median (9.5).
    values = list(range(20))
    result = _distribution_p10(values)
    assert result < 5, f"p10 should stay in the tail (small), got {result}"


def test_ranking_key_zero_expectancy_not_confused_with_missing() -> None:
    """GAMMA-R20.16: after_cost_expectancy=0.0 (break-even) must be ranked as 0.0,
    not as -999.0 (missing data sentinel).  The old `x or -999.0` pattern swallowed
    legitimate zero values."""
    from src.backtesting.early_runner_walk_forward import _ranking_key

    zero_summary = {
        "after_cost_expectancy": 0.0,
        "hit_rate_5d15": 0.0,
        "unfilled_rate": 0.0,
        "row_count": 5,
    }
    key = _ranking_key(zero_summary)
    assert key[0] == 0.0, f"expectancy 0.0 should rank as 0.0, got {key[0]}"
    assert key[1] == 0.0, f"hit_rate 0.0 should rank as 0.0, got {key[1]}"
    assert key[2] == -0.0, f"unfilled 0.0 should rank as -0.0, got {key[2]}"
    assert key[3] == 5


def test_ranking_key_missing_values_get_sentinel() -> None:
    """GAMMA-R20.16: missing (None) values must still get the sentinel defaults."""
    from src.backtesting.early_runner_walk_forward import _ranking_key

    empty_summary = {}
    key = _ranking_key(empty_summary)
    assert key[0] == -999.0, f"missing expectancy should be -999.0, got {key[0]}"
    assert key[1] == -999.0, f"missing hit_rate should be -999.0, got {key[1]}"
    assert key[2] == -999.0, f"missing unfilled should be -999.0, got {key[2]}"
    assert key[3] == 0
