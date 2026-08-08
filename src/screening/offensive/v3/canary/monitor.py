"""Plan 06 Task 7: canary 监控、halt、drain、非自动晋升.

`CanaryMonitor` 只做四件事: maintain / tighten / fence / drain. 它 **永不**:

- 扩大敞口或产出 5%/10% envelope (``promote()`` 恒拒绝);
- 阻断 exit (所有 halt/outage 下 ``exits_continue`` 恒 True);
- 重置 NAV/HWM 或 stage-loss 记账 (Plan 02 事务拥有 consumption).

15% latch 恢复需要三件齐全: 新 ``RiskEpochStarted``、更高 epoch
``PolicyActivation``、``RECOVERY`` envelope — 且继承风险与既有 consumption
全部计入.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Callable

from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    ExactInteger,
    UtcInstant,
    content_hash,
)

MONITOR_CANNOT_PROMOTE = "MONITOR_CANNOT_PROMOTE"
RECOVERY_INCOMPLETE = "RECOVERY_INCOMPLETE"

_NAV_STALENESS_LIMIT_SECONDS = 24 * 3600
_MAX_CANARY_CAP = Decimal("0.02")


class MonitorError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class MonitorAction(StrEnum):
    MAINTAIN = "MAINTAIN"
    TIGHTEN = "TIGHTEN"
    FENCE = "FENCE"
    DRAIN = "DRAIN"


class CanarySnapshot(CanonicalModel):
    """monitor 消费的只读状态快照 (由调用方从 Plan 02/03/04 投影装配)."""

    mode: str
    nav_cents: ExactInteger
    high_water_mark_cents: ExactInteger
    stage_loss_latched: bool
    drawdown_latched: bool
    envelope_valid: bool
    nav_observed_at: UtcInstant
    capacity_degraded: bool
    unresolved_exit_mandates: ExactInteger
    entry_dependencies_online: bool
    observed_at: UtcInstant


class CanaryHealth(CanonicalModel):
    status: str
    action: MonitorAction
    alerts: tuple[str, ...]
    recommended_cap_fraction: Decimal
    exits_continue: bool = True


class AssessmentPackage(CanonicalModel):
    """不可变评估包: 供人工晋升评审; monitor 自身永不晋升."""

    snapshot_hash: str
    observed_at: UtcInstant


class _RecoveryState(CanonicalModel):
    risk_epoch_started: bool
    policy_activation_epoch: int | None
    recovery_envelope_present: bool


class CanaryMonitor:
    """2% canary 的健康监视器; 无写权威."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._latched = False
        self._recovery: _RecoveryState | None = None

    def assess(self, snapshot: CanarySnapshot) -> CanaryHealth:
        alerts: list[str] = []
        action = MonitorAction.MAINTAIN

        if not snapshot.envelope_valid:
            alerts.append("envelope_invalid")
            action = MonitorAction.DRAIN
        if snapshot.stage_loss_latched:
            alerts.append("stage_loss_latched")
            self._latched = True
            action = max(action, MonitorAction.FENCE, key=_severity)
        if snapshot.drawdown_latched:
            alerts.append("drawdown_latched")
            self._latched = True
            action = max(action, MonitorAction.FENCE, key=_severity)
        nav_age = (snapshot.observed_at - snapshot.nav_observed_at).total_seconds()
        if nav_age > _NAV_STALENESS_LIMIT_SECONDS:
            alerts.append("stale_nav")
            action = max(action, MonitorAction.FENCE, key=_severity)
        if not snapshot.entry_dependencies_online:
            alerts.append("entry_dependencies_offline")
            action = max(action, MonitorAction.FENCE, key=_severity)
        if snapshot.capacity_degraded:
            alerts.append("capacity_degraded")
            action = max(action, MonitorAction.TIGHTEN, key=_severity)
        if snapshot.unresolved_exit_mandates:
            alerts.append("unresolved_exit_mandates")

        if self._latched and action is MonitorAction.MAINTAIN:
            # latch 未解除前不得自行恢复
            action = MonitorAction.FENCE
            alerts.append("latch_active")

        status = "healthy" if action is MonitorAction.MAINTAIN else "degraded"
        return CanaryHealth(
            status=status,
            action=action,
            alerts=tuple(alerts),
            recommended_cap_fraction=_MAX_CANARY_CAP,
            exits_continue=True,
        )

    def register_recovery(
        self,
        *,
        risk_epoch_started: bool,
        policy_activation_epoch: int | None,
        recovery_envelope_present: bool,
    ) -> None:
        if not (
            risk_epoch_started
            and policy_activation_epoch is not None
            and recovery_envelope_present
        ):
            raise MonitorError(
                RECOVERY_INCOMPLETE,
                "recovery requires RiskEpochStarted + higher-epoch "
                "PolicyActivation + RECOVERY envelope",
            )
        self._recovery = _RecoveryState(
            risk_epoch_started=risk_epoch_started,
            policy_activation_epoch=policy_activation_epoch,
            recovery_envelope_present=recovery_envelope_present,
        )
        self._latched = False

    def assessment_package(self, snapshot: CanarySnapshot) -> AssessmentPackage:
        return AssessmentPackage(
            snapshot_hash=content_hash(snapshot.model_dump(mode="json")),
            observed_at=snapshot.observed_at,
        )

    def promote(
        self,
        snapshot: CanarySnapshot,
        *,
        target_cap_fraction: Decimal,
    ) -> None:
        raise MonitorError(
            MONITOR_CANNOT_PROMOTE,
            f"monitor cannot promote to {target_cap_fraction}; promotion "
            "requires a new same-mode StageManifest, evaluation units, "
            "primary evidence and a complete envelope",
        )


def _severity(action: MonitorAction) -> int:
    order = {
        MonitorAction.MAINTAIN: 0,
        MonitorAction.TIGHTEN: 1,
        MonitorAction.FENCE: 2,
        MonitorAction.DRAIN: 3,
    }
    return order[action]
