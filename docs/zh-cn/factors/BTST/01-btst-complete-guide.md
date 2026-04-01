# BTST 次日短线策略完整指南

适用对象：第一次系统学习 BTST 的开发者、研究员、产品同学、复盘人员。

这份文档解决的问题：把当前仓库里分散在 Layer B、dual target、paper trading、selection artifacts 和 replay 脚本中的 BTST 知识，整理成一套从目标定义到执行验证的完整讲义。

建议搭配阅读：

1. [../03-layer-b-complete-beginner-guide.md](../03-layer-b-complete-beginner-guide.md)
2. [../24-execution-bridge-professional-guide.md](../24-execution-bridge-professional-guide.md)
3. [../28-paper-trading-tday-t1-timing-guide.md](../28-paper-trading-tday-t1-timing-guide.md)
4. [../../product/arch/dual_target_system/short_trade_target_rule_spec.md](../../product/arch/dual_target_system/short_trade_target_rule_spec.md)
5. [../../product/arch/dual_target_system/short_trade_target_metrics_and_validation.md](../../product/arch/dual_target_system/short_trade_target_metrics_and_validation.md)

---

## 1. 学习目标

读完后，你应该能真正回答下面这些问题：

1. BTST 在本系统里要解决的到底是什么问题，而不是什么问题。
2. 当前 BTST 是怎样从 Layer A 候选一路走到 T+1 执行计划的。
3. 为什么系统不是直接用 Layer C 分数做次日短线，而是专门增加一套 short trade target 规则。
4. 当前 BTST 用了哪些因子、penalty、gate 和 profile，它们各自的 why、what、how 是什么。
5. 当前 BTST 的验证为什么不是只看回测收益，而是同时看 replay、一致性、次日表现和执行约束。
6. 当你看到一个 BTST 样本时，如何定位它死在供给、预选、结构阻断、阈值还是执行承接。

---

## 2. 先用一句话理解 BTST

如果只保留一句话，请记这句：

**BTST 是一条围绕“次日仍有交易弹性且具备真实执行可能”的规则型短线目标链路，它不是单独一个阈值，而是 Layer B 供给、short trade boundary 预选、short trade target 评分、T+1 执行和 replay 验证共同组成的闭环。**

这句话里有四个重点。

### 2.1 why：为什么需要 BTST

单纯依赖 Layer C watchlist，会有两个问题：

1. 研究型目标更偏“值得深入研究和持有”，不一定等于“次日短线最有弹性”。
2. 一些没有进入最终研究 watchlist 的边缘样本，可能在次日短线语境下反而更像启动票。

所以系统引入 dual target，把“研究目标”和“次日短线目标”拆开看。

### 2.2 what：BTST 不是在找什么

BTST 不是在找：

1. 已经大幅延伸、上方空间有限的后排拉升票。
2. 旧趋势修复、均值回归反抽、看起来很强但本质陈旧的票。
3. 只有情绪冲高、但缺乏趋势新鲜度和执行条件的票。

BTST 要找的是：

1. 更接近突破起点或第二阶段扩张起点的样本。
2. 趋势刚增强，次日仍可能延续，而不是只剩尾声。
3. 放量、收盘、催化、板块共振和 Layer C 共识都足够配合的样本。

### 2.3 how：BTST 如何工作

当前默认实现可以压缩成 5 步：

1. Layer A 给出市场候选池。
2. Layer B 给出规则化的多因子供给和高分池。
3. short trade boundary 从 Layer C 之前的边缘候选里做一次短线预选补充。
4. short trade target 对 watchlist、rejected entries 和补充边界样本统一打分，判成 selected、near_miss、blocked 或 rejected。
5. paper trading 采用 T 日收盘后生成计划、T+1 执行计划的时序，再用 replay 和次日结果反向校准规则。

---

## 3. BTST 在系统中的位置

当前链路可以概括成：

