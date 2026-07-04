import pytest

from src.backtesting.portfolio import Portfolio
from src.backtesting.trader import TradeExecutor, TradingConstraints
from src.backtesting.trader_helpers import (
    _resolve_buy_execution,
    _resolve_execution_slippage_rate,
    _resolve_short_open_execution,
)


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
    # BETA-004: commission is now capitalized into the cost basis. The
    # gross executed price is 100 * 1.10 = 110 (10% slippage), and with
    # 1% commission the all-in price is 110 * 1.01 = 111.1 per share.
    # Cash debit is 10 * 111.1 = 1111.0 (no separate post-hoc commission).
    assert snapshot_after_buy["positions"]["AAPL"]["long_cost_basis"] == pytest.approx(111.1)
    assert snapshot_after_buy["cash"] == pytest.approx(100_000.0 - 1_111.0)

    sell_qty = ex.execute_trade("AAPL", "sell", 10, 100.0, portfolio, daily_turnover=100_000_000.0)
    assert sell_qty == 10
    snapshot_after_sell = portfolio.get_snapshot()
    # BETA-004: sell at 100 with 10% slippage → executed_price = 90.
    # Net proceeds = 90 * (1 - 0.01 - 0.01) = 88.2 per share.
    # Cash credit = 10 * 88.2 = 882.0. Total cash = 100_000 - 1111 + 882 = 99_771.
    # (Old test had same total — 100_000 - 1111 + 900 - 18 = 99_771 — but the
    # intermediate decomposition was different: gross debit + commission
    # double-debit. The economic total is preserved.)
    assert snapshot_after_sell["cash"] == pytest.approx(99_771.0)


def test_trade_executor_scales_slippage_with_order_size_when_turnover_is_available():
    small_order_portfolio = Portfolio(tickers=["AAPL"], initial_cash=100_000.0, margin_requirement=0.0)
    large_order_portfolio = Portfolio(tickers=["AAPL"], initial_cash=100_000.0, margin_requirement=0.0)
    executor = TradeExecutor(
        TradingConstraints(
            commission_rate=0.0,
            stamp_duty_rate=0.0,
            base_slippage_rate=0.01,
            low_liquidity_slippage_rate=0.01,
        )
    )

    executor.execute_trade("AAPL", "buy", 10, 100.0, small_order_portfolio, daily_turnover=100_000.0)
    executor.execute_trade("AAPL", "buy", 1_000, 100.0, large_order_portfolio, daily_turnover=100_000.0)

    small_cost_basis = small_order_portfolio.get_snapshot()["positions"]["AAPL"]["long_cost_basis"]
    large_cost_basis = large_order_portfolio.get_snapshot()["positions"]["AAPL"]["long_cost_basis"]

    assert large_cost_basis > small_cost_basis


def test_trade_executor_keeps_flat_slippage_when_turnover_is_missing():
    portfolio = Portfolio(tickers=["AAPL"], initial_cash=100_000.0, margin_requirement=0.0)
    executor = TradeExecutor(
        TradingConstraints(
            commission_rate=0.0,
            stamp_duty_rate=0.0,
            base_slippage_rate=0.01,
            low_liquidity_slippage_rate=0.01,
            commission_floor_yuan=0.0,  # BETA-006: disable floor to isolate test scenario
        )
    )

    executor.execute_trade("AAPL", "buy", 10, 100.0, portfolio)

    snapshot = portfolio.get_snapshot()
    assert snapshot["positions"]["AAPL"]["long_cost_basis"] == pytest.approx(101.0)


def test_resolve_execution_slippage_rate_scales_with_participation_ratio_and_caps_at_one():
    assert _resolve_execution_slippage_rate(0.01, 10, 100.0, 100_000.0) == pytest.approx(0.0101)
    assert _resolve_execution_slippage_rate(0.01, 2_000, 100.0, 100_000.0) == pytest.approx(0.02)


