# BTST 样本练习册

> 配套阅读：
>
> 1. [BTST 新人 30 分钟上手路径](./14-btst-newcomer-30-minute-guide.md)
> 2. [BTST 新人上手验收评分表](./15-btst-onboarding-readiness-scorecard.md)
> 3. [BTST 带教手册](./16-btst-trainer-handbook.md)
> 4. [BTST 当前窗口案例复盘手册](./08-btst-current-window-case-studies.md)
> 5. [BTST 优化决策树](./11-btst-optimization-decision-tree.md)
> 6. [BTST 产物判读手册](./10-btst-artifact-reading-manual.md)

## 1. 这本练习册怎么用

这本练习册不是为了考记忆，而是为了训练 BTST 最关键的 3 个能力：

1. 样本分型能力。
2. artifact 判读能力。
3. 下一步动作选择能力。

推荐用法：

1. 新人先独立作答。
2. 带教者再按标准答案核对推理方向。
3. 如果答案不对，优先纠正“分层和主线”，不要急着纠正措辞。

这本练习册适合和 [BTST 新人上手验收评分表](./15-btst-onboarding-readiness-scorecard.md) 配合使用。

---

## 2. 作答规则

每题都尽量按下面格式回答：

1. 先判断这是什么类型的问题。
2. 再给出一句不混层的解释。
3. 最后给出下一步最合理的动作。

如果回答里只有“差一点”“放松一下阈值试试”这类模糊表述，默认视为未通过。

---

## 3. 基础题

### 3.1 练习 1：解释 BTST 的定位

题目：

请用一句话解释 BTST 在当前系统里的定位，并补一句它不是什么。

标准答案要点：

1. BTST 是独立短线目标链路。
2. 它不是研究主线后面附加的一个短线阈值。

常见错误：

1. 只说“BTST 是次日短线策略”，没有说清它与研究主线的关系。
2. 把它说成 Layer C 或 execution 里的一个子规则。

### 3.2 练习 2：解释当前主线推进阶段

题目：

请用两句话说明当前 BTST 主线已经推进到哪一步，下一步重点是什么。

标准答案要点：

1. 短线不应继续共用旧 Layer B 边界股票池，这件事已经基本成立。
2. 当前重点已经转向 `short_trade_boundary` 的 score frontier 精修，而不是继续证明独立建池有没有必要。

常见错误：

1. 仍把“是否独立建池”当主问题。
2. 把主线说成“继续大范围扩 admission”。

---

## 4. 样本分型题

### 4.1 练习 3：`300724` 是什么样本

题目：

请判断 `300724` 的主类型，并说明为什么不应该把它和 candidate-entry 问题混在一起。

标准答案要点：

1. `300724` 是低成本 structural conflict / blocked release 样本。
2. 它的价值在于可以做 case-based、低污染释放验证。
3. 它不是“入口太弱”的 candidate-entry 语义样本。

常见错误：

1. 说成“就是分数差一点”。
2. 说成“和 `300502` 一样，都是入口该挡掉的票”。

### 4.2 练习 4：`300394` 是什么样本

题目：

请判断 `300394` 的主类型，并说明为什么它不是 threshold-only 释放对象。

标准答案要点：

1. `300394` 是 penalty / score construction 主导样本。
2. 它存在正向贡献，但被 avoid、stale、extension 等 penalty 压制。
3. 单靠轻微阈值放松，不足以把它稳定推到 near-miss。

常见错误：

1. 说成“它和 `300724` 一样，放掉 hard block 就好了”。
2. 说成“再松一点 near_miss_threshold 就够了”。

### 4.3 练习 5：`300502` 是什么样本

题目：

请判断 `300502` 的主类型，并说明为什么它不应该优先走 penalty 微调路线。

标准答案要点：

1. `300502` 是 candidate-entry / entry semantics 样本。
2. 它的问题更像入口语义和弱结构过滤，而不是 penalty 微调。
3. 它不应和 `300394` 一起放进同一轮 penalty 调参实验。

常见错误：

1. 说成“只是 avoid penalty 太高”。
2. 说成“它和 `300394` 都该一起做 penalty relief”。

### 4.4 练习 6：`300383` 和 `001309` 分别代表什么

题目：

请分别用一句话说明 `300383` 与 `001309` 各自更适合承担什么角色。

标准答案要点：

1. `300383` 是 threshold-only、低污染的 case-based release 样本。
2. `001309` 是 near-miss promotion follow-through 的主入口样本。

常见错误：

1. 把两者都说成“优先放阈值的边界票”。
2. 忽略 `001309` 的 close continuation 价值。

---

## 5. artifact 判读题

