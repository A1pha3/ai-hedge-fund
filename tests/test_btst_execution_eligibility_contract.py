from __future__ import annotations

import pytest

from src.execution.daily_pipeline import (
    _enforce_btst_execution_contract_p5,
    _enforce_btst_regime_gate_p2,
)
from src.execution.models import ExecutionPlan
from src.portfolio.models import PositionPlan
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetEvaluationResult
from src.targets.router_build_helpers import build_reporting_target_summary


def _build_plan(
    *,
    decision: str = "selected",
    candidate_source: str = "layer_c_watchlist",
    prior_quality_label: str = "watch_only",
    gate: str = "shadow_only",
    preferred_entry_mode: str | None = None,
    positive_tags: list[str] | None = None,
    historical_prior: dict[str, object] | None = None,
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
            preferred_entry_mode=preferred_entry_mode,
            positive_tags=list(positive_tags or []),
            metrics_payload={
                "historical_prior": dict(historical_prior or {}),
            },
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


def test_build_reporting_target_summary_tracks_formal_blocked_selected_provenance() -> None:
    evaluation = DualTargetEvaluation(
        ticker="300724",
        trade_date="20260422",
        execution_eligible=False,
        p2_execution_blocked=True,
        p2_execution_block_reason="p2_regime_gate_enforce:halt",
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision="selected",
            score_target=0.81,
        ),
    )

    summary = build_reporting_target_summary(
        selection_targets={"300724": evaluation},
        target_mode="short_trade_only",
    )

    assert summary.short_trade_selected_count == 0
    assert summary.short_trade_blocked_count == 1
    assert summary.short_trade_formal_blocked_selected_count == 1
    assert summary.short_trade_formal_block_flag_counts == {"p2_execution_blocked": 1}


def test_build_reporting_target_summary_tracks_non_halt_formal_blocked_selected_provenance() -> None:
    evaluation = DualTargetEvaluation(
        ticker="300724",
        trade_date="20260422",
        execution_eligible=False,
        btst_regime_gate="shadow_only",
        historical_prior_quality_level="watch_only",
        p2_execution_blocked=True,
        p2_execution_block_reason="p2_regime_gate_enforce:shadow_only",
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision="selected",
            score_target=0.81,
        ),
    )

    summary = build_reporting_target_summary(
        selection_targets={"300724": evaluation},
        target_mode="short_trade_only",
    )

    assert summary.short_trade_formal_non_halt_blocked_selected_count == 1
    assert summary.short_trade_formal_non_halt_gate_counts == {"shadow_only": 1}
    assert summary.short_trade_formal_non_halt_prior_quality_counts == {"watch_only": 1}


def test_shadow_only_close_continuation_near_miss_survives_p2_and_promotes_to_selected(monkeypatch) -> None:
    monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    plan = _build_plan(
        decision="near_miss",
        prior_quality_label="watch_only",
        gate="shadow_only",
        preferred_entry_mode="confirm_then_hold_breakout",
        positive_tags=["historical_execution_relief", "fresh_catalyst_support"],
        historical_prior={
            "execution_quality_label": "close_continuation",
            "evaluable_count": 5,
            "next_close_positive_rate": 0.58,
            "next_high_hit_rate_at_threshold": 0.64,
        },
    )

    after_p2 = _enforce_btst_regime_gate_p2(plan)

    assert [order.ticker for order in after_p2.buy_orders] == ["300724"]
    assert after_p2.selection_targets["300724"].p2_execution_blocked is False

    result = _enforce_btst_execution_contract_p5(after_p2)
    evaluation = result.selection_targets["300724"]

    assert evaluation.execution_eligible is True
    assert evaluation.short_trade is not None
    assert evaluation.short_trade.decision == "selected"
    assert evaluation.short_trade.execution_eligible is True
    assert [order.ticker for order in result.buy_orders] == ["300724"]


