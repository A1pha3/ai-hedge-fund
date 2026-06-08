# Layer C 策略完全讲解：从多 Agent 共识到 watchlist 的研究层算法手册

适用对象：第一次系统学习本项目 Layer C 聚合逻辑的开发者、研究者、产品同学、复盘人员。

这份文档解决的问题：把分散在产品方案、执行层代码、replay artifacts 页面和历史调参记录里的 Layer C 知识，整理成一份可以长期查阅的中文讲义。

建议搭配阅读：

1. [Layer B 策略完全讲解](./03-layer-b-complete-beginner-guide.md)
2. [Layer B 一页速查卡](./05-layer-b-one-page-cheatsheet.md)
3. [Replay Artifacts 选股阅读手册](../manual/replay-artifacts-stock-selection-manual.md)
4. [机构多策略框架 v1.4](../product/institutional_multi_strategy_framework_v1.4.md)
5. [Layer C P1 变更提交说明](../analysis/layer-b-p1-pr-summary-20260316.md)
6. [Layer C 一页速查卡](./19-layer-c-one-page-cheatsheet.md)
7. [Layer C 专题首页](./20-layer-c-topic-reading-path.md)
8. [Layer C 常见问题 FAQ](./21-layer-c-faq.md)

---

## 1. 学习目标

读完后，你应该能真正回答下面这些问题：

1. Layer C 在整个系统里到底负责什么，而不负责什么。
2. 18 个 Agent 的输出是怎样被标准化、加权、聚合成 `score_c` 的。
3. 为什么当前代码里会同时存在 `raw_score_c`、`adjusted_score_c`、`score_final` 和 `quality_score` 四种分数。
4. 为什么有些股票可以通过 Layer B，却仍然在 Layer C 被打回 `avoid` 或卡在 watchlist 之外。
5. 为什么看 Layer C 不能只看“支持票数”，还要看 cohort 贡献、B/C 冲突和执行桥接。
6. 当你在 replay artifacts 里看到一条 Layer C 记录时，应该怎样把它读成一句靠谱的研究判断。

---

## 2. 先用一句话理解 Layer C

如果只允许记一句话，请记这句：

**Layer C 是选股流水线里的多 Agent 深度研究层，负责把 Layer B 放行的高分候选，进一步做“共识确认、冲突识别和最终 watchlist 决策”。**

这句话里有四个关键词。

### 2.1 多 Agent

它不是再跑一套规则，而是把多种研究角色的结论放在一起看。

当前默认有两大 cohort：

1. 12 个 investor persona Agent。
2. 6 个 analyst Agent。

这意味着：

1. Layer C 的信息来源更丰富。
2. Layer C 天然会出现共识和分歧。
3. Layer C 不只是“给 Layer B 加一个 LLM 分数”。

### 2.2 深度研究

Layer B 主要回答“这只票在规则层面是否值得继续看”。

Layer C 进一步回答：

1. 不同研究角色是否真的认同这只票。
2. 如果不认同，分歧主要来自哪里。
3. 这是不是一只只是规则层看起来不错、但研究层逻辑并不扎实的票。

### 2.3 二次过滤

Layer C 不是展示层，它会实打实改变后续决策。

在当前代码里，Layer C 之后会发生三件事：

1. 生成 `score_c`。
2. 与 `score_b` 融合成 `score_final`。
3. 决定是否进入 watchlist，或者直接标记为 `avoid`。

### 2.4 研究与执行之间的桥

Layer C 是研究侧最后一道主闸门。

它后面才是：

1. watchlist 阈值。
2. buy order 约束。
3. T+1 执行确认。

所以：

1. Layer B 分高，不等于最终进入 watchlist。
2. Layer C 通过，不等于最终一定有 buy order。
3. 研究问题和执行问题必须分开看。

---

## 3. Layer C 在整个流水线里的位置

先把位置看清楚，后面很多阈值和分数才不会理解歪。

