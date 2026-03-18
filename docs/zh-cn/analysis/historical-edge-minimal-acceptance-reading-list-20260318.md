# 2026-03-18 历史 edge 最小验收读单

## 1. 文档目的

这份读单只服务一个场景：后续如果要快速复核当前历史 edge 样本库是否仍守住既有边界，最少应该看哪些文件、分别确认什么。

它不是新的分析文档，而是对现有 benchmark、inventory 和日期矩阵的最短读取路径压缩。

## 2. 三步完成最小验收

### 第一步：先确认三条 benchmark 仍是唯一硬基线

必读文件：

1. [edge-sample-benchmark-20260318.md](./edge-sample-benchmark-20260318.md)

读完应确认的事实：

1. 固定 benchmark 仍只有三条：`20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`。
2. `20260224 / 600519` 代表“应当放出”的历史阈值边缘样本。
3. `20260226 / 600519` 代表“仍应保持不过线”的历史边界样本。
4. `20260226 / 300724` 代表“不能绕过 re-entry 保护重新回补”的当前长窗口边缘样本。

### 第二步：回看三条 benchmark 的一手 artifact

必读文件：

1. [data/reports/live_replay_600519_20260224_p1.json](../../data/reports/live_replay_600519_20260224_p1.json)
2. [data/reports/live_replay_600519_20260226_p1.json](../../data/reports/live_replay_600519_20260226_p1.json)
3. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)

读完应确认的事实：

1. `20260224 / 600519` 仍是 `watch + bc_conflict = null`，且 `score_final` 位于应放出的边缘区。
2. `20260226 / 600519` 仍是 `watch + bc_conflict = null`，但保持 near-threshold 不过线。
3. `20260226 / 300724` 仍是 `watch + bc_conflict = null` 的 clean 边缘样本，但在 re-entry 保护下不能被低质量回补。

### 第三步：确认没有把机制样本或冲突样本误当新候选

必读文件：

1. [historical-edge-evidence-inventory-20260318.md](./historical-edge-evidence-inventory-20260318.md)
2. [historical-edge-date-coverage-matrix-20260318.md](./historical-edge-date-coverage-matrix-20260318.md)

读完应确认的事实：

1. `603993`、`300065`、`688498` 已经是机制样本，不再是第四 benchmark 候选。
2. `600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308` 已经有稳定的 conflict/suppression 入口。
3. `601600` 仍只是低优先级观察对象。
4. 当前缺的不是索引，而是新的 clean near-threshold non-conflict 一手样本。

## 3. 一页式验收口径

如果只允许保留一页口径，应该记住下面四条：

1. benchmark 只有三条，不增不减。
2. 机制样本和 conflict 样本都已有稳定 evidence 入口，不应重新打开资格讨论。
3. 没有新的 clean near-threshold non-conflict 证据之前，不做新的全局放松实验。
4. 后续工作优先继续维护只读索引，而不是改 runtime。

## 4. 最短跳转路径

如果时间更少，可以只按这个顺序跳转：

1. [edge-sample-benchmark-20260318.md](./edge-sample-benchmark-20260318.md)
2. [data/reports/live_replay_600519_20260224_p1.json](../../data/reports/live_replay_600519_20260224_p1.json)
3. [data/reports/live_replay_600519_20260226_p1.json](../../data/reports/live_replay_600519_20260226_p1.json)
4. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)
5. [historical-edge-evidence-inventory-20260318.md](./historical-edge-evidence-inventory-20260318.md)

## 5. 当前状态

截至 `2026-03-18`：

1. 这份最小验收读单已经足够复核当前历史 edge 样本库的核心边界。
2. 它不替代更细的 inventory 和 date matrix，只是为后续接手提供最低成本入口。
3. 当前结论仍然不变：样本库更干净了，但 benchmark 仍固定为三条。