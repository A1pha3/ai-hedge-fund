from __future__ import annotations

import json

from scripts.analyze_btst_primary_window_gap import analyze_btst_primary_window_gap


def test_analyze_btst_primary_window_gap_reports_missing_independent_window(tmp_path):
    primary_roll = tmp_path / "primary_roll.json"
    candidate_report = tmp_path / "candidate_report.json"

    primary_roll.write_text(
        json.dumps(
            {
                "generated_on": "2026-03-30",
                "ticker": "001309",
                "distinct_window_count": 1,
                "window_keys": ["20260323_20260326"],
                "transition_locality": "emergent_local_baseline",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    candidate_report.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "ticker": "001309",
                        "window_keys": ["20260323_20260326"],
                        "transition_locality": "emergent_local_baseline",
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_primary_window_gap(primary_roll, candidate_report_path=candidate_report)

    assert analysis["missing_window_count"] == 1
    assert "至少还缺 1 个新增独立窗口，才能进入默认升级评审。" in analysis["missing_evidence"]


def test_analyze_btst_primary_window_gap_clears_missing_window_recommendation_once_two_windows_exist(tmp_path):
    primary_roll = tmp_path / "primary_roll.json"
    candidate_report = tmp_path / "candidate_report.json"

    primary_roll.write_text(
        json.dumps(
            {
                "generated_on": "2026-03-30",
                "ticker": "001309",
                "distinct_window_count": 2,
                "window_keys": ["20260323_20260326", "20260429_20260514"],
                "transition_locality": "multi_window_stable",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    candidate_report.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "ticker": "001309",
                        "window_keys": ["20260323_20260326", "20260429_20260514"],
                        "transition_locality": "multi_window_stable",
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_primary_window_gap(primary_roll, candidate_report_path=candidate_report)

    assert analysis["missing_window_count"] == 0
    assert analysis["missing_evidence"] == []
    assert "不再缺独立窗口证据" in analysis["recommendation"]
