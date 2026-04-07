from __future__ import annotations

import json

from scripts.analyze_btst_prepared_breakout_relief_validation import (
    analyze_btst_prepared_breakout_relief_validation,
    render_btst_prepared_breakout_relief_validation_markdown,
)


def test_analyze_btst_prepared_breakout_relief_validation_marks_300505_as_supported(tmp_path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir(parents=True)
    (reports_root / "btst_merge_replay_validation_latest.json").write_text(
        json.dumps(
            {
                "candidate_summaries": [
                    {
                        "focus_ticker": "300505",
                        "candidate_recommendation": "no_incremental_merge_approved_replay_uplift_observed",
                        "recommended_signal_levers": ["catalyst_freshness", "volume_expansion_quality"],
                        "prepared_breakout_selected_catalyst_relief_applied_count": 2,
                        "rows": [
                            {
                                "report_label": "window_a",
                                "report_dir": "/tmp/window_a",
                                "trade_date": "2026-03-24",
                                "baseline_replayed_decision": "selected",
                                "merge_replayed_decision": "selected",
                                "baseline_replayed_score_target": 0.6012,
                                "merge_replayed_score_target": 0.6012,
                                "required_score_uplift_to_selected": 0.0,
                                "remaining_leverage_classification": "already_selected",
                                "recommended_primary_lever": "none",
                                "prepared_breakout_penalty_relief_applied": True,
                                "prepared_breakout_catalyst_relief_applied": True,
                                "prepared_breakout_volume_relief_applied": True,
                                "prepared_breakout_continuation_relief_applied": True,
                                "prepared_breakout_selected_catalyst_relief_applied": True,
                            },
                            {
                                "report_label": "window_b",
                                "report_dir": "/tmp/window_b",
                                "trade_date": "2026-03-25",
                                "baseline_replayed_decision": "selected",
                                "merge_replayed_decision": "selected",
                                "baseline_replayed_score_target": 0.61,
                                "merge_replayed_score_target": 0.61,
                                "required_score_uplift_to_selected": 0.0,
                                "remaining_leverage_classification": "already_selected",
                                "recommended_primary_lever": "none",
                                "prepared_breakout_penalty_relief_applied": True,
                                "prepared_breakout_catalyst_relief_applied": True,
                                "prepared_breakout_volume_relief_applied": True,
                                "prepared_breakout_continuation_relief_applied": True,
                                "prepared_breakout_selected_catalyst_relief_applied": True,
                            },
                        ],
                    },
                    {
                        "focus_ticker": "300720",
                        "prepared_breakout_selected_catalyst_relief_applied_count": 0,
                        "rows": [],
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (reports_root / "btst_tplus2_candidate_dossier_300505_latest.json").write_text(
        json.dumps(
            {
                "candidate_row_count": 4,
                "recent_window_count": 4,
                "recent_validation_verdict": "recent_tier_confirmed",
                "promotion_readiness_verdict": "validation_queue_ready",
                "tier_focus_surface_summary": {
                    "next_high_hit_rate_at_threshold": 1.0,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "next_close_return_distribution": {"mean": 0.0542},
                    "t_plus_2_close_return_distribution": {"mean": 0.0361},
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_prepared_breakout_relief_validation(reports_root, focus_ticker="300505")

    assert analysis["focus_ticker"] == "300505"
    assert analysis["row_count"] == 2
    assert analysis["merge_decision_counts"] == {"selected": 2}
    assert analysis["selected_relief_window_count"] == 2
    assert analysis["selected_relief_alignment_rate"] == 1.0
    assert analysis["outcome_support"]["evidence_status"] == "strong_t1_t2_support"
    assert analysis["verdict"] == "prepared_breakout_selected_relief_supported"

    markdown = render_btst_prepared_breakout_relief_validation_markdown(analysis)
    assert "# BTST Prepared-Breakout Relief Validation" in markdown
    assert "focus_ticker: 300505" in markdown
    assert "prepared_breakout_selected_relief_supported" in markdown
