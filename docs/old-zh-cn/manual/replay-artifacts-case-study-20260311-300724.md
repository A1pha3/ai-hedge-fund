# Replay Artifacts 案例手册：2026-03-11 的 300724 为什么入选但未买入

## 1. 这份案例要解决什么问题

这份案例专门用一个真实样本说明最容易误解的一件事：

1. 为什么一只股票已经进入 selected 或 watchlist，最终却没有进入 buy_orders。

很多人看到“没有买单”就会直觉认为系统没选好股。这个案例要说明：在很多情况下，真实原因是执行层阻塞，而不是选股失败。

---

## 2. 案例上下文

本案例使用的 report 和 trade date：

1. report：`paper_trading_20260311_selection_artifact_blocker_validation_20260323`
2. trade date：`2026-03-11`

你在页面中的进入方式：

1. 登录 Web 界面。
2. 进入 `Settings -> Replay Artifacts`。
3. 选择上述 report。
4. 选择 `2026-03-11`。

---

## 3. 第一步先看运行概览

当日 review 的核心概览是：

1. `universe = 200`
2. `candidate_count = 200`
3. `high_pool_count = 1`
4. `watchlist_count = 1`
5. `buy_order_count = 0`

这五个数字的意思是：

1. 系统当天并不是完全没有候选。
2. 最终确实筛出了一只重点候选。
3. 但它没有落成 buy_order。

这一步已经足以说明问题不是“当天完全没筛到任何东西”，而是“筛到了，但没有承接到执行层”。

---

## 4. 第二步看今日入选股票

当日只有一只 selected：

1. `300724`

页面和 review 给出的关键信息包括：

1. `final_score = 0.2144`
2. `buy_order = no`
3. `buy_order_blocker = blocked_by_reentry_score_confirmation`
4. `reentry_review_until = 20260312`

这时你应该立刻形成一个中间结论：

1. 300724 已经通过研究层进入了当日重点候选。
2. 它没买入并不是因为“完全没被选中”。
3. 页面已经明确给出 blocker，说明问题更可能出在执行承接。

---

## 5. 第三步看 Layer B，确认它为什么被选出来

这只股票的 Layer B 摘要里有三类信息：

1. `logic_score: value = 0.2144`
2. `fundamental: weight = 0.4444`
3. `trend: weight = 0.3232`

同时页面还提示：

1. `explanation_source = legacy_plan_fields`
2. `fallback_used = true`

这里要怎么理解：

1. 它确实不是随机入选，而是有 Layer B 依据。
2. 这份依据来自历史 replay 的兼容回退字段，不是最原生的 strategy_signals。
3. 所以它能证明“为什么大致被选中”，但精细度比新数据源稍弱。

正确结论不是“证据无效”，而是：

1. 证据可用，但应偏保守解释。

---

## 6. 第四步看 Layer C，确认它不是纯噪声票

Layer C 概要里有几组很重要的数据：

1. `active_agent_count = 17`
2. `positive_agent_count = 4`
3. `negative_agent_count = 7`
4. `neutral_agent_count = 6`
5. `adjusted_score_c = 0.0002`

这说明什么：

1. 这只票不是“毫无覆盖”的空白对象。
2. 多个 agent 对它有判断。
3. 但分歧比较明显，并不是强共识票。

再看 top agents：

1. 正向里有 `cathie_wood_agent`、`fundamentals_analyst_agent`、`technical_analyst_agent`
2. 负向里有 `sentiment_analyst_agent`、`valuation_analyst_agent`、`bill_ackman_agent`

这意味着：

1. 支持它的理由存在。
2. 反对它的理由也不弱。
3. 它更像“值得继续看，但不能简单视为高确定性买入”的候选。

---

## 7. 第五步看 Execution Bridge，确认真正卡点

这一步是整份案例最关键的地方。

execution_bridge 中的核心字段是：

1. `included_in_buy_orders = false`
2. `planned_shares = 0`
3. `planned_amount = 0.0`
4. `target_weight = 0.0`
5. `block_reason = blocked_by_reentry_score_confirmation`
6. `blocked_until = 20260305`
7. `reentry_review_until = 20260312`
8. `exit_trade_date = 20260226`
9. `trigger_reason = hard_stop_loss`

这组信息的解释顺序应该是：

