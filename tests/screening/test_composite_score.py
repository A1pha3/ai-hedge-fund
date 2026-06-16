"""Tests for src/screening/composite_score.py — P11-1 Composite Confidence Score."""

from __future__ import annotations

import pytest

from src.screening.composite_score import (
    _composite_grade,
    _fmt_adj,
    CompositeEntry,
    CompositeReport,
    compute_composite_scores_for_recommendations,
    render_composite_compact,
    render_composite_scores,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rec(
    ticker: str = "000001",
    name: str = "测试",
    score_b: float = 0.5,
) -> dict:
    return {"ticker": ticker, "name": name, "score_b": score_b}


# ---------------------------------------------------------------------------
# CompositeEntry / CompositeReport
# ---------------------------------------------------------------------------


class TestCompositeEntry:
    def test_default_values(self) -> None:
        entry = CompositeEntry(ticker="000001")
        assert entry.ticker == "000001"
        assert entry.base_score == 0.0
        assert entry.composite_score == 0.0
        assert entry.details == {}

    def test_all_fields_set(self) -> None:
        entry = CompositeEntry(
            ticker="600001",
            name="浦发",
            base_score=0.3,
            momentum_bonus=0.1,
            sector_bonus=0.05,
            consistency_adj=0.05,
            volume_factor=0.02,
            trend_resonance_factor=0.03,
            composite_score=0.55,
            details={"momentum_label": "bonus"},
        )
        assert entry.ticker == "600001"
        assert entry.composite_score == 0.55


class TestCompositeReport:
    def test_empty_report(self) -> None:
        report = CompositeReport()
        assert report.trade_date == ""
        assert report.items == []

    def test_to_dict(self) -> None:
        report = CompositeReport(
            trade_date="2026-01-01",
            items=[
                CompositeEntry(
                    ticker="000001",
                    name="平安",
                    base_score=0.4,
                    momentum_bonus=0.1,
                    sector_bonus=0.05,
                    consistency_adj=0.0,
                    volume_factor=0.02,
                    trend_resonance_factor=0.01,
                    composite_score=0.58,
                ),
            ],
        )
        d = report.to_dict()
        assert d["trade_date"] == "2026-01-01"
        assert len(d["items"]) == 1
        item = d["items"][0]
        assert item["ticker"] == "000001"
        assert item["composite_score"] == 0.58
        # Rounded values
        assert item["base_score"] == 0.4
        assert item["momentum_bonus"] == 0.1


# ---------------------------------------------------------------------------
# _composite_grade
# ---------------------------------------------------------------------------


class TestCompositeGrade:
    def test_a_grade(self) -> None:
        assert "A" in _composite_grade(0.8)
        assert "A" in _composite_grade(0.7)

    def test_b_grade(self) -> None:
        assert "B" in _composite_grade(0.6)
        assert "B" in _composite_grade(0.5)

    def test_c_grade(self) -> None:
        assert "C" in _composite_grade(0.4)
        assert "C" in _composite_grade(0.3)

    def test_d_grade(self) -> None:
        assert "D" in _composite_grade(0.2)
        assert "D" in _composite_grade(0.1)

    def test_f_grade(self) -> None:
        assert "F" in _composite_grade(0.0)
        assert "F" in _composite_grade(-0.5)

    def test_boundary_exactly_0_7(self) -> None:
        # >= 0.7 → A
        assert "A" in _composite_grade(0.7)

    def test_boundary_exactly_0_5(self) -> None:
        # >= 0.5 → B
        assert "B" in _composite_grade(0.5)


# ---------------------------------------------------------------------------
# _fmt_adj
# ---------------------------------------------------------------------------


class TestFmtAdj:
    def test_positive(self) -> None:
        result = _fmt_adj(0.05)
        assert "+" in result
        assert "0.05" in result

    def test_negative(self) -> None:
        result = _fmt_adj(-0.10)
        assert "0.10" in result

    def test_zero(self) -> None:
        result = _fmt_adj(0.0)
        assert "0.00" in result


# ---------------------------------------------------------------------------
# compute_composite_scores_for_recommendations (pure logic)
# ---------------------------------------------------------------------------


class TestComputeCompositeScoresForRecommendations:
    def test_empty_recommendations(self) -> None:
        report = compute_composite_scores_for_recommendations(
            recommendations=[], trade_date="2026-01-01"
        )
        assert report.trade_date == "2026-01-01"
        assert report.items == []

    def test_single_recommendation_with_consistency(self) -> None:
        """With no external deps, composite = base + consistency_adj (defaults to -0.05 for unknown)."""
        report = compute_composite_scores_for_recommendations(
            recommendations=[_make_rec(score_b=0.5)],
            trade_date="2026-01-01",
        )
        assert len(report.items) == 1
        item = report.items[0]
        assert item.ticker == "000001"
        assert item.base_score == 0.5
        # check_signal_consistency runs on raw recs → unknown → -0.05
        assert item.consistency_adj == -0.05
        assert item.composite_score == pytest.approx(0.45)

    def test_multiple_recommendations_sorted_desc(self) -> None:
        """Items sorted by composite_score descending."""
        report = compute_composite_scores_for_recommendations(
            recommendations=[
                _make_rec(ticker="000001", score_b=0.3),
                _make_rec(ticker="000002", score_b=0.8),
                _make_rec(ticker="000003", score_b=0.5),
            ],
            trade_date="2026-01-01",
        )
        assert len(report.items) == 3
        assert report.items[0].ticker == "000002"
        assert report.items[1].ticker == "000003"
        assert report.items[2].ticker == "000001"

    def test_composite_clamped_at_upper_bound(self) -> None:
        """composite_score is clamped to [-1.0, +1.0]."""
        report = compute_composite_scores_for_recommendations(
            recommendations=[_make_rec(score_b=5.0)],
            trade_date="2026-01-01",
        )
        assert report.items[0].composite_score <= 1.0

    def test_ties_broken_deterministically_by_base_score_then_ticker(self) -> None:
        """BH-011: equal composite scores must break ties deterministically
        (base_score desc, then ticker asc), not rely on JSON-dict input order.
        Two runs with the SAME data but DIFFERENT input order must yield the
        SAME ranking — otherwise Top-N membership flips nondeterministically.
        """
        # All three share the same score_b → same composite (no bonuses/penalties
        # in this path), so the tie-break decides order. ticker asc is the weakest
        # key: 000001 < 000002 < 000003.
        base_recs = [
            _make_rec(ticker="000002", score_b=0.5),
            _make_rec(ticker="000001", score_b=0.5),
            _make_rec(ticker="000003", score_b=0.5),
        ]
        report_a = compute_composite_scores_for_recommendations(
            recommendations=list(base_recs), trade_date="2026-01-01",
        )
        # Reverse input order — result must be identical (deterministic).
        report_b = compute_composite_scores_for_recommendations(
            recommendations=list(reversed(base_recs)), trade_date="2026-01-01",
        )
        order_a = [it.ticker for it in report_a.items]
        order_b = [it.ticker for it in report_b.items]
        assert order_a == order_b, f"Nondeterministic tie-break: {order_a} vs {order_b}"
        # ticker ascending within the tied group.
        assert order_a == ["000001", "000002", "000003"]

    def test_composite_clamped_at_lower_bound(self) -> None:
        """composite_score is clamped to [-1.0, +1.0]."""
        report = compute_composite_scores_for_recommendations(
            recommendations=[_make_rec(score_b=-5.0)],
            trade_date="2026-01-01",
        )
        assert report.items[0].composite_score >= -1.0

    def test_zero_score_b(self) -> None:
        """score_b=0 should produce composite = 0 + consistency_adj."""
        report = compute_composite_scores_for_recommendations(
            recommendations=[_make_rec(score_b=0.0)],
            trade_date="2026-01-01",
        )
        assert report.items[0].base_score == 0.0
        # consistency_adj for unknown signal = -0.05
        assert report.items[0].composite_score == pytest.approx(-0.05)

    def test_details_populated_with_defaults(self) -> None:
        """Details dict is populated with label strings."""
        report = compute_composite_scores_for_recommendations(
            recommendations=[_make_rec(score_b=0.5)],
            trade_date="2026-01-01",
        )
        details = report.items[0].details
        assert "momentum_label" in details
        assert "sector_label" in details
        assert "consistency_level" in details
        assert "volume_confirmation" in details
        assert "trend_resonance" in details

    def test_none_score_b_treated_as_zero(self) -> None:
        """score_b=None should be treated as 0.0."""
        report = compute_composite_scores_for_recommendations(
            recommendations=[{"ticker": "000001", "name": "测试", "score_b": None}],
            trade_date="2026-01-01",
        )
        assert report.items[0].base_score == 0.0
        assert report.items[0].composite_score == pytest.approx(-0.05)

    def test_missing_name_defaults_empty(self) -> None:
        """Missing name field defaults to empty string."""
        report = compute_composite_scores_for_recommendations(
            recommendations=[{"ticker": "000001", "score_b": 0.3}],
            trade_date="2026-01-01",
        )
        assert report.items[0].name == ""

    def test_nan_score_b_does_not_bubble_to_top(self) -> None:
        """BH-012: score_b=NaN must NOT corrupt ranking.

        ``float(nan or 0.0)`` stays NaN (NaN is truthy in Python), and
        ``max(-1.0, min(1.0, nan))`` returns ``1.0`` on CPython — so a corrupt
        ticker would silently get the HIGHEST composite and bubble to the top of
        the front-door recommendation list, displacing legitimate picks.

        A NaN/corrupt score must be coerced to 0.0 (treated as missing data),
        never collapse to the max-composite of 1.0.
        """
        nan = float("nan")
        report = compute_composite_scores_for_recommendations(
            recommendations=[
                _make_rec(ticker="GOOD", score_b=0.8),
                {"ticker": "CORRUPT", "name": "坏数据", "score_b": nan},
            ],
            trade_date="2026-01-01",
        )
        # CORRUPT must NOT be ranked above GOOD — its NaN must become 0.0,
        # yielding composite ≈ 0.0 + consistency_adj(-0.05), far below GOOD's 0.8.
        assert report.items[0].ticker == "GOOD"
        corrupt = next(it for it in report.items if it.ticker == "CORRUPT")
        assert corrupt.composite_score < 0.5
        assert corrupt.composite_score == pytest.approx(-0.05)

    def test_inf_score_b_does_not_corrupt_ranking(self) -> None:
        """BH-012: Inf must also be rejected (coerced to 0.0), not clamped."""
        report = compute_composite_scores_for_recommendations(
            recommendations=[
                {"ticker": "CORRUPT", "name": "Inf", "score_b": float("inf")},
                _make_rec(ticker="GOOD", score_b=0.7),
            ],
            trade_date="2026-01-01",
        )
        assert report.items[0].ticker == "GOOD"
        corrupt = next(it for it in report.items if it.ticker == "CORRUPT")
        assert corrupt.composite_score < 0.5


# ---------------------------------------------------------------------------
# render_composite_scores
# ---------------------------------------------------------------------------


class TestRenderCompositeScores:
    def test_empty_report(self) -> None:
        result = render_composite_scores(CompositeReport())
        assert "无推荐数据" in result

    def test_with_items(self) -> None:
        report = CompositeReport(
            trade_date="2026-01-01",
            items=[
                CompositeEntry(
                    ticker="000001",
                    name="平安银行",
                    base_score=0.6,
                    composite_score=0.6,
                ),
            ],
        )
        result = render_composite_scores(report)
        assert "000001" in result
        assert "综合信心评分" in result

    def test_grade_summary(self) -> None:
        report = CompositeReport(
            trade_date="2026-01-01",
            items=[
                CompositeEntry(ticker="A", composite_score=0.8),
                CompositeEntry(ticker="B", composite_score=0.6),
                CompositeEntry(ticker="C", composite_score=0.2),
            ],
        )
        result = render_composite_scores(report)
        assert "A级" in result
        assert "B级" in result
        assert "低信心" in result


class TestRenderCompositeCompact:
    def test_empty_report(self) -> None:
        result = render_composite_compact(CompositeReport())
        assert "无综合评分数据" in result

    def test_shows_top_5(self) -> None:
        items = [
            CompositeEntry(ticker=f"T{i:03d}", name=f"N{i}", composite_score=0.5 - i * 0.05)
            for i in range(8)
        ]
        report = CompositeReport(trade_date="2026-01-01", items=items)
        result = render_composite_compact(report)
        assert "Top 5" in result
        # First 5 should appear
        assert "T000" in result
        assert "T004" in result


# ---------------------------------------------------------------------------
# compute_composite_scores (end-to-end, with no report file → empty)
# ---------------------------------------------------------------------------


class TestComputeCompositeScores:
    def test_no_report_returns_empty(self, tmp_path) -> None:
        """When reports_dir has no report files, returns empty report."""
        from src.screening.composite_score import compute_composite_scores

        report = compute_composite_scores(reports_dir=tmp_path)
        assert report.items == []
