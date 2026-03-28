# 次日短线目标首版规则集规格

> 文档元信息
>
> - 首次创建日期：2026-03-28
> - 最近更新时间：2026-03-28 09:45:53 CST
> - 当前目录：docs/zh-cn/product/arch/dual_target_system/

## 0. 文档定位

本文档是 [arch_dual_target_selection_system.md](./arch_dual_target_selection_system.md) 的规则规格配套文档，用于定义 short trade target 的首版规则型实现。

本文档回答的问题是：

1. 短线目标首版用哪些因子
2. 这些因子如何归一化和组合
3. hard gate 与 soft gate 的顺序是什么
4. explainability 与 blocker 如何输出
5. 首版应如何与现有 Layer A / B / C 事实层衔接

本文档刻意不做的事：

1. 不追求一开始覆盖所有交易模式
2. 不直接引入黑箱模型
3. 不在首版就实现复杂的自适应权重学习

---

## 1. 首版目标

首版 short trade target 不是为了最大化想象中的极限收益，而是为了建立一个可解释、可回测、可冻结的规则基线。

首版要解决的核心问题：

1. 避免把旧趋势修复票误当成次日启动票
2. 优先识别启动新鲜度更高、扩张更顺畅的候选
3. 在现有 Layer B / Layer C 事实层上实现最小增量接入

---

## 2. 输入事实依赖

short trade target 不应该自己重新抓一遍全量数据，而应依赖统一的事实层输入。

建议最小输入字段：

1. ticker
2. trade_date
3. market_state
4. strategy_signals
5. score_b
6. score_c / score_final
7. bc_conflict
8. layer_c decision
9. liquidity_features
10. volatility_features
11. event_features
12. sector_features

其中最关键的是：

1. Layer B 提供底层结构性证据
2. Layer C 提供共识与冲突证据
3. execution constraints 提供可执行性约束

---

## 3. 首版因子集

建议首版采用 6 个正向因子与 3 个负向因子。

### 3.1 正向因子

#### breakout_freshness

用于衡量是否接近突破起点，而不是突破后的陈旧延续。

关注：

1. 近期是否刚脱离关键区间
2. 是否属于第一段或第二段扩张，而非长时间后段拉伸

#### trend_acceleration

用于衡量趋势是否在加速，而不是仅仅保持缓慢上行。

关注：

1. 短周期斜率是否快于中周期
2. 动量是否刚从弱转强

#### volume_expansion_quality

用于衡量放量是否支持价格上攻，而不是情绪性冲高。

关注：

1. 放量是否相对基线显著增强
2. 放量日是否伴随实体突破而非上影冲高

#### close_strength

用于衡量收盘位置是否强。

关注：

1. close 是否靠近日内高位
2. 是否出现冲高回落结构

#### sector_resonance

用于判断个股是否与板块主线同步，而不是独立脉冲。

关注：

1. 所属板块是否处在相对强势状态
2. 同题材是否存在联动扩散

#### catalyst_freshness

用于判断催化是否仍具备交易价值。

关注：

1. 事件是否新鲜
2. 是否已被市场充分交易

### 3.2 负向因子

#### stale_trend_repair_penalty

识别旧趋势修复、反抽、均值回归回补类样本。

#### overhead_supply_penalty

识别上方抛压重、历史套牢密集或前高压力显著的样本。

#### extension_without_room_penalty

识别已经明显延伸、但上方空间有限的样本。

---

## 4. 归一化原则

所有因子在进入总分前必须归一化到统一量纲。

建议原则：

1. 正向因子统一映射到 0 到 1
2. 负向因子统一映射到 0 到 1
3. 缺失值不默认等于 0，应有明确缺失处理
4. 缺失处理必须写入 explainability

建议缺失策略：

1. 关键执行类字段缺失时走 hard reject
2. 非关键辅助字段缺失时降权并标记 data_incomplete

---

## 5. 首版总分公式

建议首版使用显式可解释的线性组合：

```text
score_short =
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
```

说明：

