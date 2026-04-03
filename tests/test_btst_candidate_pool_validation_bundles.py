from __future__ import annotations

import json
from pathlib import Path

from scripts.run_btst_candidate_pool_corridor_shadow_pack import analyze_btst_candidate_pool_corridor_shadow_pack
from scripts.run_btst_candidate_pool_corridor_uplift_runbook import analyze_btst_candidate_pool_corridor_uplift_runbook
from scripts.run_btst_candidate_pool_lane_pair_board import analyze_btst_candidate_pool_lane_pair_board
from scripts.run_btst_candidate_pool_upstream_handoff_board import analyze_btst_candidate_pool_upstream_handoff_board
from scripts.run_btst_candidate_pool_corridor_validation_pack import analyze_btst_candidate_pool_corridor_validation_pack
from scripts.run_btst_candidate_pool_rebucket_comparison_bundle import analyze_btst_candidate_pool_rebucket_comparison_bundle


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_rebucket_comparison_bundle_reports_parallel_ready(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    branch_priority_path = tmp_path / "btst_candidate_pool_branch_priority_board_latest.json"
    rebucket_shadow_pack_path = tmp_path / "btst_candidate_pool_rebucket_shadow_pack_latest.json"
    rebucket_validation_path = tmp_path / "btst_candidate_pool_rebucket_objective_validation_latest.json"

    _write_json(dossier_path, {"priority_stage_counts": {"candidate_pool_truncated_after_filters": 2}})
    _write_json(
        lane_support_path,
        {
            "branch_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "objective_priority_rank": 1,
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "objective_fit_score": 0.9961,
                    "mean_t_plus_2_return": 0.0804,
                    "t_plus_2_return_hit_rate_at_target": 0.72,
                    "t_plus_2_positive_rate": 0.79,
                },
                {
                    "priority_handoff": "post_gate_liquidity_competition",
                    "objective_priority_rank": 2,
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "objective_fit_score": 0.9827,
                    "mean_t_plus_2_return": 0.1098,
                    "t_plus_2_return_hit_rate_at_target": 0.69,
                    "t_plus_2_positive_rate": 0.77,
                },
            ]
        },
    )
    _write_json(
        branch_priority_path,
        {
            "priority_alignment_status": "divergent_top_lane",
            "branch_rows": [
                {
                    "priority_handoff": "post_gate_liquidity_competition",
                    "execution_priority_rank": 1,
                    "prototype_readiness": "ready_for_shadow",
                },
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "execution_priority_rank": 2,
                    "prototype_readiness": "parallel_probe",
                },
            ],
        },
    )
    _write_json(rebucket_shadow_pack_path, {"experiment": {"priority_handoff": "post_gate_liquidity_competition", "tickers": ["301292"]}})
    _write_json(
        rebucket_validation_path,
        {
            "validation_status": "advance_shadow_replay_comparison",
            "recommendation": "start comparison",
            "branch_objective_row": {
                "priority_handoff": "post_gate_liquidity_competition",
                "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                "closed_cycle_count": 13,
                "objective_fit_score": 0.9827,
                "mean_t_plus_2_return": 0.1098,
                "t_plus_2_return_hit_rate_at_target": 0.69,
                "t_plus_2_positive_rate": 0.77,
            },
        },
    )

    analysis = analyze_btst_candidate_pool_rebucket_comparison_bundle(
        dossier_path,
        lane_objective_support_path=lane_support_path,
        branch_priority_board_path=branch_priority_path,
        rebucket_shadow_pack_path=rebucket_shadow_pack_path,
        rebucket_objective_validation_path=rebucket_validation_path,
    )

    assert analysis["bundle_status"] == "ready_for_parallel_comparison"
    assert analysis["priority_alignment_status"] == "divergent_top_lane"
    assert analysis["structural_leader"]["priority_handoff"] == "post_gate_liquidity_competition"
    assert analysis["objective_leader"]["priority_handoff"] == "layer_a_liquidity_corridor"


