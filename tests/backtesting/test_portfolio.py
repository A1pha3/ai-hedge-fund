import math

import pytest

from src.backtesting.portfolio import Portfolio


def test_apply_long_buy_basic(portfolio: Portfolio) -> None:
    executed = portfolio.apply_long_buy("AAPL", quantity=100, price=50.0)
    assert executed == 100
    snap = portfolio.get_snapshot()
    assert snap["positions"]["AAPL"]["long"] == 100
    assert snap["positions"]["AAPL"]["long_cost_basis"] == pytest.approx(50.0)
    # cash reduced by 5,000
    assert snap["cash"] == pytest.approx(95_000.0)


def test_apply_long_buy_partial_fill_when_insufficient_cash() -> None:
    p = Portfolio(tickers=["AAPL"], initial_cash=120.0, margin_requirement=0.5)
    # Request 10 shares at $20 = $200, but only $120 cash → max 6 shares
    executed = p.apply_long_buy("AAPL", quantity=10, price=20.0)
    assert executed == 6
    snap = p.get_snapshot()
    assert snap["positions"]["AAPL"]["long"] == 6
    assert snap["cash"] == pytest.approx(0.0)


def test_apply_long_sell_realized_gain_and_cost_basis_reset(portfolio: Portfolio) -> None:
    # Buy 100 @ 50, then sell 100 @ 60 → realized gain = 100 * (60-50) = 1000
    portfolio.apply_long_buy("AAPL", 100, 50.0)
    executed = portfolio.apply_long_sell("AAPL", 100, 60.0)
    assert executed == 100
    snap = portfolio.get_snapshot()
    assert snap["positions"]["AAPL"]["long"] == 0
    assert snap["positions"]["AAPL"]["long_cost_basis"] == pytest.approx(0.0)
    assert snap["realized_gains"]["AAPL"]["long"] == pytest.approx(1_000.0)
    # Cash: initial 100k - 5k + 6k = 101k
    assert snap["cash"] == pytest.approx(101_000.0)


def test_apply_long_sell_clamps_to_owned() -> None:
    p = Portfolio(tickers=["AAPL"], initial_cash=10_000.0, margin_requirement=0.5)
    p.apply_long_buy("AAPL", 10, 100.0)
    # Try to sell 20, but only 10 owned
    executed = p.apply_long_sell("AAPL", 20, 100.0)
    assert executed == 10
    assert p.get_snapshot()["positions"]["AAPL"]["long"] == 0


def test_apply_short_open_basic(portfolio: Portfolio) -> None:
    # Short 100 @ $30, margin 50% → proceeds 3,000; margin 1,500
    executed = portfolio.apply_short_open("MSFT", 100, 30.0)
    assert executed == 100
    snap = portfolio.get_snapshot()
    pos = snap["positions"]["MSFT"]
    assert pos["short"] == 100
    assert pos["short_cost_basis"] == pytest.approx(30.0)
    assert pos["short_margin_used"] == pytest.approx(1_500.0)
    assert snap["margin_used"] == pytest.approx(1_500.0)
    # Cash increases net by proceeds - margin = 3,000 - 1,500 = 1,500
    assert snap["cash"] == pytest.approx(101_500.0)


def test_apply_short_open_partial_when_insufficient_margin_cash() -> None:
    # Small cash: only enough margin for 4 shares at 50% of proceeds
    p = Portfolio(tickers=["AAPL"], initial_cash=200.0, margin_requirement=0.5)
    # price=100 → margin per share = 50, cash 200 → max 4 shares
    executed = p.apply_short_open("AAPL", 10, 100.0)
    assert executed == 4
    snap = p.get_snapshot()
    pos = snap["positions"]["AAPL"]
    assert pos["short"] == 4
    assert pos["short_margin_used"] == pytest.approx(200.0)
    # cash: + proceeds (400) - margin (200) = +200 → 400 total
    assert snap["cash"] == pytest.approx(400.0)


def test_apply_short_cover_realized_gain_and_margin_release(portfolio: Portfolio) -> None:
    # Open short 100 @ 50, then cover 40 @ 40 → gain = (50-40)*40 = 400
    portfolio.apply_short_open("AAPL", 100, 50.0)
    pre = portfolio.get_snapshot()
    pre_margin_used = pre["positions"]["AAPL"]["short_margin_used"]
    executed = portfolio.apply_short_cover("AAPL", 40, 40.0)
    assert executed == 40
    snap = portfolio.get_snapshot()
    pos = snap["positions"]["AAPL"]
    assert snap["realized_gains"]["AAPL"]["short"] == pytest.approx(400.0)
    # Proportional margin released: 40/100 of pre short_margin_used
    released = (40 / 100.0) * pre_margin_used
    assert pos["short_margin_used"] == pytest.approx(pre_margin_used - released)
    # Cash delta = +released - cover_cost(40*40=1600)
    expected_cash = pre["cash"] + released - 1_600.0
    assert snap["cash"] == pytest.approx(expected_cash)


