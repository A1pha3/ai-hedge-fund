from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.analyze_catalyst_theme_frontier import generate_catalyst_theme_frontier_artifacts
from scripts.analyze_btst_candidate_entry_rollout_governance import (
    analyze_btst_candidate_entry_rollout_governance,
    render_btst_candidate_entry_rollout_governance_markdown,
)
from scripts.analyze_btst_candidate_entry_window_scan import (
    analyze_btst_candidate_entry_window_scan,
    render_btst_candidate_entry_window_scan_markdown,
)
from scripts.analyze_btst_primary_roll_forward import (
    analyze_btst_primary_roll_forward,
    render_btst_primary_roll_forward_markdown,
)
from scripts.analyze_btst_primary_window_gap import (
    analyze_btst_primary_window_gap,
    render_btst_primary_window_gap_markdown,
)
from scripts.analyze_btst_primary_window_validation_runbook import (
    analyze_btst_primary_window_validation_runbook,
    render_btst_primary_window_validation_runbook_markdown,
)
from scripts.analyze_btst_recurring_shadow_runbook import (
    analyze_btst_recurring_shadow_runbook,
    render_btst_recurring_shadow_runbook_markdown,
)
from scripts.analyze_btst_governance_synthesis import (
    analyze_btst_governance_synthesis,
    render_btst_governance_synthesis_markdown,
)
from scripts.analyze_btst_rollout_governance_board import (
    analyze_btst_rollout_governance_board,
    render_btst_rollout_governance_board_markdown,
)
from scripts.analyze_btst_replay_cohort import (
    analyze_btst_replay_cohort,
    render_btst_replay_cohort_markdown,
)
from scripts.analyze_btst_independent_window_monitor import (
    analyze_btst_independent_window_monitor,
    render_btst_independent_window_monitor_markdown,
)
from scripts.analyze_btst_tplus1_tplus2_objective_monitor import (
    analyze_btst_tplus1_tplus2_objective_monitor,
    render_btst_tplus1_tplus2_objective_monitor_markdown,
)
from scripts.analyze_multi_window_short_trade_role_candidates import (
    analyze_multi_window_short_trade_role_candidates,
    render_multi_window_short_trade_role_candidates_markdown,
)
from scripts.analyze_recurring_frontier_transition_candidates import (
    analyze_recurring_frontier_transition_candidates,
    render_recurring_frontier_transition_candidates_markdown,
)
from scripts.analyze_short_trade_boundary_recurring_frontier_cases import (
    analyze_short_trade_boundary_recurring_frontier_cases,
    render_short_trade_boundary_recurring_frontier_markdown,
)
from scripts.analyze_short_trade_boundary_score_failures import (
    analyze_short_trade_boundary_score_failures,
    render_short_trade_boundary_score_failure_markdown,
)
from scripts.analyze_short_trade_boundary_score_failures_frontier import (
    analyze_short_trade_boundary_score_failures_frontier,
    render_short_trade_boundary_score_failure_frontier_markdown,
)
from scripts.validate_btst_governance_consistency import (
    render_btst_governance_validation_markdown,
    validate_btst_governance_consistency,
)


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "report_manifest_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "report_manifest_latest.md"
CANDIDATE_ENTRY_FRONTIER_JSON = "btst_candidate_entry_frontier_20260330.json"
CANDIDATE_ENTRY_STRUCTURAL_VALIDATION_JSON = "selection_target_structural_variants_candidate_entry_current_window_20260330.json"
CANDIDATE_ENTRY_SCORE_FRONTIER_JSON = "btst_score_construction_frontier_20260330.json"
CANDIDATE_ENTRY_WINDOW_SCAN_JSON = "btst_candidate_entry_window_scan_20260330.json"
CANDIDATE_ENTRY_WINDOW_SCAN_MD = "btst_candidate_entry_window_scan_20260330.md"
CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_JSON = "p9_candidate_entry_rollout_governance_20260330.json"
CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_MD = "p9_candidate_entry_rollout_governance_20260330.md"
ACTION_BOARD_JSON = "p3_top3_post_execution_action_board_20260401.json"
PRIMARY_ROLL_FORWARD_JSON = "p4_primary_roll_forward_validation_001309_20260330.json"
PRIMARY_ROLL_FORWARD_MD = "p4_primary_roll_forward_validation_001309_20260330.md"
SHADOW_EXPANSION_JSON = "p4_shadow_entry_expansion_board_300383_20260330.json"
SHADOW_LANE_PRIORITY_JSON = "p4_shadow_lane_priority_board_20260401.json"
ROLLOUT_GOVERNANCE_JSON = "p5_btst_rollout_governance_board_20260401.json"
ROLLOUT_GOVERNANCE_MD = "p5_btst_rollout_governance_board_20260401.md"
PRIMARY_WINDOW_GAP_JSON = "p6_primary_window_gap_001309_20260330.json"
PRIMARY_WINDOW_GAP_MD = "p6_primary_window_gap_001309_20260330.md"
RECURRING_SHADOW_RUNBOOK_JSON = "p6_recurring_shadow_runbook_20260401.json"
RECURRING_SHADOW_RUNBOOK_MD = "p6_recurring_shadow_runbook_20260401.md"
RECURRING_CLOSE_BUNDLE_JSON = "btst_recurring_shadow_close_bundle_300113_20260401.json"
RECURRING_CLOSE_BUNDLE_MD = "btst_recurring_shadow_close_bundle_300113_20260401.md"
PRIMARY_WINDOW_VALIDATION_RUNBOOK_JSON = "p7_primary_window_validation_runbook_001309_20260330.json"
PRIMARY_WINDOW_VALIDATION_RUNBOOK_MD = "p7_primary_window_validation_runbook_001309_20260330.md"
SHADOW_PEER_SCAN_JSON = "p7_shadow_peer_scan_300383_20260401.json"
STRUCTURAL_SHADOW_RUNBOOK_JSON = "p8_structural_shadow_runbook_300724_20260330.json"
BTST_PENALTY_FRONTIER_JSON = "btst_penalty_frontier_current_window_20260331.json"
BTST_PENALTY_FRONTIER_MD = "btst_penalty_frontier_current_window_20260331.md"
CATALYST_THEME_FRONTIER_LATEST_JSON = "catalyst_theme_frontier_latest.json"
CATALYST_THEME_FRONTIER_LATEST_MD = "catalyst_theme_frontier_latest.md"
BTST_GOVERNANCE_SYNTHESIS_JSON = "btst_governance_synthesis_latest.json"
BTST_GOVERNANCE_SYNTHESIS_MD = "btst_governance_synthesis_latest.md"
BTST_GOVERNANCE_VALIDATION_JSON = "btst_governance_validation_latest.json"
BTST_GOVERNANCE_VALIDATION_MD = "btst_governance_validation_latest.md"
BTST_REPLAY_COHORT_JSON = "btst_replay_cohort_latest.json"
BTST_REPLAY_COHORT_MD = "btst_replay_cohort_latest.md"
BTST_INDEPENDENT_WINDOW_MONITOR_JSON = "btst_independent_window_monitor_latest.json"
BTST_INDEPENDENT_WINDOW_MONITOR_MD = "btst_independent_window_monitor_latest.md"
BTST_TPLUS1_TPLUS2_OBJECTIVE_MONITOR_JSON = "btst_tplus1_tplus2_objective_monitor_latest.json"
BTST_TPLUS1_TPLUS2_OBJECTIVE_MONITOR_MD = "btst_tplus1_tplus2_objective_monitor_latest.md"
MULTI_WINDOW_ROLE_CANDIDATES_LATEST_JSON = "multi_window_short_trade_role_candidates_latest.json"
MULTI_WINDOW_ROLE_CANDIDATES_LATEST_MD = "multi_window_short_trade_role_candidates_latest.md"
RECURRING_FRONTIER_TRANSITION_LATEST_JSON = "recurring_frontier_transition_candidates_latest.json"
RECURRING_FRONTIER_TRANSITION_LATEST_MD = "recurring_frontier_transition_candidates_latest.md"
SHORT_TRADE_BOUNDARY_SCORE_FAILURES_LATEST_JSON = "short_trade_boundary_score_failures_latest.json"
SHORT_TRADE_BOUNDARY_SCORE_FAILURES_LATEST_MD = "short_trade_boundary_score_failures_latest.md"
SHORT_TRADE_BOUNDARY_SCORE_FAILURES_FRONTIER_LATEST_JSON = "short_trade_boundary_score_failures_frontier_latest.json"
SHORT_TRADE_BOUNDARY_SCORE_FAILURES_FRONTIER_LATEST_MD = "short_trade_boundary_score_failures_frontier_latest.md"
SHORT_TRADE_BOUNDARY_RECURRING_FRONTIER_LATEST_JSON = "short_trade_boundary_recurring_frontier_cases_latest.json"
SHORT_TRADE_BOUNDARY_RECURRING_FRONTIER_LATEST_MD = "short_trade_boundary_recurring_frontier_cases_latest.md"
RECURRING_PAIR_COMPARISON_JSON = "recurring_frontier_release_pair_comparison_600821_vs_300113_catalyst_floor_zero_refresh_20260401.json"
CANDIDATE_ENTRY_FOCUS_TICKERS: tuple[str, ...] = ("300502",)
CANDIDATE_ENTRY_PRESERVE_TICKERS: tuple[str, ...] = ("300394",)
STATIC_ENTRY_GLOB_OVERRIDES: dict[str, str] = {
    "p2_top3_execution_summary": "p2_top3_experiment_execution_summary_*.json",
    "p3_post_execution_action_board": "p3_top3_post_execution_action_board_*.json",
    "p5_rollout_governance_board": "p5_btst_rollout_governance_board_*.json",
    "p6_primary_window_gap": "p6_primary_window_gap_001309_*.json",
    "p6_recurring_shadow_runbook": "p6_recurring_shadow_runbook_*.json",
    "btst_recurring_shadow_close_bundle": "btst_recurring_shadow_close_bundle_*.json",
    "p7_primary_window_validation_runbook": "p7_primary_window_validation_runbook_001309_*.json",
    "p8_structural_shadow_runbook": "p8_structural_shadow_runbook_300724_*.json",
}

