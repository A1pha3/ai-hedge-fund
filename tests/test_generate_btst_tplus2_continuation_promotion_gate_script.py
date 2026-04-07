from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_tplus2_continuation_promotion_gate import (
    generate_btst_tplus2_continuation_promotion_gate,
    render_btst_tplus2_continuation_promotion_gate_markdown,
)


def test_generate_btst_tplus2_continuation_promotion_gate_approves_watchlist_promotion(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    promotion_review_path = tmp_path / "promotion_review.json"

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
    promotion_review_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "promotion_review_verdict": "watch_review_ready",
                "promotion_blockers": [],
            }
        ),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_promotion_gate(
        lane_rulepack_path=lane_rulepack_path,
        promotion_review_path=promotion_review_path,
    )

    assert analysis["focus_ticker"] == "300505"
    assert analysis["gate_verdict"] == "approve_watchlist_promotion"
    assert analysis["gate_blockers"] == []
    assert analysis["proposed_watchlist_tickers"] == ["600989", "300505"]
    assert analysis["operator_action"] == "append_focus_to_watchlist"

    markdown = render_btst_tplus2_continuation_promotion_gate_markdown(analysis)
    assert "# BTST T+2 Continuation Promotion Gate" in markdown
    assert "approve_watchlist_promotion" in markdown


def test_generate_btst_tplus2_continuation_promotion_gate_holds_when_review_is_not_ready(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    promotion_review_path = tmp_path / "promotion_review.json"

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
    promotion_review_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "promotion_review_verdict": "hold_validation_queue",
                "promotion_blockers": ["recent_tier_not_confirmed"],
            }
        ),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_promotion_gate(
        lane_rulepack_path=lane_rulepack_path,
        promotion_review_path=promotion_review_path,
    )

    assert analysis["gate_verdict"] == "hold_watchlist_promotion"
    assert "promotion_review_not_ready" in analysis["gate_blockers"]
    assert "recent_tier_not_confirmed" in analysis["gate_blockers"]
    assert analysis["proposed_watchlist_tickers"] == ["600989"]


def test_generate_btst_tplus2_continuation_promotion_gate_accepts_merge_review_ready(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    promotion_review_path = tmp_path / "promotion_review.json"

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
    promotion_review_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300720",
                "promotion_review_verdict": "ready_for_default_btst_merge_review",
                "promotion_blockers": [],
            }
        ),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_promotion_gate(
        lane_rulepack_path=lane_rulepack_path,
        promotion_review_path=promotion_review_path,
    )

    assert analysis["gate_verdict"] == "approve_watchlist_promotion"
    assert "promotion_review_not_ready" not in analysis["gate_blockers"]
    assert analysis["proposed_watchlist_tickers"] == ["600989", "300720"]
