from __future__ import annotations

import json

from scripts.analyze_case_based_short_trade_entry_readiness import analyze_case_based_short_trade_entry_readiness


def test_analyze_case_based_short_trade_entry_readiness_orders_primary_shadow_and_control(tmp_path):
    first = tmp_path / "001309.json"
    first_release = tmp_path / "001309_release.json"
    second = tmp_path / "300383.json"
    second_release = tmp_path / "300383_release.json"
    third = tmp_path / "300620.json"
    third_release = tmp_path / "300620_release.json"

    first_release.write_text(json.dumps({"changed_non_target_case_count": 0}, ensure_ascii=False) + "\n", encoding="utf-8")
    second_release.write_text(json.dumps({"changed_non_target_case_count": 0}, ensure_ascii=False) + "\n", encoding="utf-8")
    third_release.write_text(json.dumps({"changed_non_target_case_count": 0}, ensure_ascii=False) + "\n", encoding="utf-8")

    first.write_text(
        json.dumps(
            {
                "release_report": str(first_release),
                "ticker": "001309",
                "select_threshold": 0.56,
                "target_case_count": 2,
                "promoted_target_case_count": 2,
                "next_high_return_mean": 0.051,
                "next_close_return_mean": 0.0414,
                "next_close_positive_rate": 1.0,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(
            {
                "release_report": str(second_release),
                "target_case_count": 1,
                "promoted_target_case_count": 1,
                "target_cases": [
                    {
                        "ticker": "300383",
                        "before_decision": "rejected",
                        "after_decision": "near_miss",
                        "near_miss_threshold": 0.42,
                        "next_high_return": 0.0527,
                        "next_close_return": 0.0146,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    third.write_text(
        json.dumps(
            {
                "release_report": str(third_release),
                "ticker": "300620",
                "select_threshold": 0.53,
                "target_case_count": 2,
                "promoted_target_case_count": 2,
                "next_high_return_mean": 0.0479,
                "next_close_return_mean": -0.0014,
                "next_close_positive_rate": 0.5,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_case_based_short_trade_entry_readiness([str(second), str(third), str(first)])

    assert analysis["entries"][0]["ticker"] == "001309"
    assert analysis["entries"][0]["readiness_tier"] == "primary_controlled_follow_through"
    assert analysis["entries"][1]["ticker"] == "300383"
    assert analysis["entries"][1]["readiness_tier"] == "secondary_shadow_entry"
    assert analysis["entries"][2]["ticker"] == "300620"
    assert analysis["entries"][2]["readiness_tier"] == "control_only"
    assert "001309" in analysis["recommendation"]