from __future__ import annotations

import json

from scripts.analyze_recurring_frontier_ticker_release import analyze_recurring_frontier_ticker_release


def test_analyze_recurring_frontier_ticker_release_applies_case_specific_rows(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-03-10"
    selection_root.mkdir(parents=True)
    recurring_report = tmp_path / "recurring.json"

    snapshot = {
        "trade_date": "2026-03-10",
        "selection_targets": {
            "000001": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.37,
                    "metrics_payload": {
                        "stale_trend_repair_penalty": 0.52,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.45,
                        "layer_c_avoid_penalty": 0.0,
                        "total_positive_contribution": 0.4685,
                        "thresholds": {
                            "select_threshold": 0.58,
                            "near_miss_threshold": 0.46,
                            "stale_score_penalty_weight": 0.12,
                            "overhead_score_penalty_weight": 0.1,
                            "extension_score_penalty_weight": 0.08,
                            "layer_c_avoid_penalty": 0.12,
                        },
                        "weighted_positive_contributions": {},
                        "weighted_negative_contributions": {},
                    },
                },
            }
        },
    }
    (selection_root / "selection_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False) + "\n", encoding="utf-8")
    recurring_report.write_text(
        json.dumps(
            {
                "priority_queue": [
                    {
                        "ticker": "000001",
                        "cases": [
                            {
                                "trade_date": "2026-03-10",
                                "near_miss_threshold": 0.38,
                                "stale_weight": 0.1,
                                "extension_weight": 0.08,
                                "adjustment_cost": 0.1,
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_recurring_frontier_ticker_release(
        report_dir,
        recurring_frontier_report=recurring_report,
        ticker="000001",
    )

    assert analysis["target_case_count"] == 1
    assert analysis["promoted_target_case_count"] == 1
    assert analysis["changed_cases"][0]["after_decision"] == "near_miss"
