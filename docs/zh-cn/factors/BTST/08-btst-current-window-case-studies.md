# BTST 当前窗口案例复盘手册

适用对象：已经理解 BTST 基本规则，但还缺“真实样本长什么样、为什么这么判断”的研究员、开发者、AI 助手。

这份文档解决的问题：把最近一轮 2026-03-23 到 2026-03-26 的真实窗口结论，压缩成几个可反复复用的样本 archetype，帮助你用具体案例理解当前 BTST 的主矛盾。

建议搭配阅读：

1. [01-btst-complete-guide.md](./01-btst-complete-guide.md)
2. [02-btst-tuning-playbook.md](./02-btst-tuning-playbook.md)
3. [06-btst-troubleshooting-playbook.md](./06-btst-troubleshooting-playbook.md)
4. [07-btst-factor-metric-dictionary.md](./07-btst-factor-metric-dictionary.md)
5. [../../product/arch/short_trade_layer_b_split_decision_summary_20260329.md](../../product/arch/short_trade_layer_b_split_decision_summary_20260329.md)
6. [../../product/arch/pre_layer_short_trade_candidate_outcome_summary_20260329.md](../../product/arch/pre_layer_short_trade_candidate_outcome_summary_20260329.md)
7. [../../product/arch/pre_layer_short_trade_catalyst_floor_zero_full_live_summary_20260329.md](../../product/arch/pre_layer_short_trade_catalyst_floor_zero_full_live_summary_20260329.md)
8. [../../product/arch/pre_layer_short_trade_boundary_score_fail_frontier_summary_20260329.md](../../product/arch/pre_layer_short_trade_boundary_score_fail_frontier_summary_20260329.md)
9. [../../product/arch/layer_c_bearish_conflict_release_queue_summary_20260329.md](../../product/arch/layer_c_bearish_conflict_release_queue_summary_20260329.md)

---

## 1. 先讲结论：当前窗口不是一个问题，而是 4 类问题

最近这轮 BTST 真实窗口最有价值的地方，在于它把主矛盾拆开了，而不是继续让所有问题混成“短线效果不好”。

当前最值得记住的 4 个 archetype 是：

1. 旧共享边界池失败簇：样本很多，但绝大部分根本不像短线候选。
2. 新 `short_trade_boundary` 候选：数量更少，但质量明显更高。
3. `300724` 型：属于低成本可释放的结构冲突样本。
4. `300394` / `300502` 型：一个是 penalty 主导，一个是入口语义不匹配，不能跟 `300724` 混着救。

---

## 2. 案例 1：为什么要把 short trade 从旧 Layer B 边界池拆出来

### 2.1 观察到什么

在旧路径里，2026-03-23 到 2026-03-26 四天窗口累计出现了 23 个 `layer_b_boundary` score-fail 样本。

这些样本的共性不是“只差一点阈值”，而是：

1. `score_target` 均值只有低位邻域。
2. `breakout_freshness`、`volume_expansion_quality`、`catalyst_freshness` 几乎整体塌陷。
3. 大部分样本在进入正式短线比较前，就已经缺少可交易结构。

### 2.2 这说明什么

这说明旧问题的根不是 short-trade target 太严，而是短线和研究共用了一套不合适的边界补池。

### 2.3 后来怎么验证

把短线补池改成独立 `short_trade_boundary` candidate builder 后，同样窗口里旧 `layer_b_boundary` score-fail 从 23 个降到 0，替换为 6 个 `short_trade_boundary` near-miss。

### 2.4 应该怎么理解

这不是“语义上好看一点”的拆分，而是一个主失败簇被真实消除了。后续讨论 BTST 时，应以 `short_trade_boundary` 为当前入口主线，而不是再拿旧 `layer_b_boundary` 故事反推默认策略。

---

## 3. 案例 2：为什么当前更值得扩 coverage，而不是继续收紧入口

### 3.1 观察到什么

对比旧池和新池的 Layer C 之前候选质量，当前新 `short_trade_boundary` 候选在次日表现上明显更优：

1. `next_high_return_mean` 更高。
2. `next_close_return_mean` 更高。
3. `next_high_hit_rate@2%` 更高。
4. `next_close_positive_rate` 也更高。

### 3.2 这说明什么

这说明当前 builder 的主问题已经不是“候选太垃圾”，而是“覆盖还偏窄”。

### 3.3 为什么不是立刻全线放松

因为过滤明细显示，旧样本中 19 个首先死于 breakout，而不是集中死于一个轻微可放松的边缘条件。也就是说，不能把当前窗口解读成“所有 floor 都可以一键放松”。

### 3.4 当前最合理动作

先沿着单一可控杠杆扩覆盖，而不是同时打开多个入口条件。当前已经被完整窗口验证通过的，就是 catalyst-only 这条线。

---

## 4. 案例 3：为什么 `catalyst_freshness_min=0.00` 可以升级为默认 admission 候选

### 4.1 观察到什么

当前窗口中最接近放行的 edge candidates，集中在 `300308`、`300274`、`300502` 这类主要只差 catalyst floor 的样本。

### 4.2 静态 replay 给出的初步判断