def test_shadow_only_promotion_reads_historical_prior_from_explainability_payload(monkeypatch) -> None:
    monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
    plan = _build_plan(
        decision="near_miss",
        prior_quality_label="watch_only",
        gate="shadow_only",
        preferred_entry_mode="confirm_then_hold_breakout",
        positive_tags=["historical_execution_relief", "fresh_catalyst_support"],
    )
    short_trade = plan.selection_targets["300724"].short_trade
    assert short_trade is not None
    short_trade.metrics_payload = {}
    short_trade.explainability_payload = {
        "historical_prior": {
            "execution_quality_label": "close_continuation",
            "evaluable_count": 5,
            "next_close_positive_rate": 0.58,
            "next_high_hit_rate_at_threshold": 0.64,
        }
    }

    after_p2 = _enforce_btst_regime_gate_p2(plan)

    assert [order.ticker for order in after_p2.buy_orders] == ["300724"]


def test_halt_close_continuation_selected_survives_p2_and_p5_relief(monkeypatch) -> None:
    monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    plan = _build_plan(
        decision="selected",
        prior_quality_label="watch_only",
        gate="halt",
        preferred_entry_mode="confirm_then_hold_breakout",
        positive_tags=["historical_execution_relief", "fresh_catalyst_support"],
    )
    short_trade = plan.selection_targets["300724"].short_trade
    assert short_trade is not None
    short_trade.explainability_payload = {
        "historical_prior": {
            "execution_quality_label": "close_continuation",
            "evaluable_count": 6,
            "next_close_positive_rate": 0.82,
            "next_high_hit_rate_at_threshold": 0.95,
        }
    }

    after_p2 = _enforce_btst_regime_gate_p2(plan)

    assert [order.ticker for order in after_p2.buy_orders] == ["300724"]
    assert after_p2.selection_targets["300724"].p2_execution_blocked is False

    result = _enforce_btst_execution_contract_p5(after_p2)

    assert [order.ticker for order in result.buy_orders] == ["300724"]
    assert result.selection_targets["300724"].execution_eligible is True


def test_shadow_only_close_continuation_near_miss_requires_catalyst_support(monkeypatch) -> None:
    monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    plan = _build_plan(
        decision="near_miss",
        prior_quality_label="watch_only",
        gate="shadow_only",
        preferred_entry_mode="confirm_then_hold_breakout",
        positive_tags=["historical_execution_relief"],
        historical_prior={
            "execution_quality_label": "close_continuation",
            "evaluable_count": 5,
            "next_close_positive_rate": 0.58,
            "next_high_hit_rate_at_threshold": 0.64,
        },
    )

    result = _enforce_btst_execution_contract_p5(_enforce_btst_regime_gate_p2(plan))

    assert result.buy_orders == []
    assert result.selection_targets["300724"].execution_eligible is False
    assert result.selection_targets["300724"].short_trade is not None


def test_halt_close_continuation_selected_requires_minimum_score_target(monkeypatch) -> None:
    monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    plan = _build_plan(
        decision="selected",
        prior_quality_label="watch_only",
        gate="halt",
        preferred_entry_mode="confirm_then_hold_breakout",
        positive_tags=["historical_execution_relief", "fresh_catalyst_support"],
    )
    short_trade = plan.selection_targets["300724"].short_trade
    assert short_trade is not None
    short_trade.score_target = 0.49
    short_trade.explainability_payload = {
        "historical_prior": {
            "execution_quality_label": "close_continuation",
            "evaluable_count": 6,
            "next_close_positive_rate": 0.82,
            "next_high_hit_rate_at_threshold": 0.95,
        }
    }

    result = _enforce_btst_execution_contract_p5(_enforce_btst_regime_gate_p2(plan))

    assert result.buy_orders == []
    assert result.selection_targets["300724"].execution_eligible is False
    assert result.selection_targets["300724"].short_trade is not None


