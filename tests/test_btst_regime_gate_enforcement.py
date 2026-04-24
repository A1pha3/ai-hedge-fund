"""Tests for P2 regime gate hard enforcement.

P2 adds a separate flag BTST_0422_P2_REGIME_GATE_MODE (off|enforce).
When enforce:
- halt days: buy_orders cleared, enforcement reason recorded.
- shadow_only days: buy_orders cleared, enforcement reason recorded.
- normal_trade / aggressive_trade days: buy_orders kept intact.
When off: behaviour identical to baseline (P2 is a no-op).
P1 shadow path must remain unaffected when only P1 flag is on.
"""
from __future__ import annotations

import pytest

from src.execution.daily_pipeline import (
    _attach_btst_regime_gate_shadow,
    _enforce_btst_regime_gate_p2,
)
from src.execution.models import ExecutionPlan
from src.portfolio.models import PositionPlan
from src.screening.models import MarketState


def _make_plan(gate_level: str, *, with_buy_orders: bool = True) -> ExecutionPlan:
    """Build a minimal ExecutionPlan with market state that resolves to the given gate."""
    # gate mappings (from classify_btst_regime_gate):
    #   risk_off / crisis -> halt
    #   conservative profile (non risk_off) -> shadow_only
    #   breadth_ratio >= 0.60 -> aggressive_trade
    #   otherwise -> normal_trade
    breadth_map = {
        "halt": 0.39,
        "shadow_only": 0.44,
        "normal_trade": 0.52,
        "aggressive_trade": 0.67,
    }
    regime_gate_level_map = {
        "halt": "risk_off",
        "shadow_only": "normal",
        "normal_trade": "normal",
        "aggressive_trade": "normal",
    }
    regime_flip_risk_map = {
        "halt": 0.65,
        "shadow_only": 0.40,
        "normal_trade": 0.20,
        "aggressive_trade": 0.08,
    }
    style_dispersion_map = {
        "halt": 0.55,
        "shadow_only": 0.58,
        "normal_trade": 0.22,
        "aggressive_trade": 0.15,
    }
    buy_orders = (
        [PositionPlan(ticker="000001", shares=100, amount=10000.0)]
        if with_buy_orders
        else []
    )
    return ExecutionPlan(
        date="20260410",
        market_state=MarketState(
            breadth_ratio=breadth_map[gate_level],
            daily_return=-0.002,
            style_dispersion=style_dispersion_map[gate_level],
            regime_flip_risk=regime_flip_risk_map[gate_level],
            regime_gate_level=regime_gate_level_map[gate_level],
        ),
        buy_orders=buy_orders,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"buy_order_count": len(buy_orders)}},
    )


# ---------------------------------------------------------------------------
# Failing-first: these will fail before _enforce_btst_regime_gate_p2 exists
# ---------------------------------------------------------------------------


class TestP2EnforceHaltBlocksBuyOrders:
    def test_halt_clears_buy_orders_when_enforce(self, monkeypatch):
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        plan = _make_plan("halt")
        assert plan.buy_orders, "precondition: plan has buy orders before enforcement"

        updated = _enforce_btst_regime_gate_p2(plan)

        assert updated.buy_orders == [], "halt gate must clear buy_orders when P2 enforce is on"

    def test_halt_records_enforcement_reason(self, monkeypatch):
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        plan = _make_plan("halt")

        updated = _enforce_btst_regime_gate_p2(plan)

        enforcement = updated.risk_metrics.get("btst_regime_gate_enforcement", {})
        assert enforcement.get("enforced") is True
        assert enforcement.get("gate") == "halt"
        assert enforcement.get("mode") == "enforce"
        assert enforcement.get("buy_orders_cleared") is True

    def test_halt_is_noop_when_p2_off(self, monkeypatch):
        monkeypatch.delenv("BTST_0422_P2_REGIME_GATE_MODE", raising=False)
        plan = _make_plan("halt")
        original_orders = list(plan.buy_orders)

        updated = _enforce_btst_regime_gate_p2(plan)

        assert [o.ticker for o in updated.buy_orders] == [o.ticker for o in original_orders]
        assert "btst_regime_gate_enforcement" not in updated.risk_metrics