def test_resolve_buy_execution_uses_cash_capped_quantity_for_market_impact():
    portfolio = Portfolio(tickers=["AAPL"], initial_cash=10_000.0, margin_requirement=0.0)

    quantity, executed_price = _resolve_buy_execution(1_000, 100.0, portfolio, 0.01, 0.0, 100_000.0)

    assert quantity == 98
    assert executed_price == pytest.approx(101.098)


def test_resolve_short_open_execution_uses_margin_capped_quantity_for_market_impact():
    portfolio = Portfolio(tickers=["AAPL"], initial_cash=5_000.0, margin_requirement=0.5)

    quantity, executed_price = _resolve_short_open_execution(1_000, 100.0, portfolio, 0.01, 100_000.0)

    assert quantity == 101
    assert executed_price == pytest.approx(98.899)


@pytest.mark.parametrize(
    ("action", "quantity", "expected_cash_delta"),
    [
        ("buy", 10, -1_010.0),
    ],
)
def test_trade_executor_preserves_buy_fee_semantics_with_turnover(action, quantity, expected_cash_delta):
    portfolio = Portfolio(tickers=["AAPL"], initial_cash=100_000.0, margin_requirement=0.0)
    executor = TradeExecutor(
        TradingConstraints(
            commission_rate=0.01,
            stamp_duty_rate=0.001,
            base_slippage_rate=0.0,
            low_liquidity_slippage_rate=0.0,
        )
    )

    starting_cash = portfolio.get_cash()
    executed = executor.execute_trade("AAPL", action, quantity, 100.0, portfolio, daily_turnover=100_000.0)

    assert executed == quantity
    assert portfolio.get_cash() - starting_cash == pytest.approx(expected_cash_delta)


def test_trade_executor_preserves_sell_fee_semantics_with_turnover():
    portfolio = Portfolio(tickers=["AAPL"], initial_cash=100_000.0, margin_requirement=0.0)
    portfolio.apply_long_buy("AAPL", 10, 100.0)
    portfolio.record_long_entry("AAPL", "2024-01-15", reset=True)
    executor = TradeExecutor(
        TradingConstraints(
            commission_rate=0.01,
            stamp_duty_rate=0.001,
            base_slippage_rate=0.0,
            low_liquidity_slippage_rate=0.0,
        )
    )

    starting_cash = portfolio.get_cash()
    executed = executor.execute_trade("AAPL", "sell", 10, 100.0, portfolio, daily_turnover=100_000.0)

    assert executed == 10
    assert portfolio.get_cash() - starting_cash == pytest.approx(989.0)


@pytest.mark.parametrize(
    ("action", "expected_cash_delta"),
    [
        ("short", 990.0),
        ("cover", -1_010.0),
    ],
)
def test_trade_executor_preserves_short_and_cover_fee_semantics_with_turnover(action, expected_cash_delta):
    portfolio = Portfolio(tickers=["AAPL"], initial_cash=100_000.0, margin_requirement=0.0)
    if action == "cover":
        portfolio.apply_short_open("AAPL", 10, 100.0)
    executor = TradeExecutor(
        TradingConstraints(
            commission_rate=0.01,
            stamp_duty_rate=0.001,
            base_slippage_rate=0.0,
            low_liquidity_slippage_rate=0.0,
        )
    )

    starting_cash = portfolio.get_cash()
    executed = executor.execute_trade("AAPL", action, 10, 100.0, portfolio, daily_turnover=100_000.0)

    assert executed == 10
    assert portfolio.get_cash() - starting_cash == pytest.approx(expected_cash_delta)


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


def test_portfolio_record_long_entry_persists_theme_identity_metadata(portfolio):
    portfolio.apply_long_buy("AAPL", 10, 100.0)
    portfolio.record_long_entry(
        "AAPL",
        "2024-01-15",
        reset=True,
        theme_name="AI算力",
        theme_category="technology",
        is_new_theme=True,
    )

    snapshot = portfolio.get_snapshot()
    assert snapshot["positions"]["AAPL"]["theme_name"] == "AI算力"
    assert snapshot["positions"]["AAPL"]["theme_category"] == "technology"
    assert snapshot["positions"]["AAPL"]["is_new_theme"] is True


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


