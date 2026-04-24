from __future__ import annotations

import pytest

from src.execution.daily_pipeline import (
    _enforce_btst_execution_contract_p5,
    _enforce_btst_regime_gate_p2,
)
from src.execution.models import ExecutionPlan
from src.portfolio.models import PositionPlan
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetEvaluationResult


def _build_plan(
    *,
    decision: str = "selected",
    candidate_source: str = "layer_c_watchlist",
    prior_quality_label: str = "watch_only",
    gate: str = "shadow_only",
) -> ExecutionPlan:
    evaluation = DualTargetEvaluation(
        ticker="300724",
        trade_date="20260422",
        candidate_source=candidate_source,
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


def test_p5_execution_contract_enforce_downgrades_non_eligible_selected(monkeypatch):
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    plan = _build_plan()

    result = _enforce_btst_execution_contract_p5(plan)
    evaluation = result.selection_targets["300724"]

    assert result.buy_orders == []
    assert evaluation.execution_eligible is False
    assert evaluation.short_trade is not None
    assert evaluation.short_trade.decision == "near_miss"
    assert evaluation.short_trade.execution_eligible is False
    assert evaluation.historical_prior_quality_level == "watch_only"
    assert evaluation.btst_regime_gate == "shadow_only"
    assert "btst_regime_gate_not_tradeable" in evaluation.downgrade_reasons
    assert "historical_prior_not_execution_ready" in evaluation.downgrade_reasons
    assert result.dual_target_summary.execution_eligible_count == 0
    assert result.dual_target_summary.short_trade_near_miss_count == 1


@pytest.mark.parametrize("candidate_source", ["upgrade_only", "research_only"])
def test_p5_execution_contract_enforce_downgrades_non_formal_candidate_sources(monkeypatch, candidate_source):
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    plan = _build_plan(candidate_source=candidate_source, prior_quality_label="execution_ready", gate="normal_trade")

    result = _enforce_btst_execution_contract_p5(plan)
    evaluation = result.selection_targets["300724"]
    enforcement_payload = result.risk_metrics["btst_execution_contract_p5_enforcement"]

    assert result.buy_orders == []
    assert evaluation.execution_eligible is False
    assert evaluation.downgrade_reasons == ["research_only_source_not_formal_execution"]
    assert evaluation.historical_prior_quality_level == "execution_ready"
    assert evaluation.btst_regime_gate == "normal_trade"
    assert evaluation.short_trade is not None
    assert evaluation.short_trade.decision == "near_miss"
    assert evaluation.short_trade.execution_eligible is False
    assert evaluation.short_trade.downgrade_reasons == ["research_only_source_not_formal_execution"]
    assert evaluation.short_trade.historical_prior_quality_level == "execution_ready"
    assert evaluation.short_trade.btst_regime_gate == "normal_trade"
    assert result.dual_target_summary.execution_eligible_count == 0
    assert result.dual_target_summary.short_trade_selected_count == 0
    assert result.dual_target_summary.short_trade_near_miss_count == 1
    assert result.risk_metrics["counts"]["buy_order_count"] == 0
    assert enforcement_payload == {
        "mode": "enforce",
        "gate": "normal_trade",
        "execution_eligible_count": 0,
        "downgraded_to_near_miss_count": 1,
        "buy_orders_removed": 1,
        "buy_orders_already_cleared_upstream_count": 0,
        "downgrade_reason_counts": {"research_only_source_not_formal_execution": 1},
    }


def test_p5_execution_contract_off_keeps_existing_behavior(monkeypatch):
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "off")
    plan = _build_plan()

    result = _enforce_btst_execution_contract_p5(plan)
    evaluation = result.selection_targets["300724"]

    assert [order.ticker for order in result.buy_orders] == ["300724"]
    assert evaluation.short_trade is not None
    assert evaluation.short_trade.decision == "selected"
    assert evaluation.execution_eligible is False
    assert result.dual_target_summary.short_trade_selected_count == 1


def test_p5_execution_contract_reports_when_buy_orders_were_already_cleared_by_p2(monkeypatch):
    monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    plan = _build_plan(prior_quality_label="execution_ready", gate="shadow_only")

    after_p2 = _enforce_btst_regime_gate_p2(plan)
    assert after_p2.buy_orders == []

    result = _enforce_btst_execution_contract_p5(after_p2)
    enforcement_payload = result.risk_metrics["btst_execution_contract_p5_enforcement"]

    assert enforcement_payload["buy_orders_removed"] == 0
    assert enforcement_payload["buy_orders_already_cleared_upstream_count"] == 1
