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


def test_trade_executor_enforces_t_plus_1_same_day_sell_blocked(portfolio):
    """Test T+1 enforcement: cannot sell long position on same day as purchase."""
    ex = TradeExecutor()
    trade_date = "2024-01-15"

    # Buy on trade_date
    portfolio.apply_long_buy("AAPL", 10, 100.0)
    portfolio.record_long_entry("AAPL", trade_date, reset=True)

    # Attempt to sell on same trade_date should be blocked
    sell_qty = ex.execute_trade("AAPL", "sell", 10, 100.0, portfolio, trade_date=trade_date)
    assert sell_qty == 0, "Same-day sell should be blocked by T+1 enforcement"

    # Position should still be intact
    snapshot = portfolio.get_snapshot()
    assert snapshot["positions"]["AAPL"]["long"] == 10
    assert snapshot["positions"]["AAPL"]["entry_date"] == trade_date


def test_trade_executor_allows_t_plus_1_next_day_sell(portfolio):
    """Test T+1 enforcement: can sell long position on next trading day."""
    ex = TradeExecutor()
    entry_date = "2024-01-15"
    next_day = "2024-01-16"

    # Buy on entry_date
    portfolio.apply_long_buy("AAPL", 10, 100.0)
    portfolio.record_long_entry("AAPL", entry_date, reset=True)

    # Sell on next_day should succeed
    sell_qty = ex.execute_trade("AAPL", "sell", 10, 100.0, portfolio, trade_date=next_day)
    assert sell_qty == 10, "Next-day sell should be allowed"

    # Position should be closed
    snapshot = portfolio.get_snapshot()
    assert snapshot["positions"]["AAPL"]["long"] == 0


def test_trade_executor_t_plus_1_no_entry_date_allows_sell(portfolio):
    """Test T+1: positions without entry_date (legacy) can be sold."""
    ex = TradeExecutor()
    trade_date = "2024-01-15"

    # Buy without setting entry_date (legacy scenario)
    portfolio.apply_long_buy("AAPL", 10, 100.0)
    # Intentionally not calling record_long_entry

    # Sell should succeed (no entry_date to check against)
    sell_qty = ex.execute_trade("AAPL", "sell", 10, 100.0, portfolio, trade_date=trade_date)
    assert sell_qty == 10, "Sell should succeed when no entry_date is set"


def test_trade_executor_t_plus_1_no_trade_date_param_allows_sell(portfolio):
    """Test T+1: when trade_date not provided, sell is allowed (backward compat)."""
    ex = TradeExecutor()
    entry_date = "2024-01-15"

    # Buy and set entry_date
    portfolio.apply_long_buy("AAPL", 10, 100.0)
    portfolio.record_long_entry("AAPL", entry_date, reset=True)

    # Sell without trade_date parameter should succeed (backward compatibility)
    sell_qty = ex.execute_trade("AAPL", "sell", 10, 100.0, portfolio)
    assert sell_qty == 10, "Sell should succeed when trade_date param not provided"
