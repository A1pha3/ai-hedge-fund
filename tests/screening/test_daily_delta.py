"""Tests for daily_delta.py — P6-2 推荐日间变动摘要."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.daily_delta import compute_daily_delta, render_daily_delta


def _make_report(date_str: str, recs: list[dict]) -> dict:
    """Helper: build a report dict with recommendations."""
    return {
        "trade_date": date_str,
        "recommendations": recs,
    }


def _make_rec(ticker: str, name: str, score_b: float) -> dict:
    return {"ticker": ticker, "name": name, "score_b": score_b}


class TestComputeDailyDelta:
    def test_empty_dir_returns_error(self, tmp_path: Path) -> None:
        result = compute_daily_delta(reports_dir=tmp_path / "nonexistent")
        assert result.get("error") is not None

    def test_single_report_returns_error(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        report = _make_report("20260610", [_make_rec("000001", "Test", 0.6)])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(report), encoding="utf-8")
        result = compute_daily_delta(reports_dir=reports_dir)
        assert result.get("error") is not None

    def test_two_reports_shows_added_and_removed(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [
            _make_rec("000001", "StockA", 0.7),
            _make_rec("000002", "StockB", 0.5),
        ])
        today = _make_report("20260611", [
            _make_rec("000001", "StockA", 0.75),
            _make_rec("000003", "StockC", 0.8),
        ])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir, top_n=20)
        assert result["today_date"] == "2026-06-11"
        assert result["yesterday_date"] == "2026-06-10"
        assert result["added_count"] == 1
        assert result["removed_count"] == 1
        assert result["added"][0]["ticker"] == "000003"
        assert result["removed"][0]["ticker"] == "000002"

    def test_score_change_detected(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [_make_rec("000001", "StockA", 0.5)])
        today = _make_report("20260611", [_make_rec("000001", "StockA", 0.8)])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir)
        assert result["changed_count"] == 1
        assert result["changed"][0]["score_b_delta"] == pytest.approx(0.3, abs=0.001)
        assert result["changed"][0]["rank_change"] == 0  # same rank in both

    def test_unchanged_when_scores_match(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        rec = _make_rec("000001", "StockA", 0.6)
        yesterday = _make_report("20260610", [rec])
        today = _make_report("20260611", [_make_rec("000001", "StockA", 0.6)])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir)
        assert result["changed_count"] == 0
        assert result["unchanged_count"] == 1
        assert result["added_count"] == 0
        assert result["removed_count"] == 0

    def test_top_n_limits_comparison(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday_recs = [_make_rec(f"00{i:04d}", f"S{i}", 0.9 - i * 0.05) for i in range(20)]
        today_recs = [_make_rec(f"00{i:04d}", f"S{i}", 0.9 - i * 0.05 + 0.01) for i in range(20)]
        yesterday = _make_report("20260610", yesterday_recs)
        today = _make_report("20260611", today_recs)
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir, top_n=5)
        assert result["today_total"] == 5
        assert result["yesterday_total"] == 5

    def test_rank_change_tracked(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [
            _make_rec("000001", "A", 0.9),
            _make_rec("000002", "B", 0.8),
            _make_rec("000003", "C", 0.7),
        ])
        today = _make_report("20260611", [
            _make_rec("000003", "C", 0.95),
            _make_rec("000001", "A", 0.85),
            _make_rec("000002", "B", 0.75),
        ])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir)
        changed_map = {c["ticker"]: c for c in result["changed"]}
        # C moved from rank 3 to rank 1 → rank_change = +2
        assert changed_map["000003"]["rank_change"] == 2
        # A moved from rank 1 to rank 2 → rank_change = -1
        assert changed_map["000001"]["rank_change"] == -1

    def test_invalid_json_skipped(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "auto_screening_20260609.json").write_text("not json", encoding="utf-8")
        yesterday = _make_report("20260610", [_make_rec("000001", "A", 0.5)])
        today = _make_report("20260611", [_make_rec("000001", "A", 0.6)])
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = compute_daily_delta(reports_dir=reports_dir)
        assert result["today_date"] == "2026-06-11"
        assert result["changed_count"] == 1


class TestRenderDailyDelta:
    def test_error_renders_as_warning(self) -> None:
        delta = {"error": "No reports found", "today_date": "", "yesterday_date": ""}
        output = render_daily_delta(delta)
        assert "⚠" in output
        assert "No reports found" in output

    def test_added_renders(self) -> None:
        delta = {
            "today_date": "2026-06-11",
            "yesterday_date": "2026-06-10",
            "added_count": 1,
            "removed_count": 0,
            "changed_count": 0,
            "unchanged_count": 0,
            "added": [{"ticker": "000001", "name": "TestStock", "score_b": 0.8, "rank": 1}],
            "removed": [],
            "changed": [],
        }
        output = render_daily_delta(delta)
        assert "新增" in output
        assert "TestStock" in output

    def test_removed_renders(self) -> None:
        delta = {
            "today_date": "2026-06-11",
            "yesterday_date": "2026-06-10",
            "added_count": 0,
            "removed_count": 1,
            "changed_count": 0,
            "unchanged_count": 0,
            "added": [],
            "removed": [{"ticker": "000002", "name": "OldStock", "score_b": 0.3, "rank": 5}],
            "changed": [],
        }
        output = render_daily_delta(delta)
        assert "移除" in output
        assert "OldStock" in output

    def test_changed_renders_with_arrows(self) -> None:
        delta = {
            "today_date": "2026-06-11",
            "yesterday_date": "2026-06-10",
            "added_count": 0,
            "removed_count": 0,
            "changed_count": 1,
            "unchanged_count": 0,
            "added": [],
            "removed": [],
            "changed": [{"ticker": "000001", "name": "StockA", "score_b_delta": 0.15, "rank_change": 2}],
        }
        output = render_daily_delta(delta)
        assert "StockA" in output
        assert "↑" in output


class TestEdgeCases:
    def test_none_score_b_no_delta(self) -> None:
        """When yesterday's score_b is None, no delta should be computed."""
        from src.screening.daily_delta import _compute_field_deltas
        result = _compute_field_deltas(
            {"ticker": "000001", "name": "A", "score_b": 0.5},
            {"ticker": "000001", "name": "A", "score_b": None},
        )
        assert result == {}

    def test_both_none_score_b_no_delta(self) -> None:
        """When both score_b are None, no delta should be computed."""
        from src.screening.daily_delta import _compute_field_deltas
        result = _compute_field_deltas(
            {"ticker": "000001", "name": "A", "score_b": None},
            {"ticker": "000001", "name": "A", "score_b": None},
        )
        assert result == {}
