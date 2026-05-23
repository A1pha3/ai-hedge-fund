from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import scripts.analyze_btst_5d_15pct_trend_gate_threshold_grid as grid_script


def _row(
    ticker: str,
    trade_date: str,
    *,
    report_dir_name: str,
    trend_acceleration: float,
    close_strength: float,
    candidate_source: str,
    hit: bool,
    max_return: float,
    next_open_return: float = 0.01,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "report_dir_name": report_dir_name,
        "event_prototype": "trend_continuation",
        "trend_acceleration": trend_acceleration,
        "close_strength": close_strength,
        "trend_continuation": 0.88,
        "volume_expansion_quality": 0.40,
        "breakout_freshness": 0.20,
        "candidate_source": candidate_source,
        "decision": "near_miss",
        "next_open_return": next_open_return,
        "future_high_hit_15pct_2_5d": hit,
        "max_future_high_return_2_5d": max_return,
        "cycle_status": "closed_cycle",
        "gamma_closed_cycle": True,
        "beta_tradeable": next_open_return <= 0.03,
    }


def test_trend_gate_threshold_grid_compares_thresholds_with_deduped_metrics(monkeypatch) -> None:
    rows = [
        _row("AAA", "20260324", report_dir_name="report_a", trend_acceleration=0.96, close_strength=0.89, candidate_source="catalyst_theme", hit=True, max_return=0.22),
        _row("AAA", "20260324", report_dir_name="report_b", trend_acceleration=0.96, close_strength=0.89, candidate_source="catalyst_theme", hit=True, max_return=0.22),
        _row("BBB", "20260402", report_dir_name="report_c", trend_acceleration=0.94, close_strength=0.91, candidate_source="catalyst_theme", hit=False, max_return=0.04),
        _row("CCC", "20260403", report_dir_name="report_d", trend_acceleration=0.92, close_strength=0.93, candidate_source="catalyst_theme", hit=False, max_return=0.03),
        _row("DDD", "20260404", report_dir_name="report_e", trend_acceleration=0.90, close_strength=0.80, candidate_source="short_trade_boundary", hit=True, max_return=0.18),
    ]
    monkeypatch.setattr(grid_script, "_collect_rows", lambda *args, **kwargs: rows)

    grid = grid_script.analyze_btst_5d_15pct_trend_gate_threshold_grid(
        "unused",
        close_strength_thresholds=[0.90, 0.92, 0.95],
        top_fractions=[1.0],
        min_closed_cycle_count=2,
        min_train_months=1,
    )

    assert grid["grid_row_count"] == 3
    board = {row["gate_id"]: row for row in grid["grid_board"]}
    assert board["catalyst_theme_close_strength_lt_0_90"]["candidate_unique_closed"] == 1
    assert board["catalyst_theme_close_strength_lt_0_90"]["candidate_unique_hit_rate_15pct"] == 1.0
    assert board["catalyst_theme_close_strength_lt_0_90"]["duplicate_occurrence_count"] == 1
    assert board["catalyst_theme_close_strength_lt_0_92"]["candidate_unique_closed"] == 2
    assert board["catalyst_theme_close_strength_lt_0_92"]["candidate_unique_hit_rate_15pct"] == 0.5
    assert board["catalyst_theme_close_strength_lt_0_95"]["candidate_unique_closed"] == 3
    assert board["catalyst_theme_close_strength_lt_0_95"]["candidate_unique_hit_rate_15pct"] == 0.3333
    assert grid["best_research_candidate"]["gate_id"] == "catalyst_theme_close_strength_lt_0_90"
    assert grid["grid_decision"]["next_step"] == "keep_narrow_gate_collect_samples"


def test_trend_gate_threshold_grid_marks_wide_dilution(monkeypatch) -> None:
    rows = [
        _row("AAA", "20260324", report_dir_name="report_a", trend_acceleration=0.96, close_strength=0.89, candidate_source="catalyst_theme", hit=True, max_return=0.20),
        _row("BBB", "20260402", report_dir_name="report_b", trend_acceleration=0.94, close_strength=0.91, candidate_source="catalyst_theme", hit=False, max_return=0.04),
        _row("CCC", "20260403", report_dir_name="report_c", trend_acceleration=0.92, close_strength=0.93, candidate_source="catalyst_theme", hit=False, max_return=0.03),
        _row("DDD", "20260404", report_dir_name="report_d", trend_acceleration=0.90, close_strength=0.94, candidate_source="catalyst_theme", hit=False, max_return=0.02),
    ]
    monkeypatch.setattr(grid_script, "_collect_rows", lambda *args, **kwargs: rows)

    grid = grid_script.analyze_btst_5d_15pct_trend_gate_threshold_grid(
        "unused",
        close_strength_thresholds=[0.90, 0.95],
        top_fractions=[1.0],
        min_closed_cycle_count=1,
        dilution_hit_rate_drop=0.20,
    )

    wide_row = next(row for row in grid["grid_board"] if row["gate_id"] == "catalyst_theme_close_strength_lt_0_95")
    assert wide_row["dilution_flag"] is True
    assert wide_row["candidate_unique_hit_rate_15pct"] == 0.25


def test_trend_gate_threshold_grid_script_writes_outputs(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_grid"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260324",
                "selection_targets": {
                    "TREND1": {
                        "candidate_source": "catalyst_theme",
                        "short_trade": {
                            "decision": "near_miss",
                            "explainability_payload": {
                                "trend_acceleration": 0.92,
                                "close_strength": 0.88,
                                "trend_continuation": 0.90,
                                "volume_expansion_quality": 0.40,
                                "breakout_freshness": 0.20,
                            },
                        },
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    price_dir = report_dir / "data_snapshots" / "TREND1" / "2026-03-24"
    price_dir.mkdir(parents=True, exist_ok=True)
    price_dir.joinpath("prices.json").write_text(
        json.dumps(
            [
                {"time": "2026-03-24", "open": 99.0, "close": 100.0, "high": 101.0, "low": 98.0, "volume": 100000},
                {"time": "2026-03-25", "open": 101.0, "close": 110.0, "high": 118.0, "low": 100.0, "volume": 120000},
                {"time": "2026-03-26", "open": 110.0, "close": 111.0, "high": 112.0, "low": 109.0, "volume": 90000},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_json = tmp_path / "grid.json"
    output_md = tmp_path / "grid.md"

    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/analyze_btst_5d_15pct_trend_gate_threshold_grid.py").resolve()),
            "--reports-root",
            str(reports_root),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--local-price-only",
            "--top-fraction",
            "1.0",
            "--close-strength-threshold",
            "0.90",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["grid_row_count"] == 1
    assert "Grid Board" in output_md.read_text(encoding="utf-8")
