from __future__ import annotations

import json
from pathlib import Path

import scripts.analyze_btst_candidate_pool_lane_objective_support as lane_script
from scripts.analyze_btst_candidate_pool_lane_objective_support import analyze_btst_candidate_pool_lane_objective_support


def test_analyze_btst_candidate_pool_lane_objective_support_ranks_positive_false_negative_lane(monkeypatch, tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    objective_monitor_path = tmp_path / "btst_tplus1_tplus2_objective_monitor_latest.json"
    dossier_path.write_text(
        json.dumps(
            {
                "priority_handoff_branch_experiment_queue": [
                    {
                        "task_id": "post_gate_liquidity_competition_probe",
                        "priority_handoff": "post_gate_liquidity_competition",
                        "tickers": ["301292"],
                        "prototype_type": "post_gate_competition_rebucket_probe",
                        "prototype_readiness": "shadow_ready_rebucket_signal",
                        "evaluation_summary": "rebucket lane",
                        "guardrail_summary": "no gate relief",
                    },
                    {
                        "task_id": "layer_a_liquidity_corridor_probe",
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "tickers": ["300720"],
                        "prototype_type": "upstream_base_liquidity_uplift_probe",
                        "prototype_readiness": "shadow_ready_large_gap",
                        "evaluation_summary": "corridor lane",
                        "guardrail_summary": "upstream only",
                    },
                ],
                "priority_ticker_dossiers": [
                    {
                        "ticker": "301292",
                        "failure_reason": "post-gate competition",
                        "next_step": "rebucket",
                        "truncation_liquidity_profile": {"priority_handoff": "post_gate_liquidity_competition"},
                        "occurrence_evidence": [
                            {"trade_date": "20260324", "blocking_stage": "candidate_pool_truncated_after_filters"},
                            {"trade_date": "20260325", "blocking_stage": "candidate_pool_truncated_after_filters"},
                        ],
                    },
                    {
                        "ticker": "300720",
                        "failure_reason": "corridor",
                        "next_step": "uplift",
                        "truncation_liquidity_profile": {"priority_handoff": "layer_a_liquidity_corridor"},
                        "occurrence_evidence": [
                            {"trade_date": "20260324", "blocking_stage": "candidate_pool_truncated_after_filters"},
                            {"trade_date": "20260325", "blocking_stage": "candidate_pool_truncated_after_filters"},
                        ],
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    objective_monitor_path.write_text(
        json.dumps(
            {
                "tradeable_surface": {
                    "closed_cycle_count": 4,
                    "t_plus_2_positive_rate": 0.5,
                    "t_plus_2_return_hit_rate_at_target": 0.25,
                    "mean_t_plus_2_return": 0.02,
                    "verdict": "below_strict_btst_objective",
                },
                "non_tradeable_surface": {
                    "closed_cycle_count": 8,
                    "t_plus_2_positive_rate": 0.25,
                    "t_plus_2_return_hit_rate_at_target": 0.0,
                    "mean_t_plus_2_return": -0.01,
                    "verdict": "below_strict_btst_objective",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    outcome_map = {
        ("301292", "2026-03-24"): {
            "next_high_return": 0.06,
            "next_close_return": 0.04,
            "t_plus_2_close_return": 0.07,
        },
        ("301292", "2026-03-25"): {
            "next_high_return": 0.03,
            "next_close_return": 0.02,
            "t_plus_2_close_return": 0.03,
        },
        ("300720", "2026-03-24"): {
            "next_high_return": 0.01,
            "next_close_return": -0.02,
            "t_plus_2_close_return": -0.03,
        },
        ("300720", "2026-03-25"): {
            "next_high_return": 0.015,
            "next_close_return": -0.01,
            "t_plus_2_close_return": -0.02,
        },
    }

    def _fake_extract(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], object]) -> dict[str, object]:
        payload = dict(outcome_map[(ticker, trade_date)])
        payload.update({
            "cycle_status": "closed_cycle",
            "data_status": "ok",
        })
        return payload

    monkeypatch.setattr(lane_script.btst_utils, "extract_btst_price_outcome", _fake_extract)

    analysis = analyze_btst_candidate_pool_lane_objective_support(
        dossier_path,
        objective_monitor_path=objective_monitor_path,
    )

    assert analysis["branch_rows"][0]["priority_handoff"] == "post_gate_liquidity_competition"
    assert analysis["branch_rows"][0]["support_verdict"] == "candidate_pool_false_negative_outperforms_tradeable_surface"
    assert analysis["branch_rows"][0]["mean_t_plus_2_return"] == 0.05
    assert analysis["branch_rows"][1]["support_verdict"] == "weak_post_hoc_edge"
    assert analysis["ticker_rows"][0]["ticker"] == "301292"
    assert "301292" in analysis["recommendation"]
