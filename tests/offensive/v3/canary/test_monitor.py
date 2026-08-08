"""Plan 06 Task 7 (RED): canary 监控、halt、drain、非自动晋升.

锁定约束:
1. monitor 只能 maintain / tighten / fence / drain — 永不扩大敞口, 永不产出
   5%/10% envelope.
2. drawdown 曲线/latch、stage loss latch、envelope 失效、陈旧 NAV、容量退化、
   未解决 ExitMandate → 各自触发对应 health 状态与 operator alert.
3. 所有 entry 依赖离线/halt 期间 exit 继续 (monitor 不阻断 exit).
4. 15% latch 后只有新 RiskEpochStarted + 更高 epoch PolicyActivation +
   RECOVERY envelope 可恢复; NAV/HWM 不重置.
5. 晋升非自动: monitor 永不签发 5%/10% — 只产出不可变评估包.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.screening.offensive.v3.canary.monitor import (
    MONITOR_CANNOT_PROMOTE,
    CanaryHealth,
    CanaryMonitor,
    CanarySnapshot,
    MonitorAction,
    MonitorError,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


def _snapshot(**overrides: object) -> CanarySnapshot:
    values: dict[str, object] = {
        "mode": "DAILY_BAR_PROXY",
        "nav_cents": 10_000_000,
        "high_water_mark_cents": 10_000_000,
        "stage_loss_latched": False,
        "drawdown_latched": False,
        "envelope_valid": True,
        "nav_observed_at": NOW,
        "capacity_degraded": False,
        "unresolved_exit_mandates": 0,
        "entry_dependencies_online": True,
        "observed_at": NOW,
    }
    values.update(overrides)
    return CanarySnapshot(**values)


def _monitor() -> CanaryMonitor:
    return CanaryMonitor(clock=lambda: NOW)


# ---------------------------------------------------------------------------
# 健康与降级
# ---------------------------------------------------------------------------


def test_healthy_snapshot_maintains() -> None:
    health = _monitor().assess(_snapshot())
    assert health.status == "healthy"
    assert health.action is MonitorAction.MAINTAIN
    assert health.alerts == ()


def test_stage_loss_latch_fences_entry() -> None:
    health = _monitor().assess(_snapshot(stage_loss_latched=True))
    assert health.action is MonitorAction.FENCE
    assert "stage_loss_latched" in health.alerts


def test_drawdown_latch_fences_entry() -> None:
    health = _monitor().assess(_snapshot(drawdown_latched=True))
    assert health.action is MonitorAction.FENCE
    assert "drawdown_latched" in health.alerts


def test_envelope_invalidation_drains() -> None:
    health = _monitor().assess(_snapshot(envelope_valid=False))
    assert health.action is MonitorAction.DRAIN
    assert "envelope_invalid" in health.alerts


def test_stale_nav_fences() -> None:
    health = _monitor().assess(
        _snapshot(nav_observed_at=NOW - timedelta(hours=26))
    )
    assert health.action is MonitorAction.FENCE
    assert "stale_nav" in health.alerts


def test_capacity_degradation_tightens() -> None:
    health = _monitor().assess(_snapshot(capacity_degraded=True))
    assert health.action is MonitorAction.TIGHTEN
    assert "capacity_degraded" in health.alerts


def test_unresolved_exit_mandate_alerts_but_does_not_block_exits() -> None:
    health = _monitor().assess(_snapshot(unresolved_exit_mandates=2))
    assert "unresolved_exit_mandates" in health.alerts
    assert health.exits_continue is True


def test_entry_dependencies_offline_never_blocks_exits() -> None:
    health = _monitor().assess(_snapshot(entry_dependencies_online=False))
    assert health.action is MonitorAction.FENCE
    assert health.exits_continue is True


# ---------------------------------------------------------------------------
# 非自动晋升
# ---------------------------------------------------------------------------


def test_monitor_never_produces_larger_envelope() -> None:
    monitor = _monitor()
    health = monitor.assess(_snapshot())
    assert health.recommended_cap_fraction <= Decimal("0.02")
    with pytest.raises(MonitorError) as excinfo:
        monitor.promote(_snapshot(), target_cap_fraction=Decimal("0.05"))
    assert excinfo.value.code == MONITOR_CANNOT_PROMOTE


def test_assessment_package_is_immutable() -> None:
    monitor = _monitor()
    package = monitor.assessment_package(_snapshot())
    assert package.snapshot_hash
    with pytest.raises(Exception):
        package.snapshot_hash = "0" * 64  # type: ignore[misc]


# ---------------------------------------------------------------------------
# latch 恢复
# ---------------------------------------------------------------------------


def test_latched_canary_requires_recovery_envelope_to_resume() -> None:
    monitor = _monitor()
    monitor.assess(_snapshot(stage_loss_latched=True))
    # 无 RECOVERY envelope: 仍 fence
    health = monitor.assess(_snapshot())
    assert health.action is MonitorAction.FENCE
    monitor.register_recovery(
        risk_epoch_started=True,
        policy_activation_epoch=10,
        recovery_envelope_present=True,
    )
    health = monitor.assess(_snapshot())
    assert health.action is MonitorAction.MAINTAIN


def test_recovery_requires_all_three_inputs() -> None:
    monitor = _monitor()
    monitor.assess(_snapshot(stage_loss_latched=True))
    for kwargs in (
        dict(risk_epoch_started=False, policy_activation_epoch=10, recovery_envelope_present=True),
        dict(risk_epoch_started=True, policy_activation_epoch=None, recovery_envelope_present=True),
        dict(risk_epoch_started=True, policy_activation_epoch=10, recovery_envelope_present=False),
    ):
        with pytest.raises(MonitorError):
            monitor.register_recovery(**kwargs)
