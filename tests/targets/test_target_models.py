from src.execution.models import ExecutionPlan, LayerCResult
from src.screening.models import StrategySignal
from src.targets import get_short_trade_target_profile, use_short_trade_target_profile
from src.targets.router import build_selection_targets
from src.targets.short_trade_target import evaluate_short_trade_rejected_target, evaluate_short_trade_selected_target


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


def _make_prepared_breakout_penalty_relief_entry() -> dict:
    return {
        "ticker": "300505",
        "score_b": 0.3899,
        "score_c": 0.375,
        "score_final": 0.3832,
        "quality_score": 0.75,
        "decision": "watch",
        "candidate_source": "layer_c_watchlist",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                39.9193,
                sub_factors={
                    "momentum": {
                        "direction": 0,
                        "confidence": 50.0,
                        "completeness": 1.0,
                        "metrics": {
                            "momentum_1m": -0.1924,
                            "momentum_3m": 0.3893,
                            "momentum_6m": 0.4729,
                            "volume_momentum": 0.5695,
                        },
                    },
                    "adx_strength": {"direction": 1, "confidence": 31.1053, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {
                        "direction": 0,
                        "confidence": 50.0,
                        "completeness": 1.0,
                        "metrics": {
                            "historical_volatility": 0.8423,
                            "volatility_regime": 1.2639,
                            "volatility_z_score": 0.6055,
                            "atr_ratio": 0.0988,
                        },
                    },
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 0.0},
                },
            ).model_dump(mode="json"),
            "fundamental": _make_signal(1, 52.6667).model_dump(mode="json"),
            "mean_reversion": _make_signal(1, 11.1335).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.375, "investor": 0.0}},
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


