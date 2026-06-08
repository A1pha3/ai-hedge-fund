# BTST 调参与验证作战手册

适用对象：需要优化 BTST 默认规则的研究员、工程师、AI 助手。

这份文档解决的问题：把当前 BTST 的调参从“见数改数”变成“先诊断、后选杠杆、再做 replay 和真实窗口验证”的闭环方法。

建议搭配阅读：

1. [01-btst-complete-guide.md](./01-btst-complete-guide.md)
2. [../26-layer-b-parameter-tuning-playbook.md](../26-layer-b-parameter-tuning-playbook.md)
3. [../../product/arch/dual_target_system/short_trade_target_rule_spec.md](../../product/arch/dual_target_system/short_trade_target_rule_spec.md)
4. [../../product/arch/dual_target_system/short_trade_target_metrics_and_validation.md](../../product/arch/dual_target_system/short_trade_target_metrics_and_validation.md)

---

## 1. 先讲结论：BTST 调参的总原则

如果只保留最重要的原则，请记住下面 10 条：

1. 先定位问题层级，再决定动哪个参数。
2. 先修语义和结构，再修阈值。
3. 先修供给质量，再修供给数量。
4. 先用 replay 做低成本验证，再做 live validation（真实窗口验证）。
5. 每轮只动一类机制，不做组合拳。
6. 先看新增样本的次日质量，再看通过数。
7. `blocked` 和 `rejected` 必须分开调，不要混成一个集合。
8. `short_trade_boundary` 准入问题和 `short_trade_target` 分数前沿问题不是一回事。
9. 真实可交易性必须纳入判断，不允许只看规则分数或纸面收益。
10. 最优参数通常是稳定区间，不是某个窗口里最热的单一点。

---

## 2. 为什么很多 BTST 调参会失败

最常见的失败方式，不是因为实验太少，而是因为把不同层的问题混为一谈。

### 2.1 错把供给不足当成阈值问题

症状：BTST selected 很少，于是直接下调 `select_threshold`。

风险：

1. 如果真正问题是 Layer B 供给太冷，降阈值只会把边缘噪声放进来。
2. 如果真正问题是 penalty 太重，单纯降阈值会掩盖结构问题。

### 2.2 错把 blocked 当成 near-miss

症状：看到很多样本没通过，就一律想做 threshold rescue。

风险：

1. `blocked` 往往意味着结构冲突，不该优先用阈值救。
2. 这类样本更应该先做 structural variant 或 penalty 审查。

### 2.3 错把准入问题和正式评分问题混在一起

症状：short trade boundary 候选少，就同时放宽预选 floor 和 target threshold。

风险：

1. 你会失去归因能力。
2. 根本无法判断增量来自准入层、正式评分层，还是只是整体放热。

---

## 3. 调参前先做问题分型

当前 BTST 问题大致分为五类。先分型，再动手。

### 3.1 类型 A：Layer B 供给过冷

典型症状：

1. `layer_b_count` 很低。
2. `high_pool` 太少。
3. short trade boundary 几乎没有上游可选样本。

优先检查：

1. Layer B 语义和重评分配是否过冷。
2. heavy leg 覆盖是否不足。
3. `FAST_AGENT_SCORE_THRESHOLD` 是否过早截断。

### 3.2 类型 B：short_trade_boundary 准入太严

典型症状：

1. `upstream_candidate_count` 不低，但 `candidate_count` 很少。
2. `filtered_reason_counts` 高度集中在某个 floor。

优先检查：

1. `candidate_score_min`
2. `breakout_freshness_min`
3. `trend_acceleration_min`
4. `volume_expansion_quality_min`
5. `catalyst_freshness_min`

### 3.3 类型 C：BTST 分数前沿太严

典型症状：

1. 准入已经通过。
2. 但大量样本落在 `rejected_short_trade_boundary_score_fail`。
3. 很多样本距离 near-miss 仍有明确 gap。

优先检查：

1. `select_threshold`
2. `near_miss_threshold`
3. penalty 权重
4. 是否存在纯阈值救援样本

### 3.4 类型 D：structural conflict 或 penalty 过重

典型症状：

1. 大量样本被 `blocked`。
2. 负贡献主要集中在 stale、overhead、extension 或 Layer C conflict。

优先检查：

1. `hard_block_bearish_conflicts`
2. `stale_penalty_block_threshold`
3. `overhead_penalty_block_threshold`
4. `extension_penalty_block_threshold`
5. 各 penalty weight

### 3.5 类型 E：研究上通过，但执行承接差

典型症状：

1. BTST `selected` 增多了。
2. 但 `included_in_buy_orders` 没明显改善。
3. 或 T+1 表现不错，但实际 buy order 承接差。

优先检查：

1. execution bridge
2. watchlist 到 buy order 的转化
3. T+1 confirmation 的近似约束

