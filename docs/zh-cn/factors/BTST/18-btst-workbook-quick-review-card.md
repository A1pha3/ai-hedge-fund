# BTST 标准答案速评卡

> 配套阅读：
>
> 1. [BTST 样本练习册](./17-btst-sample-workbook.md)
> 2. [BTST 带教手册](./16-btst-trainer-handbook.md)
> 3. [BTST 新人上手验收评分表](./15-btst-onboarding-readiness-scorecard.md)
> 4. [BTST 当前窗口案例复盘手册](./08-btst-current-window-case-studies.md)
> 5. [BTST 优化决策树](./11-btst-optimization-decision-tree.md)

## 1. 这张速评卡怎么用

这张卡的目标不是替代 [BTST 样本练习册](./17-btst-sample-workbook.md)，而是把 12 道练习题压缩成带教现场可快速核对的一页版。

推荐用法：

1. 新人先按练习册完整作答。
2. 带教者用这张卡做现场核对。
3. 如果答案偏差明显，优先纠正分层、主线和动作方向，不纠结措辞细节。

最重要的核对标准只有 3 条：

1. 有没有把问题分对层。
2. 有没有把样本分对类。
3. 有没有把下一步动作选对方向。

---

## 2. 速评总原则

现场速评时，优先按下面口径判断：

1. 只要把 BTST 说成“短线阈值”，基础题直接判偏。
2. 只要把 `300724`、`300394`、`300502` 混成一类，样本分型直接判偏。
3. 只要把 admission、score frontier、blocked release 混成一轮动作，动作选择直接判偏。
4. 只要回答里反复出现“差一点”“松一点试试”而没有机制归类，表达质量直接降档。

---

## 3. 12 题一页速评

| 题号 | 题目核心 | 合格答案关键词 | 一票否决点 |
| ---- | -------- | -------------- | ---------- |
| 1 | BTST 定位 | 独立短线目标链路；不是研究主线附属阈值 | 说成“短线阈值”或 Layer C 子规则 |
| 2 | 当前主线阶段 | 不再共用旧 Layer B 边界池；重点转向 `short_trade_boundary` score frontier 精修 | 还把“是否独立建池”当主问题 |
| 3 | `300724` 分型 | low-cost structural conflict / blocked release；适合 case-based release | 说成 candidate-entry 或单纯阈值差一点 |
| 4 | `300394` 分型 | penalty / score construction 主导；非 threshold-only | 说成“放掉 hard block 就行” |
| 5 | `300502` 分型 | candidate-entry / weak-structure semantics；优先入口语义过滤 | 说成 penalty relief 优先对象 |
| 6 | `300383` 与 `001309` | `300383` 是 threshold-only case-based release；`001309` 是 near-miss promotion 主入口 | 两者都说成“边界阈值票” |
| 7 | report 阅读顺序 | 先总览主失败簇，再看日级 artifact，再看 frontier / outcome | 一上来盯单票或直接跑命令 |
| 8 | blocker vs targeted release | blocker 看窗口主失败簇；targeted release 看单票低污染释放 | 把 targeted release 当主线发现工具 |
| 9 | score-fail 堆积时怎么做 | 转向 score frontier 精修；不回退 admission 主线 | 直接建议全局放 admission 或阈值 |
| 10 | `300724` blocked 怎么做 | 做 case-based 受控 release；先看 `changed_non_target_case_count=0` | 建议整簇放开 hard block |
| 11 | 何时停手不调 | 主矛盾不清或机制混层时先停手回文档/案例/决策树 | 把“继续多跑几轮”当默认答案 |
| 12 | 一句话结论 | 必须写清类型 + 证据方向 + 下一步动作 | 只有空泛判断，没有机制与动作 |

---

## 4. 分题核对口径

### 4.1 题 1 到 2：基础题

现场只核对两件事：

1. 有没有说出 BTST 是独立目标链路。
2. 有没有说出当前主线已转向 score frontier，而不是继续证明独立建池。

只要这两点缺一，说明基础心智模型还不稳。

### 4.2 题 3 到 6：样本分型题

现场只核对四个锚点：

1. `300724`：blocked release。
2. `300394`：penalty / score construction。
3. `300502`：candidate-entry semantics。
4. `001309`：near-miss promotion 主入口。

如果新人把 `300724`、`300394`、`300502` 中任意两只放到同一轮实验里，说明分型仍不稳定。

### 4.3 题 7 到 8：artifact 判读题

现场只核对两个顺序：

1. 先看窗口主失败簇，再下钻日级样本。
2. 先找主线，再决定是否做 targeted release。

如果新人一开始就执着于某个 ticker，通常说明还没建立窗口级阅读顺序。

### 4.4 题 9 到 11：动作选择题

现场只核对三条纪律：

1. score-fail 堆积时，不回退 admission 主线。
2. blocked 样本优先 case-based，不做 cluster-wide 粗放放松。
3. 主矛盾不清时，先停手重分层。

只要出现“一起松几个参数试试”，这一组就应判偏。

### 4.5 题 12：综合表达题

现场只核对一句话是否同时包含：

1. 类型判断。
2. 机制解释。
3. 下一步动作。

如果只说“这票差一点能救”，即使方向接近，也不算合格表达。

---

## 5. 快速打档法

为了让带教现场更快，建议直接用下面 4 档判断：

| 档位 | 判断标准 | 建议动作 |
| ---- | -------- | -------- |
| A | 12 题里大部分都能给出分层清晰、动作明确的答案 | 可进入正式验收或真实复盘 |
| B | 基础题和样本分型大体稳定，但 artifact 顺序或动作纪律仍偶有混层 | 先补练习 7 到 12 |
| C | 能复述文档，但样本分型和动作选择明显不稳 | 回到案例手册和练习 3 到 11 |
| D | 基础定位就不稳，仍把 BTST 理解成阈值系统 | 回到 5 分钟简报和 30 分钟上手路径 |

如果只想看最小通过线，可以用这个简化规则：

1. 题 1、2、3、4、5、9、10、12 必须大体正确。
2. 其中任意 3 题明显混层，就不建议进入真实 BTST 任务。

---

## 6. 现场追问模板

如果新人回答太泛，可以直接追问下面 6 句：

1. 你说它是这个类型，证据更像入口问题还是评分问题。
2. 这只票为什么不能和 `300724` 放一组实验。
3. 你现在说的动作，属于 admission、score frontier 还是 blocked release。
4. 你为什么先看这个 artifact，而不是另一个。
5. 如果这条动作要保持低污染，你准备看哪个 guardrail。
6. 这句话里，哪部分是类型判断，哪部分是下一步动作。

这组追问的目的不是增加难度，而是逼出“是否真的分层”。

---

## 7. 一句话总结

这张速评卡真正要核对的不是名词记忆，而是新人能不能在最短时间内把 BTST 的定位、样本类型、artifact 顺序和下一步动作说对。只要这四件事说对，带教现场就能快速判断他是否已经接近可用。
