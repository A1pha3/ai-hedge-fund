# Layer B 调参作战手册：从问题定位到逐步逼近最优参数

文档日期：2026 年 3 月 27 日  
适用范围：Layer B 规则调参、真实窗口复盘后的参数优化、研究员与 AI 助手协同实验  
文档定位：方法论文档，回答 why、what、how，不替代具体实验报告

建议搭配阅读：

1. [层 B 因子参数根因分析与实验矩阵](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)
2. [Layer B 策略完全讲解](./03-layer-b-complete-beginner-guide.md)
3. [Fundamental 五子因子联动复盘手册](./15-fundamental-subfactor-joint-review-manual.md)
4. [Layer B / Layer C 联动复盘手册](./22-layer-b-c-joint-review-manual.md)
5. [Execution Bridge 专业讲解](./24-execution-bridge-professional-guide.md)

---

## 1. 这份文档要解决什么问题

很多调参工作之所以反复打转，不是因为研究不够勤奋，而是因为没有把下面三件事分开：

1. 为什么要调。
2. 应该先调什么。
3. 调完以后用什么标准判断是更好，还是只是更热。

这份文档的目标，就是把 Layer B 调参从“凭直觉试数字”，变成一条可以重复执行的闭环方法。

读完后，研究人员和 AI 助手应该能按统一流程回答下面这些问题：

1. 当前 scarcity 的主矛盾是在供给、语义、融合还是阈值。
2. 当前应该优先修哪一类因子，而不是同时乱动多个旋钮。
3. 每次实验该记录哪些指标，怎样判断结果是有效改善还是副作用。
4. 什么时候应该继续放宽，什么时候应该停止，什么时候应该回滚。
5. 怎样把“调参实验”沉淀成后续可复用的方法，而不是一次性的口头经验。

---

## 2. 先讲结论：Layer B 调参的总原则

如果只保留最重要的原则，请记住下面 8 条。

### 2.1 先修语义，再降总阈值

`FAST_AGENT_SCORE_THRESHOLD` 是最后一道门，不是第一根因。

如果整体分布本身偏冷，直接把 `0.38` 改成 `0.36`，通常只会造成两种问题：

1. 把语义问题伪装成阈值改善。
2. 增加更多“结构并不好、只是刚好被放出来”的样本。

因此，直接降总阈值应放在调参序列的后段，而不是第一步。

### 2.2 先放宽中性项和缺失项，不先放宽强负项

业界更稳妥的做法，不是先去松动真正的负面信号，而是先处理两类更容易误伤好票的机制：

1. 中性项被当成 active 稀释正向样本。
2. 缺失项被隐式当成弱负面或残缺融合惩罚。

在当前系统中，最典型的就是：

1. neutral mean_reversion 参与 active normalization。
2. event_sentiment 缺失导致候选在靠近阈值时缺乏最后一脚助推。

### 2.3 先做条件式放宽，不做全市场统一放宽

条件式放宽的意思是：只有当样本已经具备较强正向结构时，才给予局部宽松。

例如：

1. 只有 `trend > 0` 且 `fundamental > 0` 时，才弱化 neutral mean_reversion 的稀释。
2. 只有在 `event_sentiment` 缺失而非明确负面时，才给更中性的处理。

这种做法比“所有样本一起放宽”更适合研究期，因为它更容易定位增量来自哪里。

### 2.4 先看新增样本质量，再看新增样本数量

Layer B 通过数从 `1` 变成 `4`，不一定就是好结果。

真正应该看的是：

1. 新增样本是不是更像高质量边缘票。
2. 它们在 Layer C 是否仍能站住。
3. 它们是否进入 watchlist、buy_order，还是只是把垃圾样本推到下游。

### 2.5 每次只动一种机制

不要在同一轮实验里同时修改：

1. MR 语义。
2. event 缺失处理。
3. profitability 规则。
4. heavy score 供给侧上限。
5. fast gate 阈值。

如果一轮实验同时改 3 个地方，你几乎不可能知道收益究竟来自哪一项。

### 2.6 把“宽松”理解为目标区间，不是单一数字

最优参数通常不是一个静态数字，而是一个在多窗口、多市场状态下表现稳定的区间。

当前更合理的目标，不是问“`0.38` 要不要改成 `0.36`”，而是问：

1. 日均 `layer_b_count` 是否从极低水平回到可研究区间。
2. 新增样本是否仍能通过后续层级验证。
3. 运行成本是否仍在可接受范围。

