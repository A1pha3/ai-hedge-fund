from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import scripts.analyze_btst_5d_15pct_trend_breakout_drilldown as drilldown_script


def _write_snapshot(snapshot_dir: Path) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "TREND1": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.82,
                  "close_strength": 0.72,
                  "volume_expansion_quality": 0.50,
                  "breakout_freshness": 0.20,
                  "trend_continuation": 0.80
                }
              }
            },
            "TREND2": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.64,
                  "close_strength": 0.66,
                  "volume_expansion_quality": 0.48,
                  "breakout_freshness": 0.18,
                  "trend_continuation": 0.63
                }
              }
            },
            "TREND3": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "near_miss",
                "explainability_payload": {
                  "trend_acceleration": 0.56,
                  "close_strength": 0.61,
                  "volume_expansion_quality": 0.47,
                  "breakout_freshness": 0.19,
                  "trend_continuation": 0.57
                }
              }
            },
            "BREAK1": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.46,
                  "close_strength": 0.71,
                  "volume_expansion_quality": 0.76,
                  "breakout_freshness": 0.84
                }
              }
            },
            "BREAK2": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.44,
                  "close_strength": 0.60,
                  "volume_expansion_quality": 0.58,
                  "breakout_freshness": 0.62
                }
              }
            },
            "VOL1": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.40,
                  "close_strength": 0.62,
                  "volume_expansion_quality": 0.70,
                  "breakout_freshness": 0.30
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )


def test_trend_breakout_drilldown_builds_scoped_boards(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_drilldown"
    _write_snapshot(report_dir / "selection_artifacts" / "2026-03-24")

    def _fake_extract_btst_price_outcome(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], object]) -> dict[str, object]:
        outcomes = {
            "TREND1": (True, 0.19, 0.01),
            "TREND2": (False, 0.08, 0.02),
            "TREND3": (False, 0.05, 0.02),
            "BREAK1": (True, 0.21, 0.01),
            "BREAK2": (False, 0.07, 0.04),
            "VOL1": (True, 0.18, 0.01),
        }
        hit, max_return, next_open_return = outcomes[ticker]
        return {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": hit,
            "max_future_high_return_2_5d": max_return,
            "time_to_hit_15pct": 2 if hit else None,
            "next_open_return": next_open_return,
        }

    monkeypatch.setattr(drilldown_script, "_extract_btst_price_outcome", _fake_extract_btst_price_outcome)

    analysis = drilldown_script.analyze_btst_5d_15pct_trend_breakout_drilldown(
        reports_root,
        min_closed_cycle_count=1,
    )

    assert analysis["row_count"] == 6
    assert analysis["scoped_row_count"] == 5
    assert analysis["excluded_event_prototype_counts"] == {"volume_quality_release": 1}

    trend_baseline = analysis["prototype_baselines"]["trend_continuation"]
    assert trend_baseline["closed_cycle_count"] == 3
    assert trend_baseline["hit_rate_15pct"] == 0.3333

    trend_top_slice = analysis["drilldown_boards"]["trend_continuation"][0]
    assert trend_top_slice["slice_id"] == "trend_acceleration_top_40pct"
    assert trend_top_slice["row_count"] == 2
    assert trend_top_slice["hit_rate_uplift_vs_baseline"] == 0.1667
    assert trend_top_slice["decision"] == "observe"

    breakout_gap_slice = next(row for row in analysis["drilldown_boards"]["breakout_ignition"] if row["slice_id"] == "breakout_freshness_top_40pct_gap_le_3pct")
    assert breakout_gap_slice["row_count"] == 1
    assert breakout_gap_slice["hit_rate_15pct"] == 1.0
    assert breakout_gap_slice["decision"] == "observe"

    trend_top20_gap_slice = next(row for row in analysis["drilldown_boards"]["trend_continuation"] if row["slice_id"] == "trend_acceleration_top_20pct_gap_le_3pct")
    assert trend_top20_gap_slice["row_count"] == 1
    assert trend_top20_gap_slice["hit_rate_15pct"] == 1.0
    assert trend_top20_gap_slice["decision"] == "observe"

    trend_top20_selected_gap_slice = next(row for row in analysis["drilldown_boards"]["trend_continuation"] if row["slice_id"] == "trend_acceleration_top_20pct_selected_gap_le_3pct")
    assert trend_top20_selected_gap_slice["row_count"] == 1
    assert trend_top20_selected_gap_slice["hit_rate_15pct"] == 1.0

    assert analysis["scope_decision"]["next_step"] == "continue_scoped_drilldown"


def test_trend_breakout_drilldown_prefers_local_data_snapshot_prices(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_drilldown"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "TREND1": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.82,
                  "close_strength": 0.72,
                  "volume_expansion_quality": 0.50,
                  "breakout_freshness": 0.20,
                  "trend_continuation": 0.80
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    price_dir = report_dir / "data_snapshots" / "TREND1" / "2026-03-24"
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

    def _raise_if_external_called(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], object]) -> dict[str, object]:
        raise AssertionError("external price extraction should not be called when local data_snapshots prices exist")

    monkeypatch.setattr(drilldown_script, "_extract_btst_price_outcome", _raise_if_external_called)

    analysis = drilldown_script.analyze_btst_5d_15pct_trend_breakout_drilldown(
        reports_root,
        min_closed_cycle_count=1,
    )

    trend_baseline = analysis["prototype_baselines"]["trend_continuation"]
    assert trend_baseline["closed_cycle_count"] == 1
    assert trend_baseline["hit_rate_15pct"] == 1.0
    assert trend_baseline["mean_max_future_high_return_2_5d"] == 0.18


