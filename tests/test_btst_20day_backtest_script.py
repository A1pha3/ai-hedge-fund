from __future__ import annotations

import sys
from datetime import datetime as real_datetime
from types import SimpleNamespace

import pandas as pd
import pytest

import scripts.btst_20day_backtest as btst_20day_backtest
from scripts.btst_20day_backtest import (
    _apply_rank_caps_to_scored_results,
    _build_profile_leaderboard,
    _build_profiles,
    _parse_profile_names,
    compute_score,
    DEFAULT_PROFILE_NAMES,
    PROFILE_WEIGHT_FIELDS,
    PROFILES,
    summarize_return_stats,
)
from src.targets import build_short_trade_target_profile, get_short_trade_target_profile


def test_main_falls_back_to_akshare_trade_calendar_when_tushare_calendar_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class FixedDateTime:
        @classmethod
        def now(cls) -> real_datetime:
            return real_datetime(2026, 4, 22)

    class FakePro:
        def trade_cal(self, **kwargs) -> pd.DataFrame:
            return pd.DataFrame()

        def stock_basic(self, **kwargs) -> pd.DataFrame:
            raise RuntimeError("after-calendar")

    monkeypatch.setattr(btst_20day_backtest, "datetime", FixedDateTime)
    monkeypatch.setenv("TUSHARE_TOKEN", "")

    import akshare as ak
    monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(set_token=lambda _token: None, pro_api=lambda: FakePro()))
    monkeypatch.setattr(
        ak,
        "tool_trade_date_hist_sina",
        lambda: pd.DataFrame({"trade_date": pd.to_datetime(["2026-04-20", "2026-04-21", "2026-04-22"])}),
    )
    monkeypatch.setattr(
        btst_20day_backtest.argparse.ArgumentParser,
        "parse_args",
        lambda self: btst_20day_backtest.argparse.Namespace(
            profiles="default",
            output_json=str(tmp_path / "backtest.json"),
            profile_overrides_json=None,
        ),
    )

    with pytest.raises(RuntimeError, match="after-calendar"):
        btst_20day_backtest.main()


def test_momentum_tuned_profile_uses_rank_cap_for_executability() -> None:
    profile = get_short_trade_target_profile("momentum_tuned")

    assert profile.select_threshold == 0.38
    assert profile.near_miss_threshold == 0.24
    assert profile.selected_rank_cap_ratio == 0.50


def test_build_profiles_rejects_unmodeled_penalty_overrides() -> None:
    with pytest.raises(ValueError, match="not modeled by btst_20day_backtest.py"):
        _build_profiles(("momentum_tuned",), profile_overrides={"overhead_score_penalty_weight": 0.07})


def test_build_profiles_keeps_inherited_close_retention_and_gap_controls_for_momentum_tuned() -> None:
    config = _build_profiles(("momentum_tuned",))["momentum_tuned"]
    source_profile = get_short_trade_target_profile("momentum_tuned")

    assert config["selected_close_retention_min"] == source_profile.selected_close_retention_min
    assert config["selected_close_retention_threshold_lift"] == source_profile.selected_close_retention_threshold_lift
    assert config["selected_breakout_close_gap_max"] == source_profile.selected_breakout_close_gap_max
    assert config["selected_breakout_close_gap_threshold_lift"] == source_profile.selected_breakout_close_gap_threshold_lift


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
        assert config["selected_close_retention_min"] == source_profile.selected_close_retention_min
        assert config["selected_close_retention_threshold_lift"] == source_profile.selected_close_retention_threshold_lift
        assert config["selected_breakout_close_gap_max"] == source_profile.selected_breakout_close_gap_max
        assert config["selected_breakout_close_gap_threshold_lift"] == source_profile.selected_breakout_close_gap_threshold_lift
        assert config["selected_close_retention_penalty_weight"] == source_profile.selected_close_retention_penalty_weight
        for factor_name, weight_field in PROFILE_WEIGHT_FIELDS.items():
            assert config["weights"][factor_name] == getattr(source_profile, weight_field)


def test_module_profiles_stay_in_sync_with_builder_output() -> None:
    assert PROFILES == _build_profiles()


def test_build_profiles_applies_profile_overrides() -> None:
    overrides = {
        "short_term_reversal_weight": 0.50,
        "historical_continuation_score_weight": 0.08,
        "selected_rank_cap_ratio": 0.14,
    }

    profiles = _build_profiles(("btst_precision_v2",), profile_overrides=overrides)
    source_profile = build_short_trade_target_profile("btst_precision_v2", overrides=overrides)

    config = profiles["btst_precision_v2"]
    assert config["selected_rank_cap_ratio"] == source_profile.selected_rank_cap_ratio
    assert config["weights"]["reversal"] == source_profile.short_term_reversal_weight
    assert config["weights"]["historical_continuation_score"] == source_profile.historical_continuation_score_weight


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


