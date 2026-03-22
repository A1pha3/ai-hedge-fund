from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SelectedCandidate(BaseModel):
    symbol: str
    name: str = ""
    decision: str = "watchlist"
    score_b: float = 0.0
    score_c: float = 0.0
    score_final: float = 0.0
    rank_in_watchlist: int = 0
    layer_b_summary: dict[str, Any] = Field(default_factory=dict)
    layer_c_summary: dict[str, Any] = Field(default_factory=dict)
    execution_bridge: dict[str, Any] = Field(default_factory=dict)
    research_prompts: dict[str, list[str]] = Field(default_factory=dict)


class RejectedCandidate(BaseModel):
    symbol: str
    name: str = ""
    rejection_stage: str = "watchlist"
    score_b: float = 0.0
    score_c: float = 0.0
    score_final: float = 0.0
    rejection_reason_codes: list[str] = Field(default_factory=list)
    rejection_reason_text: str = ""


class SelectionSnapshot(BaseModel):
    artifact_version: str = "v1"
    run_id: str
    experiment_id: str | None = None
    trade_date: str
    market: str = "CN"
    decision_timestamp: str
    data_available_until: str
    pipeline_config_snapshot: dict[str, Any] = Field(default_factory=dict)
    universe_summary: dict[str, Any] = Field(default_factory=dict)
    selected: list[SelectedCandidate] = Field(default_factory=list)
    rejected: list[RejectedCandidate] = Field(default_factory=list)
    buy_orders: list[dict[str, Any]] = Field(default_factory=list)
    sell_orders: list[dict[str, Any]] = Field(default_factory=list)
    funnel_diagnostics: dict[str, Any] = Field(default_factory=dict)
    artifact_status: dict[str, Any] = Field(default_factory=dict)


class ResearchFeedbackRecord(BaseModel):
    feedback_version: str = "v1"
    artifact_version: str = "v1"
    run_id: str
    trade_date: str
    symbol: str
    review_scope: str = "watchlist"
    reviewer: str
    review_status: str = "draft"
    primary_tag: str
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.0)
    research_verdict: str
    notes: str = ""
    created_at: str


class SelectionArtifactWriteResult(BaseModel):
    artifact_version: str = "v1"
    snapshot_path: str | None = None
    review_path: str | None = None
    feedback_path: str | None = None
    write_status: str = "success"
    error_message: str | None = None