STATIC_ENTRY_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "btst_open_ready_delta_latest",
        "path": "data/reports/btst_open_ready_delta_latest.md",
        "report_type": "btst_open_ready_delta",
        "topic": "btst_followup",
        "usage": "tomorrow_open",
        "priority": 1,
        "is_latest": True,
        "question": "相对上一轮，今晚最该知道的 delta 是什么",
        "view_order": 0,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_nightly_control_tower_latest",
        "path": "data/reports/btst_nightly_control_tower_latest.md",
        "report_type": "btst_nightly_control_tower",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "今晚 control tower 的一页总览是什么",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "btst_latest_close_validation_latest",
        "path": "data/reports/btst_latest_close_validation_latest.md",
        "report_type": "btst_latest_close_validation",
        "topic": "btst_followup",
        "usage": "nightly_review",
        "priority": 1,
        "is_latest": True,
        "question": "今天收盘到底验证了什么，明天该如何理解当前 BTST 结论",
        "view_order": 2,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "reports_hub_readme",
        "path": "data/reports/README.md",
        "report_type": "report_hub_readme",
        "topic": "reports_navigation",
        "usage": "navigation",
        "priority": 1,
        "is_latest": True,
        "question": "reports 根入口是什么",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "stable_entry_page",
    },
    {
        "id": "optimize0330_readme",
        "path": "docs/zh-cn/factors/BTST/optimize0330/README.md",
        "report_type": "source_of_truth_doc",
        "topic": "btst_optimize0330",
        "usage": "truth_source",
        "priority": 1,
        "is_latest": True,
        "question": "0330 BTST 当前主线逻辑是什么",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "source_of_truth",
    },
    {
        "id": "optimize0330_checklist",
        "path": "docs/zh-cn/factors/BTST/optimize0330/01-0330-research-execution-checklist.md",
        "report_type": "execution_checklist",
        "topic": "btst_optimize0330",
        "usage": "truth_source",
        "priority": 2,
        "is_latest": True,
        "question": "0330 BTST 当前执行状态和下一步动作是什么",
        "view_order": 2,
        "time_scope": {"label": "rolling"},
        "source_kind": "source_of_truth",
    },
    {
        "id": "arch_optimize_implementation",
        "path": "docs/zh-cn/product/arch/arch_optimize_implementation.md",
        "report_type": "implementation_truth_doc",
        "topic": "upstream_architecture",
        "usage": "truth_source",
        "priority": 3,
        "is_latest": True,
        "question": "上游真实落地事实与系统边界是什么",
        "view_order": 3,
        "time_scope": {"label": "rolling"},
        "source_kind": "source_of_truth",
    },
    {
        "id": "btst_recurring_shadow_split_summary_20260401",
        "path": "docs/zh-cn/product/arch/btst_recurring_shadow_split_summary_20260401.md",
        "report_type": "btst_recurring_shadow_split_summary",
        "topic": "btst_governance",
        "usage": "truth_source",
        "priority": 2,
        "is_latest": True,
        "question": "当前 recurring shadow 的 300113/600821 split 应如何执行",
        "view_order": 4,
        "time_scope": {"label": "rolling"},
        "source_kind": "source_of_truth",
    },
    {
        "id": "btst_governance_synthesis_latest",
        "path": "data/reports/btst_governance_synthesis_latest.md",
        "report_type": "btst_governance_synthesis",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 1,
        "is_latest": True,
        "question": "当前 BTST 治理总览板是什么",
        "view_order": 1,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_governance_validation_latest",
        "path": "data/reports/btst_governance_validation_latest.md",
        "report_type": "btst_governance_validation",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 2,
        "is_latest": True,
        "question": "当前 BTST 治理结论之间是否一致",
        "view_order": 2,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "p2_top3_execution_summary",
        "path": "data/reports/p2_top3_experiment_execution_summary_20260330.json",
        "report_type": "btst_execution_summary",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 1,
        "is_latest": True,
        "question": "Top 3 case-based 执行结果是什么",
        "view_order": 1,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p3_post_execution_action_board",
        "path": "data/reports/p3_top3_post_execution_action_board_20260401.json",
        "report_type": "btst_action_board",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 2,
        "is_latest": True,
        "question": "当前 lane 分流后的动作板是什么",
        "view_order": 2,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p5_rollout_governance_board",
        "path": "data/reports/p5_btst_rollout_governance_board_20260401.json",
        "report_type": "btst_rollout_governance_board",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 3,
        "is_latest": True,
        "question": "当前 default / shadow / freeze 治理结论是什么",
        "view_order": 3,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_micro_window_regression_review",
        "path": "data/reports/btst_micro_window_regression_march_refresh.md",
        "report_type": "btst_micro_window_regression_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 4,
        "is_latest": True,
        "question": "0323-0326 闭环 baseline 与 catalyst_floor_zero 的微窗口回归结果是什么",
        "view_order": 4,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_profile_frontier_review",
        "path": "data/reports/btst_profile_frontier_20260330.md",
        "report_type": "btst_profile_frontier_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 5,
        "is_latest": True,
        "question": "默认 profile 与 staged_breakout/aggressive/conservative 的闭环 frontier 结果是什么",
        "view_order": 5,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_score_construction_frontier_review",
        "path": "data/reports/btst_score_construction_frontier_20260330.md",
        "report_type": "btst_score_construction_frontier_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 6,
        "is_latest": True,
        "question": "只调正向 score weight 的闭环 frontier 结果是什么",
        "view_order": 6,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_penalty_frontier_review",
        "path": "data/reports/btst_penalty_frontier_current_window_20260331.md",
        "report_type": "btst_penalty_frontier_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 7,
        "is_latest": True,
        "question": "broad stale/extension penalty relief 为什么不再是 rollout 路线",
        "view_order": 7,
        "time_scope": {"label": "current_window_20260331"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_candidate_entry_frontier_review",
        "path": "data/reports/btst_candidate_entry_frontier_20260330.md",
        "report_type": "btst_candidate_entry_frontier_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 8,
        "is_latest": True,
        "question": "哪条 candidate entry selective rule 能过滤 300502 并保住 300394",
        "view_order": 8,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_candidate_entry_window_scan_review",
        "path": "data/reports/btst_candidate_entry_window_scan_20260330.md",
        "report_type": "btst_candidate_entry_window_scan_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 9,
        "is_latest": True,
        "question": "弱结构 candidate entry 规则是否已经跨多个独立窗口命中且没有误伤 preserve 样本",
        "view_order": 9,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p9_candidate_entry_rollout_governance",
        "path": "data/reports/p9_candidate_entry_rollout_governance_20260330.md",
        "report_type": "btst_candidate_entry_rollout_governance",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "为什么弱结构 candidate entry 规则当前只能 shadow-only 而不能升级默认",
        "view_order": 10,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_independent_window_monitor_latest",
        "path": "data/reports/btst_independent_window_monitor_latest.md",
        "report_type": "btst_independent_window_monitor",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "001309、300113、600821 还差几个独立窗口，哪条 lane 已经具备重审条件",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_tplus1_tplus2_objective_monitor_latest",
        "path": "data/reports/btst_tplus1_tplus2_objective_monitor_latest.md",
        "report_type": "btst_tplus1_tplus2_objective_monitor",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 10,
        "is_latest": True,
        "question": "当前 BTST 距离“明天买、后天卖，80% 胜率且 5% 收益”目标还有多远",
        "view_order": 10,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_multi_window_role_candidates_latest",
        "path": "data/reports/multi_window_short_trade_role_candidates_latest.md",
        "report_type": "btst_multi_window_role_candidates",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 11,
        "is_latest": True,
        "question": "当前跨窗口 short-trade 角色候选名单是什么",
        "view_order": 11,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_recurring_frontier_transition_latest",
        "path": "data/reports/recurring_frontier_transition_candidates_latest.md",
        "report_type": "btst_recurring_frontier_transition",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 12,
        "is_latest": True,
        "question": "recurring frontier 候选里哪些已接近跨窗口稳定",
        "view_order": 12,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_score_fail_frontier_latest",
        "path": "data/reports/short_trade_boundary_score_failures_frontier_latest.md",
        "report_type": "btst_score_fail_frontier",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 13,
        "is_latest": True,
        "question": "当前 short-trade score-fail 样本里哪些最接近 near-miss rescue",
        "view_order": 13,
        "time_scope": {"label": "latest_btst_followup"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "btst_score_fail_recurring_frontier_latest",
        "path": "data/reports/short_trade_boundary_recurring_frontier_cases_latest.md",
        "report_type": "btst_score_fail_recurring_frontier",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 14,
        "is_latest": True,
        "question": "当前 score-fail recurring 队列里最值得跟踪的 ticker 是谁",
        "view_order": 14,
        "time_scope": {"label": "latest_btst_followup"},
        "source_kind": "generated_governance_artifact",
    },
    {
        "id": "p6_primary_window_gap",
        "path": "data/reports/p6_primary_window_gap_001309_20260330.json",
        "report_type": "btst_window_gap_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 15,
        "is_latest": True,
        "question": "001309 还缺什么窗口证据",
        "view_order": 15,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p6_recurring_shadow_runbook",
        "path": "data/reports/p6_recurring_shadow_runbook_20260401.json",
        "report_type": "btst_recurring_shadow_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 16,
        "is_latest": True,
        "question": "recurring shadow lane 该如何阅读和执行",
        "view_order": 16,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_recurring_shadow_close_bundle",
        "path": "data/reports/btst_recurring_shadow_close_bundle_300113_20260401.json",
        "report_type": "btst_recurring_shadow_close_bundle",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 17,
        "is_latest": True,
        "question": "300113 close-candidate shadow bundle 该如何直接复用",
        "view_order": 17,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p7_primary_window_validation_runbook",
        "path": "data/reports/p7_primary_window_validation_runbook_001309_20260330.json",
        "report_type": "btst_primary_validation_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 17,
        "is_latest": True,
        "question": "001309 后续复跑命令与判断条件是什么",
        "view_order": 17,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p8_structural_shadow_runbook",
        "path": "data/reports/p8_structural_shadow_runbook_300724_20260330.json",
        "report_type": "btst_structural_shadow_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 18,
        "is_latest": True,
        "question": "300724 为什么保持 structural shadow hold",
        "view_order": 18,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_replay_cohort_latest",
        "path": "data/reports/btst_replay_cohort_latest.md",
        "report_type": "btst_replay_cohort",
        "topic": "replay_artifacts",
        "usage": "replay_history",
        "priority": 1,
        "is_latest": True,
        "question": "当前 BTST live/frozen replay 队列和 short-trade 样本汇总是什么",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "generated_runtime_artifact",
    },
    {
        "id": "replay_artifacts_stock_selection_manual",
        "path": "docs/zh-cn/manual/replay-artifacts-stock-selection-manual.md",
        "report_type": "manual",
        "topic": "replay_artifacts",
        "usage": "replay_history",
        "priority": 1,
        "is_latest": True,
        "question": "Replay Artifacts 工作台如何查报告",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "manual",
    },
    {
        "id": "historical_edge_artifact_index",
        "path": "docs/zh-cn/analysis/historical-edge-artifact-index-20260318.md",
        "report_type": "artifact_index",
        "topic": "historical_edge",
        "usage": "replay_history",
        "priority": 2,
        "is_latest": True,
        "question": "历史 edge 专题从哪里进入",
        "view_order": 2,
        "time_scope": {"label": "historical_archive"},
        "source_kind": "artifact_index",
    },
)

READING_PATH_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "navigation",
        "title": "入口导航",
        "description": "先看稳定入口，不直接翻 data/reports 目录。",
        "entry_ids": ["reports_hub_readme", "optimize0330_readme", "optimize0330_checklist", "arch_optimize_implementation", "btst_recurring_shadow_split_summary_20260401"],
    },
    {
        "id": "btst_control_tower",
        "title": "BTST 控制塔",
        "description": "先看相对上一轮的 delta，再看当前 lane 状态，最后确认历史回放样本。",
        "entry_ids": [
            "btst_open_ready_delta_latest",
            "btst_latest_close_validation_latest",
            "btst_nightly_control_tower_latest",
            "btst_governance_synthesis_latest",
            "btst_tplus1_tplus2_objective_monitor_latest",
            "btst_independent_window_monitor_latest",
            "latest_btst_priority_board",
            "latest_btst_catalyst_theme_frontier_markdown",
            "btst_score_fail_frontier_latest",
            "btst_score_fail_recurring_frontier_latest",
            "btst_governance_validation_latest",
            "btst_replay_cohort_latest",
            "p5_rollout_governance_board",
            "btst_recurring_shadow_close_bundle",
            "p9_candidate_entry_rollout_governance",
        ],
    },
    {
        "id": "tomorrow_open",
        "title": "明天开盘",
        "description": "开盘前的最短阅读路径，优先解决明天到底交易什么。",
        "entry_ids": ["btst_open_ready_delta_latest", "btst_latest_close_validation_latest", "latest_btst_priority_board", "latest_btst_opening_watch_card", "latest_btst_execution_card_markdown", "latest_btst_brief_markdown"],
    },
    {
        "id": "nightly_review",
        "title": "晚间复盘",
        "description": "晚间确认本次运行发生了什么、明日结论为何如此。",
        "entry_ids": [
            "btst_open_ready_delta_latest",
            "btst_latest_close_validation_latest",
            "btst_tplus1_tplus2_objective_monitor_latest",
            "btst_nightly_control_tower_latest",
            "latest_btst_session_summary",
            "latest_btst_brief_json",
            "latest_btst_execution_card_json",
            "latest_btst_catalyst_theme_frontier_markdown",
            "btst_score_fail_frontier_latest",
            "latest_btst_selection_snapshot",
        ],
    },
    {
        "id": "btst_governance",
        "title": "BTST 治理主线",
        "description": "解释当前 lane 为什么被保留、冻结或只允许 shadow。",
        "entry_ids": [
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
            "btst_multi_window_role_candidates_latest",
            "btst_recurring_frontier_transition_latest",
            "btst_score_fail_frontier_latest",
            "btst_score_fail_recurring_frontier_latest",
            "p6_primary_window_gap",
            "p6_recurring_shadow_runbook",
            "btst_recurring_shadow_close_bundle",
            "p7_primary_window_validation_runbook",
            "p8_structural_shadow_runbook",
        ],
    },
    {
        "id": "truth_source",
        "title": "真相源文档",
        "description": "专题逻辑、执行状态和上游实现事实的固定 source of truth。",
        "entry_ids": ["optimize0330_readme", "optimize0330_checklist", "arch_optimize_implementation", "btst_recurring_shadow_split_summary_20260401"],
    },
    {
        "id": "replay_history",
        "title": "Replay 与历史专题",
        "description": "需要从工作台或历史专题入口回查时，固定从这里进入。",
        "entry_ids": ["btst_replay_cohort_latest", "replay_artifacts_stock_selection_manual", "historical_edge_artifact_index"],
    },
)


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: str | Path, content: str) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")


