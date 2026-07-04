"""Tests for src.screening.exit_timing.py — Q-1 卖时机信号.

C259 (2026-06-30): exit windows REALIGNED to the empirically-established optimal
exit. C219 backfill (n=7993 tracking_history records) measured winrate declining
monotonically across horizons: T+5=59.1%, T+10=59.2%, T+15=55.4%, T+20=51.4%,
T+25=48.9%, T+30=45.5%. The owner adopted this (must-win 周期 T+30 → T+5/T+10;
"T+5/T+10 是最佳卖出点, T+30 是长期衰退信号"). The prior window_map (C163, pre-C219)
told 匀/晚-rhythm users to "持有至 T+20–T+30" / "T+30+ 耐心持有" — the LOSS zone
(winrate <50%). These tests lock the corrected behavior: all exit advice stays
within the T+5–T+10 window (the 59% winrate zone), preserving rhythm nuance as
early-vs-late WITHIN that window.
"""

from __future__ import annotations

from src.screening.exit_timing import (
    compute_exit_timing,
    ExitTimingAdvice,
    render_exit_timing,
)

# ---------------------------------------------------------------------------
# compute_exit_timing — C219-aligned exit windows
# ---------------------------------------------------------------------------


class TestComputeExitTiming:
    def test_early_rhythm_short_window(self) -> None:
        """节奏=早 → T+5 关注止盈 (快涨型, 高点靠前, window 前半)."""
        advice = compute_exit_timing(rhythm="早", decay_change_pct=0.0, days_since_peak=0)
        assert "T+5" in advice.suggested_window
        assert "止盈" in advice.suggested_window
        assert advice.decay_warning is False

    def test_uniform_rhythm_within_optimal_window(self) -> None:
        """节奏=匀 → T+5–T+10 关注止盈 (匀速型, hold to END of optimal window).

        C259: was "T+20–T+30 持有" (loss zone, winrate 51%/45.5%). Realigned to
        the T+5–T+10 optimal exit (winrate 59%) per C219 n=7993.
        """
        advice = compute_exit_timing(rhythm="匀", decay_change_pct=0.0, days_since_peak=0)
        assert "T+5" in advice.suggested_window or "T+10" in advice.suggested_window
        assert "止盈" in advice.suggested_window
        # MUST NOT recommend the loss zone
        assert "T+20" not in advice.suggested_window
        assert "T+30" not in advice.suggested_window

    def test_late_rhythm_within_optimal_window(self) -> None:
        """节奏=晚 → T+10 关注止盈 (晚熟型, window 末端; NOT T+30+).

        C259: was "T+30+ 耐心持有" (loss zone, winrate 45.5%). Even late-maturers
        exit within T+5–T+10 — the data shows winrate collapses past T+10
        regardless of rhythm.
        """
        advice = compute_exit_timing(rhythm="晚", decay_change_pct=0.0, days_since_peak=0)
        assert "T+10" in advice.suggested_window
        assert "止盈" in advice.suggested_window
        assert "T+30" not in advice.suggested_window

    def test_no_rhythm_advises_loss_zone_horizon(self) -> None:
        """C259 regression guard: NO rhythm may suggest T+20/T+25/T+30+ exit
        (those are the empirically-confirmed LOSS zones, winrate <52%)."""
        for rhythm in ("早", "匀", "晚"):
            advice = compute_exit_timing(rhythm=rhythm, decay_change_pct=0.0, days_since_peak=0)
            for loss_horizon in ("T+20", "T+25", "T+30"):
                assert loss_horizon not in advice.suggested_window, f"rhythm={rhythm!r} suggests loss-zone {loss_horizon}: {advice.suggested_window!r}"

    def test_unknown_rhythm_no_advice(self) -> None:
        """节奏=— (无数据) → no window, honest not-a-fake-signal."""
        advice = compute_exit_timing(rhythm="—", decay_change_pct=0.0, days_since_peak=0)
        assert advice.suggested_window == ""
        assert advice.available is False

    def test_decay_warning_when_score_declining(self) -> None:
        """信号衰减 (change_pct < 0) → decay_warning True, 提前关注."""
        advice = compute_exit_timing(rhythm="匀", decay_change_pct=-0.15, days_since_peak=3)
        assert advice.decay_warning is True
        assert "衰减" in advice.rationale or "提前" in advice.rationale

    def test_no_decay_when_change_none(self) -> None:
        """change_pct None (首次/无前值) → no decay warning."""
        advice = compute_exit_timing(rhythm="早", decay_change_pct=None, days_since_peak=0)
        assert advice.decay_warning is False

    def test_no_decay_when_change_zero_or_positive(self) -> None:
        """change_pct >= 0 → no decay warning."""
        assert compute_exit_timing(rhythm="匀", decay_change_pct=0.0, days_since_peak=0).decay_warning is False
        assert compute_exit_timing(rhythm="匀", decay_change_pct=0.05, days_since_peak=0).decay_warning is False

    def test_days_since_peak_adds_context(self) -> None:
        """days_since_peak large + decay → stronger exit urgency."""
        advice = compute_exit_timing(rhythm="早", decay_change_pct=-0.10, days_since_peak=5)
        assert advice.decay_warning is True
        assert "5" in advice.rationale or "峰" in advice.rationale


# ---------------------------------------------------------------------------
# render_exit_timing
# ---------------------------------------------------------------------------


class TestRenderExitTiming:
    def test_renders_window_and_no_decay(self) -> None:
        advice = compute_exit_timing(rhythm="早", decay_change_pct=0.0, days_since_peak=0)
        out = render_exit_timing(advice)
        assert "T+5" in out
        assert "止盈" in out
        assert "⚠" not in out  # no decay warning

    def test_renders_decay_warning(self) -> None:
        advice = compute_exit_timing(rhythm="匀", decay_change_pct=-0.12, days_since_peak=4)
        out = render_exit_timing(advice)
        assert "⚠" in out
        assert "衰减" in out or "提前" in out

    def test_unavailable_returns_empty(self) -> None:
        advice = compute_exit_timing(rhythm="—", decay_change_pct=None, days_since_peak=0)
        assert render_exit_timing(advice) == ""

    def test_no_loss_zone_horizon_rendered(self) -> None:
        """C259: rendered output must never show T+20/T+30 hold advice."""
        for rhythm in ("早", "匀", "晚"):
            advice = compute_exit_timing(rhythm=rhythm, decay_change_pct=0.0, days_since_peak=0)
            out = render_exit_timing(advice)
            assert "T+20" not in out
            assert "T+30" not in out
