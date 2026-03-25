# Replay Artifacts 周度复盘工作流手册

> 配套阅读：
>
> 1. [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)
> 2. [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
> 3. [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)
> 4. [研究结论到优化 Backlog 的转换手册](./research-conclusion-to-optimization-backlog-handbook.md)
> 5. [Replay Artifacts 案例手册：2026-03-11 的 300724 为什么入选但未买入](./replay-artifacts-case-study-20260311-300724.md)

## 1. 这份手册解决什么问题

前面的几份文档已经解决了三件事：

1. 页面怎么用。
2. 标签怎么打。
3. 单个 blocker 样本怎么判。

但团队协作里还有一个常见断点：

1. 每天有人写了很多 `draft`。
2. 一周后没有人系统回看。
3. `final` 很少产生。
4. `adjudicated` 更没有明确入口。

结果就是：

1. 页面有人看过。
2. feedback 也有人写过。
3. 但这些记录没有真正变成“可累计的研究资产”。

这份手册专门解决这个问题，目标是给团队一套最小可执行的周度复盘工作流，让 Replay Artifacts 不只是日常浏览页，而是一个能持续沉淀结论的复盘系统。

当前代码状态补充：Replay Artifacts 页面已经提供三个直接服务于这套流程的入口。

1. Batch Label Workspace：可在当前 trade date 下对多只 watchlist / near-miss 样本一次写入同一组 feedback。
2. Inspector 内的 Pending Draft Queue：可按最新 review_status 查看当前 report 里还停留在 `draft` 的样本。
3. Cross-Report Workflow Queue：可切换 `my queue`、`unassigned`、`all` 查看跨 report 待办，并直接执行 `Assign to me` / `Unassign`。

---

## 2. 周度复盘和日度浏览有什么不同

### 2.1 日度浏览回答的是“今天怎么看”

日度浏览更关注：

1. 今天选了谁。
2. 今天谁被执行层拦住了。
3. 今天哪些 near-miss 值得记一笔。

所以它的产物通常是：

1. `draft` feedback。
2. 少量 `final`。
3. 当天的人工判断备忘。

### 2.2 周度复盘回答的是“这一周系统到底重复暴露了什么问题”

周度复盘更关注：

1. 某类 blocker 是否一再重复出现。
2. 哪些标签反复出现在 selected 或 near-miss 中。
3. 哪些 `draft` 已经足够升级成 `final`。
4. 哪些样本需要团队统一口径，升级成 `adjudicated`。

所以它的产物应该是：

1. 一组稳定的 `final` 记录。
2. 少量真正需要裁决的 `adjudicated` 样本。
3. 一份系统问题归因清单。

---

## 3. 一周里谁该做什么

最小建议角色分工如下。

### 3.1 日常复核人

职责：

1. 每日浏览当日 report 和 trade date。
2. 为重点票先写 `draft`。
3. notes 里写清楚初步归因。

### 3.2 周度汇总人

职责：

1. 汇总这一周的高频 blocker、near-miss 和标签分布。
2. 识别哪些 `draft` 已经足以升级为 `final`。
3. 把争议样本提给更高层级做统一判断。

### 3.3 裁决人或小组负责人

职责：

1. 对争议样本统一口径。
2. 决定是否需要标记为 `adjudicated`。
3. 将结论转化为后续规则、阈值或解释质量改进方向。

如果团队规模很小，一个人也可以兼任这三个角色。但脑中仍然要分清这三层职责，否则容易把“当天看到什么”和“这一周最终认定什么”混为一谈。

---

## 4. 推荐周度节奏

### 4.1 周一到周五：先留 `draft`

每日建议动作：

1. 选当天或最近运行的 report。
2. 重点看 selected、execution bridge、near-miss、funnel。
3. 对最重要的样本写 `draft`。
4. 不求当天就把所有结论写满，但必须把初步归因留下。

为什么这样做：

1. 当天信息最鲜活。
2. 很多判断如果不当天记录，一周后很难回忆当时为什么在意这只票。
3. 周度复盘依赖这些 `draft` 作为原始材料。

### 4.2 周末或周会前：做一次集中复盘

集中复盘时建议：

1. 选一个多日窗口 report，或者按 trade date 逐日切换。
2. 先看 Inspector 里的 Pending Draft Queue，确定这一周还没有推进的样本。
3. 把这一周所有重点 `draft` 重新过一遍。
4. 对重复出现的 blocker 和标签做归类。
5. 对同类样本优先使用 Batch Label Workspace 做批量推进，避免逐条重复填写。
6. 把稳定结论升级成 `final`。
7. 把仍然有争议、可能影响规则判断的样本提为 `adjudicated` 候选。

如果周度汇总人需要先认领工作，再集中推进，建议先看 Cross-Report Workflow Queue：

1. 先切到 `unassigned`，把本周准备处理的样本认领到自己名下。
2. 再切回 `my queue`，按 latest_review_status 和 primary_tag 连续处理。
3. 已不再由自己继续推进的样本直接 `Unassign`，避免队列失真。

### 4.3 周会后：只保留少量 `adjudicated`

`adjudicated` 不应该很多。

推荐原则：

1. 只有真的有争议，或会影响后续策略判断的样本，才值得升级。
2. 如果只是普通日常记录，停在 `final` 就够了。

---

## 5. 周度复盘前要先准备什么

开始之前，建议准备三类东西。

### 5.1 一个有连续 trade date 的 report

优先选择：

1. trade date 足够连续。
2. selection_artifact_overview 可用。
3. 同时包含 selected、near-miss 和 blocker 的窗口。

例如这类多日窗口报告更适合周度复盘：

1. `paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323`

### 5.2 一周内已写下的 `draft` 记录

如果一周里完全没人写 `draft`，周度复盘会退化成纯凭记忆回看，质量会差很多。

### 5.3 一个统一的问题分类框架

建议至少按下面五类记录问题：

1. Layer B 问题
2. Layer C 问题
3. Execution 问题
4. Threshold 问题
5. Explainability 问题

这五类并不直接等同于标签，但它们能帮助团队在周会里保持讨论结构。

---

## 6. 标准周度复盘流程

### 6.1 第一步：先看这一周哪些问题重复出现

先不要急着逐票下结论，先看模式。

优先观察：

1. 哪些 blocker 反复出现在 `buy_orders` 过滤层。
2. 哪些 rejection reason 反复出现在 near-miss。
3. 哪些标签一周内反复被打到同一类样本上。

如果某一类问题只出现一次，它更像个案。
如果一类问题连续出现多次，它更像系统性线索。

### 6.2 第二步：再看 selected 的质量是否稳定

重点问：

1. 这周 selected 是否大多逻辑清楚。
2. Layer B 的 top factors 是否越来越像噪声。
3. Layer C 的分歧是否在某些票上反复过大。

如果 selected 本身反复出现 `weak_edge`、`event_noise_suspected`，问题更可能在选股层。

### 6.3 第三步：单独拆开执行层阻塞

这是周度复盘里最容易被忽略，但最重要的一步。

重点问：

1. 这周有多少票“研究通过但执行不承接”。
2. 它们主要卡在什么 blocker。
3. 这些 blocker 是合理防守，还是过度抑制。

如果大量样本都是 selected 以后卡在 `buy_orders`，那就不要误把这周的问题总结成“系统不会选股”。

### 6.4 第四步：回看 near-miss，找阈值误伤

near-miss 的价值不是补充信息，而是帮助判断系统边界。

重点问：

1. 哪些票几乎每次都差一点点。
2. 它们的 rejection reason 是否高度相似。
3. 它们是否构成 `threshold_false_negative` 的稳定样本池。

### 6.5 第五步：把 `draft` 分成三堆

周度复盘时，建议把一周内的 `draft` 粗分为三类：

1. 可以直接升级为 `final`
2. 保持 `draft`，等待更多证据
3. 提交团队裁决，候选升级为 `adjudicated`

---

## 7. 什么样的 `draft` 应该升级为 `final`

满足以下多数条件时，通常就够了：

1. 你已经回看了 selected、execution bridge、near-miss 和 funnel。
2. 你的 notes 能清楚说出归因层级。
3. 你的主标签和补充标签没有互相打架。
4. 这条结论在一周内没有被新的证据明显推翻。

一个典型 `final` 记录应该做到：

1. 别人读完你的 notes，不需要再口头追问“你到底想表达什么”。
2. 后续统计时，这条记录可以被稳定归类。

---

## 8. 什么样的样本才值得 `adjudicated`

不要把 `adjudicated` 当成“更认真”。

它真正适合的是：

1. 团队内明显分歧的样本。
2. 会直接影响阈值、规则或解释层优化方向的样本。
3. 兼具研究层与执行层争议，单人难以下结论的样本。

例如：

1. 一部分人认为它是 `threshold_false_negative`。
2. 另一部分人认为它其实是执行层 blocker，不该动阈值。

这类样本如果不统一口径，后续策略讨论会一直反复兜圈。

---

## 9. 周会里应该讨论什么，不该讨论什么

### 9.1 应该讨论什么

1. 高频 blocker 是否合理。
2. 高频弱标签是否说明选股层在退化。
3. near-miss 是否暴露阈值切线问题。
4. 哪些解释字段仍然不足以支撑人工判断。

### 9.2 不该讨论什么

1. 单个样本的偶然涨跌。
2. 没有结构化证据支持的主观偏好。
3. 只因为“今天没买到”就要求直接放宽所有执行规则。

周会的重点应该是“模式”，不是“情绪”。

---

## 10. 推荐周度输出模板

每周复盘结束后，至少产出下面四类结论。

### 10.1 本周高频问题

例如：

1. `blocked_by_reentry_score_confirmation` 多次出现。
2. `weak_edge` 在 selected 中出现比例偏高。

### 10.2 本周稳定正样本

也就是：

1. 可以保留为 `high_quality_selection` 或 `thesis_clear` 的代表样本。

### 10.3 本周边界样本

也就是：

1. 值得继续观察的 `threshold_false_negative`。
2. 需要继续确认的 execution blocker 样本。

### 10.4 本周需要进入后续优化 backlog 的系统问题

建议直接写成：

1. Layer B
2. Layer C
3. Execution
4. Threshold
5. Explainability

这能让研究结论直接对接后续工程或策略优化。

如果你已经能把问题归到这五类，但还缺少“如何把一句复盘结论改写成具体 backlog 动作”的模板，继续阅读 [研究结论到优化 Backlog 的转换手册](./research-conclusion-to-optimization-backlog-handbook.md)。

---

## 11. 一个最小周度闭环示例

一个最小可执行版本可以非常朴素：

1. 每天写 3 到 5 条最重要的 `draft`。
2. 周末在多日 report 中重新过一遍这些样本。
3. 升级其中最稳定的记录为 `final`。
4. 只把 1 到 3 条真正争议样本提为 `adjudicated` 候选。
5. 输出一份下周最值得观察的问题清单。

如果这 5 步能长期坚持，团队对系统问题的认知会显著比“每天看看页面就算了”稳定得多。

---

## 12. 和其他手册的关系

建议把这几份文档按下面顺序组合使用：

1. [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)
2. [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
3. [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)
4. 本文
5. [Replay Artifacts 案例手册：2026-03-11 的 300724 为什么入选但未买入](./replay-artifacts-case-study-20260311-300724.md)

这样从“会点页面”到“会统一打标签”再到“会组织团队周度复盘”，链路就是完整的。

---

## 13. 最终原则

周度复盘不是为了把日常 feedback 再抄一遍，而是为了做三件更高价值的事：

1. 把 `draft` 变成稳定结论。
2. 把个案变成模式。
3. 把模式变成下一步优化输入。

只要这三件事能稳定发生，Replay Artifacts 就不只是一个回看页面，而会逐步成为选股优先优化框架里的人工研究中台。
