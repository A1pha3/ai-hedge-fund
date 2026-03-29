from __future__ import annotations

import json

from scripts.analyze_targeted_short_trade_near_miss_release import analyze_targeted_short_trade_near_miss_release


def test_analyze_targeted_short_trade_near_miss_release_changes_only_target_case(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-03-10"
    selection_root.mkdir(parents=True)

    snapshot = {
        "trade_date": "2026-03-10",
        "selection_targets": {
            "001309": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "near_miss",
                    "score_target": 0.5633,
                    "metrics_payload": {
                        "breakout_freshness": 0.86,
                        "trend_acceleration": 0.78,
                        "stale_trend_repair_penalty": 0.3764,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.45,
                        "layer_c_avoid_penalty": 0.0,
                        "total_positive_contribution": 0.6445,
                        "thresholds": {
                            "select_threshold": 0.58,
                            "near_miss_threshold": 0.46,
                            "stale_score_penalty_weight": 0.12,
                            "overhead_score_penalty_weight": 0.1,
                            "extension_score_penalty_weight": 0.08,
                            "layer_c_avoid_penalty": 0.12,
                        },
                    },
                },
            },
            "300620": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "near_miss",
                    "score_target": 0.5341,
                    "metrics_payload": {
                        "breakout_freshness": 0.87,
                        "trend_acceleration": 0.63,
                        "stale_trend_repair_penalty": 0.4712,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.44,
                        "layer_c_avoid_penalty": 0.0,
                        "total_positive_contribution": 0.6262,
                        "thresholds": {
                            "select_threshold": 0.58,
                            "near_miss_threshold": 0.46,
                            "stale_score_penalty_weight": 0.12,
                            "overhead_score_penalty_weight": 0.1,
                            "extension_score_penalty_weight": 0.08,
                            "layer_c_avoid_penalty": 0.12,
                        },
                    },
                },
            },
        },
    }
    (selection_root / "selection_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    analysis = analyze_targeted_short_trade_near_miss_release(
        report_dir,
        targets={("2026-03-10", "001309")},
        select_threshold=0.56,
        stale_weight=0.12,
        extension_weight=0.08,
    )

    assert analysis["changed_case_count"] == 1
    assert analysis["changed_non_target_case_count"] == 0
    assert analysis["decision_transition_counts"] == {"near_miss->selected": 1, "near_miss->near_miss": 1}
    assert analysis["changed_cases"][0]["ticker"] == "001309"
    assert analysis["changed_cases"][0]["after_decision"] == "selected"


def test_analyze_targeted_short_trade_near_miss_release_raises_for_missing_target(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-03-10"
    selection_root.mkdir(parents=True)
    snapshot = {
        "trade_date": "2026-03-10",
        "selection_targets": {
            "001309": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "near_miss",
                    "score_target": 0.5633,
                    "metrics_payload": {
                        "breakout_freshness": 0.86,
                        "trend_acceleration": 0.78,
                        "stale_trend_repair_penalty": 0.3764,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.45,
                        "layer_c_avoid_penalty": 0.0,
                        "total_positive_contribution": 0.6445,
                        "thresholds": {
                            "select_threshold": 0.58,
                            "near_miss_threshold": 0.46,
                            "stale_score_penalty_weight": 0.12,
                            "overhead_score_penalty_weight": 0.1,
                            "extension_score_penalty_weight": 0.08,
                            "layer_c_avoid_penalty": 0.12,
                        },
                    },
                },
            }
        },
    }
    (selection_root / "selection_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    try:
        analyze_targeted_short_trade_near_miss_release(
            report_dir,
            targets={("2026-03-10", "300620")},
            select_threshold=0.56,
            stale_weight=0.12,
            extension_weight=0.08,
        )
    except ValueError as exc:
        assert "Targets not found" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing target")