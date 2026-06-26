"""AutoDev C191 surgical patch — fix stage_receipts work_depth + C190→C191 evidence refs.

This patches the existing C191 in state.json in place (no duplication). The
original writer script (_autodev_c191_state.py) was run once with a buggy
work_depth rule that set bug_hunt=primary + feature_delivery=supporting,
but delivery mode requires feature_delivery + regression_and_commit as primary.

Also fixes semantic accuracy: C191 inherited C190's evidence refs in several
fields (evidence_profile.verification_evidence_refs, stages[].evidence_refs,
state_write_intent.evidence_refs) — rewrite them to point at ev-c191-* evidence.

Usage: uv run python scripts/_autodev_c191_patch.py
"""

from __future__ import annotations

import json
from pathlib import Path

STATE_PATH = Path(".autodev/state.json")

C191_ID = "c191-ns17-scoring-observability"


def main() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    c191 = next(c for c in state["campaigns"] if c["id"] == C191_ID)

    fixes: list[str] = []

    # --- Fix 1: stage_receipts work_depth (delivery mode primary set) ---
    # delivery mode primary = {feature_delivery, regression_and_commit}
    expected_primary = {"feature_delivery", "regression_and_commit"}
    stage_receipts = c191["stage_receipts"]
    for stage_name, receipt in stage_receipts.items():
        if stage_name in expected_primary:
            if receipt.get("work_depth") != "primary":
                receipt["work_depth"] = "primary"
                fixes.append(f"stage_receipts.{stage_name}.work_depth → primary")
        else:
            if receipt.get("work_depth") != "supporting":
                receipt["work_depth"] = "supporting"
                fixes.append(f"stage_receipts.{stage_name}.work_depth → supporting")

    # --- Fix 2: stage_receipts scan_scope (currently references NS-2 model_version) ---
    stage_receipts["bug_hunt"]["scan_scope"] = (
        "app/backend/services/graph.py parse_hedge_fund_response + "
        "app/backend/routes/hedge_fund_streaming.py SSE cancel — no bugs (observability drain, not bug fix)"
    )
    stage_receipts["refactor_batch"]["scan_scope"] = (
        "no refactor — delivery only (add module logger + print→logger drain); "
        "no helper extraction needed"
    )
    stage_receipts["product_quality_upgrade"]["scan_scope"] = (
        "no product quality upgrade — delivery only (observability is prerequisite "
        "for NS-17 score breakdown, not itself a quality upgrade)"
    )
    stage_receipts["feature_delivery"]["scan_scope"] = (
        "app/backend/services/graph.py: module logger + 3 print()→logger.warning "
        "(JSONDecodeError/TypeError/Exception in parse_hedge_fund_response); "
        "app/backend/routes/hedge_fund_streaming.py: module logger + 6 print()→logger.info "
        "(SSE disconnect/cancel/generator-cancel for hedge fund run + backtest); "
        "tests/backend/test_ns17_observability.py: 7 TDD caplog guards"
    )
    stage_receipts["regression_and_commit"]["scan_scope"] = (
        "tests/backend/test_ns17_observability.py (7 tests) + "
        "tests/backend/test_hedge_fund_streaming.py + tests/test_graph_state.py (regression) + ruff"
    )
    fixes.append("stage_receipts.*.scan_scope → NS-17 scope")

    # --- Fix 3: stage_receipts exhaustion_or_blocker (currently references NS-2 model_version) ---
    stage_receipts["bug_hunt"]["exhaustion_or_blocker"] = (
        "not applicable — delivery mode, no bug hunt; observability gap is missing-feature "
        "(no module logger / structured logging) not a bug"
    )
    stage_receipts["refactor_batch"]["exhaustion_or_blocker"] = (
        "not applicable — delivery mode, no refactor batch"
    )
    stage_receipts["product_quality_upgrade"]["exhaustion_or_blocker"] = (
        "not applicable — delivery mode, no product quality upgrade"
    )
    stage_receipts["feature_delivery"]["exhaustion_or_blocker"] = (
        "delivery complete — graph.py: module logger + 3 print()→logger.warning "
        "(parse_hedge_fund_response JSONDecodeError/TypeError/Exception); "
        "hedge_fund_streaming.py: module logger + 6 print()→logger.info "
        "(SSE disconnect/cancel/generator-cancel for hedge fund run + backtest). "
        "7 TDD caplog guards verify structured logging + no remaining print()."
    )
    stage_receipts["regression_and_commit"]["exhaustion_or_blocker"] = (
        "7 passed in test_ns17_observability, 11 passed regression "
        "(test_hedge_fund_streaming + test_graph_state), 0 lint issues — "
        "commit pending user authorization (committed_unreleased)"
    )
    fixes.append("stage_receipts.*.exhaustion_or_blocker → NS-17 outcome")

    # --- Fix 4: stages array evidence_refs + scan_scope (currently references C190) ---
    stages = c191["stages"]
    for stage in stages:
        stage["evidence_refs"] = ["ev-c191-diff"]
        stage["verification_refs"] = ["ev-c191-tdd", "ev-c191-regression"]
    # update scan_scope per stage
    stages[0]["scan_scope"] = stage_receipts["bug_hunt"]["scan_scope"]  # bug_hunt
    stages[1]["scan_scope"] = stage_receipts["refactor_batch"]["scan_scope"]  # refactor_batch
    stages[2]["scan_scope"] = stage_receipts["product_quality_upgrade"]["scan_scope"]
    stages[3]["scan_scope"] = stage_receipts["feature_delivery"]["scan_scope"]
    stages[4]["scan_scope"] = stage_receipts["regression_and_commit"]["scan_scope"]
    # exhaustion_or_blocker per stage
    stages[0]["exhaustion_or_blocker"] = stage_receipts["bug_hunt"]["exhaustion_or_blocker"]
    stages[1]["exhaustion_or_blocker"] = stage_receipts["refactor_batch"]["exhaustion_or_blocker"]
    stages[2]["exhaustion_or_blocker"] = stage_receipts["product_quality_upgrade"]["exhaustion_or_blocker"]
    stages[3]["exhaustion_or_blocker"] = stage_receipts["feature_delivery"]["exhaustion_or_blocker"]
    stages[4]["exhaustion_or_blocker"] = stage_receipts["regression_and_commit"]["exhaustion_or_blocker"]
    fixes.append("stages[].evidence_refs/scan_scope/exhaustion_or_blocker → NS-17")

    # --- Fix 5: evidence_profile.verification_evidence_refs (currently ev-c190-*) ---
    c191["evidence_profile"]["verification_evidence_refs"] = [
        "ev-c191-tdd",
        "ev-c191-regression",
        "ev-c191-lint",
    ]
    fixes.append("evidence_profile.verification_evidence_refs → ev-c191-*")

    # --- Fix 6: domain_context.detection_evidence_refs (currently ev-c190-owner) ---
    c191["domain_context"]["detection_evidence_refs"] = ["ev-c191-diff"]
    fixes.append("domain_context.detection_evidence_refs → ev-c191-diff")

    # --- Fix 7: state_write_intent.evidence_refs (currently ev-c190-*) ---
    for receipt in c191["closure_receipts"]:
        if receipt["kind"] == "state_write_intent":
            receipt["evidence_refs"] = ["ev-c191-tdd", "ev-c191-regression", "ev-c191-lint"]
            fixes.append("closure.state_write_intent.evidence_refs → ev-c191-*")
            break

    # --- Fix 8: design_decision_packet (currently NS-2 model_version — wrong campaign) ---
    c191["design_decision_packet"] = {
        "problem": (
            "graph.py parse_hedge_fund_response 的 3 处 print() (JSONDecodeError/TypeError/Exception) "
            "和 hedge_fund_streaming.py 的 6 处 print() (SSE disconnect/cancel/generator-cancel) "
            "都吞错误/事件不入结构化日志 — 运维无法从 logs 定位 LLM JSON-parse 失败和 SSE 断流"
        ),
        "invariants": [
            "行为零变更 (parse_hedge_fund_response 仍返回 None, SSE cancel 仍 return/cancel)",
            "只增加结构化日志输出 (logger.warning for parse errors, logger.info for SSE events)",
            "module logger 命名遵循 logging.getLogger(__name__) 约定",
        ],
        "options": [
            "A: print() → logger (warning for errors, info for normal events) — 标准库 logging, 零新依赖, 行为零变更, 运维可从 logs 定位",
            "B: print() → structlog — 更结构化但需引入新依赖, 超出 NS-17 切片范围",
            "C: print() → 完全删除 — 损失可观测性, 不可取",
        ],
        "recommendation": (
            "A — print() → logging.getLogger(__name__). warning 级别用于 parse 失败 "
            "(异常路径), info 级别用于 SSE cancel (正常运行事件). 零新依赖, 行为零变更."
        ),
        "acceptance_tests": [
            "parse_hedge_fund_response JSONDecodeError 时 logger.warning 被调用 (caplog)",
            "parse_hedge_fund_response TypeError 时 logger.warning 被调用 (caplog)",
            "parse_hedge_fund_response valid JSON 时不触发 warning (caplog)",
            "hedge_fund_streaming module logger 存在 + 无剩余 print()",
            "graph module logger 存在 + 无剩余 print()",
        ],
        "rollback": (
            "删除两个文件的 module logger 声明 + 把 logger.warning/logger.info 改回 print() "
            "+ 删除 tests/backend/test_ns17_observability.py 即完全回滚"
        ),
        "decision_authority": "engineering (实现选择, 非产品语义/公开契约)",
        "next_trigger": (
            "NS-17 后续切片: signal_fusion.py per-ticker DEBUG score breakdown 已实施 "
            "(line 503-518), 如需进一步可观测性可考虑 logger → structlog 升级"
        ),
    }
    fixes.append("design_decision_packet → NS-17 print→logger")

    # --- Fix 9: risk_profile (currently NS-2 model_version risk — wrong campaign) ---
    c191["risk_profile"] = {
        "blast_radius": 1,
        "design_uncertainty": 1,
        "contract_ambiguity": 1,
        "verification_gap": 0,
        "rollback_difficulty": 1,
        "migration_risk": 1,
    }
    fixes.append("risk_profile → NS-17 (blast_radius=1, observability drain)")

    # --- Fix 10: change_risk (currently 2 from C190 — should be 1 for observability) ---
    c191["change_risk"] = 1
    fixes.append("change_risk → 1 (observability drain, zero behavior change)")

    # --- Fix 11: role_reviews scope + review_delta (currently NS-2 model_version) ---
    reviews = c191["role_reviews"]
    reviews[0]["scope"] = "NS-17 打分可观测性切片 2 — graph.py + hedge_fund_streaming.py print→logger drain"
    reviews[0]["review_delta"] = (
        "Outcome Review: iv035 (NS-2 model_version infra) delivered but committed_unreleased. "
        "iv034-iv028 all released. NS-17 切片 1 (signal_fusion.py per-ticker DEBUG score breakdown) "
        "已实施 (line 503-518). 切片 2 候选: graph.py + hedge_fund_streaming.py print→logger — "
        "正交 code site, action_class=stabilization 可继续 (不在 {delivery,discovery,full_audit})."
    )
    reviews[1]["scope"] = "Select cd191-ns17-scoring-observability from backlog (NS-17 切片 2: print→logger drain)"
    reviews[1]["review_delta"] = (
        "Candidate selected from active backlog (NS-17, P1). source_kind=product_backlog (authoritative). "
        "design_decision_packet resolved Option A (print→logging.getLogger) over B (structlog, 新依赖) "
        "and C (delete, 损失可观测性) — engineering-owned decision. Slice 2 only: graph.py + "
        "hedge_fund_streaming.py; signal_fusion.py 切片 1 已实施."
    )
    reviews[2]["scope"] = (
        "TDD plan: 7 tests for NS-17 切片 2 (3 graph parse_hedge_fund_response caplog + "
        "2 hedge_fund_streaming module logger + 2 graph module logger)"
    )
    reviews[2]["review_delta"] = (
        "RED confirmed (test_ns17_observability.py 7 tests fail before implementation). "
        "Implementation plan: (1) graph.py 加 module logger + parse_hedge_fund_response "
        "3 处 print()→logger.warning (JSONDecodeError/TypeError/Exception); "
        "(2) hedge_fund_streaming.py 加 module logger + 6 处 print()→logger.info "
        "(SSE disconnect/cancel/generator-cancel for hedge fund run + backtest). "
        "Behavior zero change (仍 return None / cancel)."
    )
    reviews[3]["scope"] = "Final review: 7 tests GREEN + 11 regression + lint clean"
    reviews[3]["review_delta"] = (
        "GREEN: 7/7 focused tests pass (test_ns17_observability.py). REGRESSION: 11 passed "
        "(test_hedge_fund_streaming.py + test_graph_state.py). LINT: ruff All checks passed. "
        "Diff: 2 src files + 1 new test file. User-change isolation: verified. No residual blockers."
    )
    fixes.append("role_reviews.scope + review_delta → NS-17")

    # --- Write back ---
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OK: patched {C191_ID} in {STATE_PATH}")
    print(f"  {len(fixes)} fixes applied:")
    for fix in fixes:
        print(f"    - {fix}")


if __name__ == "__main__":
    main()
