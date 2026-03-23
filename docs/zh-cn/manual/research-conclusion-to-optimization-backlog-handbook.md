# 研究结论到优化 Backlog 的转换手册

> 配套阅读：
>
> 1. [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
> 2. [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)
> 3. [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)
> 4. [Replay Artifacts 案例手册：2026-03-11 的 300724 为什么入选但未买入](./replay-artifacts-case-study-20260311-300724.md)

## 1. 这份手册解决什么问题

很多团队做到周度复盘这一步时，会出现一个新的断点：

1. 页面会看了。
2. feedback 会写了。
3. 周会也开了。
4. 但结论并没有变成后续可执行的优化动作。

最常见的表现是：

1. 大家都说“Layer B 有问题”，但不知道该改什么。
2. 大家都说“执行规则太硬”，但没有拆成具体动作。
3. 一周后 backlog 里只剩下模糊条目，例如“优化选股”“改进解释性”。

这种状态下，研究结论虽然存在，但无法进入真实的工程或策略迭代。

这份手册的目标是把周度复盘结论标准化转换成五类优化 backlog：

1. Layer B
2. Layer C
3. Execution
4. Threshold
5. Explainability

---

## 2. 为什么要单独做这一步

如果没有“研究结论 -> backlog”的转换层，团队很容易犯两个错误：

1. 把执行层问题误改成选股层问题。
2. 把需要补观测或补解释的问题，误改成核心策略规则。

所以这一步的本质不是“写任务单”，而是**正确归因之后再落动作**。

---

## 3. 五类 backlog 各自代表什么

### 3.1 Layer B backlog

适合放入这类 backlog 的问题：

1. 因子解释经常偏噪声。
2. top factors 经常无法形成清晰主线。
3. 规则化预筛选层经常把低质量票抬进高位，或把明显好票压下去。

典型动作：

1. 调整因子权重或组合逻辑。
2. 修复因子语义不一致。
3. 增加或移除某类预筛选约束。

### 3.2 Layer C backlog

适合放入这类 backlog 的问题：

1. 多分析师共识经常失真。
2. 正负向 analyst 的权重或聚合方式不稳定。
3. 看起来是高分票，但 Layer C 分歧总是异常大。

典型动作：

1. 调整 agent contribution 聚合方式。
2. 重新审视 analyst roster 或提示词质量。
3. 优化 score_c 的计算或归一化方式。

### 3.3 Execution backlog

适合放入这类 backlog 的问题：

1. 研究层通过，但执行层反复不承接。
2. blocker 高频重复，且看起来可能过硬。
3. 再入场、止损、持仓、仓位等规则对研究层输出形成持续抑制。

典型动作：

1. 调整 reentry、cooldown、hard stop 等规则。
2. 审查持仓上限、单票上限、承接节奏。
3. 评估是否应增加更细的执行层解释字段。

### 3.4 Threshold backlog

适合放入这类 backlog 的问题：

1. near-miss 中重复出现疑似阈值误伤。
2. 某条阈值明显成为切线。
3. 同类样本总是“差一点点”，且人工复核反复认为值得继续看。

典型动作：

1. 调整 watchlist 或 buy_order 相关阈值。
2. 把硬阈值改成更柔性的分段逻辑。
3. 设计专门的阈值回放验证。

### 3.5 Explainability backlog

适合放入这类 backlog 的问题：

1. 页面已有结果，但人仍然看不懂为什么。
2. blocker 已发生，但解释字段不足。
3. 历史回放兼容字段太粗，研究员难以做稳定判断。

典型动作：

1. 增加或透传解释字段。
2. 丰富 selection_review.md 渲染内容。
3. 优化 replay viewer 的结构化展示。

---

## 4. 一个最小判断顺序

把结论放进 backlog 前，先按这个顺序问自己。

### 4.1 第一步：这是“看错了”，还是“看到了但没承接”

如果样本已经进入 selected，但没进 buy_orders，先不要碰 Layer B。

优先检查：

1. execution bridge
2. funnel buy_orders 过滤层
3. blocker 字段

这类问题更可能进 Execution backlog。

### 4.2 第二步：这是“规则问题”，还是“解释问题”

如果研究员反复说“我看不懂”，不一定说明规则错了，也可能只是 Explainability 不足。

判断标准：

1. 如果策略行为明显不合理，更偏规则问题。
2. 如果策略行为可能合理，但证据链展示不够，更偏 Explainability。

### 4.3 第三步：这是“个案”，还是“模式”

只有反复出现的现象，才更适合优先进入 backlog。

判断标准：

1. 单次样本先保留观察。
2. 同类样本重复出现，再升级为 backlog 候选。

---

## 5. 研究结论如何映射到五类 backlog

下面给出最实用的映射方法。

### 5.1 结论指向 selected 质量弱

常见信号：

1. `weak_edge` 在 selected 中反复出现。
2. Layer B 解释不清，Layer C 也没有形成强共识。

优先映射：

1. Layer B
2. Layer C

不要优先映射到：

1. Execution

因为问题发生在“被选出来的质量”本身。

### 5.2 结论指向研究通过但执行阻塞

常见信号：

1. `blocked_by_execution_not_selection`
2. execution bridge 明确存在 blocker
3. funnel 显示它卡在 buy_orders

优先映射：

1. Execution

如解释字段太弱，可追加：

1. Explainability

### 5.3 结论指向 near-miss 疑似阈值误伤

常见信号：

1. `threshold_false_negative`
2. near-miss 高度重复
3. rejection reason 像阈值切线

优先映射：

1. Threshold

如果该误伤来自前面层级解释不稳定，再补：

1. Layer B 或 Layer C

### 5.4 结论指向“我还是看不懂为什么”

常见信号：

1. 研究员 notes 反复写“解释不足”
2. 历史回放只能给出粗糙回退字段
3. blocker 已知，但缺少触发上下文

优先映射：

1. Explainability

---

## 6. 五类 backlog 的推荐动作模板

### 6.1 Layer B 模板

建议写成：

1. 现象：哪类样本反复暴露问题。
2. 证据：哪些 trade date、哪些 top factors、哪些标签支持这个结论。
3. 动作：拟调整哪类因子、权重或预筛选语义。
4. 验证：计划用什么 replay 或窗口验证。

示例：

> 现象：过去一周 selected 中 `event_noise_suspected` 比例偏高。证据：多日窗口内多只票的 Layer B top factors 反复由短期事件驱动。动作：审查 news/sentiment 相关因子的权重与组合方式。验证：对比修正前后 selected 中 `event_noise_suspected` 标签占比。

### 6.2 Layer C 模板

建议写成：

1. 现象：共识质量问题如何体现。
2. 证据：哪些 agent 经常出现失衡或异常分歧。
3. 动作：调整聚合、权重或 analyst roster。
4. 验证：看 score_c 分布和高分样本的人工评价是否改善。

### 6.3 Execution 模板

建议写成：

1. 现象：哪类 blocker 高频重复。
2. 证据：具体 blocker 名称、trade date 分布、代表性样本。
3. 动作：拟调整哪条执行规则。
4. 风险：放松后可能带来的副作用。
5. 验证：回放窗口内承接率、坏样本率是否恶化。

### 6.4 Threshold 模板

建议写成：

1. 现象：哪一条阈值可能误伤。
2. 证据：near-miss 样本重复性、切线位置、人工 verdict。
3. 动作：是轻微放宽、分段、还是分市场区别处理。
4. 验证：放宽后是否提升 selected 质量，还是只是引入更多噪声。

### 6.5 Explainability 模板

建议写成：

1. 现象：哪些判断点人仍然看不懂。
2. 证据：反馈中哪些 notes 反复抱怨解释不足。
3. 动作：补什么字段、改什么渲染、在哪个页面透传。
4. 验证：补充后研究员是否能更快做出一致判断。

---

## 7. 一个实用的转换表

| 研究结论 | 优先 backlog | 次级 backlog | 典型动作 |
| --- | --- | --- | --- |
| selected 质量普遍偏弱 | Layer B | Layer C | 调整因子语义、权重或预筛选规则 |
| analyst 分歧经常失真 | Layer C | Explainability | 调整聚合逻辑、补充 agent 贡献解释 |
| 研究通过但执行不承接 | Execution | Explainability | 调整 reentry/cooldown/承接规则，补 blocker 上下文 |
| near-miss 疑似阈值误伤 | Threshold | Layer B 或 Layer C | 轻调阈值、做分段或差异化规则 |
| 页面结果存在但人看不懂 | Explainability | 视情况追加其他类 | 增加解释字段、丰富 review 和 viewer 展示 |

---

## 8. 什么不应该直接进 backlog

下列结论不要急着进 backlog：

1. 只有一条样本支撑的偶发现象。
2. 仅凭当天涨跌得出的情绪判断。
3. 没有 evidence chain 的“感觉应该改”。

如果证据还不够，先保留在：

1. `draft` feedback
2. 周度复盘观察清单

而不是直接推成工程动作。

---

## 9. 推荐的周会输出结构

如果你希望把周会产出直接转成 backlog，建议统一成以下结构：

1. 本周高频现象
2. 归因层级
3. 推荐 backlog 类别
4. 拟采取动作
5. 验证窗口
6. 预期风险

这样可以避免周会结束后又回到“到底谁来写任务、任务写什么”的混乱状态。

---

## 10. 一个完整示例

### 10.1 研究结论

结论：

1. 本周多条样本进入 selected，但在 buy_orders 层被 `blocked_by_reentry_score_confirmation` 拦住。
2. 人工复核认为其中相当一部分并非选股失败，而是执行层过硬。

### 10.2 正确映射

优先 backlog：

1. Execution

次级 backlog：

1. Explainability

### 10.3 推荐动作

1. 审查 reentry 相关规则是否过硬。
2. 增加 blocker 触发上下文在 viewer 中的可见度。
3. 用既有 frozen replay 窗口验证放宽后承接率变化。

### 10.4 不正确映射

不要直接写成：

1. “优化选股质量”
2. “调高 Layer B 分数”

因为这会把执行层问题误归因到选股层。

---

## 11. 和现有手册的关系

建议按下面顺序使用这组文档：

1. 页面怎么用： [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
2. 标签怎么统一： [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)
3. 团队怎么周度复盘： [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)
4. 结论怎么变动作： 本文

这四步串起来之后，系统才真正拥有一条从“看结果”到“做优化”的闭环。

---

## 12. 最终原则

把研究结论转成 backlog 时，请始终坚持三条原则：

1. 先归因，再行动。
2. 先模式，再任务。
3. 先验证设计，再改主流程。

只要这三条不丢，周度复盘就不会停留在文档层，而会真正进入下一轮可验证的系统优化。