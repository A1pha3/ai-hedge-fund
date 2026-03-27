# Fundamental 因子专业讲解：从子因子、阈值到 Layer B 业务含义

适用对象：已经知道 Layer B 大框架，但想把 fundamental 因子单独看懂的开发者、研究者、复盘人员。

这份文档解决的问题：

1. fundamental 因子在 Layer B 里到底负责什么。
2. 它的 5 个子因子分别看什么、阈值是什么、如何变成方向与置信度。
3. 为什么它经常成为“把大多数股票压在 Layer B 下方”的头号因子。
4. 为什么 profitability 看起来只是一个子项，却会在业务上形成很强的压制感。
5. 当你要排障、复盘或做实验时，应该优先看哪些字段和代码位置。

建议搭配阅读：

1. [因子聚合语义入门](./01-aggregation-semantics-and-factor-traps.md)
2. [Layer B 策略完全讲解](./03-layer-b-complete-beginner-guide.md)
3. [Layer B 源码导读](./06-layer-b-source-code-walkthrough.md)
4. [层 B 因子参数根因分析与实验矩阵](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)
5. [Fundamental 因子一页速查卡](./08-fundamental-factor-one-page-cheatsheet.md)
6. [Profitability 子因子专业讲解](./09-profitability-subfactor-professional-guide.md)
7. [Growth 子因子专业讲解](./10-growth-subfactor-professional-guide.md)
8. [Financial Health 子因子专业讲解](./11-financial-health-subfactor-professional-guide.md)
9. [Growth Valuation 子因子专业讲解](./12-growth-valuation-subfactor-professional-guide.md)
10. [Industry PE 子因子专业讲解](./13-industry-pe-subfactor-professional-guide.md)
11. [Fundamental 专题首页](./14-fundamental-topic-reading-path.md)
12. [Fundamental 五子因子联动复盘手册](./15-fundamental-subfactor-joint-review-manual.md)

---

## 1. 先说结论

如果只记住最重要的判断，可以先记这 6 条：

1. fundamental 不是“估值因子”的同义词，而是一条由盈利、增长、财务健康和估值相对关系共同组成的复合策略信号。
2. 它在 Layer B 默认权重里占 `0.30`，和 trend 并列第一权重，是整个系统的中长期质量锚。
3. 它之所以经常成为主压制项，不是因为某一个子因子特别大，而是因为它本身承担了“质量底线 + 成长验证 + 相对估值约束”三层职责。
4. profitability 是 fundamental 里最敏感的硬门槛之一，因为 `0 项达标` 会直接把子因子打成强负，并可能联动 quality-first guard。
5. current window 里“多数股票广义上过不了 Layer B”更多是 fundamental 和 trend 本身不够正，而不是 neutral mean_reversion 单独造成的。
6. fundamental 的调参不能只看阈值高低，还要同时看子因子聚合语义、重评分覆盖率、市场状态调权和 Layer C 质量分衔接。

---

## 2. 它在系统里的准确位置

fundamental 属于 Layer B 的四条策略之一，和下面三条并列：

1. `trend`
2. `mean_reversion`
3. `fundamental`
4. `event_sentiment`

