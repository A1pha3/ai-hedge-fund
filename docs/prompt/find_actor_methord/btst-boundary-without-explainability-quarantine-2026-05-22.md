# btst-boundary-without-explainability-quarantine-2026-05-22

## 结论

- 本轮工作是 **research-surface quarantine**，不是 alpha 因子优化，也不是运行时放量升级。
- 目标是把 `boundary_without_explainability` 这 **121 行样本**显式隔离出 round1/round2 因子研究面，避免继续污染研究结论。
- 任何进入 `quarantine` 或 `separate_surface` 的 ticker，都不能推进到 `docs/prompt/find_actor/`，也不能接入 `ai-hedge-fund-btst`。
- **本轮不处理 round2 consumption；round2 如何消费这批隔离样本，刻意留到后续周期单独决策。**

## 这轮解决什么

1. 把 `boundary_contract_inspection` 的结果转成可消费的 quarantine artifact，让 `boundary_without_explainability` 不再只是诊断现象。
2. 让 round1 因子研究默认跳过被 quarantine 的样本，避免 121 行 metadata-only / explainability 缺失样本继续混入研究面。
3. 保持 fill-path 仍然只做后置验证，不承担研究面清洗；是否释放样本，不能由 fill-path 单独决定。

## 如何验证

1. `uv run pytest tests/test_btst_boundary_quarantine_helpers.py tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py tests/test_analyze_btst_5d_15pct_boundary_contract_fill_path_script.py tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py -q`
2. `uv run python scripts/analyze_btst_5d_15pct_boundary_quarantine.py`

## fail-closed 说明

- quarantine artifact 只用于隔离和治理，不代表这些样本已经修好，更不代表它们已经恢复为可用 alpha surface。
- 后续只有在上游 contract 修复并且 fill-path 重新验证通过后，才允许重新讨论是否释放回研究面。
- 任何处于 `quarantine` 或 `separate_surface` 的 ticker，在治理解除前都必须保持 fail-closed，不能进入 `docs/prompt/find_actor/`，也不能接入 `ai-hedge-fund-btst`。
- 本文档是 diagnosis-only note，不能进入 `docs/prompt/find_actor/`。

## 范围边界

- 本轮只解决 research-surface quarantine、round1 跳过隔离样本、以及 fill-path 保持后置验证这三件事。
- round2 consumption 明确不在本轮范围内；本轮不会定义 round2 应如何读取、放行或二次利用 quarantine artifact。
