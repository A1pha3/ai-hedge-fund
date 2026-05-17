"""Test for Task 1: win-rate-first precision tightening."""
from __future__ import annotations

import pytest

from src.execution.daily_pipeline import _enforce_btst_execution_contract_p5
from src.execution.models import ExecutionPlan
from src.portfolio.models import PositionPlan
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetEvaluationResult


def _build_test_plan(
    *,
    decision: str = "selected",
    prior_quality_label: str | None = None,
    gate: str = "normal_trade",
) -> ExecutionPlan:
    """Build test plan matching existing pattern from test_btst_execution_eligibility_contract.py"""
    evaluation = DualTargetEvaluation(
        ticker="300724",
        trade_date="20260422",
        candidate_source="layer_c_watchlist",
        p3_prior_quality_label=prior_quality_label,
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision=decision,
            score_target=0.81,
        ),
    )
    return ExecutionPlan(
        date="20260422",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "counts": {"buy_order_count": 1},
            "btst_regime_gate": {"gate": gate, "mode": "enforce"},
            "funnel_diagnostics": {},
        },
        buy_orders=[PositionPlan(ticker="300724", shares=100, amount=10000.0, score_final=0.81, quality_score=0.62)],
        selection_targets={"300724": evaluation},
        target_mode="short_trade_only",
        dual_target_summary=DualTargetSummary(target_mode="short_trade_only", selection_target_count=1, short_trade_selected_count=1),
    )


def test_win_rate_first_precision_mode_downgrades_watch_only_selected(monkeypatch):
    """Win-rate-first precision mode: downgrade watch_only from selected to near_miss."""
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE", "true")
    
    plan = _build_test_plan(prior_quality_label="watch_only", gate="normal_trade")
    result = _enforce_btst_execution_contract_p5(plan)
    
    evaluation = result.selection_targets["300724"]
    assert evaluation.short_trade is not None
    assert evaluation.short_trade.decision == "near_miss", "watch_only should be downgraded in precision mode"
    assert evaluation.execution_eligible is False
    assert "win_rate_first_precision_prior_not_execution_ready" in evaluation.downgrade_reasons
    assert result.buy_orders == []
    assert result.dual_target_summary.execution_eligible_count == 0


def test_win_rate_first_precision_mode_downgrades_none_prior_quality_selected(monkeypatch):
    """Win-rate-first precision mode: downgrade None/missing prior quality from selected to near_miss."""
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE", "true")
    
    plan = _build_test_plan(prior_quality_label=None, gate="normal_trade")
    result = _enforce_btst_execution_contract_p5(plan)
    
    evaluation = result.selection_targets["300724"]
    assert evaluation.short_trade is not None
    assert evaluation.short_trade.decision == "near_miss", "None prior quality should be downgraded in precision mode"
    assert evaluation.execution_eligible is False
    assert "win_rate_first_precision_prior_not_execution_ready" in evaluation.downgrade_reasons
    assert result.buy_orders == []


def test_win_rate_first_precision_mode_allows_execution_ready_through(monkeypatch):
    """Win-rate-first precision mode: execution_ready candidates pass through."""
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE", "true")
    
    plan = _build_test_plan(prior_quality_label="execution_ready", gate="normal_trade")
    result = _enforce_btst_execution_contract_p5(plan)
    
    evaluation = result.selection_targets["300724"]
    assert evaluation.short_trade is not None
    assert evaluation.short_trade.decision == "selected", "execution_ready should pass through in precision mode"
    assert evaluation.execution_eligible is True
    assert len(result.buy_orders) == 1
    assert result.buy_orders[0].ticker == "300724"


def test_win_rate_first_precision_mode_off_preserves_baseline_behavior(monkeypatch):
    """Win-rate-first precision mode OFF: baseline P5 behavior preserved."""
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE", "false")
    
    # None prior quality should pass through when precision mode is OFF
    plan = _build_test_plan(prior_quality_label=None, gate="normal_trade")
    result = _enforce_btst_execution_contract_p5(plan)
    
    evaluation = result.selection_targets["300724"]
    assert evaluation.short_trade is not None
    assert evaluation.short_trade.decision == "selected", "None prior should pass through when precision mode OFF"
    assert evaluation.execution_eligible is True
    assert len(result.buy_orders) == 1


