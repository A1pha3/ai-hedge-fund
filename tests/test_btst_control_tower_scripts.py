from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_governance_synthesis import analyze_btst_governance_synthesis
from scripts.analyze_btst_replay_cohort import analyze_btst_replay_cohort
from scripts.run_btst_nightly_control_tower import generate_btst_nightly_control_tower_artifacts
from scripts.validate_btst_governance_consistency import validate_btst_governance_consistency


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
) -> Path:
    report_dir = reports_root / report_name
    selection_dir = report_dir / "selection_artifacts" / trade_date
    selection_dir.mkdir(parents=True, exist_ok=True)
    _write_json(selection_dir / "selection_snapshot.json", {"trade_date": trade_date.replace("-", "")})

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
            "btst_followup": followup_block,
            "artifacts": artifacts_block,
        },
    )
    return report_dir


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
        },
        portfolio_values=[100000.0, 101200.0],
        max_drawdown=-0.2,
        sharpe_ratio=1.3,
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

    result = generate_btst_nightly_control_tower_artifacts(reports_root=reports_root)

    payload = result["payload"]
    delta_payload = result["delta_payload"]
    assert payload["latest_btst_run"]["selection_target"] == "short_trade_only"
    assert payload["control_tower_snapshot"]["waiting_lane_count"] == 5
    assert payload["latest_priority_board_snapshot"]["headline"] == "watch 600522 before 300442"
    assert payload["replay_cohort_snapshot"]["report_count"] == 2
    assert payload["recommended_reading_order"][0]["entry_id"] == "btst_governance_synthesis_latest"
    assert delta_payload["comparison_basis"] == "previous_btst_report"
    assert delta_payload["overall_delta_verdict"] == "changed"
    assert Path(result["delta_json_path"]).name == "btst_open_ready_delta_latest.json"
    assert Path(result["delta_markdown_path"]).name == "btst_open_ready_delta_latest.md"
    assert Path(result["history_json_path"]).exists()

    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "# BTST Nightly Control Tower" in markdown
    assert "## Nightly Summary" in markdown
    assert "watch 600522 before 300442" in markdown
    assert "btst_governance_synthesis_latest.md" in markdown
    assert "btst_replay_cohort_latest.md" in markdown
    delta_markdown = Path(result["delta_markdown_path"]).read_text(encoding="utf-8")
    assert "# BTST Open-Ready Delta" in delta_markdown
    assert "previous_btst_report" in delta_markdown

    manifest = json.loads(Path(result["manifest_json"]).read_text(encoding="utf-8"))
    entry_ids = {entry["id"] for entry in manifest["entries"]}
    assert "btst_open_ready_delta_latest" in entry_ids
    assert "btst_nightly_control_tower_latest" in entry_ids
    reading_paths = {reading_path["id"]: reading_path for reading_path in manifest["reading_paths"]}
    assert reading_paths["btst_control_tower"]["entry_ids"][0] == "btst_open_ready_delta_latest"
    assert reading_paths["tomorrow_open"]["entry_ids"][0] == "btst_open_ready_delta_latest"
    assert reading_paths["nightly_review"]["entry_ids"][0] == "btst_open_ready_delta_latest"


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
    )

    second_result = generate_btst_nightly_control_tower_artifacts(reports_root=reports_root)
    delta_payload = second_result["delta_payload"]

    assert delta_payload["comparison_basis"] == "nightly_history"
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

    delta_markdown = Path(second_result["delta_markdown_path"]).read_text(encoding="utf-8")
    assert "300333" in delta_markdown
    assert "single_name_shadow" in delta_markdown
    assert "candidate_entry_shadow" in delta_markdown
    assert "missing_window_count 1 -> 0" in delta_markdown
    assert "distinct_window_count 1 -> 2" in delta_markdown