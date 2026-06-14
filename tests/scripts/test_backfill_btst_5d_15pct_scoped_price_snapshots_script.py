from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

P0_BUCKET = "p0_trend_top40_missing_ticker_snapshot_root"
P1_BUCKET = "p1_trend_top40_missing_future_bar"


def _write_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "manifest_rows": [
                    {
                        "priority_rank": 1,
                        "priority_bucket": P0_BUCKET,
                        "补数_action": "fetch_missing_ticker_snapshot_history",
                        "ticker": "TREND1",
                        "trade_date": "2026-03-24",
                        "event_prototype": "trend_continuation",
                        "local_price_missing_reason": "missing_ticker_snapshot_root",
                        "priority_score": 0.91,
                        "occurrence_count": 2,
                        "report_dir_names": ["paper_a", "paper_b"],
                    },
                    {
                        "priority_rank": 2,
                        "priority_bucket": P1_BUCKET,
                        "补数_action": "extend_existing_ticker_snapshot_forward",
                        "ticker": "TREND2",
                        "trade_date": "2026-03-25",
                        "event_prototype": "trend_continuation",
                        "local_price_missing_reason": "local_snapshot_missing_future_bar",
                        "priority_score": 0.88,
                        "occurrence_count": 1,
                        "report_dir_names": ["paper_c"],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_scoped_price_backfill_dry_run_builds_p0_plan_without_fetching(tmp_path: Path) -> None:
    backfill_script = importlib.import_module("scripts.backfill_btst_5d_15pct_scoped_price_snapshots")
    reports_root = tmp_path / "data" / "reports"
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)

    def _raise_if_fetch_called(ticker: str, start_date: str, end_date: str):
        raise AssertionError("dry-run must not fetch prices")

    result = backfill_script.backfill_btst_5d_15pct_scoped_price_snapshots(
        manifest_path,
        reports_root=reports_root,
        dry_run=True,
        priority_buckets=[P0_BUCKET],
        lookback_calendar_days=5,
        forward_calendar_days=7,
        fetch_prices_fn=_raise_if_fetch_called,
    )

    assert result["dry_run"] is True
    assert result["selected_request_count"] == 1
    assert result["planned_target_count"] == 2
    assert result["written_target_count"] == 0
    row = result["result_rows"][0]
    assert row["status"] == "dry_run"
    assert row["fetch_start_date"] == "2026-03-19"
    assert row["fetch_end_date"] == "2026-03-31"
    assert len(row["target_paths"]) == 2


def test_scoped_price_backfill_execute_fetches_once_and_writes_all_occurrences(tmp_path: Path) -> None:
    backfill_script = importlib.import_module("scripts.backfill_btst_5d_15pct_scoped_price_snapshots")
    reports_root = tmp_path / "data" / "reports"
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)
    fetch_calls: list[tuple[str, str, str]] = []

    def _fake_fetch(ticker: str, start_date: str, end_date: str):
        fetch_calls.append((ticker, start_date, end_date))
        return [
            {"time": "2026-03-24", "open": 99.0, "close": 100.0, "high": 101.0, "low": 98.0, "volume": 100000},
            {"time": "2026-03-25", "open": 101.0, "close": 108.0, "high": 118.0, "low": 100.0, "volume": 120000},
            {"time": "2026-03-26", "open": 108.0, "close": 109.0, "high": 111.0, "low": 107.0, "volume": 90000},
        ]

    result = backfill_script.backfill_btst_5d_15pct_scoped_price_snapshots(
        manifest_path,
        reports_root=reports_root,
        dry_run=False,
        priority_buckets=[P0_BUCKET],
        lookback_calendar_days=5,
        forward_calendar_days=7,
        fetch_prices_fn=_fake_fetch,
    )

    assert fetch_calls == [("TREND1", "2026-03-19", "2026-03-31")]
    assert result["selected_request_count"] == 1
    assert result["success_request_count"] == 1
    assert result["written_target_count"] == 2
    for report_dir_name in ("paper_a", "paper_b"):
        prices_path = reports_root / report_dir_name / "data_snapshots" / "TREND1" / "2026-03-24" / "prices.json"
        assert json.loads(prices_path.read_text(encoding="utf-8"))[1]["high"] == 118.0


