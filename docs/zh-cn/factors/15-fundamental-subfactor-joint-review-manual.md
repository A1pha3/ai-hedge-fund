# Fundamental 五子因子联动复盘手册：谁是主拖累，谁只是缺助推

适用对象：已经知道 fundamental 五个子因子分别是什么，现在要在真实 report、selection_review 或实验样本里判断“到底是谁在拖累”的开发者、研究者、复盘人员。

这份文档解决的问题：

1. 一只股票 fundamental 为负或偏冷时，应该先看哪个字段。
2. 如何区分“主杀器”“放大器”“缺助推器”和“没参与评分”。
3. 为什么很多直觉上的结论其实把语义问题、供给问题和融合问题混在了一起。
4. 复盘和调参时，最小但可靠的判断顺序是什么。

建议搭配阅读：

1. [Fundamental 因子专业讲解](./07-fundamental-factor-professional-guide.md)
2. [Fundamental 因子一页速查卡](./08-fundamental-factor-one-page-cheatsheet.md)
3. [Profitability 子因子专业讲解](./09-profitability-subfactor-professional-guide.md)
4. [Growth 子因子专业讲解](./10-growth-subfactor-professional-guide.md)
5. [Financial Health 子因子专业讲解](./11-financial-health-subfactor-professional-guide.md)
6. [Growth Valuation 子因子专业讲解](./12-growth-valuation-subfactor-professional-guide.md)
7. [Industry PE 子因子专业讲解](./13-industry-pe-subfactor-professional-guide.md)
8. [Fundamental 常见问题 FAQ](./18-fundamental-faq.md)

---

## 1. 先说结论

如果只记住最核心的判断，可以先记这 8 条：

1. 复盘 fundamental 时，第一步不是找谁最负，而是先确认这只票有没有拿到完整评分。
2. profitability 最常见的角色是主杀器，因为它存在 hard cliff。
3. growth 更常见的角色是第二拖累项，或者不给确认。
4. financial_health 更像质量放大器，常和 profitability 联动坐实风险。
5. growth_valuation 经常非正，但很多时候只是缺助推，不是直接打死。
6. industry_pe 在当前窗口里经常是缺席项，不能把“没参与评分”误当成“宽松”。
7. 一个样本 fundamental 冷，不一定是子因子规则太严，也可能是供给侧根本没让它进入完整评分。
8. 调参前必须先判断问题属于语义、供给，还是融合层，否则容易越修越乱。

---

## 2. 先把四种角色分清

复盘时，fundamental 五个子因子可以先按四种角色理解：

### 2.1 主杀器

定义：最常直接把 fundamental 拉到负向，或成为最大负贡献项的子因子。

当前窗口里，这个角色最典型的是：

1. profitability

### 2.2 放大器

定义：不一定单独致命，但会和其他弱项联动，把风险坐实。

当前最典型的是：

1. financial_health

### 2.3 缺助推器

定义：不一定直接给负，但经常不给 fundamental 提供正向支持。

当前最典型的是：

1. growth
2. growth_valuation

两者区别是：

1. growth 偏经营验证。
2. growth_valuation 偏成长定价约束。

### 2.4 缺席项

定义：因为 completeness 为 0，没有进入当前 active 子因子集合。

当前最典型的是：

1. industry_pe

先做这个分类，能避免一上来把所有 fundamental 冷样本都归因到 profitability。

---

## 3. 复盘时的最小顺序

建议严格按下面 5 步走。

### 3.1 第一步：先看是不是没评分

优先看：

1. fundamental 的 completeness
2. 各子因子的 completeness

如果 fundamental 本身或某个子因子 completeness 为 0，那么第一结论不是“它偏空”，而是“它没参与”。

这一步的意义很大，因为当前窗口里有相当一部分问题并不是阈值太严，而是供给侧评分资格和容量导致的覆盖不足。

### 3.2 第二步：再看谁是最大负贡献项

只有在确认它真的参与评分后，才去问：

1. 谁的 direction 为负。
2. 谁的 confidence 足够高。
3. 谁在当前归一化权重下贡献了最大负值。

如果你跳过第一步，极容易把“没评分”误读成“评分后负向”。

### 3.3 第三步：判断它属于哪种角色

复盘时建议直接套用四分类：

1. 主杀器
2. 放大器
3. 缺助推器
4. 缺席项

这样你不会把所有子因子都按同一种口径解释。

### 3.4 第四步：再看是否有联动

最常见的联动包括：

1. profitability 负 + financial_health 弱
2. growth 弱 + growth_valuation 弱
3. growth 正但 financial_health 弱

