"""信号衰减检查器。"""

from __future__ import annotations

from src.execution.models import ExecutionPlan


def apply_signal_decay(
    plan: ExecutionPlan,
    trade_date_t1: str,
    refreshed_scores: dict[str, float] | None = None,
    atr_values: dict[str, float] | None = None,
    open_gap_pct: dict[str, float] | None = None,
    negative_news_tickers: set[str] | None = None,
) -> ExecutionPlan:
    refreshed_scores = refreshed_scores or {}
    atr_values = atr_values or {}
    open_gap_pct = open_gap_pct or {}
    negative_news_tickers = negative_news_tickers or set()

    filtered_buy_orders = []
    risk_alerts = list(plan.risk_alerts)
    for order in plan.buy_orders:
        ticker = order.ticker
        if ticker in negative_news_tickers:
            risk_alerts.append(f"cancel_buy_negative_news:{ticker}")
            continue
        if open_gap_pct.get(ticker, 0.0) > (1.5 * atr_values.get(ticker, float("inf"))):
            risk_alerts.append(f"cancel_buy_gap_open:{ticker}")
            continue
        refreshed_score = refreshed_scores.get(ticker)
        if refreshed_score is not None and refreshed_score < (order.score_final * 0.8):
            risk_alerts.append(f"cancel_buy_signal_decay:{ticker}")
            continue
        filtered_buy_orders.append(order)

    plan.buy_orders = filtered_buy_orders
    plan.risk_alerts = risk_alerts
    return plan
