import os
import importlib
from unittest.mock import patch

from src.data.models import FinancialMetrics
from src.screening.models import CandidateStock, StrategySignal
from src.screening.strategy_scorer import _score_profitability, score_batch
import src.screening.strategy_scorer as strategy_scorer_module


def _signal(direction: int, confidence: float, completeness: float = 1.0) -> StrategySignal:
    return StrategySignal(direction=direction, confidence=confidence, completeness=completeness, sub_factors={})


def _candidate(ticker: str, avg_volume_20d: float = 10000.0, market_cap: float = 100.0) -> CandidateStock:
    return CandidateStock(
        ticker=ticker,
        name=ticker,
        industry_sw="银行",
        avg_volume_20d=avg_volume_20d,
        market_cap=market_cap,
        listing_date="19910403",
    )


def test_score_batch_delays_heavy_signals_to_ranked_subset():
    candidates = [_candidate("000001"), _candidate("000002"), _candidate("000003")]

    light_signals = {
        "000001": {
            "trend": _signal(1, 90),
            "mean_reversion": _signal(0, 0, completeness=0.0),
            "fundamental": _signal(0, 0, completeness=0.0),
            "event_sentiment": _signal(0, 0, completeness=0.0),
        },
        "000002": {
            "trend": _signal(1, 35),
            "mean_reversion": _signal(0, 0, completeness=0.0),
            "fundamental": _signal(0, 0, completeness=0.0),
            "event_sentiment": _signal(0, 0, completeness=0.0),
        },
        "000003": {
            "trend": _signal(-1, 80),
            "mean_reversion": _signal(0, 0, completeness=0.0),
            "fundamental": _signal(0, 0, completeness=0.0),
            "event_sentiment": _signal(0, 0, completeness=0.0),
        },
    }

    fundamental_calls: list[str] = []
    event_calls: list[str] = []

    def fake_light(candidate, trade_date):
        return light_signals[candidate.ticker], None

    def fake_fundamental(ticker, trade_date, industry_name, industry_pe_medians):
        fundamental_calls.append(ticker)
        return _signal(1, 70)

    def fake_event(ticker, trade_date):
        event_calls.append(ticker)
        return _signal(1, 65)

    with patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}), \
         patch("src.screening.strategy_scorer._compute_light_signals", side_effect=fake_light), \
         patch("src.screening.strategy_scorer.score_fundamental_strategy", side_effect=fake_fundamental), \
         patch("src.screening.strategy_scorer.score_event_sentiment_strategy", side_effect=fake_event), \
         patch("src.screening.strategy_scorer.FUNDAMENTAL_SCORE_MAX_CANDIDATES", 2), \
         patch("src.screening.strategy_scorer.EVENT_SENTIMENT_MAX_CANDIDATES", 1), \
         patch("src.screening.strategy_scorer.HEAVY_SCORE_MIN_PROVISIONAL_SCORE", 0.05):
        results = score_batch(candidates, "20260305")

    assert fundamental_calls == ["000001", "000002"]
    assert event_calls == ["000001"]
    assert results["000001"]["fundamental"].completeness == 1.0
    assert results["000001"]["event_sentiment"].completeness == 1.0
    assert results["000002"]["fundamental"].completeness == 1.0
    assert results["000002"]["event_sentiment"].completeness == 0.0
    assert results["000003"]["fundamental"].completeness == 0.0
    assert results["000003"]["event_sentiment"].completeness == 0.0


def test_score_batch_keeps_all_strategy_keys_when_heavy_signals_skipped():
    candidates = [_candidate("000001")]

    with (
        patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}),
        patch(
            "src.screening.strategy_scorer._compute_light_signals",
            return_value=(
                {
                    "trend": _signal(0, 0, completeness=0.0),
                    "mean_reversion": _signal(0, 0, completeness=0.0),
                    "fundamental": _signal(0, 0, completeness=0.0),
                    "event_sentiment": _signal(0, 0, completeness=0.0),
                },
                None,
            ),
        ),
        patch("src.screening.strategy_scorer.score_fundamental_strategy") as mock_fundamental,
        patch("src.screening.strategy_scorer.score_event_sentiment_strategy") as mock_event,
        patch("src.screening.strategy_scorer.HEAVY_SCORE_MIN_PROVISIONAL_SCORE", 0.2),
    ):
        results = score_batch(candidates, "20260305")

    mock_fundamental.assert_not_called()
    mock_event.assert_not_called()
    assert set(results["000001"].keys()) == {"trend", "mean_reversion", "fundamental", "event_sentiment"}
    assert results["000001"]["fundamental"].completeness == 0.0
    assert results["000001"]["event_sentiment"].completeness == 0.0