def test_apply_short_cover_clamps_to_existing_short() -> None:
    p = Portfolio(tickers=["AAPL"], initial_cash=10_000.0, margin_requirement=0.5)
    p.apply_short_open("AAPL", 5, 100.0)
    executed = p.apply_short_cover("AAPL", 10, 100.0)
    assert executed == 5
    assert p.get_snapshot()["positions"]["AAPL"]["short"] == 0


def test_refresh_position_lifecycle_counts_trading_days_not_calendar_days() -> None:
    p = Portfolio(tickers=["AAPL"], initial_cash=10_000.0, margin_requirement=0.5)
    p.apply_long_buy("AAPL", 100, 10.0)
    p.record_long_entry("AAPL", "20240301", reset=True)

    p.refresh_position_lifecycle({"AAPL": 10.0}, "20240301")
    p.refresh_position_lifecycle({"AAPL": 10.5}, "20240304")

    snap = p.get_snapshot()
    assert snap["positions"]["AAPL"]["holding_days"] == 1
    assert snap["positions"]["AAPL"]["last_trade_date"] == "20240304"


def test_record_long_entry_persists_execution_contract_bucket() -> None:
    p = Portfolio(tickers=["AAPL"], initial_cash=10_000.0, margin_requirement=0.5)
    p.apply_long_buy("AAPL", 100, 10.0)

    p.record_long_entry("AAPL", "20240301", reset=True, execution_contract_bucket="formal_full")

    snap = p.get_snapshot()
    assert snap["positions"]["AAPL"]["execution_contract_bucket"] == "formal_full"


@pytest.mark.parametrize("action", [("buy"), ("sell"), ("short"), ("cover")])
def test_zero_or_negative_quantity_is_noop(portfolio: Portfolio, action: str) -> None:
    before = portfolio.get_snapshot()
    if action == "buy":
        executed = portfolio.apply_long_buy("AAPL", 0, 10.0)
        executed2 = portfolio.apply_long_buy("AAPL", -5, 10.0)
    elif action == "sell":
        executed = portfolio.apply_long_sell("AAPL", 0, 10.0)
        executed2 = portfolio.apply_long_sell("AAPL", -5, 10.0)
    elif action == "short":
        executed = portfolio.apply_short_open("AAPL", 0, 10.0)
        executed2 = portfolio.apply_short_open("AAPL", -5, 10.0)
    else:
        executed = portfolio.apply_short_cover("AAPL", 0, 10.0)
        executed2 = portfolio.apply_short_cover("AAPL", -5, 10.0)
    after = portfolio.get_snapshot()
    assert executed == 0 and executed2 == 0
    assert after == before


# ---------------------------------------------------------------------------
# BETA-004: fee-aware cost basis / realized gain (commission + stamp duty)
# ---------------------------------------------------------------------------

def test_apply_long_buy_capitalizes_commission_into_cost_basis(portfolio: Portfolio) -> None:
    """BETA-004 fix: when a buy is filled with commission_rate > 0, the
    per-share cost basis must be all-in (price + commission), not just
    the gross price. The bug: commission was debited from cash separately
    by trader_helpers.adjust_cash, leaving cost_basis at the gross price."""
    executed = portfolio.apply_long_buy("AAPL", quantity=100, price=50.0, commission_rate=0.001)
    assert executed == 100
    snap = portfolio.get_snapshot()
    # All-in cost: 50 * (1 + 0.001) = 50.05 per share
    assert snap["positions"]["AAPL"]["long_cost_basis"] == pytest.approx(50.05)
    # Cash debited by all-in amount, not gross
    assert snap["cash"] == pytest.approx(100_000.0 - 100 * 50.05)


def test_apply_long_buy_zero_commission_keeps_existing_behavior(portfolio: Portfolio) -> None:
    """Backward compat: commission_rate=0 (default) must produce the same
    cost_basis and cash debit as the historical gross-price code path."""
    executed = portfolio.apply_long_buy("AAPL", quantity=100, price=50.0)
    assert executed == 100
    snap = portfolio.get_snapshot()
    assert snap["positions"]["AAPL"]["long_cost_basis"] == pytest.approx(50.0)
    assert snap["cash"] == pytest.approx(100_000.0 - 100 * 50.0)


