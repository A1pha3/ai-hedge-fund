"""Plan 06 canary 包: mode-specific 2% 激活、监控与排空."""

from src.screening.offensive.v3.canary.activation import (
    ACTIVATION_REJECTED,
    EXPLORATION_FORBIDDEN,
    GROSS_CAP_EXCEEDED,
    MISSING_LOSS_BUDGET,
    MODE_MISMATCH,
    STALE_NAV,
    UNRESOLVED_RISK,
    ActivationError,
    CanaryActivator,
    CanaryCandidate,
    CanaryReceipt,
)

__all__ = [
    "ACTIVATION_REJECTED",
    "EXPLORATION_FORBIDDEN",
    "GROSS_CAP_EXCEEDED",
    "MISSING_LOSS_BUDGET",
    "MODE_MISMATCH",
    "STALE_NAV",
    "UNRESOLVED_RISK",
    "ActivationError",
    "CanaryActivator",
    "CanaryCandidate",
    "CanaryReceipt",
]
