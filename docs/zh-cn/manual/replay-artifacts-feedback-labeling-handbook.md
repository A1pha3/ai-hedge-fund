# Replay Artifacts 研究反馈标签规范手册

> 配套阅读：
>
> 1. [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)
> 2. [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
> 3. [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)
> 4. [Replay Artifacts 案例手册：2026-03-11 的 300724 为什么入选但未买入](./replay-artifacts-case-study-20260311-300724.md)

## 1. 这份手册解决什么问题

当前系统已经允许研究员直接在 Replay Artifacts 页面追加 research feedback，但“能写”不等于“写得一致”。

如果团队没有统一标签口径，会很快出现三个问题：

1. 同一种现象被不同人打成不同标签，后续统计无法聚合。
2. 同一个标签混入多种语义，后续无法稳定复盘。
3. `primary_tag`、`tags`、`review_status` 和 `research_verdict` 被混用，反馈记录会逐渐失去研究价值。

这份手册的目标就是把“怎么打标签”标准化，让研究员在写 feedback 时知道：

1. 什么时候该用哪个主标签。
2. 什么时候只是补充标签，而不该改主标签。
3. 什么时候应把问题归因为选股质量，什么时候应归因为执行承接。
4. 什么时候该停留在 `draft`，什么时候应该推进到 `final` 或 `adjudicated`。

---

## 2. 先分清四个字段

写 feedback 前，先不要急着选标签。先把四个字段彻底分开。

### 2.1 `primary_tag`

它表示这条记录的主结论。

要求：

1. 只能有一个。
2. 必须来自受控词表。
3. 应该能回答“这条记录最核心的问题或优点是什么”。

### 2.2 `tags`

它表示补充视角。

要求：

1. 可以有多个。
2. 只能补充，不应推翻 `primary_tag`。
3. 适合记录次级风险、次级优点或复核提醒。

### 2.3 `review_status`

它表示这条记录当前处于什么复核阶段，不表示你看多还是看空。

当前允许值：

1. `draft`
2. `final`
3. `adjudicated`

### 2.4 `research_verdict`

它表示你想用自然语言或项目内约定短语概括结论。

它的作用是：

1. 让人一眼看懂你真正想表达的判断。
2. 补足受控标签粒度不够细的地方。
3. 为未来统计、分组或人工复盘保留自由表达空间。

最重要的一点：

1. `research_verdict` 不是受控标签字典。
2. 它可以写成一句短语。
3. 但它不能替代 `primary_tag`。

---

## 3. 当前受控主标签的真实含义

当前系统内允许的受控标签有 6 个。不要靠字面猜，用下面这套业务口径。

### 3.1 `high_quality_selection`

适用场景：

1. 这只票被选入 watchlist 或 selected 的逻辑是扎实的。
2. 你认为它的证据链清楚，且不是噪声驱动。
3. 即便最后没有进入 `buy_orders`，你仍然认可“选出来本身是合理的”。

典型信号：

1. Layer B 因子解释清楚。
2. Layer C 共识不一定绝对一致，但主线明确。
3. 你能清楚说出“它为什么值得被研究层挑出来”。

不适用场景：

1. 你只是觉得“它没那么差”。
2. 它其实更像执行层阻塞样本，而不是高质量研究样本。
3. 你对其入选理由仍有明显疑问。

### 3.2 `thesis_clear`

适用场景：

1. 这条记录的核心投资逻辑很清楚。
2. 你能用一句到两句话讲明白它的主线。
3. 你希望强调“逻辑清晰”，而不一定强调“质量最高”。

典型信号：

1. `why_selected` 和 `what_to_check` 很顺。
2. `selection_review.md` 能清楚复述核心原因。
3. notes 中可以非常具体地写出驱动逻辑。

常见组合：

1. `primary_tag = high_quality_selection`
2. `tags` 里补 `thesis_clear`

### 3.3 `crowded_trade_risk`

适用场景：

1. 你担心它不是“逻辑错”，而是“太拥挤”。
2. 它可能已经成为市场共识交易，进一步上涨空间和持仓舒适度下降。
3. 你认为 crowding、波动或承接脆弱性值得被单独标注。

典型信号：

1. 情绪或趋势过于一致。
2. 上涨叙事被市场反复消费。
3. 继续买入可能面临拥挤交易反噬。

不适用场景：

1. 单纯因为你不喜欢这家公司。
2. 只是估值高，但没有 crowding 迹象。

### 3.4 `weak_edge`

适用场景：

1. 这只票被选出来了，但优势并不扎实。
2. 你觉得它不是明显错误，但边际优势太弱。
3. 它更像“可以看，但不值得高强度押注”。

典型信号：

1. Layer C 分歧较大。
2. 解释来源较弱，例如兼容回退字段而非原生信号。
3. 证据能成立，但不足以形成高把握度结论。

它常用于：

1. 已进入 selected，但人工复核后认为护城河不够深。
2. 案例里像 300724 这种“研究通过但把握度仍偏弱”的情形。

### 3.5 `threshold_false_negative`

适用场景：

1. 你认为系统阈值把一只本该进入更高层级的股票挡掉了。
2. near-miss 样本中有明显误伤。
3. 问题更像规则阈值过严，而不是股票本身没有逻辑。

典型信号：

1. 该票在 rejected near-miss 中非常接近入选。
2. 关键 rejection reason 更像阈值切线，而不是质量断裂。
3. 你能明确说出“如果阈值轻微放宽，它就值得继续看”。

不要误用在：

1. 已经进入 selected 的股票。
2. 实际是执行层 blocker 拦住了 buy order 的股票。

### 3.6 `event_noise_suspected`

适用场景：

1. 你怀疑入选理由过度依赖短期事件、新闻或情绪波动。
2. 逻辑看起来成立，但可持续性可疑。
3. 你担心这是一次短噪声冲击，而不是稳定边。

典型信号：

1. news/sentiment 维度异常强，但基本面或结构性证据偏弱。
2. 近期事件非常新，尚未被更多事实确认。
3. 研究 prompt 中最值得检查的项正好是事件噪声。

---

## 4. 一个实用决策顺序

如果你不知道先选哪个标签，按下面顺序判断，不容易乱。

### 4.1 第一步：先判断问题层级

先问自己：

1. 这是选股层问题。
2. 还是执行层阻塞。
3. 还是两者都有。

判断方法：

1. 看 `Selected Candidates` 是否已有该票。
2. 看 `execution_bridge.included_in_buy_orders`。
3. 看 `block_reason`、`reentry_review_until`。
4. 看 `Funnel Drilldown` 里它卡在哪一层。

如果结论是“研究层挑出来没问题，只是执行层没承接”，就不要把它误标成 `threshold_false_negative`。

### 4.2 第二步：再判断主结论是优点还是风险

如果你的第一直觉是：

1. “这票被选得不错”，优先考虑 `high_quality_selection`。
2. “逻辑很清楚”，优先考虑 `thesis_clear` 作为补充标签。
3. “逻辑能说通，但边不够厚”，优先考虑 `weak_edge`。
4. “阈值把它误伤了”，优先考虑 `threshold_false_negative`。
5. “像事件噪声”，优先考虑 `event_noise_suspected`。
6. “太拥挤”，优先考虑 `crowded_trade_risk`。

### 4.3 第三步：最后再补充 `tags`

如果主标签已经选好了，再用 `tags` 补充第二视角。

例如：

1. 主标签是 `high_quality_selection`，补 `thesis_clear`。
2. 主标签是 `weak_edge`，补 `event_noise_suspected`。
3. 主标签是 `high_quality_selection`，补 `crowded_trade_risk`。

---

## 5. `review_status` 什么时候怎么用

### 5.1 `draft`

适用场景：

1. 你刚看完页面，先写一个初步判断。
2. 证据还不够完整。
3. 你希望后面继续补充 notes 或等待更多样本。

最常见用法：

1. 单人初看后的第一条记录。
2. 当天复盘先留痕，再在周度复盘里升级。

### 5.2 `final`

适用场景：

1. 你已经完成本轮复核。
2. 结论足够稳定，短期内不会轻易改。
3. 这条记录已经可以进入稳定统计口径。

适合推进到 `final` 的条件：

1. 你已看过 selected、execution bridge、funnel 和 prompts。
2. notes 已写清楚核心因果链。
3. 你知道自己是在评估选股质量，还是执行承接。

### 5.3 `adjudicated`

适用场景：

1. 这条记录已经经过多人讨论或高层级复核。
2. 团队需要把争议统一成一个最终口径。
3. 它通常用于样本争议较大、会影响后续规则判断的记录。

不要滥用：

1. 不是所有记录都要 `adjudicated`。
2. 如果只是你个人看完一次，不要直接跳到这个状态。

---

## 6. 推荐的 `research_verdict` 写法

`research_verdict` 不必很长，但要让后来人一眼明白你的判断。

推荐写法：

1. 先说归因层级。
2. 再说结论。
3. 最后说特殊提醒。

示例：

1. `selected_for_good_reason`
2. `blocked_by_execution_not_selection`
3. `near_miss_likely_threshold_false_negative`
4. `selection_logic_clear_but_crowded`
5. `selected_but_event_noise_risk_high`

不推荐：

1. `good`
2. `bad`
3. `maybe`
4. `看看再说`

这些词没有复盘价值。

---

## 7. 常见样本应该怎么打

### 7.1 已入选，也进入买单，逻辑清楚

推荐：

1. `primary_tag = high_quality_selection`
2. `tags = [thesis_clear]`
3. `review_status = final`
4. `research_verdict = selected_for_good_reason`

### 7.2 已入选，但被执行层 blocker 拦住

推荐：

1. 不要直接打 `threshold_false_negative`。
2. 如果你认可研究层筛选本身，可以用 `weak_edge` 或 `high_quality_selection`，具体取决于你对研究证据强弱的判断。
3. `research_verdict` 里写清 `blocked_by_execution_not_selection`。
4. notes 里必须写出 blocker 字段，例如 `blocked_by_reentry_score_confirmation`。

### 7.3 near-miss 很接近入选，怀疑阈值过严

推荐：

1. `primary_tag = threshold_false_negative`
2. 如果逻辑很清楚，可补 `thesis_clear`
3. `review_status` 通常先从 `draft` 开始

### 7.4 看起来像事件驱动噪声

推荐：

1. `primary_tag = event_noise_suspected`
2. 如果同时边际优势不强，可补 `weak_edge`
3. notes 写清楚你认为是哪个事件或哪类噪声在主导

### 7.5 逻辑能讲，但市场过于拥挤

推荐：

1. `primary_tag = crowded_trade_risk`
2. 如果你仍认可其逻辑，可补 `thesis_clear`
3. 不要因为拥挤就自动否定其研究质量

---

## 8. notes 最少应该写什么

notes 不是可有可无。最少写三件事：

1. 你为什么给这个主标签。
2. 你看过了哪些页面证据。
3. 你认为问题属于选股层还是执行层。

一个合格示例：

> 入选理由基本成立，但 Layer C 分歧较大，且当前 Layer B 解释来自历史兼容回退字段，边际优势不够厚。该票未进入 buy_orders 的直接原因是 blocked_by_reentry_score_confirmation，因此不应简单归类为阈值误杀。

一个不合格示例：

> 感觉一般。

这类 notes 没有任何后续研究价值。

---

## 9. 一页决策表

| 你观察到的现象 | 更可能的主标签 | 常见补充标签 | 备注 |
| --- | --- | --- | --- |
| 已入选且逻辑扎实 | `high_quality_selection` | `thesis_clear` | 强调“被选出来是合理的” |
| 已入选但边际优势弱 | `weak_edge` | `event_noise_suspected` | 不等于完全错误 |
| near-miss 疑似阈值误伤 | `threshold_false_negative` | `thesis_clear` | 重点是“规则挡掉了它” |
| 事件驱动痕迹太重 | `event_noise_suspected` | `weak_edge` | 重点是“噪声主导” |
| 市场过于拥挤 | `crowded_trade_risk` | `thesis_clear` | 重点是“拥挤而非逻辑不存在” |
| 研究通过但执行阻塞 | `weak_edge` 或 `high_quality_selection` | 视情况补 `thesis_clear` | verdict 和 notes 必须写明 execution blocker |

---

## 10. 最常见误区

### 10.1 把 `research_verdict` 当主标签用

错误原因：

1. 这样会破坏聚合统计。
2. 后面无法稳定按主标签计数。

### 10.2 因为没买入，就打成 `threshold_false_negative`

错误原因：

1. 没买入可能是执行 blocker。
2. 阈值误伤只适用于真正被筛选规则挡掉的 near-miss。

### 10.3 主标签和补充标签表达相反含义

例如：

1. 主标签写 `high_quality_selection`
2. tags 却只写 `weak_edge` 和 `event_noise_suspected`

这种组合会让后续读者根本不知道你到底想表达什么。

### 10.4 `adjudicated` 用得太早

如果没有二次讨论或统一裁决，不要直接使用 `adjudicated`。

---

## 11. 推荐工作流

建议研究员按下面顺序写 feedback：

1. 先浏览 report 和 trade date 上下文。
2. 再看 selected、execution bridge、near-miss 和 funnel。
3. 先确定问题层级。
4. 再确定主标签。
5. 再补 tags。
6. 再填 `research_verdict`。
7. 最后写 notes 和 `review_status`。

如果团队需要周度汇总，可以采用：

1. 当日先写 `draft`。
2. 周度复盘升级为 `final`。
3. 争议样本再升级为 `adjudicated`。

---

## 12. 和现有页面手册怎么配合使用

三份文档的分工建议这样理解：

1. [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md) 负责告诉你“先点哪里”。
2. [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md) 负责告诉你“每个区域为什么看、怎么看”。
3. 本文负责告诉你“看完以后具体怎么打标签”。
4. [Replay Artifacts 案例手册：2026-03-11 的 300724 为什么入选但未买入](./replay-artifacts-case-study-20260311-300724.md) 负责用真实 blocker 样本训练你的归因直觉。

如果你是第一次接触这个工作流，建议顺序是：

1. 先看速查。
2. 再照着长手册跑一遍页面。
3. 再读本文统一标签口径。
4. 最后读案例手册校准“执行阻塞 vs 选股失败”的判断。

---

## 13. 最终原则

这套标签体系最重要的不是“写得漂亮”，而是保证后续能做稳定复盘。

请坚持三条原则：

1. 主标签只表达一个核心结论。
2. notes 必须能解释这个结论。
3. 先分清选股层和执行层，再下标签。

只要这三条不乱，research feedback 才会从“个人备注”变成“团队可累计的研究资产”。
