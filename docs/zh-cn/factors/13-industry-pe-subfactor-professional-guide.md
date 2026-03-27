# Industry PE 子因子专业讲解：行业相对估值、数据缺口与解释边界

适用对象：已经理解 Layer B 和 fundamental 基本结构，现在要单独研究 industry_pe 子因子的开发者、研究者、复盘人员。

这份文档解决的问题：

1. industry_pe 为什么不是简单的 PE 因子，而是行业相对估值因子。
2. 它的正负方向是如何由行业中位数溢价率决定的。
3. 为什么它在当前窗口里几乎没有参与评分。
4. 它的数据缺口会怎样影响对 fundamental 的解读。
5. 做 industry_pe 实验时，如何避免把数据缺失误判成估值宽松或因子失效。

建议搭配阅读：

1. [Fundamental 因子专业讲解](./07-fundamental-factor-professional-guide.md)
2. [Growth Valuation 子因子专业讲解](./12-growth-valuation-subfactor-professional-guide.md)
3. [Layer B 源码导读](./06-layer-b-source-code-walkthrough.md)
4. [层 B 因子参数根因分析与实验矩阵](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)

---

## 1. 先说结论

如果只记住最核心的判断，可以先记这 7 条：

1. industry_pe 不是比较股票绝对 PE 高低，而是比较它相对所在行业中位数的偏离程度。
2. 它在 fundamental 五个子因子里默认权重为 0.15，属于估值辅助腿。
3. 只有拿到行业名、行业 PE 中位数和股票当前 PE，这条子因子才会参与评分。
4. 它的正向区间是溢价率小于等于 0.8，负向区间是溢价率大于等于 1.2，中间保持中性。
5. 当前窗口里它几乎没有参与评分，主因不是语义太严，而是 completeness 长期为 0。
6. 因此当前看到它不出力，不应解释成“相对行业估值没有信息量”，而应先解释成“数据链路没有把它送进来”。
7. 在没有补齐行业中位数数据之前，不适合对 industry_pe 的业务价值下结论。

---

## 2. 它在代码里到底是什么

industry_pe 的 Layer B 入口在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L513) 的 `_score_industry_pe()`。

默认权重在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L75) 中定义为：

1. industry_pe = 0.15

它和其他 fundamental 子因子不一样，不依赖单只股票的内部财务时间序列，而依赖外部行业对照数据：

1. 股票当前 PE
2. 行业名称
3. 行业 PE 中位数映射表

三者缺一不可。

---

## 3. 它怎么决定方向

在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L513) 中，核心公式是：

1. premium = current_pe / industry_median_pe

然后按区间映射：

1. premium 小于等于 0.8：direction = 1
2. premium 大于等于 1.2：direction = -1
3. 其他：direction = 0

它的直觉很简单：

1. 比行业中位数便宜至少 20%，给正向。
2. 比行业中位数贵至少 20%，给负向。
3. 处在合理带内，保持中性。

这比跨行业直接比较绝对 PE 更专业，因为高成长行业和低成长行业的合理 PE 本来就不同。

---

## 4. 置信度怎么计算

industry_pe 的置信度不是固定值，而是和偏离程度有关：

1. 正向时，confidence = min(100, (1.0 - premium) × 250)
2. 负向时，confidence = min(100, (premium - 1.0) × 150)
3. 中性时，confidence = 50

这意味着：

1. 股票比行业明显便宜时，系统会快速提高正向置信度。
2. 股票比行业明显偏贵时，负向置信度也会上升，但增速稍慢。
3. 中间合理带不是没有信息，而是明确表达为中性且保留中等置信度。

这是一种偏务实的设计，不会因为估值略贵就立刻打成极强负向。

---

## 5. 为什么它在当前窗口基本没有存在感

这个问题的答案已经在 [docs/zh-cn/factors/07-fundamental-factor-professional-guide.md](./07-fundamental-factor-professional-guide.md) 里出现过：

1. 当前窗口中，industry_pe 的 completeness 基本一直为 0。
2. 这意味着它几乎没有进入 active 子因子集合。

在 fundamental 聚合器里，completeness 为 0 的子因子不会参加当前权重归一化，所以它不会形成正向，也不会形成负向。结果就是：

1. 你在复盘里很难看到它成为主拖累项。
2. 也很难看到它提供真正的估值支撑。

因此当前它更像一个“理论上存在、实际上常缺席”的因子。

---

## 6. 为什么不能把数据缺失误当成因子温和

industry_pe 最容易被误读的地方是：

1. 很多人看到它很少打负，就以为这条规则很宽松。
2. 实际上更常见的真相是它根本没被激活。

这两者差别非常大：

1. 规则宽松，意味着它确实看过了样本，只是给了中性或正向。
2. 数据缺失，意味着它根本没有进入判断，系统没有表达任何行业相对估值意见。

所以在当前窗口下，industry_pe 的首要问题不是阈值，而是可用性。

---

## 7. 它和 growth_valuation 的关系

这两个子因子都在谈估值，但角度不同：

1. growth_valuation 看成长和定价是否匹配。
2. industry_pe 看相对本行业是否高估或低估。

典型组合包括：

1. growth_valuation 中性、industry_pe 正：成长定价未必特别占优，但相对行业已经偏便宜。
2. growth_valuation 正、industry_pe 负：从成长视角价格还能接受，但相对同行已经明显偏贵。
3. 两者都缺席或中性：估值层没有给 fundamental 提供明显帮助。

如果后续要增强估值解释力，这两条腿应一起看，而不是互相替代。

---

## 8. 实验时最该先查什么

如果你怀疑 industry_pe 没有发挥作用，建议先查：

1. trade_date 对应样本是否带了 industry_name。
2. industry_pe_medians 是否成功传入。
3. current_pe 是否存在且大于 0。
4. completeness 为 0 的真实原因到底是行业缺失、映射缺失，还是 PE 缺失。

不建议一上来就做的事：

1. 先改 0.8 和 1.2 的阈值。
2. 先改置信度系数 250 和 150。
3. 不区分数据不可用和规则中性，就直接评价这个因子没价值。

在数据链路不稳定时，先调阈值通常没有意义。

---

## 9. 复盘 industry_pe 时的最小读法

建议按下面顺序看：

1. 先看它是否 active，也就是 completeness 是否大于 0。
2. 如果不 active，先定位缺的是行业名、行业中位数，还是当前 PE。
3. 如果 active，再看 premium 落在哪个区间。
4. 再看它在 fundamental 聚合里是提供了帮助、形成了拖累，还是只是中性。
5. 最后再判断当前 report 能否对行业相对估值形成可信结论。

---

## 10. 一句话总结

industry_pe 是 fundamental 里的行业相对估值校准器。它的业务价值并不在于多频繁地判空，而在于防止系统把跨行业不可比的 PE 当成统一标准；但在当前窗口里，它的主矛盾仍然是数据可用性，而不是规则强弱。
