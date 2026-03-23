from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.backend.auth.dependencies import get_current_user
from app.backend.models.user import User
from app.backend.services.replay_artifact_service import ReplayArtifactService


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


@router.get("/", response_model=ReplayArtifactListResponse)
async def list_replay_artifacts() -> ReplayArtifactListResponse:
    service = ReplayArtifactService()
    return ReplayArtifactListResponse(items=service.list_replays())


@router.get("/{report_name}", response_model=ReplayArtifactDetailResponse)
async def get_replay_artifact(report_name: str) -> ReplayArtifactDetailResponse:
    service = ReplayArtifactService()
    try:
        return ReplayArtifactDetailResponse(report=service.get_replay(report_name))
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