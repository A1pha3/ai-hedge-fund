import importlib
import os
from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

import src.screening.strategy_scorer as strategy_scorer_module
import src.screening.strategy_scorer_fundamental as fundamental_module
import src.screening.strategy_scorer_trend as trend_module
from src.data.models import CompanyNews, FinancialMetrics, InsiderTrade
from src.screening.models import CandidateStock, StrategySignal, SubFactor
from src.screening.strategy_scorer import (
    aggregate_sub_factors,
    score_batch,
    score_event_sentiment_strategy,
    score_fundamental_strategy,
    score_mean_reversion_strategy,
    score_trend_strategy,
)
from src.screening.strategy_scorer_event_sentiment_helpers import (
    _score_event_freshness,
    _score_news_sentiment,
)
from src.screening.strategy_scorer_fundamental import (
    _apply_fundamental_quality_cap,
    _score_profitability,
)
from src.screening.strategy_scorer_trend import (
    _score_adx_strength,
    _score_ema_alignment,
    _score_long_trend_alignment,
)


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

    with (
        patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}),
        patch("src.screening.strategy_scorer._compute_light_signals", side_effect=fake_light),
        patch("src.screening.strategy_scorer.score_fundamental_strategy", side_effect=fake_fundamental),
        patch("src.screening.strategy_scorer.score_event_sentiment_strategy", side_effect=fake_event),
        patch("src.screening.strategy_scorer.FUNDAMENTAL_SCORE_MAX_CANDIDATES", 2),
        patch("src.screening.strategy_scorer.EVENT_SENTIMENT_MAX_CANDIDATES", 1),
        patch("src.screening.strategy_scorer.HEAVY_SCORE_MIN_PROVISIONAL_SCORE", 0.05),
    ):
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


def test_score_batch_enriches_intraday_short_trade_metrics_for_heavy_candidates():
    candidates = [_candidate("000001")]

    trend_signal = StrategySignal(
        direction=1,
        confidence=70.0,
        completeness=1.0,
        sub_factors={
            "momentum": {
                "direction": 1,
                "confidence": 75.0,
                "completeness": 1.0,
                "metrics": {"amount_ratio_5": 1.8},
            }
        },
    )

    intraday_bars = pd.DataFrame(
        {
            "时间": pd.date_range("2026-03-05 13:01:00", periods=120, freq="min"),
            "成交额": [1000.0] * 120,
        }
    )
    intraday_ticks = pd.DataFrame(
        [
            {"ticktime": "14:10:00", "price": 10.0, "volume": 100.0, "kind": "U"},
            {"ticktime": "14:20:00", "price": 10.0, "volume": 50.0, "kind": "D"},
            {"ticktime": "14:40:00", "price": 10.0, "volume": 200.0, "kind": "U"},
            {"ticktime": "14:50:00", "price": 10.0, "volume": 100.0, "kind": "D"},
            {"ticktime": "14:58:00", "price": 10.0, "volume": 150.0, "kind": "U"},
        ]
    )

    with (
        patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}),
        patch(
            "src.screening.strategy_scorer._compute_light_signals",
            return_value=(
                {
                    "trend": trend_signal,
                    "mean_reversion": _signal(0, 0, completeness=0.0),
                    "fundamental": _signal(0, 0, completeness=0.0),
                    "event_sentiment": _signal(0, 0, completeness=0.0),
                },
                None,
            ),
        ),
        patch("src.screening.strategy_scorer.score_fundamental_strategy", return_value=_signal(1, 65)),
        patch("src.screening.strategy_scorer.score_event_sentiment_strategy", return_value=_signal(1, 60)),
        patch("src.screening.strategy_scorer.get_intraday_bars", return_value=intraday_bars),
        patch("src.screening.strategy_scorer.get_intraday_ticks", return_value=intraday_ticks),
        patch("src.screening.strategy_scorer.get_lhb_detail", return_value=pd.DataFrame([{"代码": "000001"}])),
        patch("src.screening.strategy_scorer.get_lhb_institutional_stats", return_value=pd.DataFrame([{"代码": "000001", "机构买入净额": 1.0}])),
        patch("src.screening.strategy_scorer.FUNDAMENTAL_SCORE_MAX_CANDIDATES", 1),
        patch("src.screening.strategy_scorer.EVENT_SENTIMENT_MAX_CANDIDATES", 1),
        patch("src.screening.strategy_scorer.HEAVY_SCORE_MIN_PROVISIONAL_SCORE", 0.01),
    ):
        results = score_batch(candidates, "20260305")

    metrics = results["000001"]["trend"].sub_factors["momentum"]["metrics"]
    assert metrics["amount_ratio_5"] == pytest.approx(1.8)
    assert metrics["flow_60"] == pytest.approx(0.05)
    assert metrics["persist_120"] == pytest.approx(0.025)
    assert metrics["close_support_30"] == pytest.approx(round(2500.0 / 30000.0, 4))
    assert metrics["dragon_tiger_bonus"] == pytest.approx(1.0)


