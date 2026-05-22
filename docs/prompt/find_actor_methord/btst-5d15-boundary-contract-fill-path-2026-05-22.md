# btst-5d15-boundary-contract-fill-path-2026-05-22

## 原理

- 本轮是在 boundary-contract inspection（Task 1/2）完成之后，对同一批 121 行边界样本执行 repair fill-path 的尝试与结果记录。
- fill-path 的目的不是"修好就放行"，而是 **确认哪些行可以被回收为研究面，哪些行必须永久隔离**。结论完全取决于 repair_status 分布，不主观判断。
- 数据来源：`data/reports/btst_5d_15pct_boundary_contract_fill_path_latest.json` 与同名 Markdown，不把这次 fill-path 当成 runtime 升级结论。

## fill-path 修复结果

- **总计 121 行**（75 行来自 `short_trade_boundary`，46 行来自 `layer_b_boundary`）。
- **fully_repaired_boundary_contract = 0**：没有任何一行在 `boundary_context` 中同时覆盖全部 7 个核心因子键。
- **partially_repaired_boundary_contract = 121**：所有行的 `boundary_context` 里都存在且只存在 1 个非 None 因子键：`t0_tail_strength`。其余 6 个键（`breakout_freshness`、`trend_acceleration`、`volume_expansion_quality`、`close_strength`、`trend_continuation`、`short_term_reversal`）在每一行里均为 None，因此未进入 `boundary_context`。
- **irrecoverable_boundary_contract = 0**：由于每行都携带了 `t0_tail_strength`，没有行被判为完全不可回收。

### 两个 source 的修复分布
| candidate_source | 行数 | fully_repaired | partially_repaired | irrecoverable |
|---|---|---|---|---|
| short_trade_boundary | 75 | 0 | 75 | 0 |
| layer_b_boundary | 46 | 0 | 46 | 0 |

## alpha 结论

- 从 alpha 角度，121 行样本中 `t0_tail_strength` 是当前唯一可恢复的非 None 因子。其余 6 个核心键之所以不在 `boundary_context` 中，是因为在 inspection 阶段这些因子在 `selection_snapshot` 里本来就是 None，`boundary_context` 的构建逻辑只会收集 non-None 字段。
- **这 121 行样本不具备进入 round1 因子排行面的条件**。单靠 `t0_tail_strength` 无法重建完整的选股逻辑。
- partial repair 不等于 alpha 信号恢复，不应当把这些行当成"有潜力的候选"来进一步研究。

## beta 结论

- beta 视角下，fill-path 明确了两个 boundary source 当前的修复天花板：只有 1 个因子可回收，修复深度极浅。
- 这说明边界 contract gap 的根本原因在上游（为什么这些 ticker 在 snapshot 生成时就已经是 None 因子），而不在 fill-path 层面可以解决。
- 当前治理动作应维持 **`hold_boundary_repair_until_more_context`**，等待上游 contract 修复后重新对这批样本执行 fill-path。

## gamma 结论

- gamma 当前批准的治理动作是：`hold_boundary_repair_until_more_context`。
- 触发条件：所有 121 行均为 partial repair，无 fully repaired，无 irrecoverable。
- 在 fully_repaired 数量 > 0 之前，这批 partial repair 样本仅可用于 **离线研究参考**（即了解 `t0_tail_strength` 的分布范围），不可用于实盘候选筛选或 alpha 验证。

## fail-closed 说明

- 本次 fill-path 结果是 **fail-closed**：没有任何一行被允许进入正式 alpha surface。
- partial repair 样本的唯一合法用途是：
  1. 追踪上游 snapshot 中为什么 6 个核心因子是 None（contract gap 诊断证据）。
  2. 观察 `t0_tail_strength` 在边界样本中的分布，作为后续 contract 修复的验证对照组。
- 不得将任何内容推进到 `docs/prompt/find_actor/`，不接入 `ai-hedge-fund-btst` 实盘流程。

## 下一轮动作

- 优先追查上游 snapshot 中 `breakout_freshness`、`trend_acceleration` 等 6 个因子为何为 None——这是 boundary contract 的根本缺口所在。
- 待上游 contract 修复、重新生成 snapshot 后，重跑 inspection + fill-path 完整路径，确认 fully_repaired 数量是否 > 0。
- 在此之前，保持 fail-closed，不推进任何 boundary surface 内容。
