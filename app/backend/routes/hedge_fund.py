from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.models.schemas import BacktestRequest, ErrorResponse, HedgeFundRequest
from app.backend.routes.hedge_fund_streaming import (
    hydrate_api_keys,
    resolve_model_provider,
    stream_backtest,
    stream_hedge_fund_run,
)
from app.backend.services.backtest_service import BacktestService
from app.backend.services.graph import create_graph
from app.backend.services.portfolio import create_portfolio
from src.utils.analysts import get_agents_list
from src.utils.progress import progress

router = APIRouter(prefix="/hedge-fund")


@router.post(
    path="/run",
    responses={
        200: {"description": "Successful response with streaming updates"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def run(request_data: HedgeFundRequest, request: Request, db: Session = Depends(get_db)):
    try:
        hydrate_api_keys(request_data, db)

        portfolio = create_portfolio(request_data.initial_cash, request_data.margin_requirement, request_data.tickers, request_data.portfolio_positions)
        graph = create_graph(graph_nodes=request_data.graph_nodes, graph_edges=request_data.graph_edges).compile()

        progress.update_status("system", None, "Preparing hedge fund run")
        model_provider = resolve_model_provider(request_data.model_provider)
        return StreamingResponse(stream_hedge_fund_run(request, request_data, graph, portfolio, model_provider), media_type="text/event-stream")

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while processing the request: {str(e)}")


@router.post(
    path="/backtest",
    responses={
        200: {"description": "Successful response with streaming backtest updates"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def backtest(request_data: BacktestRequest, request: Request, db: Session = Depends(get_db)):
    """Run a continuous backtest over a time period with streaming updates."""
    try:
        hydrate_api_keys(request_data, db)

        model_provider = resolve_model_provider(request_data.model_provider)

        portfolio = create_portfolio(
            request_data.initial_capital,
            request_data.margin_requirement,
            request_data.tickers,
            request_data.portfolio_positions,
        )

        graph = create_graph(graph_nodes=request_data.graph_nodes, graph_edges=request_data.graph_edges)
        graph = graph.compile()

        backtest_service = BacktestService(
            graph=graph,
            portfolio=portfolio,
            tickers=request_data.tickers,
            start_date=request_data.start_date,
            end_date=request_data.end_date,
            initial_capital=request_data.initial_capital,
            model_name=request_data.model_name,
            model_provider=model_provider,
            request=request_data,
        )

        return StreamingResponse(stream_backtest(request, backtest_service), media_type="text/event-stream")

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while processing the backtest request: {str(e)}")


@router.get(
    path="/agents",
    responses={
        200: {"description": "List of available agents"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_agents():
    """Get the list of available agents."""
    try:
        return {"agents": get_agents_list()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve agents: {str(e)}")
