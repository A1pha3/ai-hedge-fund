# Replay Artifacts 选股复核 5 分钟速查

## 1. 这页最适合干什么

这页最适合做三件事：

1. 快速看某次运行当天到底选了谁。
2. 判断问题出在选股层，还是执行层。
3. 把你的人工结论写成 feedback。

不要把它当成“自动告诉你今天立即买什么”的页面。它更像研究复核页。

---

## 2. 最短操作路径

1. 登录后进入 `Settings -> Replay Artifacts`。
2. 选一个 `selection_artifact_overview.available = true` 的 report。
3. 选一个 trade date。
4. 看 `Selected Candidates`。
5. 看 `Execution Bridge`。
6. 看 `Funnel Drilldown`。
7. 写 feedback。

如果你只有 5 分钟，这就是最短可用流程。

---

## 3. 每一步看什么

### 第一步：选 report

优先选：

1. 有 selection artifacts。
2. 有 trade date。
3. 最好有 blocker。

推荐先看：

1. `paper_trading_20260311_selection_artifact_blocker_validation_20260323`
2. `paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323`

### 第二步：选 trade date

为什么必须先选日期：

1. 这个系统是按交易日做决策的。
2. 同一只股票不同日期状态可能完全不同。

### 第三步：看 Selected Candidates

重点看：

1. `score_final`
2. `layer_b_summary.top_factors`
3. `layer_c_summary`

这里回答的是：

1. 这只票为什么被选出来。
2. 它的研究逻辑是否清楚。

### 第四步：看 Execution Bridge

重点看：

1. `included_in_buy_orders`
2. `block_reason`
3. `reentry_review_until`
4. `trigger_reason`

这里回答的是：

1. 这只票只是值得研究。
2. 还是已经能进入执行层。

判断规则：

1. `included_in_buy_orders = true`，更接近可执行候选。
2. `included_in_buy_orders = false`，说明可能是执行层阻塞，不一定是选股失败。

### 第五步：看 Funnel Drilldown

重点看三层：

1. `layer_b`
2. `watchlist`
3. `buy_orders`

它回答的是：

1. 股票大多卡在哪一层。
2. 问题更像阈值问题、研究问题还是执行问题。

### 第六步：写 feedback

最简单的写法：

1. `Primary Tag` 选主结论。
2. `Review Status` 先用 `draft`。
3. `Notes` 写一句你为什么这么判断。

---

## 4. 你应该如何快速下结论

把股票分三类：

1. 执行优先股
   已在 selected，且 `included_in_buy_orders = true`。
2. 研究优先股
   已在 selected，但被执行层 blocker 拦住。
3. 谨慎或淘汰
   分数低、共识差、理由不清或风险太强。

---

## 5. 最常见误区

1. `selected` 不等于建议立刻买入。
2. 没进 `buy_orders` 不等于选股失败。
3. 只看分数，不看 blocker 和共识，很容易误判。
4. 不写 feedback，等于这次人工判断没有沉淀价值。

---

## 6. 如果你要继续深入

1. 完整操作与原理说明： [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
2. 标签怎么打得一致： [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)
3. 团队怎么做周度复盘： [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)
4. 真实案例拆解： [Replay Artifacts 案例手册：2026-03-11 的 300724 为什么入选但未买入](./replay-artifacts-case-study-20260311-300724.md)
