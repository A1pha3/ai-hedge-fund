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
        from datetime import datetime
        # Deterministic: Fri report (2026-06-12) read Wed (2026-06-17) = 2
        # elapsed trading days (Mon, Tue) → stale. The old `now - 3 days` form
        # was weekend-flaky (e.g. on Sunday it collapses to a same-week report).
        result = _check_report_freshness("20260612", now=datetime(2026, 6, 17))
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


# ---------------------------------------------------------------------------
# _apply_consecutive_bonus_and_resort
# ---------------------------------------------------------------------------


class TestApplyConsecutiveBonusAndResort:
    """R4: fold consecutive_bonus into composite_score and re-sort descending."""

    def test_empty_list_returns_empty(self) -> None:
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        assert _apply_consecutive_bonus_and_resort([]) == []

    def test_zero_bonus_preserves_order(self) -> None:
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        ranked = [
            {"ticker": "a", "composite_score": 0.5, "consecutive_bonus": 0.0},
            {"ticker": "b", "composite_score": 0.3, "consecutive_bonus": 0.0},
        ]
        result = _apply_consecutive_bonus_and_resort(ranked)
        assert [r["ticker"] for r in result] == ["a", "b"]

    def test_bonus_boosted_pick_bubbles_up(self) -> None:
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        ranked = [
            {"ticker": "a", "composite_score": 0.50, "consecutive_bonus": 0.0},
            {"ticker": "b", "composite_score": 0.47, "consecutive_bonus": 0.05},
        ]
        result = _apply_consecutive_bonus_and_resort(ranked)
        assert [r["ticker"] for r in result] == ["b", "a"]
        assert result[0]["composite_score"] == pytest.approx(0.52)

    def test_score_rounded_to_four_decimals(self) -> None:
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        ranked = [{"ticker": "a", "composite_score": 0.123456, "consecutive_bonus": 0.03}]
        result = _apply_consecutive_bonus_and_resort(ranked)
        assert result[0]["composite_score"] == round(0.123456 + 0.03, 4)

    def test_missing_bonus_key_treated_as_zero(self) -> None:
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        ranked = [{"ticker": "a", "composite_score": 0.5}]  # no consecutive_bonus key
        result = _apply_consecutive_bonus_and_resort(ranked)
        assert result[0]["composite_score"] == pytest.approx(0.5)

    def test_mutates_in_place_and_returns_same_list(self) -> None:
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        ranked = [{"ticker": "a", "composite_score": 0.5, "consecutive_bonus": 0.04}]
        result = _apply_consecutive_bonus_and_resort(ranked)
        assert result is ranked


# ---------------------------------------------------------------------------
# _enrich_with_consecutive_bonus
# ---------------------------------------------------------------------------


class TestEnrichWithConsecutiveBonus:
    """Best-effort enrichment wrapper: exception-safe + assigns consecutive_bonus."""

    def test_exception_returns_original_unchanged(self, tmp_path) -> None:
        from src.screening import top_picks

        recs = [{"ticker": "a", "composite_score": 0.5}]
        original_recs = list(recs)

        def boom(**kwargs):
            raise RuntimeError("disk read failed")

        import unittest.mock as mock

        with mock.patch.object(top_picks, "enrich_recommendations_with_history", side_effect=boom):
            result = top_picks._enrich_with_consecutive_bonus(recs, tmp_path)

        assert result is recs or result == original_recs

    def test_assigns_bonus_from_consecutive_days(self, tmp_path) -> None:
        from src.screening import top_picks

        enriched_data = [
            {"ticker": "a", "consecutive_days": 5},
            {"ticker": "b", "consecutive_days": 2},
        ]

        def fake_enrich(**kwargs):
            return list(enriched_data)

        import unittest.mock as mock

        with mock.patch.object(top_picks, "enrich_recommendations_with_history", side_effect=fake_enrich):
            result = top_picks._enrich_with_consecutive_bonus([], tmp_path)

        assert result[0]["consecutive_bonus"] == _consecutive_bonus(5)
        assert result[1]["consecutive_bonus"] == _consecutive_bonus(2)
        assert result[0]["consecutive_bonus"] == 0.05
        assert result[1]["consecutive_bonus"] == 0.0

    def test_missing_consecutive_days_defaults_to_zero(self, tmp_path) -> None:
        from src.screening import top_picks

        enriched_data = [{"ticker": "a"}]  # no consecutive_days key

        def fake_enrich(**kwargs):
            return list(enriched_data)

        import unittest.mock as mock

        with mock.patch.object(top_picks, "enrich_recommendations_with_history", side_effect=fake_enrich):
            result = top_picks._enrich_with_consecutive_bonus([], tmp_path)

        assert result[0]["consecutive_bonus"] == 0.0