```text
Layer A 候选池
  -> Layer B 四策略打分与融合
  -> high_pool
  -> fast / precise agent 分析
  -> Layer C 聚合
  -> watchlist
  -> buy_orders
  -> execution
```

对应理解如下：

1. Layer A 负责先过滤掉明显不值得看的票。
2. Layer B 负责用规则和因子决定“哪些票值得花研究资源”。
3. Layer C 负责判断“这些票在多 Agent 视角下是否形成足够强的正向共识”。
4. watchlist 负责把 Layer C 结果再做最终研究入池判断。
5. buy_orders 和 execution 负责可交易性与真实执行。

因此，Layer C 的定位不是：

1. 重新做一遍 Layer B。
2. 单纯展示 LLM 理由。
3. 独立替代 execution。

它真正是：

1. Layer B 后的研究确认层。
2. B/C 冲突识别层。
3. watchlist 的上游共识闸门。

---

## 4. 当前代码里的核心入口在哪里

如果你只想抓主干，请先看这四个位置：

1. [src/execution/layer_c_aggregator.py](../../src/execution/layer_c_aggregator.py)
2. [src/execution/models.py](../../src/execution/models.py)
3. [src/execution/daily_pipeline.py](../../src/execution/daily_pipeline.py)
4. [src/research/artifacts.py](../../src/research/artifacts.py)

它们分别负责：

1. Layer C 聚合公式和冲突逻辑。
2. Layer C 输出数据结构。
3. watchlist 过滤和流水线接线。
4. replay artifacts 的可读化摘要。

这份文档默认以“当前代码实现”为准，而不是只引用产品设计历史版本。

---

## 5. Layer C 的核心数据结构

定义在 [src/execution/models.py](../../src/execution/models.py)。

### 5.1 LayerCResult：单标的聚合结果

你可以先记住这几个最关键字段：

1. `ticker`：标的代码。
2. `score_b`：上游 Layer B 分数。
3. `score_c`：Layer C 聚合后的研究分数。
4. `score_final`：Layer B 和 Layer C 融合后的最终分数。
5. `quality_score`：从 Layer B 的 fundamental 子因子里再抽出来的质量分。
6. `agent_signals`：各 Agent 标准化后的信号。
7. `agent_contribution_summary`：贡献摘要。
8. `bc_conflict`：B/C 冲突标签。
9. `decision`：当前 Layer C 决策标签。

这说明 Layer C 不是只输出一个 `score_c`，而是一整套“分数 + 解释 + 冲突 + 决策”的结果对象。

### 5.2 ExecutionPlan 里的 Layer C 位置

`ExecutionPlan` 会保留：

1. `layer_c_count`
2. `watchlist`
3. `logic_scores`
4. `selection_artifacts`

也就是说，后续所有 replay、watchlist、buy order 解释，都是沿着这条链路往下走的。

---

## 6. Layer C 的输入是什么

在 [src/execution/daily_pipeline.py](../../src/execution/daily_pipeline.py) 中，Layer C 的直接输入有两类：

1. `high_pool`：通过 Layer B fast gate 的候选。
2. `agent_results`：各 Agent 对这些候选给出的分析结果。

执行顺序大致是：

1. Layer B 先生成 `fused`。
2. 只保留 `score_b >= FAST_AGENT_SCORE_THRESHOLD` 的 `high_pool`。
3. 对 `high_pool` 跑 fast agent，必要时补 precise agent。
4. 把 `high_pool + agent_results` 送进 `aggregate_layer_c_results(...)`。

所以如果一只票连 Layer C 都没出现，首先要怀疑的是：

1. 它没过 Layer B fast gate。
2. 它被 high pool 上限截断了。

而不是直接怀疑 Layer C 聚合算法。

---

## 7. Agent 输出是怎么标准化的

标准化函数在 [src/execution/layer_c_aggregator.py](../../src/execution/layer_c_aggregator.py) 的 `convert_agent_signal_to_strategy_signal(...)`。