def _make_upstream_shadow_catalyst_relief_entry(*, include_profitability_hard_cliff: bool = False) -> dict:
    strategy_signals = {
        "trend": _make_signal(
            1,
            95.0,
            sub_factors={
                "momentum": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                "adx_strength": {"direction": 1, "confidence": 85.0, "completeness": 1.0},
                "ema_alignment": {"direction": 1, "confidence": 95.0, "completeness": 1.0},
                "volatility": {"direction": 1, "confidence": 30.0, "completeness": 1.0},
                "long_trend_alignment": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
            },
        ).model_dump(mode="json"),
        "event_sentiment": _make_signal(
            1,
            40.0,
            sub_factors={
                "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
            },
        ).model_dump(mode="json"),
        "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
        "fundamental": (_make_profitability_hard_cliff_signal() if include_profitability_hard_cliff else _make_signal(1, 45.0)).model_dump(mode="json"),
    }
    return {
        "ticker": "300720" if not include_profitability_hard_cliff else "003036",
        "score_b": 0.20,
        "score_c": -0.40,
        "score_final": 0.05,
        "quality_score": 0.58,
        "decision": "watch",
        "reason": "upstream_shadow_release_candidate",
        "reasons": ["upstream_shadow_release_candidate"],
        "candidate_reason_codes": ["upstream_shadow_release_candidate"],
        "short_trade_catalyst_relief": {
            "enabled": True,
            "reason": "upstream_shadow_catalyst_relief",
            "catalyst_freshness_floor": 1.0,
            "near_miss_threshold": 0.45,
            "breakout_freshness_min": 0.38,
            "trend_acceleration_min": 0.80,
            "close_strength_min": 0.85,
            "require_no_profitability_hard_cliff": True,
        },
        "strategy_signals": strategy_signals,
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
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


def test_build_selection_targets_preserves_merge_approved_reason_codes_for_watchlist_item() -> None:
    watchlist = [
        LayerCResult(
            ticker="300720",
            score_b=0.55,
            score_c=0.12,
            score_final=0.22,
            quality_score=0.56,
            decision="watch",
            candidate_source="layer_c_watchlist_merge_approved",
            candidate_reason_codes=["merge_approved_continuation"],
        )
    ]

    selection_targets, _ = build_selection_targets(
        trade_date="20260328",
        watchlist=watchlist,
        buy_order_tickers=set(),
        target_mode="dual_target",
    )

    assert selection_targets["300720"].candidate_source == "layer_c_watchlist_merge_approved"
    assert "merge_approved_continuation" in selection_targets["300720"].candidate_reason_codes


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


def test_merge_approved_continuation_relief_promotes_boundary_watchlist_candidate_to_selected() -> None:
    watch_item = LayerCResult(
        ticker="300720",
        score_b=0.74,
        score_c=0.31,
        score_final=0.55,
        quality_score=0.67,
        decision="watch",
        candidate_source="layer_c_watchlist_merge_approved",
        candidate_reason_codes=["merge_approved_continuation"],
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

    baseline_result = evaluate_short_trade_selected_target(
        trade_date="20260328",
        item=watch_item,
        rank_hint=1,
        included_in_buy_orders=False,
        profile_overrides={
            "select_threshold": 0.90,
            "near_miss_threshold": 0.80,
            "merge_approved_continuation_relief_enabled": False,
        },
    )
    relief_result = evaluate_short_trade_selected_target(
        trade_date="20260328",
        item=watch_item,
        rank_hint=1,
        included_in_buy_orders=False,
        profile_overrides={
            "select_threshold": 0.90,
            "near_miss_threshold": 0.80,
            "merge_approved_continuation_relief_enabled": True,
            "merge_approved_continuation_select_threshold": 0.56,
            "merge_approved_continuation_near_miss_threshold": 0.44,
            "merge_approved_continuation_breakout_freshness_min": 0.24,
            "merge_approved_continuation_trend_acceleration_min": 0.30,
            "merge_approved_continuation_close_strength_min": 0.55,
        },
    )

    assert baseline_result.decision in {"near_miss", "rejected"}
    assert relief_result.decision == "selected"
    assert "merge_approved_continuation_relief_applied" in relief_result.positive_tags
    assert relief_result.metrics_payload["merge_approved_continuation_relief"]["applied"] is True
    assert relief_result.explainability_payload["merge_approved_continuation_relief"]["effective_select_threshold"] == 0.56


def test_watchlist_zero_catalyst_penalty_applies_only_to_layer_c_watchlist() -> None:
    entry = {
        **_make_prepared_breakout_entry(),
        "candidate_source": "layer_c_watchlist",
    }
    entry["strategy_signals"]["event_sentiment"] = _make_signal(
        0,
        0.0,
        sub_factors={
            "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
            "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
        },
    ).model_dump(mode="json")
    baseline_result = evaluate_short_trade_rejected_target(trade_date="20260328", entry=entry, rank_hint=1)

    with use_short_trade_target_profile(
        overrides={
            "watchlist_zero_catalyst_penalty": 0.12,
            "watchlist_zero_catalyst_catalyst_freshness_max": 0.05,
            "watchlist_zero_catalyst_close_strength_min": 0.45,
            "watchlist_zero_catalyst_layer_c_alignment_min": 0.70,
            "watchlist_zero_catalyst_sector_resonance_min": 0.35,
        }
    ):
        guarded_watchlist_result = evaluate_short_trade_rejected_target(trade_date="20260328", entry=entry, rank_hint=1)
        guarded_boundary_result = evaluate_short_trade_rejected_target(
            trade_date="20260328",
            entry={**entry, "candidate_source": "short_trade_boundary"},
            rank_hint=1,
        )

    assert guarded_watchlist_result.metrics_payload["watchlist_zero_catalyst_penalty"] == 0.12
    assert guarded_watchlist_result.metrics_payload["watchlist_zero_catalyst_guard"]["applied"] is True
    assert "watchlist_zero_catalyst_penalty_applied" in guarded_watchlist_result.negative_tags
    assert guarded_watchlist_result.score_target < baseline_result.score_target
    assert guarded_boundary_result.metrics_payload["watchlist_zero_catalyst_penalty"] == 0.0
    assert guarded_boundary_result.metrics_payload["watchlist_zero_catalyst_guard"]["applied"] is False


def test_watchlist_zero_catalyst_crowded_penalty_targets_crowded_zero_catalyst_watchlist_case() -> None:
    crowded_entry = {
        "ticker": "300724",
        "score_b": 0.60,
        "score_c": 0.60,
        "score_final": 0.44,
        "quality_score": 0.66,
        "decision": "watch",
        "reason": "watchlist_selected",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                95.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 95.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 40.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 18.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.60, "investor": 0.40}},
        "candidate_source": "layer_c_watchlist",
    }

    baseline_result = evaluate_short_trade_rejected_target(trade_date="20260328", entry=crowded_entry, rank_hint=1)

    with use_short_trade_target_profile(
        overrides={
            "watchlist_zero_catalyst_crowded_penalty": 0.06,
            "watchlist_zero_catalyst_crowded_catalyst_freshness_max": 0.05,
            "watchlist_zero_catalyst_crowded_close_strength_min": 0.94,
            "watchlist_zero_catalyst_crowded_layer_c_alignment_min": 0.78,
            "watchlist_zero_catalyst_crowded_sector_resonance_min": 0.42,
        }
    ):
        crowded_result = evaluate_short_trade_rejected_target(trade_date="20260328", entry=crowded_entry, rank_hint=1)

    assert crowded_result.metrics_payload["watchlist_zero_catalyst_crowded_penalty"] == 0.06
    assert crowded_result.metrics_payload["watchlist_zero_catalyst_crowded_guard"]["applied"] is True
    assert "watchlist_zero_catalyst_crowded_penalty_applied" in crowded_result.negative_tags
    assert crowded_result.score_target < baseline_result.score_target


