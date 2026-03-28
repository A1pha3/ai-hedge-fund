# Paper Trading 时序专题：T 日计划、pending plan 与 T+1 执行口径

文档日期：2026 年 3 月 28 日  
适用范围：paper trading runtime、live pipeline 日级复盘、frozen current plan replay 判读、Replay Artifacts 日级事件理解  
文档定位：代码语义专题文档，专门解释 T 日 post-market 计划生成、pending plan 沿用、T+1 执行与 `executed_trades` 持久化口径

建议搭配阅读：

1. [Execution Bridge 专业讲解](./24-execution-bridge-professional-guide.md)
2. [Execution Bridge 一页速查卡](./25-execution-bridge-one-page-cheatsheet.md)
3. [Layer B / Layer C 联动复盘手册](./22-layer-b-c-joint-review-manual.md)
4. [选股优先优化方案实施设计文档](../product/arch/arch_optimize_implementation.md)
5. [Replay Artifacts 选股复核操作手册](../manual/replay-artifacts-stock-selection-manual.md)

---

## 1. 这份文档要解决什么问题

在当前 paper trading 链路里，最容易被误读的不是 Layer B 或 Layer C，而是日级事件本身的时序含义。

尤其是下面这些问题，经常会被混在一起：

1. `current_plan` 到底是“今天执行的计划”，还是“今天生成、明天执行的计划”。
2. `prepared_plan` 和 `pending_plan` 到底是什么关系。
3. 为什么同一条 `paper_trading_day` 事件里，既有 `executed_trades`，又有新的 `current_plan`。
4. `executed_trades` 为什么不是 `executed_orders`。
5. frozen current plan replay 到底回放的是哪一天生成的计划。

这份文档的目标，就是把这些时序口径彻底拆开。

---

## 2. 先说结论

如果只保留最重要的判断，请记住下面 10 条：

1. 当前 paper trading engine 的核心时序是：T 日 post-market 生成计划，T+1 交易日执行这份 pending plan。
2. 这里的 T+1 指下一个交易日，不一定是下一个自然日。
3. `current_plan` 表示“当前 trade_date 收盘后新生成的计划”，默认供下一个交易日使用。
4. `pending_plan` 是 engine 在循环间保存的“待执行计划”变量，也是 checkpoint 里真正续跑的计划对象。
5. `prepared_plan` 是 `pending_plan` 经过 T+1 pre-market 处理后的执行态版本。
6. `executed_trades` 记录的是“当前 trade_date 实际成交股数”，不是订单对象，也不是计划对象。
7. 同一条 `paper_trading_day` 事件同时出现 `prepared_plan`、`executed_trades` 和 `current_plan`，是因为它在记录“今天执行昨天计划，同时生成明天计划”。
8. `pipeline_timings.jsonl` 里的 `previous_plan` 指的是今天执行掉的旧计划，`current_plan` 指的是今天刚生成的新计划。
9. frozen current plan replay 回放的是历史 `daily_events.jsonl` 里保存下来的 `current_plan`，仍按“下一交易日执行”处理。
10. 当前实现确实存在 T+1 confirmation 这一步，但在 backtesting/paper trading engine 里使用的是简化版确认输入，不应把它误读成完整的真实盘中分钟级确认。

---

## 3. 先把 5 个最容易混的对象分开

### 3.1 `trade_date`

这是当前这条日级事件真正对应的交易日。

如果 `paper_trading_day.trade_date = 20260323`，它回答的是：

1. 今天执行了什么。
2. 今天收盘后又新生成了什么计划。

### 3.2 `pending_plan`

这是 engine 在循环之间保存的“待下一交易日执行的计划”。

它有两个主要来源：

1. 上一个交易日 `run_post_market()` 刚生成出来的新计划。
2. checkpoint 恢复时从磁盘读回来的 `pending_plan`。

### 3.3 `prepared_plan`

这是今天真正准备执行的计划。

它来自：

1. 对昨天留下来的 `pending_plan` 调用 `run_pre_market()`。
2. 在这一步做 signal decay、gap / negative news 类 pre-market 处理。

所以它可以理解为：

1. 昨天的计划。
2. 经过今天盘前整理之后，准备在今天进入 intraday 确认与执行的版本。

