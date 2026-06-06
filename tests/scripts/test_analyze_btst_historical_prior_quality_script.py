"""Tests for the analyze_btst_historical_prior_quality audit script.

Verifies the script produces the required JSON and Markdown report shape
from sample selection_artifact snapshots containing historical_prior payloads.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.analyze_btst_historical_prior_quality import analyze_btst_historical_prior_quality


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _sample_snapshot(trade_date: str, entries: list[dict]) -> dict:
    return {
        "trade_date": trade_date,
        "target_context": entries,
    }


def _entry_with_prior(ticker: str, decision: str, evaluable_count: int, high_hit: float, close_pos: float) -> dict:
    return {
        "ticker": ticker,
        "short_trade": {"decision": decision},
        "replay_context": {
            "historical_prior": {
                "evaluable_count": evaluable_count,
                "next_high_hit_rate_at_threshold": high_hit,
                "next_close_positive_rate": close_pos,
            }
        },
    }


class TestAnalyzeBtstHistoricalPriorQualityBasicShape:
    """The audit function must return a dict with required top-level keys."""

    def test_returns_required_keys(self, tmp_path: Path):
        report_dir = tmp_path / "paper_trading_window_sample"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json",
            _sample_snapshot("2026-04-06", [
                _entry_with_prior("000001", "selected", 8, 0.45, 0.60),
                _entry_with_prior("000002", "near_miss", 3, 0.30, 0.55),
            ]),
        )
        result = analyze_btst_historical_prior_quality(report_dir)

        assert "snapshot_count" in result
        assert "prior_quality_distribution" in result
        assert "selected_sample_quality_before" in result
        assert "selected_sample_quality_after" in result
        assert "downgrade_reasons" in result
        assert "report_type" in result

    def test_snapshot_count_matches_input(self, tmp_path: Path):
        report_dir = tmp_path / "paper_trading_window_sample"
        for date in ["2026-04-06", "2026-04-07", "2026-04-08"]:
            _write_json(
                report_dir / "selection_artifacts" / date / "selection_snapshot.json",
                _sample_snapshot(date, [_entry_with_prior("000001", "selected", 6, 0.40, 0.55)]),
            )
        result = analyze_btst_historical_prior_quality(report_dir)
        assert result["snapshot_count"] == 3


class TestAnalyzeBtstHistoricalPriorQualityClassification:
    """Distribution must reflect classifier output for each entry."""

    def test_reject_counted_in_distribution(self, tmp_path: Path):
        report_dir = tmp_path / "paper_trading_window_sample"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json",
            _sample_snapshot("2026-04-06", [
                _entry_with_prior("000001", "selected", 10, 0.0, 0.65),  # zero high hit → reject
            ]),
        )
        result = analyze_btst_historical_prior_quality(report_dir)
        assert result["prior_quality_distribution"].get("reject", 0) >= 1

    def test_watch_only_counted_in_distribution(self, tmp_path: Path):
        report_dir = tmp_path / "paper_trading_window_sample"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json",
            _sample_snapshot("2026-04-06", [
                _entry_with_prior("000001", "selected", 10, 0.35, 0.40),  # low close+ → watch_only
            ]),
        )
        result = analyze_btst_historical_prior_quality(report_dir)
        assert result["prior_quality_distribution"].get("watch_only", 0) >= 1

    def test_execution_ready_counted_in_distribution(self, tmp_path: Path):
        report_dir = tmp_path / "paper_trading_window_sample"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json",
            _sample_snapshot("2026-04-06", [
                _entry_with_prior("000001", "selected", 8, 0.45, 0.62),  # good prior
            ]),
        )
        result = analyze_btst_historical_prior_quality(report_dir)
        assert result["prior_quality_distribution"].get("execution_ready", 0) >= 1


class TestAnalyzeBtstHistoricalPriorQualityBeforeAfterComparison:
    """Must include a before/after comparison for selected-entry sample quality."""

    def test_before_count_includes_all_selected_entries(self, tmp_path: Path):
        report_dir = tmp_path / "paper_trading_window_sample"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json",
            _sample_snapshot("2026-04-06", [
                _entry_with_prior("000001", "selected", 10, 0.0, 0.65),   # reject
                _entry_with_prior("000002", "selected", 8, 0.45, 0.60),   # execution_ready
                _entry_with_prior("000003", "near_miss", 4, 0.35, 0.55),  # near_miss skipped for selected
            ]),
        )
        result = analyze_btst_historical_prior_quality(report_dir)
        # before = all selected entries regardless of prior quality
        assert result["selected_sample_quality_before"]["total_selected"] == 2

    def test_after_count_excludes_blocked_entries(self, tmp_path: Path):
        report_dir = tmp_path / "paper_trading_window_sample"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json",
            _sample_snapshot("2026-04-06", [
                _entry_with_prior("000001", "selected", 10, 0.0, 0.65),   # reject → blocked
                _entry_with_prior("000002", "selected", 8, 0.45, 0.60),   # execution_ready → kept
            ]),
        )
        result = analyze_btst_historical_prior_quality(report_dir)
        # after = only execution_ready selected entries
        assert result["selected_sample_quality_after"]["total_selected"] == 1

    def test_downgrade_reasons_present(self, tmp_path: Path):
        report_dir = tmp_path / "paper_trading_window_sample"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json",
            _sample_snapshot("2026-04-06", [
                _entry_with_prior("000001", "selected", 10, 0.0, 0.65),  # reject
                _entry_with_prior("000002", "selected", 2, 0.35, 0.55),  # tiny n
            ]),
        )
        result = analyze_btst_historical_prior_quality(report_dir)
        assert isinstance(result["downgrade_reasons"], dict)
        # Must have at least one reason code counted
        assert sum(result["downgrade_reasons"].values()) >= 1


class TestAnalyzeBtstHistoricalPriorQualityEmptyInput:
    """Gracefully handle empty or missing snapshot directories."""

    def test_empty_directory_returns_zero_snapshot_count(self, tmp_path: Path):
        report_dir = tmp_path / "paper_trading_window_empty"
        report_dir.mkdir(parents=True)
        result = analyze_btst_historical_prior_quality(report_dir)
        assert result["snapshot_count"] == 0

    def test_entries_without_prior_skipped_gracefully(self, tmp_path: Path):
        report_dir = tmp_path / "paper_trading_window_sample"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json",
            {"trade_date": "2026-04-06", "target_context": [{"ticker": "000001", "short_trade": {"decision": "selected"}}]},
        )
        result = analyze_btst_historical_prior_quality(report_dir)
        # Entry without historical_prior should be skipped (no crash)
        assert result["snapshot_count"] == 1
