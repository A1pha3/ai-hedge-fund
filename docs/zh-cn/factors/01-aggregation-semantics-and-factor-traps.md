# 因子聚合语义入门：为什么直觉调参会失效

> 适用对象：第一次接触本项目 Layer B 打分逻辑的开发者、研究者、排障人员

> 阅读目标：看懂两个反直觉结论
>
> 1. profitability 的问题不能靠简单降低 confidence 解决
> 2. mean_reversion 的问题不能靠简单降低 completeness 数值解决

---

## 1. 先说结论

如果你只记住一句话，请记这句：

**当前 Layer B 里，confidence 和 completeness 都不是“线性旋钮”，而是带有特定代码语义的结构变量。**

这意味着：

1. 你以为自己只是在把某个负项调弱一点，结果可能是把整条策略的方向结构打乱了。
2. 你以为自己把某条中性策略的权重降到一半，结果在归一化层面它仍然占着完整席位。

所以“把数字调小一点试试”在这个项目里经常不成立。

---

## 2. Layer B 到底分几层算分

要理解这个问题，先把 Layer B 拆成两个步骤看。

### 2.1 第一步：策略内部先聚合子因子

例如：

1. `profitability`
2. `growth`
3. `financial_health`
4. `growth_valuation`
5. `industry_pe`

这些会先在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L132) 的 `aggregate_sub_factors()` 里，聚合成一条 `fundamental` 策略信号。

这条策略信号有三个核心字段：

1. `direction`：方向，取值为 `-1 / 0 / +1`
2. `confidence`：置信度，范围 `0 ~ 100`
3. `completeness`：完整度，范围 `0 ~ 1`

### 2.2 第二步：多条策略再做 Layer B 融合

例如：

1. `trend`
2. `mean_reversion`
3. `fundamental`
4. `event_sentiment`

