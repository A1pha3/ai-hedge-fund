# BTST 5D/+15% runner 与 payoff 目标重对齐设计（2026-05-28）

## 背景

基于当前已经沉淀的周度回测与扩窗验证，BTST 短线系统的主矛盾已经比较稳定：

1. 正式 `selected` 层更像是在优化 `T+1 / T+2` continuation；
2. 用户真正要的目标是：**买入后 5 个交易日内，55% 以上概率出现相对买入价 `+15%` 以上的扩张**；
3. 因此系统现在的正式层排序目标，和最终收益目标并没有完全对齐。

默认分析窗口采用最近一个完整交易周：`2026-05-18 ~ 2026-05-22`。  
当前已知的关键证据是：

- `selected` 的 `5D/+15%` 命中率只有 `20.00% (3/15)`；
- `near_miss` 反而达到 `45.07% (32/71)`；
- 本周被正式层抬进去的 `short_trade_boundary` / `layer_c_watchlist` 样本，`5D/+15% hit_rate = 0.00%`；
- 被系统漏掉、但后验上是强 runner 的 false negative，集中来自 `watchlist_filter_diagnostics`。

这说明现在最大的问题不是“候选池不够大”，而是：

- **正式层把低赔率 continuation 样本排得太靠前；**
- **更像 delayed-runner 的样本还停留在正式层之外。**

## 目标

设计下一轮 BTST 优化，使系统更接近用户的最终目标：

1. 提升正式层 `selected` 的 `5D/+15%` 命中率；
2. 保持对 delayed-runner 的识别与复审能力，而不是简单放宽所有门槛；
3. 在不打穿 false-positive 预算的前提下，逐步把“更像 runner 的样本”从正式层外部引回到可控复审链路。

本轮交付物是：**一条可回测、可 rollout、可写入中文方案文档的受控优化路径**，不是直接改 live 默认执行逻辑。

## 非目标

1. 不在本轮直接把任何 shadow 变体升级为 live 默认 profile；
2. 不简单放宽全局阈值去追更多票；
3. 不把所有 `watchlist_filter_diagnostics` 票一刀切抬进正式层；
4. 不在缺少样本外验证时，把 `5D/+15%` 目标直接替换全部现有 continuation 目标。

## 备选方案

### 方案 A：formal-source downrank / exclusion shadow（推荐先做）

做法：

1. 对 `short_trade_boundary` 与 `layer_c_watchlist` 做 formal `selected` 层的 source-specific downrank / exclusion shadow；
2. 保留 `near_miss` / 观察层可见性，不做粗暴删除；
3. 先验证正式层 `5D/+15%` 是否明显改善，再决定是否进入更大 rollout。

优点：

1. 直接处理当前最明确的 formal payoff drag；
2. 改动边界清楚，便于验证；
3. 对 false-positive 预算更友好。

缺点：

1. 只能先解决“谁不该进正式层”，不能直接解决“谁应该补进正式层”；
2. 对 delayed-runner 的召回提升有限。

### 方案 B：payoff-first rerank + runner recall promotion（推荐并行设计、随后验证）

做法：

1. 针对 `watchlist_filter_diagnostics` 中被系统漏掉、但更像 delayed-runner 的样本，建立 payoff-first recall lane；
2. 不直接把这些票升级成正式层，而是先进入受控复审 / promotion 链路；
3. 结合 source、催化、后续扩张强度与 false-positive 预算，决定是否允许从 recall lane 升到更高优先级。

优点：

1. 直接针对 false negative 主因；
2. 更贴近用户要的 `5D/+15%` runner 目标；
3. 能补足当前正式层只看 continuation 的偏差。

缺点：

1. 设计更复杂；
2. 如果没有预算约束，容易把低分噪声也带回来。

### 方案 C：直接重写目标体系，全面改成 5D/+15% 标签

做法：

1. 重建标签、评分目标、阈值与 explainability；
2. 用 `5D/+15%` 目标替换现有 continuation 倾向更强的目标栈。

优点：

1. 从根上解决“目标错位”；
2. 最贴近最终用户目标。

缺点：

1. 风险最大；
2. 工程面和统计面都更重；
3. 当前不适合作为下一步的第一落点。

## 推荐方案

采用 **方案 A + 方案 B 的分阶段组合**：

1. **先用方案 A 收 formal payoff drag**，把已经证明会拖累 `5D/+15%` 的 formal 来源做 source-specific shadow 收缩；
2. **再用方案 B 补 runner recall**，把当前被压在正式层外的 delayed-runner 通过 payoff-first 复审链路带回来；
3. **方案 C 作为后续大项目**，等 A/B 跑出稳定证据后再决定要不要重写目标体系。

