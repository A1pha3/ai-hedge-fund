from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_gate_manifest_snapshot(report_dir: Path) -> None:
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260324",
                "selection_targets": {
                    "CAT_MISSING": {
                        "candidate_source": "catalyst_theme",
                        "short_trade": {
                            "decision": "near_miss",
                            "explainability_payload": {
                                "trend_acceleration": 0.94,
                                "close_strength": 0.88,
                                "volume_expansion_quality": 0.42,
                                "breakout_freshness": 0.20,
                                "trend_continuation": 0.90,
                            },
                        },
                    },
                    "CAT_HAS_PRICE": {
                        "candidate_source": "catalyst_theme",
                        "short_trade": {
                            "decision": "near_miss",
                            "explainability_payload": {
                                "trend_acceleration": 0.91,
                                "close_strength": 0.86,
                                "volume_expansion_quality": 0.40,
                                "breakout_freshness": 0.18,
                                "trend_continuation": 0.89,
                            },
                        },
                    },
                    "CAT_CLOSE_TOO_HIGH": {
                        "candidate_source": "catalyst_theme",
                        "short_trade": {
                            "decision": "near_miss",
                            "explainability_payload": {
                                "trend_acceleration": 0.93,
                                "close_strength": 0.94,
                                "volume_expansion_quality": 0.40,
                                "breakout_freshness": 0.18,
                                "trend_continuation": 0.89,
                            },
                        },
                    },
                    "BOUNDARY_MISSING": {
                        "candidate_source": "short_trade_boundary",
                        "short_trade": {
                            "decision": "near_miss",
                            "explainability_payload": {
                                "trend_acceleration": 0.92,
                                "close_strength": 0.87,
                                "volume_expansion_quality": 0.41,
                                "breakout_freshness": 0.19,
                                "trend_continuation": 0.88,
                            },
                        },
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    price_dir = report_dir / "data_snapshots" / "CAT_HAS_PRICE" / "2026-03-24"
    price_dir.mkdir(parents=True, exist_ok=True)
    price_dir.joinpath("prices.json").write_text(
        json.dumps(
            [
                {"time": "2026-03-24", "open": 99.0, "close": 100.0, "high": 101.0, "low": 98.0, "volume": 100000},
                {"time": "2026-03-25", "open": 101.0, "close": 108.0, "high": 118.0, "low": 100.0, "volume": 120000},
                {"time": "2026-03-26", "open": 108.0, "close": 109.0, "high": 111.0, "low": 107.0, "volume": 90000},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_trend_gate_missing_price_manifest_keeps_pre_execution_candidates(tmp_path: Path) -> None:
    import scripts.analyze_btst_5d_15pct_trend_gate_missing_price_manifest as manifest_script

    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_gate_manifest"
    _write_gate_manifest_snapshot(report_dir)

    manifest = manifest_script.analyze_btst_5d_15pct_trend_gate_missing_price_manifest(
        reports_root,
        report_name_contains="",
        top_fraction=1.0,
        gate_id="catalyst_theme_close_strength_lt_0_90",
    )

    assert manifest["pre_execution_unique_count"] == 2
    assert manifest["known_executable_unique_summary"]["closed_cycle_count"] == 1
    assert manifest["missing_occurrence_count"] == 1
    assert manifest["manifest_row_count"] == 1
    row = manifest["manifest_rows"][0]
    assert row["ticker"] == "CAT_MISSING"
    assert row["priority_bucket"] == "p0_gate_missing_ticker_snapshot_root"
    assert row["report_dir_names"] == [report_dir.name]


def test_trend_gate_missing_price_manifest_dedupes_repeated_reports(tmp_path: Path) -> None:
    import scripts.analyze_btst_5d_15pct_trend_gate_missing_price_manifest as manifest_script

    reports_root = tmp_path / "data" / "reports"
    first_report = reports_root / "paper_trading_window_20260323_20260326_gate_manifest_a"
    second_report = reports_root / "paper_trading_window_20260323_20260326_gate_manifest_b"
    _write_gate_manifest_snapshot(first_report)
    _write_gate_manifest_snapshot(second_report)

    manifest = manifest_script.analyze_btst_5d_15pct_trend_gate_missing_price_manifest(
        reports_root,
        report_name_contains="",
        top_fraction=1.0,
        gate_id="catalyst_theme_close_strength_lt_0_90",
    )

    assert manifest["missing_occurrence_count"] == 2
    assert manifest["manifest_row_count"] == 1
    row = manifest["manifest_rows"][0]
    assert row["occurrence_count"] == 2
    assert row["report_dir_names"] == [first_report.name, second_report.name]


def test_trend_gate_missing_price_manifest_script_writes_outputs(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_gate_manifest"
    _write_gate_manifest_snapshot(report_dir)
    output_json = tmp_path / "manifest.json"
    output_md = tmp_path / "manifest.md"

    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/analyze_btst_5d_15pct_trend_gate_missing_price_manifest.py").resolve()),
            "--reports-root",
            str(reports_root),
            "--report-name-contains",
            "",
            "--top-fraction",
            "1.0",
            "--gate-id",
            "catalyst_theme_close_strength_lt_0_90",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["manifest_row_count"] == 1
    assert "CAT_MISSING" in output_md.read_text(encoding="utf-8")
    stdout_payload = json.loads(result.stdout)
    assert stdout_payload["manifest_row_count"] == 1
    assert "manifest_rows" not in stdout_payload