def test_apply_long_sell_realized_gain_deducts_commission_and_stamp(portfolio: Portfolio) -> None:
    """BETA-004 fix: realized_gain must reflect the net proceeds, not
    the gross sale price. For 100 shares bought @ 50 (no fees) and sold
    @ 60 with 0.1% commission + 0.1% stamp duty, the realized gain
    should be (60 * (1 - 0.002) - 50) * 100 = 988.0, not (60 - 50) * 100 = 1000."""
    portfolio.apply_long_buy("AAPL", 100, 50.0)
    executed = portfolio.apply_long_sell("AAPL", 100, 60.0, commission_rate=0.001, stamp_duty_rate=0.001)
    assert executed == 100
    snap = portfolio.get_snapshot()
    expected_realized = (60.0 * (1 - 0.001 - 0.001) - 50.0) * 100  # 988.0
    assert snap["realized_gains"]["AAPL"]["long"] == pytest.approx(expected_realized)
    # Cash should be credited by net proceeds only
    expected_cash = 100_000.0 - 100 * 50.0 + 100 * 60.0 * (1 - 0.001 - 0.001)
    assert snap["cash"] == pytest.approx(expected_cash)


def test_apply_long_sell_no_fees_keeps_existing_behavior(portfolio: Portfolio) -> None:
    """Backward compat: zero rates on sell → realized_gain and cash
    credit must match the historical gross-price code path."""
    portfolio.apply_long_buy("AAPL", 100, 50.0)
    executed = portfolio.apply_long_sell("AAPL", 100, 60.0)
    assert executed == 100
    snap = portfolio.get_snapshot()
    assert snap["realized_gains"]["AAPL"]["long"] == pytest.approx(1000.0)
    assert snap["cash"] == pytest.approx(100_000.0 - 100 * 50.0 + 100 * 60.0)


def test_full_buy_sell_round_trip_breaks_even_with_no_fees(portfolio: Portfolio) -> None:
    """Sanity: with commission_rate=0 and stamp_duty_rate=0, buying and
    selling at the same price must produce realized_gain=0 and cash
    back to starting. (Today this works because of backward compat, but
    the new code path must also satisfy it.)"""
    portfolio.apply_long_buy("AAPL", 100, 50.0)
    portfolio.apply_long_sell("AAPL", 100, 50.0)
    snap = portfolio.get_snapshot()
    assert snap["realized_gains"]["AAPL"]["long"] == pytest.approx(0.0)
    assert snap["cash"] == pytest.approx(100_000.0)
    assert snap["positions"]["AAPL"]["long"] == 0
    assert snap["positions"]["AAPL"]["long_cost_basis"] == pytest.approx(0.0)


def test_full_buy_sell_round_trip_with_fees_loses_exactly_the_fees(portfolio: Portfolio) -> None:
    """BETA-004: with fees on, a round-trip at the same price must lose
    exactly the total fees paid. Buy 100@10 with 0.25% commission +
    sell 100@10 with 0.25% commission + 0.1% stamp duty.

    Buy all-in:  10 * 1.0025 = 10.025 per share → cost 1002.5
    Sell net:    10 * (1 - 0.0025 - 0.001) = 9.965 per share → proceeds 996.5
    Realized gain: (9.965 - 10.025) * 100 = -6.0 (matches fees paid)
    Cash delta from start: 100_000 - 1002.5 + 996.5 = 99_994.0"""
    portfolio.apply_long_buy("AAPL", 100, 10.0, commission_rate=0.0025)
    portfolio.apply_long_sell("AAPL", 100, 10.0, commission_rate=0.0025, stamp_duty_rate=0.001)
    snap = portfolio.get_snapshot()
    # Realized gain = net_proceeds - cost_basis = (10*(1-0.0025-0.001) - 10*1.0025) * 100 = -6.0
    assert snap["realized_gains"]["AAPL"]["long"] == pytest.approx(-6.0)
    # Cash lost exactly the fees
    assert snap["cash"] == pytest.approx(99_994.0)


