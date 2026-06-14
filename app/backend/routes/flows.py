import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.models.schemas import (
    ErrorResponse,
    FlowCreateRequest,
    FlowResponse,
    FlowSummaryResponse,
    FlowUpdateRequest,
)
from app.backend.repositories.flow_repository import FlowRepository
from app.backend.routes._common import safe_route

router = APIRouter(prefix="/flows", tags=["flows"])
logger = logging.getLogger(__name__)


@router.post(
    "/",
    response_model=FlowResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def create_flow(request: FlowCreateRequest, db: Session = Depends(get_db)):
    """Create a new hedge fund flow"""
    repo = FlowRepository(db)
    flow = repo.create_flow(
        name=request.name,
        description=request.description,
        nodes=request.nodes,
        edges=request.edges,
        viewport=request.viewport,
        data=request.data,
        is_template=request.is_template,
        tags=request.tags
    )
    return FlowResponse.model_validate(flow)


@router.get(
    "/",
    response_model=List[FlowSummaryResponse],
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def get_flows(include_templates: bool = True, db: Session = Depends(get_db)):
    """Get all flows (summary view)"""
    repo = FlowRepository(db)
    flows = repo.get_all_flows(include_templates=include_templates)
    return [FlowSummaryResponse.model_validate(flow) for flow in flows]


@router.get(
    "/{flow_id}",
    response_model=FlowResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Flow not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def get_flow(flow_id: int, db: Session = Depends(get_db)):
    """Get a specific flow by ID"""
    repo = FlowRepository(db)
    flow = repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return FlowResponse.model_validate(flow)


@router.put(
    "/{flow_id}",
    response_model=FlowResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Flow not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def update_flow(flow_id: int, request: FlowUpdateRequest, db: Session = Depends(get_db)):
    """Update an existing flow"""
    repo = FlowRepository(db)
    flow = repo.update_flow(
        flow_id=flow_id,
        name=request.name,
        description=request.description,
        nodes=request.nodes,
        edges=request.edges,
        viewport=request.viewport,
        data=request.data,
        is_template=request.is_template,
        tags=request.tags
    )
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return FlowResponse.model_validate(flow)


@router.delete(
    "/{flow_id}",
    status_code=204,
    responses={
        204: {"description": "Flow deleted successfully"},
        404: {"model": ErrorResponse, "description": "Flow not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def delete_flow(flow_id: int, db: Session = Depends(get_db)):
    """Delete a flow"""
    repo = FlowRepository(db)
    success = repo.delete_flow(flow_id)
    if not success:
        raise HTTPException(status_code=404, detail="Flow not found")


@router.post(
    "/{flow_id}/duplicate",
    response_model=FlowResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Flow not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def duplicate_flow(flow_id: int, new_name: str = None, db: Session = Depends(get_db)):
    """Create a copy of an existing flow"""
    repo = FlowRepository(db)
    flow = repo.duplicate_flow(flow_id, new_name)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return FlowResponse.model_validate(flow)


@router.get(
    "/search/{name}",
    response_model=List[FlowSummaryResponse],
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def search_flows(name: str, db: Session = Depends(get_db)):
    """Search flows by name"""
    repo = FlowRepository(db)
    flows = repo.get_flows_by_name(name)
    return [FlowSummaryResponse.model_validate(flow) for flow in flows] 
