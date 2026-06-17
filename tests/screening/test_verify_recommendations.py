"""Tests for P3-1: verify_recommendations module."""
import json
from pathlib import Path

import pytest

from src.screening.recommendation_tracker import _save_history
from src.screening.verify_recommendations import (
    _extract_tracking_returns,
    _load_auto_screening_reports,
    _load_tracking_history,
    compute_verify_recommendations,
    render_verify_recommendations,
    VerifySummary,
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
        t1, t3, t5, t10, t20, t30 = _extract_tracking_returns(tracking, "000001", "20260601")
        assert t1 == 2.0
        assert t3 == 3.5
        assert t5 == 5.0
        assert t10 is None
        assert t20 is None
        assert t30 is None

    def test_not_found(self):
        tracking = [{"ticker": "000001", "recommended_date": "20260601"}]
        t1, t3, t5, t10, t20, t30 = _extract_tracking_returns(tracking, "999999", "20260601")
        assert t1 is None
        assert t3 is None
        assert t5 is None
        assert t10 is None
        assert t20 is None
        assert t30 is None

    def test_none_values(self):
        tracking = [
            {"ticker": "000001", "recommended_date": "20260601", "next_day_return": None, "next_3day_return": None},
        ]
        t1, t3, t5, t10, t20, t30 = _extract_tracking_returns(tracking, "000001", "20260601")
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

    def test_load_auto_screening_anchors_to_latest_report_not_now(self, tmp_path: Path) -> None:
        """BH-018 / R36 same-class: the lookback cutoff must be anchored to the
        LATEST report date in the directory, not wall-clock ``datetime.now()``.

        Previously the cutoff used ``now() - (lookback+10)``, so any report
        older than ~40 days from today was silently dropped — breaking
        backfilled / historical analysis (all-old-data dirs returned empty
        despite having in-window reports relative to their own latest date).
        """
        # Reports dated 2026-01-10..12 — all "old" relative to a June 2026
        # wall-clock now, but consecutive relative to each other.
        for date_str in ("20260110", "20260111", "20260112"):
            (tmp_path / f"auto_screening_{date_str}.json").write_text(
                json.dumps({"recommendations": []}), encoding="utf-8"
            )
        result = _load_auto_screening_reports(tmp_path, lookback_days=30)
        # All three must be loaded (anchored to latest 20260112, not now()).
        assert len(result) == 3, f"Expected 3 reports (anchored to latest), got {len(result)}"

    def test_loads_tracker_payload_shape(self, tmp_path: Path):
        history_path = tmp_path / "tracking_history.json"
        records = [
            {
                "ticker": "000001",
                "recommended_date": "20260601",
                "next_day_return": 2.0,
                "tracking_status": "complete",
            }
        ]

        _save_history(history_path, records)

        result = _load_tracking_history(tmp_path)
        assert result == records


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

    def test_summary_aggregates_benchmark_and_excess_return(self, reports_dir: Path):
        """Regression (BETA-009): ``benchmark_avg_t1`` and ``excess_return`` are
        declared schema fields on VerifySummary but were never assigned in the
        aggregate, so the front-door ``超额收益`` line in top_picks.py was dead
        code. They must now be populated.

        Per-day cross-section-average "benchmark" (the picks' own mean):
          20260601: (2.0 + (-1.0)) / 2 = 0.5
          20260602: 1.5
        => benchmark_avg_t1 = (0.5 + 1.5) / 2 = 1.0 (day-weighted)
        basket_avg_t1 (per-day pick-mean, same data) = (0.5 + 1.5) / 2 = 1.0
        => excess_return = 1.0 - 1.0 = 0.0 (this fixture has benchmark ≡ basket mean).
        The weighting-consistency invariant is pinned by
        test_excess_return_uses_consistent_day_weighted_basis below with a
        divergent fixture.
        """
        summary = compute_verify_recommendations(reports_dir=reports_dir, lookback_days=30)
        assert summary.benchmark_avg_t1 is not None
        assert abs(summary.benchmark_avg_t1 - 1.0) < 0.01
        assert summary.excess_return is not None
        assert abs(summary.excess_return - 0.0) < 0.01

    def test_excess_return_uses_consistent_day_weighted_basis(self, tmp_path: Path):
        """Regression (BETA-009-drain): ``excess_return`` previously subtracted
        ``summary.avg_t1_return`` (a pick-weighted mean — every pick pooled
        across all days) from ``summary.benchmark_avg_t1`` (a day-weighted mean
        — mean of per-day basket means). When pick counts vary per day the two
        averages differ and the subtraction is meaningless.

        Fixture engineered so benchmark ≠ basket mean on at least one day, and
        daily pick counts differ, so the two weighting schemes diverge:

          Day A (2 picks): basket mean = 0.5, benchmark = 0.5
          Day B (1 pick):  basket mean = 3.0, benchmark = 3.0

        Day-weighted basket mean = (0.5 + 3.0) / 2 = 1.75
        Day-weighted benchmark    = (0.5 + 3.0) / 2 = 1.75
        => correct excess_return = 0.0

        Pick-weighted avg_t1_return = (2.0 + (-1.0) + 3.0) / 3 = 1.333
        Old (buggy) excess_return  = 1.333 - 1.75 = -0.4167  ← meaningless mix
        """
        tracking = [
            {"ticker": "000001", "recommended_date": "20260601", "next_day_return": 2.0, "tracking_status": "complete"},
            {"ticker": "600519", "recommended_date": "20260601", "next_day_return": -1.0, "tracking_status": "complete"},
            {"ticker": "300724", "recommended_date": "20260602", "next_day_return": 3.0, "tracking_status": "complete"},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps(tracking), encoding="utf-8")
        report1 = {"trade_date": "20260601", "recommendations": [
            {"ticker": "000001", "score_b": 0.8, "strategy_signals": {"trend": {"direction": 1, "confidence": 80}}},
            {"ticker": "600519", "score_b": 0.6, "strategy_signals": {"mean_reversion": {"direction": -1, "confidence": 70}}},
        ]}
        (tmp_path / "auto_screening_20260601.json").write_text(json.dumps(report1), encoding="utf-8")
        report2 = {"trade_date": "20260602", "recommendations": [
            {"ticker": "300724", "score_b": 0.7, "strategy_signals": {"trend": {"direction": 1, "confidence": 75}}},
        ]}
        (tmp_path / "auto_screening_20260602.json").write_text(json.dumps(report2), encoding="utf-8")

        summary = compute_verify_recommendations(reports_dir=tmp_path, lookback_days=30)
        # pick-weighted (would be the buggy basis)
        assert abs(summary.avg_t1_return - (2.0 - 1.0 + 3.0) / 3) < 0.01
        # day-weighted benchmark
        assert summary.benchmark_avg_t1 is not None
        assert abs(summary.benchmark_avg_t1 - 1.75) < 0.01
        # excess_return must be 0.0 (consistent day-weighted basis), NOT -0.4167
        assert summary.excess_return is not None
        assert abs(summary.excess_return - 0.0) < 0.01
        # Guard: the two weighting schemes genuinely diverge on this fixture
        # (otherwise the test wouldn't catch the regression).
        assert abs(summary.avg_t1_return - summary.benchmark_avg_t1) > 0.4

    def test_benchmark_restricted_to_report_basket_not_full_tracking(self, tmp_path: Path):
        """BH-004: ``_compute_benchmark_returns`` must average only tickers in
        the current report's basket, not every tracking entry for that date.

        Before the fix, the benchmark iterated ALL tracking entries with
        ``recommended_date == rec_date``. If the report's Top-N was trimmed
        relative to the tracked universe (e.g. 5 picks shown but 10 tracked),
        the "benchmark" and the per-day basket mean were computed over
        different ticker sets on the same day, breaking the structural
        identity ``excess_return ≡ 0`` for a reason unrelated to edge
        (Top-N trimming noise, not alpha).

        Fixture: Day A tracks 2 tickers (000001 +1.0%, 000002 +5.0%) but the
        report only shows 000001.
          - Buggy (all-tracking):  benchmark = mean(1.0, 5.0) = 3.0
          - Fixed (basket-only):   benchmark = 1.0  (== basket mean)
          - excess_return must be 0.0 (basket ≡ benchmark), not 1.0 - 3.0 = -2.0.
        """
        tracking = [
            {"ticker": "000001", "recommended_date": "20260601", "next_day_return": 1.0, "tracking_status": "complete"},
            {"ticker": "000002", "recommended_date": "20260601", "next_day_return": 5.0, "tracking_status": "complete"},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps(tracking), encoding="utf-8")
        # Report shows ONLY 000001 (Top-N trimmed 000002 out of the display).
        report = {"trade_date": "20260601", "recommendations": [
            {"ticker": "000001", "score_b": 0.8, "strategy_signals": {"trend": {"direction": 1, "confidence": 80}}},
        ]}
        (tmp_path / "auto_screening_20260601.json").write_text(json.dumps(report), encoding="utf-8")

        summary = compute_verify_recommendations(reports_dir=tmp_path, lookback_days=30)
        assert summary.benchmark_avg_t1 is not None
        # Benchmark restricted to basket → 1.0, NOT mean(1.0, 5.0)=3.0.
        assert abs(summary.benchmark_avg_t1 - 1.0) < 0.01
        # excess_return structurally ≡ 0 (basket mean == benchmark).
        assert summary.excess_return is not None
        assert abs(summary.excess_return - 0.0) < 0.01


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

    def test_verify_detail_renders_daily_details_table(self, reports_dir: Path) -> None:
        """BH-020: ``--verify-detail`` (include_detail=True) populates
        ``summary.daily_details`` (VerifyDay records), but the render function
        never rendered them — the entire ``--verify-detail`` flag was a silent
        no-op at the presentation layer despite every VerifyDay field being
        computed (date / tickers / avg_t1/t3/t5/t10/t20/t30_return /
        benchmark_return / excess_return).

        When daily_details is non-empty, the rendered output must surface them
        (a per-day detail table or per-day rows), not silently drop them.
        """
        summary = compute_verify_recommendations(reports_dir=reports_dir, lookback_days=30, include_detail=True)
        # Sanity: detail computation actually ran.
        assert len(summary.daily_details) == 2
        day_dates = {d.date for d in summary.daily_details}
        assert day_dates == {"20260601", "20260602"}
        output = render_verify_recommendations(summary)
        # Each detail day's date must appear in the rendered output (the table
        # would be useless if it dropped the date column).
        assert "20260601" in output
        assert "20260602" in output
        # A detail-specific marker so users see the detail section rendered.
        assert "日度明细" in output or "逐日" in output

    def test_verify_detail_skipped_when_no_daily_details(self, reports_dir: Path) -> None:
        """BH-020 robustness: without --verify-detail, daily_details is empty
        and the renderer must not emit a (misleading) empty detail section."""
        summary = compute_verify_recommendations(reports_dir=reports_dir, lookback_days=30, include_detail=False)
        assert summary.daily_details == []
        output = render_verify_recommendations(summary)
        assert "日度明细" not in output


# ---------------------------------------------------------------------------
# Extended horizons (T+10/T+20/T+30) - P5-1
# ---------------------------------------------------------------------------


@pytest.fixture
def extended_reports_dir(tmp_path: Path) -> Path:
    """Create a temp reports dir with extended horizon data."""
    # Use a recent date that won't be filtered out by lookback
    # tracking_history.json with T+10/T+20/T+30
    tracking = [
        {
            "ticker": "000001", "name": "平安银行", "recommended_date": "20260601",
            "recommended_price": 12.0,
            "next_day_return": 2.0, "next_3day_return": 3.5, "next_5day_return": 5.0,
            "next_10day_return": 7.0, "next_20day_return": 10.0, "next_30day_return": 12.0,
            "tracking_status": "complete"
        },
        {
            "ticker": "600519", "name": "贵州茅台", "recommended_date": "20260601",
            "recommended_price": 1500.0,
            "next_day_return": -1.0, "next_3day_return": 2.0, "next_5day_return": -0.5,
            "next_10day_return": -2.0, "next_20day_return": -3.0, "next_30day_return": -1.0,
            "tracking_status": "complete"
        },
    ]
    (tmp_path / "tracking_history.json").write_text(json.dumps(tracking), encoding="utf-8")

    # auto_screening_20260601.json
    report = {
        "trade_date": "20260601",
        "recommendations": [
            {"ticker": "000001", "name": "平安银行", "score_b": 0.8, "decision": "bullish",
             "strategy_signals": {"trend": {"direction": 1, "confidence": 80}}},
            {"ticker": "600519", "name": "贵州茅台", "score_b": 0.6, "decision": "bullish",
             "strategy_signals": {"fundamental": {"direction": 1, "confidence": 70}}},
        ],
    }
    (tmp_path / "auto_screening_20260601.json").write_text(json.dumps(report), encoding="utf-8")
    return tmp_path


class TestExtendedHorizonsVerifyRecommendations:
    def test_extended_horizon_attributes_exist(self, extended_reports_dir: Path):
        """VerifySummary and VerifyDay should have T+10/T+20/T+30 attributes."""
        summary = compute_verify_recommendations(reports_dir=extended_reports_dir, lookback_days=30)
        
        # VerifySummary should have extended stats
        assert hasattr(summary, 'overall_t10_win_rate')
        assert hasattr(summary, 'overall_t20_win_rate')
        assert hasattr(summary, 'overall_t30_win_rate')
        assert hasattr(summary, 'avg_t10_return')
        assert hasattr(summary, 'avg_t20_return')
        assert hasattr(summary, 'avg_t30_return')
    
    def test_extended_horizon_computation(self, extended_reports_dir: Path):
        """Extended horizons should be computed correctly."""
        summary = compute_verify_recommendations(reports_dir=extended_reports_dir, lookback_days=30)
        
        # T+10: 000001 (+7.0) win, 600519 (-2.0) loss → 50% win rate
        assert summary.overall_t10_win_rate == pytest.approx(0.5, abs=1e-3)
        # Average: (7.0 + (-2.0)) / 2 = 2.5
        assert summary.avg_t10_return == pytest.approx(2.5, abs=1e-3)
        
        # T+20: 000001 (+10.0) win, 600519 (-3.0) loss → 50% win rate
        assert summary.overall_t20_win_rate == pytest.approx(0.5, abs=1e-3)
        assert summary.avg_t20_return == pytest.approx(3.5, abs=1e-3)
        
        # T+30: 000001 (+12.0) win, 600519 (-1.0) loss → 50% win rate
        assert summary.overall_t30_win_rate == pytest.approx(0.5, abs=1e-3)
        assert summary.avg_t30_return == pytest.approx(5.5, abs=1e-3)
    
    def test_extended_horizon_day_details(self, extended_reports_dir: Path):
        """VerifyDay should track T+10/T+20/T+30 per-day averages."""
        summary = compute_verify_recommendations(
            reports_dir=extended_reports_dir, 
            lookback_days=30, 
            include_detail=True
        )
        
        assert len(summary.daily_details) == 1
        day = summary.daily_details[0]
        
        assert hasattr(day, 'avg_t10_return')
        assert hasattr(day, 'avg_t20_return')
        assert hasattr(day, 'avg_t30_return')
        
        # Average of 000001 and 600519
        assert day.avg_t10_return == pytest.approx(2.5, abs=1e-3)
        assert day.avg_t20_return == pytest.approx(3.5, abs=1e-3)
        assert day.avg_t30_return == pytest.approx(5.5, abs=1e-3)
    
    def test_render_shows_extended_columns(self, extended_reports_dir: Path):
        """Rendered output should include T+10/T+20/T+30 columns."""
        summary = compute_verify_recommendations(reports_dir=extended_reports_dir, lookback_days=30)
        output = render_verify_recommendations(summary)

        # Should display extended horizon stats
        assert "T+10" in output or "T+20" in output or "T+30" in output

    def test_render_shows_t5_column(self, reports_dir: Path):
        """R51: T+5 stats are computed but must also be rendered.

        The module docstring promises T+1/T+3/T+5, and ``overall_t5_win_rate``
        / ``avg_t5_return`` are populated by ``compute_verify_recommendations``,
        but the render previously showed only T+1/T+3 in the main table —
        leaving T+5 as wasted computation. The main table must now include a
        T+5 column so the full horizon ladder (T+1/T+3/T+5 + T+10/T+20/T+30)
        is visible to the user.
        """
        summary = compute_verify_recommendations(reports_dir=reports_dir, lookback_days=30)
        # Sanity: T+5 is computed.
        assert summary.avg_t5_return is not None or summary.overall_t5_win_rate is not None
        output = render_verify_recommendations(summary)
        # T+5 must appear in the rendered output.
        assert "T+5" in output
