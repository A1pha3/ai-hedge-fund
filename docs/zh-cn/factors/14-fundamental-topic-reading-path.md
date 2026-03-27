# Fundamental 专题首页：阅读路径、学习顺序与使用场景

适用对象：第一次系统学习 fundamental 因子的读者，以及想快速定位“该看哪篇”的开发者、研究者、复盘人员。

这份文档解决的问题：

1. 07 到 13 这一组文档分别讲什么。
2. 不同背景的读者应该按什么顺序读。
3. 什么时候看总览，什么时候看单因子专题，什么时候看源码或实验文档。
4. 如果只是要解决一个具体问题，应该从哪里切入。

---

## 1. 这组文档整体在解决什么

fundamental 在 Layer B 里不是一个单一指标，而是一条由五个子因子共同组成的复合策略：

1. profitability
2. growth
3. financial_health
4. growth_valuation
5. industry_pe

这条策略既负责质量过滤，也负责成长验证和相对估值约束，因此很容易出现两个问题：

1. 新读者看完总览仍不知道真正该查哪一条腿。
2. 老读者知道子因子名，但不知道复盘时先看哪个字段、哪个现象、哪个文档。

这份首页就是把这些文档组织成一条可执行阅读路径。

---

## 2. 文档地图

建议把这组文档分成四层理解。

### 2.1 第一层：先知道它是什么

1. [Fundamental 因子专业讲解](./07-fundamental-factor-professional-guide.md)
2. [Fundamental 因子一页速查卡](./08-fundamental-factor-one-page-cheatsheet.md)
3. [Fundamental 常见问题 FAQ](./18-fundamental-faq.md)

这一层回答的是：

1. fundamental 在 Layer B 里负责什么。
2. 五个子因子分别承担什么角色。
3. 为什么它经常显得冷。

### 2.2 第二层：把五条腿拆开看懂

1. [Profitability 子因子专业讲解](./09-profitability-subfactor-professional-guide.md)
2. [Growth 子因子专业讲解](./10-growth-subfactor-professional-guide.md)
3. [Financial Health 子因子专业讲解](./11-financial-health-subfactor-professional-guide.md)
4. [Growth Valuation 子因子专业讲解](./12-growth-valuation-subfactor-professional-guide.md)
5. [Industry PE 子因子专业讲解](./13-industry-pe-subfactor-professional-guide.md)

这一层回答的是：

1. 每条腿到底在问什么。
2. 它们的阈值和方向如何形成。
3. 它们最常见的误判点是什么。

### 2.3 第三层：知道如何在真实样本里读它们

1. [Fundamental 五子因子联动复盘手册](./15-fundamental-subfactor-joint-review-manual.md)
2. [Fundamental 常见问题 FAQ](./18-fundamental-faq.md)

这一层回答的是：

1. 一只股票 fundamental 低，到底是谁在拖累。
2. 谁是真正主杀器，谁只是没提供帮助。
3. 应该先排语义问题、供给问题，还是融合层问题。

### 2.4 第四层：需要回到系统全局时看哪里

1. [因子聚合语义入门](./01-aggregation-semantics-and-factor-traps.md)
2. [Layer B 策略完全讲解](./03-layer-b-complete-beginner-guide.md)
3. [Layer B 源码导读](./06-layer-b-source-code-walkthrough.md)
4. [层 B 因子参数根因分析与实验矩阵](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)

这一层回答的是：

1. fundamental 不是孤立工作的，它如何进入 Layer B 总体聚合。
2. 为什么一些直觉调参在系统层会失效。
3. 当前窗口里哪些现象是子因子语义问题，哪些是供给或容量问题。

---

## 3. 三种读法

### 3.1 新人读法

如果你第一次接触这个主题，建议顺序如下：

1. [08-fundamental-factor-one-page-cheatsheet.md](./08-fundamental-factor-one-page-cheatsheet.md)
2. [07-fundamental-factor-professional-guide.md](./07-fundamental-factor-professional-guide.md)
3. [09-profitability-subfactor-professional-guide.md](./09-profitability-subfactor-professional-guide.md)
4. [10-growth-subfactor-professional-guide.md](./10-growth-subfactor-professional-guide.md)
5. [11-financial-health-subfactor-professional-guide.md](./11-financial-health-subfactor-professional-guide.md)
6. [12-growth-valuation-subfactor-professional-guide.md](./12-growth-valuation-subfactor-professional-guide.md)
7. [13-industry-pe-subfactor-professional-guide.md](./13-industry-pe-subfactor-professional-guide.md)
8. [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)

这是从概念到拆解，再到实战读法的一条完整路径。

### 3.2 复盘读法

如果你正在看一只股票为什么被 fundamental 压下去，建议顺序如下：

1. [08-fundamental-factor-one-page-cheatsheet.md](./08-fundamental-factor-one-page-cheatsheet.md)
2. [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)
3. 再按需要跳到对应子因子专题

这条路线更快，适合带着问题进来，而不是从头学习。

### 3.3 调参读法

如果你准备做实验或提规则修改，建议顺序如下：

1. [07-fundamental-factor-professional-guide.md](./07-fundamental-factor-professional-guide.md)
2. [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)
3. [01-aggregation-semantics-and-factor-traps.md](./01-aggregation-semantics-and-factor-traps.md)
4. [04-层B因子参数根因分析与实验矩阵-20260326.md](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)

这条路线可以避免只看局部阈值就急着下结论。

---

## 4. 按问题找文档

如果你的问题更具体，可以直接按下面映射查：

1. “fundamental 到底负责什么”：看 [07-fundamental-factor-professional-guide.md](./07-fundamental-factor-professional-guide.md)
2. “我只想 5 分钟搞懂”：看 [08-fundamental-factor-one-page-cheatsheet.md](./08-fundamental-factor-one-page-cheatsheet.md)
3. “为什么 profitability 压得最狠”：看 [09-profitability-subfactor-professional-guide.md](./09-profitability-subfactor-professional-guide.md)
4. “为什么增长看起来不拉分”：看 [10-growth-subfactor-professional-guide.md](./10-growth-subfactor-professional-guide.md)
5. “为什么财务健康会和质量红旗联动”：看 [11-financial-health-subfactor-professional-guide.md](./11-financial-health-subfactor-professional-guide.md)
6. “为什么 growth_valuation 常常非正却不是主杀器”：看 [12-growth-valuation-subfactor-professional-guide.md](./12-growth-valuation-subfactor-professional-guide.md)
7. “为什么 industry_pe 几乎没存在感”：看 [13-industry-pe-subfactor-professional-guide.md](./13-industry-pe-subfactor-professional-guide.md)
8. “真实复盘时应该先查谁”：看 [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)
9. “我只是先想排除常见误解”：看 [18-fundamental-faq.md](./18-fundamental-faq.md)

---

## 5. 这组文档的最小使用方式

如果你不想一次看完全部材料，最小使用方式可以压缩成 3 步：

1. 先用 [08-fundamental-factor-one-page-cheatsheet.md](./08-fundamental-factor-one-page-cheatsheet.md) 建立整体心智模型。
2. 遇到具体拖累项时，跳到对应子因子专题。
3. 真正准备做实验时，再补 [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md) 和系统级文档。

---

## 6. 一句话总结

07 到 13 解决的是“fundamental 到底是什么”，15 解决的是“真实样本里怎么用”，而这份首页负责把它们组织成一条能学、能查、能落到实验上的阅读路径。
