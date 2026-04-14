from src.execution.models import ExecutionPlan, LayerCResult
from src.screening.models import StrategySignal
from src.targets import get_short_trade_target_profile, use_short_trade_target_profile
from src.targets.router import build_selection_targets
from src.targets.short_trade_target import (
    _resolve_selected_score_tolerance,
    evaluate_short_trade_rejected_target,
    evaluate_short_trade_selected_target,
)


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


def _make_profitability_hard_cliff_boundary_frontier_entry(*, catalyst_ready: bool = True) -> dict:
    event_signal = {
        "direction": 1 if catalyst_ready else 0,
        "confidence": 60.0 if catalyst_ready else 20.0,
        "completeness": 0.56 if catalyst_ready else 0.2,
        "sub_factors": {
            "news_sentiment": {
                "name": "news_sentiment",
                "direction": 1 if catalyst_ready else 0,
                "confidence": 60.0 if catalyst_ready else 20.0,
                "completeness": 1.0 if catalyst_ready else 0.2,
                "weight": 0.55,
                "metrics": {"weighted_score": 0.63 if catalyst_ready else 0.2, "recent_articles": 2 if catalyst_ready else 0, "articles": []},
            },
            "insider_conviction": {"name": "insider_conviction", "direction": 0, "confidence": 0.0, "completeness": 0.0, "weight": 0.25, "metrics": {}},
            "event_freshness": {
                "name": "event_freshness",
                "direction": 1 if catalyst_ready else 0,
                "confidence": 35.0 if catalyst_ready else 0.0,
                "completeness": 1.0 if catalyst_ready else 0.0,
                "weight": 0.2,
                "metrics": {"days_old": 0, "decay": 1.0, "positive_hits": 1 if catalyst_ready else 0, "negative_hits": 0},
            },
        },
    }
    return {
        "ticker": "300620",
        "score_b": -0.0293,
        "score_c": 0.0,
        "score_final": -0.0293,
        "quality_score": 0.5,
        "decision": "neutral",
        "reason": "short_trade_candidate_score_ranked",
        "reasons": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
        "candidate_source": "short_trade_boundary",
        "candidate_reason_codes": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
        "agent_contribution_summary": {},
        "strategy_signals": {
            "trend": {
                "direction": 1,
                "confidence": 21.521211971978577,
                "completeness": 1.0,
                "sub_factors": {
                    "ema_alignment": {"name": "ema_alignment", "direction": 1, "confidence": 92.70779321104632, "completeness": 1.0, "weight": 0.26, "metrics": {"ema_10": 164.7230631412387, "ema_30": 163.7076129143532, "ema_60": 158.05811447171016}},
                    "adx_strength": {"name": "adx_strength", "direction": 0, "confidence": 18.28071015676836, "completeness": 1.0, "weight": 0.21, "metrics": {"adx": 18.28071015676836, "+di": 30.33713163411284, "-di": 16.538920044841777}},
                    "momentum": {"name": "momentum", "direction": 1, "confidence": 100.0, "completeness": 1.0, "weight": 0.21, "metrics": {"momentum_1m": 0.07418125759039773, "momentum_3m": 0.18382231866987664, "momentum_6m": 0.9037767209678704, "volume_momentum": 1.5506305604559099}},
                    "volatility": {"name": "volatility", "direction": 0, "confidence": 50.0, "completeness": 1.0, "weight": 0.17, "metrics": {"historical_volatility": 0.782107599546619, "volatility_regime": 0.9232240537212402, "volatility_z_score": -0.3489133515347444, "atr_ratio": 0.07206842009045314}},
                    "long_trend_alignment": {"name": "long_trend_alignment", "direction": 1, "confidence": 95.2959858142346, "completeness": 1.0, "weight": 0.15, "metrics": {"ema_10": 164.7230631412387, "ema_200": 121.90419431525774}},
                },
            },
            "mean_reversion": {
                "direction": -1,
                "confidence": 11.106141927976662,
                "completeness": 1.0,
                "sub_factors": {
                    "zscore_bbands": {"name": "zscore_bbands", "direction": 0, "confidence": 50.0, "completeness": 1.0, "weight": 0.35, "metrics": {"z_score": 1.6085358749401812, "price_vs_bb": 1.010904139449355, "rsi_14": 56.551938627410316, "rsi_28": 50.513722087766574}},
                    "rsi_extreme": {"name": "rsi_extreme", "direction": 0, "confidence": 50.0, "completeness": 1.0, "weight": 0.2, "metrics": {"rsi_14": 56.551938627410316, "rsi_28": 50.513722087766574}},
                    "stat_arb": {"name": "stat_arb", "direction": 0, "confidence": 50.0, "completeness": 1.0, "weight": 0.25, "metrics": {"hurst_exponent": 0.4270953413359266, "skewness": 0.3513953523741022, "kurtosis": 1.1146513045523037}},
                    "hurst_regime": {"name": "hurst_regime", "direction": -1, "confidence": 22.122838559533225, "completeness": 1.0, "weight": 0.2, "metrics": {"hurst_exponent": 0.4270953413359266, "z_score": 1.6085358749401812}},
                },
            },
            "fundamental": {
                "direction": -1,
                "confidence": 30.0,
                "completeness": 1.0,
                "sub_factors": {
                    "profitability": {"name": "profitability", "direction": -1, "confidence": 100.0, "completeness": 1.0, "weight": 0.25, "metrics": {"return_on_equity": 0.08140247071640379, "net_margin": 0.11986226419354493, "operating_margin": 0.11515257585764349, "available_count": 3, "positive_count": 0, "zero_pass_mode": "bearish"}},
                    "growth": {"name": "growth", "direction": 1, "confidence": 30.0, "completeness": 1.0, "weight": 0.25, "metrics": {"score": 0.65, "revenue_growth": 0.47562899999999997, "revenue_trend": -0.008633130989221357, "eps_growth": 1.631774, "eps_trend": -0.28867597142857143, "fcf_growth": None, "fcf_trend": -0.34506548123473585}},
                    "financial_health": {"name": "financial_health", "direction": 1, "confidence": 100.0, "completeness": 1.0, "weight": 0.2, "metrics": {"score": 1.0, "debt_to_equity": 0.6771, "current_ratio": 2.4825}},
                    "growth_valuation": {"name": "growth_valuation", "direction": 0, "confidence": 50.0, "completeness": 1.0, "weight": 0.15, "metrics": {"score": 0.25, "peg_ratio": 1.5479689541884976, "price_to_sales_ratio": 30.3842}},
                    "industry_pe": {"name": "industry_pe", "direction": -1, "confidence": 100.0, "completeness": 1.0, "weight": 0.15, "metrics": {"industry": "通信", "current_pe": 253.4923, "industry_pe_median": 96.693, "premium_ratio": 2.6216199724902527}},
                },
            },
            "event_sentiment": event_signal,
        },
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
            "required_execution_quality_labels": ["close_continuation"],
            "min_historical_evaluable_count": 2,
            "min_historical_next_close_positive_rate": 0.5,
            "min_historical_next_open_to_close_return_mean": 0.0,
        },
        "historical_prior": {
            "execution_quality_label": "close_continuation",
            "evaluable_count": 4,
            "next_close_positive_rate": 0.75,
            "next_open_to_close_return_mean": 0.03,
        },
        "strategy_signals": strategy_signals,
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
    }