### 2.7 先修边缘误伤，再修全盘稀缺

当前窗口的证据已经很清楚：

1. 从全样本看，主要广义压制项是 `fundamental` 第一、`trend` 第二。
2. 但在接近阈值的边缘样本中，neutral mean_reversion 是关键压制项。

所以，MR 语义修正的价值主要是修边缘误伤，而不是一把解决全部 scarcity。

### 2.8 调参的终点不是“通过更多”，而是“研究漏斗更健康”

真正的目标应该是：

1. Layer B 不再冷到几乎掐断供给。
2. Layer C 不被无意义垃圾样本淹没。
3. watchlist 和 buy_order 的承接变得更稳定。
4. 调参逻辑可以被未来团队重复使用。

---

## 3. 什么叫“逼近最优参数”

在这个系统里，“最优参数”不应该被理解成单日、单窗口下让收益最大或通过数最多的那组数字。

更合理的定义是：

**在多个窗口中，能够稳定减少明显误伤，同时不过度释放低质量样本，并且仍保持后续研究层与执行层承接能力的一组参数区间。**

这一定义有四层含义：

1. 它是多目标优化，不是单指标优化。
2. 它关注稳定性，而不是偶发放量。
3. 它要求跨层验证，而不是只看 Layer B。
4. 它允许“区间最优”，不强迫你找到一个永远固定的点。

因此，调参的工作方法必须是迭代收敛，而不是一次性拍板。

---

## 4. 当前系统里，哪些地方可以调

为了避免“概念上知道要调，代码里却不知道从哪下手”，先把调参对象分成 5 类。

### 4.1 语义类参数

这一类决定某个 signal 是否被视为 active，以及 active 后怎样参与归一化。

当前最关键的是：

1. `LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE`
2. [src/screening/signal_fusion.py](../../../src/screening/signal_fusion.py) 中 `_normalize_for_available_signals()` 的 active 资格逻辑

适用问题：

1. 为什么边缘正样本总是差一点点。
2. 为什么 neutral signal 会把好票稀释下去。

### 4.2 供给类参数

这一类决定哪些候选有资格拿到更重的信号评分。

当前最关键的是：

1. `TECHNICAL_SCORE_MAX_CANDIDATES`
2. `FUNDAMENTAL_SCORE_MAX_CANDIDATES`
3. `EVENT_SENTIMENT_MAX_CANDIDATES`
4. `HEAVY_SCORE_MIN_PROVISIONAL_SCORE`

适用问题：

1. 为什么 Layer B 设计上看重 heavy legs，现实里却大量候选拿不到 heavy legs。
2. 为什么技术不亮但可能基本面不错的票，在进入完整评分前就死掉。

### 4.3 质量闸门类参数

这一类决定明显质量风险是否直接触发极负惩罚。

当前最关键的是：

1. `LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE`
2. [src/screening/signal_fusion.py](../../../src/screening/signal_fusion.py) 中 quality-first red flag 与 forced avoid 逻辑

适用问题：

1. 是否存在过强的左尾压制。
2. profitability 是否把本该保留的边缘好票直接打死。

### 4.4 决策阈值类参数

这一类决定最终分类和 high pool 入口。

当前最关键的是：

1. `FAST_AGENT_SCORE_THRESHOLD`
2. [src/screening/models.py](../../../src/screening/models.py) 中 `classify_decision()` 的 `watch` 阈值

适用问题：

1. 为什么 `watch` 与 high_pool 口径存在解释错位。
2. 是否已经完成语义修正，但最终仍被最后一道门卡住。

### 4.5 解释一致性类参数

这一类不是直接决定能否通过，而是决定研究人员是否容易看懂结果。

它包括：

1. watch 阈值与 fast gate 的对齐。
2. replay artifacts 中 blocker、conflict、reason 字段的解释口径。
3. 审核台账与实验命名规范。

这一类不一定直接改善业务结果，但会显著降低后续研究成本。

---

## 5. 调参优先级：先调什么，后调什么

这是整份文档最重要的一节。

### 5.1 第一优先级：neutral mean_reversion 参与语义

#### 为什么优先修 MR 语义

当前窗口的证据说明：

1. guarded 版本过弱。
2. full exclude 版本过强。
3. partial-weight 方向有效，但需要继续收敛中间档。

这意味着 MR 不是“有没有价值”的问题，而是“如何做成受控杠杆”的问题。

