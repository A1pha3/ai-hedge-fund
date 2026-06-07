"""Tests for run_explain() explainability enhancements (P0-2).

Blocks tested:
  A — 因子贡献度明细 (top-3 sub-factors per strategy)
  B — 近 5 日关键事件
  C — 同行业排名百分位
"""
from __future__ import annotations

import json
import textwrap
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sub_factor(name: str, direction: int, confidence: float, weight: float = 0.2, completeness: float = 1.0, metrics: dict | None = None) -> dict:
    return {
        "name": name,
        "direction": direction,
        "confidence": confidence,
        "completeness": completeness,
        "weight": weight,
        "metrics": metrics or {},
    }


def _make_strategy_signal(direction: int, confidence: float, completeness: float = 0.8, sub_factors: dict | None = None) -> dict:
    return {
        "direction": direction,
        "confidence": confidence,
        "completeness": completeness,
        "sub_factors": sub_factors or {},
    }


def _make_recommendation(
    ticker: str = "000001",
    name: str = "测试银行",
    industry_sw: str = "银行",
    score_b: float = 0.45,
    decision: str = "watch",
    strategy_signals: dict | None = None,
    arbitration_applied: list | None = None,
) -> dict:
    return {
        "ticker": ticker,
        "name": name,
        "industry_sw": industry_sw,
        "score_b": score_b,
        "decision": decision,
        "strategy_signals": strategy_signals or {},
        "arbitration_applied": arbitration_applied or [],
    }


def _make_report(
    recommendations: list[dict] | None = None,
    market_state: dict | None = None,
    recent_events: list | None = None,
) -> dict:
    report: dict = {
        "mode": "auto_screening",
        "recommendations": recommendations or [],
    }
    if market_state is not None:
        report["market_state"] = market_state
    if recent_events is not None:
        report["recent_events"] = recent_events
    return report


def _run_explain_capture(report_data: dict, ticker: str = "000001", reports_dir_exists: bool = True) -> tuple[int, str]:
    """Run run_explain with mocked filesystem, capture stdout. Returns (return_code, output)."""
    from src.main import run_explain

    report_json = json.dumps(report_data)
    fake_path = Path("data/reports/auto_screening_20260607.json")

    def _glob_side_effect(pattern: str):
        if "auto_screening_" in pattern:
            return [fake_path]
        return []

    # Patch open and Path.exists / Path.glob
    m = patch.object(Path, "exists", return_value=reports_dir_exists)
    g = patch.object(Path, "glob", side_effect=_glob_side_effect)

    buf = StringIO()

    with m, g, patch("builtins.open", _mock_open_read(report_json)), patch("sys.stdout", buf):
        rc = run_explain(ticker)

    return rc, buf.getvalue()


class _MockReadFile:
    """Context manager that yields a file-like object with the given content."""

    def __init__(self, content: str):
        self._content = content

    def __enter__(self):
        from io import StringIO
        return StringIO(self._content)

    def __exit__(self, *args):
        pass


def _mock_open_read(content: str):
    """Return a mock for builtins.open that returns content for any file path."""
    def _open(path, *args, **kwargs):
        return _MockReadFile(content)
    return _open


# ---------------------------------------------------------------------------
# Test 1: Factor detail shows top 3 factors per strategy
# ---------------------------------------------------------------------------

