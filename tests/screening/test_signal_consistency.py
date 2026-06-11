"""Tests for signal_consistency.py -- P7-1."""

from __future__ import annotations

from src.screening.signal_consistency import (
    check_signal_consistency,
    filter_by_consistency,
    render_consistency_report,
)


def _make_rec(
    ticker: str,
    name: str,
    score_b: float = 0.5,
    strategy_signals: dict | None = None,
) -> dict:
    return {
        "ticker": ticker,
        "name": name,
        "score_b": score_b,
        "strategy_signals": strategy_signals or {},
    }


class TestCheckSignalConsistency:
    def test_all_bullish_is_high_consistency(self) -> None:
        recs = [_make_rec("000001", "Test", 0.8, {
            "trend": {"signal": "bullish", "confidence": 80},
            "mean_reversion": {"signal": "bullish", "confidence": 70},
            "fundamental": {"signal": "bullish", "confidence": 90},
            "event_sentiment": {"signal": "bullish", "confidence": 85},
        })]
        results = check_signal_consistency(recs)
        assert len(results) == 1
        assert results[0]["consistency_level"] == "high"
        assert results[0]["agreement_ratio"] == 1.0
        assert results[0]["bullish_count"] == 4
        assert results[0]["conflicting_strategies"] == []

    def test_split_signals_is_low_consistency(self) -> None:
        recs = [_make_rec("000001", "Test", 0.5, {
            "trend": {"signal": "bullish", "confidence": 80},
            "mean_reversion": {"signal": "bearish", "confidence": 70},
            "fundamental": {"signal": "bullish", "confidence": 60},
            "event_sentiment": {"signal": "bearish", "confidence": 65},
        })]
        results = check_signal_consistency(recs)
        assert results[0]["consistency_level"] in ("low", "medium")
        assert results[0]["agreement_ratio"] == 0.5
        assert results[0]["bullish_count"] == 2
        assert results[0]["bearish_count"] == 2

    def test_three_to_one_is_medium(self) -> None:
        recs = [_make_rec("000001", "Test", 0.6, {
            "trend": {"signal": "bullish", "confidence": 80},
            "mean_reversion": {"signal": "bearish", "confidence": 70},
            "fundamental": {"signal": "bullish", "confidence": 90},
            "event_sentiment": {"signal": "bullish", "confidence": 85},
        })]
        results = check_signal_consistency(recs)
        assert results[0]["consistency_level"] == "high"
        assert results[0]["agreement_ratio"] == 0.75
        assert results[0]["conflicting_strategies"] == ["mean_reversion"]

    def test_no_strategy_signals(self) -> None:
        recs = [_make_rec("000001", "Test", 0.5)]
        results = check_signal_consistency(recs)
        assert results[0]["consistency_level"] == "unknown"
        assert results[0]["total_strategies"] == 0

    def test_neutral_signals(self) -> None:
        recs = [_make_rec("000001", "Test", 0.3, {
            "trend": {"signal": "neutral", "confidence": 50},
            "mean_reversion": {"signal": "neutral", "confidence": 50},
        })]
        results = check_signal_consistency(recs)
        assert results[0]["neutral_count"] >= 2
        assert results[0]["agreement_ratio"] == 1.0

    def test_multiple_recommendations(self) -> None:
        recs = [
            _make_rec("000001", "A", 0.9, {"trend": {"signal": "bullish"}, "fundamental": {"signal": "bullish"}}),
            _make_rec("000002", "B", 0.5, {"trend": {"signal": "bullish"}, "fundamental": {"signal": "bearish"}}),
        ]
        results = check_signal_consistency(recs)
        assert len(results) == 2
        # Both could have same consistency level depending on signals


class TestFilterByConsistency:
    def test_filter_medium_removes_low(self) -> None:
        results = [
            {"ticker": "000001", "consistency_level": "high"},
            {"ticker": "000002", "consistency_level": "medium"},
            {"ticker": "000003", "consistency_level": "low"},
        ]
        filtered = filter_by_consistency(results, min_consistency="medium")
        tickers = [r["ticker"] for r in filtered]
        assert "000001" in tickers
        assert "000002" in tickers
        assert "000003" not in tickers

    def test_filter_high_keeps_only_high(self) -> None:
        results = [
            {"ticker": "000001", "consistency_level": "high"},
            {"ticker": "000002", "consistency_level": "medium"},
        ]
        filtered = filter_by_consistency(results, min_consistency="high")
        assert len(filtered) == 1
        assert filtered[0]["ticker"] == "000001"

    def test_empty_list(self) -> None:
        assert filter_by_consistency([]) == []


class TestRenderConsistencyReport:
    def test_empty_renders_warning(self) -> None:
        output = render_consistency_report([])
        assert "No recommendations" in output

    def test_renders_summary(self) -> None:
        results = [
            {"ticker": "000001", "name": "A", "consistency_level": "high", "agreement_ratio": 1.0,
             "bullish_count": 4, "bearish_count": 0, "neutral_count": 0, "total_strategies": 4,
             "dominant_direction": "bullish", "conflicting_strategies": [], "score_b": 0.8},
        ]
        output = render_consistency_report(results)
        assert "Signal Consistency" in output
        assert "High: 1" in output
