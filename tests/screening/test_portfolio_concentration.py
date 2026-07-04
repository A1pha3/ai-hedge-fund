"""Tests for src/screening/portfolio_concentration.py — P-4 组合级行业集中度."""

from __future__ import annotations

from src.screening.portfolio_concentration import (
    compute_industry_concentration,
    IndustryConcentrationReport,
    render_concentration_line,
)

# ---------------------------------------------------------------------------
# compute_industry_concentration
# ---------------------------------------------------------------------------


class TestComputeConcentration:
    def test_concentrated_over_threshold(self) -> None:
        """4 of 5 picks in same industry → 80% → over 30% threshold."""
        picks = [
            {"ticker": "000001", "industry_sw": "电子"},
            {"ticker": "000002", "industry_sw": "电子"},
            {"ticker": "000003", "industry_sw": "电子"},
            {"ticker": "000004", "industry_sw": "电子"},
            {"ticker": "000005", "industry_sw": "银行"},
        ]
        report = compute_industry_concentration(picks, threshold=0.3)
        assert report.top_industry == "电子"
        assert report.top_share == 0.8
        assert report.over_threshold is True
        assert report.pick_count == 5

    def test_diversified_under_threshold(self) -> None:
        """5 picks across 5 industries → 20% each → under threshold."""
        picks = [
            {"ticker": "000001", "industry_sw": "电子"},
            {"ticker": "000002", "industry_sw": "银行"},
            {"ticker": "000003", "industry_sw": "医药"},
            {"ticker": "000004", "industry_sw": "消费"},
            {"ticker": "000005", "industry_sw": "化工"},
        ]
        report = compute_industry_concentration(picks, threshold=0.3)
        assert report.top_share == 0.2
        assert report.over_threshold is False

    def test_filters_unknown_industry(self) -> None:
        """未知/空 industry_sw excluded from concentration denominator."""
        picks = [
            {"ticker": "000001", "industry_sw": "电子"},
            {"ticker": "000002", "industry_sw": "电子"},
            {"ticker": "000003", "industry_sw": "未知"},
            {"ticker": "000004", "industry_sw": ""},
        ]
        report = compute_industry_concentration(picks, threshold=0.3)
        # only 2 valid picks, both 电子 → 100% concentration
        assert report.pick_count == 2
        assert report.top_industry == "电子"
        assert report.top_share == 1.0
        assert report.over_threshold is True

    def test_empty_picks(self) -> None:
        report = compute_industry_concentration([], threshold=0.3)
        assert report.top_industry == ""
        assert report.top_share == 0.0
        assert report.over_threshold is False
        assert report.pick_count == 0

    def test_all_unknown_industry(self) -> None:
        """All picks unknown → no concentration computable, not over threshold."""
        picks = [
            {"ticker": "000001", "industry_sw": "未知"},
            {"ticker": "000002", "industry_sw": ""},
        ]
        report = compute_industry_concentration(picks, threshold=0.3)
        assert report.pick_count == 0
        assert report.over_threshold is False

    def test_tie_picks_deterministic(self) -> None:
        """Two industries tied → deterministic (highest share, stable order)."""
        picks = [
            {"ticker": "000001", "industry_sw": "电子"},
            {"ticker": "000002", "industry_sw": "银行"},
        ]
        report = compute_industry_concentration(picks, threshold=0.3)
        assert report.top_share == 0.5
        # tied 50/50; top_industry is one of them (deterministic within a run)
        assert report.top_industry in {"电子", "银行"}

    def test_threshold_boundary(self) -> None:
        """Exactly at threshold (3 of 10 = 0.3) → over_threshold True (>= threshold)."""
        picks = [{"ticker": f"{i:06d}", "industry_sw": "电子"} for i in range(3)]
        picks += [{"ticker": f"{i:06d}", "industry_sw": f"其他{i}"} for i in range(3, 10)]
        report = compute_industry_concentration(picks, threshold=0.3)
        assert report.top_share == 0.3
        assert report.over_threshold is True  # >= threshold


# ---------------------------------------------------------------------------
# render_concentration_line
# ---------------------------------------------------------------------------


class TestRenderConcentrationLine:
    def test_over_threshold_shows_warning(self) -> None:
        report = IndustryConcentrationReport(top_industry="电子", top_share=0.45, pick_count=5, over_threshold=True, threshold=0.3)
        result = render_concentration_line(report)
        assert "电子" in result
        assert "45%" in result
        assert "⚠" in result  # warning marker

    def test_under_threshold_shows_ok(self) -> None:
        report = IndustryConcentrationReport(top_industry="电子", top_share=0.2, pick_count=5, over_threshold=False, threshold=0.3)
        result = render_concentration_line(report)
        assert "20%" in result
        assert "⚠" not in result

    def test_empty_picks_returns_empty(self) -> None:
        report = IndustryConcentrationReport(pick_count=0)
        assert render_concentration_line(report) == ""
