from __future__ import annotations
import pytest

from src.execution.models import ExecutionPlan
from src.execution.signal_decay import (
    P7GapOverlayConfig,
    _apply_gap_overlay,
    _build_warn_adjusted_order,
    _should_cancel_gap_open,
    apply_signal_decay,
)
from src.portfolio.models import PositionPlan


def _make_plan(*, shares: int = 100, amount: float = 10_000.0, risk_budget_ratio: float = 1.0) -> ExecutionPlan:
    return ExecutionPlan(
        date="20240301",
        buy_orders=[
            PositionPlan(
                ticker="000001",
                shares=shares,
                amount=amount,
                score_final=0.5,
                execution_ratio=1.0,
                risk_budget_ratio=risk_budget_ratio,
            )
        ],
        risk_alerts=[],
        risk_metrics={},
    )


def test_apply_signal_decay_p7_gap_overlay_enforce_halt(monkeypatch):
    monkeypatch.setenv("BTST_0422_P7_GAP_OVERLAY_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P7_GAP_WARN_THRESHOLD", "0.005")
    monkeypatch.setenv("BTST_0422_P7_GAP_HALT_THRESHOLD", "0.01")

    plan = _make_plan()
    out = apply_signal_decay(plan, "20240304", open_gap_pct={"000001": -0.02})

    assert out is plan
    assert plan.buy_orders == []
    assert "cancel_buy_gap_overlay_halt:000001" in plan.risk_alerts
    payload = plan.risk_metrics.get("btst_gap_overlay_p7_enforcement")
    assert payload is not None
    assert payload["halted_count"] == 1
    assert payload["warned_count"] == 0


def test_apply_signal_decay_p7_gap_overlay_enforce_warn_reduces_size(monkeypatch):
    monkeypatch.setenv("BTST_0422_P7_GAP_OVERLAY_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P7_GAP_WARN_THRESHOLD", "0.005")
    monkeypatch.setenv("BTST_0422_P7_GAP_HALT_THRESHOLD", "0.01")

    plan = _make_plan(shares=100, amount=20_000.0)
    apply_signal_decay(plan, "20240304", open_gap_pct={"000001": -0.006})

    assert len(plan.buy_orders) == 1
    assert plan.buy_orders[0].shares == 50
    assert plan.buy_orders[0].amount == 10_000.0
    assert "reduce_buy_gap_overlay_warn:000001" in plan.risk_alerts

    payload = plan.risk_metrics.get("btst_gap_overlay_p7_enforcement")
    assert payload is not None
    assert payload["warned_count"] == 1
    assert payload["halted_count"] == 0


def test_apply_signal_decay_p7_gap_overlay_enforce_warn_size_discount_env(monkeypatch):
    monkeypatch.setenv("BTST_0422_P7_GAP_OVERLAY_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P7_GAP_WARN_THRESHOLD", "0.005")
    monkeypatch.setenv("BTST_0422_P7_GAP_HALT_THRESHOLD", "0.01")
    monkeypatch.setenv("BTST_0422_P7_GAP_WARN_SIZE_DISCOUNT", "0.25")

    plan = _make_plan(shares=100, amount=20_000.0)
    apply_signal_decay(plan, "20240304", open_gap_pct={"000001": -0.006})

    assert len(plan.buy_orders) == 1
    assert plan.buy_orders[0].shares == 25
    assert plan.buy_orders[0].amount == 5_000.0

    payload = plan.risk_metrics.get("btst_gap_overlay_p7_enforcement")
    assert payload is not None
    assert payload["warn_size_discount"] == 0.25