默认策略权重定义在 [src/screening/models.py](../../src/screening/models.py#L49) 和 [src/screening/models.py](../../src/screening/models.py#L61)：

1. `trend = 0.30`
2. `mean_reversion = 0.20`
3. `fundamental = 0.30`
4. `event_sentiment = 0.20`

这说明它的定位不是补充说明项，而是主策略腿之一。

更准确地说，fundamental 在 Layer B 中负责三件事：

1. 给候选池提供中长期质量锚，避免系统只被短期价格形态驱动。
2. 在趋势成立时区分“有质量支撑的上涨”和“纯技术性弹跳”。
3. 在执行与持有层面提供更长持仓和更强冷却释放的依据。

对应代码上，fundamental 不只影响 `score_b`，还会进一步影响：

1. Layer C 的质量分提取，见 [src/execution/layer_c_aggregator.py](../../src/execution/layer_c_aggregator.py#L162)
2. fundamental driven 持仓语义，见 [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py#L211)
3. 长持仓策略分类，见 [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py#L11)

---

## 3. 先分清两个“基本面”概念

仓库里至少有两个容易混淆的“基本面”层：

### 3.1 Layer B 的 fundamental 策略

这是本文讲的对象。

特点是：

1. 规则化。
2. 批量可执行。
3. 输出标准三元组：`direction / confidence / completeness`。
4. 主要实现位于 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L543)

### 3.2 Layer C 的 fundamentals analyst agent

这是更偏解释型、研究型的分析 agent。

特点是：

1. 面向多智能体分析链路。
2. 输出的是更接近研究结论的信号与 reasoning。
3. 实现在 [src/agents/fundamentals.py](../../src/agents/fundamentals.py#L12)

两者关系不是替代，而是上下游：

1. Layer B fundamental 先做高吞吐快筛。
2. Layer C fundamentals analyst 再做更贵、更深的解释与确认。

因此，当你说“fundamental 因子太冷”时，通常指的是 Layer B 的规则因子，不是 Layer C 的 fundamentals analyst。

---

## 4. 数据从哪里来，覆盖范围是什么

fundamental 策略入口在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L543) 的 `score_fundamental_strategy()`。

它会调用：

1. `get_financial_metrics(ticker=ticker, end_date=trade_date, period="ttm", limit=8)`

这意味着几个很重要的边界：

1. 口径是 `ttm`，即滚动 12 个月，不是单季度快照。
2. 最多取最近 8 期，用于增长趋势类分析。
3. 如果拿不到财务数据，整条 fundamental 会直接输出空信号，`completeness = 0`。

业务含义是：

1. 这条策略天然偏中期，不是日内或超短周期因子。
2. 它更关注财务结构的稳定性，而不是新闻级别的短期跳变。
3. 数据缺失会让它彻底不参与，而不是给一个弱分。

---

## 5. 五个子因子分别在看什么

fundamental 的子因子权重定义在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L75)：

1. `profitability = 0.25`
2. `growth = 0.25`
3. `financial_health = 0.20`
4. `growth_valuation = 0.15`
5. `industry_pe = 0.15`

它不是“单个会计指标决定一切”，而是一个五段式复合判断。

### 5.1 profitability：盈利能力底线

实现位置： [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L415)

当前看三项：

1. `ROE >= 0.15`
2. `net_margin >= 0.20`
3. `operating_margin >= 0.15`

判定逻辑：

1. `2` 项及以上达标：`direction = +1`
2. `1` 项达标：`direction = 0`
3. `0` 项达标：默认 `direction = -1`

这里还有一个实验开关：

1. `LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE = bearish|neutral|inactive`

三种模式的业务差别：

1. `bearish`：当前默认语义，`0` 项达标直接强负。
2. `neutral`：保留数据但不把 `0` 项达标视为直接看空。
3. `inactive`：把这条子因子从聚合里移出，相当于不参与。

为什么它重要：

1. 它不是连续惩罚，而是带 cliff 性质。
2. 一旦为 `0` 项达标，常常会把整条 fundamental 的方向拖向负面。
3. 如果再叠加 financial_health 也差，可能触发 quality-first guard。

### 5.2 growth：增长是否可信

实现位置： [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L468)

它调用 `analyze_growth_trends(metrics_list)`，然后按输出分数离散化：

1. `score > 0.6`：正向
2. `score < 0.4`：负向
3. 其他：中性

confidence 计算方式是：

$$
|score - 0.5| \times 200
$$

这代表：

1. 越远离中性区，growth 的表达越明确。
2. 它强调趋势清晰度，而不是单点高增速。

### 5.3 financial_health：资产负债表和偿债健康

实现位置： [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L481)

它调用 `check_financial_health(metrics)`，也是按 `0.6 / 0.4` 分段：

1. 健康明显：正向
2. 脆弱明显：负向
3. 介于中间：中性

业务上它的作用非常关键，因为它更像“质量否决腿”：

1. profit 好，但财务健康差，系统不会轻易给高 fundamental。
2. 这正是为了防止只看利润表，不看资产负债表质量。

### 5.4 growth_valuation：成长与估值是否匹配

实现位置： [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L493)

它调用 `analyze_valuation(metrics)`，判定逻辑略特殊：

1. `score > 0.6`：正向
2. `score == 0`：负向
3. 其余：中性

这里的含义不是“估值越低越好”这么简单，而是：

1. 成长能否支撑当前估值。
2. 估值是否已经明显偏离可接受区间。

它只占 `0.15`，说明项目并不想让静态估值一票否决所有成长票，但也不会完全无视估值约束。

### 5.5 industry_pe：行业相对估值

实现位置： [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L517)

它不是看绝对 PE，而是看相对行业中位数的偏离：

1. `premium <= 0.8`：正向
2. `premium >= 1.2`：负向
3. 中间区间：中性

这里的 `premium = current_pe / industry_median_pe`。

这条子因子很专业，因为它避免了跨行业直接比较 PE 的低质量做法。它真正回答的问题是：

1. 这只股票相对自己行业，是便宜、合理还是偏贵。

---

## 6. 五个子因子怎么聚合成一条 fundamental 信号

所有子因子最终进入 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L132) 的 `aggregate_sub_factors()`。

这个聚合器要分四步理解。

### 6.1 第一步：只有 completeness 大于 0 的子因子才算可用

这意味着：

1. 数据缺失不是弱权重，而是直接不参与。
2. 一条策略的可用结构会随着数据完备度发生变化。

### 6.2 第二步：先做可用子因子的权重归一化

不是所有子因子都硬按原始权重加和，而是先在“当前可用集合”内部重新归一化。

这意味着：

1. 缺失某条子因子后，剩余子因子的相对影响会变大。
2. 所以 completeness 既影响信息量，也影响权重结构。

### 6.3 第三步：用有方向的加权和决定最终 direction

简化理解是：

$$
score = \sum weight_i \times direction_i \times confidence_i
$$

然后：

1. `score > 0`：整条 fundamental 为正
2. `score < 0`：整条 fundamental 为负
3. `score = 0`：整条 fundamental 为中性

### 6.4 第四步：confidence 还要再乘一次 consistency

这一步是很多误判的来源。

当前聚合器会统计：

1. 有多少子因子和最终方向一致。
2. 用这个一致性去乘加权平均 confidence。

因此 fundamental 不是“几个分数相加”，而是“方向共识强不强”。

业务结论是：

1. 如果五个子因子互相打架，即使平均 confidence 不低，最终 fundamental 也会变钝。
2. 这也是为什么“只把一个负项 confidence 调小一点”常常不能解决问题。

---

## 7. 为什么它经常成为主压制项

在当前窗口的聚合诊断里，`fundamental.direction <= 0` 的被挡样本最多。这件事并不奇怪，原因通常来自下面四层。

### 7.1 它天然是质量因子，不是追涨因子

趋势因子问的是：

1. 价格是否在走强。

fundamental 问的是：

1. 这家公司的盈利、增长、资产负债表和相对估值有没有站得住。

所以在大量普通候选里，趋势偶尔能亮，但 fundamental 更容易维持中性或负向。

### 7.2 它承担了多重约束，任何一腿差都可能拖累整体

如果一只股票出现下面任一情况，fundamental 往往不会很好看：

1. 利润率没有达到阈值。
2. 增长趋势不清晰。
3. 财务健康偏弱。
4. 估值相对行业不便宜。

也就是说，fundamental 的正向门槛天然比“单看一个好指标”更难满足。

### 7.3 profitability 的 hard cliff 会放大左尾

最典型的情况是：

1. `positive_count == 0`
2. 默认 `zero_pass_mode = bearish`

这时 profitability 会被直接打成强负。

如果再叠加：

1. financial_health 也偏弱
2. growth 也不明显

就很容易触发 [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py#L78) 的 quality-first red flag。

这不是“fundamental 少扣一点分就好”的问题，而是结构性地把一部分样本推进了 forced avoid 通道。

### 7.4 它还是一条 heavy leg，不是所有候选都能拿到

fundamental 本身虽然重要，但不是所有 200 个候选都能公平获得。

批量评分流程里：

1. 先做轻量 technical provisional score。
2. 只有 provisional score 达到门槛的候选，才进入 fundamental 重评分。
3. fundamental 还存在 `FUNDAMENTAL_SCORE_MAX_CANDIDATES = 100` 的容量上限，见 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L49) 和 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L763)

