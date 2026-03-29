from __future__ import annotations

import json

from scripts.analyze_short_trade_boundary_score_failures import analyze_short_trade_boundary_score_failures


def test_analyze_short_trade_boundary_score_failures_summarizes_cluster(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts"
    (selection_root / "2026-03-10").mkdir(parents=True)
    (selection_root / "2026-03-11").mkdir(parents=True)

    snapshot_day1 = {
        "trade_date": "2026-03-10",
        "selection_targets": {
            "000001": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.41,
                    "top_reasons": ["trend_acceleration=0.80", "score_short=0.41"],
                    "metrics_payload": {
                        "breakout_freshness": 0.40,
                        "trend_acceleration": 0.80,
                        "volume_expansion_quality": 0.25,
                        "catalyst_freshness": 0.00,
                        "close_strength": 0.90,
                        "sector_resonance": 0.10,
                        "layer_c_alignment": 0.475,
                        "stale_trend_repair_penalty": 0.50,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.32,
                        "layer_c_avoid_penalty": 0.0,
                        "weighted_positive_contributions": {
                            "trend_acceleration": 0.14,
                            "close_strength": 0.12,
                        },
                        "weighted_negative_contributions": {
                            "stale_trend_repair_penalty": 0.06,
                            "extension_without_room_penalty": 0.03,
                        },
                        "total_positive_contribution": 0.47,
                        "total_negative_contribution": 0.09,
                    },
                },
            },
            "000002": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "near_miss",
                    "score_target": 0.5,
                },
            },
        },
    }
    snapshot_day2 = {
        "trade_date": "2026-03-11",
        "selection_targets": {
            "000001": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {
                    "decision": "rejected",
                    "score_target": 0.35,
                    "top_reasons": ["trend_acceleration=0.78", "score_short=0.35"],
                    "metrics_payload": {
                        "breakout_freshness": 0.42,
                        "trend_acceleration": 0.78,
                        "volume_expansion_quality": 0.27,
                        "catalyst_freshness": 0.02,
                        "close_strength": 0.88,
                        "sector_resonance": 0.11,
                        "layer_c_alignment": 0.475,
                        "stale_trend_repair_penalty": 0.48,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.41,
                        "layer_c_avoid_penalty": 0.0,
                        "weighted_positive_contributions": {
                            "trend_acceleration": 0.13,
                            "close_strength": 0.11,
                        },
                        "weighted_negative_contributions": {
                            "stale_trend_repair_penalty": 0.0576,
                            "extension_without_room_penalty": 0.0328,
                        },
                        "total_positive_contribution": 0.45,
                        "total_negative_contribution": 0.0904,
                    },
                },
            },
            "300394": {
                "candidate_source": "watchlist_filter_diagnostics",
                "short_trade": {
                    "decision": "blocked",
                    "score_target": 0.1,
                },
            },
        },
    }

    (selection_root / "2026-03-10" / "selection_snapshot.json").write_text(json.dumps(snapshot_day1, ensure_ascii=False) + "\n", encoding="utf-8")
    (selection_root / "2026-03-11" / "selection_snapshot.json").write_text(json.dumps(snapshot_day2, ensure_ascii=False) + "\n", encoding="utf-8")

    analysis = analyze_short_trade_boundary_score_failures(report_dir)

    assert analysis["trade_day_count"] == 2
    assert analysis["rejected_short_trade_boundary_count"] == 2
    assert analysis["gap_band_counts"] == {"gap<=0.06": 1, "gap>0.06": 1}
    assert analysis["recurring_ticker_counts"] == {"000001": 2}
    assert analysis["metric_summary"]["score_target"]["mean"] == 0.38
    assert analysis["mean_positive_contributions"] == {"close_strength": 0.115, "trend_acceleration": 0.135}
    assert analysis["mean_negative_contributions"] == {"extension_without_room_penalty": 0.0314, "stale_trend_repair_penalty": 0.0588}
    assert analysis["closest_to_near_miss_cases"][0]["ticker"] == "000001"
    assert "score construction" in analysis["recommendation"]