def test_populate_intraday_short_trade_metrics_caps_candidate_count():
    candidates = [_candidate("000001"), _candidate("000002"), _candidate("000003")]
    trend_signal = StrategySignal(
        direction=1,
        confidence=70.0,
        completeness=1.0,
        sub_factors={
            "momentum": {
                "direction": 1,
                "confidence": 75.0,
                "completeness": 1.0,
                "metrics": {"amount_ratio_5": 1.8},
            }
        },
    )
    results = {
        candidate.ticker: {
            "trend": StrategySignal.model_validate(trend_signal.model_dump()),
            "mean_reversion": _signal(0, 0, completeness=0.0),
            "fundamental": _signal(0, 0, completeness=0.0),
            "event_sentiment": _signal(0, 0, completeness=0.0),
        }
        for candidate in candidates
    }
    visited_tickers: list[str] = []

    def _fake_build_intraday_metrics(ticker: str, trade_date: str) -> dict[str, float]:
        visited_tickers.append(ticker)
        return {"flow_60": 0.1}

    with (
        patch("src.screening.strategy_scorer._build_intraday_short_trade_metrics", side_effect=_fake_build_intraday_metrics),
        patch("src.screening.strategy_scorer.INTRADAY_SCORE_MAX_CANDIDATES", 2),
    ):
        strategy_scorer_module._populate_intraday_short_trade_metrics(results, candidates, "20260305")

    assert visited_tickers == ["000001", "000002"]
    assert results["000001"]["trend"].sub_factors["momentum"]["metrics"]["flow_60"] == pytest.approx(0.1)
    assert results["000002"]["trend"].sub_factors["momentum"]["metrics"]["flow_60"] == pytest.approx(0.1)
    assert "flow_60" not in results["000003"]["trend"].sub_factors["momentum"]["metrics"]


def test_score_batch_enriches_sector_diffusion_metrics_for_industry_peers() -> None:
    candidates = [
        _candidate("000001"),
        _candidate("000002"),
        _candidate("000003"),
    ]
    for candidate in candidates:
        candidate.industry_sw = "AI算力"

    def _trend_with_momentum() -> StrategySignal:
        return StrategySignal(
            direction=1,
            confidence=70.0,
            completeness=1.0,
            sub_factors={
                "momentum": {
                    "direction": 1,
                    "confidence": 75.0,
                    "completeness": 1.0,
                    "metrics": {"amount_ratio_5": 1.2},
                }
            },
        )

    price_frames = {
        "000001": pd.DataFrame({"close": [10.0, 11.0]}),
        "000002": pd.DataFrame({"close": [10.0, 10.4]}),
        "000003": pd.DataFrame({"close": [10.0, 9.9]}),
    }

    def fake_light(candidate, trade_date):
        return (
            {
                "trend": _trend_with_momentum(),
                "mean_reversion": _signal(0, 0, completeness=0.0),
                "fundamental": _signal(0, 0, completeness=0.0),
                "event_sentiment": _signal(0, 0, completeness=0.0),
            },
            price_frames[candidate.ticker],
        )

    with (
        patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}),
        patch("src.screening.strategy_scorer._compute_light_signals", side_effect=fake_light),
        patch("src.screening.strategy_scorer.score_fundamental_strategy", return_value=_signal(1, 65)),
        patch("src.screening.strategy_scorer.score_event_sentiment_strategy", return_value=_signal(1, 60)),
        patch("src.screening.strategy_scorer.FUNDAMENTAL_SCORE_MAX_CANDIDATES", 3),
        patch("src.screening.strategy_scorer.EVENT_SENTIMENT_MAX_CANDIDATES", 3),
        patch("src.screening.strategy_scorer.HEAVY_SCORE_MIN_PROVISIONAL_SCORE", 0.01),
    ):
        results = score_batch(candidates, "20260305")

    for ticker in ("000001", "000002", "000003"):
        metrics = results[ticker]["trend"].sub_factors["momentum"]["metrics"]
        assert metrics["sector_breadth_3"] == pytest.approx(2.0 / 3.0, abs=1e-4)
        assert metrics["follow_ratio_2"] == pytest.approx(0.5, abs=1e-4)


def test_score_batch_enriches_sector_amount_share_metrics_for_industry_peers() -> None:
    candidates = [
        _candidate("000001"),
        _candidate("000002"),
        _candidate("000003"),
    ]
    candidates[0].industry_sw = "AI算力"
    candidates[1].industry_sw = "AI算力"
    candidates[2].industry_sw = "机器人"

    def _trend_with_momentum() -> StrategySignal:
        return StrategySignal(
            direction=1,
            confidence=70.0,
            completeness=1.0,
            sub_factors={
                "momentum": {
                    "direction": 1,
                    "confidence": 75.0,
                    "completeness": 1.0,
                    "metrics": {"amount_ratio_5": 1.2},
                }
            },
        )

    price_frames = {
        "000001": pd.DataFrame({"close": [10.0, 11.0], "amount": [400.0, 600.0]}),
        "000002": pd.DataFrame({"close": [10.0, 10.4], "amount": [200.0, 200.0]}),
        "000003": pd.DataFrame({"close": [10.0, 9.9], "amount": [300.0, 200.0]}),
    }

    def fake_light(candidate, trade_date):
        return (
            {
                "trend": _trend_with_momentum(),
                "mean_reversion": _signal(0, 0, completeness=0.0),
                "fundamental": _signal(0, 0, completeness=0.0),
                "event_sentiment": _signal(0, 0, completeness=0.0),
            },
            price_frames[candidate.ticker],
        )

    with (
        patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}),
        patch("src.screening.strategy_scorer._compute_light_signals", side_effect=fake_light),
        patch("src.screening.strategy_scorer.score_fundamental_strategy", return_value=_signal(1, 65)),
        patch("src.screening.strategy_scorer.score_event_sentiment_strategy", return_value=_signal(1, 60)),
        patch("src.screening.strategy_scorer.FUNDAMENTAL_SCORE_MAX_CANDIDATES", 3),
        patch("src.screening.strategy_scorer.EVENT_SENTIMENT_MAX_CANDIDATES", 3),
        patch("src.screening.strategy_scorer.HEAVY_SCORE_MIN_PROVISIONAL_SCORE", 0.01),
    ):
        results = score_batch(candidates, "20260305")

    assert results["000001"]["trend"].sub_factors["momentum"]["metrics"]["sector_amt_share"] == pytest.approx(0.8, abs=1e-4)
    assert results["000002"]["trend"].sub_factors["momentum"]["metrics"]["sector_amt_share"] == pytest.approx(0.8, abs=1e-4)
    assert results["000003"]["trend"].sub_factors["momentum"]["metrics"]["sector_amt_share"] == pytest.approx(0.2, abs=1e-4)


