from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_governance_synthesis import analyze_btst_governance_synthesis
from scripts.analyze_btst_replay_cohort import analyze_btst_replay_cohort
from scripts.run_btst_nightly_control_tower import _prioritize_control_tower_next_actions, build_btst_nightly_control_tower_payload, build_btst_open_ready_delta_payload, generate_btst_nightly_control_tower_artifacts, render_btst_nightly_control_tower_markdown
from scripts.validate_btst_governance_consistency import validate_btst_governance_consistency
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


def test_build_btst_nightly_control_tower_payload_surfaces_default_merge_review() -> None:
    manifest = {
        "reports_root": "/tmp/reports",
        "entries": [
            {"id": "btst_governance_synthesis_latest", "report_path": "data/reports/btst_governance_synthesis_latest.md", "question": "gov", "absolute_path": "/tmp/reports/btst_governance_synthesis_latest.md"},
            {"id": "btst_tplus1_tplus2_objective_monitor_latest", "report_path": "data/reports/btst_tplus1_tplus2_objective_monitor_latest.md", "question": "obj", "absolute_path": "/tmp/reports/btst_tplus1_tplus2_objective_monitor_latest.md"},
            {"id": "btst_independent_window_monitor_latest", "report_path": "data/reports/btst_independent_window_monitor_latest.md", "question": "window", "absolute_path": "/tmp/reports/btst_independent_window_monitor_latest.md"},
            {"id": "btst_default_merge_review_latest", "report_path": "data/reports/btst_default_merge_review_latest.md", "question": "merge", "absolute_path": "/tmp/reports/btst_default_merge_review_latest.md"},
            {"id": "btst_default_merge_historical_counterfactual_latest", "report_path": "data/reports/btst_default_merge_historical_counterfactual_latest.md", "question": "merge-historical", "absolute_path": "/tmp/reports/btst_default_merge_historical_counterfactual_latest.md"},
            {"id": "btst_continuation_merge_candidate_ranking_latest", "report_path": "data/reports/btst_continuation_merge_candidate_ranking_latest.md", "question": "merge-ranking", "absolute_path": "/tmp/reports/btst_continuation_merge_candidate_ranking_latest.md"},
            {"id": "btst_default_merge_strict_counterfactual_latest", "report_path": "data/reports/btst_default_merge_strict_counterfactual_latest.md", "question": "merge-strict", "absolute_path": "/tmp/reports/btst_default_merge_strict_counterfactual_latest.md"},
            {"id": "btst_merge_replay_validation_latest", "report_path": "data/reports/btst_merge_replay_validation_latest.md", "question": "merge-replay", "absolute_path": "/tmp/reports/btst_merge_replay_validation_latest.md"},
            {"id": "btst_prepared_breakout_relief_validation_latest", "report_path": "data/reports/btst_prepared_breakout_relief_validation_latest.md", "question": "prepared-breakout", "absolute_path": "/tmp/reports/btst_prepared_breakout_relief_validation_latest.md"},
            {"id": "btst_prepared_breakout_cohort_latest", "report_path": "data/reports/btst_prepared_breakout_cohort_latest.md", "question": "prepared-breakout-cohort", "absolute_path": "/tmp/reports/btst_prepared_breakout_cohort_latest.md"},
            {"id": "btst_prepared_breakout_residual_surface_latest", "report_path": "data/reports/btst_prepared_breakout_residual_surface_latest.md", "question": "prepared-breakout-residual", "absolute_path": "/tmp/reports/btst_prepared_breakout_residual_surface_latest.md"},
            {"id": "btst_candidate_pool_corridor_persistence_dossier_latest", "report_path": "data/reports/btst_candidate_pool_corridor_persistence_dossier_latest.md", "question": "corridor-persistence", "absolute_path": "/tmp/reports/btst_candidate_pool_corridor_persistence_dossier_latest.md"},
            {"id": "btst_candidate_pool_corridor_window_command_board_latest", "report_path": "data/reports/btst_candidate_pool_corridor_window_command_board_latest.md", "question": "corridor-window-command", "absolute_path": "/tmp/reports/btst_candidate_pool_corridor_window_command_board_latest.md"},
            {"id": "btst_candidate_pool_corridor_window_diagnostics_latest", "report_path": "data/reports/btst_candidate_pool_corridor_window_diagnostics_latest.md", "question": "corridor-window-diagnostics", "absolute_path": "/tmp/reports/btst_candidate_pool_corridor_window_diagnostics_latest.md"},
            {"id": "btst_candidate_pool_corridor_narrow_probe_latest", "report_path": "data/reports/btst_candidate_pool_corridor_narrow_probe_latest.md", "question": "corridor-narrow-probe", "absolute_path": "/tmp/reports/btst_candidate_pool_corridor_narrow_probe_latest.md"},
        ],
        "default_merge_review_summary": {
            "focus_ticker": "300720",
            "merge_review_verdict": "ready_for_default_btst_merge_review",
            "operator_action": "review_default_btst_merge",
            "recommendation": "Promote 300720 into explicit default BTST merge review.",
            "t_plus_2_positive_rate_delta_vs_default_btst": 0.3961,
            "t_plus_2_mean_return_delta_vs_default_btst": 0.0844,
            "counterfactual_validation": {
                "counterfactual_verdict": "supports_default_btst_merge",
                "t_plus_2_positive_rate_margin_vs_threshold": 0.2961,
                "t_plus_2_mean_return_margin_vs_threshold": 0.0644,
            },
        },
        "default_merge_historical_counterfactual_summary": {
            "focus_ticker": "300720",
            "counterfactual_verdict": "merged_default_btst_uplift_positive",
            "uplift_vs_default_btst": {
                "t_plus_2_positive_rate_uplift": 0.1857,
                "mean_t_plus_2_return_uplift": 0.0394,
            },
        },
        "continuation_merge_candidate_ranking_summary": {
            "candidate_count": 2,
            "top_candidate": {
                "ticker": "300720",
                "promotion_path_status": "merge_review_ready",
                "t_plus_2_positive_rate_delta_vs_default_btst": 0.3961,
                "mean_t_plus_2_return_delta_vs_default_btst": 0.0844,
            },
        },
        "default_merge_strict_counterfactual_summary": {
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
        "merge_replay_validation_summary": {
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
        "prepared_breakout_relief_validation_summary": {
            "focus_ticker": "300505",
            "verdict": "prepared_breakout_selected_relief_supported",
            "selected_relief_window_count": 4,
            "selected_relief_alignment_rate": 1.0,
            "outcome_support": {"evidence_status": "strong_t1_t2_support"},
        },
        "prepared_breakout_cohort_summary": {
            "candidate_count": 2,
            "selected_frontier_candidate_count": 1,
            "verdict": "selected_frontier_peer_found",
            "next_candidate": {"ticker": "000792"},
        },
        "prepared_breakout_residual_surface_summary": {
            "focus_ticker": "600988",
            "verdict": "non_actionable_score_surface",
            "focus_report_dir_count": 5,
        },
        "candidate_pool_corridor_persistence_dossier_summary": {
            "focus_ticker": "300720",
            "verdict": "await_second_independent_selected_window",
            "next_confirmation_requirement": "300720 still needs 1 independent selected sample.",
        },
        "candidate_pool_corridor_window_command_board_summary": {
            "focus_ticker": "300720",
            "verdict": "collect_one_more_selected_window",
            "next_target_trade_dates": ["2026-04-06", "2026-03-27"],
        },
        "candidate_pool_corridor_window_diagnostics_summary": {
            "focus_ticker": "300720",
            "near_miss_upgrade_window": {"trade_date": "2026-04-06", "verdict": "narrow_selected_gap_candidate"},
            "visibility_gap_window": {"verdict": "recoverable_current_plan_visibility_gap", "recoverable_report_dir_count": 5},
            "recommendation": "Prioritize 2026-04-06; treat 2026-03-27 as visibility audit.",
        },
        "candidate_pool_corridor_narrow_probe_summary": {
            "focus_ticker": "300720",
            "verdict": "lane_specific_select_threshold_override_gap",
            "threshold_override_gap_vs_anchor": 0.13,
            "target_gap_to_selected": 0.1245,
        },
    }

    payload = build_btst_nightly_control_tower_payload(manifest)

    assert payload["recommended_reading_order"][3]["entry_id"] == "btst_default_merge_review_latest"
    assert payload["recommended_reading_order"][4]["entry_id"] == "btst_default_merge_historical_counterfactual_latest"
    assert payload["recommended_reading_order"][5]["entry_id"] == "btst_continuation_merge_candidate_ranking_latest"
    assert payload["recommended_reading_order"][6]["entry_id"] == "btst_default_merge_strict_counterfactual_latest"
    assert payload["recommended_reading_order"][7]["entry_id"] == "btst_merge_replay_validation_latest"
    assert payload["recommended_reading_order"][8]["entry_id"] == "btst_prepared_breakout_relief_validation_latest"
    assert payload["recommended_reading_order"][9]["entry_id"] == "btst_prepared_breakout_cohort_latest"
    assert payload["recommended_reading_order"][10]["entry_id"] == "btst_prepared_breakout_residual_surface_latest"
    assert payload["recommended_reading_order"][11]["entry_id"] == "btst_candidate_pool_corridor_persistence_dossier_latest"
    assert payload["recommended_reading_order"][12]["entry_id"] == "btst_candidate_pool_corridor_window_command_board_latest"
    assert payload["recommended_reading_order"][13]["entry_id"] == "btst_candidate_pool_corridor_window_diagnostics_latest"
    assert payload["recommended_reading_order"][14]["entry_id"] == "btst_candidate_pool_corridor_narrow_probe_latest"
    assert payload["control_tower_snapshot"]["default_merge_review_summary"]["focus_ticker"] == "300720"
    assert payload["control_tower_snapshot"]["default_merge_review_summary"]["counterfactual_validation"]["counterfactual_verdict"] == "supports_default_btst_merge"
    assert payload["control_tower_snapshot"]["default_merge_historical_counterfactual_summary"]["counterfactual_verdict"] == "merged_default_btst_uplift_positive"
    assert payload["control_tower_snapshot"]["continuation_merge_candidate_ranking_summary"]["top_candidate"]["ticker"] == "300720"
    assert payload["control_tower_snapshot"]["default_merge_strict_counterfactual_summary"]["strict_counterfactual_verdict"] == "strict_merge_uplift_positive"
    assert payload["control_tower_snapshot"]["merge_replay_validation_summary"]["overall_verdict"] == "merge_replay_promotes_selected"
    assert payload["control_tower_snapshot"]["merge_replay_validation_summary"]["relief_actionable_applied_count"] == 1
    assert payload["control_tower_snapshot"]["merge_replay_validation_summary"]["relief_already_selected_count"] == 1
    assert payload["control_tower_snapshot"]["merge_replay_validation_summary"]["relief_actionable_positive_promotion_precision"] == 1.0
    assert payload["control_tower_snapshot"]["merge_replay_validation_summary"]["relief_actionable_no_promotion_ratio"] == 0.0
    assert payload["control_tower_snapshot"]["merge_replay_validation_summary"]["recommended_next_lever"] == "execution_signal"
    assert payload["control_tower_snapshot"]["merge_replay_validation_summary"]["recommended_signal_levers"] == ["trend_acceleration", "breakout_freshness"]
    assert payload["control_tower_snapshot"]["prepared_breakout_relief_validation_summary"]["focus_ticker"] == "300505"
    assert payload["control_tower_snapshot"]["prepared_breakout_relief_validation_summary"]["verdict"] == "prepared_breakout_selected_relief_supported"
    assert payload["control_tower_snapshot"]["prepared_breakout_cohort_summary"]["next_candidate"]["ticker"] == "000792"
    assert payload["control_tower_snapshot"]["prepared_breakout_residual_surface_summary"]["focus_ticker"] == "600988"
    assert payload["control_tower_snapshot"]["candidate_pool_corridor_persistence_dossier_summary"]["focus_ticker"] == "300720"
    assert payload["control_tower_snapshot"]["candidate_pool_corridor_window_command_board_summary"]["focus_ticker"] == "300720"
    assert payload["control_tower_snapshot"]["candidate_pool_corridor_window_diagnostics_summary"]["focus_ticker"] == "300720"
    assert payload["control_tower_snapshot"]["candidate_pool_corridor_narrow_probe_summary"]["verdict"] == "lane_specific_select_threshold_override_gap"
    assert payload["merge_replay_validation_summary"]["overall_verdict"] == "merge_replay_promotes_selected"
    assert payload["merge_replay_validation_summary"]["relief_actionable_applied_count"] == 1
    assert payload["merge_replay_validation_summary"]["relief_already_selected_count"] == 1
    assert payload["merge_replay_validation_summary"]["recommended_signal_levers"] == ["trend_acceleration", "breakout_freshness"]
    assert payload["prepared_breakout_relief_validation_summary"]["selected_relief_alignment_rate"] == 1.0
    assert payload["prepared_breakout_cohort_summary"]["selected_frontier_candidate_count"] == 1
    assert payload["prepared_breakout_residual_surface_summary"]["verdict"] == "non_actionable_score_surface"
    assert payload["candidate_pool_corridor_persistence_dossier_summary"]["verdict"] == "await_second_independent_selected_window"
    assert payload["candidate_pool_corridor_window_command_board_summary"]["verdict"] == "collect_one_more_selected_window"
    assert payload["candidate_pool_corridor_window_diagnostics_summary"]["visibility_gap_window"]["verdict"] == "recoverable_current_plan_visibility_gap"


def test_build_btst_open_ready_delta_payload_surfaces_carryover_promotion_gate_changes(tmp_path: Path) -> None:
    current_payload = {
        "generated_at": "2026-04-10T08:00:00",
        "latest_btst_run": {
            "report_dir": "data/reports/report_b",
            "report_dir_abs": str(tmp_path / "data" / "reports" / "report_b"),
            "selection_target": "short_trade_only",
        },
        "latest_priority_board_snapshot": {"headline": "headline-b"},
        "latest_btst_snapshot": {},
        "control_tower_snapshot": {
            "carryover_peer_promotion_gate_summary": {
                "selected_contract_verdict": "pending_next_day",
                "focus_ticker": "300408",
                "focus_gate_verdict": "await_peer_t_plus_2_close",
                "ready_tickers": [],
                "blocked_open_tickers": [],
                "pending_t_plus_2_tickers": ["300408"],
            }
        },
        "source_paths": {},
    }
    previous_payload = {
        "generated_at": "2026-04-10T07:30:00",
        "latest_btst_run": {
            "report_dir": "data/reports/report_a",
            "report_dir_abs": str(tmp_path / "data" / "reports" / "report_a"),
            "selection_target": "short_trade_only",
        },
        "latest_priority_board_snapshot": {"headline": "headline-a"},
        "latest_btst_snapshot": {},
        "control_tower_snapshot": {
            "carryover_peer_promotion_gate_summary": {
                "selected_contract_verdict": "pending_next_day",
                "focus_ticker": "301396",
                "focus_gate_verdict": "await_peer_next_day_close",
                "ready_tickers": [],
                "blocked_open_tickers": [],
                "pending_t_plus_2_tickers": [],
            }
        },
        "source_paths": {},
    }

    delta_payload = build_btst_open_ready_delta_payload(
        current_payload,
        reports_root=tmp_path / "data" / "reports",
        current_nightly_json_path=tmp_path / "data" / "reports" / "btst_nightly_control_tower_latest.json",
        previous_payload=previous_payload,
        previous_payload_path=str(tmp_path / "data" / "reports" / "history.json"),
        historical_payload_candidates=[],
    )

    assert delta_payload["carryover_promotion_gate_delta"]["current_focus_ticker"] == "300408"
    assert delta_payload["carryover_promotion_gate_delta"]["previous_focus_ticker"] == "301396"
    assert delta_payload["carryover_promotion_gate_delta"]["current_focus_gate_verdict"] == "await_peer_t_plus_2_close"
    assert delta_payload["carryover_promotion_gate_delta"]["previous_focus_gate_verdict"] == "await_peer_next_day_close"
    assert delta_payload["carryover_promotion_gate_delta"]["added_pending_t_plus_2_tickers"] == ["300408"]
    assert any("carryover promotion gate" in item for item in delta_payload["operator_focus"])


def test_build_btst_open_ready_delta_payload_surfaces_selected_contract_changes(tmp_path: Path) -> None:
    current_payload = {
        "generated_at": "2026-04-10T08:00:00",
        "latest_btst_run": {
            "report_dir": "data/reports/report_b",
            "report_dir_abs": str(tmp_path / "data" / "reports" / "report_b"),
            "selection_target": "short_trade_only",
        },
        "latest_priority_board_snapshot": {"headline": "headline-b"},
        "latest_btst_snapshot": {},
        "control_tower_snapshot": {
            "selected_outcome_refresh_summary": {
                "focus_ticker": "002001",
                "focus_cycle_status": "t_plus_2_closed",
                "focus_overall_contract_verdict": "t_plus_2_confirmed",
                "focus_next_day_contract_verdict": "next_close_confirmed_wait_t_plus_2",
                "focus_t_plus_2_contract_verdict": "t_plus_2_confirmed",
            }
        },
        "source_paths": {},
    }
    previous_payload = {
        "generated_at": "2026-04-10T07:30:00",
        "latest_btst_run": {
            "report_dir": "data/reports/report_b",
            "report_dir_abs": str(tmp_path / "data" / "reports" / "report_b"),
            "selection_target": "short_trade_only",
        },
        "latest_priority_board_snapshot": {"headline": "headline-b"},
        "latest_btst_snapshot": {},
        "control_tower_snapshot": {
            "selected_outcome_refresh_summary": {
                "focus_ticker": "002001",
                "focus_cycle_status": "missing_next_day",
                "focus_overall_contract_verdict": "pending_next_day",
                "focus_next_day_contract_verdict": "pending_next_day",
                "focus_t_plus_2_contract_verdict": "pending_t_plus_2",
            }
        },
        "source_paths": {},
    }

    delta_payload = build_btst_open_ready_delta_payload(
        current_payload,
        reports_root=tmp_path / "data" / "reports",
        current_nightly_json_path=tmp_path / "data" / "reports" / "btst_nightly_control_tower_latest.json",
        previous_payload=previous_payload,
        previous_payload_path=str(tmp_path / "data" / "reports" / "history.json"),
        historical_payload_candidates=[],
    )

    assert delta_payload["selected_outcome_contract_delta"]["current_focus_ticker"] == "002001"
    assert delta_payload["selected_outcome_contract_delta"]["previous_focus_cycle_status"] == "missing_next_day"
    assert delta_payload["selected_outcome_contract_delta"]["current_focus_cycle_status"] == "t_plus_2_closed"
    assert delta_payload["selected_outcome_contract_delta"]["previous_focus_overall_contract_verdict"] == "pending_next_day"
    assert delta_payload["selected_outcome_contract_delta"]["current_focus_overall_contract_verdict"] == "t_plus_2_confirmed"
    assert "selected_outcome_contract" in delta_payload["material_change_anchor"].get("changed_sections", []) or delta_payload["overall_delta_verdict"] == "changed"
    assert any("selected contract" in item for item in delta_payload["operator_focus"])


def test_build_btst_open_ready_delta_payload_surfaces_carryover_peer_proof_changes(tmp_path: Path) -> None:
    current_payload = {
        "generated_at": "2026-04-10T08:00:00",
        "latest_btst_run": {
            "report_dir": "data/reports/report_b",
            "report_dir_abs": str(tmp_path / "data" / "reports" / "report_b"),
            "selection_target": "short_trade_only",
        },
        "latest_priority_board_snapshot": {"headline": "headline-b"},
        "latest_btst_snapshot": {},
        "control_tower_snapshot": {
            "carryover_aligned_peer_proof_summary": {
                "focus_ticker": "300408",
                "focus_proof_verdict": "supportive_closed_cycle",
                "focus_promotion_review_verdict": "ready_for_promotion_review",
                "ready_for_promotion_review_tickers": ["300408"],
                "risk_review_tickers": [],
            }
        },
        "source_paths": {},
    }
    previous_payload = {
        "generated_at": "2026-04-10T07:30:00",
        "latest_btst_run": {
            "report_dir": "data/reports/report_b",
            "report_dir_abs": str(tmp_path / "data" / "reports" / "report_b"),
            "selection_target": "short_trade_only",
        },
        "latest_priority_board_snapshot": {"headline": "headline-b"},
        "latest_btst_snapshot": {},
        "control_tower_snapshot": {
            "carryover_aligned_peer_proof_summary": {
                "focus_ticker": "300408",
                "focus_proof_verdict": "supportive_closed_cycle",
                "focus_promotion_review_verdict": "await_t_plus_2_close",
                "ready_for_promotion_review_tickers": [],
                "risk_review_tickers": [],
            }
        },
        "source_paths": {},
    }

    delta_payload = build_btst_open_ready_delta_payload(
        current_payload,
        reports_root=tmp_path / "data" / "reports",
        current_nightly_json_path=tmp_path / "data" / "reports" / "btst_nightly_control_tower_latest.json",
        previous_payload=previous_payload,
        previous_payload_path=str(tmp_path / "data" / "reports" / "history.json"),
        historical_payload_candidates=[],
    )

    assert delta_payload["carryover_peer_proof_delta"]["current_focus_ticker"] == "300408"
    assert delta_payload["carryover_peer_proof_delta"]["previous_focus_promotion_review_verdict"] == "await_t_plus_2_close"
    assert delta_payload["carryover_peer_proof_delta"]["current_focus_promotion_review_verdict"] == "ready_for_promotion_review"
    assert delta_payload["carryover_peer_proof_delta"]["added_ready_for_promotion_review_tickers"] == ["300408"]
    assert any("carryover peer proof" in item for item in delta_payload["operator_focus"])


def test_build_btst_open_ready_delta_payload_surfaces_top_priority_action_changes(tmp_path: Path) -> None:
    current_payload = {
        "generated_at": "2026-04-10T08:00:00",
        "latest_btst_run": {
            "report_dir": "data/reports/report_b",
            "report_dir_abs": str(tmp_path / "data" / "reports" / "report_b"),
            "selection_target": "short_trade_only",
        },
        "latest_priority_board_snapshot": {"headline": "headline-b"},
        "latest_btst_snapshot": {},
        "control_tower_snapshot": {
            "next_actions": [
                {
                    "task_id": "carryover_gate_ready_priority",
                    "title": "优先复核 300408 carryover gate-ready 扩容资格",
                    "source": "carryover_gate_ready",
                }
            ]
        },
        "source_paths": {},
    }
    previous_payload = {
        "generated_at": "2026-04-10T07:30:00",
        "latest_btst_run": {
            "report_dir": "data/reports/report_b",
            "report_dir_abs": str(tmp_path / "data" / "reports" / "report_b"),
            "selection_target": "short_trade_only",
        },
        "latest_priority_board_snapshot": {"headline": "headline-b"},
        "latest_btst_snapshot": {},
        "control_tower_snapshot": {
            "next_actions": [
                {
                    "task_id": "carryover_contract_priority",
                    "title": "固化 002001 carryover 合约并盯 300408 闭环",
                    "source": "carryover_contract",
                }
            ]
        },
        "source_paths": {},
    }

    delta_payload = build_btst_open_ready_delta_payload(
        current_payload,
        reports_root=tmp_path / "data" / "reports",
        current_nightly_json_path=tmp_path / "data" / "reports" / "btst_nightly_control_tower_latest.json",
        previous_payload=previous_payload,
        previous_payload_path=str(tmp_path / "data" / "reports" / "history.json"),
        historical_payload_candidates=[],
    )

    assert delta_payload["top_priority_action_delta"]["previous_source"] == "carryover_contract"
    assert delta_payload["top_priority_action_delta"]["current_source"] == "carryover_gate_ready"
    assert delta_payload["top_priority_action_delta"]["current_task_id"] == "carryover_gate_ready_priority"
    assert any("顶级动作切换" in item for item in delta_payload["operator_focus"])


def test_build_btst_nightly_control_tower_payload_auto_prioritizes_gate_ready_peer() -> None:
    manifest = {
        "reports_root": "/tmp/reports",
        "entries": [],
        "selected_outcome_refresh_summary": {
            "focus_ticker": "002001",
            "focus_overall_contract_verdict": "pending_next_day",
        },
        "carryover_multiday_continuation_audit_summary": {
            "selected_ticker": "002001",
            "selected_path_t2_bias_only": True,
        },
        "carryover_peer_promotion_gate_summary": {
            "selected_ticker": "002001",
            "selected_contract_verdict": "pending_next_day",
            "focus_ticker": "300408",
            "focus_gate_verdict": "promotion_gate_ready",
            "ready_tickers": ["300408"],
            "blocked_open_tickers": [],
            "pending_t_plus_2_tickers": [],
        },
        "carryover_peer_expansion_summary": {
            "focus_ticker": "300408",
            "focus_status": "promotion_review_ready",
            "priority_expansion_tickers": ["300408"],
            "watch_with_risk_tickers": [],
        },
    }

    payload = build_btst_nightly_control_tower_payload(manifest)

    assert payload["control_tower_snapshot"]["next_actions"][0]["source"] == "selected_contract_monitor"
    assert "002001" in payload["control_tower_snapshot"]["next_actions"][0]["title"]
    assert payload["control_tower_snapshot"]["next_actions"][1]["source"] == "carryover_gate_ready"
    assert "300408" in payload["control_tower_snapshot"]["next_actions"][1]["title"]
    assert "ready_tickers=['300408']" in payload["control_tower_snapshot"]["next_actions"][1]["why_now"]


def test_build_btst_nightly_control_tower_payload_prioritizes_selected_contract_resolution() -> None:
    manifest = {
        "reports_root": "/tmp/reports",
        "entries": [],
        "selected_outcome_refresh_summary": {
            "focus_ticker": "002001",
            "focus_cycle_status": "t_plus_2_closed",
            "focus_overall_contract_verdict": "t_plus_2_confirmed",
            "focus_next_day_contract_verdict": "next_close_confirmed_wait_t_plus_2",
            "focus_t_plus_2_contract_verdict": "t_plus_2_confirmed",
        },
        "carryover_multiday_continuation_audit_summary": {
            "selected_ticker": "002001",
            "selected_path_t2_bias_only": True,
        },
        "carryover_peer_promotion_gate_summary": {
            "selected_ticker": "002001",
            "selected_contract_verdict": "t_plus_2_confirmed",
            "focus_ticker": "300408",
            "focus_gate_verdict": "promotion_gate_ready",
            "ready_tickers": ["300408"],
            "blocked_open_tickers": [],
            "pending_t_plus_2_tickers": [],
        },
        "carryover_peer_expansion_summary": {
            "focus_ticker": "300408",
            "focus_status": "promotion_review_ready",
            "priority_expansion_tickers": ["300408"],
            "watch_with_risk_tickers": [],
        },
    }

    payload = build_btst_nightly_control_tower_payload(manifest)

    assert payload["control_tower_snapshot"]["next_actions"][0]["source"] == "selected_contract_resolution"
    assert "002001" in payload["control_tower_snapshot"]["next_actions"][0]["title"]
    assert payload["control_tower_snapshot"]["next_actions"][1]["source"] == "carryover_gate_ready"


def test_build_btst_nightly_control_tower_payload_prioritizes_peer_proof_review_before_generic_carryover() -> None:
    manifest = {
        "reports_root": "/tmp/reports",
        "entries": [],
        "selected_outcome_refresh_summary": {
            "focus_ticker": "002001",
            "focus_overall_contract_verdict": "pending_next_day",
        },
        "carryover_multiday_continuation_audit_summary": {
            "selected_ticker": "002001",
            "selected_path_t2_bias_only": True,
        },
        "carryover_aligned_peer_proof_summary": {
            "focus_ticker": "300408",
            "focus_proof_verdict": "supportive_closed_cycle",
            "focus_promotion_review_verdict": "ready_for_promotion_review",
            "ready_for_promotion_review_tickers": ["300408"],
            "risk_review_tickers": [],
        },
        "carryover_peer_promotion_gate_summary": {
            "selected_ticker": "002001",
            "selected_contract_verdict": "pending_next_day",
            "focus_ticker": "300408",
            "focus_gate_verdict": "blocked_selected_contract_open",
            "ready_tickers": [],
            "blocked_open_tickers": ["300408"],
            "pending_t_plus_2_tickers": [],
        },
        "carryover_peer_expansion_summary": {
            "focus_ticker": "300408",
            "focus_status": "promotion_review_ready",
            "priority_expansion_tickers": ["300408"],
            "watch_with_risk_tickers": [],
        },
    }

    payload = build_btst_nightly_control_tower_payload(manifest)

    assert payload["control_tower_snapshot"]["next_actions"][0]["source"] == "selected_contract_monitor"
    assert "002001" in payload["control_tower_snapshot"]["next_actions"][0]["title"]
    assert payload["control_tower_snapshot"]["next_actions"][1]["source"] == "carryover_peer_proof"
    assert "300408" in payload["control_tower_snapshot"]["next_actions"][1]["title"]
    assert payload["control_tower_snapshot"]["next_actions"][2]["source"] == "carryover_contract"


def test_build_btst_nightly_control_tower_payload_prioritizes_pending_peer_close_loop_before_generic_carryover() -> None:
    manifest = {
        "reports_root": "/tmp/reports",
        "entries": [],
        "selected_outcome_refresh_summary": {
            "focus_ticker": "002001",
            "focus_cycle_status": "missing_next_day",
            "focus_overall_contract_verdict": "pending_next_day",
            "focus_next_day_contract_verdict": "pending_next_day",
            "focus_t_plus_2_contract_verdict": "pending_t_plus_2",
        },
        "carryover_multiday_continuation_audit_summary": {
            "selected_ticker": "002001",
            "selected_path_t2_bias_only": True,
        },
        "carryover_aligned_peer_proof_summary": {
            "focus_ticker": "300408",
            "focus_proof_verdict": "pending_t_plus_2_close",
            "focus_promotion_review_verdict": "await_t_plus_2_close",
            "ready_for_promotion_review_tickers": [],
            "risk_review_tickers": [],
        },
        "carryover_peer_promotion_gate_summary": {
            "selected_ticker": "002001",
            "selected_contract_verdict": "pending_next_day",
            "focus_ticker": "300408",
            "focus_gate_verdict": "await_peer_t_plus_2_close",
            "ready_tickers": [],
            "blocked_open_tickers": [],
            "pending_t_plus_2_tickers": ["300408"],
        },
        "carryover_peer_expansion_summary": {
            "focus_ticker": "300408",
            "focus_status": "next_day_watch_priority",
            "priority_expansion_tickers": ["300408"],
            "watch_with_risk_tickers": [],
        },
    }

    payload = build_btst_nightly_control_tower_payload(manifest)

    assert payload["control_tower_snapshot"]["next_actions"][0]["source"] == "selected_contract_monitor"
    assert payload["control_tower_snapshot"]["next_actions"][1]["source"] == "carryover_peer_close_loop_monitor"
    assert "300408" in payload["control_tower_snapshot"]["next_actions"][1]["title"]
    assert payload["control_tower_snapshot"]["next_actions"][2]["source"] == "carryover_contract"


def test_prioritize_control_tower_next_actions_prefers_btst_flip_tasks_over_recall() -> None:
    latest_btst_snapshot = {"summary": {"primary_count": 0}}
    control_tower_snapshot = {
        "candidate_pool_recall_dossier": {
            "dominant_stage": "candidate_pool_truncated_after_filters",
            "top_stage_tickers": {"candidate_pool_truncated_after_filters": ["688796", "300683", "688383"]},
            "truncation_frontier_summary": {"frontier_verdict": "filter_recall_required"},
            "next_actions": ["先补 recall 链路"],
        },
        "active_candidate_pool_upstream_handoff_focus_tickers": ["688796", "300683", "688383"],
        "selected_outcome_refresh_summary": {
            "focus_ticker": "002001",
            "focus_overall_contract_verdict": "pending_next_day",
        },
        "carryover_aligned_peer_proof_summary": {
            "focus_ticker": "300408",
            "focus_proof_verdict": "supportive_closed_cycle",
            "focus_promotion_review_verdict": "ready_for_promotion_review",
            "ready_for_promotion_review_tickers": ["300408"],
            "risk_review_tickers": [],
        },
        "carryover_peer_promotion_gate_summary": {
            "selected_ticker": "002001",
            "selected_contract_verdict": "pending_next_day",
            "focus_ticker": "300408",
            "focus_gate_verdict": "blocked_selected_contract_open",
            "ready_tickers": [],
            "blocked_open_tickers": ["300408"],
            "pending_t_plus_2_tickers": [],
        },
        "carryover_peer_expansion_summary": {
            "focus_ticker": "300408",
            "focus_status": "promotion_review_ready",
            "priority_expansion_tickers": ["300408"],
            "watch_with_risk_tickers": [],
        },
        "carryover_multiday_continuation_audit_summary": {
            "selected_ticker": "002001",
            "selected_path_t2_bias_only": True,
        },
    }

    actions = _prioritize_control_tower_next_actions(latest_btst_snapshot, control_tower_snapshot)

    assert actions[0]["source"] == "selected_contract_monitor"
    assert actions[1]["source"] == "carryover_peer_proof"
    assert actions[2]["source"] == "carryover_contract"


def test_prioritize_control_tower_next_actions_prefers_pending_peer_close_loop_over_recall() -> None:
    latest_btst_snapshot = {"summary": {"primary_count": 0}}
    control_tower_snapshot = {
        "candidate_pool_recall_dossier": {
            "dominant_stage": "candidate_pool_truncated_after_filters",
            "top_stage_tickers": {"candidate_pool_truncated_after_filters": ["688796", "300683", "688383"]},
            "truncation_frontier_summary": {"frontier_verdict": "filter_recall_required"},
            "next_actions": ["先补 recall 链路"],
        },
        "active_candidate_pool_upstream_handoff_focus_tickers": ["688796", "300683", "688383"],
        "selected_outcome_refresh_summary": {
            "focus_ticker": "002001",
            "focus_cycle_status": "missing_next_day",
            "focus_overall_contract_verdict": "pending_next_day",
            "focus_next_day_contract_verdict": "pending_next_day",
            "focus_t_plus_2_contract_verdict": "pending_t_plus_2",
        },
        "carryover_aligned_peer_proof_summary": {
            "focus_ticker": "300408",
            "focus_proof_verdict": "pending_t_plus_2_close",
            "focus_promotion_review_verdict": "await_t_plus_2_close",
            "ready_for_promotion_review_tickers": [],
            "risk_review_tickers": [],
        },
        "carryover_peer_promotion_gate_summary": {
            "selected_ticker": "002001",
            "selected_contract_verdict": "pending_next_day",
            "focus_ticker": "300408",
            "focus_gate_verdict": "await_peer_t_plus_2_close",
            "ready_tickers": [],
            "blocked_open_tickers": [],
            "pending_t_plus_2_tickers": ["300408"],
        },
        "carryover_peer_expansion_summary": {
            "focus_ticker": "300408",
            "focus_status": "next_day_watch_priority",
            "priority_expansion_tickers": ["300408"],
            "watch_with_risk_tickers": [],
        },
        "carryover_multiday_continuation_audit_summary": {
            "selected_ticker": "002001",
            "selected_path_t2_bias_only": True,
        },
    }

    actions = _prioritize_control_tower_next_actions(latest_btst_snapshot, control_tower_snapshot)

    assert actions[0]["source"] == "selected_contract_monitor"
    assert actions[1]["source"] == "carryover_peer_close_loop_monitor"
    assert actions[2]["source"] == "carryover_contract"


def _write_btst_followup_report(
    reports_root: Path,
    *,
    report_name: str,
    selection_target: str,
    mode: str,
    trade_date: str,
    next_trade_date: str,
    summary_counts: dict[str, int] | None = None,
    portfolio_values: list[float] | None = None,
    max_drawdown: float = -0.01,
    sharpe_ratio: float = 1.2,
    executed_trade_days: int = 1,
    total_executed_orders: int = 2,
    include_btst_followup: bool = True,
    brief_payload: dict[str, object] | None = None,
    priority_board_payload: dict[str, object] | None = None,
    llm_error_digest: dict[str, object] | None = None,
    selection_snapshot_payload: dict[str, object] | None = None,
) -> Path:
    report_dir = reports_root / report_name
    selection_dir = report_dir / "selection_artifacts" / trade_date
    selection_dir.mkdir(parents=True, exist_ok=True)
    _write_json(selection_dir / "selection_snapshot.json", selection_snapshot_payload or {"trade_date": trade_date.replace("-", "")})

    followup_block = {}
    artifacts_block = {}
    if include_btst_followup:
        brief_json = report_dir / "btst_next_day_trade_brief_latest.json"
        brief_markdown = report_dir / "btst_next_day_trade_brief_latest.md"
        priority_board_json = report_dir / "btst_next_day_priority_board_latest.json"
        priority_board_markdown = report_dir / f"btst_next_day_priority_board_{next_trade_date.replace('-', '')}.md"
        brief_body = dict(
            brief_payload
            or {
                "summary": {
                    "short_trade_selected_count": int((summary_counts or {}).get("selected_count") or 0),
                    "short_trade_near_miss_count": int((summary_counts or {}).get("near_miss_count") or 0),
                    "short_trade_blocked_count": int((summary_counts or {}).get("blocked_count") or 0),
                    "short_trade_rejected_count": int((summary_counts or {}).get("rejected_count") or 0),
                    "short_trade_opportunity_pool_count": int((summary_counts or {}).get("opportunity_pool_count") or 0),
                    "research_upside_radar_count": int((summary_counts or {}).get("research_upside_radar_count") or 0),
                    "catalyst_theme_count": int((summary_counts or {}).get("catalyst_theme_count") or 0),
                    "catalyst_theme_shadow_count": int((summary_counts or {}).get("catalyst_theme_shadow_count") or 0),
                },
                "recommendation": "继续用 near-miss 与 opportunity_pool 做明早观察层。",
            }
        )
        priority_board_body = dict(
            priority_board_payload
            or {
                "trade_date": trade_date,
                "next_trade_date": next_trade_date,
                "selection_target": selection_target,
                "headline": "watch 600522 before 300442",
                "summary": {
                    "primary_count": int((summary_counts or {}).get("selected_count") or 0),
                    "near_miss_count": int((summary_counts or {}).get("near_miss_count") or 0),
                    "opportunity_pool_count": int((summary_counts or {}).get("opportunity_pool_count") or 0),
                    "research_upside_radar_count": int((summary_counts or {}).get("research_upside_radar_count") or 0),
                    "catalyst_theme_count": int((summary_counts or {}).get("catalyst_theme_count") or 0),
                    "catalyst_theme_shadow_count": int((summary_counts or {}).get("catalyst_theme_shadow_count") or 0),
                },
                "priority_rows": [
                    {
                        "ticker": "600522",
                        "lane": "near_miss_watch",
                        "actionability": "watch_only",
                        "monitor_priority": "high",
                        "execution_priority": "high",
                        "execution_quality_label": "close_continuation",
                        "score_target": 0.5558,
                        "preferred_entry_mode": "next_day_breakout_confirmation",
                        "why_now": "breakout_freshness=0.87, trend_acceleration=0.73, catalyst_freshness=0.76",
                        "suggested_action": "仅做盘中跟踪，不预设主买入动作。",
                        "historical_summary": "同层同源同分桶历史 8 例，next_high>=2.0% 命中率=0.7500, next_close 正收益率=0.7500。",
                        "execution_note": "历史上更偏向次日收盘延续，确认后可保留 follow-through 预期。",
                    },
                    {
                        "ticker": "300442",
                        "lane": "opportunity_pool",
                        "actionability": "upgrade_only",
                        "monitor_priority": "high",
                        "execution_priority": "medium",
                        "execution_quality_label": "balanced_confirmation",
                        "score_target": 0.3126,
                        "preferred_entry_mode": "next_day_breakout_confirmation",
                        "why_now": "catalyst_freshness=0.71, stale_trend_repair_penalty=0.45, score_short=0.31",
                        "suggested_action": "若催化延续并出现量价确认，可升级为观察票。",
                        "historical_summary": "同层同源历史 22 例，next_high>=2.0% 命中率=0.6364, next_close 正收益率=0.5909。",
                        "execution_note": "历史表现相对均衡，仍应坚持盘中确认后再决定是否持有。",
                    },
                ],
                "global_guardrails": [
                    "priority board 只负责排序和分层，不改变 short-trade admission 默认语义。",
                    "research_upside_radar 只做上涨线索学习，不进入当日 BTST 交易名单。",
                    "所有交易候选都仍需盘中确认，不因历史先验直接跳过执行 guardrail。",
                ],
            }
        )
        _write_json(
            brief_json,
            brief_body,
        )
        brief_markdown.write_text("# btst brief\n", encoding="utf-8")
        _write_json(priority_board_json, priority_board_body)
        priority_board_markdown.write_text("# btst priority board\n", encoding="utf-8")
        followup_block = {
            "trade_date": trade_date,
            "next_trade_date": next_trade_date,
            "brief_json": str(brief_json.resolve()),
            "brief_markdown": str(brief_markdown.resolve()),
            "priority_board_json": str(priority_board_json.resolve()),
            "priority_board_markdown": str(priority_board_markdown.resolve()),
        }
        artifacts_block = {
            "btst_next_day_trade_brief_json": str(brief_json.resolve()),
            "btst_next_day_trade_brief_markdown": str(brief_markdown.resolve()),
            "btst_next_day_priority_board_json": str(priority_board_json.resolve()),
            "btst_next_day_priority_board_markdown": str(priority_board_markdown.resolve()),
        }

    _write_json(
        report_dir / "session_summary.json",
        {
            "start_date": trade_date,
            "end_date": trade_date,
            "plan_generation": {
                "selection_target": selection_target,
                "mode": mode,
            },
            "selection_target": selection_target,
            "portfolio_values": [
                {"Portfolio Value": value}
                for value in (portfolio_values or [100000.0, 101000.0])
            ],
            "performance_metrics": {
                "max_drawdown": max_drawdown,
                "sharpe_ratio": sharpe_ratio,
            },
            "daily_event_stats": {
                "day_count": len(portfolio_values or [100000.0, 101000.0]),
                "executed_trade_days": executed_trade_days,
                "total_executed_orders": total_executed_orders,
            },
            "llm_error_digest": dict(
                llm_error_digest
                or {
                    "status": "healthy",
                    "error_count": 0,
                    "rate_limit_error_count": 0,
                    "fallback_attempt_count": 0,
                    "affected_provider_count": 0,
                    "top_error_types": [],
                    "affected_providers": [],
                    "sample_errors": [],
                    "fallback_gap_detected": False,
                    "recommendation": "no_action_needed",
                }
            ),
            "btst_followup": followup_block,
            "artifacts": artifacts_block,
        },
    )
    return report_dir


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


def test_btst_governance_synthesis_and_validation_merge_current_lane_state(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    latest_report = _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330",
        selection_target="short_trade_only",
        mode="live_pipeline",
        trade_date="2026-03-30",
        next_trade_date="2026-03-31",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 1,
            "blocked_count": 2,
            "rejected_count": 4,
            "opportunity_pool_count": 1,
            "research_upside_radar_count": 2,
        },
    )

    _write_json(
        reports_root / "p3_top3_post_execution_action_board_20260330.json",
        {
            "board_rows": [
                {"ticker": "001309", "action_tier": "primary_promote", "next_step": "collect second window"},
                {"ticker": "300383", "action_tier": "shadow_entry", "next_step": "shadow monitor"},
                {"ticker": "300724", "action_tier": "structural_shadow_hold", "next_step": "keep frozen"},
            ],
            "next_3_tasks": [
                {"task_id": "rerun_001309", "title": "补跑 001309 第二窗口", "why_now": "主 lane 仍缺第二窗口。", "next_step": "python rerun_001309.py"}
            ],
            "recommendation": "001309 继续主推进，300383 保持 shadow，300724 保持 structural hold。",
        },
    )
    _write_json(
        reports_root / "p5_btst_rollout_governance_board_20260330.json",
        {
            "governance_rows": [
                {"ticker": "001309", "governance_tier": "primary_roll_forward_only", "status": "primary_controlled_follow_through", "blocker": "cross_window_stability_missing", "next_step": "collect second window"},
                {"ticker": "300383", "governance_tier": "single_name_shadow_only", "status": "ready_for_shadow_validation", "blocker": "same_rule_shadow_expansion_not_ready", "next_step": "shadow monitor"},
                {"ticker": "002015", "governance_tier": "recurring_shadow_close_candidate", "status": "await_new_independent_window_data", "blocker": "cross_window_stability_missing", "next_step": "wait new close candidate window"},
                {"ticker": "600821", "governance_tier": "recurring_intraday_control", "status": "await_new_independent_window_data", "blocker": "cross_window_stability_missing", "next_step": "wait new intraday control window"},
                {"ticker": "300724", "governance_tier": "structural_shadow_hold_only", "status": "structural_shadow_hold_only", "blocker": "post_release_quality_negative", "next_step": "keep frozen"},
            ],
            "next_3_tasks": [
                {"task_id": "shadow_300383", "title": "继续 shadow 300383", "why_now": "单票 shadow lane 仍是低成本验证位。", "next_step": "shadow follow 300383"}
            ],
            "recommendation": "001309 继续主推进，300383 保持 shadow，300724 保持 structural hold。",
        },
    )
    _write_json(reports_root / "p6_primary_window_gap_001309_20260330.json", {"missing_window_count": 1})
    _write_json(
        reports_root / "p6_recurring_shadow_runbook_20260330.json",
        {
            "close_candidate": {
                "lane_status": "await_new_independent_window_data",
                "validation_verdict": "await_new_independent_window_data",
                "missing_window_count": 1,
                "next_step": "wait close candidate second window",
            },
            "intraday_control": {
                "lane_status": "await_new_independent_window_data",
                "validation_verdict": "await_new_independent_window_data",
                "missing_window_count": 1,
                "next_step": "wait intraday control second window",
            },
            "global_validation_verdict": "await_new_recurring_window_evidence",
        },
    )
    _write_json(
        reports_root / "p7_primary_window_validation_runbook_001309_20260330.json",
        {
            "validation_verdict": "await_new_independent_window_data",
            "rerun_commands": ["python rerun_001309.py --window next"],
        },
    )
    _write_json(
        reports_root / "p8_structural_shadow_runbook_300724_20260330.json",
        {
            "lane_status": "structural_shadow_hold_only",
            "freeze_verdict": "structural_shadow_hold_only",
            "next_step": "keep frozen",
        },
    )
    _write_json(
        reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
        {
            "lane_status": "shadow_only_until_second_window",
            "default_upgrade_status": "blocked_by_single_window_candidate_entry_signal",
            "target_window_count": 2,
            "missing_window_count": 1,
            "upgrade_gap": "await_new_independent_window_data",
            "recommended_structural_variant": "exclude_watchlist_avoid_weak_structure_entries",
            "window_scan_summary": {
                "report_count": 3,
                "filtered_report_count": 1,
                "focus_hit_report_count": 1,
                "preserve_misfire_report_count": 0,
                "distinct_window_count_with_filtered_entries": 1,
                "rollout_readiness": "shadow_only_until_second_window",
            },
            "next_actions": ["等待第二个独立窗口确认 preserve 不误伤"],
            "recommendation": "candidate-entry 仅允许 shadow-only，等待第二个独立窗口。",
        },
    )

    synthesis = analyze_btst_governance_synthesis(
        reports_root,
        action_board_path=reports_root / "p3_top3_post_execution_action_board_20260330.json",
        rollout_governance_path=reports_root / "p5_btst_rollout_governance_board_20260330.json",
        primary_window_gap_path=reports_root / "p6_primary_window_gap_001309_20260330.json",
        recurring_shadow_runbook_path=reports_root / "p6_recurring_shadow_runbook_20260330.json",
        primary_window_validation_runbook_path=reports_root / "p7_primary_window_validation_runbook_001309_20260330.json",
        structural_shadow_runbook_path=reports_root / "p8_structural_shadow_runbook_300724_20260330.json",
        candidate_entry_governance_path=reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
        latest_btst_report_dir=latest_report,
    )
    _write_json(reports_root / "btst_governance_synthesis_latest.json", synthesis)
    _write_json(
        reports_root / "btst_nightly_control_tower_latest.json",
        {
            "control_tower_snapshot": {
                "closed_frontiers": synthesis["closed_frontiers"],
            }
        },
    )
    validation = validate_btst_governance_consistency(
        action_board_path=reports_root / "p3_top3_post_execution_action_board_20260330.json",
        rollout_governance_path=reports_root / "p5_btst_rollout_governance_board_20260330.json",
        primary_window_gap_path=reports_root / "p6_primary_window_gap_001309_20260330.json",
        recurring_shadow_runbook_path=reports_root / "p6_recurring_shadow_runbook_20260330.json",
        primary_window_validation_runbook_path=reports_root / "p7_primary_window_validation_runbook_001309_20260330.json",
        structural_shadow_runbook_path=reports_root / "p8_structural_shadow_runbook_300724_20260330.json",
        candidate_entry_governance_path=reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
        governance_synthesis_path=reports_root / "btst_governance_synthesis_latest.json",
        nightly_control_tower_path=reports_root / "btst_nightly_control_tower_latest.json",
    )

    assert synthesis["latest_btst_followup"]["trade_date"] == "2026-03-30"
    assert synthesis["latest_btst_followup"]["near_miss_count"] == 1
    assert synthesis["latest_btst_followup"]["opportunity_pool_count"] == 1
    assert synthesis["latest_btst_followup"]["priority_board_headline"] == "watch 600522 before 300442"
    assert {row["lane_id"] for row in synthesis["lane_matrix"]} == {
        "primary_roll_forward",
        "single_name_shadow",
        "recurring_shadow_close_candidate",
        "recurring_intraday_control",
        "structural_shadow_hold",
        "candidate_entry_shadow",
    }
    assert synthesis["waiting_lane_count"] >= 4
    assert any(task["source"] == "p3_action_board" for task in synthesis["next_actions"])
    candidate_row = next(row for row in synthesis["lane_matrix"] if row["lane_id"] == "candidate_entry_shadow")
    assert candidate_row["missing_window_count"] == 1
    assert candidate_row["target_window_count"] == 2
    assert candidate_row["upgrade_gap"] == "await_new_independent_window_data"
    assert candidate_row["distinct_window_count_with_filtered_entries"] == 1
    assert candidate_row["preserve_misfire_report_count"] == 0

    assert validation["overall_verdict"] == "pass"
    assert validation["fail_count"] == 0
    assert validation["warn_count"] == 0
    assert any(check["check_id"] == "closed_frontier_alignment" and check["status"] == "pass" for check in validation["checks"])
    candidate_check = next(check for check in validation["checks"] if check["check_id"] == "candidate_entry_shadow_alignment")
    assert candidate_check["status"] == "pass"
    assert candidate_check["details"]["distinct_window_count_with_filtered_entries"] == 1
    assert candidate_check["details"]["expected_missing_window_count"] == 1


def test_btst_governance_synthesis_derives_execution_surface_constraints_from_followup(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    latest_report = _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260331_20260331_live_m2_7_short_trade_only_20260406_corridor_parallel",
        selection_target="short_trade_only",
        mode="live_pipeline",
        trade_date="2026-03-31",
        next_trade_date="2026-04-01",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 1,
            "blocked_count": 0,
            "rejected_count": 1,
            "opportunity_pool_count": 1,
            "research_upside_radar_count": 0,
        },
        brief_payload={
            "summary": {
                "short_trade_selected_count": 0,
                "short_trade_near_miss_count": 1,
                "short_trade_blocked_count": 0,
                "short_trade_rejected_count": 1,
                "short_trade_opportunity_pool_count": 1,
                "research_upside_radar_count": 0,
            },
            "near_miss_entries": [
                {
                    "ticker": "300720",
                    "decision": "near_miss",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "score_target": 0.4574,
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "top_reasons": ["trend_acceleration=0.88", "upstream_shadow_catalyst_relief", "confirmed_breakout"],
                    "historical_prior": {
                        "bias_label": "weak",
                        "sample_count": 1,
                        "next_close_positive_rate": 0.0,
                        "next_close_return_mean": -0.0246,
                        "execution_priority": "medium",
                        "monitor_priority": "low",
                    },
                }
            ],
            "opportunity_pool_entries": [
                {
                    "ticker": "301292",
                    "decision": "rejected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "score_target": 0.3534,
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "top_reasons": ["trend_acceleration=0.81", "profitability_hard_cliff", "confirmed_breakout"],
                    "historical_prior": {
                        "bias_label": "unknown",
                        "sample_count": 0,
                        "next_close_positive_rate": None,
                        "next_close_return_mean": None,
                        "execution_priority": "high",
                        "monitor_priority": "medium",
                    },
                }
            ],
            "recommendation": "继续用 near-miss 与 opportunity_pool 做观察层。",
        },
        priority_board_payload={
            "trade_date": "2026-03-31",
            "next_trade_date": "2026-04-01",
            "selection_target": "short_trade_only",
            "headline": "当前没有主票，优先看 near-miss，其次看机会池。",
        },
    )

    _write_json(reports_root / "p3_top3_post_execution_action_board_20260330.json", {"board_rows": [], "next_3_tasks": [], "recommendation": "保持主 lane 收敛。"})
    _write_json(reports_root / "p5_btst_rollout_governance_board_20260330.json", {"governance_rows": [], "next_3_tasks": [], "recommendation": "执行面需要更严格治理。"})
    _write_json(reports_root / "p6_primary_window_gap_001309_20260330.json", {"missing_window_count": 1})
    _write_json(reports_root / "p6_recurring_shadow_runbook_20260330.json", {"close_candidate": {}, "intraday_control": {}, "global_validation_verdict": "await_new_recurring_window_evidence"})
    _write_json(reports_root / "p7_primary_window_validation_runbook_001309_20260330.json", {"validation_verdict": "await_new_independent_window_data"})
    _write_json(reports_root / "p8_structural_shadow_runbook_300724_20260330.json", {"lane_status": "structural_shadow_hold_only"})
    _write_json(reports_root / "p9_candidate_entry_rollout_governance_20260330.json", {"lane_status": "shadow_only_until_second_window", "default_upgrade_status": "blocked_by_single_window_candidate_entry_signal"})

    synthesis = analyze_btst_governance_synthesis(
        reports_root,
        action_board_path=reports_root / "p3_top3_post_execution_action_board_20260330.json",
        rollout_governance_path=reports_root / "p5_btst_rollout_governance_board_20260330.json",
        primary_window_gap_path=reports_root / "p6_primary_window_gap_001309_20260330.json",
        recurring_shadow_runbook_path=reports_root / "p6_recurring_shadow_runbook_20260330.json",
        primary_window_validation_runbook_path=reports_root / "p7_primary_window_validation_runbook_001309_20260330.json",
        structural_shadow_runbook_path=reports_root / "p8_structural_shadow_runbook_300724_20260330.json",
        candidate_entry_governance_path=reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
        latest_btst_report_dir=latest_report,
    )

    constraint_ids = {row["constraint_id"] for row in synthesis["execution_surface_constraints"]}
    assert constraint_ids == {
        "post_gate_shadow_observation_only",
        "shadow_profitability_cliff_execution_block",
    }
    post_gate_constraint = next(row for row in synthesis["execution_surface_constraints"] if row["constraint_id"] == "post_gate_shadow_observation_only")
    assert post_gate_constraint["focus_tickers"] == ["300720"]
    assert post_gate_constraint["status"] == "continuation_only_confirm_then_review"
    profitability_constraint = next(row for row in synthesis["execution_surface_constraints"] if row["constraint_id"] == "shadow_profitability_cliff_execution_block")
    assert profitability_constraint["focus_tickers"] == ["301292"]
    assert "profitability hard-cliff" in profitability_constraint["recommendation"]


