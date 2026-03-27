# Layer B / Layer C 联动复盘手册：从规则放行到研究确认再到 watchlist

适用对象：已经分别理解 Layer B 和 Layer C，但在真实 report、selection_review 或参数实验中需要判断“问题到底卡在哪一层”的开发者、研究者、复盘人员。

这份文档解决的问题：

1. 为什么有些票死在 Layer B，有些票穿透到 Layer C 后再被拒。
2. 如何区分“Layer B 没放出来”“Layer C 不认同”“watchlist 厚度不够”和“执行未承接”四类问题。
3. 在跨层复盘时，最小但可靠的判断顺序是什么。
4. 调参时，怎么避免把 B 层、C 层和执行层的问题混成一团。

建议搭配阅读：

1. [Layer B 策略完全讲解](./03-layer-b-complete-beginner-guide.md)
2. [Layer B 一页速查卡](./05-layer-b-one-page-cheatsheet.md)
3. [Fundamental 五子因子联动复盘手册](./15-fundamental-subfactor-joint-review-manual.md)
4. [Layer C 策略完全讲解](./16-layer-c-complete-beginner-guide.md)
5. [Layer C 一页速查卡](./19-layer-c-one-page-cheatsheet.md)
6. [Layer C 常见问题 FAQ](./21-layer-c-faq.md)
7. [Execution Bridge 专业讲解](./24-execution-bridge-professional-guide.md)
8. [Execution Bridge 一页速查卡](./25-execution-bridge-one-page-cheatsheet.md)

---

## 1. 先说结论

如果只记住最核心的判断，可以先记这 8 条：

1. 复盘跨层问题时，第一步不是看最终有没有买，而是先确定样本死在哪一层。
2. Layer B 的主问题通常是规则放行和评分供给，Layer C 的主问题通常是研究共识和冲突识别。
3. 一只票没进 Layer C，优先怀疑 Layer B fast gate，而不是 Layer C 算法。
4. 一只票进了 Layer C 但没进 watchlist，优先区分 `decision_avoid` 和 `score_final_below_watchlist_threshold`。
5. Layer B 正、Layer C 负，不一定说明谁错了，更常见是规则层发现边缘机会，但研究层不买账。
6. Layer C 过了也不等于一定下单，后面还有 execution bridge 和持仓约束。
7. 参数实验必须分层观察 `layer_b_count`、`layer_c_count`、`watchlist_count`、`buy_order_count`，不能只看一个数字。
8. 真正稳的调优方式，不是让每层都“更热”，而是先定位主矛盾到底在哪一层。

---

## 2. 先把跨层流程看清楚

最简流程如下：

```text
Layer A 候选池
  -> Layer B 四策略打分与融合
  -> high_pool
  -> fast / precise agent 分析
  -> Layer C 聚合
  -> watchlist
  -> buy_orders
  -> execution
```

对应的跨层职责是：

1. Layer B 回答“规则层是否值得继续研究”。
2. Layer C 回答“研究层是否形成足够强的正向共识”。
3. watchlist 回答“综合分数和决策标签是否允许入池”。
4. execution 回答“研究通过后，今天到底能不能买”。

如果不先把这四层分开，后面的复盘结论会非常容易失真。

---

## 3. 四种最常见的失败位置

### 3.1 死在 Layer B

表现为：

1. 样本没有进入 high_pool
2. 根本没有 Layer C 记录

常见原因：

1. `score_b` 不够
2. 某条关键策略或子因子拖累明显
3. 供给侧没有拿到完整评分

### 3.2 穿透到 Layer C，但被研究层明确反对

表现为：

1. 有 Layer C 记录
2. `decision = avoid`

常见原因：

1. `raw_score_c` 强 bearish
2. 出现明显 `bc_conflict`

### 3.3 Layer C 不是强反对，但 watchlist 厚度不够

表现为：

1. `decision != avoid`
2. 但 `score_final_below_watchlist_threshold`

这说明：

1. 研究层不是完全否定
2. 但 B/C 综合共识厚度仍不足以入池

### 3.4 进了 watchlist，但 execution 未承接

表现为：

1. 有 watchlist
2. 没有 buy_order 或没有实际成交

这时重点已经不在 Layer B / C 本身，而在 execution blocker。

---

## 4. 跨层复盘的最小顺序

建议严格按下面 6 步走。

### 4.1 第一步：先定位样本停在哪一层

优先看：

1. 是否进入 high_pool
2. 是否有 Layer C 结果
3. 是否进入 watchlist
4. 是否生成 buy_order
5. 是否实际执行

这一步的目标不是解释原因，而是先确定问题边界。

### 4.2 第二步：如果停在 Layer B，就只看 B

