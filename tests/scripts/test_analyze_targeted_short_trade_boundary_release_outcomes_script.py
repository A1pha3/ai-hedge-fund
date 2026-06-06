from __future__ import annotations

import json

from scripts.analyze_targeted_short_trade_boundary_release_outcomes import analyze_targeted_short_trade_boundary_release_outcomes


def test_analyze_targeted_short_trade_boundary_release_outcomes_merges_release_and_returns(tmp_path):
    release_report = tmp_path / "release.json"
    outcome_report = tmp_path / "outcome.json"

    release_report.write_text(
        json.dumps(
            {
                "targets": ["2026-03-26:300383"],
                "changed_cases": [
                    {
                        "trade_date": "2026-03-26",
                        "ticker": "300383",
                        "before_decision": "rejected",
                        "after_decision": "near_miss",
                        "before_score_target": 0.4237,
                        "after_score_target": 0.4238,
                    }
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
                        "trade_date": "2026-03-26",
                        "ticker": "300383",
                        "next_trade_date": "2026-03-27",
                        "next_open_return": 0.0246,
                        "next_high_return": 0.0527,
                        "next_close_return": 0.0146,
                        "next_open_to_close_return": -0.0097,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_targeted_short_trade_boundary_release_outcomes(release_report, outcome_report)

    assert analysis["target_case_count"] == 1
    assert analysis["promoted_target_case_count"] == 1
    assert analysis["positive_next_close_count"] == 1
    assert analysis["target_cases"][0]["release_verdict"] == "promoted_with_positive_close"