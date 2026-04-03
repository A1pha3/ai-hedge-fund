from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

import scripts.run_paper_trading as run_paper_trading_script
from scripts.run_paper_trading import generate_btst_followup_artifacts, refresh_btst_nightly_control_tower, refresh_reports_manifest


def test_main_applies_shadow_env_before_runtime_import(monkeypatch, tmp_path, capsys) -> None:
    output_dir = tmp_path / "paper_trading"
    args = argparse.Namespace(
        start_date="2026-03-31",
        end_date="2026-03-31",
        tickers="",
        initial_capital=100000.0,
        model_name="MiniMax-M2.7",
        model_provider="MiniMax",
        selection_target="research_only",
        output_dir=str(output_dir),
        frozen_plan_source=None,
        cache_benchmark=False,
        cache_benchmark_ticker=None,
        cache_benchmark_clear_first=False,
        candidate_pool_shadow_focus_tickers=None,
        candidate_pool_shadow_corridor_focus_tickers=None,
        candidate_pool_shadow_rebucket_focus_tickers="301292",
        upstream_shadow_release_liquidity_corridor_score_min=None,
        upstream_shadow_release_post_gate_rebucket_score_min=0.28,
    )
    monkeypatch.setattr(run_paper_trading_script, "parse_args", lambda: args)
    monkeypatch.delenv("CANDIDATE_POOL_SHADOW_FOCUS_REBUCKET_TICKERS", raising=False)
    monkeypatch.delenv("DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_POST_GATE_REBUCKET_SCORE_MIN", raising=False)

    runtime_import_checked = {"done": False}

    def fake_import_module(name: str):
        if name == "scripts.model_selection":
            return SimpleNamespace(resolve_model_selection=lambda model_name, model_provider: (model_name, model_provider))
        if name == "src.paper_trading.runtime":
            assert os.environ["CANDIDATE_POOL_SHADOW_FOCUS_REBUCKET_TICKERS"] == "301292"
            assert os.environ["DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_POST_GATE_REBUCKET_SCORE_MIN"] == "0.28"
            runtime_import_checked["done"] = True
            return SimpleNamespace(
                run_paper_trading_session=lambda **kwargs: SimpleNamespace(
                    output_dir=Path(kwargs["output_dir"]),
                    daily_events_path=Path(kwargs["output_dir"]) / "daily_events.jsonl",
                    timing_log_path=Path(kwargs["output_dir"]) / "pipeline_timings.jsonl",
                    summary_path=Path(kwargs["output_dir"]) / "session_summary.json",
                )
            )
        raise AssertionError(f"Unexpected module import: {name}")

    monkeypatch.setattr(run_paper_trading_script.importlib, "import_module", fake_import_module)

    run_paper_trading_script.main()

    stdout = capsys.readouterr().out
    assert runtime_import_checked["done"] is True
    assert f"paper_trading_output_dir={output_dir}" in stdout


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
    assert Path(result["opening_card_json"]).name == "btst_opening_watch_card_20260330.json"
    assert Path(result["opening_card_markdown"]).name == "btst_opening_watch_card_20260330.md"
    assert Path(result["priority_board_json"]).name == "btst_next_day_priority_board_20260330.json"
    assert Path(result["priority_board_markdown"]).name == "btst_next_day_priority_board_20260330.md"
    assert Path(result["brief_json"]).exists()
    assert Path(result["card_json"]).exists()
    assert Path(result["opening_card_markdown"]).exists()
    assert Path(result["priority_board_markdown"]).exists()

    session_summary = json.loads((report_dir / "session_summary.json").read_text(encoding="utf-8"))
    assert session_summary["btst_followup"]["trade_date"] == "2026-03-27"
    assert session_summary["btst_followup"]["next_trade_date"] == "2026-03-30"
    assert session_summary["artifacts"]["btst_next_day_trade_brief_json"] == result["brief_json"]
    assert session_summary["artifacts"]["btst_premarket_execution_card_json"] == result["card_json"]
    assert session_summary["artifacts"]["btst_opening_watch_card_markdown"] == result["opening_card_markdown"]
    assert session_summary["artifacts"]["btst_next_day_priority_board_markdown"] == result["priority_board_markdown"]


