"""Tests for src/screening/recommendation_stability.py — P-1 推荐稳定性度量."""

from __future__ import annotations

import json
from pathlib import Path

from src.screening.recommendation_stability import (
    RecommendationStabilityReport,
    _jaccard,
    _top_n_tickers,
    compute_recommendation_stability,
    render_stability_line,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _seed_report(dir_path: Path, date_str: str, tickers: list[str]) -> None:
    """Write one auto_screening_YYYYMMDD.json with the given Top-N tickers.

    Reports are sorted by score_b in production; here each ticker gets a
    descending score so recs[:top_n] yields the intended set.
    """
    recs = [{"ticker": t, "name": t, "score_b": round(0.9 - 0.1 * i, 2)} for i, t in enumerate(tickers)]
    payload = {"date": date_str, "recommendations": recs}
    (dir_path / f"auto_screening_{date_str}.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# _jaccard / _top_n_tickers
# ---------------------------------------------------------------------------


class TestJaccard:
    def test_identical(self) -> None:
        assert _jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0

    def test_disjoint(self) -> None:
        assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_two_of_three(self) -> None:
        # |∩|=2, |∪|=4 → 0.5
        assert _jaccard({"a", "b", "c"}, {"a", "b", "d"}) == 0.5

    def test_both_empty(self) -> None:
        assert _jaccard(set(), set()) == 1.0

    def test_one_empty(self) -> None:
        assert _jaccard({"a"}, set()) == 0.0


class TestTopNTickers:
    def test_extracts_first_n(self) -> None:
        payload = {"recommendations": [{"ticker": "000001"}, {"ticker": "000002"}, {"ticker": "000003"}, {"ticker": "000004"}]}
        assert _top_n_tickers(payload, 3) == {"000001", "000002", "000003"}

    def test_empty_recommendations(self) -> None:
        assert _top_n_tickers({}, 3) == set()
        assert _top_n_tickers({"recommendations": []}, 3) == set()

    def test_skips_missing_ticker(self) -> None:
        payload = {"recommendations": [{"ticker": "000001"}, {"name": "no-ticker"}, {"ticker": "000003"}]}
        assert _top_n_tickers(payload, 3) == {"000001", "000003"}


# ---------------------------------------------------------------------------
# compute_recommendation_stability
# ---------------------------------------------------------------------------


class TestComputeRecommendationStability:
    def test_all_same_top3_is_stable(self, tmp_path: Path) -> None:
        """5 days identical Top-3 → stability 1.0, label 稳定."""
        for d in ["20260101", "20260102", "20260103", "20260104", "20260105"]:
            _seed_report(tmp_path, d, ["000001", "000002", "000003"])
        report = compute_recommendation_stability(reports_dir=tmp_path, lookback_days=5, top_n=3)
        assert report.stability_score == 1.0
        assert report.label == "稳定"
        assert report.day_count == 5
        assert len(report.adjacent_overlaps) == 4  # 5 days → 4 adjacent pairs

    def test_all_different_is_volatile_churn(self, tmp_path: Path) -> None:
        """5 days, 0 overlap → stability 0.0, label 剧烈轮换."""
        days = [
            ("20260101", ["000001", "000002", "000003"]),
            ("20260102", ["000004", "000005", "000006"]),
            ("20260103", ["000007", "000008", "000009"]),
            ("20260104", ["000010", "000011", "000012"]),
            ("20260105", ["000013", "000014", "000015"]),
        ]
        for d, tickers in days:
            _seed_report(tmp_path, d, tickers)
        report = compute_recommendation_stability(reports_dir=tmp_path, lookback_days=5, top_n=3)
        assert report.stability_score == 0.0
        assert report.label == "剧烈轮换"

    def test_partial_overlap_two_of_three_is_volatile(self, tmp_path: Path) -> None:
        """Each adjacent pair shares 2 of 3 → Jaccard 0.5 → 波动."""
        # day1: A B C, day2: A B D (2/3 overlap), day3: A B E (2/3), ...
        for i, extra in enumerate(["C", "D", "E", "F", "G"]):
            d = f"2026010{i + 1}"
            _seed_report(tmp_path, d, ["000001", "000002", f"0000{extra}"])
        report = compute_recommendation_stability(reports_dir=tmp_path, lookback_days=5, top_n=3)
        # each pair: {001,002,X} vs {001,002,Y} → |∩|=2, |∪|=4 → 0.5
        assert report.stability_score == 0.5
        assert report.label == "波动"

    def test_fewer_than_two_reports_is_insufficient(self, tmp_path: Path) -> None:
        """0 or 1 report → cannot compute, stability None, label 数据不足."""
        report = compute_recommendation_stability(reports_dir=tmp_path, lookback_days=5, top_n=3)
        assert report.stability_score is None
        assert report.label == "数据不足"
        assert not report.available

        _seed_report(tmp_path, "20260101", ["000001", "000002", "000003"])
        report = compute_recommendation_stability(reports_dir=tmp_path, lookback_days=5, top_n=3)
        assert report.stability_score is None
        assert report.day_count == 1

    def test_empty_dir_is_insufficient(self, tmp_path: Path) -> None:
        report = compute_recommendation_stability(reports_dir=tmp_path)
        assert report.stability_score is None
        assert report.label == "数据不足"


# ---------------------------------------------------------------------------
# render_stability_line
# ---------------------------------------------------------------------------


class TestRenderStabilityLine:
    def test_insufficient_returns_empty(self) -> None:
        report = RecommendationStabilityReport(lookback_days=5, top_n=3, day_count=1, stability_score=None)
        assert render_stability_line(report) == ""

    def test_stable_render(self) -> None:
        report = RecommendationStabilityReport(lookback_days=5, top_n=3, day_count=5, stability_score=1.0, label="稳定")
        result = render_stability_line(report)
        assert "推荐稳定性" in result
        assert "100%" in result
        assert "稳定" in result
        assert "近 5 日" in result

    def test_volatile_render(self) -> None:
        report = RecommendationStabilityReport(lookback_days=5, top_n=3, day_count=5, stability_score=0.5, label="波动")
        result = render_stability_line(report)
        assert "50%" in result
        assert "波动" in result
