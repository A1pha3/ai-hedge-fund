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
