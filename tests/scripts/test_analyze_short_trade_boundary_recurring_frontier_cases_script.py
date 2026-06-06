from __future__ import annotations

import json

from scripts.analyze_short_trade_boundary_recurring_frontier_cases import analyze_short_trade_boundary_recurring_frontier_cases


def test_analyze_short_trade_boundary_recurring_frontier_cases_groups_repeated_tickers(tmp_path):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-10"
    day2 = report_dir / "selection_artifacts" / "2026-03-11"
    day1.mkdir(parents=True)
    day2.mkdir(parents=True)

    snapshot_day1 = {
        "trade_date": "2026-03-10",
        "selection_targets": {
            "000001": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.37,
                    "metrics_payload": {
                        "breakout_freshness": 0.4,
                        "trend_acceleration": 0.85,
                        "volume_expansion_quality": 0.25,
                        "catalyst_freshness": 0.0,
                        "close_strength": 0.91,
                        "sector_resonance": 0.1,
                        "layer_c_alignment": 0.475,
                        "stale_trend_repair_penalty": 0.52,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.45,
                        "layer_c_avoid_penalty": 0.0,
                        "weighted_positive_contributions": {},
                        "weighted_negative_contributions": {},
                        "total_positive_contribution": 0.4685,
                        "total_negative_contribution": 0.0985,
                        "thresholds": {
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
    snapshot_day2 = {
        "trade_date": "2026-03-11",
        "selection_targets": {
            "000001": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.3663,
                    "metrics_payload": {
                        "breakout_freshness": 0.4,
                        "trend_acceleration": 0.83,
                        "volume_expansion_quality": 0.25,
                        "catalyst_freshness": 0.0,
                        "close_strength": 0.91,
                        "sector_resonance": 0.1,
                        "layer_c_alignment": 0.475,
                        "stale_trend_repair_penalty": 0.5212,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.45,
                        "layer_c_avoid_penalty": 0.0,
                        "weighted_positive_contributions": {},
                        "weighted_negative_contributions": {},
                        "total_positive_contribution": 0.4649,
                        "total_negative_contribution": 0.0985,
                        "thresholds": {
                            "near_miss_threshold": 0.46,
                            "stale_score_penalty_weight": 0.12,
                            "overhead_score_penalty_weight": 0.1,
                            "extension_score_penalty_weight": 0.08,
                            "layer_c_avoid_penalty": 0.12,
                        },
                    },
                },
            },
            "000002": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.4237,
                    "metrics_payload": {
                        "breakout_freshness": 0.4412,
                        "trend_acceleration": 0.65,
                        "volume_expansion_quality": 0.283,
                        "catalyst_freshness": 0.0573,
                        "close_strength": 0.8839,
                        "sector_resonance": 0.1247,
                        "layer_c_alignment": 0.475,
                        "stale_trend_repair_penalty": 0.1186,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.1524,
                        "layer_c_avoid_penalty": 0.0,
                        "weighted_positive_contributions": {},
                        "weighted_negative_contributions": {},
                        "total_positive_contribution": 0.4502,
                        "total_negative_contribution": 0.0264,
                        "thresholds": {
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
    (day1 / "selection_snapshot.json").write_text(json.dumps(snapshot_day1, ensure_ascii=False) + "\n", encoding="utf-8")
    (day2 / "selection_snapshot.json").write_text(json.dumps(snapshot_day2, ensure_ascii=False) + "\n", encoding="utf-8")

    analysis = analyze_short_trade_boundary_recurring_frontier_cases(report_dir, min_occurrences=2)

    assert analysis["recurring_case_count"] == 1
    assert analysis["priority_queue"][0]["ticker"] == "000001"
    assert analysis["priority_queue"][0]["occurrence_count"] == 2
    assert analysis["priority_queue"][0]["minimal_adjustment_cost"] == 0.1