def test_build_intraday_short_trade_metrics_skips_ticks_when_bars_missing():
    with (
        patch("src.screening.strategy_scorer.get_intraday_bars", return_value=None),
        patch("src.screening.strategy_scorer.get_intraday_ticks", side_effect=AssertionError("ticks should not be fetched without bars")),
        patch("src.screening.strategy_scorer._load_daily_flow_proxy_ratio", return_value=0.12),
    ):
        metrics = strategy_scorer_module._build_intraday_short_trade_metrics("000001", "20260305")

    assert metrics == {
        "flow_60": pytest.approx(0.12),
        "flow_60_source": "daily_flow_proxy",
    }


def test_build_intraday_short_trade_metrics_uses_bar_proxy_without_fetching_ticks():
    timestamps = pd.date_range("2026-03-05 13:00:00", periods=121, freq="min")
    sign_steps = ([1] * 30) + ([-1] * 30) + ([1] * 20) + ([-1] * 10) + ([1] * 15) + ([-1] * 10) + ([0] * 5)
    closes = [10.0]
    for step in sign_steps:
        closes.append(round(closes[-1] + (0.1 * step), 4))
    intraday_bars = pd.DataFrame(
        {
            "时间": timestamps,
            "收盘": closes,
            "成交额": [0.0] + ([1000.0] * 120),
        }
    )

    with (
        patch("src.screening.strategy_scorer.get_intraday_bars", return_value=intraday_bars),
        patch("src.screening.strategy_scorer.get_intraday_ticks", side_effect=AssertionError("ticks should not be fetched when bar proxy is available")),
        patch("src.screening.strategy_scorer._load_daily_flow_proxy_ratio", return_value=None),
    ):
        metrics = strategy_scorer_module._build_intraday_short_trade_metrics("000001", "20260305")

    assert metrics == {
        "flow_60": pytest.approx(0.25),
        "close_support_30": pytest.approx(0.1667),
        "persist_120": pytest.approx(0.5417),
        "flow_60_source": "bar_proxy",
        "close_support_30_source": "bar_proxy",
        "persist_120_source": "bar_proxy",
    }


def test_score_batch_requires_positive_trend_confirmation_for_heavy_scoring():
    candidates = [_candidate("000001")]

    with (
        patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}),
        patch(
            "src.screening.strategy_scorer._compute_light_signals",
            return_value=(
                {
                    "trend": _signal(0, 0, completeness=1.0),
                    "mean_reversion": _signal(1, 90, completeness=1.0),
                    "fundamental": _signal(0, 0, completeness=0.0),
                    "event_sentiment": _signal(0, 0, completeness=0.0),
                },
                None,
            ),
        ),
        patch("src.screening.strategy_scorer.score_fundamental_strategy") as mock_fundamental,
        patch("src.screening.strategy_scorer.score_event_sentiment_strategy") as mock_event,
        patch("src.screening.strategy_scorer.HEAVY_SCORE_MIN_PROVISIONAL_SCORE", 0.05),
    ):
        results = score_batch(candidates, "20260305")

    mock_fundamental.assert_not_called()
    mock_event.assert_not_called()
    assert results["000001"]["fundamental"].completeness == 0.0
    assert results["000001"]["event_sentiment"].completeness == 0.0


def test_score_batch_allows_heavy_scoring_with_sufficient_trend_confirmation():
    candidates = [_candidate("000001")]

    with (
        patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}),
        patch(
            "src.screening.strategy_scorer._compute_light_signals",
            return_value=(
                {
                    "trend": _signal(1, 45, completeness=1.0),
                    "mean_reversion": _signal(0, 0, completeness=0.0),
                    "fundamental": _signal(0, 0, completeness=0.0),
                    "event_sentiment": _signal(0, 0, completeness=0.0),
                },
                None,
            ),
        ),
        patch("src.screening.strategy_scorer.score_fundamental_strategy", return_value=_signal(1, 70)),
        patch("src.screening.strategy_scorer.score_event_sentiment_strategy", return_value=_signal(1, 65)),
        patch("src.screening.strategy_scorer.HEAVY_SCORE_MIN_PROVISIONAL_SCORE", 0.05),
    ):
        results = score_batch(candidates, "20260305")

    assert results["000001"]["fundamental"].completeness == 1.0
    assert results["000001"]["event_sentiment"].completeness == 1.0


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


def test_score_batch_technical_stage_prefers_smaller_market_cap_within_same_liquidity_band():
    candidates = [
        _candidate("000001", avg_volume_20d=12000.0, market_cap=300.0),
        _candidate("000002", avg_volume_20d=11800.0, market_cap=80.0),
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
        patch("src.screening.strategy_scorer.TECHNICAL_SCORE_MAX_CANDIDATES", 1),
        patch("src.screening.strategy_scorer.FUNDAMENTAL_SCORE_MAX_CANDIDATES", 0),
        patch("src.screening.strategy_scorer.EVENT_SENTIMENT_MAX_CANDIDATES", 0),
    ):
        score_batch(candidates, "20260305")

    assert technical_calls == ["000002"]


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
        "days_since_positive_event": 1,
        "decay": pytest.approx(0.7046880897),
        "catalyst_freshness": pytest.approx(0.7046880897),
        "positive_hits": 5,
        "negative_hits": 0,
        "freshness_weight": 1.0,
    }