所以 fundamental 的业务问题有两类，不能混在一起：

1. 因子本身对很多票给了非正判断。
2. 很多票甚至没有资格拿到完整 fundamental 评分。

### 7.5 当前窗口实证：真正最常把股票打失败的是哪一腿

上面 7.1 到 7.4 讲的是机制。把它落到当前窗口 `20260323..20260326` 的 baseline 实证后，结论可以再说得更具体。

先看总盘子：

1. 当前窗口共看到 `800` 个 Layer B 样本，其中 `799` 个被挡下，真正过线的只有 `1` 个。
2. 在这 `799` 个 blocked 样本里，`fundamental.direction <= 0` 的有 `692` 个，占 `86.61%`。
3. 但这 `692` 个里，`fundamental.direction = 0` 的有 `512` 个，`fundamental.direction = -1` 的只有 `180` 个。

这意味着第一个必须先说清的事实是：

1. “大多数股票在 fundamental 上不合格”并不等于“大多数股票都被某个子因子打成了强负”。
2. 更大的一块其实是很多股票没有进入完整 heavy fundamental 评分，或者进入后只形成了空/中性 fundamental，而不是形成明确负向 fundamental。

所以如果问“哪个 fundamental 子因子导致大多数股票都不合格”，必须拆成两层回答。

