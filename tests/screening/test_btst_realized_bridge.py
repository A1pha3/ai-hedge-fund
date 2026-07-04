"""Tests for src/screening/btst_realized_bridge.py — wire BTST picks → tracking_history.

#1 (wire BTST→calibration): BTST reports live in outputs/ with picks in
operator_summary.json (string format "002222 福晶科技"). calibration/reconcile
read data/reports/tracking_history.json. This bridge extracts BTST picks,
fetches realized returns (via the R164-fixed tushare path), and upserts into
tracking_history so calibration can learn from actual BTST outcomes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.btst_realized_bridge import (
    _extract_btst_picks,
    backfill_btst_realized,
)


def _seed_btst_report(outputs_dir: Path, date_dir: str, signal_date: str, formal: list[str], confirmation: list[str] | None = None) -> None:
    """Write a BTST operator_summary.json with the given picks."""
    d = outputs_dir / date_dir
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "signal_date": signal_date,
        "execution": {
            "formal_selected_tickers": formal,
            "confirmation_only_tickers": confirmation or formal,
            "orderable_tickers": [],
        },
    }
    (d / "operator_summary.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# _extract_btst_picks
# ---------------------------------------------------------------------------


class TestExtractBtstPicks:
    def test_extracts_formal_picks(self, tmp_path: Path) -> None:
        """Formal picks '002222 福晶科技' → ('002222', '福晶科技')."""
        _seed_btst_report(tmp_path, "20260622_scheme_a", "20260622", ["002222 福晶科技", "688766 普冉股份"])
        picks = _extract_btst_picks(tmp_path)
        assert ("20260622", "002222", "福晶科技") in picks
        assert ("20260622", "688766", "普冉股份") in picks

    def test_dedupes_across_pick_fields(self, tmp_path: Path) -> None:
        """A ticker in both formal + confirmation → counted once."""
        _seed_btst_report(tmp_path, "20260622_scheme_a", "20260622", ["002222 福晶科技"], ["002222 福晶科技"])
        picks = _extract_btst_picks(tmp_path)
        assert len([p for p in picks if p[1] == "002222"]) == 1

    def test_multiple_date_dirs(self, tmp_path: Path) -> None:
        _seed_btst_report(tmp_path, "20260618_scheme_a", "20260618", ["300395 蓝色光标"])
        _seed_btst_report(tmp_path, "20260622_scheme_a", "20260622", ["002222 福晶科技"])
        picks = _extract_btst_picks(tmp_path)
        dates = {p[0] for p in picks}
        assert dates == {"20260618", "20260622"}

    def test_empty_outputs(self, tmp_path: Path) -> None:
        assert _extract_btst_picks(tmp_path) == []

    def test_skips_dirs_without_operator_summary(self, tmp_path: Path) -> None:
        (tmp_path / "20260621").mkdir()
        (tmp_path / "20260621" / "BTST-20260621.md").write_text("no summary here")
        assert _extract_btst_picks(tmp_path) == []


# ---------------------------------------------------------------------------
# backfill_btst_realized
# ---------------------------------------------------------------------------


class TestBackfillBtstRealized:
    def test_seeds_tracking_history_with_realized_returns(self, tmp_path: Path) -> None:
        """Bridge reads BTST picks → injects fetcher → writes tracking_history with realized returns."""
        outputs_dir = tmp_path / "outputs"
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        _seed_btst_report(outputs_dir, "20260618_scheme_a", "20260618", ["300395 蓝色光标"])

        # injected fetcher (avoids network): ticker → realized returns at T+1
        def fake_fetcher(ticker: str, start_date: str, end_date: str):
            return [{"time": "2026-06-18", "close": 10.0}, {"time": "2026-06-19", "close": 11.0}]

        n = backfill_btst_realized(
            outputs_dir=outputs_dir,
            reports_dir=reports_dir,
            as_of_date="20260623",
            use_data_fetcher=fake_fetcher,
        )
        assert n >= 1  # at least 1 record seeded

        # verify tracking_history has the BTST pick with realized return
        hist_path = reports_dir / "tracking_history.json"
        assert hist_path.exists()
        data = json.load(open(hist_path))
        recs = data.get("records", data) if isinstance(data, dict) else data
        tickers = {r["ticker"] for r in recs}
        assert "300395" in tickers

    def test_idempotent(self, tmp_path: Path) -> None:
        """Running twice doesn't duplicate records."""
        outputs_dir = tmp_path / "outputs"
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        _seed_btst_report(outputs_dir, "20260618_scheme_a", "20260618", ["300395 蓝色光标"])

        def fake_fetcher(ticker, start, end):
            return [{"time": "2026-06-18", "close": 10.0}, {"time": "2026-06-19", "close": 11.0}]

        n1 = backfill_btst_realized(outputs_dir=outputs_dir, reports_dir=reports_dir, as_of_date="20260623", use_data_fetcher=fake_fetcher)
        n2 = backfill_btst_realized(outputs_dir=outputs_dir, reports_dir=reports_dir, as_of_date="20260623", use_data_fetcher=fake_fetcher)
        # second run should find existing records → 0 new (idempotent)
        hist_path = reports_dir / "tracking_history.json"
        data = json.load(open(hist_path))
        recs = data.get("records", data) if isinstance(data, dict) else data
        assert len([r for r in recs if r["ticker"] == "300395" and r["recommended_date"] == "20260618"]) == 1

    def test_no_btst_reports(self, tmp_path: Path) -> None:
        """Empty outputs → 0 seeded, no crash."""
        n = backfill_btst_realized(
            outputs_dir=tmp_path / "outputs",
            reports_dir=tmp_path / "reports",
            as_of_date="20260623",
            use_data_fetcher=lambda *a, **k: [],
        )
        assert n == 0


