import os
import importlib
from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from src.data.models import CompanyNews, FinancialMetrics, InsiderTrade
from src.screening.models import CandidateStock, StrategySignal, SubFactor
from src.screening.strategy_scorer import _apply_fundamental_quality_cap, _score_adx_strength, _score_ema_alignment, _score_event_freshness, _score_long_trend_alignment, _score_news_sentiment, _score_profitability, aggregate_sub_factors, score_batch, score_event_sentiment_strategy, score_fundamental_strategy, score_mean_reversion_strategy, score_trend_strategy
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
    payload = {
        "ticker": "300065",
        "report_period": "20251231",
        "period": "ttm",
        "currency": "CNY",
        "market_cap": 0.0,
        "enterprise_value": 0.0,
        "price_to_earnings_ratio": 0.0,
        "price_to_book_ratio": 0.0,
        "price_to_sales_ratio": 0.0,
        "enterprise_value_to_ebitda_ratio": 0.0,
        "enterprise_value_to_revenue_ratio": 0.0,
        "free_cash_flow_yield": 0.0,
        "peg_ratio": 0.0,
        "gross_margin": 0.0,
        "operating_margin": 0.06,
        "net_margin": 0.08,
        "return_on_equity": 0.05,
        "return_on_assets": 0.0,
        "return_on_invested_capital": 0.0,
        "asset_turnover": 0.0,
        "inventory_turnover": 0.0,
        "receivables_turnover": 0.0,
        "days_sales_outstanding": 0.0,
        "operating_cycle": 0.0,
        "working_capital_turnover": 0.0,
        "current_ratio": 0.0,
        "quick_ratio": 0.0,
        "cash_ratio": 0.0,
        "operating_cash_flow_ratio": 0.0,
        "debt_to_equity": 0.0,
        "debt_to_assets": 0.0,
        "interest_coverage": 0.0,
        "revenue_growth": 0.0,
        "earnings_growth": 0.0,
        "book_value_growth": 0.0,
        "earnings_per_share_growth": 0.0,
        "free_cash_flow_growth": 0.0,
        "operating_income_growth": 0.0,
        "ebitda_growth": 0.0,
        "payout_ratio": 0.0,
        "earnings_per_share": 0.0,
        "book_value_per_share": 0.0,
        "free_cash_flow_per_share": 0.0,
    }
    payload.update(overrides)
    return FinancialMetrics.model_construct(**payload)


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


def test_profitability_two_positive_metrics_is_bullish():
    metrics = _financial_metrics(return_on_equity=0.16, net_margin=0.21, operating_margin=0.10)

    factor = _score_profitability(metrics)

    assert factor.direction == 1
    assert factor.confidence == pytest.approx(66.6666666667)
    assert factor.completeness == 1.0
    assert factor.metrics["available_count"] == 3
    assert factor.metrics["positive_count"] == 2


def test_score_event_freshness_returns_incomplete_without_news():
    factor = _score_event_freshness([], "20260305")

    assert factor.direction == 0
    assert factor.confidence == 0.0
    assert factor.completeness == 0.0


def test_score_event_freshness_marks_fresh_positive_news_as_bullish():
    factor = _score_event_freshness(
        [
            _news_item(
                title="Record profit growth",
                date="2026-03-04",
                content="breakthrough contract profit growth",
            )
        ],
        "20260305",
    )

    assert factor.direction == 1
    assert factor.confidence == pytest.approx(70.4688, rel=1e-4)
    assert factor.metrics == {
        "days_old": 1,
        "decay": pytest.approx(0.7046880897),
        "positive_hits": 5,
        "negative_hits": 0,
        "freshness_weight": 1.0,
    }


def test_score_industry_pe_returns_incomplete_without_industry_context():
    factor = strategy_scorer_module._score_industry_pe(
        _financial_metrics(price_to_earnings_ratio=12.0),
        "",
        {"银行": 8.0},
    )

    assert factor.direction == 0
    assert factor.confidence == 0.0
    assert factor.completeness == 0.0