### 7.1 三元组格式

每个 Agent 的原始 payload 最终会被压缩成统一结构：

1. `direction`
2. `confidence`
3. `completeness`

这和 Layer B 的 `StrategySignal` 格式保持一致。

### 7.2 direction 的映射

当前规则很直接：

1. `bullish -> 1`
2. `bearish -> -1`
3. `neutral -> 0`

如果 signal 不是三种合法值之一，则：

1. `direction = 0`
2. `completeness = 0`

### 7.3 completeness 什么时候会变低

当前代码里，以下情况会降低完整度：

1. signal 非法。
2. reasoning 里带有 `error`。
3. `confidence <= 0`。

这里要注意：

1. `confidence <= 0` 且没有 reasoning 时，完整度会被降到最多 `0.5`。
2. 如果存在显式错误，完整度直接归零。

这意味着 Layer C 不是简单地“把 18 个 agent 都当作满权重”。

---

## 8. Agent 权重到底怎么算

默认权重定义在 [src/execution/layer_c_aggregator.py](../../src/execution/layer_c_aggregator.py)。

### 8.1 默认 cohort 配比

默认口径是：

1. 12 个 investor agent，每个 `0.06`。
2. 6 个 analyst agent，总共 `0.28`，均分后每个约 `0.0467`。

也就是：

1. investor cohort 合计约 `0.72`
2. analyst cohort 合计约 `0.28`

这和产品设计文档的 Layer C 角色定位一致：更偏向深度确认，而不是纯短线择时。

### 8.2 当前代码还做了一步 investor scale

当前生产默认值不是直接拿上述权重聚合，而是先做：

$$
w^{scaled}_{investor} = 0.90 \times w_{investor}
$$

对应环境变量：

1. `DAILY_PIPELINE_LAYER_C_INVESTOR_WEIGHT_SCALE`，默认 `0.90`

这一步的含义是：

1. investor cohort 仍然更重。
2. 但不会像最早口径那样，把 investor 声音放到过强。

### 8.3 权重还会再次归一化

权重不会无脑原样使用。

在 `_normalize_agent_weights(...)` 里，只保留 `completeness > 0` 的 active agent，再重新归一化。

因此：

1. 没有有效输出的 Agent，不占归一化席位。
2. 真正参与当日该票聚合的，是 active agent 集合。
3. 同一套默认权重，在不同股票上实际生效值可能不同。

---

## 9. Layer C 分数是怎么出来的

### 9.1 原始贡献公式

单个 Agent 的原始贡献近似可理解为：

$$
contribution^{raw}_j = w^{norm}_j \times direction_j \times \frac{confidence_j}{100} \times completeness_j
$$

所有 Agent 相加后得到：

$$
Score^{raw}_C = \sum_j contribution^{raw}_j
$$

这就是代码里的 `raw_score_c`。

### 9.2 当前代码还做了 bearish investor attenuation

对 investor cohort 的负向贡献，当前代码会再乘一个缩放系数：

$$
contribution^{adjusted}_j = 0.15 \times contribution^{raw}_j \quad (j \in investor, contribution^{raw}_j < 0)
$$

对应环境变量：

1. `DAILY_PIPELINE_LAYER_C_BEARISH_INVESTOR_CONTRIBUTION_SCALE`，默认 `0.15`

这一步非常关键。

它的意思不是“忽略 investor 的 bearish 观点”，而是：

1. 保留原始 bearish 证据用于冲突判定。
2. 同时避免 investor cohort 的负向声音把 blended 分数过度压死。

### 9.3 adjusted score 才是当前的 `score_c`

当前代码里：

1. `raw_score_c` 用于记录未经 attenuation 的真实研究分歧。
2. `adjusted_score_c` 用于生成最终 `score_c`。

也就是说：

1. 你在 UI 里看到的 `score_c`，是调整后的研究分数。
2. 但冲突和 avoid 某些逻辑，仍然会参考 `raw_score_c`。

