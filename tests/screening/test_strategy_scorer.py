from unittest.mock import patch

from src.screening.models import CandidateStock, StrategySignal
from src.screening.strategy_scorer import score_batch


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

    with patch("src.screening.strategy_scorer._build_industry_pe_medians", return_value={}), \
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
         ), \
         patch("src.screening.strategy_scorer.score_fundamental_strategy") as mock_fundamental, \
         patch("src.screening.strategy_scorer.score_event_sentiment_strategy") as mock_event, \
         patch("src.screening.strategy_scorer.HEAVY_SCORE_MIN_PROVISIONAL_SCORE", 0.2):
        results = score_batch(candidates, "20260305")

    mock_fundamental.assert_not_called()
    mock_event.assert_not_called()
    assert set(results["000001"].keys()) == {"trend", "mean_reversion", "fundamental", "event_sentiment"}
    assert results["000001"]["fundamental"].completeness == 0.0
    assert results["000001"]["event_sentiment"].completeness == 0.0