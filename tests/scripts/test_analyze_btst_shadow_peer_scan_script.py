from __future__ import annotations

import json

from scripts.analyze_btst_shadow_peer_scan import analyze_btst_shadow_peer_scan


def test_analyze_btst_shadow_peer_scan_redirects_when_no_same_rule_peer(tmp_path):
    shadow_expansion = tmp_path / "shadow_expansion.json"
    frontier_report = tmp_path / "frontier_report.json"
    scoreboard_report = tmp_path / "scoreboard_report.json"

    shadow_expansion.write_text(
        json.dumps(
            {"generated_on": "2026-03-30", "frontier_uniqueness": {"threshold_only_tickers": ["300383"]}},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    frontier_report.write_text(
        json.dumps(
            {
                "minimal_near_miss_rows": [
                    {"ticker": "300383", "trade_date": "2026-03-26", "adjustment_cost": 0.04},
                    {"ticker": "002015", "trade_date": "2026-03-23", "adjustment_cost": 0.12},
                    {"ticker": "600821", "trade_date": "2026-03-23", "adjustment_cost": 0.1},
                    {"ticker": "600821", "trade_date": "2026-03-25", "adjustment_cost": 0.12},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    scoreboard_report.write_text(
        json.dumps(
            {
                "entries": [
                    {"ticker": "002015", "priority_rank": 3, "lane_type": "recurring_frontier_release"},
                    {"ticker": "600821", "priority_rank": 4, "lane_type": "recurring_frontier_release"},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_shadow_peer_scan(
        shadow_expansion,
        frontier_report_path=frontier_report,
        scoreboard_report_path=scoreboard_report,
        ticker="300383",
    )

    assert analysis["peer_scan_verdict"] == "no_same_rule_peer_redirect_to_recurring"
    assert analysis["same_rule_peer_rows"] == []
    assert [row["ticker"] for row in analysis["redirect_candidates"]] == ["600821", "002015"]
