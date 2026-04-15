from __future__ import annotations

import pandas as pd

from scripts.btst_20day_backtest import (
    DEFAULT_PROFILE_NAMES,
    _apply_rank_caps_to_scored_results,
    _build_profile_leaderboard,
    _build_profiles,
    _parse_profile_names,
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
        assert config["selected_rank_cap_relief_score_margin_min"] == source_profile.selected_rank_cap_relief_score_margin_min
        assert config["selected_rank_cap_relief_rank_buffer"] == source_profile.selected_rank_cap_relief_rank_buffer
        assert config["selected_rank_cap_relief_rank_buffer_ratio"] == source_profile.selected_rank_cap_relief_rank_buffer_ratio
        assert config["selected_rank_cap_relief_sector_resonance_min"] == source_profile.selected_rank_cap_relief_sector_resonance_min
        assert config["selected_rank_cap_relief_close_strength_max"] == source_profile.selected_rank_cap_relief_close_strength_max
        assert config["selected_rank_cap_relief_require_confirmed_breakout"] == source_profile.selected_rank_cap_relief_require_confirmed_breakout
        assert config["selected_rank_cap_relief_allow_risk_off"] == source_profile.selected_rank_cap_relief_allow_risk_off
        assert config["selected_rank_cap_relief_allow_crisis"] == source_profile.selected_rank_cap_relief_allow_crisis
        assert config["selected_breakout_freshness_min"] == source_profile.selected_breakout_freshness_min
        assert config["selected_trend_acceleration_min"] == source_profile.selected_trend_acceleration_min
        for factor_name, weight_field in PROFILE_WEIGHT_FIELDS.items():
            assert config["weights"][factor_name] == getattr(source_profile, weight_field)


def test_module_profiles_stay_in_sync_with_builder_output() -> None:
    assert PROFILES == _build_profiles()


def test_parse_profile_names_defaults_and_deduplicates() -> None:
    assert _parse_profile_names(None) == DEFAULT_PROFILE_NAMES
    assert "btst_precision_v2" in DEFAULT_PROFILE_NAMES
    assert _parse_profile_names("default,default,ic_optimized") == ("default", "ic_optimized")


def test_build_profile_leaderboard_orders_by_avg_return_then_win_rate() -> None:
    all_daily = {
        "alpha": {
            "selected": [
                {"n": 10, "win_rate": 0.40, "avg_ret": -0.30, "big_win_rate": 0.10, "expectancy": -0.30, "downside_p10": -4.0, "payoff_ratio": 1.20},
                {"n": 12, "win_rate": 0.45, "avg_ret": -0.20, "big_win_rate": 0.12, "expectancy": -0.20, "downside_p10": -3.8, "payoff_ratio": 1.30},
            ]
        },
        "beta": {
            "selected": [
                {"n": 8, "win_rate": 0.52, "avg_ret": -0.10, "big_win_rate": 0.08, "expectancy": -0.10, "downside_p10": -3.6, "payoff_ratio": 1.10},
                {"n": 9, "win_rate": 0.50, "avg_ret": -0.15, "big_win_rate": 0.09, "expectancy": -0.15, "downside_p10": -3.5, "payoff_ratio": 1.15},
            ]
        },
    }

    leaderboard = _build_profile_leaderboard(all_daily, group_name="selected")

    assert [row["profile"] for row in leaderboard] == ["beta", "alpha"]
    assert leaderboard[0]["days"] == 2
    assert leaderboard[0]["total_n"] == 17
    assert leaderboard[0]["avg_ret"] > leaderboard[1]["avg_ret"]


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


def test_apply_rank_caps_to_scored_results_soft_relief_keeps_strong_over_cap_selected() -> None:
    results = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D", "E", "F"],
            "score_profile": [0.80, 0.70, 0.65, 0.64, 0.50, 0.45],
            "breakout_freshness": [0.20, 0.18, 0.16, 0.11, 0.08, 0.06],
            "trend_acceleration": [0.25, 0.22, 0.20, 0.17, 0.10, 0.08],
            "close_strength": [0.88, 0.86, 0.90, 0.84, 0.72, 0.70],
            "sector_resonance": [0.18, 0.16, 0.13, 0.09, 0.06, 0.04],
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
        selected_rank_cap_relief_score_margin_min=0.0,
        selected_rank_cap_relief_rank_buffer=2,
        selected_rank_cap_relief_rank_buffer_ratio=0.0,
        selected_rank_cap_relief_sector_resonance_min=0.10,
        selected_rank_cap_relief_close_strength_max=0.95,
        selected_rank_cap_relief_require_confirmed_breakout=True,
        selected_breakout_freshness_min=0.12,
        selected_trend_acceleration_min=0.16,
    )

    assert selected["ts_code"].tolist() == ["A", "B", "C"]
    assert near_miss["ts_code"].tolist() == ["D"]


