from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_reports_manifest import (
    _build_continuation_promotion_ready_summary,
    _build_execution_constraint_rollup,
    _build_transient_probe_summary,
    _collect_governance_synthesis_evidence_dirs,
    generate_reports_manifest,
    generate_reports_manifest_artifacts,
)
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


def test_generate_reports_manifest_includes_default_merge_review_summary(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    _write_json(
        reports_root / "btst_default_merge_review_latest.json",
        {
            "focus_ticker": "300720",
            "merge_review_verdict": "ready_for_default_btst_merge_review",
            "operator_action": "review_default_btst_merge",
            "t_plus_2_positive_rate_delta_vs_default_btst": 0.3961,
            "t_plus_2_mean_return_delta_vs_default_btst": 0.0844,
            "counterfactual_validation": {
                "counterfactual_verdict": "supports_default_btst_merge",
                "t_plus_2_positive_rate_margin_vs_threshold": 0.2961,
                "t_plus_2_mean_return_margin_vs_threshold": 0.0644,
            },
        },
    )
    (reports_root / "btst_default_merge_review_latest.md").write_text("# merge review\n", encoding="utf-8")
    _write_json(
        reports_root / "btst_default_merge_historical_counterfactual_latest.json",
        {
            "focus_ticker": "300720",
            "counterfactual_verdict": "merged_default_btst_uplift_positive",
            "uplift_vs_default_btst": {
                "t_plus_2_positive_rate_uplift": 0.1857,
                "mean_t_plus_2_return_uplift": 0.0394,
            },
        },
    )
    (reports_root / "btst_default_merge_historical_counterfactual_latest.md").write_text("# merge historical\n", encoding="utf-8")
    _write_json(
        reports_root / "btst_continuation_merge_candidate_ranking_latest.json",
        {
            "candidate_count": 2,
            "top_candidate": {
                "ticker": "300720",
                "promotion_path_status": "merge_review_ready",
                "t_plus_2_positive_rate_delta_vs_default_btst": 0.3961,
                "mean_t_plus_2_return_delta_vs_default_btst": 0.0844,
            },
        },
    )
    (reports_root / "btst_continuation_merge_candidate_ranking_latest.md").write_text("# candidate ranking\n", encoding="utf-8")
    _write_json(
        reports_root / "btst_default_merge_strict_counterfactual_latest.json",
        {
            "focus_ticker": "300720",
            "strict_counterfactual_verdict": "strict_merge_uplift_positive",
            "strict_uplift_vs_default_btst": {
                "t_plus_2_positive_rate_uplift": 0.0714,
                "mean_t_plus_2_return_uplift": 0.0112,
            },
            "overlap_diagnostics": {
                "overlap_case_count": 1,
            },
        },
    )
    (reports_root / "btst_default_merge_strict_counterfactual_latest.md").write_text("# strict counterfactual\n", encoding="utf-8")
    _write_json(
        reports_root / "btst_merge_replay_validation_latest.json",
        {
            "overall_verdict": "merge_replay_promotes_selected",
            "focus_tickers": ["300720", "300505"],
            "promoted_to_selected_count": 1,
            "promoted_to_near_miss_count": 1,
            "relief_applied_count": 2,
            "relief_actionable_applied_count": 1,
            "relief_already_selected_count": 1,
            "relief_positive_promotion_precision": 0.5,
            "relief_actionable_positive_promotion_precision": 1.0,
            "relief_no_promotion_ratio": 0.5,
            "relief_actionable_no_promotion_ratio": 0.0,
            "recommended_next_lever": "execution_signal",
            "recommended_signal_levers": ["trend_acceleration", "breakout_freshness"],
        },
    )
    (reports_root / "btst_merge_replay_validation_latest.md").write_text("# merge replay validation\n", encoding="utf-8")
    _write_json(
        reports_root / "btst_prepared_breakout_relief_validation_latest.json",
        {
            "focus_ticker": "300505",
            "verdict": "prepared_breakout_selected_relief_supported",
            "selected_relief_window_count": 4,
            "selected_relief_alignment_rate": 1.0,
            "outcome_support": {
                "evidence_status": "strong_t1_t2_support",
                "next_close_positive_rate": 1.0,
            },
        },
    )
    (reports_root / "btst_prepared_breakout_relief_validation_latest.md").write_text("# prepared breakout relief validation\n", encoding="utf-8")
    _write_json(
        reports_root / "btst_prepared_breakout_cohort_latest.json",
        {
            "candidate_count": 2,
            "selected_frontier_candidate_count": 1,
            "verdict": "selected_frontier_peer_found",
            "next_candidate": {"ticker": "000792"},
        },
    )
    (reports_root / "btst_prepared_breakout_cohort_latest.md").write_text("# prepared breakout cohort\n", encoding="utf-8")
    _write_json(
        reports_root / "btst_prepared_breakout_residual_surface_latest.json",
        {
            "focus_ticker": "600988",
            "verdict": "non_actionable_score_surface",
            "focus_report_dir_count": 5,
        },
    )
    (reports_root / "btst_prepared_breakout_residual_surface_latest.md").write_text("# prepared breakout residual surface\n", encoding="utf-8")
    _write_json(
        reports_root / "btst_candidate_pool_corridor_persistence_dossier_latest.json",
        {
            "focus_ticker": "300720",
            "verdict": "await_second_independent_selected_window",
            "next_confirmation_requirement": "300720 still needs 1 independent selected sample.",
        },
    )
    (reports_root / "btst_candidate_pool_corridor_persistence_dossier_latest.md").write_text("# corridor persistence dossier\n", encoding="utf-8")
    _write_json(
        reports_root / "btst_candidate_pool_corridor_window_command_board_latest.json",
        {
            "focus_ticker": "300720",
            "verdict": "collect_one_more_selected_window",
            "next_target_trade_dates": ["2026-04-06", "2026-03-27"],
        },
    )
    (reports_root / "btst_candidate_pool_corridor_window_command_board_latest.md").write_text("# corridor window command board\n", encoding="utf-8")
    _write_json(
        reports_root / "btst_candidate_pool_corridor_window_diagnostics_latest.json",
        {
            "focus_ticker": "300720",
            "near_miss_upgrade_window": {
                "trade_date": "2026-04-06",
                "verdict": "narrow_selected_gap_candidate",
            },
            "visibility_gap_window": {
                "trade_dates": ["2026-03-27"],
                "verdict": "recoverable_current_plan_visibility_gap",
                "recoverable_report_dir_count": 5,
            },
            "recommendation": "Prioritize 2026-04-06; treat 2026-03-27 as visibility audit.",
        },
    )
    (reports_root / "btst_candidate_pool_corridor_window_diagnostics_latest.md").write_text("# corridor window diagnostics\n", encoding="utf-8")
    _write_json(
        reports_root / "btst_candidate_pool_corridor_narrow_probe_latest.json",
        {
            "focus_ticker": "300720",
            "verdict": "lane_specific_select_threshold_override_gap",
            "threshold_override_gap_vs_anchor": 0.13,
            "target_gap_to_selected": 0.1245,
        },
    )
    (reports_root / "btst_candidate_pool_corridor_narrow_probe_latest.md").write_text("# corridor narrow probe\n", encoding="utf-8")

    manifest = generate_reports_manifest(reports_root=reports_root)

    entries_by_id = {entry["id"]: entry for entry in manifest["entries"]}
    assert entries_by_id["btst_default_merge_review_latest"]["report_path"] == "data/reports/btst_default_merge_review_latest.md"
    assert entries_by_id["btst_default_merge_historical_counterfactual_latest"]["report_path"] == "data/reports/btst_default_merge_historical_counterfactual_latest.md"
    assert entries_by_id["btst_continuation_merge_candidate_ranking_latest"]["report_path"] == "data/reports/btst_continuation_merge_candidate_ranking_latest.md"
    assert entries_by_id["btst_default_merge_strict_counterfactual_latest"]["report_path"] == "data/reports/btst_default_merge_strict_counterfactual_latest.md"
    assert entries_by_id["btst_merge_replay_validation_latest"]["report_path"] == "data/reports/btst_merge_replay_validation_latest.md"
    assert entries_by_id["btst_prepared_breakout_relief_validation_latest"]["report_path"] == "data/reports/btst_prepared_breakout_relief_validation_latest.md"
    assert manifest["default_merge_review_summary"]["focus_ticker"] == "300720"
    assert manifest["default_merge_review_summary"]["counterfactual_validation"]["counterfactual_verdict"] == "supports_default_btst_merge"
    assert manifest["default_merge_historical_counterfactual_summary"]["counterfactual_verdict"] == "merged_default_btst_uplift_positive"
    assert manifest["continuation_merge_candidate_ranking_summary"]["top_candidate"]["ticker"] == "300720"
    assert manifest["default_merge_strict_counterfactual_summary"]["strict_counterfactual_verdict"] == "strict_merge_uplift_positive"
    assert manifest["merge_replay_validation_summary"]["overall_verdict"] == "merge_replay_promotes_selected"
    assert manifest["merge_replay_validation_summary"]["relief_actionable_applied_count"] == 1
    assert manifest["merge_replay_validation_summary"]["relief_already_selected_count"] == 1
    assert manifest["merge_replay_validation_summary"]["relief_actionable_positive_promotion_precision"] == 1.0
    assert manifest["merge_replay_validation_summary"]["relief_actionable_no_promotion_ratio"] == 0.0
    assert manifest["merge_replay_validation_summary"]["recommended_signal_levers"] == ["trend_acceleration", "breakout_freshness"]
    assert manifest["prepared_breakout_relief_validation_summary"]["focus_ticker"] == "300505"
    assert manifest["prepared_breakout_relief_validation_summary"]["verdict"] == "prepared_breakout_selected_relief_supported"
    assert manifest["prepared_breakout_cohort_summary"]["candidate_count"] == 2
    assert manifest["prepared_breakout_cohort_summary"]["next_candidate"]["ticker"] == "000792"
    assert manifest["prepared_breakout_residual_surface_summary"]["focus_ticker"] == "600988"
    assert manifest["prepared_breakout_residual_surface_summary"]["verdict"] == "non_actionable_score_surface"
    assert manifest["candidate_pool_corridor_persistence_dossier_summary"]["focus_ticker"] == "300720"
    assert manifest["candidate_pool_corridor_persistence_dossier_summary"]["verdict"] == "await_second_independent_selected_window"
    assert manifest["candidate_pool_corridor_window_command_board_summary"]["focus_ticker"] == "300720"
    assert manifest["candidate_pool_corridor_window_command_board_summary"]["verdict"] == "collect_one_more_selected_window"
    assert manifest["candidate_pool_corridor_window_diagnostics_summary"]["focus_ticker"] == "300720"
    assert manifest["candidate_pool_corridor_window_diagnostics_summary"]["near_miss_upgrade_window"]["verdict"] == "narrow_selected_gap_candidate"
    assert manifest["candidate_pool_corridor_narrow_probe_summary"]["verdict"] == "lane_specific_select_threshold_override_gap"
    reading_paths = {reading_path["id"]: reading_path for reading_path in manifest["reading_paths"]}
    assert "btst_default_merge_review_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_default_merge_historical_counterfactual_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_continuation_merge_candidate_ranking_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_default_merge_strict_counterfactual_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_merge_replay_validation_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_prepared_breakout_relief_validation_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_prepared_breakout_cohort_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_prepared_breakout_residual_surface_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_candidate_pool_corridor_persistence_dossier_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_candidate_pool_corridor_window_command_board_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_candidate_pool_corridor_window_diagnostics_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_candidate_pool_corridor_narrow_probe_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_default_merge_review_latest" in reading_paths["nightly_review"]["entry_ids"]
    assert "btst_default_merge_historical_counterfactual_latest" in reading_paths["nightly_review"]["entry_ids"]
    assert "btst_continuation_merge_candidate_ranking_latest" in reading_paths["nightly_review"]["entry_ids"]
    assert "btst_prepared_breakout_cohort_latest" in reading_paths["nightly_review"]["entry_ids"]
    assert "btst_prepared_breakout_residual_surface_latest" in reading_paths["nightly_review"]["entry_ids"]
    assert "btst_candidate_pool_corridor_persistence_dossier_latest" in reading_paths["nightly_review"]["entry_ids"]
    assert "btst_candidate_pool_corridor_window_command_board_latest" in reading_paths["nightly_review"]["entry_ids"]
    assert "btst_candidate_pool_corridor_window_diagnostics_latest" in reading_paths["nightly_review"]["entry_ids"]
    assert "btst_candidate_pool_corridor_narrow_probe_latest" in reading_paths["nightly_review"]["entry_ids"]
    assert "btst_default_merge_strict_counterfactual_latest" in reading_paths["nightly_review"]["entry_ids"]
    assert "btst_merge_replay_validation_latest" in reading_paths["nightly_review"]["entry_ids"]
    assert "btst_prepared_breakout_relief_validation_latest" in reading_paths["nightly_review"]["entry_ids"]


def _write_tradeable_opportunity_artifacts(reports_root: Path) -> None:
    analysis = {
        "artifact_schema_version": 2,
        "generated_at": "2026-04-02T09:00:00",
        "trade_dates": ["2026-03-23", "2026-03-24", "2026-03-25", "2026-03-26"],
        "trade_date_contexts": {
            "2026-03-25": {
                "report_dir": "paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329",
                "selection_target": "dual_target",
                "mode": "live_pipeline",
            }
        },
        "result_truth_pool_count": 19,
        "tradeable_opportunity_pool_count": 11,
        "system_recall_count": 7,
        "selected_or_near_miss_count": 3,
        "main_execution_pool_count": 2,
        "strict_goal_case_count": 4,
        "strict_goal_false_negative_count": 2,
        "tradeable_pool_capture_rate": 0.6364,
        "tradeable_pool_selected_or_near_miss_rate": 0.2727,
        "tradeable_pool_main_execution_rate": 0.1818,
        "top_strict_goal_false_negative_rows": [
            {
                "trade_date": "2026-03-26",
                "ticker": "300724",
                "first_kill_switch": "score_fail",
                "t_plus_2_close_return": 0.0812,
            },
            {
                "trade_date": "2026-03-24",
                "ticker": "600522",
                "first_kill_switch": "candidate_entry_filtered",
                "t_plus_2_close_return": 0.0621,
            },
        ],
        "no_candidate_entry_summary": {
            "count": 1,
            "share_of_tradeable_pool": 0.0909,
            "strict_goal_case_count": 0,
            "strict_goal_case_share": 0.0,
            "industry_counts": {"Chip": 1},
            "trade_date_counts": {"2026-03-25": 1},
            "estimated_amount_bucket_counts": {"10000w_to_20000w": 1},
            "truth_pattern_counts": {"intraday_only": 1},
            "top_ticker_rows": [
                {
                    "ticker": "300502",
                    "occurrence_count": 1,
                    "strict_goal_case_count": 0,
                    "industry": "Chip",
                    "latest_trade_date": "2026-03-25",
                    "trade_dates": ["2026-03-25"],
                    "mean_next_high_return": 0.055,
                    "mean_next_close_return": 0.018,
                    "mean_t_plus_2_close_return": 0.021,
                    "lead_truth_pattern": "intraday_only",
                }
            ],
            "top_priority_rows": [
                {
                    "trade_date": "2026-03-25",
                    "ticker": "300502",
                    "first_kill_switch": "no_candidate_entry",
                    "next_high_return": 0.055,
                    "next_close_return": 0.018,
                    "t_plus_2_close_return": 0.021,
                }
            ],
            "recommendation": "no_candidate_entry 机会主要集中在 ['Chip']，优先围绕 ['300502'] 回查 candidate entry semantics / watchlist 召回，而不是继续放松 score。",
        },
        "recommendation": "当前主瓶颈已经集中到 short-trade boundary / score frontier，优先沿 breakout-trend-catalyst 语义做前沿修复。",
        "rows": [
            {
                "trade_date": "2026-03-25",
                "ticker": "300502",
                "industry": "Chip",
                "first_kill_switch": "no_candidate_entry",
                "strict_btst_goal_case": False,
                "next_high_return": 0.055,
                "next_close_return": 0.018,
                "t_plus_2_close_return": 0.021,
                "report_dir": "paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329",
                "report_mode": "live_pipeline",
                "report_selection_target": "dual_target",
            },
            {
                "trade_date": "2026-03-26",
                "ticker": "300724",
                "industry": "Chip",
                "first_kill_switch": "score_fail",
                "strict_btst_goal_case": True,
                "next_high_return": 0.071,
                "next_close_return": 0.042,
                "t_plus_2_close_return": 0.0812,
                "report_dir": "paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329",
                "report_mode": "live_pipeline",
                "report_selection_target": "dual_target",
            },
        ],
    }
    waterfall = {
        "generated_at": "2026-04-02T09:00:00",
        "top_tradeable_kill_switches": [
            {"kill_switch": "score_fail", "count": 4},
            {"kill_switch": "candidate_entry_filtered", "count": 2},
            {"kill_switch": "no_candidate_entry", "count": 1},
        ],
        "recommendation": analysis["recommendation"],
    }
    _write_json(reports_root / "btst_tradeable_opportunity_pool_march.json", analysis)
    _write_json(reports_root / "btst_tradeable_opportunity_reason_waterfall_march.json", waterfall)
    (reports_root / "btst_tradeable_opportunity_pool_march.md").write_text("# tradeable opportunity pool\n", encoding="utf-8")
    (reports_root / "btst_tradeable_opportunity_reason_waterfall_march.md").write_text("# tradeable opportunity waterfall\n", encoding="utf-8")
    (reports_root / "btst_tradeable_opportunity_pool_march.csv").write_text("trade_date,ticker,first_kill_switch\n2026-03-26,300724,score_fail\n", encoding="utf-8")
    snapshots_root = reports_root.parent / "snapshots"
    snapshots_root.mkdir(parents=True, exist_ok=True)
    _write_json(snapshots_root / "candidate_pool_20260325_top300.json", [{"ticker": "300394"}])


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
        "btst_latest_close_validation_latest.md",
        "btst_micro_window_regression_march_refresh.md",
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
    _write_tradeable_opportunity_artifacts(reports_root)
    _write_json(
        reports_root / "btst_tplus2_continuation_promotion_review_latest.json",
        {"focus_ticker": "300720", "promotion_review_verdict": "watch_review_ready"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_promotion_gate_latest.json",
        {"focus_ticker": "300720", "gate_verdict": "approve_watchlist_promotion"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_watchlist_execution_latest.json",
        {"focus_ticker": "300720", "execution_verdict": "watchlist_extension_applied"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_eligible_gate_latest.json",
        {"focus_ticker": "300720", "gate_verdict": "approve_eligible_promotion"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_execution_gate_latest.json",
        {"focus_ticker": "300720", "gate_verdict": "approve_execution_candidate"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_execution_overlay_latest.json",
        {
            "focus_ticker": "300720",
            "execution_verdict": "execution_candidate_applied",
            "adopted_execution_row": {
                "promotion_blocker": "no_selected_persistence_or_independent_edge",
                "persistence_requirement": "selected_persistence_across_independent_windows",
                "independent_edge_requirement": "outperform_default_btst_on_independent_windows",
                "lane_support_ratio": 0.875,
                "t_plus_2_mean_gap_vs_watch": 0.067,
                "next_step": "只保留 isolated paper execution，继续验证 selected persistence。",
            },
        },
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_governance_board_latest.json",
        {"focus_promotion_ticker": "300720", "governance_status": "single_ticker_with_validation_watch"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_watchboard_latest.json",
        {"governance_status": "single_ticker_with_validation_watch"},
    )

    result = generate_reports_manifest_artifacts(reports_root=reports_root)
    manifest = result["manifest"]
    entry_ids = {entry["id"] for entry in manifest["entries"]}

    assert manifest["catalyst_theme_frontier_refresh"]["status"] == "refreshed"
    assert manifest["catalyst_theme_frontier_refresh"]["report_dir"] == "paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330"
    assert manifest["btst_window_evidence_refresh"] == {
        "status": "skipped_no_window_reports",
        "window_report_count": 0,
    }
    refresh = manifest["candidate_entry_shadow_refresh"]
    assert refresh["status"] == "skipped_missing_inputs"
    assert refresh["missing_inputs"] == [
        "frontier_report",
        "structural_validation",
        "score_frontier_report",
    ]
    assert refresh["window_report_count"] == 0
    assert refresh["no_candidate_entry_action_board_status"] == "refreshed"
    assert refresh["no_candidate_entry_priority_queue_count"] == 1
    assert refresh["no_candidate_entry_top_tickers"] == ["300502"]
    assert refresh["no_candidate_entry_hotspot_report_dirs"] == ["paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329"]
    assert refresh["no_candidate_entry_action_board_json"] == str((reports_root / "btst_no_candidate_entry_action_board_latest.json").resolve())
    assert refresh["no_candidate_entry_replay_bundle_status"] == "skipped_missing_replay_reports"
    assert refresh["no_candidate_entry_replay_bundle_json"] is None
    assert refresh["no_candidate_entry_promising_tickers"] is None
    assert refresh["no_candidate_entry_failure_dossier_status"] == "refreshed"
    assert refresh["no_candidate_entry_failure_dossier_json"] == str((reports_root / "btst_no_candidate_entry_failure_dossier_latest.json").resolve())
    assert refresh["no_candidate_entry_upstream_absence_tickers"] == []
    assert refresh["no_candidate_entry_handoff_stage_counts"] == {"missing_replay_input_artifacts": 1}
    assert refresh["no_candidate_entry_absent_from_watchlist_tickers"] == []
    assert refresh["no_candidate_entry_watchlist_handoff_gap_tickers"] == []
    assert refresh["no_candidate_entry_candidate_entry_target_gap_tickers"] == []
    assert refresh["no_candidate_entry_handoff_action_queue_task_ids"] == ["300502_missing_replay_input_artifacts"]
    assert refresh["no_candidate_entry_semantic_miss_tickers"] == []
    assert refresh["watchlist_recall_dossier_status"] == "refreshed"
    assert refresh["watchlist_recall_stage_counts"] == {"absent_from_candidate_pool": 1}
    assert refresh["watchlist_recall_absent_from_candidate_pool_tickers"] == ["300502"]
    assert refresh["watchlist_recall_candidate_pool_layer_b_gap_tickers"] == []
    assert refresh["watchlist_recall_layer_b_watchlist_gap_tickers"] == []
    assert refresh["watchlist_recall_action_queue_task_ids"] == ["300502_absent_from_candidate_pool"]
    assert refresh["candidate_pool_recall_dossier_status"] == "refreshed"
    assert refresh["candidate_pool_recall_stage_counts"] == {"candidate_pool_truncated_after_filters": 1}
    assert refresh["candidate_pool_recall_dominant_stage"] == "candidate_pool_truncated_after_filters"
    assert refresh["candidate_pool_recall_top_stage_tickers"] == {"candidate_pool_truncated_after_filters": ["300502"]}
    assert refresh["candidate_pool_recall_truncation_frontier_summary"]["observed_case_count"] == 1
    assert refresh["candidate_pool_recall_dominant_liquidity_gap_mode"] == "near_cutoff_liquidity_gap"
    assert refresh["candidate_pool_recall_action_queue_task_ids"] == ["300502_candidate_pool_truncated_after_filters"]
    assert manifest["btst_score_fail_frontier_refresh"] == {
        "status": "refreshed",
        "report_dir": "paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330",
        "rejected_short_trade_boundary_count": 0,
        "rescueable_case_count": 0,
        "threshold_only_rescue_count": 0,
        "recurring_case_count": 0,
        "priority_queue_tickers": [],
        "top_rescue_tickers": [],
        "analysis_json": str((reports_root / "short_trade_boundary_score_failures_latest.json").resolve()),
        "analysis_markdown": str((reports_root / "short_trade_boundary_score_failures_latest.md").resolve()),
        "frontier_json": str((reports_root / "short_trade_boundary_score_failures_frontier_latest.json").resolve()),
        "frontier_markdown": str((reports_root / "short_trade_boundary_score_failures_frontier_latest.md").resolve()),
        "recurring_json": str((reports_root / "short_trade_boundary_recurring_frontier_cases_latest.json").resolve()),
        "recurring_markdown": str((reports_root / "short_trade_boundary_recurring_frontier_cases_latest.md").resolve()),
        "transition_refresh_status": "skipped_no_window_reports",
        "recurring_shadow_refresh_status": "skipped_missing_inputs",
        "missing_recurring_shadow_inputs": [
            "recurring_pair_comparison",
            "candidate_report",
            "recurring_transition_report",
            "recurring_close_bundle",
        ],
    }
    assert manifest["btst_rollout_governance_refresh"] == {
        "status": "refreshed",
        "missing_inputs": [],
        "governance_row_count": 5,
        "next_task_count": 3,
        "penalty_frontier_status": "broad_penalty_route_closed_current_window",
        "penalty_frontier_passing_variant_count": 0,
        "output_json": str((reports_root / "p5_btst_rollout_governance_board_20260401.json").resolve()),
    }
    assert "btst_latest_close_validation_latest" in entry_ids
    assert manifest["btst_governance_synthesis_refresh"]["status"] == "refreshed"
    assert manifest["btst_governance_validation_refresh"]["status"] == "refreshed"
    assert manifest["btst_independent_window_monitor_refresh"] == {
        "status": "refreshed",
        "report_dir_count": 0,
        "ready_lane_count": 0,
        "waiting_lane_count": 0,
        "no_evidence_lane_count": 3,
        "output_json": str((reports_root / "btst_independent_window_monitor_latest.json").resolve()),
    }
    assert manifest["btst_tplus1_tplus2_objective_monitor_refresh"] == {
        "status": "refreshed",
        "report_dir_count": 0,
        "closed_cycle_row_count": 0,
        "tradeable_closed_cycle_count": 0,
        "tradeable_positive_rate": None,
        "tradeable_return_hit_rate": None,
        "tradeable_mean_t_plus_2_return": None,
        "tradeable_verdict": "insufficient_closed_cycle_samples",
        "best_ticker": None,
        "best_ticker_objective_fit_score": None,
        "output_json": str((reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json").resolve()),
    }
    assert manifest["btst_replay_cohort_refresh"] == {
        "status": "refreshed",
        "report_count": 2,
        "short_trade_only_report_count": 2,
        "dual_target_report_count": 0,
        "latest_short_trade_report": "paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330",
        "output_json": str((reports_root / "btst_replay_cohort_latest.json").resolve()),
    }
    assert manifest["btst_tradeable_opportunity_pool_refresh"] == {
        "status": "loaded_existing",
        "report_dir_count": 2,
        "analysis_json": str((reports_root / "btst_tradeable_opportunity_pool_march.json").resolve()),
        "analysis_markdown": str((reports_root / "btst_tradeable_opportunity_pool_march.md").resolve()),
        "analysis_csv": str((reports_root / "btst_tradeable_opportunity_pool_march.csv").resolve()),
        "waterfall_json": str((reports_root / "btst_tradeable_opportunity_reason_waterfall_march.json").resolve()),
        "waterfall_markdown": str((reports_root / "btst_tradeable_opportunity_reason_waterfall_march.md").resolve()),
        "result_truth_pool_count": 19,
        "tradeable_opportunity_pool_count": 11,
        "system_recall_count": 7,
        "selected_or_near_miss_count": 3,
        "main_execution_pool_count": 2,
        "strict_goal_case_count": 4,
        "strict_goal_false_negative_count": 2,
        "tradeable_pool_capture_rate": 0.6364,
        "tradeable_pool_selected_or_near_miss_rate": 0.2727,
        "tradeable_pool_main_execution_rate": 0.1818,
        "no_candidate_entry_count": 1,
        "no_candidate_entry_share_of_tradeable_pool": 0.0909,
        "top_no_candidate_entry_industries": ["Chip"],
        "top_no_candidate_entry_tickers": ["300502"],
        "top_tradeable_kill_switches": [
            {"kill_switch": "score_fail", "count": 4},
            {"kill_switch": "candidate_entry_filtered", "count": 2},
            {"kill_switch": "no_candidate_entry", "count": 1},
        ],
        "top_tradeable_kill_switch_labels": ["score_fail", "candidate_entry_filtered", "no_candidate_entry"],
        "top_strict_goal_false_negative_tickers": ["300724", "600522"],
        "recommendation": "当前主瓶颈已经集中到 short-trade boundary / score frontier，优先沿 breakout-trend-catalyst 语义做前沿修复。",
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
    assert entries_by_id["btst_micro_window_regression_review"]["report_path"] == "data/reports/btst_micro_window_regression_march_refresh.md"
    assert entries_by_id["btst_profile_frontier_review"]["report_path"] == "data/reports/btst_profile_frontier_20260330.md"
    assert entries_by_id["btst_score_construction_frontier_review"]["report_path"] == "data/reports/btst_score_construction_frontier_20260330.md"
    assert entries_by_id["btst_penalty_frontier_review"]["report_path"] == "data/reports/btst_penalty_frontier_current_window_20260331.md"
    assert entries_by_id["btst_candidate_entry_frontier_review"]["report_path"] == "data/reports/btst_candidate_entry_frontier_20260330.md"
    assert entries_by_id["btst_candidate_entry_window_scan_review"]["report_path"] == "data/reports/btst_candidate_entry_window_scan_20260330.md"
    assert entries_by_id["p9_candidate_entry_rollout_governance"]["report_path"] == "data/reports/p9_candidate_entry_rollout_governance_20260330.md"
    assert entries_by_id["p5_rollout_governance_board"]["report_path"] == "data/reports/p5_btst_rollout_governance_board_20260401.json"
    assert entries_by_id["btst_open_ready_delta_latest"]["report_path"] == "data/reports/btst_open_ready_delta_latest.md"
    assert entries_by_id["btst_nightly_control_tower_latest"]["report_path"] == "data/reports/btst_nightly_control_tower_latest.md"
    assert entries_by_id["btst_governance_synthesis_latest"]["report_path"] == "data/reports/btst_governance_synthesis_latest.md"
    assert entries_by_id["btst_governance_validation_latest"]["report_path"] == "data/reports/btst_governance_validation_latest.md"
    assert entries_by_id["btst_independent_window_monitor_latest"]["report_path"] == "data/reports/btst_independent_window_monitor_latest.md"
    assert entries_by_id["btst_tplus1_tplus2_objective_monitor_latest"]["report_path"] == "data/reports/btst_tplus1_tplus2_objective_monitor_latest.md"
    assert entries_by_id["btst_candidate_pool_lane_objective_support_latest"]["report_path"] == "data/reports/btst_candidate_pool_lane_objective_support_latest.md"
    assert entries_by_id["btst_candidate_pool_rebucket_objective_validation_latest"]["report_path"] == "data/reports/btst_candidate_pool_rebucket_objective_validation_latest.md"
    assert entries_by_id["btst_tradeable_opportunity_pool_march"]["report_path"] == "data/reports/btst_tradeable_opportunity_pool_march.md"
    assert entries_by_id["btst_no_candidate_entry_action_board_latest"]["report_path"] == "data/reports/btst_no_candidate_entry_action_board_latest.md"
    assert entries_by_id["btst_no_candidate_entry_failure_dossier_latest"]["report_path"] == "data/reports/btst_no_candidate_entry_failure_dossier_latest.md"
    assert entries_by_id["btst_tradeable_opportunity_reason_waterfall_march"]["report_path"] == "data/reports/btst_tradeable_opportunity_reason_waterfall_march.md"
    assert entries_by_id["btst_replay_cohort_latest"]["report_path"] == "data/reports/btst_replay_cohort_latest.md"
    assert entries_by_id["btst_score_fail_frontier_latest"]["report_path"] == "data/reports/short_trade_boundary_score_failures_frontier_latest.md"
    assert entries_by_id["btst_score_fail_recurring_frontier_latest"]["report_path"] == "data/reports/short_trade_boundary_recurring_frontier_cases_latest.md"
    assert entries_by_id["optimize0330_readme"]["report_path"] == "docs/zh-cn/factors/BTST/optimize0330/README.md"

    reading_paths = {reading_path["id"]: reading_path for reading_path in manifest["reading_paths"]}
    assert reading_paths["btst_control_tower"]["entry_ids"] == [
        "btst_open_ready_delta_latest",
        "btst_latest_close_validation_latest",
        "btst_nightly_control_tower_latest",
        "btst_governance_synthesis_latest",
        "btst_tplus1_tplus2_objective_monitor_latest",
        "btst_independent_window_monitor_latest",
        "btst_candidate_pool_lane_objective_support_latest",
        "btst_candidate_pool_rebucket_objective_validation_latest",
        "btst_candidate_pool_rebucket_comparison_bundle_latest",
        "btst_candidate_pool_corridor_validation_pack_latest",
        "btst_candidate_pool_corridor_shadow_pack_latest",
        "btst_candidate_pool_lane_pair_board_latest",
        "btst_candidate_pool_upstream_handoff_board_latest",
        "btst_candidate_pool_corridor_uplift_runbook_latest",
        "btst_tradeable_opportunity_pool_march",
        "btst_no_candidate_entry_action_board_latest",
        "btst_no_candidate_entry_failure_dossier_latest",
        "btst_watchlist_recall_dossier_latest",
        "btst_candidate_pool_recall_dossier_latest",
        "btst_tradeable_opportunity_reason_waterfall_march",
        "latest_btst_priority_board",
        "latest_btst_catalyst_theme_frontier_markdown",
        "btst_score_fail_frontier_latest",
        "btst_score_fail_recurring_frontier_latest",
        "btst_governance_validation_latest",
        "btst_replay_cohort_latest",
        "p5_rollout_governance_board",
        "p9_candidate_entry_rollout_governance",
    ]
    assert reading_paths["tomorrow_open"]["entry_ids"] == [
        "btst_open_ready_delta_latest",
        "btst_latest_close_validation_latest",
        "latest_btst_priority_board",
        "latest_btst_opening_watch_card",
        "latest_btst_execution_card_markdown",
        "latest_btst_brief_markdown",
    ]
    assert reading_paths["nightly_review"]["entry_ids"] == [
        "btst_open_ready_delta_latest",
        "btst_latest_close_validation_latest",
        "btst_tplus1_tplus2_objective_monitor_latest",
        "btst_candidate_pool_lane_objective_support_latest",
        "btst_candidate_pool_rebucket_objective_validation_latest",
        "btst_candidate_pool_rebucket_comparison_bundle_latest",
        "btst_candidate_pool_corridor_validation_pack_latest",
        "btst_candidate_pool_corridor_shadow_pack_latest",
        "btst_candidate_pool_lane_pair_board_latest",
        "btst_candidate_pool_upstream_handoff_board_latest",
        "btst_candidate_pool_corridor_uplift_runbook_latest",
        "btst_tradeable_opportunity_pool_march",
        "btst_no_candidate_entry_action_board_latest",
        "btst_no_candidate_entry_failure_dossier_latest",
        "btst_watchlist_recall_dossier_latest",
        "btst_candidate_pool_recall_dossier_latest",
        "btst_nightly_control_tower_latest",
        "latest_btst_session_summary",
        "latest_btst_brief_json",
        "latest_btst_execution_card_json",
        "latest_btst_catalyst_theme_frontier_markdown",
        "btst_score_fail_frontier_latest",
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
        "btst_tplus1_tplus2_objective_monitor_latest",
        "btst_independent_window_monitor_latest",
        "btst_candidate_pool_lane_objective_support_latest",
        "btst_candidate_pool_rebucket_objective_validation_latest",
        "btst_candidate_pool_rebucket_comparison_bundle_latest",
        "btst_candidate_pool_corridor_validation_pack_latest",
        "btst_candidate_pool_corridor_shadow_pack_latest",
        "btst_candidate_pool_lane_pair_board_latest",
        "btst_candidate_pool_upstream_handoff_board_latest",
        "btst_candidate_pool_corridor_uplift_runbook_latest",
        "btst_tradeable_opportunity_pool_march",
        "btst_no_candidate_entry_action_board_latest",
        "btst_no_candidate_entry_failure_dossier_latest",
        "btst_watchlist_recall_dossier_latest",
        "btst_candidate_pool_recall_dossier_latest",
        "btst_tradeable_opportunity_reason_waterfall_march",
        "btst_score_fail_frontier_latest",
        "btst_score_fail_recurring_frontier_latest",
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
    assert "btst_window_evidence_refresh_status: skipped_no_window_reports" in markdown
    assert "candidate_entry_shadow_refresh_status: skipped_missing_inputs" in markdown
    assert "candidate_entry_shadow_no_candidate_entry_failure_dossier_status: refreshed" in markdown
    assert "candidate_entry_shadow_watchlist_recall_dossier_status: refreshed" in markdown
    assert "candidate_entry_shadow_watchlist_recall_absent_from_candidate_pool_tickers: ['300502']" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_dossier_status: refreshed" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_dominant_stage: candidate_pool_truncated_after_filters" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_truncation_frontier_summary:" in markdown
    assert "btst_score_fail_frontier_refresh_status: refreshed" in markdown
    assert "btst_score_fail_frontier_rejected_case_count: 0" in markdown
    assert "btst_score_fail_frontier_recurring_case_count: 0" in markdown
    assert "btst_rollout_governance_refresh_status: refreshed" in markdown
    assert "btst_rollout_governance_penalty_status: broad_penalty_route_closed_current_window" in markdown
    assert "btst_governance_synthesis_status: refreshed" in markdown
    assert "btst_governance_validation_status: refreshed" in markdown
    assert "btst_independent_window_monitor_status: refreshed" in markdown
    assert "btst_tplus1_tplus2_objective_monitor_status: refreshed" in markdown
    assert "btst_candidate_pool_lane_objective_support_latest.md" in markdown
    assert "btst_candidate_pool_rebucket_objective_validation_latest.md" in markdown
    assert "btst_tradeable_opportunity_pool_refresh_status: loaded_existing" in markdown
    assert "btst_tradeable_opportunity_pool_tradeable_count: 11" in markdown
    assert "btst_tradeable_opportunity_pool_capture_rate: 0.6364" in markdown
    assert "btst_tradeable_opportunity_pool_top_no_candidate_entry_industries: ['Chip']" in markdown
    assert "btst_tradeable_opportunity_pool_top_no_candidate_entry_tickers: ['300502']" in markdown
    assert "btst_replay_cohort_status: refreshed" in markdown
    assert "## BTST 控制塔" in markdown
    assert "## 明天开盘" in markdown
    assert "btst_open_ready_delta_latest.md" in markdown
    assert "btst_latest_close_validation_latest.md" in markdown
    assert "btst_nightly_control_tower_latest.md" in markdown
    assert "btst_next_day_priority_board_20260331.md" in markdown
    assert "catalyst_theme_frontier_latest.md" in markdown
    assert "btst_opening_watch_card_20260331.md" in markdown
    assert "btst_governance_synthesis_latest.md" in markdown
    assert "btst_governance_validation_latest.md" in markdown
    assert "btst_independent_window_monitor_latest.md" in markdown
    assert "btst_tplus1_tplus2_objective_monitor_latest.md" in markdown
    assert "btst_tradeable_opportunity_pool_march.md" in markdown
    assert "btst_no_candidate_entry_action_board_latest.md" in markdown
    assert "btst_no_candidate_entry_failure_dossier_latest.md" in markdown
    assert "btst_tradeable_opportunity_reason_waterfall_march.md" in markdown
    assert "btst_replay_cohort_latest.md" in markdown
    assert "short_trade_boundary_score_failures_frontier_latest.md" in markdown
    assert "short_trade_boundary_recurring_frontier_cases_latest.md" in markdown
    assert "btst_micro_window_regression_march_refresh.md" in markdown
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
    _write_tradeable_opportunity_artifacts(reports_root)
    _write_json(
        reports_root / "btst_tplus2_continuation_promotion_review_latest.json",
        {"focus_ticker": "300720", "promotion_review_verdict": "watch_review_ready"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_promotion_gate_latest.json",
        {"focus_ticker": "300720", "gate_verdict": "approve_watchlist_promotion"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_watchlist_execution_latest.json",
        {"focus_ticker": "300720", "execution_verdict": "watchlist_extension_applied"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_eligible_gate_latest.json",
        {"focus_ticker": "300720", "gate_verdict": "approve_eligible_promotion"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_execution_gate_latest.json",
        {"focus_ticker": "300720", "gate_verdict": "approve_execution_candidate"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_execution_overlay_latest.json",
        {
            "focus_ticker": "300720",
            "execution_verdict": "execution_candidate_applied",
            "adopted_execution_row": {
                "promotion_blocker": "no_selected_persistence_or_independent_edge",
                "persistence_requirement": "selected_persistence_across_independent_windows",
                "independent_edge_requirement": "outperform_default_btst_on_independent_windows",
                "lane_support_ratio": 0.875,
                "t_plus_2_mean_gap_vs_watch": 0.067,
                "next_step": "只保留 isolated paper execution，继续验证 selected persistence。",
            },
        },
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_governance_board_latest.json",
        {"focus_promotion_ticker": "300720", "governance_status": "single_ticker_with_validation_watch"},
    )
    _write_json(
        reports_root / "btst_tplus2_continuation_watchboard_latest.json",
        {"governance_status": "single_ticker_with_validation_watch"},
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
    assert refresh["no_candidate_entry_action_board_status"] == "refreshed"
    assert refresh["no_candidate_entry_priority_queue_count"] == 1
    assert refresh["no_candidate_entry_top_tickers"] == ["300502"]
    assert refresh["no_candidate_entry_replay_bundle_status"] == "refreshed"
    assert refresh["no_candidate_entry_promising_tickers"] == []
    assert refresh["no_candidate_entry_failure_dossier_status"] == "refreshed"
    assert refresh["no_candidate_entry_failure_dossier_json"] == str((reports_root / "btst_no_candidate_entry_failure_dossier_latest.json").resolve())

    manifest = result["manifest"]
    assert manifest["catalyst_theme_frontier_refresh"] == {
        "status": "skipped_no_latest_btst_run",
    }
    assert manifest["candidate_entry_shadow_refresh"] == refresh
    assert manifest["btst_tradeable_opportunity_pool_refresh"]["status"] == "loaded_existing"
    assert manifest["btst_rollout_governance_refresh"]["status"] == "skipped_missing_inputs"
    assert manifest["btst_governance_synthesis_refresh"]["status"] == "skipped_missing_inputs"
    assert manifest["btst_governance_validation_refresh"]["status"] == "skipped_missing_inputs"
    assert manifest["btst_replay_cohort_refresh"]["status"] == "refreshed"
    assert manifest["btst_replay_cohort_refresh"]["report_count"] == 2

    window_scan = json.loads((reports_root / "btst_candidate_entry_window_scan_20260330.json").read_text(encoding="utf-8"))
    governance = json.loads((reports_root / "p9_candidate_entry_rollout_governance_20260330.json").read_text(encoding="utf-8"))
    action_board = json.loads((reports_root / "btst_no_candidate_entry_action_board_latest.json").read_text(encoding="utf-8"))
    replay_bundle = json.loads((reports_root / "btst_no_candidate_entry_replay_bundle_latest.json").read_text(encoding="utf-8"))
    failure_dossier = json.loads((reports_root / "btst_no_candidate_entry_failure_dossier_latest.json").read_text(encoding="utf-8"))
    assert window_scan["filtered_report_count"] == 1
    assert window_scan["focus_hit_report_count"] == 1
    assert window_scan["preserve_misfire_report_count"] == 0
    assert window_scan["rollout_readiness"] == "shadow_only_until_second_window"
    assert governance["lane_status"] == "shadow_only_until_second_window"
    assert governance["default_upgrade_status"] == "blocked_by_single_window_candidate_entry_signal"
    assert governance["no_candidate_entry_action_board_summary"]["top_priority_tickers"] == ["300502"]
    assert governance["no_candidate_entry_replay_bundle_summary"]["promising_priority_tickers"] == []
    assert governance["no_candidate_entry_failure_dossier_summary"]["priority_failure_class_counts"] == failure_dossier["priority_failure_class_counts"]
    assert governance["no_candidate_entry_failure_dossier_summary"]["priority_handoff_stage_counts"] == failure_dossier["priority_handoff_stage_counts"]
    assert governance["no_candidate_entry_failure_dossier_summary"]["top_candidate_entry_visible_but_not_selection_target_tickers"] == failure_dossier["top_candidate_entry_visible_but_not_selection_target_tickers"]
    watchlist_recall = json.loads((reports_root / "btst_watchlist_recall_dossier_latest.json").read_text(encoding="utf-8"))
    assert governance["watchlist_recall_dossier_summary"]["priority_recall_stage_counts"] == watchlist_recall["priority_recall_stage_counts"]
    assert governance["watchlist_recall_dossier_summary"]["top_absent_from_candidate_pool_tickers"] == watchlist_recall["top_absent_from_candidate_pool_tickers"]
    candidate_pool_recall = json.loads((reports_root / "btst_candidate_pool_recall_dossier_latest.json").read_text(encoding="utf-8"))
    rebucket_shadow_pack = json.loads((reports_root / "btst_candidate_pool_rebucket_shadow_pack_latest.json").read_text(encoding="utf-8"))
    assert governance["candidate_pool_recall_dossier_summary"]["priority_stage_counts"] == candidate_pool_recall["priority_stage_counts"]
    assert governance["candidate_pool_recall_dossier_summary"]["dominant_stage"] == candidate_pool_recall["dominant_stage"]
    assert refresh["candidate_pool_recall_dominant_liquidity_gap_mode"] == "near_cutoff_liquidity_gap"
    assert refresh["candidate_pool_recall_focus_liquidity_profiles"] == candidate_pool_recall["focus_liquidity_profile_summary"]["primary_focus_tickers"][:3]
    assert refresh["candidate_pool_recall_priority_handoff_counts"] == candidate_pool_recall["focus_liquidity_profile_summary"]["priority_handoff_counts"]
    assert refresh["candidate_pool_recall_priority_handoff_branch_diagnoses"] == candidate_pool_recall["priority_handoff_branch_diagnoses"][:3]
    assert refresh["candidate_pool_recall_priority_handoff_branch_mechanisms"] == candidate_pool_recall["priority_handoff_branch_mechanisms"][:3]
    assert refresh["candidate_pool_recall_priority_handoff_branch_experiment_queue"] == candidate_pool_recall["priority_handoff_branch_experiment_queue"][:3]
    assert rebucket_shadow_pack["shadow_status"] == "skipped_no_rebucket_candidate"
    assert rebucket_shadow_pack["experiment"] == {}
    assert refresh["candidate_pool_branch_priority_board_status"] == "refreshed"
    assert refresh["candidate_pool_branch_priority_board_rows"][0]["priority_handoff"] == "top300_boundary_micro_tuning"
    assert refresh["candidate_pool_branch_priority_alignment_status"] == "aligned_top_lane"
    assert refresh["candidate_pool_lane_objective_support_status"] == "refreshed"
    assert refresh["candidate_pool_lane_objective_support_rows"][0]["priority_handoff"] == "top300_boundary_micro_tuning"
    assert refresh["candidate_pool_corridor_validation_pack_status"] in {"parallel_probe_ready", "accumulate_more_corridor_evidence", "skipped_no_corridor_lane"}
    assert refresh["candidate_pool_corridor_validation_pack_summary"]["pack_status"] == refresh["candidate_pool_corridor_validation_pack_status"]
    assert refresh["candidate_pool_corridor_shadow_pack_status"] in {"ready_for_primary_shadow_replay", "hold_for_more_corridor_evidence", "skipped_no_corridor_lane"}
    assert refresh["candidate_pool_corridor_shadow_pack_summary"]["shadow_status"] == refresh["candidate_pool_corridor_shadow_pack_status"]
    assert refresh["candidate_pool_rebucket_shadow_pack_status"] in {"ready_for_rebucket_shadow_replay", "persistence_diagnostics_only", "skipped_no_rebucket_candidate"}
    assert refresh["candidate_pool_rebucket_shadow_pack_json"] == str((reports_root / "btst_candidate_pool_rebucket_shadow_pack_latest.json").resolve())
    assert refresh["candidate_pool_rebucket_objective_validation_status"] in {"refreshed", "skipped_no_rebucket_candidate"}
    assert refresh["candidate_pool_rebucket_comparison_bundle_status"] in {"ready_for_parallel_comparison", "keep_shadow_first", "needs_more_closed_cycle_support", "hold_structure_only", "skipped_no_rebucket_lane"}
    assert refresh["candidate_pool_rebucket_comparison_bundle_summary"]["bundle_status"] == refresh["candidate_pool_rebucket_comparison_bundle_status"]
    assert refresh["candidate_pool_lane_pair_board_status"] in {"ready_for_ranked_comparison", "await_corridor_shadow_pack", "await_rebucket_bundle", "insufficient_lane_evidence", "skipped_missing_candidates"}
    assert refresh["candidate_pool_lane_pair_board_summary"]["pair_status"] == refresh["candidate_pool_lane_pair_board_status"]
    assert "leader_governance_status" in refresh["candidate_pool_lane_pair_board_summary"]
    assert "leader_governance_execution_quality" in refresh["candidate_pool_lane_pair_board_summary"]
    assert "leader_governance_entry_timing_bias" in refresh["candidate_pool_lane_pair_board_summary"]
    assert "parallel_watch_same_source_sample_count" in refresh["candidate_pool_lane_pair_board_summary"]
    assert refresh["candidate_pool_upstream_handoff_board_status"] in {"ready_for_upstream_handoff_execution", "skipped_no_focus_tickers"}
    assert refresh["candidate_pool_upstream_handoff_board_summary"]["board_status"] == refresh["candidate_pool_upstream_handoff_board_status"]
    assert "historical_shadow_probe_tickers" in refresh["candidate_pool_upstream_handoff_board_summary"]
    assert refresh["candidate_pool_corridor_uplift_runbook_status"] in {"ready_for_upstream_uplift_probe", "skipped_no_corridor_probe"}
    assert refresh["candidate_pool_corridor_uplift_runbook_summary"]["runbook_status"] == refresh["candidate_pool_corridor_uplift_runbook_status"]
    assert result["manifest"]["continuation_focus_summary"]["focus_ticker"] == "300720"
    assert result["manifest"]["continuation_focus_summary"]["promotion_review_verdict"] == "watch_review_ready"
    assert result["manifest"]["continuation_focus_summary"]["focus_watch_validation_status"] is None
    assert result["manifest"]["continuation_focus_summary"]["execution_gate_blockers"] is None
    assert result["manifest"]["continuation_focus_summary"]["execution_overlay_verdict"] == "execution_candidate_applied"
    assert result["manifest"]["continuation_focus_summary"]["execution_overlay_promotion_blocker"] == "no_selected_persistence_or_independent_edge"
    assert result["manifest"]["continuation_focus_summary"]["execution_overlay_persistence_requirement"] == "selected_persistence_across_independent_windows"
    assert result["manifest"]["continuation_promotion_ready_summary"]["focus_ticker"] == "300720"
    assert action_board["top_priority_tickers"] == ["300502"]
    assert replay_bundle["promising_priority_tickers"] == []
    assert failure_dossier["priority_ticker_dossiers"][0]["ticker"] == "300502"

    entries_by_id = {entry["id"]: entry for entry in result["manifest"]["entries"]}
    assert entries_by_id["btst_candidate_entry_window_scan_review"]["report_path"] == "data/reports/btst_candidate_entry_window_scan_20260330.md"
    assert entries_by_id["p9_candidate_entry_rollout_governance"]["report_path"] == "data/reports/p9_candidate_entry_rollout_governance_20260330.md"
    assert entries_by_id["btst_no_candidate_entry_action_board_latest"]["report_path"] == "data/reports/btst_no_candidate_entry_action_board_latest.md"
    assert entries_by_id["btst_no_candidate_entry_replay_bundle_latest"]["report_path"] == "data/reports/btst_no_candidate_entry_replay_bundle_latest.md"
    assert entries_by_id["btst_no_candidate_entry_failure_dossier_latest"]["report_path"] == "data/reports/btst_no_candidate_entry_failure_dossier_latest.md"
    assert entries_by_id["btst_watchlist_recall_dossier_latest"]["report_path"] == "data/reports/btst_watchlist_recall_dossier_latest.md"
    assert entries_by_id["btst_candidate_pool_recall_dossier_latest"]["report_path"] == "data/reports/btst_candidate_pool_recall_dossier_latest.md"
    assert entries_by_id["btst_candidate_pool_corridor_validation_pack_latest"]["report_path"] == "data/reports/btst_candidate_pool_corridor_validation_pack_latest.md"
    assert entries_by_id["btst_candidate_pool_corridor_shadow_pack_latest"]["report_path"] == "data/reports/btst_candidate_pool_corridor_shadow_pack_latest.md"
    assert entries_by_id["btst_candidate_pool_rebucket_comparison_bundle_latest"]["report_path"] == "data/reports/btst_candidate_pool_rebucket_comparison_bundle_latest.md"
    assert entries_by_id["btst_candidate_pool_lane_pair_board_latest"]["report_path"] == "data/reports/btst_candidate_pool_lane_pair_board_latest.md"
    assert entries_by_id["btst_candidate_pool_upstream_handoff_board_latest"]["report_path"] == "data/reports/btst_candidate_pool_upstream_handoff_board_latest.md"
    assert entries_by_id["btst_candidate_pool_corridor_uplift_runbook_latest"]["report_path"] == "data/reports/btst_candidate_pool_corridor_uplift_runbook_latest.md"

    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "candidate_entry_shadow_refresh_status: refreshed" in markdown
    assert "candidate_entry_shadow_refresh_window_reports: 2" in markdown
    assert "candidate_entry_shadow_refresh_filtered_reports: 1" in markdown
    assert "candidate_entry_shadow_refresh_rollout_readiness: shadow_only_until_second_window" in markdown
    assert "candidate_entry_shadow_no_candidate_entry_action_board_status: refreshed" in markdown
    assert "candidate_entry_shadow_no_candidate_entry_priority_queue_count: 1" in markdown
    assert "candidate_entry_shadow_no_candidate_entry_top_tickers: ['300502']" in markdown
    assert "candidate_entry_shadow_no_candidate_entry_replay_bundle_status: refreshed" in markdown
    assert "candidate_entry_shadow_no_candidate_entry_promising_tickers: []" in markdown
    assert "candidate_entry_shadow_no_candidate_entry_failure_dossier_status: refreshed" in markdown
    assert "candidate_entry_shadow_watchlist_recall_dossier_status: refreshed" in markdown
    assert "candidate_entry_shadow_watchlist_recall_absent_from_candidate_pool_tickers: ['300502']" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_dossier_status: refreshed" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_dominant_stage: candidate_pool_truncated_after_filters" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_truncation_frontier_summary:" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_dominant_liquidity_gap_mode: near_cutoff_liquidity_gap" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_focus_liquidity_profiles:" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_priority_handoff_counts:" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_priority_handoff_branch_diagnoses:" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_priority_handoff_branch_mechanisms:" in markdown
    assert "candidate_entry_shadow_candidate_pool_recall_priority_handoff_branch_experiment_queue:" in markdown
    assert "candidate_entry_shadow_candidate_pool_branch_priority_board_status:" in markdown
    assert "candidate_entry_shadow_candidate_pool_branch_priority_alignment_status:" in markdown
    assert "candidate_entry_shadow_candidate_pool_lane_objective_support_status:" in markdown
    assert "candidate_entry_shadow_candidate_pool_corridor_validation_pack_status:" in markdown
    assert "candidate_entry_shadow_candidate_pool_corridor_shadow_pack_status:" in markdown
    assert "candidate_entry_shadow_candidate_pool_rebucket_shadow_pack_status:" in markdown
    assert "candidate_entry_shadow_candidate_pool_rebucket_objective_validation_status:" in markdown
    assert "candidate_entry_shadow_candidate_pool_rebucket_comparison_bundle_status:" in markdown
    assert "candidate_entry_shadow_candidate_pool_lane_pair_board_status:" in markdown
    assert "candidate_entry_shadow_candidate_pool_upstream_handoff_board_status:" in markdown
    assert "candidate_entry_shadow_candidate_pool_corridor_uplift_runbook_status:" in markdown
    assert "btst_tradeable_opportunity_pool_refresh_status: loaded_existing" in markdown
    assert "btst_rollout_governance_refresh_status: skipped_missing_inputs" in markdown
    assert "btst_governance_synthesis_status: skipped_missing_inputs" in markdown
    assert "btst_governance_validation_status: skipped_missing_inputs" in markdown
    assert "btst_replay_cohort_status: refreshed" in markdown


def test_collect_governance_synthesis_evidence_dirs_uses_upstream_handoff_followups(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        reports_root / "btst_candidate_pool_upstream_handoff_board_latest.json",
        {
            "board_rows": [
                {"latest_followup_report_dir": "/tmp/reports/corridor_300720"},
                {"latest_followup_report_dir": "/tmp/reports/rebucket_301292"},
                {"latest_followup_report_dir": "/tmp/reports/corridor_300720"},
            ]
        },
    )

    evidence_dirs = _collect_governance_synthesis_evidence_dirs(
        reports_root,
        latest_btst_run={"report_dir": "/tmp/reports/latest_short_trade"},
    )

    assert evidence_dirs == [
        "/tmp/reports/latest_short_trade",
        "/tmp/reports/corridor_300720",
        "/tmp/reports/rebucket_301292",
    ]


def test_build_transient_probe_summary_reads_historical_shadow_probe_row(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        reports_root / "btst_candidate_pool_upstream_handoff_board_latest.json",
        {
            "board_rows": [
                {
                    "ticker": "301292",
                    "board_phase": "historical_shadow_probe_gap",
                    "downstream_followup_status": "transient_probe_only",
                    "downstream_followup_blocker": "shadow_recall_not_persistent",
                    "latest_followup_candidate_source": "post_gate_liquidity_competition_shadow",
                    "latest_followup_gate_status": {"score": "fail"},
                    "next_step": "先补 persistence diagnostics。",
                }
            ]
        },
    )

    summary = _build_transient_probe_summary(reports_root)

    assert summary["ticker"] == "301292"
    assert summary["status"] == "transient_probe_only"
    assert summary["blocker"] == "shadow_recall_not_persistent"
    assert summary["candidate_source"] == "post_gate_liquidity_competition_shadow"
    assert summary["score_state"] == "fail"


def test_build_execution_constraint_rollup_summarizes_continuation_and_shadow_blocks(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        reports_root / "btst_governance_synthesis_latest.json",
        {
            "execution_surface_constraints": [
                {
                    "status": "continuation_only_confirm_then_review",
                    "blocker": "no_selected_persistence_or_independent_edge",
                    "focus_tickers": ["300720"],
                    "recommendation": "Keep continuation review isolated.",
                },
                {
                    "status": "shadow_recall_not_execution_ready",
                    "blocker": "profitability_hard_cliff_and_score_gap",
                    "focus_tickers": ["301292"],
                    "recommendation": "Keep shadow recall names diagnostic-only.",
                },
            ]
        },
    )

    summary = _build_execution_constraint_rollup(reports_root)

    assert summary["constraint_count"] == 2
    assert summary["continuation_focus_tickers"] == ["300720"]
    assert summary["shadow_focus_tickers"] == ["301292"]


def test_build_continuation_promotion_ready_summary_quantifies_gap_vs_default_btst(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        reports_root / "btst_tplus2_continuation_execution_overlay_latest.json",
        {
            "focus_ticker": "300720",
            "adopted_execution_row": {
                "ticker": "300720",
                "t_plus_2_close_positive_rate": 0.8667,
                "t_plus_2_close_return_mean": 0.0787,
            },
        },
    )
    _write_json(
        reports_root / "btst_governance_synthesis_latest.json",
        {
            "evidence_btst_followups": [
                {
                    "trade_date": "2026-03-31",
                    "report_dir": "/tmp/reports/continuation_300720",
                    "entries": [{"ticker": "300720", "bucket": "near_miss_entries"}],
                }
            ]
        },
    )
    _write_json(
        reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json",
        {
            "tradeable_surface": {
                "t_plus_2_positive_rate": 0.4706,
                "mean_t_plus_2_return": -0.0057,
            }
        },
    )

    summary = _build_continuation_promotion_ready_summary(reports_root)

    assert summary["focus_ticker"] == "300720"
    assert summary["promotion_path_status"] == "collect_more_independent_windows"
    assert summary["blockers_remaining_count"] == 1
    assert summary["unresolved_requirements"] == ["new_independent_trade_date"]
    assert summary["observed_independent_window_count"] == 0
    assert summary["missing_independent_window_count"] == 2
    assert summary["provisional_default_btst_edge_verdict"] == "provisionally_outperforming_default_btst"
    assert summary["edge_threshold_verdict"] == "edge_threshold_satisfied"
    assert summary["promotion_merge_review_verdict"] == "await_additional_independent_window_persistence"
    assert summary["ready_after_next_qualifying_window"] is False
    assert summary["next_window_requirement"] == "collect_additional_independent_window_and_recheck_edge_thresholds"
    assert summary["next_window_duplicate_trade_date_verdict"] == "independent_window_count_unchanged"
    assert summary["next_window_quality_requirement"] == "must land in selected_entries"
    assert summary["next_window_disqualified_bucket_verdict"] == "await_higher_quality_window_bucket"
    assert summary["qualifying_window_buckets"] == ["near_miss_entries"]
    assert summary["merge_ready_window_buckets"] == []
    assert summary["next_window_qualified_merge_review_verdict"] == "await_additional_independent_window_persistence"


def test_build_continuation_promotion_ready_summary_duplicate_trade_dates_do_not_count_as_independent_windows(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        reports_root / "btst_tplus2_continuation_execution_overlay_latest.json",
        {
            "focus_ticker": "300720",
            "adopted_execution_row": {
                "ticker": "300720",
                "t_plus_2_close_positive_rate": 0.8667,
                "t_plus_2_close_return_mean": 0.0787,
            },
        },
    )
    _write_json(
        reports_root / "btst_governance_synthesis_latest.json",
        {
            "evidence_btst_followups": [
                {
                    "trade_date": "2026-03-31",
                    "report_dir": "/tmp/reports/continuation_300720_a",
                    "entries": [{"ticker": "300720", "bucket": "near_miss_entries"}],
                },
                {
                    "trade_date": "2026-03-31",
                    "report_dir": "/tmp/reports/continuation_300720_b",
                    "entries": [{"ticker": "300720", "bucket": "near_miss_entries"}],
                },
            ]
        },
    )
    _write_json(
        reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json",
        {
            "tradeable_surface": {
                "t_plus_2_positive_rate": 0.4706,
                "mean_t_plus_2_return": -0.0057,
            }
        },
    )

    summary = _build_continuation_promotion_ready_summary(reports_root)

    assert summary["observed_independent_window_count"] == 0
    assert summary["missing_independent_window_count"] == 2
    assert summary["evidence_trade_dates"] == ["2026-03-31"]
    assert summary["merge_ready_evidence_trade_dates"] == []
    assert summary["next_window_trade_date_rule"] == "must be a new trade_date outside ['2026-03-31']"
    assert summary["next_window_duplicate_trade_date_verdict"] == "independent_window_count_unchanged"


def test_build_continuation_promotion_ready_summary_same_trade_date_selected_evidence_wins_bucket(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        reports_root / "btst_tplus2_continuation_execution_overlay_latest.json",
        {
            "focus_ticker": "300720",
            "adopted_execution_row": {
                "ticker": "300720",
                "t_plus_2_close_positive_rate": 0.8667,
                "t_plus_2_close_return_mean": 0.0787,
            },
        },
    )
    _write_json(
        reports_root / "btst_governance_synthesis_latest.json",
        {
            "evidence_btst_followups": [
                {
                    "trade_date": "2026-03-31",
                    "report_dir": "/tmp/reports/continuation_300720_old",
                    "entries": [{"ticker": "300720", "bucket": "near_miss_entries"}],
                },
                {
                    "trade_date": "2026-03-31",
                    "report_dir": "/tmp/reports/continuation_300720_new",
                    "entries": [{"ticker": "300720", "bucket": "selected_entries"}],
                },
            ]
        },
    )
    _write_json(
        reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json",
        {
            "tradeable_surface": {
                "t_plus_2_positive_rate": 0.4706,
                "mean_t_plus_2_return": -0.0057,
            }
        },
    )

    summary = _build_continuation_promotion_ready_summary(reports_root)

    assert summary["observed_independent_window_count"] == 1
    assert summary["evidence_trade_dates"] == ["2026-03-31"]
    assert summary["qualifying_window_buckets"] == ["selected_entries"]


def test_build_continuation_promotion_ready_summary_dossier_same_day_variants_do_not_add_independent_windows(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        reports_root / "btst_tplus2_continuation_execution_overlay_latest.json",
        {
            "focus_ticker": "300720",
            "adopted_execution_row": {
                "ticker": "300720",
                "t_plus_2_close_positive_rate": 0.8667,
                "t_plus_2_close_return_mean": 0.0787,
            },
        },
    )
    _write_json(
        reports_root / "btst_governance_synthesis_latest.json",
        {
            "evidence_btst_followups": [
                {
                    "trade_date": "2026-03-31",
                    "report_dir": "/tmp/reports/continuation_300720",
                    "entries": [{"ticker": "300720", "bucket": "near_miss_entries"}],
                }
            ]
        },
    )
    _write_json(
        reports_root / "btst_tplus2_candidate_dossier_300720_latest.json",
        {
            "recent_supporting_window_count": 3,
            "recent_window_count": 4,
            "recent_validation_verdict": "governance_followup_pending_evidence",
            "recent_tier_verdict": "governance_followup_payoff_confirmed",
            "current_plan_visibility_summary": {
                "raw_daily_events_trade_dates": ["2026-03-27", "2026-03-31"],
                "raw_daily_events_trade_date_count": 2,
                "current_plan_visible_trade_dates": ["2026-03-31"],
                "current_plan_visible_trade_date_count": 1,
                "current_plan_visibility_gap_trade_dates": ["2026-03-27"],
                "current_plan_visibility_gap_trade_date_count": 1,
            },
            "recent_window_summaries": [
                    {"report_label": "20260331", "supporting_window": True, "decision": "selected", "report_dir": "/tmp/reports/a"},
                    {"report_label": "20260331", "supporting_window": True, "decision": "selected", "report_dir": "/tmp/reports/b"},
                    {"report_label": "20260331", "supporting_window": True, "decision": "selected", "report_dir": "/tmp/reports/c"},
                    {"report_label": "20260331", "supporting_window": False, "report_dir": "/tmp/reports/d"},
                ],
            },
    )
    _write_json(
        reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json",
        {
            "tradeable_surface": {
                "t_plus_2_positive_rate": 0.4706,
                "mean_t_plus_2_return": -0.0057,
            }
        },
    )

    summary = _build_continuation_promotion_ready_summary(reports_root)

    assert summary["observed_independent_window_count"] == 1
    assert summary["combined_merge_ready_evidence_trade_dates"] == ["2026-03-31"]
    assert summary["candidate_dossier_support_trade_date_count"] == 1
    assert summary["candidate_dossier_selected_support_trade_date_count"] == 1
    assert summary["candidate_dossier_supporting_window_variant_count"] == 3
    assert summary["candidate_dossier_same_trade_date_variant_count"] == 2
    assert summary["candidate_dossier_same_trade_date_variant_credit"] == 0.5
    assert summary["weighted_observed_window_credit"] == 1.5
    assert summary["weighted_missing_window_credit"] == 0.5
    assert summary["candidate_dossier_current_plan_visible_trade_dates"] == ["2026-03-31"]
    assert summary["candidate_dossier_current_plan_visibility_gap_trade_dates"] == ["2026-03-27"]
    assert summary["candidate_dossier_raw_daily_events_trade_dates"] == ["2026-03-27", "2026-03-31"]
    assert summary["candidate_dossier_recent_supporting_window_count"] == 3
    assert summary["candidate_dossier_recent_tier_verdict"] == "governance_followup_payoff_confirmed"


def test_build_continuation_promotion_ready_summary_dossier_second_trade_date_advances_window_count(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        reports_root / "btst_tplus2_continuation_execution_overlay_latest.json",
        {
            "focus_ticker": "300720",
            "adopted_execution_row": {
                "ticker": "300720",
                "t_plus_2_close_positive_rate": 0.8667,
                "t_plus_2_close_return_mean": 0.0787,
            },
        },
    )
    _write_json(
        reports_root / "btst_governance_synthesis_latest.json",
        {
            "evidence_btst_followups": [
                {
                    "trade_date": "2026-03-31",
                    "report_dir": "/tmp/reports/continuation_300720",
                    "entries": [{"ticker": "300720", "bucket": "near_miss_entries"}],
                }
            ]
        },
    )
    _write_json(
        reports_root / "btst_tplus2_candidate_dossier_300720_latest.json",
        {
            "recent_supporting_window_count": 2,
            "recent_window_count": 2,
            "recent_validation_verdict": "governance_followup_payoff_confirmed",
            "recent_tier_verdict": "governance_followup_payoff_confirmed",
            "recent_window_summaries": [
                    {"report_label": "20260331", "supporting_window": True, "decision": "selected", "report_dir": "/tmp/reports/a"},
                    {"report_label": "20260401", "supporting_window": True, "decision": "selected", "report_dir": "/tmp/reports/b"},
                ],
            },
        )
    _write_json(
        reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json",
        {
            "tradeable_surface": {
                "t_plus_2_positive_rate": 0.4706,
                "mean_t_plus_2_return": -0.0057,
            }
        },
    )

    summary = _build_continuation_promotion_ready_summary(reports_root)

    assert summary["candidate_dossier_support_trade_date_count"] == 2
    assert summary["candidate_dossier_selected_support_trade_date_count"] == 2
    assert summary["combined_merge_ready_evidence_trade_dates"] == ["2026-03-31", "2026-04-01"]
    assert summary["observed_independent_window_count"] == 2
    assert summary["weighted_observed_window_credit"] == 2.0
    assert summary["weighted_missing_window_credit"] == 0.0
    assert summary["missing_independent_window_count"] == 0
    assert summary["promotion_merge_review_verdict"] == "ready_for_default_btst_merge_review"


def test_build_continuation_promotion_ready_summary_rejected_second_window_does_not_qualify(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        reports_root / "btst_tplus2_continuation_execution_overlay_latest.json",
        {
            "focus_ticker": "300720",
            "adopted_execution_row": {
                "ticker": "300720",
                "t_plus_2_close_positive_rate": 0.8667,
                "t_plus_2_close_return_mean": 0.0787,
            },
        },
    )
    _write_json(
        reports_root / "btst_governance_synthesis_latest.json",
        {
            "evidence_btst_followups": [
                {
                    "trade_date": "2026-03-31",
                    "report_dir": "/tmp/reports/continuation_300720_a",
                    "entries": [{"ticker": "300720", "bucket": "selected_entries"}],
                },
                {
                    "trade_date": "2026-04-01",
                    "report_dir": "/tmp/reports/continuation_300720_b",
                    "entries": [{"ticker": "300720", "bucket": "rejected_entries"}],
                },
            ]
        },
    )
    _write_json(
        reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json",
        {
            "tradeable_surface": {
                "t_plus_2_positive_rate": 0.4706,
                "mean_t_plus_2_return": -0.0057,
            }
        },
    )

    summary = _build_continuation_promotion_ready_summary(reports_root)

    assert summary["observed_independent_window_count"] == 1
    assert summary["missing_independent_window_count"] == 1
    assert summary["promotion_path_status"] == "one_qualifying_window_away"
    assert summary["disqualified_window_trade_dates"] == ["2026-04-01"]
    assert summary["disqualified_window_buckets"] == ["rejected_entries"]
    assert summary["next_window_quality_requirement"] == "must land in selected_entries"
    assert summary["next_window_disqualified_bucket_verdict"] == "await_higher_quality_window_bucket"


def test_build_continuation_promotion_ready_summary_two_windows_with_weak_edge_stay_blocked(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        reports_root / "btst_tplus2_continuation_execution_overlay_latest.json",
        {
            "focus_ticker": "300720",
            "adopted_execution_row": {
                "ticker": "300720",
                "t_plus_2_close_positive_rate": 0.5,
                "t_plus_2_close_return_mean": 0.0,
            },
        },
    )
    _write_json(
        reports_root / "btst_governance_synthesis_latest.json",
        {
            "evidence_btst_followups": [
                {
                    "trade_date": "2026-03-31",
                    "report_dir": "/tmp/reports/continuation_300720_a",
                    "entries": [{"ticker": "300720", "bucket": "selected_entries"}],
                },
                {
                    "trade_date": "2026-04-01",
                    "report_dir": "/tmp/reports/continuation_300720_b",
                    "entries": [{"ticker": "300720", "bucket": "selected_entries"}],
                },
            ]
        },
    )
    _write_json(
        reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json",
        {
            "tradeable_surface": {
                "t_plus_2_positive_rate": 0.4706,
                "mean_t_plus_2_return": -0.0057,
            }
        },
    )

    summary = _build_continuation_promotion_ready_summary(reports_root)

    assert summary["promotion_path_status"] == "repair_edge_threshold"
    assert summary["blockers_remaining_count"] == 1
    assert summary["unresolved_requirements"] == ["edge_threshold_vs_default_btst"]
    assert summary["observed_independent_window_count"] == 2
    assert summary["persistence_verdict"] == "independent_window_requirement_satisfied"
    assert summary["edge_threshold_verdict"] == "edge_threshold_not_satisfied"
    assert summary["promotion_merge_review_verdict"] == "await_stronger_edge_vs_default_btst"
    assert summary["next_window_edge_regression_merge_review_verdict"] == "await_stronger_edge_vs_default_btst"