def test_apply_signal_decay_p7_gap_overlay_report_halt_logs_diagnostics_without_changing_orders(monkeypatch):
    monkeypatch.setenv("BTST_0422_P7_GAP_OVERLAY_MODE", "report")
    monkeypatch.setenv("BTST_0422_P7_GAP_WARN_THRESHOLD", "0.005")
    monkeypatch.setenv("BTST_0422_P7_GAP_HALT_THRESHOLD", "0.01")

    plan = _make_plan(shares=100, amount=20_000.0)
    apply_signal_decay(plan, "20240304", open_gap_pct={"000001": -0.02})

    assert len(plan.buy_orders) == 1
    assert plan.buy_orders[0].shares == 100
    assert "cancel_buy_gap_overlay_halt:000001" not in plan.risk_alerts

    payload = plan.risk_metrics.get("btst_gap_overlay_p7_report")
    assert payload is not None
    assert payload["mode"] == "report"
    assert payload["halted_count"] == 1
    assert payload["warned_count"] == 0
    assert payload["halted_tickers"] == ["000001"]

    assert plan.risk_metrics.get("btst_gap_overlay_p7_enforcement") is None
    funnel = plan.risk_metrics.get("funnel_diagnostics") or {}
    assert funnel.get("btst_gap_overlay_p7_report") is not None


def test_apply_signal_decay_p7_gap_overlay_report_warn_logs_diagnostics_without_changing_orders(monkeypatch):
    monkeypatch.setenv("BTST_0422_P7_GAP_OVERLAY_MODE", "report")
    monkeypatch.setenv("BTST_0422_P7_GAP_WARN_THRESHOLD", "0.005")
    monkeypatch.setenv("BTST_0422_P7_GAP_HALT_THRESHOLD", "0.01")

    plan = _make_plan(shares=100, amount=20_000.0)
    apply_signal_decay(plan, "20240304", open_gap_pct={"000001": -0.006})

    assert len(plan.buy_orders) == 1
    assert plan.buy_orders[0].shares == 100

    payload = plan.risk_metrics.get("btst_gap_overlay_p7_report")
    assert payload is not None
    assert payload["warned_count"] == 1
    assert payload["halted_count"] == 0
    assert payload["warned_tickers"] == ["000001"]


def test_apply_signal_decay_p7_gap_overlay_off_no_change(monkeypatch):
    monkeypatch.setenv("BTST_0422_P7_GAP_OVERLAY_MODE", "off")

    plan = _make_plan(shares=100, amount=20_000.0)
    apply_signal_decay(plan, "20240304", open_gap_pct={"000001": -0.02})

    assert len(plan.buy_orders) == 1
    assert plan.buy_orders[0].shares == 100
    assert plan.risk_metrics == {}


def test_apply_signal_decay_p7_warn_branch_preserves_zero_risk_budget_r20_17_regression(monkeypatch):
    """R20.17 (Bug C) regression: `risk_budget_ratio=0.0` 不能被 `or 1.0` 静默覆盖为满仓。

    0.0 是合法"无风险预算"语义, warn-branch 折扣后应保持 0 (而不是 0.85*1.0=0.85)。
    """
    monkeypatch.setenv("BTST_0422_P7_GAP_OVERLAY_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P7_GAP_WARN_THRESHOLD", "0.005")
    monkeypatch.setenv("BTST_0422_P7_GAP_HALT_THRESHOLD", "0.01")

    # 显式 0% 风险预算, 这是合法值 (例如 0% = 完全风控关闭, 不应买入)
    plan = _make_plan(shares=100, amount=20_000.0, risk_budget_ratio=0.0)
    apply_signal_decay(plan, "20240304", open_gap_pct={"000001": -0.006})  # 触发 warn

    assert len(plan.buy_orders) == 1
    # 关键: 折扣后应保持 0.0, 而非被 0.85 覆盖为 ~0.85
    assert plan.buy_orders[0].risk_budget_ratio == 0.0, (
        f"risk_budget_ratio=0.0 折扣后应保持 0, 实际 {plan.buy_orders[0].risk_budget_ratio} "
        f"(R20.17 Bug C 回归: or 1.0)"
    )


