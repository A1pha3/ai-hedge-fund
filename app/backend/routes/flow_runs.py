import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.repositories.flow_run_repository import FlowRunRepository
from app.backend.repositories.flow_repository import FlowRepository
from app.backend.models.schemas import (
    FlowRunCreateRequest,
    FlowRunUpdateRequest,
    FlowRunResponse,
    FlowRunSummaryResponse,
    ErrorResponse,
    HedgeFundRequest,
)
from app.backend.routes._common import safe_route
from app.backend.routes.hedge_fund_streaming import (
    hydrate_api_keys,
    resolve_model_provider,
    stream_hedge_fund_run,
)
from app.backend.services.graph import create_graph
from app.backend.services.portfolio import create_portfolio
from src.utils.progress import progress

router = APIRouter(prefix="/flows/{flow_id}/runs", tags=["flow-runs"])
logger = logging.getLogger(__name__)


@router.post(
    "/",
    response_model=FlowRunResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Flow not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def create_flow_run(
    flow_id: int,
    request: FlowRunCreateRequest,
    db: Session = Depends(get_db)
):
    """Create a new flow run for the specified flow"""
    flow_repo = FlowRepository(db)
    flow = flow_repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    run_repo = FlowRunRepository(db)
    flow_run = run_repo.create_flow_run(
        flow_id=flow_id,
        request_data=request.request_data
    )
    return FlowRunResponse.model_validate(flow_run)


@router.get(
    "/",
    response_model=List[FlowRunSummaryResponse],
    responses={
        404: {"model": ErrorResponse, "description": "Flow not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def get_flow_runs(
    flow_id: int,
    limit: int = Query(50, ge=1, le=100, description="Maximum number of runs to return"),
    offset: int = Query(0, ge=0, description="Number of runs to skip"),
    db: Session = Depends(get_db)
):
    """Get all runs for the specified flow"""
    flow_repo = FlowRepository(db)
    flow = flow_repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    run_repo = FlowRunRepository(db)
    flow_runs = run_repo.get_flow_runs_by_flow_id(flow_id, limit=limit, offset=offset)
    return [FlowRunSummaryResponse.model_validate(run) for run in flow_runs]


@router.get(
    "/active",
    response_model=Optional[FlowRunResponse],
    responses={
        404: {"model": ErrorResponse, "description": "Flow not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def get_active_flow_run(flow_id: int, db: Session = Depends(get_db)):
    """Get the current active (IN_PROGRESS) run for the specified flow"""
    flow_repo = FlowRepository(db)
    flow = flow_repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    run_repo = FlowRunRepository(db)
    active_run = run_repo.get_active_flow_run(flow_id)
    return FlowRunResponse.model_validate(active_run) if active_run else None


@router.get(
    "/latest",
    response_model=Optional[FlowRunResponse],
    responses={
        404: {"model": ErrorResponse, "description": "Flow not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def get_latest_flow_run(flow_id: int, db: Session = Depends(get_db)):
    """Get the most recent run for the specified flow"""
    flow_repo = FlowRepository(db)
    flow = flow_repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    run_repo = FlowRunRepository(db)
    latest_run = run_repo.get_latest_flow_run(flow_id)
    return FlowRunResponse.model_validate(latest_run) if latest_run else None


@router.get(
    "/count",
    responses={
        200: {"description": "Flow run count"},
        404: {"model": ErrorResponse, "description": "Flow not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def get_flow_run_count(flow_id: int, db: Session = Depends(get_db)):
    """Get the total count of runs for the specified flow"""
    flow_repo = FlowRepository(db)
    flow = flow_repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    run_repo = FlowRunRepository(db)
    count = run_repo.get_flow_run_count(flow_id)

    return {"flow_id": flow_id, "total_runs": count}


@router.get(
    "/{run_id}",
    response_model=FlowRunResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Flow or run not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def get_flow_run(flow_id: int, run_id: int, db: Session = Depends(get_db)):
    """Get a specific flow run by ID"""
    flow_repo = FlowRepository(db)
    flow = flow_repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    run_repo = FlowRunRepository(db)
    flow_run = run_repo.get_flow_run_by_id(run_id)
    if not flow_run or flow_run.flow_id != flow_id:
        raise HTTPException(status_code=404, detail="Flow run not found")

    return FlowRunResponse.model_validate(flow_run)


@router.put(
    "/{run_id}",
    response_model=FlowRunResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Flow or run not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def update_flow_run(
    flow_id: int,
    run_id: int,
    request: FlowRunUpdateRequest,
    db: Session = Depends(get_db)
):
    """Update an existing flow run"""
    flow_repo = FlowRepository(db)
    flow = flow_repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    run_repo = FlowRunRepository(db)
    existing_run = run_repo.get_flow_run_by_id(run_id)
    if not existing_run or existing_run.flow_id != flow_id:
        raise HTTPException(status_code=404, detail="Flow run not found")

    flow_run = run_repo.update_flow_run(
        run_id=run_id,
        status=request.status,
        results=request.results,
        error_message=request.error_message
    )

    if not flow_run:
        raise HTTPException(status_code=404, detail="Flow run not found")

    return FlowRunResponse.model_validate(flow_run)


@router.delete(
    "/{run_id}",
    status_code=204,
    responses={
        204: {"description": "Flow run deleted successfully"},
        404: {"model": ErrorResponse, "description": "Flow or run not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def delete_flow_run(flow_id: int, run_id: int, db: Session = Depends(get_db)):
    """Delete a flow run"""
    flow_repo = FlowRepository(db)
    flow = flow_repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    run_repo = FlowRunRepository(db)
    existing_run = run_repo.get_flow_run_by_id(run_id)
    if not existing_run or existing_run.flow_id != flow_id:
        raise HTTPException(status_code=404, detail="Flow run not found")

    success = run_repo.delete_flow_run(run_id)
    if not success:
        raise HTTPException(status_code=404, detail="Flow run not found")


@router.delete(
    "/",
    status_code=204,
    responses={
        204: {"description": "All flow runs deleted successfully"},
        404: {"model": ErrorResponse, "description": "Flow not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def delete_all_flow_runs(flow_id: int, db: Session = Depends(get_db)):
    """Delete all runs for the specified flow"""
    flow_repo = FlowRepository(db)
    flow = flow_repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    run_repo = FlowRunRepository(db)
    run_repo.delete_flow_runs_by_flow_id(flow_id)


@router.post(
    "/{run_id}/rerun",
    response_model=FlowRunResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Flow or run not found"},
        400: {"model": ErrorResponse, "description": "No request data stored in historical run"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def rerun_flow_run(
    flow_id: int,
    run_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Re-run a historical flow run using its original parameters.

    Extracts the ``request_data`` stored in the specified flow run, creates a
    new flow run record under the same flow, and immediately kicks off the
    hedge-fund execution as an SSE stream.

    Returns a JSON payload with the *new* run metadata **and** a SSE stream
    body, so the frontend can both track the new run ID and stream progress
    events in a single response.
    """
    # --- Validate parent flow ---
    flow_repo = FlowRepository(db)
    flow = flow_repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    # --- Locate source run ---
    run_repo = FlowRunRepository(db)
    source_run = run_repo.get_flow_run_by_id(run_id)
    if not source_run or source_run.flow_id != flow_id:
        raise HTTPException(status_code=404, detail="Flow run not found")

    # --- Extract original parameters ---
    request_data_raw = source_run.request_data
    if not request_data_raw:
        raise HTTPException(
            status_code=400,
            detail="Cannot rerun: original request_data is not stored for this run",
        )

    # Build HedgeFundRequest from stored dict (backwards-compatible)
    rerun_request = HedgeFundRequest(**request_data_raw)

    # --- Hydrate API keys if not already present ---
    hydrate_api_keys(rerun_request, db)

    # --- Create new flow run record ---
    new_run = run_repo.create_flow_run(
        flow_id=flow_id,
        request_data=request_data_raw,
    )

    # --- Compile graph & start execution ---
    portfolio = create_portfolio(
        rerun_request.initial_cash,
        rerun_request.margin_requirement,
        rerun_request.tickers,
        rerun_request.portfolio_positions,
    )
    graph = create_graph(
        graph_nodes=rerun_request.graph_nodes,
        graph_edges=rerun_request.graph_edges,
    )
    compiled_graph = graph.compile()

    progress.update_status("system", None, "Preparing rerun")
    model_provider = resolve_model_provider(rerun_request.model_provider)

    # Return SSE stream (same as normal /hedge-fund/run)
    return StreamingResponse(
        stream_hedge_fund_run(request, rerun_request, compiled_graph, portfolio, model_provider),
        media_type="text/event-stream",
        headers={
            "X-Rerun-Run-Id": str(new_run.id),
            "X-Rerun-Run-Number": str(new_run.run_number),
        },
    )
