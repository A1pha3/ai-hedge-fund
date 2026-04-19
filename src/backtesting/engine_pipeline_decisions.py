"""Pipeline decision execution logic extracted from BacktestEngine.

This module encapsulates all pipeline decision execution: applying decisions
to the portfolio, queuing limit-blocked orders, and recording execution
side effects (exit reentry cooldowns, long entry/exit tracking).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Callable, Sequence

from src.execution.models import ExecutionPlan, PendingOrder

from .engine_pending_helpers import (
    dedupe_pending_orders,
    queue_limit_blocked_pipeline_decision,
    queue_limit_down_sell_decision,
    queue_limit_up_buy_decision,
)
from .portfolio import Portfolio
from .trader import TradeExecutor


@dataclass(frozen=True)
class PipelineDecisionExecutionInputs:
    price: float
    normalized_ticker: str


class PipelineDecisionExecutor:
    """Encapsulates all pipeline decision execution logic.

    Coordinates applying pipeline decisions to the portfolio, handling
    limit-blocked orders via pending queues, and recording execution
    side effects such as exit reentry cooldowns and long entry tracking.
    """

    def __init__(
        self,
        *,
        portfolio: Portfolio,
        executor: TradeExecutor,
        register_cooldown_fn: Callable[[str, str, str], None],
    ) -> None:
        self._portfolio = portfolio
        self._executor = executor
        self._register_cooldown_fn = register_cooldown_fn

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def apply_decisions(
        self,
        *,
        prepared_plan: ExecutionPlan,
        current_prices: dict[str, float],
        daily_turnovers: dict[str, float],
        limit_up: set[str],
        limit_down: set[str],
        trade_date_compact: str,
        decisions: dict[str, dict],
        executed_trades: dict[str, int],
        pending_buy_queue: list[PendingOrder],
        pending_sell_queue: list[PendingOrder],
    ) -> None:
        buy_order_by_ticker, watchlist_by_ticker = self._build_lookup_maps(prepared_plan)
        for ticker, decision in decisions.items():
            self._apply_single(
                ticker=ticker,
                decision=decision,
                current_prices=current_prices,
                daily_turnovers=daily_turnovers,
                limit_up=limit_up,
                limit_down=limit_down,
                trade_date_compact=trade_date_compact,
                buy_order_by_ticker=buy_order_by_ticker,
                watchlist_by_ticker=watchlist_by_ticker,
                executed_trades=executed_trades,
                pending_buy_queue=pending_buy_queue,
                pending_sell_queue=pending_sell_queue,
            )
        self._dedupe_queues(pending_buy_queue, pending_sell_queue)

    # ------------------------------------------------------------------
    # Lookup maps
    # ------------------------------------------------------------------

    @staticmethod
    def _build_lookup_maps(prepared_plan: ExecutionPlan) -> tuple[dict[str, Any], dict[str, Any]]:
        return (
            {order.ticker: order for order in prepared_plan.buy_orders},
            {item.ticker: item for item in prepared_plan.watchlist},
        )

    # ------------------------------------------------------------------
    # Queue deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def _dedupe_queues(pending_buy_queue: list[PendingOrder], pending_sell_queue: list[PendingOrder]) -> None:
        pending_buy_queue[:] = dedupe_pending_orders(pending_buy_queue)
        pending_sell_queue[:] = dedupe_pending_orders(pending_sell_queue)

    # ------------------------------------------------------------------
    # Single decision application
    # ------------------------------------------------------------------

    def _apply_single(
        self,
        *,
        ticker: str,
        decision: dict,
        current_prices: dict[str, float],
        daily_turnovers: dict[str, float],
        limit_up: set[str],
        limit_down: set[str],
        trade_date_compact: str,
        buy_order_by_ticker: dict[str, Any],
        watchlist_by_ticker: dict[str, Any],
        executed_trades: dict[str, int],
        pending_buy_queue: list[PendingOrder],
        pending_sell_queue: list[PendingOrder],
    ) -> None:
        execution_inputs = self._build_execution_inputs(
            ticker=ticker,
            current_prices=current_prices,
        )
        if execution_inputs is None:
            return
        if self._queue_if_blocked(
            ticker=ticker,
            decision=decision,
            normalized_ticker=execution_inputs.normalized_ticker,
            trade_date_compact=trade_date_compact,
            limit_up=limit_up,
            limit_down=limit_down,
            buy_order_by_ticker=buy_order_by_ticker,
            executed_trades=executed_trades,
            pending_buy_queue=pending_buy_queue,
            pending_sell_queue=pending_sell_queue,
        ):
            return
        self._execute_and_record(
            ticker=ticker,
            decision=decision,
            execution_inputs=execution_inputs,
            daily_turnovers=daily_turnovers,
            limit_up=limit_up,
            limit_down=limit_down,
            trade_date_compact=trade_date_compact,
            buy_order_by_ticker=buy_order_by_ticker,
            watchlist_by_ticker=watchlist_by_ticker,
            executed_trades=executed_trades,
        )

    # ------------------------------------------------------------------
    # Execution inputs
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_price(*, ticker: str, current_prices: dict[str, float]) -> float | None:
        return current_prices.get(ticker)

    def _build_execution_inputs(
        self,
        *,
        ticker: str,
        current_prices: dict[str, float],
    ) -> PipelineDecisionExecutionInputs | None:
        price = self._resolve_price(ticker=ticker, current_prices=current_prices)
        if price is None:
            return None
        return PipelineDecisionExecutionInputs(
            price=price,
            normalized_ticker=self._normalize_ticker(ticker),
        )

    # ------------------------------------------------------------------
    # Limit-blocked queuing
    # ------------------------------------------------------------------

    def _queue_if_blocked(
        self,
        *,
        ticker: str,
        decision: dict,
        normalized_ticker: str,
        trade_date_compact: str,
        limit_up: set[str],
        limit_down: set[str],
        buy_order_by_ticker: dict[str, Any],
        executed_trades: dict[str, int],
        pending_buy_queue: list[PendingOrder],
        pending_sell_queue: list[PendingOrder],
    ) -> bool:
        return self._queue_limit_blocked(
            ticker=ticker,
            decision=decision,
            normalized_ticker=normalized_ticker,
            trade_date_compact=trade_date_compact,
            limit_up=limit_up,
            limit_down=limit_down,
            buy_order_by_ticker=buy_order_by_ticker,
            executed_trades=executed_trades,
            pending_buy_queue=pending_buy_queue,
            pending_sell_queue=pending_sell_queue,
        )

    # ------------------------------------------------------------------
    # Trade execution flow
    # ------------------------------------------------------------------

    def _execute_trade_flow(
        self,
        *,
        ticker: str,
        decision: dict,
        price: float,
        normalized_ticker: str,
        daily_turnovers: dict[str, float],
        limit_up: set[str],
        limit_down: set[str],
    ) -> int:
        return self._execute_decision(
            ticker=ticker,
            decision=decision,
            price=price,
            normalized_ticker=normalized_ticker,
            daily_turnovers=daily_turnovers,
            limit_up=limit_up,
            limit_down=limit_down,
        )

    # ------------------------------------------------------------------
    # Execute and record
    # ------------------------------------------------------------------

    def _execute_and_record(
        self,
        *,
        ticker: str,
        decision: dict,
        execution_inputs: PipelineDecisionExecutionInputs,
        daily_turnovers: dict[str, float],
        limit_up: set[str],
        limit_down: set[str],
        trade_date_compact: str,
        buy_order_by_ticker: dict[str, Any],
        watchlist_by_ticker: dict[str, Any],
        executed_trades: dict[str, int],
    ) -> None:
        executed_qty = self._execute_trade_flow(
            ticker=ticker,
            decision=decision,
            price=execution_inputs.price,
            normalized_ticker=execution_inputs.normalized_ticker,
            daily_turnovers=daily_turnovers,
            limit_up=limit_up,
            limit_down=limit_down,
        )
        executed_trades[ticker] = executed_qty
        self._record_side_effects(
            ticker=ticker,
            decision=decision,
            executed_qty=executed_qty,
            trade_date_compact=trade_date_compact,
            buy_order_by_ticker=buy_order_by_ticker,
            watchlist_by_ticker=watchlist_by_ticker,
        )

    # ------------------------------------------------------------------
    # Limit-blocked pipeline decision
    # ------------------------------------------------------------------

    def _queue_limit_blocked(
        self,
        *,
        ticker: str,
        decision: dict,
        normalized_ticker: str,
        trade_date_compact: str,
        limit_up: set[str],
        limit_down: set[str],
        buy_order_by_ticker: dict[str, Any],
        executed_trades: dict[str, int],
        pending_buy_queue: list[PendingOrder],
        pending_sell_queue: list[PendingOrder],
    ) -> bool:
        return queue_limit_blocked_pipeline_decision(
            **self._build_queue_limit_blocked_kwargs(
                ticker=ticker,
                decision=decision,
                normalized_ticker=normalized_ticker,
                trade_date_compact=trade_date_compact,
                limit_up=limit_up,
                limit_down=limit_down,
                buy_order_by_ticker=buy_order_by_ticker,
                executed_trades=executed_trades,
                pending_buy_queue=pending_buy_queue,
                pending_sell_queue=pending_sell_queue,
            )
        )

    def _build_queue_limit_blocked_kwargs(
        self,
        *,
        ticker: str,
        decision: dict,
        normalized_ticker: str,
        trade_date_compact: str,
        limit_up: set[str],
        limit_down: set[str],
        buy_order_by_ticker: dict[str, Any],
        executed_trades: dict[str, int],
        pending_buy_queue: list[PendingOrder],
        pending_sell_queue: list[PendingOrder],
    ) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "decision": decision,
            "normalized_ticker": normalized_ticker,
            "trade_date_compact": trade_date_compact,
            "limit_up": limit_up,
            "limit_down": limit_down,
            "buy_order_by_ticker": buy_order_by_ticker,
            "executed_trades": executed_trades,
            "queue_limit_up_buy_decision_fn": self._build_queue_limit_up_buy_fn(pending_buy_queue),
            "queue_limit_down_sell_decision_fn": self._build_queue_limit_down_sell_fn(pending_sell_queue),
        }

    # ------------------------------------------------------------------
    # Limit-up buy / limit-down sell queuing
    # ------------------------------------------------------------------

    def _build_queue_limit_up_buy_fn(self, pending_buy_queue: list[PendingOrder]) -> Callable[..., bool]:
        def _queue_limit_up_buy(
            *,
            ticker: str,
            decision: dict,
            trade_date_compact: str,
            buy_order_by_ticker: dict[str, Any],
            executed_trades: dict[str, int],
        ) -> bool:
            return queue_limit_up_buy_decision(
                pending_buy_queue=pending_buy_queue,
                ticker=ticker,
                decision=decision,
                trade_date_compact=trade_date_compact,
                buy_order_by_ticker=buy_order_by_ticker,
                executed_trades=executed_trades,
            )
        return _queue_limit_up_buy

    def _build_queue_limit_down_sell_fn(self, pending_sell_queue: list[PendingOrder]) -> Callable[..., bool]:
        def _queue_limit_down_sell(
            *,
            ticker: str,
            decision: dict,
            trade_date_compact: str,
            executed_trades: dict[str, int],
        ) -> bool:
            return queue_limit_down_sell_decision(
                pending_sell_queue=pending_sell_queue,
                positions=self._portfolio.get_positions(),
                ticker=ticker,
                decision=decision,
                trade_date_compact=trade_date_compact,
                executed_trades=executed_trades,
            )
        return _queue_limit_down_sell

    # ------------------------------------------------------------------
    # Core trade execution
    # ------------------------------------------------------------------

    def _execute_decision(
        self,
        *,
        ticker: str,
        decision: dict,
        price: float,
        normalized_ticker: str,
        daily_turnovers: dict[str, float],
        limit_up: set[str],
        limit_down: set[str],
    ) -> int:
        return self._executor.execute_trade(
            ticker,
            decision["action"],
            decision["quantity"],
            price,
            self._portfolio,
            is_limit_up=normalized_ticker in limit_up,
            is_limit_down=normalized_ticker in limit_down,
            daily_turnover=daily_turnovers.get(ticker),
        )

    # ------------------------------------------------------------------
    # Side-effect recording
    # ------------------------------------------------------------------

    def _record_side_effects(
        self,
        *,
        ticker: str,
        decision: dict,
        executed_qty: int,
        trade_date_compact: str,
        buy_order_by_ticker: dict[str, Any],
        watchlist_by_ticker: dict[str, Any],
    ) -> None:
        if executed_qty <= 0:
            return
        if decision["action"] == "buy":
            self._record_buy_execution(
                ticker=ticker,
                executed_qty=executed_qty,
                trade_date_compact=trade_date_compact,
                buy_order_by_ticker=buy_order_by_ticker,
                watchlist_by_ticker=watchlist_by_ticker,
            )
            return
        if decision["action"] == "sell":
            self._record_sell_execution(
                ticker=ticker,
                decision=decision,
                trade_date_compact=trade_date_compact,
            )

    def _record_sell_execution(
        self,
        *,
        ticker: str,
        decision: dict,
        trade_date_compact: str,
    ) -> None:
        trigger_reason = str(decision.get("reason") or "")
        self._portfolio.record_long_exit(ticker, trigger_reason=trigger_reason)
        self._register_cooldown_fn(ticker, trade_date_compact, trigger_reason)

    def _record_buy_execution(
        self,
        *,
        ticker: str,
        executed_qty: int,
        trade_date_compact: str,
        buy_order_by_ticker: dict[str, Any],
        watchlist_by_ticker: dict[str, Any],
    ) -> None:
        existing_long_before = int(self._portfolio.get_positions()[ticker]["long"]) - int(executed_qty)
        watch_item = watchlist_by_ticker.get(ticker)
        matching_order = buy_order_by_ticker.get(ticker)
        self._portfolio.record_long_entry(
            ticker,
            trade_date_compact,
            reset=existing_long_before <= 0,
            entry_score=(matching_order.score_final if matching_order is not None else (watch_item.score_final if watch_item is not None else 0.0)),
            quality_score=(matching_order.quality_score if matching_order is not None else (watch_item.quality_score if watch_item is not None else 0.5)),
            industry_sw="",
            is_fundamental_driven=False,
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        return str(ticker).split(".")[0].upper()
