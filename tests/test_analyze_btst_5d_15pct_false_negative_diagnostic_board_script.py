from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_5d_15pct_false_negative_diagnostic_board import (
    analyze_btst_5d_15pct_false_negative_diagnostic_board,
    render_btst_5d_15pct_false_negative_diagnostic_board_markdown,
)


def test_analyze_btst_5d_15pct_false_negative_diagnostic_board_prioritizes_repeat_source_and_ticker(tmp_path: Path) -> None:
    input_json = tmp_path / "btst_5d_15pct_false_negative_dossier_latest.json"
    payload = {
        "rows": [
            {
                "trade_date": "2026-03-24",
                "ticker": "300383",
                "decision": "rejected",
                "candidate_source": "short_trade_boundary",
                "score_target": 0.42,
                "max_future_high_return_2_5d": 0.17,
                "time_to_hit_15pct": 3,
            },
            {
                "trade_date": "2026-03-27",
                "ticker": "300383",
                "decision": "blocked",
                "candidate_source": "short_trade_boundary",
                "score_target": 0.45,
                "max_future_high_return_2_5d": 0.19,
                "time_to_hit_15pct": 2,
            },
            {
                "trade_date": "2026-03-28",
                "ticker": "600821",
                "decision": "rejected",
                "candidate_source": "watchlist_breakout",
                "score_target": 0.39,
                "max_future_high_return_2_5d": 0.16,
                "time_to_hit_15pct": 4,
            },
        ]
    }
    input_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    analysis = analyze_btst_5d_15pct_false_negative_diagnostic_board(input_json)

    assert analysis["source_board"][0]["candidate_source"] == "short_trade_boundary"
    assert analysis["source_board"][0]["false_negative_count"] == 2
    assert analysis["source_board"][0]["repeating_ticker_count"] == 1
    assert analysis["ticker_board"][0]["ticker"] == "300383"
    assert analysis["ticker_board"][0]["false_negative_count"] == 2
    assert analysis["ticker_board"][0]["candidate_sources"] == ["short_trade_boundary"]
    assert analysis["priority_actions"][0]["focus"] in {"short_trade_boundary", "300383"}

    markdown = render_btst_5d_15pct_false_negative_diagnostic_board_markdown(analysis)
    assert "# BTST 5D / +15% False Negative Diagnostic Board" in markdown
    assert "short_trade_boundary" in markdown
    assert "300383" in markdown
