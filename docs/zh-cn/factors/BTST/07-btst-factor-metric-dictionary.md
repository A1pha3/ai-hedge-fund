# BTST 指标与因子判读词典

适用对象：已经读过 BTST 完整指南，但在看 `selection_snapshot.json`、`selection_review.md`、frontier 分析报告时，仍然不确定每个指标到底代表什么的读者。

这份文档解决的问题：把 BTST 当前最常见的正向因子、负向 penalty、gate、决策标签和窗口级诊断指标统一成一份“看见指标就知道该怎么解释”的词典。

建议搭配阅读：

1. [01-btst-complete-guide.md](./01-btst-complete-guide.md)
2. [03-btst-one-page-cheatsheet.md](./03-btst-one-page-cheatsheet.md)
3. [06-btst-troubleshooting-playbook.md](./06-btst-troubleshooting-playbook.md)
4. [../../product/arch/pre_layer_short_trade_boundary_score_fail_frontier_summary_20260329.md](../../product/arch/pre_layer_short_trade_boundary_score_fail_frontier_summary_20260329.md)
5. [../../product/arch/layer_c_bearish_conflict_release_queue_summary_20260329.md](../../product/arch/layer_c_bearish_conflict_release_queue_summary_20260329.md)

---

## 1. 先讲结论：BTST 指标要分 5 层看

如果你把所有指标都混在一起，会很容易误判。当前 BTST 的指标建议按下面 5 层看：

1. 候选入口层：这只票有没有资格进入短线比较池。
2. 正向结构层：这只票有没有“明天还有弹性”的结构证据。
3. 负向惩罚层：这只票是不是已经太老、太挤、太高或和 Layer C 冲突。
4. 决策层：系统最终为什么把它判成 `selected`、`near_miss`、`blocked`、`rejected`。
5. 窗口诊断层：当前整批样本的主矛盾到底落在哪一层。

最常见的误判不是“看错数值”，而是把第 2 层和第 3 层混在一起，把第 4 层和第 5 层混在一起。

---

## 2. 候选入口层指标

这一层先回答一个问题：它有没有资格进入短线正式比较。

### 2.1 `candidate_source`

why：先知道样本从哪里来，才能判断后面该不该调入口。

what：当前最重要的来源有两类：

1. `short_trade_boundary`：说明它是短线独立建池补进来的候选。
2. `watchlist_filter_diagnostics` 或历史 `layer_b_boundary`：说明它更像研究主线边界样本或被 watchlist 过滤掉的边界样本。

how：

1. 如果问题样本主要来自 `short_trade_boundary`，先看 admission 规则和 score frontier。
2. 如果问题样本主要来自 `watchlist_filter_diagnostics`，先看 candidate entry 语义是否过宽。
3. 如果历史窗口里问题样本主要来自 `layer_b_boundary`，说明你看到的是旧共享池机制，不能直接拿来论证新 builder 无效。

### 2.2 `candidate_score`

why：它决定候选值不值得被送入正式 BTST 评分。

what：当前是轻量 admission score，不是最终 `score_target`。

how：它主要是 `breakout_freshness`、`trend_acceleration`、`volume_expansion_quality`、`catalyst_freshness`、`close_strength` 的加权和。解释时要注意：

1. 高 `candidate_score` 只能说明入口结构像短线，不代表最终一定过线。
2. 低 `candidate_score` 通常优先解释为入口结构不足，而不是 target 阈值太高。

### 2.3 `metric_data_fail_count`

why：当前一些 frozen replay 源缺原生 `strategy_signals`，会导致弱结构过滤的某些指标无法可靠计算。

what：它表示样本满足了某类 candidate-entry 预条件，但缺少足够高保真指标，因而不能继续做 metric-based 过滤比较。

how：

1. 它高，不等于规则无效。
2. 它更接近“方法学边界”，说明当前源不适合做这类入口实验。
3. 这类结果应先解释为“证据不足”，而不是“规则被否定”。

---

## 3. 正向结构层指标

这一层回答的问题是：如果不看 penalty，这只票有没有明天继续走的理由。

### 3.1 `breakout_freshness`

why：BTST 最核心的问题之一，是今天的强是不是“刚启动”，而不是“已经走完”。

what：它近似衡量突破的新鲜度。

how：

1. 低值通常意味着当前结构更像旧趋势修复、后排补涨或没有真正突破。
2. 在最近窗口里，大量旧 `layer_b_boundary` 候选首先死在这一项，说明主问题更像结构缺失，而不是只差一点阈值。
3. 这项偏低时，优先考虑入口过滤或 builder 语义，不优先考虑 threshold rescue。

