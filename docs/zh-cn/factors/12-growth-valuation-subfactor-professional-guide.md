# Growth Valuation 子因子专业讲解：成长定价匹配、零分判空与常见伪宽松

适用对象：已经理解 Layer B 和 fundamental 基本结构，现在要单独研究 growth_valuation 子因子的开发者、研究者、复盘人员。

这份文档解决的问题：

1. growth_valuation 为什么不等于传统意义上的低估值因子。
2. 为什么它常常不是主杀器，却经常不给 fundamental 提供推力。
3. 它的评分为什么只有零分才直接判空，而不是像 growth 那样用双阈值对称处理。
4. PEG 和市销率在当前实现里分别承担什么角色。
5. 做 growth_valuation 实验时，哪些改动是在修语义，哪些只是人为放松约束。

建议搭配阅读：

1. [Fundamental 因子专业讲解](./07-fundamental-factor-professional-guide.md)
2. [Growth 子因子专业讲解](./10-growth-subfactor-professional-guide.md)
3. [Financial Health 子因子专业讲解](./11-financial-health-subfactor-professional-guide.md)
4. [层 B 因子参数根因分析与实验矩阵](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)

---

## 1. 先说结论

如果只记住最核心的判断，可以先记这 7 条：

1. growth_valuation 不是在问股票便不便宜，而是在问成长能不能支撑当前定价。
2. 它在 fundamental 五个子因子里默认权重为 0.15，属于辅助约束腿，不是质量主轴。
3. 它的实现基于两个指标：PEG 和市销率。
4. 它只有在 score 等于 0 时才直接判空，这决定了它更常见的行为是不给帮助，而不是明确打压。
5. 只要两个估值证据里有一个还过得去，它就很容易停留在中性区，而不是落入负向。
6. 当前窗口里它虽然经常非正，但真正成为最大负贡献项的次数远少于 profitability。
7. 如果你想通过改 growth_valuation 来显著抬高通过率，先要确认自己是在修估值语义，而不是在删除增长票的定价约束。

---

## 2. 它在代码里到底是什么

growth_valuation 的 Layer B 入口在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L501) 的 `_score_growth_valuation()`。

默认权重在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L75) 中定义为：

1. growth_valuation = 0.15

它调用 [src/agents/growth_agent.py](../../src/agents/growth_agent.py#L237) 的 analyze_valuation()，先得到一个 0 到 1 的 score，再在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L501) 做方向映射。

与其他子因子相比，它最特别的地方是：

1. 正向阈值仍然是 score 大于 0.6。
2. 负向并不是 score 小于 0.4，而是只有 score 等于 0 才直接判空。
3. 只要拿到一点估值支持，它大概率就是中性而不是负向。

---

## 3. 当前它具体看哪两个指标

### 3.1 PEG Ratio

在 [src/agents/growth_agent.py](../../src/agents/growth_agent.py#L237) 中，PEG 的评分规则是：

1. PEG 小于 1.0：加 0.5
2. PEG 小于 2.0：加 0.25

如果原始 PEG 缺失，代码会尝试用 PE 和 EPS 增长近似回推：

1. 需要存在 PE
2. 需要存在 EPS 增长
3. EPS 增长必须大于 0

这说明当前实现不接受“负增长也硬算 PEG”的做法，因为那会让指标失真。

### 3.2 Price to Sales Ratio

市销率规则是：

1. 市销率小于 2.0：加 0.5
2. 市销率小于 5.0：加 0.25

它在这里的角色不是替代 PEG，而是补充一条对收入定价压力的粗粒度判断。

---

## 4. 分数怎么形成

growth_valuation 的分数不是平均值，而是两条正向证据叠加：

1. PEG 给 0、0.25 或 0.5
2. 市销率给 0、0.25 或 0.5
3. 总分上限为 1.0

所以典型区间可以这样理解：

1. score = 1.0：PEG 和市销率都明显友好
2. score = 0.5：只有一条证据明显友好，或两条都只是轻度友好
3. score = 0.25：只有一条证据轻度友好
4. score = 0：PEG 和市销率都没有提供任何支撑

这类结构决定了它天然偏向中性，因为只要不是完全失去支撑，就不一定进入负向。

---

## 5. 方向与置信度为什么看起来不对称

在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L501) 中，映射规则是：

1. score 大于 0.6：direction = 1
2. score 等于 0：direction = -1
3. 其他：direction = 0

置信度规则则是：

1. score 大于 0 时，confidence = |score - 0.5| × 200
2. score 等于 0 时，confidence 固定为 65

这背后反映的是一种业务判断：

1. 估值不够便宜，不等于明确危险，因此多数情形保持中性。
2. 只有完全没有成长定价支撑时，系统才愿意给出显式负向。

这也是它和 profitability 最大的差异之一。profitability 是 hard cliff，growth_valuation 更像缺乏助推器。

---

## 6. 为什么它常常非正，却不常是主杀器

当前窗口里的一个关键结论已经写在 [docs/zh-cn/factors/07-fundamental-factor-professional-guide.md](./07-fundamental-factor-professional-guide.md) 中：

1. growth_valuation 非正样本很多。
2. 但它成为最大负贡献项的次数不高。

这并不矛盾，原因是：

1. 它的很多非正其实是中性，不提供推力但也不形成强压制。
2. 真正把 fundamental 明确打向负向的，更多还是 profitability 这类硬门槛项。
3. 当 growth_valuation 负向时，往往意味着定价已经脱离成长支撑，这时它更像确认风险，而不是单独制造风险。

所以复盘时不要把它的出现频率和它的杀伤力混为一谈。

---

## 7. 它和 growth 的边界到底在哪里

一句话区分：

1. growth 看公司是否真的在长。
2. growth_valuation 看市场是不是已经给这段成长定了太贵的价格。

典型组合包括：

1. growth 正、growth_valuation 中性：公司增长可信，但定价优势一般。
2. growth 正、growth_valuation 负：公司确实在长，但估值已经把成长故事讲得太满。
3. growth 中性、growth_valuation 中性：增长证据不足，同时也没有估值红利。

它们分属两个不同问题，不应合并理解为一条腿。

---

## 8. 实验时最容易踩的坑

如果你怀疑 growth_valuation 太保守，不建议先做这些事：

1. 把 score 等于 0 判空直接改成 score 小于 0.4 判空。
2. 直接放宽所有 PEG 和市销率阈值。
3. 只看通过率提升，不看被放进来的样本是否已经明显偏贵。

更合理的实验顺序是：

1. 先看负向样本里到底是哪条证据经常缺失，是 PEG 还是市销率。
2. 区分真正的 score 等于 0 与普通中性样本。
3. 先验证当前负向样本后续表现，再决定是否放宽阈值。

否则你很容易把一个本来用于约束过热成长定价的子因子，改成一个永远中性的装饰项。

---

## 9. 复盘 growth_valuation 时的最小读法

建议按下面顺序看：

1. 先看 PEG 是否存在，是否是回推值。
2. 再看市销率是否存在。
3. 判断 score 是 0、0.25、0.5、0.75 还是 1.0。
4. 再看它是单纯没提供帮助，还是已经显式负向。
5. 最后放回 fundamental 聚合，看它是否只是缺助推，还是和其他质量项一起形成明确拖累。

---

## 10. 一句话总结

growth_valuation 是 fundamental 里的成长定价约束器。它不负责判断公司有没有成长，而是负责判断当前价格是否还配得上这段成长，因此它更常见的作用是阻止系统过度乐观，而不是主动大面积判空。