def test_score_industry_pe_marks_discounted_pe_as_bullish():
    factor = strategy_scorer_module._score_industry_pe(
        _financial_metrics(price_to_earnings_ratio=6.0),
        "银行",
        {"银行": 10.0},
    )

    assert factor.direction == 1
    assert factor.confidence == 100.0
    assert factor.metrics == {
        "industry": "银行",
        "current_pe": 6.0,
        "industry_pe_median": 10.0,
        "premium_ratio": 0.6,
    }


def test_aggregate_sub_factors_returns_empty_signal_when_all_incomplete():
    factors = [
        SubFactor(name="a", direction=1, confidence=80.0, completeness=0.0, weight=0.6, metrics={"x": 1}),
        SubFactor(name="b", direction=-1, confidence=20.0, completeness=0.0, weight=0.4, metrics={"y": 2}),
    ]

    signal = aggregate_sub_factors(factors)

    assert signal.direction == 0
    assert signal.confidence == 0.0
    assert signal.completeness == 0.0
    assert signal.sub_factors["a"]["metrics"] == {"x": 1}
    assert signal.sub_factors["b"]["metrics"] == {"y": 2}


def test_aggregate_sub_factors_applies_weighted_consistency_penalty():
    factors = [
        SubFactor(name="trend", direction=1, confidence=90.0, completeness=1.0, weight=0.5),
        SubFactor(name="fundamental", direction=1, confidence=60.0, completeness=1.0, weight=0.3),
        SubFactor(name="event", direction=-1, confidence=30.0, completeness=1.0, weight=0.2),
    ]

    signal = aggregate_sub_factors(factors)

    assert signal.direction == 1
    assert signal.confidence == pytest.approx(46.0)
    assert signal.completeness == 1.0


def test_score_fundamental_strategy_returns_empty_signal_when_metrics_missing(monkeypatch):
    monkeypatch.setattr(strategy_scorer_module, "get_financial_metrics", lambda **kwargs: [])

    signal = score_fundamental_strategy("000001", "20260305")

    assert signal.direction == 0
    assert signal.confidence == 0.0
    assert signal.completeness == 0.0
    assert signal.sub_factors == {}


def test_score_fundamental_strategy_builds_and_caps_sub_factors(monkeypatch):
    latest = _financial_metrics(return_on_equity=0.18)
    older = _financial_metrics(report_period="20240930", revenue_growth=0.25)
    captured: dict[str, object] = {}

    monkeypatch.setattr(strategy_scorer_module, "get_financial_metrics", lambda **kwargs: [latest, older])
    monkeypatch.setattr(strategy_scorer_module, "_score_profitability", lambda metrics: SubFactor(name="profitability", direction=1, confidence=80.0, weight=0.25, metrics={"metric": metrics.report_period}))
    monkeypatch.setattr(strategy_scorer_module, "_score_growth", lambda metrics_list: SubFactor(name="growth", direction=1, confidence=75.0, weight=0.25, metrics={"periods": len(metrics_list)}))
    monkeypatch.setattr(strategy_scorer_module, "_score_financial_health", lambda metrics: SubFactor(name="financial_health", direction=1, confidence=70.0, weight=0.20, metrics={"metric": metrics.report_period}))
    monkeypatch.setattr(strategy_scorer_module, "_score_growth_valuation", lambda metrics: SubFactor(name="growth_valuation", direction=0, confidence=50.0, weight=0.15, metrics={"metric": metrics.report_period}))
    monkeypatch.setattr(strategy_scorer_module, "_score_industry_pe", lambda metrics, industry_name, medians: SubFactor(name="industry_pe", direction=-1, confidence=20.0, weight=0.15, metrics={"industry": industry_name, "median_count": len(medians or {})}))

    def fake_aggregate(factors):
        captured["factors"] = factors
        return StrategySignal(direction=1, confidence=88.0, completeness=1.0, sub_factors={})

    monkeypatch.setattr(strategy_scorer_module, "aggregate_sub_factors", fake_aggregate)
    monkeypatch.setattr(
        strategy_scorer_module,
        "_apply_fundamental_quality_cap",
        lambda signal: captured.setdefault("pre_cap_signal", signal) or StrategySignal(direction=1, confidence=45.0, completeness=1.0, sub_factors={"capped": {}}),
    )

    score_fundamental_strategy("000001", "20260305", industry_name="银行", industry_pe_medians={"银行": 6.5})

    factor_names = [factor.name for factor in captured["factors"]]
    assert factor_names == ["profitability", "growth", "financial_health", "growth_valuation", "industry_pe"]
    assert captured["factors"][0].metrics == {"metric": "20251231"}
    assert captured["factors"][1].metrics == {"periods": 2}
    assert captured["factors"][-1].metrics == {"industry": "银行", "median_count": 1}
    assert captured["pre_cap_signal"] == StrategySignal(direction=1, confidence=88.0, completeness=1.0, sub_factors={})