#### MR 应该调什么

优先研究的不是“完全排除”或“完全保留”，而是中间语义：

1. partial weight
2. dual-leg trigger
3. event-sensitive gating
4. baseline score floor

#### MR 应该怎么调

推荐顺序：

1. 先验证更保守的 partial weight。
2. 再调整触发条件，而不是继续只改 score floor。
3. 始终导出新增样本台账做人审。

当前实操经验上，优先级如下：

1. `quarter + event positive`
2. `third`
3. `half`
4. `full exclude`

这里的含义不是说 `quarter` 一定是最终答案，而是它目前最像一个可控中间档。

### 5.2 第二优先级：event_sentiment 缺失的中性化处理

#### 为什么优先修 event 缺失语义

当前窗口里，`event_sentiment` 真正为负的样本并不多，但缺失样本很多。

因此，很多边缘票的问题不是“新闻明确不好”，而是“没有拿到足够好的事件腿支持”。

这类问题在业界通常不应与真实负面事件同等处理。

#### event 缺失语义应该调什么

优先研究的方向是：

1. 区分 `missing` 与 `negative`。
2. 对 `missing` 做更中性的参与规则。
3. 只在双正向主腿已经成立时，降低缺失事件的拖累。

#### event 缺失语义应该怎么调

建议变体设计顺序：

1. 仅对 `event_sentiment_missing` 且 `trend > 0` 且 `fundamental > 0` 的样本做中性化。
2. 不改变 `event_sentiment < 0` 的惩罚。
3. 先不扩大 `EVENT_SENTIMENT_MAX_CANDIDATES`，先验证缺失语义本身。

### 5.3 第三优先级：供给侧放宽

#### 为什么此时再看供给侧

如果设计上依赖 heavy legs，但大量候选拿不到 heavy legs，那么最终问题并不只是分数冷，而是评分资源分配错位。

#### 供给侧应该调什么

优先考虑：

1. `EVENT_SENTIMENT_MAX_CANDIDATES`
2. `TECHNICAL_SCORE_MAX_CANDIDATES`
3. `FUNDAMENTAL_SCORE_MAX_CANDIDATES`
4. `HEAVY_SCORE_MIN_PROVISIONAL_SCORE`

#### 供给侧应该怎么调

建议顺序：

1. 先动覆盖面较窄、业务解释更清楚的一项。
2. 先做小幅扩容，不做一步拉满。
3. 同时监控运行耗时。

更具体地说：

1. `EVENT_SENTIMENT_MAX_CANDIDATES: 40 -> 60 -> 80`
2. `TECHNICAL_SCORE_MAX_CANDIDATES: 160 -> 180 -> 200`
3. `FUNDAMENTAL_SCORE_MAX_CANDIDATES: 100 -> 120 -> 140`
4. `HEAVY_SCORE_MIN_PROVISIONAL_SCORE: 0.05 -> 0.04 -> 0.03`

### 5.4 第四优先级：profitability / quality-first 软化

#### 为什么 profitability 不是第一步

当前窗口证据显示，profitability 不是主矛盾，但它仍然是左尾放大器。

这类参数不应第一步就动，因为：

1. 业务风险更高。
2. 容易释放真正质量差的票。
3. 一旦放宽，新增样本的解释成本更高。

#### profitability 应该调什么

优先研究的不是“彻底取消质量约束”，而是：

1. 区分 hard cliff 与边缘零分。
2. 看 zero-pass 模式是否过于严格。
3. 只软化局部极端机制。

#### profitability 应该怎么调

建议步骤：

1. 先单独验证 `profitability inactive` 或更温和的 zero-pass 语义。
2. 如果对当前窗口几乎零敏感，就不要继续在这条线上过度消耗时间。
3. 只有当 MR 和 event 路径都走完仍然过冷，才考虑继续深挖 profitability。

### 5.5 第五优先级：fast gate 和 watch 阈值

#### 为什么阈值应后置处理

这是最容易做、也最容易误判的一类改动。

它的价值主要有两个：

1. 在前面语义问题基本处理完后，做最后微调。
2. 修复解释一致性问题。

#### 阈值层应该调什么

优先做两类事：

1. 对齐 `watch` 与 high_pool 的语义边界。
2. 只在前序调参无效时，再做小步下调。

#### 阈值层应该怎么调

推荐顺序：

1. 先处理一致性。
2. 再评估是否需要 `0.38 -> 0.37 -> 0.36` 的小步试探。
3. 严禁在语义未修复前直接把阈值大幅调低。