### 3.4 `current_plan`

这是今天 post-market 刚生成出来的新计划。

它不是今天已经执行过的计划，而是：

1. 今天收盘后根据最新市场和组合状态重新生成的计划。
2. 默认供下一个交易日继续使用。

### 3.5 `executed_trades`

这是今天真正发生的成交结果。

它记录的是：

1. ticker -> 实际成交股数
2. 当前 trade_date 的执行结果

它不是：

1. 下单意图
2. 计划对象
3. buy order 列表
4. executed order 对象集合

---

## 4. 当前 engine 的真实执行顺序

核心代码在 [src/backtesting/engine.py](../../../src/backtesting/engine.py) 的 `_run_pipeline_mode()` 中。

把单个交易日压缩后，真实顺序如下。

### 4.1 进入当前交易日循环

engine 先确定当前 `current_date`，并准备：

1. 当前交易日字符串
2. 上一个自然日字符串
3. 当前活跃 ticker 集合

这一步还会把下面几类 ticker 全部纳入活跃集合：

1. 原始观察 tickers
2. 当前持仓
3. `pending_plan` 里的买卖单 ticker

也就是说，今天即使没有新的研究候选，旧计划和旧持仓依然会被纳入执行视野。

### 4.2 先加载今天会用到的市场价格与限制状态

engine 会先加载：

1. `current_prices`
2. `daily_turnovers`
3. `limit_up`
4. `limit_down`

这一步是为了让今天的计划执行与队列处理有市场数据支撑。

### 4.3 如果存在 `pending_plan`，今天先执行昨天的计划

这是整个时序里最关键的一步。

当 `pending_plan is not None` 时，engine 会依次做：

1. `prepared_plan = pipeline.run_pre_market(pending_plan, trade_date_compact)`
2. 基于 `prepared_plan` 生成 T+1 confirmation 输入
3. 处理上一日留下的 `pending_buy_queue` 与 `pending_sell_queue`
4. `pipeline.run_intraday(prepared_plan, trade_date_compact, ...)`
5. 对确认通过的买单和卖单调用 executor

这意味着：

1. 今天盘中的执行对象，本质上来自昨天收盘后生成的计划。
2. 当前 trade_date 不是先研究、再当场立即买，而是先执行旧计划。

---

## 5. `prepared_plan` 在今天到底做了什么

`prepared_plan` 来自 [src/execution/daily_pipeline.py](../../../src/execution/daily_pipeline.py) 的 `run_pre_market()`。

当前实现是：

1. 对 `pending_plan` 调用 `apply_signal_decay()`。

这一步的语义是：

1. 昨天生成的计划不是原封不动直接执行。
2. 在今天盘前，它仍然会经过一次“是否继续有效”的预处理。

所以 `prepared_plan` 代表的是：

1. 昨天计划的今天执行态。
2. 它和原始 `pending_plan` 是同一条计划链，但不是完全同一个快照。

---

## 6. `run_intraday()` 负责什么

`run_intraday()` 在 [src/execution/daily_pipeline.py](../../../src/execution/daily_pipeline.py) 中做两类事：

1. 对 `plan.buy_orders` 逐只调用 `confirm_buy_signal()`。
2. 同时跑危机响应和退出检查。

也就是说，今天真正准备执行的不是全部 buy orders，而是：

1. 先通过 T+1 confirmation 的买单。
2. 再叠加 exits。
3. 再叠加危机响应可能带来的额外减仓。

所以你在 daily event 里看到的 `decisions`，并不只是“研究层原始输出”，而是经过 intraday 逻辑后的执行意图。

---

## 7. 当前 T+1 confirmation 的实现边界

当前代码里，T+1 confirmation 确实存在，并由 [src/execution/t1_confirmation.py](../../../src/execution/t1_confirmation.py) 的 `confirm_buy_signal()` 负责。

它要求检查三类条件：

1. `price_support`
2. `volume_price`
3. `industry_strength`

通过标准是：

1. 三项里至少两项通过。

但是要特别注意，当前 backtesting/paper trading engine 给它喂的数据来自 [src/backtesting/engine.py](../../../src/backtesting/engine.py) 的 `_build_confirmation_inputs()`，而这一步目前是简化实现。

