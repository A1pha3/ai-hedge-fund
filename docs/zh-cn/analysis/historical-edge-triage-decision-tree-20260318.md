# 2026-03-18 历史 edge 新样本单页决策树

## 1. 文档目的

这份文档只保留一个用途：当新的 ticker/date 出现时，用最短路径判断它是 benchmark 候选、机制样本、conflict/suppression，还是仅应保留为观察位。

## 2. 决策树

### 起点：先锁定固定边界

1. benchmark 仍固定为 `20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`。
2. `603993`、`300065`、`688498` 已经是机制样本。
3. `600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308` 已经是 conflict/suppression 样本。
4. `601600` 仍是低优先级观察位。

### Step 1: 先看扫描桶

必查文件：

1. [data/reports/historical_edge_sample_scan_20260318.json](../../data/reports/historical_edge_sample_scan_20260318.json)

判断：

1. 如果对象只出现在 `high_score_watch`，先归入观察位，不直接开专项。
2. 如果对象出现在 `near_threshold_watch` 或 `sub_threshold_watch`，进入 Step 2。
3. 如果扫描里根本没有，先停止，不做补证。

### Step 2: 再看是否已被库存覆盖

必查文件：

1. [historical-edge-evidence-inventory-20260318.md](./historical-edge-evidence-inventory-20260318.md)
2. [historical-edge-date-coverage-matrix-20260318.md](./historical-edge-date-coverage-matrix-20260318.md)

判断：

1. 如果 inventory 已经有稳定归类，直接停止，不重开专项。
2. 如果 date matrix 已经能落到固定 artifact，也先按既有归类处理。
3. 只有未被库存覆盖的对象，才进入 Step 3。

### Step 3: 回到一手 evidence

必查文件类型：

1. 原始 `daily_events.jsonl`
2. 原始 `pipeline_timings.jsonl`
3. 必要时补看 live replay JSON 或 `session_summary.json`

判断：

1. 若不满足 `decision = watch`，停止。
2. 若 `bc_conflict != null`，归入 conflict/suppression。
3. 若 `score_final` 不在 near-threshold 区间，停止。
4. 若只在单一实验产物里跳高，而 baseline 不稳定，归入观察位。
5. 若满足 `watch + bc_conflict = null + near-threshold` 且跨 artifact 稳定，进入 Step 4。

### Step 4: 最终落桶

1. 若语义稳定且不属于既有机制链，归入 benchmark 候选，可以新开专项补证。
2. 若表现为跨层跳变、Layer B 压线后被 Layer C 打回、或第三条腿缺失，归入机制样本。
3. 若高优先级解释是 `b_positive_c_strong_bearish` 或 watchlist suppression，归入 conflict/suppression。
4. 若只在高分实验片段里出现且跨 artifact 不稳定，归入观察位。

## 3. 最小停止条件

满足任一条件就停止继续分析：

1. 已被现有 inventory 覆盖。
2. 不满足 `watch + bc_conflict = null + near-threshold`。
3. 高优先级 conflict/suppression artifact 已经给出统一解释。
4. 正向证据只来自单一实验窗口。

## 4. 当前口径

截至 `2026-03-18`：

1. 当前真正稀缺的是新的 clean 一手证据，不是新的规则放松空间。
2. 后续优先动作仍是只读分诊、文档索引和补证收口。
3. 在没有新 clean 证据前，不触碰 runtime。
