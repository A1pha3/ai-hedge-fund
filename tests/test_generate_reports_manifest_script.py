from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_reports_manifest import generate_reports_manifest_artifacts


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_generate_reports_manifest_picks_latest_btst_followup_and_curated_entries(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    reports_root = repo_root / "data" / "reports"
    docs_root = repo_root / "docs" / "zh-cn"

    (reports_root / "README.md").parent.mkdir(parents=True, exist_ok=True)
    (reports_root / "README.md").write_text("# Reports Root\n", encoding="utf-8")
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
        "btst_micro_window_regression_20260330.md",
        "btst_profile_frontier_20260330.md",
        "btst_score_construction_frontier_20260330.md",
        "btst_candidate_entry_frontier_20260330.md",
        "btst_candidate_entry_window_scan_20260330.md",
        "p9_candidate_entry_rollout_governance_20260330.md",
        "p2_top3_experiment_execution_summary_20260330.json",
        "p3_top3_post_execution_action_board_20260330.json",
        "p5_btst_rollout_governance_board_20260330.json",
        "p6_primary_window_gap_001309_20260330.json",
        "p6_recurring_shadow_runbook_20260330.json",
        "p7_primary_window_validation_runbook_001309_20260330.json",
        "p8_structural_shadow_runbook_300724_20260330.json",
    ]:
        if filename.endswith(".md"):
            (reports_root / filename).write_text(f"# {filename}\n", encoding="utf-8")
        else:
            _write_json(reports_root / filename, {"path": filename})

    older_report = reports_root / "paper_trading_20260329_20260329_live_m2_7_short_trade_only_20260329"
    older_trade_dir = older_report / "selection_artifacts" / "2026-03-29"
    older_trade_dir.mkdir(parents=True)
    older_brief_json = older_report / "btst_next_day_trade_brief_latest.json"
    older_brief_md = older_report / "btst_next_day_trade_brief_latest.md"
    older_card_json = older_report / "btst_premarket_execution_card_latest.json"
    older_card_md = older_report / "btst_premarket_execution_card_latest.md"
    _write_json(older_brief_json, {"trade_date": "2026-03-29"})
    older_brief_md.write_text("# brief\n", encoding="utf-8")
    _write_json(older_card_json, {"trade_date": "2026-03-29"})
    older_card_md.write_text("# card\n", encoding="utf-8")
    _write_json(older_trade_dir / "selection_snapshot.json", {"trade_date": "20260329"})
    _write_json(
        older_report / "session_summary.json",
        {
            "plan_generation": {"selection_target": "short_trade_only"},
            "btst_followup": {
                "trade_date": "2026-03-29",
                "next_trade_date": "2026-03-30",
                "brief_json": str(older_brief_json.resolve()),
                "brief_markdown": str(older_brief_md.resolve()),
                "execution_card_json": str(older_card_json.resolve()),
                "execution_card_markdown": str(older_card_md.resolve()),
            },
        },
    )

    latest_report = reports_root / "paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330"
    latest_trade_dir = latest_report / "selection_artifacts" / "2026-03-30"
    latest_trade_dir.mkdir(parents=True)
    latest_brief_json = latest_report / "btst_next_day_trade_brief_latest.json"
    latest_brief_md = latest_report / "btst_next_day_trade_brief_latest.md"
    latest_card_json = latest_report / "btst_premarket_execution_card_latest.json"
    latest_card_md = latest_report / "btst_premarket_execution_card_latest.md"
    latest_opening_card = latest_report / "btst_opening_watch_card_20260331.md"
    _write_json(latest_brief_json, {"trade_date": "2026-03-30", "next_trade_date": "2026-03-31"})
    latest_brief_md.write_text("# latest brief\n", encoding="utf-8")
    _write_json(latest_card_json, {"trade_date": "2026-03-30", "next_trade_date": "2026-03-31"})
    latest_card_md.write_text("# latest card\n", encoding="utf-8")
    latest_opening_card.write_text("# opening card\n", encoding="utf-8")
    _write_json(latest_trade_dir / "selection_snapshot.json", {"trade_date": "20260330"})
    _write_json(
        latest_report / "session_summary.json",
        {
            "plan_generation": {"selection_target": "short_trade_only"},
            "btst_followup": {
                "trade_date": "2026-03-30",
                "next_trade_date": "2026-03-31",
                "brief_json": str(latest_brief_json.resolve()),
                "brief_markdown": str(latest_brief_md.resolve()),
                "execution_card_json": str(latest_card_json.resolve()),
                "execution_card_markdown": str(latest_card_md.resolve()),
            },
        },
    )

    result = generate_reports_manifest_artifacts(reports_root=reports_root)
    manifest = result["manifest"]

    assert manifest["latest_btst_run"] == {
        "report_dir": "data/reports/paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330",
        "report_dir_abs": str(latest_report.resolve()),
        "selection_target": "short_trade_only",
        "trade_date": "2026-03-30",
        "next_trade_date": "2026-03-31",
    }

    entries_by_id = {entry["id"]: entry for entry in manifest["entries"]}
    assert entries_by_id["latest_btst_opening_watch_card"]["report_path"] == "data/reports/paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330/btst_opening_watch_card_20260331.md"
    assert entries_by_id["latest_btst_brief_json"]["time_scope"] == {
        "label": "latest_btst_followup",
        "trade_date": "2026-03-30",
        "next_trade_date": "2026-03-31",
    }
    assert entries_by_id["btst_micro_window_regression_review"]["report_path"] == "data/reports/btst_micro_window_regression_20260330.md"
    assert entries_by_id["btst_profile_frontier_review"]["report_path"] == "data/reports/btst_profile_frontier_20260330.md"
    assert entries_by_id["btst_score_construction_frontier_review"]["report_path"] == "data/reports/btst_score_construction_frontier_20260330.md"
    assert entries_by_id["btst_candidate_entry_frontier_review"]["report_path"] == "data/reports/btst_candidate_entry_frontier_20260330.md"
    assert entries_by_id["btst_candidate_entry_window_scan_review"]["report_path"] == "data/reports/btst_candidate_entry_window_scan_20260330.md"
    assert entries_by_id["p9_candidate_entry_rollout_governance"]["report_path"] == "data/reports/p9_candidate_entry_rollout_governance_20260330.md"
    assert entries_by_id["p5_rollout_governance_board"]["report_path"] == "data/reports/p5_btst_rollout_governance_board_20260330.json"
    assert entries_by_id["optimize0330_readme"]["report_path"] == "docs/zh-cn/factors/BTST/optimize0330/README.md"

    reading_paths = {reading_path["id"]: reading_path for reading_path in manifest["reading_paths"]}
    assert reading_paths["tomorrow_open"]["entry_ids"] == [
        "latest_btst_opening_watch_card",
        "latest_btst_execution_card_markdown",
        "latest_btst_brief_markdown",
    ]
    assert reading_paths["nightly_review"]["entry_ids"] == [
        "latest_btst_session_summary",
        "latest_btst_brief_json",
        "latest_btst_execution_card_json",
        "latest_btst_selection_snapshot",
    ]
    assert reading_paths["btst_governance"]["entry_ids"] == [
        "p2_top3_execution_summary",
        "p3_post_execution_action_board",
        "p5_rollout_governance_board",
        "btst_micro_window_regression_review",
        "btst_profile_frontier_review",
        "btst_score_construction_frontier_review",
        "btst_candidate_entry_frontier_review",
        "btst_candidate_entry_window_scan_review",
        "p9_candidate_entry_rollout_governance",
        "p6_primary_window_gap",
        "p6_recurring_shadow_runbook",
        "p7_primary_window_validation_runbook",
        "p8_structural_shadow_runbook",
    ]

    assert Path(result["json_path"]).exists()
    assert Path(result["markdown_path"]).exists()
    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "## 明天开盘" in markdown
    assert "btst_opening_watch_card_20260331.md" in markdown
    assert "btst_micro_window_regression_20260330.md" in markdown
    assert "btst_profile_frontier_20260330.md" in markdown
    assert "btst_score_construction_frontier_20260330.md" in markdown
    assert "btst_candidate_entry_frontier_20260330.md" in markdown
    assert "btst_candidate_entry_window_scan_20260330.md" in markdown
    assert "p9_candidate_entry_rollout_governance_20260330.md" in markdown