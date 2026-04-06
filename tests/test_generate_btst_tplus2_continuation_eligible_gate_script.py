from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_tplus2_continuation_eligible_gate import (
    generate_btst_tplus2_continuation_eligible_gate,
    render_btst_tplus2_continuation_eligible_gate_markdown,
)


def test_generate_btst_tplus2_continuation_eligible_gate_approves_promotion(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    lane_validation_path = tmp_path / "lane_validation.json"
    watchlist_execution_path = tmp_path / "watchlist_execution.json"
    promotion_review_path = tmp_path / "promotion_review.json"

    lane_rulepack_path.write_text(
        json.dumps(
            {
                "eligible_tickers": ["600988"],
                "lane_rules": {
                    "block_from_default_btst_tradeable_surface": True,
                },
            }
        ),
        encoding="utf-8",
    )
    lane_validation_path.write_text(
        json.dumps(
            {
                "aggregate_surface_summary": {
                    "t_plus_2_close_return_distribution": {"mean": 0.0313},
                },
                "per_window_summaries": [
                    {"window_verdict": "supports_tplus2_lane"},
                    {"window_verdict": "supports_tplus2_lane"},
                    {"window_verdict": "supports_tplus2_lane"},
                    {"window_verdict": "supports_tplus2_lane"},
                ],
            }
        ),
        encoding="utf-8",
    )
    watchlist_execution_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "execution_verdict": "watchlist_extension_applied",
                "adopted_watch_row": {
                    "ticker": "300505",
                    "recent_support_ratio": 1.0,
                    "recent_supporting_window_count": 4,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0361,
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
                "comparison_summary": {"t_plus_2_mean_gap_vs_watch": 0.0244},
            }
        ),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_eligible_gate(
        lane_rulepack_path=lane_rulepack_path,
        lane_validation_path=lane_validation_path,
        watchlist_execution_path=watchlist_execution_path,
        promotion_review_path=promotion_review_path,
    )

    assert analysis["gate_verdict"] == "approve_eligible_promotion"
    assert analysis["gate_blockers"] == []
    assert analysis["operator_action"] == "append_focus_to_eligible"

    markdown = render_btst_tplus2_continuation_eligible_gate_markdown(analysis)
    assert "# BTST T+2 Continuation Eligible Gate" in markdown
    assert "approve_eligible_promotion" in markdown


def test_generate_btst_tplus2_continuation_eligible_gate_holds_on_low_support(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    lane_validation_path = tmp_path / "lane_validation.json"
    watchlist_execution_path = tmp_path / "watchlist_execution.json"
    promotion_review_path = tmp_path / "promotion_review.json"

    lane_rulepack_path.write_text(
        json.dumps(
            {
                "eligible_tickers": ["600988"],
                "lane_rules": {
                    "block_from_default_btst_tradeable_surface": True,
                },
            }
        ),
        encoding="utf-8",
    )
    lane_validation_path.write_text(
        json.dumps(
            {
                "aggregate_surface_summary": {
                    "t_plus_2_close_return_distribution": {"mean": 0.0313},
                },
                "per_window_summaries": [
                    {"window_verdict": "supports_tplus2_lane"},
                    {"window_verdict": "mixed_or_weak"},
                ],
            }
        ),
        encoding="utf-8",
    )
    watchlist_execution_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "execution_verdict": "watchlist_extension_applied",
                "adopted_watch_row": {
                    "ticker": "300505",
                    "recent_support_ratio": 1.0,
                    "recent_supporting_window_count": 4,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0361,
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
                "comparison_summary": {"t_plus_2_mean_gap_vs_watch": 0.0244},
            }
        ),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_eligible_gate(
        lane_rulepack_path=lane_rulepack_path,
        lane_validation_path=lane_validation_path,
        watchlist_execution_path=watchlist_execution_path,
        promotion_review_path=promotion_review_path,
    )

    assert analysis["gate_verdict"] == "hold_eligible_promotion"
    assert "insufficient_lane_support_windows" in analysis["gate_blockers"] or "lane_support_ratio_too_low" in analysis["gate_blockers"]
