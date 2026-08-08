"""Plan 06 Task 6: mode-specific 2% canary 激活守卫.

`CanaryActivator.activate()` 只消费 Plan 02 stage-loss 状态与 Plan 03 签名的
policy/envelope/Trial/SAP/Stage candidates; 它 **永不签名、永不评估 edge**,
只核验 mode/cap/budget/trust/risk/NAV 前提并产出受限 receipt.

硬约束:
- 只允许 ``DAILY_BAR_PROXY`` 或 ``MANUAL_CONFIRMED``; ``BROKER_CONFIRMED``
  的首次 2% 等 Plan 07.
- ``EXPLORATION`` kind 一律拒绝 (本计划).
- gross cap 是同 mode portfolio aggregate, 恰好 ≤ 2%; 缺失固定整数 loss
  budget 拒绝.
- proxy/manual 激活不授予 broker authority (receipt.broker_authority 恒 False).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Literal

from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    ExactInteger,
    Sha256,
    UtcInstant,
)

MODE_MISMATCH = "MODE_MISMATCH"
EXPLORATION_FORBIDDEN = "EXPLORATION_FORBIDDEN"
GROSS_CAP_EXCEEDED = "GROSS_CAP_EXCEEDED"
MISSING_LOSS_BUDGET = "MISSING_LOSS_BUDGET"
ACTIVATION_REJECTED = "ACTIVATION_REJECTED"
UNRESOLVED_RISK = "UNRESOLVED_RISK"
STALE_NAV = "STALE_NAV"

_MAX_GROSS_CAP = Decimal("0.02")
_NAV_STALENESS_LIMIT_SECONDS = 24 * 3600
_ALLOWED_MODES = frozenset({"DAILY_BAR_PROXY", "MANUAL_CONFIRMED"})


class ActivationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class CanaryCandidate(CanonicalModel):
    """激活守卫消费的全部前提; 由调用方从已验证的候选装配."""

    candidate_id: str
    mode: str
    account_id: str
    policy_activation_hash: Sha256
    stage_manifest_hash: Sha256
    envelope_kind: Literal["EDGE", "EXPLORATION"]
    gross_cap_fraction: Decimal
    loss_budget_cents: ExactInteger | None
    as_observed_nav_cents: ExactInteger
    nav_observed_at: UtcInstant
    trust_active: bool
    unresolved_risk: bool
    inherited_exposure_cents: ExactInteger
    unattributed_exposure_cents: ExactInteger
    candidate_expires_at: UtcInstant


class CanaryReceipt(CanonicalModel):
    candidate_id: str
    mode: str
    account_id: str
    gross_cap_fraction: Decimal
    loss_budget_cents: ExactInteger
    activated_at: UtcInstant
    broker_authority: Literal[False] = False


class CanaryActivator:
    """2% canary 激活守卫; 无签名能力, 无 edge 评估."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    def activate(self, candidate: CanaryCandidate) -> CanaryReceipt:
        now = self._clock()
        if now.tzinfo is not timezone.utc:
            raise ActivationError(ACTIVATION_REJECTED, "clock must be UTC")
        if candidate.mode not in _ALLOWED_MODES:
            raise ActivationError(
                MODE_MISMATCH,
                f"mode {candidate.mode!r} cannot activate in this plan",
            )
        if candidate.envelope_kind == "EXPLORATION":
            raise ActivationError(
                EXPLORATION_FORBIDDEN,
                "EXPLORATION envelopes are rejected outside broker mode",
            )
        if candidate.gross_cap_fraction > _MAX_GROSS_CAP:
            raise ActivationError(
                GROSS_CAP_EXCEEDED,
                f"gross cap {candidate.gross_cap_fraction} exceeds 2%",
            )
        if candidate.loss_budget_cents is None:
            raise ActivationError(
                MISSING_LOSS_BUDGET, "fixed integer loss budget required"
            )
        if candidate.candidate_expires_at <= now:
            raise ActivationError(
                ACTIVATION_REJECTED, "candidate expired"
            )
        if not candidate.trust_active:
            raise ActivationError(
                ACTIVATION_REJECTED, "trust is not active"
            )
        if candidate.unresolved_risk:
            raise ActivationError(
                UNRESOLVED_RISK, "unresolved risk blocks activation"
            )
        nav_age = (now - candidate.nav_observed_at).total_seconds()
        if nav_age > _NAV_STALENESS_LIMIT_SECONDS:
            raise ActivationError(
                STALE_NAV,
                f"as-observed NAV is {nav_age:.0f}s old",
            )
        if candidate.inherited_exposure_cents or candidate.unattributed_exposure_cents:
            raise ActivationError(
                ACTIVATION_REJECTED,
                "inherited or unattributed exposure blocks activation",
            )
        return CanaryReceipt(
            candidate_id=candidate.candidate_id,
            mode=candidate.mode,
            account_id=candidate.account_id,
            gross_cap_fraction=candidate.gross_cap_fraction,
            loss_budget_cents=candidate.loss_budget_cents,
            activated_at=now,
        )
