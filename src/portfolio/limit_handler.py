"""涨跌停处理器。"""

from __future__ import annotations

from src.execution.models import PendingOrder


def queue_pending_buy(ticker: str, original_score: float, queue_date: str, reason: str = "limit_up_block", shares: int = 0, amount: float = 0.0) -> PendingOrder:
    return PendingOrder(ticker=ticker, order_type="buy", original_score=original_score, shares=shares, amount=amount, queue_date=queue_date, queue_days=1, reason=reason)


def queue_pending_sell(ticker: str, original_score: float, queue_date: str, reason: str = "limit_down_block", shares: int = 0, sell_ratio: float = 1.0) -> PendingOrder:
    return PendingOrder(ticker=ticker, order_type="sell", original_score=original_score, shares=shares, sell_ratio=sell_ratio, queue_date=queue_date, queue_days=1, reason=reason)


def process_pending_buy(order: PendingOrder, current_score: float, is_limit_up: bool, opened_board: bool, current_price: float, reference_close: float) -> dict:
    next_days = order.queue_days + 1
    if is_limit_up and next_days >= 2:
        return {"action": "remove", "reason": "overheated_30d", "cooldown_days": 30}
    if opened_board and current_score >= order.original_score * 0.8 and current_price <= reference_close * 1.05:
        return {"action": "execute", "reason": "board_opened"}
    return {"action": "keep", "reason": "await_recheck", "queue_days": next_days}


def process_pending_sell(order: PendingOrder, is_limit_down: bool) -> dict:
    next_days = order.queue_days + 1
    if not is_limit_down:
        return {"action": "execute", "reason": "auction_exit"}
    if next_days >= 3:
        return {"action": "risk_reduce_others", "reason": "three_limit_down_days", "queue_days": next_days}
    return {"action": "keep", "reason": "limit_down_persist", "queue_days": next_days}
