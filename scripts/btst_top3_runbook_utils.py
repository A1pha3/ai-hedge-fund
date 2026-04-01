from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts._p0_baseline_stats import main as build_p0_baseline_artifacts


REPORTS_DIR = Path("data/reports")
P0_SAMPLE_TABLE_PATH = REPORTS_DIR / "p0_micro_window_sample_table_20260330.csv"
P0_BASELINE_JSON_PATH = REPORTS_DIR / "p0_baseline_freeze_20260330.json"
P2_RUNBOOK_JSON_PATH = REPORTS_DIR / "p2_top3_experiment_runbook_20260330.json"
CATALYST_FLOOR_ZERO_REPORT_DIR = REPORTS_DIR / "paper_trading_window_20260323_20260326_live_m2_7_dual_target_catalyst_floor_zero_validation_20260329"
REPLAY_VALIDATION_REPORT_DIR = REPORTS_DIR / "paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329"
DEFAULT_STALE_WEIGHT = 0.12
DEFAULT_EXTENSION_WEIGHT = 0.08
DEFAULT_NEXT_HIGH_HIT_THRESHOLD = 0.02


def ensure_inputs() -> None:
    if P0_SAMPLE_TABLE_PATH.exists() and P0_BASELINE_JSON_PATH.exists():
        return
    build_p0_baseline_artifacts()