def test_watchlist_zero_catalyst_flat_trend_penalty_targets_low_trend_zero_catalyst_watchlist_case() -> None:
    low_trend_entry = {
        "ticker": "300724",
        "score_b": 1.0,
        "score_c": 0.8,
        "score_final": 0.44,
        "quality_score": 0.66,
        "decision": "watch",
        "reason": "watchlist_selected",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                78.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 25.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 40.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 18.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.60, "investor": 0.40}},
        "candidate_source": "layer_c_watchlist",
    }
    high_trend_control_entry = {
        **low_trend_entry,
        "ticker": "000792",
        "strategy_signals": {
            **low_trend_entry["strategy_signals"],
            "trend": _make_signal(
                1,
                78.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 40.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 18.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
        },
    }

    with use_short_trade_target_profile(
        overrides={
            "watchlist_zero_catalyst_flat_trend_penalty": 0.03,
            "watchlist_zero_catalyst_flat_trend_catalyst_freshness_max": 0.05,
            "watchlist_zero_catalyst_flat_trend_close_strength_min": 0.945,
            "watchlist_zero_catalyst_flat_trend_layer_c_alignment_min": 0.75,
            "watchlist_zero_catalyst_flat_trend_sector_resonance_min": 0.388,
            "watchlist_zero_catalyst_flat_trend_trend_acceleration_max": 0.66,
        }
    ):
        low_trend_result = evaluate_short_trade_rejected_target(trade_date="20260328", entry=low_trend_entry, rank_hint=1)
        high_trend_control_result = evaluate_short_trade_rejected_target(trade_date="20260328", entry=high_trend_control_entry, rank_hint=1)

    assert low_trend_result.metrics_payload["watchlist_zero_catalyst_flat_trend_penalty"] == 0.03
    assert low_trend_result.metrics_payload["watchlist_zero_catalyst_flat_trend_guard"]["applied"] is True
    assert "watchlist_zero_catalyst_flat_trend_penalty_applied" in low_trend_result.negative_tags
    assert low_trend_result.metrics_payload["trend_acceleration"] <= 0.66
    assert high_trend_control_result.metrics_payload["watchlist_zero_catalyst_flat_trend_penalty"] == 0.0
    assert high_trend_control_result.metrics_payload["watchlist_zero_catalyst_flat_trend_guard"]["applied"] is False
    assert high_trend_control_result.metrics_payload["trend_acceleration"] > 0.66


def test_t_plus_2_continuation_candidate_tags_mid_alignment_low_catalyst_watchlist_case() -> None:
    continuation_entry = {
        "ticker": "600988",
        "score_b": 0.7668,
        "score_c": -0.054,
        "score_final": 0.3657,
        "quality_score": 0.58,
        "decision": "watch",
        "reason": "watchlist_selected",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                72.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 35.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 92.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 38.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 15.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                30.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 8.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 6.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.12, "investor": 0.02}},
        "candidate_source": "layer_c_watchlist",
    }
    crowded_control_entry = {
        **continuation_entry,
        "ticker": "300724",
        "score_c": 0.8,
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.60, "investor": 0.40}},
    }
    high_close_control_entry = {
        **continuation_entry,
        "ticker": "002001",
        "score_b": 0.99,
        "score_c": 0.12,
        "strategy_signals": {
            **continuation_entry["strategy_signals"],
            "trend": _make_signal(
                1,
                86.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 92.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 96.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 38.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 15.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.14, "investor": 0.03}},
    }

    with use_short_trade_target_profile(profile_name="watchlist_zero_catalyst_guard_relief"):
        continuation_result = evaluate_short_trade_rejected_target(trade_date="20260328", entry=continuation_entry, rank_hint=1)
        crowded_control_result = evaluate_short_trade_rejected_target(trade_date="20260328", entry=crowded_control_entry, rank_hint=1)
        high_close_control_result = evaluate_short_trade_rejected_target(trade_date="20260328", entry=high_close_control_entry, rank_hint=1)

    assert continuation_result.metrics_payload["t_plus_2_continuation_candidate"]["applied"] is True
    assert "t_plus_2_continuation_candidate" in continuation_result.positive_tags
    assert continuation_result.metrics_payload["watchlist_zero_catalyst_penalty"] == 0.0
    assert continuation_result.metrics_payload["thresholds"]["t_plus_2_continuation_enabled"] is True
    assert continuation_result.metrics_payload["thresholds"]["t_plus_2_continuation_trend_acceleration_max"] == 0.6
    assert continuation_result.metrics_payload["thresholds"]["t_plus_2_continuation_close_strength_max"] == 0.9
    assert crowded_control_result.metrics_payload["t_plus_2_continuation_candidate"]["applied"] is False
    assert high_close_control_result.metrics_payload["t_plus_2_continuation_candidate"]["applied"] is False


