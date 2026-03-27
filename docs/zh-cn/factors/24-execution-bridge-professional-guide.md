# Execution Bridge 专业讲解：从 watchlist 到 buy order 到实际承接

适用对象：已经理解 Layer B、Layer C 和 watchlist，但在复盘时还需要回答“为什么通过了研究层却没买”的开发者、研究者、复盘人员。

这份文档解决的问题：

1. Execution Bridge 在整个链路里到底负责什么。
2. 为什么 selected 或 watchlist 不等于一定会有 buy order。
3. `position_blocked_score`、`position_blocked_single_name`、`blocked_by_exit_cooldown`、`blocked_by_reentry_score_confirmation` 各自代表什么。
4. 真实复盘中，怎样区分“选股失败”和“执行未承接”。

建议搭配阅读：

1. [Layer C 策略完全讲解](./16-layer-c-complete-beginner-guide.md)
2. [Layer C 一页速查卡](./19-layer-c-one-page-cheatsheet.md)
3. [Layer B / Layer C 联动复盘手册](./22-layer-b-c-joint-review-manual.md)
4. [Execution Score Floor 复盘 2026-03-24](../analysis/execution-score-floor-review-20260324.md)
5. [Replay Artifacts 选股复核操作手册](../manual/replay-artifacts-stock-selection-manual.md)

---

## 1. 一句话定义

Execution Bridge 是 watchlist 和实际 buy order 之间的承接层。它不再回答“值不值得研究”，而是回答“在当前持仓、现金、仓位约束和再入场规则下，今天到底能不能买”。

---

## 2. 为什么这层必须单独看

很多复盘会在 selected 或 watchlist 就停住，然后直接把“没有下单”归因到 Layer B 或 Layer C。这会造成一个很常见的误判：

1. 研究层已经通过。
2. 但执行层没有承接。
3. 最终却被误写成“选股逻辑失败”。

Execution Bridge 的存在，就是为了把这两个问题拆开。

更直白地说：

1. Layer B / Layer C 负责会不会选。
2. Execution Bridge 负责会不会买。

---

## 3. 先把最小链路看清楚

跨层最小流程如下：

```text
score_b
  -> Layer C 聚合
  -> watchlist
  -> execution_bridge
  -> buy_orders
  -> T+1 execution
```

这条链路里，Execution Bridge 做的是两类事：

1. 读取研究层已经给出的 `score_final`、quality 相关信息和 selected/watchlist 结果。
2. 结合执行层自己的仓位、现金、单名额、流动性、行业约束、冷却与 reentry 规则，决定是否真正形成 buy order。

所以它天然不是 Layer C 的附庸，而是一道独立闸门。

---

## 4. Execution Bridge 主要看哪些字段

复盘时最关键的是这些字段：

1. `included_in_buy_orders`
2. `planned_shares`
3. `planned_amount`
4. `target_weight`
5. `block_reason`
6. `blocked_until`
7. `reentry_review_until`
8. `exit_trade_date`
9. `trigger_reason`

这些字段回答的分别是：

1. 它有没有真的进入 buy order。
2. 如果进入了，系统准备买多少。
3. 如果没进入，是哪条执行规则拦住了它。
4. 这种阻塞是短期冷却，还是更结构性的仓位 / 分数 / 风控约束。

---

## 5. 执行层最核心的第一道门：score floor

当前执行层最重要的硬门槛之一在 [src/portfolio/position_calculator.py](../../../src/portfolio/position_calculator.py) 里。

默认参数：

1. `WATCHLIST_MIN_SCORE = 0.225`
2. `STANDARD_EXECUTION_SCORE = 0.25`
3. `FULL_EXECUTION_SCORE = 0.50`
4. `WATCHLIST_EDGE_EXECUTION_RATIO = 0.3`

最关键的第一道判断是：

1. `score_final < WATCHLIST_MIN_SCORE` 时，直接返回 `constraint_binding = score`、`shares = 0`。

这意味着：

1. 一只票即使已经进入 watchlist，也可能因为执行层的最小分数门槛不够而拿不到任何仓位。
2. `position_blocked_score` 不是一个模糊的“综合不通过”，而是一条很具体的执行层硬门槛。

---

## 6. 当前执行层分数档位怎么工作

Execution Bridge 对 `score_final` 的直观分层可以近似理解为：

1. `score_final < 0.225`：不给执行仓位。
2. `0.225 <= score_final < 0.25`：允许 watchlist edge execution ratio。
3. `0.25 <= score_final <= 0.50`：进入标准执行比率。
4. `score_final > 0.50`：进入 full execution ratio。

然后它还会再乘上一层 quality 调整，这意味着：

1. 执行层不只看有没有过线。
2. 还会根据质量语境决定边缘票到底给多少仓位厚度。

所以 execution 不是“有或无”二元判断，它内部还有强弱层次。

---

## 7. 四类最常见的 blocker

### 7.1 `position_blocked_score`

语义：

1. 研究层已经允许它进入 watchlist。
2. 但执行层认为 `score_final` 仍低于最小可执行门槛。

这类 blocker 最容易被误读，因为：

1. 它看起来像执行问题。
2. 但本质上也在提示“研究层厚度还不够强”。

更准确的理解是：

1. 它不是 Layer C 明确反对。
2. 它是 B/C 综合共识已经通过 watchlist，但还没强到足以承接成仓位。

### 7.2 `position_blocked_single_name`

语义：