这一步的核心不是找“哪条腿更重要”，而是判断 fundamental 冷是单点故障，还是多腿共振。

### 3.5 第五步：最后才放回 Layer B 全局

只在前四步做完之后，才去看：

1. market_state 调权是否改变边际影响
2. 其他策略是否对冲了 fundamental 的冷意
3. Layer C 是否进一步否决或放大了这个结论

否则你很容易把全局融合问题，误判成某个子因子的局部问题。

---

## 4. 五个子因子分别怎么读

### 4.1 profitability：先看 positive_count

这条腿最关键的不是某个连续分数，而是：

1. positive_count 是 0、1、2 还是 3
2. zero_pass_mode 是什么

在当前系统里，positive_count 等于 0 时，默认会直接走负向 hard cliff，因此它最容易成为主杀器。

### 4.2 growth：先看 active，再看 score 落区间

这条腿的典型读法是：

1. 是否满足至少 4 期财务数据
2. score 是小于 0.4、介于 0.4 到 0.6，还是大于 0.6
3. 收入、利润、现金流到底是谁在拖后腿

它更像连续验证器，而不是硬门槛。

### 4.3 financial_health：先看它是不是在给 profitability 做负向确认

这条腿要优先看：

1. debt_to_equity
2. current_ratio
3. 它是不是和 profitability 一起指向质量脆弱

它单看未必总是主杀器，但经常会把已有的质量弱点放大成更强的 fundamental 冷意。

### 4.4 growth_valuation：重点区分中性和真负向

这条腿最容易被误读。复盘时要分清：

1. 它只是中性，没有提供帮助
2. 还是 score 等于 0，已经明确负向

当前实现里，只有 score 等于 0 才直接判空，所以很多“growth_valuation 非正”并不是主杀信号。

### 4.5 industry_pe：先看 completeness，再谈语义

这条腿当前最重要的判断顺序是：

1. 行业名有没有
2. 行业中位数有没有
3. 当前 PE 有没有
4. completeness 是否大于 0

如果这些都没满足，它就只是缺席项，根本没有表达估值观点。

---

## 5. 三种最常见的错误复盘

### 5.1 把所有 fundamental 失败都归因到 profitability

profitability 最显眼，但它不是唯一原因。很多票 fundamental 偏冷，其实是：

1. growth 没确认
2. growth_valuation 没提供帮助
3. financial_health 在放大弱点

### 5.2 把所有非正都理解成主拖累

非正包括两种完全不同的情况：

1. 明确负向
2. 中性但不助推

growth_valuation 最典型地属于第二类。

### 5.3 把没参与评分理解成因子太温和

这在 industry_pe 上最常见。当前很多样本里它根本没进 active 集合，所以不能从“它很少判负”得出“它规则宽松”的结论。

---

## 6. 调参前的判断框架

如果你准备针对 fundamental 做实验，先把问题归类到下面三类之一。

### 6.1 语义问题

典型特征：

1. 子因子参与评分了
2. 规则逻辑本身让结果明显过硬或失真

例子：

1. profitability 的 zero_pass_mode

### 6.2 供给问题

典型特征：

1. 很多子因子 completeness 为 0
2. 不是规则结果太冷，而是很多票根本没得到完整评分

例子：

1. growth 的历史期数不足
2. industry_pe 的行业中位数缺失
3. heavy fundamental 容量限制带来的覆盖不足

### 6.3 融合问题

典型特征：

1. 子因子局部看合理
2. 但进入 Layer B 全局后边际效果和直觉不一致

例子：

1. 其他策略稀释了 fundamental 的正向
2. 市场状态调权改变了它的最终边际影响

只有先做这一步分类，实验结果才有可解释性。

---

## 7. 复盘模板

如果你要快速写一段样本复盘，可以直接套这个模板：

1. 该样本是否拿到完整 fundamental 评分。
2. 五个子因子中谁 active，谁 completeness 为 0。
3. 最大负贡献项是谁。
4. 是否存在主杀器 + 放大器联动。
5. 是否存在缺助推器导致的整体偏冷。
6. 当前问题属于语义、供给还是融合。
7. 下一步应该去改规则、补数据，还是看 Layer B 全局。

这个模板的目的是让复盘结论能直接落到实验动作，而不是停留在“感觉这个因子太严”。

---

## 8. 一句话总结

fundamental 的五个子因子不是五个平行扣分器，而是由主杀器、放大器、缺助推器和缺席项共同组成的解释系统。复盘时先分角色、再看联动、最后再看全局，结论才会稳。
