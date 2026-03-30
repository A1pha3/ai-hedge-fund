from __future__ import annotations

import json
from pathlib import Path

from scripts.run_paper_trading import generate_btst_followup_artifacts, refresh_reports_manifest


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


def test_refresh_reports_manifest_writes_latest_index_for_reports_root(tmp_path):
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260329"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-27"
    trade_dir.mkdir(parents=True)

    (reports_root / "README.md").write_text("# Reports Root\n", encoding="utf-8")
    docs_root = tmp_path / "docs" / "zh-cn"
    (docs_root / "factors" / "BTST" / "optimize0330" / "README.md").parent.mkdir(parents=True, exist_ok=True)
    (docs_root / "factors" / "BTST" / "optimize0330" / "README.md").write_text("# Optimize\n", encoding="utf-8")
    (docs_root / "factors" / "BTST" / "optimize0330" / "01-0330-research-execution-checklist.md").write_text("# Checklist\n", encoding="utf-8")
    (docs_root / "product" / "arch" / "arch_optimize_implementation.md").parent.mkdir(parents=True, exist_ok=True)
    (docs_root / "product" / "arch" / "arch_optimize_implementation.md").write_text("# Arch\n", encoding="utf-8")
    (docs_root / "manual" / "replay-artifacts-stock-selection-manual.md").parent.mkdir(parents=True, exist_ok=True)
    (docs_root / "manual" / "replay-artifacts-stock-selection-manual.md").write_text("# Manual\n", encoding="utf-8")
    (docs_root / "analysis" / "historical-edge-artifact-index-20260318.md").parent.mkdir(parents=True, exist_ok=True)
    (docs_root / "analysis" / "historical-edge-artifact-index-20260318.md").write_text("# Historical Edge\n", encoding="utf-8")

    for filename in [
        "p2_top3_experiment_execution_summary_20260330.json",
        "p3_top3_post_execution_action_board_20260330.json",
        "p5_btst_rollout_governance_board_20260330.json",
        "p6_primary_window_gap_001309_20260330.json",
        "p6_recurring_shadow_runbook_20260330.json",
        "p7_primary_window_validation_runbook_001309_20260330.json",
        "p8_structural_shadow_runbook_300724_20260330.json",
    ]:
        (reports_root / filename).write_text("{}\n", encoding="utf-8")

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

    generate_btst_followup_artifacts(report_dir, "2026-03-27", next_trade_date="2026-03-30")
    result = refresh_reports_manifest(report_dir)

    assert result is not None
    manifest = json.loads(Path(result["manifest_json"]).read_text(encoding="utf-8"))
    assert manifest["latest_btst_run"]["report_dir"] == "data/reports/paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260329"
    entry_ids = {entry["id"] for entry in manifest["entries"]}
    assert "latest_btst_brief_markdown" in entry_ids
    assert "latest_btst_execution_card_json" in entry_ids
