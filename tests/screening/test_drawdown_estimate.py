"""Tests for src/screening/drawdown_estimate.py — Q-2 回撤预期."""

from __future__ import annotations

import pytest

from src.screening.drawdown_estimate import (
    _estimate_path_max_drawdown,
    compute_drawdown_estimate,
    DrawdownEstimate,
    render_drawdown_line,
)

# ---------------------------------------------------------------------------
# _estimate_path_max_drawdown
# ---------------------------------------------------------------------------


class TestEstimatePathDrawdown:
    def test_monotonic_up_no_drawdown(self) -> None:
        """Path strictly rising → no drawdown → 0.0."""
        # cumulative returns: 1%, 3%, 5%, 8%
        dd = _estimate_path_max_drawdown([1.0, 3.0, 5.0, 8.0])
        assert dd == 0.0

    def test_dip_then_recover(self) -> None:
        """Peak 5% at t5, trough -3% at t10 → drawdown -8%."""
        # t1=2, t5=5 (peak), t10=-3 (trough), t20=1, t30=3.2
        dd = _estimate_path_max_drawdown([2.0, 5.0, -3.0, 1.0, 3.2])
        # peak 5 → trough -3 = -8
        assert dd == pytest.approx(-8.0, abs=1e-3)

    def test_deeper_dip_later(self) -> None:
        """Two dips; the deeper one wins."""
        # t1=1, t5=4 (peak), t10=2 (dip -2), t20=6 (new peak), t30=-1 (trough, -7)
        dd = _estimate_path_max_drawdown([1.0, 4.0, 2.0, 6.0, -1.0])
        # peak 6 → trough -1 = -7 (deeper than 4→2=-2)
        assert dd == pytest.approx(-7.0, abs=1e-3)

    def test_single_point_no_drawdown(self) -> None:
        """1 point → no path → None (can't compute)."""
        assert _estimate_path_max_drawdown([5.0]) is None

    def test_empty_none(self) -> None:
        assert _estimate_path_max_drawdown([]) is None

    def test_with_none_values_skipped(self) -> None:
        """None horizons (no data) → skip; compute on remaining."""
        dd = _estimate_path_max_drawdown([2.0, None, -3.0, 1.0])
        # path [2, -3, 1]: peak 2 → trough -3 = -5
        assert dd == pytest.approx(-5.0, abs=1e-3)

    def test_all_none_none(self) -> None:
        assert _estimate_path_max_drawdown([None, None, None]) is None


# ---------------------------------------------------------------------------
# compute_drawdown_estimate
# ---------------------------------------------------------------------------


class TestComputeDrawdownEstimate:
    def test_from_horizon_returns(self) -> None:
        """Build from a dict of horizon → cumulative avg return."""
        horizon_returns = {"t1": 2.0, "t5": 5.0, "t10": -3.0, "t20": 1.0, "t30": 3.2}
        est = compute_drawdown_estimate(horizon_returns)
        assert est.max_drawdown == pytest.approx(-8.0, abs=1e-3)
        assert est.available is True
        assert est.t30_return == pytest.approx(3.2)

    def test_missing_horizons(self) -> None:
        """Only t5 + t30 (no mid) → still computable on 2 points."""
        est = compute_drawdown_estimate({"t5": 5.0, "t30": 3.2})
        # path [5, 3.2]: peak 5 → trough 3.2 = -1.8
        assert est.max_drawdown == pytest.approx(-1.8, abs=1e-3)

    def test_insufficient_none(self) -> None:
        """<2 valid horizons → available False."""
        est = compute_drawdown_estimate({"t1": 5.0})
        assert est.available is False
        assert est.max_drawdown is None

    def test_empty_dict(self) -> None:
        est = compute_drawdown_estimate({})
        assert est.available is False

    def test_no_drawdown_when_steady_climb(self) -> None:
        """All-positive monotonic → max_drawdown 0.0 (available)."""
        est = compute_drawdown_estimate({"t1": 1.0, "t5": 2.0, "t10": 3.0, "t30": 4.0})
        assert est.available is True
        assert est.max_drawdown == 0.0


# ---------------------------------------------------------------------------
# render_drawdown_line
# ---------------------------------------------------------------------------


class TestRenderDrawdownLine:
    def test_renders_drawdown(self) -> None:
        est = DrawdownEstimate(max_drawdown=-8.0, t30_return=3.2, available=True)
        out = render_drawdown_line(est)
        assert "回撤" in out
        assert "-8" in out
        assert "3.2" in out

    def test_unavailable_empty(self) -> None:
        est = DrawdownEstimate(max_drawdown=None, t30_return=None, available=False)
        assert render_drawdown_line(est) == ""

    def test_zero_drawdown_shows_ok(self) -> None:
        """0 drawdown (steady climb) → shown as 0%, no warning."""
        est = DrawdownEstimate(max_drawdown=0.0, t30_return=4.0, available=True)
        out = render_drawdown_line(est)
        assert "0" in out
        assert "⚠" not in out

    def test_deep_drawdown_warns(self) -> None:
        """Drawdown worse than -10% → ⚠ warning."""
        est = DrawdownEstimate(max_drawdown=-15.0, t30_return=3.2, available=True)
        out = render_drawdown_line(est)
        assert "⚠" in out
