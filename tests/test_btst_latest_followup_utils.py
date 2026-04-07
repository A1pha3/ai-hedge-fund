from __future__ import annotations

import json
import os

from scripts.btst_latest_followup_utils import (
    load_latest_upstream_shadow_followup_by_ticker,
    load_latest_upstream_shadow_followup_summary,
    select_latest_btst_followup_candidate,
)


def _write_followup_report(
    report_dir,
    *,
    trade_date: str,
    selection_target: str,
    brief_payload: dict,
    mtime: int,
) -> None:
    report_dir.mkdir(parents=True)
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    brief_path.write_text(json.dumps(brief_payload, ensure_ascii=False) + "\n", encoding="utf-8")
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "end_date": trade_date,
                "plan_generation": {"selection_target": selection_target},
                "btst_followup": {
                    "trade_date": trade_date,
                    "brief_json": str(brief_path.resolve()),
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(report_dir, (mtime, mtime))


def test_select_latest_btst_followup_candidate_prefers_selected_over_larger_near_miss_report(tmp_path):
    reports_root = tmp_path / "reports"
    old_report = reports_root / "paper_trading_20260331_old_near_miss"
    new_report = reports_root / "paper_trading_20260331_new_selected"

    _write_followup_report(
        old_report,
        trade_date="2026-03-31",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720", "003036"]},
            "near_miss_entries": [
                {"ticker": "300720", "decision": "near_miss", "candidate_source": "post_gate_liquidity_competition_shadow"},
                {"ticker": "003036", "decision": "near_miss", "candidate_source": "post_gate_liquidity_competition_shadow"},
            ],
        },
        mtime=200,
    )
    _write_followup_report(
        new_report,
        trade_date="2026-03-31",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720"]},
            "selected_entries": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "historical_prior": {
                        "execution_quality_label": "balanced_confirmation",
                        "entry_timing_bias": "confirm_then_review",
                        "execution_note": "历史表现相对均衡，仍应坚持盘中确认后再决定是否持有。",
                    },
                },
            ],
        },
        mtime=100,
    )

    latest_candidate = select_latest_btst_followup_candidate(reports_root)
    latest_summary = load_latest_upstream_shadow_followup_summary(reports_root)
    latest_by_ticker = load_latest_upstream_shadow_followup_by_ticker(reports_root)

    assert latest_candidate["report_dir_name"] == "paper_trading_20260331_new_selected"
    assert latest_summary["report_dir"].endswith("paper_trading_20260331_new_selected")
    assert latest_summary["selected_tickers"] == ["300720"]
    assert latest_by_ticker["300720"]["decision"] == "selected"
    assert latest_by_ticker["300720"]["report_dir"].endswith("paper_trading_20260331_new_selected")
    assert latest_by_ticker["300720"]["historical_execution_quality_label"] == "balanced_confirmation"
    assert latest_by_ticker["300720"]["historical_entry_timing_bias"] == "confirm_then_review"
