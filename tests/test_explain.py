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
# Test: R75 trust-calibration disclaimer (R71/R72/R73 family)
# ---------------------------------------------------------------------------


class TestExplainDisclaimer:
    def test_explain_carries_non_advice_disclaimer(self):
        """R75 (R71/R72/R73 trust-calibration family): ``--explain`` emits a
        per-ticker decision label (``决策: buy/hold/sell``) plus a full strategy
        + factor breakdown for a specific stock, but the 5 sibling decision
        surfaces (``--top-picks``, ``--daily-brief``, ``--position-check``, PDF
        exporter, backtest CLI) all carry a non-advice disclaimer and
        ``--explain`` did not. Users reading "决策: buy" with a detailed factor
        rationale could treat it as a deterministic instruction. The footer must
        carry the same boundary disclaimer so all 6 user-visible decision
        surfaces are consistent."""
        signals = {
            "trend": _make_strategy_signal(1, 65.0, sub_factors={}),
            "mean_reversion": _make_strategy_signal(0, 20.0, sub_factors={}),
            "fundamental": _make_strategy_signal(1, 50.0, sub_factors={}),
            "event_sentiment": _make_strategy_signal(1, 55.0, sub_factors={}),
        }
        rec = _make_recommendation(strategy_signals=signals, decision="buy")
        report = _make_report(recommendations=[rec])

        rc, output = _run_explain_capture(report)

        assert rc == 0
        assert "不构成任何投资建议" in output
        assert "研究" in output


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
                "news_sentiment",
                1,
                60.0,
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
                "news_sentiment",
                1,
                60.0,
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

    def test_explain_article_unknown_date_sentinel_not_rendered_as_9999(self):
        """autodev-13 / loop 100: days_old=9999 is the upstream sentinel for
        "unparseable date" (_resolve_news_article_days_old returns 9999 when
        _safe_date cannot parse the article date — empirically ALL 29 articles
        across all 7 tickers in report 20260703 carry this sentinel because the
        akshare 发布时间 field uses relative Chinese formats _safe_date doesn't
        handle). Rendering "9999天前" (~27 years) on a "近期事件 (5 日)" block is
        absurd and misleads the operator. The sentinel must render as an honest
        "unknown date" label, NOT "9999天前".
        """
        articles = [
            {"title": "鼎龙股份：上半年光刻胶整体交付规模同比稳步提升", "days_old": 9999},
            {"title": "鼎龙股份市值破千亿", "days_old": 9999},
        ]
        sub_factors_event = {
            "news_sentiment": _make_sub_factor(
                "news_sentiment",
                1,
                60.0,
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
        assert "9999天前" not in output, (
            "days_old=9999 is the upstream sentinel for unparseable date — must "
            "NOT render as '9999天前' (~27 years), which is absurd on a 近期事件 "
            "block and misleads the operator."
        )
        # The article title is still real news and should be shown; only the
        # bogus timestamp must be replaced with an honest "unknown" label.
        assert "光刻胶" in output
        assert "日期未知" in output or "未知" in output, (
            "When days_old is the unknown-date sentinel, render an honest label "
            "so the operator knows the article date is unavailable."
        )


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
        from src.cli.explain_helpers import _build_factor_bar

        assert _build_factor_bar(100.0) == "██████████"

    def test_build_factor_bar_zero(self):
        from src.cli.explain_helpers import _build_factor_bar

        assert _build_factor_bar(0.0) == "░░░░░░░░░░"

    def test_build_factor_bar_mid(self):
        from src.cli.explain_helpers import _build_factor_bar

        assert _build_factor_bar(50.0) == "█████░░░░░"

    def test_build_factor_bar_clamps(self):
        from src.cli.explain_helpers import _build_factor_bar

        assert _build_factor_bar(150.0) == "██████████"
        assert _build_factor_bar(-10.0) == "░░░░░░░░░░"

    def test_extract_articles_empty(self):
        from src.cli.explain_helpers import _extract_articles_from_event_subfactors

        assert _extract_articles_from_event_subfactors({}) == []
        assert _extract_articles_from_event_subfactors({"news_sentiment": "bad"}) == []
        assert _extract_articles_from_event_subfactors({"news_sentiment": {"metrics": "bad"}}) == []
        assert _extract_articles_from_event_subfactors({"news_sentiment": {"metrics": {"articles": "notalist"}}}) == []

    def test_extract_articles_valid(self):
        from src.cli.explain_helpers import _extract_articles_from_event_subfactors

        arts = [{"title": "a"}, {"title": "b"}]
        result = _extract_articles_from_event_subfactors({"news_sentiment": {"metrics": {"articles": arts}}})
        assert len(result) == 2

    def test_build_factor_bar_nan_returns_empty(self):
        """GAMMA-008: NaN confidence should not crash and should produce empty bar."""
        import math

        from src.cli.explain_helpers import _build_factor_bar

        result = _build_factor_bar(float("nan"))
        assert result == "░░░░░░░░░░"

    # --- _print_strategy_breakdown (extracted from run_explain R20.45) ---

    def test_print_strategy_breakdown_all_directions(self, capsys):
        """Bullish/bearish/neutral directions render correct arrows + confidence."""
        from src.cli.explain_helpers import _print_strategy_breakdown

        signals = {
            "trend": {"direction": 1, "confidence": 72.5},
            "mean_reversion": {"direction": -1, "confidence": 45.0},
            "fundamental": {"direction": 0, "confidence": 30.0},
            "event_sentiment": {"direction": 1, "confidence": 55.0},
        }
        _print_strategy_breakdown(signals)
        output = capsys.readouterr().out
        assert "策略贡献" in output
        assert "↑" in output  # trend (bullish)
        assert "↓" in output  # mean_reversion (bearish)
        assert "—" in output  # fundamental (neutral)
        assert "72.5" in output
        assert "45.0" in output

    def test_print_strategy_breakdown_missing_strategy(self, capsys):
        """Missing strategy shows 数据缺失 fallback."""
        from src.cli.explain_helpers import _print_strategy_breakdown

        signals = {"trend": {"direction": 1, "confidence": 65.0}}
        _print_strategy_breakdown(signals)
        output = capsys.readouterr().out
        assert "数据缺失" in output
        assert "trend" in output  # present strategy still rendered

    def test_print_strategy_breakdown_empty_signals(self, capsys):
        """Empty signals dict → all 4 strategies show 数据缺失."""
        from src.cli.explain_helpers import _print_strategy_breakdown

        _print_strategy_breakdown({})
        output = capsys.readouterr().out
        assert output.count("数据缺失") == 4

    # --- _print_factor_detail_block (Block A) ---

    def test_print_factor_detail_block_top3_sorted(self, capsys):
        """Top 3 factors shown per strategy, sorted by |confidence| descending."""
        from src.cli.explain_helpers import _print_factor_detail_block

        signals = {
            "trend": {
                "sub_factors": {
                    "momentum": {"name": "momentum", "direction": 1, "confidence": 72.0},
                    "supply_pressure": {"name": "supply_pressure", "direction": -1, "confidence": 45.0},
                    "volatility": {"name": "volatility", "direction": 1, "confidence": 30.0},
                    "macd_signal": {"name": "macd_signal", "direction": 0, "confidence": 10.0},
                }
            }
        }
        _print_factor_detail_block(signals)
        output = capsys.readouterr().out
        assert "因子明细" in output
        assert "趋势策略" in output  # Chinese label for trend
        # Top 3 by |confidence|: momentum(72), supply_pressure(45), volatility(30)
        assert "momentum" in output
        assert "supply_pressure" in output
        assert "volatility" in output
        assert "macd_signal" not in output  # 4th, excluded
        assert "█" in output  # bar chart rendered

    def test_print_factor_detail_block_empty_shows_fallback(self, capsys):
        """Empty signals → 暂无因子明细数据 fallback."""
        from src.cli.explain_helpers import _print_factor_detail_block

        _print_factor_detail_block({})
        output = capsys.readouterr().out
        assert "暂无因子明细数据" in output

    def test_print_factor_detail_block_no_subfactors_shows_fallback(self, capsys):
        """Strategy without sub_factors → skipped; fallback shown if none have factors."""
        from src.cli.explain_helpers import _print_factor_detail_block

        signals = {"trend": {"direction": 1, "confidence": 65.0}}  # no sub_factors key
        _print_factor_detail_block(signals)
        output = capsys.readouterr().out
        assert "暂无因子明细数据" in output

    # --- _print_recent_events_block (extracted helper, Block B) ---

    def test_print_recent_events_from_report_dicts(self, capsys):
        """Priority 1: report-level recent_events list of dicts → date + description."""
        from src.cli.explain_helpers import _print_recent_events_block

        report = {"recent_events": [{"date": "20260610", "description": "财报超预期"}]}
        _print_recent_events_block(report, {})
        output = capsys.readouterr().out
        assert "20260610" in output
        assert "财报超预期" in output

    def test_print_recent_events_from_report_strings(self, capsys):
        """Priority 1: recent_events list of plain strings → printed as-is."""
        from src.cli.explain_helpers import _print_recent_events_block

        report = {"recent_events": ["限售解禁", "大宗交易"]}
        _print_recent_events_block(report, {})
        output = capsys.readouterr().out
        assert "限售解禁" in output
        assert "大宗交易" in output

    def test_print_recent_events_from_subfactors(self, capsys):
        """Priority 2: no report events, extract from event_sentiment sub_factors."""
        from src.cli.explain_helpers import _print_recent_events_block

        report = {}
        match = {"strategy_signals": {"event_sentiment": {"sub_factors": {"news_sentiment": {"metrics": {"articles": [{"days_old": "3", "title": "利好消息"}]}}}}}}
        _print_recent_events_block(report, match)
        output = capsys.readouterr().out
        assert "3天前" in output
        assert "利好消息" in output

    def test_print_recent_events_no_data_fallback(self, capsys):
        """No report events and no articles → fallback message."""
        from src.cli.explain_helpers import _print_recent_events_block

        _print_recent_events_block({}, {})
        output = capsys.readouterr().out
        assert "暂无近期事件数据" in output

    # --- _print_industry_ranking_block (extracted helper, Block C) ---

    def test_print_industry_ranking_no_industry(self, capsys):
        """Match has no industry_sw → shows 无行业信息."""
        from src.cli.explain_helpers import _print_industry_ranking_block

        _print_industry_ranking_block([], {"ticker": "000001"})
        output = capsys.readouterr().out
        assert "无行业信息" in output

    def test_print_industry_ranking_no_peers(self, capsys):
        """Industry present but no same-industry recs → 无同行业数据."""
        from src.cli.explain_helpers import _print_industry_ranking_block

        recs = [{"ticker": "000002", "industry_sw": "银行", "score_b": 0.5}]
        _print_industry_ranking_block(recs, {"ticker": "000001", "industry_sw": "电子"})
        output = capsys.readouterr().out
        assert "无同行业数据" in output

    def test_print_industry_ranking_normal(self, capsys):
        """Same-industry recs → prints rank/total/percentile."""
        from src.cli.explain_helpers import _print_industry_ranking_block

        recs = [
            {"ticker": "000001", "industry_sw": "电子", "score_b": 0.8},
            {"ticker": "000002", "industry_sw": "电子", "score_b": 0.5},
            {"ticker": "000003", "industry_sw": "电子", "score_b": 0.3},
        ]
        _print_industry_ranking_block(recs, {"ticker": "000002", "industry_sw": "电子"})
        output = capsys.readouterr().out
        assert "第 2/3 名" in output

    def test_print_industry_ranking_none_score_b_coerced(self, capsys):
        """GAMMA-008: None score_b coerced to 0.0 without crash."""
        from src.cli.explain_helpers import _print_industry_ranking_block

        recs = [
            {"ticker": "000001", "industry_sw": "电子", "score_b": None},
            {"ticker": "000002", "industry_sw": "电子", "score_b": 0.5},
        ]
        _print_industry_ranking_block(recs, {"ticker": "000001", "industry_sw": "电子"})
        output = capsys.readouterr().out
        # None coerced to 0.0 → ranked last → rank 2/2
        assert "第 2/2 名" in output


# ---------------------------------------------------------------------------
# Loop 95 (autodev): run_explain None-handling — sibling-disease sweep of
# GAMMA-008 (_print_industry_ranking_block None score_b coerced) to the
# run_explain main function. GAMMA-008 drained the helper but missed the
# main function's own score_b read at main.py:3102.
# ---------------------------------------------------------------------------


class TestRunExplainNoneScoreBHandling:
    """Loop 95: drain None score_b crash in run_explain main function.

    GAMMA-008 (test above) drained ``_print_industry_ranking_block``'s None
    score_b via ``_safe_float`` coercion. But the sibling read in
    ``run_explain`` (main.py:3102) was missed:

    .. code-block:: python

        score_b = match.get("score_b", 0.0)        # None if key present, value=None
        ...
        print(f"  决策: {decision}  |  Score B: {score_b:+.4f}")  # crash: None:+.4f

    ``dict.get("score_b", 0.0)`` returns ``0.0`` only when the KEY is MISSING.
    When the key is PRESENT but the value is ``None`` (corrupt report / partial
    pipeline / upstream None propagation), ``.get`` returns ``None``, and
    ``None:+.4f`` raises ``TypeError: unsupported format string passed to
    NoneType.__format__``.

    This is the same falsy-None disease class as R68/R69/R96/R100 (margin_of_safety
    footgun) and GAMMA-008 (sibling helper). The fix mirrors GAMMA-008: coerce
    None/NaN to 0.0 before formatting.
    """

    def test_none_score_b_does_not_crash(self) -> None:
        """run_explain must not crash when score_b=None (key present, value=None).

        Reproduction: a corrupt/partial report where ``score_b`` is explicitly
        null (JSON ``null`` → Python ``None``). Without the fix, ``run_explain``
        crashes with TypeError at the ``score_b:+.4f`` format string, blocking
        the operator from seeing the rest of the explain output (strategy
        breakdown, factor detail, events, industry ranking).
        """
        rec = _make_recommendation(score_b=None)  # type: ignore[arg-type]
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0, (
            f"run_explain crashed on score_b=None (TypeError at score_b:+.4f format). "
            f"Operator cannot see explain output for corrupt/partial reports. "
            f"Got rc={rc}, output={output!r}"
        )
        # Score B line should show 0.0000 (coerced) not crash
        assert "Score B:" in output

    def test_missing_score_b_key_still_uses_default(self) -> None:
        """Regression guard: missing score_b key must still fall back to 0.0.

        The fix (None coercion) must not break the existing missing-key path
        (dict.get default 0.0). This test pins the missing-key baseline.
        """
        rec = _make_recommendation()
        del rec["score_b"]  # key missing entirely
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0
        assert "Score B:" in output

    def test_none_score_b_shows_zero_not_blank(self) -> None:
        """None score_b must render as 0.0000, not blank or 'None'.

        Honest coercion: operator sees 'Score B: +0.0000' (a real number),
        not 'Score B: None' or a crash. This lets the operator continue
        inspecting the pick instead of being blocked.
        """
        rec = _make_recommendation(score_b=None)  # type: ignore[arg-type]
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0
        assert "+0.0000" in output, (
            f"None score_b should coerce to 0.0000 for honest display. Got: {output!r}"
        )


class TestRunExplainNoneDecisionHandling:
    """Loop 95 (sibling): drain None decision misleading-display in run_explain.

    Same disease class as score_b=None (TestRunExplainNoneScoreBHandling above),
    same module, same None-propagation root cause. ``dict.get("decision", "neutral")``
    returns "neutral" only when the KEY is MISSING; when key is present but
    value=None, .get returns None, and the f-string renders "决策: None" —
    misleading the operator into thinking the pick has a literal "None" decision
    rather than a missing/unknown one.

    Fix mirrors score_b: coerce None/empty to "neutral" (the existing default).
    """

    def test_none_decision_shows_neutral_not_none(self) -> None:
        """decision=None must render as 'neutral', not 'None'.

        Without the fix, a corrupt/partial report with ``decision: null`` shows
        '决策: None' — operator cannot tell if this is a real decision label
        or a missing-data artifact. Honest coercion: show 'neutral' (the
        existing missing-key default).
        """
        rec = _make_recommendation(decision=None)  # type: ignore[arg-type]
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0
        assert "决策: neutral" in output, (
            f"None decision should coerce to 'neutral' (the missing-key default), "
            f"not render as '决策: None'. Got: {output!r}"
        )
        assert "None" not in output.replace("Score B:", ""), (
            f"Literal 'None' should not appear in decision display. Got: {output!r}"
        )

    def test_empty_string_decision_shows_neutral(self) -> None:
        """decision='' (empty string) must also coerce to 'neutral'.

        Empty string is another missing-data artifact (e.g. upstream
        ``decision = pick.get("decision") or ""``). The fix must handle both
        None and empty string.
        """
        rec = _make_recommendation(decision="")
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0
        assert "决策: neutral" in output

    def test_valid_decision_preserved(self) -> None:
        """Regression guard: valid decision must be preserved (not coerced).

        The fix (None/empty coercion) must not over-reach into valid inputs.
        """
        rec = _make_recommendation(decision="watch")
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0
        assert "决策: watch" in output


class TestRunExplainNoneSignalsHandling:
    """Loop 96 (autodev): drain None strategy_signals crash in run_explain.

    Sibling-disease sweep of Loop 95 score_b/decision None-handling. Same
    disease class: ``dict.get("strategy_signals", {})`` returns ``{}`` only
    when the KEY is MISSING; when key is present but value=None (corrupt
    report / partial pipeline / upstream None propagation from
    ``to_recommendation_dict``), ``.get`` returns None, and downstream
    helpers call ``signals.get(strat_name)`` -> ``AttributeError: 'NoneType'
    object has no attribute 'get'``.

    Crash surface: ``_print_strategy_breakdown(signals)`` (explain_helpers.py:43)
    and ``_print_factor_detail_block(signals)`` (explain_helpers.py:61).

    Fix mirrors Loop 95: coerce None/empty to ``{}`` (the existing default).
    """

    def test_none_signals_does_not_crash(self) -> None:
        """strategy_signals=None must not crash _print_strategy_breakdown.

        Without the fix, None propagates to ``signals.get(...)`` in
        ``_print_strategy_breakdown`` (explain_helpers.py:43) and raises
        AttributeError. Honest coercion: treat as missing data, show
        '数据缺失' for each strategy (existing missing-key path).

        NOTE: bypass _make_recommendation helper — it coerces None → {} via
        ``strategy_signals or {}``, masking the disease. Construct the dict
        directly so None actually reaches run_explain.
        """
        rec: dict = {
            "ticker": "000001",
            "name": "测试银行",
            "industry_sw": "银行",
            "score_b": 0.45,
            "decision": "watch",
            "strategy_signals": None,  # type: ignore[dict-item]
            "arbitration_applied": [],
        }
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0, (
            f"None strategy_signals should not crash run_explain. "
            f"Got rc={rc}, output={output!r}"
        )
        # Existing '数据缺失' fallback (explain_helpers.py:45) should fire
        # for each of the 4 strategies when signals is missing.
        assert "数据缺失" in output, (
            f"None strategy_signals should fall back to '数据缺失' label, "
            f"not crash. Got: {output!r}"
        )

    def test_missing_signals_key_uses_default(self) -> None:
        """Regression guard: missing strategy_signals key still uses {} default.

        The fix must not break the existing missing-key path. When the key
        is absent from the recommendation dict, ``.get("strategy_signals", {})``
        returns ``{}`` and the 4 strategies show '数据缺失'.
        """
        rec = _make_recommendation()
        del rec["strategy_signals"]
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0
        assert "数据缺失" in output

    def test_valid_signals_preserved(self) -> None:
        """Regression guard: valid strategy_signals must be preserved (not coerced)."""
        signals = {
            "trend": _make_strategy_signal(1, 65.0, sub_factors={}),
            "mean_reversion": _make_strategy_signal(0, 20.0, sub_factors={}),
            "fundamental": _make_strategy_signal(1, 50.0, sub_factors={}),
            "event_sentiment": _make_strategy_signal(1, 55.0, sub_factors={}),
        }
        rec = _make_recommendation(strategy_signals=signals)
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0
        # 策略贡献 block should show the trend strategy with non-zero confidence
        assert "趋势策略" in output or "trend" in output


class TestRunExplainNoneArbitrationHandling:
    """Loop 96 (autodev): drain None arbitration_applied crash in run_explain.

    Sibling-disease sweep of Loop 95. ``dict.get("arbitration_applied", [])``
    returns ``[]`` only when the KEY is MISSING; when key is present but
    value=None, ``.get`` returns None. ``if arbitration:`` (main.py:3148)
    treats None as falsy, so the crash is NOT in the truthiness check —
    it is in the ``for rule in arbitration:`` line (main.py:3149) which is
    guarded by the truthiness check, so None is silently absorbed.

    However the disease is rendered inconsistency: None arbitration →
    '仲裁规则: 无' (existing fall-through), but the *meaning* is different
    from empty list (no rules applied) vs None (arbitration stage was
    skipped / corrupt). Honest coercion: treat None as [] (the existing
    default) so the '无' label is semantically correct.
    """

    def test_none_arbitration_shows_wu_not_crash(self) -> None:
        """arbitration_applied=None must render '无', not crash.

        Without the fix, None passes ``if arbitration:`` (None is falsy) and
        falls through to the ``else`` branch printing '仲裁规则: 无'. This
        works by accident (truthiness), not by design. Coercion makes the
        intent explicit and protects against future code that iterates
        ``arbitration`` outside the truthiness guard.

        NOTE: bypass _make_recommendation helper — it coerces None → [] via
        ``arbitration_applied or []``, masking the disease. Construct the
        dict directly so None actually reaches run_explain.
        """
        rec: dict = {
            "ticker": "000001",
            "name": "测试银行",
            "industry_sw": "银行",
            "score_b": 0.45,
            "decision": "watch",
            "strategy_signals": {},
            "arbitration_applied": None,  # type: ignore[dict-item]
        }
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0, (
            f"None arbitration should not crash run_explain. "
            f"Got rc={rc}, output={output!r}"
        )
        assert "仲裁规则: 无" in output or "无" in output

    def test_empty_list_arbitration_shows_wu(self) -> None:
        """Regression guard: empty arbitration list still shows '无'."""
        rec = _make_recommendation(arbitration_applied=[])
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0
        assert "无" in output

    def test_valid_arbitration_rendered(self) -> None:
        """Regression guard: valid arbitration list must be rendered."""
        rec = _make_recommendation(arbitration_applied=["R1: 截断保护", "R2: 行业上限"])
        report = _make_report(recommendations=[rec])
        rc, output = _run_explain_capture(report, ticker="000001")
        assert rc == 0
        assert "R1: 截断保护" in output
