# 2026-03-18 历史 edge 索引刷新协议

## 1. 文档目的

这份协议只回答一个问题：未来如果 `data/reports` 下出现了新的 replay、paper trading 或扫描产物，应该按什么顺序刷新当前这套历史 edge 索引，而不是重新从头分析。

## 2. 适用前提

执行这份协议前，默认下面四点仍成立：

1. benchmark 固定为 `20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`。
2. `603993`、`300065`、`688498` 仍按机制样本处理。
3. `600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308` 仍按 conflict/suppression 处理。
4. `601600` 仍只保留观察位。

如果这四点里有任意一点被新的 clean 一手证据直接推翻，才值得新开专项补证。

## 3. 刷新顺序

### 第一步：先重跑结构化扫描

使用脚本：

1. [scripts/scan_historical_edge_samples.py](../../scripts/scan_historical_edge_samples.py)

目标：

1. 确认新的 ticker/date 是否进入 `near_threshold_watch` 或 `sub_threshold_watch`。
2. 如果对象只进入 `high_score_watch`，先按观察位处理。
3. 如果扫描结果没有新增 near-threshold non-conflict 对象，协议到此可以停止。

### 第二步：对照既有 inventory 和 date matrix

必看文档：

1. [historical-edge-evidence-inventory-20260318.md](./historical-edge-evidence-inventory-20260318.md)
2. [historical-edge-date-coverage-matrix-20260318.md](./historical-edge-date-coverage-matrix-20260318.md)
3. [historical-edge-triage-decision-tree-20260318.md](./historical-edge-triage-decision-tree-20260318.md)

目标：

1. 判断新增对象是否其实已经被现有库存覆盖。
2. 如果对象已被覆盖，就只更新索引，不新开专项。
3. 只有未覆盖对象才进入下一步。

### 第三步：回到原始 evidence 做最小确认

必看文件类型：

1. 原始 `daily_events.jsonl`
2. 原始 `pipeline_timings.jsonl`
3. 必要时补看 live replay JSON 或 `session_summary.json`

最小准入条件：

1. `decision = watch`
2. `bc_conflict = null`
3. `score_final` 落在 near-threshold 区间
4. 语义在多个 artifact 间稳定，而不是单一实验跳高

只要有任一条件不满足，就停止新增专项文档。

### 第四步：只更新必要文档

按结果分流：

1. 如果没有新对象，只更新扫描输出和必要的状态说明。
2. 如果只是把对象进一步压实为机制样本、conflict/suppression 或观察位，只更新对应 inventory、date matrix、reading list 或 handoff。
3. 只有出现新的 clean 候选，才新建专项补证文档。

## 4. 推荐更新顺序

如果真的需要改文档，顺序固定为：

1. 先更新扫描结果或 follow-up 结论。
2. 再更新 evidence inventory 和 date coverage matrix。
3. 再更新 overview、handoff、artifact index 这些入口页。
4. 最后才考虑是否新增新的专项补证文档。

## 5. 停止条件

满足下面任一条件，就说明这次刷新不需要继续扩展：

1. 新 reports 没带来新的 near-threshold non-conflict 对象。
2. 新对象已经被现有 inventory 覆盖。
3. 新对象的正向信号只存在于单一实验片段。
4. 更高优先级 conflict/suppression artifact 已经给出统一解释。

## 6. 当前口径

截至 `2026-03-18`，这份协议的核心原则是：先刷新 scan，再做分诊，再决定是否写新文档；默认不碰 runtime。
