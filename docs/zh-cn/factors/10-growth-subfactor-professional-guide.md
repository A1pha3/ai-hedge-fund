# Growth 子因子专业讲解：趋势阈值、数据覆盖与伪成长陷阱

适用对象：已经理解 Layer B 和 fundamental 基本结构，现在要单独研究 growth 子因子的开发者、研究者、复盘人员。

这份文档解决的问题：

1. growth 在 Layer B 里到底测什么，而不是笼统地说“看成长性”。
2. 为什么它和 growth_valuation 看起来都带 growth，但职责并不一样。
3. 为什么很多样本不是被 growth 明确看空，而是根本没有拿到有效 growth 评分。
4. 它的 `0.6 / 0.4` 阈值、置信度公式、数据覆盖要求分别意味着什么。
5. 做 growth 实验时，哪些改动是在修语义，哪些改动只是把噪声放大。

建议搭配阅读：

1. [Fundamental 因子专业讲解](./07-fundamental-factor-professional-guide.md)
2. [Fundamental 因子一页速查卡](./08-fundamental-factor-one-page-cheatsheet.md)
3. [Profitability 子因子专业讲解](./09-profitability-subfactor-professional-guide.md)
4. [层 B 因子参数根因分析与实验矩阵](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)

---

## 1. 先说结论

如果只记住最核心的判断，可以先记这 7 条：

1. growth 不是估值，也不是事件驱动，它只回答一个问题：最近几期经营结果能不能支持“这家公司还在持续长大”。
2. 它在 fundamental 五个子因子里默认权重为 `0.25`，和 profitability 并列第一权重，但它的语义比 profitability 更连续。
3. growth 并不直接看股价涨跌，而是看财务指标的增长质量，所以它经常和 trend 分歧。
4. 当前实现要求至少 `4` 期财务指标，否则直接不给有效评分，这比阈值本身更常见地影响通过率。
5. growth 的方向阈值是 `score > 0.6` 判多，`score < 0.4` 判空，中间视为中性。
6. growth 的置信度不是单独配置项，而是由 `abs(score - 0.5) * 200` 直接推出，意味着它天然是“离中性越远越自信”。
7. growth 常见问题不是“阈值太高”，而是样本本身增长趋势平、波动大、或历史序列不完整。

---

## 2. 它在代码里到底是什么

growth 的 Layer B 入口在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L472) 的 `_score_growth()`。

它属于 fundamental 五个子因子之一，默认权重在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L75) 定义为：

1. `growth = 0.25`

它的执行流程很直接：

