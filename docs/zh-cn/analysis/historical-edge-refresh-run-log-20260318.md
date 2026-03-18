# 2026-03-18 历史 edge refresh protocol 首次实战记录

## 1. 目的

这份 run log 用来完成 P0-3：把一次真实的 historical edge refresh 过程，按 [historical-edge-refresh-protocol-20260318.md](./historical-edge-refresh-protocol-20260318.md) 的顺序固化下来，保证后续可以按同样步骤复刻，而不是依赖口头经验。

本次实战的目标不是发现新对象，而是验证协议在“没有新 clean 样本进入”的情况下，能否快速停止并留下足够清晰的记录。

## 2. 输入

1. [historical-edge-refresh-protocol-20260318.md](./historical-edge-refresh-protocol-20260318.md)
2. [../../scripts/scan_historical_edge_samples.py](../../scripts/scan_historical_edge_samples.py)
3. [historical-edge-evidence-inventory-20260318.md](./historical-edge-evidence-inventory-20260318.md)
4. [historical-edge-date-coverage-matrix-20260318.md](./historical-edge-date-coverage-matrix-20260318.md)
5. [historical-edge-triage-decision-tree-20260318.md](./historical-edge-triage-decision-tree-20260318.md)

## 3. 执行步骤

### Step 1: 运行结构化扫描

执行方式：

1. 直接调用 `scan_reports()`，扫描 `data/reports`，参数为 `lower_bound=0.14`、`near_min=0.17`、`near_max=0.26`。

扫描结果摘要：

1. `files_scanned = 189`
2. `raw_record_count = 3679`
3. `deduped_record_count = 3471`
4. `near_threshold_watch`：`1075` 条记录，`3` 个 ticker
5. `sub_threshold_watch`：`11` 条记录，`2` 个 ticker
6. `high_score_watch`：`517` 条记录，`4` 个 ticker

桶内 ticker 概览：

1. `near_threshold_watch`：`300724`、`600519`、`600988`
2. `sub_threshold_watch`：`600519`、`603993`
3. `high_score_watch`：`300724`、`600519`、`601600`、`603993`

第一步结论：

1. 这次扫描没有出现新的 ticker。
2. 新增进入 near-threshold 视野的对象里，唯一需要特别复核的是 `600988`，因为它看起来像 near-threshold，但既有口径中已被归入 conflict/suppression。

### Step 2: 对照 inventory 与 date matrix

核对结果：

1. [historical-edge-evidence-inventory-20260318.md](./historical-edge-evidence-inventory-20260318.md) 已明确把 `600988` 放进 Layer C conflict 主入口，并与 `000426`、`000960`、`300251`、`300775`、`600111`、`300308` 同组处理。
2. [historical-edge-date-coverage-matrix-20260318.md](./historical-edge-date-coverage-matrix-20260318.md) 已提供 `20260303` prepared-plan 截面，作为 suppression 主入口日期。
3. benchmark 仍只有 `20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724` 三条，没有出现第四条可替换或追加对象。

第二步结论：

1. `300724`、`600519` 已被 benchmark 库存覆盖。
2. `603993` 已被机制样本库存覆盖。
3. `600988` 已被 conflict/suppression 库存覆盖。
4. 扫描命中的所有 ticker 都已被既有 inventory 吸收，没有对象进入“未覆盖空白区”。

### Step 3: 回看决策树，确认是否需要新开专项

按 [historical-edge-triage-decision-tree-20260318.md](./historical-edge-triage-decision-tree-20260318.md) 逐条判断：

1. `300724`、`600519`：属于固定 benchmark，停止。
2. `603993`：属于已收口机制样本，停止。
3. `600988`：虽然扫描命中 near-threshold bucket，但高优先级解释已由 conflict/suppression artifacts 覆盖，因此停止，不重开专项。
4. `601600`：只出现在 `high_score_watch`，且口径仍是观察位，因此停止。

第三步结论：

1. 本次 refresh 不满足新建专项补证条件。
2. 正确动作是记录扫描结果与 triage 结论，而不是继续扩写对象文档。

## 4. 本次刷新结果

本次 protocol run 的最终结果是：

1. 没有发现新的 clean near-threshold non-conflict 对象。
2. 扫描命中的对象全部可被现有 inventory、date matrix 与 decision tree 覆盖。
3. 因此本次刷新在 Step 2 到 Step 3 之间停止，不新增 benchmark，不新增机制样本补证，也不打开 runtime 改动。

这正是协议里定义的正常停止路径，而不是一次失败刷新。

## 5. 本次最小文档更新

本次 protocol run 后，保留的最小更新为：

1. 新增本页 run log，作为 refresh protocol 的首次实战记录。
2. 不修改 benchmark 列表。
3. 不修改 inventory、date matrix、handoff、overview 的对象归类。

## 6. 复刻步骤

下次有新 reports 到来时，按下面顺序操作即可：

1. 先运行 `scan_historical_edge_samples.py` 或调用 `scan_reports()` 获取三类 bucket 概览。
2. 把 near-threshold 与 sub-threshold 命中的 ticker/date 先对照 inventory 和 date matrix。
3. 若对象已被覆盖，直接停止，只补 run log 或状态说明。
4. 只有对象未被覆盖，且满足 `watch + bc_conflict = null + near-threshold` 时，才回到原始 `daily_events.jsonl` / `pipeline_timings.jsonl` 做最小确认。
5. 只有最小确认仍通过，才新建专项补证文档。

## 7. 当前结论

截至 `2026-03-18`，refresh protocol 的第一次实战已经证明两件事：

1. 协议可以在没有新 clean 样本时快速停止，不会把“扫描命中”误当成“新对象出现”。
2. 当前 historical edge 体系的主缺口仍然是新 clean 样本，而不是旧对象缺索引入口。

## 8. 关联文档

1. [historical-edge-refresh-protocol-20260318.md](./historical-edge-refresh-protocol-20260318.md)
2. [historical-edge-evidence-inventory-20260318.md](./historical-edge-evidence-inventory-20260318.md)
3. [historical-edge-date-coverage-matrix-20260318.md](./historical-edge-date-coverage-matrix-20260318.md)
4. [historical-edge-triage-decision-tree-20260318.md](./historical-edge-triage-decision-tree-20260318.md)