def test_score_industry_pe_returns_incomplete_without_industry_context():
    factor = fundamental_module._score_industry_pe(
        _financial_metrics(price_to_earnings_ratio=12.0),
        "",
        {"银行": 8.0},
    )

    assert factor.direction == 0
    assert factor.confidence == 0.0
    assert factor.completeness == 0.0


def test_score_industry_pe_marks_discounted_pe_as_bullish():
    factor = fundamental_module._score_industry_pe(
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
    monkeypatch.setattr(fundamental_module, "get_financial_metrics", lambda **kwargs: [])
    signal = score_fundamental_strategy("000001", "20260305")

    assert signal.direction == 0
    assert signal.confidence == 0.0
    assert signal.completeness == 0.0
    assert signal.sub_factors == {}


def test_score_fundamental_strategy_builds_and_caps_sub_factors(monkeypatch):
    latest = _financial_metrics(return_on_equity=0.18)
    older = _financial_metrics(report_period="20240930", revenue_growth=0.25)
    captured: dict[str, object] = {}

    monkeypatch.setattr(fundamental_module, "get_financial_metrics", lambda **kwargs: [latest, older])
    monkeypatch.setattr(fundamental_module, "_score_profitability", lambda metrics: SubFactor(name="profitability", direction=1, confidence=80.0, weight=0.25, metrics={"metric": metrics.report_period}))
    monkeypatch.setattr(fundamental_module, "_score_growth", lambda metrics_list: SubFactor(name="growth", direction=1, confidence=75.0, weight=0.25, metrics={"periods": len(metrics_list)}))
    monkeypatch.setattr(fundamental_module, "_score_financial_health", lambda metrics: SubFactor(name="financial_health", direction=1, confidence=70.0, weight=0.20, metrics={"metric": metrics.report_period}))
    monkeypatch.setattr(fundamental_module, "_score_growth_valuation", lambda metrics: SubFactor(name="growth_valuation", direction=0, confidence=50.0, weight=0.15, metrics={"metric": metrics.report_period}))
    monkeypatch.setattr(fundamental_module, "_score_industry_pe", lambda metrics, industry_name, medians: SubFactor(name="industry_pe", direction=-1, confidence=20.0, weight=0.15, metrics={"industry": industry_name, "median_count": len(medians or {})}))

    def fake_aggregate(factors):
        captured["factors"] = factors
        return StrategySignal(direction=1, confidence=88.0, completeness=1.0, sub_factors={})

    monkeypatch.setattr(fundamental_module, "aggregate_sub_factors", fake_aggregate)
    monkeypatch.setattr(
        fundamental_module,
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
        trend_module,
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
        trend_module,
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
        trend_module,
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
        trend_module,
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
        trend_module,
        "_get_trend_subfactor_weights",
        lambda: {
            "ema_alignment": 0.3,
            "adx_strength": 0.2,
            "momentum": 0.25,
            "volatility": 0.15,
            "long_trend_alignment": 0.1,
        },
    )
    monkeypatch.setattr(trend_module, "calculate_momentum_signals", lambda df: {"signal": "bullish", "confidence": 0.7, "metrics": {"mom": 1}})
    monkeypatch.setattr(trend_module, "calculate_volatility_signals", lambda df: {"signal": "bearish", "confidence": 0.4, "metrics": {"vol": 2}})
    monkeypatch.setattr(trend_module, "_score_ema_alignment", lambda df, weight: SubFactor(name="ema_alignment", direction=1, confidence=80.0, completeness=1.0, weight=weight, metrics={}))
    monkeypatch.setattr(trend_module, "_score_adx_strength", lambda df, weight: SubFactor(name="adx_strength", direction=1, confidence=25.0, completeness=1.0, weight=weight, metrics={}))
    monkeypatch.setattr(trend_module, "_score_long_trend_alignment", lambda df, weight: SubFactor(name="long_trend_alignment", direction=1, confidence=30.0, completeness=1.0, weight=weight, metrics={}))
    monkeypatch.setattr(trend_module, "aggregate_sub_factors", fake_aggregate)

    score_trend_strategy(prices_df)

    factor_names = [factor.name for factor in captured["factors"]]
    assert factor_names == ["ema_alignment", "adx_strength", "momentum", "volatility", "long_trend_alignment"]
    momentum = captured["factors"][2]
    volatility = captured["factors"][3]
    assert momentum.direction == 1 and momentum.confidence == 70.0 and momentum.completeness == 1.0
    assert volatility.direction == -1 and volatility.confidence == 40.0 and volatility.completeness == 1.0


def test_score_trend_strategy_surfaces_short_trade_doc_metrics() -> None:
    close = [10.0 + (0.01 * idx) for idx in range(130)]
    open_ = [value * 0.99 for value in close]
    high = [value * 1.01 for value in close]
    low = [value * 0.98 for value in close]
    volume = [100.0] * 129 + [300.0]
    amount = [100.0] * 129 + [300.0]

    for idx, breakout_high in ((120, 12.0), (124, 12.4), (129, 12.8)):
        open_[idx] = close[idx] + 0.4
        high[idx] = breakout_high
        low[idx] = close[idx] - 0.2

    prices_df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
        }
    )

    signal = score_trend_strategy(prices_df)
    metrics = signal.sub_factors["momentum"]["metrics"]

    assert metrics["failed_breakout_10"] == 3
    assert metrics["amount_ratio_5"] == pytest.approx(round(300.0 / 140.0, 4))
    expected_range = high[-1] - low[-1]
    expected_clv = (close[-1] - low[-1]) / expected_range
    expected_upper_shadow = (high[-1] - max(open_[-1], close[-1])) / expected_range
    assert metrics["close_structure"] == pytest.approx(round(expected_clv - (0.5 * expected_upper_shadow), 4))
    assert metrics["attack_slope_258"] > 0.0
    assert isinstance(metrics["breakout_quality_20_atr"], float)


