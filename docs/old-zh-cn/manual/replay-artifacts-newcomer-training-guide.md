# Replay Artifacts 新人培训讲义

> 配套阅读：
>
> 1. [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)
> 2. [Replay Artifacts 值班速查卡](./replay-artifacts-duty-cheatsheet.md)
> 3. [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
> 4. [Replay Artifacts 分析报告术语解析手册](./replay-artifacts-report-terminology-guide.md)
> 5. [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)
> 6. [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)
> 7. [Replay Artifacts 新人上手验收评分表](./replay-artifacts-onboarding-readiness-scorecard.md)
> 8. [Replay Artifacts 试用验收计划](./replay-artifacts-trial-acceptance-plan.md)

## 1. 这份讲义解决什么问题

当前 Replay Artifacts 相关文档已经很多，但对新人来说，真正困难的通常不是“没有文档”，而是“知道每份文档存在，却不知道先看哪一份，也不知道什么叫做学会”。

这份讲义就是为这个问题准备的。

它的目标不是再重复一遍所有术语，也不是把长手册压缩成几句口号，而是把新人从“第一次打开页面有点懵”带到“能够独立完成一次最小复核闭环”。

所谓最小复核闭环，至少包括四件事：

1. 知道 Replay Artifacts 页面在系统里到底扮演什么角色。
2. 能把 report、trade date、selected、execution blocker、feedback、workflow 这些层级分开看。
3. 能写出一句不混淆研究结论、执行结论和流程结论的话。
4. 能把一次真实使用留下合格的 evidence，而不是只停留在口头判断。

如果你读完这份讲义后，仍然只能说“这个字段我见过”，那还不算真正上手。真正上手的标准是：你能独立读一份 report，并把判断沉淀到 feedback、observation 或 weekly review 里。

如果你需要把“感觉已经会上手了”变成一张可交接、可打分、可复核的验收结果，请继续使用 [Replay Artifacts 新人上手验收评分表](./replay-artifacts-onboarding-readiness-scorecard.md)。

---

## 2. 学习目标

读完本讲义后，你应该能够做到：

1. 用一句话说明 Replay Artifacts 不是交易下单页，而是研究复核工作台。
2. 用五层结构解释一份 report 是如何被阅读的。
3. 区分“选股被选中”和“执行层允许承接”不是一回事。
4. 区分 `review_status`、`workflow_status` 与 `ready_for_adjudication` 的职责边界。
5. 在真实样本上写出一条合格的 `draft` 结论，并判断它应该进入 observation、issue log 还是 weekly review。

---

## 3. 先建立最小心智模型

### 3.1 这页到底是什么

先记住一句最重要的话：

Replay Artifacts 不是选股引擎本身，而是选股结果的研究复核工作台。

这句话为什么重要：

1. 如果你把它当成“今天应该买什么”的页面，就会把很多研究字段误读成交易信号。
2. 如果你把它当成纯日志页，又会低估 feedback、workflow 和 cache benchmark 这些证据层的价值。

所以它的正确定位是：

1. 消费已经落盘的 report 证据。
2. 帮你判断问题更像出在选股、执行、流程还是运行质量。
3. 把人工判断沉淀成后续可以复盘和治理的结构化记录。

### 3.2 五层结构

新人最容易犯的错误，是把所有字段都当成同一层信息。正确做法是先分层。

一份 Replay Artifacts report，至少有五层：

1. Report 层：这次运行是谁、覆盖了什么窗口、产物齐不齐。
2. Trade Date 层：某一天的决策切片。
3. Selection Artifact 层：这一天留下的 snapshot、review、feedback。
4. Candidate 层：某一只股票为什么被选中、为什么没进下一层、为什么被阻塞。
5. Feedback / Workflow 层：人怎么写结论，团队怎么流转结论。

只要层级不分清，后面几乎一定会误判。

### 3.3 三类结论必须分开写

新人写结论时，最常见的问题不是字段看不懂，而是三类结论写在了一句话里。

你必须强制区分：

1. 研究结论：这只票为什么被认为值得重点看。
2. 执行结论：这只票为什么没有进入 buy order，或者为什么被执行层挡住。
3. 流程结论：这条人工结论现在处于 `draft`、`final` 还是 `ready_for_adjudication`。

这三类结论的边界一旦混掉，后续无论是做周度复盘，还是做 backlog 映射，都会失真。

---

## 4. 新人上手顺序

### 4.1 第 0 步：只记一个判断标准

你第一天不需要会所有字段，但必须会判断下面这件事：

当前看到的现象，更像是选股问题、执行问题、流程问题，还是运行证据问题。

为什么这一步最先学：

1. 因为它决定你后面应该继续看 `selected`、`execution_bridge`、`workflow queue`，还是 `cache_benchmark`。
2. 如果这个方向先错了，越看细节越容易走偏。

### 4.2 第 1 步：先读短入口，再读长手册

推荐新人第一轮的阅读顺序如下：

1. 先看 [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)，建立最小使用路径。
2. 再看 [Replay Artifacts 值班速查卡](./replay-artifacts-duty-cheatsheet.md)，学会按问题类型反查字段。
3. 遇到术语不稳时，再查 [Replay Artifacts 分析报告术语解析手册](./replay-artifacts-report-terminology-guide.md)。
4. 当你准备真正开始每天使用页面时，再进入 [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)。

这条顺序背后的逻辑是：

1. quickstart 先解决“我应该怎么开始”。
2. duty cheatsheet 解决“我先看哪里才不乱”。
3. terminology guide 解决“这个字段为什么存在”。
4. full manual 解决“我该如何稳定地完成整条复核流程”。

### 4.3 第 2 步：用一份真实样本建立手感

不要一开始就随机点 report。推荐先用有代表性的真实样本：

1. `paper_trading_20260311_selection_artifact_blocker_validation_20260323`
2. `paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323`
3. `paper_trading_probe_20260205_cache_benchmark_20260325`

为什么先看这几份：

1. 第一份适合看 selected 进入研究重点但被执行层 blocker 挡住的情形。
2. 第二份适合看长窗口下 Layer B scarcity 与 near-miss 的整体结构。
3. 第三份适合理解 cache benchmark 是运行证据，不是投资结论。

---

## 5. 第一天应该学会的 4 个判断动作

### 5.1 动作一：判断这份 report 值不值得下钻

先看：

1. `selection_artifact_overview.available`
2. `blocker_counts`
3. `feedback_summary`
4. `cache_benchmark_overview`

你要回答的问题不是“这份 report 好不好”，而是：

1. 有没有可复核的日级样本。
2. 主矛盾更像选股、执行、流程还是运行证据。

### 5.2 动作二：判断 selected 为什么没有变成 buy order

先看：

1. `selected[*].score_final`
2. `selected[*].layer_b_summary.top_factors`
3. `selected[*].layer_c_summary`
4. `selected[*].execution_bridge`

你必须学会写出这样的句子：

1. 该样本已进入研究重点，但当前没有被执行层承接，主因是 `block_reason` 对应的执行约束，而不是选股失败。

### 5.3 动作三：判断 near-miss 是弱样本，还是边界样本

先看：

1. `rejected[*].score_final`
2. `rejection_reason_codes`
3. `rejection_reason_text`
4. `funnel_diagnostics.filters.watchlist`

为什么这一步重要：

1. 边界样本更适合进入阈值复盘或周度讨论。
2. 明显弱样本则不值得过度解释，更不应该占用过多 workflow 精力。

### 5.4 动作四：判断这条人工结论该写到哪里

请按下面规则分流：

1. 已经跑通链路，但有轻微语义摩擦，写 observation。
2. 真正阻断使用，写 issue log。
3. 结论已经稳定，可进入 `final` 或 `ready_for_adjudication`，进入 weekly review。
4. 只是个人初步判断，还未形成稳定共识，先写 `draft` feedback。

---

## 6. 建议的 30 分钟培训流程

如果你要带一位新同学快速上手，建议按下面节奏做首轮培训。

### 6.1 第 1 段：10 分钟建立定位

目标：让对方知道这页不是下单页。

讲清三件事：

1. Replay Artifacts 消费的是已落盘 report，而不是实时生成结果。
2. 页面最重要的价值是分离研究、执行与流程三个层面。
3. 一条不准确的结论，往往不是字段没看见，而是层级混掉了。

### 6.2 第 2 段：10 分钟演示阅读顺序

目标：让对方形成固定阅读节奏。

建议现场演示：

1. 先看 report 概览。
2. 再看 `selection_artifact_overview`。
3. 下钻 trade date。
4. 先读 selected，再读 execution bridge。
5. 最后再谈 feedback 与 workflow。

培训时不要反过来从某个 workflow 状态开始讲，因为新人很容易把 `ready_for_adjudication` 听成“推荐买入”。

### 6.3 第 3 段：10 分钟让新人自己写一句话

目标：检验是否真的理解。

要求对方针对一个真实样本写一句话，且必须同时满足：

1. 写清这是研究结论、执行结论，还是流程结论。
2. 至少引用 2 个字段作为证据。
3. 不使用“系统不会选股”“系统建议买入”这类混层表达。

推荐模板：

1. `trade_date / symbol` 在 `字段 A + 字段 B` 上表现为 `事实`，因此当前更支持“`正确归类`”，而不是“`常见误判`”。

---

## 7. 建议的 2 小时上手作业

如果希望对方不是“听懂了”，而是“真的能独立做”，建议安排一轮 2 小时上手作业。

### 7.1 作业一：读一份 report，写一条 report 级判断

要求：

1. 先判断主矛盾更像选股、执行、流程还是运行证据。
2. 至少引用 3 个 report 级字段。
3. 不允许直接写收益好坏替代结构判断。

### 7.2 作业二：读一个 selected 样本，写一条执行判断

要求：

1. 明确该样本是否已被研究层选中。
2. 明确是否被执行层承接。
3. 如果没有承接，写出 blocker 语义，而不是泛泛地说“没买”。

### 7.3 作业三：读一个 near-miss 样本，判断是否值得进入周度复盘

要求：

1. 明确它是边界样本还是弱样本。
2. 写出你引用的 rejection 证据。
3. 给出“进入 weekly review”或“不进入”的判断。

### 7.4 作业四：把一次使用证据分流到正确载体

要求：

1. 如果是链路通过但仍有摩擦，写到 [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md)。
2. 如果是阻断性缺陷，写到 [Replay Artifacts 试用问题记录模板](./replay-artifacts-trial-issue-log-template.md)。
3. 如果是已经稳定的周度结论，写到 [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md) 对应流程里。

---

## 8. 常见新人误判与纠正方式

### 8.1 误判一：selected 就等于建议买入

纠正：

1. `selected` 只说明进入研究重点，不说明执行层一定承接。
2. 是否进入实际执行，还要看 `execution_bridge` 与 `buy_orders`。

### 8.2 误判二：没进 buy orders 就说明选股失败

纠正：

1. 很多时候是执行层保护在生效，例如 reentry、risk 或 position blocker。
2. 这类样本常常恰恰是最有研究价值的样本，因为它证明系统的研究判断和执行保护是两套不同机制。

### 8.3 误判三：workflow 状态就是投资观点

纠正：

1. `draft`、`final`、`ready_for_adjudication` 说的是人工结论流转成熟度。
2. 它们不是 bullish、bearish、neutral 的替代词。

### 8.4 误判四：cache benchmark 好，说明策略结论也更可信

纠正：

1. cache benchmark 回答的是运行证据和缓存复用，不回答投资正确性。
2. 它能增强你对运行质量的信心，但不能替代研究判断。

---

## 9. 遇到不同问题时，应该回到哪份文档

如果你不知道接下来该看哪份文档，不要盲翻。按问题类型回去。

1. 我完全不知道从哪里开始：看 [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)。
2. 我已经在页面里了，但想快速定位该看哪些字段：看 [Replay Artifacts 值班速查卡](./replay-artifacts-duty-cheatsheet.md)。
3. 我知道要看这个字段，但不明白它为什么存在：看 [Replay Artifacts 分析报告术语解析手册](./replay-artifacts-report-terminology-guide.md)。
4. 我准备每天真实使用页面：看 [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)。
5. 我不知道 feedback 应该怎么打标签：看 [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)。
6. 我需要把日常结论推进成周度结论：看 [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)。
7. 我需要判断一次试用现象该记 observation 还是 issue：看 [Replay Artifacts 试用验收计划](./replay-artifacts-trial-acceptance-plan.md) 和 [Replay Artifacts 试用观察记录表](./replay-artifacts-trial-observation-sheet.md)。
8. 我需要把结论映射到优化动作：看 [研究结论到优化 Backlog 的转换手册](./research-conclusion-to-optimization-backlog-handbook.md)。

---

## 10. 带教者交接清单

如果你是带教者，建议不要只把链接发给新人，而是按下面清单交接。

### 10.1 交接前必须讲清楚的话

1. Replay Artifacts 是复核工作台，不是交易建议页。
2. 先分清研究、执行、流程三类结论，再写任何一句话。
3. 不确定时先写 `draft`，不要硬写 `final`。

### 10.2 交接时必须现场演示的动作

1. 切换一个有 selection artifacts 的 report。
2. 切换一个 trade date。
3. 找到一个 selected 样本和一个 blocker 样本。
4. 现场写入一条 feedback 或解释为什么先只做 observation。

### 10.3 交接后必须检查的产出

1. 对方是否写出过一条不混层的结论。
2. 对方是否知道 observation、issue log、weekly review 的分流规则。
3. 对方是否知道什么时候该回去查长手册，而不是继续靠猜。

---

## 11. 自测题

如果下面 6 题里有 2 题答不稳，就不算真正上手。

1. `selected` 和 `buy_orders` 的区别是什么。
2. 为什么 `review_status` 不能直接当作投资结论。
3. 什么情况下应该优先看 `execution_bridge`。
4. 什么情况下应该写 observation，而不是 issue。
5. `reuse_confirmed = true` 说明了什么，又没有说明什么。
6. 你如何用一句话区分“研究层正确但执行层未承接”和“研究层本身就不成立”。

---

## 12. 建议的第一周学习路径

如果你是新人，建议第一周按下面节奏推进，而不是第一天把所有文档一次性看完。

### 第 1 天

1. 读本讲义。
2. 读 [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)。
3. 跟着带教者完成一次页面 walkthrough。

### 第 2 天

1. 读 [Replay Artifacts 值班速查卡](./replay-artifacts-duty-cheatsheet.md)。
2. 读一个 selected 样本和一个 blocker 样本。
3. 写出两句不混层的判断。

### 第 3 天

1. 查 [Replay Artifacts 分析报告术语解析手册](./replay-artifacts-report-terminology-guide.md)。
2. 补齐自己前两天看不稳的术语。

### 第 4 天

1. 读 [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)。
2. 写一条合格的 `draft` feedback。

### 第 5 天

1. 读 [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)。
2. 试着把本周的一个样本推进到“是否值得进入 weekly review”的判断。

到这一步，才算从“会打开页面”进入“会留下有效研究证据”。

如果你是带教者，建议在这五天路径走完后，立刻补一份 [Replay Artifacts 新人上手验收评分表](./replay-artifacts-onboarding-readiness-scorecard.md)，不要只停留在口头印象。