def test_build_selection_targets_merges_rejected_and_supplemental_short_trade_for_same_ticker() -> None:
    trend_signal = _make_signal(
        1,
        84.0,
        sub_factors={
            "momentum": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
            "adx_strength": {"direction": 1, "confidence": 81.0, "completeness": 1.0},
            "ema_alignment": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
            "volatility": {"direction": 1, "confidence": 62.0, "completeness": 1.0},
            "long_trend_alignment": {"direction": 1, "confidence": 32.0, "completeness": 1.0},
        },
    )
    event_signal = _make_signal(
        1,
        75.0,
        sub_factors={
            "event_freshness": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
            "news_sentiment": {"direction": 1, "confidence": 68.0, "completeness": 1.0},
        },
    )

    rejected_entry = {
        "ticker": "000960",
        "score_b": 0.4099,
        "score_c": -0.0329,
        "score_final": 0.1947,
        "quality_score": 0.5,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "reason": "decision_avoid",
        "reasons": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "candidate_source": "watchlist_filter_diagnostics",
        "strategy_signals": {
            "trend": trend_signal.model_dump(mode="json"),
            "event_sentiment": event_signal.model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 8.0).model_dump(mode="json"),
            "fundamental": _make_signal(1, 45.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0152, "investor": -0.0481}},
    }
    supplemental_entry = {
        **rejected_entry,
        "bc_conflict": None,
        "reason": "watchlist_avoid_shadow_release",
        "reasons": ["watchlist_avoid_shadow_release", "watchlist_avoid_shadow_release_boundary_pass", "decision_avoid"],
        "candidate_source": "watchlist_avoid_shadow_release",
        "candidate_reason_codes": ["watchlist_avoid_shadow_release", "watchlist_avoid_shadow_release_boundary_pass", "decision_avoid"],
        "shadow_release_reason": "watchlist_avoid_shadow_release_boundary_pass",
        "source_bc_conflict": "b_positive_c_strong_bearish",
    }

    selection_targets, summary = build_selection_targets(
        trade_date="20260328",
        watchlist=[],
        rejected_entries=[rejected_entry],
        supplemental_short_trade_entries=[supplemental_entry],
        target_mode="dual_target",
    )

    assert selection_targets["000960"].research is not None
    assert selection_targets["000960"].research.decision == "rejected"
    assert selection_targets["000960"].short_trade is not None
    assert selection_targets["000960"].short_trade.decision in {"selected", "near_miss"}
    assert selection_targets["000960"].candidate_source == "watchlist_filter_diagnostics"
    assert "watchlist_avoid_shadow_release" in selection_targets["000960"].candidate_reason_codes
    assert summary.research_target_count == 1
    assert summary.short_trade_target_count == 1
    assert summary.short_trade_blocked_count == 0


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
    guard_relief_profile = get_short_trade_target_profile("watchlist_zero_catalyst_guard_relief")

    assert conservative_profile.select_threshold > default_profile.select_threshold > aggressive_profile.select_threshold
    assert conservative_profile.layer_c_avoid_penalty > default_profile.layer_c_avoid_penalty > aggressive_profile.layer_c_avoid_penalty
    assert conservative_profile.stale_score_penalty_weight > default_profile.stale_score_penalty_weight > aggressive_profile.stale_score_penalty_weight
    assert guard_relief_profile.select_threshold < aggressive_profile.select_threshold
    assert guard_relief_profile.watchlist_zero_catalyst_penalty == 0.12
    assert guard_relief_profile.watchlist_zero_catalyst_crowded_penalty == 0.06
    assert guard_relief_profile.watchlist_zero_catalyst_crowded_close_strength_min == 0.938
    assert guard_relief_profile.watchlist_zero_catalyst_flat_trend_penalty == 0.03
    assert guard_relief_profile.watchlist_zero_catalyst_flat_trend_trend_acceleration_max == 0.66
    assert guard_relief_profile.t_plus_2_continuation_enabled is True
    assert guard_relief_profile.t_plus_2_continuation_trend_acceleration_max == 0.60
    assert guard_relief_profile.t_plus_2_continuation_close_strength_max == 0.90
    assert guard_relief_profile.t_plus_2_continuation_sector_resonance_max == 0.20
    assert default_profile.visibility_gap_continuation_relief_enabled is True
    assert default_profile.visibility_gap_continuation_breakout_freshness_min == 0.32
    assert default_profile.visibility_gap_continuation_trend_acceleration_min == 0.78
    assert default_profile.visibility_gap_continuation_close_strength_min == 0.88
    assert default_profile.visibility_gap_continuation_catalyst_freshness_floor == 0.35
    assert default_profile.visibility_gap_continuation_near_miss_threshold == 0.44
    assert default_profile.visibility_gap_continuation_require_relaxed_band is True
    assert guard_relief_profile.hard_block_bearish_conflicts == frozenset()


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


