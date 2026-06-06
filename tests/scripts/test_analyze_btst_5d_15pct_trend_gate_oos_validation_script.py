from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import scripts.analyze_btst_5d_15pct_trend_gate_oos_validation as oos_script


def _row(
    ticker: str,
    trade_date: str,
    *,
    report_dir_name: str,
    trend_acceleration: float,
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
        "close_strength": 0.75,
        "next_open_return": next_open_return,
        "future_high_hit_15pct_2_5d": hit,
        "max_future_high_return_2_5d": max_return,
        "cycle_status": "closed_cycle",
        "gamma_closed_cycle": True,
        "beta_tradeable": next_open_return <= 0.03,
        "decision": "near_miss",
        "candidate_source": "short_trade_boundary",
    }


def test_trend_gate_oos_validation_dedupes_before_monthly_and_rolling_splits(monkeypatch) -> None:
    rows = [
        _row("AAA", "20260324", report_dir_name="report_a", trend_acceleration=0.92, hit=True, max_return=0.22),
        _row("AAA", "20260324", report_dir_name="report_b", trend_acceleration=0.92, hit=True, max_return=0.22),
        _row("BBB", "20260402", report_dir_name="report_c", trend_acceleration=0.88, hit=False, max_return=0.05),
        _row("CCC", "20260403", report_dir_name="report_c", trend_acceleration=0.70, hit=False, max_return=0.04),
    ]
    monkeypatch.setattr(oos_script, "_collect_rows", lambda *args, **kwargs: rows)

    validation = oos_script.analyze_btst_5d_15pct_trend_gate_oos_validation(
        "unused",
        min_closed_cycle_count=1,
        min_train_months=1,
        top_fraction=1.0,
        gate_id="trend_acceleration_ge_0_85",
    )

    assert validation["base_unique_summary"]["closed_cycle_count"] == 3
    assert validation["candidate_unique_summary"]["closed_cycle_count"] == 2
    assert validation["candidate_unique_summary"]["hit_rate_15pct"] == 0.5
    assert validation["candidate_unique_summary"]["duplicate_occurrence_count"] == 1

    month_board = {row["month"]: row for row in validation["monthly_board"]}
    assert month_board["2026-03"]["closed_cycle_count"] == 1
    assert month_board["2026-03"]["hit_rate_15pct"] == 1.0
    assert month_board["2026-04"]["closed_cycle_count"] == 1
    assert month_board["2026-04"]["hit_rate_15pct"] == 0.0

    rolling = validation["rolling_splits"]
    assert rolling[0]["train_months"] == ["2026-03"]
    assert rolling[0]["test_month"] == "2026-04"
    assert rolling[0]["train_summary"]["hit_rate_15pct"] == 1.0
    assert rolling[0]["test_summary"]["hit_rate_15pct"] == 0.0
    assert validation["rollout_decision"]["next_step"] == "continue_research_not_rollout"


def test_trend_gate_oos_validation_promotes_only_when_oos_thresholds_hold(monkeypatch) -> None:
    rows = [
        _row("AAA", "20260105", report_dir_name="report_a", trend_acceleration=0.91, hit=True, max_return=0.21),
        _row("BBB", "20260206", report_dir_name="report_b", trend_acceleration=0.90, hit=True, max_return=0.18),
        _row("CCC", "20260307", report_dir_name="report_c", trend_acceleration=0.89, hit=True, max_return=0.17),
        _row("DDD", "20260408", report_dir_name="report_d", trend_acceleration=0.88, hit=True, max_return=0.19),
    ]
    monkeypatch.setattr(oos_script, "_collect_rows", lambda *args, **kwargs: rows)

    validation = oos_script.analyze_btst_5d_15pct_trend_gate_oos_validation(
        "unused",
        min_closed_cycle_count=2,
        min_train_months=2,
        min_oos_test_months=2,
        top_fraction=1.0,
        gate_id="trend_acceleration_ge_0_85",
    )

    assert validation["candidate_unique_summary"]["hit_rate_15pct"] == 1.0
    assert validation["stable_oos_test_month_count"] == 2
    assert validation["rollout_decision"]["next_step"] == "promote_to_shadow_rollout"


def test_trend_gate_oos_validation_supports_candidate_source_gate_ids(monkeypatch) -> None:
    rows = [
        {
            **_row("AAA", "20260324", report_dir_name="report_a", trend_acceleration=0.92, hit=True, max_return=0.20),
            "candidate_source": "catalyst_theme",
        },
        {
            **_row("BBB", "20260325", report_dir_name="report_b", trend_acceleration=0.91, hit=False, max_return=0.04),
            "candidate_source": "short_trade_boundary",
        },
    ]
    monkeypatch.setattr(oos_script, "_collect_rows", lambda *args, **kwargs: rows)

    validation = oos_script.analyze_btst_5d_15pct_trend_gate_oos_validation(
        "unused",
        min_closed_cycle_count=1,
        top_fraction=1.0,
        gate_id="candidate_source_catalyst_theme",
    )

    assert validation["candidate_unique_summary"]["closed_cycle_count"] == 1
    assert validation["candidate_manifest"][0]["ticker"] == "AAA"


def test_trend_gate_oos_validation_supports_parameterized_catalyst_close_strength_gate_ids(monkeypatch) -> None:
    rows = [
        {
            **_row("AAA", "20260324", report_dir_name="report_a", trend_acceleration=0.92, hit=True, max_return=0.20),
            "candidate_source": "catalyst_theme",
            "close_strength": 0.91,
        },
        {
            **_row("BBB", "20260325", report_dir_name="report_b", trend_acceleration=0.91, hit=False, max_return=0.04),
            "candidate_source": "catalyst_theme",
            "close_strength": 0.93,
        },
    ]
    monkeypatch.setattr(oos_script, "_collect_rows", lambda *args, **kwargs: rows)

    validation = oos_script.analyze_btst_5d_15pct_trend_gate_oos_validation(
        "unused",
        min_closed_cycle_count=1,
        top_fraction=1.0,
        gate_id="catalyst_theme_close_strength_lt_0_92",
    )

    assert validation["candidate_unique_summary"]["closed_cycle_count"] == 1
    assert validation["candidate_manifest"][0]["ticker"] == "AAA"


def test_trend_gate_oos_validation_script_writes_outputs(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_oos"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260324",
                "selection_targets": {
                    "TREND1": {
                        "candidate_source": "short_trade_boundary",
                        "short_trade": {
                            "decision": "near_miss",
                            "explainability_payload": {
                                "trend_acceleration": 0.92,
                                "close_strength": 0.80,
                                "volume_expansion_quality": 0.40,
                                "breakout_freshness": 0.20,
                                "trend_continuation": 0.90,
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
    output_json = tmp_path / "oos.json"
    output_md = tmp_path / "oos.md"

    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/analyze_btst_5d_15pct_trend_gate_oos_validation.py").resolve()),
            "--reports-root",
            str(reports_root),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--min-closed-cycle-count",
            "1",
            "--min-train-months",
            "1",
            "--top-fraction",
            "1.0",
            "--local-price-only",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["candidate_unique_summary"]["closed_cycle_count"] == 1
    assert "Rollout Decision" in output_md.read_text(encoding="utf-8")