def test_execute_buy_trade_no_longer_debits_cash_separately(monkeypatch) -> None:
    """BETA-004: after the refactor, execute_buy_trade must NOT call
    portfolio.adjust_cash for the commission — the fee must already be
    baked into the all-in price passed to apply_long_buy.

    We verify by inspecting the call history of adjust_cash: only
    no-fee debit (the all-in cost is debited inside apply_long_buy)."""
    from src.backtesting.trader_helpers import execute_buy_trade
    from src.backtesting.portfolio import Portfolio

    p = Portfolio(tickers=["AAPL"], initial_cash=100_000.0, margin_requirement=0.5)
    # Spy on adjust_cash
    cash_history: list[float] = []
    orig_adjust = p.adjust_cash
    def spy_adjust(delta):
        cash_history.append(delta)
        orig_adjust(delta)
    monkeypatch.setattr(p, "adjust_cash", spy_adjust)

    execute_buy_trade(
        ticker="AAPL",
        quantity=100,
        current_price=10.0,
        portfolio=p,
        slippage_rate=0.0,
        commission_rate=0.0025,
    )
    # After the refactor, there should be ZERO post-hoc adjust_cash calls
    # in execute_buy_trade — the all-in cost was debited inside apply_long_buy.
    assert cash_history == [], (
        f"execute_buy_trade made {len(cash_history)} adjust_cash call(s) "
        f"({cash_history}); the commission must be baked into apply_long_buy, "
        f"not debited separately (BETA-004)."
    )
    snap = p.get_snapshot()
    # All-in cash debit: 100 * 10 * 1.0025 = 1002.5
    assert snap["cash"] == pytest.approx(100_000.0 - 1002.5)
    assert snap["positions"]["AAPL"]["long_cost_basis"] == pytest.approx(10.025)


def test_execute_sell_trade_no_longer_debits_cash_separately(monkeypatch) -> None:
    """BETA-004 mirror: execute_sell_trade must NOT adjust_cash for
    commission+stamp after the sell — the net proceeds are credited
    inside apply_long_sell at the fee-aware price."""
    from src.backtesting.trader_helpers import execute_sell_trade
    from src.backtesting.portfolio import Portfolio

    p = Portfolio(tickers=["AAPL"], initial_cash=100_000.0, margin_requirement=0.5)
    p.apply_long_buy("AAPL", 100, 10.0)
    starting_cash = p.get_cash()

    cash_history: list[float] = []
    orig_adjust = p.adjust_cash
    def spy_adjust(delta):
        cash_history.append(delta)
        orig_adjust(delta)
    monkeypatch.setattr(p, "adjust_cash", spy_adjust)

    execute_sell_trade(
        ticker="AAPL",
        quantity=100,
        current_price=11.0,
        portfolio=p,
        slippage_rate=0.0,
        commission_rate=0.0025,
        stamp_duty_rate=0.001,
    )
    # No post-hoc adjust_cash for fees
    assert cash_history == [], (
        f"execute_sell_trade made {len(cash_history)} post-fill adjust_cash "
        f"calls ({cash_history}); fees must be in apply_long_sell (BETA-004)."
    )
    snap = p.get_snapshot()
    # Net cash credit: 100 * 11 * (1 - 0.0025 - 0.001) = 100 * 11 * 0.9965 = 1096.15
    expected_cash = starting_cash + 100 * 11.0 * 0.9965
    assert snap["cash"] == pytest.approx(expected_cash)


# ---------------------------------------------------------------------------
# REF-006: _EMPTY_POSITION stays in sync with PositionState type
# ---------------------------------------------------------------------------

def test_empty_position_keys_match_position_state_type():
    """REF-006: any new field added to PositionState must also be added
    to _EMPTY_POSITION. This test catches the regression at the type
    level so the compiler/linter flags it next time someone adds
    e.g. a new ``stop_loss_pct`` field to PositionState."""
    from src.backtesting.portfolio import _EMPTY_POSITION
    from src.backtesting.types import PositionState, PositionStateRequired

    expected_keys = set(PositionStateRequired.__annotations__.keys()) | set(PositionState.__annotations__.keys())
    actual_keys = set(_EMPTY_POSITION.keys())
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    assert not missing, f"_EMPTY_POSITION is missing keys present in PositionState: {missing}"
    assert not extra, f"_EMPTY_POSITION has extra keys not in PositionState: {extra}"


def test_ensure_ticker_uses_empty_position_default():
    """REF-006: ensure_ticker must produce a position that is a copy of
    _EMPTY_POSITION (not a reference) so per-ticker mutations are isolated."""
    from src.backtesting.portfolio import _EMPTY_POSITION

    p = Portfolio(tickers=["AAPL"], initial_cash=100_000.0, margin_requirement=0.0)
    p.ensure_ticker("MSFT")
    assert p.get_positions()["MSFT"] == _EMPTY_POSITION
    # Verify it's a copy, not a shared reference
    p.get_positions()["MSFT"]["long"] = 100
    assert _EMPTY_POSITION["long"] == 0