def test_prepared_breakout_penalty_relief_softens_narrow_watchlist_case() -> None:
    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260326",
        entry=_make_prepared_breakout_penalty_relief_entry(),
        profile_name="default",
        profile_overrides={
            "prepared_breakout_penalty_relief_enabled": False,
            "prepared_breakout_continuation_relief_enabled": False,
        },
    )
    relieved_result = evaluate_short_trade_rejected_target(
        trade_date="20260326",
        entry=_make_prepared_breakout_penalty_relief_entry(),
        profile_name="default",
        profile_overrides={"prepared_breakout_continuation_relief_enabled": False},
    )

    assert baseline_result.decision == "rejected"
    assert relieved_result.decision == "rejected"
    assert relieved_result.score_target > baseline_result.score_target
    assert relieved_result.metrics_payload["prepared_breakout_penalty_relief"]["enabled"] is True
    assert relieved_result.metrics_payload["prepared_breakout_penalty_relief"]["eligible"] is True
    assert relieved_result.metrics_payload["prepared_breakout_penalty_relief"]["applied"] is True
    assert relieved_result.metrics_payload["prepared_breakout_penalty_relief"]["gate_hits"]["prepared_breakout_stage"] is True
    assert relieved_result.metrics_payload["prepared_breakout_penalty_relief"]["effective_stale_score_penalty_weight"] == 0.06
    assert relieved_result.metrics_payload["prepared_breakout_penalty_relief"]["effective_extension_score_penalty_weight"] == 0.04
    assert relieved_result.metrics_payload["thresholds"]["effective_positive_score_weights"]["layer_c_alignment"] == 0.22
    assert "prepared_breakout_penalty_relief_applied" in relieved_result.positive_tags
    assert "prepared_breakout_penalty_relief" in relieved_result.top_reasons


