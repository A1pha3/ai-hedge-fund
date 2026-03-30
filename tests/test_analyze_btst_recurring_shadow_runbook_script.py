from __future__ import annotations

import json

from scripts.analyze_btst_recurring_shadow_runbook import analyze_btst_recurring_shadow_runbook


def test_analyze_btst_recurring_shadow_runbook_builds_close_and_control_tracks(tmp_path):
    shadow_lane = tmp_path / "shadow_lane.json"
    pair_report = tmp_path / "pair_report.json"

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

    analysis = analyze_btst_recurring_shadow_runbook(shadow_lane, recurring_pair_comparison_path=pair_report)

    assert analysis["close_candidate"]["ticker"] == "002015"
    assert analysis["intraday_control"]["ticker"] == "600821"
    assert analysis["execution_sequence"][1] == "并行把 002015 固定为 recurring shadow close 候选。"
