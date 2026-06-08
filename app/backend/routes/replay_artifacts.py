from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.backend.auth.dependencies import get_current_user
from app.backend.models.user import User
from app.backend.services.replay_artifact_service import ReplayArtifactService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/replay-artifacts", tags=["replay-artifacts"])


class ReplayArtifactListResponse(BaseModel):
    items: list[dict[str, Any]]


class ReplayArtifactDetailResponse(BaseModel):
    report: dict[str, Any]


class ReplaySelectionArtifactResponse(BaseModel):
    selection_artifact: dict[str, Any]


class ReplayFeedbackAppendRequest(BaseModel):
    symbol: str
    primary_tag: str
    research_verdict: str
    tags: list[str] = Field(default_factory=list)
    review_status: str = "draft"
    review_scope: str | None = None
    confidence: float = 0.0
    notes: str = ""
    created_at: str | None = None


class ReplayFeedbackAppendResponse(BaseModel):
    feedback: dict[str, Any]


class ReplayFeedbackBatchAppendRequest(BaseModel):
    symbols: list[str]
    primary_tag: str
    research_verdict: str
    tags: list[str] = Field(default_factory=list)
    review_status: str = "draft"
    confidence: float = 0.0
    notes: str = ""
    created_at: str | None = None


class ReplayFeedbackBatchAppendResponse(BaseModel):
    feedback: dict[str, Any]


class ReplaySignalTradeComparisonResponse(BaseModel):
    pairs: list[dict[str, Any]]
    summary: dict[str, Any]


class ReplayFeedbackActivityResponse(BaseModel):
    activity: dict[str, Any]


class ReplayWorkflowQueueResponse(BaseModel):
    queue: dict[str, Any]


class ReplayWorkflowItemUpdateRequest(BaseModel):
    report_name: str
    trade_date: str
    symbol: str
    review_scope: str
    assignee: str | None = None
    workflow_status: str | None = None


class ReplayWorkflowItemUpdateResponse(BaseModel):
    item: dict[str, Any]


@router.get("/", response_model=ReplayArtifactListResponse)
async def list_replay_artifacts() -> ReplayArtifactListResponse:
    service = ReplayArtifactService()
    try:
        return ReplayArtifactListResponse(items=service.list_replays())
    except Exception as exc:
        logger.exception("Failed to list replay artifacts")
        raise HTTPException(status_code=500, detail="Failed to list replay artifacts") from exc


@router.get("/feedback-activity", response_model=ReplayFeedbackActivityResponse)
async def get_replay_feedback_activity(
    report_name: str | None = None,
    reviewer: str | None = None,
    limit: int = 20,
) -> ReplayFeedbackActivityResponse:
    service = ReplayArtifactService()
    try:
        return ReplayFeedbackActivityResponse(
            activity=service.get_feedback_activity(
                report_name=report_name,
                reviewer=reviewer,
                limit=limit,
            )
        )
    except Exception as exc:
        logger.exception("Failed to get replay feedback activity")
        raise HTTPException(status_code=500, detail="Failed to get replay feedback activity") from exc


@router.get("/workflow-queue", response_model=ReplayWorkflowQueueResponse)
async def get_replay_workflow_queue(
    assignee: str | None = None,
    workflow_status: str | None = None,
    report_name: str | None = None,
    limit: int = 50,
) -> ReplayWorkflowQueueResponse:
    service = ReplayArtifactService()
    try:
        return ReplayWorkflowQueueResponse(
            queue=service.list_workflow_queue(
                assignee=assignee,
                workflow_status=workflow_status,
                report_name=report_name,
                limit=limit,
            )
        )
    except Exception as exc:
        logger.exception("Failed to get replay workflow queue")
        raise HTTPException(status_code=500, detail="Failed to get replay workflow queue") from exc


@router.patch("/workflow-queue/item", response_model=ReplayWorkflowItemUpdateResponse)
async def update_replay_workflow_item(request: ReplayWorkflowItemUpdateRequest) -> ReplayWorkflowItemUpdateResponse:
    service = ReplayArtifactService()
    try:
        item = service.update_workflow_item(
            report_name=request.report_name,
            trade_date=request.trade_date,
            symbol=request.symbol,
            review_scope=request.review_scope,
            assignee=request.assignee,
            workflow_status=request.workflow_status,
        )
        return ReplayWorkflowItemUpdateResponse(item=item)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{report_name}", response_model=ReplayArtifactDetailResponse)
async def get_replay_artifact(report_name: str) -> ReplayArtifactDetailResponse:
    service = ReplayArtifactService()
    try:
        return ReplayArtifactDetailResponse(report=service.get_replay(report_name))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{report_name}/signal-trade-comparison", response_model=ReplaySignalTradeComparisonResponse)
async def get_signal_trade_comparison(
    report_name: str,
    time_window_days: int = 1,
) -> ReplaySignalTradeComparisonResponse:
    """Compare strategy signals against actual executed trades for a replay run.

    Returns per-signal match status (filled/partial/missed), price slippage,
    and fill delay statistics.
    """
    service = ReplayArtifactService()
    try:
        result = service.get_signal_trade_comparison(report_name, time_window_days=time_window_days)
        return ReplaySignalTradeComparisonResponse(pairs=result["pairs"], summary=result["summary"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{report_name}/selection-artifacts/{trade_date}", response_model=ReplaySelectionArtifactResponse)
async def get_replay_selection_artifact(report_name: str, trade_date: str) -> ReplaySelectionArtifactResponse:
    service = ReplayArtifactService()
    try:
        return ReplaySelectionArtifactResponse(selection_artifact=service.get_selection_artifact_day(report_name, trade_date))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{report_name}/selection-artifacts/{trade_date}/feedback", response_model=ReplayFeedbackAppendResponse)
async def append_replay_selection_feedback(
    report_name: str,
    trade_date: str,
    request: ReplayFeedbackAppendRequest,
    current_user: User = Depends(get_current_user),
) -> ReplayFeedbackAppendResponse:
    service = ReplayArtifactService()
    try:
        feedback = service.append_selection_artifact_feedback(
            report_name=report_name,
            trade_date=trade_date,
            reviewer=current_user.username,
            symbol=request.symbol,
            primary_tag=request.primary_tag,
            research_verdict=request.research_verdict,
            tags=request.tags,
            review_status=request.review_status,
            review_scope=request.review_scope,
            confidence=request.confidence,
            notes=request.notes,
            created_at=request.created_at,
        )
        return ReplayFeedbackAppendResponse(feedback=feedback)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{report_name}/selection-artifacts/{trade_date}/feedback/batch", response_model=ReplayFeedbackBatchAppendResponse)
async def append_replay_selection_feedback_batch(
    report_name: str,
    trade_date: str,
    request: ReplayFeedbackBatchAppendRequest,
    current_user: User = Depends(get_current_user),
) -> ReplayFeedbackBatchAppendResponse:
    service = ReplayArtifactService()
    try:
        feedback = service.append_selection_artifact_feedback_batch(
            report_name=report_name,
            trade_date=trade_date,
            reviewer=current_user.username,
            symbols=request.symbols,
            primary_tag=request.primary_tag,
            research_verdict=request.research_verdict,
            tags=request.tags,
            review_status=request.review_status,
            confidence=request.confidence,
            notes=request.notes,
            created_at=request.created_at,
        )
        return ReplayFeedbackBatchAppendResponse(feedback=feedback)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