#### 第一层：广义上为什么大多数股票过不了 fundamental

如果把“过不了”理解成 `fundamental <= 0`，那么最先看到的不是某个子因子，而是供给侧漏斗：

1. `profitability`、`growth`、`financial_health`、`growth_valuation` 这四条子因子，在 `799` 个 blocked 样本里各自都有 `512` 个 `completeness = 0`。
2. `industry_pe` 更极端，在当前窗口 `799/799` 都是 `completeness = 0`。

这对应 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L746) 到 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L767) 的批量评分漏斗：

1. 先做轻量 provisional score。
2. 只有过了 `HEAVY_SCORE_MIN_PROVISIONAL_SCORE = 0.05` 的候选，才进入 heavy fundamental 评分。
3. 进入后还要受 `FUNDAMENTAL_SCORE_MAX_CANDIDATES = 100` 容量上限约束。

因此，广义上的第一主因不是某个 fundamental 子因子，而是：

1. 很多股票根本没有拿到完整 fundamental 评分。
2. 这是供给侧问题，不是子因子语义问题。

#### 第二层：一旦进入了 fundamental 评分，真正最常把股票打失败的是哪一腿

如果只看真正拿到评分的样本，那么答案就很清楚了：`profitability` 是头号主拖累项。

在当前窗口的 blocked 样本里：

1. `growth_valuation` 非正最多，共 `261` 个。
2. `profitability` 非正 `233` 个。
3. `growth` 非正 `184` 个。
4. `financial_health` 非正 `82` 个。

但“非正最多”不等于“真正最常把整条 fundamental 打失败”。如果看“最大负贡献因子”统计：

1. `profitability` 是最大负贡献项的有 `164` 个。
2. `growth` 只有 `43` 个。
3. `growth_valuation` 只有 `15` 个。
4. `financial_health` 也是 `15` 个。

如果进一步只看 `fundamental.direction <= 0` 的 blocked 样本，则更集中：

