# btst-5d15-boundary-contract-fill-path-2026-05-22

## 背景与范围

- 本轮工作是在边界契约检查（boundary contract inspection，任务 1/2）完成后，对同一批 121 行边界样本执行补全路径（fill-path）修复，并记录尝试过程与结果。
- 补全路径（fill-path）的目的不是“修好就放行”，而是**确认哪些行可以回收进入研究面、哪些行必须永久隔离**。结论完全由 `repair_status` 分布决定，不做主观放宽。
- 数据来源为 `data/reports/btst_5d_15pct_boundary_contract_fill_path_latest.json` 及其同名 Markdown；本次补全路径修复不应被视为运行时升级结论。

## 补全路径修复结果

- **总计 121 行**（其中 `short_trade_boundary` 75 行，`layer_b_boundary` 46 行）。
- **`fully_repaired_boundary_contract = 0`**：没有任何一行在 `boundary_context` 中同时覆盖全部 7 个核心因子键。
- **`partially_repaired_boundary_contract = 121`**：所有行的 `boundary_context` 中都仅存在 1 个非 `None` 因子键，即 `t0_tail_strength`。其余 6 个键——`breakout_freshness`、`trend_acceleration`、`volume_expansion_quality`、`close_strength`、`trend_continuation`、`short_term_reversal`——在每一行中均为 `None`，因此没有进入 `boundary_context`。
- **`irrecoverable_boundary_contract = 0`**：由于每一行都携带 `t0_tail_strength`，没有样本被判定为完全不可回收。

### 两个来源的修复分布
| 来源（`candidate_source`） | 行数 | 完全修复（`fully_repaired`） | 部分修复（`partially_repaired`） | 不可恢复（`irrecoverable`） |
|---|---:|---:|---:|---:|
| `short_trade_boundary` | 75 | 0 | 75 | 0 |
| `layer_b_boundary` | 46 | 0 | 46 | 0 |

## Alpha 视角

- 从 Alpha 角度看，121 行样本中 `t0_tail_strength` 是当前唯一可恢复的非 `None` 因子。其余 6 个核心键之所以不在 `boundary_context` 中，是因为在 inspection 阶段，这些因子在 `selection_snapshot` 中本来就是 `None`；而 `boundary_context` 的构建逻辑只会收集非 `None` 字段。
- **这 121 行样本不具备进入 round1 因子排行面的条件**。仅凭 `t0_tail_strength` 无法重建完整的选股逻辑。
- partial repair 不等于 Alpha 信号恢复，不应把这些样本当作“有潜力的候选”继续研究。

## Beta 视角

- 从 Beta 视角看，补全路径已经明确了两个 boundary source 当前的修复上限：只有 1 个因子可以回收，修复深度非常有限。
- 这说明边界契约缺口（contract gap）的根因在上游：这些 ticker 为什么在 snapshot 生成时就已经变成 `None` 因子，而不是补全路径层面可以独立解决的问题。
- 当前治理动作应继续维持 **`hold_boundary_repair_until_more_context`**，等待上游契约修复后，再重新对这批样本执行补全路径。

## Gamma 视角

- Gamma 当前批准的治理动作是：`hold_boundary_repair_until_more_context`。
- 触发条件为：121 行全部是 partial repair，没有 fully repaired，也没有 irrecoverable。
- 在 `fully_repaired` 数量大于 0 之前，这批 partial repair 样本仅可用于**离线研究参考**（例如观察 `t0_tail_strength` 的分布范围），不能用于实盘候选筛选或 Alpha 验证。

## 默认关闭（fail-closed）说明

- 本次补全路径结果为 **默认关闭（fail-closed）**：没有任何一行被允许进入正式的 Alpha 因子表层。
- partial repair 样本的唯一合法用途是：
  1. 追踪上游 snapshot 中为何有 6 个核心因子为 `None`，作为契约缺口的诊断证据；
  2. 观察 `t0_tail_strength` 在边界样本中的分布，作为后续契约修复的验证对照组。
- 不得将任何内容推进到 `docs/prompt/find_actor/`，也不得接入 `ai-hedge-fund-btst` 实盘流程。

## 下一轮动作

- 优先追查上游 snapshot 中 `breakout_freshness`、`trend_acceleration` 等 6 个因子为何为 `None`；这是 boundary contract 的根本缺口。
- 待上游契约修复并重新生成 snapshot 后，重跑 inspection + fill-path 全链路，确认 `fully_repaired` 数量是否大于 0。
- 在此之前，继续保持默认关闭（fail-closed），不推进任何边界表层（boundary surface）内容。
