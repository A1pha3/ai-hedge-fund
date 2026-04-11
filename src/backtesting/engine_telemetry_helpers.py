from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any, Callable, Sequence

from src.execution.models import ExecutionPlan, PendingOrder

if TYPE_CHECKING:
    from .engine import PipelineModeDayState
    from .engine_pipeline_helpers import PipelineDayContext


def build_pipeline_queue_counts(*, pending_buy_queue: Sequence[PendingOrder], pending_sell_queue: Sequence[PendingOrder]) -> dict[str, int]:
    return {
        "pending_buy_queue_count": len(pending_buy_queue),
        "pending_sell_queue_count": len(pending_sell_queue),
    }


def build_pipeline_day_timing_seconds(
    *,
    load_market_data_seconds: float,
    pre_market_seconds: float,
    intraday_seconds: float,
    append_daily_state_seconds: float,
    post_market_seconds: float,
    total_day_seconds: float,
) -> dict[str, float]:
    return {
        "load_market_data_seconds": load_market_data_seconds,
        "pre_market_seconds": pre_market_seconds,
        "intraday_seconds": intraday_seconds,
        "append_daily_state_seconds": append_daily_state_seconds,
        "post_market_seconds": post_market_seconds,
        "total_day_seconds": total_day_seconds,
    }


def build_pipeline_runtime_state_payload(
    *,
    portfolio_snapshot: dict[str, Any],
    pending_buy_queue: Sequence[PendingOrder],
    pending_sell_queue: Sequence[PendingOrder],
    exit_reentry_cooldowns: dict[str, dict],
) -> dict[str, object]:
    return {
        "portfolio_snapshot": portfolio_snapshot,
        "pending_buy_queue": list(pending_buy_queue),
        "pending_sell_queue": list(pending_sell_queue),
        "exit_reentry_cooldowns": exit_reentry_cooldowns,
    }


def build_pipeline_day_timing_payload(
    *,
    trade_date_compact: str,
    active_tickers: Sequence[str],
    executed_trades: dict[str, int],
    execution_plan_observations: list[dict],
    load_market_data_seconds: float,
    pre_market_seconds: float,
    intraday_seconds: float,
    append_daily_state_seconds: float,
    post_market_seconds: float,
    total_day_seconds: float,
    pending_plan: ExecutionPlan | None,
    previous_plan_counts: dict[str, int],
    previous_plan_timing: dict[str, float],
    previous_plan_funnel_diagnostics: dict,
    pending_buy_queue: Sequence[PendingOrder],
    pending_sell_queue: Sequence[PendingOrder],
    timing_payload_builder: Callable[..., dict],
) -> dict:
    return timing_payload_builder(
        trade_date_compact=trade_date_compact,
        active_tickers=active_tickers,
        executed_trades=executed_trades,
        execution_plan_observations=execution_plan_observations,
        pending_plan=pending_plan,
        previous_plan_counts=previous_plan_counts,
        previous_plan_timing=previous_plan_timing,
        previous_plan_funnel_diagnostics=previous_plan_funnel_diagnostics,
        **build_pipeline_queue_counts(
            pending_buy_queue=pending_buy_queue,
            pending_sell_queue=pending_sell_queue,
        ),
        **build_pipeline_day_timing_seconds(
            load_market_data_seconds=load_market_data_seconds,
            pre_market_seconds=pre_market_seconds,
            intraday_seconds=intraday_seconds,
            append_daily_state_seconds=append_daily_state_seconds,
            post_market_seconds=post_market_seconds,
            total_day_seconds=total_day_seconds,
        ),
    )


def build_pipeline_day_event_payload(
    *,
    trade_date_compact: str,
    active_tickers: Sequence[str],
    executed_trades: dict[str, int],
    decisions: dict[str, dict],
    current_prices: dict[str, float],
    prepared_plan: ExecutionPlan | None,
    pending_plan: ExecutionPlan | None,
    execution_plan_observations: list[dict],
    timing_seconds: dict,
    portfolio_snapshot: dict[str, Any],
    pending_buy_queue: Sequence[PendingOrder],
    pending_sell_queue: Sequence[PendingOrder],
    exit_reentry_cooldowns: dict[str, dict],
    event_payload_builder: Callable[..., dict],
) -> dict:
    return event_payload_builder(
        trade_date_compact=trade_date_compact,
        active_tickers=active_tickers,
        executed_trades=executed_trades,
        decisions=decisions,
        current_prices=current_prices,
        prepared_plan=prepared_plan,
        pending_plan=pending_plan,
        execution_plan_observations=execution_plan_observations,
        timing_seconds=timing_seconds,
        **build_pipeline_runtime_state_payload(
            portfolio_snapshot=portfolio_snapshot,
            pending_buy_queue=pending_buy_queue,
            pending_sell_queue=pending_sell_queue,
            exit_reentry_cooldowns=exit_reentry_cooldowns,
        ),
    )


def build_pipeline_day_record_payloads(
    *,
    day_context: "PipelineDayContext",
    day_state: "PipelineModeDayState",
    pending_plan: ExecutionPlan | None,
    current_prices: dict[str, float],
    day_started_at: float,
    execution_plan_observations: list[dict],
    pending_buy_queue: Sequence[PendingOrder],
    pending_sell_queue: Sequence[PendingOrder],
    portfolio_snapshot: dict[str, Any],
    exit_reentry_cooldowns: dict[str, dict],
    timing_payload_builder: Callable[..., dict],
    event_payload_builder: Callable[..., dict],
) -> tuple[dict, dict]:
    timing_payload = build_pipeline_day_timing_payload(
        trade_date_compact=day_context.trade_date_compact,
        active_tickers=day_context.active_tickers,
        executed_trades=day_state.executed_trades,
        execution_plan_observations=execution_plan_observations,
        load_market_data_seconds=day_context.load_market_data_seconds,
        pre_market_seconds=day_state.pre_market_seconds,
        intraday_seconds=day_state.intraday_seconds,
        append_daily_state_seconds=day_state.append_daily_state_seconds,
        post_market_seconds=day_state.post_market_seconds,
        total_day_seconds=perf_counter() - day_started_at,
        pending_plan=pending_plan,
        previous_plan_counts=day_state.previous_plan_counts,
        previous_plan_timing=day_state.previous_plan_timing,
        previous_plan_funnel_diagnostics=day_state.previous_plan_funnel_diagnostics,
        pending_buy_queue=pending_buy_queue,
        pending_sell_queue=pending_sell_queue,
        timing_payload_builder=timing_payload_builder,
    )
    event_payload = build_pipeline_day_event_payload(
        trade_date_compact=day_context.trade_date_compact,
        active_tickers=day_context.active_tickers,
        executed_trades=day_state.executed_trades,
        decisions=day_state.decisions,
        current_prices=current_prices,
        prepared_plan=day_state.prepared_plan,
        pending_plan=pending_plan,
        execution_plan_observations=execution_plan_observations,
        timing_seconds=timing_payload["timing_seconds"],
        portfolio_snapshot=portfolio_snapshot,
        pending_buy_queue=pending_buy_queue,
        pending_sell_queue=pending_sell_queue,
        exit_reentry_cooldowns=exit_reentry_cooldowns,
        event_payload_builder=event_payload_builder,
    )
    return timing_payload, event_payload