---

## 4. BTST 可以调的参数分成哪几类

### 4.1 第一类：Layer B 供给参数

why：BTST 的上游供给主要由 Layer B 决定。

what：当前常见抓手包括：

1. `DAILY_PIPELINE_FAST_SCORE_THRESHOLD`
2. `SCORE_BATCH_TECHNICAL_MAX_CANDIDATES`
3. `SCORE_BATCH_FUNDAMENTAL_MAX_CANDIDATES`
4. `SCORE_BATCH_EVENT_SENTIMENT_MAX_CANDIDATES`
5. `SCORE_BATCH_MIN_PROVISIONAL_SCORE`
6. `LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE`
7. `LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE`
8. `LAYER_B_ANALYSIS_QUALITY_FIRST_GUARD`
9. `LAYER_B_ANALYSIS_ENABLE_LONG_TREND_ALIGNMENT`

how：先用 Layer B 文档和现有 rule variant 比较定位，再决定是否让 BTST 调优从上游开始。

### 4.2 第二类：short trade boundary 准入参数

why：这一层决定哪些边界候选有资格进入 BTST 正式评估。

what：当前核心参数包括：

1. `DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_SCORE_BUFFER`
2. `DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_MAX_TICKERS`
3. `DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN`
4. `DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_BREAKOUT_MIN`
5. `DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_TREND_MIN`
6. `DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_VOLUME_MIN`
7. `DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_CATALYST_MIN`

how：优先配合 `analyze_short_trade_boundary_filtered_candidates.py` 和 `run_short_trade_boundary_variant_validation.py` 使用。

### 4.3 第三类：short trade target profile 参数

why：这一层决定正式目标分数如何变成 selected、near_miss、blocked 或 rejected。

what：当前核心参数包括：

1. `select_threshold`
2. `near_miss_threshold`
3. `stale_penalty_block_threshold`
4. `overhead_penalty_block_threshold`
5. `extension_penalty_block_threshold`
6. `layer_c_avoid_penalty`
7. `stale_score_penalty_weight`
8. `overhead_score_penalty_weight`
9. `extension_score_penalty_weight`
10. `hard_block_bearish_conflicts`
11. `overhead_conflict_penalty_conflicts`

how：主要通过 replay 校准脚本做 profile override，不建议第一步就改源码默认值。

### 4.4 第四类：candidate entry（候选入口）过滤策略

why：有些问题不是 target 评分本身，而是某类“弱结构候选”本来就不该进入比较池。

what：当前 replay 工具支持候选入口指标网格，按 `breakout_freshness`、`trend_acceleration`、`volume_expansion_quality`、`close_strength`、`catalyst_freshness` 做上限过滤试验。

how：适合回答“如果先把某类明显弱结构样本挡掉，会不会更稳”。

---

## 5. 标准调参流程：一步一步做什么

### 第 0 步：固定 baseline

why：没有稳定 baseline，就没有对比。

what：每轮实验至少固定下面这些信息：

1. 评估窗口
2. 目标模式，比如 `dual_target`
3. 模型 provider / name
4. 是否使用 frozen current plan replay
5. 当前默认 target profile

how：把这些信息写入实验名、输出目录和文档摘要。

### 第 1 步：先看 artifacts，不要先改代码

why：现有 artifacts 已经包含了足够多的诊断线索。

what：优先看：

1. `selection_snapshot.json`
2. `selection_review.md`
3. `selection_target_replay_input.json`
4. `daily_events.jsonl`

how：先回答三个问题：

1. 候选是不是太少。
2. 是准入层死掉，还是正式评分死掉。
3. 是 score fail，还是 structural block。

### 第 2 步：选一个唯一实验主题

why：只有单主题实验，结果才可归因。

可选主题通常只有这些：

1. Layer B 供给
2. short trade boundary 准入
3. 阈值前沿
4. 惩罚前沿
5. structural conflict release
6. 候选入口过滤

### 第 3 步：先做 replay 校准

why：replay 成本低、速度快、可批量扫网格。

what：当前最常用的 replay 模式：

1. threshold grid
2. structural variants
3. combination grid
4. candidate entry metric grid（候选入口指标网格）
5. penalty grid
6. penalty threshold grid

how：用 `scripts/replay_selection_target_calibration.py` 对 `selection_target_replay_input.json` 或整个 report 目录进行分析。

### 第 4 步：再做 live validation（真实窗口验证）

why：replay 能回答“规则是否变化”，但不能直接证明“次日是否更好”。

what：在真实报告窗口中跑一轮变体，再产出过滤结果和次日表现统计。

how：当前常用路径是：

1. `scripts/run_short_trade_boundary_variant_validation.py`
2. `scripts/analyze_pre_layer_short_trade_outcomes.py`
3. `scripts/analyze_short_trade_boundary_score_failures.py`
4. `scripts/analyze_short_trade_boundary_score_failures_frontier.py`

