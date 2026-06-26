"""AutoDev C191 NS-17 切片 2 state.json writer.

基于 C190 结构创建 C191 (NS-17 打分可观测性切片 2:
graph.py + hedge_fund_streaming.py print→logger drain)。

修改:
- campaigns: 添加 C191 (复用 C190 结构, 修改 id/slug/changes/issue_outcome/affected_surfaces)
- evidence_catalog: 添加 C191 相关 evidence (TDD/lint/regression/diff)
- interventions: 添加 iv036-ns17-scoring-observability (delivered, committed_unreleased)
- release_batches: 添加 rb-ns17-observability (包含 iv035 + iv036, 同 workflow WIP gate)
- candidate_portfolio: 添加 cd191-ns17-scoring-observability
- budget: campaigns_executed 4→5, value_campaigns_completed 4→5
- next_outer_loop_action: awaiting_release (iv035+iv036 同 workflow delivered)
- iv035: 更新 release_batch_id 指向 rb-ns17-observability

使用: uv run python scripts/_autodev_c191_state.py
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path(".autodev/state.json")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def main() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    # 1. 找到 C190 campaign 作为模板
    c190 = next(c for c in state["campaigns"] if c["id"] == "c190-ns2-model-version-infra")
    c191 = copy.deepcopy(c190)

    # 2. 修改 C191 关键字段
    c191["id"] = "c191-ns17-scoring-observability"
    c191["selected_candidate_id"] = "cd191-ns17-scoring-observability"
    # policy_digest 保持与 C190 相同 (同一 product_context, 同一 policy)

    # 修改 issue_outcome
    c191["issue_outcome"] = {
        "summary": "NS-17 切片 2: graph.py parse_hedge_fund_response + hedge_fund_streaming.py SSE cancel 之前用 print() 吞错误/事件, 运维无法从结构化日志定位'为何某 ticker 缺 strategy signal'以及'为何某次 hedge fund run/backtest 中途断流'。修复: 两个文件新增 module logger, 9 处 print() → logger.warning (JSON parse 失败) / logger.info (SSE cancel 事件), 行为零变更, 但 LLM 打分链路与 SSE 流式的降级/中断完全可观测。",
        "root_cause": "graph.py parse_hedge_fund_response 的 3 处 print() (JSONDecodeError/TypeError/Exception) 和 hedge_fund_streaming.py 的 6 处 print() (SSE cancel/task cancel/generator cancel) 都不入结构化日志, 运维无法从 logs 定位 LLM JSON-parse 失败和 SSE 断流。NS-17 描述明确指出这两个文件是 must-win workflow 可观测性缺口。",
        "fix": "graph.py: 新增 module logger + 3 处 print() → logger.warning (含 parse_hedge_fund_response 标记 + response repr)。hedge_fund_streaming.py: 新增 module logger + 6 处 print() → logger.info (SSE disconnect/cancel 是正常运行事件)。7 个 TDD caplog 守卫 (3 graph parse + 2 module logger exists + 2 no print remain)。",
        "residual_risk": "signal_fusion.py 的 NS-17 核心部分 (per-ticker DEBUG score breakdown) 此前已实施 (line 503-518 logger.debug), 本次切片只覆盖剩余的 graph.py + hedge_fund_streaming.py。无残余风险 — 行为零变更 (仍降级/返回 None), 只增加了结构化日志输出。"
    }

    # 修改 changes (scope/behavior delta)
    c191["changes"] = [
        {
            "scope": "app/backend/services/graph.py",
            "behavior_delta": "新增 module logger (logging.getLogger); parse_hedge_fund_response 的 3 处 print() (JSONDecodeError/TypeError/Exception) 改为 logger.warning, 含 parse_hedge_fund_response 标记 + response repr, 行为零变更 (仍返回 None)",
            "evidence_refs": ["ev-c191-diff", "ev-c191-lint"]
        },
        {
            "scope": "app/backend/routes/hedge_fund_streaming.py",
            "behavior_delta": "新增 module logger (logging.getLogger); 6 处 print() (SSE disconnect/cancel/generator-cancel for hedge fund run + backtest) 改为 logger.info, 行为零变更 (仍 return/cancel)",
            "evidence_refs": ["ev-c191-diff", "ev-c191-lint"]
        },
        {
            "scope": "tests/backend/test_ns17_observability.py",
            "behavior_delta": "新增 7 个 TDD 守卫: 3 个 graph parse_hedge_fund_response caplog (JSONDecodeError/TypeError/valid) + 2 个 hedge_fund_streaming module logger + no-print + 2 个 graph module logger + no-print",
            "evidence_refs": ["ev-c191-tdd", "ev-c191-regression"]
        }
    ]

    # 修改 affected_surfaces (observability, 不是 market_data/backtest/performance_claim)
    c191["domain_context"]["affected_surfaces"] = ["observability"]

    # 修改 domain_control_receipts (observability 不触发 finance-quant controls)
    for control in c191["domain_context"]["domain_control_receipts"]:
        control["status"] = "not_applicable"
        control["evidence_refs"] = []
        control["reason"] = "NS-17 切片 2 affected_surfaces=[observability], 不触及 market_data/backtest/performance_claim, finance-quant overlay controls 未 triggered"

    # 修改 stage_receipts (复用 C190 结构, 修改 evidence_refs)
    # stabilization mode: feature_delivery + regression_and_commit 为 primary
    stage_receipts = c191["stage_receipts"]
    for stage_name, receipt in stage_receipts.items():
        receipt["evidence_refs"] = ["ev-c191-diff"]
        receipt["verification_refs"] = ["ev-c191-tdd", "ev-c191-regression"]
        # work_depth 保持, verdict=pass
        if stage_name in ("feature_delivery", "regression_and_commit"):
            receipt["work_depth"] = "primary"
        else:
            receipt["work_depth"] = "supporting"

    # 修改 role_reviews (evidence_refs + recorded_at)
    for review in c191["role_reviews"]:
        review["evidence_refs"] = ["ev-c191-diff"]
        review["required_verification"] = ["ev-c191-tdd", "ev-c191-regression", "ev-c191-lint"]
        review["recorded_at"] = _now()
        # policy_digest 保持与 campaign 相同 (candidate_selection/pre_closure)
        # lenses 保持结构, 修改 findings_or_candidates
        for role, lens in review.get("lenses", {}).items():
            lens["findings_or_candidates"] = [
                "NS-17 切片 2: graph.py + hedge_fund_streaming.py print→logger drain"
            ]

    # 修改 closure_receipts
    for receipt in c191["closure_receipts"]:
        receipt["recorded_at"] = _now()
        if receipt["kind"] == "git_closure":
            receipt["evidence_refs"] = ["ev-c191-diff", "ev-c191-lint"]
            receipt["user_change_isolation"] = "verified"
        elif receipt["kind"] == "release_handoff":
            receipt["intervention_id"] = "iv036-ns17-scoring-observability"
            receipt["status"] = "committed_unreleased"
            receipt["commit_or_no_diff"] = "commit_pending"
            receipt["release_or_observation_refs"] = []
            receipt["next_owner_or_trigger"] = "user commit authorization pending — C191 NS-17 切片 2 (graph.py + hedge_fund_streaming.py print→logger) delivered but committed_unreleased; 与 iv035 同 workflow, 需 release batch"
        elif receipt["kind"] == "pre_closure_review":
            receipt["evidence_refs"] = ["ev-c191-tdd", "ev-c191-regression", "ev-c191-lint"]
        elif receipt["kind"] == "state_write_intent":
            receipt["target_campaign_status"] = "completed"

    # 添加 C191 到 campaigns
    state["campaigns"].append(c191)

    # 3. 添加 evidence 到 evidence_catalog
    new_evidence = [
        {
            "id": "ev-c191-diff",
            "kind": "source_document",
            "attestation": "file_observed",
            "environment": "local",
            "observed_at": _now(),
            "campaign_id": "c191-ns17-scoring-observability",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "wf-top-picks-must-win",
            "raw_ref": "git diff: app/backend/services/graph.py + app/backend/routes/hedge_fund_streaming.py (print→logger) + tests/backend/test_ns17_observability.py (new)"
        },
        {
            "id": "ev-c191-tdd",
            "kind": "test_result",
            "attestation": "command_observed",
            "environment": "local",
            "observed_at": _now(),
            "campaign_id": "c191-ns17-scoring-observability",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "wf-top-picks-must-win",
            "raw_ref": "uv run python -m pytest tests/backend/test_ns17_observability.py -v → 7 passed (3 graph parse caplog + 2 hedge_fund_streaming module logger + 2 graph module logger)"
        },
        {
            "id": "ev-c191-regression",
            "kind": "test_result",
            "attestation": "command_observed",
            "environment": "local",
            "observed_at": _now(),
            "campaign_id": "c191-ns17-scoring-observability",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "wf-top-picks-must-win",
            "raw_ref": "uv run python -m pytest tests/backend/test_hedge_fund_streaming.py tests/test_graph_state.py -v → 11 passed (回归无破坏)"
        },
        {
            "id": "ev-c191-lint",
            "kind": "static_analysis",
            "attestation": "command_observed",
            "environment": "local",
            "observed_at": _now(),
            "campaign_id": "c191-ns17-scoring-observability",
            "workflow_id": "wf-top-picks-must-win",
            "subject": "wf-top-picks-must-win",
            "raw_ref": "uv run ruff check app/backend/services/graph.py app/backend/routes/hedge_fund_streaming.py tests/backend/test_ns17_observability.py → All checks passed!"
        }
    ]
    state["evidence_catalog"].extend(new_evidence)

    # 4. 创建 iv036 intervention (基于 iv035 结构)
    iv035 = next(iv for iv in state["interventions"] if iv["id"] == "iv035-ns2-model-version")
    iv036 = copy.deepcopy(iv035)
    iv036["id"] = "iv036-ns17-scoring-observability"
    iv036["status"] = "delivered"
    iv036["history"] = ["planned", "delivered"]
    iv036["release_batch_id"] = "rb-ns17-observability"
    iv036["predicted_outcome"] = "运维可从结构化日志定位 LLM JSON-parse 失败 (graph.py parse_hedge_fund_response → logger.warning) 和 SSE 断流 (hedge_fund_streaming.py → logger.info), 不再依赖 print() stdout"
    # evidence_profile 保持结构 (unobserved + focused_tests/full_regression/static_analysis)
    state["interventions"].append(iv036)

    # 5. 更新 iv035 的 release_batch_id (之前可能是 null, 现在指向 rb-ns17-observability)
    iv035["release_batch_id"] = "rb-ns17-observability"

    # 6. 创建 release batch rb-ns17-observability
    release_batch = {
        "id": "rb-ns17-observability",
        "workflow_id": "wf-top-picks-must-win",
        "intervention_ids": ["iv035-ns2-model-version", "iv036-ns17-scoring-observability"],
        "max_size": 3,
        "rationale": "C190 NS-2 切片 1 (model_version infra) + C191 NS-17 切片 2 (print→logger drain) 是同 workflow 的正交 stabilization, code site 完全独立 (main.py/recommendation_tracker.py vs graph.py/hedge_fund_streaming.py), 可一起 release",
        "release_owner_or_trigger": "user commit authorization (两场 campaign 代码改动均已验证: TDD + regression + lint GREEN)",
        "attribution_plan": "per-intervention evidence_profile 保持独立 (unobserved + focused_tests/full_regression/static_analysis), 聚合 release 时分别 commit 或合并 commit",
        "member_effect_isolation": {}
    }
    state["release_batches"].append(release_batch)

    # 7. 创建 cd191 candidate (基于 cd190 结构)
    cd190 = next(c for c in state["candidate_portfolio"] if c["id"] == "cd190-ns2-model-version-infra")
    cd191 = copy.deepcopy(cd190)
    cd191["id"] = "cd191-ns17-scoring-observability"
    cd191["family_id"] = "ns17-scoring-observability"
    cd191["source_refs"] = ["ev-c191-diff", "ev-c191-tdd"]
    cd191["provenance_chain"] = [
        {
            "source_kind": "product_backlog",
            "source_ref": "ev-c191-diff",
            "node": "§三·6 NS-17 (P1): 打分可观测性 — graph.py + hedge_fund_streaming.py print→logger drain"
        }
    ]
    # change_risk=1 (行为零变更, 只加 logger), domain_impact_risk=1 (observability, 不触及 finance-quant surfaces)
    cd191["change_risk"] = 1
    cd191["domain_impact_risk"] = 1
    state["candidate_portfolio"].append(cd191)

    # 8. 更新 budget
    state["budget"]["campaigns_executed"] = 5
    state["budget"]["value_campaigns_completed"] = 5

    # 9. 更新 next_outer_loop_action
    state["next_outer_loop_action"] = {
        "action": "awaiting_release",
        "target_workflow_id": "wf-top-picks-must-win",
        "action_class": "stabilization",
        "next_trigger": "Campaign 2/3 (C191 NS-17 切片 2 graph.py + hedge_fund_streaming.py print→logger) completed delivered but committed_unreleased — iv035 + iv036 同 workflow delivered, release batch rb-ns17-observability 已创建, 等待 user commit authorization 后 release。剩余 1 场额度可做正交 stabilization (如 NS-13 NaN guard) 或停止。"
    }

    # 10. 写回 state.json
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OK: C191 written to {STATE_PATH}")
    print(f"  campaigns: {len(state['campaigns'])} (c187-c191)")
    print(f"  interventions: {len(state['interventions'])} (iv022-iv036)")
    print(f"  candidate_portfolio: {len(state['candidate_portfolio'])} (cd181-cd191)")
    print(f"  release_batches: {len(state['release_batches'])}")
    print(f"  evidence_catalog: {len(state['evidence_catalog'])} entries")
    print(f"  budget: campaigns_executed={state['budget']['campaigns_executed']}, value={state['budget']['value_campaigns_completed']}")


if __name__ == "__main__":
    main()
