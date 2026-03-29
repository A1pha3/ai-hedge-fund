from __future__ import annotations

import json

from scripts.analyze_short_trade_boundary_score_failures_frontier import analyze_short_trade_boundary_score_failures_frontier


def test_analyze_short_trade_boundary_score_failures_frontier_finds_minimal_rescue_rows(tmp_path):
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
                    "score_target": 0.43,
                    "metrics_payload": {
                        "breakout_freshness": 0.4,
                        "trend_acceleration": 0.8,
                        "volume_expansion_quality": 0.25,
                        "catalyst_freshness": 0.0,
                        "close_strength": 0.9,
                        "sector_resonance": 0.1,
                        "layer_c_alignment": 0.475,
                        "stale_trend_repair_penalty": 0.12,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.1,
                        "layer_c_avoid_penalty": 0.0,
                        "weighted_positive_contributions": {},
                        "weighted_negative_contributions": {},
                        "total_positive_contribution": 0.4524,
                        "total_negative_contribution": 0.0224,
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
                    "score_target": 0.34,
                    "metrics_payload": {
                        "breakout_freshness": 0.4,
                        "trend_acceleration": 0.8,
                        "volume_expansion_quality": 0.25,
                        "catalyst_freshness": 0.0,
                        "close_strength": 0.9,
                        "sector_resonance": 0.1,
                        "layer_c_alignment": 0.475,
                        "stale_trend_repair_penalty": 0.5,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.45,
                        "layer_c_avoid_penalty": 0.0,
                        "weighted_positive_contributions": {},
                        "weighted_negative_contributions": {},
                        "total_positive_contribution": 0.448,
                        "total_negative_contribution": 0.108,
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
        },
    }
    (selection_root / "selection_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    analysis = analyze_short_trade_boundary_score_failures_frontier(
        report_dir,
        near_miss_threshold_grid=[0.46, 0.44, 0.42],
        stale_weight_grid=[0.12, 0.1, 0.08],
        extension_weight_grid=[0.08, 0.04, 0.0],
    )

    assert analysis["rescueable_case_count"] == 1
    assert analysis["rescueable_with_threshold_only_count"] == 1
    assert analysis["minimal_near_miss_rows"][0]["ticker"] == "000001"
    assert analysis["minimal_near_miss_rows"][0]["near_miss_threshold"] == 0.42
    assert analysis["minimal_near_miss_rows"][0]["adjustment_cost"] == 0.04