# Catalyst Floor Zero 扩覆盖的真实 live 局部验证：决策摘要

## 一句话结论

截至当前已完成的 `2026-03-23` 与 `2026-03-24` 两天真实 live candidate-generation 路径，`catalyst_freshness_min = 0.00` 这个 catalyst-only 扩覆盖变体不但显著扩大了 pre-Layer C short-trade boundary 候选覆盖，而且候选次日表现依然很强，没有出现“覆盖一扩就明显塌质量”的现象。

## 这次验证了什么

这轮不是再用静态 replay pool 推断，而是直接在真实 live paper trading 路径上运行：

- 运行变体：`DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_CATALYST_MIN=0.0`
- 输出目录：`data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_catalyst_floor_zero_validation_20260329`

由于完整 4 日窗口在本轮收口时仍在继续运行，这里先收口已经完整落盘的前两天 `2026-03-23, 2026-03-24` 结果。

## 与旧 short_trade_boundary live 路径相比发生了什么

在此前默认 builder 的真实 `2026-03-23,2026-03-24` 局部验证里：

- short-trade target 总数：`5`
- `short_trade_boundary` near-miss：`2`
- `layer_b_boundary` score-fail：`0`

而在 catalyst-only 变体的真实局部验证里：

- short-trade target 总数：`15`
- `short_trade_boundary` 候选：`12`
- `short_trade_boundary` near-miss：`2`
- `short_trade_boundary` rejected：`10`
- `layer_b_boundary` score-fail：`0`

这说明 catalyst-only 变体并没有把旧共享 `layer_b_boundary` 失败簇重新放回来；它扩出来的是新的 `short_trade_boundary` 候选，而不是把老的低质量入口重新引入。

## pre-Layer C 候选质量有没有塌

没有。从当前已落盘的 `12` 个 `short_trade_boundary` pre-Layer C 候选看，次日表现如下：

- `next_high_return_mean = 0.0602`
- `next_close_return_mean = 0.0392`
- `next_high_hit_rate@2% = 0.9167`
- `next_close_positive_rate = 0.9167`

这组结果比旧 `layer_b_boundary` 4 日窗口的 `next_close_return_mean = 0.0027` 明显更强，也比此前默认新 builder 当前样本里的 “只有 2 个样本但质量很高” 更进一步，因为它现在在真实 live 路径里把覆盖扩大到了 `12` 个样本，同时仍保持了非常强的次日表现。

## 代表样本说明了什么

当前 partial live 结果里，若只看次日表现最强的代表样本：

1. `2026-03-24 / 688525`：次日最高 `+13.00%`，收盘 `+9.44%`
2. `2026-03-23 / 600821`：次日最高 `+10.04%`，收盘 `+10.04%`
3. `2026-03-24 / 300620`：次日最高 `+8.46%`，收盘 `+2.67%`
4. `2026-03-24 / 001309`：次日最高 `+8.11%`，收盘 `+7.30%`

同时，之前静态 targeted coverage 里新增的 `300308`、`300274`、`300502` 三个样本，也已被逐票案例分析器确认属于纯 `catalyst_freshness` 单条门槛放行，而不是多条 floor 同时宽松造成的混杂结果。

## 这条证据把主线收紧到了哪里

这轮 partial live 证据把前置短线主线进一步收紧成下面两点：

1. `catalyst_freshness_min = 0.00` 已经不再只是静态 replay 建议，而是在真实 candidate-generation 路径中表现出强覆盖增量与强次日质量的组合。
2. 下一轮前置优化更值得做的，不是继续广泛放松其他 floor，而是优先围绕 catalyst-only 变体继续扩完整窗口验证，并审查新增 `short_trade_boundary` rejected 样本为什么还停在 `score_fail`。

## 最终决策

如果下一轮继续优先推进 Layer C 之前的短线优化，那么最合理的默认实验顺序应改为：

1. 先把 `catalyst_freshness_min = 0.00` 当作主实验变体继续验证完整窗口。
2. 不要先联动放松 `volume_expansion_quality_min`，因为静态 targeted 结果已经显示这会开始拉低质量。
3. 下一步重点应转向“新增 short_trade_boundary 候选为什么仍有 10 个 score_fail”，而不是重新回到旧 `layer_b_boundary` 池。