def test_btst_governance_synthesis_merges_same_trade_date_followups_to_strongest_bucket(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    old_report = _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260331_old_near_miss",
        selection_target="short_trade_only",
        mode="live_pipeline",
        trade_date="2026-03-31",
        next_trade_date="2026-04-01",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 1,
            "blocked_count": 0,
            "rejected_count": 0,
            "opportunity_pool_count": 0,
            "research_upside_radar_count": 0,
        },
        brief_payload={
            "summary": {
                "short_trade_selected_count": 0,
                "short_trade_near_miss_count": 1,
                "short_trade_blocked_count": 0,
                "short_trade_rejected_count": 0,
                "short_trade_opportunity_pool_count": 0,
                "research_upside_radar_count": 0,
            },
            "near_miss_entries": [
                {
                    "ticker": "300720",
                    "decision": "near_miss",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "score_target": 0.4574,
                    "top_reasons": ["trend_acceleration=0.88"],
                }
            ],
        },
        priority_board_payload={"trade_date": "2026-03-31", "next_trade_date": "2026-04-01", "selection_target": "short_trade_only", "headline": "旧 near-miss。"},
    )
    new_report = _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260331_new_selected",
        selection_target="short_trade_only",
        mode="live_pipeline",
        trade_date="2026-03-31",
        next_trade_date="2026-04-01",
        summary_counts={
            "selected_count": 1,
            "near_miss_count": 0,
            "blocked_count": 0,
            "rejected_count": 0,
            "opportunity_pool_count": 0,
            "research_upside_radar_count": 0,
        },
        brief_payload={
            "summary": {
                "short_trade_selected_count": 1,
                "short_trade_near_miss_count": 0,
                "short_trade_blocked_count": 0,
                "short_trade_rejected_count": 0,
                "short_trade_opportunity_pool_count": 0,
                "research_upside_radar_count": 0,
            },
            "selected_entries": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "score_target": 0.4584,
                    "top_reasons": ["upstream_shadow_catalyst_relief", "confirmed_breakout"],
                    "historical_prior": {
                        "execution_quality_label": "intraday_only",
                        "entry_timing_bias": "confirm_then_reduce",
                        "execution_note": "历史上更多是盘中给空间、收盘回落，更适合作为 intraday 机会而不是隔夜延续。",
                    },
                }
            ],
        },
        priority_board_payload={"trade_date": "2026-03-31", "next_trade_date": "2026-04-01", "selection_target": "short_trade_only", "headline": "新 selected。"},
    )

    _write_json(reports_root / "p3_top3_post_execution_action_board_20260330.json", {"board_rows": [], "next_3_tasks": [], "recommendation": "保持主 lane 收敛。"})
    _write_json(reports_root / "p5_btst_rollout_governance_board_20260330.json", {"governance_rows": [], "next_3_tasks": [], "recommendation": "执行面需要更严格治理。"})
    _write_json(reports_root / "p6_primary_window_gap_001309_20260330.json", {"missing_window_count": 1})
    _write_json(reports_root / "p6_recurring_shadow_runbook_20260330.json", {"close_candidate": {}, "intraday_control": {}, "global_validation_verdict": "await_new_recurring_window_evidence"})
    _write_json(reports_root / "p7_primary_window_validation_runbook_001309_20260330.json", {"validation_verdict": "await_new_independent_window_data"})
    _write_json(reports_root / "p8_structural_shadow_runbook_300724_20260330.json", {"lane_status": "structural_shadow_hold_only"})
    _write_json(reports_root / "p9_candidate_entry_rollout_governance_20260330.json", {"lane_status": "shadow_only_until_second_window", "default_upgrade_status": "blocked_by_single_window_candidate_entry_signal"})

    synthesis = analyze_btst_governance_synthesis(
        reports_root,
        action_board_path=reports_root / "p3_top3_post_execution_action_board_20260330.json",
        rollout_governance_path=reports_root / "p5_btst_rollout_governance_board_20260330.json",
        primary_window_gap_path=reports_root / "p6_primary_window_gap_001309_20260330.json",
        recurring_shadow_runbook_path=reports_root / "p6_recurring_shadow_runbook_20260330.json",
        primary_window_validation_runbook_path=reports_root / "p7_primary_window_validation_runbook_001309_20260330.json",
        structural_shadow_runbook_path=reports_root / "p8_structural_shadow_runbook_300724_20260330.json",
        candidate_entry_governance_path=reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
        latest_btst_report_dir=new_report,
        evidence_btst_report_dirs=[old_report, new_report],
    )

    assert len(synthesis["evidence_btst_followups"]) == 1
    merged_followup = synthesis["evidence_btst_followups"][0]
    assert merged_followup["selected_count"] == 1
    assert merged_followup["near_miss_count"] == 0
    assert merged_followup["report_dir"] == str(new_report.resolve())
    assert merged_followup["entries"][0]["ticker"] == "300720"
    assert merged_followup["entries"][0]["bucket"] == "selected_entries"
    assert merged_followup["entries"][0]["historical_execution_quality_label"] == "intraday_only"
    assert merged_followup["entries"][0]["historical_entry_timing_bias"] == "confirm_then_reduce"

    upstream_intraday_constraint = next(
        row for row in synthesis["execution_surface_constraints"] if row["constraint_id"] == "upstream_shadow_selected_intraday_bias"
    )
    assert upstream_intraday_constraint["status"] == "continuation_confirm_only_intraday_bias"
    assert upstream_intraday_constraint["blocker"] == "weak_overnight_follow_through_after_shadow_recall"
    assert upstream_intraday_constraint["focus_tickers"] == ["300720"]
    assert upstream_intraday_constraint["evidence"]["selected_count"] == 1
    assert upstream_intraday_constraint["evidence"]["entries"][0]["bucket"] == "selected_entries"


