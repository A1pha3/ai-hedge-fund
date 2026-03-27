# Execution Bridge 一页速查卡

适用对象：在 report、selection_review 或 daily_events 里快速判断“这只票为什么没下单”的读者。

---

## 1. 一句话定义

Execution Bridge 负责把 watchlist 样本转成 buy order，核心问题不是“会不会选”，而是“今天能不能买”。

---

## 2. 先记住的 6 件事

1. 进入 watchlist 不等于进入 buy order。
2. `included_in_buy_orders` 是 execution 是否承接的第一信号。
3. `position_blocked_score` 表示综合分数已够研究层通过，但还没强到执行层愿意给仓位。
4. `position_blocked_single_name` 更像组合结构问题，不是单票 thesis 失败。
5. `blocked_by_exit_cooldown` 和 `blocked_by_reentry_score_confirmation` 是时序问题，不是研究层否定。
6. 复盘执行问题时，先看 blocker，再决定该改研究层还是执行层。

---

## 3. 最核心的字段

| 字段 | 它在回答什么 | 复盘时怎么用 |
| --- | --- | --- |
| `included_in_buy_orders` | 执行层有没有承接 | 先分“会选但不买”和“已准备买” |
| `planned_shares` | 计划买多少股 | 看执行厚度是否偏薄 |
| `planned_amount` | 计划买入金额 | 看仓位承接强弱 |
| `block_reason` | 为什么没进入 buy order | 先分类问题类型 |
| `blocked_until` | 冷却期到哪天 | 看是不是短期时序约束 |
| `reentry_review_until` | 再确认窗口到哪天 | 看是否需要更高确认分数 |

---

## 4. 最常见 blocker 速查

| blocker | 直观含义 | 应先怀疑什么 |
| --- | --- | --- |
| `position_blocked_score` | watchlist 过了，但 execution floor 没过 | 共识厚度不足，或执行分数门槛过高 |
| `position_blocked_single_name` | 单票仓位约束命中 | 组合已持有、单名额上限 |
| `blocked_by_exit_cooldown` | 退出后冷却期未过 | 不应立刻回补 |
| `blocked_by_reentry_score_confirmation` | 再入场仍需更高确认 | thesis 还在，但当前确认不足 |

---

## 5. 执行层分数档位速查

默认参数来自 [src/portfolio/position_calculator.py](../../../src/portfolio/position_calculator.py)：

1. `WATCHLIST_MIN_SCORE = 0.225`
2. `STANDARD_EXECUTION_SCORE = 0.25`
3. `FULL_EXECUTION_SCORE = 0.50`
4. `WATCHLIST_EDGE_EXECUTION_RATIO = 0.3`

最小理解：

1. `score_final < 0.225`，不给执行仓位。
2. `0.225 ~ 0.25`，只给 edge execution。
3. `0.25 ~ 0.50`，给标准执行厚度。
4. `> 0.50`，给 full execution。

---

## 6. 最小复盘顺序

1. 先确认它是否进入 watchlist。
2. 再看 `included_in_buy_orders`。
3. 如果没有，立即看 `block_reason`。
4. 再看 `blocked_until / reentry_review_until / exit_trade_date`。
5. 最后看 `planned_shares / planned_amount / target_weight`。

---

## 7. 最常见误判

1. selected 就等于系统建议买入。
2. `position_blocked_score` 等于 Layer C 否决。
3. `position_blocked_single_name` 等于这只票质量差。
4. cooldown / reentry blocker 等于 thesis 被推翻。

---

## 8. 需要深入时看哪里

1. 长文版：[24-execution-bridge-professional-guide.md](./24-execution-bridge-professional-guide.md)
2. 跨层复盘：[22-layer-b-c-joint-review-manual.md](./22-layer-b-c-joint-review-manual.md)
3. Layer C 速查：[19-layer-c-one-page-cheatsheet.md](./19-layer-c-one-page-cheatsheet.md)
4. 执行分数门槛样本复盘：[../analysis/execution-score-floor-review-20260324.md](../analysis/execution-score-floor-review-20260324.md)