```text
Layer A 候选池
  -> Layer B 四策略评分
  -> fast pool
  -> Layer C 聚合与 watchlist
  -> short_trade_boundary 补充预选
  -> short_trade_target 规则评估
  -> selection_targets
  -> T 日 post-market 生成计划
  -> T+1 pre-market / intraday 确认与执行
```

这条链路里每一层的职责不同。

### 3.1 Layer A

why：先把全市场压缩成一个可批量打分的候选集合。

what：它提供的是供给，不提供 BTST 结论。

how：由 candidate pool 规则筛出候选，再进入 Layer B 打分。

### 3.2 Layer B

why：用可解释、可批量执行的规则，快速判断哪些样本值得继续投入更昂贵的分析资源。

what：输出 `score_b`、四条策略信号、仲裁信息和高分池。

how：核心逻辑在策略评分器与信号融合模块里，后面会详细拆开。

### 3.3 Layer C

why：补上多智能体深度分析，形成 watchlist 和 buy orders。

what：它更像“研究层深度判断”，不是专为次日短线设计。

how：fast pool 进入多 agent 聚合，再形成 `score_c`、`score_final` 和 `decision`。

### 3.4 short trade boundary

why：防止系统完全被“研究 funnel”绑死，给短线语境保留一条来自 Layer C 之前的边界补充通道。

what：它不是最终 BTST 结论，而是 pre-Layer C 的候选补充池。

how：从未进入 fast pool 的上游候选中，按短线结构预选一批 `supplemental_short_trade_entries`。

### 3.5 short trade target

why：把研究目标和次日短线目标正式拆开，让系统对同一只票给出两种不同目标判断。

what：输出 `selected`、`near_miss`、`blocked`、`rejected` 四类结论，以及完整 explainability。

how：对 watchlist 样本、被 watchlist 过滤掉的 rejected entries，以及 short trade boundary 补充样本统一打分。

---

## 4. Layer B 是 BTST 的供给层

BTST 不是从真空里产生的。它的供给质量首先取决于 Layer B 是否把足够多、足够像短线候选的样本送下来。

### 4.1 当前 Layer B 的四条主策略

当前默认由四条策略组成：

1. `trend`
2. `mean_reversion`
3. `fundamental`
4. `event_sentiment`

why：次日短线不能只看技术，也不能只看事件；需要把“价格结构”“反身性风险”“质量底色”“催化支持”拼在一起。

what：每条策略都会输出统一的 `StrategySignal`，包含 `direction`、`confidence`、`completeness` 和 `sub_factors`。

how：当前主要由以下模块负责：

1. 趋势与均值回归：`src/screening/strategy_scorer.py`
2. 融合与仲裁：`src/screening/signal_fusion.py`
3. pipeline 入口：`src/execution/daily_pipeline.py`

### 4.2 趋势策略为什么最重要

why：次日短线本质上是“明天是否还有顺势空间”的问题，所以趋势是第一性输入。

what：趋势策略重点看下面这些子因子：

1. `ema_alignment`
2. `adx_strength`
3. `momentum`
4. `volatility`
5. `long_trend_alignment`

how：这些子因子先在 Layer B 内部聚合，再在 short trade target 中进一步转成：

1. `breakout_freshness`
2. `trend_acceleration`
3. `volume_expansion_quality`
4. `close_strength`

### 4.3 均值回归为什么既有价值又危险

why：均值回归能帮助识别超涨、修复和反抽，但这类信号如果处理不当，会把“已经老化的修复票”误当成次日短线机会。

what：BTST 里最关键的负向机制之一就是 `stale_trend_repair_penalty`，它就会吃到 mean reversion 与 long trend 的组合影响。

how：仓库里专门保留了多种 `LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE` 变体，用于调节中性均值回归是否参与 active normalization。

### 4.4 基本面为什么仍然重要

why：次日短线不是价值投资，但弱质量票更容易形成“涨得快、死得也快”的脆弱结构。

what：Layer B 基本面策略会产出盈利能力、成长、财务健康、成长估值和行业 PE 等子因子。

