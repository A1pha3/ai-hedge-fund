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
    assert any("run_btst_candidate_pool_corridor_shadow_pack.py" in command for command in analysis["refresh_commands"])
    assert any("parallel_watch=003036" in command for command in analysis["shadow_replay_commands"])


def test_lane_pair_board_keeps_corridor_primary_first(tmp_path: Path) -> None:
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    rebucket_comparison_bundle_path = tmp_path / "btst_candidate_pool_rebucket_comparison_bundle_latest.json"
    governance_synthesis_path = tmp_path / "btst_governance_synthesis_latest.json"
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
    _write_json(
        governance_synthesis_path,
        {
            "execution_surface_constraints": [
                {
                    "constraint_id": "post_gate_shadow_observation_only",
                    "focus_tickers": ["300720"],
                    "status": "continuation_only_confirm_then_review",
                    "blocker": "no_selected_persistence_or_independent_edge",
                    "recommendation": "Keep post-gate shadow names in observation / continuation review until a selected row persists across independent windows.",
                },
                {
                    "constraint_id": "shadow_profitability_cliff_execution_block",
                    "focus_tickers": ["301292"],
                    "status": "shadow_recall_not_execution_ready",
                    "blocker": "profitability_hard_cliff_and_score_gap",
                    "recommendation": "Do not promote shadow recall names with profitability hard-cliff evidence into execution lanes; keep them in replay-input / shadow-governance diagnostics.",
                },
            ],
            "evidence_btst_followups": [
                {
                    "entries": [
                        {
                            "ticker": "300720",
                            "decision": "near_miss",
                            "candidate_source": "post_gate_liquidity_competition_shadow",
                            "top_reasons": [
                                "trend_acceleration=0.88",
                                "confirmed_breakout",
                            ],
                            "historical_next_close_positive_rate": 0.0,
                        },
                        {
                            "ticker": "003036",
                            "decision": "near_miss",
                            "candidate_source": "upstream_liquidity_corridor_shadow",
                            "top_reasons": [
                                "trend_acceleration=0.86",
                                "profitability_hard_cliff",
                            ],
                            "historical_sample_count": 8,
                            "historical_next_close_positive_rate": 0.125,
                            "historical_next_close_return_mean": -0.0313,
                        },
                        {
                            "ticker": "301292",
                            "decision": "rejected",
                            "candidate_source": "post_gate_liquidity_competition_shadow",
                            "top_reasons": [
                                "trend_acceleration=0.81",
                                "profitability_hard_cliff",
                            ],
                            "historical_next_close_positive_rate": None,
                        },
                    ]
                }
            ],
        },
    )

    analysis = analyze_btst_candidate_pool_lane_pair_board(
        corridor_shadow_pack_path,
        rebucket_comparison_bundle_path,
        governance_synthesis_path=governance_synthesis_path,
    )

    assert analysis["pair_status"] == "ready_for_ranked_comparison"
    assert analysis["board_leader"]["ticker"] == "300720"
    assert analysis["board_leader"]["lane_family"] == "corridor"
    rows_by_ticker = {row["ticker"]: row for row in analysis["candidates"]}
    assert rows_by_ticker["300720"]["governance_status"] == "continuation_only_confirm_then_review"
    assert rows_by_ticker["003036"]["governance_status"] == "parallel_watch_only_not_default_ready"
    assert "samples=8" in rows_by_ticker["003036"]["governance_summary"]
    assert "next_close_positive_rate=0.125" in rows_by_ticker["003036"]["governance_summary"]
    assert rows_by_ticker["301292"]["lane_family"] == "rebucket"
    assert rows_by_ticker["301292"]["governance_status"] == "shadow_recall_not_execution_ready"


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
    assert any("run_btst_candidate_pool_corridor_uplift_runbook.py" in command for command in analysis["board_rows"][0]["recommended_commands"])
    assert any("run_btst_candidate_pool_rebucket_shadow_pack.py" in command for command in analysis["board_rows"][1]["recommended_commands"])


