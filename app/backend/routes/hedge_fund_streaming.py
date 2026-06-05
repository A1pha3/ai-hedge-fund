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


def _compute_edge_data_for_completion(
    analyst_signals: dict[str, Any],
    decisions: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Derive per-ticker edge / risk-budget metrics from analyst signals.

    The full research pipeline (``src/research/artifacts.py``) populates
    ``risk_budget_ratio`` / ``expected_edge`` / ``cvar_95`` from the
    execution plan, but the standard hedge-fund web run does not invoke
    that pipeline. We therefore compute a deterministic proxy here so
    the InvestmentReportDialog has a "30D Edge" card to render.

    Derivation (per ticker):
    - ``expected_30d_edge``: scale the net bullish-confidence of analyst
      signals (bullish*conf - bearish*conf) into a 0..+/-15% range.
    - ``cvar_95``: a conservative 8% tail risk placeholder, scaled by
      the number of analysts disagreeing with the consensus.
    - ``risk_budget_ratio``: position_limit utilization proxy from the
      ``max_shares`` available vs. decided shares.
    - ``edge_summary``: one-line Chinese explanation.

    The numbers are explicitly framed as "proxies" — they are
    deterministic, well-defined, and clearly *not* the full execution
    pipeline output. The InvestmentReportDialog falls back to a similar
    placeholder when this dict is empty.
    """
    if not analyst_signals or not decisions:
        return {}

    # Aggregate per-agent confidence by ticker and signal polarity.
    bullish_by_ticker: dict[str, list[float]] = {}
    bearish_by_ticker: dict[str, list[float]] = {}
    risk_manager_data: dict[str, dict[str, Any]] = {}
    for agent, ticker_signals in analyst_signals.items():
        if not isinstance(ticker_signals, dict):
            continue
        is_risk_manager = "risk_management" in str(agent or "")
        for ticker, payload in ticker_signals.items():
            if not isinstance(payload, dict):
                continue
            if is_risk_manager:
                risk_manager_data[str(ticker)] = dict(payload)
                continue
            sig = str(payload.get("signal") or "").lower()
            conf = payload.get("confidence")
            if not isinstance(conf, (int, float)):
                continue
            if sig == "bullish":
                bullish_by_ticker.setdefault(str(ticker), []).append(float(conf))
            elif sig == "bearish":
                bearish_by_ticker.setdefault(str(ticker), []).append(float(conf))

    edge_data: dict[str, dict[str, Any]] = {}
    for ticker, decision in decisions.items():
        if not isinstance(decision, dict):
            continue
        bull = bullish_by_ticker.get(ticker, [])
        bear = bearish_by_ticker.get(ticker, [])
        bull_score = sum(bull) / len(bull) if bull else 0.0
        bear_score = sum(bear) / len(bear) if bear else 0.0
        net = bull_score - bear_score  # in [-100, 100]
        # Map net into a -15%..+15% expected 30d edge.
        expected_edge = round(net * 0.15, 2)
        # Disagreement count drives CVaR (more disagreement = wider tail).
        disagreement = (len(bull) > 0 and len(bear) > 0)
        cvar_95 = round(0.05 + (0.10 if disagreement else 0.0) + (0.02 * min(len(bull) + len(bear), 10)), 4)

        # Risk budget ratio: try the risk manager's remaining_position_limit
        # vs. current_price*quantity as a proxy. If the risk manager did
        # not provide it, fall back to a heuristic from the action.
        risk_data = risk_manager_data.get(ticker, {})
        risk_budget_ratio: float | None = None
        try:
            remaining = float(risk_data.get("remaining_position_limit") or 0.0)
            price = float(risk_data.get("current_price") or 0.0)
            quantity = int(decision.get("quantity") or 0)
            if price > 0 and remaining > 0:
                consumed = quantity * price
                risk_budget_ratio = round(min(1.0, consumed / max(consumed + remaining, 1e-6)), 4)
        except (TypeError, ValueError):
            risk_budget_ratio = None
        if risk_budget_ratio is None:
            action = str(decision.get("action") or "").lower()
            confidence = float(decision.get("confidence") or 0.0)
            if action == "hold":
                risk_budget_ratio = 0.0
            else:
                # Use 50% base + scaled by confidence (0..1).
                risk_budget_ratio = round(min(1.0, 0.5 * (confidence / 100.0) + 0.2), 4)

        # One-line summary.
        action = str(decision.get("action") or "").lower()
        if expected_edge > 3:
            summary = f"30 天期望 +{expected_edge:.2f}% 处于前列 (action={action})，可重点关注。"
        elif expected_edge > 0:
            summary = f"30 天期望 +{expected_edge:.2f}% 偏正 (action={action})，仓位建议保守。"
        elif expected_edge < -3:
            summary = f"30 天期望 {expected_edge:.2f}% 显著为负 (action={action})，建议避免开仓。"
        elif expected_edge < 0:
            summary = f"30 天期望 {expected_edge:.2f}% 偏负 (action={action})，谨慎加仓。"
        else:
            summary = f"30 天期望收益接近 0 (action={action})，建议观望等待更明确信号。"

        edge_data[str(ticker)] = {
            "expected_30d_edge": expected_edge,
            "cvar_95": cvar_95,
            "risk_budget_ratio": risk_budget_ratio,
            "edge_summary": summary,
        }
    return edge_data


def create_run_completion_event(result: dict[str, Any]) -> CompleteEvent | ErrorEvent:
    if not result or not result.get("messages"):
        return ErrorEvent(message="Failed to generate hedge fund decisions")

    decisions = parse_hedge_fund_response(result.get("messages", [])[-1].content) or {}
    analyst_signals = result.get("data", {}).get("analyst_signals", {}) or {}
    return CompleteEvent(
        data={
            "decisions": decisions,
            "analyst_signals": analyst_signals,
            "current_prices": result.get("data", {}).get("current_prices", {}),
            "edge_data": _compute_edge_data_for_completion(analyst_signals, decisions),
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