原因：

- 当前证据已经足够说明谁在拖正式层后腿；
- 也已经能看到强 runner 主要漏在哪条来源链路；
- 但还没有到可以直接推翻整个目标栈的程度。

## alpha / beta / gamma 的职责分配

### alpha：标签与统计验证

alpha 负责：

1. 定义 `5D/+15%` payoff-first 评估口径；
2. 拆出 `continuation` 与 `runner` 的样本差异；
3. 验证 source-specific shadow 与 recall lane 是否具有统计稳健性；
4. 防止过拟合和单周偶然性。

### beta：执行链路与 explainability

beta 负责：

1. 把 formal-source downrank / exclusion shadow 做成可解释、可回放的执行前链路；
2. 让 recall lane 的 promotion 条件在 explainability 中可见；
3. 保证不是靠“放宽所有门槛”来提高 runner 命中。

### gamma：风险预算与 rollout

gamma 负责：

1. 给 recall lane 和 source shadow 设 false-positive 预算；
2. 决定哪些候选变体只能停留在 shadow，哪些允许进入 rollout；
3. 保证提升 `5D/+15%` 的同时，不把 execution quality 整体打穿。

## 设计

### 1. formal-source shadow 收缩层

目标：先降低 formal `selected` 层中已经确认拖累 payoff 的来源权重。

本轮优先对象：

1. `layer_c_watchlist`
2. `short_trade_boundary`（先做 shadow 验证，不直接全局收紧）

预期行为：

1. formal `selected` 暴露下降；
2. `near_miss` / 观察层仍保留可见性；
3. 重点看 `5D/+15%` 是否改善，而不是只看 `T+2`。

### 2. payoff-first runner recall lane

目标：把当前被 `watchlist_filter_diagnostics` 压掉、但后验强 runner 的样本，纳入受控复审。

预期行为：

1. recall lane 不等于正式执行层；
2. 只有满足更强催化 / 后续扩张特征的 delayed-runner 才能进入 promotion 观察；
3. 所有提升都必须挂接 false-positive 预算。

### 3. 统一评估面

下一轮验证不再只看：

1. `T+2 close return`
2. `next_close_positive_rate`

而要统一看：

1. `5D/+15% hit_rate`
2. `mean_max_future_high_return_2_5d`
3. false-positive / false-negative 变化
4. `T+2` 是否只是温和回撤，而不是主目标反噬

## 数据流

目标数据流应当是：

`weekly BTST report batch -> source split diagnosis -> formal-source shadow replay -> runner recall replay -> false-positive budget check -> rollout decision -> 中文方案文档`

这里必须显式区分两条线：

1. **formal-source 收缩线**：解决“谁不该进正式层”；
2. **runner recall 补偿线**：解决“谁值得从正式层外部被带回来复审”。

## 验证规则

### 主验证规则

只有同时满足以下条件，方案才可以进入下一步 rollout 文档：

1. 正式 `selected` 的 `5D/+15% hit_rate` 提升；
2. false-positive 没有明显恶化；
3. recall lane 带回来的 runner，不是靠广泛放宽阈值得到；
4. 提升结果在扩窗样本里仍然成立，而不是单周偶然。

### 否决条件

出现以下任一情况，方案直接停留在 shadow：

1. `T+2` 质量大幅崩塌，但 `5D/+15%` 提升不显著；
2. recall lane 带回大量低质量噪声；
3. 样本只在一周内成立，扩窗后失效；
4. explainability 无法区分 source shadow 与 recall promotion。

## 测试与工件

下一轮必须产出的工件：

1. source-specific weekly replay / aggregate JSON
2. recall lane false-negative / false-positive 诊断 JSON
3. 受控 rollout 决策工件
4. 中文优化方案文档，落在 `docs/prompt/generate_file/optimize_methord/`

## 风险与边界

最大风险不是“方案不够激进”，而是：

1. 为了追 runner，把太多低质量样本重新抬回执行链；
2. 把单周有效样本误判成长期结构结论；
3. 把 formal-source 问题和 recall 问题混成一条线，导致验证失焦。

所以这轮必须坚持：

1. source shadow 与 recall lane 分开验证；
2. payoff-first 指标与 continuation 指标同时保留；
3. 所有推进都要经过样本外和 rollout 预算检查。

## 结论

下一轮 BTST 优化不该从“放宽阈值”开始，而应该从 **formal payoff drag 收缩 + delayed-runner recall 补偿** 开始。

也就是说：

1. 先把不该进正式层的来源收掉；
2. 再把真正像 runner、但被压在正式层外的样本，放进受控复审链路；
3. 等这两条线都稳定后，再考虑是否升级到更大范围的 5D/+15% 目标重构。
