# btst-boundary-upstream-contract-repair-2026-05-22

## 结论

- 本轮工作是 **upstream boundary contract repair**，不是 alpha 因子优化，不是 skill wiring，也不是 `docs/prompt/find_actor/` 的 promotion。
- 目标是让 `short_trade_boundary` / `layer_b_boundary` 在源头稳定输出 inspection 与 round1 需要的 core explainability surface，尽量减少同一批样本继续落入 `boundary_without_explainability`。
- quarantine 仍然保留为 fail-closed backstop；本轮重点是把上游 contract 修正到位，而不是把治理责任继续下放给后置隔离。

## 这轮解决什么

1. 统一 short-trade boundary 的 canonical payload，让核心 explainability keys 在 inspection 路径上可见且可验证。
2. 让 downstream candidate helper 继续使用同一套 precedence / backfill 规则，避免 contract 在不同 surface 上出现漂移。
3. 让 inspection / quarantine / round1 三个既有 surface 继续作为回归观测面，用来确认 repaired cohort 是否收缩。

## 如何验证

1. `uv run pytest tests/targets/test_short_trade_boundary_contract_helpers.py tests/targets/test_short_trade_target_snapshot_payload_helpers.py tests/execution/test_daily_pipeline_candidate_helpers.py tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py -q`
2. `uv run python scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py`
3. `uv run python scripts/analyze_btst_5d_15pct_boundary_quarantine.py`

## fail-closed 说明

- 如果源头仍然缺少 core explainability keys，就继续保持缺失并让 inspection / quarantine 暴露问题，不能伪造默认值。
- quarantine 只负责隔离和治理，不代表这些样本已经修好，也不代表它们可以回流为可用 surface。
- 只有在 upstream contract 修复后，且 inspection / quarantine / round1 重新验证通过，才允许重新讨论释放。

## 范围边界

- 本轮只处理 upstream boundary contract repair 与诊断验证，不做因子晋升。
- 本轮不接入 `docs/prompt/find_actor/`，不触碰 skill wiring，不定义 round2 消费策略。
- 这是 diagnosis-only note，保留在 `docs/prompt/find_actor_methord/`。
