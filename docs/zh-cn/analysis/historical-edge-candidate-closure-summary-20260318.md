# 2026-03-18 历史边缘候选收口总结：603993、300065、688498

## 1. 结论先行

截至 2026-03-18，这一轮历史 edge candidate 收口已经完成，结论可以统一写成一句话：

1. `603993`、`300065`、`688498` 都不能进入 clean edge benchmark。
2. 三者都有研究价值，但价值都落在“形成机制解释”而不是“固定验收边界”。
3. 因此当前固定 benchmark 仍然只有三条：`20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`。

这份总结的目的，是把三份专项补证文档的结论压成一层统一口径，避免后续再次把它们误当成第四个 benchmark 候选。

## 2. 三只票的最终归类

### 2.1 603993：上游形成机制样本

603993 的核心特征是跨层跳变：

1. baseline / scan 里，它主要表现为 Layer B near-threshold 或 sub-threshold；
2. frozen replay 里，它又会被抬成 high-score watch 并真实买入；
3. 随后很快进入 logic stop failure 链并卖出。

因此它的价值在解释：

1. 为什么 near-threshold ticker 会被抬成 high-score watch；
2. 为什么这种抬升会迅速失败。

它不是稳定边界样本，所以不能进入 benchmark。

### 2.2 300065：上游压线与强 bearish avoid 样本

300065 的核心特征是：

1. 在 20260223、20260224、20260225 连续三天停在 Layer B 下沿 `0.3735 / 0.3739 / 0.3736`；
2. 历史结构化 scan 里没有 clean near-threshold watch 足迹；
3. 长窗回放里它可以过 Layer B，但会被 investor bearish Layer C 强烈压回 `decision = avoid`；
4. 因子分析显示其根因更像 `profitability` 硬负项 cliff，而不是 arbitration 误杀。

因此它的价值在解释：

1. 为什么票会长期贴在 fast gate 下沿；
2. 为什么即使穿过 Layer B，也会被 Layer C 直接打回。

它同样不是稳定边界样本，所以不能进入 benchmark。

### 2.3 688498：第三条腿缺失与中性稀释样本

688498 的核心特征是：

1. `trend + fundamental` 同时为正，但历史结构化 scan 里没有 clean watch 足迹；
2. 一手 replay 中最接近阈值时也只是 `score_b = 0.3725`，停在 fast gate 下方；
3. 它没有明显 hard negative fundamental blocker；
4. 真正的问题是缺少第三条增量腿，同时 `mean_reversion` 以中性 completeness 参与聚合，稀释了已有正项。

因此它的价值在解释：

1. 为什么两条正腿仍然不足以过线；
2. 中性策略参与归一化时如何摊薄正向分数。

它也不是稳定边界样本，所以不能进入 benchmark。

## 3. 三者之间的差异

虽然三只票都被降格为机制样本，但它们并不是同一类型：

1. `603993` 是跨层跳变型：near-threshold 或 sub-threshold -> high-score watch -> buy -> logic stop。
2. `300065` 是硬负项压线型：Layer B 连续压线 -> Layer C 强 bearish -> avoid。
3. `688498` 是结构缺口型：没有明显 hard negative，但缺少第三条增量腿，且被中性策略稀释。

这三个结论合起来说明，当前未能扩出第四个 benchmark，并不是因为所有候选都“只差一点”，而是因为它们卡住的机制根本不同。

## 4. 对后续工作的直接约束

这轮收口完成后，后续工作应遵守三条约束：

1. 不要把 `603993`、`300065`、`688498` 再次当成第四个 clean benchmark 候选。
2. benchmark 继续固定为 `20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`。
3. 在找到新的 clean near-threshold non-conflict 一手证据之前，不做新的全局 Layer C / watchlist / avoid 放松实验。

## 5. 当前阶段的意义

这一轮工作的价值不在“增加了几个候选”，而在于把候选库收得更干净：

1. 603993 从潜在 benchmark 候选收紧为形成机制样本；
2. 300065 从待补证候选收紧为压线与 avoid 机制样本；
3. 688498 从低优先级候选收紧为第三条腿缺失与中性稀释样本；
4. 当前样本库因此变得更小，但证据质量更高。

## 6. 当前结论

截至 2026-03-18：

1. 这三只票的专项补证已经完成；
2. 三者都不再属于第四个 benchmark 候选池；
3. 当前历史 edge sample 扩库仍未产生新的 clean benchmark；
4. 下一步若继续推进，应转向寻找新的 clean 一手证据，而不是继续围绕这三只票做全局放宽推演。