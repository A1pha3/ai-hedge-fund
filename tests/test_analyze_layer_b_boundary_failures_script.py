from __future__ import annotations

import json

from scripts.analyze_layer_b_boundary_failures import analyze_layer_b_boundary_failures


def test_analyze_layer_b_boundary_failures_aggregates_boundary_score_failures(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts"
    (selection_root / "2026-03-10").mkdir(parents=True)
    (selection_root / "2026-03-11").mkdir(parents=True)

    (selection_root / "2026-03-10" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-10",
                "selection_targets": {
                    "000001": {
                        "candidate_source": "layer_b_boundary",
                        "candidate_reason_codes": ["near_fast_score_threshold"],
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.21,
                            "top_reasons": ["trend_acceleration=0.40"],
                            "metrics_payload": {
                                "score_b": 0.36,
                                "score_final": 0.18,
                                "weighted_positive_contributions": {"trend_acceleration": 0.08, "close_strength": 0.06},
                                "weighted_negative_contributions": {"overhead_supply_penalty": 0.05},
                            },
                        },
                    },
                    "000002": {
                        "candidate_source": "layer_b_boundary",
                        "candidate_reason_codes": ["near_fast_score_threshold"],
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.16,
                            "top_reasons": ["breakout_freshness=0.30"],
                            "metrics_payload": {
                                "score_b": 0.31,
                                "score_final": 0.12,
                                "weighted_positive_contributions": {"trend_acceleration": 0.04, "close_strength": 0.03},
                                "weighted_negative_contributions": {"overhead_supply_penalty": 0.06},
                            },
                        },
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_root / "2026-03-11" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-11",
                "selection_targets": {
                    "000003": {
                        "candidate_source": "layer_c_watchlist",
                        "short_trade": {"decision": "rejected", "score_target": 0.33, "metrics_payload": {"score_b": 0.5, "score_final": 0.24}},
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_layer_b_boundary_failures(report_dir)

    assert analysis["layer_b_boundary_rejected_count"] == 2
    assert analysis["candidate_reason_code_counts"] == {"near_fast_score_threshold": 2}
    assert analysis["score_target_distribution"]["max"] == 0.21
    assert analysis["day_breakdown"][0]["rejected_count"] == 2
    assert analysis["strongest_negative_metrics"][0]["metric"] == "overhead_supply_penalty"
    assert analysis["recommended_focus_areas"][0]["focus_area"] == "raise_layer_b_boundary_quality_before_short_trade"
