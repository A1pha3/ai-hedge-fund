# 2026-03-17 候选抑制链分析：为什么拦下 300724 之后利用率仍然偏低

## 结论摘要

- 在 `2026-02-25 .. 2026-03-04` 的关键窗口内，组合利用率下降的主要原因不是仓位约束过紧。
- 真正的问题是：`300724` 被拦下之后，几乎没有健康替代标的能够穿过 `Layer C -> watchlist -> buy_orders` 链路。
- 多数近端候选并非简单“分数略低”，而是在 `watchlist` 阶段即被判为 `decision_avoid`，同时伴随 `bc_conflict = b_positive_c_strong_bearish`。
- 这意味着下一阶段最值得研究的不是放松仓位计算器，而是 `Layer C / watchlist / avoid` 抑制机制。

## 分析范围

分析产物：

- [ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)

聚焦日期：

- `20260225`
- `20260226`
- `20260227`
- `20260302`
- `20260303`
- `20260304`

这些日期覆盖了：

- `300724` 冷却后准备回补的关键阶段
- `300724` 被 re-entry 规则拦下后的替代候选空窗期
- `603993` 卖出后组合进一步缩窄的阶段

## 逐日抑制链

### 20260225

Layer B 通过：

- `000960`
- `300724`

进入 watchlist：

- `300724`，`score_final = 0.2019`，`decision = watch`

watchlist 近端落选：

- `000960`，`score_final = 0.1964`，`decision = avoid`
- 原因：`b_positive_c_strong_bearish`

买单层结果：

- `300724` 仍未形成买单
- 原因：`position_blocked_score`

解释：

- 这一天的问题还不是 re-entry 规则，而是 `300724` 本身仍低于建仓要求，且第二候选 `000960` 已经在 watchlist 阶段被 avoid 拦下。

### 20260226

Layer B 通过：

- `300724`
- `600988`
- `000960`

进入 watchlist：

- `300724`，`score_final = 0.2250`，`decision = watch`

watchlist 近端落选：

- `000960`，`score_final = 0.1893`，`decision = avoid`
- `600988`，`score_final = 0.1687`，`decision = avoid`
- 二者均伴随：`b_positive_c_strong_bearish`

买单层结果：

- `300724` 被拦下
- 原因：`blocked_by_reentry_score_confirmation`
- 当日分数：`0.2250`
- 需要分数：`0.25`

解释：

- 这一天 re-entry 规则确实准确命中了目标，但同时也暴露出：除了 `300724` 之外，没有任何候选能顺利穿过 watchlist。

### 20260227

Layer B 通过：

- `603799`
- `600988`
- `000960`

进入 watchlist：

- 无

watchlist 近端落选：

- `000960`，`score_final = 0.1909`，`decision = avoid`
- `600988`，`score_final = 0.1686`，`decision = avoid`

解释：

- 即便当日不再有 `300724` 候选，系统也没有新的健康标的顶上来；问题完全发生在 watchlist 之前。

### 20260302

Layer B 通过：

- `300724`

进入 watchlist：

- `300724`，`score_final = 0.2233`，`decision = watch`

买单层结果：

- `300724` 未形成买单
- 原因：`position_blocked_score`

解释：

- 这一天候选池更窄，只有 `300724` 一个名字进入 watchlist，说明利用率下降首先是供给问题，不是排序问题。

### 20260303

Layer B 通过：

- `300251`
- `002602`

进入 watchlist：

- 无

watchlist 近端落选：

- `300251`，`score_final = 0.1735`，`decision = avoid`
- 原因：`b_positive_c_strong_bearish`

解释：

- 在 `603993` 触发卖出之后，组合没有获得新的补位候选，这直接导致利用率进一步掉到很低水平。

### 20260304

Layer B 通过：

- `300775`
- `600111`
- `000426`
- `300308`
- `300251`

进入 watchlist：

- 无

watchlist 近端落选：

- `300775`，`score_final = 0.2215`，`decision = avoid`
- `600111`，`score_final = 0.2145`，`decision = avoid`
- `300308`，`score_final = 0.1815`，`decision = avoid`
- `000426`，`score_final = 0.1786`，`decision = avoid`
- 共性：全部存在 `b_positive_c_strong_bearish`

解释：

- 这一天最有代表性：Layer B 并非完全没有供给，但最终全部被 Layer C / watchlist 抑制掉了。

## 综合判断

从关键日链路看，抑制顺序是：

1. Layer B 能放出少量候选
2. 多数候选在 Layer C 聚合后触发 `b_positive_c_strong_bearish`
3. `decision_avoid` 使其无法进入 watchlist
4. 结果是 watchlist 常常只剩 `300724` 或直接为空
5. 一旦 `300724` 被 re-entry 规则或建仓分数门槛拦下，当日就没有替代买单

因此：

- `reentry` 规则解决的是错误回补问题，方向正确
- 利用率下降是修复后的次级现象，不是说明 re-entry 规则本身有问题
- 如果现在仅放松单票上限、可用现金分配、日交易额上限，预期收益有限，因为很多日期根本没有第二个通过 watchlist 的标的

## 对后续实验的约束

后续最小实验应满足：

1. 不回退本轮 re-entry 确认规则
2. 不优先动 `logic_stop_loss` 阈值
3. 不先动仓位计算器的单票上限或每日交易限额
4. 优先在 `Layer C / watchlist / avoid` 侧寻找“只释放边缘健康票、不放出结构性冲突票”的最小杠杆

## 推荐下一步

建议先做一个“只读实验设计”，而不是立刻改代码：

1. 针对上述关键日的近端落选者，汇总其 `score_b / score_c / score_final / bc_conflict`
2. 评估这些标的是否属于此前已识别的边缘型样本，还是结构性被投资人群体压制的样本
3. 仅当存在少量可控边缘票时，再考虑做最小化的 `Layer C + watchlist` 参数实验

当前最重要的认知是：

- `300724` 被拦下以后没有替代票，不是因为买单层太严，而是因为大多数候选更早就被判定为 `avoid`