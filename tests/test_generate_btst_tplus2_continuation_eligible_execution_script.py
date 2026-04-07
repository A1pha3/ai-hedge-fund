from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_tplus2_continuation_eligible_execution import (
    generate_btst_tplus2_continuation_eligible_execution,
    render_btst_tplus2_continuation_eligible_execution_markdown,
)


def test_generate_btst_tplus2_continuation_eligible_execution_applies_extension(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    watchlist_execution_path = tmp_path / "watchlist_execution.json"
    eligible_gate_path = tmp_path / "eligible_gate.json"

    lane_rulepack_path.write_text(json.dumps({"eligible_tickers": ["600988"], "lane_rules": {"lane_stage": "observation_only", "capital_mode": "paper_only"}}), encoding="utf-8")
    watchlist_execution_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "adopted_watch_row": {
                    "priority_score": 2,
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
    eligible_gate_path.write_text(json.dumps({"focus_ticker": "300505", "gate_verdict": "approve_eligible_promotion"}), encoding="utf-8")

    analysis = generate_btst_tplus2_continuation_eligible_execution(
        lane_rulepack_path=lane_rulepack_path,
        watchlist_execution_path=watchlist_execution_path,
        eligible_gate_path=eligible_gate_path,
    )

    assert analysis["execution_verdict"] == "eligible_extension_applied"
    assert analysis["effective_eligible_tickers"] == ["600988", "300505"]
    assert analysis["adopted_eligible_row"]["ticker"] == "300505"
    assert analysis["adopted_eligible_row"]["entry_type"] == "promoted_watch_eligible"

    markdown = render_btst_tplus2_continuation_eligible_execution_markdown(analysis)
    assert "# BTST T+2 Continuation Eligible Execution" in markdown
    assert "eligible_extension_applied" in markdown


def test_generate_btst_tplus2_continuation_eligible_execution_keeps_merge_review_pending_wording(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    watchlist_execution_path = tmp_path / "watchlist_execution.json"
    eligible_gate_path = tmp_path / "eligible_gate.json"

    lane_rulepack_path.write_text(json.dumps({"eligible_tickers": ["600988"], "lane_rules": {"lane_stage": "observation_only", "capital_mode": "paper_only"}}), encoding="utf-8")
    watchlist_execution_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300720",
                "adopted_watch_row": {
                    "priority_score": 1,
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
    eligible_gate_path.write_text(json.dumps({"focus_ticker": "300720", "gate_verdict": "approve_eligible_promotion"}), encoding="utf-8")

    analysis = generate_btst_tplus2_continuation_eligible_execution(
        lane_rulepack_path=lane_rulepack_path,
        watchlist_execution_path=watchlist_execution_path,
        eligible_gate_path=eligible_gate_path,
    )

    assert analysis["adopted_eligible_row"]["promotion_blocker"] == "default_btst_merge_approved_execution_active"
    assert analysis["adopted_eligible_row"]["merge_approved_daily_pipeline_active"] is True
    assert "merge-approved daily-pipeline uplift is already active" in analysis["adopted_eligible_row"]["next_step"]
    assert "merge-approved daily-pipeline uplift is already active" in analysis["recommendation"]