def _resolve_existing_artifact_path(
    reports_root: str | Path,
    preferred_name: str,
    *,
    glob_pattern: str | None = None,
) -> Path:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    preferred_path = resolved_reports_root / preferred_name
    if preferred_path.exists():
        return preferred_path
    if not glob_pattern:
        return preferred_path

    matches = sorted(
        [path for path in resolved_reports_root.glob(glob_pattern) if path.is_file()],
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    return matches[0] if matches else preferred_path


def _normalize_trade_date(value: Any) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    if len(digits) != 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"


def _resolve_repo_root(reports_root: Path) -> Path:
    resolved_reports_root = reports_root.expanduser().resolve()
    if resolved_reports_root.name == "reports" and resolved_reports_root.parent.name == "data":
        return resolved_reports_root.parent.parent
    return resolved_reports_root.parent


def _repo_relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _build_entry(
    *,
    entry_id: str,
    absolute_path: Path,
    repo_root: Path,
    report_type: str,
    topic: str,
    usage: str,
    priority: int,
    is_latest: bool,
    question: str,
    view_order: int,
    time_scope: dict[str, Any],
    source_kind: str,
    report_dir: str | None = None,
) -> dict[str, Any] | None:
    resolved_path = absolute_path.expanduser().resolve()
    if not resolved_path.exists():
        return None
    return {
        "id": entry_id,
        "report_path": _repo_relative_path(resolved_path, repo_root),
        "absolute_path": resolved_path.as_posix(),
        "report_type": report_type,
        "topic": topic,
        "usage": usage,
        "priority": priority,
        "is_latest": is_latest,
        "question": question,
        "view_order": view_order,
        "time_scope": time_scope,
        "source_kind": source_kind,
        "report_dir": report_dir,
    }


def _looks_like_report_dir(path: Path) -> bool:
    return path.is_dir() and (path / "session_summary.json").exists() and (path / "selection_artifacts").exists()


def _discover_report_dirs(reports_root: Path) -> list[Path]:
    resolved_reports_root = reports_root.expanduser().resolve()
    if not resolved_reports_root.exists():
        return []
    return sorted(
        candidate
        for candidate in resolved_reports_root.iterdir()
        if _looks_like_report_dir(candidate) and candidate.name.startswith("paper_trading")
    )


def _extract_btst_candidate(report_dir: Path, repo_root: Path) -> dict[str, Any] | None:
    summary = _load_json(report_dir / "session_summary.json")
    followup = dict(summary.get("btst_followup") or {})
    artifacts = dict(summary.get("artifacts") or {})
    selection_target = str(summary.get("plan_generation", {}).get("selection_target") or summary.get("selection_target") or "")

    brief_json_path = followup.get("brief_json") or artifacts.get("btst_next_day_trade_brief_json")
    brief_markdown_path = followup.get("brief_markdown") or artifacts.get("btst_next_day_trade_brief_markdown")
    card_json_path = followup.get("execution_card_json") or artifacts.get("btst_premarket_execution_card_json")
    card_markdown_path = followup.get("execution_card_markdown") or artifacts.get("btst_premarket_execution_card_markdown")
    opening_card_markdown_path = followup.get("opening_watch_card_markdown") or artifacts.get("btst_opening_watch_card_markdown")
    priority_board_markdown_path = followup.get("priority_board_markdown") or artifacts.get("btst_next_day_priority_board_markdown")
    catalyst_theme_frontier_json_path = followup.get("catalyst_theme_frontier_json") or artifacts.get("btst_catalyst_theme_frontier_json")
    catalyst_theme_frontier_markdown_path = followup.get("catalyst_theme_frontier_markdown") or artifacts.get("btst_catalyst_theme_frontier_markdown")
    if not any([brief_json_path, brief_markdown_path, card_json_path, card_markdown_path]):
        return None

    trade_date = _normalize_trade_date(followup.get("trade_date") or summary.get("end_date"))
    next_trade_date = _normalize_trade_date(followup.get("next_trade_date"))
    selection_snapshot_path = report_dir / "selection_artifacts" / trade_date / "selection_snapshot.json" if trade_date else None
    opening_card_path = Path(opening_card_markdown_path).expanduser().resolve() if opening_card_markdown_path else None
    if opening_card_path is None and next_trade_date:
        opening_card_path = report_dir / f"btst_opening_watch_card_{next_trade_date.replace('-', '')}.md"

    trade_date_rank = trade_date or _normalize_trade_date(summary.get("end_date")) or ""
    selection_target_rank = 2 if selection_target == "short_trade_only" else 1

    return {
        "report_dir": report_dir.resolve(),
        "report_dir_name": report_dir.name,
        "report_dir_path": _repo_relative_path(report_dir, repo_root),
        "selection_target": selection_target or None,
        "trade_date": trade_date,
        "next_trade_date": next_trade_date,
        "brief_json_path": Path(brief_json_path).expanduser().resolve() if brief_json_path else None,
        "brief_markdown_path": Path(brief_markdown_path).expanduser().resolve() if brief_markdown_path else None,
        "card_json_path": Path(card_json_path).expanduser().resolve() if card_json_path else None,
        "card_markdown_path": Path(card_markdown_path).expanduser().resolve() if card_markdown_path else None,
        "session_summary_path": (report_dir / "session_summary.json").resolve(),
        "selection_snapshot_path": selection_snapshot_path.resolve() if selection_snapshot_path and selection_snapshot_path.exists() else None,
        "opening_card_path": opening_card_path.resolve() if opening_card_path and opening_card_path.exists() else None,
        "priority_board_markdown_path": Path(priority_board_markdown_path).expanduser().resolve() if priority_board_markdown_path else None,
        "catalyst_theme_frontier_json_path": Path(catalyst_theme_frontier_json_path).expanduser().resolve() if catalyst_theme_frontier_json_path else None,
        "catalyst_theme_frontier_markdown_path": Path(catalyst_theme_frontier_markdown_path).expanduser().resolve() if catalyst_theme_frontier_markdown_path else None,
        "rank": (selection_target_rank, trade_date_rank, report_dir.stat().st_mtime_ns, report_dir.name),
    }


def _select_latest_btst_candidate(reports_root: Path, repo_root: Path) -> dict[str, Any] | None:
    candidates = [candidate for candidate in (_extract_btst_candidate(path, repo_root) for path in _discover_report_dirs(reports_root)) if candidate]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate["rank"])


