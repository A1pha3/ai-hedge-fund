# btst-5d15-boundary-contract-inspection-2026-05-22

## 背景与范围
- 本轮工作不是继续挖掘 Alpha，也不是重构整个流水线（pipeline），而是聚焦检查 `short_trade_boundary` 与 `layer_b_boundary`：为什么它们只输出仅含元数据的可解释性载荷（metadata-only explainability payload），却没有输出 round1 所需的核心因子键。
- 全部结论仅基于 `data/reports/btst_5d_15pct_boundary_contract_inspection_latest.json` 及其同名 Markdown；本次边界契约检查（boundary contract inspection）不应被解读为运行时升级结论。

## 来源对比
- `short_trade_boundary`：共 75 行，决策以 `rejected` 和 `near_miss` 为主，`metadata_only_rate=1.0`，`core_payload_empty_count=75`，契约判定为 `metadata_only_boundary_contract`。
- `layer_b_boundary`：共 46 行，全部为 `rejected`，`metadata_only_rate=1.0`，`core_payload_empty_count=46`，契约判定同样为 `metadata_only_boundary_contract`。
- 两个来源前五个元数据键基本一致：`available_strategy_signals`、`bc_conflict`、`candidate_source`、`layer_c_decision`、`replay_context`。这说明当前问题不是单一来源偶发缺字段，而是边界契约整体只提供元数据，没有提供 round1 所需的核心结构。

## Alpha 视角
- 从 Alpha 视角看，这 121 行边界样本并不是“潜在强因子被漏算”，而是根本没有进入可用于 round1 排行的结构层。
- 因此，本轮工作的价值在于清理研究面污染，而不是提升当前 5D/+15% 的命中率。

## Beta 视角
- 从 Beta 视角看，`short_trade_boundary` 与 `layer_b_boundary` 更像是可修复的契约缺口（fixable contract gap），而不是独立的 Alpha 因子表层。
- 下一步应优先追查边界来源为何只输出 metadata-only 键集合，而不是继续把这批样本混入因子研究面。

## Gamma 视角
- Gamma 当前批准的统一治理动作是：`fix_candidate_source_contract`。
- 在契约修复完成之前，这两个边界来源（boundary source）不应继续作为可解释的因子表层（factor surface）输入。

## 下一轮动作
- 直接围绕边界候选来源契约（boundary candidate-source contract）开展检查与修复验证，优先确认 round1 核心键为何没有出现在可解释性载荷（explainability payload）中。
- 在契约未修复之前，继续保持默认关闭（fail-closed），不把这两个边界来源（boundary source）视为可用的 Alpha 因子表层。
- 暂不将任何内容推进到 `docs/prompt/find_actor/`，也不接入 `ai-hedge-fund-btst`。