若只把 `catalyst_freshness_min` 从 `0.12` 放到 `0.00`，其余 floor 不动，会新增有限数量样本，且质量没有明显坍塌。

### 4.3 真实 live 窗口继续证明了什么

完整 4 日 live validation 进一步证明：

1. 旧 `layer_b_boundary` score-fail 仍保持为 0。
2. 短线目标总量提升到了更合理区间。
3. 前置候选的 `next_high_return_mean` 和 `next_close_return_mean` 仍明显优于旧池。

### 4.4 结论为什么成立

这意味着当前 admission 放松线已经不是“值得继续试一试”，而是“已有真实完整窗口证据支持的默认候选”。

### 4.5 但为什么不能顺手再放松 volume

因为一旦把 volume floor 一起降下来，样本虽然更多，但 `next_close_return_mean` 和 `next_close_positive_rate` 都明显走弱。这类变体更像放热，而不是受控扩覆盖。

---

## 5. 案例 4：为什么 `300724` 是当前唯一值得定向 release 的 blocked 样本

### 5.1 baseline 长什么样

`2026-03-25 / 300724` 在 baseline 下是 `blocked`，但它有一个非常重要的特征：距离 near-miss 的 gap 明显小于窗口里其他 blocked 样本。

### 5.2 手工直觉为什么不够

很多人看到 blocked 样本，第一反应是“把 hard block 去掉试试”。但 `300724` 的窗口证据表明，只去掉 hard block 不够，它只会从 `blocked -> rejected`，分数不变。

### 5.3 真正的 low-cost rescue row 是什么

当前 evidence 表明：

1. 先移除 hard block 与 conflict surcharge 的重复惩罚。
2. 再把 `near_miss_threshold` 从 `0.46` 调到 `0.42`。

做到这一步，它就能以很低 adjustment cost 进入 `near_miss`。

### 5.4 为什么这是当前唯一合理的 release 实验

窗口级 rescue queue 已经证明，5 个 blocked 样本里只有它存在低成本 near-miss rescue row。换句话说，它是单点 case，不是整簇政策。

### 5.5 正确动作

如果下一轮要做 structural conflict release，优先做 `300724-only` 的 case-based 受控实验，而不是按整日、整窗口或整簇统一放宽。

---

## 6. 案例 5：为什么 `300394` 不是简单 threshold rescue 对象

### 6.1 它的问题不是没有优点

`300394` 的正向结构并不弱。它的问题恰恰是：有明显正贡献，但被多项 penalty 一起压住。

### 6.2 这类票最容易误判成什么

最容易被误判成“再降一点阈值就能救回来”。

### 6.3 frontier 实际说明了什么

真实 replay frontier 已经证明：

1. 只放松 penalty，不足以把它推到 near-miss。
2. 就算做极端 penalty relief，也仍需要明显下调 `near_miss_threshold`。
3. 如果想直接把它推到 `selected`，成本更高，而且会明显污染默认 profile。

### 6.4 正确结论

`300394` 当前不是 release 优先对象，也不是简单 threshold-only 对象。它更适合被视为 penalty / score construction 研究样本。

---

## 7. 案例 6：为什么 `300502` 应该优先走 candidate-entry 语义路径，而不是 penalty 路径

### 7.1 它和 `300394` 的关键差异

`300502` 不是“有不少正贡献但被压住”，而是正向结构本身就弱。

### 7.2 证据是什么

当前 replay 与 candidate-entry frontier 已经说明：

1. 它的 `breakout_freshness` 和 `volume_expansion_quality` 很弱。
2. `trend_acceleration` 和 `close_strength` 也落在弱结构 separating row 的一侧。
3. 最小 preserving row 甚至表明，仅 `volume_expansion_quality <= 0.0` 就足以把它从候选中去掉，同时保留 `300394`。

### 7.3 这说明什么

这说明它首先是入口语义问题，而不是 penalty 微调对象。

### 7.4 正确动作

对这类票，应优先继续定义“弱结构 candidate-entry 过滤”规则，而不是把它和 `300394` 一起塞进 penalty frontier。

---

## 8. 当前窗口最应该记住的判断顺序

如果你拿到一个新样本，不知道该把它归到哪一类，建议按这个顺序判断：

1. 它来自 `short_trade_boundary` 还是 `watchlist_filter_diagnostics`。
2. 它是入口结构弱，还是正式评分差一点。
3. 它是 `blocked` 还是 `rejected`。
4. 它的 penalty 是单项主导，还是多项叠加。
5. 它有没有 low-cost rescue row。

按这个顺序看，你通常能把新样本快速归到下面 4 个 archetype 之一：

1. 入口不该进来。
2. 入口可以，但 score frontier 还差一点。
3. 结构冲突可定向释放。
4. penalty / score construction 需要单独研究。

---

## 9. 一句话总结

当前窗口最大的价值，不是证明“某个参数更好”，而是把 BTST 的后续工作明确拆成三条互不混淆的主线：admission 默认保留 catalyst-only 扩覆盖，score frontier 继续做 `short_trade_boundary` 样本救援，structural conflict 只对 `300724` 做 case-based release，其余像 `300394`、`300502` 这样的样本继续分别回到 penalty 与 candidate-entry 语义路径。