def test_validate_btst_governance_consistency_fails_on_closed_frontier_drift(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)

    _write_json(
        reports_root / "p3_top3_post_execution_action_board_20260330.json",
        {
            "board_rows": [
                {"ticker": "001309", "action_tier": "primary_promote"},
                {"ticker": "300724", "action_tier": "structural_shadow_hold"},
            ],
            "recommendation": "001309, 300383, 300724",
        },
    )
    closed_frontier = {
        "frontier_id": "broad_penalty_relief",
        "status": "broad_penalty_route_closed_current_window",
        "headline": "broad stale/extension penalty relief 在当前窗口没有形成任何通过 closed-tradeable guardrail 的 row。",
        "passing_variant_count": 0,
        "best_variant_name": "nm_0.42__avoid_0.12__stale_0.08__ext_0.02",
        "best_variant_released_tickers": ["300724"],
        "best_variant_focus_released_tickers": [],
    }
    _write_json(
        reports_root / "p5_btst_rollout_governance_board_20260330.json",
        {
            "governance_rows": [
                {"ticker": "001309", "status": "continue_controlled_roll_forward", "blocker": "cross_window_stability_missing"},
                {"ticker": "002015", "status": "await_new_close_candidate_window"},
                {"ticker": "600821", "status": "await_new_intraday_control_window"},
                {"ticker": "300724", "status": "structural_shadow_hold_only"},
            ],
            "frontier_constraints": [closed_frontier],
            "recommendation": "001309, 300383, 300724 broad penalty route closed",
        },
    )
    _write_json(reports_root / "p6_primary_window_gap_001309_20260330.json", {"missing_window_count": 1})
    _write_json(
        reports_root / "p6_recurring_shadow_runbook_20260330.json",
        {
            "close_candidate": {"lane_status": "await_new_close_candidate_window", "validation_verdict": "await_new_independent_window_data"},
            "intraday_control": {"lane_status": "await_new_intraday_control_window", "validation_verdict": "await_new_independent_window_data"},
            "global_validation_verdict": "await_new_recurring_window_evidence",
        },
    )
    _write_json(reports_root / "p7_primary_window_validation_runbook_001309_20260330.json", {"validation_verdict": "await_new_independent_window_data"})
    _write_json(reports_root / "p8_structural_shadow_runbook_300724_20260330.json", {"lane_status": "structural_shadow_hold_only"})
    _write_json(
        reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
        {
            "lane_status": "shadow_only_until_second_window",
            "default_upgrade_status": "blocked_by_single_window_candidate_entry_signal",
        },
    )
    _write_json(reports_root / "btst_governance_synthesis_latest.json", {"closed_frontiers": [closed_frontier]})
    drifted_frontier = dict(closed_frontier)
    drifted_frontier["best_variant_released_tickers"] = ["300383"]
    _write_json(
        reports_root / "btst_nightly_control_tower_latest.json",
        {
            "control_tower_snapshot": {
                "closed_frontiers": [drifted_frontier],
            }
        },
    )

    validation = validate_btst_governance_consistency(
        action_board_path=reports_root / "p3_top3_post_execution_action_board_20260330.json",
        rollout_governance_path=reports_root / "p5_btst_rollout_governance_board_20260330.json",
        primary_window_gap_path=reports_root / "p6_primary_window_gap_001309_20260330.json",
        recurring_shadow_runbook_path=reports_root / "p6_recurring_shadow_runbook_20260330.json",
        primary_window_validation_runbook_path=reports_root / "p7_primary_window_validation_runbook_001309_20260330.json",
        structural_shadow_runbook_path=reports_root / "p8_structural_shadow_runbook_300724_20260330.json",
        candidate_entry_governance_path=reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
        governance_synthesis_path=reports_root / "btst_governance_synthesis_latest.json",
        nightly_control_tower_path=reports_root / "btst_nightly_control_tower_latest.json",
    )

    assert validation["overall_verdict"] == "fail"
    assert any(check["check_id"] == "closed_frontier_alignment" and check["status"] == "fail" for check in validation["checks"])