def test_score_trend_strategy_surfaces_retention_metrics() -> None:
    close = [10.0 + (0.01 * idx) for idx in range(130)]
    open_ = [value * 0.99 for value in close]
    high = [value * 1.01 for value in close]
    low = [value * 0.98 for value in close]
    volume = [100.0] * 130
    amount = [price * volume[idx] for idx, price in enumerate(close)]

    prices_df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
        }
    )

    signal = score_trend_strategy(prices_df)
    metrics = signal.sub_factors["momentum"]["metrics"]

    expected_range = high[-1] - low[-1]
    expected_upper_shadow = (high[-1] - max(open_[-1], close[-1])) / expected_range
    expected_close_structure = (close[-1] - low[-1]) / expected_range - (0.5 * expected_upper_shadow)
    expected_retention_proxy = round((0.5 * expected_close_structure) + (0.3 * (1.0 - expected_upper_shadow)), 4)

    assert metrics["supply_pressure_60"] == pytest.approx(0.0)
    assert metrics["retention_proxy"] == pytest.approx(expected_retention_proxy)


def test_score_trend_strategy_surfaces_attention_turnover_and_limit_up_metrics() -> None:
    close = [10.0] * 130
    close[121] = 12.0
    close[122:126] = [12.0] * 4
    close[126] = 13.2
    close[127:] = [13.2] * 3

    prices_df = pd.DataFrame(
        {
            "open": [value * 0.99 for value in close],
            "high": [value * 1.01 for value in close],
            "low": [value * 0.98 for value in close],
            "close": close,
            "volume": [100.0] * 130,
            "amount": [100.0] * 130,
            "turnover_rate": ([2.0] * 129) + [5.0],
        }
    )

    signal = score_trend_strategy(prices_df, ticker="300001")
    metrics = signal.sub_factors["momentum"]["metrics"]

    assert metrics["turnover_ratio_20"] == pytest.approx(2.5)
    assert metrics["limit_up_memory_259"] == pytest.approx(0.2)
    assert metrics["ret_2d"] == pytest.approx(0.0)
    assert metrics["ret_5d"] == pytest.approx(0.1)


def test_score_trend_strategy_surfaces_gap_to_limit_metric() -> None:
    close = [10.0] * 129 + [10.95]
    prices_df = pd.DataFrame(
        {
            "open": [value * 0.99 for value in close],
            "high": [value * 1.01 for value in close],
            "low": [value * 0.98 for value in close],
            "close": close,
            "volume": [100.0] * 130,
            "amount": [price * 100.0 for price in close],
        }
    )

    signal = score_trend_strategy(prices_df, ticker="000001")
    metrics = signal.sub_factors["momentum"]["metrics"]

    assert metrics["gap_to_limit"] == pytest.approx(round((11.0 - 10.95) / 10.95, 4))


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

    with patch("src.screening.strategy_scorer_event_sentiment_helpers.get_company_news", return_value=news), patch("src.screening.strategy_scorer_event_sentiment_helpers.get_insider_trades", return_value=[]):
        signal = score_event_sentiment_strategy("000001", "20260305")

    assert signal.direction == 0
    assert signal.confidence == 0.0
    assert signal.sub_factors["news_sentiment"]["metrics"]["informative_articles"] == 0


def test_event_sentiment_keeps_fresh_multi_keyword_news_actionable():
    news = [_news_item("profit growth beat upgrade", "2026-03-05", "record order growth and profit beat")]

    with patch("src.screening.strategy_scorer_event_sentiment_helpers.get_company_news", return_value=news), patch("src.screening.strategy_scorer_event_sentiment_helpers.get_insider_trades", return_value=[]):
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

    import src.screening.strategy_scorer_event_sentiment_helpers as _esh

    monkeypatch.setattr(_esh, "get_company_news", fake_news_loader)
    monkeypatch.setattr(_esh, "get_insider_trades", fake_trades_loader)
    monkeypatch.setattr(_esh, "_score_news_sentiment", lambda items, trade_date: SubFactor(name="news_sentiment", direction=1, confidence=80.0, weight=0.55, metrics={"news_count": len(items), "trade_date": trade_date}))
    monkeypatch.setattr(_esh, "_score_insider_conviction", lambda items: SubFactor(name="insider_conviction", direction=1, confidence=40.0, weight=0.25, metrics={"trade_count": len(items)}))
    monkeypatch.setattr(_esh, "_score_event_freshness", lambda items, trade_date: SubFactor(name="event_freshness", direction=0, confidence=25.0, weight=0.20, metrics={"fresh_news_count": len(items), "trade_date": trade_date}))

    def fake_aggregate(factors):
        captured["factors"] = factors
        return StrategySignal(direction=1, confidence=61.0, completeness=1.0, sub_factors={})

    monkeypatch.setattr(strategy_scorer_module, "aggregate_sub_factors", fake_aggregate)
    monkeypatch.setattr(_esh, "aggregate_sub_factors", fake_aggregate)

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
    import src.screening.strategy_scorer_event_sentiment_helpers as _esh

    metrics = _esh._score_news_article(
        _news_item("profit growth beat", "2026-03-05", "record upgrade and contract"),
        datetime(2026, 3, 5),
    )

    assert metrics["days_old"] == 0
    assert metrics["direction"] == 1
    assert metrics["confidence"] > 45.0
    assert metrics["effective_weight"] == metrics["decay"]


