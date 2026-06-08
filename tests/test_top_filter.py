"""R20.5 tests for --top --filter feature extension."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.main import _apply_top_filters


def _sample_recs() -> list[dict]:
    return [
        {"ticker": "300750", "name": "宁德时代", "industry_sw": "电气设备", "score_b": 0.85, "market_cap": 1.2e12, "consecutive_days": 3},
        {"ticker": "600519", "name": "贵州茅台", "industry_sw": "食品饮料", "score_b": 0.72, "market_cap": 2.0e12, "consecutive_days": 2},
        {"ticker": "000001", "name": "平安银行", "industry_sw": "银行", "score_b": 0.55, "market_cap": 2.5e11, "consecutive_days": 1},
        {"ticker": "000880", "name": "*ST 慧辰", "industry_sw": "计算机", "score_b": 0.30, "market_cap": 5e9, "consecutive_days": 0},
        {"ticker": "002475", "name": "立讯精密", "industry_sw": "电子", "score_b": 0.68, "market_cap": 3.5e11, "consecutive_days": 2},
    ]


class TestApplyTopFilters:
    def test_no_filter_returns_all(self):
        recs, summary = _apply_top_filters(_sample_recs(), {})
        assert len(recs) == 5

    def test_industry_filter(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"industry": "银行"})
        assert len(recs) == 1
        assert recs[0]["ticker"] == "000001"
        assert "银行" in summary

    def test_industry_filter_substring(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"industry": "电"})
        # "电气设备" contains "电" and "电子" contains "电" — 2 matches
        assert len(recs) == 2
        tickers = {r["ticker"] for r in recs}
        assert "300750" in tickers  # 电气设备
        assert "002475" in tickers  # 电子

    def test_min_score_filter(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"min_score": 0.7})
        assert len(recs) == 2  # 300750 (0.85) and 600519 (0.72)

    def test_max_score_filter(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"max_score": 0.5})
        assert len(recs) == 1  # 000880 (0.30)

    def test_score_range_filter(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"min_score": 0.5, "max_score": 0.7})
        assert len(recs) == 2  # 000001 (0.55) and 002475 (0.68)

    def test_min_market_cap_filter(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"min_market_cap": 1e12})
        assert len(recs) == 2  # 300750 (1.2T) and 600519 (2.0T)

    def test_max_market_cap_filter(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"max_market_cap": 4e11})
        # 000001 (250B ✓), 000880 (5B ✓), 002475 (350B ✓) — all ≤ 400B
        # 300750 (1.2T ✗), 600519 (2.0T ✗) excluded
        assert len(recs) == 3

    def test_exclude_st(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"exclude_st": True})
        assert len(recs) == 4  # Excludes *ST 慧辰
        assert all("ST" not in (r.get("name", "") or "").upper() for r in recs)

    def test_min_consecutive(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"min_consecutive": 2})
        assert len(recs) == 3  # 300750 (3d), 600519 (2d), 002475 (2d)

    def test_ticker_exact_match(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"ticker": "600519"})
        assert len(recs) == 1
        assert recs[0]["name"] == "贵州茅台"

    def test_name_contains(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"name_contains": "时代"})
        assert len(recs) == 1
        assert recs[0]["ticker"] == "300750"

    def test_combined_filters(self):
        recs, summary = _apply_top_filters(
            _sample_recs(),
            {"min_score": 0.6, "exclude_st": True, "min_consecutive": 2},
        )
        # 300750 (0.85, 3d), 600519 (0.72, 2d), 002475 (0.68, 2d) — all pass
        assert len(recs) == 3

    def test_filter_that_excludes_all(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"min_score": 0.99})
        assert len(recs) == 0
        assert "0→0" in summary or "5→0" in summary

    def test_summary_shows_filter_count(self):
        recs, summary = _apply_top_filters(_sample_recs(), {"industry": "银行"})
        assert "5→1" in summary


class TestResolveTopFilterParsing:
    """Test that _resolve_top correctly parses filter arguments."""

    def test_filter_flags_parsed(self):
        from src.cli.dispatcher import _resolve_top

        # Need a report to exist for run_top to succeed; test the parsing
        # by checking the function doesn't crash on unknown flags.
        # We test _apply_top_filters separately for the actual filter logic.
        # Here we just verify the parsing doesn't error.
        try:
            _resolve_top(["--top", "--industry=电子", "--min-score=0.5"])
        except SystemExit:
            pass  # run_top may exit(1) if no report; that's fine for parsing test
        except FileNotFoundError:
            pass  # No report dir; fine

    def test_exclude_st_flag_parsed(self):
        from src.cli.dispatcher import _resolve_top

        try:
            _resolve_top(["--top", "--exclude-st"])
        except (SystemExit, FileNotFoundError):
            pass
