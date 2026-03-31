from src.execution.models import ExecutionPlan, LayerCResult
from src.screening.models import StrategySignal
from src.targets import get_short_trade_target_profile
from src.targets.router import build_selection_targets
from src.targets.short_trade_target import evaluate_short_trade_rejected_target


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _make_prepared_breakout_entry() -> dict:
    return {
        "ticker": "300620",
        "score_b": 0.60,
        "score_c": 0.60,
        "score_final": 0.40,
        "quality_score": 0.63,
        "decision": "watch",
        "reason": "watchlist_selected",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                60.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 28.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 34.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 44.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 42.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 10.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                60.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 30.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.40, "investor": 0.20}},
    }


def _make_profitability_hard_cliff_signal() -> StrategySignal:
    return _make_signal(
        -1,
        68.0,
        sub_factors={
            "profitability": {
                "direction": -1,
                "confidence": 72.0,
                "completeness": 1.0,
                "metrics": {"positive_count": 0},
            },
            "financial_health": {"direction": 0, "confidence": 34.0, "completeness": 1.0},
            "growth": {"direction": 1, "confidence": 48.0, "completeness": 1.0},
        },
    )


def _make_profitability_relief_entry(*, sector_resonance_ready: bool = True, include_profitability_hard_cliff: bool = True) -> dict:
    agent_contributions = {"analyst": 0.48, "investor": 0.28} if sector_resonance_ready else {"analyst": 0.08, "investor": 0.04}
    strategy_signals = {
        "trend": _make_signal(
            1,
            55.0,
            sub_factors={
                "momentum": {"direction": 1, "confidence": 55.0, "completeness": 1.0},
                "adx_strength": {"direction": 1, "confidence": 52.0, "completeness": 1.0},
                "ema_alignment": {"direction": 1, "confidence": 52.0, "completeness": 1.0},
                "volatility": {"direction": 1, "confidence": 45.0, "completeness": 1.0},
                "long_trend_alignment": {"direction": 1, "confidence": 8.0, "completeness": 1.0},
            },
        ).model_dump(mode="json"),
        "event_sentiment": _make_signal(
            1,
            52.0,
            sub_factors={
                "event_freshness": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                "news_sentiment": {"direction": 1, "confidence": 52.0, "completeness": 1.0},
            },
        ).model_dump(mode="json"),
        "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
    }
    if include_profitability_hard_cliff:
        strategy_signals["fundamental"] = _make_profitability_hard_cliff_signal().model_dump(mode="json")
    return {
        "ticker": "300987",
        "score_b": 0.30,
        "score_c": 0.05,
        "score_final": 0.18,
        "quality_score": 0.60,
        "decision": "avoid",
        "reason": "decision_avoid",
        "reasons": ["decision_avoid"],
        "strategy_signals": strategy_signals,
        "agent_contribution_summary": {"cohort_contributions": agent_contributions},
    }


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


def test_build_selection_targets_adds_boundary_short_trade_candidate_outside_research_funnel() -> None:
    selection_targets, summary = build_selection_targets(
        trade_date="20260328",
        watchlist=[],
        rejected_entries=[],
        supplemental_short_trade_entries=[
            {
                "ticker": "000625",
                "score_b": 0.49,
                "score_c": 0.0,
                "score_final": 0.49,
                "quality_score": 0.52,
                "decision": "watch",
                "reason": "near_fast_score_threshold",
                "reasons": ["near_fast_score_threshold"],
                "candidate_source": "short_trade_boundary",
                "strategy_signals": {
                    "trend": _make_signal(
                        1,
                        86.0,
                        sub_factors={
                            "momentum": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                            "adx_strength": {"direction": 1, "confidence": 83.0, "completeness": 1.0},
                            "ema_alignment": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                            "volatility": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
                            "long_trend_alignment": {"direction": 0, "confidence": 18.0, "completeness": 1.0},
                        },
                    ).model_dump(mode="json"),
                    "event_sentiment": _make_signal(
                        1,
                        78.0,
                        sub_factors={
                            "event_freshness": {"direction": 1, "confidence": 92.0, "completeness": 1.0},
                            "news_sentiment": {"direction": 1, "confidence": 68.0, "completeness": 1.0},
                        },
                    ).model_dump(mode="json"),
                    "mean_reversion": _make_signal(-1, 12.0).model_dump(mode="json"),
                },
            }
        ],
        target_mode="dual_target",
    )

    assert selection_targets["000625"].research is None
    assert selection_targets["000625"].short_trade is not None
    assert selection_targets["000625"].short_trade.decision == "selected"
    assert selection_targets["000625"].candidate_source == "short_trade_boundary"
    assert summary.research_target_count == 0
    assert summary.short_trade_target_count == 1
    assert summary.short_trade_selected_count == 1


