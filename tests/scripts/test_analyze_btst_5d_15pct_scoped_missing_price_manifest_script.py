from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path


def _write_manifest_fixture(report_dir: Path) -> None:
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "TREND_TOP": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.90,
                  "close_strength": 0.76,
                  "volume_expansion_quality": 0.42,
                  "breakout_freshness": 0.20,
                  "trend_continuation": 0.88
                }
              }
            },
            "TREND_LOW": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.58,
                  "close_strength": 0.64,
                  "volume_expansion_quality": 0.41,
                  "breakout_freshness": 0.18,
                  "trend_continuation": 0.60
                }
              }
            },
            "BREAK_TOP": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.48,
                  "close_strength": 0.70,
                  "volume_expansion_quality": 0.74,
                  "breakout_freshness": 0.86
                }
              }
            },
            "VOL_ONLY": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.30,
                  "close_strength": 0.62,
                  "volume_expansion_quality": 0.72,
                  "breakout_freshness": 0.25
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    price_dir = report_dir / "data_snapshots" / "BREAK_TOP" / "2026-03-24"
    price_dir.mkdir(parents=True, exist_ok=True)
    price_dir.joinpath("prices.json").write_text(
        json.dumps(
            [
                {"time": "2026-03-24", "open": 99.0, "close": 100.0, "high": 101.0, "low": 98.0, "volume": 100000},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_scoped_missing_price_manifest_prioritizes_trend_breakout_only(tmp_path: Path) -> None:
    manifest_script = importlib.import_module("scripts.analyze_btst_5d_15pct_scoped_missing_price_manifest")
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_manifest"
    _write_manifest_fixture(report_dir)

    manifest = manifest_script.analyze_btst_5d_15pct_scoped_missing_price_manifest(
        reports_root,
        report_name_contains="",
    )

    assert manifest["row_count"] == 4
    assert manifest["scoped_missing_count"] == 3
    assert manifest["excluded_event_prototype_counts"] == {"volume_quality_release": 1}
    assert manifest["missing_reason_counts"] == {
        "local_snapshot_missing_future_bar": 1,
        "missing_ticker_snapshot_root": 2,
    }
    assert manifest["priority_bucket_counts"] == {
        "p0_trend_top40_missing_ticker_snapshot_root": 1,
        "p2_trend_scoped_missing": 1,
        "p3_breakout_scoped_missing": 1,
    }

    first_row = manifest["manifest_rows"][0]
    assert first_row["priority_rank"] == 1
    assert first_row["ticker"] == "TREND_TOP"
    assert first_row["event_prototype"] == "trend_continuation"
    assert first_row["local_price_missing_reason"] == "missing_ticker_snapshot_root"
    assert first_row["priority_bucket"] == "p0_trend_top40_missing_ticker_snapshot_root"
    assert first_row["slice_tags"] == ["trend_acceleration_top_40pct", "close_strength_confirmed"]
    assert first_row["补数_action"] == "fetch_missing_ticker_snapshot_history"


def test_scoped_missing_price_manifest_dedupes_repeated_ticker_dates(tmp_path: Path) -> None:
    manifest_script = importlib.import_module("scripts.analyze_btst_5d_15pct_scoped_missing_price_manifest")
    reports_root = tmp_path / "data" / "reports"
    first_report_dir = reports_root / "paper_trading_window_20260323_20260326_manifest_a"
    second_report_dir = reports_root / "paper_trading_window_20260323_20260326_manifest_b"
    _write_manifest_fixture(first_report_dir)
    _write_manifest_fixture(second_report_dir)

    manifest = manifest_script.analyze_btst_5d_15pct_scoped_missing_price_manifest(
        reports_root,
        report_name_contains="",
    )

    assert manifest["scoped_missing_count"] == 6
    assert manifest["manifest_row_count"] == 3
    first_row = manifest["manifest_rows"][0]
    assert first_row["ticker"] == "TREND_TOP"
    assert first_row["occurrence_count"] == 2
    assert first_row["report_dir_names"] == [first_report_dir.name, second_report_dir.name]


def test_scoped_missing_price_manifest_script_writes_json_and_markdown(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_manifest"
    _write_manifest_fixture(report_dir)
    output_json = tmp_path / "manifest.json"
    output_md = tmp_path / "manifest.md"

    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/analyze_btst_5d_15pct_scoped_missing_price_manifest.py").resolve()),
            "--reports-root",
            str(reports_root),
            "--report-name-contains",
            "",
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
    assert payload["scoped_missing_count"] == 3
    assert "TREND_TOP" in output_md.read_text(encoding="utf-8")
    stdout_payload = json.loads(result.stdout)
    assert stdout_payload["manifest_row_count"] == 3
    assert "manifest_rows" not in stdout_payload
