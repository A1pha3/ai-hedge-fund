"""Tests for outlier_detect.py -- P8-2."""

from __future__ import annotations

import json
from pathlib import Path

from src.screening.outlier_detect import detect_outliers, render_outliers


def _make_report(date_str: str, recs: list[dict]) -> dict:
    return {"trade_date": date_str, "recommendations": recs}


def _make_rec(ticker: str, name: str, score_b: float) -> dict:
    return {"ticker": ticker, "name": name, "score_b": score_b}


class TestDetectOutliers:
    def test_no_reports(self, tmp_path: Path) -> None:
        result = detect_outliers(reports_dir=tmp_path)
        assert result.get("error") is not None

    def test_single_report(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "auto_screening_20260611.json").write_text(
            json.dumps(_make_report("20260611", [])), encoding="utf-8"
        )
        result = detect_outliers(reports_dir=reports_dir)
        assert result.get("error") is not None

    def test_no_outliers(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [_make_rec("000001", "A", 0.50)])
        today = _make_report("20260611", [_make_rec("000001", "A", 0.55)])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = detect_outliers(threshold=0.30, reports_dir=reports_dir)
        assert result["outlier_count"] == 0
        assert result["outliers"] == []

    def test_detects_surge(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [
            _make_rec("000001", "A", 0.20),
            _make_rec("000002", "B", 0.50),
        ])
        today = _make_report("20260611", [
            _make_rec("000001", "A", 0.60),  # +0.40 surge
            _make_rec("000002", "B", 0.55),  # +0.05 normal
        ])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = detect_outliers(threshold=0.30, reports_dir=reports_dir)
        assert result["outlier_count"] == 1
        assert result["outliers"][0]["ticker"] == "000001"
        assert result["outliers"][0]["direction"] == "surge"
        assert result["outliers"][0]["delta"] == 0.40

    def test_detects_drop(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [_make_rec("000001", "A", 0.80)])
        today = _make_report("20260611", [_make_rec("000001", "A", 0.30)])  # -0.50 drop
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = detect_outliers(threshold=0.30, reports_dir=reports_dir)
        assert result["outlier_count"] == 1
        assert result["outliers"][0]["direction"] == "drop"
        assert result["outliers"][0]["delta"] == -0.50

    def test_new_entry_not_outlier(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [])
        today = _make_report("20260611", [_make_rec("000001", "A", 0.90)])  # New entry
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = detect_outliers(reports_dir=reports_dir)
        assert result["outlier_count"] == 0

    def test_sorted_by_abs_delta(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [
            _make_rec("000001", "A", 0.20),
            _make_rec("000002", "B", 0.80),
        ])
        today = _make_report("20260611", [
            _make_rec("000001", "A", 0.60),  # +0.40
            _make_rec("000002", "B", 0.20),  # -0.60
        ])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = detect_outliers(threshold=0.30, reports_dir=reports_dir)
        assert result["outlier_count"] == 2
        assert result["outliers"][0]["ticker"] == "000002"  # |0.60| > |0.40|

    def test_custom_threshold(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [_make_rec("000001", "A", 0.50)])
        today = _make_report("20260611", [_make_rec("000001", "A", 0.70)])  # +0.20
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        # With default threshold 0.30, not an outlier
        result_default = detect_outliers(threshold=0.30, reports_dir=reports_dir)
        assert result_default["outlier_count"] == 0

        # With threshold 0.15, is an outlier
        result_low = detect_outliers(threshold=0.15, reports_dir=reports_dir)
        assert result_low["outlier_count"] == 1


class TestRenderOutliers:
    def test_error_renders(self) -> None:
        result = {"error": "Need at least 2 days"}
        output = render_outliers(result)
        assert "Need at least 2" in output

    def test_no_outliers_renders(self) -> None:
        result = {"outliers": [], "total_compared": 5, "threshold": 0.3,
                  "today_date": "2026-06-11", "yesterday_date": "2026-06-10"}
        output = render_outliers(result)
        assert "No significant outliers" in output

    def test_outliers_renders(self) -> None:
        result = {
            "outliers": [{"ticker": "000001", "name": "Test", "today_score": 0.8,
                          "yesterday_score": 0.4, "delta": 0.4, "abs_delta": 0.4,
                          "direction": "surge", "today_rank": 1}],
            "outlier_count": 1, "total_compared": 5, "threshold": 0.3,
            "today_date": "2026-06-11", "yesterday_date": "2026-06-10",
        }
        output = render_outliers(result)
        assert "1 outlier" in output
        assert "Test" in output
