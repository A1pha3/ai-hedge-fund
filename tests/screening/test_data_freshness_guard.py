"""Tests for data_freshness_guard.py — P6-1 数据新鲜度守门员."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.screening.data_freshness_guard import (
    apply_freshness_confidence_penalty,
    check_data_freshness,
    _normalize_date,
    _days_between,
)


class TestNormalizeDate:
    def test_compact_to_hyphenated(self) -> None:
        assert _normalize_date("20260611") == "2026-06-11"

    def test_already_hyphenated(self) -> None:
        assert _normalize_date("2026-06-11") == "2026-06-11"

    def test_empty(self) -> None:
        assert _normalize_date("") == ""

    def test_none_like(self) -> None:
        assert _normalize_date("None") == "None"


class TestDaysBetween:
    def test_same_day(self) -> None:
        assert _days_between("2026-06-11", "2026-06-11") == 0

    def test_one_day(self) -> None:
        assert _days_between("2026-06-10", "2026-06-11") == 1

    def test_week(self) -> None:
        assert _days_between("2026-06-04", "2026-06-11") == 7

    def test_reversed(self) -> None:
        assert _days_between("2026-06-12", "2026-06-11") == 0

    def test_invalid(self) -> None:
        assert _days_between("invalid", "2026-06-11") == 0


class TestCheckDataFreshness:
    def test_fresh_when_no_cache_and_no_reports(self) -> None:
        """No cache and no reports → still returns fresh=True (graceful)."""
        result = check_data_freshness(trade_date="20260611", cache_path=Path("/nonexistent/cache.sqlite"))
        assert result["fresh"] is True
        assert result["warning_count"] == 0

    def test_stale_report_detected(self, tmp_path: Path) -> None:
        """When reports_dir has only old reports, freshness check should flag it."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        # Create an old report
        old_report = reports_dir / "auto_screening_20260601.json"
        old_report.write_text(json.dumps({"recommendations": []}), encoding="utf-8")

        result = check_data_freshness(trade_date="20260611", reports_dir=reports_dir)
        assert result["fresh"] is False
        assert result["warning_count"] >= 1
        # Should have a HIGH severity warning about the report
        warning_sources = [w["source"] for w in result["warnings"]]
        assert "report_file" in warning_sources

    def test_today_report_is_fresh(self, tmp_path: Path) -> None:
        """When today's report exists, freshness check passes."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        today_report = reports_dir / "auto_screening_20260611.json"
        today_report.write_text(json.dumps({"recommendations": []}), encoding="utf-8")

        result = check_data_freshness(trade_date="20260611", reports_dir=reports_dir)
        assert result["fresh"] is True

    def test_trade_date_normalized(self) -> None:
        """trade_date is normalized to YYYY-MM-DD in output."""
        result = check_data_freshness(trade_date="20260611")
        assert result["trade_date"] == "2026-06-11"


class TestApplyFreshnessConfidencePenalty:
    def test_no_penalty_when_fresh(self) -> None:
        recs = [{"ticker": "000001", "confidence": 85}]
        freshness = {"fresh": True, "warnings": []}
        result = apply_freshness_confidence_penalty(recs, freshness)
        assert result[0]["confidence"] == 85
        assert "confidence_penalty" not in result[0]

    def test_high_severity_penalty(self) -> None:
        recs = [{"ticker": "000001", "confidence": 100}]
        freshness = {
            "fresh": False,
            "warnings": [{"severity": "HIGH", "source": "daily_prices"}],
        }
        result = apply_freshness_confidence_penalty(recs, freshness)
        assert result[0]["confidence"] == pytest.approx(70.0, abs=0.1)
        assert result[0]["confidence_penalty"] == 0.3

    def test_medium_severity_penalty(self) -> None:
        recs = [{"ticker": "000001", "confidence": 100}]
        freshness = {
            "fresh": False,
            "warnings": [{"severity": "MEDIUM", "source": "financial_metrics"}],
        }
        result = apply_freshness_confidence_penalty(recs, freshness)
        assert result[0]["confidence"] == pytest.approx(85.0, abs=0.1)

    def test_low_severity_penalty(self) -> None:
        recs = [{"ticker": "000001", "confidence": 100}]
        freshness = {
            "fresh": False,
            "warnings": [{"severity": "LOW", "source": "industry"}],
        }
        result = apply_freshness_confidence_penalty(recs, freshness)
        assert result[0]["confidence"] == pytest.approx(95.0, abs=0.1)

    def test_worst_severity_wins(self) -> None:
        """When multiple warnings, the worst severity determines penalty."""
        recs = [{"ticker": "000001", "confidence": 100}]
        freshness = {
            "fresh": False,
            "warnings": [
                {"severity": "LOW", "source": "a"},
                {"severity": "HIGH", "source": "b"},
                {"severity": "MEDIUM", "source": "c"},
            ],
        }
        result = apply_freshness_confidence_penalty(recs, freshness)
        assert result[0]["confidence"] == pytest.approx(70.0, abs=0.1)

    def test_empty_recommendations(self) -> None:
        freshness = {"fresh": False, "warnings": [{"severity": "HIGH"}]}
        result = apply_freshness_confidence_penalty([], freshness)
        assert result == []
