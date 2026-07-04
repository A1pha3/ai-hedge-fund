"""Tests for src/screening/correlation_discount.py — Q-4 相关性仓位折减."""

from __future__ import annotations

import pytest

from src.screening.correlation_discount import (
    _correlation_proxy,
    compute_correlation_discount,
    CorrelationDiscountReport,
    render_correlation_note,
)

# ---------------------------------------------------------------------------
# _correlation_proxy
# ---------------------------------------------------------------------------


class TestCorrelationProxy:
    def test_same_industry_high(self) -> None:
        """Two picks same industry + close score → high correlation (≥0.9)."""
        corr = _correlation_proxy(
            {"industry_sw": "电子", "score_b": 0.75},
            {"industry_sw": "电子", "score_b": 0.73},
        )
        # industry 0.6 + proximity (Δ=0.02) ≈ 0.373 → 0.973 (high, not capped unless identical)
        assert corr >= 0.9

    def test_different_industry_low(self) -> None:
        """Different industry + far score → low correlation."""
        corr = _correlation_proxy(
            {"industry_sw": "电子", "score_b": 0.85},
            {"industry_sw": "银行", "score_b": 0.50},
        )
        assert corr < 0.5

    def test_different_industry_close_score_moderate(self) -> None:
        """Different industry but very close score → some correlation (score proximity)."""
        corr = _correlation_proxy(
            {"industry_sw": "电子", "score_b": 0.75},
            {"industry_sw": "银行", "score_b": 0.74},
        )
        # industry differs (0) but score proximity contributes
        assert 0.0 < corr < 0.5

    def test_same_industry_far_score_still_moderate(self) -> None:
        """Same industry but far score → industry overlap dominates."""
        corr = _correlation_proxy(
            {"industry_sw": "电子", "score_b": 0.85},
            {"industry_sw": "电子", "score_b": 0.50},
        )
        # same industry contributes the industry weight even if score far apart
        assert corr >= 0.4

    def test_missing_industry(self) -> None:
        """Missing/unknown industry on either → no industry contribution."""
        corr = _correlation_proxy(
            {"industry_sw": "", "score_b": 0.75},
            {"industry_sw": "电子", "score_b": 0.73},
        )
        # only score proximity contributes (industry unknown)
        assert corr < 0.5

    def test_capped_at_one(self) -> None:
        """Proxy never exceeds 1.0."""
        corr = _correlation_proxy(
            {"industry_sw": "电子", "score_b": 0.75},
            {"industry_sw": "电子", "score_b": 0.75},
        )
        assert corr <= 1.0


# ---------------------------------------------------------------------------
# compute_correlation_discount
# ---------------------------------------------------------------------------


class TestComputeCorrelationDiscount:
    def test_single_pick_no_discount(self) -> None:
        """1 pick → no overlap possible → no discount."""
        report = compute_correlation_discount([{"ticker": "000001", "industry_sw": "电子", "score_b": 0.75}])
        assert len(report.per_pick_discount) == 1
        assert report.per_pick_discount["000001"] == pytest.approx(1.0)  # no discount
        assert report.max_pair_correlation is None

    def test_two_uncorrelated_no_discount(self) -> None:
        """Two picks different industry + far score → ~no discount."""
        picks = [
            {"ticker": "000001", "industry_sw": "电子", "score_b": 0.85},
            {"ticker": "000002", "industry_sw": "银行", "score_b": 0.50},
        ]
        report = compute_correlation_discount(picks)
        # low correlation → discount factor near 1.0
        assert all(d > 0.9 for d in report.per_pick_discount.values())

    def test_two_correlated_discount(self) -> None:
        """Two picks same industry + close score → both discounted below 1.0."""
        picks = [
            {"ticker": "000001", "industry_sw": "电子", "score_b": 0.75},
            {"ticker": "000002", "industry_sw": "电子", "score_b": 0.73},
        ]
        report = compute_correlation_discount(picks)
        assert report.max_pair_correlation is not None
        assert report.max_pair_correlation > 0.7
        assert all(d < 1.0 for d in report.per_pick_discount.values())
        assert report.overlap_warning is True

    def test_empty_picks(self) -> None:
        report = compute_correlation_discount([])
        assert report.per_pick_discount == {}
        assert report.max_pair_correlation is None

    def test_three_picks_one_outlier(self) -> None:
        """A + B correlated (same industry), C independent → A,B discounted, C not."""
        picks = [
            {"ticker": "A", "industry_sw": "电子", "score_b": 0.75},
            {"ticker": "B", "industry_sw": "电子", "score_b": 0.74},
            {"ticker": "C", "industry_sw": "银行", "score_b": 0.50},
        ]
        report = compute_correlation_discount(picks)
        assert report.per_pick_discount["A"] < 1.0
        assert report.per_pick_discount["B"] < 1.0
        # C is independent (different industry, far score) → near 1.0
        assert report.per_pick_discount["C"] > 0.9

    def test_discount_bounded(self) -> None:
        """Discount factor always in (0, 1]."""
        picks = [
            {"ticker": "A", "industry_sw": "电子", "score_b": 0.75},
            {"ticker": "B", "industry_sw": "电子", "score_b": 0.75},
            {"ticker": "C", "industry_sw": "电子", "score_b": 0.75},
        ]
        report = compute_correlation_discount(picks)
        for d in report.per_pick_discount.values():
            assert 0.0 < d <= 1.0


# ---------------------------------------------------------------------------
# render_correlation_note
# ---------------------------------------------------------------------------


class TestRenderCorrelationNote:
    def test_overlap_warning(self) -> None:
        report = CorrelationDiscountReport(
            per_pick_discount={"A": 0.7, "B": 0.7},
            max_pair_correlation=0.9,
            overlap_warning=True,
            correlated_pairs=[("A", "B", 0.9)],
        )
        out = render_correlation_note(report)
        assert "相关" in out
        assert "⚠" in out
        assert "A" in out and "B" in out

    def test_no_overlap(self) -> None:
        report = CorrelationDiscountReport(
            per_pick_discount={"A": 1.0, "B": 0.95},
            max_pair_correlation=0.2,
            overlap_warning=False,
            correlated_pairs=[],
        )
        out = render_correlation_note(report)
        # no warning; may show "分散" or be brief
        assert "⚠" not in out

    def test_empty(self) -> None:
        report = CorrelationDiscountReport()
        assert render_correlation_note(report) == ""