### 第 5 步：最后才决定是否升级默认参数

why：默认值一旦升级，就会影响后续所有研究和 live 流水线。

what：至少需要同时满足：

1. 供给改善
2. 次日表现没有明显恶化
3. Layer C 和 execution 承接没有崩
4. 解释性仍然清晰

---

## 6. 每类问题应该优先调什么

### 6.1 如果是供给过冷

优先顺序：

1. 检查 Layer B 中性均值回归语义
2. 检查 heavy score 覆盖上限
3. 检查 provisional score 下限
4. 最后才看 `FAST_AGENT_SCORE_THRESHOLD`

原因：这类问题通常发生在 BTST 之前，不该第一步就改 BTST 自己的 target threshold。

### 6.2 如果是边界准入太严

优先顺序：

1. `catalyst_freshness_min`
2. `candidate_score_min`
3. `breakout_freshness_min`
4. `trend_acceleration_min`
5. `volume_expansion_quality_min`

原因：很多窗口里，catalyst floor 是最容易形成“入口误伤”的准入杠杆。

### 6.3 如果是分数前沿太严

优先顺序：

1. 先看纯阈值救援样本是否存在
2. 如果有，就先做 `near_miss_threshold` 或 `select_threshold` 小步测试
3. 如果没有，就别再迷信阈值，直接转到惩罚前沿

原因：不是所有 rejected 都值得用 threshold 救。

### 6.4 如果是 stale / extension penalty 太重

优先顺序：

1. 先用 failure 分析看主负贡献是谁
2. 再用 penalty grid 看 focused ticker 的 score 和 gap 如何变化
3. 如果需要，再做 penalty + threshold 联合扫描

原因：这类问题通常需要 penalty 联动，而不是单一阈值。

### 6.5 如果是结构冲突太重

优先顺序：

1. 先做 structural variant
2. 再看 blocked 是否被释放为 near_miss 或 selected
3. 如果只释放出一堆低质量 rejected，就回滚

原因：structural conflict 是规则定义问题，不是热度问题。

---

## 7. 当前最常用的验证脚本分别适合什么场景

### 7.1 `replay_selection_target_calibration.py`

why：这是 BTST replay 校准的总入口。

适合场景：

1. 看代码改动是否引起决策漂移
2. 做 threshold grid
3. 做 structural / penalty / candidate entry（候选入口）联合扫描

重点产出：

1. `decision_transition_counts`
2. `decision_mismatch_count`
3. `focused_score_diagnostics`
4. `first_row_with_selected`
5. `first_row_with_near_miss`
6. `first_row_releasing_blocked`

### 7.2 `analyze_pre_layer_short_trade_outcomes.py`

why：直接看前置候选的次日表现。

适合场景：

1. 验证 short trade boundary 是否真的在提升候选质量
2. 比较 old boundary 与 new boundary

重点产出：

1. `next_open_return_distribution`
2. `next_high_return_distribution`
3. `next_close_return_distribution`
4. `next_high_hit_rate_at_threshold`
5. `next_close_positive_rate`

### 7.3 `analyze_short_trade_boundary_score_failures.py`

why：识别 rejected cluster 的主失败机制。

适合场景：

1. 明明准入已通过，但大批样本仍卡在 BTST score fail

重点产出：

1. 主负贡献均值
2. 距离 near-miss 的 gap 分布
3. score-fail 是否主要是 threshold 问题还是 penalty 问题

### 7.4 `analyze_short_trade_boundary_score_failures_frontier.py`

why：从分数失利主簇里找最小成本救援行。

适合场景：

1. 你已经确认问题在分数前沿，但不想大面积整体放松

重点产出：

1. 哪些样本存在纯阈值救援
2. 哪些样本必须 stale / extension 联动放松

### 7.5 `run_short_trade_boundary_variant_validation.py`

why：快速把规则变体跑成真实窗口报告。

适合场景：

1. 先做一个受控 live variant，再自动分析 filtered candidates

当前内置示例：

1. `catalyst_floor_zero`

---

## 8. 推荐的实验顺序模板

### 8.1 模板 A：怀疑准入太严

步骤：

1. 跑 baseline report
2. 看 `short_trade_boundary_filtered_candidates` 的 `filtered_reason_counts`
3. 如果主要卡在 catalyst，就先做 `catalyst_floor_zero`
4. 再跑 `analyze_pre_layer_short_trade_outcomes.py`
5. 如果候选数上来了但次日质量没明显掉，再考虑更细的准入调整

### 8.2 模板 B：怀疑分数前沿太严

步骤：

