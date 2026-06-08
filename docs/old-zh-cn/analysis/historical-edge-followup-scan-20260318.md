# 2026-03-18 历史 edge follow-up 扫描：未发现新的 clean near-threshold 候选

## 1. 结论先行

本轮 follow-up 只读扫描的结论很直接：

1. 当前历史 reports 里仍未发现第四个 clean near-threshold non-conflict 一手样本。
2. 固定 benchmark 继续保持三条：`20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`。
3. 603993、300065、688498 之外，唯一需要额外复核的新名字只剩 `601600`，但复核后也不应进入补证池。
4. 因而当前历史扩库可以视为阶段性见顶，下一步不应转向新的全局规则放松实验。

## 2. 本轮复核范围

本轮没有改 runtime，只复核了以下证据：

1. `data/reports/historical_edge_sample_scan_20260318.json`
2. 已有中文分析文档与专项补证结论
3. `601600` 在原始 reports 中的直接记录

复核目标只有一个：在不推翻既有收口结论的前提下，判断是否还存在未被专项否决、且真正满足 `watch + bc_conflict = null + near-threshold` 的新样本。

## 3. 扫描结果的剩余空间

结构化扫描结果本身已经非常收敛：

1. `near_threshold_watch` 只剩 `300724`、`600519`、`600988`
2. `sub_threshold_watch` 只剩 `600519`、`603993`
3. `high_score_watch` 只剩 `300724`、`600519`、`601600`、`603993`

结合已有结论后：

1. `600988` 已被既有高优先级文档明确排除为结构性冲突噪声样本
2. `603993` 已完成补证，收口为上游形成机制样本
3. `300724`、`600519` 已是固定 benchmark

因此，本轮真正还需要额外复核的新名字只有 `601600`。

## 4. 601600 为什么不能进入候选池

### 4.1 它只出现在 `high_score_watch`，而不是 near-threshold 桶

在 `historical_edge_sample_scan_20260318.json` 中，`601600` 的结构化摘要是：

1. 只出现在 `high_score_watch`
2. 日期集中在 `20260202`、`20260203`
3. `score_final` 范围是 `0.3195 ~ 0.3630`
4. 来源主要是 `paper_trading_window_20260202_20260303_exit_fix_cooldown5` 相关 artifacts

这已经说明它不属于本轮要找的对象，因为当前目标是 clean near-threshold non-conflict 样本，而不是高分 watch 样本。

### 4.2 一手 records 显示它更像实验产物里的高分或截断样本

在 `paper_trading_window_20260202_20260303_exit_fix_cooldown5` 的原始记录里，`601600` 的代表形态包括：

1. `score_b = 0.3838`、`decision = watch`，但在 Layer B 被标记为 `high_pool_truncated_by_max_size`
2. 同组产物里它对应的 `score_final` 可到 `0.3630`

这类记录说明的是：

1. 它不是贴着 watchlist 边界上下波动的样本
2. 它更像某个特定 exit-fix 实验里的高分 watch 或容量截断残留
3. 这类样本不能直接转译成 benchmark 或 clean edge 候选

### 4.3 baseline 与其他产物里，它又退回普通 below-fast-threshold 残留

和上面的高分实验切片相比，`601600` 在 baseline 与其他 pipeline artifacts 中更常见的形态反而是：

1. `score_b = 0.1021`
2. `score_b = 0.1027`
3. `score_b = 0.1038`
4. `score_b = 0.1962`
5. `score_b = 0.2732`

并且这些记录普遍是：

1. `reason = below_fast_score_threshold`
2. `decision = neutral`

也就是说，`601600` 并没有形成稳定、跨产物一致的 near-threshold watch 边界形态，而是在不同实验上下文之间大幅跳变。

### 4.4 因此它既不是 benchmark，也不是优先补证对象

综合起来，`601600` 的问题和 603993 类似但更弱：

1. 它缺少 clean near-threshold 证据
2. 它的正向记录主要来自特定实验产物
3. 它在 baseline 视角下并不稳定

因此，它不能进入当前补证池，更不能被当作第四个 benchmark 候选。

## 5. 当前阶段判断

截至本轮 follow-up：

1. 历史结构化 reports 没有再给出新的 clean near-threshold non-conflict 一手证据
2. 当前扩库池已经完成一次有效收缩，边界比之前更干净
3. 历史扩库在现有 reports 范围内可以视为阶段性见顶

这里的“见顶”指的是证据库暂时穷尽，不是要求转向实盘部署，也不是要求去放松 runtime 规则制造样本。

## 6. 下一步最合理的低风险方向

在保持现有 benchmark 与规则约束不变的前提下，后续最合理的低风险方向是：

1. 继续做只读 inventory，把未纳入 `historical_edge_sample_scan_20260318.json` 的 targeted replay / live replay / tradeoff 报告按 `ticker/date` 建成补证索引
2. 新样本只接受一类准入条件：必须先出现 `watch + bc_conflict = null + score_final` 接近 watchlist 阈值的一手证据，再决定是否写专项补证
3. 如果索引层面仍没有新的一手 clean 证据，就明确接受“当前历史样本库只有三条 benchmark”的状态，等待未来 reports 自然积累，而不是继续做全局规则放松试验

## 7. 当前结论

截至 `2026-03-18`：

1. 本轮 follow-up 没有找到新的 clean edge benchmark 候选
2. `601600` 已完成最低必要复核，结论是不进入补证池
3. benchmark 继续固定为 `20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`
4. 下一步应继续坚持只读扩库与证据索引，而不是触碰 runtime 行为