def test_apply_rank_caps_to_scored_results_raises_selected_threshold_for_weak_close_retention() -> None:
    results = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C"],
            "score_profile": [0.39, 0.37, 0.31],
            "breakout_freshness": [0.55, 0.48, 0.40],
            "trend_acceleration": [0.52, 0.42, 0.36],
            "volume_expansion_quality": [0.58, 0.41, 0.33],
            "close_strength": [0.20, 0.62, 0.44],
            "layer_c_alignment": [0.26, 0.60, 0.42],
            "next_ret": [1.0, 0.5, -0.2],
        }
    )
    baseline_selected, baseline_near_miss = _apply_rank_caps_to_scored_results(
        results,
        score_col="score_profile",
        select_threshold=0.34,
        near_miss_threshold=0.26,
        selected_rank_cap=10,
        near_miss_rank_cap=10,
    )
    tightened_selected, tightened_near_miss = _apply_rank_caps_to_scored_results(
        results,
        score_col="score_profile",
        select_threshold=0.34,
        near_miss_threshold=0.26,
        selected_rank_cap=10,
        near_miss_rank_cap=10,
        selected_close_retention_min=0.44,
        selected_close_retention_threshold_lift=0.035,
        selected_breakout_close_gap_max=0.18,
        selected_breakout_close_gap_threshold_lift=0.025,
    )

    assert baseline_selected["ts_code"].tolist() == ["A", "B"]
    assert baseline_near_miss["ts_code"].tolist() == ["C"]
    assert tightened_selected["ts_code"].tolist() == ["B"]
    assert tightened_near_miss["ts_code"].tolist() == ["A", "C"]


def test_compute_score_penalizes_weak_close_retention_breakout_chase() -> None:
    factors = {
        "breakout_freshness": 0.62,
        "trend_acceleration": 0.58,
        "volume_expansion_quality": 0.54,
        "close_strength": 0.20,
        "sector_resonance": 0.30,
        "catalyst_freshness": 0.24,
        "layer_c_alignment": 0.28,
        "momentum_strength": 0.55,
        "reversal": 0.10,
        "intraday_strength": 0.18,
        "reversal_2d": 0.12,
    }
    weights = {
        "breakout_freshness": 0.20,
        "trend_acceleration": 0.20,
        "volume_expansion_quality": 0.10,
        "close_strength": 0.10,
        "sector_resonance": 0.10,
        "catalyst_freshness": 0.10,
        "layer_c_alignment": 0.10,
        "momentum_strength": 0.05,
        "reversal": 0.0,
        "intraday_strength": 0.025,
        "reversal_2d": 0.025,
    }

    baseline_score = compute_score(factors, weights)
    penalized_score = compute_score(
        factors,
        weights,
        selected_close_retention_min=0.46,
        selected_breakout_close_gap_max=0.16,
        selected_close_retention_penalty_weight=0.06,
    )

    assert penalized_score < baseline_score
    assert penalized_score == pytest.approx(baseline_score - 0.06, abs=1e-4)


def test_compute_score_adds_historical_continuation_factor_weight() -> None:
    factors = {
        "breakout_freshness": 0.62,
        "trend_acceleration": 0.58,
        "volume_expansion_quality": 0.54,
        "close_strength": 0.45,
        "sector_resonance": 0.30,
        "catalyst_freshness": 0.24,
        "layer_c_alignment": 0.28,
        "historical_continuation_score": 0.80,
        "momentum_strength": 0.55,
        "reversal": 0.10,
        "intraday_strength": 0.18,
        "reversal_2d": 0.12,
    }
    weights = {
        "breakout_freshness": 0.20,
        "trend_acceleration": 0.20,
        "volume_expansion_quality": 0.10,
        "close_strength": 0.10,
        "sector_resonance": 0.10,
        "catalyst_freshness": 0.10,
        "layer_c_alignment": 0.10,
        "historical_continuation_score": 0.08,
        "momentum_strength": 0.05,
        "reversal": 0.0,
        "intraday_strength": 0.025,
        "reversal_2d": 0.025,
    }

    assert compute_score(factors, weights) == pytest.approx(0.481481, abs=1e-4)


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
