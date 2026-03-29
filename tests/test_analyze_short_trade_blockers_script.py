from __future__ import annotations

import json

from scripts.analyze_short_trade_blockers import analyze_short_trade_blockers


def test_analyze_short_trade_blockers_aggregates_decisions_and_sources(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts"
    (selection_root / "2026-03-10").mkdir(parents=True)
    (selection_root / "2026-03-11").mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "dual_target"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (selection_root / "2026-03-10" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-10",
                "selection_targets": {
                    "000001": {
                        "candidate_source": "layer_b_boundary",
                        "candidate_reason_codes": ["near_fast_score_threshold"],
                        "delta_classification": "research_reject_short_pass",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.61,
                            "blockers": [],
                            "negative_tags": [],
                            "top_reasons": ["score_short=0.61"],
                            "gate_status": {"score": "pass", "structural": "pass"},
                            "metrics_payload": {"score_b": 0.49, "score_c": 0.0, "score_final": 0.49},
                            "explainability_payload": {"available_strategy_signals": ["trend", "event_sentiment"]},
                        },
                    },
                    "000002": {
                        "candidate_source": "watchlist_filter_diagnostics",
                        "candidate_reason_codes": ["decision_avoid"],
                        "delta_classification": "both_reject_but_reason_diverge",
                        "short_trade": {
                            "decision": "blocked",
                            "score_target": 0.22,
                            "blockers": ["layer_c_bearish_conflict"],
                            "negative_tags": ["layer_c_avoid_signal"],
                            "top_reasons": ["score_short=0.22"],
                            "gate_status": {"score": "fail", "structural": "fail"},
                            "metrics_payload": {"score_b": 0.40, "score_c": -0.05, "score_final": 0.19},
                            "explainability_payload": {"available_strategy_signals": []},
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
                        "candidate_reason_codes": [],
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.31,
                            "blockers": [],
                            "negative_tags": ["event_signal_incomplete"],
                            "top_reasons": ["score_short=0.31"],
                            "gate_status": {"score": "fail", "structural": "pass"},
                            "metrics_payload": {"score_b": 0.58, "score_c": 0.12, "score_final": 0.34},
                            "explainability_payload": {"available_strategy_signals": ["trend"]},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_blockers(report_dir)

    assert analysis["target_mode"] == "dual_target"
    assert analysis["short_trade_target_count"] == 3
    assert analysis["short_trade_decision_counts"] == {"selected": 1, "blocked": 1, "rejected": 1}
    assert analysis["candidate_source_counts"] == {
        "layer_b_boundary": 1,
        "watchlist_filter_diagnostics": 1,
        "layer_c_watchlist": 1,
    }
    assert analysis["failure_mechanism_counts"] == {
        "selected": 1,
        "blocked_structural_bearish_conflict": 1,
        "rejected_layer_c_watchlist_score_fail": 1,
    }
    assert analysis["candidate_source_breakdown"]["watchlist_filter_diagnostics"]["decision_counts"] == {"blocked": 1}
    assert analysis["candidate_source_breakdown"]["watchlist_filter_diagnostics"]["blocker_counts"] == {"layer_c_bearish_conflict": 1}
    assert analysis["blocker_counts"] == {"layer_c_bearish_conflict": 1}
    assert analysis["negative_tag_counts"] == {"layer_c_avoid_signal": 1, "event_signal_incomplete": 1}
    assert analysis["signal_availability"] == {"has_any": 2, "missing_all": 1}
    assert analysis["available_strategy_signal_counts"] == {"trend": 2, "event_sentiment": 1}
    assert analysis["top_blocked_examples"][0]["available_strategy_signals"] == []
    assert analysis["top_blocked_examples"][0]["ticker"] == "000002"
    assert analysis["recommended_focus_areas"][0]["focus_area"] == "layer_c_bearish_conflict_review"