def test_score_news_article_downweights_stale_negative_article():
    import src.screening.strategy_scorer_event_sentiment_helpers as _esh

    metrics = _esh._score_news_article(
        _news_item("downgrade warning", "2026-03-01", "fraud risk and weak demand"),
        datetime(2026, 3, 5),
    )

    assert metrics["days_old"] == 4
    assert metrics["direction"] == -1
    assert metrics["effective_weight"] < metrics["decay"]


def test_score_news_article_prior_day_morning_not_treated_as_today():
    """R119 lookahead family: news published the prior morning (2026-03-04T08:00:00)
    must NOT be scored as days_old==0 (today/freshest). trade_date midnight vs the
    article's kept time-of-day made ``timedelta(0.67).days == 0``, inflating freshness
    weight for a genuinely-prior-day article. Expected: prior day == 1 day old.
    """
    import src.screening.strategy_scorer_event_sentiment_helpers as _esh

    metrics = _esh._score_news_article(
        _news_item("profit growth beat", "2026-03-04T08:00:00", "record upgrade and contract"),
        datetime(2026, 3, 5),
    )

    assert metrics["days_old"] == 1


def test_score_news_article_same_day_after_decision_is_lookahead_not_freshest():
    """R119 lookahead family: an article timestamped AFTER midnight on the trade day
    (e.g. evening 2026-03-05T18:30:00) must not be privileged as fresher than a
    genuine prior-day article. Before the fix ``timedelta(-0.77).days == -1`` →
    ``max(-1,0)==0`` made the post-decision same-day article the freshest input.
    After the .date()-only comparison it is days_old==0 (same calendar day), which is
    acceptable because the per-source fetch already excludes articles strictly after
    end_date; the key guard is that a prior-day article (days_old==1) is NOT tied with
    it at 0, i.e. the lookahead floor no longer collapses prior-day to same-day.
    """
    import src.screening.strategy_scorer_event_sentiment_helpers as _esh

    prior_day = _esh._score_news_article(
        _news_item("profit growth beat", "2026-03-04T08:00:00", "record upgrade and contract"),
        datetime(2026, 3, 5),
    )
    post_decision = _esh._score_news_article(
        _news_item("profit growth beat", "2026-03-05T18:30:00", "record upgrade and contract"),
        datetime(2026, 3, 5),
    )

    # Prior-day article is strictly older; no longer tied at 0 days due to the floor bug.
    assert prior_day["days_old"] > post_decision["days_old"]


def test_resolve_event_freshness_days_old_prior_day_morning_is_one_day():
    """R119 lookahead family: _resolve_event_freshness_days_old shares the same
    midnight-trade_dt vs kept-time-of-day news_date bug as _resolve_news_article_days_old.
    Prior-day morning article must read as 1 day old, not 0.
    """
    import src.screening.strategy_scorer_event_sentiment_helpers as _esh

    assert _esh._resolve_event_freshness_days_old("2026-03-04T08:00:00", "20260305") == 1


def test_resolve_news_article_days_old_no_negative_timedelta_floor():
    """R119 lookahead family: direct helper guard. A same-calendar-day article with a
    late time-of-day (after the midnight trade_dt) must not floor to a negative delta
    that ``max(.., 0)`` then masks as 0 while a prior-day article is also mis-floored
    to 0. The same-day value is 0; the prior-day value is 1; they are now distinct.
    """
    import src.screening.strategy_scorer_event_sentiment_helpers as _esh

    assert _esh._resolve_news_article_days_old("2026-03-05T18:30:00", datetime(2026, 3, 5)) == 0
    assert _esh._resolve_news_article_days_old("2026-03-04T08:00:00", datetime(2026, 3, 5)) == 1


def test_resolve_news_article_days_old_parses_akshare_space_separated_format():
    """autodev-13 / loop 101: the akshare ``发布时间`` field (the A-share news
    source via build_company_news_entry) returns dates in SPACE-separated
    ``%Y-%m-%d %H:%M:%S`` format (e.g. "2026-07-03 11:22:00" — verified
    empirically via ak.stock_news_em). _safe_date only tried the T-separated
    ISO format (%Y-%m-%dT%H:%M:%S), so EVERY A-share article's date was
    unparseable → _resolve_news_article_days_old returned the 9999 sentinel
    → compute_event_decay(9999)≈0 → the event_sentiment factor was deaf to
    A-share article freshness model-wide (all 29 articles across all 7 tickers
    in report 20260703 carried days_old=9999).

    This is a data-correctness fix: add the space-separated format to _safe_date
    so the EXISTING freshness logic works as designed on A-share data. It does
    not change scoring semantics — the model was always designed to weight fresh
    articles higher; the parser gap silently zeroed that signal.
    """
    import src.screening.strategy_scorer_event_sentiment_helpers as _esh

    # Real akshare 发布时间 format (space-separated, verified via ak.stock_news_em).
    # A same-day article must resolve to 0 (freshest), NOT the 9999 sentinel.
    assert _esh._resolve_news_article_days_old("2026-07-03 11:22:00", datetime(2026, 7, 3)) == 0
    # A 2-day-old article must resolve to 2, NOT 9999.
    assert _esh._resolve_news_article_days_old("2026-07-01 09:00:00", datetime(2026, 7, 3)) == 2
    # The T-separated format (used by the financialdatasets.ai US-equity path)
    # must still parse (regression guard).
    assert _esh._resolve_news_article_days_old("2026-07-03T11:22:00", datetime(2026, 7, 3)) == 0


