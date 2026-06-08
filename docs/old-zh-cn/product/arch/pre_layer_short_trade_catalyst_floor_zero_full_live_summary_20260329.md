# Catalyst Floor Zero 扩覆盖的真实 live 完整窗口验证：决策摘要

## 一句话结论

`catalyst_freshness_min = 0.00` 在完整 `2026-03-23` 到 `2026-03-26` 四天真实 live candidate-generation 路径里依然成立：它把 pre-Layer C `short_trade_boundary` 候选覆盖扩到 `24` 个，同时没有把旧 `layer_b_boundary` score-fail 簇重新带回来，候选次日表现也仍明显强于旧路径。

## 这次补完了什么

上一轮只收口了前两天 partial live 结果；这轮把完整 4 日窗口全部补齐，并统一输出了：

1. `data/reports/short_trade_blocker_analysis_catalyst_floor_zero_full_20260329.json`
2. `data/reports/pre_layer_short_trade_outcomes_catalyst_floor_zero_full_20260329.json`
3. `data/reports/short_trade_boundary_score_failures_catalyst_floor_zero_full_20260329.json`

因此这里的结论不再建立在 partial artifact 上，而是基于完整窗口闭环。

## 与默认路径相比发生了什么

当前窗口的 baseline 默认路径是：

- short-trade target 总数：`32`
- `layer_b_boundary` score-fail：`23`
- `short_trade_boundary` near-miss：`0`

而 catalyst-only 真实 live 完整窗口是：

- short-trade target 总数：`33`
- `short_trade_boundary` 候选：`24`
- `short_trade_boundary` near-miss：`6`
- `short_trade_boundary` rejected：`18`
- `layer_b_boundary` score-fail：`0`

这说明 catalyst-only 扩出来的是新的 `short_trade_boundary` 候选，而不是把旧共享 Layer B boundary 失败簇重新放回系统。

## pre-Layer C 候选质量有没有塌

没有。完整 4 日窗口里，`24` 个 `short_trade_boundary` pre-Layer C 候选的次日表现为：

- `next_high_return_mean = 0.0471`
- `next_close_return_mean = 0.0186`
- `next_high_hit_rate@2% = 0.75`
- `next_close_positive_rate = 0.7083`

虽然比前两天 partial live 的极强样本均值有所回落，但依然明显高于旧 `layer_b_boundary` 池在同窗口里的：

- `next_high_return_mean = 0.0263`
- `next_close_return_mean = 0.0027`
- `next_high_hit_rate@2% = 0.5217`
- `next_close_positive_rate = 0.5652`

所以这不是“扩大覆盖换来质量塌陷”，而是“扩大覆盖后质量仍明显优于旧路径”。

## 完整窗口把主矛盾收敛到了哪里

完整窗口现在把前置短线主线收敛成两层：

1. admission 层已经足够清楚：`catalyst_freshness_min = 0.00` 是当前最值得保留的第一条轻量扩覆盖杠杆。
2. 新主失败簇已经不再是 `layer_b_boundary`，而是 `18` 个 `short_trade_boundary` score-fail 样本，需要进一步审查它们为什么过了入口仍然停在 near-miss 线之下。

## 最终决策

如果下一轮继续优先优化 Layer C 之前的短线策略，那么默认顺序应更新为：

1. 把 `catalyst_freshness_min = 0.00` 视为已通过完整 live 窗口验证的主实验变体。
2. 不要回头重新放大旧 `layer_b_boundary` 池，也不要先联动放松 volume floor。
3. 下一步重点转向新增 `short_trade_boundary` score-fail 簇的 score frontier，而不是继续改 admission floor。
