# Profitability 子因子专业讲解：hard cliff、聚合陷阱与实验口径

适用对象：已经理解 Layer B 和 fundamental 基本结构，现在要单独研究 profitability 子因子的开发者、研究者、复盘人员。

这份文档解决的问题：

1. profitability 到底在测什么，而不是泛泛说“盈利质量”。
2. 为什么它在业务上会呈现 hard cliff 感。
3. 为什么“把 confidence 调小一点”经常不但没放松，反而更差。
4. 它和 quality-first guard、forced avoid、Layer C 质量分之间是什么关系。
5. 做 profitability 实验时，什么是合理口径，什么是容易误导的口径。

建议搭配阅读：

1. [因子聚合语义入门](./01-aggregation-semantics-and-factor-traps.md)
2. [Fundamental 因子专业讲解](./07-fundamental-factor-professional-guide.md)
3. [层 B 因子参数根因分析与实验矩阵](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)
4. [Layer B 最小规则变体验证](../analysis/layer-b-rule-variant-validation-20260312.md)

---

## 1. 先说结论

如果只记住最核心的判断，可以先记这 7 条：

1. profitability 是 fundamental 的一个子因子，不是整条 fundamental 的全部。
2. 它当前只看三项利润质量阈值，且采用离散分支，不是连续打分。
3. 其中最敏感的分支是 `positive_count == 0`，默认会直接走负向分支，这就是 hard cliff 的来源。
4. profitability 的问题首先是语义问题，其次才是参数问题。
5. 在当前聚合器里，简单降低 profitability 的 `confidence`，并不等于温和化负项。
6. profitability 会影响 fundamental 最终方向，也可能通过 quality-first guard 把样本直接推进 forced avoid。
7. 做 profitability 实验时，最可靠的是改 `zero_pass_mode` 或阈值分支语义，而不是先拍脑袋改一个数值系数。

---

## 2. 它在代码里到底是什么

profitability 的实现入口在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L415) 的 `_score_profitability()`。

它属于 fundamental 五个子因子之一，默认权重在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L75) 定义为：

1. `profitability = 0.25`

这说明它很重要，但不是 fundamental 的一票否决器。真正的问题在于：

1. 它的位置靠前。
2. 它的分支语义偏硬。
3. 它容易和 financial_health 一起形成质量红旗组合。

---

## 3. 当前它具体看哪三项

当前指标与阈值如下：

1. `return_on_equity >= 0.15`
2. `net_margin >= 0.20`
3. `operating_margin >= 0.15`

这三项的共同特点是：

1. 都偏利润质量，不是收入规模。
2. 都偏经营结果，不是市场情绪。
3. 都倾向筛掉“故事很好、但赚钱质量不够”的票。

因此 profitability 的真实问题不是“公司会不会增长”，而是：

1. 它赚的钱够不够厚。
2. 经营利润有没有质量。
3. 股东回报能力是否站得住。

---

## 4. 为什么它会呈现 hard cliff

核心原因在于，它不是连续评分，而是先数 `positive_count`。

当前分支逻辑：

1. `positive_count >= 2`：`direction = +1`
2. `positive_count == 1`：`direction = 0`
3. `positive_count == 0`：默认 `direction = -1`

也就是说，这里没有“稍微差一点但仍是弱正”的细分层。

一旦从 `1 项达标` 掉到 `0 项达标`，语义就会发生跳变：

1. 从中性
2. 直接变成负向

这就是 hard cliff 的本质。

它不是数值连续变化，而是分类语义突然折断。

### 4.1 当前窗口实证：到底是哪一项最常不过线

为了把上面的机制落到真实样本，2026-03-27 对当前窗口 `20260323..20260326` 做了一次 profitability 三指标拆解。产物见：

1. [scripts/analyze_profitability_subfactor_breakdown.py](../../scripts/analyze_profitability_subfactor_breakdown.py)
2. [data/reports/profitability_subfactor_breakdown_current_window_20260327.json](../../data/reports/profitability_subfactor_breakdown_current_window_20260327.json)

先看参与统计的范围：

1. 在当前窗口所有 blocked 样本里，真正拿到 profitability 评分的有 `287` 个。
2. 这 `287` 个里，最终 `fundamental <= 0` 的有 `180` 个。
3. 其中 `positive_count = 0` 的有 `164` 个；而在 `fundamental <= 0` 子集里，`positive_count = 0` 的有 `149` 个。