def test_trend_breakout_drilldown_merges_local_ticker_snapshots_for_future_outcome(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_drilldown"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "TREND1": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.82,
                  "close_strength": 0.72,
                  "volume_expansion_quality": 0.50,
                  "breakout_freshness": 0.20,
                  "trend_continuation": 0.80
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    same_day_dir = report_dir / "data_snapshots" / "TREND1" / "2026-03-24"
    same_day_dir.mkdir(parents=True, exist_ok=True)
    same_day_dir.joinpath("prices.json").write_text(
        json.dumps(
            [
                {"time": "2026-03-24", "open": 99.0, "close": 100.0, "high": 101.0, "low": 98.0, "volume": 100000},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    later_dir = report_dir / "data_snapshots" / "TREND1" / "2026-03-26"
    later_dir.mkdir(parents=True, exist_ok=True)
    later_dir.joinpath("prices.json").write_text(
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

    monkeypatch.setattr(
        drilldown_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: (_ for _ in ()).throw(AssertionError("external should not be called")),
    )

    analysis = drilldown_script.analyze_btst_5d_15pct_trend_breakout_drilldown(
        reports_root,
        min_closed_cycle_count=1,
        local_price_only=True,
    )

    trend_baseline = analysis["prototype_baselines"]["trend_continuation"]
    assert trend_baseline["closed_cycle_count"] == 1
    assert trend_baseline["hit_rate_15pct"] == 1.0
    assert analysis["outcome_source_counts"] == {"local_data_snapshot": 1}


def test_trend_breakout_drilldown_can_include_non_window_reports_with_local_prices(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "btst_react_20260425_local_snapshot_variant"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "TREND1": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.82,
                  "close_strength": 0.72,
                  "volume_expansion_quality": 0.50,
                  "breakout_freshness": 0.20,
                  "trend_continuation": 0.80
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    price_dir = report_dir / "data_snapshots" / "TREND1" / "2026-03-24"
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

    monkeypatch.setattr(
        drilldown_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: (_ for _ in ()).throw(AssertionError("external should not be called")),
    )

    default_analysis = drilldown_script.analyze_btst_5d_15pct_trend_breakout_drilldown(
        reports_root,
        min_closed_cycle_count=1,
        local_price_only=True,
    )
    expanded_analysis = drilldown_script.analyze_btst_5d_15pct_trend_breakout_drilldown(
        reports_root,
        min_closed_cycle_count=1,
        local_price_only=True,
        report_name_contains="",
    )

    assert default_analysis["row_count"] == 0
    assert expanded_analysis["row_count"] == 1
    assert expanded_analysis["outcome_source_counts"] == {"local_data_snapshot": 1}


def test_trend_breakout_drilldown_local_price_only_marks_missing_without_external_call(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_drilldown"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "TREND1": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.82,
                  "close_strength": 0.72,
                  "volume_expansion_quality": 0.50,
                  "breakout_freshness": 0.20,
                  "trend_continuation": 0.80
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def _raise_if_external_called(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], object]) -> dict[str, object]:
        raise AssertionError("external price extraction should not be called in local_price_only mode")

    monkeypatch.setattr(drilldown_script, "_extract_btst_price_outcome", _raise_if_external_called)

    analysis = drilldown_script.analyze_btst_5d_15pct_trend_breakout_drilldown(
        reports_root,
        min_closed_cycle_count=1,
        local_price_only=True,
    )

    trend_baseline = analysis["prototype_baselines"]["trend_continuation"]
    assert trend_baseline["row_count"] == 1
    assert trend_baseline["closed_cycle_count"] == 0
    assert trend_baseline["hit_rate_15pct"] is None


def test_trend_breakout_drilldown_explains_local_price_coverage_gaps(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_drilldown"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "TREND1": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.82,
                  "close_strength": 0.72,
                  "volume_expansion_quality": 0.50,
                  "breakout_freshness": 0.20,
                  "trend_continuation": 0.80
                }
              }
            },
            "BREAK1": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.46,
                  "close_strength": 0.71,
                  "volume_expansion_quality": 0.76,
                  "breakout_freshness": 0.84
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    price_dir = report_dir / "data_snapshots" / "BREAK1" / "2026-03-24"
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

    monkeypatch.setattr(
        drilldown_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: (_ for _ in ()).throw(AssertionError("external should not be called")),
    )

    analysis = drilldown_script.analyze_btst_5d_15pct_trend_breakout_drilldown(
        reports_root,
        min_closed_cycle_count=1,
        local_price_only=True,
    )

    coverage = analysis["local_price_coverage"]
    assert coverage["total_rows"] == 2
    assert coverage["local_outcome_count"] == 0
    assert coverage["missing_count"] == 2
    assert coverage["missing_reason_counts"] == {
        "local_snapshot_missing_future_bar": 1,
        "missing_ticker_snapshot_root": 1,
    }
    assert coverage["missing_by_event_prototype"] == {
        "breakout_ignition": 1,
        "trend_continuation": 1,
    }
    assert coverage["top_missing_report_dirs"] == [
        {
            "report_dir_name": report_dir.name,
            "missing_count": 2,
            "scoped_missing_count": 2,
        }
    ]


def test_trend_breakout_drilldown_script_runs_as_python_entrypoint(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_drilldown"
    _write_snapshot(report_dir / "selection_artifacts" / "2026-03-24")
    output_json = tmp_path / "drilldown.json"
    output_md = tmp_path / "drilldown.md"

    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/analyze_btst_5d_15pct_trend_breakout_drilldown.py").resolve()),
            "--reports-root",
            str(reports_root),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--min-closed-cycle-count",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert output_json.exists()
    assert output_md.exists()