def test_score_batch_limits_technical_scoring_to_ranked_subset():
    candidates = [
        _candidate("000001", avg_volume_20d=30000.0, market_cap=300.0),
        _candidate("000002", avg_volume_20d=20000.0, market_cap=200.0),
        _candidate("000003", avg_volume_20d=10000.0, market_cap=100.0),
    ]
    technical_calls: list[str] = []

    def fake_light(candidate, trade_date):
        technical_calls.append(candidate.ticker)
        return {
            "trend": _signal(1, 70),
            "mean_reversion": _signal(0, 0, completeness=0.0),
            "fundamental": _signal(0, 0, completeness=0.0),
            "event_sentiment": _signal(0, 0, completeness=0.0),
        }, None

    with (
        patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}),
        patch("src.screening.strategy_scorer._compute_light_signals", side_effect=fake_light),
        patch("src.screening.strategy_scorer.TECHNICAL_SCORE_MAX_CANDIDATES", 2),
        patch("src.screening.strategy_scorer.FUNDAMENTAL_SCORE_MAX_CANDIDATES", 0),
        patch("src.screening.strategy_scorer.EVENT_SENTIMENT_MAX_CANDIDATES", 0),
    ):
        results = score_batch(candidates, "20260305")

    assert technical_calls == ["000001", "000002"]
    assert results["000003"]["trend"].completeness == 0.0
    assert results["000003"]["mean_reversion"].completeness == 0.0


def test_scoring_stage_defaults_scale_with_candidate_pool_size(monkeypatch):
    monkeypatch.setenv("MAX_CANDIDATE_POOL_SIZE", "300")
    monkeypatch.delenv("SCORE_BATCH_TECHNICAL_MAX_CANDIDATES", raising=False)
    monkeypatch.delenv("SCORE_BATCH_FUNDAMENTAL_MAX_CANDIDATES", raising=False)
    monkeypatch.delenv("SCORE_BATCH_EVENT_SENTIMENT_MAX_CANDIDATES", raising=False)
    reloaded_module = importlib.reload(strategy_scorer_module)

    try:
        assert reloaded_module.TECHNICAL_SCORE_MAX_CANDIDATES == 225
        assert reloaded_module.FUNDAMENTAL_SCORE_MAX_CANDIDATES == 141
        assert reloaded_module.EVENT_SENTIMENT_MAX_CANDIDATES == 60
    finally:
        importlib.reload(strategy_scorer_module)


def _financial_metrics(**overrides) -> FinancialMetrics:
    return FinancialMetrics.model_construct(
        ticker="300065",
        report_period="20251231",
        period="ttm",
        currency="CNY",
        market_cap=0.0,
        enterprise_value=0.0,
        price_to_earnings_ratio=0.0,
        price_to_book_ratio=0.0,
        price_to_sales_ratio=0.0,
        enterprise_value_to_ebitda_ratio=0.0,
        enterprise_value_to_revenue_ratio=0.0,
        free_cash_flow_yield=0.0,
        peg_ratio=0.0,
        gross_margin=0.0,
        operating_margin=0.06,
        net_margin=0.08,
        return_on_equity=0.05,
        return_on_assets=0.0,
        return_on_invested_capital=0.0,
        asset_turnover=0.0,
        inventory_turnover=0.0,
        receivables_turnover=0.0,
        days_sales_outstanding=0.0,
        operating_cycle=0.0,
        working_capital_turnover=0.0,
        current_ratio=0.0,
        quick_ratio=0.0,
        cash_ratio=0.0,
        operating_cash_flow_ratio=0.0,
        debt_to_equity=0.0,
        debt_to_assets=0.0,
        interest_coverage=0.0,
        revenue_growth=0.0,
        earnings_growth=0.0,
        book_value_growth=0.0,
        earnings_per_share_growth=0.0,
        free_cash_flow_growth=0.0,
        operating_income_growth=0.0,
        ebitda_growth=0.0,
        payout_ratio=0.0,
        earnings_per_share=0.0,
        book_value_per_share=0.0,
        free_cash_flow_per_share=0.0,
        **overrides,
    )


def test_profitability_zero_pass_defaults_to_bearish():
    metrics = _financial_metrics()

    with patch.dict(os.environ, {}, clear=False):
        factor = _score_profitability(metrics)

    assert factor.direction == -1
    assert factor.confidence == 100.0
    assert factor.metrics["positive_count"] == 0
    assert factor.metrics["zero_pass_mode"] == "bearish"


def test_profitability_zero_pass_can_switch_to_neutral_for_analysis():
    metrics = _financial_metrics()

    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE": "neutral"}, clear=False):
        factor = _score_profitability(metrics)

    assert factor.direction == 0
    assert factor.confidence == 0.0
    assert factor.metrics["positive_count"] == 0
    assert factor.metrics["zero_pass_mode"] == "neutral"


def test_profitability_zero_pass_can_be_excluded_for_analysis():
    metrics = _financial_metrics()

    with patch.dict(os.environ, {"LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE": "inactive"}, clear=False):
        factor = _score_profitability(metrics)

    assert factor.direction == 0
    assert factor.confidence == 0.0
    assert factor.completeness == 0.0
    assert factor.metrics["positive_count"] == 0
    assert factor.metrics["zero_pass_mode"] == "inactive"
