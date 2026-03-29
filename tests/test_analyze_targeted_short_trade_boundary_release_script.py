from __future__ import annotations

import json

from scripts.analyze_targeted_short_trade_boundary_release import analyze_targeted_short_trade_boundary_release


def test_analyze_targeted_short_trade_boundary_release_changes_only_target_case(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-03-10"
    selection_root.mkdir(parents=True)

    snapshot = {
        "trade_date": "2026-03-10",
        "selection_targets": {
            "000001": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.4237,
                    "metrics_payload": {
                        "stale_trend_repair_penalty": 0.1186,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.1524,
                        "layer_c_avoid_penalty": 0.0,
                        "total_positive_contribution": 0.4502,
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
            },
            "000002": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.35,
                    "metrics_payload": {
                        "stale_trend_repair_penalty": 0.5,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.45,
                        "layer_c_avoid_penalty": 0.0,
                        "total_positive_contribution": 0.448,
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
            },
        },
    }
    (selection_root / "selection_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    analysis = analyze_targeted_short_trade_boundary_release(
        report_dir,
        targets={("2026-03-10", "000001")},
        near_miss_threshold=0.42,
        stale_weight=0.12,
        extension_weight=0.08,
    )

    assert analysis["changed_case_count"] == 1
    assert analysis["changed_non_target_case_count"] == 0
    assert analysis["decision_transition_counts"] == {"rejected->rejected": 1, "rejected->near_miss": 1}
    assert analysis["changed_cases"][0]["ticker"] == "000001"
    assert analysis["changed_cases"][0]["after_decision"] == "near_miss"
