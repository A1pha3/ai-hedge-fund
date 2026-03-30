from __future__ import annotations

import json

from scripts.analyze_btst_primary_roll_forward import analyze_btst_primary_roll_forward


def test_analyze_btst_primary_roll_forward_requires_multi_window_evidence_for_default_upgrade(tmp_path):
    execution_summary = tmp_path / "execution_summary.json"
    candidate_report = tmp_path / "candidate_report.json"

    execution_summary.write_text(
        json.dumps(
            {
                "generated_on": "2026-03-30",
                "experiments": [
                    {
                        "ticker": "001309",
                        "action_tier": "primary_promote",
                        "target_case_count": 2,
                        "promoted_target_case_count": 2,
                        "changed_non_target_case_count": 0,
                        "next_high_return_mean": 0.051,
                        "next_close_return_mean": 0.0414,
                        "next_close_positive_rate": 1.0,
                        "release_report": "r1.json",
                        "outcome_report": "o1.json",
                    }
                ],
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
                        "short_trade_trade_date_count": 3,
                        "distinct_window_count": 1,
                        "distinct_report_count": 2,
                        "transition_locality": "emergent_local_baseline",
                        "window_keys": ["20260323_20260326"],
                        "role_counts": {"short_trade_boundary_near_miss": 3},
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_primary_roll_forward(
        execution_summary,
        candidate_report_path=candidate_report,
        ticker="001309",
    )

    assert analysis["roll_forward_verdict"] == "continue_controlled_roll_forward"
    assert analysis["default_upgrade_eligible"] is False
    assert "distinct_window_count<2，尚未形成跨窗口稳定复现证据。" in analysis["evidence_gaps"]
