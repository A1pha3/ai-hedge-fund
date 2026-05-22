# btst-5d15-boundary-contract-inspection-2026-05-22

## 原理
- 本轮不是继续挖 alpha，也不是重构整个 pipeline，而是只检查 `short_trade_boundary` 和 `layer_b_boundary` 为什么会输出 metadata-only explainability payload，却不输出 round1 核心因子键。
- 结论只基于 `data/reports/btst_5d_15pct_boundary_contract_inspection_latest.json` 与同名 Markdown，不把这次 contract inspection 当成 runtime 升级结论。

## source comparison
- `short_trade_boundary`：75 行，决策以 `rejected` 和 `near_miss` 为主，`metadata_only_rate=1.0`，`core_payload_empty_count=75`，contract verdict 是 `metadata_only_boundary_contract`。
- `layer_b_boundary`：46 行，全部是 `rejected`，`metadata_only_rate=1.0`，`core_payload_empty_count=46`，contract verdict 也是 `metadata_only_boundary_contract`。
- 两个 source 的前五个 metadata key 基本一致：`available_strategy_signals`、`bc_conflict`、`candidate_source`、`layer_c_decision`、`replay_context`。这说明当前问题不是单个 source 偶发缺字段，而是边界 contract 整体只给了元数据，没有给 round1 核心结构。

## alpha 结论
- alpha 视角下，这 121 行边界样本不是“潜在强因子被漏算”，而是压根没有进入可用于 round1 排行的结构面。
- 因此这一轮工作的价值在于清理研究面污染，而不是提高当前 5D/+15% 命中率。

## beta 结论
- beta 视角下，`short_trade_boundary` 和 `layer_b_boundary` 现在都更像 fixable contract gap，而不是独立 alpha 面。
- 下一步应先追边界 source 为什么只输出 metadata-only key 集，而不是继续把这些样本混进因子研究面。

## gamma 结论
- gamma 当前批准的治理动作是统一的：`fix_candidate_source_contract`。
- 在合约修好之前，这两个 boundary source 不应该继续被当作可解释的 factor surface 输入。

## 下一轮动作
- 直接围绕 boundary candidate-source contract 做检查与修复验证，优先确认为什么 round1 核心键没有出现在 explainability payload 中。
- 在 contract 没有修好之前，保持 fail-closed，不把这两个 boundary source 当成可用 alpha surface。
- 暂不推进任何内容到 `docs/prompt/find_actor/`，也不接入 `ai-hedge-fund-btst`。
