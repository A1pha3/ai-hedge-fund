"""Plan 06 Task 6 (RED): mode-specific 2% canary 激活守卫.

锁定约束:
1. 错误 mode/account/policy/stage/sample、过期 candidate、inactive trust、
   未解决风险、陈旧 as-observed NAV、继承/不可归因敞口 → 全部拒绝.
2. EXPLORATION kind 在非 broker mode 使用一律拒绝; 本计划只允许
   DAILY_BAR_PROXY 或有完整来源的 MANUAL_CONFIRMED.
3. gross cap 超过 2% 拒绝; 缺失固定整数 loss budget 拒绝.
4. Activator 永不签名、永不自行评估 edge; 只能消费已激活的同模式
   EDGE envelope 的完整 target policy.
5. proxy-to-broker 重用拒绝: 2% canary 不授予 broker authority.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.screening.offensive.v3.canary.activation import (
    ACTIVATION_REJECTED,
    ActivationError,
    CanaryActivator,
    CanaryCandidate,
    EXPLORATION_FORBIDDEN,
    GROSS_CAP_EXCEEDED,
    MISSING_LOSS_BUDGET,
    MODE_MISMATCH,
    STALE_NAV,
    UNRESOLVED_RISK,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


def _candidate(**overrides: object) -> CanaryCandidate:
    values: dict[str, object] = {
        "candidate_id": "cand-1",
        "mode": "DAILY_BAR_PROXY",
        "account_id": "paper-v3",
        "policy_activation_hash": "a" * 64,
        "stage_manifest_hash": "b" * 64,
        "envelope_kind": "EDGE",
        "gross_cap_fraction": Decimal("0.02"),
        "loss_budget_cents": 200_000,
        "as_observed_nav_cents": 10_000_000,
        "nav_observed_at": NOW,
        "trust_active": True,
        "unresolved_risk": False,
        "inherited_exposure_cents": 0,
        "unattributed_exposure_cents": 0,
        "candidate_expires_at": NOW + timedelta(minutes=30),
    }
    values.update(overrides)
    return CanaryCandidate(**values)


def _activator() -> CanaryActivator:
    return CanaryActivator(clock=lambda: NOW)


# ---------------------------------------------------------------------------
# 合法路径
# ---------------------------------------------------------------------------


def test_valid_proxy_candidate_activates() -> None:
    receipt = _activator().activate(_candidate())
    assert receipt.mode == "DAILY_BAR_PROXY"
    assert receipt.gross_cap_fraction == Decimal("0.02")
    assert receipt.broker_authority is False


def test_manual_confirmed_with_full_provenance_activates() -> None:
    receipt = _activator().activate(_candidate(mode="MANUAL_CONFIRMED"))
    assert receipt.mode == "MANUAL_CONFIRMED"
    assert receipt.broker_authority is False


# ---------------------------------------------------------------------------
# mode / kind
# ---------------------------------------------------------------------------


def test_exploration_kind_rejected_in_proxy_mode() -> None:
    with pytest.raises(ActivationError) as excinfo:
        _activator().activate(_candidate(envelope_kind="EXPLORATION"))
    assert excinfo.value.code == EXPLORATION_FORBIDDEN


def test_broker_mode_rejected_in_this_plan() -> None:
    with pytest.raises(ActivationError) as excinfo:
        _activator().activate(_candidate(mode="BROKER_CONFIRMED"))
    assert excinfo.value.code == MODE_MISMATCH


def test_proxy_evidence_cannot_confer_broker_authority() -> None:
    receipt = _activator().activate(_candidate())
    assert receipt.broker_authority is False
    with pytest.raises(ActivationError) as excinfo:
        _activator().activate(_candidate(mode="BROKER_CONFIRMED",
                                         envelope_kind="EDGE"))
    assert excinfo.value.code == MODE_MISMATCH


# ---------------------------------------------------------------------------
# cap / budget
# ---------------------------------------------------------------------------


def test_gross_cap_above_two_percent_rejected() -> None:
    with pytest.raises(ActivationError) as excinfo:
        _activator().activate(_candidate(gross_cap_fraction=Decimal("0.03")))
    assert excinfo.value.code == GROSS_CAP_EXCEEDED


def test_missing_loss_budget_rejected() -> None:
    with pytest.raises(ActivationError) as excinfo:
        _activator().activate(_candidate(loss_budget_cents=None))
    assert excinfo.value.code == MISSING_LOSS_BUDGET


# ---------------------------------------------------------------------------
# 状态前提
# ---------------------------------------------------------------------------


def test_expired_candidate_rejected() -> None:
    with pytest.raises(ActivationError) as excinfo:
        _activator().activate(
            _candidate(candidate_expires_at=NOW - timedelta(minutes=1))
        )
    assert excinfo.value.code == ACTIVATION_REJECTED


def test_inactive_trust_rejected() -> None:
    with pytest.raises(ActivationError) as excinfo:
        _activator().activate(_candidate(trust_active=False))
    assert excinfo.value.code == ACTIVATION_REJECTED


def test_unresolved_risk_rejected() -> None:
    with pytest.raises(ActivationError) as excinfo:
        _activator().activate(_candidate(unresolved_risk=True))
    assert excinfo.value.code == UNRESOLVED_RISK


def test_stale_nav_rejected() -> None:
    with pytest.raises(ActivationError) as excinfo:
        _activator().activate(
            _candidate(nav_observed_at=NOW - timedelta(hours=26))
        )
    assert excinfo.value.code == STALE_NAV


def test_inherited_or_unattributed_exposure_rejected() -> None:
    with pytest.raises(ActivationError) as excinfo:
        _activator().activate(_candidate(inherited_exposure_cents=1))
    assert excinfo.value.code == ACTIVATION_REJECTED
    with pytest.raises(ActivationError) as excinfo:
        _activator().activate(_candidate(unattributed_exposure_cents=1))
    assert excinfo.value.code == ACTIVATION_REJECTED
