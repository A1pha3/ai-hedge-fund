# BTST AI 助手优化执行手册

适用对象：负责协助研究员完成 BTST 定位、实验、验证和文档沉淀的 AI 助手，也适合把优化任务拆给自动化代理前先做约束定义的研究员。

这份文档解决的问题：让 AI 助手在执行 BTST 优化任务时，不再凭感觉乱试，而是按固定闭环工作，确保每一步都可归因、可验证、可交接。

---

## 1. AI 助手的职责边界

### 1.1 该做什么

AI 助手应负责：

1. 读现有 artifacts、脚本和文档，先做问题分型。
2. 明确本轮唯一实验主题。
3. 找到最小可调参数或脚本入口。
4. 先做 replay，再做真实窗口验证。
5. 汇总结果，沉淀为研究可消费的结论文档。

### 1.2 不该做什么

AI 助手不应：

1. 在没有 baseline 的情况下直接改默认参数。
2. 同一轮同时推动 admission、threshold、penalty、structural conflict 多条线。
3. 只因为某个数变大，就宣称策略变好。
4. 把 `blocked` 样本和 `rejected` 样本混在一起处理。
5. 在没有真实窗口验证前，就建议升级默认值。

---

## 2. AI 助手的标准工作流

### 第 1 步：确认输入和目标

why：没有边界，AI 助手很容易把任务越做越散。

what：先确认四件事：

1. 本轮研究窗口
2. target mode
3. baseline report 或 replay 输入
4. 用户最关心的是覆盖、质量、还是某个具体 ticker

how：在开始任何修改前，先把这四项写成一段任务定义。

### 第 2 步：先做问题分型

why：不同问题对应完全不同的工具。

what：先判断本轮属于哪一类：

1. 供给问题
2. admission 问题
3. score frontier 问题
4. structural conflict 问题
5. execution 承接问题

how：优先读取：

1. `selection_snapshot.json`
2. `selection_target_replay_input.json`
3. `selection_review.md`
4. `daily_events.jsonl`
5. 已有分析 markdown / json

### 第 3 步：选唯一实验主题

why：只有单主题实验，结果才有解释力。

what：这一轮只能在下面选一个：

1. Layer B 供给
2. short trade boundary admission
3. threshold frontier
4. penalty frontier
5. structural conflict release
6. candidate entry semantics

how：如果发现用户的问题跨了两层，优先选更上游的一层。

### 第 4 步：先做 replay，不先改主线默认值

why：replay 成本最低，最适合先验证方向。

what：根据问题类型选择 replay 模式：

1. threshold grid
2. structural variants
3. combination grid
4. candidate entry metric grid
5. penalty grid
6. penalty threshold grid

how：用 `scripts/replay_selection_target_calibration.py` 和 focused tickers 做最小变体扫描。

### 第 5 步：如果 replay 方向成立，再做 live validation

why：replay 能证明规则漂移，但不能直接证明真实窗口质量更好。

what：对受控变体跑真实窗口或最小 live 报告。

how：优先使用：

1. `scripts/run_short_trade_boundary_variant_validation.py`
2. `scripts/analyze_pre_layer_short_trade_outcomes.py`
3. `scripts/analyze_short_trade_boundary_score_failures.py`
4. `scripts/analyze_short_trade_boundary_score_failures_frontier.py`

### 第 6 步：最后产出结构化结论

why：AI 助手不是为了“跑完命令”，而是为了帮助研究员做下一步决策。

what：最终至少输出：

1. 本轮为什么做
2. 本轮只改了什么
3. replay 说明了什么
4. 真实窗口说明了什么
5. 下一轮最合理动作是什么

how：按 [04-btst-experiment-template.md](./04-btst-experiment-template.md) 填写。

---

## 3. AI 助手的决策树

### 3.1 如果目标是“覆盖不够”

先问：

1. 是 `layer_b_count` 不够，还是 `short_trade_boundary candidate_count` 不够？
2. 是 boundary floor 卡得太严，还是上游本来就没合格样本？

然后：

1. 如果上游都很冷，先回到 Layer B。
2. 如果上游不冷但 boundary 少，先做 admission 诊断。

### 3.2 如果目标是“很多 score fail”

先问：

1. 这些样本离 near-miss 近不近？
2. 主负贡献是阈值问题还是 penalty 问题？

然后：

1. 存在 threshold-only rescue 样本，先做 threshold frontier。
2. 大多数都远离 near-miss，直接做 penalty frontier 或 score construction 审查。

### 3.3 如果目标是“很多 blocked”

先问：

1. 是不是同一种 structural conflict 导致？
2. 是否存在低成本 near-miss rescue row？

然后：

1. 如果只有个别样本能救，做 case-based release。
2. 如果整个 blocked 簇都没有 rescue row，不做 cluster-wide 放宽。

### 3.4 如果目标是“某个 ticker 为什么一直救不回来”

先问：

1. 它是 candidate entry 问题、penalty 问题，还是结构本身不匹配？
2. 它是否在多个 trade_date 重复出现？

然后：

1. 用 focused ticker 诊断。
2. 看最小 adjustment cost。
3. 如果需要极端放宽才能救，不建议继续。

---

## 4. AI 助手每轮必须遵守的 12 条纪律

1. 每轮只做一个主题。
2. 先解释 why，再说 what，最后给 how。
3. 每次实验都保留 baseline。
4. 不混用 `blocked` 和 `rejected`。
5. 不把 admission floor 和 target threshold 一起放松。
6. 不把某个单日结果当成稳定规律。
7. 不用“看起来更热”替代“质量更好”。
8. 不用局部 ticker 的成功，包装成全局默认策略建议。
9. 如果样本量太小，要明确写出局限性。
10. 如果 replay 和 live validation 结论不一致，以 live validation 为更高优先级信号。
11. 任何默认值升级建议，都必须写明风险与副作用。
12. 结束时一定要给出“下一轮只做什么，不做什么”。

---

## 5. AI 助手推荐输出格式

每轮结束时，建议统一输出成 6 段：

1. 任务定义
2. 问题分型
3. 本轮变体
4. replay 结果
5. live 结果
6. 下一轮建议

这样做的目的：

1. 研究员读起来快。
2. 下一位 AI 助手容易接手。
3. 结论容易沉淀成长期文档。

---

## 6. AI 助手最常犯的 8 个错误

1. 看到 near-miss 少，就先降阈值。
2. 看到 blocked 多，就放 structural conflict。
3. 看到 `300724` 能救，就想全局放松同类 blocker。
4. 看到 `300502` 被过滤，就继续走 penalty 路线。
5. 只做 focused ticker，不看整个窗口副作用。
6. 只做 replay，不看次日结果。
7. 跳过 artifacts，直接读结论文档复述。
8. 不更新实验记录，导致后续重复劳动。

---

## 7. AI 助手可直接套用的最小提示模板

```text
目标：优化 BTST 当前窗口的 [唯一主题]。

已知输入：
1. baseline report / replay 输入：...
2. 评估窗口：...
3. target mode：...
4. focus ticker（可选）：...

执行要求：
1. 先做问题分型，不直接改默认值。
2. 每轮只动一个机制。
3. 先做 replay，再做真实窗口验证。
4. 输出 why / what / how。
5. 最终必须给出：本轮结论、风险、副作用、下一轮唯一建议动作。
```

---

## 8. 一句话总结

AI 助手在 BTST 优化里的最佳角色，不是“自动乱扫参数”，而是作为一个纪律化研究执行器：先分型、再选唯一杠杆、再做 replay 和 live 双验证，最后把结果压缩成可决策的结论。