def test_corridor_validation_pack_reports_parallel_probe_ready(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    branch_priority_path = tmp_path / "btst_candidate_pool_branch_priority_board_latest.json"

    _write_json(dossier_path, {"priority_stage_counts": {"candidate_pool_truncated_after_filters": 3}})
    _write_json(
        lane_support_path,
        {
            "branch_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "closed_cycle_count": 29,
                    "objective_fit_score": 0.9961,
                    "mean_t_plus_2_return": 0.0804,
                }
            ],
            "ticker_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "ticker": "300720",
                    "mean_t_plus_2_return": 0.0841,
                    "objective_fit_score": 0.997,
                },
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "ticker": "003036",
                    "mean_t_plus_2_return": 0.0788,
                    "objective_fit_score": 0.991,
                },
            ],
        },
    )
    _write_json(
        branch_priority_path,
        {
            "branch_rows": [
                {"priority_handoff": "layer_a_liquidity_corridor", "execution_priority_rank": 1, "prototype_readiness": "parallel_probe"}
            ],
            "corridor_ticker_rows": [
                {"ticker": "300720", "corridor_priority_rank": 1, "tractability_tier": "primary", "uplift_to_cutoff_multiple_mean": 1.2},
                {"ticker": "003036", "corridor_priority_rank": 2, "tractability_tier": "parallel", "uplift_to_cutoff_multiple_mean": 1.1},
            ],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_validation_pack(
        dossier_path,
        lane_objective_support_path=lane_support_path,
        branch_priority_board_path=branch_priority_path,
    )

    assert analysis["pack_status"] == "parallel_probe_ready"
    assert analysis["primary_validation_ticker"]["ticker"] == "300720"
    assert [row["ticker"] for row in analysis["parallel_watch_tickers"]] == ["003036"]


def test_corridor_shadow_pack_promotes_primary_shadow_replay(tmp_path: Path) -> None:
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "primary_validation_ticker": {
                "ticker": "300720",
                "validation_priority_rank": 1,
                "tractability_tier": "second_shadow_probe",
                "corridor_priority_rank": 1,
                "closed_cycle_count": 15,
                "mean_t_plus_2_return": 0.0787,
                "t_plus_2_return_hit_rate_at_target": 0.8,
                "t_plus_2_positive_rate": 0.8667,
                "objective_fit_score": 1.0,
                "uplift_to_cutoff_multiple_mean": 6.6541,
                "profile_summary": "primary corridor ticker",
            },
            "parallel_watch_tickers": [
                {
                    "ticker": "003036",
                    "validation_priority_rank": 2,
                    "tractability_tier": "upstream_research_only",
                    "corridor_priority_rank": 2,
                    "closed_cycle_count": 14,
                    "mean_t_plus_2_return": 0.0823,
                    "t_plus_2_return_hit_rate_at_target": 0.7857,
                    "t_plus_2_positive_rate": 1.0,
                    "objective_fit_score": 0.992,
                    "uplift_to_cutoff_multiple_mean": 10.691,
                    "profile_summary": "parallel corridor ticker",
                }
            ],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(corridor_validation_pack_path)

    assert analysis["shadow_status"] == "ready_for_primary_shadow_replay"
    assert analysis["primary_shadow_replay"]["ticker"] == "300720"
    assert [row["ticker"] for row in analysis["parallel_watch_lanes"]] == ["003036"]


def test_lane_pair_board_keeps_corridor_primary_first(tmp_path: Path) -> None:
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    rebucket_comparison_bundle_path = tmp_path / "btst_candidate_pool_rebucket_comparison_bundle_latest.json"
    _write_json(
        corridor_shadow_pack_path,
        {
            "shadow_status": "ready_for_primary_shadow_replay",
            "primary_shadow_replay": {
                "ticker": "300720",
                "mean_t_plus_2_return": 0.0787,
                "objective_fit_score": 1.0,
                "t_plus_2_return_hit_rate_at_target": 0.8,
                "t_plus_2_positive_rate": 0.8667,
                "tractability_tier": "second_shadow_probe",
            },
            "parallel_watch_lanes": [
                {
                    "ticker": "003036",
                    "mean_t_plus_2_return": 0.0823,
                    "objective_fit_score": 0.992,
                    "t_plus_2_return_hit_rate_at_target": 0.7857,
                    "t_plus_2_positive_rate": 1.0,
                    "tractability_tier": "upstream_research_only",
                }
            ],
        },
    )
    _write_json(
        rebucket_comparison_bundle_path,
        {
            "priority_alignment_status": "divergent_top_lane",
            "rebucket_objective_row": {
                "ticker": "301292",
                "tickers": ["301292"],
                "mean_t_plus_2_return": 0.1098,
                "objective_fit_score": 0.9827,
                "t_plus_2_return_hit_rate_at_target": 0.7692,
                "t_plus_2_positive_rate": 0.9231,
                "prototype_readiness": "shadow_ready_rebucket_signal",
            },
        },
    )

    analysis = analyze_btst_candidate_pool_lane_pair_board(
        corridor_shadow_pack_path,
        rebucket_comparison_bundle_path,
    )

    assert analysis["pair_status"] == "ready_for_ranked_comparison"
    assert analysis["board_leader"]["ticker"] == "300720"
    assert analysis["board_leader"]["lane_family"] == "corridor"


def test_upstream_handoff_board_prioritizes_watchlist_break_before_lane_probe(tmp_path: Path) -> None:
    failure_dossier_path = tmp_path / "btst_no_candidate_entry_failure_dossier_latest.json"
    watchlist_dossier_path = tmp_path / "btst_watchlist_recall_dossier_latest.json"
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"

    _write_json(
        failure_dossier_path,
        {
            "top_upstream_absence_tickers": ["300720", "301292"],
            "priority_ticker_dossiers": [
                {
                    "ticker": "300720",
                    "primary_failure_class": "upstream_absent_from_replay_inputs",
                    "handoff_stage": "absent_from_watchlist",
                    "primary_report_dir": "report_a",
                    "replay_input_visible_report_count": 0,
                    "watchlist_visible_report_count": 0,
                    "failure_reason": "missing before watchlist",
                    "next_step": "trace replay input",
                },
                {
                    "ticker": "301292",
                    "primary_failure_class": "upstream_absent_from_replay_inputs",
                    "handoff_stage": "absent_from_watchlist",
                    "primary_report_dir": "report_b",
                    "replay_input_visible_report_count": 0,
                    "watchlist_visible_report_count": 0,
                    "failure_reason": "missing before watchlist",
                    "next_step": "trace replay input",
                },
            ],
        },
    )
    _write_json(
        watchlist_dossier_path,
        {
            "focus_tickers": ["300720", "301292"],
            "priority_ticker_dossiers": [
                {"ticker": "300720", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
                {"ticker": "301292", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
            ],
        },
    )
    _write_json(
        recall_dossier_path,
        {
            "focus_tickers": ["300720", "301292"],
            "action_queue": [
                {
                    "ticker": "300720",
                    "dominant_blocking_stage": "candidate_pool_truncated_after_filters",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "min_rank_gap_to_cutoff": 878,
                        "avg_amount_share_of_cutoff_mean": 0.1573,
                        "avg_amount_share_of_min_gate_mean": 5.2437,
                        "profile_summary": "corridor profile",
                    },
                },
                {
                    "ticker": "301292",
                    "dominant_blocking_stage": "candidate_pool_truncated_after_filters",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "post_gate_liquidity_competition",
                        "min_rank_gap_to_cutoff": 309,
                        "avg_amount_share_of_cutoff_mean": 0.4421,
                        "avg_amount_share_of_min_gate_mean": 14.736,
                        "profile_summary": "rebucket profile",
                    },
                },
            ],
            "priority_handoff_branch_experiment_queue": [
                {"task_id": "corridor_probe", "tickers": ["300720"], "prototype_readiness": "shadow_ready_large_gap", "prototype_type": "upstream_base_liquidity_uplift_probe"},
                {"task_id": "rebucket_probe", "tickers": ["301292"], "prototype_readiness": "shadow_ready_rebucket_signal", "prototype_type": "post_gate_competition_rebucket_probe"},
            ],
        },
    )

    analysis = analyze_btst_candidate_pool_upstream_handoff_board(
        failure_dossier_path,
        watchlist_recall_dossier_path=watchlist_dossier_path,
        candidate_pool_recall_dossier_path=recall_dossier_path,
    )

    assert analysis["board_status"] == "ready_for_upstream_handoff_execution"
    assert analysis["board_rows"][0]["ticker"] == "300720"
    assert analysis["board_rows"][0]["first_broken_handoff"] == "absent_from_watchlist"
    assert analysis["board_rows"][0]["prototype_task_id"] == "corridor_probe"


def test_corridor_uplift_runbook_keeps_corridor_first_and_parallel_confirmatory(tmp_path: Path) -> None:
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 8.603,
                    "uplift_to_cutoff_multiple_min": 3.4211,
                    "target_cutoff_avg_amount_20d_mean": 166904.4837,
                    "prototype_summary": "run uplift probe",
                    "evaluation_summary": "measure uplift before cutoff tuning",
                    "guardrail_summary": "do not rewrite as cutoff tuning",
                    "why_now": "large liquidity wall remains",
                    "success_signal": "compress nearest frontier multiple",
                }
            ]
        },
    )
    _write_json(
        corridor_shadow_pack_path,
        {
            "primary_shadow_replay": {"ticker": "300720"},
            "parallel_watch_lanes": [{"ticker": "003036"}],
            "success_criteria": ["keep primary above tradeable surface"],
            "guardrails": ["no default cutoff tuning"],
        },
    )
    _write_json(
        lane_pair_board_path,
        {
            "board_leader": {"ticker": "300720", "lane_family": "corridor"},
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        recall_dossier_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        lane_pair_board_path=lane_pair_board_path,
    )

    assert analysis["runbook_status"] == "ready_for_upstream_uplift_probe"
    assert analysis["primary_shadow_replay"] == "300720"
    assert analysis["parallel_watch_tickers"] == ["003036"]
    assert analysis["leader_lane_family"] == "corridor"