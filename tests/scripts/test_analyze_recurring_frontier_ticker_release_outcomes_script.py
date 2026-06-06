from __future__ import annotations

import json

from scripts.analyze_recurring_frontier_ticker_release_outcomes import analyze_recurring_frontier_ticker_release_outcomes


def test_analyze_recurring_frontier_ticker_release_outcomes_summarizes_promoted_cases(tmp_path):
    release_report = tmp_path / "release.json"
    outcome_report = tmp_path / "outcome.json"

    release_report.write_text(
        json.dumps(
            {
                "ticker": "600821",
                "promoted_target_case_count": 2,
                "changed_cases": [
                    {"trade_date": "2026-03-23", "ticker": "600821", "before_decision": "rejected", "after_decision": "near_miss"},
                    {"trade_date": "2026-03-25", "ticker": "600821", "before_decision": "rejected", "after_decision": "near_miss"},
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    outcome_report.write_text(
        json.dumps(
            {
                "next_high_hit_threshold": 0.02,
                "rows": [
                    {"trade_date": "2026-03-23", "ticker": "600821", "next_trade_date": "2026-03-24", "next_open_return": 0.0149, "next_high_return": 0.1004, "next_close_return": 0.1004},
                    {"trade_date": "2026-03-25", "ticker": "600821", "next_trade_date": "2026-03-26", "next_open_return": -0.032, "next_high_return": 0.04, "next_close_return": -0.072},
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_recurring_frontier_ticker_release_outcomes(release_report, outcome_report)

    assert analysis["ticker"] == "600821"
    assert analysis["target_case_count"] == 2
    assert analysis["next_high_hit_rate_at_threshold"] == 1.0
    assert analysis["recommendation"]