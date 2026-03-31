from __future__ import annotations

import json

from scripts.analyze_btst_rollout_governance_board import analyze_btst_rollout_governance_board


def test_analyze_btst_rollout_governance_board_prioritizes_primary_then_recurring_shadow(tmp_path):
    action_board = tmp_path / "action_board.json"
    primary_roll = tmp_path / "primary_roll.json"
    shadow_expansion = tmp_path / "shadow_expansion.json"
    shadow_lane = tmp_path / "shadow_lane.json"
    primary_gap = tmp_path / "primary_gap.json"
    recurring_runbook = tmp_path / "recurring_runbook.json"
    primary_window_runbook = tmp_path / "primary_window_runbook.json"
    shadow_peer_scan = tmp_path / "shadow_peer_scan.json"
    structural_shadow_runbook = tmp_path / "structural_shadow_runbook.json"
    penalty_frontier = tmp_path / "penalty_frontier.json"

    action_board.write_text(
        json.dumps(
            {
                "generated_on": "2026-03-30",
                "board_rows": [
                    {
                        "ticker": "300724",
                        "action_tier": "structural_shadow_hold",
                        "next_step": "freeze 300724",
                        "next_close_return_mean": -0.0443,
                        "next_close_positive_rate": 0.0,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    primary_roll.write_text(
        json.dumps(
            {
                "roll_forward_verdict": "continue_controlled_roll_forward",
                "target_case_count": 2,
                "distinct_window_count": 1,
                "next_close_positive_rate": 1.0,
                "next_actions": ["keep 001309 primary"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    shadow_expansion.write_text(
        json.dumps(
            {
                "expansion_verdict": "hold_shadow_only_no_same_rule_expansion",
                "target_case_count": 1,
                "frontier_uniqueness": {"threshold_only_candidate_count": 1, "same_rule_expansion_ready": False},
                "next_actions": ["keep 300383 shadow"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    shadow_lane.write_text(
        json.dumps(
            {
                "lane_rows": [
                    {
                        "ticker": "002015",
                        "target_case_count": 3,
                        "next_close_positive_rate": 0.6667,
                        "next_close_return_mean": -0.0057,
                        "next_step": "validate 002015",
                    },
                    {
                        "ticker": "600821",
                        "target_case_count": 3,
                        "next_high_return_mean": 0.0503,
                        "next_close_positive_rate": 0.3333,
                        "next_step": "keep 600821 control",
                    },
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    primary_gap.write_text(
        json.dumps(
            {"missing_window_count": 1, "next_step_commands": ["find next independent window"]},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    recurring_runbook.write_text(
        json.dumps(
            {
                "close_candidate": {
                    "next_step": "validate 002015 via runbook",
                    "lane_status": "await_new_close_candidate_window",
                    "validation_verdict": "await_new_independent_window_data",
                    "distinct_window_count": 1,
                    "missing_window_count": 1,
                    "transition_locality": "emergent_local_baseline",
                },
                "intraday_control": {
                    "next_step": "keep 600821 via runbook",
                    "lane_status": "await_new_intraday_control_window",
                    "validation_verdict": "await_new_independent_window_data",
                    "distinct_window_count": 1,
                    "missing_window_count": 1,
                    "transition_locality": "emergent_local_baseline",
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    primary_window_runbook.write_text(
        json.dumps(
            {"rerun_commands": ["rerun multi-window scan"], "window_scan_rows": [{"window_key": "20260323_20260326"}]},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    shadow_peer_scan.write_text(
        json.dumps(
            {"next_actions": ["keep 300383 as single-name shadow"], "same_rule_peer_rows": []},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    structural_shadow_runbook.write_text(
        json.dumps(
            {
                "lane_status": "structural_shadow_hold_only",
                "freeze_verdict": "hold_single_name_only_quality_negative",
                "window_blocked_case_count": 5,
                "window_near_miss_rescuable_count": 1,
                "next_close_return_mean": -0.0443,
                "next_close_positive_rate": 0.0,
                "next_step": "hold 300724 structural shadow only",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    penalty_frontier.write_text(
        json.dumps(
            {
                "passing_variant_count": 0,
                "focus_tickers": ["300383", "002015", "600821"],
                "best_variant": {
                    "variant_name": "nm_0.42__avoid_0.12__stale_0.08__ext_0.02",
                    "variant_family": "penalty_coupled",
                    "guardrail_status": "fails_closed_tradeable_guardrails",
                    "closed_cycle_tradeable_count": 2,
                    "tradeable_cases": [
                        "2026-03-26:300724:near_miss",
                        "2026-03-26:300724:selected"
                    ],
                    "focus_tradeable_cases": [],
                },
                "recommendation": "当前窗口 broad penalty relief 不构成 rollout 路线。",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_rollout_governance_board(
        action_board,
        primary_roll_forward_path=primary_roll,
        shadow_expansion_path=shadow_expansion,
        shadow_lane_priority_path=shadow_lane,
        primary_window_gap_path=primary_gap,
        recurring_shadow_runbook_path=recurring_runbook,
        primary_window_validation_runbook_path=primary_window_runbook,
        shadow_peer_scan_path=shadow_peer_scan,
        structural_shadow_runbook_path=structural_shadow_runbook,
        penalty_frontier_path=penalty_frontier,
    )

    assert analysis["governance_rows"][0]["ticker"] == "001309"
    assert analysis["governance_rows"][2]["ticker"] == "002015"
    assert analysis["next_3_tasks"][0]["task_id"] == "001309_independent_window_validation"
    assert analysis["next_3_tasks"][1]["task_id"] == "002015_recurring_shadow_validation"
    assert analysis["governance_rows"][0]["next_step"] == "rerun multi-window scan"
    assert analysis["governance_rows"][2]["next_step"] == "validate 002015 via runbook"
    assert analysis["governance_rows"][2]["status"] == "await_new_close_candidate_window"
    assert analysis["governance_rows"][2]["blocker"] == "cross_window_stability_missing"
    assert analysis["governance_rows"][2]["evidence"]["distinct_window_count"] == 1
    assert analysis["governance_rows"][3]["status"] == "await_new_intraday_control_window"
    assert analysis["governance_rows"][1]["next_step"] == "keep 300383 as single-name shadow"
    assert analysis["governance_rows"][4]["status"] == "structural_shadow_hold_only"
    assert analysis["governance_rows"][4]["next_step"] == "hold 300724 structural shadow only"
    assert analysis["governance_rows"][4]["evidence"]["freeze_verdict"] == "hold_single_name_only_quality_negative"
    assert analysis["penalty_frontier_summary"]["status"] == "broad_penalty_route_closed_current_window"
    assert analysis["penalty_frontier_summary"]["best_variant_released_tickers"] == ["300724"]
    assert analysis["frontier_constraints"][0]["frontier_id"] == "broad_penalty_relief"
    assert "broad stale/extension penalty relief 已在当前窗口被证伪" in analysis["recommendation"]