how：这些信号不直接变成 BTST 的显式正向因子，但会通过：

1. Layer B 供给排序
2. `quality_score`
3. analyst / investor cohort alignment
4. 质量优先护栏

间接影响 BTST 是否有健康底座。

### 4.5 事件情绪为什么决定“新鲜度”

why：BTST 最怕“看上去很强，但催化已经过期”。

what：事件策略包含：

1. `news_sentiment`
2. `insider_conviction`
3. `event_freshness`

how：在 short trade target 中，这些输入进一步合成为：

1. `catalyst_freshness`
2. `breakout_freshness` 的一部分
3. `volume_expansion_quality` 的一部分
4. `sector_resonance` 的一部分

---

## 5. short trade boundary 是 BTST 的预选补充层

这一步非常重要，因为很多人会误以为 BTST 只对 Layer C watchlist 生效。当前实现不是这样。

### 5.1 why：为什么还要多一层 boundary

如果 short trade target 只看 Layer C watchlist，会出现两个问题：

1. 研究 funnel 太冷时，短线机会会被直接饿死。
2. 一些结构上很像次日启动票，但并不适合研究 funnel 的样本，会完全失去被观察的机会。

### 5.2 what：boundary 在筛什么

它从 `fused` 结果里挑出那些没有进入 fast pool 的上游候选，再按短线预选规则过滤。

当前默认只保留满足以下条件的样本：

1. 数据 gate 通过
2. 结构 gate 通过
3. `breakout_freshness >= 0.18`
4. `trend_acceleration >= 0.22`
5. `volume_expansion_quality >= 0.15`
6. `catalyst_freshness >= 0.12`
7. `candidate_score >= 0.24`

同时还受两个总量限制：

1. 只从 `FAST_AGENT_SCORE_THRESHOLD - SHORT_TRADE_BOUNDARY_SCORE_BUFFER` 以上的边缘地带挑候选
2. 最多保留 `DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_MAX_TICKERS`，默认 6 只

### 5.3 how：boundary 的 candidate_score 是怎么来的

当前预选得分不是最终 `score_target`，而是一个轻量的准入评分：

```text
0.30 * breakout_freshness
+ 0.25 * trend_acceleration
+ 0.20 * volume_expansion_quality
+ 0.15 * catalyst_freshness
+ 0.10 * close_strength
```

why：预选层只解决“值不值得送进 BTST 正式评估”，不直接下最终结论。

what：它更像准入底线。

how：通过 `supplemental_short_trade_entries` 附着到 selection targets 的 replay 输入中。

---

## 6. short trade target 才是 BTST 的正式评分层

这一层是当前 BTST 的核心。

### 6.1 why：为什么要单独做 target 评估

因为“研究型好票”和“次日短线好票”不是完全重合的集合。

研究型目标更关心：

1. 深度共识
2. 长一点的持有逻辑
3. 质量与风险平衡

BTST 更关心：

1. 次日是否还有弹性
2. 结构是否新鲜
3. 是否存在上方压制和过度延伸
4. 明天是否仍有执行可能

### 6.2 what：当前 BTST 的 7 个正向项

当前正式总分包含 7 个正向项：

1. `breakout_freshness`
2. `trend_acceleration`
3. `volume_expansion_quality`
4. `close_strength`
5. `sector_resonance`
6. `catalyst_freshness`
7. `layer_c_alignment`

### 6.3 what：当前 BTST 的 4 个负向项

当前正式负项包括：

1. `stale_trend_repair_penalty`
2. `overhead_supply_penalty`
3. `extension_without_room_penalty`
4. `layer_c_avoid_penalty`

前三个是结构性 penalty，最后一个是 profile 注入的规则惩罚。

### 6.4 how：当前默认总分公式

当前默认 profile 下，正式分数可以写成：

