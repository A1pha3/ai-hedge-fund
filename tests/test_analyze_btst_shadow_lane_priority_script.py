from __future__ import annotations

import json

from scripts.analyze_btst_shadow_lane_priority import analyze_btst_shadow_lane_priority


def test_analyze_btst_shadow_lane_priority_prefers_002015_as_close_candidate(tmp_path):
    shadow_board = tmp_path / "shadow_board.json"
    pair_report = tmp_path / "pair.json"
    report_002015 = tmp_path / "002015.json"
    report_600821 = tmp_path / "600821.json"

    shadow_board.write_text(
        json.dumps(
            {
                "generated_on": "2026-03-30",
                "frontier_uniqueness": {"same_rule_expansion_ready": False},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    pair_report.write_text(
        json.dumps(
            {"recommendation": "600821 更适合作为 recurring release 的 intraday 主样本，002015 更适合作为 close-continuation 对照样本。"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    report_002015.write_text(
        json.dumps(
            {
                "ticker": "002015",
                "target_case_count": 3,
                "promoted_target_case_count": 3,
                "next_high_return_mean": 0.0339,
                "next_close_return_mean": -0.0057,
                "next_close_positive_rate": 0.6667,
                "release_report": "r2.json",
                "outcome_report": "o2.json",
                "recommendation": "002015 recurring lane",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    report_600821.write_text(
        json.dumps(
            {
                "ticker": "600821",
                "target_case_count": 3,
                "promoted_target_case_count": 3,
                "next_high_return_mean": 0.0503,
                "next_close_return_mean": -0.002,
                "next_close_positive_rate": 0.3333,
                "release_report": "r6.json",
                "outcome_report": "o6.json",
                "recommendation": "600821 recurring lane",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_shadow_lane_priority(
        shadow_board,
        recurring_pair_comparison_path=pair_report,
        recurring_002015_path=report_002015,
        recurring_600821_path=report_600821,
    )

    assert analysis["expansion_constraint"] == "300383_same_rule_expansion_blocked"
    assert analysis["lane_rows"][0]["ticker"] == "002015"
    assert analysis["lane_rows"][0]["lane_role"] == "recurring_shadow_close_candidate"
    assert analysis["lane_rows"][1]["ticker"] == "600821"
