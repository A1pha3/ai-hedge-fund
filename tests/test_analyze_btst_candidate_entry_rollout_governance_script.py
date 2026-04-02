from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_candidate_entry_rollout_governance import analyze_btst_candidate_entry_rollout_governance


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_analyze_btst_candidate_entry_rollout_governance_shadow_only(tmp_path: Path) -> None:
    frontier_path = _write_json(
        tmp_path / "btst_candidate_entry_frontier.json",
        {
            "best_variant": {
                "variant_name": "weak_structure_triplet",
                "filtered_candidate_entry_count": 1,
                "focus_filtered_tickers": ["300502"],
                "preserve_filtered_tickers": [],
                "filtered_next_high_hit_rate_at_threshold": 0.0,
                "filtered_next_close_positive_rate": 0.0,
                "evidence_tier": "window_verified_selective_rule",
                "selection_basis": "candidate_entry_frontier_priority",
            }
        },
    )
    structural_path = _write_json(
        tmp_path / "structural_validation.json",
        {
            "rows": [
                {
                    "structural_variant": "exclude_watchlist_avoid_weak_structure_entries",
                    "decision_mismatch_count": 1,
                    "released_from_blocked": ["300502"],
                    "blocked_to_near_miss": [],
                    "blocked_to_selected": [],
                    "analysis": {
                        "filtered_candidate_entry_counts": {"watchlist_avoid_boundary_weak_structure_entry": 1},
                        "candidate_entry_filter_observability": {"watchlist_avoid_boundary_weak_structure_entry": {"precondition_match_count": 3, "metric_data_pass_count": 3, "metric_threshold_match_count": 1}},
                    },
                }
            ]
        },
    )
    window_scan_path = _write_json(
        tmp_path / "window_scan.json",
        {
            "report_count": 2,
            "filtered_report_count": 1,
            "focus_hit_report_count": 1,
            "preserve_misfire_report_count": 0,
            "distinct_window_count_with_filtered_entries": 1,
            "rollout_readiness": "shadow_only_until_second_window",
            "filtered_ticker_counts": {"300502": 1},
        },
    )
    score_frontier_path = _write_json(
        tmp_path / "score_frontier.json",
        {
            "ranked_variants": [
                {"variant_name": "prepared_breakout_balance", "closed_cycle_tradeable_count": 0},
                {"variant_name": "catalyst_volume_balance", "closed_cycle_tradeable_count": 0},
            ]
        },
    )
    no_candidate_entry_action_board_path = _write_json(
        tmp_path / "btst_no_candidate_entry_action_board_latest.json",
        {
            "priority_queue": [
                {"ticker": "300720"},
                {"ticker": "003036"},
            ],
            "window_hotspot_rows": [
                {"report_dir": "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh"},
            ],
            "next_3_tasks": [
                {"task_id": "300720_no_candidate_entry_replay"},
            ],
            "recommendation": "优先围绕 300720 与 003036 回放 no_candidate_entry backlog。",
        },
    )
    no_candidate_entry_replay_bundle_path = _write_json(
        tmp_path / "btst_no_candidate_entry_replay_bundle_latest.json",
        {
            "promising_priority_tickers": ["300720"],
            "promising_hotspot_report_dirs": ["paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh"],
            "candidate_entry_status_counts": {"filters_focus_and_weaker_than_false_negative_pool": 2},
            "global_window_scan": {"rollout_readiness": "shadow_only_until_second_window"},
            "recommendation": "300720 已形成 preserve-safe recall probe，应优先接回 shadow governance。",
        },
    )
    no_candidate_entry_failure_dossier_path = _write_json(
        tmp_path / "btst_no_candidate_entry_failure_dossier_latest.json",
        {
            "priority_failure_class_counts": {"upstream_absent_from_replay_inputs": 1},
            "priority_handoff_stage_counts": {"absent_from_watchlist": 1},
            "top_upstream_absence_tickers": ["003036"],
            "top_absent_from_watchlist_tickers": ["003036"],
            "top_watchlist_visible_but_not_candidate_entry_tickers": [],
            "top_candidate_entry_visible_but_not_selection_target_tickers": [],
            "top_present_but_outside_candidate_entry_tickers": [],
            "top_candidate_entry_semantic_miss_tickers": [],
            "recommendation": "003036 在 replay input / candidate-entry source 中缺席，应先补 observability。",
        },
    )
    watchlist_recall_dossier_path = _write_json(
        tmp_path / "btst_watchlist_recall_dossier_latest.json",
        {
            "priority_recall_stage_counts": {"absent_from_candidate_pool": 1},
            "top_absent_from_candidate_pool_tickers": ["003036"],
            "top_candidate_pool_visible_but_missing_layer_b_tickers": [],
            "top_layer_b_visible_but_missing_watchlist_tickers": [],
            "recommendation": "003036 连 candidate_pool snapshot 都没有进入，应先回查 Layer A 候选池召回。",
        },
    )
    candidate_pool_recall_dossier_path = _write_json(
        tmp_path / "btst_candidate_pool_recall_dossier_latest.json",
        {
            "priority_stage_counts": {"low_avg_amount_20d": 1},
            "dominant_stage": "low_avg_amount_20d",
            "top_stage_tickers": {"low_avg_amount_20d": ["003036"]},
            "truncation_frontier_summary": {"observed_case_count": 0, "rank_observed_case_count": 0, "closest_cases": [], "min_rank_gap_to_cutoff": None, "max_rank_gap_to_cutoff": None, "avg_rank_gap_to_cutoff": None, "dominant_ranking_driver": None},
            "recommendation": "003036 在 Layer A 卡在 20 日均成交额门槛，应先检查 liquidity gate。",
        },
    )

    analysis = analyze_btst_candidate_entry_rollout_governance(
        frontier_path,
        structural_validation_path=structural_path,
        window_scan_path=window_scan_path,
        score_frontier_path=score_frontier_path,
        no_candidate_entry_action_board_path=no_candidate_entry_action_board_path,
        no_candidate_entry_replay_bundle_path=no_candidate_entry_replay_bundle_path,
        no_candidate_entry_failure_dossier_path=no_candidate_entry_failure_dossier_path,
        watchlist_recall_dossier_path=watchlist_recall_dossier_path,
        candidate_pool_recall_dossier_path=candidate_pool_recall_dossier_path,
    )

    assert analysis["candidate_entry_rule"] == "weak_structure_triplet"
    assert analysis["recommended_structural_variant"] == "exclude_watchlist_avoid_weak_structure_entries"
    assert analysis["lane_status"] == "shadow_only_until_second_window"
    assert analysis["default_upgrade_status"] == "blocked_by_single_window_candidate_entry_signal"
    assert analysis["target_window_count"] == 2
    assert analysis["missing_window_count"] == 1
    assert analysis["upgrade_gap"] == "await_new_independent_window_data"
    assert analysis["score_frontier_all_zero"] is True
    assert analysis["main_chain_validation"]["released_from_blocked"] == ["300502"]
    assert analysis["window_scan_summary"]["distinct_window_count_with_filtered_entries"] == 1
    assert analysis["no_candidate_entry_action_board_summary"]["top_priority_tickers"] == ["300720", "003036"]
    assert analysis["no_candidate_entry_action_board_summary"]["next_task_ids"] == ["300720_no_candidate_entry_replay"]
    assert analysis["no_candidate_entry_replay_bundle_summary"]["promising_priority_tickers"] == ["300720"]
    assert analysis["no_candidate_entry_failure_dossier_summary"]["top_upstream_absence_tickers"] == ["003036"]
    assert analysis["no_candidate_entry_failure_dossier_summary"]["priority_handoff_stage_counts"] == {"absent_from_watchlist": 1}
    assert analysis["no_candidate_entry_failure_dossier_summary"]["top_absent_from_watchlist_tickers"] == ["003036"]
    assert analysis["watchlist_recall_dossier_summary"]["priority_recall_stage_counts"] == {"absent_from_candidate_pool": 1}
    assert analysis["watchlist_recall_dossier_summary"]["top_absent_from_candidate_pool_tickers"] == ["003036"]
    assert analysis["candidate_pool_recall_dossier_summary"]["dominant_stage"] == "low_avg_amount_20d"
    assert analysis["candidate_pool_recall_dossier_summary"]["top_stage_tickers"] == {"low_avg_amount_20d": ["003036"]}
    assert analysis["candidate_pool_recall_dossier_summary"]["truncation_frontier_summary"]["observed_case_count"] == 0
    assert analysis["candidate_pool_recall_dossier_summary"]["dominant_ranking_driver"] is None
    assert analysis["candidate_pool_recall_dossier_summary"]["dominant_liquidity_gap_mode"] is None
    assert analysis["candidate_pool_recall_dossier_summary"]["focus_liquidity_profile_summary"] == {}
    assert analysis["candidate_pool_recall_dossier_summary"]["focus_liquidity_profiles"] == []
    assert analysis["candidate_pool_recall_dossier_summary"]["priority_handoff_branch_diagnoses"] == []
    assert analysis["candidate_pool_recall_dossier_summary"]["priority_handoff_branch_mechanisms"] == []
    assert analysis["candidate_pool_recall_dossier_summary"]["priority_handoff_branch_experiment_queue"] == []
    assert any("300720" in item for item in analysis["next_actions"])
    assert "no_candidate_entry backlog" in analysis["recommendation"]
    assert "candidate_pool snapshot 都没有进入" in analysis["recommendation"]
    assert "low_avg_amount_20d" in analysis["recommendation"]
    assert "连 watchlist 都没有进入" in analysis["recommendation"]
    assert "preserve-safe recall probe" in analysis["recommendation"]
