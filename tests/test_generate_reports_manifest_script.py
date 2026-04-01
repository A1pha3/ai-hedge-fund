from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_reports_manifest import generate_reports_manifest_artifacts
from src.screening.models import StrategySignal
from src.targets.router import build_selection_targets


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _build_entry(ticker: str, *, weak_structure: bool) -> dict:
    if weak_structure:
        return {
            "ticker": ticker,
            "score_b": 0.3829,
            "score_c": -0.1194,
            "score_final": 0.1568,
            "quality_score": 0.9375,
            "decision": "avoid",
            "bc_conflict": "b_positive_c_strong_bearish",
            "candidate_source": "watchlist_filter_diagnostics",
            "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
            "reason": "decision_avoid",
            "strategy_signals": {
                "trend": _make_signal(
                    1,
                    70.0,
                    sub_factors={
                        "momentum": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                        "adx_strength": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                        "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                        "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                        "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    },
                ),
                "event_sentiment": _make_signal(
                    0,
                    0.0,
                    sub_factors={
                        "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                        "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    },
                ),
                "mean_reversion": _make_signal(0, 0.0),
            },
            "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0646, "investor": -0.0548}},
        }
    return {
        "ticker": ticker,
        "score_b": 0.4199,
        "score_c": -0.0961,
        "score_final": 0.1877,
        "quality_score": 0.975,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                100.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 49.24, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0305, "investor": -0.0656}},
    }


