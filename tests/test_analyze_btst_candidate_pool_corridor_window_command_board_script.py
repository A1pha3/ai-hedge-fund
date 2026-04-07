from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_candidate_pool_corridor_window_command_board import (
    analyze_btst_candidate_pool_corridor_window_command_board,
    render_btst_candidate_pool_corridor_window_command_board_markdown,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_btst_candidate_pool_corridor_window_command_board_prioritizes_near_miss_then_visibility_gap(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    manifest_path = reports_root / "report_manifest_latest.json"
    persistence_path = reports_root / "btst_candidate_pool_corridor_persistence_dossier_latest.json"
    candidate_dossier_path = reports_root / "btst_tplus2_candidate_dossier_300720_latest.json"

    _write_json(
        manifest_path,
        {
            "continuation_promotion_ready_summary": {
                "focus_ticker": "300720",
                "combined_merge_ready_evidence_trade_dates": ["2026-03-31"],
                "combined_evidence_trade_dates": ["2026-03-31", "2026-04-06"],
                "candidate_dossier_current_plan_visible_trade_dates": ["2026-03-23", "2026-03-31", "2026-04-06"],
                "candidate_dossier_current_plan_visibility_gap_trade_dates": ["2026-03-27"],
            }
        },
    )
    _write_json(
        persistence_path,
        {
            "focus_ticker": "300720",
            "continuation_readiness": {"missing_independent_sample_count": 1},
        },
    )
    _write_json(
        candidate_dossier_path,
        {
            "recent_window_summaries": [
                {
                    "report_label": "2026-03-31",
                    "decision": "selected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "score_target": 0.4583,
                    "report_dir": "/tmp/selected",
                    "downstream_bottleneck": "selected",
                },
                {
                    "report_label": "2026-04-06",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "score_target": 0.4555,
                    "report_dir": "/tmp/nearmiss",
                    "downstream_bottleneck": "catalyst_relief_validated",
                },
            ]
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_window_command_board(
        manifest_path=manifest_path,
        persistence_dossier_path=persistence_path,
    )

    assert analysis["focus_ticker"] == "300720"
    assert analysis["confirmed_selected_trade_dates"] == ["2026-03-31"]
    assert analysis["next_target_trade_dates"][:2] == ["2026-04-06", "2026-03-27"]
    assert analysis["action_rows"][0]["action_tier"] == "upgrade_near_miss_window"
    assert analysis["action_rows"][1]["action_tier"] == "recover_visibility_gap_window"

    markdown = render_btst_candidate_pool_corridor_window_command_board_markdown(analysis)
    assert "# BTST Candidate Pool Corridor Window Command Board" in markdown
    assert "collect_one_more_selected_window" in markdown