### 3.2 `trend_acceleration`

why：短线不是只看趋势存在，而是看趋势是否还在加速。

what：它表示趋势强化程度，而不是长期趋势好坏本身。

how：

1. 它高，意味着次日延续更有可能。
2. 它低，但 `close_strength` 很高时，要警惕“尾盘强但趋势确认不足”。
3. 在 `300502` 这类 candidate-entry 案例里，这项偏低是弱结构语义的重要组成部分之一。

### 3.3 `volume_expansion_quality`

why：没有成交量承接，很多“看起来像启动”的票只是表面强。

what：它衡量放量质量，而不是单纯成交额大。

how：

1. 这项接近 0 时，优先解释为“结构确认不足”。
2. 对 `300502` 这类样本，volume 是最小 separating row 的核心锚点，说明它首先是 zero-volume-expansion 样本。
3. 如果放松这项 floor 导致新增样本次日 close 表现明显变差，说明你引入的是假突破而不是扩覆盖。

### 3.4 `close_strength`

why：收盘强度是“今天买盘是否愿意把强势留到收盘”的直接证据。

what：它刻画的是日内承接和收盘位置质量。

how：

1. 它高但 breakout、volume 都弱时，不应单独当成次日看多证据。
2. 它更适合和 `trend_acceleration` 联动解释。
3. 如果一只票只有 `close_strength` 高，其余关键结构弱，通常更像冲高尾盘而非可持续启动。

### 3.5 `catalyst_freshness`

why：催化是否新鲜，直接决定“今天的强”到底还有没有信息增量。

what：它衡量的是催化支持的新鲜度，而不是新闻条数。

how：

1. 最近完整窗口已经证明，把 `catalyst_freshness_min` 从 `0.12` 放到 `0.00` 可以受控扩覆盖，并保持较好的前置候选质量。
2. 这说明它当前是“可控放松”的入口杠杆，而不是绝对不能动的红线。
3. 但这并不意味着可以继续顺手放松 volume 或 breakout；单项放松成立，不等于组合放松成立。

### 3.6 `sector_resonance`

why：孤立强势和板块共振，在次日延续概率上不是一个等级。

what：它衡量个股与题材、行业、共振环境的同步程度。

how：

1. 它高时，说明个股强不是完全孤立事件。
2. 它低不一定直接判死刑，但会削弱次日持续性解释。
3. 在窗口级诊断中，这项更适合作为辅助项，而不是第一主矛盾。

### 3.7 `layer_c_alignment`

why：BTST 虽然独立于研究目标，但不是完全无视研究侧。

what：它表示短线结构和 Layer C 侧共识之间的对齐程度。

how：

1. 它高，说明研究侧并没有明显反对短线结论。
2. 它低，不一定直接 block，但要警惕后续 `layer_c_avoid_penalty` 和冲突类 gate。
3. 它更像“解释加强项”，不是 admission 主因子。

---

## 4. 负向 penalty 层指标

这一层回答的问题是：为什么它明明有一些优点，系统却仍然不愿意放行。

### 4.1 `stale_trend_repair_penalty`

why：BTST 最怕把旧趋势修复误判成新启动。

what：它惩罚“看上去强，但更像陈旧修复”的结构。

how：

1. 这项高时，优先解释为“趋势年龄问题”。
2. 它高不等于完全没机会，但说明这类票更像尾声、修复或补涨。
3. 在 `300394` 一类样本上，这项与 avoid、extension 一起构成 penalty 主导簇。

### 4.2 `overhead_supply_penalty`

why：上方抛压重，次日即使冲高也容易被砸回。

what：它刻画的是上方套牢和供给压力。

how：

1. 这项高时，优先解释为“空间不干净”。
2. 如果它和 `layer_c_bearish_conflict` 同时高，要警惕重复惩罚。
3. 它更适合和 structural conflict 一起看，而不是单独调权重后期待立刻救回所有样本。

### 4.3 `extension_without_room_penalty`

why：很多票不是不强，而是已经太高、太挤、上方空间不足。

what：它惩罚“延伸过度但剩余空间不够”的结构。

how：

1. 这项高时，优先解释为过度延伸。
2. 它高但 `breakout_freshness` 又低时，通常不是好短线，而是后排末端。
3. frontier 报告里如果很多样本都要同时放松 extension 和 stale 才能被救，说明主问题不是 threshold-only。

### 4.4 `layer_c_avoid_penalty`