def _build_static_entries(repo_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for spec in STATIC_ENTRY_SPECS:
        absolute_path = repo_root / spec["path"]
        if not absolute_path.exists() and spec["id"] in STATIC_ENTRY_GLOB_OVERRIDES and str(spec["path"]).startswith("data/reports/"):
            resolved_reports_root = repo_root / "data" / "reports"
            relative_name = str(spec["path"]).replace("data/reports/", "", 1)
            absolute_path = _resolve_existing_artifact_path(
                resolved_reports_root,
                relative_name,
                glob_pattern=STATIC_ENTRY_GLOB_OVERRIDES[spec["id"]],
            )
        entry = _build_entry(
            entry_id=spec["id"],
            absolute_path=absolute_path,
            repo_root=repo_root,
            report_type=spec["report_type"],
            topic=spec["topic"],
            usage=spec["usage"],
            priority=int(spec["priority"]),
            is_latest=bool(spec["is_latest"]),
            question=spec["question"],
            view_order=int(spec["view_order"]),
            time_scope=dict(spec["time_scope"]),
            source_kind=spec["source_kind"],
        )
        if entry:
            entries.append(entry)
    return entries


def _build_dynamic_latest_btst_entries(latest_btst_run: dict[str, Any] | None, repo_root: Path) -> list[dict[str, Any]]:
    if not latest_btst_run:
        return []

    report_dir = latest_btst_run["report_dir_path"]
    time_scope = {
        "label": "latest_btst_followup",
        "trade_date": latest_btst_run.get("trade_date"),
        "next_trade_date": latest_btst_run.get("next_trade_date"),
    }

    dynamic_specs = [
        {
            "id": "latest_btst_priority_board",
            "path": latest_btst_run.get("priority_board_markdown_path"),
            "report_type": "btst_next_day_priority_board_markdown",
            "topic": "btst_followup",
            "usage": "tomorrow_open",
            "priority": 1,
            "is_latest": True,
            "question": "明天应该按什么顺序看票",
            "view_order": 1,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_opening_watch_card",
            "path": latest_btst_run.get("opening_card_path"),
            "report_type": "btst_opening_watch_card",
            "topic": "btst_followup",
            "usage": "tomorrow_open",
            "priority": 2,
            "is_latest": True,
            "question": "明天开盘第一眼该看什么",
            "view_order": 2,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_execution_card_markdown",
            "path": latest_btst_run.get("card_markdown_path"),
            "report_type": "btst_premarket_execution_card_markdown",
            "topic": "btst_followup",
            "usage": "tomorrow_open",
            "priority": 3,
            "is_latest": True,
            "question": "当前执行姿态和 guardrails 是什么",
            "view_order": 3,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_brief_markdown",
            "path": latest_btst_run.get("brief_markdown_path"),
            "report_type": "btst_next_day_trade_brief_markdown",
            "topic": "btst_followup",
            "usage": "tomorrow_open",
            "priority": 4,
            "is_latest": True,
            "question": "明日主票、观察票和排除票结论是什么",
            "view_order": 4,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_session_summary",
            "path": latest_btst_run.get("session_summary_path"),
            "report_type": "paper_trading_session_summary",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 1,
            "is_latest": True,
            "question": "这次运行整体发生了什么",
            "view_order": 1,
            "source_kind": "generated_runtime_artifact",
        },
        {
            "id": "latest_btst_brief_json",
            "path": latest_btst_run.get("brief_json_path"),
            "report_type": "btst_next_day_trade_brief_json",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 2,
            "is_latest": True,
            "question": "结构化主票与观察票结论是什么",
            "view_order": 2,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_execution_card_json",
            "path": latest_btst_run.get("card_json_path"),
            "report_type": "btst_premarket_execution_card_json",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 3,
            "is_latest": True,
            "question": "结构化执行 guardrails 是什么",
            "view_order": 3,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_catalyst_theme_frontier_markdown",
            "path": latest_btst_run.get("catalyst_theme_frontier_markdown_path"),
            "report_type": "catalyst_theme_frontier_markdown",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 4,
            "is_latest": True,
            "question": "题材催化影子池离正式研究池还差什么",
            "view_order": 4,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_selection_snapshot",
            "path": latest_btst_run.get("selection_snapshot_path"),
            "report_type": "selection_snapshot",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 5,
            "is_latest": True,
            "question": "逐票底层证据是什么",
            "view_order": 5,
            "source_kind": "generated_runtime_artifact",
        },
    ]

    entries: list[dict[str, Any]] = []
    for spec in dynamic_specs:
        path = spec.get("path")
        if not path:
            continue
        entry = _build_entry(
            entry_id=spec["id"],
            absolute_path=Path(path),
            repo_root=repo_root,
            report_type=spec["report_type"],
            topic=spec["topic"],
            usage=spec["usage"],
            priority=int(spec["priority"]),
            is_latest=bool(spec["is_latest"]),
            question=spec["question"],
            view_order=int(spec["view_order"]),
            time_scope=dict(time_scope),
            source_kind=spec["source_kind"],
            report_dir=report_dir,
        )
        if entry:
            entries.append(entry)
    return entries


def refresh_latest_btst_catalyst_theme_frontier_artifacts(latest_btst_run: dict[str, Any] | None) -> dict[str, Any]:
    if not latest_btst_run:
        return {
            "status": "skipped_no_latest_btst_run",
        }

    report_dir = Path(latest_btst_run["report_dir"]).expanduser().resolve()
    summary_path = report_dir / "session_summary.json"
    if not summary_path.exists():
        return {
            "status": "skipped_missing_session_summary",
            "report_dir": report_dir.name,
        }

    try:
        frontier_result = generate_catalyst_theme_frontier_artifacts(
            report_dir,
            output_json=report_dir / CATALYST_THEME_FRONTIER_LATEST_JSON,
            output_md=report_dir / CATALYST_THEME_FRONTIER_LATEST_MD,
        )
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "report_dir": report_dir.name,
            "error": str(exc),
        }

    summary = _load_json(summary_path)
    followup = dict(summary.get("btst_followup") or {})
    followup.update(
        {
            "catalyst_theme_frontier_json": frontier_result["json_path"],
            "catalyst_theme_frontier_markdown": frontier_result["markdown_path"],
        }
    )
    summary["btst_followup"] = followup

    artifacts = dict(summary.get("artifacts") or {})
    artifacts.update(
        {
            "btst_catalyst_theme_frontier_json": frontier_result["json_path"],
            "btst_catalyst_theme_frontier_markdown": frontier_result["markdown_path"],
        }
    )
    summary["artifacts"] = artifacts
    _write_json(summary_path, summary)

    analysis = dict(frontier_result.get("analysis") or {})
    recommended_variant = dict(analysis.get("recommended_variant") or {})
    return {
        "status": "refreshed",
        "report_dir": report_dir.name,
        "shadow_candidate_count": int(analysis.get("shadow_candidate_count") or 0),
        "baseline_selected_count": int(analysis.get("baseline_selected_count") or 0),
        "recommended_variant_name": recommended_variant.get("variant_name"),
        "recommended_promoted_shadow_count": int(recommended_variant.get("promoted_shadow_count") or 0),
        "recommended_relaxation_cost": recommended_variant.get("threshold_relaxation_cost"),
        "output_json": frontier_result["json_path"],
        "output_markdown": frontier_result["markdown_path"],
    }


