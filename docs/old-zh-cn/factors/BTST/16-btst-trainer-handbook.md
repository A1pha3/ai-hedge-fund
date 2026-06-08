# BTST 带教手册

> 配套阅读：
>
> 1. [BTST 新人 30 分钟上手路径](./14-btst-newcomer-30-minute-guide.md)
> 2. [BTST 新人上手验收评分表](./15-btst-onboarding-readiness-scorecard.md)
> 3. [BTST 次日短线 5 分钟简报](./12-btst-five-minute-brief.md)
> 4. [BTST 一页速查卡](./03-btst-one-page-cheatsheet.md)
> 5. [BTST 当前窗口案例复盘手册](./08-btst-current-window-case-studies.md)
> 6. [BTST 产物判读手册](./10-btst-artifact-reading-manual.md)
> 7. [BTST 优化决策树](./11-btst-optimization-decision-tree.md)
> 8. [BTST 样本练习册](./17-btst-sample-workbook.md)

## 1. 这份手册解决什么问题

到目前为止，BTST 文档已经回答了三类问题：

1. 策略是什么。
2. 新人应该怎么学。
3. 学到什么程度才算基本上手。

但实际交接时，还缺最后一块：

**带教者应该怎样用这套材料，在有限时间里把一个新人稳定带到“可独立使用”的状态。**

这份手册就是为带教者准备的。

它不是策略设计文档，也不是实验 runbook，而是一份培训执行脚本。

它解决的是：

1. 一小时培训应该怎么排顺序。
2. 哪些地方最容易讲散、讲混层。
3. 现场应该问什么题，才能快速判断新人是真懂还是只会复述。
4. 培训后应该布置什么练习，才能把“理解”变成“能判断”。

---

## 2. 带教目标

一轮合格的 BTST 带教，不追求让新人立刻会做全部 frontier 实验，而是先完成下面 4 个目标：

1. 建立最小心智模型：知道 BTST 是独立短线目标链路，而不是研究主线上的附属阈值。
2. 建立样本分型能力：能把 `300724`、`300394`、`300502` 分到不同机制类别。
3. 建立 artifact 阅读顺序：拿到 report 后知道先看什么、后看什么。
4. 建立动作选择纪律：知道 admission、score frontier、blocked release 不能混成一轮。

只要这 4 件事稳定了，新人才有资格进入更细的调参、命令执行和 case-based release 工作。

---

## 3. 带教前准备

正式培训前，建议带教者先完成下面 5 项准备：

1. 自己先重读 [BTST 次日短线 5 分钟简报](./12-btst-five-minute-brief.md)，确保阶段性主线讲法一致。
2. 准备一个当前窗口的代表性 report，用于现场做 artifact 判读。
3. 准备三只标准样本：`300724`、`300394`、`300502`。
4. 打开 [BTST 样本练习册](./17-btst-sample-workbook.md)，确认本轮培训用哪几题。
5. 打开 [BTST 新人上手验收评分表](./15-btst-onboarding-readiness-scorecard.md)，提前明确通过线。

带教前不建议做两件事：

1. 现场临时决定讲哪些文档。
2. 直接从命令或参数开始讲。

因为新人最先缺的不是命令执行能力，而是层级感和主线感。

---

## 4. 推荐的 60 分钟培训脚本

### 4.1 第 1 段：10 分钟讲定位

目标：让新人先知道 BTST 到底是什么。

建议只讲 3 句话：

1. BTST 不是研究主线加一个短线阈值，而是一条独立目标链路。
2. 当前主线已经不是“独立建池要不要做”，而是“独立建池成立后，score frontier 如何继续精修”。
3. 后续所有样本、artifact 和调参动作，都必须围绕这条阶段性主线理解。

这一段建议搭配：

1. [BTST 次日短线 5 分钟简报](./12-btst-five-minute-brief.md)
2. [BTST 一页速查卡](./03-btst-one-page-cheatsheet.md)

这一段不要讲太多参数细节。

如果新人在这一段结束后还会把 BTST 说成“短线阈值”，后面就不要急着进入样本练习。

### 4.2 第 2 段：15 分钟讲链路

目标：让新人知道 BTST 不是单点规则，而是一条链。

建议顺序：

1. Layer B 提供候选供给。
2. `short_trade_boundary` 负责独立补池。
3. `short_trade_target` 负责正式决策。
4. T+1 执行和 replay 负责反向验证。

这一段建议搭配：

1. [BTST 次日短线策略完整指南](./01-btst-complete-guide.md)
2. [BTST 产物判读手册](./10-btst-artifact-reading-manual.md)

