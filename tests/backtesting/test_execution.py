import pytest

from src.backtesting.trader import TradeExecutor, TradingConstraints


def test_trade_executor_routes_actions(portfolio):
    ex = TradeExecutor()

    # buy
    qty = ex.execute_trade("AAPL", "buy", 10, 100.0, portfolio)
    assert qty == 10
    # sell
    qty = ex.execute_trade("AAPL", "sell", 5, 100.0, portfolio)
    assert qty == 5
    # short
    qty = ex.execute_trade("MSFT", "short", 4, 200.0, portfolio)
    assert qty == 4
    # cover
    qty = ex.execute_trade("MSFT", "cover", 1, 200.0, portfolio)
    assert qty == 1


def test_trade_executor_guards_and_unknown_action(portfolio):
    ex = TradeExecutor()

    assert ex.execute_trade("AAPL", "buy", 0, 10.0, portfolio) == 0
    assert ex.execute_trade("AAPL", "buy", -5, 10.0, portfolio) == 0
    assert ex.execute_trade("AAPL", "unknown", 10, 10.0, portfolio) == 0


def test_trade_executor_blocks_limit_up_buy_and_limit_down_sell(portfolio):
    ex = TradeExecutor()

    assert ex.execute_trade("AAPL", "buy", 10, 100.0, portfolio, is_limit_up=True) == 0
    portfolio.apply_long_buy("AAPL", 10, 100.0)
    assert ex.execute_trade("AAPL", "sell", 10, 100.0, portfolio, is_limit_down=True) == 0


def test_trade_executor_applies_slippage_and_fees(portfolio):
    ex = TradeExecutor(
        TradingConstraints(
            commission_rate=0.01,
            stamp_duty_rate=0.01,
            base_slippage_rate=0.10,
            low_liquidity_slippage_rate=0.10,
        )
    )

    buy_qty = ex.execute_trade("AAPL", "buy", 10, 100.0, portfolio, daily_turnover=100_000_000.0)
    assert buy_qty == 10
    snapshot_after_buy = portfolio.get_snapshot()
    assert snapshot_after_buy["positions"]["AAPL"]["long_cost_basis"] == pytest.approx(110.0)
    assert snapshot_after_buy["cash"] == pytest.approx(100_000.0 - 1_100.0 - 11.0)

    sell_qty = ex.execute_trade("AAPL", "sell", 10, 100.0, portfolio, daily_turnover=100_000_000.0)
    assert sell_qty == 10
    snapshot_after_sell = portfolio.get_snapshot()
    assert snapshot_after_sell["cash"] == pytest.approx(100_000.0 - 1_111.0 + 900.0 - 18.0)
