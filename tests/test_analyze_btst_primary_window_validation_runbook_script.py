from __future__ import annotations

import json

from scripts.analyze_btst_primary_window_validation_runbook import analyze_btst_primary_window_validation_runbook


def test_analyze_btst_primary_window_validation_runbook_flags_missing_new_window(tmp_path):
    candidate_report = tmp_path / "candidate_report.json"
    primary_roll_forward = tmp_path / "primary_roll_forward.json"
    primary_window_gap = tmp_path / "primary_window_gap.json"
    report_dir = tmp_path / "paper_trading_window_20260323_20260326_live"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-26"
    snapshot_dir.mkdir(parents=True)

    candidate_report.write_text(
        json.dumps(
            {
                "report_dirs": [str(report_dir)],
                "candidates": [
                    {"ticker": "001309", "distinct_window_count": 1, "window_keys": ["20260323_20260326"]}
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    primary_roll_forward.write_text(json.dumps({"generated_on": "2026-03-30"}, ensure_ascii=False) + "\n", encoding="utf-8")
    primary_window_gap.write_text(
        json.dumps({"missing_window_count": 1, "target_window_count": 2}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (snapshot_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-26",
                "rows": [
                    {
                        "ticker": "001309",
                        "candidate_source": "short_trade_boundary",
                        "short_trade": {"decision": "near_miss", "score_target": 0.48, "metrics_payload": {}},
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_primary_window_validation_runbook(
        candidate_report,
        primary_roll_forward_path=primary_roll_forward,
        primary_window_gap_path=primary_window_gap,
        ticker="001309",
    )

    assert analysis["validation_verdict"] == "await_new_independent_window_data"
    assert analysis["window_scan_rows"][0]["status"] == "current_qualified_window"