1. 跑 `analyze_short_trade_boundary_score_failures.py`
2. 判断这些样本离 near-miss 近不近
3. 如果存在贴线样本，再跑 `analyze_short_trade_boundary_score_failures_frontier.py`
4. 先做纯阈值救援
5. 只有纯阈值救援不够时，才进惩罚前沿

### 8.3 模板 C：怀疑 blocked 释放有价值

步骤：

1. 先做 structural variant replay
2. 看 `first_row_releasing_blocked`
3. 再看释放的是不是 near-miss 或 selected
4. 如果只是 blocked 变 rejected，没有价值，就停止

### 8.4 模板 D：怀疑重复 ticker 被 stale / extension 压死

步骤：

1. 设定 `focus_tickers`
2. 跑 penalty grid
3. 再跑 penalty threshold grid
4. 优先选择最小 adjustment cost 且能把目标推进到 near-miss 的组合

---

## 9. 当前最值得优先优化的参数理解方式

### 9.1 `catalyst_freshness_min`

why：这是边界准入层常见的误伤点。

什么时候调：

1. 当趋势和放量都不错，但催化新鲜度过低把样本拦在门外时。

怎么调：

1. 优先做 0.12 到 0.00 的受控变体，而不是一开始就永久改默认值。

### 9.2 `near_miss_threshold`

why：决定哪些样本进入“值得继续观察”的灰区。

什么时候调：

1. 当大量样本贴线，但未必值得直接 selected 时。

怎么调：

1. 用 replay threshold grid 小步下探。

### 9.3 `stale_score_penalty_weight`

why：它往往决定老修复票会不会被错误救回来。

什么时候调：

1. 当 `stale_trend_repair_penalty` 是主负贡献，且你确认其中存在被误伤的边界样本时。

怎么调：

1. 先做 focused penalty grid，不做全市场立即放松。

### 9.4 `extension_score_penalty_weight`

why：它决定系统会不会在高位延伸末端追进太多票。

什么时候调：

1. 当很多样本已经具备强趋势和 close，但因为 extension 被整体压死时。

怎么调：

1. 和 stale 一起联动看，不要孤立看。

### 9.5 `layer_c_avoid_penalty`

why：它决定 BTST 对研究层 `avoid` 的服从程度。

什么时候调：

1. 当你怀疑研究层对某类短线票过于保守时。

怎么调：

1. 先做 replay override，观察 focused ticker 的漂移，不建议直接全局放低。

---

## 10. 研究员与 AI 助手如何协作

### 10.1 研究员负责什么

1. 选窗口
2. 定主假设
3. 决定 focus tickers
4. 做人工审核
5. 决定是否升级默认参数

### 10.2 AI 助手负责什么

1. 定位可调参数和脚本入口
2. 实现最小变体
3. 组织 replay / live validation（真实窗口验证）命令
4. 生成对照分析文档
5. 汇总样本台账与主要结论

### 10.3 协作时必须遵守什么

1. 同一轮实验只改一类机制
2. 输出目录和命名必须可追溯
3. 每轮都保留 baseline 对照
4. 结论必须对应 artifacts，而不是只对应口头印象

---

## 11. 每轮实验至少要记录哪些内容

建议固定一个实验记录模板，至少包含：

1. 窗口起止日期
2. target mode
3. model provider / model name
4. baseline 参数
5. 本轮只改了什么
6. 产出目录
7. replay 结果
8. 次日结果统计
9. 是否影响 Layer C / execution 承接
10. 结论：继续、停止还是回滚

---

## 12. 升级默认参数前的验收标准

只有同时满足下面条件，才值得考虑升级默认参数：

1. 不是单一窗口偶然变好。
2. 供给改善不是纯噪声扩容。
3. 次日 `next_high` 和 `next_close` 没有明显劣化。
4. `blocked` 没被错误洗成一堆低质量 `near_miss`。
5. watchlist / buy orders 承接没有明显恶化。
6. 解释性仍然能说清楚 why、what、how。

---

## 13. 当前最务实的执行建议

如果今天就继续推进 BTST，最稳的顺序通常是：

1. 先确认问题是在 supply、准入、分数前沿还是 structural conflict。
2. 如果是准入，先做 `catalyst_floor_zero` 这类最小真实窗口变体。
3. 如果是 score fail，先做前沿诊断，优先找纯阈值救援样本。
4. 如果问题明确在 stale / extension，再进入惩罚前沿，不要先整体降线。
5. 每一轮都用 artifacts 回放和次日结果双重确认，不让任何“看起来更热”的变体直接晋升默认值。

---

## 14. 一句话总结

BTST 调参的核心不是把 `selected` 变多，而是通过“问题分型 -> 单机制实验 -> replay 校准 -> 真实窗口验证 -> 承接检查”这条纪律化流程，持续减少明显误伤、保留真正的次日弹性样本，并逐步逼近稳定而不是偶发的最优参数区间。