带教时最重要的不是把所有字段都讲一遍，而是让新人回答：

1. admission 和 final score 分别解决什么问题。
2. `blocked` 和 `rejected` 为什么不是同一回事。

### 4.3 第 3 段：20 分钟讲样本分型

目标：把新人从“懂概念”推进到“会分类”。

这段建议固定讲三只票：

1. `300724`：低成本 structural release 样本。
2. `300394`：penalty / score construction 样本。
3. `300502`：candidate-entry 语义样本。

这一段的教学标准不是“记住结论”，而是“能说出为什么不能混成一类”。

建议搭配：

1. [BTST 当前窗口案例复盘手册](./08-btst-current-window-case-studies.md)
2. [BTST 指标与因子判读词典](./07-btst-factor-metric-dictionary.md)

如果时间够，可以补两个对照样本：

1. `300383`：threshold-only 的低污染 case-based release。
2. `001309`：near-miss promotion follow-through 的主入口样本。

### 4.4 第 4 段：15 分钟讲动作选择

目标：让新人知道下一步该做什么，不该做什么。

建议带着 [BTST 优化决策树](./11-btst-optimization-decision-tree.md) 讲下面 4 条：

1. admission 问题优先去看入口与边界条件。
2. score frontier 问题优先去看 score-fail 和 release frontier。
3. blocked release 问题优先做 case-based 释放，不做 cluster-wide 粗放放松。
4. 任何实验都应保持一次只改一类机制。

如果新人在这一段仍然倾向于“几个阈值一起松”，说明还不能进入独立实验阶段。

---

## 5. 现场必须问的 6 个问题

为了快速判断新人是否真正理解，建议每次培训都固定问下面 6 个问题：

1. BTST 在当前系统里是什么，不是什么。
2. 为什么 `short_trade_boundary` 不是最终结论。
3. 为什么 `300724` 和 `300394` 不能放进同一轮 release 实验。
4. 为什么 `300502` 不是 penalty 微调优先对象。
5. 拿到一份 report 后，你先看哪 3 个 artifact。
6. 如果当前窗口大量出现 `rejected_short_trade_boundary_score_fail`，下一步最合理的动作是什么。

这 6 题的价值在于，它们几乎覆盖了定位、链路、分型、artifact 阅读和动作选择这 5 个核心能力。

---

## 6. 最容易讲错的 5 个点

### 6.1 把 BTST 讲成“短线阈值系统”

这是最常见的错误。

一旦这么讲，新人后面会天然把所有问题都理解成“阈值差一点”。

### 6.2 把 blocked 和 rejected 一起讲

这样会让新人误以为结构冲突和正式比评分数失败只是强弱差异，而不是机制差异。

### 6.3 把 `300724`、`300394`、`300502` 讲成“都能救的边界样本”

这会直接毁掉后续实验纪律。

### 6.4 太早讲参数，太少讲主线

新人早期最需要的是路径感和判断框架，不是参数矩阵。

### 6.5 把单票成立讲成默认规则成立

带教时必须反复强调：

1. 单票成立说明方向存在。
2. 窗口级成立才有资格讨论升级默认。

---

## 7. 培训后的练习安排

培训结束后，建议不要让新人直接去跑大量命令，而是先做一轮标准练习。

推荐顺序：

1. 先做 [BTST 样本练习册](./17-btst-sample-workbook.md) 的前 4 题，检查样本分型是否稳定。
2. 再让新人写一句窗口级结论，检查是否会混层。
3. 最后才让新人根据 [BTST 命令作战手册](./13-btst-command-cookbook.md) 选择一条最短命令链。

如果练习表现不稳，优先回到 [BTST 当前窗口案例复盘手册](./08-btst-current-window-case-studies.md)，而不是继续加命令难度。

---

## 8. 带教后的验收建议

培训后建议立即进入一次轻量验收，而不是隔很久再回头判断。

推荐顺序：

1. 用 [BTST 新人上手验收评分表](./15-btst-onboarding-readiness-scorecard.md) 打分。
2. 如果总分低于通过线，先补样本分型和 artifact 阅读。
3. 如果达到“有条件通过”，可以让新人参与真实复盘，但需二次复核。
4. 如果达到“稳定通过”，才可以让新人独立承担常规 BTST 文档使用与基础判断任务。

这一步的目的不是给人贴标签，而是避免“看过文档”被误当成“已经能独立判断”。

---

## 9. 一句话总结

BTST 带教最重要的不是多讲，而是讲对顺序：先讲定位，再讲链路，再讲样本分型，最后讲动作选择。顺序对了，培训才会真正沉淀成可用判断力。
