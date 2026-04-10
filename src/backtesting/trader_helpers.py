from __future__ import annotations

from src.backtesting.portfolio import Portfolio

from .types import Action


def coerce_trade_action(action) -> Action:
    try:
        return Action(action) if not isinstance(action, Action) else action
    except Exception:
        return Action.HOLD


def execute_buy_trade(ticker: str, quantity: float, current_price: float, portfolio: Portfolio, slippage_rate: float, commission_rate: float) -> int:
    executed_price = float(current_price) * (1 + slippage_rate)
    max_affordable = int(portfolio.get_cash() / (executed_price * (1 + commission_rate))) if executed_price > 0 else 0
    requested_quantity = min(int(quantity), max_affordable)
    executed = portfolio.apply_long_buy(ticker, requested_quantity, executed_price)
    if executed > 0:
        portfolio.adjust_cash(-(executed * executed_price * commission_rate))
    return executed


def execute_sell_trade(ticker: str, quantity: float, current_price: float, portfolio: Portfolio, slippage_rate: float, commission_rate: float, stamp_duty_rate: float) -> int:
    executed_price = float(current_price) * (1 - slippage_rate)
    executed = portfolio.apply_long_sell(ticker, int(quantity), executed_price)
    if executed > 0:
        gross_amount = executed * executed_price
        portfolio.adjust_cash(-(gross_amount * (commission_rate + stamp_duty_rate)))
    return executed


def execute_short_trade(ticker: str, quantity: float, current_price: float, portfolio: Portfolio, slippage_rate: float, commission_rate: float) -> int:
    executed_price = float(current_price) * (1 - slippage_rate)
    executed = portfolio.apply_short_open(ticker, int(quantity), executed_price)
    if executed > 0:
        portfolio.adjust_cash(-(executed * executed_price * commission_rate))
    return executed


def execute_cover_trade(ticker: str, quantity: float, current_price: float, portfolio: Portfolio, slippage_rate: float, commission_rate: float) -> int:
    executed_price = float(current_price) * (1 + slippage_rate)
    executed = portfolio.apply_short_cover(ticker, int(quantity), executed_price)
    if executed > 0:
        portfolio.adjust_cash(-(executed * executed_price * commission_rate))
    return executed
