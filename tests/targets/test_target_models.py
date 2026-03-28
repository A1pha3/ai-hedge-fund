from src.execution.models import ExecutionPlan, LayerCResult
from src.targets.router import build_selection_targets


def test_build_selection_targets_wraps_research_semantics_for_watchlist() -> None:
    watchlist = [
        LayerCResult(
            ticker="000001",
            score_b=0.61,
            score_c=0.22,
            score_final=0.43,
            quality_score=0.58,
            decision="watch",
        )
    ]

    selection_targets, summary = build_selection_targets(
        trade_date="20260328",
        watchlist=watchlist,
        buy_order_tickers={"000001"},
        target_mode="research_only",
    )

    assert list(selection_targets.keys()) == ["000001"]
    assert selection_targets["000001"].ticker == "000001"
    assert selection_targets["000001"].research is not None
    assert selection_targets["000001"].research.decision == "selected"
    assert selection_targets["000001"].research.gate_status["execution_bridge"] == "pass"
    assert selection_targets["000001"].short_trade is None
    assert summary.target_mode == "research_only"
    assert summary.selection_target_count == 1
    assert summary.research_target_count == 1
    assert summary.research_selected_count == 1
    assert summary.shell_target_count == 0


def test_build_selection_targets_builds_dual_target_delta_for_rejected_entry() -> None:
    selection_targets, summary = build_selection_targets(
        trade_date="20260328",
        watchlist=[],
        rejected_entries=[
            {
                "ticker": "300750",
                "score_b": 0.55,
                "score_c": -0.12,
                "score_final": 0.18,
                "reason": "score_final_below_watchlist_threshold",
                "reasons": ["score_final_below_watchlist_threshold"],
            }
        ],
        target_mode="dual_target",
    )

    assert selection_targets["300750"].research is not None
    assert selection_targets["300750"].research.decision == "near_miss"
    assert selection_targets["300750"].short_trade is not None
    assert selection_targets["300750"].short_trade.decision == "rejected"
    assert selection_targets["300750"].delta_classification == "both_reject_but_reason_diverge"
    assert summary.research_target_count == 1
    assert summary.short_trade_target_count == 1
    assert summary.research_near_miss_count == 1
    assert summary.short_trade_rejected_count == 1
    assert summary.delta_classification_counts == {"both_reject_but_reason_diverge": 1}


def test_execution_plan_defaults_dual_target_fields_for_legacy_payloads() -> None:
    plan = ExecutionPlan.model_validate({"date": "20260328"})

    assert plan.target_mode == "research_only"
    assert plan.selection_targets == {}
    assert plan.dual_target_summary.target_mode == "research_only"
    assert plan.dual_target_summary.selection_target_count == 0