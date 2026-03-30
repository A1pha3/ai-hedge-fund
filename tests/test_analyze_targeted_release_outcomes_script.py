from __future__ import annotations

import json

from scripts.analyze_targeted_release_outcomes import analyze_targeted_release_outcomes


def test_analyze_targeted_release_outcomes_merges_target_cases_and_price_outcomes(tmp_path, monkeypatch):
    release_report = tmp_path / "release.json"
    release_report.write_text(
        json.dumps(
            {
                "report_dir": "data/reports/example",
                "targets": ["2026-03-25:300724"],
                "profile_overrides": {
                    "near_miss_threshold": 0.42,
                },
                "changed_non_target_case_count": 0,
                "changed_cases": [
                    {
                        "trade_date": "2026-03-25",
                        "ticker": "300724",
                        "before_decision": "blocked",
                        "after_decision": "near_miss",
                        "before_score_target": 0.3785,
                        "after_score_target": 0.4235,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_extract_next_day_outcome(ticker: str, trade_date: str, price_cache):
        assert ticker == "300724"
        assert trade_date == "2026-03-25"
        return {
            "data_status": "ok",
            "next_trade_date": "2026-03-26",
            "next_open_return": 0.0112,
            "next_high_return": 0.0345,
            "next_close_return": 0.0188,
            "next_open_to_close_return": 0.0075,
        }

    monkeypatch.setattr("scripts.analyze_targeted_release_outcomes._extract_next_day_outcome", fake_extract_next_day_outcome)

    analysis = analyze_targeted_release_outcomes(release_report)

    assert analysis["release_mode"] == "structural_conflict_release"
    assert analysis["target_case_count"] == 1
    assert analysis["promoted_target_case_count"] == 1
    assert analysis["next_close_positive_rate"] == 1.0
    assert analysis["target_cases"][0]["release_verdict"] == "promoted_with_positive_close"
    assert analysis["near_miss_threshold"] == 0.42