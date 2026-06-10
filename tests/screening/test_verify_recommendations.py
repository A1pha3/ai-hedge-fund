"""Tests for P3-1: verify_recommendations module."""
import json
import pytest
from pathlib import Path

from src.screening.verify_recommendations import (
    VerifySummary,
    VerifyDay,
    StrategyAttribution,
    compute_verify_recommendations,
    render_verify_recommendations,
    _extract_tracking_returns,
    _load_tracking_history,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    """Create a temp reports dir with sample data."""
    # tracking_history.json
    tracking = [
        {"ticker": "000001", "name": "平安银行", "recommended_date": "20260601", "recommended_price": 12.0, "next_day_return": 2.0, "next_3day_return": 3.5, "next_5day_return": 5.0, "tracking_status": "complete"},
        {"ticker": "600519", "name": "贵州茅台", "recommended_date": "20260601", "recommended_price": 1500.0, "next_day_return": -1.0, "next_3day_return": 2.0, "next_5day_return": -0.5, "tracking_status": "complete"},
        {"ticker": "300724", "name": "捷佳伟创", "recommended_date": "20260602", "recommended_price": 50.0, "next_day_return": 1.5, "next_3day_return": None, "next_5day_return": None, "tracking_status": "partial"},
    ]
    (tmp_path / "tracking_history.json").write_text(json.dumps(tracking), encoding="utf-8")

    # auto_screening_20260601.json
    report1 = {
        "trade_date": "20260601",
        "recommendations": [
            {"ticker": "000001", "name": "平安银行", "score_b": 0.8, "decision": "bullish",
             "strategy_signals": {"trend": {"direction": 1, "confidence": 80}, "fundamental": {"direction": 1, "confidence": 60}}},
            {"ticker": "600519", "name": "贵州茅台", "score_b": 0.6, "decision": "bullish",
             "strategy_signals": {"mean_reversion": {"direction": -1, "confidence": 70}}},
        ],
    }
    (tmp_path / "auto_screening_20260601.json").write_text(json.dumps(report1), encoding="utf-8")

    # auto_screening_20260602.json
    report2 = {
        "trade_date": "20260602",
        "recommendations": [
            {"ticker": "300724", "name": "捷佳伟创", "score_b": 0.7, "decision": "bullish",
             "strategy_signals": {"trend": {"direction": 1, "confidence": 75}}},
        ],
    }
    (tmp_path / "auto_screening_20260602.json").write_text(json.dumps(report2), encoding="utf-8")

    return tmp_path


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestExtractTrackingReturns:
    def test_found(self):
        tracking = [
            {"ticker": "000001", "recommended_date": "20260601", "next_day_return": 2.0, "next_3day_return": 3.5, "next_5day_return": 5.0},
        ]
        t1, t3, t5 = _extract_tracking_returns(tracking, "000001", "20260601")
        assert t1 == 2.0
        assert t3 == 3.5
        assert t5 == 5.0

    def test_not_found(self):
        tracking = [{"ticker": "000001", "recommended_date": "20260601"}]
        t1, t3, t5 = _extract_tracking_returns(tracking, "999999", "20260601")
        assert t1 is None
        assert t3 is None
        assert t5 is None

    def test_none_values(self):
        tracking = [
            {"ticker": "000001", "recommended_date": "20260601", "next_day_return": None, "next_3day_return": None},
        ]
        t1, t3, t5 = _extract_tracking_returns(tracking, "000001", "20260601")
        assert t1 is None
        assert t3 is None


class TestLoadTrackingHistory:
    def test_loads_valid(self, reports_dir: Path):
        result = _load_tracking_history(reports_dir)
        assert len(result) == 3

    def test_returns_empty_for_missing(self, tmp_path: Path):
        result = _load_tracking_history(tmp_path / "nonexistent")
        assert result == []

    def test_handles_corrupt(self, tmp_path: Path):
        (tmp_path / "tracking_history.json").write_text("not json{{{", encoding="utf-8")
        result = _load_tracking_history(tmp_path)
        assert result == []


class TestComputeVerifyRecommendations:
    def test_basic_computation(self, reports_dir: Path):
        summary = compute_verify_recommendations(reports_dir=reports_dir, lookback_days=30)
        assert summary.total_days == 2
        assert summary.total_recommendations == 3
        assert summary.unique_tickers == 3

    def test_t1_win_rate(self, reports_dir: Path):
        summary = compute_verify_recommendations(reports_dir=reports_dir, lookback_days=30)
        # 000001: +2.0 (win), 600519: -1.0 (loss), 300724: +1.5 (win) → 2/3 = 66.7%
        assert summary.overall_t1_win_rate is not None
        assert abs(summary.overall_t1_win_rate - 2 / 3) < 0.01

    def test_avg_t1_return(self, reports_dir: Path):
        summary = compute_verify_recommendations(reports_dir=reports_dir, lookback_days=30)
        # (2.0 + (-1.0) + 1.5) / 3 = 0.833...
        assert summary.avg_t1_return is not None
        assert abs(summary.avg_t1_return - (2.0 - 1.0 + 1.5) / 3) < 0.01

    def test_strategy_attribution(self, reports_dir: Path):
        summary = compute_verify_recommendations(reports_dir=reports_dir, lookback_days=30)
        assert len(summary.strategy_attribution) > 0
        # trend has 000001 (+2.0) and 300724 (+1.5) → avg = 1.75
        trend = next((s for s in summary.strategy_attribution if s.strategy_name == "trend"), None)
        assert trend is not None
        assert trend.recommendation_count == 2

    def test_detail_mode(self, reports_dir: Path):
        summary = compute_verify_recommendations(reports_dir=reports_dir, lookback_days=30, include_detail=True)
        assert len(summary.daily_details) == 2
        # Reports are sorted newest-first
        dates = [d.date for d in summary.daily_details]
        assert "20260601" in dates
        assert "20260602" in dates

    def test_empty_dir(self, tmp_path: Path):
        summary = compute_verify_recommendations(reports_dir=tmp_path / "empty", lookback_days=30)
        assert summary.total_days == 0
        assert summary.total_recommendations == 0

    def test_no_tracking(self, tmp_path: Path):
        """Reports exist but no tracking history."""
        report = {"trade_date": "20260601", "recommendations": [{"ticker": "000001", "score_b": 0.8}]}
        (tmp_path / "auto_screening_20260601.json").write_text(json.dumps(report), encoding="utf-8")
        summary = compute_verify_recommendations(reports_dir=tmp_path, lookback_days=30)
        assert summary.total_days == 1
        assert summary.avg_t1_return is None  # No tracking data


class TestRenderVerifyRecommendations:
    def test_renders_basic(self, reports_dir: Path):
        summary = compute_verify_recommendations(reports_dir=reports_dir, lookback_days=30)
        output = render_verify_recommendations(summary)
        assert "推荐闭环验证" in output
        assert "近 30 天" in output
        assert "策略归因" in output

    def test_renders_empty(self):
        summary = VerifySummary()
        output = render_verify_recommendations(summary)
        assert "无推荐数据" in output

    def test_renders_with_detail(self, reports_dir: Path):
        summary = compute_verify_recommendations(reports_dir=reports_dir, lookback_days=30, include_detail=True)
        output = render_verify_recommendations(summary)
        assert "推荐闭环验证" in output
