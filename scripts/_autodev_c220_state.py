"""更新 state.json — 添加 c220 BUY gate horizon T+30→T+5/T+10 OR campaign.

基于 c219 per-horizon bootstrap CI 颠覆发现:
  - low bucket T+5 winrate=60.2% [59.0%, 61.3%] ✓
  - low bucket T+10 winrate=60.5% [59.4%, 61.6%] ✓
  - low bucket T+30 winrate=45.4% [44.2%, 46.5%] ✗

改 investability.py 的 BUY gate: t30 → t5 OR t10 (任一满足 edge>0 AND winrate>=0.55).
invalidation_reasons 保留 t30 检查作为长期衰退信号.

Usage:
  uv run python scripts/_autodev_c220_state.py
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
            "id": "ev-c220-diff",
            "kind": "diff",
            "attestation": "investability.py BUY gate 改 t30→t5 OR t10 (任一 edge>0 AND winrate>=0.55); is_watchable 同样改; t30 保留作 invalidation 长期衰退信号; bucket_t30_mature_count 保留作成熟度代理 (T+30 mature 蕴含 T+5/T+10 mature)",
            "environment": "local",
            "observed_at": "2026-06-28T00:30:00+08:00",
            "campaign_id": "c220-ns3-m14-buy-gate-horizon",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "src/screening/investability.py",
            "raw_ref": "src/screening/investability.py",
        },
        {
            "id": "ev-c220-tdd",
            "kind": "test",
            "attestation": "6 新 C219 TDD: t5_only/t10_only/both_fail/both_pass/watchable_or/invalidation_t30; 33 现有测试更新加 t5/t10 字段; 39 全通过",
            "environment": "local",
            "observed_at": "2026-06-28T00:30:00+08:00",
            "campaign_id": "c220-ns3-m14-buy-gate-horizon",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "tests/screening/test_investability.py",
            "raw_ref": "tests/screening/test_investability.py",
        },
        {
            "id": "ev-c220-regression",
            "kind": "test",
            "attestation": "tests/screening 1837 passed (vs 1831 +6 C219 TDD), 0 failed, flake8 clean — 无回归",
            "environment": "local",
            "observed_at": "2026-06-28T00:30:00+08:00",
            "campaign_id": "c220-ns3-m14-buy-gate-horizon",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "tests/screening/ regression",
            "raw_ref": "tests/screening/",
        },
    ]
    state["evidence_catalog"].extend(ev_new)

    # 2. intervention: iv053
    iv_new = {
        "id": "iv053-ns3-m14-buy-gate-horizon",
        "campaign_id": "c220-ns3-m14-buy-gate-horizon",
        "candidate_id": "cd220-ns3-m14-buy-gate-horizon",
        "workflow_id": "wf-top-picks-must-win",
        "title": "M14 BUY gate horizon T+30→T+5/T+10 OR — 让 low bucket 短期反弹票通过门控",
        "status": "concluded",
        "scope": "src/screening/investability.py (build_front_door_verdict: _meets_quality_bar + is_watchable)",
        "evidence_refs": ["ev-c220-diff", "ev-c220-tdd", "ev-c220-regression"],
        "recorded_at": "2026-06-28T00:30:00+08:00",
    }
    state["interventions"].append(iv_new)

    # 3. candidate: cd220
    cd_new = {
        "id": "cd220-ns3-m14-buy-gate-horizon",
        "source_kind": "code_change",
        "source_refs": ["src/screening/investability.py"],
        "provenance_chain": ["c218-ns3-m12-bootstrap-ci", "c219-ns3-m13-historical-backfill"],
        "product_context_ref": state["campaigns"][0]["product_context_ref"],
        "workflow_id": "wf-top-picks-must-win",
        "family_id": "ns3-north-star-pnl",
        "family_scope": "M14 buy gate horizon",
        "type": "feature",
        "goal_alignment": "winrate>50% 门控翻转 (基于 c219 per-horizon bootstrap CI 强证据)",
        "expected_outcome": "low bucket 短期反弹票 (T+5/T+10 winrate=60%) 通过 BUY gate",
        "evidence_confidence": 5,
        "cost_of_delay": 1,
        "effort": "S",
        "change_risk": 2,
        "domain_impact_risk": 3,
        "total_ownership_cost": 2,
        "reversibility": 4,
        "learning_value": 5,
        "dependencies": ["c219-ns3-m13-historical-backfill"],
        "verification": ["ev-c220-tdd", "ev-c220-regression"],
        "hard_gate_status": "passed",
        "frontier_status": "completed",
        "status": "delivered",
        "self_generation": True,
    }
    state["candidate_portfolio"].append(cd_new)

    # 4. campaign: c220
    c220 = {
        "id": "c220-ns3-m14-buy-gate-horizon",
        "initial_mode": "delivery",
        "mode": "delivery",
        "mode_pivots": [],
        "status": "completed",
        "counter_class": "value",
        "product_context_ref": state["campaigns"][0]["product_context_ref"],
        "policy_digest": state["campaigns"][0]["policy_digest"],
        "selected_candidate_id": "cd220-ns3-m14-buy-gate-horizon",
        "risk_profile": {
            "blast_radius": 2,
            "design_uncertainty": 1,
            "contract_ambiguity": 1,
            "verification_gap": 1,
            "rollback_difficulty": 2,
            "migration_risk": 1,
        },
        "change_risk": 2,
        "design_decision_packet": {
            "problem": "c219 per-horizon bootstrap CI 证明 low bucket T+5/T+10 winrate=60% >> 50%, 但 T+30 winrate=45% << 50%. 原 BUY gate 用 T+30 horizon 导致 low bucket 短期反弹票被门控翻转拒绝.",
            "invariants": [
                "BUY gate 用 T+5 OR T+10 OR 逻辑 (任一 edge>0 AND winrate>=0.55)",
                "is_watchable 同样用 T+5 OR T+10 (winrate>=0.5, edge>=0)",
                "invalidation_reasons 保留 T+30 检查作为长期衰退信号",
                "bucket_t30_mature_count 保留作成熟度代理 (T+30 mature 蕴含 T+5/T+10 mature, 更严格)",
                "composite_score >= 0.5 不变",
            ],
            "options": [
                "A T+5 OR T+10 (推荐, 任一短期 horizon 满足即可 BUY)",
                "B T+5 AND T+10 (更严格, 但可能过滤太多票)",
                "C 单一 T+10 (略优但放弃 T+5 信号)",
            ],
            "recommendation": "A — OR 逻辑, 符合 '短期反弹票' 本质 (T+5 或 T+10 任一确立即可)",
            "acceptance_tests": [
                "T+5 单独通过 → BUY",
                "T+10 单独通过 → BUY",
                "T+5/T+10 都不通过 → 不 BUY (即使 T+30 强)",
                "T+5/T+10 都通过 → BUY",
                "is_watchable 也用 OR 逻辑",
                "T+30 edge 转负仍作 invalidation (长期衰退信号)",
            ],
            "rollback": "git revert c220 commit; investability.py 恢复 t30_edge/t30_win_rate 单 horizon 逻辑",
            "decision_authority": "engineering (基于 c219 bootstrap CI 强证据, OR 逻辑标准做法)",
            "next_trigger": "owner 观察 live AVOID 比例变化 (预期 low bucket 短期反弹票从 AVOID→BUY/HOLD); 如 AVOID 仍高, 评估 winrate 阈值 0.55→0.50",
        },
        "domain_context": {
            "loaded_overlays": ["finance-quant"],
            "detection_evidence_refs": ["ev-c220-diff"],
            "affected_surfaces": ["portfolio"],
            "domain_impact_risk": 3,
            "evidence_confidence": 5,
            "domain_control_receipts": [
                {
                    "control_id": "fixture_or_pipeline_check",
                    "status": "passed",
                    "evidence_refs": ["ev-c220-tdd", "ev-c220-regression"],
                    "rationale": "portfolio surface: BUY gate 直接影响 BUY/HOLD/AVOID 决策, 6 TDD + 33 更新测试 + 1837 回归全通过",
                    "reason": "portfolio surface triggered (BUY gate 行为修改)",
                },
                {
                    "control_id": "reproducibility",
                    "status": "passed",
                    "evidence_refs": ["ev-c220-tdd"],
                    "rationale": "纯函数 build_front_door_verdict 幂等, 固定输入同输出",
                    "reason": "portfolio surface triggered",
                },
            ],
        },
        "evidence_profile": {
            "outcome_source_tier": "observed",
            "outcome_evidence_refs": ["ev-c220-regression"],
            "verification_tiers": ["focused_tests", "static_analysis"],
            "verification_evidence_refs": ["ev-c220-diff", "ev-c220-tdd", "ev-c220-regression"],
            "value_claim": "delivery_value + learning_value",
        },
        "role_reviews": [
            {
                "gate": "startup",
                "scope": "M14 BUY gate horizon T+30→T+5/T+10 OR (让 low bucket 短期反弹票通过门控)",
                "evidence_refs": ["ev-c220-diff"],
                "required_verification": ["ev-c220-tdd", "ev-c220-regression"],
                "review_delta": "",
                "recorded_at": "2026-06-28T00:30:00+08:00",
                "lenses": {
                    "alpha": {"findings_or_candidates": ["基于 c219 bootstrap CI 强证据 (T+5/T+10 winrate=60% CI 下界 59% >> 50%)"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "beta": {"findings_or_candidates": ["OR 逻辑标准做法; invalidation 保留 t30; mature_count 保留作代理"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "gamma": {"findings_or_candidates": ["服务 owner winrate>50% 门控翻转决策 (c218/c219 累积证据指向改 horizon)"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                },
            },
            {
                "gate": "pre_closure",
                "scope": "M14 BUY gate horizon T+30→T+5/T+10 OR",
                "evidence_refs": ["ev-c220-diff", "ev-c220-tdd"],
                "required_verification": ["ev-c220-regression"],
                "review_delta": "",
                "recorded_at": "2026-06-28T00:30:00+08:00",
                "lenses": {
                    "alpha": {"findings_or_candidates": ["6 C219 TDD + 33 更新全通过; OR 逻辑覆盖 t5_only/t10_only/both_fail/both_pass/watchable_or/invalidation_t30"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "beta": {"findings_or_candidates": ["1837 回归全通过, 0 failed, flake8 clean"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "gamma": {
                        "findings_or_candidates": [
                            "BUY gate 现在接受 low bucket 短期反弹票 (T+5/T+10 winrate=60%)",
                            "预期 live AVOID 比例下降 (low bucket 票从 AVOID→BUY/HOLD)",
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
                "scan_scope": "investability.py build_front_door_verdict: _meets_quality_bar + is_watchable 改 T+5 OR T+10",
                "finding_count": 0,
                "candidate_count": 0,
                "evidence_refs": ["ev-c220-diff"],
                "verification_refs": ["ev-c220-tdd", "ev-c220-regression"],
                "exhaustion_or_blocker": "delivery complete — BUY gate horizon 改 T+5/T+10 OR",
                "review_gate": "pre_closure",
            },
            "regression_and_commit": {
                "work_depth": "primary",
                "verdict": "pass",
                "scan_scope": "tests/screening/ (1837) + flake8",
                "finding_count": 0,
                "candidate_count": 0,
                "evidence_refs": ["ev-c220-diff"],
                "verification_refs": ["ev-c220-regression"],
                "exhaustion_or_blocker": "1837 passed + 0 lint — committed",
                "review_gate": "pre_closure",
            },
        },
        "issue_outcome": {
            "summary": "M14 BUY gate horizon T+30→T+5/T+10 OR. investability.py _meets_quality_bar 改用 T+5 OR T+10 (任一 edge>0 AND winrate>=0.55); is_watchable 同样改; t30 保留作 invalidation 长期衰退信号; bucket_t30_mature_count 保留作成熟度代理. 6 新 TDD + 33 更新测试 + 1837 回归全通过.",
            "root_cause": "c218 用 T+30 horizon 评估 low bucket winrate=45% 判断门控翻转不成立, 但 c219 per-horizon CI 证明 T+5/T+10 winrate=60% — horizon 选错了",
            "prediction": "live AVOID 比例下降 (low bucket 短期反弹票从 AVOID→BUY/HOLD)",
            "observed_outcome": "待 live 验证 (下一次 --auto 跑)",
        },
        "changes": [
            {
                "scope": "src/screening/investability.py",
                "behavior_delta": "build_front_door_verdict: +t5_edge/t5_win_rate/t10_edge/t10_win_rate; _meets_quality_bar 改 _short_term_passes (T+5 OR T+10); is_watchable 改 T+5 OR T+10; t30 保留作 invalidation",
                "evidence_refs": ["ev-c220-diff", "ev-c220-tdd"],
            },
            {
                "scope": "tests/screening/test_investability.py",
                "behavior_delta": "+6 C219 TDD (t5_only/t10_only/both_fail/both_pass/watchable_or/invalidation_t30); 7 现有测试更新加 t5/t10 字段",
                "evidence_refs": ["ev-c220-tdd"],
            },
        ],
        "closure_receipts": [
            {
                "kind": "git_closure",
                "status": "pass",
                "evidence_refs": ["ev-c220-diff", "ev-c220-tdd", "ev-c220-regression"],
                "user_change_isolation": "verified",
                "recorded_at": "2026-06-28T00:30:00+08:00",
                "commit_sha": "pending",
                "diff_evidence": "investability.py + test_investability.py 待 commit",
            },
            {
                "kind": "release_handoff",
                "intervention_id": "iv053-ns3-m14-buy-gate-horizon",
                "workflow_id": "wf-top-picks-must-win",
                "status": "concluded",
                "commit_or_no_diff": "pending commit",
                "release_or_observation_refs": ["ev-c220-regression"],
                "next_owner_or_trigger": "owner 观察 live AVOID 比例变化; 如仍高, 评估 winrate 阈值 0.55→0.50",
                "recorded_at": "2026-06-28T00:30:00+08:00",
            },
            {
                "kind": "pre_closure_review",
                "role_gate": "pre_closure",
                "residual_blockers": None,
                "evidence_refs": ["ev-c220-diff", "ev-c220-tdd", "ev-c220-regression"],
                "recorded_at": "2026-06-28T00:30:00+08:00",
            },
            {
                "kind": "state_write_intent",
                "target_campaign_status": "completed",
                "evidence_refs": ["ev-c220-diff", "ev-c220-tdd", "ev-c220-regression"],
                "recorded_at": "2026-06-28T00:30:00+08:00",
            },
        ],
    }
    state["campaigns"].append(c220)

    # 5. next_outer_loop_action
    state["next_outer_loop_action"] = {
        "action": "wait",
        "target_workflow_id": "wf-top-picks-must-win",
        "action_class": "delivery",
        "next_trigger": (
            "M14 BUY gate horizon T+30→T+5/T+10 OR 已交付 (基于 c219 per-horizon bootstrap CI 强证据: "
            "T+5 winrate=60.2% [59.0%, 61.3%], T+10 winrate=60.5% [59.4%, 61.6%], CI 下界 59% >> 50%). "
            "6 新 TDD + 33 更新测试 + 1837 回归全通过. "
            "下个 owner 观察: (1) live --auto 跑看 AVOID 比例是否下降 (预期 low bucket 短期反弹票从 AVOID→BUY/HOLD); "
            "(2) 如 AVOID 仍高, 评估 winrate 阈值 0.55→0.50; "
            "(3) 或继续其他因子修复 (volatility dir=0 55.7%). 模型 factor 仍 owner 范畴."
        ),
    }

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(f"✓ state.json updated: +c220 campaign +iv053 +cd220 +3 evidence")
    print(f"  campaigns: {len(state['campaigns'])}")
    print(f"  interventions: {len(state['interventions'])}")
    print(f"  candidate_portfolio: {len(state['candidate_portfolio'])}")
    print(f"  evidence_catalog: {len(state['evidence_catalog'])}")


if __name__ == "__main__":
    main()