1. `profitability` 是最大负贡献项的有 `149` 个。
2. `growth` 有 `23` 个。
3. `financial_health` 有 `8` 个。

这说明：

1. `growth_valuation` 更像“经常不给帮助”。
2. `profitability` 才是“最经常把股票明确打失败”的那条腿。

#### 为什么 profitability 会比 growth_valuation 更像主杀器

原因在于两者语义不同：

1. `growth_valuation` 在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L486) 到 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L497) 里，大量情况只是中性，不会自动形成强负。
2. `profitability` 在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L410) 到 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L454) 里，只要 `positive_count = 0`，默认就直接进入 `direction = -1`。

当前窗口里，拿到 profitability 评分的 blocked 样本中：

1. `positive_count = 0` 的有 `164` 个。
2. `positive_count = 1` 的有 `69` 个。
3. `positive_count = 2` 的有 `25` 个。
4. `positive_count = 3` 的有 `29` 个。

而在 `fundamental.direction <= 0` 的这批样本里：

1. `positive_count = 0` 的有 `149` 个。
2. `positive_count = 1` 的有 `31` 个。

也就是说，当前窗口里真正最典型的 fundamental 失败路径不是“估值略贵”，而是：

1. profitability 三项里一项都没过。
2. 然后被 hard cliff 直接打成负向。
3. 若再叠加 financial_health 偏弱，就可能进一步触发 quality-first guard。

#### 所以这道题的准确答案应该怎么说

一句话版：

1. 如果把“导致大多数股票不合格”理解成整个 fundamental 漏斗，那第一主因是很多股票没拿到完整评分。
2. 如果只看已经进入 fundamental 评分的样本，那真正最常把股票打失败的子因子是 `profitability`。
3. `growth` 是第二拖累项。
4. `growth_valuation` 很常非正，但更像普遍不给推力，而不是最常执行一票否决。
5. `financial_health` 更像放大器，尤其会和 profitability 负向联动。
6. `industry_pe` 在当前窗口没有形成有效约束，因为它基本没有参与评分。

---

## 8. 它如何进入最终 score_b

