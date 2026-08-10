"""Plan 05 Task 8: ledger-derived reporting — 操作员每日状态投影子系统。

导出 ``DailyOperatorProjection`` (含子视图 dataclass)、``ReportingService``
(只读组合器) 与 ``render_json`` / ``render_text`` (共享同一 projection 的两个
renderer)。详见 ``projection`` / ``service`` / ``render`` 模块 docstring。
"""

from __future__ import annotations

from src.screening.offensive.v3.reporting.projection import (
    AccountCapitalView,
    DailyOperatorProjection,
    EXECUTABLE_ENTRY_STATUSES,
    FILL_PROVENANCE_BROKER,
    FILL_PROVENANCE_MANUAL,
    FILL_PROVENANCE_PROXY,
    PendingExitView,
    PerformanceView,
    PlannedEntryView,
    ShadowDecisionSummary,
)
from src.screening.offensive.v3.reporting.render import render_json, render_text
from src.screening.offensive.v3.reporting.service import (
    CapitalReaderPort,
    ReportingService,
    ShadowDecisionReader,
)
from src.screening.offensive.v3.reporting.shadow_store import InMemoryShadowStore
from src.screening.offensive.v3.reporting.trial_projection import (
    AssessmentProjectionError,
    EligibilityGates,
    HEADLINE_INACTIVE_CANDIDATE,
    HEADLINE_NOT_ELIGIBLE,
    TrialAssessmentProjection,
    rebuild_trial_assessment,
    render_trial_assessment,
)

__all__ = [
    "AccountCapitalView",
    "AssessmentProjectionError",
    "CapitalReaderPort",
    "DailyOperatorProjection",
    "EXECUTABLE_ENTRY_STATUSES",
    "EligibilityGates",
    "FILL_PROVENANCE_BROKER",
    "FILL_PROVENANCE_MANUAL",
    "FILL_PROVENANCE_PROXY",
    "HEADLINE_INACTIVE_CANDIDATE",
    "HEADLINE_NOT_ELIGIBLE",
    "InMemoryShadowStore",
    "PendingExitView",
    "PerformanceView",
    "PlannedEntryView",
    "ReportingService",
    "ShadowDecisionReader",
    "ShadowDecisionSummary",
    "TrialAssessmentProjection",
    "rebuild_trial_assessment",
    "render_json",
    "render_text",
    "render_trial_assessment",
]
