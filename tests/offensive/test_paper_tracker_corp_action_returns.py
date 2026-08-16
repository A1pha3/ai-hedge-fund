"""除权免疫 realized P&L 回归测试 (autodev 2026-08-16 delivery).

price_cache 存不复权原始价: 持有窗口跨除权日时, 原始价比值把分红/送转造成的
机械跳变读成真实亏损 (分红方向一律低估收益)。三个 realized P&L 计算点

- ``paper_tracker.PaperTracker._execution_adjusted_return``
- ``paper_tracker.PaperTracker._close_to_close_return``
- ``execution_adjuster.adjust_returns``

必须用 pct_change 链还原调整后收益 (AGENTS.md 陷阱 15); pct_change 不可用时
诚实回退原始比值 (与旧口径逐位一致)。
"""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd
import pytest

from src.screening.offensive.execution_adjuster import (
    ExecutionConfig,
    adjust_returns,
)
from src.screening.offensive.paper_tracker import PaperTracker


def _gap_frame() -> pd.DataFrame:
    """D0 10.00 → D1 +2% → D2 除权日 (每股派 0.50, 除权基准 9.70, 真实 -2%).

    raw close[D2] = 9.506; raw 比值 9.506/10.20-1 = -6.80% vs 真实 -2.00%,
    偏差 4.8pp 全部来自除权缺口 — 复现 002378@2024-05-28 类陷阱。
    """
    return pd.DataFrame(
        {
            "date": [
                datetime(2024, 5, 20),
                datetime(2024, 5, 21),
                datetime(2024, 5, 22),
            ],
            "open": [10.00, 10.10, 9.60],
            "close": [10.00, 10.20, 9.506],
            "pct_change": [1.0, 2.0, -2.0],
        }
    )


class TestExecutionAdjustedReturn:
    def test_exit_leg_uses_pct_change_chain(self) -> None:
        frame = _gap_frame()
        result = PaperTracker._execution_adjusted_return(frame, "20240520", 2)
        assert result is not None
        realized, exit_price = result
        slip = ExecutionConfig().slippage_bps / 10_000.0
        expected_exit = 10.20 * (1.0 - 0.02) * (1.0 - slip)
        expected = expected_exit / (10.10 * (1.0 + slip)) - 1.0
        assert realized == pytest.approx(expected, abs=1e-12)
        assert exit_price == pytest.approx(expected_exit, abs=1e-12)
        # fixture 自检: 缺口造成的 raw/链口径偏差必须显著 (>0.5pp)
        raw = (9.506 * (1.0 - slip)) / (10.10 * (1.0 + slip)) - 1.0
        assert abs(expected - raw) > 0.005

    def test_same_day_exit_keeps_raw_ratio(self) -> None:
        """horizon=1 → exit==entry 日内, 无跨日缺口, 保持原始 close/open。"""
        frame = _gap_frame()
        result = PaperTracker._execution_adjusted_return(frame, "20240520", 1)
        assert result is not None
        realized, _ = result
        slip = ExecutionConfig().slippage_bps / 10_000.0
        expected = (10.20 * (1.0 - slip)) / (10.10 * (1.0 + slip)) - 1.0
        assert realized == pytest.approx(expected, abs=1e-12)


class TestCloseToCloseReturn:
    def test_realized_equals_chain(self) -> None:
        frame = _gap_frame()
        result = PaperTracker._close_to_close_return(frame, "20240520", 2)
        assert result is not None
        realized, exit_price = result
        chain = 1.02 * 0.98 - 1.0  # D1→D2 pct 链
        assert realized == pytest.approx(chain, abs=1e-12)
        assert exit_price == pytest.approx(10.00 * (1.0 + chain), abs=1e-12)
        raw = 9.506 / 10.00 - 1.0
        assert abs(chain - raw) > 0.005  # fixture 自检


class TestAdjustReturns:
    def test_exit_leg_uses_pct_change_chain(self) -> None:
        frame = _gap_frame()
        config = ExecutionConfig(slippage_bps=30)
        out = adjust_returns(["20240520"], ["600000"], {"600000": frame}, 2, config)
        assert not math.isnan(out[0])
        slip = 0.003
        expected = (10.20 * 0.98 * (1.0 - slip)) / (10.10 * (1.0 + slip)) - 1.0
        assert out[0] == pytest.approx(expected, abs=1e-12)
        raw = (9.506 * (1.0 - slip)) / (10.10 * (1.0 + slip)) - 1.0
        assert abs(expected - raw) > 0.005  # fixture 自检