def test_scoped_price_backfill_execute_prefers_local_snapshot_before_fetch(tmp_path: Path) -> None:
    backfill_script = importlib.import_module("scripts.backfill_btst_5d_15pct_scoped_price_snapshots")
    reports_root = tmp_path / "data" / "reports"
    snapshot_root = tmp_path / "data" / "snapshots"
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)
    source_prices = [
        {"time": "2026-03-24", "open": 99.0, "close": 100.0, "high": 101.0, "low": 98.0, "volume": 100000},
        {"time": "2026-03-25", "open": 101.0, "close": 108.0, "high": 118.0, "low": 100.0, "volume": 120000},
        {"time": "2026-03-26", "open": 108.0, "close": 109.0, "high": 111.0, "low": 107.0, "volume": 90000},
    ]
    source_path = snapshot_root / "TREND1" / "2026-03-31" / "prices.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(json.dumps(source_prices, ensure_ascii=False), encoding="utf-8")

    def _raise_if_fetch_called(ticker: str, start_date: str, end_date: str):
        raise AssertionError("local snapshot should be used before external fetch")

    result = backfill_script.backfill_btst_5d_15pct_scoped_price_snapshots(
        manifest_path,
        reports_root=reports_root,
        dry_run=False,
        priority_buckets=[P0_BUCKET],
        local_snapshot_roots=[snapshot_root],
        scan_report_snapshots=False,
        fetch_prices_fn=_raise_if_fetch_called,
    )

    assert result["success_request_count"] == 1
    assert result["local_source_request_count"] == 1
    row = result["result_rows"][0]
    assert row["status"] == "copied_local_snapshot"
    assert row["source_path"] == str(source_path.resolve())
    assert row["written_target_count"] == 2


def test_scoped_price_backfill_local_only_skips_when_no_local_source(tmp_path: Path) -> None:
    backfill_script = importlib.import_module("scripts.backfill_btst_5d_15pct_scoped_price_snapshots")
    reports_root = tmp_path / "data" / "reports"
    snapshot_root = tmp_path / "data" / "snapshots"
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)

    def _raise_if_fetch_called(ticker: str, start_date: str, end_date: str):
        raise AssertionError("local-only mode must not call external fetch")

    result = backfill_script.backfill_btst_5d_15pct_scoped_price_snapshots(
        manifest_path,
        reports_root=reports_root,
        dry_run=False,
        priority_buckets=[P0_BUCKET],
        local_snapshot_roots=[snapshot_root],
        scan_report_snapshots=False,
        local_only=True,
        fetch_prices_fn=_raise_if_fetch_called,
    )

    assert result["success_request_count"] == 0
    assert result["skipped_no_local_source_request_count"] == 1
    assert result["failed_request_count"] == 0
    assert result["result_rows"][0]["status"] == "missing_local_source"


def test_scoped_price_backfill_rejects_local_source_without_future_bars_for_future_bar_repairs(tmp_path: Path) -> None:
    backfill_script = importlib.import_module("scripts.backfill_btst_5d_15pct_scoped_price_snapshots")
    reports_root = tmp_path / "data" / "reports"
    snapshot_root = tmp_path / "data" / "snapshots"
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)
    incomplete_source = snapshot_root / "TREND2" / "2026-03-25" / "prices.json"
    incomplete_source.parent.mkdir(parents=True, exist_ok=True)
    incomplete_source.write_text(
        json.dumps(
            [
                {"time": "2026-03-24", "open": 99.0, "close": 100.0, "high": 101.0, "low": 98.0, "volume": 100000},
                {"time": "2026-03-25", "open": 101.0, "close": 102.0, "high": 103.0, "low": 100.0, "volume": 120000},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = backfill_script.backfill_btst_5d_15pct_scoped_price_snapshots(
        manifest_path,
        reports_root=reports_root,
        dry_run=False,
        priority_buckets=[P1_BUCKET],
        local_snapshot_roots=[snapshot_root],
        scan_report_snapshots=False,
        local_only=True,
    )

    assert result["success_request_count"] == 0
    assert result["local_source_request_count"] == 0
    assert result["skipped_no_local_source_request_count"] == 1
    assert result["result_rows"][0]["status"] == "missing_local_source"


def test_scoped_price_backfill_script_writes_outputs_in_dry_run(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    manifest_path = tmp_path / "manifest.json"
    output_json = tmp_path / "backfill.json"
    output_md = tmp_path / "backfill.md"
    _write_manifest(manifest_path)

    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/backfill_btst_5d_15pct_scoped_price_snapshots.py").resolve()),
            "--manifest",
            str(manifest_path),
            "--reports-root",
            str(reports_root),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--priority-bucket",
            P0_BUCKET,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert payload["selected_request_count"] == 1
    assert "TREND1" in output_md.read_text(encoding="utf-8")
