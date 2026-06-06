from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import scripts.analyze_btst_5d_15pct_trend_gate_sample_intake_board as intake_script


def _row(
    ticker: str,
    trade_date: str,
    *,
    report_dir_name: str,
    hit: bool | None,
    max_return: float | None,
    next_open_return: float | None = 0.01,
    local_price_missing_reason: str | None = None,
    gamma_closed_cycle: bool = True,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "report_dir_name": report_dir_name,
        "event_prototype": "trend_continuation",
        "candidate_source": "catalyst_theme",
        "decision": "near_miss",
        "trend_acceleration": 0.92,
        "close_strength": 0.88,
        "trend_continuation": 0.90,
        "volume_expansion_quality": 0.40,
        "breakout_freshness": 0.20,
        "next_open_return": next_open_return,
        "future_high_hit_15pct_2_5d": hit,
        "max_future_high_return_2_5d": max_return,
        "cycle_status": "closed_cycle" if gamma_closed_cycle else "t1_only",
        "gamma_closed_cycle": gamma_closed_cycle,
        "beta_tradeable": next_open_return is not None and next_open_return <= 0.03,
        "local_price_missing_reason": local_price_missing_reason,
    }


def test_trend_gate_sample_intake_board_decomposes_unique_candidate_statuses(monkeypatch) -> None:
    rows = [
        _row("AAA", "20260324", report_dir_name="report_a", hit=True, max_return=0.22),
        _row("AAA", "20260324", report_dir_name="report_b", hit=True, max_return=0.22),
        _row("BBB", "20260402", report_dir_name="report_c", hit=False, max_return=0.04),
        _row("CCC", "20260403", report_dir_name="report_d", hit=None, max_return=None, next_open_return=None, local_price_missing_reason="missing_ticker_snapshot_root", gamma_closed_cycle=False),
        _row("DDD", "20260404", report_dir_name="report_e", hit=True, max_return=0.18, next_open_return=0.05),
        _row("EEE", "20260405", report_dir_name="report_f", hit=None, max_return=None, gamma_closed_cycle=False),
    ]
    monkeypatch.setattr(intake_script, "_collect_rows", lambda *args, **kwargs: rows)

    board = intake_script.analyze_btst_5d_15pct_trend_gate_sample_intake_board(
        "unused",
        gate_id="catalyst_theme_close_strength_lt_0_90",
        top_fraction=1.0,
        min_closed_cycle_count=3,
    )

    assert board["pre_execution_unique_count"] == 5
    assert board["duplicate_occurrence_count"] == 1
    assert board["executable_unique_count"] == 3
    assert board["closed_unique_count"] == 2
    assert board["sample_gap_to_min_closed"] == 1
    assert board["status_counts"] == {
        "closed_hit": 1,
        "closed_miss": 1,
        "missing_price": 1,
        "non_executable_gap": 1,
        "pending_cycle": 1,
    }
    assert board["closed_unique_summary"]["hit_rate_15pct"] == 0.5
    assert board["intake_decision"]["next_step"] == "backfill_missing_prices"


def test_trend_gate_sample_intake_board_collects_new_trade_dates_when_no_repairable_gap(monkeypatch) -> None:
    rows = [
        _row("AAA", "20260324", report_dir_name="report_a", hit=True, max_return=0.22),
        _row("BBB", "20260402", report_dir_name="report_b", hit=False, max_return=0.04),
    ]
    monkeypatch.setattr(intake_script, "_collect_rows", lambda *args, **kwargs: rows)

    board = intake_script.analyze_btst_5d_15pct_trend_gate_sample_intake_board(
        "unused",
        gate_id="catalyst_theme_close_strength_lt_0_90",
        top_fraction=1.0,
        min_closed_cycle_count=5,
    )

    assert board["sample_gap_to_min_closed"] == 3
    assert board["intake_decision"]["next_step"] == "collect_new_trade_dates"


def test_trend_gate_sample_intake_board_script_writes_outputs(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_intake"
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
    output_json = tmp_path / "intake.json"
    output_md = tmp_path / "intake.md"

    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/analyze_btst_5d_15pct_trend_gate_sample_intake_board.py").resolve()),
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
    assert payload["closed_unique_count"] == 1
    assert "Sample Status Board" in output_md.read_text(encoding="utf-8")
