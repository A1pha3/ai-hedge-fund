# Execution Score Floor 复盘 2026-03-24

## 1. 目标

这份文档只回答一个问题：

- `position_blocked_score` 到底是在拦低质量噪声，还是在误伤已经通过 watchlist 的边缘候选？

## 2. 代码事实

执行层硬阈值位于：

- `src/portfolio/position_calculator.py`

默认参数：

1. `WATCHLIST_MIN_SCORE = 0.225`
2. `STANDARD_EXECUTION_SCORE = 0.25`
3. `FULL_EXECUTION_SCORE = 0.50`
4. `WATCHLIST_EDGE_EXECUTION_RATIO = 0.3`

`calculate_position()` 的第一道硬判断是：

```python
if current_price <= 0 or portfolio_nav <= 0 or score_final < WATCHLIST_MIN_SCORE:
    return PositionPlan(... constraint_binding="score", shares=0, execution_ratio=0.0)
```

这意味着：

1. `position_blocked_score` 不是现金、流动性或行业约束的复合结果。
2. 它首先是一个“是否达到最小执行分数”的硬门槛。

## 3. 当前样本证据

### 3.1 已观测到的 blocker 样本

在当前窗口内，明确被 `position_blocked_score` 阻塞且可定位的典型样本有：

1. `2026-03-23 / 300724 / score_final=0.2110`
2. `2026-03-05 / 600988 / score_final=0.2170`

这两个样本都有共同点：

1. 已经进入 watchlist
2. `bc_conflict=None`
3. 最终没有转成 buy_order
4. 分数都落在 `0.21~0.225` 之间

这说明当前 execution floor 拦住的并不只是明显低质量或强冲突票，其中至少包含一类“非冲突边缘样本”。

但这个结论在进入固定样本重放后需要再细分：

1. `600988` 确实是 execution floor 样本。
2. `300724` 在 `2026-03-23` 这一天虽然原始原因显示为 `position_blocked_score`，但在使用真实价格 `128.41` 重放后，阻塞原因会切换为 `position_blocked_single_name`，说明它还叠加了“已有持仓下的单名额约束”。

### 3.2 `fast_0375` fresh rerun 的配套证据

前一轮 fresh rerun 已确认：

1. `2026-03-04 / 300724` 在 `fast_0375` 下可以进入 buy_order
2. `2026-03-05 / 600988` 在 `fast_0375` 下可以进入 watchlist，但会被 `position_blocked_score` 挡住

这说明 execution floor 正在决定“边缘释放能否最终形成可执行仓位”。

## 4. 本轮新增实现

2026-03-24 已将 execution 分数档位改为环境变量可配置，默认值保持不变：

1. `PIPELINE_WATCHLIST_MIN_SCORE`
2. `PIPELINE_STANDARD_EXECUTION_SCORE`
3. `PIPELINE_FULL_EXECUTION_SCORE`
4. `PIPELINE_WATCHLIST_EDGE_EXECUTION_RATIO`

当前代码默认仍等价于：

1. `0.225`
2. `0.25`
3. `0.50`
4. `0.3`

## 5. 验证结果

### 5.1 直接公式验证

对 `600988 / score_final=0.2170 / current_price=20 / nav=100000 / available_cash=33333`：

默认阈值：

1. `constraint_binding=score`
2. `shares=0`
3. `execution_ratio=0.0`

当 `PIPELINE_WATCHLIST_MIN_SCORE=0.21`：

1. `constraint_binding=single_name`
2. `shares=100`
3. `execution_ratio=0.3`

这说明：

1. `600988` 并不是因为现金或流动性约束被挡住。
2. 它是被 `0.225` 这条硬执行分数门槛挡住。

### 5.2 定向测试验证

已新增并通过的直接相关测试：

1. `tests/portfolio/test_phase3_portfolio.py::test_watchlist_min_score_can_be_lowered_via_env`
2. `tests/execution/test_phase4_execution.py::test_build_buy_orders_allows_edge_watchlist_name_when_execution_score_floor_is_lowered`
3. `tests/execution/test_phase4_execution.py::test_build_buy_orders_blocks_watchlist_name_below_buy_threshold_sample`

定向执行结果：`3 passed`

### 5.3 固定样本探针复跑

使用修复后的 `scripts/probe_execution_buy_orders.py` 重新验证后，旧版探针里默认回退到 `10.0` 的假价格问题已被排除。

#### 样本 A: `2026-03-23 / 300724`

输入条件：