# ---------------------------------------------------------------------------
# coerce_trade_action — NS-17 / BH-017 family sibling (c269)
# ---------------------------------------------------------------------------


class TestCoerceTradeActionSilentFailure:
    """Backtest signal → Action coercion: HOLD fallback preserved, but the
    fallback must be observable so backtest operators can detect biased results
    caused by upstream agents emitting case-mismatched / whitespace-laden /
    unknown signal strings that get silently downgraded to HOLD."""

    def test_valid_lowercase_string_no_warning(self, caplog) -> None:
        import logging

        from src.backtesting.trader_helpers import coerce_trade_action
        from src.backtesting.types import Action

        with caplog.at_level(logging.WARNING, logger="src.backtesting.trader_helpers"):
            assert coerce_trade_action("buy") is Action.BUY
            assert coerce_trade_action("sell") is Action.SELL
            assert coerce_trade_action("hold") is Action.HOLD

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not warning_records, f"valid signal strings must NOT emit warning, got {warning_records}"

    def test_action_enum_passthrough_no_warning(self, caplog) -> None:
        import logging

        from src.backtesting.trader_helpers import coerce_trade_action
        from src.backtesting.types import Action

        with caplog.at_level(logging.WARNING, logger="src.backtesting.trader_helpers"):
            assert coerce_trade_action(Action.BUY) is Action.BUY

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not warning_records

    def test_unknown_string_returns_hold_and_emits_warning(self, caplog) -> None:
        """NS-17 / BH-017 family: unknown signal string must NOT be silent.

        背景: ``coerce_trade_action`` 在 ``Action(action)`` 抛 ValueError 时返回
        HOLD 是 best-effort 有意为之 (回测不崩溃), 但之前完全静默 — 上游 agent
        若发出 "unknown" / 大小写不匹配 / 带空白 的信号, 该笔 BUY/SELL 被悄悄降级
        为 HOLD (不交易), 回测表现失真且无任何信号。修复后必须发 logger.warning
        让回测 operators 能感知"信号被吞"并定位上游 agent 输出格式漂移。
        """
        import logging

        from src.backtesting.trader_helpers import coerce_trade_action
        from src.backtesting.types import Action

        with caplog.at_level(logging.WARNING, logger="src.backtesting.trader_helpers"):
            result = coerce_trade_action("unknown")

        assert result is Action.HOLD  # best-effort contract preserved
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning_records, f"expected >=1 WARNING record for unknown signal, got {caplog.records}"
        msg = warning_records[0].getMessage()
        # Must name the function / feature so operators can grep it.
        assert "coerce_trade_action" in msg, f"warning must name the degraded function, got: {msg!r}"
        # Must include the offending value so operators can trace the upstream agent.
        assert "unknown" in msg, f"warning must include the bad value, got: {msg!r}"

    def test_case_mismatch_returns_hold_and_emits_warning(self, caplog) -> None:
        """Uppercase 'BUY' is NOT a valid StrEnum value (only 'buy' is). This is
        the most likely real-world drift (an agent formatting signals as uppercase
        after a refactor). Must warn so the backtest bias is detectable."""
        import logging

        from src.backtesting.trader_helpers import coerce_trade_action
        from src.backtesting.types import Action

        with caplog.at_level(logging.WARNING, logger="src.backtesting.trader_helpers"):
            result = coerce_trade_action("BUY")

        assert result is Action.HOLD
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning_records, "uppercase 'BUY' must emit warning (case drift)"
        msg = warning_records[0].getMessage()
        assert "BUY" in msg

    def test_whitespace_laden_returns_hold_and_emits_warning(self, caplog) -> None:
        """Trailing whitespace 'buy ' is NOT a valid StrEnum value. Another
        common real-world drift (string concatenation / JSON formatting)."""
        import logging

        from src.backtesting.trader_helpers import coerce_trade_action
        from src.backtesting.types import Action

        with caplog.at_level(logging.WARNING, logger="src.backtesting.trader_helpers"):
            result = coerce_trade_action("buy ")

        assert result is Action.HOLD
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning_records, "whitespace-laden 'buy ' must emit warning"
