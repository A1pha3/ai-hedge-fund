"""BTST operator summary — versioned, immutable, derived view of a single BTST run.

P0C (2026-06-04): establishes the canonical schema for ``operator_summary.json``.

**Design principles:**
- Only references canonical artifacts; never replaces them.
- Never contains realized outcome fields.
- ``complete`` / ``degraded`` / ``failed`` always produce valid JSON.
- Atomic write via temp-file-and-rename.
- Same inputs → identical output (idempotent).
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SummaryStatus(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    FAILED = "failed"


class DecisionPhase(str, Enum):
    POST_CLOSE_PLAN = "post_close_plan"
    T_PLUS_1_OPEN_CONFIRMATION = "t_plus_1_open_confirmation"
    POST_TRADE_EVALUATION = "post_trade_evaluation"


class BoardDateAlignmentStatus(str, Enum):
    EXACT = "exact"
    STALE_FALLBACK = "stale_fallback"
    UNAVAILABLE = "unavailable"


class ArtifactFreshnessStatus(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class PointInTimeStatus(str, Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"
    UNKNOWN = "unknown"


class ActionabilityStatus(str, Enum):
    ELIGIBLE_FOR_CONFIRMATION = "eligible_for_confirmation"
    RESEARCH_ONLY = "research_only"
    UNAVAILABLE = "unavailable"
    EXECUTABLE = "executable"
    CONFIRMATION_FAILED = "confirmation_failed"
    NOT_APPLICABLE = "not_applicable"


class ComparisonScope(str, Enum):
    DOC_BUNDLE_RENDERING = "doc_bundle_rendering"


class IncrementalEvidenceStatus(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    PARTIAL = "partial"


# ---------------------------------------------------------------------------
# Forbidden outcome fields — must never appear in a summary
# ---------------------------------------------------------------------------

_OUTCOME_FIELDS = frozenset({
    "realized_return",
    "realized_outcome",
    "t_plus_1_outcome",
    "actual_return",
    "pnl",
    "exit_price",
})


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class OptimizationResolution(BaseModel):
    status: str = "unoptimized"
    manifest_ref: str | None = None
    fallback_reason: str | None = None


class MarketSection(BaseModel):
    regime_gate_level: str | None = None
    market_gate: str | None = None
    gate_enforced: bool | None = None
    buy_orders_cleared: bool | None = None


class ExecutionSection(BaseModel):
    report_mode: str | None = None
    formal_selected_tickers: list[str] = Field(default_factory=list)
    orderable_tickers: list[str] = Field(default_factory=list)
    confirmation_only_tickers: list[str] = Field(default_factory=list)
    first_invalidate_if: str | None = None


class EarlyRunnerSection(BaseModel):
    board_date_alignment_status: BoardDateAlignmentStatus | None = None
    artifact_freshness_status: ArtifactFreshnessStatus | None = None
    point_in_time_status: PointInTimeStatus | None = None
    source_generated_at: str | None = None
    source_gate_action: str | None = None
    source_deployment_mode: str | None = None
    actionability_status: ActionabilityStatus | None = None
    intersection_count: int = 0
    only_early_runner_count: int = 0
    second_entry_count: int = 0


class IncrementalEvidenceSection(BaseModel):
    status: IncrementalEvidenceStatus = IncrementalEvidenceStatus.INSUFFICIENT
    sample_count: int = 0
    coverage: float | None = None
    confidence: float | None = None
    evidence_ref: str | None = None


class ProfileCompareSection(BaseModel):
    comparison_scope: ComparisonScope = ComparisonScope.DOC_BUNDLE_RENDERING
    effective_decision_diff: bool = False
    recommended_profile: str | None = None
    reason: str | None = None


class ArtifactEntry(BaseModel):
    artifact_type: str
    path: str
    generated_at: str | None = None
    data_as_of: str | None = None
    validation_status: str = "unknown"


class ArtifactsSection(BaseModel):
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)


class BridgeSection(BaseModel):
    updated_files: list[str] = Field(default_factory=list)
    unchanged_files: list[str] = Field(default_factory=list)
    missing_targets: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)


class RunStep(BaseModel):
    step_name: str
    status: str  # "success" | "skipped" | "failed" | "reused"
    duration_seconds: float | None = None
    source_path: str | None = None
    failure_reason: str | None = None


class ManualIntervention(BaseModel):
    required: bool = False
    reasons: list[str] = Field(default_factory=list)


class SourceConflict(BaseModel):
    field: str
    artifact_a: str
    value_a: Any = None
    artifact_b: str
    value_b: Any = None
    resolution: str = "unresolved"


# ---------------------------------------------------------------------------
# Top-level model
# ---------------------------------------------------------------------------

class OperatorSummary(BaseModel):
    """Top-level schema for ``operator_summary.json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    summary_status: SummaryStatus = SummaryStatus.COMPLETE
    generated_at: str
    decision_id: str
    decision_phase: DecisionPhase = DecisionPhase.POST_CLOSE_PLAN
    signal_date: str
    next_trade_date: str | None = None
    decision_as_of: str
    data_as_of: str
    baseline_commit: str | None = None

    optimization_resolution: OptimizationResolution = Field(default_factory=OptimizationResolution)
    market: MarketSection = Field(default_factory=MarketSection)
    execution: ExecutionSection = Field(default_factory=ExecutionSection)
    early_runner: EarlyRunnerSection = Field(default_factory=EarlyRunnerSection)
    incremental_evidence: IncrementalEvidenceSection = Field(default_factory=IncrementalEvidenceSection)
    profile_compare: ProfileCompareSection = Field(default_factory=ProfileCompareSection)
    artifacts: ArtifactsSection = Field(default_factory=ArtifactsSection)
    bridge: BridgeSection = Field(default_factory=BridgeSection)
    source_artifacts: list[ArtifactEntry] = Field(default_factory=list)
    source_conflicts: list[SourceConflict] = Field(default_factory=list)
    run_steps: list[RunStep] = Field(default_factory=list)
    manual_intervention: ManualIntervention = Field(default_factory=ManualIntervention)

    # legacy alias for consumers that still read manual_patch_required
    @property
    def manual_patch_required(self) -> bool:
        return self.manual_intervention.required

    @field_validator("schema_version")
    @classmethod
    def _must_be_version_1(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"Only schema_version=1 is supported, got {v}")
        return v

    @model_validator(mode="after")
    def _no_outcome_fields(self) -> "OperatorSummary":
        """P0C rule 3: summary must not contain realized outcome data."""
        raw = self.model_dump()
        found = [k for k in _OUTCOME_FIELDS if raw.get(k) is not None]
        if found:
            raise ValueError(
                f"operator_summary must not contain outcome fields: {found}"
            )
        return self


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------

