from __future__ import annotations

from typing import Any, Callable, Dict, Sequence

from src.execution.models import ExecutionPlan, PendingOrder
from src.portfolio.limit_handler import process_pending_buy, process_pending_sell, queue_pending_buy, queue_pending_sell


def dedupe_pending_orders(orders: Sequence[PendingOrder]) -> list[PendingOrder]:
    by_key: dict[tuple[str, str], PendingOrder] = {}
    for order in orders:
        by_key[(order.ticker, order.order_type)] = order
    return list(by_key.values())


def evaluate_pending_buy_order(
    *,
    order: PendingOrder,
    current_score: float,
    is_limit_up: bool,
    price: float,
) -> dict:
    return process_pending_buy(
        order,
        current_score=current_score,
        is_limit_up=is_limit_up,
        opened_board=not is_limit_up,
        current_price=price,
        reference_close=price,
    )


def apply_pending_buy_result(
    *,
    order: PendingOrder,
    result: dict,
    decisions: Dict[str, dict],
    next_pending_buy: list[PendingOrder],
    alerts: list[str],
) -> None:
    if result["action"] == "execute" and order.shares > 0:
        existing_qty = int(decisions.get(order.ticker, {}).get("quantity", 0))
        decisions[order.ticker] = {"action": "buy", "quantity": max(existing_qty, order.shares)}
        alerts.append(f"pending_buy_execute:{order.ticker}")
        return
    if result["action"] == "keep":
        next_pending_buy.append(order.model_copy(update={"queue_days": int(result["queue_days"])}))
        return
    if result["action"] == "remove":
        alerts.append(f"pending_buy_remove:{order.ticker}:{result['reason']}")


def evaluate_pending_sell_order(*, order: PendingOrder, is_limit_down: bool) -> dict:
    return process_pending_sell(order, is_limit_down=is_limit_down)


def apply_pending_sell_result(
    *,
    order: PendingOrder,
    result: dict,
    decisions: Dict[str, dict],
    next_pending_sell: list[PendingOrder],
    alerts: list[str],
) -> None:
    if result["action"] == "execute" and order.shares > 0:
        existing_qty = int(decisions.get(order.ticker, {}).get("quantity", 0))
        decisions[order.ticker] = {"action": "sell", "quantity": max(existing_qty, order.shares), "reason": order.reason}
        alerts.append(f"pending_sell_execute:{order.ticker}")
        return
    if result["action"] == "keep":
        next_pending_sell.append(order.model_copy(update={"queue_days": int(result["queue_days"])}))
        return
    if result["action"] == "risk_reduce_others":
        next_pending_sell.append(order.model_copy(update={"queue_days": int(result["queue_days"])}))
        alerts.append(f"pending_sell_risk_reduce:{order.ticker}")


def initialize_pending_queue_state() -> tuple[list[PendingOrder], list[PendingOrder], list[str]]:
    return [], [], []


def build_pending_watch_scores(prepared_plan: ExecutionPlan) -> dict[str, float]:
    return {item.ticker: item.score_final for item in prepared_plan.watchlist}


def process_pending_queues(
    *,
    pending_buy_queue: Sequence[PendingOrder],
    pending_sell_queue: Sequence[PendingOrder],
    prepared_plan: ExecutionPlan,
    current_prices: Dict[str, float],
    limit_up: set[str],
    limit_down: set[str],
    decisions: Dict[str, dict],
    process_single_pending_buy: Callable[..., None],
    process_single_pending_sell: Callable[..., None],
    dedupe_pending_orders_fn: Callable[[Sequence[PendingOrder]], list[PendingOrder]],
) -> tuple[list[PendingOrder], list[PendingOrder], list[str]]:
    next_pending_buy, next_pending_sell, alerts = initialize_pending_queue_state()
    watch_scores = build_pending_watch_scores(prepared_plan)
    for order in pending_buy_queue:
        process_single_pending_buy(
            order=order,
            current_prices=current_prices,
            limit_up=limit_up,
            watch_scores=watch_scores,
            decisions=decisions,
            next_pending_buy=next_pending_buy,
            alerts=alerts,
        )
    for order in pending_sell_queue:
        process_single_pending_sell(
            order=order,
            limit_down=limit_down,
            decisions=decisions,
            next_pending_sell=next_pending_sell,
            alerts=alerts,
        )
    return dedupe_pending_orders_fn(next_pending_buy), dedupe_pending_orders_fn(next_pending_sell), alerts


def queue_limit_up_buy_decision(
    *,
    pending_buy_queue: list[PendingOrder],
    ticker: str,
    decision: dict,
    trade_date_compact: str,
    buy_order_by_ticker: dict[str, Any],
    executed_trades: Dict[str, int],
) -> bool:
    matching_order = buy_order_by_ticker.get(ticker)
    pending_buy_queue.append(
        queue_pending_buy(
            ticker,
            original_score=(matching_order.score_final if matching_order is not None else 0.0),
            queue_date=trade_date_compact,
            shares=int(decision["quantity"]),
            amount=(matching_order.amount if matching_order is not None else 0.0),
        )
    )
    executed_trades[ticker] = 0
    return True


def queue_limit_down_sell_decision(
    *,
    pending_sell_queue: list[PendingOrder],
    positions: dict[str, dict[str, Any]],
    ticker: str,
    decision: dict,
    trade_date_compact: str,
    executed_trades: Dict[str, int],
) -> bool:
    long_shares = positions.get(ticker, {}).get("long", 0)
    sell_ratio = (int(decision["quantity"]) / long_shares) if long_shares else 1.0
    pending_sell_queue.append(
        queue_pending_sell(
            ticker,
            original_score=-1.0,
            queue_date=trade_date_compact,
            reason=str(decision.get("reason") or "limit_down_block"),
            shares=int(decision["quantity"]),
            sell_ratio=sell_ratio,
        )
    )
    executed_trades[ticker] = 0
    return True


def queue_limit_blocked_pipeline_decision(
    *,
    ticker: str,
    decision: dict,
    normalized_ticker: str,
    trade_date_compact: str,
    limit_up: set[str],
    limit_down: set[str],
    buy_order_by_ticker: dict[str, Any],
    executed_trades: Dict[str, int],
    queue_limit_up_buy_decision_fn: Callable[..., bool],
    queue_limit_down_sell_decision_fn: Callable[..., bool],
) -> bool:
    if decision["action"] == "buy" and normalized_ticker in limit_up:
        return queue_limit_up_buy_decision_fn(
            ticker=ticker,
            decision=decision,
            trade_date_compact=trade_date_compact,
            buy_order_by_ticker=buy_order_by_ticker,
            executed_trades=executed_trades,
        )
    if decision["action"] == "sell" and normalized_ticker in limit_down:
        return queue_limit_down_sell_decision_fn(
            ticker=ticker,
            decision=decision,
            trade_date_compact=trade_date_compact,
            executed_trades=executed_trades,
        )
    return False