如果只问“单个指标谁最常不过阈值”，当前窗口顺序是：

1. `net_margin < 0.20`：`246` 次
2. `return_on_equity < 0.15`：`210` 次
3. `operating_margin < 0.15`：`191` 次

如果只看 `fundamental <= 0` 的 profitability 已评分样本，顺序仍然一样：

1. `net_margin` 失败：`176` 次
2. `return_on_equity` 失败：`171` 次
3. `operating_margin` 失败：`154` 次

所以如果一定要选“最常不过线的单项”，答案是：

1. `net_margin`

但这还不是最重要的结论。

### 4.2 当前窗口里 hard cliff 最典型的失败形态

如果只盯“哪一项失败最多”，很容易误判 profitability 的真实业务形态。

当前窗口里最关键的不是某一项单独不过线，而是三项一起不过线：

1. 在所有 profitability 已评分的 blocked 样本里，最常见失败组合是 `ROE + net_margin + operating_margin` 三项全失败，共 `164` 个。
2. 第二常见组合才是 `ROE + net_margin` 双失败，共 `38` 个。
3. `net_margin + operating_margin` 双失败有 `27` 个。
4. 只有 `net_margin` 单独失败的有 `17` 个。
5. 只有 `ROE` 单独失败的只有 `8` 个。

如果只看 `fundamental <= 0` 的子集，这种集中度更高：

1. `ROE + net_margin + operating_margin` 三项全失败有 `149` 个。
2. `ROE + net_margin` 双失败有 `22` 个。
3. `net_margin + operating_margin` 双失败有 `5` 个。
4. 三项全过但 fundamental 仍然非正的只剩 `4` 个。

这说明当前窗口里 profitability 的真实主杀器不是“某一项偶尔踩线”，而是：

1. 大量样本在利润质量三项上同时都不过线。
2. 一旦三项全失败，`positive_count = 0` 就稳定触发 hard cliff。
3. 所以系统感受到的不是“一个指标稍微偏弱”，而是“整段盈利质量整体站不住”。

### 4.3 这组实证该怎么解释

一句话版：

1. 单项频率上，`net_margin` 是最常不过线的指标。
2. 但 profitability 的核心杀伤并不是 `net_margin` 单独失败，而是三项一起失败。
3. 也就是说，当前窗口最典型的失败不是“利润率略低”，而是“ROE、净利率、营业利润率同时都不达标”。
4. 这也是为什么 profitability 在业务上会表现成 hard cliff，而不是温和扣分。
5. 当前窗口里 `positive_count = 0` 的样本没有任何 near-threshold 样本，说明一旦命中 profitability hard cliff，通常已经不是 `0.38` 边缘问题，而是更深层的质量问题。

### 4.4 这些“三项全失败”样本主要集中在哪些行业和体量

这一步也很重要，因为它决定我们该把问题理解成“全市场普遍冷”，还是“少数赛道系统性偏冷”。

当前窗口里，`ROE + net_margin + operating_margin` 三项全失败的 `164` 个 blocked 样本，行业集中度最高的是：

1. `通信`：`30`
2. `电子`：`30`
3. `电力设备`：`24`
4. `机械设备`：`16`
5. `计算机`：`13`
6. `有色金属`：`11`
7. `石油石化`：`9`

如果只看其中 `fundamental <= 0` 的子集，头部结构仍基本不变：

1. `电子`：`26`
2. `通信`：`23`
3. `电力设备`：`20`
4. `机械设备`：`16`
5. `计算机`：`13`

这说明：

1. 当前窗口里的 profitability 深层失败，不是均匀撒在所有行业上的。
2. 它明显更集中在科技成长和设备制造相关赛道。
3. 因而这更像“部分赛道利润质量结构性偏冷”，而不是“整个市场都一样差”。

再看市值分布，同样不是“小票垃圾堆”的简单故事：

1. `300b_to_1000b`：`76`
2. `100b_to_300b`：`48`
3. `ge_1000b`：`39`
4. `lt_100b`：`1`

这意味着：

1. 三项全失败样本主要集中在中大市值区间。
2. 它不是“只有很小很差的票才会被 profitability 打死”。
3. 系统当前过滤掉的，里面包含大量主流赛道里的中大盘股票。

### 4.5 这对后续实验意味着什么

