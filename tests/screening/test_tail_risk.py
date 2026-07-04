"""Tests for src/screening/tail_risk.py — Q-5 尾部风险 (5th-pct CVaR)."""

from __future__ import annotations

import pytest

from src.screening.tail_risk import (
    TailRiskReport,
    _percentile_or_none,
    compute_tail_risk,
    render_tail_risk_line,
)

# ---------------------------------------------------------------------------
# _percentile_or_none
# ---------------------------------------------------------------------------


class TestPercentile:
    def test_p5_of_simple_dist(self) -> None:
        """5th percentile of [1..20] ≈ 1.95 (linear interp)."""
        values = list(range(1, 21))  # 1..20
        p5 = _percentile_or_none(values, 5)
        assert p5 is not None
        assert 1.0 <= p5 <= 2.5  # near the bottom

    def test_p5_picks_near_worst(self) -> None:
        """5th-pct should be close to the minimum for a reasonable sample."""
        values = [-30.0, -25.0, -20.0, -15.0, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0]
        p5 = _percentile_or_none(values, 5)
        assert p5 is not None
        assert p5 <= -25.0  # near the worst tail

    def test_empty_none(self) -> None:
        assert _percentile_or_none([], 5) is None

    def test_single_none(self) -> None:
        """1 value → percentile undefined (need ≥2 for interpolation) → None."""
        assert _percentile_or_none([5.0], 5) is None

    def test_identical_values(self) -> None:
        """All same value → percentile = that value."""
        assert _percentile_or_none([3.0, 3.0, 3.0, 3.0], 5) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# compute_tail_risk
# ---------------------------------------------------------------------------


class TestComputeTailRisk:
    def test_tail_risk_from_returns(self) -> None:
        """Worst-tail outcomes → 5th-pct deeply negative."""
        returns = [-30.0, -25.0, -20.0, -15.0, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0]
        report = compute_tail_risk(returns)
        assert report.p5_return is not None
        assert report.p5_return <= -25.0  # near worst
        assert report.available is True
        assert report.sample_count == 10

    def test_insufficient_samples(self) -> None:
        """<2 returns → available False (honest, not a fake 0)."""
        report = compute_tail_risk([5.0])
        assert report.available is False
        assert report.p5_return is None

    def test_empty(self) -> None:
        report = compute_tail_risk([])
        assert report.available is False

    def test_positive_tail_still_computed(self) -> None:
        """Even all-positive returns → p5 is the low end (still honest)."""
        returns = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        report = compute_tail_risk(returns)
        assert report.available is True
        assert report.p5_return is not None
        assert report.p5_return < 2.0  # near the low end

    def test_extreme_outlier_visible(self) -> None:
        """A single -50% outlier among mild returns → p5 captures it (tail ≠ mean)."""
        returns = [-50.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        report = compute_tail_risk(returns)
        # p5 should be near -50 (the tail), NOT near the mean (~0)
        assert report.p5_return is not None
        assert report.p5_return < -5.0  # tail captured, distinct from mean


# ---------------------------------------------------------------------------
# render_tail_risk_line
# ---------------------------------------------------------------------------


class TestRenderTailRiskLine:
    def test_renders_p5(self) -> None:
        report = TailRiskReport(p5_return=-18.0, sample_count=45, available=True)
        out = render_tail_risk_line(report)
        assert "尾部" in out or "5%" in out
        assert "-18" in out

    def test_deep_tail_warns(self) -> None:
        """p5 worse than -15% → ⚠ deep-tail warning."""
        report = TailRiskReport(p5_return=-20.0, sample_count=45, available=True)
        out = render_tail_risk_line(report)
        assert "⚠" in out

    def test_moderate_tail_no_warning(self) -> None:
        report = TailRiskReport(p5_return=-5.0, sample_count=45, available=True)
        out = render_tail_risk_line(report)
        assert "⚠" not in out

    def test_unavailable_empty(self) -> None:
        report = TailRiskReport(p5_return=None, sample_count=0, available=False)
        assert render_tail_risk_line(report) == ""
