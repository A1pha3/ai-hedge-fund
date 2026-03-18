# 2026-03-18 300065 补证：它是上游近阈值与强负向 Layer C avoid 样本，不是 clean edge benchmark

## 1. 结论先行

这轮补证之后，300065 的定位也可以收紧：

1. 它不是新的 clean edge benchmark。
2. 它更像一条“上游 Layer B 连续压线，随后在某些长窗回放里即使穿过 Layer B 也会被强 bearish Layer C 打回 avoid”的样本。
3. 因此它可以保留为机制样本或低优先级线索，但不能升级为新的 benchmark。

这份补证的目的，是把 300065 和 600519、300724 这类固定验收样本区分开，避免后续把“interesting but dirty”的样本混进 benchmark 池。

## 2. 一手与二手证据链

### 2.1 历史结构化扫描里，它没有自然长成 clean watch 证据

在 data/reports/historical_edge_sample_scan_20260318.json 的当前结果中：

1. near_threshold_watch 主要集中在 300724、600519、600988；
2. sub_threshold_watch 只稳定出现 600519、603993；
3. 没有看到 300065 的 final near-threshold non-conflict watch 记录。

这点很关键，因为 benchmark 候选首先要在历史结构化产物里留下自然、可复用的 clean watch 痕迹。300065 当前不满足这个前提。

### 2.2 20 日窗口分析显示它连续三天卡在 Layer B 下沿

在 docs/zh-cn/analysis/pipeline-funnel-scan-202602-window-20260312.md 中，300065 的关键证据很集中：

1. 20260223：score_b = 0.3735
2. 20260224：score_b = 0.3739
3. 20260225：score_b = 0.3736

这三天的共同点是：

1. 它连续三天贴在 0.38 fast threshold 下沿；
2. 它没有触发会改写分数的 arbitration；
3. 因而它更像原始聚合层面的 near-threshold 样本，而不是被某个后置仲裁错误压下去的样本。

这说明 300065 的信息量主要落在上游 Layer B 边缘，而不是最终 watchlist 边缘。

### 2.3 长窗 paper trading 里，它可以过 Layer B，但会被 Layer C 强烈打回 avoid

在 data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl 的 20260223 prepared plan 中，可以直接看到 300065 被选入 layer_b 和 layer_c：

1. layer_b.selected_tickers = ["300065"]
2. layer_c.selected_tickers = ["300065"]
3. watchlist.filtered_count = 1

同一条记录里，300065 的具体状态是：

1. score_b = 0.401
2. score_c = -0.6861
3. score_final = -0.0882
4. decision = avoid
5. bc_conflict = b_positive_c_strong_bearish
6. active_agent_count = 17，negative_agent_count = 14

这说明它并不是简单地“永远上不去”。更准确的说法是：

1. 它在某些长窗回放里可以越过 Layer B；
2. 但 investor cohort 的强 bearish 共识会把 Layer C 压得很低；
3. 最终它不会形成 clean watch，而是直接变成 conflict + avoid。

这种形态对机制研究有价值，但对 benchmark 没价值，因为 benchmark 需要的是稳定边界，而不是“先上去再被强烈打回”的冲突型样本。

### 2.4 其他 baseline-like 产物里，它经常只是更低层级的残留

在多份 baseline / 长窗 timing 产物中，300065 反复以 below_fast_score_threshold 的形态出现，常见 score_b 命中值包括：

1. 0.0738
2. 0.0735
3. -0.0186
4. 0.0

这进一步说明：

1. 它的稳定形态并不是 final watch 边缘；
2. 在不同回放或上下文里，它很容易退回到更低层级；
3. 它不具备 benchmark 所需要的稳定、可复用边界特征。

## 3. 根因更像 profitability 硬负项，而不是 arbitration 误杀

在 docs/zh-cn/factors/01-aggregation-semantics-and-factor-traps.md 中，对 300065 的反事实分析给了很强的解释力：

1. 如果直接移除 profitability 硬负项，它可以从约 0.3735 到 0.3739 被抬到约 0.3870 到 0.3874；
2. 但如果只是把 profitability 的 confidence 从 100 降到 40，反而会掉到约 0.3404 到 0.3408。

这两个结果合起来说明：

1. 300065 的问题不是简单的“负项太激进，可以靠下调 confidence 温和修复”；
2. 它更像由 profitability 语义本身触发的硬负向结构；
3. 因此它适合作为因子语义与聚合陷阱样本，而不是 benchmark。

## 4. 为什么它不能进入 benchmark

300065 当前不能进入 benchmark，原因有三个。

### 4.1 它没有 clean non-conflict watch 的自然历史足迹

结构化 scan 没有给出它在 near-threshold_watch 或 sub-threshold_watch 中的稳定存在，这一点已经足够让它失去 benchmark 资格。

### 4.2 它的核心价值落在机制研究，而不是稳定边界验收

300065 更适合回答的是：

1. 为什么某些票会连续三天贴住 Layer B 下沿；
2. 为什么即使越过 Layer B，也会被 Layer C 的 investor bearish 共识直接打回 avoid；
3. profitability 这种硬负项在聚合语义里到底起了什么作用。

这不是 benchmark 该解决的问题。benchmark 应该约束的是稳定边界，而不是机制解释。

### 4.3 它跨产物状态不稳定

同一个 ticker 既可以表现为：

1. 连续三天卡在 0.373x；
2. 长窗里 score_b = 0.401 但 score_final = -0.0882；
3. 其他回放里又退回到 0.0738、0.0735、-0.0186 这类更低层级。

这种跨产物波动说明它对上下文非常敏感，不适合当作后续最小规则实验的固定验收样本。

## 5. 更合理的归类

截至当前，300065 更合理的归类应当是：

1. 不是固定 benchmark；
2. 不是当前可准入的第四个 clean edge sample；
3. 是“上游 Layer B 压线 + profitability 硬负项 + Layer C avoid”机制样本；
4. 如果后续还要继续补证，它的价值在解释聚合与 conflict 形成机制，而不是验证 watchlist 放宽是否合理。

## 6. 对后续工作的约束

这份补证对下一步有两个直接约束：

1. benchmark 继续固定为三条：20260224/600519、20260226/600519、20260226/300724；
2. 在 688498 或其他候选没有出现更干净的一手 near-threshold non-conflict watch 证据前，不应因为 300065 的连续压线特征而推进新的全局规则放松实验。

## 7. 当前结论

截至 2026-03-18：

1. 300065 已完成专项补证；
2. 它的证据链已经够完整：结构化 scan 缺席 clean watch -> 20 日窗口三天 0.373x 压线 -> 长窗回放里 score_b 过线但 score_final 被打成 avoid -> factor 分析指向 profitability 硬负项；
3. 这足以证明它是机制样本，不是新的 clean edge benchmark。