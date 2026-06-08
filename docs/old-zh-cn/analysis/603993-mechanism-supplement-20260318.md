# 2026-03-18 603993 补证：它是上游形成机制样本，不是 clean edge benchmark

## 1. 结论先行

这轮补证之后，603993 的定位可以收得更严一些：

1. 它不是像 600519 那样稳定贴着 watchlist 阈值边界的 clean edge sample。
2. 它更像一条跨层跳变链条：上游 Layer B 近阈值或 sub-threshold，随后在 frozen replay 里被抬成 high-score watch 并真实买入，最后很快触发 logic stop 卖出。
3. 因此它只能作为“上游形成机制样本”保留，不能升级为新的 benchmark。

这份补证的目的不是证明 603993 没有信息量，恰恰相反，它很有信息量，只是信息量落在“形成机制研究”而不是“固定验收基准”。

## 2. 一手证据链

### 2.1 baseline 扫描结果只证明它有 sub-threshold 身份

在 data/reports/historical_edge_sample_scan_20260318.json 里，603993 只出现在 sub_threshold_watch 两次：

1. 20260203：score_b = 0.4536，score_c = -0.0607，score_final = 0.145
2. 20260204：score_b = 0.4536，score_c = -0.0607，score_final = 0.145

这两条记录都来自：

- data/reports/rule_variant_backtests/baseline.timings.jsonl

这说明的不是“603993 已经是 clean watch 边缘票”，而是：

1. 它在 baseline 视角下确实靠近上游阈值；
2. 但最终只落在 sub-threshold 档；
3. 单靠这两条记录，还不足以把它升格为 benchmark。

### 2.2 baseline 原始 timeline 显示它经常停在 Layer B fast threshold 下方

在 baseline.timings.jsonl 的多日记录里，603993 反复出现在 layer_b.filters.tickers，原因都是 below_fast_score_threshold。例如：

1. line 10 附近：score_b = 0.3366
2. line 11 附近：score_b = 0.2596
3. line 12 附近：score_b = 0.2783
4. line 13 附近：score_b = 0.2770
5. line 14 附近：score_b = 0.2762
6. line 15 附近：score_b = 0.3414

这组证据很关键，因为它说明：

1. 603993 并不是稳定停在最终 watchlist 边缘的一类票；
2. 它在 baseline 的更常见形态，是上游 Layer B 卡在 fast threshold 下沿；
3. 这更接近“待解释的形成机制”，而不是“可复用的验收样本”。

### 2.3 frozen replay 里它又被抬成 high-score watch 并真实买入

在 data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl 里，可以看到另一套完全不同的表现。

20260202 的 prepared plan 显示：

1. logic_scores[603993] = 0.2650335815790726
2. watchlist.selected_entries 中 603993 为：
   - score_b = 0.4122
   - score_c = 0.0852
   - score_final = 0.2650
   - decision = watch
   - bc_conflict = null
3. buy_orders 对 603993 下了 200 股买单

20260204 的 prepared plan 进一步显示：

1. logic_scores[603993] = 0.28809701675813465
2. watchlist.selected_entries 中 603993 为：
   - score_b = 0.4536
   - score_c = 0.0859
   - score_final = 0.2881
   - decision = watch
   - bc_conflict = null
3. buy_orders 又对 603993 下了 100 股买单

也就是说，同一个 ticker 在 baseline 里表现为 sub-threshold 或 Layer B below-threshold，但在 frozen replay 里又被抬成了明确的 high-score watch，并且真实成交 200 + 100 股。

### 2.4 紧接着它就进入 logic stop 失败链

同一份 frozen replay 的 20260205 事件又给出了失败闭环：

1. decisions[603993] = {"action": "sell", "quantity": 300, "reason": "logic_stop_loss"}
2. executed_trades[603993] = 300
3. realized_gains[603993][long] = -362.46600000000024
4. prepared_plan.logic_scores[603993] = -0.25

这里最重要的不是单日亏损金额，而是行为顺序：

1. 先是 high-score watch
2. 再是真实买入与加仓
3. 随后 prepared plan 直接跌到 -0.25
4. 下一交易日触发 logic_stop_loss 全部卖出

这说明 603993 并没有呈现出 benchmark 需要的那种“贴近阈值但行为稳定”的特征，而是呈现出“跨层抬升后快速失败出清”的特征。

## 3. 为什么它不能进入 benchmark

benchmark 的作用不是收集所有 interesting case，而是提供后续最小参数实验的硬性验收边界。对这个目标来说，603993 有三个问题。

### 3.1 它的核心价值在形成机制，不在稳定边界

600519 和 300724 之所以能当 benchmark，是因为它们约束的是稳定、可复用的边界行为：

1. 哪些票应当被放出
2. 哪些票应当保持不过线
3. 哪些回补不应重新放回来

603993 约束的不是这个问题。它更像在回答：

1. 为什么一个上游 near-threshold ticker 会在某些回放中被 Layer C 或组合逻辑抬成 high-score watch；
2. 为什么这种抬升会很快失败并落入 logic stop。

### 3.2 它的跨产物跳变太大

同一个 ticker，在本轮补证中同时出现了两种非常不同的状态：

1. baseline / scan：score_final = 0.145 的 sub-threshold watch
2. frozen replay：score_final = 0.2650 到 0.2881 的 high-score watch

这种跨层跳变说明：

1. 它对规则、上下文和回放形态高度敏感；
2. 不适合作为“改参数时必须守住”的固定边界样本；
3. 更适合作为机制研究对象，解释为什么会从 near-threshold 变成 high-score 再变成 stop-loss failure。

### 3.3 它没有提供健康新增样本，反而提供了失败样本

如果误把 603993 纳入 benchmark，会把 benchmark 的语义搞乱：

1. benchmark 应该验证“不要往错误方向改”；
2. 603993 更像在提醒“某些抬升路径会把票送进快速止损”；
3. 这是高价值信息，但属于 failure-mode evidence，不属于 clean edge evidence。

## 4. 更合理的归类

因此，603993 的当前归类应当是：

1. 不是固定 benchmark；
2. 不是当前可准入的第四个 clean edge sample；
3. 是高优先级的上游形成机制样本；
4. 后续如果继续补证，重点应该放在“它为什么能从 Layer B 近阈值跳到 high-score watch”，而不是把它当作边缘准入样本去做验收。

## 5. 对后续工作的约束

这份补证对下一步工作有两个直接约束：

1. benchmark 继续固定为三条：20260224/600519、20260226/600519、20260226/300724。
2. 在 300065、688498 或其他候选没有出现更干净的一手 near-threshold non-conflict 证据前，不应因为 603993 的存在而推进新的全局规则放松实验。

## 6. 当前结论

截至 2026-03-18：

1. 603993 已经完成专项补证；
2. 它的证据链是完整的：Layer B near-threshold 或 sub-threshold -> frozen replay high-score watch -> buy -> add -> logic stop sell；
3. 这条链足以证明它是形成机制样本，而不是新的 clean edge benchmark。