def _write_replay_input(report_dir: Path, *, trade_date: str, entries: list[dict]) -> None:
    selection_targets, summary = build_selection_targets(
        trade_date=trade_date.replace("-", ""),
        watchlist=[],
        rejected_entries=entries,
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    payload = {
        "artifact_version": "v1",
        "run_id": f"test_{report_dir.name}_{trade_date}",
        "trade_date": trade_date,
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": len(entries),
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": [
            {
                **entry,
                "strategy_signals": {name: signal.model_dump(mode="json") for name, signal in entry["strategy_signals"].items()},
            }
            for entry in entries
        ],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    target_dir = report_dir / "selection_artifacts" / trade_date
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "selection_target_replay_input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_json(report_dir / "session_summary.json", {"plan_generation": {"selection_target": "dual_target"}})


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
        "btst_open_ready_delta_latest.md",
        "btst_nightly_control_tower_latest.md",
        "btst_micro_window_regression_20260330.md",
        "btst_profile_frontier_20260330.md",
        "btst_score_construction_frontier_20260330.md",
        "btst_penalty_frontier_current_window_20260331.md",
        "btst_candidate_entry_frontier_20260330.md",
        "btst_candidate_entry_window_scan_20260330.md",
        "btst_penalty_frontier_current_window_20260331.json",
        "p9_candidate_entry_rollout_governance_20260330.json",
        "p9_candidate_entry_rollout_governance_20260330.md",
        "p2_top3_experiment_execution_summary_20260330.json",
        "p3_top3_post_execution_action_board_20260330.json",
        "p4_primary_roll_forward_validation_001309_20260330.json",
        "p4_shadow_entry_expansion_board_300383_20260330.json",
        "p4_shadow_lane_priority_board_20260330.json",
        "p5_btst_rollout_governance_board_20260330.json",
        "p6_primary_window_gap_001309_20260330.json",
        "p6_recurring_shadow_runbook_20260330.json",
        "p7_primary_window_validation_runbook_001309_20260330.json",
        "p7_shadow_peer_scan_300383_20260330.json",
        "p8_structural_shadow_runbook_300724_20260330.json",
    ]:
        if filename.endswith(".md"):
            (reports_root / filename).write_text(f"# {filename}\n", encoding="utf-8")
        else:
            _write_json(reports_root / filename, {"path": filename})

    _write_json(
        reports_root / "btst_penalty_frontier_current_window_20260331.json",
        {
            "passing_variant_count": 0,
            "focus_tickers": ["300383", "002015", "600821"],
            "best_variant": {
                "variant_name": "nm_0.42__avoid_0.12__stale_0.08__ext_0.02",
                "variant_family": "penalty_coupled",
                "guardrail_status": "fails_closed_tradeable_guardrails",
                "closed_cycle_tradeable_count": 2,
                "tradeable_cases": ["2026-03-26:300724:near_miss", "2026-03-26:300724:selected"],
                "focus_tradeable_cases": [],
            },
            "recommendation": "当前窗口 broad penalty relief 不构成 rollout 路线。",
        },
    )

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
    latest_priority_board = latest_report / "btst_next_day_priority_board_20260331.md"
    _write_json(latest_brief_json, {"trade_date": "2026-03-30", "next_trade_date": "2026-03-31"})
    latest_brief_md.write_text("# latest brief\n", encoding="utf-8")
    _write_json(latest_card_json, {"trade_date": "2026-03-30", "next_trade_date": "2026-03-31"})
    latest_card_md.write_text("# latest card\n", encoding="utf-8")
    latest_opening_card.write_text("# opening card\n", encoding="utf-8")
    latest_priority_board.write_text("# priority board\n", encoding="utf-8")
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
                "priority_board_markdown": str(latest_priority_board.resolve()),
            },
        },
    )

    result = generate_reports_manifest_artifacts(reports_root=reports_root)
    manifest = result["manifest"]

    assert manifest["catalyst_theme_frontier_refresh"]["status"] == "refreshed"
    assert manifest["catalyst_theme_frontier_refresh"]["report_dir"] == "paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330"
    assert manifest["candidate_entry_shadow_refresh"] == {
        "status": "skipped_missing_inputs",
        "missing_inputs": [
            "frontier_report",
            "structural_validation",
            "score_frontier_report",
        ],
        "window_report_count": 0,
    }
    assert manifest["btst_rollout_governance_refresh"] == {
        "status": "refreshed",
        "missing_inputs": [],
        "governance_row_count": 5,
        "next_task_count": 3,
        "penalty_frontier_status": "broad_penalty_route_closed_current_window",
        "penalty_frontier_passing_variant_count": 0,
        "output_json": str((reports_root / "p5_btst_rollout_governance_board_20260330.json").resolve()),
    }
    assert manifest["btst_governance_synthesis_refresh"]["status"] == "refreshed"
    assert manifest["btst_governance_validation_refresh"]["status"] == "refreshed"
    assert manifest["btst_replay_cohort_refresh"] == {
        "status": "refreshed",
        "report_count": 2,
        "short_trade_only_report_count": 2,
        "dual_target_report_count": 0,
        "latest_short_trade_report": "paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330",
        "output_json": str((reports_root / "btst_replay_cohort_latest.json").resolve()),
    }
    assert manifest["latest_btst_run"] == {
        "report_dir": "data/reports/paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330",
        "report_dir_abs": str(latest_report.resolve()),
        "selection_target": "short_trade_only",
        "trade_date": "2026-03-30",
        "next_trade_date": "2026-03-31",
    }

    entries_by_id = {entry["id"]: entry for entry in manifest["entries"]}
    assert entries_by_id["latest_btst_priority_board"]["report_path"] == "data/reports/paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330/btst_next_day_priority_board_20260331.md"
    assert entries_by_id["latest_btst_catalyst_theme_frontier_markdown"]["report_path"] == "data/reports/paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330/catalyst_theme_frontier_latest.md"
    assert entries_by_id["latest_btst_opening_watch_card"]["report_path"] == "data/reports/paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330/btst_opening_watch_card_20260331.md"
    assert entries_by_id["latest_btst_brief_json"]["time_scope"] == {
        "label": "latest_btst_followup",
        "trade_date": "2026-03-30",
        "next_trade_date": "2026-03-31",
    }
    assert entries_by_id["btst_micro_window_regression_review"]["report_path"] == "data/reports/btst_micro_window_regression_20260330.md"
    assert entries_by_id["btst_profile_frontier_review"]["report_path"] == "data/reports/btst_profile_frontier_20260330.md"
    assert entries_by_id["btst_score_construction_frontier_review"]["report_path"] == "data/reports/btst_score_construction_frontier_20260330.md"
    assert entries_by_id["btst_penalty_frontier_review"]["report_path"] == "data/reports/btst_penalty_frontier_current_window_20260331.md"
    assert entries_by_id["btst_candidate_entry_frontier_review"]["report_path"] == "data/reports/btst_candidate_entry_frontier_20260330.md"
    assert entries_by_id["btst_candidate_entry_window_scan_review"]["report_path"] == "data/reports/btst_candidate_entry_window_scan_20260330.md"
    assert entries_by_id["p9_candidate_entry_rollout_governance"]["report_path"] == "data/reports/p9_candidate_entry_rollout_governance_20260330.md"
    assert entries_by_id["p5_rollout_governance_board"]["report_path"] == "data/reports/p5_btst_rollout_governance_board_20260330.json"
    assert entries_by_id["btst_open_ready_delta_latest"]["report_path"] == "data/reports/btst_open_ready_delta_latest.md"
    assert entries_by_id["btst_nightly_control_tower_latest"]["report_path"] == "data/reports/btst_nightly_control_tower_latest.md"
    assert entries_by_id["btst_governance_synthesis_latest"]["report_path"] == "data/reports/btst_governance_synthesis_latest.md"
    assert entries_by_id["btst_governance_validation_latest"]["report_path"] == "data/reports/btst_governance_validation_latest.md"
    assert entries_by_id["btst_replay_cohort_latest"]["report_path"] == "data/reports/btst_replay_cohort_latest.md"
    assert entries_by_id["optimize0330_readme"]["report_path"] == "docs/zh-cn/factors/BTST/optimize0330/README.md"

    reading_paths = {reading_path["id"]: reading_path for reading_path in manifest["reading_paths"]}
    assert reading_paths["btst_control_tower"]["entry_ids"] == [
        "btst_open_ready_delta_latest",
        "btst_nightly_control_tower_latest",
        "btst_governance_synthesis_latest",
        "latest_btst_priority_board",
        "latest_btst_catalyst_theme_frontier_markdown",
        "btst_governance_validation_latest",
        "btst_replay_cohort_latest",
        "p5_rollout_governance_board",
        "p9_candidate_entry_rollout_governance",
    ]
    assert reading_paths["tomorrow_open"]["entry_ids"] == [
        "btst_open_ready_delta_latest",
        "latest_btst_priority_board",
        "latest_btst_opening_watch_card",
        "latest_btst_execution_card_markdown",
        "latest_btst_brief_markdown",
    ]
    assert reading_paths["nightly_review"]["entry_ids"] == [
        "btst_open_ready_delta_latest",
        "btst_nightly_control_tower_latest",
        "latest_btst_session_summary",
        "latest_btst_brief_json",
        "latest_btst_execution_card_json",
        "latest_btst_catalyst_theme_frontier_markdown",
        "latest_btst_selection_snapshot",
    ]
    assert reading_paths["btst_governance"]["entry_ids"] == [
        "btst_governance_synthesis_latest",
        "btst_governance_validation_latest",
        "p2_top3_execution_summary",
        "p3_post_execution_action_board",
        "p5_rollout_governance_board",
        "btst_micro_window_regression_review",
        "btst_profile_frontier_review",
        "btst_score_construction_frontier_review",
        "btst_penalty_frontier_review",
        "btst_candidate_entry_frontier_review",
        "btst_candidate_entry_window_scan_review",
        "p9_candidate_entry_rollout_governance",
        "p6_primary_window_gap",
        "p6_recurring_shadow_runbook",
        "p7_primary_window_validation_runbook",
        "p8_structural_shadow_runbook",
    ]
    assert reading_paths["replay_history"]["entry_ids"] == [
        "btst_replay_cohort_latest",
        "replay_artifacts_stock_selection_manual",
        "historical_edge_artifact_index",
    ]

    assert Path(result["json_path"]).exists()
    assert Path(result["markdown_path"]).exists()
    synthesis = json.loads((reports_root / "btst_governance_synthesis_latest.json").read_text(encoding="utf-8"))
    assert synthesis["closed_frontiers"][0]["frontier_id"] == "broad_penalty_relief"
    assert synthesis["closed_frontiers"][0]["status"] == "broad_penalty_route_closed_current_window"
    latest_session_summary = json.loads((latest_report / "session_summary.json").read_text(encoding="utf-8"))
    assert latest_session_summary["artifacts"]["btst_catalyst_theme_frontier_markdown"].endswith("catalyst_theme_frontier_latest.md")
    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "catalyst_theme_frontier_refresh_status: refreshed" in markdown
    assert "candidate_entry_shadow_refresh_status: skipped_missing_inputs" in markdown
    assert "btst_rollout_governance_refresh_status: refreshed" in markdown
    assert "btst_rollout_governance_penalty_status: broad_penalty_route_closed_current_window" in markdown
    assert "btst_governance_synthesis_status: refreshed" in markdown
    assert "btst_governance_validation_status: refreshed" in markdown
    assert "btst_replay_cohort_status: refreshed" in markdown
    assert "## BTST 控制塔" in markdown
    assert "## 明天开盘" in markdown
    assert "btst_open_ready_delta_latest.md" in markdown
    assert "btst_nightly_control_tower_latest.md" in markdown
    assert "btst_next_day_priority_board_20260331.md" in markdown
    assert "catalyst_theme_frontier_latest.md" in markdown
    assert "btst_opening_watch_card_20260331.md" in markdown
    assert "btst_governance_synthesis_latest.md" in markdown
    assert "btst_governance_validation_latest.md" in markdown
    assert "btst_replay_cohort_latest.md" in markdown
    assert "btst_micro_window_regression_20260330.md" in markdown
    assert "btst_profile_frontier_20260330.md" in markdown
    assert "btst_score_construction_frontier_20260330.md" in markdown
    assert "btst_penalty_frontier_current_window_20260331.md" in markdown
    assert "btst_candidate_entry_frontier_20260330.md" in markdown
    assert "btst_candidate_entry_window_scan_20260330.md" in markdown
    assert "p9_candidate_entry_rollout_governance_20260330.md" in markdown


