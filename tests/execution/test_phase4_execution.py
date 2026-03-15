"""Phase 4 执行层测试。"""

from __future__ import annotations

import pytest

from src.execution.daily_pipeline import DailyPipeline, WATCHLIST_SCORE_THRESHOLD
from src.execution.crisis_handler import evaluate_crisis_response
from src.execution.layer_c_aggregator import (
    LAYER_C_AVOID_SCORE_C_THRESHOLD,
    LAYER_C_BLEND_B_WEIGHT,
    LAYER_C_BLEND_C_WEIGHT,
    LAYER_C_INVESTOR_WEIGHT_SCALE,
    aggregate_layer_c_results,
    convert_agent_signal_to_strategy_signal,
)
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


def _evaluate_default_layer_c_outcome(score_b: float, investor: float, analyst: float, other: float = 0.0) -> dict:
    total_weight = LAYER_C_BLEND_B_WEIGHT + LAYER_C_BLEND_C_WEIGHT
    blend_b = LAYER_C_BLEND_B_WEIGHT / total_weight
    blend_c = LAYER_C_BLEND_C_WEIGHT / total_weight
    score_c = (investor * LAYER_C_INVESTOR_WEIGHT_SCALE) + analyst + other
    decision = "strong_buy" if score_b > 0.50 else "watch" if score_b >= 0.35 else "neutral"
    bc_conflict = None
    if score_b > 0.50 and score_c < 0:
        bc_conflict = "b_strong_buy_c_negative"
        decision = "watch"
    if score_b > 0 and score_c < LAYER_C_AVOID_SCORE_C_THRESHOLD:
        bc_conflict = "b_positive_c_strong_bearish"
        decision = "avoid"
    score_final = (score_b * blend_b) + (score_c * blend_c)
    return {
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

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [])

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

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [])

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
    assert diagnostics["filters"]["watchlist"]["tickers"][0]["agent_contribution_summary"]["negative_agent_count"] == 2
    assert diagnostics["filters"]["watchlist"]["selected_entries"][0]["agent_contribution_summary"]["positive_agent_count"] == 2
    assert diagnostics["filters"]["buy_orders"]["reason_counts"] == {"no_available_cash": 1}
    assert calls[0][1] == "fast"


def test_watchlist_threshold_020_admits_edge_case_between_020_and_025():
    def fake_agent_runner(tickers: list[str], trade_date: str, model: str):
        return {
            "aswath_damodaran_agent": {ticker: {"signal": "bullish", "confidence": 70, "reasoning": "ok"} for ticker in tickers},
            "technical_analyst_agent": {ticker: {"signal": "bearish", "confidence": 100, "reasoning": "ok"} for ticker in tickers},
        }

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [])

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
    assert result["score_c"] < LAYER_C_AVOID_SCORE_C_THRESHOLD, ticker


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

    pipeline = DailyPipeline(agent_runner=fake_agent_runner, exit_checker=lambda portfolio, trade_date: [])

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
    assert calls[1]["model_name"] == "glm-4.7"
    assert calls[1]["model_provider"] == "Zhipu"


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
    assert calls[1]["model_name"] == "gpt-4.1"
    assert calls[1]["model_provider"] == "OpenAI"


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