优先看：

1. `score_b`
2. 四策略贡献
3. fundamental 内部五子因子
4. coverage / completeness

这时不要急着讨论 Layer C，因为样本根本没到那一层。

### 4.3 第三步：如果进了 Layer C，再区分是明确反对还是厚度不够

优先看：

1. `decision`
2. `bc_conflict`
3. `raw_score_c`
4. `score_c`
5. `score_final`

关键分叉是：

1. `decision_avoid`
2. `score_final_below_watchlist_threshold`

这是两个完全不同的问题。

### 4.4 第四步：判断是 B/C 冲突，还是研究层自然偏弱

最常见的两种情况：

1. Layer B 强，但 Layer C 原始研究层为负
2. Layer B 只是边缘正，Layer C 也只是近中性

前者更像结构性冲突票，后者更像研究厚度不足票。

### 4.5 第五步：如果过了 watchlist，再看 execution bridge

优先看：

1. blocker 原因
2. reentry / position / timing 约束
3. T+1 执行桥接是否承接

如果需要把这一步单独展开，直接看 [24-execution-bridge-professional-guide.md](./24-execution-bridge-professional-guide.md)；如果只需要快速解释 blocker 含义，看 [25-execution-bridge-one-page-cheatsheet.md](./25-execution-bridge-one-page-cheatsheet.md)。

这一步避免把 execution 问题错误甩回 Layer C。

### 4.6 第六步：最后才讨论参数应该改哪层

只有前五步做完之后，才去判断：

1. 要不要调 Layer B
2. 要不要调 Layer C
3. 还是执行层限制才是主矛盾

---

## 5. 三类典型跨层样本

### 5.1 Layer B 冷样本

特征：

1. `layer_b_count` 本身就很低
2. 样本没有 Layer C 记录

这类样本的优先问题通常是：

1. fast gate 太冷
2. fundamental / trend 本身不给通过
3. 样本供给没有进入重评分

### 5.2 B 强 C 弱样本

特征：

1. `score_b` 不低
2. `raw_score_c` 为负或明显偏弱
3. 有 `bc_conflict`

这类样本最重要的不是“哪一层错了”，而是：

1. 规则层发现了边缘机会
2. 研究层认为这不是干净强票

### 5.3 C 过但 execution 未承接样本

特征：

1. 进入 watchlist
2. buy_order 缺失或执行未发生

这类样本优先应放到 execution bridge 里解释，而不是继续争论 Layer B / C 分数。

---

## 6. 参数实验时该看哪些计数

跨层实验不能只盯一个数。最小观察面至少包括：

1. `layer_b_count`
2. `layer_c_count`
3. `watchlist_count`
4. `buy_order_count`
5. `decision_avoid` 分布
6. `score_final_below_watchlist_threshold` 分布

这是因为：

1. 只看 Layer B count，会忽视样本是否只是被挪到 Layer C 再拒。
2. 只看 watchlist count，会忽视 execution 是否根本不承接。
3. 只看 buy order count，又会把执行层约束误解释为研究层改好了。

---

## 7. 最常见的 5 个错误复盘

### 7.1 把所有问题都归因到 Layer B 太严

如果样本已经稳定进入 Layer C，主矛盾可能早就不在 Layer B。

### 7.2 把所有 watchlist 拒绝都归因到 Layer C 强反对

很多样本并不是 `avoid`，而只是 `score_final` 厚度不够。

### 7.3 把 execution blocker 误读成 Layer C 没通过

watchlist 已过但没下单，不等于研究层没通过。

### 7.4 只看单层通过率，不看跨层迁移

释放出来的样本如果只是从 Layer B 挪到 Layer C 再死，业务价值可能很有限。

### 7.5 不区分结构性冲突票和边缘厚度不足票

前者更适合继续 veto，后者才更可能值得讨论放宽。

---

## 8. 复盘模板

如果你要快速写一段跨层复盘，可以直接套这个模板：

1. 该样本停在 Layer B、Layer C、watchlist 还是 execution。
2. 如果停在 Layer B，主拖累策略和子因子是什么。
3. 如果进入 Layer C，`decision`、`bc_conflict`、`raw_score_c`、`score_final` 分别是什么。
4. 它属于研究层明确反对，还是共识厚度不够。
5. 如果过了 watchlist，execution bridge 是否承接。
6. 当前问题属于 B 层、C 层、还是执行层。
7. 下一步应该改规则、改融合、还是改执行约束。

---

## 9. 一句话总结

跨层复盘最重要的不是谁的分更高，而是先判断样本死在哪一层，再决定该解释规则问题、研究问题，还是执行问题。只有先做分层定位，后面的调参才不会乱。