def test_upstream_handoff_board_overlays_latest_shadow_followup_validation(tmp_path: Path) -> None:
    failure_dossier_path = tmp_path / "btst_no_candidate_entry_failure_dossier_latest.json"
    watchlist_dossier_path = tmp_path / "btst_watchlist_recall_dossier_latest.json"
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"

    _write_json(
        failure_dossier_path,
        {
            "top_upstream_absence_tickers": ["300720", "003036", "301292"],
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
                    "ticker": "003036",
                    "primary_failure_class": "upstream_absent_from_replay_inputs",
                    "handoff_stage": "absent_from_watchlist",
                    "primary_report_dir": "report_b",
                    "replay_input_visible_report_count": 0,
                    "watchlist_visible_report_count": 0,
                    "failure_reason": "missing before watchlist",
                    "next_step": "trace replay input",
                },
                {
                    "ticker": "301292",
                    "primary_failure_class": "upstream_absent_from_replay_inputs",
                    "handoff_stage": "absent_from_watchlist",
                    "primary_report_dir": "report_c",
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
            "focus_tickers": ["300720", "003036", "301292"],
            "priority_ticker_dossiers": [
                {"ticker": "300720", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
                {"ticker": "003036", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
                {"ticker": "301292", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
            ],
        },
    )
    _write_json(
        recall_dossier_path,
        {
            "focus_tickers": ["300720", "003036", "301292"],
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
                    "ticker": "003036",
                    "dominant_blocking_stage": "candidate_pool_truncated_after_filters",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "min_rank_gap_to_cutoff": 644,
                        "avg_amount_share_of_cutoff_mean": 0.2214,
                        "avg_amount_share_of_min_gate_mean": 4.8831,
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
                {"task_id": "corridor_probe", "tickers": ["300720", "003036"], "prototype_readiness": "shadow_ready_large_gap", "prototype_type": "upstream_base_liquidity_uplift_probe"},
                {"task_id": "rebucket_probe", "tickers": ["301292"], "prototype_readiness": "shadow_ready_rebucket_signal", "prototype_type": "post_gate_competition_rebucket_probe"},
            ],
        },
    )

    followup_report_dir = tmp_path / "paper_trading_20260331_20260331_live_m2_7_short_trade_only_shadow_followup"
    followup_report_dir.mkdir(parents=True, exist_ok=True)
    followup_brief_path = followup_report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        followup_brief_path,
        {
            "upstream_shadow_recall_summary": {"top_focus_tickers": ["300720", "003036"]},
            "priority_rows": [
                {
                    "ticker": "300720",
                    "decision": "near_miss",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "positive_tags": ["upstream_shadow_catalyst_relief_applied"],
                    "top_reasons": ["upstream_shadow_catalyst_relief"],
                },
                {
                    "ticker": "003036",
                    "decision": "rejected",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "top_reasons": ["profitability_hard_cliff"],
                },
            ],
        },
    )
    _write_json(
        followup_report_dir / "session_summary.json",
        {
            "plan_generation": {"selection_target": "short_trade_only"},
            "btst_followup": {
                "trade_date": "2026-03-31",
                "brief_json": str(followup_brief_path.resolve()),
            },
        },
    )

    rebucket_report_dir = tmp_path / "paper_trading_20260324_20260326_live_m2_7_short_trade_only_rebucket_shadow_301292"
    rebucket_report_dir.mkdir(parents=True, exist_ok=True)
    rebucket_brief_path = rebucket_report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        rebucket_brief_path,
        {
            "upstream_shadow_recall_summary": {"top_focus_tickers": ["301292"]},
            "priority_rows": [
                {
                    "ticker": "301292",
                    "decision": "rejected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "positive_tags": ["upstream_shadow_release_candidate"],
                    "top_reasons": ["profitability_hard_cliff", "score_short_below_threshold"],
                }
            ],
        },
    )
    _write_json(
        rebucket_report_dir / "session_summary.json",
        {
            "plan_generation": {"selection_target": "short_trade_only"},
            "btst_followup": {
                "trade_date": "2026-03-24",
                "brief_json": str(rebucket_brief_path.resolve()),
            },
        },
    )

    analysis = analyze_btst_candidate_pool_upstream_handoff_board(
        failure_dossier_path,
        watchlist_recall_dossier_path=watchlist_dossier_path,
        candidate_pool_recall_dossier_path=recall_dossier_path,
    )

    rows_by_ticker = {row["ticker"]: row for row in analysis["board_rows"]}
    assert analysis["board_status"] == "mixed_upstream_and_post_recall_followup"
    assert rows_by_ticker["300720"]["board_phase"] == "post_recall_downstream_followup"
    assert rows_by_ticker["300720"]["first_broken_handoff"] == "downstream_validated_after_shadow_recall"
    assert rows_by_ticker["300720"]["latest_followup_decision"] == "near_miss"
    assert rows_by_ticker["300720"]["downstream_followup_lane"] == "t_plus_2_continuation_review"
    assert rows_by_ticker["300720"]["downstream_followup_status"] == "continuation_confirm_then_review"
    assert rows_by_ticker["003036"]["latest_followup_downstream_bottleneck"] == "profitability_hard_cliff"
    assert rows_by_ticker["003036"]["downstream_followup_lane"] == "shadow_profitability_diagnostics"
    assert rows_by_ticker["301292"]["board_phase"] == "historical_shadow_probe_gap"
    assert rows_by_ticker["301292"]["first_broken_handoff"] == "transient_shadow_recall_without_persistence"
    assert rows_by_ticker["301292"]["latest_followup_decision"] == "rejected"
    assert rows_by_ticker["301292"]["downstream_followup_lane"] == "rebucket_persistence_diagnostics"
    assert rows_by_ticker["301292"]["downstream_followup_status"] == "transient_probe_only"
    assert rows_by_ticker["301292"]["downstream_followup_blocker"] == "shadow_recall_not_persistent"
    assert "301292" in analysis["recommendation"]


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
    assert any("run_btst_candidate_pool_lane_pair_board.py" in command for command in analysis["execution_commands"])
    paper_trading_commands = [command for command in analysis["execution_commands"] if "run_paper_trading.py" in command]
    assert paper_trading_commands
    assert "--candidate-pool-shadow-focus-tickers 300720,003036" in paper_trading_commands[0]
    assert "--candidate-pool-shadow-corridor-focus-tickers 300720,003036" in paper_trading_commands[0]
