from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_tplus2_continuation_execution_overlay import (
    generate_btst_tplus2_continuation_execution_overlay,
    render_btst_tplus2_continuation_execution_overlay_markdown,
)


def test_generate_btst_tplus2_continuation_execution_overlay_applies_candidate(tmp_path: Path) -> None:
    eligible_execution_path = tmp_path / "eligible_execution.json"
    execution_gate_path = tmp_path / "execution_gate.json"

    eligible_execution_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "adopted_eligible_row": {
                    "priority_score": 2,
                    "lane_stage": "observation_only",
                    "watchlist_validation_status": "promoted_from_validation_queue",
                    "recent_supporting_window_count": 4,
                    "recent_window_count": 4,
                    "recent_support_ratio": 1.0,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0361,
                },
            }
        ),
        encoding="utf-8",
    )
    execution_gate_path.write_text(json.dumps({"focus_ticker": "300505", "gate_verdict": "approve_execution_candidate"}), encoding="utf-8")

    analysis = generate_btst_tplus2_continuation_execution_overlay(
        eligible_execution_path=eligible_execution_path,
        execution_gate_path=execution_gate_path,
    )

    assert analysis["execution_verdict"] == "execution_candidate_applied"
    assert analysis["effective_execution_candidates"] == ["300505"]
    assert analysis["adopted_execution_row"]["entry_type"] == "paper_execution_candidate"
    assert analysis["adopted_execution_row"]["promotion_blocker"] == "no_selected_persistence_or_independent_edge"
    assert analysis["adopted_execution_row"]["persistence_requirement"] == "selected_persistence_across_independent_windows"
    markdown = render_btst_tplus2_continuation_execution_overlay_markdown(analysis)
    assert "execution_candidate_applied" in markdown


def test_generate_btst_tplus2_continuation_execution_overlay_keeps_merge_review_pending_wording(tmp_path: Path) -> None:
    eligible_execution_path = tmp_path / "eligible_execution.json"
    execution_gate_path = tmp_path / "execution_gate.json"

    eligible_execution_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300720",
                "adopted_eligible_row": {
                    "priority_score": 1,
                    "lane_stage": "observation_only",
                    "promotion_blocker": "default_btst_merge_review_pending",
                    "watchlist_validation_status": "governance_followup_payoff_confirmed",
                    "recent_supporting_window_count": 5,
                    "recent_window_count": 5,
                    "recent_support_ratio": 1.0,
                    "next_close_positive_rate": 0.8,
                    "t_plus_2_close_positive_rate": 0.8667,
                    "t_plus_2_close_return_mean": 0.0787,
                },
            }
        ),
        encoding="utf-8",
    )
    execution_gate_path.write_text(json.dumps({"focus_ticker": "300720", "gate_verdict": "approve_execution_candidate"}), encoding="utf-8")

    analysis = generate_btst_tplus2_continuation_execution_overlay(
        eligible_execution_path=eligible_execution_path,
        execution_gate_path=execution_gate_path,
    )

    assert analysis["adopted_execution_row"]["promotion_blocker"] == "default_btst_merge_approved_execution_active"
    assert analysis["adopted_execution_row"]["merge_approved_daily_pipeline_active"] is True
    assert "merge-approved daily-pipeline uplift is already active" in analysis["adopted_execution_row"]["next_step"]
    assert "merge-approved daily-pipeline uplift is already active" in analysis["recommendation"]
