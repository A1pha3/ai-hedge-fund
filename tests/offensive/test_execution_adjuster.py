"""执行成本调整测试 — v2 P0 关键模块。

验证: 涨停次日不可买 → 剔除样本; T+1 锁; 滑点扣减。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.screening.offensive.execution_adjuster import (
    ExecutionConfig,
    adjust_returns,
    is_limit_up_unbuyable_next_day,
)


def _prices(ticker, dates, closes):
    """构造价格 DataFrame: date, close, open, high, low, pct_change。"""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "close": closes,
            "open": closes,  # 简化: open=close
            "high": [c * 1.02 for c in closes],
            "low": [c * 0.98 for c in closes],
            "pct_change": [0.0] + [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))],
        }
    )


def test_limit_up_next_day_unbuyable_detected():
    """触发日涨停 (pct_change≈+10%) 且次日开盘仍涨停 → 不可买。"""
    prices = _prices("X", ["2026-07-01", "2026-07-02"], [10.0, 11.0])
    prices.loc[0, "pct_change"] = 10.0  # T 日涨停
    prices.loc[1, "open"] = 12.1  # T+1 开盘 = 11.0 × 1.10 (继续涨停)
    assert is_limit_up_unbuyable_next_day(prices, trigger_idx=0) is True


def test_limit_up_but_next_day_buyable():
    """触发日涨停, 但次日开盘低于涨停价 → 可买 (低开/平开/小高开)。"""
    prices = _prices("X", ["2026-07-01", "2026-07-02"], [10.0, 11.0])
    prices.loc[0, "pct_change"] = 10.0  # T 涨停 (close=10.0)
    # T+1 涨停价 = 10.0 × 1.10 = 11.0; open=10.5 < 11.0 → 可买
    prices.loc[1, "open"] = 10.5
    assert is_limit_up_unbuyable_next_day(prices, trigger_idx=0) is False


def test_adjust_returns_applies_slippage():
    """无涨停问题: T+5 收益扣 2× slippage (买卖两端)。"""
    prices = _prices("X", ["2026-07-0" + str(i) for i in range(1, 8)], [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.3])
    config = ExecutionConfig(slippage_bps=30, limit_up_unbuyable=False, t_plus_1_lock=False)
    result = adjust_returns(
        trigger_dates=["20260701"],
        tickers=["X"],
        prices_by_ticker={"X": prices},
        horizon=5,
        config=config,
    )
    assert len(result) == 1
    assert result[0] < 0.05  # 扣滑点后低于名义 +5%
    assert result[0] > 0.03  # 但仍为正


def test_adjust_returns_skips_unbuyable():
    """触发日涨停 + 次日继续涨停 → 样本被剔除 (返回 NaN)。"""
    prices = _prices("X", ["2026-07-01", "2026-07-02"], [10.0, 11.0])
    prices.loc[0, "pct_change"] = 10.0
    prices.loc[1, "open"] = 12.1  # 次日继续涨停
    config = ExecutionConfig(slippage_bps=30, limit_up_unbuyable=True, t_plus_1_lock=False)
    result = adjust_returns(
        trigger_dates=["20260701"],
        tickers=["X"],
        prices_by_ticker={"X": prices},
        horizon=1,
        config=config,
    )
    assert len(result) == 1
    assert np.isnan(result[0])


def test_star_market_20pct_limit_up_next_day_unbuyable():
    """科创板 +20% 真涨停, 次日开盘继续涨停 (+20%) → 不可买.

    Bug A 回归: 旧固定 9.5% 判涨停时, 次日开盘 +20% 当然 > trigger_close*1.095
    所以能判对. 但板块自适应后涨停阈值是 19.5%, 需验证 20% 板的「真涨停」
    次日继续涨停仍被正确识别为不可买 (倍数 = 1+19.5/100 = 1.195).
    """
    prices = _prices("688037", ["2026-07-01", "2026-07-02"], [10.0, 12.0])
    prices.loc[0, "pct_change"] = 20.0  # T 日 20% 板涨停
    prices.loc[1, "open"] = 14.4  # T+1 开盘 = 12.0 × 1.20 (继续涨停)
    assert is_limit_up_unbuyable_next_day(prices, trigger_idx=0, ticker="688037") is True


def test_star_market_15pct_not_limit_up_so_buyable():
    """科创板 +15% 非涨停 (20% 板) → 不触发「涨停不可买」逻辑, 可买.

    Bug A 回归: 旧固定 9.5% 会把 +15% 判为涨停 → 若次日开盘 +13% (>1.095)
    会错误判为不可买, 剔除实际可买样本. 板块自适应后 +15% < 19.5% 阈值,
    不进涨停判定 → 可买.
    """
    prices = _prices("688037", ["2026-07-01", "2026-07-02"], [10.0, 11.5])
    prices.loc[0, "pct_change"] = 15.0  # T 日 +15% (非涨停)
    prices.loc[1, "open"] = 13.0  # T+1 开盘 +13% (旧逻辑会判不可买)
    assert is_limit_up_unbuyable_next_day(prices, trigger_idx=0, ticker="688037") is False