def test_apply_signal_decay_p7_warn_branch_default_risk_budget_1_0(monkeypatch):
    """对照组: missing risk_budget_ratio 应走默认 1.0 (满仓), 折扣后 = 0.5。"""
    monkeypatch.setenv("BTST_0422_P7_GAP_OVERLAY_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P7_GAP_WARN_THRESHOLD", "0.005")
    monkeypatch.setenv("BTST_0422_P7_GAP_HALT_THRESHOLD", "0.01")

    # 默认 risk_budget_ratio=1.0 (满仓, _make_plan 默认值)
    plan = _make_plan(shares=100, amount=20_000.0)
    apply_signal_decay(plan, "20240304", open_gap_pct={"000001": -0.006})

    assert len(plan.buy_orders) == 1
    # 默认 P7 warn discount = 0.5; 1.0 * 0.5 = 0.5
    assert plan.buy_orders[0].risk_budget_ratio == pytest.approx(0.5), (
        f"默认 risk_budget_ratio=1.0 折扣后应 = 0.5, 实际 {plan.buy_orders[0].risk_budget_ratio}"
    )


def test_apply_signal_decay_zero_atr_does_not_cancel_normal_gap_up(monkeypatch):
    """R20.26-B BETA-007: gap-up cancellation threshold ``gap > 1.5 * atr``
    must require a *positive, finite* ATR. With ``atr=0.0`` (missing ATR
    data — e.g. a fresh IPO, or a corrupted feed) the previous code computed
    ``1.5 * 0.0 = 0.0`` and ANY positive open gap (even a normal 0.1% gap)
    cancelled the buy order. That gate is meant to detect abnormal gap-ups
    relative to volatility, so a zero / unknown ATR must NOT turn the gate
    into a "cancel everything that gaps up" tripwire."""
    monkeypatch.setenv("BTST_0422_P7_GAP_OVERLAY_MODE", "off")  # disable P7 overlay

    plan = _make_plan(shares=100, amount=20_000.0)
    apply_signal_decay(
        plan,
        "20240304",
        open_gap_pct={"000001": 0.001},  # tiny normal gap up (0.1%)
        atr_values={"000001": 0.0},      # invalid / unknown ATR
    )

    # Order must survive — a tiny gap with unknown ATR is not an abnormal gap.
    assert len(plan.buy_orders) == 1, (
        f"ATR=0 + 0.1% gap should NOT cancel the buy order, got alerts: {plan.risk_alerts}"
    )
    assert not any("cancel_buy_gap_open" in alert for alert in plan.risk_alerts)


def test_should_cancel_gap_open_requires_positive_atr() -> None:
    assert _should_cancel_gap_open(atr_value=0.0, gap_value=0.02) is False
    assert _should_cancel_gap_open(atr_value=None, gap_value=0.02) is False
    assert _should_cancel_gap_open(atr_value=0.01, gap_value=0.02) is True


def test_build_warn_adjusted_order_preserves_zero_risk_budget_ratio() -> None:
    order = _make_plan(shares=100, amount=20_000.0, risk_budget_ratio=0.0).buy_orders[0]

    adjusted = _build_warn_adjusted_order(order, warn_size_discount=0.5)

    assert adjusted is not None
    assert adjusted.shares == 50
    assert adjusted.amount == 10_000.0
    assert adjusted.risk_budget_ratio == 0.0


def test_build_warn_adjusted_order_returns_none_when_discount_zeroes_position() -> None:
    order = _make_plan(shares=1, amount=1.0).buy_orders[0]

    adjusted = _build_warn_adjusted_order(order, warn_size_discount=0.1)

    assert adjusted is None


def test_apply_gap_overlay_report_warn_keeps_order_and_records_report_action() -> None:
    order = _make_plan(shares=100, amount=20_000.0).buy_orders[0]
    overlay = P7GapOverlayConfig(
        mode="report",
        warn_threshold=0.005,
        halt_threshold=0.01,
        warn_size_discount=0.5,
    )

    action, adjusted = _apply_gap_overlay(order=order, gap_pct=-0.006, overlay=overlay)

    assert action == "report_warn"
    assert adjusted is None


def test_apply_gap_overlay_warn_zeroed_returns_halt_style_action() -> None:
    order = _make_plan(shares=1, amount=1.0).buy_orders[0]
    overlay = P7GapOverlayConfig(
        mode="enforce",
        warn_threshold=0.005,
        halt_threshold=0.01,
        warn_size_discount=0.1,
    )

    action, adjusted = _apply_gap_overlay(order=order, gap_pct=-0.006, overlay=overlay)

    assert action == "warn_zeroed"
    assert adjusted is None
