from __future__ import annotations

import json

from scripts.analyze_case_based_short_trade_follow_through_runbook import analyze_case_based_short_trade_follow_through_runbook


def test_analyze_case_based_short_trade_follow_through_runbook_builds_primary_shadow_control(tmp_path):
    readiness_report = tmp_path / "readiness.json"
    primary_release = tmp_path / "001309_release.json"
    shadow_release = tmp_path / "300383_release.json"
    control_release = tmp_path / "300620_release.json"

    primary_release.write_text(
        json.dumps(
            {
                "targets": ["2026-03-24:001309", "2026-03-25:001309"],
                "select_threshold": 0.56,
                "stale_weight": 0.12,
                "extension_weight": 0.08,
                "changed_cases": [{"trade_date": "2026-03-24", "ticker": "001309"}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    shadow_release.write_text(
        json.dumps(
            {
                "targets": ["2026-03-26:300383"],
                "near_miss_threshold": 0.42,
                "stale_weight": 0.12,
                "extension_weight": 0.08,
                "changed_cases": [{"trade_date": "2026-03-26", "ticker": "300383", "near_miss_threshold": 0.42}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    control_release.write_text(
        json.dumps(
            {
                "targets": ["2026-03-24:300620", "2026-03-25:300620"],
                "select_threshold": 0.53,
                "stale_weight": 0.12,
                "extension_weight": 0.08,
                "changed_cases": [{"trade_date": "2026-03-24", "ticker": "300620"}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    readiness_report.write_text(
        json.dumps(
            {
                "recommendation": "当前最应推进的 case-based 受控实验入口是 001309。",
                "entries": [
                    {
                        "ticker": "001309",
                        "lane_type": "near_miss_promotion",
                        "target_case_count": 2,
                        "adjustment_cost": 0.02,
                        "changed_non_target_case_count": 0,
                        "next_high_return_mean": 0.051,
                        "next_close_return_mean": 0.0414,
                        "next_close_positive_rate": 1.0,
                        "readiness_tier": "primary_controlled_follow_through",
                        "recommendation": "001309 已具备下一轮主实验资格。",
                        "release_report": str(primary_release),
                    },
                    {
                        "ticker": "300383",
                        "lane_type": "targeted_boundary_release",
                        "target_case_count": 1,
                        "adjustment_cost": 0.04,
                        "changed_non_target_case_count": 0,
                        "next_high_return_mean": 0.0527,
                        "next_close_return_mean": 0.0146,
                        "next_close_positive_rate": 1.0,
                        "readiness_tier": "secondary_shadow_entry",
                        "recommendation": "300383 适合作为 shadow entry 保留。",
                        "release_report": str(shadow_release),
                    },
                    {
                        "ticker": "300620",
                        "lane_type": "near_miss_promotion",
                        "target_case_count": 2,
                        "adjustment_cost": 0.05,
                        "changed_non_target_case_count": 0,
                        "next_high_return_mean": 0.0479,
                        "next_close_return_mean": -0.0014,
                        "next_close_positive_rate": 0.5,
                        "readiness_tier": "control_only",
                        "recommendation": "300620 更适合作为对照样本保留。",
                        "release_report": str(control_release),
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_case_based_short_trade_follow_through_runbook(readiness_report)

    assert analysis["primary_entry"]["ticker"] == "001309"
    assert analysis["primary_entry"]["parameter_summary"]["parameter_name"] == "select_threshold"
    assert analysis["primary_entry"]["parameter_summary"]["parameter_value"] == 0.56
    assert analysis["shadow_entry"]["ticker"] == "300383"
    assert analysis["shadow_entry"]["parameter_summary"]["parameter_name"] == "near_miss_threshold"
    assert analysis["control_entry"]["ticker"] == "300620"
    assert "001309" in analysis["execution_sequence"][0]