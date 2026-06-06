from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_5d_15pct_false_negative_dossier import (
    analyze_btst_5d_15pct_false_negative_dossier,
    render_btst_5d_15pct_false_negative_dossier_markdown,
)


def test_analyze_btst_5d_15pct_false_negative_dossier_summarizes_repeating_patterns(tmp_path: Path) -> None:
    input_json = tmp_path / "btst_5d_15pct_objective_monitor_latest.json"
    payload = {
        "false_negative_strict_goal_rows": [
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

    analysis = analyze_btst_5d_15pct_false_negative_dossier(input_json)

    assert analysis["false_negative_count"] == 3
    assert analysis["decision_counts"] == {"rejected": 2, "blocked": 1}
    assert analysis["candidate_source_counts"]["short_trade_boundary"] == 2
    assert analysis["ticker_counts"]["300383"] == 2
    assert analysis["repeating_tickers"] == ["300383"]
    assert analysis["max_future_high_return_2_5d_summary"]["mean"] == 0.1733
    assert analysis["time_to_hit_15pct_summary"]["mean"] == 3.0
    assert "300383" in analysis["recommendation"]

    markdown = render_btst_5d_15pct_false_negative_dossier_markdown(analysis)
    assert "# BTST 5D / +15% False Negative Dossier" in markdown
    assert "300383" in markdown
    assert "short_trade_boundary" in markdown
