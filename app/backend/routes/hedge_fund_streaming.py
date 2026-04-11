import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.backend.models.events import (
    CompleteEvent,
    ErrorEvent,
    ProgressUpdateEvent,
    StartEvent,
)
from app.backend.models.schemas import (
    BacktestDayResult,
    BacktestPerformanceMetrics,
    BacktestRequest,
    HedgeFundRequest,
)
from app.backend.services.api_key_service import ApiKeyService
from app.backend.services.backtest_service import BacktestService
from app.backend.services.graph import parse_hedge_fund_response, run_graph_async
from src.utils.progress import progress


def hydrate_api_keys(request_data: HedgeFundRequest | BacktestRequest, db: Session) -> None:
    if request_data.api_keys:
        return

    request_data.api_keys = ApiKeyService(db).get_api_keys_dict()


def resolve_model_provider(model_provider: Any) -> Any:
    return getattr(model_provider, "value", model_provider)


async def wait_for_disconnect(request: Request) -> bool:
    """Wait for client disconnect and return True when it happens."""
    try:
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                return True
    except Exception:
        return True


def create_progress_handler(progress_queue: asyncio.Queue[ProgressUpdateEvent]):
    def progress_handler(agent_name: str, ticker: str | None, status: str, analysis: str | None, timestamp: str | None) -> None:
        progress_queue.put_nowait(
            ProgressUpdateEvent(
                agent=agent_name,
                ticker=ticker,
                status=status,
                timestamp=timestamp,
                analysis=analysis,
            )
        )

    return progress_handler


def create_backtest_progress_event(update: dict[str, Any]) -> ProgressUpdateEvent | None:
    if update["type"] == "progress":
        return ProgressUpdateEvent(
            agent="backtest",
            ticker=None,
            status=f"Processing {update['current_date']} ({update['current_step']}/{update['total_dates']})",
            timestamp=None,
            analysis=None,
        )

    if update["type"] == "backtest_result":
        backtest_result = BacktestDayResult(**update["data"])
        return ProgressUpdateEvent(
            agent="backtest",
            ticker=None,
            status=f"Completed {backtest_result.date} - Portfolio: ${backtest_result.portfolio_value:,.2f}",
            timestamp=None,
            analysis=json.dumps(update["data"]),
        )

    return None


def create_backtest_progress_callback(progress_queue: asyncio.Queue[ProgressUpdateEvent]):
    def progress_callback(update: dict[str, Any]) -> None:
        event = create_backtest_progress_event(update)
        if event is not None:
            progress_queue.put_nowait(event)

    return progress_callback


async def cancel_task(task: asyncio.Task[Any] | None) -> None:
    if task is None or task.done():
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def create_run_completion_event(result: dict[str, Any]) -> CompleteEvent | ErrorEvent:
    if not result or not result.get("messages"):
        return ErrorEvent(message="Failed to generate hedge fund decisions")

    return CompleteEvent(
        data={
            "decisions": parse_hedge_fund_response(result.get("messages", [])[-1].content),
            "analyst_signals": result.get("data", {}).get("analyst_signals", {}),
            "current_prices": result.get("data", {}).get("current_prices", {}),
        }
    )


def create_backtest_completion_event(result: dict[str, Any] | None) -> CompleteEvent | ErrorEvent:
    if not result:
        return ErrorEvent(message="Failed to complete backtest")

    performance_metrics = BacktestPerformanceMetrics(**result["performance_metrics"])
    return CompleteEvent(
        data={
            "performance_metrics": performance_metrics.model_dump(),
            "final_portfolio": result["final_portfolio"],
            "total_days": len(result["results"]),
        }
    )


async def stream_hedge_fund_run(
    request: Request,
    request_data: HedgeFundRequest,
    graph: Any,
    portfolio: dict[str, Any],
    model_provider: str | None,
) -> AsyncIterator[str]:
    progress_queue: asyncio.Queue[ProgressUpdateEvent] = asyncio.Queue()
    run_task: asyncio.Task[Any] | None = None
    disconnect_task: asyncio.Task[bool] | None = None
    progress_handler = create_progress_handler(progress_queue)

    progress.register_handler(progress_handler)

    try:
        run_task = asyncio.create_task(
            run_graph_async(
                graph=graph,
                portfolio=portfolio,
                tickers=request_data.tickers,
                start_date=request_data.start_date,
                end_date=request_data.end_date,
                model_name=request_data.model_name,
                model_provider=model_provider,
                request=request_data,
            )
        )
        disconnect_task = asyncio.create_task(wait_for_disconnect(request))

        yield StartEvent().to_sse()

        while not run_task.done():
            if disconnect_task.done():
                print("Client disconnected, cancelling hedge fund execution")
                await cancel_task(run_task)
                return

            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                yield event.to_sse()
            except asyncio.TimeoutError:
                pass

        try:
            result = await run_task
        except asyncio.CancelledError:
            print("Task was cancelled")
            return

        yield create_run_completion_event(result).to_sse()

    except asyncio.CancelledError:
        print("Event generator cancelled")
        return
    finally:
        progress.unregister_handler(progress_handler)
        await cancel_task(run_task)
        await cancel_task(disconnect_task)


async def stream_backtest(
    request: Request,
    backtest_service: BacktestService,
) -> AsyncIterator[str]:
    progress_queue: asyncio.Queue[ProgressUpdateEvent] = asyncio.Queue()
    backtest_task: asyncio.Task[Any] | None = None
    disconnect_task: asyncio.Task[bool] | None = None
    progress_handler = create_progress_handler(progress_queue)
    progress_callback = create_backtest_progress_callback(progress_queue)

    progress.register_handler(progress_handler)

    try:
        backtest_task = asyncio.create_task(backtest_service.run_backtest_async(progress_callback=progress_callback))
        disconnect_task = asyncio.create_task(wait_for_disconnect(request))

        yield StartEvent().to_sse()

        while not backtest_task.done():
            if disconnect_task.done():
                print("Client disconnected, cancelling backtest execution")
                await cancel_task(backtest_task)
                return

            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                yield event.to_sse()
            except asyncio.TimeoutError:
                pass

        try:
            result = await backtest_task
        except asyncio.CancelledError:
            print("Backtest task was cancelled")
            return

        yield create_backtest_completion_event(result).to_sse()

    except asyncio.CancelledError:
        print("Backtest event generator cancelled")
        return
    finally:
        progress.unregister_handler(progress_handler)
        await cancel_task(backtest_task)
        await cancel_task(disconnect_task)
