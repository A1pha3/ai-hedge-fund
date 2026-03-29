from __future__ import annotations

import json

from scripts.analyze_targeted_short_trade_near_miss_release_outcomes import analyze_targeted_short_trade_near_miss_release_outcomes


def test_analyze_targeted_short_trade_near_miss_release_outcomes_merges_promotion_and_returns(tmp_path):
    release_report = tmp_path / "release.json"
    outcome_report = tmp_path / "outcome.json"

    release_report.write_text(
        json.dumps(
            {
                "targets": ["2026-03-24:001309", "2026-03-25:001309"],
                "select_threshold": 0.56,
                "changed_cases": [
                    {
                        "trade_date": "2026-03-24",
                        "ticker": "001309",
                        "before_decision": "near_miss",
                        "after_decision": "selected",
                        "before_score_target": 0.5633,
                        "after_score_target": 0.5633,
                    },
                    {
                        "trade_date": "2026-03-25",
                        "ticker": "001309",
                        "before_decision": "near_miss",
                        "after_decision": "selected",
                        "before_score_target": 0.5637,
                        "after_score_target": 0.5637,
                    },
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
                    {
                        "trade_date": "2026-03-24",
                        "ticker": "001309",
                        "next_trade_date": "2026-03-25",
                        "next_open_return": 0.0152,
                        "next_high_return": 0.0811,
                        "next_close_return": 0.073,
                        "next_open_to_close_return": 0.057,
                    },
                    {
                        "trade_date": "2026-03-25",
                        "ticker": "001309",
                        "next_trade_date": "2026-03-26",
                        "next_open_return": -0.0377,
                        "next_high_return": 0.0209,
                        "next_close_return": 0.0098,
                        "next_open_to_close_return": 0.0494,
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_targeted_short_trade_near_miss_release_outcomes(release_report, outcome_report)

    assert analysis["ticker"] == "001309"
    assert analysis["target_case_count"] == 2
    assert analysis["promoted_target_case_count"] == 2
    assert analysis["next_close_positive_rate"] == 1.0
    assert analysis["target_cases"][0]["promotion_verdict"] == "selected_with_positive_close"