def refresh_btst_candidate_entry_shadow_lane_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    frontier_report_path = resolved_reports_root / CANDIDATE_ENTRY_FRONTIER_JSON
    structural_validation_path = resolved_reports_root / CANDIDATE_ENTRY_STRUCTURAL_VALIDATION_JSON
    score_frontier_path = resolved_reports_root / CANDIDATE_ENTRY_SCORE_FRONTIER_JSON
    window_scan_json_path = resolved_reports_root / CANDIDATE_ENTRY_WINDOW_SCAN_JSON
    window_scan_md_path = resolved_reports_root / CANDIDATE_ENTRY_WINDOW_SCAN_MD
    rollout_governance_json_path = resolved_reports_root / CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_JSON
    rollout_governance_md_path = resolved_reports_root / CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_MD

    required_inputs = {
        "frontier_report": frontier_report_path,
        "structural_validation": structural_validation_path,
        "score_frontier_report": score_frontier_path,
    }
    missing_inputs = [label for label, path in required_inputs.items() if not path.exists()]
    if missing_inputs:
        return {
            "status": "skipped_missing_inputs",
            "missing_inputs": missing_inputs,
            "window_report_count": 0,
        }

    report_dirs = [path for path in _discover_report_dirs(resolved_reports_root) if "paper_trading_window" in path.name]
    if not report_dirs:
        return {
            "status": "skipped_no_window_reports",
            "missing_inputs": [],
            "window_report_count": 0,
        }

    try:
        window_scan_analysis = analyze_btst_candidate_entry_window_scan(
            report_dirs,
            structural_variant="exclude_watchlist_avoid_weak_structure_entries",
            focus_tickers=list(CANDIDATE_ENTRY_FOCUS_TICKERS),
            preserve_tickers=list(CANDIDATE_ENTRY_PRESERVE_TICKERS),
        )
        window_scan_json_path.write_text(json.dumps(window_scan_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        window_scan_md_path.write_text(render_btst_candidate_entry_window_scan_markdown(window_scan_analysis), encoding="utf-8")

        rollout_governance_analysis = analyze_btst_candidate_entry_rollout_governance(
            frontier_report_path,
            structural_validation_path=structural_validation_path,
            window_scan_path=window_scan_json_path,
            score_frontier_path=score_frontier_path,
        )
        rollout_governance_json_path.write_text(json.dumps(rollout_governance_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rollout_governance_md_path.write_text(render_btst_candidate_entry_rollout_governance_markdown(rollout_governance_analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "missing_inputs": [],
            "window_report_count": len(report_dirs),
            "error": str(exc),
        }

    return {
        "status": "refreshed",
        "missing_inputs": [],
        "window_report_count": len(report_dirs),
        "filtered_report_count": window_scan_analysis.get("filtered_report_count"),
        "focus_hit_report_count": window_scan_analysis.get("focus_hit_report_count"),
        "preserve_misfire_report_count": window_scan_analysis.get("preserve_misfire_report_count"),
        "rollout_readiness": window_scan_analysis.get("rollout_readiness"),
        "lane_status": rollout_governance_analysis.get("lane_status"),
        "window_scan_json": window_scan_json_path.as_posix(),
        "rollout_governance_json": rollout_governance_json_path.as_posix(),
    }


def refresh_btst_window_evidence_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    report_dirs = [path for path in _discover_report_dirs(resolved_reports_root) if "paper_trading_window" in path.name]
    if not report_dirs:
        return {
            "status": "skipped_no_window_reports",
            "window_report_count": 0,
        }

    candidate_json_path = resolved_reports_root / MULTI_WINDOW_ROLE_CANDIDATES_LATEST_JSON
    candidate_md_path = resolved_reports_root / MULTI_WINDOW_ROLE_CANDIDATES_LATEST_MD
    try:
        candidate_analysis = analyze_multi_window_short_trade_role_candidates(
            report_dirs,
            min_short_trade_trade_dates=2,
        )
        _write_json(candidate_json_path, candidate_analysis)
        _write_markdown(candidate_md_path, render_multi_window_short_trade_role_candidates_markdown(candidate_analysis))
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "window_report_count": len(report_dirs),
            "error": str(exc),
        }

    refresh: dict[str, Any] = {
        "status": "refreshed",
        "window_report_count": len(report_dirs),
        "candidate_count": candidate_analysis.get("candidate_count"),
        "stable_candidate_count": candidate_analysis.get("stable_candidate_count"),
        "candidate_report_json": candidate_json_path.as_posix(),
        "candidate_report_markdown": candidate_md_path.as_posix(),
        "primary_refresh_status": "skipped_missing_execution_summary",
        "primary_window_gap_status": "skipped_missing_primary_roll_forward",
        "primary_window_validation_status": "skipped_missing_primary_window_gap",
    }

    execution_summary_path = resolved_reports_root / "p2_top3_experiment_execution_summary_20260330.json"
    if not execution_summary_path.exists():
        return refresh

    primary_roll_forward_json_path = resolved_reports_root / PRIMARY_ROLL_FORWARD_JSON
    primary_roll_forward_md_path = resolved_reports_root / PRIMARY_ROLL_FORWARD_MD
    try:
        primary_analysis = analyze_btst_primary_roll_forward(
            execution_summary_path,
            candidate_report_path=candidate_json_path,
            ticker="001309",
        )
        _write_json(primary_roll_forward_json_path, primary_analysis)
        _write_markdown(primary_roll_forward_md_path, render_btst_primary_roll_forward_markdown(primary_analysis))
        refresh["primary_refresh_status"] = "refreshed"
        refresh["primary_roll_forward_verdict"] = primary_analysis.get("roll_forward_verdict")
        refresh["primary_distinct_window_count"] = primary_analysis.get("distinct_window_count")
    except Exception as exc:
        refresh["primary_refresh_status"] = "skipped_refresh_error"
        refresh["primary_refresh_error"] = str(exc)
        return refresh

    primary_window_gap_json_path = resolved_reports_root / PRIMARY_WINDOW_GAP_JSON
    primary_window_gap_md_path = resolved_reports_root / PRIMARY_WINDOW_GAP_MD
    try:
        primary_gap_analysis = analyze_btst_primary_window_gap(
            primary_roll_forward_json_path,
            candidate_report_path=candidate_json_path,
            ticker="001309",
        )
        _write_json(primary_window_gap_json_path, primary_gap_analysis)
        _write_markdown(primary_window_gap_md_path, render_btst_primary_window_gap_markdown(primary_gap_analysis))
        refresh["primary_window_gap_status"] = "refreshed"
        refresh["primary_missing_window_count"] = primary_gap_analysis.get("missing_window_count")
    except Exception as exc:
        refresh["primary_window_gap_status"] = "skipped_refresh_error"
        refresh["primary_window_gap_error"] = str(exc)
        return refresh

    primary_window_validation_json_path = resolved_reports_root / PRIMARY_WINDOW_VALIDATION_RUNBOOK_JSON
    primary_window_validation_md_path = resolved_reports_root / PRIMARY_WINDOW_VALIDATION_RUNBOOK_MD
    try:
        primary_validation_analysis = analyze_btst_primary_window_validation_runbook(
            candidate_json_path,
            primary_roll_forward_path=primary_roll_forward_json_path,
            primary_window_gap_path=primary_window_gap_json_path,
            ticker="001309",
        )
        _write_json(primary_window_validation_json_path, primary_validation_analysis)
        _write_markdown(primary_window_validation_md_path, render_btst_primary_window_validation_runbook_markdown(primary_validation_analysis))
        refresh["primary_window_validation_status"] = "refreshed"
        refresh["primary_validation_verdict"] = primary_validation_analysis.get("validation_verdict")
    except Exception as exc:
        refresh["primary_window_validation_status"] = "skipped_refresh_error"
        refresh["primary_window_validation_error"] = str(exc)

    return refresh


def refresh_btst_score_fail_frontier_artifacts(
    reports_root: str | Path,
    *,
    latest_btst_run: dict[str, Any] | None = None,
    window_evidence_refresh: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    if not latest_btst_run:
        return {
            "status": "skipped_no_latest_btst_run",
        }

    report_dir_value = latest_btst_run.get("report_dir")
    report_dir = Path(report_dir_value).expanduser().resolve() if report_dir_value else None
    if report_dir is None or not report_dir.exists():
        return {
            "status": "skipped_missing_latest_report_dir",
        }

    analysis_json_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_SCORE_FAILURES_LATEST_JSON
    analysis_md_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_SCORE_FAILURES_LATEST_MD
    frontier_json_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_SCORE_FAILURES_FRONTIER_LATEST_JSON
    frontier_md_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_SCORE_FAILURES_FRONTIER_LATEST_MD
    recurring_json_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_RECURRING_FRONTIER_LATEST_JSON
    recurring_md_path = resolved_reports_root / SHORT_TRADE_BOUNDARY_RECURRING_FRONTIER_LATEST_MD

    try:
        score_fail_analysis = analyze_short_trade_boundary_score_failures(report_dir)
        score_fail_frontier_analysis = analyze_short_trade_boundary_score_failures_frontier(report_dir)
        recurring_frontier_analysis = analyze_short_trade_boundary_recurring_frontier_cases(report_dir)
        _write_json(analysis_json_path, score_fail_analysis)
        _write_markdown(analysis_md_path, render_short_trade_boundary_score_failure_markdown(score_fail_analysis))
        _write_json(frontier_json_path, score_fail_frontier_analysis)
        _write_markdown(frontier_md_path, render_short_trade_boundary_score_failure_frontier_markdown(score_fail_frontier_analysis))
        _write_json(recurring_json_path, recurring_frontier_analysis)
        _write_markdown(recurring_md_path, render_short_trade_boundary_recurring_frontier_markdown(recurring_frontier_analysis))
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "report_dir": report_dir.name,
            "error": str(exc),
        }

    refresh: dict[str, Any] = {
        "status": "refreshed",
        "report_dir": report_dir.name,
        "rejected_short_trade_boundary_count": score_fail_analysis.get("rejected_short_trade_boundary_count"),
        "rescueable_case_count": score_fail_frontier_analysis.get("rescueable_case_count"),
        "threshold_only_rescue_count": score_fail_frontier_analysis.get("rescueable_with_threshold_only_count"),
        "recurring_case_count": recurring_frontier_analysis.get("recurring_case_count"),
        "priority_queue_tickers": [
            str(row.get("ticker") or "")
            for row in list(recurring_frontier_analysis.get("priority_queue") or [])[:3]
            if row.get("ticker")
        ],
        "top_rescue_tickers": [
            str(row.get("ticker") or "")
            for row in list(score_fail_frontier_analysis.get("minimal_near_miss_rows") or [])[:3]
            if row.get("ticker")
        ],
        "analysis_json": analysis_json_path.as_posix(),
        "analysis_markdown": analysis_md_path.as_posix(),
        "frontier_json": frontier_json_path.as_posix(),
        "frontier_markdown": frontier_md_path.as_posix(),
        "recurring_json": recurring_json_path.as_posix(),
        "recurring_markdown": recurring_md_path.as_posix(),
        "transition_refresh_status": "skipped_no_window_reports",
        "recurring_shadow_refresh_status": "skipped_missing_inputs",
    }

    report_dirs = [path for path in _discover_report_dirs(resolved_reports_root) if "paper_trading_window" in path.name]
    recurring_transition_json_path = resolved_reports_root / RECURRING_FRONTIER_TRANSITION_LATEST_JSON
    recurring_transition_md_path = resolved_reports_root / RECURRING_FRONTIER_TRANSITION_LATEST_MD
    if report_dirs:
        try:
            recurring_transition_analysis = analyze_recurring_frontier_transition_candidates(
                recurring_json_path,
                role_history_report_dirs=report_dirs,
            )
            _write_json(recurring_transition_json_path, recurring_transition_analysis)
            _write_markdown(recurring_transition_md_path, render_recurring_frontier_transition_candidates_markdown(recurring_transition_analysis))
            refresh["transition_refresh_status"] = "refreshed"
            refresh["transition_candidate_count"] = len(list(recurring_transition_analysis.get("candidates") or []))
            refresh["transition_json"] = recurring_transition_json_path.as_posix()
            refresh["transition_markdown"] = recurring_transition_md_path.as_posix()
        except Exception as exc:
            refresh["transition_refresh_status"] = "skipped_refresh_error"
            refresh["transition_refresh_error"] = str(exc)

    candidate_report_json = str((window_evidence_refresh or {}).get("candidate_report_json") or "")
    shadow_lane_priority_path = _resolve_existing_artifact_path(
        resolved_reports_root,
        SHADOW_LANE_PRIORITY_JSON,
        glob_pattern="p4_shadow_lane_priority_board_*.json",
    )
    recurring_pair_comparison_path = _resolve_existing_artifact_path(
        resolved_reports_root,
        RECURRING_PAIR_COMPARISON_JSON,
        glob_pattern="recurring_frontier_release_pair_comparison_*.json",
    )
    recurring_shadow_inputs = {
        "shadow_lane_priority": shadow_lane_priority_path,
        "recurring_pair_comparison": recurring_pair_comparison_path,
        "candidate_report": Path(candidate_report_json).expanduser().resolve() if candidate_report_json else None,
        "recurring_transition_report": recurring_transition_json_path if recurring_transition_json_path.exists() else None,
        "recurring_close_bundle": _resolve_existing_artifact_path(
            resolved_reports_root,
            RECURRING_CLOSE_BUNDLE_JSON,
            glob_pattern="btst_recurring_shadow_close_bundle_*.json",
        ),
    }
    missing_recurring_shadow_inputs = [
        label
        for label, path in recurring_shadow_inputs.items()
        if path is None or not Path(path).exists()
    ]
    if missing_recurring_shadow_inputs:
        refresh["recurring_shadow_refresh_status"] = "skipped_missing_inputs"
        refresh["missing_recurring_shadow_inputs"] = missing_recurring_shadow_inputs
        return refresh

    recurring_shadow_json_path = resolved_reports_root / RECURRING_SHADOW_RUNBOOK_JSON
    recurring_shadow_md_path = resolved_reports_root / RECURRING_SHADOW_RUNBOOK_MD
    try:
        recurring_shadow_analysis = analyze_btst_recurring_shadow_runbook(
            recurring_shadow_inputs["shadow_lane_priority"],
            recurring_pair_comparison_path=recurring_shadow_inputs["recurring_pair_comparison"],
            candidate_report_path=recurring_shadow_inputs["candidate_report"],
            recurring_transition_report_path=recurring_shadow_inputs["recurring_transition_report"],
            recurring_close_bundle_path=recurring_shadow_inputs["recurring_close_bundle"] if recurring_shadow_inputs["recurring_close_bundle"].exists() else None,
        )
        _write_json(recurring_shadow_json_path, recurring_shadow_analysis)
        _write_markdown(recurring_shadow_md_path, render_btst_recurring_shadow_runbook_markdown(recurring_shadow_analysis))
        refresh["recurring_shadow_refresh_status"] = "refreshed"
        refresh["recurring_shadow_global_validation_verdict"] = recurring_shadow_analysis.get("global_validation_verdict")
        refresh["recurring_shadow_close_candidate_status"] = dict(recurring_shadow_analysis.get("close_candidate") or {}).get("lane_status")
        refresh["recurring_shadow_intraday_control_status"] = dict(recurring_shadow_analysis.get("intraday_control") or {}).get("lane_status")
    except Exception as exc:
        refresh["recurring_shadow_refresh_status"] = "skipped_refresh_error"
        refresh["recurring_shadow_refresh_error"] = str(exc)

    return refresh


def refresh_btst_rollout_governance_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    required_inputs = {
        "action_board": _resolve_existing_artifact_path(resolved_reports_root, ACTION_BOARD_JSON, glob_pattern="p3_top3_post_execution_action_board_*.json"),
        "primary_roll_forward": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_ROLL_FORWARD_JSON, glob_pattern="p4_primary_roll_forward_validation_001309_*.json"),
        "shadow_expansion": _resolve_existing_artifact_path(resolved_reports_root, SHADOW_EXPANSION_JSON, glob_pattern="p4_shadow_entry_expansion_board_300383_*.json"),
        "shadow_lane_priority": _resolve_existing_artifact_path(resolved_reports_root, SHADOW_LANE_PRIORITY_JSON, glob_pattern="p4_shadow_lane_priority_board_*.json"),
        "primary_window_gap": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_GAP_JSON, glob_pattern="p6_primary_window_gap_001309_*.json"),
        "recurring_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, RECURRING_SHADOW_RUNBOOK_JSON, glob_pattern="p6_recurring_shadow_runbook_*.json"),
        "primary_window_validation_runbook": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_VALIDATION_RUNBOOK_JSON, glob_pattern="p7_primary_window_validation_runbook_001309_*.json"),
        "shadow_peer_scan": _resolve_existing_artifact_path(resolved_reports_root, SHADOW_PEER_SCAN_JSON, glob_pattern="p7_shadow_peer_scan_300383_*.json"),
        "structural_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, STRUCTURAL_SHADOW_RUNBOOK_JSON, glob_pattern="p8_structural_shadow_runbook_300724_*.json"),
        "recurring_close_bundle": _resolve_existing_artifact_path(resolved_reports_root, RECURRING_CLOSE_BUNDLE_JSON, glob_pattern="btst_recurring_shadow_close_bundle_*.json"),
    }
    missing_inputs = [label for label, path in required_inputs.items() if label != "recurring_close_bundle" and not path.exists()]
    if missing_inputs:
        return {
            "status": "skipped_missing_inputs",
            "missing_inputs": missing_inputs,
        }

    output_json_path = resolved_reports_root / ROLLOUT_GOVERNANCE_JSON
    output_md_path = resolved_reports_root / ROLLOUT_GOVERNANCE_MD
    penalty_frontier_path = resolved_reports_root / BTST_PENALTY_FRONTIER_JSON
    try:
        analysis = analyze_btst_rollout_governance_board(
            required_inputs["action_board"],
            primary_roll_forward_path=required_inputs["primary_roll_forward"],
            shadow_expansion_path=required_inputs["shadow_expansion"],
            shadow_lane_priority_path=required_inputs["shadow_lane_priority"],
            primary_window_gap_path=required_inputs["primary_window_gap"],
            recurring_shadow_runbook_path=required_inputs["recurring_shadow_runbook"],
            recurring_close_bundle_path=required_inputs["recurring_close_bundle"] if required_inputs["recurring_close_bundle"].exists() else None,
            primary_window_validation_runbook_path=required_inputs["primary_window_validation_runbook"],
            shadow_peer_scan_path=required_inputs["shadow_peer_scan"],
            structural_shadow_runbook_path=required_inputs["structural_shadow_runbook"],
            penalty_frontier_path=penalty_frontier_path if penalty_frontier_path.exists() else None,
        )
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_rollout_governance_board_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "missing_inputs": [],
            "error": str(exc),
        }

    penalty_frontier_summary = dict(analysis.get("penalty_frontier_summary") or {})
    return {
        "status": "refreshed",
        "missing_inputs": [],
        "governance_row_count": len(list(analysis.get("governance_rows") or [])),
        "next_task_count": len(list(analysis.get("next_3_tasks") or [])),
        "penalty_frontier_status": penalty_frontier_summary.get("status"),
        "penalty_frontier_passing_variant_count": penalty_frontier_summary.get("passing_variant_count"),
        "output_json": output_json_path.as_posix(),
    }


