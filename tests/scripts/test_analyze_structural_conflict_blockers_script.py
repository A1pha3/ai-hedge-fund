from __future__ import annotations

import json

from scripts.analyze_structural_conflict_blockers import analyze_structural_conflict_blockers


def test_analyze_structural_conflict_blockers_summarizes_blocked_cluster(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts"
    (selection_root / "2026-03-10").mkdir(parents=True)

    (selection_root / "2026-03-10" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-10",
                "selection_targets": {
                    "300724": {
                        "candidate_source": "layer_c_watchlist",
                        "delta_classification": "research_pass_short_reject",
                        "short_trade": {
                            "decision": "blocked",
                            "score_target": 0.3785,
                            "blockers": ["layer_c_bearish_conflict"],
                            "top_reasons": ["trend_acceleration=0.72"],
                            "metrics_payload": {
                                "layer_c_avoid_penalty": 0.0,
                                "stale_trend_repair_penalty": 0.12,
                                "overhead_supply_penalty": 0.45,
                                "extension_without_room_penalty": 0.48,
                                "breakout_freshness": 0.44,
                                "trend_acceleration": 0.72,
                                "volume_expansion_quality": 0.31,
                                "close_strength": 0.55,
                                "sector_resonance": 0.41,
                                "catalyst_freshness": 0.22,
                                "layer_c_alignment": 0.47,
                            },
                        },
                    },
                    "300394": {
                        "candidate_source": "watchlist_filter_diagnostics",
                        "delta_classification": "both_reject_but_reason_diverge",
                        "short_trade": {
                            "decision": "blocked",
                            "score_target": 0.1714,
                            "blockers": ["layer_c_bearish_conflict"],
                            "top_reasons": ["stale_trend_repair_penalty=0.47"],
                            "metrics_payload": {
                                "layer_c_avoid_penalty": 0.12,
                                "stale_trend_repair_penalty": 0.47,
                                "overhead_supply_penalty": 0.46,
                                "extension_without_room_penalty": 0.33,
                                "breakout_freshness": 0.21,
                                "trend_acceleration": 0.74,
                                "volume_expansion_quality": 0.18,
                                "close_strength": 0.61,
                                "sector_resonance": 0.19,
                                "catalyst_freshness": 0.08,
                                "layer_c_alignment": 0.26,
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

    analysis = analyze_structural_conflict_blockers(report_dir)

    assert analysis["blocked_count"] == 2
    assert analysis["candidate_source_counts"] == {"layer_c_watchlist": 1, "watchlist_filter_diagnostics": 1}
    assert analysis["delta_classification_counts"] == {"research_pass_short_reject": 1, "both_reject_but_reason_diverge": 1}
    assert analysis["top_examples"][0]["ticker"] == "300724"
    assert analysis["recommended_focus_areas"][0]["focus_area"] == "review_bearish_conflict_hard_block_for_high_score_cases"


def test_analyze_structural_conflict_blockers_can_filter_trade_dates(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts"
    (selection_root / "2026-03-10").mkdir(parents=True)
    (selection_root / "2026-03-11").mkdir(parents=True)

    (selection_root / "2026-03-10" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-10",
                "selection_targets": {
                    "300724": {
                        "candidate_source": "layer_c_watchlist",
                        "short_trade": {
                            "decision": "blocked",
                            "score_target": 0.37,
                            "blockers": ["layer_c_bearish_conflict"],
                            "metrics_payload": {},
                        },
                    }
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
                    "300394": {
                        "candidate_source": "watchlist_filter_diagnostics",
                        "short_trade": {
                            "decision": "blocked",
                            "score_target": 0.17,
                            "blockers": ["layer_c_bearish_conflict"],
                            "metrics_payload": {},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_structural_conflict_blockers(report_dir, trade_dates={"2026-03-11"})

    assert analysis["trade_dates_filter"] == ["2026-03-11"]
    assert analysis["trade_day_count"] == 1
    assert analysis["blocked_count"] == 1
    assert analysis["candidate_source_counts"] == {"watchlist_filter_diagnostics": 1}

