"""Tests for src.screening.ticker_horizon_stats — per-ticker multi-horizon stats.

T+5/T+10 per-ticker winrate/payoff/expectancy 纯函数 helper. 与
historical_prior_opportunity._summarize_next_close_payoff 的 T+1 算法
同口径 (avg_win/avg_loss_abs), 保证 T+1 与 T+5/T+10 数字可比.

关联: C219 (tracking_history 回填 7993 records + 7201 mature),
C220 (BUY gate horizon T+5/T+10 OR), C221 (signal_horizon 呈现层).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.ticker_horizon_stats import (
    TickerHorizonStats,
    compute_ticker_horizon_stats,
    load_tracking_records,
)


# ---------------------------------------------------------------------------
# 纯函数测试 — compute_ticker_horizon_stats
# ---------------------------------------------------------------------------


def _rec(
    *,
    ticker: str = "002463",
    t5: float | None = None,
    t10: float | None = None,
    t30: float | None = None,
) -> dict:
    """Build a minimal tracking_history record dict for tests."""
    return {
        "ticker": ticker,
        "recommended_date": "20260601",
        "next_5day_return": t5,
        "next_10day_return": t10,
        "next_30day_return": t30,
    }


class TestComputeTickerHorizonStats:
    """per-ticker × per-horizon winrate/payoff/expectancy 纯函数."""

    def test_empty_records_returns_empty_stats_for_all_horizons(self) -> None:
        stats = compute_ticker_horizon_stats([], "002463")
        assert set(stats.keys()) == {"t5", "t10"}
        for horizon_stats in stats.values():
            assert horizon_stats.sample_count == 0
            assert horizon_stats.winrate is None
            assert horizon_stats.payoff_ratio is None
            assert horizon_stats.expectancy is None

    def test_no_matching_ticker_returns_empty_stats(self) -> None:
        records = [_rec(ticker="688008", t5=1.5, t10=2.0)]
        stats = compute_ticker_horizon_stats(records, "002463")
        assert stats["t5"].sample_count == 0
        assert stats["t10"].sample_count == 0

    def test_filters_by_ticker_correctly(self) -> None:
        records = [
            _rec(ticker="002463", t5=1.5, t10=2.0),
            _rec(ticker="688008", t5=0.8, t10=-1.0),
            _rec(ticker="002463", t5=-0.5, t10=1.0),
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        assert stats["t5"].sample_count == 2  # 只算 002463 的
        assert stats["t10"].sample_count == 2

    def test_skips_none_return_values(self) -> None:
        records = [
            _rec(ticker="002463", t5=1.5, t10=None),
            _rec(ticker="002463", t5=None, t10=2.0),
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        assert stats["t5"].sample_count == 1  # 只 1 条有 t5 数据
        assert stats["t10"].sample_count == 1

    def test_winrate_is_positive_count_over_total(self) -> None:
        records = [
            _rec(ticker="002463", t5=1.5, t10=2.0),
            _rec(ticker="002463", t5=-0.5, t10=1.0),
            _rec(ticker="002463", t5=0.8, t10=-1.0),
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        assert stats["t5"].winrate == pytest.approx(2 / 3, abs=0.01)  # 2/3 正收益
        assert stats["t5"].positive_count == 2
        assert stats["t5"].negative_count == 1

    def test_payoff_ratio_is_avg_win_over_avg_loss_abs(self) -> None:
        records = [
            _rec(ticker="002463", t5=2.0, t10=4.0),
            _rec(ticker="002463", t5=-1.0, t10=-2.0),
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        # avg_win=2.0, avg_loss_abs=1.0 → payoff_ratio=2.0
        assert stats["t5"].payoff_ratio == pytest.approx(2.0, abs=0.01)
        # avg_win=4.0, avg_loss_abs=2.0 → payoff_ratio=2.0
        assert stats["t10"].payoff_ratio == pytest.approx(2.0, abs=0.01)

    def test_payoff_ratio_none_when_no_losses(self) -> None:
        records = [
            _rec(ticker="002463", t5=1.5, t10=2.0),
            _rec(ticker="002463", t5=0.8, t10=1.0),
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        assert stats["t5"].payoff_ratio is None  # 无亏损样本
        assert stats["t5"].winrate == 1.0  # 100% 胜率

    def test_expectancy_is_mean_of_returns(self) -> None:
        records = [
            _rec(ticker="002463", t5=2.0, t10=4.0),
            _rec(ticker="002463", t5=-1.0, t10=-2.0),
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        assert stats["t5"].expectancy == pytest.approx(0.5, abs=0.01)  # (2.0 + -1.0) / 2
        assert stats["t10"].expectancy == pytest.approx(1.0, abs=0.01)  # (4.0 + -2.0) / 2

    def test_custom_horizons_parameter(self) -> None:
        records = [
            _rec(ticker="002463", t5=1.5, t10=2.0, t30=3.0),
        ]
        stats = compute_ticker_horizon_stats(records, "002463", horizons=("t5", "t10", "t30"))
        assert set(stats.keys()) == {"t5", "t10", "t30"}
        assert stats["t30"].sample_count == 1
        assert stats["t30"].winrate == 1.0

    def test_invalid_horizon_raises_key_error(self) -> None:
        records = [_rec(ticker="002463", t5=1.5)]
        with pytest.raises(KeyError):
            compute_ticker_horizon_stats(records, "002463", horizons=("t99",))

    def test_non_numeric_return_skipped_silently(self) -> None:
        records = [
            {"ticker": "002463", "next_5day_return": "invalid"},  # type: ignore[dict-item]
            {"ticker": "002463", "next_5day_return": 1.5},
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        assert stats["t5"].sample_count == 1  # 非数字被跳过
        assert stats["t5"].winrate == 1.0

    def test_ticker_match_is_string_exact(self) -> None:
        records = [
            _rec(ticker="002463", t5=1.5),
            {"ticker": 2463, "next_5day_return": 2.0},  # type: ignore[dict-item]  # int ticker
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        assert stats["t5"].sample_count == 1  # 只匹配 str "002463"

    def test_stats_are_frozen_dataclass(self) -> None:
        stats = compute_ticker_horizon_stats([], "002463")
        with pytest.raises(Exception):  # FrozenInstanceError
            stats["t5"].winrate = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# C251 — NaN/Inf guard (sibling alignment with regime_winrate_recompute._optional_float)
# ---------------------------------------------------------------------------


class TestNanInfGuard:
    """NaN/Inf 在 returns 中应被过滤, 不污染 winrate/expectancy.

    Background (C251, d3ad07ac 引入的 fresh code latent defect):
      `_collect_ticker_horizon_returns` 用 `float(value)` + `(TypeError,
      ValueError)` guard, 但 `float(NaN)` 不抛异常 → NaN 进 returns →
      `_summarize_returns` 的 `statistics.mean(returns)` 传播 NaN →
      expectancy=NaN, winrate 分母被稀释. 与 sibling
      `regime_winrate_recompute._optional_float` 的 NaN/Inf guard 不一致.
    """

    def test_nan_return_skipped_does_not_pollute_expectancy(self) -> None:
        """NaN 在 returns 中应被过滤; 不应传播到 expectancy."""
        import math

        records = [
            {"ticker": "002463", "next_5day_return": 1.5},
            {"ticker": "002463", "next_5day_return": float("nan")},
            {"ticker": "002463", "next_5day_return": 2.5},
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        # NaN 应被过滤 → sample_count=2, expectancy=(1.5+2.5)/2=2.0
        assert stats["t5"].sample_count == 2, (
            f"NaN 应被过滤, sample_count=2; got {stats['t5'].sample_count}"
        )
        assert stats["t5"].expectancy == pytest.approx(2.0, abs=0.01), (
            f"NaN 过滤后 expectancy=2.0; got {stats['t5'].expectancy}"
        )
        assert not math.isnan(stats["t5"].expectancy), "expectancy 不应是 NaN"

    def test_nan_return_skipped_does_not_dilute_winrate(self) -> None:
        """NaN 不应进入分母稀释 winrate."""
        records = [
            {"ticker": "002463", "next_5day_return": 1.5},  # win
            {"ticker": "002463", "next_5day_return": float("nan")},  # 应过滤
            {"ticker": "002463", "next_5day_return": -0.5},  # loss
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        # NaN 过滤后: 1 win / 2 total = 0.5; BUG: NaN 不过滤 → 1/3 = 0.333
        assert stats["t5"].winrate == pytest.approx(0.5, abs=0.01), (
            f"NaN 过滤后 winrate=0.5; got {stats['t5'].winrate} (NaN 稀释分母 bug)"
        )

    def test_inf_return_skipped_does_not_pollute_stats(self) -> None:
        """Inf 在 returns 中应被过滤."""
        records = [
            {"ticker": "002463", "next_5day_return": 1.5},
            {"ticker": "002463", "next_5day_return": float("inf")},
            {"ticker": "002463", "next_5day_return": float("-inf")},
            {"ticker": "002463", "next_5day_return": 2.5},
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        # Inf 应被过滤 → sample_count=2
        assert stats["t5"].sample_count == 2, (
            f"Inf 应被过滤, sample_count=2; got {stats['t5'].sample_count}"
        )
        assert stats["t5"].expectancy == pytest.approx(2.0, abs=0.01)

    def test_all_nan_returns_yields_empty_stats(self) -> None:
        """全部 NaN → sample_count=0 (regression guard)."""
        records = [
            {"ticker": "002463", "next_5day_return": float("nan")},
            {"ticker": "002463", "next_5day_return": float("nan")},
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        assert stats["t5"].sample_count == 0
        assert stats["t5"].winrate is None
        assert stats["t5"].expectancy is None

    def test_string_nan_skipped_silently(self) -> None:
        """字符串 'nan' 转 float 后也应被过滤 (regression guard for float('nan'))."""
        records = [
            {"ticker": "002463", "next_5day_return": "nan"},  # float("nan")=NaN
            {"ticker": "002463", "next_5day_return": 1.5},
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        assert stats["t5"].sample_count == 1, (
            f"'nan' 转 float 后应被过滤, sample_count=1; got {stats['t5'].sample_count}"
        )
        assert stats["t5"].winrate == 1.0

    def test_valid_floats_pass_through_unchanged(self) -> None:
        """合法 float (含 0.0, 负数) 不受影响 (regression guard)."""
        records = [
            {"ticker": "002463", "next_5day_return": 0.0},  # 0.0 合法, 不是 NaN
            {"ticker": "002463", "next_5day_return": -1.5},
            {"ticker": "002463", "next_5day_return": 2.5},
        ]
        stats = compute_ticker_horizon_stats(records, "002463")
        assert stats["t5"].sample_count == 3  # 0.0 不被过滤
        assert stats["t5"].winrate == pytest.approx(1 / 3, abs=0.01)  # 只有 2.5 是 win
        assert stats["t5"].expectancy == pytest.approx((0.0 + -1.5 + 2.5) / 3, abs=0.01)


# ---------------------------------------------------------------------------
# Loader 测试 — load_tracking_records
# ---------------------------------------------------------------------------


class TestLoadTrackingRecords:
    """tracking_history.json loader (I/O 分离)."""

    def test_returns_empty_list_when_file_missing(self, tmp_path: Path) -> None:
        result = load_tracking_records(tmp_path)
        assert result == []

    def test_loads_records_from_valid_json(self, tmp_path: Path) -> None:
        tracking_data = {
            "records": [
                {"ticker": "002463", "next_5day_return": 1.5},
                {"ticker": "688008", "next_5day_return": 2.0},
            ],
            "updated_at": "2026-06-29T00:00:00",
        }
        (tmp_path / "tracking_history.json").write_text(
            json.dumps(tracking_data), encoding="utf-8"
        )
        result = load_tracking_records(tmp_path)
        assert len(result) == 2
        assert result[0]["ticker"] == "002463"

    def test_returns_empty_list_when_records_key_missing(self, tmp_path: Path) -> None:
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"updated_at": "2026-06-29"}), encoding="utf-8"
        )
        result = load_tracking_records(tmp_path)
        assert result == []

    def test_returns_empty_list_when_json_corrupted(self, tmp_path: Path) -> None:
        (tmp_path / "tracking_history.json").write_text(
            "not valid json {{{", encoding="utf-8"
        )
        result = load_tracking_records(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# 集成测试 — end-to-end with realistic data
# ---------------------------------------------------------------------------


class TestIntegrationWithRealisticData:
    """端到端: 合成 records 模拟真实 tracking_history 结构."""

    def test_realistic_scenario_multiple_tickers_multiple_horizons(self) -> None:
        records = [
            _rec(ticker="002463", t5=1.5, t10=2.0, t30=3.0),
            _rec(ticker="002463", t5=-0.5, t10=1.0, t30=-1.0),
            _rec(ticker="002463", t5=0.8, t10=-0.3, t30=2.5),
            _rec(ticker="688008", t5=2.0, t10=3.0, t30=5.0),
            _rec(ticker="688008", t5=None, t10=None, t30=None),  # 未 mature
        ]
        stats_002463 = compute_ticker_horizon_stats(records, "002463")
        stats_688008 = compute_ticker_horizon_stats(records, "688008")

        # 002463: 3 条 mature (T+5/T+10), winrate 2/3
        assert stats_002463["t5"].sample_count == 3
        assert stats_002463["t5"].winrate == pytest.approx(2 / 3, abs=0.01)
        assert stats_002463["t10"].sample_count == 3

        # 688008: 1 条 mature (T+5/T+10), winrate 1/1
        assert stats_688008["t5"].sample_count == 1
        assert stats_688008["t5"].winrate == 1.0