1. 这是首版研究公式，不是长期固定真理
2. layer_c_alignment 只能作为增强项，不能压过硬 gate
3. penalty 项必须保留，否则系统会重新回到“旧趋势修复票放量”的老问题

---

## 6. gate 顺序

gate 的顺序比阈值本身更重要。

建议采用四段式：

1. data gate
2. execution gate
3. structural gate
4. score gate

### 6.1 data gate

先判断是否具备足够事实。

直接拒绝条件：

1. 核心价格序列缺失
2. 核心流动性字段缺失
3. 必要事件字段无法判断且无法降级

### 6.2 execution gate

再判断是否具备实际可交易性。

直接拒绝条件：

1. 流动性低于阈值
2. 涨停买入成功率过低
3. 成本或滑点显著吞噬潜在边际

### 6.3 structural gate

然后过滤那些虽然有分数但本质上不是次日强机会的结构。

直接拒绝条件：

1. stale_trend_repair_penalty 过高
2. overhead_supply_penalty 过高
3. extension_without_room_penalty 过高
4. bc_conflict 指向明显强 bearish 冲突

### 6.4 score gate

最后才看总分。

建议：

1. score_short 过最低阈值才入 short trade candidate
2. 更高阈值才进入 short trade watchlist
3. entry confirmation 再决定是否形成次日执行计划

---

## 7. Layer C 的使用方式

short trade target 不应被 Layer C 完全主导，但也不应忽略 Layer C。

建议使用方式：

1. score_c 和 score_final 作为辅助增强项
2. bc_conflict 作为结构性风险信号
3. agent_contribution_summary 作为 explainability 来源

禁止的用法：

1. 因为 LLM 很看好，就绕过执行与结构 gate
2. 让 Layer C 单独决定是否进入 short trade plan

---

## 8. explainability 输出规范

每个 short trade result 应至少输出：

1. positive_tags
2. negative_tags
3. blockers
4. top_reasons
5. target_decision

建议标准标签：

正向：

1. fresh_breakout_setup
2. trend_acceleration_active
3. volume_expansion_confirmed
4. close_near_high
5. sector_relative_strength
6. fresh_event_catalyst
7. breakout_room_large

负向：

1. post_run_pullback_chop
2. stale_trend_repair
3. overhead_supply_risk
4. repeated_failed_breakout
5. event_not_fresh
6. weak_next_day_edge
7. late_stage_extension_without_room

blockers 建议至少区分：

1. data_incomplete
2. low_liquidity
3. execution_unfavorable
4. stale_structure
5. overhead_supply
6. bearish_conflict

---

## 9. profile 设计

首版建议保留 profile 概念，但不要过多。

建议仅保留三档：

1. conservative
2. default
3. aggressive

各 profile 主要差异应体现在：

1. execution gate 严格程度
2. structural gate 阈值
3. score gate 阈值

不建议首版让 profile 改变整套因子定义，否则解释成本会急剧上升。

---

## 10. 与现有 artifacts 的承接

short trade target 结果建议先写入 selection_artifacts，而不是第一步直接大改执行模型。

建议新增结构：

1. selection_targets.research
2. selection_targets.short_trade
3. dual_target_delta

这样可以先在 Replay Artifacts 中复盘：

1. 为什么某票 research pass 但 short reject
2. 为什么某票 short pass 但 research reject
3. 哪类 blocker 最常见

---

## 11. 首版测试建议

至少应覆盖以下场景：

1. 缺失关键数据时 hard reject
2. 低流动性样本 hard reject
3. 旧趋势修复样本被 penalty 压下
4. fresh breakout 样本在相同 Layer B 条件下高于 repair 样本
5. bc_conflict 强 bearish 时拒绝或显著降权
6. positive_tags / blockers 输出稳定

如果这些基础测试都不稳，后续再谈更复杂策略没有意义。

---

## 12. 当前建议结论

short trade target 首版最重要的不是“复杂”，而是：

1. 规则顺序清楚
2. gate 分层清楚
3. 因子语义清楚
4. explainability 清楚
5. 可以直接被 replay 和 artifacts 复盘

只要这一版规则基线干净，后续再迭代 profile、参数和更复杂模型才有意义。
