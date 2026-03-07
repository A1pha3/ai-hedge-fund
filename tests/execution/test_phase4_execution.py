"""Phase 4 执行层测试。"""

from __future__ import annotations

from src.execution.daily_pipeline import DailyPipeline
from src.execution.crisis_handler import evaluate_crisis_response
from src.execution.layer_c_aggregator import aggregate_layer_c_results, convert_agent_signal_to_strategy_signal
from src.execution.signal_decay import apply_signal_decay
from src.execution.t1_confirmation import confirm_buy_signal
from src.execution.models import ExecutionPlan
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
    def fake_agent_runner(tickers: list[str], trade_date: str):
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