这也是为什么 replay 页面同时展示 `adjusted_score_c` 和 `raw_score_c`。

---

## 10. Layer C 不只看分数，还会算质量分

质量分函数在 [src/execution/layer_c_aggregator.py](../../src/execution/layer_c_aggregator.py) 的 `_derive_quality_score(...)`。

### 10.1 quality_score 的来源

它不是从 Agent 文本理由里抽出来的。

它是从 Layer B 的 `fundamental` 策略里，再提取三个质量相关子因子：

1. `profitability`，权重 `0.40`
2. `financial_health`，权重 `0.35`
3. `growth`，权重 `0.25`

### 10.2 quality_score 的含义

它本质上是在问：

**这只票在基本面质量维度上，当前是偏强、偏弱，还是中性。**

如果 fundamental 子因子缺失严重，则会回退到：

1. 用整体 `fundamental_signal` 估一个质量分。
2. 再不行就回到默认中性 `0.5`。

### 10.3 它的作用

当前 `quality_score` 不直接进入 `score_final` 公式，但会进入：

1. replay artifacts 的解释层。
2. “为什么这只票虽然分过线，但仍需警惕质量陷阱”的研究语境。

所以它更像：

1. Layer C 的辅助解释信号。
2. fundamental 与 Layer C 衔接的桥接字段。

---

## 11. Layer B 和 Layer C 是怎么融合的

### 11.1 当前默认融合权重

当前代码默认值：

1. `DAILY_PIPELINE_LAYER_C_BLEND_B_WEIGHT = 0.55`
2. `DAILY_PIPELINE_LAYER_C_BLEND_C_WEIGHT = 0.45`

最终会再归一化，所以近似公式为：

$$
Score_{final} = 0.55 \times Score_B + 0.45 \times Score_C
$$

### 11.2 这里和产品文档存在历史差异

[机构多策略框架 v1.4](../product/institutional_multi_strategy_framework_v1.4.md) 里写的是：

$$
Score_{final} = 0.4 \times Score_B + 0.6 \times Score_C
$$

但当前代码实现已经改成 `0.55 / 0.45`。

原因不是产品文档错了，而是后来做过一次最小 Layer C P1 校准，结论沉淀在：

1. [Layer C P1 变更提交说明](../analysis/layer-b-p1-pr-summary-20260316.md)
2. [Layer C P1 短版提交模板](../analysis/layer-b-p1-short-templates-20260316.md)

因此，做当前系统分析时要分清：

1. 历史设计口径。
2. 当前生产代码口径。

本讲义以后者为准。

---

## 12. Layer C 里的 B/C 冲突是怎么定义的

当前冲突逻辑在 `aggregate_layer_c_results(...)` 里有两条主规则。

### 12.1 强 B、负 C

如果：

1. `score_b > 0.50`
2. `raw_score_c < 0`

则会标记：

1. `bc_conflict = b_strong_buy_c_negative`
2. `decision = watch`

这表示：

1. Layer B 认为这只票很强。
2. 但研究层已经出现净负向。
3. 当前系统不会直接把它视为健康强票，而是降级成需要观察的对象。

### 12.2 正 B、强 bearish C

如果：

1. `score_b > 0`
2. `raw_score_c < -0.30`

则会标记：

1. `bc_conflict = b_positive_c_strong_bearish`
2. `decision = avoid`

注意这里用的是 `raw_score_c`，不是调整后的 `score_c`。

原因很明确：

1. 调整后的 `score_c` 是为了防止 investor bearish 对 blended 分数过度压制。
2. 但如果原始研究层已经出现强烈 bearish 共识，系统仍然要把这类票识别成结构性冲突样本。

这正是“允许边缘票穿透”和“保留强冲突票 veto”之间的折中。

---

## 13. watchlist 是怎么从 Layer C 结果里出来的

watchlist 接线在 [src/execution/daily_pipeline.py](../../src/execution/daily_pipeline.py)。

