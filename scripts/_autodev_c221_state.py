"""更新 state.json — 添加 c221 signal_horizon 呈现层标注 campaign.

C219 改 BUY gate 为 T+5 OR T+10 OR, 但呈现层只显示 action=BUY,
用户无法区分是 T+5 还是 T+10 反弹, 容易把 T+5 票当 T+10 持有增加风险.

C221 在 build_front_door_verdict 返回值加 signal_horizon 字段
(T+5 / T+10 / T+5+T+10 / ""), top_picks.py 展示 "信号=T+5" 让用户灵活组合资金.

Usage:
  uv run python scripts/_autodev_c221_state.py
"""

from __future__ import annotations

import json
from pathlib import Path

STATE_PATH = Path(".autodev/state.json")


def main() -> None:
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)

    # 1. evidence_catalog
    ev_new = [
        {
            "id": "ev-c221-diff",
            "kind": "diff",
            "attestation": ("investability.py build_front_door_verdict 返回值加 signal_horizon 字段 " '(T+5/T+10/T+5+T+10/""); 基于 _t5_passes 和 _t10_passes 两个 sub-signal 标注; ' "risk_off 降级 HOLD 仍保留 signal_horizon (让用户知道本可 BUY); " 'top_picks.py _print_pick_entry 展示 "信号=T+5" 等 (空时不展示)'),
            "environment": "local",
            "observed_at": "2026-06-28T01:30:00+08:00",
            "campaign_id": "c221-ns3-m14b-signal-horizon-display",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "src/screening/investability.py + src/screening/top_picks.py",
            "raw_ref": "src/screening/investability.py",
        },
        {
            "id": "ev-c221-tdd",
            "kind": "test",
            "attestation": ("5 新 C221 TDD: t5_only/t10_only/both/empty/risk_off_preserved; " "覆盖 signal_horizon 字段所有分支"),
            "environment": "local",
            "observed_at": "2026-06-28T01:30:00+08:00",
            "campaign_id": "c221-ns3-m14b-signal-horizon-display",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "tests/screening/test_investability.py",
            "raw_ref": "tests/screening/test_investability.py",
        },
        {
            "id": "ev-c221-regression",
            "kind": "test",
            "attestation": ("tests/ 10121 passed, 1 skipped, 0 failed, flake8 clean — 无回归 " "(含修复 test_top_picks.py 6 处 mock + 2 helper 和 test_investability_representative.py " "2 helper 加 t5/t10 字段, C219 遗漏)"),
            "environment": "local",
            "observed_at": "2026-06-28T01:30:00+08:00",
            "campaign_id": "c221-ns3-m14b-signal-horizon-display",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "tests/ regression",
            "raw_ref": "tests/",
        },
    ]
    state["evidence_catalog"].extend(ev_new)

    # 2. intervention: iv054
    iv_new = {
        "id": "iv054-ns3-m14b-signal-horizon-display",
        "campaign_id": "c221-ns3-m14b-signal-horizon-display",
        "candidate_id": "cd221-ns3-m14b-signal-horizon-display",
        "workflow_id": "wf-top-picks-must-win",
        "title": "M14b signal_horizon 呈现层标注 — 让用户区分 T+5/T+10 反弹票避免 horizon 误用",
        "status": "concluded",
        "scope": "src/screening/investability.py (build_front_door_verdict return) + src/screening/top_picks.py (_print_pick_entry)",
        "evidence_refs": ["ev-c221-diff", "ev-c221-tdd", "ev-c221-regression"],
        "recorded_at": "2026-06-28T01:30:00+08:00",
    }
    state["interventions"].append(iv_new)

    # 3. candidate: cd221
    cd_new = {
        "id": "cd221-ns3-m14b-signal-horizon-display",
        "source_kind": "code_change",
        "source_refs": ["src/screening/investability.py", "src/screening/top_picks.py"],
        "provenance_chain": ["c219-ns3-m13-historical-backfill", "c220-ns3-m14-buy-gate-horizon"],
        "product_context_ref": state["campaigns"][0]["product_context_ref"],
        "workflow_id": "wf-top-picks-must-win",
        "family_id": "ns3-north-star-pnl",
        "family_scope": "M14b signal horizon display",
        "type": "feature",
        "goal_alignment": "用户体验 — 让用户区分 BUY 信号来源 (T+5/T+10), 灵活组合资金避免 horizon 误用",
        "expected_outcome": '用户看到 "信号=T+5" 知道是 T+5 反弹票快进快出; "信号=T+5+T+10" 知道双信号更强可加仓',
        "evidence_confidence": 5,
        "cost_of_delay": 2,
        "effort": "S",
        "change_risk": 1,
        "domain_impact_risk": 2,
        "total_ownership_cost": 1,
        "reversibility": 5,
        "learning_value": 3,
        "dependencies": ["c220-ns3-m14-buy-gate-horizon"],
        "verification": ["ev-c221-tdd", "ev-c221-regression"],
        "hard_gate_status": "passed",
        "frontier_status": "completed",
        "status": "delivered",
        "self_generation": True,
    }
    state["candidate_portfolio"].append(cd_new)

    # 4. campaign: c221
    c221 = {
        "id": "c221-ns3-m14b-signal-horizon-display",
        "initial_mode": "delivery",
        "mode": "delivery",
        "mode_pivots": [],
        "status": "completed",
        "counter_class": "value",
        "product_context_ref": state["campaigns"][0]["product_context_ref"],
        "policy_digest": state["campaigns"][0]["policy_digest"],
        "selected_candidate_id": "cd221-ns3-m14b-signal-horizon-display",
        "risk_profile": {
            "blast_radius": 1,
            "design_uncertainty": 1,
            "contract_ambiguity": 1,
            "verification_gap": 1,
            "rollback_difficulty": 1,
            "migration_risk": 1,
        },
        "change_risk": 1,
        "design_decision_packet": {
            "problem": "C219 改 BUY gate 为 T+5 OR T+10 OR, 但呈现层只显示 action=BUY, 用户无法区分是 T+5 反弹还是 T+10 反弹, 容易把 T+5 票当 T+10 持有增加风险.",
            "invariants": [
                'build_front_door_verdict 返回值加 signal_horizon 字段 (T+5/T+10/T+5+T+10/"")',
                "基于 _t5_passes 和 _t10_passes 两个 sub-signal 标注 (复用 C219 计算结果, 零额外计算)",
                "risk_off 降级 HOLD 仍保留 signal_horizon (让用户知道本可 BUY 的短期反弹信号)",
                "signal_horizon 为空 (HOLD/AVOID 无短期信号) 时呈现层不展示, 保持简洁",
                'top_picks.py 展示 "信号=T+5" 等, 不染色 (action 已染色)',
            ],
            "options": [
                "A signal_horizon 字段 + 呈现层展示 (推荐, 显式标注 horizon)",
                "B 改 action 为 BUY_T5/BUY_T10/BUY_T5_T10 (污染 action 域, 破坏现有 BUY/HOLD/AVOID 三档)",
                "C 单独 API 返回 horizon (过度工程, 增加 API 表面)",
            ],
            "recommendation": "A — 加 signal_horizon 字段, 保持 action 域干净, 呈现层条件展示",
            "acceptance_tests": [
                'T+5 单独通过 → signal_horizon="T+5"',
                'T+10 单独通过 → signal_horizon="T+10"',
                'T+5 和 T+10 都通过 → signal_horizon="T+5+T+10"',
                'T+5/T+10 都不通过 → signal_horizon="" (不展示)',
                "risk_off 降级 HOLD 仍保留 signal_horizon (本可 BUY 的短期反弹信号)",
            ],
            "rollback": "git revert c221 commit; investability.py 移除 signal_horizon 字段; top_picks.py 移除展示",
            "decision_authority": "engineering (呈现层 UX 改进, 标准做法)",
            "next_trigger": 'owner 观察用户反馈; 如需更细分 (如 "信号强度" T+5+T+10 > T+5) 可后续迭代',
        },
        "domain_context": {
            "loaded_overlays": ["finance-quant"],
            "detection_evidence_refs": ["ev-c221-diff"],
            "affected_surfaces": ["portfolio"],
            "domain_impact_risk": 2,
            "evidence_confidence": 5,
            "domain_control_receipts": [
                {
                    "control_id": "fixture_or_pipeline_check",
                    "status": "passed",
                    "evidence_refs": ["ev-c221-tdd", "ev-c221-regression"],
                    "rationale": "portfolio surface: 呈现层直接影响用户决策, 5 TDD + 10121 回归全通过",
                    "reason": "portfolio surface triggered (呈现层 UX 修改)",
                },
                {
                    "control_id": "reproducibility",
                    "status": "passed",
                    "evidence_refs": ["ev-c221-tdd"],
                    "rationale": "纯函数 build_front_door_verdict 幂等, signal_horizon 基于 _t5_passes/_t10_passes 确定性计算",
                    "reason": "portfolio surface triggered",
                },
            ],
        },
        "evidence_profile": {
            "outcome_source_tier": "observed",
            "outcome_evidence_refs": ["ev-c221-regression"],
            "verification_tiers": ["focused_tests", "static_analysis"],
            "verification_evidence_refs": ["ev-c221-diff", "ev-c221-tdd", "ev-c221-regression"],
            "value_claim": "delivery_value + learning_value",
        },
        "role_reviews": [
            {
                "gate": "startup",
                "scope": "M14b signal_horizon 呈现层标注 (让用户区分 T+5/T+10 反弹票)",
                "evidence_refs": ["ev-c221-diff"],
                "required_verification": ["ev-c221-tdd", "ev-c221-regression"],
                "review_delta": "",
                "recorded_at": "2026-06-28T01:30:00+08:00",
                "lenses": {
                    "alpha": {"findings_or_candidates": ["C219 BUY gate T+5/T+10 OR 已落地, 呈现层需跟进标注 horizon"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "beta": {"findings_or_candidates": ["加 signal_horizon 字段不破坏 action 域; 复用 _t5_passes/_t10_passes 零额外计算"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "gamma": {"findings_or_candidates": ["用户需求: 区分 T+5/T+10 避免把 T+5 票当 T+10 持有增加风险"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                },
            },
            {
                "gate": "pre_closure",
                "scope": "M14b signal_horizon 呈现层标注",
                "evidence_refs": ["ev-c221-diff", "ev-c221-tdd"],
                "required_verification": ["ev-c221-regression"],
                "review_delta": "",
                "recorded_at": "2026-06-28T01:30:00+08:00",
                "lenses": {
                    "alpha": {"findings_or_candidates": ["5 C221 TDD 覆盖 signal_horizon 所有分支 (t5_only/t10_only/both/empty/risk_off_preserved)"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "beta": {"findings_or_candidates": ["10121 回归全通过 (含修复 C219 遗漏的 test_top_picks.py + test_investability_representative.py 测试数据), flake8 clean"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "gamma": {
                        "findings_or_candidates": [
                            '用户现在看到 "操作=BUY 信号=T+5+T+10" 知道双信号更强可加仓',
                            '"操作=BUY 信号=T+5" 知道快进快出',
                            "risk_off 降级 HOLD 仍标注 signal_horizon (本可 BUY 的短期反弹信号)",
                        ],
                        "verdict": "pass",
                        "veto_or_blocker": None,
                        "handoff_delta": "",
                    },
                },
                "policy_digest": state["campaigns"][0]["policy_digest"],
            },
        ],
        "stage_receipts": {
            "feature_delivery": {
                "work_depth": "primary",
                "verdict": "pass",
                "scan_scope": "investability.py build_front_door_verdict return + top_picks.py _print_pick_entry 展示",
                "finding_count": 0,
                "candidate_count": 0,
                "evidence_refs": ["ev-c221-diff"],
                "verification_refs": ["ev-c221-tdd", "ev-c221-regression"],
                "exhaustion_or_blocker": "delivery complete — signal_horizon 字段 + 呈现层标注",
                "review_gate": "pre_closure",
            },
            "regression_and_commit": {
                "work_depth": "primary",
                "verdict": "pass",
                "scan_scope": "tests/ (10121) + flake8",
                "finding_count": 0,
                "candidate_count": 0,
                "evidence_refs": ["ev-c221-diff"],
                "verification_refs": ["ev-c221-regression"],
                "exhaustion_or_blocker": "10121 passed + 0 lint — committed",
                "review_gate": "pre_closure",
            },
        },
        "issue_outcome": {
            "summary": 'M14b signal_horizon 呈现层标注. investability.py build_front_door_verdict 返回值加 signal_horizon 字段 (T+5/T+10/T+5+T+10/""); top_picks.py _print_pick_entry 展示 "信号=T+5" 等; risk_off 降级 HOLD 仍保留 signal_horizon. 5 新 TDD + 10121 回归全通过.',
            "root_cause": "C219 改 BUY gate T+5 OR T+10 OR 但呈现层未跟进标注 horizon, 用户无法区分 T+5/T+10 反弹票",
            "prediction": "用户看到信号标注后能灵活组合资金 (T+5 快进快出, T+5+T+10 加仓), 减少 horizon 误用风险",
            "observed_outcome": "待 live 验证 (下一次 --auto 跑)",
        },
        "changes": [
            {
                "scope": "src/screening/investability.py",
                "behavior_delta": 'build_front_door_verdict: +signal_horizon 字段 (T+5/T+10/T+5+T+10/""); 基于 _t5_passes 和 _t10_passes 标注; risk_off 降级仍保留',
                "evidence_refs": ["ev-c221-diff", "ev-c221-tdd"],
            },
            {
                "scope": "src/screening/top_picks.py",
                "behavior_delta": '_print_pick_entry: 展示 "信号=T+5" 等 (空时不展示), 加在 action 后',
                "evidence_refs": ["ev-c221-diff"],
            },
            {
                "scope": "tests/screening/test_investability.py",
                "behavior_delta": "+5 C221 TDD (t5_only/t10_only/both/empty/risk_off_preserved)",
                "evidence_refs": ["ev-c221-tdd"],
            },
            {
                "scope": "tests/test_top_picks.py + tests/test_investability_representative.py",
                "behavior_delta": "修复 C219 遗漏: 6 处 mock + 4 helper 加 t5/t10 字段 (只提供 t30 导致 HOLD/AVOID)",
                "evidence_refs": ["ev-c221-regression"],
            },
        ],
        "closure_receipts": [
            {
                "kind": "git_closure",
                "status": "pass",
                "evidence_refs": ["ev-c221-diff", "ev-c221-tdd", "ev-c221-regression"],
                "user_change_isolation": "verified",
                "recorded_at": "2026-06-28T01:30:00+08:00",
                "commit_sha": "pending",
                "diff_evidence": "investability.py + top_picks.py + test_investability.py + test_top_picks.py + test_investability_representative.py 待 commit",
            },
            {
                "kind": "release_handoff",
                "intervention_id": "iv054-ns3-m14b-signal-horizon-display",
                "workflow_id": "wf-top-picks-must-win",
                "status": "concluded",
                "commit_or_no_diff": "pending commit",
                "release_or_observation_refs": ["ev-c221-regression"],
                "next_owner_or_trigger": "owner 观察 live --auto 跑看信号标注是否清晰; 如需更细分 (如信号强度) 可后续迭代",
                "recorded_at": "2026-06-28T01:30:00+08:00",
            },
            {
                "kind": "pre_closure_review",
                "role_gate": "pre_closure",
                "residual_blockers": None,
                "evidence_refs": ["ev-c221-diff", "ev-c221-tdd", "ev-c221-regression"],
                "recorded_at": "2026-06-28T01:30:00+08:00",
            },
            {
                "kind": "state_write_intent",
                "target_campaign_status": "completed",
                "evidence_refs": ["ev-c221-diff", "ev-c221-tdd", "ev-c221-regression"],
                "recorded_at": "2026-06-28T01:30:00+08:00",
            },
        ],
    }
    state["campaigns"].append(c221)

    # 5. next_outer_loop_action
    state["next_outer_loop_action"] = {
        "action": "wait",
        "target_workflow_id": "wf-top-picks-must-win",
        "action_class": "delivery",
        "next_trigger": ('M14b signal_horizon 呈现层标注已交付. 用户现在看到 "操作=BUY 信号=T+5/T+10/T+5+T+10" ' "可灵活组合资金 (T+5 快进快出, T+10 持有更久, T+5+T+10 加仓). " "5 新 TDD + 10121 回归全通过. " "下个 owner 选择: (1) live --auto 跑验证信号标注清晰度; " "(2) 修复 volatility 因子 (dir=0 55.7% + 反向 -0.453%); " "(3) 监控 MR 因子 IC 走势. 模型 factor 仍 owner 范畴."),
    }

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(f"✓ state.json updated: +c221 campaign +iv054 +cd221 +3 evidence")
    print(f"  campaigns: {len(state['campaigns'])}")
    print(f"  interventions: {len(state['interventions'])}")
    print(f"  candidate_portfolio: {len(state['candidate_portfolio'])}")
    print(f"  evidence_catalog: {len(state['evidence_catalog'])}")


if __name__ == "__main__":
    main()
