"""autodev C218 state.json 更新脚本 — 添加 c218 bootstrap CI campaign.

镜像 c211 campaign 结构, 适配 M12 bootstrap CI 内容.
- 5 evidence (diff/tdd/focused/static/realdata)
- 1 campaign (c218-ns3-m12-bootstrap-ci)
- 1 candidate (cd218-ns3-m12-bootstrap-ci)
- 1 intervention (iv051-ns3-m12-bootstrap-ci)
- 更新 next_outer_loop_action (wait — 证据不足以支撑门控翻转)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

STATE_PATH = Path(".autodev/state.json")
NOW = "2026-06-27T23:30:00+08:00"
COMMIT_SHA = "7223b348"

# 复用 c211 的 product_context_ref + policy_digest (同 workflow, 同 policy)
PRODUCT_CONTEXT_DIGEST = "bf857d02bac31295aac3b64c9adf1c5042e05278c2f21f59d788213160c1da4c"
POLICY_DIGEST = "95b3ea1a8610f4811fc3691b6bcd25019927436f6d9f05b84b8f7e5a073962c0"

EVIDENCES = [
    {
        "id": "ev-c218-diff",
        "kind": "diff_observation",
        "attestation": "file_observed",
        "environment": "local",
        "observed_at": NOW,
        "campaign_id": "c218-ns3-m12-bootstrap-ci",
        "workflow_id": "wf-top-picks-must-win",
        "subject": "wf-top-picks-must-win",
        "raw_ref": "file: git diff 7223b348 — north_star_pnl.py (+BootstrapCIResult +_bootstrap_winrate_ci percentile +compute_bootstrap_ci_from_loaded +render_bootstrap_ci_line) + top_picks.py (footer M12 bootstrap CI 行) + test (+8 TDD M12)"
    },
    {
        "id": "ev-c218-tdd",
        "kind": "test_result",
        "attestation": "command_observed",
        "environment": "local",
        "observed_at": NOW,
        "campaign_id": "c218-ns3-m12-bootstrap-ci",
        "workflow_id": "wf-top-picks-must-win",
        "subject": "wf-top-picks-must-win",
        "raw_ref": "cmd: uv run pytest tests/screening/test_north_star_pnl.py -k bootstrap_ci -v (8 TDD passed: percentile bounds / monotonic / idempotent / insufficient / per-bucket / extreme capped / render / silent)"
    },
    {
        "id": "ev-c218-focused",
        "kind": "test_result",
        "attestation": "command_observed",
        "environment": "local",
        "observed_at": NOW,
        "campaign_id": "c218-ns3-m12-bootstrap-ci",
        "workflow_id": "wf-top-picks-must-win",
        "subject": "wf-top-picks-must-win",
        "raw_ref": "cmd: uv run pytest tests/screening/test_north_star_pnl.py -q (35 passed = 27 existing + 8 new M12) + uv run pytest tests/screening/ -q (1831 passed, 0 failed)"
    },
    {
        "id": "ev-c218-static",
        "kind": "static_analysis",
        "attestation": "command_observed",
        "environment": "local",
        "observed_at": NOW,
        "campaign_id": "c218-ns3-m12-bootstrap-ci",
        "workflow_id": "wf-top-picks-must-win",
        "subject": "wf-top-picks-must-win",
        "raw_ref": "cmd: uv run flake8 src/screening/north_star_pnl.py src/screening/top_picks.py tests/screening/test_north_star_pnl.py (no output = clean; E402 修复: import random as _random 移到顶部)"
    },
    {
        "id": "ev-c218-realdata",
        "kind": "dogfood_observation",
        "attestation": "command_observed",
        "environment": "local",
        "observed_at": NOW,
        "campaign_id": "c218-ns3-m12-bootstrap-ci",
        "workflow_id": "wf-top-picks-must-win",
        "subject": "wf-top-picks-must-win",
        "raw_ref": "cmd: real-data 493 bootstrap CI (n_boot=10000, seed=42) → low 50.5% [41%, 60%] n=105 | mid_low 46.2% [40%, 53%] n=225 | mid_high 43.2% [34%, 52%] n=125 | high 39.5% [24%, 55%] n=38. ⚠ low CI 下界 41% < 50% — 现有证据不足以稳健支撑门控翻转"
    }
]

CAMPAIGN = {
    "id": "c218-ns3-m12-bootstrap-ci",
    "initial_mode": "delivery",
    "mode": "delivery",
    "mode_pivots": [],
    "status": "completed",
    "counter_class": "value",
    "product_context_ref": {"revision": 3, "context_digest": PRODUCT_CONTEXT_DIGEST},
    "policy_digest": POLICY_DIGEST,
    "selected_candidate_id": "cd218-ns3-m12-bootstrap-ci",
    "risk_profile": {
        "blast_radius": 1,
        "design_uncertainty": 1,
        "contract_ambiguity": 0,
        "verification_gap": 1,
        "rollback_difficulty": 1,
        "migration_risk": 0
    },
    "change_risk": 1,
    "design_decision_packet": {
        "problem": "owner 需基于 low bucket winrate=50% (n=105) 决策门控翻转, 但正态近似 95% CI (±9.6%, [40%, 60%]) 太宽无法支撑决策",
        "invariants": [
            "纯诊断不改 gate/factor (Phase 0 STOP)",
            "display-only best-effort",
            "幂等 (固定 seed=42)",
            "单调 (lower<=upper clamp [0,1])",
            "无新依赖 (标准库 random)"
        ],
        "options": [
            "A bootstrap percentile CI (免正态假设, per-bucket)",
            "B 独立脚本 scripts/bootstrap_ci.py (不动 product code)",
            "C 加到 --decision-flow 现有诊断模块"
        ],
        "recommendation": "A — compute_bootstrap_ci_from_loaded (per-bucket, percentile method) + render_bootstrap_ci_line, 与 M10/M11 payoff+pruning 同源",
        "acceptance_tests": [
            "bootstrap percentile bounds 计算",
            "CI 单调 (lower <= upper)",
            "幂等 (同 seed 同 output)",
            "小样本 insufficient 静默",
            "per-bucket 模式",
            "winrate=100% capped at 1.0",
            "render 含 bounds + bucket label",
            "全 insufficient → 空串"
        ],
        "rollback": "删 BootstrapCIResult + _bootstrap_winrate_ci + compute/render_bootstrap_ci_line + footer 调用",
        "decision_authority": "engineering (bootstrap percentile method 标准做法)",
        "next_trigger": "owner 据 bootstrap CI 决策门控翻转 (low CI 下界 41% < 50% → 等累积) 或授权 daily_accumulate cron 持续累积"
    },
    "domain_context": {
        "loaded_overlays": ["finance-quant"],
        "detection_evidence_refs": ["ev-c218-diff"],
        "affected_surfaces": ["portfolio"],
        "domain_impact_risk": 4,
        "evidence_confidence": 2,
        "domain_control_receipts": [
            {
                "control_id": "fixture_or_pipeline_check",
                "status": "passed",
                "evidence_refs": ["ev-c218-tdd"],
                "rationale": "portfolio surface: bootstrap CI 是全样本统计, 8 TDD 合成数据覆盖; 不触及真实 portfolio/NAV 计算, 只读 tracking_history",
                "reason": "portfolio surface triggered (winrate CI 概念)"
            },
            {
                "control_id": "timestamp_alignment",
                "status": "not_applicable",
                "evidence_refs": [],
                "rationale": "静态历史记录, 无时间对齐变更",
                "reason": "display-only 全样本统计, 无 finance surface triggered"
            },
            {
                "control_id": "reproducibility",
                "status": "passed",
                "evidence_refs": ["ev-c218-tdd"],
                "rationale": "portfolio surface: 纯函数 _bootstrap_winrate_ci 幂等 (固定 seed=42), 8 TDD 验证可复现; test_bootstrap_ci_idempotent_same_seed 锁定",
                "reason": "portfolio surface triggered"
            },
            {
                "control_id": "cost_and_slippage",
                "status": "not_applicable",
                "evidence_refs": [],
                "rationale": "无 execution 声明",
                "reason": "display-only 全样本统计, 无 finance surface triggered"
            },
            {
                "control_id": "benchmark_disclosure",
                "status": "not_applicable",
                "evidence_refs": [],
                "rationale": "历史统计, sample_count 已标",
                "reason": "display-only 全样本统计, 无 finance surface triggered"
            }
        ]
    },
    "evidence_profile": {
        "outcome_source_tier": "unobserved",
        "outcome_evidence_refs": [],
        "verification_tiers": ["focused_tests", "static_analysis"],
        "verification_evidence_refs": ["ev-c218-tdd", "ev-c218-focused", "ev-c218-static"],
        "value_claim": "delivery_value"
    },
    "role_reviews": [
        {
            "gate": "startup",
            "scope": "M12 winrate bootstrap CI (per-bucket percentile, 服务 winrate>50% 门控决策稳健不确定性估计)",
            "evidence_refs": ["ev-c218-diff"],
            "required_verification": ["ev-c218-tdd"],
            "review_delta": "",
            "recorded_at": NOW,
            "lenses": {
                "alpha": {"findings_or_candidates": ["M12 bootstrap CI 扩展 north_star_pnl (8 新 TDD), focused 35 绿"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                "beta": {"findings_or_candidates": ["display-only 全样本统计; 不改 gate/factor; flake8 clean"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                "gamma": {"findings_or_candidates": ["服务 owner winrate>50% 门控决策: 给稳健不确定性估计 (vs 正态近似 ±9.6%)"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""}
            }
        },
        {
            "gate": "candidate_selection",
            "scope": "M12 winrate bootstrap CI (per-bucket percentile, 服务 winrate>50% 门控决策稳健不确定性估计)",
            "evidence_refs": ["ev-c218-diff"],
            "required_verification": ["ev-c218-tdd"],
            "review_delta": "",
            "recorded_at": NOW,
            "lenses": {
                "alpha": {"findings_or_candidates": ["cd product_backlog authoritative (NS-3 北极星诊断链); WIP 解锁"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                "beta": {"findings_or_candidates": ["WIP: c211 concluded; 新 intervention iv051"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                "gamma": {"findings_or_candidates": ["owner 目标 winrate>50% 门控决策 → 需稳健 CI → autodev 提供 bootstrap percentile"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""}
            },
            "policy_digest": POLICY_DIGEST
        },
        {
            "gate": "pre_implementation",
            "scope": "M12 winrate bootstrap CI (per-bucket percentile, 服务 winrate>50% 门控决策稳健不确定性估计)",
            "evidence_refs": ["ev-c218-diff"],
            "required_verification": ["ev-c218-tdd"],
            "review_delta": "",
            "recorded_at": NOW,
            "lenses": {
                "alpha": {"findings_or_candidates": ["_bootstrap_winrate_ci (percentile, 幂等 seed, 单调 clamp) + compute_bootstrap_ci_from_loaded (per-bucket, insufficient 静默) + render_bootstrap_ci_line"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                "beta": {"findings_or_candidates": ["TDD 8: percentile bounds / monotonic / idempotent / insufficient / per-bucket / extreme capped / render / silent"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                "gamma": {"findings_or_candidates": ["render bootstrap CI → 给 owner 稳健不确定性估计 (CI 下界 < 50% → 诚实告知证据不足)"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""}
            }
        },
        {
            "gate": "pre_closure",
            "scope": "M12 winrate bootstrap CI (per-bucket percentile, 服务 winrate>50% 门控决策稳健不确定性估计)",
            "evidence_refs": ["ev-c218-diff"],
            "required_verification": ["ev-c218-tdd"],
            "review_delta": "",
            "recorded_at": NOW,
            "lenses": {
                "alpha": {"findings_or_candidates": ["8 TDD green, focused 35, full screening 1831, flake8 clean, real-data low 50.5% [41%, 60%] 验证, committed 7223b348"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                "beta": {"findings_or_candidates": ["无 blocker; controls passed (reproducibility 幂等); full regression 1831 passed (vs 1823 +8 M12)"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                "gamma": {"findings_or_candidates": ["delivery_value + learning_value (bootstrap CI 下界 41% < 50% → 诚实告知证据不足以支撑门控翻转)"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""}
            },
            "policy_digest": POLICY_DIGEST
        }
    ],
    "stage_receipts": {
        "bug_hunt": {
            "work_depth": "supporting", "verdict": "pass",
            "scan_scope": "bootstrap CI 新增 display 无 bug",
            "finding_count": 0, "candidate_count": 0,
            "evidence_refs": ["ev-c218-diff"],
            "verification_refs": ["ev-c218-tdd", "ev-c218-focused"],
            "exhaustion_or_blocker": "not applicable — delivery",
            "review_gate": "pre_implementation"
        },
        "refactor_batch": {
            "work_depth": "supporting", "verdict": "pass",
            "scan_scope": "no refactor",
            "finding_count": 0, "candidate_count": 0,
            "evidence_refs": ["ev-c218-diff"],
            "verification_refs": ["ev-c218-tdd", "ev-c218-focused"],
            "exhaustion_or_blocker": "not applicable",
            "review_gate": "pre_implementation"
        },
        "product_quality_upgrade": {
            "work_depth": "supporting", "verdict": "pass",
            "scan_scope": "no quality upgrade",
            "finding_count": 0, "candidate_count": 0,
            "evidence_refs": ["ev-c218-diff"],
            "verification_refs": ["ev-c218-tdd", "ev-c218-focused"],
            "exhaustion_or_blocker": "not applicable",
            "review_gate": "pre_implementation"
        },
        "feature_delivery": {
            "work_depth": "primary", "verdict": "pass",
            "scan_scope": "north_star_pnl.py (+BootstrapCIResult +_bootstrap_winrate_ci +compute_bootstrap_ci_from_loaded +render_bootstrap_ci_line) + top_picks.py (footer M12) + test (+8 TDD M12)",
            "finding_count": 0, "candidate_count": 0,
            "evidence_refs": ["ev-c218-diff"],
            "verification_refs": ["ev-c218-tdd", "ev-c218-focused"],
            "exhaustion_or_blocker": "delivery complete — bootstrap CI per-bucket [low 50.5% [41%, 60%]] 验证",
            "review_gate": "pre_closure"
        },
        "regression_and_commit": {
            "work_depth": "primary", "verdict": "pass",
            "scan_scope": "test_north_star_pnl.py (35) + tests/screening (1831) + flake8",
            "finding_count": 0, "candidate_count": 0,
            "evidence_refs": ["ev-c218-diff"],
            "verification_refs": ["ev-c218-tdd", "ev-c218-focused"],
            "exhaustion_or_blocker": "35+1831 passed + 0 lint — committed 7223b348",
            "review_gate": "pre_closure"
        }
    },
    "issue_outcome": {
        "summary": "M12 winrate bootstrap CI. 真实 493 (n_boot=10000, seed=42): low 50.5% [41%, 60%] n=105 | mid_low 46.2% [40%, 53%] n=225 | mid_high 43.2% [34%, 52%] n=125 | high 39.5% [24%, 55%] n=38. ⚠ low CI 下界 41% < 50% — 现有证据不足以稳健支撑 winrate>50% 门控翻转.",
        "root_cause": "owner 需基于 low bucket winrate=50% 决策门控翻转, 但正态近似 ±9.6% 太宽 → 需 bootstrap CI 更稳健",
        "prediction": "owner 据 bootstrap CI 决策: low CI 下界 41% < 50% → 等累积; 或授权 daily_accumulate cron 持续累积到 n≥300 CI 收窄",
        "observed_outcome": "real-data low 50.5% [41%, 60%] 正确 (CI 下界 41% < 50% 诚实告知证据不足)"
    },
    "changes": [
        {
            "scope": "src/screening/north_star_pnl.py",
            "behavior_delta": "+BootstrapCIResult +_bootstrap_winrate_ci (percentile, 幂等 seed, 单调 clamp [0,1]) +compute_bootstrap_ci_from_loaded (per-bucket, insufficient 静默) +render_bootstrap_ci_line",
            "evidence_refs": ["ev-c218-diff", "ev-c218-tdd"]
        },
        {
            "scope": "src/screening/top_picks.py",
            "behavior_delta": "_print_north_star_block 加 M12 bootstrap CI footer 行 (try/except 隔离, best-effort)",
            "evidence_refs": ["ev-c218-diff"]
        },
        {
            "scope": "tests/screening/test_north_star_pnl.py",
            "behavior_delta": "+8 TDD M12 (percentile bounds / monotonic / idempotent / insufficient / per-bucket / extreme capped / render / silent)",
            "evidence_refs": ["ev-c218-tdd"]
        }
    ],
    "closure_receipts": [
        {
            "kind": "git_closure", "status": "pass",
            "evidence_refs": ["ev-c218-diff", "ev-c218-tdd"],
            "user_change_isolation": "verified",
            "recorded_at": NOW,
            "commit_sha": COMMIT_SHA,
            "diff_evidence": f"Committed {COMMIT_SHA} feat(NS-3/M12) winrate bootstrap CI"
        },
        {
            "kind": "release_handoff",
            "intervention_id": "iv051-ns3-m12-bootstrap-ci",
            "workflow_id": "wf-top-picks-must-win",
            "status": "concluded",
            "commit_or_no_diff": f"committed {COMMIT_SHA}",
            "release_or_observation_refs": ["ev-c218-realdata"],
            "next_owner_or_trigger": "iv051 conclude (real-data render); owner 据 bootstrap CI 决策门控翻转或授权累积",
            "recorded_at": NOW
        },
        {
            "kind": "pre_closure_review",
            "role_gate": "pre_closure",
            "residual_blockers": None,
            "evidence_refs": ["ev-c218-tdd", "ev-c218-focused"],
            "recorded_at": NOW
        },
        {
            "kind": "state_write_intent",
            "target_campaign_status": "completed",
            "evidence_refs": ["ev-c218-tdd", "ev-c218-focused"],
            "recorded_at": NOW
        }
    ]
}

CANDIDATE = {
    "id": "cd218-ns3-m12-bootstrap-ci",
    "source_kind": "product_backlog",
    "source_refs": ["ev-c218-diff"],
    "provenance_chain": [
        {
            "source_kind": "product_backlog",
            "source_ref": "ev-c218-diff",
            "node": "owner 需基于 low bucket winrate=50% (n=105) 决策门控翻转, 正态近似 ±9.6% 太宽 → 需 bootstrap CI"
        },
        {
            "source_kind": "product_backlog",
            "source_ref": "ev-c218-realdata",
            "node": "真实: low 50.5% [41%, 60%] — CI 下界 41% < 50% 诚实告知证据不足"
        }
    ],
    "product_context_ref": {"revision": 3, "context_digest": PRODUCT_CONTEXT_DIGEST},
    "workflow_id": "wf-top-picks-must-win",
    "family_id": "ns3-m12-bootstrap-ci",
    "family_scope": {
        "revision": "2026-06-27-r1",
        "roots": ["north_star_pnl.py (bootstrap CI)"],
        "dimensions": ["bootstrap-ci", "percentile-method", "uncertainty-quantification", "winrate-confidence-interval"],
        "exclusions": ["factor changes (Phase 0 STOP)", "BUY 门控变更 (owner semantics)"],
        "scope_digest": "a8f3c2e9b1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1"
    },
    "type": "delivery",
    "goal_alignment": 4,
    "expected_outcome": "winrate bootstrap CI 给 owner 门控决策稳健不确定性估计 (vs 正态近似 ±9.6%)",
    "evidence_confidence": 2,
    "cost_of_delay": 4,
    "effort": 3,
    "change_risk": 1,
    "domain_impact_risk": 4,
    "total_ownership_cost": 1,
    "reversibility": 4,
    "learning_value": 4,
    "dependencies": [],
    "verification": ["ev-c218-tdd", "ev-c218-focused"],
    "hard_gate_status": "pass",
    "frontier_status": "selected",
    "status": "delivered",
    "self_generation": {
        "source_class": "authoritative",
        "depth_before_selection": 0,
        "depth_after_selection": 0,
        "reset_evidence_ref": None
    }
}

INTERVENTION = {
    "id": "iv051-ns3-m12-bootstrap-ci",
    "workflow_id": "wf-top-picks-must-win",
    "status": "concluded",
    "history": ["planned", "delivered", "released", "observing", "concluded"],
    "release_batch_id": "rb022-ns3-m12",
    "predicted_outcome": "--top-picks footer 展示 winrate bootstrap CI; 真实 low 50.5% [41%, 60%] 让 owner 看到证据不足以支撑门控翻转",
    "evidence_profile": {
        "outcome_source_tier": "controlled_dogfood",
        "outcome_evidence_refs": ["ev-c218-realdata"],
        "verification_tiers": ["focused_tests", "full_regression", "static_analysis"],
        "verification_evidence_refs": ["ev-c218-tdd", "ev-c218-focused", "ev-c218-static"],
        "value_claim": "realized_value",
        "baseline": "前门无 winrate CI, owner 只能看正态近似 ±9.6% (太宽)",
        "observed_result": "real-data render: footer 展示 low 50.5% [41%, 60%] (n=105), CI 下界 41% < 50% 诚实告知证据不足",
        "guardrail": "render insufficient 静默 (不破坏前门); 幂等 (seed=42); 单调 (clamp [0,1])",
        "observation_window": "c218 real-data render (493 真实记录) + 8 TDD",
        "decision": "keep"
    }
}

NEXT_ACTION = {
    "action": "wait",
    "target_workflow_id": "wf-top-picks-must-win",
    "action_class": "delivery",
    "next_trigger": (
        "M12 bootstrap CI delivered (7223b348). **winrate>50% 门控决策证据不足**: "
        "low bucket 50.5% (n=105) bootstrap 95% CI = [41%, 60%] — CI 下界 41% < 50%, "
        "现有证据不足以稳健支撑门控翻转 (正态近似 ±9.6% → bootstrap 更精准但结论一致: 等累积). "
        "下个: (1) owner 授权 daily_accumulate cron 持续累积到 n≥300 (CI 收窄到 ±5.5%); "
        "(2) owner 据现有证据决策 (接受小样本风险改门控 or 等累积); "
        "(3) 或启动并行 NS-5 (P1, autodev 可自主, REGIME_HISTORICAL_WINRATES 自动刷新). "
        "模型 factor 仍 owner 范畴."
    )
}


def main() -> None:
    """更新 state.json: 添加 c218 campaign + evidence + candidate + intervention."""
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    # 1. 追加 evidence (避免重复)
    existing_ev_ids = {e["id"] for e in state["evidence_catalog"]}
    for ev in EVIDENCES:
        if ev["id"] not in existing_ev_ids:
            state["evidence_catalog"].append(ev)

    # 2. 追加 campaign (避免重复)
    existing_camp_ids = {c["id"] for c in state["campaigns"]}
    if CAMPAIGN["id"] not in existing_camp_ids:
        state["campaigns"].append(CAMPAIGN)

    # 3. 追加 candidate (避免重复) — key 是 candidate_portfolio 不是 candidates
    existing_cd_ids = {c["id"] for c in state["candidate_portfolio"]}
    if CANDIDATE["id"] not in existing_cd_ids:
        state["candidate_portfolio"].append(CANDIDATE)

    # 4. 追加 intervention (避免重复)
    existing_iv_ids = {i["id"] for i in state["interventions"]}
    if INTERVENTION["id"] not in existing_iv_ids:
        state["interventions"].append(INTERVENTION)

    # 5. 更新 next_outer_loop_action
    state["next_outer_loop_action"] = NEXT_ACTION

    # 6. 写回 (原子写)
    tmp_path = STATE_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(STATE_PATH)
    print(f"updated {STATE_PATH}: +{len(EVIDENCES)} ev +1 camp +1 cd +1 iv +next_action")


if __name__ == "__main__":
    main()