当前输入近似为：

1. `day_low = current_price`
2. `ema30 = price * 0.99`
3. `vwap = price * 0.995`
4. `intraday_volume = 1.0`
5. `avg_same_time_volume = 1.0`
6. `industry_percentile = 0.5`

这意味着：

1. 当前系统已经表达了“T+1 盘中确认”这一语义层。
2. 但在 paper trading/backtesting 里，它还不是完整的分钟级真实市场确认。
3. 因此，复盘时应把它理解为“日级近似确认流程”，而不是实盘级盘中确认重建。

---

## 8. `decisions` 和 `executed_trades` 不是一回事

这两个字段非常容易被混淆。

### 8.1 `decisions`

表示今天打算怎么做。

来源包括：

1. intraday confirmation 后通过的 buy
2. exit signals
3. crisis response 强制减仓
4. pending queues 被重新触发的订单

### 8.2 `executed_trades`

表示今天实际上做成了多少。

它是 executor 的最终结果：

1. 成功成交则记录股数
2. 未成交则为 `0`

所以最稳的理解是：

1. `decisions` 是执行意图层。
2. `executed_trades` 是执行结果层。

如果一只票在 `decisions` 中出现，但 `executed_trades[ticker] = 0`，说明今天“想做但没做成”或“被约束转移到队列”。

---

## 9. 为什么字段名是 `executed_trades`，不是 `executed_orders`

当前持久化口径记录的是：

1. 每个 ticker 在当前 trade_date 实际成交的股数。

例如：

1. `executed_trades = {"300724": 100}`

它回答的是：

1. 今天这个 ticker 到底实际成交了多少股。

它不回答：

1. 今天生成了多少张订单对象。
2. 今天有哪些订单进入了准备态。

所以在当前 paper trading runtime 里：

1. 日级事实字段叫 `executed_trades` 是准确的。
2. 如果写成 `executed_orders`，反而会让人误以为这里保存的是订单明细集合。

`JsonlPaperTradingRecorder` 统计 `total_executed_orders` 的方法，也是基于 `executed_trades` 里非零 ticker 的数量，而不是订单对象数量。

---

## 10. `current_plan` 为什么和 `executed_trades` 会同时出现在同一天事件里

这是因为一条 `paper_trading_day` 事件，记录的是“当天完整闭环”，而不是只记录单一阶段。

它同时覆盖：

1. 今天执行了什么
2. 今天执行后组合变成什么样
3. 今天收盘后又新生成了什么计划

所以同一事件里你会同时看到：

1. `prepared_plan`：今天真正执行的旧计划
2. `executed_trades`：今天真正成交的结果
3. `current_plan`：今天收盘后新生成、准备给下一个交易日用的新计划

这不是混乱，而是同一日闭环的完整快照。

---

## 11. `pipeline_timings.jsonl` 里的 `previous_plan` 和 `current_plan` 怎么读

当前 `pipeline_day_timing` 事件里，会同时记录：

1. `previous_plan`
2. `current_plan`

直观理解：

1. `previous_plan`：今天执行掉的那份旧计划的计数、耗时和 funnel 摘要。
2. `current_plan`：今天收盘后新生成的计划的计数、耗时和 funnel 摘要。

因此：

1. 如果你想解释今天为什么有执行，应优先看 `previous_plan` 和 `prepared_plan`。
2. 如果你想解释明天可能执行什么，应优先看 `current_plan`。

---

## 12. checkpoint 是怎样把时序续上的

checkpoint 逻辑在 [src/backtesting/engine.py](../../../src/backtesting/engine.py) 的 `_save_checkpoint()` 和 `_load_checkpoint()` 中。

每个交易日结束后，engine 会把以下内容写入 checkpoint：

1. `last_processed_date`
2. `portfolio_snapshot`
3. `pending_buy_queue`
4. `pending_sell_queue`
5. `exit_reentry_cooldowns`
6. `pending_plan`

这里最关键的是最后一项：

1. `pending_plan` 保存的就是今天 post-market 刚生成的新计划。
2. 如果中断后恢复，下一次运行会直接把它当作“待执行计划”接着跑。