def test_prepared_breakout_catalyst_relief_carries_minimum_catalyst_floor_for_narrow_watchlist_case() -> None:
    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260326",
        entry=_make_prepared_breakout_penalty_relief_entry(),
        profile_name="default",
        profile_overrides={
            "prepared_breakout_catalyst_relief_enabled": False,
            "prepared_breakout_selected_catalyst_relief_enabled": False,
        },
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260326",
        entry=_make_prepared_breakout_penalty_relief_entry(),
        profile_name="default",
        profile_overrides={"prepared_breakout_selected_catalyst_relief_enabled": False},
    )

    assert relief_result.score_target > baseline_result.score_target
    assert relief_result.metrics_payload["prepared_breakout_catalyst_relief"]["enabled"] is True
    assert relief_result.metrics_payload["prepared_breakout_catalyst_relief"]["eligible"] is True
    assert relief_result.metrics_payload["prepared_breakout_catalyst_relief"]["applied"] is True
    assert relief_result.metrics_payload["effective_catalyst_freshness"] == 0.35
    assert relief_result.metrics_payload["prepared_breakout_catalyst_relief"]["effective_catalyst_freshness"] == 0.35
    assert relief_result.metrics_payload["prepared_breakout_catalyst_relief"]["gate_hits"]["prepared_breakout_stage"] is True
    assert "prepared_breakout_catalyst_relief_applied" in relief_result.positive_tags
    assert "prepared_breakout_catalyst_relief" in relief_result.top_reasons
    assert relief_result.explainability_payload["prepared_breakout_catalyst_relief"]["applied"] is True


def test_prepared_breakout_volume_relief_carries_hidden_volatility_expansion_for_narrow_watchlist_case() -> None:
    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260326",
        entry=_make_prepared_breakout_penalty_relief_entry(),
        profile_name="default",
        profile_overrides={
            "prepared_breakout_volume_relief_enabled": False,
            "prepared_breakout_continuation_relief_enabled": False,
        },
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260326",
        entry=_make_prepared_breakout_penalty_relief_entry(),
        profile_name="default",
        profile_overrides={"prepared_breakout_continuation_relief_enabled": False},
    )

    assert relief_result.score_target > baseline_result.score_target
    assert relief_result.metrics_payload["prepared_breakout_volume_relief"]["enabled"] is True
    assert relief_result.metrics_payload["prepared_breakout_volume_relief"]["eligible"] is True
    assert relief_result.metrics_payload["prepared_breakout_volume_relief"]["applied"] is True
    assert relief_result.metrics_payload["volume_expansion_quality"] == 0.35
    assert relief_result.metrics_payload["prepared_breakout_volume_relief"]["effective_volume_expansion_quality"] == 0.35
    assert relief_result.metrics_payload["prepared_breakout_volume_relief"]["volatility_regime"] == 1.2639
    assert relief_result.metrics_payload["prepared_breakout_volume_relief"]["atr_ratio"] == 0.0988
    assert "prepared_breakout_volume_relief_applied" in relief_result.positive_tags
    assert relief_result.explainability_payload["prepared_breakout_volume_relief"]["applied"] is True


