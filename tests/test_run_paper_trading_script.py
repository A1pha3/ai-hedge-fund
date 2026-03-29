from __future__ import annotations

import json
from pathlib import Path

from scripts.run_paper_trading import generate_btst_followup_artifacts


def test_generate_btst_followup_artifacts_writes_latest_brief_and_card(tmp_path):
    report_dir = tmp_path / "report"
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

    result = generate_btst_followup_artifacts(report_dir, "2026-03-27", next_trade_date="2026-03-30")

    assert Path(result["brief_json"]).name == "btst_next_day_trade_brief_latest.json"
    assert Path(result["brief_markdown"]).name == "btst_next_day_trade_brief_latest.md"
    assert Path(result["card_json"]).name == "btst_premarket_execution_card_latest.json"
    assert Path(result["card_markdown"]).name == "btst_premarket_execution_card_latest.md"
    assert Path(result["brief_json"]).exists()
    assert Path(result["card_json"]).exists()

    session_summary = json.loads((report_dir / "session_summary.json").read_text(encoding="utf-8"))
    assert session_summary["btst_followup"]["trade_date"] == "2026-03-27"
    assert session_summary["btst_followup"]["next_trade_date"] == "2026-03-30"
    assert session_summary["artifacts"]["btst_next_day_trade_brief_json"] == result["brief_json"]
    assert session_summary["artifacts"]["btst_premarket_execution_card_json"] == result["card_json"]
