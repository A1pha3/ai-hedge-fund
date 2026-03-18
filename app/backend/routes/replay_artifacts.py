from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.backend.services.replay_artifact_service import ReplayArtifactService


router = APIRouter(prefix="/replay-artifacts", tags=["replay-artifacts"])


class ReplayArtifactListResponse(BaseModel):
    items: list[dict[str, Any]]


class ReplayArtifactDetailResponse(BaseModel):
    report: dict[str, Any]


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