def test_generate_btst_followup_artifacts_refreshes_manifest_before_generation(monkeypatch, tmp_path):
    report_dir = tmp_path / "data" / "reports" / "paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260329"
    report_dir.mkdir(parents=True)

    calls: list[str] = []

    def _fake_refresh(report_dir_arg):
        assert Path(report_dir_arg) == report_dir
        calls.append("manifest")
        return {"manifest_json": "manifest.json", "manifest_markdown": "manifest.md"}

    def _fake_generate(report_dir, trade_date, next_trade_date=None):
        calls.append("followup")
        assert calls == ["manifest", "followup"]
        assert trade_date == "2026-03-27"
        assert next_trade_date == "2026-03-30"
        return {
            "brief_json": "brief.json",
            "brief_markdown": "brief.md",
            "execution_card_json": "card.json",
            "execution_card_markdown": "card.md",
            "opening_watch_card_json": "opening.json",
            "opening_watch_card_markdown": "opening.md",
            "priority_board_json": "priority.json",
            "priority_board_markdown": "priority.md",
        }

    monkeypatch.setattr("scripts.run_paper_trading.refresh_reports_manifest", _fake_refresh)

    def _fake_import_module(name: str):
        if name == "src.paper_trading.btst_reporting":
            return SimpleNamespace(generate_and_register_btst_followup_artifacts=_fake_generate)
        raise AssertionError(f"Unexpected module import: {name}")

    monkeypatch.setattr(run_paper_trading_script.importlib, "import_module", _fake_import_module)

    result = generate_btst_followup_artifacts(report_dir, "2026-03-27", next_trade_date="2026-03-30")

    assert calls == ["manifest", "followup"]
    assert result["brief_json"] == "brief.json"
    assert result["priority_board_markdown"] == "priority.md"


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
    assert "latest_btst_priority_board" in entry_ids
    assert "latest_btst_opening_watch_card" in entry_ids
    assert "latest_btst_brief_markdown" in entry_ids
    assert "latest_btst_execution_card_json" in entry_ids
    assert "latest_btst_catalyst_theme_frontier_markdown" in entry_ids
    assert (report_dir / "catalyst_theme_frontier_latest.md").exists()


def test_refresh_btst_nightly_control_tower_writes_bundle_for_reports_root(tmp_path):
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
        "p9_candidate_entry_rollout_governance_20260330.json",
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
    result = refresh_btst_nightly_control_tower(report_dir)

    assert result is not None
    assert Path(result["open_ready_delta_json"]).name == "btst_open_ready_delta_latest.json"
    assert Path(result["open_ready_delta_markdown"]).name == "btst_open_ready_delta_latest.md"
    assert Path(result["nightly_control_tower_json"]).name == "btst_nightly_control_tower_latest.json"
    assert Path(result["nightly_control_tower_markdown"]).name == "btst_nightly_control_tower_latest.md"
    assert Path(result["open_ready_delta_json"]).exists()
    assert Path(result["open_ready_delta_markdown"]).exists()
    assert Path(result["nightly_control_tower_json"]).exists()
    assert Path(result["nightly_control_tower_markdown"]).exists()

    manifest = json.loads(Path(result["manifest_json"]).read_text(encoding="utf-8"))
    entry_ids = {entry["id"] for entry in manifest["entries"]}
    assert "btst_open_ready_delta_latest" in entry_ids
    assert "btst_nightly_control_tower_latest" in entry_ids
    assert "latest_btst_catalyst_theme_frontier_markdown" in entry_ids
    assert Path(result["catalyst_theme_frontier_markdown"]).exists()

    delta_markdown = Path(result["open_ready_delta_markdown"]).read_text(encoding="utf-8")
    assert "# BTST Open-Ready Delta" in delta_markdown
    nightly_markdown = Path(result["nightly_control_tower_markdown"]).read_text(encoding="utf-8")
    assert "# BTST Nightly Control Tower" in nightly_markdown
    assert "## Catalyst Theme Frontier" in nightly_markdown
    assert "300757" in nightly_markdown
    assert "btst_next_day_priority_board_20260330.md" in nightly_markdown