def test_prepared_breakout_continuation_relief_restores_breakout_and_trend_expression_for_pullback_case() -> None:
    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260326",
        entry=_make_prepared_breakout_penalty_relief_entry(),
        profile_name="default",
        profile_overrides={
            "prepared_breakout_continuation_relief_enabled": False,
            "prepared_breakout_selected_catalyst_relief_enabled": False,
        },
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260326",
        entry=_make_prepared_breakout_penalty_relief_entry(),
        profile_name="default",
        profile_overrides={"prepared_breakout_selected_catalyst_relief_enabled": False},
    )

    assert baseline_result.decision == "rejected"
    assert relief_result.score_target > baseline_result.score_target
    assert relief_result.decision == "near_miss"
    assert relief_result.metrics_payload["prepared_breakout_continuation_relief"]["enabled"] is True
    assert relief_result.metrics_payload["prepared_breakout_continuation_relief"]["eligible"] is True
    assert relief_result.metrics_payload["prepared_breakout_continuation_relief"]["applied"] is True
    assert relief_result.metrics_payload["breakout_freshness"] == 0.24
    assert relief_result.metrics_payload["trend_acceleration"] == 0.78
    assert relief_result.metrics_payload["prepared_breakout_continuation_relief"]["continuation_support"] == 0.4636
    assert relief_result.metrics_payload["prepared_breakout_continuation_relief"]["gate_hits"]["momentum_1m_pullback"] is True
    assert "prepared_breakout_continuation_relief_applied" in relief_result.positive_tags
    assert relief_result.explainability_payload["prepared_breakout_continuation_relief"]["applied"] is True


def test_prepared_breakout_selected_catalyst_relief_promotes_narrow_near_miss_case_to_selected() -> None:
    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260326",
        entry=_make_prepared_breakout_penalty_relief_entry(),
        profile_name="default",
        profile_overrides={"prepared_breakout_selected_catalyst_relief_enabled": False},
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260326",
        entry=_make_prepared_breakout_penalty_relief_entry(),
        profile_name="default",
    )

    assert baseline_result.decision == "near_miss"
    assert relief_result.score_target > baseline_result.score_target
    assert relief_result.decision == "selected"
    assert relief_result.metrics_payload["prepared_breakout_selected_catalyst_relief"]["enabled"] is True
    assert relief_result.metrics_payload["prepared_breakout_selected_catalyst_relief"]["eligible"] is True
    assert relief_result.metrics_payload["prepared_breakout_selected_catalyst_relief"]["applied"] is True
    assert relief_result.metrics_payload["breakout_freshness"] == 0.35
    assert relief_result.metrics_payload["effective_catalyst_freshness"] == 1.0
    assert relief_result.metrics_payload["selected_breakout_gate_pass"] is True
    assert "prepared_breakout_selected_catalyst_relief_applied" in relief_result.positive_tags
    assert relief_result.explainability_payload["prepared_breakout_selected_catalyst_relief"]["applied"] is True


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


def test_upstream_shadow_catalyst_relief_promotes_strong_recalled_shadow_to_near_miss() -> None:
    baseline_entry = _make_upstream_shadow_catalyst_relief_entry()
    relief_entry = _make_upstream_shadow_catalyst_relief_entry()

    baseline_entry.pop("short_trade_catalyst_relief", None)
    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=baseline_entry,
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=relief_entry,
    )

    assert baseline_result.decision == "rejected"
    assert round(baseline_result.score_target, 4) == 0.4362
    assert baseline_result.metrics_payload["catalyst_freshness"] == 0.0
    assert baseline_result.metrics_payload["effective_catalyst_freshness"] == 0.0
    assert relief_result.decision == "near_miss"
    assert round(relief_result.score_target, 4) == 0.5246
    assert relief_result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is True
    assert relief_result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.45
    assert relief_result.metrics_payload["effective_catalyst_freshness"] == 1.0
    assert relief_result.explainability_payload["upstream_shadow_catalyst_relief"]["applied"] is True


