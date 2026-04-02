from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_candidate_pool_branch_priority_board import analyze_btst_candidate_pool_branch_priority_board


def test_analyze_btst_candidate_pool_branch_priority_board_prioritizes_rebucket_and_sorts_corridor(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_objective_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    dossier_path.write_text(
        json.dumps(
            {
                "priority_handoff_branch_experiment_queue": [
                    {
                        "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                        "priority_rank": 1,
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "tickers": ["003036", "300720"],
                        "prototype_type": "upstream_base_liquidity_uplift_probe",
                        "prototype_readiness": "shadow_ready_large_gap",
                        "uplift_to_cutoff_multiple_mean": 8.603,
                        "top300_lower_market_cap_hot_peer_count_mean": 3.4138,
                        "estimated_rank_gap_after_rebucket_mean": 2024.6897,
                        "evaluation_summary": "corridor 仍需大幅抬升流动性。",
                        "guardrail_summary": "不得直接讨论 cutoff 微调。",
                    },
                    {
                        "task_id": "post_gate_liquidity_competition_post_gate_competition_rebucket_probe",
                        "priority_rank": 2,
                        "priority_handoff": "post_gate_liquidity_competition",
                        "tickers": ["301292"],
                        "prototype_type": "post_gate_competition_rebucket_probe",
                        "prototype_readiness": "shadow_ready_rebucket_signal",
                        "uplift_to_cutoff_multiple_mean": 2.3035,
                        "top300_lower_market_cap_hot_peer_count_mean": 23.3846,
                        "estimated_rank_gap_after_rebucket_mean": 460.3846,
                        "evaluation_summary": "rebucket 信号已经成立。",
                        "guardrail_summary": "不得直接下调 gate。",
                    },
                ],
                "priority_ticker_dossiers": [
                    {
                        "ticker": "003036",
                        "truncation_liquidity_profile": {
                            "priority_handoff": "layer_a_liquidity_corridor",
                            "profile_summary": "003036 更接近 corridor 可救边界。",
                        },
                        "occurrence_evidence": [
                            {
                                "blocking_stage": "candidate_pool_truncated_after_filters",
                                "pre_truncation_avg_amount_share_of_cutoff": 0.29,
                                "pre_truncation_rank_gap_to_cutoff": 900,
                                "estimated_rank_gap_after_rebucket": 896,
                                "top300_lower_market_cap_hot_peer_count": 4,
                            }
                        ],
                    },
                    {
                        "ticker": "300720",
                        "truncation_liquidity_profile": {
                            "priority_handoff": "layer_a_liquidity_corridor",
                            "profile_summary": "300720 仍是更重的 corridor 样本。",
                        },
                        "occurrence_evidence": [
                            {
                                "blocking_stage": "candidate_pool_truncated_after_filters",
                                "pre_truncation_avg_amount_share_of_cutoff": 0.08,
                                "pre_truncation_rank_gap_to_cutoff": 1800,
                                "estimated_rank_gap_after_rebucket": 1795,
                                "top300_lower_market_cap_hot_peer_count": 5,
                            }
                        ],
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    lane_objective_support_path.write_text(
        json.dumps(
            {
                "branch_rows": [
                    {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                        "closed_cycle_count": 29,
                        "t_plus_2_return_hit_rate_at_target": 0.7931,
                        "mean_t_plus_2_return": 0.0804,
                    },
                    {
                        "priority_handoff": "post_gate_liquidity_competition",
                        "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                        "closed_cycle_count": 13,
                        "t_plus_2_return_hit_rate_at_target": 0.7692,
                        "mean_t_plus_2_return": 0.1098,
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    analysis = analyze_btst_candidate_pool_branch_priority_board(dossier_path, lane_objective_support_path=lane_objective_support_path)

    assert analysis["branch_rows"][0]["priority_handoff"] == "post_gate_liquidity_competition"
    assert analysis["branch_rows"][0]["execution_priority_rank"] == 1
    assert analysis["branch_rows"][0]["objective_support_rank"] == 2
    assert analysis["corridor_ticker_rows"][0]["ticker"] == "003036"
    assert analysis["corridor_ticker_rows"][0]["tractability_tier"] == "first_shadow_probe"
    assert analysis["corridor_ticker_rows"][1]["ticker"] == "300720"
    assert analysis["corridor_ticker_rows"][1]["tractability_tier"] == "upstream_research_only"
    assert analysis["priority_alignment_status"] == "divergent_top_lane"
    assert analysis["top_structural_handoff"] == "post_gate_liquidity_competition"
    assert analysis["top_objective_handoff"] == "layer_a_liquidity_corridor"
    assert "post_gate_liquidity_competition" in analysis["recommendation"]
    assert "layer_a_liquidity_corridor" in analysis["recommendation"]
