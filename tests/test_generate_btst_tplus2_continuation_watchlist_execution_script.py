from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_tplus2_continuation_watchlist_execution import (
    generate_btst_tplus2_continuation_watchlist_execution,
    render_btst_tplus2_continuation_watchlist_execution_markdown,
)


def test_generate_btst_tplus2_continuation_watchlist_execution_applies_watchlist_extension(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    validation_queue_path = tmp_path / "validation_queue.json"
    promotion_gate_path = tmp_path / "promotion_gate.json"

    lane_rulepack_path.write_text(
        json.dumps(
            {
                "eligible_tickers": ["600988"],
                "watchlist_tickers": ["600989"],
                "lane_rules": {
                    "lane_stage": "observation_only",
                    "capital_mode": "paper_only",
                },
            }
        ),
        encoding="utf-8",
    )
    validation_queue_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "focus_candidate": {
                    "ticker": "300505",
                    "priority_rank": 2,
                    "recent_tier_window_count": 4,
                    "recent_window_count": 4,
                    "recent_tier_ratio": 1.0,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0361,
                },
            }
        ),
        encoding="utf-8",
    )
    promotion_gate_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "gate_verdict": "approve_watchlist_promotion",
            }
        ),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_watchlist_execution(
        lane_rulepack_path=lane_rulepack_path,
        validation_queue_path=validation_queue_path,
        promotion_gate_path=promotion_gate_path,
    )

    assert analysis["execution_verdict"] == "watchlist_extension_applied"
    assert analysis["effective_watchlist_tickers"] == ["600989", "300505"]
    assert analysis["added_watchlist_tickers"] == ["300505"]
    assert analysis["adopted_watch_row"]["ticker"] == "300505"
    assert analysis["adopted_watch_row"]["entry_type"] == "promoted_validation_watch"

    markdown = render_btst_tplus2_continuation_watchlist_execution_markdown(analysis)
    assert "# BTST T+2 Continuation Watchlist Execution" in markdown
    assert "watchlist_extension_applied" in markdown


def test_generate_btst_tplus2_continuation_watchlist_execution_marks_governance_followup_watch(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    validation_queue_path = tmp_path / "validation_queue.json"
    promotion_gate_path = tmp_path / "promotion_gate.json"

    lane_rulepack_path.write_text(
        json.dumps(
            {
                "eligible_tickers": ["600988"],
                "watchlist_tickers": ["600989"],
                "lane_rules": {
                    "lane_stage": "observation_only",
                    "capital_mode": "paper_only",
                },
            }
        ),
        encoding="utf-8",
    )
    validation_queue_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300720",
                "focus_candidate": {
                    "ticker": "300720",
                    "candidate_tier_focus": "governance_followup",
                    "promotion_readiness_verdict": "watch_review_ready",
                    "recent_tier_verdict": "governance_followup_payoff_confirmed",
                    "priority_rank": 1,
                    "recent_tier_window_count": 4,
                    "recent_window_count": 4,
                    "recent_tier_ratio": 1.0,
                    "next_close_positive_rate": 0.75,
                    "t_plus_2_close_positive_rate": 0.75,
                    "t_plus_2_close_return_mean": 0.031,
                },
            }
        ),
        encoding="utf-8",
    )
    promotion_gate_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300720",
                "gate_verdict": "approve_watchlist_promotion",
            }
        ),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_watchlist_execution(
        lane_rulepack_path=lane_rulepack_path,
        validation_queue_path=validation_queue_path,
        promotion_gate_path=promotion_gate_path,
    )

    assert analysis["adopted_watch_row"]["promotion_blocker"] == "governance_approved_continuation_watch"
    assert analysis["adopted_watch_row"]["watchlist_validation_status"] == "governance_followup_payoff_confirmed"
    assert "isolated paper-only controls" in analysis["adopted_watch_row"]["next_step"]