也就是说，checkpoint 延续的不是“今天已经执行完的 prepared_plan”，而是“明天还要继续执行的 pending_plan”。

---

## 13. pending buy / sell queues 在时序里扮演什么角色

当前 engine 还会在日与日之间维护两类队列：

1. `pending_buy_queue`
2. `pending_sell_queue`

它们主要用于处理：

1. 涨停导致买不进去
2. 跌停导致卖不出去
3. 当日未完成、需要下个交易日继续处理的订单

在时序上，它们是这样工作的：

1. 今天 intraday / executor 发现无法成交
2. 对应订单进入 pending queue
3. 下一个交易日开始时，`_process_pending_queues()` 先尝试重新处理
4. 处理结果再并入今天的 `decisions`

所以队列本身也是 T -> T+1 传递链的一部分。

---

## 14. frozen current plan replay 到底回放什么

在 frozen current plan replay 模式下，runtime 会从历史 `daily_events.jsonl` 中读取旧的 `current_plan`，并把它们装载到 `DailyPipeline.frozen_post_market_plans` 里。

它回放的不是：

1. 历史当天已经执行完成的交易结果

而是：

1. 历史当天收盘后生成的计划对象
2. 再按当前 replay 的交易日顺序，把这份计划作为后续待执行计划使用

因此 frozen replay 的核心语义是：

1. 复用历史 post-market 计划
2. 继续验证后续执行链和落盘口径

而不是重新生成一份全新的 post-market 研究结果。

---

## 15. 真实样本里最该怎么解释

当前仓库里已经有一条很关键的验证结论，见 [arch_optimize_implementation.md](../product/arch/arch_optimize_implementation.md)：

1. 当前 paper trading pipeline 的实际执行时序是“T 日 post-market 生成计划，T+1 交易日执行 pending plan”。
2. 日级事件里的实际成交字段名是 `executed_trades`，不是 `executed_orders`。

这意味着，在真实窗口复盘里：

1. 如果你在 `20260320` 的 `current_plan` 里看到某只票的 buy order，这并不表示它在 `20260320` 当天已经成交。
2. 你需要去下一个交易日的 `executed_trades` 里确认它是否真正成交。
3. 如果中间跨周末，那么这个 T+1 是下一个交易日，而不是自然日。

---

## 16. 最常见的 6 个误读

### 16.1 把 `current_plan` 当成“今天已执行计划”

它其实更接近“今天生成、下个交易日执行的计划”。

### 16.2 把 `executed_trades` 当成订单列表

它记录的是成交股数，不是订单对象。

### 16.3 看见 `buy_orders` 就认为当天已经买入

`buy_orders` 仍属于计划层，不等于执行结果层。

### 16.4 忽略 `prepared_plan`

如果只看 `current_plan`，你会把今天执行的旧计划和今天新生成的新计划混成一团。

### 16.5 把 T+1 confirmation 当成完整实盘盘中确认

当前 paper trading/backtesting 里，这一步是存在的，但输入仍是简化实现。

### 16.6 把 checkpoint 里的 `pending_plan` 当成历史残留垃圾

它其实是跨交易日续跑最关键的时序载体。

---

## 17. 复盘时的最小阅读顺序

如果你要判断某只票到底是在什么时候被选中、什么时候真正成交，建议按下面顺序读：

1. 先看当天 `paper_trading_day.trade_date`。
2. 再看 `prepared_plan`，确认今天真正执行的是哪份旧计划。
3. 再看 `decisions` 和 `executed_trades`，确认今天到底做了什么。
4. 再看 `current_plan`，确认今天又为下一个交易日准备了什么。
5. 如果涉及续跑或中断恢复，再看 checkpoint 里的 `pending_plan`。
6. 如果是 frozen replay，再确认计划源来自哪份历史 `daily_events.jsonl.current_plan`。

---

## 18. 一句话总结

当前 paper trading 的真实时序不是“今天研究、今天买”，而是“今天执行昨天的 pending plan，同时在收盘后生成明天的 current_plan”。只有先把 `prepared_plan`、`current_plan` 和 `executed_trades` 这三层分开，daily_events.jsonl 和 pipeline_timings.jsonl 才不会被读反。
