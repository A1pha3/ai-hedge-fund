# 前置短线 score-fail 簇下一步该怎么救：决策摘要

## 一句话结论

`catalyst_freshness_min = 0.00` 扩出来的 `18` 个 `short_trade_boundary` score-fail 样本，并不是新的 admission 垃圾簇。它们普遍已经具备足够强的 breakout、trend、volume 与 close 结构，但大多数离 near-miss 仍差 `0.06+`，且主负贡献集中在 `stale_trend_repair_penalty` 与 `extension_without_room_penalty`。这意味着下一轮最值得做的不是继续放 admission floor，而是做 score frontier / penalty frontier 的受控实验。

## 这次新增验证了什么

这轮新增两类分析产物：

1. `data/reports/short_trade_boundary_score_failures_catalyst_floor_zero_full_20260329.json`
2. `data/reports/short_trade_boundary_score_failures_frontier_catalyst_floor_zero_full_20260329.json`

它们分别回答两个问题：

1. 新增 `short_trade_boundary` rejected 样本的共性到底是什么。
2. 这些样本里有没有值得做 near-miss rescue 的低成本 frontier。

## 这 18 个 score-fail 样本本质上是什么

聚合结果说明，这批样本不是入口结构差，而是评分后段没过线：

- `score_target_mean = 0.3653`
- `gap_to_near_miss_mean = 0.0947`
- `breakout_freshness_mean = 0.4084`
- `trend_acceleration_mean = 0.7758`
- `volume_expansion_quality_mean = 0.2741`
- `close_strength_mean = 0.8738`
- `catalyst_freshness_mean = 0.0122`

同时，正负贡献均值进一步说明了失败结构：

- 正贡献主力：`trend_acceleration = 0.1396`、`close_strength = 0.1223`、`breakout_freshness = 0.0899`
- 负贡献主力：`stale_trend_repair_penalty = 0.0559`、`extension_without_room_penalty = 0.0356`

而且 `17/18` 个样本距离 near-miss 仍超过 `0.06`，只有 `2026-03-26 / 300383` 这一票属于明显贴线样本。

## frontier 扫描说明了什么

在扫描以下空间后：

- `near_miss_threshold`: `0.46, 0.44, 0.42, 0.40, 0.38`
- `stale_score_penalty_weight`: `0.12 -> 0.02`
- `extension_score_penalty_weight`: `0.08 -> 0.00`

结果显示：

- `18/18` 个样本都存在 near-miss rescue row
- 但仅 `1/18` 个样本可以只靠 threshold 放松救回
- 其余 `17/18` 个样本都需要 stale/extension penalty 联动下调

最小成本 rescue row 只有一票：

- `2026-03-26 / 300383`
- baseline `score_target = 0.4237`
- 只需把 `near_miss_threshold: 0.46 -> 0.42`
- `adjustment_cost = 0.04`

而像 `600821`、`002015` 这类重复出现的候选，要进入 near-miss，至少都需要把 extension penalty 再往下压，或把 stale penalty 一并放松。

## 这把下一轮主线收紧到了哪里

当前证据已经足够把后续动作分层：

1. admission 层先停手：不必继续找第二条 floor 放松，因为主矛盾已经不在 admission。
2. rescue 层可受控推进：优先审查 `300383` 这类 threshold-only 贴线样本，再看是否值得把 `600821` / `002015` 这类重复 ticker 纳入小规模 stale+extension frontier。
3. 不应做 cluster-wide 宽松：因为只有 1 个样本是纯 threshold-only，其余都牵涉 penalty 联动，不能被包装成“简单整体放松 near-miss 线”。

## 最终决策

如果下一轮继续优先推进 Layer C 之前的短线策略，那么建议顺序应更新为：

1. 先做 `300383` 的 threshold-only near-miss 受控实验，验证最小成本 rescue 是否有真实价值。
2. 再做 `600821` / `002015` 这类重复 ticker 的 stale+extension frontier 样本审查。
3. 在这条 score frontier 路线验证前，不要继续扩大 admission floor 的实验面。