def test_score_ema_alignment_returns_bullish_for_stacked_emas():
    prices_df = pd.DataFrame({"close": [10.0] * 59 + [12.0]})

    with patch.object(
        strategy_scorer_module,
        "calculate_ema",
        side_effect=[
            pd.Series([0.0] * 59 + [12.0]),
            pd.Series([0.0] * 59 + [11.0]),
            pd.Series([0.0] * 59 + [10.0]),
        ],
    ):
        factor = _score_ema_alignment(prices_df, weight=0.4)

    assert factor.direction == 1
    assert factor.confidence == 100.0
    assert factor.metrics == {"ema_10": 12.0, "ema_30": 11.0, "ema_60": 10.0}


def test_score_ema_alignment_returns_incomplete_for_short_history():
    factor = _score_ema_alignment(pd.DataFrame({"close": [10.0] * 10}), weight=0.4)

    assert factor.direction == 0
    assert factor.confidence == 0.0
    assert factor.completeness == 0.0


def test_score_long_trend_alignment_returns_bullish_for_ema_above_200():
    prices_df = pd.DataFrame({"close": [10.0] * 199 + [20.0]})

    with patch.object(
        strategy_scorer_module,
        "calculate_ema",
        side_effect=[
            pd.Series([0.0] * 199 + [18.0]),
            pd.Series([0.0] * 199 + [12.0]),
        ],
    ):
        factor = _score_long_trend_alignment(prices_df, weight=0.25)

    assert factor.direction == 1
    assert factor.confidence == 100.0
    assert factor.metrics == {"ema_10": 18.0, "ema_200": 12.0}


def test_score_long_trend_alignment_returns_incomplete_for_short_history():
    factor = _score_long_trend_alignment(pd.DataFrame({"close": [10.0] * 20}), weight=0.25)

    assert factor.direction == 0
    assert factor.confidence == 0.0
    assert factor.completeness == 0.0


def test_score_adx_strength_returns_bullish_when_plus_di_leads():
    prices_df = pd.DataFrame({"close": [10.0] * 30})

    with patch.object(
        strategy_scorer_module,
        "calculate_adx",
        return_value=pd.DataFrame({"adx": [28.0], "+di": [35.0], "-di": [12.0]}),
    ):
        factor = _score_adx_strength(prices_df, weight=0.21)

    assert factor.direction == 1
    assert factor.confidence == 28.0
    assert factor.metrics == {"adx": 28.0, "+di": 35.0, "-di": 12.0}


