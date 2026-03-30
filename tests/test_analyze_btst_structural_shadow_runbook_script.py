from __future__ import annotations

import json

from scripts.analyze_btst_structural_shadow_runbook import analyze_btst_structural_shadow_runbook


def test_analyze_btst_structural_shadow_runbook_freezes_negative_post_release_case(tmp_path):
    structural_window = tmp_path / "structural_window.json"
    release_report = tmp_path / "release.json"
    outcome_report = tmp_path / "outcomes.json"

    structural_window.write_text(
        json.dumps(
            {
                "blocked_case_count": 5,
                "near_miss_rescuable_count": 1,
                "selected_rescuable_count": 0,
                "priority_queue": [
                    {
                        "trade_date": "2026-03-25",
                        "ticker": "300724",
                        "baseline_score_target": 0.3785,
                        "minimal_near_miss_adjustment_cost": 0.08,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    release_report.write_text(
        json.dumps(
            {
                "changed_non_target_case_count": 0,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    outcome_report.write_text(
        json.dumps(
            {
                "target_cases": [
                    {"trade_date": "2026-03-25", "ticker": "300724", "after_decision": "near_miss"}
                ],
                "next_high_return_mean": -0.007,
                "next_close_return_mean": -0.0443,
                "next_close_positive_rate": 0.0,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_structural_shadow_runbook(
        structural_window,
        release_report_path=release_report,
        outcome_report_path=outcome_report,
    )

    assert analysis["ticker"] == "300724"
    assert analysis["freeze_verdict"] == "hold_single_name_only_quality_negative"
    assert analysis["lane_status"] == "structural_shadow_hold_only"
    assert analysis["window_near_miss_rescuable_count"] == 1
    assert analysis["changed_non_target_case_count"] == 0
    assert analysis["priority_case"]["ticker"] == "300724"
    assert len(analysis["rerun_commands"]) == 3
