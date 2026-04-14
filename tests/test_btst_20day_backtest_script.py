from __future__ import annotations

import pandas as pd

from scripts.btst_20day_backtest import (
    _apply_rank_caps_to_scored_results,
    _build_profiles,
    PROFILE_WEIGHT_FIELDS,
    PROFILES,
    summarize_return_stats,
)
from src.targets import get_short_trade_target_profile


def test_build_profiles_uses_live_short_trade_profile_thresholds_and_weights() -> None:
    profiles = _build_profiles(("default", "ic_optimized"))

    for profile_name, config in profiles.items():
        source_profile = get_short_trade_target_profile(profile_name)
        assert config["select_threshold"] == source_profile.select_threshold
        assert config["near_miss_threshold"] == source_profile.near_miss_threshold
        assert config["selected_rank_cap"] == source_profile.selected_rank_cap
        assert config["near_miss_rank_cap"] == source_profile.near_miss_rank_cap
        assert config["selected_rank_cap_ratio"] == source_profile.selected_rank_cap_ratio
        assert config["near_miss_rank_cap_ratio"] == source_profile.near_miss_rank_cap_ratio
        for factor_name, weight_field in PROFILE_WEIGHT_FIELDS.items():
            assert config["weights"][factor_name] == getattr(source_profile, weight_field)


def test_module_profiles_stay_in_sync_with_builder_output() -> None:
    assert PROFILES == _build_profiles()


def test_summarize_return_stats_reports_payoff_and_expectancy() -> None:
    stats = summarize_return_stats(pd.Series([5.0, -2.0, 3.0, -1.0, 0.0]))
    assert stats["win_rate"] == 0.4
    assert stats["avg_win_ret"] == 4.0
    assert stats["avg_loss_ret"] == -1.0
    assert stats["payoff_ratio"] == 4.0
    assert stats["expectancy"] == 1.0
    assert stats["downside_p10"] == -1.6


def test_summarize_return_stats_handles_all_winners_without_payoff_ratio() -> None:
    stats = summarize_return_stats(pd.Series([1.2, 0.8, 0.4]))
    assert stats["win_rate"] == 1.0
    assert stats["payoff_ratio"] is None
    assert stats["expectancy"] == stats["avg_ret"]


def test_apply_rank_caps_to_scored_results_demotes_selected_and_limits_near_miss() -> None:
    results = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D", "E", "F"],
            "score_profile": [0.80, 0.70, 0.65, 0.60, 0.50, 0.45],
            "next_ret": [1.0, 0.5, -0.2, 0.3, -0.1, 0.2],
        }
    )
    selected, near_miss = _apply_rank_caps_to_scored_results(
        results,
        score_col="score_profile",
        select_threshold=0.60,
        near_miss_threshold=0.45,
        selected_rank_cap=2,
        near_miss_rank_cap=4,
        selected_rank_cap_ratio=0.0,
        near_miss_rank_cap_ratio=0.0,
    )

    assert selected["ts_code"].tolist() == ["A", "B"]
    assert near_miss["ts_code"].tolist() == ["C", "D"]
    assert "E" not in near_miss["ts_code"].tolist()


def test_apply_rank_caps_to_scored_results_supports_ratio_caps() -> None:
    results = pd.DataFrame(
        {
            "ts_code": [f"T{i:03d}" for i in range(1, 101)],
            "score_profile": [1.0 - (i * 0.005) for i in range(100)],
            "next_ret": [0.1 for _ in range(100)],
        }
    )
    selected, near_miss = _apply_rank_caps_to_scored_results(
        results,
        score_col="score_profile",
        select_threshold=0.60,
        near_miss_threshold=0.45,
        selected_rank_cap=0,
        near_miss_rank_cap=0,
        selected_rank_cap_ratio=0.05,
        near_miss_rank_cap_ratio=0.12,
    )

    assert len(selected) == 5
    assert len(near_miss) == 7