# ---------------------------------------------------------------------------
# Task 4: T+15 / T+25 horizon support (multi-horizon diagnosis plan)
# ---------------------------------------------------------------------------


class TestTask4T15T25Horizons:
    """Task 4: seed dict and horizon mapping must include T+15 / T+25."""

    def test_seed_dict_includes_t15_t25_keys(self, tmp_path: Path) -> None:
        """Newly seeded records must carry next_15day_return / next_25day_return keys."""
        outputs_dir = tmp_path / "outputs"
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        _seed_btst_report(outputs_dir, "20260618_scheme_a", "20260618", ["300395 蓝色光标"])

        def fake_fetcher(ticker, start, end):
            return [{"time": "2026-06-18", "close": 10.0}, {"time": "2026-06-19", "close": 11.0}]

        backfill_btst_realized(
            outputs_dir=outputs_dir,
            reports_dir=reports_dir,
            as_of_date="20260623",
            use_data_fetcher=fake_fetcher,
        )
        hist_path = reports_dir / "tracking_history.json"
        data = json.load(open(hist_path))
        recs = data.get("records", data) if isinstance(data, dict) else data
        rec = next(r for r in recs if r["ticker"] == "300395")
        # Seed dict must include the new horizon keys (None until backfilled)
        assert "next_15day_return" in rec
        assert "next_25day_return" in rec

    def test_horizon_mapping_backfills_t15_t25(self, tmp_path: Path) -> None:
        """When fetcher returns enough data, day_15/day_25 land in the right fields."""
        outputs_dir = tmp_path / "outputs"
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        _seed_btst_report(outputs_dir, "20260618_scheme_a", "20260618", ["300395 蓝色光标"])

        # Fetcher that returns 31 daily bars so fetch_actual_returns produces day_15/day_25.
        # Use real calendar dates — date parsing rejects invalid month/day combos silently.
        import datetime as _dt

        def fake_fetcher(ticker, start, end):
            base = 10.0
            start_dt = _dt.date(2026, 6, 18)
            return [{"time": (start_dt + _dt.timedelta(days=i)).isoformat(), "close": base + i * 0.1} for i in range(31)]

        backfill_btst_realized(
            outputs_dir=outputs_dir,
            reports_dir=reports_dir,
            as_of_date="20260720",
            use_data_fetcher=fake_fetcher,
        )
        hist_path = reports_dir / "tracking_history.json"
        data = json.load(open(hist_path))
        recs = data.get("records", data) if isinstance(data, dict) else data
        rec = next(r for r in recs if r["ticker"] == "300395")
        # Mapping must route day_15 → next_15day_return (positive since prices rise)
        assert rec.get("next_15day_return") is not None
        assert rec.get("next_15day_return") > 0
        assert rec.get("next_25day_return") is not None
        assert rec.get("next_25day_return") > 0