class TestP2EnforceShadowOnlyBlocksBuyOrders:
    def test_shadow_only_clears_buy_orders_when_enforce(self, monkeypatch):
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        plan = _make_plan("shadow_only")
        assert plan.buy_orders, "precondition: plan has buy orders before enforcement"

        updated = _enforce_btst_regime_gate_p2(plan)

        assert updated.buy_orders == [], "shadow_only gate must clear buy_orders when P2 enforce is on"

    def test_shadow_only_records_enforcement_reason(self, monkeypatch):
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        plan = _make_plan("shadow_only")

        updated = _enforce_btst_regime_gate_p2(plan)

        enforcement = updated.risk_metrics.get("btst_regime_gate_enforcement", {})
        assert enforcement.get("enforced") is True
        assert enforcement.get("gate") == "shadow_only"
        assert enforcement.get("buy_orders_cleared") is True

    def test_shadow_only_is_noop_when_p2_off(self, monkeypatch):
        monkeypatch.delenv("BTST_0422_P2_REGIME_GATE_MODE", raising=False)
        plan = _make_plan("shadow_only")
        original_orders = list(plan.buy_orders)

        updated = _enforce_btst_regime_gate_p2(plan)

        assert [o.ticker for o in updated.buy_orders] == [o.ticker for o in original_orders]


class TestP2EnforceAllowsStrongAndNormalDays:
    def test_normal_trade_keeps_buy_orders_when_enforce(self, monkeypatch):
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        plan = _make_plan("normal_trade")
        original_tickers = [o.ticker for o in plan.buy_orders]

        updated = _enforce_btst_regime_gate_p2(plan)

        assert [o.ticker for o in updated.buy_orders] == original_tickers, \
            "normal_trade gate must not block buy_orders"

    def test_aggressive_trade_keeps_buy_orders_when_enforce(self, monkeypatch):
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        plan = _make_plan("aggressive_trade")
        original_tickers = [o.ticker for o in plan.buy_orders]

        updated = _enforce_btst_regime_gate_p2(plan)

        assert [o.ticker for o in updated.buy_orders] == original_tickers, \
            "aggressive_trade gate must not block buy_orders"


class TestP1ShadowUnaffectedByP2:
    """P1 shadow behavior must remain intact regardless of P2 flag."""

    def test_p1_shadow_still_records_payload_when_p2_off(self, monkeypatch):
        monkeypatch.setenv("BTST_0422_P1_REGIME_GATE_MODE", "shadow")
        monkeypatch.delenv("BTST_0422_P2_REGIME_GATE_MODE", raising=False)
        plan = _make_plan("halt")

        updated_p1 = _attach_btst_regime_gate_shadow(plan)

        assert updated_p1.risk_metrics.get("btst_regime_gate", {}).get("mode") == "shadow"
        # buy_orders untouched because P2 is off
        assert updated_p1.buy_orders != [], "P1 shadow must NOT clear buy_orders"

    def test_p1_shadow_still_records_payload_when_p2_enforce(self, monkeypatch):
        monkeypatch.setenv("BTST_0422_P1_REGIME_GATE_MODE", "shadow")
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        plan = _make_plan("halt")

        # P1 shadow — only records, does not clear
        after_p1 = _attach_btst_regime_gate_shadow(plan)
        assert after_p1.risk_metrics.get("btst_regime_gate", {}).get("mode") == "shadow"
        assert after_p1.buy_orders != [], "P1 shadow alone must NOT clear buy_orders"

        # P2 enforce — now actually clears
        after_p2 = _enforce_btst_regime_gate_p2(after_p1)
        assert after_p2.buy_orders == []
        enforcement = after_p2.risk_metrics.get("btst_regime_gate_enforcement", {})
        assert enforcement.get("enforced") is True


class TestP2ReuseP1GatePayload:
    """If P1 has already computed the gate, P2 should reuse it rather than re-classify."""

    def test_p2_reuses_existing_gate_in_risk_metrics(self, monkeypatch):
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        # Pre-populate P1 gate payload so P2 can reuse it
        plan = _make_plan("halt", with_buy_orders=True)
        plan.risk_metrics["btst_regime_gate"] = {
            "gate": "halt",
            "mode": "shadow",
            "profile_hint": "conservative",
            "reason_codes": ["regime_gate_level_risk_off"],
        }

        updated = _enforce_btst_regime_gate_p2(plan)

        assert updated.buy_orders == []
        enforcement = updated.risk_metrics.get("btst_regime_gate_enforcement", {})
        assert enforcement.get("gate") == "halt"

    def test_p2_classifies_gate_independently_when_p1_not_present(self, monkeypatch):
        """P2 enforce should work even if P1 shadow flag is off (no pre-existing gate)."""
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        monkeypatch.delenv("BTST_0422_P1_REGIME_GATE_MODE", raising=False)
        plan = _make_plan("halt", with_buy_orders=True)
        # No btst_regime_gate in risk_metrics — P2 must classify independently
        assert "btst_regime_gate" not in plan.risk_metrics

        updated = _enforce_btst_regime_gate_p2(plan)

        assert updated.buy_orders == []
        enforcement = updated.risk_metrics.get("btst_regime_gate_enforcement", {})
        assert enforcement.get("gate") == "halt"