def test_win_rate_first_precision_mode_does_not_touch_near_miss(monkeypatch):
    """Win-rate-first precision mode: does not change near_miss candidates."""
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE", "true")
    
    plan = _build_test_plan(decision="near_miss", prior_quality_label="watch_only", gate="normal_trade")
    plan.buy_orders = []  # near_miss has no buy orders
    plan.dual_target_summary.short_trade_selected_count = 0
    plan.dual_target_summary.short_trade_near_miss_count = 1
    
    result = _enforce_btst_execution_contract_p5(plan)
    
    evaluation = result.selection_targets["300724"]
    assert evaluation.short_trade is not None
    assert evaluation.short_trade.decision == "near_miss", "near_miss should remain near_miss"
    assert evaluation.execution_eligible is False


def test_win_rate_first_precision_mode_combined_with_existing_downgrades(monkeypatch):
    """Win-rate-first precision mode: combines with existing P5 downgrade reasons."""
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE", "true")
    
    # Bad gate + watch_only = both downgrade reasons should be present
    plan = _build_test_plan(prior_quality_label="watch_only", gate="shadow_only")
    result = _enforce_btst_execution_contract_p5(plan)
    
    evaluation = result.selection_targets["300724"]
    assert evaluation.short_trade is not None
    assert evaluation.short_trade.decision == "near_miss"
    assert "btst_regime_gate_not_tradeable" in evaluation.downgrade_reasons
    assert "win_rate_first_precision_prior_not_execution_ready" in evaluation.downgrade_reasons
    assert len(evaluation.downgrade_reasons) >= 2


def test_win_rate_first_precision_mode_preserves_formal_blocked_selected_provenance(monkeypatch):
    """CRITICAL: Win-rate-first precision mode must NOT downgrade already formal-blocked selected names.
    
    Formal-blocked names (p2_execution_blocked, p3_execution_blocked, etc.) that have raw decision="selected"
    must preserve that raw decision for correct reporting (blocked-selected provenance).
    
    The win-rate-first downgrade should ONLY apply to non-blocked selected names with bad prior quality.
    """
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE", "true")
    
    # Build a name that is raw selected + p2_execution_blocked + watch_only prior
    evaluation = DualTargetEvaluation(
        ticker="300724",
        trade_date="20260422",
        candidate_source="layer_c_watchlist",
        p3_prior_quality_label="watch_only",  # Would trigger downgrade if not blocked
        p2_execution_blocked=True,  # Formal block flag
        p2_execution_block_reason="gate:shadow_only",
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision="selected",  # Raw decision is selected
            score_target=0.81,
        ),
    )
    plan = ExecutionPlan(
        date="20260422",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "counts": {"buy_order_count": 0},
            "btst_regime_gate": {"gate": "normal_trade", "mode": "enforce"},
            "funnel_diagnostics": {},
        },
        buy_orders=[],  # Already blocked upstream, no buy orders
        selection_targets={"300724": evaluation},
        target_mode="short_trade_only",
        dual_target_summary=DualTargetSummary(target_mode="short_trade_only", selection_target_count=1, short_trade_selected_count=1),
    )
    
    result = _enforce_btst_execution_contract_p5(plan)
    
    evaluation = result.selection_targets["300724"]
    assert evaluation.short_trade is not None
    # CRITICAL: raw decision must remain "selected" to preserve formal-blocked-selected provenance
    assert evaluation.short_trade.decision == "selected", "Formal-blocked selected must preserve raw 'selected' decision"
    # But it must still be non-execution-eligible due to the formal block
    assert evaluation.execution_eligible is False, "Formal-blocked names are never execution-eligible"
    # And must have no buy orders
    assert result.buy_orders == [], "Formal-blocked names must have no buy orders"
    # Win-rate-first downgrade should NOT be in reasons (because we didn't downgrade a formal block)
    assert "win_rate_first_precision_prior_not_execution_ready" not in evaluation.downgrade_reasons