def test_build_selection_targets_softens_layer_c_avoid_without_bearish_conflict() -> None:
    selection_targets, summary = build_selection_targets(
        trade_date="20260328",
        watchlist=[],
        rejected_entries=[
            {
                "ticker": "300888",
                "score_b": 0.54,
                "score_c": 0.04,
                "score_final": 0.26,
                "quality_score": 0.57,
                "decision": "avoid",
                "reason": "decision_avoid",
                "reasons": ["decision_avoid"],
                "strategy_signals": {
                    "trend": _make_signal(
                        1,
                        84.0,
                        sub_factors={
                            "momentum": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                            "adx_strength": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                            "ema_alignment": {"direction": 1, "confidence": 76.0, "completeness": 1.0},
                            "volatility": {"direction": 1, "confidence": 62.0, "completeness": 1.0},
                            "long_trend_alignment": {"direction": 0, "confidence": 20.0, "completeness": 1.0},
                        },
                    ).model_dump(mode="json"),
                    "event_sentiment": _make_signal(
                        1,
                        73.0,
                        sub_factors={
                            "event_freshness": {"direction": 1, "confidence": 87.0, "completeness": 1.0},
                            "news_sentiment": {"direction": 1, "confidence": 64.0, "completeness": 1.0},
                        },
                    ).model_dump(mode="json"),
                    "mean_reversion": _make_signal(-1, 15.0).model_dump(mode="json"),
                },
                "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.16, "investor": 0.07}},
            }
        ],
        target_mode="dual_target",
    )

    assert selection_targets["300888"].research is not None
    assert selection_targets["300888"].research.decision == "rejected"
    assert selection_targets["300888"].short_trade is not None
    assert selection_targets["300888"].short_trade.decision in {"selected", "near_miss", "rejected"}
    assert selection_targets["300888"].short_trade.decision != "blocked"
    assert "layer_c_bearish_conflict" not in selection_targets["300888"].short_trade.blockers
    assert summary.short_trade_blocked_count == 0


def test_execution_plan_defaults_dual_target_fields_for_legacy_payloads() -> None:
    plan = ExecutionPlan.model_validate({"date": "20260328"})

    assert plan.target_mode == "research_only"
    assert plan.selection_targets == {}
    assert plan.dual_target_summary.target_mode == "research_only"
    assert plan.dual_target_summary.selection_target_count == 0


def test_short_trade_profiles_define_ordered_governance_envelopes() -> None:
    default_profile = get_short_trade_target_profile("default")
    conservative_profile = get_short_trade_target_profile("conservative")
    aggressive_profile = get_short_trade_target_profile("aggressive")

    assert conservative_profile.select_threshold > default_profile.select_threshold > aggressive_profile.select_threshold
    assert conservative_profile.layer_c_avoid_penalty > default_profile.layer_c_avoid_penalty > aggressive_profile.layer_c_avoid_penalty
    assert conservative_profile.stale_score_penalty_weight > default_profile.stale_score_penalty_weight > aggressive_profile.stale_score_penalty_weight