def _make_historical_execution_relief_entry() -> dict:
    entry = _make_upstream_shadow_catalyst_relief_entry(include_profitability_hard_cliff=True)
    entry.pop("short_trade_catalyst_relief", None)
    entry["ticker"] = "300757"
    entry["candidate_source"] = "short_trade_boundary"
    entry["reason"] = "short_trade_candidate_score_ranked"
    entry["reasons"] = ["short_trade_candidate_score_ranked", "short_trade_prequalified"]
    entry["candidate_reason_codes"] = ["short_trade_candidate_score_ranked", "short_trade_prequalified"]
    entry["historical_prior"] = {
        "execution_quality_label": "gap_chase_risk",
        "entry_timing_bias": "avoid_open_chase",
        "evaluable_count": 6,
        "next_high_hit_rate_at_threshold": 0.6667,
        "next_close_positive_rate": 0.6667,
        "execution_note": "历史上更像高开后回落，避免开盘直接追价。",
    }
    return entry


def _make_catalyst_theme_short_trade_carryover_entry(*, include_profitability_hard_cliff: bool = False) -> dict:
    entry = _make_upstream_shadow_catalyst_relief_entry(include_profitability_hard_cliff=include_profitability_hard_cliff)
    entry["ticker"] = "688195"
    entry["candidate_source"] = "catalyst_theme"
    entry["reason"] = "catalyst_theme_candidate_score_ranked"
    entry["reasons"] = [
        "catalyst_theme_candidate_score_ranked",
        "catalyst_theme_research_candidate",
        "catalyst_theme_short_trade_carryover_candidate",
    ]
    entry["candidate_reason_codes"] = list(entry["reasons"])
    entry["short_trade_catalyst_relief"] = {
        "enabled": True,
        "reason": "catalyst_theme_short_trade_carryover",
        "catalyst_freshness_floor": 1.0,
        "near_miss_threshold": 0.44,
        "breakout_freshness_min": 0.35,
        "trend_acceleration_min": 0.72,
        "close_strength_min": 0.85,
        "require_no_profitability_hard_cliff": True,
    }
    entry["historical_prior"] = {
        "execution_quality_label": "close_continuation",
        "entry_timing_bias": "confirm_then_hold",
        "evaluable_count": 4,
        "next_high_hit_rate_at_threshold": 0.75,
        "next_close_positive_rate": 0.75,
        "next_open_to_close_return_mean": 0.012,
        "execution_note": "历史上更偏向确认后持有，具备可研究的收盘延续质量。",
    }
    return entry


def _make_balanced_confirmation_relief_entry() -> dict:
    entry = _make_historical_execution_relief_entry()
    entry["ticker"] = "300620"
    entry["historical_prior"] = {
        "execution_quality_label": "balanced_confirmation",
        "entry_timing_bias": "confirm_then_review",
        "evaluable_count": 6,
        "next_high_hit_rate_at_threshold": 0.6667,
        "next_close_positive_rate": 0.6667,
        "execution_note": "历史表现相对均衡，仍应坚持盘中确认后再决定是否持有。",
    }
    return entry


def _make_close_continuation_relief_entry() -> dict:
    entry = _make_historical_execution_relief_entry()
    entry["ticker"] = "003036"
    entry["historical_prior"] = {
        "execution_quality_label": "close_continuation",
        "entry_timing_bias": "confirm_then_hold",
        "evaluable_count": 2,
        "next_high_hit_rate_at_threshold": 1.0,
        "next_close_positive_rate": 1.0,
        "next_open_to_close_return_mean": 0.0457,
        "execution_note": "历史上更偏向次日收盘延续，确认后可保留 follow-through 预期。",
    }
    return entry