def test_halt_catalyst_theme_carryover_selected_survives_p2_and_p5_relief(monkeypatch) -> None:
    monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    plan = _build_plan(
        decision="selected",
        candidate_source="catalyst_theme",
        prior_quality_label="watch_only",
        gate="halt",
        preferred_entry_mode="confirm_then_hold_breakout",
        positive_tags=["catalyst_theme_short_trade_carryover_applied"],
    )
    short_trade = plan.selection_targets["300724"].short_trade
    assert short_trade is not None
    short_trade.score_target = 0.52
    short_trade.explainability_payload = {
        "replay_context": {
            "candidate_reason_codes": [
                "catalyst_theme_candidate_score_ranked",
                "catalyst_theme_short_trade_carryover_candidate",
            ],
            "short_trade_catalyst_relief": {
                "enabled": True,
                "reason": "catalyst_theme_short_trade_carryover",
                "min_historical_evaluable_count": 3,
            },
        },
        "upstream_shadow_catalyst_relief": {
            "enabled": True,
            "eligible": True,
            "applied": True,
            "reason": "catalyst_theme_short_trade_carryover",
        },
        "historical_prior": {
            "execution_quality_label": "close_continuation",
            "evaluable_count": 4,
            "next_close_positive_rate": 0.68,
            "next_high_hit_rate_at_threshold": 0.78,
        },
    }

    after_p2 = _enforce_btst_regime_gate_p2(plan)

    assert [order.ticker for order in after_p2.buy_orders] == ["300724"]
    assert after_p2.selection_targets["300724"].p2_execution_blocked is False

    result = _enforce_btst_execution_contract_p5(after_p2)

    assert [order.ticker for order in result.buy_orders] == ["300724"]
    assert result.selection_targets["300724"].execution_eligible is True


def test_halt_catalyst_theme_carryover_selected_clears_stale_p2_flags_from_replay(monkeypatch) -> None:
    monkeypatch.setenv("BTST_0422_P2_REGIME_GATE_MODE", "enforce")
    monkeypatch.setenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "enforce")
    plan = _build_plan(
        decision="selected",
        candidate_source="catalyst_theme",
        prior_quality_label="watch_only",
        gate="halt",
        preferred_entry_mode="confirm_then_hold_breakout",
        positive_tags=["catalyst_theme_short_trade_carryover_applied"],
    )
    evaluation = plan.selection_targets["300724"]
    short_trade = evaluation.short_trade
    assert short_trade is not None
    evaluation.execution_eligible = False
    evaluation.p2_execution_blocked = True
    evaluation.p2_execution_block_reason = "p2_regime_gate_enforce:halt"
    short_trade.execution_eligible = False
    short_trade.score_target = 0.52
    short_trade.explainability_payload = {
        "replay_context": {
            "candidate_reason_codes": [
                "catalyst_theme_candidate_score_ranked",
                "catalyst_theme_short_trade_carryover_candidate",
            ],
            "short_trade_catalyst_relief": {
                "enabled": True,
                "reason": "catalyst_theme_short_trade_carryover",
                "min_historical_evaluable_count": 3,
            },
        },
        "upstream_shadow_catalyst_relief": {
            "enabled": True,
            "eligible": True,
            "applied": True,
            "reason": "catalyst_theme_short_trade_carryover",
        },
        "historical_prior": {
            "execution_quality_label": "close_continuation",
            "evaluable_count": 4,
            "next_close_positive_rate": 0.68,
            "next_high_hit_rate_at_threshold": 0.78,
        },
    }

    after_p2 = _enforce_btst_regime_gate_p2(plan)

    assert [order.ticker for order in after_p2.buy_orders] == ["300724"]
    assert after_p2.selection_targets["300724"].p2_execution_blocked is False
    assert after_p2.selection_targets["300724"].p2_execution_block_reason is None

    result = _enforce_btst_execution_contract_p5(after_p2)

    assert result.selection_targets["300724"].execution_eligible is True
