"""ATR 计算工具测试 — 验证因果 Wilder True Range/RMA + 止损价计算."""

from __future__ import annotations

import pandas as pd
import pytest

from src.screening.offensive.atr_utils import atr_stop_price, compute_atr


def _prices(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
):
    highs = highs or [c * 1.02 for c in closes]
    lows = lows or [c * 0.98 for c in closes]
    return pd.DataFrame({"close": closes, "high": highs, "low": lows})


class TestComputeAtr:
    def test_hand_calculated_wilder_seed_and_recursive_update(self):
        """period=3: seed=mean(1,2,3)=2; next=(2*2+6)/3=10/3."""
        prices = _prices(
            [10.0] * 4,
            [10.5, 11.0, 11.5, 13.0],
            [9.5, 9.0, 8.5, 7.0],
        )

        assert compute_atr(prices, period=3, at_idx=2) is None
        assert compute_atr(prices, period=3, at_idx=3) == pytest.approx(2.0)
        assert compute_atr(prices, period=3, at_idx=4) == pytest.approx(10.0 / 3.0)

    def test_wilder_value_is_prefix_invariant(self):
        prefix = _prices(
            [10.0] * 4,
            [10.5, 11.0, 11.5, 13.0],
            [9.5, 9.0, 8.5, 7.0],
        )
        extended = pd.concat(
            (
                prefix,
                _prices([100.0, 200.0], [110.0, 220.0], [90.0, 180.0]),
            ),
            ignore_index=True,
        )

        assert compute_atr(extended, period=3, at_idx=4) == pytest.approx(
            compute_atr(prefix, period=3)
        )

    def test_duplicate_or_nonmonotonic_prefix_dates_fail_closed(self):
        prices = _prices([10.0] * 4, [10.5] * 4, [9.5] * 4)
        prices["date"] = ["2026-01-01", "2026-01-02", "2026-01-02", "2026-01-04"]
        assert compute_atr(prices, period=3) is None

        prices["date"] = ["2026-01-01", "2026-01-03", "2026-01-02", "2026-01-04"]
        assert compute_atr(prices, period=3) is None

    def test_invalid_future_date_does_not_poison_causal_prefix(self):
        prices = _prices([10.0] * 5, [10.5] * 5, [9.5] * 5)
        prices["date"] = [
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "not-a-date",
        ]

        assert compute_atr(prices, period=3, at_idx=4) == pytest.approx(1.0)
        assert compute_atr(prices, period=3) is None

    def test_constant_range_atr(self):
        """每根 K 线 high-low 恒定 1.0, 无 gap → ATR = 1.0."""
        closes = [10.0] * 25
        highs = [10.5] * 25
        lows = [9.5] * 25
        atr = compute_atr(_prices(closes, highs, lows), period=20)
        assert atr == pytest.approx(1.0, abs=0.01)

    def test_insufficient_data_returns_none(self):
        """数据不足 (len < period+1) → None."""
        atr = compute_atr(_prices([10.0, 11.0, 12.0]), period=20)
        assert atr is None

    def test_missing_columns_returns_none(self):
        """缺 high/low/close 列 → None."""
        df = pd.DataFrame({"close": [10.0] * 25, "high": [10.5] * 25})  # 缺 low
        assert compute_atr(df, period=20) is None

    def test_at_idx_truncates_to_avoid_lookahead(self):
        """at_idx 参数: 只用 [0, at_idx) 的数据算 ATR (回测防未来函数)."""
        closes = [10.0] * 30 + [20.0] * 10  # 后 10 根波动变大
        highs = [10.5] * 30 + [21.0] * 10
        lows = [9.5] * 30 + [19.0] * 10
        # at_idx=30: 只用前 30 根 (波动 1.0) → ATR ≈ 1.0
        atr_before = compute_atr(_prices(closes, highs, lows), period=20, at_idx=30)
        # at_idx=None: seed=1; 跳空 TR=11 后 ATR=1.5; 再递推 9 根 TR=2.
        atr_full = compute_atr(_prices(closes, highs, lows), period=20)
        assert atr_before == pytest.approx(1.0, abs=0.05)
        assert atr_full == pytest.approx(2.0 - 0.5 * (19.0 / 20.0) ** 9)

    def test_gap_increases_tr(self):
        """跳空高开: TR 应含 |high - prev_close| 项 → ATR 增大."""
        closes = [10.0] * 22
        highs = [10.5] * 22
        lows = [9.5] * 22
        # 在倒数第 5 根制造跳空: close 突然到 15, high 15.5, low 14.5
        closes[-5:] = [15.0] * 5
        highs[-5:] = [15.5] * 5
        lows[-5:] = [14.5] * 5
        atr = compute_atr(_prices(closes, highs, lows), period=20)
        # 跳空根的 TR = max(1.0, |15.5-10|=5.5, |14.5-10|=4.5) = 5.5 → ATR 被拉高
        assert atr > 1.0


class TestAtrStopPrice:
    def test_basic_stop(self):
        """entry=100, ATR=5, k=2 → stop = 100 - 2×5 = 90."""
        assert atr_stop_price(100.0, 5.0, k=2.0) == pytest.approx(90.0)

    def test_none_atr_returns_none(self):
        assert atr_stop_price(100.0, None, k=2.0) is None

    def test_zero_atr_returns_none(self):
        assert atr_stop_price(100.0, 0.0, k=2.0) is None

    def test_negative_entry_returns_none(self):
        assert atr_stop_price(-100.0, 5.0, k=2.0) is None

    def test_wider_k_gives_wider_stop(self):
        """k=3 比 k=2 止损更宽 (离 entry 更远)."""
        stop_2 = atr_stop_price(100.0, 5.0, k=2.0)
        stop_3 = atr_stop_price(100.0, 5.0, k=3.0)
        assert stop_3 < stop_2  # 止损价更低 = 离 entry 更远 = 更宽
