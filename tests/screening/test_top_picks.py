"""Tests for src/screening/top_picks.py — P12-2 Top Picks pure helpers."""

from __future__ import annotations

import pytest

from src.screening.top_picks import (
    _check_report_freshness,
    _compute_confluence,
    _consecutive_bonus,
    _render_confluence,
    _render_factor_attribution,
    _render_market_opportunity_index,
    _render_pick_changes,
    _render_sector_focus,
    _render_sector_rotation,
    _status_icon,
)


# ---------------------------------------------------------------------------
# _consecutive_bonus
# ---------------------------------------------------------------------------


class TestConsecutiveBonus:
    def test_less_than_3(self) -> None:
        assert _consecutive_bonus(0) == 0.0
        assert _consecutive_bonus(1) == 0.0
        assert _consecutive_bonus(2) == 0.0

    def test_3_days(self) -> None:
        assert _consecutive_bonus(3) == 0.03

    def test_4_days(self) -> None:
        assert _consecutive_bonus(4) == 0.04

    def test_5_days(self) -> None:
        assert _consecutive_bonus(5) == 0.05

    def test_6_plus(self) -> None:
        assert _consecutive_bonus(6) == 0.08
        assert _consecutive_bonus(10) == 0.08


# ---------------------------------------------------------------------------
# _status_icon
# ---------------------------------------------------------------------------


class TestStatusIcon:
    def test_reentry(self) -> None:
        assert _status_icon("reentry") == "🔄"

    def test_3plus(self) -> None:
        assert _status_icon("3plus") == "🔁"

    def test_2days(self) -> None:
        assert _status_icon("2days") == "🔁"

    def test_broken(self) -> None:
        assert _status_icon("broken") == "⬇️"

    def test_new(self) -> None:
        assert _status_icon("new") == "🆕"


# ---------------------------------------------------------------------------
# _compute_confluence
# ---------------------------------------------------------------------------


class TestComputeConfluence:
    def test_all_bullish(self) -> None:
        item = {"strategy_signals": {
            "trend": {"direction": 1, "confidence": 80},
            "mean_reversion": {"direction": 1, "confidence": 70},
            "fundamental": {"direction": 1, "confidence": 90},
            "event_sentiment": {"direction": 1, "confidence": 85},
        }}
        bullish, total = _compute_confluence(item)
        assert bullish == 4
        assert total == 4

    def test_mixed(self) -> None:
        item = {"strategy_signals": {
            "trend": {"direction": 1, "confidence": 80},
            "fundamental": {"direction": -1, "confidence": 90},
        }}
        bullish, total = _compute_confluence(item)
        assert bullish == 1
        assert total == 2

    def test_no_signals(self) -> None:
        assert _compute_confluence({}) == (0, 0)

    def test_empty_signals(self) -> None:
        assert _compute_confluence({"strategy_signals": {}}) == (0, 0)


# ---------------------------------------------------------------------------
# _render_confluence
# ---------------------------------------------------------------------------


class TestRenderConfluence:
    def test_zero_total(self) -> None:
        assert _render_confluence(0, 0) == ""

    def test_full_confluence(self) -> None:
        result = _render_confluence(4, 4)
        assert "4/4" in result

    def test_partial(self) -> None:
        result = _render_confluence(2, 4)
        assert "2/4" in result


# ---------------------------------------------------------------------------
# _render_factor_attribution
# ---------------------------------------------------------------------------


class TestRenderFactorAttribution:
    def test_no_signals(self) -> None:
        assert _render_factor_attribution({}) == ""

    def test_with_signals(self) -> None:
        item = {"strategy_signals": {
            "trend": {"direction": 1, "confidence": 80},
            "fundamental": {"direction": -1, "confidence": 60},
        }}
        result = _render_factor_attribution(item)
        assert "主因:" in result
        assert "趋势↑" in result
        assert "基本面↓" in result

    def test_all_neutral(self) -> None:
        item = {"strategy_signals": {
            "trend": {"direction": 0, "confidence": 50},
        }}
        assert _render_factor_attribution(item) == ""


# ---------------------------------------------------------------------------
# _check_report_freshness
# ---------------------------------------------------------------------------


class TestCheckReportFreshness:
    def test_empty_date(self) -> None:
        assert _check_report_freshness("") == ""

    def test_invalid_date(self) -> None:
        assert _check_report_freshness("invalid") == ""

    def test_today_is_fresh(self) -> None:
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        assert _check_report_freshness(today) == ""

    def test_yesterday_is_fresh(self) -> None:
        from datetime import datetime, timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        assert _check_report_freshness(yesterday) == ""

    def test_old_report_warns(self) -> None:
        from datetime import datetime, timedelta
        old = (datetime.now() - timedelta(days=3)).strftime("%Y%m%d")
        result = _check_report_freshness(old)
        assert "非最新" in result


# ---------------------------------------------------------------------------
# _render_pick_changes
# ---------------------------------------------------------------------------


class TestRenderPickChanges:
    def test_no_changes(self) -> None:
        assert _render_pick_changes(set(), set(), []) == ""

    def test_new_picks(self) -> None:
        result = _render_pick_changes({"000001"}, set(), [])
        assert "新入选" in result
        assert "000001" in result

    def test_dropped_picks(self) -> None:
        result = _render_pick_changes(set(), {"000002"}, [])
        assert "退出" in result
        assert "000002" in result


# ---------------------------------------------------------------------------
# _render_sector_focus
# ---------------------------------------------------------------------------


class TestRenderSectorFocus:
    def test_empty(self) -> None:
        assert _render_sector_focus([]) == ""

    def test_with_industries(self) -> None:
        picks = [
            {"industry_sw": "电子"},
            {"industry_sw": "电子"},
            {"industry_sw": "银行"},
        ]
        result = _render_sector_focus(picks)
        assert "电子" in result
        assert "行业聚焦" in result

    def test_unknown_industry_excluded(self) -> None:
        picks = [{"industry_sw": "未知"}, {"industry_sw": ""}]
        assert _render_sector_focus(picks) == ""


# ---------------------------------------------------------------------------
# _render_sector_rotation
# ---------------------------------------------------------------------------


class TestRenderSectorRotation:
    def test_no_rotation_data(self) -> None:
        assert _render_sector_rotation({}, []) == ""

    def test_with_rotation(self) -> None:
        report = {"industry_rotation": [
            {"industry_name": "电子", "momentum_score": 50.0},
            {"industry_name": "银行", "momentum_score": -30.0},
        ]}
        picks = [{"industry_sw": "电子"}, {"industry_sw": "银行"}]
        result = _render_sector_rotation(report, picks)
        assert "行业轮动" in result
        assert "电子" in result


# ---------------------------------------------------------------------------
# _render_market_opportunity_index
# ---------------------------------------------------------------------------


class TestRenderMarketOpportunityIndex:
    def test_empty_picks(self) -> None:
        result = _render_market_opportunity_index([], "normal")
        assert "CAUTION" in result

    def test_normal_regime(self) -> None:
        """Without strategy_signals the verdict defaults to AVOID, so buy_count=0 → CAUTION."""
        picks = [{"composite_score": 0.6}]
        result = _render_market_opportunity_index(picks, "normal")
        # buy_count=0, high_quality=1 → score = 0 + 0.3 = 0.3 → CAUTION
        assert "CAUTION" in result

    def test_crisis_regime(self) -> None:
        picks = [{"composite_score": 0.6}]
        result = _render_market_opportunity_index(picks, "crisis")
        assert "WAIT" in result