def test_generate_reports_manifest_refreshes_candidate_entry_shadow_lane_artifacts(tmp_path: Path) -> None:
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

    _write_json(
        reports_root / "btst_candidate_entry_frontier_20260330.json",
        {
            "best_variant": {
                "variant_name": "weak_structure_triplet",
                "filtered_candidate_entry_count": 1,
                "focus_filtered_tickers": ["300502"],
                "preserve_filtered_tickers": [],
                "filtered_next_high_hit_rate_at_threshold": 0.0,
                "filtered_next_close_positive_rate": 0.0,
                "evidence_tier": "window_verified_selective_rule",
                "selection_basis": "candidate_entry_frontier_priority",
            }
        },
    )
    _write_json(
        reports_root / "selection_target_structural_variants_candidate_entry_current_window_20260330.json",
        {
            "rows": [
                {
                    "structural_variant": "exclude_watchlist_avoid_weak_structure_entries",
                    "decision_mismatch_count": 1,
                    "released_from_blocked": ["300502"],
                    "blocked_to_near_miss": [],
                    "blocked_to_selected": [],
                    "analysis": {
                        "filtered_candidate_entry_counts": {"watchlist_avoid_boundary_weak_structure_entry": 1},
                        "candidate_entry_filter_observability": {
                            "watchlist_avoid_boundary_weak_structure_entry": {
                                "precondition_match_count": 3,
                                "metric_data_pass_count": 3,
                                "metric_threshold_match_count": 1,
                            }
                        },
                    },
                }
            ]
        },
    )
    _write_json(
        reports_root / "btst_score_construction_frontier_20260330.json",
        {
            "ranked_variants": [
                {"variant_name": "prepared_breakout_balance", "closed_cycle_tradeable_count": 0},
                {"variant_name": "catalyst_volume_balance", "closed_cycle_tradeable_count": 0},
            ]
        },
    )

    report_a = reports_root / "paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329"
    _write_replay_input(report_a, trade_date="2026-03-26", entries=[_build_entry("300394", weak_structure=False), _build_entry("300502", weak_structure=True)])

    report_b = reports_root / "paper_trading_window_20260316_20260323_live_m2_7_20260323"
    _write_replay_input(report_b, trade_date="2026-03-20", entries=[_build_entry("300394", weak_structure=False)])

    result = generate_reports_manifest_artifacts(reports_root=reports_root)

    refresh = result["candidate_entry_shadow_refresh"]
    assert refresh["status"] == "refreshed"
    assert refresh["window_report_count"] == 2
    assert refresh["filtered_report_count"] == 1
    assert refresh["focus_hit_report_count"] == 1
    assert refresh["preserve_misfire_report_count"] == 0
    assert refresh["rollout_readiness"] == "shadow_only_until_second_window"
    assert refresh["lane_status"] == "shadow_only_until_second_window"

    manifest = result["manifest"]
    assert manifest["catalyst_theme_frontier_refresh"] == {
        "status": "skipped_no_latest_btst_run",
    }
    assert manifest["candidate_entry_shadow_refresh"] == refresh
    assert manifest["btst_rollout_governance_refresh"]["status"] == "skipped_missing_inputs"
    assert manifest["btst_governance_synthesis_refresh"]["status"] == "skipped_missing_inputs"
    assert manifest["btst_governance_validation_refresh"]["status"] == "skipped_missing_inputs"
    assert manifest["btst_replay_cohort_refresh"]["status"] == "refreshed"
    assert manifest["btst_replay_cohort_refresh"]["report_count"] == 2

    window_scan = json.loads((reports_root / "btst_candidate_entry_window_scan_20260330.json").read_text(encoding="utf-8"))
    governance = json.loads((reports_root / "p9_candidate_entry_rollout_governance_20260330.json").read_text(encoding="utf-8"))
    assert window_scan["filtered_report_count"] == 1
    assert window_scan["focus_hit_report_count"] == 1
    assert window_scan["preserve_misfire_report_count"] == 0
    assert window_scan["rollout_readiness"] == "shadow_only_until_second_window"
    assert governance["lane_status"] == "shadow_only_until_second_window"
    assert governance["default_upgrade_status"] == "blocked_by_single_window_candidate_entry_signal"

    entries_by_id = {entry["id"]: entry for entry in result["manifest"]["entries"]}
    assert entries_by_id["btst_candidate_entry_window_scan_review"]["report_path"] == "data/reports/btst_candidate_entry_window_scan_20260330.md"
    assert entries_by_id["p9_candidate_entry_rollout_governance"]["report_path"] == "data/reports/p9_candidate_entry_rollout_governance_20260330.md"

    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "candidate_entry_shadow_refresh_status: refreshed" in markdown
    assert "candidate_entry_shadow_refresh_window_reports: 2" in markdown
    assert "candidate_entry_shadow_refresh_filtered_reports: 1" in markdown
    assert "candidate_entry_shadow_refresh_rollout_readiness: shadow_only_until_second_window" in markdown
    assert "btst_rollout_governance_refresh_status: skipped_missing_inputs" in markdown
    assert "btst_governance_synthesis_status: skipped_missing_inputs" in markdown
    assert "btst_governance_validation_status: skipped_missing_inputs" in markdown
    assert "btst_replay_cohort_status: refreshed" in markdown