def test_short_trade_target_reports_profile_metadata_and_override_thresholds() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry={
            "ticker": "300750",
            "score_b": 0.48,
            "score_c": 0.08,
            "score_final": 0.29,
            "quality_score": 0.59,
            "decision": "watch",
            "reason": "score_final_below_watchlist_threshold",
            "reasons": ["score_final_below_watchlist_threshold"],
            "strategy_signals": {
                "trend": _make_signal(
                    1,
                    80.0,
                    sub_factors={
                        "momentum": {"direction": 1, "confidence": 82.0, "completeness": 1.0},
                        "adx_strength": {"direction": 1, "confidence": 74.0, "completeness": 1.0},
                        "ema_alignment": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
                        "volatility": {"direction": 1, "confidence": 64.0, "completeness": 1.0},
                        "long_trend_alignment": {"direction": 0, "confidence": 25.0, "completeness": 1.0},
                    },
                ).model_dump(mode="json"),
                "event_sentiment": _make_signal(
                    1,
                    72.0,
                    sub_factors={
                        "event_freshness": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                        "news_sentiment": {"direction": 1, "confidence": 61.0, "completeness": 1.0},
                    },
                ).model_dump(mode="json"),
                "mean_reversion": _make_signal(-1, 18.0).model_dump(mode="json"),
            },
            "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.18, "investor": 0.09}},
        },
        profile_name="aggressive",
        profile_overrides={"select_threshold": 0.57, "near_miss_threshold": 0.41},
    )

    assert result.metrics_payload["thresholds"]["profile_name"] == "aggressive"
    assert result.metrics_payload["thresholds"]["select_threshold"] == 0.57
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.41
    assert result.explainability_payload["target_profile"] == "aggressive"


def test_staged_breakout_profile_promotes_prepared_breakout_to_near_miss() -> None:
    default_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_prepared_breakout_entry(),
        profile_name="default",
    )
    staged_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_prepared_breakout_entry(),
        profile_name="staged_breakout",
    )

    assert default_result.decision == "rejected"
    assert default_result.rejection_reasons == ["score_short_below_threshold"]
    assert staged_result.decision == "near_miss"
    assert staged_result.metrics_payload["breakout_stage"] == "prepared_breakout"
    assert staged_result.metrics_payload["selected_breakout_gate_pass"] is False
    assert staged_result.metrics_payload["near_miss_breakout_gate_pass"] is True
    assert staged_result.metrics_payload["thresholds"]["profile_name"] == "staged_breakout"
    assert staged_result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.42
    assert staged_result.metrics_payload["thresholds"]["near_miss_breakout_freshness_min"] == 0.18
    assert staged_result.metrics_payload["thresholds"]["near_miss_trend_acceleration_min"] == 0.22


def test_short_trade_target_weight_overrides_can_raise_prepared_breakout_score() -> None:
    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_prepared_breakout_entry(),
        profile_name="default",
    )
    weighted_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_prepared_breakout_entry(),
        profile_name="default",
        profile_overrides={
            "breakout_freshness_weight": 0.08,
            "trend_acceleration_weight": 0.20,
            "volume_expansion_quality_weight": 0.20,
            "close_strength_weight": 0.06,
            "sector_resonance_weight": 0.04,
            "catalyst_freshness_weight": 0.20,
            "layer_c_alignment_weight": 0.22,
        },
    )

    assert weighted_result.score_target > baseline_result.score_target
    assert weighted_result.decision == "near_miss"
    assert weighted_result.metrics_payload["positive_score_weights"]["layer_c_alignment"] > baseline_result.metrics_payload["positive_score_weights"]["layer_c_alignment"]
    assert weighted_result.metrics_payload["thresholds"]["effective_positive_score_weights"]["catalyst_freshness"] == 0.20


