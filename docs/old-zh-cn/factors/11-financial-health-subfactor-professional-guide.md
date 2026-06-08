# Financial Health 子因子专业讲解：杠杆、流动性与质量红旗联动

适用对象：已经理解 Layer B 和 fundamental 基本结构，现在要单独研究 financial_health 子因子的开发者、研究者、复盘人员。

这份文档解决的问题：

1. financial_health 在 Layer B 里究竟测什么，而不是泛泛地说“资产负债表健康”。
2. 为什么它的规则看起来很简单，却能在业务上形成明显压制感。
3. 它和 profitability、growth 一起是如何组成 quality-first guard 的。
4. 为什么它常常不是单独把股票打死，而是作为放大器把已有风险坐实。
5. 做 financial_health 实验时，应该优先验证什么，不该误改什么。

建议搭配阅读：

1. [Fundamental 因子专业讲解](./07-fundamental-factor-professional-guide.md)
2. [Profitability 子因子专业讲解](./09-profitability-subfactor-professional-guide.md)
3. [Growth 子因子专业讲解](./10-growth-subfactor-professional-guide.md)
4. [Layer B 源码导读](./06-layer-b-source-code-walkthrough.md)

---

## 1. 先说结论

如果只记住最核心的判断，可以先记这 7 条：

1. financial_health 不是收益性因子，而是风险约束因子，主要看杠杆和流动性是否踩线。
2. 它在 fundamental 五个子因子里默认权重为 `0.20`，权重低于 profitability 和 growth，但业务影响不小。
3. 当前实现非常简洁，只看 `debt_to_equity` 和 `current_ratio` 两个指标。
4. 它的分数从 `1.0` 倒扣，因此默认立场是“先假设健康，看到风险再减分”。
5. 它的方向阈值同样是 `> 0.6` 多、`< 0.4` 空，中间中性。
6. 单看 financial_health 往往只是轻度拖累，但它很容易和 profitability 共同触发质量红旗。
7. 如果你发现很多样本被 fundamental 压住，不要只看 profitability，也要看 financial_health 是否在持续提供负向确认。

---

## 2. 它在代码里到底是什么

financial_health 的 Layer B 入口在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L488) 的 `_score_financial_health()`。

默认权重在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L75) 中定义为：

1. `financial_health = 0.20`

它的评分实现来自 [src/agents/growth_agent.py](../../src/agents/growth_agent.py#L333) 的 `check_financial_health()`，处理过程是：

1. 读取 `debt_to_equity`
2. 读取 `current_ratio`
3. 从 `score = 1.0` 起步
4. 按风险区间逐步扣分
5. 最终把分数限制在 `[0, 1]`

可以把它理解成一条非常典型的“负面证据扣分器”。

---

## 3. 当前具体看哪两个指标

### 3.1 Debt to Equity

逻辑如下：

1. `debt_to_equity > 1.5`：减 `0.5`
2. `debt_to_equity > 0.8`：减 `0.2`

它测的是资本结构压力。杠杆高，不代表公司一定差，但意味着风险承受区间更窄。

### 3.2 Current Ratio

逻辑如下：

1. `current_ratio < 1.0`：减 `0.5`
2. `current_ratio < 1.5`：减 `0.2`

它测的是短期流动性安全垫。这个指标偏低时，说明公司短债压力更可能传导成经营约束。

---

## 4. 分数、方向和置信度怎么映射

`check_financial_health()` 先给出 `[0, 1]` 区间的 `score`，随后在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L488) 中映射为：

1. `score > 0.6`：`direction = 1`
2. `score < 0.4`：`direction = -1`
3. 其他：`direction = 0`

置信度公式同样是：

$$
confidence = |score - 0.5| \times 200
$$

几个典型情形：

1. 两项都好，`score = 1.0`，方向正，置信度 `100`
2. 一项轻度踩线，另一项健康，`score = 0.8`，方向正，置信度 `60`
3. 两项都轻度踩线，`score = 0.6`，方向中性，置信度 `20`
4. 一项重踩线、一项正常，`score = 0.5`，方向中性，置信度 `0`
5. 两项都重踩线，`score = 0.0`，方向负，置信度 `100`

这说明它不是只会出负分。很多时候它其实在提供“强正向确认”或“中性风险提示”。

---

## 5. 为什么它业务上压制感很强

虽然规则只有两项，但它容易让人感觉“压得狠”，主要有 4 个原因：

1. 它默认从满分起步，所以一旦踩线，负面信号很清晰。
2. 杠杆和流动性问题往往与利润质量弱同时出现，于是会和 profitability 共振。
3. 在 fundamental 聚合里，它代表的是质量下限，不需要很多项就能形成有效警告。
4. 在 Layer C 里，它不是孤立存在，而会进入质量分计算，影响持仓解释。

因此它常见的真实角色不是“主杀器”，而是“风险坐实器”。

---

## 6. 它和 quality-first guard 的关系

在 [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py) 中，`profitability`、`financial_health`、`growth` 会一起参与质量红旗判断。

这背后的业务语义是：

1. profitability 负责看赚不赚钱。
2. growth 负责看是否还在持续长大。
3. financial_health 负责看这种经营状态是不是建立在危险杠杆或脆弱流动性上。

如果 profitability 已经弱，而 financial_health 再给出负向确认，系统就更有理由把样本打入质量不可信区域。也就是说，它是 guard 体系里的重要辅助锚点。

---

## 7. 它和 Layer C 的关系

在 [src/execution/layer_c_aggregator.py](../../src/execution/layer_c_aggregator.py) 中，Layer C 质量分会吸收来自 Layer B fundamental 子因子的质量信息，其中 `financial_health` 是关键组成部分之一。

这意味着：

1. 它不只影响 `score_b`。
2. 它还会影响后续仓位解释和“为什么系统不愿意持有这只票”的叙事。

因此如果只看 Layer B 局部放松 financial_health，而不看 Layer C，容易出现前层放松、后层依旧冷的错觉。

---

## 8. 实验时最常见的误区

如果你怀疑 financial_health 太严格，不建议先做这些事：

1. 直接把 `debt_to_equity` 和 `current_ratio` 阈值整体大幅放宽。
2. 不区分轻度踩线和重度踩线的样本结构，就先改扣分值。
3. 只看通过率，不看被放进来的样本后续质量。

更合理的实验顺序是：

1. 先统计到底是杠杆问题更常见，还是流动性问题更常见。
2. 分开看“轻踩线”和“重踩线”样本在后续表现上的差异。
3. 再决定是调阈值、调扣分幅度，还是仅对特定行业做条件化处理。

否则很容易把一个本来用于识别风险底线的因子，改成一个没有约束力的装饰项。

---

## 9. 复盘 financial_health 时的最小读法

建议按下面顺序看：

1. 先看 `debt_to_equity` 和 `current_ratio` 原始值。
2. 再看最终 `score` 落在哪个区间。
3. 判断它是轻度拖累、中性提醒，还是明确负向。
4. 再联动 profitability 和 growth，看是否形成质量红旗组合。
5. 最后放回 Layer C，看它是不是进一步压低了质量分叙事。

---

## 10. 一句话总结

financial_health 是 fundamental 里的资产负债表守门员。它规则少，但语义明确，负责把高杠杆、低流动性的风险显式写进 Layer B 和 Layer C 的质量判断里。
