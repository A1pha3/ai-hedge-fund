# Layer C 之前的短线候选该怎么扩覆盖：决策摘要

## 一句话结论

可以扩，但不能按“所有 floor 都一起放松”的思路粗放扩。当前 4 日窗口里的旧 `layer_b_boundary` 候选池显示：温和放松几乎没有增量；真正能带来新增覆盖的第一杠杆其实是把 `catalyst_freshness` floor 从 `0.12` 降到 `0.00`，而不是先去放松 breakout 或 volume。继续把 volume floor 一并放低虽然能多带来 1 个样本，但质量已经开始明显变差。

## 这次新增验证了什么

这轮不是再看静态 filtered_reason_counts，而是补了两类前置分析器：

1. `scripts/analyze_short_trade_boundary_coverage_variants.py`
2. `scripts/analyze_short_trade_boundary_filtered_candidates.py`

它们分别回答两个问题：

1. 如果想扩 `short_trade_boundary` 覆盖，哪些 threshold 变体真的能带来新增样本，且次日表现不明显塌掉。
2. 当前被挡在 floor 外的样本里，哪些是最接近可放行的 edge candidate。

## 当前 baseline 说明了什么

在真实 `2026-03-23` 到 `2026-03-26` 窗口上，对旧 `layer_b_boundary` 候选池做回放后，baseline short-trade boundary floor 的结果是：

- 候选总数：`23`
- baseline 放行数：`0`
- 主失败簇：
  - `breakout_freshness_below_short_trade_boundary_floor = 19`
  - `catalyst_freshness_below_short_trade_boundary_floor = 3`
  - `volume_expansion_below_short_trade_boundary_floor = 1`

这说明一个很关键的事实：当前旧池里的绝大多数样本并不是“差一点过线”，而是在 breakout 维度上大量接近归零。

## 过滤明细告诉了我们什么

过滤明细脚本把“最接近放行”的样本具体排出来后，结论比聚合计数更清楚：

1. `2026-03-25 / 300308` 只差 `catalyst_freshness=0.12`，次日最高 `+2.64%`，但收盘 `-2.26%`。
2. `2026-03-24 / 300274` 只差 `catalyst_freshness=0.12`，次日最高 `+2.31%`，收盘 `+1.46%`。
3. `2026-03-23 / 300502` 只差 `catalyst_freshness=0.12`，次日最高 `+1.71%`，收盘 `+1.64%`。
4. `2026-03-26 / 002463` 虽然次日最高 `+4.56%`、收盘 `+2.06%`，但同时还差 breakout、volume、candidate_score 三个条件，不属于“轻微放行”样本。

换句话说，当前最像可控扩覆盖入口的，不是去动 breakout 主 floor，而是先处理一小簇“结构已经够强，但 catalyst_freshness 恰好为 0”的样本。

## 定向 coverage 变体验证结果

围绕这些 edge candidate 做定向回放后，结果可以收敛成两档：

### 方案 A：只放松 catalyst floor

当保持下面四个 floor 不变：

- `candidate_score_min = 0.24`
- `breakout_freshness_min = 0.18`
- `trend_acceleration_min = 0.22`
- `volume_expansion_quality_min = 0.15`

只把：

- `catalyst_freshness_min: 0.12 -> 0.00`

则可新增 `3` 个样本：

- `300308`
- `300274`
- `300502`

对应次日表现为：

- `next_high_return_mean = 0.0222`
- `next_close_return_mean = 0.0028`
- `next_high_hit_rate@2% = 0.6667`
- `next_close_positive_rate = 0.6667`

这是当前窗口里最像“扩覆盖但质量未明显塌掉”的最小方案。

### 方案 B：继续把 volume floor 一并放松

如果在方案 A 基础上继续把：

- `volume_expansion_quality_min: 0.15 -> 0.06`

则样本会从 `3` 增到 `4`，多出来的是 `2026-03-26 / 002463`。但这时整体表现退化为：

- `next_high_return_mean = 0.0209`
- `next_close_return_mean = -0.0036`
- `next_high_hit_rate@2% = 0.5`
- `next_close_positive_rate = 0.5`

也就是说，这个额外样本换来的不是更好的 coverage-quality balance，而是已经开始把组合均值压回负数。

## 该怎么理解这轮结果

这轮证据把前置主线进一步收紧成三点：

1. 旧 `layer_b_boundary` 池里大部分样本依旧不值得救，因为 `19/23` 在 breakout 维度上明显缺失，不属于轻微放行对象。
2. 当前最值得测试的扩覆盖方向，不是广泛放松多个 floor，而是单独测试 `catalyst_freshness` 这一条门槛。
3. volume floor 继续往下放会开始明显拉低质量，因此不应和 catalyst 放松一起直接变成默认策略。

## 最终决策

如果下一轮继续优先优化 Layer C 之前的短线选股，那么建议顺序应是：

1. 先做 `catalyst_freshness_min = 0.00` 的受控扩覆盖实验。
2. 不要把 `volume_expansion_quality_min = 0.06` 这类更激进变体作为默认候选，因为它已经在当前窗口里出现质量退化。
3. breakout floor 暂时不应作为“轻微扩覆盖”的主杠杆，因为当前 `19/23` 的 breakout 失败更像结构性缺失，而不是边缘样本问题。
