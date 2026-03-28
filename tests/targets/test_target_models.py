from src.execution.models import ExecutionPlan, LayerCResult
from src.screening.models import StrategySignal
from src.targets.router import build_selection_targets


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


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
    assert selection_targets["300750"].short_trade.decision == "blocked"
    assert selection_targets["300750"].delta_classification == "both_reject_but_reason_diverge"
    assert summary.research_target_count == 1
    assert summary.short_trade_target_count == 1
    assert summary.research_near_miss_count == 1
    assert summary.short_trade_blocked_count == 1
    assert summary.delta_classification_counts == {"both_reject_but_reason_diverge": 1}


def test_build_selection_targets_selects_short_trade_for_fresh_watchlist_candidate() -> None:
    watchlist = [
        LayerCResult(
            ticker="000001",
            score_b=0.74,
            score_c=0.31,
            score_final=0.55,
            quality_score=0.67,
            decision="watch",
            strategy_signals={
                "trend": _make_signal(
                    1,
                    82.0,
                    sub_factors={
                        "momentum": {"direction": 1, "confidence": 85.0, "completeness": 1.0},
                        "adx_strength": {"direction": 1, "confidence": 76.0, "completeness": 1.0},
                        "ema_alignment": {"direction": 1, "confidence": 72.0, "completeness": 1.0},
                        "volatility": {"direction": 1, "confidence": 68.0, "completeness": 1.0},
                        "long_trend_alignment": {"direction": 0, "confidence": 30.0, "completeness": 1.0},
                    },
                ),
                "event_sentiment": _make_signal(
                    1,
                    74.0,
                    sub_factors={
                        "event_freshness": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                        "news_sentiment": {"direction": 1, "confidence": 66.0, "completeness": 1.0},
                    },
                ),
                "mean_reversion": _make_signal(-1, 20.0),
            },
            agent_contribution_summary={"cohort_contributions": {"analyst": 0.22, "investor": 0.11}},
        )
    ]

    selection_targets, summary = build_selection_targets(
        trade_date="20260328",
        watchlist=watchlist,
        buy_order_tickers={"000001"},
        target_mode="dual_target",
    )

    assert selection_targets["000001"].research is not None
    assert selection_targets["000001"].research.decision == "selected"
    assert selection_targets["000001"].short_trade is not None
    assert selection_targets["000001"].short_trade.decision == "selected"
    assert selection_targets["000001"].short_trade.score_target >= 0.58
    assert summary.short_trade_selected_count == 1
    assert summary.short_trade_blocked_count == 0


def test_build_selection_targets_promotes_rejected_entry_for_short_trade_when_signals_are_fresh() -> None:
    trend_signal = _make_signal(
        1,
        80.0,
        sub_factors={
            "momentum": {"direction": 1, "confidence": 82.0, "completeness": 1.0},
            "adx_strength": {"direction": 1, "confidence": 74.0, "completeness": 1.0},
            "ema_alignment": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
            "volatility": {"direction": 1, "confidence": 64.0, "completeness": 1.0},
            "long_trend_alignment": {"direction": 0, "confidence": 25.0, "completeness": 1.0},
        },
    )
    event_signal = _make_signal(
        1,
        72.0,
        sub_factors={
            "event_freshness": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
            "news_sentiment": {"direction": 1, "confidence": 61.0, "completeness": 1.0},
        },
    )

    selection_targets, summary = build_selection_targets(
        trade_date="20260328",
        watchlist=[],
        rejected_entries=[
            {
                "ticker": "300750",
                "score_b": 0.48,
                "score_c": 0.08,
                "score_final": 0.29,
                "quality_score": 0.59,
                "decision": "watch",
                "reason": "score_final_below_watchlist_threshold",
                "reasons": ["score_final_below_watchlist_threshold"],
                "strategy_signals": {
                    "trend": trend_signal.model_dump(mode="json"),
                    "event_sentiment": event_signal.model_dump(mode="json"),
                    "mean_reversion": _make_signal(-1, 18.0).model_dump(mode="json"),
                },
                "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.18, "investor": 0.09}},
            }
        ],
        target_mode="dual_target",
    )

    assert selection_targets["300750"].research is not None
    assert selection_targets["300750"].research.decision == "near_miss"
    assert selection_targets["300750"].short_trade is not None
    assert selection_targets["300750"].short_trade.decision == "selected"
    assert selection_targets["300750"].delta_classification == "research_reject_short_pass"
    assert summary.short_trade_selected_count == 1
    assert summary.short_trade_blocked_count == 0
    assert summary.delta_classification_counts == {"research_reject_short_pass": 1}


def test_execution_plan_defaults_dual_target_fields_for_legacy_payloads() -> None:
    plan = ExecutionPlan.model_validate({"date": "20260328"})

    assert plan.target_mode == "research_only"
    assert plan.selection_targets == {}
    assert plan.dual_target_summary.target_mode == "research_only"
    assert plan.dual_target_summary.selection_target_count == 0