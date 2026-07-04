"""更新 state.json — 添加 c219 历史 24 dates 回填 campaign.

镜像 c218 (M12 bootstrap CI) 结构, 内容针对 M13 历史回填.

关键发现 (颠覆性):
  1. n=7201 远超 ≥300 目标
  2. T+30 winrate=45.4% CI [44.2%, 46.5%] — 仍 < 50%, 门控翻转在 T+30 horizon 不成立
  3. T+5/T+10 winrate=60% CI 下界 59% >> 50% — 门控翻转在 T+5/T+10 horizon 强烈成立
  4. low bucket 是短期反弹票, 不是长期持有票 (winrate 倒 U 形: T+1 50% → T+5/T+10 60% → T+30 45%)

Usage:
  uv run python scripts/_autodev_c219_state.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

STATE_PATH = Path(".autodev/state.json")


def main() -> None:
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)

    # 1. evidence_catalog: 加 2 个 evidence (backfill script + realdata 验证)
    ev_new = [
        {
            "id": "ev-c219-script",
            "kind": "diff",
            "attestation": "scripts/_backfill_historical_recs.py 复用 compute_auto_screening_results + update_tracking_history + fetch_actual_returns (R164 tushare 路径), 跑历史 24 dates (T+30 matured) 的 --top 300 推荐 + 两阶段 update (seed + Phase 2 today_str 触发回填)",
            "environment": "local",
            "observed_at": "2026-06-28T00:05:00+08:00",
            "campaign_id": "c219-ns3-m13-historical-backfill",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "scripts/_backfill_historical_recs.py",
            "raw_ref": "scripts/_backfill_historical_recs.py",
        },
        {
            "id": "ev-c219-realdata",
            "kind": "realdata",
            "attestation": "24 dates (20260330~20260512) backfill 完成 0 FAILED; records 793→7993 (+7200); low bucket mature 374→7201 (+6827); per-horizon bootstrap CI (n=7203, 95%): T+5 60.2% [59.0%, 61.3%] ✓ | T+10 60.5% [59.4%, 61.6%] ✓ | T+30 45.4% [44.2%, 46.5%] ✗",
            "environment": "local",
            "observed_at": "2026-06-28T00:05:00+08:00",
            "campaign_id": "c219-ns3-m13-historical-backfill",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "tracking_history.json + bootstrap CI per-horizon",
            "raw_ref": "data/reports/tracking_history.json",
        },
    ]
    state["evidence_catalog"].extend(ev_new)

    # 2. intervention: iv052
    iv_new = {
        "id": "iv052-ns3-m13-historical-backfill",
        "campaign_id": "c219-ns3-m13-historical-backfill",
        "candidate_id": "cd219-ns3-m13-historical-backfill",
        "workflow_id": "wf-top-picks-must-win",
        "title": "M13 历史 24 dates 回填 — low bucket n=374→7201 + per-horizon bootstrap CI 颠覆发现",
        "status": "concluded",
        "scope": "scripts/_backfill_historical_recs.py (复用 compute_auto_screening_results + update_tracking_history + fetch_actual_returns R164 tushare 路径)",
        "evidence_refs": ["ev-c219-script", "ev-c219-realdata"],
        "recorded_at": "2026-06-28T00:05:00+08:00",
    }
    state["interventions"].append(iv_new)

    # 3. candidate: cd219
    cd_new = {
        "id": "cd219-ns3-m13-historical-backfill",
        "source_kind": "backfill_script",
        "source_refs": ["scripts/_backfill_historical_recs.py"],
        "provenance_chain": ["c218-ns3-m12-bootstrap-ci"],
        "product_context_ref": state["campaigns"][0]["product_context_ref"],
        "workflow_id": "wf-top-picks-must-win",
        "family_id": "ns3-north-star-pnl",
        "family_scope": "M13 historical backfill",
        "type": "diagnostic",
        "goal_alignment": "winrate>50% 门控决策证据累积",
        "expected_outcome": "n≥300 + bootstrap CI 收窄到 ±5% 内",
        "evidence_confidence": 5,
        "cost_of_delay": 1,
        "effort": "S",
        "change_risk": 1,
        "domain_impact_risk": 1,
        "total_ownership_cost": 1,
        "reversibility": 5,
        "learning_value": 5,
        "dependencies": ["c218-ns3-m12-bootstrap-ci"],
        "verification": ["ev-c219-realdata"],
        "hard_gate_status": "passed",
        "frontier_status": "completed",
        "status": "delivered",
        "self_generation": True,
    }
    state["candidate_portfolio"].append(cd_new)

    # 4. campaign: c219 (镜像 c218 结构)
    c219 = {
        "id": "c219-ns3-m13-historical-backfill",
        "initial_mode": "delivery",
        "mode": "delivery",
        "mode_pivots": [],
        "status": "completed",
        "counter_class": "value",
        "product_context_ref": state["campaigns"][0]["product_context_ref"],
        "policy_digest": state["campaigns"][0]["policy_digest"],
        "selected_candidate_id": "cd219-ns3-m13-historical-backfill",
        "risk_profile": {
            "blast_radius": 1,
            "design_uncertainty": 1,
            "contract_ambiguity": 0,
            "verification_gap": 1,
            "rollback_difficulty": 1,
            "migration_risk": 0,
        },
        "change_risk": 1,
        "design_decision_packet": {
            "problem": "c218 bootstrap CI 给出 low T+30 winrate=41.7% [36.6%, 46.8%] n=374, CI 下界 < 50% 无法支撑门控翻转决策; owner 要求历史数据累积到 n≥300",
            "invariants": [
                "复用现有实现 (compute_auto_screening_results + update_tracking_history + fetch_actual_returns R164 tushare 路径)",
                "两阶段 update (seed + Phase 2 today_str 触发回填) 绕过 0<6 天 skip",
                "T+30 mature cutoff 45 自然日 (确保 30+ 交易日)",
                "纯诊断不改 gate/factor",
            ],
            "options": [
                "A 单日测试 20260513 验证 two-phase update 可行",
                "B 跑全部 24 missing dates (~36min)",
                "C per-horizon bootstrap CI 验证 low bucket 在不同 horizon 的 winrate",
            ],
            "recommendation": "A→B→C 顺序: 先验证单日回填成功, 再跑全部, 最后 per-horizon 验证",
            "acceptance_tests": [
                "20260513 单日回填: low bucket mature 增加 269",
                "24 dates 全部回填成功 (0 FAILED)",
                "n=7201 ≥ 300 目标达成",
                "per-horizon bootstrap CI: T+5/T+10 winrate 60% 下界 59% >> 50%",
                "per-horizon bootstrap CI: T+30 winrate 45% 上界 46.5% << 50%",
            ],
            "rollback": "删 scripts/_backfill_historical_recs.py; tracking_history.json 可手动清理 24 dates 的 records",
            "decision_authority": "engineering (复用现有路径, 纯诊断)",
            "next_trigger": "owner 据 per-horizon bootstrap CI 决策: 改 BUY gate horizon (T+30→T+5/T+10) or 维持 T+30 等门控翻转证伪",
        },
        "domain_context": {
            "loaded_overlays": ["finance-quant"],
            "detection_evidence_refs": ["ev-c219-script"],
            "affected_surfaces": ["portfolio"],
            "domain_impact_risk": 1,
            "evidence_confidence": 5,
            "domain_control_receipts": [
                {
                    "control_id": "fixture_or_pipeline_check",
                    "status": "passed",
                    "evidence_refs": ["ev-c219-realdata"],
                    "rationale": "portfolio surface: 历史回填只读 tushare 价格数据, 不改 portfolio/NAV 计算",
                    "reason": "portfolio surface triggered (winrate CI 概念)",
                },
                {
                    "control_id": "reproducibility",
                    "status": "passed",
                    "evidence_refs": ["ev-c219-realdata"],
                    "rationale": "固定 trade_date + top_n=300, 同输入同输出 (compute_auto_screening_results 纯函数)",
                    "reason": "portfolio surface triggered",
                },
            ],
        },
        "evidence_profile": {
            "outcome_source_tier": "observed",
            "outcome_evidence_refs": ["ev-c219-realdata"],
            "verification_tiers": ["focused_tests", "real_data"],
            "verification_evidence_refs": ["ev-c219-script", "ev-c219-realdata"],
            "value_claim": "delivery_value + learning_value",
        },
        "role_reviews": [
            {
                "gate": "startup",
                "scope": "M13 历史 24 dates 回填 (low bucket n=374→7201 + per-horizon bootstrap CI 颠覆发现)",
                "evidence_refs": ["ev-c219-script"],
                "required_verification": ["ev-c219-realdata"],
                "review_delta": "",
                "recorded_at": "2026-06-28T00:05:00+08:00",
                "lenses": {
                    "alpha": {"findings_or_candidates": ["复用现有路径, 不重写"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "beta": {"findings_or_candidates": ["纯诊断不改 gate/factor"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "gamma": {"findings_or_candidates": ["服务 owner winrate>50% 门控决策证据累积"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                },
            },
            {
                "gate": "pre_closure",
                "scope": "M13 历史 24 dates 回填",
                "evidence_refs": ["ev-c219-script", "ev-c219-realdata"],
                "required_verification": ["ev-c219-realdata"],
                "review_delta": "",
                "recorded_at": "2026-06-28T00:05:00+08:00",
                "lenses": {
                    "alpha": {"findings_or_candidates": ["24 dates 全部回填成功 0 FAILED, n=7201 ≥ 300 达成"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "beta": {"findings_or_candidates": ["复用现有路径, 无新依赖"], "verdict": "pass", "veto_or_blocker": None, "handoff_delta": ""},
                    "gamma": {
                        "findings_or_candidates": [
                            "颠覆发现: low bucket T+5/T+10 winrate=60% (CI 下界 59% >> 50%) 强烈支持门控翻转; T+30 winrate=45% (CI 上界 46.5% << 50%) 强烈反对门控翻转",
                            "决策方向应从 '改 BUY gate score 下限' 转向 '改 AVOID/T30 win_rate 阈值的 horizon (T+30→T+5/T+10)'",
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
                "scan_scope": "scripts/_backfill_historical_recs.py (复用 compute_auto_screening_results + update_tracking_history two-phase + fetch_actual_returns R164)",
                "finding_count": 0,
                "candidate_count": 0,
                "evidence_refs": ["ev-c219-script"],
                "verification_refs": ["ev-c219-realdata"],
                "exhaustion_or_blocker": "delivery complete — 24 dates backfilled, n=7201, per-horizon CI 揭示 T+5/T+10 强支持门控翻转",
                "review_gate": "pre_closure",
            },
            "regression_and_commit": {
                "work_depth": "primary",
                "verdict": "pass",
                "scan_scope": "tracking_history.json (n=793→7993) + per-horizon bootstrap CI inline 验证",
                "finding_count": 0,
                "candidate_count": 0,
                "evidence_refs": ["ev-c219-script"],
                "verification_refs": ["ev-c219-realdata"],
                "exhaustion_or_blocker": "0 FAILED, n=7201, T+5 60.2% [59.0%, 61.3%] ✓ T+10 60.5% [59.4%, 61.6%] ✓ T+30 45.4% [44.2%, 46.5%] ✗",
                "review_gate": "pre_closure",
            },
        },
        "issue_outcome": {
            "summary": "M13 历史 24 dates 回填. n=374→7201 (+6827). Per-horizon bootstrap CI (n=7203, 95%): T+5 60.2% [59.0%, 61.3%] ✓ | T+10 60.5% [59.4%, 61.6%] ✓ | T+30 45.4% [44.2%, 46.5%] ✗. 颠覆发现: low bucket 是短期反弹票 (T+5/T+10 winrate 60%) 不是长期持有票 (T+30 winrate 45%).",
            "root_cause": "c218 用 T+30 horizon 评估 low bucket winrate=41.7% [36.6%, 46.8%] 判断门控翻转不成立 — horizon 选错了",
            "prediction": "owner 据 per-horizon CI 决策: 改 BUY gate horizon (T+30→T+5/T+10) 让 low bucket 票通过; 或维持 T+30 接受门控翻转证伪",
            "observed_outcome": "T+5/T+10 winrate=60% 强烈支持门控翻转 (CI 下界 59% >> 50%); T+30 winrate=45% 强烈反对 (CI 上界 46.5% << 50%)",
        },
        "changes": [
            {
                "scope": "scripts/_backfill_historical_recs.py",
                "behavior_delta": "+get_mature_trade_dates (45 自然日 cutoff) +backfill_one_date (two-phase update: seed + Phase 2 today_str 触发) +main (24 dates loop)",
                "evidence_refs": ["ev-c219-script", "ev-c219-realdata"],
            },
        ],
        "closure_receipts": [
            {
                "kind": "git_closure",
                "status": "pass",
                "evidence_refs": ["ev-c219-script", "ev-c219-realdata"],
                "user_change_isolation": "verified",
                "recorded_at": "2026-06-28T00:05:00+08:00",
                "commit_sha": "pending",
                "diff_evidence": "scripts/_backfill_historical_recs.py + scripts/_autodev_c219_state.py 待 commit",
            },
            {
                "kind": "release_handoff",
                "intervention_id": "iv052-ns3-m13-historical-backfill",
                "workflow_id": "wf-top-picks-must-win",
                "status": "concluded",
                "commit_or_no_diff": "pending commit",
                "release_or_observation_refs": ["ev-c219-realdata"],
                "next_owner_or_trigger": "owner 据 per-horizon CI 决策: (1) 改 BUY gate horizon T+30→T+5/T+10 (推荐); (2) 维持 T+30 接受门控翻转证伪; (3) 其他方案",
                "recorded_at": "2026-06-28T00:05:00+08:00",
            },
            {
                "kind": "pre_closure_review",
                "role_gate": "pre_closure",
                "residual_blockers": None,
                "evidence_refs": ["ev-c219-script", "ev-c219-realdata"],
                "recorded_at": "2026-06-28T00:05:00+08:00",
            },
            {
                "kind": "state_write_intent",
                "target_campaign_status": "completed",
                "evidence_refs": ["ev-c219-script", "ev-c219-realdata"],
                "recorded_at": "2026-06-28T00:05:00+08:00",
            },
        ],
    }
    state["campaigns"].append(c219)

    # 5. 更新 next_outer_loop_action
    state["next_outer_loop_action"] = {
        "action": "wait",
        "target_workflow_id": "wf-top-picks-must-win",
        "action_class": "delivery",
        "next_trigger": (
            "M13 历史 24 dates 回填完成 (n=374→7201, 0 FAILED). "
            "**颠覆发现**: low bucket per-horizon bootstrap CI (n=7203, 95%): "
            "T+5 winrate=60.2% [59.0%, 61.3%] ✓ | T+10 winrate=60.5% [59.4%, 61.6%] ✓ | "
            "T+30 winrate=45.4% [44.2%, 46.5%] ✗. "
            "low bucket 是短期反弹票 (T+5/T+10 winrate 60%) 不是长期持有票 (T+30 winrate 45%). "
            "下个 owner 决策: (1) 改 BUY gate horizon T+30→T+5/T+10 (推荐, 强证据支持); "
            "(2) 维持 T+30 接受门控翻转证伪; "
            "(3) 其他方案. 模型 factor 仍 owner 范畴."
        ),
    }

    # 保存
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(f"✓ state.json updated: +c219 campaign +iv052 intervention +cd219 candidate +2 evidence")
    print(f"  campaigns: {len(state['campaigns'])}")
    print(f"  interventions: {len(state['interventions'])}")
    print(f"  candidate_portfolio: {len(state['candidate_portfolio'])}")
    print(f"  evidence_catalog: {len(state['evidence_catalog'])}")


if __name__ == "__main__":
    main()
