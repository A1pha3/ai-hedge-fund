from __future__ import annotations

import json

from scripts.generate_btst_premarket_execution_card import generate_btst_premarket_execution_card_artifacts


def test_generate_btst_premarket_execution_card_creates_primary_watch_and_non_trade_sections(tmp_path):
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
                    },
                    "601869": {
                        "ticker": "601869",
                        "short_trade": {
                            "decision": "near_miss",
                            "score_target": 0.5540,
                            "confidence": 0.8667,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_catalyst_support"],
                            "top_reasons": ["trend_acceleration=0.76"],
                            "gate_status": {"score": "near_miss"},
                            "metrics_payload": {"trend_acceleration": 0.7637},
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    },
                    "002001": {
                        "ticker": "002001",
                        "research": {"decision": "selected", "score_target": 0.2912},
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3130,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                        },
                        "delta_summary": ["research target selected while short trade target stays rejected"],
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = generate_btst_premarket_execution_card_artifacts(
        input_path=report_dir,
        output_dir=tmp_path,
        trade_date="2026-03-27",
        next_trade_date="2026-03-30",
    )

    payload = json.loads((tmp_path / "btst_premarket_execution_card_20260327_for_20260330.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "btst_premarket_execution_card_20260327_for_20260330.md").read_text(encoding="utf-8")

    assert result["analysis"]["primary_action"]["ticker"] == "300757"
    assert [entry["ticker"] for entry in payload["watch_actions"]] == ["601869"]
    assert [entry["ticker"] for entry in payload["excluded_research_entries"]] == ["002001"]
    assert "# BTST Premarket Execution Card" in markdown
    assert "300757" in markdown
    assert "601869" in markdown
    assert "002001" in markdown