def _make_strong_close_continuation_selected_frontier_entry() -> dict:
    return {
        "ticker": "601869",
        "score_b": 0.20,
        "score_c": -0.40,
        "score_final": 0.05,
        "quality_score": 0.60,
        "decision": "watch",
        "reason": "short_trade_candidate_score_ranked",
        "reasons": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
        "candidate_source": "short_trade_boundary",
        "candidate_reason_codes": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
        "strategy_signals": {
            "trend": _make_signal(
                1,
                70.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 73.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 64.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 60.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 56.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 30.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                60.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 72.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 52.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(-1, 20.0).model_dump(mode="json"),
            "fundamental": _make_profitability_hard_cliff_signal().model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
        "historical_prior": {
            "execution_quality_label": "close_continuation",
            "entry_timing_bias": "confirm_then_hold",
            "evaluable_count": 4,
            "next_high_hit_rate_at_threshold": 1.0,
            "next_close_positive_rate": 1.0,
            "next_open_to_close_return_mean": 0.0917,
            "execution_note": "历史上确认后继续收盘延续，属于强 continuation 子桶。",
        },
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


def test_build_selection_targets_preserves_catalyst_theme_source_and_carryover_reason_for_short_trade_only_supplemental_entry() -> None:
    supplemental_entry = _make_catalyst_theme_short_trade_carryover_entry()

    selection_targets, summary = build_selection_targets(
        trade_date="20260328",
        watchlist=[],
        rejected_entries=[],
        supplemental_short_trade_entries=[supplemental_entry],
        target_mode="short_trade_only",
    )

    assert selection_targets["688195"].candidate_source == "catalyst_theme"
    assert "catalyst_theme_short_trade_carryover_candidate" in selection_targets["688195"].candidate_reason_codes
    assert selection_targets["688195"].short_trade is not None
    assert selection_targets["688195"].short_trade.decision in {"selected", "near_miss"}
    assert selection_targets["688195"].short_trade.explainability_payload["candidate_source"] == "catalyst_theme"
    assert selection_targets["688195"].short_trade.explainability_payload["upstream_shadow_catalyst_relief"]["reason"] == "catalyst_theme_short_trade_carryover"
    assert summary.target_mode == "short_trade_only"


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
    ).model_copy(
        update={
            "historical_prior": {
                "execution_quality_label": "close_continuation",
                "applied_scope": "same_ticker",
                "evaluable_count": 1,
                "next_close_positive_rate": 1.0,
                "next_high_hit_rate_at_threshold": 1.0,
                "next_open_to_close_return_mean": 0.021,
            }
        }
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


def test_merge_approved_continuation_relief_requires_evaluable_history() -> None:
    entry = {
        "ticker": "300720",
        "score_b": 0.74,
        "score_c": 0.31,
        "score_final": 0.55,
        "quality_score": 0.67,
        "decision": "watch",
        "reason": "watchlist_selected",
        "candidate_source": "layer_c_watchlist_merge_approved",
        "candidate_reason_codes": ["merge_approved_continuation"],
        "strategy_signals": {
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
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                74.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 66.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(-1, 20.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.22, "investor": 0.11}},
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
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

    assert result.decision in {"near_miss", "rejected"}
    assert "merge_approved_continuation_relief_applied" not in result.positive_tags
    assert result.metrics_payload["merge_approved_continuation_relief"]["applied"] is False
    assert result.metrics_payload["merge_approved_continuation_relief"]["gate_hits"]["has_evaluable_history"] is False
    assert result.metrics_payload["thresholds"]["effective_select_threshold"] == 0.90


def test_merge_approved_continuation_relief_suppresses_same_ticker_intraday_only_history() -> None:
    entry = {
        "ticker": "300720",
        "score_b": 0.74,
        "score_c": 0.31,
        "score_final": 0.55,
        "quality_score": 0.67,
        "decision": "watch",
        "reason": "watchlist_selected",
        "candidate_source": "layer_c_watchlist_merge_approved",
        "candidate_reason_codes": ["merge_approved_continuation"],
        "historical_prior": {
            "applied_scope": "same_ticker",
            "execution_quality_label": "intraday_only",
            "evaluable_count": 4,
            "next_close_positive_rate": 0.0,
        },
        "strategy_signals": {
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
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                74.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 66.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(-1, 20.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.22, "investor": 0.11}},
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
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

    assert result.decision in {"near_miss", "rejected"}
    assert "merge_approved_continuation_relief_applied" not in result.positive_tags
    assert result.metrics_payload["merge_approved_continuation_relief"]["applied"] is False
    assert result.metrics_payload["merge_approved_continuation_relief"]["gate_hits"]["historical_execution_quality"] is False
    assert result.metrics_payload["merge_approved_continuation_relief"]["historical_execution_quality_label"] == "intraday_only"
    assert result.metrics_payload["thresholds"]["effective_select_threshold"] == 0.90


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


def test_t_plus_2_continuation_candidate_suppresses_weak_same_ticker_intraday_history() -> None:
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
        "historical_prior": {
            "execution_quality_label": "intraday_only",
            "applied_scope": "same_ticker",
            "evaluable_count": 3,
            "next_close_positive_rate": 0.0,
            "next_high_hit_rate_at_threshold": 0.3333,
            "next_open_to_close_return_mean": -0.011,
        },
    }

    with use_short_trade_target_profile(profile_name="watchlist_zero_catalyst_guard_relief"):
        result = evaluate_short_trade_rejected_target(trade_date="20260328", entry=continuation_entry, rank_hint=1)

    assert result.metrics_payload["t_plus_2_continuation_candidate"]["applied"] is False
    assert result.metrics_payload["t_plus_2_continuation_candidate"]["gate_hits"]["historical_execution_quality"] is False
    assert "t_plus_2_continuation_candidate" not in result.positive_tags


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
    assert default_profile.visibility_gap_continuation_breakout_freshness_min == 0.24
    assert default_profile.visibility_gap_continuation_trend_acceleration_min == 0.60
    assert default_profile.visibility_gap_continuation_close_strength_min == 0.75
    assert default_profile.visibility_gap_continuation_catalyst_freshness_floor == 0.25
    assert default_profile.visibility_gap_continuation_near_miss_threshold == 0.34
    assert default_profile.visibility_gap_continuation_require_relaxed_band is True
    assert default_profile.selected_rank_cap == 0
    assert default_profile.near_miss_rank_cap == 0
    assert default_profile.profitability_hard_cliff_boundary_relief_trend_acceleration_min == 0.45
    assert default_profile.profitability_hard_cliff_boundary_relief_close_strength_min == 0.35
    assert default_profile.profitability_hard_cliff_boundary_relief_sector_resonance_min == 0.125
    assert default_profile.profitability_hard_cliff_boundary_relief_stale_penalty_max == 0.47
    assert default_profile.profitability_hard_cliff_boundary_relief_near_miss_threshold == 0.28
    assert guard_relief_profile.hard_block_bearish_conflicts == frozenset()


def test_short_trade_rank_threshold_tightening_raises_thresholds_for_deep_rank_entries() -> None:
    entry = _make_prepared_breakout_entry()

    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
    )
    deep_rank_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=20,
    )

    baseline_tightening = baseline_result.metrics_payload["thresholds"]["rank_threshold_tightening"]
    deep_rank_tightening = deep_rank_result.metrics_payload["thresholds"]["rank_threshold_tightening"]

    assert baseline_tightening["enabled"] is False
    assert deep_rank_tightening["enabled"] is True
    assert deep_rank_tightening["tiers"] == 2
    assert deep_rank_result.effective_select_threshold == 0.5
    assert deep_rank_result.effective_near_miss_threshold == 0.36
    assert deep_rank_result.effective_select_threshold > baseline_result.effective_select_threshold
    assert deep_rank_result.effective_near_miss_threshold > baseline_result.effective_near_miss_threshold


def test_short_trade_rank_decision_cap_rejects_deep_rank_near_miss_entries() -> None:
    entry = _make_prepared_breakout_entry()

    with use_short_trade_target_profile(
        profile_name="default",
        overrides={
            "near_miss_rank_cap": 10,
        },
    ):
        baseline_result = evaluate_short_trade_rejected_target(
            trade_date="20260328",
            entry=entry,
            rank_hint=1,
        )
        deep_rank_result = evaluate_short_trade_rejected_target(
            trade_date="20260328",
            entry=entry,
            rank_hint=20,
        )

    cap_state = deep_rank_result.metrics_payload["thresholds"]["rank_decision_cap"]
    assert baseline_result.decision == "near_miss"
    assert deep_rank_result.decision == "rejected"
    assert cap_state["enabled"] is True
    assert cap_state["near_miss_rank_cap"] == 10
    assert cap_state["near_miss_cap_exceeded"] is True
    assert "near_miss_rank_cap_exceeded" in deep_rank_result.rejection_reasons


def test_short_trade_rank_decision_cap_downgrades_selected_to_near_miss() -> None:
    entry = _make_catalyst_theme_short_trade_carryover_entry()

    with use_short_trade_target_profile(
        profile_name="default",
        overrides={
            "selected_rank_cap": 8,
            "near_miss_rank_cap": 25,
        },
    ):
        baseline_result = evaluate_short_trade_rejected_target(
            trade_date="20260328",
            entry=entry,
            rank_hint=1,
        )
        deep_rank_result = evaluate_short_trade_rejected_target(
            trade_date="20260328",
            entry=entry,
            rank_hint=20,
        )

    cap_state = deep_rank_result.metrics_payload["thresholds"]["rank_decision_cap"]
    assert baseline_result.decision == "selected"
    assert deep_rank_result.decision == "near_miss"
    assert deep_rank_result.gate_status.get("rank") == "selected_cap_exceeded"
    assert cap_state["enabled"] is True
    assert cap_state["selected_rank_cap"] == 8
    assert cap_state["selected_cap_exceeded"] is True
    assert cap_state["near_miss_cap_exceeded"] is False


def test_short_trade_market_state_threshold_adjustment_tightens_crisis_regime() -> None:
    baseline_entry = _make_prepared_breakout_entry()
    crisis_entry = _make_prepared_breakout_entry()
    crisis_entry["market_state"] = {
        "breadth_ratio": 0.32,
        "position_scale": 0.50,
    }

    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=baseline_entry,
        rank_hint=1,
    )
    crisis_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=crisis_entry,
        rank_hint=1,
    )

    adjustment = crisis_result.metrics_payload["thresholds"]["market_state_threshold_adjustment"]
    assert adjustment["enabled"] is True
    assert adjustment["risk_level"] == "crisis"
    assert crisis_result.effective_select_threshold == 0.51
    assert crisis_result.effective_near_miss_threshold == 0.36
    assert crisis_result.effective_select_threshold > baseline_result.effective_select_threshold
    assert crisis_result.effective_near_miss_threshold > baseline_result.effective_near_miss_threshold


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

    assert default_result.decision in {"rejected", "near_miss"}
    assert default_result.rejection_reasons == [] or default_result.rejection_reasons == ["score_short_below_threshold"]
    assert staged_result.decision in {"near_miss", "selected"}
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
    assert weighted_result.decision in {"near_miss", "selected"}
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

    assert baseline_result.decision in {"rejected", "near_miss"}
    assert relieved_result.decision in {"rejected", "near_miss"}
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

    assert baseline_result.decision in {"rejected", "near_miss"}
    assert relief_result.score_target > baseline_result.score_target
    assert relief_result.decision in {"near_miss", "selected"}
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

    assert baseline_result.decision in {"near_miss", "selected"}
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

    assert baseline_result.decision in {"rejected", "near_miss"}
    assert relief_result.decision in {"near_miss", "selected"}
    assert baseline_result.metrics_payload["profitability_relief_applied"] in {True, False}
    assert relief_result.metrics_payload["profitability_relief_applied"] is True
    assert relief_result.metrics_payload["profitability_hard_cliff"] is True
    assert relief_result.metrics_payload["layer_c_avoid_penalty"] == 0.04
    assert relief_result.metrics_payload["base_layer_c_avoid_penalty"] == 0.12
    assert relief_result.metrics_payload["thresholds"]["profile_name"] == "staged_breakout_profitability_relief"
    assert relief_result.metrics_payload["thresholds"]["profitability_relief_enabled"] is True
    assert relief_result.explainability_payload["profitability_relief"]["applied"] is True
    assert relief_result.candidate_source == "watchlist_filter_diagnostics"
    assert relief_result.effective_near_miss_threshold == 0.42
    assert relief_result.effective_select_threshold == 0.58
    assert relief_result.breakout_freshness == round(relief_result.metrics_payload["breakout_freshness"], 4)
    assert relief_result.trend_acceleration == round(relief_result.metrics_payload["trend_acceleration"], 4)
    assert relief_result.catalyst_freshness == round(relief_result.metrics_payload["catalyst_freshness"], 4)
    assert relief_result.weighted_positive_contributions == relief_result.metrics_payload["weighted_positive_contributions"]
    assert relief_result.weighted_negative_contributions == relief_result.metrics_payload["weighted_negative_contributions"]


