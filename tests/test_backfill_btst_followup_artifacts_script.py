from __future__ import annotations

import json

from scripts.backfill_btst_followup_artifacts import _discover_report_dirs
from src.paper_trading.btst_reporting import generate_and_register_btst_followup_artifacts


def test_backfill_btst_followup_artifacts_supports_report_root_discovery(tmp_path):
    report_root = tmp_path / "reports"
    report_dir = report_root / "paper_trading_window_20260327_20260327_live_m2_7_short_trade_only_20260329"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-27"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260327",
                "target_mode": "short_trade_only",
                "selection_targets": {
                    "300757": {
                        "ticker": "300757",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.5907,
                            "confidence": 0.935,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["breakout_freshness=0.94"],
                            "gate_status": {"score": "pass"},
                            "metrics_payload": {"breakout_freshness": 0.935},
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    discovered = _discover_report_dirs(report_root, "paper_trading_window_")

    assert discovered == [report_dir.resolve()]

    result = generate_and_register_btst_followup_artifacts(report_dir, trade_date="2026-03-27", next_trade_date="2026-03-30")
    assert result["brief_json"].endswith("btst_next_day_trade_brief_latest.json")
    assert result["execution_card_json"].endswith("btst_premarket_execution_card_latest.json")
    assert result["opening_watch_card_json"].endswith("btst_opening_watch_card_latest.json")
    assert result["priority_board_json"].endswith("btst_next_day_priority_board_latest.json")
    assert (report_dir / "btst_opening_watch_card_latest.json").exists()
    assert (report_dir / "btst_next_day_priority_board_latest.json").exists()

    session_summary = json.loads((report_dir / "session_summary.json").read_text(encoding="utf-8"))
    assert session_summary["btst_followup"]["brief_json"] == result["brief_json"]
    assert session_summary["btst_followup"]["execution_card_json"] == result["execution_card_json"]
    assert session_summary["btst_followup"]["opening_watch_card_json"] == result["opening_watch_card_json"]
    assert session_summary["btst_followup"]["priority_board_json"] == result["priority_board_json"]


def test_backfill_btst_followup_artifacts_registers_trade_dates_when_not_explicitly_provided(tmp_path):
    report_dir = tmp_path / "paper_trading_window_20260323_20260326_live_m2_7_20260326"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-26"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260326",
                "selection_targets": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = generate_and_register_btst_followup_artifacts(report_dir, trade_date=None, next_trade_date=None)

    session_summary = json.loads((report_dir / "session_summary.json").read_text(encoding="utf-8"))
    assert result["trade_date"] == "2026-03-26"
    assert session_summary["btst_followup"]["trade_date"] == "2026-03-26"
    assert session_summary["btst_followup"]["next_trade_date"] is not None
