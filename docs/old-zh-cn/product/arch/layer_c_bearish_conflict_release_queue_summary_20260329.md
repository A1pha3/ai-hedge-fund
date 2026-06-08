# Layer C Bearish Conflict 是否应窗口级放松：决策摘要

## 一句话结论

不应做窗口级统一放松。当前 4 日窗口里，`layer_c_bearish_conflict` blocked 簇共 5 个样本，但只有 `2026-03-25 / 300724` 在当前搜索空间内存在低成本 near-miss rescue row；其余 blocked 样本都不适合跟着一起放开。

## 为什么要单独做这份判断

前一轮已经确认：short-trade 从 Layer B 开始独立建池后，旧的 boundary score-fail 主失败簇已经在真实窗口里清掉了。这样一来，剩余最值得审的就是 `layer_c_bearish_conflict` blocked 簇。

但这里有一个风险：

- 如果只看 `300724`，很容易误以为“既然它低成本可救回，那是不是整个 blocked 簇都该一起放松”。
- 真正该验证的不是单点是否可救，而是整个窗口里有多少 blocked 样本具备同类可救回性。

## 窗口级结果

基于 `scripts/analyze_structural_conflict_rescue_window.py` 对当前 4 日高保真窗口的批量扫描，结果如下：

- blocked 样本总数：`5`
- 存在 near-miss rescue row 的样本数：`1`
- 存在 selected rescue row 的样本数：`1`
- 唯一进入 rescue priority queue 的样本：`2026-03-25 / 300724`

其余 4 个 blocked 样本都没有在当前搜索空间内出现 near-miss row：

- `2026-03-25 / 300394`
- `2026-03-26 / 300394`
- `2026-03-23 / 300308`
- `2026-03-26 / 300502`

## 300724 为什么特殊

`300724` 的 baseline `score_target=0.3785`，距离 near-miss 仅差 `0.0815`。在移除 hard block 与 conflict surcharge 后：

- 最小 near-miss row 只需要把 `near_miss_threshold` 从 `0.46` 下调到 `0.42`
- 其余 stale / extension penalty 权重可以保持默认
- `adjustment_cost=0.04`

这说明它是一个非常典型的“高分 blocked、低成本可释放”样本。

## 其余样本为什么不该跟着一起放

### 300394

`300394` 在 `2026-03-25` 和 `2026-03-26` 两天都出现过 blocked，但即便在当前搜索空间里把 hard block 去掉，并把 stale / extension 权重压到窗口扫描的最低点，它仍然没有 near-miss row。最好结果也只是：

- `2026-03-25` best_score_row=`0.2970`
- `2026-03-26` best_score_row=`0.2994`

这和 earlier replay frontier 的结论一致：`300394` 不是“微调一下就能进 near-miss”的样本，它需要更实质的 penalty+threshold 联动，甚至可能仍要回到 candidate-entry / score construction 路径。

### 300308

`300308` 的 best_score_row 只有 `0.2310`，距离 near-miss 仍然太远。它不是值得优先拿来做 hard block 放松实验的对象。

### 300502

`300502` 的 best_score_row 只有 `0.0579`。这个样本的问题仍然不是 structural conflict 微调，而是 candidate-entry 语义本身不匹配，继续沿 breakout / volume / entry 规则处理更合理。

## 这意味着什么

这轮结果实际上把问题收得更紧了：

- `layer_c_bearish_conflict` blocked 簇不是一个应被整体放松的集群。
- 真正值得做受控释放实验的，只有 `300724` 这一类“高分、低成本、接近 near-miss”的个别样本。
- 如果把整个 blocked 簇一起放松，等于会把大量本来并不接近 near-miss 的低质量 blocked 样本也一起放进实验噪声里。

## 最合理的下一步

下一轮最合理的动作不是做 cluster-wide hard block relaxation，而是：

1. 仅对 `300724` 做受控 near-miss 释放实验。
2. 明确实验语义是“去掉重复 conflict 惩罚后，near_miss_threshold 从 `0.46` 调到 `0.42`”。
3. 保持其余 blocked 样本不动，继续按各自路径处理：
   - `300394` 走 penalty / threshold 联动审查。
   - `300502` 走 candidate-entry / breakout 语义路径。
   - `300308` 暂不作为优先对象。

## 已完成的受控实验验证

这一步现在已经不是停留在建议层。基于 `scripts/analyze_targeted_structural_conflict_release.py`，已对当前 4 日高保真窗口执行一次真实 `300724-only` case-based release：

- 目标 case：`2026-03-25 / 300724`
- overrides：移除 `hard_block_bearish_conflicts`、移除 `overhead_conflict_penalty_conflicts`、把 `near_miss_threshold` 从 `0.46` 下调到 `0.42`
- 窗口总样本数：`32`
- 实际发生变化的样本数：`1`
- 唯一变化样本：`2026-03-25 / 300724`，`blocked -> near_miss`
- 变化后 `score_target`: `0.3785 -> 0.4235`
- 非目标样本变化数：`0`

这条结果很关键，因为它把“只该做 300724-only 实验”进一步推进成了窗口级实证：当前 case-based 实验不会把其它 31 个样本一起带动，不会把 `300394`、`300308`、`300502` 混进同一轮实验噪声里。

## 最终决策

当前窗口不支持把 `layer_c_bearish_conflict` 当作一个统一放松的 blocked 簇来处理。更稳健的决策是：只把 `300724` 作为唯一低成本 near-miss 释放候选单独做实验，其余 blocked 样本暂不随之放宽。