1. 先检查 `metrics_list` 长度是否至少为 `4`。
2. 不足 `4` 期，直接返回 `completeness = 0.0` 的空信号。
3. 数据足够时，调用 [src/agents/growth_agent.py](../../src/agents/growth_agent.py#L191) 的 `analyze_growth_trends()`。
4. 根据 `score` 映射成 `direction` 和 `confidence`。

这意味着 growth 首先是一个“时序覆盖敏感”的子因子，其次才是一个阈值策略。

---

## 3. 它到底看哪些增长信息

当前 `analyze_growth_trends()` 主要看三类数据：

1. `revenue_growth`
2. `earnings_growth`
3. `free_cash_flow_growth`

同时还会用 `_calculate_trend()` 看这些序列的方向，而不是只看最近一期的绝对值。

可以把它理解成三层判断：

1. 最新一期增长够不够强。
2. 最近几期趋势有没有继续改善。
3. 增长是不是落到现金流和利润上，而不只是营收数字好看。

这也是为什么 growth 比“单看 revenue yoy”更稳，但也更容易给出中性分数。

---

## 4. 当前分数是怎么累出来的

在 [src/agents/growth_agent.py](../../src/agents/growth_agent.py#L191) 里，growth 的主体规则可以概括为：

### 4.1 Revenue Growth

1. `revenue_growth > 0.20`：加 `0.4`
2. `revenue_growth > 0.10`：加 `0.2`
3. `revenue_growth < -0.10`：减 `0.2`
4. 收入趋势为正：再加 `0.1`

### 4.2 Earnings Growth

1. `earnings_growth > 0.20`：加 `0.25`
2. `earnings_growth > 0.10`：加 `0.1`
3. `earnings_growth < -0.50`：减 `0.2`
4. `earnings_growth < -0.10`：减 `0.1`
5. 盈利趋势为正：再加 `0.05`

### 4.3 Free Cash Flow Growth

1. `free_cash_flow_growth > 0.15`：加 `0.1`

最后分数会被限制在 `[0, 1]` 区间。

这说明 growth 的结构不是平均分，而是偏“正向证据累积”。收入和利润是主轴，自由现金流更像确认项。

---

## 5. 分数怎么映射成方向与置信度

在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L472) 中，映射规则是：

1. `score > 0.6`：`direction = 1`
2. `score < 0.4`：`direction = -1`
3. 其他：`direction = 0`

置信度公式为：

$$
confidence = |score - 0.5| \times 200
$$

几个直观例子：

1. `score = 0.80`，则 `confidence = 60`
2. `score = 0.65`，则 `confidence = 30`
3. `score = 0.50`，则 `confidence = 0`
4. `score = 0.20`，则 `confidence = 60`

这个设计有两个含义：

1. growth 是一个明显的“中心中性”因子，靠近 `0.5` 时系统承认自己没有足够把握。
2. 只要分数远离中性，无论正负，置信度都会抬起来。

---

## 6. 为什么它常常表现为“不给帮助”而不是“明确打压”

growth 在复盘里常见的体感是“没拉分”，而不是“强烈看空”，原因通常有 4 类：

1. 数据不足 `4` 期，直接没有有效评分。
2. 收入有增长，但利润和现金流没有同步确认，得分停在中性附近。
3. 最近一期很好，但多期趋势不稳定，趋势奖励拿不到。
4. 财务增长指标正负交错，最后落在 `0.4` 到 `0.6` 的中性带。

这和 profitability 很不一样。profitability 更像硬底线，growth 更像连续验证器。

---

## 7. 它和 growth_valuation 到底有什么区别

这两个名字容易混，但职责完全不同：

1. growth 问的是“你有没有真的在长”。
2. growth_valuation 问的是“即使你在长，这个估值是不是还配得上这种增长”。

更实际一点说：

1. growth 偏经营现实。
2. growth_valuation 偏经营与定价的匹配关系。

所以常见的组合包括：

1. growth 正、growth_valuation 中性：公司在长，但估值不算特别便宜。
2. growth 中性、growth_valuation 中性：增长证据不足，也谈不上估值匹配优势。
3. growth 正、growth_valuation 负或弱：公司确实在长，但价格已经提前反映太多。

调试时不要把它们当作同一条腿拆两遍。

---

## 8. 它和 trend、financial_health 的常见分歧

growth 与其他因子的分歧，是 Layer B 里很常见且合理的现象：

1. `trend` 正、`growth` 中性或负：价格先走强，但财务增长还没确认。
2. `growth` 正、`trend` 弱：基本面改善已经出现，但市场尚未形成价格趋势。
3. `growth` 正、`financial_health` 弱：公司还在长，但靠高杠杆或流动性压力支撑，这种成长质量不够稳。

这也是 fundamental 需要多个子因子的原因。单独一个 growth 无法回答“这种成长是否可持续”。

---

## 9. 实验时真正该看什么

如果你怀疑 growth 太严格，建议先按这个顺序排障：

1. 看样本是否经常 `len(metrics_list) < 4`。
2. 看 `revenue_growth`、`earnings_growth`、`free_cash_flow_growth` 到底是哪一项持续不给分。
3. 看趋势奖励是否经常拿不到，说明问题可能是序列波动而不是阈值。
4. 再考虑是否需要调整区间阈值，例如 `0.6 / 0.4`。

不建议一上来就做的事情：

1. 直接把 bullish 门槛大幅下调。
2. 只调 confidence 而不改 score 语义。
3. 不区分“没评分”和“被评成中性/负向”。

这三种做法都容易让回测看起来更热闹，但会损坏 growth 的判别含义。

---

## 10. 复盘 growth 时的最小读法

建议按下面顺序看：

1. 先看 growth 子因子是否 active。
2. 如果不 active，先定位是不是历史财务期数不够。
3. 如果 active，再看 `score` 落在 bullish、neutral、bearish 哪一段。
4. 再拆 revenue、earnings、free cash flow 三条证据链。
5. 最后放回 fundamental 聚合，看它是主拖累项，还是只是没有提供帮助。

---

## 11. 一句话总结

growth 不是“增长想象力”因子，而是一个带历史覆盖要求的经营增长验证器。它最重要的不是把所有成长股都亮绿灯，而是把那些没有持续经营增长证据的样本挡在中性甚至负向区间里。
