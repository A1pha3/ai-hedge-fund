"""Phase 4 执行层测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from src.execution.daily_pipeline import DailyPipeline, WATCHLIST_SCORE_THRESHOLD
import src.execution.daily_pipeline as daily_pipeline_module
from src.execution.crisis_handler import evaluate_crisis_response
from src.execution.layer_c_aggregator import (
    LAYER_C_AVOID_SCORE_C_THRESHOLD,
    LAYER_C_BEARISH_INVESTOR_CONTRIBUTION_SCALE,
    LAYER_C_BLEND_B_WEIGHT,
    LAYER_C_BLEND_C_WEIGHT,
    LAYER_C_INVESTOR_WEIGHT_SCALE,
    aggregate_layer_c_results,
    convert_agent_signal_to_strategy_signal,
)
import src.execution.layer_c_aggregator as layer_c_aggregator_module
from src.execution.signal_decay import apply_signal_decay
from src.execution.t1_confirmation import confirm_buy_signal
from src.execution.models import ExecutionPlan, LayerCResult
from src.portfolio.models import PositionPlan
from src.screening.models import CandidateStock, FusedScore, MarketState, MarketStateType, StrategySignal


def _fused(ticker: str, score_b: float) -> FusedScore:
    return FusedScore(
        ticker=ticker,
        score_b=score_b,
        strategy_signals={
            "trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}),
            "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}),
            "fundamental": StrategySignal(direction=1, confidence=70, completeness=1.0, sub_factors={}),
            "event_sentiment": StrategySignal(direction=1, confidence=60, completeness=1.0, sub_factors={}),
        },
        arbitration_applied=[],
        market_state=MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}),
        weights_used={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2},
        decision="strong_buy" if score_b > 0.5 else "watch",
    )


def _evaluate_default_layer_c_outcome(
    score_b: float,
    investor: float,
    analyst: float,
    other: float = 0.0,
    bearish_investor_contribution_scale: float = 1.0,
) -> dict:
    total_weight = LAYER_C_BLEND_B_WEIGHT + LAYER_C_BLEND_C_WEIGHT
    blend_b = LAYER_C_BLEND_B_WEIGHT / total_weight
    blend_c = LAYER_C_BLEND_C_WEIGHT / total_weight
    raw_investor = investor * LAYER_C_INVESTOR_WEIGHT_SCALE
    score_c_raw = raw_investor + analyst + other
    adjusted_investor = raw_investor if raw_investor >= 0 else raw_investor * bearish_investor_contribution_scale
    score_c = adjusted_investor + analyst + other
    decision = "strong_buy" if score_b > 0.50 else "watch" if score_b >= 0.35 else "neutral"
    bc_conflict = None
    if score_b > 0.50 and score_c_raw < 0:
        bc_conflict = "b_strong_buy_c_negative"
        decision = "watch"
    if score_b > 0 and score_c_raw < LAYER_C_AVOID_SCORE_C_THRESHOLD:
        bc_conflict = "b_positive_c_strong_bearish"
        decision = "avoid"
    score_final = (score_b * blend_b) + (score_c * blend_c)
    return {
        "raw_score_c": score_c_raw,
        "score_c": score_c,
        "score_final": score_final,
        "decision": decision,
        "bc_conflict": bc_conflict,
        "passes_watchlist": score_final >= WATCHLIST_SCORE_THRESHOLD and decision != "avoid",
    }


def test_layer_c_agent_conversion():
    converted = convert_agent_signal_to_strategy_signal({"signal": "bullish", "confidence": 88, "reasoning": "ok"})
    assert converted.direction == 1
    assert converted.confidence == 88
    assert converted.completeness == 1.0

    failed = convert_agent_signal_to_strategy_signal({"signal": "neutral", "confidence": 0, "reasoning": {"error": "missing"}})
    assert failed.completeness == 0.0


def test_layer_c_aggregation():
    fused = [_fused("000001", 0.60)]
    analyst_signals = {
        "aswath_damodaran_agent": {"000001": {"signal": "bearish", "confidence": 30, "reasoning": "x"}},
        "technical_analyst_agent": {"000001": {"signal": "neutral", "confidence": 50, "reasoning": "x"}},
    }
    result = aggregate_layer_c_results(fused, analyst_signals)[0]
    assert result.decision == "watch"
    assert result.bc_conflict == "b_strong_buy_c_negative"
    assert result.agent_contribution_summary["negative_agent_count"] == 1
    assert result.agent_contribution_summary["top_negative_agents"][0]["agent_id"] == "aswath_damodaran_agent"


def test_layer_c_investor_scale_tilts_equal_raw_weights_toward_analyst():
    fused = [_fused("000001", 0.60)]
    analyst_signals = {
        "aswath_damodaran_agent": {"000001": {"signal": "bullish", "confidence": 100, "reasoning": "x"}},
        "technical_analyst_agent": {"000001": {"signal": "bearish", "confidence": 100, "reasoning": "x"}},
    }
    result = aggregate_layer_c_results(
        fused,
        analyst_signals,
        agent_weights={"aswath_damodaran_agent": 1.0, "technical_analyst_agent": 1.0},
    )[0]
    assert result.score_c == pytest.approx(-0.0526, abs=1e-4)
    assert result.agent_contribution_summary["top_negative_agents"][0]["agent_id"] == "technical_analyst_agent"


def test_layer_c_bearish_investor_attenuation_keeps_raw_avoid_veto_even_if_final_score_recovers(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(layer_c_aggregator_module, "LAYER_C_BEARISH_INVESTOR_CONTRIBUTION_SCALE", 0.15)

    fused = [_fused("000001", 0.45)]
    analyst_signals = {
        "bill_ackman_agent": {"000001": {"signal": "bearish", "confidence": 100, "reasoning": "x"}},
        "technical_analyst_agent": {"000001": {"signal": "bullish", "confidence": 100, "reasoning": "x"}},
    }
    result = aggregate_layer_c_results(
        fused,
        analyst_signals,
        agent_weights={
            "bill_ackman_agent": 4.0,
            "technical_analyst_agent": 1.0,
        },
    )[0]

    assert result.decision == "avoid"
    assert result.agent_contribution_summary["raw_score_c"] == pytest.approx(-0.5652, abs=1e-4)
    assert result.score_c == pytest.approx(0.1, abs=1e-4)
    assert result.score_final == pytest.approx(0.2925, abs=1e-4)


def test_layer_c_bc_conflict_avoid():
    fused = [_fused("000001", 0.35)]
    analyst_signals = {
        "aswath_damodaran_agent": {"000001": {"signal": "bearish", "confidence": 95, "reasoning": "x"}},
        "ben_graham_agent": {"000001": {"signal": "bearish", "confidence": 95, "reasoning": "x"}},
    }
    result = aggregate_layer_c_results(fused, analyst_signals)[0]
    assert result.decision == "avoid"
    assert result.bc_conflict == "b_positive_c_strong_bearish"


def test_full_pipeline_smoke():
    calls = []

    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        calls.append((tuple(tickers), model))
        return {
            "aswath_damodaran_agent": {ticker: {"signal": "bullish", "confidence": 70, "reasoning": "ok"} for ticker in tickers},
            "technical_analyst_agent": {ticker: {"signal": "bullish", "confidence": 65, "reasoning": "ok"} for ticker in tickers},
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], base_model_name="gpt-4.1", base_model_provider="OpenAI")

    import src.execution.daily_pipeline as daily_pipeline_module

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [CandidateStock(ticker="000001", name="平安银行", industry_sw="银行", avg_volume_20d=10000, market_cap=100, listing_date="19910403")]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {"000001": {"trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}), "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}), "fundamental": StrategySignal(direction=1, confidence=75, completeness=1.0, sub_factors={}), "event_sentiment": StrategySignal(direction=1, confidence=65, completeness=1.0, sub_factors={})}}
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [_fused("000001", 0.55)]

        plan = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 500000, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch

    assert plan.layer_a_count == 1
    assert plan.layer_b_count == 1
    assert plan.layer_c_count == 1
    assert len(plan.watchlist) == 1
    assert calls[0][1] == "fast"
    assert calls[1][1] == "precise"


def test_run_post_market_emits_structured_funnel_diagnostics():
    calls = []

    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        calls.append((tuple(tickers), model))
        payload = {}
        for ticker in tickers:
            if ticker == "000002":
                payload[ticker] = {"signal": "bearish", "confidence": 95, "reasoning": "avoid"}
            else:
                payload[ticker] = {"signal": "bullish", "confidence": 80, "reasoning": "buy"}
        return {
            "aswath_damodaran_agent": payload,
            "ben_graham_agent": payload,
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], base_model_name="gpt-4.1", base_model_provider="OpenAI")

    import src.execution.daily_pipeline as daily_pipeline_module

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [
            CandidateStock(ticker="000001", name="甲", industry_sw="银行", avg_volume_20d=10000, market_cap=100, listing_date="19910403"),
            CandidateStock(ticker="000002", name="乙", industry_sw="银行", avg_volume_20d=9000, market_cap=90, listing_date="19910403"),
            CandidateStock(ticker="000003", name="丙", industry_sw="银行", avg_volume_20d=8000, market_cap=80, listing_date="19910403"),
        ]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {
            candidate.ticker: {
                "trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}),
                "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}),
                "fundamental": StrategySignal(direction=1, confidence=75, completeness=1.0, sub_factors={}),
                "event_sentiment": StrategySignal(direction=1, confidence=65, completeness=1.0, sub_factors={}),
            }
            for candidate in candidates
        }
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [
            _fused("000001", 0.60),
            _fused("000002", 0.45),
            _fused("000003", 0.20),
        ]

        plan = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 0, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch

    diagnostics = plan.risk_metrics["funnel_diagnostics"]
    assert plan.layer_a_count == 3
    assert plan.layer_b_count == 2
    assert plan.layer_c_count == 2
    assert diagnostics["counts"]["watchlist_count"] == 1
    assert diagnostics["counts"]["buy_order_count"] == 0
    assert diagnostics["filters"]["layer_b"]["reason_counts"] == {"below_fast_score_threshold": 1}
    assert diagnostics["filters"]["watchlist"]["reason_counts"] == {"decision_avoid": 1}
    assert diagnostics["filters"]["short_trade_candidates"]["candidate_count"] == 0
    assert diagnostics["filters"]["watchlist"]["tickers"][0]["agent_contribution_summary"]["negative_agent_count"] == 2
    assert diagnostics["filters"]["watchlist"]["selected_entries"][0]["agent_contribution_summary"]["positive_agent_count"] == 2
    assert diagnostics["filters"]["buy_orders"]["reason_counts"] == {"no_available_cash": 1}
    assert calls[0][1] == "fast"


def test_run_post_market_adds_boundary_short_trade_candidates_to_selection_targets():
    calls = []

    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        calls.append((tuple(tickers), model))
        payload = {ticker: {"signal": "bullish", "confidence": 80, "reasoning": "buy"} for ticker in tickers}
        return {
            "aswath_damodaran_agent": payload,
            "ben_graham_agent": payload,
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], base_model_name="gpt-4.1", base_model_provider="OpenAI", target_mode="dual_target")

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [
            CandidateStock(ticker="000001", name="甲", industry_sw="银行", avg_volume_20d=10000, market_cap=100, listing_date="19910403"),
            CandidateStock(ticker="000004", name="丁", industry_sw="银行", avg_volume_20d=9000, market_cap=90, listing_date="19910403"),
            CandidateStock(ticker="000005", name="戊", industry_sw="银行", avg_volume_20d=8000, market_cap=80, listing_date="19910403"),
        ]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {
            candidate.ticker: {
                "trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}),
                "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}),
                "fundamental": StrategySignal(direction=1, confidence=75, completeness=1.0, sub_factors={}),
                "event_sentiment": StrategySignal(direction=1, confidence=65, completeness=1.0, sub_factors={}),
            }
            for candidate in candidates
        }
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [
            _fused("000001", 0.60),
            FusedScore(
                ticker="000004",
                score_b=0.35,
                strategy_signals={
                    "trend": StrategySignal(
                        direction=1,
                        confidence=86,
                        completeness=1.0,
                        sub_factors={
                            "momentum": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                            "adx_strength": {"direction": 1, "confidence": 83.0, "completeness": 1.0},
                            "ema_alignment": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                            "volatility": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
                            "long_trend_alignment": {"direction": 0, "confidence": 18.0, "completeness": 1.0},
                        },
                    ),
                    "mean_reversion": StrategySignal(direction=-1, confidence=12, completeness=1.0, sub_factors={}),
                    "fundamental": StrategySignal(direction=1, confidence=70, completeness=1.0, sub_factors={}),
                    "event_sentiment": StrategySignal(
                        direction=1,
                        confidence=78,
                        completeness=1.0,
                        sub_factors={
                            "event_freshness": {"direction": 1, "confidence": 92.0, "completeness": 1.0},
                            "news_sentiment": {"direction": 1, "confidence": 68.0, "completeness": 1.0},
                        },
                    ),
                },
                arbitration_applied=[],
                market_state=MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}),
                weights_used={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2},
                decision="watch",
            ),
            _fused("000005", 0.20),
        ]

        plan = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 0, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch

    diagnostics = plan.risk_metrics["funnel_diagnostics"]
    assert diagnostics["filters"]["short_trade_candidates"]["candidate_count"] == 1
    assert diagnostics["filters"]["short_trade_candidates"]["selected_tickers"] == ["000004"]
    assert "000004" in plan.selection_targets
    assert plan.selection_targets["000004"].research is None
    assert plan.selection_targets["000004"].candidate_source == "short_trade_boundary"
    assert plan.selection_targets["000004"].short_trade is not None
    assert plan.selection_targets["000004"].short_trade.decision in {"selected", "near_miss"}
    assert calls[0][0] == ("000001",)


def test_run_post_market_filters_weak_boundary_candidates_before_short_trade_targets():
    calls = []

    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        calls.append((tuple(tickers), model))
        payload = {ticker: {"signal": "bullish", "confidence": 80, "reasoning": "buy"} for ticker in tickers}
        return {
            "aswath_damodaran_agent": payload,
            "ben_graham_agent": payload,
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], base_model_name="gpt-4.1", base_model_provider="OpenAI", target_mode="dual_target")

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [
            CandidateStock(ticker="000001", name="甲", industry_sw="银行", avg_volume_20d=10000, market_cap=100, listing_date="19910403"),
            CandidateStock(ticker="000004", name="丁", industry_sw="银行", avg_volume_20d=9000, market_cap=90, listing_date="19910403"),
        ]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {
            candidate.ticker: {
                "trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}),
                "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}),
                "fundamental": StrategySignal(direction=1, confidence=75, completeness=1.0, sub_factors={}),
                "event_sentiment": StrategySignal(direction=1, confidence=65, completeness=1.0, sub_factors={}),
            }
            for candidate in candidates
        }
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [
            _fused("000001", 0.60),
            _fused("000004", 0.35),
        ]

        plan = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 0, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch

    diagnostics = plan.risk_metrics["funnel_diagnostics"]
    assert diagnostics["filters"]["short_trade_candidates"]["candidate_count"] == 0
    assert diagnostics["filters"]["short_trade_candidates"]["filtered_reason_counts"] == {
        "breakout_freshness_below_short_trade_boundary_floor": 1
    }
    assert "000004" not in plan.selection_targets
    assert calls[0][0] == ("000001",)


def test_run_post_market_promotes_strong_short_trade_boundary_candidate_even_below_old_score_buffer():
    calls = []

    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        calls.append((tuple(tickers), model))
        payload = {ticker: {"signal": "bullish", "confidence": 80, "reasoning": "buy"} for ticker in tickers}
        return {
            "aswath_damodaran_agent": payload,
            "ben_graham_agent": payload,
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], base_model_name="gpt-4.1", base_model_provider="OpenAI", target_mode="dual_target")

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [
            CandidateStock(ticker="000001", name="甲", industry_sw="银行", avg_volume_20d=10000, market_cap=100, listing_date="19910403"),
            CandidateStock(ticker="000004", name="丁", industry_sw="银行", avg_volume_20d=9000, market_cap=90, listing_date="19910403"),
        ]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {
            candidate.ticker: {
                "trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}),
                "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}),
                "fundamental": StrategySignal(direction=1, confidence=75, completeness=1.0, sub_factors={}),
                "event_sentiment": StrategySignal(direction=1, confidence=65, completeness=1.0, sub_factors={}),
            }
            for candidate in candidates
        }
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [
            _fused("000001", 0.60),
            FusedScore(
                ticker="000004",
                score_b=0.24,
                strategy_signals={
                    "trend": StrategySignal(
                        direction=1,
                        confidence=90,
                        completeness=1.0,
                        sub_factors={
                            "momentum": {"direction": 1, "confidence": 95.0, "completeness": 1.0},
                            "adx_strength": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                            "ema_alignment": {"direction": 1, "confidence": 86.0, "completeness": 1.0},
                            "volatility": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                            "long_trend_alignment": {"direction": 0, "confidence": 12.0, "completeness": 1.0},
                        },
                    ),
                    "mean_reversion": StrategySignal(direction=-1, confidence=8, completeness=1.0, sub_factors={}),
                    "fundamental": StrategySignal(direction=1, confidence=68, completeness=1.0, sub_factors={}),
                    "event_sentiment": StrategySignal(
                        direction=1,
                        confidence=84,
                        completeness=1.0,
                        sub_factors={
                            "event_freshness": {"direction": 1, "confidence": 94.0, "completeness": 1.0},
                            "news_sentiment": {"direction": 1, "confidence": 72.0, "completeness": 1.0},
                        },
                    ),
                },
                arbitration_applied=[],
                market_state=MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}),
                weights_used={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2},
                decision="watch",
            ),
        ]

        plan = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 0, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch

    diagnostics = plan.risk_metrics["funnel_diagnostics"]
    assert diagnostics["filters"]["short_trade_candidates"]["candidate_count"] == 1
    assert diagnostics["filters"]["short_trade_candidates"]["selected_tickers"] == ["000004"]
    assert diagnostics["filters"]["short_trade_candidates"]["prefilter_thresholds"]["candidate_score_min"] == 0.24
    assert diagnostics["filters"]["short_trade_candidates"]["tickers"][0]["short_trade_boundary_metrics"]["candidate_score"] > 0.24
    assert plan.selection_targets["000004"].candidate_source == "short_trade_boundary"
    assert calls[0][0] == ("000001",)


def test_run_post_market_adds_catalyst_theme_candidates_without_touching_main_selection_targets():
    calls = []

    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        calls.append((tuple(tickers), model))
        payload = {ticker: {"signal": "bullish", "confidence": 80, "reasoning": "buy"} for ticker in tickers}
        return {
            "aswath_damodaran_agent": payload,
            "ben_graham_agent": payload,
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], base_model_name="gpt-4.1", base_model_provider="OpenAI", target_mode="dual_target")

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    original_build_short_trade_target_snapshot_from_entry = daily_pipeline_module.build_short_trade_target_snapshot_from_entry
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [
            CandidateStock(ticker="000001", name="甲", industry_sw="银行", avg_volume_20d=10000, market_cap=100, listing_date="19910403"),
            CandidateStock(ticker="000006", name="己", industry_sw="传媒", avg_volume_20d=9000, market_cap=90, listing_date="19910403"),
        ]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {
            candidate.ticker: {
                "trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}),
                "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}),
                "fundamental": StrategySignal(direction=1, confidence=75, completeness=1.0, sub_factors={}),
                "event_sentiment": StrategySignal(direction=1, confidence=65, completeness=1.0, sub_factors={}),
            }
            for candidate in candidates
        }
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [
            _fused("000001", 0.60),
            FusedScore(
                ticker="000006",
                score_b=0.34,
                strategy_signals={
                    "trend": StrategySignal(
                        direction=1,
                        confidence=74,
                        completeness=1.0,
                        sub_factors={
                            "momentum": {"direction": 1, "confidence": 36.0, "completeness": 1.0},
                            "adx_strength": {"direction": 1, "confidence": 32.0, "completeness": 1.0},
                            "ema_alignment": {"direction": 1, "confidence": 72.0, "completeness": 1.0},
                            "volatility": {"direction": 1, "confidence": 10.0, "completeness": 1.0},
                            "long_trend_alignment": {"direction": 0, "confidence": 12.0, "completeness": 1.0},
                        },
                    ),
                    "mean_reversion": StrategySignal(direction=-1, confidence=8, completeness=1.0, sub_factors={}),
                    "fundamental": StrategySignal(direction=1, confidence=60, completeness=1.0, sub_factors={}),
                    "event_sentiment": StrategySignal(
                        direction=1,
                        confidence=92,
                        completeness=1.0,
                        sub_factors={
                            "event_freshness": {"direction": 1, "confidence": 95.0, "completeness": 1.0},
                            "news_sentiment": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                        },
                    ),
                },
                arbitration_applied=[],
                market_state=MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2}),
                weights_used={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2},
                decision="watch",
            ),
        ]
        daily_pipeline_module.build_short_trade_target_snapshot_from_entry = lambda trade_date, entry: {
            "gate_status": {"data": "pass", "structural": "fail", "score": "proxy_only"},
            "blockers": ["stale_trend_repair_penalty"],
            "breakout_freshness": 0.31 if entry.get("ticker") == "000006" else 0.12,
            "trend_acceleration": 0.26 if entry.get("ticker") == "000006" else 0.10,
            "volume_expansion_quality": 0.12 if entry.get("ticker") == "000006" else 0.08,
            "close_strength": 0.57 if entry.get("ticker") == "000006" else 0.10,
            "sector_resonance": 0.25 if entry.get("ticker") == "000006" else 0.12,
            "catalyst_freshness": 0.82 if entry.get("ticker") == "000006" else 0.10,
        }

        plan = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 0, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch
        daily_pipeline_module.build_short_trade_target_snapshot_from_entry = original_build_short_trade_target_snapshot_from_entry

    diagnostics = plan.risk_metrics["funnel_diagnostics"]
    catalyst_diagnostics = diagnostics["filters"]["catalyst_theme_candidates"]
    assert catalyst_diagnostics["candidate_count"] == 1
    assert catalyst_diagnostics["selected_tickers"] == ["000006"]
    assert catalyst_diagnostics["tickers"][0]["candidate_source"] == "catalyst_theme"
    assert plan.risk_metrics["counts"]["catalyst_theme_candidate_count"] == 1
    assert "000006" not in plan.selection_targets
    assert calls[0][0] == ("000001",)


def test_watchlist_threshold_020_admits_edge_case_between_020_and_025():
    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        return {
            "aswath_damodaran_agent": {ticker: {"signal": "bullish", "confidence": 70, "reasoning": "ok"} for ticker in tickers},
            "technical_analyst_agent": {ticker: {"signal": "bearish", "confidence": 100, "reasoning": "ok"} for ticker in tickers},
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], base_model_name="gpt-4.1", base_model_provider="OpenAI")

    import src.execution.daily_pipeline as daily_pipeline_module

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [CandidateStock(ticker="000001", name="甲", industry_sw="银行", avg_volume_20d=10000, market_cap=100, listing_date="19910403")]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {
            "000001": {
                "trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}),
                "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}),
                "fundamental": StrategySignal(direction=1, confidence=75, completeness=1.0, sub_factors={}),
                "event_sentiment": StrategySignal(direction=1, confidence=65, completeness=1.0, sub_factors={}),
            }
        }
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [_fused("000001", 0.44)]

        plan = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 500000, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch

    assert len(plan.watchlist) == 1
    assert plan.watchlist[0].score_final == pytest.approx(0.2024, abs=1e-4)
    assert plan.watchlist[0].score_final < 0.25


@pytest.mark.parametrize(
    ("ticker", "score_b", "investor", "analyst"),
    [
        ("300699_20260202", 0.3992, -0.5557, -0.1234),
        ("600089_20260202", 0.4289, -0.5151, -0.1062),
        ("300502_20260224", 0.4078, -0.4233, -0.0409),
        ("300065_20260224", 0.3869, -0.5952, -0.0548),
        ("002602_20260224", 0.3858, -0.5392, -0.0800),
        ("600111_20260224", 0.3852, -0.3893, -0.0175),
        ("300699_20260203", 0.4116, -0.5971, -0.1234),
        ("600111_20260203", 0.3979, -0.4605, -0.0175),
    ],
)
def test_p1_defaults_keep_structural_conflict_samples_blocked(ticker: str, score_b: float, investor: float, analyst: float):
    result = _evaluate_default_layer_c_outcome(score_b, investor, analyst)
    assert result["decision"] == "avoid", ticker
    assert result["bc_conflict"] == "b_positive_c_strong_bearish", ticker
    assert result["passes_watchlist"] is False, ticker
    assert result["raw_score_c"] < LAYER_C_AVOID_SCORE_C_THRESHOLD, ticker


def test_p1_bearish_investor_attenuation_preserves_avoid_veto_for_structural_conflict_sample():
    result = _evaluate_default_layer_c_outcome(0.4078, -0.4233, -0.0409, bearish_investor_contribution_scale=0.15)

    assert result["decision"] == "avoid"
    assert result["bc_conflict"] == "b_positive_c_strong_bearish"
    assert result["raw_score_c"] == pytest.approx(-0.4219, abs=1e-4)
    assert result["score_c"] == pytest.approx(-0.0980, abs=1e-4)
    assert result["passes_watchlist"] is False


def test_p1_bearish_investor_attenuation_can_release_documented_watchlist_edge_case():
    result = _evaluate_default_layer_c_outcome(0.4360, -0.2246 / LAYER_C_INVESTOR_WEIGHT_SCALE, -0.0460, bearish_investor_contribution_scale=0.15)

    assert result["decision"] == "watch"
    assert result["raw_score_c"] == pytest.approx(-0.2706, abs=1e-4)
    assert result["score_c"] == pytest.approx(-0.0797, abs=1e-4)
    assert result["score_final"] == pytest.approx(0.2039, abs=1e-4)
    assert result["passes_watchlist"] is True


def test_p1_defaults_admit_only_stronger_600519_edge_case_from_focused_samples():
    stronger_edge = _evaluate_default_layer_c_outcome(0.4023, 0.0617, 0.0)
    weaker_edge = _evaluate_default_layer_c_outcome(0.3951, -0.1315, 0.0)

    assert stronger_edge["decision"] == "watch"
    assert stronger_edge["bc_conflict"] is None
    assert stronger_edge["passes_watchlist"] is True
    assert stronger_edge["score_final"] == pytest.approx(0.2463, abs=1e-4)

    assert weaker_edge["decision"] == "watch"
    assert weaker_edge["bc_conflict"] is None
    assert weaker_edge["passes_watchlist"] is False
    assert weaker_edge["score_final"] == pytest.approx(0.164, abs=1e-4)


def test_build_buy_orders_diagnostics_marks_daily_trade_limit():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    watchlist = [
        LayerCResult(ticker=f"00000{index}", score_c=0.4, score_final=0.4 + index / 100.0, score_b=0.5, decision="watch")
        for index in range(4)
    ]

    buy_orders, diagnostics = pipeline._build_buy_orders_with_diagnostics(watchlist, {"cash": 1_000_000, "positions": {}})

    assert len(buy_orders) == 3
    assert diagnostics["reason_counts"] == {"filtered_by_daily_trade_limit": 1}
    assert diagnostics["filtered_count"] == 1


def test_build_buy_orders_blocks_watchlist_name_below_buy_threshold_sample():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    watchlist = [
        LayerCResult(ticker="300724", score_c=-0.0792, score_final=0.2042, score_b=0.4360, decision="watch")
    ]

    buy_orders, diagnostics = pipeline._build_buy_orders_with_diagnostics(watchlist, {"cash": 100_000, "positions": {}})

    assert buy_orders == []
    assert diagnostics["reason_counts"] == {"position_blocked_score": 1}
    assert diagnostics["tickers"][0]["ticker"] == "300724"
    assert diagnostics["tickers"][0]["constraint_binding"] == "score"
    assert diagnostics["tickers"][0]["execution_ratio"] == 0.0


def test_build_buy_orders_allows_edge_watchlist_name_when_execution_score_floor_is_lowered(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PIPELINE_WATCHLIST_MIN_SCORE", "0.21")

    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    watchlist = [
        LayerCResult(ticker="600988", score_c=0.0182, score_final=0.2170, score_b=0.3798, decision="watch")
    ]
    candidate_by_ticker = {
        "600988": CandidateStock(ticker="600988", name="样本", industry_sw="电力设备", avg_volume_20d=10_000_000, market_cap=100, listing_date="19910403")
    }

    buy_orders, diagnostics = pipeline._build_buy_orders_with_diagnostics(
        watchlist,
        {"cash": 100_000, "positions": {}},
        candidate_by_ticker=candidate_by_ticker,
        price_map={"600988": 20.0},
    )

    assert len(buy_orders) == 1
    assert buy_orders[0].ticker == "600988"
    assert buy_orders[0].constraint_binding == "single_name"
    assert buy_orders[0].shares == 100
    assert diagnostics["reason_counts"] == {}


def test_build_buy_orders_uses_real_price_map_for_high_price_ticker_position_sizing():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    watchlist = [
        LayerCResult(ticker="300724", score_c=0.2, score_final=0.6, score_b=0.6, decision="watch")
    ]
    candidate_by_ticker = {
        "300724": CandidateStock(ticker="300724", name="光伏样本", industry_sw="电力设备", avg_volume_20d=10_000_000, market_cap=100, listing_date="20100520")
    }

    buy_orders, diagnostics = pipeline._build_buy_orders_with_diagnostics(
        watchlist,
        {"cash": 200_000, "positions": {}},
        candidate_by_ticker=candidate_by_ticker,
        price_map={"300724": 142.71},
    )

    assert len(buy_orders) == 1
    assert buy_orders[0].ticker == "300724"
    assert buy_orders[0].constraint_binding == "single_name"
    assert buy_orders[0].shares == 100
    assert buy_orders[0].amount == pytest.approx(14271.0)
    assert diagnostics["reason_counts"] == {}


def test_build_buy_orders_gives_higher_quality_candidate_more_size_when_scores_match():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    watchlist = [
        LayerCResult(ticker="000001", score_c=0.2, score_final=0.30, score_b=0.5, quality_score=0.9, decision="watch"),
        LayerCResult(ticker="000002", score_c=0.2, score_final=0.30, score_b=0.5, quality_score=0.1, decision="watch"),
    ]
    candidate_by_ticker = {
        "000001": CandidateStock(ticker="000001", name="高质量", industry_sw="银行", avg_volume_20d=10_000_000, market_cap=100, listing_date="19910403"),
        "000002": CandidateStock(ticker="000002", name="低质量", industry_sw="银行", avg_volume_20d=10_000_000, market_cap=100, listing_date="19910403"),
    }

    buy_orders, diagnostics = pipeline._build_buy_orders_with_diagnostics(
        watchlist,
        {"cash": 120_000, "positions": {}},
        candidate_by_ticker=candidate_by_ticker,
        price_map={"000001": 10.0, "000002": 10.0},
    )

    assert len(buy_orders) == 2
    plans_by_ticker = {plan.ticker: plan for plan in buy_orders}
    assert plans_by_ticker["000001"].execution_ratio > plans_by_ticker["000002"].execution_ratio
    assert plans_by_ticker["000001"].amount > plans_by_ticker["000002"].amount
    assert diagnostics["reason_counts"] == {}


def test_build_buy_orders_blocks_ticker_during_exit_cooldown():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    watchlist = [
        LayerCResult(ticker="300724", score_c=0.2, score_final=0.6, score_b=0.6, decision="watch")
    ]

    buy_orders, diagnostics = pipeline._build_buy_orders_with_diagnostics(
        watchlist,
        {"cash": 200_000, "positions": {}},
        trade_date="20260310",
        blocked_buy_tickers={"300724": {"trigger_reason": "hard_stop_loss", "exit_trade_date": "20260305", "blocked_until": "20260312"}},
        price_map={"300724": 142.71},
    )

    assert buy_orders == []
    assert diagnostics["reason_counts"] == {"blocked_by_exit_cooldown": 1}
    assert diagnostics["tickers"][0]["trigger_reason"] == "hard_stop_loss"
    assert diagnostics["tickers"][0]["blocked_until"] == "20260312"


def test_build_buy_orders_requires_stronger_score_after_exit_cooldown_expires():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    watchlist = [
        LayerCResult(ticker="300724", score_c=0.2, score_final=0.24, score_b=0.6, decision="watch")
    ]

    buy_orders, diagnostics = pipeline._build_buy_orders_with_diagnostics(
        watchlist,
        {"cash": 200_000, "positions": {}},
        trade_date="20260313",
        blocked_buy_tickers={
            "300724": {
                "trigger_reason": "hard_stop_loss",
                "exit_trade_date": "20260305",
                "blocked_until": "20260312",
                "reentry_review_until": "20260318",
            }
        },
        price_map={"300724": 142.71},
    )

    assert buy_orders == []
    assert diagnostics["reason_counts"] == {"blocked_by_reentry_score_confirmation": 1}
    assert diagnostics["tickers"][0]["required_score"] == 0.25


def test_build_buy_orders_allows_stronger_score_after_exit_cooldown_expires():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    watchlist = [
        LayerCResult(ticker="300724", score_c=0.2, score_final=0.26, score_b=0.6, decision="watch")
    ]

    buy_orders, diagnostics = pipeline._build_buy_orders_with_diagnostics(
        watchlist,
        {"cash": 200_000, "positions": {}},
        trade_date="20260313",
        blocked_buy_tickers={
            "300724": {
                "trigger_reason": "hard_stop_loss",
                "exit_trade_date": "20260305",
                "blocked_until": "20260312",
                "reentry_review_until": "20260318",
            }
        },
        price_map={"300724": 142.71},
    )

    assert len(buy_orders) == 1
    assert buy_orders[0].ticker == "300724"
    assert diagnostics["reason_counts"] == {}


def test_run_post_market_uses_trade_date_close_price_for_buy_order_sizing(monkeypatch: pytest.MonkeyPatch):
    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        return {
            "aswath_damodaran_agent": {ticker: {"signal": "bullish", "confidence": 100, "reasoning": "ok"} for ticker in tickers},
            "technical_analyst_agent": {ticker: {"signal": "bullish", "confidence": 100, "reasoning": "ok"} for ticker in tickers},
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], base_model_name="gpt-4.1", base_model_provider="OpenAI")

    import src.execution.daily_pipeline as daily_pipeline_module

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    original_get_daily_basic_batch = daily_pipeline_module.get_daily_basic_batch
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [
            CandidateStock(ticker="300724", name="光伏样本", industry_sw="电力设备", avg_volume_20d=10_000_000, market_cap=100, listing_date="20100520")
        ]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {
            "300724": {
                "trend": StrategySignal(direction=1, confidence=90, completeness=1.0, sub_factors={}),
                "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}),
                "fundamental": StrategySignal(direction=1, confidence=85, completeness=1.0, sub_factors={}),
                "event_sentiment": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}),
            }
        }
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [_fused("300724", 0.60)]
        daily_pipeline_module.get_daily_basic_batch = lambda trade_date: pd.DataFrame(
            [{"ts_code": "300724.SZ", "close": 142.71}]
        )

        plan = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 200_000, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch
        daily_pipeline_module.get_daily_basic_batch = original_get_daily_basic_batch

    assert len(plan.buy_orders) == 1
    assert plan.buy_orders[0].ticker == "300724"
    assert plan.buy_orders[0].shares == 100
    assert plan.buy_orders[0].amount == pytest.approx(14271.0)


def test_build_buy_orders_treats_candidate_avg_volume_as_wan_cny_when_evaluating_liquidity_blockers():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    watchlist = [
        LayerCResult(ticker="300724", score_c=-0.0350, score_final=0.2260, score_b=0.4370, decision="watch")
    ]
    candidate_by_ticker = {
        "300724": CandidateStock(
            ticker="300724",
            name="捷佳伟创",
            industry_sw="电力设备",
            avg_volume_20d=253_911.41073,
            market_cap=462.0,
            listing_date="20180810",
        )
    }

    buy_orders, diagnostics = pipeline._build_buy_orders_with_diagnostics(
        watchlist,
        {"cash": 100_000, "positions": {}},
        candidate_by_ticker=candidate_by_ticker,
        price_map={"300724": 142.71},
    )

    assert len(buy_orders) == 1
    assert buy_orders[0].ticker == "300724"
    assert buy_orders[0].constraint_binding == "single_name"
    assert buy_orders[0].shares == 100
    assert buy_orders[0].amount == pytest.approx(14271.0)
    assert diagnostics["reason_counts"] == {}


def test_build_buy_orders_respects_existing_single_name_exposure_when_position_already_large():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    watchlist = [
        LayerCResult(ticker="300724", score_c=-0.0120, score_final=0.2269, score_b=0.4330, decision="watch")
    ]
    candidate_by_ticker = {
        "300724": CandidateStock(
            ticker="300724",
            name="捷佳伟创",
            industry_sw="电力设备",
            avg_volume_20d=253_911.41073,
            market_cap=462.0,
            listing_date="20180810",
        )
    }

    buy_orders, diagnostics = pipeline._build_buy_orders_with_diagnostics(
        watchlist,
        {
            "cash": 8_718.0,
            "positions": {
                "300724": {"long": 600, "long_cost_basis": 136.4752},
                "603993": {"long": 400, "long_cost_basis": 23.4351},
            },
        },
        candidate_by_ticker=candidate_by_ticker,
        price_map={"300724": 129.61},
    )

    assert buy_orders == []
    assert diagnostics["reason_counts"] == {"position_blocked_single_name": 1}
    assert diagnostics["tickers"][0]["constraint_binding"] == "single_name"


def test_default_exit_checker_emits_hard_stop_from_position_snapshot_metadata(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        daily_pipeline_module,
        "get_daily_basic_batch",
        lambda trade_date: pd.DataFrame([{"ts_code": "300724.SZ", "close": 130.0}]),
    )

    exits = daily_pipeline_module._default_exit_checker(
        {
            "cash": 50_000,
            "positions": {
                "300724": {
                    "long": 100,
                    "short": 0,
                    "long_cost_basis": 142.924065,
                    "short_cost_basis": 0.0,
                    "short_margin_used": 0.0,
                    "entry_date": "20260203",
                    "holding_days": 5,
                    "max_unrealized_pnl_pct": 0.0,
                    "profit_take_stage": 0,
                    "entry_score": 0.22,
                    "is_fundamental_driven": False,
                    "industry_sw": "电力设备",
                }
            },
            "realized_gains": {},
        },
        "20260211",
    )

    assert len(exits) == 1
    assert exits[0].ticker == "300724"
    assert exits[0].trigger_reason == "hard_stop_loss"


def test_default_exit_checker_uses_logic_scores_when_available(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        daily_pipeline_module,
        "get_daily_basic_batch",
        lambda trade_date: pd.DataFrame([{"ts_code": "300724.SZ", "close": 142.92}]),
    )

    exits = daily_pipeline_module._default_exit_checker(
        {
            "cash": 50_000,
            "positions": {
                "300724": {
                    "long": 100,
                    "short": 0,
                    "long_cost_basis": 142.924065,
                    "short_cost_basis": 0.0,
                    "short_margin_used": 0.0,
                    "entry_date": "20260203",
                    "holding_days": 5,
                    "max_unrealized_pnl_pct": 0.0,
                    "profit_take_stage": 0,
                    "entry_score": 0.22,
                    "is_fundamental_driven": False,
                    "industry_sw": "电力设备",
                }
            },
            "realized_gains": {},
        },
        "20260211",
        {"300724": -0.25},
    )

    assert len(exits) == 1
    assert exits[0].ticker == "300724"
    assert exits[0].trigger_reason == "logic_stop_loss"


def test_signal_decay_jump_gap():
    plan = ExecutionPlan(
        date="20260305",
        buy_orders=[PositionPlan(ticker="000001", shares=1000, amount=10000, constraint_binding="cash", score_final=0.5, execution_ratio=1.0)],
    )
    updated = apply_signal_decay(plan, "20260306", atr_values={"000001": 0.02}, open_gap_pct={"000001": 0.04})
    assert len(updated.buy_orders) == 0
    assert any(alert.startswith("cancel_buy_gap_open") for alert in updated.risk_alerts)


def test_signal_decay_expiry():
    plan = ExecutionPlan(
        date="20260305",
        buy_orders=[PositionPlan(ticker="000001", shares=1000, amount=10000, constraint_binding="cash", score_final=0.5, execution_ratio=1.0)],
    )
    updated = apply_signal_decay(plan, "20260307", refreshed_scores={"000001": 0.39})
    assert len(updated.buy_orders) == 0
    assert any(alert.startswith("cancel_buy_signal_decay") for alert in updated.risk_alerts)


def test_t1_confirmation():
    result = confirm_buy_signal(
        day_low=10.0,
        ema30=10.0,
        current_price=10.3,
        vwap=10.1,
        intraday_volume=800000,
        avg_same_time_volume=900000,
        industry_percentile=0.4,
    )
    assert result["confirmed"] is True
    assert result["passed_checks"] >= 2


def test_crisis_defense_mode():
    result = evaluate_crisis_response(hs300_daily_return=-0.051, limit_down_count=100, recent_total_volumes=[6000, 6200, 6100], drawdown_pct=-0.03)
    assert result["mode"] == "defense"
    assert result["position_cap"] == 0.3


def test_low_volume_shrink_and_recovery_trigger():
    result = evaluate_crisis_response(hs300_daily_return=-0.01, limit_down_count=50, recent_total_volumes=[3900, 3800, 3700], drawdown_pct=-0.16)
    assert result["pause_new_buys"] is True
    assert result["forced_reduce_ratio"] == 0.5
    assert result["recovery_cooldown_days"] == 5


def test_crisis_limit_down_500():
    result = evaluate_crisis_response(hs300_daily_return=-0.01, limit_down_count=501, recent_total_volumes=[6000, 6200, 6100], drawdown_pct=-0.03)
    assert result["mode"] == "defense"
    assert "crisis_defense_mode" in result["alerts"]


def test_tiered_llm_call():
    calls = []

    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        calls.append((len(tickers), model))
        return {
            "aswath_damodaran_agent": {ticker: {"signal": "bullish", "confidence": 60, "reasoning": "ok"} for ticker in tickers},
        }

    pipeline = DailyPipeline(
        agent_runner=fake_agent_runner,
        exit_checker=lambda portfolio, trade_date: [],
        base_model_name="gpt-4.1",
        base_model_provider="OpenAI",
    )

    import src.execution.daily_pipeline as daily_pipeline_module

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [CandidateStock(ticker=f"{i:06d}", name=str(i), industry_sw="银行", avg_volume_20d=10000, market_cap=100, listing_date="19910403") for i in range(30)]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {candidate.ticker: {"trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}), "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}), "fundamental": StrategySignal(direction=1, confidence=75, completeness=1.0, sub_factors={}), "event_sentiment": StrategySignal(direction=1, confidence=65, completeness=1.0, sub_factors={})} for candidate in candidates}
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [_fused(ticker, 0.46 + index / 1000.0) for index, ticker in enumerate(scored.keys())]
        pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 500000, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch

    assert calls[0] == (12, "fast")
    assert calls[1] == (6, "precise")


def test_default_pipeline_runner_preserves_explicit_non_openai_provider(monkeypatch):
    calls = []

    def fake_run_hedge_fund(**kwargs):
        calls.append(kwargs)
        return {"analyst_signals": {}}

    monkeypatch.setattr("src.main.run_hedge_fund", fake_run_hedge_fund)

    pipeline = DailyPipeline(base_model_name="glm-4.7", base_model_provider="Zhipu")
    pipeline.agent_runner(["000001"], "20260305", "fast")
    pipeline.agent_runner(["000001"], "20260305", "precise")

    assert calls[0]["model_name"] == "glm-4.7"
    assert calls[0]["model_provider"] == "Zhipu"
    assert calls[0]["llm_observability"] == {"trade_date": "20260305", "pipeline_stage": "daily_pipeline_post_market", "model_tier": "fast"}
    assert calls[1]["model_name"] == "glm-4.7"
    assert calls[1]["model_provider"] == "Zhipu"
    assert calls[1]["llm_observability"] == {"trade_date": "20260305", "pipeline_stage": "daily_pipeline_post_market", "model_tier": "precise"}


def test_default_pipeline_runner_keeps_openai_fast_precise_split(monkeypatch):
    calls = []

    def fake_run_hedge_fund(**kwargs):
        calls.append(kwargs)
        return {"analyst_signals": {}}

    monkeypatch.setattr("src.main.run_hedge_fund", fake_run_hedge_fund)

    pipeline = DailyPipeline(base_model_name="gpt-4.1", base_model_provider="OpenAI")
    pipeline.agent_runner(["000001"], "20260305", "fast")
    pipeline.agent_runner(["000001"], "20260305", "precise")

    assert calls[0]["model_name"] == "gpt-4.1-mini"
    assert calls[0]["model_provider"] == "OpenAI"
    assert calls[0]["llm_observability"] == {"trade_date": "20260305", "pipeline_stage": "daily_pipeline_post_market", "model_tier": "fast"}
    assert calls[1]["model_name"] == "gpt-4.1"
    assert calls[1]["model_provider"] == "OpenAI"
    assert calls[1]["llm_observability"] == {"trade_date": "20260305", "pipeline_stage": "daily_pipeline_post_market", "model_tier": "precise"}


def test_run_post_market_skips_duplicate_precise_stage_for_non_openai():
    calls = []

    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        calls.append((tuple(tickers), model))
        return {
            "aswath_damodaran_agent": {ticker: {"signal": "bullish", "confidence": 70, "reasoning": "ok"} for ticker in tickers},
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], base_model_name="glm-4.7", base_model_provider="Zhipu")

    import src.execution.daily_pipeline as daily_pipeline_module

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [CandidateStock(ticker=f"{i:06d}", name=str(i), industry_sw="银行", avg_volume_20d=10000, market_cap=100, listing_date="19910403") for i in range(4)]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {candidate.ticker: {"trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}), "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}), "fundamental": StrategySignal(direction=1, confidence=75, completeness=1.0, sub_factors={}), "event_sentiment": StrategySignal(direction=1, confidence=65, completeness=1.0, sub_factors={})} for candidate in candidates}
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [_fused(ticker, 0.46 + index / 1000.0) for index, ticker in enumerate(scored.keys())]

        plan = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 500000, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch

    assert plan.layer_b_count == 4
    assert calls == [(("000003", "000002", "000001", "000000"), "fast")]
    assert plan.risk_metrics["timing_seconds"]["precise_agent"] == 0.0
    assert plan.risk_metrics["counts"]["precise_stage_skipped"] is True
    assert plan.risk_metrics["counts"]["skipped_precise_ticker_count"] == 4
    assert plan.risk_metrics["timing_seconds"]["estimated_skipped_precise"] >= 0.0


def test_run_post_market_keeps_precise_stage_for_openai():
    calls = []

    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        calls.append((tuple(tickers), model))
        return {
            "aswath_damodaran_agent": {ticker: {"signal": "bullish", "confidence": 70, "reasoning": "ok"} for ticker in tickers},
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], base_model_name="gpt-4.1", base_model_provider="OpenAI")

    import src.execution.daily_pipeline as daily_pipeline_module

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [CandidateStock(ticker=f"{i:06d}", name=str(i), industry_sw="银行", avg_volume_20d=10000, market_cap=100, listing_date="19910403") for i in range(4)]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {candidate.ticker: {"trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}), "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}), "fundamental": StrategySignal(direction=1, confidence=75, completeness=1.0, sub_factors={}), "event_sentiment": StrategySignal(direction=1, confidence=65, completeness=1.0, sub_factors={})} for candidate in candidates}
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [_fused(ticker, 0.46 + index / 1000.0) for index, ticker in enumerate(scored.keys())]

        pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 500000, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch

    assert calls == [(("000003", "000002", "000001", "000000"), "fast"), (("000003", "000002", "000001", "000000"), "precise")]
    assert pipeline._skip_precise_stage is False


def test_run_post_market_records_zero_skip_metrics_when_precise_runs():
    calls = []

    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        calls.append((tuple(tickers), model))
        return {
            "aswath_damodaran_agent": {ticker: {"signal": "bullish", "confidence": 70, "reasoning": "ok"} for ticker in tickers},
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [], base_model_name="gpt-4.1", base_model_provider="OpenAI")

    import src.execution.daily_pipeline as daily_pipeline_module

    original_build_candidate_pool = daily_pipeline_module.build_candidate_pool
    original_detect_market_state = daily_pipeline_module.detect_market_state
    original_score_batch = daily_pipeline_module.score_batch
    original_fuse_batch = daily_pipeline_module.fuse_batch
    try:
        daily_pipeline_module.build_candidate_pool = lambda trade_date: [CandidateStock(ticker=f"{i:06d}", name=str(i), industry_sw="银行", avg_volume_20d=10000, market_cap=100, listing_date="19910403") for i in range(2)]
        daily_pipeline_module.detect_market_state = lambda trade_date: MarketState(state_type=MarketStateType.TREND, adjusted_weights={"trend": 0.3, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.2})
        daily_pipeline_module.score_batch = lambda candidates, trade_date: {candidate.ticker: {"trend": StrategySignal(direction=1, confidence=80, completeness=1.0, sub_factors={}), "mean_reversion": StrategySignal(direction=0, confidence=50, completeness=1.0, sub_factors={}), "fundamental": StrategySignal(direction=1, confidence=75, completeness=1.0, sub_factors={}), "event_sentiment": StrategySignal(direction=1, confidence=65, completeness=1.0, sub_factors={})} for candidate in candidates}
        daily_pipeline_module.fuse_batch = lambda scored, market_state, trade_date: [_fused(ticker, 0.46 + index / 1000.0) for index, ticker in enumerate(scored.keys())]

        plan = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 500000, "positions": {}})
    finally:
        daily_pipeline_module.build_candidate_pool = original_build_candidate_pool
        daily_pipeline_module.detect_market_state = original_detect_market_state
        daily_pipeline_module.score_batch = original_score_batch
        daily_pipeline_module.fuse_batch = original_fuse_batch

    assert len(calls) == 2
    assert plan.risk_metrics["counts"]["precise_stage_skipped"] is False
    assert plan.risk_metrics["counts"]["skipped_precise_ticker_count"] == 0
    assert plan.risk_metrics["timing_seconds"]["estimated_skipped_precise"] == 0.0
    assert set(plan.logic_scores.keys()) == {"000000", "000001"}


def test_intraday_exit_checker_reads_logic_scores_from_plan(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        daily_pipeline_module,
        "get_daily_basic_batch",
        lambda trade_date: pd.DataFrame([{"ts_code": "300724.SZ", "close": 142.92}]),
    )

    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {})
    plan = ExecutionPlan(
        date="20260305",
        logic_scores={"300724": -0.25},
        portfolio_snapshot={
            "cash": 50_000,
            "positions": {
                "300724": {
                    "long": 100,
                    "short": 0,
                    "long_cost_basis": 142.924065,
                    "short_cost_basis": 0.0,
                    "short_margin_used": 0.0,
                    "entry_date": "20260203",
                    "holding_days": 5,
                    "max_unrealized_pnl_pct": 0.0,
                    "profit_take_stage": 0,
                    "entry_score": 0.22,
                    "is_fundamental_driven": False,
                    "industry_sw": "电力设备",
                }
            },
            "realized_gains": {},
        },
    )

    confirmed, exits, crisis = pipeline.run_intraday(plan, "20260211")

    assert confirmed == []
    assert len(exits) == 1
    assert exits[0].trigger_reason == "logic_stop_loss"
    assert crisis["mode"] == "normal"


def test_daily_pipeline_returns_frozen_current_plan_without_running_live_stages(monkeypatch):
    frozen_plan = ExecutionPlan(
        date="20260305",
        buy_orders=[PositionPlan(ticker="600000", shares=100, amount=1000.0, score_final=0.42, execution_ratio=1.0)],
        portfolio_snapshot={"cash": 500000.0, "positions": {}},
        risk_metrics={"counts": {"watchlist_count": 1}},
    )
    pipeline = DailyPipeline(frozen_post_market_plans={"20260305": frozen_plan}, frozen_plan_source="/tmp/frozen.jsonl")

    monkeypatch.setattr("src.execution.daily_pipeline.build_candidate_pool", lambda trade_date: (_ for _ in ()).throw(AssertionError("live candidate build should be bypassed")))

    replayed = pipeline.run_post_market("20260305", portfolio_snapshot={"cash": 1.0, "positions": {}}, blocked_buy_tickers={"600000": {"blocked_until": "20260304"}})

    assert replayed.model_dump() == frozen_plan.model_dump()
    assert replayed is not frozen_plan


def test_daily_pipeline_applies_reentry_filter_to_frozen_buy_orders():
    frozen_plan = ExecutionPlan(
        date="20260310",
        buy_orders=[PositionPlan(ticker="300724", shares=100, amount=12000.0, score_final=0.24, execution_ratio=0.3)],
        watchlist=[LayerCResult(ticker="300724", score_c=-0.05, score_final=0.24, score_b=0.43, decision="watch")],
        portfolio_snapshot={"cash": 500000.0, "positions": {}},
        risk_metrics={
            "counts": {"watchlist_count": 1, "buy_order_count": 1},
            "funnel_diagnostics": {
                "filters": {
                    "buy_orders": {"filtered_count": 0, "reason_counts": {}, "tickers": [], "selected_tickers": ["300724"]}
                }
            },
        },
    )
    pipeline = DailyPipeline(frozen_post_market_plans={"20260310": frozen_plan}, frozen_plan_source="/tmp/frozen.jsonl")

    replayed = pipeline.run_post_market(
        "20260310",
        portfolio_snapshot={"cash": 1.0, "positions": {}},
        blocked_buy_tickers={
            "300724": {
                "trigger_reason": "hard_stop_loss",
                "exit_trade_date": "20260303",
                "blocked_until": "20260306",
                "reentry_review_until": "20260312",
            }
        },
    )

    assert replayed.buy_orders == []
    assert replayed.risk_metrics["counts"]["buy_order_count"] == 0
    assert replayed.risk_metrics["funnel_diagnostics"]["filters"]["buy_orders"]["reason_counts"] == {"blocked_by_reentry_score_confirmation": 1}
    assert replayed.risk_metrics["funnel_diagnostics"]["filters"]["buy_orders"]["selected_tickers"] == []


def test_recovery_protocol():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    plan = ExecutionPlan(date="20260305")
    confirmed, exits, crisis = pipeline.run_intraday(
        plan,
        "20260306",
        crisis_inputs={
            "hs300_daily_return": -0.01,
            "limit_down_count": 50,
            "recent_total_volumes": [3900, 3800, 3700],
            "drawdown_pct": -0.16,
        },
    )
    assert confirmed == []
    assert exits == []
    assert crisis["forced_reduce_ratio"] == 0.5
    assert crisis["recovery_cooldown_days"] == 5


def test_pre_market_pipeline_decay():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    plan = ExecutionPlan(date="20260305", buy_orders=[PositionPlan(ticker="000001", shares=1000, amount=10000, constraint_binding="cash", score_final=0.5, execution_ratio=1.0)])
    updated = pipeline.run_pre_market(plan, "20260306", negative_news_tickers={"000001"})
    assert updated.buy_orders == []


def test_intraday_confirmation_pipeline():
    pipeline = DailyPipeline(agent_runner=lambda tickers, trade_date, model: {}, exit_checker=lambda portfolio, trade_date: [])
    plan = ExecutionPlan(date="20260305", buy_orders=[PositionPlan(ticker="000001", shares=1000, amount=10000, constraint_binding="cash", score_final=0.5, execution_ratio=1.0)], portfolio_snapshot={})
    confirmed, exits, crisis = pipeline.run_intraday(
        plan,
        "20260306",
        confirmation_inputs={
            "000001": {
                "day_low": 10.0,
                "ema30": 10.0,
                "current_price": 10.3,
                "vwap": 10.1,
                "intraday_volume": 900000,
                "avg_same_time_volume": 1000000,
                "industry_percentile": 0.4,
            }
        },
    )
    assert len(confirmed) == 1
    assert exits == []
    assert crisis["mode"] == "normal"
