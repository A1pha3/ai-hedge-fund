"""Tests for src/screening/horizon_conflict.py — R-1 多周期冲突."""

from __future__ import annotations

import pytest

from src.screening.horizon_conflict import (
    HorizonConflict,
    detect_horizon_conflict,
    render_horizon_conflict,
)

# ---------------------------------------------------------------------------
# detect_horizon_conflict
# ---------------------------------------------------------------------------


class TestDetectHorizonConflict:
    def test_short_bullish_long_bearish(self) -> None:
        """T+1/T+5 positive but T+20/T+30 negative → conflict."""
        er = {"t1": 2.0, "t5": 3.0, "t10": 1.0, "t20": -1.0, "t30": -2.0}
        c = detect_horizon_conflict(er)
        assert c.has_conflict is True
        # anchors: t5 (short) vs t20 (long)
        assert "T+5" in c.short_label or "t5" in c.short_label.lower()
        assert "T+20" in c.long_label or "t20" in c.long_label.lower()

    def test_short_bearish_long_bullish(self) -> None:
        """Reverse: T+1 negative but T+30 positive → conflict (fade then recover)."""
        er = {"t1": -2.0, "t5": -1.0, "t10": 0.5, "t20": 1.5, "t30": 2.5}
        c = detect_horizon_conflict(er)
        assert c.has_conflict is True

    def test_aligned_bullish_no_conflict(self) -> None:
        """All horizons positive → no conflict."""
        er = {"t1": 1.0, "t5": 2.0, "t10": 2.5, "t20": 3.0, "t30": 3.2}
        c = detect_horizon_conflict(er)
        assert c.has_conflict is False

    def test_aligned_bearish_no_conflict(self) -> None:
        """All horizons negative → no conflict (consistently bearish, not a conflict)."""
        er = {"t1": -1.0, "t5": -2.0, "t10": -2.5, "t20": -3.0, "t30": -3.2}
        c = detect_horizon_conflict(er)
        assert c.has_conflict is False

    def test_missing_horizons_no_conflict(self) -> None:
        """Missing key horizons → can't determine → no conflict (honest)."""
        er = {"t1": 2.0, "t30": -1.0}  # missing t5/t20
        c = detect_horizon_conflict(er)
        assert c.has_conflict is False

    def test_empty_no_conflict(self) -> None:
        c = detect_horizon_conflict({})
        assert c.has_conflict is False

    def test_near_zero_not_conflict(self) -> None:
        """Values near zero (within epsilon) → treat as no clear sign → no conflict."""
        er = {"t1": 0.05, "t5": 0.05, "t10": 0.05, "t20": -0.05, "t30": -0.05}
        c = detect_horizon_conflict(er)
        # tiny magnitudes shouldn't trigger a strong-conflict flag
        assert c.has_conflict is False

    def test_material_conflict_threshold(self) -> None:
        """Only flag conflict when both sides are materially non-zero (not tiny)."""
        er = {"t1": 2.0, "t5": 1.5, "t10": 0.5, "t20": -1.5, "t30": -2.0}
        c = detect_horizon_conflict(er)
        assert c.has_conflict is True
        assert c.short_value > 0
        assert c.long_value < 0


# ---------------------------------------------------------------------------
# render_horizon_conflict
# ---------------------------------------------------------------------------


class TestRenderHorizonConflict:
    def test_renders_conflict(self) -> None:
        c = HorizonConflict(
            has_conflict=True,
            short_label="T+1",
            short_value=2.0,
            long_label="T+30",
            long_value=-1.5,
        )
        out = render_horizon_conflict(c)
        assert "冲突" in out
        assert "T+1" in out
        assert "T+30" in out
        assert "⚠" in out

    def test_no_conflict_empty(self) -> None:
        c = HorizonConflict(has_conflict=False)
        assert render_horizon_conflict(c) == ""