def refresh_btst_governance_synthesis_artifacts(
    reports_root: str | Path,
    *,
    latest_btst_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    required_inputs = {
        "action_board": _resolve_existing_artifact_path(resolved_reports_root, ACTION_BOARD_JSON, glob_pattern="p3_top3_post_execution_action_board_*.json"),
        "rollout_governance": _resolve_existing_artifact_path(resolved_reports_root, ROLLOUT_GOVERNANCE_JSON, glob_pattern="p5_btst_rollout_governance_board_*.json"),
        "primary_window_gap": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_GAP_JSON, glob_pattern="p6_primary_window_gap_001309_*.json"),
        "recurring_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, RECURRING_SHADOW_RUNBOOK_JSON, glob_pattern="p6_recurring_shadow_runbook_*.json"),
        "primary_window_validation_runbook": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_VALIDATION_RUNBOOK_JSON, glob_pattern="p7_primary_window_validation_runbook_001309_*.json"),
        "structural_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, STRUCTURAL_SHADOW_RUNBOOK_JSON, glob_pattern="p8_structural_shadow_runbook_300724_*.json"),
        "candidate_entry_governance": _resolve_existing_artifact_path(resolved_reports_root, CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_JSON, glob_pattern="p9_candidate_entry_rollout_governance_*.json"),
    }
    missing_inputs = [label for label, path in required_inputs.items() if not path.exists()]
    if missing_inputs:
        return {
            "status": "skipped_missing_inputs",
            "missing_inputs": missing_inputs,
        }

    output_json_path = resolved_reports_root / BTST_GOVERNANCE_SYNTHESIS_JSON
    output_md_path = resolved_reports_root / BTST_GOVERNANCE_SYNTHESIS_MD
    try:
        analysis = analyze_btst_governance_synthesis(
            resolved_reports_root,
            action_board_path=required_inputs["action_board"],
            rollout_governance_path=required_inputs["rollout_governance"],
            primary_window_gap_path=required_inputs["primary_window_gap"],
            recurring_shadow_runbook_path=required_inputs["recurring_shadow_runbook"],
            primary_window_validation_runbook_path=required_inputs["primary_window_validation_runbook"],
            structural_shadow_runbook_path=required_inputs["structural_shadow_runbook"],
            candidate_entry_governance_path=required_inputs["candidate_entry_governance"],
            latest_btst_report_dir=latest_btst_run.get("report_dir") if latest_btst_run else None,
        )
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_governance_synthesis_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "missing_inputs": [],
            "error": str(exc),
        }

    latest_followup = dict(analysis.get("latest_btst_followup") or {})
    return {
        "status": "refreshed",
        "missing_inputs": [],
        "ready_lane_count": analysis.get("ready_lane_count"),
        "waiting_lane_count": analysis.get("waiting_lane_count"),
        "latest_trade_date": latest_followup.get("trade_date"),
        "latest_selected_count": latest_followup.get("selected_count"),
        "output_json": output_json_path.as_posix(),
    }


def refresh_btst_governance_validation_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    required_inputs = {
        "action_board": _resolve_existing_artifact_path(resolved_reports_root, ACTION_BOARD_JSON, glob_pattern="p3_top3_post_execution_action_board_*.json"),
        "rollout_governance": _resolve_existing_artifact_path(resolved_reports_root, ROLLOUT_GOVERNANCE_JSON, glob_pattern="p5_btst_rollout_governance_board_*.json"),
        "primary_window_gap": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_GAP_JSON, glob_pattern="p6_primary_window_gap_001309_*.json"),
        "recurring_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, RECURRING_SHADOW_RUNBOOK_JSON, glob_pattern="p6_recurring_shadow_runbook_*.json"),
        "primary_window_validation_runbook": _resolve_existing_artifact_path(resolved_reports_root, PRIMARY_WINDOW_VALIDATION_RUNBOOK_JSON, glob_pattern="p7_primary_window_validation_runbook_001309_*.json"),
        "structural_shadow_runbook": _resolve_existing_artifact_path(resolved_reports_root, STRUCTURAL_SHADOW_RUNBOOK_JSON, glob_pattern="p8_structural_shadow_runbook_300724_*.json"),
        "candidate_entry_governance": _resolve_existing_artifact_path(resolved_reports_root, CANDIDATE_ENTRY_ROLLOUT_GOVERNANCE_JSON, glob_pattern="p9_candidate_entry_rollout_governance_*.json"),
        "governance_synthesis": resolved_reports_root / BTST_GOVERNANCE_SYNTHESIS_JSON,
    }
    missing_inputs = [label for label, path in required_inputs.items() if not path.exists()]
    if missing_inputs:
        return {
            "status": "skipped_missing_inputs",
            "missing_inputs": missing_inputs,
        }

    output_json_path = resolved_reports_root / BTST_GOVERNANCE_VALIDATION_JSON
    output_md_path = resolved_reports_root / BTST_GOVERNANCE_VALIDATION_MD
    try:
        analysis = validate_btst_governance_consistency(
            action_board_path=required_inputs["action_board"],
            rollout_governance_path=required_inputs["rollout_governance"],
            primary_window_gap_path=required_inputs["primary_window_gap"],
            recurring_shadow_runbook_path=required_inputs["recurring_shadow_runbook"],
            primary_window_validation_runbook_path=required_inputs["primary_window_validation_runbook"],
            structural_shadow_runbook_path=required_inputs["structural_shadow_runbook"],
            candidate_entry_governance_path=required_inputs["candidate_entry_governance"],
            governance_synthesis_path=required_inputs["governance_synthesis"],
            nightly_control_tower_path=resolved_reports_root / "btst_nightly_control_tower_latest.json",
        )
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_governance_validation_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "missing_inputs": [],
            "error": str(exc),
        }

    return {
        "status": "refreshed",
        "missing_inputs": [],
        "overall_verdict": analysis.get("overall_verdict"),
        "pass_count": analysis.get("pass_count"),
        "warn_count": analysis.get("warn_count"),
        "fail_count": analysis.get("fail_count"),
        "output_json": output_json_path.as_posix(),
    }