class TestExplainFactorDetail:

    def test_explain_shows_top3_factors_per_strategy(self):
        """Verify factor detail output contains top-3 factor names per strategy."""
        sub_factors_trend = {
            "momentum": _make_sub_factor("momentum", 1, 72.0),
            "supply_pressure": _make_sub_factor("supply_pressure", -1, 45.0),
            "volatility": _make_sub_factor("volatility", 1, 30.0),
            "macd_signal": _make_sub_factor("macd_signal", 0, 10.0),
        }
        signals = {
            "trend": _make_strategy_signal(1, 65.0, sub_factors=sub_factors_trend),
            "mean_reversion": _make_strategy_signal(0, 20.0),
            "fundamental": _make_strategy_signal(1, 50.0),
            "event_sentiment": _make_strategy_signal(1, 55.0),
        }
        rec = _make_recommendation(strategy_signals=signals)
        report = _make_report(recommendations=[rec])

        rc, output = _run_explain_capture(report)

        assert rc == 0
        # Should show the trend strategy label
        assert "趋势策略" in output
        # Should show top 3 factor names (momentum, supply_pressure, volatility)
        assert "momentum" in output
        assert "supply_pressure" in output
        assert "volatility" in output
        # Should NOT show the 4th factor (macd_signal) since we only show top 3
        assert "macd_signal" not in output
        # Should show arrows and bar chart characters
        assert "↑" in output
        assert "↓" in output
        assert "█" in output
        assert "░" in output

    def test_explain_handles_missing_subfactors(self):
        """When strategy has no sub_factors, should not crash and show fallback."""
        signals = {
            "trend": _make_strategy_signal(1, 65.0, sub_factors={}),
            "mean_reversion": _make_strategy_signal(0, 20.0, sub_factors={}),
            "fundamental": _make_strategy_signal(1, 50.0, sub_factors={}),
            "event_sentiment": _make_strategy_signal(1, 55.0, sub_factors={}),
        }
        rec = _make_recommendation(strategy_signals=signals)
        report = _make_report(recommendations=[rec])

        rc, output = _run_explain_capture(report)

        assert rc == 0
        # Should show fallback message for no factor details
        assert "暂无因子明细数据" in output


# ---------------------------------------------------------------------------
# Test 2: Industry ranking
# ---------------------------------------------------------------------------

class TestExplainIndustryRanking:

    def test_explain_shows_industry_ranking(self):
        """Verify industry ranking output with correct rank and percentile."""
        recs = [
            _make_recommendation(ticker="000001", industry_sw="电子", score_b=0.60),
            _make_recommendation(ticker="000002", industry_sw="电子", score_b=0.55),
            _make_recommendation(ticker="000003", industry_sw="电子", score_b=0.50),
            _make_recommendation(ticker="000004", industry_sw="电子", score_b=0.40),
            _make_recommendation(ticker="600001", industry_sw="银行", score_b=0.70),
        ]
        report = _make_report(recommendations=recs)

        rc, output = _run_explain_capture(report, ticker="000001")

        assert rc == 0
        # Should show industry name
        assert "电子" in output
        # 000001 has score_b 0.60, which is highest in "电子" (4 peers)
        # Rank should be 1/4
        assert "第 1/4 名" in output
        assert "前 25%" in output

    def test_explain_industry_ranking_no_industry(self):
        """When ticker has no industry_sw, show fallback."""
        rec = _make_recommendation(ticker="000001", industry_sw="", score_b=0.45)
        report = _make_report(recommendations=[rec])

        rc, output = _run_explain_capture(report)

        assert rc == 0
        assert "无行业信息" in output

    def test_explain_industry_ranking_none_score_b_no_crash(self):
        """GAMMA-008: score_b=None in peers must not crash sorted() with TypeError."""
        recs = [
            _make_recommendation(ticker="000001", industry_sw="电子", score_b=0.60),
            _make_recommendation(ticker="000002", industry_sw="电子", score_b=None),
            _make_recommendation(ticker="000003", industry_sw="电子", score_b=0.50),
        ]
        report = _make_report(recommendations=recs)

        rc, output = _run_explain_capture(report, ticker="000001")

        assert rc == 0
        assert "电子" in output
        assert "第" in output

    def test_explain_industry_ranking_nan_score_b_no_crash(self):
        """GAMMA-008: score_b=NaN in peers must not produce undefined ordering."""
        recs = [
            _make_recommendation(ticker="000001", industry_sw="电子", score_b=float("nan")),
            _make_recommendation(ticker="000002", industry_sw="电子", score_b=0.55),
        ]
        report = _make_report(recommendations=recs)

        rc, output = _run_explain_capture(report, ticker="000001")

        assert rc == 0
        assert "电子" in output


# ---------------------------------------------------------------------------
# Test 3: Recent events
# ---------------------------------------------------------------------------