def test_profitability_relief_requires_sector_resonance_confirmation() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_profitability_relief_entry(sector_resonance_ready=False),
        profile_name="staged_breakout_profitability_relief",
    )

    assert result.decision in {"rejected", "near_miss"}
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


def test_profitability_hard_cliff_boundary_relief_promotes_frontier_case_to_near_miss() -> None:
    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260324",
        entry=_make_profitability_hard_cliff_boundary_frontier_entry(),
        profile_overrides={"profitability_hard_cliff_boundary_relief_enabled": False},
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260324",
        entry=_make_profitability_hard_cliff_boundary_frontier_entry(),
    )

    assert baseline_result.decision in {"rejected", "near_miss"}
    assert 0.40 <= baseline_result.score_target < 0.46
    assert relief_result.decision in {"near_miss", "selected"}
    assert relief_result.score_target == baseline_result.score_target
    assert "profitability_hard_cliff_boundary_relief_applied" in relief_result.positive_tags
    assert relief_result.metrics_payload["profitability_hard_cliff_boundary_relief"]["applied"] is True
    assert relief_result.metrics_payload["profitability_hard_cliff_boundary_relief"]["gate_hits"]["candidate_source"] is True
    assert relief_result.metrics_payload["profitability_hard_cliff_boundary_relief"]["effective_near_miss_threshold"] == 0.28
    assert relief_result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.28
    assert relief_result.explainability_payload["profitability_hard_cliff_boundary_relief"]["applied"] is True


def test_profitability_hard_cliff_boundary_relief_requires_catalyst_confirmation() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260324",
        entry=_make_profitability_hard_cliff_boundary_frontier_entry(catalyst_ready=False),
    )

    assert result.decision in {"rejected", "near_miss"}
    assert result.metrics_payload["profitability_hard_cliff_boundary_relief"]["applied"] is False
    assert result.metrics_payload["profitability_hard_cliff_boundary_relief"]["gate_hits"]["catalyst_freshness"] is False


def test_profitability_hard_cliff_boundary_relief_rejects_weak_same_ticker_intraday_history() -> None:
    entry = _make_profitability_hard_cliff_boundary_frontier_entry()
    entry["historical_prior"] = {
        "execution_quality_label": "intraday_only",
        "applied_scope": "same_ticker",
        "evaluable_count": 3,
        "next_close_positive_rate": 0.0,
        "next_high_hit_rate_at_threshold": 0.3333,
        "next_open_to_close_return_mean": -0.011,
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260324",
        entry=entry,
    )

    assert result.decision in {"rejected", "near_miss"}
    assert result.metrics_payload["profitability_hard_cliff_boundary_relief"]["applied"] is False
    assert result.metrics_payload["profitability_hard_cliff_boundary_relief"]["gate_hits"]["historical_execution_quality"] is False
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.34


def test_historical_execution_relief_promotes_positive_gap_chase_boundary_to_near_miss() -> None:
    baseline_entry = _make_historical_execution_relief_entry()
    relieved_entry = _make_historical_execution_relief_entry()
    baseline_entry.pop("historical_prior", None)
    relieved_entry["historical_prior"]["next_open_to_close_return_mean"] = 0.01

    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=baseline_entry,
        rank_hint=1,
    )
    relieved_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=relieved_entry,
        rank_hint=1,
    )

    assert baseline_result.decision == "near_miss"
    assert relieved_result.decision == "selected"
    assert relieved_result.preferred_entry_mode == "avoid_open_chase_confirmation"
    assert relieved_result.metrics_payload["historical_execution_relief"]["applied"] is True
    assert relieved_result.metrics_payload["historical_execution_relief"]["effective_near_miss_threshold"] == 0.32
    assert relieved_result.metrics_payload["historical_execution_relief"]["effective_select_threshold"] == 0.38
    assert relieved_result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.32
    assert relieved_result.metrics_payload["thresholds"]["effective_select_threshold"] == 0.38
    assert relieved_result.explainability_payload["historical_execution_relief"]["applied"] is True


def test_historical_execution_relief_does_not_promote_gap_chase_profitability_hard_cliff_with_negative_open_to_close() -> None:
    entry = _make_historical_execution_relief_entry()
    entry["historical_prior"]["next_open_to_close_return_mean"] = -0.0056

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
    )

    assert result.decision in {"rejected", "near_miss"}
    assert result.metrics_payload["historical_execution_relief"]["applied"] is False
    assert result.metrics_payload["historical_execution_relief"]["gate_hits"]["execution_quality_support"] is False
    assert result.metrics_payload["historical_execution_relief"]["gate_hits"]["gap_chase_open_to_close_support"] is False
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.34


def test_historical_execution_relief_does_not_promote_balanced_confirmation_boundary() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_balanced_confirmation_relief_entry(),
        rank_hint=1,
    )

    assert result.decision in {"rejected", "near_miss"}
    assert result.preferred_entry_mode == "next_day_breakout_confirmation"
    assert result.metrics_payload["historical_execution_relief"]["applied"] is False
    assert result.metrics_payload["historical_execution_relief"]["gate_hits"]["execution_quality_support"] is False
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.34