def test_score_adx_strength_returns_neutral_below_threshold():
    prices_df = pd.DataFrame({"close": [10.0] * 30})

    with patch.object(
        strategy_scorer_module,
        "calculate_adx",
        return_value=pd.DataFrame({"adx": [18.0], "+di": [35.0], "-di": [12.0]}),
    ):
        factor = _score_adx_strength(prices_df, weight=0.21)

    assert factor.direction == 0
    assert factor.confidence == 18.0


def test_score_trend_strategy_builds_optional_sub_factors(monkeypatch):
    prices_df = pd.DataFrame({"close": [10.0] * 130})
    captured: dict[str, list] = {}

    def fake_aggregate(factors):
        captured["factors"] = factors
        return StrategySignal(direction=1, confidence=66.0, completeness=1.0, sub_factors={})

    monkeypatch.setattr(
        strategy_scorer_module,
        "_get_trend_subfactor_weights",
        lambda: {
            "ema_alignment": 0.3,
            "adx_strength": 0.2,
            "momentum": 0.25,
            "volatility": 0.15,
            "long_trend_alignment": 0.1,
        },
    )
    monkeypatch.setattr(strategy_scorer_module, "calculate_momentum_signals", lambda df: {"signal": "bullish", "confidence": 0.7, "metrics": {"mom": 1}})
    monkeypatch.setattr(strategy_scorer_module, "calculate_volatility_signals", lambda df: {"signal": "bearish", "confidence": 0.4, "metrics": {"vol": 2}})
    monkeypatch.setattr(strategy_scorer_module, "_score_ema_alignment", lambda df, weight: SubFactor(name="ema_alignment", direction=1, confidence=80.0, completeness=1.0, weight=weight, metrics={}))
    monkeypatch.setattr(strategy_scorer_module, "_score_adx_strength", lambda df, weight: SubFactor(name="adx_strength", direction=1, confidence=25.0, completeness=1.0, weight=weight, metrics={}))
    monkeypatch.setattr(strategy_scorer_module, "_score_long_trend_alignment", lambda df, weight: SubFactor(name="long_trend_alignment", direction=1, confidence=30.0, completeness=1.0, weight=weight, metrics={}))
    monkeypatch.setattr(strategy_scorer_module, "aggregate_sub_factors", fake_aggregate)

    score_trend_strategy(prices_df)

    factor_names = [factor.name for factor in captured["factors"]]
    assert factor_names == ["ema_alignment", "adx_strength", "momentum", "volatility", "long_trend_alignment"]
    momentum = captured["factors"][2]
    volatility = captured["factors"][3]
    assert momentum.direction == 1 and momentum.confidence == 70.0 and momentum.completeness == 1.0
    assert volatility.direction == -1 and volatility.confidence == 40.0 and volatility.completeness == 1.0


def _news_item(title: str, date: str, content: str = "") -> CompanyNews:
    return CompanyNews(
        ticker="000001",
        title=title,
        author="test",
        source="test",
        date=date,
        url="https://example.com",
        content=content,
    )


def test_event_sentiment_ignores_stale_weak_single_keyword_news():
    news = [_news_item("Company growth", "2026-02-26", "")]

    with patch("src.screening.strategy_scorer.get_company_news", return_value=news), \
         patch("src.screening.strategy_scorer.get_insider_trades", return_value=[]):
        signal = score_event_sentiment_strategy("000001", "20260305")

    assert signal.direction == 0
    assert signal.confidence == 0.0
    assert signal.sub_factors["news_sentiment"]["metrics"]["informative_articles"] == 0


def test_event_sentiment_keeps_fresh_multi_keyword_news_actionable():
    news = [_news_item("profit growth beat upgrade", "2026-03-05", "record order growth and profit beat")]

    with patch("src.screening.strategy_scorer.get_company_news", return_value=news), \
         patch("src.screening.strategy_scorer.get_insider_trades", return_value=[]):
        signal = score_event_sentiment_strategy("000001", "20260305")

    assert signal.direction == 1
    assert signal.confidence > 0
    assert signal.sub_factors["news_sentiment"]["metrics"]["informative_articles"] == 1