```text
score_target =
  0.22 * breakout_freshness
  + 0.18 * trend_acceleration
  + 0.16 * volume_expansion_quality
  + 0.14 * close_strength
  + 0.12 * sector_resonance
  + 0.08 * catalyst_freshness
  + 0.10 * layer_c_alignment
  - 0.12 * stale_trend_repair_penalty
  - 0.10 * overhead_supply_penalty
  - 0.08 * extension_without_room_penalty
  - layer_c_avoid_penalty
```

这套权重的含义很明确：

1. 最看重 breakout 和 trend，因为短线核心是“明天还能不能延续”。
2. volume 与 close 不是配角，因为次日短线极度依赖日内结构质量。
3. catalyst 和 Layer C alignment 是加分项，但不能主导全局。
4. stale 和 extension 必须保留，否则系统会把老修复票、末端延伸票重新放出来。

---

## 7. 每个因子的 why、what、how

### 7.1 breakout_freshness

why：BTST 最想抓的是“刚启动”而不是“涨了很久”。

what：它衡量的是突破新鲜度和启动起点感。

how：当前由以下输入合成：

1. `momentum_strength` 的 40%
2. `event_freshness_strength` 的 35%
3. `event_signal_strength` 的 25%

理解方式：不是单纯看价格涨没涨，而是看“价格动能”和“催化新鲜度”是否一起成立。

### 7.2 trend_acceleration

why：次日短线吃的是趋势增强，不是慢速爬坡。

what：它衡量趋势是否正在加速。

how：当前由：

1. `momentum_strength` 40%
2. `adx_strength` 35%
3. `ema_strength` 25%

共同构成。

### 7.3 volume_expansion_quality

why：没有量的突破，持续性通常很差。

what：它衡量的是放量质量，而不是只看是否成交量变大。

how：当前由：

1. `volatility_strength` 55%
2. `momentum_strength` 25%
3. `event_signal_strength` 20%

组成。这里的设计含义是：量价扩张必须和动量、事件支持一起看。

### 7.4 close_strength

why：次日短线更偏好强势收盘，而不是冲高回落。

what：它衡量日线末端的收盘质量。

how：当前由：

1. `ema_strength` 55%
2. `momentum_strength` 25%
3. `score_b_strength` 20%

组成。

### 7.5 sector_resonance

why：孤立上涨比板块共振更脆弱。

what：它衡量个股与 cohort 共识、行业和事件支持之间的共振。

how：当前由：

1. `analyst_alignment` 45%
2. `investor_alignment` 20%
3. `score_c_strength` 20%
4. `event_signal_strength` 15%

组成。

### 7.6 catalyst_freshness

why：次日短线高度依赖催化是否还在“可交易的新鲜区间”。

what：它衡量事件有没有被市场交易旧。

how：当前由：

1. `event_freshness_strength` 65%
2. `news_sentiment_strength` 35%

组成。

### 7.7 layer_c_alignment

why：BTST 不能被 Layer C 完全主导，但也不能完全无视研究层共识。

what：它是一个辅助增强项，不是最终拍板项。

how：当前由：

1. `score_c_strength` 55%
2. `analyst_alignment` 25%
3. 如果 `layer_c_decision != avoid`，额外给 20% 的状态增强

组成。

---

## 8. penalty 为什么是 BTST 成败关键

很多短线系统的问题，不是正向因子不够，而是 penalty 太弱，导致放进来一堆“看起来能涨、实际上已经老了”的票。

### 8.1 stale_trend_repair_penalty

why：这是专门识别旧趋势修复和均值回归反抽的主 penalty。

what：它主要打击“不是新启动，而是老票修复”的样本。

how：当前由：

1. `mean_reversion_strength` 45%
2. `long_trend_strength` 35%
3. `max(0, long_trend_strength - breakout_freshness)` 20%

组成。

### 8.2 overhead_supply_penalty

why：有些票结构不差，但上方压制和强烈冲突太重。

what：它衡量上方抛压和 Layer C 冲突压力。

how：当前主要来源于：

1. 如果 `bc_conflict` 命中强 bearish conflict，直接给 45% 基础惩罚
2. `analyst_penalty` 35%
3. `investor_penalty` 20%

