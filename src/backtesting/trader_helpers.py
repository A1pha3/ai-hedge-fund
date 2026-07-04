from __future__ import annotations

import logging
import re

from src.backtesting.portfolio import Portfolio

from .types import Action

logger = logging.getLogger(__name__)


def _compact_date(date_str: str) -> str:
    """Normalize a date string to ``%Y%m%d`` for safe comparison."""
    return re.sub(r"\D", "", date_str) if date_str else ""


def coerce_trade_action(action) -> Action:
    try:
        return Action(action) if not isinstance(action, Action) else action
    except Exception as e:
        # NS-17 / BH-017 family sibling (c269): 返回 HOLD 是 best-effort 有意为之
        # (回测不崩溃), 但之前完全静默 — 上游 agent 若发出 "unknown" / 大小写不
        # 匹配 ("BUY") / 带空白 ("buy ") 的信号, 该笔 BUY/SELL 被悄悄降级为 HOLD
        # (不交易), 回测表现失真且无任何信号。surface 到 logger.warning 让回测
        # operators 能感知"信号被吞"并定位上游 agent 输出格式漂移。repr() 避免
        # 空白/不可见字符在日志中消失。
        logger.warning(
            "coerce_trade_action 无法识别信号, 降级为 HOLD (回测该笔不交易, " "可能掩盖上游 agent 输出格式漂移): action=%r, error=%s",
            action,
            e,
        )
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


def _apply_commission_floor(
    commission_rate: float,
    quantity: float,
    price: float,
    floor_yuan: float = 5.0,
) -> float:
    """A-share 最低佣金 5 元/笔 — 当名义金额 * commission_rate < 5 时,
    等效提升 commission_rate 使其至少收取 5 元。

    等效佣金率 = max(rate, floor / notional)
    notional = abs(quantity) * price
    """
    # 用绝对值计算 notional, 避免卖出/负数量造成下限失效
    notional = abs(float(quantity)) * float(price)
    if notional <= 0 or floor_yuan <= 0:
        return float(commission_rate)
    floor_rate = float(floor_yuan) / notional
    return max(float(commission_rate), floor_rate)


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
    commission_floor_yuan: float = 5.0,
) -> int:
    requested_quantity, executed_price = _resolve_buy_execution(quantity, current_price, portfolio, slippage_rate, commission_rate, daily_turnover)
    # BETA-004: commission is now internalized in apply_long_buy (cost basis
    # is all-in, cash debit is all-in). No post-hoc adjust_cash for fees.
    # BETA-006: Apply 5 yuan commission floor — small trades would otherwise
    # pay sub-floor commission, underestimating real cost.
    effective_rate = _apply_commission_floor(commission_rate, requested_quantity, executed_price, commission_floor_yuan)
    return portfolio.apply_long_buy(ticker, requested_quantity, executed_price, commission_rate=effective_rate)


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
    commission_floor_yuan: float = 5.0,
) -> int:
    positions = portfolio.get_positions()
    # T+1 enforcement: block same-day sell if trade_date and entry_date are both provided and equal
    if trade_date:
        if ticker in positions:
            position = positions[ticker]
            entry_date = position.get("entry_date", "")
            if entry_date and _compact_date(entry_date) == _compact_date(trade_date) and position.get("long", 0) > 0:
                return 0

    executable_quantity = min(int(quantity), int(positions.get(ticker, {}).get("long", 0))) if quantity > 0 else 0
    executed_price = float(current_price) * (1 - _resolve_execution_slippage_rate(slippage_rate, executable_quantity, current_price, daily_turnover))
    # BETA-004: commission + stamp duty are internalized in apply_long_sell
    # (net proceeds price, realized gain computed on net). No post-hoc
    # adjust_cash for fees.
    # BETA-006: Apply 5 yuan commission floor to sell side too.
    effective_rate = _apply_commission_floor(commission_rate, executable_quantity, executed_price, commission_floor_yuan)
    return portfolio.apply_long_sell(
        ticker,
        executable_quantity,
        executed_price,
        commission_rate=effective_rate,
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
    commission_floor_yuan: float = 5.0,
) -> int:
    requested_quantity, executed_price = _resolve_short_open_execution(quantity, current_price, portfolio, slippage_rate, daily_turnover)
    # BETA-004 mirror: commission is internalized in apply_short_open
    # (net proceeds credited to cash). No post-hoc adjust_cash for fees.
    # NS-19(2): Apply 5 yuan commission floor — symmetric with execute_buy_trade /
    # execute_sell_trade (BETA-006). A small short (notional * rate < 5 yuan) would
    # otherwise undercharge commission, underestimating real shorting cost and
    # violating the finance-quant beta "missing transaction costs" gate.
    effective_rate = _apply_commission_floor(commission_rate, requested_quantity, executed_price, commission_floor_yuan)
    return portfolio.apply_short_open(ticker, requested_quantity, executed_price, commission_rate=effective_rate)


def execute_cover_trade(
    ticker: str,
    quantity: float,
    current_price: float,
    portfolio: Portfolio,
    slippage_rate: float,
    commission_rate: float,
    daily_turnover: float | None = None,
    commission_floor_yuan: float = 5.0,
) -> int:
    positions = portfolio.get_positions()
    executable_quantity = min(int(quantity), int(positions.get(ticker, {}).get("short", 0))) if quantity > 0 else 0
    executed_price = float(current_price) * (1 + _resolve_execution_slippage_rate(slippage_rate, executable_quantity, current_price, daily_turnover))
    # BETA-004 mirror: commission is internalized in apply_short_cover
    # (all-in cover cost debited from cash). No post-hoc adjust_cash.
    # NS-19(2): Apply 5 yuan commission floor — symmetric with execute_buy_trade /
    # execute_sell_trade (BETA-006) and with execute_short_trade above. A small cover
    # would otherwise undercharge commission, underestimating real cover cost.
    effective_rate = _apply_commission_floor(commission_rate, executable_quantity, executed_price, commission_floor_yuan)
    return portfolio.apply_short_cover(ticker, executable_quantity, executed_price, commission_rate=effective_rate)
