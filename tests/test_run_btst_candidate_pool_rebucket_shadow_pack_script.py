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

    assert pack["shadow_status"] == "ready_for_rebucket_shadow_replay"
    assert pack["experiment"]["priority_handoff"] == "post_gate_liquidity_competition"
    assert pack["recommended_release_score_min"] == 0.28
    assert pack["target_rows"][0]["ticker"] == "301292"
    assert pack["target_rows"][0]["uplift_to_cutoff_multiple_mean"] == 2.25
    assert pack["target_rows"][0]["top300_lower_market_cap_hot_peer_examples"] == ["300265", "002173", "300189"]
    assert Path(pack["artifacts"]["json_path"]).exists()
    assert Path(pack["artifacts"]["markdown_path"]).exists()
    assert "rebucket shadow target" in pack["recommendation"]
    paper_trading_commands = [command for command in pack["run_commands"] if "run_paper_trading.py" in command]
    assert paper_trading_commands
    assert "--candidate-pool-shadow-rebucket-focus-tickers 301292" in paper_trading_commands[0]
    assert "--upstream-shadow-release-post-gate-rebucket-score-min 0.28" in paper_trading_commands[0]


def test_run_btst_candidate_pool_rebucket_shadow_pack_writes_skipped_placeholder_when_no_candidate(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    dossier_path.write_text(
        json.dumps(
            {
                "priority_handoff_branch_experiment_queue": [],
                "priority_ticker_dossiers": [
                    {
                        "ticker": "301292",
                        "failure_reason": "cooldown_excluded",
                        "next_step": "先核对 cooldown 规则。",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    pack = run_btst_candidate_pool_rebucket_shadow_pack(dossier_path, output_dir=tmp_path)

    assert pack["shadow_status"] == "skipped_no_rebucket_candidate"
    assert pack["experiment"] == {}
    assert pack["target_rows"] == []
    assert pack["run_commands"] == []
    assert "只保留为空位监控" in pack["recommendation"]
    markdown = Path(pack["artifacts"]["markdown_path"]).read_text(encoding="utf-8")
    assert "shadow_status: skipped_no_rebucket_candidate" in markdown
    assert "## Commands" in markdown
    assert "- none" in markdown


def test_run_btst_candidate_pool_rebucket_shadow_pack_downgrades_transient_probe_to_persistence_only(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    upstream_handoff_board_path = tmp_path / "btst_candidate_pool_upstream_handoff_board_latest.json"
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
                        "evaluation_summary": "hot peers dominate the cutoff set.",
                        "guardrail_summary": "do not relax default gates.",
                    }
                ],
                "priority_ticker_dossiers": [
                    {
                        "ticker": "301292",
                        "failure_reason": "transient rebucket probe",
                        "next_step": "repair persistence first",
                        "occurrence_evidence": [
                            {
                                "blocking_stage": "candidate_pool_truncated_after_filters",
                                "pre_truncation_avg_amount_share_of_cutoff": 0.5,
                                "top300_lower_market_cap_hot_peer_count": 2,
                                "estimated_rank_gap_after_rebucket": 338,
                                "top300_lower_market_cap_hot_peer_examples": ["300265", "002173"],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    upstream_handoff_board_path.write_text(
        json.dumps(
            {
                "board_rows": [
                    {
                        "ticker": "301292",
                        "board_phase": "historical_shadow_probe_gap",
                        "downstream_followup_status": "transient_probe_only",
                        "downstream_followup_blocker": "shadow_recall_not_persistent",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    pack = run_btst_candidate_pool_rebucket_shadow_pack(
        dossier_path,
        output_dir=tmp_path,
        upstream_handoff_board_path=upstream_handoff_board_path,
    )

    assert pack["shadow_status"] == "persistence_diagnostics_only"
    assert pack["handoff_context"]["ticker"] == "301292"
    assert pack["target_rows"][0]["ticker"] == "301292"
    assert "historical shadow probe" in pack["recommendation"]