def refresh_btst_replay_cohort_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    output_json_path = resolved_reports_root / BTST_REPLAY_COHORT_JSON
    output_md_path = resolved_reports_root / BTST_REPLAY_COHORT_MD
    try:
        analysis = analyze_btst_replay_cohort(resolved_reports_root)
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_replay_cohort_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "error": str(exc),
            "report_count": 0,
        }

    selection_target_counts = dict(analysis.get("selection_target_counts") or {})
    latest_short_trade = dict(analysis.get("latest_short_trade_row") or {})
    return {
        "status": "refreshed",
        "report_count": analysis.get("report_count"),
        "short_trade_only_report_count": selection_target_counts.get("short_trade_only"),
        "dual_target_report_count": selection_target_counts.get("dual_target"),
        "latest_short_trade_report": latest_short_trade.get("report_dir_name"),
        "output_json": output_json_path.as_posix(),
    }


def refresh_btst_independent_window_monitor_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    output_json_path = resolved_reports_root / BTST_INDEPENDENT_WINDOW_MONITOR_JSON
    output_md_path = resolved_reports_root / BTST_INDEPENDENT_WINDOW_MONITOR_MD
    try:
        analysis = analyze_btst_independent_window_monitor(resolved_reports_root)
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_independent_window_monitor_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "error": str(exc),
            "report_dir_count": 0,
        }

    return {
        "status": "refreshed",
        "report_dir_count": analysis.get("report_dir_count"),
        "ready_lane_count": analysis.get("ready_lane_count"),
        "waiting_lane_count": analysis.get("waiting_lane_count"),
        "no_evidence_lane_count": analysis.get("no_evidence_lane_count"),
        "output_json": output_json_path.as_posix(),
    }


def refresh_btst_tplus1_tplus2_objective_monitor_artifacts(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    output_json_path = resolved_reports_root / BTST_TPLUS1_TPLUS2_OBJECTIVE_MONITOR_JSON
    output_md_path = resolved_reports_root / BTST_TPLUS1_TPLUS2_OBJECTIVE_MONITOR_MD
    try:
        analysis = analyze_btst_tplus1_tplus2_objective_monitor(resolved_reports_root)
        output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_md_path.write_text(render_btst_tplus1_tplus2_objective_monitor_markdown(analysis), encoding="utf-8")
    except Exception as exc:
        return {
            "status": "skipped_refresh_error",
            "error": str(exc),
            "report_dir_count": 0,
        }

    tradeable_surface = dict(analysis.get("tradeable_surface") or {})
    ticker_leaderboard = list(analysis.get("ticker_leaderboard") or [])
    best_ticker_row = ticker_leaderboard[0] if ticker_leaderboard else {}
    return {
        "status": "refreshed",
        "report_dir_count": analysis.get("report_dir_count"),
        "closed_cycle_row_count": dict(analysis.get("all_surface") or {}).get("closed_cycle_count"),
        "tradeable_closed_cycle_count": tradeable_surface.get("closed_cycle_count"),
        "tradeable_positive_rate": tradeable_surface.get("t_plus_2_positive_rate"),
        "tradeable_return_hit_rate": tradeable_surface.get("t_plus_2_return_hit_rate_at_target"),
        "tradeable_mean_t_plus_2_return": tradeable_surface.get("mean_t_plus_2_return"),
        "tradeable_verdict": tradeable_surface.get("verdict"),
        "best_ticker": best_ticker_row.get("group_label"),
        "best_ticker_objective_fit_score": best_ticker_row.get("objective_fit_score"),
        "output_json": output_json_path.as_posix(),
    }


def generate_reports_manifest(
    reports_root: str | Path,
    *,
    latest_btst_run: dict[str, Any] | None = None,
    catalyst_theme_frontier_refresh: dict[str, Any] | None = None,
    btst_window_evidence_refresh: dict[str, Any] | None = None,
    candidate_entry_shadow_refresh: dict[str, Any] | None = None,
    btst_score_fail_frontier_refresh: dict[str, Any] | None = None,
    btst_rollout_governance_refresh: dict[str, Any] | None = None,
    btst_governance_synthesis_refresh: dict[str, Any] | None = None,
    btst_governance_validation_refresh: dict[str, Any] | None = None,
    btst_replay_cohort_refresh: dict[str, Any] | None = None,
    btst_independent_window_monitor_refresh: dict[str, Any] | None = None,
    btst_tplus1_tplus2_objective_monitor_refresh: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    repo_root = _resolve_repo_root(resolved_reports_root)
    latest_btst_run = latest_btst_run or _select_latest_btst_candidate(resolved_reports_root, repo_root)

    entries = _build_static_entries(repo_root) + _build_dynamic_latest_btst_entries(latest_btst_run, repo_root)
    entries.sort(key=lambda entry: (entry["usage"], entry["priority"], entry["view_order"], entry["id"]))

    entry_ids = {entry["id"] for entry in entries}
    reading_paths: list[dict[str, Any]] = []
    for spec in READING_PATH_SPECS:
        resolved_entry_ids = [entry_id for entry_id in spec["entry_ids"] if entry_id in entry_ids]
        if not resolved_entry_ids:
            continue
        reading_paths.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "description": spec["description"],
                "entry_ids": resolved_entry_ids,
            }
        )

    entry_count_by_usage: dict[str, int] = {}
    for entry in entries:
        entry_count_by_usage[entry["usage"]] = entry_count_by_usage.get(entry["usage"], 0) + 1

    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repo_root": repo_root.as_posix(),
        "reports_root": resolved_reports_root.as_posix(),
        "entry_count": len(entries),
        "entry_count_by_usage": entry_count_by_usage,
        "catalyst_theme_frontier_refresh": catalyst_theme_frontier_refresh,
        "btst_window_evidence_refresh": btst_window_evidence_refresh,
        "candidate_entry_shadow_refresh": candidate_entry_shadow_refresh,
        "btst_score_fail_frontier_refresh": btst_score_fail_frontier_refresh,
        "btst_rollout_governance_refresh": btst_rollout_governance_refresh,
        "btst_governance_synthesis_refresh": btst_governance_synthesis_refresh,
        "btst_governance_validation_refresh": btst_governance_validation_refresh,
        "btst_replay_cohort_refresh": btst_replay_cohort_refresh,
        "btst_independent_window_monitor_refresh": btst_independent_window_monitor_refresh,
        "btst_tplus1_tplus2_objective_monitor_refresh": btst_tplus1_tplus2_objective_monitor_refresh,
        "latest_btst_run": None,
        "reading_paths": reading_paths,
        "entries": entries,
    }
    if latest_btst_run:
        manifest["latest_btst_run"] = {
            "report_dir": latest_btst_run["report_dir_path"],
            "report_dir_abs": latest_btst_run["report_dir"].as_posix(),
            "selection_target": latest_btst_run.get("selection_target"),
            "trade_date": latest_btst_run.get("trade_date"),
            "next_trade_date": latest_btst_run.get("next_trade_date"),
        }
    return manifest


def _build_markdown_link(entry: dict[str, Any], output_parent: Path) -> str:
    relative_target = Path(os.path.relpath(entry["absolute_path"], output_parent)).as_posix()
    return f"[{entry['report_path']}]({relative_target})"