def test_score_event_sentiment_strategy_builds_sub_factors_from_loaded_data(monkeypatch):
    news = [_news_item("profit growth beat upgrade", "2026-03-05", "record order growth and profit beat")]
    trades = [
        InsiderTrade(
            ticker="000001",
            issuer="issuer",
            name="tester",
            title="CEO",
            is_board_director=False,
            transaction_date="2026-03-01",
            transaction_shares=1000.0,
            transaction_price_per_share=10.0,
            transaction_value=10000.0,
            shares_owned_before_transaction=5000.0,
            shares_owned_after_transaction=6000.0,
            security_title="common",
            filing_date="2026-03-02",
        )
    ]
    captured: dict[str, object] = {}

    def fake_news_loader(*, ticker, start_date, end_date, limit):
        captured["news_loader"] = {"ticker": ticker, "start_date": start_date, "end_date": end_date, "limit": limit}
        return news

    def fake_trades_loader(*, ticker, start_date, end_date, limit):
        captured["trade_loader"] = {"ticker": ticker, "start_date": start_date, "end_date": end_date, "limit": limit}
        return trades

    monkeypatch.setattr(strategy_scorer_module, "get_company_news", fake_news_loader)
    monkeypatch.setattr(strategy_scorer_module, "get_insider_trades", fake_trades_loader)
    monkeypatch.setattr(strategy_scorer_module, "_score_news_sentiment", lambda items, trade_date: SubFactor(name="news_sentiment", direction=1, confidence=80.0, weight=0.55, metrics={"news_count": len(items), "trade_date": trade_date}))
    monkeypatch.setattr(strategy_scorer_module, "_score_insider_conviction", lambda items: SubFactor(name="insider_conviction", direction=1, confidence=40.0, weight=0.25, metrics={"trade_count": len(items)}))
    monkeypatch.setattr(strategy_scorer_module, "_score_event_freshness", lambda items, trade_date: SubFactor(name="event_freshness", direction=0, confidence=25.0, weight=0.20, metrics={"fresh_news_count": len(items), "trade_date": trade_date}))

    def fake_aggregate(factors):
        captured["factors"] = factors
        return StrategySignal(direction=1, confidence=61.0, completeness=1.0, sub_factors={})

    monkeypatch.setattr(strategy_scorer_module, "aggregate_sub_factors", fake_aggregate)

    signal = score_event_sentiment_strategy("000001", "20260305")

    assert captured["news_loader"] == {"ticker": "000001", "start_date": "2026-02-03", "end_date": "2026-03-05", "limit": 50}
    assert captured["trade_loader"] == {"ticker": "000001", "start_date": "2026-02-03", "end_date": "2026-03-05", "limit": 100}
    assert [factor.name for factor in captured["factors"]] == ["news_sentiment", "insider_conviction", "event_freshness"]
    assert signal == StrategySignal(direction=1, confidence=61.0, completeness=1.0, sub_factors={})


def test_score_news_sentiment_tracks_recent_and_informative_articles():
    factor = _score_news_sentiment(
        [
            _news_item("profit growth beat", "2026-03-05", "growth beat upgrade"),
            _news_item("legacy headline", "2026-02-20", ""),
        ],
        "20260305",
    )

    assert factor.direction == 1
    assert factor.metrics["recent_articles"] == 1
    assert factor.metrics["informative_articles"] == 1
    assert factor.metrics["articles"][0]["direction"] == 1
    assert factor.metrics["articles"][1]["effective_weight"] == 0.0


def test_score_news_sentiment_returns_incomplete_when_no_news():
    factor = _score_news_sentiment([], "20260305")

    assert factor.direction == 0
    assert factor.confidence == 0.0
    assert factor.completeness == 0.0


