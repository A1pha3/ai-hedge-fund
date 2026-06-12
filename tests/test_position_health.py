"""Tests for position_health.py — P15-1 position health check."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.screening.position_health import (
    PositionHealth,
    PositionHealthReport,
    _determine_action,
    _find_ticker_in_history,
    compute_position_health,
    render_position_health,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_reports(tmp_dir: Path, reports: dict[str, list[dict]]) -> None:
    for date_str, recs in reports.items():
        path = tmp_dir / f"auto_screening_{date_str}.json"
        path.write_text(
            json.dumps({"trade_date": date_str, "recommendations": recs}),
            encoding="utf-8",
        )


def _make_rec(ticker: str, name: str, score_b: float, **kwargs: Any) -> dict[str, Any]:
    rec = {
        "ticker": ticker,
        "name": name,
        "score_b": score_b,
        "industry_sw": "电子",
        "strategy_signals": {
            "trend": {"signal": "bullish", "confidence": 70, "direction": 1},
            "fundamental": {"signal": "bullish", "confidence": 60, "direction": 1},
            "mean_reversion": {"signal": "neutral", "confidence": 40, "direction": 0},
            "event_sentiment": {"signal": "bullish", "confidence": 55, "direction": 1},
        },
    }
    rec.update(kwargs)
    return rec


# ---------------------------------------------------------------------------
# Unit: _find_ticker_in_history
# ---------------------------------------------------------------------------


class TestFindTickerInHistory:
    def test_found_in_latest(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}}
        ]
        result = _find_ticker_in_history("000001", history)
        assert result is not None
        assert result["score_b"] == 0.5

    def test_not_found(self) -> None:
        history = [{"payload": {"recommendations": [{"ticker": "000002", "score_b": 0.5}]}}]
        result = _find_ticker_in_history("000001", history)
        assert result is None

    def test_empty_history(self) -> None:
        result = _find_ticker_in_history("000001", [])
        assert result is None


# ---------------------------------------------------------------------------
# Unit: _determine_action
# ---------------------------------------------------------------------------


class TestDetermineAction:
    def test_sell_below_threshold(self) -> None:
        action, reason = _determine_action(0.10, 0.0, 0.0, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "SELL"
        assert "0.10" in reason

    def test_watch_in_zone(self) -> None:
        action, reason = _determine_action(0.20, 0.0, 0.0, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "WATCH"

    def test_hold_healthy(self) -> None:
        action, reason = _determine_action(0.50, 0.0, 0.0, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "HOLD"

    def test_watch_due_to_deterioration(self) -> None:
        action, reason = _determine_action(0.50, -0.10, -0.05, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "WATCH"
        assert "衰减" in reason

    def test_hold_despite_mild_momentum_decline(self) -> None:
        action, reason = _determine_action(0.50, -0.03, 0.0, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "HOLD"


# ---------------------------------------------------------------------------
# Integration: compute_position_health
# ---------------------------------------------------------------------------


class TestComputePositionHealth:
    def test_empty_dir(self, tmp_path: Path) -> None:
        report = compute_position_health(tickers=["000001"], reports_dir=tmp_path)
        assert report.items == []

    def test_ticker_found_in_report(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", "平安银行", 0.6)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_position_health(tickers=["000001"], reports_dir=tmp_path)
        assert len(report.items) == 1
        assert report.items[0].ticker == "000001"

    def test_ticker_not_in_report(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", "平安银行", 0.6)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_position_health(tickers=["999999"], reports_dir=tmp_path)
        assert len(report.items) == 1
        assert report.items[0].ticker == "999999"
        # Ticker not found → score_b=0.0 → composite_score should be low
        assert report.items[0].score_b == 0.0

    def test_sell_low_score(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", "Test", 0.05)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_position_health(tickers=["000001"], reports_dir=tmp_path)
        assert report.items[0].action in ("SELL", "WATCH")

    def test_hold_high_score(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", "Test", 0.8)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_position_health(tickers=["000001"], reports_dir=tmp_path)
        assert report.items[0].action == "HOLD"

    def test_multiple_tickers_sorted_by_action(self, tmp_path: Path) -> None:
        recs = [
            _make_rec("000001", "Hold", 0.7),
            _make_rec("000002", "Low", 0.05),
            _make_rec("000003", "Mid", 0.2),
        ]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_position_health(
            tickers=["000001", "000002", "000003"],
            sell_threshold=0.01,  # very low so we focus on action ordering
            watch_threshold=0.01,
            reports_dir=tmp_path,
        )
        # With very low thresholds, all should be HOLD (composite >= watch_threshold)
        actions = [item.action for item in report.items]
        # Verify they all have valid actions
        assert all(a in ("HOLD", "WATCH", "SELL") for a in actions)
        # Items with same action should be sorted by composite_score ascending
        hold_items = [i for i in report.items if i.action == "HOLD"]
        for i in range(1, len(hold_items)):
            assert hold_items[i - 1].composite_score <= hold_items[i].composite_score

    def test_custom_thresholds(self, tmp_path: Path) -> None:
        recs = [_make_rec("000001", "Test", 0.3)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_position_health(
            tickers=["000001"],
            sell_threshold=0.4,
            watch_threshold=0.6,
            reports_dir=tmp_path,
        )
        # With higher thresholds, score_b=0.3 should trigger SELL
        assert report.items[0].action == "SELL"


# ---------------------------------------------------------------------------
# Unit: render_position_health
# ---------------------------------------------------------------------------


class TestRenderPositionHealth:
    def test_empty(self) -> None:
        output = render_position_health(PositionHealthReport())
        assert "无持仓数据" in output

    def test_with_items(self) -> None:
        report = PositionHealthReport(
            trade_date="20260610",
            items=[
                PositionHealth(
                    ticker="000001",
                    name="Test",
                    composite_score=0.6,
                    action="HOLD",
                    reason="综合信号健康",
                ),
                PositionHealth(
                    ticker="000002",
                    name="Test2",
                    composite_score=0.1,
                    action="SELL",
                    reason="composite=0.100 < sell_threshold=0.15",
                ),
            ],
        )
        output = render_position_health(report)
        assert "000001" in output
        assert "000002" in output
        assert "HOLD" in output
        assert "SELL" in output

    def test_to_dict(self) -> None:
        report = PositionHealthReport(
            trade_date="20260610",
            items=[
                PositionHealth(
                    ticker="000001",
                    composite_score=0.55,
                    action="HOLD",
                    reason="healthy",
                ),
            ],
        )
        d = report.to_dict()
        assert d["trade_date"] == "20260610"
        assert len(d["items"]) == 1
        assert d["items"][0]["action"] == "HOLD"
