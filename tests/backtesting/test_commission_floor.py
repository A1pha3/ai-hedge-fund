"""BETA-006: A 股最低佣金 5 元/笔回归测试。

覆盖场景:
- 小额交易触发佣金下限 (< 5 元 → effective_rate 上调)
- 大额交易不触发 (effective_rate = raw rate)
- 买入侧 (apply_long_buy via execute_buy_trade)
- 卖出侧 (apply_long_sell via execute_sell_trade)
- 零名义金额 → 边界 (不崩)
"""
from __future__ import annotations

import pytest

from src.backtesting.portfolio import Portfolio
from src.backtesting.trader_helpers import (
    _apply_commission_floor,
    execute_buy_trade,
    execute_sell_trade,
)


class TestCommissionFloorHelper:
    """BETA-006: _apply_commission_floor 单元测试。"""

    def test_small_trade_raises_to_floor(self) -> None:
        """1000 元 @ 0.025% = 0.25 元 → 等效提升至 5 元 (0.5%)。"""
        # 100 shares * 10 yuan = 1000 yuan notional
        # floor rate = 5 / 1000 = 0.005
        # raw rate 0.00025 < 0.005 → effective = 0.005
        effective = _apply_commission_floor(0.00025, quantity=100, price=10.0)
        assert abs(effective - 0.005) < 1e-9

    def test_large_trade_unchanged(self) -> None:
        """100000 元 @ 0.025% = 25 元 (>= 5) → 不触发下限。"""
        # 1000 shares * 100 yuan = 100000 yuan notional
        # floor rate = 5 / 100000 = 0.00005
        # raw rate 0.00025 > 0.00005 → effective = 0.00025
        effective = _apply_commission_floor(0.00025, quantity=1000, price=100.0)
        assert abs(effective - 0.00025) < 1e-9

    def test_exactly_at_floor(self) -> None:
        """交易额恰好等于下限对应金额 → effective = floor rate。"""
        # raw rate 0.00025 * 20000 = 5 yuan (exactly at floor)
        effective = _apply_commission_floor(0.00025, quantity=200, price=100.0)
        # floor rate = 5 / 20000 = 0.00025 (same as raw)
        assert abs(effective - 0.00025) < 1e-9

    def test_zero_notional_no_change(self) -> None:
        """零名义金额 → 不崩溃, 返回原费率。"""
        effective = _apply_commission_floor(0.00025, quantity=0, price=100.0)
        assert abs(effective - 0.00025) < 1e-9

    def test_negative_quantity_uses_abs(self) -> None:
        """负数量 (卖出) → abs() 后正常应用下限。"""
        effective = _apply_commission_floor(0.00025, quantity=-100, price=10.0)
        # abs(-100) * 10 = 1000, floor rate = 5/1000 = 0.005
        assert abs(effective - 0.005) < 1e-9

    def test_custom_floor(self) -> None:
        """自定义下限 (10 元) → 等效提升。"""
        # 100 shares * 10 yuan = 1000
        # floor rate = 10 / 1000 = 0.01
        effective = _apply_commission_floor(0.00025, quantity=100, price=10.0, floor_yuan=10.0)
        assert abs(effective - 0.01) < 1e-9

    def test_zero_floor_no_effect(self) -> None:
        """floor = 0 → 不应用下限。"""
        effective = _apply_commission_floor(0.00025, quantity=100, price=10.0, floor_yuan=0.0)
        assert abs(effective - 0.00025) < 1e-9


class TestExecuteBuyWithFloor:
    """BETA-006: 买入侧执行 — 小额交易触发下限。"""

    def test_small_buy_charges_floor(self) -> None:
        """买入 100 股 @ ¥10 (¥1000) — commission 上调至 5 元 (0.5%)。"""
        portfolio = Portfolio(tickers=["000001"], initial_cash=10_000.0, margin_requirement=1.0)
        # expected cost with floor: 100 * 10 * (1 + 0.005) = 1005 yuan
        executed = execute_buy_trade(
            ticker="000001",
            quantity=100,
            current_price=10.0,
            portfolio=portfolio,
            slippage_rate=0.0,
            commission_rate=0.00025,
        )
        assert executed == 100
        # cash should be debited by 1005 (all-in price with floor rate)
        expected_cash = 10_000.0 - 1005.0
        actual_cash = portfolio.get_cash()
        assert abs(actual_cash - expected_cash) < 1e-6, f"Expected {expected_cash}, got {actual_cash}"

    def test_large_buy_uses_raw_rate(self) -> None:
        """买入 1000 股 @ ¥100 (¥100000) — raw rate 适用 (无下限触发)。"""
        portfolio = Portfolio(tickers=["000001"], initial_cash=200_000.0, margin_requirement=1.0)
        # cost: 1000 * 100 * (1 + 0.00025) = 100025
        executed = execute_buy_trade(
            ticker="000001",
            quantity=1000,
            current_price=100.0,
            portfolio=portfolio,
            slippage_rate=0.0,
            commission_rate=0.00025,
        )
        assert executed == 1000
        expected_cash = 200_000.0 - 100025.0
        actual_cash = portfolio.get_cash()
        assert abs(actual_cash - expected_cash) < 1e-6


class TestExecuteSellWithFloor:
    """BETA-006: 卖出侧执行 — 小额交易触发下限。"""

    def test_small_sell_charges_floor(self) -> None:
        """卖出 100 股 @ ¥10 (¥1000) — commission 上调至 5 元。"""
        portfolio = Portfolio(tickers=["000001"], initial_cash=10_000.0, margin_requirement=1.0)
        portfolio.apply_long_buy("000001", 100, 10.0)
        cash_before = portfolio.get_cash()

        executed = execute_sell_trade(
            ticker="000001",
            quantity=100,
            current_price=10.0,
            portfolio=portfolio,
            slippage_rate=0.0,
            commission_rate=0.00025,
            stamp_duty_rate=0.0005,
            trade_date=None,
        )
        assert executed == 100
        # Net proceeds = 100 * 10 * (1 - 0.005 - 0.0005) = 100 * 9.945 = 994.5
        # (floor rate 0.005 for commission + 0.0005 stamp duty)
        cash_after = portfolio.get_cash()
        actual_proceeds = cash_after - cash_before
        expected_proceeds = 100 * 10 * (1 - 0.005 - 0.0005)
        assert abs(actual_proceeds - expected_proceeds) < 1e-6, (
            f"Expected proceeds {expected_proceeds}, got {actual_proceeds}"
        )

    def test_large_sell_uses_raw_rate(self) -> None:
        """卖出 1000 股 @ ¥100 (¥100000) — raw rate 适用。"""
        portfolio = Portfolio(tickers=["000001"], initial_cash=200_000.0, margin_requirement=1.0)
        portfolio.apply_long_buy("000001", 1000, 100.0)
        cash_before = portfolio.get_cash()

        executed = execute_sell_trade(
            ticker="000001",
            quantity=1000,
            current_price=100.0,
            portfolio=portfolio,
            slippage_rate=0.0,
            commission_rate=0.00025,
            stamp_duty_rate=0.0005,
            trade_date=None,
        )
        assert executed == 1000
        # net = 1000 * 100 * (1 - 0.00025 - 0.0005) = 1000 * 99.925 = 99925
        cash_after = portfolio.get_cash()
        actual_proceeds = cash_after - cash_before
        expected_proceeds = 1000 * 100 * (1 - 0.00025 - 0.0005)
        assert abs(actual_proceeds - expected_proceeds) < 1e-6