def test_upstream_shadow_catalyst_relief_can_promote_post_gate_shadow_to_selected() -> None:
    entry = _make_upstream_shadow_catalyst_relief_entry()
    entry["short_trade_catalyst_relief"]["selected_threshold"] = 0.45

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision == "selected"
    assert round(result.score_target, 4) == 0.5246
    assert result.metrics_payload["thresholds"]["effective_select_threshold"] == 0.45
    assert result.metrics_payload["thresholds"]["upstream_shadow_catalyst_relief_select_threshold_override"] == 0.45
    assert result.explainability_payload["upstream_shadow_catalyst_relief"]["effective_select_threshold"] == 0.45


def test_upstream_shadow_catalyst_relief_keeps_profitability_hard_cliff_sample_rejected() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_upstream_shadow_catalyst_relief_entry(include_profitability_hard_cliff=True),
    )

    assert result.decision == "rejected"
    assert round(result.score_target, 4) == 0.4362
    assert result.metrics_payload["profitability_hard_cliff"] is True
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is False
    assert result.metrics_payload["upstream_shadow_catalyst_relief_gate_hits"]["no_profitability_hard_cliff"] is False
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.46
    assert "upstream_shadow_catalyst_relief_not_triggered" in result.negative_tags


def test_upstream_shadow_catalyst_relief_can_promote_corridor_profitability_hard_cliff_sample_when_gate_relaxed() -> None:
    entry = _make_upstream_shadow_catalyst_relief_entry(include_profitability_hard_cliff=True)
    entry["short_trade_catalyst_relief"]["require_no_profitability_hard_cliff"] = False

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision == "near_miss"
    assert round(result.score_target, 4) == 0.5246
    assert result.metrics_payload["profitability_hard_cliff"] is True
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is True
    assert result.metrics_payload["upstream_shadow_catalyst_relief_gate_hits"]["no_profitability_hard_cliff"] is True
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.45


def test_visibility_gap_continuation_relief_promotes_selected_visibility_gap_shadow_to_near_miss() -> None:
    entry = _make_upstream_shadow_catalyst_relief_entry()
    entry.pop("short_trade_catalyst_relief", None)
    entry["candidate_source"] = "post_gate_liquidity_competition_shadow"
    entry["candidate_pool_lane"] = "post_gate_liquidity_competition"
    entry["candidate_pool_shadow_reason"] = "upstream_base_liquidity_uplift_shadow_visibility_gap_relaxed_band"
    entry["shadow_visibility_gap_selected"] = True
    entry["shadow_visibility_gap_relaxed_band"] = True
    entry["score_b"] = 0.40

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision == "near_miss"
    assert round(result.score_target, 4) == 0.4754
    assert "visibility_gap_continuation_relief_applied" in result.positive_tags
    assert result.metrics_payload["effective_catalyst_freshness"] == 0.35
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.44
    assert result.metrics_payload["visibility_gap_continuation_relief"]["applied"] is True
    assert result.metrics_payload["visibility_gap_continuation_relief"]["gate_hits"]["relaxed_band"] is True
    assert result.explainability_payload["visibility_gap_continuation_relief"]["applied"] is True


def test_visibility_gap_continuation_relief_requires_relaxed_band_when_profile_demands_it() -> None:
    entry = _make_upstream_shadow_catalyst_relief_entry()
    entry.pop("short_trade_catalyst_relief", None)
    entry["candidate_source"] = "post_gate_liquidity_competition_shadow"
    entry["candidate_pool_lane"] = "post_gate_liquidity_competition"
    entry["candidate_pool_shadow_reason"] = "upstream_base_liquidity_uplift_shadow"
    entry["shadow_visibility_gap_selected"] = True
    entry["shadow_visibility_gap_relaxed_band"] = False
    entry["score_b"] = 0.40

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision == "rejected"
    assert round(result.score_target, 4) == 0.4390
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.46
    assert result.metrics_payload["visibility_gap_continuation_relief"]["applied"] is False
    assert result.metrics_payload["visibility_gap_continuation_relief"]["gate_hits"]["relaxed_band"] is False