def test_validate_btst_governance_consistency_fails_on_candidate_entry_evidence_drift(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)

    _write_json(
        reports_root / "p3_top3_post_execution_action_board_20260330.json",
        {
            "board_rows": [
                {"ticker": "001309", "action_tier": "primary_promote"},
                {"ticker": "300724", "action_tier": "structural_shadow_hold"},
            ],
            "recommendation": "001309, 300383, 300724",
        },
    )
    _write_json(
        reports_root / "p5_btst_rollout_governance_board_20260330.json",
        {
            "governance_rows": [
                {"ticker": "001309", "status": "continue_controlled_roll_forward", "blocker": "cross_window_stability_missing"},
                {"ticker": "002015", "status": "await_new_close_candidate_window"},
                {"ticker": "600821", "status": "await_new_intraday_control_window"},
                {"ticker": "300724", "status": "structural_shadow_hold_only"},
            ],
            "recommendation": "001309, 300383, 300724",
        },
    )
    _write_json(reports_root / "p6_primary_window_gap_001309_20260330.json", {"missing_window_count": 1})
    _write_json(
        reports_root / "p6_recurring_shadow_runbook_20260330.json",
        {
            "close_candidate": {"lane_status": "await_new_close_candidate_window", "validation_verdict": "await_new_independent_window_data"},
            "intraday_control": {"lane_status": "await_new_intraday_control_window", "validation_verdict": "await_new_independent_window_data"},
            "global_validation_verdict": "await_new_recurring_window_evidence",
        },
    )
    _write_json(reports_root / "p7_primary_window_validation_runbook_001309_20260330.json", {"validation_verdict": "await_new_independent_window_data"})
    _write_json(
        reports_root / "p8_structural_shadow_runbook_300724_20260330.json",
        {
            "lane_status": "structural_shadow_hold_only",
            "freeze_verdict": "structural_shadow_hold_only",
        },
    )
    _write_json(
        reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
        {
            "lane_status": "shadow_only_until_second_window",
            "default_upgrade_status": "blocked_by_single_window_candidate_entry_signal",
            "target_window_count": 2,
            "missing_window_count": 1,
            "upgrade_gap": "await_new_independent_window_data",
            "recommended_structural_variant": "exclude_watchlist_avoid_weak_structure_entries",
            "window_scan_summary": {
                "report_count": 4,
                "filtered_report_count": 2,
                "focus_hit_report_count": 2,
                "preserve_misfire_report_count": 0,
                "distinct_window_count_with_filtered_entries": 2,
                "rollout_readiness": "shadow_rollout_review_ready",
            },
        },
    )

    validation = validate_btst_governance_consistency(
        action_board_path=reports_root / "p3_top3_post_execution_action_board_20260330.json",
        rollout_governance_path=reports_root / "p5_btst_rollout_governance_board_20260330.json",
        primary_window_gap_path=reports_root / "p6_primary_window_gap_001309_20260330.json",
        recurring_shadow_runbook_path=reports_root / "p6_recurring_shadow_runbook_20260330.json",
        primary_window_validation_runbook_path=reports_root / "p7_primary_window_validation_runbook_001309_20260330.json",
        structural_shadow_runbook_path=reports_root / "p8_structural_shadow_runbook_300724_20260330.json",
        candidate_entry_governance_path=reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
    )

    candidate_check = next(check for check in validation["checks"] if check["check_id"] == "candidate_entry_shadow_alignment")
    assert validation["overall_verdict"] == "fail"
    assert candidate_check["status"] == "fail"
    assert candidate_check["details"]["distinct_window_count_with_filtered_entries"] == 2
    assert candidate_check["details"]["expected_missing_window_count"] == 0


def test_btst_replay_cohort_summarizes_short_trade_and_frozen_reports(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260331_20260331_live_m2_7_short_trade_only_20260331",
        selection_target="short_trade_only",
        mode="live_pipeline",
        trade_date="2026-03-31",
        next_trade_date="2026-04-01",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 1,
            "blocked_count": 1,
            "rejected_count": 2,
            "opportunity_pool_count": 2,
            "research_upside_radar_count": 1,
        },
        portfolio_values=[100000.0, 105000.0],
        max_drawdown=-0.015,
        sharpe_ratio=1.4,
        executed_trade_days=1,
        total_executed_orders=2,
    )
    _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260330_20260330_frozen_replay_m2_7_short_trade_only_20260331_run1",
        selection_target="short_trade_only",
        mode="frozen_current_plan_replay",
        trade_date="2026-03-30",
        next_trade_date="2026-03-31",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 1,
            "blocked_count": 2,
            "rejected_count": 4,
            "opportunity_pool_count": 1,
            "research_upside_radar_count": 0,
        },
        portfolio_values=[100000.0, 100000.0],
        max_drawdown=0.0,
        sharpe_ratio=0.0,
        executed_trade_days=0,
        total_executed_orders=0,
    )
    _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260329_20260329_live_m2_7_dual_target_20260329",
        selection_target="dual_target",
        mode="live_pipeline",
        trade_date="2026-03-29",
        next_trade_date="2026-03-30",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 0,
            "blocked_count": 0,
            "rejected_count": 0,
            "opportunity_pool_count": 0,
            "research_upside_radar_count": 0,
        },
        portfolio_values=[100000.0, 97000.0],
        max_drawdown=-0.03,
        sharpe_ratio=-0.7,
        executed_trade_days=2,
        total_executed_orders=3,
        include_btst_followup=False,
    )

    analysis = analyze_btst_replay_cohort(reports_root)

    assert analysis["report_count"] == 3
    assert analysis["selection_target_counts"] == {
        "short_trade_only": 2,
        "dual_target": 1,
        "other": 0,
    }
    assert analysis["latest_short_trade_row"]["report_dir_name"] == "paper_trading_20260331_20260331_live_m2_7_short_trade_only_20260331"
    assert analysis["top_return_rows"][0]["report_dir_name"] == "paper_trading_20260331_20260331_live_m2_7_short_trade_only_20260331"
    assert analysis["top_return_rows"][0]["total_return_pct"] == 5.0
    short_trade_summary = next(summary for summary in analysis["cohort_summaries"] if summary["label"] == "short_trade_only")
    assert short_trade_summary["report_count"] == 2
    assert short_trade_summary["live_report_count"] == 1
    assert short_trade_summary["frozen_report_count"] == 1
    assert short_trade_summary["actionable_report_count"] == 2
    assert "short_trade_only cohort" in analysis["recommendation"]


