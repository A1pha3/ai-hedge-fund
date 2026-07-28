"""Public risk-state enums shared by capital, decision, and execution contracts."""

from enum import StrEnum


class RiskSnapshotFreshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class RiskSnapshotCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class RiskLatchState(StrEnum):
    CLEAR = "CLEAR"
    RISK_HALTED = "RISK_HALTED"


class StageLossLatchState(StrEnum):
    CLEAR = "CLEAR"
    STAGE_LOSS_HALTED = "STAGE_LOSS_HALTED"


class ReconciliationLatchState(StrEnum):
    CLEAR = "CLEAR"
    RECONCILIATION_HALT = "RECONCILIATION_HALT"


__all__ = [
    "ReconciliationLatchState",
    "RiskLatchState",
    "RiskSnapshotCompleteness",
    "RiskSnapshotFreshness",
    "StageLossLatchState",
]