def test_historical_execution_relief_promotes_strong_close_continuation_boundary_to_near_miss() -> None:
    baseline_entry = _make_close_continuation_relief_entry()
    relief_entry = _make_close_continuation_relief_entry()
    baseline_entry.pop("historical_prior", None)

    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=baseline_entry,
        rank_hint=1,
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=relief_entry,
        rank_hint=1,
    )

    assert baseline_result.decision == "near_miss"
    assert relief_result.decision == "selected"
    assert relief_result.preferred_entry_mode == "confirm_then_hold_breakout"
    assert relief_result.metrics_payload["historical_execution_relief"]["applied"] is True
    assert relief_result.metrics_payload["historical_execution_relief"]["strong_close_continuation"] is True
    assert relief_result.metrics_payload["historical_execution_relief"]["effective_near_miss_threshold"] == 0.32
    assert relief_result.metrics_payload["historical_execution_relief"]["effective_select_threshold"] == 0.37
    assert relief_result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.32
    assert relief_result.metrics_payload["thresholds"]["effective_select_threshold"] == 0.37


def test_historical_execution_relief_promotes_strong_close_continuation_boundary_without_profitability_hard_cliff() -> None:
    baseline_entry = _make_close_continuation_relief_entry()
    relief_entry = _make_close_continuation_relief_entry()
    baseline_entry.pop("historical_prior", None)
    baseline_entry["strategy_signals"]["fundamental"] = _make_signal(1, 45.0).model_dump(mode="json")
    relief_entry["strategy_signals"]["fundamental"] = _make_signal(1, 45.0).model_dump(mode="json")

    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=baseline_entry,
        rank_hint=1,
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=relief_entry,
        rank_hint=1,
    )

    assert baseline_result.decision == "near_miss"
    assert relief_result.decision == "selected"
    assert relief_result.metrics_payload["historical_execution_relief"]["applied"] is True
    assert relief_result.metrics_payload["historical_execution_relief"]["strong_close_continuation"] is True
    assert relief_result.metrics_payload["historical_execution_relief"]["gate_hits"]["profitability_hard_cliff"] is True
    assert relief_result.metrics_payload["historical_execution_relief"]["effective_select_threshold"] == 0.37


def test_historical_execution_relief_promotes_strong_close_continuation_frontier_to_selected() -> None:
    baseline_entry = _make_strong_close_continuation_selected_frontier_entry()
    relief_entry = _make_strong_close_continuation_selected_frontier_entry()

    baseline_entry["historical_prior"]["next_open_to_close_return_mean"] = 0.01
    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=baseline_entry,
        rank_hint=1,
        profile_overrides={"select_threshold": 0.90, "near_miss_threshold": 0.80},
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=relief_entry,
        rank_hint=1,
        profile_overrides={"select_threshold": 0.90, "near_miss_threshold": 0.80},
    )

    assert round(relief_result.score_target, 4) == 0.5835
    assert baseline_result.decision in {"near_miss", "selected"}
    assert baseline_result.metrics_payload["historical_execution_relief"]["strong_close_continuation"] is False
    assert baseline_result.metrics_payload["historical_execution_relief"]["effective_select_threshold"] == 0.38
    assert baseline_result.metrics_payload["thresholds"]["effective_select_threshold"] == 0.38
    assert relief_result.decision == "selected"
    assert relief_result.preferred_entry_mode == "confirm_then_hold_breakout"
    assert relief_result.metrics_payload["historical_execution_relief"]["applied"] is True
    assert relief_result.metrics_payload["historical_execution_relief"]["strong_close_continuation"] is True
    assert relief_result.metrics_payload["historical_execution_relief"]["effective_select_threshold"] == 0.37
    assert relief_result.metrics_payload["thresholds"]["effective_select_threshold"] == 0.37
    assert relief_result.explainability_payload["historical_execution_relief"]["effective_select_threshold"] == 0.37


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

    assert baseline_result.decision in {"rejected", "near_miss"}
    assert round(baseline_result.score_target, 4) == 0.4273
    assert baseline_result.metrics_payload["catalyst_freshness"] == 0.0
    assert baseline_result.metrics_payload["effective_catalyst_freshness"] == 0.0
    assert relief_result.decision in {"near_miss", "selected"}
    assert round(relief_result.score_target, 4) == 0.5536
    assert relief_result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is True
    assert relief_result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.34
    assert relief_result.metrics_payload["effective_catalyst_freshness"] == 1.0
    assert relief_result.explainability_payload["upstream_shadow_catalyst_relief"]["applied"] is True


def test_upstream_shadow_catalyst_relief_can_promote_post_gate_shadow_to_selected() -> None:
    entry = _make_upstream_shadow_catalyst_relief_entry()
    entry["candidate_source"] = "post_gate_liquidity_competition_shadow"
    entry["short_trade_catalyst_relief"]["selected_threshold"] = 0.45

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision == "selected"
    assert round(result.score_target, 4) == 0.5536
    assert result.metrics_payload["thresholds"]["effective_select_threshold"] == 0.45
    assert result.metrics_payload["thresholds"]["upstream_shadow_catalyst_relief_select_threshold_override"] == 0.45
    assert result.explainability_payload["upstream_shadow_catalyst_relief"]["effective_select_threshold"] == 0.45


def test_upstream_shadow_selected_without_historical_proof_downgrades_to_near_miss() -> None:
    entry = _make_upstream_shadow_catalyst_relief_entry()
    entry["candidate_source"] = "post_gate_liquidity_competition_shadow"
    entry.pop("short_trade_catalyst_relief", None)
    entry["historical_prior"] = {}

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        profile_overrides={"select_threshold": 0.43, "near_miss_threshold": 0.40},
    )

    assert result.decision in {"near_miss", "selected"}
    assert "selected_historical_proof_missing" in result.negative_tags
    assert result.metrics_payload["selected_historical_proof_deficiency"]["proof_missing"] is True
    assert result.explainability_payload["selected_historical_proof_deficiency"]["candidate_source"] == "post_gate_liquidity_competition_shadow"


def test_upstream_shadow_catalyst_relief_requires_close_continuation_history_support() -> None:
    entry = _make_upstream_shadow_catalyst_relief_entry()
    entry["historical_prior"] = {
        "execution_quality_label": "balanced_confirmation",
        "evaluable_count": 4,
        "next_close_positive_rate": 0.75,
        "next_open_to_close_return_mean": 0.03,
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision in {"rejected", "near_miss"}
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is False
    assert result.metrics_payload["upstream_shadow_catalyst_relief_gate_hits"]["historical_continuation_quality"] is False


def test_upstream_shadow_catalyst_relief_keeps_profitability_hard_cliff_sample_rejected() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_upstream_shadow_catalyst_relief_entry(include_profitability_hard_cliff=True),
    )

    assert result.decision in {"rejected", "near_miss"}
    assert round(result.score_target, 4) == 0.4273
    assert result.metrics_payload["profitability_hard_cliff"] is True
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is False
    assert result.metrics_payload["upstream_shadow_catalyst_relief_gate_hits"]["no_profitability_hard_cliff"] is False
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.34
    assert "upstream_shadow_catalyst_relief_not_triggered" in result.negative_tags


def test_upstream_shadow_catalyst_relief_can_promote_corridor_profitability_hard_cliff_sample_when_gate_relaxed() -> None:
    entry = _make_upstream_shadow_catalyst_relief_entry(include_profitability_hard_cliff=True)
    entry["short_trade_catalyst_relief"]["require_no_profitability_hard_cliff"] = False

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision in {"near_miss", "selected"}
    assert round(result.score_target, 4) == 0.5536
    assert result.metrics_payload["profitability_hard_cliff"] is True
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is True
    assert result.metrics_payload["upstream_shadow_catalyst_relief_gate_hits"]["no_profitability_hard_cliff"] is True
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.34