### 8.3 extension_without_room_penalty

why：不是所有强趋势都值得追，很多时候已经没空间了。

what：它识别“趋势很强，但已经延伸过头”的样本。

how：当前由：

1. `long_trend_strength` 45%
2. `max(0, volatility_strength - catalyst_freshness)` 35%
3. `score_final_strength` 过高后的拥挤延伸惩罚 20%

共同构成。

### 8.4 layer_c_avoid_penalty

why：研究层明确 `avoid` 时，BTST 不能假装没看见。

what：它是 profile 注入的硬编码惩罚，默认 0.12。

how：只要 `layer_c_decision == avoid` 就直接扣分。

---

## 9. gate 是如何决定 selected、near_miss、blocked、rejected 的

### 9.1 为什么先看 gate 再看分数

因为分数再高，也不能绕过“结构上根本不是次日短线机会”的事实。

### 9.2 data gate

why：没有关键信号就不应硬评估。

what：当前最关键的 fail 情况是缺趋势信号。

how：如果 `trend_signal` 缺失或完整度为 0，会记成 `missing_trend_signal`，并把 data gate 置为 fail。

### 9.3 structural gate

why：这是 BTST 真正的防漏闸门。

what：当前会触发 blocker 的关键情况包括：

1. `layer_c_bearish_conflict`
2. `trend_not_constructive`
3. `stale_trend_repair_penalty`
4. `overhead_supply_penalty`
5. `extension_without_room_penalty`

how：如果命中这些 blocker，样本会优先进入 `blocked` 或 `rejected`，而不是直接看分数。

### 9.4 score gate

当前 default profile 下：

1. `score_target >= 0.58`，且 `breakout_freshness >= 0.35`、`trend_acceleration >= 0.38`，判为 `selected`
2. 未选中但 `score_target >= 0.46`，判为 `near_miss`
3. 否则判为 `rejected`

### 9.5 blocked 和 rejected 的区别

这两者在研究上必须分开理解。

`blocked` 的含义更接近：

1. 结构冲突太重
2. 数据不完整
3. 本质上不属于 BTST 允许通过的类型

`rejected` 的含义更接近：

1. 结构上不一定完全错误
2. 但当前分数和条件还不够
3. 更适合做 near-miss 或 frontier（前沿）分析

---

## 10. profile 为什么重要

当前 BTST 不是只有一个固定点，而是有 profile 机制。

### 10.1 default

当前默认 profile：

1. `select_threshold = 0.58`
2. `near_miss_threshold = 0.46`
3. `stale_penalty_block_threshold = 0.72`
4. `overhead_penalty_block_threshold = 0.68`
5. `extension_penalty_block_threshold = 0.74`
6. `layer_c_avoid_penalty = 0.12`

### 10.2 conservative

why：适合先保守，减少误放。

what：更高的 select 和 near-miss 阈值、更严的 penalty block 阈值、更重的 penalty 权重。

### 10.3 aggressive

why：适合验证是否存在“边界候选被压太狠”的情况。

what：更低的 select 和 near-miss 阈值、更宽的 penalty block 阈值、更轻的 penalty 权重。

how：通过 target profile context 切换，不必改动主逻辑。

---

## 11. selection target 是如何落到 artifacts 里的

为什么要关心这一步：因为 BTST 是否真的可研究、可复盘，取决于它有没有被稳定地写进 artifacts。

当前每个交易日都会生成：

1. `selection_snapshot.json`
2. `selection_review.md`
3. `selection_target_replay_input.json`

其中最关键的是 `selection_target_replay_input.json`。

它会保存：

1. watchlist 样本
2. rejected entries
3. supplemental short trade entries
4. buy order tickers
5. 已附着的 selection targets
6. target summary

这使得 BTST 可以做完全离线 replay，而不是每次重跑整条实时链路。

---

## 12. BTST 的验证为什么必须是多层验证

### 12.1 why：为什么不能只看纸面分数