def test_score_mean_reversion_strategy_marks_rsi_oversold_bearish_post_ns4_flip():
    prices_df = pd.DataFrame({"close": [100.0] * 100})

    with (
        patch("src.screening.strategy_scorer_mean_reversion.calculate_mean_reversion_signals", return_value={"signal": "bullish", "confidence": 0.7, "metrics": {"z": -2.1}}),
        patch("src.screening.strategy_scorer_mean_reversion.calculate_stat_arb_signals", return_value={"signal": "neutral", "confidence": 0.2, "metrics": {}}),
        patch(
            "src.screening.strategy_scorer_mean_reversion.calculate_rsi",
            side_effect=[
                pd.Series([25.0] * len(prices_df)),
                pd.Series([35.0] * len(prices_df)),
            ],
        ),
        patch("src.screening.strategy_scorer_mean_reversion.calculate_hurst_exponent", return_value=0.4),
    ):
        signal = score_mean_reversion_strategy(prices_df)

    # NS-4 flip (autodev C225 sep=-2.15%): oversold RSI<30 → bearish (direction -1; was
    # +1 pre-flip when MR bet on mean reversion). Momentum dominates T+1 → oversold keeps falling.
    assert signal.sub_factors["rsi_extreme"]["direction"] == -1
    assert signal.sub_factors["rsi_extreme"]["metrics"] == {"rsi_14": 25.0, "rsi_28": 35.0}
    assert signal.sub_factors["hurst_regime"]["direction"] == 0
    assert signal.sub_factors["hurst_regime"]["metrics"]["hurst_exponent"] == 0.4


def test_score_mean_reversion_strategy_marks_insufficient_rsi_history_incomplete():
    prices_df = pd.DataFrame({"close": [100.0] * 20})

    with (
        patch("src.screening.strategy_scorer_mean_reversion.calculate_mean_reversion_signals", return_value=None),
        patch("src.screening.strategy_scorer_mean_reversion.calculate_stat_arb_signals", return_value=None),
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


# ---------------------------------------------------------------------------
# Parallelisation tests — verify ThreadPoolExecutor path matches serial path
# ---------------------------------------------------------------------------


def test_score_batch_parallel_produces_same_results_as_serial():
    """Parallel score_batch (concurrency>1) must produce identical results to serial (concurrency=1)."""
    candidates = [
        _candidate("000001", avg_volume_20d=30000.0, market_cap=300.0),
        _candidate("000002", avg_volume_20d=20000.0, market_cap=200.0),
        _candidate("000003", avg_volume_20d=10000.0, market_cap=100.0),
    ]
    trade_date = "20260305"

    def fake_light(candidate, trade_date):
        return {
            "trend": _signal(1, 70),
            "mean_reversion": _signal(0, 0, completeness=0.0),
            "fundamental": _signal(0, 0, completeness=0.0),
            "event_sentiment": _signal(0, 0, completeness=0.0),
        }, None

    def run_score_batch(concurrency: int) -> dict:
        with (
            patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}),
            patch("src.screening.strategy_scorer._compute_light_signals", side_effect=fake_light),
            patch("src.screening.strategy_scorer.score_fundamental_strategy", return_value=_signal(1, 65)),
            patch("src.screening.strategy_scorer.score_event_sentiment_strategy", return_value=_signal(1, 60)),
            patch("src.screening.strategy_scorer.TECHNICAL_SCORE_MAX_CANDIDATES", 3),
            patch("src.screening.strategy_scorer.FUNDAMENTAL_SCORE_MAX_CANDIDATES", 3),
            patch("src.screening.strategy_scorer.EVENT_SENTIMENT_MAX_CANDIDATES", 3),
            patch("src.screening.strategy_scorer.HEAVY_SCORE_MIN_PROVISIONAL_SCORE", 0.01),
            patch("src.screening.strategy_scorer.SCORE_BATCH_CONCURRENCY", concurrency),
        ):
            return score_batch(candidates, trade_date)

    serial_results = run_score_batch(concurrency=1)
    parallel_results = run_score_batch(concurrency=4)

    assert set(serial_results.keys()) == set(parallel_results.keys())
    for ticker in serial_results:
        for strategy_name in ("trend", "mean_reversion", "fundamental", "event_sentiment"):
            s = serial_results[ticker][strategy_name]
            p = parallel_results[ticker][strategy_name]
            assert s.direction == p.direction, f"{ticker}/{strategy_name} direction mismatch"
            assert s.confidence == pytest.approx(p.confidence), f"{ticker}/{strategy_name} confidence mismatch"
            assert s.completeness == pytest.approx(p.completeness), f"{ticker}/{strategy_name} completeness mismatch"


def test_score_batch_concurrency_env_var_respected():
    """SCORE_BATCH_CONCURRENCY env var should be read at module load time."""
    with patch.dict(os.environ, {"SCORE_BATCH_CONCURRENCY": "8"}):
        reloaded = importlib.reload(strategy_scorer_module)
        try:
            assert reloaded.SCORE_BATCH_CONCURRENCY == 8
        finally:
            importlib.reload(strategy_scorer_module)