def test_catalyst_theme_short_trade_carryover_promotes_strong_close_theme_candidate_to_near_miss() -> None:
    baseline_entry = _make_catalyst_theme_short_trade_carryover_entry()
    relief_entry = _make_catalyst_theme_short_trade_carryover_entry()

    baseline_entry.pop("short_trade_catalyst_relief", None)
    baseline_entry["candidate_reason_codes"] = ["catalyst_theme_candidate_score_ranked", "catalyst_theme_research_candidate"]
    baseline_entry["reasons"] = list(baseline_entry["candidate_reason_codes"])

    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=baseline_entry,
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=relief_entry,
    )

    assert baseline_result.decision in {"rejected", "near_miss"}
    assert round(baseline_result.score_target, 4) == 0.4273
    assert relief_result.decision in {"near_miss", "selected"}
    assert round(relief_result.score_target, 4) == 0.5536
    assert "catalyst_theme_short_trade_carryover_applied" in relief_result.positive_tags
    assert relief_result.metrics_payload["upstream_shadow_catalyst_relief_reason"] == "catalyst_theme_short_trade_carryover"
    assert relief_result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.34
    assert relief_result.metrics_payload["effective_catalyst_freshness"] == 1.0
    assert relief_result.explainability_payload["upstream_shadow_catalyst_relief"]["reason"] == "catalyst_theme_short_trade_carryover"


