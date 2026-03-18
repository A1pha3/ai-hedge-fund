# 2026-03-18 688498 补证：它是第三条腿缺失与中性稀释样本，不是 clean edge benchmark

## 1. 结论先行

这轮补证之后，688498 的定位也可以固定下来：

1. 它不是新的 clean edge benchmark。
2. 它也不是当前优先级很高的历史 edge 候选。
3. 它更像一条“trend 和 fundamental 都为正，但缺少第三条增量腿，同时被中性 mean_reversion 稀释”的机制样本。

因此，688498 目前只适合作为低优先级机制线索保留，不应继续被当作第四个 benchmark 候选。

## 2. 证据链

### 2.1 历史结构化扫描里没有它的 clean watch 足迹

在 data/reports/historical_edge_sample_scan_20260318.json 中，没有出现 688498 的 near-threshold non-conflict watch 记录。

这意味着：

1. 它没有像 600519、300724 那样在结构化历史产物里自然长出 clean watch 证据；
2. 单靠现有 reports，无法把它提升为可复用的 benchmark 样本。

### 2.2 一手回放里，它最接近阈值时也只是停在 fast gate 下方

在 data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl 的 20260205 current plan 中，688498 的记录是：

1. score_b = 0.3725
2. decision = watch
3. reason = below_fast_score_threshold

这条记录很关键，因为它说明：

1. 688498 的确到过阈值附近；
2. 但它停在 0.38 fast gate 下方，没有自然进入 Layer B 通过区；
3. 它的主要形态仍然是上游 near-threshold residue，而不是 final watch 样本。

### 2.3 文档级分析显示它不是被 hard negative 压下去，而是缺少第三条增量腿

在 docs/zh-cn/analysis/pipeline-funnel-scan-202602-window-20260312.md 中，对 688498 的解释已经相当完整：

1. 20260205 时它的 fundamental 并不差；
2. `profitability` 为正；
3. `growth` 为正；
4. `financial_health` 为强正；
5. 没有明显的 fundamental 显式负项；
6. 但总分仍然只停在 `0.3516`。

文档给出的原因是：

1. `trend` 约贡献 `0.2054`；
2. `fundamental` 约贡献 `0.1461`；
3. `mean_reversion` 中性，贡献接近 `0`；
4. `event_sentiment` 缺席，贡献为 `0`。

因此 688498 的核心问题不是“某个 hard negative 把它打没了”，而是：

1. 两条正腿还不够；
2. 第三条增量腿没有出现；
3. 最终自然停在 fast threshold 下方。

### 2.4 更深一层的问题是 mean_reversion 的中性稀释

同一份分析文档继续往下给出了更重要的一层机制：

1. 688498 的 `mean_reversion` 在 20260205 几乎是一个“全中性包”；
2. 但这些中性子因子仍带着 `completeness = 1.0` 进入聚合；
3. 这会在权重归一化时稀释已经为正的 `trend` 和 `fundamental`。

文档中的反事实结果是：

1. 如果把这些中性 `mean_reversion` 子因子移出聚合；
2. 688498 的 `score_b` 会从 `0.3516` 直接升到 `0.4688`；
3. 增量达到 `+0.1172`。

这说明 688498 的问题本质上更接近：

1. 第三条腿缺失；
2. 再叠加一个完整中性策略的权重稀释；
3. 所以它不是 benchmark，而是聚合机制样本。

## 3. 为什么它不能进入 benchmark

688498 当前不能进入 benchmark，原因有三个。

### 3.1 它没有 clean watch 的历史结构化证据

这是最直接的一条。没有 clean watch 足迹，就没有资格进入 benchmark 池。

### 3.2 它的问题更像策略结构缺口，不是稳定阈值边界

688498 适合回答的问题是：

1. 当 `trend + fundamental` 都为正时，为什么票仍然过不了 fast gate；
2. `event_sentiment` 缺席与 `mean_reversion` 中性稀释会怎样共同压低总分；
3. 当前聚合逻辑是否会让“完整中性策略”对正向样本形成结构性摊薄。

这类问题属于机制分析，而不是 benchmark 验收。

### 3.3 它在不同产物里更常见的形态仍是 below_fast_score_threshold 残留

现有 reports 中，688498 大量命中都只是：

1. score_b = 0.3725
2. score_b = 0.2573
3. score_b = 0.2295
4. score_b = 0.1981
5. score_b = 0.0

也就是说，它没有收敛成一个稳定的边缘准入样本，而是长期停留在 fast gate 下方的不同深度残留中。

## 4. 更合理的归类

截至当前，688498 更合理的归类应当是：

1. 不是固定 benchmark；
2. 不是当前可准入的第四个 clean edge sample；
3. 是“第三条腿缺失 + 中性 mean_reversion 稀释”机制样本；
4. 当前优先级低于 603993 与 300065，后续若继续补证，应聚焦聚合机制，而不是 watchlist 放宽。

## 5. 对后续工作的约束

这份补证进一步收紧了当前历史扩库结论：

1. benchmark 继续固定为三条：20260224/600519、20260226/600519、20260226/300724；
2. 603993、300065、688498 都不应再被当作第四个 clean benchmark 候选；
3. 在出现新的 near-threshold non-conflict 一手证据前，不应继续推动新的全局规则放松实验。

## 6. 当前结论

截至 2026-03-18：

1. 688498 已完成当前阶段的最低必要补证；
2. 它的证据链足以说明：问题不在 hard negative，而在第三条腿缺失与中性稀释；
3. 因此它只保留为低优先级机制线索，不是新的 clean edge benchmark。