def test_btst_nightly_control_tower_generates_one_click_bundle_and_reindexes_manifest(tmp_path: Path) -> None:
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

    _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260331_20260331_live_m2_7_short_trade_only_20260331",
        selection_target="short_trade_only",
        mode="live_pipeline",
        trade_date="2026-03-31",
        next_trade_date="2026-04-01",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 1,
            "blocked_count": 1,
            "rejected_count": 2,
            "opportunity_pool_count": 2,
            "research_upside_radar_count": 1,
            "catalyst_theme_count": 1,
            "catalyst_theme_shadow_count": 2,
        },
        portfolio_values=[100000.0, 101200.0],
        max_drawdown=-0.2,
        sharpe_ratio=1.3,
        executed_trade_days=1,
        total_executed_orders=2,
        llm_error_digest={
            "status": "degraded",
            "error_count": 5,
            "rate_limit_error_count": 0,
            "fallback_attempt_count": 0,
            "affected_provider_count": 1,
            "top_error_types": [{"error_type": "TimeoutError", "count": 5}],
            "affected_providers": [
                {
                    "provider": "MiniMax",
                    "attempts": 49,
                    "errors": 5,
                    "error_rate": 0.102,
                    "rate_limit_errors": 0,
                    "fallback_attempts": 0,
                    "top_error_types": [{"error_type": "TimeoutError", "count": 5}],
                }
            ],
            "sample_errors": [
                {
                    "trade_date": "2026-03-31",
                    "pipeline_stage": "daily_pipeline_post_market",
                    "model_tier": "fast",
                    "provider": "MiniMax",
                    "error_type": "TimeoutError",
                    "message": "upstream timeout after 30s",
                }
            ],
            "fallback_gap_detected": True,
            "recommendation": "errors_detected_without_fallback_review_provider_routing",
        },
        selection_snapshot_payload={
            "trade_date": "20260331",
            "catalyst_theme_candidates": [],
            "catalyst_theme_shadow_candidates": [
                {
                    "ticker": "301001",
                    "decision": "catalyst_theme_shadow",
                    "score_target": 0.32,
                    "candidate_source": "catalyst_theme_shadow",
                    "filter_reason": "sector_resonance_below_catalyst_theme_floor",
                    "threshold_shortfalls": {"candidate_score": 0.02, "sector_resonance": 0.03},
                    "failed_threshold_count": 2,
                    "total_shortfall": 0.05,
                    "gate_status": {"data": "pass", "structural": "fail", "score": "shadow"},
                    "metrics": {
                        "breakout_freshness": 0.14,
                        "trend_acceleration": 0.21,
                        "close_strength": 0.41,
                        "sector_resonance": 0.22,
                        "catalyst_freshness": 0.82,
                    },
                }
            ],
        },
    )
    _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260330_20260330_frozen_replay_m2_7_short_trade_only_20260331_run1",
        selection_target="short_trade_only",
        mode="frozen_current_plan_replay",
        trade_date="2026-03-30",
        next_trade_date="2026-03-31",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 1,
            "blocked_count": 2,
            "rejected_count": 4,
            "opportunity_pool_count": 1,
            "research_upside_radar_count": 0,
        },
        portfolio_values=[100000.0, 100000.0],
        max_drawdown=0.0,
        sharpe_ratio=0.0,
        executed_trade_days=0,
        total_executed_orders=0,
    )
    _write_json(
        reports_root / "p2_top3_experiment_execution_summary_20260330.json",
        {
            "generated_on": "2026-03-31T00:00:00",
            "experiments": [],
            "recommendation": "keep primary lane narrow",
            "runbook": [],
        },
    )
    _write_json(
        reports_root / "p3_top3_post_execution_action_board_20260330.json",
        {
            "board_rows": [
                {"ticker": "001309", "action_tier": "primary_promote", "next_step": "collect second window"},
                {"ticker": "300383", "action_tier": "shadow_keep", "next_step": "shadow monitor"},
                {"ticker": "300724", "action_tier": "structural_shadow_hold", "next_step": "keep frozen"},
            ],
            "next_3_tasks": [
                {"task_id": "rerun_001309", "title": "补跑 001309 第二窗口", "why_now": "主 lane 仍缺第二窗口。", "next_step": "python rerun_001309.py"}
            ],
            "recommendation": "优先推进 001309，保持 300383 shadow，保持 300724 structural hold。",
        },
    )
    _write_json(
        reports_root / "p5_btst_rollout_governance_board_20260330.json",
        {
            "generated_on": "2026-03-31T00:00:00",
            "governance_rows": [
                {"ticker": "001309", "governance_tier": "primary_roll_forward_only", "status": "continue_controlled_roll_forward", "blocker": "cross_window_stability_missing", "next_step": "collect second window"},
                {"ticker": "300383", "governance_tier": "single_name_shadow_only", "status": "hold_shadow_only_no_same_rule_expansion", "blocker": "same_rule_shadow_expansion_not_ready", "next_step": "shadow monitor"},
                {"ticker": "002015", "governance_tier": "recurring_shadow_close_candidate", "status": "await_new_close_candidate_window", "blocker": "cross_window_stability_missing", "next_step": "wait close candidate"},
                {"ticker": "600821", "governance_tier": "recurring_intraday_control", "status": "await_new_intraday_control_window", "blocker": "cross_window_stability_missing", "next_step": "wait intraday control"},
                {"ticker": "300724", "governance_tier": "structural_shadow_hold_only", "status": "structural_shadow_hold_only", "blocker": "post_release_quality_negative", "next_step": "keep frozen"},
            ],
            "next_3_tasks": [
                {"task_id": "primary_roll_forward", "title": "推进 001309", "why_now": "仍是唯一 primary lane。", "next_step": "collect second window"}
            ],
            "recommendation": "当前 rollout 治理应分三条车道：001309 主推进，300383 shadow，300724 structural hold。",
        },
    )
    _write_json(reports_root / "p6_primary_window_gap_001309_20260330.json", {"missing_window_count": 1})
    _write_json(
        reports_root / "p6_recurring_shadow_runbook_20260330.json",
        {
            "close_candidate": {
                "lane_status": "await_new_close_candidate_window",
                "validation_verdict": "await_new_independent_window_data",
                "missing_window_count": 1,
                "next_step": "wait close candidate",
            },
            "intraday_control": {
                "lane_status": "await_new_intraday_control_window",
                "validation_verdict": "await_new_independent_window_data",
                "missing_window_count": 1,
                "next_step": "wait intraday control",
            },
            "global_validation_verdict": "await_new_recurring_window_evidence",
        },
    )
    _write_json(
        reports_root / "p7_primary_window_validation_runbook_001309_20260330.json",
        {
            "validation_verdict": "await_new_independent_window_data",
            "rerun_commands": ["python rerun_001309.py --window next"],
        },
    )
    _write_json(
        reports_root / "p8_structural_shadow_runbook_300724_20260330.json",
        {
            "lane_status": "structural_shadow_hold_only",
            "freeze_verdict": "hold_single_name_only_quality_negative",
            "next_step": "keep frozen",
        },
    )
    _write_json(
        reports_root / "btst_candidate_entry_frontier_20260330.json",
        {
            "best_variant": {
                "variant_name": "weak_structure_triplet",
                "filtered_candidate_entry_count": 1,
                "focus_filtered_tickers": ["300502"],
                "preserve_filtered_tickers": [],
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
    _write_json(
        reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
        {
            "lane_status": "shadow_only_until_second_window",
            "default_upgrade_status": "blocked_by_single_window_candidate_entry_signal",
            "target_window_count": 2,
            "missing_window_count": 1,
            "upgrade_gap": "await_new_independent_window_data",
            "recommended_structural_variant": "exclude_watchlist_avoid_weak_structure_entries",
            "window_scan_summary": {
                "report_count": 2,
                "filtered_report_count": 1,
                "focus_hit_report_count": 1,
                "preserve_misfire_report_count": 0,
                "distinct_window_count_with_filtered_entries": 1,
                "rollout_readiness": "shadow_only_until_second_window",
            },
            "next_actions": ["等待第二个独立窗口确认 preserve 不误伤"],
            "recommendation": "candidate-entry 仅允许 shadow-only，等待第二个独立窗口。",
        },
    )
    for filename in [
        "btst_micro_window_regression_20260330.md",
        "btst_profile_frontier_20260330.md",
        "btst_score_construction_frontier_20260330.md",
        "btst_candidate_entry_frontier_20260330.md",
        "btst_candidate_entry_window_scan_20260330.md",
        "p9_candidate_entry_rollout_governance_20260330.md",
    ]:
        (reports_root / filename).write_text(f"# {filename}\n", encoding="utf-8")
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
                "ticker": "300720",
                "promotion_blocker": "no_selected_persistence_or_independent_edge",
                "persistence_requirement": "selected_persistence_across_independent_windows",
                "independent_edge_requirement": "outperform_default_btst_on_independent_windows",
                "lane_support_ratio": 0.875,
                "t_plus_2_mean_gap_vs_watch": 0.067,
                "t_plus_2_close_positive_rate": 0.8667,
                "t_plus_2_close_return_mean": 0.0787,
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
    _write_json(
        reports_root / "btst_governance_synthesis_latest.json",
        {
            "evidence_btst_followups": [
                {
                    "trade_date": "2026-03-31",
                    "report_dir": str(reports_root / "paper_trading_20260331_20260331_live_m2_7_short_trade_only_20260331"),
                    "entries": [{"ticker": "300720"}],
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
    _write_json(
        reports_root / "btst_selected_outcome_refresh_board_latest.json",
        {
            "trade_date": "2026-04-09",
            "selected_count": 1,
            "current_cycle_status_counts": {"missing_next_day": 1},
            "entries": [
                {
                    "ticker": "002001",
                    "current_cycle_status": "missing_next_day",
                    "current_data_status": "missing_next_trade_day_bar",
                    "current_next_close_return": None,
                    "current_t_plus_2_close_return": None,
                    "historical_next_close_positive_rate": 1.0,
                    "historical_t_plus_2_close_positive_rate": 1.0,
                    "next_day_contract_verdict": "pending_next_day",
                    "t_plus_2_contract_verdict": "pending_t_plus_2",
                    "overall_contract_verdict": "pending_next_day",
                }
            ],
            "recommendation": "formal selected still open case",
        },
    )
    _write_json(
        reports_root / "btst_carryover_multiday_continuation_audit_latest.json",
        {
            "selected_ticker": "002001",
            "selected_trade_date": "2026-04-09",
            "supportive_case_count": 3,
            "peer_status_counts": {"broad_family_only": 2, "same_ticker_ready": 1},
            "selected_historical_proof_summary": {
                "next_close_positive_rate": 1.0,
                "t_plus_2_close_positive_rate": 1.0,
                "t_plus_3_close_positive_rate": 0.0,
            },
            "broad_family_only_summary": {
                "next_close_positive_rate": 0.0,
                "t_plus_2_close_positive_rate": 0.0,
            },
            "policy_checks": {
                "selected_path_t2_bias_only": True,
                "broad_family_only_multiday_unsupported": True,
                "aligned_peer_multiday_ready": False,
                "open_selected_case_count": 1,
            },
            "policy_recommendations": [
                "002001 only supports T+2 bias.",
                "broad_family_only should stay outside multiday continuation contract.",
            ],
            "recommendation": "keep T+2 bias only",
        },
    )
    _write_json(
        reports_root / "btst_carryover_aligned_peer_harvest_latest.json",
        {
            "ticker": "002001",
            "peer_row_count": 18,
            "peer_count": 13,
            "status_counts": {"next_day_watch": 1, "fresh_open_cycle": 12},
            "focus_ticker": "300408",
            "focus_status": "next_day_watch",
            "harvest_entries": [
                {
                    "ticker": "300408",
                    "harvest_status": "next_day_watch",
                    "latest_trade_date": "2026-04-08",
                    "latest_scope": "same_family_source",
                    "closed_cycle_count": 0,
                    "next_day_available_count": 1,
                    "recommendation": "watch 300408 T+2 close loop",
                },
                {"ticker": "301396", "harvest_status": "fresh_open_cycle"},
                {"ticker": "300620", "harvest_status": "fresh_open_cycle"},
            ],
            "recommendation": "watch aligned peers",
        },
    )
    _write_json(
        reports_root / "btst_carryover_peer_expansion_latest.json",
        {
            "selected_ticker": "002001",
            "selected_path_t2_bias_only": True,
            "broad_family_only_multiday_unsupported": True,
            "peer_count": 3,
            "expansion_status_counts": {"next_day_watch_priority": 1, "open_cycle_priority": 1, "open_cycle_with_history_risk": 1},
            "priority_expansion_tickers": ["300408", "301396"],
            "watch_with_risk_tickers": ["688498"],
            "focus_ticker": "300408",
            "focus_status": "next_day_watch_priority",
            "entries": [
                {
                    "ticker": "300408",
                    "expansion_status": "next_day_watch_priority",
                    "latest_trade_date": "2026-04-08",
                    "latest_scope": "same_family_source",
                    "recommendation": "watch 300408 first",
                }
            ],
            "recommendation": "watch 300408 first and keep 688498 watch-with-risk",
        },
    )
    _write_json(
        reports_root / "btst_carryover_aligned_peer_proof_board_latest.json",
        {
            "selected_ticker": "002001",
            "selected_trade_date": "2026-04-09",
            "selected_cycle_status": "missing_next_day",
            "selected_contract_verdict": "pending_next_day",
            "peer_count": 3,
            "proof_verdict_counts": {"supportive_closed_cycle": 1, "pending_t_plus_2_close": 1, "supportive_with_history_risk": 1},
            "promotion_review_verdict_counts": {"ready_for_promotion_review": 1, "await_t_plus_2_close": 1, "requires_history_risk_review": 1},
            "ready_for_promotion_review_tickers": ["301396"],
            "risk_review_tickers": ["688498"],
            "pending_t_plus_2_tickers": ["300408"],
            "focus_ticker": "301396",
            "focus_proof_verdict": "supportive_closed_cycle",
            "focus_promotion_review_verdict": "ready_for_promotion_review",
            "entries": [
                {
                    "ticker": "301396",
                    "latest_trade_date": "2026-04-10",
                    "latest_scope": "same_family_source_score_catalyst",
                    "proof_verdict": "supportive_closed_cycle",
                    "promotion_review_verdict": "ready_for_promotion_review",
                    "recommendation": "301396 ready",
                }
            ],
            "recommendation": "301396 is ready for promotion review.",
        },
    )
    _write_json(
        reports_root / "btst_carryover_peer_promotion_gate_latest.json",
        {
            "selected_ticker": "002001",
            "selected_trade_date": "2026-04-09",
            "selected_contract_verdict": "pending_next_day",
            "peer_count": 3,
            "gate_verdict_counts": {"blocked_selected_contract_open": 1, "await_peer_t_plus_2_close": 1, "await_peer_next_day_close": 1},
            "ready_tickers": [],
            "blocked_open_tickers": ["301396"],
            "risk_review_tickers": [],
            "pending_t_plus_2_tickers": ["300408"],
            "focus_ticker": "301396",
            "focus_gate_verdict": "blocked_selected_contract_open",
            "entries": [
                {
                    "ticker": "301396",
                    "gate_verdict": "blocked_selected_contract_open",
                    "recommendation": "301396 blocked until 002001 closes.",
                }
            ],
            "recommendation": "301396 proof is ready but blocked by 002001 open contract.",
        },
    )

    report_a = reports_root / "paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329"
    _write_replay_input(report_a, trade_date="2026-03-26", entries=[_build_entry("300394", weak_structure=False), _build_entry("300502", weak_structure=True)])

    report_b = reports_root / "paper_trading_window_20260316_20260323_live_m2_7_20260323"
    _write_replay_input(report_b, trade_date="2026-03-20", entries=[_build_entry("300394", weak_structure=False)])

    result = generate_btst_nightly_control_tower_artifacts(reports_root=reports_root)

    payload = result["payload"]
    delta_payload = result["delta_payload"]
    assert payload["latest_btst_run"]["selection_target"] == "short_trade_only"
    assert payload["control_tower_snapshot"]["waiting_lane_count"] == 5
    assert payload["latest_priority_board_snapshot"]["headline"] == "watch 600522 before 300442"
    assert payload["replay_cohort_snapshot"]["report_count"] == 4
    assert payload["latest_btst_snapshot"]["llm_error_digest"]["status"] == "degraded"
    assert payload["latest_btst_snapshot"]["llm_error_digest"]["fallback_gap_detected"] is True
    assert payload["latest_btst_snapshot"]["catalyst_theme_frontier_summary"]["status"] == "promotable_shadow_exists"
    assert payload["latest_btst_snapshot"]["catalyst_theme_frontier_summary"]["recommended_promoted_tickers"] == ["301001"]
    assert payload["latest_btst_snapshot"]["score_fail_frontier_summary"]["status"] == "refreshed"
    assert payload["latest_btst_snapshot"]["score_fail_frontier_summary"]["rejected_short_trade_boundary_count"] == 0
    assert payload["recommended_reading_order"][0]["entry_id"] == "btst_governance_synthesis_latest"
    assert payload["recommended_reading_order"][1]["entry_id"] == "btst_tplus1_tplus2_objective_monitor_latest"
    assert payload["recommended_reading_order"][2]["entry_id"] == "btst_independent_window_monitor_latest"
    assert payload["recommended_reading_order"][3]["entry_id"] == "btst_tradeable_opportunity_pool_march"
    assert payload["recommended_reading_order"][4]["entry_id"] == "btst_no_candidate_entry_action_board_latest"
    assert payload["recommended_reading_order"][5]["entry_id"] == "btst_no_candidate_entry_replay_bundle_latest"
    assert payload["recommended_reading_order"][6]["entry_id"] == "btst_no_candidate_entry_failure_dossier_latest"
    assert payload["recommended_reading_order"][7]["entry_id"] == "btst_watchlist_recall_dossier_latest"
    assert payload["recommended_reading_order"][8]["entry_id"] == "btst_candidate_pool_recall_dossier_latest"
    assert payload["recommended_reading_order"][9]["entry_id"] == "btst_tradeable_opportunity_reason_waterfall_march"
    assert payload["control_tower_snapshot"]["independent_window_ready_lane_count"] == 0
    assert payload["control_tower_snapshot"]["independent_window_waiting_lane_count"] == 0
    assert payload["control_tower_snapshot"]["independent_window_monitor"]["report_dir_count"] == 0
    assert payload["control_tower_snapshot"]["tplus1_tplus2_tradeable_verdict"] == "insufficient_closed_cycle_samples"
    assert payload["control_tower_snapshot"]["tradeable_opportunity_pool_count"] == 11
    assert payload["control_tower_snapshot"]["tradeable_opportunity_capture_rate"] == 0.6364
    assert payload["control_tower_snapshot"]["tradeable_opportunity_top_kill_switches"] == ["score_fail", "candidate_entry_filtered", "no_candidate_entry"]
    assert payload["control_tower_snapshot"]["no_candidate_entry_priority_queue_count"] == 1
    assert payload["control_tower_snapshot"]["no_candidate_entry_priority_tickers"] == ["300502"]
    assert payload["control_tower_snapshot"]["no_candidate_entry_recall_probe_tickers"] == []
    assert payload["control_tower_snapshot"]["no_candidate_entry_failure_class_counts"]
    assert payload["control_tower_snapshot"]["no_candidate_entry_handoff_stage_counts"]
    assert payload["control_tower_snapshot"]["watchlist_recall_stage_counts"] == {"absent_from_candidate_pool": 1}
    assert payload["control_tower_snapshot"]["watchlist_recall_absent_from_candidate_pool_tickers"] == ["300502"]
    assert payload["control_tower_snapshot"]["candidate_pool_recall_stage_counts"] == {"candidate_pool_truncated_after_filters": 1}
    assert payload["control_tower_snapshot"]["candidate_pool_recall_dominant_stage"] == "candidate_pool_truncated_after_filters"
    assert payload["control_tower_snapshot"]["candidate_pool_recall_top_stage_tickers"] == {"candidate_pool_truncated_after_filters": ["300502"]}
    assert payload["control_tower_snapshot"]["candidate_pool_recall_truncation_frontier_summary"]["observed_case_count"] == 1
    assert payload["control_tower_snapshot"]["candidate_pool_recall_dominant_ranking_driver"] == "mixed_post_filter_gap"
    assert payload["control_tower_snapshot"]["candidate_pool_recall_dominant_liquidity_gap_mode"] == "near_cutoff_liquidity_gap"
    assert payload["control_tower_snapshot"]["candidate_pool_recall_focus_liquidity_profiles"][0]["ticker"] == "300502"
    assert payload["control_tower_snapshot"]["candidate_pool_recall_focus_liquidity_profiles"][0]["priority_handoff"] == "top300_boundary_micro_tuning"
    assert payload["control_tower_snapshot"]["candidate_pool_recall_priority_handoff_counts"] == {"top300_boundary_micro_tuning": 1}
    assert payload["control_tower_snapshot"]["candidate_pool_recall_priority_handoff_branch_diagnoses"][0]["priority_handoff"] == "top300_boundary_micro_tuning"
    assert payload["control_tower_snapshot"]["candidate_pool_recall_priority_handoff_branch_mechanisms"][0]["priority_handoff"] == "top300_boundary_micro_tuning"
    assert payload["control_tower_snapshot"]["candidate_pool_recall_priority_handoff_branch_experiment_queue"][0]["priority_handoff"] == "top300_boundary_micro_tuning"
    assert payload["control_tower_snapshot"]["candidate_pool_branch_priority_board_status"] == "refreshed"
    assert payload["control_tower_snapshot"]["candidate_pool_branch_priority_board_rows"][0]["priority_handoff"] == "top300_boundary_micro_tuning"
    assert payload["control_tower_snapshot"]["candidate_pool_branch_priority_alignment_status"] == "aligned_top_lane"
    assert payload["control_tower_snapshot"]["candidate_pool_lane_objective_support_status"] == "refreshed"
    assert payload["control_tower_snapshot"]["candidate_pool_lane_objective_support_rows"][0]["priority_handoff"] == "top300_boundary_micro_tuning"
    assert payload["control_tower_snapshot"]["candidate_pool_corridor_validation_pack_status"] in {"parallel_probe_ready", "accumulate_more_corridor_evidence", "skipped_no_corridor_lane"}
    assert payload["control_tower_snapshot"]["candidate_pool_corridor_shadow_pack_status"] in {"ready_for_primary_shadow_replay", "hold_for_more_corridor_evidence", "skipped_no_corridor_lane"}
    assert payload["control_tower_snapshot"]["candidate_pool_rebucket_shadow_pack_status"] in {"ready_for_rebucket_shadow_replay", "persistence_diagnostics_only", "skipped_no_rebucket_candidate"}
    assert payload["control_tower_snapshot"]["candidate_pool_rebucket_objective_validation_status"] in {"refreshed", "skipped_no_rebucket_candidate"}
    assert payload["control_tower_snapshot"]["candidate_pool_rebucket_comparison_bundle_status"] in {"ready_for_parallel_comparison", "keep_shadow_first", "needs_more_closed_cycle_support", "hold_structure_only", "skipped_no_rebucket_lane"}
    assert payload["control_tower_snapshot"]["candidate_pool_lane_pair_board_status"] in {"ready_for_ranked_comparison", "await_corridor_shadow_pack", "await_rebucket_bundle", "insufficient_lane_evidence", "skipped_missing_candidates"}
    assert "leader_governance_status" in payload["control_tower_snapshot"]["candidate_pool_lane_pair_board_summary"]
    assert "leader_governance_execution_quality" in payload["control_tower_snapshot"]["candidate_pool_lane_pair_board_summary"]
    assert "leader_governance_entry_timing_bias" in payload["control_tower_snapshot"]["candidate_pool_lane_pair_board_summary"]
    assert "parallel_watch_same_source_sample_count" in payload["control_tower_snapshot"]["candidate_pool_lane_pair_board_summary"]
    assert payload["control_tower_snapshot"]["continuation_focus_summary"]["focus_ticker"] == "300720"
    assert payload["control_tower_snapshot"]["continuation_focus_summary"]["promotion_gate_verdict"] == "approve_watchlist_promotion"
    assert payload["control_tower_snapshot"]["continuation_focus_summary"]["focus_watch_validation_status"] is None
    assert payload["control_tower_snapshot"]["continuation_focus_summary"]["execution_gate_blockers"] is None
    assert payload["control_tower_snapshot"]["continuation_focus_summary"]["execution_overlay_verdict"] == "execution_candidate_applied"
    assert payload["control_tower_snapshot"]["continuation_focus_summary"]["execution_overlay_promotion_blocker"] == "no_selected_persistence_or_independent_edge"
    assert payload["control_tower_snapshot"]["continuation_focus_summary"]["execution_overlay_persistence_requirement"] == "selected_persistence_across_independent_windows"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["focus_ticker"] == "300720"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["promotion_merge_review_verdict"] == "await_additional_independent_window_persistence"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["promotion_path_status"] == "collect_more_independent_windows"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["blockers_remaining_count"] == 2
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["edge_threshold_verdict"] == "insufficient_default_btst_edge_data"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["ready_after_next_qualifying_window"] is False
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["next_window_duplicate_trade_date_verdict"] == "independent_window_count_unchanged"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["next_window_quality_requirement"] == "must land in selected_entries"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["next_window_disqualified_bucket_verdict"] == "await_higher_quality_window_bucket"
    assert payload["control_tower_snapshot"]["selected_outcome_refresh_summary"]["focus_ticker"] == "002001"
    assert payload["control_tower_snapshot"]["selected_outcome_refresh_summary"]["focus_overall_contract_verdict"] == "pending_next_day"
    assert payload["control_tower_snapshot"]["carryover_multiday_continuation_audit_summary"]["selected_path_t2_bias_only"] is True
    assert payload["control_tower_snapshot"]["carryover_multiday_continuation_audit_summary"]["broad_family_only_multiday_unsupported"] is True
    assert payload["control_tower_snapshot"]["carryover_aligned_peer_harvest_summary"]["focus_ticker"] == "300408"
    assert payload["control_tower_snapshot"]["carryover_aligned_peer_harvest_summary"]["fresh_open_cycle_tickers"] == ["301396", "300620"]
    assert payload["control_tower_snapshot"]["carryover_peer_expansion_summary"]["focus_ticker"] == "300408"
    assert payload["control_tower_snapshot"]["carryover_peer_expansion_summary"]["priority_expansion_tickers"] == ["300408", "301396"]
    assert payload["control_tower_snapshot"]["carryover_peer_expansion_summary"]["watch_with_risk_tickers"] == ["688498"]
    assert payload["control_tower_snapshot"]["carryover_aligned_peer_proof_summary"]["focus_ticker"] == "301396"
    assert payload["control_tower_snapshot"]["carryover_aligned_peer_proof_summary"]["focus_promotion_review_verdict"] == "ready_for_promotion_review"
    assert payload["control_tower_snapshot"]["carryover_aligned_peer_proof_summary"]["ready_for_promotion_review_tickers"] == ["301396"]
    assert payload["control_tower_snapshot"]["carryover_peer_promotion_gate_summary"]["focus_ticker"] == "301396"
    assert payload["control_tower_snapshot"]["carryover_peer_promotion_gate_summary"]["focus_gate_verdict"] == "blocked_selected_contract_open"
    assert payload["control_tower_snapshot"]["carryover_peer_promotion_gate_summary"]["blocked_open_tickers"] == ["301396"]
    carryover_task = next(task for task in payload["control_tower_snapshot"]["next_actions"] if task.get("source") == "carryover_contract")
    assert "002001" in carryover_task["title"]
    assert "300408" in carryover_task["title"]
    assert "t_plus_2_bias_only" in carryover_task["why_now"]
    assert "peer_proof_focus=301396" in carryover_task["why_now"]
    assert "peer_proof_verdict=ready_for_promotion_review" in carryover_task["why_now"]
    assert "peer_gate_focus=301396" in carryover_task["why_now"]
    assert "peer_gate_verdict=blocked_selected_contract_open" in carryover_task["why_now"]
    assert "watch_with_risk=['688498']" in carryover_task["why_now"]
    assert "T+2 bias" in carryover_task["next_step"]
    assert "['300408', '301396']" in carryover_task["next_step"]
    assert "['301396']" in carryover_task["next_step"]
    assert "['688498']" in carryover_task["next_step"]
    assert payload["control_tower_snapshot"]["candidate_pool_upstream_handoff_board_status"] in {"ready_for_upstream_handoff_execution", "skipped_no_focus_tickers"}
    assert "historical_shadow_probe_tickers" in payload["control_tower_snapshot"]["candidate_pool_upstream_handoff_board_summary"]
    assert payload["control_tower_snapshot"]["candidate_pool_corridor_uplift_runbook_status"] in {"ready_for_upstream_uplift_probe", "skipped_no_corridor_probe"}
    assert any(item["entry_id"] == "latest_btst_catalyst_theme_frontier_markdown" for item in payload["recommended_reading_order"])
    assert any(item["entry_id"] == "btst_score_fail_frontier_latest" for item in payload["recommended_reading_order"])
    assert delta_payload["comparison_basis"] == "previous_btst_report"
    assert delta_payload["comparison_scope"] == "previous_btst_report"
    assert delta_payload["overall_delta_verdict"] == "changed"
    assert Path(result["delta_json_path"]).name == "btst_open_ready_delta_latest.json"
    assert Path(result["delta_markdown_path"]).name == "btst_open_ready_delta_latest.md"
    assert Path(result["close_validation_json_path"]).name == "btst_latest_close_validation_latest.json"
    assert Path(result["close_validation_markdown_path"]).name == "btst_latest_close_validation_latest.md"
    assert Path(result["history_json_path"]).exists()

    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "# BTST Nightly Control Tower" in markdown
    assert "## Nightly Summary" in markdown
    assert "watch 600522 before 300442" in markdown
    assert "selected_outcome_refresh_summary: focus_ticker=002001" in markdown
    assert "carryover_multiday_continuation_audit_summary: selected_ticker=002001 selected_path_t2_bias_only=True" in markdown
    assert "carryover_aligned_peer_harvest_summary: focus_ticker=300408 focus_status=next_day_watch" in markdown
    assert "carryover_peer_expansion_summary: focus_ticker=300408 focus_status=next_day_watch_priority" in markdown
    assert "carryover_aligned_peer_proof_summary: focus_ticker=301396 focus_proof_verdict=supportive_closed_cycle focus_promotion_review_verdict=ready_for_promotion_review" in markdown
    assert "carryover_peer_promotion_gate_summary: focus_ticker=301396 focus_gate_verdict=blocked_selected_contract_open" in markdown
    assert "## Rollout Lanes" in markdown
    assert "## Independent Window Monitor" in markdown
    assert "## T+1/T+2 Objective Monitor" in markdown
    assert "## Tradeable Opportunity Pool" in markdown
    assert "## Catalyst Theme Frontier" in markdown
    assert "## Score-Fail Frontier Queue" in markdown
    assert "301001" in markdown
    assert "tradeable_opportunity_pool_count: 11" in markdown
    assert "tradeable_pool_capture_rate: 0.6364" in markdown
    assert "top_no_candidate_entry_industries: ['Chip']" in markdown
    assert "top_no_candidate_entry_tickers: ['300502']" in markdown
    assert "## No Candidate Entry Action Board" in markdown
    assert "priority_queue_count: 1" in markdown
    assert "top_priority_tickers: ['300502']" in markdown
    assert "## No Candidate Entry Replay Bundle" in markdown
    assert "promising_priority_tickers: []" in markdown
    assert "## No Candidate Entry Failure Dossier" in markdown
    assert "priority_handoff_stage_counts:" in markdown
    assert "handoff_task:" in markdown
    assert "## Watchlist Recall Dossier" in markdown
    assert "top_absent_from_candidate_pool_tickers: ['300502']" in markdown
    assert "watchlist_recall_task:" in markdown
    assert "candidate_pool_recall_truncation_frontier_summary:" in markdown
    assert "candidate_pool_recall_dominant_ranking_driver: mixed_post_filter_gap" in markdown
    assert "candidate_pool_recall_dominant_liquidity_gap_mode: near_cutoff_liquidity_gap" in markdown
    assert "candidate_pool_recall_focus_liquidity_profiles:" in markdown
    assert "candidate_pool_recall_priority_handoff_counts: {'top300_boundary_micro_tuning': 1}" in markdown
    assert "candidate_pool_recall_priority_handoff_branch_diagnoses:" in markdown
    assert "candidate_pool_recall_priority_handoff_branch_mechanisms:" in markdown
    assert "candidate_pool_recall_priority_handoff_branch_experiment_queue:" in markdown
    assert "candidate_pool_branch_priority_board_status:" in markdown
    assert "candidate_pool_branch_priority_alignment_status:" in markdown
    assert "candidate_pool_lane_objective_support_status:" in markdown
    assert "candidate_pool_corridor_validation_pack_status:" in markdown
    assert "candidate_pool_corridor_shadow_pack_status:" in markdown
    assert "candidate_pool_rebucket_shadow_pack_status:" in markdown
    assert "candidate_pool_rebucket_objective_validation_status:" in markdown
    assert "candidate_pool_rebucket_comparison_bundle_status:" in markdown
    assert "candidate_pool_lane_pair_board_status:" in markdown
    assert "candidate_pool_upstream_handoff_board_status:" in markdown
    assert "candidate_pool_corridor_uplift_runbook_status:" in markdown
    assert "## Candidate Pool Recall Dossier" in markdown
    assert "dominant_stage: candidate_pool_truncated_after_filters" in markdown
    assert "candidate_pool_recall_task:" in markdown
    assert "300724" in markdown
    assert "## LLM Health" in markdown
    assert "llm_health_status: degraded" in markdown
    assert "sample_error: MiniMax TimeoutError" in markdown
    assert "btst_governance_synthesis_latest.md" in markdown
    assert "btst_tplus1_tplus2_objective_monitor_latest.md" in markdown
    assert "btst_independent_window_monitor_latest.md" in markdown
    assert "btst_tradeable_opportunity_pool_march.md" in markdown
    assert "btst_no_candidate_entry_action_board_latest.md" in markdown
    assert "btst_no_candidate_entry_replay_bundle_latest.md" in markdown
    assert "btst_no_candidate_entry_failure_dossier_latest.md" in markdown
    assert "btst_watchlist_recall_dossier_latest.md" in markdown
    assert "btst_candidate_pool_recall_dossier_latest.md" in markdown
    assert "btst_tradeable_opportunity_reason_waterfall_march.md" in markdown
    assert "btst_replay_cohort_latest.md" in markdown
    delta_markdown = Path(result["delta_markdown_path"]).read_text(encoding="utf-8")
    close_validation_markdown = Path(result["close_validation_markdown_path"]).read_text(encoding="utf-8")
    assert "# BTST Open-Ready Delta" in delta_markdown
    assert "## Score-Fail Frontier Delta" in delta_markdown
    assert "## Carryover Promotion Gate Delta" in delta_markdown
    assert "previous_btst_report" in delta_markdown
    assert "# BTST Latest Close Validation" in close_validation_markdown
    assert "## Tonight Verdict" in close_validation_markdown
    assert "## Governance Check" in close_validation_markdown

    manifest = json.loads(Path(result["manifest_json"]).read_text(encoding="utf-8"))
    entry_ids = {entry["id"] for entry in manifest["entries"]}
    assert "btst_open_ready_delta_latest" in entry_ids
    assert "btst_nightly_control_tower_latest" in entry_ids
    assert "btst_latest_close_validation_latest" in entry_ids
    assert "btst_tplus1_tplus2_objective_monitor_latest" in entry_ids
    assert "btst_independent_window_monitor_latest" in entry_ids
    assert "btst_tradeable_opportunity_pool_march" in entry_ids
    assert "btst_no_candidate_entry_action_board_latest" in entry_ids
    assert "btst_no_candidate_entry_replay_bundle_latest" in entry_ids
    assert "btst_no_candidate_entry_failure_dossier_latest" in entry_ids
    assert "btst_watchlist_recall_dossier_latest" in entry_ids
    assert "btst_candidate_pool_recall_dossier_latest" in entry_ids
    assert "btst_candidate_pool_corridor_shadow_pack_latest" in entry_ids
    assert "btst_candidate_pool_lane_pair_board_latest" in entry_ids
    assert "btst_candidate_pool_upstream_handoff_board_latest" in entry_ids
    assert "btst_candidate_pool_corridor_uplift_runbook_latest" in entry_ids
    assert "btst_tradeable_opportunity_reason_waterfall_march" in entry_ids
    assert "latest_btst_catalyst_theme_frontier_markdown" in entry_ids
    reading_paths = {reading_path["id"]: reading_path for reading_path in manifest["reading_paths"]}
    assert reading_paths["btst_control_tower"]["entry_ids"][0] == "btst_open_ready_delta_latest"
    assert reading_paths["btst_control_tower"]["entry_ids"][1] == "btst_latest_close_validation_latest"
    assert "btst_tplus1_tplus2_objective_monitor_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert "btst_independent_window_monitor_latest" in reading_paths["btst_control_tower"]["entry_ids"]
    assert reading_paths["tomorrow_open"]["entry_ids"][0] == "btst_open_ready_delta_latest"
    assert reading_paths["tomorrow_open"]["entry_ids"][1] == "btst_latest_close_validation_latest"
    assert reading_paths["nightly_review"]["entry_ids"][0] == "btst_open_ready_delta_latest"
    assert reading_paths["nightly_review"]["entry_ids"][1] == "btst_latest_close_validation_latest"
    assert "btst_tplus1_tplus2_objective_monitor_latest" in reading_paths["nightly_review"]["entry_ids"]


def test_btst_control_tower_overlays_latest_upstream_shadow_followup(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    report_dir = _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260331_20260331_live_m2_7_short_trade_only_shadow_followup",
        selection_target="short_trade_only",
        mode="live_pipeline",
        trade_date="2026-03-31",
        next_trade_date="2026-04-01",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 1,
            "blocked_count": 0,
            "rejected_count": 1,
            "opportunity_pool_count": 0,
            "research_upside_radar_count": 0,
        },
        brief_payload={
            "summary": {
                "short_trade_selected_count": 0,
                "short_trade_near_miss_count": 1,
                "short_trade_blocked_count": 0,
                "short_trade_rejected_count": 1,
                "short_trade_opportunity_pool_count": 0,
                "research_upside_radar_count": 0,
            },
            "recommendation": "转入 downstream followup。",
            "upstream_shadow_recall_summary": {"top_focus_tickers": ["300720", "003036"]},
            "priority_rows": [
                {
                    "ticker": "300720",
                    "decision": "near_miss",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "positive_tags": ["upstream_shadow_catalyst_relief_applied"],
                    "top_reasons": ["upstream_shadow_catalyst_relief"],
                },
                {
                    "ticker": "003036",
                    "decision": "rejected",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "top_reasons": ["profitability_hard_cliff"],
                },
            ],
        },
    )

    synthesis_json = reports_root / "btst_governance_synthesis_latest.json"
    validation_json = reports_root / "btst_governance_validation_latest.json"
    independent_json = reports_root / "btst_independent_window_monitor_latest.json"
    tplus_json = reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json"
    replay_json = reports_root / "btst_replay_cohort_latest.json"
    action_board_json = reports_root / "btst_no_candidate_entry_action_board_latest.json"
    failure_dossier_json = reports_root / "btst_no_candidate_entry_failure_dossier_latest.json"
    watchlist_dossier_json = reports_root / "btst_watchlist_recall_dossier_latest.json"
    candidate_pool_dossier_json = reports_root / "btst_candidate_pool_recall_dossier_latest.json"

    _write_json(synthesis_json, {"lane_matrix": [], "waiting_lane_count": 0, "ready_lane_count": 0, "recommendation": "聚焦 active upstream backlog。", "lane_status_counts": {}, "closed_frontiers": [], "next_actions": []})
    _write_json(validation_json, {"overall_verdict": "pass", "warn_count": 0, "fail_count": 0})
    _write_json(independent_json, {"report_dir_count": 0, "rows": [], "recommendation": "n/a"})
    _write_json(tplus_json, {"tradeable_surface": {"verdict": "n/a"}})
    _write_json(replay_json, {"report_count": 1, "selection_target_counts": {"short_trade_only": 1}, "cohort_summaries": [], "recommendation": "n/a"})
    _write_json(action_board_json, {"priority_queue_count": 3, "top_priority_tickers": ["300720", "003036", "301292"], "recommendation": "历史 backlog 仍显示 upstream absence。"})
    _write_json(
        failure_dossier_json,
        {
            "priority_failure_class_counts": {"upstream_absent_from_replay_inputs": 3},
            "priority_handoff_stage_counts": {"absent_from_watchlist": 3},
            "top_absent_from_watchlist_tickers": ["300720", "003036", "301292"],
            "top_upstream_absence_tickers": ["300720", "003036", "301292"],
            "recommendation": "先查 absent_from_watchlist。",
        },
    )
    _write_json(
        watchlist_dossier_json,
        {
            "priority_recall_stage_counts": {"absent_from_candidate_pool": 3},
            "top_absent_from_candidate_pool_tickers": ["300720", "003036", "301292"],
            "recommendation": "先补 candidate pool recall。",
        },
    )
    _write_json(
        candidate_pool_dossier_json,
        {
            "priority_stage_counts": {"candidate_pool_truncated_after_filters": 3},
            "dominant_stage": "candidate_pool_truncated_after_filters",
            "top_stage_tickers": {"candidate_pool_truncated_after_filters": ["300720", "003036", "301292"]},
            "upstream_handoff_board_status": "mixed_upstream_and_post_recall_followup",
            "upstream_handoff_board_summary": {
                "board_status": "mixed_upstream_and_post_recall_followup",
                "focus_tickers": ["300720", "003036", "301292"],
            },
            "recommendation": "raw backlog 与最新 followup 需要分层展示。",
        },
    )

    manifest = {
        "reports_root": str(reports_root.resolve()),
        "latest_btst_run": {
            "report_dir_abs": str(report_dir.resolve()),
            "report_dir": report_dir.name,
            "selection_target": "short_trade_only",
            "trade_date": "2026-03-31",
            "next_trade_date": "2026-04-01",
        },
        "btst_governance_synthesis_refresh": {"status": "refreshed", "output_json": str(synthesis_json.resolve())},
        "btst_governance_validation_refresh": {"status": "refreshed", "output_json": str(validation_json.resolve())},
        "btst_independent_window_monitor_refresh": {"status": "refreshed", "output_json": str(independent_json.resolve())},
        "btst_tplus1_tplus2_objective_monitor_refresh": {"status": "refreshed", "output_json": str(tplus_json.resolve())},
        "btst_replay_cohort_refresh": {"status": "refreshed", "output_json": str(replay_json.resolve())},
        "candidate_entry_shadow_refresh": {
            "status": "refreshed",
            "no_candidate_entry_action_board_json": str(action_board_json.resolve()),
            "no_candidate_entry_failure_dossier_json": str(failure_dossier_json.resolve()),
            "watchlist_recall_dossier_json": str(watchlist_dossier_json.resolve()),
            "candidate_pool_recall_dossier_json": str(candidate_pool_dossier_json.resolve()),
            "candidate_pool_upstream_handoff_board_status": "mixed_upstream_and_post_recall_followup",
            "candidate_pool_upstream_handoff_board_summary": {
                "board_status": "mixed_upstream_and_post_recall_followup",
                "focus_tickers": ["300720", "003036", "301292"],
                "historical_shadow_probe_tickers": ["301292"],
            },
        },
        "entries": [],
    }

    payload = build_btst_nightly_control_tower_payload(manifest)
    control = payload["control_tower_snapshot"]

    assert control["upstream_shadow_followup_validated_tickers"] == ["300720", "003036"]
    assert control["upstream_shadow_followup_near_miss_tickers"] == ["300720"]
    assert control["upstream_shadow_followup_rejected_profitability_tickers"] == ["003036"]
    assert control["active_no_candidate_entry_priority_tickers"] == ["301292"]
    assert control["active_no_candidate_entry_absent_from_watchlist_tickers"] == ["301292"]
    assert control["active_watchlist_recall_absent_from_candidate_pool_tickers"] == ["301292"]
    assert control["active_candidate_pool_upstream_handoff_focus_tickers"] == ["301292"]
    assert "301292" in str(control["upstream_shadow_followup_recommendation"])

    markdown = render_btst_nightly_control_tower_markdown(payload, output_parent=reports_root)
    assert "## Latest Upstream Shadow Followup Overlay" in markdown
    assert "validated_tickers: ['300720', '003036']" in markdown
    assert "active_no_candidate_entry_priority_tickers: ['301292']" in markdown
    assert "upstream_shadow_followup_overlay_recommendation:" in markdown


def test_control_tower_surfaces_transient_probe_summary_from_manifest_refresh() -> None:
    manifest = {
        "reports_root": "data/reports",
        "btst_governance_synthesis_refresh": {},
        "btst_governance_validation_refresh": {},
        "btst_independent_window_monitor_refresh": {},
        "btst_tplus1_tplus2_objective_monitor_refresh": {},
        "candidate_entry_shadow_refresh": {
            "candidate_pool_recall_dossier_status": "refreshed",
            "candidate_pool_upstream_handoff_board_summary": {"focus_tickers": ["301292"]},
            "continuation_promotion_ready_summary": {
                "focus_ticker": "300720",
                "promotion_path_status": "one_qualifying_window_away",
                "blockers_remaining_count": 1,
                "observed_independent_window_count": 1,
                "weighted_observed_window_credit": 1.5,
                "missing_independent_window_count": 1,
                "weighted_missing_window_credit": 0.5,
                "provisional_default_btst_edge_verdict": "provisionally_outperforming_default_btst",
                "edge_threshold_verdict": "edge_threshold_satisfied",
                "promotion_merge_review_verdict": "await_additional_independent_window_persistence",
                "candidate_dossier_same_trade_date_variant_credit": 0.5,
                "ready_after_next_qualifying_window": True,
                "next_window_requirement": "capture_one_new_independent_trade_date_with_edge_thresholds_still_satisfied",
                "next_window_duplicate_trade_date_verdict": "independent_window_count_unchanged",
                "next_window_quality_requirement": "must land in selected_entries",
                "next_window_disqualified_bucket_verdict": "await_higher_quality_window_bucket",
                "next_window_qualified_merge_review_verdict": "ready_for_default_btst_merge_review",
            },
            "execution_constraint_rollup": {
                "constraint_count": 2,
                "continuation_focus_tickers": ["300720"],
                "shadow_focus_tickers": ["301292"],
            },
            "transient_probe_summary": {
                "ticker": "301292",
                "status": "transient_probe_only",
                "blocker": "shadow_recall_not_persistent",
                "candidate_source": "post_gate_liquidity_competition_shadow",
                "score_state": "fail",
            },
        },
        "entries": [],
    }

    payload = build_btst_nightly_control_tower_payload(manifest)

    assert payload["control_tower_snapshot"]["transient_probe_summary"]["ticker"] == "301292"
    assert payload["control_tower_snapshot"]["transient_probe_summary"]["status"] == "transient_probe_only"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["focus_ticker"] == "300720"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["promotion_merge_review_verdict"] == "await_additional_independent_window_persistence"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["promotion_path_status"] == "one_qualifying_window_away"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["weighted_observed_window_credit"] == 1.5
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["candidate_dossier_same_trade_date_variant_credit"] == 0.5
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["ready_after_next_qualifying_window"] is True
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["next_window_quality_requirement"] == "must land in selected_entries"
    assert payload["control_tower_snapshot"]["continuation_promotion_ready_summary"]["next_window_qualified_merge_review_verdict"] == "ready_for_default_btst_merge_review"
    assert payload["control_tower_snapshot"]["execution_constraint_rollup"]["constraint_count"] == 2


def test_control_tower_prioritizes_recall_and_primary_lane_when_latest_btst_has_no_selected(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260409_20260409_live_m2_7_short_trade_only_20260410",
        selection_target="short_trade_only",
        mode="live_pipeline",
        trade_date="2026-04-09",
        next_trade_date="2026-04-10",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 1,
            "blocked_count": 2,
            "rejected_count": 5,
            "opportunity_pool_count": 0,
            "research_upside_radar_count": 0,
        },
    )

    synthesis_json = reports_root / "btst_governance_synthesis_latest.json"
    validation_json = reports_root / "btst_governance_validation_latest.json"
    independent_json = reports_root / "btst_independent_window_monitor_latest.json"
    tplus_json = reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json"
    replay_json = reports_root / "btst_replay_cohort_latest.json"
    candidate_pool_dossier_json = reports_root / "btst_candidate_pool_recall_dossier_latest.json"

    _write_json(
        synthesis_json,
        {
            "lane_matrix": [
                {
                    "lane_id": "primary_roll_forward",
                    "ticker": "001309",
                    "lane_status": "primary_controlled_follow_through",
                    "blocker": "cross_window_stability_missing",
                    "next_step": "collect second window",
                },
                {
                    "lane_id": "single_name_shadow",
                    "ticker": "300383",
                    "lane_status": "ready_for_shadow_validation",
                    "blocker": "same_rule_shadow_expansion_not_ready",
                    "next_step": "shadow monitor",
                },
            ],
            "waiting_lane_count": 1,
            "ready_lane_count": 1,
            "recommendation": "聚焦 recall 和 primary lane。",
            "lane_status_counts": {"primary_controlled_follow_through": 1, "ready_for_shadow_validation": 1},
            "closed_frontiers": [],
            "next_actions": [
                {"task_id": "existing", "title": "旧任务", "why_now": "旧排序", "next_step": "legacy step", "source": "legacy"}
            ],
        },
    )
    _write_json(validation_json, {"overall_verdict": "pass", "warn_count": 0, "fail_count": 0})
    _write_json(independent_json, {"report_dir_count": 0, "rows": [], "recommendation": "n/a"})
    _write_json(tplus_json, {"tradeable_surface": {"verdict": "n/a"}})
    _write_json(replay_json, {"report_count": 1, "selection_target_counts": {"short_trade_only": 1}, "cohort_summaries": [], "recommendation": "n/a"})
    _write_json(
        candidate_pool_dossier_json,
        {
            "priority_stage_counts": {"cooldown_excluded": 2},
            "dominant_stage": "cooldown_excluded",
            "top_stage_tickers": {"cooldown_excluded": ["301292", "301188"]},
            "truncation_frontier_summary": {"frontier_verdict": "far_below_cutoff_not_boundary"},
            "next_actions": ["先核对硬过滤规则是否误杀当前策略主线候选。"],
            "recommendation": "优先检查 cooldown 规则。",
        },
    )

    manifest = {
        "reports_root": str(reports_root.resolve()),
        "latest_btst_run": {
            "report_dir_abs": str(report_dir.resolve()),
            "report_dir": report_dir.name,
            "selection_target": "short_trade_only",
            "trade_date": "2026-04-09",
            "next_trade_date": "2026-04-10",
        },
        "btst_governance_synthesis_refresh": {"status": "refreshed", "output_json": str(synthesis_json.resolve())},
        "btst_governance_validation_refresh": {"status": "refreshed", "output_json": str(validation_json.resolve())},
        "btst_independent_window_monitor_refresh": {"status": "refreshed", "output_json": str(independent_json.resolve())},
        "btst_tplus1_tplus2_objective_monitor_refresh": {"status": "refreshed", "output_json": str(tplus_json.resolve())},
        "btst_replay_cohort_refresh": {"status": "refreshed", "output_json": str(replay_json.resolve())},
        "candidate_entry_shadow_refresh": {
            "status": "refreshed",
            "candidate_pool_recall_dossier_json": str(candidate_pool_dossier_json.resolve()),
        },
        "entries": [],
    }

    payload = build_btst_nightly_control_tower_payload(manifest)
    next_actions = payload["control_tower_snapshot"]["next_actions"]

    assert [task["task_id"] for task in next_actions] == [
        "candidate_pool_recall_priority",
        "primary_roll_forward_priority",
        "single_name_shadow_priority",
    ]
    assert "cooldown_excluded" in next_actions[0]["title"]
    assert "001309" in next_actions[1]["title"]
    assert "evidence_only_not_current_formal_selected" in next_actions[1]["why_now"]
    assert next_actions[1]["next_step"] == "collect second window；仅作独立窗口证据补充，不把它包装成当前 formal selected 主票。"
    assert "300383" in next_actions[2]["title"]


def test_control_tower_recall_priority_prefers_active_upstream_handoff_focus_tickers(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260409_20260409_live_m2_7_short_trade_only_20260410",
        selection_target="short_trade_only",
        mode="live_pipeline",
        trade_date="2026-04-09",
        next_trade_date="2026-04-10",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 2,
            "blocked_count": 0,
            "rejected_count": 0,
            "opportunity_pool_count": 0,
            "research_upside_radar_count": 0,
        },
    )

    synthesis_json = reports_root / "btst_governance_synthesis_latest.json"
    validation_json = reports_root / "btst_governance_validation_latest.json"
    independent_json = reports_root / "btst_independent_window_monitor_latest.json"
    tplus_json = reports_root / "btst_tplus1_tplus2_objective_monitor_latest.json"
    replay_json = reports_root / "btst_replay_cohort_latest.json"
    candidate_pool_dossier_json = reports_root / "btst_candidate_pool_recall_dossier_latest.json"

    _write_json(
        synthesis_json,
        {
            "lane_matrix": [],
            "waiting_lane_count": 0,
            "ready_lane_count": 0,
            "recommendation": "聚焦 recall。",
            "lane_status_counts": {},
            "closed_frontiers": [],
            "next_actions": [],
        },
    )
    _write_json(validation_json, {"overall_verdict": "pass", "warn_count": 0, "fail_count": 0})
    _write_json(independent_json, {"report_dir_count": 0, "rows": [], "recommendation": "n/a"})
    _write_json(tplus_json, {"tradeable_surface": {"verdict": "n/a"}})
    _write_json(replay_json, {"report_count": 1, "selection_target_counts": {"short_trade_only": 1}, "cohort_summaries": [], "recommendation": "n/a"})
    _write_json(
        candidate_pool_dossier_json,
        {
            "priority_stage_counts": {"candidate_pool_truncated_after_filters": 3},
            "dominant_stage": "candidate_pool_truncated_after_filters",
            "top_stage_tickers": {"candidate_pool_truncated_after_filters": ["688796", "688383", "301292"]},
            "truncation_frontier_summary": {"frontier_verdict": "far_below_cutoff_not_boundary"},
            "recommendation": "先拆 liquidity corridor 和 post-gate competition。",
        },
    )

    manifest = {
        "reports_root": str(reports_root.resolve()),
        "latest_btst_run": {
            "report_dir_abs": str(report_dir.resolve()),
            "report_dir": report_dir.name,
            "selection_target": "short_trade_only",
            "trade_date": "2026-04-09",
            "next_trade_date": "2026-04-10",
        },
        "btst_governance_synthesis_refresh": {"status": "refreshed", "output_json": str(synthesis_json.resolve())},
        "btst_governance_validation_refresh": {"status": "refreshed", "output_json": str(validation_json.resolve())},
        "btst_independent_window_monitor_refresh": {"status": "refreshed", "output_json": str(independent_json.resolve())},
        "btst_tplus1_tplus2_objective_monitor_refresh": {"status": "refreshed", "output_json": str(tplus_json.resolve())},
        "btst_replay_cohort_refresh": {"status": "refreshed", "output_json": str(replay_json.resolve())},
        "candidate_entry_shadow_refresh": {
            "status": "refreshed",
            "candidate_pool_recall_dossier_json": str(candidate_pool_dossier_json.resolve()),
            "candidate_pool_upstream_handoff_board_summary": {
                "focus_tickers": ["688796", "300683", "688383"],
            },
        },
        "entries": [],
    }

    payload = build_btst_nightly_control_tower_payload(manifest)
    next_action = payload["control_tower_snapshot"]["next_actions"][0]

    assert next_action["task_id"] == "candidate_pool_recall_priority"
    assert next_action["title"] == "优先修复 Layer A recall / handoff 主链路"
    assert "focus_tickers=['688796', '300683', '688383']" in next_action["why_now"]
    assert next_action["next_step"] == "先补 ['688796', '300683', '688383'] 的 candidate pool -> watchlist 召回观测，确认它们为何连 watchlist 都没进入。"


def test_btst_open_ready_delta_compares_against_previous_nightly_snapshot(tmp_path: Path) -> None:
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
    ]:
        (reports_root / filename).write_text(f"# {filename}\n", encoding="utf-8")

    _write_json(reports_root / "p2_top3_experiment_execution_summary_20260330.json", {"generated_on": "2026-03-31T00:00:00"})
    _write_json(
        reports_root / "p3_top3_post_execution_action_board_20260330.json",
        {
            "board_rows": [
                {"ticker": "001309", "action_tier": "primary_promote", "next_step": "collect second window"},
                {"ticker": "300383", "action_tier": "shadow_keep", "next_step": "shadow monitor"},
                {"ticker": "300724", "action_tier": "structural_shadow_hold", "next_step": "keep frozen"},
            ],
            "next_3_tasks": [
                {"task_id": "rerun_001309", "title": "补跑 001309 第二窗口", "why_now": "主 lane 仍缺第二窗口。", "next_step": "python rerun_001309.py"}
            ],
            "recommendation": "优先推进 001309，保持 300383 shadow，保持 300724 structural hold。",
        },
    )
    _write_json(reports_root / "p6_primary_window_gap_001309_20260330.json", {"missing_window_count": 1})
    _write_json(
        reports_root / "p6_recurring_shadow_runbook_20260330.json",
        {
            "close_candidate": {
                "lane_status": "await_new_close_candidate_window",
                "validation_verdict": "await_new_independent_window_data",
                "missing_window_count": 1,
                "next_step": "wait close candidate",
            },
            "intraday_control": {
                "lane_status": "await_new_intraday_control_window",
                "validation_verdict": "await_new_independent_window_data",
                "missing_window_count": 1,
                "next_step": "wait intraday control",
            },
            "global_validation_verdict": "await_new_recurring_window_evidence",
        },
    )
    _write_json(
        reports_root / "p7_primary_window_validation_runbook_001309_20260330.json",
        {
            "validation_verdict": "await_new_independent_window_data",
            "rerun_commands": ["python rerun_001309.py --window next"],
        },
    )
    _write_json(
        reports_root / "p8_structural_shadow_runbook_300724_20260330.json",
        {
            "lane_status": "structural_shadow_hold_only",
            "freeze_verdict": "hold_single_name_only_quality_negative",
            "next_step": "keep frozen",
        },
    )
    _write_json(
        reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
        {
            "lane_status": "shadow_only_until_second_window",
            "default_upgrade_status": "blocked_by_single_window_candidate_entry_signal",
            "target_window_count": 2,
            "missing_window_count": 1,
            "upgrade_gap": "await_new_independent_window_data",
            "recommended_structural_variant": "exclude_watchlist_avoid_weak_structure_entries",
            "window_scan_summary": {
                "report_count": 2,
                "filtered_report_count": 1,
                "focus_hit_report_count": 1,
                "preserve_misfire_report_count": 0,
                "distinct_window_count_with_filtered_entries": 1,
                "rollout_readiness": "shadow_only_until_second_window",
            },
            "next_actions": ["等待第二个独立窗口确认 preserve 不误伤"],
            "recommendation": "candidate-entry 仅允许 shadow-only，等待第二个独立窗口。",
        },
    )

    _write_json(reports_root / "btst_candidate_entry_frontier_20260330.json", {"best_variant": {"variant_name": "weak_structure_triplet"}})
    _write_json(reports_root / "selection_target_structural_variants_candidate_entry_current_window_20260330.json", {"rows": []})
    _write_json(reports_root / "btst_score_construction_frontier_20260330.json", {"ranked_variants": []})

    _write_json(
        reports_root / "p5_btst_rollout_governance_board_20260330.json",
        {
            "generated_on": "2026-03-31T00:00:00",
            "governance_rows": [
                {"ticker": "001309", "governance_tier": "primary_roll_forward_only", "status": "continue_controlled_roll_forward", "blocker": "cross_window_stability_missing", "next_step": "collect second window"},
                {"ticker": "300383", "governance_tier": "single_name_shadow_only", "status": "hold_shadow_only_no_same_rule_expansion", "blocker": "same_rule_shadow_expansion_not_ready", "next_step": "shadow monitor"},
                {"ticker": "002015", "governance_tier": "recurring_shadow_close_candidate", "status": "await_new_close_candidate_window", "blocker": "cross_window_stability_missing", "next_step": "wait close candidate"},
                {"ticker": "600821", "governance_tier": "recurring_intraday_control", "status": "await_new_intraday_control_window", "blocker": "cross_window_stability_missing", "next_step": "wait intraday control"},
                {"ticker": "300724", "governance_tier": "structural_shadow_hold_only", "status": "structural_shadow_hold_only", "blocker": "post_release_quality_negative", "next_step": "keep frozen"},
            ],
            "next_3_tasks": [{"task_id": "primary_roll_forward", "title": "推进 001309", "why_now": "仍是唯一 primary lane。", "next_step": "collect second window"}],
            "recommendation": "当前 rollout 治理应分三条车道：001309 主推进，300383 shadow，300724 structural hold。",
        },
    )
    _write_tradeable_opportunity_artifacts(reports_root)

    _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330",
        selection_target="short_trade_only",
        mode="live_pipeline",
        trade_date="2026-03-30",
        next_trade_date="2026-03-31",
        summary_counts={
            "selected_count": 0,
            "near_miss_count": 1,
            "blocked_count": 1,
            "rejected_count": 2,
            "opportunity_pool_count": 0,
            "research_upside_radar_count": 0,
        },
        priority_board_payload={
            "trade_date": "2026-03-30",
            "next_trade_date": "2026-03-31",
            "selection_target": "short_trade_only",
            "headline": "先看 600111，再决定是否需要盘中升级。",
            "summary": {
                "primary_count": 0,
                "near_miss_count": 1,
                "opportunity_pool_count": 0,
                "research_upside_radar_count": 0,
            },
            "priority_rows": [
                {
                    "ticker": "600111",
                    "lane": "near_miss_watch",
                    "actionability": "watch_only",
                    "monitor_priority": "high",
                    "execution_priority": "high",
                    "execution_quality_label": "close_continuation",
                    "score_target": 0.54,
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "why_now": "breakout_freshness=0.82",
                    "suggested_action": "仅做盘中跟踪。",
                    "historical_summary": "v1",
                    "execution_note": "v1",
                }
            ],
            "global_guardrails": ["guardrail_v1"],
        },
    )

    first_result = generate_btst_nightly_control_tower_artifacts(reports_root=reports_root)
    assert first_result["delta_payload"]["overall_delta_verdict"] == "baseline_captured"

    _write_json(
        reports_root / "p5_btst_rollout_governance_board_20260330.json",
        {
            "generated_on": "2026-03-31T08:00:00",
            "governance_rows": [
                {"ticker": "001309", "governance_tier": "primary_roll_forward_only", "status": "continue_controlled_roll_forward", "blocker": "cross_window_stability_missing", "next_step": "collect second window"},
                {"ticker": "300383", "governance_tier": "single_name_shadow_only", "status": "ready_for_shadow_validation", "blocker": "same_rule_shadow_expansion_not_ready", "next_step": "shadow monitor"},
                {"ticker": "002015", "governance_tier": "recurring_shadow_close_candidate", "status": "await_new_close_candidate_window", "blocker": "cross_window_stability_missing", "next_step": "wait close candidate"},
                {"ticker": "600821", "governance_tier": "recurring_intraday_control", "status": "await_new_intraday_control_window", "blocker": "cross_window_stability_missing", "next_step": "wait intraday control"},
                {"ticker": "300724", "governance_tier": "structural_shadow_hold_only", "status": "structural_shadow_hold_only", "blocker": "post_release_quality_negative", "next_step": "keep frozen"},
            ],
            "next_3_tasks": [{"task_id": "shadow_300383", "title": "推进 300383 shadow 验证", "why_now": "shadow lane 开始进入准备态。", "next_step": "shadow validate"}],
            "recommendation": "当前 rollout 治理应分三条车道：001309 主推进，300383 进入 shadow validation，300724 structural hold。",
        },
    )
    _write_json(
        reports_root / "p9_candidate_entry_rollout_governance_20260330.json",
        {
            "lane_status": "shadow_rollout_review_ready",
            "default_upgrade_status": "blocked_pending_additional_shadow_execution_evidence",
            "target_window_count": 2,
            "missing_window_count": 0,
            "upgrade_gap": "ready_for_shadow_rollout_review",
            "recommended_structural_variant": "exclude_watchlist_avoid_weak_structure_entries",
            "window_scan_summary": {
                "report_count": 3,
                "filtered_report_count": 2,
                "focus_hit_report_count": 2,
                "preserve_misfire_report_count": 0,
                "distinct_window_count_with_filtered_entries": 2,
                "rollout_readiness": "shadow_rollout_review_ready",
            },
            "next_actions": ["进入 shadow rollout review，继续补 shadow execution 证据"],
            "recommendation": "candidate-entry 进入 shadow rollout review，但仍需补 shadow execution 证据。",
        },
    )

    _write_btst_followup_report(
        reports_root,
        report_name="paper_trading_20260331_20260331_live_m2_7_short_trade_only_20260331",
        selection_target="short_trade_only",
        mode="live_pipeline",
        trade_date="2026-03-31",
        next_trade_date="2026-04-01",
        summary_counts={
            "selected_count": 1,
            "near_miss_count": 0,
            "blocked_count": 1,
            "rejected_count": 1,
            "opportunity_pool_count": 1,
            "research_upside_radar_count": 0,
        },
        priority_board_payload={
            "trade_date": "2026-03-31",
            "next_trade_date": "2026-04-01",
            "selection_target": "short_trade_only",
            "headline": "当前已有主票，先看 300333，再看机会池补位。",
            "summary": {
                "primary_count": 1,
                "near_miss_count": 0,
                "opportunity_pool_count": 1,
                "research_upside_radar_count": 0,
            },
            "priority_rows": [
                {
                    "ticker": "300333",
                    "lane": "primary_entry",
                    "actionability": "trade_candidate",
                    "monitor_priority": "high",
                    "execution_priority": "high",
                    "execution_quality_label": "balanced_confirmation",
                    "score_target": 0.61,
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "why_now": "breakout_freshness=0.91",
                    "suggested_action": "盘中确认后执行。",
                    "historical_summary": "v2",
                    "execution_note": "v2",
                },
                {
                    "ticker": "300222",
                    "lane": "opportunity_pool",
                    "actionability": "upgrade_only",
                    "monitor_priority": "medium",
                    "execution_priority": "medium",
                    "execution_quality_label": "balanced_confirmation",
                    "score_target": 0.34,
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "why_now": "catalyst_freshness=0.66",
                    "suggested_action": "只在盘中增强时升级。",
                    "historical_summary": "v2",
                    "execution_note": "v2",
                },
            ],
            "global_guardrails": ["guardrail_v1", "guardrail_v2"],
        },
        selection_snapshot_payload={
            "trade_date": "20260331",
            "catalyst_theme_candidates": [],
            "catalyst_theme_shadow_candidates": [
                {
                    "ticker": "301001",
                    "decision": "catalyst_theme_shadow",
                    "score_target": 0.32,
                    "candidate_source": "catalyst_theme_shadow",
                    "filter_reason": "sector_resonance_below_catalyst_theme_floor",
                    "threshold_shortfalls": {"candidate_score": 0.02, "sector_resonance": 0.03},
                    "failed_threshold_count": 2,
                    "total_shortfall": 0.05,
                    "gate_status": {"data": "pass", "structural": "fail", "score": "shadow"},
                    "metrics": {
                        "breakout_freshness": 0.14,
                        "trend_acceleration": 0.21,
                        "close_strength": 0.41,
                        "sector_resonance": 0.22,
                        "catalyst_freshness": 0.82,
                    },
                }
            ],
        },
    )

    second_result = generate_btst_nightly_control_tower_artifacts(reports_root=reports_root)
    delta_payload = second_result["delta_payload"]

    assert delta_payload["comparison_basis"] == "nightly_history"
    assert delta_payload["comparison_scope"] == "report_rollforward"
    assert delta_payload["overall_delta_verdict"] == "changed"
    assert any(item["ticker"] == "300333" for item in delta_payload["priority_delta"]["added_tickers"])
    assert any(item["ticker"] == "600111" for item in delta_payload["priority_delta"]["removed_tickers"])
    assert delta_payload["governance_delta"]["available"] is True
    assert any(item["lane_id"] == "single_name_shadow" for item in delta_payload["governance_delta"]["lane_changes"])
    candidate_lane_delta = next(item for item in delta_payload["governance_delta"]["lane_changes"] if item["lane_id"] == "candidate_entry_shadow")
    assert candidate_lane_delta["current_missing_window_count"] == 0
    assert candidate_lane_delta["current_distinct_window_count_with_filtered_entries"] == 2
    assert candidate_lane_delta["current_upgrade_gap"] == "ready_for_shadow_rollout_review"
    assert delta_payload["replay_delta"]["report_count_delta"] == 1
    assert delta_payload["catalyst_frontier_delta"]["current_status"] == "promotable_shadow_exists"
    assert delta_payload["catalyst_frontier_delta"]["added_promoted_tickers"] == ["301001"]

    delta_markdown = Path(second_result["delta_markdown_path"]).read_text(encoding="utf-8")
    assert "300333" in delta_markdown
    assert "single_name_shadow" in delta_markdown
    assert "candidate_entry_shadow" in delta_markdown
    assert "missing_window_count 1 -> 0" in delta_markdown
    assert "distinct_window_count 1 -> 2" in delta_markdown
    assert "## Catalyst Theme Frontier Delta" in delta_markdown
    assert "added_promoted_ticker: 301001" in delta_markdown

    third_result = generate_btst_nightly_control_tower_artifacts(reports_root=reports_root)
    third_delta_payload = third_result["delta_payload"]

    assert third_delta_payload["comparison_basis"] == "nightly_history"
    assert third_delta_payload["comparison_scope"] == "same_report_rerun"
    assert third_delta_payload["overall_delta_verdict"] == "stable"
    assert third_delta_payload["previous_reference"]["report_dir"] == third_delta_payload["current_reference"]["report_dir"]
    assert third_delta_payload["previous_reference"]["generated_at"] == second_result["payload"]["generated_at"]
    assert third_delta_payload["catalyst_frontier_delta"]["previous_data_available"] is True
    assert third_delta_payload["material_change_anchor"]["reference_generated_at"] == first_result["payload"]["generated_at"]
    assert third_delta_payload["material_change_anchor"]["reference_report_dir"] == "data/reports/paper_trading_20260330_20260330_live_m2_7_short_trade_only_20260330"
    assert third_delta_payload["material_change_anchor"]["comparison_scope"] == "report_rollforward"
    assert third_delta_payload["material_change_anchor"]["overall_delta_verdict"] == "changed"
    assert third_delta_payload["material_change_anchor"]["skipped_snapshot_count"] == 1
    assert "priority" in third_delta_payload["material_change_anchor"]["changed_sections"]
    assert "catalyst_frontier" in third_delta_payload["material_change_anchor"]["changed_sections"]

    third_delta_markdown = Path(third_result["delta_markdown_path"]).read_text(encoding="utf-8")
    assert "comparison_scope: same_report_rerun" in third_delta_markdown
    assert f"previous_snapshot_generated_at: {second_result['payload']['generated_at']}" in third_delta_markdown
    assert "## Last Material Change Anchor" in third_delta_markdown
    assert f"reference_generated_at: {first_result['payload']['generated_at']}" in third_delta_markdown
    assert "skipped_same_report_rerun_snapshots: 1" in third_delta_markdown
