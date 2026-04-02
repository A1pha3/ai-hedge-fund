from __future__ import annotations

import json
from pathlib import Path

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