1. 样本本身可能没有问题。
2. 但当前组合在单票维度已经接近或达到上限。

这类 blocker 强调的是组合结构，而不是样本质量。

### 7.3 `blocked_by_exit_cooldown`

语义：

1. 该票刚经历某类退出。
2. 仍处于冷却期内。

这类 blocker 表明当前不是“永远不能买”，而是“今天不能立刻回补”。

### 7.4 `blocked_by_reentry_score_confirmation`

语义：

1. 冷却窗口后期允许重新审视。
2. 但在 `reentry_review_until` 之前，它还需要达到更高确认分数。

这类 blocker 的重点不是否定 thesis，而是要求更强确认。

---

## 8. Execution Bridge 最容易被误判的地方

### 8.1 把 `selected` 直接当成“已建议买入`

`selected` 只说明研究层通过，不等于 buy order 已成立。

### 8.2 把 `position_blocked_score` 当成纯执行噪声

它虽然发生在执行层，但会暴露研究共识厚度仍偏边缘。

### 8.3 把 `position_blocked_single_name` 误读成选股弱

它更多反映组合拥挤度，而不是单票质量。

### 8.4 把 reentry blocker 误写成“系统否定这只票”

这类 blocker 常常意味着系统仍认可样本，只是要求等待时间或二次确认。

---

## 9. 三类最常见的 execution bridge 样本

### 9.1 研究通过但厚度不够样本

特征：

1. `included_in_buy_orders = false`
2. `block_reason = position_blocked_score`

这类样本最重要的判断是：

1. 不是 Layer C 完全拒绝。
2. 而是综合厚度没强到执行层愿意承接仓位。

### 9.2 研究通过但组合结构不允许样本

特征：

1. `block_reason = position_blocked_single_name`
2. 或出现 cash / vol / industry 相关约束

这类样本更适合放到仓位与风险规则里解释。

### 9.3 thesis 仍在，但短期不允许回补样本

特征：

1. `blocked_by_exit_cooldown`
2. `blocked_by_reentry_score_confirmation`
3. 带有 `blocked_until` 或 `reentry_review_until`

这类样本反映的是时序约束，不是研究层否决。

---

## 10. 真实窗口给出的关键证据

当前仓库里已经有几类非常关键的 execution 侧证据。

### 10.1 `600988` 是比较干净的 execution floor 样本

在 [docs/zh-cn/analysis/execution-score-floor-review-20260324.md](../analysis/execution-score-floor-review-20260324.md) 中，`2026-03-05 / 600988` 给出了最干净的例子：

1. 已经进入 watchlist。
2. 原始阻塞是 `position_blocked_score`。
3. 当 `PIPELINE_WATCHLIST_MIN_SCORE` 从 `0.225` 放到 `0.21` 后，可以转成最小 lot buy order。

这说明 execution floor 的确会决定边缘票能否真正变成买单。

### 10.2 `300724` 说明同一个样本可能叠加多种 blocker

`300724` 在不同日期的样本说明：

1. 有时表面 blocker 是 `position_blocked_score`。
2. 但在真实价格和实际持仓上下文下，可能进一步切换成 `position_blocked_single_name`。

这提醒复盘时不要只看第一层原因码，而要看真实持仓与执行上下文。

### 10.3 reentry blocker 说明“会选”不等于“今天会买”

`blocked_by_reentry_score_confirmation` 这类样本说明：

1. 研究链路认可这只票仍值得看。
2. 但执行链路要求在一定时间窗内等待更强确认。

---

## 11. 复盘 execution bridge 的最小顺序

建议按下面 6 步走。

### 11.1 先确认它是否进入 watchlist

如果没进 watchlist，就不要先讨论 execution。

### 11.2 再看 `included_in_buy_orders`

这是 execution 是否承接的第一信号。

### 11.3 如果没承接，优先看 `block_reason`

这是第一层原因分类。

### 11.4 再看时间类字段

优先看：

1. `blocked_until`
2. `reentry_review_until`
3. `exit_trade_date`

用来区分长期结构性约束和短期冷却。

### 11.5 再看仓位厚度

优先看：

1. `planned_shares`
2. `planned_amount`
3. `target_weight`

有时问题不是完全挡掉，而是执行厚度偏薄。

### 11.6 最后才判断应该改哪层

结论通常落在三种之一：

1. 应该改 B/C 厚度，而不是执行层。
2. 应该改 execution floor 或持仓约束，而不是研究层。
3. 当前只是 reentry / cooldown 时序，不应草率下调任何阈值。

---

## 12. 调参时最容易犯的 4 个错误

### 12.1 看见 blocker 就直接下调执行门槛

如果 blocker 的根因其实是研究厚度不足，直接放低 execution floor 可能只是在买更多边缘票。

### 12.2 只看 `position_blocked_score`，不看是否还有叠加约束

例如单票上限、已有持仓、真实价格口径下的最小 lot 约束，都可能把同一样本推到不同 blocker。

### 12.3 把 reentry 问题混进选股调参

这会让 Layer B / C 的调参结论失真。

### 12.4 只看 buy order 数，不看 blocker 分布

同样的 buy order 数变化，可能来自完全不同的执行机制变化。

---

## 13. 一句话总结

Execution Bridge 的核心价值，是把“研究通过”与“执行承接”拆开。复盘时，只有先确认 blocker 是分数门槛、组合约束还是再入场时序，才知道后续该改 Layer B / C、execution floor，还是根本不该动参数。