def test_generate_btst_tplus2_continuation_watchlist_execution_surfaces_merge_review_pending(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    validation_queue_path = tmp_path / "validation_queue.json"
    promotion_gate_path = tmp_path / "promotion_gate.json"

    lane_rulepack_path.write_text(
        json.dumps({"eligible_tickers": ["600988"], "watchlist_tickers": ["600989"], "lane_rules": {"lane_stage": "observation_only", "capital_mode": "paper_only"}}),
        encoding="utf-8",
    )
    validation_queue_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300720",
                "focus_candidate": {
                    "ticker": "300720",
                    "candidate_tier_focus": "governance_followup",
                    "promotion_readiness_verdict": "merge_review_ready",
                    "recent_tier_verdict": "governance_followup_payoff_confirmed",
                    "priority_rank": 1,
                    "recent_tier_window_count": 5,
                    "recent_window_count": 5,
                    "recent_tier_ratio": 1.0,
                    "next_close_positive_rate": 0.8,
                    "t_plus_2_close_positive_rate": 0.8667,
                    "t_plus_2_close_return_mean": 0.0787,
                },
            }
        ),
        encoding="utf-8",
    )
    promotion_gate_path.write_text(
        json.dumps({"focus_ticker": "300720", "gate_verdict": "approve_watchlist_promotion", "promotion_review_verdict": "ready_for_default_btst_merge_review"}),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_watchlist_execution(
        lane_rulepack_path=lane_rulepack_path,
        validation_queue_path=validation_queue_path,
        promotion_gate_path=promotion_gate_path,
    )

    assert analysis["adopted_watch_row"]["promotion_blocker"] == "default_btst_merge_approved_execution_active"
    assert analysis["adopted_watch_row"]["merge_approved_daily_pipeline_active"] is True
    assert "merge-approved daily-pipeline uplift is already active" in analysis["adopted_watch_row"]["next_step"]
    assert "merge-approved daily-pipeline uplift is already active" in analysis["recommendation"]


def test_generate_btst_tplus2_continuation_watchlist_execution_threads_payload(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    validation_queue_path = tmp_path / "validation_queue.json"
    promotion_gate_path = tmp_path / "promotion_gate.json"

    lane_rulepack_path.write_text(
        json.dumps({"eligible_tickers": ["600988"], "watchlist_tickers": ["600989"], "lane_rules": {"lane_stage": "observation_only", "capital_mode": "paper_only"}}),
        encoding="utf-8",
    )
    validation_queue_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "focus_candidate": {
                    "ticker": "300505",
                    "priority_rank": 2,
                    "recent_tier_window_count": 4,
                    "recent_window_count": 4,
                    "recent_tier_ratio": 1.0,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0361,
                },
            }
        ),
        encoding="utf-8",
    )
    promotion_gate_path.write_text(
        json.dumps({"focus_ticker": "300505", "gate_verdict": "approve_watchlist_promotion"}),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_watchlist_execution(
        lane_rulepack_path=lane_rulepack_path,
        validation_queue_path=validation_queue_path,
        promotion_gate_path=promotion_gate_path,
    )

    assert analysis["focus_ticker"] == "300505"
    assert analysis["gate_verdict"] == "approve_watchlist_promotion"
    assert analysis["execution_verdict"] == "watchlist_extension_applied"
    assert analysis["raw_watchlist_tickers"] == ["600989"]
    assert analysis["effective_watchlist_tickers"] == ["600989", "300505"]
    assert analysis["added_watchlist_tickers"] == ["300505"]
    assert analysis["eligible_tickers"] == ["600988"]
    assert analysis["adopted_watch_row"]["ticker"] == "300505"
    assert "300505" in analysis["recommendation"]
    assert analysis["source_reports"] == {
        "lane_rulepack": str(lane_rulepack_path.expanduser().resolve()),
        "validation_queue": str(validation_queue_path.expanduser().resolve()),
        "promotion_gate": str(promotion_gate_path.expanduser().resolve()),
    }