当前逻辑很直接：

$$
score_{final} \ge WATCHLIST\_SCORE\_THRESHOLD \quad 且 \quad decision \neq avoid
$$

### 13.1 当前 watchlist 阈值

代码里默认值是：

1. `WATCHLIST_SCORE_THRESHOLD = 0.20`

因此，一只票就算：

1. `score_final` 过线
2. 但 `decision = avoid`

它也不会进入 watchlist。

### 13.2 watchlist 过滤理由怎么分类

在 `_classify_watchlist_filter(...)` 中，当前主过滤理由有两种：

1. `decision_avoid`
2. `score_final_below_watchlist_threshold`

这两类必须分开看。

因为它们分别意味着：

1. 研究层明确反对。
2. 研究层不是强反对，但综合共识厚度仍不够。

---

## 14. Replay Artifacts 里该怎么看 Layer C

### 14.1 最关键的摘要字段

在 replay 页面和 `selection_snapshot.json` 里，建议优先看：

1. `active_agent_count`
2. `positive_agent_count`
3. `negative_agent_count`
4. `neutral_agent_count`
5. `cohort_contributions`
6. `top_positive_agents`
7. `top_negative_agents`
8. `raw_score_c`
9. `adjusted_score_c`
10. `bc_conflict`

### 14.2 最稳的阅读顺序

建议按下面顺序：

1. 先看 `score_b`、`score_c`、`score_final`。
2. 再看 `bc_conflict`。
3. 再看 `cohort_contributions`，判断 investor 和 analyst 是一致还是对冲。
4. 再看 `top_positive_agents` 和 `top_negative_agents`。
5. 最后再去看 execution bridge，区分“会选”还是“会买”。

### 14.3 怎样读出一句可靠判断

如果你只想写一句研究判断，推荐模板：

“该样本在 Layer B 上由什么支撑，在 Layer C 上 investor / analyst 是否形成一致正向共识；若存在 `bc_conflict`，则说明它更像边缘研究样本而非干净强票。”

---

## 15. 当前默认参数速查

以下内容以 [src/execution/layer_c_aggregator.py](../../src/execution/layer_c_aggregator.py) 和 [src/execution/daily_pipeline.py](../../src/execution/daily_pipeline.py) 当前代码为准。

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `DAILY_PIPELINE_LAYER_C_INVESTOR_WEIGHT_SCALE` | `0.90` | investor cohort 预缩放 |
| `DAILY_PIPELINE_LAYER_C_BEARISH_INVESTOR_CONTRIBUTION_SCALE` | `0.15` | investor 负向贡献衰减 |
| `DAILY_PIPELINE_LAYER_C_BLEND_B_WEIGHT` | `0.55` | 最终分数中 B 权重 |
| `DAILY_PIPELINE_LAYER_C_BLEND_C_WEIGHT` | `0.45` | 最终分数中 C 权重 |
| `DAILY_PIPELINE_LAYER_C_AVOID_SCORE_C_THRESHOLD` | `-0.30` | 强 bearish avoid 阈值 |
| `WATCHLIST_SCORE_THRESHOLD` | `0.20` | watchlist 入池阈值 |

这些参数不是独立旋钮。

你改其中任何一个，都要连着观察：

1. `layer_c_count`
2. `watchlist_count`
3. `buy_order_count`
4. `decision_avoid` 分布
5. `score_final_below_watchlist_threshold` 分布

---

## 16. Layer C 最容易被误解的 6 个点

### 16.1 误区一：Layer C 是在覆盖 Layer B

不准确。

当前实现是融合，不是覆盖。

### 16.2 误区二：看 `score_c` 就够了

不够。

还要同时看：

1. `raw_score_c`
2. `bc_conflict`
3. `decision`

### 16.3 误区三：负向 agent 多，就一定更危险

不一定。

更关键的是：

1. 负向 agent 的权重是谁。
2. 它们的 confidence 多高。
3. investor 和 analyst 是否在同一方向上共振。

