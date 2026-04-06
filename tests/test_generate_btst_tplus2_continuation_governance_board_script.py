from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_tplus2_continuation_governance_board import (
    generate_btst_tplus2_continuation_governance_board,
    render_btst_tplus2_continuation_governance_board_markdown,
)


def test_generate_btst_tplus2_continuation_governance_board_single_ticker_observation_only(tmp_path: Path) -> None:
    observation_pool_path = tmp_path / "observation_pool.json"
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    lane_validation_path = tmp_path / "lane_validation.json"
    watchlist_validation_path = tmp_path / "watchlist_validation.json"
    promotion_review_path = tmp_path / "promotion_review.json"
    promotion_gate_path = tmp_path / "promotion_gate.json"

    observation_pool_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "ticker": "600988",
                        "entry_type": "anchor_cluster",
                        "priority_score": 28.55,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_mean": 0.0355,
                        "next_close_positive_rate": 0.5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
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
    lane_validation_path.write_text(
        json.dumps(
            {
                "eligible_tickers": ["600988"],
                "per_window_summaries": [
                    {"window_verdict": "supports_tplus2_lane"},
                    {"window_verdict": "mixed_or_weak"},
                ]
            }
        ),
        encoding="utf-8",
    )
    watchlist_validation_path.write_text(
        json.dumps(
            {
                "candidate_ticker": "600989",
                "recent_validation_verdict": "recent_support_confirmed",
                "recent_supporting_window_count": 3,
                "recent_window_count": 3,
                "recent_support_ratio": 1.0,
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
    promotion_gate_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "gate_verdict": "approve_watchlist_promotion",
                "gate_blockers": [],
                "operator_action": "append_focus_to_watchlist",
                "proposed_watchlist_tickers": ["600989", "300505"],
            }
        ),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_governance_board(
        observation_pool_path,
        lane_rulepack_path=lane_rulepack_path,
        lane_validation_path=lane_validation_path,
        watchlist_validation_path=watchlist_validation_path,
        promotion_review_path=promotion_review_path,
        promotion_gate_path=promotion_gate_path,
    )

    assert analysis["governance_status"] == "single_ticker_with_validation_watch"
    assert analysis["promotion_blocker"] == "near_cluster_only"
    assert analysis["validation_support_window_count"] == 1
    assert analysis["validation_mixed_window_count"] == 1
    assert analysis["watchlist_tickers"] == ["600989"]
    assert analysis["watchlist_validation_status"] == "recent_support_confirmed"
    assert analysis["recent_supporting_window_count"] == 3
    assert analysis["focus_promotion_ticker"] == "300505"
    assert analysis["focus_promotion_review_verdict"] == "watch_review_ready"
    assert analysis["focus_promotion_gate_verdict"] == "approve_watchlist_promotion"
    assert analysis["focus_promotion_gate_action"] == "append_focus_to_watchlist"
    assert analysis["focus_promotion_gate_watchlist"] == ["600989", "300505"]
    assert analysis["board_rows"][0]["ticker"] == "600988"
    assert analysis["board_rows"][0]["lane_stage"] == "observation_only"
    assert analysis["board_rows"][0]["capital_mode"] == "paper_only"
    assert analysis["board_rows"][0]["promotion_blocker"] == "near_cluster_only"
    assert analysis["board_rows"][0]["watchlist_validation_status"] is None

    markdown = render_btst_tplus2_continuation_governance_board_markdown(analysis)
    assert "# BTST T+2 Continuation Governance Board" in markdown
    assert "near_cluster_only" in markdown
    assert "recent_support_confirmed" in markdown
    assert "watch_review_ready" in markdown
    assert "approve_watchlist_promotion" in markdown
