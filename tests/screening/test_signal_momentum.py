"""Tests for src/screening/signal_momentum.py — P10-1 Signal Momentum."""

from __future__ import annotations

import pytest

from src.screening.signal_momentum import (
    MomentumInfo,
    MomentumReport,
    _classify_momentum,
    _simple_slope,
    render_signal_momentum,
)


# ---------------------------------------------------------------------------
# _simple_slope
# ---------------------------------------------------------------------------


class TestSimpleSlope:
    def test_empty_returns_zero(self) -> None:
        assert _simple_slope([]) == 0.0

    def test_single_value_returns_zero(self) -> None:
        assert _simple_slope([5.0]) == 0.0

    def test_two_values_ascending(self) -> None:
        # (0,0) → (1,1): slope = 1.0
        assert _simple_slope([0.0, 1.0]) == pytest.approx(1.0)

    def test_two_values_descending(self) -> None:
        # (0,1) → (1,0): slope = -1.0
        assert _simple_slope([1.0, 0.0]) == pytest.approx(-1.0)

    def test_flat_values_zero_slope(self) -> None:
        assert _simple_slope([0.5, 0.5, 0.5, 0.5]) == pytest.approx(0.0)

    def test_linear_ascending(self) -> None:
        # y = 0.1 * x → slope = 0.1
        values = [0.0, 0.1, 0.2, 0.3, 0.4]
        assert _simple_slope(values) == pytest.approx(0.1)

    def test_linear_descending(self) -> None:
        values = [0.4, 0.3, 0.2, 0.1, 0.0]
        assert _simple_slope(values) == pytest.approx(-0.1)

    def test_constant_values_zero_denominator(self) -> None:
        # All same value → denominator > 0, but numerator = 0
        assert _simple_slope([3.0, 3.0, 3.0]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _classify_momentum
# ---------------------------------------------------------------------------


class TestClassifyMomentum:
    def test_strong_improving(self) -> None:
        label, bonus = _classify_momentum(0.05)
        assert label == "strong_improving"
        assert bonus == 0.10

    def test_improving(self) -> None:
        label, bonus = _classify_momentum(0.01)
        assert label == "improving"
        assert bonus == 0.05

    def test_stable_zero(self) -> None:
        label, bonus = _classify_momentum(0.0)
        assert label == "stable"
        assert bonus == 0.0

    def test_stable_near_zero(self) -> None:
        label, bonus = _classify_momentum(0.003)
        assert label == "stable"
        assert bonus == 0.0

    def test_declining(self) -> None:
        label, bonus = _classify_momentum(-0.01)
        assert label == "declining"
        assert bonus == -0.05

    def test_strong_declining(self) -> None:
        label, bonus = _classify_momentum(-0.05)
        assert label == "strong_declining"
        assert bonus == -0.10

    def test_boundary_strong(self) -> None:
        """Exactly 0.02 should be strong_improving (>=)."""
        label, bonus = _classify_momentum(0.02)
        assert label == "strong_improving"

    def test_boundary_weak(self) -> None:
        """Exactly 0.005 should be improving (>=)."""
        label, bonus = _classify_momentum(0.005)
        assert label == "improving"


# ---------------------------------------------------------------------------
# MomentumInfo / MomentumReport
# ---------------------------------------------------------------------------


class TestMomentumInfo:
    def test_defaults(self) -> None:
        info = MomentumInfo(ticker="000001")
        assert info.ticker == "000001"
        assert info.momentum_label == "stable"
        assert info.momentum_bonus == 0.0
        assert info.days_observed == 0


class TestMomentumReport:
    def test_empty(self) -> None:
        report = MomentumReport()
        assert report.items == []

    def test_to_dict(self) -> None:
        report = MomentumReport(
            trade_date="2026-01-01",
            lookback_days=5,
            items=[
                MomentumInfo(
                    ticker="000001",
                    name="平安",
                    score_current=0.6,
                    slope=0.03,
                    momentum_label="strong_improving",
                    momentum_bonus=0.10,
                    days_observed=5,
                ),
            ],
        )
        d = report.to_dict()
        assert d["trade_date"] == "2026-01-01"
        assert d["lookback_days"] == 5
        assert len(d["items"]) == 1
        assert d["items"][0]["ticker"] == "000001"
        assert d["items"][0]["slope"] == pytest.approx(0.03)
        assert d["items"][0]["momentum_bonus"] == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# render_signal_momentum
# ---------------------------------------------------------------------------


class TestRenderSignalMomentum:
    def test_empty(self) -> None:
        result = render_signal_momentum(MomentumReport())
        assert "无推荐数据" in result

    def test_with_items(self) -> None:
        report = MomentumReport(
            trade_date="2026-01-01",
            items=[
                MomentumInfo(ticker="000001", name="平安", score_current=0.5, momentum_bonus=0.05),
            ],
        )
        result = render_signal_momentum(report)
        assert "000001" in result
        assert "信号动量" in result


# ---------------------------------------------------------------------------
# compute_signal_momentum (end-to-end, no report files → empty)
# ---------------------------------------------------------------------------


class TestComputeSignalMomentum:
    def test_no_reports_returns_empty(self, tmp_path) -> None:
        from src.screening.signal_momentum import compute_signal_momentum

        report = compute_signal_momentum(reports_dir=tmp_path)
        assert report.items == []