class TestP2RecordsEnforcementInFunnelDiagnostics:
    """Enforcement reason must be visible in funnel_diagnostics for artifact tracing."""

    def test_enforcement_written_to_funnel_diagnostics(self, monkeypatch):
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        plan = _make_plan("halt")

        updated = _enforce_btst_regime_gate_p2(plan)

        funnel = updated.risk_metrics.get("funnel_diagnostics", {})
        enforcement = funnel.get("btst_regime_gate_enforcement", {})
        assert enforcement.get("enforced") is True
        assert enforcement.get("gate") == "halt"


# ---------------------------------------------------------------------------
# Gap 1: Router-level semantics — p2_execution_blocked in selection_targets
# ---------------------------------------------------------------------------

class TestP2RouterLevelExecutionBlocked:
    """P2 enforcement must mark selection_targets as p2_execution_blocked, not only clear buy_orders."""

    def test_halt_marks_selection_targets_p2_execution_blocked(self, monkeypatch):
        from src.targets.router import apply_p2_regime_gate_enforcement_to_selection_targets
        from src.targets.models import DualTargetEvaluation, TargetEvaluationResult
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        evaluation = DualTargetEvaluation(
            ticker="000001", trade_date="20260410",
            research=TargetEvaluationResult(target_type="research", decision="selected"),
        )
        targets = {"000001": evaluation}
        apply_p2_regime_gate_enforcement_to_selection_targets(targets, gate="halt")
        assert targets["000001"].p2_execution_blocked is True
        assert targets["000001"].p2_execution_block_reason is not None

    def test_shadow_only_marks_selection_targets_p2_execution_blocked(self, monkeypatch):
        from src.targets.router import apply_p2_regime_gate_enforcement_to_selection_targets
        from src.targets.models import DualTargetEvaluation, TargetEvaluationResult
        evaluation = DualTargetEvaluation(
            ticker="000001", trade_date="20260410",
            research=TargetEvaluationResult(target_type="research", decision="selected"),
        )
        targets = {"000001": evaluation}
        apply_p2_regime_gate_enforcement_to_selection_targets(targets, gate="shadow_only")
        assert targets["000001"].p2_execution_blocked is True

    def test_normal_trade_does_not_mark_p2_execution_blocked(self, monkeypatch):
        from src.targets.router import apply_p2_regime_gate_enforcement_to_selection_targets
        from src.targets.models import DualTargetEvaluation, TargetEvaluationResult
        evaluation = DualTargetEvaluation(
            ticker="000001", trade_date="20260410",
            research=TargetEvaluationResult(target_type="research", decision="selected"),
        )
        targets = {"000001": evaluation}
        apply_p2_regime_gate_enforcement_to_selection_targets(targets, gate="normal_trade")
        assert targets["000001"].p2_execution_blocked is False

    def test_research_visibility_preserved_after_execution_blocked(self, monkeypatch):
        """Research decision stays 'selected' — only p2_execution_blocked flag changes."""
        from src.targets.router import apply_p2_regime_gate_enforcement_to_selection_targets
        from src.targets.models import DualTargetEvaluation, TargetEvaluationResult
        evaluation = DualTargetEvaluation(
            ticker="000001", trade_date="20260410",
            research=TargetEvaluationResult(target_type="research", decision="selected"),
        )
        targets = {"000001": evaluation}
        apply_p2_regime_gate_enforcement_to_selection_targets(targets, gate="halt")
        assert targets["000001"].research.decision == "selected", "research visibility must remain"
        assert targets["000001"].p2_execution_blocked is True, "execution must be flagged blocked"

    def test_dual_target_summary_counts_p2_execution_blocked(self, monkeypatch):
        """DualTargetSummary must expose p2_execution_blocked_count after enforcement."""
        from src.targets.router import apply_p2_regime_gate_enforcement_to_selection_targets, summarize_selection_targets
        from src.targets.models import DualTargetEvaluation, TargetEvaluationResult
        e1 = DualTargetEvaluation(
            ticker="000001", trade_date="20260410",
            research=TargetEvaluationResult(target_type="research", decision="selected"),
        )
        e2 = DualTargetEvaluation(
            ticker="000002", trade_date="20260410",
            research=TargetEvaluationResult(target_type="research", decision="near_miss"),
        )
        targets = {"000001": e1, "000002": e2}
        apply_p2_regime_gate_enforcement_to_selection_targets(targets, gate="halt")
        summary = summarize_selection_targets(selection_targets=targets, target_mode="research_only")
        assert summary.p2_execution_blocked_count == 1, "only selected items should be blocked"

    def test_plan_selection_targets_updated_after_p2_enforce(self, monkeypatch):
        """_enforce_btst_regime_gate_p2 must update plan.selection_targets when present."""
        from src.execution.daily_pipeline import _enforce_btst_regime_gate_p2
        from src.targets.models import DualTargetEvaluation, TargetEvaluationResult
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        plan = _make_plan("halt")
        plan.selection_targets = {
            "000001": DualTargetEvaluation(
                ticker="000001", trade_date="20260410",
                research=TargetEvaluationResult(target_type="research", decision="selected"),
            )
        }
        updated = _enforce_btst_regime_gate_p2(plan)
        st = updated.selection_targets or {}
        assert st.get("000001") is not None
        assert st["000001"].p2_execution_blocked is True, "selection_target must be marked execution_blocked"


