from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, Field, model_validator

from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetEvaluationResult


RESEARCH_FEEDBACK_LABEL_VERSION = "v1"
RESEARCH_FEEDBACK_ALLOWED_TAGS = (
    "high_quality_selection",
    "thesis_clear",
    "crowded_trade_risk",
    "weak_edge",
    "threshold_false_negative",
    "event_noise_suspected",
)
RESEARCH_FEEDBACK_ALLOWED_REVIEW_STATUS = (
    "draft",
    "final",
    "adjudicated",
)


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
    target_context: dict[str, Any] = Field(default_factory=dict)
    target_decisions: dict[str, TargetEvaluationResult] = Field(default_factory=dict)


class RejectedCandidate(BaseModel):
    symbol: str
    name: str = ""
    rejection_stage: str = "watchlist"
    score_b: float = 0.0
    score_c: float = 0.0
    score_final: float = 0.0
    rejection_reason_codes: list[str] = Field(default_factory=list)
    rejection_reason_text: str = ""
    target_context: dict[str, Any] = Field(default_factory=dict)
    target_decisions: dict[str, TargetEvaluationResult] = Field(default_factory=dict)


class ResearchTargetView(BaseModel):
    selected_symbols: list[str] = Field(default_factory=list)
    near_miss_symbols: list[str] = Field(default_factory=list)
    rejected_symbols: list[str] = Field(default_factory=list)
    blocker_counts: dict[str, int] = Field(default_factory=dict)


class ShortTradeTargetView(BaseModel):
    selected_symbols: list[str] = Field(default_factory=list)
    near_miss_symbols: list[str] = Field(default_factory=list)
    rejected_symbols: list[str] = Field(default_factory=list)
    blocked_symbols: list[str] = Field(default_factory=list)
    blocker_counts: dict[str, int] = Field(default_factory=dict)


class DualTargetDeltaView(BaseModel):
    delta_counts: dict[str, int] = Field(default_factory=dict)
    representative_cases: list[dict[str, Any]] = Field(default_factory=list)
    dominant_delta_reasons: list[str] = Field(default_factory=list)


class SelectionSnapshot(BaseModel):
    artifact_version: str = "v1"
    run_id: str
    experiment_id: str | None = None
    trade_date: str
    market: str = "CN"
    decision_timestamp: str
    data_available_until: str
    target_mode: str = "research_only"
    pipeline_config_snapshot: dict[str, Any] = Field(default_factory=dict)
    universe_summary: dict[str, Any] = Field(default_factory=dict)
    selected: list[SelectedCandidate] = Field(default_factory=list)
    rejected: list[RejectedCandidate] = Field(default_factory=list)
    selection_targets: dict[str, DualTargetEvaluation] = Field(default_factory=dict)
    target_summary: DualTargetSummary = Field(default_factory=DualTargetSummary)
    research_view: ResearchTargetView = Field(default_factory=ResearchTargetView)
    short_trade_view: ShortTradeTargetView = Field(default_factory=ShortTradeTargetView)
    dual_target_delta: DualTargetDeltaView = Field(default_factory=DualTargetDeltaView)
    buy_orders: list[dict[str, Any]] = Field(default_factory=list)
    sell_orders: list[dict[str, Any]] = Field(default_factory=list)
    funnel_diagnostics: dict[str, Any] = Field(default_factory=dict)
    artifact_status: dict[str, Any] = Field(default_factory=dict)


class ResearchFeedbackRecord(BaseModel):
    feedback_version: str = "v1"
    artifact_version: str = "v1"
    label_version: str = RESEARCH_FEEDBACK_LABEL_VERSION
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

    @model_validator(mode="after")
    def _normalize_tags(self) -> "ResearchFeedbackRecord":
        normalized_tags = []
        seen_tags: set[str] = set()
        for tag in [self.primary_tag, *self.tags]:
            normalized_tag = str(tag or "").strip()
            if not normalized_tag:
                continue
            if normalized_tag not in RESEARCH_FEEDBACK_ALLOWED_TAGS:
                raise ValueError(f"Unsupported research feedback tag: {normalized_tag}")
            if normalized_tag not in seen_tags:
                normalized_tags.append(normalized_tag)
                seen_tags.add(normalized_tag)
        if self.review_status not in RESEARCH_FEEDBACK_ALLOWED_REVIEW_STATUS:
            raise ValueError(f"Unsupported review_status: {self.review_status}")
        if self.label_version != RESEARCH_FEEDBACK_LABEL_VERSION:
            raise ValueError(f"Unsupported label_version: {self.label_version}")
        self.tags = normalized_tags
        return self


class ResearchFeedbackSummary(BaseModel):
    label_version: str = RESEARCH_FEEDBACK_LABEL_VERSION
    feedback_count: int = 0
    final_feedback_count: int = 0
    symbols: list[str] = Field(default_factory=list)
    reviewers: list[str] = Field(default_factory=list)
    primary_tag_counts: dict[str, int] = Field(default_factory=dict)
    tag_counts: dict[str, int] = Field(default_factory=dict)
    review_status_counts: dict[str, int] = Field(default_factory=dict)
    verdict_counts: dict[str, int] = Field(default_factory=dict)
    latest_created_at: str | None = None

    @classmethod
    def from_records(cls, records: list[ResearchFeedbackRecord]) -> "ResearchFeedbackSummary":
        primary_tag_counts = Counter(record.primary_tag for record in records)
        tag_counts = Counter(tag for record in records for tag in record.tags)
        review_status_counts = Counter(record.review_status for record in records)
        verdict_counts = Counter(record.research_verdict for record in records)
        latest_created_at = max((record.created_at for record in records), default=None)
        return cls(
            feedback_count=len(records),
            final_feedback_count=sum(1 for record in records if record.review_status == "final"),
            symbols=sorted({record.symbol for record in records}),
            reviewers=sorted({record.reviewer for record in records}),
            primary_tag_counts=dict(primary_tag_counts),
            tag_counts=dict(tag_counts),
            review_status_counts=dict(review_status_counts),
            verdict_counts=dict(verdict_counts),
            latest_created_at=latest_created_at,
        )


class ResearchFeedbackDirectorySummary(BaseModel):
    label_version: str = RESEARCH_FEEDBACK_LABEL_VERSION
    artifact_root: str
    feedback_file_count: int = 0
    trade_date_count: int = 0
    overall: ResearchFeedbackSummary = Field(default_factory=ResearchFeedbackSummary)
    by_trade_date: dict[str, ResearchFeedbackSummary] = Field(default_factory=dict)


class SelectionArtifactWriteResult(BaseModel):
    artifact_version: str = "v1"
    snapshot_path: str | None = None
    review_path: str | None = None
    feedback_path: str | None = None
    write_status: str = "success"
    error_message: str | None = None