def test_score_news_article_builds_positive_fresh_article_metrics():
    metrics = strategy_scorer_module._score_news_article(
        _news_item("profit growth beat", "2026-03-05", "record upgrade and contract"),
        datetime(2026, 3, 5),
    )

    assert metrics["days_old"] == 0
    assert metrics["direction"] == 1
    assert metrics["confidence"] > 45.0
    assert metrics["effective_weight"] == metrics["decay"]


def test_score_news_article_downweights_stale_negative_article():
    metrics = strategy_scorer_module._score_news_article(
        _news_item("downgrade warning", "2026-03-01", "fraud risk and weak demand"),
        datetime(2026, 3, 5),
    )

    assert metrics["days_old"] == 4
    assert metrics["direction"] == -1
    assert metrics["effective_weight"] < metrics["decay"]


def test_score_mean_reversion_strategy_marks_rsi_oversold_and_reversion_regime():
    prices_df = pd.DataFrame({"close": [100.0] * 100})

    with (
        patch("src.screening.strategy_scorer.calculate_mean_reversion_signals", return_value={"signal": "bullish", "confidence": 0.7, "metrics": {"z": -2.1}}),
        patch("src.screening.strategy_scorer.calculate_stat_arb_signals", return_value={"signal": "neutral", "confidence": 0.2, "metrics": {}}),
        patch(
            "src.screening.strategy_scorer.calculate_rsi",
            side_effect=[
                pd.Series([25.0] * len(prices_df)),
                pd.Series([35.0] * len(prices_df)),
            ],
        ),
        patch("src.screening.strategy_scorer.calculate_hurst_exponent", return_value=0.4),
    ):
        signal = score_mean_reversion_strategy(prices_df)

    assert signal.sub_factors["rsi_extreme"]["direction"] == 1
    assert signal.sub_factors["rsi_extreme"]["metrics"] == {"rsi_14": 25.0, "rsi_28": 35.0}
    assert signal.sub_factors["hurst_regime"]["direction"] == 0
    assert signal.sub_factors["hurst_regime"]["metrics"]["hurst_exponent"] == 0.4


def test_score_mean_reversion_strategy_marks_insufficient_rsi_history_incomplete():
    prices_df = pd.DataFrame({"close": [100.0] * 20})

    with (
        patch("src.screening.strategy_scorer.calculate_mean_reversion_signals", return_value=None),
        patch("src.screening.strategy_scorer.calculate_stat_arb_signals", return_value=None),
    ):
        signal = score_mean_reversion_strategy(prices_df)

    assert signal.sub_factors["rsi_extreme"]["completeness"] == 0.0
    assert signal.sub_factors["hurst_regime"]["completeness"] == 0.0


def test_fundamental_quality_cap_neutralizes_bullish_signal_without_quality_confirmation():
    signal = StrategySignal(
        direction=1,
        confidence=72.0,
        completeness=1.0,
        sub_factors={
            "profitability": {"direction": 0, "confidence": 30.0, "metrics": {"positive_count": 1}},
            "financial_health": {"direction": 0, "confidence": 25.0, "metrics": {}},
            "growth": {"direction": 1, "confidence": 80.0, "metrics": {}},
        },
    )

    capped = _apply_fundamental_quality_cap(signal)

    assert capped.direction == 0
    assert capped.confidence == 45.0
    assert capped.sub_factors["quality_cap"]["applied"] is True


def test_fundamental_quality_cap_keeps_signal_when_core_quality_is_bullish():
    signal = StrategySignal(
        direction=1,
        confidence=72.0,
        completeness=1.0,
        sub_factors={
            "profitability": {"direction": 1, "confidence": 70.0, "metrics": {"positive_count": 2}},
            "financial_health": {"direction": 0, "confidence": 25.0, "metrics": {}},
            "growth": {"direction": 1, "confidence": 80.0, "metrics": {}},
        },
    )

    capped = _apply_fundamental_quality_cap(signal)

    assert capped.direction == 1
    assert capped.confidence == 72.0