这组行业和市值分布，给出的后续研究含义是：

1. 不能把 profitability hard cliff 简化理解成“清理低质量尾部小票”。
2. 它在当前窗口里，实际上对一批科技成长和设备链的中大盘样本也在形成系统性压制。
3. 但由于 `neutral` 和 `inactive` 在当前窗口依然 `delta = 0`，这批样本即使解除 profitability hard cliff，也未必能直接变成 Layer B 边缘通过票。
4. 因此，更合理的下一步不是直接放松 profitability，而是判断：
	1. 这些赛道样本到底是基本面真的偏弱。
	2. 还是当前 profitability 阈值对某些赛道口径存在结构性失配。
5. 如果后面继续做 profitability 研究，更值得优先看的不是全市场统一降阈值，而是：
	1. 行业分层口径。
	2. 与 growth、financial_health 的联动语义。
	3. 这些样本在 Layer C 研究视角里是否同样被判定为低质量。

---

## 5. `zero_pass_mode` 三种模式到底差什么

当前实验开关是：

1. `LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE`

支持三种模式：

### 5.1 `bearish`

默认模式。

含义：

1. `0` 项达标就是负向。
2. 这会保留当前最严格的盈利底线。

### 5.2 `neutral`

含义：

1. `0` 项达标不再直接给负向。
2. 但子因子仍然 active，仍然参与聚合。

风险：

1. 看起来温和，但不一定真正释放边缘票。
2. 甚至可能因为聚合一致性变化，让结果更怪。

### 5.3 `inactive`

含义：

1. `0` 项达标时直接 `completeness = 0`。
2. 相当于把 profitability 从 fundamental 聚合里移出。

业务意义：

1. 它不是“负面更弱”。
2. 它是“这条子因子暂时不发言”。

这也是为什么它通常比简单改 confidence 更符合实验语义。

---

## 6. 为什么“降低 confidence”不是正确修法

这个问题最容易误导人。

直觉会觉得：

1. profitability 太严。
2. 那就把负向时的 confidence 从 `100` 降到 `40`。
3. 这样不就温和了吗。

但当前聚合器不是线性加法。

在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L148) 的 `aggregate_sub_factors()` 里：

1. 先根据各子因子方向和强度形成总方向。
2. 再看有多少子因子和最终方向一致。
3. 再用一致性去乘最终 confidence。

所以你改 profitability 的 confidence，不只是“把负项音量调小”，还会间接改变：

1. fundamental 的最终方向判定。
2. 一致性比例。
3. 最终 confidence。

这就是为什么一些样本上会出现反直觉结果：

1. 你以为是在放松规则。
2. 实际却把整条 fundamental 变得更模糊。

更细的机制说明已经写在 [01-aggregation-semantics-and-factor-traps.md](./01-aggregation-semantics-and-factor-traps.md)。

---

## 7. 它和 quality-first guard 是怎么串起来的