这些会在 [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py#L15) 的 `_normalize_for_available_signals()` 和 [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py#L117) 的 `compute_score_b()` 里，融合成最终的 `score_b`。

所以你调一个子因子，至少会经过两层语义转换：

1. 子因子如何影响“单策略输出”
2. 单策略又如何影响“Layer B 总分”

很多直觉错误，都是因为把这两层混在一起看了。

---

## 3. 为什么 profitability 不能靠简单降低 confidence 解决

### 3.1 直觉上你会怎么想

看到 `profitability` 是强负项时，最自然的想法是：

1. 现在它太严了
2. 不要让它是 `confidence = 100`
3. 改成 `confidence = 40`
4. 这样它对总分的拖累应该就变小了

这个直觉在很多系统里是对的。

但在这里，不对。

### 3.2 当前代码不是“简单相加”

在 [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py#L132) 的 `aggregate_sub_factors()` 里，逻辑大致是：

1. 先把所有可用子因子做带方向的加权和
2. 根据这个和的正负，得出最终 `direction`
3. 再统计“有多少子因子和最终方向一致”
4. 用这个一致性 `consistency` 去乘平均 confidence

简化理解就是：

$$
\text{最终 confidence} \approx \text{加权平均 confidence} \times \text{一致性 consistency}
$$

重点在于：

**confidence 不只是“音量”，它还会间接影响整条策略看起来是否方向清晰。**

### 3.3 这为什么会导致反直觉结果

假设一条策略内部有：

1. 一个强正项
2. 一个强负项
3. 其他几个中性项

如果你把强负项从 `-1 / 100` 改成 `-1 / 40`，你并不只是把负面影响缩小了。

你同时也在改变：

1. 最终方向是怎么算出来的
2. 哪些子因子算“和最终方向一致”
3. 最后那条策略的 `confidence × consistency`

结果就可能变成：

1. 负项没被真正消掉
2. 方向结构还更乱了
3. 最终整条策略输出反而更弱

### 3.4 实际样本：300065 和 600111

我们做过小范围反事实，样本包括：

1. `300065`：20260223、20260224、20260225
2. `600111`：20260204

结论是：

1. 如果把 `profitability` 这个硬负项直接移出聚合，`300065` 会从约 `0.3735 ~ 0.3739` 抬到约 `0.3870 ~ 0.3874`
2. 同样处理 `600111`，会从 `0.3454` 抬到 `0.3803`
3. 但如果只是把 `profitability` 从 `confidence = 100` 改成 `confidence = 40`，`300065` 反而掉到约 `0.3404 ~ 0.3408`
4. `600111` 也会掉到 `0.2958`

这说明一件事：

**在当前聚合器里，“降低负项 confidence”不等于“温和化负项”，它可能是在破坏整条 fundamental 的方向表达。**

### 3.5 所以 profitability 真正的问题是什么

真正的问题更接近：

1. 当前 `profitability` 是一个很硬的 cliff 规则
2. 它不是连续扣分，而是“0 项达标直接强负”
3. 所以该优先检查的是“谁会掉进这条支路”，而不是先调 confidence 数值

当前规则是：

1. `ROE >= 0.15`
2. `net_margin >= 0.20`
3. `operating_margin >= 0.15`

然后：

1. 2 项及以上达标：正向
2. 0 项达标：强负
3. 1 项达标：中性

所以更合理的问题是：

1. 这三个阈值是否太刚性
2. “0 项达标直接强负”是否过陡
3. 这类硬负项是否应该以现在的方式参与子因子聚合

而不是简单问：“confidence 100 要不要改成 40”。

---

## 4. 为什么 mean_reversion 不能靠简单降低 completeness 数值解决

### 4.1 直觉上你会怎么想

看到 `mean_reversion` 经常是中性时，很自然会想：

1. 它虽然不给分
2. 但也别让它占太多权重
3. 那我把它的 `completeness` 从 `1.0` 改成 `0.5`
4. 甚至改成 `0.25`
5. 这样它就只占半份或四分之一权重了

这个直觉也很自然。

但在当前实现里，同样不成立。

### 4.2 问题出在归一化逻辑

在 [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py#L15) 的 `_normalize_for_available_signals()` 里，策略是否参与权重归一化，看的是：

$$
\text{signal.completeness} > 0
$$

只要大于 0，这条策略就会被认为是“active”。

注意这个判断的性质：

1. 不是按 `0.25`、`0.5`、`1.0` 连续变化
2. 而是一个开关
3. 只分“参与”或“不参与”

### 4.3 这会造成什么结果

假设 Layer B 里有三条活跃策略：

1. `trend`
2. `fundamental`
3. `mean_reversion`

如果 `mean_reversion` 是中性，但 `completeness = 1.0`，它会占一份归一化权重。

如果你把它改成 `completeness = 0.5`：

1. 它自己的分值还是方向为 0
2. 但在“是否参与归一化”这一步，它仍然是 active
3. 所以 `trend` 和 `fundamental` 的权重并没有变大

也就是说：

**你以为在调权重，实际上你只是改了一个不会影响 active/inactive 判定的数值。**

### 4.4 实际反事实：0.5 和 0.25 都完全没用

我们做过两个更温和的窗口级反事实：

1. 当 `mean_reversion` 整体为中性时，把 completeness 从 `1.0` 降到 `0.5`
2. 当 `mean_reversion` 整体为中性时，把 completeness 从 `1.0` 降到 `0.25`

结果都一样：

1. 20 日窗口 Layer B 通过数仍然是 `4`
2. 新增穿线数仍然是 `0`
3. 边缘样本也完全不动

这不是因为 mean_reversion 不重要。

恰恰相反，正是因为当前代码把 completeness 当成“是否参与归一化的开关”，所以你改小它的数值没有意义。

### 4.5 mean_reversion 真正的问题是什么

真正的问题不是：

1. `completeness` 应该是 1.0 还是 0.5

而是：

1. 一条 `direction = 0` 的策略，是否应该占用完整归一化席位
2. “完整中性”是否应该和“有效信息”被同等对待
3. 当前中性策略的 active 判定条件是否过宽

所以更有效的问题是：

1. 中性策略是否应该完全退出归一化
2. 中性策略是否只占部分显式权重
3. 哪些中性情况其实应该被视为“信息不足”而不是“完整中性”

而不是先问：“把 completeness 从 1.0 改成 0.5 行不行”。

---

## 5. 一个最小对照表

| 你以为自己在做什么 | 当前代码里实际发生了什么 | 为什么结果反直觉 |
|---|---|---|
| 把 profitability 的负项 confidence 从 100 降到 40 | 改的不只是负项强弱，还会影响整条策略的方向一致性和最终 confidence | 子因子聚合不是线性加法 |
| 把中性 mean_reversion 的 completeness 从 1.0 降到 0.5 | 只要 completeness 仍然大于 0，它在归一化里还是 full active | 归一化只看是否大于 0，不看具体数值 |

---

## 6. 用一句更准确的话重写那两个结论

原始说法是：

1. profitability 的问题不能靠简单降 confidence 解决
2. mean_reversion 的问题不能靠简单降 completeness 数值解决

如果改写成更容易懂的版本，可以写成：

1. **profitability 的问题不只是参数值太大，而是“硬负项如何参与子因子聚合”的语义问题。**
2. **mean_reversion 的问题不只是 completeness 太高，而是“中性策略是否参与完整归一化”的语义问题。**

也就是说，这两个问题都不是单纯调一个数字，而是要先问：

**这个数字在代码里到底代表什么。**

---

## 7. 新手最容易犯的两个误区

### 误区一：把 confidence 当成线性音量旋钮

错误想法：

1. 负项太重
2. 把 confidence 调低就好了

正确理解：

1. 在当前 `aggregate_sub_factors()` 里，confidence 还会影响整条策略的方向一致性表达
2. 所以它不是一个独立的线性音量旋钮

### 误区二：把 completeness 当成连续权重旋钮

错误想法：

1. 中性策略占权重太多
2. 把 completeness 从 1.0 改成 0.5 就会只占一半

正确理解：

1. 在当前 `_normalize_for_available_signals()` 里，只要 completeness 大于 0 就会参与归一化
2. 所以 completeness 现在更像开关，不像连续权重

---

## 8. 后续真正有意义的改动方向是什么

先强调：下面是“值得分析的方向”，不是已经确认应该上线的改法。

### 8.1 对 profitability

更有意义的方向：

1. 调整“0 项达标 -> 强负”的进入条件
2. 调整三条 profitability 阈值本身
3. 改变硬负项在子因子聚合里的参与方式

不太有意义的方向：

1. 只把强负项 confidence 从 100 改到 40

### 8.2 对 mean_reversion

更有意义的方向：

1. 改 active signal 的判定方式
2. 让中性策略不占完整归一化席位
3. 明确定义“完整中性”和“信息不足”的区别

不太有意义的方向：

1. 只把中性策略 completeness 从 1.0 改成 0.5 或 0.25

---

## 9. 你可以怎么用这篇文档

如果你是第一次接触这块逻辑，建议按这个顺序反复看：

1. 先看“第 2 节”，建立 Layer B 两层计算框架
2. 再看“第 3 节”，理解为什么 profitability 的调参直觉会失效
3. 再看“第 4 节”，理解为什么 mean_reversion 的 completeness 直觉会失效
4. 最后看“第 8 节”，区分“值得继续验证的方向”和“看起来合理但其实无效的方向”

如果你后面要继续读专项分析，建议配合这份文档一起看：

1. [pipeline-funnel-scan-202602-window-20260312.md](../analysis/pipeline-funnel-scan-202602-window-20260312.md)

---

## 10. 最后的记忆卡片

可以把下面这 4 句当成速记：

1. `profitability` 的 hard negative 先是“语义问题”，后才是“参数问题”。
2. `mean_reversion` 的 neutral completeness 先是“归一化问题”，后才是“数值问题”。
3. `confidence` 在当前子因子聚合里不是线性音量。
4. `completeness` 在当前 Layer B 归一化里不是连续权重，而更像开关。