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
# _classify_return_rhythm (O-3 / 收益节奏标签)
# ---------------------------------------------------------------------------


class TestClassifyReturnRhythm:
    """O-3: classify the T+30 gain pattern as 早/匀/晚 from the 5-horizon
    cumulative return shape. Serves the product goal's explicit '持续时间综合最优'
    dimension (line 31: 10天涨50% > 5天涨20% — the user must distinguish a
    slow-grind holdable winner from a fast-mover that fades). Display-only, does
    not enter ranking (avoids new sort-dimension bloat)."""

    def test_early_most_gain_by_t5(self) -> None:
        from src.screening.top_picks import _classify_return_rhythm

        # t5=0.06, t30=0.08 → 75% of gain by T+5
        assert _classify_return_rhythm({"t5": 0.06, "t20": 0.08, "t30": 0.08}) == "早"

    def test_late_most_gain_after_t20(self) -> None:
        from src.screening.top_picks import _classify_return_rhythm

        # t20=0.03, t30=0.08 → 62.5% of gain after T+20
        assert _classify_return_rhythm({"t5": 0.01, "t20": 0.03, "t30": 0.08}) == "晚"

    def test_steady_linear_gain(self) -> None:
        from src.screening.top_picks import _classify_return_rhythm

        # roughly linear: t5=0.015, t20=0.05, t30=0.08
        assert _classify_return_rhythm({"t5": 0.015, "t20": 0.05, "t30": 0.08}) == "匀"

    def test_negative_or_zero_t30_returns_dash(self) -> None:
        from src.screening.top_picks import _classify_return_rhythm

        assert _classify_return_rhythm({"t5": 0.01, "t20": 0.02, "t30": 0.0}) == "—"
        assert _classify_return_rhythm({"t5": 0.01, "t20": 0.02, "t30": -0.03}) == "—"

    def test_missing_horizons_returns_dash(self) -> None:
        from src.screening.top_picks import _classify_return_rhythm

        assert _classify_return_rhythm({}) == "—"
        assert _classify_return_rhythm({"t5": 0.05, "t30": 0.08}) == "—"  # no t20
        assert _classify_return_rhythm(None) == "—"  # type: ignore[arg-type]

    def test_non_numeric_returns_dash(self) -> None:
        from src.screening.top_picks import _classify_return_rhythm

        assert _classify_return_rhythm({"t5": "n/a", "t20": 0.05, "t30": 0.08}) == "—"


# ---------------------------------------------------------------------------
# _format_sample_count (O-2 / R35 mature-T+30 disclosure)
# ---------------------------------------------------------------------------