---

## 6. 一套标准调参流程

下面这套流程，建议每次实验都完整走一遍。

### 6.1 第一步：固定研究基线

目标：确保大家讨论的是同一份事实，不是不同窗口、不同口径、不同缓存状态下的混合印象。

必须固定的内容：

1. 研究窗口。
2. report 目录。
3. 是否使用 frozen replay。
4. 当前默认模型路由。
5. 当前默认 Layer B 规则。

推荐产物：

1. `session_summary.json`
2. `daily_events.jsonl`
3. `layer_b_review/layer_b_pass_ledger.csv`
4. `layer_b_review/layer_b_review.md`

### 6.2 第二步：判断主矛盾属于哪一类

先问四个问题：

1. 大多数样本是死在供给不足，还是死在融合语义。
2. 是广义全盘偏冷，还是边缘票被继续压住。
3. 是强负项压制，还是中性项稀释。
4. 放出来的样本是死在 Layer C，还是能往下承接。

如果没有回答清楚这四个问题，不要进入下一步调参。

### 6.3 第三步：只选一个实验主题

实验主题必须是下面之一：

1. MR 语义
2. event 缺失语义
3. 供给侧扩容
4. profitability 软化
5. threshold 对齐或微调

一次只能选一个主题。

### 6.4 第四步：设计最小变体

一个合格的变体设计，必须回答四个问题：

1. 它具体改了哪个变量。
2. 它为什么应该影响当前窗口的主矛盾。
3. 它为什么比其它方案更保守或更可控。
4. 如果失败，会以什么形式失败。

示例：

1. 不是“放宽 MR”。
2. 而是“在 `trend > 0` 且 `fundamental > 0` 且 `event_sentiment > 0` 时，把 neutral MR 的 active raw weight 降到 1/4”。

### 6.5 第五步：先跑窗口级对照

至少要对照三类结果：

1. baseline
2. 当前候选变体
3. 一个更保守或更激进的参照变体

例如：

1. baseline
2. `quarter + event positive`
3. `third`

这样做的目的，是避免只知道“变好了”，却不知道自己处在哪个梯度上。

### 6.6 第六步：导出新增样本人工审核台账

窗口级对照只是第一层。

必须继续做两件事：

1. 导出新增释放样本台账。
2. 做人工审核打标。

最少要区分四类结论：

1. 优秀候选
2. 边界但可接受
3. 可疑放行
4. 明显不该通过

### 6.7 第七步：做跨层承接检查

如果新增样本全部在 Layer C 被一致判负，或者全部死在 watchlist 之下，那么 Layer B 的放宽就可能只是把问题往下游移动。

因此要继续看：

1. `avg_watchlist_count`
2. `avg_buy_order_count`
3. Layer C 冲突分布
4. execution blocker 分布

### 6.8 第八步：决定继续、停止或回滚

可以继续的条件：

1. 新增样本质量总体可接受。
2. 下游承接没有明显恶化。
3. 运行成本没有超出预算。

应该停止的条件：

1. 增量很小，但副作用明显。
2. 新增样本多数属于可疑放行。
3. 变体结果不稳定，只在单日偶发有效。

应该回滚的条件：

1. 新增样本大面积低质量。
2. Layer C / watchlist 负担明显失控。
3. 解释复杂度已经远高于收益。

---

## 7. 每一类因子应该怎么调

下面把“what”和“how”进一步落细。

### 7.1 neutral mean_reversion

这是当前最应该优先迭代的因子语义。

#### MR 的推荐调法

1. 先从 partial-weight 族继续收敛。
2. 优先收紧触发条件，不优先直接增减 score floor。
3. 区分 `event positive`、`event missing`、`event negative` 三种环境。

#### MR 的不推荐调法

1. 直接默认 full exclude。
2. 只在 `0.32`、`0.33`、`0.34` 之间反复抖 threshold。
3. 不做人工审核，只看 `delta`。

#### 当前推荐研究序列

1. `quarter + event positive`
2. `quarter + event missing neutralized`
3. `third`
4. `half`

### 7.2 event_sentiment

这条腿的核心，不是“新闻越多越好”，而是“缺失不应被误当成明确利空”。

#### event 的推荐调法

1. 先调整 `missing` 语义。
2. 再考虑扩大 `EVENT_SENTIMENT_MAX_CANDIDATES`。
3. 始终保留真实负面事件的约束。