def render_reports_manifest_markdown(manifest: dict[str, Any], *, output_parent: str | Path) -> str:
    resolved_output_parent = Path(output_parent).expanduser().resolve()
    entries_by_id = {entry["id"]: entry for entry in list(manifest.get("entries") or [])}

    lines: list[str] = []
    lines.append("# Reports Manifest Latest")
    lines.append("")
    lines.append(f"- generated_at: {manifest['generated_at']}")
    lines.append(f"- entry_count: {manifest['entry_count']}")
    lines.append(f"- reports_root: {manifest['reports_root']}")
    catalyst_theme_frontier_refresh = manifest.get("catalyst_theme_frontier_refresh") or {}
    if catalyst_theme_frontier_refresh:
        lines.append(f"- catalyst_theme_frontier_refresh_status: {catalyst_theme_frontier_refresh.get('status')}")
        lines.append(f"- catalyst_theme_frontier_shadow_candidate_count: {catalyst_theme_frontier_refresh.get('shadow_candidate_count')}")
        lines.append(f"- catalyst_theme_frontier_promoted_shadow_count: {catalyst_theme_frontier_refresh.get('recommended_promoted_shadow_count')}")
        lines.append(f"- catalyst_theme_frontier_recommended_variant: {catalyst_theme_frontier_refresh.get('recommended_variant_name')}")
    btst_window_evidence_refresh = manifest.get("btst_window_evidence_refresh") or {}
    if btst_window_evidence_refresh:
        lines.append(f"- btst_window_evidence_refresh_status: {btst_window_evidence_refresh.get('status')}")
        lines.append(f"- btst_window_evidence_window_report_count: {btst_window_evidence_refresh.get('window_report_count')}")
        lines.append(f"- btst_window_evidence_candidate_count: {btst_window_evidence_refresh.get('candidate_count')}")
        lines.append(f"- btst_window_evidence_stable_candidate_count: {btst_window_evidence_refresh.get('stable_candidate_count')}")
        lines.append(f"- btst_window_evidence_primary_refresh_status: {btst_window_evidence_refresh.get('primary_refresh_status')}")
        lines.append(f"- btst_window_evidence_primary_missing_window_count: {btst_window_evidence_refresh.get('primary_missing_window_count')}")
    candidate_entry_shadow_refresh = manifest.get("candidate_entry_shadow_refresh") or {}
    if candidate_entry_shadow_refresh:
        lines.append(f"- candidate_entry_shadow_refresh_status: {candidate_entry_shadow_refresh.get('status')}")
        lines.append(f"- candidate_entry_shadow_refresh_window_reports: {candidate_entry_shadow_refresh.get('window_report_count')}")
        lines.append(f"- candidate_entry_shadow_refresh_filtered_reports: {candidate_entry_shadow_refresh.get('filtered_report_count')}")
        lines.append(f"- candidate_entry_shadow_refresh_rollout_readiness: {candidate_entry_shadow_refresh.get('rollout_readiness')}")
    btst_score_fail_frontier_refresh = manifest.get("btst_score_fail_frontier_refresh") or {}
    if btst_score_fail_frontier_refresh:
        lines.append(f"- btst_score_fail_frontier_refresh_status: {btst_score_fail_frontier_refresh.get('status')}")
        lines.append(f"- btst_score_fail_frontier_rejected_case_count: {btst_score_fail_frontier_refresh.get('rejected_short_trade_boundary_count')}")
        lines.append(f"- btst_score_fail_frontier_rescueable_case_count: {btst_score_fail_frontier_refresh.get('rescueable_case_count')}")
        lines.append(f"- btst_score_fail_frontier_recurring_case_count: {btst_score_fail_frontier_refresh.get('recurring_case_count')}")
        lines.append(f"- btst_score_fail_frontier_transition_refresh_status: {btst_score_fail_frontier_refresh.get('transition_refresh_status')}")
        lines.append(f"- btst_score_fail_frontier_recurring_shadow_refresh_status: {btst_score_fail_frontier_refresh.get('recurring_shadow_refresh_status')}")
    btst_rollout_governance_refresh = manifest.get("btst_rollout_governance_refresh") or {}
    if btst_rollout_governance_refresh:
        lines.append(f"- btst_rollout_governance_refresh_status: {btst_rollout_governance_refresh.get('status')}")
        lines.append(f"- btst_rollout_governance_row_count: {btst_rollout_governance_refresh.get('governance_row_count')}")
        lines.append(f"- btst_rollout_governance_penalty_status: {btst_rollout_governance_refresh.get('penalty_frontier_status')}")
    btst_governance_synthesis_refresh = manifest.get("btst_governance_synthesis_refresh") or {}
    if btst_governance_synthesis_refresh:
        lines.append(f"- btst_governance_synthesis_status: {btst_governance_synthesis_refresh.get('status')}")
        lines.append(f"- btst_governance_synthesis_waiting_lane_count: {btst_governance_synthesis_refresh.get('waiting_lane_count')}")
        lines.append(f"- btst_governance_synthesis_ready_lane_count: {btst_governance_synthesis_refresh.get('ready_lane_count')}")
    btst_governance_validation_refresh = manifest.get("btst_governance_validation_refresh") or {}
    if btst_governance_validation_refresh:
        lines.append(f"- btst_governance_validation_status: {btst_governance_validation_refresh.get('status')}")
        lines.append(f"- btst_governance_validation_overall_verdict: {btst_governance_validation_refresh.get('overall_verdict')}")
    btst_replay_cohort_refresh = manifest.get("btst_replay_cohort_refresh") or {}
    if btst_replay_cohort_refresh:
        lines.append(f"- btst_replay_cohort_status: {btst_replay_cohort_refresh.get('status')}")
        lines.append(f"- btst_replay_cohort_report_count: {btst_replay_cohort_refresh.get('report_count')}")
        lines.append(f"- btst_replay_cohort_short_trade_only_report_count: {btst_replay_cohort_refresh.get('short_trade_only_report_count')}")
    btst_independent_window_monitor_refresh = manifest.get("btst_independent_window_monitor_refresh") or {}
    if btst_independent_window_monitor_refresh:
        lines.append(f"- btst_independent_window_monitor_status: {btst_independent_window_monitor_refresh.get('status')}")
        lines.append(f"- btst_independent_window_monitor_report_dir_count: {btst_independent_window_monitor_refresh.get('report_dir_count')}")
        lines.append(f"- btst_independent_window_monitor_ready_lane_count: {btst_independent_window_monitor_refresh.get('ready_lane_count')}")
        lines.append(f"- btst_independent_window_monitor_waiting_lane_count: {btst_independent_window_monitor_refresh.get('waiting_lane_count')}")
    btst_tplus1_tplus2_objective_monitor_refresh = manifest.get("btst_tplus1_tplus2_objective_monitor_refresh") or {}
    if btst_tplus1_tplus2_objective_monitor_refresh:
        lines.append(f"- btst_tplus1_tplus2_objective_monitor_status: {btst_tplus1_tplus2_objective_monitor_refresh.get('status')}")
        lines.append(f"- btst_tplus1_tplus2_objective_monitor_report_dir_count: {btst_tplus1_tplus2_objective_monitor_refresh.get('report_dir_count')}")
        lines.append(f"- btst_tplus1_tplus2_objective_monitor_tradeable_closed_cycle_count: {btst_tplus1_tplus2_objective_monitor_refresh.get('tradeable_closed_cycle_count')}")
        lines.append(f"- btst_tplus1_tplus2_objective_monitor_tradeable_positive_rate: {btst_tplus1_tplus2_objective_monitor_refresh.get('tradeable_positive_rate')}")
        lines.append(f"- btst_tplus1_tplus2_objective_monitor_tradeable_return_hit_rate: {btst_tplus1_tplus2_objective_monitor_refresh.get('tradeable_return_hit_rate')}")
        lines.append(f"- btst_tplus1_tplus2_objective_monitor_best_ticker: {btst_tplus1_tplus2_objective_monitor_refresh.get('best_ticker')}")
    latest_btst_run = manifest.get("latest_btst_run") or {}
    if latest_btst_run:
        lines.append(f"- latest_btst_report_dir: {latest_btst_run['report_dir']}")
        lines.append(f"- latest_btst_trade_date: {latest_btst_run.get('trade_date')}")
        lines.append(f"- latest_btst_next_trade_date: {latest_btst_run.get('next_trade_date')}")
        lines.append(f"- latest_btst_selection_target: {latest_btst_run.get('selection_target')}")
    lines.append("")

    for reading_path in list(manifest.get("reading_paths") or []):
        lines.append(f"## {reading_path['title']}")
        lines.append("")
        lines.append(reading_path["description"])
        lines.append("")
        for index, entry_id in enumerate(list(reading_path.get("entry_ids") or []), start=1):
            entry = entries_by_id[entry_id]
            lines.append(f"{index}. {_build_markdown_link(entry, resolved_output_parent)}")
            lines.append(f"   用途：{entry['question']}")
            lines.append(f"   类型：{entry['report_type']} | usage={entry['usage']} | priority={entry['priority']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_reports_manifest_artifacts(
    reports_root: str | Path,
    *,
    output_json: str | Path | None = None,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_output_json = Path(output_json).expanduser().resolve() if output_json else (resolved_reports_root / DEFAULT_OUTPUT_JSON.name).resolve()
    resolved_output_md = Path(output_md).expanduser().resolve() if output_md else (resolved_reports_root / DEFAULT_OUTPUT_MD.name).resolve()
    repo_root = _resolve_repo_root(resolved_reports_root)
    latest_btst_run = _select_latest_btst_candidate(resolved_reports_root, repo_root)
    catalyst_theme_frontier_refresh = refresh_latest_btst_catalyst_theme_frontier_artifacts(latest_btst_run)
    if latest_btst_run:
        latest_btst_run = _extract_btst_candidate(latest_btst_run["report_dir"], repo_root)
    btst_window_evidence_refresh = refresh_btst_window_evidence_artifacts(resolved_reports_root)
    btst_independent_window_monitor_refresh = refresh_btst_independent_window_monitor_artifacts(resolved_reports_root)
    btst_tplus1_tplus2_objective_monitor_refresh = refresh_btst_tplus1_tplus2_objective_monitor_artifacts(resolved_reports_root)
    candidate_entry_shadow_refresh = refresh_btst_candidate_entry_shadow_lane_artifacts(resolved_reports_root)
    btst_score_fail_frontier_refresh = refresh_btst_score_fail_frontier_artifacts(
        resolved_reports_root,
        latest_btst_run=latest_btst_run,
        window_evidence_refresh=btst_window_evidence_refresh,
    )
    btst_rollout_governance_refresh = refresh_btst_rollout_governance_artifacts(resolved_reports_root)
    btst_governance_synthesis_refresh = refresh_btst_governance_synthesis_artifacts(
        resolved_reports_root,
        latest_btst_run=latest_btst_run,
    )
    btst_governance_validation_refresh = refresh_btst_governance_validation_artifacts(resolved_reports_root)
    btst_replay_cohort_refresh = refresh_btst_replay_cohort_artifacts(resolved_reports_root)
    manifest = generate_reports_manifest(
        resolved_reports_root,
        latest_btst_run=latest_btst_run,
        catalyst_theme_frontier_refresh=catalyst_theme_frontier_refresh,
        btst_window_evidence_refresh=btst_window_evidence_refresh,
        candidate_entry_shadow_refresh=candidate_entry_shadow_refresh,
        btst_score_fail_frontier_refresh=btst_score_fail_frontier_refresh,
        btst_rollout_governance_refresh=btst_rollout_governance_refresh,
        btst_governance_synthesis_refresh=btst_governance_synthesis_refresh,
        btst_governance_validation_refresh=btst_governance_validation_refresh,
        btst_replay_cohort_refresh=btst_replay_cohort_refresh,
        btst_independent_window_monitor_refresh=btst_independent_window_monitor_refresh,
        btst_tplus1_tplus2_objective_monitor_refresh=btst_tplus1_tplus2_objective_monitor_refresh,
    )
    resolved_output_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resolved_output_md.write_text(render_reports_manifest_markdown(manifest, output_parent=resolved_output_md.parent), encoding="utf-8")
    return {
        "manifest": manifest,
        "catalyst_theme_frontier_refresh": catalyst_theme_frontier_refresh,
        "btst_window_evidence_refresh": btst_window_evidence_refresh,
        "candidate_entry_shadow_refresh": candidate_entry_shadow_refresh,
        "btst_score_fail_frontier_refresh": btst_score_fail_frontier_refresh,
        "btst_rollout_governance_refresh": btst_rollout_governance_refresh,
        "btst_governance_synthesis_refresh": btst_governance_synthesis_refresh,
        "btst_governance_validation_refresh": btst_governance_validation_refresh,
        "btst_replay_cohort_refresh": btst_replay_cohort_refresh,
        "btst_independent_window_monitor_refresh": btst_independent_window_monitor_refresh,
        "btst_tplus1_tplus2_objective_monitor_refresh": btst_tplus1_tplus2_objective_monitor_refresh,
        "json_path": resolved_output_json.as_posix(),
        "markdown_path": resolved_output_md.as_posix(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a machine-readable manifest for frequently reviewed reports under data/reports.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR), help="Reports root directory to scan")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON manifest path")
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD), help="Output Markdown manifest path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = generate_reports_manifest_artifacts(
        reports_root=args.reports_root,
        output_json=args.output_json,
        output_md=args.output_md,
    )
    print(f"report_manifest_json={result['json_path']}")
    print(f"report_manifest_markdown={result['markdown_path']}")


if __name__ == "__main__":
    main()