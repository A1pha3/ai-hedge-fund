# 2026-03-18 历史 edge 总览首页

## 1. 文档目的

这页只做一件事：告诉后续接手者，在不同场景下应该先打开哪一份文档，而不是重复从总索引或全量 reports 开始找。

如果当前目标是直接接手这条线并避免误操作，可以先看 [historical-edge-handoff-note-20260318.md](./historical-edge-handoff-note-20260318.md)。
如果当前目标是刷新新一批 reports 对索引体系的影响，可以再看 [historical-edge-refresh-protocol-20260318.md](./historical-edge-refresh-protocol-20260318.md)。

## 2. 当前固定口径

先记住四条不变前提：

1. benchmark 固定为 `20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`。
2. `603993`、`300065`、`688498` 已经收口为机制样本。
3. `600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308` 已经收口为 conflict/suppression 样本。
4. `601600` 只保留观察位，不进入当前补证池。

## 3. 按场景跳转

### 场景 A：只想确认当前 benchmark 边界有没有变化

先看：

1. [historical-edge-minimal-acceptance-reading-list-20260318.md](./historical-edge-minimal-acceptance-reading-list-20260318.md)

适用问题：

1. benchmark 还是不是只有三条。
2. 600519 和 300724 的关键边界是否仍稳定。

### 场景 B：只想知道某个对象为什么被降格为机制样本

先看：

1. [historical-edge-mechanism-samples-reading-list-20260318.md](./historical-edge-mechanism-samples-reading-list-20260318.md)

适用问题：

1. 603993 为什么不是第四 benchmark。
2. 300065 为什么属于 Layer B 压线 + Layer C avoid。
3. 688498 为什么只是第三条腿缺失样本。

### 场景 C：只想知道某个对象为什么应按 conflict/suppression 排除

先看：

1. [historical-edge-conflict-suppression-reading-list-20260318.md](./historical-edge-conflict-suppression-reading-list-20260318.md)

适用问题：

1. 600988、000426、000960、300251、300775、600111、300308 为什么不应重开专项。
2. 什么时候只看 tradeoff/suppression artifact 就够了。

### 场景 D：新 ticker/date 出现了，想知道值不值得开专项

先看：

1. [historical-edge-triage-decision-tree-20260318.md](./historical-edge-triage-decision-tree-20260318.md)
2. [historical-edge-new-candidate-triage-checklist-20260318.md](./historical-edge-new-candidate-triage-checklist-20260318.md)

适用问题：

1. 这个对象是 benchmark 候选、机制样本、conflict/suppression，还是观察位。
2. 应该在哪一步停止，不继续深挖。

### 场景 E：需要总表、总入口和原始 artifacts 跳转

先看：

1. [historical-edge-artifact-index-20260318.md](./historical-edge-artifact-index-20260318.md)

适用问题：

1. 某个对象对应的原始 reports 在哪里。
2. 当前整个补证体系的分层入口是什么。

## 4. 最短工作流

如果时间很少，只按这个顺序：

1. 新对象先看 [historical-edge-triage-decision-tree-20260318.md](./historical-edge-triage-decision-tree-20260318.md)。
2. 已知 benchmark 复核先看 [historical-edge-minimal-acceptance-reading-list-20260318.md](./historical-edge-minimal-acceptance-reading-list-20260318.md)。
3. 机制样本复核看 [historical-edge-mechanism-samples-reading-list-20260318.md](./historical-edge-mechanism-samples-reading-list-20260318.md)。
4. 冲突样本复核看 [historical-edge-conflict-suppression-reading-list-20260318.md](./historical-edge-conflict-suppression-reading-list-20260318.md)。
5. 只有需要原始 artifacts 时再回到 [historical-edge-artifact-index-20260318.md](./historical-edge-artifact-index-20260318.md)。

## 5. 当前状态

截至 `2026-03-18`：

1. 当前缺的不是入口，而是新的 clean near-threshold non-conflict 一手证据。
2. 在没有新证据前，后续工作应继续维持只读索引和补证收口。
3. 不需要触碰 runtime，也不需要重开既有样本资格讨论。