why：BTST 不应该盲目逆着研究侧的明确回避信号。

what：它是研究层回避态度对短线评分的负向压制。

how：

1. 它高说明研究层对样本已有较强保留意见。
2. 对 `300394` 这类 penalty 主导样本，单项最大收益往往就来自这项放松。
3. 但单独降低这项往往仍不足以让样本跨过 near-miss，不能把它误当成万能旋钮。

---

## 5. Gate 与决策层标签

### 5.1 `selected`

what：正式通过短线目标规则，且结构、评分、风险约束都达标。

how：

1. 这不等于一定进入 buy orders。
2. 还要继续检查 execution bridge 和 T+1 承接。

### 5.2 `near_miss`

what：已经非常接近通过，通常是下一轮最值得优先审查的边界样本。

how：

1. 它适合做 threshold frontier 或最小 rescue 搜索。
2. 但也要区分是 threshold-only near-miss，还是 penalty/冲突主导样本。

### 5.3 `blocked`

what：它不是简单分数不够，而是存在结构性阻断。

how：

1. 优先看 hard block、structural conflict 和高 penalty 暴露。
2. 不要把 `blocked` 和 `rejected` 混成一个集合做统一阈值实验。
3. 最近窗口里，`300724` 是唯一低成本 near-miss rescue 候选；大部分 blocked 样本不属于统一放宽对象。

### 5.4 `rejected`

what：样本进入了正式评分比较，但没过最终分数或风险约束。

how：

1. 如果它主要集中在 `rejected_short_trade_boundary_score_fail`，主问题通常是 score frontier。
2. 如果它距离 near-miss 普遍还很远，说明你该回到 score construction，而不是降一点阈值。

### 5.5 `layer_c_bearish_conflict`

what：当前最关键的结构冲突类阻断之一。

how：

1. 它存在时，先区分 hard block 和 conflict surcharge 是不是重复惩罚。
2. 当前窗口级 evidence 表明，不应做 cluster-wide 放松，而应优先做 `300724-only` 的 case-based release。

---

## 6. 窗口级诊断指标

### 6.1 `next_high_return_mean`

what：候选集合在 T+1 最高价维度上的平均表现。

how：

1. 它适合回答“有没有短线弹性”。
2. 如果它改善而 `next_close_return_mean` 很差，说明你可能抓到的是冲高回落型样本。

### 6.2 `next_close_return_mean`

what：候选集合在 T+1 收盘维度上的平均表现。

how：

1. 它更接近“次日收盘是否仍站得住”。
2. admission 扩覆盖时，这项比单看 high 更能防止引入垃圾候选。

### 6.3 `next_high_hit_rate@threshold`

what：候选集合中，T+1 冲到目标阈值以上的比例。

how：

1. 它更像弹性命中率。
2. 适合比较两批池子谁更像短线机会集合。

### 6.4 `next_close_positive_rate`

what：T+1 收盘为正的比例。

how：

1. 它是 admission 放松时非常关键的防守指标。
2. 如果样本数增加，但这项显著恶化，通常不能升级默认参数。

### 6.5 `gap_to_near_miss`

what：当前分数距离 near-miss 阈值还有多远。

how：

1. 小 gap 适合做最小 rescue 搜索。
2. 大 gap 说明不要再浪费时间做 threshold-only 实验。

---

## 7. 一张最实用的判读表

| 你看到的现象 | 第一解释 | 第一动作 |
| ------------ | -------- | -------- |
| `breakout_freshness` 普遍很低 | 入口结构缺失 | 先看 builder / admission，不先降 threshold |
| `volume_expansion_quality` 接近 0 | 假突破或弱承接 | 优先做 candidate-entry 过滤或 builder 语义审查 |
| `gap_to_near_miss` 普遍大于 0.06 | 不是阈值差一点 | 回到 score construction 或 penalty 结构 |
| `blocked` 高于 `rejected` | 结构冲突主导 | 先看 hard block / conflict surcharge |
| `next_high_return_mean` 好但 `next_close_return_mean` 差 | 冲高回落 | admission 可能放热过度 |
| `catalyst_freshness` 是唯一集中失败项 | 可控扩覆盖候选 | 先做 catalyst-only 变体 |

---

## 8. 一句话总结

BTST 指标最重要的不是背定义，而是形成一个稳定顺序：先看来源，再看正向结构，再看 penalty，再看决策标签，最后再看窗口级质量指标。只要顺序不乱，你就不会轻易把“入口问题”误判成“阈值问题”，也不会把“结构性阻断”误判成“差一点就能救回来”。
