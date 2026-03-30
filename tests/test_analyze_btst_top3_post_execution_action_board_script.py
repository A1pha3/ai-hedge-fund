from __future__ import annotations

import json

from scripts.analyze_btst_top3_post_execution_action_board import analyze_btst_top3_post_execution_action_board


def test_analyze_btst_top3_post_execution_action_board_orders_primary_shadow_and_structural_hold(tmp_path):
    execution_summary = tmp_path / "execution_summary.json"
    readiness_report = tmp_path / "readiness.json"
    scoreboard_report = tmp_path / "scoreboard.json"
    runbook = tmp_path / "runbook.json"

    runbook.write_text(
        json.dumps(
            {
                "top_3_experiments": [
                    {"experiment_id": "001309_primary_controlled_follow_through", "objective": "primary objective", "keep_guardrails": ["g1"], "decision_rules": {"go": "go"}},
                    {"experiment_id": "300383_threshold_only_shadow_entry", "objective": "shadow objective", "keep_guardrails": ["g2"], "decision_rules": {"go": "shadow go"}},
                    {"experiment_id": "300724_structural_conflict_shadow_release", "objective": "structural objective", "keep_guardrails": ["g3"], "decision_rules": {"shadow_only": "hold"}},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    execution_summary.write_text(
        json.dumps(
            {
                "generated_on": "2026-03-30",
                "runbook": str(runbook),
                "recommendation": "优先推进 001309。300383 仅保留 shadow queue。300724 继续 structural shadow hold，不做 cluster-wide 放松。",
                "experiments": [
                    {
                        "priority_rank": 1,
                        "experiment_id": "001309_primary_controlled_follow_through",
                        "ticker": "001309",
                        "track": "case_based_near_miss_promotion",
                        "default_mode": "primary_controlled_follow_through",
                        "verdict": "go",
                        "action_tier": "primary_promote",
                        "action_summary": "primary",
                        "primary_eligible": True,
                        "next_high_return_mean": 0.051,
                        "next_close_return_mean": 0.0414,
                        "next_close_positive_rate": 1.0,
                        "changed_non_target_case_count": 0,
                        "release_report": "r1.json",
                        "outcome_report": "o1.json",
                        "cli_preview": ["cmd1"],
                    },
                    {
                        "priority_rank": 2,
                        "experiment_id": "300383_threshold_only_shadow_entry",
                        "ticker": "300383",
                        "track": "case_based_score_frontier_release",
                        "default_mode": "secondary_shadow_entry",
                        "verdict": "go",
                        "action_tier": "shadow_keep",
                        "action_summary": "shadow",
                        "primary_eligible": False,
                        "next_high_return_mean": 0.0527,
                        "next_close_return_mean": 0.0146,
                        "next_close_positive_rate": 1.0,
                        "changed_non_target_case_count": 0,
                        "release_report": "r2.json",
                        "outcome_report": "o2.json",
                        "cli_preview": ["cmd2"],
                    },
                    {
                        "priority_rank": 3,
                        "experiment_id": "300724_structural_conflict_shadow_release",
                        "ticker": "300724",
                        "track": "case_based_structural_conflict_release",
                        "default_mode": "shadow_structural_candidate",
                        "verdict": "shadow_only",
                        "action_tier": "structural_shadow_hold",
                        "action_summary": "hold",
                        "primary_eligible": False,
                        "next_high_return_mean": -0.007,
                        "next_close_return_mean": -0.0443,
                        "next_close_positive_rate": 0.0,
                        "changed_non_target_case_count": 0,
                        "release_report": "r3.json",
                        "outcome_report": "o3.json",
                        "cli_preview": ["cmd3"],
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    readiness_report.write_text(
        json.dumps(
            {
                "entries": [
                    {"ticker": "001309", "readiness_tier": "primary_controlled_follow_through"},
                    {"ticker": "300383", "readiness_tier": "secondary_shadow_entry"},
                    {"ticker": "300724", "readiness_tier": "not_ready"},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    scoreboard_report.write_text(
        json.dumps(
            {
                "entries": [
                    {"ticker": "001309", "priority_rank": 1},
                    {"ticker": "300383", "priority_rank": 2},
                    {"ticker": "300724", "priority_rank": 5},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_top3_post_execution_action_board(
        execution_summary,
        readiness_report_path=readiness_report,
        scoreboard_report_path=scoreboard_report,
    )

    assert analysis["board_rows"][0]["ticker"] == "001309"
    assert analysis["board_rows"][1]["ticker"] == "300383"
    assert analysis["board_rows"][2]["ticker"] == "300724"
    assert analysis["next_3_tasks"][0]["task_id"] == "001309_primary_follow_through_roll_forward"
    assert analysis["next_3_tasks"][1]["task_id"] == "300383_shadow_queue_hold"
    assert analysis["next_3_tasks"][2]["task_id"] == "300724_structural_shadow_freeze"