#### event 的不推荐调法

1. 把 `missing` 与 `negative` 合并处理。
2. 在没有审核运营能力的情况下大幅扩大 event 覆盖面。
3. 用 event 扩容去掩盖 MR 语义问题。

### 7.3 fundamental 与 trend

从广义统计看，它们是压制大多数样本的主要来源。

这意味着它们重要，但不意味着应该立刻放宽。

#### fundamental 与 trend 的推荐调法

1. 先区分“真负面”与“没拿到完整重评分”。
2. 先处理供给问题，再处理因子规则本身。
3. 优先从具体子因子诊断入手，而不是一把放松整个 fundamental。

#### fundamental 与 trend 的不推荐调法

1. 直接整体降低 fundamental 的负面强度。
2. 在不知道主拖累子因子的前提下泛化修改。
3. 把 fundamental 的广义压制误判为唯一主开关。

### 7.4 profitability

这条腿的研究方法应该更保守。

#### profitability 的推荐调法

1. 只在其它路径收效不足时再进入深挖。
2. 优先验证 zero-pass mode 的边缘软化。
3. 始终保留真正的质量红旗。

#### profitability 的不推荐调法

1. 直接关闭 quality-first guard。
2. 把 profitability 当成当前 scarcity 的唯一元凶。
3. 在没有新增样本台账的情况下上线更宽松模式。

---

## 8. 验收指标：怎样判断这轮实验值不值得继续

建议把指标分成四层。

### 8.1 第一层：Layer B 漏斗指标

至少记录：

1. `avg_layer_b_count`
2. `nonzero_layer_b_days`
3. `near_threshold_count`
4. `layer_b_pass_delta`

这一层解决的是“有没有真的增加可研究供给”。

### 8.2 第二层：新增样本质量指标

至少记录：

1. `added_sample_count`
2. `excellent_candidate_ratio`
3. `acceptable_borderline_ratio`
4. `suspicious_release_ratio`
5. `obviously_bad_ratio`

这一层解决的是“增加的是不是好样本”。

### 8.3 第三层：跨层承接指标

至少记录：

1. `avg_watchlist_count`
2. `avg_buy_order_count`
3. `layer_c_negative_rejection_ratio`
4. `execution_blocked_ratio`

这一层解决的是“放出来的样本能否被下游真正承接”。

### 8.4 第四层：工程成本指标

至少记录：

1. `avg_total_day_seconds`
2. event 分析耗时变化
3. heavy score 覆盖面变化
4. 缓存命中与资源消耗变化

这一层解决的是“是否为了少量改善付出过高成本”。

---

## 9. 一套推荐的实验顺序

如果现在要从当前窗口继续往下做，我建议按下面顺序推进。

### 9.1 阶段 A：修边缘误伤

目标：先把明显接近阈值、却被中性语义压住的样本释放出来。

顺序：

1. MR `quarter + event positive`
2. MR `quarter + event missing neutralized`
3. MR `third`

验收重点：

1. 新增样本台账质量
2. Layer C 承接情况

### 9.2 阶段 B：修缺失惩罚

目标：避免 `event_sentiment_missing` 对双正向主腿形成不必要的残缺惩罚。

顺序：

1. 缺失事件中性化语义
2. 小步扩大 event 覆盖面

验收重点：

1. 是否只放出更合理的边缘票
2. 是否引入过多新闻噪声

### 9.3 阶段 C：修供给错配

目标：让更多候选有机会获得设计上应有的重评分资源。

顺序：

1. `EVENT_SENTIMENT_MAX_CANDIDATES`
2. `TECHNICAL_SCORE_MAX_CANDIDATES`
3. `FUNDAMENTAL_SCORE_MAX_CANDIDATES`
4. `HEAVY_SCORE_MIN_PROVISIONAL_SCORE`

验收重点：

1. 分布是否真正变暖
2. 成本是否过快上升

### 9.4 阶段 D：修质量闸门与最后一道门

目标：只在前面三阶段仍不足时，才进一步处理高风险改动。

顺序：

1. profitability 局部软化
2. `watch` 与 high_pool 口径一致化
3. fast gate 微调

验收重点：

1. 是否开始明显释放低质量样本
2. 是否只是数字好看但业务解释变差

---

## 10. 研究人员与 AI 助手如何协同

这部分是为了让文档真正可执行。

### 10.1 研究人员负责什么