def test_populate_intraday_parallel_produces_same_results_as_serial():
    """Parallel intraday metrics population must match serial results."""
    candidates = [_candidate("000001"), _candidate("000002")]

    def _trend_with_momentum() -> StrategySignal:
        return StrategySignal(
            direction=1,
            confidence=70.0,
            completeness=1.0,
            sub_factors={
                "momentum": {
                    "direction": 1,
                    "confidence": 75.0,
                    "completeness": 1.0,
                    "metrics": {"amount_ratio_5": 1.8},
                }
            },
        )

    def build_results():
        return {
            candidate.ticker: {
                "trend": StrategySignal.model_validate(_trend_with_momentum().model_dump()),
                "mean_reversion": _signal(0, 0, completeness=0.0),
                "fundamental": _signal(0, 0, completeness=0.0),
                "event_sentiment": _signal(0, 0, completeness=0.0),
            }
            for candidate in candidates
        }

    call_order: list[str] = []

    def fake_intraday(ticker, trade_date):
        call_order.append(ticker)
        return {"flow_60": 0.1234}

    # Serial
    serial_results = build_results()
    with (
        patch("src.screening.strategy_scorer._build_intraday_short_trade_metrics", side_effect=fake_intraday),
        patch("src.screening.strategy_scorer.INTRADAY_SCORE_MAX_CANDIDATES", 2),
        patch("src.screening.strategy_scorer.SCORE_BATCH_CONCURRENCY", 1),
    ):
        strategy_scorer_module._populate_intraday_short_trade_metrics(serial_results, candidates, "20260305")
    assert call_order == ["000001", "000002"]

    # Parallel
    call_order.clear()
    parallel_results = build_results()
    with (
        patch("src.screening.strategy_scorer._build_intraday_short_trade_metrics", side_effect=fake_intraday),
        patch("src.screening.strategy_scorer.INTRADAY_SCORE_MAX_CANDIDATES", 2),
        patch("src.screening.strategy_scorer.SCORE_BATCH_CONCURRENCY", 4),
    ):
        strategy_scorer_module._populate_intraday_short_trade_metrics(parallel_results, candidates, "20260305")

    # Results must be identical regardless of execution order
    for ticker in ("000001", "000002"):
        serial_m = serial_results[ticker]["trend"].sub_factors["momentum"]["metrics"]
        parallel_m = parallel_results[ticker]["trend"].sub_factors["momentum"]["metrics"]
        assert serial_m["flow_60"] == pytest.approx(parallel_m["flow_60"])


def test_parallel_handles_individual_candidate_failure_gracefully():
    """If one candidate's light-signal computation fails, others must still succeed."""
    candidates = [
        _candidate("000001", avg_volume_20d=30000.0, market_cap=300.0),
        _candidate("000002", avg_volume_20d=20000.0, market_cap=200.0),
    ]

    def fake_light(candidate, trade_date):
        if candidate.ticker == "000001":
            raise RuntimeError("Simulated IO failure")
        return {
            "trend": _signal(1, 70),
            "mean_reversion": _signal(0, 0, completeness=0.0),
            "fundamental": _signal(0, 0, completeness=0.0),
            "event_sentiment": _signal(0, 0, completeness=0.0),
        }, None

    with (
        patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}),
        patch("src.screening.strategy_scorer._compute_light_signals", side_effect=fake_light),
        patch("src.screening.strategy_scorer.FUNDAMENTAL_SCORE_MAX_CANDIDATES", 0),
        patch("src.screening.strategy_scorer.EVENT_SENTIMENT_MAX_CANDIDATES", 0),
        patch("src.screening.strategy_scorer.SCORE_BATCH_CONCURRENCY", 4),
    ):
        results = score_batch(candidates, "20260305")

    # Failed candidate gets empty signal fallback (direction=0, completeness=0)
    assert results["000001"]["trend"].direction == 0
    assert results["000001"]["trend"].completeness == 0.0
    # Healthy candidate still scored correctly
    assert results["000002"]["trend"].direction == 1
    assert results["000002"]["trend"].confidence == 70.0


def test_light_weights_trend_dominates_reversed_mr() -> None:
    """C226 revert: 全 universe 诊断 (C225 n=8901/sub-factor) 证实 MR 全 4 sub-factor 与
    T+1 反向 (sep<0, IC=-0.128); _backtest_light_stage_universe 显示 MR-heavy (0.65)
    跑输 trend-heavy (daily excess -0.28%). mean-reversion bet 在 T+1 horizon 失败
    (短期 momentum 主导). Light stage 权重应让 trend (正向有效) 主导, MR 降权.
    """
    from src.screening.strategy_scorer import LIGHT_STRATEGY_WEIGHTS

    mr_w = LIGHT_STRATEGY_WEIGHTS.get("mean_reversion", 0.0)
    trend_w = LIGHT_STRATEGY_WEIGHTS.get("trend", 0.0)
    assert trend_w >= 0.55, f"trend weight={trend_w} 应 >= 0.55 (C225: MR reversed IC=-0.128; trend 正向有效). " f"当前 trend={trend_w}, MR={mr_w}"
    assert trend_w > mr_w, f"trend weight={trend_w} 必须 > MR={mr_w}. " f"MR 全 4 sub-factor 与 T+1 反向 (C225 IC=-0.128), 不应主导 light score."
    # 权重之和必须为 1.0 (light stage 只有这两个策略)
    assert mr_w + trend_w == 1.0, f"权重和必须为 1.0, got {mr_w + trend_w}"
