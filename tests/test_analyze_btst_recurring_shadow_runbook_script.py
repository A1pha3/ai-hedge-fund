from __future__ import annotations

import json

from scripts.analyze_btst_recurring_shadow_runbook import analyze_btst_recurring_shadow_runbook


def test_analyze_btst_recurring_shadow_runbook_builds_close_and_control_tracks(tmp_path):
    shadow_lane = tmp_path / "shadow_lane.json"
    pair_report = tmp_path / "pair_report.json"
    candidate_report = tmp_path / "candidate_report.json"
    transition_report = tmp_path / "transition_report.json"

    shadow_lane.write_text(
        json.dumps(
            {
                "lane_rows": [
                    {"ticker": "002015", "lane_role": "recurring_shadow_close_candidate", "next_step": "validate 002015"},
                    {"ticker": "600821", "lane_role": "recurring_shadow_intraday_control", "next_step": "keep 600821 control"},
                ]
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
    candidate_report.write_text(
        json.dumps(
            {
                "candidates": [
                    {"ticker": "002015", "distinct_window_count": 1, "window_keys": ["20260323_20260326"], "short_trade_trade_date_count": 3, "transition_locality": "emergent_local_baseline", "recommendation": "002015 still local."},
                    {"ticker": "600821", "distinct_window_count": 1, "window_keys": ["20260323_20260326"], "short_trade_trade_date_count": 3, "transition_locality": "emergent_local_baseline", "recommendation": "600821 still local."},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    transition_report.write_text(
        json.dumps(
            {
                "candidates": [
                    {"ticker": "002015", "transition_locality": "emergent_local_baseline", "current_window_role_count": 3, "recommendation": "002015 transition."},
                    {"ticker": "600821", "transition_locality": "emergent_local_baseline", "current_window_role_count": 3, "recommendation": "600821 transition."},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_recurring_shadow_runbook(
        shadow_lane,
        recurring_pair_comparison_path=pair_report,
        candidate_report_path=candidate_report,
        recurring_transition_report_path=transition_report,
    )

    assert analysis["close_candidate"]["ticker"] == "002015"
    assert analysis["intraday_control"]["ticker"] == "600821"
    assert analysis["execution_sequence"][1] == "并行把 002015 固定为 recurring shadow close 候选。"
    assert analysis["close_candidate"]["lane_status"] == "await_new_close_candidate_window"
    assert analysis["intraday_control"]["lane_status"] == "await_new_intraday_control_window"
    assert analysis["close_candidate"]["missing_window_count"] == 1
    assert analysis["global_validation_verdict"] == "await_new_recurring_window_evidence"
    assert analysis["rerun_commands"][0].startswith("python scripts/analyze_multi_window_short_trade_role_candidates.py")