class TestHonestFallback:
    """pct_change 缺失/非有限 → 三函数输出与修复前原始比值口径逐位一致。"""

    def test_missing_pct_change_column_bit_exact(self) -> None:
        frame = _gap_frame().drop(columns=["pct_change"])
        slip = ExecutionConfig().slippage_bps / 10_000.0

        result = PaperTracker._execution_adjusted_return(frame, "20240520", 2)
        assert result is not None
        entry_price = 10.10 * (1.0 + slip)
        exit_price = 9.506 * (1.0 - slip)
        assert result[0] == (exit_price / entry_price) - 1.0
        assert result[1] == exit_price

        result = PaperTracker._close_to_close_return(frame, "20240520", 2)
        assert result is not None
        assert result[0] == (9.506 / 10.00) - 1.0
        assert result[1] == 9.506

        config = ExecutionConfig(slippage_bps=30)
        out = adjust_returns(["20240520"], ["600000"], {"600000": frame}, 2, config)
        assert not math.isnan(out[0])
        assert out[0] == pytest.approx(
            (9.506 * (1.0 - 0.003)) / (10.10 * (1.0 + 0.003)) - 1.0, abs=1e-15
        )

    def test_non_finite_pct_in_window_falls_back(self) -> None:
        frame = _gap_frame().copy()
        frame.loc[frame.index[-1], "pct_change"] = float("nan")
        slip = ExecutionConfig().slippage_bps / 10_000.0

        result = PaperTracker._execution_adjusted_return(frame, "20240520", 2)
        assert result is not None
        entry_price = 10.10 * (1.0 + slip)
        exit_price = 9.506 * (1.0 - slip)
        assert result[0] == (exit_price / entry_price) - 1.0

        result = PaperTracker._close_to_close_return(frame, "20240520", 2)
        assert result is not None
        assert result[0] == (9.506 / 10.00) - 1.0


class TestUnrealizedPctCorpActionImmunity:
    """open_positions_detail 的 unrealized_pct 除权免疫 (autodev 2026-08-16 第三轮).

    持有中仓位的浮动盈亏此前用 latest_close/entry_price 原始价比值, 跨除权日
    显示幻影跳变 (10送10 后真实 +36.7% 显示 -67% 类)。修复: 窗口检出缺口时用
    pct_change 链口径; 无缺口 (±0.5% 容差) 或链不可用时保持原始比值 (逐位一致)。
    """

    @staticmethod
    def _tracker_with_buy(tmp_path, entry_price: float = 10.0) -> PaperTracker:
        tracker = PaperTracker(tmp_path / "journal_dir")
        tracker.record_buy(
            "20240520",
            "600000",
            "btst_breakout",
            10,
            entry_price,
            0.08,
            -0.05,
            -0.08,
            "test",
        )
        return tracker

    @staticmethod
    def _held_gap_frame() -> pd.DataFrame:
        """D0 close 10.00 买入持有; D1 +2%; D2 除权 (10送10) 真实 +5%.

        raw close[D2] = 10.20*1.05/2 = 5.355; raw 比值 5.355/10-1 = -46.45%
        vs 真实 +7.1% (close[D0]→close[D2] 链 = 1.02*1.05-1) — 幻影全部来自缺口。
        """
        return pd.DataFrame(
            {
                "date": ["20240520", "20240521", "20240522"],
                "close": [10.00, 10.20, 5.355],
                "pct_change": [1.0, 2.0, 5.0],
            }
        )

    def test_held_gap_uses_chain_basis(self, tmp_path) -> None:
        tracker = self._tracker_with_buy(tmp_path)
        frame = self._held_gap_frame()

        details = tracker.open_positions_detail(
            as_of="20240522", price_loader=lambda _t, _d: frame
        )

        assert len(details) == 1
        expected = (1.02 * 1.05) * (10.00 / 10.0) - 1.0  # close[buy]=entry_price
        assert details[0]["unrealized_pct"] == pytest.approx(expected, abs=1e-12)
        # fixture 自检: raw 比值与链口径偏差必须显著 (>0.5pp)
        raw = 5.355 / 10.0 - 1.0
        assert abs(expected - raw) > 0.005

    def test_no_gap_frame_keeps_raw_ratio_bitwise(self, tmp_path) -> None:
        tracker = self._tracker_with_buy(tmp_path)
        frame = self._held_gap_frame()
        # 无缺口: close 比值与 pct_change 完全一致 (除权比 1.0)
        frame.loc[2, "close"] = 10.20 * 1.05
        frame.loc[2, "pct_change"] = 5.0

        details = tracker.open_positions_detail(
            as_of="20240522", price_loader=lambda _t, _d: frame
        )

        raw = 10.20 * 1.05 / 10.0 - 1.0
        assert details[0]["unrealized_pct"] == raw  # 逐位一致, 非 approx

    def test_missing_pct_change_keeps_raw_ratio_bitwise(self, tmp_path) -> None:
        tracker = self._tracker_with_buy(tmp_path)
        frame = self._held_gap_frame().drop(columns=["pct_change"])

        details = tracker.open_positions_detail(
            as_of="20240522", price_loader=lambda _t, _d: frame
        )

        raw = 5.355 / 10.0 - 1.0
        assert details[0]["unrealized_pct"] == raw  # 回退: 与旧口径逐位一致