1. 使用事件内真实价格 `128.41`
2. `PIPELINE_WATCHLIST_MIN_SCORE=0.21`
3. 组合中已存在 `300724` 持仓 `100` 股

复跑结果：

1. 原始结果：`position_blocked_score`
2. 重算后：仍然不进入 `buy_orders`
3. 新阻塞原因：`position_blocked_single_name`

这说明：

1. `300724` 在这一天并不能作为“只被 execution floor 挡住”的纯样本。
2. 一旦把价格修正到真实值，`0.21` 只会把它从 score blocker 推进到 single-name blocker，而不会真正出票。

#### 样本 B: `2026-03-05 / 600988`

输入条件：

1. 使用真实价格覆盖 `600988=40.34`
2. `PIPELINE_WATCHLIST_MIN_SCORE=0.21`
3. 组合为空仓

复跑结果：

1. 原始结果：`position_blocked_score`
2. 重算后：进入 `buy_orders`
3. `shares=100`
4. `amount=4034.0`
5. `constraint_binding=single_name`

这说明：

1. `600988` 才是当前最干净的 execution floor 边缘释放样本。
2. 在真实价格口径下，把 floor 从 `0.225` 放到 `0.21`，确实会把它从“0 股”变成“最小 lot 可执行买单”。

### 5.4 三样本一致性补强

在完成探针价格解析修复后，又补跑了两组同方法 fixed-sample repriced probe，得到与 `600988` 一致的结果。

#### 样本 C: `2026-02-06 / 300724`

输入条件：

1. 来源文件：`data/reports/fresh_rerun_20260206_fast_0375_20260324/daily_events.jsonl`
2. 使用真实价格覆盖 `300724=129.59`
3. `PIPELINE_WATCHLIST_MIN_SCORE=0.21`
4. 组合为空仓

复跑结果：

1. 原始结果：`position_blocked_score`
2. 样本分数：`score_final=0.2127`
3. 重算后：进入 `buy_orders`
4. `shares=100`
5. `amount=12959.0`

这说明：

1. `300724 / 2026-02-06` 是一个干净的 execution floor 边缘样本。
2. 它与 `600988 / 2026-03-05` 一样，原始阻塞点就是 `0.225` 这条硬门槛。

#### 样本 D: `2026-02-25 / 300724`

输入条件：

1. 来源文件：`data/reports/paper_trading_20260224_20260227_logic_scores_live_seed/daily_events.jsonl`
2. 使用真实价格覆盖 `300724=123.60`
3. `PIPELINE_WATCHLIST_MIN_SCORE=0.21`
4. 组合为空仓

复跑结果：

1. 原始结果：`position_blocked_score`
2. 样本分数：`score_final=0.2242`
3. 重算后：进入 `buy_orders`
4. `shares=100`
5. `amount=12360.0`

这说明：

1. `2026-02-25 / 300724` 也满足“空仓、非额外单名额约束、只差 execution floor”的判定标准。
2. 即使这组样本来自较早的 logic-seed 工件，它仍然和另外两组样本给出了同方向证据。

#### 三样本合并判断

截至目前，已成立的固定样本证明链是：

1. `300724 / 2026-02-06 / score_final=0.2127`
2. `300724 / 2026-02-25 / score_final=0.2242`
3. `600988 / 2026-03-05 / score_final=0.2170`

三组样本共同满足：

1. 原始阻塞原因都是 `position_blocked_score`
2. 样本处于空仓上下文
3. 使用真实价格重放后，在 `0.21` 下都能转成 100 股最小 lot 买单

因此，当前证据已经从“单样本成立”升级为“三样本一致成立”。

### 5.5 短窗口实验配置 sanity check

为了避免结论只停留在固定样本重放，又补跑了一个最小 live pipeline 短窗口：

1. 时间窗：`2026-03-04 ~ 2026-03-06`
2. 上游阈值：`DAILY_PIPELINE_FAST_SCORE_THRESHOLD=0.375`
3. 对比组 A：`PIPELINE_WATCHLIST_MIN_SCORE=0.225`
4. 对比组 B：`PIPELINE_WATCHLIST_MIN_SCORE=0.21`

这个窗口有两个价值：

1. `2026-03-04` 会先生成 `300724` 的计划，并在 `2026-03-05` 实际执行，能验证实验配置不会破坏已成立的交易。
2. `2026-03-05` 当天同时出现 `600988` 这类边缘样本，能继续观察它是否会在 `2026-03-06` 真实成交。

#### 对比结果

共同部分：