1. 它进入了研究候选，但并未进入执行单。
2. 原因不是分数为零，也不是没有入选。
3. 原因是再入场确认机制触发了阻塞。
4. 这次阻塞和此前的止损事件有关。
5. 系统要求到 `20260312` 之后再继续评估是否恢复承接。

所以最终判断是：

1. 这是“研究候选存在，但执行层暂不承接”的典型场景。

---

## 8. 第六步看 Funnel Drilldown，验证这不是单点解释

如果你只看 execution_bridge，仍然可能担心是不是某个字段解释失真。Funnel Drilldown 的价值在于给出第二份独立证据。

这个样本的关键 funnel 信息是：

1. `layer_b.filtered_count = 199`
2. `watchlist.filtered_count = 0`
3. `buy_orders.filtered_count = 1`

更重要的是，在 `buy_orders` 过滤明细中，`300724` 直接出现，并带有：

1. `reason = blocked_by_reentry_score_confirmation`
2. `score_final = 0.2144`
3. `required_score = 0.25`
4. `reentry_review_until = 20260312`
5. `trigger_reason = hard_stop_loss`
6. `exit_trade_date = 20260226`

这一步的意义是：

1. 你不再只是依赖 candidate 详情页里的 execution_bridge。
2. funnel 本身也独立证明：它卡在 buy_orders 这一层，而不是更早的 layer_b 或 watchlist 层。

这就让“问题出在执行承接”这个结论更稳了。

---

## 9. 第七步看 Research Prompts，确认人工复核应该关注什么

系统给出的 prompts 是：

### why_selected

1. `Layer B 综合分数为 0.3897`
2. `Layer C 综合分数为 0.0002`
3. `最终得分为 0.2144`

### what_to_check

1. `执行层未生成 buy_order，原因: blocked_by_reentry_score_confirmation`
2. `当前 Layer B 因子摘要来自历史回放兼容字段，需结合原始 plan 字段复核`

这两组 prompts 的价值在于：

1. 先提醒你它为什么值得看。
2. 再提醒你真正该质疑的点在哪里。

也就是说，系统并没有让你盲目把 300724 当成正面案例，而是明确把“执行阻塞”和“兼容回退解释”都作为人工复核重点。

---

## 10. 这条案例的正确结论是什么

如果把所有页面证据合起来，这个案例的正确结论应当是：

1. 300724 在 2026-03-11 确实被研究层筛成了重点候选。
2. 它不是“没有被选中”。
3. 它没有进入 buy_orders 的主因是执行层的 reentry 确认规则。
4. 因为存在历史回放兼容回退字段，Layer B 解释可用但需要保守解读。
5. 这更像一个“执行承接受限”的样本，而不是一个“选股彻底失败”的样本。

---

## 11. 如果你要写 feedback，应该怎么写

### 推荐主标签方向

这个案例更适合下列标签方向之一：

1. `weak_edge`
2. 自定义 verdict：`blocked_by_execution_not_selection`
3. 如果你更强调规则影响，也可以在 notes 中写清“研究通过但执行阻塞”

### 一个示例写法

1. `Primary Tag`: `weak_edge`
2. `Review Status`: `draft`
3. `Research Verdict`: `blocked_by_execution_not_selection`
4. `Notes`: `300724 已通过研究层筛选并进入 watchlist，但未生成 buy_order 的主因是 blocked_by_reentry_score_confirmation，不应简单归因为选股失败。Layer B 解释来自历史回放兼容字段，建议结合原始 plan 字段继续复核。`

---

## 12. 从这个案例学到什么

这条案例最重要的学习点只有三条：

1. `selected != buy_orders`
2. `没有买入 != 没有选中`
3. 要同时看 candidate 详情、execution_bridge 和 Funnel Drilldown，才能正确判断问题归因

如果你学会了这三点，就已经掌握了 Replay Artifacts 页面最关键的使用方法。

---

## 13. 建议下一步

看完这条案例后，建议你再做两件事：

1. 回到多日窗口 report，观察是否还有其他股票反复卡在 buy_orders 层。
2. 对比一条 `included_in_buy_orders = true` 的样本，看看“研究通过且执行承接”与本案例的差别。

配套文档：

1. 完整手册： [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
2. 速查版： [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)
3. 标签规范： [Replay Artifacts 研究反馈标签规范手册](./replay-artifacts-feedback-labeling-handbook.md)