def test_catalyst_theme_short_trade_carryover_promotes_strong_close_theme_candidate_to_selected() -> None:
    entry = _make_catalyst_theme_short_trade_carryover_entry()
    entry["historical_prior"] = {
        "execution_quality_label": "close_continuation",
        "entry_timing_bias": "confirm_then_hold",
        "evaluable_count": 3,
        "next_high_hit_rate_at_threshold": 1.0,
        "next_close_positive_rate": 1.0,
        "next_open_to_close_return_mean": 0.0393,
        "execution_note": "历史上更偏向次日收盘延续，确认后可保留 follow-through 预期。",
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision == "selected"
    assert result.preferred_entry_mode == "confirm_then_hold_breakout"
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is True
    assert result.metrics_payload["thresholds"]["effective_select_threshold"] == 0.45
    assert result.metrics_payload["thresholds"]["selected_score_tolerance"] == 0.0
    assert result.explainability_payload["upstream_shadow_catalyst_relief"]["effective_select_threshold"] == 0.45
    assert result.metrics_payload["upstream_shadow_catalyst_relief_gate_hits"]["historical_continuation_quality"] is True


def test_catalyst_theme_short_trade_carryover_requires_three_evaluable_samples_for_selected_relief() -> None:
    entry = _make_catalyst_theme_short_trade_carryover_entry()
    entry["historical_prior"] = {
        "execution_quality_label": "close_continuation",
        "entry_timing_bias": "confirm_then_hold",
        "evaluable_count": 2,
        "next_high_hit_rate_at_threshold": 1.0,
        "next_close_positive_rate": 1.0,
        "next_open_to_close_return_mean": 0.0393,
        "execution_note": "历史 close continuation 仍只有 2 个 evaluable 样本，先继续观察。",
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision in {"rejected", "near_miss"}
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is False
    assert result.metrics_payload["upstream_shadow_catalyst_relief_gate_hits"]["historical_continuation_quality"] is False
    assert result.metrics_payload["thresholds"]["effective_select_threshold"] == 0.48


def test_selected_score_tolerance_only_applies_to_strong_carryover_close_continuation() -> None:
    tolerance = _resolve_selected_score_tolerance(
        score_target=0.44934181968680575,
        effective_select_threshold=0.45,
        upstream_shadow_catalyst_relief_applied=True,
        upstream_shadow_catalyst_relief_reason="catalyst_theme_short_trade_carryover",
        historical_prior={
            "execution_quality_label": "close_continuation",
            "entry_timing_bias": "confirm_then_hold",
            "evaluable_count": 3,
            "next_high_hit_rate_at_threshold": 0.8,
            "next_close_positive_rate": 0.8,
            "next_open_to_close_return_mean": 0.02,
        },
    )

    assert tolerance == 0.001
    assert (
        _resolve_selected_score_tolerance(
            score_target=0.44934181968680575,
            effective_select_threshold=0.45,
            upstream_shadow_catalyst_relief_applied=True,
            upstream_shadow_catalyst_relief_reason="catalyst_theme_short_trade_carryover",
            historical_prior={
                "execution_quality_label": "balanced_confirmation",
                "entry_timing_bias": "confirm_then_review",
                "evaluable_count": 3,
                "next_high_hit_rate_at_threshold": 0.8,
                "next_close_positive_rate": 0.8,
                "next_open_to_close_return_mean": 0.02,
            },
        )
        == 0.0
    )
    assert (
        _resolve_selected_score_tolerance(
            score_target=0.44934181968680575,
            effective_select_threshold=0.45,
            upstream_shadow_catalyst_relief_applied=False,
            upstream_shadow_catalyst_relief_reason="catalyst_theme_short_trade_carryover",
            historical_prior={
                "execution_quality_label": "close_continuation",
                "entry_timing_bias": "confirm_then_hold",
                "next_high_hit_rate_at_threshold": 0.8,
                "next_close_positive_rate": 0.8,
                "next_open_to_close_return_mean": 0.02,
            },
        )
        == 0.0
    )
    assert (
        _resolve_selected_score_tolerance(
            score_target=0.44934181968680575,
            effective_select_threshold=0.45,
            upstream_shadow_catalyst_relief_applied=True,
            upstream_shadow_catalyst_relief_reason="catalyst_theme_short_trade_carryover",
            historical_prior={
                "execution_quality_label": "close_continuation",
                "entry_timing_bias": "confirm_then_hold",
                "evaluable_count": 2,
                "next_high_hit_rate_at_threshold": 0.8,
                "next_close_positive_rate": 0.8,
                "next_open_to_close_return_mean": 0.02,
            },
        )
        == 0.0
    )
    assert (
        _resolve_selected_score_tolerance(
            score_target=0.44934181968680575,
            effective_select_threshold=0.45,
            upstream_shadow_catalyst_relief_applied=True,
            upstream_shadow_catalyst_relief_reason="catalyst_theme_short_trade_carryover",
            historical_prior={
                "execution_quality_label": "close_continuation",
                "entry_timing_bias": "confirm_then_hold",
                "evaluable_count": 3,
                "next_high_hit_rate_at_threshold": 0.79,
                "next_close_positive_rate": 0.8,
                "next_open_to_close_return_mean": 0.02,
            },
        )
        == 0.0
    )
    assert (
        _resolve_selected_score_tolerance(
            score_target=0.44934181968680575,
            effective_select_threshold=0.45,
            upstream_shadow_catalyst_relief_applied=True,
            upstream_shadow_catalyst_relief_reason="catalyst_theme_short_trade_carryover",
            historical_prior={
                "execution_quality_label": "close_continuation",
                "entry_timing_bias": "confirm_then_hold",
                "evaluable_count": 3,
                "next_high_hit_rate_at_threshold": 0.8,
                "next_close_positive_rate": 0.79,
                "next_open_to_close_return_mean": 0.02,
            },
        )
        == 0.0
    )
    assert (
        _resolve_selected_score_tolerance(
            score_target=0.44934181968680575,
            effective_select_threshold=0.45,
            upstream_shadow_catalyst_relief_applied=True,
            upstream_shadow_catalyst_relief_reason="catalyst_theme_short_trade_carryover",
            historical_prior={
                "execution_quality_label": "close_continuation",
                "entry_timing_bias": "confirm_then_hold",
                "evaluable_count": 3,
                "next_high_hit_rate_at_threshold": 0.8,
                "next_close_positive_rate": 0.8,
                "next_open_to_close_return_mean": 0.019,
            },
        )
        == 0.0
    )


def test_catalyst_theme_short_trade_carryover_requires_candidate_reason_code() -> None:
    entry = _make_catalyst_theme_short_trade_carryover_entry()
    entry["candidate_reason_codes"] = ["catalyst_theme_candidate_score_ranked", "catalyst_theme_research_candidate"]
    entry["reasons"] = list(entry["candidate_reason_codes"])

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision in {"rejected", "near_miss"}
    assert round(result.score_target, 4) == 0.4273
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is False
    assert "catalyst_theme_short_trade_carryover_applied" not in result.positive_tags


def test_catalyst_theme_short_trade_carryover_keeps_profitability_hard_cliff_sample_rejected() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_catalyst_theme_short_trade_carryover_entry(include_profitability_hard_cliff=True),
    )

    assert result.decision != "selected"
    assert result.metrics_payload["profitability_hard_cliff"] is True
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is False
    assert result.metrics_payload["upstream_shadow_catalyst_relief_gate_hits"]["no_profitability_hard_cliff"] is False
    assert "catalyst_theme_short_trade_carryover_not_triggered" in result.negative_tags


def test_catalyst_theme_short_trade_carryover_requires_supported_historical_continuation_quality() -> None:
    entry = _make_catalyst_theme_short_trade_carryover_entry()
    entry["historical_prior"] = {
        "execution_quality_label": "unknown",
        "entry_timing_bias": "unknown",
        "evaluable_count": 0,
        "next_high_hit_rate_at_threshold": 0.0,
        "next_close_positive_rate": 0.0,
        "next_open_to_close_return_mean": 0.0,
        "execution_note": "历史执行样本不足。",
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision in {"rejected", "near_miss"}
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is False
    assert result.metrics_payload["upstream_shadow_catalyst_relief_gate_hits"]["historical_continuation_quality"] is False
    assert "catalyst_theme_short_trade_carryover_not_triggered" in result.negative_tags


def test_catalyst_theme_short_trade_carryover_does_not_trigger_for_balanced_confirmation_profile() -> None:
    entry = _make_catalyst_theme_short_trade_carryover_entry()
    entry["historical_prior"] = {
        "execution_quality_label": "balanced_confirmation",
        "entry_timing_bias": "confirm_then_review",
        "evaluable_count": 4,
        "next_high_hit_rate_at_threshold": 0.75,
        "next_close_positive_rate": 0.75,
        "next_open_to_close_return_mean": 0.012,
        "execution_note": "历史更像确认后再决定是否持有，不适合按 close continuation carryover 放宽。",
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision in {"rejected", "near_miss"}
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is False
    assert result.metrics_payload["upstream_shadow_catalyst_relief_gate_hits"]["historical_continuation_quality"] is False
    assert "catalyst_theme_short_trade_carryover_not_triggered" in result.negative_tags


def test_catalyst_theme_short_trade_carryover_uses_historical_execution_relief_for_strong_close_continuation() -> None:
    entry = _make_strong_close_continuation_selected_frontier_entry()
    entry["candidate_source"] = "catalyst_theme"
    entry["reason"] = "catalyst_theme_candidate_score_ranked"
    entry["reasons"] = [
        "catalyst_theme_candidate_score_ranked",
        "catalyst_theme_research_candidate",
        "catalyst_theme_short_trade_carryover_candidate",
    ]
    entry["candidate_reason_codes"] = list(entry["reasons"])
    entry["short_trade_catalyst_relief"] = {
        "enabled": True,
        "reason": "catalyst_theme_short_trade_carryover",
        "catalyst_freshness_floor": 1.0,
        "near_miss_threshold": 0.44,
        "breakout_freshness_min": 0.35,
        "trend_acceleration_min": 0.72,
        "close_strength_min": 0.85,
        "require_no_profitability_hard_cliff": True,
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision == "selected"
    assert round(result.score_target, 4) == 0.5835
    assert result.metrics_payload["historical_execution_relief"]["applied"] in {True, False}
    assert result.metrics_payload["historical_execution_relief"]["candidate_source"] == "catalyst_theme"
    assert result.metrics_payload["historical_execution_relief"]["execution_quality_label"] == "close_continuation"
    assert result.metrics_payload["thresholds"]["effective_select_threshold"] == 0.48
    assert result.explainability_payload["historical_execution_relief"]["effective_select_threshold"] == 0.48


def test_catalyst_theme_short_trade_carryover_historical_execution_relief_requires_three_samples() -> None:
    entry = _make_strong_close_continuation_selected_frontier_entry()
    entry["candidate_source"] = "catalyst_theme"
    entry["reason"] = "catalyst_theme_candidate_score_ranked"
    entry["reasons"] = [
        "catalyst_theme_candidate_score_ranked",
        "catalyst_theme_research_candidate",
        "catalyst_theme_short_trade_carryover_candidate",
    ]
    entry["candidate_reason_codes"] = list(entry["reasons"])
    entry["short_trade_catalyst_relief"] = {
        "enabled": True,
        "reason": "catalyst_theme_short_trade_carryover",
        "catalyst_freshness_floor": 1.0,
        "near_miss_threshold": 0.44,
        "breakout_freshness_min": 0.35,
        "trend_acceleration_min": 0.72,
        "close_strength_min": 0.85,
        "min_historical_evaluable_count": 3,
        "require_no_profitability_hard_cliff": True,
    }
    entry["historical_prior"] = {
        "execution_quality_label": "close_continuation",
        "entry_timing_bias": "confirm_then_hold",
        "evaluable_count": 2,
        "next_high_hit_rate_at_threshold": 1.0,
        "next_close_positive_rate": 1.0,
        "next_open_to_close_return_mean": 0.0917,
        "execution_note": "历史 close continuation 只有 2 个 evaluable 样本。",
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        profile_overrides={"select_threshold": 0.90, "near_miss_threshold": 0.80},
    )

    assert result.decision in {"rejected", "near_miss"}
    assert result.metrics_payload["historical_execution_relief"]["applied"] is False
    assert result.metrics_payload["historical_execution_relief"]["gate_hits"]["evaluable_count"] is False
    assert result.metrics_payload["upstream_shadow_catalyst_relief_applied"] is False
    assert result.metrics_payload["upstream_shadow_catalyst_relief_gate_hits"]["historical_continuation_quality"] is False


def test_catalyst_theme_short_trade_carryover_does_not_use_historical_execution_relief_for_gap_chase_risk() -> None:
    entry = _make_catalyst_theme_short_trade_carryover_entry()
    entry["historical_prior"] = {
        "execution_quality_label": "gap_chase_risk",
        "entry_timing_bias": "avoid_open_chase",
        "evaluable_count": 6,
        "next_high_hit_rate_at_threshold": 0.8333,
        "next_close_positive_rate": 0.8333,
        "next_open_to_close_return_mean": 0.031,
        "execution_note": "历史上更像冲高回落，不适合按题材延续逻辑放宽 carryover。",
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.metrics_payload["historical_execution_relief"]["candidate_source"] == "catalyst_theme"
    assert result.metrics_payload["historical_execution_relief"]["execution_quality_label"] == "gap_chase_risk"
    assert result.metrics_payload["historical_execution_relief"]["gate_hits"]["execution_quality_support"] is False
    assert result.metrics_payload["historical_execution_relief"]["applied"] is False


def test_catalyst_theme_short_trade_carryover_marks_broad_family_only_low_sample_as_evidence_deficient() -> None:
    entry = _make_catalyst_theme_short_trade_carryover_entry()
    entry["ticker"] = "688498"
    entry["score_b"] = 0.25
    entry["score_c"] = -0.55
    entry["score_final"] = -0.10
    entry["quality_score"] = 0.58
    entry["historical_prior"] = {
        "execution_quality_label": "close_continuation",
        "entry_timing_bias": "confirm_then_hold",
        "evaluable_count": 1,
        "next_high_hit_rate_at_threshold": 1.0,
        "next_close_positive_rate": 1.0,
        "next_open_to_close_return_mean": 0.0172,
        "same_ticker_sample_count": 1,
        "same_family_sample_count": 74,
        "same_family_source_sample_count": 0,
        "same_family_source_score_catalyst_sample_count": 0,
        "same_source_score_sample_count": 0,
        "execution_note": "历史 close-continuation 兑现次数过少，且只有 broad family 外围样本。",
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260330",
        entry=entry,
    )

    assert result.decision in {"rejected", "near_miss"}
    assert "evidence_deficient_broad_family_only" in result.negative_tags
    assert result.rejection_reasons[0] == "evidence_deficient_broad_family_only"
    assert result.metrics_payload["carryover_evidence_deficiency"]["evidence_deficient"] is True
    assert result.metrics_payload["carryover_evidence_deficiency"]["gate_hits"]["broad_family_only"] is True
    assert result.explainability_payload["carryover_evidence_deficiency"]["same_family_sample_count"] == 74


def test_catalyst_theme_short_trade_carryover_evidence_deficiency_blocks_near_miss_promotion() -> None:
    entry = _make_catalyst_theme_short_trade_carryover_entry()
    entry["ticker"] = "688498"
    entry["historical_prior"] = {
        "execution_quality_label": "close_continuation",
        "entry_timing_bias": "confirm_then_hold",
        "evaluable_count": 1,
        "next_high_hit_rate_at_threshold": 1.0,
        "next_close_positive_rate": 1.0,
        "next_open_to_close_return_mean": 0.0172,
        "same_ticker_sample_count": 1,
        "same_family_sample_count": 74,
        "same_family_source_sample_count": 0,
        "same_family_source_score_catalyst_sample_count": 0,
        "same_source_score_sample_count": 0,
        "execution_note": "历史 close-continuation 兑现次数过少，且只有 broad family 外围样本。",
    }

    with use_short_trade_target_profile(
        profile_name="default",
        overrides={"near_miss_threshold": 0.40},
    ):
        result = evaluate_short_trade_rejected_target(
            trade_date="20260330",
            entry=entry,
        )

    assert result.score_target >= result.metrics_payload["thresholds"]["near_miss_threshold"]
    assert result.decision in {"rejected", "near_miss"}
    assert result.metrics_payload["carryover_evidence_deficiency"]["evidence_deficient"] is True
    assert result.rejection_reasons[0] == "evidence_deficient_broad_family_only"


def test_visibility_gap_continuation_relief_promotes_selected_visibility_gap_shadow_to_near_miss() -> None:
    entry = _make_upstream_shadow_catalyst_relief_entry()
    entry.pop("short_trade_catalyst_relief", None)
    entry["candidate_source"] = "post_gate_liquidity_competition_shadow"
    entry["candidate_pool_lane"] = "post_gate_liquidity_competition"
    entry["candidate_pool_shadow_reason"] = "upstream_base_liquidity_uplift_shadow_visibility_gap_relaxed_band"
    entry["shadow_visibility_gap_selected"] = True
    entry["shadow_visibility_gap_relaxed_band"] = True
    entry["score_b"] = 0.40
    entry["historical_prior"] = {
        "applied_scope": "same_ticker",
        "execution_quality_label": "close_continuation",
        "evaluable_count": 1,
        "next_close_positive_rate": 1.0,
        "next_high_hit_rate_at_threshold": 1.0,
        "next_open_to_close_return_mean": 0.021,
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision in {"near_miss", "selected"}
    assert round(result.score_target, 4) == 0.4646
    assert "visibility_gap_continuation_relief_applied" in result.positive_tags
    assert result.metrics_payload["effective_catalyst_freshness"] == 0.25
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.34
    assert result.metrics_payload["visibility_gap_continuation_relief"]["applied"] is True
    assert result.metrics_payload["visibility_gap_continuation_relief"]["gate_hits"]["relaxed_band"] is True
    assert result.explainability_payload["visibility_gap_continuation_relief"]["applied"] is True


def test_visibility_gap_continuation_relief_requires_evaluable_history() -> None:
    entry = _make_upstream_shadow_catalyst_relief_entry()
    entry.pop("short_trade_catalyst_relief", None)
    entry["candidate_source"] = "post_gate_liquidity_competition_shadow"
    entry["candidate_pool_lane"] = "post_gate_liquidity_competition"
    entry["candidate_pool_shadow_reason"] = "upstream_base_liquidity_uplift_shadow_visibility_gap_relaxed_band"
    entry["shadow_visibility_gap_selected"] = True
    entry["shadow_visibility_gap_relaxed_band"] = True
    entry["score_b"] = 0.40
    entry["historical_prior"] = {}

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.metrics_payload["visibility_gap_continuation_relief"]["applied"] is False
    assert result.metrics_payload["visibility_gap_continuation_relief"]["gate_hits"]["has_evaluable_history"] is False
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.34


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

    assert result.decision in {"rejected", "near_miss"}
    assert round(result.score_target, 4) == 0.4293
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.34
    assert result.metrics_payload["visibility_gap_continuation_relief"]["applied"] is False
    assert result.metrics_payload["visibility_gap_continuation_relief"]["gate_hits"]["relaxed_band"] is False


def test_visibility_gap_continuation_relief_suppresses_same_ticker_intraday_only_history() -> None:
    entry = _make_upstream_shadow_catalyst_relief_entry()
    entry.pop("short_trade_catalyst_relief", None)
    entry["candidate_source"] = "post_gate_liquidity_competition_shadow"
    entry["candidate_pool_lane"] = "post_gate_liquidity_competition"
    entry["candidate_pool_shadow_reason"] = "upstream_base_liquidity_uplift_shadow_visibility_gap_relaxed_band"
    entry["shadow_visibility_gap_selected"] = True
    entry["shadow_visibility_gap_relaxed_band"] = True
    entry["score_b"] = 0.40
    entry["historical_prior"] = {
        "applied_scope": "same_ticker",
        "execution_quality_label": "intraday_only",
        "evaluable_count": 4,
        "next_close_positive_rate": 0.0,
    }

    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
    )

    assert result.decision in {"rejected", "near_miss"}
    assert "visibility_gap_continuation_relief_applied" not in result.positive_tags
    assert result.metrics_payload["visibility_gap_continuation_relief"]["applied"] is False
    assert result.metrics_payload["visibility_gap_continuation_relief"]["gate_hits"]["historical_execution_quality"] is False
    assert result.metrics_payload["visibility_gap_continuation_relief"]["historical_execution_quality_label"] == "intraday_only"
    assert result.metrics_payload["thresholds"]["near_miss_threshold"] == 0.34
