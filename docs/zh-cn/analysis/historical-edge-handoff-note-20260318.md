# 2026-03-18 历史 edge 会话交接说明

## 1. 当前阶段状态

截至 `2026-03-18`，历史 edge 扩库已经进入“索引闭环、样本暂时见顶”的状态。

当前稳定结论：

1. benchmark 仍固定为 `20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`。
2. `603993`、`300065`、`688498` 已收口为机制样本，不再作为第四 benchmark 候选。
3. `600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308` 已收口为 conflict/suppression 样本。
4. `601600` 只保留观察位，不进入当前补证池。
5. 现有 reports 范围内没有新的 clean near-threshold non-conflict 一手证据。

## 2. 当前能做的事

后续低风险动作只保留三类：

1. 继续维护只读索引与入口文档。
2. 等新的 ticker/date 自然出现后，按既有 triage 流程做分诊。
3. 在确实出现新的 clean 一手证据时，再新开专项补证文档。

如果未来是因为新 reports 到来而需要刷新整套索引，可以直接按 [historical-edge-refresh-protocol-20260318.md](./historical-edge-refresh-protocol-20260318.md) 执行。

## 3. 当前不要做的事

在没有新 clean 证据前，不应做下面这些动作：

1. 不重开 `603993`、`300065`、`688498` 的 benchmark 资格讨论。
2. 不通过放松全局 Layer C、watchlist、avoid 规则来制造新样本。
3. 不因为 isolated watch 或单一实验片段，就把对象升级为 benchmark 候选。
4. 不触碰 runtime，只继续做只读分析、文档固化和一手 evidence 复核。

## 4. 新证据出现时的最短路径

如果未来 reports 里出现新的 ticker/date，按下面顺序处理：

1. 先看 [historical-edge-triage-decision-tree-20260318.md](./historical-edge-triage-decision-tree-20260318.md)。
2. 再看 [historical-edge-new-candidate-triage-checklist-20260318.md](./historical-edge-new-candidate-triage-checklist-20260318.md)。
3. 只有对象满足 `watch + bc_conflict = null + near-threshold` 且未被 inventory 覆盖，才新开专项补证。

## 5. 需要快速复核时的入口

按问题类型跳转：

1. benchmark 边界复核：看 [historical-edge-minimal-acceptance-reading-list-20260318.md](./historical-edge-minimal-acceptance-reading-list-20260318.md)。
2. 机制样本复核：看 [historical-edge-mechanism-samples-reading-list-20260318.md](./historical-edge-mechanism-samples-reading-list-20260318.md)。
3. conflict/suppression 复核：看 [historical-edge-conflict-suppression-reading-list-20260318.md](./historical-edge-conflict-suppression-reading-list-20260318.md)。
4. 总入口与原始 artifacts：看 [historical-edge-artifact-index-20260318.md](./historical-edge-artifact-index-20260318.md)。

## 6. 下一次继续推进的触发条件

只有满足下面任一条件，才值得继续新增分析文档：

1. `historical_edge_sample_scan_20260318.json` 或后续同类扫描里出现新的 near-threshold non-conflict ticker/date。
2. 现有 inventory 无法覆盖某个新对象。
3. 原始 evidence 能跨 artifact 稳定支持 `watch + bc_conflict = null + near-threshold`。

## 7. 一句话交接

当前不是“规则不够松”，而是“新 clean 证据还没出现”；所以继续保持只读、索引化、等待新证据即可。
