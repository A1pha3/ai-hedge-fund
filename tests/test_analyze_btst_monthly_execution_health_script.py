from __future__ import annotations

import json
from pathlib import Path

import scripts.analyze_btst_monthly_execution_health as health


def test_analyze_btst_monthly_execution_health_counts_zero_pick_days(tmp_path: Path) -> None:
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)

    # day with picks
    plan1 = reports_dir / "paper_trading_20260506_20260506_live_test_short_trade_only_20260506_plan"
    plan1.mkdir(parents=True)
    (plan1 / "session_summary.json").write_text(
        json.dumps(
            {
                "reporting_target_summary": {
                    "p2_execution_blocked_count": 1,
                    "short_trade_selected_count": 1,
                    "short_trade_near_miss_count": 2,
                    "short_trade_blocked_count": 0,
                    "short_trade_rejected_count": 3,
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (plan1 / "btst_next_day_trade_brief_latest.json").write_text(
        json.dumps(
            {
                "trade_date": "20260506",
                "next_trade_date": "20260507",
                "session_summary_path": str(plan1 / "session_summary.json"),
                "primary_entry": {"ticker": "000001"},
                "selected_entries": [],
                "near_miss_entries": [{"ticker": "000002"}],
                "summary": {"execution_blocked_candidate_count": 5},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # day with zero picks
    plan2 = reports_dir / "paper_trading_20260507_20260507_live_test_short_trade_only_20260507_plan"
    plan2.mkdir(parents=True)
    (plan2 / "session_summary.json").write_text(json.dumps({"reporting_target_summary": {}}) + "\n", encoding="utf-8")
    (plan2 / "btst_next_day_trade_brief_latest.json").write_text(
        json.dumps(
            {
                "trade_date": "20260507",
                "next_trade_date": "20260508",
                "session_summary_path": str(plan2 / "session_summary.json"),
                "primary_entry": None,
                "selected_entries": [],
                "near_miss_entries": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = health.analyze_btst_monthly_execution_health(month="202605", reports_dir=reports_dir)

    assert analysis["overall"]["day_count"] == 2
    assert analysis["overall"]["days_with_picks"] == 1
    assert analysis["overall"]["zero_pick_days"] == ["20260507"]

    md = health.render_btst_monthly_execution_health_markdown(analysis)
    assert "BTST Monthly Execution Health 202605" in md
    assert "Daily breakdown" in md
