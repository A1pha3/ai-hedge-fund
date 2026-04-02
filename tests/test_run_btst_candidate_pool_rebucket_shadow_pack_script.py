from __future__ import annotations

import json
from pathlib import Path

from scripts.run_btst_candidate_pool_rebucket_shadow_pack import run_btst_candidate_pool_rebucket_shadow_pack


def test_run_btst_candidate_pool_rebucket_shadow_pack_builds_target_pack(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    dossier_path.write_text(
        json.dumps(
            {
                "priority_handoff_branch_experiment_queue": [
                    {
                        "task_id": "post_gate_liquidity_competition_post_gate_competition_rebucket_probe",
                        "priority_handoff": "post_gate_liquidity_competition",
                        "tickers": ["301292"],
                        "prototype_type": "post_gate_competition_rebucket_probe",
                        "prototype_readiness": "shadow_ready_rebucket_signal",
                        "evaluation_summary": "top300 中存在大量 smaller-cap hot peers。",
                        "guardrail_summary": "不得直接下调 MIN_AVG_AMOUNT_20D。",
                    }
                ],
                "priority_ticker_dossiers": [
                    {
                        "ticker": "301292",
                        "failure_reason": "post-gate competition lane",
                        "next_step": "先做 rebucket shadow probe。",
                        "occurrence_evidence": [
                            {
                                "blocking_stage": "candidate_pool_truncated_after_filters",
                                "pre_truncation_avg_amount_share_of_cutoff": 0.5,
                                "top300_lower_market_cap_hot_peer_count": 2,
                                "estimated_rank_gap_after_rebucket": 338,
                                "top300_lower_market_cap_hot_peer_examples": ["300265", "002173"],
                            },
                            {
                                "blocking_stage": "candidate_pool_truncated_after_filters",
                                "pre_truncation_avg_amount_share_of_cutoff": 0.4,
                                "top300_lower_market_cap_hot_peer_count": 1,
                                "estimated_rank_gap_after_rebucket": 329,
                                "top300_lower_market_cap_hot_peer_examples": ["300189"],
                            },
                        ],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    pack = run_btst_candidate_pool_rebucket_shadow_pack(dossier_path, output_dir=tmp_path)

    assert pack["experiment"]["priority_handoff"] == "post_gate_liquidity_competition"
    assert pack["target_rows"][0]["ticker"] == "301292"
    assert pack["target_rows"][0]["uplift_to_cutoff_multiple_mean"] == 2.25
    assert pack["target_rows"][0]["top300_lower_market_cap_hot_peer_examples"] == ["300265", "002173", "300189"]
    assert Path(pack["artifacts"]["json_path"]).exists()
    assert Path(pack["artifacts"]["markdown_path"]).exists()
    assert "rebucket shadow target" in pack["recommendation"]