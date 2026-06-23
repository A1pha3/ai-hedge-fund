"""Tests for src/screening/exit_timing.py — Q-1 卖时机信号."""

from __future__ import annotations

import pytest

from src.screening.exit_timing import (
    ExitTimingAdvice,
    compute_exit_timing,
    render_exit_timing,
)


# ---------------------------------------------------------------------------
# compute_exit_timing
# ---------------------------------------------------------------------------


class TestComputeExitTiming:
    def test_early_rhythm_short_window(self) -> None:
        """节奏=早 → 建议 T+5–T+10 关注止盈 (peak early, take profits)."""
        advice = compute_exit_timing(rhythm="早", decay_change_pct=0.0, days_since_peak=0)
        assert "T+5" in advice.suggested_window
        assert "止盈" in advice.suggested_window
        assert advice.decay_warning is False

    def test_uniform_rhythm_hold_to_horizon(self) -> None:
        """节奏=匀 → 持有至 T+20–T+30 (steady grind)."""
        advice = compute_exit_timing(rhythm="匀", decay_change_pct=0.0, days_since_peak=0)
        assert "T+20" in advice.suggested_window or "T+30" in advice.suggested_window
        assert "持有" in advice.suggested_window

    def test_late_rhythm_patience(self) -> None:
        """节奏=晚 → T+30+ 耐心持有 (late bloomer, don't exit early)."""
        advice = compute_exit_timing(rhythm="晚", decay_change_pct=0.0, days_since_peak=0)
        assert "T+30" in advice.suggested_window or "耐心" in advice.suggested_window

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
        # rationale should mention the peak age
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