# ---------------------------------------------------------------------------
# Gap 2: Artifact/config propagation — pipeline_config_snapshot records P2 flag
# ---------------------------------------------------------------------------

class TestP2ArtifactConfigPropagation:
    """pipeline_config_snapshot must record both P1 and P2 regime gate flags."""

    def test_pipeline_config_snapshot_includes_p2_flag(self, monkeypatch):
        import os
        from src.research.artifacts import _build_pipeline_config_snapshot
        from src.execution.models import ExecutionPlan
        monkeypatch.setenv("BTST_0422_P1_REGIME_GATE_MODE", "shadow")
        monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
        plan = ExecutionPlan(date="20260410", portfolio_snapshot={})
        snapshot = _build_pipeline_config_snapshot(plan, None, None)
        flags = snapshot.get("btst_0422_flags", {})
        assert "p2_regime_gate_mode" in flags, "p2_regime_gate_mode must appear in btst_0422_flags"
        assert flags["p2_regime_gate_mode"] == "enforce"

    def test_pipeline_config_snapshot_p2_flag_is_off_by_default(self, monkeypatch):
        from src.research.artifacts import _build_pipeline_config_snapshot
        from src.execution.models import ExecutionPlan
        monkeypatch.delenv("BTST_0422_P2_REGIME_GATE_MODE", raising=False)
        plan = ExecutionPlan(date="20260410", portfolio_snapshot={})
        snapshot = _build_pipeline_config_snapshot(plan, None, None)
        flags = snapshot.get("btst_0422_flags", {})
        assert flags.get("p2_regime_gate_mode") == "off"


# ---------------------------------------------------------------------------
# Single-source-of-truth: _P2_BLOCKED_GATES must come from one place only
# ---------------------------------------------------------------------------


class TestP2BlockedGatesSingleSource:
    """_P2_BLOCKED_GATES must be defined once and imported (not duplicated)."""

    def test_router_and_pipeline_use_identical_blocked_gates(self):
        """Both modules must expose the same set of blocked gates."""
        from src.targets.router import _P2_BLOCKED_GATES as router_gates
        from src.execution.daily_pipeline import _P2_BLOCKED_GATES as pipeline_gates  # type: ignore[attr-defined]
        assert router_gates == pipeline_gates, (
            "_P2_BLOCKED_GATES must have identical values in router and daily_pipeline"
        )

    def test_pipeline_imports_gates_from_router(self):
        """daily_pipeline._P2_BLOCKED_GATES must be the exact same object as router._P2_BLOCKED_GATES.

        This proves there is a single source of truth — daily_pipeline imports from router
        rather than re-defining the frozenset.
        """
        from src.targets.router import _P2_BLOCKED_GATES as router_gates
        from src.execution.daily_pipeline import _P2_BLOCKED_GATES as pipeline_gates  # type: ignore[attr-defined]
        assert pipeline_gates is router_gates, (
            "daily_pipeline._P2_BLOCKED_GATES must be the same object as router._P2_BLOCKED_GATES "
            "(imported, not redefined)"
        )

    def test_blocked_gates_contains_halt_and_shadow_only(self):
        from src.targets.router import _P2_BLOCKED_GATES
        assert "halt" in _P2_BLOCKED_GATES
        assert "shadow_only" in _P2_BLOCKED_GATES
