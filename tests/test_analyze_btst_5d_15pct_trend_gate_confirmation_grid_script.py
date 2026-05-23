from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import scripts.analyze_btst_5d_15pct_trend_gate_confirmation_grid as confirmation_script


def _row(
    ticker: str,
    trade_date: str,
    *,
    report_dir_name: str,
    hit: bool,
    max_return: float,
    trend_continuation: float,
    volume_expansion_quality: float,
    breakout_freshness: float = 0.20,
    t0_tail_strength: float = 0.55,
    trend_acceleration: float = 0.92,
    close_strength: float = 0.88,
    candidate_source: str = "catalyst_theme",
    next_open_return: float = 0.01,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "report_dir_name": report_dir_name,
        "event_prototype": "trend_continuation",
        "trend_acceleration": trend_acceleration,
        "close_strength": close_strength,
        "trend_continuation": trend_continuation,
        "volume_expansion_quality": volume_expansion_quality,
        "breakout_freshness": breakout_freshness,
        "t0_tail_strength": t0_tail_strength,
        "candidate_source": candidate_source,
        "decision": "near_miss",
        "next_open_return": next_open_return,
        "future_high_hit_15pct_2_5d": hit,
        "max_future_high_return_2_5d": max_return,
        "cycle_status": "closed_cycle",
        "gamma_closed_cycle": True,
        "beta_tradeable": next_open_return <= 0.03,
    }


def test_confirmation_grid_prefers_best_deduped_confirmation_candidate(monkeypatch) -> None:
    rows = [
        _row("AAA", "20260324", report_dir_name="report_a", hit=True, max_return=0.24, trend_continuation=0.92, volume_expansion_quality=0.48),
        _row("AAA", "20260324", report_dir_name="report_b", hit=True, max_return=0.24, trend_continuation=0.92, volume_expansion_quality=0.48),
        _row("BBB", "20260402", report_dir_name="report_c", hit=False, max_return=0.04, trend_continuation=0.84, volume_expansion_quality=0.30),
        _row("CCC", "20260403", report_dir_name="report_d", hit=True, max_return=0.18, trend_continuation=0.90, volume_expansion_quality=0.42),
    ]
    monkeypatch.setattr(confirmation_script, "_collect_rows", lambda *args, **kwargs: rows)

    board = confirmation_script.analyze_btst_5d_15pct_trend_gate_confirmation_grid(
        "unused",
        top_fraction=1.0,
        min_closed_cycle_count=2,
        confirmation_specs=[
            ("trend_continuation_ge_0_90", "trend_continuation", ">=", 0.90),
            ("volume_expansion_quality_ge_0_45", "volume_expansion_quality", ">=", 0.45),
        ],
    )

    assert board["base_summary"]["closed_cycle_count"] == 3
    assert board["best_confirmation_candidate"]["confirmation_id"] == "trend_continuation_ge_0_90"
    assert board["best_confirmation_candidate"]["candidate_unique_closed"] == 2
    assert board["best_confirmation_candidate"]["candidate_unique_hit_rate_15pct"] == 1.0


def test_confirmation_grid_stays_collect_samples_when_quality_is_promising_but_count_is_small(monkeypatch) -> None:
    rows = [
        _row("AAA", "20260324", report_dir_name="report_a", hit=True, max_return=0.22, trend_continuation=0.91, volume_expansion_quality=0.46),
        _row("BBB", "20260402", report_dir_name="report_b", hit=False, max_return=0.10, trend_continuation=0.91, volume_expansion_quality=0.44),
        _row("CCC", "20260403", report_dir_name="report_c", hit=False, max_return=0.03, trend_continuation=0.80, volume_expansion_quality=0.25),
    ]
    monkeypatch.setattr(confirmation_script, "_collect_rows", lambda *args, **kwargs: rows)

    board = confirmation_script.analyze_btst_5d_15pct_trend_gate_confirmation_grid(
        "unused",
        top_fraction=1.0,
        min_closed_cycle_count=5,
        confirmation_specs=[("trend_continuation_ge_0_90", "trend_continuation", ">=", 0.90)],
    )

    assert board["best_confirmation_candidate"]["candidate_unique_closed"] == 2
    assert board["best_confirmation_candidate"]["candidate_unique_hit_rate_15pct"] == 0.5
    assert board["best_confirmation_candidate"]["candidate_unique_mean_max_return"] == 0.16
    assert board["grid_decision"]["next_step"] == "keep_confirmation_candidate_collect_samples"


def test_confirmation_grid_script_writes_outputs(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_confirmation"
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
                                "trend_continuation": 0.91,
                                "volume_expansion_quality": 0.47,
                                "breakout_freshness": 0.20,
                                "t0_tail_strength": 0.58,
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
    output_json = tmp_path / "confirmation.json"
    output_md = tmp_path / "confirmation.md"

    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/analyze_btst_5d_15pct_trend_gate_confirmation_grid.py").resolve()),
            "--reports-root",
            str(reports_root),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--local-price-only",
            "--report-name-contains",
            "",
            "--top-fraction",
            "1.0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["grid_row_count"] >= 1
    assert payload["base_summary"]["closed_cycle_count"] == 1
    assert "Confirmation Grid Board" in output_md.read_text(encoding="utf-8")
