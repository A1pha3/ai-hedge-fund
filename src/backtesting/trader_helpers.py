from __future__ import annotations

from src.backtesting.portfolio import Portfolio

from .types import Action


def coerce_trade_action(action) -> Action:
    try:
        return Action(action) if not isinstance(action, Action) else action
    except Exception:
        return Action.HOLD


def _resolve_execution_slippage_rate(
    slippage_rate: float,
    quantity: float,
    current_price: float,
    daily_turnover: float | None = None,
) -> float:
    if daily_turnover is None or daily_turnover <= 0:
        return float(slippage_rate)
    order_notional = abs(float(quantity)) * float(current_price)
    if order_notional <= 0:
        return float(slippage_rate)
    participation_ratio = min(order_notional / float(daily_turnover), 1.0)
    return round(float(slippage_rate) * (1.0 + participation_ratio), 6)


def _resolve_buy_execution(quantity: float, current_price: float, portfolio: Portfolio, slippage_rate: float, commission_rate: float, daily_turnover: float | None = None) -> tuple[int, float]:
    requested_quantity = max(int(quantity), 0)
    base_price = float(current_price)
    if requested_quantity <= 0 or base_price <= 0:
        return 0, base_price

    executable_quantity = requested_quantity
    while True:
        slippage = _resolve_execution_slippage_rate(slippage_rate, executable_quantity, base_price, daily_turnover)
        executed_price = base_price * (1 + slippage)
        max_affordable = int(portfolio.get_cash() / (executed_price * (1 + commission_rate))) if executed_price > 0 else 0
        next_quantity = min(requested_quantity, max_affordable)
        if next_quantity == executable_quantity:
            return executable_quantity, executed_price
        if next_quantity <= 0:
            return 0, executed_price
        executable_quantity = next_quantity


def _resolve_short_open_execution(quantity: float, current_price: float, portfolio: Portfolio, slippage_rate: float, daily_turnover: float | None = None) -> tuple[int, float]:
    requested_quantity = max(int(quantity), 0)
    base_price = float(current_price)
    if requested_quantity <= 0 or base_price <= 0:
        return 0, base_price

    margin_requirement = float(portfolio.get_snapshot()["margin_requirement"])
    executable_quantity = requested_quantity
    while True:
        slippage = _resolve_execution_slippage_rate(slippage_rate, executable_quantity, base_price, daily_turnover)
        executed_price = base_price * (1 - slippage)
        max_shortable = requested_quantity
        if margin_requirement > 0 and executed_price > 0:
            max_shortable = int(portfolio.get_cash() / (executed_price * margin_requirement))
        next_quantity = min(requested_quantity, max_shortable)
        if next_quantity == executable_quantity:
            return executable_quantity, executed_price
        if next_quantity <= 0:
            return 0, executed_price
        executable_quantity = next_quantity


def execute_buy_trade(
    ticker: str,
    quantity: float,
    current_price: float,
    portfolio: Portfolio,
    slippage_rate: float,
    commission_rate: float,
    daily_turnover: float | None = None,
) -> int:
    requested_quantity, executed_price = _resolve_buy_execution(quantity, current_price, portfolio, slippage_rate, commission_rate, daily_turnover)
    # BETA-004: commission is now internalized in apply_long_buy (cost basis
    # is all-in, cash debit is all-in). No post-hoc adjust_cash for fees.
    return portfolio.apply_long_buy(ticker, requested_quantity, executed_price, commission_rate=commission_rate)


def execute_sell_trade(
    ticker: str,
    quantity: float,
    current_price: float,
    portfolio: Portfolio,
    slippage_rate: float,
    commission_rate: float,
    stamp_duty_rate: float,
    trade_date: str | None = None,
    daily_turnover: float | None = None,
) -> int:
    positions = portfolio.get_positions()
    # T+1 enforcement: block same-day sell if trade_date and entry_date are both provided and equal
    if trade_date:
        if ticker in positions:
            position = positions[ticker]
            entry_date = position.get("entry_date", "")
            if entry_date and entry_date == trade_date and position.get("long", 0) > 0:
                return 0

    executable_quantity = min(int(quantity), int(positions.get(ticker, {}).get("long", 0))) if quantity > 0 else 0
    executed_price = float(current_price) * (1 - _resolve_execution_slippage_rate(slippage_rate, executable_quantity, current_price, daily_turnover))
    # BETA-004: commission + stamp duty are internalized in apply_long_sell
    # (net proceeds price, realized gain computed on net). No post-hoc
    # adjust_cash for fees.
    return portfolio.apply_long_sell(
        ticker,
        executable_quantity,
        executed_price,
        commission_rate=commission_rate,
        stamp_duty_rate=stamp_duty_rate,
    )


def execute_short_trade(
    ticker: str,
    quantity: float,
    current_price: float,
    portfolio: Portfolio,
    slippage_rate: float,
    commission_rate: float,
    daily_turnover: float | None = None,
) -> int:
    requested_quantity, executed_price = _resolve_short_open_execution(quantity, current_price, portfolio, slippage_rate, daily_turnover)
    executed = portfolio.apply_short_open(ticker, requested_quantity, executed_price)
    if executed > 0:
        portfolio.adjust_cash(-(executed * executed_price * commission_rate))
    return executed


def execute_cover_trade(
    ticker: str,
    quantity: float,
    current_price: float,
    portfolio: Portfolio,
    slippage_rate: float,
    commission_rate: float,
    daily_turnover: float | None = None,
) -> int:
    positions = portfolio.get_positions()
    executable_quantity = min(int(quantity), int(positions.get(ticker, {}).get("short", 0))) if quantity > 0 else 0
    executed_price = float(current_price) * (1 + _resolve_execution_slippage_rate(slippage_rate, executable_quantity, current_price, daily_turnover))
    executed = portfolio.apply_short_cover(ticker, executable_quantity, executed_price)
    if executed > 0:
        portfolio.adjust_cash(-(executed * executed_price * commission_rate))
    return executed
