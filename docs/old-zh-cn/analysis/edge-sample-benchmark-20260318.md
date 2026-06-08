# 2026-03-18 边缘样本基准：600519 与 300724 的统一验收口径

## 结论摘要

- 当前仓库里已经存在两类经过验证的边缘样本证据：
  - `600519`：历史 Layer C / watchlist 阈值边缘样本
  - `300724`：当前长窗口中的 re-entry 边缘样本
- 这两类样本应该被统一成后续最小实验的固定基准，而不是继续零散引用。
- 截至目前，适合作为后续最小参数实验硬性验收基线的边缘样本有且仅有三条：
  - `20260224 / 600519`
  - `20260226 / 600519`
  - `20260226 / 300724`

## 为什么需要统一基准

前面的分析已经给出两个关键事实：

1. 在 `2026-02-02 .. 2026-03-04` 长窗口里，真正的近阈值非冲突样本只有 `300724`
2. 历史上已经单独完成 live targeted replay 补证的 `600519`，是另一个明确的阈值边缘样本

因此，如果后续继续做“只释放边缘票、不放出结构性冲突票”的最小实验，就不应该每次重新选样本，而应统一使用固定边缘基准。

## 基准样本一：20260224 / 600519

证据来源：

- [ai-hedge-fund-fork/data/reports/live_replay_600519_20260224_p1.json](ai-hedge-fund-fork/data/reports/live_replay_600519_20260224_p1.json)
- [ai-hedge-fund-fork/docs/zh-cn/analysis/layer-b-p1-pr-summary-20260316.md](ai-hedge-fund-fork/docs/zh-cn/analysis/layer-b-p1-pr-summary-20260316.md)

关键事实：

- `score_b = 0.4023`
- `score_c = -0.0122`
- `score_final = 0.2158`
- `decision = watch`
- `bc_conflict = null`
- 实际跨过 `0.20` watchlist 门槛

agent 结构特征：

- `cohort_contributions.investor = -0.0122`
- `cohort_contributions.analyst = 0.0`
- 正负 agent 数量接近平衡：`positive = 4`, `negative = 4`, `neutral = 9`

业务含义：

- 这是一个“应该被放出”的边缘阈值样本
- 后续最小实验不能把它重新压回 watchlist 以下

## 基准样本二：20260226 / 600519

证据来源：

- [ai-hedge-fund-fork/data/reports/live_replay_600519_20260226_p1.json](ai-hedge-fund-fork/data/reports/live_replay_600519_20260226_p1.json)
- [ai-hedge-fund-fork/docs/zh-cn/analysis/layer-b-p1-pr-summary-20260316.md](ai-hedge-fund-fork/docs/zh-cn/analysis/layer-b-p1-pr-summary-20260316.md)

关键事实：

- `score_b = 0.3951`
- `score_c = -0.0469`
- `score_final = 0.1962`
- `decision = watch`
- `bc_conflict = null`
- 仍未跨过 `0.20` watchlist 门槛

agent 结构特征：

- `cohort_contributions.investor = -0.0469`
- `cohort_contributions.analyst = 0.0`
- `positive = 3`, `negative = 4`, `neutral = 10`

业务含义：

- 这是一个“边缘但仍应保持不过线”的样本
- 后续最小实验不能把它推到明显更激进的通过区间

## 基准样本三：20260226 / 300724

证据来源：

- [ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)
- [ai-hedge-fund-fork/docs/zh-cn/analysis/paper-trading-reentry-validation-20260317.md](ai-hedge-fund-fork/docs/zh-cn/analysis/paper-trading-reentry-validation-20260317.md)
- [ai-hedge-fund-fork/docs/zh-cn/analysis/paper-trading-edge-candidate-list-20260318.md](ai-hedge-fund-fork/docs/zh-cn/analysis/paper-trading-edge-candidate-list-20260318.md)

关键事实：

- `score_b = 0.4360`
- `score_c = -0.0328`
- `score_final = 0.2250`
- `decision = watch`
- `bc_conflict = null`
- 本身已进入 watchlist
- 在新规则下被 `blocked_by_reentry_score_confirmation` 拦下
- 要求分数：`0.25`

agent 结构特征：

- `cohort_contributions.investor = 0.0132`
- `cohort_contributions.analyst = -0.0460`
- 不是结构性冲突票

业务含义：

- 这是一个“边缘 watch 样本，但在防御性退出后不应立即回补”的样本
- 后续实验不能破坏当前 re-entry 保护逻辑，让它重新以 `0.2250` 这类分数直接回补

## 三条基准样本的角色分工

这三条样本分别约束不同的失败模式：

1. `20260224 / 600519`
   - 约束：不要把应当放出的边缘阈值样本重新压没

2. `20260226 / 600519`
   - 约束：不要把仍应保持边缘不过线的样本过度放大

3. `20260226 / 300724`
   - 约束：不要为了提高利用率而破坏 re-entry 保护，把低质量回补重新放回来

## 后续最小实验的硬性验收条件

后续任何 Layer C / watchlist 最小实验，至少要同时满足以下条件：

1. `20260224 / 600519` 仍能进入 watchlist，或至少不弱于当前 `score_final = 0.2158`
2. `20260226 / 600519` 仍保持边缘不过线，不能明显越过 `0.20`
3. `20260226 / 300724` 仍不得绕过当前 re-entry 确认保护重新回补
4. 不得放出已被判定为结构性冲突的样本，如：
   - `000960`
   - `600988`
   - `300251`
   - `300775`
   - `600111`
   - `300308`
   - `000426`

## 当前最重要的限制

虽然已经建立了统一边缘样本基准，但当前样本库仍然很小：

- 只有一个历史阈值边缘 ticker：`600519`
- 只有一个当前 re-entry 边缘 ticker：`300724`

因此：

- 这套基准足够用于约束“不要往错误方向改”
- 但还不足以支持更激进的全局放宽决策

## 推荐下一步

下一步应以这份边缘样本基准为核心，继续扩充样本库：

1. 回收更多历史 `watch / bc_conflict = null / near-threshold` 样本
2. 为每个新增样本补齐 agent 级结构判断
3. 当样本库达到可比较规模后，再决定是否值得做新的 Layer C / watchlist 最小参数实验

## 当前结论

截至 `2026-03-18`：

- `600519` 与 `300724` 已足以构成一个小而有效的边缘样本验收基准
- 任何后续最小实验都应至少同时守住这三条样本的行为边界
- 在扩充样本库之前，不建议做更大范围的全局参数放宽