class TestExplainRecentEvents:

    def test_explain_handles_no_events(self):
        """When no event data at all, show fallback message."""
        rec = _make_recommendation()
        report = _make_report(recommendations=[rec])

        rc, output = _run_explain_capture(report)

        assert rc == 0
        assert "暂无近期事件数据" in output

    def test_explain_shows_events_from_report(self):
        """When report has recent_events, show them."""
        events = [
            {"date": "06-05", "description": "龙虎榜净买入 ¥2.3亿"},
            {"date": "06-04", "description": "北向资金 +¥1.5亿"},
        ]
        rec = _make_recommendation()
        report = _make_report(recommendations=[rec], recent_events=events)

        rc, output = _run_explain_capture(report)

        assert rc == 0
        assert "龙虎榜净买入" in output
        assert "06-05" in output

    def test_explain_shows_events_from_subfactors(self):
        """When report has no recent_events but event_sentiment sub-factors have articles, extract them."""
        articles = [
            {"title": "公司发布业绩预增公告", "days_old": 1},
            {"title": "机构调研纪要", "days_old": 3},
        ]
        sub_factors_event = {
            "news_sentiment": _make_sub_factor(
                "news_sentiment", 1, 60.0,
                metrics={"articles": articles},
            ),
        }
        signals = {
            "event_sentiment": _make_strategy_signal(1, 55.0, sub_factors=sub_factors_event),
        }
        rec = _make_recommendation(strategy_signals=signals)
        report = _make_report(recommendations=[rec])

        rc, output = _run_explain_capture(report)

        assert rc == 0
        assert "公司发布业绩预增公告" in output
        assert "1天前" in output

    def test_explain_articles_all_empty_titles_falls_back(self):
        """When articles exist but all have empty titles, should show fallback message."""
        articles = [
            {"title": "", "days_old": 1},
            {"title": "", "days_old": 2},
        ]
        sub_factors_event = {
            "news_sentiment": _make_sub_factor(
                "news_sentiment", 1, 60.0,
                metrics={"articles": articles},
            ),
        }
        signals = {
            "event_sentiment": _make_strategy_signal(1, 55.0, sub_factors=sub_factors_event),
        }
        rec = _make_recommendation(strategy_signals=signals)
        report = _make_report(recommendations=[rec])

        rc, output = _run_explain_capture(report)

        assert rc == 0
        assert "暂无近期事件数据" in output


# ---------------------------------------------------------------------------
# Test 4: Ticker not found (existing logic)
# ---------------------------------------------------------------------------

class TestExplainTickerNotFound:

    def test_explain_handles_ticker_not_found(self):
        """Ticker not in recommendations should return 1 and show available tickers."""
        recs = [
            _make_recommendation(ticker="000002", name="万科A"),
            _make_recommendation(ticker="000001", name="平安银行"),
        ]
        report = _make_report(recommendations=recs)

        rc, output = _run_explain_capture(report, ticker="999999")

        assert rc == 1
        assert "999999" in output
        assert "未在 Top 推荐中" in output


# ---------------------------------------------------------------------------
# Test 5: Unit tests for helper functions
# ---------------------------------------------------------------------------

class TestHelperFunctions:

    def test_build_factor_bar_full(self):
        from src.main import _build_factor_bar
        assert _build_factor_bar(100.0) == "██████████"

    def test_build_factor_bar_zero(self):
        from src.main import _build_factor_bar
        assert _build_factor_bar(0.0) == "░░░░░░░░░░"

    def test_build_factor_bar_mid(self):
        from src.main import _build_factor_bar
        assert _build_factor_bar(50.0) == "█████░░░░░"

    def test_build_factor_bar_clamps(self):
        from src.main import _build_factor_bar
        assert _build_factor_bar(150.0) == "██████████"
        assert _build_factor_bar(-10.0) == "░░░░░░░░░░"

    def test_extract_articles_empty(self):
        from src.main import _extract_articles_from_event_subfactors
        assert _extract_articles_from_event_subfactors({}) == []
        assert _extract_articles_from_event_subfactors({"news_sentiment": "bad"}) == []
        assert _extract_articles_from_event_subfactors({"news_sentiment": {"metrics": "bad"}}) == []
        assert _extract_articles_from_event_subfactors({"news_sentiment": {"metrics": {"articles": "notalist"}}}) == []

    def test_extract_articles_valid(self):
        from src.main import _extract_articles_from_event_subfactors
        arts = [{"title": "a"}, {"title": "b"}]
        result = _extract_articles_from_event_subfactors({"news_sentiment": {"metrics": {"articles": arts}}})
        assert len(result) == 2

    def test_build_factor_bar_nan_returns_empty(self):
        """GAMMA-008: NaN confidence should not crash and should produce empty bar."""
        from src.main import _build_factor_bar
        import math
        result = _build_factor_bar(float("nan"))
        assert result == "░░░░░░░░░░"