def build_decision_id(*, signal_date: str, decision_phase: str, version: int = 1) -> str:
    """Construct a stable ``decision_id`` string."""
    phase_short = decision_phase.replace("_", "-")
    return f"btst-{signal_date}-{phase_short}-v{version}"


def build_operator_summary(
    *,
    signal_date: str,
    decision_phase: str = "post_close_plan",
    next_trade_date: str | None = None,
    decision_as_of: str | None = None,
    data_as_of: str | None = None,
    baseline_commit: str | None = None,
    summary_status: str = "complete",
    market: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    early_runner: dict[str, Any] | None = None,
    incremental_evidence: dict[str, Any] | None = None,
    profile_compare: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    bridge: dict[str, Any] | None = None,
    source_artifacts: list[dict[str, Any]] | None = None,
    source_conflicts: list[dict[str, Any]] | None = None,
    run_steps: list[dict[str, Any]] | None = None,
    manual_intervention: dict[str, Any] | None = None,
    optimization_resolution: dict[str, Any] | None = None,
    decision_id: str | None = None,
    version: int = 1,
) -> OperatorSummary:
    """Build and validate an ``OperatorSummary`` from raw dicts.

    All sub-sections are optional and default to their empty/zero values.
    The returned model is fully validated — any forbidden field raises.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    resolved_decision_id = decision_id or build_decision_id(
        signal_date=signal_date, decision_phase=decision_phase, version=version,
    )
    resolved_decision_as_of = decision_as_of or now
    resolved_data_as_of = data_as_of or now

    return OperatorSummary(
        generated_at=now,
        decision_id=resolved_decision_id,
        decision_phase=decision_phase,
        signal_date=signal_date,
        next_trade_date=next_trade_date,
        decision_as_of=resolved_decision_as_of,
        data_as_of=resolved_data_as_of,
        baseline_commit=baseline_commit,
        summary_status=summary_status,
        market=MarketSection(**(market or {})),
        execution=ExecutionSection(**(execution or {})),
        early_runner=EarlyRunnerSection(**(early_runner or {})),
        incremental_evidence=IncrementalEvidenceSection(**(incremental_evidence or {})),
        profile_compare=ProfileCompareSection(**(profile_compare or {})),
        artifacts=ArtifactsSection(**(artifacts or {})),
        bridge=BridgeSection(**(bridge or {})),
        source_artifacts=[ArtifactEntry(**a) for a in (source_artifacts or [])],
        source_conflicts=[SourceConflict(**c) for c in (source_conflicts or [])],
        run_steps=[RunStep(**s) for s in (run_steps or [])],
        manual_intervention=ManualIntervention(**(manual_intervention or {})),
        optimization_resolution=OptimizationResolution(**(optimization_resolution or {})),
    )


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def write_operator_summary(summary: OperatorSummary, path: Path) -> Path:
    """Write an ``OperatorSummary`` to disk using atomic temp-file-and-rename.

    Returns the final path of the written file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        summary.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".operator_summary_",
        suffix=".tmp",
    )
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        # Atomic rename (POSIX) — on Windows this may fail if target exists.
        Path(tmp_path).rename(path)
    except BaseException:
        # Clean up the temp file on any failure.
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def read_operator_summary(path: Path) -> OperatorSummary:
    """Read and validate an ``OperatorSummary`` from disk."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return OperatorSummary(**raw)
