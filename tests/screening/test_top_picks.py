"""Tests for src/screening/top_picks.py — P12-2 Top Picks pure helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.screening.top_picks import (
    _check_report_freshness,
    _compute_confluence,
    _compute_factor_reason,
    _consecutive_bonus,
    _print_pick_entry,
    _render_confluence,
    _render_factor_attribution,
    _render_market_opportunity_index,
    _render_pick_changes,
    _render_sector_focus,
    _render_sector_rotation,
    _status_icon,
    TopPicksRenderContext,
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
        item = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 80},
                "mean_reversion": {"direction": 1, "confidence": 70},
                "fundamental": {"direction": 1, "confidence": 90},
                "event_sentiment": {"direction": 1, "confidence": 85},
            }
        }
        bullish, total = _compute_confluence(item)
        assert bullish == 4
        assert total == 4

    def test_mixed(self) -> None:
        item = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 80},
                "fundamental": {"direction": -1, "confidence": 90},
            }
        }
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
    def test_zero_total_emits_warning_marker(self) -> None:
        """NS-18 c276: total==0 (数据缺失) 必须标 ⚠无信号 而非空串.

        原先返回空串让用户无法区分 "4 策略都缺失" 与 "策略存在但都是 direction=0".
        修复后返回 ⚠无信号 让数据缺失在呈现层可观测.
        """
        result = _render_confluence(0, 0)
        assert "⚠无信号" in result
        assert result != "", (
            "total==0 必须返回 ⚠无信号 标注, 不再返回空串 (NS-18 c276)"
        )

    def test_full_confluence(self) -> None:
        result = _render_confluence(4, 4)
        assert "4/4" in result

    def test_partial(self) -> None:
        result = _render_confluence(2, 4)
        assert "2/4" in result


# ---------------------------------------------------------------------------
# NS-18 c276: _compute_factor_reason missing field observability
# ---------------------------------------------------------------------------


class TestComputeFactorReasonMissingField:
    """NS-18 c276: LLM agent 输出 missing field (direction/confidence=None) 必须
    发 debug log 让运维知道, 不再静默退化为 0."""

    def test_missing_direction_emits_debug(self, caplog) -> None:
        """direction=None 必须发 debug log (LLM agent 输出 incomplete)."""
        import logging

        item = {
            "strategy_signals": {
                "trend": {"direction": None, "confidence": 0.8},
            }
        }
        with caplog.at_level(logging.DEBUG, logger="src.screening.top_picks"):
            result = _compute_factor_reason(item)

        # 呈现层行为不变: direction=None 退化为 0 → 无 contributions → 返回 ""
        assert result == ""
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 1, (
            f"expected 1 DEBUG for missing direction, got {debug_records}"
        )
        msg = debug_records[0].getMessage()
        assert "missing field" in msg
        assert "trend" in msg
        assert "direction=None" in msg

    def test_missing_confidence_emits_debug(self, caplog) -> None:
        """confidence=None 必须发 debug log (LLM agent 输出 incomplete)."""
        import logging

        item = {
            "strategy_signals": {
                "mean_reversion": {"direction": 1, "confidence": None},
            }
        }
        with caplog.at_level(logging.DEBUG, logger="src.screening.top_picks"):
            result = _compute_factor_reason(item)

        # direction=1 但 confidence=None → strength=0 → 不进 contributions (因 >0 判断)
        # 实际: direction=1>0 → 进 contributions, 但 strength=0
        # 呈现层行为: 返回 "反转↑"
        assert "反转" in result
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 1
        msg = debug_records[0].getMessage()
        assert "missing field" in msg
        assert "mean_reversion" in msg
        assert "confidence=None" in msg

    def test_valid_fields_no_debug(self, caplog) -> None:
        """合法 direction/confidence 不应发 debug (避免日志噪声)."""
        import logging

        item = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 0.8},
                "mean_reversion": {"direction": -1, "confidence": 0.6},
            }
        }
        with caplog.at_level(logging.DEBUG, logger="src.screening.top_picks"):
            result = _compute_factor_reason(item)

        assert result != ""
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 0

    def test_zero_direction_no_debug(self, caplog) -> None:
        """direction=0 (真正的中性信号, 非 None) 不应发 debug."""
        import logging

        item = {
            "strategy_signals": {
                "trend": {"direction": 0, "confidence": 0.5},
            }
        }
        with caplog.at_level(logging.DEBUG, logger="src.screening.top_picks"):
            result = _compute_factor_reason(item)

        # direction=0 不 >0 也不 <0 → 无 contributions → 返回 ""
        assert result == ""
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 0, (
            "direction=0 (真中性) 不应发 debug, 只有 None 才发"
        )


# ---------------------------------------------------------------------------
# _render_factor_attribution
# ---------------------------------------------------------------------------


class TestRenderFactorAttribution:
    def test_no_signals(self) -> None:
        assert _render_factor_attribution({}) == ""

    def test_with_signals(self) -> None:
        item = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 80},
                "fundamental": {"direction": -1, "confidence": 60},
            }
        }
        result = _render_factor_attribution(item)
        assert "主因:" in result
        assert "趋势↑" in result
        assert "基本面↓" in result

    def test_all_neutral(self) -> None:
        item = {
            "strategy_signals": {
                "trend": {"direction": 0, "confidence": 50},
            }
        }
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
        report = {
            "industry_rotation": [
                {"industry_name": "电子", "momentum_score": 50.0},
                {"industry_name": "银行", "momentum_score": -30.0},
            ]
        }
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
        """C269 (2026-07-01): without strategy_signals/calibration the verdict
        defaults to AVOID, so buy_count=0 AND high_quality=0 → score=0 → WAIT.
        Previously the composite-only high_quality filter (composite>=0.5) gave
        AVOID picks the +0.3 bonus, mislabeling all-AVOID days as CAUTION."""
        picks = [{"composite_score": 0.6}]
        result = _render_market_opportunity_index(picks, "normal")
        assert "WAIT" in result
        assert "HQ 0" in result

    def test_crisis_regime(self) -> None:
        picks = [{"composite_score": 0.6}]
        result = _render_market_opportunity_index(picks, "crisis")
        assert "WAIT" in result


# ---------------------------------------------------------------------------
# _suggest_position_pct (A-1 / per-pick position suggestion)
# ---------------------------------------------------------------------------


class TestSuggestPositionPct:
    """A-1: transparent per-pick position suggestion for BUY picks. Simple
    risk-budget — base scaled by confidence (winrate above coin-flip) and the
    decision-horizon edge magnitude, regime-downgraded (crisis/risk_off → 0),
    capped at a per-pick maximum for diversification. Educational decision-support
    only: NOT portfolio optimization (no correlation/risk-parity), reuses the
    R71-R77 disclaimer. Serves the "买哪只 → 买多少" bridge for the product goal.

    C260 (2026-06-30): ``decision_edge`` is in PERCENT (e.g. 8.0 = 8%), matching
    the sole caller ``_extract_decision_horizon_metrics`` (max of T+5/T+10
    expected_returns, rendered as ``f"{decision_edge:+.2f}%"``). The prior tests
    passed FRACTION inputs (0.08) that never occur in production, masking a 100×
    unit bug (the ``×100`` multiplier saturated the 15% cap for ~all BUY picks,
    making the feature non-informative). Tests now use realistic percent inputs.
    """

    def test_normal_regime_scales_with_edge_and_winrate(self) -> None:
        from src.screening.top_picks import _suggest_position_pct

        # edge=8% (percent), winrate=0.62, normal → confidence 0.6, base = 8.0*0.6 = 4.8
        assert (
            _suggest_position_pct(
                decision_edge=8.0, decision_winrate=0.62, market_regime="normal"
            )
            == 4.8
        )

    def test_high_conviction_larger_size(self) -> None:
        from src.screening.top_picks import _suggest_position_pct

        # edge=12%, winrate=0.70 → confidence 1.0, base = 12.0
        assert (
            _suggest_position_pct(
                decision_edge=12.0, decision_winrate=0.70, market_regime="normal"
            )
            == 12.0
        )

    def test_capped_at_max_per_pick(self) -> None:
        from src.screening.top_picks import _suggest_position_pct

        # edge=20%, winrate=0.80 → confidence 1.5, base = 30.0 → capped at 15.0
        assert (
            _suggest_position_pct(
                decision_edge=20.0, decision_winrate=0.80, market_regime="normal"
            )
            == 15.0
        )

    def test_crisis_regime_returns_zero(self) -> None:
        from src.screening.top_picks import _suggest_position_pct

        assert (
            _suggest_position_pct(
                decision_edge=10.0, decision_winrate=0.65, market_regime="crisis"
            )
            == 0.0
        )
        assert (
            _suggest_position_pct(
                decision_edge=10.0, decision_winrate=0.65, market_regime="risk_off"
            )
            == 0.0
        )

    def test_caution_regime_halved(self) -> None:
        from src.screening.top_picks import _suggest_position_pct

        # edge=12%, winrate=0.70 → base 12.0; cautious → ×0.5 = 6.0
        assert (
            _suggest_position_pct(
                decision_edge=12.0, decision_winrate=0.70, market_regime="cautious"
            )
            == 6.0
        )

    def test_non_positive_edge_returns_zero(self) -> None:
        from src.screening.top_picks import _suggest_position_pct

        assert (
            _suggest_position_pct(
                decision_edge=-3.0, decision_winrate=0.60, market_regime="normal"
            )
            == 0.0
        )
        assert (
            _suggest_position_pct(
                decision_edge=0.0, decision_winrate=0.60, market_regime="normal"
            )
            == 0.0
        )

    def test_none_inputs_return_zero(self) -> None:
        from src.screening.top_picks import _suggest_position_pct

        assert (
            _suggest_position_pct(
                decision_edge=None, decision_winrate=0.60, market_regime="normal"
            )
            == 0.0
        )
        assert (
            _suggest_position_pct(
                decision_edge=8.0, decision_winrate=None, market_regime="normal"
            )
            == 0.0
        )

    def test_low_winrate_below_coin_flip_shrinks(self) -> None:
        from src.screening.top_picks import _suggest_position_pct

        # winrate=0.52 (barely above coin-flip) → confidence 0.1, base = 8.0*0.1 = 0.8
        assert (
            _suggest_position_pct(
                decision_edge=8.0, decision_winrate=0.52, market_regime="normal"
            )
            == 0.8
        )

    def test_realistic_pick_does_not_saturate_cap(self) -> None:
        """C260 regression: the bug's signature was that realistic BUY picks
        (edge~4-5%, winrate~0.60) hit the 15% cap. With the unit fix, a typical
        pick must size WELL BELOW the cap (realistic input from 2026-06-30 data:
        edge=4.66%, winrate=0.597 → 4.66*0.485 = 2.26 → 2.3%)."""
        from src.screening.top_picks import _suggest_position_pct

        pos = _suggest_position_pct(
            decision_edge=4.66, decision_winrate=0.597, market_regime="normal"
        )
        assert pos < 15.0  # MUST NOT saturate the cap
        assert 1.5 < pos < 3.5  # sane ~2.3% for a typical pick

    def test_differentiates_by_conviction(self) -> None:
        """C260: the feature must actually differentiate — strong pick > typical
        > marginal (the bug made all three return 15%)."""
        from src.screening.top_picks import _suggest_position_pct

        strong = _suggest_position_pct(
            decision_edge=8.0, decision_winrate=0.70, market_regime="normal"
        )
        typical = _suggest_position_pct(
            decision_edge=4.0, decision_winrate=0.58, market_regime="normal"
        )
        marginal = _suggest_position_pct(
            decision_edge=1.5, decision_winrate=0.52, market_regime="normal"
        )
        assert strong > typical > marginal
        assert marginal < 5.0  # marginal pick gets a small size, not the cap


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

    def test_nan_anchor_horizon_returns_dash(self) -> None:
        """NaN in any anchor horizon → '—' (not silent '匀' misclassification).

        NaN t5 passes isinstance(t5, (int, float)) at line 337, t30<=0 is
        False (NaN compared), so the function falls through all branches into
        the '匀' default — a silent misclassification. The fix adds math.isfinite
        or safe_float guards so the function returns '—' for corrupt data.
        """
        import math
        from src.screening.top_picks import _classify_return_rhythm

        nan = math.nan
        assert _classify_return_rhythm({"t5": nan, "t20": 0.05, "t30": 0.08}) == "—", (
            "NaN t5 → '—', not fall-through to 匀"
        )
        assert _classify_return_rhythm({"t5": 0.06, "t20": nan, "t30": 0.08}) == "—", (
            "NaN t20 → '—'"
        )
        assert _classify_return_rhythm({"t5": 0.06, "t20": 0.05, "t30": nan}) == "—", (
            "NaN t30 → '—', not fall-through (NaN t30 <= 0 is False)"
        )
        assert _classify_return_rhythm({"t5": nan, "t20": nan, "t30": nan}) == "—"


# ---------------------------------------------------------------------------
# Loops 63-64 (autodev): NaN display-layer guard — position sizing / portfolio
# ---------------------------------------------------------------------------


class TestDecisionHorizonMetricsWithNan:
    """loop 64: _extract_decision_horizon_metrics — NaN in horizon dicts must
    not propagate to position-sizing / portfolio aggregation as nan%.

    _extract_decision_horizon_metrics calls _max_short_horizon_metric which
    filters with isinstance(raw, (int, float)) — NaN passes through. The
    caller _suggest_position_pct checks 'decision_edge <= 0' which returns
    False for NaN, letting NaN into the position-size computation and
    ultimately rendering as '建议仓位=nan%'.

    These tests pin the NaN-aware behavior.
    """

    def test_extract_nan_horizon_returns_none(self) -> None:
        import math
        from src.screening.top_picks import _extract_decision_horizon_metrics

        edge, winrate = _extract_decision_horizon_metrics({
            "expected_returns": {"t5": math.nan, "t10": math.nan},
            "win_rates": {"t5": math.nan, "t10": math.nan},
        })
        assert edge is None, f"expected None for NaN edge, got {edge!r}"
        assert winrate is None, f"expected None for NaN winrate, got {winrate!r}"

    def test_extract_mixed_nan_horizon_returns_clean(self) -> None:
        import math
        from src.screening.top_picks import _extract_decision_horizon_metrics

        edge, winrate = _extract_decision_horizon_metrics({
            "expected_returns": {"t5": math.nan, "t10": 9.0},
            "win_rates": {"t5": math.nan, "t10": 0.62},
        })
        assert edge == 9.0, f"expected 9.0 for mixed NaN/clean edge, got {edge!r}"
        assert winrate == 0.62, f"expected 0.62 for mixed NaN/clean winrate, got {winrate!r}"


class TestNanDoesNotRenderNanInPositionSizing:
    """loop 63: _suggest_position_pct must not render nan% when NaN flows
    through from horizon dicts.

    The bug chain: all-NaN expected_returns → _extract_decision_horizon_metrics
    → None (after fix) → _suggest_position_pct → 0.0 (not NaN+confidence→nan%).
    """

    def test_nan_expected_returns_gives_zero_position(self) -> None:
        import math
        from src.screening.top_picks import _suggest_position_pct

        pos = _suggest_position_pct(
            decision_edge=math.nan,
            decision_winrate=math.nan,
            market_regime="trend",
        )
        assert pos == 0.0, (
            f"NaN decision_edge → position should be 0.0, got {pos!r}"
        )

    def test_nan_winrate_with_finite_edge_gives_position(self) -> None:
        import math
        from src.screening.top_picks import _suggest_position_pct

        # NaN winrate should not crash — confidence should be treated safely
        pos = _suggest_position_pct(
            decision_edge=5.0,
            decision_winrate=math.nan,
            market_regime="trend",
        )
        assert isinstance(pos, (int, float)), "position must be a number"
        assert pos >= 0.0, "position must be non-negative"


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

        assert (
            _format_sample_count(
                {"bucket_sample_count": 50, "bucket_t30_mature_count": 20}
            )
            == "50(熟20)"
        )

    def test_mature_equals_total_no_suffix(self) -> None:
        from src.screening.top_picks import _format_sample_count

        assert (
            _format_sample_count(
                {"bucket_sample_count": 30, "bucket_t30_mature_count": 30}
            )
            == "30"
        )

    def test_mature_exceeds_total_clamped_no_suffix(self) -> None:
        from src.screening.top_picks import _format_sample_count

        assert (
            _format_sample_count(
                {"bucket_sample_count": 10, "bucket_t30_mature_count": 15}
            )
            == "10"
        )

    def test_no_mature_field_just_total(self) -> None:
        from src.screening.top_picks import _format_sample_count

        assert _format_sample_count({"bucket_sample_count": 45}) == "45"

    def test_missing_sample_count_zero(self) -> None:
        from src.screening.top_picks import _format_sample_count

        assert _format_sample_count({}) == "0"


# ---------------------------------------------------------------------------
# _print_pick_entry — T+30 winrate low-confidence flag (R51/R52 family)
# ---------------------------------------------------------------------------


class TestPrintPickEntryT30LowConfidence:
    """R141 Bug Hunt (R51/R52 family — coverage gap drain): c271 added the
    ``⚠少样本`` low-confidence marker to ``render_expected_returns_compact``
    (--decision-flow view), c277 to ``render_expected_returns`` (full
    --expected-returns table), but ``_print_pick_entry`` (the DEFAULT front door
    ``--top-picks`` per-pick row) was missed — it renders ``T+30胜率`` without
    the flag even when ``bucket_t30_mature_count < 5``, same R51/R52 family
    coverage gap. A per-bucket n=1 "100% winrate" renders confident-green in
    the default front door while the sibling expected-returns table flags it
    yellow — inconsistent honesty across surfaces in the same command.
    """

    @patch("src.screening.top_picks.build_front_door_verdict")
    def test_t30_winrate_flags_low_confidence_when_mature_tiny(
        self, mock_verdict, capsys
    ) -> None:
        """Tiny mature sample (n=1, 100% winrate) must flag ⚠少样本."""
        mock_verdict.return_value = {
            "action": "HOLD",
            "market_regime": "NORMAL",
            "signal_horizon": "",
            "invalidation_reason": "",
        }
        item = {
            "ticker": "000001",
            "name": "TestStock",
            "score_b": 0.85,
            "composite_score": 0.8,
            "win_rates": {"t30": 1.0, "t5": 0.6, "t10": 0.6},
            "expected_returns": {"t30": 0.03, "t5": 0.01, "t10": 0.012},
            "bucket_sample_count": 4,
            "bucket_t30_mature_count": 1,
        }
        ctx = TopPicksRenderContext(
            market_regime="NORMAL",
            new_tickers=set(),
            report_dir=Path("."),
            trade_date="20260701",
        )
        _print_pick_entry(1, item, ctx)
        out = capsys.readouterr().out
        assert "少样本" in out or "⚠" in out, (
            "_print_pick_entry (--top-picks per-pick row) must flag T+30 winrate "
            "low-confidence when mature sample < 5 — c271/c277 fixed the expected_return "
            "renderers but missed the default front door's per-pick row."
        )

    @patch("src.screening.top_picks.build_front_door_verdict")
    def test_t30_winrate_no_flag_when_mature_sufficient(
        self, mock_verdict, capsys
    ) -> None:
        """Sufficient mature sample (n=20) must NOT emit the low-confidence marker."""
        mock_verdict.return_value = {
            "action": "HOLD",
            "market_regime": "NORMAL",
            "signal_horizon": "",
            "invalidation_reason": "",
        }
        item = {
            "ticker": "000001",
            "name": "TestStock",
            "score_b": 0.85,
            "composite_score": 0.8,
            "win_rates": {"t30": 0.6, "t5": 0.6, "t10": 0.6},
            "expected_returns": {"t30": 0.03, "t5": 0.01, "t10": 0.012},
            "bucket_sample_count": 50,
            "bucket_t30_mature_count": 20,
        }
        ctx = TopPicksRenderContext(
            market_regime="NORMAL",
            new_tickers=set(),
            report_dir=Path("."),
            trade_date="20260701",
        )
        _print_pick_entry(1, item, ctx)
        out = capsys.readouterr().out
        assert "少样本" not in out


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

        ranked = [
            {"ticker": "a", "composite_score": 0.123456, "consecutive_bonus": 0.03}
        ]
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

    def test_tied_composite_tiebreaks_by_decision_horizon_edge_not_alphabetical(
        self,
    ) -> None:
        """R143/O-1: when picks tie on composite_score (post-bonus), the tie-break
        must be risk-aware — higher BUY-gate decision-horizon edge (max t5/t10)
        ranks first — restoring the investability 6-tuple
        (rank_recommendations_by_investability:309) that the bonus re-sort was
        discarding. Product goal "更高确信": the user must see the stronger-evidence
        BUY first, not whichever ticker sorts alphabetically.

        C222 (2026-06-28 horizon 一致性): tie-breakers 2/3 changed from t30_edge /
        t30_winrate to ``_max_short_horizon_metric`` (max of t5/t10) to align with
        BUY gate horizon (T+5 OR T+10 pass, see C220 commit 4184dd7e). Test data
        now uses t5 as the decision-horizon carrier (max(t5, t10) == t5 when t10
        absent).

        Before: two BUY picks with equal composite but different edge sorted
        alphabetically (000001 < 600999), hiding the 12%-edge pick below the 8%-edge one."""
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        ranked = [
            {
                "ticker": "000001",
                "composite_score": 0.50,
                "consecutive_bonus": 0.0,
                "expected_returns": {"t5": 0.08, "t30": 0.08},
                "win_rates": {"t5": 0.62, "t30": 0.62},
                "bucket_sample_count": 45,
                "score_b": 0.50,
            },
            {
                "ticker": "600999",
                "composite_score": 0.50,
                "consecutive_bonus": 0.0,
                "expected_returns": {"t5": 0.12, "t30": 0.12},
                "win_rates": {"t5": 0.58, "t30": 0.58},
                "bucket_sample_count": 120,
                "score_b": 0.50,
            },
        ]
        result = _apply_consecutive_bonus_and_resort(ranked)
        # 600999 has higher decision-horizon edge (max t5/t10 = 12% > 8%) → ranks
        # first despite 000001 < 600999.
        assert result[0]["ticker"] == "600999"
        assert result[1]["ticker"] == "000001"

    def test_tied_composite_and_edge_tiebreaks_by_decision_horizon_winrate(
        self,
    ) -> None:
        """R143/O-1: when composite AND decision-horizon edge both tie, higher
        decision-horizon winrate ranks first (the 6-tuple's 3rd level). Confirms
        the full risk-aware cascade.

        C222: tie-breaker 3 changed from t30_winrate to max(t5, t10) winrate.
        """
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        ranked = [
            {
                "ticker": "000001",
                "composite_score": 0.50,
                "consecutive_bonus": 0.0,
                "expected_returns": {"t5": 0.10, "t30": 0.10},
                "win_rates": {"t5": 0.62, "t30": 0.62},
                "bucket_sample_count": 45,
                "score_b": 0.50,
            },
            {
                "ticker": "600999",
                "composite_score": 0.50,
                "consecutive_bonus": 0.0,
                "expected_returns": {"t5": 0.10, "t30": 0.10},
                "win_rates": {"t5": 0.58, "t30": 0.58},
                "bucket_sample_count": 120,
                "score_b": 0.50,
            },
        ]
        result = _apply_consecutive_bonus_and_resort(ranked)
        # 000001 has higher decision-horizon winrate (62% > 58%) → ranks first
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

        result_desc = _apply_consecutive_bonus_and_resort(
            [dict(r) for r in ranked_desc]
        )
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
        result_reversed = _apply_consecutive_bonus_and_resort(
            [dict(r) for r in reversed(base)]
        )

        forward_top2 = {r["ticker"] for r in result_forward[:2]}
        reversed_top2 = {r["ticker"] for r in result_reversed[:2]}
        assert forward_top2 == reversed_top2 == {"000001", "300118"}

    # ------------------------------------------------------------------
    # NS-11 (autodev c232): consecutive bonus 不应喂 BUY 门控 — bonus 本意
    # 是排序 tie-break, 不是放水 gate. _apply_consecutive_bonus_and_resort
    # 必须在加 bonus 前存 pre-bonus `composite_score_gated`, 让下游
    # build_front_door_verdict 用 pre-bonus score 判 BUY gate (>=0.5), 用
    # post-bonus composite_score 排序. C220 horizon 对齐后, bonus 污染 gate
    # 会让 0.47 真分 + 0.05 bonus = 0.52 越过 BUY → stale 挑选反而更容易 BUY.
    # ------------------------------------------------------------------

    def test_ns11_preserves_pre_bonus_score_as_composite_score_gated(self) -> None:
        """NS-11: pre-bonus composite_score 必须存入 `composite_score_gated`
        字段, 让 BUY gate 用 pre-bonus score 判定, bonus 仅用于排序."""
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        ranked = [
            {"ticker": "a", "composite_score": 0.47, "consecutive_bonus": 0.05},
        ]
        result = _apply_consecutive_bonus_and_resort(ranked)
        # post-bonus composite_score (用于排序)
        assert result[0]["composite_score"] == pytest.approx(0.52)
        # pre-bonus composite_score_gated (用于 BUY gate, NS-11 新增)
        assert result[0]["composite_score_gated"] == pytest.approx(0.47)

    def test_ns11_zero_bonus_composite_score_gated_equals_composite_score(self) -> None:
        """NS-11: bonus=0 时 composite_score_gated 与 composite_score 相同."""
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        ranked = [
            {"ticker": "a", "composite_score": 0.50, "consecutive_bonus": 0.0},
        ]
        result = _apply_consecutive_bonus_and_resort(ranked)
        assert result[0]["composite_score_gated"] == pytest.approx(0.50)
        assert result[0]["composite_score"] == pytest.approx(0.50)

    def test_ns11_composite_score_gated_clamped_to_domain(self) -> None:
        """NS-11: composite_score_gated 也必须 clamp 到 [-1.0, 1.0] 域,
        与 composite_score 一致 (composite_score.py:16 文档化域)."""
        from src.screening.top_picks import _apply_consecutive_bonus_and_resort

        # bonus>0 让 composite_score 也被 clamp (bonus=0 时 composite_score 不修改)
        ranked = [
            {"ticker": "a", "composite_score": 1.5, "consecutive_bonus": 0.05},
        ]
        result = _apply_consecutive_bonus_and_resort(ranked)
        # pre-bonus 1.5 clamped to 1.0
        assert result[0]["composite_score_gated"] == 1.0
        # post-bonus 1.5+0.05=1.55 clamped to 1.0
        assert result[0]["composite_score"] == 1.0


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

        with mock.patch.object(
            top_picks, "enrich_recommendations_with_history", side_effect=boom
        ):
            result = top_picks._enrich_with_consecutive_bonus(recs, tmp_path)

        assert result is recs or result == original_recs

    def test_exception_emits_warning_for_ranking_degradation(
        self, tmp_path, caplog
    ) -> None:
        """NS-17 / BH-017 family sibling: enrich 失败时必须发 warning, 不再静默。

        背景: 失败时返回原 list 是有意为之 (best-effort), 但之前完全静默 —
        consecutive_bonus 字段缺失会让下游 ranking 退化到无 bonus tie-breaker
        (C232 已隔离 BUY gate 不喂 bonus, 但 ranking 仍依赖 bonus 做 tie-breaking)。
        修复后必须发 logger.warning 让 operators 能感知 ranking 退化触发。
        """
        import logging
        import unittest.mock as mock

        from src.screening import top_picks

        recs = [{"ticker": "a", "composite_score": 0.5}]
        original_recs = list(recs)

        def boom(**kwargs):
            raise RuntimeError("simulated enrich failure")

        with mock.patch.object(
            top_picks, "enrich_recommendations_with_history", side_effect=boom
        ):
            with caplog.at_level(logging.WARNING, logger="src.screening.top_picks"):
                result = top_picks._enrich_with_consecutive_bonus(recs, tmp_path)

        # Best-effort contract preserved: original list returned.
        assert result is recs or result == original_recs

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1, (
            f"expected >=1 WARNING record from enrich failure, got {caplog.records}"
        )
        msg = warning_records[0].getMessage()
        assert (
            "enrich_recommendations_with_history" in msg or "consecutive_bonus" in msg
        )
        assert "simulated enrich failure" in msg

    def test_assigns_bonus_from_consecutive_days(self, tmp_path) -> None:
        from src.screening import top_picks

        enriched_data = [
            {"ticker": "a", "consecutive_days": 5},
            {"ticker": "b", "consecutive_days": 2},
        ]

        def fake_enrich(**kwargs):
            return list(enriched_data)

        import unittest.mock as mock

        with mock.patch.object(
            top_picks, "enrich_recommendations_with_history", side_effect=fake_enrich
        ):
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

        with mock.patch.object(
            top_picks, "enrich_recommendations_with_history", side_effect=fake_enrich
        ):
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


def test_print_stability_block_renders_when_reports_exist(tmp_path, capsys):
    """P-1: --top-picks footer 必须展示推荐稳定性行（近 N 日 Top-3 Jaccard）。

    产品目标核心形容词"稳定"此前无度量。有 ≥2 份历史报告时，footer 必须渲染
    稳定性摘要行；不足 2 份（首次运行）时静默不渲染，不污染前门。
    """
    import json

    from src.screening import top_picks

    # 3 份相同 Top-3 的报告 → stability 1.0 稳定
    for d in ["20260101", "20260102", "20260103"]:
        payload = {
            "date": d,
            "recommendations": [
                {"ticker": "000001", "name": "平安", "score_b": 0.9},
                {"ticker": "000002", "name": "万科", "score_b": 0.8},
                {"ticker": "000003", "name": "招行", "score_b": 0.7},
            ],
        }
        (tmp_path / f"auto_screening_{d}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    top_picks._print_stability_block(tmp_path)
    out = capsys.readouterr().out
    assert "推荐稳定性" in out
    assert "稳定" in out

    # 空目录 → 静默不渲染
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    top_picks._print_stability_block(empty_dir)
    extra = capsys.readouterr().out
    assert extra == "", "不足 2 份报告时不得渲染稳定性行"


def test_print_concentration_block_warns_when_concentrated(capsys):
    """P-4: --top-picks footer shows ⚠ concentration warning when one industry dominates."""
    from src.screening import top_picks

    picks = [
        {"ticker": "000001", "industry_sw": "电子"},
        {"ticker": "000002", "industry_sw": "电子"},
        {"ticker": "000003", "industry_sw": "电子"},
        {"ticker": "000004", "industry_sw": "电子"},
        {"ticker": "000005", "industry_sw": "银行"},
    ]
    top_picks._print_concentration_block(picks)
    out = capsys.readouterr().out
    assert "电子" in out
    assert "⚠" in out

    # diversified → no warning
    diverse = [{"ticker": f"{i:06d}", "industry_sw": f"行业{i}"} for i in range(5)]
    top_picks._print_concentration_block(diverse)
    out2 = capsys.readouterr().out
    assert "⚠" not in out2


def test_print_correlation_block_warns_on_overlap(capsys):
    """Q-4: --top-picks footer shows ⚠ correlation warning when BUY picks overlap."""
    from src.screening import top_picks

    picks = [
        {"ticker": "000001", "industry_sw": "电子", "score_b": 0.75},
        {"ticker": "000002", "industry_sw": "电子", "score_b": 0.74},
    ]
    top_picks._print_correlation_block(picks)
    out = capsys.readouterr().out
    assert "相关" in out
    assert "⚠" in out

    # independent picks → silent
    indep = [
        {"ticker": "000001", "industry_sw": "电子", "score_b": 0.85},
        {"ticker": "000002", "industry_sw": "银行", "score_b": 0.50},
    ]
    top_picks._print_correlation_block(indep)
    out2 = capsys.readouterr().out
    assert out2 == ""


# ---------------------------------------------------------------------------
# _compute_pick_risk_advice — NS-17 / BH-017 family sibling (c268)
# ---------------------------------------------------------------------------


class TestComputePickRiskAdviceSilentFailure:
    """R32 risk-advice fetcher: best-effort return-None preserved, but failure
    must be observable so operators can correlate missing stop-loss/take-profit
    labels on BUY picks with upstream data-fetch degradation."""

    def test_exception_returns_none_and_emits_warning(self, caplog) -> None:
        """NS-17 / BH-017 family: tushare price fetch raising must NOT be silent.

        背景: ``_compute_pick_risk_advice`` 在 ``get_ashare_prices_with_tushare``
        抛异常时返回 None 是 best-effort 有意为之 (前门永不崩溃), 但之前完全静默 —
        advice=None 会让该 BUY pick 在前门渲染时缺止损/止盈/盈亏比标签 (操作员拿
        到无风险约束的 BUY 信号)。修复后必须发 logger.warning 让 operators 能关
        联"BUY pick 缺风险标签"与"tushare 接口抖动"。
        """
        import logging
        import unittest.mock as mock

        from src.screening import top_picks

        def boom(*args, **kwargs):
            raise RuntimeError("simulated tushare price fetch failure")

        with mock.patch(
            "src.tools.tushare_api.get_ashare_prices_with_tushare", side_effect=boom
        ):
            with caplog.at_level(logging.WARNING, logger="src.screening.top_picks"):
                result = top_picks._compute_pick_risk_advice(
                    "000001", "平安", trade_date="20260101"
                )

        # Best-effort contract preserved: None returned, no crash.
        assert result is None

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning_records, (
            f"expected >=1 WARNING record from risk-advice fetch failure, "
            f"got {caplog.records}"
        )
        msg = warning_records[0].getMessage()
        # Must name the function / feature so operators can grep it.
        assert (
            "_compute_pick_risk_advice" in msg or "risk_advice" in msg.lower()
        ), f"warning must name the degraded feature, got: {msg!r}"
        # Must include the ticker so the operator knows WHICH pick lost its label.
        assert "000001" in msg, f"warning must include ticker, got: {msg!r}"
        # Must include the underlying exception message for triage.
        assert "simulated tushare price fetch failure" in msg

    def test_empty_prices_returns_none_silently(self, caplog) -> None:
        """Empty price series is a legitimate no-data condition, NOT an exception
        — must return None without emitting a warning (avoid log noise when a
        ticker simply has no recent trades)."""
        import logging
        import unittest.mock as mock

        from src.screening import top_picks

        with mock.patch(
            "src.tools.tushare_api.get_ashare_prices_with_tushare", return_value=[]
        ):
            with caplog.at_level(logging.WARNING, logger="src.screening.top_picks"):
                result = top_picks._compute_pick_risk_advice(
                    "000001", "平安", trade_date="20260101"
                )

        assert result is None
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not warning_records, (
            f"empty-price path must be silent, got {warning_records}"
        )