### 5.1 练习 7：拿到 report 后先看什么

题目：

你拿到一份 BTST report，第一步应该优先看哪 3 类 artifact，为什么。

标准答案要点：

1. 先看总览层，判断当前主失败簇在哪里。
2. 再看日级快照或 selection artifact，定位具体样本。
3. 最后看 frontier / targeted release / outcome 层，决定下一步动作。

常见错误：

1. 一上来就盯单个 ticker。
2. 一上来就跑命令，而不是先判断主矛盾。

### 5.2 练习 8：什么时候看 blocker analysis，什么时候看 targeted release

题目：

请解释 blocker analysis 和 targeted release 各自回答什么问题，以及在什么场景下该先看哪一个。

标准答案要点：

1. blocker analysis 用来找窗口级主失败簇。
2. targeted release 用来验证单票或单类样本的低污染释放可能性。
3. 先看哪个，取决于你当前是在找主线，还是已经锁定了目标样本。

常见错误：

1. 把 targeted release 当成全局主线发现工具。
2. 把 blocker analysis 当成具体 release 方案本身。

---

## 6. 动作选择题

### 6.1 练习 9：当前窗口大量出现 `rejected_short_trade_boundary_score_fail`

题目：

如果当前窗口里 `rejected_short_trade_boundary_score_fail` 大量堆积，下一步最合理的动作是什么。

标准答案要点：

1. 主线应转向 score frontier 精修。
2. 不应重新退回“短线是否独立建池”的讨论。
3. 也不应把 blocked release 和 admission 放松混进同一轮。

常见错误：

1. 直接建议继续大范围放 admission。
2. 直接建议全局放宽 near-miss 或 selected 阈值。

### 6.2 练习 10：当前窗口出现 `300724` 一类 blocked 样本

题目：

如果你确认窗口里存在 `300724` 这类低成本 blocked 样本，下一步更合理的是哪种实验。

标准答案要点：

1. 做 case-based 的受控 release。
2. 先验证 changed_non_target_case_count 是否保持为 0。
3. 不做 blocked cluster-wide 的统一放松。

常见错误：

1. 一看到 blocked 就建议整簇放开 hard block。
2. 不区分 `300724` 和 `300394` / `300502` 的成本结构。

### 6.3 练习 11：什么时候应该停止调参

题目：

请举一个场景，说明什么时候应当停止继续调参，而是先回到文档、案例或 artifact 判读。

标准答案要点：

1. 当主矛盾尚未判断清楚时，应先停手。
2. 当 admission、score frontier、blocked release 混成一团时，应先回到案例和决策树。
3. 当一轮实验准备同时改多类机制时，应先停下重分层。

常见错误：

1. 把“没有结果”理解成“再多跑几轮就好”。
2. 用命令数量代替判断质量。

---

## 7. 综合题

### 7.1 练习 12：写一句合格的 BTST 结论

题目：

请围绕下面任一场景，写一句不混层、可执行的 BTST 结论：

1. `300724`
2. `300394`
3. `300502`
4. `001309`

标准答案示例：

1. `300724` 更像低成本 structural conflict release 样本，当前更适合做 case-based 的 `blocked -> near_miss` 受控验证，而不是和 penalty 主导或 candidate-entry 语义样本混在一轮实验里。
2. `300394` 当前主矛盾仍是 penalty / score construction 压制，轻微 threshold-only 放松不足以形成稳定 near-miss rescue，因此下一步应优先保持分层诊断，而不是把它当作低成本 release 票。
3. `300502` 当前更像 candidate-entry 弱结构语义样本，优先方向应是入口语义收紧或弱结构过滤，而不是 penalty relief。
4. `001309` 已具备 near-miss promotion follow-through 的低污染特征，可优先作为 threshold-only 的主实验入口。

评分要点：

1. 是否明确写出类型。
2. 是否明确写出下一步动作。
3. 是否避免“差一点”“感觉能救”这类空泛语句。

---

## 8. 建议评分方式

如果这本练习册用于带教或验收，建议按下面方法评分：

1. 练习 1 到 2：看定位和主线是否准确。
2. 练习 3 到 6：看样本分型是否稳定。
3. 练习 7 到 8：看 artifact 阅读顺序是否正确。
4. 练习 9 到 11：看动作选择是否有纪律。
5. 练习 12：看表达是否能形成一句合格结论。

如果练习 3 到 5 仍然明显混掉，建议先不要进入真实 BTST 任务。

---

## 9. 一句话总结

BTST 练习最重要的不是答对名词，而是能稳定完成三件事：把样本分对类、把 artifact 看对顺序、把下一步动作选对方向。只要这三件事成立，文档才算真正被用起来。