### 16.4 误区四：进入 watchlist 就等于会下单

不对。

watchlist 后面还有 buy order 约束和 T+1 确认。

### 16.5 误区五：Layer C 放宽就一定能改善交易结果

也不对。

如果释放出来的是结构性冲突样本，后面可能只是把噪声从 Layer C 挪到 execution。

### 16.6 误区六：产品文档写什么，当前代码就是什么

这个项目不是静态文档系统。

像 Layer C 的融合权重，历史设计口径和当前生产代码已经不一致，所以分析时必须以当前实现为准。

---

## 17. 当你要排查 Layer C 问题时，最小工作流是什么

建议按这个顺序做。

### 第一步：先确认问题是不是 Layer C

看：

1. `layer_b_count` 是否已经很低。
2. 候选是否根本没进入 Layer C。

如果 Layer B 本身几乎没放票，就不应优先怀疑 Layer C。

### 第二步：区分是 avoid 还是 near-miss

看 watchlist 过滤理由：

1. `decision_avoid`
2. `score_final_below_watchlist_threshold`

两类问题对应的调参方向不同。

### 第三步：判断是 investor 压制还是 analyst 不认同

重点看：

1. `cohort_contributions`
2. `top_negative_agents`

### 第四步：检查是不是 B/C 冲突样本

如果反复出现：

1. `b_strong_buy_c_negative`
2. `b_positive_c_strong_bearish`

说明你面对的是“规则层很强，但研究层不买账”的票。

### 第五步：最后再看 execution bridge

确认：

1. 它是研究层没过。
2. 还是研究层过了，但执行没承接。

---

## 18. 当前最重要的工程与研究结论

结合当前代码和近期窗口研究，可以把 Layer C 理解成下面这套折中设计：

1. 保留多 Agent 深度研究的主导作用。
2. 不再让 investor cohort 的 bearish 贡献无条件压死 blended score。
3. 但仍保留 `raw_score_c` 作为结构性冲突和 avoid veto 的证据。
4. 最终以 `score_final + decision` 的双条件决定 watchlist。

这套设计的核心意图不是“尽量多放票”，而是：

1. 尽量放出边缘但仍可研究的票。
2. 同时继续挡住研究层已经明显不认同的票。

---

## 19. 一页总结

如果你只想记住最关键的 8 句话，可以直接记这组：

1. Layer C 是多 Agent 深度研究层，不是又一层规则打分。
2. 它的输入是 Layer B 放行的高分池，不是全市场候选。
3. 当前 `score_c` 是调整后的研究分，`raw_score_c` 是未衰减的原始研究分。
4. investor bearish 贡献会被衰减，但强 bearish 原始共识仍可触发 `avoid`。
5. `score_final = 0.55 * score_b + 0.45 * score_c` 是当前代码默认口径。
6. 进入 watchlist 需要同时满足“最终分过线”和“不是 avoid”。
7. replay 里看 Layer C，不能只看分数，还要看 cohort、冲突和执行桥接。
8. 分析 Layer C 是否有问题，必须先确认主矛盾是不是其实还停留在 Layer B。

---

## 20. 继续深入时该看哪里

1. 聚合实现：[src/execution/layer_c_aggregator.py](../../src/execution/layer_c_aggregator.py)
2. 执行接线：[src/execution/daily_pipeline.py](../../src/execution/daily_pipeline.py)
3. replay 摘要生成：[src/research/artifacts.py](../../src/research/artifacts.py)
4. 产品历史口径：[../product/institutional_multi_strategy_framework_v1.4.md](../product/institutional_multi_strategy_framework_v1.4.md)
5. replay 读法：[../manual/replay-artifacts-stock-selection-manual.md](../manual/replay-artifacts-stock-selection-manual.md)
6. Layer B 背景：[./03-layer-b-complete-beginner-guide.md](./03-layer-b-complete-beginner-guide.md)