研究人员最应该负责的是判断质量，而不是手工跑所有实验。

研究人员的核心职责：

1. 选择研究窗口。
2. 明确当前假设。
3. 审核新增样本质量。
4. 决定是否继续下一轮。

### 10.2 AI 助手负责什么

AI 助手更适合承担：

1. 代码定位
2. 变体实现
3. 批量对照实验
4. 产物整理
5. 跨窗口结果归纳

### 10.3 一轮标准协作模板

研究人员先给出：

1. 当前窗口
2. 当前主假设
3. 本轮只允许改一个机制

AI 助手按顺序执行：

1. 确认当前 baseline 和产物位置。
2. 定位相关代码与现有变体。
3. 实现一个最小变体。
4. 跑 baseline 与对照变体。
5. 导出新增样本审核台账。
6. 汇总窗口级指标与新增样本质量摘要。
7. 明确是否建议进入下一轮。

---

## 11. AI 助手执行清单

下面这份清单可以直接作为操作模板。

### 11.1 输入清单

开始实验前，AI 助手必须先确认：

1. 当前 report 目录
2. 当前 trade dates
3. 当前 baseline 规则名
4. 本轮唯一实验主题
5. 需要输出的对照产物目录

### 11.2 执行顺序

1. 读取当前 Layer B 根因文档和最近实验结论。
2. 只选一个机制设计最小变体。
3. 补单元测试或注册变体。
4. 跑聚焦测试。
5. 跑窗口级规则对照。
6. 导出新增样本审核台账。
7. 生成 Markdown 摘要。
8. 汇总建议：继续、停止或回滚。

### 11.3 输出格式

AI 助手的每轮输出，至少应包括：

1. 本轮假设
2. 本轮改动
3. baseline 与变体对照结果
4. 新增样本列表
5. 人工审核建议
6. 下一步建议

### 11.4 禁止事项

AI 助手不应：

1. 一次实现多个独立调参主题。
2. 只汇报 `delta`，不导出新增样本。
3. 只看 Layer B，不看 Layer C / execution 承接。
4. 在没有 baseline 的前提下直接宣布某个参数“更优”。

---

## 12. 常见误区

### 12.1 误区一：通过数太少，先降阈值

这是最常见、也最容易把问题搞乱的做法。

更正确的顺序是：

1. 先判断整体分布偏冷的原因。
2. 先修语义和供给。
3. 最后才考虑降阈值。

### 12.2 误区二：fundamental 是主压制项，所以先放 fundamental

广义统计上确实如此，但这并不自动意味着首先应该放它。

如果当前目标是修边缘误伤，那么先动 MR 或 event 缺失语义，通常更安全、可解释性也更好。

### 12.3 误区三：新增样本多就是成功

如果新增样本大多数在人工审核中被判定为可疑放行，或者全部死在 Layer C，那么这轮实验不应算成功。

### 12.4 误区四：单窗口有效就可以默认上线

单窗口结果只能用于方向判断，不能直接等同于长期默认参数。

至少应继续做：

1. 跨窗口复验
2. 市场状态对照
3. 人工审核复核

---

## 13. 最小落地版本：如果你今天就要开始做

如果今天就要开始下一轮，而且希望路径最务实，可以直接按下面步骤做。

1. 把当前 baseline、MR quarter 和下一版 event-missing neutral 变体设为三组对照。
2. 只在当前窗口先跑一轮窗口级对照。
3. 导出新增样本台账。
4. 研究人员优先审核新增样本，而不是先看收益。
5. 如果新增样本质量可接受，再补 Layer C 承接检查。
6. 只有在这一步通过后，才进入下一轮供给侧实验。

这条路径的优点是：

1. 风险可控。
2. 解释清楚。
3. 适合持续迭代。
4. 最符合当前窗口已经暴露出来的真实问题结构。

---

## 14. 最终总结

Layer B 调参不应被理解为“找一个更热的数字”，而应被理解为一套分层收敛的方法。

当前最合理的方法论是：

1. 先固定基线。
2. 先判断主矛盾。
3. 一次只动一种机制。
4. 先修中性项与缺失项误伤。
5. 用新增样本审核台账做质量验证。
6. 再看 Layer C 和 execution 是否承接。
7. 只有在前面都验证过后，才动更重的质量闸门或总阈值。

如果持续按这套方法执行，团队得到的就不只是某一轮实验结果，而是一条能够稳定逼近最优参数区间的研究工作流。
