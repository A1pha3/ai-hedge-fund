# BTST 5D15 Catalyst 主线里的 close_strength 确认边界研究

日期：2026-05-23

## 这次在看什么

这轮不是重新找一条新主线，而是在已经确认最有研究价值的窄 gate 里面，继续找第二层确认条件。

当前母样本仍然固定为：

```text
trend_acceleration_top_20pct
+ next_open_return <= 3%
+ candidate_source == catalyst_theme
+ close_strength < 0.90
```

这条母样本的最新去重结果是：

- 去重样本：13
- 去重 closed cycle：11
- 5 日内触及 15% 命中率：45.45%
- 2-5 日未来最高收益均值：20.62%
- beta 可执行率：100%

它的赔率还可以，但胜率没有过 55%。这说明问题已经不再是“这条主线有没有价值”，而是“这条主线里面，哪一段更像高质量确认边界”。

## 先踩到的坑

最开始给 confirmation grid 配的默认条件是偏通用 breakout 风格的：

- `trend_continuation >= ...`
- `volume_expansion_quality >= ...`
- `t0_tail_strength >= ...`
- `breakout_freshness <= 0.25 / 0.35`

真实数据一跑，全部是 0 行。后来回头看母样本分布，问题很清楚：

- `trend_continuation` 在这批样本里几乎都缺失
- `t0_tail_strength` 全部缺失
- `volume_expansion_quality` 集中在 `0.25 ~ 0.31`
- `breakout_freshness` 集中在 `0.40 ~ 0.48`

也就是说，原先那组默认条件根本不是这条 catalyst 窄 gate 的语言。它们更像在找“更强 breakout”，而这条线真正有用的反而是“别太热”的约束。

## 修正后的扫描结果

把默认 catalog 改成和真实分布对齐之后，再扫一遍：

| confirmation | closed | 命中率 | 均值最高收益 | 结论 |
| --- | ---: | ---: | ---: | --- |
| `breakout_freshness <= 0.40` | 10 | 50.00% | 22.68% | 比母样本稳一点，但胜率抬升有限 |
| `breakout_freshness <= 0.43` | 10 | 50.00% | 22.68% | 和 `0.40` 基本一致 |
| `volume_expansion_quality <= 0.25` | 10 | 50.00% | 22.68% | 也是轻微改善，不够强 |
| `volume_expansion_quality <= 0.28` | 10 | 50.00% | 22.68% | 与上面差异很小 |
| `close_strength <= 0.885` | 4 | 50.00% | 23.03% | 太紧，样本掉得太快 |
| `close_strength <= 0.890` | 5 | 60.00% | 21.79% | 当前最优平衡点 |
| `close_strength <= 0.892` | 5 | 60.00% | 21.79% | 与 `0.890` 等价 |
| `close_strength <= 0.895` | 9 | 44.44% | 20.05% | 已经开始稀释 |

最值得记住的是两件事：

1. `0.895` 往上放，胜率和均值收益都会回落，说明这条确认边界确实不是越宽越好。
2. `0.885` 虽然均值收益更高，但样本只剩 4 个 closed，不够稳，暂时不能把它当成主确认边界。

所以当前最像“研究中可保留边界”的是：

```text
candidate_source == catalyst_theme
+ trend_acceleration_top_20pct
+ next_open_return <= 3%
+ close_strength <= 0.89
```

## 这条边界现在处在什么状态

它还不是可推广因子，只能算 research-only 的确认边界。

当前证据：

- 去重 closed：5
- 命中率：60.00%
- 2-5 日未来最高收益均值：21.79%
- 相对母样本命中率提升：+14.55 个百分点
- 相对母样本均值最高收益提升：+1.17 个百分点

问题也很直接：

- 5 个 closed cycle 太少
- 距离 30 个 closed 的最低研究样本线还差 25 个
- 还没有资格谈 OOS 或 rollout

所以这轮结论不是“发现了可上线因子”，而是“发现了一个值得继续积累样本的高优先级确认边界”。

## 这条研究结论怎么用

下一轮沿 catalyst 主线继续收样本时，不要再把 `close_strength < 0.90` 当成终点，而是要额外盯住：

```text
close_strength <= 0.89
```

具体用法：

1. 先继续沿现有母样本流程收新交易日，不回头放宽到 `0.895+`。
2. 每次补完新样本后，先更新 confirmation grid，看 `close_strength <= 0.89` 的 closed 数、命中率、均值收益有没有继续站住。
3. 在 closed 数还没到 30 之前，不要急着再叠很多第三层条件，先确认 `0.89` 这条边界是不是稳定存在。

## 下一步优先级

当前最优先的不是再改代码逻辑，而是继续积累这条边界的 closed sample。

执行顺序建议：

1. 继续跑新交易日报告，扩充 catalyst 主线样本。
2. 每批新样本先更新 confirmation grid。
3. 如果 `close_strength <= 0.89` 在样本变多后仍能保持 55% 以上命中率，再考虑给它叠第三层确认条件。
4. 如果样本扩大到接近 30 时，这条边界开始退化，再回头检查是不是 `0.892` 或 breakout/volume 的组合更稳。

这条线现在最大的价值，不是“已经找到了最终答案”，而是把搜索范围从模糊的 catalyst 主线，进一步压缩到了一个可以持续验证的窄边界上。
