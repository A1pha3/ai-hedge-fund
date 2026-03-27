# Fundamental 常见问题 FAQ

适用对象：已经接触过 fundamental 相关文档，但在学习、复盘或调参时反复遇到相同疑问的开发者、研究者、复盘人员。

这份 FAQ 解决的问题：

1. 把散落在多篇文档里的常见误判收成问答式入口。
2. 让读者在不通读所有专题的前提下，也能快速定位核心结论。
3. 给复盘和实验提供一份“先别误会这几点”的短清单。

建议搭配阅读：

1. [Fundamental 专题首页](./14-fundamental-topic-reading-path.md)
2. [Fundamental 因子一页速查卡](./08-fundamental-factor-one-page-cheatsheet.md)
3. [Fundamental 五子因子联动复盘手册](./15-fundamental-subfactor-joint-review-manual.md)

---

## 1. fundamental 是不是就是估值因子

不是。

fundamental 在这个项目里是一条复合策略，同时覆盖：

1. 盈利底线
2. 增长验证
3. 财务健康
4. 成长定价匹配
5. 行业相对估值

它当然包含估值约束，但绝不是“只看 PE”。

进一步阅读：

1. [07-fundamental-factor-professional-guide.md](./07-fundamental-factor-professional-guide.md)

---

## 2. 为什么它经常显得特别冷

通常不是因为有 bug，而是因为它承担了质量过滤职责。

最常见的原因有三类：

1. 候选本身盈利、增长或财务健康不够正。
2. profitability 的 hard cliff 把边缘样本直接推入负向。
3. 一部分样本根本没拿到完整评分，供给侧本来就偏冷。

进一步阅读：

1. [08-fundamental-factor-one-page-cheatsheet.md](./08-fundamental-factor-one-page-cheatsheet.md)
2. [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)

---

## 3. fundamental 低通过率，是不是说明这条因子没用

不是。

低通过率本身只说明它真的在过滤，不说明过滤一定正确或错误。真正要问的是：

1. 它挡掉的是噪音，还是错杀了边缘票。
2. 问题来自子因子语义、评分供给，还是全局融合。

进一步阅读：

1. [07-fundamental-factor-professional-guide.md](./07-fundamental-factor-professional-guide.md)
2. [04-层B因子参数根因分析与实验矩阵-20260326.md](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)

---

## 4. 为什么 profitability 总是最显眼

因为它有 hard cliff。

在当前实现里，如果三项盈利指标一项都没过，默认就会直接进入负向分支，所以它很容易成为主杀器。

这和 growth 或 growth_valuation 不一样，后两者更常见的是不给帮助，而不是立刻强负。

进一步阅读：

1. [09-profitability-subfactor-professional-guide.md](./09-profitability-subfactor-professional-guide.md)
2. [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)

---

## 5. 把 profitability 的 confidence 调低，是不是就会更宽松

不能这样简单理解。

当前聚合器里，confidence 不只是一个线性强度旋钮，还会参与最终策略输出和一致性效果，因此单独调低 confidence 并不等于“安全放松语义”。

如果真正想放松 profitability，优先应该研究：

1. zero_pass_mode
2. 阈值本身
3. 分支语义是否合理

进一步阅读：

1. [09-profitability-subfactor-professional-guide.md](./09-profitability-subfactor-professional-guide.md)
2. [01-aggregation-semantics-and-factor-traps.md](./01-aggregation-semantics-and-factor-traps.md)

---

## 6. growth 和 growth_valuation 到底差在哪

一句话区分：

1. growth 看公司有没有真的在长。
2. growth_valuation 看这种成长当前价格还配不配得上。

一个偏经营现实，一个偏经营与定价匹配关系。

进一步阅读：

1. [10-growth-subfactor-professional-guide.md](./10-growth-subfactor-professional-guide.md)
2. [12-growth-valuation-subfactor-professional-guide.md](./12-growth-valuation-subfactor-professional-guide.md)

---

## 7. 为什么 growth_valuation 经常非正，但又不像主杀器

因为它很多“非正”其实只是中性，不提供帮助，但不一定明确负向。

当前实现里，只有 score 等于 0 才直接判空。所以它经常扮演的是缺助推器，而不是主杀器。

进一步阅读：

1. [12-growth-valuation-subfactor-professional-guide.md](./12-growth-valuation-subfactor-professional-guide.md)
2. [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)

---

## 8. 为什么 industry_pe 几乎没存在感

当前窗口里，主因通常不是它规则太温和，而是它经常没有进入 active 集合。

也就是说，更常见的问题是：

1. 行业名缺失
2. 行业中位数缺失
3. 当前 PE 缺失

这会让它 completeness 为 0，根本没有参与评分。

进一步阅读：

1. [13-industry-pe-subfactor-professional-guide.md](./13-industry-pe-subfactor-professional-guide.md)

---

## 9. 一只票被 fundamental 压下去，复盘时第一步看什么

先看 completeness。

先确认：

1. 这只票是否真的拿到完整 fundamental 评分。
2. 哪些子因子 active，哪些 completeness 为 0。

如果第一步不做，后面的所有结论都可能建立在误读上。

进一步阅读：

1. [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)

---

## 10. 调参前最重要的判断是什么

先把问题分成三类：

1. 语义问题
2. 供给问题
3. 融合问题

如果不先分这个，最常见的结果就是：

1. 用阈值去修供给问题
2. 用局部子因子修改去修全局融合问题
3. 用表面通过率改善掩盖解释力下降

进一步阅读：

1. [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)
2. [04-层B因子参数根因分析与实验矩阵-20260326.md](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)

---

## 11. 我应该先看 FAQ、速查卡、专题首页还是专业长文

可以按这个顺序选：

1. 只想 5 分钟建立轮廓：看 [08-fundamental-factor-one-page-cheatsheet.md](./08-fundamental-factor-one-page-cheatsheet.md)
2. 想知道整套材料如何组织：看 [14-fundamental-topic-reading-path.md](./14-fundamental-topic-reading-path.md)
3. 已经带着具体疑问进来：先看这份 FAQ
4. 准备认真复盘或调参：看 [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)
5. 准备深挖定义和代码语义：看 [07-fundamental-factor-professional-guide.md](./07-fundamental-factor-professional-guide.md)

---

## 12. 一句话总结

这份 FAQ 的作用不是替代长文，而是把最容易反复误会的问题先收口，让你知道哪些直觉不能直接拿来解释 fundamental。