def test_short_trade_target_can_remove_conflict_hard_block_without_dropping_overhead_conflict_penalty() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry={
            "ticker": "300724",
            "score_b": 0.62,
            "score_c": 0.18,
            "score_final": 0.41,
            "quality_score": 0.66,
            "decision": "watch",
            "bc_conflict": "b_positive_c_strong_bearish",
            "reason": "watchlist_selected",
            "reasons": ["watchlist_selected"],
            "strategy_signals": {
                "trend": _make_signal(
                    1,
                    84.0,
                    sub_factors={
                        "momentum": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                        "adx_strength": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                        "ema_alignment": {"direction": 1, "confidence": 82.0, "completeness": 1.0},
                        "volatility": {"direction": 1, "confidence": 76.0, "completeness": 1.0},
                        "long_trend_alignment": {"direction": 0, "confidence": 20.0, "completeness": 1.0},
                    },
                ).model_dump(mode="json"),
                "event_sentiment": _make_signal(
                    1,
                    76.0,
                    sub_factors={
                        "event_freshness": {"direction": 1, "confidence": 82.0, "completeness": 1.0},
                        "news_sentiment": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
                    },
                ).model_dump(mode="json"),
                "mean_reversion": _make_signal(-1, 12.0).model_dump(mode="json"),
            },
            "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.10, "investor": 0.04}},
        },
        profile_overrides={
            "hard_block_bearish_conflicts": [],
            "overhead_conflict_penalty_conflicts": ["b_positive_c_strong_bearish"],
        },
    )

    assert "layer_c_bearish_conflict" not in result.blockers
    assert result.gate_status["structural"] == "pass"
    assert result.metrics_payload["overhead_supply_penalty"] > 0.0
    assert result.metrics_payload["thresholds"]["hard_block_bearish_conflicts"] == []
    assert result.metrics_payload["thresholds"]["overhead_conflict_penalty_conflicts"] == ["b_positive_c_strong_bearish"]


def test_profitability_relief_profile_reduces_avoid_penalty_for_strong_btst_context() -> None:
    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_profitability_relief_entry(),
        profile_name="default",
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_profitability_relief_entry(),
        profile_name="staged_breakout_profitability_relief",
    )

    assert baseline_result.decision == "rejected"
    assert relief_result.decision == "near_miss"
    assert baseline_result.metrics_payload["profitability_relief_applied"] is False
    assert relief_result.metrics_payload["profitability_relief_applied"] is True
    assert relief_result.metrics_payload["profitability_hard_cliff"] is True
    assert relief_result.metrics_payload["layer_c_avoid_penalty"] == 0.04
    assert relief_result.metrics_payload["base_layer_c_avoid_penalty"] == 0.12
    assert relief_result.metrics_payload["thresholds"]["profile_name"] == "staged_breakout_profitability_relief"
    assert relief_result.metrics_payload["thresholds"]["profitability_relief_enabled"] is True
    assert relief_result.explainability_payload["profitability_relief"]["applied"] is True


def test_profitability_relief_requires_sector_resonance_confirmation() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_profitability_relief_entry(sector_resonance_ready=False),
        profile_name="staged_breakout_profitability_relief",
    )

    assert result.decision == "rejected"
    assert result.metrics_payload["profitability_relief_applied"] is False
    assert result.metrics_payload["layer_c_avoid_penalty"] == 0.12
    assert result.metrics_payload["profitability_relief_gate_hits"]["sector_resonance"] is False
    assert "profitability_relief_not_triggered" in result.negative_tags


def test_profitability_relief_does_not_trigger_without_profitability_hard_cliff() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_profitability_relief_entry(include_profitability_hard_cliff=False),
        profile_name="staged_breakout_profitability_relief",
    )

    assert result.metrics_payload["profitability_hard_cliff"] is False
    assert result.metrics_payload["profitability_relief_applied"] is False
    assert result.metrics_payload["layer_c_avoid_penalty"] == 0.12
    assert result.explainability_payload["profitability_relief"]["hard_cliff"] is False