def test_apply_rank_caps_to_scored_results_soft_relief_respects_sector_floor() -> None:
    results = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D", "E", "F"],
            "score_profile": [0.80, 0.70, 0.65, 0.64, 0.50, 0.45],
            "breakout_freshness": [0.20, 0.18, 0.16, 0.11, 0.08, 0.06],
            "trend_acceleration": [0.25, 0.22, 0.20, 0.17, 0.10, 0.08],
            "close_strength": [0.88, 0.86, 0.90, 0.84, 0.72, 0.70],
            "sector_resonance": [0.18, 0.16, 0.09, 0.09, 0.06, 0.04],
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
        selected_rank_cap_relief_score_margin_min=0.0,
        selected_rank_cap_relief_rank_buffer=2,
        selected_rank_cap_relief_rank_buffer_ratio=0.0,
        selected_rank_cap_relief_sector_resonance_min=0.10,
        selected_rank_cap_relief_close_strength_max=0.95,
        selected_rank_cap_relief_require_confirmed_breakout=True,
        selected_breakout_freshness_min=0.12,
        selected_trend_acceleration_min=0.16,
    )

    assert selected["ts_code"].tolist() == ["A", "B"]
    assert near_miss["ts_code"].tolist() == ["C", "D"]


def test_apply_rank_caps_to_scored_results_soft_relief_respects_close_strength_cap() -> None:
    results = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D", "E", "F"],
            "score_profile": [0.80, 0.70, 0.65, 0.64, 0.50, 0.45],
            "breakout_freshness": [0.20, 0.18, 0.16, 0.11, 0.08, 0.06],
            "trend_acceleration": [0.25, 0.22, 0.20, 0.17, 0.10, 0.08],
            "close_strength": [0.88, 0.86, 0.96, 0.84, 0.72, 0.70],
            "sector_resonance": [0.18, 0.16, 0.13, 0.09, 0.06, 0.04],
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
        selected_rank_cap_relief_score_margin_min=0.0,
        selected_rank_cap_relief_rank_buffer=2,
        selected_rank_cap_relief_rank_buffer_ratio=0.0,
        selected_rank_cap_relief_sector_resonance_min=0.10,
        selected_rank_cap_relief_close_strength_max=0.93,
        selected_rank_cap_relief_require_confirmed_breakout=True,
        selected_breakout_freshness_min=0.12,
        selected_trend_acceleration_min=0.16,
    )

    assert selected["ts_code"].tolist() == ["A", "B"]
    assert near_miss["ts_code"].tolist() == ["C", "D"]


def test_apply_rank_caps_to_scored_results_soft_relief_respects_market_risk_gate() -> None:
    results = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D", "E", "F"],
            "score_profile": [0.80, 0.70, 0.65, 0.64, 0.50, 0.45],
            "breakout_freshness": [0.20, 0.18, 0.16, 0.11, 0.08, 0.06],
            "trend_acceleration": [0.25, 0.22, 0.20, 0.17, 0.10, 0.08],
            "close_strength": [0.88, 0.86, 0.90, 0.84, 0.72, 0.70],
            "sector_resonance": [0.18, 0.16, 0.13, 0.09, 0.06, 0.04],
            "market_risk_level": ["normal", "normal", "risk_off", "normal", "normal", "normal"],
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
        selected_rank_cap_relief_score_margin_min=0.0,
        selected_rank_cap_relief_rank_buffer=2,
        selected_rank_cap_relief_rank_buffer_ratio=0.0,
        selected_rank_cap_relief_sector_resonance_min=0.10,
        selected_rank_cap_relief_close_strength_max=0.95,
        selected_rank_cap_relief_require_confirmed_breakout=True,
        selected_rank_cap_relief_allow_risk_off=False,
        selected_rank_cap_relief_allow_crisis=True,
        selected_breakout_freshness_min=0.12,
        selected_trend_acceleration_min=0.16,
    )

    assert selected["ts_code"].tolist() == ["A", "B"]
    assert near_miss["ts_code"].tolist() == ["C", "D"]
