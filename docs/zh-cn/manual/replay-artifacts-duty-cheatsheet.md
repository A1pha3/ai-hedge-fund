# Replay Artifacts 值班速查卡

> 配套阅读：
>
> 1. [Replay Artifacts 分析报告术语解析手册](./replay-artifacts-report-terminology-guide.md)
> 2. [Replay Artifacts 选股复核 5 分钟速查](./replay-artifacts-stock-selection-quickstart.md)
> 3. [Replay Artifacts 新人培训讲义](./replay-artifacts-newcomer-training-guide.md)
> 4. [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
> 5. [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)

## 1. 这张卡最适合什么时候用

这张卡不是完整手册，而是给下面三类场景准备的：

1. 你已经打开了 Replay Artifacts 页面，但只有几分钟时间。
2. 你知道自己要判断一份 report，却不想再从头翻长文档。
3. 你需要先快速写出一句稳的结论，再决定要不要继续深挖。

如果你现在遇到的是“术语根本看不懂”，先回到 [Replay Artifacts 分析报告术语解析手册](./replay-artifacts-report-terminology-guide.md)。

## 2. 30 秒起手顺序

不要一上来就盯某只股票。

先按这个顺序看：

1. `selection_artifact_overview`
2. `blocker_counts`
3. `feedback_summary`
4. `cache_benchmark_overview`
5. 然后再下钻到具体 `selected` / `rejected` 样本

这 30 秒回答的是：

1. 这份 report 有没有可读样本。
2. 问题更像选股层、执行层、流程层，还是运行证据层。
3. 值不值得继续深挖到单只股票。

## 3. 遇到不同问题，先看哪里

### 3.1 候选为什么这么少

先看：

1. `selection_artifact_overview`
2. `funnel_diagnostics.filters.layer_b`
3. `reason_counts`

一句话判断：

1. 如果 Layer B 在前面就大量过滤，问题更像候选 scarcity，而不是 report 异常。

### 3.2 为什么进了 selected 却没买

先看：

1. `selected[*].execution_bridge`
2. `funnel_diagnostics.filters.buy_orders`
3. `block_reason`

一句话判断：

1. 如果 `selected` 已成立但 `included_in_buy_orders = false`，优先把它当成执行承接问题，而不是选股失败。

### 3.3 为什么差一点进 watchlist 但最终没进

先看：

1. `rejected[*].rejection_reason_codes`
2. `score_final`
3. 门槛相关 reason text

一句话判断：

1. 如果是贴着阈值线掉下去，它更像 near-miss，而不是彻底弱样本。

### 3.4 这份 report 现在是草稿状态，还是已经有稳定结论

先看：

1. `feedback_summary.feedback_count`
2. `feedback_summary.final_feedback_count`
3. `feedback_summary.review_status_counts`

一句话判断：

1. `final_feedback_count` 上来之后，才说明这份 report 不再只是零散草稿。

### 3.5 为什么 workflow 里出现 `ready_for_adjudication`

先看：

1. `latest_review_status`
2. `workflow_status`
3. `assignee`

一句话判断：

1. 这是流程成熟度信号，不是交易信号。

### 3.6 cache benchmark 到底有没有真实执行

先看：

1. `data_cache_benchmark_status.requested`
2. `executed`
3. `write_status`
4. `reason`

一句话判断：

1. 页面能显示 cache benchmark，不代表这次运行一定真的写出了 benchmark 结果。

### 3.7 缓存复用是不是已经被证明成立

先看：

1. `reuse_confirmed`
2. `first_hit_rate`
3. `second_hit_rate`
4. `disk_hit_gain`

一句话判断：

1. 这证明的是本次验证通过，不是未来永远命中缓存。

## 4. 最短结论模板

### 4.1 report 级一句话

1. 这份 report 属于“`[主要类型]`”样本，核心证据是 `[`字段 A` + `字段 B` + `字段 C`]`，因此当前更应该把它读成“`[正确结论]`”，而不是“`[常见误判]`”。

### 4.2 单只样本一句话

1. `[`trade_date` / `symbol`]` 在 `[`字段组合`]` 上表现为 `[`事实`]`，因此它更接近“`[正确归类]`”，而不是“`[错误归类]`”。

### 4.3 周度复盘一句话

1. 本周重复出现的现象是 `[`重复模式`]`，主要证据来自 `[`聚合字段`]` 与 `[`代表样本字段`]`，因此下一步更适合进入 `[`final / ready_for_adjudication / backlog mapping`]`。

## 5. 最容易写错的三种句子

### 5.1 错句一

1. 没进 `buy_orders`，说明系统不会选股。

改成：

1. 该样本已进入研究重点，但执行层因 blocker 暂未承接，因此当前更支持“执行保护生效”，而不是“选股失败”。

### 5.2 错句二

1. `ready_for_adjudication`，说明系统建议重点买入。

改成：

1. `ready_for_adjudication` 说明该样本已具备进入更高层复核的成熟度，但不等同于交易建议。

### 5.3 错句三

1. `reuse_confirmed = true`，说明缓存问题已经永久解决。

改成：

1. 当前 benchmark 样本中缓存复用验证成立，但后续仍应按运行条件持续观察。

## 6. 写结论前先问自己三件事

1. 我现在写的是研究层、执行层，还是工作流层结论。
2. 我引用的是单条样本字段，还是 report 级聚合字段。
3. 我写的是事实判断、流程判断，还是投资判断。

只要这三问答不稳，这句话就先不要发出去。

## 7. 什么时候该离开这张卡，去看长文档

出现下面任一情况，就不要继续只靠速查卡：

1. 你发现自己已经分不清 `selected`、`watchlist`、`buy_orders` 的层级。
2. 你发现自己把 `review_status`、`workflow_status`、`ready_for_adjudication` 混成一件事。
3. 你需要系统解释某类术语为什么存在，而不是只想知道先看哪里。
4. 你要把周度复盘结论转成 backlog。

对应入口：

1. 术语与误判： [Replay Artifacts 分析报告术语解析手册](./replay-artifacts-report-terminology-guide.md)
2. 新人带教路径： [Replay Artifacts 新人培训讲义](./replay-artifacts-newcomer-training-guide.md)
3. 页面完整使用： [Replay Artifacts 选股复核页面使用手册](./replay-artifacts-stock-selection-manual.md)
4. 周度复盘： [Replay Artifacts 周度复盘工作流手册](./replay-artifacts-weekly-review-workflow.md)
5. 结论落 backlog： [研究结论到优化 Backlog 的转换手册](./research-conclusion-to-optimization-backlog-handbook.md)