fundamental 不会单独决定 Layer B，而是要和其他策略一起进入 [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py#L184) 的归一化与融合。

简化理解：

$$
score_b = \sum normalized\_weight_i \times direction_i \times confidence_i \times completeness_i
$$

其中对 fundamental 来说，有三个关键现实：

1. 它默认基础权重高，意味着一旦为正，提振效果也明显。
2. 它 completeness 为 0 时会直接退出归一化。
3. 市场状态可能进一步上调或下调它的权重。

市场状态调权位置在 [src/screening/market_state.py](../../src/screening/market_state.py#L76)。

几个典型场景：

1. 危机场景会提高 fundamental 权重，降低 trend 权重。
2. 区间震荡场景会轻微降低 fundamental。
3. 北向连续流入、涨跌停结构失衡等情形，也可能额外抬升 fundamental 权重。

这意味着 fundamental 不是静态 `0.30`，而是有状态依赖的质量锚。

---

## 9. 为什么它对 Layer C 和执行层也有后效应

fundamental 的影响不会止步于 Layer B。

### 9.1 Layer C 会从 fundamental 子因子再提一次 quality score

在 [src/execution/layer_c_aggregator.py](../../src/execution/layer_c_aggregator.py#L162)，系统会从 fundamental 中抽取：

1. `profitability`
2. `financial_health`
3. `growth`

重新推导 quality score。

这说明：

1. fundamental 不只是 Layer B 的输入。
2. 它还是 Layer C 中质量理解的上游证据。

### 9.2 它还影响持仓语义

在 [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py#L11)，fundamental 被列入 `LONG_HOLD_STRATEGIES`。

在业务上这代表：

1. 由 fundamental 驱动的票允许更长持有周期。
2. 当 fundamental 持续为正时，也更可能支持冷却提前释放。

所以 fundamental 并不只是“选不选”，还影响“拿多久”。

---

## 10. 复盘时应该怎么看它

如果你在 selection snapshot 或融合结果里看到某只票的 fundamental，建议按下面顺序读。

### 10.1 先看策略级三元组

先问三个问题：

1. `direction` 是正、负还是中性。
2. `confidence` 是低置信中性，还是高置信负向。
3. `completeness` 是满的，还是因为数据缺失变成半盲。

### 10.2 再拆五个子因子

再问：

1. 是 profitability 在拉低，还是 growth 不成立。
2. 是 financial_health 真有红旗，还是估值腿在拖分。
3. 是单腿明显差，还是五腿普遍不够正。

### 10.3 最后再放回融合语境

最后再问：

1. 当前市场状态有没有抬高 fundamental 权重。
2. trend 是否和 fundamental 同向。
3. mean_reversion 是否在边缘样本上稀释了 fundamental 的正面贡献。

只有这样读，才能区分：

1. fundamental 自身冷。
2. fundamental 其实不差，但在融合层被别的腿抵消。
3. fundamental 根本没拿到完整评分。

---

## 11. 调参时最容易犯的错误

### 11.1 只盯 profitability 阈值，不看聚合语义

错误直觉是：

1. 把 `confidence` 调低一点，就会更宽松。

但在当前聚合器里，confidence 还会影响方向一致性后的最终输出，所以这并不是线性旋钮。

### 11.2 把 fundamental 低通过率误读成“这条因子没用”

fundamental 低通过率通常说明：

1. 当前候选池质量并不高。
2. 这条策略真的在做过滤，而不是摆设。

问题不在于它“太会挡”，而在于要判断它挡掉的是噪音，还是错杀了本该保留的边缘票。

### 11.3 把所有问题都归因到 profitability

profitability 很显眼，但 fundamental 是五条腿共同决定的。

很多票 fundamental 为负，真正原因可能是：

1. growth 不成立。
2. financial_health 过弱。
3. 估值相对行业过贵。

### 11.4 忽视覆盖率问题

如果 fundamental 只对一半候选开放，那么“fundamental 太冷”有时也可能包含：

1. 评分资格阶段本身就把很多票挡在门外。

所以做实验时，必须把“语义问题”和“供给问题”拆开测。

---

## 12. 建议的排障顺序

如果你要判断一只股票为什么被 fundamental 压下去，建议按下面顺序排。

1. 先确认这只票是否真的拿到了 fundamental 评分，而不是 `completeness = 0`。
2. 再看 profitability 的 `positive_count` 和 `zero_pass_mode`。
3. 再看 growth、financial_health、growth_valuation、industry_pe 分别谁在拖累。
4. 再看 fundamental 最终方向是否因为子因子打架而被 consistency 压低。
5. 最后才看它在 Layer B 融合中是否被 neutral mean_reversion 或市场状态调权进一步改变边际结果。

如果你要做参数实验，建议优先分三类：

1. 子因子语义实验：例如 profitability 的 `zero_pass_mode`。
2. 供给侧实验：例如放宽 fundamental 重评分覆盖率。
3. 融合层实验：例如修正 neutral mean_reversion active 资格。

---

## 13. 最终判断

fundamental 因子在这个项目里，本质上不是“给价值投资者看的装饰性因子”，而是 Layer B 最重要的质量锚之一。

它之所以经常显得冷，是因为它承担了系统里最不讨好的工作：

1. 拦住盈利差但价格形态好看的票。
2. 拦住增长叙事不扎实的票。
3. 拦住财务结构脆弱的票。
4. 拦住相对行业明显偏贵的票。

因此，对它的正确研究方式不是先问“怎么让它少挡一点”，而是先问：

1. 它现在挡掉的主要是哪一类票。
2. 哪些是正确过滤，哪些是边缘误伤。
3. 应该修子因子语义、开放评分供给，还是修融合层对边缘样本的稀释。

只有把这三层拆开，fundamental 的调优才会稳，而不是反复在阈值上来回摆动。