1. 两组在 `2026-03-04` 都为 `300724` 生成 buy_order。
2. 两组在 `2026-03-05` 都实际买入 `300724` 100 股。
3. 说明实验配置没有扰乱这条已经成立的交易路径。

差异部分：

1. 默认组 `0.225`：
    - `2026-03-05 / 600988 / score_final=0.2134`
    - 当天被 `position_blocked_score` 挡住
    - `2026-03-06` 没有 `600988` 实际成交
2. 实验组 `0.21`：
    - `2026-03-05 / 600988 / score_final=0.2149`
    - 当天生成 buy_order：`shares=100`、`amount=4034.0`
    - `2026-03-06` 实际成交：`executed_trades.600988=100`

窗口结束时的组合状态：

1. 默认组：只持有 `300724`，`cash=88540.87`，`gross_exposure=11392.0`
2. 实验组：持有 `300724 + 600988`，`cash=84533.89`，`gross_exposure=15386.0`

这说明：

1. `0.21` 在真实 T+1 运行路径中，确实会把 `600988` 从“边缘 watchlist 候选”推进为“次日真实成交”。
2. 这次变化符合预期边界，只额外新增了一笔最小 lot 小仓买单，而不是把整个窗口的交易行为打乱。
3. 但该窗口太短，且期末净值差异只反映一笔新增仓位的即时 mark-to-market，不具备收益统计意义，不能据此宣称 `0.21` 更优。

## 6. 方法边界

### 6.1 为什么 fresh rerun 不能隔离 execution floor

如果直接做 live fresh rerun：

1. 上游 Layer B / Layer C / watchlist 会重新生成
2. LLM 输出具有非确定性
3. 样本可能在 rerun 中直接换成另一只票，无法保证是在同一个 watchlist 样本上比较 execution rule

本轮就出现了这种情况：

1. `2026-03-05 fast_0375` 初次 fresh rerun 中 `600988` 为 `watchlist=1 / buy_order=0`
2. 当联合设置 `PIPELINE_WATCHLIST_MIN_SCORE=0.21` 再做一次 fresh rerun 时，上游结果漂移，`600988` 反而变成 `score_final=0.1990` 的 watchlist 落选样本

所以这条路径不能拿来做 execution floor 的纯隔离验证。

### 6.2 为什么 frozen current_plan replay 也不能隔离 execution floor

当前 frozen replay 在 `src/execution/daily_pipeline.py::_apply_frozen_buy_order_filters()` 中：

1. 复用历史 `plan.buy_orders`
2. 只对已有 `buy_orders` 重放 reentry / cooldown 过滤
3. 不会重新执行 `calculate_position()`

因此它适合验证：

1. `blocked_by_exit_cooldown`
2. `blocked_by_reentry_score_confirmation`

但不适合验证：

1. `position_blocked_score`
2. `position_blocked_single_name`
3. `filtered_by_daily_trade_limit`

## 7. 当前可成立的结论

基于代码、测试和样本三层证据，当前可以成立的结论是：

1. `position_blocked_score` 的核心机制就是 `WATCHLIST_MIN_SCORE=0.225` 硬门槛。
2. 这条线会拦住至少一类非冲突边缘票，其中 `600988(0.217)` 已经通过真实价格固定样本复跑确认。
3. `300724(0.211)` 不能再被简单归类为 execution floor 样本，因为在真实价格口径下它还会被 `position_blocked_single_name` 继续挡住。
4. 把执行分数门槛做成可配置是合理的，因为它确实控制了边缘票能否形成最小 lot 买单。
5. 在剔除 `2026-03-23 / 300724` 这种混入单名约束的伪纯样本后，当前已经有三组 fixed-sample repriced probe 连续成立，证据强度已足够支持“把 `0.21` 提升为实验配置候选”。
6. 最小 live pipeline 短窗口也已观察到 `0.21` 会把 `600988` 这类边缘样本推进到 T+1 实际成交，说明该配置不只是 probe 内成立，而是能沿真实执行时序落地。
7. 但这些证据仍然不足以完成端到端收益、回撤、换手和集中度验证，因此不应直接改默认值。

## 8. 下一步建议

最小且稳妥的下一步应是：

1. 保持当前默认值 `0.225` 不变
2. 将 `0.21` 明确标记为“实验配置候选”，只在受控窗口下运行
3. 下一轮应把实验窗口从 3 天扩到更长交易窗，继续观察交易数、持仓集中度、回撤和失败样本结构，而不是只看是否多出买单
4. 继续把固定样本探针作为主证明链，把 live fresh rerun 作为“sanity check + 行为确认”补充，而不是默认值调整的唯一依据