class TestFormatSampleCount:
    """O-2: T+30 winrate confidence calibration. The winrate is computed over ALL
    bucket records, but only *mature* ones (R35 ``bucket_t30_mature_count``) have
    full 30-day outcomes — and the BUY gate requires mature >= 20. Showing
    ``样本=N(熟M)`` when M < N lets the user see that a 62% winrate on 50 samples
    of which only 20 are mature is weaker evidence than the bare "样本=50" implies."""

    def test_mature_less_than_total_shows_suffix(self) -> None:
        from src.screening.top_picks import _format_sample_count

        assert _format_sample_count({"bucket_sample_count": 50, "bucket_t30_mature_count": 20}) == "50(熟20)"

    def test_mature_equals_total_no_suffix(self) -> None:
        from src.screening.top_picks import _format_sample_count

        assert _format_sample_count({"bucket_sample_count": 30, "bucket_t30_mature_count": 30}) == "30"

    def test_mature_exceeds_total_clamped_no_suffix(self) -> None:
        from src.screening.top_picks import _format_sample_count

        assert _format_sample_count({"bucket_sample_count": 10, "bucket_t30_mature_count": 15}) == "10"

    def test_no_mature_field_just_total(self) -> None:
        from src.screening.top_picks import _format_sample_count

        assert _format_sample_count({"bucket_sample_count": 45}) == "45"

    def test_missing_sample_count_zero(self) -> None:
        from src.screening.top_picks import _format_sample_count

        assert _format_sample_count({}) == "0"


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

    def test_tied_composite_tiebreaks_by_t30_edge_not_alphabetical(self) -> None:
        """R143/O-1: when picks tie on composite_score (post-bonus), the tie-break
        must be risk-aware — higher T+30 edge ranks first — restoring the
        investability 6-tuple (rank_recommendations_by_investability:309) that the
        bonus re-sort was discarding. Product goal "更高确信": the user must see the
        stronger-evidence BUY first, not whichever ticker sorts alphabetically.

        Before: two BUY picks with equal composite but different edge sorted
        alphabetically (000001 < 600999), hiding the 12%-edge pick below the 8%-edge one."""
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        ranked = [
            {"ticker": "000001", "composite_score": 0.50, "consecutive_bonus": 0.0,
             "expected_returns": {"t30": 0.08}, "win_rates": {"t30": 0.62},
             "bucket_sample_count": 45, "score_b": 0.50},
            {"ticker": "600999", "composite_score": 0.50, "consecutive_bonus": 0.0,
             "expected_returns": {"t30": 0.12}, "win_rates": {"t30": 0.58},
             "bucket_sample_count": 120, "score_b": 0.50},
        ]
        result = _apply_consecutive_bonus_and_resort(ranked)
        # 600999 has higher T+30 edge (12% > 8%) → ranks first despite 000001 < 600999
        assert result[0]["ticker"] == "600999"
        assert result[1]["ticker"] == "000001"

    def test_tied_composite_and_edge_tiebreaks_by_winrate(self) -> None:
        """R143/O-1: when composite AND t30_edge both tie, higher T+30 winrate ranks
        first (the 6-tuple's 3rd level). Confirms the full risk-aware cascade."""
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        ranked = [
            {"ticker": "000001", "composite_score": 0.50, "consecutive_bonus": 0.0,
             "expected_returns": {"t30": 0.10}, "win_rates": {"t30": 0.62},
             "bucket_sample_count": 45, "score_b": 0.50},
            {"ticker": "600999", "composite_score": 0.50, "consecutive_bonus": 0.0,
             "expected_returns": {"t30": 0.10}, "win_rates": {"t30": 0.58},
             "bucket_sample_count": 120, "score_b": 0.50},
        ]
        result = _apply_consecutive_bonus_and_resort(ranked)
        # 000001 has higher winrate (62% > 58%) → ranks first
        assert result[0]["ticker"] == "000001"

    def test_tied_composite_score_tiebreaks_by_ticker_ascending(self) -> None:
        """R120/BH-011 family: two picks sharing a (rounded) composite_score must not
        depend on input list order. Before the fix the single-key resort preserved
        whatever upstream (JSON-dict / fallback-merge) order ``ranked`` arrived in, so
        two identical runs over the same data could flip which tied ticker reached
        ``representative_picks[:N]`` — breaking the "稳定找到" product goal. The sibling
        ``composite_score.py:312`` already documents ``(-composite_score, -base_score,
        ticker)``; this downstream resort must mirror it (ticker ascending as the
        deterministic final key)."""
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        # Two picks tie at composite_score=0.6000 after bonus folding (R4 rounds to 4dp).
        # Input in descending ticker order to prove the output is NOT just input order.
        ranked_desc = [
            {"ticker": "600999", "composite_score": 0.6000, "consecutive_bonus": 0.0},
            {"ticker": "000001", "composite_score": 0.6000, "consecutive_bonus": 0.0},
        ]
        ranked_asc = list(reversed(ranked_desc))

        result_desc = _apply_consecutive_bonus_and_resort([dict(r) for r in ranked_desc])
        result_asc = _apply_consecutive_bonus_and_resort([dict(r) for r in ranked_asc])

        assert [r["ticker"] for r in result_desc] == ["000001", "600999"]
        assert [r["ticker"] for r in result_asc] == ["000001", "600999"]

    def test_tied_top_n_boundary_does_not_flip_membership(self) -> None:
        """R120/BH-011 family: at the Top-N membership boundary, two tied picks must
        drop/keep deterministically (ticker ascending), so the user sees the same
        stock set every run regardless of upstream dict/JSON iteration order."""
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        base = [
            {"ticker": "000001", "composite_score": 0.9000, "consecutive_bonus": 0.0},
            {"ticker": "600999", "composite_score": 0.5000, "consecutive_bonus": 0.0},
            {"ticker": "300118", "composite_score": 0.5000, "consecutive_bonus": 0.0},
        ]
        # Reverse input order; the two tied-at-0.5 tickers must always come out
        # as 000001 > 300118 > 600999 (ticker ascending within the tie), so a
        # subsequent [:2] cut keeps {000001, 300118} every time.
        result_forward = _apply_consecutive_bonus_and_resort([dict(r) for r in base])
        result_reversed = _apply_consecutive_bonus_and_resort([dict(r) for r in reversed(base)])

        forward_top2 = {r["ticker"] for r in result_forward[:2]}
        reversed_top2 = {r["ticker"] for r in result_reversed[:2]}
        assert forward_top2 == reversed_top2 == {"000001", "300118"}


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


def test_print_hit_rate_block_logs_degradation_on_silent_failure(tmp_path, caplog):
    """BH-021 / R48 BH-017 同族: 前门命中率摘要 (R5) 静默失败时必须发可观测日志。

    背景: ``_print_hit_rate_block`` 此前 ``except Exception: pass`` 静默吞掉
    ``compute_verify_recommendations`` 失败 → 用户看不到前门历史命中率摘要 (R5
    能力)，且无任何信号表明 verify pipeline 降级。破坏"更高确信"目标。修复:
    行为零变更 (仍 best-effort 跳过)，但发 logger.debug 降级诊断。
    """
    import logging
    import unittest.mock as mock

    from src.screening import top_picks

    with mock.patch.object(
        top_picks,
        "compute_verify_recommendations",
        side_effect=RuntimeError("simulated verify pipeline failure"),
    ):
        with caplog.at_level(logging.DEBUG, logger="src.screening.top_picks"):
            # 必须不 raise (行为零变更)
            top_picks._print_hit_rate_block(tmp_path)

    debug_records = [r for r in caplog.records if r.levelname == "DEBUG"]
    assert debug_records, "verify pipeline 静默失败时必须发 DEBUG 级降级诊断"
    joined = "\n".join(r.getMessage() for r in debug_records)
    assert "hit-rate" in joined, "降级日志必须命名 hit-rate summary 降级"

