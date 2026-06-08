# Replay Artifacts 新人上手验收评分表

> 配套阅读：
>
> 1. [Replay Artifacts 新人培训讲义](./replay-artifacts-newcomer-training-guide.md)
> 2. [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)
> 3. [Replay Artifacts 值班速查卡](./replay-artifacts-duty-cheatsheet.md)
> 4. [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
> 5. [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md)
> 6. [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)

## 1. 这张评分表解决什么问题

新人培训讲义已经回答了“应该怎么学”，但团队在真正交接时还会遇到另一个问题：

1. 到底怎样才算已经上手。
2. 哪些表现只是第一次接触的生疏，哪些表现说明还不能独立使用。
3. 什么时候可以从“需要带教”切换到“可以独立值班或独立参与试用”。

这张表专门解决这个判断问题。

它不是试用总结，也不是周度复盘模板，而是一张面向单个新人的上手验收表。

它回答的是：

1. 这个人是否已经具备最小心智模型。
2. 是否已经能完成最小页面操作闭环。
3. 是否已经能写出不混层的结论。
4. 是否知道如何把一次真实使用分流到 feedback、observation、issue 或 weekly review。

如果这四件事还不稳，就不应该把“会打开页面”误当成“已经能独立使用”。

---

## 2. 使用场景

推荐在下面三种场景使用这张表：

1. 第一次完成 30 分钟培训和 2 小时上手作业之后。
2. 准备让新人独立参加试用窗口之前。
3. 准备让新人开始独立写 `draft`、认领 queue 或参与 weekly review 之前。

不建议把它用成：

1. 团队整体试用成败判断。
2. 产品缺陷优先级判断。
3. 绩效评分工具。

它只做一件事：判断“这个人现在是否已经到达最小可独立使用水平”。

---

## 3. 验收方式

建议一次完整验收包含四个环节：

1. 口头解释：验证心智模型是否正确。
2. 实际操作：验证页面路径是否顺畅。
3. 书面判断：验证结论是否不混层。
4. 证据分流：验证是否知道该把记录写到哪里。

如果只做口头问答，不看实际操作，很容易高估掌握程度。

如果只看能不能点开页面，不看书面判断，又会高估真正的研究可用性。

---

## 4. 五级评分标准

为避免不同带教者口径漂移，建议统一按 0 到 4 分打分。

| 分数 | 含义 | 判断标准 |
| --- | --- | --- |
| 0 | 不会 | 无法解释或无法完成动作 |
| 1 | 初步接触 | 在大量提示下勉强完成，但明显依赖带教 |
| 2 | 基本可做 | 能完成主要动作，但经常混层或判断不稳 |
| 3 | 稳定可用 | 能独立完成，偶尔需要查文档 |
| 4 | 可带别人 | 不仅自己稳，还能向别人解释 why |

最重要的分界线不是 4 分，而是 3 分。

因为当前阶段的目标不是把所有人都训练成讲师，而是先确保能够独立、安全、稳定地参与研究复核工作流。

---

## 5. 验收维度

建议按 6 个维度评分，总分满分 24 分。

### 5.1 维度 A：页面定位与层级理解

要验证什么：

1. 是否知道 Replay Artifacts 不是交易下单页。
2. 是否能说出 report、trade date、candidate、feedback / workflow 这几层。
3. 是否知道研究结论、执行结论、流程结论不能混写。

评分锚点：

1. 0 分：把页面直接当作交易建议页。
2. 2 分：知道这不是下单页，但仍容易把 workflow 状态当成投资结论。
3. 3 分：能稳定区分研究、执行、流程三层。
4. 4 分：不仅能区分，还能解释为什么这三层必须分开。

### 5.2 维度 B：report 阅读顺序

要验证什么：

1. 是否知道先看 report 概览，再看 `selection_artifact_overview`。
2. 是否知道什么时候先看 `blocker_counts`、`feedback_summary`、`cache_benchmark_overview`。
3. 是否知道何时值得继续下钻到 trade date 和具体样本。

评分锚点：

1. 0 分：随机点字段，没有顺序。
2. 2 分：知道几个字段名，但不会据此判断主矛盾。
3. 3 分：能按固定顺序读 report，并给出初步方向判断。
4. 4 分：能解释为什么先看这些字段而不是先盯某只股票。

### 5.3 维度 C：sample 判读能力

要验证什么：

1. 是否能解释 selected 为什么没变成 buy order。
2. 是否能判断 near-miss 是边界样本还是弱样本。
3. 是否能从 `execution_bridge` 看出当前更像执行保护还是选股失败。

评分锚点：

1. 0 分：只能描述“买了 / 没买”。
2. 2 分：能找到 blocker，但还经常把执行阻塞写成选股失败。
3. 3 分：能稳定写出研究层与执行层分离的判断。
4. 4 分：能进一步解释这类样本为什么对周度复盘有价值。

### 5.4 维度 D：feedback 与 workflow 使用

要验证什么：

1. 是否知道 `draft`、`final`、`ready_for_adjudication` 的边界。
2. 是否知道什么时候先写 `draft`，什么时候不该直接写 `final`。
3. 是否知道 queue 认领是流程动作，不是投资动作。

评分锚点：

1. 0 分：不会选 `review_status`，或语义完全混乱。
2. 2 分：会填写，但常把 workflow 状态当成结论本身。
3. 3 分：能稳定完成写入和基本流转判断。
4. 4 分：能向别人解释为什么 `ready_for_adjudication` 不是买入建议。

### 5.5 维度 E：证据分流能力

要验证什么：

1. 是否知道 observation、issue log、weekly review、feedback 的区别。
2. 是否能把一次真实使用放到正确载体。
3. 是否知道“链路通过但仍有摩擦”通常先记 observation，而不是马上报缺陷。

评分锚点：

1. 0 分：不知道要记录到哪里。
2. 2 分：知道这些载体存在，但经常分不清边界。
3. 3 分：能把常见情况稳定分流到正确文档。
4. 4 分：能解释为什么某条记录应当升格为 issue 或 weekly review 输入。

### 5.6 维度 F：表达与结论质量

要验证什么：

1. 是否能写出至少一句不混层的判断。
2. 是否会引用字段作为证据，而不是只写感受。
3. 是否避免“系统不会选股”“系统建议买入”这类高风险误判句式。

评分锚点：

1. 0 分：结论空泛或明显错误。
2. 2 分：有结论，但证据不足或经常混层。
3. 3 分：能写出结构稳定、证据明确的一句话。
4. 4 分：能进一步写出 why，并指出常见误判在哪里。

---

## 6. 最低通过线

建议使用下面三层通过标准：

### 6.1 不通过

满足任一情况即判定为不通过：

1. 总分低于 14 分。
2. 维度 A、C、F 任一项低于 2 分。
3. 无法写出一条不混层的样本判断。

这意味着还不能独立参加试用或独立写反馈。

### 6.2 有条件通过

满足以下条件：

1. 总分 14 到 18 分。
2. 所有核心维度不低于 2 分。
3. 可以独立操作，但仍建议带教者做二次复核。

这意味着可以开始参与真实使用，但不建议单独承担队列推进或周度结论输出。

### 6.3 稳定通过

满足以下条件：

1. 总分不低于 19 分。
2. 维度 A、C、E、F 均不低于 3 分。
3. 能独立完成一次最小闭环：读 report、判读样本、写 `draft`、正确分流证据。

这意味着已经可以独立参与常规使用。

---

## 7. 推荐验收题目

为了让评分更客观，建议带教时固定使用下面 4 题。

### 7.1 题目一：口头解释题

请对新人提问：

1. Replay Artifacts 页面在当前系统里到底是什么，不是什么。
2. 为什么 `selected` 不等于建议立刻买入。
3. 为什么 `ready_for_adjudication` 不是交易结论。

### 7.2 题目二：report 阅读题

给一份真实 report，让新人先不看具体样本，只回答：

1. 这份 report 有没有继续下钻的价值。
2. 当前主矛盾更像选股、执行、流程还是运行证据。
3. 你先看了哪些字段，为什么。

### 7.3 题目三：sample 判读题

给一个 selected 样本或 blocker 样本，让新人写一句判断，要求：

1. 至少引用 2 个字段。
2. 说明这是研究结论还是执行结论。
3. 不能用泛化口号替代字段证据。

### 7.4 题目四：证据分流题

给一个真实现象，例如：

1. 链路跑通，但 `workflow_status` 语义需要靠文档辅助理解。
2. `Assign to me` 成功，但多人协作下优先级仍难判断。
3. feedback 写入失败且 activity 没有回读。

要求新人回答：

1. 这条记录应该写到哪里。
2. 是否需要升格为 issue。
3. 为什么。

---

## 8. 验收记录模板

```md
## 新人上手验收记录

- 日期：
- 被验收人：
- 带教人：
- 使用样本 report：
- 使用样本 trade_date：

### 评分

- 维度 A 页面定位与层级理解：0-4
- 维度 B report 阅读顺序：0-4
- 维度 C sample 判读能力：0-4
- 维度 D feedback 与 workflow 使用：0-4
- 维度 E 证据分流能力：0-4
- 维度 F 表达与结论质量：0-4

- 总分：
- 结论：不通过 / 有条件通过 / 稳定通过

### 代表性表现

- 做得稳的地方：
- 当前主要风险：
- 需要补学的文档：
- 建议下一步：
```

---

## 9. 最小示例

```md
## 新人上手验收记录

- 日期：2026-03-26
- 被验收人：einstein-trainee
- 带教人：einstein
- 使用样本 report：paper_trading_window_20260316_20260323_live_m2_7_20260323
- 使用样本 trade_date：2026-03-23

### 评分

- 维度 A 页面定位与层级理解：3
- 维度 B report 阅读顺序：3
- 维度 C sample 判读能力：3
- 维度 D feedback 与 workflow 使用：2
- 维度 E 证据分流能力：3
- 维度 F 表达与结论质量：3

- 总分：17
- 结论：有条件通过

### 代表性表现

- 做得稳的地方：能区分 selected 与 execution blocker，也能解释为什么 `position_blocked_score` 不等于选股失败。
- 当前主要风险：对 `final` 与 `ready_for_adjudication` 的边界还不够稳。
- 需要补学的文档：Replay Artifacts 周度复盘工作流手册、Replay Artifacts 研究反馈标签规范手册。
- 建议下一步：继续完成 2 到 3 次真实 `draft` 写入，并由带教人二次复核。
```

---

## 10. 带教建议

如果验收结果没有通过，不建议只说“再熟悉一下”。

建议直接指出是哪个维度没过线，并配对补学动作：

1. A 维度低：回到 [Replay Artifacts 新人培训讲义](./replay-artifacts-newcomer-training-guide.md) 和 [Replay Artifacts 分析报告术语解析手册](./replay-artifacts-report-terminology-guide.md)。
2. B、C 维度低：回到 [Replay Artifacts 值班速查卡](./replay-artifacts-duty-cheatsheet.md) 和 [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)。
3. D、E 维度低：回到 [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md)、[Replay Artifacts 试用验收计划](./replay-artifacts-trial-acceptance-plan.md) 和 [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)。
4. F 维度低：回到 [Replay Artifacts 分析报告术语解析手册](./replay-artifacts-report-terminology-guide.md) 中的误判与结论模板部分，再做一轮样本写作练习。

只要补学动作和低分维度一一对应，这张评分表就不只是打分工具，而是带教闭环的一部分。