profitability 自己只是子因子，但在 [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py#L78) 的 `_has_quality_first_red_flag()` 中，它会和其他质量腿一起被二次判断。

两类典型红旗：

1. profitability 和 financial_health 同时为负，且置信度都较高。
2. profitability 命中 hard cliff，同时 financial_health 与 growth 也没有形成有效对冲。

一旦命中，后果不是“稍微扣点分”，而是：

1. 进入 `forced_avoid`
2. `score_b` 直接被打到极负侧
3. 可能触发冷却逻辑

这说明 profitability 的业务影响有两层：

1. 先拖 fundamental。
2. 再可能被 red flag 放大成更强的系统级回避。

---

## 8. 它和 Layer C 的关系

在 [src/execution/layer_c_aggregator.py](../../src/execution/layer_c_aggregator.py#L162) 中，Layer C 还会从 fundamental 里抽取 quality 相关子因子再算 quality score。

其中 profitability 就是核心输入之一。

这代表：

1. profitability 不是只影响 Layer B fast gate。
2. 它还会影响后续“这只票质量到底好不好”的解释层口径。

所以对 profitability 的变更，不能只盯 `layer_b_count`，还要看：

1. 新释放的样本在 Layer C 是继续存活，还是马上被质量口径打回去。

---

## 9. 复盘时应该怎么看 profitability

建议按下面顺序看。

### 9.1 先看 `positive_count`

这是第一判断位。

1. `2` 或 `3`：通常不是 profitability 主问题。
2. `1`：边缘样本，更多看其他子因子是否支撑。
3. `0`：硬 cliff 高风险样本。

### 9.2 再看 `zero_pass_mode`

同一个 `positive_count = 0`，在不同模式下含义完全不同：

1. `bearish`：强负
2. `neutral`：中性但仍 active
3. `inactive`：不参与聚合

### 9.3 再看是不是和 financial_health 一起坏掉

如果是，那就不要只把它看成“单个盈利因子问题”，而应看成质量组合问题。

### 9.4 最后再看它对 fundamental 最终方向造成了什么

重点不是“profitability 自己负不负”，而是：

1. 它有没有把整条 fundamental 拖成负向。
2. 它有没有让 fundamental 的一致性明显变差。

---

## 10. 实验时最可靠的口径

### 10.1 推荐优先口径

1. `inactive` 和 baseline 对比。
2. `neutral` 和 baseline 对比。
3. 只改单一分支，不同时改 fast gate。
4. 统计新增样本是否只是从 Layer B 挪到 Layer C 被拒。

### 10.2 当前窗口验证：`neutral` 和 `inactive` 为什么都没有放量

上面是实验方法论。2026-03-27 还把 profitability 的 `zero_pass_mode` 做成了当前窗口可跑变体，产物见：

1. [data/reports/profitability_zero_pass_variants_current_window_20260327.json](../../data/reports/profitability_zero_pass_variants_current_window_20260327.json)

本次窗口 `20260323..20260326` 的结果非常明确：

1. baseline：`1`
2. `profitability_neutral`：`1`，`delta = 0`
3. `profitability_only` 也就是 `inactive`：`1`，`delta = 0`

这意味着：

1. 在当前窗口里，profitability 虽然是已评分样本中的头号负向子因子。
2. 但它压住的主要不是接近 `0.38` 的边缘票。
3. 单独把 `0 项达标` 从 `bearish` 改成 `neutral` 或 `inactive`，并不能直接释放新的 Layer B 通过样本。

这和前面的三指标拆解是相互印证的：

1. 当前窗口里 `positive_count = 0` 的样本主要是 `ROE + net_margin + operating_margin` 三项同时失败。
2. 这些样本通常不是“差一点就过线”的票，而是更深层的盈利质量失败样本。
3. 所以 profitability 在当前窗口更像“深层质量闸门”，而不是“边缘票释放旋钮”。

这条结论很重要，因为它会直接影响实验优先级：

1. 如果目标是释放 near-threshold 边缘票，当前窗口更应该优先修的是 neutral mean_reversion 语义。
2. 如果目标是研究深层质量过滤是否过严，profitability 仍值得研究，但那已经不是同一类问题。
3. 因此，不能因为 profitability 是“主负项”就默认它也是“当前窗口最有效的放量杠杆”。

### 10.3 不推荐的口径

1. 同时改 profitability、MR、fast gate。
2. 只看 `layer_b_count` 增加，不看 watchlist 和 buy_order。
3. 只看单日分数变化，不看窗口级稳定性。
4. 用“感觉更宽松”代替结构化指标。

---

## 11. 最常见的 5 个误判

1. 把 profitability 当成 fundamental 的全部。
2. 把 hard cliff 问题误解成单纯阈值过高。
3. 把 `neutral` 模式误解成一定比 `inactive` 更温和、更安全。
4. 把降低 confidence 误解成最小改动。
5. 看到当前窗口对 profitability 不敏感，就误以为这条子因子不重要。

实际上更准确的说法是：

1. profitability 不是每个窗口的第一主矛盾。
2. 但它始终是一个高杠杆语义位。

---

## 12. 最终判断

profitability 在当前系统里的真实身份，不是“一个普通负项”，而是：

1. fundamental 质量底线的最硬表达之一。
2. quality-first guard 的重要上游触发源。
3. Layer B 讨论里最容易被误调的语义杠杆。

所以当你要研究它时，正确问题不是：

1. “怎么把它调得更弱一点？”

而是：

1. “`0 项达标` 这条分支应该在系统里表达成负向、中性还是不参与？”
2. “它释放出来的样本，是正确纠偏，还是会在 Layer C 被马上打回？”
3. “当前窗口里它是主压制项，还是只是放大器？”

把这三个问题拆清楚，profitability 才能被稳妥地调，而不是反复成为误伤来源。