def build_execution_bundle(
    *,
    release_mode: str,
    report_dir: Path,
    artifact_stub: str,
    reference_release_report: str,
    reference_outcome_report: str = "",
    profile_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    release_scripts = {
        "near_miss_promotion": "scripts/analyze_targeted_short_trade_near_miss_release.py",
        "score_frontier_release": "scripts/analyze_targeted_short_trade_boundary_release.py",
        "structural_conflict_release": "scripts/analyze_targeted_structural_conflict_release.py",
    }
    return {
        "release_mode": release_mode,
        "report_dir": str(report_dir),
        "artifact_stub": artifact_stub,
        "release_script": release_scripts[release_mode],
        "generic_outcome_script": "scripts/analyze_targeted_release_outcomes.py",
        "default_weights": {
            "stale_weight": DEFAULT_STALE_WEIGHT,
            "extension_weight": DEFAULT_EXTENSION_WEIGHT,
            "next_high_hit_threshold": DEFAULT_NEXT_HIGH_HIT_THRESHOLD,
        },
        "profile_overrides": dict(profile_overrides or {}),
        "reference_artifacts": {
            "release_report": reference_release_report,
            "outcome_report": reference_outcome_report,
        },
    }


def build_top3_runbook() -> dict[str, Any]:
    runbook = {
        "generated_on": "2026-03-30",
        "baseline_guardrails": {
            "next_high_hit_rate_at_2pct_floor": 0.5217,
            "next_close_positive_rate_floor": 0.5652,
            "single_ticker_or_single_industry_domination": "not_allowed",
        },
        "top_3_experiments": [
            {
                "priority_rank": 1,
                "experiment_id": "001309_primary_controlled_follow_through",
                "track": "case_based_near_miss_promotion",
                "objective": "验证 near-miss promotion 是否可以在不污染其他样本的前提下转成主入场票。",
                "target_cases": ["2026-03-24:001309", "2026-03-25:001309"],
                "parameter_change": {
                    "select_threshold": {"from": 0.58, "to": 0.56},
                    "scope": "targeted_case_only",
                },
                "validated_evidence": {
                    "expected_migration": "2/2 near_miss -> selected",
                    "changed_non_target_case_count": 0,
                    "next_high_return_mean": 0.0510,
                    "next_close_return_mean": 0.0414,
                    "next_close_positive_rate": 1.0,
                },
                "default_mode": "primary_controlled_follow_through",
                "keep_guardrails": [
                    "changed_non_target_case_count == 0",
                    "next_close_return_mean > 0",
                    "next_close_positive_rate >= 0.75",
                ],
                "decision_rules": {
                    "go": "全部 keep guardrails 满足，且 case 语义仍可解释。",
                    "shadow_only": "intraday 仍强，但 close continuation 下滑到 0.5~0.75 之间。",
                    "rollback": "出现非目标样本污染，或 close continuation 转负。",
                },
                "evaluation_policy": {
                    "target_promotion_required": True,
                    "max_changed_non_target_case_count": 0,
                    "go_requirements": {
                        "min_next_close_return_mean": 0.0,
                        "min_next_close_positive_rate": 0.75,
                    },
                    "shadow_only_requirements": {
                        "min_next_high_return_mean": 0.02,
                        "min_next_close_positive_rate": 0.5,
                    },
                },
                "execution_bundle": build_execution_bundle(
                    release_mode="near_miss_promotion",
                    report_dir=CATALYST_FLOOR_ZERO_REPORT_DIR,
                    artifact_stub="001309_primary_controlled_follow_through",
                    reference_release_report="data/reports/targeted_short_trade_near_miss_release_001309_20260329.json",
                    reference_outcome_report="data/reports/targeted_short_trade_near_miss_release_outcomes_001309_20260329.json",
                ),
            },
            {
                "priority_rank": 2,
                "experiment_id": "300383_threshold_only_shadow_entry",
                "track": "case_based_score_frontier_release",
                "objective": "验证 threshold-only 的低成本 score frontier 释放是否值得保留为影子入口。",
                "target_cases": ["2026-03-26:300383"],
                "parameter_change": {
                    "near_miss_threshold": {"from": 0.46, "to": 0.42},
                    "scope": "targeted_case_only",
                },
                "validated_evidence": {
                    "expected_migration": "1/18 rejected short_trade_boundary -> near_miss",
                    "changed_non_target_case_count": 0,
                    "next_open_return": 0.0246,
                    "next_high_return": 0.0527,
                    "next_close_return": 0.0146,
                },
                "default_mode": "secondary_shadow_entry",
                "keep_guardrails": [
                    "changed_non_target_case_count == 0",
                    "next_high_return >= 0.02",
                    "next_close_return > 0",
                ],
                "decision_rules": {
                    "go": "继续保留为低污染 case-based shadow entry，并纳入更多窗口复核。",
                    "shadow_only": "只有 intraday 通过，close continuation 不稳定。",
                    "rollback": "出现额外样本污染，或 T+1 机会空间失效。",
                },
                "evaluation_policy": {
                    "target_promotion_required": True,
                    "max_changed_non_target_case_count": 0,
                    "go_requirements": {
                        "min_next_high_return_mean": 0.02,
                        "min_next_close_return_mean": 0.0,
                    },
                    "shadow_only_requirements": {
                        "min_next_high_return_mean": 0.02,
                    },
                },
                "execution_bundle": build_execution_bundle(
                    release_mode="score_frontier_release",
                    report_dir=CATALYST_FLOOR_ZERO_REPORT_DIR,
                    artifact_stub="300383_threshold_only_shadow_entry",
                    reference_release_report="data/reports/targeted_short_trade_boundary_release_300383_20260329.json",
                    reference_outcome_report="data/reports/targeted_short_trade_boundary_release_outcomes_300383_20260329.json",
                ),
            },
            {
                "priority_rank": 3,
                "experiment_id": "300724_structural_conflict_shadow_release",
                "track": "case_based_structural_conflict_release",
                "objective": "验证 structural conflict 的重复惩罚是否能在单票范围内释放成 near-miss，而不污染 blocked 簇。",
                "target_cases": ["2026-03-25:300724"],
                "parameter_change": {
                    "hard_block_bearish_conflicts": {"from": True, "to": False},
                    "overhead_conflict_penalty_conflicts": {"from": True, "to": False},
                    "near_miss_threshold": {"from": 0.46, "to": 0.42},
                    "scope": "targeted_case_only",
                },
                "validated_evidence": {
                    "expected_migration": "blocked -> near_miss",
                    "score_target_before": 0.3785,
                    "score_target_after": 0.4235,
                    "changed_non_target_case_count": 0,
                },
                "default_mode": "shadow_structural_candidate",
                "keep_guardrails": [
                    "changed_non_target_case_count == 0",
                    "只释放 300724 单票，不扩散到其他 blocked 样本",
                    "默认不作为 cluster-wide structural 放松依据",
                ],
                "decision_rules": {
                    "go": "只进入 targeted shadow queue，不进入默认 blocked release。",
                    "shadow_only": "窗口内仍仅此一票变化，但后验机会质量不足时继续挂起。",
                    "rollback": "出现任何非目标样本联动释放。",
                },
                "evaluation_policy": {
                    "target_promotion_required": True,
                    "max_changed_non_target_case_count": 0,
                    "go_requirements": {
                        "min_next_close_return_mean": 0.0,
                    },
                    "shadow_only_requirements": {},
                },
                "execution_bundle": build_execution_bundle(
                    release_mode="structural_conflict_release",
                    report_dir=REPLAY_VALIDATION_REPORT_DIR,
                    artifact_stub="300724_structural_conflict_shadow_release",
                    reference_release_report="data/reports/targeted_structural_conflict_release_300724_current_window_20260329.json",
                    profile_overrides={
                        "hard_block_bearish_conflicts": [],
                        "overhead_conflict_penalty_conflicts": [],
                        "near_miss_threshold": 0.42,
                    },
                ),
            },
        ],
        "deferred_queue": [
            {
                "experiment_id": "300113_recurring_frontier_close_continuation",
                "reason": "当前 close-candidate 车道已刷新为 300113，先保留为紧随其后的 recurring frontier 队列。",
            },
            {
                "experiment_id": "600821_recurring_frontier_intraday_primary",
                "reason": "已具备 recurring evidence，但优先级仍低于 001309 / 300383。",
            },
            {
                "experiment_id": "profitability_soft_penalty_conditional_relief",
                "reason": "仍缺和当前 frontier 样本的直接对齐，不应抢在 case-based frontier 前面。",
            },
        ],
    }
    P2_RUNBOOK_JSON_PATH.write_text(json.dumps(runbook, ensure_ascii=False, indent=2), encoding="utf-8")
    return runbook