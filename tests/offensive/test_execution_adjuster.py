"""执行成本调整测试 — v2 P0 关键模块。

验证: 涨停次日不可买 → 剔除样本; T+1 锁; 滑点扣减。
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.screening.offensive.execution_adjuster import (
    ExecutionConfig,
    ExecutionCosts,
    ExecutionStatus,
    apply_execution_costs,
    adjust_returns,
    classify_open_fill,
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


def test_open_inside_limits_is_executable_proxy():
    result = classify_open_fill(open_price=10.5, limit_down=9.0, limit_up=11.0, suspended=False)
    assert result is ExecutionStatus.EXECUTABLE_PROXY


def test_open_on_limit_is_unknown_queue():
    assert classify_open_fill(11.0, 9.0, 11.0, False) is ExecutionStatus.UNKNOWN_QUEUE


def test_locked_board_is_conservative_unexecutable_proxy():
    assert (
        classify_open_fill(11.0, 9.0, 11.0, False, high=11.0, low=11.0)
        is ExecutionStatus.UNEXECUTABLE_PROXY
    )


@pytest.mark.parametrize(
    ("open_price", "limit_down", "limit_up", "high", "low"),
    [
        (float("nan"), 9.0, 11.0, None, None),
        (10.0, float("inf"), 11.0, None, None),
        (10.0, 9.0, 0.0, None, None),
        (10.0, 11.0, 9.0, None, None),
        (10.0, 9.0, 11.0, float("nan"), 9.5),
        (10.0, 9.0, 11.0, 9.5, -1.0),
        (10.0, 9.0, 11.0, 12.0, 9.5),
        (10.0, 9.0, 11.0, 10.5, 8.0),
    ],
)
def test_invalid_open_or_band_data_is_unknown_queue(open_price, limit_down, limit_up, high, low):
    assert (
        classify_open_fill(open_price, limit_down, limit_up, False, high=high, low=low)
        is ExecutionStatus.UNKNOWN_QUEUE
    )


def test_known_suspension_does_not_override_invalid_price_data():
    assert (
        classify_open_fill(float("nan"), 9.0, 11.0, True)
        is ExecutionStatus.UNKNOWN_QUEUE
    )


def test_limit_comparison_uses_half_tick_tolerance():
    assert classify_open_fill(10.996, 9.0, 11.0, False) is ExecutionStatus.UNKNOWN_QUEUE
    assert classify_open_fill(10.994, 9.0, 11.0, False) is ExecutionStatus.EXECUTABLE_PROXY


def test_locked_board_uses_half_tick_tolerance():
    assert (
        classify_open_fill(10.996, 9.0, 11.0, False, high=11.004, low=10.995)
        is ExecutionStatus.UNEXECUTABLE_PROXY
    )


def test_missing_limit_or_suspension_state_fails_closed():
    assert classify_open_fill(10.0, None, 11.0, False) is ExecutionStatus.UNKNOWN_QUEUE
    assert classify_open_fill(10.0, 9.0, 11.0, None) is ExecutionStatus.UNKNOWN_QUEUE


def test_costs_are_not_embedded_in_raw_fill_price():
    fill = apply_execution_costs(
        raw_fill_price=10.0,
        quantity=1_000,
        side="buy",
        costs=ExecutionCosts(commission=5.0, tax_rate=0.0, slippage_bps=30),
    )
    assert fill.raw_fill_price == 10.0
    assert fill.gross_notional == 10_000.0
    assert fill.slippage_cost == 30.0
    assert fill.net_cash_flow == -10_035.0


def test_same_day_exit_is_rejected_by_t_plus_one():
    with pytest.raises(ValueError, match="strictly after entry_date"):
        apply_execution_costs(
            raw_fill_price=10.0,
            quantity=1_000,
            side="sell",
            costs=ExecutionCosts(),
            entry_date=date(2026, 7, 13),
            exit_date=date(2026, 7, 13),
        )


@pytest.mark.parametrize(
    ("entry_date", "exit_date"),
    [
        (None, None),
        (date(2026, 7, 13), None),
        (None, date(2026, 7, 14)),
        (date(2026, 7, 14), date(2026, 7, 13)),
    ],
)
def test_sell_requires_complete_strictly_ordered_dates(entry_date, exit_date):
    with pytest.raises(ValueError, match="strictly after entry_date"):
        apply_execution_costs(
            raw_fill_price=10.0,
            quantity=1_000,
            side="sell",
            costs=ExecutionCosts(),
            entry_date=entry_date,
            exit_date=exit_date,
        )


@pytest.mark.parametrize("raw_fill_price", [0.0, -1.0, float("nan"), float("inf")])
def test_raw_fill_price_must_be_finite_and_positive(raw_fill_price):
    with pytest.raises(ValueError, match="raw_fill_price"):
        apply_execution_costs(raw_fill_price, 1_000, "buy", ExecutionCosts())


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5])
def test_quantity_must_be_a_positive_integer(quantity):
    with pytest.raises(ValueError, match="quantity"):
        apply_execution_costs(10.0, quantity, "buy", ExecutionCosts())


@pytest.mark.parametrize(
    "costs",
    [
        ExecutionCosts(commission=float("nan")),
        ExecutionCosts(tax_rate=float("inf")),
        ExecutionCosts(slippage_bps=-1.0),
        ExecutionCosts(other_fee=-1.0),
        ExecutionCosts(version=""),
    ],
)
def test_cost_configuration_must_be_finite_nonnegative_and_versioned(costs):
    with pytest.raises(ValueError, match="cost|version"):
        apply_execution_costs(10.0, 1_000, "buy", costs)


def test_stamp_tax_applies_only_to_sell():
    costs = ExecutionCosts(tax_rate=0.001)
    buy = apply_execution_costs(10.0, 1_000, "buy", costs)
    sell = apply_execution_costs(
        10.0,
        1_000,
        "sell",
        costs,
        entry_date=date(2026, 7, 13),
        exit_date=date(2026, 7, 14),
    )
    assert buy.tax == 0.0
    assert buy.net_cash_flow == -10_000.0
    assert sell.tax == 10.0
    assert sell.net_cash_flow == 9_990.0
