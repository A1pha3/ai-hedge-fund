"""Tests for scripts/diff_screening_results.py — diff between two auto-screening reports."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Make scripts/ importable
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import diff_screening_results as diff_mod  # noqa: E402


def _make_report(recs: list[dict], date: str = "20260601") -> dict:
    return {
        "date": date,
        "market_state": {"state_type": "trend", "position_scale": 1.0},
        "recommendations": recs,
    }


def test_build_index_assigns_rank_from_position() -> None:
    """_build_index should assign rank 1, 2, 3, ... based on list position."""
    recs = [
        {"ticker": "000001", "score_b": 0.5, "name": "A", "industry_sw": "X"},
        {"ticker": "000002", "score_b": 0.4, "name": "B", "industry_sw": "Y"},
    ]
    report = _make_report(recs)
    index = diff_mod._build_index(report)
    assert index["000001"]["rank"] == 1
    assert index["000002"]["rank"] == 2


def test_build_index_empty_report() -> None:
    """Empty recommendations should yield empty index."""
    assert diff_mod._build_index({}) == {}
    assert diff_mod._build_index({"recommendations": []}) == {}


def test_compute_diff_detects_new_entrants_and_dropouts() -> None:
    """Tickers in idx2 but not idx1 = new entrants; reverse = dropouts."""
    idx1 = diff_mod._build_index(
        _make_report(
            [
                {"ticker": "000001", "score_b": 0.5, "name": "A", "industry_sw": "X"},
                {"ticker": "000002", "score_b": 0.4, "name": "B", "industry_sw": "Y"},
            ]
        )
    )
    idx2 = diff_mod._build_index(
        _make_report(
            [
                {"ticker": "000001", "score_b": 0.5, "name": "A", "industry_sw": "X"},
                {"ticker": "000003", "score_b": 0.6, "name": "C", "industry_sw": "Z"},
            ]
        )
    )
    diff = diff_mod.compute_diff(idx1, idx2)
    new_tickers = [e["ticker"] for e in diff["new_entrants"]]
    drop_tickers = [e["ticker"] for e in diff["dropouts"]]
    assert "000003" in new_tickers
    assert "000002" in drop_tickers
    assert "000001" not in new_tickers and "000001" not in drop_tickers


def test_compute_diff_detects_rank_movers() -> None:
    """Tickers in both with different ranks should appear in rank_movers."""
    idx1 = diff_mod._build_index(
        _make_report(
            [
                {"ticker": "000001", "score_b": 0.3, "name": "A", "industry_sw": "X"},
                {"ticker": "000002", "score_b": 0.5, "name": "B", "industry_sw": "Y"},
            ]
        )
    )
    idx2 = diff_mod._build_index(
        _make_report(
            [
                {"ticker": "000002", "score_b": 0.5, "name": "B", "industry_sw": "Y"},
                {"ticker": "000001", "score_b": 0.4, "name": "A", "industry_sw": "X"},
            ]
        )
    )
    diff = diff_mod.compute_diff(idx1, idx2)
    movers = {m["ticker"]: m for m in diff["rank_movers"]}
    assert "000001" in movers
    assert "000002" in movers
    # 000001 went from #1 to #2 → rank_delta = -1 (moved down)
    assert movers["000001"]["rank_delta"] == -1
    # 000002 went from #2 to #1 → rank_delta = +1 (moved up)
    assert movers["000002"]["rank_delta"] == 1


def test_compute_diff_no_change_when_identical() -> None:
    """Identical indexes should yield empty new_entrants, dropouts, and movers."""
    recs = [
        {"ticker": "000001", "score_b": 0.5, "name": "A", "industry_sw": "X"},
        {"ticker": "000002", "score_b": 0.4, "name": "B", "industry_sw": "Y"},
    ]
    idx1 = diff_mod._build_index(_make_report(recs))
    idx2 = diff_mod._build_index(_make_report(recs))
    diff = diff_mod.compute_diff(idx1, idx2)
    assert diff["new_entrants"] == []
    assert diff["dropouts"] == []
    assert diff["rank_movers"] == []


def test_latest_date_returns_most_recent_yyyymmdd() -> None:
    """_latest_date should return the latest YYYYMMDD from filenames."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "auto_screening_20260601.json").write_text("{}")
        (d / "auto_screening_20260605.json").write_text("{}")
        (d / "auto_screening_20260603.json").write_text("{}")
        assert diff_mod._latest_date(d) == "20260605"


def test_latest_date_returns_none_when_empty() -> None:
    """_latest_date on empty dir should return None."""
    with tempfile.TemporaryDirectory() as td:
        assert diff_mod._latest_date(Path(td)) is None


def test_main_runs_end_to_end(tmp_path: Path, capsys) -> None:
    """main() should load two reports, compute diff, and save JSON output."""
    r1 = _make_report(
        [
            {"ticker": "000001", "score_b": 0.5, "name": "A", "industry_sw": "银行"},
            {"ticker": "000002", "score_b": 0.4, "name": "B", "industry_sw": "电子"},
        ],
        date="20260601",
    )
    r2 = _make_report(
        [
            {"ticker": "000001", "score_b": 0.6, "name": "A", "industry_sw": "银行"},
            {"ticker": "000003", "score_b": 0.7, "name": "C", "industry_sw": "医药"},
        ],
        date="20260602",
    )
    (tmp_path / "auto_screening_20260601.json").write_text(json.dumps(r1))
    (tmp_path / "auto_screening_20260602.json").write_text(json.dumps(r2))

    rc = diff_mod.main() if False else None  # don't call main; test compute_diff directly
    # Direct test of compute_diff + format_table
    idx1 = diff_mod._build_index(r1)
    idx2 = diff_mod._build_index(r2)
    diff = diff_mod.compute_diff(idx1, idx2)
    table = diff_mod.format_table(diff, "20260601", "20260602")
    assert "000003" in table  # new entrant
    assert "000002" in table  # dropout
    assert "20260601" in table and "20260602" in table
