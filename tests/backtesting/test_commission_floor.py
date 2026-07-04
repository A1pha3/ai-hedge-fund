"""BETA-006: A 股最低佣金 5 元/笔回归测试。

覆盖场景:
- 小额交易触发佣金下限 (< 5 元 → effective_rate 上调)
- 大额交易不触发 (effective_rate = raw rate)
- 买入侧 (apply_long_buy via execute_buy_trade)
- 卖出侧 (apply_long_sell via execute_sell_trade)
- 做空侧 (apply_short_open via execute_short_trade)  — NS-19(2) 对称性
- 平仓侧 (apply_short_cover via execute_cover_trade)  — NS-19(2) 对称性
- 零名义金额 → 边界 (不崩)
"""

from __future__ import annotations

from src.backtesting.portfolio import Portfolio
from src.backtesting.trader_helpers import (
    _apply_commission_floor,
    execute_buy_trade,
    execute_cover_trade,
    execute_sell_trade,
    execute_short_trade,
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
        assert abs(actual_proceeds - expected_proceeds) < 1e-6, f"Expected proceeds {expected_proceeds}, got {actual_proceeds}"

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


class TestExecuteShortWithFloor:
    """NS-19(2): 做空侧执行 — 小额交易触发佣金下限。

    BETA-006 给买入/卖出侧加了 5 元佣金下限, 但 ``execute_short_trade``
    (apply_short_open) 与 ``execute_cover_trade`` (apply_short_cover) 漏改,
    导致做空/平仓的小额交易少收佣金 (raw rate * notional < 5 元时)，
    低估做空真实成本。这与 finance-quant beta veto "missing transaction
    costs" 直接相关 — 必须与 long 侧对称。
    """

    def test_small_short_charges_floor(self) -> None:
        """做空 100 股 @ ¥10 (¥1000 名义) — commission 上调至 5 元 (0.5%)。

        apply_short_open: net_proceeds_price = price * (1 - commission_rate)。
        floor rate = 5 / 1000 = 0.005 > raw 0.00025 → effective = 0.005。
        net_proceeds_price = 10 * (1 - 0.005) = 9.95。
        margin_requirement=1.0 → margin = 9.95 * 100 * 1.0 = 995。
        cash delta = +995 (proceeds) - 995 (margin) = 0。
        若不应用 floor: net_proceeds_price = 10 * (1 - 0.00025) = 9.9975,
        cash delta = +999.75 - 999.75 = 0 (看似相同), 但 short_cost_basis
        与 margin 记录偏低 — 通过 margin/short_cost_basis 间接断言更稳。
        这里用 margin_used 直接断言 floor 已生效。
        """
        portfolio = Portfolio(tickers=["000001"], initial_cash=10_000.0, margin_requirement=1.0)
        executed = execute_short_trade(
            ticker="000001",
            quantity=100,
            current_price=10.0,
            portfolio=portfolio,
            slippage_rate=0.0,
            commission_rate=0.00025,
        )
        assert executed == 100
        # margin_used = net_proceeds_price * qty * margin_ratio
        # floor: 9.95 * 100 * 1.0 = 995.0
        # no-floor (buggy): 9.9975 * 100 * 1.0 = 999.75
        margin_used = portfolio._portfolio["margin_used"]  # noqa: SLF001
        assert abs(margin_used - 995.0) < 1e-6, f"Expected margin_used 995.0 (floor applied), got {margin_used}"

    def test_large_short_uses_raw_rate(self) -> None:
        """做空 1000 股 @ ¥100 (¥100000) — raw rate 适用 (不触发下限)。"""
        portfolio = Portfolio(tickers=["000001"], initial_cash=200_000.0, margin_requirement=1.0)
        executed = execute_short_trade(
            ticker="000001",
            quantity=1000,
            current_price=100.0,
            portfolio=portfolio,
            slippage_rate=0.0,
            commission_rate=0.00025,
        )
        assert executed == 1000
        # floor rate = 5 / 100000 = 0.00005 < raw 0.00025 → effective = 0.00025
        # margin_used = 100 * (1 - 0.00025) * 1000 * 1.0 = 99.975 * 1000 = 99975.0
        margin_used = portfolio._portfolio["margin_used"]  # noqa: SLF001
        assert abs(margin_used - 99_975.0) < 1e-6


class TestExecuteCoverWithFloor:
    """NS-19(2): 平仓侧执行 — 小额交易触发佣金下限。

    apply_short_cover: all_in_price = price * (1 + commission_rate)。
    floor 生效时 all_in_price 上升 → cover_cost 上升 → cash 多扣。
    """

    def test_small_cover_charges_floor(self) -> None:
        """平仓 100 股 @ ¥10 (¥1000 名义) — commission 上调至 5 元 (0.5%)。

        先做空建仓, 再平仓。floor rate = 5 / 1000 = 0.005。
        all_in_price = 10 * (1 + 0.005) = 10.05。
        cover_cost = 10.05 * 100 = 1005。
        """
        portfolio = Portfolio(tickers=["000001"], initial_cash=10_000.0, margin_requirement=1.0)
        # 建空仓 (用足够大的 commission_rate 避免 floor 干扰建仓数学)
        portfolio.apply_short_open("000001", 100, 10.0, commission_rate=0.0)
        cash_before = portfolio.get_cash()

        executed = execute_cover_trade(
            ticker="000001",
            quantity=100,
            current_price=10.0,
            portfolio=portfolio,
            slippage_rate=0.0,
            commission_rate=0.00025,
        )
        assert executed == 100
        # all_in_price with floor = 10.05, cover_cost = 1005
        # margin_release = 100% of short_margin_used (建仓时 margin=1000)
        # cash delta = +1000 (margin release) - 1005 (cover cost) = -5
        # no-floor (buggy): all_in_price = 10 * 1.00025 = 10.0025, cover_cost=1000.25
        #   cash delta = +1000 - 1000.25 = -0.25
        cash_after = portfolio.get_cash()
        actual_cover_cost = cash_before - cash_after  # net cash decrease
        # floor: margin_release(1000) - cover_cost(1005) = -5 net decrease
        assert abs(actual_cover_cost - 5.0) < 1e-6, f"Expected net cash decrease 5.0 (floor applied), got {actual_cover_cost}"

    def test_large_cover_uses_raw_rate(self) -> None:
        """平仓 1000 股 @ ¥100 (¥100000) — raw rate 适用。"""
        portfolio = Portfolio(tickers=["000001"], initial_cash=200_000.0, margin_requirement=1.0)
        portfolio.apply_short_open("000001", 1000, 100.0, commission_rate=0.0)
        cash_before = portfolio.get_cash()

        executed = execute_cover_trade(
            ticker="000001",
            quantity=1000,
            current_price=100.0,
            portfolio=portfolio,
            slippage_rate=0.0,
            commission_rate=0.00025,
        )
        assert executed == 1000
        # floor rate = 5 / 100000 = 0.00005 < raw 0.00025 → effective = raw
        # all_in_price = 100 * 1.00025 = 100.025, cover_cost = 100025
        # margin_release = 100000 (建仓 margin), cash delta = +100000 - 100025 = -25
        cash_after = portfolio.get_cash()
        actual_cover_cost = cash_before - cash_after
        assert abs(actual_cover_cost - 25.0) < 1e-6


class TestShortCoverFloorParameter:
    """NS-19(2): commission_floor_yuan 参数对称性。"""

    def test_short_accepts_custom_floor(self) -> None:
        """execute_short_trade 接受 commission_floor_yuan 参数 (与 buy/sell 对称)。"""
        portfolio = Portfolio(tickers=["000001"], initial_cash=10_000.0, margin_requirement=1.0)
        # 100 * 10 = 1000, floor 10 → floor_rate = 10/1000 = 0.01
        executed = execute_short_trade(
            ticker="000001",
            quantity=100,
            current_price=10.0,
            portfolio=portfolio,
            slippage_rate=0.0,
            commission_rate=0.00025,
            commission_floor_yuan=10.0,
        )
        assert executed == 100
        # effective rate 0.01, net_proceeds_price = 10 * 0.99 = 9.9
        # margin_used = 9.9 * 100 = 990.0
        margin_used = portfolio._portfolio["margin_used"]  # noqa: SLF001
        assert abs(margin_used - 990.0) < 1e-6

    def test_cover_accepts_custom_floor(self) -> None:
        """execute_cover_trade 接受 commission_floor_yuan 参数 (与 buy/sell 对称)。"""
        portfolio = Portfolio(tickers=["000001"], initial_cash=10_000.0, margin_requirement=1.0)
        portfolio.apply_short_open("000001", 100, 10.0, commission_rate=0.0)
        cash_before = portfolio.get_cash()
        # 100 * 10 = 1000, floor 10 → floor_rate = 0.01
        # all_in_price = 10 * 1.01 = 10.1, cover_cost = 1010
        # cash delta = +1000 (margin) - 1010 = -10
        executed = execute_cover_trade(
            ticker="000001",
            quantity=100,
            current_price=10.0,
            portfolio=portfolio,
            slippage_rate=0.0,
            commission_rate=0.00025,
            commission_floor_yuan=10.0,
        )
        assert executed == 100
        cash_after = portfolio.get_cash()
        assert abs((cash_before - cash_after) - 10.0) < 1e-6
