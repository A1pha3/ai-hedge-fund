# 2026-03-18 边缘样本候选清单：当前长窗口内是否存在可安全释放的替代票

## 结论摘要

- 基于 `2026-02-02 .. 2026-03-04` 长窗口修复后回放产物，按“近阈值且无结构性冲突”的标准筛查后，当前窗口内真正符合条件的边缘样本只有 `300724`。
- 没有发现第二个类似历史 `600519` 的候选样本。
- 这意味着：在当前窗口里，`300724` 被 re-entry 规则拦下后，系统几乎没有天然替代票可接力。
- 因此，下一步如果要继续寻找“只释放边缘票”的最小实验目标，必须扩大样本范围，而不是继续在当前窗口内做全局放宽。

## 分析标准

数据来源：

- [ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)

边缘样本筛选口径：

1. `score_final` 位于近阈值区间 `0.17 .. 0.26`
2. `bc_conflict = null`
3. 不属于 `decision_avoid`
4. 可以是：
   - 已进入 watchlist 的 `watch`
   - 或未进 watchlist 但仍是 `watch` 且只因分数略低被过滤

这个口径的目的，是优先找出：

- 没有结构性冲突
- 只是分数接近 watchlist / execution 阈值
- 理论上最适合做“最小释放实验”的样本

## 扫描结果

在整个窗口内，唯一满足上述条件的 ticker 是：

- `300724`

没有其他 ticker 同时满足：

- `score_final` 接近阈值
- `bc_conflict = null`
- 且不属于结构性 `avoid`

## 300724 的边缘样本轨迹

符合条件的记录如下：

### 已进入 watchlist 的边缘 watch 样本

- `20260203`: `score_final = 0.2223`
- `20260204`: `score_final = 0.2227`
- `20260205`: `score_final = 0.2238`
- `20260209`: `score_final = 0.2526`
- `20260210`: `score_final = 0.2059`
- `20260225`: `score_final = 0.2019`
- `20260226`: `score_final = 0.2250`
- `20260302`: `score_final = 0.2233`

### 未进入 watchlist，但仍为非冲突 watch 样本

- `20260211`: `score_final = 0.1860`，原因为 `score_final_below_watchlist_threshold`
- `20260212`: `score_final = 0.1856`，原因为 `score_final_below_watchlist_threshold`
- `20260213`: `score_final = 0.1821`，原因为 `score_final_below_watchlist_threshold`

### 共性特征

- 全部记录均为 `decision = watch`
- 全部记录均为 `bc_conflict = null`
- `score_final` 区间：`0.1821 .. 0.2526`
- investor 贡献多数为轻微正或轻微负
- analyst 贡献多数为轻微负

这说明：

- `300724` 是当前窗口里非常典型的“边缘但非结构性冲突”样本
- 它适合作为 re-entry、阈值和边缘入场规则的验证对象
- 但它不适合作为“替代票池”的证据，因为它本身就是当前唯一的边缘样本

## 当前窗口为什么没有第二个边缘样本

结合前两份分析文档：

- [ai-hedge-fund-fork/docs/zh-cn/analysis/paper-trading-candidate-suppression-20260317.md](ai-hedge-fund-fork/docs/zh-cn/analysis/paper-trading-candidate-suppression-20260317.md)
- [ai-hedge-fund-fork/docs/zh-cn/analysis/paper-trading-agent-conflict-diagnosis-20260318.md](ai-hedge-fund-fork/docs/zh-cn/analysis/paper-trading-agent-conflict-diagnosis-20260318.md)

可以看到：

- `000960`、`600988`、`300251`、`300775`、`600111`、`300308`、`000426` 等近端样本几乎都带有 `bc_conflict = b_positive_c_strong_bearish`
- 它们虽然有时 `score_final` 也接近阈值，但本质上是结构性冲突样本，不属于当前要找的“安全边缘票”

因此，当前窗口内没有第二个边缘样本，并不是筛选条件太严，而是样本本身就不存在。

## 业务含义

当前结论对后续实验有直接约束：

1. 在本窗口内，不能指望通过轻微参数放松就自然补出一批健康替代票
2. 如果直接放松 `Layer C / avoid`，放出来的更可能是结构性冲突票，而不是新的 `300724` 型边缘票
3. 当前窗口更适合作为“验证 re-entry 是否精准命中边缘样本”的用例，不适合作为“寻找新的边缘替代票池”的唯一依据

## 下一步建议

如果目标是继续推进“只释放边缘票”的最小实验，应优先：

1. 扩大样本窗口，纳入更长时间段的 watchlist / near-watch 历史记录
2. 把历史文档中提到的 `600519` 一类边缘样本重新纳入统一候选清单
3. 在更大样本池中先做“边缘样本候选库”，再决定是否值得做新的 Layer C / watchlist 最小化参数实验

## 当前结论

截至 `2026-03-18`：

- 当前长窗口内唯一明确的边缘样本是 `300724`
- 当前窗口内没有第二个可直接接替它的安全边缘候选
- 因此，后续工作重点应转向“扩大边缘样本库”，而不是在当前窗口里继续全局放宽规则

## 状态更新

基于当日后续的 targeted supplementation：

- `603993` 已确认降格为“上游形成机制样本”，不是新的 clean edge benchmark。
- `300065` 也已确认降格为“上游 Layer B 压线 + 强负向 Layer C avoid 机制样本”，不是新的 clean edge benchmark。
- `688498` 已完成最低必要补证，确认属于“第三条腿缺失 + 中性稀释”低优先级机制样本，不是新的 clean edge benchmark。