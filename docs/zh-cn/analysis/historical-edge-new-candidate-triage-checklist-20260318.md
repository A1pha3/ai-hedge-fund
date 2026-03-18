# 2026-03-18 历史 edge 新样本分诊清单

## 1. 文档目的

这份清单只服务一个场景：后续如果历史 reports 里又出现新的 ticker/date，应该先按什么顺序分诊，才能避免把旧结论重新打开，或者把 conflict/机制样本误当成新的 clean benchmark 候选。

它不新增任何 runtime 假设，也不放松现有准入标准，只把当前已经稳定的补证流程压成一张固定检查表。

如果只需要更短的入口，可以直接看 [historical-edge-triage-decision-tree-20260318.md](./historical-edge-triage-decision-tree-20260318.md)。

## 2. 固定前提

开始分诊前，先锁定三条前提：

1. benchmark 仍固定为 `20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`。
2. `603993`、`300065`、`688498` 已经收口为机制样本，不重新进入 benchmark 候选池。
3. `600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308` 已经有稳定 conflict/suppression 解释，不因为 isolated watch 切片重开专项。

## 3. 分诊顺序

### 第一步：先查结构化扫描结果

必读文件：

1. [data/reports/historical_edge_sample_scan_20260318.json](../../data/reports/historical_edge_sample_scan_20260318.json)
2. [historical-edge-followup-scan-20260318.md](./historical-edge-followup-scan-20260318.md)

检查项：

1. 对象是否出现在 `near_threshold_watch` 或 `sub_threshold_watch`。
2. 如果对象只出现在 `high_score_watch`，默认先降为低优先级观察位，不直接进入补证池。
3. 如果 follow-up 文档已经明确否决，直接停止追踪。

### 第二步：再查是否已被库存覆盖

必读文件：

1. [historical-edge-artifact-index-20260318.md](./historical-edge-artifact-index-20260318.md)
2. [historical-edge-evidence-inventory-20260318.md](./historical-edge-evidence-inventory-20260318.md)
3. [historical-edge-date-coverage-matrix-20260318.md](./historical-edge-date-coverage-matrix-20260318.md)

检查项：

1. 对象是否已经被 benchmark、机制样本、conflict/suppression 或观察位覆盖。
2. 对应日期是否已经能在 date matrix 里落到稳定 artifact。
3. 如果 inventory 已经给出归类，就不要重复创建新专项。

### 第三步：只在未覆盖时回到一手 evidence

必读文件类型：

1. 原始 `daily_events.jsonl`
2. 原始 `pipeline_timings.jsonl`
3. 必要时补看对应 `session_summary.json` 或 live replay JSON

检查项：

1. 是否先满足 `decision = watch`。
2. 是否满足 `bc_conflict = null`。
3. `score_final` 是否真的落在 near-threshold 区间，而不是高分实验产物或普通 below-fast-threshold 残留。
4. 证据是否跨 artifact 稳定，而不是只在某个特定实验窗口里跳高。

### 第四步：按四类对象落桶

#### A. benchmark 候选

准入条件：

1. 一手 evidence 先满足 `watch + bc_conflict = null + near-threshold`。
2. 不属于已知机制样本。
3. 不属于已知 conflict/suppression 对象。
4. 跨 artifact 语义稳定。

动作：

1. 这类对象才值得新开专项补证文档。

#### B. 机制样本

识别信号：

1. 类似 `603993` 的跨层跳变。
2. 类似 `300065` 的 Layer B 压线后被 Layer C 强 bearish 打回。
3. 类似 `688498` 的第三条腿缺失或中性稀释。

动作：

1. 归入机制样本，不进入 benchmark 候选池。

#### C. conflict/suppression 样本

识别信号：

1. 在 [historical-edge-conflict-suppression-reading-list-20260318.md](./historical-edge-conflict-suppression-reading-list-20260318.md) 对应的主入口里已有高优先级解释。
2. 主语义是 `b_positive_c_strong_bearish` 或 watchlist suppression。

动作：

1. 归入排除样本，不重开专项。

#### D. 低优先级观察位

识别信号：

1. 类似 `601600`，只在 `high_score_watch` 或特定实验产物里出现。
2. baseline 或其他 artifact 里语义不稳定。

动作：

1. 只保留记录，不进入当前补证池。

## 4. 最小停止条件

满足下面任一条件就应停止继续深挖：

1. 对象已经在现有 inventory 里有稳定归类。
2. 一手 evidence 无法同时满足 `watch + bc_conflict = null + near-threshold`。
3. 正向记录只来自单一实验产物，而 baseline 语义明显回落。
4. 更高优先级 conflict/suppression artifact 已经给出统一解释。

## 5. 当前口径

截至 `2026-03-18`，这份清单对应的固定口径是：

1. 当前历史样本库仍只有三条 benchmark。
2. 当前缺的不是旧对象的入口，而是新的 clean 一手证据。
3. 在没有新的 clean near-threshold non-conflict 证据之前，继续做只读分诊、索引和补证收口，不触碰 runtime。