因为纸面分数只说明规则内部自洽，不说明次日真的有用。

### 12.2 当前至少有四类验证

#### 第一类：一致性 replay

what：用 artifacts 回放 selection targets，看代码变更后决策是否漂移。

how：核心脚本是：

1. `scripts/replay_selection_target_calibration.py`

它可以做：

1. 单次 replay
2. threshold grid
3. structural variants
4. combination grid
5. candidate entry metric grid（候选入口指标网格）
6. penalty grid
7. penalty + threshold 联合网格

#### 第二类：pre-Layer C 次日结果验证

what：直接看前置短线候选的次日开盘、高点、收盘表现。

how：核心脚本是：

1. `scripts/analyze_pre_layer_short_trade_outcomes.py`

它会统计：

1. `next_open_return`
2. `next_high_return`
3. `next_close_return`
4. 次日最高是否达到阈值，比如 `+2%`
5. 次日收盘是否为正

#### 第三类：分数失利主簇诊断

what：分析被 BTST 拒绝的边界候选，判断问题在准入、阈值还是惩罚。

how：当前核心脚本是：

1. `scripts/analyze_short_trade_boundary_score_failures.py`
2. `scripts/analyze_short_trade_boundary_score_failures_frontier.py`

#### 第四类：真实窗口验证

what：在真实报告窗口中跑规则变体，再自动导出覆盖情况。

how：当前核心脚本是：

1. `scripts/run_short_trade_boundary_variant_validation.py`

---

## 13. T 日计划和 T+1 执行是 BTST 的时间基础

这是新手最容易理解错的一点。

### 13.1 why：为什么必须先讲时序

因为 BTST 讨论的是“次日短线”。如果你把 T 日研究结果误当成 T 日盘中立刻执行，整个验证都会错位。

### 13.2 what：当前系统的真实口径

当前默认时序是：

1. T 日 post-market 生成计划
2. T+1 pre-market 准备计划
3. T+1 intraday 做确认和执行

### 13.3 how：BTST 在执行层的含义

当前 short trade target 的输出会携带两个很明确的执行语义：

1. `expected_holding_window = t1_short_trade`
2. `preferred_entry_mode = next_day_breakout_confirmation`

再加上 execution constraints 中 `included_in_buy_orders`，系统会区分：

1. 只是规则上看好
2. 已经具备 execution bridge 承接

---

## 14. 当前 BTST 研究最重要的经验结论

结合当前仓库里的最新文档和脚本，可以把主线总结成四句：

1. short_trade_boundary 已经证明方向是对的，前置候选的次日质量明显优于旧的 layer_b_boundary。
2. 当前更大的问题往往不是准入完全不行，而是高质量候选数太少。
3. 在很多窗口里，真正的主矛盾已经从“继续放宽准入底线”转向“分数前沿和惩罚前沿”。
4. blocked 样本并不天然等于阈值共调对象，很多样本本质上需要结构或 penalty 重构，而不是简单降线。

---

## 15. 新手看 BTST，最该先掌握什么

如果你是第一次上手，建议按这个顺序理解：

1. 先搞清楚 BTST 的目标不是“找所有强票”，而是“找明天还可能继续强的票”。
2. 再搞清楚供给来自 Layer B，而不是凭空生成。
3. 再搞清楚 short trade boundary 只是准入层，不是最终结论。
4. 然后重点理解 `stale_trend_repair_penalty` 和 `extension_without_room_penalty`，因为这两者最容易决定一个样本为什么死掉。
5. 最后再去看 threshold、near_miss 和 replay grid，因为那是调优阶段，而不是入门阶段。

---

## 16. 一句话总结

当前 BTST 不是一套“拍脑袋追涨”的短线规则，而是一条把 Layer B 供给、边界补充、结构型 penalty、Layer C 共识、T+1 执行和 replay 校准绑定在一起的规则闭环；真正理解它，关键不在记住某一个阈值，而在理解每一层到底在防什么错误、放什么机会。
